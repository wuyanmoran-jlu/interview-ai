import json
import re

import pytest
from fastapi.testclient import TestClient
import main
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def _parse_meta(sse_text):
    """从 SSE 文本中解析 meta 事件的 JSON。"""
    match = re.search(r"event: meta\ndata: (.*)\n", sse_text)
    assert match, f"未找到 meta 事件: {sse_text[:200]}"
    return json.loads(match.group(1))


def test_root_health_check(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Interview AI backend is running"


def test_start_interview_invalid_body(client):
    """Invalid field types should return 422"""
    resp = client.post("/interview/start", json={"topic": 123, "difficulty": []})
    # Pydantic validates types — invalid types cause 422
    assert resp.status_code == 422


def test_run_code_no_session_ok(client):
    """run endpoint should accept any session_id format"""
    resp = client.post("/interview/run", json={
        "session_id": "test-123",
        "source_code": "print('hello')",
        "language": "python",
    })
    # Judge0 may not be running, but endpoint itself should respond
    assert resp.status_code in (200, 500, 502, 503)


def test_review_endpoint_returns_round_info_and_allows_repeated_submissions(client, monkeypatch):
    """review 应为 SSE 流：meta 事件携带轮数与运行结果，delta 事件携带增量文本"""

    async def fake_add_message(session_id, role, content):
        return None

    async def fake_get_history(session_id):
        return []

    async def fake_run_code(source_code, language, stdin=""):
        return {"stdout": "", "stderr": "", "signal": None, "code": 0}

    async def fake_chat_stream(messages):
        yield "这是"
        yield "一条反馈"

    async def fake_get_session_summary(session_id):
        return ""

    async def fake_get_session_meta(session_id):
        return None

    async def fake_set_session_summary(session_id, summary):
        return None

    async def fake_generate_session_summary(history):
        return "摘要"

    async def fake_get_cached_feedback(source_code, language, stdin="", stage="review"):
        return None

    # 轮数存储层的轻量 fake：模拟真实递增语义
    rounds = {}

    async def fake_get_review_round(session_id):
        return rounds.get(session_id, 0)

    async def fake_increment_review_round(session_id):
        rounds[session_id] = rounds.get(session_id, 0) + 1
        return rounds[session_id]

    monkeypatch.setattr(main, "add_message", fake_add_message)
    monkeypatch.setattr(main, "get_history", fake_get_history)
    monkeypatch.setattr(main, "run_code", fake_run_code)
    monkeypatch.setattr(main, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(main, "get_session_summary", fake_get_session_summary)
    monkeypatch.setattr(main, "get_session_meta", fake_get_session_meta)
    monkeypatch.setattr(main, "set_session_summary", fake_set_session_summary)
    monkeypatch.setattr(main, "generate_session_summary", fake_generate_session_summary)
    monkeypatch.setattr(main, "get_cached_feedback", fake_get_cached_feedback)
    monkeypatch.setattr(main, "get_review_round", fake_get_review_round)
    monkeypatch.setattr(main, "increment_review_round", fake_increment_review_round)

    first_resp = client.post("/interview/review", json={
        "session_id": "review-round-session",
        "source_code": "print('hello')",
        "language": "python",
    })
    second_resp = client.post("/interview/review", json={
        "session_id": "review-round-session",
        "source_code": "print('hello again')",
        "language": "python",
    })

    assert first_resp.status_code == 200
    assert "text/event-stream" in first_resp.headers["content-type"]
    first_text = first_resp.text
    # 增量以独立 delta 事件逐段发送
    assert '"delta": "这是"' in first_text
    assert '"delta": "一条反馈"' in first_text
    meta1 = _parse_meta(first_text)
    assert meta1["review_round"] == 1
    assert meta1["next_step"]
    assert "run_result" in meta1

    meta2 = _parse_meta(second_resp.text)
    assert second_resp.status_code == 200
    assert meta2["review_round"] == 2


def test_verify_endpoint_unavailable_without_question(client, monkeypatch):
    """LLM 生成题（无 question_id）时返回 available=false"""

    async def fake_get_session_meta(session_id):
        return {}

    monkeypatch.setattr(main, "get_session_meta", fake_get_session_meta)

    resp = client.post("/interview/verify", json={
        "session_id": "no-question-session",
        "source_code": "print(1)",
        "language": "python",
    })
    assert resp.status_code == 200
    assert resp.json() == {"available": False}


def test_verify_endpoint_returns_verdict(client, monkeypatch):
    """有题库题时返回判题结果"""

    async def fake_get_session_meta(session_id):
        return {"question_id": 1}

    async def fake_verify_solution_cases(session, question_id, source_code, language):
        return {"question_id": question_id, "passed": 2, "total": 3, "results": []}

    monkeypatch.setattr(main, "get_session_meta", fake_get_session_meta)
    monkeypatch.setattr(main, "verify_solution_cases", fake_verify_solution_cases)

    resp = client.post("/interview/verify", json={
        "session_id": "bank-question-session",
        "source_code": "print(1)",
        "language": "python",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["passed"] == 2
    assert data["total"] == 3
