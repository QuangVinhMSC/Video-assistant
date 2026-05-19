"""
End-to-end integration test using the real video file and live OpenAI API.
Runs entirely in-process via FastAPI TestClient — no server needed.
"""
import io
import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
VIDEO_PATH = Path(__file__).parent.parent / "videofile.mp4"

SEP = "-" * 60


def banner(title: str):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def poll_until_ready(job_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        body = client.get(f"/status/{job_id}").json()
        status = body["status"]
        if status != last_status:
            print(f"  [{time.strftime('%H:%M:%S')}] status -> {status}"
                  + (f"  (progress: {body.get('progress')}%)" if body.get("progress") else ""))
            last_status = status
        if status in ("ready", "failed"):
            return body
        time.sleep(2)
    raise TimeoutError(f"Job did not complete within {timeout}s")


# ── Step 1: Upload ─────────────────────────────────────────────────────────────
banner("STEP 1 — Upload video")
print(f"  File : {VIDEO_PATH.name}")
print(f"  Size : {VIDEO_PATH.stat().st_size / 1024 / 1024:.1f} MB")

r = client.post(
    "/upload",
    files={"file": ("videofile.mp4", io.BytesIO(VIDEO_PATH.read_bytes()), "video/mp4")},
)
assert r.status_code == 200, f"Upload failed: {r.text}"
job_id = r.json()["job_id"]
print(f"  job_id: {job_id}")

# ── Step 2-3: Wait for pipeline ────────────────────────────────────────────────
banner("STEPS 2-3 — Processing pipeline")
job = poll_until_ready(job_id)

if job["status"] == "failed":
    print(f"\n  ERROR: {job['error']}")
    sys.exit(1)

print(f"\n  Pipeline complete.")
print(f"  parent_topic       : {job.get('parent_topic')}")
print(f"  main_topic         : {job.get('main_topic')}")
print(f"  topic_confidence   : {job.get('topic_confidence')}")
print(f"  transcript_tokens  : {job.get('transcript_token_count')}")
print(f"  context_mode       : {job.get('context_mode')}")
print(f"  chunk_count        : {job.get('chunk_count')}")

# ── Step 4: Q&A ───────────────────────────────────────────────────────────────
questions = [
    "What is this video about? Give me a brief summary.",
    "What are the main techniques or concepts explained?",
    "What advice does the speaker give?",
]

for i, question in enumerate(questions, 1):
    banner(f"STEP 4 — Question {i}/{len(questions)}")
    print(f"  Q: {question}\n")

    t0 = time.time()
    r = client.post(f"/ask/{job_id}", json={"question": question})
    elapsed = time.time() - t0

    assert r.status_code == 200, f"Ask failed ({r.status_code}): {r.text}"
    ans = r.json()

    print(f"  Answer ({elapsed:.1f}s):")
    print(f"  {ans['answer']}\n")

    if ans.get("based_on_video"):
        print("  Based on the video:")
        for point in ans["based_on_video"]:
            print(f"    • {point}")

    if ans.get("expert_explanation"):
        print("\n  Expert explanation:")
        for point in ans["expert_explanation"]:
            print(f"    • {point}")

    if ans.get("relevant_timestamps"):
        print(f"\n  Timestamps: {', '.join(ans['relevant_timestamps'])}")

    if ans.get("search_note"):
        print(f"\n  Search note: {ans['search_note']}")

    print(f"\n  Confidence : {ans.get('confidence')}")
    print(f"  Used chunks: {ans.get('used_chunks')}")

banner("DONE — all steps passed")
