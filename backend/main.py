import json
import logging
import re
import uuid
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from models import (StartRequest, RunRequest, ReviewRequest, EvaluateRequest,
                    AnswerRequest, QuestionCreate, QuestionUpdate, QuestionStatusUpdate,
                    QuestionRatingCreate)
from ai_client import chat, get_cached_feedback, cache_feedback
from code_executor import run_code, summarize_run_result
from database import get_session
from interview_manager import (create_session, get_history, add_message,
                               clear_session, get_user_sessions, get_session_meta,
                               delete_session, SCORING_RUBRIC, EVALUATION_PROMPT,
                               get_review_round, increment_review_round,
                               get_session_summary, set_session_summary,
                               generate_session_summary, build_prompt_context)
from kb_service import (
    list_questions, get_question, create_question, update_question,
    delete_question, set_status, pick_question, increment_usage,
    get_used_question_ids, mark_question_used,
    submit_rating, list_ratings, InvalidRatingError, pick_rubric,
    update_avg_score, get_stats,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("interview")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )

@app.get("/")
def read_root():
    return {"message": "Interview AI backend is running"}

@app.post("/interview/start")
async def start_interview(req: StartRequest, session: AsyncSession = Depends(get_session)):
    session_id = str(uuid.uuid4())
    # 先创建会话（含 system prompt + 元信息）
    await create_session(session_id, req.topic, req.difficulty,
                         req.language, req.user_id, "")

    # 优先从题库检索（published/new），命中则直接使用，节省 LLM 调用
    used_ids = await get_used_question_ids(req.user_id)
    picked = await pick_question(
        session, req.difficulty, req.language, req.topic, used_ids
    )

    if picked is not None:
        question_text = picked.description
        await increment_usage(session, picked)
        await mark_question_used(req.user_id, picked.id)
        source, question_id = "bank", picked.id
        await add_message(session_id, "assistant", question_text)
        logger.info("出题来源=题库 id=%s", question_id)
    else:
        # 题库未命中，降级为 LLM 生成。
        # 不回写题库：自由文本缺少结构化测试用例，直接入库会污染题库；
        # 批量扩充题库走 batch_generate.py 专用流水线。
        history = await get_history(session_id)
        summary = await get_session_summary(session_id)
        messages = build_prompt_context(history, summary=summary, max_recent=6) + [
            {"role": "user", "content": "请开始面试，出一道题。"}
        ]
        question_text = await chat(messages)
        await add_message(session_id, "assistant", question_text)
        source, question_id = "generated", None
        logger.info("出题来源=LLM 生成（题库未命中）")

    generated_summary = await generate_session_summary(await get_history(session_id))
    await set_session_summary(session_id, generated_summary)

    # 用题目文本更新会话标题
    from interview_manager import _get_redis, _meta_key, _make_title, SESSION_TTL
    redis = _get_redis()
    meta_key = _meta_key(session_id)
    meta_raw = await redis.get(meta_key)
    if meta_raw:
        meta = json.loads(meta_raw)
        meta["title"] = _make_title(req.topic, req.language, question_text)
        if question_id is not None:
            meta["question_id"] = question_id
            meta["question_source"] = source
        await redis.setex(meta_key, SESSION_TTL, json.dumps(meta, ensure_ascii=False))

    return {
        "session_id": session_id,
        "question": question_text,
        "question_id": question_id,
        "source": source,
    }

@app.post("/interview/run")
async def run_user_code(req: RunRequest):
    result = await run_code(req.source_code, req.language, req.stdin)
    return result

@app.post("/interview/review")
async def review_code(req: ReviewRequest):
    lang = req.language
    result = await run_code(req.source_code, lang)

    review_round = await get_review_round(req.session_id)
    review_round += 1
    await increment_review_round(req.session_id)

    # 构建消息让 AI 点评：只保留关键输出摘要，不再把完整 stdout/stderr 拼进 prompt
    execution_summary = summarize_run_result(result)
    user_msg = (
        f"这是第 {review_round} 轮修改反馈。\n"
        f"我提交了以下{lang}代码，运行结果摘要为：\n{execution_summary}\n"
        f"代码:\n{req.source_code}\n\n请点评。"
    )
    cached_review = await get_cached_feedback(req.source_code, lang, "", "review")
    if cached_review:
        review = cached_review
    else:
        await add_message(req.session_id, "user", user_msg)
        history = await get_history(req.session_id)
        summary = await get_session_summary(req.session_id)
        messages = build_prompt_context(history, summary=summary, max_recent=6)
        review = await chat(messages)
        await add_message(req.session_id, "assistant", review)
        cache_feedback(req.source_code, lang, "", "review", review)

    updated_history = await get_history(req.session_id)
    new_summary = await generate_session_summary(updated_history)
    await set_session_summary(req.session_id, new_summary)

    return {
        "review": review,
        "run_result": result,
        "review_round": review_round,
        "next_step": "你可以继续修改代码并再次提交进行下一轮反馈。"
    }

@app.post("/interview/answer")
async def answer_followup(req: AnswerRequest):
    await add_message(req.session_id, "user", req.answer)
    history = await get_history(req.session_id)
    summary = await get_session_summary(req.session_id)
    messages = build_prompt_context(history, summary=summary, max_recent=6)
    reply = await chat(messages)
    await add_message(req.session_id, "assistant", reply)

    updated_history = await get_history(req.session_id)
    new_summary = await generate_session_summary(updated_history)
    await set_session_summary(req.session_id, new_summary)
    return {"reply": reply}

@app.post("/interview/evaluate")
async def evaluate_interview(req: EvaluateRequest, session: AsyncSession = Depends(get_session)):
    # 根据会话方向/难度从知识库检索评分标准（考官版），未命中则回退内置标准
    meta = await get_session_meta(req.session_id)
    topic = (meta or {}).get("topic", "all") or "all"
    difficulty = (meta or {}).get("difficulty", "all") or "all"

    rubric = await pick_rubric(session, topic, difficulty)
    scoring_rubric = rubric.llm_view if rubric and rubric.llm_view else SCORING_RUBRIC

    eval_msg = EVALUATION_PROMPT.format(scoring_rubric=scoring_rubric)
    await add_message(req.session_id, "user", eval_msg)
    history = await get_history(req.session_id)
    summary = await get_session_summary(req.session_id)
    messages = build_prompt_context(history, summary=summary, max_recent=6)
    evaluation = await chat(messages)
    await add_message(req.session_id, "assistant", evaluation)

    updated_history = await get_history(req.session_id)
    new_summary = await generate_session_summary(updated_history)
    await set_session_summary(req.session_id, new_summary)

    # 从评分报告中提取加权总分，回写题库用于难度校准
    question_id = (meta or {}).get("question_id")
    if question_id is not None:
        match = re.search(r"加权总分[：:]\s*(\d+(?:\.\d+)?)", evaluation)
        if match:
            score = float(match.group(1))
            await update_avg_score(session, question_id, score)
            logger.info("题目 %s 评分回写: %.2f", question_id, score)

    return {"evaluation": evaluation, "rubric": SCORING_RUBRIC}


@app.get("/interview/rubric")
async def get_rubric(session: AsyncSession = Depends(get_session)):
    """返回评分细则的用户版（成长导向），供前端展示。"""
    rubric = await pick_rubric(session, "all", "all")
    user_view = rubric.user_view if rubric and rubric.user_view else SCORING_RUBRIC
    return {"rubric": user_view}

# ==================== 多会话管理 ====================

@app.get("/interview/sessions")
async def list_sessions(user_id: str):
    """返回用户所有会话列表"""
    sessions = await get_user_sessions(user_id)
    return {"sessions": sessions}


@app.get("/interview/session/{session_id}")
async def load_session(session_id: str):
    """加载指定会话的完整消息 + 元信息"""
    messages = await get_history(session_id)
    meta = await get_session_meta(session_id)
    return {"session_id": session_id, "messages": messages, "meta": meta}


@app.delete("/interview/session/{session_id}")
async def remove_session(session_id: str, user_id: str):
    """删除一个会话"""
    await delete_session(session_id, user_id)
    return {"ok": True}


# ==================== 知识库管理 ====================

@app.get("/kb/questions")
async def kb_list_questions(
    difficulty: str = None,
    language: str = None,
    topic: str = None,
    status: str = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """按条件分页查询题目。"""
    questions = await list_questions(
        session, difficulty, language, topic, status, limit, offset
    )
    return {"questions": [q.to_dict() for q in questions]}


@app.post("/kb/questions")
async def kb_create_question(req: QuestionCreate, session: AsyncSession = Depends(get_session)):
    """新增题目（人工导入），默认 draft。"""
    question = await create_question(session, req.model_dump())
    return question.to_dict()


@app.get("/kb/questions/{question_id}")
async def kb_get_question(question_id: int, session: AsyncSession = Depends(get_session)):
    """题目详情。"""
    question = await get_question(session, question_id)
    if question is None:
        return JSONResponse(status_code=404, content={"error": "题目不存在"})
    return question.to_dict()


@app.put("/kb/questions/{question_id}")
async def kb_update_question(
    question_id: int, req: QuestionUpdate, session: AsyncSession = Depends(get_session)
):
    """更新题目。"""
    question = await update_question(session, question_id, req.model_dump(exclude_none=True))
    if question is None:
        return JSONResponse(status_code=404, content={"error": "题目不存在"})
    return question.to_dict()


@app.patch("/kb/questions/{question_id}/status")
async def kb_set_status(
    question_id: int, req: QuestionStatusUpdate, session: AsyncSession = Depends(get_session)
):
    """人工审核流转（draft->new/failed 等）。"""
    question = await set_status(session, question_id, req.status)
    if question is None:
        return JSONResponse(status_code=400, content={"error": "状态流转非法或题目不存在"})
    return question.to_dict()


@app.delete("/kb/questions/{question_id}")
async def kb_delete_question(question_id: int, session: AsyncSession = Depends(get_session)):
    """删除题目。"""
    ok = await delete_question(session, question_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "题目不存在"})
    return {"ok": True}


@app.post("/kb/questions/{question_id}/rating")
async def kb_rate_question(
    question_id: int,
    req: QuestionRatingCreate,
    session: AsyncSession = Depends(get_session),
):
    """提交题目评价（赞/踩），自动触发转正/踢出裁决。"""
    try:
        result = await submit_rating(
            session, question_id, req.user_id, req.value, req.dimension, req.comment
        )
    except InvalidRatingError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    if result is None:
        return JSONResponse(status_code=404, content={"error": "题目不存在"})
    return result


@app.get("/kb/questions/{question_id}/ratings")
async def kb_list_ratings(
    question_id: int, limit: int = 100, session: AsyncSession = Depends(get_session)
):
    """查看某道题的评价记录。"""
    ratings = await list_ratings(session, question_id, limit)
    return {
        "ratings": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "dimension": r.dimension,
                "value": r.value,
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in ratings
        ]
    }


@app.get("/kb/stats")
async def kb_stats(session: AsyncSession = Depends(get_session)):
    """题库健康度看板。"""
    return await get_stats(session)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)