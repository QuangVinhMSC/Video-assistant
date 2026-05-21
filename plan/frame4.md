# Frame Step 4 — Chunk Merging, Frame Store & Q&A Integration

## Goal

Wire the frame metadata produced by Steps 1–3 into the rest of the pipeline. Attach frames to their matching transcript chunks, build an in-memory frame store for efficient Q&A lookups, and update the Q&A formatter so that captions and OCR text surface in model answers.

---

## Scope

- `services/chunker.py` — add `attach_frames_to_chunks`
- `services/frame_store.py` — new in-memory frame index
- `services/qa.py` — update `_format_chunks` to include frame context
- `tasks/pipeline.py` — call `attach_frames_to_chunks` between chunking and embedding

---

## What Frame Step 4 Receives from Steps 1–3

| Source | Description |
|---|---|
| `index_path` | Path to `{job_dir}/frames/index.json` — may be `None` if extraction failed |
| `frames/index.json` | Entries with `frame_id`, `timestamp`, `path`, `ocr_text`, `caption` |
| `chunks` | List of `{chunk_id, start, end, text, token_count}` from `chunk_transcript` |

If `index_path` is `None`, frame attachment is skipped and chunks keep `"frames": []`.

---

## Implementation

### 4.1 Update `services/chunker.py`

Add `attach_frames_to_chunks` after the existing `chunk_transcript` function.

```python
def attach_frames_to_chunks(chunks: list[dict], index_path: str) -> list[dict]:
    """
    Annotate each chunk with frames whose timestamp falls within [start, end].
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

Updated chunk structure after attachment:

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

### 4.2 New Service: `services/frame_store.py`

Thin in-memory wrapper so the Q&A layer can look up frames by timestamp range without re-parsing `index.json` on every question.

```python
import json
from pathlib import Path

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

### 4.3 Update `services/qa.py`

Replace `_format_chunks` (currently lines 130–136) with a version that appends frame captions and OCR text when present.

```python
def _format_chunks(chunks: list[dict]) -> str:
    lines = []
    for c in chunks:
        start = _fmt_time(c.get("start", 0))
        end = _fmt_time(c.get("end", 0))
        block = [f"[{c['chunk_id']} | {start}–{end}]", c["text"]]
        for frame in c.get("frames", []):
            ts = _fmt_time(frame["timestamp"])
            if frame.get("caption"):
                block.append(f"  [Visual at {ts}: {frame['caption']}]")
            if frame.get("ocr_text"):
                block.append(f"  [On-screen text at {ts}: {frame['ocr_text']}]")
        lines.append("\n".join(block))
    return "\n\n".join(lines)
```

No changes needed to the prompts — frame context flows in through `formatted_chunks`.

---

### 4.4 Update `tasks/pipeline.py`

**Add import** alongside the existing `chunk_transcript` import:

```python
from services.chunker import chunk_transcript, attach_frames_to_chunks
```

**After `chunk_transcript` succeeds and before `embed_and_store`**, insert the frame attachment call:

```python
    try:
        chunks = chunk_transcript(json_path)
    except RuntimeError as e:
        fail_job(job_id, "chunking", str(e))
        return

    if index_path:
        try:
            chunks = attach_frames_to_chunks(chunks, index_path)
        except Exception as e:
            logging.warning(f"Frame attachment failed for {job_id}: {e}")

    try:
        embed_and_store(job_id, chunks)
    except RuntimeError as e:
        fail_job(job_id, "embedding", f"Embedding failed: {e}")
        return
```

The `index_path` variable is already in scope from the frame extraction block earlier in `process_video`.

---

## Error Handling

| Error | Behaviour |
|---|---|
| `index_path` is `None` | `if index_path:` guard skips attachment — chunks get `"frames": []` |
| `index.json` unreadable | Exception caught by outer `try/except` — logged as warning, pipeline continues with un-annotated chunks |
| Frame timestamp outside all chunk windows | Frame is simply not attached to any chunk — no error |
| Frame store key missing in Q&A | `get_frames_in_range` returns `[]` — Q&A continues without frame context |

All failures are soft — the pipeline always continues to embedding.

---

## Deliverables

- [ ] `services/chunker.py` — add `attach_frames_to_chunks(chunks, index_path) -> list[dict]`; add `import json` if not already present
- [ ] `services/frame_store.py` — new file with `load_frame_index`, `get_frames_in_range`, `evict`
- [ ] `services/qa.py` — replace `_format_chunks` to include frame captions and OCR lines
- [ ] `tasks/pipeline.py` — import `attach_frames_to_chunks`; call after chunking, inside `if index_path:` guard, before `embed_and_store`