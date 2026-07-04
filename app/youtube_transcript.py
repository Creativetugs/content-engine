import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

YOUTUBE_ID_PATTERN = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})",
    re.IGNORECASE,
)

PREFERRED_LANGUAGES = ("en", "en-US", "en-GB", "en-CA", "en-AU")
MAX_ATTEMPTS = 3


def extract_youtube_id(url: str) -> str | None:
    match = YOUTUBE_ID_PATTERN.search(url.strip())
    return match.group(1) if match else None


def fetch_youtube_oembed(url: str) -> dict[str, Any]:
    """Backward-compatible re-export — implementation lives in app.youtube."""
    from app.youtube import fetch_youtube_oembed as _fetch

    return _fetch(url)


def _normalize_proxy_url(proxy: str) -> str:
    proxy = proxy.strip()
    if not proxy:
        return ""
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return proxy


def _build_transcript_api():
    from youtube_transcript_api import YouTubeTranscriptApi

    webshare_user = os.getenv("CE_WEBSHARE_PROXY_USERNAME", "").strip()
    webshare_pass = os.getenv("CE_WEBSHARE_PROXY_PASSWORD", "").strip()
    if webshare_user and webshare_pass:
        try:
            from youtube_transcript_api.proxies import WebshareProxyConfig

            retries = int(os.getenv("CE_WEBSHARE_RETRIES_WHEN_BLOCKED", "5"))
            config = WebshareProxyConfig(
                proxy_username=webshare_user,
                proxy_password=webshare_pass,
                retries_when_blocked=retries,
            )
            logger.info("YouTube transcript API using Webshare rotating residential proxy")
            return YouTubeTranscriptApi(proxy_config=config)
        except Exception as exc:
            logger.error("Webshare proxy config failed: %s", exc)
            raise

    proxy = _normalize_proxy_url(os.getenv("CE_YTDLP_PROXY", ""))
    if proxy:
        try:
            from youtube_transcript_api.proxies import GenericProxyConfig

            config = GenericProxyConfig(http_url=proxy, https_url=proxy)
            logger.info("YouTube transcript API using generic proxy")
            return YouTubeTranscriptApi(proxy_config=config)
        except Exception as exc:
            logger.error("Generic proxy config failed: %s", exc)
            raise

    return YouTubeTranscriptApi()


def get_youtube_proxy_mode() -> str:
    if os.getenv("CE_WEBSHARE_PROXY_USERNAME", "").strip() and os.getenv(
        "CE_WEBSHARE_PROXY_PASSWORD", ""
    ).strip():
        return "webshare"
    if os.getenv("CE_YTDLP_PROXY", "").strip():
        return "generic"
    return "none"


def _fetched_to_text(fetched: Any) -> str:
    if fetched is None:
        return ""

    if hasattr(fetched, "to_raw_data"):
        raw = fetched.to_raw_data()
        if isinstance(raw, list):
            return re.sub(
                r"\s+",
                " ",
                " ".join(
                    str(item.get("text", "")).strip()
                    for item in raw
                    if isinstance(item, dict) and item.get("text")
                ),
            ).strip()

    parts: list[str] = []
    try:
        for snippet in fetched:
            if isinstance(snippet, dict):
                text = snippet.get("text", "")
            else:
                text = getattr(snippet, "text", "")
            text = str(text).strip()
            if text:
                parts.append(text)
    except TypeError:
        return ""

    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _format_transcript_error(exc: Exception) -> str:
    name = type(exc).__name__
    message = str(exc).strip()
    lowered = message.lower()
    if "ipblocked" in name.lower() or "ip" in lowered and "block" in lowered:
        return (
            "YouTube blocked caption requests from this server IP. "
            "Add Webshare rotating residential proxy on Railway "
            "(CE_WEBSHARE_PROXY_USERNAME + CE_WEBSHARE_PROXY_PASSWORD), "
            "or upload the audio/video file instead."
        )
    if "requestblocked" in name.lower() or "too many requests" in lowered:
        return "YouTube rate-limited caption requests. Try again in a few minutes or upload the file."
    if "transcriptsdisabled" in name.lower() or "disabled" in lowered:
        return "This video has captions disabled on YouTube. Upload the audio/video file instead."
    if "notranscriptfound" in name.lower() or "no transcript" in lowered:
        return "No captions found for this video. Upload the audio/video file instead."
    return message or name


def fetch_youtube_transcript(url: str) -> tuple[str | None, str | None]:
    """
    Fetch captions from YouTube without downloading video.
    Returns (transcript_text, error_message).
    """
    video_id = extract_youtube_id(url)
    if not video_id:
        return None, "Invalid YouTube URL."

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.warning("youtube-transcript-api not installed")
        return None, "Caption library not installed on API server."

    api = _build_transcript_api()
    languages = list(PREFERRED_LANGUAGES)
    last_error = "Could not fetch YouTube captions."

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # 1) Preferred languages
        try:
            fetched = api.fetch(video_id, languages=languages)
            text = _fetched_to_text(fetched)
            if text:
                logger.info(
                    "YouTube captions via fetch(languages) for %s (%d chars, attempt %d)",
                    video_id,
                    len(text),
                    attempt,
                )
                return text, None
        except Exception as exc:
            last_error = _format_transcript_error(exc)
            logger.info("YouTube fetch(languages) attempt %d failed for %s: %s", attempt, video_id, exc)

        # 2) Any available language
        try:
            fetched = api.fetch(video_id)
            text = _fetched_to_text(fetched)
            if text:
                logger.info(
                    "YouTube captions via fetch(any) for %s (%d chars, attempt %d)",
                    video_id,
                    len(text),
                    attempt,
                )
                return text, None
        except Exception as exc:
            last_error = _format_transcript_error(exc)
            logger.info("YouTube fetch(any) attempt %d failed for %s: %s", attempt, video_id, exc)

        # 3) list + find generated/manual
        try:
            listing = api.list(video_id)
            try:
                transcript = listing.find_transcript(languages)
            except Exception:
                transcript = listing.find_generated_transcript(languages)
            text = _fetched_to_text(transcript.fetch())
            if text:
                logger.info(
                    "YouTube captions via list() for %s (%d chars, attempt %d)",
                    video_id,
                    len(text),
                    attempt,
                )
                return text, None
        except Exception as exc:
            last_error = _format_transcript_error(exc)
            logger.info("YouTube list() attempt %d failed for %s: %s", attempt, video_id, exc)

        if attempt < MAX_ATTEMPTS:
            time.sleep(1.5 * attempt)

    return None, last_error


__all__ = [
    "extract_youtube_id",
    "fetch_youtube_oembed",
    "fetch_youtube_transcript",
    "get_youtube_proxy_mode",
]
