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


def extract_frames(job_id: str, video_path: str) -> None:
    pass  # deferred — image processing not in scope yet
