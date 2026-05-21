# Frame Step 5 — Visual-Audio Reconciliation

## Goal

Use the OCR text and visual captions attached to each chunk (produced in Step 4) to detect where the audio transcript misheard or misrepresented on-screen content. For each chunk where a discrepancy is found, store a `corrected_text` and a `visual_correction` record alongside the original transcript. The original text is never overwritten.

---

## Scope

- New `services/frame_reconciler.py` with a single public function `reconcile_chunks`
- Call an LLM to compare each chunk's transcript text against its frame OCR and captions
- Add `corrected_text` and `visual_correction` fields to chunks where a correction is warranted
- Skip chunks that have no frame content (no OCR, no caption)
- Skip the entire pass silently if `OPENAI_API_KEY` is not set or the call fails
- Wire the call into `tasks/pipeline.py` after `attach_frames_to_chunks`, before `embed_and_store`

---

## What Frame Step 5 Receives from Step 4

| Source | Description |
|---|---|
| `chunks` | List of chunks, each with `frames: [{frame_id, timestamp, ocr_text, caption}]` attached |
| `index_path` | Used as the gate — if `None`, no frames are attached and reconciliation is skipped |

Chunks with no frames, or frames where both `ocr_text` and `caption` are `null`, are skipped — nothing to compare against.

---

## Implementation

### 5.1 New Service: `services/frame_reconciler.py`

```python
import json
import os

from openai import OpenAI


_RECONCILE_PROMPT = """\
You are reviewing a transcript chunk alongside visual evidence from the same moment in the video.

Transcript text:
{transcript}

Visual evidence from frames in this time range:
{frame_evidence}

Decide whether the visual evidence reveals a meaningful error or gap in the transcript — \
for example, a mishearing of an on-screen term, a command name, a proper noun, or technical text \
that the speech-to-text model got wrong.

Return valid JSON only. No markdown.

{{
  "has_correction": false,
  "corrected_text": null,
  "reason": null,
  "confidence": "high"
}}

Rules:
- Set has_correction to true only if the discrepancy is clear and meaningful.
- corrected_text should be the full corrected version of the transcript text, not just the changed word.
- reason should explain what the visual evidence shows vs what the transcript says.
- confidence is "high", "medium", or "low".
- If there is no meaningful discrepancy, return has_correction: false and null for the rest.\
"""


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _build_frame_evidence(frames: list[dict]) -> str:
    lines = []
    for f in frames:
        ts = _fmt_time(f["timestamp"])
        if f.get("ocr_text"):
            lines.append(f"  OCR at {ts}: {f['ocr_text']}")
        if f.get("caption"):
            lines.append(f"  Visual at {ts}: {f['caption']}")
    return "\n".join(lines)


def reconcile_chunks(chunks: list[dict]) -> list[dict]:
    """
    Compare each chunk's transcript text against its frame OCR and captions.
    Adds corrected_text and visual_correction to chunks where a discrepancy is found.
    No-ops if OPENAI_API_KEY is not set.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return chunks

    client = OpenAI()

    for chunk in chunks:
        frames_with_content = [
            f for f in chunk.get("frames", [])
            if f.get("ocr_text") or f.get("caption")
        ]
        if not frames_with_content:
            continue

        frame_evidence = _build_frame_evidence(frames_with_content)
        prompt = _RECONCILE_PROMPT.format(
            transcript=chunk["text"],
            frame_evidence=frame_evidence,
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300,
            )
            raw = (response.choices[0].message.content or "").strip()
            result = json.loads(raw)
            if result.get("has_correction"):
                chunk["corrected_text"] = result.get("corrected_text")
                chunk["visual_correction"] = {
                    "has_correction": True,
                    "reason": result.get("reason"),
                    "confidence": result.get("confidence", "medium"),
                }
        except Exception:
            pass  # LLM error or JSON parse failure — skip this chunk silently

    return chunks
```

---

### 5.2 Updated Chunk Structure

```json
{
  "chunk_id": "chunk_003",
  "start": 120.0,
  "end": 180.0,
  "text": "...original transcript text...",
  "corrected_text": "...corrected version if applicable...",
  "token_count": 640,
  "frames": [...],
  "visual_correction": {
    "has_correction": true,
    "reason": "OCR shows 'Ctrl + C' while transcript says 'control sea'",
    "confidence": "high"
  }
}
```

Chunks without a correction keep no `corrected_text` or `visual_correction` keys.

---

### 5.3 Update `tasks/pipeline.py`

**Add import** alongside the frame-related imports:

```python
from services.frame_reconciler import reconcile_chunks
```

**After `attach_frames_to_chunks` and before `embed_and_store`:**

```python
    if index_path:
        try:
            chunks = attach_frames_to_chunks(chunks, index_path)
        except Exception as e:
            logging.warning(f"Frame attachment failed for {job_id}: {e}")
        try:
            chunks = reconcile_chunks(chunks)
        except Exception as e:
            logging.warning(f"Visual reconciliation failed for {job_id}: {e}")

    try:
        embed_and_store(job_id, chunks)
    ...
```

Reconciliation is nested inside the same `if index_path:` block — no frames means nothing to reconcile.

---

## Error Handling

| Error | Behaviour |
|---|---|
| `OPENAI_API_KEY` not set | `reconcile_chunks` returns chunks unchanged immediately |
| LLM returns unparseable JSON | `json.loads` raises — caught per-chunk, chunk is left unchanged |
| LLM finds no discrepancy | `has_correction: false` — chunk is left unchanged, no keys added |
| Chunk has no frame content | Skipped by `frames_with_content` guard |

All failures are soft — the pipeline always continues to embedding.

---

## Deliverables

- [ ] `services/frame_reconciler.py` — `reconcile_chunks(chunks) -> list[dict]` with API key guard and per-chunk safety
- [ ] `tasks/pipeline.py` — import `reconcile_chunks`; call inside `if index_path:` block after `attach_frames_to_chunks`, before `embed_and_store`
