import json
import os

from openai import OpenAI


_RECONCILE_PROMPT = """\
You are reviewing a transcript chunk alongside visual evidence from the same moment in the video.

Transcript text:
{transcript}

Visual evidence from frames in this time range:
{frame_evidence}

Decide whether the visual evidence reveals a meaningful error or gap in the transcript — \
for example, a mishearing of an on-screen term, a command name, a proper noun, or technical text \
that the speech-to-text model got wrong.

Return valid JSON only. No markdown.

{{
  "has_correction": false,
  "corrected_text": null,
  "reason": null,
  "confidence": "high"
}}

Rules:
- Set has_correction to true only if the discrepancy is clear and meaningful.
- corrected_text should be the full corrected version of the transcript text, not just the changed word.
- reason should explain what the visual evidence shows vs what the transcript says.
- confidence is "high", "medium", or "low".
- If there is no meaningful discrepancy, return has_correction: false and null for the rest.\
"""


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _build_frame_evidence(frames: list[dict]) -> str:
    lines = []
    for f in frames:
        ts = _fmt_time(f["timestamp"])
        if f.get("ocr_text"):
            lines.append(f"  OCR at {ts}: {f['ocr_text']}")
        if f.get("caption"):
            lines.append(f"  Visual at {ts}: {f['caption']}")
    return "\n".join(lines)


def reconcile_chunks(chunks: list[dict]) -> list[dict]:
    """
    Compare each chunk's transcript text against its frame OCR and captions.
    Adds corrected_text and visual_correction to chunks where a discrepancy is found.
    No-ops if OPENAI_API_KEY is not set.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return chunks

    client = OpenAI()

    for chunk in chunks:
        frames_with_content = [
            f for f in chunk.get("frames", [])
            if f.get("ocr_text") or f.get("caption")
        ]
        if not frames_with_content:
            continue

        frame_evidence = _build_frame_evidence(frames_with_content)
        prompt = _RECONCILE_PROMPT.format(
            transcript=chunk["text"],
            frame_evidence=frame_evidence,
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300,
            )
            raw = (response.choices[0].message.content or "").strip()
            result = json.loads(raw)
            if result.get("has_correction"):
                chunk["corrected_text"] = result.get("corrected_text")
                chunk["visual_correction"] = {
                    "has_correction": True,
                    "reason": result.get("reason"),
                    "confidence": result.get("confidence", "medium"),
                }
        except Exception:
            pass  # LLM error or JSON parse failure — skip this chunk silently

    return chunks
