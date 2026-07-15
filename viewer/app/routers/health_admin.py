"""Rutas de estado operacional (solo admin): API JSON y panel HTML.

Solo lectura: ejecutan healthchecks y guardan el último informe sanitizado.
No reinician servicios ni escriben en Neo4j.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_admin, require_api_role
from app.auth.models import User
from app.health import runner, storage

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/api/admin/health")
async def api_admin_health(request: Request, _=Depends(require_api_role("admin"))):
    report = runner.run_report()
    try:
        storage.save_report(report)
    except Exception:
        pass
    return JSONResponse(report.to_dict())


@router.get("/admin/health", response_class=HTMLResponse)
async def admin_health_panel(request: Request, admin: User = Depends(require_admin)):
    if isinstance(admin, RedirectResponse):
        return admin
    report = runner.run_report()
    try:
        storage.save_report(report)
    except Exception:
        pass
    return templates.TemplateResponse(
        request, "auth/admin/health.html",
        {"report": report.to_dict(), "overall": report.overall.value},
    )
