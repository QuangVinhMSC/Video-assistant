# Step 1 — Video Ingestion & Processing Job

## Goal

Accept a video file upload, spin up a background processing job, and extract the audio track. This step produces the raw audio that all downstream steps depend on.

---

## Scope

- FastAPI application scaffold
- Video upload endpoint
- Background job creation and status tracking
- Audio extraction from video
- Frame extraction (stubbed — image processing is deferred)

---

## Implementation

### 1.1 FastAPI App Scaffold

Create the base FastAPI application with a single router for video processing.

Entry point: `main.py`  
Router: `routers/video.py`

### 1.2 Upload Endpoint

```
POST /upload
```

Accepts a video file (multipart form data).

On receipt:
1. Validate file type (accept: `.mp4`, `.mkv`, `.mov`, `.webm`, `.avi`)
2. Validate file size (reject if over configured limit)
3. Save video to a temp directory under a unique `job_id`
4. Create a job state object and store it in memory
5. Launch background processing task
6. Return `job_id` and initial status immediately

**Response:**

```json
{
  "job_id": "abc123",
  "status": "uploaded"
}
```

### 1.3 Job Status Endpoint

```
GET /status/{job_id}
```

Returns current job state.

**Response:**

```json
{
  "job_id": "abc123",
  "status": "extracting_audio",
  "step": "extracting_audio",
  "progress": 20
}
```

**Possible statuses (in order):**

```
uploaded → extracting_audio → transcribing → summarizing → chunking → embedding → ready → failed
```

### 1.4 In-Memory Job Store

A simple dict keyed by `job_id` holds runtime state for each session.

```python
jobs: dict[str, dict] = {}
```

No database. State is lost when the server restarts (acceptable for MVP).

### 1.5 Background Task

Use `FastAPI BackgroundTasks` to run processing after the upload response is returned.

Background task sequence (Step 1 covers only the first two):

1. Update status → `extracting_audio`
2. **Extract audio** from video file → save as `audio.wav` in the job temp dir
3. Update status → `transcribing`
4. *(Transcription and beyond handled in Step 2)*

If any step fails, set `status = "failed"` with an error message.

### 1.6 Audio Extraction

Use `ffmpeg` via `subprocess` or the `ffmpeg-python` wrapper.

Extract:
- Full audio track
- Format: WAV (16kHz mono — standard for speech-to-text)
- Output: `jobs/{job_id}/audio.wav`

### 1.7 Frame Extraction (Stub)

Extract one frame every 5 frames from the video.

For Step 1, this is **stubbed** — write the function signature but do not implement processing logic. Image processing is deferred to a later step.

```python
def extract_frames(job_id: str, video_path: str):
    pass  # deferred — image processing not in scope yet
```

---

## Error Handling

| Error | Status set to | Error message |
|---|---|---|
| Unsupported file type | `failed` | `"Unsupported file type: {ext}"` |
| File too large | `failed` | `"File exceeds maximum allowed size"` |
| No audio stream in video | `failed` | `"No audio stream detected in the uploaded video"` |
| ffmpeg extraction error | `failed` | `"Audio extraction failed: {detail}"` |

---

## Deliverables

- [ ] `main.py` — FastAPI app entry point
- [ ] `routers/video.py` — upload and status endpoints
- [ ] `services/job_store.py` — in-memory job state management
- [ ] `services/extractor.py` — audio extraction logic, frame extraction stub
- [ ] `models/job.py` — job state schema (Pydantic)

---

## What Step 1 Does NOT Cover

- Transcription (Step 2)
- Summarization and token check (Step 2)
- Chunking and embedding (Step 3)
- Topic extraction and Q&A (Step 4)
- Image/frame processing (deferred)
