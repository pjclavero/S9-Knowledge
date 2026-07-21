# -*- coding: utf-8 -*-
"""Orquestador del motor hibrido por etapas (PR#95 V4).

Compone las etapas puras de `stages.py` en un flujo DESACTIVABLE por flags. El
DEFAULT de todos los flags reproduce EXACTAMENTE la base: con `hybrid_stages={}`
(o cualquier dict que deje las etapas en su valor por defecto) y `top_k<=0`,
`build_candidate_records_staged` produce candidatos byte-identicos a los del
camino clasico del pipeline.

Decoplado: NO importa `relations.pipeline`. Todas las piezas de la base
(funciones heuristicas, maps, constructor de candidato, proveedores, consenso)
se inyectan via `StageDeps`. Asi se REUTILIZA la logica existente sin
reimplementarla y sin import circular.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from relations.contracts import Direction, EpistemicStatus, ExtractionMethod
from relations.hybrid import stages as _st

# Flags de etapa y su DEFAULT (True = reproduce la base). La etapa de ranking de
# menciones se gobierna aparte, por `top_k` (0 = desactivada = base).
STAGE_DEFAULTS: dict[str, bool] = {
    "structural_hypothesis": True,
    "predicate_direction": True,
    "evidence": True,
    "verification": True,
    "temporal_epistemic": True,
    "consensus": True,
}
STAGE_NAMES = tuple(STAGE_DEFAULTS.keys()) + ("mention_ranking",)


class HybridConfigError(ValueError):
    """Configuracion de etapas invalida."""


def resolve_stages(hybrid_stages: Optional[dict]) -> dict:
    """Normaliza el dict de flags a booleanos, aplicando defaults base.

    `None` no deberia llegar aqui (lo intercepta el pipeline: None = camino
    clasico). `{}` => todos los defaults => base. Claves desconocidas => error
    (fail-closed, no se silencian typos que desactivarian una etapa por sorpresa).
    """
    flags = dict(STAGE_DEFAULTS)
    data = dict(hybrid_stages or {})
    unknown = set(data) - set(STAGE_DEFAULTS) - {"mention_ranking"}
    if unknown:
        raise HybridConfigError(f"etapas desconocidas: {sorted(unknown)}; validas: {sorted(STAGE_NAMES)}")
    for k in STAGE_DEFAULTS:
        if k in data:
            v = data[k]
            if not isinstance(v, bool):
                raise HybridConfigError(f"flag de etapa {k!r} debe ser bool, no {type(v).__name__}")
            flags[k] = v
    return flags


@dataclass(frozen=True)
class StageDeps:
    """Dependencias inyectadas desde el pipeline (reutilizacion, no reimplantacion)."""

    signal_map: Callable[[Any], dict]
    confidence: Callable[[dict], float]
    choose_predicate: Callable[[dict], str]
    dir_by_pred: dict
    temporal_scope: Callable[[dict], Any]
    epistemic_status: Callable[[dict], EpistemicStatus]
    build_signals: Callable[..., list]      # compute_all_signals wrapper (pair, seg_text)->signals
    candidate_key: Callable[[str, Any], str]
    run_local: Callable[..., tuple]
    run_external: Callable[..., tuple]
    compute_consensus: Callable[..., Any]
    candidate_cls: Any                       # RelationCandidate
    candidate_build_error: Any               # _CandidateBuildError
    provider_executed: str
    provider_failed_closed: str
    state_counter: dict                      # consensus state -> summary counter key


def build_candidate_records_staged(
    pairs: list,
    seg_text: str,
    syntax_analysis: Any,
    workspace: str,
    config: Any,
    ctx: Any,
    summary: dict,
    errors: list,
    seen_candidates: set,
    deps: StageDeps,
) -> list:
    """Produce los `candidate_records` de un segmento via el motor por etapas.

    Reemplaza el bucle `for pair in pairs: _process_pair(...)` del pipeline SOLO
    cuando el modo hibrido esta activo. Con `top_k<=0` y etapas en default, el
    resultado es byte-identico al del camino clasico.
    """
    flags = resolve_stages(config.hybrid_stages)
    top_k = int(getattr(config, "hybrid_top_k", 0) or 0)

    # --- Paso 1: senales + hipotesis para TODOS los pares (orden base) ---
    # Las senales se registran para todos los pares (igual que la base), de modo
    # que la salida de senales del segmento no cambia; el top-k solo acota los
    # CANDIDATOS, nunca las senales ni los pares.
    prepared: list[tuple] = []  # (pair, sigmap, signals, hypothesis)
    for pair in pairs:
        try:
            signals = deps.build_signals(pair, seg_text)
        except Exception as exc:  # noqa: BLE001 - offsets fuera de rango, etc.
            errors.append({
                "code": "signal_error",
                "message": f"{type(exc).__name__}: {exc}",
                "pair_id": pair.pair_id,
                "fatal_for_segment": False,
            })
            continue
        ctx.register_signals(pair.pair_id, signals)
        sigmap = deps.signal_map(signals)
        hyp = _st.stage_hypothesis(pair, sigmap, deps.confidence)
        if not flags["structural_hypothesis"]:
            # Etapa desactivada: sin scoring estructural (score neutro). Solo afecta
            # al ranking top-k; el candidato final no depende del score.
            hyp = _st.RelationHypothesis(
                pair_id=hyp.pair_id, subject_id=hyp.subject_id, object_id=hyp.object_id,
                subject_type=hyp.subject_type, object_type=hyp.object_type,
                subject_start=hyp.subject_start, subject_end=hyp.subject_end,
                object_start=hyp.object_start, object_end=hyp.object_end,
                predicate=hyp.predicate, direction=hyp.direction, score=0.0,
                reasoning=hyp.reasoning + ("etapa hipotesis estructural DESACTIVADA",),
            )
        prepared.append((pair, sigmap, signals, hyp))

    # --- Paso 2: ranking / top-k (anti-explosion de candidatos) ---
    hyps = [p[3] for p in prepared]
    kept_hyps, _truncated = _st.stage_rank_mentions(hyps, top_k)
    kept_ids = {h.pair_id for h in kept_hyps}
    prepared = [p for p in prepared if p[0].pair_id in kept_ids]

    # --- Paso 3..7: por cada hipotesis conservada, completar y construir ---
    records: list[dict] = []
    for pair, sigmap, signals, hyp in prepared:
        hyp = _st.stage_predicate_direction(
            hyp, sigmap,
            enabled=flags["predicate_direction"],
            choose_predicate=deps.choose_predicate,
            dir_by_pred=deps.dir_by_pred,
        )
        bundle = _st.stage_evidence(hyp, seg_text, enabled=flags["evidence"])
        bundle, ok, reason = _st.stage_verification(bundle, enabled=flags["verification"])
        if not ok:
            errors.append({
                "code": reason or "evidence_rejected",
                "message": "evidencia rechazada por la etapa de verificacion",
                "pair_id": pair.pair_id,
                "fatal_for_segment": False,
            })
            continue

        temporal, epistemic, _why = _st.stage_temporal_epistemic(
            sigmap,
            enabled=flags["temporal_epistemic"],
            temporal_fn=deps.temporal_scope,
            epistemic_fn=deps.epistemic_status,
        )

        try:
            candidate = deps.candidate_cls(
                subject_id=pair.subject_id,
                subject_type=pair.subject_type,
                predicate=hyp.predicate,
                object_id=pair.object_id,
                object_type=pair.object_type,
                direction=Direction(hyp.direction),
                confidence=deps.confidence(sigmap),
                evidence_text=bundle.evidence_text,
                evidence_start=bundle.evidence_start,
                evidence_end=bundle.evidence_end,
                source_id=pair.source_id,
                source_page=pair.source_page,
                source_segment=pair.source_segment,
                extraction_method=ExtractionMethod.HEURISTIC,
                model=None,
                negated=bool(sigmap.get("negation")),
                temporal_scope=temporal,
                epistemic_status=epistemic,
                workspace=workspace,
                validation_flags=["dry_run", "heuristic"],
            )
            candidate.validate()
        except Exception as exc:  # noqa: BLE001 - contrato invalido, aislado
            errors.append({
                "code": "contract_invalid",
                "message": str(exc),
                "pair_id": pair.pair_id,
                "fatal_for_segment": False,
            })
            continue

        ckey = deps.candidate_key(workspace, candidate)
        if ckey in seen_candidates:
            continue
        seen_candidates.add(ckey)
        summary["candidates_evaluated"] += 1

        local_rec, local_status = deps.run_local(candidate, pair, seg_text, config, ctx)
        external_eval, external_status = deps.run_external(candidate, config, ctx, seg_text)
        if local_status == deps.provider_executed:
            summary["local_calls_simulated"] += 1
        if external_status == deps.provider_executed:
            summary["external_calls_simulated"] += 1
        if local_status == deps.provider_failed_closed:
            summary["provider_fail_closed"] += 1
        if external_status == deps.provider_failed_closed:
            summary["provider_fail_closed"] += 1

        if flags["consensus"]:
            consensus = deps.compute_consensus(
                candidate, signals=signals, syntax=syntax_analysis,
                local=local_rec, external=external_eval,
            )
            counter_state = consensus.state
            consensus_dict = consensus.to_dict()
        else:
            counter_state = None
            consensus_dict = None
        if counter_state is not None:
            counter = deps.state_counter.get(counter_state)
            if counter:
                summary[counter] += 1

        records.append({
            "candidate_id": ckey,
            "pair_id": pair.pair_id,
            "candidate": candidate.to_dict(),
            "consensus": consensus_dict,
            "local": local_rec.to_dict() if local_rec is not None else None,
            "local_status": local_status,
            "external": external_eval.to_dict() if external_eval is not None else None,
            "external_status": external_status,
        })

    return records


__all__ = [
    "STAGE_DEFAULTS",
    "STAGE_NAMES",
    "HybridConfigError",
    "resolve_stages",
    "StageDeps",
    "build_candidate_records_staged",
]
