"""Configuración del subsistema de autenticación del visor.

**Instalación cerrada de fábrica** (ver `docs/75-autoridad-unica-admin-full.md`
§ supersesión): `S9K_AUTH_ENABLED` es `True` por defecto. Una instalación
nueva que copia `.env.example` a `.env` y arranca sin tocar nada más queda
autenticada; `false` sigue existiendo como *opt-out* explícito para
desarrollo/laboratorio, nunca como el estado al copiar la plantilla.

`S9K_AUTH_DB_PATH` vacío (el valor de la plantilla) se resuelve a una ruta
ABSOLUTA anclada al repo (`<repo>/viewer/state/auth.db`), calculada a partir
de la ubicación de este fichero y no del directorio de trabajo del proceso.
Antes de esto, activar auth por defecto con la ruta relativa histórica habría
abortado el arranque de fábrica con `AUTH_DB_PATH_NOT_ABSOLUTE`: exactamente
el terminal que este corte existe para evitar.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repo root: viewer/app/auth/config.py -> viewer/app/auth -> viewer/app ->
#: viewer -> <repo>. Tres `.parent` desde el fichero.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Ruta absoluta por defecto de la auth DB cuando la plantilla no fija nada.
DEFAULT_AUTH_DB_PATH = str(_REPO_ROOT / "viewer" / "state" / "auth.db")


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Activar autenticación. `true` es el default de PRODUCTO desde el corte
    # "instalación cerrada de fábrica": `false` sigue siendo un opt-out
    # explícito y legítimo (desarrollo/laboratorio), pero deja de ser lo que
    # trae la plantilla.
    S9K_AUTH_ENABLED: bool = True

    # Ruta de la base de datos SQLite de autenticación. Vacío -> se resuelve
    # a `DEFAULT_AUTH_DB_PATH` (ver validador más abajo): la plantilla puede
    # dejarlo en blanco sin que el arranque de fábrica aborte por ruta
    # relativa o vacía.
    S9K_AUTH_DB_PATH: str = DEFAULT_AUTH_DB_PATH

    @model_validator(mode="after")
    def _resolver_ruta_por_defecto(self) -> "AuthSettings":
        if not (self.S9K_AUTH_DB_PATH or "").strip():
            object.__setattr__(self, "S9K_AUTH_DB_PATH", DEFAULT_AUTH_DB_PATH)
        return self

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

    # Secreto CSRF. Vacío (el valor de la plantilla) YA NO aborta el arranque
    # de fábrica: se resuelve mediante bootstrap seguro en disco (ver
    # `get_auth_settings` y `app.auth.csrf_bootstrap`). No hay valor por
    # defecto adivinable aquí a propósito: un secreto fijo en un repo público
    # no es un secreto.
    S9K_CSRF_SECRET: str = ""


@lru_cache
def get_auth_settings() -> AuthSettings:
    cfg = AuthSettings()
    if cfg.S9K_AUTH_ENABLED:
        from app.auth.csrf_bootstrap import resolve_csrf_secret

        resuelto = resolve_csrf_secret(cfg.S9K_CSRF_SECRET, cfg.S9K_AUTH_DB_PATH)
        if resuelto != cfg.S9K_CSRF_SECRET:
            cfg = cfg.model_copy(update={"S9K_CSRF_SECRET": resuelto})
    return cfg
