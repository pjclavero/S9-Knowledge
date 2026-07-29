"""Authenticated HTML routes for the Knowledge V3 human review queue."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.config import get_auth_settings
from app.auth.csrf import get_csrf_token_for_session, validate_csrf
from app.services.v3_review import ReviewError, ReviewService

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(prefix="/v3/review", tags=["v3-review"])
_RANK = {"admin": 3, "reviewer": 2, "viewer": 1}


def _service() -> ReviewService:
    return ReviewService()


def _guard(request: Request):
    if not get_auth_settings().S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    if _RANK.get(getattr(user, "role", ""), 0) < _RANK["reviewer"]:
        raise HTTPException(status_code=403, detail="Se requiere rol reviewer o admin.")
    return user


def _reviewer(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "reviewer-local"
    return getattr(user, "username", None) or getattr(user, "display_name", None) or "reviewer"


def _csrf(request: Request) -> str:
    cfg = get_auth_settings()
    session = getattr(request.state, "session", None)
    raw = getattr(request.state, "csrf_raw", "")
    return get_csrf_token_for_session(session.id if session else 0, raw, secret=cfg.S9K_CSRF_SECRET)


def _check_csrf(request: Request, token: str) -> None:
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return
    session = getattr(request.state, "session", None)
    raw = getattr(request.state, "csrf_raw", "")
    if not validate_csrf(token, session.id if session else 0, raw, secret=cfg.S9K_CSRF_SECRET):
        raise HTTPException(status_code=403, detail="CSRF inválido")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def queue(
    request: Request,
    workspace: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    engine_decision: str | None = Query(default=None),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    service = _service()
    workspaces = service.workspaces()
    selected_workspace = workspace or (workspaces[0] if len(workspaces) == 1 else None)
    if selected_workspace and selected_workspace not in workspaces:
        raise HTTPException(status_code=404, detail="Workspace no encontrado")
    view = (
        service.queue(
            selected_workspace,
            source_id=source_id,
            engine_decision=engine_decision,
        )
        if selected_workspace else None
    )
    return templates.TemplateResponse(
        request,
        "v3_review.html",
        {
            "auth_user": guard,
            "csrf_token": _csrf(request),
            "workspaces": workspaces,
            "workspace": selected_workspace,
            "source_id": source_id,
            "engine_decision": engine_decision,
            "queue": view,
            "request_id": str(uuid.uuid4()),
        },
    )


@router.post("/decide")
def decide(
    request: Request,
    workspace: str = Form(...),
    proposal_id: str = Form(...),
    human_decision: str = Form(...),
    request_id: str = Form(...),
    rationale: str = Form(""),
    predicate: str = Form(""),
    direction: str = Form(""),
    negated: str = Form(""),
    scope: str = Form(""),
    csrf_token: str = Form(""),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    _check_csrf(request, csrf_token)
    correction = {
        key: value for key, value in {
            "predicate": predicate.strip(),
            "direction": direction.strip(),
            "negated": negated == "true" if negated else None,
            "scope": scope.strip(),
        }.items()
        if value not in ("", None)
    }
    if human_decision == "CORRECT" and not correction:
        raise HTTPException(status_code=400, detail="CORRECT requiere al menos un cambio")
    try:
        _service().record(
            proposal_id=proposal_id,
            workspace=workspace,
            reviewer=_reviewer(request),
            human_decision=human_decision,
            request_id=request_id,
            rationale=rationale,
            correction=correction,
        )
    except ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/v3/review?workspace={workspace}", status_code=303)


@router.post("/undo")
def undo(
    request: Request,
    workspace: str = Form(...),
    request_id: str = Form(...),
    csrf_token: str = Form(""),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    _check_csrf(request, csrf_token)
    try:
        _service().undo_last(
            workspace=workspace,
            reviewer=_reviewer(request),
            request_id=request_id,
        )
    except ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/v3/review?workspace={workspace}", status_code=303)

