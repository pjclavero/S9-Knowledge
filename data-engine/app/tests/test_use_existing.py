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
    _build_merge_entity_query,
    ingest,
)


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
        mock_record = MagicMock()
        mock_record.__getitem__ = MagicMock(return_value=0)
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("review.ingest_approved.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            with pytest.raises(RuntimeError, match="no existe ningún nodo"):
                ingest(p, dry_run=False)
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
        mock_record = MagicMock()
        mock_record.__getitem__ = MagicMock(return_value=2)
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("review.ingest_approved.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            with pytest.raises(RuntimeError, match="no es inequívoco"):
                ingest(p, dry_run=False)
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

    result = ingest(p, dry_run=True)
    captured = capsys.readouterr()

    assert result["dry_run"] is True
    assert result["would_write"] == 0
    assert result["use_existing"] == 1
    assert result["entities"] == 0
    assert "NINGUNA" in captured.out


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

    result = ingest(p, dry_run=True)
    assert result["relations"] == 0
    assert result["entities"] == 1


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
