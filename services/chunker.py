import json
from pathlib import Path

from services.transcriber import count_tokens

CHUNK_SIZE = 750
OVERLAP = 125


def chunk_transcript(transcript_path: str) -> list[dict]:
    """
    Read transcript.json and return overlapping chunk dicts:
    {chunk_id, start, end, text, token_count}.
    Raises RuntimeError if no chunks are produced.
    """
    segments = json.loads(Path(transcript_path).read_text(encoding="utf-8"))

    chunks = []
    buffer: list[dict] = []
    buffer_tokens = 0
    chunk_index = 0

    for seg in segments:
        buffer.append(seg)
        buffer_tokens += count_tokens(seg["text"])

        if buffer_tokens >= CHUNK_SIZE:
            chunks.append({
                "chunk_id": f"chunk_{chunk_index:03d}",
                "start": buffer[0]["start"],
                "end": buffer[-1]["end"],
                "text": " ".join(s["text"] for s in buffer),
                "token_count": buffer_tokens,
            })
            chunk_index += 1

            # slide forward: drop leading segments until buffer is within overlap budget
            while buffer_tokens > OVERLAP and buffer:
                buffer_tokens -= count_tokens(buffer[0]["text"])
                buffer.pop(0)

    # flush remaining segments as a final chunk
    if buffer:
        chunks.append({
            "chunk_id": f"chunk_{chunk_index:03d}",
            "start": buffer[0]["start"],
            "end": buffer[-1]["end"],
            "text": " ".join(s["text"] for s in buffer),
            "token_count": buffer_tokens,
        })

    if not chunks:
        raise RuntimeError("Transcript produced no chunks")

    return chunks
