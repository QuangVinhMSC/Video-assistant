import json
import os

from openai import OpenAI

_PROMPT = """\
Read the following content extracted from a video and return a JSON object.

Content:
{context_text}

Return valid JSON only. No markdown. No explanation.

{{
  "parent_topic": "<broad domain or category, e.g. music, programming, cooking>",
  "main_topic": "<specific subject of the video, e.g. vocal training, async Python, sourdough bread>",
  "confidence": "<high | medium | low>"
}}"""


def extract_topics(context_text: str, model: str = "gpt-4o-mini", api_key: str = None) -> dict:
    """
    Call OpenAI Chat API (gpt-4o-mini) to extract parent_topic, main_topic, confidence.
    Retries once on JSON parse failure.
    Raises RuntimeError on API error or two consecutive parse failures.
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("No OpenAI API key provided")

    client = OpenAI(api_key=api_key)
    prompt = _PROMPT.format(context_text=context_text)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            content = response.choices[0].message.content or ""
            return json.loads(content.strip())
        except json.JSONDecodeError:
            if attempt == 1:
                raise RuntimeError("Topic extraction returned unparseable response")
        except Exception as e:
            raise RuntimeError(f"Topic extraction failed: {e}")

    raise RuntimeError("Topic extraction returned unparseable response")
