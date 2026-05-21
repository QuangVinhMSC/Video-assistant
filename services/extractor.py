import json
import subprocess
from pathlib import Path


def extract_audio(video_path: str, output_path: str) -> None:
    """Extract full audio track from video as 16kHz mono WAV."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def extract_frames(job_id: str, video_path: str, job_dir: str) -> str:
    """
    Extract one frame per 2 seconds from the video via ffmpeg.
    Returns path to frames/index.json.
    """
    frames_dir = Path(job_dir) / "frames"
    frames_dir.mkdir(exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "fps=0.5",
        "-q:v", "3",
        str(frames_dir / "frame_%06d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr}")

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    index = [
        {
            "frame_id": f.stem,
            "timestamp": (i + 1) * 2.0,
            "path": str(f),
            "ocr_text": None,
            "caption": None,
        }
        for i, f in enumerate(frames)
    ]
    index_path = frames_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return str(index_path)
