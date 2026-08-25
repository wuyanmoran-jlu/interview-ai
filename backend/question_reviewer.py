"""题目质检管线（三层）。

1. 结构校验：纯规则，检查字段完整性（确定性）
2. 实跑验证：用 Judge0 跑参考解法 + 测试用例，逐一比对输出（确定性）
3. LLM 审题：语义层检查题意清晰度、难度匹配（非确定性，只做辅助）

三层全部通过 -> 题目可入库（status: new）
"""
import logging
import re

from ai_client import chat
from code_executor import run_code

logger = logging.getLogger("interview.kb.review")

VALID_DIFFICULTIES = {"简单", "中等", "困难"}
VALID_LANGUAGES = {"python", "javascript", "java", "cpp"}


def validate_structure(question: dict) -> list[str]:
    """第一层：结构校验，返回问题列表（空列表表示通过）。"""
    problems = []

    if not str(question.get("title", "")).strip():
        problems.append("标题为空")
    if len(str(question.get("description", "")).strip()) < 20:
        problems.append("题目描述过短")
    if question.get("difficulty") not in VALID_DIFFICULTIES:
        problems.append(f"难度非法: {question.get('difficulty')}")
    if question.get("language") not in VALID_LANGUAGES:
        problems.append(f"语言非法: {question.get('language')}")
    if not question.get("topic"):
        problems.append("方向为空")

    examples = question.get("examples") or []
    if len(examples) < 2:
        problems.append(f"示例不足 2 个（当前 {len(examples)}）")

    test_cases = question.get("test_cases") or []
    if len(test_cases) < 2:
        problems.append(f"测试用例不足 2 个（当前 {len(test_cases)}）")

    solution = str(question.get("reference_solution") or "").strip()
    if not solution:
        problems.append("缺少参考解法")

    return problems


def _normalize_output(text: str) -> str:
    """宽松化输出比较：去首尾空白、忽略逗号后空格、压平换行和连续空白。"""
    text = str(text).strip()
    text = re.sub(r",\s*", ",", text)  # [0, 1] 与 [0,1] 视为等价
    return " ".join(text.split())


def compare_outputs(actual: str, expected: str) -> bool:
    """比对实际输出与期望输出（纯函数，便于测试）。"""
    return _normalize_output(actual) == _normalize_output(expected)


async def verify_solution(question: dict) -> list[str]:
    """第二层：Judge0 实跑参考解法并逐一比对测试用例，返回失败列表。"""
    problems = []
    solution = str(question.get("reference_solution") or "").strip()
    language = question.get("language", "python")
    test_cases = question.get("test_cases") or []

    if not solution or not test_cases:
        return problems  # 结构层已经报错，这里不重复

    for idx, case in enumerate(test_cases):
        stdin = str(case.get("stdin") or "")
        expected = str(case.get("expected_output") or "")

        result = await run_code(solution, language, stdin)
        if result.get("code") != 3:  # Judge0: 3 = Accepted
            problems.append(
                f"测试用例 {idx + 1} 运行失败: {result.get('signal') or '未知错误'}"
            )
            continue

        actual = result.get("stdout") or ""
        if not compare_outputs(actual, expected):
            problems.append(
                f"测试用例 {idx + 1} 输出不符：期望 {expected!r}，实际 {actual!r}"
            )

    return problems


async def llm_review(question: dict) -> list[str]:
    """第三层：LLM 审题（语义层辅助检查）。

    只让 LLM 回答"是/否"，尽量降低其自由度，减少同源偏差带来的错误。
    """
    prompt = (
        "请作为严格审题人检查下面这道编程题，只检查三个点：\n"
        "1. 题意是否清晰无歧义？\n"
        "2. 难度标注（{difficulty}）是否与实际相符？\n"
        "3. 示例与题目描述是否一致？\n\n"
        "题目：\n{description}\n\n"
        "如果全部通过请只回复 PASS，如果有问题请只回复 FAIL 并简短说明原因。"
    ).format(difficulty=question.get("difficulty"), description=question.get("description"))

    reply = await chat([{"role": "user", "content": prompt}], temperature=0.2)
    if reply.strip().upper().startswith("PASS"):
        return []
    return [f"LLM 审题未通过: {reply.strip()[:200]}"]


async def review_question(question: dict) -> tuple[bool, list[str]]:
    """综合三层质检。返回 (是否通过, 问题列表)。"""
    problems = validate_structure(question)
    if problems:
        return False, problems

    problems += await verify_solution(question)
    if problems:
        return False, problems

    problems += await llm_review(question)
    if problems:
        return False, problems

    return True, []
