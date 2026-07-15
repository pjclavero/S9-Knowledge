"""Configuración del subsistema de autenticación del visor."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Activar autenticación (false = comportamiento actual sin cambios)
    S9K_AUTH_ENABLED: bool = False

    # Ruta de la base de datos SQLite de autenticación
    S9K_AUTH_DB_PATH: str = "viewer/state/auth.db"

    # Cookie de sesión
    S9K_SESSION_COOKIE_NAME: str = "s9k_session"
    S9K_SESSION_TTL_HOURS: int = 12
    S9K_SESSION_IDLE_MINUTES: int = 60
    S9K_SESSION_SECURE: bool = True
    S9K_SESSION_SAMESITE: str = "lax"
    S9K_SESSION_HTTPONLY: bool = True

    # Bloqueo por intentos fallidos
    S9K_AUTH_MAX_FAILED_ATTEMPTS: int = 5
    S9K_AUTH_LOCK_MINUTES: int = 15

    # Exponer /docs y /redoc a usuarios autenticados no-admin
    S9K_AUTH_EXPOSE_DOCS: bool = False

    # Confiar en cabeceras de proxy (X-Forwarded-For)
    S9K_AUTH_TRUST_PROXY_HEADERS: bool = False

    # Secreto CSRF (debe configurarse en producción)
    S9K_CSRF_SECRET: str = "s9k-csrf-change-me"


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
