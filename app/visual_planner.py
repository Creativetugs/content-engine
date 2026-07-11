import json

import os

import re

from typing import Any



from dotenv import load_dotenv

from openai import OpenAI



from app.schemas import BrandSettings



load_dotenv()



client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))





def _parse_json(raw: str | None) -> dict:

    if not raw or not raw.strip():

        raise ValueError("Visual planner returned empty response.")

    text = raw.strip()

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)

    if match:

        text = match.group(1).strip()

    return json.loads(text)





def _block_summary(blocks: list[dict]) -> dict[str, Any]:

    h2s, quotes, faqs = [], [], []

    h2_index = -1

    for block in blocks:

        btype = block.get("type", "")

        if btype == "heading" and block.get("level") == "h2":

            h2_index += 1

            text = (block.get("text") or "").strip()

            if text:

                h2s.append({"index": h2_index, "text": text})

        elif btype == "quote":

            text = (block.get("text") or "").strip()

            if text:

                quotes.append(text[:200])

        elif btype == "faq":

            q = (block.get("question") or "").strip()

            if q:

                faqs.append(q[:200])

    return {"h2s": h2s[:6], "quotes": quotes[:3], "faqs": faqs[:3]}





def _image_style_guide(style: str) -> str:
    guides = {
        "mixed": (
            "MIXED style — vary by role:\n"
            "- featured_image, email_banner: photorealistic professional photography\n"
            "- section_illustration: alternate photorealistic scenes AND clean editorial illustrations\n"
            "- social_graphic, carousel_visual: bold branded graphic design with light backgrounds, "
            "subtle photo or illustration accents, space for text overlay\n"
            "- faq_illustration: simple flat icons\n"
            "- quote_background: soft abstract editorial texture, no text"
        ),
        "illustration": (
            "ILLUSTRATION style for all assets — flat editorial illustration, vector-style, "
            "no photorealism, no stock-photo look"
        ),
        "photo": (
            "PHOTO style for all assets — photorealistic professional photography, natural lighting, "
            "real-world scenes, no cartoon or flat illustration"
        ),
    }
    return guides.get(style, guides["mixed"])


def _carousel_slide_summary(content: dict) -> list[dict]:
    carousel = content.get("carousel") or {}
    slides = carousel.get("slides", []) if isinstance(carousel, dict) else []
    summary = []
    for slide in slides[:9]:
        if not isinstance(slide, dict):
            continue
        summary.append(
            {
                "slide": slide.get("slide"),
                "type": slide.get("type", "body"),
                "headline": (slide.get("headline") or "")[:120],
            }
        )
    return summary


def plan_visuals(content: dict, settings: BrandSettings) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set.")

    blog = content.get("blog", {})

    blocks = blog.get("content_blocks", [])

    outputs = settings.outputs

    summary = _block_summary(blocks)
    carousel_slides = _carousel_slide_summary(content)
    style_guide = _image_style_guide(settings.image_style)

    prompt = f"""

Analyze this content and plan block-mapped AI image assets. Return ONLY valid JSON:



{{

  "assets": [

    {{"id":"featured","role":"featured_image","prompt":"...","alt":"...","size":"1792x1024"}},

    {{"id":"section_0","role":"section_illustration","prompt":"...","alt":"","after_h2_index":0,"size":"1792x1024"}},

    {{"id":"quote_0","role":"quote_background","prompt":"...","alt":"","quote_index":0,"size":"1024x1024"}},

    {{"id":"faq_0","role":"faq_illustration","prompt":"...","alt":"","faq_index":0,"size":"1024x1024"}},

    {{"id":"social_1","role":"social_graphic","prompt":"...","alt":"","social_index":0,"size":"1024x1024"}},

    {{"id":"community_snippet","role":"community_snippet","prompt":"...","alt":"","size":"1024x1024"}},

    {{"id":"email_banner","role":"email_banner","prompt":"...","alt":"","size":"1792x1024"}},

    {{"id":"carousel_1","role":"carousel_visual","prompt":"...","alt":"","slide":1,"size":"1024x1024"}},

    {{"id":"shorts_1","role":"shorts_thumbnail","prompt":"...","alt":"","short_index":0,"size":"1024x1024"}}

  ]

}}



Brand: {settings.industry} | {settings.audience} | {settings.tone}

Colors: {settings.brand_primary}, {settings.brand_secondary}
Image style: {settings.image_style}
Outputs: {outputs}

IMAGE STYLE RULES:
{style_guide}

RULES:

- 1 featured_image hero

- section_illustration per H2 (max {len(summary['h2s'])}), prompt must match each H2 topic

- quote_background per quote (max {len(summary['quotes'])}), minimal editorial, NO text in image

- faq_illustration per FAQ (max {len(summary['faqs'])}), simple icon style

- social_graphic max 3 if linkedin in outputs

- community_snippet: 1 CTA-style social graphic if community_snippet in outputs

- email_banner if email in outputs

- carousel_visual for slides 1, 2, 3, and 9 if carousel in outputs (square, light branded background, social carousel slide design, NO text baked into image — leave clean space for headline overlay)

- shorts_thumbnail indices 0-2 if shorts in outputs

H2s: {json.dumps(summary['h2s'])}
Quotes: {json.dumps(summary['quotes'])}
FAQs: {json.dumps(summary['faqs'])}
Carousel slides: {json.dumps(carousel_slides)}
Title: {blog.get('title', '')}
Meta: {blog.get('meta_description', '')}
"""



    response = client.chat.completions.create(

        model="gpt-4o",

        response_format={"type": "json_object"},

        messages=[

            {"role": "system", "content": "Creative director planning block-mapped visuals. JSON only."},

            {"role": "user", "content": prompt},

        ],

    )



    plan = _parse_json(response.choices[0].message.content)

    assets = plan.get("assets", [])

    if not isinstance(assets, list) or not assets:

        raise ValueError("Visual plan contained no assets.")

    return {"assets": assets}


