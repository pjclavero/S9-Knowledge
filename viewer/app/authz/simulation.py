"""Modo admin "ver como personaje": solo lectura y AUDITADO.

Un administrador puede inspeccionar el grafo tal y como lo vería un personaje
jugador concreto (para verificar la política sin filtrar información). Esta
acción:

  - NO concede escritura: se sirve con un ``PolicyFilteredProvider`` cuyo
    contexto tiene ``admin_full=False`` (encarna al personaje).
  - Emite un evento de auditoría ``review-audit-event`` con
    ``event_type = VIEW_AS_CHARACTER``, validado con el validador ÚNICO de
    contratos (``contracts/review-ingest/v1/validator.py``) SIN modificarlo.

El evento NO contiene secretos (password/cookie/token/...): el propio validador
lo rechazaría. Devolvemos el documento; la persistencia append-only es
responsabilidad del llamador (fuera de este slice).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _synthetic_hash(*parts: str) -> dict[str, str]:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return {"algorithm": "sha256", "value": h}


def build_view_as_character_event(
    *,
    workspace: str,
    admin_actor_id: str,
    simulated_character: str,
    event_id: str,
    document_id: Optional[str] = None,
    max_visible_session: Optional[int] = None,
    request_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Construye un evento review-audit-event v1 VIEW_AS_CHARACTER.

    No persiste nada; devuelve el documento listo para validar/almacenar.
    """
    ts = timestamp or _now_iso()
    src_id = f"authz:view-as:{workspace}"
    src_hash = _synthetic_hash(workspace, simulated_character)
    producer = {
        "kind": "POLICY_ENGINE",
        "name": "s9k-viewer-authz",
        "version": "0.1.0",
        "model": None,
    }
    provenance = {
        "source_id": src_id,
        "source_hash": src_hash,
        "review_generation": 0,
        "pipeline_version": "0.1.0",
        "producer": producer,
    }
    # metadata: solo campos NO sensibles (nada de password/cookie/token/...).
    metadata: dict[str, Any] = {
        "action": "view_as_character",
        "simulated_character": simulated_character,
        "read_only": True,
    }
    if max_visible_session is not None:
        metadata["max_visible_session"] = max_visible_session

    return {
        "schema_version": "1.0.0",
        "document_type": "review-audit-event",
        "document_id": document_id or f"view-as-character_{event_id}",
        "created_at": ts,
        "workspace": workspace,
        "source_id": src_id,
        "source_hash": src_hash,
        "review_generation": 0,
        "producer": producer,
        "provenance": provenance,
        "event_id": event_id,
        "event_type": "VIEW_AS_CHARACTER",
        "actor_type": "HUMAN",
        "actor_id": admin_actor_id,
        "timestamp": ts,
        "candidate_id": None,
        "plan_id": None,
        "request_id": request_id,
        "metadata": metadata,
    }
