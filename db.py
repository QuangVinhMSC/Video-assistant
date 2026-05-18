import os
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session

_db_url = os.environ.get("DATABASE_URL", "sqlite:///data/video_assistant.db")
engine = create_engine(_db_url, connect_args={"check_same_thread": False})


def init_db() -> None:
    import models.job  # noqa: F401 — registers JobState table metadata
    import models.conversation  # noqa: F401 — registers ConversationTurn table metadata
    if _db_url.startswith("sqlite:///data/"):
        Path("data").mkdir(exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
