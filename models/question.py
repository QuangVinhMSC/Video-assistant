from pydantic import BaseModel
from typing import Optional


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    based_on_video: Optional[list[str]] = None
    expert_explanation: Optional[list[str]] = None
    relevant_timestamps: Optional[list[str]] = None
    search_note: Optional[str] = None
    confidence: Optional[str] = None
    used_chunks: Optional[list[str]] = None
