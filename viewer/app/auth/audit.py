"""Eventos de auditoría — append-only, no editables desde UI."""
from __future__ import annotations

import sqlite3
from typing import Optional

from app.auth import db as auth_db

# ---------------------------------------------------------------------------
# Tipos de evento
# ---------------------------------------------------------------------------

LOGIN_SUCCESS = "LOGIN_SUCCESS"
LOGIN_FAILURE = "LOGIN_FAILURE"
ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
LOGOUT = "LOGOUT"
SESSION_EXPIRED = "SESSION_EXPIRED"
PASSWORD_CHANGED = "PASSWORD_CHANGED"
USER_CREATED = "USER_CREATED"
USER_UPDATED = "USER_UPDATED"
USER_DISABLED = "USER_DISABLED"
USER_ENABLED = "USER_ENABLED"
ROLE_CHANGED = "ROLE_CHANGED"
SESSIONS_REVOKED = "SESSIONS_REVOKED"
ACCESS_DENIED = "ACCESS_DENIED"
# Fallo del backend de auth (DB/sesión). Cuando la propia DB está caída no puede
# persistirse; en ese caso el middleware lo registra por logging estructurado.
AUTH_BACKEND_ERROR = "AUTH_BACKEND_ERROR"

ALL_EVENT_TYPES = [
    LOGIN_SUCCESS, LOGIN_FAILURE, ACCOUNT_LOCKED, LOGOUT, SESSION_EXPIRED,
    PASSWORD_CHANGED, USER_CREATED, USER_UPDATED, USER_DISABLED, USER_ENABLED,
    ROLE_CHANGED, SESSIONS_REVOKED, ACCESS_DENIED, AUTH_BACKEND_ERROR,
]

# ---------------------------------------------------------------------------
# Helpers de registro
# ---------------------------------------------------------------------------

def log(
    conn: sqlite3.Connection,
    event_type: str,
    result: str,
    *,
    user_id: Optional[int] = None,
    username_snapshot: Optional[str] = None,
    route: Optional[str] = None,
    method: Optional[str] = None,
    ip_hash: Optional[str] = None,
    user_agent_hash: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Registra un evento de auditoría. Append-only."""
    auth_db.log_audit_event(
        conn,
        event_type=event_type,
        result=result,
        user_id=user_id,
        username_snapshot=username_snapshot,
        route=route,
        method=method,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
        metadata=metadata,
    )
