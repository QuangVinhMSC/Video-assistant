# Video Assistant — Improved Implementation Plan

## Overview

A web application that ingests a video file, processes its audio content, creates searchable video knowledge, and answers user questions using:

- video context
- transcript retrieval
- model expertise
- optional web search

---

# 1. Video Ingestion

Given a video file, extract:

- Full audio for transcription
- Frames sampled every 5 frames

Example:

```txt
Extract one frame every 5 frames.

Image processing is deferred for the current version.

2. Processing Job

Video processing should run as a background job.

Flow:

Upload video
→ create processing job
→ process in background
→ return job status
Job Status Example
{
  "job_id": "abc123",
  "status": "processing",
  "step": "transcription",
  "progress": 45
}

Possible statuses:

uploaded
extracting_audio
transcribing
summarizing
chunking
embedding
ready
failed

MVP:

FastAPI BackgroundTasks

Production:

Redis Queue
Celery
RQ
3. Audio Processing
3.1 Transcription

Convert audio into timestamped transcript.

Primary format:

transcript.json

Example:

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

Optional readable export:

transcript.txt

The system should internally use:

transcript.json
4. Token Check & Summary

Check whether transcript exceeds 20,000 tokens.

Condition	Action
<= 20,000 tokens	Use full transcript as global context
> 20,000 tokens	Generate summary.md and use retrieval chunks for details

Important:

Do not use summary only.
Use summary + relevant transcript chunks.
5. Summary Generation

Generate:

summary.md

Structure:

# Overview

# Main Topics

# Key Concepts

# Important Details

# Step-by-step Process

# Examples Mentioned

# Possible User Questions

# Important Timestamps

Purpose:

Summary provides global understanding
Transcript chunks provide detailed evidence
6. Transcript Chunking

Split transcript into chunks for retrieval.

Chunk structure:

{
  "chunk_id": "chunk_001",
  "start": 0.0,
  "end": 45.0,
  "text": "...",
  "token_count": 650
}

Recommended:

Chunk size: 500–1000 tokens
Overlap: 100–150 tokens
7. Embedding & Retrieval

Create embeddings for transcript chunks.

Temporary vector storage options:

ChromaDB
FAISS
SQLite vector extension
in-memory vector store

No persistent storage required.

Temporary runtime/session storage only.

Delete embeddings after session ends.

8. Runtime State

No persistent metadata is stored.

Runtime-only session state:

{
  "job_id": "abc123",
  "summary": true,
  "transcript_token_count": 42000,
  "context_mode": "summary_plus_retrieval",
  "parent_topic": "music",
  "main_topic": "vocal training",
  "status": "ready"
}
9. Topic Extraction

An LLM reads:

summary.md if available
otherwise transcript excerpt/full transcript

Return valid JSON only:

{
  "parent_topic": "music",
  "main_topic": "vocal training",
  "confidence": "high"
}
10. Question Answering Pipeline

Pipeline:

User question
→ retrieve relevant transcript chunks
→ combine with summary/global context
→ generate initial answer
→ decide whether web search is needed
→ generate final refined answer
11. Query Understanding

Before answering, classify the question.

Example:

{
  "question_type": "conceptual_explanation",
  "needs_video_evidence": true,
  "needs_external_search": false,
  "retrieval_query": "breathing control in vocal training"
}

Possible question types:

video_specific
conceptual_explanation
how_to
fact_check
law_or_standard
current_information
summary_request
12. Retrieval Step

Retrieve top relevant chunks.

Example:

{
  "top_k": 5,
  "chunks": [
    {
      "chunk_id": "chunk_003",
      "start": 125.5,
      "end": 180.0,
      "text": "...",
      "score": 0.87
    }
  ]
}

Retrieved chunks are passed to the answering model.

13. Initial Answer Prompt
prompt = f"""
You are an expert in {parent_topic}.

The video is about {main_topic}.

Global video context:
{summary_or_short_context}

Relevant transcript chunks:
{retrieved_chunks}

User question:
{question}

RULES:
- Do not simply copy from the transcript.
- Use the video context as support.
- Answer with expert understanding.
- Clearly separate what comes from the video and what comes from general expertise when useful.
- If the question asks what the video specifically says, prioritize transcript evidence.
- If the question asks for advice or explanation, combine video context with expert knowledge.
- If the question relates to laws, standards, prices, timelines, software versions, new information, or data requiring high accuracy, set need_search = true.
- Search_Query should be concise and optimized for web search. Maximum 15 words.
- Return valid JSON only. Do not include markdown.

Return:
{
  "answer": "...",
  "need_search": false,
  "search_query": null,
  "confidence": "high",
  "used_chunks": ["chunk_003", "chunk_004"]
}
"""
14. Supplementary Search

If:

"need_search": true

Perform web search.

Search result structure:

{
  "results": [
    {
      "title": "...",
      "url": "...",
      "snippet": "...",
      "source": "..."
    }
  ]
}

Search should be used for:

laws
standards
prices
current data
new technology
software versions
medical/legal/safety-critical information
15. Final Refined Answer

Final LLM receives:

original question
parent_topic
main_topic
summary/global context
retrieved transcript chunks
initial answer
search results if any

Prompt:

prompt = f"""
You are an expert in {parent_topic}.

Video topic:
{main_topic}

Original question:
{question}

Global video context:
{summary_or_short_context}

Relevant transcript chunks:
{retrieved_chunks}

Initial answer:
{initial_answer}

Supplementary search results:
{search_results}

Write the final answer.

RULES:
- Give a clear and helpful answer.
- Use video information when relevant.
- Use external search results only if they are relevant.
- Separate video-based points from expert knowledge when useful.
- Mention timestamps when the answer depends on transcript chunks.
- If confidence is low, say what is uncertain.
"""
16. Final Answer Format

Recommended response format:

## Answer

...

## Based on the video

- ...
- ...

## Expert explanation

- ...
- ...

## Relevant timestamps

- 02:05–03:00
- 04:20–05:10

## Additional search note

...

For simple questions:

## Answer

...
17. Error Handling

Handle:

video too large
unsupported file type
audio extraction failed
no audio detected
transcription failed
summary failed
embedding failed
JSON parse failed
search failed
LLM timeout
token limit exceeded

Example error response:

{
  "status": "failed",
  "step": "transcription",
  "error": "No audio stream detected in the uploaded video."
}
18. Data Flow Summary
Video File
    │
    ├─► Create Processing Job
    │
    ├─► Extract Audio
    │       │
    │       ▼
    │   Transcription
    │       │
    │       ├─► transcript.json with timestamps
    │       └─► transcript.txt
    │
    ├─► Token Check
    │       ├─ <= 20,000 tokens
    │       │      └─ use transcript as global context
    │       │
    │       └─ > 20,000 tokens
    │              └─ generate summary.md
    │
    ├─► Chunk Transcript
    │       └─ chunks with timestamps
    │
    ├─► Create Embeddings
    │       └─ temporary vector index
    │
    ├─► Topic Extraction
    │       └─ parent_topic, main_topic
    │
    └─► Ready for Questions

User Question
    │
    ├─► Question Classification
    │
    ├─► Retrieve Relevant Chunks
    │
    ├─► Initial Answer
    │       └─ answer + need_search + search_query
    │
    ├─► Optional Web Search
    │
    └─► Final Refined Answer
            └─ answer + timestamps + confidence
19. Final Architecture Notes

Current architecture type:

Context-Augmented Video Knowledge Assistant

Not just transcript QA.

Combines:

transcript understanding
semantic retrieval
expert reasoning
optional web augmentation

---

## Plan Change Note

Frame sampling rate changed from **every 5 frames** to **1 frame every 2 seconds** (`fps=0.5` in ffmpeg).
The references to "every 5 frames" in Section 1 reflect the original plan and are kept for historical record.
Current implementation in `services/extractor.py` uses the 2-second interval.