import os
import httpx
from dotenv import load_dotenv

load_dotenv()

JDOODLE_URL = "https://api.jdoodle.com/v1/execute"
CLIENT_ID = os.getenv("JDOODLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("JDOODLE_CLIENT_SECRET", "")

# JDoodle 语言映射：{ 简称: (JDoodle语言码, 版本序号) }
LANG_MAP = {
    "python":     ("python3",   "4"),   # Python 3.10+
    "javascript": ("nodejs",    "4"),   # Node.js 18+
    "java":       ("java",      "4"),   # Java 17
    "cpp":        ("cpp17",     "1"),   # C++17
}

async def run_code(source_code: str, language: str = "python", stdin: str = ""):
    lang, version = LANG_MAP.get(language, ("python3", "4"))

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            JDOODLE_URL,
            json={
                "clientId": CLIENT_ID,
                "clientSecret": CLIENT_SECRET,
                "script": source_code,
                "language": lang,
                "versionIndex": version,
                "stdin": stdin,
            },
        )
        data = resp.json()

        return {
            "stdout": data.get("output", ""),
            "stderr": data.get("error", ""),
            "output": data.get("output", ""),
            "code": data.get("statusCode", None),
            "signal": None,
            "cpu_time": data.get("cpuTime", ""),
            "memory": data.get("memory", ""),
        }