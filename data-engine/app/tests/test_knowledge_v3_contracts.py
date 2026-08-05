# -*- coding: utf-8 -*-
"""Modelos Python de los contratos `v3-internal-v1`.

Roundtrip, serializacion estable y pruebas de mutacion sobre los dataclasses.
Los mismos documentos que valida el gate de JSON Schema
(`contracts/knowledge-v3/v1/tests/`) se validan aqui a traves de los modelos:
un solo cuerpo de ejemplos, dos puertas.
"""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import (  # noqa: E402
    CONTRACT_CLASSES,
    CONTRACT_VERSION,
    CONTRACTS_DIR,
    ClaimProposal,
    EntityMention,
    EntityResolution,
    EvidenceFragment,
    FactAssertion,
    GameProfile,
    GraphMutationPlan,
    Provider,
    SourceAsset,
    SourceEpisode,
    V3ContractError,
    canonical_json,
    parse_document,
    provider_step,
    seal_plan,
)


def _load_fixtures():
    path = CONTRACTS_DIR / "tests" / "v3_fixtures.py"
    spec = importlib.util.spec_from_file_location("s9k_v3_fixtures", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s9k_v3_fixtures"] = mod
    spec.loader.exec_module(mod)
    return mod


fixtures = _load_fixtures()

#: Fixture -> clase esperada. Cubre los nueve contratos.
CASES = {
    "source_asset_pdf": SourceAsset,
    "source_asset_personal_audio": SourceAsset,
    "source_episode_text": SourceEpisode,
    "source_episode_audio": SourceEpisode,
    "source_episode_table": SourceEpisode,
    "evidence_fragment_text": EvidenceFragment,
    "evidence_fragment_ocr": EvidenceFragment,
    "evidence_fragment_htr": EvidenceFragment,
    "entity_mention": EntityMention,
    "claim_proposal": ClaimProposal,
    "claim_proposal_abstained": ClaimProposal,
    "claim_proposal_visual": ClaimProposal,
    "entity_resolution_link": EntityResolution,
    "entity_resolution_provisional": EntityResolution,
    "fact_assertion": FactAssertion,
    "fact_assertion_superseded": FactAssertion,
    "fact_assertion_conflicted": FactAssertion,
    "graph_mutation_plan_approved": GraphMutationPlan,
    "graph_mutation_plan_not_approved": GraphMutationPlan,
    "game_profile_generic": GameProfile,
}


def doc(name: str) -> dict:
    return fixtures.VALID_BUILDERS[name]()


# ==========================================================================
# Cobertura de la familia
# ==========================================================================
def test_nine_contracts_registered():
    assert len(CONTRACT_CLASSES) == 9
    assert set(CASES.values()) == set(CONTRACT_CLASSES.values())


def test_contract_ids_match_the_json_schemas():
    from knowledge_v3.contracts.base import schema_validator

    assert set(CONTRACT_CLASSES) == set(schema_validator.CONTRACT_SCHEMAS)


def test_contract_version_is_the_v1_of_the_v3_family():
    assert CONTRACT_VERSION.startswith("1.")
    for name in CASES:
        assert doc(name)["contract_version"] == CONTRACT_VERSION


def test_provider_kinds_are_exactly_three():
    assert {p.value for p in Provider} == {"local", "ollama", "external"}


def test_provider_step_builds_a_valid_entry():
    entry = provider_step("x", Provider.OLLAMA, "s9k.extractor", "3.0.0", ["claim"], model="qwen2.5:7b")
    assert entry["provider"] == "ollama"
    assert entry["produced"] == ["claim"]


# ==========================================================================
# Roundtrip y determinismo
# ==========================================================================
@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_roundtrip_dict_is_exact(name: str):
    cls = CASES[name]
    obj = cls.from_dict(doc(name))
    assert obj.to_dict() == doc(name)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_roundtrip_json_returns_an_identical_object(name: str):
    cls = CASES[name]
    obj = cls.from_dict(doc(name))
    again = cls.from_json(obj.to_json())
    assert again == obj
    assert again.to_json() == obj.to_json()


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_serialization_is_byte_stable(name: str):
    cls = CASES[name]
    obj = cls.from_dict(doc(name))
    first = obj.to_json()
    for _ in range(3):
        assert obj.to_json() == first
    # Reconstruir desde un dict con las claves en otro orden no cambia un byte.
    shuffled = {k: v for k, v in reversed(list(doc(name).items()))}
    assert cls.from_dict(shuffled).to_json() == first


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_json_is_canonical(name: str):
    obj = CASES[name].from_dict(doc(name))
    raw = obj.to_json()
    assert raw == canonical_json(json.loads(raw))
    # Claves ordenadas en el nivel raiz: el orden no depende del dataclass.
    keys = list(json.loads(raw))
    assert keys == sorted(keys)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_parse_document_dispatches_by_contract_id(name: str):
    obj = parse_document(doc(name))
    assert isinstance(obj, CASES[name])


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_document_hash_is_reproducible(name: str):
    a = CASES[name].from_dict(doc(name))
    b = CASES[name].from_dict(doc(name))
    assert a.document_hash() == b.document_hash()


# ==========================================================================
# Mutacion: el contrato es CERRADO
# ==========================================================================
@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_unknown_field_is_rejected(name: str):
    data = doc(name)
    data["campo_que_no_existe"] = 1
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize(
    "field",
    ["workspace", "contract_version", "source_hash", "provider_trace",
     "source_asset_id", "produced_by_step"],
)
@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_missing_envelope_field_is_rejected(name: str, field: str):
    data = doc(name)
    data.pop(field)
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_wrong_contract_id_is_rejected(name: str):
    data = doc(name)
    data["contract_id"] = "source-asset/v3-internal-v2"
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_wrong_major_version_is_rejected(name: str):
    data = doc(name)
    data["contract_version"] = "2.0.0"
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_empty_workspace_is_rejected(name: str):
    data = doc(name)
    data["workspace"] = ""
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_hash_without_algorithm_is_rejected(name: str):
    data = doc(name)
    data["source_hash"] = {"value": "0" * 64}
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_secret_in_metadata_is_rejected(name: str):
    data = doc(name)
    data["metadata"] = {"password": "hunter2"}
    with pytest.raises(V3ContractError):
        CASES[name].from_dict(data)


def test_from_dict_of_another_contract_is_rejected():
    with pytest.raises(V3ContractError):
        SourceAsset.from_dict(doc("entity_mention"))


def test_parse_document_without_contract_id_is_rejected():
    with pytest.raises(V3ContractError):
        parse_document({"workspace": "leyenda"})


def test_from_json_rejects_broken_json():
    with pytest.raises(V3ContractError):
        SourceAsset.from_json("{no es json")


# ==========================================================================
# Reglas semanticas a traves de los modelos
# ==========================================================================
def test_asset_policy_helper():
    asset = SourceAsset.from_dict(doc("source_asset_pdf"))
    assert asset.allows_external_providers() is False


def test_personal_data_asset_cannot_open_external_providers():
    data = doc("source_asset_personal_audio")
    data["processing_policy"]["allow_external_providers"] = True
    with pytest.raises(V3ContractError):
        SourceAsset.from_dict(data)


def test_mention_best_type():
    mention = EntityMention.from_dict(doc("entity_mention"))
    assert mention.best_type() == "Character"


def test_claim_helpers():
    claim = ClaimProposal.from_dict(doc("claim_proposal"))
    assert claim.best_predicate() == "MEMBER_OF"
    assert claim.best_direction() == "SUBJECT_TO_OBJECT"
    assert claim.producing_provider()["provider"] == "ollama"


def test_abstained_claim_cannot_propose_a_predicate():
    data = doc("claim_proposal_abstained")
    data["predicate_candidates"] = [{"predicate": "MEMBER_OF", "confidence": 0.9}]
    with pytest.raises(V3ContractError):
        ClaimProposal.from_dict(data)


def test_provisional_resolution_helper():
    res = EntityResolution.from_dict(doc("entity_resolution_provisional"))
    assert res.is_provisional() is True
    assert res.selected_entity_id is None


def test_assertion_open_interval():
    a = FactAssertion.from_dict(doc("fact_assertion"))
    assert a.is_open_interval() is True
    b = FactAssertion.from_dict(doc("fact_assertion_superseded"))
    assert b.is_open_interval() is False


def test_game_profile_domain_and_range():
    profile = GameProfile.from_dict(doc("game_profile_generic"))
    assert profile.allows("MEMBER_OF", "Character", "Faction") is True
    assert profile.allows("MEMBER_OF", "Location", "Faction") is False
    assert "HAS_MEMBER" in profile.predicate_names()


# ==========================================================================
# GraphMutationPlan: lo que el writer exigira
# ==========================================================================
def test_plan_is_signed_locally_and_intact():
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_approved"))
    assert plan.approved is True
    assert plan.signed_locally() is True
    assert plan.signature_is_intact() is True
    # La clave declarada es EXACTAMENTE la derivada: no vale inventarsela.
    assert plan.idempotency_keys() == plan.expected_idempotency_keys()
    assert plan.idempotency_keys()[0].startswith("idem:sha256:")
    # Verificable no es autenticado: sin signature/key_id no hay firma real.
    assert plan.is_authenticated() is False


def test_plan_sealing_is_idempotent():
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_approved"))
    assert plan.sealed().to_json() == plan.to_json()


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace", "otro"),
        ("source_asset_id", "asset:otro"),
        ("engine_version", "0.0.1"),
        ("ontology_version", "core-0.0.1"),
        ("game_profile", "otro"),
        ("collection_id", "collection:otra"),
    ],
)
def test_tampering_a_signed_field_breaks_the_plan(field, value):
    data = doc("graph_mutation_plan_approved")
    data[field] = value
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(data)


def test_plan_without_signature_is_rejected():
    data = doc("graph_mutation_plan_approved")
    data.pop("local_approval")
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_plan_signed_by_an_external_provider_is_rejected():
    data = doc("graph_mutation_plan_approved")
    data["local_approval"]["approved_by"]["provider"] = "external"
    # Resellado: se prueba la regla del firmante, no la deteccion de manipulacion.
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_plan_with_duplicate_idempotency_key_is_rejected():
    data = doc("graph_mutation_plan_approved")
    op = dict(data["mutation_operations"][0], operation_id="op:0002")
    data["mutation_operations"].append(op)
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_plan_operation_must_hang_from_an_accept_decision():
    data = doc("graph_mutation_plan_approved")
    data["mutation_operations"][0]["decision_id"] = "decision:0002"  # ABSTAIN
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(seal_plan(data))


def test_not_approved_plan_is_a_legitimate_document():
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_not_approved"))
    assert plan.approved is False
    assert plan.signature_is_intact() is True


# ==========================================================================
# Ronda de correcciones: hallazgos del revisor independiente
# ==========================================================================
def test_producing_provider_uses_the_declared_step():
    """H3 — referencia explicita, no heuristica sobre `produced`."""
    claim = ClaimProposal.from_dict(doc("claim_proposal_visual"))
    entry = claim.producing_provider()
    assert entry["step"] == claim.produced_by_step
    assert entry["provider"] == "external"


def test_best_direction_is_stable_with_tied_confidences():
    """H4 — `max()` devolvia lo que hubiese llegado antes."""
    claim = ClaimProposal.from_dict(doc("claim_proposal"))
    claim.direction_candidates = [
        {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.5},
        {"direction": "UNDIRECTED", "confidence": 0.5},
    ]
    claim.validate()
    assert claim.best_direction() == "SUBJECT_TO_OBJECT"


def test_unordered_candidates_are_rejected_by_the_model():
    claim = ClaimProposal.from_dict(doc("claim_proposal"))
    claim.direction_candidates = [
        {"direction": "UNDIRECTED", "confidence": 0.5},
        {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.5},
    ]
    with pytest.raises(V3ContractError):
        claim.validate()


def test_assertion_exposes_both_temporal_axes():
    """H2 — `state` y `status` conviven; ninguno sustituye al otro."""
    a = FactAssertion.from_dict(doc("fact_assertion"))
    assert (a.state, a.status) == ("ACTIVE", "ASSERTED")
    assert a.event_time == "1042-03-01T00:00:00Z"
    assert a.negated is False
    b = FactAssertion.from_dict(doc("fact_assertion_superseded"))
    assert (b.state, b.status) == ("ENDED", "SUPERSEDED")


def test_conflicted_assertion_is_representable():
    """H1 — el motor ya puede emitir un estado en conflicto."""
    a = FactAssertion.from_dict(doc("fact_assertion_conflicted"))
    assert a.epistemic_status == "CONFLICTED"


@pytest.mark.parametrize("field", ["state", "event_time", "negated"])
def test_assertion_new_fields_are_required_in_the_model(field):
    """H2 y H5 — required de verdad, no opcionales con default."""
    data = doc("fact_assertion")
    data.pop(field)
    with pytest.raises(V3ContractError):
        FactAssertion.from_dict(data)


def test_resolution_entity_type_is_required_in_the_model():
    """H5 — puede valer null; lo que no puede es faltar."""
    data = doc("entity_resolution_link")
    data.pop("entity_type")
    with pytest.raises(V3ContractError):
        EntityResolution.from_dict(data)


def test_resolution_entity_id_helper():
    """H6 — la identidad la fija la resolucion, no una convencion de cadena."""
    link = EntityResolution.from_dict(doc("entity_resolution_link"))
    prov = EntityResolution.from_dict(doc("entity_resolution_provisional"))
    assert link.entity_id() == "entity:daiki"
    assert prov.entity_id() == "entity:prov:consejo-umbra"
    assert prov.assigned_entity_id != prov.selected_entity_id


def test_creating_without_assigned_id_is_rejected_in_the_model():
    data = doc("entity_resolution_provisional")
    data["assigned_entity_id"] = None
    with pytest.raises(V3ContractError):
        EntityResolution.from_dict(data)


def test_plan_snapshot_is_required_in_the_model():
    """H7 — ancla del estado sobre el que se calculo el plan."""
    data = doc("graph_mutation_plan_approved")
    assert data["snapshot_id"]
    data.pop("snapshot_id")
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(data)


def test_plan_idempotency_keys_are_derived():
    """H7 — declaradas == derivadas, o el plan no vale."""
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_approved"))
    assert plan.idempotency_keys() == plan.expected_idempotency_keys()


def test_plan_is_verifiable_but_not_authenticated():
    """H8 — hash correcto no es firma."""
    plan = GraphMutationPlan.from_dict(doc("graph_mutation_plan_approved"))
    assert plan.signature_is_intact() is True
    assert plan.is_authenticated() is False
    data = doc("graph_mutation_plan_approved")
    data["local_approval"]["signature"] = "ed25519:" + "0" * 64
    data["local_approval"]["key_id"] = "key:engine-local-1"
    signed = GraphMutationPlan.from_dict(seal_plan(data))
    assert signed.is_authenticated() is True


def test_changing_approved_breaks_the_decision_hash_in_the_model():
    """H9 — `approved` entra ahora en el hash de decision."""
    data = doc("graph_mutation_plan_approved")
    data["local_approval"]["approved"] = False
    with pytest.raises(V3ContractError):
        GraphMutationPlan.from_dict(data)


def test_episode_speaker_turn_and_table_roundtrip():
    """H12 y H16 — campos nuevos, mismo roundtrip exacto."""
    audio = SourceEpisode.from_dict(doc("source_episode_audio"))
    assert audio.speaker["speaker_id"] == "speaker:02" and audio.turn == 17
    table = SourceEpisode.from_dict(doc("source_episode_table"))
    assert table.table["header"] == ["Casa", "Sede", "Lema"]
    assert SourceEpisode.from_json(table.to_json()) == table


def test_htr_evidence_is_its_own_media_type():
    """H11 — el manuscrito ya no tiene que disfrazarse de OCR."""
    frag = EvidenceFragment.from_dict(doc("evidence_fragment_htr"))
    assert frag.media_type == "HTR_TEXT"


# --------------------------------------------------------------------------
# M0 — docs/v3/49-multipartida-diseno.md: `partida_id` en SourceAsset,
# ClaimProposal y GraphMutationPlan (+ bloque `scope` en el plan). Bajo
# riesgo declarado: campo opcional, sin logica que lo use aun.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,cls",
    [
        ("source_asset_pdf", SourceAsset),
        ("claim_proposal", ClaimProposal),
    ],
)
def test_m0_partida_id_defaults_to_none_and_is_omitted(name, cls):
    """(b) retrocompatibilidad: material existente sin `partida_id` carga tal cual."""
    data = doc(name)
    assert "partida_id" not in data
    obj = cls.from_dict(data)
    assert obj.partida_id is None
    assert "partida_id" not in obj.to_dict()
    assert obj.to_dict() == data


def test_m0_plan_partida_id_and_scope_default_to_none_and_are_omitted():
    data = doc("graph_mutation_plan_approved")
    assert "partida_id" not in data and "scope" not in data
    plan = GraphMutationPlan.from_dict(data)
    assert plan.partida_id is None and plan.scope is None
    assert "partida_id" not in plan.to_dict() and "scope" not in plan.to_dict()
    assert plan.to_dict() == data


@pytest.mark.parametrize(
    "name,cls",
    [
        ("source_asset_pdf", SourceAsset),
        ("claim_proposal", ClaimProposal),
    ],
)
def test_m0_partida_id_travels_through_roundtrip(name, cls):
    """(a) el campo viaja intacto: se fija, se serializa y vuelve igual."""
    data = doc(name)
    data["partida_id"] = "partida:brumal-01"
    obj = cls.from_dict(data)
    assert obj.partida_id == "partida:brumal-01"
    assert obj.to_dict()["partida_id"] == "partida:brumal-01"
    assert cls.from_json(obj.to_json()) == obj


def test_m0_plan_partida_id_and_scope_travel_through_roundtrip():
    data = doc("graph_mutation_plan_approved")
    data["partida_id"] = "partida:brumal-01"
    data["scope"] = {"layer": "PARTIDA", "game_id": data["workspace"], "partida_id": "partida:brumal-01"}
    sealed = seal_plan(data)
    plan = GraphMutationPlan.from_dict(sealed)
    assert plan.partida_id == "partida:brumal-01"
    assert plan.scope == {"layer": "PARTIDA", "game_id": data["workspace"], "partida_id": "partida:brumal-01"}
    assert GraphMutationPlan.from_json(plan.to_json()) == plan


def test_m0_two_plans_differing_only_in_partida_id_have_different_plan_hash():
    """(c) — verificacion del hash, no asuncion (docs/v3/49 §2.2).

    `plan_hash` cubre el documento completo salvo el propio `plan_hash`, asi
    que SI distingue `partida_id` gratis: sella y valida. `decision_hash` NO
    lo distingue (`DECISION_HASH_FIELDS` es una lista curada y cerrada que
    M0 decide NO tocar para no romper `decision_hash` ya congelados en
    datasets gold/held-out) — ese hueco queda documentado como pendiente de
    M3 en `contracts/knowledge-v3/v1/validator.py` y en
    `data-engine/app/knowledge_v3/contracts/mutation_plan.py`, no oculto.
    """
    base = doc("graph_mutation_plan_approved")
    base.pop("plan_hash", None)
    base["local_approval"].pop("decision_hash", None)

    plan_a = seal_plan({**base, "partida_id": "partida:brumal-01"})
    plan_b = seal_plan({**base, "partida_id": "partida:brumal-02"})

    assert plan_a["plan_hash"] != plan_b["plan_hash"]
    # Agujero conocido y documentado, no cerrado en M0 (ver docstring):
    assert plan_a["local_approval"]["decision_hash"] == plan_b["local_approval"]["decision_hash"]

    GraphMutationPlan.from_dict(plan_a)
    GraphMutationPlan.from_dict(plan_b)


def test_m0_two_plans_differing_only_in_scope_have_different_plan_hash():
    base = doc("graph_mutation_plan_approved")
    base.pop("plan_hash", None)
    base["local_approval"].pop("decision_hash", None)

    scope_a = {"layer": "PARTIDA", "game_id": base["workspace"], "partida_id": "partida:brumal-01"}
    scope_b = {"layer": "PARTIDA", "game_id": base["workspace"], "partida_id": "partida:brumal-02"}

    plan_a = seal_plan({**base, "scope": scope_a})
    plan_b = seal_plan({**base, "scope": scope_b})

    assert plan_a["plan_hash"] != plan_b["plan_hash"]
    assert plan_a["local_approval"]["decision_hash"] == plan_b["local_approval"]["decision_hash"]


def test_m0_plan_none_partida_id_matches_a_plan_never_declaring_it():
    """None explicito y ausencia total del campo deben producir el mismo hash:
    `to_dict()` omite el campo cuando vale `None` (mismo patron que `metadata`)."""
    import dataclasses

    without = doc("graph_mutation_plan_approved")
    plan_without = GraphMutationPlan.from_dict(without)
    with_none = dataclasses.replace(plan_without, partida_id=None)
    assert plan_without.to_dict() == with_none.to_dict()
    assert plan_without.expected_plan_hash() == with_none.expected_plan_hash()
