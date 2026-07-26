# -*- coding: utf-8 -*-
"""Bloque 6 (motor de relaciones v2): CONSENSO, ABSTENCION Y RECHAZO JUSTIFICADO.

Tests REALES de `relations.abstention` y de su integracion en
`relations.consensus_adapter`, `relations.pipeline` y `relations.ensemble`.

Que se verifica aqui (y por que):

  * Que existe un camino a `reject` SIN proveedores (el techo mecanico que el
    diagnostico del bloque documento) y que ese camino esta JUSTIFICADO por
    evidencia contradictoria, no por bajar ningun umbral.
  * Que las senales del motor v2 (abstencion del selector de predicado, confianza
    de direccion, vigencia temporal, estado epistemico, negacion, tipos) LLEGAN a
    la decision y quedan como MOTIVOS ESTRUCTURADOS.
  * Que la incoherencia diagnosticada (recomendar `propose` con el predicado en
    abstencion) es IMPOSIBLE por construccion.
  * Que la puerta SOLO DEGRADA: no existe combinacion alguna de estado,
    recomendacion y veredicto que produzca `propose`, `STRONG_CONSENSUS` o una
    aprobacion que no estuviera ya ahi. Se comprueba EXHAUSTIVAMENTE.
  * Que el DEFAULT (politica v1) es el comportamiento historico, byte a byte.

Todas las entidades y frases son INVENTADAS (Marcus, Kael, Gorm, Ysera, la Cofradia
del Yunque...): NO son calcos del corpus de benchmark. Sin skip ni xfail.
"""
from __future__ import annotations

import itertools

import pytest

from external_ai.models import (
    CONSENSUS_STATES,
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)

from relations import abstention as A
from relations import ensemble as E
from relations import pipeline as P
from relations.consensus_adapter import (
    CONSENSUS_POLICIES,
    POLICY_V1,
    POLICY_V2,
    RECO_HUMAN,
    RECO_PROPOSE,
    RECO_REJECT,
    RELATION_RECOMMENDATIONS,
    _FORBIDDEN_RECOMMENDATIONS,
    compute_relation_consensus,
)
from relations.direction import LOW_CONFIDENCE_THRESHOLD, REVIEW_DIRECTION_FLAG
from relations.predicate_selector import REVIEW_PREDICATE_FLAG
from relations.temporal_v2 import TemporalState


# ---------------------------------------------------------------------------
# Utillaje determinista (entidades INVENTADAS)
# ---------------------------------------------------------------------------
_TEXT = "Marcus lidera la Cofradia del Yunque desde hace anos."


def _cand(**over) -> dict:
    """Candidato valido minimo (dict), con overrides."""
    base = {
        "subject_id": "marcus",
        "subject_type": "Character",
        "predicate": "MEMBER_OF",
        "object_id": "cofradia-yunque",
        "object_type": "Faction",
        "direction": "SUBJECT_TO_OBJECT",
        "confidence": 0.6,
        "evidence_text": _TEXT,
        "evidence_start": 0,
        "evidence_end": len(_TEXT),
        "source_id": "src-inventada",
        "source_page": None,
        "source_segment": "seg-1",
        "extraction_method": "HEURISTIC",
        "model": None,
        "negated": False,
        "temporal_scope": "PRESENT | state=ACTIVE",
        "epistemic_status": "ASSERTED",
        "workspace": "ws-invencion",
        "validation_flags": ["dry_run", "heuristic"],
    }
    base.update(over)
    return base


class _Sig:
    """Senal heuristica minima (duck-typed) como la emite `relations.signals`."""

    def __init__(self, name, value):
        self.name = name
        self.value = value


def _structural_signals(*, negation=False, type_compatibility=("MEMBERSHIP",)):
    return [
        _Sig("same_sentence", True),
        _Sig("svo_pattern", True),
        _Sig("negation", negation),
        _Sig("type_compatibility", list(type_compatibility)),
    ]


# ---------------------------------------------------------------------------
# 1. Catalogos CERRADOS y versiones estables
# ---------------------------------------------------------------------------
def test_version_and_schema_are_stable():
    assert A.ABSTENTION_VERSION == "relation-abstention-1.0.0"
    assert A.ABSTENTION_SCHEMA == "relation-abstention/v1"


def test_catalogs_are_closed_sorted_and_disjoint():
    assert A.SEVERITIES == tuple(sorted(A.SEVERITIES))
    assert A.REASON_CODES == tuple(sorted(A.REASON_CODES))
    assert A.REASON_SOURCES == tuple(sorted(A.REASON_SOURCES))
    assert A.VERDICTS == tuple(sorted(A.VERDICTS))
    # Ningun codigo/veredicto puede colisionar con la taxonomia de consenso ni con
    # el vocabulario de recomendaciones: son planos distintos.
    assert not set(A.VERDICTS) & set(CONSENSUS_STATES)
    assert not set(A.REASON_CODES) & set(RELATION_RECOMMENDATIONS)


def test_reason_rejects_unknown_code_severity_or_source():
    with pytest.raises(ValueError):
        A.DecisionReason("inventado", A.SEVERITY_BLOCKING, A.SOURCE_NEGATION)
    with pytest.raises(ValueError):
        A.DecisionReason(A.REASON_NEGATED_RELATION, "MUY_GRAVE", A.SOURCE_NEGATION)
    with pytest.raises(ValueError):
        A.DecisionReason(A.REASON_NEGATED_RELATION, A.SEVERITY_BLOCKING, "astrologia")


def test_assessment_rejects_unknown_verdict():
    with pytest.raises(ValueError):
        A.Assessment(verdict="QUIZAS")


def test_policy_rejects_non_boolean_and_empty_name():
    with pytest.raises(A.AbstentionPolicyError):
        A.AbstentionPolicy(reject_on_negation="si")
    with pytest.raises(A.AbstentionPolicyError):
        A.AbstentionPolicy(name="  ")
    with pytest.raises(A.AbstentionPolicyError):
        A.assess(_cand(), policy="politica")


# ---------------------------------------------------------------------------
# 2. Lectura del estado de vigencia (B4) desde el `temporal_scope`
# ---------------------------------------------------------------------------
def test_temporal_state_of_reads_state_segment():
    assert A.temporal_state_of("ENDED | state=ENDED | markers=rompio") == TemporalState.ENDED
    assert A.temporal_state_of("FUTURE | state=PLANNED") == TemporalState.PLANNED
    assert A.temporal_state_of("PRESENT | state=ACTIVE") == TemporalState.ACTIVE


def test_temporal_state_of_is_unknown_when_absent_or_junk():
    # Alcance de v1 (sin `state=`), None y basura -> UNKNOWN ("no consta").
    assert A.temporal_state_of("PAST") == TemporalState.UNKNOWN
    assert A.temporal_state_of(None) == TemporalState.UNKNOWN
    assert A.temporal_state_of(123) == TemporalState.UNKNOWN
    assert A.temporal_state_of("PAST | state=INVENTADO") == TemporalState.UNKNOWN


# ---------------------------------------------------------------------------
# 3. Derivacion de motivos (una senal por bloque del motor v2)
# ---------------------------------------------------------------------------
def _codes(assessment, severity=None):
    return {r.code for r in assessment.reasons
            if severity is None or r.severity == severity}


def test_predicate_abstention_blocks_and_is_structured():
    cand = _cand(validation_flags=["dry_run", "heuristic", REVIEW_PREDICATE_FLAG])
    a = A.assess(cand)
    assert a.verdict == A.VERDICT_ABSTAIN
    assert A.REASON_PREDICATE_ABSTAINED in _codes(a, A.SEVERITY_BLOCKING)
    reason = [r for r in a.reasons if r.code == A.REASON_PREDICATE_ABSTAINED][0]
    assert reason.source == A.SOURCE_PREDICATE
    assert reason.to_dict()["severity"] == A.SEVERITY_BLOCKING
    # El motivo es ESTRUCTURADO: el detalle es traza, no criterio.
    assert set(reason.to_dict()) == {"code", "severity", "source", "detail"}


def test_negation_justifies_reject():
    a = A.assess(_cand(negated=True))
    assert a.verdict == A.VERDICT_REJECT
    assert A.REASON_NEGATED_RELATION in _codes(a, A.SEVERITY_REJECTING)


def test_epistemic_not_asserted_blocks_but_does_not_reject():
    for status in ("RUMORED", "HYPOTHETICAL", "INTENDED"):
        a = A.assess(_cand(epistemic_status=status))
        assert a.verdict == A.VERDICT_ABSTAIN, status
        assert A.REASON_EPISTEMIC_NOT_ASSERTED in _codes(a, A.SEVERITY_BLOCKING)


def test_temporal_not_in_force_blocks():
    for state in (TemporalState.PLANNED, TemporalState.HYPOTHETICAL):
        a = A.assess(_cand(temporal_scope=f"FUTURE | state={state}"))
        assert a.verdict == A.VERDICT_ABSTAIN, state
        assert A.REASON_TEMPORAL_NOT_IN_FORCE in _codes(a, A.SEVERITY_BLOCKING)


def test_temporal_ended_is_informative_by_default_and_changes_nothing():
    """ENDED NO rechaza por defecto: medido, fabricaria rechazos falsos en masa."""
    a = A.assess(_cand(temporal_scope="ENDED | state=ENDED"))
    assert a.verdict == A.VERDICT_NEUTRAL
    assert A.REASON_TEMPORAL_ENDED in _codes(a, A.SEVERITY_INFORMATIVE)
    assert A.apply_verdict(PARTIAL_CONSENSUS, RECO_PROPOSE, a) == (
        PARTIAL_CONSENSUS, RECO_PROPOSE)
    # Activar la regla explicitamente SI rechaza (la regla existe, no esta muerta).
    policy = A.AbstentionPolicy(reject_on_temporal_ended=True)
    b = A.assess(_cand(temporal_scope="ENDED | state=ENDED"), policy=policy)
    assert b.verdict == A.VERDICT_REJECT


def test_temporal_unknown_is_informative():
    a = A.assess(_cand(temporal_scope=None))
    assert a.verdict == A.VERDICT_NEUTRAL
    assert A.REASON_TEMPORAL_UNRESOLVED in _codes(a, A.SEVERITY_INFORMATIVE)


def test_direction_low_confidence_is_informative_by_default():
    cand = _cand(validation_flags=["dry_run", "heuristic", REVIEW_DIRECTION_FLAG])
    a = A.assess(cand)
    assert a.verdict == A.VERDICT_NEUTRAL
    assert A.REASON_DIRECTION_LOW_CONFIDENCE in _codes(a, A.SEVERITY_INFORMATIVE)
    # Pero la regla bloqueante EXISTE y se puede activar de forma explicita.
    b = A.assess(cand, policy=A.AbstentionPolicy(veto_on_direction=True))
    assert b.verdict == A.VERDICT_ABSTAIN
    assert A.REASON_DIRECTION_LOW_CONFIDENCE in _codes(b, A.SEVERITY_BLOCKING)


def test_type_incompatibility_blocks():
    a = A.assess(_cand(), signals=_structural_signals(type_compatibility=()))
    assert a.verdict == A.VERDICT_ABSTAIN
    assert A.REASON_TYPE_INCOMPATIBLE in _codes(a, A.SEVERITY_BLOCKING)
    # Sin tipos conocidos NO se puede afirmar incompatibilidad.
    b = A.assess(_cand(subject_type=None, object_type=None),
                 signals=_structural_signals(type_compatibility=()))
    assert A.REASON_TYPE_INCOMPATIBLE not in _codes(b)


def test_clean_candidate_has_no_blocking_reason():
    a = A.assess(_cand(), signals=_structural_signals())
    assert a.verdict == A.VERDICT_NEUTRAL
    assert _codes(a, A.SEVERITY_BLOCKING) == set()
    assert _codes(a, A.SEVERITY_REJECTING) == set()


def test_reasons_are_sorted_and_assessment_is_deterministic():
    cand = _cand(negated=True, epistemic_status="RUMORED",
                 temporal_scope="FUTURE | state=PLANNED",
                 validation_flags=["dry_run", REVIEW_DIRECTION_FLAG])
    a = A.assess(cand)
    b = A.assess(dict(cand))
    assert a.to_dict() == b.to_dict()
    assert list(a.codes) == sorted(a.codes)


def test_assess_never_mutates_the_candidate():
    cand = _cand(negated=True)
    snapshot = dict(cand)
    A.assess(cand, signals=_structural_signals(negation=True))
    assert cand == snapshot


# ---------------------------------------------------------------------------
# 4. PRECEDENCIA: si el predicado esta en abstencion, tampoco se rechaza
# ---------------------------------------------------------------------------
def test_predicate_abstention_blocks_reject():
    cand = _cand(negated=True,
                 validation_flags=["dry_run", "heuristic", REVIEW_PREDICATE_FLAG])
    a = A.assess(cand)
    assert a.verdict == A.VERDICT_ABSTAIN
    assert A.apply_verdict(PARTIAL_CONSENSUS, RECO_PROPOSE, a) == (
        HUMAN_REQUIRED, RECO_HUMAN)
    # Desactivar la precedencia SI permite el rechazo (la opcion no esta muerta).
    b = A.assess(cand, policy=A.AbstentionPolicy(
        predicate_abstention_blocks_reject=False))
    assert b.verdict == A.VERDICT_REJECT


# ---------------------------------------------------------------------------
# 5. `apply_verdict`: BARRERA ANTI-MEJORA, comprobada EXHAUSTIVAMENTE
# ---------------------------------------------------------------------------
_ALL_COMBOS = list(itertools.product(
    CONSENSUS_STATES, RELATION_RECOMMENDATIONS, A.VERDICTS))


def test_apply_verdict_never_creates_a_proposal():
    for state, reco, verdict in _ALL_COMBOS:
        out_state, out_reco = A.apply_verdict(
            state, reco, A.Assessment(verdict=verdict))
        if out_reco == RECO_PROPOSE:
            assert reco == RECO_PROPOSE, (state, reco, verdict)


def test_apply_verdict_never_raises_the_state():
    for state, reco, verdict in _ALL_COMBOS:
        out_state, _ = A.apply_verdict(state, reco, A.Assessment(verdict=verdict))
        assert out_state in CONSENSUS_STATES
        if out_state == STRONG_CONSENSUS:
            assert state == STRONG_CONSENSUS, (state, reco, verdict)


def test_apply_verdict_never_emits_a_forbidden_recommendation():
    for state, reco, verdict in _ALL_COMBOS:
        _, out_reco = A.apply_verdict(state, reco, A.Assessment(verdict=verdict))
        assert out_reco in RELATION_RECOMMENDATIONS
        assert out_reco.lower() not in _FORBIDDEN_RECOMMENDATIONS


def test_apply_verdict_leaves_invalid_and_conflict_untouched():
    for state in (INVALID_RESPONSES, MODEL_CONFLICT):
        for reco, verdict in itertools.product(RELATION_RECOMMENDATIONS, A.VERDICTS):
            assert A.apply_verdict(state, reco, A.Assessment(verdict=verdict)) == (
                state, reco), (state, reco, verdict)


def test_apply_verdict_reject_lands_on_partial_never_strong():
    for state in (STRONG_CONSENSUS, PARTIAL_CONSENSUS, HUMAN_REQUIRED):
        out = A.apply_verdict(state, RECO_PROPOSE,
                              A.Assessment(verdict=A.VERDICT_REJECT))
        assert out == (PARTIAL_CONSENSUS, RECO_REJECT), state


def test_abstain_only_degrades_a_proposal_and_never_softens_a_reject():
    abstain = A.Assessment(verdict=A.VERDICT_ABSTAIN)
    assert A.apply_verdict(PARTIAL_CONSENSUS, RECO_PROPOSE, abstain) == (
        HUMAN_REQUIRED, RECO_HUMAN)
    # Un `reject` previo (voto negativo real) NO se ablanda a humano.
    assert A.apply_verdict(PARTIAL_CONSENSUS, RECO_REJECT, abstain) == (
        PARTIAL_CONSENSUS, RECO_REJECT)
    assert A.apply_verdict(HUMAN_REQUIRED, RECO_HUMAN, abstain) == (
        HUMAN_REQUIRED, RECO_HUMAN)


def test_neutral_verdict_changes_nothing():
    neutral = A.Assessment(verdict=A.VERDICT_NEUTRAL)
    for state, reco in itertools.product(CONSENSUS_STATES, RELATION_RECOMMENDATIONS):
        assert A.apply_verdict(state, reco, neutral) == (state, reco)


def test_summarize_is_stable_and_mentions_the_codes():
    a = A.assess(_cand(negated=True))
    assert A.summarize(a) == A.summarize(a)
    assert A.REASON_NEGATED_RELATION in A.summarize(a)
    assert A.summarize(A.Assessment(verdict=A.VERDICT_NEUTRAL)).startswith("Sin motivos")


# ---------------------------------------------------------------------------
# 6. Integracion en `consensus_adapter`
# ---------------------------------------------------------------------------
def test_default_policy_is_v1_and_is_byte_identical():
    cand = _cand(negated=True)
    sig = _structural_signals(negation=True)
    default = compute_relation_consensus(cand, signals=sig)
    explicit = compute_relation_consensus(cand, signals=sig, policy=POLICY_V1)
    assert default.to_dict() == explicit.to_dict()
    assert default.policy == POLICY_V1
    assert default.decision_reasons == []
    # v1 NO puede rechazar sin proveedores: ese es el techo que B6 documenta.
    assert default.recommendation != RECO_REJECT


def test_invalid_policy_is_rejected():
    for bad in ("v3", "auto", "", None):
        with pytest.raises(ValueError):
            compute_relation_consensus(_cand(), policy=bad)
    assert CONSENSUS_POLICIES == (POLICY_V1, POLICY_V2)


def test_policy_v2_opens_a_justified_reject_path_without_providers():
    cons = compute_relation_consensus(
        _cand(negated=True), signals=_structural_signals(negation=True),
        policy=POLICY_V2)
    assert cons.recommendation == RECO_REJECT
    assert cons.state == PARTIAL_CONSENSUS
    assert A.REASON_NEGATED_RELATION in cons.reason_codes
    codes = {r["code"] for r in cons.decision_reasons}
    assert A.REASON_NEGATED_RELATION in codes


def test_policy_v2_never_proposes_when_the_predicate_abstained():
    """La incoherencia diagnosticada en B6 es IMPOSIBLE por construccion."""
    cand = _cand(validation_flags=["dry_run", "heuristic", REVIEW_PREDICATE_FLAG])
    sig = _structural_signals()
    v1 = compute_relation_consensus(cand, signals=sig)
    v2 = compute_relation_consensus(cand, signals=sig, policy=POLICY_V2)
    assert v1.recommendation == RECO_PROPOSE   # el motor v1 SI proponia
    assert v2.recommendation == RECO_HUMAN     # v2 ya no
    assert v2.state == HUMAN_REQUIRED


def test_policy_v2_records_reasons_even_when_nothing_changes():
    cand = _cand(temporal_scope="ENDED | state=ENDED")
    v1 = compute_relation_consensus(cand, signals=_structural_signals())
    v2 = compute_relation_consensus(cand, signals=_structural_signals(),
                                    policy=POLICY_V2)
    assert (v2.state, v2.recommendation) == (v1.state, v1.recommendation)
    assert {r["code"] for r in v2.decision_reasons} == {A.REASON_TEMPORAL_ENDED}
    assert v2.policy == POLICY_V2


def test_policy_v2_does_not_touch_an_invalid_candidate():
    invalid = _cand(evidence_text="", evidence_start=0, evidence_end=0, negated=True)
    cons = compute_relation_consensus(invalid, signals=_structural_signals(),
                                      policy=POLICY_V2)
    assert cons.state == INVALID_RESPONSES
    assert cons.recommendation == RECO_HUMAN


def test_policy_v2_does_not_turn_a_model_conflict_into_a_reject():
    """Si las fuentes se contradicen ENTRE SI, ni proponer ni rechazar."""
    class _Sent:
        negated = False
        subject_index = 0
        main_verb_index = 1
        object_index = 2

    class _Syntax:
        sentences = (_Sent(),)

    cons = compute_relation_consensus(
        _cand(negated=True), signals=_structural_signals(negation=True),
        syntax=_Syntax(), policy=POLICY_V2)
    assert cons.state == MODEL_CONFLICT
    assert cons.recommendation == RECO_HUMAN


def test_policy_v2_is_deterministic_and_does_not_mutate():
    cand = _cand(negated=True, epistemic_status="RUMORED")
    snapshot = dict(cand)
    a = compute_relation_consensus(cand, signals=_structural_signals(negation=True),
                                   policy=POLICY_V2)
    b = compute_relation_consensus(cand, signals=_structural_signals(negation=True),
                                   policy=POLICY_V2)
    assert a.to_dict() == b.to_dict()
    assert cand == snapshot


def test_policy_v2_never_emits_an_approval():
    for over in ({}, {"negated": True}, {"epistemic_status": "RUMORED"},
                 {"temporal_scope": "FUTURE | state=PLANNED"},
                 {"validation_flags": ["dry_run", REVIEW_PREDICATE_FLAG]}):
        cons = compute_relation_consensus(_cand(**over),
                                          signals=_structural_signals(),
                                          policy=POLICY_V2)
        assert cons.recommendation in RELATION_RECOMMENDATIONS
        assert cons.recommendation.lower() not in _FORBIDDEN_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# 7. Integracion en el pipeline (config + flag de direccion)
# ---------------------------------------------------------------------------
def test_resolve_consensus_policy_follows_the_engine():
    assert P.resolve_consensus_policy(P.PipelineConfig()) == POLICY_V1
    assert P.resolve_consensus_policy(
        P.PipelineConfig(predicate_selector="v2")) == POLICY_V2
    # Override explicito: manda sobre el selector, en ambos sentidos.
    assert P.resolve_consensus_policy(
        P.PipelineConfig(predicate_selector="v2", consensus_policy="v1")) == POLICY_V1
    assert P.resolve_consensus_policy(
        P.PipelineConfig(predicate_selector="v1", consensus_policy="v2")) == POLICY_V2


def test_pipeline_config_rejects_an_invalid_policy():
    with pytest.raises(P.PipelineError):
        P.config_from_dict({"consensus_policy": "v9"})
    assert P.config_from_dict({"consensus_policy": "v2"}).consensus_policy == "v2"
    # La barrera de dry-run sigue intacta.
    with pytest.raises(P.PipelineError):
        P.config_from_dict({"consensus_policy": "v2", "write": True})


def _seg(text, entities):
    return {"segment_id": "s1", "text": text, "entities": entities}


def _ent(id_, text, whole, type_):
    start = whole.index(text)
    return {"id": id_, "start": start, "end": start + len(text), "type": type_}


def _negated_payload():
    text = "Gorm no pertenece a la Cofradia del Yunque."
    return {
        "document": "doc-b6",
        "workspace": "ws-invencion",
        "segments": [_seg(text, [
            _ent("gorm", "Gorm", text, "Character"),
            _ent("cofradia", "Cofradia del Yunque", text, "Faction"),
        ])],
    }


def test_pipeline_v1_keeps_the_historic_consensus():
    out = P.run_pipeline(_negated_payload(),
                         config=P.PipelineConfig(predicate_selector="v1"))
    cons = out["results"][0]["consensus"]
    assert cons["policy"] == POLICY_V1
    assert cons["decision_reasons"] == []
    assert cons["recommendation"] != RECO_REJECT


def test_pipeline_v2_rejects_a_negated_relation_with_structured_reasons():
    out = P.run_pipeline(_negated_payload(),
                         config=P.PipelineConfig(predicate_selector="v2"))
    rec = out["results"][0]
    assert rec["candidate"]["negated"] is True
    cons = rec["consensus"]
    assert cons["policy"] == POLICY_V2
    assert cons["recommendation"] == RECO_REJECT
    codes = {r["code"] for r in cons["decision_reasons"]}
    assert A.REASON_NEGATED_RELATION in codes
    assert all(set(r) == {"code", "severity", "source", "detail"}
               for r in cons["decision_reasons"])


def test_pipeline_v2_emits_the_direction_confidence_flag():
    """La confianza de direccion (B3) ya no se pierde: viaja como flag."""
    text = "Ysera y Kael comparten el estandarte de la Marca Gris."
    payload = {
        "document": "doc-b6b",
        "workspace": "ws-invencion",
        "segments": [_seg(text, [
            _ent("ysera", "Ysera", text, "Character"),
            _ent("kael", "Kael", text, "Character"),
        ])],
    }
    out = P.run_pipeline(payload, config=P.PipelineConfig(predicate_selector="v2"))
    assert out["results"], "el par inventado deberia producir un candidato"
    flags = out["results"][0]["candidate"]["validation_flags"]
    assert REVIEW_DIRECTION_FLAG in flags
    # v1 NO emite el flag (comportamiento historico intacto).
    out_v1 = P.run_pipeline(payload, config=P.PipelineConfig(predicate_selector="v1"))
    assert REVIEW_DIRECTION_FLAG not in out_v1["results"][0]["candidate"]["validation_flags"]


def test_direction_threshold_sits_between_the_weak_and_strong_signals():
    from relations import direction as D
    assert D.CONF_TEXTUAL < LOW_CONFIDENCE_THRESHOLD <= D.CONF_ACTIVE_EXPR
    assert D.CONF_GENERIC < LOW_CONFIDENCE_THRESHOLD


def test_pipeline_v2_is_deterministic():
    a = P.run_pipeline(_negated_payload(),
                       config=P.PipelineConfig(predicate_selector="v2"))
    b = P.run_pipeline(_negated_payload(),
                       config=P.PipelineConfig(predicate_selector="v2"))
    assert a["result_hash"] == b["result_hash"]
    assert [r["consensus"] for r in a["results"]] == [r["consensus"] for r in b["results"]]


# ---------------------------------------------------------------------------
# 8. Integracion en el ensemble calibrado
# ---------------------------------------------------------------------------
# NOTA: en estos tests el candidato lleva `temporal_scope=None` a proposito. El
# ensemble contrasta el alcance temporal DECLARADO contra la clase que infiere del
# texto y, si discrepan, registra un conflicto tipificado que manda a
# MODEL_CONFLICT/human ANTES de que B6 entre en juego. Con el alcance ausente no hay
# nada que contradecir y el ensemble llega a `propose`, que es justo el caso que hay
# que degradar aqui.
def test_ensemble_default_policy_is_v1_and_unchanged():
    cand = _cand(temporal_scope=None,
                 validation_flags=["dry_run", "heuristic", REVIEW_PREDICATE_FLAG])
    dec = E.combine(cand, signals=_structural_signals())
    assert dec.consensus_policy == POLICY_V1
    assert dec.decision_reasons == ()
    assert dec.recommendation == RECO_PROPOSE


def test_ensemble_v2_applies_the_abstention_after_the_thresholds():
    cand = _cand(temporal_scope=None,
                 validation_flags=["dry_run", "heuristic", REVIEW_PREDICATE_FLAG])
    dec = E.combine(cand, signals=_structural_signals(), consensus_policy=POLICY_V2)
    assert dec.recommendation == RECO_HUMAN
    assert dec.state == HUMAN_REQUIRED
    assert A.REASON_PREDICATE_ABSTAINED in {r["code"] for r in dec.decision_reasons}


def test_ensemble_v2_can_reject_a_negated_relation():
    dec = E.combine(_cand(negated=True, temporal_scope=None),
                    signals=_structural_signals(negation=True),
                    consensus_policy=POLICY_V2)
    assert dec.recommendation == RECO_REJECT
    assert dec.state != STRONG_CONSENSUS


def test_ensemble_rejects_an_invalid_consensus_policy():
    with pytest.raises(E.EnsembleConfigError):
        E.combine(_cand(), consensus_policy="v9")


def test_ensemble_v2_cannot_be_recalibrated_into_proposing_an_abstention():
    """Ninguna configuracion de pesos/umbrales puede saltarse la abstencion."""
    permisiva = E.EnsembleConfig(strong_threshold=0.05, partial_threshold=0.01,
                                 conflict_margin=0.0, min_decisive_sources=1)
    cand = _cand(temporal_scope=None,
                 validation_flags=["dry_run", "heuristic", REVIEW_PREDICATE_FLAG])
    dec = E.combine(cand, signals=_structural_signals(), config=permisiva,
                    consensus_policy=POLICY_V2)
    assert dec.recommendation == RECO_HUMAN


def test_ensemble_v2_serializes_the_reasons():
    dec = E.combine(_cand(epistemic_status="RUMORED", temporal_scope=None),
                    signals=_structural_signals(), consensus_policy=POLICY_V2)
    payload = dec.to_dict()
    assert payload["consensus_policy"] == POLICY_V2
    assert {r["code"] for r in payload["decision_reasons"]} >= {
        A.REASON_EPISTEMIC_NOT_ASSERTED}
    assert dec.to_json() == E.combine(
        _cand(epistemic_status="RUMORED", temporal_scope=None),
        signals=_structural_signals(), consensus_policy=POLICY_V2).to_json()
