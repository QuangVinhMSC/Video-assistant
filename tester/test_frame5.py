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
from services.frame_reconciler import reconcile_chunks
from services.job_store import get_job

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"

_FAKE_SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
_FAKE_TOPICS = {"parent_topic": "test", "main_topic": "test video", "confidence": "high"}
_FAKE_CHUNKS = [{"chunk_id": "chunk_000", "start": 0.0, "end": 5.0,
                 "text": "Hello world.", "token_count": 10}]


def _chunk_with_frames(ocr_text=None, caption=None):
    return {
        "chunk_id": "chunk_000", "start": 0.0, "end": 10.0,
        "text": "control sea to copy",
        "token_count": 10,
        "frames": [{"frame_id": "frame_000001", "timestamp": 2.0,
                    "ocr_text": ocr_text, "caption": caption}],
    }


def _mock_openai(response_json: dict):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value \
        .choices[0].message.content = json.dumps(response_json)
    return mock_client


def _upload_pipeline(tmp_path, fake_index=None, reconcile_side_effect=None):
    json_p = tmp_path / "transcript.json"
    txt_p = tmp_path / "transcript.txt"
    json_p.write_text(json.dumps(_FAKE_SEGMENTS), encoding="utf-8")
    txt_p.write_text("Hello world.", encoding="utf-8")

    reconcile_kwargs = {"return_value": list(_FAKE_CHUNKS)}
    if reconcile_side_effect is not None:
        reconcile_kwargs = {"side_effect": reconcile_side_effect}

    with patch("tasks.pipeline.extract_frames", return_value=fake_index), \
         patch("tasks.pipeline.run_ocr"), \
         patch("tasks.pipeline.caption_frames"), \
         patch("tasks.pipeline.transcribe", return_value=(str(json_p), str(txt_p))), \
         patch("tasks.pipeline.summarize"), \
         patch("tasks.pipeline.chunk_transcript", return_value=list(_FAKE_CHUNKS)), \
         patch("tasks.pipeline.attach_frames_to_chunks", return_value=list(_FAKE_CHUNKS)), \
         patch("tasks.pipeline.reconcile_chunks", **reconcile_kwargs) as mock_rec, \
         patch("tasks.pipeline.embed_and_store"), \
         patch("tasks.pipeline.extract_topics", return_value=_FAKE_TOPICS):
        r = client.post(
            "/upload",
            files={"file": ("videofile.mp4", io.BytesIO(VIDEO_PATH.read_bytes()), "video/mp4")},
        )
        job_id = r.json()["job_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            if client.get(f"/status/{job_id}").json()["status"] in ("ready", "failed"):
                break
            time.sleep(0.5)
        called = mock_rec.called
        call_args = mock_rec.call_args
    return job_id, called, call_args


# ── TC-01: reconcile_chunks is a no-op when OPENAI_API_KEY is not set ─────────
def test_reconcile_noop_without_api_key():
    chunk = _chunk_with_frames(ocr_text="Ctrl + C", caption=None)
    with patch.dict(os.environ):
        os.environ.pop("OPENAI_API_KEY", None)
        result = reconcile_chunks([chunk])
    assert "visual_correction" not in result[0]
    assert "corrected_text" not in result[0]


# ── TC-02: chunk with no frame content is skipped ─────────────────────────────
def test_reconcile_skips_chunk_with_no_frame_content():
    chunk = _chunk_with_frames(ocr_text=None, caption=None)
    mock_client = _mock_openai({"has_correction": True, "corrected_text": "x",
                                "reason": "r", "confidence": "high"})
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
         patch("services.frame_reconciler.OpenAI", return_value=mock_client):
        result = reconcile_chunks([chunk])
    mock_client.chat.completions.create.assert_not_called()
    assert "visual_correction" not in result[0]


# ── TC-03: correction fields are added when LLM returns has_correction=true ───
def test_reconcile_adds_correction_when_found():
    chunk = _chunk_with_frames(ocr_text="Ctrl + C")
    response = {"has_correction": True, "corrected_text": "Ctrl + C to copy",
                "reason": "OCR shows Ctrl + C", "confidence": "high"}
    mock_client = _mock_openai(response)
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
         patch("services.frame_reconciler.OpenAI", return_value=mock_client):
        result = reconcile_chunks([chunk])
    assert result[0]["corrected_text"] == "Ctrl + C to copy"
    assert result[0]["visual_correction"]["has_correction"] is True
    assert result[0]["visual_correction"]["confidence"] == "high"


# ── TC-04: original text is never modified even when correction is found ───────
def test_reconcile_does_not_overwrite_original_text():
    chunk = _chunk_with_frames(ocr_text="Ctrl + C")
    original_text = chunk["text"]
    response = {"has_correction": True, "corrected_text": "Ctrl + C to copy",
                "reason": "OCR shows Ctrl + C", "confidence": "high"}
    mock_client = _mock_openai(response)
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
         patch("services.frame_reconciler.OpenAI", return_value=mock_client):
        result = reconcile_chunks([chunk])
    assert result[0]["text"] == original_text


# ── TC-05: no correction fields added when LLM returns has_correction=false ───
def test_reconcile_no_keys_when_no_correction():
    chunk = _chunk_with_frames(caption="A talking head shot.")
    response = {"has_correction": False, "corrected_text": None,
                "reason": None, "confidence": "high"}
    mock_client = _mock_openai(response)
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
         patch("services.frame_reconciler.OpenAI", return_value=mock_client):
        result = reconcile_chunks([chunk])
    assert "corrected_text" not in result[0]
    assert "visual_correction" not in result[0]


# ── TC-06: continues per-chunk when LLM returns unparseable JSON ──────────────
def test_reconcile_continues_on_json_parse_error():
    chunk = _chunk_with_frames(ocr_text="Some text")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value \
        .choices[0].message.content = "not valid json {{{"
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
         patch("services.frame_reconciler.OpenAI", return_value=mock_client):
        result = reconcile_chunks([chunk])
    assert "visual_correction" not in result[0]


# ── TC-07: continues per-chunk when API raises an exception ───────────────────
def test_reconcile_continues_on_api_error():
    chunk = _chunk_with_frames(ocr_text="Some text")
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("Rate limit")
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
         patch("services.frame_reconciler.OpenAI", return_value=mock_client):
        result = reconcile_chunks([chunk])
    assert "visual_correction" not in result[0]


# ── TC-08: pipeline calls reconcile_chunks when index_path is set ─────────────
def test_pipeline_calls_reconcile_when_index_set(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    _, called, _ = _upload_pipeline(tmp_path, fake_index=fake_index)
    assert called


# ── TC-09: pipeline skips reconcile_chunks when index_path is None ────────────
def test_pipeline_skips_reconcile_when_index_none(tmp_path):
    _, called, _ = _upload_pipeline(tmp_path, fake_index=None)
    assert not called


# ── TC-10: pipeline reaches ready even if reconcile_chunks raises ──────────────
def test_pipeline_continues_when_reconcile_raises(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    job_id, _, _ = _upload_pipeline(
        tmp_path,
        fake_index=fake_index,
        reconcile_side_effect=RuntimeError("LLM timeout"),
    )
    job = get_job(job_id)
    assert job.status == "ready"
