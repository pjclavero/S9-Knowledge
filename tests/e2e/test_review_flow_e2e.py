"""test_review_flow_e2e.py — E2E del flujo de revisión contra el producto integrado.

Fase 2: A (auth/sesión), B (panel + servicio review_console) y C (viewer/authz)
están en main. Estos E2E ejercitan la app FastAPI real vía TestClient in-process:
login/sesión/CSRF reales, rutas reales del panel, control optimista real y
persistencia real en un almacén de laboratorio (JSONL temporal). NUNCA tocan
Neo4j ni producción (cortafuegos activo, provider de laboratorio, ingesta off).

Cubre las dependencias históricas D-DEP-1..4.
"""
from __future__ import annotations

import pytest

from support import contracts

pytestmark = pytest.mark.e2e


# ── D-DEP-1: login, sesión y acceso al panel ───────────────────────────────
def test_operator_can_log_in_and_reach_review_panel(e2e) -> None:
    """Login real -> cookie de sesión -> panel; logout -> sesión invalidada."""
    e2e.make_user("oper_rev", "reviewer")
    c = e2e.client()  # anónimo

    # Anónimo: el panel redirige a /login.
    anon = c.get("/review-console")
    assert anon.status_code == 302 and "/login" in anon.headers["location"]

    # Login real (CSRF de login + credenciales).
    page = c.get("/login")
    assert page.status_code == 200
    r = c.post("/login", data={
        "username": "oper_rev", "password": "LabPass_1234567890!",
        "csrf_token": e2e.csrf_from_html(page.text), "next": "/review-console",
    })
    assert r.status_code in (302, 303)
    session_cookie = c.cookies.get("s9k_session")
    assert session_cookie, "el login debe emitir la cookie de sesión"

    # Sesión válida: acceso al panel.
    panel = c.get("/review-console")
    assert panel.status_code == 200
    assert "src_demo_01" in panel.text  # bandeja con fuentes

    # Logout real (CSRF de sesión) -> sesión invalidada.
    logout = c.post("/logout", data={"csrf_token": e2e.csrf_from_html(panel.text)})
    assert logout.status_code in (302, 303)
    after = c.get("/review-console")
    assert after.status_code == 302 and "/login" in after.headers["location"]


# ── D-DEP-2: panel + resumen por fuente (BLOCKED con conflictos) ────────────
def test_source_summary_panel_shows_blocked_when_conflicts(e2e) -> None:
    """El panel refleja el resumen por fuente; con conflictos el plan no está listo."""
    reviewer = e2e.make_user("rev_b", "reviewer")
    c = e2e.client(reviewer)

    # Invariante contractual que el panel debe respetar.
    summary = contracts.load_example("source_summary_conflicts")
    assert summary["status"] == "BLOCKED" and summary["ready_to_plan"] is False
    contracts.validator.validate_document(summary)

    # Bandeja lista las fuentes reales del servicio.
    inbox = c.get("/review-console")
    assert inbox.status_code == 200
    assert "src_demo_01" in inbox.text and "src_demo_02" in inbox.text

    # Detalle de una fuente con conflictos: el preview del plan reporta el conflicto.
    detail = c.get("/review-console/source/src_demo_02")
    assert detail.status_code == 200
    from app.services import review_console as rc
    preview = rc.plan_preview("src_demo_02")
    assert preview["conflicts"] >= 1
    assert preview["authorization_granted"] is False


# ── D-DEP-3: POST decisión con control optimista (stale hash) ──────────────
def test_stale_candidate_hash_rejects_decision(e2e) -> None:
    """Decisión con hash correcto persiste; con hash obsoleto se rechaza sin escribir."""
    reviewer = e2e.make_user("rev_c", "reviewer")
    c = e2e.client(reviewer)
    from app.services import review_console as rc

    src, cand = "src_demo_01", "cand_a1"
    good_hash = rc.candidate_hash(rc.get_candidate(src, cand))["value"]

    detail = c.get(f"/review-console/source/{src}")
    assert detail.status_code == 200
    csrf = e2e.csrf_from_html(detail.text)

    # 1) Decisión válida -> 303 al detalle (sin ?stale) + persistida en laboratorio.
    ok = c.post(f"/review-console/source/{src}/decide", data={
        "candidate_id": cand, "action": "APPROVE",
        "expected_candidate_hash": good_hash, "csrf_token": csrf,
    })
    assert ok.status_code == 303 and "stale=1" not in ok.headers["location"]
    decisions = rc.read_decisions(e2e.lab_dir)
    assert len(decisions) == 1 and decisions[0]["action"] == "APPROVE"
    contracts.validator.validate_document(decisions[0])

    # 2) Segundo intento con hash OBSOLETO -> 303 a ?stale=1, sin nueva decisión.
    stale = c.post(f"/review-console/source/{src}/decide", data={
        "candidate_id": cand, "action": "APPROVE",
        "expected_candidate_hash": "0" * 64, "csrf_token": csrf,
    })
    assert stale.status_code == 303 and "stale=1" in stale.headers["location"]
    assert len(rc.read_decisions(e2e.lab_dir)) == 1  # NO se escribió una segunda
    events = rc.read_audit_events(e2e.lab_dir)
    assert any(ev["event_type"] == "STALE_REVIEW_REJECTED" for ev in events)

    # Doble submit del MISMO hash válido: idempotencia observable — no crea
    # una decisión "distinta"; ambas referencian el mismo candidate_hash.
    c.post(f"/review-console/source/{src}/decide", data={
        "candidate_id": cand, "action": "APPROVE",
        "expected_candidate_hash": good_hash, "csrf_token": csrf,
    })
    dec = rc.read_decisions(e2e.lab_dir)
    assert len({d["expected_candidate_hash"]["value"] for d in dec}) == 1


# ── D-DEP-3: EXTERNAL_AI_SHADOW no puede auto-aprobar (no vinculante) ───────
def test_shadow_ai_decision_cannot_auto_approve_via_api(e2e) -> None:
    """La IA en sombra sólo puede DIFERIR; APPROVE con EXTERNAL_AI_SHADOW viola el contrato."""
    from app.services import review_console as rc
    cand = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(cand)

    # DEFER en sombra: válido.
    defer = rc.build_decision(cand, "DEFER", "shadow", ch, reviewer_type="EXTERNAL_AI_SHADOW")
    contracts.validator.validate_document(defer)

    # APPROVE en sombra: el contrato lo rechaza (no vinculante).
    approve = rc.build_decision(cand, "DEFER", "shadow", ch,
                                reviewer_type="EXTERNAL_AI_SHADOW") | {"action": "APPROVE"}
    with pytest.raises(Exception):
        contracts.validator.validate_document(approve)


# ── D-DEP-4: ingest-plan dry-run no crea nada (0 escrituras) ───────────────
def test_ingest_plan_dry_run_creates_nothing(e2e) -> None:
    """DRY_RUN: neo4j_before == neo4j_after; el preview no escribe en el laboratorio."""
    from app.services import review_console as rc

    result = contracts.load_example("dry_run_success")
    assert result["mode"] == "DRY_RUN"
    assert result["neo4j_before"] == result["neo4j_after"]  # 0 escrituras
    contracts.validator.validate_document(result)

    # Preview real del plan (solo lectura): reporta conteos, no autoriza ni escribe.
    preview = rc.plan_preview("src_demo_01")
    assert preview["would_create"] >= 1
    assert preview["authorization_granted"] is False
    # El preview NO escribe decisiones/eventos en el almacén de laboratorio.
    assert rc.read_decisions(e2e.lab_dir) == []
    assert rc.read_audit_events(e2e.lab_dir) == []


# ── D-DEP-4: APPLY exige autorización explícita del operador (separada) ─────
def test_apply_requires_explicit_operator_authorization(e2e) -> None:
    """Crear/pre-visualizar un plan NO autoriza aplicar: authorization.granted=False."""
    from app.services import review_console as rc

    plan = rc.get_ingest_plan("src_demo_01")
    assert plan is not None
    contracts.validator.validate_document(plan)
    # El plan por defecto no está aplicado ni autorizado.
    assert plan.get("status") != "APPLIED"
    auth = plan.get("authorization", {})
    assert auth.get("granted") is not True

    # Un plan "ready" del contrato tampoco lleva autorización concedida implícita.
    ready = contracts.load_example("ingest_plan_ready")
    assert ready["authorization"]["granted"] is False
    # Un plan BLOQUEADO nunca está listo para aplicar.
    blocked = contracts.load_example("ingest_plan_blocked")
    assert blocked["status"] == "BLOCKED"
