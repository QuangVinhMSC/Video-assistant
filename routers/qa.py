from fastapi import APIRouter, HTTPException

from models.question import AskRequest, AskResponse
from services.job_store import get_job
from services.qa import qa_pipeline

router = APIRouter()


@router.post("/ask/{job_id}", response_model=AskResponse)
def ask(job_id: str, body: AskRequest):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "ready":
        raise HTTPException(status_code=409, detail=f"Job is not ready: {job.status}")

    try:
        result = qa_pipeline(job, body.question)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return AskResponse(**result)
