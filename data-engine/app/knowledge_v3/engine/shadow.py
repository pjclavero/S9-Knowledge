# -*- coding: utf-8 -*-
"""Evaluacion semantica en sombra: datos de metricas, nunca planes."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from ..contracts import ClaimProposal
from . import findings as F
from .config import EngineConfig
from .decision import ClaimDecision, apply_batch_contradictions
from .ontology import ProfileIndex

IGNORED_FINDING = "EXTRACTOR_REQUESTED_REVIEW"
SEMANTIC_STEP = "extract.semantic"


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
    if claim.produced_by_step != SEMANTIC_STEP or claim.abstained or not claim.review_required:
        return False
    try:
        origin = claim.producing_provider()
    except Exception:  # el contrato se valido antes; defensa fail-closed
        return False
    return bool(
        origin.get("provider")
        and origin.get("name")
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
        origin = claim.producing_provider()
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
                provider=str(origin["provider"]),
                model=origin.get("model"),
            )
        )
    return tuple(records)


__all__ = ["ShadowDecisionRecord", "evaluate_semantic_shadow"]
