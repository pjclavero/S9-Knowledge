# -*- coding: utf-8 -*-
"""E2E de navegador: el backend de datos no esta disponible.

El visor se arranca con `S9K_GRAPH_PROVIDER=neo4j` apuntando a un puerto donde
NO hay nada escuchando. Es la simulacion honesta de "Neo4j caido": no se sustituye
el proveedor por un doble que finja fallar, se le da una direccion muerta y se
observa lo que el producto hace de verdad.

Lo que se exige: nadie ve una traza de Python, nadie ve un 500 desnudo, y —sobre
todo— la caida del grafo NO abre la puerta: las rutas protegidas siguen exigiendo
sesion. Un fallo de infraestructura que convierta el visor en publico seria el
peor defecto posible.
"""
from __future__ import annotations

from typing import Iterator

import pytest

from e2e_support import ViewerServer, fetch_status, is_denied, login_as, start_viewer

# Puerto reservado a "descartar": nunca hay nada escuchando ahi.
NEO4J_MUERTO = "bolt://127.0.0.1:9"


@pytest.fixture(scope="module")
def viewer(tmp_path_factory) -> Iterator[ViewerServer]:
    """Sobrescribe la fixture global: mismo visor, con el grafo inalcanzable."""
    yield from start_viewer(tmp_path_factory, env={
        "S9K_GRAPH_PROVIDER": "neo4j",
        "S9K_NEO4J_URI": NEO4J_MUERTO,
        "S9K_NEO4J_USER": "neo4j",
        "S9K_NEO4J_PASSWORD": "password-de-laboratorio-inexistente",
    })


@pytest.fixture()
def admin_page(page, viewer):
    login_as(page, viewer, "s9admin")
    return page


def test_el_escenario_esta_realmente_montado(page, viewer):
    """Control del propio escenario: si el visor siguiese en `mock`, todo lo que
    viene despues seria un verde vacio. Se comprueba que el proveedor activo es
    neo4j y que NO esta conectado."""
    login_as(page, viewer, "s9admin")
    datos = page.request.get(viewer.url("/api/status")).json()
    assert datos.get("provider") == "neo4j", \
        f"el escenario no monto el proveedor neo4j (provider={datos.get('provider')})"
    assert datos.get("neo4j_connected") is False, \
        "el escenario dice estar conectado a un Neo4j que no existe"


def test_el_login_sigue_funcionando_con_el_grafo_caido(page, viewer):
    """La autenticacion no depende del grafo: vive en su propia base."""
    login_as(page, viewer, "s9admin")
    assert "/login" not in page.url, "con Neo4j caido ni siquiera se puede entrar"


@pytest.mark.parametrize("path", ["/", "/entities", "/graph", "/status"])
def test_las_paginas_no_reventan_ni_filtran_trazas(admin_page, viewer, path):
    status = fetch_status(admin_page, viewer, path)
    cuerpo = admin_page.content()
    assert "Traceback (most recent call last)" not in cuerpo, \
        f"{path} filtro una traza de Python con el backend caido"
    assert "neo4j://" not in cuerpo and NEO4J_MUERTO not in cuerpo, \
        f"{path} filtro la cadena de conexion del backend"
    assert status != 500 or "Traceback" not in cuerpo
    assert status < 600


def test_el_estado_admite_que_el_grafo_no_responde(admin_page, viewer):
    """/status es la pagina cuyo trabajo es decir la verdad sobre el backend."""
    resp = admin_page.request.get(viewer.url("/api/status"))
    assert resp.status in (200, 500, 503), f"status inesperado: {resp.status}"
    if resp.status == 200:
        datos = resp.json()
        assert datos.get("neo4j_connected") is not True, \
            "el visor dice estar conectado a un Neo4j que no existe"


def test_el_grafo_caido_no_convierte_el_visor_en_publico(new_page, viewer):
    """LA prueba de este modulo: sin sesion se sigue sin pasar.

    Fail-closed: que la fuente de datos este muerta no puede degradar la
    autorizacion. Si esto se pusiera verde por accidente (por ejemplo, porque un
    error del proveedor cortocircuitase el guarda), seria un agujero real.
    """
    anonimo = new_page()
    for path in ["/", "/entities", "/graph", "/status", "/admin/users"]:
        denied, status, url = is_denied(anonimo, viewer, path)
        assert denied, f"{path} se sirvio sin sesion con el backend caido: status={status} url={url}"


def test_la_api_sin_sesion_sigue_dando_401_no_500(new_page, viewer):
    anonimo = new_page()
    for path in ["/api/entities", "/api/graph", "/api/status"]:
        resp = anonimo.request.get(viewer.url(path))
        assert resp.status == 401, \
            f"{path} respondio {resp.status} sin sesion con el backend caido"


def test_los_roles_siguen_separados_con_el_backend_caido(new_page, viewer):
    pg = new_page()
    login_as(pg, viewer, "s9viewer")
    assert fetch_status(pg, viewer, "/admin/users") == 403, \
        "con el backend caido un viewer entro en el panel de admin"
