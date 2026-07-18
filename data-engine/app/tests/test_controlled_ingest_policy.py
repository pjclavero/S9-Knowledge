"""Tests de la politica de ingesta controlada v1 (motor).

Todo se valida contra el validador UNICO de contratos
(contracts/review-ingest/v1/validator.py). Sin produccion: SQLite/Neo4j no se
tocan; la fixture ``source_narrative_01`` es sintetica y anonimizada.

Resultado obligatorio (source_narrative_01): DRY_RUN produce exactamente
4 WOULD_CREATE, 0 conflictos, 0 ambiguos, 4 diferidos, 0 relaciones, 0 escrituras.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.controlled_ingest import (  # noqa: E402
    ApplyRequest,
    EngineCandidate,
    PlanItem,
    SourceContext,
    apply_decision,
    build_candidate,
    build_plan,
    build_summary,
    candidate_hash,
    dry_run,
    evaluate_apply,
    hash_block,
    plan_hash,
    validate_document,
)
from review.controlled_ingest.policy import ENV_ALLOW_REAL_INGEST  # noqa: E402

_FIXTURE = _TESTS_DIR / "fixtures" / "source_narrative_01.json"


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_all():
    """Ejecuta el slice completo sobre la fixture y devuelve los artefactos."""
    fx = _load_fixture()
    ctx = SourceContext(
        workspace=fx["workspace"],
        source_id=fx["source_id"],
        source_hash_value=fx["source_hash_value"],
        review_generation=fx["review_generation"],
    )

    candidates: list[dict] = []
    actions: dict[str, str] = {}
    for raw in fx["candidates"]:
        ec = EngineCandidate(
            candidate_id=raw["candidate_id"],
            segment_id=raw["segment_id"],
            kind=raw["kind"],
            name=raw["name"],
            entity_type=raw["entity_type"],
            confidence=raw["confidence"],
            evidence=raw["evidence"],
        )
        doc = build_candidate(ctx, ec)
        validate_document(doc)  # cada candidato cumple el contrato
        candidates.append(doc)
        actions[raw["candidate_id"]] = raw["decision_action"]

    # Consumo de decisiones con control optimista.
    final_status: dict[str, str] = {}
    items: list[PlanItem] = []
    for cand in candidates:
        cid = cand["candidate_id"]
        action = actions[cid]
        decision = _make_decision(ctx, cand, action)
        validate_document(decision)
        outcome = apply_decision(cand, decision)
        assert outcome.outcome == "APPLIED", outcome.reason
        final_status[cid] = outcome.new_status
        items.append(PlanItem(candidate_doc=cand, final_status=outcome.new_status))

    summary = build_summary(
        ctx,
        source_kind=fx["source_kind"],
        source_document=fx["source_document"],
        segments_total=fx["segments_total"],
        segments_reviewed=fx["segments_reviewed"],
        statuses=list(final_status.values()),
    )
    validate_document(summary)

    review_hash = hash_block(summary)
    plan = build_plan(
        ctx,
        review_document_id=summary["document_id"],
        review_hash=review_hash,
        items=items,
    )
    validate_document(plan)

    result = dry_run(ctx, plan, graph_baseline={"nodes": 200, "relationships": 140})
    validate_document(result)

    return ctx, candidates, summary, plan, result, review_hash


def _make_decision(ctx: SourceContext, cand: dict, action: str) -> dict:
    doc = {
        "schema_version": "1.0.0",
        "document_type": "review-decision",
        "document_id": f"review-decision_{cand['candidate_id']}",
        "created_at": _now(),
        "workspace": ctx.workspace,
        "source_id": ctx.source_id,
        "source_hash": ctx.source_hash(),
        "review_generation": ctx.review_generation,
        "producer": ctx.producer(),
        "provenance": ctx.provenance(),
        "decision_id": f"dec_{cand['candidate_id']}",
        "candidate_id": cand["candidate_id"],
        "action": action,
        "reviewer_type": "HUMAN",
        "reviewer_id": "operator_lab",
        "decided_at": _now(),
        "reason_code": "LAB_TEST_DECISION",
        "expected_candidate_hash": candidate_hash(cand),
        "decision_hash": hash_block({"candidate_id": cand["candidate_id"], "action": action}),
    }
    return doc


# ── Resultado obligatorio: source_narrative_01 ────────────────────────────────

def test_source_narrative_01_dry_run_exact_counts():
    _, candidates, summary, plan, result, _ = _build_all()

    assert len(candidates) == 8

    # Plan determinista.
    assert plan["relations_enabled"] is False
    assert plan["summary"]["would_create"] == 4
    assert plan["summary"]["conflicts"] == 0
    assert plan["summary"]["deferred"] == 4
    assert plan["summary"]["relations"] == 0
    assert len(plan["operations"]) == 4
    assert len(plan["deferred_items"]) == 4
    assert all(op["operation_type"] == "CREATE_ENTITY" for op in plan["operations"])

    # DRY_RUN: 4 WOULD_CREATE, 0 conflictos, 0 ambiguos, 0 escrituras.
    sm = result["summary"]
    assert result["mode"] == "DRY_RUN"
    assert result["status"] == "SUCCEEDED"
    assert sm["would_create"] == 4
    assert sm["created"] == 0
    assert sm["conflict"] == 0  # 0 conflictos
    assert sm["failed"] == 0
    assert sm["rolled_back"] == 0
    would_create_ops = [o for o in result["operations"] if o["result"] == "WOULD_CREATE"]
    ambiguous_ops = [o for o in result["operations"] if o["result"] == "CONFLICT"]
    assert len(would_create_ops) == 4
    assert len(ambiguous_ops) == 0  # 0 ambiguos
    # 0 escrituras: el grafo no cambia.
    assert result["neo4j_before"] == result["neo4j_after"]


def test_plan_is_deterministic():
    _, _, _, plan_a, _, _ = _build_all()
    _, _, _, plan_b, _, _ = _build_all()
    # operation_id / idempotency_key estables e independientes del reloj.
    ops_a = [(o["operation_id"], o["idempotency_key"], o["candidate_id"]) for o in plan_a["operations"]]
    ops_b = [(o["operation_id"], o["idempotency_key"], o["candidate_id"]) for o in plan_b["operations"]]
    assert ops_a == ops_b
    idem = [o["idempotency_key"] for o in plan_a["operations"]]
    assert len(idem) == len(set(idem))  # idempotency_key unica
    op_ids = [o["operation_id"] for o in plan_a["operations"]]
    assert len(op_ids) == len(set(op_ids))  # operation_id unico


def test_summary_counts_coherent():
    _, _, summary, _, _, _ = _build_all()
    assert summary["candidates_total"] == 8
    assert summary["approved"] == 4
    assert summary["deferred"] == 4
    assert summary["pending"] == 0
    assert summary["conflicts"] == 0
    assert summary["ready_to_plan"] is True


# ── Control optimista: hash obsoleto -> CONFLICT (STALE) ──────────────────────

def test_optimistic_control_stale_hash_conflict():
    _, candidates, _, _, _, _ = _build_all()
    fx = _load_fixture()
    ctx = SourceContext(
        workspace=fx["workspace"], source_id=fx["source_id"],
        source_hash_value=fx["source_hash_value"], review_generation=fx["review_generation"],
    )
    cand = candidates[0]
    decision = _make_decision(ctx, cand, "APPROVE")
    # El candidato cambia despues de emitir la decision: la decision queda STALE.
    mutated = dict(cand)
    mutated["display_name"] = cand["display_name"] + " (editado)"
    outcome = apply_decision(mutated, decision)
    assert outcome.outcome == "CONFLICT"
    assert outcome.new_status is None


# ── AUTO_APPROVABLE es solo recomendacion ─────────────────────────────────────

def test_engine_never_proposes_approved():
    _, candidates, _, _, _, _ = _build_all()
    # El motor jamas propone APPROVED por su cuenta; requiere revision humana.
    for cand in candidates:
        assert cand["proposed_status"] != "APPROVED"
        assert cand["requires_review"] is True


# ── Gate de APPLY ─────────────────────────────────────────────────────────────

def _authorized_plan(ctx, plan, operator_id="operator_lab"):
    """Copia del plan con autorizacion concedida (para probar el gate)."""
    p = json.loads(json.dumps(plan))
    p["authorization"] = {
        "required": True,
        "granted": True,
        "operator_id": operator_id,
        "authorized_at": _now(),
        "authorization_hash": hash_block({"operator": operator_id}),
    }
    return p


def test_apply_blocked_when_env_missing():
    ctx, _, _, plan, _, review_hash = _build_all()
    p = _authorized_plan(ctx, plan)
    validate_document(p)
    req = ApplyRequest(
        mode="APPLY", plan_doc=p, expected_plan_hash=plan_hash(p),
        expected_review_hash=review_hash, operator_id="operator_lab",
        production_env=True, cli_confirmed=True,
        env={},  # falta S9K_ALLOW_REAL_INGEST
    )
    gate = evaluate_apply(req)
    assert gate.allowed is False
    assert any(ENV_ALLOW_REAL_INGEST in r for r in gate.blocked_reasons)


def test_apply_blocked_when_not_authorized():
    ctx, _, _, plan, _, review_hash = _build_all()
    # plan sin authorization.granted=true
    req = ApplyRequest(
        mode="APPLY", plan_doc=plan, expected_plan_hash=plan_hash(plan),
        expected_review_hash=review_hash, operator_id="operator_lab",
        production_env=True, cli_confirmed=True,
        env={ENV_ALLOW_REAL_INGEST: "true"},
    )
    gate = evaluate_apply(req)
    assert gate.allowed is False
    assert any("granted" in r for r in gate.blocked_reasons)


def test_apply_blocked_when_cli_not_confirmed():
    ctx, _, _, plan, _, review_hash = _build_all()
    p = _authorized_plan(ctx, plan)
    req = ApplyRequest(
        mode="APPLY", plan_doc=p, expected_plan_hash=plan_hash(p),
        expected_review_hash=review_hash, operator_id="operator_lab",
        production_env=True, cli_confirmed=False,  # falta confirmacion CLI
        env={ENV_ALLOW_REAL_INGEST: "true"},
    )
    gate = evaluate_apply(req)
    assert gate.allowed is False
    assert any("CLI" in r for r in gate.blocked_reasons)


def test_apply_blocked_when_plan_hash_tampered():
    ctx, _, _, plan, _, review_hash = _build_all()
    p = _authorized_plan(ctx, plan)
    req = ApplyRequest(
        mode="APPLY", plan_doc=p,
        expected_plan_hash=hash_block({"tampered": True}),  # hash que no coincide
        expected_review_hash=review_hash, operator_id="operator_lab",
        production_env=True, cli_confirmed=True,
        env={ENV_ALLOW_REAL_INGEST: "true"},
    )
    gate = evaluate_apply(req)
    assert gate.allowed is False
    assert any("hash de plan" in r for r in gate.blocked_reasons)


def test_apply_allowed_only_when_all_conditions_met():
    ctx, _, _, plan, _, review_hash = _build_all()
    p = _authorized_plan(ctx, plan)
    req = ApplyRequest(
        mode="APPLY", plan_doc=p, expected_plan_hash=plan_hash(p),
        expected_review_hash=review_hash, operator_id="operator_lab",
        production_env=True, cli_confirmed=True,
        env={ENV_ALLOW_REAL_INGEST: "true"},
    )
    gate = evaluate_apply(req)
    assert gate.allowed is True, gate.blocked_reasons
    assert gate.blocked_reasons == []
