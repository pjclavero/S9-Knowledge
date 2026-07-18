"""Panel de revisión v1 (Equipo B) — consola de revisión del visor.

Rutas (reviewer+):
  GET  /review-console                         → bandeja de fuentes (summaries v1)
  GET  /review-console/source/{source_id}      → candidatos + preview del plan
  POST /review-console/source/{source_id}/decide → registra review-decision v1 +
                                                    review-audit-event v1 (control
                                                    optimista). NUNCA escribe Neo4j.

El panel produce ÚNICAMENTE review-decision v1 y review-audit-event v1 en un
almacén LOCAL de laboratorio. No aplica el ingest-plan, no autoriza ingesta y no
modifica el review original.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.config import get_auth_settings
from app.auth.csrf import get_csrf_token_for_session, validate_csrf
from app.services import review_console as rc

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/review-console", tags=["review-console"])

_RANK = {"admin": 3, "reviewer": 2, "viewer": 1}


# ---------------------------------------------------------------------------
# Guardias (reviewer+); no tocan el middleware global de permisos (Equipo C)
# ---------------------------------------------------------------------------
def _guard(request: Request):
    """reviewer+: público con auth off; 302 /login anónimo; 403 rol insuficiente."""
    if not get_auth_settings().S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    if _RANK.get(getattr(user, "role", ""), 0) < _RANK["reviewer"]:
        raise HTTPException(status_code=403, detail="Se requiere rol reviewer o admin.")
    return user


def _reviewer_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is not None:
        return getattr(user, "username", None) or getattr(user, "display_name", None) or "reviewer"
    return "reviewer-local"


def _session_id(request: Request) -> int:
    session = getattr(request.state, "session", None)
    return session.id if session is not None else 0


def _csrf_token(request: Request) -> str:
    cfg = get_auth_settings()
    raw = getattr(request.state, "csrf_raw", "")
    return get_csrf_token_for_session(_session_id(request), raw, secret=cfg.S9K_CSRF_SECRET)


def _check_csrf(request: Request, token: str) -> bool:
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return True  # auth off: sin sesión ni CSRF (paridad con el resto del visor)
    raw = getattr(request.state, "csrf_raw", "")
    return validate_csrf(token, _session_id(request), raw, secret=cfg.S9K_CSRF_SECRET)


# ---------------------------------------------------------------------------
# GET bandeja
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def inbox(request: Request):
    guard = _guard(request)
    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    summaries = rc.list_source_summaries()
    return templates.TemplateResponse(
        request, "reviews_console.html",
        {"summaries": summaries, "auth_user": guard, "csrf_token": _csrf_token(request)},
    )


# ---------------------------------------------------------------------------
# GET detalle de fuente: candidatos + preview del plan
# ---------------------------------------------------------------------------
@router.get("/source/{source_id}", response_class=HTMLResponse)
def source_detail(request: Request, source_id: str, stale: int = 0):
    guard = _guard(request)
    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    summary = rc.get_source_summary(source_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Fuente no encontrada: {source_id}")
    candidates = [rc.candidate_view(c) for c in rc.list_candidates(source_id)]
    preview = rc.plan_preview(source_id)
    return templates.TemplateResponse(
        request, "reviews_console_source.html",
        {
            "summary": summary, "source_id": source_id, "candidates": candidates,
            "plan_preview": preview, "actions": sorted(rc.VALID_ACTIONS),
            "stale_warning": bool(stale), "auth_user": guard,
            "csrf_token": _csrf_token(request),
        },
    )


# ---------------------------------------------------------------------------
# POST decisión
# ---------------------------------------------------------------------------
@router.post("/source/{source_id}/decide")
async def decide(
    request: Request,
    source_id: str,
    candidate_id: str = Form(...),
    action: str = Form(...),
    expected_candidate_hash: str = Form(...),
    reason_code: str = Form(""),
    comment: str = Form(""),
    after_canonical_name: str = Form(""),
    target_existing_id: str = Form(""),
    csrf_token: str = Form(""),
):
    guard = _guard(request)
    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    if not _check_csrf(request, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF inválido")
    if action not in rc.VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"acción no válida: {action}")

    after = {"canonical_name": after_canonical_name} if after_canonical_name else None
    try:
        result = rc.submit_decision(
            source_id, candidate_id, action, _reviewer_id(request),
            expected_candidate_hash={"algorithm": "sha256", "value": expected_candidate_hash},
            reason_code=reason_code or None, comment=comment or None,
            after=after, target_existing_id=target_existing_id or None,
            request_id=getattr(request.state, "request_id", None),
        )
    except rc.ReviewConsoleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Control optimista: si es obsoleta, volver al detalle con aviso.
    if result.stale:
        return RedirectResponse(url=f"/review-console/source/{source_id}?stale=1",
                                status_code=303)
    return RedirectResponse(url=f"/review-console/source/{source_id}", status_code=303)
