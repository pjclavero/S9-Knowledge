"""Hashing y verificación segura de contraseñas con Argon2id (o bcrypt como fallback).

Orden de preferencia:
1. argon2-cffi  → Argon2id (recomendado para producción)
2. bcrypt        → bcrypt con work factor 12
3. hashlib.pbkdf2_hmac → PBKDF2-SHA256 (solo para desarrollo/tests; NO para producción)
"""
from __future__ import annotations

import hmac

_BACKEND: str = "none"

try:
    from argon2 import PasswordHasher as _ArgonHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    _ph = _ArgonHasher()
    _BACKEND = "argon2id"

    def hash_password(password: str) -> str:
        """Devuelve hash Argon2id de la contraseña."""
        return _ph.hash(password)

    def verify_password(password: str, password_hash: str) -> bool:
        """Verifica contraseña con comparación en tiempo constante."""
        try:
            return _ph.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(password_hash: str) -> bool:
        """True si el hash usa parámetros desactualizados."""
        return _ph.check_needs_rehash(password_hash)

except ImportError:
    try:
        import bcrypt as _bcrypt

        _BACKEND = "bcrypt"

        def hash_password(password: str) -> str:
            return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode()

        def verify_password(password: str, password_hash: str) -> bool:
            try:
                pw = password.encode("utf-8")
                ph = password_hash.encode("utf-8")
                return bool(_bcrypt.checkpw(pw, ph))
            except Exception:
                return False

        def needs_rehash(password_hash: str) -> bool:  # type: ignore[misc]
            return False

    except ImportError:
        # Fallback PBKDF2 — solo para entornos de desarrollo/CI sin argon2/bcrypt.
        # En producción se DEBE instalar argon2-cffi.
        import hashlib
        import os
        import base64

        _BACKEND = "pbkdf2-sha256-dev"

        _PBKDF2_ITERATIONS = 260_000
        _PBKDF2_PREFIX = "$pbkdf2-sha256$"

        def hash_password(password: str) -> str:  # type: ignore[misc]
            salt = os.urandom(16)
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
            )
            salt_b64 = base64.b64encode(salt).decode()
            dk_b64 = base64.b64encode(dk).decode()
            return f"{_PBKDF2_PREFIX}i={_PBKDF2_ITERATIONS},s={salt_b64},h={dk_b64}"

        def verify_password(password: str, password_hash: str) -> bool:  # type: ignore[misc]
            try:
                if not password_hash.startswith(_PBKDF2_PREFIX):
                    return False
                rest = password_hash[len(_PBKDF2_PREFIX):]
                parts = dict(p.split("=", 1) for p in rest.split(","))
                iterations = int(parts["i"])
                salt = base64.b64decode(parts["s"])
                expected_dk = base64.b64decode(parts["h"])
                dk = hashlib.pbkdf2_hmac(
                    "sha256", password.encode("utf-8"), salt, iterations
                )
                return hmac.compare_digest(dk, expected_dk)
            except Exception:
                return False

        def needs_rehash(password_hash: str) -> bool:  # type: ignore[misc]
            return False


def get_backend() -> str:
    return _BACKEND


# ---------------------------------------------------------------------------
# Validación de contraseña
# ---------------------------------------------------------------------------

MIN_LENGTH = 12


def validate_password(password: str, username: str) -> list[str]:
    """Devuelve lista de errores (vacía si la contraseña es válida)."""
    errors: list[str] = []
    if len(password) < MIN_LENGTH:
        errors.append(f"La contraseña debe tener al menos {MIN_LENGTH} caracteres.")
    if password.lower() == username.lower():
        errors.append("La contraseña no puede ser igual al nombre de usuario.")
    return errors


def safe_compare(a: str, b: str) -> bool:
    """Comparación en tiempo constante."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
