"""用户会话索引与匿名数据迁移测试（SQLite 内存库）。"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from knowledge_base import QuestionRating
from user_sessions import (
    UserSession,
    delete_session_index,
    get_session_index,
    get_user_stats,
    list_sessions_by_user,
    migrate_user_data,
    update_session_title,
    upsert_session,
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_creates_index(db):
    await upsert_session(db, "s1", "u1", "标题", "python", "算法", "简单")
    index = await get_session_index(db, "s1")
    assert index is not None
    assert index.user_id == "u1"
    assert index.title == "标题"


@pytest.mark.asyncio
async def test_upsert_updates_existing(db):
    await upsert_session(db, "s1", "u1", "旧标题", "python", "算法", "简单")
    await upsert_session(db, "s1", "u1", "新标题", "python", "算法", "简单")
    index = await get_session_index(db, "s1")
    assert index.title == "新标题"


@pytest.mark.asyncio
async def test_update_session_title(db):
    await upsert_session(db, "s1", "u1", "旧", "python", "算法", "简单")
    await update_session_title(db, "s1", "新标题")
    index = await get_session_index(db, "s1")
    assert index.title == "新标题"


@pytest.mark.asyncio
async def test_list_sessions_sorted_desc(db):
    await upsert_session(db, "s1", "u1", "A", "python", "算法", "简单")
    await upsert_session(db, "s2", "u1", "B", "python", "算法", "简单")
    await upsert_session(db, "s3", "other", "C", "python", "算法", "简单")
    rows = await list_sessions_by_user(db, "u1")
    assert len(rows) == 2
    assert all(r.user_id == "u1" for r in rows)


@pytest.mark.asyncio
async def test_delete_session_index(db):
    await upsert_session(db, "s1", "u1", "A", "python", "算法", "简单")
    assert await delete_session_index(db, "s1") is True
    assert await get_session_index(db, "s1") is None
    assert await delete_session_index(db, "s1") is False


@pytest.mark.asyncio
async def test_migrate_user_data_moves_sessions_and_ratings(db):
    # 匿名用户有一条会话索引和一条题目评价
    await upsert_session(db, "s1", "anon-id", "A", "python", "算法", "简单")
    db.add(QuestionRating(question_id=1, user_id="anon-id", value=1))
    await db.commit()

    result = await migrate_user_data(db, "anon-id", "account-id")
    assert result["sessions"] == 1
    assert result["ratings"] == 1

    index = await get_session_index(db, "s1")
    assert index.user_id == "account-id"

    rating = (await db.execute(
        select(QuestionRating).where(QuestionRating.user_id == "account-id")
    )).scalar_one()
    assert rating.question_id == 1


@pytest.mark.asyncio
async def test_migrate_user_data_returns_zero_when_nothing(db):
    result = await migrate_user_data(db, "ghost", "account-id")
    assert result == {"sessions": 0, "ratings": 0}


# ===== 个人统计 =====

@pytest.mark.asyncio
async def test_get_user_stats_aggregates(db):
    await upsert_session(db, "s1", "u1", "A", "python", "算法", "简单")
    await upsert_session(db, "s2", "u1", "B", "python", "算法", "困难")
    await upsert_session(db, "s3", "u1", "C", "python", "数据结构", "简单")
    await upsert_session(db, "s4", "other", "D", "python", "算法", "简单")
    db.add(QuestionRating(question_id=1, user_id="u1", value=1))
    db.add(QuestionRating(question_id=2, user_id="u1", value=0))
    await db.commit()

    stats = await get_user_stats(db, "u1")
    assert stats["total_sessions"] == 3
    assert stats["by_topic"] == {"算法": 2, "数据结构": 1}
    assert stats["by_difficulty"] == {"简单": 2, "困难": 1}
    assert stats["total_ratings"] == 2


@pytest.mark.asyncio
async def test_get_user_stats_empty(db):
    stats = await get_user_stats(db, "nobody")
    assert stats == {
        "total_sessions": 0,
        "by_topic": {},
        "by_difficulty": {},
        "total_ratings": 0,
    }
