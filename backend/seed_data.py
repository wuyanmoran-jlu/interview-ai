"""种子数据加载：把 data/ 下的手工黄金题和评分标准导入数据库。

只导入"未出现过"的记录，避免重复执行脚本造成重复入库。
"""
import json
import logging
import os
from pathlib import Path

from sqlalchemy import select

from database import SessionLocal
from knowledge_base import QuestionBank, RubricBank

logger = logging.getLogger("interview.kb.seed")

SEED_FILE = Path(__file__).parent / "data" / "seed_questions.json"
RUBRIC_FILE = Path(__file__).parent / "data" / "rubrics.json"


def _load_json(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def load_seed_questions() -> int:
    """加载种子题目，返回新导入的数量。"""
    items = _load_json(SEED_FILE)
    inserted = 0

    async with SessionLocal() as session:
        for item in items:
            existing = await session.scalar(
                select(QuestionBank.id).where(QuestionBank.title == item["title"])
            )
            if existing is not None:
                continue

            question = QuestionBank(**item)
            session.add(question)
            inserted += 1

        await session.commit()

    logger.info("Seed questions loaded: %d new items", inserted)
    return inserted


async def load_seed_rubrics() -> int:
    """加载评分标准（双视图），按 topic+difficulty+version 去重，返回新导入数量。"""
    items = _load_json(RUBRIC_FILE)
    inserted = 0

    async with SessionLocal() as session:
        for item in items:
            existing = await session.scalar(
                select(RubricBank.id).where(
                    RubricBank.topic == item.get("topic", "all"),
                    RubricBank.difficulty == item.get("difficulty", "all"),
                    RubricBank.version == item.get("version", "v1"),
                )
            )
            if existing is not None:
                continue

            rubric = RubricBank(**item)
            session.add(rubric)
            inserted += 1

        await session.commit()

    logger.info("Seed rubrics loaded: %d new items", inserted)
    return inserted


if __name__ == "__main__":
    import asyncio

    async def main():
        q_count = await load_seed_questions()
        r_count = await load_seed_rubrics()
        print(f"Imported {q_count} question(s), {r_count} rubric(s).")

    asyncio.run(main())
