"""test_review_flow_e2e.py — E2E del panel de revisión (PREPARADOS, fase 1).

Estos escenarios dependen de trabajo aún NO publicado por otros equipos:
  - EQUIPO A: login, sesión, CSRF, roles.
  - EQUIPO B (data-engine): generación de candidatos, resumen por fuente,
    creación de ingest-plan, ejecución DRY_RUN.
  - EQUIPO C (viewer): rutas/plantillas del panel de review, endpoints de
    decisión, permisos por workspace/personaje, conteos/búsqueda filtrados.

Se dejan como `skip` con motivo explícito (no `xfail` silencioso) para que sean
visibles en el reporte y se activen en cuanto A/B/C expongan la superficie. El
contrato consumido para construir/validar payloads es review/ingest v1.

DEPENDENCIAS declaradas al coordinador (ver cuerpo del PR):
  D-DEP-1  ruta de login + helper de sesión autenticada (A).
  D-DEP-2  endpoint que sirve el panel de review y el resumen por fuente (B/C).
  D-DEP-3  endpoint POST de decisión (APPROVE/EDIT/DEFER/...) con control
           optimista (expected_candidate_hash) (C).
  D-DEP-4  endpoint de ingest-plan dry-run y su resultado (B/C).
  D-DEP-5  modelo de permisos por workspace/personaje y filtrado de
           conteos/búsqueda (C).
"""
from __future__ import annotations

import pytest

from support import contracts

pytestmark = pytest.mark.e2e

_NEEDS_ABC = "PENDIENTE fase 1: depende de endpoints/funciones de A/B/C aún no publicados"


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-1: login/sesión)")
def test_operator_can_log_in_and_reach_review_panel(lab_env, require_playwright) -> None:
    raise NotImplementedError


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-2: panel + resumen por fuente)")
def test_source_summary_panel_shows_blocked_when_conflicts() -> None:
    # Contrato listo: podemos afirmar la invariante que el panel debe reflejar.
    summary = contracts.load_example("source_summary_conflicts")
    assert summary["status"] == "BLOCKED"
    assert summary["ready_to_plan"] is False
    raise NotImplementedError("falta el endpoint que sirve el resumen")


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-3: POST decisión + control optimista)")
def test_stale_candidate_hash_rejects_decision() -> None:
    """Al decidir sobre un candidato ya cambiado, el visor debe devolver CONFLICT."""
    raise NotImplementedError


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-3: EXTERNAL_AI_SHADOW no vinculante)")
def test_shadow_ai_decision_cannot_auto_approve_via_api() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-4: ingest-plan dry-run)")
def test_ingest_plan_dry_run_creates_nothing() -> None:
    """DRY_RUN no debe crear/rollbackear nada; neo4j_before == neo4j_after."""
    result = contracts.load_example("dry_run_success")
    assert result["mode"] == "DRY_RUN"
    assert result["neo4j_before"] == result["neo4j_after"]
    raise NotImplementedError("falta el endpoint de dry-run")


@pytest.mark.skip(reason=_NEEDS_ABC + " (D-DEP-4: autorización separada del plan)")
def test_apply_requires_explicit_operator_authorization() -> None:
    raise NotImplementedError
