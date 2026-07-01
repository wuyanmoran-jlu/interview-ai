from pydantic import BaseModel

class StartRequest(BaseModel):
    topic: str = "算法"
    difficulty: str = "中等"
    language: str = "python"

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