# -*- coding: utf-8 -*-
"""Adaptador V3 -> `relation-candidate/internal-v1`.

`relation-candidate/internal-v1` (`relations/contracts.py`, 20 campos, contrato
CERRADO) es la unica frontera que consume el resto del sistema y es INTOCABLE.
Este modulo es el puente: convierte un `ClaimProposal` V3 de tipo relacion en un
`RelationCandidate` v1 valido, sin modificar ni un byte del contrato v1.

Direccion del puente: V3 -> v1, y solo eso. No existe conversion inversa: v1
tiene estrictamente menos informacion y reconstruirla seria inventarla.

Perdidas de informacion, explicitas y documentadas
--------------------------------------------------
v1 no tiene sitio para varias cosas que V3 si modela. En vez de tirarlas en
silencio, cada una deja un `validation_flag` (el unico campo v1 abierto):

    V3_ADAPTED                  siempre; marca el origen del candidato
    V3_MULTIPLE_PREDICATES      habia mas de un predicado candidato
    V3_HAS_ALTERNATIVES         habia lecturas alternativas
    V3_VISUAL_INFERRED          epistemic_status_hint=VISUAL_INFERRED, que no
                                existe en v1 y se degrada a HYPOTHETICAL
    V3_CONFLICTED               epistemic_status_hint=CONFLICTED (no existe en v1)
    V3_UNKNOWN_EPISTEMIC        epistemic_status_hint=UNKNOWN (no existe en v1)
    V3_EXTERNAL_PROVIDER        lo produjo un proveedor externo
    V3_REVIEW_REQUIRED          el claim exigia revision humana
    V3_MULTI_MENTION_SUBJECT    el sujeto agrupaba varias menciones
    V3_MULTI_MENTION_OBJECT     el objeto agrupaba varias menciones
    V3_PROVISIONAL_SUBJECT      el sujeto es una entidad provisional
    V3_PROVISIONAL_OBJECT       el objeto es una entidad provisional
"""
from __future__ import annotations

from typing import Optional

from relations.contracts import (
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
    normalize_predicate,
)

from ..contracts import (
    ClaimProposal,
    EntityResolution,
    EvidenceFragment,
    ResolutionAction,
    V3ContractError,
)


class V3AdapterError(V3ContractError):
    """El claim V3 no puede convertirse en un `relation-candidate/internal-v1`."""


#: `provider` de V3 -> `extraction_method` de v1. v1 solo conoce cuatro metodos:
#: 'external' se proyecta sobre NVIDIA (el unico externo que v1 contempla) y se
#: marca con el flag V3_EXTERNAL_PROVIDER para no perder el matiz.
_PROVIDER_TO_METHOD = {
    "local": ExtractionMethod.HEURISTIC,
    "ollama": ExtractionMethod.LLM_LOCAL,
    "external": ExtractionMethod.NVIDIA,
}

#: `epistemic_status_hint` de V3 -> `epistemic_status` de v1.
#: VISUAL_INFERRED no existe en v1: se degrada al valor mas conservador que v1
#: admite (HYPOTHETICAL) y deja constancia por flag.
_STATUS_MAP = {
    "ASSERTED": EpistemicStatus.ASSERTED,
    "RUMORED": EpistemicStatus.RUMORED,
    "HYPOTHETICAL": EpistemicStatus.HYPOTHETICAL,
    "INTENDED": EpistemicStatus.INTENDED,
    # Los tres siguientes NO existen en v1. Se degradan al valor mas
    # conservador que v1 admite, y cada uno deja su propio flag.
    "VISUAL_INFERRED": EpistemicStatus.HYPOTHETICAL,
    "CONFLICTED": EpistemicStatus.HYPOTHETICAL,
    "UNKNOWN": EpistemicStatus.HYPOTHETICAL,
}

#: Pistas epistemicas sin equivalente en v1 -> flag que deja constancia.
_STATUS_FLAG = {
    "VISUAL_INFERRED": "V3_VISUAL_INFERRED",
    "CONFLICTED": "V3_CONFLICTED",
    "UNKNOWN": "V3_UNKNOWN_EPISTEMIC",
}


def entity_id_from_resolution(resolution: EntityResolution) -> str:
    """Identificador de entidad fijado por una `EntityResolution`.

    Sale de `selected_entity_id` (LINK_EXISTING) o de `assigned_entity_id`
    (CREATE_NEW / CREATE_PROVISIONAL): quien crea la identidad es quien la
    nombra. El adaptador NO fabrica identificadores por convencion de cadena.
    `REVIEW` y `SPLIT` no fijan identidad: no hay nada que adaptar.
    """
    action = resolution.action
    if action in (ResolutionAction.REVIEW.value, ResolutionAction.SPLIT.value):
        raise V3AdapterError(
            f"la resolucion {resolution.resolution_id} con action={action} no fija identidad"
        )
    entity_id = resolution.entity_id()
    if not entity_id:
        raise V3AdapterError(
            f"la resolucion {resolution.resolution_id} no declara identificador de entidad"
        )
    return entity_id


def claim_to_relation_candidate(
    claim: ClaimProposal,
    evidence: EvidenceFragment,
    *,
    subject_entity_id: str,
    object_entity_id: str,
    subject_type: Optional[str] = None,
    object_type: Optional[str] = None,
    subject_provisional: bool = False,
    object_provisional: bool = False,
    validate: bool = True,
) -> RelationCandidate:
    """Convierte un `ClaimProposal` V3 en un `RelationCandidate` v1 valido.

    `evidence` debe ser uno de los fragmentos citados por el claim: los offsets
    del candidato v1 salen de ahi, no se recalculan ni se inventan.
    """
    _check_claim_is_relational(claim)
    _check_evidence_matches(claim, evidence)

    if not subject_entity_id or not object_entity_id:
        raise V3AdapterError("subject_entity_id y object_entity_id son obligatorios")
    if subject_entity_id == object_entity_id:
        raise V3AdapterError(
            "sujeto y objeto resuelven a la misma entidad: no es una relacion"
        )

    predicate = normalize_predicate(claim.predicate_candidates[0]["predicate"])
    direction = Direction(claim.best_direction())
    method = _extraction_method(claim)

    candidate = RelationCandidate(
        subject_id=subject_entity_id,
        subject_type=subject_type,
        predicate=predicate,
        object_id=object_entity_id,
        object_type=object_type,
        direction=direction,
        confidence=claim.confidence,
        evidence_text=evidence.literal_text,
        evidence_start=evidence.start,
        evidence_end=evidence.end,
        source_id=claim.source_asset_id,
        source_page=evidence.page,
        source_segment=claim.episode_id,
        extraction_method=method,
        model=_model_of(claim),
        negated=claim.negated,
        temporal_scope=(claim.temporal_expressions or None),
        epistemic_status=_STATUS_MAP[claim.epistemic_status_hint],
        workspace=claim.workspace,
        validation_flags=_flags(claim, subject_provisional, object_provisional),
    )
    if validate:
        candidate.validate()
    return candidate


def claim_with_resolutions_to_relation_candidate(
    claim: ClaimProposal,
    evidence: EvidenceFragment,
    subject_resolution: EntityResolution,
    object_resolution: EntityResolution,
    *,
    validate: bool = True,
) -> RelationCandidate:
    """Igual que `claim_to_relation_candidate`, tomando las identidades de sus
    `EntityResolution` (que es de donde deben salir en el pipeline real)."""
    for res, label in ((subject_resolution, "sujeto"), (object_resolution, "objeto")):
        if res.workspace != claim.workspace:
            raise V3AdapterError(
                f"la resolucion del {label} pertenece a otro workspace: "
                f"{res.workspace!r} != {claim.workspace!r}"
            )
    return claim_to_relation_candidate(
        claim,
        evidence,
        subject_entity_id=entity_id_from_resolution(subject_resolution),
        object_entity_id=entity_id_from_resolution(object_resolution),
        subject_type=subject_resolution.entity_type,
        object_type=object_resolution.entity_type,
        subject_provisional=subject_resolution.is_provisional(),
        object_provisional=object_resolution.is_provisional(),
        validate=validate,
    )


# --------------------------------------------------------------------------
# Internos
# --------------------------------------------------------------------------
def _check_claim_is_relational(claim: ClaimProposal) -> None:
    if claim.abstained:
        raise V3AdapterError("una abstencion no es un candidato de relacion")
    if not claim.predicate_candidates:
        raise V3AdapterError("el claim no propone ningun predicado")
    if not claim.subject_mentions or not claim.object_mentions:
        raise V3AdapterError("el claim no tiene sujeto y objeto")


def _check_evidence_matches(claim: ClaimProposal, evidence: EvidenceFragment) -> None:
    if evidence.fragment_id not in claim.evidence_fragment_ids:
        raise V3AdapterError(
            f"el fragmento {evidence.fragment_id} no es evidencia de {claim.claim_id}"
        )
    if evidence.workspace != claim.workspace:
        raise V3AdapterError(
            f"evidencia de otro workspace: {evidence.workspace!r} != {claim.workspace!r}"
        )
    if evidence.episode_id != claim.episode_id:
        raise V3AdapterError(
            f"evidencia de otro episodio: {evidence.episode_id!r} != {claim.episode_id!r}"
        )
    if evidence.source_hash != claim.source_hash:
        raise V3AdapterError("source_hash de la evidencia distinto del source_hash del claim")
    # v1 exige evidencia textual salvo metodo ONTOLOGY. Mejor un error propio y
    # explicito aqui que dejar escapar un RelationContractError ajeno desde
    # dentro del contrato v1: el fallo es del adaptador, no de v1.
    if not evidence.literal_text or not evidence.literal_text.strip():
        raise V3AdapterError(
            f"el fragmento {evidence.fragment_id} no tiene texto literal: "
            "sin evidencia textual no hay candidato de relacion"
        )


def _producing_entry(claim: ClaimProposal) -> dict:
    """Paso productor por referencia EXPLICITA (`produced_by_step`).

    No se adivina a partir de los nombres de `produced`: adivinarlo hacia que
    una salida de NVIDIA cuya traza dijese `produced=["predicate_candidates"]`
    acabase etiquetada HEURISTIC y sin V3_EXTERNAL_PROVIDER.
    """
    if not claim.provider_trace:
        raise V3AdapterError("el claim no tiene provider_trace: sin trazabilidad no se adapta")
    try:
        return claim.producing_provider()
    except V3ContractError as exc:
        raise V3AdapterError(str(exc)) from exc


def _extraction_method(claim: ClaimProposal) -> ExtractionMethod:
    provider = _producing_entry(claim).get("provider")
    method = _PROVIDER_TO_METHOD.get(provider)
    if method is None:
        raise V3AdapterError(f"provider desconocido en provider_trace: {provider!r}")
    return method


def _model_of(claim: ClaimProposal) -> Optional[str]:
    return _producing_entry(claim).get("model")


def _flags(claim: ClaimProposal, subject_provisional: bool, object_provisional: bool) -> list[str]:
    flags = {"V3_ADAPTED"}
    if len(claim.predicate_candidates) > 1:
        flags.add("V3_MULTIPLE_PREDICATES")
    if claim.alternatives:
        flags.add("V3_HAS_ALTERNATIVES")
    status_flag = _STATUS_FLAG.get(claim.epistemic_status_hint)
    if status_flag:
        flags.add(status_flag)
    if _producing_entry(claim).get("provider") == "external":
        flags.add("V3_EXTERNAL_PROVIDER")
    if claim.review_required:
        flags.add("V3_REVIEW_REQUIRED")
    if len(claim.subject_mentions) > 1:
        flags.add("V3_MULTI_MENTION_SUBJECT")
    if len(claim.object_mentions) > 1:
        flags.add("V3_MULTI_MENTION_OBJECT")
    if subject_provisional:
        flags.add("V3_PROVISIONAL_SUBJECT")
    if object_provisional:
        flags.add("V3_PROVISIONAL_OBJECT")
    # Orden estable: el candidato v1 debe serializarse igual siempre.
    return sorted(flags)
