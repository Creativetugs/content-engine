"""License keys, monthly project quotas, and spend caps for Content Engine API."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
USAGE_PATH = Path(os.getenv("CE_LICENSE_USAGE_PATH", "data/license_usage.json"))
CATALOG_PATH = Path(os.getenv("CE_LICENSE_CATALOG_PATH", "data/licenses.json"))

DEFAULT_MAX_SPEND_USD = float(os.getenv("CE_DEFAULT_MAX_SPEND_USD", "20"))
IMAGE_COST_USD = float(os.getenv("CE_IMAGE_COST_USD", "0.06"))
PLANNER_COST_USD = float(os.getenv("CE_PLANNER_COST_USD", "0.02"))


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def global_kill_enabled() -> bool:
    return os.getenv("CE_GLOBAL_KILL", "").strip().lower() in {"1", "true", "yes", "on"}


def estimate_visual_cost_usd(image_count: int) -> float:
    count = max(0, int(image_count or 0))
    if count <= 0:
        return 0.0
    return round(PLANNER_COST_USD + (count * IMAGE_COST_USD), 4)


def _load_catalog_from_env() -> dict[str, dict[str, Any]]:
    raw = os.getenv("CE_LICENSES", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("CE_LICENSES JSON invalid: %s", exc)
        return {}
    if isinstance(data, dict) and "licenses" in data:
        licenses = data["licenses"]
    else:
        licenses = data
    if not isinstance(licenses, dict):
        return {}
    return {str(key).strip(): _normalize_license_record(value) for key, value in licenses.items() if str(key).strip()}


def _load_catalog_from_file() -> dict[str, dict[str, Any]]:
    if not CATALOG_PATH.is_file():
        return {}
    try:
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read license catalog file: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    if "licenses" in data and isinstance(data["licenses"], dict):
        data = data["licenses"]
    return {
        str(key).strip(): _normalize_license_record(value)
        for key, value in data.items()
        if str(key).strip()
    }


def _normalize_license_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        record = {}
    brand_kit = record.get("brand_kit")
    if not isinstance(brand_kit, dict):
        brand_kit = {}
    try:
        max_spend = float(record.get("max_spend_usd_month", DEFAULT_MAX_SPEND_USD) or DEFAULT_MAX_SPEND_USD)
    except (TypeError, ValueError):
        max_spend = DEFAULT_MAX_SPEND_USD
    max_spend = max(0.0, min(10000.0, max_spend))
    return {
        "label": str(record.get("label", "") or "").strip(),
        "max_projects_month": int(record.get("max_projects_month", 0) or 0),
        "max_spend_usd_month": max_spend,
        "visuals_allowed": bool(record.get("visuals_allowed", True)),
        "active": bool(record.get("active", True)),
        "notes": str(record.get("notes", "") or "").strip(),
        "plan_price": str(record.get("plan_price", "") or "").strip(),
        "website_url": str(record.get("website_url", "") or "").strip(),
        "brand_kit": brand_kit,
    }


def _save_catalog_to_file(catalog: dict[str, dict[str, Any]]) -> None:
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CATALOG_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump({"licenses": catalog}, handle, indent=2)
    tmp.replace(CATALOG_PATH)


def licensing_enabled() -> bool:
    return bool(load_license_catalog())


def load_license_catalog() -> dict[str, dict[str, Any]]:
    """Env seeds defaults; data/licenses.json overrides (admin dashboard edits)."""
    merged = _load_catalog_from_env()
    merged.update(_load_catalog_from_file())
    return merged


def _load_usage() -> dict[str, Any]:
    if not USAGE_PATH.is_file():
        return {}
    try:
        with USAGE_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read license usage file: %s", exc)
        return {}


def _save_usage(data: dict[str, Any]) -> None:
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USAGE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    tmp.replace(USAGE_PATH)


def _get_counter(usage_data: dict[str, Any], license_key: str) -> tuple[str, int, float]:
    month = _month_key()
    entry = usage_data.get(license_key, {})
    if not isinstance(entry, dict) or entry.get("month") != month:
        return month, 0, 0.0
    try:
        spend = float(entry.get("spend_usd", 0) or 0)
    except (TypeError, ValueError):
        spend = 0.0
    return month, int(entry.get("projects_used", 0) or 0), max(0.0, spend)


def _license_record(license_key: str) -> dict[str, Any]:
    if global_kill_enabled():
        raise ValueError(
            "Content Engine is temporarily paused (global kill switch). Contact Creative Tugs."
        )
    catalog = load_license_catalog()
    record = catalog.get(license_key)
    if not isinstance(record, dict):
        raise ValueError("Invalid license key. Contact Creative Tugs for access.")
    if not record.get("active", True):
        raise ValueError("This license is inactive. Contact Creative Tugs.")
    return record


def usage_summary(license_key: str) -> dict[str, Any]:
    license_key = (license_key or "").strip()
    if not licensing_enabled():
        return {
            "licensing_enabled": False,
            "license_key": license_key,
            "projects_used": 0,
            "projects_limit": 0,
            "projects_remaining": 0,
            "spend_usd": 0.0,
            "spend_limit_usd": DEFAULT_MAX_SPEND_USD,
            "spend_remaining_usd": DEFAULT_MAX_SPEND_USD,
            "month": _month_key(),
            "visuals_allowed": True,
            "label": "Development",
            "global_kill": global_kill_enabled(),
            "image_cost_usd": IMAGE_COST_USD,
            "planner_cost_usd": PLANNER_COST_USD,
        }
    if not license_key:
        raise ValueError("License key required. Add it in Content Engine → Dashboard.")

    record = _license_record(license_key)
    limit = int(record.get("max_projects_month", 0) or 0)
    spend_limit = float(record.get("max_spend_usd_month", DEFAULT_MAX_SPEND_USD) or DEFAULT_MAX_SPEND_USD)
    with _lock:
        usage_data = _load_usage()
        month, used, spend = _get_counter(usage_data, license_key)

    remaining = max(0, limit - used) if limit else 0
    spend_remaining = max(0.0, round(spend_limit - spend, 4)) if spend_limit else 0.0
    return {
        "licensing_enabled": True,
        "license_key": license_key,
        "label": record.get("label", ""),
        "projects_used": used,
        "projects_limit": limit,
        "projects_remaining": remaining,
        "spend_usd": round(spend, 4),
        "spend_limit_usd": spend_limit,
        "spend_remaining_usd": spend_remaining,
        "month": month,
        "visuals_allowed": bool(record.get("visuals_allowed", True)),
        "limit_reached": bool(limit and used >= limit),
        "spend_limit_reached": bool(spend_limit and spend >= spend_limit),
        "website_url": record.get("website_url", ""),
        "has_brand_kit": bool(record.get("brand_kit")),
        "global_kill": False,
        "image_cost_usd": IMAGE_COST_USD,
        "planner_cost_usd": PLANNER_COST_USD,
    }


def license_check(
    license_key: str,
    *,
    increment: bool = False,
    need_visuals: bool = False,
    image_count: int = 0,
) -> dict[str, Any]:
    if not licensing_enabled():
        if global_kill_enabled():
            raise ValueError(
                "Content Engine is temporarily paused (global kill switch). Contact Creative Tugs."
            )
        return usage_summary("")

    license_key = (license_key or "").strip()
    summary = usage_summary(license_key)
    record = _license_record(license_key)

    if need_visuals and not record.get("visuals_allowed", True):
        raise ValueError("Your plan does not include AI visuals. Contact Creative Tugs to upgrade.")

    spend_limit = float(record.get("max_spend_usd_month", DEFAULT_MAX_SPEND_USD) or DEFAULT_MAX_SPEND_USD)
    spend_used = float(summary.get("spend_usd", 0) or 0)
    if need_visuals and spend_limit and spend_used >= spend_limit:
        raise ValueError(
            f"Monthly OpenAI spend limit reached (${spend_used:.2f}/${spend_limit:.2f}). "
            "Contact Creative Tugs to raise your budget."
        )

    # Soft pre-check: estimated cost for upcoming images would exceed remaining budget.
    if need_visuals and image_count > 0 and spend_limit:
        projected = estimate_visual_cost_usd(image_count)
        if spend_used + projected > spend_limit + 0.001:
            remaining = max(0.0, spend_limit - spend_used)
            raise ValueError(
                f"Estimated visual cost (~${projected:.2f}) exceeds remaining budget "
                f"(${remaining:.2f} of ${spend_limit:.2f}). Lower image count or contact Creative Tugs."
            )

    limit = int(record.get("max_projects_month", 0) or 0)
    used = int(summary["projects_used"])

    if increment:
        if limit and used >= limit:
            raise ValueError(
                f"Monthly project limit reached ({limit}/{limit}). "
                "Resets on the 1st of next month or contact Creative Tugs for more."
            )
        with _lock:
            usage_data = _load_usage()
            month, current, spend = _get_counter(usage_data, license_key)
            if limit and current >= limit:
                raise ValueError(
                    f"Monthly project limit reached ({limit}/{limit}). "
                    "Resets on the 1st of next month or contact Creative Tugs for more."
                )
            add_spend = estimate_visual_cost_usd(image_count) if image_count else 0.0
            if spend_limit and (spend + add_spend) > spend_limit + 0.001 and add_spend:
                raise ValueError(
                    f"Monthly OpenAI spend limit reached (${spend:.2f}/${spend_limit:.2f}). "
                    "Contact Creative Tugs to raise your budget."
                )
            usage_data[license_key] = {
                "month": month,
                "projects_used": current + 1,
                "spend_usd": round(spend + add_spend, 4),
            }
            _save_usage(usage_data)
        logger.info(
            "License %s usage %d/%d spend +%.4f",
            license_key,
            current + 1,
            limit,
            add_spend,
        )
        return usage_summary(license_key)

    if limit and used >= limit:
        raise ValueError(
            f"Monthly project limit reached ({used}/{limit}). "
            "Resets on the 1st of next month or contact Creative Tugs for more."
        )

    return summary


def record_visual_spend(license_key: str, image_count: int) -> dict[str, Any]:
    """Add estimated visual spend without incrementing project count."""
    if not licensing_enabled():
        return usage_summary("")
    license_key = (license_key or "").strip()
    if not license_key or image_count <= 0:
        return usage_summary(license_key) if license_key else usage_summary("")

    record = _license_record(license_key)
    spend_limit = float(record.get("max_spend_usd_month", DEFAULT_MAX_SPEND_USD) or DEFAULT_MAX_SPEND_USD)
    add_spend = estimate_visual_cost_usd(image_count)

    with _lock:
        usage_data = _load_usage()
        month, used, spend = _get_counter(usage_data, license_key)
        if spend_limit and spend >= spend_limit:
            raise ValueError(
                f"Monthly OpenAI spend limit reached (${spend:.2f}/${spend_limit:.2f}). "
                "Contact Creative Tugs to raise your budget."
            )
        usage_data[license_key] = {
            "month": month,
            "projects_used": used,
            "spend_usd": round(spend + add_spend, 4),
        }
        _save_usage(usage_data)
    return usage_summary(license_key)


def resolve_license_key(request_headers: dict[str, str], fallback: str = "") -> str:
    for name in ("x-ce-license", "X-CE-License"):
        if name in request_headers and request_headers[name]:
            return str(request_headers[name]).strip()
    return (fallback or "").strip()


def billable_visual_assets(assets: Any) -> bool:
    if not isinstance(assets, list):
        return False
    return any(isinstance(asset, dict) and asset.get("url") for asset in assets)


def count_billable_assets(assets: Any) -> int:
    if not isinstance(assets, list):
        return 0
    return sum(1 for asset in assets if isinstance(asset, dict) and asset.get("url"))


def get_brand_kit(license_key: str) -> dict[str, Any]:
    license_key = (license_key or "").strip()
    if not license_key or not licensing_enabled():
        return {}
    catalog = load_license_catalog()
    record = catalog.get(license_key)
    if not isinstance(record, dict):
        return {}
    kit = record.get("brand_kit")
    return kit if isinstance(kit, dict) else {}


def save_brand_kit(license_key: str, website_url: str, brand_kit: dict[str, Any]) -> dict[str, Any]:
    license_key = (license_key or "").strip()
    if not license_key:
        raise ValueError("License key is required to remember brand research.")
    if not isinstance(brand_kit, dict) or not brand_kit:
        raise ValueError("brand_kit is required.")

    with _lock:
        catalog = load_license_catalog()
        existing = catalog.get(license_key)
        if not isinstance(existing, dict):
            # Allow saving kit even if key only exists in env by writing file override.
            existing = _normalize_license_record({"label": license_key, "max_projects_month": 6})
        record = _normalize_license_record(
            {
                **existing,
                "website_url": website_url or existing.get("website_url", ""),
                "brand_kit": brand_kit,
            }
        )
        file_catalog = _load_catalog_from_file()
        file_catalog[license_key] = record
        _save_catalog_to_file(file_catalog)

    logger.info("Saved brand kit for license %s", license_key)
    return {"ok": True, "license_key": license_key, "brand_kit": brand_kit, "website_url": record["website_url"]}


def reset_usage(license_key: str = "", *, all_keys: bool = False) -> dict[str, Any]:
    """Reset monthly project counter and spend for one license or all licenses."""
    if not licensing_enabled():
        return {
            "reset": True,
            "licensing_enabled": False,
            "month": _month_key(),
        }

    month = _month_key()
    with _lock:
        usage_data = _load_usage()
        if all_keys:
            usage_data = {}
            _save_usage(usage_data)
            logger.info("License usage reset for ALL keys")
            return {
                "reset": True,
                "scope": "all",
                "month": month,
                "licensing_enabled": True,
            }

        license_key = (license_key or "").strip()
        if not license_key:
            raise ValueError("license_key is required unless all=true.")

        _license_record(license_key)
        usage_data[license_key] = {"month": month, "projects_used": 0, "spend_usd": 0.0}
        _save_usage(usage_data)

    logger.info("License usage reset for %s", license_key)
    summary = usage_summary(license_key)
    summary["reset"] = True
    summary["scope"] = license_key
    return summary


def list_clients_admin() -> dict[str, Any]:
    """All clients with usage for the operator dashboard."""
    catalog = load_license_catalog()
    month = _month_key()
    with _lock:
        usage_data = _load_usage()

    clients: list[dict[str, Any]] = []
    total_used = 0
    total_spend = 0.0
    active_count = 0

    for license_key in sorted(catalog.keys()):
        record = catalog[license_key]
        _, used, spend = _get_counter(usage_data, license_key)
        limit = int(record.get("max_projects_month", 0) or 0)
        spend_limit = float(record.get("max_spend_usd_month", DEFAULT_MAX_SPEND_USD) or DEFAULT_MAX_SPEND_USD)
        remaining = max(0, limit - used) if limit else 0
        active = bool(record.get("active", True))

        if active:
            active_count += 1
        total_used += used
        total_spend += spend

        clients.append(
            {
                "license_key": license_key,
                "label": record.get("label", ""),
                "max_projects_month": limit,
                "projects_used": used,
                "projects_remaining": remaining,
                "spend_usd": round(spend, 4),
                "max_spend_usd_month": spend_limit,
                "spend_remaining_usd": max(0.0, round(spend_limit - spend, 4)),
                "visuals_allowed": bool(record.get("visuals_allowed", True)),
                "active": active,
                "notes": record.get("notes", ""),
                "plan_price": record.get("plan_price", ""),
                "website_url": record.get("website_url", ""),
                "has_brand_kit": bool(record.get("brand_kit")),
                "limit_reached": bool(limit and used >= limit),
                "spend_limit_reached": bool(spend_limit and spend >= spend_limit),
                "month": month,
            }
        )

    return {
        "month": month,
        "client_count": len(clients),
        "active_count": active_count,
        "total_projects_used": total_used,
        "total_spend_usd": round(total_spend, 4),
        "clients": clients,
        "global_kill": global_kill_enabled(),
        "catalog_source": "file+env" if CATALOG_PATH.is_file() else "env",
        "usage_path": str(USAGE_PATH),
        "catalog_path": str(CATALOG_PATH),
    }


def upsert_client(
    license_key: str,
    *,
    label: str = "",
    max_projects_month: int = 6,
    max_spend_usd_month: float = DEFAULT_MAX_SPEND_USD,
    visuals_allowed: bool = True,
    active: bool = True,
    notes: str = "",
    plan_price: str = "",
    website_url: str = "",
    brand_kit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    license_key = (license_key or "").strip().upper()
    if not license_key:
        raise ValueError("License key is required.")
    if not re.match(r"^[A-Z0-9][A-Z0-9_-]{2,63}$", license_key):
        raise ValueError("License key must be 3–64 chars: letters, numbers, dash, underscore.")

    existing = load_license_catalog().get(license_key, {})
    keep_kit = brand_kit if isinstance(brand_kit, dict) else existing.get("brand_kit", {})
    record = _normalize_license_record(
        {
            "label": label,
            "max_projects_month": max_projects_month,
            "max_spend_usd_month": max_spend_usd_month,
            "visuals_allowed": visuals_allowed,
            "active": active,
            "notes": notes,
            "plan_price": plan_price,
            "website_url": website_url or existing.get("website_url", ""),
            "brand_kit": keep_kit,
        }
    )

    with _lock:
        catalog = _load_catalog_from_file()
        catalog[license_key] = record
        _save_catalog_to_file(catalog)

    logger.info("License catalog upsert: %s", license_key)
    return usage_summary(license_key)


def delete_client(license_key: str) -> dict[str, Any]:
    license_key = (license_key or "").strip()
    if not license_key:
        raise ValueError("License key is required.")

    catalog_all = load_license_catalog()
    if license_key not in catalog_all:
        raise ValueError(f"License key not found: {license_key}")

    with _lock:
        catalog = _load_catalog_from_file()
        existing = catalog_all.get(license_key, {})
        catalog[license_key] = _normalize_license_record(
            {
                **existing,
                "active": False,
                "notes": (existing.get("notes", "") + " [deactivated in admin]").strip(),
            }
        )
        _save_catalog_to_file(catalog)

        usage_data = _load_usage()
        usage_data.pop(license_key, None)
        _save_usage(usage_data)

    logger.info("License deactivated: %s", license_key)
    return {"deleted": True, "license_key": license_key, "active": False}


def set_usage_count(license_key: str, projects_used: int) -> dict[str, Any]:
    license_key = (license_key or "").strip()
    if not license_key:
        raise ValueError("License key is required.")
    if projects_used < 0:
        raise ValueError("projects_used cannot be negative.")

    _license_record(license_key)
    month = _month_key()

    with _lock:
        usage_data = _load_usage()
        _, _, spend = _get_counter(usage_data, license_key)
        usage_data[license_key] = {
            "month": month,
            "projects_used": int(projects_used),
            "spend_usd": spend,
        }
        _save_usage(usage_data)

    return usage_summary(license_key)
