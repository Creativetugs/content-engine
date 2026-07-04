import os
import json
import re
import logging
import time
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from app.schemas import BrandSettings, parse_outputs

os.makedirs("uploads", exist_ok=True)
os.makedirs("output", exist_ok=True)
os.makedirs("output/images", exist_ok=True)
os.makedirs("static", exist_ok=True)

app = FastAPI()
app.mount("/images", StaticFiles(directory="output/images"), name="images")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("content_engine")


@app.get("/health")
def health():
    """Verify API and critical imports. Never raises — safe for Railway health checks."""
    payload: dict = {
        "ok": True,
        "version": "1.7.4",
    }

    try:
        from app.youtube_transcript import get_youtube_proxy_mode

        payload["youtube_proxy"] = get_youtube_proxy_mode()
    except Exception as exc:
        payload["youtube_proxy"] = "unknown"
        payload["youtube_proxy_error"] = str(exc)

    try:
        from app.youtube_transcript import get_youtube_proxy_diagnostics

        proxy_env = get_youtube_proxy_diagnostics()
    except Exception:
        proxy_env = {
            "webshare_username_set": bool(os.getenv("CE_WEBSHARE_PROXY_USERNAME", "").strip()),
            "webshare_password_set": bool(os.getenv("CE_WEBSHARE_PROXY_PASSWORD", "").strip()),
            "generic_proxy_set": bool(os.getenv("CE_YTDLP_PROXY", "").strip()),
        }
    payload["proxy_env"] = proxy_env

    try:
        from app.youtube import fetch_youtube_oembed  # noqa: F401
        from app.youtube_transcript import fetch_youtube_transcript  # noqa: F401

        payload["youtube_captions"] = "ready"
    except ImportError as exc:
        payload["ok"] = False
        payload["youtube_captions"] = str(exc)

    try:
        from app.blog_fetch import fetch_blog_article  # noqa: F401

        payload["blog_url"] = "ready"
    except ImportError as exc:
        payload["blog_url"] = str(exc)

    proxy_mode = payload.get("youtube_proxy", "none")
    if proxy_mode == "none":
        if not proxy_env.get("webshare_username_set") and not proxy_env.get("generic_proxy_set"):
            payload["youtube_proxy_hint"] = (
                "Add CE_YTDLP_PROXY=http://USER:PASS@p.webshare.io:80 on Railway, "
                "or CE_WEBSHARE_PROXY_USERNAME + CE_WEBSHARE_PROXY_PASSWORD."
            )
        elif proxy_env.get("webshare_username_set") and not proxy_env.get("webshare_password_set"):
            payload["youtube_proxy_hint"] = "CE_WEBSHARE_PROXY_USERNAME is set but PASSWORD is missing."
        elif proxy_env.get("webshare_password_set") and not proxy_env.get("webshare_username_set"):
            payload["youtube_proxy_hint"] = "CE_WEBSHARE_PROXY_PASSWORD is set but USERNAME is missing."

    return payload


@app.get("/")
def home():
    from app.blocks import BLOCK_MODELS
    from app.schemas import VALID_OUTPUTS

    return {
        "message": "Content Engine API is running",
        "outputs": sorted(VALID_OUTPUTS),
        "block_types": list(BLOCK_MODELS.keys()),
        "visual_roles": [
            "featured_image",
            "section_illustration",
            "quote_background",
            "faq_illustration",
            "social_graphic",
            "community_snippet",
            "email_banner",
            "carousel_visual",
            "shorts_thumbnail",
        ],
        "media_sources": ["youtube", "vimeo", "loom", "blog", "upload", "idea"],
    }


@app.get("/demo")
def demo_page():
    demo_path = os.path.join("static", "demo.html")
    if not os.path.isfile(demo_path):
        raise HTTPException(status_code=404, detail="Demo page not found.")
    return FileResponse(demo_path)


@app.get("/blocks/schema")
def block_schema():
    from app.blocks import BLOCK_MODELS, BLOCK_SCHEMA

    return {
        "blocks": BLOCK_SCHEMA,
        "types": {
            block_type: list(model.model_json_schema()["properties"].keys())
            for block_type, model in BLOCK_MODELS.items()
        },
    }


def _build_response(
    filename: str,
    transcript: str,
    content: dict,
    settings: BrandSettings,
    source: dict | None = None,
) -> dict:
    response = {
        "filename": filename,
        "transcript": transcript,
        "brand": settings.model_dump(),
    }

    if source:
        response["source"] = source

    output_map = {
        "blog": "blog",
        "linkedin": "linkedin_posts",
        "email": "email_newsletter",
        "shorts": "shorts",
        "carousel": "carousel",
        "seo_pack": "seo_pack",
        "community_snippet": "community_snippet",
    }

    for output_key, content_key in output_map.items():
        if output_key in settings.outputs:
            response[content_key] = content.get(content_key, {})

    if content.get("visuals"):
        response["visuals"] = content["visuals"]
    if content.get("social_graphics"):
        response["social_graphics"] = content["social_graphics"]

    return response


_WP_TO_INTERNAL = {
    "blog": "blog",
    "linkedin_posts": "linkedin",
    "email_newsletter": "email",
    "shorts": "shorts",
    "carousel": "carousel",
    "seo_pack": "seo_pack",
    "community_snippet": "community_snippet",
}


def _wp_payload_to_content(payload: dict) -> dict:
    content: dict = {}
    for wp_key, internal_key in _WP_TO_INTERNAL.items():
        if wp_key in payload and payload[wp_key]:
            content[internal_key] = payload[wp_key]
    return content


def _outputs_from_wp_payload(payload: dict) -> list[str]:
    outputs = [internal for wp_key, internal in _WP_TO_INTERNAL.items() if wp_key in payload]
    return outputs or ["blog"]


def _apply_visuals_to_wp_payload(payload: dict, content: dict) -> dict:
    updated = dict(payload)
    for wp_key, internal_key in _WP_TO_INTERNAL.items():
        if internal_key in content:
            updated[wp_key] = content[internal_key]
    if content.get("visuals"):
        updated["visuals"] = content["visuals"]
    if content.get("social_graphics"):
        updated["social_graphics"] = content["social_graphics"]
    return updated


def _settings_from_wp_payload(wp_payload: dict) -> BrandSettings:
    brand_data = wp_payload.get("brand") if isinstance(wp_payload.get("brand"), dict) else {}
    return BrandSettings(
        tone=brand_data.get("tone", "Professional"),
        industry=brand_data.get("industry", "General"),
        brand_primary=brand_data.get("brand_primary", "#002a65"),
        brand_secondary=brand_data.get("brand_secondary", "#56814f"),
        audience=brand_data.get("audience", "General audience"),
        writing_style=brand_data.get("writing_style", "Educational"),
        outputs=_outputs_from_wp_payload(wp_payload),
        cta_style=brand_data.get("cta_style", "Direct"),
    )


class ExportRequest(BaseModel):
    blocks: list[dict]
    brand: dict | None = None
    format: str = "html"


@app.post("/export")
def export_content(payload: ExportRequest):
    from app.exporters import blocks_to_gutenberg, blocks_to_html, blocks_to_markdown

    if payload.format == "html":
        return {"content": blocks_to_html(payload.blocks, payload.brand)}
    if payload.format == "markdown":
        return {"content": blocks_to_markdown(payload.blocks)}
    if payload.format == "gutenberg":
        return {"content": blocks_to_gutenberg(payload.blocks)}
    if payload.format == "json":
        return {"content": json.dumps(payload.blocks, indent=2)}

    raise HTTPException(status_code=400, detail="format must be html, markdown, gutenberg, or json")


class RegenerateVisualRequest(BaseModel):
    asset: dict
    brand: dict | None = None
    prompt: str | None = None


class GenerateVisualsRequest(BaseModel):
    """WordPress payload from step 1 — visuals generated in a separate request."""
    payload: dict


class VisualAttachRequest(BaseModel):
    payload: dict
    assets: list[dict]


class GenerateAssetRequest(BaseModel):
    asset: dict


class RegenerateContentRequest(BaseModel):
    transcript: str
    tone: str = "Professional"
    industry: str = "General"
    brand_primary: str = "#002a65"
    brand_secondary: str = "#56814f"
    audience: str = "General audience"
    writing_style: str = "Educational"
    outputs: list[str] | str = '["blog", "linkedin", "email"]'
    cta_style: str = "Direct"
    generate_visuals: bool = True


class GenerateIdeaRequest(BaseModel):
    idea: str
    tone: str = "Professional"
    industry: str = "General"
    brand_primary: str = "#002a65"
    brand_secondary: str = "#56814f"
    audience: str = "General audience"
    writing_style: str = "Educational"
    outputs: list[str] | str = '["blog", "linkedin", "email", "community_snippet"]'
    cta_style: str = "Direct"
    generate_visuals: bool = False


@app.post("/visuals/regenerate")
def regenerate_visual(request: Request, payload: RegenerateVisualRequest):
    from app.image_generator import regenerate_asset

    base_url = str(request.base_url).rstrip("/")
    try:
        asset = regenerate_asset(payload.asset, base_url, payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"asset": asset}


@app.post("/visuals/generate")
def generate_visuals_batch(request: Request, body: GenerateVisualsRequest):
    """Generate AI visuals for an existing content payload (step 2 after /repurpose)."""
    from app.blocks import normalize_blocks
    from app.visual_layer import run_visual_pipeline

    wp_payload = body.payload
    if not isinstance(wp_payload, dict) or not wp_payload:
        raise HTTPException(status_code=400, detail="payload is required.")

    content = _wp_payload_to_content(wp_payload)
    if not content:
        raise HTTPException(status_code=400, detail="No content in payload to attach visuals to.")

    try:
        settings = _settings_from_wp_payload(wp_payload)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    base_url = str(request.base_url).rstrip("/")
    t0 = time.perf_counter()
    try:
        run_visual_pipeline(content, settings, base_url)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Visual generation failed: {exc}") from exc

    if content.get("blog", {}).get("content_blocks"):
        content["blog"]["content_blocks"] = normalize_blocks(content["blog"]["content_blocks"])

    logger.info("Visuals generated in %.1fs (separate /visuals/generate call)", time.perf_counter() - t0)
    return _apply_visuals_to_wp_payload(wp_payload, content)


@app.post("/visuals/plan")
def visuals_plan(body: GenerateVisualsRequest):
    """Plan which images to generate (fast GPT call only)."""
    from app.visual_planner import plan_visuals

    wp_payload = body.payload
    if not isinstance(wp_payload, dict) or not wp_payload:
        raise HTTPException(status_code=400, detail="payload is required.")

    content = _wp_payload_to_content(wp_payload)
    if not content:
        raise HTTPException(status_code=400, detail="No content in payload.")

    try:
        settings = _settings_from_wp_payload(wp_payload)
        plan = plan_visuals(content, settings)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"plan": plan}


@app.post("/visuals/generate-asset")
def visuals_generate_asset(request: Request, body: GenerateAssetRequest):
    """Generate a single image (~15–25s). Used for one-at-a-time WordPress requests."""
    from app.image_generator import regenerate_asset

    base_url = str(request.base_url).rstrip("/")
    try:
        asset = regenerate_asset(body.asset, base_url)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"asset": asset}


@app.post("/visuals/attach")
def visuals_attach(body: VisualAttachRequest):
    """Attach generated assets into content blocks (instant, no OpenAI)."""
    from app.blocks import normalize_blocks
    from app.visual_layer import attach_assets

    content = _wp_payload_to_content(body.payload)
    if not content:
        raise HTTPException(status_code=400, detail="No content in payload.")

    content["visuals"] = attach_assets(content, body.assets)
    if content.get("blog", {}).get("content_blocks"):
        content["blog"]["content_blocks"] = normalize_blocks(content["blog"]["content_blocks"])

    return _apply_visuals_to_wp_payload(body.payload, content)


@app.post("/regenerate")
def regenerate_content(request: Request, payload: RegenerateContentRequest):
    """Regenerate all content from a stored transcript (no re-upload)."""
    from app.blocks import normalize_blocks
    from app.generator import generate_content
    from app.visual_layer import run_visual_pipeline

    transcript = payload.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript is required.")

    try:
        settings = BrandSettings(
            tone=payload.tone,
            industry=payload.industry,
            brand_primary=payload.brand_primary,
            brand_secondary=payload.brand_secondary,
            audience=payload.audience,
            writing_style=payload.writing_style,
            outputs=parse_outputs(payload.outputs),
            cta_style=payload.cta_style,
        )
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        structured_content = generate_content(transcript, settings)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.generate_visuals:
        try:
            base_url = str(request.base_url).rstrip("/")
            visuals = run_visual_pipeline(structured_content, settings, base_url)
            structured_content["visuals"] = visuals
            if structured_content.get("blog", {}).get("content_blocks"):
                structured_content["blog"]["content_blocks"] = normalize_blocks(
                    structured_content["blog"]["content_blocks"]
                )
        except ValueError as exc:
            structured_content["visuals"] = {"error": str(exc), "assets": []}
        except Exception as exc:
            structured_content["visuals"] = {"error": f"Visual generation failed: {exc}", "assets": []}

    return _build_response("regenerate", transcript, structured_content, settings)


def _run_generation_pipeline(
    request: Request,
    transcript: str,
    settings: BrandSettings,
    filename: str,
    source: dict | None,
    generate_visuals: bool,
) -> dict:
    from app.blocks import normalize_blocks
    from app.generator import generate_content, generate_from_idea
    from app.visual_layer import run_visual_pipeline

    t2 = time.perf_counter()
    try:
        if source and source.get("type") == "idea":
            structured_content = generate_from_idea(transcript, settings)
        else:
            structured_content = generate_content(transcript, settings)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.info("Content generated in %.1fs", time.perf_counter() - t2)

    if source and source.get("type") == "blog" and structured_content.get("community_snippet"):
        snippet = structured_content["community_snippet"]
        if not snippet.get("read_more_url") and source.get("url"):
            snippet["read_more_url"] = source["url"]

    if source and source.get("type") in ("youtube", "vimeo", "loom", "blog") and "blog" in structured_content:
        blog = structured_content["blog"]
        if not blog.get("title") and source.get("title"):
            blog["title"] = source["title"]

    if source and source.get("type") == "idea" and "blog" in structured_content:
        blog = structured_content["blog"]
        if not blog.get("title"):
            blog["title"] = source.get("title", "AI Generated Article")

    if generate_visuals:
        t3 = time.perf_counter()
        try:
            base_url = str(request.base_url).rstrip("/")
            visuals = run_visual_pipeline(structured_content, settings, base_url)
            structured_content["visuals"] = visuals
            if "blog" in structured_content and structured_content["blog"].get("content_blocks"):
                structured_content["blog"]["content_blocks"] = normalize_blocks(
                    structured_content["blog"]["content_blocks"]
                )
        except ValueError as exc:
            structured_content["visuals"] = {"error": str(exc), "assets": []}
        except Exception as exc:
            structured_content["visuals"] = {
                "error": f"Visual generation failed: {exc}",
                "assets": [],
            }
        else:
            logger.info("Visuals generated in %.1fs", time.perf_counter() - t3)

    output_path = "output/generated_content.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {"brand": settings.model_dump(), "source": source, **structured_content},
            f,
            indent=4,
        )

    return _build_response(filename, transcript, structured_content, settings, source)


@app.post("/generate-idea")
def generate_idea(request: Request, payload: GenerateIdeaRequest):
    """Generate content from a written idea or brief — no file or URL required."""
    from app.generator import generate_from_idea

    idea = payload.idea.strip()
    if not idea:
        raise HTTPException(status_code=400, detail="Idea text is required.")

    try:
        settings = BrandSettings(
            tone=payload.tone,
            industry=payload.industry,
            brand_primary=payload.brand_primary,
            brand_secondary=payload.brand_secondary,
            audience=payload.audience,
            writing_style=payload.writing_style,
            outputs=parse_outputs(payload.outputs),
            cta_style=payload.cta_style,
        )
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        structured_content = generate_from_idea(idea, settings)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    source = {
        "type": "idea",
        "title": structured_content.get("blog", {}).get("title") or idea[:80],
        "idea_preview": idea[:200],
    }
    filename = re.sub(r"[^\w\s-]", "", source["title"]).strip().replace(" ", "-")[:80] or "ai-idea"

    if payload.generate_visuals:
        from app.blocks import normalize_blocks
        from app.visual_layer import run_visual_pipeline

        try:
            base_url = str(request.base_url).rstrip("/")
            visuals = run_visual_pipeline(structured_content, settings, base_url)
            structured_content["visuals"] = visuals
            if structured_content.get("blog", {}).get("content_blocks"):
                structured_content["blog"]["content_blocks"] = normalize_blocks(
                    structured_content["blog"]["content_blocks"]
                )
        except Exception as exc:
            structured_content["visuals"] = {"error": str(exc), "assets": []}

    output_path = "output/generated_content.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {"brand": settings.model_dump(), "source": source, **structured_content},
            f,
            indent=4,
        )

    return _build_response(filename, idea, structured_content, settings, source)


@app.post("/repurpose")
async def repurpose(
    request: Request,
    tone: str = Form("Professional"),
    industry: str = Form("General"),
    brand_primary: str = Form("#002a65"),
    brand_secondary: str = Form("#56814f"),
    audience: str = Form("General audience"),
    writing_style: str = Form("Educational"),
    outputs: str = Form('["blog", "linkedin", "email"]'),
    cta_style: str = Form("Direct"),
    youtube_url: str = Form(""),
    blog_url: str = Form(""),
    idea: str = Form(""),
    generate_visuals: str = Form("true"),
    file: Optional[UploadFile] = File(None),
):
    from app.blog_fetch import fetch_blog_article, is_valid_blog_url
    from app.media_download import download_media_audio, detect_media_source, is_valid_media_url
    from app.transcriber import transcribe_audio

    try:
        settings = BrandSettings(
            tone=tone,
            industry=industry,
            brand_primary=brand_primary,
            brand_secondary=brand_secondary,
            audience=audience,
            writing_style=writing_style,
            outputs=parse_outputs(outputs),
            cta_style=cta_style,
        )
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    t0 = time.perf_counter()
    source: dict | None = None
    blog_input = blog_url.strip()
    media_url = youtube_url.strip()
    idea_input = idea.strip()
    # Accept blog links pasted in the video URL field (older plugin builds).
    if not blog_input and media_url and is_valid_blog_url(media_url):
        blog_input = media_url
        media_url = ""
    transcript: str | None = None
    filename = "media-upload"

    if blog_input:
        if not is_valid_blog_url(blog_input):
            raise HTTPException(
                status_code=422,
                detail="Invalid blog URL. Use a public article link (not YouTube/Vimeo/Loom).",
            )

        article, article_error = fetch_blog_article(blog_input)
        if article_error or not article or not article.get("text"):
            raise HTTPException(
                status_code=400,
                detail=article_error or "Could not extract article text from this URL.",
            )

        transcript = article["text"]
        source = {
            "type": "blog",
            "url": blog_input,
            "title": article.get("title", "Blog Article"),
            "thumbnail_url": article.get("thumbnail_url", ""),
            "text_source": article.get("fetch_method", "blog_url"),
        }
        filename = re.sub(r"[^\w\s-]", "", source["title"]).strip().replace(" ", "-")[:80] or "blog-article"
        logger.info(
            "Blog article ready in %.1fs (%d chars, %s)",
            time.perf_counter() - t0,
            len(transcript),
            source["text_source"],
        )

    elif media_url:
        if not is_valid_media_url(media_url):
            raise HTTPException(
                status_code=422,
                detail="Invalid media URL. Use YouTube, Vimeo, or Loom share links.",
            )

        source_type = detect_media_source(media_url)
        caption_error: str | None = None

        if source_type == "youtube":
            from app.youtube import fetch_youtube_oembed
            from app.youtube_transcript import fetch_youtube_transcript

            # Fast path: YouTube captions (works on cloud IPs, great for podcasts).
            caption_result = fetch_youtube_transcript(media_url)
            if isinstance(caption_result, tuple):
                transcript, caption_error = caption_result
            else:
                transcript, caption_error = caption_result, None
            if transcript:
                meta = fetch_youtube_oembed(media_url)
                source = {
                    "type": "youtube",
                    "url": media_url,
                    "title": meta.get("title", "YouTube Video"),
                    "thumbnail_url": meta.get("thumbnail_url", ""),
                    "transcript_source": "youtube_captions",
                }
                filename = re.sub(r"[^\w\s-]", "", source["title"]).strip().replace(" ", "-")[:80] or "youtube-video"
                logger.info(
                    "YouTube captions ready in %.1fs (%d chars)",
                    time.perf_counter() - t0,
                    len(transcript),
                )

        # Full pipeline: download audio + transcribe (local dev / when allowed).
        if not transcript:
            from app.youtube import cloud_download_disabled, youtube_no_captions_message

            if source_type == "youtube" and cloud_download_disabled():
                logger.warning(
                    "YouTube captions unavailable for %s; skipping yt-dlp on cloud (%s)",
                    media_url,
                    caption_error if source_type == "youtube" else "n/a",
                )
                raise HTTPException(
                    status_code=400,
                    detail=youtube_no_captions_message(
                        caption_error if source_type == "youtube" else None
                    ),
                )

            try:
                yt = download_media_audio(media_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                detail = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()
                raise HTTPException(status_code=502, detail=detail) from exc

            upload_path = yt["file_path"]
            filename = yt["filename"]
            source_type = yt.get("source_type", source_type)
            source = {
                "type": source_type,
                "url": yt["url"],
                "title": yt["title"],
                "thumbnail_url": yt.get("thumbnail_url", ""),
                "transcript_source": "audio_transcription",
            }
            logger.info("Downloaded media in %.1fs", time.perf_counter() - t0)

            t1 = time.perf_counter()
            transcript = transcribe_audio(upload_path)
            logger.info("Transcribed in %.1fs", time.perf_counter() - t1)
    elif idea_input:
        transcript = idea_input
        source = {
            "type": "idea",
            "title": idea_input[:80],
            "idea_preview": idea_input[:200],
        }
        filename = "ai-idea"
        logger.info("AI idea ready (%d chars)", len(transcript))
    elif file and file.filename:
        upload_path = f"uploads/{file.filename}"
        with open(upload_path, "wb") as buffer:
            buffer.write(await file.read())
        filename = file.filename
        source = {"type": "upload", "filename": filename}
        logger.info("Uploaded file in %.1fs", time.perf_counter() - t0)

        t1 = time.perf_counter()
        transcript = transcribe_audio(upload_path)
        logger.info("Transcribed in %.1fs", time.perf_counter() - t1)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide a media file, blog URL, video URL, or written idea.",
        )

    if not transcript:
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not get source text for this input. "
                "For videos without captions, upload the audio/video file instead."
            ),
        )

    should_generate_visuals = generate_visuals.lower() in {"true", "1", "yes", "on"}
    logger.info("Total /repurpose source ready in %.1fs", time.perf_counter() - t0)
    return _run_generation_pipeline(
        request, transcript, settings, filename, source, should_generate_visuals
    )
