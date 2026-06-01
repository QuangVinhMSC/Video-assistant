from fastapi import APIRouter, Depends, HTTPException, Request

from auth import require_api_key
from limiter import limiter
from models.question import AskRequest, AskResponse
from services.job_store import get_job
from services.history import get_conversation_history, get_turn_count, save_turn
from services.qa import qa_pipeline

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/ask/{job_id}", response_model=AskResponse)
@limiter.limit("20/minute")
def ask(request: Request, job_id: str, body: AskRequest):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "ready":
        raise HTTPException(status_code=409, detail=f"Job is not ready: {job.status}")

    history = get_conversation_history(job_id, last_n=5)

    try:
        result = qa_pipeline(job, body.question, history=history, model=body.qa_model)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    save_turn(job_id, body.question, result.get("answer", ""), result.get("confidence"))
    result["turn"] = get_turn_count(job_id)

    return AskResponse(**result)
