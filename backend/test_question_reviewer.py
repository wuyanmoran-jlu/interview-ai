"""题目质检管线测试。

重点覆盖确定性层：结构校验、输出比对、Judge0 实跑接线。
LLM 审题层（第三层）依赖外部模型，不在此测试。
"""
import pytest

from question_reviewer import (
    compare_outputs,
    review_question,
    validate_structure,
    verify_solution,
)


def good_question() -> dict:
    return {
        "title": "数组求和",
        "description": "给定一个整数数组，返回所有元素之和。" * 3,
        "difficulty": "简单",
        "language": "python",
        "topic": "算法",
        "tags": ["数组"],
        "examples": [
            {"input": "[1,2,3]", "output": "6"},
            {"input": "[4,5]", "output": "9"},
        ],
        "test_cases": [
            {"stdin": "1 2 3", "expected_output": "6"},
            {"stdin": "4 5", "expected_output": "9"},
        ],
        "reference_solution": "nums = list(map(int, input().split()))\nprint(sum(nums))",
    }


# ===== 第一层：结构校验 =====

def test_validate_structure_accepts_good_question():
    assert validate_structure(good_question()) == []


def test_validate_structure_rejects_missing_title():
    q = good_question()
    q["title"] = ""
    problems = validate_structure(q)
    assert any("标题" in p for p in problems)


def test_validate_structure_rejects_too_few_examples():
    q = good_question()
    q["examples"] = [{"input": "[1]", "output": "1"}]
    problems = validate_structure(q)
    assert any("示例不足" in p for p in problems)


def test_validate_structure_rejects_invalid_difficulty():
    q = good_question()
    q["difficulty"] = "超难"
    problems = validate_structure(q)
    assert any("难度非法" in p for p in problems)


def test_validate_structure_rejects_missing_solution():
    q = good_question()
    q["reference_solution"] = ""
    problems = validate_structure(q)
    assert any("参考解法" in p for p in problems)


# ===== 输出比对 =====

def test_compare_outputs_ignores_whitespace_differences():
    assert compare_outputs("1 2 3\n", "1 2 3") is True
    assert compare_outputs("  a   b ", "a b") is True


def test_compare_outputs_detects_real_difference():
    assert compare_outputs("6", "9") is False
    assert compare_outputs("", "9") is False


# ===== 第二层：Judge0 实跑验证（fake 外部执行器）=====

@pytest.mark.asyncio
async def test_verify_solution_passes_when_all_cases_match(monkeypatch):
    async def fake_run_code(source_code, language, stdin):
        # 模拟真实执行器：按 stdin 数字求和
        nums = [int(x) for x in stdin.split()]
        return {"code": 3, "stdout": str(sum(nums)), "stderr": "", "signal": "Accepted"}

    monkeypatch.setattr("question_reviewer.run_code", fake_run_code)
    problems = await verify_solution(good_question())
    assert problems == []


@pytest.mark.asyncio
async def test_verify_solution_reports_wrong_output(monkeypatch):
    async def fake_run_code(source_code, language, stdin):
        return {"code": 3, "stdout": "42", "stderr": "", "signal": "Accepted"}

    monkeypatch.setattr("question_reviewer.run_code", fake_run_code)
    problems = await verify_solution(good_question())
    assert any("输出不符" in p for p in problems)


@pytest.mark.asyncio
async def test_verify_solution_reports_runtime_error(monkeypatch):
    async def fake_run_code(source_code, language, stdin):
        return {"code": 11, "stdout": "", "stderr": "boom", "signal": "Runtime Error"}

    monkeypatch.setattr("question_reviewer.run_code", fake_run_code)
    problems = await verify_solution(good_question())
    assert any("运行失败" in p for p in problems)


@pytest.mark.asyncio
async def test_verify_solution_skips_when_no_solution():
    q = good_question()
    q["reference_solution"] = ""
    assert await verify_solution(q) == []


# ===== 综合管线：结构层失败时不触发下游 =====

@pytest.mark.asyncio
async def test_review_question_short_circuits_on_structure_failure(monkeypatch):
    called = {"verify": False, "llm": False}

    async def fake_verify(question):
        called["verify"] = True
        return []

    async def fake_llm(question):
        called["llm"] = True
        return []

    monkeypatch.setattr("question_reviewer.verify_solution", fake_verify)
    monkeypatch.setattr("question_reviewer.llm_review", fake_llm)

    q = good_question()
    q["title"] = ""

    ok, problems = await review_question(q)
    assert ok is False
    assert called["verify"] is False
    assert called["llm"] is False
