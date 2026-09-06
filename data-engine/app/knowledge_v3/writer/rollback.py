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
            doc.instructions.append(
                RollbackInstruction(
                    operation_id=op.operation_id,
                    action="DELETE_NODE",
                    target_id=op.target_id,
                    detail={
                        "created_id": op.created_id,
                        "workspace": view.workspace,
                        "label": op.node_label,
                        # El ambito viaja SIEMPRE, y `None` significa capa
                        # juego, no "cualquiera". La diferencia entre el campo
                        # ausente y el campo a `None` es justo lo que separa
                        # un DENY de un borrado de capa juego.
                        "partida_id": op.partida_id,
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
                    action="DELETE_RELATIONSHIP",
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
                    action="RESTORE_PROPERTIES",
                    target_id=op.target_id,
                    detail={
                        "restore": op.previous_state or {},
                        "changed": dict(op.changed_props),
                        "workspace": view.workspace,
                        "label": op.node_label,
                        "partida_id": op.partida_id,
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
    return doc


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


#: Ausencia de campo, distinguida de `None`. `None` es un ambito CONCRETO (la
#: capa juego); la ausencia del campo es un documento que no dice en que
#: ambito estaba lo que quiere borrar, y eso se deniega.
_AUSENTE = object()

#: Etiquetas que una consulta de reversion puede borrar, y por que propiedad
#: durable se localiza cada una. Es una lista blanca a proposito: sin etiqueta,
#: un `MATCH (n {workspace, idempotency_key})` alcanza cualquier nodo que
#: comparta clave, incluido el de otra partida.
#:
#: Ampliarla es el punto de extension previsto (por ejemplo `V3Evidence` con
#: `evidence_id`): una entrada aqui y la consulta sale ya acotada por
#: workspace, ambito y clave, sin tocar la generacion.
DELETABLE_NODE_LABELS: dict[str, str] = {
    cypher_mod.LABEL_ENTITY: "entity_id",
    cypher_mod.LABEL_ASSERTION: "assertion_id",
}


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


def scope_clause(
    alias: str, partida_id: Any, params: dict[str, Any], *, contexto: str = "rollback"
) -> str:
    """UNICA definicion del filtro de ambito del camino de recuperacion.

    Escribe el parametro en `params` (si hace falta) y devuelve el predicado.
    Cualquier otro modulo del camino de recuperacion --por ejemplo el de
    procedencia-- debe llamar aqui en vez de escribir su propio criterio: dos
    definiciones que deben coincidir sin nada que lo verifique acaban
    divergiendo, y la que diverge borra de mas.

    `None` es la capa juego (`IS NULL`), nunca un comodin. Neo4j no compara
    `= null` como cierto, asi que esto va en `WHERE`, jamas en el patron de
    mapa.
    """
    if partida_id is None:
        return f"{alias}.partida_id IS NULL"
    if not isinstance(partida_id, str) or not partida_id.strip():
        raise RollbackNotReconstructible(
            f"{contexto}: 'partida_id' malformado ({partida_id!r}); ambito "
            "incoherente se deniega"
        )
    params["partida_id"] = partida_id
    return f"{alias}.partida_id = $partida_id"


def _scope_clause(
    alias: str, detail: dict[str, Any], instruccion: RollbackInstruction
) -> tuple[str, dict[str, Any]]:
    """Filtro de ambito, fail-closed. Nunca un comodin.

    Tres casos y solo tres:

    * campo ausente -> DENY. Un documento que no declara ambito no autoriza a
      borrar "donde sea": ambito ausente o incoherente se deniega.
    * `None` -> capa juego, y se exige `IS NULL`. Neo4j no compara `= null`
      como cierto, asi que esto va en `WHERE`, jamas en el patron de mapa.
    * cadena no vacia -> esa partida exacta.

    Cualquier otra cosa (cadena vacia, tipo raro) es un ambito malformado y
    tambien se deniega.
    """
    if detail.get("partida_id", _AUSENTE) is _AUSENTE:
        raise RollbackNotReconstructible(
            f"{instruccion.operation_id}: la instruccion no declara "
            "'partida_id'; sin ambito declarado no se borra (fail-closed)"
        )
    params: dict[str, Any] = {}
    clause = scope_clause(
        alias, detail["partida_id"], params, contexto=instruccion.operation_id
    )
    return clause, params


def delete_node_query(
    label: str,
    node_id: str,
    workspace: str,
    partida_id: Any,
    idempotency_key: str,
    *,
    contexto: str = "rollback",
) -> RollbackQuery:
    """Borrado de UN nodo por su clave durable completa.

    Punto de extension: registrar la etiqueta en `DELETABLE_NODE_LABELS` basta
    para que otra familia de nodos (por ejemplo `V3Evidence` por
    `fragment_id`) se pueda borrar por esta misma via, ya acotada por
    workspace, ambito y clave.
    """
    id_field = DELETABLE_NODE_LABELS.get(label)
    if id_field is None:
        raise RollbackNotReconstructible(
            f"{contexto}: etiqueta {label!r} no esta en la lista blanca de "
            "borrado; sin etiqueta conocida no se borra"
        )
    etiqueta = cypher_mod.safe_token(label, "label")
    params: dict[str, Any] = {"id": node_id, "ws": workspace, "key": idempotency_key}
    scope = scope_clause("n", partida_id, params, contexto=contexto)
    return RollbackQuery(
        f"MATCH (n:{etiqueta} {{{id_field}: $id, workspace: $ws, "
        "idempotency_key: $key}) "
        f"WHERE {scope} "
        "DETACH DELETE n RETURN count(*) AS borrados",
        params,
    )


def rollback_query(instruction: RollbackInstruction) -> RollbackQuery:
    """Traduce una instruccion a Cypher usando SOLO identidad durable.

    Ni una sola de estas consultas menciona `elementId`. Se localiza por la
    clave durable COMPLETA -- `workspace`, sujeto/predicado/objeto o
    identificador del nodo, etiqueta o tipo de relacion, `idempotency_key` y
    **ambito de partida** -- todo ello propiedades del grafo, que sobreviven a
    un restore.

    El ambito no es decorado: dos hechos semanticamente iguales, uno en capa
    juego y otro en `partida:otra`, comparten workspace, extremos, predicado y
    hasta `idempotency_key`. Sin el filtro de partida, deshacer uno se lleva el
    otro por delante. Y `partida_id: null` NO es comodin: es la capa juego.
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
        scope, scope_params = _scope_clause("r", detail, instruction)
        return RollbackQuery(
            f"MATCH (a:{cypher_mod.LABEL_ENTITY} {{entity_id: $subject, workspace: $ws}})"
            f"-[r:{predicate} {{workspace: $ws, idempotency_key: $key}}]->"
            f"(b:{cypher_mod.LABEL_ENTITY} {{entity_id: $object, workspace: $ws}}) "
            f"WHERE {scope} "
            "DELETE r RETURN count(*) AS borradas",
            {
                "subject": subject,
                "object": obj,
                "ws": workspace,
                "key": key,
                **scope_params,
            },
        )
    if instruction.action == "DELETE_NODE":
        node_id = detail.get("created_id") or instruction.target_id
        if not node_id:
            raise RollbackNotReconstructible(
                f"{instruction.operation_id}: sin identificador durable del nodo"
            )
        workspace = _require(detail, "workspace", instruction)
        key = _require(detail, "idempotency_key", instruction)
        label = _require(detail, "label", instruction)
        if detail.get("partida_id", _AUSENTE) is _AUSENTE:
            raise RollbackNotReconstructible(
                f"{instruction.operation_id}: la instruccion no declara "
                "'partida_id'; sin ambito declarado no se borra (fail-closed)"
            )
        return delete_node_query(
            label,
            node_id,
            workspace,
            detail["partida_id"],
            key,
            contexto=instruction.operation_id,
        )
    raise RollbackNotReconstructible(
        f"{instruction.operation_id}: {instruction.action} no se traduce a "
        "consulta (RESTORE_PROPERTIES lo decide el operador con el estado previo)"
    )


__all__ = [
    "RollbackInstruction",
    "RollbackDocument",
    "build_rollback",
    "RollbackQuery",
    "RollbackNotReconstructible",
    "rollback_query",
    "DELETABLE_NODE_LABELS",
    "delete_node_query",
    "scope_clause",
]
