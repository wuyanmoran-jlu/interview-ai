# 后端架构文档

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| Web 框架 | **FastAPI** | 构建 RESTful API，提供异步支持和自动生成 OpenAPI 文档 |
| ASGI 服务器 | **Uvicorn** | 运行 FastAPI 应用，支持高并发异步请求 |
| 数据校验 | **Pydantic** | 定义请求/响应模型，自动校验参数类型和必填项 |
| AI 对话 | **OpenAI SDK** (兼容模式) | 连接 DeepSeek API，实现面试官的智能对话 |
| HTTP 客户端 | **httpx** (异步) | 调用 Judge0 API 在 Docker 沙箱中执行用户代码 |
| 环境变量 | **python-dotenv** | 从 `.env` 文件加载 DeepSeek、Judge0 和 Redis 配置 |
| 会话存储 | **Redis** (异步) | 持久化面试对话历史，支持 TTL 自动过期 |

---

## 文件结构

```
backend/
├── main.py              # FastAPI 应用入口，定义所有 API 接口
├── models.py            # Pydantic 请求体模型定义
├── ai_client.py         # DeepSeek AI 对话客户端
├── code_executor.py     # Judge0 在线代码执行服务（本地 Docker）
├── interview_manager.py # 面试会话管理 + Redis 存储 + AI 系统提示词
├── requirements.txt     # Python 依赖清单
├── .env                 # 环境变量（DeepSeek + Judge0 + Redis 配置）
└── README.md            # 本文档
```

---

## 各模块详解

### 1. `main.py` — 应用入口 + API 路由

创建 FastAPI 实例并配置 CORS 中间件，允许前端跨域访问。定义了 **5 个接口**：

| 方法 | 路由 | 功能 | 调用的核心函数 |
|------|------|------|---------------|
| `GET` | `/` | 健康检查 | — |
| `POST` | `/interview/start` | 开始新面试，生成会话 ID 并由 AI 出题 | `create_session()` → `chat()` |
| `POST` | `/interview/run` | 仅执行用户代码，返回运行结果 | `run_code()` |
| `POST` | `/interview/review` | 执行代码 + AI 点评，将代码和运行结果发给 AI | `run_code()` → `chat()` |
| `POST` | `/interview/answer` | 用户回复 AI 的追问，AI 继续对话 | `chat()` |
| `POST` | `/interview/evaluate` | 结束面试，AI 给出最终评分和评价 | `chat()` |

**关键设计**：
- 所有接口均为 `async`，配合异步 HTTP 客户端，避免阻塞
- 会话通过 `session_id`（UUID）串联，每个面试独立隔离
- 启动入口 `if __name__ == "__main__"` 调用 `uvicorn.run()`，监听 `0.0.0.0:8000`

### 2. `models.py` — 请求体模型

使用 Pydantic 定义 5 个请求模型，自动校验字段：

- **`StartRequest`**：`topic`（题目方向）、`difficulty`（难度）、`language`（编程语言）
- **`RunRequest`**：`session_id`、`source_code`、`language`、`stdin`（标准输入）
- **`ReviewRequest`**：`session_id`、`source_code`、`language`
- **`AnswerRequest`**：`session_id`、`answer`（用户的追问回答）
- **`EvaluateRequest`**：`session_id`

### 3. `ai_client.py` — AI 对话客户端

**技术**：使用 OpenAI 官方 SDK 的兼容模式连接 DeepSeek API。

```
加载 .env → 创建 AsyncOpenAI 客户端 → chat() 函数
```

- `chat(messages, model, temperature)`：异步调用 DeepSeek 的 `chat.completions.create`，传入完整的消息历史（含 system prompt），返回 AI 的回复文本
- API Key 和 Base URL 通过 `.env` 环境变量配置，不硬编码

### 4. `code_executor.py` — 代码执行服务

**技术**：调用 **Judge0 API**（本地 Docker 自托管代码沙箱，无需外部 API Key，无调用次数限制）。

- `run_code(source_code, language, stdin)`：将用户代码、语言、标准输入发送到 Judge0，返回运行结果
- `LANG_MAP`：将前端传的简称（如 `"cpp"`）映射为 Judge0 语言 ID（如 `54`）
- 支持的 4 种语言：**Python、JavaScript、Java、C++**
- 返回结构化结果：`stdout`、`stderr`、`output`、`code`（HTTP 状态码）、`cpu_time`、`memory`

### 5. `interview_manager.py` — 会话管理

**技术**：使用 **Redis** 持久化存储对话历史，通过 `redis.asyncio` 异步客户端操作。

- **连接池**：懒加载单例模式，`decode_responses=True` 自动解码 UTF-8
- **Key 设计**：`interview:session:{session_id}` → JSON 字符串
- **TTL**：`SESSION_TTL = 86400`（24 小时），每次 `add_message` 自动续期
- **序列化**：`json.dumps(messages, ensure_ascii=False)` 保留中文

核心数据结构（存储在 Redis 中）：
```json
[
  {"role": "system", "content": "你是专业面试官..."},
  {"role": "user", "content": "请开始面试"},
  {"role": "assistant", "content": "请实现一个..."}
]
```

提供的 4 个异步函数：
- **`create_session()`**：初始化会话，`SETEX` 写入 system prompt（根据语言/方向/难度动态生成）
- **`get_history()`**：`GET` 读取并 `json.loads` 解析对话历史
- **`add_message()`**：read-modify-write 追加消息，重置 TTL
- **`clear_session()`**：`DEL` 删除整个会话

**System Prompt 设计**：定义 AI 面试官的 4 个职责（出题、点评、追问、最终评价），并约束输出格式（禁用 `***`、代码块用反引号、避免过度格式化）。提示词根据用户选择的语言、方向、难度动态生成。

---

## 数据流示意

```
用户点击"开始面试"
  │
  ▼
POST /interview/start
  │
  ├─ create_session()          ← 初始化会话 + system prompt
  ├─ chat(messages)            ← AI 生成题目
  └─ 返回 { session_id, question }

用户编写代码，点击"运行"
  │
  ▼
POST /interview/run
  │
  ├─ run_code(code, lang, stdin)  ← Judge0 API 在 Docker 中执行代码
  └─ 返回 { stdout, stderr, ... }

用户点击"提交并获取点评"
  │
  ▼
POST /interview/review
  │
  ├─ run_code(code, lang)      ← 再次执行代码
  ├─ add_message()             ← 将代码+运行结果写入历史
  ├─ chat(messages)            ← AI 点评代码
  └─ 返回 { review, run_result }

AI 追问后，用户输入回答
  │
  ▼
POST /interview/answer
  │
  ├─ add_message()             ← 用户回答写入历史
  ├─ chat(messages)            ← AI 继续对话
  └─ 返回 { reply }

用户点击"结束面试"
  │
  ▼
POST /interview/evaluate
  │
  ├─ add_message()             ← "请给出最终评分"
  ├─ chat(messages)            ← AI 生成最终评价
  └─ 返回 { evaluation }
```

---

## 启动方式

**一键启动（推荐）**：
```powershell
.\start.ps1    # 自动启动 Redis + 后端 + 前端
.\stop.ps1     # 一键停止所有服务
```

**手动分别启动**：
```bash
# 1. 启动 Redis
cd judge0
docker-compose up -d session-redis

# 2. 启动后端
cd backend
.venv\Scripts\python.exe main.py
# 输出: Uvicorn running on http://0.0.0.0:8000

# 3. 启动前端（新终端窗口）
cd frontend
npm run dev
# 输出: http://localhost:5173
```

首次运行前需确保：
1. 创建虚拟环境并安装依赖：`pip install -r requirements.txt`
3. 确保 Docker 已启动，Judge0 容器正在运行（`localhost:2358`）
3. 确保 Redis 已启动（默认 `localhost:6379`）
