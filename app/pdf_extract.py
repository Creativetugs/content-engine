"""Extract plain text from uploaded PDF files for content generation."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

MIN_PDF_CHARS = 200


def is_pdf_file(filename: str | None, content_type: str | None = None) -> bool:
    name = (filename or "").strip().lower()
    if name.endswith(".pdf"):
        return True
    ctype = (content_type or "").strip().lower()
    return ctype in ("application/pdf", "application/x-pdf")


def extract_pdf_text(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    Read text from a PDF on disk.

    Returns (payload, None) on success, or (None, error_message) on failure.
    payload keys: title, text, page_count, fetch_method
    """
    if not path or not os.path.isfile(path):
        return None, "PDF file not found."

    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "PDF support is not installed on the API (missing pypdf)."

    try:
        reader = PdfReader(path)
    except Exception as exc:
        logger.warning("Failed to open PDF %s: %s", path, exc)
        return None, f"Could not open PDF: {exc}"

    if getattr(reader, "is_encrypted", False):
        try:
            unlocked = reader.decrypt("")
            if unlocked == 0:
                return None, "This PDF is password-protected. Upload an unlocked PDF."
        except Exception:
            return None, "This PDF is password-protected. Upload an unlocked PDF."

    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            logger.info("Skipping a PDF page during extract: %s", exc)
            continue
        page_text = _normalize_whitespace(page_text)
        if page_text:
            parts.append(page_text)

    text = _normalize_whitespace("\n\n".join(parts))
    if len(text) < MIN_PDF_CHARS:
        return None, (
            "Could not extract enough text from this PDF "
            f"(need at least {MIN_PDF_CHARS} characters). "
            "Scanned/image-only PDFs are not supported yet — use a text-based PDF, "
            "or paste the content as an AI Idea."
        )

    meta_title = ""
    try:
        meta = reader.metadata
        if meta:
            raw = getattr(meta, "title", None) or (meta.get("/Title") if hasattr(meta, "get") else None)
            if raw:
                meta_title = _normalize_whitespace(str(raw))
    except Exception:
        meta_title = ""

    title = meta_title or _title_from_filename(path) or "PDF Document"
    page_count = len(reader.pages)

    logger.info(
        "Extracted PDF text (%d chars, %d pages) from %s",
        len(text),
        page_count,
        os.path.basename(path),
    )

    return {
        "title": title,
        "text": text,
        "page_count": page_count,
        "fetch_method": "pdf",
    }, None


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _title_from_filename(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"[_\-]+", " ", base).strip()
    return base[:120] if base else ""
