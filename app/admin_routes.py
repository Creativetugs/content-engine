"""Creative Tugs operator dashboard API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.admin_auth import require_admin_secret

router = APIRouter(prefix="/admin", tags=["admin"])


class ClientUpsertRequest(BaseModel):
    license_key: str
    label: str = ""
    max_projects_month: int = Field(default=6, ge=0, le=999)
    visuals_allowed: bool = True
    active: bool = True
    notes: str = ""
    plan_price: str = ""


class ClientUsageSetRequest(BaseModel):
    projects_used: int = Field(ge=0, le=9999)


@router.get("/overview")
def admin_overview(request: Request):
    require_admin_secret(request)
    from app.licensing import list_clients_admin, licensing_enabled

    data = list_clients_admin()
    data["licensing_enabled"] = licensing_enabled()
    return data


@router.post("/clients")
def admin_upsert_client(request: Request, body: ClientUpsertRequest):
    require_admin_secret(request)
    from app.licensing import upsert_client

    try:
        return upsert_client(
            body.license_key,
            label=body.label,
            max_projects_month=body.max_projects_month,
            visuals_allowed=body.visuals_allowed,
            active=body.active,
            notes=body.notes,
            plan_price=body.plan_price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/clients/{license_key}")
def admin_delete_client(request: Request, license_key: str):
    require_admin_secret(request)
    from app.licensing import delete_client

    try:
        return delete_client(license_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/clients/{license_key}/reset")
def admin_reset_client(request: Request, license_key: str):
    require_admin_secret(request)
    from app.licensing import reset_usage

    try:
        return reset_usage(license_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/clients/reset-all")
def admin_reset_all_clients(request: Request):
    require_admin_secret(request)
    from app.licensing import reset_usage

    return reset_usage(all_keys=True)


@router.post("/clients/{license_key}/usage")
def admin_set_client_usage(request: Request, license_key: str, body: ClientUsageSetRequest):
    require_admin_secret(request)
    from app.licensing import set_usage_count

    try:
        return set_usage_count(license_key, body.projects_used)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
