# -*- coding: utf-8 -*-
"""Reconciliacion de identidad contra el GRAFO REAL, con un humano en medio.

EL HUECO QUE ESTE MODULO CIERRA
-------------------------------
El catalogo del que salia el mundo del resolutor era un FICHERO
(`ingest_cli --catalogo`). El grafo sobre el que escribe el writer es REAL. Y
no habia nada que los uniera: el fichero podia declarar `entity:sela-marrec`
mientras el grafo estaba vacio, y el plan salia con `CREATE_ASSERTION` +
`PROJECT_RELATION` sobre entidades inexistentes. Contra un Neo4j real eso
aborta con `EXEC_TARGET_MISSING`, y la unica forma de continuar era sembrar
las entidades a mano por Cypher — justo lo que el criterio de producto
prohibe.

Aqui la pregunta "¿esta entidad ya existe?" se le hace AL GRAFO
(`writer.reads.list_entities`), no a un fichero, y cada mencion sale con una
de estas tres decisiones:

  * ``LINK_EXISTING``          — el resolutor enlazo Y la entidad se OBSERVO
                                 en el grafo. No hace falta revisar nada.
  * ``CREATE_ENTITY_REQUIRED`` — hay que dar de alta. **Requiere aprobacion
                                 humana explicita, por id.**
  * ``REVIEW_IDENTITY``        — el resolutor no supo decidir (REVIEW/SPLIT).
                                 No es un alta ni un enlace: es una pregunta.

LA REGLA QUE NO SE RELAJA
-------------------------
``LINK_EXISTING`` NO es "enlaza, y si no existe creala". Un enlace cuya
entidad no aparece en el grafo NO se convierte en alta automatica: se
DEGRADA a ``CREATE_ENTITY_REQUIRED`` y se queda esperando a una persona, con
el motivo ``ENLACE_SIN_RESPALDO_EN_GRAFO`` escrito al lado. Esa degradacion
es el hallazgo del supervisor convertido en decision revisable: el fichero
decia que existia, el grafo dice que no, y quien resuelve la discrepancia es
un humano, no un valor por defecto.

La aprobacion se da POR ID, uno a uno. No hay "aprobar todas": una bandera
asi seria la conversion silenciosa que este modulo existe para impedir, solo
que escrita en la linea de comandos.

LO QUE ESTE MODULO NO HACE
--------------------------
No escribe en el grafo, no construye planes y no toca el writer. Produce un
DOCUMENTO de decisiones. Quien lo aplica es la cadena de siempre, con su gate
triple intacto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

#: Contrato INTERNO de este carril. No es uno de los contratos congelados de
#: `contracts/knowledge-v3/v1/`: no existe ninguno que exprese "decisiones de
#: identidad pendientes de revision humana", y inventarse uno con la etiqueta
#: `v3-internal-v1` seria colar un contrato nuevo por la puerta de atras. Se
#: declara como lo que es: un artefacto de operacion, versionado aparte.
DECISIONS_CONTRACT = "entity-decisions/carril-b-v1"

LINK_EXISTING = "LINK_EXISTING"
CREATE_ENTITY_REQUIRED = "CREATE_ENTITY_REQUIRED"
REVIEW_IDENTITY = "REVIEW_IDENTITY"

PENDIENTE = "PENDIENTE"
APROBADA = "APROBADA"
NO_PROCEDE = "NO_PROCEDE"

#: Acciones del contrato `entity-resolution/v3-internal-v1` que piden un alta.
ACCIONES_DE_ALTA = ("CREATE_NEW", "CREATE_PROVISIONAL")


@dataclass(frozen=True)
class EntityDecision:
    """Una mencion, y que hay que hacerle al grafo. Con su porque observado."""

    resolution_id: str
    decision: str
    entity_id: Optional[str]
    entity_type: Optional[str]
    name: Optional[str]
    mention_ids: tuple[str, ...]
    confidence: Optional[float]
    #: Codigos del resolutor MAS los que anade esta reconciliacion.
    reason_codes: tuple[str, ...]
    #: `PENDIENTE` mientras un alta no la haya aprobado una persona.
    review: str = NO_PROCEDE
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    @property
    def bloquea(self) -> bool:
        """True si la cadena NO puede continuar hasta que alguien la mire."""
        return self.review == PENDIENTE

    def to_dict(self) -> dict:
        return {
            "resolution_id": self.resolution_id,
            "decision": self.decision,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "mention_ids": list(self.mention_ids),
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "review": self.review,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    @staticmethod
    def from_dict(doc: Mapping[str, Any]) -> "EntityDecision":
        return EntityDecision(
            resolution_id=doc["resolution_id"],
            decision=doc["decision"],
            entity_id=doc.get("entity_id"),
            entity_type=doc.get("entity_type"),
            name=doc.get("name"),
            mention_ids=tuple(doc.get("mention_ids") or ()),
            confidence=doc.get("confidence"),
            reason_codes=tuple(doc.get("reason_codes") or ()),
            review=doc.get("review", NO_PROCEDE),
            approved_by=doc.get("approved_by"),
            approved_at=doc.get("approved_at"),
        )


@dataclass(frozen=True)
class DecisionLedger:
    """El conjunto de decisiones de una corrida, mas de donde salio el mundo."""

    workspace: str
    partida_id: Optional[str]
    source_path: str
    #: Ids OBSERVADOS en el grafo en el momento de reconciliar. Se guardan
    #: para que un revisor pueda comprobar contra que se comparo, en vez de
    #: fiarse de un veredicto sin contexto.
    graph_entity_ids: tuple[str, ...] = ()
    decisions: tuple[EntityDecision, ...] = ()
    generated_at: Optional[str] = None
    carencias: tuple[dict, ...] = ()

    @property
    def altas(self) -> tuple[EntityDecision, ...]:
        return tuple(d for d in self.decisions if d.decision == CREATE_ENTITY_REQUIRED)

    @property
    def pendientes(self) -> tuple[EntityDecision, ...]:
        return tuple(d for d in self.decisions if d.bloquea)

    @property
    def aprobadas(self) -> tuple[EntityDecision, ...]:
        return tuple(
            d for d in self.decisions
            if d.decision == CREATE_ENTITY_REQUIRED and d.review == APROBADA
        )

    def to_dict(self) -> dict:
        return {
            "contract": DECISIONS_CONTRACT,
            "workspace": self.workspace,
            "partida_id": self.partida_id,
            "source_path": self.source_path,
            "generated_at": self.generated_at,
            "graph_entity_ids": list(self.graph_entity_ids),
            "decisions": [d.to_dict() for d in self.decisions],
            "carencias": [dict(c) for c in self.carencias],
            "totals": {
                "link_existing": sum(
                    1 for d in self.decisions if d.decision == LINK_EXISTING),
                "create_entity_required": len(self.altas),
                "review_identity": sum(
                    1 for d in self.decisions if d.decision == REVIEW_IDENTITY),
                "pendientes": len(self.pendientes),
                "aprobadas": len(self.aprobadas),
                "graph_entities_observed": len(self.graph_entity_ids),
            },
        }

    @staticmethod
    def from_dict(doc: Mapping[str, Any]) -> "DecisionLedger":
        if doc.get("contract") != DECISIONS_CONTRACT:
            raise ValueError(
                f"documento de decisiones desconocido: {doc.get('contract')!r}; "
                f"se esperaba {DECISIONS_CONTRACT!r}"
            )
        return DecisionLedger(
            workspace=doc["workspace"],
            partida_id=doc.get("partida_id"),
            source_path=doc.get("source_path", ""),
            graph_entity_ids=tuple(doc.get("graph_entity_ids") or ()),
            decisions=tuple(
                EntityDecision.from_dict(d) for d in doc.get("decisions") or ()),
            generated_at=doc.get("generated_at"),
            carencias=tuple(dict(c) for c in doc.get("carencias") or ()),
        )


class AltaNoAprobada(RuntimeError):
    """La cadena se detiene: hay altas que ninguna persona ha aprobado."""

    def __init__(self, pendientes: Sequence[EntityDecision]):
        self.pendientes = tuple(pendientes)
        ids = ", ".join(sorted(str(d.entity_id) for d in self.pendientes))
        super().__init__(
            f"{len(self.pendientes)} alta(s) de entidad sin aprobacion humana: {ids}. "
            "Aprueba cada una por su id antes de aplicar; no existe forma de "
            "convertir un LINK_EXISTING en alta automatica"
        )


def reconcile(
    *,
    resolutions: Iterable[Mapping[str, Any]],
    graph_entity_ids: Iterable[str],
    workspace: str,
    source_path: str,
    partida_id: Optional[str] = None,
    generated_at: Optional[str] = None,
    names_by_mention: Optional[Mapping[str, str]] = None,
) -> DecisionLedger:
    """Contrasta lo que el resolutor PIDIO con lo que el grafo TIENE.

    `resolutions` son las filas de `candidates.*` del informe `ingest-run/v1`
    (link_existing + create_entity + review_identity, todas juntas): asi el
    criterio de agrupacion sigue siendo el campo `action` del contrato, no una
    heuristica de este modulo.

    `graph_entity_ids` es lo OBSERVADO. Un conjunto vacio es un dato
    legitimo (grafo nuevo) y produce altas para todo, no un enlace optimista.
    """
    presentes = set(graph_entity_ids)
    nombres = dict(names_by_mention or {})
    salida: list[EntityDecision] = []

    for fila in resolutions:
        accion = fila.get("action")
        resolution_id = fila.get("resolution_id")
        mention_ids = tuple(fila.get("mention_ids") or ())
        motivos = list(fila.get("reason_codes") or ())
        seleccionada = fila.get("selected_entity_id")
        asignada = fila.get("assigned_entity_id")
        nombre = next(
            (nombres[m] for m in mention_ids if m in nombres), None
        )

        if accion == LINK_EXISTING:
            if seleccionada in presentes:
                salida.append(EntityDecision(
                    resolution_id=resolution_id,
                    decision=LINK_EXISTING,
                    entity_id=seleccionada,
                    entity_type=fila.get("entity_type"),
                    name=nombre,
                    mention_ids=mention_ids,
                    confidence=fila.get("confidence"),
                    reason_codes=tuple(motivos + ["OBSERVADA_EN_GRAFO"]),
                    review=NO_PROCEDE,
                ))
                continue
            # El resolutor enlazo contra un catalogo que decia que existia; el
            # grafo dice que no. NO se crea sola: se degrada a alta pendiente.
            # Esta rama es, literalmente, el `EXEC_TARGET_MISSING` detectado
            # ANTES de tocar el grafo y convertido en una pregunta.
            salida.append(EntityDecision(
                resolution_id=resolution_id,
                decision=CREATE_ENTITY_REQUIRED,
                entity_id=seleccionada,
                entity_type=fila.get("entity_type"),
                name=nombre,
                mention_ids=mention_ids,
                confidence=fila.get("confidence"),
                reason_codes=tuple(motivos + ["ENLACE_SIN_RESPALDO_EN_GRAFO"]),
                review=PENDIENTE,
            ))
            continue

        if accion in ACCIONES_DE_ALTA:
            entity_id = asignada or seleccionada
            if entity_id in presentes:
                # El resolutor propuso un alta con un id que YA existe. Crear
                # abortaria con `EXEC_TARGET_EXISTS`; enlazar por nuestra
                # cuenta seria decidir una identidad sin que nadie la mire.
                salida.append(EntityDecision(
                    resolution_id=resolution_id,
                    decision=REVIEW_IDENTITY,
                    entity_id=entity_id,
                    entity_type=fila.get("entity_type"),
                    name=nombre,
                    mention_ids=mention_ids,
                    confidence=fila.get("confidence"),
                    reason_codes=tuple(motivos + ["ALTA_CON_ID_YA_EXISTENTE"]),
                    review=PENDIENTE,
                ))
                continue
            salida.append(EntityDecision(
                resolution_id=resolution_id,
                decision=CREATE_ENTITY_REQUIRED,
                entity_id=entity_id,
                entity_type=fila.get("entity_type"),
                name=nombre,
                mention_ids=mention_ids,
                confidence=fila.get("confidence"),
                reason_codes=tuple(motivos + ["AUSENTE_DEL_GRAFO"]),
                review=PENDIENTE,
            ))
            continue

        salida.append(EntityDecision(
            resolution_id=resolution_id,
            decision=REVIEW_IDENTITY,
            entity_id=seleccionada or asignada,
            entity_type=fila.get("entity_type"),
            name=nombre,
            mention_ids=mention_ids,
            confidence=fila.get("confidence"),
            reason_codes=tuple(motivos),
            review=PENDIENTE,
        ))

    carencias: list[dict] = []
    if not presentes:
        carencias.append({
            "code": "GRAFO_SIN_ENTIDADES",
            "detail": (
                "la lectura del grafo no devolvio ninguna entidad para este "
                "workspace. Es un dato, no un fallo: en un grafo nuevo TODO es "
                "alta. Se declara porque un conjunto vacio tambien se obtiene "
                "leyendo el workspace equivocado"
            ),
        })
    sin_nombre = [d.entity_id for d in salida
                  if d.decision == CREATE_ENTITY_REQUIRED and not d.name]
    if sin_nombre:
        carencias.append({
            "code": "ALTA_SIN_NOMBRE_OBSERVADO",
            "detail": (
                "estas altas no traen nombre canonico desde la mencion; el "
                "alta usara el propio entity_id como `name`: "
                + ", ".join(sorted(str(x) for x in sin_nombre))
            ),
        })

    return DecisionLedger(
        workspace=workspace,
        partida_id=partida_id,
        source_path=source_path,
        graph_entity_ids=tuple(sorted(presentes)),
        decisions=tuple(salida),
        generated_at=generated_at,
        carencias=tuple(carencias),
    )


def approve(
    ledger: DecisionLedger,
    entity_ids: Sequence[str],
    *,
    reviewer: str,
    at: str,
    entity_types: Optional[Mapping[str, str]] = None,
) -> DecisionLedger:
    """Aprueba altas POR ID. Sin comodines y sin "aprobar todas".

    Un id que no corresponda a un alta pendiente es un ERROR, no un no-op:
    aprobar algo que no estaba pendiente casi siempre significa que el revisor
    esta mirando un documento distinto del que se va a aplicar, y tragarselo
    en silencio dejaria pasar una aprobacion que no cubre lo que se escribe.
    """
    if not reviewer:
        raise ValueError("una aprobacion sin revisor no es una aprobacion")
    pedidos = list(entity_ids)
    pendientes = {
        d.entity_id for d in ledger.decisions
        if d.decision == CREATE_ENTITY_REQUIRED and d.review == PENDIENTE
    }
    desconocidos = [e for e in pedidos if e not in pendientes]
    if desconocidos:
        raise ValueError(
            "estos ids no son altas pendientes en este documento: "
            + ", ".join(sorted(desconocidos))
            + ". Pendientes: "
            + (", ".join(sorted(str(p) for p in pendientes)) or "(ninguna)")
        )
    elegidos = set(pedidos)
    # EQUIPO 5A. El revisor puede DECLARAR el tipo al aprobar. En un grafo
    # nuevo el resolutor no tiene con que inferirlo y `entity_type` sale
    # `None` para todo; sin esta via, la unica salida era que el alta se
    # descartase despues en silencio (ver `approved_snapshot_entities`).
    # Aprobar sigue siendo por id, uno a uno: esto no aprueba nada, solo
    # completa el dato que le falta a un alta que YA se esta aprobando.
    tipos = dict(entity_types or {})
    ajenos = [e for e in tipos if e not in elegidos]
    if ajenos:
        raise ValueError(
            "se declaro tipo para ids que no se estan aprobando: "
            + ", ".join(sorted(ajenos))
        )
    nuevas = tuple(
        EntityDecision(
            resolution_id=d.resolution_id,
            decision=d.decision,
            entity_id=d.entity_id,
            entity_type=(
                tipos.get(d.entity_id, d.entity_type)
                if d.entity_id in elegidos else d.entity_type
            ),
            name=d.name,
            mention_ids=d.mention_ids,
            confidence=d.confidence,
            reason_codes=d.reason_codes,
            review=APROBADA if d.entity_id in elegidos else d.review,
            approved_by=reviewer if d.entity_id in elegidos else d.approved_by,
            approved_at=at if d.entity_id in elegidos else d.approved_at,
        )
        for d in ledger.decisions
    )
    return DecisionLedger(
        workspace=ledger.workspace,
        partida_id=ledger.partida_id,
        source_path=ledger.source_path,
        graph_entity_ids=ledger.graph_entity_ids,
        decisions=nuevas,
        generated_at=ledger.generated_at,
        carencias=ledger.carencias,
    )


def require_reviewed(ledger: DecisionLedger, *, ignore_review_identity: bool = True) -> None:
    """Falla CERRADO si queda un alta sin aprobar. No degrada a dry-run.

    `ignore_review_identity` deja pasar las decisiones `REVIEW_IDENTITY`: no
    producen escritura ninguna (el motor no acepta un hecho cuya entidad no
    esta en el snapshot), asi que bloquear por ellas impediria aplicar la
    parte que SI esta resuelta. Las altas, en cambio, escriben: esas no pasan.
    """
    pendientes = [
        d for d in ledger.pendientes
        if not (ignore_review_identity and d.decision == REVIEW_IDENTITY)
    ]
    if pendientes:
        raise AltaNoAprobada(pendientes)


class AltaAprobadaSinTipo(RuntimeError):
    """Un alta que una PERSONA aprobo y que no se puede crear por falta de tipo.

    EL DEFECTO QUE ESTA EXCEPCION SUSTITUYE
    ---------------------------------------
    `approved_snapshot_entities` filtraba `if d.entity_id and d.entity_type`.
    En un grafo nuevo, `entity_type` sale `None` para TODO --el resolutor no
    tiene contra que inferirlo-- incluso declarando el titulo en el perfil y
    usandolo en el texto. Consecuencia MEDIDA: un alta aprobada por una
    persona desaparecia sin codigo, sin carencia y sin mensaje, mientras el
    mando seguia informando `"aprobadas": 10`. La cadena entera
    (`CREATE_PROVISIONAL` -> `ENTITY_PROVISIONAL` -> todo a `REVIEW` ->
    `_altas()` nunca invocado -> `plan_operations: 0`) hacia imposible
    arrancar un workspace nuevo por la ruta documentada.

    Un filtro silencioso sobre una decision humana es la peor forma de
    perderla: no deja rastro que auditar. Se cambia por esto, que DICE cual
    falta y como darselo.
    """

    def __init__(self, decisiones: Sequence["EntityDecision"]):
        self.decisiones = tuple(decisiones)
        ids = ", ".join(sorted(str(d.entity_id) for d in self.decisiones))
        super().__init__(
            "hay altas APROBADAS que no se pueden crear porque les falta "
            f"`entity_type`: {ids}. El tipo no se inventa: declaralo al "
            "aprobar (`--tipo-alta <entity_id>=<Tipo>`) o escribelo en el "
            "campo `entity_type` del documento de decisiones."
        )


def approved_snapshot_entities(ledger: DecisionLedger) -> list[dict]:
    """Las altas APROBADAS, en la forma que el snapshot del motor entiende.

    Solo `review == APROBADA`. Una pendiente no sale de aqui ni por descuido:
    esta funcion es la unica puerta por la que un alta entra en el snapshot,
    y filtra por el campo que escribe una persona.

    EQUIPO 5A: lo que falta se DICE. Un alta aprobada sin `entity_type` ya no
    se descarta: levanta `AltaAprobadaSinTipo`. `entity_id` ausente si sigue
    siendo un descarte legitimo --sin id no hay nada que crear ni que
    nombrarle al operador, y esa decision no es un alta, es una fila
    incompleta que nunca se aprobo por id.
    """
    faltan_tipo = [d for d in ledger.aprobadas if d.entity_id and not d.entity_type]
    if faltan_tipo:
        raise AltaAprobadaSinTipo(faltan_tipo)
    return [
        {
            "entity_id": d.entity_id,
            "type": d.entity_type,
            "name": d.name or d.entity_id,
            "pending_creation": True,
        }
        for d in ledger.aprobadas
        if d.entity_id and d.entity_type
    ]


__all__ = [
    "DECISIONS_CONTRACT",
    "LINK_EXISTING",
    "CREATE_ENTITY_REQUIRED",
    "REVIEW_IDENTITY",
    "PENDIENTE",
    "APROBADA",
    "NO_PROCEDE",
    "EntityDecision",
    "DecisionLedger",
    "AltaNoAprobada",
    "AltaAprobadaSinTipo",
    "reconcile",
    "approve",
    "require_reviewed",
    "approved_snapshot_entities",
]
