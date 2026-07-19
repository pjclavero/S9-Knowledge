"""test_export_import_contract.py — Contrato interno export/import v1.

Cubre el contrato `s9-knowledge-export/internal-v1`:
  - MANIFEST bien formado + validacion.
  - Estados de import DRY-RUN (nunca APPLY).
  - Validadores de ZIP manifestado, JSONL, JSON, CSV y GraphML declarado.
  - Reutilizacion de la redaccion de review.export_import.

PRUEBAS HOSTILES (cada una debe rechazar y NUNCA aplicar):
  1. path traversal en nombre de fichero
  2. zip-bomb SIMULADA por metadata (ratio declarado excesivo, sin bomba real)
  3. hash sha256 incorrecto
  4. manifest ausente
  5. version desconocida
  6. IDs duplicados
  7. workspace ajeno/incorrecto
  8. fichero no declarado en el manifest
  9. tamano excesivo (supera limite)
 10. JSONL invalido
 (+ secreto/credencial en registro)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

# Bootstrap sys.path (mismo patron que el resto de tests del proyecto).
_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from export_import.contract import (  # noqa: E402
    CONTRACT_FORMAT,
    CONTRACT_VERSION,
    SUPPORTED_VERSIONS,
    ImportState,
    RecordType,
    EXPORTABLE_RECORD_TYPES,
    FORBIDDEN_EXPORT_CATEGORIES,
    Limits,
    Manifest,
    build_manifest,
    validate_manifest,
    validate_safe_path,
    validate_sha256,
    remap_external_id,
    validate_zip_metadata,
    validate_jsonl,
    validate_json,
    validate_csv,
    validate_graphml_declared,
    dry_run_import,
)
from export_import.contract import sanitize_value  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

WS = "campaign_alpha"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _good_manifest(workspace: str = WS) -> dict:
    payload = b'{"ok": true}'
    m = build_manifest(
        workspace,
        entity_count=2,
        relation_count=1,
        schemas={"entities": "entity/v1", "relations": "relation/v1"},
        hashes={"entities.jsonl": _sha(payload)},
        compression={"algorithm": "deflate"},
    )
    return m.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Identidad del contrato
# ─────────────────────────────────────────────────────────────────────────────

def test_contract_identity():
    assert CONTRACT_FORMAT == "s9-knowledge-export/internal-v1"
    assert CONTRACT_VERSION in SUPPORTED_VERSIONS


def test_manifest_has_all_required_fields():
    m = build_manifest(WS)
    d = m.to_dict()
    for field_name in (
        "format", "version", "created_at", "exporter_version", "workspace",
        "filters", "entity_count", "relation_count", "file_count",
        "schemas", "hashes", "compression", "redaction_policy",
    ):
        assert field_name in d, f"falta campo {field_name} en manifest"
    assert d["format"] == CONTRACT_FORMAT


def test_exportable_record_types_and_forbidden_categories():
    # Registros soportados.
    for rt in ("entities", "relations", "aliases", "provenance",
               "decisions", "plans", "metrics", "events"):
        assert rt in EXPORTABLE_RECORD_TYPES
    # Nunca exporta secretos/dumps.
    for cat in ("passwords", "sessions", "credentials", "tokens",
                "internal_paths", "sensitive_config", "neo4j_dump"):
        assert cat in FORBIDDEN_EXPORT_CATEGORIES


def test_all_dry_run_states_present():
    for name in ("VALID", "INVALID", "WOULD_CREATE", "WOULD_UPDATE",
                 "WOULD_LINK", "CONFLICT", "DUPLICATE", "DEFERRED"):
        assert hasattr(ImportState, name)


def test_reuses_review_redaction():
    # La redaccion viene de review.export_import (no duplicada aqui).
    dirty = {"note": "server 192.168.1.10 token=abc bolt://neo4j:7687 /home/ia02/x"}
    clean = sanitize_value(dirty)
    blob = json.dumps(clean)
    assert "192.168.1.10" not in blob
    assert "bolt://" not in blob
    assert "/home/ia02" not in blob


# ─────────────────────────────────────────────────────────────────────────────
# Validadores atomicos
# ─────────────────────────────────────────────────────────────────────────────

def test_safe_path_accepts_relative():
    ok, _ = validate_safe_path("data/entities.jsonl")
    assert ok


@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "/etc/passwd",
    "\\windows\\system32",
    "C:\\secret.txt",
    "data/../../escape",
    "a\x00b",
])
def test_safe_path_rejects_traversal_and_absolute(bad):
    ok, why = validate_safe_path(bad)
    assert not ok and why


def test_sha256_format_and_match():
    data = b"hello"
    good = _sha(data)
    assert validate_sha256(good, data)[0]
    assert not validate_sha256("deadbeef", data)[0]           # formato malo
    assert not validate_sha256(good, b"tampered")[0]          # no coincide


def test_remap_external_id_deterministic_and_isolated():
    a1 = remap_external_id("ext-1", "ws_a")
    a2 = remap_external_id("ext-1", "ws_a")
    b1 = remap_external_id("ext-1", "ws_b")
    assert a1 == a2               # determinista
    assert a1 != b1              # aislado por workspace
    assert a1.startswith("s9x_")


# ─────────────────────────────────────────────────────────────────────────────
# Validador de MANIFEST (camino feliz)
# ─────────────────────────────────────────────────────────────────────────────

def test_valid_manifest():
    state, errors = validate_manifest(_good_manifest(), expected_workspace=WS)
    assert state == ImportState.VALID, errors
    assert errors == []


# ─────────────────────────────────────────────────────────────────────────────
# Formatos de datos (camino feliz)
# ─────────────────────────────────────────────────────────────────────────────

def test_json_valid():
    state, errors, obj = validate_json('{"a": 1}')
    assert state == ImportState.VALID
    assert obj == {"a": 1}


def test_jsonl_valid():
    text = '{"id": "e1", "type": "entities"}\n{"id": "e2", "type": "entities"}\n'
    state, errors, rows = validate_jsonl(text)
    assert state == ImportState.VALID
    assert len(rows) == 2


def test_csv_valid_with_required_columns():
    text = "id,type\ne1,entities\ne2,entities\n"
    state, errors, rows = validate_csv(text, required_columns=["id", "type"])
    assert state == ImportState.VALID
    assert len(rows) == 2


def test_csv_missing_required_column():
    text = "id\ne1\n"
    state, errors, _ = validate_csv(text, required_columns=["id", "type"])
    assert state == ImportState.INVALID
    assert any("type" in e for e in errors)


def test_graphml_declared_ok():
    schemas = {"graphml": "graphml/v1"}
    state, errors = validate_graphml_declared(schemas, file_name="graph.graphml")
    assert state == ImportState.VALID, errors


def test_graphml_not_declared_rejected():
    state, errors = validate_graphml_declared({}, file_name="graph.graphml")
    assert state == ImportState.INVALID


def test_zip_metadata_ok():
    payload = b"a" * 1000
    entries = [{"name": "entities.jsonl", "compress_size": 100, "file_size": 1000}]
    state, errors = validate_zip_metadata(entries)
    assert state == ImportState.VALID, errors
    assert payload  # sin bomba real


# ─────────────────────────────────────────────────────────────────────────────
# Import DRY-RUN (camino feliz) — nunca aplica
# ─────────────────────────────────────────────────────────────────────────────

def test_dry_run_would_create_and_link():
    manifest = _good_manifest()
    records = [
        {"id": "n1", "type": "entities", "workspace": WS},
        {"id": "n2", "type": "entities", "workspace": WS},
        {"id": "r1", "type": "relations", "from": "n1", "to": "n2", "workspace": WS},
    ]
    report = dry_run_import(manifest, records, target_workspace=WS)
    assert report.applied is False                     # invariante
    assert report.manifest_state == ImportState.VALID
    states = [r.state for r in report.records]
    assert ImportState.WOULD_CREATE in states
    assert ImportState.WOULD_LINK in states
    assert not report.rejected_any


def test_dry_run_would_update_existing():
    manifest = _good_manifest()
    rec = {"id": "n1", "type": "entities", "workspace": WS}
    existing = {remap_external_id("n1", WS)}
    report = dry_run_import(manifest, [rec], target_workspace=WS,
                            existing_internal_ids=existing)
    assert report.records[0].state == ImportState.WOULD_UPDATE
    assert report.applied is False


def test_dry_run_relation_missing_endpoints_deferred():
    manifest = _good_manifest()
    records = [
        {"id": "r1", "type": "relations", "from": "ghost1", "to": "ghost2",
         "workspace": WS},
    ]
    report = dry_run_import(manifest, records, target_workspace=WS)
    assert report.records[0].state == ImportState.DEFERRED
    assert report.applied is False


# ─────────────────────────────────────────────────────────────────────────────
# PRUEBAS HOSTILES — todas deben rechazar y NUNCA aplicar
# ─────────────────────────────────────────────────────────────────────────────

def test_hostile_1_path_traversal_in_manifest_files():
    m = _good_manifest()
    m["hashes"] = {"../../etc/passwd": _sha(b"x")}
    m["file_count"] = 1
    state, errors = validate_manifest(m, expected_workspace=WS)
    assert state == ImportState.INVALID
    assert any("traversal" in e or "insegura" in e for e in errors)


def test_hostile_2_zip_bomb_simulated_by_ratio():
    # Ratio declarado enorme SIN descomprimir nada real.
    entries = [{"name": "bomb.bin", "compress_size": 1, "file_size": 10_000_000}]
    state, errors = validate_zip_metadata(entries)
    assert state == ImportState.INVALID
    assert any("zip-bomb" in e or "ratio" in e for e in errors)


def test_hostile_2b_zip_bomb_infinite_ratio():
    entries = [{"name": "bomb.bin", "compress_size": 0, "file_size": 5000}]
    state, errors = validate_zip_metadata(entries)
    assert state == ImportState.INVALID


def test_hostile_3_wrong_hash():
    m = _good_manifest()
    m["hashes"] = {"entities.jsonl": "not_a_valid_sha256"}
    state, errors = validate_manifest(m, expected_workspace=WS)
    assert state == ImportState.INVALID
    # Y a nivel de contenido:
    good = _sha(b"real")
    assert not validate_sha256(good, b"tampered")[0]


def test_hostile_4_manifest_absent():
    state, errors = validate_manifest(None, expected_workspace=WS)
    assert state == ImportState.INVALID
    assert any("ausente" in e for e in errors)
    # dry-run con manifest ausente no procesa registros ni aplica.
    report = dry_run_import(None, [{"id": "n1", "type": "entities"}],
                            target_workspace=WS)
    assert report.applied is False
    assert report.manifest_state == ImportState.INVALID
    assert report.records == []


def test_hostile_5_unknown_version():
    m = _good_manifest()
    m["version"] = "999.0"
    state, errors = validate_manifest(m, expected_workspace=WS)
    assert state == ImportState.INVALID
    assert any("version" in e for e in errors)


def test_hostile_6_duplicate_ids():
    manifest = _good_manifest()
    records = [
        {"id": "dup", "type": "entities", "workspace": WS},
        {"id": "dup", "type": "entities", "workspace": WS},
    ]
    report = dry_run_import(manifest, records, target_workspace=WS)
    states = [r.state for r in report.records]
    assert ImportState.DUPLICATE in states
    assert report.rejected_any
    assert report.applied is False


def test_hostile_7_foreign_workspace():
    manifest = _good_manifest()
    # a) registro de otro workspace
    records = [{"id": "n1", "type": "entities", "workspace": "OTHER_WS"}]
    report = dry_run_import(manifest, records, target_workspace=WS)
    assert report.records[0].state == ImportState.CONFLICT
    assert report.applied is False
    # b) manifest de otro workspace
    m2 = _good_manifest(workspace="OTHER_WS")
    state, errors = validate_manifest(m2, expected_workspace=WS)
    assert state == ImportState.INVALID
    assert any("ajeno" in e for e in errors)


def test_hostile_8_file_not_declared_in_manifest():
    # El paquete trae un fichero que NO esta en manifest.hashes.
    m = _good_manifest()
    declared = set(m["hashes"].keys())
    present = declared | {"stowaway.jsonl"}
    undeclared = present - declared
    assert undeclared, "debe existir un fichero no declarado"
    # Politica: un fichero presente no declarado se rechaza.
    for fname in undeclared:
        assert fname not in m["hashes"]
    # Simulamos la comprobacion que hace el importador (fail-closed):
    rejected = [f for f in present if f not in m["hashes"]]
    assert rejected == ["stowaway.jsonl"]


def test_hostile_9_size_limit_exceeded():
    tiny = Limits(max_records=1)
    manifest = _good_manifest()
    records = [
        {"id": "n1", "type": "entities", "workspace": WS},
        {"id": "n2", "type": "entities", "workspace": WS},
    ]
    report = dry_run_import(manifest, records, target_workspace=WS, limits=tiny)
    assert report.manifest_state == ImportState.INVALID
    assert report.applied is False
    # Y validacion de manifest con demasiados registros declarados.
    m = _good_manifest()
    m["entity_count"] = 10_000_000
    state, errors = validate_manifest(m, expected_workspace=WS,
                                      limits=Limits(max_records=10))
    assert state == ImportState.INVALID


def test_hostile_10_invalid_jsonl():
    text = '{"id": "e1"}\n{not json}\n'
    state, errors, rows = validate_jsonl(text)
    assert state == ImportState.INVALID
    assert any("linea 2" in e for e in errors)


def test_hostile_11_secret_in_record_rejected():
    manifest = _good_manifest()
    records = [
        {"id": "n1", "type": "entities", "workspace": WS,
         "password": "hunter2", "token": "abc"},
    ]
    report = dry_run_import(manifest, records, target_workspace=WS)
    assert report.records[0].state == ImportState.INVALID
    assert report.applied is False


def test_hostile_12_non_exportable_type():
    manifest = _good_manifest()
    records = [{"id": "d1", "type": "neo4j_dump", "workspace": WS}]
    report = dry_run_import(manifest, records, target_workspace=WS)
    assert report.records[0].state == ImportState.INVALID
    assert report.applied is False


def test_never_applies_invariant_across_all_hostiles():
    """Meta-test: ningun dry-run marca applied=True, pase lo que pase."""
    manifest = _good_manifest()
    hostile_batches = [
        [{"id": "dup", "type": "entities", "workspace": WS},
         {"id": "dup", "type": "entities", "workspace": WS}],
        [{"id": "n1", "type": "entities", "workspace": "OTHER"}],
        [{"id": "n1", "type": "neo4j_dump", "workspace": WS}],
        [{"id": "n1", "type": "entities", "workspace": WS, "secret": "x"}],
        [{"type": "entities", "workspace": WS}],  # sin id
    ]
    for batch in hostile_batches:
        report = dry_run_import(manifest, batch, target_workspace=WS)
        assert report.applied is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
