import os
os.environ["TESTING"] = "true"

import io
import json
import uuid
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent))

from main import app
from services.job_store import get_job, create_job, update_job
from models.job import JobStatus

client = TestClient(app)

# ── shared fake data ──────────────────────────────────────────────────────────

FAKE_CLASSIFICATION = {
    "question_type": "how_to",
    "needs_video_evidence": True,
    "needs_external_search": False,
    "retrieval_query": "breathing technique vocal training",
}
FAKE_INITIAL = {
    "answer": "Use diaphragmatic breathing.",
    "need_search": False,
    "search_query": None,
    "confidence": "high",
    "used_chunks": ["chunk_000"],
}
FAKE_FINAL = {
    "answer": "The instructor recommends diaphragmatic breathing.",
    "based_on_video": ["At 02:05 the instructor demonstrates abdominal expansion."],
    "expert_explanation": ["Diaphragmatic breathing increases lung capacity."],
    "relevant_timestamps": ["02:05-03:00"],
    "search_note": None,
    "confidence": "high",
}
FAKE_EMBEDDING = [0.1] * 1536
FAKE_CHUNKS = [
    {"chunk_id": "chunk_000", "start": 0.0, "end": 45.0,
     "text": "breathing technique content", "score": 0.92},
]


def _make_ready_job(tmp_path: Path, job_id: str = None) -> str:
    """Insert a ready job into SQLite with transcript file on disk."""
    job_id = job_id or f"testjob_{uuid.uuid4().hex[:8]}"
    txt_path = tmp_path / "transcript.txt"
    txt_path.write_text("This is a transcript about vocal training.", encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("# Overview\nVocal training video.", encoding="utf-8")

    create_job(job_id, str(tmp_path / "video.mp4"), str(tmp_path))
    update_job(
        job_id,
        status=JobStatus.ready,
        step="ready",
        progress=100,
        context_mode="full_transcript",
        transcript_txt_path=str(txt_path),
        summary_path=str(summary_path),
        parent_topic="music",
        main_topic="vocal training",
        topic_confidence="high",
        chunk_count=1,
        summary=False,
    )
    return job_id


def _ask(job_id: str, question: str = "What breathing technique is recommended?"):
    return client.post(f"/ask/{job_id}", json={"question": question})


def _patched_qa(fn, *args, **kwargs):
    with patch("services.qa.embed_query", return_value=FAKE_EMBEDDING), \
         patch("services.qa.retrieve", return_value=FAKE_CHUNKS), \
         patch("services.qa._llm", side_effect=[
             json.dumps(FAKE_CLASSIFICATION),
             json.dumps(FAKE_INITIAL),
             json.dumps(FAKE_FINAL),
         ]):
        return fn(*args, **kwargs)


# ── TC-01: 404 for unknown job_id ─────────────────────────────────────────────
def test_ask_unknown_job():
    r = client.post("/ask/doesnotexist", json={"question": "test"})
    assert r.status_code == 404


# ── TC-02: 409 when job is not ready ──────────────────────────────────────────
def test_ask_job_not_ready(tmp_path):
    job_id = f"processingjob_{uuid.uuid4().hex[:8]}"
    txt_path = tmp_path / "transcript.txt"
    txt_path.write_text("text", encoding="utf-8")
    create_job(job_id, str(tmp_path / "v.mp4"), str(tmp_path))
    update_job(job_id, status=JobStatus.transcribing, transcript_txt_path=str(txt_path))
    r = client.post(f"/ask/{job_id}", json={"question": "test"})
    assert r.status_code == 409
    assert "not ready" in r.json()["detail"].lower()


# ── TC-03: successful ask returns all required fields ─────────────────────────
def test_ask_returns_required_fields(tmp_path):
    job_id = _make_ready_job(tmp_path)
    r = _patched_qa(_ask, job_id)
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert len(body["answer"]) > 0


# ── TC-04: response includes based_on_video and relevant_timestamps ───────────
def test_ask_response_structure(tmp_path):
    job_id = _make_ready_job(tmp_path)
    r = _patched_qa(_ask, job_id)
    body = r.json()
    assert body["based_on_video"] is not None
    assert body["relevant_timestamps"] is not None
    assert body["confidence"] == "high"


# ── TC-05: used_chunks propagated from initial answer ─────────────────────────
def test_used_chunks_propagated(tmp_path):
    job_id = _make_ready_job(tmp_path)
    r = _patched_qa(_ask, job_id)
    body = r.json()
    assert body["used_chunks"] == ["chunk_000"]


# ── TC-06: web search triggered when need_search=true ────────────────────────
def test_web_search_triggered_when_needed(tmp_path):
    job_id = _make_ready_job(tmp_path)
    initial_with_search = {**FAKE_INITIAL, "need_search": True, "search_query": "vocal training laws"}
    search_results = [{"title": "T", "url": "http://x.com", "snippet": "S"}]

    with patch("services.qa.embed_query", return_value=FAKE_EMBEDDING), \
         patch("services.qa.retrieve", return_value=FAKE_CHUNKS), \
         patch("services.qa.search", return_value=search_results) as mock_search, \
         patch("services.qa._llm", side_effect=[
             json.dumps(FAKE_CLASSIFICATION),
             json.dumps(initial_with_search),
             json.dumps(FAKE_FINAL),
         ]):
        r = _ask(job_id)

    assert r.status_code == 200
    mock_search.assert_called_once_with("vocal training laws")


# ── TC-07: web search not called when need_search=false ───────────────────────
def test_web_search_not_called_when_not_needed(tmp_path):
    job_id = _make_ready_job(tmp_path)

    with patch("services.qa.embed_query", return_value=FAKE_EMBEDDING), \
         patch("services.qa.retrieve", return_value=FAKE_CHUNKS), \
         patch("services.qa.search") as mock_search, \
         patch("services.qa._llm", side_effect=[
             json.dumps(FAKE_CLASSIFICATION),
             json.dumps(FAKE_INITIAL),
             json.dumps(FAKE_FINAL),
         ]):
        r = _ask(job_id)

    assert r.status_code == 200
    mock_search.assert_not_called()


# ── TC-08: search failure is silent — response still succeeds ─────────────────
def test_search_failure_is_silent(tmp_path):
    job_id = _make_ready_job(tmp_path)
    initial_with_search = {**FAKE_INITIAL, "need_search": True, "search_query": "q"}

    with patch("services.qa.embed_query", return_value=FAKE_EMBEDDING), \
         patch("services.qa.retrieve", return_value=FAKE_CHUNKS), \
         patch("services.qa.search", side_effect=Exception("network error")), \
         patch("services.qa._llm", side_effect=[
             json.dumps(FAKE_CLASSIFICATION),
             json.dumps(initial_with_search),
             json.dumps(FAKE_FINAL),
         ]):
        r = _ask(job_id)

    assert r.status_code == 200


# ── TC-09: LLM failure returns 500 with readable message ─────────────────────
def test_llm_failure_returns_500(tmp_path):
    job_id = _make_ready_job(tmp_path)

    with patch("services.qa._llm", side_effect=RuntimeError("OpenAI timeout")):
        r = _ask(job_id)

    assert r.status_code == 500
    assert r.json()["detail"]


# ── TC-10: searcher returns [] on exception (unit test) ───────────────────────
def test_searcher_returns_empty_on_failure():
    from services.searcher import search
    with patch("services.searcher.DDGS", side_effect=Exception("blocked")):
        result = search("anything")
    assert result == []
