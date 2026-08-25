"""题库业务层测试（SQLite 内存库，不依赖 PostgreSQL）。

覆盖：CRUD、状态机流转、检索式选题（published 优先 / 排除已用 / 低频排序）。
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from kb_service import (
    InvalidRatingError,
    can_transition,
    create_question,
    delete_question,
    get_question,
    get_stats,
    increment_usage,
    list_questions,
    list_ratings,
    pick_question,
    pick_rubric,
    set_status,
    submit_rating,
    update_avg_score,
    update_question,
)
from knowledge_base import (
    MIN_REVIEWS_FOR_DECISION,
    QuestionBank,
    QuestionRating,
    RubricBank,
    suggest_difficulty,
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


def qdata(title="测试题", status="draft", difficulty="简单", language="python",
          topic="算法", usage_count=0):
    return {
        "title": title,
        "description": "给定一个数组返回其和。" * 5,
        "difficulty": difficulty,
        "language": language,
        "topic": topic,
        "tags": ["数组"],
        "examples": [{"input": "[1]", "output": "1"}, {"input": "[2]", "output": "2"}],
        "test_cases": [{"stdin": "1", "expected_output": "1"}],
        "status": status,
        "usage_count": usage_count,
    }


# ===== CRUD =====

@pytest.mark.asyncio
async def test_create_and_get_question(db):
    created = await create_question(db, qdata())
    fetched = await get_question(db, created.id)
    assert fetched is not None
    assert fetched.title == "测试题"
    assert fetched.status == "draft"


@pytest.mark.asyncio
async def test_list_questions_filters_by_status(db):
    await create_question(db, qdata(title="A", status="draft"))
    await create_question(db, qdata(title="B", status="published"))
    result = await list_questions(db, status="published")
    assert [q.title for q in result] == ["B"]


@pytest.mark.asyncio
async def test_update_question_only_changes_provided_fields(db):
    created = await create_question(db, qdata())
    updated = await update_question(db, created.id, {"title": "新标题"})
    assert updated.title == "新标题"
    assert updated.difficulty == "简单"


@pytest.mark.asyncio
async def test_delete_question(db):
    created = await create_question(db, qdata())
    assert await delete_question(db, created.id) is True
    assert await get_question(db, created.id) is None
    assert await delete_question(db, 999) is False


# ===== 状态机 =====

def test_can_transition_rules():
    assert can_transition("draft", "new") is True
    assert can_transition("draft", "failed") is True
    assert can_transition("new", "published") is True
    assert can_transition("rejected", "draft") is True
    assert can_transition("draft", "published") is False  # 必须经 new
    assert can_transition("published", "draft") is False  # 不能回退草稿


@pytest.mark.asyncio
async def test_set_status_valid_transition(db):
    created = await create_question(db, qdata())
    moved = await set_status(db, created.id, "new")
    assert moved.status == "new"


@pytest.mark.asyncio
async def test_set_status_rejects_invalid_transition(db):
    created = await create_question(db, qdata())
    result = await set_status(db, created.id, "published")  # draft 不能直接 published
    assert result is None
    fetched = await get_question(db, created.id)
    assert fetched.status == "draft"


# ===== 检索式选题 =====

@pytest.mark.asyncio
async def test_pick_question_returns_none_when_bank_empty(db):
    assert await pick_question(db, "简单", "python", "算法", set()) is None


@pytest.mark.asyncio
async def test_pick_question_excludes_used_ids(db):
    q1 = await create_question(db, qdata(title="已用", status="published"))
    result = await pick_question(db, "简单", "python", "算法", {str(q1.id)})
    assert result is None


@pytest.mark.asyncio
async def test_pick_question_ignores_draft_and_rejected(db):
    await create_question(db, qdata(title="草稿", status="draft"))
    await create_question(db, qdata(title="被踢", status="rejected"))
    result = await pick_question(db, "简单", "python", "算法", set())
    assert result is None


@pytest.mark.asyncio
async def test_pick_question_prefers_published_then_low_usage(monkeypatch, db):
    # published 高频 vs published 低频 vs new 低频
    await create_question(db, qdata(title="pub高", status="published", usage_count=100))
    pub_low = await create_question(db, qdata(title="pub低", status="published", usage_count=0))
    await create_question(db, qdata(title="new低", status="new", usage_count=0))

    captured = {}

    def fake_choice(pool):
        captured["pool"] = pool
        return pool[0]

    monkeypatch.setattr("kb_service.random.choice", fake_choice)
    result = await pick_question(db, "简单", "python", "算法", set())

    pool = captured["pool"]
    # published 优先，同状态低频优先
    assert [q.title for q in pool] == ["pub低", "pub高", "new低"]
    assert result.id == pub_low.id


@pytest.mark.asyncio
async def test_pick_question_filters_by_dimensions(db):
    await create_question(db, qdata(difficulty="困难"))
    await create_question(db, qdata(language="java"))
    await create_question(db, qdata(topic="数据库"))
    result = await pick_question(db, "简单", "python", "算法", set())
    assert result is None  # 没有匹配 简单/python/算法 的题


@pytest.mark.asyncio
async def test_increment_usage(db):
    created = await create_question(db, qdata())
    await increment_usage(db, created)
    fetched = await get_question(db, created.id)
    assert fetched.usage_count == 1


# ===== 评价与自动裁决 =====

@pytest.mark.asyncio
async def test_submit_rating_records_and_returns_stats(db):
    created = await create_question(db, qdata(status="new"))
    result = await submit_rating(db, created.id, user_id="u1", value=1)
    assert result["question_id"] == created.id
    assert result["up_count"] == 1
    assert result["review_count"] == 1
    assert result["status"] == "new"  # 冷启动未满，保持 new

    ratings = await list_ratings(db, created.id)
    assert len(ratings) == 1
    assert ratings[0].user_id == "u1"
    assert ratings[0].value == 1


@pytest.mark.asyncio
async def test_auto_publish_after_enough_upvotes(db):
    created = await create_question(db, qdata(status="new"))
    for i in range(MIN_REVIEWS_FOR_DECISION):
        await submit_rating(db, created.id, user_id=f"u{i}", value=1)
    fetched = await get_question(db, created.id)
    assert fetched.status == "published"


@pytest.mark.asyncio
async def test_auto_reject_after_enough_downvotes(db):
    created = await create_question(db, qdata(status="new"))
    for i in range(MIN_REVIEWS_FOR_DECISION):
        await submit_rating(db, created.id, user_id=f"u{i}", value=0)
    fetched = await get_question(db, created.id)
    assert fetched.status == "rejected"


@pytest.mark.asyncio
async def test_rating_on_draft_counts_but_does_not_flip_status(db):
    created = await create_question(db, qdata(status="draft"))
    await submit_rating(db, created.id, value=1)
    fetched = await get_question(db, created.id)
    assert fetched.status == "draft"
    assert fetched.review_count == 1


@pytest.mark.asyncio
async def test_submit_rating_invalid_dimension_raises(db):
    created = await create_question(db, qdata(status="new"))
    with pytest.raises(InvalidRatingError):
        await submit_rating(db, created.id, value=1, dimension="nonsense")


@pytest.mark.asyncio
async def test_submit_rating_invalid_value_raises(db):
    created = await create_question(db, qdata(status="new"))
    with pytest.raises(InvalidRatingError):
        await submit_rating(db, created.id, value=5)


@pytest.mark.asyncio
async def test_submit_rating_missing_question_returns_none(db):
    assert await submit_rating(db, 999, value=1) is None


# ===== 评分标准检索 =====

async def add_rubric(db, topic="all", difficulty="all", version="v1", status="active"):
    rubric = RubricBank(
        topic=topic,
        difficulty=difficulty,
        version=version,
        dimensions=[],
        llm_view="考官版标准",
        user_view="用户版说明",
        status=status,
    )
    db.add(rubric)
    await db.commit()
    await db.refresh(rubric)
    return rubric


@pytest.mark.asyncio
async def test_pick_rubric_returns_none_when_empty(db):
    assert await pick_rubric(db, "算法", "简单") is None


@pytest.mark.asyncio
async def test_pick_rubric_exact_match_preferred(db):
    generic = await add_rubric(db, "all", "all")
    specific = await add_rubric(db, "算法", "简单")
    result = await pick_rubric(db, "算法", "简单")
    assert result.id == specific.id


@pytest.mark.asyncio
async def test_pick_rubric_falls_back_to_topic_level(db):
    topic_level = await add_rubric(db, "算法", "all")
    result = await pick_rubric(db, "算法", "困难")
    assert result.id == topic_level.id


@pytest.mark.asyncio
async def test_pick_rubric_falls_back_to_generic(db):
    generic = await add_rubric(db, "all", "all")
    result = await pick_rubric(db, "数据库", "简单")
    assert result.id == generic.id


@pytest.mark.asyncio
async def test_pick_rubric_ignores_inactive(db):
    inactive = await add_rubric(db, "all", "all", status="inactive")
    result = await pick_rubric(db, "算法", "简单")
    assert result is None


# ===== 评分统计与难度校准 =====

def test_suggest_difficulty_rules():
    assert suggest_difficulty("简单", 4.0) == "偏难：建议上调为中等"
    assert suggest_difficulty("中等", 3.5) == "偏难：建议上调为困难"
    assert suggest_difficulty("中等", 8.5) == "偏易：建议下调为简单"
    assert suggest_difficulty("困难", 7.5) == "偏易：建议下调为中等"
    assert suggest_difficulty("简单", 7.0) is None  # 简单题高分正常
    assert suggest_difficulty("中等", 6.0) is None
    assert suggest_difficulty("困难", 5.0) is None  # 困难题低分正常
    assert suggest_difficulty("简单", None) is None  # 无数据不提示


@pytest.mark.asyncio
async def test_update_avg_score_running_average(db):
    created = await create_question(db, qdata())
    await update_avg_score(db, created.id, 8.0)
    result = await update_avg_score(db, created.id, 6.0)
    assert result["score_count"] == 2
    assert result["avg_score"] == 7.0  # (8+6)/2

    fetched = await get_question(db, created.id)
    assert fetched.avg_score == 7.0
    assert fetched.score_count == 2


@pytest.mark.asyncio
async def test_update_avg_score_missing_question_returns_none(db):
    assert await update_avg_score(db, 999, 5.0) is None


@pytest.mark.asyncio
async def test_get_stats_aggregates(db):
    await create_question(db, qdata(title="A", status="published", difficulty="简单"))
    await create_question(db, qdata(title="B", status="new", difficulty="中等"))
    await create_question(db, qdata(title="C", status="draft", difficulty="困难"))

    stats = await get_stats(db)
    assert stats["total"] == 3
    assert stats["by_status"] == {"published": 1, "new": 1, "draft": 1}
    assert stats["active"] == 2
    assert stats["review_total"] == 0
    assert stats["up_ratio"] is None


@pytest.mark.asyncio
async def test_get_stats_counts_calibration_needs(db):
    q1 = await create_question(db, qdata(title="简单难", status="published", difficulty="简单"))
    q2 = await create_question(db, qdata(title="困难易", status="published", difficulty="困难"))
    await update_avg_score(db, q1.id, 3.0)   # 简单题均分低 -> 需要校准
    await update_avg_score(db, q2.id, 9.0)   # 困难题均分高 -> 需要校准

    stats = await get_stats(db)
    assert stats["needs_calibration"] == 2


@pytest.mark.asyncio
async def test_to_dict_exposes_difficulty_hint(db):
    q = await create_question(db, qdata(difficulty="简单"))
    await update_avg_score(db, q.id, 3.0)
    fetched = await get_question(db, q.id)
    data = fetched.to_dict()
    assert data["difficulty_hint"] == "偏难：建议上调为中等"
    assert data["avg_score"] == 3.0
