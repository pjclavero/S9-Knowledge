"""Q — invariantes de seguridad del contrato REAL de EXPORT/IMPORT.

Importa `export_import.contract` (implementación fusionada de B2) y ejercita sus
validadores reales. MUTATION checks: hash ignorado y path traversal son reglas
load-bearing; el import es SIEMPRE dry-run (`applied` invariante False).
"""
from __future__ import annotations

import hashlib

import pytest

from export_import.contract import (
    CONTRACT_FORMAT,
    CONTRACT_VERSION,
    DryRunReport,
    ImportState,
    dry_run_import,
    validate_manifest,
    validate_safe_path,
    validate_sha256,
    validate_zip_metadata,
)


# ── rutas seguras (path traversal) ─────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "../../etc/passwd", "..\\..\\win", "/abs/path", "C:\\x", "a/../../b", "x\x00y",
])
def test_unsafe_paths_rejected(bad):
    ok, _ = validate_safe_path(bad)
    assert ok is False


def test_safe_path_accepted():
    ok, _ = validate_safe_path("data/entities.jsonl")
    assert ok is True


@pytest.mark.mutation
def test_mutation_path_traversal_rejected_by_real_validator():
    """Si se relajara la regla, `../` pasaría; el validador real DEBE rechazarlo."""
    assert validate_safe_path("../secret")[0] is False
    assert validate_safe_path("ok/inner.json")[0] is True  # control


# ── hashes sha256 ──────────────────────────────────────────────────────────
def test_bad_hash_format_rejected():
    assert validate_sha256("not-a-hash")[0] is False


@pytest.mark.mutation
def test_mutation_wrong_hash_rejected_by_real_validator():
    data = b"contenido de laboratorio"
    good = hashlib.sha256(data).hexdigest()
    assert validate_sha256(good, data)[0] is True          # control
    assert validate_sha256("0" * 64, data)[0] is False     # hash que no coincide


# ── manifest: ausente / versión desconocida / workspace ajeno ──────────────
def test_missing_manifest_is_invalid():
    state, errors = validate_manifest(None)
    assert state == ImportState.INVALID and errors


def test_unknown_version_is_invalid():
    m = {"format": CONTRACT_FORMAT, "version": "999.0", "workspace": "leyenda"}
    state, _ = validate_manifest(m)
    assert state == ImportState.INVALID


def test_foreign_workspace_is_invalid():
    m = {"format": CONTRACT_FORMAT, "version": CONTRACT_VERSION, "workspace": "otra_boveda"}
    state, _ = validate_manifest(m, expected_workspace="leyenda")
    assert state == ImportState.INVALID


# ── zip metadata (bomba simulada por ratio) ────────────────────────────────
def test_zip_bomb_ratio_rejected():
    entries = [{"name": "a.json", "compress_size": 1, "file_size": 10**9}]
    state, errors = validate_zip_metadata(entries)
    assert state == ImportState.INVALID and errors


# ── import SIEMPRE dry-run: applied invariante False ───────────────────────
def test_dryrun_report_applied_is_false():
    assert DryRunReport(workspace="leyenda").applied is False


@pytest.mark.mutation
def test_mutation_import_never_applies():
    """El contrato real no tiene camino de APPLY: `dry_run_import` deja applied=False."""
    manifest = {"format": CONTRACT_FORMAT, "version": CONTRACT_VERSION, "workspace": "leyenda"}
    report = dry_run_import(manifest, [], target_workspace="leyenda")
    assert report.applied is False
    # El Enum de estados NO contiene 'APPLIED': ningún estado implica escritura.
    assert not any(s.value == "APPLIED" for s in ImportState)
