# -*- coding: utf-8 -*-
"""Caché local de respuestas de IA externa (idempotencia). Ignorada por Git.

NUNCA guarda API keys. La clave es un SHA256 determinista de los factores que
afectan al resultado; si cambia el prompt o el esquema, la caché se invalida.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

_CACHE_DIR_ENV = "S9K_EXTERNAL_AI_CACHE_DIR"
_CACHE_SUBDIR = "external_ai_cache"


def _enabled() -> bool:
    return os.environ.get("S9K_NVIDIA_CACHE_ENABLED", "true").strip().lower() != "false"


def cache_key(provider: str, model: str, prompt_version: str, workspace: str,
              candidate_id: str, segment_hash: str, schema_version: str,
              glossary_snapshot_hash: str) -> str:
    raw = "|".join([
        provider, model, prompt_version, workspace, candidate_id,
        segment_hash, schema_version, glossary_snapshot_hash,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, repo_root: Optional[Path] = None, enabled: Optional[bool] = None,
                 root: Optional[Path] = None):
        # H-06/H-08: la cache es ESTADO, nunca vive en la release. `repo_root` se conserva
        # por compatibilidad de firma y ya no decide la ruta: la decide `root` (explicita),
        # `S9K_EXTERNAL_AI_CACHE_DIR` o el state root efectivo de la autoridad.
        if root is not None:
            self.root = Path(root)
        elif os.environ.get(_CACHE_DIR_ENV, "").strip():
            self.root = Path(os.environ[_CACHE_DIR_ENV].strip())
        else:
            from knowledge_v3 import service_state  # noqa: PLC0415
            self.root = service_state.default_state_path(_CACHE_SUBDIR)
        self.enabled = _enabled() if enabled is None else enabled
        if self.enabled:
            # H-1 (ronda 2): estado privado con el modo EXACTO de la autoridad; root no lo crea.
            from knowledge_v3 import service_state  # noqa: PLC0415
            service_state.ensure_private_dir(self.root)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        if not self.enabled:
            return None
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def put(self, key: str, raw_response: str, normalized: dict, latency_ms: int) -> None:
        if not self.enabled:
            return
        entry = {
            "key": key,
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "latency_ms": latency_ms,
            "raw_response": raw_response,
            "normalized": normalized,
        }
        from knowledge_v3 import service_state  # noqa: PLC0415
        fd = service_state.open_private_write(self._path(key))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, indent=2))
