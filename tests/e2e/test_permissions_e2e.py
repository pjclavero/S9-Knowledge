"""test_permissions_e2e.py — E2E de permisos RPG contra el producto integrado.

Fase 2: la autorización del EQUIPO C está en main. Estos E2E usan login real y
las rutas reales del visor; la autorización (rol -> contexto RPG ->
PolicyFilteredProvider) es la REAL. Sólo la fuente de datos es un doble de
laboratorio (fixture anonimizada). Nunca se toca producción ni Neo4j.

El nodo secreto ``n_culto`` ("Culto del Pozo Viejo") y el de otro workspace
``n_foraneo`` (workspace ``otra_boveda``) permiten comprobar el aislamiento.

DEPENDENCIAS históricas cubiertas: D-DEP-1 (sesión), D-DEP-5 (permisos/filtrado).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

SECRET_ID = "n_culto"
NARRATOR_ID = "n_gm_nota"
FOREIGN_ID = "n_foraneo"          # workspace "otra_boveda"
KNOWN_SECRET_ID = "n_conocido"    # secreto que pc_bryn SÍ conoce


# ── D-DEP-5: un operador sólo ve su workspace autorizado ───────────────────
def test_operator_sees_only_authorized_workspace(e2e) -> None:
    reviewer = e2e.make_user("rev_ws", "reviewer")
    admin = e2e.make_user("adm_ws", "admin")

    # Reviewer: sólo enumera el workspace por defecto autorizado (leyenda).
    rc_ws = e2e.client(reviewer).get("/api/workspaces").json()["workspaces"]
    assert "leyenda" in rc_ws
    assert "otra_boveda" not in rc_ws  # workspace ajeno nunca se enumera

    # Admin (admin_full): ve todos los workspaces.
    ad_ws = e2e.client(admin).get("/api/workspaces").json()["workspaces"]
    assert "leyenda" in ad_ws and "otra_boveda" in ad_ws

    # Las fuentes que ve el reviewer no incluyen entidades del workspace ajeno.
    sources = e2e.client(reviewer).get("/api/sources").json()["sources"]
    assert all(s["source_id"] != "doc_otra" for s in sources)


# ── D-DEP-5: "ver como personaje" filtra por conocimiento (solo lectura) ───
def test_view_as_character_filters_visible_entities(e2e) -> None:
    """Simulación real: admin_full desactivado; el personaje sólo ve lo que conoce."""
    from app.authz.context import context_for_simulated_character
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.authz.simulation import build_view_as_character_event
    from app.providers.mock_provider import MockGraphProvider
    from support import contracts

    ctx = context_for_simulated_character(
        default_workspace="leyenda", allowed_workspaces=["leyenda"],
        active_character="pc_bryn", max_visible_session=5,
        party_membership=["grupo_alfa"], character_knowledge=[KNOWN_SECRET_ID],
    )
    assert ctx.admin_full is False  # el admin NO conserva bypass al encarnar

    provider = PolicyFilteredProvider(MockGraphProvider(e2e.graph_path), ctx)
    items, _ = provider.list_entities("leyenda", limit=1000)
    visible = {n["id"] for n in items}

    # Ve el secreto que su personaje conoce, pero NO el secreto ajeno ni el narrador.
    assert KNOWN_SECRET_ID in visible
    assert SECRET_ID not in visible
    assert NARRATOR_ID not in visible
    # Acceso directo al secreto no conocido: indistinguible de inexistente.
    assert provider.entity(SECRET_ID) is None

    # La acción se audita con un evento VIEW_AS_CHARACTER válido...
    event = build_view_as_character_event(
        workspace="leyenda", admin_actor_id="adm_1",
        simulated_character="pc_bryn", event_id="evt_e2e_1",
    )
    contracts.validator.validate_document(event)
    assert event["event_type"] == "VIEW_AS_CHARACTER"
    # ...y es SOLO LECTURA: no se persiste ninguna decisión en el laboratorio.
    from app.services import review_console as rc
    assert rc.read_decisions(e2e.lab_dir) == []


# ── D-DEP-5: conteos y búsqueda llegan filtrados por permiso ───────────────
def test_counts_and_search_are_permission_filtered(e2e) -> None:
    viewer = e2e.make_user("vw_cs", "viewer")
    admin = e2e.make_user("adm_cs", "admin")

    v_status = e2e.client(viewer).get("/api/status").json()
    a_status = e2e.client(admin).get("/api/status").json()
    # El viewer cuenta MENOS que el admin (no puede inferir el total real).
    assert v_status["nodes"] < a_status["nodes"]
    assert v_status["provider"] == "mock"  # identidad del provider preservada

    # Búsqueda: "culto" sólo aparece en el nodo secreto -> el viewer no lo obtiene.
    v_search = e2e.client(viewer).get("/api/search?q=culto").json()["results"]
    assert SECRET_ID not in {n["id"] for n in v_search}
    # Admin sí lo encuentra.
    a_search = e2e.client(admin).get("/api/search?q=culto").json()["results"]
    assert SECRET_ID in {n["id"] for n in a_search}

    # El grafo del viewer no contiene el nodo secreto ni aristas hacia él.
    v_graph = e2e.client(viewer).get("/api/graph").json()
    ids = {n["id"] for n in v_graph["nodes"]}
    assert SECRET_ID not in ids and NARRATOR_ID not in ids
    for edge in v_graph["edges"]:
        assert edge.get("from") != SECRET_ID and edge.get("to") != SECRET_ID


# ── D-DEP-1 + D-DEP-5: acceso a workspace ajeno denegado (404 indistinguible) ─
def test_unauthorized_workspace_access_is_denied(e2e) -> None:
    viewer = e2e.make_user("vw_denied", "viewer")
    c = e2e.client(viewer)

    # ID de un nodo real pero de workspace ajeno -> 404 (como si no existiera),
    # tanto por la ruta nueva (C) como por la legacy (fix de fuga).
    assert c.get(f"/api/entities/{FOREIGN_ID}").status_code == 404
    assert c.get(f"/api/entity/{FOREIGN_ID}").status_code == 404

    # El workspace ajeno no se enumera para el viewer.
    assert "otra_boveda" not in c.get("/api/workspaces").json()["workspaces"]

    # El secreto del propio workspace también da 404 por ID (no 403), para no
    # revelar su existencia por diferencia de código.
    assert c.get(f"/api/entities/{SECRET_ID}").status_code == 404
    assert c.get(f"/api/entity/{SECRET_ID}").status_code == 404
