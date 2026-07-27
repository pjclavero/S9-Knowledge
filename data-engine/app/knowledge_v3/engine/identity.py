# -*- coding: utf-8 -*-
"""Eje de EXISTENCIA: quien es el sujeto y quien el objeto, si es que se sabe.

El motor NO resuelve identidades — eso es del subsistema de resolucion, que le
entrega `EntityResolution`. Lo que el motor hace es COMPROBAR que la identidad
que se le entrega es utilizable para escribir:

* que cada mencion del claim tiene resolucion;
* que la resolucion FIJA una identidad (`LINK_EXISTING`); las demas acciones
  (`CREATE_NEW`, `CREATE_PROVISIONAL`, `SPLIT`, `REVIEW`) son, por definicion,
  identidad no consolidada, y una identidad no consolidada no se escribe: va a
  revision. Aqui es donde se corta de raiz el patron "crear un nodo nuevo por
  cada error de ASR/OCR";
* que la entidad EXISTE en el snapshot del grafo (si no existe, el motor no
  tiene `expected_version` con el que anclar la escritura);
* que todas las menciones de un mismo rol resuelven a la MISMA entidad;
* que sujeto y objeto no son la misma entidad (el contrato de `FactAssertion`
  prohibe la auto-relacion, asi que es una invalidez demostrable).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..contracts.claim import ClaimProposal
from ..contracts.resolution import EntityResolution
from . import findings as F
from .config import EngineConfig
from .snapshot import GraphSnapshot

#: Unica accion que consolida una identidad ya existente en el grafo.
SETTLED_ACTION = "LINK_EXISTING"

#: Acciones que significan "identidad todavia no consolidada".
UNSETTLED_ACTIONS = {
    "CREATE_PROVISIONAL": F.ENTITY_PROVISIONAL,
    "CREATE_NEW": F.ENTITY_RESOLUTION_DEFERRED,
    "SPLIT": F.ENTITY_RESOLUTION_DEFERRED,
    "REVIEW": F.ENTITY_RESOLUTION_DEFERRED,
}


@dataclass
class ResolutionIndex:
    """Resoluciones indexadas por mencion."""

    by_mention: dict[str, EntityResolution]

    @classmethod
    def build(cls, resolutions: Iterable[EntityResolution]) -> "ResolutionIndex":
        by_mention: dict[str, EntityResolution] = {}
        for resolution in resolutions:
            for mention_id in resolution.mention_ids:
                by_mention[mention_id] = resolution
        return cls(by_mention=by_mention)

    def of(self, mention_id: str) -> Optional[EntityResolution]:
        return self.by_mention.get(mention_id)


@dataclass(frozen=True)
class Role:
    """Resultado del eje para un extremo de la relacion."""

    entity_id: Optional[str]
    entity_type: Optional[str]
    confidence: float


@dataclass(frozen=True)
class IdentityOutcome:
    subject: Role
    object: Role
    findings: tuple[F.Finding, ...]


def _role(
    label: str,
    mention_ids: list[str],
    index: ResolutionIndex,
    snapshot: GraphSnapshot,
    config: EngineConfig,
    out: list[F.Finding],
) -> Role:
    entity_ids: set[str] = set()
    types: set[str] = set()
    confidences: list[float] = []
    settled = True

    for mention_id in mention_ids:
        resolution = index.of(mention_id)
        if resolution is None:
            out.append(F.UNRESOLVED_MENTION(f"{label}: mencion {mention_id} sin resolucion"))
            settled = False
            continue
        confidences.append(resolution.confidence)
        if resolution.entity_type:
            types.add(resolution.entity_type)
        if resolution.action != SETTLED_ACTION:
            out.append(
                UNSETTLED_ACTIONS.get(resolution.action, F.ENTITY_RESOLUTION_DEFERRED)(
                    f"{label}: {mention_id} resuelto como {resolution.action}"
                )
            )
            settled = False
            continue
        entity_id = resolution.entity_id()
        if entity_id is None:
            out.append(F.UNRESOLVED_MENTION(f"{label}: {mention_id} sin entidad asignada"))
            settled = False
            continue
        entity_ids.add(entity_id)
        if resolution.confidence < config.min_resolution_confidence:
            out.append(
                F.ENTITY_LOW_CONFIDENCE(
                    f"{label}: {entity_id} con {resolution.confidence} < "
                    f"{config.min_resolution_confidence}"
                )
            )
            settled = False

    if len(entity_ids) > 1:
        out.append(F.ENTITY_ROLE_AMBIGUOUS(f"{label}: {sorted(entity_ids)}"))
        return Role(None, None, 0.0)
    if not entity_ids or not settled:
        return Role(
            next(iter(entity_ids), None),
            next(iter(types), None) if len(types) == 1 else None,
            min(confidences, default=0.0),
        )

    entity_id = next(iter(entity_ids))
    node = snapshot.entity(entity_id)
    if node is None:
        out.append(F.ENTITY_NOT_IN_SNAPSHOT(f"{label}: {entity_id} no existe en el snapshot"))
        return Role(entity_id, next(iter(types), None) if len(types) == 1 else None, 0.0)

    entity_type = next(iter(types)) if len(types) == 1 else node.entity_type
    if len(types) > 1:
        out.append(F.ENTITY_TYPE_UNKNOWN(f"{label}: tipos en conflicto {sorted(types)}"))
        entity_type = None
    elif types and node.entity_type != entity_type:
        out.append(
            F.ENTITY_TYPE_UNKNOWN(
                f"{label}: la resolucion dice {entity_type}, el grafo {node.entity_type}"
            )
        )
        entity_type = None
    return Role(entity_id, entity_type, min(confidences, default=0.0))


def resolve_identity(
    claim: ClaimProposal,
    index: ResolutionIndex,
    snapshot: GraphSnapshot,
    config: EngineConfig,
) -> IdentityOutcome:
    """Fija (o no) las dos identidades de un claim."""
    out: list[F.Finding] = []
    if claim.abstained:
        out.append(F.CLAIM_ABSTAINED_UPSTREAM("el extractor se abstuvo"))
        return IdentityOutcome(Role(None, None, 0.0), Role(None, None, 0.0), tuple(out))

    subject = _role("sujeto", claim.subject_mentions, index, snapshot, config, out)
    obj = _role("objeto", claim.object_mentions, index, snapshot, config, out)

    if subject.entity_id and subject.entity_id == obj.entity_id:
        out.append(F.SELF_RELATION(f"sujeto y objeto son {subject.entity_id}"))

    return IdentityOutcome(subject, obj, tuple(out))
