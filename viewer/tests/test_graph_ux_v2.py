"""Visor de grafo UX V2 — página, contrato con la API y lógica pura en JS.

Dos bloques:

1. Tests de la página `/graph` y de los estáticos que sirve el visor
   (estructura, ausencia de CDN, no regresión de rutas).
2. Un puente a `viewer/tests/js/graph_core_spec.js`, que ejerce con Node la
   lógica pura de búsqueda/filtros/estados/URL de `graph-core.js`.

Este módulo NO comprueba autorización ni visibilidad: eso es competencia de
los tests de authz (test_authz_*, test_visibility_*). Aquí solo se verifica
que la interfaz no inventa vocabulario de permisos por su cuenta.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

VIEWER_ROOT = Path(__file__).resolve().parents[1]
STATIC = VIEWER_ROOT / "app" / "static"
TEMPLATES = VIEWER_ROOT / "app" / "templates"
GRAPH_HTML = TEMPLATES / "graph.html"
GRAPH_JS = STATIC / "js" / "graph.js"
GRAPH_CORE_JS = STATIC / "js" / "graph-core.js"
VENDOR_JS = STATIC / "js" / "vendor" / "vis-network.min.js"
JS_SPEC = Path(__file__).resolve().parent / "js" / "graph_core_spec.js"

client = TestClient(app)


# ---------------------------------------------------------------------------
# Página /graph: estructura de la interfaz
# ---------------------------------------------------------------------------

def test_graph_page_renders():
    r = client.get("/graph")
    assert r.status_code == 200
    assert "graph-canvas" in r.text


@pytest.mark.parametrize(
    "element_id",
    [
        "filters-panel",          # panel lateral de filtros
        "entity-type-filters",    # filtros por tipo de entidad
        "relation-type-filters",  # filtros por tipo de relación
        "graph-legend",           # leyenda visual
        "search-input",           # búsqueda
        "search-results",         # resultados de búsqueda localizables
        "side-panel",             # ficha lateral sin abandonar el grafo
        "side-panel-body",
        "counter-nodes",          # contador de nodos
        "counter-edges",          # contador de relaciones
        "labels-toggle",          # mostrar/ocultar etiquetas de relación
        "fit-btn",                # encajar
        "reset-btn",              # reiniciar vista
        "graph-status",           # zona de estados (cargando/vacío/error)
    ],
)
def test_graph_page_contiene_los_controles_de_la_v2(element_id):
    r = client.get("/graph")
    assert f'id="{element_id}"' in r.text, f"falta el control {element_id!r} en /graph"


def test_graph_page_carga_el_core_y_la_ui():
    r = client.get("/graph")
    assert "/static/js/graph-core.js" in r.text
    assert "/static/js/graph.js" in r.text


def test_zona_de_estado_es_anunciable_por_lector_de_pantalla():
    r = client.get("/graph")
    assert 'role="status"' in r.text
    assert 'aria-live="polite"' in r.text


def test_graph_page_no_embebe_datos_del_grafo():
    """La plantilla solo lleva workspace y límite; los datos llegan por la API
    ya filtrada. Si se embebieran nodos aquí se saltaría el filtrado."""
    r = client.get("/graph")
    assert '"nodes"' not in r.text
    assert '"edges"' not in r.text


# ---------------------------------------------------------------------------
# Sin dependencias externas: vis-network vendorizado
# ---------------------------------------------------------------------------

def test_vis_network_esta_vendorizado_y_es_real():
    assert VENDOR_JS.exists(), "falta el vis-network vendorizado"
    # 600 KB largos: si alguien lo sustituye por un stub, esto salta.
    assert VENDOR_JS.stat().st_size > 400_000
    head = VENDOR_JS.read_text(encoding="utf-8", errors="replace")[:400]
    assert "vis-network" in head


def test_la_pagina_del_grafo_no_pide_nada_a_internet():
    r = client.get("/graph")
    externos = re.findall(r'(?:src|href)="(https?://[^"]+)"', r.text)
    assert externos == [], f"la página del grafo depende de recursos externos: {externos}"


@pytest.mark.parametrize(
    "ruta",
    ["/static/js/graph.js", "/static/js/graph-core.js", "/static/css/app.css"],
)
def test_los_estaticos_del_visor_se_sirven(ruta):
    r = client.get(ruta)
    assert r.status_code == 200
    assert len(r.content) > 0


def test_el_vendor_se_sirve_desde_el_propio_servidor():
    r = client.get("/static/js/vendor/vis-network.min.js")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Contrato con la API que consume el visor
# ---------------------------------------------------------------------------

def test_api_graph_devuelve_lo_que_la_ui_necesita():
    data = client.get("/api/graph", params={"workspace": "leyenda", "limit": 100}).json()
    assert data["nodes"] and data["edges"]
    n = data["nodes"][0]
    for campo in ("id", "label", "type", "type_label"):
        assert campo in n, f"la UI necesita el campo {campo!r} en cada nodo"
    e = data["edges"][0]
    for campo in ("id", "from", "to", "type", "label"):
        assert campo in e, f"la UI necesita el campo {campo!r} en cada relación"


def test_expandir_vecinos_usa_un_endpoint_existente():
    """El botón "Expandir vecinos" llama a /api/entities/{id}: si esa ruta
    cambia de forma, la funcionalidad muere en silencio en el navegador."""
    assert "/api/entities/" in GRAPH_JS.read_text(encoding="utf-8")
    node_id = client.get("/api/graph", params={"workspace": "leyenda", "limit": 5}).json()["nodes"][0]["id"]
    r = client.get(f"/api/entities/{node_id}")
    assert r.status_code == 200
    data = r.json()
    assert "outgoing" in data and "incoming" in data


def test_api_entities_inexistente_no_filtra_detalle_interno():
    r = client.get("/api/entities/no-existe-este-id")
    assert r.status_code == 404
    assert "Traceback" not in r.text
    assert str(VIEWER_ROOT) not in r.text


# ---------------------------------------------------------------------------
# No regresión de rutas del visor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/", "/graph", "/entities", "/status", "/jobs"])
def test_las_rutas_html_siguen_respondiendo(ruta):
    assert client.get(ruta).status_code == 200


@pytest.mark.parametrize(
    "ruta",
    ["/api/status", "/api/graph", "/api/entities", "/api/entity-types"],
)
def test_las_rutas_api_siguen_respondiendo(ruta):
    assert client.get(ruta).status_code == 200


# ---------------------------------------------------------------------------
# Fronteras del carril: la UI no inventa vocabulario de autorización
# ---------------------------------------------------------------------------

VOCABULARIO_PROHIBIDO = [
    "known_by",
    "known_from_session",
    "max_visible_session",
    "can_view_future",
    "character_access",
    "knowledge_grant",
    "view_as",
]


@pytest.mark.parametrize("termino", VOCABULARIO_PROHIBIDO)
def test_la_ui_del_grafo_no_reimplementa_autorizacion(termino):
    """El visor pinta lo que el backend le da. Si aquí apareciera lógica de
    visibilidad, habría dos fuentes de verdad para los permisos."""
    for fichero in (GRAPH_HTML, GRAPH_JS, GRAPH_CORE_JS):
        assert termino not in fichero.read_text(encoding="utf-8"), (
            f"{fichero.name} menciona {termino!r}: la autorización vive en el backend"
        )


def test_el_estado_de_la_url_solo_admite_parametros_de_presentacion():
    """Nada de la URL puede pedir ver más de lo que corresponde: las claves
    aceptadas son solo de presentación."""
    texto = GRAPH_CORE_JS.read_text(encoding="utf-8")
    m = re.search(r"ALLOWED_STATE_KEYS\s*=\s*\[([^\]]*)\]", texto)
    assert m, "no se encuentra la lista blanca de parámetros de URL"
    claves = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert claves == {"q", "types", "rels", "limit", "labels", "iso"}


# ---------------------------------------------------------------------------
# Puente a la especificación en Node (lógica pura: búsqueda y filtros)
# ---------------------------------------------------------------------------

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node no disponible en este entorno")
def test_graph_core_js_spec():
    """Ejecuta viewer/tests/js/graph_core_spec.js.

    Cada caso de esa especificación cubre búsqueda, filtros de entidad y de
    relación, estados vacíos/sin resultados/error y el estado de la URL.
    """
    proc = subprocess.run(
        [NODE, str(JS_SPEC)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(VIEWER_ROOT),
    )
    salida = proc.stdout + proc.stderr
    assert proc.returncode == 0, "la especificación JS ha fallado:\n" + salida
    m = re.search(r"(\d+) pasados, (\d+) fallidos", salida)
    assert m, "la especificación JS no ha informado de su recuento:\n" + salida
    pasados, fallidos = int(m.group(1)), int(m.group(2))
    assert fallidos == 0
    assert pasados >= 30, f"se esperaban al menos 30 casos JS, hubo {pasados}"


def test_la_especificacion_js_existe_aunque_no_haya_node():
    """Si node no está, el puente se salta; el fichero debe seguir en el repo."""
    assert JS_SPEC.exists()
