# -*- coding: utf-8 -*-
"""Rollback: lo que se deshace despues del commit.

Hay dos cosas distintas que la palabra «rollback» suele mezclar, y aqui NO se
mezclan:

* **Aborto a mitad** — lo resuelve la transaccion: si algo falla, no se escribe
  nada. No hace falta deshacer, porque no se hizo. Lo cubre `executor.py`.
* **Deshacer un plan YA confirmado** — eso ya no es transaccional: hay datos en
  el grafo. Esto es lo que genera este modulo.

Y lo genera como INSTRUCCIONES, no como ejecucion. El writer no borra por su
cuenta lo que escribio: deshacer es una decision de operador, y ademas las
instrucciones inversas incluyen borrados, que es exactamente lo que este
subsistema tiene prohibido hacer sin plan. Lo que sale de aqui es un documento
que un operador lee, aprueba y aplica — o convierte en un plan inverso que el
motor local vuelva a sellar.

Limite dicho sin adornos: el rollback de un cierre de vigencia solo puede
restaurar `version` y `state_hash`, que es lo que el writer leyo antes de
escribir. Las propiedades previas que no leyo no las puede devolver. Restaurar
un estado completo exigiria leerlo entero antes de cada cierre, y eso no esta
hecho.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import cypher as cypher_mod
from .executor import AppliedOperation
from .view import SignedView

#: Acciones. Las tres primeras existian; las dos ultimas las anade este bloque.
ACTION_DELETE_NODE = "DELETE_NODE"
ACTION_DELETE_RELATIONSHIP = "DELETE_RELATIONSHIP"
ACTION_RESTORE_PROPERTIES = "RESTORE_PROPERTIES"
#: Purga la procedencia que sostenia lo borrado -- y SOLO la que se queda sin
#: ninguna referencia viva. Se ejecuta DESPUES del `DELETE_NODE` de la asercion.
ACTION_PURGE_PROVENANCE = "PURGE_PROVENANCE"
#: Retira la marca autoritativa de idempotencia (`V3AppliedOperation`) de la
#: operacion revertida. Sin esto, el grafo sigue afirmando que la operacion esta
#: aplicada cuando su conocimiento ya no existe, y el siguiente apply devuelve
#: un no-op limpio sobre un grafo vacio.
ACTION_FORGET_APPLIED = "FORGET_APPLIED_OPERATION"


@dataclass
class RollbackInstruction:
    """Una accion inversa. Descriptiva: nadie la ejecuta automaticamente."""

    operation_id: str
    action: str  # DELETE_NODE | DELETE_RELATIONSHIP | RESTORE_PROPERTIES
    target_id: str | None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "action": self.action,
            "target_id": self.target_id,
            "detail": dict(self.detail),
        }


@dataclass
class RollbackDocument:
    workspace: str
    snapshot_id: str
    plan_hash: str
    instructions: list[RollbackInstruction] = field(default_factory=list)
    unrecoverable: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "snapshot_id": self.snapshot_id,
            "plan_hash": self.plan_hash,
            "instructions": [i.to_dict() for i in self.instructions],
            "unrecoverable": list(self.unrecoverable),
        }


def build_rollback(
    view: SignedView, applied: Iterable[AppliedOperation]
) -> RollbackDocument:
    """Instrucciones para deshacer lo que ESTE writer escribio, en orden inverso.

    Orden inverso a proposito: las aristas se borran antes que los nodos que
    unen, o el borrado del nodo tropieza con la arista.
    """
    doc = RollbackDocument(
        workspace=view.workspace,
        snapshot_id=view.snapshot_id,
        plan_hash=view.plan_hash_value,
    )
    for op in reversed(list(applied)):
        if op.kind == "NODE":
            # Lo que el `DETACH DELETE` de este nodo se va a llevar por delante
            # SIN decirlo: las aristas de procedencia que apuntan a la asercion.
            # Se DECLARAN aqui, en el propio documento, en vez de descubrirlas
            # comparando censos despues.
            detaches = _provenance_edges_of(op)
            doc.instructions.append(
                RollbackInstruction(
                    operation_id=op.operation_id,
                    action=ACTION_DELETE_NODE,
                    target_id=op.target_id,
                    detail={
                        "created_id": op.created_id,
                        "workspace": view.workspace,
                        "partida_id": op.partida_id if op.partida_id else view.partida_id,
                        "idempotency_key": op.idempotency_key,
                        "detaches_provenance": detaches,
                    },
                )
            )
            if op.evidence_fragment_ids:
                # La purga va DESPUES del borrado del nodo, a proposito: solo
                # entonces la evidencia que sostenia queda (o no) sin referencias
                # vivas, y la cuenta de referencias mide lo que hay de verdad.
                doc.instructions.append(
                    RollbackInstruction(
                        operation_id=op.operation_id,
                        action=ACTION_PURGE_PROVENANCE,
                        target_id=op.target_id,
                        detail={
                            "workspace": view.workspace,
                            "partida_id": op.partida_id if op.partida_id else view.partida_id,
                            "assertion_id": op.target_id,
                            "fragment_ids": list(op.evidence_fragment_ids),
                            "idempotency_key": op.idempotency_key,
                        },
                    )
                )
        elif op.kind == "RELATIONSHIP":
            # `target_id` es el SUJETO (identidad de producto), no el
            # `elementId`. El `elementId` contiene el UUID de la base y se
            # regenera al restaurar un dump: una instruccion que dependiese de
            # el dejaria de ser ejecutable justo cuando hace falta. Va aparte,
            # como dato informativo del momento de la escritura, con un nombre
            # que dice lo que es.
            doc.instructions.append(
                RollbackInstruction(
                    operation_id=op.operation_id,
                    action=ACTION_DELETE_RELATIONSHIP,
                    target_id=op.subject_id or op.target_id,
                    detail={
                        "subject": op.subject_id or op.target_id,
                        "predicate": op.predicate,
                        "object": op.object_id,
                        "workspace": view.workspace,
                        "partida_id": op.partida_id,
                        "idempotency_key": op.idempotency_key,
                        "element_id_at_write": op.created_id,
                    },
                )
            )
            faltan = [
                nombre
                for nombre, valor in (
                    ("subject", op.subject_id or op.target_id),
                    ("predicate", op.predicate),
                    ("object", op.object_id),
                )
                if not valor
            ]
            if faltan:
                doc.unrecoverable.append(
                    f"{op.operation_id}: la relacion no quedo identificada por "
                    f"dominio (faltan {faltan})"
                )
        elif op.kind == "PROPERTIES":
            doc.instructions.append(
                RollbackInstruction(
                    operation_id=op.operation_id,
                    action=ACTION_RESTORE_PROPERTIES,
                    target_id=op.target_id,
                    detail={
                        "restore": op.previous_state or {},
                        "changed": dict(op.changed_props),
                        "workspace": view.workspace,
                        "idempotency_key": op.idempotency_key,
                    },
                )
            )
            missing = sorted(set(op.changed_props) - set(op.previous_state or {}))
            if missing:
                doc.unrecoverable.append(
                    f"{op.operation_id}: no se leyo el valor previo de {missing}"
                )
        else:  # SIMULATED u otro: no escribio nada, no hay nada que deshacer.
            continue
        # La marca de idempotencia vive en el grafo (`V3AppliedOperation`) y es
        # lo que decide si el proximo apply reescribe o se declara no-op. Si el
        # rollback no la retira, el grafo afirma «esto ya esta aplicado» sobre
        # un conocimiento que acaba de borrar.
        doc.instructions.append(
            RollbackInstruction(
                operation_id=op.operation_id,
                action=ACTION_FORGET_APPLIED,
                target_id=op.idempotency_key,
                detail={
                    "workspace": view.workspace,
                    "idempotency_key": op.idempotency_key,
                    "plan_hash": view.plan_hash_value,
                },
            )
        )
    return doc


def _provenance_edges_of(op: AppliedOperation) -> list[dict[str, Any]]:
    """Aristas de procedencia que cuelgan del nodo que se va a borrar.

    Se derivan de lo que el writer ESTAMPO en ese nodo (`evidence_fragment_ids`,
    sujeto y objeto), no de una lectura del grafo: el documento se construye en
    el APPLY y la procedencia se persiste despues, en su propia transaccion.
    Que existan o no en el momento del rollback lo dice la ejecucion; que el
    `DETACH DELETE` se las llevaria, lo dice esto.
    """
    edges: list[dict[str, Any]] = []
    for fragment_id in op.evidence_fragment_ids or []:
        edges.append({"type": "SUPPORTED_BY", "to_label": "V3Evidence", "to_id": fragment_id})
    if op.subject_id:
        edges.append({"type": "HAS_SUBJECT", "to_label": "V3Entity", "to_id": op.subject_id})
    if op.object_id:
        edges.append({"type": "HAS_OBJECT", "to_label": "V3Entity", "to_id": op.object_id})
    return edges


# --- Reconstruccion: de instruccion a consulta ------------------------------
@dataclass
class RollbackQuery:
    """Consulta de reversion. NO pasa por `cypher.Query` a proposito.

    `cypher.Query` prohibe `DELETE` porque el writer no borra. Deshacer SI
    borra, y por eso vive en otro tipo: quien ejecute esto esta ejercitando el
    camino de recuperacion, no el de escritura, y tiene que verse en el codigo.
    """

    cypher: str
    params: dict[str, Any] = field(default_factory=dict)


class RollbackNotReconstructible(ValueError):
    """La instruccion no trae identidad de dominio suficiente para ejecutarse."""


def _require(detail: dict[str, Any], campo: str, instruccion: RollbackInstruction) -> Any:
    valor = detail.get(campo)
    if not valor:
        raise RollbackNotReconstructible(
            f"{instruccion.operation_id}: falta {campo!r} en el detalle; la "
            "instruccion no se puede localizar por identidad durable"
        )
    return valor


def rollback_query(instruction: RollbackInstruction) -> RollbackQuery:
    """Traduce una instruccion a Cypher usando SOLO identidad durable.

    Ni una sola de estas consultas menciona `elementId`. Se localiza por
    `(workspace, entity_id)` mas predicado, objeto y `idempotency_key` de la
    operacion que la escribio — todo ello propiedades del grafo, que sobreviven
    a un restore. `element_id_at_write`, si viaja en el detalle, se ignora.

    El `idempotency_key` es lo que impide borrar de mas: acota el borrado a la
    arista que ESTE plan escribio, aunque existan otras entre los mismos
    extremos y con el mismo predicado.
    """
    detail = dict(instruction.detail)
    if instruction.action == "DELETE_RELATIONSHIP":
        subject = _require(detail, "subject", instruction)
        obj = _require(detail, "object", instruction)
        predicate = cypher_mod.safe_token(
            _require(detail, "predicate", instruction), "predicate"
        )
        workspace = _require(detail, "workspace", instruction)
        key = _require(detail, "idempotency_key", instruction)
        return RollbackQuery(
            f"MATCH (a:{cypher_mod.LABEL_ENTITY} {{entity_id: $subject, workspace: $ws}})"
            f"-[r:{predicate} {{workspace: $ws, idempotency_key: $key}}]->"
            f"(b:{cypher_mod.LABEL_ENTITY} {{entity_id: $object, workspace: $ws}}) "
            "DELETE r RETURN count(*) AS borradas",
            {"subject": subject, "object": obj, "ws": workspace, "key": key},
        )
    if instruction.action == "DELETE_NODE":
        node_id = detail.get("created_id") or instruction.target_id
        if not node_id:
            raise RollbackNotReconstructible(
                f"{instruction.operation_id}: sin identificador durable del nodo"
            )
        workspace = _require(detail, "workspace", instruction)
        key = _require(detail, "idempotency_key", instruction)
        return RollbackQuery(
            "MATCH (n {workspace: $ws, idempotency_key: $key}) "
            "WHERE n.entity_id = $id OR n.assertion_id = $id "
            "DETACH DELETE n RETURN count(*) AS borrados",
            {"id": node_id, "ws": workspace, "key": key},
        )
    raise RollbackNotReconstructible(
        f"{instruction.operation_id}: {instruction.action} no se traduce a "
        "consulta (RESTORE_PROPERTIES lo decide el operador con el estado previo)"
    )


__all__ = [
    "ACTION_DELETE_NODE",
    "ACTION_DELETE_RELATIONSHIP",
    "ACTION_RESTORE_PROPERTIES",
    "ACTION_PURGE_PROVENANCE",
    "ACTION_FORGET_APPLIED",
    "RollbackInstruction",
    "RollbackDocument",
    "build_rollback",
    "RollbackQuery",
    "RollbackNotReconstructible",
    "rollback_query",
]
