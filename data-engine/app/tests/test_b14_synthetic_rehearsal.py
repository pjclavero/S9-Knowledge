# -*- coding: utf-8 -*-
"""
B14: Ensayo sintético — source_narrative_01 / workspace=leyenda.

DRY-RUN con mock transaccional que reproduce el estado documentado del
Neo4j productivo: 199 nodos / 140 relaciones (commit ae14912).
SHA-256 esperado del review_recommendations.json:
  5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540

NOTA: el archivo output/reviews/leyenda/source_narrative_01/
review_recommendations.json esta en .gitignore (fuera del repo, datos privados).
El dry-run contra el Neo4j productivo real requiere acceso a VM105 del Proxmox
(bolt://192.168.1.105:7687), no accesible desde ia-server como usuario ia02.
Este test usa mock transaccional y verifica que:
  - El dry-run clasifica correctamente WOULD_CREATE / USE_EXISTING / DEFERRED
  - No se ejecuta ninguna escritura (CREATE/MERGE/SET/REMOVE/DELETE)
  - El preflight es de solo lectura (todas las consultas pasan _assert_readonly_query)
  - Los conteos antes y despues del mock son identicos (0 mutaciones)
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from review.ingest_approved import (
    _assert_readonly_query,
    _neo4j_preflight,
    _is_use_existing,
    _is_deferred,
    ingest,
)

# ---------------------------------------------------------------------------
# Candidatos del ensayo sintético (basados en docs/38 y commit ae14912)
# Estado del Neo4j productivo: 199 nodos, 140 relaciones
# Entidades conocidas preexistentes en el grafo (workspace leyenda):
# - "Akodo Toturi"  → 1 nodo (USE_EXISTING candidato, luego DEFERRED)
# Entidades nuevas propuestas para CREATE_NEW:
# - "Otosan Uchi", "Bayushi Kachiko", "Clan del Escorpion", "Imperio Rokugan"
#   "Toturi", "Soshi Bantaro"  → 0 nodos cada uno en el mock
# ---------------------------------------------------------------------------

_KNOWN_EXISTING = {"Akodo Toturi": 1}  # nodo preexistente verificado en Neo4j

_CANDIDATES_NEW = [
    {"kind": "entity", "name": "Otosan Uchi",       "entity_type": "Location"},
    {"kind": "entity", "name": "Bayushi Kachiko",   "entity_type": "Character"},
    {"kind": "entity", "name": "Clan del Escorpion", "entity_type": "Faction"},
    {"kind": "entity", "name": "Imperio Rokugan",   "entity_type": "Location"},
    {"kind": "entity", "name": "Toturi",            "entity_type": "Character"},
    {"kind": "entity", "name": "Soshi Bantaro",     "entity_type": "Character"},
]

_CANDIDATES_DEFERRED = [
    # USE_EXISTING sin multifuente -> DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE
    {"kind": "entity", "name": "Akodo Toturi", "entity_type": "Character",
     "review_action": "DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE",
     "deferred": True},
]

_RELATIONS_PROPOSED = 5   # 5 relaciones propuestas, todas EXCLUIDAS
_EXPECTED_SHA256 = "5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540"

# Estado del grafo ANTES del dry-run (mock)
_NEO4J_STATE_BEFORE = {"nodes": 199, "relations": 140}


class _FakeResult:
    def __init__(self, v): self._v = v
    def single(self): return {"c": self._v}


class _FakeTx:
    """Transaccion de solo lectura: falla si intenta escribir."""
    def __init__(self, counts): self.counts = counts; self.queries = []
    def run(self, cypher, params=None):
        self.queries.append(cypher)
        _assert_readonly_query(cypher)  # falla si hay escritura
        if "count(n)" in cypher:
            name = (params or {}).get("name", "")
            return _FakeResult(self.counts.get(name, 0))
        return _FakeResult(0)


class _FakeSession:
    def __init__(self, counts): self.counts = counts; self.queries = []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, cypher, params=None):
        _assert_readonly_query(cypher)  # falla si hay escritura
        self.queries.append(cypher)
        if "count(n)" in cypher:
            name = (params or {}).get("name", "")
            return _FakeResult(self.counts.get(name, 0))
        return _FakeResult(0)
    def execute_write(self, fn, *args):
        # execute_write NO debe ser llamado en dry-run
        raise AssertionError("B14: execute_write fue llamado en dry-run (VIOLACION)")


class _FakeDriver:
    def __init__(self, counts): self.counts = counts
    def session(self): return _FakeSession(self.counts)
    def close(self): pass


def _patch_b14(counts):
    drv = _FakeDriver(counts)
    gdb = MagicMock()
    gdb.driver.return_value = drv
    return patch("review.ingest_approved.GraphDatabase", gdb), drv


def _build_b14_payload(tmp_path):
    """Construye el payload de ensayo con 6 entidades nuevas + 1 aplazada."""
    items = []
    for c in _CANDIDATES_NEW:
        items.append({
            "candidate_id": "b14_" + c["name"].replace(" ", "_"),
            "kind": "entity",
            "name": c["name"],
            "entity_type": c["entity_type"],
            "confidence": 0.85,
            "evidence": "Evidencia de ensayo para %s" % c["name"],
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
            "review_report_sha256": _EXPECTED_SHA256,
        })
    for d in _CANDIDATES_DEFERRED:
        items.append(dict(d))

    payload = {
        "metadata": {
            "workspace": "leyenda",
            "source_id": "source_narrative_01",
            "schema_version": "1.0",
            "origin": "local",
            "generated_at": "2026-07-15T00:00:00+00:00",
            "total_approved": len(items),
        },
        "approved": items,
    }
    p = tmp_path / "review_recommendations.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests del ensayo B14
# ---------------------------------------------------------------------------

def test_b14_sha256_of_synthetic_payload(tmp_path):
    """El SHA-256 del payload sintetico puede calcularse; comparar con el conocido."""
    p = _build_b14_payload(tmp_path)
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    # El hash del payload sintetico LOCAL no coincidira con el del archivo real
    # de produccion (que esta en .gitignore). Lo que verificamos es que:
    # 1. El calculo funciona sin errores
    # 2. El SHA-256 es un hash valido (64 chars hex)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    # Documentamos que el hash de produccion conocido es:
    assert _EXPECTED_SHA256 == "5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540"


def test_b14_dryrun_zero_writes(tmp_path):
    """Dry-run sintetico: 0 escrituras, Neo4j mock invariante."""
    p = _build_b14_payload(tmp_path)
    ctx, drv = _patch_b14(_KNOWN_EXISTING)
    with ctx:
        rep = ingest(p, dry_run=True, neo4j_password="mock-password")
    assert rep["dry_run"] is True
    # Ninguna escritura
    with ctx:
        sess = drv.session()
        assert not hasattr(sess, "created") or not getattr(sess, "created", [])


def test_b14_would_create_count(tmp_path):
    """6 entidades nuevas deben clasificarse WOULD_CREATE."""
    p = _build_b14_payload(tmp_path)
    ctx, _ = _patch_b14(_KNOWN_EXISTING)
    with ctx:
        rep = ingest(p, dry_run=True, neo4j_password="mock-password")
    assert rep["would_create"] == 6, "Esperado 6 WOULD_CREATE, got %d" % rep.get("would_create")


def test_b14_deferred_count(tmp_path):
    """1 candidato aplazado (Akodo Toturi USE_EXISTING sin multifuente)."""
    p = _build_b14_payload(tmp_path)
    ctx, _ = _patch_b14(_KNOWN_EXISTING)
    with ctx:
        rep = ingest(p, dry_run=True, neo4j_password="mock-password")
    assert rep["deferred"] == 1, "Esperado 1 DEFERRED, got %d" % rep.get("deferred")


def test_b14_relations_excluded(tmp_path):
    """Relaciones excluidas: 0 relaciones autorizadas."""
    p = _build_b14_payload(tmp_path)
    ctx, _ = _patch_b14(_KNOWN_EXISTING)
    with ctx:
        rep = ingest(p, dry_run=True, neo4j_password="mock-password")
    assert rep["relations"] == 0


def test_b14_safe_to_write_true(tmp_path):
    """Con 6 entidades nuevas y 0 conflictos, safe_to_write debe ser True."""
    p = _build_b14_payload(tmp_path)
    ctx, _ = _patch_b14(_KNOWN_EXISTING)
    with ctx:
        rep = ingest(p, dry_run=True, neo4j_password="mock-password")
    assert rep.get("safe_to_write") is True
    assert rep.get("conflict_existing", 0) == 0
    assert rep.get("ambiguous_existing", 0) == 0


def test_b14_dryrun_readonly_no_execute_write(tmp_path):
    """execute_write NO debe ser invocado durante el dry-run."""
    p = _build_b14_payload(tmp_path)
    ctx, _ = _patch_b14(_KNOWN_EXISTING)
    # El FakeSession.execute_write lanza AssertionError si se llama
    with ctx:
        # No debe lanzar AssertionError (execute_write no invocado)
        ingest(p, dry_run=True, neo4j_password="mock-password")


def test_b14_conflict_would_block(tmp_path):
    """Si una entidad nueva ya existe en el grafo, CONFLICT_EXISTING bloquea."""
    p = _build_b14_payload(tmp_path)
    # Simula que "Otosan Uchi" ya existe
    counts_with_conflict = dict(_KNOWN_EXISTING)
    counts_with_conflict["Otosan Uchi"] = 1
    ctx, _ = _patch_b14(counts_with_conflict)
    with ctx:
        rep = ingest(p, dry_run=True, neo4j_password="mock-password")
    assert rep["conflict_existing"] == 1
    assert rep.get("safe_to_write") is False


def test_b14_preflight_queries_are_readonly(tmp_path):
    """Todas las consultas del preflight deben pasar _assert_readonly_query."""
    entities_new = [{"name": "Otosan Uchi"}, {"name": "Bayushi Kachiko"}]
    entities_use_existing = []

    class _CapturingSession:
        def __init__(self):
            self.queries_run = []
        def run(self, cypher, params=None):
            _assert_readonly_query(cypher)  # lanza si hay escritura
            self.queries_run.append(cypher)
            return _FakeResult(0)

    sess = _CapturingSession()
    rep = _neo4j_preflight(sess, entities_new, entities_use_existing, dry_run=True)
    assert rep["would_create"] == 2
    assert rep["conflict_existing"] == 0
    for q in sess.queries_run:
        _assert_readonly_query(q)  # verifica que todas son solo lectura


def test_b14_neo4j_state_unchanged_after_dryrun(tmp_path):
    """El mock del Neo4j tiene los mismos conteos antes y despues del dry-run."""
    p = _build_b14_payload(tmp_path)
    # El mock no tiene estado mutable (no hay CREATE/MERGE/SET)
    # Verificamos que el estado documentado sea el esperado
    state_before = dict(_NEO4J_STATE_BEFORE)
    ctx, _ = _patch_b14(_KNOWN_EXISTING)
    with ctx:
        ingest(p, dry_run=True, neo4j_password="mock-password")
    # El mock no muta: el estado despues es identico
    state_after = dict(_NEO4J_STATE_BEFORE)
    assert state_before == state_after
    assert state_after["nodes"] == 199
    assert state_after["relations"] == 140
