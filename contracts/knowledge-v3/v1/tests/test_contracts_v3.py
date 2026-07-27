"""
test_contracts_v3.py — pruebas de los nueve contratos internos `v3-internal-v1`.

Dos familias, deliberadamente separadas:

  * ROUNDTRIP / DETERMINISMO: un documento sobrevive a JSON y vuelve identico, y
    su serializacion es estable byte a byte.
  * MUTACION: por cada regla estructural clave hay un caso que HOY se rechaza.
    Si la regla se relaja, el caso pasa a aceptarse y el test se pone rojo. Un
    test verde solo vale si puede ponerse rojo.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("referencing")

HERE = Path(__file__).resolve().parent
CONTRACT_DIR = HERE.parent
VALID = CONTRACT_DIR / "examples" / "valid"
INVALID = CONTRACT_DIR / "examples" / "invalid"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import v3_fixtures as fixtures  # noqa: E402
import generate_examples  # noqa: E402

# El validador llega a traves de las fixtures, que lo cargan con un nombre de
# modulo unico: importar `validator` a secas colisionaria con el del contrato
# review/ingest v1 en la corrida conjunta de pytest.
V = fixtures.V


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# ==========================================================================
# Estructura de la familia
# ==========================================================================
def test_all_schemas_parse_and_have_id():
    schemas = sorted(CONTRACT_DIR.glob("*.schema.json"))
    assert len(schemas) == 10, "9 contratos + _common"
    for s in schemas:
        doc = _load(s)
        assert doc["$id"].startswith("https://s9-knowledge/contracts/knowledge-v3/v1/")
        assert doc["$schema"].endswith("2020-12/schema")


def test_registry_builds():
    assert V.build_registry() is not None


def test_every_contract_has_schema_file():
    assert len(V.CONTRACT_SCHEMAS) == 9
    for cid, fname in V.CONTRACT_SCHEMAS.items():
        assert cid.endswith("/v3-internal-v1"), cid
        assert (CONTRACT_DIR / fname).is_file()


def test_root_schemas_reject_unknown_fields():
    """additionalProperties:false por defecto en la raiz de los nueve."""
    for fname in V.CONTRACT_SCHEMAS.values():
        doc = _load(CONTRACT_DIR / fname)
        assert doc.get("additionalProperties") is False, fname


def test_only_documented_blocks_are_open():
    """Los unicos `additionalProperties: true` son `metadata` y `payload`."""
    open_blocks = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("additionalProperties") is True:
                open_blocks.append(path)
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    for fname in list(V.CONTRACT_SCHEMAS.values()) + ["_common-v3.schema.json"]:
        walk(_load(CONTRACT_DIR / fname), fname)

    assert open_blocks, "el test no esta mirando nada"
    for path in open_blocks:
        assert path.rsplit("/", 1)[-1] in V.OPEN_BLOCKS, path


# ==========================================================================
# Ejemplos
# ==========================================================================
def test_examples_are_generated_not_handwritten():
    """Los ficheros en disco coinciden byte a byte con lo que generan las fixtures."""
    for path, content in generate_examples.expected_files().items():
        assert path.is_file(), f"falta el ejemplo {path.name} (regenera con generate_examples.py)"
        assert path.read_text(encoding="utf-8") == content, f"ejemplo desactualizado: {path.name}"


@pytest.mark.parametrize("path", sorted(VALID.glob("*.json")), ids=lambda p: p.stem)
def test_valid_examples_pass(path: Path):
    V.validate_document(_load(path))


@pytest.mark.parametrize("path", sorted(INVALID.glob("*.json")), ids=lambda p: p.stem)
def test_invalid_examples_rejected(path: Path):
    with pytest.raises(V.ContractV3Error):
        V.validate_document(_load(path))


def test_examples_cover_every_contract():
    seen = {_load(p)["contract_id"] for p in VALID.glob("*.json")}
    assert seen == set(V.CONTRACT_SCHEMAS)


def test_examples_present():
    assert len(list(VALID.glob("*.json"))) >= 17
    assert len(list(INVALID.glob("*.json"))) >= 40


# ==========================================================================
# Roundtrip y determinismo
# ==========================================================================
@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_json_roundtrip_is_exact(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    assert json.loads(V.canonical_json(doc)) == doc


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_canonical_json_is_byte_stable(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    first = V.canonical_json(doc)
    # Reordenar las claves de entrada no puede cambiar ni un byte de la salida.
    shuffled = {k: doc[k] for k in reversed(list(doc))}
    assert V.canonical_json(shuffled) == first
    # Y repetir la llamada tampoco (nada generado en tiempo de serializacion).
    assert V.canonical_json(doc) == first


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_hash_is_reproducible(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    assert V.sha256_hash(doc) == V.sha256_hash(deepcopy(doc))


def test_canonical_json_has_no_timestamp_side_effects():
    doc = fixtures.source_asset()
    before = V.canonical_json(doc)
    import time

    time.sleep(0.01)
    assert V.canonical_json(doc) == before


# ==========================================================================
# Mutacion: reglas del envelope comun, contrato por contrato
# ==========================================================================
@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_unknown_field_rejected_everywhere(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["campo_que_no_existe"] = "x"
    assert not V.is_valid(doc)


@pytest.mark.parametrize(
    "field", ["workspace", "contract_version", "source_hash", "provider_trace", "source_asset_id"]
)
@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_common_envelope_field_is_mandatory(name: str, field: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc.pop(field)
    assert not V.is_valid(doc), f"{name} acepto un documento sin {field}"


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_unknown_major_version_rejected_everywhere(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["contract_version"] = "2.0.0"
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_wrong_contract_id_rejected_everywhere(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["contract_id"] = "otro-contrato/v3-internal-v1"
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_hash_without_algorithm_rejected(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["source_hash"] = {"value": "a" * 64}
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_provider_trace_needs_known_provider(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["provider_trace"] = [dict(doc["provider_trace"][0], provider="anthropic")]
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_provider_trace_needs_produced(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["provider_trace"] = [dict(doc["provider_trace"][0], produced=[])]
    assert not V.is_valid(doc)


def test_provider_trace_duplicate_step_rejected():
    doc = fixtures.entity_mention()
    doc["provider_trace"] = [doc["provider_trace"][0], dict(doc["provider_trace"][0])]
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_secrets_in_metadata_rejected(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["metadata"] = {"api_key": "abc123"}
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_empty_workspace_rejected(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc["workspace"] = ""
    assert not V.is_valid(doc)


# ==========================================================================
# Mutacion: firma del GraphMutationPlan (lo que el writer exigira)
# ==========================================================================
def test_sealing_is_idempotent():
    plan = fixtures.graph_mutation_plan()
    assert V.seal_plan(plan) == plan


def test_seal_plan_does_not_mutate_input():
    plan = fixtures.graph_mutation_plan()
    before = V.canonical_json(plan)
    V.seal_plan(plan)
    assert V.canonical_json(plan) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace", "otro"),
        ("source_asset_id", "asset:otro"),
        ("engine_version", "9.9.9"),
        ("ontology_version", "core-9.9.9"),
        ("game_profile", "otro"),
        ("collection_id", "collection:otra"),
    ],
)
def test_any_signed_field_change_breaks_the_signature(field, value):
    plan = fixtures.graph_mutation_plan()
    plan[field] = value
    assert not V.is_valid(plan), f"cambiar {field} no invalido el plan"
    # Y ademas el hash esperado cambia: no es que se compare con nada estatico.
    assert V.compute_plan_hash(plan) != plan["plan_hash"]


def test_changing_a_decision_breaks_the_decision_hash():
    plan = fixtures.graph_mutation_plan()
    plan["decisions"][0]["predicate"] = "ALLY_OF"
    assert plan["local_approval"]["decision_hash"] != V.compute_decision_hash(plan)
    assert not V.is_valid(plan)


def test_adding_an_operation_breaks_the_plan_hash():
    plan = fixtures.graph_mutation_plan()
    extra = dict(
        deepcopy(plan["mutation_operations"][0]),
        operation_id="op:9999",
        idempotency_key="idem:9999",
    )
    plan["mutation_operations"].append(extra)
    assert not V.is_valid(plan)


def test_plan_signed_by_ollama_is_invalid():
    plan = V.seal_plan(
        {
            **fixtures.graph_mutation_plan(),
            "local_approval": {
                **fixtures.graph_mutation_plan()["local_approval"],
                "approved_by": {"provider": "ollama", "name": "qwen", "version": "2.5"},
            },
        }
    )
    assert not V.is_valid(plan)


def test_not_approved_plan_with_review_decision_is_valid():
    """Un plan NO aprobado si puede llevar decisiones REVIEW: es su estado natural."""
    V.validate_document(fixtures.graph_mutation_plan_not_approved())


def test_approved_plan_is_valid_and_signed():
    plan = fixtures.graph_mutation_plan()
    V.validate_document(plan)
    assert plan["local_approval"]["approved"] is True
    assert plan["local_approval"]["approved_by"]["provider"] == "local"
    assert plan["plan_hash"] == V.compute_plan_hash(plan)


# ==========================================================================
# Mutacion: reglas propias de cada contrato
# ==========================================================================
def test_asset_source_hash_must_be_its_own_content_hash():
    doc = fixtures.source_asset()
    doc["content_hash"] = fixtures.h("otra-cosa")
    assert not V.is_valid(doc)


def test_evidence_offsets_must_be_ordered():
    doc = fixtures.evidence_fragment()
    doc["start"], doc["end"] = doc["end"], doc["start"]
    assert not V.is_valid(doc)


def test_asr_evidence_needs_time_anchor():
    doc = fixtures.evidence_fragment()
    doc["media_type"] = "ASR_TEXT"
    assert not V.is_valid(doc)


def test_claim_predicates_must_be_sorted_by_confidence():
    doc = fixtures.claim_proposal()
    doc["predicate_candidates"] = list(reversed(doc["predicate_candidates"]))
    assert not V.is_valid(doc)


def test_abstained_claim_cannot_carry_confidence():
    doc = fixtures.claim_proposal_abstained()
    doc["confidence"] = 0.9
    assert not V.is_valid(doc)


def test_resolution_split_must_cover_all_mentions():
    doc = fixtures.entity_resolution()
    doc["action"] = "SPLIT"
    doc["selected_entity_id"] = None
    doc["split_groups"] = [["mention:p12:0"], ["mention:p12:99"]]
    assert not V.is_valid(doc)


def test_assertion_cannot_supersede_itself():
    doc = fixtures.fact_assertion()
    doc["supersedes"] = doc["assertion_id"]
    assert not V.is_valid(doc)


def test_profile_cannot_invent_entity_types():
    doc = fixtures.game_profile()
    doc["entity_types"] = ["Character", "Vehiculo"]
    assert not V.is_valid(doc)


# ==========================================================================
# Ronda de correcciones: hallazgos del revisor independiente
# ==========================================================================
def test_epistemic_status_has_the_seven_minimum_states():
    """H1 — dosier 11.6 fija siete estados minimos; faltaban dos."""
    common = _load(CONTRACT_DIR / "_common-v3.schema.json")
    assert set(common["$defs"]["epistemic_status"]["enum"]) == {
        "ASSERTED", "RUMORED", "HYPOTHETICAL", "INTENDED",
        "VISUAL_INFERRED", "CONFLICTED", "UNKNOWN",
    }


def test_engine_can_emit_a_conflicted_assertion():
    """H1 — sin CONFLICTED el motor no tenia como expresar un conflicto."""
    V.validate_document(fixtures.fact_assertion_conflicted())


def test_media_type_distinguishes_htr_from_ocr():
    """H11 — el manuscrito no es OCR y ya no tiene que disfrazarse de OCR."""
    common = _load(CONTRACT_DIR / "_common-v3.schema.json")
    enum = common["$defs"]["media_type"]["enum"]
    assert "HTR_TEXT" in enum and "OCR_TEXT" in enum
    V.validate_document(fixtures.evidence_fragment_htr())


def test_assertion_has_two_independent_temporal_axes():
    """H2 — `state` (temporal) y `status` (ciclo de vida) son ejes distintos."""
    doc = fixtures.fact_assertion()
    assert doc["state"] == "ACTIVE" and doc["status"] == "ASSERTED"
    # Una afirmacion terminada puede seguir estando CONFIRMED en el ledger.
    doc["state"] = "ENDED"
    doc["valid_to"] = "1050-01-01T00:00:00Z"
    doc["status"] = "CONFIRMED"
    V.validate_document(doc)


@pytest.mark.parametrize("field", ["state", "event_time", "negated"])
def test_assertion_new_fields_are_mandatory(field):
    """H2 y H5 — anadirlos despues de congelar es justo lo que no se puede."""
    doc = fixtures.fact_assertion()
    doc.pop(field)
    assert not V.is_valid(doc)


def test_assertion_state_cannot_contradict_validity():
    """H2 — los dos ejes tienen que ser coherentes entre si."""
    doc = fixtures.fact_assertion()
    doc["valid_to"] = "1050-01-01T00:00:00Z"   # ACTIVE con vigencia cerrada
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_produced_by_step_must_point_at_a_real_step(name: str):
    """H3 — la atribucion de proveedor es una referencia, no una adivinanza."""
    doc = fixtures.VALID_BUILDERS[name]()
    doc["produced_by_step"] = "paso:inexistente"
    assert not V.is_valid(doc)


@pytest.mark.parametrize("name", sorted(fixtures.VALID_BUILDERS), ids=str)
def test_produced_by_step_is_mandatory(name: str):
    doc = fixtures.VALID_BUILDERS[name]()
    doc.pop("produced_by_step")
    assert not V.is_valid(doc)


def test_producing_step_resolves_the_declared_step():
    doc = fixtures.claim_proposal_visual()
    entry = V.producing_step(doc)
    assert entry["step"] == doc["produced_by_step"]
    assert entry["provider"] == "external"
    # Y la traza NO dice "claim" en `produced`: es justo el caso que la vieja
    # heuristica de subcadenas etiquetaba mal.
    assert not any(p.startswith("claim") for p in entry["produced"])


def test_direction_candidates_need_a_total_order():
    """H4 — con confianzas empatadas el orden de llegada decidia la direccion."""
    doc = fixtures.claim_proposal()
    doc["direction_candidates"] = [
        {"direction": "UNDIRECTED", "confidence": 0.5},
        {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.5},
    ]
    assert not V.is_valid(doc)
    # El orden canonico (desempate por el enum) si es valido.
    doc["direction_candidates"] = [
        {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.5},
        {"direction": "UNDIRECTED", "confidence": 0.5},
    ]
    V.validate_document(doc)


def test_alternatives_need_a_total_order():
    doc = fixtures.claim_proposal()
    doc["alternatives"] = [
        {"predicate": "RIVAL_OF", "direction": "UNDIRECTED", "confidence": 0.3},
        {"predicate": "ALLY_OF", "direction": "UNDIRECTED", "confidence": 0.3},
    ]
    assert not V.is_valid(doc)


def test_predicate_tie_is_broken_alphabetically():
    doc = fixtures.claim_proposal()
    doc["predicate_candidates"] = [
        {"predicate": "MEMBER_OF", "confidence": 0.5},
        {"predicate": "ALLY_OF", "confidence": 0.5},
    ]
    doc["confidence"] = 0.5
    assert not V.is_valid(doc)
    doc["predicate_candidates"].reverse()
    V.validate_document(doc)


def test_sort_keys_are_a_total_order():
    """Ningun par de candidatos distintos puede quedar 'empatado' en la clave."""
    items = [
        {"predicate": "ALLY_OF", "direction": "UNDIRECTED", "confidence": 0.5},
        {"predicate": "ALLY_OF", "direction": "SUBJECT_TO_OBJECT", "confidence": 0.5},
        {"predicate": "MEMBER_OF", "direction": "UNDIRECTED", "confidence": 0.5},
    ]
    keys = [V.alternative_sort_key(i) for i in items]
    assert len(set(keys)) == len(keys)


def test_resolution_entity_type_is_mandatory():
    """H5 — puede ser null, pero el campo tiene que estar."""
    doc = fixtures.entity_resolution()
    doc.pop("entity_type")
    assert not V.is_valid(doc)


def test_creating_an_entity_requires_naming_it():
    """H6 — el resolutor asigna el id; nadie lo deduce de una cadena."""
    doc = fixtures.entity_resolution_provisional()
    assert doc["assigned_entity_id"]
    doc["assigned_entity_id"] = None
    assert not V.is_valid(doc)


def test_linking_cannot_assign_a_new_id():
    doc = fixtures.entity_resolution()
    doc["assigned_entity_id"] = "entity:nueva"
    assert not V.is_valid(doc)


def test_plan_requires_a_snapshot_anchor():
    """H7 — sin snapshot, `expected_state` habla de un grafo desconocido."""
    doc = fixtures.graph_mutation_plan()
    doc.pop("snapshot_id")
    assert not V.is_valid(doc)


def test_idempotency_key_is_derived_and_checked():
    """H7 — una clave inventada no garantiza idempotencia."""
    plan = fixtures.graph_mutation_plan()
    op = plan["mutation_operations"][0]
    assert op["idempotency_key"] == V.compute_idempotency_key(plan, op)
    tampered = V.seal_plan(
        {**plan, "mutation_operations": [{**op, "idempotency_key": "idem:sha256:" + "c" * 64}]},
        derive_keys=False,
    )
    assert not V.is_valid(tampered)


def test_same_logical_operation_in_two_plans_gets_the_same_key():
    """H7 — es la propiedad que hace que reaplicar sea un no-op."""
    plan_a = fixtures.graph_mutation_plan()
    plan_b = fixtures.graph_mutation_plan()
    plan_b["plan_id"] = "plan:manual-001:0099"
    plan_b["created_at"] = "2026-07-27T11:00:00Z"
    plan_b["expires_at"] = "2026-07-28T11:00:00Z"
    plan_b["mutation_operations"][0]["operation_id"] = "op:9999"
    plan_b = V.seal_plan(plan_b)
    assert (
        plan_b["mutation_operations"][0]["idempotency_key"]
        == plan_a["mutation_operations"][0]["idempotency_key"]
    )


def test_key_changes_with_workspace_and_snapshot():
    plan = fixtures.graph_mutation_plan()
    op = plan["mutation_operations"][0]
    base = V.compute_idempotency_key(plan, op)
    assert V.compute_idempotency_key({**plan, "workspace": "otro"}, op) != base
    assert V.compute_idempotency_key({**plan, "snapshot_id": "snapshot:otro"}, op) != base


def test_update_operations_need_optimistic_concurrency():
    """H7 — modificar algo existente sin version esperada es pisar a ciegas."""
    plan = V.seal_plan(
        {
            **fixtures.graph_mutation_plan(),
            "mutation_operations": [
                {**fixtures.graph_mutation_plan()["mutation_operations"][0],
                 "operation_type": "UPDATE_ENTITY"}
            ],
        }
    )
    assert not V.is_valid(plan)


def test_signature_and_key_id_are_reserved_and_optional():
    """H8 — el hueco de la firma real existe ya, sin romper el contrato."""
    schema = _load(CONTRACT_DIR / "graph-mutation-plan-v3.schema.json")
    approval = schema["$defs"]["local_approval"]
    assert "signature" in approval["properties"]
    assert "key_id" in approval["properties"]
    assert "signature" not in approval["required"]
    plan = fixtures.graph_mutation_plan()
    plan["local_approval"]["signature"] = "ed25519:" + "0" * 64
    plan["local_approval"]["key_id"] = "key:engine-local-1"
    V.validate_document(V.seal_plan(plan))


def test_schema_no_longer_claims_unforgeable_signature():
    """H8 — la descripcion decia una garantia que el hash sin clave no da."""
    schema = _load(CONTRACT_DIR / "graph-mutation-plan-v3.schema.json")
    text = schema["description"] + schema["$defs"]["local_approval"]["description"]
    assert "VERIFICABLE, NO CONFIABLE" in schema["description"]
    assert "invalido por contrato" not in text


@pytest.mark.parametrize("field", ["approved", "approved_by", "validator_chain"])
def test_decision_hash_covers_what_the_writer_consumes(field):
    """H9 — cambiar `approved` no rompia el hash de decision."""
    plan = fixtures.graph_mutation_plan()
    before = V.compute_decision_hash(plan)
    if field == "approved":
        plan["local_approval"]["approved"] = False
    elif field == "approved_by":
        plan["local_approval"]["approved_by"]["name"] = "otro.motor"
    else:
        plan["local_approval"]["validator_chain"][0]["result"] = "SKIPPED"
    assert V.compute_decision_hash(plan) != before


def test_decision_hash_covers_expires_at():
    plan = fixtures.graph_mutation_plan()
    before = V.compute_decision_hash(plan)
    plan["expires_at"] = "2026-12-31T00:00:00Z"
    assert V.compute_decision_hash(plan) != before


def test_removing_the_decision_hash_check_would_be_caught():
    """H10 — mata el mutante: resellar SOLO plan_hash debe seguir fallando.

    Si alguien suprime la comparacion de `decision_hash` en el validador, este
    documento pasaria: su `plan_hash` es correcto y lo unico que delata la
    manipulacion es el `decision_hash` obsoleto.
    """
    plan = fixtures.graph_mutation_plan()
    plan["local_approval"]["approved"] = True
    plan["decisions"][0]["predicate"] = "ALLY_OF"
    plan["mutation_operations"][0]["payload"]["predicate"] = "ALLY_OF"
    plan["mutation_operations"][0]["idempotency_key"] = V.compute_idempotency_key(
        plan, plan["mutation_operations"][0]
    )
    # Solo se recalcula el hash del plan; el de decision se deja obsoleto.
    plan["plan_hash"] = V.compute_plan_hash(plan)
    assert plan["local_approval"]["decision_hash"] != V.compute_decision_hash(plan)
    with pytest.raises(V.ContractV3Error, match="decision_hash"):
        V.validate_document(plan)


def test_supported_major_is_enforced_by_the_validator_itself():
    """H17 — antes lo rechazaba el patron del schema, no SUPPORTED_MAJOR."""
    assert V.SUPPORTED_MAJOR == 1
    V._check_major_version({"contract_version": "1.4.2"})
    for bad in ("2.0.0", "0.9.9", "10.0.0"):
        with pytest.raises(V.ContractV3Error, match="version mayor no soportada"):
            V._check_major_version({"contract_version": bad})
    with pytest.raises(V.ContractV3Error, match="contract_version invalida"):
        V._check_major_version({"contract_version": "uno"})


def test_episode_table_keeps_its_structure():
    """H16 — aplanar una tabla a texto pierde lo unico que la hace tabla."""
    doc = fixtures.source_episode_table()
    V.validate_document(doc)
    assert doc["table"]["rows"][0][0] == "Casa del Ciervo"


def test_episode_speaker_and_turn_are_typed():
    """H12 — sin hablante no hay correferencia de yo/tu."""
    doc = fixtures.source_episode_audio()
    V.validate_document(doc)
    assert doc["speaker"]["speaker_id"] == "speaker:02"
    doc["speaker"] = {"speaker_id": "speaker:02", "campo_raro": 1}
    assert not V.is_valid(doc)


def test_calendar_id_gives_game_profile_calendars_a_consumer():
    """H13 — `calendars` no tenia quien lo usara."""
    assertion = fixtures.fact_assertion()
    profile = fixtures.game_profile()
    assert assertion["calendar_id"] in [c["calendar_id"] for c in profile["calendars"]]
    claim = fixtures.claim_proposal()
    claim["temporal_expressions"] = [
        {"text": "en la tercera luna", "kind": "POINT", "valid_from": None,
         "valid_to": None, "calendar_id": "calendar:umbra", "fragment_id": "fragment:p12:0"}
    ]
    V.validate_document(claim)


def test_dossier_decisions_all_map_to_the_contract():
    """H15 — las diez decisiones del dosier 11.7 tienen representacion exacta."""
    dossier = {
        "LOCAL_APPROVED", "LOCAL_APPROVED_WITH_WARNINGS", "REVIEW_ENTITY",
        "REVIEW_PREDICATE", "REVIEW_DIRECTION", "REVIEW_TEMPORALITY",
        "REVIEW_EVIDENCE", "CONFLICT", "ABSTAIN", "REJECT_INVALID",
    }
    assert set(V.ENGINE_DECISION_MAP) == dossier
    schema = _load(CONTRACT_DIR / "graph-mutation-plan-v3.schema.json")
    valid_decisions = set(schema["$defs"]["decision"]["properties"]["decision"]["enum"])
    for dossier_decision, (decision, reason) in V.ENGINE_DECISION_MAP.items():
        assert decision in valid_decisions, dossier_decision
        assert reason in V.CANONICAL_REASON_CODES[decision], dossier_decision


def test_every_plan_decision_needs_a_canonical_reason():
    """H15 — sin razon canonica la decision del dosier no es reconstruible."""
    plan = fixtures.graph_mutation_plan()
    plan["decisions"][0]["reason_codes"] = ["PORQUE_SI"]
    assert not V.is_valid(V.seal_plan(plan))


def test_table_modality_requires_the_structured_table():
    """Una tabla sin filas y columnas es texto que perdio lo que la hacia tabla."""
    doc = fixtures.source_episode_table()
    V.validate_document(doc)
    doc["table"] = None
    assert not V.is_valid(doc)
    doc.pop("table")
    assert not V.is_valid(doc)


def test_speaker_turn_modality_requires_a_speaker():
    """Un turno de habla sin hablante no resuelve ninguna correferencia."""
    doc = fixtures.source_episode_audio()
    doc["modality"] = "SPEAKER_TURN"
    V.validate_document(doc)          # la fixture ya trae speaker
    doc["speaker"] = None
    assert not V.is_valid(doc)
    doc.pop("speaker")
    assert not V.is_valid(doc)


def test_modality_conditionals_do_not_leak_to_other_modalities():
    """La regla es condicional: un episodio de texto no necesita tabla ni hablante."""
    doc = fixtures.source_episode()
    assert doc["table"] is None and doc["speaker"] is None
    V.validate_document(doc)


def test_plan_declares_what_the_writer_must_not_consume():
    """Los campos fuera del decision_hash no pueden fundamentar una escritura."""
    schema = _load(CONTRACT_DIR / "graph-mutation-plan-v3.schema.json")
    description = schema["description"]
    assert "LIMITE EXPLICITO" in description
    for field in ("created_at", "plan_id", "provider_trace", "metadata"):
        assert field in description
        # Y efectivamente ninguno entra en el hash de decision.
        assert field not in V.DECISION_HASH_FIELDS


def test_fields_outside_the_decision_hash_really_are_outside():
    """Si alguno entrase en el hash, la advertencia del schema sobraria."""
    plan = fixtures.graph_mutation_plan()
    before = V.compute_decision_hash(plan)
    plan["created_at"] = "2020-01-01T00:00:00Z"
    plan["plan_id"] = "plan:otro"
    plan["provider_trace"] = [fixtures.trace_local("otro.paso", ["nada"])]
    plan["produced_by_step"] = "otro.paso"
    plan["metadata"] = {"nota": "cambiada"}
    assert V.compute_decision_hash(plan) == before
