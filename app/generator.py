import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

from app.blocks import BLOCK_RULES, BLOCK_SCHEMA, build_block_rules, normalize_blocks, word_count_bounds
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


def _parse_word_count_from_text(text: str) -> int | None:
    """Read an explicit word-count request from a user brief or transcript note."""
    lowered = text.lower()

    range_match = re.search(
        r"(\d[\d,]*)\s*(?:[-–—]|to)\s*(\d[\d,]*)\s*words?",
        lowered,
    )
    if range_match:
        low = int(range_match.group(1).replace(",", ""))
        high = int(range_match.group(2).replace(",", ""))
        if low > 0 and high > 0:
            return max(low, high) if low < high else low

    min_match = re.search(
        r"(?:at\s+least|minimum|min\.?|no\s+less\s+than)\s*(\d[\d,]*)\s*words?",
        lowered,
    )
    if min_match:
        return int(min_match.group(1).replace(",", ""))

    single_match = re.search(r"(\d[\d,]*)\s*[-]?\s*words?", lowered)
    if single_match:
        count = int(single_match.group(1).replace(",", ""))
        if count >= 500:
            return count

    return None


def _resolve_target_word_count(source_text: str, settings: BrandSettings) -> int:
    parsed = _parse_word_count_from_text(source_text)
    if parsed:
        return max(800, min(10000, parsed))
    return settings.target_word_count


def _count_blog_words(blog: dict) -> int:
    blocks = blog.get("content_blocks") or []
    parts: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "bullet_list":
            parts.extend(block.get("items") or [])
        elif block_type == "faq":
            parts.append(f"{block.get('question', '')} {block.get('answer', '')}")
        elif block.get("text"):
            parts.append(block["text"])
        elif block.get("button_text"):
            parts.append(block["button_text"])
    return len(" ".join(parts).split())


def _blog_outline_for_ancillary(blog: dict) -> str:
    lines = [
        f"Title: {blog.get('title', '')}",
        f"Meta: {blog.get('meta_description', '')}",
        f"Keywords: {', '.join(blog.get('keywords') or [])}",
        "",
        "Article outline and key copy:",
    ]
    char_budget = 12000
    used = sum(len(line) for line in lines)

    for block in blog.get("content_blocks") or []:
        chunk = ""
        block_type = block.get("type")
        if block_type == "heading":
            chunk = f"\n[{block.get('level', 'h2').upper()}] {block.get('text', '')}"
        elif block_type == "paragraph":
            chunk = block.get("text", "")
        elif block_type == "bullet_list":
            chunk = "• " + "\n• ".join(block.get("items") or [])
        elif block_type == "quote":
            chunk = f"\"{block.get('text', '')}\""
        elif block_type == "faq":
            chunk = f"Q: {block.get('question', '')}\nA: {block.get('answer', '')}"

        if not chunk:
            continue
        if used + len(chunk) > char_budget:
            lines.append("\n[...article continues...]")
            break
        lines.append(chunk)
        used += len(chunk)

    return "\n".join(lines)


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
    min_words, max_words = word_count_bounds(settings.target_word_count)
    length_line = (
        f"- Blog article target length: {min_words}-{max_words} words (~{settings.target_word_count} words)"
        if "blog" in settings.outputs
        else ""
    )

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
{length_line}
"""


def _build_shared_content_rules(include_blog: bool) -> str:
    rules = [
        "- SEO optimized with publish-ready copy tailored to the industry and audience",
        "- slug should be lowercase, hyphen-separated",
        "- meta_title under 60 characters, meta_description under 160 characters",
        "- keywords: 5-10 relevant terms for the industry",
        "- linkedin_posts: exactly 3 distinct posts (if included)",
        "- shorts: exactly 3 shorts, each with hook, 3 scene breakdowns, caption, and 5-8 hashtags (if included)",
        "- carousel: exactly 9 slides — slide 1 hook, slides 2-8 body, slide 9 CTA with button_text (if included)",
        "- seo_pack: include schema_markup, faq_schema, internal and external link suggestions (if included)",
        "- community_snippet: headline (bold-worthy feed title), teaser (2-4 engaging sentences — not the full blog), 3-6 relevant hashtags without # prefix, cta_text (default \"Read more\" or brand-appropriate), read_more_url (leave empty string)",
        "- Human sounding, no placeholder text",
    ]
    if include_blog:
        rules.insert(0, "- Turn the source into a complete, original long-form article — do not copy placeholder text")
    return "Content rules:\n" + "\n".join(rules)


def _call_gpt_json(system: str, user: str, max_tokens: int = 16384) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return _parse_json_response(response.choices[0].message.content)


def _postprocess_result(result: dict) -> dict:
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


def _generate_blog_only(source_text: str, settings: BrandSettings, *, from_idea: bool) -> dict:
    target = _resolve_target_word_count(source_text, settings)
    min_words, max_words = word_count_bounds(target)
    blog_settings = settings.model_copy(update={"outputs": ["blog"], "target_word_count": target})
    schema = _build_output_schema(blog_settings)
    brand_rules = _build_brand_rules(blog_settings)
    block_rules = build_block_rules(target)

    source_label = "User idea / brief" if from_idea else "Transcript"
    intro = (
        "The user provided this content idea or brief. Expand it into a complete long-form article."
        if from_idea
        else "Based on this transcript, write a complete long-form article."
    )

    prompt = f"""
{intro}
Return ONLY valid JSON matching this exact structure:

{schema}

{brand_rules}

{block_rules}

Content rules:
- PRIORITY: Hit the word count target ({min_words}-{max_words} words). Depth and completeness matter more than brevity.
- SEO optimized with publish-ready copy tailored to the industry and audience
- slug should be lowercase, hyphen-separated
- meta_title under 60 characters, meta_description under 160 characters
- keywords: 5-10 relevant terms for the industry
- Human sounding, authoritative, no placeholder text

{source_label}:
{source_text}
"""

    system = (
        "You are an expert long-form content writer who produces comprehensive, in-depth "
        "SEO articles. You NEVER write short summaries when a long article is requested. "
        "Return only valid JSON, no markdown."
    )

    result = _call_gpt_json(system, prompt, max_tokens=16384)
    blog = result.get("blog", result)
    if blog.get("content_blocks"):
        blog["content_blocks"] = normalize_blocks(blog["content_blocks"])
    return blog


def _generate_ancillary_outputs(source_text: str, blog: dict, settings: BrandSettings) -> dict:
    other_outputs = [output for output in settings.outputs if output != "blog"]
    if not other_outputs:
        return {}

    ancillary_settings = settings.model_copy(update={"outputs": other_outputs})
    schema = _build_output_schema(ancillary_settings)
    brand_rules = _build_brand_rules(ancillary_settings)
    outline = _blog_outline_for_ancillary(blog)

    prompt = f"""
The blog article has already been written. Generate ONLY the remaining marketing outputs listed in the schema.
Do NOT include a "blog" key. Base social, email, carousel, and other outputs on the article below.

{schema}

{brand_rules}

{_build_shared_content_rules(include_blog=False)}

Finished blog article:
{outline}

Original source material (for tone and facts):
{source_text[:6000]}
"""

    system = (
        "You are an expert content strategist creating social and email derivatives "
        "from a finished long-form article. Return only valid JSON, no markdown."
    )

    return _call_gpt_json(system, prompt, max_tokens=8192)


def _generate_single_pass(source_text: str, settings: BrandSettings, *, from_idea: bool) -> dict:
    schema = _build_output_schema(settings)
    brand_rules = _build_brand_rules(settings)
    block_rules = build_block_rules(settings.target_word_count) if "blog" in settings.outputs else BLOCK_RULES
    source_label = "User idea / brief" if from_idea else "Transcript"
    intro = (
        "The user provided this content idea or brief. Expand it into publish-ready content."
        if from_idea
        else "Based on this transcript, write publish-ready content."
    )

    prompt = f"""
{intro}
Return ONLY valid JSON matching this exact structure:

{schema}

{brand_rules}

{block_rules}

{_build_shared_content_rules(include_blog="blog" in settings.outputs)}

{source_label}:
{source_text}
"""

    system = (
        "You are an expert content strategist who turns rough ideas into on-brand, "
        "publish-ready content. Return only valid JSON, no markdown."
        if from_idea
        else
        "You are an expert content strategist who writes on-brand, publish-ready content. "
        "Return only valid JSON, no markdown."
    )

    return _call_gpt_json(system, prompt, max_tokens=16384)


def _generate_full_pack(source_text: str, settings: BrandSettings, *, from_idea: bool) -> dict:
    result: dict = {}

    if "blog" in settings.outputs:
        result["blog"] = _generate_blog_only(source_text, settings, from_idea=from_idea)

    other_outputs = [output for output in settings.outputs if output != "blog"]
    if other_outputs:
        if "blog" in result:
            result.update(_generate_ancillary_outputs(source_text, result["blog"], settings))
        else:
            result.update(_generate_single_pass(source_text, settings, from_idea=from_idea))

    return _postprocess_result(result)


def generate_content(transcript: str, settings: BrandSettings | None = None) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file.")

    settings = settings or BrandSettings()
    if "blog" in settings.outputs:
        return _generate_full_pack(transcript, settings, from_idea=False)
    return _postprocess_result(_generate_single_pass(transcript, settings, from_idea=False))


def generate_from_idea(idea: str, settings: BrandSettings | None = None) -> dict:
    """Generate full content pack from a user-written idea or brief (no media required)."""
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file.")

    idea = idea.strip()
    if not idea:
        raise ValueError("Idea text is required.")

    settings = settings or BrandSettings()
    if "blog" in settings.outputs:
        return _generate_full_pack(idea, settings, from_idea=True)
    return _postprocess_result(_generate_single_pass(idea, settings, from_idea=True))
