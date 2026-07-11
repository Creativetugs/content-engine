from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

HeadingLevel = Literal["h1", "h2", "h3", "h4"]


class HeadingBlock(BaseModel):
    type: Literal["heading"] = "heading"
    level: HeadingLevel
    text: str


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    text: str


class BulletListBlock(BaseModel):
    type: Literal["bullet_list"] = "bullet_list"
    items: list[str] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def strip_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("items must contain at least one non-empty string")
        return cleaned


class QuoteBlock(BaseModel):
    type: Literal["quote"] = "quote"
    text: str


class FaqBlock(BaseModel):
    type: Literal["faq"] = "faq"
    question: str
    answer: str


class CtaBlock(BaseModel):
    type: Literal["cta"] = "cta"
    button_text: str
    button_url: str = "#"


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    url: str
    alt: str = ""
    caption: str = ""
    role: str = "section_illustration"
    asset_id: str = ""


BLOCK_MODELS: dict[str, type[BaseModel]] = {
    "heading": HeadingBlock,
    "paragraph": ParagraphBlock,
    "bullet_list": BulletListBlock,
    "quote": QuoteBlock,
    "faq": FaqBlock,
    "cta": CtaBlock,
    "image": ImageBlock,
}

BLOCK_SCHEMA = [
    {"type": "heading", "level": "h1", "text": ""},
    {"type": "paragraph", "text": ""},
    {"type": "heading", "level": "h2", "text": ""},
    {"type": "paragraph", "text": ""},
    {"type": "bullet_list", "items": ["", ""]},
    {"type": "quote", "text": ""},
    {"type": "faq", "question": "", "answer": ""},
    {"type": "cta", "button_text": "", "button_url": "#"},
]

BLOCK_RULES = """
content_blocks rules:
- Start with one "heading" block at level "h1" (article title)
- Follow with a "paragraph" block (lead / intro copy)
- Use "heading" level "h2" for major sections, "h3" for subsections
- Use "paragraph" for all body copy between headings
- Use "bullet_list" for unordered points and key takeaways
- Include at least one "quote" block with a compelling pull quote from the content
- Use one "faq" block per question (do NOT nest FAQs in an items array)
- End with one "cta" block with button_text and button_url
- Every block must use "text" (not "content" or "heading") for string fields
- Every block must match its type schema exactly
"""


def word_count_bounds(target_word_count: int) -> tuple[int, int]:
    target = max(800, min(10000, int(target_word_count)))
    if target >= 4000:
        return int(target * 0.82), int(target * 1.18)
    if target >= 2000:
        return int(target * 0.85), int(target * 1.15)
    return int(target * 0.9), int(target * 1.1)


def build_block_rules(target_word_count: int) -> str:
    min_words, max_words = word_count_bounds(target_word_count)
    base = BLOCK_RULES.strip()

    if target_word_count < 2000:
        length_rules = f"""
Article length rules:
- Target approximately {target_word_count} words ({min_words}-{max_words} acceptable)
- Use 4-6 major h2 sections with 2-3 substantial paragraphs each
"""
    elif target_word_count < 4000:
        length_rules = f"""
Article length rules:
- Target approximately {target_word_count} words ({min_words}-{max_words} acceptable)
- Use 7-10 major h2 sections with 2-4 paragraphs (80-120 words each) per section
- Include at least 5 faq blocks with detailed answers
"""
    else:
        length_rules = f"""
Article length rules (CRITICAL — do not shorten):
- The blog MUST be {min_words}-{max_words} words total (target ~{target_word_count} words)
- This is a comprehensive pillar article, NOT a summary or overview
- Use 12-18 major h2 sections; add h3 subsections where more depth is needed
- Write 3-5 substantial paragraph blocks (90-150 words each) under every major section
- Include 8-15 faq blocks with thorough answers (70-130 words each)
- Include 4-6 bullet_list blocks with 5-8 detailed items each
- Include 2-4 quote blocks
- Never truncate, never use placeholder text, never stop early
- If the article feels short, add more sections, examples, and technical depth
"""

    return f"{base}\n{length_rules}"


def _heading(level: HeadingLevel, text: str) -> dict[str, Any]:
    return {"type": "heading", "level": level, "text": text}


def _paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "text": text}


def _expand_legacy_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    block_type = block.get("type")

    if block_type == "faq" and "items" in block:
        return [
            {"type": "faq", "question": item.get("question", ""), "answer": item.get("answer", "")}
            for item in block["items"]
            if isinstance(item, dict)
        ]

    if block_type == "cta" and "button_text" not in block:
        return [
            {
                "type": "cta",
                "button_text": block.get("button_text") or block.get("content", "Learn More"),
                "button_url": block.get("button_url", "#"),
            }
        ]

    if block_type in {"hero", "intro"}:
        heading_text = block.get("heading") or block.get("text") or block.get("content", "")
        level: HeadingLevel = "h1" if block_type == "hero" else "h2"
        expanded = [_heading(level, heading_text)]
        body = block.get("content", "")
        if body and body != heading_text:
            expanded.append(_paragraph(body))
        return expanded

    if block_type in {"h1", "h2", "h3", "h4"}:
        level = block_type  # type: ignore[assignment]
        heading_text = block.get("heading") or block.get("text") or block.get("content", "")
        expanded = [_heading(level, heading_text)]
        body = block.get("content", "")
        if body and body != heading_text:
            expanded.append(_paragraph(body))
        return expanded

    if block_type == "heading":
        return [
            {
                "type": "heading",
                "level": block.get("level", "h2"),
                "text": block.get("text") or block.get("heading", ""),
            }
        ]

    if block_type == "paragraph":
        return [_paragraph(block.get("text") or block.get("content", ""))]

    if block_type == "quote":
        return [{"type": "quote", "text": block.get("text") or block.get("content", "")}]

    if block_type in {"bullet_list", "key_takeaways"}:
        return [{"type": "bullet_list", "items": block.get("items", [])}]

    if "heading" in block and "content" in block and block_type not in BLOCK_MODELS:
        expanded = [_heading("h2", block["heading"])]
        if block.get("content"):
            expanded.append(_paragraph(block["content"]))
        return expanded

    return [block]


def validate_block(block: dict[str, Any]) -> dict[str, Any]:
    block_type = block.get("type")
    model = BLOCK_MODELS.get(block_type)
    if not model:
        raise ValueError(f"Unknown block type: {block_type}")

    return model.model_validate(block).model_dump()


def normalize_blocks(raw_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        raise ValueError("content_blocks must be a list.")

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, block in enumerate(raw_blocks):
        if not isinstance(block, dict):
            errors.append(f"Block {index}: expected object, got {type(block).__name__}")
            continue

        for candidate in _expand_legacy_block(block):
            try:
                normalized.append(validate_block(candidate))
            except (ValidationError, ValueError) as exc:
                errors.append(f"Block {index} ({candidate.get('type')}): {exc}")

    if errors:
        raise ValueError("Invalid content_blocks:\n" + "\n".join(errors))

    if not normalized:
        raise ValueError("content_blocks is empty.")

    return normalized
