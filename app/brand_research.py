"""Research a company website into a reusable brand kit."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

MIN_SITE_CHARS = 300
MAX_PAGE_CHARS = 12000
MAX_TOTAL_CHARS = 28000


def _openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _fetch_page_text(url: str, timeout: int = 25) -> str:
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            extracted = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
            )
            if extracted and len(extracted.strip()) >= 80:
                return _normalize_whitespace(extracted)[:MAX_PAGE_CHARS]
    except Exception as exc:
        logger.info("trafilatura fetch skipped for %s: %s", url, exc)

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ContentEngine/1.0 (+https://content-engine.local)"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        text = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return _normalize_whitespace(text)[:MAX_PAGE_CHARS]
    except Exception as exc:
        logger.info("HTML fallback failed for %s: %s", url, exc)
        return ""


def _candidate_paths(base_url: str) -> list[str]:
    parsed = urllib.parse.urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    paths = [
        "",
        "/about",
        "/about-us",
        "/company",
        "/products",
        "/solutions",
        "/services",
        "/industries",
        "/what-we-do",
    ]
    urls: list[str] = []
    for path in paths:
        urls.append(urllib.parse.urljoin(origin + "/", path.lstrip("/")) if path else origin + "/")
    # Always include the exact URL the user provided first.
    ordered = [base_url.rstrip("/") + ("/" if base_url.endswith("/") else "")]
    for url in urls:
        if url.rstrip("/") not in {u.rstrip("/") for u in ordered}:
            ordered.append(url)
    return ordered[:6]


def gather_website_corpus(website_url: str) -> tuple[str, list[str], str | None]:
    url = (website_url or "").strip()
    if not url:
        return "", [], "Website URL is required."
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", [], "Enter a valid http(s) website URL."

    parts: list[str] = []
    used: list[str] = []
    total = 0
    for page_url in _candidate_paths(url):
        text = _fetch_page_text(page_url)
        if len(text) < 80:
            continue
        chunk = f"PAGE: {page_url}\n{text}"
        if total + len(chunk) > MAX_TOTAL_CHARS:
            chunk = chunk[: max(0, MAX_TOTAL_CHARS - total)]
        parts.append(chunk)
        used.append(page_url)
        total += len(chunk)
        if total >= MAX_TOTAL_CHARS or len(used) >= 4:
            break

    corpus = "\n\n---\n\n".join(parts).strip()
    if len(corpus) < MIN_SITE_CHARS:
        return "", used, (
            "Could not read enough text from this website. "
            "Check the URL is public, or paste company details manually."
        )
    return corpus, used, None


def analyze_website(website_url: str) -> dict[str, Any]:
    client = _openai_client()

    corpus, pages, error = gather_website_corpus(website_url)
    if error:
        raise ValueError(error)

    system = (
        "You are a brand strategist and B2B SEO analyst. "
        "Extract a factual brand kit from website copy. "
        "Do not invent products, certifications, or claims not supported by the text. "
        "Return ONLY valid JSON."
    )
    user = f"""
Analyze this company website corpus and return JSON with:
{{
  "company_name": "",
  "company_gist": "2-4 sentences: what the company does, who they serve, what makes them distinct",
  "industry": "",
  "audience": "specific buyer personas",
  "tone": "e.g. Professional, Technical, Supportive",
  "writing_style": "e.g. Educational, Authoritative",
  "cta_style_hint": "e.g. Direct, Supportive",
  "topics": ["5-12 core topics/themes the company talks about"],
  "seo_keywords": ["8-15 realistic SEO keywords / phrases"],
  "voice_notes": "bullet-like notes on voice, terminology, do/don't for writers",
  "visual_style_notes": "how product/industrial imagery should look for this brand"
}}

Website URL: {website_url}
Pages read: {", ".join(pages)}

CORPUS:
{corpus}
"""
    response = client.chat.completions.create(
        model=os.getenv("CE_BRAND_MODEL", "gpt-4o"),
        response_format={"type": "json_object"},
        max_tokens=2500,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    raw = response.choices[0].message.content or ""
    try:
        kit = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Brand analysis returned invalid JSON.") from exc

    if not isinstance(kit, dict):
        raise ValueError("Brand analysis returned an invalid payload.")

    kit["source_url"] = website_url.strip()
    kit["pages_analyzed"] = pages
    kit["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    # Normalize list fields
    for key in ("topics", "seo_keywords"):
        value = kit.get(key)
        if isinstance(value, str):
            kit[key] = [part.strip() for part in value.split(",") if part.strip()]
        elif not isinstance(value, list):
            kit[key] = []
        else:
            kit[key] = [str(item).strip() for item in value if str(item).strip()]

    logger.info(
        "Brand kit built for %s (%d pages, %d corpus chars)",
        website_url,
        len(pages),
        len(corpus),
    )
    return kit
