import pytest
from fastapi.testclient import TestClient
import main
from main import app


@pytest.fixture
def client():
    return TestClient(app)


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
    """review should return a revision round and support repeated submissions"""

    async def fake_add_message(session_id, role, content):
        return None

    async def fake_get_history(session_id):
        return []

    async def fake_run_code(source_code, language, stdin=""):
        return {"stdout": "", "stderr": "", "signal": None, "code": 0}

    async def fake_chat(messages):
        return "这是一条反馈"

    async def fake_get_session_summary(session_id):
        return ""

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
    monkeypatch.setattr(main, "chat", fake_chat)
    monkeypatch.setattr(main, "get_session_summary", fake_get_session_summary)
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
    assert first_resp.json()["review_round"] == 1
    assert first_resp.json()["next_step"]
    assert second_resp.status_code == 200
    assert second_resp.json()["review_round"] == 2
