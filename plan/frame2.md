# Frame Step 2 — OCR

## Goal

Add an optional OCR pass over the extracted frames. Read each JPEG from the `frames/index.json` produced in Frame Step 1, run Tesseract to pull out on-screen text, and write the results back into the same index. This enriches the frame metadata so that slide text, captions, and on-screen labels are available for later chunk merging and Q&A context.

---

## Scope

- New `services/frame_ocr.py` with a single public function `run_ocr(index_path)`
- Annotate `ocr_text` on each entry in `frames/index.json` in place
- Skip frames where Tesseract returns fewer than 10 characters (noise rejection)
- Skip the entire pass silently if Tesseract is not installed — pipeline continues
- Wire the call into `tasks/pipeline.py` after frame extraction

Visual captioning is deferred to Frame Step 3.

---

## What Frame Step 2 Receives from Frame Step 1

| Source | Description |
|---|---|
| `frames_index_path` | Path to `{job_dir}/frames/index.json` — may be `None` if extraction failed |
| `frames/index.json` | List of `{frame_id, timestamp, path, ocr_text: null, caption: null}` entries |
| `{job_dir}/frames/*.jpg` | JPEG files referenced by `path` in each index entry |

If `frames_index_path` is `None` (frame extraction soft-failed in Step 1), OCR is skipped entirely.

---

## Implementation

### 2.1 New Service: `services/frame_ocr.py`

```python
import json
from pathlib import Path

try:
    import pytesseract
    from PIL import Image
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False


def run_ocr(index_path: str) -> None:
    """
    Annotate each frame entry in index.json with OCR text.
    Mutates index.json in place. No-ops if Tesseract is not installed.
    """
    if not _TESSERACT_AVAILABLE:
        return

    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    for entry in index:
        try:
            text = pytesseract.image_to_string(Image.open(entry["path"])).strip()
            if len(text) >= 10:
                entry["ocr_text"] = text
        except Exception:
            pass  # corrupt frame or Tesseract crash — skip silently
    Path(index_path).write_text(json.dumps(index, indent=2), encoding="utf-8")
```

Key decisions:

- Import guard at module level: if `pytesseract` or `Pillow` is missing, `_TESSERACT_AVAILABLE = False` and the function returns immediately — no exception propagates to the pipeline
- Per-frame `try/except` so one bad frame does not abort the rest
- 10-character threshold filters out Tesseract noise (stray letters, punctuation) on frames with no real text
- Entries where OCR yields nothing keep `"ocr_text": null`

---

### 2.2 Update `tasks/pipeline.py`

Add the import and call the OCR pass immediately after the frame extraction block.

**Add import:**

```python
from services.frame_ocr import run_ocr
```

**After the frame extraction block:**

```python
    try:
        index_path = extract_frames(job_id, video_path, job_dir)
        update_job(job_id, frames_index_path=index_path, progress=33)
    except RuntimeError as e:
        logging.warning(f"Frame extraction failed for {job_id}: {e}")
        update_job(job_id, frames_index_path=None, progress=33)
        index_path = None

    if index_path:
        try:
            run_ocr(index_path)
        except Exception as e:
            logging.warning(f"OCR pass failed for {job_id}: {e}")
```

`run_ocr` itself is already safe (returns silently if Tesseract is missing), but the outer `try/except` protects against any unexpected error reading or writing `index.json`.

---

## Error Handling

| Error | Behaviour |
|---|---|
| `pytesseract` not installed | `_TESSERACT_AVAILABLE = False` — `run_ocr` returns immediately, `ocr_text` stays `null` |
| Tesseract binary not on PATH | `pytesseract` raises on first call — caught per-frame, rest of frames continue |
| Corrupt JPEG | `Image.open` raises — caught per-frame, entry keeps `ocr_text: null` |
| `index.json` unreadable | Exception propagates to pipeline's outer `try/except` — logged as warning, pipeline continues |
| `index_path` is `None` | Guard in pipeline skips OCR entirely |

All failures are soft — the pipeline always continues to transcription.

---

## Deliverables

- [ ] `services/frame_ocr.py` — `run_ocr(index_path)` with import guard and per-frame safety
- [ ] `tasks/pipeline.py` — import `run_ocr`; call after frame extraction with `index_path` guard

---

## Dependencies to Add

```
pytesseract      # OCR (requires Tesseract binary on PATH)
Pillow           # image loading for pytesseract
```

Both are optional at runtime — the pipeline works without them.

---

## What Frame Step 2 Does NOT Cover

- Visual captioning via OpenAI vision (`services/frame_captioner.py`) — Frame Step 3
- Merging frame metadata into transcript chunks — Frame Step 4
- In-memory frame store and Q&A integration — Frame Step 4
