"""Admin authentication for Creative Tugs operator dashboard."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request


def admin_secret_configured() -> bool:
    return bool(os.getenv("CE_ADMIN_SECRET", "").strip())


def require_admin_secret(request: Request) -> None:
    secret = os.getenv("CE_ADMIN_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=403,
            detail="Set CE_ADMIN_SECRET on Railway to use the admin dashboard.",
        )

    provided = (
        request.headers.get("x-ce-admin-secret")
        or request.headers.get("X-CE-Admin-Secret")
        or request.query_params.get("admin_secret")
        or ""
    ).strip()

    if not provided or provided != secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret.")
