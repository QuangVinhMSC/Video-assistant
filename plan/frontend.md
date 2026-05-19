# Video Assistant — Frontend Plan

## Overview

A single-page application (SPA) that wraps the Video Assistant API. Three sequential views:
**Upload → Processing → Chat**. No routing library needed — state-driven view switching.

---

## Tech Stack

| Concern | Choice | Reason |
|---|---|---|
| Framework | React 18 (Vite) | Fast dev server, simple SPA setup |
| Styling | Tailwind CSS | Utility-first, no design system overhead |
| HTTP | `fetch` (native) | No extra dependency needed |
| State | `useState` + `useReducer` | Local state is enough; no global store needed |
| Icons | `lucide-react` | Tree-shakable, consistent style |

No TypeScript required for MVP, but add JSDoc types on API response shapes.

---

## File Structure

```
frontend/
├── index.html
├── vite.config.js
├── tailwind.config.js
├── src/
│   ├── main.jsx
│   ├── App.jsx               # view switcher
│   ├── api.js                # all fetch calls in one place
│   ├── views/
│   │   ├── UploadView.jsx
│   │   ├── ProcessingView.jsx
│   │   └── ChatView.jsx
│   └── components/
│       ├── DropZone.jsx
│       ├── StatusTimeline.jsx
│       ├── ProgressBar.jsx
│       ├── MessageBubble.jsx
│       ├── TimestampBadge.jsx
│       └── ApiKeyGate.jsx
```

---

## Views

### 1. UploadView

**Trigger:** App start, or user clicks "Upload new video".

**Layout:**
```
┌─────────────────────────────────────────┐
│  Video Assistant                        │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │                                 │    │
│  │   Drag & drop your video here   │    │
│  │   or click to browse            │    │
│  │                                 │    │
│  │   MP4 · MKV · MOV · WEBM · AVI  │    │
│  │   Max 500 MB                    │    │
│  └─────────────────────────────────┘    │
│                                         │
│  [  Upload & Analyze  ]                 │
└─────────────────────────────────────────┘
```

**Behavior:**
- Accept drag-and-drop or file picker.
- Validate file type client-side (`.mp4`, `.mkv`, `.mov`, `.webm`, `.avi`) before sending.
- Validate size < 500 MB client-side.
- Show selected filename + size after selection.
- On submit: `POST /upload` with `multipart/form-data`.
- On success (201): receive `job_id`, transition to ProcessingView.
- On error: show inline error message (file too large, wrong type, server error).

**State:**
```js
{ file, uploading, error }
```

---

### 2. ProcessingView

**Trigger:** After successful upload.

**Layout:**
```
┌─────────────────────────────────────────┐
│  Processing your video...               │
│                                         │
│  ████████████████░░░░░░  65%            │
│                                         │
│  ● uploaded          ✓                  │
│  ● extracting_audio  ✓                  │
│  ● transcribing      ● (current)        │
│  ● summarizing       ○                  │
│  ● chunking          ○                  │
│  ● embedding         ○                  │
│  ● ready             ○                  │
│                                         │
│  job_id: abc123                         │
└─────────────────────────────────────────┘
```

**Behavior:**
- Poll `GET /status/{job_id}` every 3 seconds.
- Map `status` → progress percentage:

  | status | progress |
  |---|---|
  | uploaded | 5% |
  | extracting_audio | 20% |
  | transcribing | 40% |
  | summarizing | 60% |
  | chunking | 75% |
  | embedding | 90% |
  | ready | 100% |

- Stop polling when `status === "ready"` → transition to ChatView.
- Stop polling when `status === "failed"` → show error with step and message, offer retry.
- Show elapsed time counter.
- Show `job_id` so the user can note it for later.

**State:**
```js
{ jobId, status, step, progress, elapsed, error }
```

---

### 3. ChatView

**Trigger:** `status === "ready"`.

**Layout:**
```
┌─────────────────────────────────────────┐
│  ← Upload new video                     │
│  Topic: Vocal Training  (Music)         │
├─────────────────────────────────────────┤
│                                         │
│  [assistant] Ready! Ask me anything     │
│              about this video.          │
│                                         │
│  [user]      How do I improve breath... │
│                                         │
│  [assistant] ## Answer                  │
│              ...                        │
│              ## Based on the video      │
│              - ...                      │
│              ## Relevant timestamps     │
│              02:05–03:00  04:20–05:10   │
│                                         │
│                          (loading...)   │
│                                         │
├─────────────────────────────────────────┤
│  [  Ask a question...          ] [Send] │
└─────────────────────────────────────────┘
```

**Behavior:**
- Show `parent_topic` and `main_topic` from the job status at top.
- Textarea + send button. Submit on Enter (Shift+Enter for newline).
- On submit: `POST /ask/{job_id}` with `{ "question": "..." }`.
- Show a loading indicator (three animated dots) while waiting.
- Render the response as Markdown sections (use `marked` or `react-markdown`).
- Parse `relevant_timestamps` array → render as clickable badge chips below the answer (no video seek for MVP, just visual).
- Keep full conversation history in local state and display it scrolled to bottom.
- Disable input while a request is in flight.
- On API error: show inline error under the input, do not clear the question.
- "Upload new video" link resets all state back to UploadView.

**Response rendering:**

Each assistant message is a structured object:
```js
{
  answer: "...",
  based_on_video: ["...", "..."],
  expert_explanation: ["...", "..."],
  relevant_timestamps: [{ start: 125.5, end: 180.0 }],
  search_used: false
}
```

Render as formatted sections:
- **Answer** — plain paragraph
- **Based on the video** — bulleted list (only if non-empty)
- **Expert explanation** — bulleted list (only if non-empty)
- **Relevant timestamps** — badge row: `02:05 → 03:00`
- **Search note** — small footnote (only if `search_used === true`)

**State:**
```js
{ messages, inputText, loading, error }
// messages: [{ role: "user"|"assistant", content, timestamp }]
```

---

## API Layer (`src/api.js`)

Centralise all calls here. Read the API key from `localStorage` (set via ApiKeyGate on first load).

```js
const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function headers() {
  return {
    "X-API-Key": localStorage.getItem("api_key") ?? "",
  };
}

export async function uploadVideo(file) { ... }          // POST /upload
export async function getStatus(jobId) { ... }           // GET /status/{job_id}
export async function askQuestion(jobId, question) { ... } // POST /ask/{job_id}
```

All functions throw a structured `{ status, message }` object on non-2xx so views can display it directly.

---

## Components

### `DropZone`
- Props: `onFile(file)`, `accept`, `maxBytes`
- Handles drag enter/over/leave/drop + click-to-open
- Shows drag-active highlight state
- Renders selected file name + formatted size

### `StatusTimeline`
- Props: `currentStatus`
- Renders the ordered step list with icons: ✓ done, ● current, ○ pending

### `ProgressBar`
- Props: `percent`
- Animated fill, transitions smoothly between values

### `MessageBubble`
- Props: `role`, `content` (structured response object or plain string)
- User: right-aligned, muted background
- Assistant: left-aligned, renders structured sections

### `TimestampBadge`
- Props: `start`, `end` (seconds)
- Formats as `MM:SS → MM:SS`
- Chip style, monospace font

### `ApiKeyGate`
- Shown once on first load if no key in `localStorage`
- Simple modal with a password input
- Saves to `localStorage` on confirm

---

## Environment Config

```env
# frontend/.env
VITE_API_URL=http://localhost:8000
```

For production, set `VITE_API_URL` to the deployed backend URL.

---

## Error States

| Scenario | UI Response |
|---|---|
| Wrong file type | Inline error under dropzone |
| File > 500 MB | Inline error under dropzone |
| Upload fails (5xx) | Error banner, retry button |
| Processing fails | Red status timeline, error message from `step` + `error` fields |
| Ask fails (rate limited) | "Too many requests — wait a moment" under input |
| Ask fails (job not ready) | Should not happen; show generic error |
| API key missing/wrong | ApiKeyGate modal, or 401 banner with "Update API key" link |
| Network offline | Generic "Cannot reach server" banner |

---

## Polish (Post-MVP)

- Copy answer to clipboard button
- "Was this helpful?" thumbs up/down on each answer
- Show `confidence` field from LLM response as a small badge (high / medium / low)
- Persist `job_id` to `localStorage` so the user can return to a processed video
- Mobile-responsive layout (Tailwind breakpoints)
- Dark mode toggle
