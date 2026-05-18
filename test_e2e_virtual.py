"""
Virtual-video end-to-end test.

What is real (no mocks):
  - ffmpeg audio extraction from a synthetic MP4
  - Chunking (services/chunker.py)
  - FAISS index creation and retrieval (services/vector_store.py)
  - SQLite job store and conversation history
  - Full HTTP routing, auth bypass (API_KEY unset), rate limiting

What is mocked (no network / API cost):
  - OpenAI Whisper transcription → deterministic fake transcript
  - OpenAI embeddings → fixed unit vectors
  - OpenAI Chat (topic extraction, Q&A LLM calls) → fixed JSON responses
"""

import os
os.environ["DATABASE_URL"] = "sqlite:///data/test_e2e_virtual.db"

import contextlib
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from db import init_db
from services.history import get_conversation_history, get_turn_count

init_db()
client = TestClient(app)

# ── fake content ──────────────────────────────────────────────────────────────

FAKE_TOPICS = {
    "parent_topic": "programming",
    "main_topic": "Python async programming",
    "confidence": "high",
}

# Six segments ≈ 1 200 tokens total → chunker produces ≥1 full chunk
FAKE_SEGMENTS = [
    {"start": 0.0, "end": 30.0, "text": (
        "Welcome to this comprehensive tutorial on Python asynchronous programming. "
        "In this session we explore the core concepts of async and await syntax, "
        "how the event loop works under the hood, and how to write efficient concurrent "
        "code without the complexity of traditional threading. Asynchronous programming "
        "allows your program to perform multiple operations simultaneously using cooperative "
        "multitasking. While waiting for I/O operations like network requests or file reads "
        "your program can do other work instead of blocking. Python's asyncio library "
        "provides the infrastructure for writing asynchronous code using coroutines."
    )},
    {"start": 30.0, "end": 60.0, "text": (
        "The event loop is the central execution mechanism in asyncio. When you call "
        "asyncio.run() it creates a new event loop, runs your coroutine until completion, "
        "and then closes the loop. The event loop schedules coroutines, tasks, and callbacks "
        "in a single thread. This means async code is not truly parallel in the traditional "
        "sense but it can handle thousands of concurrent I/O-bound operations efficiently "
        "because it never blocks waiting for one operation when others could run. "
        "Understanding the event loop scheduler is essential for writing performant async "
        "applications and avoiding common pitfalls like blocking calls inside coroutines."
    )},
    {"start": 60.0, "end": 90.0, "text": (
        "Coroutines are defined using the async def syntax and are the basic building block "
        "of async programs. When you call a coroutine function it returns a coroutine object "
        "which must be awaited to actually execute. The await keyword suspends the current "
        "coroutine and yields control back to the event loop allowing other coroutines to run. "
        "Cooperative multitasking means that coroutines must explicitly yield control "
        "using await, otherwise they block the entire event loop. Common awaitable objects "
        "include coroutines, futures, and tasks. Using asyncio.create_task() allows you to "
        "schedule a coroutine as a concurrent task within the running loop."
    )},
    {"start": 90.0, "end": 120.0, "text": (
        "asyncio.gather() is a powerful tool for running multiple coroutines concurrently. "
        "It takes multiple awaitables and returns a single future that aggregates results. "
        "All coroutines passed to gather run concurrently within the same event loop. "
        "If any coroutine raises an exception gather propagates it by default. "
        "You can set return_exceptions equal to True to collect exceptions as results. "
        "For producer-consumer patterns asyncio.Queue provides a coroutine-safe queue for "
        "passing data between coroutines. Producers call put and consumers call get, "
        "allowing flexible pipeline architectures without shared mutable state."
    )},
    {"start": 120.0, "end": 150.0, "text": (
        "When working with HTTP requests the aiohttp library provides an async HTTP client "
        "and server framework built on top of asyncio. Using aiohttp.ClientSession you can "
        "make concurrent HTTP requests without blocking the event loop. Always use the "
        "session as a context manager to ensure proper cleanup of connections. For database "
        "access asyncpg provides a fast PostgreSQL client and SQLAlchemy supports async "
        "engines. Common pitfalls include calling blocking functions like time.sleep "
        "inside coroutines — replace them with await asyncio.sleep. Another pitfall "
        "is creating new event loops in threads, which leads to subtle runtime bugs."
    )},
    {"start": 150.0, "end": 180.0, "text": (
        "Testing async code requires special consideration. pytest-asyncio provides "
        "fixtures and markers for testing coroutines directly. Use asyncio.run() for "
        "simple scripts or the pytest.mark.asyncio decorator for async test functions. "
        "When profiling async applications look for coroutines that spend most of their "
        "time not awaiting, which indicates blocking code. Tools like aiodebug and "
        "asyncio debug mode help identify slow callbacks and long-running coroutines. "
        "In production always use structured logging with correlation IDs to trace "
        "requests across coroutines that interleave during concurrent execution."
    )},
]

FAKE_EMBED = [0.05] * 1536
FAKE_CHUNK_RESULT = [
    {"chunk_id": "chunk_000", "start": 0.0, "end": 60.0,
     "text": "Python async programming tutorial content.", "score": 0.95}
]

_C = lambda a: json.dumps({
    "question_type": "how_to", "needs_video_evidence": True,
    "needs_external_search": False, "retrieval_query": "async python",
})
_I = lambda a: json.dumps({
    "answer": a, "need_search": False, "search_query": None,
    "confidence": "high", "used_chunks": ["chunk_000"],
})
_F = lambda a: json.dumps({
    "answer": a,
    "based_on_video": [f"Video explains: {a[:40]}"],
    "expert_explanation": ["Core concept in async programming."],
    "relevant_timestamps": ["00:00-00:30"],
    "search_note": None,
    "confidence": "high",
})

A1 = "Python async programming allows concurrent I/O without traditional threads."
A2 = "The event loop schedules coroutines cooperatively in a single thread."
A3 = "Use asyncio.gather() to run multiple coroutines concurrently."

FAKE_LLM_RESPONSES = [
    _C(A1), _I(A1), _F(A1),   # question 1
    _C(A2), _I(A2), _F(A2),   # question 2
    _C(A3), _I(A3), _F(A3),   # question 3
]

# ── mock implementations ──────────────────────────────────────────────────────

def _fake_transcribe(audio_path: str, output_dir: str):
    out = Path(output_dir)
    json_path = out / "transcript.json"
    txt_path = out / "transcript.txt"
    json_path.write_text(json.dumps(FAKE_SEGMENTS, indent=2), encoding="utf-8")
    txt_path.write_text("\n".join(s["text"] for s in FAKE_SEGMENTS), encoding="utf-8")
    return str(json_path), str(txt_path)


def _fake_embed_and_store(job_id: str, chunks: list) -> None:
    embeddings = [[0.1 * (i + 1)] + [0.01] * 1535 for i in range(len(chunks))]
    from services.vector_store import store_embeddings_direct
    store_embeddings_direct(job_id, chunks, embeddings)


def _poll_until_ready(job_id: str, timeout: int = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/status/{job_id}").json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.15)
    raise TimeoutError(f"Job {job_id} did not finish in {timeout}s")

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def virtual_video_path(tmp_path_factory):
    """Create a 5-second synthetic MP4: 440 Hz sine + black frames."""
    out = tmp_path_factory.mktemp("vvid") / "virtual.mp4"
    proc = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-f", "lavfi", "-i", "color=black:size=160x120:rate=5:duration=5",
            "-map", "0:a", "-map", "1:v",
            "-c:v", "libx264", "-c:a", "aac",
            "-pix_fmt", "yuv420p", "-shortest",
            str(out),
        ],
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        pytest.skip(f"ffmpeg unavailable: {proc.stderr.decode()[:200]}")
    assert out.exists() and out.stat().st_size > 0
    return out


@pytest.fixture(scope="module")
def e2e(virtual_video_path):
    """
    Upload the synthetic video, wait for pipeline, ask 3 questions.
    Patches every OpenAI call — runs entirely offline.
    """
    # tasks/pipeline.py imports these names at module level, so patch them
    # there — patching only the source module would have no effect on the
    # already-bound names that process_video() calls.
    patches = [
        patch("tasks.pipeline.transcribe", side_effect=_fake_transcribe),
        patch("tasks.pipeline.embed_and_store", side_effect=_fake_embed_and_store),
        patch("tasks.pipeline.extract_topics", return_value=FAKE_TOPICS),
        patch("services.qa.embed_query", return_value=FAKE_EMBED),
        patch("services.qa.retrieve", return_value=FAKE_CHUNK_RESULT),
        patch("services.qa._llm", side_effect=list(FAKE_LLM_RESPONSES)),
    ]

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        r = client.post(
            "/upload",
            files={"file": ("virtual.mp4", virtual_video_path.read_bytes(), "video/mp4")},
        )
        assert r.status_code == 200, f"upload failed: {r.text}"
        job_id = r.json()["job_id"]

        job = _poll_until_ready(job_id)

        answers = []
        for q in [
            "What is Python async programming?",
            "How does the event loop work?",
            "How do I run multiple coroutines concurrently?",
        ]:
            answers.append(client.post(f"/ask/{job_id}", json={"question": q}))

    return {"job_id": job_id, "job": job, "answers": answers}


# ── 10 tests ──────────────────────────────────────────────────────────────────

# TC-01: pipeline reaches "ready" with full progress
def test_pipeline_completes_as_ready(e2e):
    assert e2e["job"]["status"] == "ready"
    assert e2e["job"]["progress"] == 100


# TC-02: topic metadata is populated from the fake topics response
def test_job_topic_metadata(e2e):
    job = e2e["job"]
    assert job["parent_topic"] == "programming"
    assert job["main_topic"] == "Python async programming"
    assert job["topic_confidence"] == "high"


# TC-03: chunker produced at least one chunk (real chunking, fake transcript)
def test_job_has_chunks(e2e):
    assert e2e["job"].get("chunk_count") is not None
    assert e2e["job"]["chunk_count"] >= 1


# TC-04: real ffmpeg created audio.wav; fake transcribe wrote transcript files;
#         real vector store wrote index files
def test_pipeline_files_exist_on_disk(e2e):
    job_dir = Path(e2e["job"]["job_dir"])
    assert (job_dir / "audio.wav").exists(),       "audio.wav missing"
    assert (job_dir / "transcript.json").exists(), "transcript.json missing"
    assert (job_dir / "transcript.txt").exists(),  "transcript.txt missing"
    assert (job_dir / "chunks.json").exists(),     "chunks.json missing"
    has_index = (job_dir / "faiss.index").exists() or (job_dir / "embeddings.npy").exists()
    assert has_index, "vector index missing"


# TC-05: transcript.json is valid and contains all fake segments
def test_transcript_json_content(e2e):
    job_dir = Path(e2e["job"]["job_dir"])
    segs = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
    assert len(segs) == len(FAKE_SEGMENTS)
    assert segs[0]["start"] == 0.0
    assert segs[-1]["end"] == 180.0


# TC-06: GET /status returns job_dir and context_mode
def test_status_endpoint_fields(e2e):
    r = client.get(f"/status/{e2e['job_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == e2e["job_id"]
    assert body["job_dir"] is not None
    assert body["context_mode"] in ("full_transcript", "summary_plus_retrieval")


# TC-07: first question returns a proper answer with turn=1
def test_first_answer_structure_and_turn(e2e):
    body = e2e["answers"][0].json()
    assert e2e["answers"][0].status_code == 200
    assert body["answer"] == A1
    assert body["turn"] == 1
    assert body["confidence"] == "high"
    assert isinstance(body["based_on_video"], list)
    assert isinstance(body["relevant_timestamps"], list)


# TC-08: second and third questions increment the turn counter
def test_turn_counter_increments(e2e):
    assert e2e["answers"][1].json()["turn"] == 2
    assert e2e["answers"][2].json()["turn"] == 3


# TC-09: SQLite conversation table has all three turns in order
def test_conversation_history_in_db(e2e):
    job_id = e2e["job_id"]
    assert get_turn_count(job_id) == 3
    hist = get_conversation_history(job_id, last_n=10)
    assert len(hist) == 3
    assert hist[0]["turn"] == 1 and hist[0]["answer"] == A1
    assert hist[1]["turn"] == 2 and hist[1]["answer"] == A2
    assert hist[2]["turn"] == 3 and hist[2]["answer"] == A3


# TC-10: FAISS / NumPy index written by pipeline is retrievable
def test_vector_index_retrievable(e2e):
    from services.vector_store import retrieve
    job_id = e2e["job_id"]
    results = retrieve(job_id, [0.1] + [0.01] * 1535, top_k=3)
    assert len(results) >= 1
    r0 = results[0]
    assert "chunk_id" in r0
    assert "text" in r0
    assert "score" in r0
