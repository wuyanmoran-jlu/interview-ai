"""题库业务层。

- CRUD：题目增删改查
- 状态机：审核流转（draft -> new/failed、failed -> draft、new -> published/rejected、rejected -> draft）
- 检索式选题：pick_question（published 优先、低频优先、排除用户已用过的题）
- 用户已用题去重：Redis Set
- 评分统计：滚动平均更新 avg_score，供难度校准
- 看板：题库健康度统计
"""
import logging
import random
from typing import Optional, Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base import (
    QuestionBank,
    QuestionRating,
    RatingDimension,
    RubricBank,
    record_rating,
    suggest_difficulty,
)
from interview_manager import _get_redis
from question_reviewer import compare_outputs

logger = logging.getLogger("interview.kb.service")

# 人工可执行的合法状态流转
ALLOWED_TRANSITIONS = {
    "draft": {"new", "failed"},
    "failed": {"draft"},
    "new": {"published", "rejected"},
    "published": {"rejected"},
    "rejected": {"draft"},
}

USED_TTL = 60 * 60 * 24 * 30  # 用户已用题记录保留 30 天

VALID_DIMENSIONS = {d.value for d in RatingDimension}


class InvalidRatingError(Exception):
    """非法评价参数。"""


def _used_key(user_id: str) -> str:
    return f"interview:used_questions:{user_id}"


async def get_used_question_ids(user_id: str) -> set[str]:
    """获取用户已出过的题目 ID 集合（Redis）。"""
    if not user_id:
        return set()
    redis = _get_redis()
    raw = await redis.smembers(_used_key(user_id))
    return set(raw)


async def mark_question_used(user_id: str, question_id: int) -> None:
    """记录用户已使用某道题，避免短期内重复出题。"""
    if not user_id:
        return
    redis = _get_redis()
    key = _used_key(user_id)
    await redis.sadd(key, str(question_id))
    await redis.expire(key, USED_TTL)


# ===== CRUD =====

async def list_questions(
    session: AsyncSession,
    difficulty: Optional[str] = None,
    language: Optional[str] = None,
    topic: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[QuestionBank]:
    """按条件分页查询题目。"""
    stmt = select(QuestionBank).order_by(QuestionBank.id.desc()).limit(limit).offset(offset)
    if difficulty:
        stmt = stmt.where(QuestionBank.difficulty == difficulty)
    if language:
        stmt = stmt.where(QuestionBank.language == language)
    if topic:
        stmt = stmt.where(QuestionBank.topic == topic)
    if status:
        stmt = stmt.where(QuestionBank.status == status)
    return (await session.scalars(stmt)).all()


async def get_question(session: AsyncSession, question_id: int) -> Optional[QuestionBank]:
    return await session.get(QuestionBank, question_id)


async def create_question(session: AsyncSession, data: dict) -> QuestionBank:
    question = QuestionBank(**data)
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return question


async def update_question(session: AsyncSession, question_id: int, data: dict) -> Optional[QuestionBank]:
    question = await session.get(QuestionBank, question_id)
    if question is None:
        return None
    for field, value in data.items():
        if value is not None:
            setattr(question, field, value)
    await session.commit()
    await session.refresh(question)
    return question


async def delete_question(session: AsyncSession, question_id: int) -> bool:
    question = await session.get(QuestionBank, question_id)
    if question is None:
        return False
    await session.delete(question)
    await session.commit()
    return True


# ===== 状态机 =====

def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


async def set_status(session: AsyncSession, question_id: int, new_status: str) -> Optional[QuestionBank]:
    """人工审核流转，非法流转返回 None。"""
    question = await session.get(QuestionBank, question_id)
    if question is None:
        return None
    if not can_transition(question.status, new_status):
        logger.warning(
            "非法状态流转: question %s %s -> %s", question_id, question.status, new_status
        )
        return None
    question.status = new_status
    await session.commit()
    await session.refresh(question)
    return question


# ===== 检索式选题 =====

async def pick_question(
    session: AsyncSession,
    difficulty: str,
    language: str,
    topic: str,
    used_ids: Optional[set[str]] = None,
) -> Optional[QuestionBank]:
    """从题库中挑一道题。

    策略：
    1. 只选 published / new 状态的题
    2. 匹配难度、语言、方向
    3. published 优先于 new
    4. 低频题优先（usage_count 升序），取前 20 个候选随机挑一个
    5. 排除用户已用过的题
    """
    used_ids = used_ids or set()

    stmt = (
        select(QuestionBank)
        .where(
            QuestionBank.status.in_(["published", "new"]),
            QuestionBank.difficulty == difficulty,
            QuestionBank.language == language,
            QuestionBank.topic == topic,
        )
        .order_by(
            case((QuestionBank.status == "published", 0), else_=1),
            QuestionBank.usage_count.asc(),
        )
        .limit(20)
    )
    candidates = [
        q for q in (await session.scalars(stmt)).all() if str(q.id) not in used_ids
    ]
    if not candidates:
        return None

    # 低频优先的前 5 个里随机，兼顾随机性和冷题消化
    pool = candidates[:5]
    return random.choice(pool)


async def increment_usage(session: AsyncSession, question: QuestionBank) -> None:
    """题目被使用后，使用计数 +1。"""
    question.usage_count = (question.usage_count or 0) + 1
    await session.commit()


# ===== 用户评价与自动裁决 =====

async def submit_rating(
    session: AsyncSession,
    question_id: int,
    user_id: str = "",
    value: int = 1,
    dimension: str = "overall",
    comment: Optional[str] = None,
) -> Optional[dict]:
    """提交一条评价，更新统计并触发自动裁决。

    返回裁决结果（含最新状态），题目不存在时返回 None。
    """
    if value not in (0, 1):
        raise InvalidRatingError("value 只能是 0（踩）或 1（赞）")
    if dimension not in VALID_DIMENSIONS:
        raise InvalidRatingError(f"非法评价维度: {dimension}")

    question = await session.get(QuestionBank, question_id)
    if question is None:
        return None

    rating = QuestionRating(
        question_id=question_id,
        user_id=user_id,
        dimension=dimension,
        value=value,
        comment=comment,
    )
    session.add(rating)

    # 更新统计并裁决（draft/failed/rejected 状态只计数，不翻转状态）
    new_status = record_rating(question, value)
    await session.commit()

    return {
        "question_id": question_id,
        "status": new_status.value,
        "review_count": question.review_count or 0,
        "up_count": question.up_count or 0,
        "down_count": question.down_count or 0,
    }


async def list_ratings(
    session: AsyncSession, question_id: int, limit: int = 100
) -> Sequence[QuestionRating]:
    """查看某道题的评价记录（倒序）。"""
    stmt = (
        select(QuestionRating)
        .where(QuestionRating.question_id == question_id)
        .order_by(QuestionRating.id.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


# ===== 评分标准检索 =====

async def pick_rubric(
    session: AsyncSession, topic: str = "all", difficulty: str = "all"
) -> Optional[RubricBank]:
    """按方向 + 难度检索启用的评分标准，逐级回退到通用标准。

    回退顺序：
    (topic, difficulty) -> (topic, all) -> (all, difficulty) -> (all, all)
    """
    fallbacks = [
        (topic, difficulty),
        (topic, "all"),
        ("all", difficulty),
        ("all", "all"),
    ]
    for t, d in fallbacks:
        stmt = (
            select(RubricBank)
            .where(
                RubricBank.topic == t,
                RubricBank.difficulty == d,
                RubricBank.status == "active",
            )
            .order_by(RubricBank.id.desc())
            .limit(1)
        )
        rubric = await session.scalar(stmt)
        if rubric is not None:
            return rubric
    return None


# ===== 自动判题 =====

async def verify_solution_cases(
    session: AsyncSession,
    question_id: int,
    source_code: str,
    language: str,
) -> Optional[dict]:
    """用题库的隐藏测试用例判题用户代码。

    返回 {question_id, passed, total, results[]}；
    题目不存在或没有测试用例时返回 None（不可判题，前端降级为普通运行）。
    """
    from code_executor import run_code

    question = await get_question(session, question_id)
    if question is None or not question.test_cases:
        return None

    results = []
    passed = 0
    for case in question.test_cases:
        result = await run_code(source_code, language, str(case.get("stdin") or ""))
        ok = result.get("code") == 3 and compare_outputs(
            result.get("stdout") or "", str(case.get("expected_output") or "")
        )
        if ok:
            passed += 1
        results.append(
            {
                "passed": ok,
                "stdin": str(case.get("stdin") or ""),
                "expected": str(case.get("expected_output") or ""),
                "actual": str(result.get("stdout") or "").strip(),
                "signal": result.get("signal"),
            }
        )

    return {
        "question_id": question_id,
        "passed": passed,
        "total": len(question.test_cases),
        "results": results,
    }


# ===== 评分统计与难度校准 =====

async def update_avg_score(session: AsyncSession, question_id: int, score: float) -> Optional[dict]:
    """用滚动平均更新题目平均分，返回更新后的统计。

    面试评分（0~10 分制）作为难度校准的数据来源。
    """
    question = await session.get(QuestionBank, question_id)
    if question is None:
        return None

    count = question.score_count or 0
    current = question.avg_score or 0.0
    new_count = count + 1
    question.avg_score = round((current * count + score) / new_count, 2)
    question.score_count = new_count
    await session.commit()

    return {
        "avg_score": question.avg_score,
        "score_count": question.score_count,
    }


async def get_stats(session: AsyncSession) -> dict:
    """题库健康度看板统计。"""
    total = await session.scalar(select(func.count()).select_from(QuestionBank)) or 0

    by_status_rows = (
        await session.execute(
            select(QuestionBank.status, func.count()).group_by(QuestionBank.status)
        )
    ).all()
    by_status = {status: count for status, count in by_status_rows}

    by_difficulty_rows = (
        await session.execute(
            select(QuestionBank.difficulty, func.count()).group_by(QuestionBank.difficulty)
        )
    ).all()
    by_difficulty = {d: c for d, c in by_difficulty_rows}

    active = by_status.get("published", 0) + by_status.get("new", 0)
    review_total = (
        await session.scalar(select(func.coalesce(func.sum(QuestionBank.review_count), 0)))
    ) or 0
    up_total = (
        await session.scalar(select(func.coalesce(func.sum(QuestionBank.up_count), 0)))
    ) or 0
    up_ratio = round(up_total / review_total, 3) if review_total > 0 else None

    # 需要校准的题目数（有评分数据且难度标注失衡）
    calibrated = 0
    rows = (
        await session.execute(
            select(QuestionBank.difficulty, QuestionBank.avg_score)
        )
    ).all()
    for difficulty, avg_score in rows:
        if suggest_difficulty(difficulty, avg_score) is not None:
            calibrated += 1

    return {
        "total": total,
        "by_status": by_status,
        "by_difficulty": by_difficulty,
        "active": active,
        "review_total": review_total,
        "up_ratio": up_ratio,
        "needs_calibration": calibrated,
    }
