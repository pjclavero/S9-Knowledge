"""Validaciones de seguridad *fail-closed* para producción con auth activada.

Cuando ``S9K_AUTH_ENABLED=true`` el arranque debe abortar si la configuración
no es segura: secreto CSRF por defecto/débil o backend de contraseñas no apto.
No se generan secretos silenciosamente ni se hace fallback silencioso.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
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


# Códigos ESTABLES de problema de seguridad de arranque. Forman parte del
# contrato: una prueba que sostenga la garantía «fail-closed de arranque»
# comprueba el CÓDIGO, nunca la redacción del mensaje (que puede cambiar).
CSRF_SECRET_EMPTY = "CSRF_SECRET_EMPTY"
CSRF_SECRET_DEFAULT = "CSRF_SECRET_DEFAULT"
CSRF_SECRET_TOO_SHORT = "CSRF_SECRET_TOO_SHORT"
CSRF_SECRET_LOW_ENTROPY = "CSRF_SECRET_LOW_ENTROPY"
PASSWORD_BACKEND_NOT_ALLOWED = "PASSWORD_BACKEND_NOT_ALLOWED"
AUTH_DB_PATH_EMPTY = "AUTH_DB_PATH_EMPTY"
AUTH_DB_PATH_NOT_ABSOLUTE = "AUTH_DB_PATH_NOT_ABSOLUTE"
AUTH_DB_PATH_MISSING = "AUTH_DB_PATH_MISSING"


@dataclass(frozen=True)
class SecurityProblem:
    """Problema de configuración con CÓDIGO estable + mensaje humano.

    ``__str__`` devuelve el mensaje para no romper a quien lo registre o lo
    concatene; la garantía se comprueba por ``code``.
    """

    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class AuthSecurityError(RuntimeError):
    """Configuración de auth insegura: el arranque debe abortar.

    Lleva ``codes`` (tupla de códigos estables) además del texto: las pruebas
    que sostienen la garantía comprueban tipo + código, no redacción.
    """

    def __init__(self, message: str, problems: "List[SecurityProblem]" | None = None):
        super().__init__(message)
        self.problems: List[SecurityProblem] = list(problems or [])
        self.codes: tuple = tuple(p.code for p in self.problems)


def validate_csrf_secret(secret: str) -> List[SecurityProblem]:
    """Devuelve la lista de problemas del secreto CSRF (vacía si es válido).

    Longitud mínima y entropía mínima son propiedades INDEPENDIENTES: cada una
    tiene su propio código y se evalúa por separado, para que una no pueda
    prestarle el rojo a la otra.
    """
    problems: List[SecurityProblem] = []
    value = (secret or "").strip()
    if not value:
        problems.append(SecurityProblem(CSRF_SECRET_EMPTY, "secreto CSRF vacío"))
        return problems
    if value in _DEFAULT_CSRF_SECRETS:
        problems.append(SecurityProblem(
            CSRF_SECRET_DEFAULT,
            "secreto CSRF por defecto (debe cambiarse en producción)"))
        return problems
    if len(value) < _MIN_CSRF_SECRET_LEN:
        problems.append(SecurityProblem(
            CSRF_SECRET_TOO_SHORT,
            "secreto CSRF demasiado corto (%d < %d)" % (len(value), _MIN_CSRF_SECRET_LEN)))
    if len(set(value)) < _MIN_CSRF_UNIQUE_CHARS:
        problems.append(SecurityProblem(
            CSRF_SECRET_LOW_ENTROPY,
            "secreto CSRF con entropía insuficiente (%d caracteres distintos < %d)"
            % (len(set(value)), _MIN_CSRF_UNIQUE_CHARS)))
    return problems


def validate_password_backend() -> List[SecurityProblem]:
    """Devuelve problemas del backend de contraseñas activo (vacía si es apto)."""
    backend = get_backend()
    if backend not in _ALLOWED_PASSWORD_BACKENDS:
        return [SecurityProblem(
            PASSWORD_BACKEND_NOT_ALLOWED,
            "backend de contraseñas no permitido en producción: %r "
            "(instale argon2-cffi o bcrypt)" % backend)]
    return []


def validate_auth_db_path(raw_path: str) -> List[SecurityProblem]:
    """Devuelve problemas de la ruta de la auth DB (vacía si es válida).

    Con auth activa NO se admite una ruta relativa (dependería del cwd del
    proceso y podría resolver a otra base según quién arranque) ni una base
    inexistente (el visor no debe crearla en silencio: la creación legítima es
    la CLI de provisión).
    """
    from pathlib import Path

    problems: List[SecurityProblem] = []
    if not raw_path:
        problems.append(SecurityProblem(AUTH_DB_PATH_EMPTY, "S9K_AUTH_DB_PATH vacío"))
        return problems
    p = Path(raw_path)
    if not p.is_absolute():
        problems.append(SecurityProblem(
            AUTH_DB_PATH_NOT_ABSOLUTE,
            "S9K_AUTH_DB_PATH debe ser una ruta absoluta con auth activa "
            "(valor relativo detectado)"))
        return problems
    if not p.exists():
        problems.append(SecurityProblem(
            AUTH_DB_PATH_MISSING,
            "la auth DB no existe en S9K_AUTH_DB_PATH; el visor no la crea "
            "automáticamente (provisiónela con la CLI: create-admin)"))
    return problems


def enforce_auth_security(cfg: AuthSettings) -> None:
    """Aborta el arranque si la configuración de auth activa es insegura.

    No-op cuando ``S9K_AUTH_ENABLED=false``.
    """
    if not cfg.S9K_AUTH_ENABLED:
        return

    problems: List[SecurityProblem] = []
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
            log.error("Configuración de auth insegura: [%s] %s", p.code, p.message)
        raise AuthSecurityError(
            "Arranque abortado por configuración de auth insegura: "
            + "; ".join(p.message for p in problems),
            problems,
        )
