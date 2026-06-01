import base64
import json
import os
from pathlib import Path

import openai


def caption_frames(index_path: str, sample_every: int = 5, model: str = "gpt-4o") -> None:
    """
    Caption every Nth frame using the OpenAI vision API (gpt-4o).
    Annotates index.json in place. No-ops if OPENAI_API_KEY is not set.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return

    client = openai.OpenAI()
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))

    for i, entry in enumerate(index):
        if i % sample_every != 0:
            continue
        try:
            image_data = base64.b64encode(Path(entry["path"]).read_bytes()).decode()
            response = client.chat.completions.create(
                model=model,
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}",
                                    "detail": "low",
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Describe what is shown in this video frame in one to two sentences. "
                                    "Focus on text, diagrams, demonstrations, or anything visually informative. "
                                    "If the frame shows nothing noteworthy (talking head, blank screen), respond with null."
                                ),
                            },
                        ],
                    }
                ],
            )
            text = response.choices[0].message.content.strip()
            if text.lower() not in ("null", "null.", ""):
                entry["caption"] = text
        except Exception:
            pass  # API error or bad image — skip silently

    Path(index_path).write_text(json.dumps(index, indent=2), encoding="utf-8")
