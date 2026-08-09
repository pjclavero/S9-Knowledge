# -*- coding: utf-8 -*-
"""Ejecucion del plan: todo o nada, con concurrencia optimista e idempotencia.

Tres invariantes, y ninguna es negociable:

1. **Transaccional.** Una sola transaccion para el plan entero. Cualquier fallo
   —driver, precondicion, payload— la aborta completa. No existe «se aplicaron
   3 de 5»: un plan a medias deja el grafo en un estado que ningun snapshot
   describe.
2. **Concurrencia optimista.** Cada operacion que toca algo existente comprueba
   `expected_version` y `expected_hash` contra lo que hay AHORA. Un solo
   desajuste aborta el plan entero, no solo esa operacion: si el grafo se movio
   bajo el plan, el resto de operaciones tampoco se calcularon sobre este
   estado.
3. **Idempotencia real.** Una `idempotency_key` ya registrada como aplicada es
   un no-op CONTABILIZADO, y ni siquiera llega al driver. Reaplicar el mismo
   plan no escribe dos veces.

El driver se INYECTA. Este modulo no importa `neo4j`, no lee variables de
conexion y no tiene ninguna URL por defecto.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..ledger.entries import LedgerOperation
from ..ledger.supersession import CANONICAL_REASONS as _LEDGER_CANONICAL_REASONS
from . import codes, cypher
from .admission import declares_local_override
from .errors import WriterAbort
from .idempotency import AppliedKeyStore
from .visibility import SIN_DECLARAR, VisibilityStampError
from .view import SignedView

#: M4 (docs/v3/49 §2.5): catalogo COMPARTIDO con el ledger local -- una sola
#: fuente de verdad para los motivos canonicos de un ASSERT, en vez de
#: duplicar la lista aqui. `LOCAL_DIVERGENCE` es el unico motivo admisible
#: para una operacion que trae `local_override_of`: los otros tres motivos de
#: la misma familia (`INITIAL_ASSERTION`, `NEW_EVIDENCE`,
#: `REINSTATED_AFTER_REVIEW`) describen una asercion CORRIENTE, no una
#: divergencia local, y aceptarlos aqui confundiria las dos cosas.
_LOCAL_DIVERGENCE_REASON = "LOCAL_DIVERGENCE"
assert _LOCAL_DIVERGENCE_REASON in _LEDGER_CANONICAL_REASONS[LedgerOperation.ASSERT]

#: `\Z` y no `$`: `$` tambien casa antes de un `\n` final.
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}\Z")

CREATING_TYPES = frozenset({"CREATE_ENTITY", "CREATE_ASSERTION"})
RELATION_TYPES = frozenset({"LINK_EXISTING", "PROJECT_RELATION"})
#: Operaciones que cierran una vigencia. Exigen `reason_code` (R1 del ledger).
CLOSING_TYPES = frozenset({"UPDATE_ENTITY", "SUPERSEDE_ASSERTION"})
SUPPORTED_TYPES = CREATING_TYPES | RELATION_TYPES | CLOSING_TYPES


@dataclass
class AppliedOperation:
    """Lo que una operacion escribio de verdad. Base del rollback."""

    operation_id: str
    operation_type: str
    idempotency_key: str
    kind: str  # NODE | RELATIONSHIP | PROPERTIES
    created_id: Optional[str] = None
    target_id: Optional[str] = None
    previous_state: Optional[dict[str, Any]] = None
    changed_props: dict[str, Any] = field(default_factory=dict)
    #: M4 (rework): marcas de revision de ESTA operacion. No son rechazos: la
    #: operacion se aplico. Existen para que la auditoria encuentre lo que hay
    #: que mirar sin conocer la forma interna del grafo (sin tener que buscar
    #: `local_override_of IS NOT NULL` a mano).
    review_marks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "idempotency_key": self.idempotency_key,
            "kind": self.kind,
            "created_id": self.created_id,
            "target_id": self.target_id,
            "previous_state": self.previous_state,
            "changed_props": dict(self.changed_props),
            "review_marks": [dict(m) for m in self.review_marks],
        }


@dataclass
class ExecutionContext:
    """Contexto de una ejecucion concreta. Nada de esto sale del plan."""

    operator_id: str
    written_at: str
    applied_keys: AppliedKeyStore


@dataclass
class ExecutionOutcome:
    applied: list[AppliedOperation] = field(default_factory=list)
    noop_keys: list[str] = field(default_factory=list)

    @property
    def created_ids(self) -> list[str]:
        return [a.created_id for a in self.applied if a.created_id]

    @property
    def review_marks(self) -> list[dict[str, Any]]:
        """Todo lo que esta ejecucion deja pendiente de mirar, ya resuelto.

        Cada marca lleva la operacion y el objetivo, para que un auditor no
        tenga que volver al grafo ni saber que campo mirar.
        """
        out: list[dict[str, Any]] = []
        for applied in self.applied:
            for mark in applied.review_marks:
                out.append(
                    {
                        "operation_id": applied.operation_id,
                        "assertion_id": applied.target_id,
                        **mark,
                    }
                )
        return out


# --- Utilidades de lectura del driver -------------------------------------
def _field(record: Any, name: str) -> Any:
    """Lee un campo de un registro del driver sin asumir su clase concreta."""
    if record is None:
        return None
    if isinstance(record, dict):
        return record.get(name)
    try:
        return record[name]
    except (KeyError, TypeError, IndexError):
        return getattr(record, name, None)


def _single(tx: Any, query: cypher.Query) -> Any:
    """Ejecuta y devuelve el unico registro, o None. Traduce fallos del driver."""
    try:
        result = tx.run(query.cypher, query.params)
        return result.single() if result is not None else None
    except WriterAbort:
        raise
    except Exception as exc:
        raise WriterAbort(
            codes.EXEC_DRIVER_FAILURE,
            f"el driver fallo ejecutando la consulta: {exc}",
            {"cypher": query.cypher},
        ) from exc


# --- Precondiciones -------------------------------------------------------
def _check_expected_state(
    tx: Any,
    op: dict,
    workspace: str,
    target_id: str,
    is_assertion: bool,
    partida_id: str | None = None,
) -> dict:
    """Concurrencia optimista. Un desajuste aborta el PLAN, no la operacion.

    M3 (docs/v3/49 §2.4): la lectura esta ACOTADA al ambito del plan
    (`partida_id`). Si no aparece nada ahi, se distingue -- con una segunda
    consulta, tambien en Cypher -- entre "no existe" (`EXEC_TARGET_MISSING`)
    y "existe, pero en otro ambito" (`EXEC_SCOPE_MISMATCH`, el Invariante 2
    violado en lectura: leer un nodo de otra partida y operarlo).
    """
    reader = cypher.read_assertion_state if is_assertion else cypher.read_entity_state
    record = _single(tx, reader(target_id, workspace, partida_id))
    if record is None:
        any_scope_reader = (
            cypher.read_assertion_state_any_scope
            if is_assertion
            else cypher.read_entity_state_any_scope
        )
        if _single(tx, any_scope_reader(target_id, workspace)) is not None:
            raise WriterAbort(
                codes.EXEC_SCOPE_MISMATCH,
                f"la operacion {op['operation_id']} apunta a {target_id!r}, que "
                "existe pero en otro ambito de partida que el declarado por el plan",
                {
                    "operation_id": op["operation_id"],
                    "target_id": target_id,
                    "declared_partida_id": partida_id,
                },
            )
        raise WriterAbort(
            codes.EXEC_TARGET_MISSING,
            f"la operacion {op['operation_id']} apunta a {target_id!r}, que no existe",
            {"operation_id": op["operation_id"], "target_id": target_id},
        )
    version = _field(record, "version")
    state_hash = _field(record, "state_hash")
    if version != op["expected_version"]:
        raise WriterAbort(
            codes.EXEC_VERSION_MISMATCH,
            "la version leida no es la esperada: el grafo se movio bajo el plan",
            {
                "operation_id": op["operation_id"],
                "target_id": target_id,
                "expected_version": op["expected_version"],
                "actual_version": version,
            },
        )
    expected_hash = (op.get("expected_hash") or {}).get("value")
    if expected_hash is not None and state_hash != expected_hash:
        raise WriterAbort(
            codes.EXEC_HASH_MISMATCH,
            "el hash de estado leido no es el esperado",
            {
                "operation_id": op["operation_id"],
                "target_id": target_id,
                "expected_hash": expected_hash,
                "actual_hash": state_hash,
            },
        )
    return {"version": version, "state_hash": state_hash}


def _assert_absent(tx: Any, op: dict, workspace: str, target_id: str, is_assertion: bool) -> None:
    """CREATE-only estricto: crear algo que ya existe es un conflicto, no un update.

    Deliberadamente SIN filtro de partida (`*_any_scope`): la identidad de un
    `entity_id`/`assertion_id` es unica en todo el workspace, cruzando capa
    juego y todas sus partidas -- dos ambitos jamas comparten el mismo id.
    """
    reader = (
        cypher.read_assertion_state_any_scope
        if is_assertion
        else cypher.read_entity_state_any_scope
    )
    if _single(tx, reader(target_id, workspace)) is not None:
        raise WriterAbort(
            codes.EXEC_TARGET_ALREADY_EXISTS,
            f"la operacion {op['operation_id']} crea {target_id!r}, que ya existe",
            {"operation_id": op["operation_id"], "target_id": target_id},
        )


def _check_local_override(
    tx: Any, op: dict, payload: dict, workspace: str, partida_id: str | None = None
) -> list[dict[str, Any]]:
    """M4 (docs/v3/49 §2.5): el otro filo del Invariante 2 para `local_override_of`.

    `admission.py` (`_local_override_incoherence`) ya rechazo, sin tocar
    Neo4j, el caso estructural (capa juego declarando un override). Lo que
    solo se sabe leyendo el grafo es si el `assertion_id` apuntado es de
    verdad de CAPA JUEGO -- ni de la propia partida (una cadena de
    overrides), ni de otra partida (el cruce cross-partida). Ambos casos
    ilegitimos comparten un solo chequeo: leer el objetivo ACOTADO a capa
    juego (`partida_id=None`, la misma `_scoped_match` de M3) y, si no
    aparece ahi, distinguir "no existe en ningun ambito" de "existe, pero no
    es de capa juego" -- exactamente el mismo patron MISSING/SCOPE_MISMATCH
    que ya usa `_check_expected_state`.

    SEMANTICA DE CADENAS (decision explicita de M4): un override SIEMPRE
    apunta a capa juego, nunca a otro override. Overridear un override ya
    existente cae en la misma rama que overridear el hecho de otra partida:
    `EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER`. Se elige "sin cadenas" y no
    "colapsar al original" ni "resolver al ultimo de la cadena" porque
    cualquiera de esas dos exigiria que el writer recorriera un grafo de
    punteros para decidir una escritura -- justo el tipo de logica que este
    modulo evita a proposito (fail-closed simple, sin inferencia). Quien
    quiera corregir una divergencia local ya escrita debe hacerlo sobre ESA
    afirmacion de partida (via el ciclo de vida normal: confirmar, contradecir
    o retractar), no encadenando un override sobre otro.

    UNICIDAD (rework, P1 del dictamen): dentro de `(workspace, partida_id)`
    solo puede haber UN `local_override_of` apuntando al mismo hecho de lore.
    El segundo intento es un conflicto duro
    (`EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED`), con el mismo criterio CREATE-only
    de `_assert_absent`: ni se fusiona, ni se encadena, ni "gana el ultimo".
    Sin esto, la propia partida podia acabar viendo dos divergencias
    simultaneas del mismo hecho, sin desempate posible en lectura.

    Devuelve las MARCAS DE REVISION de la operacion (vacio si no declara
    ninguna divergencia): la escritura se aplica, pero deja constancia
    explicita en el resultado. El circuito de aprobacion humana es M5; aqui
    solo se garantiza que la divergencia no pase inadvertida.
    """
    if not declares_local_override(payload):
        return []
    target = payload["local_override_of"]
    reason = payload.get("reason_code")
    if reason != _LOCAL_DIVERGENCE_REASON:
        raise WriterAbort(
            codes.EXEC_LOCAL_OVERRIDE_REASON_INVALID,
            f"la operacion {op['operation_id']} declara local_override_of sin el "
            f"reason_code canonico {_LOCAL_DIVERGENCE_REASON!r} (R1 del ledger)",
            {"operation_id": op["operation_id"], "reason_code": reason},
        )
    # Acotado a capa juego (`partida_id=None`), NUNCA al ambito del plan: un
    # override siempre apunta al lore compartido, jamas a la propia partida
    # ni a otra.
    game_state = _single(tx, cypher.read_assertion_state(target, workspace, None))
    if game_state is not None:
        if partida_id is not None:
            existing = _single(tx, cypher.find_local_override(workspace, partida_id, target))
            if existing is not None:
                raise WriterAbort(
                    codes.EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED,
                    f"la operacion {op['operation_id']} declara "
                    f"local_override_of={target!r}, pero la partida {partida_id!r} ya "
                    "tiene una divergencia local declarada sobre ese mismo hecho de "
                    "capa juego: una partida diverge de un hecho del lore UNA vez",
                    {
                        "operation_id": op["operation_id"],
                        "local_override_of": target,
                        "partida_id": partida_id,
                        "existing_assertion_id": _field(existing, "id"),
                    },
                )
        return [
            {
                "code": codes.LOCAL_DIVERGENCE_PENDING_REVIEW,
                "local_override_of": target,
                "partida_id": partida_id,
            }
        ]
    if _single(tx, cypher.read_assertion_state_any_scope(target, workspace)) is not None:
        raise WriterAbort(
            codes.EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER,
            f"la operacion {op['operation_id']} declara local_override_of={target!r}, "
            "que existe pero no es de capa juego (pertenece a una partida, la "
            "propia u otra): un override solo puede apuntar al lore compartido",
            {"operation_id": op["operation_id"], "local_override_of": target},
        )
    raise WriterAbort(
        codes.EXEC_LOCAL_OVERRIDE_TARGET_MISSING,
        f"la operacion {op['operation_id']} declara local_override_of={target!r}, "
        "que no existe en ningun ambito de este workspace",
        {"operation_id": op["operation_id"], "local_override_of": target},
    )


def _require(value: Any, op: dict, what: str) -> Any:
    if not value:
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_PAYLOAD,
            f"la operacion {op['operation_id']} ({op['operation_type']}) exige {what}",
            {"operation_id": op["operation_id"], "missing": what},
        )
    return value


def _reason_code(op: dict) -> str:
    """R1: el motivo viaja al grafo o no se escribe.

    El contrato congelado de `fact-assertion` no tiene campo de motivo, asi que
    `COPYRIGHT_TAKEDOWN` y `EXTRACTION_ERROR` dejarian el mismo nodo. El ledger
    lo puso por escrito como requisito de integracion: el writer transporta el
    `reason_code` del payload, y si no viene, no cierra nada.
    """
    value = (op.get("payload") or {}).get("reason_code")
    if not isinstance(value, str) or not _REASON_CODE.match(value):
        raise WriterAbort(
            codes.EXEC_REASON_CODE_MISSING,
            f"la operacion {op['operation_id']} cierra una vigencia sin reason_code valido "
            "(R1 del ledger): sin el, el grafo no distingue un takedown de un error",
            {"operation_id": op["operation_id"], "reason_code": value},
        )
    return value


def _validated_payload(op: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    """Valida la parte ejecutable de una operacion sin consultar el grafo.

    Es deliberadamente comun a apply y dry-run: una simulacion no puede
    presentar como ejecutable un payload que el writer real rechazaria.
    """
    op_type = op["operation_type"]
    if op_type not in SUPPORTED_TYPES:
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_OPERATION,
            f"tipo de operacion no soportado: {op_type}",
            {"operation_id": op["operation_id"], "operation_type": op_type},
        )
    payload = dict(op.get("payload") or {})
    # T2: la sesion de REVELACION viaja en el payload, que es el punto de
    # extension DOCUMENTADO del contrato (`additionalProperties: true`, por
    # depender del tipo de operacion y de la ontologia). No se anadio al
    # esquema del plan a proposito: los contratos v3 estan congelados en
    # 1.0.0 y hay una prueba que lo verifica byte a byte; ampliarlos sin
    # versionar seria colar un cambio de contrato por la puerta de atras.
    # Se retira antes de calcular `props` para que no acabe como propiedad
    # cruda del nodo: la estampa `visibility.stamp`, no el payload.
    payload.pop("known_from_session", None)
    props = cypher.safe_props(payload)
    def _estampar(fn, *args, **kwargs):
        """Traduce un fallo de declaracion en un aborto con codigo propio."""
        try:
            return fn(*args, **kwargs)
        except VisibilityStampError as exc:
            raise WriterAbort(
                codes.EXEC_REVELACION_NO_DECLARADA,
                str(exc),
                {"operation_id": op.get("operation_id")},
            ) from exc

    if op_type == "CREATE_ENTITY":
        _require(op.get("target_entity_id"), op, "target_entity_id")
        cypher.safe_token(payload.get("entity_type"), "etiqueta")
    elif op_type == "CREATE_ASSERTION":
        _require(op.get("assertion_id"), op, "assertion_id")
    elif op_type in RELATION_TYPES:
        _require(payload.get("subject_entity_id"), op, "payload.subject_entity_id")
        _require(payload.get("object_entity_id"), op, "payload.object_entity_id")
        predicate = _require(payload.get("predicate"), op, "payload.predicate")
        cypher.safe_token(predicate, "tipo de relacion")
    else:
        _require(
            op.get("assertion_id")
            if op_type == "SUPERSEDE_ASSERTION"
            else op.get("target_entity_id"),
            op,
            "assertion_id" if op_type == "SUPERSEDE_ASSERTION" else "target_entity_id",
        )
        _reason_code(op)
    return payload, props


# --- Procedencia ----------------------------------------------------------
def _provenance(view: SignedView, op: dict, ctx: ExecutionContext) -> dict[str, Any]:
    """Lo que el writer estampa el mismo en todo lo que escribe.

    `written_snapshot_id` es el testigo externo de R2 dentro del propio grafo;
    `reason_codes` transporta las razones de la decision (R1).
    """
    decision = view.decision_by_id(op["decision_id"])
    return {
        "workspace": view.workspace,
        "partida_id": view.partida_id,
        "version": 0,
        "written_snapshot_id": view.snapshot_id,
        "written_by_plan_hash": view.plan_hash_value,
        "written_by_operator": ctx.operator_id,
        "written_at": ctx.written_at,
        "idempotency_key": op["idempotency_key"],
        "decision_id": op["decision_id"],
        "reason_codes": list(decision.get("reason_codes") or []),
        "evidence_fragment_ids": list(op.get("evidence_fragment_ids") or []),
        "source_asset_id": view.source_asset_id,
        "collection_id": view.collection_id,
        "engine_version": view.engine_version,
        "ontology_version": view.ontology_version,
        "game_profile": view.game_profile,
    }


# --- Una operacion --------------------------------------------------------
def execute_operation(
    tx: Any, op: dict, view: SignedView, ctx: ExecutionContext
) -> AppliedOperation:
    op_type = op["operation_type"]
    ws = view.workspace
    partida_id = view.partida_id
    payload, props = _validated_payload(op)
    prov = _provenance(view, op, ctx)
    # T2: la sesion de REVELACION se declara por OPERACION, no por plan: dos
    # hechos del mismo plan pueden revelarse en sesiones distintas. Ausente en
    # ambito de partida -> el estampado aborta antes de tocar Neo4j.
    desde = (op.get("payload") or {}).get("known_from_session", SIN_DECLARAR)

    def _estampar(fn, *args, **kwargs):
        """Traduce un fallo de declaracion en un aborto con codigo propio."""
        try:
            return fn(*args, **kwargs)
        except VisibilityStampError as exc:
            raise WriterAbort(
                codes.EXEC_REVELACION_NO_DECLARADA,
                str(exc),
                {"operation_id": op.get("operation_id")},
            ) from exc

    if op_type == "CREATE_ENTITY":
        entity_id = _require(op.get("target_entity_id"), op, "target_entity_id")
        _assert_absent(tx, op, ws, entity_id, is_assertion=False)
        label = payload.get("entity_type")
        record = _single(
            tx,
            _estampar(cypher.create_entity, entity_id, ws, label,
                      {**props, **prov}, partida_id, known_from_session=desde),
        )
        return AppliedOperation(
            operation_id=op["operation_id"],
            operation_type=op_type,
            idempotency_key=op["idempotency_key"],
            kind="NODE",
            created_id=_field(record, "id") or entity_id,
            target_id=entity_id,
        )

    if op_type == "CREATE_ASSERTION":
        assertion_id = _require(op.get("assertion_id"), op, "assertion_id")
        _assert_absent(tx, op, ws, assertion_id, is_assertion=True)
        marks = _check_local_override(tx, op, payload, ws, partida_id)
        record = _single(
            tx,
            _estampar(cypher.create_assertion, assertion_id, ws,
                      {**props, **prov}, partida_id, known_from_session=desde),
        )
        return AppliedOperation(
            operation_id=op["operation_id"],
            operation_type=op_type,
            idempotency_key=op["idempotency_key"],
            kind="NODE",
            created_id=_field(record, "id") or assertion_id,
            target_id=assertion_id,
            review_marks=marks,
        )

    if op_type in RELATION_TYPES:
        subject = _require(payload.get("subject_entity_id"), op, "payload.subject_entity_id")
        obj = _require(payload.get("object_entity_id"), op, "payload.object_entity_id")
        predicate = _require(payload.get("predicate"), op, "payload.predicate")
        target = op.get("target_entity_id") or subject
        previous = _check_expected_state(tx, op, ws, target, is_assertion=False, partida_id=partida_id)
        rel_props = {k: v for k, v in props.items() if k != "predicate"}
        record = _single(
            tx,
            _estampar(
                cypher.create_relation,
                predicate, subject, obj, ws, {**rel_props, **prov}, partida_id,
                known_from_session=desde,
            ),
        )
        if record is None:
            raise WriterAbort(
                codes.EXEC_TARGET_MISSING,
                f"la operacion {op['operation_id']} enlaza con {obj!r}, que no es "
                "visible en el ambito del plan (no existe o pertenece a otra partida)",
                {"operation_id": op["operation_id"], "target_id": obj},
            )
        return AppliedOperation(
            operation_id=op["operation_id"],
            operation_type=op_type,
            idempotency_key=op["idempotency_key"],
            kind="RELATIONSHIP",
            created_id=_field(record, "id"),
            target_id=target,
            previous_state=previous,
        )

    # Cierre de vigencia: UPDATE_ENTITY / SUPERSEDE_ASSERTION.
    is_assertion = op_type == "SUPERSEDE_ASSERTION"
    target = _require(
        op.get("assertion_id") if is_assertion else op.get("target_entity_id"),
        op,
        "assertion_id" if is_assertion else "target_entity_id",
    )
    reason = _reason_code(op)
    previous = _check_expected_state(tx, op, ws, target, is_assertion=is_assertion, partida_id=partida_id)
    changed = {
        k: v for k, v in props.items() if k in cypher.ALLOWED_UPDATE_PROPS and k != "version"
    }
    changed["reason_code"] = reason
    changed["version"] = int(op["expected_version"]) + 1
    changed["updated_at"] = ctx.written_at
    writer_fn = (
        cypher.close_assertion_validity if is_assertion else cypher.close_entity_validity
    )
    _single(tx, writer_fn(target, ws, changed, partida_id))
    return AppliedOperation(
        operation_id=op["operation_id"],
        operation_type=op_type,
        idempotency_key=op["idempotency_key"],
        kind="PROPERTIES",
        target_id=target,
        previous_state=previous,
        changed_props=changed,
    )


# --- El plan entero -------------------------------------------------------
def execute_plan(driver: Any, view: SignedView, ctx: ExecutionContext) -> ExecutionOutcome:
    """Aplica el plan en UNA transaccion. Cualquier fallo la revierte entera.

    La marca autoritativa vive en Neo4j y se crea dentro de esta transaccion.
    El almacén inyectado se actualiza después sólo como caché compatible.
    """
    outcome = ExecutionOutcome()
    pending: list[AppliedOperation] = []

    try:
        session_cm = driver.session()
    except Exception as exc:
        raise WriterAbort(
            codes.EXEC_DRIVER_FAILURE, f"no se pudo abrir la sesion: {exc}"
        ) from exc

    with session_cm as session:
        try:
            tx = session.begin_transaction()
        except Exception as exc:
            raise WriterAbort(
                codes.EXEC_DRIVER_FAILURE, f"no se pudo abrir la transaccion: {exc}"
            ) from exc
        try:
            for op in view.mutation_operations:
                key = op["idempotency_key"]
                cached = ctx.applied_keys.is_applied(key)
                claimed = _single(
                    tx,
                    cypher.claim_applied_operation(
                        view.workspace,
                        key,
                        view.plan_hash_value,
                        op["operation_id"],
                        ctx.written_at,
                        uuid.uuid4().hex,
                    ),
                )
                existing_hash = _field(claimed, "plan_hash")
                existing_operation = _field(claimed, "operation_id")
                created = _field(claimed, "created")
                # Compatibilidad con drivers falsos antiguos sin retorno tipado.
                if created is None and existing_hash is None:
                    created = not cached
                if not created:
                    if (
                        existing_hash != view.plan_hash_value
                        or existing_operation != op["operation_id"]
                    ):
                        raise WriterAbort(
                            codes.EXEC_IDEMPOTENCY_CONFLICT,
                            "idempotency_key ya aplicada por un plan incompatible",
                            {
                                "workspace": view.workspace,
                                "idempotency_key": key,
                                "expected_plan_hash": view.plan_hash_value,
                                "actual_plan_hash": existing_hash,
                                "expected_operation_id": op["operation_id"],
                                "actual_operation_id": existing_operation,
                            },
                        )
                    outcome.noop_keys.append(key)
                    continue
                pending.append(execute_operation(tx, op, view, ctx))
            tx.commit()
        except Exception:
            try:
                tx.rollback()
            except Exception:  # pragma: no cover - rollback del rollback
                pass
            raise

    for applied in pending:
        try:
            ctx.applied_keys.record(
                applied.idempotency_key,
                {
                    "workspace": view.workspace,
                    "snapshot_id": view.snapshot_id,
                    "plan_hash": view.plan_hash_value,
                    "operation_id": applied.operation_id,
                    "operation_type": applied.operation_type,
                    "target_id": applied.target_id,
                    "created_id": applied.created_id,
                    "applied_at": ctx.written_at,
                    "operator_id": ctx.operator_id,
                    "authority": "neo4j",
                },
            )
        except Exception:
            # Una caché vacía o atrasada es segura: el reintento consulta Neo4j.
            pass
    outcome.applied = pending
    return outcome


def simulate_plan(view: SignedView, ctx: ExecutionContext) -> ExecutionOutcome:
    """Dry-run: clasifica sin tocar el driver.

    No recibe driver. No puede tocarlo aunque quisiera: no lo tiene.
    """
    outcome = ExecutionOutcome()
    for op in view.mutation_operations:
        key = op["idempotency_key"]
        if ctx.applied_keys.is_applied(key):
            outcome.noop_keys.append(key)
            continue
        payload, _props = _validated_payload(op)
        # El dry-run tambien anuncia la divergencia: quien simula antes de
        # aplicar tiene que poder ver que ESTE plan la trae, sin aplicarlo.
        marks = (
            [
                {
                    "code": codes.LOCAL_DIVERGENCE_PENDING_REVIEW,
                    "local_override_of": payload["local_override_of"],
                    "partida_id": getattr(view, "partida_id", None),
                }
            ]
            if op["operation_type"] == "CREATE_ASSERTION"
            and declares_local_override(payload)
            else []
        )
        outcome.applied.append(
            AppliedOperation(
                operation_id=op["operation_id"],
                operation_type=op["operation_type"],
                idempotency_key=key,
                kind="SIMULATED",
                target_id=op.get("target_entity_id") or op.get("assertion_id"),
                review_marks=marks,
            )
        )
    return outcome


__all__ = [
    "AppliedOperation",
    "ExecutionContext",
    "ExecutionOutcome",
    "execute_operation",
    "execute_plan",
    "simulate_plan",
    "SUPPORTED_TYPES",
]
