# Frame Step 1 — Frame Extraction

## Goal

Implement the `extract_frames` stub in `services/extractor.py`. Extract one JPEG frame every 2 seconds from the uploaded video using ffmpeg, write a `frames/index.json` timestamp index, and wire the step into the processing pipeline. This produces the frame artifact that all later frame steps (OCR, captioning, chunk merging) depend on.

---

## Scope

- Replace the `pass` stub in `services/extractor.py` with a real ffmpeg call
- Update the function signature to accept `job_dir`
- Save frames to `{job_dir}/frames/frame_000001.jpg`, `frame_000002.jpg`, …
- Write `{job_dir}/frames/index.json` with one entry per frame
- Add `extracting_frames` to `JobStatus` in `models/job.py`
- Add `frames_index_path` field to `JobState`
- Update `tasks/pipeline.py` to pass `job_dir` and handle failure

OCR, captioning, chunk merging, and Q&A integration are deferred to later frame steps.

---

## What Frame Step 1 Receives from the Current Pipeline

| Source | Description |
|---|---|
| `video_path` | Absolute path to the uploaded video in `job_dir` |
| `job_dir` | Per-job working directory — already contains `audio.wav` |
| `job_id` | Job identifier for status updates |

The stub call `extract_frames(job_id, video_path)` already exists in `tasks/pipeline.py` immediately after `extract_audio` succeeds.

---

## Implementation

### 1.1 Update `services/extractor.py`

Replace the stub. Add `import json` alongside the existing imports.

```python
def extract_frames(job_id: str, video_path: str, job_dir: str) -> str:
    """
    Extract one frame per 2 seconds from the video via ffmpeg.
    Returns path to frames/index.json.
    """
    frames_dir = Path(job_dir) / "frames"
    frames_dir.mkdir(exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "fps=0.5",    # 0.5 fps = 1 frame every 2 seconds
        "-q:v", "3",         # JPEG quality (2=best, 31=worst)
        str(frames_dir / "frame_%06d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr}")

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    index = [
        {
            "frame_id": f.stem,
            "timestamp": i * 2.0,  # frame 1 → 2.0 s, frame 2 → 4.0 s, …
            "path": str(f),
            "ocr_text": None,
            "caption": None,
        }
        for i, f in enumerate(frames)
    ]
    index_path = frames_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return str(index_path)
```

Frame naming convention:

| File | Timestamp |
|---|---|
| `frame_000001.jpg` | 2.0 s |
| `frame_000002.jpg` | 4.0 s |
| `frame_000003.jpg` | 6.0 s |

`ocr_text` and `caption` are `null` at this step — populated by later frame steps.

---

### 1.2 Update `models/job.py`

**Add `extracting_frames` to `JobStatus`** between `extracting_audio` and `transcribing`:

```python
class JobStatus(str, Enum):
    uploaded = "uploaded"
    extracting_audio = "extracting_audio"
    extracting_frames = "extracting_frames"   # new
    transcribing = "transcribing"
    summarizing = "summarizing"
    chunking = "chunking"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"
```

**Add `frames_index_path` to `JobState`** after `audio_path`:

```python
audio_path: Optional[str] = None
frames_index_path: Optional[str] = None   # new — path to frames/index.json
```

---

### 1.3 Update `tasks/pipeline.py`

Replace the existing bare call:

```python
extract_frames(job_id, video_path)
```

With:

```python
update_job(job_id, status=JobStatus.extracting_frames, step="extracting_frames", progress=28)
try:
    index_path = extract_frames(job_id, video_path, job_dir)
except RuntimeError as e:
    fail_job(job_id, "extracting_frames", str(e))
    return

update_job(job_id, frames_index_path=index_path, progress=33)
```

Also lower the `progress=30` after `extract_audio` to `progress=25` to leave room for the new step between 25 and 33.

---

## Error Handling

| Error | Behaviour |
|---|---|
| ffmpeg not on PATH | `fail_job` step `"extracting_frames"` — pipeline stops |
| ffmpeg non-zero exit | `fail_job` with stderr detail — pipeline stops |
| Video has no video stream | ffmpeg returns non-zero → `fail_job` |
| Zero frames extracted (very short video) | `index.json` written as `[]` — pipeline continues |

Frame extraction failure should not stop the core audio pipeline.
Set frames_index_path = None, log warning, continue to transcribing.

---

## Deliverables

- [ ] `services/extractor.py` — implement `extract_frames(job_id, video_path, job_dir) -> str`; add `import json`
- [ ] `models/job.py` — add `extracting_frames` to `JobStatus`; add `frames_index_path: Optional[str]` to `JobState`
- [ ] `tasks/pipeline.py` — update `extract_frames` call with `job_dir`, status update, error handling, adjusted progress

---

## What Frame Step 1 Does NOT Cover

- OCR text extraction from frames (`services/frame_ocr.py`) — Frame Step 2
- Visual captioning via OpenAI vision (`services/frame_captioner.py`) — Frame Step 3
- Merging frame metadata into transcript chunks — Frame Step 4
- In-memory frame store and Q&A integration — Frame Step 4
