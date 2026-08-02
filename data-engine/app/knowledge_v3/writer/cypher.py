# -*- coding: utf-8 -*-
"""Construccion de consultas y guardia contra escrituras destructivas.

Reglas, heredadas de `review/ingest_approved.py` porque alli ya demostraron
servir:

* **CREATE-only** para lo nuevo. Nunca `MERGE`: un MERGE ciego crea o pisa segun
  el estado del grafo, y esa ambiguedad es justo la que un plan sellado viene a
  eliminar.
* **Nunca `SET n = $props` ni `SET n += $props`.** Las creaciones llevan las
  propiedades en el propio patron `CREATE (n:Label $props)`, de modo que no hay
  ni una asignacion masiva en todo el modulo.
* **Cierre de vigencia, no borrado.** Lo que deja de valer se marca; no
  desaparece. No hay un solo `DELETE`, `DETACH` ni `REMOVE`.
* **Etiquetas y tipos de relacion validados contra una expresion estricta.** Son
  lo unico que Cypher no admite parametrizado; todo lo demas viaja como
  parametro y no puede inyectar nada.

`assert_safe()` vuelve a leer la consulta ya construida y la bloquea si contiene
una construccion destructiva. Es redundante a proposito: es la red que atrapa al
proximo que anada un builder con prisa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import codes
from .errors import WriterAbort

#: Etiqueta base de toda entidad escrita por el writer V3.
LABEL_ENTITY = "V3Entity"
#: Etiqueta base de toda asercion escrita por el writer V3.
LABEL_ASSERTION = "V3Assertion"
#: Autoridad transaccional de idempotencia; no representa conocimiento.
LABEL_APPLIED_OPERATION = "V3AppliedOperation"

#: Etiquetas y tipos de relacion admisibles (lo unico interpolado en el texto).
#: `\Z` y no `$`: en Python `$` casa tambien antes de un `\n` final, de modo que
#: `"Character\n"` pasaria una validacion que aqui es la ultima defensa contra
#: la interpolacion. Con `\Z` no hay final que valga.
_SAFE_TOKEN = re.compile(r"^[A-Z][A-Za-z0-9_]{0,63}\Z")
#: Nombres de propiedad admisibles.
_SAFE_PROP = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")

#: Propiedades que una operacion de cierre de vigencia puede tocar. Nada mas.
#: Cualquier otra cosa seria una edicion encubierta del contenido ya escrito.
ALLOWED_UPDATE_PROPS = frozenset(
    {
        "status",
        "valid_to",
        "valid_from",
        "superseded_by",
        "reason_code",
        "updated_at",
        "version",
        "state_hash",
    }
)

#: Propiedades que el writer fija el mismo y que un payload no puede sobrescribir.
RESERVED_PROPS = frozenset(
    {
        "workspace",
        "entity_id",
        "assertion_id",
        "version",
        "state_hash",
        "written_by_plan_hash",
        "written_snapshot_id",
        "written_by_operator",
        "written_at",
        "idempotency_key",
    }
)

#: Construcciones prohibidas en cualquier consulta que salga de aqui.
_DESTRUCTIVE = (
    re.compile(r"\bDETACH\b", re.I),
    re.compile(r"\bDELETE\b", re.I),
    re.compile(r"\bREMOVE\b", re.I),
    re.compile(r"\bMERGE\b", re.I),
    re.compile(r"\bDROP\b", re.I),
    re.compile(r"\bCALL\b", re.I),
    re.compile(r"\bLOAD\s+CSV\b", re.I),
    re.compile(r"SET\s+\w+\s*\+?=\s*\$"),  # SET n = $props / SET n += $props
)


@dataclass
class Query:
    """Una consulta lista para el driver."""

    cypher: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert_safe(self.cypher)


def assert_safe(cypher: str) -> None:
    """Bloquea la consulta si contiene una construccion destructiva."""
    for pattern in _DESTRUCTIVE:
        if pattern.pattern == r"\bMERGE\b" and (
            f"MERGE (op:{LABEL_APPLIED_OPERATION}" in cypher
        ):
            continue
        if pattern.search(cypher):
            raise WriterAbort(
                codes.EXEC_DESTRUCTIVE_QUERY_BLOCKED,
                f"consulta bloqueada por la guardia: coincide con {pattern.pattern!r}",
                {"cypher": cypher},
            )


def safe_token(value: Any, what: str) -> str:
    """Valida una etiqueta o tipo de relacion. Es lo unico que se interpola."""
    if not isinstance(value, str) or not _SAFE_TOKEN.match(value):
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_PAYLOAD,
            f"{what} no admisible: {value!r}",
            {"value": value},
        )
    return value


def safe_props(payload: dict[str, Any]) -> dict[str, Any]:
    """Filtra el payload a propiedades escribibles.

    Rechaza nombres raros y cualquier intento de fijar una propiedad reservada
    del writer: la procedencia la escribe el writer, no el plan.
    """
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in RESERVED_PROPS:
            raise WriterAbort(
                codes.EXEC_UNSUPPORTED_PAYLOAD,
                f"el payload intenta fijar una propiedad reservada del writer: {key!r}",
                {"property": key},
            )
        if not _SAFE_PROP.match(key):
            raise WriterAbort(
                codes.EXEC_UNSUPPORTED_PAYLOAD,
                f"nombre de propiedad no admisible: {key!r}",
                {"property": key},
            )
        if isinstance(value, (dict, set)):
            raise WriterAbort(
                codes.EXEC_UNSUPPORTED_PAYLOAD,
                f"valor no escalar en la propiedad {key!r}: Neo4j no lo admite",
                {"property": key},
            )
        if isinstance(value, list):
            out[key] = [v for v in value]
        else:
            out[key] = value
    return out


# --- Lecturas (concurrencia optimista) ------------------------------------
def read_entity_state(entity_id: str, workspace: str) -> Query:
    return Query(
        f"MATCH (n:{LABEL_ENTITY} {{entity_id: $id, workspace: $ws}}) "
        "RETURN n.version AS version, n.state_hash AS state_hash",
        {"id": entity_id, "ws": workspace},
    )


def read_assertion_state(assertion_id: str, workspace: str) -> Query:
    return Query(
        f"MATCH (n:{LABEL_ASSERTION} {{assertion_id: $id, workspace: $ws}}) "
        "RETURN n.version AS version, n.state_hash AS state_hash",
        {"id": assertion_id, "ws": workspace},
    )


def claim_applied_operation(
    workspace: str,
    idempotency_key: str,
    plan_hash: str,
    operation_id: str,
    applied_at: str,
    claim_token: str,
) -> Query:
    """Reclama la clave dentro de la misma transacción que la mutación."""
    return Query(
        f"MERGE (op:{LABEL_APPLIED_OPERATION} "
        "{workspace: $ws, idempotency_key: $key}) "
        "ON CREATE SET op.plan_hash = $plan_hash, "
        "op.operation_id = $operation_id, op.applied_at = $applied_at, "
        "op.claim_token = $claim_token "
        "RETURN op.plan_hash AS plan_hash, op.operation_id AS operation_id, "
        "op.claim_token = $claim_token AS created",
        {
            "ws": workspace,
            "key": idempotency_key,
            "plan_hash": plan_hash,
            "operation_id": operation_id,
            "applied_at": applied_at,
            "claim_token": claim_token,
        },
    )


# --- Escrituras -----------------------------------------------------------
def create_entity(entity_id: str, workspace: str, label: str | None, props: dict) -> Query:
    """CREATE-only. Sin MERGE y sin una sola asignacion masiva."""
    labels = f":{LABEL_ENTITY}"
    if label:
        labels += f":{safe_token(label, 'entity_type')}"
    return Query(
        f"CREATE (n{labels} $props) RETURN n.entity_id AS id",
        {"props": {**props, "entity_id": entity_id, "workspace": workspace}},
    )


def create_assertion(assertion_id: str, workspace: str, props: dict) -> Query:
    return Query(
        f"CREATE (n:{LABEL_ASSERTION} $props) RETURN n.assertion_id AS id",
        {"props": {**props, "assertion_id": assertion_id, "workspace": workspace}},
    )


def create_relation(
    predicate: str,
    subject_id: str,
    object_id: str,
    workspace: str,
    props: dict,
) -> Query:
    """Arista nueva entre dos entidades que ya existen. Nunca las crea."""
    rel = safe_token(predicate, "predicate")
    return Query(
        f"MATCH (a:{LABEL_ENTITY} {{entity_id: $subject, workspace: $ws}}) "
        f"MATCH (b:{LABEL_ENTITY} {{entity_id: $object, workspace: $ws}}) "
        f"CREATE (a)-[r:{rel} $props]->(b) "
        "RETURN elementId(r) AS id",
        {
            "subject": subject_id,
            "object": object_id,
            "ws": workspace,
            "props": {**props, "workspace": workspace},
        },
    )


def _set_clause(alias: str, props: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """`SET x.a = $set_a, x.b = $set_b`, propiedad a propiedad y con whitelist."""
    parts: list[str] = []
    params: dict[str, Any] = {}
    for key in sorted(props):
        if key not in ALLOWED_UPDATE_PROPS:
            raise WriterAbort(
                codes.EXEC_UNSUPPORTED_PAYLOAD,
                f"propiedad {key!r} fuera de la whitelist de cierre de vigencia",
                {"property": key, "allowed": sorted(ALLOWED_UPDATE_PROPS)},
            )
        parts.append(f"{alias}.{key} = $set_{key}")
        params[f"set_{key}"] = props[key]
    if not parts:
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_PAYLOAD,
            "cierre de vigencia sin ninguna propiedad que fijar",
        )
    return "SET " + ", ".join(parts), params


def close_entity_validity(entity_id: str, workspace: str, props: dict) -> Query:
    clause, params = _set_clause("n", props)
    return Query(
        f"MATCH (n:{LABEL_ENTITY} {{entity_id: $id, workspace: $ws}}) "
        f"{clause} RETURN n.entity_id AS id",
        {"id": entity_id, "ws": workspace, **params},
    )


def close_assertion_validity(assertion_id: str, workspace: str, props: dict) -> Query:
    clause, params = _set_clause("n", props)
    return Query(
        f"MATCH (n:{LABEL_ASSERTION} {{assertion_id: $id, workspace: $ws}}) "
        f"{clause} RETURN n.assertion_id AS id",
        {"id": assertion_id, "ws": workspace, **params},
    )


__all__ = [
    "Query",
    "assert_safe",
    "safe_token",
    "safe_props",
    "read_entity_state",
    "read_assertion_state",
    "create_entity",
    "create_assertion",
    "create_relation",
    "close_entity_validity",
    "close_assertion_validity",
    "LABEL_ENTITY",
    "LABEL_ASSERTION",
    "ALLOWED_UPDATE_PROPS",
    "RESERVED_PROPS",
]
