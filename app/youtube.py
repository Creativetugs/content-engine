import json
import logging
import os
import re
import urllib.parse
import urllib.request
import uuid
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)

YOUTUBE_URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/|embed/)|youtu\.be/)[\w-]{6,}",
    re.IGNORECASE,
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# Default web client fails on Windows and cloud IPs; try mobile clients first.
PLAYER_CLIENT_FALLBACKS = (
    ("android", "web"),
    ("ios", "web"),
    ("mweb",),
    ("tv_embedded",),
)


def cloud_download_disabled() -> bool:
    """
    On cloud hosts (Railway), yt-dlp downloads are usually blocked by YouTube.
    Default: disabled when CE_TRANSCRIBE_MODE=openai (production).
    Set CE_ALLOW_YTDLP_DOWNLOAD=true to force download attempts.
    """
    explicit = os.getenv("CE_ALLOW_YTDLP_DOWNLOAD", "").strip().lower()
    if explicit in ("1", "true", "yes"):
        return False
    if explicit in ("0", "false", "no"):
        return True
    return os.getenv("CE_TRANSCRIBE_MODE", "local").strip().lower() == "openai"


def youtube_no_captions_message(detail: str | None = None) -> str:
    if detail:
        return detail
    return (
        "Could not fetch YouTube captions from the server. "
        "Upload the audio or video file instead. "
        "Tip: enable auto-captions on YouTube for podcast episodes."
    )


def is_valid_youtube_url(url: str) -> bool:
    return bool(url.strip() and YOUTUBE_URL_PATTERN.search(url.strip()))


def fetch_youtube_oembed(url: str) -> dict[str, Any]:
    """Public YouTube metadata (title, thumbnail) — works from cloud IPs."""
    endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": url.strip(), "format": "json"}
    )
    try:
        with urllib.request.urlopen(endpoint, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
            return {
                "title": data.get("title") or "YouTube Video",
                "thumbnail_url": data.get("thumbnail_url") or "",
            }
    except Exception as exc:
        logger.warning("YouTube oEmbed failed: %s", exc)
        return {"title": "YouTube Video", "thumbnail_url": ""}


def _clean_error(message: str) -> str:
    text = ANSI_ESCAPE.sub("", message or "").strip()
    if "not a bot" in text or "Sign in to confirm" in text:
        return (
            "YouTube blocked this download from the cloud server (bot check). "
            "Download the video on your computer and use Upload File instead, "
            "or try a Vimeo or Loom link."
        )
    if "This video is not available" in text:
        return (
            "This YouTube video could not be downloaded. It may be private, "
            "age-restricted, region-blocked, or removed. Try uploading the file instead."
        )
    if "Sign in to confirm your age" in text:
        return "This video is age-restricted. Download the file and upload it instead."
    if "Private video" in text:
        return "This is a private YouTube video. Download the file and upload it instead."
    return text or "YouTube download failed."


def _build_ydl_opts(out_template: str, player_clients: tuple[str, ...]) -> dict[str, Any]:
    opts: dict[str, Any] = {
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
        "extractor_args": {
            "youtube": {
                "player_client": list(player_clients),
            }
        },
    }
    cookie_file = os.getenv("CE_YTDLP_COOKIES", "").strip()
    if cookie_file and os.path.isfile(cookie_file):
        opts["cookiefile"] = cookie_file
    proxy = os.getenv("CE_YTDLP_PROXY", "").strip()
    if proxy and "://" not in proxy:
        proxy = f"http://{proxy}"
    if proxy:
        opts["proxy"] = proxy
    return opts


def download_youtube_audio(url: str, output_dir: str = "uploads") -> dict[str, Any]:
    if not is_valid_youtube_url(url):
        raise ValueError("Invalid YouTube URL. Use a link from youtube.com or youtu.be.")

    os.makedirs(output_dir, exist_ok=True)
    file_id = uuid.uuid4().hex
    out_template = os.path.join(output_dir, f"yt_{file_id}.%(ext)s")
    url = url.strip()

    last_error = "YouTube download failed."
    for player_clients in PLAYER_CLIENT_FALLBACKS:
        ydl_opts = _build_ydl_opts(out_template, player_clients)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = _resolve_download_path(ydl, info)

            if file_path and os.path.isfile(file_path):
                title = info.get("title") or "YouTube Video"
                safe_name = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-")[:80] or "youtube-video"
                return {
                    "file_path": file_path,
                    "filename": f"{safe_name}{os.path.splitext(file_path)[1] or '.m4a'}",
                    "title": title,
                    "url": url,
                    "thumbnail_url": info.get("thumbnail") or "",
                    "duration": info.get("duration"),
                }
        except (DownloadError, yt_dlp.utils.ExtractorError) as exc:
            last_error = _clean_error(str(exc))
            continue

    raise ValueError(last_error)


def _resolve_download_path(ydl: yt_dlp.YoutubeDL, info: dict[str, Any]) -> str | None:
    path = ydl.prepare_filename(info)
    if path and os.path.isfile(path):
        return path

    if not path:
        return None

    base, _ext = os.path.splitext(path)
    for ext in (".m4a", ".webm", ".mp4", ".opus", ".mp3", ".wav"):
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate

    return None
