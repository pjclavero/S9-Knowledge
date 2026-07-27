# -*- coding: utf-8 -*-
"""Tests del MOTOR LOCAL V3 (prompt maestro §8, pruebas separadas: "motor").

Un test por regla y por eje, con caso POSITIVO y NEGATIVO en los cinco ejes que
el encargo nombra — negacion, direccion, epistemicidad, temporalidad y
contradiccion — mas existencia, evidencia, predicado, plan, aislamiento y
autoridad.

Los tests de mutacion viven aparte, en `test_knowledge_v3_engine_mutations.py`.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from knowledge_v3.contracts import GraphMutationPlan
from knowledge_v3.contracts.base import schema_validator as V
from knowledge_v3.engine import (
    DEFAULT_CONFIG,
    EngineConfig,
    EngineInputError,
    ExternalSignal,
    LocalKnowledgeEngine,
    Neo4jReadOnlyGraphSnapshot,
    canonical_key,
)
from knowledge_v3.engine.ontology import ProfileIndex
from knowledge_v3.engine.planner import plan_is_self_consistent
from test_knowledge_v3_engine_gold import (  # noqa: I100 - modulo hermano de fixtures
    ASSET_ID,
    COLLECTION_ID,
    EPISODE_VISUAL_ID,
    NOW,
    WORKSPACE,
    claim,
    claim_dict,
    codes,
    engine,
    episode,
    episode_visual,
    fragment,
    fragment_dict,
    fragment_negated,
    fragment_visual,
    only,
    profile,
    resolution,
    resolution_casa,
    resolution_consejo,
    resolution_puerto,
    resolution_torre,
    run,
    snapshot,
    vigente,
    DEFAULT_RESOLUTIONS,
)


# ==========================================================================
# 1. Camino feliz y forma de la decision
# ==========================================================================
def test_happy_path_is_accepted_with_the_canonical_reason():
    decision = only(run())
    assert decision.decision == "ACCEPT"
    assert "LOCAL_APPROVED" in codes(decision)
    assert decision.predicate == "MEMBER_OF"
    assert decision.direction == "SUBJECT_TO_OBJECT"
    assert decision.subject_entity_id == "entity:daiki"
    assert decision.object_entity_id == "entity:casa-ciervo"


def test_every_decision_carries_a_canonical_reason_code_of_its_kind():
    scenarios = [
        run(),
        run([claim(review_required=True)]),
        run([claim(evidence_fragment_ids=["fragment:no-existe"])]),
        run([claim(predicate_candidates=[{"predicate": "GOBIERNA_EN", "confidence": 0.9}])]),
    ]
    for result in scenarios:
        for decision in result.decisions:
            allowed = V.CANONICAL_REASON_CODES[decision.decision]
            assert codes(decision) & allowed, (decision.decision, codes(decision))


def test_reason_codes_are_sorted_and_deduplicated():
    decision = only(run())
    reasons = decision.reason_codes()
    assert reasons == sorted(set(reasons))


def test_the_decision_explains_itself_axis_by_axis():
    decision = only(run([claim(review_required=True)]))
    assert any("EXTRACTOR_REQUESTED_REVIEW" in line for line in decision.explanation())


def test_summary_counts_every_decision():
    result = run([claim(), claim(claim_id="claim:gold:1", review_required=True)])
    assert result.summary() == {"ACCEPT": 1, "REVIEW": 1, "ABSTAIN": 0, "REJECT_INVALID": 0}


# ==========================================================================
# 2. Eje EXISTENCIA / identidad
# ==========================================================================
def test_unresolved_mention_goes_to_review():
    decision = only(run([claim(subject_mentions=["mention:fantasma"])]))
    assert decision.decision == "REVIEW"
    assert "REVIEW_ENTITY" in codes(decision)
    assert "UNRESOLVED_MENTION" in codes(decision)


def test_provisional_entity_is_never_written():
    provisional = resolution(
        resolution_id="resolution:prov",
        mention_ids=["mention:daiki"],
        candidate_entity_ids=[],
        selected_entity_id=None,
        assigned_entity_id="entity:prov:daiki",
        action="CREATE_PROVISIONAL",
        confidence=0.4,
    )
    decision = only(run(resolutions=[provisional, resolution_casa()]))
    assert decision.decision == "REVIEW"
    assert "ENTITY_PROVISIONAL" in codes(decision)


def test_entity_absent_from_the_snapshot_goes_to_review():
    decision = only(run(snap=snapshot(entities=[("entity:casa-ciervo", "Faction", 1)])))
    assert decision.decision == "REVIEW"
    assert "ENTITY_NOT_IN_SNAPSHOT" in codes(decision)


def test_low_confidence_resolution_goes_to_review():
    weak = resolution(confidence=0.4)
    decision = only(run(resolutions=[weak, resolution_casa()]))
    assert decision.decision == "REVIEW"
    assert "ENTITY_LOW_CONFIDENCE" in codes(decision)


def test_two_mentions_of_the_same_role_pointing_elsewhere_go_to_review():
    decision = only(run([claim(subject_mentions=["mention:daiki", "mention:consejo"])]))
    assert decision.decision == "REVIEW"
    assert "ENTITY_ROLE_AMBIGUOUS" in codes(decision)


def test_self_relation_is_rejected_as_demonstrably_false():
    twin = resolution(resolution_id="resolution:daiki2", mention_ids=["mention:daiki2"])
    decision = only(
        run(
            [
                claim(
                    object_mentions=["mention:daiki2"],
                    predicate_candidates=[{"predicate": "ALLY_OF", "confidence": 0.9}],
                )
            ],
            resolutions=[resolution(), twin, resolution_casa()],
        )
    )
    assert decision.decision == "REJECT_INVALID"
    assert "SELF_RELATION" in codes(decision)
    assert "DEMONSTRABLY_FALSE" in codes(decision)


def test_type_disagreement_between_resolution_and_graph_goes_to_review():
    decision = only(
        run(snap=snapshot(entities=[("entity:daiki", "Faction", 1), ("entity:casa-ciervo", "Faction", 1)]))
    )
    assert decision.decision == "REVIEW"
    assert "ENTITY_TYPE_UNKNOWN" in codes(decision)


def test_an_upstream_abstention_is_respected():
    abstained = claim(
        predicate_candidates=[],
        alternatives=[],
        confidence=0,
        abstained=True,
        review_required=True,
    )
    decision = only(run([abstained]))
    assert decision.decision == "ABSTAIN"
    assert "CLAIM_ABSTAINED_UPSTREAM" in codes(decision)


# ==========================================================================
# 3. Eje EVIDENCIA
# ==========================================================================
def test_positive_evidence_is_verified_against_the_episode_text():
    assert "EVIDENCE_LITERAL_VERIFIED" in codes(only(run()))


def test_unknown_fragment_makes_the_engine_abstain():
    decision = only(run([claim(evidence_fragment_ids=["fragment:inventado"])]))
    assert decision.decision == "ABSTAIN"
    assert "INSUFFICIENT_EVIDENCE" in codes(decision)


def test_a_quote_that_is_not_in_the_episode_goes_to_review():
    forged = fragment_dict(literal_text="Daiki traiciono a la Casa del Ciervo")
    from knowledge_v3.contracts import EvidenceFragment

    decision = only(
        run(fragments=[EvidenceFragment.from_dict(forged), fragment_negated(), fragment_visual()])
    )
    assert decision.decision == "REVIEW"
    assert "EVIDENCE_TEXT_MISMATCH" in codes(decision)


def test_offsets_beyond_the_episode_go_to_review():
    decision = only(run(fragments=[fragment(start=900, end=999), fragment_visual()]))
    assert decision.decision == "REVIEW"
    assert "EVIDENCE_OFFSETS_OUT_OF_RANGE" in codes(decision)


def test_a_low_quality_episode_makes_the_engine_abstain():
    decision = only(run(episodes=[episode(quality={"score": 0.2, "flags": ["ASR_NOISY"]})]))
    assert decision.decision == "ABSTAIN"
    assert "LOW_QUALITY_EPISODE" in codes(decision)


def test_evidence_borrowed_from_another_asset_is_rejected():
    alien = fragment(source_asset_id="asset:otro", source_hash=fragment().source_hash)
    decision = only(run(fragments=[alien]))
    assert decision.decision == "REJECT_INVALID"
    assert "EVIDENCE_FOREIGN_ASSET" in codes(decision)


def test_evidence_from_another_episode_does_not_support_the_claim():
    decision = only(run([claim(evidence_fragment_ids=["fragment:gold:visual"])]))
    assert decision.decision == "ABSTAIN"
    assert "EVIDENCE_EPISODE_UNKNOWN" in codes(decision)


def test_the_extractor_can_demand_review_and_is_obeyed():
    decision = only(run([claim(review_required=True)]))
    assert decision.decision == "REVIEW"
    assert "EXTRACTOR_REQUESTED_REVIEW" in codes(decision)


def test_a_claim_below_the_confidence_threshold_goes_to_review():
    decision = only(
        run([claim(confidence=0.3, predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 0.82}])])
    )
    assert decision.decision == "REVIEW"
    assert "CLAIM_LOW_CONFIDENCE" in codes(decision)


def test_non_textual_evidence_can_never_be_literally_verified():
    """Limite honesto: sin texto no hay cotejo, y sin cotejo no hay ACCEPT."""
    visual = claim(
        claim_id="claim:gold:visual",
        episode_id=EPISODE_VISUAL_ID,
        evidence_fragment_ids=["fragment:gold:visual"],
        object_mentions=["mention:torre"],
        predicate_candidates=[{"predicate": "LOCATED_IN", "confidence": 0.9}],
        epistemic_status_hint="VISUAL_INFERRED",
        review_required=True,
    )
    decision = only(run([visual]))
    assert decision.decision != "ACCEPT"
    assert "EVIDENCE_LITERAL_VERIFIED" not in codes(decision)


# ==========================================================================
# 4. Eje PREDICADO
# ==========================================================================
def test_a_claim_without_predicate_candidates_produces_an_abstention():
    decision = only(run([claim(predicate_candidates=[])]))
    assert decision.decision == "ABSTAIN"
    assert "AMBIGUOUS_SEMANTICS" in codes(decision)


def test_a_predicate_outside_the_profile_is_rejected():
    decision = only(run([claim(predicate_candidates=[{"predicate": "GOBIERNA_EN", "confidence": 0.95}])]))
    assert decision.decision == "REJECT_INVALID"
    assert "ONTOLOGY_INCOMPATIBLE" in codes(decision)


def test_a_predicate_incompatible_with_the_types_is_rejected():
    decision = only(run([claim(object_mentions=["mention:torre"])]))
    assert decision.decision == "REJECT_INVALID"
    assert "TYPE_INCOMPATIBLE" in codes(decision)


def test_two_candidates_that_almost_tie_go_to_review():
    decision = only(
        run(
            [
                claim(
                    predicate_candidates=[
                        {"predicate": "MEMBER_OF", "confidence": 0.7},
                        {"predicate": "SERVES", "confidence": 0.65},
                    ]
                )
            ]
        )
    )
    assert decision.decision == "REVIEW"
    assert "PREDICATE_AMBIGUOUS" in codes(decision)


def test_a_predicate_below_its_threshold_goes_to_review():
    decision = only(
        run([claim(predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 0.4}])])
    )
    assert decision.decision == "REVIEW"
    assert "PREDICATE_LOW_CONFIDENCE" in codes(decision)


def test_the_engine_demotes_an_impossible_favourite_and_says_so():
    decision = only(
        run(
            [
                claim(
                    predicate_candidates=[
                        {"predicate": "GOBIERNA_EN", "confidence": 0.9},
                        {"predicate": "MEMBER_OF", "confidence": 0.82},
                    ]
                )
            ]
        )
    )
    assert decision.decision == "ACCEPT"
    assert decision.predicate == "MEMBER_OF"
    assert "PREDICATE_DEMOTED" in codes(decision)
    assert "LOCAL_APPROVED_WITH_WARNINGS" in codes(decision)


def test_the_thresholds_are_configurable():
    strict = EngineConfig(min_predicate_confidence=0.99)
    assert only(run(config=strict)).decision == "REVIEW"


# ==========================================================================
# 5. Eje DIRECCION
# ==========================================================================
def test_a_symmetric_predicate_is_undirected_whatever_the_extractor_says():
    decision = only(
        run([claim(predicate_candidates=[{"predicate": "ALLY_OF", "confidence": 0.9}])])
    )
    assert decision.decision == "ACCEPT"
    assert decision.direction == "UNDIRECTED"
    assert "SYMMETRIC_PREDICATE" in codes(decision)


def test_an_undirected_proposal_for_an_asymmetric_predicate_goes_to_review():
    decision = only(
        run([claim(direction_candidates=[{"direction": "UNDIRECTED", "confidence": 0.9}])])
    )
    assert decision.decision == "REVIEW"
    assert "DIRECTION_UNDETERMINED" in codes(decision)


def test_a_direction_incompatible_with_the_types_is_never_flipped_in_silence():
    decision = only(
        run([claim(direction_candidates=[{"direction": "OBJECT_TO_SUBJECT", "confidence": 0.9}])])
    )
    assert decision.decision == "REVIEW"
    assert "DIRECTION_TYPE_MISMATCH" in codes(decision)
    assert decision.direction == "OBJECT_TO_SUBJECT"  # se conserva lo propuesto


def test_a_direction_below_its_threshold_goes_to_review():
    decision = only(
        run([claim(direction_candidates=[{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.4}])])
    )
    assert decision.decision == "REVIEW"
    assert "DIRECTION_LOW_CONFIDENCE" in codes(decision)


def test_a_tie_between_the_two_directions_goes_to_review():
    decision = only(
        run(
            [
                claim(
                    direction_candidates=[
                        {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.8},
                        {"direction": "OBJECT_TO_SUBJECT", "confidence": 0.8},
                    ]
                )
            ]
        )
    )
    assert decision.decision == "REVIEW"
    assert "DIRECTION_AMBIGUOUS" in codes(decision)


def test_no_direction_candidates_at_all_goes_to_review():
    decision = only(run([claim(direction_candidates=[])]))
    assert decision.decision == "REVIEW"
    assert "DIRECTION_UNDETERMINED" in codes(decision)


# ==========================================================================
# 6. Eje NEGACION
# ==========================================================================
def test_a_negated_fact_is_a_fact_and_is_accepted_with_a_warning():
    decision = only(
        run(
            [
                claim(
                    claim_id="claim:gold:neg",
                    negated=True,
                    object_mentions=["mention:consejo"],
                    relation_phrase="jamas sirvio al",
                    predicate_candidates=[{"predicate": "SERVES", "confidence": 0.85}],
                    evidence_fragment_ids=["fragment:gold:1"],
                    epistemic_cues=["jamas"],
                )
            ]
        )
    )
    assert decision.decision == "ACCEPT"
    assert decision.negated is True
    assert "NEGATED_CLAIM" in codes(decision)
    assert "LOCAL_APPROVED_WITH_WARNINGS" in codes(decision)


def test_the_negated_flag_travels_untouched_to_the_assertion():
    result = run(
        [
            claim(
                claim_id="claim:gold:neg",
                negated=True,
                object_mentions=["mention:consejo"],
                predicate_candidates=[{"predicate": "SERVES", "confidence": 0.85}],
                evidence_fragment_ids=["fragment:gold:1"],
            )
        ]
    )
    assert result.assertions[0].negated is True


def test_negation_can_be_configured_out_and_then_goes_to_review():
    decision = only(
        run(
            [
                claim(
                    negated=True,
                    object_mentions=["mention:consejo"],
                    predicate_candidates=[{"predicate": "SERVES", "confidence": 0.85}],
                    evidence_fragment_ids=["fragment:gold:1"],
                )
            ],
            config=EngineConfig(accept_negated=False),
        )
    )
    assert decision.decision == "REVIEW"
    assert "NEGATION_NOT_ACCEPTED" in codes(decision)


def test_the_engine_never_infers_negation_by_itself():
    """El claim no negado sigue no negado aunque el episodio contenga 'jamas'."""
    decision = only(run())
    assert decision.negated is False


# ==========================================================================
# 7. Eje EPISTEMICIDAD
# ==========================================================================
@pytest.mark.parametrize("hint", ["RUMORED", "HYPOTHETICAL", "INTENDED"])
def test_what_is_not_asserted_is_not_written(hint):
    decision = only(run([claim(epistemic_status_hint=hint)]))
    assert decision.decision == "REVIEW"
    assert "EPISTEMIC_NOT_ASSERTED" in codes(decision)


def test_an_unknown_epistemic_status_makes_the_engine_abstain():
    decision = only(run([claim(epistemic_status_hint="UNKNOWN")]))
    assert decision.decision == "ABSTAIN"
    assert "EPISTEMIC_UNKNOWN" in codes(decision)


def test_a_visual_reading_always_goes_to_review():
    decision = only(
        run([claim(epistemic_status_hint="VISUAL_INFERRED", review_required=True)])
    )
    assert decision.decision == "REVIEW"
    assert "EPISTEMIC_VISUAL_INFERRED" in codes(decision)


def test_widening_the_acceptable_epistemic_set_lands_a_provisional_assertion():
    config = EngineConfig(acceptable_epistemic_status=frozenset({"ASSERTED", "RUMORED"}))
    result = run([claim(epistemic_status_hint="RUMORED")], config=config)
    assert only(result).decision == "ACCEPT"
    assert result.assertions[0].status == "PROVISIONAL"
    assert result.assertions[0].epistemic_status == "RUMORED"


def test_a_contradicted_claim_is_marked_conflicted():
    decision = only(run(snap=snapshot(assertions=[vigente(negated=True)])))
    assert decision.epistemic_status == "CONFLICTED"


# ==========================================================================
# 8. Eje TEMPORALIDAD
# ==========================================================================
def test_the_verbal_past_does_not_mean_ended():
    """'juro lealtad' esta en pasado; la pertenencia sigue viva."""
    result = run()
    assert result.assertions[0].state == "UNKNOWN"
    assert result.assertions[0].valid_to is None


def test_an_explicit_closed_interval_does_mean_ended():
    result = run(
        [
            claim(
                temporal_expressions=[
                    {
                        "text": "entre 1042 y 1050",
                        "kind": "INTERVAL",
                        "valid_from": "1042-01-01T00:00:00Z",
                        "valid_to": "1050-01-01T00:00:00Z",
                        "calendar_id": "calendar:umbra",
                        "fragment_id": "fragment:gold:0",
                    }
                ]
            )
        ]
    )
    assertion = result.assertions[0]
    assert assertion.state == "ENDED"
    assert assertion.valid_to == "1050-01-01T00:00:00Z"
    assert assertion.calendar_id == "calendar:umbra"


def test_an_open_point_in_time_is_active_and_sets_the_event_time():
    result = run(
        [
            claim(
                temporal_expressions=[
                    {
                        "text": "en el ciclo 1042",
                        "kind": "POINT",
                        "valid_from": "1042-03-01T00:00:00Z",
                        "valid_to": None,
                        "calendar_id": "calendar:umbra",
                        "fragment_id": "fragment:gold:0",
                    }
                ]
            )
        ]
    )
    assertion = result.assertions[0]
    assert assertion.state == "ACTIVE"
    assert assertion.event_time == "1042-03-01T00:00:00Z"
    assert assertion.valid_to is None


def test_a_calendar_the_profile_does_not_know_goes_to_review():
    decision = only(
        run(
            [
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
        )
    )
    assert decision.decision == "REVIEW"
    assert "REVIEW_TEMPORALITY" in codes(decision)
    assert "TEMPORAL_CALENDAR_UNKNOWN" in codes(decision)


def test_two_calendars_in_the_same_claim_go_to_review():
    decision = only(
        run(
            [
                claim(
                    temporal_expressions=[
                        {"text": "a", "kind": "POINT", "calendar_id": "calendar:umbra"},
                        {"text": "b", "kind": "POINT", "calendar_id": "calendar:otro"},
                    ]
                )
            ]
        )
    )
    assert decision.decision == "REVIEW"
    assert "TEMPORAL_CALENDAR_MIXED" in codes(decision)


def test_an_inverted_interval_goes_to_review():
    decision = only(
        run(
            [
                claim(
                    temporal_expressions=[
                        {
                            "text": "mal anclado",
                            "kind": "INTERVAL",
                            "valid_from": "1050-01-01T00:00:00Z",
                            "valid_to": "1042-01-01T00:00:00Z",
                        }
                    ]
                )
            ]
        )
    )
    assert decision.decision == "REVIEW"
    assert "TEMPORAL_INTERVAL_INVERTED" in codes(decision)


def test_contradictory_temporal_expressions_go_to_review():
    decision = only(
        run(
            [
                claim(
                    temporal_expressions=[
                        {"text": "a", "kind": "POINT", "valid_from": "1042-01-01T00:00:00Z"},
                        {"text": "b", "kind": "POINT", "valid_from": "1099-01-01T00:00:00Z"},
                    ]
                )
            ]
        )
    )
    assert decision.decision == "REVIEW"
    assert "TEMPORAL_CONFLICTING_EXPRESSIONS" in codes(decision)


def test_an_unanchored_relative_expression_is_a_warning_not_a_date():
    result = run([claim(temporal_expressions=[{"text": "tres lunas despues", "kind": "RELATIVE"}])])
    decision = only(result)
    assert decision.decision == "ACCEPT"
    assert "TEMPORAL_UNRESOLVED_RELATIVE" in codes(decision)
    assert result.assertions[0].state == "UNKNOWN"
    assert result.assertions[0].event_time is None


def test_a_temporal_expression_citing_an_unknown_fragment_goes_to_review():
    decision = only(
        run(
            [
                claim(
                    temporal_expressions=[
                        {"text": "en el ciclo 1042", "kind": "POINT", "fragment_id": "fragment:no"}
                    ]
                )
            ]
        )
    )
    assert decision.decision == "REVIEW"
    assert "TEMPORAL_FRAGMENT_UNKNOWN" in codes(decision)


def test_an_intention_is_planned_not_active():
    config = EngineConfig(acceptable_epistemic_status=frozenset({"ASSERTED", "INTENDED"}))
    result = run(
        [
            claim(
                epistemic_status_hint="INTENDED",
                temporal_expressions=[
                    {"text": "el proximo ciclo", "kind": "POINT", "valid_from": "1060-01-01T00:00:00Z"}
                ],
            )
        ],
        config=config,
    )
    assert result.assertions[0].state == "PLANNED"


# ==========================================================================
# 9. Eje CONTRADICCION
# ==========================================================================
def test_the_opposite_of_what_the_graph_says_goes_to_review():
    decision = only(run(snap=snapshot(assertions=[vigente(negated=True)])))
    assert decision.decision == "REVIEW"
    assert "CONFLICT_WITH_EXISTING" in codes(decision)
    assert "CONTRADICTS_VIGENTE_ASSERTION" in codes(decision)


def test_a_contradiction_is_never_auto_approved_however_confident():
    perfect = claim(
        confidence=1.0,
        predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 1.0}],
        direction_candidates=[{"direction": "SUBJECT_TO_OBJECT", "confidence": 1.0}],
    )
    result = run([perfect], snap=snapshot(assertions=[vigente(negated=True)]))
    assert only(result).decision == "REVIEW"
    assert result.plan is None or not result.plan.approved


def test_the_inverse_predicate_is_the_same_fact_and_the_conflict_is_seen():
    inverse = vigente(
        assertion_id="assertion:inversa",
        subject_entity_id="entity:casa-ciervo",
        object_entity_id="entity:daiki",
        predicate="HAS_MEMBER",
        negated=True,
    )
    decision = only(run(snap=snapshot(assertions=[inverse])))
    assert decision.decision == "REVIEW"
    assert "CONTRADICTS_VIGENTE_ASSERTION" in codes(decision)


def test_a_symmetric_pair_said_backwards_is_a_duplicate_not_a_new_fact():
    existing = vigente(
        assertion_id="assertion:ally",
        subject_entity_id="entity:casa-ciervo",
        object_entity_id="entity:daiki",
        predicate="ALLY_OF",
        direction="UNDIRECTED",
    )
    result = run(
        [claim(predicate_candidates=[{"predicate": "ALLY_OF", "confidence": 0.9}])],
        snap=snapshot(assertions=[existing]),
    )
    decision = only(result)
    assert decision.decision == "ACCEPT"
    assert "ALREADY_ASSERTED" in codes(decision)
    assert result.assertions == ()
    assert not result.approved


def test_an_inverted_direction_against_the_graph_is_a_conflict():
    existing = vigente(
        assertion_id="assertion:serves",
        subject_entity_id="entity:casa-ciervo",
        object_entity_id="entity:daiki",
        predicate="SERVES",
    )
    decision = only(
        run(
            [claim(predicate_candidates=[{"predicate": "SERVES", "confidence": 0.9}])],
            snap=snapshot(assertions=[existing]),
        )
    )
    assert decision.decision == "REVIEW"
    assert "DIRECTION_CONFLICT_WITH_VIGENTE" in codes(decision)


def test_a_functional_predicate_pointing_somewhere_else_is_a_conflict():
    existing = vigente(
        assertion_id="assertion:located",
        subject_entity_id="entity:daiki",
        object_entity_id="entity:puerto-sal",
        predicate="LOCATED_IN",
    )
    decision = only(
        run(
            [
                claim(
                    object_mentions=["mention:torre"],
                    predicate_candidates=[{"predicate": "LOCATED_IN", "confidence": 0.9}],
                )
            ],
            snap=snapshot(assertions=[existing]),
        )
    )
    assert decision.decision == "REVIEW"
    assert "FUNCTIONAL_PREDICATE_CONFLICT" in codes(decision)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "SUPERSEDED", "state": "ACTIVE"},
        {"status": "RETRACTED", "state": "ACTIVE"},
        {"status": "ASSERTED", "state": "ENDED"},
    ],
)
def test_a_dead_assertion_contradicts_nobody(overrides):
    decision = only(run(snap=snapshot(assertions=[vigente(negated=True, **overrides)])))
    assert decision.decision == "ACCEPT"


def test_the_canonical_key_collapses_orientation_symmetry_and_inverse():
    index = ProfileIndex(profile())
    assert canonical_key(index, "a", "b", "MEMBER_OF", "SUBJECT_TO_OBJECT") == canonical_key(
        index, "b", "a", "MEMBER_OF", "OBJECT_TO_SUBJECT"
    )
    assert canonical_key(index, "a", "b", "ALLY_OF", "UNDIRECTED") == canonical_key(
        index, "b", "a", "ALLY_OF", "UNDIRECTED"
    )
    assert canonical_key(index, "a", "b", "MEMBER_OF", "SUBJECT_TO_OBJECT") == canonical_key(
        index, "b", "a", "HAS_MEMBER", "SUBJECT_TO_OBJECT"
    )


# ==========================================================================
# 10. Plan de mutacion
# ==========================================================================
def test_the_plan_is_sealed_with_the_frozen_validator():
    plan = run().plan
    assert isinstance(plan, GraphMutationPlan)
    assert plan.signature_is_intact()
    assert plan.local_approval["decision_hash"] == V.compute_decision_hash(plan.to_dict())
    assert plan.plan_hash == V.compute_plan_hash(plan.to_dict())
    plan.validate()


def test_the_idempotency_keys_are_derived_not_invented():
    plan = run().plan
    assert plan.idempotency_keys() == plan.expected_idempotency_keys()
    assert len(set(plan.idempotency_keys())) == len(plan.idempotency_keys())


def test_the_same_input_produces_byte_identical_plans():
    first, second = run().plan, run().plan
    assert first.to_json() == second.to_json()


def test_the_plan_is_signed_by_the_local_engine():
    plan = run().plan
    assert plan.signed_locally()
    assert plan.approved
    assert plan.is_authenticated() is False  # honestidad: verificable, no autenticado


def test_creations_carry_no_expected_state_and_updates_do():
    plan = run().plan
    by_type = {op["operation_type"]: op for op in plan.mutation_operations}
    assert by_type["CREATE_ASSERTION"]["expected_version"] is None
    assert by_type["PROJECT_RELATION"]["expected_version"] == 3  # version del snapshot
    assert by_type["PROJECT_RELATION"]["expected_hash"] is not None


def test_the_plan_anchors_the_snapshot_and_expires():
    plan = run().plan
    assert plan.snapshot_id == "snapshot:gold:0001"
    assert plan.created_at == NOW
    assert plan.expires_at == "2026-07-28T10:30:00Z"


def test_every_operation_hangs_from_an_accept():
    plan = run().plan
    accepted = {d["decision_id"] for d in plan.decisions if d["decision"] == "ACCEPT"}
    assert {op["decision_id"] for op in plan.mutation_operations} <= accepted


def test_review_decisions_travel_in_their_own_unapproved_plan():
    result = run([claim(), claim(claim_id="claim:gold:1", review_required=True)])
    assert result.plan.approved is True
    assert result.review_plan is not None
    assert result.review_plan.approved is False
    assert result.review_plan.mutation_operations == []
    result.review_plan.validate()


def test_without_splitting_a_single_review_blocks_the_whole_batch():
    result = run(
        [claim(), claim(claim_id="claim:gold:1", review_required=True)],
        config=EngineConfig(split_review_plan=False),
    )
    assert result.plan.approved is False
    assert result.review_plan is None


def test_a_batch_with_nothing_to_write_produces_no_write_plan():
    result = run([claim(review_required=True)])
    assert result.plan is None
    assert result.review_plan is not None


def test_the_derived_assertions_validate_against_the_frozen_contract():
    for assertion in run().assertions:
        assertion.validate()


def test_the_assertion_id_is_derived_from_the_fact_not_from_the_run():
    first = run().assertions[0].assertion_id
    second = run(now="2027-01-01T00:00:00Z").assertions[0].assertion_id
    assert first == second


def test_tampering_the_sealed_plan_breaks_its_signature():
    plan = run().plan
    tampered = GraphMutationPlan.from_dict(
        {**plan.to_dict(), "workspace": "otro-workspace"}, validate=False
    )
    assert not tampered.signature_is_intact()


def test_the_validator_chain_is_recorded_in_the_approval():
    plan = run().plan
    names = [v["validator"] for v in plan.local_approval["validator_chain"]]
    assert names == ["structural", "semantic", "ontology", "contradiction", "authority", "concurrency"]
    assert all(v["result"] == "PASS" for v in plan.local_approval["validator_chain"])


def test_projection_can_be_switched_off():
    plan = run(config=EngineConfig(emit_projection=False)).plan
    assert [op["operation_type"] for op in plan.mutation_operations] == ["CREATE_ASSERTION"]


# ==========================================================================
# 11. Aislamiento y entradas
# ==========================================================================
def test_a_batch_mixing_workspaces_is_blocked():
    with pytest.raises(EngineInputError, match="workspaces mezclados"):
        run([claim(), claim(claim_id="claim:otro", workspace="otro")])


def test_a_profile_from_another_workspace_is_blocked():
    with pytest.raises(EngineInputError, match="workspace"):
        run(eng=engine(workspace="otro"))


def test_a_snapshot_from_another_workspace_is_blocked():
    with pytest.raises(EngineInputError, match="snapshot"):
        run(snap=snapshot(workspace="otro"))


def test_a_batch_mixing_assets_is_blocked():
    with pytest.raises(EngineInputError, match="source_asset_id"):
        run([claim(), claim(claim_id="claim:otro", source_asset_id="asset:otro")])


def test_an_invalid_input_document_is_blocked_not_decided():
    from test_knowledge_v3_engine_gold import claim_raw

    with pytest.raises(EngineInputError, match="invalido"):
        run([claim_raw(confidence=1.5)])


def test_an_empty_batch_is_blocked():
    with pytest.raises(EngineInputError, match="no hay claims"):
        run([])


def test_an_ontology_version_that_does_not_match_the_profile_is_blocked():
    with pytest.raises(EngineInputError, match="ontology_version"):
        run(config=EngineConfig(ontology_version="core-9.9.9"))


def test_the_neo4j_snapshot_is_declared_but_refuses_to_pretend():
    with pytest.raises(NotImplementedError, match="no implementado"):
        Neo4jReadOnlyGraphSnapshot()


# ==========================================================================
# 12. Autoridad: quien propone y quien decide
# ==========================================================================
def test_a_claim_proposed_by_an_external_provider_is_flagged():
    external = claim_dict(
        provider_trace=[
            {
                "step": "extract.external",
                "provider": "external",
                "name": "s9k.external_ai.nvidia",
                "version": "3.0.0",
                "model": "meta/llama-3.1-70b-instruct",
                "produced": ["predicate_candidates"],
            }
        ],
        produced_by_step="extract.external",
    )
    from knowledge_v3.contracts import ClaimProposal

    decision = only(run([ClaimProposal.from_dict(external)]))
    assert decision.decision == "ACCEPT"
    assert "EXTERNAL_PROPOSAL" in codes(decision)
    assert "LOCAL_APPROVED_WITH_WARNINGS" in codes(decision)


def test_a_signal_that_agrees_changes_nothing_but_is_traced():
    signal = ExternalSignal(
        claim_id="claim:gold:0",
        step="signal.ollama",
        provider="ollama",
        name="s9k.signal.ollama",
        version="1.0.0",
        model="qwen2.5:7b",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        confidence=0.99,
    )
    result = run(signals=[signal])
    assert only(result).decision == "ACCEPT"
    assert "EXTERNAL_SIGNAL_CONSULTED" in codes(only(result))
    steps = [entry["step"] for entry in result.plan.provider_trace]
    assert "signal.ollama" in steps
    assert [e for e in result.plan.provider_trace if e["step"] == "signal.ollama"][0][
        "provider"
    ] == "ollama"


def test_a_signal_that_dissents_can_only_make_things_stricter():
    signal = ExternalSignal(
        claim_id="claim:gold:0",
        step="signal.nvidia",
        provider="external",
        name="s9k.signal.nvidia",
        version="1.0.0",
        predicate="ALLY_OF",
        confidence=1.0,
    )
    decision = only(run(signals=[signal]))
    assert decision.decision == "REVIEW"
    assert "EXTERNAL_SIGNAL_DISSENTS" in codes(decision)
    assert decision.predicate == "MEMBER_OF"  # decide el motor, no la senal


def test_a_signal_alone_can_never_produce_an_acceptance():
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
    result = run([claim(predicate_candidates=[])], signals=[signal])
    assert only(result).decision == "ABSTAIN"
    assert result.plan is None or not result.plan.approved


def test_a_local_signal_is_a_contradiction_in_terms():
    with pytest.raises(ValueError, match="senal"):
        ExternalSignal(
            claim_id="claim:gold:0",
            step="signal.local",
            provider="local",
            name="s9k.rules",
            version="1.0.0",
        )


# ==========================================================================
# 13. Cobertura del mapa de decisiones del dosier §11.7
# ==========================================================================
def test_the_engine_can_reach_every_dossier_decision():
    """Las diez decisiones del dosier 11.7, cada una atada a SU escenario.

    Antes esta comprobacion acumulaba todas las decisiones en un conjunto
    global y solo exigia que cada par apareciese en ALGUNA parte: un escenario
    podia dejar de producir lo suyo sin que nadie se enterase, porque otro se lo
    tapaba. Ahora cada escenario declara que decision y que razon canonica debe
    producir, y falla el escenario concreto que se rompa.
    """
    scenarios = {
        "LOCAL_APPROVED": run(),
        "LOCAL_APPROVED_WITH_WARNINGS": run(
            [
                claim(
                    negated=True,
                    object_mentions=["mention:consejo"],
                    predicate_candidates=[{"predicate": "SERVES", "confidence": 0.85}],
                    evidence_fragment_ids=["fragment:gold:1"],
                )
            ]
        ),
        "REVIEW_ENTITY": run([claim(subject_mentions=["mention:fantasma"])]),
        "REVIEW_PREDICATE": run(
            [claim(predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 0.4}])]
        ),
        "REVIEW_DIRECTION": run(
            [claim(direction_candidates=[{"direction": "UNDIRECTED", "confidence": 0.9}])]
        ),
        "REVIEW_TEMPORALITY": run(
            [
                claim(
                    temporal_expressions=[
                        {"text": "x", "kind": "POINT", "calendar_id": "calendar:inventado"}
                    ]
                )
            ]
        ),
        "REVIEW_EVIDENCE": run([claim(review_required=True)]),
        "CONFLICT": run(snap=snapshot(assertions=[vigente(negated=True)])),
        "ABSTAIN": run([claim(evidence_fragment_ids=["fragment:inventado"])]),
        "REJECT_INVALID": run(
            [claim(predicate_candidates=[{"predicate": "GOBIERNA_EN", "confidence": 0.9}])]
        ),
    }
    assert set(scenarios) == set(V.ENGINE_DECISION_MAP), "faltan escenarios del dosier"

    for dossier_decision, result in scenarios.items():
        expected_decision, expected_reason = V.ENGINE_DECISION_MAP[dossier_decision]
        decision = only(result)
        assert decision.decision == expected_decision, dossier_decision
        assert expected_reason in codes(decision), dossier_decision


# ==========================================================================
# 14. Hallazgos de la revision independiente (H1-H6)
# ==========================================================================
def _opposite_pair():
    """El par exacto del revisor: el mismo hecho afirmado y negado en un lote."""
    return [
        claim(claim_id="claim:batch:si", negated=False),
        claim(claim_id="claim:batch:no", negated=True, epistemic_cues=["jamas"]),
    ]


def test_h1_two_opposite_claims_in_the_same_batch_never_both_accept():
    result = run(_opposite_pair())
    assert [d.decision for d in result.decisions] == ["REVIEW", "REVIEW"]
    for decision in result.decisions:
        assert "CONFLICT_WITH_EXISTING" in codes(decision)
        assert "CONTRADICTS_CLAIM_IN_BATCH" in codes(decision)
    assert result.plan is None
    assert result.review_plan is not None and result.review_plan.approved is False


def test_h1_the_inverse_predicate_variant_inside_the_batch_is_also_caught():
    batch = [
        claim(claim_id="claim:batch:member", negated=False),
        claim(
            claim_id="claim:batch:hasmember",
            subject_mentions=["mention:casa"],
            object_mentions=["mention:daiki"],
            negated=True,
            predicate_candidates=[{"predicate": "HAS_MEMBER", "confidence": 0.85}],
        ),
    ]
    result = run(batch)
    assert [d.decision for d in result.decisions] == ["REVIEW", "REVIEW"]
    assert all("CONTRADICTS_CLAIM_IN_BATCH" in codes(d) for d in result.decisions)


def test_h1_a_batch_contradiction_marks_the_claims_as_conflicted():
    for decision in run(_opposite_pair()).decisions:
        assert decision.epistemic_status == "CONFLICTED"


def test_h1_the_same_claim_twice_in_a_batch_is_written_once():
    result = run([claim(claim_id="claim:a"), claim(claim_id="claim:b")])
    assert [d.decision for d in result.decisions] == ["ACCEPT", "ACCEPT"]
    assert "DUPLICATE_IN_BATCH" in codes(result.decisions[1])
    assert len(result.assertions) == 1
    assert result.plan.approved is True


def test_h1_an_inverted_direction_inside_the_batch_is_a_conflict():
    batch = [
        claim(claim_id="claim:s2o", predicate_candidates=[{"predicate": "OWES_TO", "confidence": 0.9}]),
        claim(
            claim_id="claim:o2s",
            subject_mentions=["mention:casa"],
            object_mentions=["mention:daiki"],
            predicate_candidates=[{"predicate": "OWES_TO", "confidence": 0.9}],
        ),
    ]
    result = run(batch)
    assert [d.decision for d in result.decisions] == ["REVIEW", "REVIEW"]
    assert all("DIRECTION_CONFLICT_IN_BATCH" in codes(d) for d in result.decisions)


def test_h1_a_functional_predicate_with_two_objects_in_the_batch_is_a_conflict():
    batch = [
        claim(
            claim_id="claim:torre",
            object_mentions=["mention:torre"],
            predicate_candidates=[{"predicate": "LOCATED_IN", "confidence": 0.9}],
        ),
        claim(
            claim_id="claim:puerto",
            object_mentions=["mention:puerto"],
            predicate_candidates=[{"predicate": "LOCATED_IN", "confidence": 0.9}],
        ),
    ]
    result = run(batch, resolutions=[*DEFAULT_RESOLUTIONS(), resolution_puerto()])
    assert [d.decision for d in result.decisions] == ["REVIEW", "REVIEW"]
    assert all("FUNCTIONAL_CONFLICT_IN_BATCH" in codes(d) for d in result.decisions)


def test_h1b_the_plan_validator_checks_the_plan_against_itself():
    """Defensa en profundidad: el validador mira el artefacto, no la decision."""
    index = ProfileIndex(profile())
    coherent = run().plan.mutation_operations
    assert plan_is_self_consistent(coherent, index) is True

    incoherent = [op for op in coherent if op["operation_type"] == "CREATE_ASSERTION"]
    twin = deepcopy(incoherent[0])
    twin["operation_id"] = "op:twin"
    twin["payload"] = {**twin["payload"], "negated": True}
    assert plan_is_self_consistent([*incoherent, twin], index) is False


def test_h2_reaffirming_a_contradicted_assertion_goes_to_review():
    """Reprocesar el asset no puede saltarse la cola humana."""
    marked = vigente(assertion_id="assertion:enconflicto", status="CONTRADICTED")
    decision = only(run(snap=snapshot(assertions=[marked])))
    assert decision.decision == "REVIEW"
    assert "CONFLICT_WITH_EXISTING" in codes(decision)
    assert "REAFFIRMS_CONTRADICTED_ASSERTION" in codes(decision)


def test_h2_history_is_still_history():
    for status in ("SUPERSEDED", "RETRACTED"):
        decision = only(run(snap=snapshot(assertions=[vigente(status=status)])))
        assert decision.decision == "ACCEPT", status


def test_h3_the_confidence_never_exceeds_the_evidence_that_supports_it():
    weak = fragment(confidence=0.50)
    result = run(
        [
            claim(
                confidence=0.99,
                predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 0.99}],
                direction_candidates=[{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.99}],
            )
        ],
        fragments=[weak],
    )
    decision = only(result)
    assert decision.confidence == 0.5
    assert result.assertions[0].confidence == 0.5


def test_h3_the_episode_quality_also_caps_the_confidence():
    result = run(
        [claim(confidence=0.99, predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 0.99}],
               direction_candidates=[{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.99}])],
        episodes=[episode(quality={"score": 0.6, "flags": []})],
    )
    assert only(result).confidence == 0.6


@pytest.mark.parametrize(
    "acceptable",
    [
        frozenset({"RUMORED", "UNKNOWN"}),  # el ataque exacto del revisor
        frozenset({"ASSERTED", "UNKNOWN"}),
        frozenset({"ASSERTED", "CONFLICTED"}),
        frozenset({"RUMORED"}),
    ],
)
def test_h4_a_configuration_that_would_rubber_stamp_is_rejected(acceptable):
    with pytest.raises(ValueError):
        EngineConfig(acceptable_epistemic_status=acceptable)


def test_h4_no_threshold_can_go_below_the_hard_confidence_floor():
    permissive = EngineConfig(
        min_claim_confidence=0.0,
        min_predicate_confidence=0.0,
        min_predicate_margin=0.0,
        min_direction_confidence=0.0,
        min_resolution_confidence=0.0,
        min_episode_quality=0.0,
        min_fragment_confidence=0.0,
        acceptable_epistemic_status=frozenset({"ASSERTED", "RUMORED"}),
    )
    decision = only(
        run(
            [
                claim(
                    confidence=0.05,
                    epistemic_status_hint="RUMORED",
                    predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 0.05}],
                )
            ],
            config=permissive,
        )
    )
    assert decision.decision == "REVIEW"
    assert "CONFIDENCE_BELOW_HARD_FLOOR" in codes(decision)


def test_h5_a_signal_cannot_name_itself_after_an_engine_step():
    with pytest.raises(ValueError, match="RESERVADO"):
        ExternalSignal(
            claim_id="claim:gold:0",
            step="engine.decide",
            provider="ollama",
            name="s9k.signal.ollama",
            version="1.0.0",
        )


def test_h5_a_forged_signal_step_is_renamed_before_entering_the_trace():
    signal = ExternalSignal(
        claim_id="claim:gold:0",
        step="signal.ollama",
        provider="ollama",
        name="s9k.signal.ollama",
        version="1.0.0",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
    )
    object.__setattr__(signal, "step", "engine.decide")  # se salta la validacion
    plan = run(signals=[signal]).plan
    reserved = {"engine.decide", "engine.plan"}
    assert all(
        e["provider"] == "local" for e in plan.provider_trace if e["step"] in reserved
    ), "una senal se ha colado en un paso del motor"
    renamed = [e for e in plan.provider_trace if e["step"] == "signal.engine.decide"]
    assert [e["provider"] for e in renamed] == ["ollama"]


def test_h6_the_provider_is_revalidated_when_the_signal_enters_a_document():
    signal = ExternalSignal(
        claim_id="claim:gold:0",
        step="signal.ollama",
        provider="ollama",
        name="s9k.signal.ollama",
        version="1.0.0",
    )
    object.__setattr__(signal, "provider", "local")
    with pytest.raises(ValueError, match="senal"):
        signal.trace_entry()
