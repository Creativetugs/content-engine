import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

VALID_OUTPUTS = frozenset({"blog", "linkedin", "email", "shorts", "carousel", "seo_pack", "community_snippet"})
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandSettings(BaseModel):
    tone: str = "Professional"
    industry: str = "General"
    brand_primary: str = "#002a65"
    brand_secondary: str = "#56814f"
    audience: str = "General audience"
    writing_style: str = "Educational"
    outputs: list[
        Literal["blog", "linkedin", "email", "shorts", "carousel", "seo_pack", "community_snippet"]
    ] = Field(default=["blog", "linkedin", "email"])
    cta_style: str = "Direct"
    image_style: str = "mixed"

    @field_validator("image_style")
    @classmethod
    def validate_image_style(cls, value: str) -> str:
        allowed = {"mixed", "illustration", "photo"}
        normalized = (value or "mixed").strip().lower()
        return normalized if normalized in allowed else "mixed"

    @field_validator("brand_primary", "brand_secondary")
    @classmethod
    def validate_hex_color(cls, value: str) -> str:
        if not HEX_COLOR_PATTERN.match(value):
            raise ValueError(f"Invalid hex color: {value}. Use format #RRGGBB.")
        return value.lower()

    @field_validator("outputs")
    @classmethod
    def validate_outputs(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one output type is required.")
        invalid = set(value) - VALID_OUTPUTS
        if invalid:
            raise ValueError(
                f"Invalid output types: {', '.join(sorted(invalid))}. "
                f"Allowed: {', '.join(sorted(VALID_OUTPUTS))}."
            )
        return value


def parse_outputs(raw: str | list[str]) -> list[str]:
    """Parse outputs from JSON array, comma-separated string, or list."""
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]

    raw = raw.strip()
    if not raw:
        return ["blog", "linkedin", "email"]

    if raw.startswith("["):
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("outputs must be a JSON array.")
        return parsed

    return [part.strip() for part in raw.split(",") if part.strip()]
