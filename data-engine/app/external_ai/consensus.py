# -*- coding: utf-8 -*-
"""Motor de consenso entre dos revisores de modelo (shadow mode).

Las shadow_recommendation NUNCA activan decisiones productivas.
Nada escribe en Neo4j.
"""
from __future__ import annotations

from external_ai.models import (
    STRONG_CONSENSUS,
    PARTIAL_CONSENSUS,
    MODEL_CONFLICT,
    INVALID_RESPONSES,
    HUMAN_REQUIRED,
    ModelReviewResponse,
    ModelReviewDecision,
    ConsensusResult,
    ReviewBatchRequest,
)

# Decisiones que implican "aceptar" la entidad (polarity positiva).
_ACCEPTING = frozenset({"accept", "edit", "use_existing"})


def _norm_name(name: str | None) -> str | None:
    """Normaliza canonical_name para comparación (strip + lower)."""
    if name is None:
        return None
    cleaned = name.strip().lower()
    return cleaned if cleaned else None


def compute_consensus(
    response_a: ModelReviewResponse,
    response_b: ModelReviewResponse,
    request: ReviewBatchRequest,
    adjudicate_fn=None,
) -> list[ConsensusResult]:
    """Calcula el consenso entre dos revisores para cada candidato del lote.

    Parámetros
    ----------
    response_a, response_b:
        Respuestas validadas de los dos revisores.
    request:
        Lote original con la lista canónica de candidate_id a procesar.
    adjudicate_fn:
        Callable opcional ``(candidate_id: str) -> ModelReviewDecision | None``.
        Solo se invoca en estado MODEL_CONFLICT.

    Retorna
    -------
    Lista de ConsensusResult, uno por candidate_id en request.items.
    """
    by_a = response_a.by_candidate()
    by_b = response_b.by_candidate()

    results: list[ConsensusResult] = []

    for item in request.items:
        cid = item.candidate_id
        da: ModelReviewDecision | None = by_a.get(cid)
        db: ModelReviewDecision | None = by_b.get(cid)

        # ------------------------------------------------------------------
        # Comprobación de validez individual de cada decisión
        # ------------------------------------------------------------------
        # Validez POR CANDIDATO: si la decisión está presente ya pasó validación
        # del parser; un candidato inválido no debe anular al resto del lote.
        a_invalid = da is None
        b_invalid = db is None

        if a_invalid or b_invalid:
            missing = []
            if a_invalid:
                missing.append("reviewer_a")
            if b_invalid:
                missing.append("reviewer_b")
            results.append(ConsensusResult(
                candidate_id=cid,
                state=INVALID_RESPONSES,
                shadow_recommendation="human",
                reviewer_a=da.to_dict() if da is not None else None,
                reviewer_b=db.to_dict() if db is not None else None,
                reason=f"Decisión ausente o respuesta inválida en: {', '.join(missing)}",
            ))
            continue

        # A partir de aquí, da y db son ModelReviewDecision válidas.
        decision_a = da.decision
        decision_b = db.decision

        # ------------------------------------------------------------------
        # Ambos incertidumbre → HUMAN_REQUIRED
        # ------------------------------------------------------------------
        if decision_a == "uncertain" and decision_b == "uncertain":
            results.append(ConsensusResult(
                candidate_id=cid,
                state=HUMAN_REQUIRED,
                shadow_recommendation="human",
                reviewer_a=da.to_dict(),
                reviewer_b=db.to_dict(),
                reason="Ambos revisores reportan 'uncertain'.",
            ))
            continue

        # ------------------------------------------------------------------
        # Precondiciones para STRONG_CONSENSUS
        # ------------------------------------------------------------------
        name_a = _norm_name(da.canonical_name)
        name_b = _norm_name(db.canonical_name)
        same_decision = decision_a == decision_b
        same_name = name_a == name_b          # None == None es True
        same_type = da.entity_type == db.entity_type
        both_have_evidence = bool(da.evidence and da.evidence.strip()) and \
                             bool(db.evidence and db.evidence.strip())

        # Conflicto de merged duplicado: ambos use_existing pero apuntan a
        # entidades distintas → no es strong consensus.
        use_existing_conflict = (
            decision_a == "use_existing"
            and decision_b == "use_existing"
            and da.matched_existing != db.matched_existing
        )

        if (
            same_decision
            and same_name
            and same_type
            and both_have_evidence
            and not use_existing_conflict
        ):
            results.append(ConsensusResult(
                candidate_id=cid,
                state=STRONG_CONSENSUS,
                shadow_recommendation=decision_a,
                reviewer_a=da.to_dict(),
                reviewer_b=db.to_dict(),
                reason="Acuerdo total en decisión, nombre canónico, tipo y evidencia.",
            ))
            continue

        # ------------------------------------------------------------------
        # PARTIAL_CONSENSUS: misma polaridad pero difieren en detalles
        # ------------------------------------------------------------------
        a_accepting = decision_a in _ACCEPTING
        b_accepting = decision_b in _ACCEPTING
        a_rejecting = decision_a == "reject"
        b_rejecting = decision_b == "reject"

        same_polarity_accept = a_accepting and b_accepting
        same_polarity_reject = a_rejecting and b_rejecting

        if same_polarity_accept or same_polarity_reject:
            if same_polarity_accept:
                # Si aceptan pero difieren en canonical/tipo → recomendar edit
                if not same_name or not same_type:
                    shadow = "edit"
                else:
                    shadow = decision_a
            else:
                shadow = decision_a  # ambos rechazan

            results.append(ConsensusResult(
                candidate_id=cid,
                state=PARTIAL_CONSENSUS,
                shadow_recommendation=shadow,
                reviewer_a=da.to_dict(),
                reviewer_b=db.to_dict(),
                reason=(
                    "Misma polaridad pero difieren en nombre canónico, tipo, "
                    "matched_existing y/o confianza."
                ),
            ))
            continue

        # ------------------------------------------------------------------
        # MODEL_CONFLICT: polaridades opuestas o uno es uncertain
        # ------------------------------------------------------------------
        adj_dict = None
        shadow = "human"

        if adjudicate_fn is not None:
            adj: ModelReviewDecision | None = adjudicate_fn(cid)
            if adj is not None:
                adj_dict = adj.to_dict()
                shadow = adj.decision

        results.append(ConsensusResult(
            candidate_id=cid,
            state=MODEL_CONFLICT,
            shadow_recommendation=shadow,
            reviewer_a=da.to_dict(),
            reviewer_b=db.to_dict(),
            adjudication=adj_dict,
            reason=(
                "Conflicto de polaridad entre revisores "
                f"(a={decision_a}, b={decision_b})."
            ),
        ))

    return results


def needs_adjudication(state: str) -> bool:
    """Retorna True si el estado requiere adjudicación (MODEL_CONFLICT)."""
    return state == MODEL_CONFLICT


def summarize(results: list[ConsensusResult]) -> dict:
    """Estadísticas agregadas del resultado del motor de consenso.

    Retorna
    -------
    dict con conteos por estado y tasas derivadas.
    """
    total = len(results)
    counts: dict[str, int] = {
        STRONG_CONSENSUS: 0,
        PARTIAL_CONSENSUS: 0,
        MODEL_CONFLICT: 0,
        INVALID_RESPONSES: 0,
        HUMAN_REQUIRED: 0,
    }

    for r in results:
        counts[r.state] = counts.get(r.state, 0) + 1

    strong = counts[STRONG_CONSENSUS]
    conflict = counts[MODEL_CONFLICT]
    partial = counts[PARTIAL_CONSENSUS]
    human_req = counts[HUMAN_REQUIRED]
    invalid = counts[INVALID_RESPONSES]

    def _rate(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    return {
        "total": total,
        "by_state": counts,
        "strong_consensus_coverage": _rate(strong),
        "conflict_rate": _rate(conflict),
        "partial_rate": _rate(partial),
        "human_required": _rate(human_req),
        "invalid": _rate(invalid),
        "shadow_mode": True,
    }
