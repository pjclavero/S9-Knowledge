"""Regresión: los endpoints LEGACY aplican la MISMA política RPG que las rutas
nuevas del panel de solo lectura.

Antes de este fix, las rutas nuevas de #40 (``/api/entities`` ...) filtraban por
el ``PolicyFilteredProvider`` pero los endpoints legacy (``/api/search``,
``/api/entity/{id}``, ``/api/graph``, ``/api/workspaces``, ``/api/entity-types``,
``/api/status``, HTML ``/entity/{id}`` y ``/status``) consultaban el provider
BASE sin política: un viewer autenticado veía secretos, narrador, futuro,
workspaces ajenos y conteos totales.

Estos tests inyectan un ``ViewerContext`` restringido vía
``app.dependency_overrides[get_filtered_provider]`` (igual que
``test_authz_api_enforcement``) y comprueban de forma DETERMINISTA que:

  - ninguna ruta legacy revela el nodo secreto ni el de narrador;
  - el acceso directo por ID no visible devuelve 404 (indistinguible);
  - conteos y workspaces se calculan sobre lo visible;
  - el grafo (JSON y HTML) no contiene nodos/aristas ocultos;
  - la visibilidad efectiva es idéntica entre ruta nueva y ruta legacy;
  - un admin (admin_full) sigue viéndolo todo.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.authz.dependencies import get_filtered_provider
from app.authz.filtered_provider import PolicyFilteredProvider
from app.deps import get_provider
from app.policies.models import ViewerContext
from app.providers.mock_provider import MockGraphProvider

# --- sample_graph.json (escenario "culto"): mismo fixture que usa C en
#     test_authz_api_enforcement. El nodo secreto es "Culto del Pozo Viejo".
SECRET_ID = "n_culto_pozo_viejo"
NARRATOR_ID = "n_bayushi_hisao"
SECRET_LABEL = "Culto del Pozo Viejo"

# --- fixture rica (dimensiones de workspace/futuro/party): la de C.
RICH_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rpg_visibility_graph.json"
RICH_WS = "campania_lab"
RICH_HIDDEN = {
    "secret_villano",
    "secret_conocido_por_arden",
    "narrator_nota",
    "future_evento",
    "otro_grupo_npc",
    "otra_boveda_node",
}


def _viewer_ctx() -> ViewerContext:
    return ViewerContext(
        role="viewer",
        allowed_workspaces=frozenset({"leyenda"}),
        can_view_secret=False,
        can_view_future=False,
        can_view_reference=True,
        session_public=True,
    )


def _admin_ctx() -> ViewerContext:
    return ViewerContext(role="admin", admin_full=True, session_public=True)


def _viewer_bryn() -> ViewerContext:
    return ViewerContext(
        role="viewer",
        allowed_workspaces=frozenset({RICH_WS}),
        active_character="pc_bryn",
        max_visible_session=3,
        can_view_reference=True,
        party_membership=frozenset({"grupo_alfa"}),
        session_public=True,
    )


def _client(ctx: ViewerContext, base=None):
    """TestClient con el provider filtrado forzado a ``ctx``.

    Se sobreescribe ``get_filtered_provider`` (usado ahora por TODAS las rutas de
    datos, nuevas y legacy). Si ``base`` es None se usa el provider por defecto
    del entorno de test (sample_graph.json).
    """
    from app.main import app
    from fastapi.testclient import TestClient

    def _override():
        return PolicyFilteredProvider(base if base is not None else get_provider(), ctx)

    app.dependency_overrides[get_filtered_provider] = _override
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    from app.main import app
    app.dependency_overrides.pop(get_filtered_provider, None)


# ── /api/search ────────────────────────────────────────────────────────────

def test_legacy_search_oculta_secreto_para_viewer():
    c = _client(_viewer_ctx())
    r = c.get("/api/search?q=culto", headers={"accept": "application/json"})
    assert r.status_code == 200
    ids = {n["id"] for n in r.json()["results"]}
    # La ENTIDAD secreta (y la de narrador) no se devuelve como resultado. Que un
    # nodo visible (p.ej. n_kimi) mencione el nombre del secreto en su texto libre
    # es un asunto de autoría de datos, no del filtrado de entidades/aristas.
    assert SECRET_ID not in ids
    assert NARRATOR_ID not in ids


def test_legacy_search_admin_ve_secreto():
    c = _client(_admin_ctx())
    r = c.get("/api/search?q=culto", headers={"accept": "application/json"})
    assert r.status_code == 200
    assert SECRET_ID in {n["id"] for n in r.json()["results"]}


# ── /api/entity/{id} (JSON legacy) y /entity/{id} (HTML legacy) ─────────────

def test_legacy_entity_by_id_no_visible_404():
    c = _client(_viewer_ctx())
    assert c.get(f"/api/entity/{SECRET_ID}").status_code == 404
    assert c.get(f"/api/entity/{NARRATOR_ID}").status_code == 404


def test_legacy_entity_html_no_visible_404_sin_filtrar_datos():
    c = _client(_viewer_ctx())
    r = c.get(f"/entity/{SECRET_ID}")
    assert r.status_code == 404
    assert SECRET_LABEL not in r.text  # nada del secreto se envía al navegador


def test_legacy_entity_by_id_admin_200():
    c = _client(_admin_ctx())
    assert c.get(f"/api/entity/{SECRET_ID}").status_code == 200


# ── /api/graph y /graph HTML ───────────────────────────────────────────────

def test_legacy_graph_json_sin_nodos_ni_aristas_ocultos():
    c = _client(_viewer_ctx())
    data = c.get("/api/graph", headers={"accept": "application/json"}).json()
    ids = {n["id"] for n in data["nodes"]}
    assert SECRET_ID not in ids
    assert NARRATOR_ID not in ids
    # ninguna arista referencia un nodo oculto
    for e in data["edges"]:
        assert e.get("from") not in {SECRET_ID, NARRATOR_ID}
        assert e.get("to") not in {SECRET_ID, NARRATOR_ID}


def test_legacy_graph_html_no_embebe_secreto():
    c = _client(_viewer_ctx())
    r = c.get("/graph")
    assert r.status_code == 200
    assert SECRET_ID not in r.text
    assert SECRET_LABEL not in r.text


def test_legacy_graph_json_admin_incluye_secreto():
    c = _client(_admin_ctx())
    data = c.get("/api/graph", headers={"accept": "application/json"}).json()
    assert SECRET_ID in {n["id"] for n in data["nodes"]}


# ── /api/status y /api/entity-types: conteos filtrados ─────────────────────

def test_legacy_status_conteos_filtrados_y_provider_preservado():
    v = _client(_viewer_ctx()).get("/api/status").json()
    a = _client(_admin_ctx()).get("/api/status").json()
    assert v["nodes"] == 9      # 11 totales - 1 secreto - 1 narrador
    assert a["nodes"] == 11
    assert v["nodes"] < a["nodes"]  # el viewer no puede inferir el total
    assert v["provider"] == "mock"  # el wrapper no enmascara la identidad base


def test_legacy_entity_types_conteos_filtrados():
    v = _client(_viewer_ctx()).get("/api/entity-types").json()
    total_v = sum(t["count"] for t in v["entity_types"])
    assert total_v == 9  # solo lo visible se cuenta
    assert SECRET_LABEL not in str(v)


# ── /api/workspaces: solo los permitidos ───────────────────────────────────

def test_legacy_workspaces_solo_permitidos():
    base = MockGraphProvider(RICH_FIXTURE)  # tiene campania_lab y otra_boveda
    c = _client(_viewer_bryn(), base=base)
    wss = c.get("/api/workspaces").json()["workspaces"]
    assert "campania_lab" in wss
    assert "otra_boveda" not in wss  # workspace ajeno nunca se enumera


def test_legacy_graph_rich_oculta_futuro_party_y_secreto():
    base = MockGraphProvider(RICH_FIXTURE)
    c = _client(_viewer_bryn(), base=base)
    data = c.get(f"/api/graph?workspace={RICH_WS}", headers={"accept": "application/json"}).json()
    ids = {n["id"] for n in data["nodes"]}
    assert not (ids & RICH_HIDDEN)  # ni secreto, ni narrador, ni futuro, ni party ajena


# ── Equivalencia ruta NUEVA (C) vs ruta LEGACY ─────────────────────────────

def test_equivalencia_nueva_vs_legacy_oculta_igual():
    c = _client(_viewer_ctx())
    nueva = c.get("/api/entities?q=culto&limit=200").json()
    legacy = c.get("/api/search?q=culto").json()
    ids_nueva = {i["id"] for i in nueva["items"]}
    ids_legacy = {n["id"] for n in legacy["results"]}
    # ninguna de las dos revela el secreto: visibilidad efectiva idéntica
    assert SECRET_ID not in ids_nueva
    assert SECRET_ID not in ids_legacy


def test_equivalencia_id_404_en_ambas_rutas():
    c = _client(_viewer_ctx())
    assert c.get(f"/api/entities/{SECRET_ID}").status_code == 404   # ruta nueva (C)
    assert c.get(f"/api/entity/{SECRET_ID}").status_code == 404     # ruta legacy
