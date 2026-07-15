# -*- coding: utf-8 -*-
"""Prioridad 2.1 — política full_human_review y procedencia de revisión (§3-§6).

Demuestra que bajo full_human_review NINGÚN candidato se autoaprueba y que
ingest-approved exige procedencia de revisión humana. Sin Ollama ni Neo4j.
"""
from __future__ import annotations
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from review.auto_decider import decide_one, _review_policy
from review.models import Candidate, ValidationResult, ResolutionResult
from review import ingest_approved
from cli import review_manual


def _cand(**k):
    d = dict(candidate_id="e1", source_id="src", segment_id="g", workspace="w",
             kind="entity", name="Kakita Asuka", entity_type="Character", confidence=0.95,
             evidence="Kakita Asuka llega", timestamp_start="00:00:00",
             timestamp_end="00:01:00", source_kind="audio")
    d.update(k)
    return Candidate(**d)


def _rel(**k):
    return _cand(candidate_id="r1", kind="relation", name=None, entity_type=None,
                 from_entity="Kakita Asuka", to_entity="Clan Grulla",
                 relation_type="MEMBER_OF", **k)


def _vr(cid="e1"):
    return ValidationResult(candidate_id=cid, valid="valid")


def _rr(cid="e1", action="create_new"):
    return ResolutionResult(candidate_id=cid, action=action, reason="", neo4j_available=True)


def _full(monkeypatch):
    monkeypatch.setenv("S9K_REVIEW_POLICY", "full_human_review")


# 1-5: entidades de cualquier procedencia → needs_review
def test_1_high_confidence_entity_review(monkeypatch):
    _full(monkeypatch)
    d = decide_one(_cand(confidence=0.99), _vr(), _rr())
    assert d.decision == "needs_review" and "full_human_review_policy" in d.decision_reason

def test_2_existing_entity_review(monkeypatch):
    _full(monkeypatch)
    d = decide_one(_cand(), _vr(), _rr(action="use_existing"))
    assert d.decision == "needs_review"

def test_3_heuristic_entity_review(monkeypatch):
    _full(monkeypatch)
    d = decide_one(_cand(origin="local", glossary_match=True), _vr(), _rr())
    assert d.decision == "needs_review"

def test_4_llm_entity_review(monkeypatch):
    _full(monkeypatch)
    d = decide_one(_cand(confidence=0.9), _vr(), _rr())
    assert d.decision == "needs_review"

def test_5_hybrid_entity_review(monkeypatch):
    _full(monkeypatch)
    d = decide_one(_cand(name="Doji Satsume"), _vr(), _rr())
    assert d.decision == "needs_review"

# 6-7: relaciones
def test_6_valid_relation_review(monkeypatch):
    _full(monkeypatch)
    d = decide_one(_rel(confidence=0.9), _vr("r1"), _rr("r1"))
    assert d.decision == "needs_review"

def test_7_invalid_relation_not_autoapproved(monkeypatch):
    _full(monkeypatch)
    d = decide_one(_rel(confidence=0.2, evidence=""), _vr("r1"), _rr("r1"))
    assert d.decision != "auto_approve"

# 8: payload automático vacío (ninguna decisión auto_approve bajo full)
def test_8_automatic_payload_empty(monkeypatch):
    _full(monkeypatch)
    cands = [_cand(confidence=0.99), _cand(candidate_id="e2", name="Doji Satsume"),
             _rel(confidence=0.9)]
    decisions = [decide_one(c, _vr(c.candidate_id), _rr(c.candidate_id)) for c in cands]
    auto = [d for d in decisions if d.decision == "auto_approve"]
    assert auto == []


# ── Fixtures para CLI + ingest ────────────────────────────────────────────────
def _setup_repo(tmp_path, review_status="pending"):
    rdir = tmp_path / "output" / "reviews" / "leyenda" / "src"
    rdir.mkdir(parents=True)
    decisions = [{
        "candidate_id": "e1", "decision": "needs_review",
        "candidate": {"candidate_id": "e1", "kind": "entity", "name": "Kakita Asuka",
                      "entity_type": "Character", "evidence": "Kakita Asuka llega",
                      "source_id": "src", "confidence": 0.9, "workspace": "leyenda"},
    }]
    (rdir / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    return rdir


# 9: candidato aprobado manualmente entra en el payload
def test_9_manual_approve_enters_payload(tmp_path):
    _setup_repo(tmp_path)
    res = review_manual.record_decision(tmp_path, "leyenda", "src", "e1",
                                        "approve", "ana", "correcta")
    assert res["approved_in_payload"] == 1
    payload = json.loads((tmp_path / "output/reviews/leyenda/src/approved_payload.reviewed.json").read_text())
    it = payload["approved"][0]
    assert it["review_status"] == "approved"
    assert it["reviewed_by"] == "manual-cli:ana" and it["reviewed_at"]
    assert it["review_action"] == "approve"


# 10-11: ingest rechaza sin reviewed_by / reviewed_at
def _payload(tmp_path, **overrides):
    item = {"kind": "entity", "name": "Kakita Asuka", "entity_type": "Character",
            "evidence": "ev", "source_id": "src", "source_kind": "markdown",
            "source_document": "src", "workspace": "leyenda", "knowledge_layer": "narrative",
            "visibility": "player", "confidence": 0.9, "review_status": "approved",
            "reviewed_by": "manual-cli:ana", "reviewed_at": "2026-07-14T00:00:00+00:00",
            "review_action": "approve"}
    item.update(overrides)
    p = tmp_path / "approved_payload.json"
    p.write_text(json.dumps({"metadata": {"workspace": "leyenda", "source_id": "src",
                 "schema_version": "1.0", "origin": "local"}, "approved": [item]}), encoding="utf-8")
    return p

def test_10_missing_reviewed_by_rejected(tmp_path, monkeypatch):
    _full(monkeypatch)
    p = _payload(tmp_path, reviewed_by="")
    with pytest.raises(ValueError):
        ingest_approved.ingest(p, dry_run=True)

def test_11_missing_reviewed_at_rejected(tmp_path, monkeypatch):
    _full(monkeypatch)
    p = _payload(tmp_path, reviewed_at="")
    with pytest.raises(ValueError):
        ingest_approved.ingest(p, dry_run=True)

# 12: dry-run acepta payload íntegramente revisado
def test_12_dryrun_accepts_reviewed_payload(tmp_path, monkeypatch):
    _full(monkeypatch)
    p = _payload(tmp_path)
    res = ingest_approved.ingest(p, dry_run=True)
    assert res.get("dry_run") is True

# 13: rechaza payload con autoaprobados bajo política
def test_13_rejects_autoapproved_under_policy(tmp_path, monkeypatch):
    _full(monkeypatch)
    p = _payload(tmp_path, review_status="auto_approved", reviewed_by="", reviewed_at="", review_action="")
    with pytest.raises(ValueError):
        ingest_approved.ingest(p, dry_run=True)

# 14: modo normal conserva comportamiento
def test_14_normal_mode_autoapproves_entity(monkeypatch):
    monkeypatch.setenv("S9K_REVIEW_POLICY", "normal")
    d = decide_one(_cand(name="Doji Satsume", confidence=0.95), _vr(), _rr())
    assert d.decision == "auto_approve"

# 15: política desconocida → error de configuración
def test_15_unknown_policy_errors(monkeypatch):
    monkeypatch.setenv("S9K_REVIEW_POLICY", "loose")
    with pytest.raises(ValueError):
        _review_policy()
