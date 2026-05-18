from pydantic import BaseModel
from typing import Optional
from enum import Enum


class JobStatus(str, Enum):
    uploaded = "uploaded"
    extracting_audio = "extracting_audio"
    transcribing = "transcribing"
    summarizing = "summarizing"
    chunking = "chunking"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"


class JobState(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.uploaded
    step: Optional[str] = None
    progress: int = 0
    error: Optional[str] = None
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    # Step 2 fields
    transcript_path: Optional[str] = None
    transcript_txt_path: Optional[str] = None
    transcript_token_count: Optional[int] = None
    summary: bool = False
    summary_path: Optional[str] = None
    context_mode: Optional[str] = None  # "full_transcript" | "summary_plus_retrieval"
    # Step 3 fields
    chunk_count: Optional[int] = None
    parent_topic: Optional[str] = None
    main_topic: Optional[str] = None
    topic_confidence: Optional[str] = None  # "high" | "medium" | "low"
