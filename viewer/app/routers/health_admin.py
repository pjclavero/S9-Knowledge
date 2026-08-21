"""Rutas de estado operacional (solo admin): API JSON, panel HTML e instantánea.

FRONTERA, y es el motivo de este módulo: **ningún `GET` de aquí escribe**.

Hasta 2026-08-19 los dos `GET` ejecutaban los healthchecks y, dentro de la misma
petición, llamaban a ``storage.save_report(report)`` — que hace ``mkdir`` +
``write_text`` + ``os.replace`` + ``chmod 0600``, es decir, deja estado DURABLE
en disco. El censo de métodos de escritura (docs/84) los marcó como
``lectura-que-escribe`` y la decisión del operador fue explícita: *«si esos dos
GET provocan escritura, el defecto está en las rutas, no en la puerta»*. Sin
exenciones y sin listas blancas: se arregla la ruta.

Cómo se resolvió, endpoint por endpoint y por SEMÁNTICA:

``GET /api/admin/health`` y ``GET /admin/health``
    Lo que estos endpoints pretenden hacer es **consultar** la salud: ejecutan
    las comprobaciones y devuelven el resultado. Guardarlo era **incidental**
    —una caché para que el panel B (``/panel/operations``) tuviera algo que
    enseñar—, no la operación que el endpoint nombra. Se elimina la escritura:
    quedan de LECTURA PURA. Ejecutar comprobaciones no es escribir; no deja
    estado durable propio.

``POST /admin/health/snapshot`` (NUEVO)
    Aquí la escritura **sí es la operación**: «toma una instantánea y guárdala».
    Por eso es un verbo mutador, con ``require_admin`` y verificación CSRF, como
    el resto de escrituras del panel de administración. Existe para no perder la
    capacidad que el ``GET`` daba de refilón: refrescar desde la interfaz el
    informe que ``/panel/operations`` lee.

QUIÉN CONSUME EL INFORME GUARDADO, comprobado antes de tocar nada:
``app.health.storage.load_last`` lo leen ``app/routers/chassis_operations.py``
(panel B) y ``app/cli/health.py``. El CLI **también lo escribe**, y es el camino
previsto en producción (el timer horario), así que quitar la escritura del
``GET`` no deja al panel sin fuente: sigue teniendo el CLI y ahora, además, un
POST explícito.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.config import get_auth_settings
from app.auth.csrf import get_csrf_token_for_session, validate_csrf
from app.auth.dependencies import require_admin, require_api_role
from app.auth.models import User
from app.health import runner, storage

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _get_csrf(request: Request, session_id: int) -> str:
    cfg = get_auth_settings()
    raw = getattr(request.state, "csrf_raw", "")
    return get_csrf_token_for_session(session_id, raw, secret=cfg.S9K_CSRF_SECRET)


def _check_csrf(request: Request, token: str, session_id: int) -> bool:
    cfg = get_auth_settings()
    raw = getattr(request.state, "csrf_raw", "")
    return validate_csrf(token, session_id, raw, secret=cfg.S9K_CSRF_SECRET)


@router.get("/api/admin/health")
async def api_admin_health(request: Request, _=Depends(require_api_role("admin"))):
    """Consulta de salud. NO persiste: para eso está el POST de instantánea."""
    report = runner.run_report()
    return JSONResponse(report.to_dict())


@router.get("/admin/health", response_class=HTMLResponse)
async def admin_health_panel(request: Request, admin: User = Depends(require_admin)):
    """Consulta de salud en HTML. NO persiste."""
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)
    report = runner.run_report()
    return templates.TemplateResponse(
        request, "auth/admin/health.html",
        {
            "report": report.to_dict(),
            "overall": report.overall.value,
            "csrf_token": _get_csrf(request, session.id if session else 0),
            "hay_informe_guardado": storage.load_last() is not None,
        },
    )


@router.post("/admin/health/snapshot")
async def admin_health_snapshot(
    request: Request,
    csrf_token: str = Form(...),
    admin: User = Depends(require_admin),
):
    """Ejecuta el informe y lo GUARDA.

    La escritura es la operación que este endpoint nombra, así que el verbo es
    mutador y lleva guardián de administración y CSRF.
    """
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)
    if not _check_csrf(request, csrf_token, session.id if session else 0):
        raise HTTPException(status_code=403, detail="CSRF inválido")
    report = runner.run_report()
    storage.save_report(report)
    return RedirectResponse(url="/admin/health", status_code=302)
