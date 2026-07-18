"""
test_contracts_v1.py — pruebas de los contratos review/ingest v1.

Valida schemas, ejemplos válidos/inválidos, unicidad de IDs, coherencia de
conteos, versiones desconocidas, additionalProperties, hashes, UTC, enums y
control optimista. Fuente única: los .schema.json + validator.py del contrato.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("referencing")

HERE = Path(__file__).resolve().parent
CONTRACT_DIR = HERE.parent
VALID = CONTRACT_DIR / "examples" / "valid"
INVALID = CONTRACT_DIR / "examples" / "invalid"

import sys
sys.path.insert(0, str(CONTRACT_DIR))
import validator as V  # noqa: E402


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_all_schemas_parse_and_have_id():
    schemas = list(CONTRACT_DIR.glob("*.schema.json"))
    assert len(schemas) == 7  # 6 documentos + _common
    for s in schemas:
        doc = _load(s)
        assert doc["$id"].startswith("https://s9-knowledge/")
        assert doc["$schema"].endswith("2020-12/schema")


def test_registry_builds():
    reg = V.build_registry()
    assert reg is not None


@pytest.mark.parametrize("path", sorted(VALID.glob("*.json")), ids=lambda p: p.stem)
def test_valid_examples_pass(path: Path):
    V.validate_document(_load(path))


@pytest.mark.parametrize("path", sorted(INVALID.glob("*.json")), ids=lambda p: p.stem)
def test_invalid_examples_rejected(path: Path):
    with pytest.raises(V.ContractError):
        V.validate_document(_load(path))


def test_examples_present():
    assert len(list(VALID.glob("*.json"))) >= 10
    assert len(list(INVALID.glob("*.json"))) >= 12


def test_unknown_document_type_rejected():
    with pytest.raises(V.ContractError):
        V.validate_document({"document_type": "nope", "schema_version": "1.0.0"})


def test_unknown_major_version_rejected():
    doc = _load(next(VALID.glob("candidate_new.json")))
    doc["schema_version"] = "2.0.0"
    with pytest.raises(V.ContractError):
        V.validate_document(doc)


def test_shadow_ai_cannot_auto_approve():
    doc = _load(VALID / "decision_defer_shadow.json")
    doc["action"] = "APPROVE"
    assert not V.is_valid(doc)


def test_authorization_granted_requires_operator():
    doc = _load(VALID / "ingest_plan_ready.json")
    doc["authorization"] = {"required": True, "granted": True}
    assert not V.is_valid(doc)


def test_summary_counts_must_sum():
    doc = _load(VALID / "source_summary_conflicts.json")
    doc["candidates_total"] = doc["candidates_total"] + 1
    assert not V.is_valid(doc)


def test_dry_run_cannot_create():
    doc = _load(VALID / "dry_run_success.json")
    doc["summary"]["created"] = 1
    assert not V.is_valid(doc)


def test_secrets_in_metadata_rejected():
    doc = _load(VALID / "audit_event.json")
    doc["metadata"] = {"token": "abc123"}
    assert not V.is_valid(doc)


def test_hash_requires_algorithm():
    doc = _load(next(VALID.glob("candidate_new.json")))
    doc["source_hash"] = {"value": "a" * 64}
    assert not V.is_valid(doc)


def test_utc_datetime_enforced():
    doc = _load(next(VALID.glob("candidate_new.json")))
    doc["created_at"] = "2026-07-18 14:00:00"  # sin T ni Z
    assert not V.is_valid(doc)
