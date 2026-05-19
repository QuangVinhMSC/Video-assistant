# Step 5 — Persistence, Job Queue, Conversation History & Auth

## Goal

Complete the remaining backend. Replace in-memory state and the single-process task runner with durable equivalents, add per-job conversation history to support follow-up questions, and protect all endpoints with API key authentication and rate limiting.

By the end of this step the server can restart without losing job state, the pipeline can survive under concurrent uploads, and the Q&A endpoint is aware of previous turns in a session.

---

## Scope

- **5.1 Persistent job state** — SQLite via SQLModel; replaces the in-memory dict
- **5.2 Production job queue** — RQ (Redis Queue); replaces `FastAPI BackgroundTasks`
- **5.3 Persistent vector index** — FAISS index saved to disk per job; replaces the in-memory NumPy dict
- **5.4 Conversation history** — Q&A turns stored in SQLite; history passed to the final answer prompt
- **5.5 API key authentication** — `X-API-Key` header checked on all endpoints
- **5.6 Rate limiting** — per-endpoint limits via `slowapi`

---

## What Step 5 Receives from Step 4

| Component | Current state | Replaced by |
|---|---|---|
| `services/job_store.py` | `dict[str, JobState]` in memory | SQLite table via SQLModel |
| `routers/video.py` `BackgroundTasks` | In-process, lost on restart | RQ worker + Redis |
| `services/vector_store.py` | NumPy dict in memory | FAISS index on disk |
| `POST /ask/{job_id}` | Stateless, no history | Reads + writes conversation table |
| All endpoints | No auth | `X-API-Key` header required |
| All endpoints | No rate limiting | `slowapi` per-IP limits |

---

## Implementation

### 5.1 Persistent Job State

Replace `services/job_store.py` with a SQLite-backed store using **SQLModel** (SQLAlchemy + Pydantic in one).

#### 5.1.1 Database setup

Single SQLite file: `data/video_assistant.db`

```python
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///data/video_assistant.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def init_db():
    SQLModel.metadata.create_all(engine)
```

Call `init_db()` from `main.py` at startup via `lifespan`.

#### 5.1.2 Job table model

Replace `models/job.py` `JobState` (Pydantic BaseModel) with a SQLModel table model. All existing fields are preserved; the model gains `table=True` and a proper primary key.

```python
class JobState(SQLModel, table=True):
    job_id: str = Field(primary_key=True)
    status: str = "uploaded"
    step: Optional[str] = None
    progress: int = 0
    error: Optional[str] = None
    # ... all existing fields unchanged ...
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

#### 5.1.3 Updated job store API

`services/job_store.py` keeps the same function signatures — only the backing store changes. All callers (`routers/video.py`, `routers/qa.py`, tests) remain unchanged.

```python
def create_job(job_id: str, video_path: str) -> JobState: ...
def get_job(job_id: str) -> JobState | None: ...
def update_job(job_id: str, **kwargs) -> JobState: ...
def fail_job(job_id: str, step: str, error: str) -> JobState: ...
```

Each function opens a short-lived `Session`, commits, and closes. No long-lived sessions.

---

### 5.2 Production Job Queue (RQ)

Replace `FastAPI BackgroundTasks` with **RQ** (Redis Queue). RQ uses Redis as the broker and runs workers as separate processes.

#### 5.2.1 Architecture change

```
Before:                          After:
  POST /upload                     POST /upload
    └─ BackgroundTasks               └─ enqueue job to Redis
         └─ process_video()                └─ RQ worker picks it up
              (same process)                    └─ process_video()
                                                     (separate process)
```

#### 5.2.2 Enqueue from the upload endpoint

```python
from redis import Redis
from rq import Queue

redis_conn = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
task_queue = Queue(connection=redis_conn)

# In upload_video():
task_queue.enqueue(
    process_video,
    job_id, str(video_path), str(job_dir),
    job_timeout=600,
)
```

`process_video` moves to `tasks/pipeline.py` — a plain Python function, no FastAPI dependency.

#### 5.2.3 Running the worker

```bash
rq worker --with-scheduler
```

One worker process per machine is sufficient for MVP. Multiple workers can be added for concurrency without code changes.

#### 5.2.4 Redis URL config

Add to `.env`:

```
REDIS_URL=redis://localhost:6379
```

#### 5.2.5 Fallback for development

If Redis is not available (e.g. local dev without Docker), fall back to `threading.Thread` so the server still works without Redis.

```python
def _enqueue_or_thread(fn, *args):
    try:
        task_queue.enqueue(fn, *args, job_timeout=600)
    except Exception:
        import threading
        threading.Thread(target=fn, args=args, daemon=True).start()
```

---

### 5.3 Persistent Vector Index (FAISS)

Replace the in-memory NumPy dict in `services/vector_store.py` with a **FAISS** flat index saved to disk.

#### 5.3.1 Storage layout

```
temp_jobs/{job_id}/
    audio.wav
    transcript.json
    transcript.txt
    summary.md          (if generated)
    faiss.index         (NEW — FAISS binary index)
    chunks.json         (NEW — chunk metadata without embeddings)
```

#### 5.3.2 Updated vector store API

Same public signatures as Step 3. Internal implementation changes only.

```python
def embed_and_store(job_id: str, chunks: list[dict]) -> None:
    """Embed chunks, build FAISS index, save both to disk."""

def retrieve(job_id: str, query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Load FAISS index from disk, run nearest-neighbour search."""

def embed_query(query: str) -> list[float]:
    """Unchanged — single embedding call."""

def delete(job_id: str) -> None:
    """Delete faiss.index and chunks.json from disk."""
```

#### 5.3.3 FAISS index structure

Use `faiss.IndexFlatIP` (inner product = cosine similarity on unit vectors). Normalize embeddings to unit length before adding.

```python
import faiss
import numpy as np

def _save_index(job_dir: str, chunks: list[dict], embeddings: list[list[float]]):
    vecs = np.array(embeddings, dtype=np.float32)
    faiss.normalize_L2(vecs)
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)
    faiss.write_index(index, str(Path(job_dir) / "faiss.index"))
    # save chunk metadata (no embeddings) separately
    meta = [{k: v for k, v in c.items() if k != "embedding"} for c in chunks]
    (Path(job_dir) / "chunks.json").write_text(json.dumps(meta), encoding="utf-8")
```

#### 5.3.4 JobState gains `job_dir`

Add `job_dir: Optional[str] = None` to `JobState` so the vector store can locate the FAISS files without reconstructing the path.

---

### 5.4 Conversation History

Store every Q&A turn in a `Conversation` table so the final answer prompt can reference what was already asked and answered in the same session.

#### 5.4.1 Conversation table

```python
class ConversationTurn(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    turn: int                          # 1-based turn index
    question: str
    answer: str
    confidence: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

#### 5.4.2 History passed to final answer

Before the final answer call, load the last N turns for this job:

```python
history = get_conversation_history(job_id, last_n=5)
```

Format for the prompt:

```
Previous Q&A in this session:

Q1: What is this video about?
A1: The video covers vocal training techniques...

Q2: What breathing method is recommended?
A2: Diaphragmatic breathing is emphasised...
```

Append after `Initial answer:` in the final answer prompt (§4.6) with the heading `Conversation history:`.

#### 5.4.3 New service functions in `services/history.py`

```python
def save_turn(job_id: str, question: str, answer: str, confidence: str) -> None:
    """Append a completed Q&A turn to the conversation table."""

def get_conversation_history(job_id: str, last_n: int = 5) -> list[dict]:
    """Return the last N turns as list of {turn, question, answer}."""

def clear_history(job_id: str) -> None:
    """Delete all turns for this job (called by delete endpoint if added later)."""
```

#### 5.4.4 `AskResponse` gains `turn`

```python
class AskResponse(BaseModel):
    ...
    turn: int   # which turn number this answer is
```

---

### 5.5 API Key Authentication

Protect all endpoints with a static API key passed in the `X-API-Key` header.

#### 5.5.1 Config

Add to `.env`:

```
API_KEY=your-secret-key-here
```

#### 5.5.2 FastAPI dependency

```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(key: str = Security(_api_key_header)):
    if key != os.environ.get("API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
```

#### 5.5.3 Apply to all routers

Add `dependencies=[Depends(require_api_key)]` to both routers:

```python
router = APIRouter(dependencies=[Depends(require_api_key)])
```

No per-endpoint changes required.

---

### 5.6 Rate Limiting

Use **`slowapi`** (the standard rate-limiting library for FastAPI/Starlette).

#### 5.6.1 Limiter setup in `main.py`

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

#### 5.6.2 Per-endpoint limits

| Endpoint | Limit | Reason |
|---|---|---|
| `POST /upload` | 5/minute per IP | File upload is expensive |
| `GET /status/{job_id}` | 60/minute per IP | Polling — should be generous |
| `POST /ask/{job_id}` | 20/minute per IP | LLM calls have cost |

```python
@router.post("/upload")
@limiter.limit("5/minute")
async def upload_video(request: Request, ...):
```

---

### 5.7 Updated `main.py`

```python
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from db import init_db
from routers.video import router as video_router
from routers.qa import router as qa_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Video Assistant", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(video_router)
app.include_router(qa_router)
```

---

## Error Handling

| Error | HTTP status | Detail |
|---|---|---|
| Missing or invalid API key | 401 | `"Invalid or missing API key"` |
| Rate limit exceeded | 429 | `"Rate limit exceeded"` |
| Redis unavailable on upload | *(fallback to thread)* | Logged; upload still returns 200 |
| DB write failure | 500 | `"Database error: {detail}"` |
| FAISS index missing on retrieve | 500 | `"Vector index not found for job"` |

---

## Deliverables

- [ ] `db.py` — SQLite engine, `init_db()`, `get_session()`
- [ ] `models/job.py` — `JobState` as SQLModel table model (same fields + `created_at`, `updated_at`, `job_dir`)
- [ ] `models/conversation.py` — `ConversationTurn` SQLModel table model
- [ ] `services/job_store.py` — rewritten to use SQLite session; same public API
- [ ] `services/vector_store.py` — rewritten to use FAISS on disk; same public API
- [ ] `services/history.py` — `save_turn`, `get_conversation_history`, `clear_history`
- [ ] `tasks/pipeline.py` — `process_video` extracted from `routers/video.py`
- [ ] `routers/video.py` — enqueue via RQ (with thread fallback); add auth + rate limiting
- [ ] `routers/qa.py` — load history, save turn after answer; add auth + rate limiting
- [ ] `main.py` — lifespan for `init_db()`, slowapi setup, auth dependency
- [ ] `models/question.py` — `AskResponse` gains `turn` field

---

## Dependencies to Add

```
sqlmodel
rq
redis
faiss-cpu
slowapi
```

---

## What Step 5 Does NOT Cover

- Frontend / UI (separate concern)
- Multi-user account system (API key is single shared secret for now)
- Image / frame processing (deferred)
- Horizontal scaling (multiple API servers behind a load balancer)
