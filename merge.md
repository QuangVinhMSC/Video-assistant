# Video Assistant — Backend ↔ Frontend Integration Plan

## Overview

The backend (FastAPI, `localhost:8000`) and frontend (React/Vite, `localhost:5173`) are built
independently. This document lists every integration point, every contract mismatch found by
comparing source code on both sides, and the exact changes needed to make them work together.

---

## 1. Contract Map

### `POST /upload`

| Field | Backend (actual) | Frontend (expected) | Match? |
|---|---|---|---|
| Request | `multipart/form-data`, field `file` | `FormData` with `file` field | ✓ |
| Auth header | `X-API-Key` | `X-API-Key` from localStorage | ✓ |
| Success response | `{"job_id": "...", "status": "uploaded"}` | `data.job_id` | ✓ |
| 400 bad type | `{"detail": "Unsupported file type: .xxx"}` | shown in error banner | ✓ |
| 413 too large | `{"detail": "File exceeds maximum allowed size"}` | not explicitly handled | needs fix |
| 429 rate limit | `{"error": "Rate limit exceeded: ..."}` | `err.status === 429` check | ✓ |
| Size limit | **2 GB** (backend) | **500 MB** (frontend DropZone) | mismatch |

---

### `GET /status/{job_id}`

| Field | Backend (actual) | Frontend (expected) | Match? |
|---|---|---|---|
| `status` | string enum (`uploaded`…`ready`…`failed`) | `data.status` | ✓ |
| `step` | Optional[str] | `data.step` (shown in error) | ✓ |
| `error` | Optional[str] | `data.error` | ✓ |
| `parent_topic` | Optional[str] on `JobState` | `jobData?.parent_topic` | ✓ |
| `main_topic` | Optional[str] on `JobState` | `jobData?.main_topic` | ✓ |
| `progress` | `int` (0–100) set by pipeline | frontend ignores it, maps status → % itself | harmless dup |

---

### `POST /ask/{job_id}`

| Field | Backend (`AskResponse`) | Frontend (`ChatView` / `MessageBubble`) | Match? |
|---|---|---|---|
| `answer` | `str` | `data.final_answer ?? data.answer` | ✓ (fallback works) |
| `based_on_video` | `Optional[list[str]]` | `data.based_on_video ?? []` | ✓ |
| `expert_explanation` | `Optional[list[str]]` | `data.expert_explanation ?? []` | ✓ |
| `relevant_timestamps` | `Optional[list[str]]` — e.g. `["02:05-03:00"]` | expects `[{start: float, end: float}]` objects | **MISMATCH** |
| `search_note` | `Optional[str]` | frontend reads `data.search_used` (bool) | **MISMATCH** |
| `confidence` | `Optional[str]` | not rendered (ignored) | harmless |
| `used_chunks` | `Optional[list[str]]` | not rendered (ignored) | harmless |
| `turn` | `Optional[int]` | not rendered (ignored) | harmless |

---

## 2. Blockers (must fix before any request works)

### 2.1 CORS is missing

**File:** `main.py`

The browser will refuse every request from `localhost:5173` to `localhost:8000` because
FastAPI has no `CORSMiddleware`. This blocks the entire integration.

**Fix — add to `main.py`:**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)
```

For production, replace the origin with the deployed frontend URL.

---

## 3. Contract Mismatches (must fix for correct behaviour)

### 3.1 `relevant_timestamps` — string vs object

**Root cause:** The backend LLM prompt asks for strings (`"02:05-03:00"`). The frontend
`MessageBubble` iterates with `ts.start` / `ts.end` (numeric seconds) and passes them to
`TimestampBadge`, which formats seconds → `MM:SS`.

**Two options — pick one:**

**Option A (fix frontend):** Parse the string format in `MessageBubble`.  
Change in `src/components/MessageBubble.jsx`:

```jsx
// Replace:
{relevant_timestamps.map((ts, i) => (
  <TimestampBadge key={i} start={ts.start} end={ts.end} />
))}

// With:
{relevant_timestamps.map((ts, i) => {
  // ts is either a "MM:SS-MM:SS" string or a {start, end} object
  if (typeof ts === "string") {
    const [a, b] = ts.split("-");
    const parse = (t) => {
      const [m, s] = t.trim().split(":").map(Number);
      return m * 60 + s;
    };
    return <TimestampBadge key={i} start={parse(a)} end={parse(b)} />;
  }
  return <TimestampBadge key={i} start={ts.start} end={ts.end} />;
})}
```

**Option B (fix backend):** Change `AskResponse` to return objects and update the LLM prompt.  
Change in `models/question.py`:

```python
class TimestampRange(BaseModel):
    start: float
    end: float

class AskResponse(BaseModel):
    ...
    relevant_timestamps: Optional[list[TimestampRange]] = None
```

Then update the `_FINAL_PROMPT` in `services/qa.py` to ask for
`"relevant_timestamps": [{"start": 125.5, "end": 180.0}]`.

**Recommendation: Option A.** Less risky — the LLM already produces strings reliably.
Option B risks LLM non-compliance with the new format.

---

### 3.2 `search_used` vs `search_note`

**Root cause:** `AskResponse` has `search_note: Optional[str]` (a text footnote).
`ChatView` maps `search_used: data.search_used ?? false` and `MessageBubble` renders
`{search_used && <footnote>}`.

**Fix — two one-line changes in the frontend:**

In `src/views/ChatView.jsx`:
```js
// Replace:
search_used: data.search_used ?? false,

// With:
search_note: data.search_note ?? null,
```

In `src/components/MessageBubble.jsx`:
```jsx
// Replace:
const { answer, based_on_video, expert_explanation, relevant_timestamps, search_used } = content;
// ...
{search_used && (
  <p ...>Supplementary web search was used to answer this question.</p>
)}

// With:
const { answer, based_on_video, expert_explanation, relevant_timestamps, search_note } = content;
// ...
{search_note && (
  <p ...>{search_note}</p>
)}
```

---

## 4. Minor Issues (low-risk, fix before launch)

### 4.1 File size limit inconsistency

Frontend `DropZone` rejects files > 500 MB. Backend accepts up to 2 GB.

**Decision needed:** pick one limit. Recommended: align both to **500 MB** (backend already
enforces 2 GB; tighten it to 500 MB, or raise the frontend limit to 2 GB).

To tighten the backend limit, change in `routers/video.py`:
```python
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB
```

### 4.2 413 response not handled in `UploadView`

The backend returns HTTP 413 `"File exceeds maximum allowed size"` if the file slips past
the client-side guard. `api.js` already extracts `body.detail` and throws it, so it will
appear in the generic error banner — acceptable, but consider explicit messaging.

### 4.3 `data.final_answer` dead read

`ChatView.jsx` reads `data.final_answer ?? data.answer`. The backend never returns
`final_answer`. The fallback works, but the dead read is confusing. Remove it:

```js
// Replace:
answer: data.final_answer ?? data.answer ?? "No answer returned.",

// With:
answer: data.answer ?? "No answer returned.",
```

---

## 5. Environment Setup

### Backend (`.env` in project root)

```env
OPENAI_API_KEY=sk-...        # required — transcription, summarization, Q&A
API_KEY=your-secret-key      # optional — if set, all endpoints require X-API-Key header
REDIS_URL=redis://localhost:6379  # optional — falls back to threading if Redis unavailable
```

### Frontend (`frontend/.env`)

```env
VITE_API_URL=http://localhost:8000   # backend base URL
```

If `API_KEY` is set on the backend, the user must enter it in the `ApiKeyGate` modal on
first load. If `API_KEY` is not set (dev mode), the modal still appears but any value is
accepted because `auth.py` skips the check when `API_KEY` env var is absent.

---

## 6. Implementation Order

Apply changes in this order to minimise broken states:

| Step | File(s) | Change | Risk |
|---|---|---|---|
| 1 | `main.py` | Add `CORSMiddleware` | Low — additive only |
| 2 | `src/components/MessageBubble.jsx` | Fix `relevant_timestamps` parsing (Option A) | Low — isolated component |
| 3 | `src/views/ChatView.jsx` | `search_used` → `search_note` | Low — field rename |
| 4 | `src/components/MessageBubble.jsx` | `search_used` → `search_note` | Low — field rename |
| 5 | `src/views/ChatView.jsx` | Remove `data.final_answer ??` | Low — dead code removal |
| 6 | `routers/video.py` | Align `MAX_FILE_SIZE_BYTES` | Low — single constant |
| 7 | `frontend/.env` + backend `.env` | Set env vars | Config only |

---

## 7. Verification Checklist

After applying all changes:

- [ ] `POST /upload` — upload a `.mp4` from the browser; no CORS error in DevTools; `job_id` received
- [ ] `GET /status/{job_id}` — polling renders the timeline steps correctly; transitions to `ready`
- [ ] `ChatView` topic header — `parent_topic` and `main_topic` appear from status response
- [ ] `POST /ask` — answer renders with "Based on the video" and "Expert explanation" sections
- [ ] Timestamps — at least one answer shows `TimestampBadge` chips with correct `MM:SS → MM:SS` format
- [ ] `search_note` — ask a question about current software versions; confirm footnote renders
- [ ] 429 handling — exceed rate limit; "Too many requests" message appears under input
- [ ] API key gate — set `API_KEY=test` in backend `.env`; verify 401 on wrong key; gate modal saves correct key
- [ ] File type rejection — drop a `.txt` file; inline error appears without page reload
- [ ] File size rejection — attempt > 500 MB; client-side error before upload starts
