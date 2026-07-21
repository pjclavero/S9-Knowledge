# -*- coding: utf-8 -*-
"""Tests de la limpieza controlada y reversible del grafo (review/graph_cleanup).

Sin Neo4j real: una sesion FALSA registra las queries y devuelve datos canonizados.
Los tests matan al mutante: comprueban la clasificacion (auto vs revision), el
fail-closed de la doble llave + backup, que dry-run no escribe, y la reversibilidad.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review import graph_cleanup as gc  # noqa: E402


# --- Sesion falsa ----------------------------------------------------------
class _FakeRecord(dict):
    def single(self):  # compat: algunos codepaths llaman .single() sobre el result
        return self


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return _FakeRecord(self._rows[0]) if self._rows else None

    def data(self):
        return list(self._rows)


class FakeSession:
    """Registra queries ejecutadas y responde por coincidencia de subcadena."""

    def __init__(self, responses):
        # responses: lista de (substring, rows). Primera coincidencia gana.
        self._responses = responses
        self.writes = []       # queries que escriben (SET/DELETE/CREATE/REMOVE)
        self.all_queries = []

    def run(self, query, params=None):
        self.all_queries.append((query, params or {}))
        upper = query.upper()
        if any(kw in upper for kw in ("SET ", "DELETE ", "CREATE ", "REMOVE ")):
            self.writes.append((query, params or {}))
        for sub, rows in self._responses:
            if sub in query:
                return _FakeResult(rows)
        return _FakeResult([])


def _base_responses(*, missing=0, totals=(199, 140), bad_rels=None, dup_names=None):
    bad_rels = bad_rels or []
    dup_names = dup_names if dup_names is not None else []
    return [
        ("MATCH (n) RETURN count(n) AS c", [{"c": totals[0]}]),
        ("MATCH ()-[r]->() RETURN count(r) AS c", [{"c": totals[1]}]),
        ("n.source_id IS NULL OR n.source_id = '') \n        RETURN count(n) AS c", [{"c": missing}]),
        ("(n.source_id IS NULL OR n.source_id = '') RETURN count(n) AS c", [{"c": missing}]),
        ("WHERE NOT type(r) IN $allowed", bad_rels),
        ("RETURN n.canonical_name AS name LIMIT 5000", [{"name": n} for n in dup_names]),
        # forward de provenance
        ("SET n.source_id = $sid", [{"updated": missing}]),
        # rollback de provenance
        ("REMOVE n.source_id, n.source_kind, n._mig", [{"reverted": missing}]),
    ]


# --- Planificacion / clasificacion -----------------------------------------
def test_missing_provenance_is_auto_safe():
    s = FakeSession(_base_responses(missing=87))
    plan = gc.plan_cleanup(s)
    autos = plan.auto_items
    assert len(autos) == 1
    it = autos[0]
    assert it.finding == "missing_provenance"
    assert it.klass == gc.CLASS_AUTO_SAFE
    assert it.count == 87
    assert it.to_dict()["auto_applicable"] is True
    # plan_cleanup NO debe escribir nada
    assert s.writes == []


def test_no_missing_provenance_yields_no_auto_item():
    s = FakeSession(_base_responses(missing=0))
    plan = gc.plan_cleanup(s)
    assert plan.auto_items == []


def test_bad_relation_without_mapping_is_review_required():
    s = FakeSession(_base_responses(bad_rels=[{"t": "ZZZ_NOT_A_TYPE", "c": 3}]))
    plan = gc.plan_cleanup(s)
    review = [it for it in plan.review_items if it.finding == "bad_relation"]
    assert len(review) == 1
    assert review[0].klass == gc.CLASS_REVIEW_REQUIRED
    assert review[0].count == 3


def test_valid_relation_is_never_flagged_bad():
    # Un tipo ya valido nunca deberia venir del auditor; si viniera, se ignora
    # (no se crea un remap de ALLIED_WITH -> ALLIED_WITH).
    s = FakeSession(_base_responses(bad_rels=[{"t": "ALLIED_WITH", "c": 1}]))
    plan = gc.plan_cleanup(s)
    items = [it for it in plan.items if it.finding == "bad_relation"]
    assert items == []


def test_duplicates_are_review_required():
    s = FakeSession(_base_responses(dup_names=["Tamori Family", "tamori family", "Otro"]))
    plan = gc.plan_cleanup(s)
    dups = [it for it in plan.items if it.finding == "duplicate_candidate"]
    assert len(dups) == 1
    assert dups[0].klass == gc.CLASS_REVIEW_REQUIRED
    assert dups[0].count == 1  # un grupo duplicado


# --- Fail-closed de apply --------------------------------------------------
def test_apply_dry_run_writes_nothing():
    s = FakeSession(_base_responses(missing=87))
    plan = gc.plan_cleanup(s)
    res = gc.apply_plan(s, plan, apply=False, backup_ref="backup-xyz", env={gc.GRAPH_MIGRATION_ENV: "true"})
    assert res.applied is False
    assert s.writes == []  # dry-run no escribe


def test_apply_blocked_without_env_double_key():
    s = FakeSession(_base_responses(missing=87))
    plan = gc.plan_cleanup(s)
    with pytest.raises(gc.GraphCleanupError):
        gc.apply_plan(s, plan, apply=True, backup_ref="backup-xyz", env={})  # sin env
    assert s.writes == []


def test_apply_blocked_without_backup_ref():
    s = FakeSession(_base_responses(missing=87))
    plan = gc.plan_cleanup(s)
    with pytest.raises(gc.GraphCleanupError):
        gc.apply_plan(s, plan, apply=True, backup_ref="", env={gc.GRAPH_MIGRATION_ENV: "true"})
    assert s.writes == []


def test_apply_env_must_be_exactly_true():
    s = FakeSession(_base_responses(missing=87))
    plan = gc.plan_cleanup(s)
    for bad in ("1", "yes", "", "false", "tru"):
        s2 = FakeSession(_base_responses(missing=87))
        p2 = gc.plan_cleanup(s2)
        with pytest.raises(gc.GraphCleanupError):
            gc.apply_plan(s2, p2, apply=True, backup_ref="b", env={gc.GRAPH_MIGRATION_ENV: bad})
        assert s2.writes == []


def test_apply_writes_only_auto_safe_and_is_reversible():
    # Con doble llave + backup, solo aplica AUTO_SAFE (provenance), y el rollback
    # revierte exactamente lo escrito.
    s = FakeSession(_base_responses(missing=87, bad_rels=[{"t": "ZZZ", "c": 2}]))
    plan = gc.plan_cleanup(s)
    res = gc.apply_plan(s, plan, apply=True, backup_ref="backup-2026", env={gc.GRAPH_MIGRATION_ENV: "true"})
    assert res.applied is True
    assert len(res.manifest["results"]) == 1  # solo el AUTO_SAFE, no el bad_relation
    assert res.manifest["results"][0]["finding"] == "missing_provenance"
    assert res.manifest["results"][0]["updated"] == 87
    # se escribio el forward (SET ... _mig)
    assert any("SET n.source_id" in q for q, _ in s.writes)
    # NO se escribio ningun DELETE de relacion (eso es revision)
    assert not any("DELETE r" in q for q, _ in s.writes)

    # rollback
    rb = gc.rollback_migration(s, res.manifest, apply=True, env={gc.GRAPH_MIGRATION_ENV: "true"})
    assert rb["applied"] is True
    assert rb["reverted"][0]["reverted"] == 87
    assert any("REMOVE n.source_id" in q for q, _ in s.writes)


def test_rollback_dry_run_writes_nothing():
    s = FakeSession(_base_responses(missing=5))
    plan = gc.plan_cleanup(s)
    res = gc.apply_plan(s, plan, apply=True, backup_ref="b", env={gc.GRAPH_MIGRATION_ENV: "true"})
    writes_before = len(s.writes)
    rb = gc.rollback_migration(s, res.manifest, apply=False, env={gc.GRAPH_MIGRATION_ENV: "true"})
    assert rb["applied"] is False
    assert len(s.writes) == writes_before  # dry-run rollback no escribe


def test_plan_report_md_mentions_dry_run_and_classes():
    s = FakeSession(_base_responses(missing=3, bad_rels=[{"t": "ZZZ", "c": 1}]))
    plan = gc.plan_cleanup(s)
    md = plan.to_report_md()
    assert "DRY-RUN" in md
    assert "AUTO_SAFE" in md
    assert "revision humana" in md.lower()
