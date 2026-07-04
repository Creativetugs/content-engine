import json
import logging
import re
import urllib.parse
import urllib.request
from html import unescape
from typing import Any

from app.media_download import is_valid_media_url

logger = logging.getLogger(__name__)

MIN_ARTICLE_CHARS = 200


def is_valid_blog_url(url: str) -> bool:
    url = url.strip()
    if not url:
        return False
    if is_valid_media_url(url):
        return False
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _slug_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.strip("/")
    if not path:
        return ""
    return path.split("/")[-1]


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_json(url: str, timeout: int = 25) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ContentEngine/1.0 (+https://content-engine.local)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _try_wordpress(url: str) -> dict[str, Any] | None:
    slug = _slug_from_url(url)
    if not slug:
        return None

    parsed = urllib.parse.urlparse(url)
    api_url = (
        f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2/posts?"
        + urllib.parse.urlencode({"slug": slug, "_embed": "1"})
    )

    try:
        posts = _fetch_json(api_url)
    except Exception as exc:
        logger.info("WordPress REST fetch skipped for %s: %s", url, exc)
        return None

    if not isinstance(posts, list) or not posts:
        return None

    post = posts[0]
    title = unescape(post.get("title", {}).get("rendered", "") or "Blog Article")
    html = post.get("content", {}).get("rendered", "") or ""
    text = _strip_html(html)

    thumbnail_url = ""
    embedded = post.get("_embedded", {})
    featured = embedded.get("wp:featuredmedia", [])
    if featured and isinstance(featured, list):
        thumbnail_url = featured[0].get("source_url", "") or ""

    if len(text) < MIN_ARTICLE_CHARS:
        return None

    logger.info("Blog article fetched via WordPress REST for %s (%d chars)", slug, len(text))
    return {
        "title": title,
        "text": text,
        "url": url,
        "thumbnail_url": thumbnail_url,
        "fetch_method": "wordpress_rest",
    }


def _try_trafilatura(url: str) -> dict[str, Any] | None:
    try:
        import trafilatura
    except ImportError:
        logger.warning("trafilatura not installed")
        return None

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as exc:
        logger.info("trafilatura fetch failed for %s: %s", url, exc)
        return None

    if not downloaded:
        return None

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if not text or len(text.strip()) < MIN_ARTICLE_CHARS:
        return None

    title = "Blog Article"
    thumbnail_url = ""
    try:
        metadata = trafilatura.extract_metadata(downloaded)
        if metadata:
            if metadata.title:
                title = metadata.title
            if metadata.image:
                thumbnail_url = metadata.image
    except Exception:
        pass

    logger.info("Blog article fetched via trafilatura for %s (%d chars)", url, len(text))
    return {
        "title": title,
        "text": text.strip(),
        "url": url,
        "thumbnail_url": thumbnail_url or "",
        "fetch_method": "trafilatura",
    }


def fetch_blog_article(url: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    Fetch article title and body text from a public blog URL.
    Tries WordPress REST API first, then trafilatura.
    """
    url = url.strip()
    if not is_valid_blog_url(url):
        return None, "Invalid blog URL. Use a public article link (not YouTube/Vimeo/Loom)."

    article = _try_wordpress(url)
    if article:
        return article, None

    article = _try_trafilatura(url)
    if article:
        return article, None

    return None, (
        "Could not read article text from this URL. "
        "Make sure the page is public and contains a full article, or try another link."
    )
