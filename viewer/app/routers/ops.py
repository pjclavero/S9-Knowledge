"""Centro de Estado de S9 Knowledge — panel de observación (solo admin).

100% solo lectura: este router no expone ni una sola ruta POST/PUT/DELETE.
No reinicia servicios, no lanza ni cancela jobs, no escribe en Neo4j, no
consulta Proxmox y no revela secretos, rutas del servidor ni trazas.

Montaje: `viewer/app/main.py` pertenece a otro equipo en este programa, así
que este router NO se auto-registra. Para activarlo hace falta una línea en
main.py (ver docs/current/ADMIN_OPERATIONS_DASHBOARD.md):

    from app.routers import ops as ops_router
    app.include_router(ops_router.router)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_admin, require_api_role
from app.auth.models import User
from app.ops import collector

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/api/admin/ops")
async def api_admin_ops(request: Request, _=Depends(require_api_role("admin"))):
    """Informe JSON del Centro de Estado. Nunca escribe nada."""
    return JSONResponse(collector.build_report().to_dict())


@router.get("/admin/ops", response_class=HTMLResponse)
async def admin_ops_panel(request: Request, admin: User = Depends(require_admin)):
    if isinstance(admin, RedirectResponse):
        return admin
    report = collector.build_report()
    return templates.TemplateResponse(
        request,
        "auth/admin/ops.html",
        {"report": report.to_dict(), "overall": report.overall.value, "admin": admin},
    )
