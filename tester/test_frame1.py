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
from models.job import JobStatus
from services.extractor import extract_frames
from services.job_store import get_job

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"

_FAKE_SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
_FAKE_TOPICS = {"parent_topic": "test", "main_topic": "test video", "confidence": "high"}
_FAKE_CHUNKS = [{"chunk_id": "chunk_000", "start": 0.0, "end": 5.0,
                 "text": "Hello world.", "token_count": 10}]


def _ffmpeg_ok():
    r = MagicMock()
    r.returncode = 0
    r.stderr = ""
    return r


def _ffmpeg_fail():
    r = MagicMock()
    r.returncode = 1
    r.stderr = "Invalid data found when processing input"
    return r


def _make_fake_jpgs(frames_dir: Path, count: int = 3) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (frames_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")


def _upload_with_mocks(tmp_path: Path, fake_index_path=None, frames_side_effect=None):
    """Upload real video with extract_frames and all downstream steps mocked."""
    json_p = tmp_path / "transcript.json"
    txt_p = tmp_path / "transcript.txt"
    json_p.write_text(json.dumps(_FAKE_SEGMENTS), encoding="utf-8")
    txt_p.write_text("Hello world.", encoding="utf-8")

    frames_kwargs = {}
    if frames_side_effect is not None:
        frames_kwargs["side_effect"] = frames_side_effect
    else:
        frames_kwargs["return_value"] = fake_index_path

    with patch("tasks.pipeline.extract_frames", **frames_kwargs), \
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
    return job_id


# ── TC-01: extract_frames returns path to index.json ─────────────────────────
def test_extract_frames_returns_index_path(tmp_path):
    frames_dir = tmp_path / "frames"
    _make_fake_jpgs(frames_dir, count=2)
    with patch("services.extractor.subprocess.run", return_value=_ffmpeg_ok()):
        result = extract_frames("job123", str(tmp_path / "video.mp4"), str(tmp_path))
    assert result.endswith("index.json")
    assert Path(result).exists()


# ── TC-02: each index.json entry has exactly the required keys ────────────────
def test_index_json_entry_structure(tmp_path):
    frames_dir = tmp_path / "frames"
    _make_fake_jpgs(frames_dir, count=2)
    with patch("services.extractor.subprocess.run", return_value=_ffmpeg_ok()):
        index_path = extract_frames("job123", str(tmp_path / "video.mp4"), str(tmp_path))
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert len(index) == 2
    for entry in index:
        assert set(entry.keys()) == {"frame_id", "timestamp", "path", "ocr_text", "caption"}


# ── TC-03: timestamps follow the (i+1)*2.0 pattern ───────────────────────────
def test_index_timestamps_correct(tmp_path):
    frames_dir = tmp_path / "frames"
    _make_fake_jpgs(frames_dir, count=3)
    with patch("services.extractor.subprocess.run", return_value=_ffmpeg_ok()):
        index_path = extract_frames("job123", str(tmp_path / "video.mp4"), str(tmp_path))
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert [e["timestamp"] for e in index] == [2.0, 4.0, 6.0]


# ── TC-04: ocr_text and caption are null in the initial index ─────────────────
def test_index_ocr_and_caption_null(tmp_path):
    frames_dir = tmp_path / "frames"
    _make_fake_jpgs(frames_dir, count=2)
    with patch("services.extractor.subprocess.run", return_value=_ffmpeg_ok()):
        index_path = extract_frames("job123", str(tmp_path / "video.mp4"), str(tmp_path))
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    for entry in index:
        assert entry["ocr_text"] is None
        assert entry["caption"] is None


# ── TC-05: ffmpeg non-zero exit raises RuntimeError ───────────────────────────
def test_ffmpeg_failure_raises(tmp_path):
    with patch("services.extractor.subprocess.run", return_value=_ffmpeg_fail()):
        with pytest.raises(RuntimeError, match="Frame extraction failed"):
            extract_frames("job123", str(tmp_path / "video.mp4"), str(tmp_path))


# ── TC-06: frames/ directory is created even if it did not exist ──────────────
def test_frames_directory_created(tmp_path):
    frames_dir = tmp_path / "frames"
    assert not frames_dir.exists()
    with patch("services.extractor.subprocess.run", return_value=_ffmpeg_ok()):
        # Create the jpgs after the directory check so mkdir inside the fn creates it
        def _side_effect(*args, **kwargs):
            _make_fake_jpgs(frames_dir, count=1)
            return _ffmpeg_ok()
        with patch("services.extractor.subprocess.run", side_effect=_side_effect):
            extract_frames("job123", str(tmp_path / "video.mp4"), str(tmp_path))
    assert frames_dir.is_dir()


# ── TC-07: JobStatus.extracting_frames is defined in the enum ─────────────────
def test_job_status_extracting_frames_exists():
    assert hasattr(JobStatus, "extracting_frames")
    assert JobStatus.extracting_frames == "extracting_frames"


# ── TC-08: pipeline sets frames_index_path on the job record ──────────────────
def test_pipeline_sets_frames_index_path(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    job_id = _upload_with_mocks(tmp_path, fake_index_path=fake_index)
    job = get_job(job_id)
    assert job.frames_index_path == fake_index


# ── TC-09: pipeline reaches ready even when frame extraction raises ────────────
def test_pipeline_continues_on_frame_failure(tmp_path):
    job_id = _upload_with_mocks(
        tmp_path,
        frames_side_effect=RuntimeError("ffmpeg exploded"),
    )
    job = get_job(job_id)
    assert job.status == "ready"
    assert job.frames_index_path is None


# ── TC-10: status endpoint includes frames_index_path in the response ─────────
def test_status_exposes_frames_index_path(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    job_id = _upload_with_mocks(tmp_path, fake_index_path=fake_index)
    body = client.get(f"/status/{job_id}").json()
    assert "frames_index_path" in body
