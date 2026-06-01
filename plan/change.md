# Dockerise Video Assistant

## Goal

Run the full stack (backend, frontend, Redis, RQ worker) with a single `docker compose up`.

---

## Files to create

### `Dockerfile` — backend + RQ worker (shared image)

```dockerfile
FROM python:3.11-slim

# ffmpeg for audio extraction, whisper needs it at runtime
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# data/ holds SQLite DB and FAISS indexes — mount as a volume at runtime
RUN mkdir -p data
```

No `CMD` here; `docker-compose.yml` sets the command per service so the same image runs as either the API server or the RQ worker.

---

### `frontend/Dockerfile` — multi-stage React build

```dockerfile
# Stage 1: build
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build          # output → /app/dist

# Stage 2: serve with nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

---

### `frontend/nginx.conf` — proxy API calls to backend

```nginx
server {
    listen 80;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 500m;   # match upload limit
    }

    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

---

### `docker-compose.yml`

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped

  backend:
    build: .
    command: uvicorn main:app --host 0.0.0.0 --port 8000
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
      FRONTEND_ORIGIN: http://localhost
      DATABASE_URL: sqlite:///data/video_assistant.db
    volumes:
      - app_data:/app/data
      - app_jobs:/app/temp_jobs
    ports:
      - "8000:8000"
    depends_on:
      - redis

  worker:
    build: .
    command: rq worker --url redis://redis:6379
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
    volumes:
      - app_data:/app/data
      - app_jobs:/app/temp_jobs
    depends_on:
      - redis

  frontend:
    build: frontend
    ports:
      - "80:80"
    depends_on:
      - backend

volumes:
  app_data:
  app_jobs:
```

---

### `.dockerignore`

```
__pycache__/
*.pyc
.env
data/
temp_jobs/
videofile.mp4
frontend/node_modules/
frontend/dist/
tester/
plan/
.git/
```

---

## Code changes required

### 1. `frontend/vite.config.js` — remove dev proxy

The Vite proxy (`/api → localhost:8000`) is only needed for `npm run dev`. In the Docker build nginx handles proxying, so no change needed — but confirm the React `api.js` prefixes all calls with `/api/` (not a hardcoded `localhost:8000` URL).

Check `frontend/src/api.js`: every `fetch` call should use a relative path like `/api/videos/...`. If any call uses an absolute `http://localhost:8000` URL, change it to the relative form.

### 2. `tasks/process_video.py` (or wherever the RQ task is registered)

RQ workers discover tasks by import path. Confirm the worker command (`rq worker`) is invoked from `/app` so Python imports resolve. No code change needed if the working directory is correct — the `docker-compose.yml` above sets `WORKDIR /app` via the Dockerfile.

### 3. `db.py` — ensure `data/` directory is created at startup

SQLite will fail if `data/` doesn't exist inside the container. The `init_db()` call in `main.py` lifespan should create the directory before opening the connection:

```python
import os
os.makedirs("data", exist_ok=True)
```

Add this line at the top of `init_db()` if it isn't there already.

### 4. `.env.example` — add Docker-specific notes

Document that `REDIS_URL`, `FRONTEND_ORIGIN`, and `DATABASE_URL` are overridden by `docker-compose.yml` and don't need to be set in `.env` when running via Compose.

---

## Build & run

```bash
# first time (or after dependency changes)
docker compose build

# start everything
docker compose up -d

# view logs
docker compose logs -f

# stop
docker compose down
```

App is then accessible at `http://localhost` (frontend) and `http://localhost:8000` (API direct).

---

## Verification checklist

- [ ] `docker compose up` starts all four services without errors
- [ ] Frontend loads at `http://localhost`
- [ ] Upload a video; job appears in `backend` logs and worker picks it up
- [ ] Q&A works after processing completes
- [ ] `docker compose down && docker compose up` retains processed jobs (volumes persist)
- [ ] `docker compose down -v` cleanly wipes all state
