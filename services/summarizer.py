import os
from pathlib import Path

from openai import OpenAI

_SECTIONS = (
    "# Overview",
    "# Main Topics",
    "# Key Concepts",
    "# Important Details",
    "# Step-by-step Process",
    "# Examples Mentioned",
    "# Possible User Questions",
    "# Important Timestamps",
)

_PROMPT_TEMPLATE = """\
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

Be thorough. Preserve specific names, numbers, techniques, and timestamps mentioned in the transcript.\
"""


def summarize(transcript_text: str, output_dir: str) -> str:
    """
    Generate summary.md from transcript_text via OpenAI Chat API.
    Returns path to the written file.
    Raises RuntimeError on failure.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(transcript_text=transcript_text)}],
        temperature=0.3,
    )

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("Summary generation returned an empty response")

    out_path = Path(output_dir) / "summary.md"
    out_path.write_text(content.strip(), encoding="utf-8")
    return str(out_path)
