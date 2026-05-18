import os
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str = Security(_header)) -> None:
    """Skip auth if API_KEY env var is not set (dev/test mode)."""
    expected = os.environ.get("API_KEY")
    if expected and key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
