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
from services.transcriber import count_tokens
from services.job_store import get_job

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"
TOKEN_THRESHOLD = 20_000

FAKE_SEGMENTS = [
    {"start": 0.0, "end": 5.2, "text": "Today we will learn about vocal training."},
    {"start": 5.2, "end": 12.8, "text": "The first step is breathing control."},
]
FAKE_TRANSCRIPT_TEXT = "\n".join(s["text"] for s in FAKE_SEGMENTS)
FAKE_SUMMARY = "# Overview\nThis video covers vocal training basics."


def _upload_mocked(tmp_path: Path, transcript_text: str = FAKE_TRANSCRIPT_TEXT,
                   summary_side_effect=None):
    """Upload real video with transcribe + summarize mocked."""
    json_path = tmp_path / "transcript.json"
    txt_path = tmp_path / "transcript.txt"
    json_path.write_text(json.dumps(FAKE_SEGMENTS, indent=2), encoding="utf-8")
    txt_path.write_text(transcript_text, encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    summary_path.write_text(FAKE_SUMMARY, encoding="utf-8")

    with patch("tasks.pipeline.transcribe") as mt, patch("tasks.pipeline.summarize") as ms, \
         patch("tasks.pipeline.chunk_transcript", return_value=[
             {"chunk_id": "chunk_000", "start": 0.0, "end": 5.0,
              "text": "Hello world.", "token_count": 10}
         ]), \
         patch("tasks.pipeline.embed_and_store"), \
         patch("tasks.pipeline.extract_topics",
               return_value={"parent_topic": "test", "main_topic": "test", "confidence": "high"}):
        mt.return_value = (str(json_path), str(txt_path))
        if summary_side_effect:
            ms.side_effect = summary_side_effect
        else:
            ms.return_value = str(summary_path)

        r = client.post(
            "/upload",
            files={"file": ("videofile.mp4", io.BytesIO(VIDEO_PATH.read_bytes()), "video/mp4")},
        )
        job_id = r.json()["job_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            status = client.get(f"/status/{job_id}").json()["status"]
            if status in ("chunking", "ready", "failed"):
                break
            time.sleep(0.5)
        return job_id, mt, ms


# ── TC-01: transcript.json is created with correct structure ──────────────────
def test_transcript_json_created(tmp_path):
    job_id, _, _ = _upload_mocked(tmp_path)
    job = get_job(job_id)
    assert job.transcript_path is not None
    segments = json.loads(Path(job.transcript_path).read_text(encoding="utf-8"))
    assert isinstance(segments, list) and len(segments) > 0
    for seg in segments:
        assert {"start", "end", "text"} <= seg.keys()


# ── TC-02: transcript.txt is created and non-empty ────────────────────────────
def test_transcript_txt_created(tmp_path):
    job_id, _, _ = _upload_mocked(tmp_path)
    job = get_job(job_id)
    assert job.transcript_txt_path is not None
    assert Path(job.transcript_txt_path).read_text(encoding="utf-8").strip()


# ── TC-03: transcript_token_count is set to a positive integer ────────────────
def test_transcript_token_count_set(tmp_path):
    job_id, _, _ = _upload_mocked(tmp_path)
    job = get_job(job_id)
    assert isinstance(job.transcript_token_count, int)
    assert job.transcript_token_count > 0


# ── TC-04: context_mode is set to a valid value ───────────────────────────────
def test_context_mode_is_valid(tmp_path):
    job_id, _, _ = _upload_mocked(tmp_path)
    job = get_job(job_id)
    assert job.context_mode in ("full_transcript", "summary_plus_retrieval")


# ── TC-05: short transcript → full_transcript mode, summary=False ─────────────
def test_short_transcript_no_summary(tmp_path):
    job_id, _, mock_summarize = _upload_mocked(tmp_path, transcript_text=FAKE_TRANSCRIPT_TEXT)
    job = get_job(job_id)
    assert job.transcript_token_count <= TOKEN_THRESHOLD
    assert job.context_mode == "full_transcript"
    assert job.summary is False
    assert job.summary_path is None
    mock_summarize.assert_not_called()


# ── TC-06: count_tokens returns correct type and positive count ───────────────
def test_count_tokens_returns_positive_int():
    result = count_tokens("Hello world, this is a test.")
    assert isinstance(result, int)
    assert result > 0


# ── TC-07: count_tokens scales with text length ───────────────────────────────
def test_count_tokens_scales():
    assert count_tokens("Hello.") < count_tokens("Hello. " * 500)


# ── TC-08: long transcript triggers summary generation ────────────────────────
def test_long_transcript_triggers_summary(tmp_path):
    big_text = "word " * 25_000
    job_id, _, mock_summarize = _upload_mocked(tmp_path, transcript_text=big_text)
    job = get_job(job_id)
    assert job.summary is True
    assert job.context_mode == "summary_plus_retrieval"
    assert job.summary_path is not None
    mock_summarize.assert_called_once()


# ── TC-09: summarizer failure marks job as failed with a readable error ────────
def test_summarizer_failure_fails_job(tmp_path):
    big_text = "word " * 25_000
    job_id, _, _ = _upload_mocked(
        tmp_path,
        transcript_text=big_text,
        summary_side_effect=RuntimeError("Summary generation failed: API timeout"),
    )
    job = get_job(job_id)
    assert job.status == "failed"
    assert job.error and len(job.error) > 0


# ── TC-10: status endpoint exposes all Step 2 fields ─────────────────────────
def test_status_exposes_step2_fields(tmp_path):
    job_id, _, _ = _upload_mocked(tmp_path)
    body = client.get(f"/status/{job_id}").json()
    for field in ("transcript_path", "transcript_txt_path", "transcript_token_count",
                  "context_mode", "summary"):
        assert field in body, f"Missing field: {field}"
