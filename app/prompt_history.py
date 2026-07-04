from datetime import datetime, timezone
from typing import Any


def record_prompt_history(visuals: dict[str, Any], assets: list[dict]) -> list[dict]:
    """Append generated asset prompts to project prompt history."""
    history = list(visuals.get("prompt_history") or [])
    seen = {(h.get("asset_id"), h.get("prompt")) for h in history if h.get("prompt")}

    for asset in assets:
        prompt = (asset.get("prompt") or "").strip()
        if not prompt:
            continue
        key = (asset.get("id", ""), prompt)
        if key in seen:
            continue
        history.append(
            {
                "asset_id": asset.get("id", ""),
                "role": asset.get("role", ""),
                "prompt": prompt,
                "status": asset.get("status", "generated"),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        seen.add(key)

    return history[-50:]
