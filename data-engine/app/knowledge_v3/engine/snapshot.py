# -*- coding: utf-8 -*-
"""Estado actual del grafo, visto por el motor como una FOTO INMUTABLE.

El motor local NO habla con Neo4j. Ni para leer. Recibe un `GraphSnapshot`:
una vista de solo lectura, identificada por `snapshot_id`, que fija el estado
sobre el que se calculan las decisiones y del que salen `expected_version` y
`expected_hash` de cada operacion del plan.

Por que una interfaz y no un cliente:

* el plan declara `snapshot_id`; si el motor leyese "lo que hubiera ahora" en
  cada consulta, ese ancla seria mentira y dos planes concurrentes no se
  podrian ordenar;
* la implementacion en memoria hace que todo el motor sea testeable sin base
  de datos, sin contenedores y sin red — que es la unica forma de que los
  tests de reglas midan reglas y no infraestructura;
* el enganche real a Neo4j es de SOLO LECTURA y queda DECLARADO aqui
  (`Neo4jReadOnlyGraphSnapshot`) sin implementar: conectarlo es trabajo del
  bloque de integracion, y hasta entonces cualquiera que lo instancie recibe
  un error explicito en vez de un cliente a medias.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional, Protocol, runtime_checkable

from ..contracts.base import sha256_hash
from .config import BLOCKING_STATUSES, LIVE_STATES, LIVE_STATUSES


@dataclass(frozen=True)
class SnapshotEntity:
    """Entidad existente en el grafo, con su version y su hash de estado.

    `version` y `state_hash` son los que el plan copia a `expected_version` /
    `expected_hash`: concurrencia optimista. Si el grafo cambio entre el
    snapshot y el apply, el writer rechaza la operacion.
    """

    entity_id: str
    entity_type: str
    version: int
    state_hash: dict
    labels: tuple[str, ...] = ()

    @staticmethod
    def of(entity_id: str, entity_type: str, version: int = 1, **kw) -> "SnapshotEntity":
        """Constructor de conveniencia con `state_hash` derivado del estado."""
        return SnapshotEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            version=version,
            state_hash=sha256_hash(
                {"entity_id": entity_id, "entity_type": entity_type, "version": version}
            ),
            **kw,
        )


@dataclass(frozen=True)
class SnapshotAssertion:
    """Afirmacion ya presente en el ledger, reducida a lo que el motor necesita.

    No es un `FactAssertion` completo a proposito: el motor solo puede
    comparar; construir afirmaciones es del ledger, y arrastrar el documento
    entero aqui invitaria a que el motor lo modificase.
    """

    assertion_id: str
    subject_entity_id: str
    object_entity_id: str
    predicate: str
    direction: str
    negated: bool
    status: str
    state: str
    version: int = 1
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidence: float = 1.0
    state_hash: Optional[dict] = None

    def is_live(self) -> bool:
        """Vigente = viva en el ledger Y viva en el eje temporal.

        Los dos ejes son distintos (contrato: `status` vs `state`) y aqui hacen
        falta los dos: una afirmacion `CONFIRMED` pero `ENDED` describe un
        tramo de tiempo cerrado y no contradice a una nueva.
        """
        return self.status in LIVE_STATUSES and self.state in LIVE_STATES

    def is_unresolved_conflict(self) -> bool:
        """Marcada `CONTRADICTED` y aun sin resolver por un humano."""
        return self.status == "CONTRADICTED" and self.state in LIVE_STATES

    def blocks_new_claims(self) -> bool:
        """Vigente, o pendiente de que un humano resuelva su contradiccion.

        Es lo que el eje de contradiccion debe mirar: `is_live()` sola dejaba
        pasar la reafirmacion de una cara de un conflicto abierto.
        """
        return self.status in BLOCKING_STATUSES and self.state in LIVE_STATES


@runtime_checkable
class GraphSnapshot(Protocol):
    """Vista de SOLO LECTURA del grafo en un instante identificado."""

    @property
    def snapshot_id(self) -> str: ...

    @property
    def workspace(self) -> str: ...

    def entity(self, entity_id: str) -> Optional[SnapshotEntity]:
        """Entidad por id, o None si no existe en este snapshot."""
        ...

    def assertions_for_pair(self, a: str, b: str) -> Iterator[SnapshotAssertion]:
        """Afirmaciones que involucran a la pareja {a, b}, en cualquier orden."""
        ...

    def assertions_for_subject(self, entity_id: str, predicate: str) -> Iterator[SnapshotAssertion]:
        """Afirmaciones con `entity_id` como sujeto logico de `predicate`."""
        ...


@dataclass
class InMemoryGraphSnapshot:
    """Implementacion en memoria. Determinista y sin efectos secundarios.

    Es la implementacion que usan los tests y la que hace de doble en cualquier
    ejecucion en sombra. No escribe nada: no tiene un solo metodo que mute el
    grafo, y eso es intencionado.
    """

    snapshot_id: str
    workspace: str
    entities: dict[str, SnapshotEntity] = field(default_factory=dict)
    assertions: list[SnapshotAssertion] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        snapshot_id: str,
        workspace: str,
        entities: Iterable[SnapshotEntity] = (),
        assertions: Iterable[SnapshotAssertion] = (),
    ) -> "InMemoryGraphSnapshot":
        return cls(
            snapshot_id=snapshot_id,
            workspace=workspace,
            entities={e.entity_id: e for e in entities},
            assertions=list(assertions),
        )

    def entity(self, entity_id: str) -> Optional[SnapshotEntity]:
        return self.entities.get(entity_id)

    def assertions_for_pair(self, a: str, b: str) -> Iterator[SnapshotAssertion]:
        pair = {a, b}
        for item in self.assertions:
            if {item.subject_entity_id, item.object_entity_id} == pair:
                yield item

    def assertions_for_subject(self, entity_id: str, predicate: str) -> Iterator[SnapshotAssertion]:
        for item in self.assertions:
            if item.predicate != predicate:
                continue
            subject = (
                item.object_entity_id
                if item.direction == "OBJECT_TO_SUBJECT"
                else item.subject_entity_id
            )
            if subject == entity_id:
                yield item


class Neo4jReadOnlyGraphSnapshot:
    """Enganche de SOLO LECTURA a Neo4j. DECLARADO, no implementado.

    Contrato que debera cumplir el bloque de integracion:

    1. abrir una sesion de **lectura** (`default_access_mode=READ`) y no
       exponer ningun metodo de escritura;
    2. materializar `snapshot_id` a partir de una marca del propio grafo
       (por ejemplo la transaccion o un `lastCommittedTxId`), NUNCA de
       `datetime.now()`: el ancla debe poder recomprobarse;
    3. devolver `version` y `state_hash` por nodo y por afirmacion, que son
       los que acaban en `expected_version` / `expected_hash`;
    4. filtrar SIEMPRE por `workspace`: el aislamiento es duro.

    Se deja declarado y fallando en voz alta para que nadie confunda "hay una
    clase" con "hay integracion". Instanciarlo hoy es un error del llamante,
    no un modo degradado.
    """

    def __init__(self, *args, **kwargs):  # pragma: no cover - declarado, no implementado
        raise NotImplementedError(
            "Neo4jReadOnlyGraphSnapshot esta declarado para el bloque de integracion "
            "y no implementado: el motor local no lee del grafo productivo en esta "
            "fase. Usa InMemoryGraphSnapshot."
        )


EMPTY_SNAPSHOT_ID = "snapshot:empty"


def empty_snapshot(workspace: str) -> InMemoryGraphSnapshot:
    """Snapshot vacio: grafo sin entidades ni afirmaciones.

    Util y peligroso a partes iguales: con el, ningun claim contradice nada
    (no hay con que) y ninguna entidad existe (asi que ningun claim se acepta).
    """
    return InMemoryGraphSnapshot(snapshot_id=EMPTY_SNAPSHOT_ID, workspace=workspace)
