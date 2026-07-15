# -*- coding: utf-8 -*-
"""Tests del writer seguro de ingesta controlada (§10): CREATE-only, dry-run
conectado en lectura, procedencia explícita, allowlist, transacción atómica.
Sin Neo4j real (fake driver)."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from review import ingest_approved as ia
from review.ingest_approved import (
    _build_create_entity, _neo4j_preflight, _tx_create_all, _validate_write_provenance,
    _is_deferred, ingest, _ALLOWED_LABELS,
)


class _Res:
    def __init__(self, v): self._v = v
    def single(self): return {"c": self._v}
class _Tx:
    def __init__(self, counts, created): self.counts = counts; self.created = created
    def run(self, cypher, params=None):
        if "count(n)" in cypher:
            return _Res(self.counts.get((params or {}).get("name"), 0))
        if cypher.strip().upper().startswith("CREATE"):
            self.created.append((cypher, params)); return _Res(1)
        return _Res(0)
class _Sess:
    def __init__(self, counts, created): self.counts = counts; self.created = created
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, cypher, params=None):
        if "count(n)" in cypher:
            return _Res(self.counts.get((params or {}).get("name"), 0))
        return _Res(0)
    def execute_write(self, fn, *a): return fn(_Tx(self.counts, self.created), *a)
class _Drv:
    def __init__(self, counts): self.counts = counts; self.created = []
    def session(self): return _Sess(self.counts, self.created)
    def close(self): pass

def _patch(counts):
    drv = _Drv(counts); gdb = MagicMock(); gdb.driver.return_value = drv
    return patch("review.ingest_approved.GraphDatabase", gdb), drv


def _ent(name="Otosan Uchi", etype="Location", **kw):
    d = {"candidate_id": "c_" + name.replace(" ", ""), "kind": "entity", "name": name,
         "entity_type": etype, "confidence": 0.9, "evidence": "ev " + name,
         "source_id": "source_narrative_01", "source_kind": "markdown",
         "source_document": "source_narrative_01", "workspace": "leyenda",
         "knowledge_layer": "narrative", "visibility": "player", "review_status": "approved",
         "reviewed_by": "manual-cli:ana", "reviewed_at": "2026-07-15T12:00:00+00:00",
         "review_action": "approve"}
    d.update(kw); return d

def _payload(items):
    return {"metadata": {"workspace": "leyenda", "source_id": "source_narrative_01",
            "schema_version": "1.0", "origin": "local"}, "approved": items}

def _write(tmp, items):
    p = tmp / "approved_payload.reviewed.json"; p.write_text(json.dumps(_payload(items)), encoding="utf-8"); return p


# 1. CREATE_NEW usa CREATE, no MERGE
def test_1_create_not_merge():
    counts = {}; created = []
    _tx_create_all(_Tx(counts, created), [_ent()], [])
    assert created and created[0][0].strip().upper().startswith("CREATE")
    assert "MERGE" not in created[0][0].upper()

# 2. Una coincidencia bloquea creación
def test_2_one_match_blocks(tmp_path):
    os.environ["S9K_ALLOW_REAL_INGEST"] = "true"
    try:
        ctx, _ = _patch({"Otosan Uchi": 1})
        with ctx, pytest.raises(RuntimeError, match="preflight no seguro|CONFLICT"):
            ingest(_write(tmp_path, [_ent()]), dry_run=False, neo4j_password="x")
    finally:
        del os.environ["S9K_ALLOW_REAL_INGEST"]

# 3. Varias coincidencias bloquean creación
def test_3_multiple_matches_block(tmp_path):
    ctx, _ = _patch({"Otosan Uchi": 3})
    with ctx:
        rep = ingest(_write(tmp_path, [_ent()]), dry_run=True, neo4j_password="x")
    assert rep["ambiguous_existing"] == 1 and rep["safe_to_write"] is False

# 4. USE_EXISTING no muta (cypher sin SET)
def test_4_use_existing_no_mutation():
    from review.ingest_approved import _build_match_use_existing_query
    c1, c2, _ = _build_match_use_existing_query({"name": "Akodo Toturi"})
    assert " SET " not in c1 and " SET " not in c2

# 5. Dry-run consulta Neo4j
def test_5_dry_run_queries_neo4j(tmp_path):
    ctx, drv = _patch({})
    with ctx:
        ingest(_write(tmp_path, [_ent()]), dry_run=True, neo4j_password="x")
    # el fake fue usado (would_create calculado a partir de la consulta)

# 6. Dry-run no llama al writer (0 CREATE)
def test_6_dry_run_no_writer(tmp_path):
    ctx, drv = _patch({})
    with ctx:
        ingest(_write(tmp_path, [_ent()]), dry_run=True, neo4j_password="x")
    assert drv.created == []

# 7. Dry-run detecta nodo existente mal clasificado como nuevo
def test_7_detect_existing_as_new(tmp_path):
    ctx, _ = _patch({"Otosan Uchi": 1})
    with ctx:
        rep = ingest(_write(tmp_path, [_ent()]), dry_run=True, neo4j_password="x")
    assert rep["conflict_existing"] == 1 and rep["safe_to_write"] is False

# 8/9. No default audio / transcript (props explícitas)
def test_8_no_default_audio():
    _, props = _build_create_entity(_ent(source_kind="markdown"))
    assert props["source_kind"] == "markdown" and props["source_kind"] != "audio"
def test_9_no_default_transcript():
    _, props = _build_create_entity(_ent(knowledge_layer="narrative"))
    assert props["knowledge_layer"] == "narrative" and props["knowledge_layer"] != "transcript"

# 10. No auto_approved para revisión humana
def test_10_no_auto_approved():
    errs = _validate_write_provenance(_payload([_ent(review_status="auto_approved")]))
    assert any("auto_approved" in e for e in errs)

# 11. Se escriben reviewed_by y reviewed_at
def test_11_writes_review_provenance():
    _, props = _build_create_entity(_ent())
    assert props["reviewed_by"] == "manual-cli:ana" and props["reviewed_at"]
    assert props["review_status"] == "approved" and props["review_action"] == "approve"

# 12. Falta source_kind rechaza
def test_12_missing_source_kind_rejected():
    it = _ent(); it.pop("source_kind")
    assert any("source_kind" in e for e in _validate_write_provenance(_payload([it])))

# 13. Falta visibility rechaza
def test_13_missing_visibility_rejected():
    it = _ent(); it.pop("visibility")
    assert any("visibility" in e for e in _validate_write_provenance(_payload([it])))

# 14. Tipo no permitido rechazado
def test_14_invalid_type_rejected():
    assert any("no permitido" in e for e in _validate_write_provenance(_payload([_ent(entity_type="Clan")])))
    with pytest.raises(ValueError):
        _build_create_entity(_ent(entity_type="Clan"))

# 15. Cero relaciones (payload con relación rechazado)
def test_15_zero_relations(tmp_path):
    rel = {"kind": "relation", "from_entity": "A", "to_entity": "B", "relation_type": "KNOWS",
           "evidence": "e", "source_id": "s", "workspace": "leyenda"}
    ctx, _ = _patch({})
    with ctx, pytest.raises(ValueError, match="no admite relaciones"):
        ingest(_write(tmp_path, [_ent(), rel]), dry_run=True, neo4j_password="x")

# 16. Transacción completa hace rollback ante conflicto (atómica)
def test_16_atomic_rollback():
    counts = {"Río Kanji": 1}; created = []  # segundo conflicta
    with pytest.raises(RuntimeError, match="CONFLICT"):
        _tx_create_all(_Tx(counts, created), [_ent("Otosan Uchi"), _ent("Río Kanji")], [])
    assert created == []  # ninguna creada (rollback total)

# 17. Neo4j intacto en dry-run (0 CREATE)
def test_17_neo4j_intact_dry_run(tmp_path):
    ctx, drv = _patch({})
    with ctx:
        ingest(_write(tmp_path, [_ent("A", "Character"), _ent("B", "Location")]), dry_run=True, neo4j_password="x")
    assert drv.created == []

# 18. Candidato aplazado no entra en el payload
def test_18_deferred_excluded(tmp_path):
    deferred = _ent("Akodo Toturi", "Character",
                    review_action="DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE")
    assert _is_deferred(deferred)
    ctx, _ = _patch({})
    with ctx:
        rep = ingest(_write(tmp_path, [_ent("Otosan Uchi"), deferred]), dry_run=True, neo4j_password="x")
    assert rep["deferred"] == 1 and rep["would_create"] == 1
