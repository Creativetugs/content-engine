import os
import re
import uuid
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from app.youtube import (
    ANSI_ESCAPE,
    PLAYER_CLIENT_FALLBACKS,
    _build_ydl_opts,
    _clean_error,
    _resolve_download_path,
    is_valid_youtube_url,
)

MEDIA_URL_PATTERN = re.compile(
    r"(https?://)?("
    r"(www\.)?(youtube\.com/(watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"|(www\.)?vimeo\.com/"
    r"|(www\.)?loom\.com/share/"
    r")[\w\-/?=&%.]+",
    re.IGNORECASE,
)

SOURCE_LABELS = {
    "youtube": "YouTube Video",
    "vimeo": "Vimeo Video",
    "loom": "Loom Recording",
}


def is_valid_media_url(url: str) -> bool:
    return bool(url.strip() and MEDIA_URL_PATTERN.search(url.strip()))


def detect_media_source(url: str) -> str:
    url = url.strip().lower()
    if "vimeo.com" in url:
        return "vimeo"
    if "loom.com" in url:
        return "loom"
    if is_valid_youtube_url(url):
        return "youtube"
    return "unknown"


def download_media_audio(url: str, output_dir: str = "uploads") -> dict[str, Any]:
    """Download audio from YouTube, Vimeo, or Loom via yt-dlp."""
    if not is_valid_media_url(url):
        raise ValueError(
            "Invalid media URL. Supported: youtube.com, youtu.be, vimeo.com, loom.com/share"
        )

    source = detect_media_source(url)
    if source == "unknown":
        raise ValueError("Unsupported media URL.")

    os.makedirs(output_dir, exist_ok=True)
    file_id = uuid.uuid4().hex
    out_template = os.path.join(output_dir, f"media_{file_id}.%(ext)s")
    url = url.strip()

    last_error = "Media download failed."
    client_fallbacks = PLAYER_CLIENT_FALLBACKS if source == "youtube" else (("web",),)

    for player_clients in client_fallbacks:
        ydl_opts: dict[str, Any] = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": out_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
        }
        if source == "youtube":
            ydl_opts = _build_ydl_opts(out_template, player_clients)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = _resolve_download_path(ydl, info)

            if file_path and os.path.isfile(file_path):
                title = info.get("title") or SOURCE_LABELS.get(source, "Media")
                safe_name = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-")[:80] or source
                return {
                    "file_path": file_path,
                    "filename": f"{safe_name}{os.path.splitext(file_path)[1] or '.m4a'}",
                    "title": title,
                    "url": url,
                    "thumbnail_url": info.get("thumbnail") or "",
                    "duration": info.get("duration"),
                    "source_type": source,
                }
        except (DownloadError, yt_dlp.utils.ExtractorError) as exc:
            last_error = _clean_error(str(exc))
            continue

    raise ValueError(last_error)
