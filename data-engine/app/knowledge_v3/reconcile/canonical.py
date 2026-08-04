# -*- coding: utf-8 -*-
"""Claves canonicas conservadoras para reconciliacion textual."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from ..claim_metadata import ClaimSemanticMetadata
from ..contracts import ClaimProposal, EntityMention
from ..contracts.base import canonical_json, schema_validator, sha256_hash

RECONCILIATION_METADATA_KEY = "reconciliation"

_CLAIM_METADATA_SIGNATURE_FIELDS = (
    "abstention_reasons",
    "direction_unresolved",
    "negation_kind",
    "temporal_resolution_required",
    "temporal_codes",
)


@dataclass(frozen=True, order=True)
class MentionKey:
    workspace: str
    source_asset_id: str
    source_hash: str
    episode_id: str
    offset_basis: str
    offset_fragment_id: str
    start: int
    end: int
    normalized_surface: str

    def hash_id(self, prefix: str) -> str:
        return _hash_id(prefix, self)


@dataclass(frozen=True, order=True)
class ClaimKey:
    workspace: str
    source_asset_id: str
    source_hash: str
    episode_id: str
    subject_mentions: tuple[str, ...]
    object_mentions: tuple[str, ...]
    evidence_fragment_ids: tuple[str, ...]
    relation_phrase: str
    negated: bool
    negation_kind: str
    epistemic_status_hint: str
    epistemic_cues: tuple[str, ...]
    temporal_expressions: str
    qualifiers: str
    abstained: bool
    review_required: bool
    metadata_signature: str

    def hash_id(self, prefix: str) -> str:
        return _hash_id(prefix, self)


@dataclass(frozen=True, order=True)
class CoreferentClaimKey:
    """Clave GRUESA: "estas propuestas hablan de la MISMA relacion".

    `ClaimKey` es deliberadamente estricta -- incluye la frase de relacion, la
    evidencia y la firma de metadatos -- porque agrupa propuestas IDENTICAS. Eso
    deja pasar un caso que solo aparece cuando se unen dos extractores: el
    determinista y el semantico proponen la MISMA relacion (mismo episodio,
    mismas menciones de sujeto y objeto) con distinta redaccion, y la union
    entrega DOS propuestas donde el texto sostiene UNA.

    Esta clave no mira la frase ni el predicado a proposito. El predicado NO
    forma parte de ella: si dos extractores discrepan sobre el, la salida
    correcta es una propuesta con los dos `predicate_candidates` ordenados -- que
    es justo lo que hace `_merge_claims` -- y no dos propuestas que el motor
    tendria que desempatar sin saber que hablan de lo mismo.

    Si se distinguen `negated` y `abstained`: una abstencion y una asercion
    sobre el mismo par NO son la misma propuesta, y fundirlas perderia la
    abstencion.
    """

    workspace: str
    source_asset_id: str
    source_hash: str
    episode_id: str
    subject_mentions: tuple[str, ...]
    object_mentions: tuple[str, ...]
    negated: bool
    abstained: bool

    def hash_id(self, prefix: str) -> str:
        return _hash_id(prefix, self)


def _hash_id(prefix: str, key: object) -> str:
    digest = sha256_hash(asdict(key))["value"][:16]
    return f"{prefix}:{digest}"


def _source_hash_value(value: dict) -> str:
    return canonical_json(value or {})


def _metadata(doc) -> dict:
    return dict(getattr(doc, "metadata", None) or {})


def without_reconciliation_metadata(metadata: dict | None) -> dict:
    out = dict(metadata or {})
    out.pop(RECONCILIATION_METADATA_KEY, None)
    return out


def mention_key(mention: EntityMention) -> MentionKey:
    meta = _metadata(mention)
    basis = str(meta.get("offset_basis") or "")
    fragment_id = str(meta.get("offset_fragment_id") or "")
    if basis == "fragment" and not fragment_id:
        fragment_id = str((mention.evidence_fragment_ids or [""])[0])
    return MentionKey(
        workspace=mention.workspace,
        source_asset_id=mention.source_asset_id,
        source_hash=_source_hash_value(mention.source_hash),
        episode_id=mention.episode_id,
        offset_basis=basis,
        offset_fragment_id=fragment_id,
        start=int(mention.start),
        end=int(mention.end),
        normalized_surface=str(mention.normalized_surface or ""),
    )


def claim_key(claim: ClaimProposal) -> ClaimKey:
    meta = _metadata(claim)
    semantic_meta = ClaimSemanticMetadata.from_metadata(meta)
    return ClaimKey(
        workspace=claim.workspace,
        source_asset_id=claim.source_asset_id,
        source_hash=_source_hash_value(claim.source_hash),
        episode_id=claim.episode_id,
        subject_mentions=stable_unique(claim.subject_mentions),
        object_mentions=stable_unique(claim.object_mentions),
        evidence_fragment_ids=stable_unique(claim.evidence_fragment_ids),
        relation_phrase=str(claim.relation_phrase or "").strip().casefold(),
        negated=bool(claim.negated),
        negation_kind=semantic_meta.negation_kind if claim.negated else "",
        epistemic_status_hint=str(claim.epistemic_status_hint or ""),
        epistemic_cues=stable_unique(claim.epistemic_cues),
        temporal_expressions=canonical_sequence(claim.temporal_expressions),
        qualifiers=canonical_sequence(claim.qualifiers),
        abstained=bool(claim.abstained),
        review_required=bool(claim.review_required),
        metadata_signature=canonical_json(
            {k: meta.get(k) for k in _CLAIM_METADATA_SIGNATURE_FIELDS if k in meta}
        ),
    )


def coreferent_claim_key(claim: ClaimProposal) -> CoreferentClaimKey:
    """Clave gruesa de co-referencia de propuestas (ver `CoreferentClaimKey`)."""
    return CoreferentClaimKey(
        workspace=claim.workspace,
        source_asset_id=claim.source_asset_id,
        source_hash=_source_hash_value(claim.source_hash),
        episode_id=claim.episode_id,
        subject_mentions=stable_unique(claim.subject_mentions),
        object_mentions=stable_unique(claim.object_mentions),
        negated=bool(claim.negated),
        abstained=bool(claim.abstained),
    )


def canonical_sequence(items: Iterable[Any]) -> str:
    return canonical_json(sorted((canonical_json(i) for i in items or ())))


def stable_unique(items: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({str(item) for item in items or ()}))


def canonical_trace(trace: Iterable[dict]) -> list[dict]:
    """Traza contractual sin steps duplicados; los duplicados viven en metadata."""
    by_step: dict[str, dict] = {}
    for entry in trace or ():
        step = str(entry.get("step") or "")
        if not step:
            continue
        current = by_step.get(step)
        if current is None or canonical_json(entry) < canonical_json(current):
            by_step[step] = dict(entry)
    return [by_step[k] for k in sorted(by_step)]


def sort_type_candidates(items: Iterable[dict]) -> list[dict]:
    by_type: dict[str, float] = {}
    for item in items or ():
        entity_type = str(item.get("type") or "")
        if not entity_type:
            continue
        confidence = float(item.get("confidence", 0.0))
        by_type[entity_type] = max(confidence, by_type.get(entity_type, 0.0))
    return [
        {"type": entity_type, "confidence": confidence}
        for entity_type, confidence in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def sort_predicate_candidates(items: Iterable[dict]) -> list[dict]:
    by_predicate: dict[str, float] = {}
    for item in items or ():
        predicate = str(item.get("predicate") or "")
        if not predicate:
            continue
        confidence = float(item.get("confidence", 0.0))
        by_predicate[predicate] = max(confidence, by_predicate.get(predicate, 0.0))
    out = [
        {"predicate": predicate, "confidence": confidence}
        for predicate, confidence in by_predicate.items()
    ]
    out.sort(key=schema_validator.predicate_sort_key)
    return out


def sort_direction_candidates(items: Iterable[dict]) -> list[dict]:
    by_direction: dict[str, float] = {}
    for item in items or ():
        direction = str(item.get("direction") or "")
        if not direction:
            continue
        confidence = float(item.get("confidence", 0.0))
        by_direction[direction] = max(confidence, by_direction.get(direction, 0.0))
    out = [
        {"direction": direction, "confidence": confidence}
        for direction, confidence in by_direction.items()
    ]
    out.sort(key=schema_validator.direction_sort_key)
    return out


def sort_alternatives(items: Iterable[dict]) -> list[dict]:
    by_key: dict[tuple[str, str, str], dict] = {}
    for item in items or ():
        predicate = str(item.get("predicate") or "")
        direction = str(item.get("direction") or "")
        reasons = tuple(sorted(str(c) for c in item.get("reason_codes") or ()))
        key = (predicate, direction, canonical_json(reasons))
        current = by_key.get(key)
        if current is None or float(item.get("confidence", 0.0)) > float(
            current.get("confidence", 0.0)
        ):
            out = {
                "predicate": predicate,
                "direction": direction,
                "confidence": float(item.get("confidence", 0.0)),
            }
            if reasons:
                out["reason_codes"] = list(reasons)
            by_key[key] = out
    out = list(by_key.values())
    out.sort(key=schema_validator.alternative_sort_key)
    return out


def mention_sort_key(mention: EntityMention) -> tuple:
    key = mention_key(mention)
    return (
        key.workspace,
        key.source_asset_id,
        key.episode_id,
        key.start,
        key.end,
        key.normalized_surface,
        mention.produced_by_step,
        mention.mention_id,
    )


def claim_sort_key(claim: ClaimProposal) -> tuple:
    key = claim_key(claim)
    predicates = tuple(c.get("predicate") for c in claim.predicate_candidates)
    return (
        key.workspace,
        key.source_asset_id,
        key.episode_id,
        key.evidence_fragment_ids,
        key.subject_mentions,
        predicates,
        key.object_mentions,
        key.negated,
        key.negation_kind,
        key.epistemic_status_hint,
        key.temporal_expressions,
        claim.claim_id,
    )


__all__ = [
    "ClaimKey",
    "CoreferentClaimKey",
    "MentionKey",
    "RECONCILIATION_METADATA_KEY",
    "canonical_sequence",
    "canonical_trace",
    "claim_key",
    "claim_sort_key",
    "coreferent_claim_key",
    "mention_key",
    "mention_sort_key",
    "sort_alternatives",
    "sort_direction_candidates",
    "sort_predicate_candidates",
    "sort_type_candidates",
    "stable_unique",
    "without_reconciliation_metadata",
]
