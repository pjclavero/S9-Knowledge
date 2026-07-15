# -*- coding: utf-8 -*-
"""Registro y configuración de proveedores externos (solo por entorno)."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

from external_ai.errors import ConfigError


def is_nvidia_enabled() -> bool:
    return os.environ.get("S9K_NVIDIA_ENABLED", "false").strip().lower() == "true"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def nvidia_config() -> dict:
    """Config NVIDIA desde entorno. No expone la API key (solo indica si existe)."""
    return {
        "base_url": _env("S9K_NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "api_key_present": bool(_env("S9K_NVIDIA_API_KEY")),
        "review_models": [m for m in _env("S9K_NVIDIA_REVIEW_MODELS").split(",") if m.strip()],
        "adjudicator_model": _env("S9K_NVIDIA_ADJUDICATOR_MODEL") or None,
        "timeout_seconds": int(_env("S9K_NVIDIA_TIMEOUT_SECONDS", "180") or "180"),
        "max_retries": int(_env("S9K_NVIDIA_MAX_RETRIES", "3") or "3"),
        "max_concurrency": int(_env("S9K_NVIDIA_MAX_CONCURRENCY", "2") or "2"),
        "cache_enabled": _env("S9K_NVIDIA_CACHE_ENABLED", "true").lower() != "false",
    }


def get_api_key() -> str:
    """Devuelve la API key desde entorno. Nunca se registra ni se serializa."""
    key = os.environ.get("S9K_NVIDIA_API_KEY", "").strip()
    if not key:
        raise ConfigError("S9K_NVIDIA_API_KEY ausente en el entorno")
    return key


def get_provider(name: str, repo_root: Path):
    """Construye un proveedor por nombre. Import perezoso para no acoplar módulos."""
    name = (name or "").lower()
    if name in ("nvidia", "nvidia_nim", "nim"):
        from external_ai.nvidia_nim import NvidiaNimProvider
        return NvidiaNimProvider(repo_root=repo_root)
    raise ConfigError(f"Proveedor externo desconocido: '{name}'")


def review_models() -> list:
    return nvidia_config()["review_models"]


def adjudicator_model() -> Optional[str]:
    return nvidia_config()["adjudicator_model"]
