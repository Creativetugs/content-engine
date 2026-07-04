from typing import Any



from app.schemas import BrandSettings

from app.visual_planner import plan_visuals

from app.image_generator import generate_visual_assets

from app.prompt_history import record_prompt_history





def run_visual_pipeline(

    content: dict,

    settings: BrandSettings,

    api_base_url: str,

) -> dict[str, Any]:

    plan = plan_visuals(content, settings)

    assets = generate_visual_assets(plan, api_base_url)



    visuals: dict[str, Any] = {

        "plan": plan.get("assets", []),

        "assets": assets,

    }

    visuals["prompt_history"] = record_prompt_history(visuals, assets)

    _attach_to_content(content, assets, api_base_url)

    return visuals





def _attach_to_content(content: dict, assets: list[dict], api_base_url: str) -> None:

    featured = _find_asset(assets, "featured_image")

    if featured and featured.get("url") and "blog" in content:

        content["blog"]["featured_image_url"] = featured["url"]

        content["blog"]["featured_image_alt"] = featured.get("alt", "")



    if "blog" in content and content["blog"].get("content_blocks"):

        blocks = content["blog"]["content_blocks"]

        blocks = inject_section_images(blocks, [a for a in assets if a.get("role") == "section_illustration"])

        blocks = inject_quote_backgrounds(blocks, [a for a in assets if a.get("role") == "quote_background"])

        blocks = inject_faq_illustrations(blocks, [a for a in assets if a.get("role") == "faq_illustration"])

        content["blog"]["content_blocks"] = blocks



    if [a for a in assets if a.get("role") == "carousel_visual"] and "carousel" in content:

        _attach_carousel_visuals(content["carousel"], [a for a in assets if a.get("role") == "carousel_visual"])



    if [a for a in assets if a.get("role") == "shorts_thumbnail"] and "shorts" in content:

        _attach_shorts_thumbnails(content["shorts"], [a for a in assets if a.get("role") == "shorts_thumbnail"])



    social_assets = [a for a in assets if a.get("role") == "social_graphic" and a.get("url")]

    if social_assets:

        content["social_graphics"] = [

            {"url": a["url"], "alt": a.get("alt", ""), "prompt": a.get("prompt", ""), "id": a.get("id", ""), "social_index": a.get("social_index", i)}

            for i, a in enumerate(social_assets)

        ]



    snippet_asset = _find_asset(assets, "community_snippet")

    if not snippet_asset:

        snippet_asset = social_assets[0] if social_assets else None

    if snippet_asset and snippet_asset.get("url") and isinstance(content.get("community_snippet"), dict):

        content["community_snippet"]["image_url"] = snippet_asset["url"]

        content["community_snippet"]["image_alt"] = snippet_asset.get("alt", "")

        content["community_snippet"]["asset_id"] = snippet_asset.get("id", "")



    email_banner = _find_asset(assets, "email_banner")

    if email_banner and email_banner.get("url") and isinstance(content.get("email_newsletter"), dict):

        content["email_newsletter"]["banner_url"] = email_banner["url"]

        content["email_newsletter"]["banner_alt"] = email_banner.get("alt", "")





def inject_section_images(blocks: list[dict], section_assets: list[dict]) -> list[dict]:

    if not section_assets:

        return blocks

    h2_count = -1

    insertions: list[tuple[int, dict]] = []

    for index, block in enumerate(blocks):

        if block.get("type") == "heading" and block.get("level") == "h2":

            h2_count += 1

            for asset in section_assets:

                if asset.get("after_h2_index") == h2_count and asset.get("url"):

                    insertions.append((index + 1, {

                        "type": "image", "url": asset["url"], "alt": asset.get("alt", ""),

                        "caption": "", "role": "section_illustration", "asset_id": asset.get("id", ""),

                    }))

    for pos, image_block in sorted(insertions, key=lambda x: x[0], reverse=True):

        blocks.insert(pos, image_block)

    return blocks





def inject_quote_backgrounds(blocks: list[dict], quote_assets: list[dict]) -> list[dict]:

    quote_index = -1

    for block in blocks:

        if block.get("type") != "quote":

            continue

        quote_index += 1

        for asset in quote_assets:

            if asset.get("quote_index") == quote_index and asset.get("url"):

                block["background_url"] = asset["url"]

                block["background_alt"] = asset.get("alt", "")

                block["asset_id"] = asset.get("id", "")

    return blocks





def inject_faq_illustrations(blocks: list[dict], faq_assets: list[dict]) -> list[dict]:

    faq_index = -1

    for block in blocks:

        if block.get("type") != "faq":

            continue

        faq_index += 1

        for asset in faq_assets:

            if asset.get("faq_index") == faq_index and asset.get("url"):

                block["illustration_url"] = asset["url"]

                block["illustration_alt"] = asset.get("alt", "")

                block["asset_id"] = asset.get("id", "")

    return blocks





def _attach_carousel_visuals(carousel: dict | list, assets: list[dict]) -> None:

    slides = carousel.get("slides", []) if isinstance(carousel, dict) else carousel

    if not isinstance(slides, list):

        return

    for asset in assets:

        for slide in slides:

            if slide.get("slide") == asset.get("slide"):

                slide["image_url"] = asset.get("url", "")

                slide["image_alt"] = asset.get("alt", "")

                slide["asset_id"] = asset.get("id", "")





def _attach_shorts_thumbnails(shorts: list, assets: list[dict]) -> None:

    for asset in assets:

        idx = asset.get("short_index", 0)

        if 0 <= idx < len(shorts):

            shorts[idx]["thumbnail_url"] = asset.get("url", "")

            shorts[idx]["thumbnail_alt"] = asset.get("alt", "")

            shorts[idx]["asset_id"] = asset.get("id", "")





def _find_asset(assets: list[dict], role: str) -> dict | None:

    for asset in assets:

        if asset.get("role") == role and asset.get("url"):

            return asset

    return None


def attach_assets(content: dict, assets: list[dict], api_base_url: str = "") -> dict[str, Any]:
    """Attach generated image URLs into content and return visuals metadata."""
    _attach_to_content(content, assets, api_base_url)
    return {
        "plan": assets,
        "assets": assets,
        "prompt_history": record_prompt_history({"assets": assets}, assets),
    }
