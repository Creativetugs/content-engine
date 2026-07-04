import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

from app.blocks import BLOCK_RULES, BLOCK_SCHEMA, normalize_blocks
from app.schemas import BrandSettings
from app.social_formats import CAROUSEL_SCHEMA, SEO_PACK_SCHEMA, SHORTS_SCHEMA, normalize_carousel, normalize_seo_pack, normalize_shorts
from app.community_formats import COMMUNITY_SNIPPET_SCHEMA, normalize_community_snippet

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _parse_json_response(raw: str | None) -> dict:
    if not raw or not raw.strip():
        raise ValueError("OpenAI returned an empty response. Check your API key and quota.")

    text = raw.strip()

    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI returned invalid JSON: {exc}") from exc


def _build_output_schema(settings: BrandSettings) -> str:
    parts = []

    if "blog" in settings.outputs:
        blocks_example = json.dumps(BLOCK_SCHEMA, indent=6)
        parts.append(
            f'''
  "blog": {{
    "title": "",
    "slug": "",
    "meta_title": "",
    "meta_description": "",
    "keywords": [],
    "schema_suggestions": [],
    "internal_link_suggestions": [],
    "content_blocks": {blocks_example}
  }}'''
        )

    if "linkedin" in settings.outputs:
        parts.append('"linkedin_posts": ["", "", ""]')

    if "email" in settings.outputs:
        parts.append(
            '''
  "email_newsletter": {
    "subject": "",
    "body": ""
  }'''
        )

    if "shorts" in settings.outputs:
        shorts_example = json.dumps(SHORTS_SCHEMA, indent=6)
        parts.append(f'"shorts": {shorts_example}')

    if "carousel" in settings.outputs:
        carousel_example = json.dumps(CAROUSEL_SCHEMA, indent=6)
        parts.append(f'"carousel": {carousel_example}')

    if "seo_pack" in settings.outputs:
        seo_example = json.dumps(SEO_PACK_SCHEMA, indent=6)
        parts.append(f'"seo_pack": {seo_example}')

    if "community_snippet" in settings.outputs:
        snippet_example = json.dumps(COMMUNITY_SNIPPET_SCHEMA, indent=6)
        parts.append(f'"community_snippet": {snippet_example}')

    return "{\n" + ",\n".join(parts) + "\n}"


def _build_brand_rules(settings: BrandSettings) -> str:
    output_labels = ", ".join(settings.outputs)

    return f"""
Brand context (apply to ALL generated content):
- Tone: {settings.tone}
- Industry: {settings.industry}
- Target audience: {settings.audience}
- CTA style: {settings.cta_style}
- Writing style: {settings.writing_style}
- Brand primary color: {settings.brand_primary}
- Brand secondary color: {settings.brand_secondary}

Brand rules:
- Write specifically for the {settings.industry} industry using appropriate terminology
- Speak directly to: {settings.audience}
- Match a {settings.tone.lower()} tone and {settings.writing_style.lower()} writing style throughout
- CTAs must use a {settings.cta_style.lower()} approach — never generic or salesy unless tone allows it
- Content should feel on-brand for a company using these colors (professional, cohesive voice)
- Only generate these output types: {output_labels}
"""


def generate_content(transcript: str, settings: BrandSettings | None = None) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file.")

    settings = settings or BrandSettings()
    schema = _build_output_schema(settings)
    brand_rules = _build_brand_rules(settings)

    prompt = f"""
Based on this transcript, return ONLY valid JSON matching this exact structure:

{schema}

{brand_rules}

{BLOCK_RULES}

Content rules:
- SEO optimized with publish-ready copy tailored to the industry and audience
- slug should be lowercase, hyphen-separated
- meta_title under 60 characters, meta_description under 160 characters
- keywords: 5-10 relevant terms for the industry
- linkedin_posts: exactly 3 distinct posts (if included)
- shorts: exactly 3 shorts, each with hook, 3 scene breakdowns, caption, and 5-8 hashtags (if included)
- carousel: exactly 9 slides — slide 1 hook, slides 2-8 body, slide 9 CTA with button_text (if included)
- seo_pack: include schema_markup, faq_schema, internal and external link suggestions (if included)
- community_snippet: headline (bold-worthy feed title), teaser (2-4 engaging sentences — not the full blog), 3-6 relevant hashtags without # prefix, cta_text (default "Read more" or brand-appropriate), read_more_url (leave empty string)
- Human sounding, no placeholder text

Transcript:
{transcript}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert content strategist who writes on-brand, "
                    "publish-ready content. Return only valid JSON, no markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content
    result = _parse_json_response(content)

    if "blog" in result and "content_blocks" in result["blog"]:
        result["blog"]["content_blocks"] = normalize_blocks(result["blog"]["content_blocks"])

    if "shorts" in result:
        result["shorts"] = normalize_shorts(result["shorts"])

    if "carousel" in result:
        result["carousel"] = normalize_carousel(result["carousel"])

    if "seo_pack" in result:
        result["seo_pack"] = normalize_seo_pack(result["seo_pack"])

    if "community_snippet" in result:
        result["community_snippet"] = normalize_community_snippet(result["community_snippet"])

    return result


def generate_from_idea(idea: str, settings: BrandSettings | None = None) -> dict:
    """Generate full content pack from a user-written idea or brief (no media required)."""
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file.")

    idea = idea.strip()
    if not idea:
        raise ValueError("Idea text is required.")

    settings = settings or BrandSettings()
    schema = _build_output_schema(settings)
    brand_rules = _build_brand_rules(settings)

    prompt = f"""
The user provided this content idea or brief. Expand it into publish-ready content.
Return ONLY valid JSON matching this exact structure:

{schema}

{brand_rules}

{BLOCK_RULES}

Content rules:
- Turn the idea into a complete, original article — do not copy placeholder text
- SEO optimized with publish-ready copy tailored to the industry and audience
- slug should be lowercase, hyphen-separated
- meta_title under 60 characters, meta_description under 160 characters
- keywords: 5-10 relevant terms for the industry
- linkedin_posts: exactly 3 distinct posts (if included)
- shorts: exactly 3 shorts with hook, scenes, caption, hashtags (if included)
- carousel: exactly 9 slides (if included)
- seo_pack: schema, FAQ, link suggestions (if included)
- community_snippet: headline, teaser, hashtags, cta_text (if included)
- Human sounding, no placeholder text

User idea / brief:
{idea}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert content strategist who turns rough ideas into "
                    "on-brand, publish-ready content. Return only valid JSON, no markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content
    result = _parse_json_response(content)

    if "blog" in result and "content_blocks" in result["blog"]:
        result["blog"]["content_blocks"] = normalize_blocks(result["blog"]["content_blocks"])

    if "shorts" in result:
        result["shorts"] = normalize_shorts(result["shorts"])

    if "carousel" in result:
        result["carousel"] = normalize_carousel(result["carousel"])

    if "seo_pack" in result:
        result["seo_pack"] = normalize_seo_pack(result["seo_pack"])

    if "community_snippet" in result:
        result["community_snippet"] = normalize_community_snippet(result["community_snippet"])

    return result
