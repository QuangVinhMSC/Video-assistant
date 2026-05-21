# Frame Processing Plan

## Goal

Extend the video pipeline to extract representative frames, enrich them with optional OCR and visual captions, merge the frame metadata into transcript chunks, and expose frame context to the Q&A pipeline so visual questions can be answered with evidence from the video.

---

## Scope

- Implement `extract_frames` in `services/extractor.py` (currently a stub)
- Extract 1 frame per 2 seconds via ffmpeg, saved as JPEG with a timestamp index
- Optional OCR pass to pull text from slides, screens, or on-screen graphics
- Optional visual caption pass using the OpenAI vision API
- Merge frame metadata into `chunks.json` so each chunk carries its associated frames
- Extend the Q&A pipeline to include frame captions/OCR in context when relevant
- New `services/frame_store.py` for frame index management

---

## What Frame Processing Receives from the Current Pipeline

| Source | Description |
|---|---|
| `video_path` | Path to the original uploaded video file |
| `job_dir` | Per-job working directory (already contains `audio.wav`) |
| `job_id` | Used to key the frame index in memory |
| `chunks.json` | Timestamped transcript chunks produced by Step 3 |

Frame extraction runs immediately after audio extraction in `tasks/pipeline.py` — the stub call `extract_frames(job_id, video_path)` is already in place.

---

## Implementation

### 1. Frame Extraction (`services/extractor.py`)

Replace the `pass` stub with an ffmpeg call that outputs one frame every 2 seconds.

```python
def extract_frames(job_id: str, video_path: str, job_dir: str) -> str:
    """
    Extract one frame per 2 seconds from the video.
    Returns path to frames/index.json.
    """
    frames_dir = Path(job_dir) / "frames"
    frames_dir.mkdir(exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "fps=0.5",
        "-q:v", "3",
        str(frames_dir / "frame_%06d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr}")

    # Build timestamp index: ffmpeg names frames 000001, 000002, ...
    # Frame N was captured at N * 2 seconds.
    frames = sorted(frames_dir.glob("frame_*.jpg"))
    index = [
        {
            "frame_id": f.stem,
            "timestamp": (i + 1) * 2.0,
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

Frame naming and timestamps:

| File | Timestamp |
|---|---|
| `frame_000001.jpg` | 2.0 s |
| `frame_000002.jpg` | 4.0 s |
| `frame_000003.jpg` | 6.0 s |

---

### 2. Optional OCR (`services/frame_ocr.py`)

Run after frame extraction if OCR is enabled. Uses `pytesseract` with a JPEG input.

```python
def run_ocr(index_path: str) -> None:
    """
    Annotate each frame entry in index.json with extracted OCR text.
    Mutates index.json in place. Skips frames where OCR yields nothing useful.
    """
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    for entry in index:
        text = pytesseract.image_to_string(entry["path"]).strip()
        if len(text) > 10:
            entry["ocr_text"] = text
    Path(index_path).write_text(json.dumps(index, indent=2), encoding="utf-8")
```

OCR is skipped entirely if `pytesseract` / Tesseract is not installed — the pipeline continues without it.

---

### 3. Optional Visual Caption (`services/frame_captioner.py`)

Run after OCR. Uses `gpt-4o` vision to caption frames that have visual content worth describing (diagrams, slides, on-screen demos).

```python
def caption_frames(index_path: str, sample_every: int = 5) -> None:
    """
    Caption every Nth frame using the OpenAI vision API.
    Annotates index.json in place.
    sample_every: caption 1 in every N frames to control cost.
    """
```

Prompt sent to `gpt-4o`:

```
Describe what is shown in this video frame in one to two sentences.
Focus on text, diagrams, demonstrations, or anything visually informative.
If the frame shows nothing noteworthy (talking head, blank screen), respond with null.
```

Caption is stored in `entry["caption"]`. Frames where the model returns `null` keep `caption: null`.

Captioning is skipped silently if `OPENAI_API_KEY` is missing or the API call fails — pipeline continues.

---

### 4. Merging Frames into Chunks (`services/chunker.py`)

After frames are indexed, annotate each chunk in `chunks.json` with the frame IDs whose timestamps fall within the chunk's `[start, end]` window.

```python
def attach_frames_to_chunks(chunks: list[dict], index_path: str) -> list[dict]:
    """
    For each chunk, find frames whose timestamp falls within [start, end].
    Adds 'frames' key: list of {frame_id, timestamp, ocr_text, caption}.
    """
    frame_index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    for chunk in chunks:
        chunk["frames"] = [
            {
                "frame_id": f["frame_id"],
                "timestamp": f["timestamp"],
                "ocr_text": f["ocr_text"],
                "caption": f["caption"],
            }
            for f in frame_index
            if chunk["start"] <= f["timestamp"] <= chunk["end"]
        ]
    return chunks
```

Updated chunk structure:

```json
{
  "chunk_id": "chunk_003",
  "start": 120.0,
  "end": 180.0,
  "text": "...",
  "token_count": 640,
  "frames": [
    {
      "frame_id": "frame_000061",
      "timestamp": 122.0,
      "ocr_text": "Step 3: Exhale slowly over 4 counts",
      "caption": "A slide showing a numbered breathing exercise with a diagram of the diaphragm."
    }
  ]
}
```

---

### 5. Frame Context in the Q&A Pipeline (`services/qa.py`)

When formatting retrieved chunks for the answer prompts, include frame captions and OCR text if present.

```python
def format_chunk_with_frames(chunk: dict) -> str:
    lines = [f"[{chunk['chunk_id']} | {fmt_ts(chunk['start'])}–{fmt_ts(chunk['end'])}]"]
    lines.append(chunk["text"])
    for frame in chunk.get("frames", []):
        if frame.get("caption"):
            lines.append(f"  [Visual at {fmt_ts(frame['timestamp'])}: {frame['caption']}]")
        if frame.get("ocr_text"):
            lines.append(f"  [On-screen text at {fmt_ts(frame['timestamp'])}: {frame['ocr_text']}]")
    return "\n".join(lines)
```

The initial-answer and final-answer prompts already accept `formatted_chunks` — no prompt changes are needed; the frame context flows in through that string.

---

### 6. Pipeline Integration (`tasks/pipeline.py`)

Update `process_video` to pass `job_dir` to `extract_frames` and call the new annotation steps.

```python
# after extract_audio:
update_job(job_id, status=JobStatus.extracting_frames, step="extracting_frames", progress=28)
try:
    index_path = extract_frames(job_id, video_path, job_dir)
except RuntimeError as e:
    fail_job(job_id, "extracting_frames", str(e))
    return

# optional passes (both are safe to skip on failure):
try:
    run_ocr(index_path)
except Exception:
    pass

try:
    caption_frames(index_path)
except Exception:
    pass

update_job(job_id, frames_index_path=index_path, progress=33)
```

Later, when chunks are produced, call `attach_frames_to_chunks` before `embed_and_store`.

New `JobStatus` value: `extracting_frames` (add to `models/job.py`).

---

### 7. New Service: `services/frame_store.py`

Thin wrapper used by the Q&A layer to look up frames by timestamp range, without re-parsing `index.json` on every question.

```python
_frame_index: dict[str, list[dict]] = {}

def load_frame_index(job_id: str, index_path: str) -> None:
    _frame_index[job_id] = json.loads(Path(index_path).read_text(encoding="utf-8"))

def get_frames_in_range(job_id: str, start: float, end: float) -> list[dict]:
    return [
        f for f in _frame_index.get(job_id, [])
        if start <= f["timestamp"] <= end
    ]

def evict(job_id: str) -> None:
    _frame_index.pop(job_id, None)
```

---

## Error Handling

| Error | Behaviour |
|---|---|
| ffmpeg frame extraction fails | `fail_job` with step `"extracting_frames"` — hard stop |
| Tesseract not installed | Skip OCR silently; `ocr_text` stays `null` |
| Vision API call fails | Skip caption silently; `caption` stays `null` |
| `index.json` missing when merging chunks | Log warning; chunks get `"frames": []` |
| Frame store key not found | Return `[]` — Q&A continues without frame context |

---

## Deliverables

- [ ] `services/extractor.py` — implement `extract_frames`, update signature to accept `job_dir`
- [ ] `services/frame_ocr.py` — `run_ocr(index_path)` with graceful skip
- [ ] `services/frame_captioner.py` — `caption_frames(index_path, sample_every)` with graceful skip
- [ ] `services/chunker.py` — add `attach_frames_to_chunks`
- [ ] `services/frame_store.py` — in-memory frame index with `load`, `get_frames_in_range`, `evict`
- [ ] `services/qa.py` — update `format_chunk_with_frames` to include visual context
- [ ] `tasks/pipeline.py` — wire in frame extraction, OCR, caption, and chunk annotation steps
- [ ] `models/job.py` — add `extracting_frames` status and `frames_index_path` field

---

## Dependencies to Add

```
pytesseract      # OCR (requires Tesseract binary on PATH)
Pillow           # image loading for pytesseract
```

`openai` is already present (reused for vision captions).

---

## What This Does NOT Cover

- Scene-change detection (deferred — use timestamp sampling for now)
- Serving frame images to the frontend
- Storing frames in the database
- Deleting frame files after session ends (temp job directories handle this)
- Frame-level semantic search (frames are retrieved via their parent chunks, not independently)
