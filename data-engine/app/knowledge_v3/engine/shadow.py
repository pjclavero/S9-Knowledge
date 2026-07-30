# -*- coding: utf-8 -*-
"""Evaluacion semantica en sombra: datos de metricas, nunca planes."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from ..contracts import ClaimProposal
from . import findings as F
from .config import EngineConfig
from .decision import ClaimDecision, apply_batch_contradictions
from .ontology import ProfileIndex

IGNORED_FINDING = "EXTRACTOR_REQUESTED_REVIEW"
SEMANTIC_STEP = "extract.semantic"
SEMANTIC_FAMILIES = frozenset({"semantic-prompt-v1.2"})


def _is_semantic_origin(origin: Mapping[str, Any]) -> bool:
    """Recognise declared origins without guessing from provider/model names."""
    step = origin.get("step")
    family = origin.get("family") or origin.get("independent_family")
    return step == SEMANTIC_STEP or (
        isinstance(family, str) and family in SEMANTIC_FAMILIES
    )


def has_semantic_origin(claim: ClaimProposal) -> bool:
    """Whether a claim retains a declared semantic origin after reconciliation."""
    if claim.produced_by_step == SEMANTIC_STEP:
        return True
    if isinstance(claim.provider_trace, list) and any(
        isinstance(entry, Mapping) and _is_semantic_origin(entry)
        for entry in claim.provider_trace
    ):
        return True
    metadata = claim.metadata
    if not isinstance(metadata, Mapping):
        return False
    reconciliation = metadata.get("reconciliation")
    if not isinstance(reconciliation, Mapping):
        return False
    origins = reconciliation.get("origins")
    if not isinstance(origins, list):
        return False
    return any(
        isinstance(origin, Mapping) and _is_semantic_origin(origin)
        for origin in origins
    )


def _semantic_provider(claim: ClaimProposal) -> Mapping[str, Any] | None:
    candidates: list[Mapping[str, Any]] = []
    if isinstance(claim.provider_trace, list):
        candidates.extend(
            entry
            for entry in claim.provider_trace
            if isinstance(entry, Mapping) and _is_semantic_origin(entry)
        )
    reconciliation = (
        claim.metadata.get("reconciliation")
        if isinstance(claim.metadata, Mapping)
        else None
    )
    if isinstance(reconciliation, Mapping):
        candidates.extend(
            origin
            for origin in (reconciliation.get("origins") or ())
            if isinstance(origin, Mapping) and _is_semantic_origin(origin)
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            str(item.get("step") or ""),
            str(item.get("provider") or ""),
            str(item.get("name") or ""),
            str(item.get("model") or ""),
        ),
    )[0]


@dataclass(frozen=True)
class ShadowDecisionRecord:
    """Comparacion inerte. No contiene contratos ni operaciones aplicables."""

    claim_id: str
    effective_decision: str
    shadow_decision: str
    ignored_findings: tuple[str, ...]
    effective_findings: tuple[str, ...]
    shadow_findings: tuple[str, ...]
    would_emit_operations: bool
    operation_kinds: tuple[str, ...]
    provider: str
    model: str | None


def _eligible(claim: ClaimProposal, decision: ClaimDecision) -> bool:
    if not has_semantic_origin(claim) or claim.abstained or not claim.review_required:
        return False
    return bool(
        _semantic_provider(claim)
        and any(f.code == IGNORED_FINDING for f in decision.findings)
    )


def _operation_kinds(decision: ClaimDecision, config: EngineConfig) -> tuple[str, ...]:
    if not decision.writes:
        return ()
    kinds = ["CREATE_ASSERTION"]
    if decision.supersedes is not None:
        kinds.append("SUPERSEDE_ASSERTION")
    if config.emit_projection and not decision.negated:
        kinds.append("PROJECT_RELATION")
    return tuple(kinds)


def evaluate_semantic_shadow(
    claims: Sequence[ClaimProposal],
    effective: Sequence[ClaimDecision],
    pre_batch: Sequence[ClaimDecision],
    profile: ProfileIndex,
    config: EngineConfig,
) -> tuple[ShadowDecisionRecord, ...]:
    """Ignora un solo finding sobre copias y vuelve a aplicar contradicciones."""
    claim_by_id = {claim.claim_id: claim for claim in claims}
    copied: list[ClaimDecision] = []
    eligible_ids: set[str] = set()
    for decision in pre_batch:
        claim = claim_by_id[decision.claim_id]
        findings = list(decision.findings)
        if _eligible(claim, decision):
            findings = [f for f in findings if f.code != IGNORED_FINDING]
            eligible_ids.add(decision.claim_id)
        copied.append(
            replace(
                decision,
                findings=findings,
                decision=F.decision_for(findings),
                evidence_fragment_ids=list(decision.evidence_fragment_ids),
            )
        )
    shadow = apply_batch_contradictions(copied, profile)
    effective_by_id = {d.claim_id: d for d in effective}
    records: list[ShadowDecisionRecord] = []
    for decision in shadow:
        if decision.claim_id not in eligible_ids:
            continue
        claim = claim_by_id[decision.claim_id]
        origin = _semantic_provider(claim)
        if origin is None:
            continue
        actual = effective_by_id[decision.claim_id]
        kinds = _operation_kinds(decision, config)
        records.append(
            ShadowDecisionRecord(
                claim_id=decision.claim_id,
                effective_decision=actual.decision,
                shadow_decision=decision.decision,
                ignored_findings=(IGNORED_FINDING,),
                effective_findings=tuple(f.code for f in actual.findings),
                shadow_findings=tuple(f.code for f in decision.findings),
                would_emit_operations=bool(kinds),
                operation_kinds=kinds,
                provider=str(origin.get("provider") or "not_available"),
                model=origin.get("model"),
            )
        )
    return tuple(records)


__all__ = ["ShadowDecisionRecord", "evaluate_semantic_shadow", "has_semantic_origin"]
