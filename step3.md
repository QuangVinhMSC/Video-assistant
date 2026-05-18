# Step 3 — Chunking, Embedding & Topic Extraction

## Goal

Pick up the background task at `status = "chunking"` (set by Step 2). Split `transcript.json` into overlapping chunks, embed them into an in-memory vector index, then extract `parent_topic` and `main_topic` via an LLM call. Advance the job to `status = "ready"` so it can serve Q&A requests in Step 4.

---

## Scope

- Split `transcript.json` segments into token-bounded, overlapping chunks
- Embed all chunks in a single OpenAI batch call
- Store embeddings in an in-memory index keyed by `job_id` (no persistence)
- Extract `parent_topic`, `main_topic`, `confidence` via LLM — using `context_mode` from Step 2 to select the right input text
- Extend `JobState` with Step 3 fields
- Advance job to `status = "ready"`

---

## What Step 3 Receives from Step 2

| Field | Type | Description |
|---|---|---|
| `status` | `"chunking"` | Handoff point |
| `transcript_path` | `str` | Path to `transcript.json` |
| `transcript_txt_path` | `str` | Path to `transcript.txt` |
| `transcript_token_count` | `int` | Token count of full transcript |
| `summary` | `bool` | Whether `summary.md` was generated |
| `summary_path` | `str \| None` | Path to `summary.md` if `summary = True` |
| `context_mode` | `str` | `"full_transcript"` or `"summary_plus_retrieval"` |

---

## Implementation

### 3.1 Transcript Chunking

Read `transcript.json` (a list of `{start, end, text}` segment dicts from Step 2) and accumulate segments into chunks by token count, then slide forward with overlap.

**Chunk output structure:**

```json
{
  "chunk_id": "chunk_001",
  "start": 0.0,
  "end": 45.0,
  "text": "Today we will learn about vocal training. The first step is breathing control.",
  "token_count": 650
}
```

**Parameters:**

| Parameter | Value |
|---|---|
| Target chunk size | 750 tokens |
| Max chunk size | 1000 tokens |
| Overlap | 125 tokens |

**Algorithm:**

```
chunks = []
buffer = []          # list of segment dicts
buffer_tokens = 0
chunk_index = 0

for each segment in transcript.json:
    buffer.append(segment)
    buffer_tokens += count_tokens(segment["text"])

    if buffer_tokens >= CHUNK_SIZE:
        emit chunk:
            chunk_id  = f"chunk_{chunk_index:03d}"
            start     = buffer[0]["start"]
            end       = buffer[-1]["end"]
            text      = " ".join(s["text"] for s in buffer)
            token_count = buffer_tokens
        chunk_index += 1

        # slide forward: drop leading segments until buffer_tokens <= OVERLAP
        while buffer_tokens > OVERLAP and buffer:
            buffer_tokens -= count_tokens(buffer[0]["text"])
            buffer.pop(0)

# flush remaining buffer as a final chunk if non-empty
```

Chunks are held in memory — not written to disk.

If no chunks are produced (empty or silent transcript), raise `RuntimeError("Transcript produced no chunks")`.

### 3.2 Embedding

Embed all chunks in a **single batch API call** to avoid per-chunk latency and rate-limit risk.

- Model: `text-embedding-3-small` (1536 dimensions, cost-efficient)
- Pass all chunk texts as the `input` list

```python
response = client.embeddings.create(
    model="text-embedding-3-small",
    input=[chunk["text"] for chunk in chunks],
)
for chunk, item in zip(chunks, response.data):
    chunk["embedding"] = item.embedding
```

### 3.3 In-Memory Vector Index

Store embedded chunks in a module-level dict in `services/vector_store.py`:

```python
_index: dict[str, list[dict]] = {}  # job_id → list of embedded chunk dicts
```

No external vector database. Retrieval uses **cosine similarity** computed with NumPy.

**Retrieval result** (embedding field stripped before returning):

```json
{
  "chunk_id": "chunk_003",
  "start": 125.5,
  "end": 180.0,
  "text": "...",
  "score": 0.87
}
```

The index exists only in process memory. It is gone when the server restarts — this is intentional per the plan (temporary runtime/session storage only).

### 3.4 Topic Extraction

After embedding, call the OpenAI Chat API to determine what the video is about.

**Context text selection** — use `context_mode` from `JobState`:

| `context_mode` | Input to topic extractor |
|---|---|
| `"summary_plus_retrieval"` | Full content of `summary.md` |
| `"full_transcript"` | Full content of `transcript.txt` |
| Fallback (edge case) | First 3,000 tokens of `transcript.txt` |

**Prompt:**

```python
prompt = f"""
Read the following content extracted from a video and return a JSON object.

Content:
{context_text}

Return valid JSON only. No markdown. No explanation.

{{
  "parent_topic": "<broad domain or category, e.g. music, programming, cooking>",
  "main_topic": "<specific subject of the video, e.g. vocal training, async Python, sourdough bread>",
  "confidence": "<high | medium | low>"
}}
"""
```

Parse with `json.loads()`. If parsing fails, retry the API call once. If it fails again, raise `RuntimeError("Topic extraction returned unparseable response")`.

### 3.5 Extended JobState Fields

Add to `models/job.py`:

```python
parent_topic: Optional[str] = None
main_topic: Optional[str] = None
topic_confidence: Optional[str] = None  # "high" | "medium" | "low"
chunk_count: Optional[int] = None
```

### 3.6 Background Task — Continued

Step 3 extends `process_video` in `routers/video.py` after Step 2 sets `status = "chunking"` at `progress = 80`.

Full Step 3 sequence:

```
status = "chunking", progress = 80
  │
  ├─► chunk_transcript(transcript_path)
  │       └─ list of chunk dicts (no embeddings yet)
  │
  ├─► embed_and_store(job_id, chunks)
  │       └─ embeds all chunks in one batch, writes to _index[job_id]
  │
  ├─► update_job(chunk_count=len(chunks), progress=88)
  │
  ├─► update_job(status="embedding", step="embedding", progress=90)
  │
  ├─► select context_text from job.context_mode
  │
  ├─► extract_topics(context_text)
  │       └─ {"parent_topic": ..., "main_topic": ..., "confidence": ...}
  │
  ├─► update_job(parent_topic=..., main_topic=..., topic_confidence=..., progress=98)
  │
  └─► update_job(status="ready", step="ready", progress=100)
```

Any exception sets `status = "failed"` with the step name and error message.

### 3.7 New Service: `services/chunker.py`

```python
CHUNK_SIZE = 750   # tokens
OVERLAP = 125      # tokens

def chunk_transcript(transcript_path: str) -> list[dict]:
    """
    Read transcript.json, return list of chunk dicts:
    {chunk_id, start, end, text, token_count}.
    Raises RuntimeError if no chunks are produced.
    """
```

Uses `count_tokens` imported from `services/transcriber.py` (already exists from Step 2).

### 3.8 New Service: `services/vector_store.py`

```python
def embed_and_store(job_id: str, chunks: list[dict]) -> None:
    """Batch-embed all chunks and store in _index[job_id]."""

def retrieve(job_id: str, query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Return top-k chunks by cosine similarity. Strips embedding field."""

def embed_query(query: str) -> list[float]:
    """Embed a single query string using text-embedding-3-small."""

def delete(job_id: str) -> None:
    """Remove all data for this job from the index."""
```

### 3.9 New Service: `services/topic_extractor.py`

```python
def extract_topics(context_text: str) -> dict:
    """
    Call OpenAI Chat API (gpt-4o-mini).
    Return {"parent_topic": ..., "main_topic": ..., "confidence": ...}.
    Retries once on JSON parse failure.
    Raises RuntimeError on second failure or API error.
    """
```

---

## Progress Values (consistent with Steps 1 & 2)

| Progress | Status | Action |
|---|---|---|
| 80 | `chunking` | Received from Step 2 |
| 88 | `chunking` | Chunks created and embedded |
| 90 | `embedding` | Status label updated |
| 98 | `embedding` | Topics extracted |
| 100 | `ready` | Job complete |

---

## Error Handling

| Error | Status | Error message |
|---|---|---|
| Transcript produces no chunks | `failed` | `"Transcript produced no chunks"` |
| Embedding API fails | `failed` | `"Embedding failed: {detail}"` |
| Topic extraction API fails | `failed` | `"Topic extraction failed: {detail}"` |
| Topic JSON unparseable after retry | `failed` | `"Topic extraction returned unparseable response"` |

---

## Deliverables

- [ ] `services/chunker.py` — segment accumulator with overlap, reuses `count_tokens` from Step 2
- [ ] `services/vector_store.py` — batch embed, in-memory cosine index, retrieve, delete
- [ ] `services/topic_extractor.py` — LLM call with one retry on parse failure
- [ ] `models/job.py` — add `parent_topic`, `main_topic`, `topic_confidence`, `chunk_count`
- [ ] `routers/video.py` — `process_video` extended through to `status = "ready"`

---

## Dependencies to Add

```
numpy
```

(`openai` and `tiktoken` already present from Step 2.)

---

## What Step 3 Does NOT Cover

- Q&A endpoints and the retrieval-augmented answering pipeline (Step 4)
- Web search (Step 4)
- Image/frame processing (deferred)
