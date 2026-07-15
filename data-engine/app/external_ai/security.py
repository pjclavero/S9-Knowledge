# -*- coding: utf-8 -*-
"""Guardas de seguridad para IA externa: detección de secretos y sanitización.

Reutiliza la sanitización existente (review.export_import.sanitize_object) y añade
un detector de credenciales que BLOQUEA el envío si encuentra secretos. Solo se
registran hashes y tamaños, nunca el contenido de la clave.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any

from external_ai.errors import SecretLeakError

# Patrones habituales de credenciales (incluye NVIDIA nvapi-...).
_SECRET_PATTERNS = [
    re.compile(r"nvapi-[A-Za-z0-9_\-]{16,}"),          # NVIDIA NIM
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                # OpenAI-style
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),         # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),                   # AWS
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),  # Authorization: Bearer
    re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----"),  # PEM
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][^'\"]{8,}"),
]


def allow_private_content() -> bool:
    return os.environ.get("S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT", "false").strip().lower() == "true"


def find_secrets(obj: Any) -> list:
    """Devuelve una lista de patrones detectados (nombre del patrón), sin exponer el valor."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    found = []
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            found.append(pat.pattern[:24])
    return found


def assert_no_secrets(obj: Any) -> None:
    """Lanza SecretLeakError si el payload contiene credenciales. Se llama ANTES de enviar."""
    hits = find_secrets(obj)
    if hits:
        raise SecretLeakError(f"payload contiene posibles secretos ({len(hits)} patrón/es); envío bloqueado")


def sanitize_request(obj: dict, repo_root=None) -> dict:
    """Sanitiza un payload reutilizando review.export_import.sanitize_object."""
    try:
        from review.export_import import sanitize_object
        return sanitize_object(obj)
    except Exception:
        # Sin la sanitización del repo no se envía nada.
        raise SecretLeakError("sanitize_object no disponible; envío bloqueado por seguridad")
