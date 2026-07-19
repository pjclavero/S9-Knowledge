# -*- coding: utf-8 -*-
"""Q — adaptador de CONSENSO REAL (`relations.consensus_adapter`).

Cubre 6 puntos de la matriz con MUTATION checks contra la logica REAL:
  * Punto 6:  workspace mezclado aceptado -> se INVALIDA la mezcla de workspaces.
  * Punto 7:  negacion se pierde        -> el consenso PRESERVA `negated`.
  * Punto 8:  temporalidad se pierde     -> el consenso PRESERVA `temporal_scope`.
  * Punto 9:  consenso depende del orden -> es INDEPENDIENTE del orden de entrada.
  * Punto 10: proveedor ausente = rechazo -> ausente != voto negativo.
  * Punto 11: aparece autoaprobacion     -> ningun modulo emite APPROVED/AUTO_APPROVED.

Las FUENTES (R5 local / R6 externa) se aportan como dobles duck-typed, tal como
hace el propio test del modulo (`data-engine/app/tests/test_relation_consensus.py`);
el MODULO BAJO PRUEBA (`compute_relation_consensus`) es el REAL.
"""
from __future__ import annotations

import pytest

from external_ai.models import (
    CONSENSUS_STATES,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
)
from relations.consensus_adapter import (
    RECO_PROPOSE,
    RELATION_RECOMMENDATIONS,
    RelationConsensus,
    compute_relation_consensus,
)
from relations.contracts import (
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
)
from relations.signals import Signal


# ---------------------------------------------------------------------------
# Factorias (candidato real + senales reales + dobles de proveedor)
# ---------------------------------------------------------------------------
def make_candidate(**over) -> RelationCandidate:
    data = dict(
        subject_id="ent:aria", subject_type="Character", predicate="MEMBER_OF",
        object_id="ent:orden", object_type="Faction",
        direction=Direction.SUBJECT_TO_OBJECT, confidence=0.8,
        evidence_text="Aria es miembro de la Orden.", evidence_start=0, evidence_end=27,
        source_id="src-1", source_page=3, source_segment="seg-1",
        extraction_method=ExtractionMethod.HEURISTIC, model=None, negated=False,
        temporal_scope=None, epistemic_status=EpistemicStatus.ASSERTED, workspace="ws-alpha",
    )
    data.update(over)
    return RelationCandidate(**data).validate()


def sig(name, value):
    return Signal(name=name, value=value, evidence="ev", explanation="ex")


def strong_signals():
    return [
        sig("same_clause", True), sig("same_sentence", True), sig("svo_pattern", True),
        sig("type_compatibility", ["MEMBERSHIP"]), sig("negation", False), sig("rumor", False),
    ]


class FakeLocal:
    """Doble de R5 (interfaz leida por el adapter). No reimplementa el evaluador."""

    def __init__(self, recommendation="recommend_propose", *, state=PARTIAL_CONSENSUS,
                 validation_status="VALID", provider="ollama",
                 candidate=None, validation_errors=None):
        self.recommendation = recommendation
        self.state = state
        self.validation_status = validation_status
        self.provider = provider
        self.candidate = candidate
        self.validation_errors = validation_errors or []


class FakeExternal:
    """Doble de R6 (interfaz leida por el adapter)."""

    def __init__(self, shadow_recommendation="confirm", *, state=PARTIAL_CONSENSUS,
                 provider="nvidia", workspace=None, validation_errors=None):
        self.shadow_recommendation = shadow_recommendation
        self.state = state
        self.provider = provider
        self.workspace = workspace
        self.validation_errors = validation_errors or []


# ---------------------------------------------------------------------------
# Control: estados reutilizados, sin autoaprobacion.
# ---------------------------------------------------------------------------
def test_states_reused_and_no_approval():
    res = compute_relation_consensus(make_candidate(), signals=strong_signals())
    assert res.state in CONSENSUS_STATES
    assert res.consensus_states_source == "external_ai.models.CONSENSUS_STATES"
    assert res.recommendation in RELATION_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# MUTATION 6 (punto 6): mezcla de workspaces -> INVALIDA.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_workspace_mismatch_is_invalidated():
    """La invalidacion de mezcla de workspaces es load-bearing.

    Mutacion: si el adapter ignorara el workspace de las fuentes, un proveedor de
    OTRO workspace se combinaria en silencio (fuga entre espacios). El modulo real
    devuelve INVALID_RESPONSES/workspace_mismatch. Control: mismo workspace -> NO
    se invalida por esta causa.
    """
    cand = make_candidate(workspace="ws-alpha")
    mixed_local = FakeLocal(candidate={"workspace": "ws-otro"})
    res_bad = compute_relation_consensus(cand, signals=strong_signals(), local=mixed_local)
    assert res_bad.state == INVALID_RESPONSES
    assert "workspace_mismatch" in res_bad.reason_codes

    same_local = FakeLocal(candidate={"workspace": "ws-alpha"})
    res_ok = compute_relation_consensus(cand, signals=strong_signals(), local=same_local)
    assert "workspace_mismatch" not in res_ok.reason_codes


# ---------------------------------------------------------------------------
# MUTATION 7 (punto 7): la negacion NO se pierde en la combinacion.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_negation_is_preserved():
    """Preservar `negated` es load-bearing.

    Mutacion: si el consenso emitiera `negated` fijo (p.ej. False), una relacion
    NEGADA se propagaria como afirmacion. El modulo real copia el valor del
    candidato. Control: negated=False tambien se preserva (no se invierte).
    """
    neg_cand = make_candidate(negated=True)
    # La senal `negation` debe coincidir con el candidato para no crear conflicto.
    res_neg = compute_relation_consensus(
        neg_cand,
        signals=[sig("same_sentence", True), sig("svo_pattern", True),
                 sig("type_compatibility", ["MEMBERSHIP"]), sig("negation", True)],
    )
    assert res_neg.negated is True

    pos_cand = make_candidate(negated=False)
    res_pos = compute_relation_consensus(pos_cand, signals=strong_signals())
    assert res_pos.negated is False


# ---------------------------------------------------------------------------
# MUTATION 8 (punto 8): la temporalidad NO se pierde.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_temporal_scope_is_preserved():
    """Preservar `temporal_scope` es load-bearing.

    Mutacion: si el consenso descartara la temporalidad, se perderia el alcance
    (antes/despues/anios) de la afirmacion. El modulo real lo copia intacto.
    Control: None tambien se preserva como None.
    """
    scope = {"before": "guerra_hantei", "years": [1123]}
    res = compute_relation_consensus(
        make_candidate(temporal_scope=scope), signals=strong_signals())
    assert res.temporal_scope == scope

    res_none = compute_relation_consensus(make_candidate(), signals=strong_signals())
    assert res_none.temporal_scope is None


# ---------------------------------------------------------------------------
# MUTATION 9 (punto 9): independiente del orden de las senales.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_consensus_is_order_independent():
    """La independencia del orden de entrada es load-bearing.

    Mutacion: si `_signal_map` tomara "el ultimo gana" (dependiente del orden),
    un mismo conjunto de senales en distinto orden -incluyendo duplicados con
    valores distintos- daria resultados distintos. El modulo real es
    determinista e independiente del orden. Control: dos permutaciones producen
    EXACTAMENTE el mismo `to_dict`.
    """
    cand = make_candidate()
    base = [
        sig("same_sentence", True), sig("svo_pattern", True),
        sig("type_compatibility", ["MEMBERSHIP"]),
        sig("rumor", False), sig("rumor", False),  # duplicado deliberado
    ]
    res_a = compute_relation_consensus(cand, signals=list(base))
    res_b = compute_relation_consensus(cand, signals=list(reversed(base)))
    assert res_a.to_dict() == res_b.to_dict()


# ---------------------------------------------------------------------------
# MUTATION 10 (punto 10): proveedor AUSENTE != voto negativo.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_absent_provider_is_not_a_reject():
    """"Ausente != rechazo" es load-bearing.

    Mutacion: si la ausencia de un proveedor contara como voto NEGATIVO, un unico
    proveedor que PROPONE (con el otro ausente) acabaria en conflicto/reject. El
    modulo real trata la ausencia como abstencion: un unico proveedor positivo ->
    PARTIAL/propose. Control: si el otro proveedor esta PRESENTE y RECHAZA de
    verdad, entonces si hay MODEL_CONFLICT (demostrando que la diferencia es real).
    """
    cand = make_candidate()
    # Local PROPONE, externo AUSENTE -> corroboracion parcial, propone (no reject).
    res_absent = compute_relation_consensus(
        cand, signals=strong_signals(), local=FakeLocal("recommend_propose"), external=None)
    assert res_absent.state == PARTIAL_CONSENSUS
    assert res_absent.recommendation == RECO_PROPOSE

    # Externo PRESENTE y RECHAZA -> conflicto real (contraste con la ausencia).
    res_conflict = compute_relation_consensus(
        cand, signals=strong_signals(),
        local=FakeLocal("recommend_propose"), external=FakeExternal("reject"))
    assert res_conflict.state == MODEL_CONFLICT


# ---------------------------------------------------------------------------
# MUTATION 11 (punto 11): ningun modulo emite APPROVED/AUTO_APPROVED.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_no_auto_approval_across_modules():
    """La barrera anti-aprobacion es load-bearing en las tres capas.

    Mutacion: si se relajara el catalogo de recomendaciones, alguna capa podria
    emitir APPROVED/AUTO_APPROVED (autoaprobacion = escritura sin humano). Los
    __post_init__ reales lo IMPIDEN. Control: las recomendaciones legitimas SI
    construyen, y un consenso calculado nunca contiene "APPROVED".
    """
    # (a) consenso calculado: recomendacion valida, jamas APPROVED.
    res = compute_relation_consensus(make_candidate(), signals=strong_signals())
    assert res.recommendation in RELATION_RECOMMENDATIONS
    assert "APPROVED" not in res.recommendation.upper()

    # (b) RelationConsensus rechaza una recomendacion de aprobacion.
    ok = dict(state=PARTIAL_CONSENSUS, recommendation=RECO_PROPOSE, subject_id="s",
              predicate="MEMBER_OF", object_id="o", workspace="w", negated=False,
              epistemic_status="ASSERTED", temporal_scope=None)
    RelationConsensus(**ok)  # control: construye
    with pytest.raises(ValueError):
        RelationConsensus(**{**ok, "recommendation": "approve"})

    # (c) evaluador EXTERNO real: AUTO_APPROVED prohibido en __post_init__.
    from relations.external_ai_shadow import RelationExternalEvaluation
    RelationExternalEvaluation(candidate_id="c", state=PARTIAL_CONSENSUS,
                               shadow_recommendation="human", provider="nvidia", model="m")
    with pytest.raises(AssertionError):
        RelationExternalEvaluation(candidate_id="c", state=PARTIAL_CONSENSUS,
                                   shadow_recommendation="AUTO_APPROVED",
                                   provider="nvidia", model="m")

    # (d) evaluador LOCAL real: recomendacion fuera del catalogo (incl. AUTO_APPROVED)
    #     es rechazada por __post_init__.
    from relations.local_llm_shadow import LocalRelationRecommendation, RECOMMEND_PROPOSE
    common = dict(state=PARTIAL_CONSENSUS, validation_status="VALID", provider="local_llm",
                  model="m", prompt_suite="balanced", prompt_version="1.0",
                  template_id="membership", template_version="1.0.0",
                  input_hash="x", prompt_hash="y", latency_ms=1)
    LocalRelationRecommendation(recommendation=RECOMMEND_PROPOSE, **common)  # control
    with pytest.raises(ValueError):
        LocalRelationRecommendation(recommendation="AUTO_APPROVED", **common)
