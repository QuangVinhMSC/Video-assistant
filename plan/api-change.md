# Per-step model selection

## Goal

Let the user pick from `gpt-4o-mini`, `gpt-4o`, or `gpt-5.5` for each AI step, directly in the frontend UI.

---

## Scope

Only chat-completion models are swappable. Two steps use fixed models from different families and are **not** in scope:
- Transcription → `whisper-1` (speech-to-text)
- Embeddings → `text-embedding-3-small` (embedding)

Configurable steps:

| Step | Service file | Default |
|---|---|---|
| Summarize | `services/summarizer.py` | `gpt-5.5` |
| Topic extraction | `services/topic_extractor.py` | `gpt-4o-mini` |
| Frame captioning | `services/frame_captioner.py` | `gpt-4o` |
| Frame reconciliation | `services/frame_reconciler.py` | `gpt-4o-mini` |
| Q&A (all three calls) | `services/qa.py` | `gpt-4o-mini` |

Pipeline steps (summarize, topic, frame captioning, frame reconciliation) are set **once at upload time** and stored on the job — they can't change mid-pipeline. The Q&A model is set **per question** so the user can switch models between questions in the same chat session.

---

## Backend changes

### 1. `models/job.py` — add model fields to `JobState`

```python
model_summarize: str = "gpt-5.5"
model_topic: str = "gpt-4o-mini"
model_frame_caption: str = "gpt-4o"
model_frame_reconcile: str = "gpt-4o-mini"
```

Add a new Alembic migration (or re-run `SQLModel.metadata.create_all`) if using an existing DB.

### 2. `models/question.py` — add `qa_model` to `AskRequest`

```python
class AskRequest(BaseModel):
    question: str
    qa_model: str = "gpt-4o-mini"
```

### 3. `routers/video.py` — accept model config at upload

Change the `upload_video` endpoint to accept four optional form fields alongside the file:

```python
@router.post("/upload")
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    model_summarize: str = Form("gpt-5.5"),
    model_topic: str = Form("gpt-4o-mini"),
    model_frame_caption: str = Form("gpt-4o"),
    model_frame_reconcile: str = Form("gpt-4o-mini"),
):
```

Validate each value is one of `{"gpt-4o-mini", "gpt-4o", "gpt-5.5"}` — raise HTTP 400 otherwise.

Pass the four values to `create_job` so they are persisted on `JobState`.

Pass them to `process_video` (or let the pipeline read them from the job record).

### 4. Service functions — accept a `model` parameter

Each service function gets a `model: str` keyword argument instead of a hardcoded string:

- `summarizer.summarize(transcript_text, output_dir, model="gpt-5.5")`
- `topic_extractor.extract_topics(context_text, model="gpt-4o-mini")`
- `frame_captioner.caption_frames(index_path, model="gpt-4o")`
- `frame_reconciler.reconcile_chunks(chunks, model="gpt-4o-mini")`
- `qa.qa_pipeline(..., model="gpt-4o-mini")`

Each function passes its `model` argument to the `client.chat.completions.create(model=model, ...)` call.

### 5. `tasks/pipeline.py` — read models from job and pass through

After loading the job record, read the four model fields and pass them to the relevant service calls:

```python
job = get_job(job_id)
summarize(transcript_text, job_dir, model=job.model_summarize)
extract_topics(context_text, model=job.model_topic)
caption_frames(index_path, model=job.model_frame_caption)
reconcile_chunks(chunks, model=job.model_frame_reconcile)
```

### 6. `routers/qa.py` — pass `qa_model` to the pipeline

```python
@router.post("/ask/{job_id}")
def ask(job_id: str, body: AskRequest, ...):
    ...
    answer = qa_pipeline(..., model=body.qa_model)
```

---

## Frontend changes

### 7. `App.jsx` — add model config state

```js
const MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-5.5"];

const [pipelineModels, setPipelineModels] = useState({
  summarize: "gpt-5.5",
  topic: "gpt-4o-mini",
  frame_caption: "gpt-4o",
  frame_reconcile: "gpt-4o-mini",
});
const [qaModel, setQaModel] = useState("gpt-4o-mini");
```

Pass `pipelineModels` down to `UploadView` and `qaModel`/`setQaModel` down to `ChatView`.

### 8. `views/UploadView.jsx` — model selector panel

Add a collapsible "Advanced settings" section below the file drop zone. For each pipeline step, render a labelled `<select>` populated from `MODELS`:

```
┌─────────────────────────────────────────┐
│  Advanced settings ▾                    │
│  Summarize          [gpt-5.5       ▾]   │
│  Topic extraction   [gpt-4o-mini   ▾]   │
│  Frame captioning   [gpt-4o        ▾]   │
│  Frame reconcile    [gpt-4o-mini   ▾]   │
└─────────────────────────────────────────┘
```

When the user submits the upload form, pass `pipelineModels` to `uploadVideo`.

### 9. `views/ChatView.jsx` — Q&A model selector

Add a small inline selector in the chat input area:

```
[gpt-4o-mini ▾]  [input field...]  [Send]
```

The selected model is sent with every question. No page reload needed — switching models takes effect on the next question.

### 10. `api.js` — pass models with requests

**`uploadVideo`** — append the four model values as form fields:

```js
export async function uploadVideo(file, pipelineModels) {
  const form = new FormData();
  form.append("file", file);
  form.append("model_summarize", pipelineModels.summarize);
  form.append("model_topic", pipelineModels.topic);
  form.append("model_frame_caption", pipelineModels.frame_caption);
  form.append("model_frame_reconcile", pipelineModels.frame_reconcile);
  ...
}
```

**`askQuestion`** — add `qa_model` to the JSON body:

```js
export async function askQuestion(jobId, question, qaModel) {
  ...
  body: JSON.stringify({ question, qa_model: qaModel }),
  ...
}
```

---

## File change summary

| File | Change |
|---|---|
| `models/job.py` | +4 model fields |
| `models/question.py` | +`qa_model` field |
| `routers/video.py` | accept + validate 4 Form fields |
| `routers/qa.py` | pass `qa_model` to pipeline |
| `services/summarizer.py` | `model` param |
| `services/topic_extractor.py` | `model` param |
| `services/frame_captioner.py` | `model` param |
| `services/frame_reconciler.py` | `model` param |
| `services/qa.py` | `model` param |
| `tasks/pipeline.py` | read models from job, pass through |
| `frontend/src/App.jsx` | model state |
| `frontend/src/views/UploadView.jsx` | pipeline model selectors |
| `frontend/src/views/ChatView.jsx` | Q&A model selector |
| `frontend/src/api.js` | pass models in both requests |
