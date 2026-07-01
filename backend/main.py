import uuid
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models import StartRequest, RunRequest, ReviewRequest, EvaluateRequest, AnswerRequest
from ai_client import chat
from code_executor import run_code
from interview_manager import create_session, get_history, add_message, clear_session

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Interview AI backend is running"}

@app.post("/interview/start")
async def start_interview(req: StartRequest):
    session_id = str(uuid.uuid4())
    create_session(session_id, req.topic, req.difficulty, req.language)
    
    # 让 AI 出第一道题
    messages = get_history(session_id) + [
        {"role": "user", "content": "请开始面试，出一道题。"}
    ]
    question = await chat(messages)
    add_message(session_id, "assistant", question)
    
    return {
        "session_id": session_id,
        "question": question
    }

@app.post("/interview/run")
async def run_user_code(req: RunRequest):
    result = await run_code(req.source_code, req.language, req.stdin)
    return result

@app.post("/interview/review")
async def review_code(req: ReviewRequest):
    lang = req.language
    result = await run_code(req.source_code, lang)
    
    # 构建消息让 AI 点评
    user_msg = (
        f"我提交了以下{lang}代码，运行结果为：\n"
        f"stdout:\n{result['stdout']}\n"
        f"stderr:\n{result['stderr']}\n"
        f"代码:\n{req.source_code}\n\n请点评。"
    )
    add_message(req.session_id, "user", user_msg)
    messages = get_history(req.session_id)
    review = await chat(messages)
    add_message(req.session_id, "assistant", review)
    
    return {
        "review": review,
        "run_result": result
    }

@app.post("/interview/answer")
async def answer_followup(req: AnswerRequest):
    add_message(req.session_id, "user", req.answer)
    messages = get_history(req.session_id)
    reply = await chat(messages)
    add_message(req.session_id, "assistant", reply)
    return {"reply": reply}

@app.post("/interview/evaluate")
async def evaluate_interview(req: EvaluateRequest):
    add_message(req.session_id, "user", "面试结束，请给出最终评分和详细评价。")
    messages = get_history(req.session_id)
    evaluation = await chat(messages)
    add_message(req.session_id, "assistant", evaluation)
    
    # 清理会话（可选）
    # clear_session(req.session_id)
    
    return {"evaluation": evaluation}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)