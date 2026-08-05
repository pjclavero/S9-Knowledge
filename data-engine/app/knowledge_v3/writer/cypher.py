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
#: M3: `partida_id` se une a `workspace` -- el ambito lo estampa el writer
#: desde el `SignedView`, nunca el payload (docs/v3/49 §2.4).
RESERVED_PROPS = frozenset(
    {
        "workspace",
        "partida_id",
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


# --- Ambito (M3: docs/v3/49 §2.4) ------------------------------------------
#: Neo4j no compara `= null` como verdadero (siempre `NULL`, nunca `true`):
#: por eso el filtrado de capa juego (`partida_id IS NULL`) va en `WHERE`,
#: nunca en el patron de mapa `{partida_id: $valor}`. Disciplina del diseno:
#: el filtrado de ambito vive en Cypher, jamas en Python.
def _scoped_match(
    label: str, id_field: str, id_value: str, workspace: str, partida_id: str | None,
    *, alias: str = "n",
) -> tuple[str, dict[str, Any]]:
    """MATCH exacto de un nodo en SU propio ambito declarado.

    `partida_id=None` exige capa juego (`IS NULL`); `partida_id="partida:Y"`
    exige esa partida exacta. Nunca un comodin: esto es la precondicion de
    una operacion sobre un objetivo concreto, no una vista de visibilidad.
    """
    params: dict[str, Any] = {"id": id_value, "ws": workspace}
    if partida_id is None:
        pattern = (
            f"MATCH ({alias}:{label} {{{id_field}: $id, workspace: $ws}}) "
            f"WHERE {alias}.partida_id IS NULL"
        )
    else:
        params["partida_id"] = partida_id
        pattern = (
            f"MATCH ({alias}:{label} "
            f"{{{id_field}: $id, workspace: $ws, partida_id: $partida_id}})"
        )
    return pattern, params


def _visible_predicate(alias: str, partida_id: str | None) -> str:
    """Predicado de VISIBILIDAD (capa juego + partida propia), no de identidad.

    Se usa para los extremos de una relacion: un plan de partida Y puede
    enlazar tanto entidades de capa juego como de su propia partida (M2,
    misma direccion unica del Invariante 1), nunca de otra partida.
    """
    if partida_id is None:
        return f"{alias}.partida_id IS NULL"
    return f"({alias}.partida_id IS NULL OR {alias}.partida_id = $partida_id)"


# --- Lecturas (concurrencia optimista) ------------------------------------
def read_entity_state(entity_id: str, workspace: str, partida_id: str | None = None) -> Query:
    pattern, params = _scoped_match(LABEL_ENTITY, "entity_id", entity_id, workspace, partida_id)
    return Query(
        f"{pattern} RETURN n.version AS version, n.state_hash AS state_hash",
        params,
    )


def read_assertion_state(
    assertion_id: str, workspace: str, partida_id: str | None = None
) -> Query:
    pattern, params = _scoped_match(
        LABEL_ASSERTION, "assertion_id", assertion_id, workspace, partida_id
    )
    return Query(
        f"{pattern} RETURN n.version AS version, n.state_hash AS state_hash",
        params,
    )


def read_entity_state_any_scope(entity_id: str, workspace: str) -> Query:
    """Existencia SIN filtro de ambito: solo para diagnosticar un drift.

    No se usa para decidir si una operacion se aplica -- eso siempre pasa por
    la lectura acotada de arriba. Sirve unicamente para distinguir, cuando la
    lectura acotada no encuentra nada, "no existe" de "existe en otra
    partida" (`EXEC_TARGET_MISSING` vs `EXEC_SCOPE_MISMATCH`).
    """
    return Query(
        f"MATCH (n:{LABEL_ENTITY} {{entity_id: $id, workspace: $ws}}) "
        "RETURN n.version AS version, n.state_hash AS state_hash",
        {"id": entity_id, "ws": workspace},
    )


def read_assertion_state_any_scope(assertion_id: str, workspace: str) -> Query:
    """Gemela de `read_entity_state_any_scope` para aserciones."""
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
def create_entity(
    entity_id: str,
    workspace: str,
    label: str | None,
    props: dict,
    partida_id: str | None = None,
) -> Query:
    """CREATE-only. Sin MERGE y sin una sola asignacion masiva.

    `partida_id=None` no escribe la propiedad (Neo4j omite claves con valor
    `null` en un `CREATE (n $props)`): un nodo de capa juego queda EXACTAMENTE
    igual que antes de M3, sin la propiedad presente en absoluto.
    """
    labels = f":{LABEL_ENTITY}"
    if label:
        labels += f":{safe_token(label, 'entity_type')}"
    return Query(
        f"CREATE (n{labels} $props) RETURN n.entity_id AS id",
        {
            "props": {
                **props,
                "entity_id": entity_id,
                "workspace": workspace,
                "partida_id": partida_id,
            }
        },
    )


def create_assertion(
    assertion_id: str, workspace: str, props: dict, partida_id: str | None = None
) -> Query:
    return Query(
        f"CREATE (n:{LABEL_ASSERTION} $props) RETURN n.assertion_id AS id",
        {
            "props": {
                **props,
                "assertion_id": assertion_id,
                "workspace": workspace,
                "partida_id": partida_id,
            }
        },
    )


def create_relation(
    predicate: str,
    subject_id: str,
    object_id: str,
    workspace: str,
    props: dict,
    partida_id: str | None = None,
) -> Query:
    """Arista nueva entre dos entidades que ya existen. Nunca las crea.

    Los extremos se exigen VISIBLES desde el ambito del plan (capa juego +
    la propia partida, nunca otra) -- mismo criterio de direccion unica que
    el resolutor (M2): un plan de capa juego solo enlaza capa juego; un plan
    de partida Y enlaza capa juego o su propia partida.
    """
    rel = safe_token(predicate, "predicate")
    params: dict[str, Any] = {
        "subject": subject_id,
        "object": object_id,
        "ws": workspace,
        "props": {**props, "workspace": workspace, "partida_id": partida_id},
    }
    if partida_id is not None:
        params["partida_id"] = partida_id
    where = f"WHERE {_visible_predicate('a', partida_id)} AND {_visible_predicate('b', partida_id)}"
    return Query(
        f"MATCH (a:{LABEL_ENTITY} {{entity_id: $subject, workspace: $ws}}) "
        f"MATCH (b:{LABEL_ENTITY} {{entity_id: $object, workspace: $ws}}) "
        f"{where} "
        f"CREATE (a)-[r:{rel} $props]->(b) "
        "RETURN elementId(r) AS id",
        params,
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


def close_entity_validity(
    entity_id: str, workspace: str, props: dict, partida_id: str | None = None
) -> Query:
    clause, params = _set_clause("n", props)
    pattern, match_params = _scoped_match(LABEL_ENTITY, "entity_id", entity_id, workspace, partida_id)
    return Query(
        f"{pattern} {clause} RETURN n.entity_id AS id",
        {**match_params, **params},
    )


def close_assertion_validity(
    assertion_id: str, workspace: str, props: dict, partida_id: str | None = None
) -> Query:
    clause, params = _set_clause("n", props)
    pattern, match_params = _scoped_match(
        LABEL_ASSERTION, "assertion_id", assertion_id, workspace, partida_id
    )
    return Query(
        f"{pattern} {clause} RETURN n.assertion_id AS id",
        {**match_params, **params},
    )


# --- Lectura con enmascarado de supersesion LOCAL (M4: docs/v3/49 §2.5) ----
def list_visible_assertions_query(
    workspace: str,
    partida_id: str | None,
    *,
    subject_entity_id: str | None = None,
) -> Query:
    """Aserciones VISIBLES desde `partida_id`, con el override de M4 aplicado.

    Visibilidad = capa juego + partida propia (`_visible_predicate`, el mismo
    criterio que ya usan los dos extremos de `create_relation` en M3).
    Enmascarado: una asercion de capa juego se OCULTA de esta lista si, en el
    mismo ambito de lectura, existe una asercion de la PROPIA partida con
    `local_override_of` apuntando a ella. El nodo de capa juego no se toca en
    absoluto: sigue existiendo, intacto, y sigue apareciendo en cualquier
    lectura que no sea la de esa partida (otra partida, o la propia capa
    juego).

    DECISION DE COSTE (explicita, no implicita): el enmascarado se resuelve
    con un `WHERE NOT EXISTS { ... }` correlacionado por fila, en Cypher,
    acotado a `workspace` + `partida_id` -- los mismos dos campos que ya
    indexa `schema.py` para `_scoped_match`. Se descarta la alternativa de
    traer todo el conjunto visible a Python y filtrar ahi (el patron que ya
    usa `PolicyFilteredProvider` en el visor, con su propio comentario de
    coste conocido, `_ALL = 10_000_000`): esa alternativa duplica en Python
    una regla de visibilidad que el propio Cypher ya expresa, y multiplica el
    trafico de red por cada asercion candidata. La subconsulta de esta
    funcion es barata porque el volumen esperado de overrides POR PARTIDA es
    pequeno frente al volumen del ambito (una partida diverge del lore en
    puntos concretos, no en bloque) -- si eso deja de ser cierto, el punto de
    escalar es anadir un indice compuesto sobre
    `(workspace, partida_id, local_override_of)`, no cambiar de sitio el
    filtro.

    No se usa por `execute_plan` ni por `admission.py`: es una lectura de
    solo consulta (ver `writer/reads.py`), no una decision de escritura.
    """
    where = [_visible_predicate("n", partida_id), "n.workspace = $ws"]
    params: dict[str, Any] = {"ws": workspace}
    if subject_entity_id is not None:
        where.append("n.subject_entity_id = $subject")
        params["subject"] = subject_entity_id
    if partida_id is not None:
        # Solo una PARTIDA puede tener declarado un `local_override_of`
        # (Invariante 2, M4): la capa juego (`partida_id=None`) nunca
        # necesita enmascarar nada, y por eso el `NOT EXISTS` solo se anade
        # cuando la lectura es de una partida concreta.
        params["partida_id"] = partida_id
        mask = (
            f"NOT EXISTS {{ MATCH (o:{LABEL_ASSERTION}) WHERE o.workspace = $ws "
            "AND o.partida_id = $partida_id AND o.local_override_of = n.assertion_id }"
        )
        where.append(mask)
    return Query(
        f"MATCH (n:{LABEL_ASSERTION}) WHERE {' AND '.join(where)} "
        "RETURN n.assertion_id AS assertion_id, n AS props "
        "ORDER BY n.assertion_id",
        params,
    )


__all__ = [
    "Query",
    "assert_safe",
    "safe_token",
    "safe_props",
    "read_entity_state",
    "read_assertion_state",
    "read_entity_state_any_scope",
    "read_assertion_state_any_scope",
    "create_entity",
    "create_assertion",
    "create_relation",
    "close_entity_validity",
    "close_assertion_validity",
    "list_visible_assertions_query",
    "LABEL_ENTITY",
    "LABEL_ASSERTION",
    "ALLOWED_UPDATE_PROPS",
    "RESERVED_PROPS",
]
