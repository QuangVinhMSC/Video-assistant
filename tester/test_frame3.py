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
from services.frame_captioner import caption_frames
from services.job_store import get_job

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"

_FAKE_SEGMENTS = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
_FAKE_TOPICS = {"parent_topic": "test", "main_topic": "test video", "confidence": "high"}
_FAKE_CHUNKS = [{"chunk_id": "chunk_000", "start": 0.0, "end": 5.0,
                 "text": "Hello world.", "token_count": 10}]


def _make_index(tmp_path: Path, count: int = 10) -> str:
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


def _mock_openai(response_text: str = "A slide showing the main topic."):
    """Return a mock OpenAI client whose chat response contains response_text."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value \
        .choices[0].message.content = response_text
    return mock_client


def _upload_pipeline(tmp_path, fake_index=None, caption_side_effect=None):
    """Upload with all pipeline steps mocked; returns (job_id, called, call_args)."""
    json_p = tmp_path / "transcript.json"
    txt_p = tmp_path / "transcript.txt"
    json_p.write_text(json.dumps(_FAKE_SEGMENTS), encoding="utf-8")
    txt_p.write_text("Hello world.", encoding="utf-8")

    caption_kwargs = {}
    if caption_side_effect is not None:
        caption_kwargs["side_effect"] = caption_side_effect

    with patch("tasks.pipeline.extract_frames", return_value=fake_index), \
         patch("tasks.pipeline.run_ocr"), \
         patch("tasks.pipeline.caption_frames", **caption_kwargs) as mock_cap, \
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
        called = mock_cap.called
        call_args = mock_cap.call_args
    return job_id, called, call_args


# ── TC-01: caption_frames is a no-op when OPENAI_API_KEY is not set ───────────
def test_caption_frames_noop_without_api_key(tmp_path):
    index_path = _make_index(tmp_path, count=2)
    with patch.dict(os.environ):
        os.environ.pop("OPENAI_API_KEY", None)
        caption_frames(index_path)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert all(e["caption"] is None for e in index)


# ── TC-02: only every Nth frame is sent to the API ────────────────────────────
def test_caption_frames_samples_every_nth(tmp_path):
    index_path = _make_index(tmp_path, count=10)
    mock_client = _mock_openai("A diagram showing breathing technique.")
    with patch("services.frame_captioner.openai.OpenAI", return_value=mock_client):
        caption_frames(index_path, sample_every=3)
    # Frames at indices 0, 3, 6, 9 should be captioned (4 out of 10)
    assert mock_client.chat.completions.create.call_count == 4


# ── TC-03: non-null API response is stored as caption ─────────────────────────
def test_caption_frames_stores_response(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    expected = "A slide showing the breathing exercise diagram."
    mock_client = _mock_openai(expected)
    with patch("services.frame_captioner.openai.OpenAI", return_value=mock_client):
        caption_frames(index_path, sample_every=1)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["caption"] == expected


# ── TC-04: model response "null" keeps caption as None ────────────────────────
def test_caption_frames_null_string_stays_none(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    mock_client = _mock_openai("null")
    with patch("services.frame_captioner.openai.OpenAI", return_value=mock_client):
        caption_frames(index_path, sample_every=1)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["caption"] is None


# ── TC-05: model response "null." keeps caption as None ───────────────────────
def test_caption_frames_null_dot_stays_none(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    mock_client = _mock_openai("null.")
    with patch("services.frame_captioner.openai.OpenAI", return_value=mock_client):
        caption_frames(index_path, sample_every=1)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["caption"] is None


# ── TC-06: empty string response keeps caption as None ────────────────────────
def test_caption_frames_empty_response_stays_none(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    mock_client = _mock_openai("")
    with patch("services.frame_captioner.openai.OpenAI", return_value=mock_client):
        caption_frames(index_path, sample_every=1)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["caption"] is None


# ── TC-07: per-frame API exception is caught; remaining frames are captioned ───
def test_caption_frames_continues_after_api_error(tmp_path):
    index_path = _make_index(tmp_path, count=3)
    mock_client = MagicMock()
    # First call raises, second returns a valid caption
    def _resp(text):
        r = MagicMock()
        r.choices[0].message.content = text
        return r

    mock_client.chat.completions.create.side_effect = [
        Exception("Rate limit"),
        _resp("A breathing exercise diagram."),
        _resp("A vocal warm-up slide."),
    ]
    with patch("services.frame_captioner.openai.OpenAI", return_value=mock_client):
        caption_frames(index_path, sample_every=1)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["caption"] is None                          # failed → null
    assert index[1]["caption"] == "A breathing exercise diagram."
    assert index[2]["caption"] == "A vocal warm-up slide."


# ── TC-08: index.json is updated in place with captions ───────────────────────
def test_caption_frames_writes_index_in_place(tmp_path):
    index_path = _make_index(tmp_path, count=1)
    mock_client = _mock_openai("A slide with text about vocal training.")
    with patch("services.frame_captioner.openai.OpenAI", return_value=mock_client):
        caption_frames(index_path, sample_every=1)
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    assert index[0]["caption"] == "A slide with text about vocal training."


# ── TC-09: pipeline calls caption_frames when index_path is not None ──────────
def test_pipeline_calls_caption_frames_when_index_set(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    _, called, call_args = _upload_pipeline(tmp_path, fake_index=fake_index)
    assert called
    assert call_args.args[0] == fake_index


# ── TC-10: pipeline reaches ready even if caption_frames raises ───────────────
def test_pipeline_continues_when_caption_raises(tmp_path):
    fake_index = str(tmp_path / "frames" / "index.json")
    job_id, _, _ = _upload_pipeline(
        tmp_path,
        fake_index=fake_index,
        caption_side_effect=RuntimeError("OpenAI timeout"),
    )
    job = get_job(job_id)
    assert job.status == "ready"
