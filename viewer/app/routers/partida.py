"""Selector de partida activa (M5a, docs/v3/49-multipartida-diseno.md §2.6).

Un usuario logueado puede tener varias partidas asignadas por un admin
(``partida_access``), pero solo una activa por sesión (``sessions.
active_partida``). Este router expone el único punto de escritura de ese
estado: elegir cuál está activa ahora mismo. No hace ninguna otra cosa —
el aislamiento real ocurre en ``app.policies.engine.VisibilityPolicy``
sobre el valor que aquí se fija.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import audit, db as auth_db
from app.auth.config import get_auth_settings
from app.auth.csrf import validate_csrf
from app.auth.dependencies import require_authenticated_user
from app.auth.models import User

router = APIRouter()


def _get_db_path() -> Path:
    return Path(get_auth_settings().S9K_AUTH_DB_PATH)


def _safe_next(next_url: Optional[str]) -> str:
    """Anti open-redirect: solo rutas relativas internas (mismo criterio que /login)."""
    if not next_url:
        return "/"
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc or not next_url.startswith("/"):
        return "/"
    return next_url


@router.post("/partida/select")
async def select_partida(
    request: Request,
    partida_id: str = Form(default=""),
    next: str = Form(default="/"),
    csrf_token: str = Form(...),
    user: User = Depends(require_authenticated_user),
):
    if isinstance(user, RedirectResponse):
        return user

    session = getattr(request.state, "session", None)
    cfg = get_auth_settings()
    raw = getattr(request.state, "csrf_raw", "")
    if not validate_csrf(csrf_token, session.id if session else 0, raw, secret=cfg.S9K_CSRF_SECRET):
        raise HTTPException(status_code=403, detail="CSRF inválido")

    # Cadena vacía (o solo espacios) = "volver a la capa juego", nunca una
    # partida llamada "". Semántica explícita, igual que en M4.
    chosen = partida_id.strip() or None
    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        if chosen is not None:
            if not user.is_admin():
                allowed = auth_db.user_allowed_partidas(conn, user.id)
                if chosen not in allowed:
                    raise HTTPException(
                        status_code=403,
                        detail="No tienes asignada esa partida.",
                    )
            elif not auth_db.partida_exists(conn, chosen):
                # El admin ve todo igualmente (admin_full), pero fijar una
                # partida inexistente solo puede ser un error: se rechaza para
                # que no quede estado sin sentido en la sesión.
                raise HTTPException(
                    status_code=400,
                    detail="Esa partida no existe.",
                )
        if session is not None:
            auth_db.set_session_active_partida(conn, session.id, chosen)
        audit.log(
            conn, audit.PARTIDA_SELECTED, "success",
            user_id=user.id, username_snapshot=user.username,
            metadata={"partida_id": chosen},
        )

    return RedirectResponse(url=_safe_next(next), status_code=302)
