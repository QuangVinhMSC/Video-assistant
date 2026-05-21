import json
from pathlib import Path

_frame_index: dict[str, list[dict]] = {}


def load_frame_index(job_id: str, index_path: str) -> None:
    _frame_index[job_id] = json.loads(Path(index_path).read_text(encoding="utf-8"))


def get_frames_in_range(job_id: str, start: float, end: float) -> list[dict]:
    return [
        f for f in _frame_index.get(job_id, [])
        if start <= f["timestamp"] <= end
    ]


def evict(job_id: str) -> None:
    _frame_index.pop(job_id, None)
