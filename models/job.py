from typing import Optional
from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field


class JobStatus(str, Enum):
    uploaded = "uploaded"
    extracting_audio = "extracting_audio"
    extracting_frames = "extracting_frames"
    running_ocr = "running_ocr"
    captioning_frames = "captioning_frames"
    transcribing = "transcribing"
    summarizing = "summarizing"
    chunking = "chunking"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"


class JobState(SQLModel, table=True):
    __tablename__ = "jobs"

    job_id: str = Field(primary_key=True)
    status: str = "uploaded"
    step: Optional[str] = None
    progress: int = 0
    error: Optional[str] = None
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    frames_index_path: Optional[str] = None
    job_dir: Optional[str] = None
    # Step 2
    transcript_path: Optional[str] = None
    transcript_txt_path: Optional[str] = None
    transcript_token_count: Optional[int] = None
    summary: bool = False
    summary_path: Optional[str] = None
    context_mode: Optional[str] = None
    # Step 3
    chunk_count: Optional[int] = None
    parent_topic: Optional[str] = None
    main_topic: Optional[str] = None
    topic_confidence: Optional[str] = None
    # Step 5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
