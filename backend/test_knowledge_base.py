"""知识库模型与题目生命周期逻辑测试。

测试策略：
- 裁决函数是纯函数，直接断言输入输出
- record_rating 是状态机核心，构造模型对象验证流转
- 种子数据文件做格式验证
"""
import json
from pathlib import Path

import pytest

from knowledge_base import (
    MIN_REVIEWS_FOR_DECISION,
    QuestionBank,
    QuestionStatus,
    decide_status,
    record_rating,
)


def make_question(status=QuestionStatus.NEW.value):
    return QuestionBank(
        title="测试题",
        description="测试描述",
        difficulty="简单",
        language="python",
        topic="算法",
        status=status,
    )


# ===== decide_status：纯函数裁决测试 =====

def test_decide_status_insufficient_reviews_stays_new():
    result = decide_status(up_count=5, down_count=4, review_count=9)
    assert result == QuestionStatus.NEW


def test_decide_status_publishes_when_up_ratio_reached():
    result = decide_status(up_count=7, down_count=3, review_count=10)
    assert result == QuestionStatus.PUBLISHED


def test_decide_status_rejects_when_down_ratio_reached():
    result = decide_status(up_count=5, down_count=5, review_count=10)
    assert result == QuestionStatus.REJECTED


def test_decide_status_middle_ground_stays_new():
    result = decide_status(up_count=6, down_count=4, review_count=10)
    assert result == QuestionStatus.NEW


def test_decide_status_empty_reviews_never_divides_by_zero():
    result = decide_status(up_count=0, down_count=0, review_count=0)
    assert result == QuestionStatus.NEW


# ===== record_rating：状态机流转测试 =====

def test_record_rating_does_not_flip_draft_status():
    question = make_question(status=QuestionStatus.DRAFT.value)
    result = record_rating(question, value=1)
    assert result == QuestionStatus.DRAFT
    assert question.up_count == 1
    assert question.review_count == 1


def test_record_rating_publishes_new_question_with_enough_good_ratings():
    question = make_question(status=QuestionStatus.NEW.value)
    for _ in range(MIN_REVIEWS_FOR_DECISION):
        record_rating(question, value=1)
    assert question.status == QuestionStatus.PUBLISHED.value
    assert question.review_count == MIN_REVIEWS_FOR_DECISION


def test_record_rating_rejects_new_question_with_enough_bad_ratings():
    question = make_question(status=QuestionStatus.NEW.value)
    for _ in range(MIN_REVIEWS_FOR_DECISION):
        record_rating(question, value=0)
    assert question.status == QuestionStatus.REJECTED.value


# ===== 模型与种子数据格式测试 =====

def test_question_to_dict_contains_public_fields():
    question = make_question()
    data = question.to_dict()
    assert data["title"] == "测试题"
    assert data["status"] == QuestionStatus.NEW.value
    assert "test_cases" not in data  # 测试用例不对外暴露


def test_seed_file_is_valid_and_marked_published():
    seed_path = Path(__file__).parent / "data" / "seed_questions.json"
    with open(seed_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    assert len(items) >= 3
    for item in items:
        assert item["title"]
        assert item["description"]
        assert item["difficulty"] in {"简单", "中等", "困难"}
        assert item["language"] in {"python", "javascript", "java", "cpp"}
        assert item["status"] == "published"
        assert isinstance(item["examples"], list)
        assert isinstance(item["test_cases"], list)
