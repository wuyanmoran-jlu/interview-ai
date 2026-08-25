import asyncio
import hashlib
import logging
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

_FEEDBACK_CACHE = {}


def compact_messages_for_budget(messages: list[dict], max_chars: int = 6000) -> list[dict]:
    """裁剪超长 prompt，确保发送给 LLM 的文本长度在预算内。"""
    compact: list[dict] = []
    total = 0

    for msg in reversed(messages):
        content = str(msg.get("content", ""))
        if not content:
            continue

        if len(content) > 1200:
            content = content[:1200].rstrip() + "..."

        if total + len(content) > max_chars:
            continue

        compact.insert(0, {"role": msg.get("role", "user"), "content": content})
        total += len(content)

    return compact


def make_feedback_cache_key(source_code: str, language: str, stdin: str = "", stage: str = "review") -> str:
    """为重复的代码反馈请求生成稳定缓存 key。"""
    raw = f"{stage}:{language}:{stdin}:{source_code.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_cached_feedback(source_code: str, language: str, stdin: str = "", stage: str = "review"):
    """若同一代码状态已评审过，则直接复用结果，避免重复调用大模型。"""
    key = make_feedback_cache_key(source_code, language, stdin, stage)
    return _FEEDBACK_CACHE.get(key)


def cache_feedback(source_code: str, language: str, stdin: str = "", stage: str = "review", content: str = ""):
    """保存反馈结果到内存缓存。"""
    if not content:
        return
    key = make_feedback_cache_key(source_code, language, stdin, stage)
    _FEEDBACK_CACHE[key] = content

load_dotenv()
logger = logging.getLogger("interview.ai")

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    timeout=30.0,
    max_retries=2,
)

async def chat(messages: list[dict], model="deepseek-chat", temperature=0.7, response_format=None, max_tokens=1024):
    bounded_messages = compact_messages_for_budget(messages)

    kwargs = {
        "model": model,
        "messages": bounded_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    for attempt in range(3):
        try:
            resp = await client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            if not content or not content.strip():
                return "当前上下文较复杂，无法给出有效反馈，请稍后再试。"
            return content
        except Exception as e:
            logger.warning("AI call attempt %d failed: %s", attempt + 1, e)
            if attempt == 2:
                return "模型当前不可用，已触发安全兜底。请稍后重试或检查运行环境。"
            await asyncio.sleep(2 ** attempt)