# Video Assistant

An AI-powered video Q&A application. Upload a video, the pipeline transcribes and indexes it, then you can ask natural-language questions and get timestamped answers grounded in the video content.

## Stack

| Layer | Tech |
|---|---|
| Backend API | FastAPI + SQLModel (SQLite) |
| Job queue | Redis Queue (RQ) with thread fallback |
| Transcription | OpenAI Whisper |
| Embeddings | OpenAI `text-embedding-3-small` + FAISS (disk) |
| Q&A | OpenAI `gpt-4o-mini` |
| Web search | DuckDuckGo (optional fallback on low-confidence answers) |
| Frontend | React 18 + Vite + Tailwind CSS v4 |

## Quick start (Docker)

**Prerequisites:** Docker, Docker Compose, an OpenAI API key.

```bash
cp .env.example .env      # add your OPENAI_API_KEY
docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

`docker compose down` stops everything. `docker compose down -v` also wipes persisted data.

## Local development (no Docker)

**Prerequisites:** Python 3.11+, Node.js 18+, ffmpeg on PATH, Redis (optional).

```bash
# backend
pip install -r requirements.txt
cp .env.example .env      # add your OPENAI_API_KEY
uvicorn main:app --reload

# frontend (separate terminal)
cd frontend
npm install
npm run dev               # http://localhost:5173
```

Redis is optional — the app falls back to threads if Redis is unavailable.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Required |
| `REDIS_URL` | `redis://localhost:6379` | Optional; threads used if Redis is down |
| `API_KEY` | _(unset)_ | Optional; if set, all requests require `X-API-Key: <value>` |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowed origin |
| `DATABASE_URL` | `sqlite:///data/video_assistant.db` | SQLite path |

When running via Docker Compose, `REDIS_URL`, `FRONTEND_ORIGIN`, and `DATABASE_URL` are set automatically — only `OPENAI_API_KEY` (and optionally `API_KEY`) need to be in `.env`.

## Project structure

```
video-assistant/
├── Dockerfile               # backend + worker image (shared)
├── docker-compose.yml       # redis, backend, worker, frontend
├── .env.example
├── main.py                  # FastAPI app entry point
├── auth.py                  # optional API key auth
├── limiter.py               # slowapi rate limiter
├── db.py                    # SQLite engine + init
├── models/                  # SQLModel + Pydantic schemas
├── routers/                 # HTTP route handlers
├── services/                # transcriber, chunker, vector store, QA, history
├── tasks/                   # background pipeline (process_video)
├── frontend/
│   ├── Dockerfile           # multi-stage: Node build → nginx serve
│   ├── nginx.conf           # proxies /upload, /status/, /ask/ to backend
│   └── src/
│       ├── api.js           # all fetch calls
│       ├── App.jsx          # root state machine
│       ├── views/           # UploadView, ProcessingView, ChatView
│       └── components/      # MessageBubble, TimestampBadge, ApiKeyGate
└── tester/                  # pytest test suite (64 tests)
```

## Processing pipeline

1. **Upload** — save file, create job record, enqueue background task
2. **Extract audio** — ffmpeg → `audio.wav`
3. **Transcribe** — Whisper → `transcript.json` + `transcript.txt`
4. **Summarize** — if transcript > 20k tokens, generate `summary.md` via gpt-4o-mini
5. **Chunk** — 750-token chunks with 125-token overlap → `chunks.json`
6. **Embed & store** — batch embed chunks → FAISS index on disk
7. **Extract topics** — gpt-4o-mini classifies parent/main topic
8. **Ready** — status set to `ready`, frontend unlocks Q&A

## Q&A flow

Each question makes three LLM calls:

1. **Classify** — determine question type and build a retrieval query
2. **Initial answer** — answer using retrieved chunks; decide if web search is needed
3. **Final answer** — synthesize answer with timestamps, video evidence, and optional search results

## Tests

```bash
# backend (64 tests)
python -m pytest tester/ -v

# frontend (10 tests)
cd frontend && npx vitest run
```
