"""Enforcement extremo a extremo vía API (router + provider filtrado + política).

Usa el grafo de ejemplo (sample_graph.json), que contiene un nodo `secret`
(n_culto_pozo_viejo) y un nodo `narrator` (n_bayushi_hisao).

El ViewerContext se inyecta con ``app.dependency_overrides`` sobre
``get_filtered_provider``: así se prueba de forma DETERMINISTA que el filtrado
ocurre en la ruta/query real (no en HTML), sin depender del estado global de
settings/env entre tests. La construcción del contexto por rol se prueba aparte
en ``test_visibility_policy`` y en el propio ``context.py``.
"""
from __future__ import annotations

import pytest

from app.authz.dependencies import get_filtered_provider
from app.authz.filtered_provider import PolicyFilteredProvider
from app.deps import get_provider
from app.policies.models import ViewerContext

SECRET_ID = "n_culto_pozo_viejo"     # visibility=secret en el sample
NARRATOR_ID = "n_bayushi_hisao"      # visibility=narrator en el sample
WS = "leyenda"


def _viewer_ctx() -> ViewerContext:
    return ViewerContext(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        can_view_secret=False,
        can_view_future=False,
        can_view_reference=True,
        session_public=True,
    )


def _admin_ctx() -> ViewerContext:
    return ViewerContext(role="admin", admin_full=True, session_public=True)


def _client_with_ctx(ctx: ViewerContext):
    from app.main import app
    from fastapi.testclient import TestClient

    def _override():
        return PolicyFilteredProvider(get_provider(), ctx)

    app.dependency_overrides[get_filtered_provider] = _override
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    from app.main import app
    app.dependency_overrides.pop(get_filtered_provider, None)


def test_viewer_no_ve_secreto_en_listado():
    c = _client_with_ctx(_viewer_ctx())
    r = c.get("/api/entities?limit=200", headers={"accept": "application/json"})
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    assert SECRET_ID not in ids
    assert NARRATOR_ID not in ids


def test_viewer_acceso_directo_secreto_404():
    c = _client_with_ctx(_viewer_ctx())
    assert c.get(f"/api/entities/{SECRET_ID}").status_code == 404
    assert c.get(f"/api/entities/{NARRATOR_ID}").status_code == 404


def test_viewer_busqueda_no_revela_secreto():
    c = _client_with_ctx(_viewer_ctx())
    # "culto" sólo aparece en el nodo secreto.
    r = c.get("/api/entities?q=culto&limit=200")
    assert r.status_code == 200
    assert SECRET_ID not in {i["id"] for i in r.json()["items"]}


def test_admin_si_ve_secreto():
    c = _client_with_ctx(_admin_ctx())
    r = c.get("/api/entities?limit=200")
    ids = {i["id"] for i in r.json()["items"]}
    assert SECRET_ID in ids
    assert c.get(f"/api/entities/{SECRET_ID}").status_code == 200


def test_quality_no_incluye_secreto_para_viewer():
    c = _client_with_ctx(_viewer_ctx())
    r = c.get("/api/quality")
    assert r.status_code == 200
    by_vis = r.json().get("by_visibility", {})
    assert by_vis.get("secret", 0) == 0
    assert by_vis.get("narrator", 0) == 0
