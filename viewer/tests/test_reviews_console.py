"""Tests del panel de revisión v1 (Equipo B) — consola de revisión.

Cubren la capa de servicio (contratos v1, hashes, control optimista, almacén de
laboratorio) y las rutas FastAPI. NUNCA tocan Neo4j ni producción: usan las
fixtures ANONIMIZADAS del panel y directorios temporales.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import review_console as rc


# ---------------------------------------------------------------------------
# Servicio: fixtures y contratos
# ---------------------------------------------------------------------------
def test_fixtures_are_contract_valid():
    summaries = rc.list_source_summaries()
    assert {s["source_id"] for s in summaries} == {"src_demo_01", "src_demo_02"}
    for s in summaries:
        rc.validate_document(s)  # no lanza
    cands = rc.list_candidates("src_demo_01")
    assert {c["candidate_id"] for c in cands} == {"cand_a1", "cand_a2", "cand_a3"}
    for c in cands:
        rc.validate_document(c)


def test_candidate_hash_is_deterministic_and_content_sensitive():
    c = rc.get_candidate("src_demo_01", "cand_a1")
    h1 = rc.candidate_hash(c)
    h2 = rc.candidate_hash(dict(c))
    assert h1 == h2
    mutated = dict(c)
    mutated["canonical_name"] = c["canonical_name"] + " (edit)"
    assert rc.candidate_hash(mutated) != h1
    assert h1["algorithm"] == "sha256" and len(h1["value"]) == 64


def test_plan_preview_readonly_summary():
    p = rc.plan_preview("src_demo_01")
    assert p["would_create"] == 1 and p["would_link_existing"] == 1
    assert p["authorization_granted"] is False
    assert rc.plan_preview("src_demo_02")["conflicts"] == 1


# ---------------------------------------------------------------------------
# Servicio: construcción de documentos producidos por el panel
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", sorted(rc.VALID_ACTIONS))
def test_build_decision_valid_for_every_action(action):
    c = rc.get_candidate("src_demo_01", "cand_a2")  # tiene existing_matches
    ch = rc.candidate_hash(c)
    dec = rc.build_decision(c, action, "tester", ch)
    rc.validate_document(dec)  # cumple review-decision v1
    assert dec["action"] == action
    assert dec["decision_hash"]["algorithm"] == "sha256"


def test_shadow_reviewer_only_defers():
    c = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(c)
    dec = rc.build_decision(c, "DEFER", "shadow", ch, reviewer_type="EXTERNAL_AI_SHADOW")
    rc.validate_document(dec)
    # APPROVE con EXTERNAL_AI_SHADOW viola el contrato
    with pytest.raises(Exception):
        rc.validate_document(rc.build_decision(
            c, "DEFER", "shadow", ch, reviewer_type="EXTERNAL_AI_SHADOW") | {"action": "APPROVE"})


# ---------------------------------------------------------------------------
# Servicio: control optimista + almacén de laboratorio
# ---------------------------------------------------------------------------
def test_submit_decision_persists_decision_and_audit(tmp_path):
    c = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(c)
    res = rc.submit_decision("src_demo_01", "cand_a1", "APPROVE", "tester", ch, store=tmp_path)
    assert res.ok and not res.stale
    decisions = rc.read_decisions(tmp_path)
    events = rc.read_audit_events(tmp_path)
    assert len(decisions) == 1 and decisions[0]["action"] == "APPROVE"
    assert events[0]["event_type"] == "DECISION_RECORDED"
    rc.validate_document(decisions[0])
    rc.validate_document(events[0])


def test_submit_decision_stale_is_rejected_and_not_written(tmp_path):
    stale = {"algorithm": "sha256", "value": "0" * 64}
    res = rc.submit_decision("src_demo_01", "cand_a1", "APPROVE", "tester", stale, store=tmp_path)
    assert res.stale and not res.ok
    assert rc.read_decisions(tmp_path) == []  # NO se escribió la decisión
    events = rc.read_audit_events(tmp_path)
    assert len(events) == 1 and events[0]["event_type"] == "STALE_REVIEW_REJECTED"
    rc.validate_document(events[0])


def test_submit_decision_unknown_candidate_raises(tmp_path):
    ch = {"algorithm": "sha256", "value": "0" * 64}
    with pytest.raises(rc.ReviewConsoleError):
        rc.submit_decision("src_demo_01", "no_existe", "APPROVE", "t", ch, store=tmp_path)


def test_lab_store_never_references_neo4j(tmp_path):
    c = rc.get_candidate("src_demo_01", "cand_a1")
    rc.submit_decision("src_demo_01", "cand_a1", "APPROVE", "t", rc.candidate_hash(c), store=tmp_path)
    blob = (tmp_path / "decisions.jsonl").read_text().lower()
    assert "neo4j" not in blob and "bolt://" not in blob


# ---------------------------------------------------------------------------
# Rutas FastAPI (auth desactivada por defecto en tests)
# ---------------------------------------------------------------------------
def _client():
    from app.main import app
    return TestClient(app)


def test_inbox_lists_sources():
    r = _client().get("/review-console")
    assert r.status_code == 200
    assert "src_demo_01" in r.text and "src_demo_02" in r.text
    assert "No se escribe en Neo4j" in r.text


def test_source_detail_shows_candidates_and_plan_preview():
    r = _client().get("/review-console/source/src_demo_01")
    assert r.status_code == 200
    assert "Personaje Alfa" in r.text
    assert "Preview del ingest-plan" in r.text
    assert "WOULD_CREATE" in r.text
    assert "expected_candidate_hash" in r.text  # control optimista en el form


def test_source_detail_404_for_missing():
    assert _client().get("/review-console/source/nope").status_code == 404


def test_post_decide_happy_path_writes_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_REVIEW_LAB_DIR", str(tmp_path))
    c = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(c)["value"]
    r = _client().post(
        "/review-console/source/src_demo_01/decide",
        data={"candidate_id": "cand_a1", "action": "APPROVE",
              "expected_candidate_hash": ch},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/review-console/source/src_demo_01"
    assert len(rc.read_decisions(tmp_path)) == 1


def test_post_decide_stale_redirects_with_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_REVIEW_LAB_DIR", str(tmp_path))
    r = _client().post(
        "/review-console/source/src_demo_01/decide",
        data={"candidate_id": "cand_a1", "action": "APPROVE",
              "expected_candidate_hash": "0" * 64},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith("?stale=1")
    assert rc.read_decisions(tmp_path) == []
    # la página de detalle muestra el aviso de obsolescencia
    detail = _client().get("/review-console/source/src_demo_01?stale=1")
    assert "Revisión obsoleta" in detail.text


def test_post_decide_invalid_action_400(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_REVIEW_LAB_DIR", str(tmp_path))
    r = _client().post(
        "/review-console/source/src_demo_01/decide",
        data={"candidate_id": "cand_a1", "action": "PURGE",
              "expected_candidate_hash": "0" * 64},
        follow_redirects=False,
    )
    assert r.status_code == 400
