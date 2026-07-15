# -*- coding: utf-8 -*-
"""Cache idempotente por SHA256 para procesamiento externo (Fase B1).

Clave de cache:
    SHA256(source_hash + task_type + chunk_range + provider + model +
           processing_version + parameters)

Reglas:
- Antes de crear un job: buscar resultado previo valido y reutilizarlo.
- Invalidar cuando cambie modelo, prompt o parametros.
- Nunca cachear resultados con errores.
- La cache vive fuera de Git (state/external_processing_cache/).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

_CACHE_ROOT = "state/external_processing_cache"
_PROCESSING_VERSION = "B1.0"


def _enabled() -> bool:
    return os.environ.get("S9K_EXTERNAL_PROCESSING_CACHE_ENABLED", "true").strip().lower() != "false"


def build_cache_key(
    source_hash: str,
    task_type: str,
    chunk_range: str,
    provider: str,
    model: str,
    processing_version: str = _PROCESSING_VERSION,
    parameters: Optional[dict] = None,
) -> str:
    """Construye la clave de cache determinista."""
    params_str = json.dumps(parameters or {}, sort_keys=True)
    raw = "|".join([
        source_hash,
        task_type,
        chunk_range,
        provider,
        model,
        processing_version,
        params_str,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ProcessingCache:
    """Cache local idempotente para resultados de procesamiento externo."""

    def __init__(self, repo_root: Path, enabled: Optional[bool] = None):
        self.root = Path(repo_root) / _CACHE_ROOT
        self.enabled = _enabled() if enabled is None else enabled
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        """Devuelve el resultado cacheado o None si no existe / esta deshabilitada."""
        if not self.enabled:
            return None
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def put(self, key: str, result: dict) -> None:
        """Almacena el resultado con metadatos de tiempo."""
        if not self.enabled:
            return
        entry = {
            "key": key,
            "stored_at": time.time(),
            "processing_version": _PROCESSING_VERSION,
            "result": result,
        }
        try:
            self._path(key).write_text(json.dumps(entry, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError:
            pass

    def exists(self, key: str) -> bool:
        """Indica si existe una entrada valida en cache."""
        if not self.enabled:
            return False
        return self._path(key).exists()

    def invalidate(self, key: str) -> bool:
        """Elimina una entrada de cache. Devuelve True si existia."""
        p = self._path(key)
        if p.exists():
            p.unlink()
            return True
        return False

    def clear_all(self) -> int:
        """Elimina todas las entradas. Solo para tests."""
        count = 0
        if self.root.exists():
            for p in self.root.glob("*.json"):
                p.unlink()
                count += 1
        return count
