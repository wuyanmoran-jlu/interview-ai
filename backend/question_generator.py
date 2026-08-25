"""LLM 批量题目生成器。

让 DeepSeek 按严格 JSON 结构生成面试题，包含：
- 题面（含至少 2 个示例）
- 测试用例（stdin / expected_output，供 Judge0 实跑验证）
- 参考解法（供质检层用 Judge0 确定性验证）
"""
import json
import logging
import re

from ai_client import chat

logger = logging.getLogger("interview.kb.generate")

GENERATE_PROMPT = """你是一位资深算法题库编辑。请为{topic}方向生成{count}道{difficulty}难度的{language}编程面试题。

要求：
1. 题面清晰无歧义，必须包含至少 2 个示例用例，每个示例标注输入和期望输出。
2. 测试用例采用标准输入输出（stdin/stdout）形式，至少 3 个，覆盖边界情况。
3. 参考解法必须能通过全部测试用例，代码完整可运行。
4. 不要出偏题怪题，优先经典题型。

只输出 JSON 数组，不要输出其他任何文字。每个元素的格式：
{{
  "title": "题目标题",
  "description": "题目描述（含示例）",
  "difficulty": "{difficulty}",
  "language": "{language}",
  "topic": "{topic}",
  "tags": ["标签1", "标签2"],
  "examples": [{{"input": "示例输入", "output": "期望输出"}}],
  "test_cases": [{{"stdin": "标准输入", "expected_output": "期望输出"}}],
  "reference_solution": "参考解法完整代码"
}}"""


def _extract_json(text: str) -> list:
    """从 LLM 返回文本中提取 JSON 数组（容忍代码块包裹）。"""
    cleaned = text.strip()
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if not match:
        raise ValueError("无法从模型输出中解析 JSON 数组")
    return json.loads(match.group(0))


async def generate_questions(topic: str, difficulty: str, language: str, count: int = 5) -> list[dict]:
    """批量生成题目，返回符合题库结构的字典列表。"""
    prompt = GENERATE_PROMPT.format(
        topic=topic, difficulty=difficulty, language=language, count=count
    )
    messages = [{"role": "user", "content": prompt}]

    raw = await chat(
        messages,
        temperature=0.8,
        response_format={"type": "json_object"},
        max_tokens=4096,
    )
    items = _extract_json(raw)

    if not isinstance(items, list):
        raise ValueError("模型输出不是数组")

    # 补齐统一字段，生成题一律进入 draft 状态，来源标记为 generated
    for item in items:
        item.setdefault("source", "generated")
        item.setdefault("status", "draft")
        item.setdefault("tags", [])
        item.setdefault("test_cases", [])
    return items
