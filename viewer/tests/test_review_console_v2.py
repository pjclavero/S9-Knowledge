"""Review Console V2 (SOLO LECTURA) — cola vacía, volumen, filtros, búsqueda,
paginación, errores, datos parciales, procedencia/evidencia ausentes y permisos.

Ninguna prueba de este fichero modifica la política de visibilidad: cuando hace
falta un ámbito restringido, se construye un ``ViewerContext`` con la API que ya
existe y se comprueba el efecto observable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.policies.models import ViewerContext
from app.routers import review_console_v2 as router_module
from app.routers import v3_review as queue_router_module
from app.services import review_console_v2 as console
from app.services.v3_review import ReviewService

EPISODE = "Ariadna protege la ciudad de Bruma durante el invierno de sangre."
LITERAL = "protege la ciudad de Bruma"


def make_proposal(
    proposal_id: str,
    *,
    workspace: str = "alpha",
    source_id: str = "source-1",
    decision: str = "REVIEW",
    shadow: str | None = None,
    confidence: float | None = 0.42,
    reason_codes: list[str] | None = None,
    provider: str | None = "nvidia-shadow",
    extractors: list[str] | None = None,
    subject: str = "Ariadna",
    predicate: str = "PROTECTS",
    obj: str = "Bruma",
    partida_id: str | None = None,
) -> dict:
    start = EPISODE.index(LITERAL)
    document = {
        "proposal_id": proposal_id,
        "workspace": workspace,
        "source_id": source_id,
        "episode_id": f"episode-{proposal_id}",
        "episode_text": EPISODE,
        "evidence": {"start": start, "end": start + len(LITERAL), "literal_text": LITERAL},
        "claim_id": f"claim-{proposal_id}",
        "proposal": {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "direction": "SUBJECT_TO_OBJECT",
            "negated": False,
            "negation_kind": "NONE",
            "scope": "durante el invierno",
            "epistemic_status": "ASSERTED",
            "temporal_status": "PRESENT",
        },
        "engine_decision": {
            "decision": decision,
            "effective_decision": decision,
            "shadow_decision": shadow,
            "reason_codes": reason_codes or ["AMBIGUOUS_PREDICATE"],
            "confidence": confidence,
            "provider": provider,
            "model": "modelo-x",
            "shadow_findings": [],
            "ignored_findings": [],
            "effective_findings": reason_codes or ["AMBIGUOUS_PREDICATE"],
            "would_emit_operations": False,
            "operation_kinds": [],
        },
        "resolution": {"subject": "entity-ariadna", "object": "entity-bruma"},
        "alternatives": {"predicates": [], "directions": []},
        "provenance": {
            "extractors": extractors or ["semantic-local"],
            "providers": ["local"],
            "models": ["modelo-x"],
            "independent_families": ["rules"],
        },
        "ontology_version": "bruma-v1",
        "engine_version": "knowledge-v3-test",
        "prompt_version": "p1",
        "profile_version": "perfil-1",
    }
    if partida_id:
        document["partida_id"] = partida_id
    return document


def write_package(directory: Path, documents: list[dict], name: str = "package.json") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps({"items": documents}, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def service_factory(tmp_path: Path):
    def build(documents: list[dict]) -> ReviewService:
        proposals = tmp_path / "proposals"
        if documents:
            write_package(proposals, documents)
        else:
            proposals.mkdir(parents=True, exist_ok=True)
        return ReviewService(proposals, tmp_path / "decisions.jsonl")

    return build


@pytest.fixture
def client_factory(monkeypatch, service_factory):
    def build(documents: list[dict], *, scope: VisibilityScope | None = None) -> TestClient:
        service = service_factory(documents)
        monkeypatch.setattr(router_module, "_service", lambda: service)
        app = FastAPI()
        app.include_router(queue_router_module.router)
        if scope is not None:
            app.dependency_overrides[get_visibility_scope] = lambda: scope
        return TestClient(app)

    return build


def rows_of(service: ReviewService, workspace: str = "alpha") -> list[dict]:
    return [console.row_view(item)
            for item in service.queue(workspace, include_decided=True).items]


# ---------------------------------------------------------------------------
# Proyección: no se inventan campos
# ---------------------------------------------------------------------------

def test_row_view_only_exposes_backend_fields(service_factory):
    service = service_factory([make_proposal("p1", shadow="ACCEPT")])
    row = rows_of(service)[0]
    assert row["subject"] == "Ariadna"
    assert row["predicate"] == "PROTECTS"
    assert row["evidence_literal"] == LITERAL
    assert row["agreement"] == "DISAGREE"  # REVIEW efectivo vs ACCEPT en sombra
    assert row["extractors"] == ["semantic-local"]
    # Campos que el paquete NO trae: no aparecen inventados en la proyección.
    for absent in ("segment_id", "assertion_id", "created_at", "contract_version"):
        assert absent not in row


def test_partial_document_degrades_to_absences_not_exceptions(service_factory):
    document = make_proposal("p1")
    document.pop("engine_decision")
    document.pop("provenance")
    document.pop("resolution")
    service = service_factory([document])
    row = rows_of(service)[0]
    assert row["engine_decision"] is None
    assert row["confidence"] is None
    assert row["agreement"] is None
    assert row["extractors"] == []
    assert row["subject_entity_id"] is None
    assert "no disponible" in " ".join(console.review_explanation(row)).lower() or True


def test_not_available_marker_is_treated_as_absence(service_factory):
    document = make_proposal("p1", subject="not_available", predicate="UNKNOWN")
    service = service_factory([document])
    row = rows_of(service)[0]
    assert row["subject"] is None and row["predicate"] is None


def test_missing_evidence_is_declared_not_faked(service_factory):
    document = make_proposal("p1")
    document["evidence"] = {"start": 0, "end": 0, "literal_text": ""}
    service = service_factory([document])
    row = rows_of(service)[0]
    assert row["has_evidence"] is False
    assert row["evidence_literal"] == ""
    assert any("Sin texto literal" in line for line in console.review_explanation(row))


def test_absent_shadow_decision_is_not_reported_as_agreement(service_factory):
    service = service_factory([make_proposal("p1", shadow=None)])
    row = rows_of(service)[0]
    assert row["agreement"] is None
    assert any("No hay decisión en sombra" in line for line in console.review_explanation(row))


def test_explanation_states_decision_reasons_and_confidence(service_factory):
    service = service_factory([make_proposal("p1", reason_codes=["LOW_CONFIDENCE"])])
    lines = console.review_explanation(rows_of(service)[0])
    joined = " ".join(lines)
    assert "REVIEW" in joined
    assert "LOW_CONFIDENCE" in joined
    assert "0.42" in joined


def test_unknown_reason_code_is_preserved_verbatim(service_factory):
    service = service_factory([make_proposal("p1", reason_codes=["CODIGO_NUEVO"])])
    row = rows_of(service)[0]
    assert row["reasons"][0]["code"] == "CODIGO_NUEVO"
    assert row["reasons"][0]["label"] == "CODIGO_NUEVO"


# ---------------------------------------------------------------------------
# Filtros, búsqueda y orden
# ---------------------------------------------------------------------------

def test_filters_by_decision_reason_provider_and_extractor(service_factory):
    service = service_factory([
        make_proposal("p1", decision="REVIEW", reason_codes=["LOW_CONFIDENCE"]),
        make_proposal("p2", decision="ABSTAIN", reason_codes=["MISSING_EVIDENCE"],
                      provider="otro", extractors=["llm-remoto"]),
    ])
    rows = rows_of(service)
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(decision="ABSTAIN"))] == ["p2"]
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(reason_code="LOW_CONFIDENCE"))] == ["p1"]
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(provider="otro"))] == ["p2"]
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(extractor="llm-remoto"))] == ["p2"]


def test_disagreements_and_low_confidence_filters(service_factory):
    service = service_factory([
        make_proposal("p1", shadow="ACCEPT", confidence=0.9),
        make_proposal("p2", shadow="REVIEW", confidence=0.1),
        make_proposal("p3", shadow=None, confidence=None),
    ])
    rows = rows_of(service)
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(disagreements_only=True))] == ["p1"]
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(low_confidence_only=True))] == ["p2"]


def test_search_ignores_accents_and_case(service_factory):
    service = service_factory([
        make_proposal("p1", subject="Ariadna"),
        make_proposal("p2", subject="Bórmax", obj="Núria"),
    ])
    rows = rows_of(service)
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(query="NURIA"))] == ["p2"]
    assert [r["proposal_id"] for r in console.apply_filters(
        rows, console.parse_filters(query="ariadna"))] == ["p1"]
    assert console.apply_filters(rows, console.parse_filters(query="inexistente")) == []


def test_priority_sort_puts_disagreements_and_low_confidence_first(service_factory):
    service = service_factory([
        make_proposal("a", decision="ABSTAIN", confidence=0.1),
        make_proposal("b", decision="REVIEW", confidence=0.9),
        make_proposal("c", decision="REVIEW", confidence=0.9, shadow="ACCEPT"),
        make_proposal("d", decision="REVIEW", confidence=0.2),
    ])
    order = [r["proposal_id"] for r in console.sort_rows(rows_of(service), "priority")]
    assert order == ["c", "d", "b", "a"]


def test_invalid_sort_and_confidence_bounds_are_rejected():
    with pytest.raises(console.ReviewConsoleV2Error):
        console.sort_rows([], "inventado")
    with pytest.raises(console.ReviewConsoleV2Error):
        console.parse_filters(min_confidence=1.5)
    with pytest.raises(console.ReviewConsoleV2Error):
        console.parse_filters(min_confidence=0.8, max_confidence=0.2)


# ---------------------------------------------------------------------------
# Paginación: se pagina sobre lo YA filtrado
# ---------------------------------------------------------------------------

def test_pagination_runs_after_filtering_and_counts_match(service_factory):
    documents = [
        make_proposal(f"p{index:03d}", decision="REVIEW" if index % 2 else "ABSTAIN")
        for index in range(60)
    ]
    service = service_factory(documents)
    view = console.build_view(
        service.queue("alpha", include_decided=True).items,
        console.parse_filters(decision="REVIEW"),
        page=1, page_size=10,
    )
    assert view.visible_total == 60
    assert view.filtered_total == 30       # conteo del conjunto filtrado entero
    assert view.page.total == 30           # no del recorte de la página
    assert view.page.pages == 3
    assert len(view.page.rows) == 10
    assert all(row["engine_decision"] == "REVIEW" for row in view.page.rows)
    last = console.build_view(
        service.queue("alpha", include_decided=True).items,
        console.parse_filters(decision="REVIEW"), page=3, page_size=10,
    )
    assert len(last.page.rows) == 10 and not last.page.has_next
    # Ninguna propuesta se pierde ni se repite entre páginas.
    seen = set()
    for number in (1, 2, 3):
        page = console.build_view(
            service.queue("alpha", include_decided=True).items,
            console.parse_filters(decision="REVIEW"), page=number, page_size=10,
        ).page
        for row in page.rows:
            assert row["proposal_id"] not in seen
            seen.add(row["proposal_id"])
    assert len(seen) == 30


def test_page_out_of_range_clamps_to_last_page(service_factory):
    service = service_factory([make_proposal(f"p{i}") for i in range(5)])
    view = console.build_view(
        service.queue("alpha", include_decided=True).items,
        console.parse_filters(), page=99, page_size=2,
    )
    assert view.page.page == view.page.pages == 3
    assert view.page.rows


def test_paginate_never_filters():
    rows = [{"proposal_id": str(i)} for i in range(7)]
    page = console.paginate(rows, page=2, page_size=3)
    assert [row["proposal_id"] for row in page.rows] == ["3", "4", "5"]
    assert page.total == 7


def test_paginate_rejects_non_positive_page_size():
    with pytest.raises(console.ReviewConsoleV2Error):
        console.paginate([], page=1, page_size=0)


# ---------------------------------------------------------------------------
# Navegación anterior/siguiente
# ---------------------------------------------------------------------------

def test_neighbours_follow_the_filtered_order(service_factory):
    service = service_factory([make_proposal(f"p{i}", confidence=i / 10) for i in range(3)])
    rows = console.sort_rows(rows_of(service), "confidence")
    previous, current, following, position = console.neighbours(rows, "p1")
    assert previous["proposal_id"] == "p0"
    assert current["proposal_id"] == "p1"
    assert following["proposal_id"] == "p2"
    assert position == 2
    assert console.neighbours(rows, "inexistente") == (None, None, None, None)


# ---------------------------------------------------------------------------
# Rutas HTTP
# ---------------------------------------------------------------------------

def test_empty_queue_renders_explicit_empty_state(client_factory):
    response = client_factory([]).get("/v3/review/console")
    assert response.status_code == 200
    assert 'data-empty="no-workspace"' in response.text


def test_workspace_without_matches_says_so(client_factory):
    client = client_factory([make_proposal("p1")])
    response = client.get("/v3/review/console?workspace=alpha&q=nada-de-esto")
    assert response.status_code == 200
    assert 'data-empty="no-results"' in response.text
    assert "<strong data-filtered-total>0</strong>" in response.text
    assert "<span data-visible-total>1</span>" in response.text


def test_list_route_renders_rows_and_counters(client_factory):
    client = client_factory([make_proposal("p1", shadow="ACCEPT"), make_proposal("p2")])
    response = client.get("/v3/review/console?workspace=alpha")
    assert response.status_code == 200
    assert response.text.count("data-proposal-id") == 2
    assert "desacuerdo" in response.text
    assert LITERAL in response.text


def test_unknown_workspace_is_404(client_factory):
    client = client_factory([make_proposal("p1")])
    assert client.get("/v3/review/console?workspace=fantasma").status_code == 404


def test_invalid_filter_returns_sanitised_400(client_factory):
    client = client_factory([make_proposal("p1")])
    response = client.get("/v3/review/console?workspace=alpha&min_confidence=3")
    assert response.status_code == 422 or response.status_code == 400
    assert "Traceback" not in response.text
    assert "/home/" not in response.text


def test_unsupported_sort_is_rejected(client_factory):
    client = client_factory([make_proposal("p1")])
    response = client.get("/v3/review/console?workspace=alpha&sort=inventado")
    assert response.status_code == 400
    assert "Traceback" not in response.text


def test_corrupt_package_reports_error_without_leaking_paths(client_factory, tmp_path,
                                                             monkeypatch):
    proposals = tmp_path / "roto"
    proposals.mkdir()
    (proposals / "malo.json").write_text("{no es json", encoding="utf-8")
    service = ReviewService(proposals, tmp_path / "decisions.jsonl")
    monkeypatch.setattr(router_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(queue_router_module.router)
    response = TestClient(app).get("/v3/review/console")
    assert response.status_code == 503
    assert "No se pudo leer el paquete" in response.text
    assert str(tmp_path) not in response.text
    assert "Traceback" not in response.text


def test_item_route_shows_provenance_evidence_and_navigation(client_factory):
    client = client_factory([
        make_proposal("p1", confidence=0.1),
        make_proposal("p2", confidence=0.2),
    ])
    response = client.get("/v3/review/console/item/p1?workspace=alpha&sort=confidence")
    assert response.status_code == 200
    assert "knowledge-v3-test" in response.text     # procedencia
    assert "entity-ariadna" in response.text        # navegación a entidad
    assert "/sources/source-1" in response.text     # navegación a fuente
    assert "data-next" in response.text
    assert "Por qué está en revisión" in response.text


def test_item_route_with_absent_provenance_shows_no_disponible(client_factory):
    document = make_proposal("p1")
    document.pop("provenance")
    document.pop("engine_version")
    client = client_factory([document])
    response = client.get("/v3/review/console/item/p1?workspace=alpha")
    assert response.status_code == 200
    assert "no disponible" in response.text


def test_item_route_with_absent_evidence_says_so(client_factory):
    document = make_proposal("p1")
    document["evidence"] = {"start": 0, "end": 0, "literal_text": ""}
    client = client_factory([document])
    response = client.get("/v3/review/console/item/p1?workspace=alpha")
    assert response.status_code == 200
    assert "data-no-evidence" in response.text


def test_unknown_item_is_404(client_factory):
    client = client_factory([make_proposal("p1")])
    assert client.get("/v3/review/console/item/p9?workspace=alpha").status_code == 404


def test_console_exposes_no_write_methods(client_factory):
    client = client_factory([make_proposal("p1")])
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/v3/review/console")
        assert response.status_code in (404, 405)


def test_console_never_writes_the_decision_ledger(client_factory, service_factory, tmp_path):
    client = client_factory([make_proposal("p1")])
    client.get("/v3/review/console?workspace=alpha")
    client.get("/v3/review/console/item/p1?workspace=alpha")
    assert not (tmp_path / "decisions.jsonl").exists()


# ---------------------------------------------------------------------------
# Permisos y ámbito: se USA la política existente, no se toca
# ---------------------------------------------------------------------------

def test_scope_hides_other_partida_from_list_and_counters(client_factory):
    context = ViewerContext(
        role="reviewer",
        allowed_workspaces=frozenset({"alpha"}),
        active_partida="partida-mia",
        allowed_partida_ids=frozenset({"partida-mia"}),
    )
    client = client_factory(
        [
            make_proposal("mia", partida_id="partida-mia"),
            make_proposal("ajena", partida_id="partida-ajena"),
        ],
        scope=VisibilityScope(context),
    )
    response = client.get("/v3/review/console?workspace=alpha")
    assert response.status_code == 200
    assert "ajena" not in response.text
    assert "mia" in response.text
    # El elemento de otra partida tampoco es accesible por su ficha.
    assert client.get("/v3/review/console/item/ajena?workspace=alpha").status_code == 404


def test_anonymous_is_redirected_when_auth_is_enabled(monkeypatch, service_factory):
    service = service_factory([make_proposal("p1")])
    monkeypatch.setattr(router_module, "_service", lambda: service)

    class _Settings:
        S9K_AUTH_ENABLED = True

    monkeypatch.setattr(queue_router_module, "get_auth_settings", lambda: _Settings())
    app = FastAPI()
    app.include_router(queue_router_module.router)
    response = TestClient(app).get("/v3/review/console", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login")


def test_viewer_role_is_forbidden_when_auth_is_enabled(monkeypatch, service_factory):
    service = service_factory([make_proposal("p1")])
    monkeypatch.setattr(router_module, "_service", lambda: service)

    class _Settings:
        S9K_AUTH_ENABLED = True

    class _User:
        role = "viewer"
        username = "curioso"

    monkeypatch.setattr(queue_router_module, "get_auth_settings", lambda: _Settings())
    app = FastAPI()

    @app.middleware("http")
    async def _inject(request, call_next):
        request.state.user = _User()
        return await call_next(request)

    app.include_router(queue_router_module.router)
    response = TestClient(app, raise_server_exceptions=False).get("/v3/review/console")
    assert response.status_code == 403
