# -*- coding: utf-8 -*-
"""Tests de MUTACION del motor local (prompt maestro §2 y §6).

Un test que pasa no demuestra que la regla exista: demuestra que el caso pasa.
Cada test de aqui **quita una regla del motor** y comprueba que el resultado se
vuelve INCORRECTO — es decir, que el test correspondiente de
`test_knowledge_v3_engine.py` moriria con esa mutacion. Un mutante que
sobrevive es una regla que ningun test estaba vigilando.

Las tres mutaciones que el encargo nombra explicitamente estan aqui:

* quitar la regla de contradiccion -> el motor aprueba una contradiccion;
* permitir ACCEPT sin evidencia verificada -> el motor aprueba una cita falsa;
* dejar que una senal externa aporte el predicado -> el motor aprueba con una
  base exclusivamente externa.

Y ademas: la comprobacion de tipos, la validacion de calendario, la prohibicion
de voltear la direccion, la capa de invariantes, el sellado del plan y las dos
reglas que el validador congelado impone al plan.
"""
from __future__ import annotations

import pytest

from knowledge_v3.contracts import GraphMutationPlan, V3ContractError
from knowledge_v3.contracts.base import schema_validator as V
from knowledge_v3.engine import EngineConfig, EnginePlanError
from knowledge_v3.engine import decision as decision_module
from knowledge_v3.engine import planner as planner_module
from knowledge_v3.engine.contradiction import ContradictionOutcome
from knowledge_v3.engine.ontology import DirectionOutcome, PredicateOutcome, PredicateSpec
from knowledge_v3.engine.temporal import TemporalOutcome
from test_knowledge_v3_engine_gold import (  # noqa: I100 - modulo hermano de fixtures
    EPISODE_VISUAL_ID,
    claim,
    codes,
    episode,
    episode_visual,
    fragment,
    fragment_dict,
    fragment_negated,
    fragment_visual,
    only,
    run,
    snapshot,
    vigente,
)


# --------------------------------------------------------------------------
# 1. Quitar la regla de contradiccion
# --------------------------------------------------------------------------
def test_mutant_without_the_contradiction_rule_approves_a_contradiction(monkeypatch):
    contradicted = snapshot(assertions=[vigente(negated=True)])
    assert only(run(snap=contradicted)).decision == "REVIEW"  # motor intacto

    monkeypatch.setattr(
        decision_module,
        "check_contradictions",
        lambda *a, **k: ContradictionOutcome((), None, ()),
    )
    mutant = run(snap=contradicted)
    assert only(mutant).decision == "ACCEPT"
    assert mutant.approved is True  # el mutante ESCRIBE lo contrario de lo vigente


# --------------------------------------------------------------------------
# 2. Permitir ACCEPT sin evidencia verificada
# --------------------------------------------------------------------------
def _forged_fragments():
    from knowledge_v3.contracts import EvidenceFragment

    forged = EvidenceFragment.from_dict(
        fragment_dict(literal_text="Daiki traiciono a la Casa del Ciervo")
    )
    return [forged, fragment_negated(), fragment_visual()]


def test_mutant_that_trusts_the_quote_approves_a_forged_citation(monkeypatch):
    from knowledge_v3.engine import findings as F

    assert only(run(fragments=_forged_fragments())).decision == "REVIEW"  # motor intacto

    monkeypatch.setattr(
        decision_module,
        "verify_evidence",
        lambda claim_, index, config: [F.EVIDENCE_LITERAL_VERIFIED("mutante: me lo creo")],
    )
    mutant = run(fragments=_forged_fragments())
    assert only(mutant).decision == "ACCEPT"
    assert mutant.approved is True


def test_mutant_without_the_invariant_layer_writes_unverifiable_evidence(monkeypatch):
    """Evidencia de un mapa: no hay texto que cotejar, luego no hay ACCEPT."""
    visual = claim(
        claim_id="claim:visual",
        episode_id=EPISODE_VISUAL_ID,
        evidence_fragment_ids=["fragment:gold:visual"],
        object_mentions=["mention:torre"],
        predicate_candidates=[{"predicate": "LOCATED_IN", "confidence": 0.9}],
    )
    batch = dict(
        claims=[visual],
        fragments=[fragment(), fragment_visual()],
        episodes=[episode(), episode_visual()],
    )
    assert only(run(batch["claims"], fragments=batch["fragments"], episodes=batch["episodes"])).decision != "ACCEPT"

    monkeypatch.setattr(
        decision_module,
        "_enforce_invariants",
        lambda decision, *a, **k: decision,
    )
    mutant = run(batch["claims"], fragments=batch["fragments"], episodes=batch["episodes"])
    assert only(mutant).decision == "ACCEPT"


# --------------------------------------------------------------------------
# 3. Dejar que una senal externa aporte la decision
# --------------------------------------------------------------------------
def test_mutant_that_takes_the_predicate_from_a_signal_approves_on_external_basis(monkeypatch):
    from knowledge_v3.engine import ExternalSignal

    signal = ExternalSignal(
        claim_id="claim:gold:0",
        step="signal.nvidia",
        provider="external",
        name="s9k.signal.nvidia",
        version="1.0.0",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        confidence=1.0,
    )
    empty = claim(predicate_candidates=[])
    assert only(run([empty], signals=[signal])).decision == "ABSTAIN"  # motor intacto

    monkeypatch.setattr(
        decision_module,
        "resolve_predicate",
        lambda candidates, index, s_type, o_type, config: PredicateOutcome("MEMBER_OF", 1.0, ()),
    )
    mutant = run([empty], signals=[signal])
    assert only(mutant).decision == "ACCEPT"
    assert mutant.approved is True  # aprobado sin una sola razon local


# --------------------------------------------------------------------------
# 4. Quitar la comprobacion de tipos de la ontologia
# --------------------------------------------------------------------------
def test_mutant_without_domain_and_range_accepts_a_nonsense_relation(monkeypatch):
    nonsense = [claim(object_mentions=["mention:torre"])]  # MEMBER_OF a un Location
    assert only(run(nonsense)).decision == "REJECT_INVALID"  # motor intacto

    monkeypatch.setattr(PredicateSpec, "allows", lambda self, s, o: True)
    mutant = run(nonsense)
    assert only(mutant).decision == "ACCEPT"


# --------------------------------------------------------------------------
# 5. Quitar la validacion del calendario contra el perfil
# --------------------------------------------------------------------------
def test_mutant_without_calendar_validation_writes_an_unknown_calendar(monkeypatch):
    dated = [
        claim(
            temporal_expressions=[
                {
                    "text": "tercer ciclo",
                    "kind": "POINT",
                    "valid_from": "1042-03-01T00:00:00Z",
                    "calendar_id": "calendar:inventado",
                }
            ]
        )
    ]
    assert only(run(dated)).decision == "REVIEW"  # motor intacto

    monkeypatch.setattr(
        decision_module,
        "resolve_temporality",
        lambda claim_, index, ids: TemporalOutcome(
            "ACTIVE", "1042-03-01T00:00:00Z", "1042-03-01T00:00:00Z", None, "calendar:inventado", ()
        ),
    )
    mutant = run(dated)
    assert only(mutant).decision == "ACCEPT"
    assert mutant.assertions[0].calendar_id == "calendar:inventado"


# --------------------------------------------------------------------------
# 6. Voltear la direccion en silencio
# --------------------------------------------------------------------------
def test_mutant_that_flips_the_direction_hides_an_extractor_error(monkeypatch):
    inverted = [claim(direction_candidates=[{"direction": "OBJECT_TO_SUBJECT", "confidence": 0.9}])]
    assert only(run(inverted)).decision == "REVIEW"  # motor intacto

    monkeypatch.setattr(
        decision_module,
        "resolve_direction",
        lambda candidates, spec, s_type, o_type, config: DirectionOutcome(
            "SUBJECT_TO_OBJECT", 0.9, ()
        ),
    )
    mutant = run(inverted)
    assert only(mutant).decision == "ACCEPT"
    assert only(mutant).direction == "SUBJECT_TO_OBJECT"  # nadie vera que hubo duda


# --------------------------------------------------------------------------
# 7. El pasado verbal como final de vigencia
# --------------------------------------------------------------------------
def test_mutant_that_ends_a_fact_without_a_closing_date_breaks_the_contract(monkeypatch):
    assert run().assertions[0].state == "UNKNOWN"  # motor intacto

    monkeypatch.setattr(
        decision_module,
        "resolve_temporality",
        lambda claim_, index, ids: TemporalOutcome("ENDED", None, None, None, None, ()),
    )
    # El contrato congelado no admite ENDED sin valid_to: el mutante ni siquiera
    # consigue construir la afirmacion, y el plan sale sin aprobar.
    mutant = run()
    assert mutant.assertions == ()
    assert not mutant.approved
    semantic = [v for v in mutant.validator_chain if v["validator"] == "semantic"][0]
    assert semantic["result"] == "FAIL"
    assert "ASSERTION_INVALID" in semantic["reason_codes"]


# --------------------------------------------------------------------------
# 8. Quitar el sellado del plan
# --------------------------------------------------------------------------
def test_mutant_that_does_not_seal_the_plan_cannot_produce_one(monkeypatch):
    assert run().plan.signature_is_intact()  # motor intacto

    monkeypatch.setattr(planner_module, "seal_plan", lambda body, **kw: body)
    with pytest.raises(EnginePlanError, match="no valida"):
        run()


def test_mutant_that_reimplements_the_hash_is_caught_by_the_frozen_validator():
    """Reimplementar la formula del hash produce un plan que el writer rechaza."""
    plan = run().plan
    doc = plan.to_dict()
    doc["local_approval"] = {**doc["local_approval"], "decision_hash": V.sha256_hash("mi formula")}
    doc["plan_hash"] = V.compute_plan_hash(doc)
    with pytest.raises(V3ContractError, match="decision_hash"):
        GraphMutationPlan.from_dict(doc)


# --------------------------------------------------------------------------
# 9. Reglas del plan que impone el contrato congelado
# --------------------------------------------------------------------------
def test_an_operation_hanging_from_a_review_decision_is_rejected():
    result = run([claim(), claim(claim_id="claim:gold:1", review_required=True)],
                 config=EngineConfig(split_review_plan=False))
    doc = result.plan.to_dict()
    review_id = [d["decision_id"] for d in doc["decisions"] if d["decision"] == "REVIEW"][0]
    doc["mutation_operations"][0]["decision_id"] = review_id
    with pytest.raises(V3ContractError, match="solo ACCEPT"):
        GraphMutationPlan.from_dict(V.seal_plan(doc))


def test_a_plan_approved_with_pending_reviews_is_rejected():
    result = run([claim(), claim(claim_id="claim:gold:1", review_required=True)],
                 config=EngineConfig(split_review_plan=False))
    doc = result.plan.to_dict()
    doc["local_approval"] = {**doc["local_approval"], "approved": True}
    with pytest.raises(V3ContractError, match="REVIEW"):
        GraphMutationPlan.from_dict(V.seal_plan(doc))


def test_a_plan_that_claims_to_be_signed_by_an_external_provider_is_rejected():
    doc = run().plan.to_dict()
    doc["local_approval"] = {
        **doc["local_approval"],
        "approved_by": {"provider": "external", "name": "nvidia", "version": "1"},
    }
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(V.seal_plan(doc))


def test_an_invented_idempotency_key_is_rejected():
    doc = run().plan.to_dict()
    doc["mutation_operations"][0]["idempotency_key"] = "idem:sha256:" + "b" * 64
    with pytest.raises(V3ContractError, match="idempotency_key"):
        GraphMutationPlan.from_dict(V.seal_plan(doc, derive_keys=False))


def test_a_mutant_that_drops_expected_version_loses_optimistic_concurrency():
    doc = run().plan.to_dict()
    projection = [op for op in doc["mutation_operations"] if op["operation_type"] == "PROJECT_RELATION"][0]
    projection["expected_version"] = None
    projection["expected_hash"] = None
    with pytest.raises(V3ContractError, match="expected_version"):
        GraphMutationPlan.from_dict(V.seal_plan(doc))


# --------------------------------------------------------------------------
# 10. La configuracion no puede abrir ninguna de las tres invariantes
# --------------------------------------------------------------------------
def test_no_configuration_can_approve_a_contradiction():
    """Umbrales al minimo, todos los estatus epistemicos aceptados: sigue en REVIEW."""
    permissive = EngineConfig(
        min_claim_confidence=0.0,
        min_predicate_confidence=0.0,
        min_predicate_margin=0.0,
        min_direction_confidence=0.0,
        min_resolution_confidence=0.0,
        min_episode_quality=0.0,
        min_fragment_confidence=0.0,
        acceptable_epistemic_status=frozenset(
            {"ASSERTED", "RUMORED", "HYPOTHETICAL", "INTENDED", "VISUAL_INFERRED", "CONFLICTED", "UNKNOWN"}
        ),
    )
    decision = only(run(snap=snapshot(assertions=[vigente(negated=True)]), config=permissive))
    assert decision.decision == "REVIEW"
    assert "CONFLICT_WITH_EXISTING" in codes(decision)


def test_turning_the_literal_check_off_makes_the_engine_stricter_not_laxer():
    """`require_literal_evidence=False` no abre la puerta: la cierra del todo."""
    config = EngineConfig(require_literal_evidence=False)
    result = run(config=config)
    assert only(result).decision != "ACCEPT"
    assert not result.approved
