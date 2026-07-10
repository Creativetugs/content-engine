"""License keys and monthly project quotas for hosted Content Engine API."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
USAGE_PATH = Path(os.getenv("CE_LICENSE_USAGE_PATH", "data/license_usage.json"))


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def licensing_enabled() -> bool:
    return bool(load_license_catalog())


def load_license_catalog() -> dict[str, dict[str, Any]]:
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
    return {str(key).strip(): value for key, value in licenses.items() if str(key).strip()}


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


def _get_counter(usage_data: dict[str, Any], license_key: str) -> tuple[str, int]:
    month = _month_key()
    entry = usage_data.get(license_key, {})
    if not isinstance(entry, dict) or entry.get("month") != month:
        return month, 0
    return month, int(entry.get("projects_used", 0) or 0)


def _license_record(license_key: str) -> dict[str, Any]:
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
            "month": _month_key(),
            "visuals_allowed": True,
            "label": "Development",
        }
    if not license_key:
        raise ValueError("License key required. Add it in Content Engine → Dashboard.")

    record = _license_record(license_key)
    limit = int(record.get("max_projects_month", 0) or 0)
    with _lock:
        usage_data = _load_usage()
        month, used = _get_counter(usage_data, license_key)

    remaining = max(0, limit - used) if limit else 0
    return {
        "licensing_enabled": True,
        "license_key": license_key,
        "label": record.get("label", ""),
        "projects_used": used,
        "projects_limit": limit,
        "projects_remaining": remaining,
        "month": month,
        "visuals_allowed": bool(record.get("visuals_allowed", True)),
        "limit_reached": bool(limit and used >= limit),
    }


def license_check(
    license_key: str,
    *,
    increment: bool = False,
    need_visuals: bool = False,
) -> dict[str, Any]:
    if not licensing_enabled():
        return usage_summary("")

    license_key = (license_key or "").strip()
    summary = usage_summary(license_key)
    record = _license_record(license_key)

    if need_visuals and not record.get("visuals_allowed", True):
        raise ValueError("Your plan does not include AI visuals. Contact Creative Tugs to upgrade.")

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
            month, current = _get_counter(usage_data, license_key)
            if limit and current >= limit:
                raise ValueError(
                    f"Monthly project limit reached ({limit}/{limit}). "
                    "Resets on the 1st of next month or contact Creative Tugs for more."
                )
            usage_data[license_key] = {"month": month, "projects_used": current + 1}
            _save_usage(usage_data)
        logger.info("License %s usage %d/%d", license_key, current + 1, limit)
        return usage_summary(license_key)

    if limit and used >= limit:
        raise ValueError(
            f"Monthly project limit reached ({used}/{limit}). "
            "Resets on the 1st of next month or contact Creative Tugs for more."
        )

    return summary


def resolve_license_key(request_headers: dict[str, str], fallback: str = "") -> str:
    for name in ("x-ce-license", "X-CE-License"):
        if name in request_headers and request_headers[name]:
            return str(request_headers[name]).strip()
    return (fallback or "").strip()
