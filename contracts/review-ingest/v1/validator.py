"""
validator.py — validador ÚNICO de los contratos review/ingest v1.

Fuente compartida por el motor (data-engine) y el visor: ambos importan/leen
este modulo y los .schema.json de este directorio; no se duplican los contratos.

Ofrece:
  - validate_document(doc): valida contra JSON Schema por `document_type` y aplica
    las comprobaciones SEMANTICAS que el JSON Schema no puede expresar (suma de
    conteos, unicidad de IDs, ausencia de secretos, coherencia ready_to_plan).
  - Rechazo de una version MAYOR desconocida (compatibilidad forward).

No escribe en Neo4j ni en SQLite; no tiene efectos secundarios.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA_DIR = Path(__file__).resolve().parent
SUPPORTED_MAJOR = 1

DOC_SCHEMAS = {
    "review-candidate": "review-candidate-v1.schema.json",
    "review-decision": "review-decision-v1.schema.json",
    "review-source-summary": "review-source-summary-v1.schema.json",
    "ingest-plan": "ingest-plan-v1.schema.json",
    "ingest-plan-result": "ingest-plan-result-v1.schema.json",
    "review-audit-event": "review-audit-event-v1.schema.json",
}

_SENSITIVE_KEY = re.compile(r"(password|passwd|secret|token|cookie|api[_-]?key|authorization)", re.IGNORECASE)


class ContractError(ValueError):
    """Documento que incumple el contrato (schema o semantica)."""


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def build_registry() -> Registry:
    resources = []
    for path in SCHEMA_DIR.glob("*.schema.json"):
        doc = _load_json(path.name)
        resources.append((doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


_REGISTRY = build_registry()


def schema_for(document_type: str) -> dict[str, Any]:
    if document_type not in DOC_SCHEMAS:
        raise ContractError(f"document_type desconocido: {document_type!r}")
    return _load_json(DOC_SCHEMAS[document_type])


def _check_major_version(doc: dict[str, Any]) -> None:
    ver = str(doc.get("schema_version", ""))
    m = re.match(r"^(\d+)\.", ver)
    if not m:
        raise ContractError(f"schema_version invalida: {ver!r}")
    if int(m.group(1)) != SUPPORTED_MAJOR:
        raise ContractError(f"version mayor no soportada: {ver} (soporto {SUPPORTED_MAJOR}.x)")


def _find_sensitive(obj: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _SENSITIVE_KEY.search(str(k)):
                hits.append(f"{path}/{k}")
            hits += _find_sensitive(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _find_sensitive(v, f"{path}[{i}]")
    return hits


def _semantic_checks(doc: dict[str, Any]) -> None:
    dt = doc.get("document_type")

    # Nunca almacenar secretos en metadata/atributos.
    for block in ("metadata", "attributes"):
        if isinstance(doc.get(block), dict):
            hits = _find_sensitive(doc[block], block)
            if hits:
                raise ContractError(f"campos sensibles prohibidos en {block}: {hits}")

    if dt == "review-source-summary":
        states = ["pending", "auto_approvable", "approved", "edited", "use_existing",
                  "deferred", "conflicts", "rejected"]
        total = doc["candidates_total"]
        s = sum(doc[k] for k in states)
        if s != total:
            raise ContractError(f"suma de estados ({s}) != candidates_total ({total})")
        if doc["segments_reviewed"] > doc["segments_total"]:
            raise ContractError("segments_reviewed > segments_total")
        must_block = doc["conflicts"] > 0 or doc["pending"] > 0
        if must_block and doc["ready_to_plan"]:
            raise ContractError("ready_to_plan=true con conflictos o pendientes")

    elif dt == "ingest-plan":
        ops = doc["operations"]
        op_ids = [o["operation_id"] for o in ops]
        if len(op_ids) != len(set(op_ids)):
            raise ContractError("operation_id duplicado")
        idem = [o["idempotency_key"] for o in ops]
        if len(idem) != len(set(idem)):
            raise ContractError("idempotency_key duplicada")
        if not doc.get("relations_enabled", False):
            if any(o["operation_type"] in ("CREATE_RELATION", "UPDATE_RELATION") for o in ops):
                raise ContractError("operaciones de relacion con relations_enabled=false")

    elif dt == "ingest-plan-result":
        if doc["mode"] == "DRY_RUN":
            sm = doc["summary"]
            if sm["created"] or sm["rolled_back"]:
                raise ContractError("DRY_RUN no puede tener created/rolled_back > 0")
        if doc["mode"] == "APPLY" and doc["status"] == "PARTIAL":
            if not doc.get("transactional_rollback_demonstrated", False):
                raise ContractError("APPLY PARTIAL sin rollback transaccional demostrado")


def validate_document(doc: dict[str, Any]) -> None:
    """Valida un documento v1. Lanza ContractError si no cumple."""
    if not isinstance(doc, dict):
        raise ContractError("documento no es objeto")
    dt = doc.get("document_type")
    if dt not in DOC_SCHEMAS:
        raise ContractError(f"document_type desconocido o ausente: {dt!r}")
    _check_major_version(doc)
    schema = schema_for(dt)
    validator = jsonschema.Draft202012Validator(schema, registry=_REGISTRY)
    errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
    if errors:
        msgs = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
        raise ContractError(f"schema {dt}: {msgs}")
    _semantic_checks(doc)


def is_valid(doc: dict[str, Any]) -> bool:
    try:
        validate_document(doc)
        return True
    except ContractError:
        return False
