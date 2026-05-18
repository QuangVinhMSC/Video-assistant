import uuid
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from models.job import JobStatus
from services.job_store import create_job, get_job, update_job, fail_job
from services.extractor import extract_audio, extract_frames
from services.transcriber import transcribe, count_tokens
from services.summarizer import summarize
from services.chunker import chunk_transcript
from services.vector_store import embed_and_store
from services.topic_extractor import extract_topics

router = APIRouter()

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
TEMP_DIR = Path("temp_jobs")


@router.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
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

    create_job(job_id, str(video_path))
    background_tasks.add_task(process_video, job_id, str(video_path), str(job_dir))

    return {"job_id": job_id, "status": JobStatus.uploaded}


@router.get("/status/{job_id}")
def get_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def process_video(job_id: str, video_path: str, job_dir: str):
    audio_path = str(Path(job_dir) / "audio.wav")

    update_job(job_id, status=JobStatus.extracting_audio, step="extracting_audio", progress=10)
    try:
        extract_audio(video_path, audio_path)
    except RuntimeError as e:
        error = str(e)
        if "no audio" in error.lower() or "does not contain" in error.lower():
            fail_job(job_id, "extracting_audio", "No audio stream detected in the uploaded video")
        else:
            fail_job(job_id, "extracting_audio", f"Audio extraction failed: {error}")
        return

    update_job(job_id, audio_path=audio_path, progress=30)
    extract_frames(job_id, video_path)

    update_job(job_id, status=JobStatus.transcribing, step="transcribing", progress=35)

    # Step 2 — transcription
    try:
        json_path, txt_path = transcribe(audio_path, job_dir)
    except RuntimeError as e:
        fail_job(job_id, "transcribing", str(e))
        return

    transcript_text = Path(txt_path).read_text(encoding="utf-8")
    token_count = count_tokens(transcript_text)

    needs_summary = token_count > 20_000
    context_mode = "summary_plus_retrieval" if needs_summary else "full_transcript"

    update_job(
        job_id,
        transcript_path=json_path,
        transcript_txt_path=txt_path,
        transcript_token_count=token_count,
        summary=needs_summary,
        context_mode=context_mode,
        progress=60,
    )

    # Step 2 — summarization (only when transcript is too long)
    if needs_summary:
        update_job(job_id, status=JobStatus.summarizing, step="summarizing", progress=65)
        try:
            summary_path = summarize(transcript_text, job_dir)
        except RuntimeError as e:
            fail_job(job_id, "summarizing", str(e))
            return
        update_job(job_id, summary_path=summary_path, progress=75)

    update_job(job_id, status=JobStatus.chunking, step="chunking", progress=80)

    # Step 3 — chunking
    try:
        chunks = chunk_transcript(json_path)
    except RuntimeError as e:
        fail_job(job_id, "chunking", str(e))
        return

    # Step 3 — embedding
    try:
        embed_and_store(job_id, chunks)
    except RuntimeError as e:
        fail_job(job_id, "embedding", f"Embedding failed: {e}")
        return

    update_job(job_id, chunk_count=len(chunks), progress=88)
    update_job(job_id, status=JobStatus.embedding, step="embedding", progress=90)

    # Step 3 — topic extraction
    job = get_job(job_id)
    if job.context_mode == "summary_plus_retrieval" and job.summary_path:
        context_text = Path(job.summary_path).read_text(encoding="utf-8")
    else:
        context_text = Path(txt_path).read_text(encoding="utf-8")

    try:
        topics = extract_topics(context_text)
    except RuntimeError as e:
        fail_job(job_id, "embedding", str(e))
        return

    update_job(
        job_id,
        parent_topic=topics.get("parent_topic"),
        main_topic=topics.get("main_topic"),
        topic_confidence=topics.get("confidence"),
        progress=98,
    )
    update_job(job_id, status=JobStatus.ready, step="ready", progress=100)
