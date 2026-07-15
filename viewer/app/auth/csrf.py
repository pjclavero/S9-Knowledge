"""Tokens CSRF por sesión con verificación hmac.compare_digest."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

_CSRF_SESSION_KEY = "_csrf_token"

# Cookie que transporta el token CSRF de login (double-submit) antes de existir
# una sesión. El mismo valor firmado va en el campo oculto del formulario.
LOGIN_CSRF_COOKIE = "_s9k_login_csrf"

# Vida del token de login (segundos): un token filtrado no debe ser eterno.
LOGIN_CSRF_MAX_AGE = 3600


def generate_csrf_token() -> str:
    """Genera un token CSRF de 32 bytes en urlsafe base64."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# CSRF de login (stateless, firmado y temporal, ligado al navegador por cookie)
# ---------------------------------------------------------------------------

def _login_sig(secret: str, ts: str, nonce: str) -> str:
    msg = f"login:{ts}:{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def issue_login_csrf(secret: str) -> str:
    """Emite un token de login firmado: ``<ts>.<nonce>.<hmac>``.

    Se coloca simultáneamente en la cookie ``LOGIN_CSRF_COOKIE`` y en el campo
    oculto del formulario. El servidor exige que ambos coincidan (double-submit)
    y que la firma y la caducidad sean válidas.
    """
    ts = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    sig = _login_sig(secret, ts, nonce)
    return f"{ts}.{nonce}.{sig}"


def validate_login_csrf(
    submitted_token: Optional[str],
    cookie_token: Optional[str],
    *,
    secret: str,
    max_age: int = LOGIN_CSRF_MAX_AGE,
    now: Optional[int] = None,
) -> bool:
    """Valida el token CSRF de login.

    Requisitos (todos obligatorios):
    - token presente en formulario y en cookie;
    - ambos idénticos (comparación segura) → ligado al navegador;
    - firma HMAC válida → un token inventado falla;
    - no caducado.
    """
    if not submitted_token or not cookie_token:
        return False
    if not hmac.compare_digest(submitted_token, cookie_token):
        return False
    parts = submitted_token.split(".")
    if len(parts) != 3:
        return False
    ts, nonce, sig = parts
    expected = _login_sig(secret, ts, nonce)
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        issued = int(ts)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if current - issued > max_age or issued - current > 60:
        return False
    return True


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
