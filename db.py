import os
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session

_db_url = os.environ.get("DATABASE_URL", "sqlite:///data/video_assistant.db")
engine = create_engine(_db_url, connect_args={"check_same_thread": False})


_NEW_COLUMNS = {
    "model_summarize": "VARCHAR NOT NULL DEFAULT 'gpt-5.5'",
    "model_topic": "VARCHAR NOT NULL DEFAULT 'gpt-4o-mini'",
    "model_frame_caption": "VARCHAR NOT NULL DEFAULT 'gpt-4o'",
    "model_frame_reconcile": "VARCHAR NOT NULL DEFAULT 'gpt-4o-mini'",
    "openai_api_key": "VARCHAR",
}


def init_db() -> None:
    import models.job  # noqa: F401 — registers JobState table metadata
    import models.conversation  # noqa: F401 — registers ConversationTurn table metadata
    if _db_url.startswith("sqlite:///data/"):
        Path("data").mkdir(exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _migrate_jobs_table()


def _migrate_jobs_table() -> None:
    with engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(jobs)").fetchall()}
        for col, col_def in _NEW_COLUMNS.items():
            if col not in existing:
                conn.exec_driver_sql(f"ALTER TABLE jobs ADD COLUMN {col} {col_def}")
        conn.commit()


def get_session() -> Session:
    return Session(engine)
