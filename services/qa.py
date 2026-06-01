import json
import os
from pathlib import Path

from openai import OpenAI

from models.job import JobState
from services.vector_store import embed_query, retrieve
from services.searcher import search

_CLASSIFY_PROMPT = """\
Classify the following question about a video.

Question: {question}
Video topic: {main_topic}

Return valid JSON only. No markdown.

{{
  "question_type": "<video_specific|conceptual_explanation|how_to|fact_check|law_or_standard|current_information|summary_request>",
  "needs_video_evidence": true,
  "needs_external_search": false,
  "retrieval_query": "<concise rephrasing optimised for semantic search, max 15 words>"
}}\
"""

_INITIAL_PROMPT = """\
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
- If the question relates to laws, standards, prices, timelines, software versions, new information, \
or data requiring high accuracy, set need_search to true.
- search_query must be concise and optimised for web search. Maximum 15 words.
- Return valid JSON only. Do not include markdown.

{{
  "answer": "...",
  "need_search": false,
  "search_query": null,
  "confidence": "high",
  "used_chunks": ["chunk_003", "chunk_004"]
}}\
"""

_FINAL_PROMPT = """\
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
{conversation_history}
Supplementary search results:
{search_results}

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
  "based_on_video": ["point from video...", "..."],
  "expert_explanation": ["expert point...", "..."],
  "relevant_timestamps": ["02:05-03:00", "..."],
  "search_note": "note about search results used, or null",
  "confidence": "high"
}}\
"""


def _client(api_key: str = None) -> OpenAI:
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("No OpenAI API key provided")
    return OpenAI(api_key=api_key)


def _llm(prompt: str, temperature: float = 0.2, model: str = "gpt-4o-mini", api_key: str = None) -> str:
    response = _client(api_key).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return (response.choices[0].message.content or "").strip()


def _parse_json(raw: str, retry_fn, error_msg: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raw2 = retry_fn()
        try:
            return json.loads(raw2)
        except json.JSONDecodeError:
            raise RuntimeError(error_msg)


def _format_chunks(chunks: list[dict]) -> str:
    lines = []
    for c in chunks:
        start = _fmt_time(c.get("start", 0))
        end = _fmt_time(c.get("end", 0))
        block = [f"[{c['chunk_id']} | {start}–{end}]", c["text"]]
        for frame in c.get("frames", []):
            ts = _fmt_time(frame["timestamp"])
            if frame.get("caption"):
                block.append(f"  [Visual at {ts}: {frame['caption']}]")
            if frame.get("ocr_text"):
                block.append(f"  [On-screen text at {ts}: {frame['ocr_text']}]")
        lines.append("\n".join(block))
    return "\n\n".join(lines)


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for h in history:
        lines.append(f"Q{h['turn']}: {h['question']}\nA{h['turn']}: {h['answer']}")
    return "\nConversation history:\n\n" + "\n\n".join(lines) + "\n"


def _format_search_results(results: list[dict]) -> str:
    if not results:
        return "None"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}")
    return "\n\n".join(lines)


def _build_global_context(job: JobState) -> str:
    if job.context_mode == "summary_plus_retrieval" and job.summary_path:
        return Path(job.summary_path).read_text(encoding="utf-8")
    return Path(job.transcript_txt_path).read_text(encoding="utf-8")


def qa_pipeline(job: JobState, question: str, history: list[dict] = None, model: str = "gpt-4o-mini", api_key: str = None) -> dict:
    """
    Run the full Q&A pipeline for one question.
    Returns the final structured answer dict.
    Raises RuntimeError on unrecoverable LLM failure.
    """
    # Step 1 — classify
    classify_prompt = _CLASSIFY_PROMPT.format(question=question, main_topic=job.main_topic)
    raw = _llm(classify_prompt, temperature=0.0, model=model, api_key=api_key)
    classification = _parse_json(
        raw,
        lambda: _llm(classify_prompt, temperature=0.0, model=model, api_key=api_key),
        "Question classification failed: unparseable response",
    )
    retrieval_query = classification.get("retrieval_query") or question

    # Step 2 — build context and retrieve chunks
    global_context = _build_global_context(job)
    query_embedding = embed_query(retrieval_query, api_key=api_key)
    chunks = retrieve(job.job_id, query_embedding, top_k=5)
    formatted_chunks = _format_chunks(chunks)

    # Step 3 — initial answer
    initial_prompt = _INITIAL_PROMPT.format(
        parent_topic=job.parent_topic,
        main_topic=job.main_topic,
        global_context=global_context,
        formatted_chunks=formatted_chunks,
        question=question,
    )
    raw = _llm(initial_prompt, model=model, api_key=api_key)
    initial = _parse_json(
        raw,
        lambda: _llm(initial_prompt, model=model, api_key=api_key),
        "Answer generation failed: unparseable response",
    )

    # Step 4 — optional web search (failure is always silent)
    search_results: list[dict] = []
    if initial.get("need_search") and initial.get("search_query"):
        try:
            search_results = search(initial["search_query"])
        except Exception:
            search_results = []

    # Step 5 — final refined answer
    final_prompt = _FINAL_PROMPT.format(
        parent_topic=job.parent_topic,
        main_topic=job.main_topic,
        question=question,
        global_context=global_context,
        formatted_chunks=formatted_chunks,
        initial_answer=initial.get("answer", ""),
        conversation_history=_format_history(history or []),
        search_results=_format_search_results(search_results),
    )
    raw = _llm(final_prompt, model=model, api_key=api_key)
    final = _parse_json(
        raw,
        lambda: _llm(final_prompt, model=model, api_key=api_key),
        "Final answer generation failed: unparseable response",
    )

    final["used_chunks"] = initial.get("used_chunks")
    return final
