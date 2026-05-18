from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class ConversationTurn(SQLModel, table=True):
    __tablename__ = "conversation_turns"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    turn: int
    question: str
    answer: str
    confidence: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
