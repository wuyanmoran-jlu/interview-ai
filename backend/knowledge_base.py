"""知识库 ORM 模型与题目生命周期逻辑。

包含三张表：
- QuestionBank：题目库（含状态机字段）
- QuestionRating：用户评价
- RubricBank：评分标准（双视图：LLM 版 + 用户版）

题目状态机：
    draft -> (LLM 质检) -> new | failed
    new   -> (用户评价裁决) -> published | rejected | 保持 new
    published -> (长期差评) -> 可降级
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from database import Base


class QuestionStatus(str, Enum):
    """题目状态枚举。"""

    DRAFT = "draft"          # 草稿：LLM 生成/人工导入，待质检
    FAILED = "failed"        # 质检未通过
    NEW = "new"              # 新题：已过质检，待用户验证
    PUBLISHED = "published"  # 转正：评价达标，长期入库
    REJECTED = "rejected"    # 踢出：差评过多


class RatingDimension(str, Enum):
    """评价维度。"""

    CLARITY = "clarity"          # 题意清晰度
    DIFFICULTY = "difficulty"    # 难度匹配度
    TEST_CASES = "test_cases"    # 测试用例完备性
    OVERALL = "overall"          # 总体评价


# 冷启动裁决阈值（可配置）
MIN_REVIEWS_FOR_DECISION = 10  # 至少收集 10 条评价才自动裁决
PUBLISH_UP_RATIO = 0.70        # 好评率 >= 70% 转正
REJECT_DOWN_RATIO = 0.50       # 差评率 >= 50% 踢出


class QuestionBank(Base):
    """题库表。"""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    examples: Mapped[list] = mapped_column(JSON, default=list)
    test_cases: Mapped[list] = mapped_column(JSON, default=list)
    reference_solution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual / generated
    status: Mapped[str] = mapped_column(String(20), default=QuestionStatus.DRAFT.value, index=True)

    # 使用与评价统计（用于难度校准和自动裁决）
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_count: Mapped[int] = mapped_column(Integer, default=0)  # 有效评分次数（面试评价，非赞踩）
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    up_count: Mapped[int] = mapped_column(Integer, default=0)
    down_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        """序列化为普通字典，供 API 返回。"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "difficulty": self.difficulty,
            "language": self.language,
            "topic": self.topic,
            "tags": self.tags,
            "examples": self.examples,
            "reference_solution": self.reference_solution,
            "source": self.source,
            "status": self.status,
            "usage_count": self.usage_count,
            "avg_score": self.avg_score,
            "score_count": self.score_count or 0,
            "difficulty_hint": suggest_difficulty(self.difficulty, self.avg_score),
            "review_count": self.review_count,
            "up_count": self.up_count,
            "down_count": self.down_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class QuestionRating(Base):
    """用户对题目的评价表。"""

    __tablename__ = "question_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dimension: Mapped[str] = mapped_column(String(20), default=RatingDimension.OVERALL.value)
    value: Mapped[int] = mapped_column(Integer, default=1)  # 1=赞，0=踩
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RubricBank(Base):
    """评分标准表（双视图：给 LLM 的考官版 + 给用户的成长版）。"""

    __tablename__ = "rubrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(30), default="all", index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="all", index=True)
    version: Mapped[str] = mapped_column(String(20), default="v1")
    dimensions: Mapped[list] = mapped_column(JSON, default=list)  # 维度定义 + 权重
    llm_view: Mapped[str] = mapped_column(Text, default="")       # 考官版 prompt
    user_view: Mapped[str] = mapped_column(Text, default="")      # 用户版说明
    status: Mapped[str] = mapped_column(String(20), default="active")  # active / inactive
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def decide_status(up_count: int, down_count: int, review_count: int) -> QuestionStatus:
    """根据评价数据裁决题目状态（纯函数，便于测试）。

    规则：
    - 评价数不足 MIN_REVIEWS_FOR_DECISION：保持 new
    - 好评率 >= PUBLISH_UP_RATIO：published
    - 差评率 >= REJECT_DOWN_RATIO：rejected
    - 其余：保持 new（继续观察）
    """
    # 防御式处理：未落库的模型字段可能为 None
    up_count = up_count or 0
    down_count = down_count or 0
    review_count = review_count or 0

    if review_count < MIN_REVIEWS_FOR_DECISION:
        return QuestionStatus.NEW

    if review_count <= 0:
        return QuestionStatus.NEW

    up_ratio = up_count / review_count
    down_ratio = down_count / review_count

    if up_ratio >= PUBLISH_UP_RATIO:
        return QuestionStatus.PUBLISHED
    if down_ratio >= REJECT_DOWN_RATIO:
        return QuestionStatus.REJECTED
    return QuestionStatus.NEW


def suggest_difficulty(difficulty: str, avg_score: Optional[float]) -> Optional[str]:
    """根据题目历史平均分判断难度标注是否失衡。

    返回建议文案；无数据或标注合理时返回 None。
    阈值设定：简单题平均分低 -> 实际偏难；困难题平均分高 -> 实际偏易。
    """
    if avg_score is None:
        return None

    if difficulty == "简单" and avg_score < 5.0:
        return "偏难：建议上调为中等"
    if difficulty == "中等" and avg_score < 4.0:
        return "偏难：建议上调为困难"
    if difficulty == "中等" and avg_score > 8.0:
        return "偏易：建议下调为简单"
    if difficulty == "困难" and avg_score > 7.0:
        return "偏易：建议下调为中等"
    return None


def record_rating(question: QuestionBank, value: int) -> QuestionStatus:
    """记录一条评价到题目统计中，并返回新的裁决状态。

    value: 1=赞, 0=踩
    """
    # 未落库时列默认值尚未生效，这里做 None 防护
    up = question.up_count or 0
    down = question.down_count or 0
    reviews = question.review_count or 0

    if value >= 1:
        question.up_count = up + 1
    else:
        question.down_count = down + 1
    question.review_count = reviews + 1

    if question.status in (QuestionStatus.NEW.value, QuestionStatus.PUBLISHED.value):
        decision = decide_status(
            question.up_count,
            question.down_count,
            question.review_count,
        )
        question.status = decision.value
        return decision
    return QuestionStatus(question.status)
