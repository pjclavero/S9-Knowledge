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
