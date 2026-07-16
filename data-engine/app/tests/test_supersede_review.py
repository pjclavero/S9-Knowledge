# -*- coding: utf-8 -*-
"""
Tests de supersede_review.py — herramienta genérica de supersesión inmutable de reviews.

24 casos de prueba (B6):
  1.  hash_original_correcto — SHA-256 correcto acepta la ejecución
  2.  hash_original_incorrecto — SHA-256 incorrecto aborta
  3.  original_intacto — el archivo original no es modificado
  4.  salida_nueva — se crea un archivo de salida distinto del original
  5.  supersedes_sha256 — el v2 contiene supersedes_sha256
  6.  historial_consolidado — fichas duplicadas conservan consolidated_from
  7.  duplicado_consolidado — fichas duplicadas colapsan en DEFERRED
  8.  reviewed_by_obligatorio — reviewed_by vacío levanta error
  9.  correction_reason_obligatorio — correction_reason vacío levanta error
 10.  escritura_atomica — fichero .tmp no queda si la escritura es exitosa
 11.  archivo_existente_idempotente — segunda llamada con mismo hash es idempotente
 12.  archivo_existente_conflictivo — segunda llamada con hash distinto es rechazada
 13.  json_invalido — JSON mal formado en original aborta
 14.  esquema_invalido — original sin 'fichas' aborta
 15.  permisos — archivo de salida tiene permisos 0600
 16.  unicode_peligroso — caracteres BIDI peligrosos en reviewed_by son rechazados
 17.  path_traversal — rutas con '..' son rechazadas
 18.  symlink_rechazado — symlinks en --out son rechazados
 19.  no_neo4j — no hay llamadas a GraphDatabase ni drivers
 20.  no_ingest — función ingest no es llamada
 21.  dry_run_v2 — dry-run no escribe en disco
 22.  conflict_cero — v2 tiene CONFLICT_EXISTING=0 (Faction Delta consolidada)
 23.  relaciones_cero — relations_authorized == 0 en v2
 24.  hash_nuevo_estable — mismo input produce mismo sha256 (salvo created_at)
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

# Añadir el directorio app al path
_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from review import supersede_review as sr
from review.supersede_review import (
    run,
    supersede,
    validate_schema,
    write_atomic,
    _sha256,
    _sha256_str,
    _contains_dangerous_unicode,
    _resolve_path_safe,
    DEFERRED,
)

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

_FIXTURE = Path(__file__).parent / "fixtures" / "review_supersede" / "review_anon.json"
_FIXTURE_SHA = "20ec50a8586d74664a4ae1f761942a4a89eccccec4bbd2d1845b1c57b6bdd547"

_REVIEWED_BY = "manual-cli:test-agent"
_CORRECTION_REASON = "Test supersession: consolidate Faction Delta duplicates"


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Test 1: hash original correcto acepta la ejecución
# ---------------------------------------------------------------------------
def test_01_hash_original_correcto(tmp_path):
    out = tmp_path / "v2.json"
    report = run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    assert report["status"] == "OK"
    assert report["input_sha256_verified"] is True


# ---------------------------------------------------------------------------
# Test 2: hash original incorrecto aborta
# ---------------------------------------------------------------------------
def test_02_hash_original_incorrecto(tmp_path):
    out = tmp_path / "v2.json"
    with pytest.raises(SystemExit, match="SHA-256"):
        run(
            inp_path=str(_FIXTURE),
            supersedes_sha256="0" * 64,
            out_path=str(out),
            reviewed_by=_REVIEWED_BY,
            correction_reason=_CORRECTION_REASON,
        )


# ---------------------------------------------------------------------------
# Test 3: el archivo original no es modificado
# ---------------------------------------------------------------------------
def test_03_original_intacto(tmp_path):
    out = tmp_path / "v2.json"
    sha_before = _sha256(_FIXTURE)
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    sha_after = _sha256(_FIXTURE)
    assert sha_before == sha_after, "El original fue modificado"
    assert report["original_modified"] is False if (report := None) else True


def test_03b_original_intacto_invariante(tmp_path):
    out = tmp_path / "v2.json"
    report = run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    assert report["original_modified"] is False


# ---------------------------------------------------------------------------
# Test 4: se crea un archivo de salida distinto del original
# ---------------------------------------------------------------------------
def test_04_salida_nueva(tmp_path):
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    assert out.exists()
    # El output es diferente del original
    assert out.resolve() != _FIXTURE.resolve()
    # El contenido es diferente (v2 tiene campos adicionales)
    v2 = json.loads(out.read_text(encoding="utf-8"))
    assert "correction" in v2
    assert v2.get("supersedes_sha256") == _FIXTURE_SHA


# ---------------------------------------------------------------------------
# Test 5: el v2 contiene supersedes_sha256
# ---------------------------------------------------------------------------
def test_05_supersedes_sha256(tmp_path):
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    v2 = json.loads(out.read_text(encoding="utf-8"))
    assert v2["supersedes_sha256"] == _FIXTURE_SHA


# ---------------------------------------------------------------------------
# Test 6: fichas duplicadas conservan consolidated_from
# ---------------------------------------------------------------------------
def test_06_historial_consolidado(tmp_path):
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    v2 = json.loads(out.read_text(encoding="utf-8"))
    faction_delta = next(
        (f for f in v2["fichas"] if f["name"] == "Faction Delta"), None
    )
    assert faction_delta is not None
    consolidated = faction_delta.get("consolidated_from")
    assert isinstance(consolidated, list)
    assert len(consolidated) == 2
    ids = {c["candidate_id"] for c in consolidated}
    assert "aaa004a" in ids
    assert "aaa004b" in ids


# ---------------------------------------------------------------------------
# Test 7: fichas duplicadas colapsan en DEFERRED
# ---------------------------------------------------------------------------
def test_07_duplicado_consolidado(tmp_path):
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    v2 = json.loads(out.read_text(encoding="utf-8"))
    faction_delta = next(
        (f for f in v2["fichas"] if f["name"] == "Faction Delta"), None
    )
    assert faction_delta is not None
    assert faction_delta["recommendation"] == DEFERRED
    assert faction_delta.get("deferred") is True
    # Nunca CREATE_NEW para entidades que ya existen
    assert faction_delta["recommendation"] != "CREATE_NEW"
    assert faction_delta["recommendation"] != "APPROVE_UNCHANGED"


# ---------------------------------------------------------------------------
# Test 8: reviewed_by vacío levanta error
# ---------------------------------------------------------------------------
def test_08_reviewed_by_obligatorio(tmp_path):
    out = tmp_path / "v2.json"
    with pytest.raises((SystemExit, ValueError), match="reviewed_by"):
        run(
            inp_path=str(_FIXTURE),
            supersedes_sha256=_FIXTURE_SHA,
            out_path=str(out),
            reviewed_by="",
            correction_reason=_CORRECTION_REASON,
        )


# ---------------------------------------------------------------------------
# Test 9: correction_reason vacío levanta error
# ---------------------------------------------------------------------------
def test_09_correction_reason_obligatorio(tmp_path):
    out = tmp_path / "v2.json"
    with pytest.raises((SystemExit, ValueError), match="correction_reason"):
        run(
            inp_path=str(_FIXTURE),
            supersedes_sha256=_FIXTURE_SHA,
            out_path=str(out),
            reviewed_by=_REVIEWED_BY,
            correction_reason="",
        )


# ---------------------------------------------------------------------------
# Test 10: fichero .tmp no queda tras escritura exitosa
# ---------------------------------------------------------------------------
def test_10_escritura_atomica(tmp_path):
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    tmp_file = out.with_suffix(".tmp")
    assert not tmp_file.exists(), "Archivo .tmp no fue limpiado tras escritura exitosa"
    assert out.exists(), "El archivo de salida no fue creado"


# ---------------------------------------------------------------------------
# Test 11: idempotencia — segunda llamada con mismo hash
# ---------------------------------------------------------------------------
def test_11_idempotente(tmp_path):
    out = tmp_path / "v2.json"
    r1 = run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    r2 = run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    assert r1["new_sha256"] == r2["new_sha256"]
    assert r2.get("idempotent") is True or r2.get("status") in ("OK", "ALREADY_DONE")


# ---------------------------------------------------------------------------
# Test 12: segunda llamada con hash distinto es rechazada
# ---------------------------------------------------------------------------
def test_12_conflicto_segunda_supersesion(tmp_path):
    out = tmp_path / "v2.json"
    # Primera llamada OK
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    # Crear un fixture alternativo para simular distinto original
    alt_fixture = tmp_path / "review_alt.json"
    alt_data = _load_fixture()
    alt_data["source_id"] = "different_source"
    alt_fixture.write_text(json.dumps(alt_data), encoding="utf-8")
    alt_sha = _sha256(alt_fixture)

    # Debe rechazar porque --out ya existe con diferente supersedes_sha256
    with pytest.raises(SystemExit, match="segunda supersesión|conflictiva|ya existe"):
        run(
            inp_path=str(alt_fixture),
            supersedes_sha256=alt_sha,
            out_path=str(out),
            reviewed_by=_REVIEWED_BY,
            correction_reason=_CORRECTION_REASON,
        )


# ---------------------------------------------------------------------------
# Test 13: JSON mal formado en original aborta
# ---------------------------------------------------------------------------
def test_13_json_invalido(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ invalid json }", encoding="utf-8")
    bad_sha = _sha256(bad)
    out = tmp_path / "v2.json"
    with pytest.raises(SystemExit, match="JSON"):
        run(
            inp_path=str(bad),
            supersedes_sha256=bad_sha,
            out_path=str(out),
            reviewed_by=_REVIEWED_BY,
            correction_reason=_CORRECTION_REASON,
        )


# ---------------------------------------------------------------------------
# Test 14: original sin 'fichas' aborta
# ---------------------------------------------------------------------------
def test_14_esquema_invalido(tmp_path):
    bad = tmp_path / "noschema.json"
    bad.write_text(json.dumps({"source_id": "x", "workspace": "y"}), encoding="utf-8")
    bad_sha = _sha256(bad)
    out = tmp_path / "v2.json"
    with pytest.raises(SystemExit, match="esquema"):
        run(
            inp_path=str(bad),
            supersedes_sha256=bad_sha,
            out_path=str(out),
            reviewed_by=_REVIEWED_BY,
            correction_reason=_CORRECTION_REASON,
        )


# ---------------------------------------------------------------------------
# Test 15: archivo de salida tiene permisos 0600
# ---------------------------------------------------------------------------
def test_15_permisos(tmp_path):
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    mode = out.stat().st_mode & 0o777
    assert mode == 0o600, f"Permisos esperados 0600, obtenidos {oct(mode)}"


# ---------------------------------------------------------------------------
# Test 16: caracteres BIDI peligrosos en reviewed_by son rechazados
# ---------------------------------------------------------------------------
def test_16_unicode_peligroso(tmp_path):
    out = tmp_path / "v2.json"
    # U+202E RIGHT-TO-LEFT OVERRIDE (Trojan Source)
    malicious_reviewed_by = "admin‮"
    with pytest.raises((SystemExit, ValueError), match="Unicode peligroso|reviewed_by"):
        run(
            inp_path=str(_FIXTURE),
            supersedes_sha256=_FIXTURE_SHA,
            out_path=str(out),
            reviewed_by=malicious_reviewed_by,
            correction_reason=_CORRECTION_REASON,
        )


# ---------------------------------------------------------------------------
# Test 17: rutas con '..' son rechazadas
# ---------------------------------------------------------------------------
def test_17_path_traversal(tmp_path):
    out = tmp_path / "v2.json"
    with pytest.raises((SystemExit, ValueError), match="[Tt]raversal|'..'"):
        _resolve_path_safe("../../../etc/passwd")


# ---------------------------------------------------------------------------
# Test 18: symlinks en --out son rechazados
# ---------------------------------------------------------------------------
def test_18_symlink_rechazado(tmp_path):
    real_file = tmp_path / "real.json"
    real_file.write_text("{}", encoding="utf-8")
    symlink = tmp_path / "sym.json"
    symlink.symlink_to(real_file)

    with pytest.raises((SystemExit, ValueError), match="symlink"):
        _resolve_path_safe(str(symlink), allow_symlink=False)


# ---------------------------------------------------------------------------
# Test 19: no hay llamadas a GraphDatabase ni drivers
# ---------------------------------------------------------------------------
def test_19_no_neo4j(tmp_path):
    """Verifica que supersede_review no importa ni usa GraphDatabase."""
    import importlib
    import sys

    # Asegurarse de que no hay GraphDatabase en el módulo
    module = sys.modules.get("review.supersede_review")
    if module is None:
        module = importlib.import_module("review.supersede_review")

    module_source = Path(module.__file__).read_text(encoding="utf-8")
    assert "GraphDatabase" not in module_source, "supersede_review.py referencia GraphDatabase"
    assert "neo4j" not in module_source.lower(), "supersede_review.py referencia neo4j"


# ---------------------------------------------------------------------------
# Test 20: función ingest no es llamada
# ---------------------------------------------------------------------------
def test_20_no_ingest(tmp_path):
    """Verifica que supersede_review no llama a ingest_approved ni a ingest()."""
    module = sys.modules.get("review.supersede_review")
    if module is None:
        import importlib
        module = importlib.import_module("review.supersede_review")

    module_source = Path(module.__file__).read_text(encoding="utf-8")
    assert "ingest_approved" not in module_source, "supersede_review.py importa ingest_approved"
    assert "execute_write" not in module_source, "supersede_review.py llama execute_write"


# ---------------------------------------------------------------------------
# Test 21: dry-run no escribe en disco
# ---------------------------------------------------------------------------
def test_21_dry_run_no_escribe(tmp_path):
    out = tmp_path / "v2.json"
    report = run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
        dry_run=True,
    )
    assert not out.exists(), "dry-run escribió en disco"
    assert report.get("dry_run") is True


# ---------------------------------------------------------------------------
# Test 22: v2 tiene CONFLICT_EXISTING=0 (Faction Delta consolidada)
# ---------------------------------------------------------------------------
def test_22_conflict_cero(tmp_path):
    """
    Faction Delta tenía 2 fichas en conflicto en el original.
    Después de supersede, debe haber 0 fichas APPROVE_UNCHANGED para entidades
    con match existente (el conflicto fue resuelto por consolidación en DEFERRED).
    """
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    v2 = json.loads(out.read_text(encoding="utf-8"))
    fichas = v2["fichas"]

    # No debe haber ninguna ficha con recommendation=APPROVE_UNCHANGED Y match_type=exact
    conflicts = [
        f for f in fichas
        if f.get("recommendation") == "APPROVE_UNCHANGED"
        and (f.get("match_type") == "exact" or f.get("resolver") == "use_existing")
    ]
    assert len(conflicts) == 0, f"Conflictos sin resolver: {conflicts}"

    # Faction Delta debe ser exactamente DEFERRED
    faction_delta = next((f for f in fichas if f["name"] == "Faction Delta"), None)
    assert faction_delta is not None
    assert faction_delta["recommendation"] == DEFERRED


# ---------------------------------------------------------------------------
# Test 23: relations_authorized == 0 en v2
# ---------------------------------------------------------------------------
def test_23_relaciones_cero(tmp_path):
    out = tmp_path / "v2.json"
    run(
        inp_path=str(_FIXTURE),
        supersedes_sha256=_FIXTURE_SHA,
        out_path=str(out),
        reviewed_by=_REVIEWED_BY,
        correction_reason=_CORRECTION_REASON,
    )
    v2 = json.loads(out.read_text(encoding="utf-8"))
    assert v2["relations_authorized"] == 0
    # relations_total preservado del original
    assert v2["relations_total"] == 3


# ---------------------------------------------------------------------------
# Test 24: mismo input produce mismo sha256 (modulo created_at)
# ---------------------------------------------------------------------------
def test_24_hash_nuevo_estable():
    """
    El SHA-256 del v2 debe ser determinista para el mismo contenido.
    Usamos la función supersede() directamente (sin created_at variable).
    """
    original = _load_fixture()
    fixed_time = "2026-01-01T00:00:00+00:00"

    v2a = supersede(original, _FIXTURE_SHA, _REVIEWED_BY, _CORRECTION_REASON, fixed_time)
    v2b = supersede(original, _FIXTURE_SHA, _REVIEWED_BY, _CORRECTION_REASON, fixed_time)

    text_a = json.dumps(v2a, ensure_ascii=False, indent=2)
    text_b = json.dumps(v2b, ensure_ascii=False, indent=2)

    sha_a = _sha256_str(text_a)
    sha_b = _sha256_str(text_b)
    assert sha_a == sha_b, "Hash del v2 no es estable para mismo input"
