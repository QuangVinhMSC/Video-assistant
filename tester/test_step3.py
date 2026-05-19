import os
os.environ["TESTING"] = "true"

import io
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from services.chunker import chunk_transcript, CHUNK_SIZE, OVERLAP
from services.vector_store import retrieve, delete, store_embeddings_direct
from services.job_store import get_job, create_job

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"

# ── shared fake data ──────────────────────────────────────────────────────────

FAKE_SEGMENTS = [
    {"start": i * 5.0, "end": (i + 1) * 5.0, "text": f"Segment {i} about vocal training technique."}
    for i in range(40)
]
FAKE_TRANSCRIPT_TEXT = "\n".join(s["text"] for s in FAKE_SEGMENTS)
FAKE_TOPICS = {"parent_topic": "music", "main_topic": "vocal training", "confidence": "high"}
FAKE_EMBEDDING = [0.1] * 1536


def _make_transcript_files(tmp_path: Path) -> tuple[str, str]:
    json_path = tmp_path / "transcript.json"
    txt_path = tmp_path / "transcript.txt"
    json_path.write_text(json.dumps(FAKE_SEGMENTS, indent=2), encoding="utf-8")
    txt_path.write_text(FAKE_TRANSCRIPT_TEXT, encoding="utf-8")
    return str(json_path), str(txt_path)


def _upload_mocked(tmp_path: Path, extra_patches: dict | None = None):
    """Upload with transcribe, summarize, embed_and_store, extract_topics all mocked."""
    json_path, txt_path = _make_transcript_files(tmp_path)
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("# Overview\nFake summary.", encoding="utf-8")

    fake_chunks = [
        {"chunk_id": "chunk_000", "start": 0.0, "end": 45.0,
         "text": "vocal training content", "token_count": 100}
    ]

    patches = {
        "tasks.pipeline.transcribe":      MagicMock(return_value=(str(json_path), str(txt_path))),
        "tasks.pipeline.summarize":       MagicMock(return_value=str(summary_path)),
        "tasks.pipeline.chunk_transcript": MagicMock(return_value=fake_chunks),
        "tasks.pipeline.embed_and_store": MagicMock(),
        "tasks.pipeline.extract_topics":  MagicMock(return_value=FAKE_TOPICS),
    }
    if extra_patches:
        patches.update(extra_patches)

    with patch("tasks.pipeline.transcribe",      patches["tasks.pipeline.transcribe"]), \
         patch("tasks.pipeline.summarize",        patches["tasks.pipeline.summarize"]), \
         patch("tasks.pipeline.chunk_transcript", patches["tasks.pipeline.chunk_transcript"]), \
         patch("tasks.pipeline.embed_and_store",  patches["tasks.pipeline.embed_and_store"]), \
         patch("tasks.pipeline.extract_topics",   patches["tasks.pipeline.extract_topics"]):

        r = client.post(
            "/upload",
            files={"file": ("videofile.mp4", io.BytesIO(VIDEO_PATH.read_bytes()), "video/mp4")},
        )
        job_id = r.json()["job_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            status = client.get(f"/status/{job_id}").json()["status"]
            if status in ("ready", "failed"):
                break
            time.sleep(0.5)
        return job_id, patches


# ── TC-01: chunk_transcript produces chunks with required fields ───────────────
def test_chunk_transcript_structure(tmp_path):
    json_path, _ = _make_transcript_files(tmp_path)
    chunks = chunk_transcript(str(json_path))
    assert len(chunks) > 0
    for c in chunks:
        assert {"chunk_id", "start", "end", "text", "token_count"} <= c.keys()
        assert c["token_count"] > 0
        assert c["start"] <= c["end"]


# ── TC-02: chunk IDs are sequential and zero-padded ───────────────────────────
def test_chunk_ids_sequential(tmp_path):
    json_path, _ = _make_transcript_files(tmp_path)
    chunks = chunk_transcript(str(json_path))
    for i, c in enumerate(chunks):
        assert c["chunk_id"] == f"chunk_{i:03d}"


# ── TC-03: no chunk exceeds max token size significantly ─────────────────────
def test_chunk_token_sizes(tmp_path):
    json_path, _ = _make_transcript_files(tmp_path)
    chunks = chunk_transcript(str(json_path))
    for c in chunks:
        assert c["token_count"] <= CHUNK_SIZE * 2, (
            f"Chunk {c['chunk_id']} too large: {c['token_count']} tokens"
        )


# ── TC-04: empty transcript raises RuntimeError ───────────────────────────────
def test_chunk_transcript_empty_raises(tmp_path):
    json_path = tmp_path / "transcript.json"
    json_path.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no chunks"):
        chunk_transcript(str(json_path))


# ── TC-05: vector_store retrieve returns top-k results with score field ────────
def test_retrieve_returns_scores(tmp_path):
    job_id = f"test_retrieve_step3_{os.getpid()}"
    create_job(job_id, str(tmp_path / "v.mp4"), str(tmp_path))

    chunks = [
        {"chunk_id": "chunk_000", "start": 0.0, "end": 5.0,
         "text": "hello", "token_count": 10},
        {"chunk_id": "chunk_001", "start": 5.0, "end": 10.0,
         "text": "world", "token_count": 10},
    ]
    embeddings = [
        [1.0] + [0.0] * 1535,
        [0.0, 1.0] + [0.0] * 1534,
    ]
    store_embeddings_direct(job_id, chunks, embeddings)

    query_emb = [1.0] + [0.0] * 1535
    results = retrieve(job_id, query_emb, top_k=2)
    delete(job_id)

    assert len(results) == 2
    assert results[0]["chunk_id"] == "chunk_000"
    assert "score" in results[0]
    assert "embedding" not in results[0]
    assert results[0]["score"] >= results[1]["score"]


# ── TC-06: job reaches status=ready after full pipeline ───────────────────────
def test_job_reaches_ready(tmp_path):
    job_id, _ = _upload_mocked(tmp_path)
    job = get_job(job_id)
    assert job.status == "ready"
    assert job.progress == 100


# ── TC-07: job has parent_topic, main_topic, topic_confidence set ─────────────
def test_topics_set_on_job(tmp_path):
    job_id, _ = _upload_mocked(tmp_path)
    job = get_job(job_id)
    assert job.parent_topic == "music"
    assert job.main_topic == "vocal training"
    assert job.topic_confidence == "high"


# ── TC-08: chunk_count is set correctly on job ────────────────────────────────
def test_chunk_count_set(tmp_path):
    job_id, patches = _upload_mocked(tmp_path)
    job = get_job(job_id)
    expected = len(patches["tasks.pipeline.chunk_transcript"].return_value)
    assert job.chunk_count == expected


# ── TC-09: embedding failure marks job as failed ─────────────────────────────
def test_embedding_failure_fails_job(tmp_path):
    job_id, _ = _upload_mocked(tmp_path, extra_patches={
        "tasks.pipeline.embed_and_store": MagicMock(
            side_effect=RuntimeError("API rate limit exceeded")
        )
    })
    job = get_job(job_id)
    assert job.status == "failed"
    assert "embedding" in job.error.lower() or "rate" in job.error.lower()


# ── TC-10: topic extraction failure marks job as failed ──────────────────────
def test_topic_extraction_failure_fails_job(tmp_path):
    job_id, _ = _upload_mocked(tmp_path, extra_patches={
        "tasks.pipeline.extract_topics": MagicMock(
            side_effect=RuntimeError("Topic extraction returned unparseable response")
        )
    })
    job = get_job(job_id)
    assert job.status == "failed"
    assert job.error and len(job.error) > 0
