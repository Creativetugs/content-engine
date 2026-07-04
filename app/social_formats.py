from typing import Any

from pydantic import BaseModel, Field, ValidationError


class ShortScene(BaseModel):
    duration: str = ""
    visual: str = ""
    script: str = ""


class ShortFormat(BaseModel):
    title: str = ""
    hook: str = ""
    scenes: list[ShortScene] = Field(min_length=1)
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)


class CarouselSlide(BaseModel):
    slide: int
    type: str  # hook, body, cta
    headline: str = ""
    body: str = ""
    button_text: str = ""
    button_url: str = "#"


class CarouselFormat(BaseModel):
    slides: list[CarouselSlide] = Field(min_length=1)


SHORTS_SCHEMA = [
    {
        "title": "Short 1",
        "hook": "",
        "scenes": [
            {"duration": "0-3s", "visual": "", "script": ""},
            {"duration": "3-15s", "visual": "", "script": ""},
            {"duration": "15-45s", "visual": "", "script": ""},
        ],
        "caption": "",
        "hashtags": ["", ""],
    },
    {
        "title": "Short 2",
        "hook": "",
        "scenes": [
            {"duration": "0-3s", "visual": "", "script": ""},
            {"duration": "3-15s", "visual": "", "script": ""},
            {"duration": "15-45s", "visual": "", "script": ""},
        ],
        "caption": "",
        "hashtags": ["", ""],
    },
    {
        "title": "Short 3",
        "hook": "",
        "scenes": [
            {"duration": "0-3s", "visual": "", "script": ""},
            {"duration": "3-15s", "visual": "", "script": ""},
            {"duration": "15-45s", "visual": "", "script": ""},
        ],
        "caption": "",
        "hashtags": ["", ""],
    },
]

CAROUSEL_SCHEMA = {
    "slides": [
        {"slide": 1, "type": "hook", "headline": "", "body": ""},
        {"slide": 2, "type": "body", "headline": "", "body": ""},
        {"slide": 3, "type": "body", "headline": "", "body": ""},
        {"slide": 4, "type": "body", "headline": "", "body": ""},
        {"slide": 5, "type": "body", "headline": "", "body": ""},
        {"slide": 6, "type": "body", "headline": "", "body": ""},
        {"slide": 7, "type": "body", "headline": "", "body": ""},
        {"slide": 8, "type": "body", "headline": "", "body": ""},
        {"slide": 9, "type": "cta", "headline": "", "body": "", "button_text": "", "button_url": "#"},
    ]
}

SEO_PACK_SCHEMA = {
    "meta_title": "",
    "meta_description": "",
    "keywords": [],
    "slug": "",
    "schema_markup": {"@type": "Article", "headline": "", "description": ""},
    "faq_schema": [{"question": "", "answer": ""}],
    "internal_link_suggestions": [{"anchor": "", "url": ""}],
    "external_authority_links": [{"anchor": "", "url": ""}],
}


def _expand_legacy_short(item: Any, index: int) -> dict[str, Any]:
    if isinstance(item, str):
        text = item.strip()
        item = {
            "title": f"Short {index + 1}",
            "hook": text,
            "script": text,
            "caption": text,
            "hashtags": [],
        }
    elif not isinstance(item, dict):
        item = {"title": f"Short {index + 1}", "script": str(item)}

    if "scenes" in item:
        return item

    script = item.get("script", "")
    return {
        "title": item.get("title") or f"Short {index + 1}",
        "hook": item.get("hook", ""),
        "scenes": [
            {"duration": "0-3s", "visual": "Hook shot", "script": item.get("hook", "")},
            {"duration": "3-30s", "visual": "Main content", "script": script},
            {"duration": "30-45s", "visual": "CTA shot", "script": "Call to action"},
        ],
        "caption": item.get("caption", script),
        "hashtags": item.get("hashtags", []),
    }


def normalize_shorts(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raw = [raw] if raw else []

    normalized = []
    for index, item in enumerate(raw):
        expanded = _expand_legacy_short(item, index)
        normalized.append(ShortFormat.model_validate(expanded).model_dump())
    return normalized


def _expand_legacy_carousel(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and "slides" in raw:
        return raw

    slides_raw = raw if isinstance(raw, list) else []
    slides = []
    for index, item in enumerate(slides_raw):
        slide_num = index + 1
        slide_type = "hook" if slide_num == 1 else "cta" if slide_num == len(slides_raw) and slide_num > 1 else "body"
        if isinstance(item, str):
            item = {"headline": item.strip(), "body": item.strip()}
        elif not isinstance(item, dict):
            item = {"headline": str(item), "body": ""}
        slides.append(
            {
                "slide": slide_num,
                "type": item.get("type", slide_type),
                "headline": item.get("headline", ""),
                "body": item.get("body", ""),
                "button_text": item.get("button_text", ""),
                "button_url": item.get("button_url", "#"),
            }
        )
    return {"slides": slides}


def normalize_carousel(raw: Any) -> dict[str, Any]:
    expanded = _expand_legacy_carousel(raw)
    return CarouselFormat.model_validate(expanded).model_dump()


def normalize_seo_pack(raw: dict[str, Any]) -> dict[str, Any]:
    pack = dict(raw)
    if "schema_suggestions" in pack and "schema_markup" not in pack:
        pack["schema_markup"] = {"@type": "Article", "suggestions": pack.pop("schema_suggestions")}
    pack.setdefault("faq_schema", [])
    pack.setdefault("internal_link_suggestions", [])
    pack.setdefault("external_authority_links", [])
    return pack
