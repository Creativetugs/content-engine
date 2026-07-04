from typing import Any


def blocks_to_html(blocks: list[dict[str, Any]], brand: dict[str, Any] | None = None) -> str:
    brand = brand or {}
    primary = brand.get("brand_primary", "#002a65")
    secondary = brand.get("brand_secondary", "#56814f")

    parts = [
        f'<article class="ce-content" style="--ce-primary:{primary};--ce-secondary:{secondary}">'
    ]

    for block in blocks:
        block_type = block.get("type")

        if block_type == "heading":
            level = block.get("level", "h2")
            if level not in {"h1", "h2", "h3", "h4"}:
                level = "h2"
            parts.append(f"<{level}>{_esc(block.get('text', ''))}</{level}>")

        elif block_type == "paragraph":
            parts.append(f"<p>{_esc(block.get('text', ''))}</p>")

        elif block_type == "bullet_list":
            items = "".join(f"<li>{_esc(item)}</li>" for item in block.get("items", []))
            parts.append(f"<ul>{items}</ul>")

        elif block_type == "quote":
            parts.append(f"<blockquote><p>{_esc(block.get('text', ''))}</p></blockquote>")

        elif block_type == "faq":
            parts.append(
                '<div class="ce-faq">'
                f"<h4>{_esc(block.get('question', ''))}</h4>"
                f"<p>{_esc(block.get('answer', ''))}</p>"
                "</div>"
            )

        elif block_type == "cta":
            parts.append(
                f'<p class="ce-cta"><a href="{_esc(block.get("button_url", "#"))}" '
                f'style="background:{primary};color:#fff;padding:12px 24px;text-decoration:none;'
                f'border-radius:4px;display:inline-block;">'
                f"{_esc(block.get('button_text', 'Learn More'))}</a></p>"
            )

        elif block_type == "image":
            url = _esc(block.get("url", ""))
            alt = _esc(block.get("alt", ""))
            caption = block.get("caption", "")
            cap_html = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
            parts.append(
                f'<figure class="ce-image"><img src="{url}" alt="{alt}" loading="lazy">{cap_html}</figure>'
            )

    parts.append("</article>")
    return "\n".join(parts)


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    for block in blocks:
        block_type = block.get("type")

        if block_type == "heading":
            level = block.get("level", "h2")
            hashes = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}.get(level, "##")
            lines.append(f"{hashes} {block.get('text', '')}\n")

        elif block_type == "paragraph":
            lines.append(f"{block.get('text', '')}\n")

        elif block_type == "bullet_list":
            for item in block.get("items", []):
                lines.append(f"- {item}")
            lines.append("")

        elif block_type == "quote":
            lines.append(f"> {block.get('text', '')}\n")

        elif block_type == "faq":
            lines.append(f"**{block.get('question', '')}**\n")
            lines.append(f"{block.get('answer', '')}\n")

        elif block_type == "cta":
            text = block.get("button_text", "Learn More")
            url = block.get("button_url", "#")
            lines.append(f"[{text}]({url})\n")

    return "\n".join(lines).strip()


def blocks_to_gutenberg(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []

    for block in blocks:
        block_type = block.get("type")

        if block_type == "heading":
            level = int(block.get("level", "h2").replace("h", ""))
            text = _esc(block.get("text", ""))
            parts.append(f'<!-- wp:heading {{"level":{level}}} -->\n<{block.get("level", "h2")}>{text}</{block.get("level", "h2")}>\n<!-- /wp:heading -->')

        elif block_type == "paragraph":
            text = _esc(block.get("text", ""))
            parts.append(f"<!-- wp:paragraph -->\n<p>{text}</p>\n<!-- /wp:paragraph -->")

        elif block_type == "bullet_list":
            items = "".join(f"<li>{_esc(item)}</li>" for item in block.get("items", []))
            parts.append(f"<!-- wp:list -->\n<ul>{items}</ul>\n<!-- /wp:list -->")

        elif block_type == "quote":
            text = _esc(block.get("text", ""))
            parts.append(f"<!-- wp:quote -->\n<blockquote class=\"wp-block-quote\"><p>{text}</p></blockquote>\n<!-- /wp:quote -->")

        elif block_type == "faq":
            q = _esc(block.get("question", ""))
            a = _esc(block.get("answer", ""))
            parts.append(
                f"<!-- wp:heading {{\"level\":4}} -->\n<h4>{q}</h4>\n<!-- /wp:heading -->\n"
                f"<!-- wp:paragraph -->\n<p>{a}</p>\n<!-- /wp:paragraph -->"
            )

        elif block_type == "cta":
            text = _esc(block.get("button_text", "Learn More"))
            url = _esc(block.get("button_url", "#"))
            parts.append(
                f'<!-- wp:buttons -->\n<div class="wp-block-buttons">'
                f'<!-- wp:button -->\n<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="{url}">{text}</a></div>\n<!-- /wp:button -->'
                f"</div>\n<!-- /wp:buttons -->"
            )

    return "\n\n".join(parts)


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
