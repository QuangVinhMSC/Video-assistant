# Frame Step 3 — Visual Captioning

## Goal

Add an optional captioning pass that sends every Nth frame to the OpenAI vision API (`gpt-4o`) and writes a one-to-two sentence description back into `frames/index.json`. Frames are sampled to control cost; uninteresting frames (talking heads, blank screens) where the model returns `null` are skipped. All failures are soft — the pipeline always continues.

---

## Scope

- New `services/frame_captioner.py` with a single public function `caption_frames(index_path, sample_every=5)`
- Read JPEGs from `index.json`, base64-encode them, and call `gpt-4o` with a vision prompt
- Write captions back to `index.json` in place; entries that are skipped or return null keep `"caption": null`
- Skip the entire pass silently if `OPENAI_API_KEY` is not set, or on any per-frame failure
- Wire the call into `tasks/pipeline.py` after the OCR pass

Chunk merging and Q&A integration are deferred to Frame Step 4.

---

## What Frame Step 3 Receives from Frame Steps 1 & 2

| Source | Description |
|---|---|
| `index_path` | Path to `{job_dir}/frames/index.json` — may be `None` if extraction failed |
| `frames/index.json` | Entries with `ocr_text` already populated by Frame Step 2 (or `null` if OCR was skipped) |
| `{job_dir}/frames/*.jpg` | JPEG files referenced by `path` in each index entry |

If `index_path` is `None` the pass is skipped entirely by the existing pipeline guard (`if index_path:`).

---

## Implementation

### 3.1 New Service: `services/frame_captioner.py`

```python
import base64
import json
import os
from pathlib import Path

import openai


def caption_frames(index_path: str, sample_every: int = 5) -> None:
    """
    Caption every Nth frame using the OpenAI vision API (gpt-4o).
    Annotates index.json in place. No-ops if OPENAI_API_KEY is not set.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return

    client = openai.OpenAI()
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))

    for i, entry in enumerate(index):
        if i % sample_every != 0:
            continue
        try:
            image_data = base64.b64encode(Path(entry["path"]).read_bytes()).decode()
            response = client.chat.completions.create(
                model="gpt-4o",
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}",
                                    "detail": "low",
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Describe what is shown in this video frame in one to two sentences. "
                                    "Focus on text, diagrams, demonstrations, or anything visually informative. "
                                    "If the frame shows nothing noteworthy (talking head, blank screen), respond with null."
                                ),
                            },
                        ],
                    }
                ],
            )
            text = response.choices[0].message.content.strip()
            if text.lower() not in ("null", "null.", ""):
                entry["caption"] = text
        except Exception:
            pass  # API error or bad image — skip silently

    Path(index_path).write_text(json.dumps(index, indent=2), encoding="utf-8")
```

Key decisions:

| Decision | Reason |
|---|---|
| `detail: "low"` | Cheaper and faster; sufficient for detecting slides/diagrams |
| `max_tokens=100` | Captions are 1–2 sentences; longer output wastes tokens |
| `sample_every=5` default | 1 frame/2s × every 5th = 1 caption per 10s of video — balances cost and coverage |
| Null check on response text | Model returns the string `"null"` for boring frames — normalise to `None` |
| Per-frame `try/except` | One bad image or transient API error must not abort the rest |
| API key guard at entry | Entire pass is skipped cleanly if the env var is absent |

Sampling pattern with the default `sample_every=5` and `fps=0.5`:

| Frame index (0-based) | Captioned? | Timestamp |
|---|---|---|
| 0 (frame_000001) | yes | 2.0 s |
| 1–4 | no | 4.0–10.0 s |
| 5 (frame_000006) | yes | 12.0 s |
| 6–9 | no | 14.0–20.0 s |

---

### 3.2 Update `tasks/pipeline.py`

Add the import and wire the captioning call inside the existing `if index_path:` block, after OCR.

**Add import** (alongside the `run_ocr` import):

```python
from services.frame_captioner import caption_frames
```

**Updated `if index_path:` block:**

```python
    if index_path:
        try:
            run_ocr(index_path)
        except Exception as e:
            logging.warning(f"OCR pass failed for {job_id}: {e}")
        try:
            caption_frames(index_path)
        except Exception as e:
            logging.warning(f"Caption pass failed for {job_id}: {e}")
```

`caption_frames` is already safe (returns on missing API key, per-frame try/except), but the outer guard keeps the pattern consistent with the OCR call.

---

## Error Handling

| Error | Behaviour |
|---|---|
| `OPENAI_API_KEY` not set | `caption_frames` returns immediately — `caption` stays `null` |
| API rate limit or network error on a frame | Caught per-frame — that entry keeps `caption: null`, rest continue |
| `gpt-4o` response is `"null"` or empty | Treated as no caption — entry keeps `caption: null` |
| JPEG file missing or unreadable | `Path.read_bytes()` raises — caught per-frame |
| `index.json` unreadable | Exception propagates to outer `try/except` — logged, pipeline continues |

All failures are soft — the pipeline always continues to transcription.

---

## Deliverables

- [ ] `services/frame_captioner.py` — `caption_frames(index_path, sample_every=5)` with API key guard and per-frame safety
- [ ] `tasks/pipeline.py` — import `caption_frames`; call inside the `if index_path:` block after `run_ocr`

---

## Dependencies

`openai` is already installed. `base64` is stdlib. No new packages required.

---

## What Frame Step 3 Does NOT Cover

- Merging frame metadata (`ocr_text`, `caption`) into transcript chunks — Frame Step 4
- In-memory frame store for Q&A lookups — Frame Step 4
- Q&A prompt changes to include frame context — Frame Step 4
