import io
import json
import time
import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent))

from main import app

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent / "videofile.mp4"

# Mocks for everything downstream of audio extraction (Steps 2-4).
# Step 1 tests only care about upload, job creation, and ffmpeg.
_FAKE_SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
_FAKE_TOPICS = {"parent_topic": "test", "main_topic": "test video", "confidence": "high"}
_FAKE_CHUNKS = [{"chunk_id": "chunk_000", "start": 0.0, "end": 5.0,
                 "text": "Hello world.", "token_count": 10}]


@contextmanager
def _mock_pipeline(tmp_path=None):
    """Patch all API-dependent steps so real-video tests don't need OPENAI_API_KEY."""
    import tempfile, os
    td = tmp_path or tempfile.mkdtemp()
    json_p = Path(td) / "transcript.json"
    txt_p  = Path(td) / "transcript.txt"
    json_p.write_text(json.dumps(_FAKE_SEGMENTS), encoding="utf-8")
    txt_p.write_text("Hello world.", encoding="utf-8")

    with patch("routers.video.transcribe",    return_value=(str(json_p), str(txt_p))), \
         patch("routers.video.summarize",     return_value=str(Path(td) / "summary.md")), \
         patch("routers.video.chunk_transcript", return_value=_FAKE_CHUNKS), \
         patch("routers.video.embed_and_store"), \
         patch("routers.video.extract_topics", return_value=_FAKE_TOPICS):
        yield


def upload(filename="videofile.mp4", content=None, content_type="video/mp4"):
    data = content if content is not None else VIDEO_PATH.read_bytes()
    return client.post(
        "/upload",
        files={"file": (filename, io.BytesIO(data), content_type)},
    )


# ── TC-01: successful upload returns job_id and status=uploaded ──────────────
def test_upload_success():
    r = upload()
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "uploaded"
    assert len(body["job_id"]) == 32  # uuid4 hex


# ── TC-02: status endpoint returns job immediately after upload ───────────────
def test_status_after_upload():
    with _mock_pipeline():
        job_id = upload().json()["job_id"]
    r = client.get(f"/status/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id
    assert body["status"] in (
        "uploaded", "extracting_audio", "transcribing", "chunking",
        "embedding", "summarizing", "ready", "failed",
    )


# ── TC-03: status endpoint returns 404 for unknown job_id ────────────────────
def test_status_unknown_job():
    r = client.get("/status/nonexistent000000000000000000000")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


# ── TC-04: unsupported file extension is rejected with 400 ───────────────────
def test_upload_unsupported_extension():
    r = upload(filename="clip.xyz", content=b"fake data")
    assert r.status_code == 400
    assert "Unsupported file type" in r.json()["detail"]


# ── TC-05: each upload gets a unique job_id ───────────────────────────────────
def test_unique_job_ids():
    ids = {upload().json()["job_id"] for _ in range(3)}
    assert len(ids) == 3


# ── TC-06: all allowed extensions are accepted (200 response) ─────────────────
@pytest.mark.parametrize("ext", [".mp4", ".mkv", ".mov", ".webm", ".avi"])
def test_allowed_extensions(ext):
    r = upload(filename=f"clip{ext}", content=b"fake video bytes")
    assert r.status_code == 200


# ── TC-07: empty file upload is accepted (ffmpeg will fail in background) ─────
def test_empty_file_upload():
    r = upload(filename="empty.mp4", content=b"")
    assert r.status_code == 200
    assert "job_id" in r.json()


# ── TC-08: background task extracts audio — audio.wav exists after processing ─
def test_audio_extracted_from_real_video():
    with _mock_pipeline():
        job_id = upload().json()["job_id"]
        deadline = time.time() + 60
        while time.time() < deadline:
            status = client.get(f"/status/{job_id}").json()["status"]
            if status in ("ready", "failed"):
                break
            time.sleep(1)

    from services.job_store import get_job
    job = get_job(job_id)

    # Audio extraction is a Step 1 concern — verify it regardless of later steps
    assert job.audio_path is not None, "audio_path was never set"
    assert Path(job.audio_path).exists(), "audio.wav was not created on disk"


# ── TC-09: job progresses through the pipeline to ready ──────────────────────
def test_job_status_progression():
    with _mock_pipeline():
        job_id = upload().json()["job_id"]
        seen = set()
        deadline = time.time() + 60
        while time.time() < deadline:
            status = client.get(f"/status/{job_id}").json()["status"]
            seen.add(status)
            if status in ("ready", "failed"):
                break
            time.sleep(0.5)

    # Fast machines may skip early statuses — what matters is the job
    # completed the pipeline without failing.
    assert "ready" in seen, f"Job never reached ready; saw: {seen}"
    assert "failed" not in seen, f"Job unexpectedly failed; saw: {seen}"


# ── TC-10: failed job surfaces a readable error message ───────────────────────
def test_failed_job_has_error_message():
    r = upload(filename="bad.mp4", content=b"not a real video")
    job_id = r.json()["job_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        body = client.get(f"/status/{job_id}").json()
        if body["status"] == "failed":
            assert body["error"] is not None
            assert len(body["error"]) > 0
            return
        time.sleep(1)
    pytest.fail("Job with corrupt video never reached failed status")
