try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None


def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Web search via DuckDuckGo. Returns list of {title, url, snippet}.
    Returns [] silently on any error — search failure must not break Q&A.
    """
    if DDGS is None:
        return []
    try:
        with DDGS() as ddgs:
            return [
                {"title": r["title"], "url": r["href"], "snippet": r["body"]}
                for r in ddgs.text(query, max_results=max_results)
            ]
    except Exception:
        return []
