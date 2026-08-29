"""用户会话索引持久化（PostgreSQL）。

会话消息仍存 Redis（热数据、TTL），这里只持久化轻量索引：
谁（user_id）在什么时间做了哪场面试（标题/方向/难度/语言），
保证登录后历史列表永久可见。
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import DateTime, Float, String, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from knowledge_base import QuestionRating

logger = logging.getLogger("interview.sessions")


class UserSession(Base):
    """会话索引表。"""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # session_id
    # 兼容匿名 ID（user- 前缀 + UUID，41 字符）与账号 UUID（36 字符）
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(20), default="python")
    topic: Mapped[str] = mapped_column(String(30), default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="")
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 面试加权总分（0-10）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "language": self.language,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


async def upsert_session(
    session: AsyncSession,
    session_id: str,
    user_id: str,
    title: str,
    language: str,
    topic: str,
    difficulty: str,
) -> None:
    """创建或更新会话索引。"""
    existing = await session.get(UserSession, session_id)
    if existing is None:
        session.add(
            UserSession(
                id=session_id,
                user_id=user_id,
                title=title,
                language=language,
                topic=topic,
                difficulty=difficulty,
            )
        )
    else:
        existing.user_id = user_id
        existing.title = title
        existing.language = language
        existing.topic = topic
        existing.difficulty = difficulty
    await session.commit()


async def update_session_title(session: AsyncSession, session_id: str, title: str) -> None:
    """更新会话标题（索引）。"""
    existing = await session.get(UserSession, session_id)
    if existing is not None:
        existing.title = title
        await session.commit()


async def delete_session_index(session: AsyncSession, session_id: str) -> bool:
    """删除会话索引。"""
    existing = await session.get(UserSession, session_id)
    if existing is None:
        return False
    await session.delete(existing)
    await session.commit()
    return True


async def list_sessions_by_user(
    session: AsyncSession, user_id: str, limit: int = 100
) -> Sequence[UserSession]:
    """按用户查询会话索引（倒序）。"""
    stmt = (
        select(UserSession)
        .where(UserSession.user_id == user_id)
        .order_by(UserSession.created_at.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def get_session_index(session: AsyncSession, session_id: str) -> Optional[UserSession]:
    return await session.get(UserSession, session_id)


async def migrate_user_data(
    session: AsyncSession, old_user_id: str, new_user_id: str
) -> dict:
    """把匿名用户的数据迁移到账号（PG 部分）：会话索引 + 题目评价。"""
    sessions_result = await session.execute(
        update(UserSession).where(UserSession.user_id == old_user_id).values(user_id=new_user_id)
    )
    ratings_result = await session.execute(
        update(QuestionRating).where(QuestionRating.user_id == old_user_id).values(user_id=new_user_id)
    )
    await session.commit()
    return {
        "sessions": sessions_result.rowcount or 0,
        "ratings": ratings_result.rowcount or 0,
    }


async def get_user_stats(session: AsyncSession, user_id: str) -> dict:
    """用户个人统计：会话总数、方向/难度分布、题目评价数。"""
    total = (
        await session.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == user_id)
        )
    ) or 0

    topic_rows = (
        await session.execute(
            select(UserSession.topic, func.count())
            .where(UserSession.user_id == user_id)
            .group_by(UserSession.topic)
        )
    ).all()
    difficulty_rows = (
        await session.execute(
            select(UserSession.difficulty, func.count())
            .where(UserSession.user_id == user_id)
            .group_by(UserSession.difficulty)
        )
    ).all()
    rating_total = (
        await session.scalar(
            select(func.count()).select_from(QuestionRating).where(QuestionRating.user_id == user_id)
        )
    ) or 0

    return {
        "total_sessions": total,
        "by_topic": {t: c for t, c in topic_rows},
        "by_difficulty": {d: c for d, c in difficulty_rows},
        "total_ratings": rating_total,
    }


# ===== 会话评分与薄弱分析 =====

async def set_session_score(session: AsyncSession, session_id: str, score: float) -> None:
    """把面试加权总分回写到会话索引，供薄弱分析使用。"""
    existing = await session.get(UserSession, session_id)
    if existing is not None:
        existing.score = score
        await session.commit()


async def get_topic_scores(session: AsyncSession, user_id: str) -> list[dict]:
    """按方向聚合该用户带评分的会话平均分（升序返回）。"""
    rows = (
        await session.execute(
            select(
                UserSession.topic,
                func.avg(UserSession.score),
                func.count(UserSession.score),
            )
            .where(UserSession.user_id == user_id, UserSession.score.is_not(None))
            .group_by(UserSession.topic)
        )
    ).all()
    return [
        {"topic": topic, "avg_score": round(float(avg), 2), "sessions": int(cnt)}
        for topic, avg, cnt in rows
    ]


async def get_user_weaknesses(session: AsyncSession, user_id: str) -> dict:
    """薄弱方向分析：均分最低的方向排在前面。

    评分样本不足 3 场时不给出结论，避免噪声数据误导。
    """
    scores = await get_topic_scores(session, user_id)
    scored_sessions = sum(s["sessions"] for s in scores)
    if scored_sessions < 3:
        return {
            "ready": False,
            "message": "完成至少 3 场带评分的面试后，即可解锁薄弱方向分析",
            "weaknesses": [],
        }
    return {
        "ready": True,
        "weaknesses": sorted(scores, key=lambda s: s["avg_score"]),
    }
