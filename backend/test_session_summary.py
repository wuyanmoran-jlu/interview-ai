import pytest

from interview_manager import build_prompt_context, generate_session_summary, trim_chat_history
from code_executor import summarize_run_result
from ai_client import get_cached_feedback, make_feedback_cache_key


def test_build_prompt_context_keeps_summary_and_recent_messages():
    history = [
        {"role": "system", "content": "base system"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {"role": "assistant", "content": "second answer"},
        {"role": "user", "content": "third question"},
        {"role": "assistant", "content": "third answer"},
        {"role": "user", "content": "fourth question"},
    ]

    context = build_prompt_context(history, summary="current summary", max_recent=4)

    assert context[0]["role"] == "system"
    assert "base system" in context[0]["content"]
    assert any(item["role"] == "system" and "current summary" in item["content"] for item in context)
    assert len(context) <= 7
    assert context[-1]["content"] == "fourth question"


def test_trim_chat_history_keeps_recent_window_and_truncates_long_messages():
    history = [
        {"role": "system", "content": "base system"},
        {"role": "user", "content": "x" * 4000},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "question 2"},
        {"role": "assistant", "content": "answer 2"},
        {"role": "user", "content": "question 3"},
        {"role": "assistant", "content": "answer 3"},
        {"role": "user", "content": "question 4"},
    ]

    trimmed = trim_chat_history(history, max_recent=4, max_message_chars=1200)

    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["content"] == "question 4"
    assert len(trimmed[-1]["content"]) <= 1200
    assert len(trimmed) <= 7


def test_summarize_run_result_extracts_error_and_status():
    result = {
        "stdout": "",
        "stderr": "Traceback (most recent call last):\n  File \"main.py\", line 7, in <module>\nIndexError: list index out of range",
        "code": 11,
        "signal": "Runtime Error (NZEC)",
        "time": "0.02",
        "memory": "12345"
    }

    summary = summarize_run_result(result)

    assert "IndexError" in summary
    assert "Runtime Error" in summary
    assert "0.02" in summary
    assert len(summary) < 500


def test_make_feedback_cache_key_is_stable_for_same_inputs():
    key1 = make_feedback_cache_key("print('x')", "python", "", "review")
    key2 = make_feedback_cache_key("print('x')", "python", "", "review")
    assert key1 == key2
    assert isinstance(key1, str)
    assert len(key1) > 0


def test_chat_budget_trims_or_returns_safe_fallback():
    from ai_client import compact_messages_for_budget

    long_messages = [
        {"role": "system", "content": "你是面试官"},
        {"role": "user", "content": "x" * 20000},
        {"role": "assistant", "content": "y" * 5000},
        {"role": "user", "content": "请根据代码给出建议"},
    ]

    compact = compact_messages_for_budget(long_messages, max_chars=4000)
    assert isinstance(compact, list)
    assert len(compact) <= 4
    assert compact[0]["role"] == "system"
    assert any("请根据代码给出建议" in msg["content"] for msg in compact)


@pytest.mark.asyncio
async def test_generate_session_summary_returns_short_text():
    history = [
        {"role": "user", "content": "请写一个二分查找题的答案"},
        {"role": "assistant", "content": "我先解释思路，然后给出代码。"},
        {"role": "user", "content": "代码有边界问题，空数组会报错"},
        {"role": "assistant", "content": "需要补充空数组和越界检查。"},
    ]

    summary = await generate_session_summary(history)

    assert isinstance(summary, str)
    assert len(summary) > 0
    assert len(summary) < 200
