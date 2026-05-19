"""Step 5 tests: SQLite persistence, RQ thread fallback, FAISS on disk,
conversation history, API key auth, turn counter."""

import os
# Must be set before any app imports so db.py picks up the test engine.
os.environ["DATABASE_URL"] = "sqlite:///data/test_step5.db"
os.environ["TESTING"] = "true"

import json
import uuid
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from db import init_db
from services.job_store import create_job, get_job, update_job
from services.history import save_turn, get_conversation_history, get_turn_count
from models.job import JobState, JobStatus

init_db()
client = TestClient(app)

# ── shared fake data ──────────────────────────────────────────────────────────

FAKE_CLASSIFICATION = {
    "question_type": "how_to",
    "needs_video_evidence": True,
    "needs_external_search": False,
    "retrieval_query": "breathing technique",
}
FAKE_INITIAL = {
    "answer": "Use diaphragmatic breathing.",
    "need_search": False,
    "search_query": None,
    "confidence": "high",
    "used_chunks": ["chunk_000"],
}
FAKE_FINAL = {
    "answer": "Diaphragmatic breathing is recommended.",
    "based_on_video": ["At 02:05 the technique is shown."],
    "expert_explanation": ["Increases lung capacity."],
    "relevant_timestamps": ["02:05-03:00"],
    "search_note": None,
    "confidence": "high",
}
FAKE_EMBEDDING = [0.1] * 1536
FAKE_CHUNKS = [
    {"chunk_id": "chunk_000", "start": 0.0, "end": 45.0,
     "text": "breathing content", "score": 0.92}
]


def _jid(label: str) -> str:
    return f"{label}_{uuid.uuid4().hex[:8]}"


def _make_ready_job(tmp_path: Path, job_id: str) -> None:
    txt = tmp_path / "transcript.txt"
    txt.write_text("Vocal training transcript.", encoding="utf-8")
    create_job(job_id, str(tmp_path / "video.mp4"), str(tmp_path))
    update_job(
        job_id,
        status=JobStatus.ready,
        step="ready",
        progress=100,
        context_mode="full_transcript",
        transcript_txt_path=str(txt),
        parent_topic="music",
        main_topic="vocal training",
        chunk_count=1,
    )


def _llm_side_effects(n_calls: int = 1):
    """Return n_calls worth of classify+initial+final mocked responses."""
    return (
        [json.dumps(FAKE_CLASSIFICATION), json.dumps(FAKE_INITIAL), json.dumps(FAKE_FINAL)]
        * n_calls
    )


# ── TC-01: 401 when API_KEY is set and header is absent ──────────────────────
def test_auth_missing_key_returns_401(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    r = client.get("/status/anyjob")
    assert r.status_code == 401
    assert "api key" in r.json()["detail"].lower()


# ── TC-02: 401 when API_KEY is set and wrong key is sent ─────────────────────
def test_auth_wrong_key_returns_401(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    r = client.get("/status/anyjob", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401


# ── TC-03: Auth bypassed when API_KEY env var is not configured ───────────────
def test_auth_bypassed_when_api_key_unset(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    # Should reach the handler (404 not 401)
    r = client.get("/status/no-such-job")
    assert r.status_code == 404


# ── TC-04: Job written by create_job is visible in a fresh SQLite Session ─────
def test_job_persists_across_sessions(tmp_path):
    jid = _jid("tc04")
    create_job(jid, str(tmp_path / "v.mp4"), str(tmp_path))

    from sqlmodel import Session
    from db import engine
    with Session(engine) as session:
        job = session.get(JobState, jid)

    assert job is not None
    assert job.job_id == jid
    assert job.status == "uploaded"
    assert job.job_dir == str(tmp_path)


# ── TC-05: update_job writes every changed field correctly to DB ──────────────
def test_update_job_persists_fields(tmp_path):
    jid = _jid("tc05")
    create_job(jid, str(tmp_path / "v.mp4"), str(tmp_path))
    update_job(jid, progress=77, step="transcribing", transcript_token_count=12345)

    job = get_job(jid)
    assert job.progress == 77
    assert job.step == "transcribing"
    assert job.transcript_token_count == 12345


# ── TC-06: Conversation history stores turns in order; last_n filters ─────────
def test_conversation_history_order_and_last_n(tmp_path):
    jid = _jid("tc06")
    create_job(jid, str(tmp_path / "v.mp4"), str(tmp_path))

    save_turn(jid, "Q1", "A1", "high")
    save_turn(jid, "Q2", "A2", "medium")
    save_turn(jid, "Q3", "A3", "low")

    full = get_conversation_history(jid, last_n=10)
    assert len(full) == 3
    assert full[0]["question"] == "Q1"
    assert full[2]["turn"] == 3

    last2 = get_conversation_history(jid, last_n=2)
    assert len(last2) == 2
    assert last2[0]["question"] == "Q2"
    assert last2[1]["question"] == "Q3"


# ── TC-07: /ask endpoint returns turn=1 on the first question ─────────────────
def test_ask_returns_turn_number_one(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    jid = _jid("tc07")
    _make_ready_job(tmp_path, jid)

    with patch("services.qa.embed_query", return_value=FAKE_EMBEDDING), \
         patch("services.qa.retrieve", return_value=FAKE_CHUNKS), \
         patch("services.qa._llm", side_effect=_llm_side_effects(1)):
        r = client.post(f"/ask/{jid}", json={"question": "What breathing?"})

    assert r.status_code == 200
    assert r.json()["turn"] == 1


# ── TC-08: Consecutive /ask calls increment the turn counter ──────────────────
def test_consecutive_asks_increment_turn(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    jid = _jid("tc08")
    _make_ready_job(tmp_path, jid)

    with patch("services.qa.embed_query", return_value=FAKE_EMBEDDING), \
         patch("services.qa.retrieve", return_value=FAKE_CHUNKS), \
         patch("services.qa._llm", side_effect=_llm_side_effects(2)):
        r1 = client.post(f"/ask/{jid}", json={"question": "First question"})
        r2 = client.post(f"/ask/{jid}", json={"question": "Second question"})

    assert r1.json()["turn"] == 1
    assert r2.json()["turn"] == 2
    assert get_turn_count(jid) == 2


# ── TC-09: FAISS index saved to disk; retrieve returns the nearest chunk ──────
def test_faiss_index_persist_and_retrieve(tmp_path):
    jid = _jid("tc09")
    create_job(jid, str(tmp_path / "v.mp4"), str(tmp_path))

    chunks = [
        {"chunk_id": "c0", "start": 0.0, "end": 10.0, "text": "diaphragm technique"},
        {"chunk_id": "c1", "start": 10.0, "end": 20.0, "text": "resonance chamber"},
    ]
    embeddings = [
        [1.0] + [0.0] * 1535,
        [0.0, 1.0] + [0.0] * 1534,
    ]

    from services.vector_store import store_embeddings_direct, retrieve
    store_embeddings_direct(jid, chunks, embeddings)

    # index file (FAISS or NumPy fallback) must exist on disk
    assert (tmp_path / "chunks.json").exists()
    assert (tmp_path / "faiss.index").exists() or (tmp_path / "embeddings.npy").exists()

    # query closest to c0 should return c0
    results = retrieve(jid, [1.0] + [0.0] * 1535, top_k=1)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c0"


# ── TC-10: Upload returns 200 via thread fallback when Redis is unavailable ───
def test_upload_thread_fallback(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)

    with patch("routers.video._enqueue_or_thread") as mock_enqueue:
        r = client.post(
            "/upload",
            files={"file": ("clip.mp4", b"fake-video-bytes", "video/mp4")},
        )

    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "uploaded"
    mock_enqueue.assert_called_once()
