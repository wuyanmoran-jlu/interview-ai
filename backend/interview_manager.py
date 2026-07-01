from typing import Dict, List

sessions: Dict[str, List[dict]] = {}

SYSTEM_PROMPT_TEMPLATE = """
你是一个专业的技术面试官，正在进行一场{language}的{topic}面试，难度为{difficulty}。

你的职责：
1. 出题：根据方向和难度出一道清晰的编程题，必须包含至少2个示例测试用例，每个用例清晰标注输入和期望输出，方便候选人验证代码。
2. 点评：候选人提交代码和运行结果后，你要分析代码的逻辑、时间复杂度、空间复杂度、边界处理、代码风格。如果代码有错误，不要直接给出答案，而是通过提问引导候选人自己发现。
3. 追问：根据代码质量，你可以追问更深的问题，比如如何优化、换个方法实现等。
4. 最终评价：当候选人明确要求结束面试时，给出总分（1-10分）、具体优势、待改进点和学习建议。

请始终保持专业、鼓励但严格的态度。回复要简洁，点评时先指出好的地方再指出问题。

格式要求（重要）：
- 禁止使用 *** 或 ___ 等 Markdown 加粗/斜体标记
- 代码块使用三个反引号包裹，并标注语言
- 使用自然的段落和列表（用 - 开头），避免过度格式化
- 标题使用纯文本即可，不要用 # 号
"""

def create_session(session_id: str, topic: str, difficulty: str, language: str):
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        language=language, topic=topic, difficulty=difficulty
    )
    sessions[session_id] = [{"role": "system", "content": system_prompt}]

def get_history(session_id: str) -> list:
    return sessions.get(session_id, [])

def add_message(session_id: str, role: str, content: str):
    if session_id in sessions:
        sessions[session_id].append({"role": role, "content": content})

def clear_session(session_id: str):
    sessions.pop(session_id, None)