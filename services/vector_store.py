import json
import os
from pathlib import Path

import numpy as np
from openai import OpenAI

try:
    import faiss
    _USE_FAISS = True
except ImportError:
    _USE_FAISS = False

_EMBED_MODEL = "text-embedding-3-small"
_DIMS = 1536


def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")
    return OpenAI(api_key=api_key)


def _job_dir(job_id: str) -> Path:
    from services.job_store import get_job
    job = get_job(job_id)
    if job is None or not job.job_dir:
        raise RuntimeError(f"Vector index not found for job: {job_id}")
    return Path(job.job_dir)


def embed_and_store(job_id: str, chunks: list[dict]) -> None:
    """Batch-embed all chunks and persist index to disk."""
    client = _client()
    response = client.embeddings.create(
        model=_EMBED_MODEL,
        input=[c["text"] for c in chunks],
    )
    embeddings = [item.embedding for item in response.data]
    _save_index(job_id, chunks, embeddings)


def _save_index(job_id: str, chunks: list[dict], embeddings: list[list[float]]) -> None:
    job_dir = _job_dir(job_id)
    vecs = np.array(embeddings, dtype=np.float32)

    # save chunk metadata (no embeddings)
    meta = [{k: v for k, v in c.items() if k != "embedding"} for c in chunks]
    (job_dir / "chunks.json").write_text(json.dumps(meta), encoding="utf-8")

    if _USE_FAISS:
        faiss.normalize_L2(vecs)
        index = faiss.IndexFlatIP(_DIMS)
        index.add(vecs)
        faiss.write_index(index, str(job_dir / "faiss.index"))
    else:
        np.save(str(job_dir / "embeddings.npy"), vecs)


def retrieve(job_id: str, query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Load index from disk and return top-k chunks by cosine similarity."""
    job_dir = _job_dir(job_id)
    meta = json.loads((job_dir / "chunks.json").read_text(encoding="utf-8"))
    qvec = np.array(query_embedding, dtype=np.float32)

    if _USE_FAISS and (job_dir / "faiss.index").exists():
        index = faiss.read_index(str(job_dir / "faiss.index"))
        qvec_norm = qvec.reshape(1, -1).copy()
        faiss.normalize_L2(qvec_norm)
        k = min(top_k, index.ntotal)
        scores, indices = index.search(qvec_norm, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            result = dict(meta[idx])
            result["score"] = round(float(score), 4)
            results.append(result)
        return results
    else:
        # NumPy fallback
        vecs = np.load(str(job_dir / "embeddings.npy"))
        qnorm = qvec / (np.linalg.norm(qvec) + 1e-10)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10
        sims = (vecs / norms) @ qnorm
        top_idx = np.argsort(sims)[::-1][:top_k]
        return [
            {**meta[i], "score": round(float(sims[i]), 4)}
            for i in top_idx
        ]


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    client = _client()
    response = client.embeddings.create(model=_EMBED_MODEL, input=[query])
    return response.data[0].embedding


def delete(job_id: str) -> None:
    """Remove FAISS index and chunk metadata from disk."""
    try:
        job_dir = _job_dir(job_id)
        for fname in ("faiss.index", "chunks.json", "embeddings.npy"):
            p = job_dir / fname
            if p.exists():
                p.unlink()
    except Exception:
        pass


def store_embeddings_direct(job_id: str, chunks: list[dict], embeddings: list[list[float]]) -> None:
    """Test helper: persist chunks+embeddings without calling the embedding API."""
    _save_index(job_id, chunks, embeddings)
