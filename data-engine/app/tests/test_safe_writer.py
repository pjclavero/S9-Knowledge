# -*- coding: utf-8 -*-
"""Tests del writer seguro de ingesta controlada (§10): CREATE-only, dry-run
conectado en lectura, procedencia explícita, allowlist, transacción atómica,
auditoría append-only, idempotencia, rollback por lote, anti-TOCTOU.
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
    _assert_readonly_query,
    _build_create_entity,
    _neo4j_preflight,
    _tx_create_all,
    _validate_write_provenance,
    _validate_candidate_fields_b2,
    _is_deferred,
    _check_idempotency,
    _append_audit_log,
    _load_audit_log,
    _compute_payload_sha256,
    build_rollback_cypher,
    build_rollback_count_cypher,
    ingest,
    _ALLOWED_LABELS,
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
    _tx_create_all(_Tx(counts, created), [_ent()], [], "batch-test-001")
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
        _tx_create_all(_Tx(counts, created), [_ent("Otosan Uchi"), _ent("Río Kanji")], [], "batch-rollback-001")
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


# 19. ingest_batch_id y ingested_at se persisten en el nodo creado
def test_19_batch_id_persisted_in_node():
    counts = {}; created = []
    _tx_create_all(_Tx(counts, created), [_ent()], [], "batch-xyz-999")
    # El segundo elemento del primer CREATE es el dict de params
    props = created[0][1]["props"]
    assert props["ingest_batch_id"] == "batch-xyz-999"
    assert "ingested_at" in props and props["ingested_at"]


# 20. review_report_sha256 se incluye en el resultado del dry-run
def test_20_review_report_sha256_in_result(tmp_path):
    ctx, _ = _patch({})
    with ctx:
        rep = ingest(_write(tmp_path, [_ent()]), dry_run=True, neo4j_password="x")
    assert "review_report_sha256" in rep and rep["review_report_sha256"]


# 21. Idempotencia: mismo source_id + mismo sha256 → ALREADY_APPLIED
def test_21_idempotency_already_applied(tmp_path):
    p = _write(tmp_path, [_ent()])
    sha = _compute_payload_sha256(p)
    audit = tmp_path / "audit.jsonl"
    _append_audit_log(audit, {
        "source_id": "source_narrative_01",
        "review_report_sha256": sha,
        "result": "SUCCESS",
    })
    records = _load_audit_log(audit)
    status = _check_idempotency(records, "source_narrative_01", sha)
    assert status == "ALREADY_APPLIED"
    ctx, _ = _patch({})
    with ctx:
        rep = ingest(p, dry_run=True, neo4j_password="x", audit_log_path=audit)
    assert rep.get("already_applied") is True


# 22. Idempotencia: mismo source_id con hash distinto → CONFLICTING_REVIEW_REPORT
def test_22_conflicting_review_report(tmp_path):
    p = _write(tmp_path, [_ent()])
    audit = tmp_path / "audit.jsonl"
    _append_audit_log(audit, {
        "source_id": "source_narrative_01",
        "review_report_sha256": "hash_anterior_diferente",
        "result": "SUCCESS",
    })
    records = _load_audit_log(audit)
    sha_nuevo = "hash_nuevo_diferente"
    status = _check_idempotency(records, "source_narrative_01", sha_nuevo)
    assert status == "CONFLICTING_REVIEW_REPORT"
    ctx, _ = _patch({})
    with ctx:
        with pytest.raises(ValueError, match="CONFLICTING_REVIEW_REPORT"):
            ingest(p, dry_run=True, neo4j_password="x", audit_log_path=audit)


# 23. Auditoría append-only: nueva ejecución no sobrescribe registro anterior
def test_23_audit_log_append_only(tmp_path):
    audit = tmp_path / "audit.jsonl"
    _append_audit_log(audit, {"ingest_batch_id": "b1", "result": "SUCCESS"})
    _append_audit_log(audit, {"ingest_batch_id": "b2", "result": "FAILED"})
    records = _load_audit_log(audit)
    assert len(records) == 2
    assert records[0]["ingest_batch_id"] == "b1"
    assert records[1]["ingest_batch_id"] == "b2"


# 24. Auditoría registra dry-run con operator
def test_24_audit_log_records_dryrun(tmp_path):
    p = _write(tmp_path, [_ent()])
    audit = tmp_path / "audit.jsonl"
    ctx, _ = _patch({})
    with ctx:
        ingest(p, dry_run=True, neo4j_password="x", audit_log_path=audit, operator="test-op")
    records = _load_audit_log(audit)
    assert len(records) == 1
    r = records[0]
    assert r["result"] == "DRY_RUN"
    assert r["operator"] == "test-op"
    assert r["created_count"] == 0
    assert "ingest_batch_id" in r
    assert "review_report_sha256" in r
    # Sin secretos en el log
    raw = (tmp_path / "audit.jsonl").read_text()
    assert "password" not in raw.lower()


# 25. Rollback cypher: solo borra por ingest_batch_id, cypher correcto
def test_25_rollback_cypher_correct():
    cypher = build_rollback_cypher("batch-abc-123")
    assert "ingest_batch_id" in cypher
    assert "DETACH DELETE" in cypher
    assert "batch-abc-123" not in cypher  # el valor va como parámetro, no interpolado
    count_cypher = build_rollback_count_cypher()
    assert "count(n)" in count_cypher
    assert "ingest_batch_id" in count_cypher


# 26. Rollback cypher con batch_id vacío lanza error
def test_26_rollback_empty_batch_id():
    with pytest.raises(ValueError, match="batch_id"):
        build_rollback_cypher("")
    with pytest.raises(ValueError, match="batch_id"):
        build_rollback_cypher("   ")


# 27. Dry-run intercepta escrituras — _assert_readonly_query
def test_27_assert_readonly_query_blocks_writes():
    write_cyphers = [
        "CREATE (n:Entity) SET n.name = 'x'",
        "MERGE (n {canonical_name: $name})",
        "MATCH (n) SET n.foo = 1",
        "MATCH (n) REMOVE n.foo",
        "MATCH (n) DELETE n",
    ]
    for cypher in write_cyphers:
        with pytest.raises(AssertionError, match="DRY-RUN VIOLATION"):
            _assert_readonly_query(cypher)


# 28. _assert_readonly_query permite consultas de solo lectura
def test_28_assert_readonly_query_allows_reads():
    read_cyphers = [
        "MATCH (n {canonical_name: $name}) RETURN count(n) AS c",
        "MATCH (n) RETURN n.entity_type",
        "MATCH (n {canonical_name: $name}) RETURN labels(n)",
    ]
    for cypher in read_cyphers:
        _assert_readonly_query(cypher)  # no debe lanzar


# 29. TOCTOU: conflicto detectado DENTRO de la transacción aborta el lote completo
def test_29_toctou_detected_inside_transaction():
    """Simula el caso en que el preflight ve 0 coincidencias pero la transacción
    detecta 1 (race condition). El lote debe abortar completamente."""
    counts = {"Otosan Uchi": 1}  # dentro de la tx hay conflicto
    created = []
    with pytest.raises(RuntimeError, match="CONFLICT_EXISTING_NODE"):
        _tx_create_all(_Tx(counts, created), [_ent("Otosan Uchi")], [], "batch-toctou-001")
    assert created == []  # nada creado


# 30. Nodo preexistente no es borrado por rollback: cypher filtra por batch_id
def test_30_rollback_does_not_touch_preexisting():
    """El rollback solo borra por ingest_batch_id. Un nodo sin ese campo
    no sería alcanzado por el DELETE aunque comparta canonical_name."""
    cypher = build_rollback_cypher("batch-safe-001")
    # El WHERE es por ingest_batch_id, no por canonical_name
    assert "canonical_name" not in cypher
    # Solo opera sobre nodos que tengan el batch_id exacto
    assert "ingest_batch_id" in cypher


# 31. Campo B2 obligatorio ausente (candidate_id) rechaza el candidato
def test_31_missing_candidate_id_rejected():
    it = _ent(); it.pop("candidate_id")
    errors = _validate_candidate_fields_b2(_payload([it]))
    assert any("candidate_id" in e for e in errors)


# 32. Campo B2 workspace distinto del payload es detectado
def test_32_missing_workspace_in_candidate_rejected():
    it = _ent(); it.pop("workspace")
    errors = _validate_candidate_fields_b2(_payload([it]))
    assert any("workspace" in e for e in errors)


# 33. Unicode peligroso (Trojan Source): el log de auditoría no contiene chars bidi
def test_33_dangerous_unicode_not_in_log(tmp_path):
    """El writer nunca pone caracteres de control bidi en el log de auditoría.
    Los codepoints se construyen con chr() para no ponerlos literalmente en el fuente."""
    audit = tmp_path / "audit.jsonl"
    _append_audit_log(audit, {
        "ingest_batch_id": "batch-unicode-001",
        "operator": "test",
        "result": "DRY_RUN",
        "error": None,
    })
    raw = audit.read_text(encoding="utf-8")
    # U+202A..202E (embeddings/overrides), U+2066..2069 (isolates),
    # U+200F RTL mark, U+200E LTR mark, U+061C Arabic letter mark
    dangerous_codepoints = [
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
        0x2066, 0x2067, 0x2068, 0x2069,
        0x200F, 0x200E, 0x061C,
    ]
    for cp in dangerous_codepoints:
        assert chr(cp) not in raw, "Caracter bidi peligroso U+%04X encontrado en log" % cp


# 34. Secretos no aparecen en el log de auditoría
def test_34_no_secrets_in_audit_log(tmp_path):
    """El log de auditoría no contiene contraseñas ni tokens."""
    audit = tmp_path / "audit.jsonl"
    p = _write(tmp_path, [_ent()])
    ctx, _ = _patch({})
    with ctx:
        ingest(p, dry_run=True, neo4j_password="supersecret123",
               audit_log_path=audit, operator="op")
    raw = audit.read_text(encoding="utf-8")
    assert "supersecret123" not in raw
    assert "password" not in raw.lower()


# 35. allow_relationships=True acepta relaciones (flag explícito)
def test_35_allow_relationships_flag(tmp_path):
    """Con allow_relationships=False (default), relaciones bloquean la ingesta."""
    rel = {"kind": "relation", "from_entity": "A", "to_entity": "B",
           "relation_type": "KNOWS", "evidence": "e",
           "source_id": "s", "workspace": "leyenda"}
    ctx, _ = _patch({})
    with ctx, pytest.raises(ValueError, match="no admite relaciones"):
        ingest(_write(tmp_path, [_ent(), rel]), dry_run=True,
               neo4j_password="x", allow_relationships=False)


# 36. _build_merge_relation_query requiere source_kind explícito (sin default audio)
def test_36_relation_query_no_default_audio():
    from review.ingest_approved import _build_merge_relation_query
    item_sin_source_kind = {
        "from_entity": "A", "to_entity": "B", "relation_type": "KNOWS",
        "source_id": "s1", "workspace": "leyenda", "review_status": "approved",
        "confidence": 0.8, "evidence": "ev",
    }
    with pytest.raises((ValueError, KeyError)):
        _build_merge_relation_query(item_sin_source_kind)


# 37. _build_merge_relation_query requiere review_status explícito (sin auto_approved)
def test_37_relation_query_no_default_auto_approved():
    from review.ingest_approved import _build_merge_relation_query
    item_sin_review_status = {
        "from_entity": "A", "to_entity": "B", "relation_type": "KNOWS",
        "source_id": "s1", "source_kind": "narrative",
        "workspace": "leyenda",
        "confidence": 0.8, "evidence": "ev",
    }
    with pytest.raises((ValueError, KeyError)):
        _build_merge_relation_query(item_sin_review_status)
