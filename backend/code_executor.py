import logging
import httpx

from config import settings

logger = logging.getLogger("interview.code_executor")


def summarize_run_result(result: dict, max_chars: int = 300) -> str:
    """将 Judge0 的完整输出压缩成适合 LLM 的简短摘要。"""
    if not result:
        return "没有执行结果。"

    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    signal = str(result.get("signal") or "").strip()
    code = result.get("code")
    runtime = str(result.get("time") or "").strip()
    memory = str(result.get("memory") or "").strip()

    parts = []
    if stderr:
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        for line in lines[:3]:
            parts.append(line)
    elif stdout:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        for line in lines[:3]:
            parts.append(line)

    if signal:
        parts.append(f"状态：{signal}")
    if code not in (None, ""):
        parts.append(f"退出码：{code}")
    if runtime:
        parts.append(f"耗时：{runtime}s")
    if memory:
        parts.append(f"内存：{memory}KB")

    summary = " | ".join(parts)
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary or "无明显输出。"


JUDGE0_URL = f"{settings.judge0_url}/submissions?base64_encoded=false&wait=true"

# Judge0 语言 ID 映射（judge0/judge0:1.13.0）
LANG_MAP = {
    "python":     71,   # Python 3.10
    "javascript": 63,   # Node.js 12
    "java":       62,   # Java 13
    "cpp":        54,   # C++ GCC 9.2
}

STATUS_MAP = {
    1:  "In Queue",
    2:  "Processing",
    3:  "Accepted",
    4:  "Wrong Answer",
    5:  "Time Limit Exceeded",
    6:  "Compilation Error",
    7:  "Runtime Error (SIGSEGV)",
    8:  "Runtime Error (SIGXFSZ)",
    9:  "Runtime Error (SIGFPE)",
    10: "Runtime Error (SIGABRT)",
    11: "Runtime Error (NZEC)",
    12: "Runtime Error (Other)",
    13: "Internal Error",
    14: "Exec Format Error",
}


async def run_code(source_code: str, language: str = "python", stdin: str = ""):
    language_id = LANG_MAP.get(language, 71)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                JUDGE0_URL,
                json={
                    "source_code": source_code,
                    "language_id": language_id,
                    "stdin": stdin,
                    # cgroup v2 兼容：开启 per-process 限制可让 isolate 不再尝试创建 cgroup
                    "enable_per_process_and_thread_time_limit": True,
                    "enable_per_process_and_thread_memory_limit": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error("Judge0 request failed: %s", e)
        return {
            "stdout": "",
            "stderr": f"Code execution service unavailable: {e}",
            "output": "",
            "code": -1,
            "signal": "Service Error",
            "time": "",
            "memory": "",
        }
    except Exception as e:
        logger.exception("Unexpected error in code execution: %s", e)
        return {
            "stdout": "",
            "stderr": f"Unexpected error: {e}",
            "output": "",
            "code": -1,
            "signal": "Internal Error",
            "time": "",
            "memory": "",
        }

    status = data.get("status", {})
    status_id = status.get("id", -1)
    status_desc = status.get("description", "")
    compile_output = data.get("compile_output") or ""

    stderr = data.get("stderr") or ""
    if compile_output:
        stderr = compile_output + "\n" + stderr
    if status_id not in (3,):
        stderr = f"[{status_desc}]" + stderr

    return {
        "stdout": data.get("stdout") or "",
        "stderr": stderr,
        "output": data.get("stdout") or "",
        "code": status_id,
        "signal": status_desc,
        "time": data.get("time") or "",
        "memory": str(data.get("memory") or ""),
    }