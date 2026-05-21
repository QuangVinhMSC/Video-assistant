# Frame Processing Progress

## Summary

5 frame steps total. **5 done, 0 remaining.**

---

## Steps

### Step 1 — Frame Extraction ✅ DONE
**Plan:** `frame1.md`

- `services/extractor.py` — `extract_frames(job_id, video_path, job_dir)` implemented
  - ffmpeg extracts 1 JPEG every 2 seconds (`fps=0.5`)
  - writes `{job_dir}/frames/index.json` with `{frame_id, timestamp, path, ocr_text: null, caption: null}` per frame
- `models/job.py` — `extracting_frames` added to `JobStatus`; `frames_index_path` field added to `JobState`
- `tasks/pipeline.py` — extraction wired with status update, soft-failure (logs warning, sets `index_path = None`, pipeline continues)

---

### Step 2 — OCR ✅ DONE
**Plan:** `frame2.md`

- `services/frame_ocr.py` — `run_ocr(index_path)` implemented
  - import guard: skips entirely if `pytesseract`/`Pillow` not installed
  - per-frame `try/except`; 10-character threshold filters noise
  - mutates `index.json` in place
- `tasks/pipeline.py` — `run_ocr` called inside `if index_path:` block with outer `try/except`

---

### Step 3 — Visual Captioning ✅ DONE
**Plan:** `frame3.md`

- `services/frame_captioner.py` — `caption_frames(index_path, sample_every=5)` implemented
  - skips entirely if `OPENAI_API_KEY` not set
  - captions every 5th frame via `gpt-4o` vision (1 caption per ~10 s of video)
  - per-frame `try/except`; model response `"null"` kept as `null`
  - mutates `index.json` in place
- `tasks/pipeline.py` — `caption_frames` called after `run_ocr` inside the same `if index_path:` block

---

### Step 4 — Chunk Merging, Frame Store & Q&A Integration ✅ DONE
**Plan:** `frame4.md`

- `services/chunker.py` — `attach_frames_to_chunks(chunks, index_path)` added; annotates each chunk with frames whose timestamp falls in `[start, end]`
- `services/frame_store.py` — new file with `load_frame_index`, `get_frames_in_range`, `evict`
- `services/qa.py` — `_format_chunks` updated to append `[Visual at ...]` and `[On-screen text at ...]` lines from frame captions and OCR
- `tasks/pipeline.py` — `attach_frames_to_chunks` called inside `if index_path:` guard after chunking, before `embed_and_store`

---

### Step 5 — Visual-Audio Reconciliation ✅ DONE
**Plan:** `frame5.md`

- `services/frame_reconciler.py` — `reconcile_chunks(chunks)` implemented
  - skips entirely if `OPENAI_API_KEY` not set
  - per-chunk: builds frame evidence from OCR + captions, calls `gpt-4o-mini` to detect transcript misheards
  - adds `corrected_text` and `visual_correction` to chunks where a clear discrepancy is found
  - original `text` is never overwritten; per-chunk `try/except` for silent failure
- `tasks/pipeline.py` — `reconcile_chunks` called inside `if index_path:` block after `attach_frames_to_chunks`, before `embed_and_store`

---

## Remaining Steps (vs. `frame_plan.md`)

**0 steps remaining.** All 8 deliverables listed in `frame_plan.md` are fully implemented:

| Deliverable | Covered by |
|---|---|
| `services/extractor.py` — `extract_frames` | Step 1 |
| `models/job.py` — `extracting_frames` status + `frames_index_path` field | Step 1 |
| `services/frame_ocr.py` — `run_ocr` | Step 2 |
| `services/frame_captioner.py` — `caption_frames` | Step 3 |
| `services/chunker.py` — `attach_frames_to_chunks` | Step 4 |
| `services/frame_store.py` — `load_frame_index`, `get_frames_in_range`, `evict` | Step 4 |
| `services/qa.py` — `_format_chunks` with frame captions and OCR | Step 4 |
| `tasks/pipeline.py` — full pipeline wiring | Steps 1–5 |

Step 5 (visual-audio reconciliation via `services/frame_reconciler.py`) was not in the original `frame_plan.md` and was added as an extension beyond the plan.
