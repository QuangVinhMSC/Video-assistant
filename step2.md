# Step 2 — Transcription, Token Check & Summarization

## Goal

Pick up the background task from Step 1 at `status = "transcribing"`. Convert `audio.wav` into a timestamped transcript, decide whether it exceeds the token limit, and generate a structured summary when needed. By the end of this step the job state has a `context_mode` and the text artifacts that all downstream steps depend on.

---

## Scope

- Transcribe `audio.wav` → `transcript.json` (primary) + `transcript.txt` (readable export)
- Count tokens in the transcript
- If transcript exceeds 20,000 tokens: generate `summary.md` and set `context_mode = "summary_plus_retrieval"`
- If within limit: set `context_mode = "full_transcript"`
- Extend `JobState` with new fields
- Continue the background task chain from Step 1

---

## Implementation

### 2.1 Transcription

Use **OpenAI Whisper** (local `openai-whisper` package) to transcribe `audio.wav`.

Whisper returns word/segment-level timestamps natively — use `model.transcribe()` with `word_timestamps=False` (segment level is sufficient).

**Primary output — `transcript.json`:**

```json
[
  {
    "start": 0.0,
    "end": 5.2,
    "text": "Today we will learn about vocal training..."
  },
  {
    "start": 5.2,
    "end": 12.8,
    "text": "The first step is breathing control..."
  }
]
```

**Readable export — `transcript.txt`:**

Plain concatenated text, one segment per line, with no timestamps.  
Used only for token counting and as a human-readable artifact.

Both files saved to: `temp_jobs/{job_id}/`

### 2.2 Token Counting

Count tokens in `transcript.txt` using the `tiktoken` library with the `cl100k_base` encoding (compatible with GPT-4 / embedding models).

```python
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")
token_count = len(enc.encode(text))
```

**Decision threshold: 20,000 tokens**

| Condition | `summary` flag | `context_mode` |
|---|---|---|
| `token_count <= 20,000` | `False` | `"full_transcript"` |
| `token_count > 20,000` | `True` | `"summary_plus_retrieval"` |

### 2.3 Summary Generation

Only runs when `summary = True`.

Call the OpenAI Chat API (`gpt-4o-mini` for cost efficiency) with the full transcript text and prompt it to produce a structured markdown summary.

**Output file: `summary.md`**

Required sections:

```markdown
# Overview

# Main Topics

# Key Concepts

# Important Details

# Step-by-step Process

# Examples Mentioned

# Possible User Questions

# Important Timestamps
```

The summary serves as the **global context** for all Q&A steps when the transcript is too long to fit in a prompt.

**Prompt:**

```python
prompt = f"""
You are summarizing a video transcript for use in a question-answering system.

Transcript:
{transcript_text}

Produce a structured summary in markdown with exactly these sections:
# Overview
# Main Topics
# Key Concepts
# Important Details
# Step-by-step Process
# Examples Mentioned
# Possible User Questions
# Important Timestamps

Be thorough. Preserve specific names, numbers, techniques, and timestamps mentioned in the transcript.
"""
```

### 2.4 Extended JobState Fields

Add to `models/job.py`:

```python
summary: bool = False
context_mode: Optional[str] = None        # "full_transcript" | "summary_plus_retrieval"
transcript_token_count: Optional[int] = None
transcript_path: Optional[str] = None     # path to transcript.json
transcript_txt_path: Optional[str] = None # path to transcript.txt
summary_path: Optional[str] = None        # path to summary.md (if generated)
```

### 2.5 Background Task — Continued

Step 2 extends the `process_video` function in `routers/video.py`.

After Step 1 sets `status = "transcribing"`, the task continues:

```
transcribing
  → transcribe audio.wav
  → save transcript.json + transcript.txt
  → count tokens
  → if > 20,000:
      → status = "summarizing"
      → generate summary.md
  → update job: summary, context_mode, token_count, paths
  → status = "chunking"   ← handed off to Step 3
```

If any step fails, set `status = "failed"` with the relevant error message.

### 2.6 New Service: `services/transcriber.py`

```python
def transcribe(audio_path: str, output_dir: str) -> tuple[str, str]:
    """
    Returns (transcript_json_path, transcript_txt_path).
    Runs Whisper locally.
    """

def count_tokens(text: str) -> int:
    """Returns token count using cl100k_base encoding."""
```

### 2.7 New Service: `services/summarizer.py`

```python
def summarize(transcript_text: str, output_dir: str) -> str:
    """
    Calls OpenAI Chat API to generate summary.md.
    Returns path to the generated file.
    """
```

---

## Error Handling

| Error | Status set to | Error message |
|---|---|---|
| Whisper model load failure | `failed` | `"Transcription model failed to load"` |
| Transcription produces empty text | `failed` | `"Transcription returned empty result"` |
| Summary API call fails | `failed` | `"Summary generation failed: {detail}"` |
| Summary response is empty/malformed | `failed` | `"Summary generation returned an empty response"` |

---

## Deliverables

- [ ] `services/transcriber.py` — Whisper transcription + token counting
- [ ] `services/summarizer.py` — OpenAI summary generation
- [ ] `models/job.py` — extended with Step 2 fields
- [ ] `routers/video.py` — `process_video` extended with transcription + summarization logic
- [ ] `temp_jobs/{job_id}/transcript.json` — timestamped segments
- [ ] `temp_jobs/{job_id}/transcript.txt` — plain text export
- [ ] `temp_jobs/{job_id}/summary.md` — generated only when `token_count > 20,000`

---

## Dependencies to Add

```
openai-whisper
tiktoken
openai
```

---

## What Step 2 Does NOT Cover

- Chunking and embedding (Step 3)
- Topic extraction (Step 3 or Step 4)
- Q&A pipeline (Step 4)
- Image/frame processing (deferred)
