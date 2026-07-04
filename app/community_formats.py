from typing import Any

from pydantic import BaseModel, Field


class CommunitySnippetFormat(BaseModel):
    headline: str = ""
    teaser: str = ""
    hashtags: list[str] = Field(default_factory=list)
    cta_text: str = "Read more"
    read_more_url: str = ""


COMMUNITY_SNIPPET_SCHEMA = {
    "headline": "",
    "teaser": "",
    "hashtags": ["", ""],
    "cta_text": "Read more",
    "read_more_url": "",
}


def normalize_community_snippet(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    data = dict(raw)
    data.setdefault("cta_text", "Read more")
    data.setdefault("hashtags", [])
    data.setdefault("read_more_url", "")
    return CommunitySnippetFormat.model_validate(data).model_dump()
