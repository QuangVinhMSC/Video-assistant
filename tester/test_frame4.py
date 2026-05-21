import os
os.environ["TESTING"] = "true"

import io
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from services.chunker import attach_frames_to_chunks
from services.frame_store import load_frame_index, get_frames_in_range, evict
import services.qa as qa_module
from services.job_store import get_job

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"

_FAKE_SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
_FAKE_TOPICS = {"parent_topic": "test", "main_topic": "test video", "confidence": "high"}
_FAKE_CHUNKS = [{"chunk_id": "chunk_000", "start": 0.0, "end": 10.0,
                 "text": "Hello world.", "token_count": 10}]


def _make_index(tmp_path: Path, entries: list = None) -> str:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    if entries is None:
        entries = [
            {"frame_id": "frame_000001", "timestamp": 2.0,
             "path": str(frames_dir / "frame_000001.jpg"), "ocr_text": None, "caption": None},
            {"frame_id": "frame_000002", "timestamp": 4.0,
             "path": str(frames_dir / "frame_000002.jpg"), "ocr_text": None, "caption": None},
            {"frame_id": "frame_000003", "timestamp": 12.0,
             "path": str(frames_dir / "frame_000003.jpg"), "ocr_text": None, "caption": None},
        ]
    index_path = frames_dir / "index.json"
    index_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return str(index_path)


def _upload_pipeline(tmp_path, fake_index=None, attach_side_effect=None):
    json_p = tmp_path / "transcript.json"
    txt_p = tmp_path / "transcript.txt"
    json_p.write_text(json.dumps(_FAKE_SEGMENTS), encoding="utf-8")
    txt_p.write_text("Hello world.", encoding="utf-8")

    attach_kwargs = {"return_value": list(_FAKE_CHUNKS)}
    if attach_side_effect is not None:
        attach_kwargs = {"side_effect": attach_side_effect}

    with patch("tasks.pipeline.extract_frames", return_value=fake_index), \
         patch("tasks.pipeline.run_ocr"), \
         patch("tasks.pipeline.caption_frames"), \
         patch("tasks.pipeline.transcribe", return_value=(str(json_p), str(txt_p))), \
         patch("tasks.pipeline.summarize"), \
         patch("tasks.pipeline.chunk_transcript", return_value=list(_FAKE_CHUNKS)), \
         patch("tasks.pipeline.attach_frames_to_chunks", **attach_kwargs) as mock_attach, \
         patch("tasks.pipeline.reconcile_chunks", return_value=list(_FAKE_CHUNKS)), \
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
        called = mock_attach.called
        call_args = mock_attach.call_args
    return job_id, called, call_args


# ── TC-01: frames within chunk window are attached ────────────────────────────
def test_attach_frames_within_window(tmp_path):
    index_path = _make_index(tmp_path)
    chunks = [{"chunk_id": "chunk_000", "start": 0.0, "end": 10.0, "text": "Hello"}]
    result = attach_frames_to_chunks(chunks, index_path)
    ids = [f["frame_id"] for f in result[0]["frames"]]
    assert "frame_000001" in ids   # ts=2.0, inside 0–10
    assert "frame_000002" in ids   # ts=4.0, inside 0–10


# ── TC-02: frame outside all chunk windows is not attached ────────────────────
def test_attach_frames_outside_window_excluded(tmp_path):
    index_path = _make_index(tmp_path)
    chunks = [{"chunk_id": "chunk_000", "start": 0.0, "end": 10.0, "text": "Hello"}]
    result = attach_frames_to_chunks(chunks, index_path)
    ids = [f["frame_id"] for f in result[0]["frames"]]
    assert "frame_000003" not in ids   # ts=12.0, outside 0–10


# ── TC-03: chunk with no matching frames gets an empty list ───────────────────
def test_attach_frames_no_match_gives_empty_list(tmp_path):
    index_path = _make_index(tmp_path)
    chunks = [{"chunk_id": "chunk_000", "start": 50.0, "end": 60.0, "text": "No frames here"}]
    result = attach_frames_to_chunks(chunks, index_path)
    assert result[0]["frames"] == []


# ── TC-04: ocr_text and caption are preserved in attached frame entry ─────────
def test_attach_frames_preserves_metadata(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    entries = [{"frame_id": "frame_000001", "timestamp": 2.0,
                "path": str(frames_dir / "frame_000001.jpg"),
                "ocr_text": "Slide title", "caption": "A diagram."}]
    index_path = frames_dir / "index.json"
    index_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    chunks = [{"chunk_id": "chunk_000", "start": 0.0, "end": 5.0, "text": "text"}]
    result = attach_frames_to_chunks(chunks, str(index_path))
    frame = result[0]["frames"][0]
    assert frame["ocr_text"] == "Slide title"
    assert frame["caption"] == "A diagram."


# ── TC-05: frame_store get_frames_in_range returns matching frames ────────────
def test_frame_store_get_in_range(tmp_path):
    index_path = _make_index(tmp_path)
    load_frame_index("job_tc05", index_path)
    try:
        results = get_frames_in_range("job_tc05", 0.0, 10.0)
        ids = [f["frame_id"] for f in results]
        assert "frame_000001" in ids   # ts=2.0, inside range
        assert "frame_000002" in ids   # ts=4.0, inside range
        assert "frame_000003" not in ids  # ts=12.0, outside range
    finally:
        evict("job_tc05")


# ── TC-06: frame_store evict removes the job index ────────────────────────────
def test_frame_store_evict_clears_index(tmp_path):
    index_path = _make_index(tmp_path)
    load_frame_index("job_tc06", index_path)
    evict("job_tc06")
    assert get_frames_in_range("job_tc06", 0.0, 100.0) == []


# ── TC-07: _format_chunks includes Visual and On-screen text lines ────────────
def test_format_chunks_includes_frame_context():
    chunks = [{
        "chunk_id": "chunk_000", "start": 0.0, "end": 10.0, "text": "Hello world.",
        "frames": [{"timestamp": 2.0, "frame_id": "frame_000001",
                    "caption": "A diagram.", "ocr_text": "Step 1: Begin"}],
    }]
    result = qa_module._format_chunks(chunks)
    assert "[Visual at 00:02: A diagram.]" in result
    assert "[On-screen text at 00:02: Step 1: Begin]" in result


# ── TC-08: _format_chunks works for chunks with no frames key ─────────────────
def test_format_chunks_handles_missing_frames_key():
    chunks = [{"chunk_id": "chunk_000", "start": 0.0, "end": 10.0, "text": "Hello world."}]
    result = qa_module._format_chunks(chunks)
    assert "Hello world." in result
    assert "Visual" not in result


# ── TC-09: pipeline calls attach_frames_to_chunks when index_path is set ──────
def test_pipeline_calls_attach_when_index_set(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    _, called, call_args = _upload_pipeline(tmp_path, fake_index=fake_index)
    assert called
    assert call_args.args[1] == fake_index


# ── TC-10: pipeline skips attach_frames_to_chunks when index_path is None ─────
def test_pipeline_skips_attach_when_index_none(tmp_path):
    _, called, _ = _upload_pipeline(tmp_path, fake_index=None)
    assert not called
