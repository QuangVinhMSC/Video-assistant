import os
import copy

import numpy as np
from openai import OpenAI

_index: dict[str, list[dict]] = {}  # job_id → list of embedded chunk dicts

_EMBED_MODEL = "text-embedding-3-small"


def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")
    return OpenAI(api_key=api_key)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def embed_and_store(job_id: str, chunks: list[dict]) -> None:
    """Batch-embed all chunks and store in the in-memory index."""
    client = _client()
    response = client.embeddings.create(
        model=_EMBED_MODEL,
        input=[c["text"] for c in chunks],
    )
    stored = []
    for chunk, item in zip(chunks, response.data):
        entry = dict(chunk)
        entry["embedding"] = item.embedding
        stored.append(entry)
    _index[job_id] = stored


def retrieve(job_id: str, query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Return top-k chunks by cosine similarity. Embedding field is stripped from results."""
    entries = _index.get(job_id, [])
    scored = [
        (c, _cosine_similarity(query_embedding, c["embedding"]))
        for c in entries
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    results = []
    for chunk, score in scored[:top_k]:
        result = {k: v for k, v in chunk.items() if k != "embedding"}
        result["score"] = round(score, 4)
        results.append(result)
    return results


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    client = _client()
    response = client.embeddings.create(model=_EMBED_MODEL, input=[query])
    return response.data[0].embedding


def delete(job_id: str) -> None:
    """Remove all data for this job from the index."""
    _index.pop(job_id, None)
