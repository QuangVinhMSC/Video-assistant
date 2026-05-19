# Step 4 — Question Answering Pipeline

## Goal

Expose a `POST /ask/{job_id}` endpoint that accepts a user question and returns a refined, expert-level answer. The pipeline runs three sequential LLM calls — query classification, initial answer with retrieval, and final refinement — with an optional web search between the second and third calls.

---

## Scope

- New `POST /ask/{job_id}` endpoint
- Query classification (question type, retrieval strategy)
- Chunk retrieval from the in-memory vector index (built in Step 3)
- Initial answer generation with retrieval-augmented context
- Conditional web search based on `need_search` flag
- Final refined answer generation
- Structured response with timestamps and source attribution
- New request/response schemas
- New router and Q&A orchestration service

---

## What Step 4 Receives from Step 3

| Field on `JobState` | Description |
|---|---|
| `status = "ready"` | Job is ready to serve questions |
| `context_mode` | `"full_transcript"` or `"summary_plus_retrieval"` |
| `summary_path` | Path to `summary.md` (if `summary = True`) |
| `transcript_txt_path` | Path to `transcript.txt` |
| `parent_topic` | Broad domain of the video (e.g. `"music"`) |
| `main_topic` | Specific subject of the video (e.g. `"vocal training"`) |
| `_index[job_id]` | In-memory vector index of embedded chunks |

---

## API

### Request

```
POST /ask/{job_id}
Content-Type: application/json

{
  "question": "What breathing technique does the instructor recommend?"
}
```

### Response

```json
{
  "answer": "The instructor recommends diaphragmatic breathing...",
  "based_on_video": [
    "At 02:05, the instructor demonstrates abdominal expansion.",
    "The three-step exhale technique is introduced at 04:20."
  ],
  "expert_explanation": [
    "Diaphragmatic breathing increases lung capacity by...",
    "This technique is standard in classical vocal pedagogy."
  ],
  "relevant_timestamps": ["02:05–03:00", "04:20–05:10"],
  "search_note": null,
  "confidence": "high",
  "used_chunks": ["chunk_003", "chunk_004"]
}
```

For simple questions that don't need all sections, `based_on_video`, `expert_explanation`, `relevant_timestamps`, and `search_note` may be `null`.

---

## Implementation

### 4.1 Query Classification

Before retrieval, classify the question with a lightweight LLM call to determine retrieval strategy and whether web search is likely needed.

**Prompt:**

```python
prompt = f"""
Classify the following question about a video.

Question: {question}
Video topic: {main_topic}

Return valid JSON only. No markdown.

{{
  "question_type": "<video_specific|conceptual_explanation|how_to|fact_check|law_or_standard|current_information|summary_request>",
  "needs_video_evidence": true,
  "needs_external_search": false,
  "retrieval_query": "<concise rephrasing optimised for semantic search, max 15 words>"
}}
"""
```

**Question types:**

| Type | Description |
|---|---|
| `video_specific` | Asks what the video specifically says or shows |
| `conceptual_explanation` | Asks for an explanation of a concept |
| `how_to` | Asks for a process or technique |
| `fact_check` | Asks to verify a claim |
| `law_or_standard` | Involves regulations, standards, safety rules |
| `current_information` | Involves prices, software versions, recent events |
| `summary_request` | Asks for an overview of the video content |

The `retrieval_query` field is used instead of the raw question for embedding and retrieval — it strips filler words and focuses on the semantic core.

### 4.2 Global Context Selection

Build the global context string passed to both answer prompts, using `context_mode` from `JobState`:

| `context_mode` | Global context |
|---|---|
| `"summary_plus_retrieval"` | Full content of `summary.md` |
| `"full_transcript"` | Full content of `transcript.txt` |

### 4.3 Chunk Retrieval

Embed `retrieval_query` (from classification) and retrieve the top 5 chunks from the in-memory vector index.

```python
query_embedding = embed_query(classification["retrieval_query"])
chunks = retrieve(job_id, query_embedding, top_k=5)
```

Format retrieved chunks for the prompt:

```
[chunk_003 | 02:05–03:00]
The instructor demonstrates how to expand the abdomen...

[chunk_004 | 04:20–05:10]
The three-step exhale technique involves...
```

### 4.4 Initial Answer

**Prompt:**

```python
prompt = f"""
You are an expert in {parent_topic}.

The video is about {main_topic}.

Global video context:
{global_context}

Relevant transcript chunks:
{formatted_chunks}

User question:
{question}

RULES:
- Do not simply copy from the transcript.
- Use the video context as support.
- Answer with expert understanding.
- Clearly separate what comes from the video and what comes from general expertise when useful.
- If the question asks what the video specifically says, prioritize transcript evidence.
- If the question asks for advice or explanation, combine video context with expert knowledge.
- If the question relates to laws, standards, prices, timelines, software versions, new information,
  or data requiring high accuracy, set need_search to true.
- search_query must be concise and optimised for web search. Maximum 15 words.
- Return valid JSON only. Do not include markdown.

{{
  "answer": "...",
  "need_search": false,
  "search_query": null,
  "confidence": "high",
  "used_chunks": ["chunk_003", "chunk_004"]
}}
"""
```

Parse with `json.loads()`. Retry once on parse failure.

### 4.5 Supplementary Web Search

Only runs if `need_search = true`.

Use the `duckduckgo-search` package (`ddgs.text()`). No API key required.

```python
from duckduckgo_search import DDGS

def search(query: str, max_results: int = 5) -> list[dict]:
    with DDGS() as ddgs:
        return [
            {"title": r["title"], "url": r["href"], "snippet": r["body"]}
            for r in ddgs.text(query, max_results=max_results)
        ]
```

If the search raises an exception, log the error and continue with empty results — web search failure must not fail the Q&A request.

Format search results for the final prompt:

```
[1] Title of result
URL: https://...
Snippet: ...
```

### 4.6 Final Refined Answer

**Prompt:**

```python
prompt = f"""
You are an expert in {parent_topic}.

Video topic: {main_topic}

Original question:
{question}

Global video context:
{global_context}

Relevant transcript chunks:
{formatted_chunks}

Initial answer:
{initial_answer}

Supplementary search results:
{formatted_search_results or "None"}

Write the final answer using the structure below.

RULES:
- Give a clear and helpful answer.
- Use video information when relevant.
- Use external search results only if they are relevant and accurate.
- Mention timestamps when the answer depends on specific transcript chunks.
- If confidence is low, state what is uncertain.
- Return valid JSON only. No markdown outside the answer text.

{{
  "answer": "...",
  "based_on_video": ["point from video...", "..."] or null,
  "expert_explanation": ["expert point...", "..."] or null,
  "relevant_timestamps": ["02:05–03:00", "..."] or null,
  "search_note": "note about search results used" or null,
  "confidence": "high"
}}
"""
```

### 4.7 New Router: `routers/qa.py`

```
POST /ask/{job_id}
```

Steps:
1. Fetch job — return 404 if not found
2. Return 409 if `status != "ready"` (job still processing or failed)
3. Call `qa_pipeline(job, question)` from `services/qa.py`
4. Return the structured answer

### 4.8 New Service: `services/qa.py`

Orchestrates the full pipeline. One public function:

```python
def qa_pipeline(job: JobState, question: str) -> dict:
    """
    Run the full Q&A pipeline for one question.
    Returns the final structured answer dict.
    Raises RuntimeError on unrecoverable LLM failure.
    """
```

Internal call sequence:

```
classify_question(question, main_topic)
    └─ classification: {question_type, retrieval_query, ...}

build_global_context(job)
    └─ global_context: str

embed_query(classification["retrieval_query"])
    └─ query_embedding: list[float]

retrieve(job_id, query_embedding, top_k=5)
    └─ chunks: list[dict]

initial_answer(parent_topic, main_topic, global_context, chunks, question)
    └─ {answer, need_search, search_query, confidence, used_chunks}

if need_search:
    search(search_query)
        └─ search_results: list[dict]

final_answer(parent_topic, main_topic, global_context, chunks,
             question, initial_answer, search_results)
    └─ {answer, based_on_video, expert_explanation,
        relevant_timestamps, search_note, confidence}
```

### 4.9 New Service: `services/searcher.py`

```python
def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Web search via DuckDuckGo. Returns list of {title, url, snippet}.
    Returns [] silently on any error — search failure must not break Q&A.
    """
```

### 4.10 New Models: `models/question.py`

```python
class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    answer: str
    based_on_video: Optional[list[str]] = None
    expert_explanation: Optional[list[str]] = None
    relevant_timestamps: Optional[list[str]] = None
    search_note: Optional[str] = None
    confidence: Optional[str] = None
    used_chunks: Optional[list[str]] = None
```

### 4.11 Register New Router

In `main.py`, add:

```python
from routers.qa import router as qa_router
app.include_router(qa_router)
```

---

## Error Handling

| Error | HTTP status | Detail |
|---|---|---|
| Job not found | 404 | `"Job not found"` |
| Job not ready | 409 | `"Job is not ready: {current_status}"` |
| Classification LLM fails | 500 | `"Question classification failed: {detail}"` |
| Initial answer LLM fails | 500 | `"Answer generation failed: {detail}"` |
| Final answer LLM fails | 500 | `"Final answer generation failed: {detail}"` |
| Web search fails | *(silent)* | Empty results; pipeline continues |

---

## Deliverables

- [ ] `routers/qa.py` — `POST /ask/{job_id}` endpoint
- [ ] `services/qa.py` — full pipeline orchestration
- [ ] `services/searcher.py` — DuckDuckGo web search with silent failure
- [ ] `models/question.py` — `AskRequest` and `AskResponse` schemas
- [ ] `main.py` — register `qa_router`

---

## Dependencies to Add

```
duckduckgo-search
```

(`openai` already present from Steps 2 & 3.)

---

## What Step 4 Does NOT Cover

- Frontend / UI (separate concern)
- Authentication or rate limiting
- Conversation history / multi-turn Q&A
- Image/frame processing (deferred)
