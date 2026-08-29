import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

import redis.asyncio as aioredis
from dotenv import load_dotenv

from config import settings

load_dotenv()
logger = logging.getLogger("interview.session")

REDIS_URL = settings.redis_url
SESSION_TTL = 604800  # 会话过期时间：7 天
KEY_SESSION = "interview:session:"   # 对话消息
KEY_META = "interview:meta:"         # 会话元信息
KEY_SUMMARY = "interview:summary:"   # 会话摘要（压缩后的上下文）
KEY_USER = "interview:user:"         # 用户会话列表 (Sorted Set)

_pool: Optional[aioredis.ConnectionPool] = None


def _get_pool() -> aioredis.ConnectionPool:
    """懒加载 Redis 连接池（单例）"""
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            REDIS_URL,
            max_connections=10,
            decode_responses=True,
        )
    return _pool


def _get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=_get_pool())


def _msg_key(session_id: str) -> str:
    return f"{KEY_SESSION}{session_id}"


def _meta_key(session_id: str) -> str:
    return f"{KEY_META}{session_id}"


def _summary_key(session_id: str) -> str:
    return f"{KEY_SUMMARY}{session_id}"


def _user_key(user_id: str) -> str:
    return f"{KEY_USER}{user_id}"


def trim_chat_history(history: List[dict], max_recent: int = 6, max_message_chars: int = 1200) -> List[dict]:
    """限制消息数量和单条消息长度，避免长历史/长代码直接膨胀 prompt。"""
    if not history:
        return []

    system_prompt = None
    if history[0].get("role") == "system":
        system_prompt = history[0]
        recent = history[1:]
    else:
        recent = history[:]

    if len(recent) > max_recent:
        recent = recent[-max_recent:]

    trimmed: List[dict] = []
    if system_prompt is not None:
        trimmed.append({
            "role": system_prompt.get("role", "system"),
            "content": str(system_prompt.get("content", "")).strip(),
        })

    for msg in recent:
        content = str(msg.get("content", "")).strip()
        if len(content) > max_message_chars:
            content = content[:max_message_chars].rstrip() + "..."
        trimmed.append({
            "role": msg.get("role", "user"),
            "content": content,
        })
    return trimmed


def build_prompt_context(history: List[dict], summary: str = "", max_recent: int = 6) -> list[dict]:
    """按“系统提示词 + 摘要 + 近期消息”的顺序组装更短的上下文。

    这样可以避免把整段历史一次性喂给大模型，降低 token 成本与无效上下文干扰。
    """
    if not history:
        return []

    trimmed = trim_chat_history(history, max_recent=max_recent)
    kept: list[dict] = []

    if trimmed and trimmed[0].get("role") == "system":
        kept.append(trimmed[0])
        recent = trimmed[1:]
    else:
        recent = trimmed[:]

    if summary:
        kept.append({
            "role": "system",
            "content": "会话摘要：\n" + summary.strip(),
        })

    kept.extend(recent)
    return kept


def _make_title(topic: str, language: str, question_preview: str) -> str:
    """从 AI 返回的题目中取前 20 个字作为会话标题"""
    preview = question_preview.replace("\n", " ").strip()
    if len(preview) > 20:
        preview = preview[:20] + "..."
    lang_label = {"python": "Py", "javascript": "JS", "java": "Java", "cpp": "C++"}.get(language, language)
    return f"[{lang_label}] {preview}"


SYSTEM_PROMPT_TEMPLATE = """
你是一个专业的技术面试官，正在进行一场{language}的{topic}面试，难度为{difficulty}。

你的职责：
1. 出题：根据方向和难度出一道清晰的编程题，必须包含至少2个示例测试用例，每个用例清晰标注输入和期望输出，方便候选人验证代码。
2. 点评：候选人提交代码和运行结果后，你要分析代码的逻辑、时间复杂度、空间复杂度、边界处理、代码风格。如果代码有错误，不要直接给出答案，而是通过提问引导候选人自己发现。
3. 追问：根据代码质量，你可以追问更深的问题，比如如何优化、换个方法实现等。
4. 最终评价：当候选人明确要求结束面试时，严格按照评分细则对每个维度打分，并给出综合评价。

请始终保持专业、鼓励但严格的态度。回复要简洁，点评时先指出好的地方再指出问题。

格式要求（重要）：
- 禁止使用 *** 或 ___ 等 Markdown 加粗/斜体标记
- 代码块使用三个反引号包裹，并标注语言
- 使用自然的段落和列表（用 - 开头），避免过度格式化
- 标题使用纯文本即可，不要用 # 号
"""

SCORING_RUBRIC = """
## 评分细则（5 维度 × 10 分制，加权总分）

### 1. 代码正确性（权重 30%）
- 10 分：通过所有测试用例，输出完全符合预期，无逻辑错误
- 7-9 分：主要用例通过，有 1-2 个边界情况未覆盖或小瑕疵
- 4-6 分：核心思路正确但存在明显 bug，特定输入会出错
- 1-3 分：代码无法运行或逻辑严重偏离题意

### 2. 算法效率（权重 25%）
- 10 分：时间/空间复杂度均为最优解，能解释优化思路
- 7-9 分：复杂度在可接受范围（如 O(n log n) 而非 O(n²)）
- 4-6 分：能运行但使用了暴力解法，存在明显优化空间
- 1-3 分：完全没有复杂度意识，使用了指数级算法

### 3. 代码质量（权重 20%）
- 10 分：命名规范、结构清晰、函数拆分合理、有适当注释
- 7-9 分：总体清晰，个别命名或格式可改进
- 4-6 分：能读但结构混乱，变量名无意义，缺少注释
- 1-3 分：代码杂乱无章，难以阅读和维护

### 4. 边界处理（权重 15%）
- 10 分：全面处理了空输入、极值、异常数据、溢出等边界情况
- 7-9 分：考虑了主要边界，遗漏了少数极端情况
- 4-6 分：仅处理正常输入，边界情况会导致崩溃
- 1-3 分：完全没有边界处理意识

### 5. 沟通与思维（权重 10%）
- 10 分：能清晰阐述解题思路，被追问后主动改进，思路连贯
- 7-9 分：基本能表达思路，对追问有一定回应
- 4-6 分：思路模糊，回答被动，缺少独立分析
- 1-3 分：无法解释自己的代码，对追问没有有效回应

### 最终得分计算
总分 = 正确性×0.30 + 算法×0.25 + 代码质量×0.20 + 边界×0.15 + 沟通×0.10
（保留一位小数）

### 输出格式
评分时请严格按照以下格式输出：

- 正确性：X/10 — 简要说明
- 算法效率：X/10 — 简要说明
- 代码质量：X/10 — 简要说明
- 边界处理：X/10 — 简要说明
- 沟通思维：X/10 — 简要说明
- 加权总分：XX.X/10
- 优势总结：
- 待改进点：
- 学习建议：
"""

EVALUATION_PROMPT = """
面试结束。请严格按照以下评分细则，对候选人的整场面试表现进行打分。

{scoring_rubric}

注意事项：
1. 必须对 5 个维度逐个打分，不可遗漏
2. 每个分数必须有简要理由
3. 加权总分必须精确计算
4. 评价要具体，引用实际代码或对话中的例子
"""


async def create_session(session_id: str, topic: str, difficulty: str,
                         language: str, user_id: str = "", question_preview: str = "",
                         summary: str = ""):
    """创建新面试会话，写入 system prompt + 元信息 + 关联用户 + 摘要"""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        language=language, topic=topic, difficulty=difficulty
    )
    messages = [{"role": "system", "content": system_prompt}]
    redis = _get_redis()
    pipe = redis.pipeline()

    # 消息
    pipe.setex(_msg_key(session_id), SESSION_TTL,
               json.dumps(messages, ensure_ascii=False))

    # 元信息
    now = datetime.now(timezone.utc).isoformat()
    title = _make_title(topic, language, question_preview) if question_preview else f"[{language}] {topic} 面试"
    meta = {
        "title": title,
        "language": language,
        "topic": topic,
        "difficulty": difficulty,
        "created_at": now,
        "summary": summary,
    }
    pipe.setex(_meta_key(session_id), SESSION_TTL,
               json.dumps(meta, ensure_ascii=False))

    if summary:
        pipe.setex(_summary_key(session_id), SESSION_TTL, summary)

    # 关联用户
    if user_id:
        pipe.zadd(_user_key(user_id), {session_id: int(datetime.now(timezone.utc).timestamp())})
        pipe.expire(_user_key(user_id), SESSION_TTL)

    await pipe.execute()


async def get_history(session_id: str) -> list:
    """获取会话的完整对话历史"""
    redis = _get_redis()
    data = await redis.get(_msg_key(session_id))
    if data is None:
        return []
    return json.loads(data)


async def add_message(session_id: str, role: str, content: str):
    """追加一条对话记录，并重置 TTL"""
    redis = _get_redis()
    key = _msg_key(session_id)
    try:
        data = await redis.get(key)
        if data is None:
            logger.warning("add_message: session %s not found, message dropped", session_id[:8])
            return
        messages = json.loads(data)
        messages.append({"role": role, "content": content})
        await redis.setex(key, SESSION_TTL, json.dumps(messages, ensure_ascii=False))
    except redis.RedisError as e:
        logger.error("add_message failed for session %s: %s", session_id[:8], e)


async def clear_session(session_id: str):
    """删除整个会话（消息 + 元信息 + 摘要）"""
    redis = _get_redis()
    await redis.delete(_msg_key(session_id), _meta_key(session_id), _summary_key(session_id))


async def get_session_summary(session_id: str) -> str:
    """获取会话摘要（压缩后的上下文）"""
    redis = _get_redis()
    summary = await redis.get(_summary_key(session_id))
    return summary or ""


async def set_session_summary(session_id: str, summary: str):
    """写入会话摘要，并同步到元信息中"""
    if not summary:
        return
    redis = _get_redis()
    await redis.setex(_summary_key(session_id), SESSION_TTL, summary)

    meta = await get_session_meta(session_id)
    if meta is None:
        return
    meta["summary"] = summary
    await redis.setex(_meta_key(session_id), SESSION_TTL, json.dumps(meta, ensure_ascii=False))


async def generate_session_summary(history: List[dict], max_chars: int = 180) -> str:
    """从会话历史提炼出一个简短摘要，供后续推理使用。

    只保留最重要的事实：当前题目、已尝试的思路、关键问题、下一步方向。
    """
    if not history:
        return ""

    lines: List[str] = []
    recent_text = []

    for msg in history:
        role = msg.get("role")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        recent_text.append(f"{role}: {content}")

    if not recent_text:
        return ""

    for item in recent_text[-10:]:
        text = item.strip()
        if text:
            lines.append(text)

    summary = " ".join(lines)
    summary = summary.replace("\n", " ")
    summary = " ".join(summary.split())

    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."

    # 简化摘要，避免把历史全部噪声带进下一轮的 prompt
    return summary


async def get_review_round(session_id: str) -> int:
    """获取当前会话的评审轮数，默认 0。"""
    redis = _get_redis()
    raw = await redis.get(f"{_meta_key(session_id)}:review_round")
    return int(raw) if raw and raw.isdigit() else 0


async def increment_review_round(session_id: str) -> int:
    """递增会话的评审轮数并返回最新值。"""
    redis = _get_redis()
    key = f"{_meta_key(session_id)}:review_round"
    current = await get_review_round(session_id)
    next_round = current + 1
    await redis.setex(key, SESSION_TTL, str(next_round))
    return next_round


# ==================== 新增：多会话管理 ====================

async def get_session_meta(session_id: str) -> Optional[dict]:
    """获取会话元信息，并附带当前 summary（如果存在）"""
    redis = _get_redis()
    data = await redis.get(_meta_key(session_id))
    if not data:
        return None

    meta = json.loads(data)
    summary = await get_session_summary(session_id)
    if summary:
        meta["summary"] = summary
    return meta


async def get_user_sessions(user_id: str) -> list:
    """获取用户所有会话列表，按时间倒序"""
    redis = _get_redis()
    raw = await redis.zrange(_user_key(user_id), 0, -1, desc=True)
    sessions = []
    for sid in raw:
        meta = await get_session_meta(sid)
        if meta:
            sessions.append({"id": sid, **meta})
    return sessions


async def delete_session(session_id: str, user_id: str):
    """删除会话：消息 + 元信息 + 摘要 + 用户关联"""
    redis = _get_redis()
    pipe = redis.pipeline()
    pipe.delete(_msg_key(session_id))
    pipe.delete(_meta_key(session_id))
    pipe.delete(_summary_key(session_id))
    pipe.zrem(_user_key(user_id), session_id)
    await pipe.execute()