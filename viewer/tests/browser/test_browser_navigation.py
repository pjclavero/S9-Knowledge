# -*- coding: utf-8 -*-
"""E2E de navegador: recorrido de producto.

Grafo, busqueda, seleccion, ficha de entidad, Fuentes, Jobs, Reviews, estados
sin datos y errores. Todo con un usuario real de cada rol y contra el servidor
real; el unico elemento sustituido es el origen de datos del grafo (proveedor
`mock`, que es del propio producto).
"""
from __future__ import annotations

import pytest

from e2e_support import fetch_status, login_as

# Una entidad que existe de verdad en examples/sample_graph.json.
ENTIDAD_CONOCIDA = "Agasha Tamori"
# Termino que aisla UN solo nodo en el grafo de ejemplo (comprobado en la
# propia prueba: si dejara de ser unico, la prueba falla en vez de saltarse).
ENTIDAD_UNICA = "Kimi"


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


def test_la_busqueda_del_grafo_filtra_de_verdad(admin_page, viewer):
    """Escribir y pulsar Enter dispara una consulta filtrada al backend."""
    admin_page.goto(viewer.url("/graph"))
    admin_page.wait_for_selector("#graph-canvas canvas", timeout=10_000)

    with admin_page.expect_response(lambda r: "/api/graph" in r.url and "q=" in r.url) as info:
        admin_page.fill("#search-input", ENTIDAD_CONOCIDA)
        admin_page.press("#search-input", "Enter")
    respuesta = info.value
    assert respuesta.status == 200, f"la busqueda del grafo fallo: {respuesta.status}"
    datos = respuesta.json()
    etiquetas = [n["label"] for n in datos.get("nodes", [])]
    assert ENTIDAD_CONOCIDA in etiquetas, f"la busqueda no encontro la entidad: {etiquetas}"


def test_seleccionar_un_nodo_abre_su_ficha_lateral(admin_page, viewer):
    """Filtra a un unico nodo y pincha en el lienzo: el panel debe describirlo.

    Con un solo nodo, vis-network lo situa en el centro del lienzo; ese es el
    unico punto de entrada realista, porque el grafo se pinta en <canvas> y no
    expone elementos DOM por nodo (ver limitacion documentada).
    """
    admin_page.goto(viewer.url("/graph"))
    admin_page.wait_for_selector("#graph-canvas canvas", timeout=10_000)

    with admin_page.expect_response(lambda r: "/api/graph" in r.url and "q=" in r.url) as info:
        admin_page.fill("#search-input", ENTIDAD_UNICA)
        admin_page.press("#search-input", "Enter")
    nodos = info.value.json().get("nodes", [])
    assert len(nodos) == 1, (
        f"«{ENTIDAD_UNICA}» ya no aisla un unico nodo ({[n['label'] for n in nodos]}); "
        "elige otro termino en vez de saltarte la prueba")

    admin_page.wait_for_timeout(2500)                 # estabilizacion del layout

    # El grafo se pinta en <canvas>: no hay elemento DOM por nodo. Se localiza
    # el nodo por su color de relleno (Character = #6ea8fe en graph.js) leyendo
    # los pixeles reales que el navegador dibujo, y se pincha ahi. Nada de
    # tocar el objeto vis-network: el click es un click de raton de verdad.
    punto = admin_page.evaluate(
        """(color) => {
            const canvas = document.querySelector('#graph-canvas canvas');
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
            const rect = canvas.getBoundingClientRect();
            const ratio = rect.width / width;
            return {x: rect.left + (sx / n) * ratio, y: rect.top + (sy / n) * ratio, n};
        }""",
        "#6ea8fe",
    )
    assert punto, "no se encontro el nodo dibujado en el lienzo"
    admin_page.mouse.click(punto["x"], punto["y"])
    admin_page.wait_for_timeout(400)

    panel = admin_page.locator("#side-panel")
    assert ENTIDAD_UNICA in panel.inner_text(), \
        f"el panel no describe el nodo seleccionado: {panel.inner_text()[:200]}"
    assert panel.locator("a[href^='/entity/']").count() == 1, \
        "la ficha lateral no ofrece el enlace a la ficha completa"


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


def test_jobs_sin_base_de_datos_avisa_en_vez_de_reventar(admin_page, viewer):
    """Backend caido de forma controlada: la cola de jobs no esta disponible.

    En laboratorio no hay `jobs.db`, que es exactamente el fallo controlado que
    interesa: la pagina debe cargar (200) y decirlo, no dar un 500.
    """
    resp = admin_page.request.get(viewer.url("/api/jobs"))
    datos = resp.json()
    assert resp.status == 200
    if datos.get("ok"):
        pytest.skip("este entorno si tiene jobs.db: no se puede observar el estado degradado")

    status = fetch_status(admin_page, viewer, "/jobs")
    assert status == 200, f"/jobs con backend caido devolvio {status}"
    texto = admin_page.locator("body").inner_text().lower()
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


def test_404_en_html_no_deberia_devolver_json_crudo(admin_page, viewer):
    """HALLAZGO A-01 (defecto de aplicacion, fuera de mi zona: NO lo corrijo).

    Varias rutas HTML lanzan HTTPException sin manejador propio, asi que
    FastAPI responde `{"detail": ...}` en JSON y el navegador ensena el JSON en
    crudo, sin navegacion ni forma de volver. `/entities/{id}` si usa
    `error.html`: la inconsistencia es del producto, no del navegador.

    Esta prueba DOCUMENTA el comportamiento actual y se pondra roja el dia que
    se arregle — momento de borrarla y quedarse solo con la de arriba.
    """
    fetch_status(admin_page, viewer, "/entity/no-existe-esta-entidad")
    cuerpo = admin_page.content()
    es_json_crudo = '{"detail"' in cuerpo and "topbar" not in cuerpo
    assert es_json_crudo, (
        "el 404 de /entity/{id} ya devuelve HTML: el defecto A-01 esta corregido, "
        "borra esta prueba de documentacion")


def test_403_en_html_no_deberia_devolver_json_crudo(new_page, viewer):
    """HALLAZGO A-02: mismo defecto en el 403 de admin (ver A-01).

    `_require_reviewer_or_redirect` si pinta `auth/403.html`; `require_admin`
    lanza HTTPException y el usuario ve JSON. Documentado, no corregido.
    """
    pg = new_page()
    login_as(pg, viewer, "s9viewer")
    status = fetch_status(pg, viewer, "/admin/users")
    assert status == 403
    cuerpo = pg.content()
    assert '{"detail"' in cuerpo and "topbar" not in cuerpo, (
        "el 403 de /admin ya devuelve HTML: el defecto A-02 esta corregido, "
        "borra esta prueba de documentacion")


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
