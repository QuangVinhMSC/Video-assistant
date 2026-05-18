import os
import uuid
import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File

from auth import require_api_key
from limiter import limiter
from models.job import JobStatus
from services.job_store import create_job, get_job
from tasks.pipeline import process_video

try:
    from redis import Redis
    from rq import Queue as RQQueue
    _redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    _redis_conn = Redis.from_url(_redis_url, socket_connect_timeout=2)
    _redis_conn.ping()
    _task_queue = RQQueue(connection=_redis_conn)
    _USE_RQ = True
except Exception:
    _USE_RQ = False
    _task_queue = None
    _redis_conn = None

router = APIRouter(dependencies=[Depends(require_api_key)])

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024
TEMP_DIR = Path("temp_jobs")


def _enqueue_or_thread(fn, *args) -> None:
    if _USE_RQ:
        try:
            _task_queue.enqueue(fn, *args, job_timeout=600)
            return
        except Exception:
            pass
    threading.Thread(target=fn, args=args, daemon=True).start()


@router.post("/upload")
@limiter.limit("5/minute")
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    job_id = uuid.uuid4().hex
    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_path = job_dir / f"video{ext}"
    size = 0
    with video_path.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE_BYTES:
                video_path.unlink(missing_ok=True)
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(status_code=413, detail="File exceeds maximum allowed size")
            f.write(chunk)

    create_job(job_id, str(video_path), str(job_dir))
    _enqueue_or_thread(process_video, job_id, str(video_path), str(job_dir))

    return {"job_id": job_id, "status": JobStatus.uploaded}


@router.get("/status/{job_id}")
@limiter.limit("60/minute")
def get_status(request: Request, job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
