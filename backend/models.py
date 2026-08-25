from pydantic import BaseModel
from typing import Optional


class StartRequest(BaseModel):
    topic: str = "算法"
    difficulty: str = "中等"
    language: str = "python"
    user_id: str = ""


class RunRequest(BaseModel):
    session_id: str
    source_code: str
    language: str = "python"
    stdin: str = ""


class ReviewRequest(BaseModel):
    session_id: str
    source_code: str
    language: str = "python"


class EvaluateRequest(BaseModel):
    session_id: str


class AnswerRequest(BaseModel):
    session_id: str
    answer: str


# ===== 多会话管理 =====

class SessionItem(BaseModel):
    id: str
    title: str
    language: str
    topic: str
    difficulty: str
    created_at: str


class SessionListResponse(BaseModel):
    sessions: list[SessionItem]


class SessionDetailResponse(BaseModel):
    session_id: str
    messages: list[dict]
    meta: Optional[dict] = None


# ===== 知识库管理 =====

class QuestionCreate(BaseModel):
    title: str
    description: str
    difficulty: str = "简单"
    language: str = "python"
    topic: str = "算法"
    tags: list = []
    examples: list = []
    test_cases: list = []
    reference_solution: Optional[str] = None
    source: str = "manual"
    status: str = "draft"


class QuestionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    difficulty: Optional[str] = None
    language: Optional[str] = None
    topic: Optional[str] = None
    tags: Optional[list] = None
    examples: Optional[list] = None
    test_cases: Optional[list] = None
    reference_solution: Optional[str] = None


class QuestionStatusUpdate(BaseModel):
    status: str


class QuestionRatingCreate(BaseModel):
    user_id: str = ""
    value: int = 1          # 1=赞，0=踩
    dimension: str = "overall"  # clarity / difficulty / test_cases / overall
    comment: Optional[str] = None