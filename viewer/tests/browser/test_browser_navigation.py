# -*- coding: utf-8 -*-
"""E2E de navegador: recorrido de producto.

Grafo, busqueda, seleccion, ficha de entidad, Fuentes, Jobs, Reviews, estados
sin datos y errores. Todo con un usuario real de cada rol y contra el servidor
real; el unico elemento sustituido es el origen de datos del grafo (proveedor
`mock`, que es del propio producto).
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote, quote_plus

import pytest

from e2e_support import fetch_status, login_as

# Una entidad que existe de verdad en examples/sample_graph.json.
ENTIDAD_CONOCIDA = "Agasha Tamori"


@pytest.fixture()
def admin_page(page, viewer):
    """Sesion de admin: el rol que ve todas las secciones."""
    login_as(page, viewer, "s9admin")
    return page


# ---------------------------------------------------------------------------
# Navegacion principal
# ---------------------------------------------------------------------------

def test_la_navegacion_lleva_a_todas_sus_secciones(admin_page, viewer):
    """Cada enlace de la barra abre una pagina de verdad, sin 4xx/5xx."""
    nav = admin_page.locator("header.topbar nav a")
    hrefs = [nav.nth(i).get_attribute("href") for i in range(nav.count())]
    assert hrefs, "la barra de navegacion no tiene enlaces"

    for href in hrefs:
        status = fetch_status(admin_page, viewer, href)
        assert status == 200, f"el enlace de la nav {href} devolvio {status}"
        assert "/login" not in admin_page.url, f"{href} expulso la sesion"


def test_el_titulo_de_cada_pagina_la_identifica(admin_page, viewer):
    """Sin <title> distinto, el historial y las pestanas son inservibles."""
    titulos = {}
    for path in ["/", "/entities", "/graph", "/jobs", "/status", "/sources", "/reviews"]:
        fetch_status(admin_page, viewer, path)
        titulos[path] = admin_page.title()
    assert all(titulos.values()), f"hay paginas sin titulo: {titulos}"
    assert len(set(titulos.values())) == len(titulos), \
        f"hay paginas que comparten titulo: {titulos}"


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------

def test_el_grafo_se_dibuja(admin_page, viewer):
    admin_page.goto(viewer.url("/graph"))
    admin_page.wait_for_load_state("networkidle")
    admin_page.wait_for_selector("#graph-canvas canvas", timeout=10_000)
    assert admin_page.locator("#graph-canvas canvas").count() == 1
    assert admin_page.page_errors == [], f"excepciones JS al dibujar el grafo: {admin_page.page_errors}"


# ---------------------------------------------------------------------------
# Busqueda del grafo: QUE puede encontrar, no COMO lo busca
# ---------------------------------------------------------------------------
#
# POR QUE SE REESCRIBIERON ESTAS PRUEBAS
# --------------------------------------
# Las dos versiones anteriores (`test_la_busqueda_del_grafo_filtra_de_verdad` y
# `test_seleccionar_un_nodo_abre_su_ficha_lateral`) exigian que teclear en el
# buscador disparase una peticion `/api/graph?...&q=...`. Eso NO era un requisito
# de producto: era la implementacion de entonces. La UX V2 del grafo busca en el
# cliente, sobre lo que el backend ya entrego, y aquellas pruebas se rompian sin
# que hubiera ningun defecto.
#
# Se congela el RESULTADO DE SEGURIDAD, no la implementacion:
#
#     «la busqueda solo puede encontrar lo que ya existe en la vista autorizada»
#
# Deliberadamente NO se afirma «buscar no hace ninguna peticion». Si manana se
# decide una busqueda remota AUTORIZADA, estas tres pruebas deben seguir valiendo
# tal cual: solo hablan de lo que la persona encuentra, no de por que canal.

# El nodo `secret` del grafo de ejemplo. El backend NO lo entrega a un `viewer`
# (9 nodos frente a los 11 del admin) y le responde 404 a su id. Ambas cosas se
# comprueban dentro de la prueba, no se dan por supuestas.
SECRETO_NOMBRE = "Culto del Pozo Viejo"
SECRETO_ID = "n_culto_pozo_viejo"

# Nodo unico de tipo Creature (color propio en graph-core.js): permite localizar
# en el <canvas> exactamente un nodo por su color. Lo ve cualquier rol.
NODO_VISIBLE = "Oni de la Montaña Negra"
COLOR_CREATURE = "#e5534b"

INEXISTENTE_NOMBRE = "Zzyzx Fantasmagorico Inexistente"
INEXISTENTE_ID = "n_zzyzx_fantasmagorico_inexistente"

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


# Huella del lienzo. Se resume en un entero (FNV-1a sobre TODOS los canales de
# TODOS los pixeles) mas el numero de pixeles no transparentes: cualquier
# diferencia de dibujo —un nodo mas, un resaltado, un encuadre distinto— cambia
# el resumen. Comparar dataURL completas seria equivalente pero mucho mas caro
# de mover entre navegador y prueba.
_HUELLA_CANVAS_JS = """() => {
    const c = document.querySelector('#graph-canvas canvas');
    if (!c) { return null; }
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let h = 0x811c9dc5, opacos = 0;
    for (let i = 0; i < d.length; i += 4) {
      h = ((h ^ d[i]) * 16777619) >>> 0;
      h = ((h ^ d[i + 1]) * 16777619) >>> 0;
      h = ((h ^ d[i + 2]) * 16777619) >>> 0;
      h = ((h ^ d[i + 3]) * 16777619) >>> 0;
      if (d[i + 3] > 0) { opacos++; }
    }
    return c.width + 'x' + c.height + ':' + h.toString(16) + ':' + opacos;
}"""


def _esperar_lienzo_quieto(page, timeout_ms: int = 20_000) -> str:
    """Espera a que la FISICA se pare y devuelve la huella del lienzo.

    POR QUE ESTO Y NO UN `wait_for_timeout` GENEROSO
    ------------------------------------------------
    El grafo se dibuja con vis-network, que mueve los nodos solo hasta que el
    motor de fisicas converge. Comparar dos capturas con el grafo todavia en
    movimiento produce una prueba que falla al azar, y una prueba que falla al
    azar es peor que no tenerla: se acaba ignorando.

    Se esperan DOS cosas, y las dos hacen falta:
      1. Que el producto declare la estabilizacion (evento `stabilized` de
         vis-network, expuesto en `S9KGraphView.isStabilized`). Es la senal
         autoritativa del motor de fisicas.
      2. Que dos capturas consecutivas del lienzo sean identicas. Cubre lo que
         el evento no cubre: las animaciones de `focus`/`fit`, que mueven la
         camara DESPUES de que la fisica se haya parado.
    """
    page.wait_for_function(
        "() => window.S9KGraphView && window.S9KGraphView.isStabilized()",
        timeout=timeout_ms)
    anterior = None
    intentos = max(4, timeout_ms // 250)
    for _ in range(intentos):
        actual = page.evaluate(_HUELLA_CANVAS_JS)
        assert actual is not None, "no hay lienzo del grafo que observar"
        if actual == anterior:
            return actual
        anterior = actual
        page.wait_for_timeout(250)
    raise AssertionError(
        "el lienzo del grafo no se queda quieto: comparar huellas seria un "
        "sorteo. Ultimas capturas distintas entre si.")


def _abrir_grafo(page, viewer):
    """Grafo cargado y con el layout fisico ya estabilizado."""
    page.goto(viewer.url("/graph"))
    page.wait_for_selector("#graph-canvas canvas", timeout=15_000)
    page.wait_for_function(
        "() => document.getElementById('counter-nodes').textContent !== '0'",
        timeout=15_000)
    _esperar_lienzo_quieto(page)
    return page


def _buscar(page, texto):
    """Teclea y pulsa Intro. No se afirma nada sobre peticiones de red."""
    page.fill("#search-input", texto)
    page.press("#search-input", "Enter")
    _esperar_lienzo_quieto(page)


def _resultados(page) -> list:
    """Etiquetas de los resultados pinchables que ofrece el buscador."""
    items = page.locator("#search-results button.search-result")
    return [items.nth(i).inner_text() for i in range(items.count())]


def _variantes(termino: str) -> list:
    """Las formas en que el termino buscado puede aparecer escrito en la UI."""
    formas = {
        termino,
        termino.lower(),
        quote(termino, safe=""),
        quote(termino, safe="").lower(),
        quote_plus(termino),
        unicodedata.normalize("NFD", termino).encode("ascii", "ignore").decode(),
    }
    return sorted((f for f in formas if f), key=len, reverse=True)


def _sin_el_termino(valor, termino: str):
    """Sustituye el texto buscado por un marcador, en cualquier profundidad.

    POR QUE HACE FALTA NORMALIZAR
    -----------------------------
    Dos busquedas distintas se distinguen siempre en una cosa trivial: el texto
    que se ha tecleado, que viaja al campo, a la URL (`?q=…`) y a cualquier
    mensaje que lo cite. Eso no es un canal lateral, es la busqueda haciendo su
    trabajo; exigir igualdad literal haria imposible comparar nada.

    Lo que SI es un canal lateral es cualquier diferencia que quede DESPUES de
    borrar el termino: un parametro de mas en la URL, un contador que cambia,
    un mensaje que solo aparece para un nombre concreto. Por eso se compara la
    huella con el termino sustituido por `<TERMINO>`: lo que sobreviva a esa
    sustitucion y siga siendo distinto solo puede venir de los DATOS, no de la
    consulta.
    """
    if isinstance(valor, str):
        out = valor
        for forma in _variantes(termino):
            out = re.sub(re.escape(forma), "<TERMINO>", out, flags=re.IGNORECASE)
        return out
    if isinstance(valor, list):
        return [_sin_el_termino(v, termino) for v in valor]
    if isinstance(valor, dict):
        return {k: _sin_el_termino(v, termino) for k, v in valor.items()}
    return valor


def _huella_de_busqueda(page, termino: str) -> dict:
    """Los DIECISIETE canales observables que esta huella cubre.

    Si un nodo no autorizado y un nombre inexistente producen la misma huella,
    esos diecisiete canales no permiten distinguirlos. Eso es lo que la prueba
    demuestra; ni mas, ni menos.

    QUE CANALES ENTRAN
    ------------------
    La version anterior de esta funcion miraba cuatro cosas (la lista de
    resultados, el contador de nodos y si la ficha estaba abierta) y por eso no
    valia: un revisor escribio fugas en el contador de ARISTAS, en el mensaje
    de `#graph-status` —visible y anunciado por `aria-live`— y en la URL, y la
    prueba siguio verde. La lista cubierta hoy, enumerada sin adornos:

       1. `resultados`         lista de resultados pinchables
       2. `texto_lista`        texto de `#search-results`
       3. `lista_oculta`       visibilidad de `#search-results`
       4. `contador_nodos`     `#counter-nodes`
       5. `contador_aristas`   `#counter-edges`
       6. `estado_texto`       texto de `#graph-status` (anunciado por aria-live)
       7. `estado_visible`     visibilidad de `#graph-status`
       8. `ficha_texto`        texto de la ficha lateral
       9. `ficha_abierta`      si la ficha esta desplegada
      10. `ficha_aria`         `aria-label` + `aria-hidden` de la ficha lateral
      11. `titulo`             `document.title`
      12. `contadores_filtro`  todos los `.filter-count` del panel de filtros
      13. `leyenda`            texto de cada fila de `#graph-legend`
      14. `url`                la URL COMPLETA
      15. `seleccion`          seleccion REAL de vis-network (via S9KGraphView)
      16. `encuadre`           zoom y centro del lienzo (via S9KGraphView)
      17. `lienzo`             el `<canvas>` pixel a pixel, con la fisica parada

    QUE NO ENTRA, NOMINALMENTE
    --------------------------
    Esta lista es la parte importante del docstring. Una version anterior decia
    «todo el estado observable»; era falso, y una afirmacion falsa en una prueba
    de seguridad es peor que una limitacion escrita.

      a) DETALLES DE IMPLEMENTACION, a proposito: si hubo peticion de red, que
         funcion se llamo, en que orden se pintaron los filtros. La prueba habla
         de lo que una persona percibe, no de como esta hecho el visor.

      b) EL LIMITE INTRINSECO DE LA TECNICA — el mas sutil, y el que no se puede
         cerrar sin romper la prueba entera. Antes de comparar, `_sin_el_termino`
         borra el termino buscado en todas sus formas (tal cual, minusculas,
         percent-encoded, sin acentos). Eso es necesario —dos busquedas siempre
         difieren en el texto tecleado— pero tiene un precio exacto: BORRA
         TAMBIEN CUALQUIER FUGA QUE SOLO SE DISTINGA POR COMO SE RENDERIZA EL
         TERMINO BUSCADO. Si el visor mostrase el nombre CANONICO del nodo
         autorizado alli donde para un termino inventado repite lo tecleado
         —distinta capitalizacion, acentos restituidos, forma canonica—, la
         sustitucion tapa la diferencia y la huella sale igual. No es un
         descuido: es el precio de poder comparar dos busquedas distintas. Un
         canal de ese tipo necesita una prueba dedicada que compare la forma
         literal, no esta.

      c) Todo canal fuera del `<body>` de `/graph`: cabeceras HTTP, cookies,
         `localStorage`, tiempos de respuesta. La promesa es sobre la VISTA
         ORDINARIA, no sobre un atacante con herramientas de red.

    Los cuatro canales que el revisor encontro escapados —`.filter-count`, fila
    extra en la leyenda, `document.title` y el `aria-label` de la ficha— SI se
    han incorporado (10-13). Son lecturas de DOM baratas y deterministas: no
    dependen del termino buscado, asi que no introducen intermitencia, y los
    tres primeros se derivan de los datos cargados, que es justo por donde
    entraria una fuga de autorizacion.
    """
    panel = page.locator("#side-panel")
    estado = page.locator("#graph-status")
    filtros = page.locator(".filter-count")
    leyenda = page.locator("#graph-legend li")
    huella = {
        "resultados": _resultados(page),
        "texto_lista": page.locator("#search-results").inner_text().strip(),
        "lista_oculta": page.locator("#search-results").is_hidden(),
        "contador_nodos": page.locator("#counter-nodes").inner_text().strip(),
        "contador_aristas": page.locator("#counter-edges").inner_text().strip(),
        "estado_texto": estado.inner_text().strip(),
        "estado_visible": estado.is_visible(),
        "ficha_texto": panel.inner_text().strip(),
        "ficha_abierta": "side-panel-closed" not in (panel.get_attribute("class") or ""),
        "ficha_aria": [panel.get_attribute("aria-label"), panel.get_attribute("aria-hidden")],
        "titulo": page.title(),
        "contadores_filtro": [filtros.nth(i).inner_text().strip()
                              for i in range(filtros.count())],
        "leyenda": [leyenda.nth(i).inner_text().strip()
                    for i in range(leyenda.count())],
        "url": page.url,
        "seleccion": page.evaluate("() => window.S9KGraphView.selection()"),
        "encuadre": page.evaluate(
            "() => { const v = window.S9KGraphView.viewport();"
            "  return v && {scale: Math.round(v.scale * 1000),"
            "               x: Math.round(v.x), y: Math.round(v.y)}; }"),
        "lienzo": _esperar_lienzo_quieto(page),
    }
    return _sin_el_termino(huella, termino)


def test_la_busqueda_encuentra_centra_y_resalta_un_nodo_visible(page, viewer):
    """CASO 1. Un nodo que el backend SI entrego a este rol se encuentra,
    se centra en el lienzo y queda resaltado (seleccionado y con su ficha)."""
    login_as(page, viewer, "s9viewer")
    entregados = [n["label"] for n in
                  page.request.get(viewer.url("/api/graph?limit=300")).json()["nodes"]]
    assert NODO_VISIBLE in entregados, \
        f"el nodo de referencia ya no llega a este rol ({entregados}); elige otro"

    _abrir_grafo(page, viewer)
    antes = page.evaluate(_CENTROIDE_JS, COLOR_CREATURE)
    assert antes, "el nodo de referencia no esta dibujado en el lienzo"

    _buscar(page, NODO_VISIBLE)

    # Lo encuentra: aparece como resultado pinchable.
    assert any(NODO_VISIBLE in r for r in _resultados(page)), \
        f"la busqueda no ofrece el nodo visible: {_resultados(page)}"

    # Lo centra: el nodo (unico de su color) queda en el centro del lienzo.
    despues = page.evaluate(_CENTROIDE_JS, COLOR_CREATURE)
    assert despues, "el nodo buscado ha desaparecido del lienzo"
    dx = abs(despues["x"] - despues["w"] / 2) / despues["w"]
    dy = abs(despues["y"] - despues["h"] / 2) / despues["h"]
    assert dx < 0.12 and dy < 0.12, (
        f"buscar no centro el nodo: centro relativo ({dx:.2f}, {dy:.2f}); "
        f"antes estaba en ({antes['x']:.0f}, {antes['y']:.0f})")

    # Lo resalta: se comprueba la seleccion REAL de vis-network (ventana de
    # observacion de solo lectura) ademas de su reflejo en la ficha lateral.
    # Con solo la ficha, un visor que abriese el panel sin seleccionar nada en
    # el lienzo pasaria por bueno.
    seleccion = page.evaluate("() => window.S9KGraphView.selection()")
    assert seleccion and len(seleccion["nodes"]) == 1, \
        f"buscar no dejo el nodo seleccionado en el lienzo: {seleccion}"

    panel = page.locator("#side-panel")
    assert "side-panel-closed" not in (panel.get_attribute("class") or ""), \
        "buscar no abrio la ficha del nodo"
    assert NODO_VISIBLE in panel.inner_text(), \
        f"la ficha no describe el nodo buscado: {panel.inner_text()[:200]}"
    assert panel.locator("a[href^='/entities/'], a[href^='/entity/']").count() >= 1, \
        "la ficha lateral no ofrece el enlace a la ficha completa"
    assert page.page_errors == [], f"excepciones JS al buscar: {page.page_errors}"


@pytest.mark.parametrize("termino", [INEXISTENTE_NOMBRE, INEXISTENTE_ID])
def test_la_busqueda_de_algo_inexistente_no_encuentra_nada(page, viewer, termino):
    """CASO 2. Un nombre o un id que no existe en ninguna parte: cero
    resultados, mensaje de vacio y ninguna ficha abierta."""
    login_as(page, viewer, "s9viewer")
    _abrir_grafo(page, viewer)
    _buscar(page, termino)

    huella = _huella_de_busqueda(page, termino)
    assert huella["resultados"] == [], \
        f"«{termino}» no existe y sin embargo produjo resultados: {huella['resultados']}"
    assert "Sin coincidencias" in huella["texto_lista"], \
        f"no hay mensaje de vacio: {huella['texto_lista']!r}"
    assert huella["seleccion"] == {"nodes": [], "edges": []}, \
        f"una busqueda vacia dejo algo seleccionado: {huella['seleccion']}"
    assert "Pincha un nodo" in huella["ficha_texto"], \
        f"una busqueda vacia abrio la ficha de algo: {huella['ficha_texto'][:200]}"
    assert page.page_errors == [], f"excepciones JS al buscar: {page.page_errors}"


def test_un_nodo_no_autorizado_es_indistinguible_de_uno_inexistente(new_page, viewer):
    """CASO 3 — el resultado de seguridad que hay que congelar.

    Un `viewer` busca el nombre EXACTO y el id EXACTO de un nodo `secret` que el
    backend no le ha entregado. Debe obtener exactamente lo mismo que al buscar
    algo que no existe: ni resultados, ni contador distinto, ni hueco, ni un
    mensaje diferente. Desde la vista ordinaria, «no autorizado» y «no existe»
    tienen que ser el mismo hecho observable.

    La prueba NO puede pasar por vacio: primero se comprueba, con un admin, que
    el nodo EXISTE de verdad y que la misma busqueda SI lo encuentra. Si alguien
    borrase el nodo del fixture, esta prueba enrojece en vez de aprobar.
    """
    # --- Control positivo: para el admin el nodo existe y la busqueda lo halla.
    admin = new_page()
    login_as(admin, viewer, "s9admin")
    del_admin = admin.request.get(viewer.url("/api/graph?limit=300")).json()["nodes"]
    labels_admin = [n["label"] for n in del_admin]
    assert SECRETO_NOMBRE in labels_admin, (
        f"el nodo secreto ya no esta en el fixture ({labels_admin}): la prueba "
        "aprobaria por vacio, asi que falla a proposito")
    assert admin.request.get(viewer.url(f"/api/entity/{SECRETO_ID}")).status == 200, \
        "el id secreto no resuelve ni para el admin: fixture inservible"
    entregado = [n for n in del_admin if n["label"] == SECRETO_NOMBRE][0]
    assert entregado.get("entity_id") == SECRETO_ID, (
        f"el backend no entrega el identificador estable del nodo secreto "
        f"({entregado.get('entity_id')!r}): el caso «buscar por id» seria vacuo")

    _abrir_grafo(admin, viewer)
    # Por NOMBRE y por IDENTIFICADOR ESTABLE. El segundo es la mitad que antes
    # no existia: el id no estaba en el indice, asi que «buscar por id» no
    # encontraba nada ni siquiera para el admin y la prueba de mas abajo se
    # cumplia por vacuidad, no por autorizacion.
    for termino in (SECRETO_NOMBRE, SECRETO_ID):
        _buscar(admin, termino)
        assert any(SECRETO_NOMBRE in r for r in _resultados(admin)), (
            f"ni siquiera el admin encuentra el nodo secreto buscando «{termino}» "
            f"({_resultados(admin)}): sin control positivo el resto de la prueba "
            "no demuestra nada")

    # --- El rol sin autorizacion: el backend no le entrega ese nodo.
    victima = new_page()
    login_as(victima, viewer, "s9viewer")
    del_viewer = victima.request.get(viewer.url("/api/graph?limit=300")).json()["nodes"]
    labels_viewer = [n["label"] for n in del_viewer]
    assert SECRETO_NOMBRE not in labels_viewer, (
        "el backend esta entregando el nodo secreto a un viewer: el defecto es "
        "de autorizacion, no de la busqueda")
    assert len(labels_viewer) < len(labels_admin), \
        "el viewer recibe tantos nodos como el admin: no hay nada que ocultar"
    assert victima.request.get(viewer.url(f"/api/entity/{SECRETO_ID}")).status == 404, \
        "el id secreto no da 404 al viewer"

    _abrir_grafo(victima, viewer)

    # Cada caso se compara con SU referencia de vacio: un nombre inventado
    # frente al nombre secreto, y un id inventado frente al id secreto.
    parejas = ((SECRETO_NOMBRE, INEXISTENTE_NOMBRE), (SECRETO_ID, INEXISTENTE_ID))
    for secreto, inventado in parejas:
        _buscar(victima, inventado)
        referencia = _huella_de_busqueda(victima, inventado)
        assert referencia["resultados"] == [], "la referencia de vacio no esta vacia"

        _buscar(victima, secreto)
        huella = _huella_de_busqueda(victima, secreto)
        assert huella["resultados"] == [], \
            f"buscar «{secreto}» revela el nodo no autorizado: {huella['resultados']}"

        # Comparacion canal por canal: si algo se distingue, el mensaje dice
        # CUAL, que es lo que hace util un fallo de este tipo.
        distintos = {k: (huella[k], referencia[k])
                     for k in huella if huella[k] != referencia[k]}
        assert not distintos, (
            f"buscar «{secreto}» se distingue de buscar «{inventado}».\n"
            + "\n".join(f"  · {k}: no autorizado={v[0]!r} / inexistente={v[1]!r}"
                        for k, v in distintos.items()))

    # Y en ninguna parte del DOM aparece el nodo ni su id.
    contenido = victima.content()
    assert SECRETO_NOMBRE not in contenido, "el nombre del nodo secreto esta en el DOM"
    assert SECRETO_ID not in contenido, "el id del nodo secreto esta en el DOM"
    assert victima.page_errors == [], f"excepciones JS: {victima.page_errors}"


def test_desde_la_ficha_lateral_se_llega_a_la_ficha_completa(admin_page, viewer):
    admin_page.goto(viewer.url("/entities"))
    admin_page.wait_for_load_state("networkidle")
    enlace = admin_page.locator("table a[href^='/entity/']").first
    nombre = enlace.inner_text().strip()
    enlace.click()
    admin_page.wait_for_load_state("networkidle")
    assert "/entity/" in admin_page.url, f"no se abrio la ficha: {admin_page.url}"
    assert nombre in admin_page.content()


# ---------------------------------------------------------------------------
# Busqueda y ficha en el listado de entidades
# ---------------------------------------------------------------------------

def test_buscar_seleccionar_y_abrir_el_detalle(admin_page, viewer):
    """El recorrido completo: buscar -> resultado -> seleccionar -> detalle."""
    admin_page.goto(viewer.url("/entities"))
    admin_page.wait_for_load_state("networkidle")
    admin_page.fill("input[name='q']", ENTIDAD_CONOCIDA)
    admin_page.click("form[action='/entities'] button[type='submit']")
    admin_page.wait_for_load_state("networkidle")

    filas = admin_page.locator("table tbody tr")
    assert filas.count() >= 1, "la busqueda no devolvio ningun resultado"
    assert ENTIDAD_CONOCIDA in filas.first.inner_text()

    filas.first.locator("a").first.click()
    admin_page.wait_for_load_state("networkidle")
    assert ENTIDAD_CONOCIDA in admin_page.content(), "la ficha no muestra la entidad"


def test_estado_sin_datos_en_el_listado_de_entidades(admin_page, viewer):
    """Buscar algo inexistente da un mensaje, no una tabla vacia ni un error."""
    admin_page.goto(viewer.url("/entities?q=zzz-esto-no-existe-zzz"))
    admin_page.wait_for_load_state("networkidle")
    texto = admin_page.locator("main").inner_text()
    assert "Sin resultados" in texto, f"no hay mensaje de vacio: {texto[:300]}"
    assert admin_page.locator("table tbody tr").count() == 0


# ---------------------------------------------------------------------------
# Fuentes, Jobs y Reviews
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,marca", [
    ("/sources", "Fuentes"),
    ("/jobs", "Jobs"),
    ("/reviews", "Reviews"),
    ("/status", "Estado"),
])
def test_las_secciones_de_reviewer_cargan_para_un_admin(admin_page, viewer, path, marca):
    status = fetch_status(admin_page, viewer, path)
    assert status == 200, f"{path} devolvio {status}"
    assert marca.lower() in admin_page.title().lower(), \
        f"{path} no se identifica como «{marca}»: {admin_page.title()}"
    assert admin_page.page_errors == [], f"{path} lanzo excepciones JS: {admin_page.page_errors}"


def test_jobs_carga_haya_o_no_base_de_datos(admin_page, viewer):
    """La pagina de Jobs debe cargar (200) en los dos escenarios posibles.

    En laboratorio no suele haber `jobs.db`, que es el fallo controlado que
    interesa: la pagina debe cargar y DECIRLO, no dar un 500. Pero si el entorno
    si la tiene, la exigencia no desaparece, solo cambia: debe pintar la cola.

    Sin `skip`: el job de CI `test-login-browser` falla ante cualquier `skipped`,
    asi que un salto condicional por una circunstancia del entorno pondria el job
    rojo sin que hubiera ningun defecto. Se comprueba una cosa u otra segun el
    escenario, y en ambos se comprueba algo.
    """
    resp = admin_page.request.get(viewer.url("/api/jobs"))
    assert resp.status == 200, f"/api/jobs devolvio {resp.status}"
    hay_jobs_db = bool(resp.json().get("ok"))

    status = fetch_status(admin_page, viewer, "/jobs")
    assert status == 200, f"/jobs devolvio {status} (hay jobs.db: {hay_jobs_db})"
    texto = admin_page.locator("body").inner_text().lower()

    if hay_jobs_db:
        # Escenario nominal: la cola existe y la pagina la presenta.
        assert "jobs" in texto, f"/jobs con base de datos no pinta la cola: {texto[:300]}"
        assert admin_page.page_errors == [], \
            f"/jobs lanzo excepciones JS: {admin_page.page_errors}"
    else:
        # Escenario degradado: sin base de datos, la pagina lo dice.
        assert any(p in texto for p in ("no disponible", "not_found", "error", "sin ")), \
            f"/jobs no informa del estado degradado: {texto[:300]}"


def test_reviews_sin_fuentes_no_finge_datos(admin_page, viewer):
    fetch_status(admin_page, viewer, "/reviews")
    assert admin_page.locator("table tbody tr, .source-card").count() >= 0
    assert admin_page.page_errors == []


# ---------------------------------------------------------------------------
# 404 y errores
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/entities/no-existe-esta-entidad",
    "/entity/no-existe-esta-entidad",
    "/reviews/no-existe-esta-fuente",
    "/jobs/no-existe-este-job",
    "/ruta-que-no-existe",
])
def test_las_rutas_inexistentes_no_dan_500_ni_filtran_trazas(admin_page, viewer, path):
    status = fetch_status(admin_page, viewer, path)
    assert status < 500, f"{path} devolvio {status}"
    cuerpo = admin_page.content()
    assert "Traceback" not in cuerpo, f"{path} filtro una traza de Python"
    assert "sqlite3" not in cuerpo.lower()


def test_el_404_de_la_ficha_de_entidad_es_una_pagina_del_visor(admin_page, viewer):
    """/entities/{id} inexistente devuelve la pagina de error del producto."""
    status = fetch_status(admin_page, viewer, "/entities/no-existe-esta-entidad")
    assert status == 404
    assert "Error 404" in admin_page.content()
    assert admin_page.locator("header.topbar").count() == 1, \
        "la pagina de error pierde la navegacion del visor"


@pytest.mark.xfail(
    strict=True,
    reason="A-01: /entity/{id} lanza HTTPException sin manejador HTML y "
           "FastAPI responde {\"detail\": ...} en JSON crudo")
def test_el_404_de_entity_es_una_pagina_html_del_visor(admin_page, viewer):
    """HALLAZGO A-01 (defecto de aplicacion, fuera de mi zona: NO lo corrijo).

    Escrita como la prueba CORRECTA —el 404 debe ser HTML con navegacion— y
    marcada como fallo esperado. Antes afirmaba lo contrario (`assert
    es_json_crudo`) y se contaba en verde, de modo que arreglar el defecto habria
    enrojecido la suite: se castigaba el arreglo. Ahora el arreglo produce un
    XPASS y `strict` obliga a quitar la marca, que es el aviso correcto.

    Contraste: `/entities/{id}` si usa `error.html` (ver la prueba de arriba); la
    inconsistencia es del producto.
    """
    fetch_status(admin_page, viewer, "/entity/no-existe-esta-entidad")
    cuerpo = admin_page.content()
    assert '{"detail"' not in cuerpo, \
        "el 404 de /entity/{id} se sirve como JSON crudo, no como pagina de error"
    assert "topbar" in cuerpo, \
        "el 404 de /entity/{id} no conserva la navegacion del visor"


@pytest.mark.xfail(
    strict=True,
    reason="A-02: require_admin lanza HTTPException y el 403 de /admin sale en JSON crudo")
def test_el_403_de_admin_es_una_pagina_html_del_visor(new_page, viewer):
    """HALLAZGO A-02: mismo defecto en el 403 de admin (ver A-01).

    `_require_reviewer_or_redirect` si pinta `auth/403.html`; `require_admin`
    lanza HTTPException y el usuario ve JSON. Igual que A-01, se escribe la
    prueba correcta y se marca, en vez de consagrar el defecto en verde.
    """
    pg = new_page()
    login_as(pg, viewer, "s9viewer")
    status = fetch_status(pg, viewer, "/admin/users")
    assert status == 403, f"/admin/users como viewer devolvio {status}"
    cuerpo = pg.content()
    assert '{"detail"' not in cuerpo, \
        "el 403 de /admin se sirve como JSON crudo, no como pagina de error"
    assert "topbar" in cuerpo, \
        "el 403 de /admin no conserva la navegacion del visor"


def test_el_403_de_reviewer_si_es_una_pagina_del_visor(new_page, viewer):
    """Contraste con A-02: aqui el producto ya hace lo correcto."""
    pg = new_page()
    login_as(pg, viewer, "s9viewer")
    status = fetch_status(pg, viewer, "/reviews")
    assert status == 403
    assert "403" in pg.content()
    assert pg.locator("header.topbar").count() == 1


# ---------------------------------------------------------------------------
# Consola limpia
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/entities", "/graph", "/jobs", "/status",
                                  "/sources", "/reviews", "/admin/users"])
def test_ninguna_pagina_lanza_errores_js_graves(admin_page, viewer, path):
    fetch_status(admin_page, viewer, path)
    admin_page.wait_for_timeout(1200)
    assert admin_page.page_errors == [], f"{path} lanzo excepciones JS: {admin_page.page_errors}"
    assert admin_page.console_errors == [], f"{path} escribio errores en consola: {admin_page.console_errors}"
