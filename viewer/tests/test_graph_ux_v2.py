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
    """HALLAZGO H5: la versión anterior de este test buscaba `aria-live` en
    cualquier sitio de la página y se conformaba con el de `.graph-counters`,
    así que `#graph-status` —la zona que anuncia cargando/vacío/error— podía
    quedarse muda sin que nada fallara. Ahora se mira ESE elemento."""
    r = client.get("/graph")
    m = re.search(r"<p[^>]*id=\"graph-status\"[^>]*>", r.text)
    assert m, "no se encuentra el elemento #graph-status en la página"
    etiqueta = m.group(0)
    assert 'role="status"' in etiqueta, f"#graph-status sin role=status: {etiqueta}"
    assert 'aria-live="polite"' in etiqueta, (
        f"#graph-status no es una región viva; un aria-live en otro elemento "
        f"no anuncia estos mensajes: {etiqueta}")


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


@pytest.mark.parametrize("fichero", ["graph.js", "graph-core.js"])
def test_los_estaticos_del_grafo_no_llevan_caracteres_de_control(fichero):
    """`graph-core.js` llevaba un NUL incrustado en un separador de cadena
    (`join(" \\x00 ")`). Invisible al leer, hacía que git tratase el fichero
    como binario —sin diffs revisables— y podría romper cualquier herramienta
    que lo procese como texto."""
    crudo = (STATIC / "js" / fichero).read_bytes()
    malos = {b for b in crudo if b < 9 or 13 < b < 32}
    assert not malos, f"{fichero} contiene bytes de control: {sorted(malos)}"


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

def test_api_graph_devuelve_lo_que_la_ui_necesita(lector_por_dependencia):
    # LORE-ANONIMO-DENEGADO (V3 RC, 2026-08-14): sin principal ya no se
    # entrega la capa juego, asi que esta prueba de FORMA necesita un lector
    # con derecho. Lo instala por las dependencias que si muerden.
    lector_por_dependencia(app)
    data = client.get("/api/graph", params={"workspace": "leyenda", "limit": 100}).json()
    assert data["nodes"] and data["edges"]
    n = data["nodes"][0]
    for campo in ("id", "label", "type", "type_label"):
        assert campo in n, f"la UI necesita el campo {campo!r} en cada nodo"
    e = data["edges"][0]
    for campo in ("id", "from", "to", "type", "label"):
        assert campo in e, f"la UI necesita el campo {campo!r} en cada relación"


def test_expandir_vecinos_usa_un_endpoint_existente(lector_por_dependencia):
    """El botón "Expandir vecinos" llama a /api/entities/{id}: si esa ruta
    cambia de forma, la funcionalidad muere en silencio en el navegador."""
    # LORE-ANONIMO-DENEGADO (V3 RC, 2026-08-14): sin principal ya no se
    # entrega la capa juego, asi que esta prueba de FORMA necesita un lector
    # con derecho. Lo instala por las dependencias que si muerden.
    lector_por_dependencia(app)
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


# ---------------------------------------------------------------------------
# Coherencia transversal: `visibility` y `knowledge_layer` no son presentación
#
# DECISIÓN DEL OPERADOR: esos campos se quedan FUERA de la ficha del usuario
# normal. El razonamiento no admite excepciones por plantilla: el frontend no
# debe razonar sobre `visibility`, `known_by`, `scope` ni `knowledge_layer`
# como si fueran atributos de presentación, porque la autorización ocurre
# ANTES de que el contenido llegue.
#
# La objeción del revisor era justa: la ficha lateral del grafo dejó de
# mostrarlos, pero `entity.html` y `entity_detail.html` —a las que se llega
# desde el botón "Ficha completa" de esa misma ficha— seguían haciéndolo. Tal
# cual, era una incoherencia, no un principio. Estos tests la cierran.
#
# Lo que NO se retira: `review_status_label`, que es calidad del dato (¿está
# revisado?) y no autorización. Sigue mostrándose en las dos plantillas.
# ---------------------------------------------------------------------------

FICHAS_DE_ENTIDAD = ("entity.html", "entity_detail.html")


@pytest.mark.parametrize("nombre", FICHAS_DE_ENTIDAD)
@pytest.mark.parametrize("campo", ["visibility_label", "knowledge_layer_label",
                                   "visibility", "knowledge_layer"])
def test_las_fichas_de_entidad_no_pintan_vocabulario_de_visibilidad(nombre, campo):
    texto = (TEMPLATES / nombre).read_text(encoding="utf-8")
    renderizados = re.findall(r"\{\{[^}]*\}\}", texto)
    for expr in renderizados:
        assert campo not in expr, (
            f"{nombre} renderiza {campo!r} ({expr.strip()}): la autorización no "
            f"es un atributo de presentación")


@pytest.mark.parametrize("nombre", FICHAS_DE_ENTIDAD)
def test_las_fichas_de_entidad_conservan_el_estado_de_revision(nombre):
    """Control de que la limpieza no se ha llevado por delante información
    funcional: el estado de revisión dice si el dato está validado."""
    texto = (TEMPLATES / nombre).read_text(encoding="utf-8")
    assert "review_status_label" in texto, (
        f"{nombre} ha perdido el estado de revisión, que sí es información que "
        f"el usuario necesita")


@pytest.mark.parametrize("plantilla", ["/entity/{}", "/entities/{}"])
def test_la_ficha_servida_no_menciona_ninguna_etiqueta_de_visibilidad(plantilla, lector_por_dependencia):
    """La comprobación equivalente sobre el HTML ya renderizado, por si algún
    día el dato llegase por otro camino (una macro, un include)."""
    # LORE-ANONIMO-DENEGADO (V3 RC, 2026-08-14): sin principal ya no se
    # entrega la capa juego, asi que esta prueba de FORMA necesita un lector
    # con derecho. Lo instala por las dependencias que si muerden.
    lector_por_dependencia(app)
    from app.labels import VISIBILITY_LABELS_ES

    entity_id = client.get(
        "/api/graph", params={"workspace": "leyenda", "limit": 5}
    ).json()["nodes"][0]["id"]
    r = client.get(plantilla.format(entity_id))
    assert r.status_code == 200
    for etiqueta in VISIBILITY_LABELS_ES.values():
        assert f">{etiqueta}<" not in r.text, (
            f"{plantilla} sigue pintando la visibilidad ({etiqueta})")


# ---------------------------------------------------------------------------
# "Sin acceso" no es lo mismo que "no existe" (bloqueante 5)
# ---------------------------------------------------------------------------

def test_la_ui_solo_habla_de_acceso_ante_401_y_403():
    """Contrato real, comprobado contra `graph-core.js`.

    Cuando la política oculta un nodo, el proveedor filtrado devuelve `None` y
    `/api/entities/{id}` responde 404: exactamente lo mismo que si el id no
    existiera. Por tanto el 404 NO puede traducirse a "no tienes acceso" —eso
    confirmaría la existencia de lo oculto—, y solo 401/403, que vienen del
    guarda y no del contenido, pueden hablar de acceso.
    """
    texto = GRAPH_CORE_JS.read_text(encoding="utf-8")
    familias = dict(re.findall(r"code === (\d+)\) return \"(\w+)\"", texto))
    assert familias.get("401") == "unauthenticated"
    assert familias.get("403") == "forbidden"
    assert familias.get("404") == "not_found", \
        "un 404 debe ser 'no encontrado'; nunca 'sin acceso'"

    mensajes = dict(re.findall(r"^\s{4}(\w+): \"([^\"]+)\"", texto, re.M))
    assert "acceso" not in mensajes["not_found"].lower(), (
        f"el mensaje de 404 habla de acceso y delata que el elemento existe: "
        f"{mensajes['not_found']!r}")
    assert "acceso" in mensajes["forbidden"].lower()


def test_una_entidad_oculta_y_una_inexistente_son_indistinguibles_para_la_ui():
    """El 404 del backend no lleva nada que permita distinguir los dos casos."""
    r = client.get("/api/entities/no-existe-este-id")
    assert r.status_code == 404
    cuerpo = r.text.lower()
    for pista in ("visibility", "secret", "oculto", "known_by", "scope", "policy"):
        assert pista not in cuerpo, f"el 404 filtra vocabulario de política: {pista}"


# ---------------------------------------------------------------------------
# Expandir vecinos: ni un contador de lo que falta (bloqueante 4)
# ---------------------------------------------------------------------------

def test_expandir_vecinos_no_cuenta_lo_que_no_ha_llegado():
    """REGLA DEL OPERADOR: pedir expandir X y pintar lo que el backend dé. Si
    llegan menos vecinos de los que existen, la UI NO dice cuántos faltan;
    "3 de 7 visibles" revelaría que hay cuatro ocultos."""
    texto = GRAPH_JS.read_text(encoding="utf-8")
    m = re.search(r"function expandNeighbors\(nodeId\) \{(.+?)\n  \}\n", texto, re.S)
    assert m, "no se encuentra expandNeighbors en graph.js"
    cuerpo = m.group(1)
    assert "Se muestran los elementos disponibles para tu vista." in texto
    for sospechoso in ("after.nodes - before.nodes", "added", " de \" +", "length +"):
        assert sospechoso not in cuerpo, (
            f"expandNeighbors calcula un recuento de vecinos ({sospechoso!r}): "
            f"cualquier número ahí delata lo que la política ocultó")


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


def test_el_job_de_ci_que_obliga_a_node_esta_instalado():
    """Este fichero se auto-omite si falta Node (`skipif`), así que sin un job
    que instale Node las ~38 aserciones de la especificación JS se saltaban en
    silencio y el job requerido pasaba igual. `.github/scripts/check_ci_config.py`
    es el gate que lo impide; aquí se comprueba que sigue habiendo un job."""
    ci = (VIEWER_ROOT.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "actions/setup-node" in ci, "ningún job de CI instala Node"
    assert "tests/test_graph_ux_v2.py" in ci, \
        "ningún job de CI ejecuta este fichero con Node disponible"


def test_existe_la_bateria_de_navegador_del_grafo():
    """`graph.js` (DOM + vis-network) solo se puede comprobar en un navegador.
    Si este fichero desapareciera, volveríamos al punto de partida: renombrar
    un id y ver la suite en verde con la página en negro."""
    e2e = Path(__file__).resolve().parent / "browser" / "test_browser_graph_ux.py"
    assert e2e.exists(), "falta la batería E2E de navegador del visor de grafo"
    assert (e2e.parent / "e2e_support.py").exists(), \
        "falta la infraestructura de navegador compartida (carril D)"


# ---------------------------------------------------------------------------
# GATE de parcialidad, parte JS (docs/73). Vive AQUI y no en
# `test_parcialidad_declarada.py` porque este es el fichero que el job
# `test-graph-js` ejecuta POR NOMBRE con Node instalado y prohibiendo skips.
# En `viewer/tests/` a secas se omitiria en silencio: un gate omitido no es un
# gate. Su gemelo en Python (contrato del servidor, contadores, plantilla) si
# vive alli, porque no necesita Node.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# El aviso en JS: mutación real del fichero, ejecutada con Node
# ---------------------------------------------------------------------------
_SONDA_JS = """
const assert = require("assert");
const core = require(process.argv[process.argv.length - 1]);
const truncada = {limit:300, truncated:true, nodes_shown:300, nodes_total:2000,
                  edges_shown:171, edges_total:6000};
const aviso = core.partialityNotice(truncada);
assert(aviso, "vista TRUNCADA sin aviso: el visor la presenta como completa");
assert(/300/.test(aviso) && /2000/.test(aviso), "el aviso no dice cuanto falta");
assert(core.partialityNotice({limit:300, truncated:false, nodes_shown:5,
       nodes_total:5, edges_shown:4, edges_total:4}) === null,
       "una vista completa no debe avisar");
assert(core.partialityNotice(undefined), "sin metadato hay que avisar");
"""


def _corre_sonda(ruta_core: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, "-e", _SONDA_JS, "--", str(ruta_core)],
        capture_output=True, text=True, timeout=60,
    )


@pytest.mark.skipif(NODE is None, reason="node no disponible en este entorno")
def test_la_sonda_js_pasa_sobre_el_fichero_real():
    r = _corre_sonda(GRAPH_CORE_JS)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(NODE is None, reason="node no disponible en este entorno")
def test_calibracion_js_romper_el_aviso_pone_la_sonda_en_ROJO(tmp_path):
    """MUTACIÓN 7, la que pedía el operador con nombre y apellidos: forzar una
    respuesta truncada y ROMPER el indicador de parcialidad. La sonda que pasa
    en verde sobre el fichero real tiene que ponerse ROJA sobre cada mutante.

    Tres mutantes, tres formas distintas de romperlo:
      (a) callar siempre,
      (b) declarar completa cualquier vista,
      (c) avisar, pero sin decir cuánto falta.
    """
    fuente = GRAPH_CORE_JS.read_text(encoding="utf-8")
    ORIGINAL_AVISO = (
        'return "Vista parcial: se muestran " + n + " de " + N + " entidades y " +'
    )
    mutantes = {
        "callar_siempre": ("  function partialityNotice(view) {",
                           "  function partialityNotice(view) {\n    return null;"),
        "todo_completo": ("    if (view.truncated === false) {",
                          "    if (true) {"),
        "aviso_sin_cifras": (ORIGINAL_AVISO, 'return "Vista parcial." + ("" +'),
    }

    verde = _corre_sonda(GRAPH_CORE_JS)
    assert verde.returncode == 0, "la sonda no está verde sobre el fichero real: " + (
        verde.stdout + verde.stderr
    )

    for nombre, (viejo, nuevo) in mutantes.items():
        assert viejo in fuente, f"la mutación {nombre} ya no muerde: revísala"
        destino = tmp_path / f"mutante_{nombre}.js"
        destino.write_text(fuente.replace(viejo, nuevo, 1), encoding="utf-8")
        r = _corre_sonda(destino)
        assert r.returncode != 0, (
            f"mutante {nombre}: el indicador de parcialidad está roto y la sonda "
            f"siguió VERDE. Este gate no defiende nada."
        )

    # ...y revertir devuelve el verde (mismo proceso, sin residuos).
    intacto = tmp_path / "revertido.js"
    intacto.write_text(fuente, encoding="utf-8")
    assert _corre_sonda(intacto).returncode == 0
