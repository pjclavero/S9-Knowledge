# -*- coding: utf-8 -*-
"""E2E de navegador del visor de grafo (UX V2).

POR QUE EXISTE ESTE FICHERO
---------------------------
`graph.js` no tenia ni una sola prueba de comportamiento. El revisor lo
demostro de la peor manera posible: renombro seis ids del DOM y la suite entera
siguio verde mientras la pagina quedaba en negro, porque `bindEvents()` revienta
con un `TypeError` antes de dibujar nada; despues inyecto `if (true) return;` al
principio de `bindEvents()` y tampoco fallo nadie. Las 38 aserciones de
`tests/js/graph_core_spec.js` ejercen `graph-core.js`, que es logica pura y no
toca el DOM: son correctas y siguen siendo el sitio adecuado para esa logica,
pero por construccion no pueden ver un id roto.

Aqui se cubre SOLO lo que Node no puede ver: que los eventos estan atados, que
el DOM que la UI busca existe, y que las acciones producen el efecto que la
persona espera en un Chromium de verdad.

INFRAESTRUCTURA
---------------
Se reutiliza la del carril D (`e2e_support.py` + `conftest.py`): mismo servidor
uvicorn real, misma autenticacion real, mismo proveedor `mock` como unico
elemento sustituido. No se monta una segunda infraestructura de navegador.

EL GRAFO SE PINTA EN <canvas>
-----------------------------
No hay un elemento DOM por nodo, asi que "esta centrado" se comprueba leyendo
los pixeles que el navegador dibujo de verdad, igual que hace el carril D. No se
manipula el objeto `vis-network` desde la prueba.
"""
from __future__ import annotations

import json
import re

import pytest

from e2e_support import MOBILE_VIEWPORT, login_as

# Nodo unico de tipo Creature en examples/sample_graph.json, y su color en
# graph-core.js (TYPE_COLORS.Creature). Es el unico dato del fixture que se
# escribe a mano; TODOS los recuentos se leen en vivo de /api/graph, porque lo
# que el backend entrega depende del rol y esta prueba no debe adivinarlo.
UNICO_CREATURE = "Oni de la Montaña Negra"
COLOR_CREATURE = "#e5534b"

MENSAJE_EXPANDIR = "Se muestran los elementos disponibles para tu vista."

ROL = "s9viewer"                              # un usuario normal, no un admin


@pytest.fixture()
def datos(page, viewer):
    """Lo que el backend entrega a ESTE rol. La UI no puede pintar otra cosa."""
    login_as(page, viewer, ROL)
    d = page.request.get(viewer.url("/api/graph?limit=300")).json()
    tipos: dict = {}
    for n in d["nodes"]:
        tipos[n["type"]] = tipos.get(n["type"], 0) + 1
    assert d["nodes"], "el proveedor mock no ha devuelto nada: fixture inservible"
    assert UNICO_CREATURE in [n["label"] for n in d["nodes"]], \
        "el nodo de referencia ya no llega a este rol; elige otro en vez de saltarte la prueba"
    assert tipos.get("Creature") == 1, f"'Creature' ya no aisla un unico nodo: {tipos}"
    return {"total": len(d["nodes"]), "tipos": tipos, "nodes": d["nodes"]}


@pytest.fixture()
def graph_page(page, viewer, datos):
    """Un usuario normal con el grafo cargado y el layout ya estabilizado."""
    page.goto(viewer.url("/graph"))
    page.wait_for_selector("#graph-canvas canvas", timeout=15_000)
    page.wait_for_function(
        "() => document.getElementById('counter-nodes').textContent !== '0'",
        timeout=15_000)
    page.wait_for_timeout(2500)               # estabilizacion del layout fisico
    return page


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

_CENTROIDE_JS = """(color) => {
    const canvas = document.querySelector('#graph-canvas canvas');
    if (!canvas) { return null; }
    const ctx = canvas.getContext('2d');
    const {width, height} = canvas;
    const data = ctx.getImageData(0, 0, width, height).data;
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);
    let sx = 0, sy = 0, n = 0;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        if (Math.abs(data[i] - r) < 12 && Math.abs(data[i+1] - g) < 12
            && Math.abs(data[i+2] - b) < 12 && data[i+3] > 200) {
          sx += x; sy += y; n++;
        }
      }
    }
    if (n === 0) { return null; }
    return {x: sx / n, y: sy / n, w: width, h: height, n: n};
}"""


def centroide(page, color: str):
    """Centro de masa (en pixeles del lienzo) de todo lo pintado de ese color."""
    return page.evaluate(_CENTROIDE_JS, color)


def visibles(page) -> int:
    """Nodos que la UI dice estar mostrando ("N" o "N / M")."""
    texto = page.locator("#counter-nodes").inner_text().strip()
    return int(texto.split("/")[0].strip())


def panel_abierto(page) -> bool:
    clases = page.locator("#side-panel").get_attribute("class") or ""
    return "side-panel-closed" not in clases


# ---------------------------------------------------------------------------
# 1. La pagina viva
# ---------------------------------------------------------------------------

def test_el_grafo_se_dibuja_y_los_eventos_quedan_atados(graph_page, datos):
    """Prueba centinela: si un id del DOM cambia de nombre o `bindEvents()` no
    llega a ejecutarse, `graph.js` lanza y aqui se ve."""
    assert graph_page.page_errors == [], \
        f"excepciones JS al arrancar el visor: {graph_page.page_errors}"
    assert graph_page.locator("#graph-canvas canvas").count() == 1
    assert visibles(graph_page) == datos["total"]
    # Los filtros se construyen desde JS: si no hay casillas, el arranque murio.
    assert graph_page.locator("#entity-type-filters input[type=checkbox]").count() > 0, \
        "los filtros por tipo no se han construido: bindEvents/init no llego al final"
    assert graph_page.locator("#graph-legend li").count() > 0, "la leyenda esta vacia"


# ---------------------------------------------------------------------------
# 2. Buscar localiza Y centra
# ---------------------------------------------------------------------------

def test_buscar_centra_el_nodo_y_abre_su_ficha(graph_page):
    """Intro en el buscador: el nodo queda en el centro del lienzo y su ficha
    se abre. Es exactamente lo que Node no puede comprobar."""
    antes = centroide(graph_page, COLOR_CREATURE)
    assert antes, f"no se encuentra dibujado ningun nodo {COLOR_CREATURE}"

    graph_page.fill("#search-input", "Oni de la Montaña")
    graph_page.press("#search-input", "Enter")
    graph_page.wait_for_timeout(1200)          # la animacion de focus dura 400 ms

    despues = centroide(graph_page, COLOR_CREATURE)
    assert despues, "el nodo buscado ha desaparecido del lienzo"
    dx = abs(despues["x"] - despues["w"] / 2) / despues["w"]
    dy = abs(despues["y"] - despues["h"] / 2) / despues["h"]
    assert dx < 0.12 and dy < 0.12, (
        f"buscar no ha centrado el nodo: centro relativo ({dx:.2f}, {dy:.2f}); "
        f"antes estaba en ({antes['x']:.0f}, {antes['y']:.0f})")

    assert panel_abierto(graph_page), "buscar no ha abierto la ficha del nodo"
    assert UNICO_CREATURE in graph_page.locator("#side-panel").inner_text()


def test_la_lista_de_resultados_lleva_al_nodo(graph_page):
    """Escribir (sin Intro) ofrece resultados pinchables que seleccionan."""
    graph_page.fill("#search-input", "Kimi")
    graph_page.wait_for_timeout(300)
    resultados = graph_page.locator("#search-results button.search-result")
    assert resultados.count() >= 1, "escribir no ha producido resultados de busqueda"
    resultados.first.click()
    graph_page.wait_for_timeout(800)
    assert panel_abierto(graph_page)
    assert "Kimi" in graph_page.locator("#side-panel").inner_text()


# ---------------------------------------------------------------------------
# 3. Filtros
# ---------------------------------------------------------------------------

def test_un_filtro_de_tipo_cambia_el_grafo_visible(graph_page, datos):
    caja = graph_page.locator("#entity-type-filters input[value='Character']")
    assert caja.count() == 1, "no hay filtro para el tipo Character"
    caja.uncheck()
    graph_page.wait_for_timeout(400)
    assert visibles(graph_page) == datos["total"] - datos["tipos"]["Character"], \
        "desmarcar un tipo no ha cambiado lo que se ve"
    caja.check()
    graph_page.wait_for_timeout(400)
    assert visibles(graph_page) == datos["total"], "volver a marcarlo no restaura la vista"


def test_desmarcar_todos_los_tipos_no_equivale_a_marcarlos_todos(graph_page):
    """HALLAZGO H5: antes, ninguna casilla marcada mostraba el grafo entero."""
    cajas = graph_page.locator("#entity-type-filters input[type=checkbox]")
    for i in range(cajas.count()):
        cajas.nth(i).uncheck()
    graph_page.wait_for_timeout(500)
    assert visibles(graph_page) == 0, \
        "con todos los tipos desmarcados el visor sigue mostrando nodos"
    estado = graph_page.locator("#graph-status")
    assert estado.is_visible(), "sin nada visible el usuario se queda sin mensaje"
    assert "Ningún elemento" in estado.inner_text()


def test_quitar_filtros_limpia_tambien_la_busqueda_y_los_nodos_sueltos(graph_page, datos):
    """HALLAZGO H5: "Quitar filtros" se dejaba fuera `hideIsolated` y la busqueda."""
    graph_page.locator("#entity-type-filters input[value='Character']").uncheck()
    graph_page.check("#isolated-toggle")
    graph_page.fill("#search-input", "Kimi")
    graph_page.press("#search-input", "Enter")
    graph_page.wait_for_timeout(600)

    graph_page.click("#clear-filters-btn")
    graph_page.wait_for_timeout(600)

    assert graph_page.input_value("#search-input") == "", "la busqueda sigue puesta"
    assert graph_page.is_checked("#isolated-toggle") is False, \
        "'ocultar nodos sueltos' sigue activo despues de quitar filtros"
    assert visibles(graph_page) == datos["total"]
    assert "q=" not in graph_page.url and "iso=" not in graph_page.url, \
        f"la URL conserva filtros ya quitados: {graph_page.url}"


def test_encajar_y_reiniciar_vista_funcionan(graph_page, datos):
    graph_page.fill("#search-input", "Kimi")
    graph_page.press("#search-input", "Enter")
    graph_page.wait_for_timeout(800)
    assert "q=" in graph_page.url

    graph_page.click("#fit-btn")               # no debe lanzar nada
    graph_page.wait_for_timeout(500)
    graph_page.click("#reset-btn")
    graph_page.wait_for_timeout(800)

    assert graph_page.input_value("#search-input") == ""
    assert visibles(graph_page) == datos["total"]
    assert not panel_abierto(graph_page) or "Pincha un nodo" in \
        graph_page.locator("#side-panel-body").inner_text()
    assert graph_page.page_errors == [], f"encajar/reiniciar lanzo JS: {graph_page.page_errors}"


def test_cerrar_la_ficha_restaura_el_estado(graph_page, datos):
    """En escritorio la ficha es una columna fija y se cierra con Escape: el
    boton de aspa esta `display:none` por encima de 900 px (ver app.css). Por
    eso la prueba usa la via real de cada tamano en vez de fingir que hay un
    boton donde no lo hay."""
    graph_page.fill("#search-input", "Kimi")
    graph_page.press("#search-input", "Enter")
    graph_page.wait_for_timeout(800)
    assert panel_abierto(graph_page)
    assert "Kimi" in graph_page.locator("#side-panel").inner_text()

    graph_page.locator("#graph-canvas").click(position={"x": 5, "y": 5})
    graph_page.keyboard.press("Escape")
    graph_page.wait_for_timeout(400)

    cuerpo = graph_page.locator("#side-panel-body").inner_text()
    assert "Pincha un nodo" in cuerpo, f"cerrar la ficha no restaura el texto guia: {cuerpo[:120]}"
    assert visibles(graph_page) == datos["total"], "cerrar la ficha ha alterado el grafo"
    assert graph_page.page_errors == []


def test_en_movil_la_ficha_se_abre_y_el_aspa_la_cierra(new_page, viewer, datos):
    """En pantalla estrecha la ficha tapa el grafo, asi que SI hay aspa y tiene
    que funcionar: sin ella el grafo queda inaccesible en un movil."""
    movil = new_page(MOBILE_VIEWPORT)
    login_as(movil, viewer, ROL)
    movil.goto(viewer.url("/graph"))
    movil.wait_for_selector("#graph-canvas canvas", timeout=15_000)
    movil.wait_for_timeout(2000)

    movil.fill("#search-input", "Kimi")
    movil.press("#search-input", "Enter")
    movil.wait_for_timeout(800)
    assert panel_abierto(movil), "en movil la ficha no se ha abierto"

    aspa = movil.locator("#side-panel-close")
    assert aspa.is_visible(), "en movil el aspa de cerrar no se ve"
    aspa.click()
    movil.wait_for_timeout(500)
    assert not panel_abierto(movil), "el aspa no cierra la ficha en movil"
    assert movil.page_errors == []


# ---------------------------------------------------------------------------
# 4. La URL
# ---------------------------------------------------------------------------

def test_la_url_restaura_los_filtros_permitidos(page, viewer, datos):
    page.goto(viewer.url("/graph?types=Character&labels=0&iso=1&limit=100"))
    page.wait_for_selector("#graph-canvas canvas", timeout=15_000)
    page.wait_for_timeout(1500)

    assert page.is_checked("#entity-type-filters input[value='Character']")
    assert page.is_checked("#entity-type-filters input[value='Creature']") is False, \
        "la URL pedia solo Character y hay otros tipos marcados"
    assert page.is_checked("#labels-toggle") is False
    assert page.is_checked("#isolated-toggle") is True
    assert page.locator("#limit-select").input_value() == "100"
    assert visibles(page) <= datos["tipos"]["Character"]


def test_los_parametros_sensibles_de_la_url_se_ignoran(page, viewer):
    """Nada de la barra de direcciones puede pedir ver mas de lo que toca."""
    login_as(page, viewer, "s9viewer")
    peticiones = []
    page.on("request", lambda r: peticiones.append(r.url) if "/api/" in r.url else None)

    page.goto(viewer.url(
        "/graph?q=Kimi&view_as=gm&visibility=secret&known_by=n_kimi"
        "&scope=partida7&character_id=99&partida_id=7"))
    page.wait_for_selector("#graph-canvas canvas", timeout=15_000)
    page.wait_for_timeout(1500)

    prohibidos = ["view_as", "visibility", "known_by", "scope", "character_id", "partida_id"]
    for clave in prohibidos:
        assert clave not in page.url, \
            f"el visor ha conservado '{clave}' en la URL: {page.url}"
        for url in peticiones:
            assert clave not in url, f"'{clave}' viajo al backend en {url}"
    assert "q=Kimi" in page.url, "el parametro legitimo se ha perdido por el camino"


# ---------------------------------------------------------------------------
# 5. Errores: el JS no se rompe y no se confunden las causas
# ---------------------------------------------------------------------------

def test_un_error_del_backend_deja_estado_visible_sin_romper_el_js(page, viewer):
    login_as(page, viewer, "s9viewer")
    page.route("**/api/graph*", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": "fuente caida"})))

    page.goto(viewer.url("/graph"))
    page.wait_for_selector("#graph-status:not([hidden])", timeout=15_000)

    texto = page.locator("#graph-status").inner_text()
    assert "no está disponible" in texto, f"mensaje inesperado con el backend caido: {texto}"
    assert "Traceback" not in page.content()
    assert page.page_errors == [], f"el fallo del backend rompio el JS: {page.page_errors}"
    # La pagina sigue siendo una pagina: los controles no desaparecen.
    assert page.locator("#search-input").is_visible()


def test_un_403_dice_falta_de_acceso_y_un_404_no(graph_page, viewer):
    """"Sin acceso" NO se deduce: se lee del status.

    El backend responde 404 tanto si la entidad no existe como si la politica la
    oculta (el proveedor filtrado devuelve `None` en los dos casos), asi que un
    404 jamas puede presentarse como "no tienes acceso": eso confirmaria que
    existe. Solo el 401/403 del guarda habla de acceso.
    """
    graph_page.fill("#search-input", "Kimi")
    graph_page.press("#search-input", "Enter")
    graph_page.wait_for_timeout(800)

    graph_page.route("**/api/entities/*", lambda route: route.fulfill(
        status=404, content_type="application/json",
        body=json.dumps({"detail": {"error": {"code": "ENTITY_NOT_FOUND"}}})))
    graph_page.click("#expand-node-btn")
    graph_page.wait_for_timeout(600)
    nota = graph_page.locator("#expand-note").inner_text()
    assert "No se ha encontrado" in nota, f"404 mal traducido: {nota}"
    assert "acceso" not in nota.lower(), \
        f"un 404 no puede hablar de acceso (revelaria que el elemento existe): {nota}"

    graph_page.unroute("**/api/entities/*")
    graph_page.route("**/api/entities/*", lambda route: route.fulfill(
        status=403, content_type="application/json", body=json.dumps({"detail": "no"})))
    graph_page.click("#expand-node-btn")
    graph_page.wait_for_timeout(600)
    nota = graph_page.locator("#expand-note").inner_text()
    assert "No tienes acceso" in nota, f"403 mal traducido: {nota}"


def test_sin_la_biblioteca_de_dibujo_el_aviso_no_culpa_al_servidor(page, viewer):
    """HALLAZGO H3: si el vendor no carga (integrity que no cuadra), el servidor
    esta vivo. Decir "no se ha podido contactar con el servidor" manda a mirar
    donde no es."""
    login_as(page, viewer, "s9viewer")
    page.route("**/static/js/vendor/vis-network.min.js", lambda route: route.abort())

    page.goto(viewer.url("/graph"))
    page.wait_for_selector("#graph-status:not([hidden])", timeout=15_000)
    texto = page.locator("#graph-status").inner_text()

    assert "componente que dibuja el grafo" in texto, \
        f"sin vendor el visor dice otra cosa: {texto}"
    assert "contactar con el servidor" not in texto, \
        "el fallo del vendor se sigue presentando como un fallo de red"
    # Y el resto de la pagina no se cae con un ReferenceError.
    assert page.locator("#search-input").is_visible()


# ---------------------------------------------------------------------------
# 6. Expandir vecinos: ni un contador de lo que falta
# ---------------------------------------------------------------------------

def test_expandir_vecinos_no_revela_cuantos_faltan(graph_page):
    """REGLA DEL OPERADOR: la UI pide expandir X y pinta lo que el backend da.
    Si recibe menos vecinos de los que existen NO debe indicar cuantos faltan;
    "3 de 7 visibles" revelaria que hay cuatro ocultos."""
    graph_page.fill("#search-input", "Kimi")
    graph_page.press("#search-input", "Enter")
    graph_page.wait_for_timeout(800)

    with graph_page.expect_response(lambda r: "/api/entities/" in r.url) as info:
        graph_page.click("#expand-node-btn")
    assert info.value.status == 200
    graph_page.wait_for_timeout(800)

    nota = graph_page.locator("#expand-note").inner_text().strip()
    assert nota == MENSAJE_EXPANDIR, f"mensaje de expansion inesperado: {nota!r}"
    assert not re.search(r"\d", nota), f"la nota lleva un numero: {nota!r}"

    panel = graph_page.locator("#side-panel").inner_text()
    assert not re.search(r"\d+\s*(de|/)\s*\d+", panel), \
        f"la ficha muestra un recuento del tipo 'N de M': {panel[:200]}"
    for pista in ("oculto", "ocultos", "no visible", "restringid", "vecinos totales"):
        assert pista not in panel.lower(), f"la ficha insinua contenido oculto ({pista})"
    assert graph_page.page_errors == []


# ---------------------------------------------------------------------------
# 7. Coherencia de la ficha completa (bloqueante 3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plantilla", ["/entities/{}", "/entity/{}"])
def test_la_ficha_completa_tampoco_habla_de_visibilidad_ni_de_capa(page, viewer, plantilla):
    """La ficha lateral del grafo dejo de mostrar `visibility`/`knowledge_layer`,
    pero se llega a ESTAS paginas desde su boton "Ficha completa": si aqui
    siguieran, la decision seria una incoherencia en vez de un principio."""
    # Se entra como ADMIN a proposito: es el unico rol al que el backend le
    # sirve el nodo `secret`, o sea el unico caso en el que la plantilla TIENE
    # el dato y podria pintarlo. A un viewer el backend le da 404 y la prueba
    # pasaria sin comprobar nada.
    login_as(page, viewer, "s9admin")
    page.goto(viewer.url(plantilla.format("n_culto_pozo_viejo")))   # visibility=secret
    page.wait_for_load_state("networkidle")
    texto = page.locator("main").inner_text()

    assert "Culto del Pozo Viejo" in texto, "la ficha no ha cargado"
    for prohibido in ("Secreto", "Narrador", "Jugador", "Referencia"):
        assert prohibido not in texto, \
            f"la ficha completa sigue mostrando la visibilidad ({prohibido}): {texto[:300]}"
    assert "Capa:" not in texto and "Capa de conocimiento" not in texto, \
        "la ficha completa sigue mostrando la capa de conocimiento"
    # Lo que SI debe seguir estando: el estado de revision es informacion de
    # calidad del dato, no de autorizacion.
    assert "revisión" in texto.lower() or "Revisión" in texto
