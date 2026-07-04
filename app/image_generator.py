import base64
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.request import urlopen

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

IMAGES_DIR = "output/images"
MAX_ASSETS = int(os.getenv("CE_MAX_VISUAL_ASSETS", "8"))
IMAGE_CONCURRENCY = int(os.getenv("CE_IMAGE_CONCURRENCY", "3"))
IMAGE_MODEL = os.getenv("CE_IMAGE_MODEL", "gpt-image-1")

ROLE_PRIORITY = (
    "featured_image",
    "section_illustration",
    "social_graphic",
    "community_snippet",
    "email_banner",
    "carousel_visual",
    "shorts_thumbnail",
    "quote_background",
    "faq_illustration",
)

SIZE_ALIASES = {
    "1792x1024": "1536x1024",
    "1024x1792": "1024x1536",
}
VALID_SIZES = {"1024x1024", "1792x1024", "1024x1792", "1536x1024", "1024x1536"}


def _role_sort_key(asset: dict[str, Any]) -> tuple[int, str]:
    role = asset.get("role", "")
    try:
        return (ROLE_PRIORITY.index(role), asset.get("id", ""))
    except ValueError:
        return (len(ROLE_PRIORITY), asset.get("id", ""))


def _prioritize_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(assets, key=_role_sort_key)[:MAX_ASSETS]


def _resolve_size(asset: dict[str, Any]) -> str:
    size = asset.get("size", "1024x1024")
    if size not in VALID_SIZES:
        size = "1792x1024" if asset.get("role") == "featured_image" else "1024x1024"
    return SIZE_ALIASES.get(size, size)


def _save_image_data(data: Any, local_path: str) -> None:
    if data.b64_json:
        with open(local_path, "wb") as f:
            f.write(base64.b64decode(data.b64_json))
        return
    if data.url:
        with urlopen(data.url) as response, open(local_path, "wb") as f:  # noqa: S310
            f.write(response.read())
        return
    raise ValueError("Image response contained no url or b64_json data.")


def _generate_one_asset(asset: dict[str, Any], api_base_url: str) -> dict[str, Any]:
    prompt = asset.get("prompt", "").strip()
    if not prompt:
        return {**asset, "url": "", "status": "skipped", "error": "Empty prompt"}

    size = _resolve_size(asset)
    try:
        kwargs: dict[str, Any] = {
            "model": IMAGE_MODEL,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }
        if IMAGE_MODEL == "dall-e-3":
            kwargs["quality"] = "standard"

        result = client.images.generate(**kwargs)
        image_data = result.data[0]

        filename = f"{asset.get('id', 'asset')}_{uuid.uuid4().hex[:10]}.png"
        local_path = os.path.join(IMAGES_DIR, filename)
        _save_image_data(image_data, local_path)

        return {
            **asset,
            "filename": filename,
            "local_path": local_path,
            "url": f"{api_base_url}/images/{filename}",
            "status": "generated",
        }
    except Exception as exc:
        return {**asset, "url": "", "status": "failed", "error": str(exc)}


def generate_visual_assets(plan: dict, api_base_url: str) -> list[dict[str, Any]]:
    """Generate images from visual plan (parallel where possible)."""
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set.")

    os.makedirs(IMAGES_DIR, exist_ok=True)
    api_base_url = api_base_url.rstrip("/")

    assets = _prioritize_assets(plan.get("assets", []))
    if not assets:
        return []

    workers = max(1, min(IMAGE_CONCURRENCY, len(assets)))
    logger.info("Generating %d visuals with %d workers", len(assets), workers)

    generated: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_generate_one_asset, asset, api_base_url): asset
            for asset in assets
        }
        for future in as_completed(futures):
            generated.append(future.result())

    generated.sort(key=_role_sort_key)
    return generated


def regenerate_asset(
    asset: dict[str, Any],
    api_base_url: str,
    prompt_override: str | None = None,
) -> dict[str, Any]:
    updated = dict(asset)
    if prompt_override:
        updated["prompt"] = prompt_override
    return _generate_one_asset(updated, api_base_url.rstrip("/"))
