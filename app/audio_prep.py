"""Prepare uploaded media for OpenAI Whisper (25 MB limit)."""

import logging
import os
import shutil
import subprocess
import uuid

logger = logging.getLogger(__name__)

WHISPER_MAX_BYTES = 24 * 1024 * 1024  # stay under OpenAI 25 MB cap
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".webm"}


def _file_size(path: str) -> int:
    return os.path.getsize(path) if os.path.isfile(path) else 0


def _run_ffmpeg(args: list[str]) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError(
            "This video is too large for direct transcription and ffmpeg is not available on the server."
        )
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise ValueError(f"Could not extract audio from upload: {detail[:500]}")


def prepare_audio_for_whisper(file_path: str) -> str:
    """
    Return a path suitable for Whisper transcription.
    Large video/audio files are compressed to mono MP3 via ffmpeg.
    """
    if not os.path.isfile(file_path):
        raise ValueError("Uploaded file not found on server.")

    size = _file_size(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    if size <= WHISPER_MAX_BYTES and ext in AUDIO_EXTENSIONS:
        return file_path

    out_dir = os.path.dirname(file_path) or "uploads"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"whisper_{uuid.uuid4().hex}.mp3")

    logger.info(
        "Compressing upload for Whisper (%d MB, ext=%s)",
        round(size / (1024 * 1024), 1),
        ext or "none",
    )

    # Mono 64 kbps keeps long walkthrough videos under the Whisper size cap.
    _run_ffmpeg(
        [
            "-i",
            file_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            out_path,
        ]
    )

    out_size = _file_size(out_path)
    if out_size <= 0:
        raise ValueError("Audio extraction produced an empty file.")

    if out_size > WHISPER_MAX_BYTES:
        raise ValueError(
            "This file is too long even after compression. "
            "Try a shorter clip, export audio only, or use a YouTube link with captions."
        )

    logger.info("Whisper-ready audio: %d MB", round(out_size / (1024 * 1024), 1))
    return out_path
