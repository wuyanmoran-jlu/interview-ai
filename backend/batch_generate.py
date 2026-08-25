"""批量生成 + 质检 + 入库流水线。

流程：
    按组合（方向 × 难度 × 语言）批量生成题目
    -> 每道题走三层质检（结构 / Judge0 实跑 / LLM 审题）
    -> 通过者以 status=new 入库（纯生成题库，无人工黄金题，质检三重通过是强信号）
    -> 未通过者记录原因，不落库

用法：
    python batch_generate.py --topics 算法 数据结构 --difficulties 简单 --languages python --count 3
"""
import argparse
import asyncio
import logging

from sqlalchemy import select

from database import init_db, SessionLocal
from knowledge_base import QuestionBank
from question_generator import generate_questions
from question_reviewer import review_question

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("interview.kb.batch")


async def save_question(item: dict) -> bool:
    """质检通过的题目以 new 状态入库；同标题已存在则跳过。"""
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(QuestionBank.id).where(QuestionBank.title == item["title"])
        )
        if existing is not None:
            return False

        question = QuestionBank(
            title=item["title"],
            description=item["description"],
            difficulty=item["difficulty"],
            language=item["language"],
            topic=item["topic"],
            tags=item.get("tags") or [],
            examples=item.get("examples") or [],
            test_cases=item.get("test_cases") or [],
            reference_solution=item.get("reference_solution"),
            source=item.get("source", "generated"),
            status="new",  # 质检三重通过是强信号，直接进入新题池
        )
        session.add(question)
        await session.commit()
        return True


async def run_batch(topics, difficulties, languages, count) -> dict:
    """批量执行，返回统计结果。"""
    await init_db()
    stats = {"generated": 0, "passed": 0, "rejected": 0}

    for topic in topics:
        for difficulty in difficulties:
            for language in languages:
                logger.info("生成组合: %s / %s / %s", topic, difficulty, language)
                try:
                    items = await generate_questions(topic, difficulty, language, count)
                except Exception as e:
                    logger.error("生成失败: %s", e)
                    continue

                stats["generated"] += len(items)
                for item in items:
                    ok, problems = await review_question(item)
                    if ok:
                        saved = await save_question(item)
                        if saved:
                            stats["passed"] += 1
                            logger.info("通过: %s", item["title"])
                        else:
                            logger.info("跳过（同标题已存在）: %s", item["title"])
                    else:
                        stats["rejected"] += 1
                        logger.warning(
                            "拒绝: %s -> %s",
                            item.get("title", "无标题"),
                            "; ".join(problems),
                        )

    return stats


def main():
    parser = argparse.ArgumentParser(description="批量生成并质检面试题")
    parser.add_argument("--topics", nargs="+", default=["算法", "数据结构"])
    parser.add_argument("--difficulties", nargs="+", default=["简单"])
    parser.add_argument("--languages", nargs="+", default=["python"])
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()

    stats = asyncio.run(
        run_batch(args.topics, args.difficulties, args.languages, args.count)
    )
    print(f"生成 {stats['generated']} 道，通过 {stats['passed']} 道，拒绝 {stats['rejected']} 道")


if __name__ == "__main__":
    main()
