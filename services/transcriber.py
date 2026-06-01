import json
import os
from pathlib import Path

import tiktoken
from openai import OpenAI


def transcribe(audio_path: str, output_dir: str, api_key: str = None) -> tuple[str, str]:
    """
    Transcribe audio_path via OpenAI Whisper API.
    Returns (transcript_json_path, transcript_txt_path).
    Raises RuntimeError on failure.
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("No OpenAI API key provided")

    client = OpenAI(api_key=api_key)

    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
        )

    segments = getattr(response, "segments", None) or []
    full_text = getattr(response, "text", "") or ""

    if not full_text.strip():
        raise RuntimeError("Transcription returned empty result")

    # Segments are TranscriptionSegment Pydantic objects — use attribute access
    transcript_data = [
        {
            "start": round(float(s.start), 3),
            "end": round(float(s.end), 3),
            "text": str(s.text).strip(),
        }
        for s in segments
    ] if segments else [{"start": 0.0, "end": 0.0, "text": full_text.strip()}]

    out = Path(output_dir)

    json_path = out / "transcript.json"
    json_path.write_text(json.dumps(transcript_data, ensure_ascii=False, indent=2), encoding="utf-8")

    txt_path = out / "transcript.txt"
    txt_path.write_text("\n".join(s["text"] for s in transcript_data), encoding="utf-8")

    return str(json_path), str(txt_path)


def count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))
