import os
os.environ["TESTING"] = "true"

import io
import json
import time
import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
import services.frame_ocr as ocr_module
from services.frame_ocr import run_ocr
from services.job_store import get_job

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"

_FAKE_SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
_FAKE_TOPICS = {"parent_topic": "test", "main_topic": "test video", "confidence": "high"}
_FAKE_CHUNKS = [{"chunk_id": "chunk_000", "start": 0.0, "end": 5.0,
                 "text": "Hello world.", "token_count": 10}]


def _make_index(tmp_path: Path, count: int = 3) -> str:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(1, count + 1):
        p = frames_dir / f"frame_{i:06d}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0fake")
        entries.append({"frame_id": p.stem, "timestamp": i * 2.0,
                        "path": str(p), "ocr_text": None, "caption": None})
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return str(index_path)


@contextmanager
def mock_tesseract(return_text: str = "Some slide text from OCR"):
    """Make pytesseract appear installed and return a fixed string."""
    mock_pyt = MagicMock()
    mock_pyt.image_to_string.return_value = return_text
    mock_img = MagicMock()
    with patch.object(ocr_module, "_TESSERACT_AVAILABLE", True), \
         patch.object(ocr_module, "pytesseract", mock_pyt, create=True), \
         patch.object(ocr_module, "Image", mock_img, create=True):
        yield mock_pyt


def _upload_pipeline(tmp_path, fake_index=None, run_ocr_side_effect=None):
    """Upload with all pipeline steps mocked; returns (job_id, mock_run_ocr)."""
    json_p = tmp_path / "transcript.json"
    txt_p = tmp_path / "transcript.txt"
    json_p.write_text(json.dumps(_FAKE_SEGMENTS), encoding="utf-8")
    txt_p.write_text("Hello world.", encoding="utf-8")

    run_ocr_kwargs = {}
    if run_ocr_side_effect is not None:
        run_ocr_kwargs["side_effect"] = run_ocr_side_effect

    with patch("tasks.pipeline.extract_frames", return_value=fake_index), \
         patch("tasks.pipeline.run_ocr", **run_ocr_kwargs) as mock_run_ocr, \
         patch("tasks.pipeline.caption_frames"), \
         patch("tasks.pipeline.transcribe", return_value=(str(json_p), str(txt_p))), \
         patch("tasks.pipeline.summarize"), \
         patch("tasks.pipeline.chunk_transcript", return_value=_FAKE_CHUNKS), \
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
        called = mock_run_ocr.called
        call_args = mock_run_ocr.call_args
    return job_id, called, call_args


# ── TC-01: run_ocr is a no-op when Tesseract is not available ─────────────────
def test_run_ocr_noop_when_tesseract_unavailable(tmp_path):
    index_path = _make_index(tmp_path)
    with patch.object(ocr_module, "_TESSERACT_AVAILABLE", False):
        run_ocr(index_path)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert all(e["ocr_text"] is None for e in index)


# ── TC-02: text >= 10 chars is stored as ocr_text ─────────────────────────────
def test_run_ocr_stores_long_text(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    with mock_tesseract("Step 3: Exhale slowly over four counts"):
        run_ocr(index_path)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["ocr_text"] == "Step 3: Exhale slowly over four counts"


# ── TC-03: text shorter than 10 chars is treated as noise and stays null ───────
def test_run_ocr_rejects_short_text(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    with mock_tesseract("abc"):  # 3 chars — below threshold
        run_ocr(index_path)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["ocr_text"] is None


# ── TC-04: empty Tesseract result stays null ───────────────────────────────────
def test_run_ocr_empty_result_stays_null(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    with mock_tesseract(""):
        run_ocr(index_path)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["ocr_text"] is None


# ── TC-05: per-frame exception is caught and remaining frames are processed ────
def test_run_ocr_continues_after_frame_error(tmp_path):
    index_path = _make_index(tmp_path, count=3)
    mock_pyt = MagicMock()
    mock_img = MagicMock()
    # First frame raises, second and third return valid text
    mock_pyt.image_to_string.side_effect = [
        Exception("Tesseract crash"),
        "Valid slide text here",
        "Another valid text",
    ]
    with patch.object(ocr_module, "_TESSERACT_AVAILABLE", True), \
         patch.object(ocr_module, "pytesseract", mock_pyt, create=True), \
         patch.object(ocr_module, "Image", mock_img, create=True):
        run_ocr(index_path)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["ocr_text"] is None            # failed frame → null
    assert index[1]["ocr_text"] == "Valid slide text here"
    assert index[2]["ocr_text"] == "Another valid text"


# ── TC-06: index.json is mutated in place ─────────────────────────────────────
def test_run_ocr_writes_index_in_place(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    mtime_before = Path(index_path).stat().st_mtime
    with mock_tesseract("Sufficient length text"):
        run_ocr(index_path)
    mtime_after = Path(index_path).stat().st_mtime
    assert mtime_after >= mtime_before
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["ocr_text"] == "Sufficient length text"


# ── TC-07: all frames in the index are processed ──────────────────────────────
def test_run_ocr_processes_all_frames(tmp_path):
    index_path = _make_index(tmp_path, count=4)
    with mock_tesseract("Long enough OCR text here"):
        run_ocr(index_path)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert all(e["ocr_text"] == "Long enough OCR text here" for e in index)


# ── TC-08: pipeline calls run_ocr when index_path is not None ─────────────────
def test_pipeline_calls_run_ocr_when_index_set(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    _, called, call_args = _upload_pipeline(tmp_path, fake_index=fake_index)
    assert called
    assert call_args.args[0] == fake_index


# ── TC-09: pipeline does not call run_ocr when index_path is None ─────────────
def test_pipeline_skips_run_ocr_when_index_none(tmp_path):
    _, called, _ = _upload_pipeline(tmp_path, fake_index=None)
    assert not called


# ── TC-10: pipeline reaches ready even if run_ocr raises ──────────────────────
def test_pipeline_continues_when_run_ocr_raises(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    job_id, _, _ = _upload_pipeline(
        tmp_path,
        fake_index=fake_index,
        run_ocr_side_effect=RuntimeError("Tesseract exploded"),
    )
    job = get_job(job_id)
    assert job.status == "ready"
