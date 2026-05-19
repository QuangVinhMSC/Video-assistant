# Video Assistant

An AI-powered video Q&A application. Upload a video, let the pipeline transcribe and index it, then ask natural-language questions and get timestamped answers grounded in the video content.

## Architecture

| Layer | Tech |
|---|---|
| Backend API | FastAPI + SQLModel (SQLite) |
| Job queue | Redis Queue (RQ) with thread fallback |
| Transcription | OpenAI Whisper |
| Embeddings | OpenAI `text-embedding-3-small` + FAISS (disk) |
| Q&A | OpenAI `gpt-4o-mini` (classify → retrieve → answer) |
| Web search | DuckDuckGo (optional, on low-confidence answers) |
| Frontend | React 18 + Vite + Tailwind CSS v4 |

## Features

- Upload MP4, MKV, MOV, WEBM, or AVI (up to 500 MB)
- Automatic audio extraction via ffmpeg
- Token-aware context mode: full transcript (< 20k tokens) or summary + retrieval (≥ 20k tokens)
- FAISS vector index persisted to disk per job
- Conversation history stored in SQLite with turn counter
- API key authentication (optional, via `X-API-Key` header)
- Rate limiting (5 uploads/min, 30 questions/min per IP)

## Project Structure

```
video-assistant/
├── main.py                  # FastAPI app entry point
├── auth.py                  # Optional API key auth
├── limiter.py               # slowapi rate limiter
├── db.py                    # SQLite engine + init
├── models/                  # SQLModel + Pydantic schemas
├── routers/                 # HTTP route handlers
├── services/                # Transcriber, chunker, vector store, QA, history
├── tasks/                   # Background pipeline (process_video)
├── frontend/                # React + Vite frontend
│   └── src/
│       ├── api.js           # All fetch calls
│       ├── App.jsx          # Root state machine
│       ├── views/           # UploadView, ProcessingView, ChatView
│       └── components/      # MessageBubble, TimestampBadge, ApiKeyGate
├── tester/                  # pytest test suite (64 tests)
└── plan/                    # Design docs and planning notes
```

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- ffmpeg on PATH
- OpenAI API key
- Redis (optional — falls back to threads if unavailable)

### Backend

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in OPENAI_API_KEY
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and proxies API calls to `http://localhost:8000`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Required |
| `REDIS_URL` | `redis://localhost:6379` | Optional; threads used if Redis is down |
| `API_KEY` | _(unset)_ | Optional; if set, all requests require `X-API-Key` header |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowed origin |
| `DATABASE_URL` | `sqlite:///data/video_assistant.db` | SQLite path |

## Running Tests

```bash
# Backend (64 tests)
python -m pytest tester/ -v

# Frontend (10 tests)
cd frontend && npx vitest run
```

## Pipeline Steps

1. **Upload** — save file, create job record, enqueue background task
2. **Extract audio** — ffmpeg → `audio.wav`
3. **Transcribe** — Whisper → `transcript.json` + `transcript.txt`
4. **Summarize** — if transcript > 20k tokens, generate `summary.md` via gpt-4o-mini
5. **Chunk** — 750-token chunks with 125-token overlap → `chunks.json`
6. **Embed & store** — batch embed chunks → FAISS index on disk
7. **Extract topics** — gpt-4o-mini classifies parent/main topic
8. **Ready** — status set to `ready`, frontend unlocks Q&A

## Q&A Flow

Each question goes through three LLM calls:

1. **Classify** — determine question type and build a retrieval query
2. **Initial answer** — answer using retrieved chunks; decide if web search is needed
3. **Final answer** — synthesize answer with timestamps, video evidence, and optional search results
