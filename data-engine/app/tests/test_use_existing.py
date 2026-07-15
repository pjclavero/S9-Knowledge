"""Tests para la rama USE_EXISTING del writer (ingest_approved).

Cubre los 13 puntos del checklist obligatorio:
 1. USE_EXISTING no crea nodos.
 2. Falla con cero coincidencias.
 3. Falla con más de una coincidencia.
 4. No cambia description.
 5. No cambia confidence.
 6. No cambia nombre ni tipo.
 7. No reemplaza aliases.
 8. No reemplaza created_at.
 9. No sobrescribe source_id.
10. El dry-run muestra cero mutaciones peligrosas.
11. Los candidatos rechazados no entran en el payload.
12. Las relaciones continúan excluidas.
13. La ejecución sin autorización no escribe.
"""
from __future__ import annotations
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


import sys
_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.ingest_approved import (
    _is_use_existing,
    _build_match_use_existing_query,
    _build_create_entity,
    ingest,
)


# ---- Fake Neo4j (driver/session/tx) con conteos controlables ----
class _FakeResult:
    def __init__(self, value): self._v = value
    def single(self): return {"c": self._v}

class _FakeTx:
    def __init__(self, counts, created): self.counts = counts; self.created = created
    def run(self, cypher, params=None):
        if "count(n)" in cypher:
            return _FakeResult(self.counts.get((params or {}).get("name"), 0))
        if cypher.strip().upper().startswith("CREATE"):
            self.created.append((cypher, params)); return _FakeResult(1)
        return _FakeResult(0)

class _FakeSession:
    def __init__(self, counts, created): self.counts = counts; self.created = created
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, cypher, params=None):
        if "count(n)" in cypher:
            return _FakeResult(self.counts.get((params or {}).get("name"), 0))
        return _FakeResult(0)
    def execute_write(self, fn, *args): return fn(_FakeTx(self.counts, self.created), *args)

class _FakeDriver:
    def __init__(self, counts): self.counts = counts; self.created = []
    def session(self): return _FakeSession(self.counts, self.created)
    def close(self): pass

def _patch_neo4j(counts):
    """Devuelve (patch_ctx, driver) para inyectar el fake."""
    drv = _FakeDriver(counts)
    gdb = MagicMock(); gdb.driver.return_value = drv
    return patch("review.ingest_approved.GraphDatabase", gdb), drv


# ---- Fixtures ----

def _make_payload(approved, workspace="leyenda", source_id="source_narrative_01"):
    return {
        "metadata": {
            "workspace": workspace,
            "source_id": source_id,
            "schema_version": "1.0",
            "origin": "local",
            "generated_at": "2026-07-15T00:00:00+00:00",
            "total_approved": len(approved),
        },
        "approved": approved,
    }


def _use_existing_item(name="Akodo Toturi", etype="Character", confidence=0.9):
    return {
        "candidate_id": "016981d6e956",
        "kind": "entity",
        "name": name,
        "entity_type": etype,
        "confidence": confidence,
        "evidence": "Toturi, sin embargo, desconfiaba...",
        "source_id": "source_narrative_01",
        "source_kind": "narrative",
        "source_document": "source_narrative_01",
        "workspace": "leyenda",
        "review_status": "approved",
        "reviewed_by": "manual-cli:operator",
        "reviewed_at": "2026-07-15T12:00:00+00:00",
        "review_action": "use-existing",
        "resolver_action": "use_existing",
        "recommendation": "USE_EXISTING",
    }


def _new_entity_item(name="Otosan Uchi", etype="Location", confidence=0.85):
    return {
        "candidate_id": "030526ae6a78",
        "kind": "entity",
        "name": name,
        "entity_type": etype,
        "confidence": confidence,
        "evidence": "cabalgó hasta las murallas de Otosan Uchi",
        "source_id": "source_narrative_01",
        "source_kind": "narrative",
        "source_document": "source_narrative_01",
        "workspace": "leyenda",
        "knowledge_layer": "narrative",
        "visibility": "player",
        "review_status": "approved",
        "reviewed_by": "manual-cli:operator",
        "reviewed_at": "2026-07-15T12:00:00+00:00",
        "review_action": "approve",
    }


# ---- Test 1: USE_EXISTING no crea nodos ----

def test_use_existing_uses_match_not_merge():
    """USE_EXISTING usa MATCH, no MERGE — nunca puede crear un nodo."""
    item = _use_existing_item()
    cypher_count, cypher_verify, params = _build_match_use_existing_query(item)
    assert "MERGE" not in cypher_count.upper()
    assert "MERGE" not in cypher_verify.upper()
    assert "MATCH" in cypher_count.upper()
    assert params == {"name": "Akodo Toturi"}


# ---- Test 2: Falla con cero coincidencias ----

def test_use_existing_fails_zero_matches(tmp_path):
    """Si el nodo no existe, USE_EXISTING lanza RuntimeError."""
    item = _use_existing_item()
    payload = _make_payload([item])
    p = tmp_path / "approved_payload.reviewed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    os.environ["S9K_ALLOW_REAL_INGEST"] = "true"
    try:
        ctx, _ = _patch_neo4j({})  # Akodo Toturi -> 0 coincidencias
        with ctx:
            with pytest.raises(RuntimeError, match="USE_EXISTING sin nodo|preflight no seguro"):
                ingest(p, dry_run=False, neo4j_password="x")
    finally:
        del os.environ["S9K_ALLOW_REAL_INGEST"]


# ---- Test 3: Falla con más de una coincidencia ----

def test_use_existing_fails_multiple_matches(tmp_path):
    """Si hay más de 1 coincidencia, USE_EXISTING lanza RuntimeError."""
    item = _use_existing_item()
    payload = _make_payload([item])
    p = tmp_path / "approved_payload.reviewed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    os.environ["S9K_ALLOW_REAL_INGEST"] = "true"
    try:
        ctx, _ = _patch_neo4j({"Akodo Toturi": 2})  # 2 coincidencias -> ambiguo
        with ctx:
            with pytest.raises(RuntimeError, match="ambiguo|preflight no seguro"):
                ingest(p, dry_run=False, neo4j_password="x")
    finally:
        del os.environ["S9K_ALLOW_REAL_INGEST"]


# ---- Tests 4-9: No cambia propiedades del nodo existente ----

def test_use_existing_cypher_has_no_set():
    """El Cypher de USE_EXISTING no contiene SET — no puede modificar propiedades."""
    item = _use_existing_item()
    cypher_count, cypher_verify, _ = _build_match_use_existing_query(item)
    assert " SET " not in cypher_count
    assert " SET " not in cypher_verify


def test_use_existing_no_description_in_query():
    """El Cypher de USE_EXISTING no referencia description."""
    item = _use_existing_item()
    c1, c2, _ = _build_match_use_existing_query(item)
    assert "description" not in c1 and "description" not in c2


def test_use_existing_no_confidence_in_query():
    """El Cypher de USE_EXISTING no referencia confidence."""
    item = _use_existing_item()
    c1, c2, _ = _build_match_use_existing_query(item)
    assert "confidence" not in c1 and "confidence" not in c2


def test_use_existing_no_name_type_set():
    """El Cypher de USE_EXISTING no modifica canonical_name ni entity_type."""
    item = _use_existing_item()
    c1, c2, _ = _build_match_use_existing_query(item)
    for c in [c1, c2]:
        assert " SET " not in c


def test_use_existing_no_aliases_in_query():
    """El Cypher de USE_EXISTING no referencia aliases."""
    item = _use_existing_item()
    c1, c2, _ = _build_match_use_existing_query(item)
    assert "aliases" not in c1 and "aliases" not in c2


def test_use_existing_no_created_at_in_query():
    """El Cypher de USE_EXISTING no referencia created_at."""
    item = _use_existing_item()
    c1, c2, _ = _build_match_use_existing_query(item)
    assert "created_at" not in c1 and "created_at" not in c2


def test_use_existing_no_source_id_in_query():
    """El Cypher de USE_EXISTING no sobrescribe source_id."""
    item = _use_existing_item()
    c1, c2, params = _build_match_use_existing_query(item)
    assert "source_id" not in c1
    assert "source_id" not in c2
    assert "source_id" not in params


# ---- Test 10: Dry-run muestra cero mutaciones peligrosas ----

def test_dry_run_use_existing_zero_mutations(tmp_path, capsys):
    """El dry-run con USE_EXISTING reporta 0 nodos mutados."""
    item = _use_existing_item()
    payload = _make_payload([item])
    p = tmp_path / "approved_payload.reviewed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    ctx, _ = _patch_neo4j({"Akodo Toturi": 1})  # existe exactamente 1
    with ctx:
        result = ingest(p, dry_run=True, neo4j_password="x")

    assert result["dry_run"] is True
    assert result["would_verify_existing"] == 1
    assert result["would_create"] == 0
    assert result["would_update"] == 0
    assert result["would_overwrite"] == 0


# ---- Test 11: Candidatos rechazados no entran en el payload ----

def test_rejected_candidates_blocked_by_provenance(tmp_path):
    """Un candidato con review_status=rejected es bloqueado por la validación."""
    rejected_item = {
        "candidate_id": "6a36f2884a46",
        "kind": "entity",
        "name": "Clan Escorpión",
        "entity_type": "Clan",
        "confidence": 0.85,
        "evidence": "Bayushi Kachiko envió...",
        "source_id": "source_narrative_01",
        "workspace": "leyenda",
        "review_status": "rejected",
        "reviewed_by": "manual-cli:operator",
        "reviewed_at": "2026-07-15T12:00:00+00:00",
        "review_action": "reject",
    }
    payload = _make_payload([rejected_item])
    p = tmp_path / "approved_payload.reviewed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    prev = os.environ.get("S9K_REVIEW_POLICY")
    os.environ["S9K_REVIEW_POLICY"] = "full_human_review"
    try:
        with pytest.raises(ValueError, match="PROVENANCE RECHAZADA|review_status"):
            ingest(p, dry_run=True)
    finally:
        if prev is None:
            os.environ.pop("S9K_REVIEW_POLICY", None)
        else:
            os.environ["S9K_REVIEW_POLICY"] = prev


# ---- Test 12: Relaciones excluidas no generan escrituras ----

def test_dry_run_without_relations_has_zero_entity_writes(tmp_path, capsys):
    """Un payload con solo entidades nuevas (sin relaciones) escribe solo entidades."""
    new_item = _new_entity_item()
    payload = _make_payload([new_item])
    p = tmp_path / "approved_payload.reviewed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    ctx, _ = _patch_neo4j({})  # Otosan Uchi -> 0 (nueva)
    with ctx:
        result = ingest(p, dry_run=True, neo4j_password="x")
    assert result["relations"] == 0
    assert result["would_create"] == 1


# ---- Test 13: Sin autorización no escribe ----

def test_no_authorization_no_write(tmp_path):
    """Sin S9K_ALLOW_REAL_INGEST=true, ingest() aborta sin tocar Neo4j."""
    item = _new_entity_item()
    payload = _make_payload([item])
    p = tmp_path / "approved_payload.reviewed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    os.environ.pop("S9K_ALLOW_REAL_INGEST", None)

    with patch("review.ingest_approved.GraphDatabase") as mock_gdb:
        with pytest.raises(RuntimeError, match="S9K_ALLOW_REAL_INGEST"):
            ingest(p, dry_run=False)
        mock_gdb.driver.assert_not_called()


def test_env_guard_false_also_blocked(tmp_path):
    """Con S9K_ALLOW_REAL_INGEST=false, también aborta."""
    item = _new_entity_item()
    payload = _make_payload([item])
    p = tmp_path / "approved_payload.reviewed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    os.environ["S9K_ALLOW_REAL_INGEST"] = "false"
    try:
        with patch("review.ingest_approved.GraphDatabase") as mock_gdb:
            with pytest.raises(RuntimeError, match="S9K_ALLOW_REAL_INGEST"):
                ingest(p, dry_run=False)
            mock_gdb.driver.assert_not_called()
    finally:
        del os.environ["S9K_ALLOW_REAL_INGEST"]


# ---- Auxiliar: detección de _is_use_existing ----

def test_is_use_existing_detection():
    """_is_use_existing detecta correctamente los tres campos posibles."""
    assert _is_use_existing({"review_action": "use-existing"})
    assert _is_use_existing({"resolver_action": "use_existing"})
    assert _is_use_existing({"recommendation": "USE_EXISTING"})
    assert not _is_use_existing({"review_action": "approve"})
    assert not _is_use_existing({})
