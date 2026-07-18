"""Hashes canonicos y deterministas para los documentos v1.

Un hash canonico no depende del orden de las claves ni del espaciado del JSON:
se serializa con claves ordenadas y separadores compactos antes de sha256. Esto
permite el control optimista (expected_candidate_hash) y planes deterministas.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

_ALGO = "sha256"


def canonical_json(obj: Any) -> str:
    """Serializacion canonica y estable de ``obj`` (claves ordenadas, compacta)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(obj: Any) -> str:
    """sha256 hexadecimal (64 hex) de la forma canonica de ``obj``."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def hash_block(obj: Any) -> dict[str, str]:
    """Bloque hash del contrato: ``{"algorithm": "sha256", "value": <64hex>}``."""
    return {"algorithm": _ALGO, "value": sha256_hex(obj)}


def short_id(prefix: str, *parts: Any) -> str:
    """ID estable derivado de ``parts`` (compatible con el patron stable_id)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


__all__ = ["canonical_json", "sha256_hex", "hash_block", "short_id"]
