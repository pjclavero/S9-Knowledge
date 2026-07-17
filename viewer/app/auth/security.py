"""Validaciones de seguridad *fail-closed* para producción con auth activada.

Cuando ``S9K_AUTH_ENABLED=true`` el arranque debe abortar si la configuración
no es segura: secreto CSRF por defecto/débil o backend de contraseñas no apto.
No se generan secretos silenciosamente ni se hace fallback silencioso.
"""
from __future__ import annotations

import logging
from typing import List

from app.auth.config import AuthSettings
from app.auth.passwords import get_backend

log = logging.getLogger("s9k.auth.security")

# Secretos CSRF prohibidos (valor por defecto del repo y placeholders comunes).
_DEFAULT_CSRF_SECRETS = {
    "",
    "s9k-csrf-change-me",
    "s9k-csrf-default",
    "change-me",
    "changeme",
    "secret",
}

# Longitud mínima recomendada para un token urlsafe de ~24 bytes.
_MIN_CSRF_SECRET_LEN = 32

# Número mínimo de caracteres distintos (proxy de entropía).
_MIN_CSRF_UNIQUE_CHARS = 8

# Backends de hashing permitidos cuando auth está activa.
_ALLOWED_PASSWORD_BACKENDS = {"argon2id", "bcrypt"}


class AuthSecurityError(RuntimeError):
    """Configuración de auth insegura: el arranque debe abortar."""


def validate_csrf_secret(secret: str) -> List[str]:
    """Devuelve la lista de problemas del secreto CSRF (vacía si es válido)."""
    problems: List[str] = []
    value = (secret or "").strip()
    if not value:
        problems.append("secreto CSRF vacío")
        return problems
    if value in _DEFAULT_CSRF_SECRETS:
        problems.append("secreto CSRF por defecto (debe cambiarse en producción)")
        return problems
    if len(value) < _MIN_CSRF_SECRET_LEN:
        problems.append(
            "secreto CSRF demasiado corto (%d < %d)" % (len(value), _MIN_CSRF_SECRET_LEN)
        )
    if len(set(value)) < _MIN_CSRF_UNIQUE_CHARS:
        problems.append("secreto CSRF con entropía insuficiente")
    return problems


def validate_password_backend() -> List[str]:
    """Devuelve problemas del backend de contraseñas activo (vacía si es apto)."""
    backend = get_backend()
    if backend not in _ALLOWED_PASSWORD_BACKENDS:
        return [
            "backend de contraseñas no permitido en producción: %r "
            "(instale argon2-cffi o bcrypt)" % backend
        ]
    return []


def validate_auth_db_path(raw_path: str) -> List[str]:
    """Devuelve problemas de la ruta de la auth DB (vacía si es válida).

    Con auth activa NO se admite una ruta relativa (dependería del cwd del
    proceso y podría resolver a otra base según quién arranque) ni una base
    inexistente (el visor no debe crearla en silencio: la creación legítima es
    la CLI de provisión).
    """
    from pathlib import Path

    problems: List[str] = []
    p = Path(raw_path or "")
    if not str(p):
        problems.append("S9K_AUTH_DB_PATH vacío")
        return problems
    if not p.is_absolute():
        problems.append(
            "S9K_AUTH_DB_PATH debe ser una ruta absoluta con auth activa "
            "(valor relativo detectado)"
        )
        return problems
    if not p.exists():
        problems.append(
            "la auth DB no existe en S9K_AUTH_DB_PATH; el visor no la crea "
            "automáticamente (provisiónela con la CLI: create-admin)"
        )
    return problems


def enforce_auth_security(cfg: AuthSettings) -> None:
    """Aborta el arranque si la configuración de auth activa es insegura.

    No-op cuando ``S9K_AUTH_ENABLED=false``.
    """
    if not cfg.S9K_AUTH_ENABLED:
        return

    problems: List[str] = []
    problems += validate_csrf_secret(cfg.S9K_CSRF_SECRET)
    problems += validate_password_backend()
    problems += validate_auth_db_path(cfg.S9K_AUTH_DB_PATH)

    # Cookies: no debe desactivarse Secure en producción (solo aviso, no aborta,
    # porque un entorno de desarrollo legítimo puede requerir HTTP directo).
    if not cfg.S9K_SESSION_SECURE:
        log.warning(
            "S9K_SESSION_SECURE=false: las cookies de sesión viajarán sin TLS. "
            "En producción debe accederse por HTTPS mediante el reverse proxy."
        )

    if problems:
        # Log sanitizado: NUNCA se registra el valor del secreto, solo el diagnóstico.
        for p in problems:
            log.error("Configuración de auth insegura: %s", p)
        raise AuthSecurityError(
            "Arranque abortado por configuración de auth insegura: " + "; ".join(problems)
        )
