"""Gestión de sesiones server-side: creación, validación, renovación, expiración."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
from typing import Optional, Tuple

from app.auth import db as auth_db
from app.auth.config import get_auth_settings
from app.auth.models import Session, User


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_ip(ip: Optional[str]) -> Optional[str]:
    if ip is None:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]  # prefijo para no guardar IP completa


def _hash_ua(ua: Optional[str]) -> Optional[str]:
    if ua is None:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Crear sesión
# ---------------------------------------------------------------------------

def create_session(
    conn,
    user: User,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[str, Session]:
    """
    Crea una nueva sesión para el usuario.
    Devuelve (token_en_claro, Session).
    El token en claro se envía en la cookie; NUNCA se guarda en DB.
    """
    cfg = get_auth_settings()
    token = secrets.token_urlsafe(32)
    session_hash = _sha256(token)
    expires_at = (
        _utcnow() + timedelta(hours=cfg.S9K_SESSION_TTL_HOURS)
    ).isoformat()

    session = auth_db.create_session(
        conn,
        user_id=user.id,
        session_hash=session_hash,
        expires_at=expires_at,
        ip_hash=_hash_ip(ip),
        user_agent_hash=_hash_ua(user_agent),
    )
    return token, session


# ---------------------------------------------------------------------------
# Validar sesión a partir de token
# ---------------------------------------------------------------------------

def get_valid_session(
    conn,
    token: str,
    *,
    idle_minutes: Optional[int] = None,
) -> Optional[Tuple[Session, User]]:
    """
    Valida el token de sesión.
    Comprueba: existencia, no revocada, no expirada absolutamente, no inactiva.
    Actualiza last_seen_at si es válida.
    Devuelve (Session, User) o None.
    """
    cfg = get_auth_settings()
    session_hash = _sha256(token)
    session = auth_db.get_session_by_hash(conn, session_hash)
    if session is None:
        return None

    now = _utcnow()

    # Revocada
    if session.revoked_at is not None:
        return None

    # Expiración absoluta
    if now >= session.expires_at:
        auth_db.revoke_session(conn, session.id)
        return None

    # Expiración por inactividad
    idle = idle_minutes if idle_minutes is not None else cfg.S9K_SESSION_IDLE_MINUTES
    if idle > 0:
        idle_deadline = session.last_seen_at + timedelta(minutes=idle)
        if now >= idle_deadline:
            auth_db.revoke_session(conn, session.id)
            return None

    # Actualizar last_seen
    auth_db.update_session_last_seen(conn, session.id)

    # Cargar usuario
    user = auth_db.get_user_by_id(conn, session.user_id)
    if user is None or not user.is_active:
        auth_db.revoke_session(conn, session.id)
        return None

    return session, user


# ---------------------------------------------------------------------------
# Revocar
# ---------------------------------------------------------------------------

def revoke_session_by_token(conn, token: str) -> bool:
    session_hash = _sha256(token)
    session = auth_db.get_session_by_hash(conn, session_hash)
    if session is None:
        return False
    auth_db.revoke_session(conn, session.id)
    return True


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def cookie_kwargs() -> dict:
    cfg = get_auth_settings()
    return {
        "key": cfg.S9K_SESSION_COOKIE_NAME,
        "httponly": cfg.S9K_SESSION_HTTPONLY,
        "secure": cfg.S9K_SESSION_SECURE,
        "samesite": cfg.S9K_SESSION_SAMESITE,
        "max_age": cfg.S9K_SESSION_TTL_HOURS * 3600,
        "path": "/",
    }
