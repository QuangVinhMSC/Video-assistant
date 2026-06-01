import logging
from pathlib import Path

from models.job import JobStatus
from services.job_store import update_job, fail_job, get_job
from services.extractor import extract_audio, extract_frames
from services.frame_ocr import run_ocr
from services.frame_captioner import caption_frames
from services.transcriber import transcribe, count_tokens
from services.summarizer import summarize
from services.chunker import chunk_transcript, attach_frames_to_chunks
from services.frame_reconciler import reconcile_chunks
from services.vector_store import embed_and_store
from services.topic_extractor import extract_topics


def process_video(job_id: str, video_path: str, job_dir: str) -> None:
    audio_path = str(Path(job_dir) / "audio.wav")

    job_config = get_job(job_id)
    model_summarize = job_config.model_summarize
    model_topic = job_config.model_topic
    model_frame_caption = job_config.model_frame_caption
    model_frame_reconcile = job_config.model_frame_reconcile

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

    update_job(job_id, audio_path=audio_path, progress=25)

    update_job(job_id, status=JobStatus.extracting_frames, step="extracting_frames", progress=28)
    try:
        index_path = extract_frames(job_id, video_path, job_dir)
        update_job(job_id, frames_index_path=index_path, progress=33)
    except RuntimeError as e:
        logging.warning(f"Frame extraction failed for {job_id}: {e}")
        update_job(job_id, frames_index_path=None, progress=33)
        index_path = None

    if index_path:
        update_job(job_id, status=JobStatus.running_ocr, step="running_ocr", progress=34)
        try:
            run_ocr(index_path)
        except Exception as e:
            logging.warning(f"OCR pass failed for {job_id}: {e}")

        update_job(job_id, status=JobStatus.captioning_frames, step="captioning_frames", progress=36)
        try:
            caption_frames(index_path, model=model_frame_caption)
        except Exception as e:
            logging.warning(f"Caption pass failed for {job_id}: {e}")

    update_job(job_id, status=JobStatus.transcribing, step="transcribing", progress=35)

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

    if needs_summary:
        update_job(job_id, status=JobStatus.summarizing, step="summarizing", progress=65)
        try:
            summary_path = summarize(transcript_text, job_dir, model=model_summarize)
        except RuntimeError as e:
            fail_job(job_id, "summarizing", str(e))
            return
        update_job(job_id, summary_path=summary_path, progress=75)

    update_job(job_id, status=JobStatus.chunking, step="chunking", progress=80)

    try:
        chunks = chunk_transcript(json_path)
    except RuntimeError as e:
        fail_job(job_id, "chunking", str(e))
        return

    if index_path:
        try:
            chunks = attach_frames_to_chunks(chunks, index_path)
        except Exception as e:
            logging.warning(f"Frame attachment failed for {job_id}: {e}")
        try:
            chunks = reconcile_chunks(chunks, model=model_frame_reconcile)
        except Exception as e:
            logging.warning(f"Visual reconciliation failed for {job_id}: {e}")

    try:
        embed_and_store(job_id, chunks)
    except RuntimeError as e:
        fail_job(job_id, "embedding", f"Embedding failed: {e}")
        return

    update_job(job_id, chunk_count=len(chunks), progress=88)
    update_job(job_id, status=JobStatus.embedding, step="embedding", progress=90)

    job = get_job(job_id)
    if job.context_mode == "summary_plus_retrieval" and job.summary_path:
        context_text = Path(job.summary_path).read_text(encoding="utf-8")
    else:
        context_text = Path(txt_path).read_text(encoding="utf-8")

    try:
        topics = extract_topics(context_text, model=model_topic)
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
