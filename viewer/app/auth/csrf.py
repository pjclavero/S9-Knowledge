"""Tokens CSRF por sesión con verificación hmac.compare_digest."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

_CSRF_SESSION_KEY = "_csrf_token"


def generate_csrf_token() -> str:
    """Genera un token CSRF de 32 bytes en urlsafe base64."""
    return secrets.token_urlsafe(32)


def _derive_token(session_id: int, secret: str, raw_token: str) -> str:
    """HMAC-SHA256 del token vinculado a la sesión."""
    msg = f"{session_id}:{raw_token}".encode("utf-8")
    key = secret.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def get_csrf_token_for_session(
    session_id: int,
    raw_token: str,
    *,
    secret: str = "s9k-csrf-default",
) -> str:
    """
    Devuelve token CSRF derivado para incluir en formularios.
    `raw_token` se almacena en la sesión (en memoria o en la cookie firmada),
    y el derivado HMAC es lo que se pone en el campo hidden.
    """
    return _derive_token(session_id, secret, raw_token)


def validate_csrf(
    submitted_token: Optional[str],
    session_id: int,
    raw_token: str,
    *,
    secret: str = "s9k-csrf-default",
) -> bool:
    """
    Verifica el token CSRF enviado por el formulario.
    Usa hmac.compare_digest para evitar timing attacks.
    """
    if not submitted_token:
        return False
    expected = _derive_token(session_id, secret, raw_token)
    return hmac.compare_digest(submitted_token, expected)
