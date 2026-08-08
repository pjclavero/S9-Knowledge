# -*- coding: utf-8 -*-
"""E2E de navegador: accesibilidad, teclado y responsive.

Auditoria, no certificacion WCAG. Dos clases de prueba conviven aqui:

1. INVARIANTES que el visor YA cumple. Fallan si alguien los rompe.
2. DEFECTOS conocidos, escritos como la prueba que DEBERIA pasar y marcados
   `xfail(strict=True)`. No enrojecen la CI hoy, pero el dia que alguien
   corrija el defecto la prueba pasa, `strict` convierte ese XPASS en fallo y
   obliga a quitar la marca. Un defecto documentado asi no se pudre en un
   backlog: esta en el arnes.

Ninguno de estos defectos se corrige aqui: todos viven en `viewer/app/**`, que
es zona de otros carriles (PR #152/#153). Ver el backlog en
`docs/47_qa_browser_e2e_visor.md`.
"""
from __future__ import annotations

import pytest

from e2e_support import MOBILE_VIEWPORT, fetch_status, login_as

PAGINAS = ["/", "/entities", "/graph", "/jobs", "/status", "/sources",
           "/reviews", "/admin/users"]

# Los defectos conocidos se marcan en el propio parametro: la prueba sigue
# siendo la correcta y el dia que se arreglen, `strict` obliga a quitar la marca.
XF_TABLA_STATUS = pytest.mark.xfail(
    strict=True, reason="ACC-06: la tabla de /status no tiene <th>")
XF_DESBORDE_ADMIN = pytest.mark.xfail(
    strict=True, reason="ACC-07: /admin/users se desborda a lo ancho en movil (613px en 393px)")

PAGINAS_TABLAS = [pytest.param("/status", marks=XF_TABLA_STATUS) if p == "/status" else p
                  for p in PAGINAS]
PAGINAS_MOVIL = [pytest.param("/admin/users", marks=XF_DESBORDE_ADMIN) if p == "/admin/users" else p
                 for p in PAGINAS]

# --- JS de auditoria, reutilizado por varias pruebas ------------------------

JS_CONTROLES_SIN_ETIQUETA = """
() => [...document.querySelectorAll('input:not([type=hidden]), select, textarea')]
  .filter(c => {
    if (c.getAttribute('aria-label') || c.getAttribute('aria-labelledby')) return false;
    if (c.id && document.querySelector(`label[for="${CSS.escape(c.id)}"]`)) return false;
    if (c.closest('label')) return false;
    return true;
  })
  .map(c => c.tagName.toLowerCase() + '#' + (c.id || c.name || '?'))
"""

JS_CONTRASTE = """
() => {
  const lum = (c) => {
    const m = c.match(/[\\d.]+/g).map(Number).slice(0, 3).map(v => {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
  };
  const bgOf = (el) => {
    let e = el;
    while (e) {
      const b = getComputedStyle(e).backgroundColor;
      if (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent') return b;
      e = e.parentElement;
    }
    return 'rgb(255, 255, 255)';
  };
  const malos = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!el.innerText || el.children.length > 0) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const size = parseFloat(cs.fontSize);
    const l1 = lum(cs.color), l2 = lum(bgOf(el));
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const grande = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight) >= 700);
    if (ratio < (grande ? 3 : 4.5)) {
      malos.push({texto: el.innerText.slice(0, 40), color: cs.color,
                  fondo: bgOf(el), tam: size, ratio: +ratio.toFixed(2)});
    }
  }
  return malos;
}
"""


@pytest.fixture()
def admin_page(page, viewer):
    login_as(page, viewer, "s9admin")
    return page


# ---------------------------------------------------------------------------
# Invariantes que el visor YA cumple
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PAGINAS)
def test_cada_pagina_declara_su_idioma(admin_page, viewer, path):
    """Sin lang, un lector de pantalla lee el castellano con fonemas ingleses."""
    fetch_status(admin_page, viewer, path)
    assert admin_page.get_attribute("html", "lang") == "es", f"{path} sin lang=es"


def test_el_login_declara_su_idioma(page, viewer):
    page.goto(viewer.url("/login"))
    assert page.get_attribute("html", "lang") == "es"


def test_los_campos_del_login_estan_etiquetados(page, viewer):
    page.goto(viewer.url("/login"))
    assert page.evaluate(JS_CONTROLES_SIN_ETIQUETA) == [], \
        "el formulario de login tiene controles sin etiqueta"
    assert page.get_attribute("#username", "autocomplete") == "username"
    assert page.get_attribute("#password", "autocomplete") == "current-password"


def test_los_campos_obligatorios_del_login_estan_marcados(page, viewer):
    page.goto(viewer.url("/login"))
    for campo in ("#username", "#password"):
        assert page.get_attribute(campo, "required") is not None, \
            f"{campo} no esta marcado como obligatorio"


def test_el_error_de_login_se_anuncia_como_alerta(page, viewer):
    """role=alert hace que el lector de pantalla lea el error sin mover el foco."""
    from e2e_support import do_login

    do_login(page, viewer, "s9viewer", "password-que-no-es")
    alerta = page.locator("[role='alert']")
    assert alerta.count() >= 1, "el error de login no es una region de alerta"
    assert "incorrect" in alerta.first.inner_text().lower()


def test_el_formulario_de_admin_etiqueta_todos_sus_campos(admin_page, viewer):
    fetch_status(admin_page, viewer, "/admin/users/new")
    sin_etiqueta = admin_page.evaluate(JS_CONTROLES_SIN_ETIQUETA)
    assert sin_etiqueta == [], f"campos sin etiqueta en el alta de usuario: {sin_etiqueta}"


def test_el_boton_de_cerrar_el_panel_tiene_nombre_accesible(admin_page, viewer):
    fetch_status(admin_page, viewer, "/graph")
    boton = admin_page.locator("#side-panel-close")
    assert boton.count() == 1
    assert (boton.get_attribute("aria-label") or "").strip(), \
        "el boton de cerrar el panel es un aspa sin nombre accesible"


@pytest.mark.parametrize("path", PAGINAS)
def test_ningun_boton_ni_enlace_se_queda_sin_nombre(admin_page, viewer, path):
    fetch_status(admin_page, viewer, path)
    admin_page.wait_for_timeout(500)
    anonimos = admin_page.evaluate("""
        () => [...document.querySelectorAll('button, a')]
          .filter(el => !el.innerText.trim() && !el.getAttribute('aria-label')
                        && !el.getAttribute('title'))
          .map(el => el.tagName.toLowerCase() + '.' + (el.className || ''))
    """)
    assert anonimos == [], f"{path} tiene controles sin nombre accesible: {anonimos}"


@pytest.mark.parametrize("path", PAGINAS_TABLAS)
def test_las_tablas_de_datos_tienen_cabeceras(admin_page, viewer, path):
    fetch_status(admin_page, viewer, path)
    sin_th = admin_page.evaluate(
        "() => [...document.querySelectorAll('table')].filter(t => !t.querySelector('th')).length")
    assert sin_th == 0, f"{path} tiene tablas de datos sin <th>"


# ---------------------------------------------------------------------------
# Teclado
# ---------------------------------------------------------------------------

def test_se_puede_iniciar_sesion_solo_con_el_teclado(page, viewer):
    """Sin raton: Tab hasta los campos, escribir, Tab al boton, Enter."""
    page.goto(viewer.url("/login"))
    page.keyboard.press("Tab")                        # el autofocus ya esta en #username
    activo = page.evaluate("() => document.activeElement.id")
    if activo != "username":
        page.focus("#username")
    page.keyboard.type("s9viewer")
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement.id") == "password", \
        "Tab desde el usuario no lleva a la contrasena"
    page.keyboard.type(viewer.users["s9viewer"]["password"])
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement.id") == "login-submit", \
        "Tab desde la contrasena no lleva al boton de enviar"
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, "no se pudo entrar solo con el teclado"


def test_el_foco_del_teclado_es_visible(page, viewer):
    """Un foco invisible deja a quien navega con Tab sin saber donde esta."""
    page.goto(viewer.url("/login"))
    page.focus("#username")
    estilo = page.evaluate("""() => {
        const cs = getComputedStyle(document.activeElement);
        return {outline: cs.outlineStyle, ancho: cs.outlineWidth, sombra: cs.boxShadow};
    }""")
    visible = (estilo["outline"] not in ("none", "") or estilo["sombra"] not in ("none", ""))
    assert visible, f"el elemento enfocado no muestra indicador de foco: {estilo}"


def test_la_navegacion_principal_es_alcanzable_con_tab(admin_page, viewer):
    fetch_status(admin_page, viewer, "/")
    alcanzados = []
    for _ in range(12):
        admin_page.keyboard.press("Tab")
        alcanzados.append(admin_page.evaluate(
            "() => document.activeElement.getAttribute('href') || ''"))
    assert "/entities" in alcanzados, \
        f"la nav no se alcanza con Tab desde el inicio: {alcanzados}"


def test_ningun_elemento_secuestra_el_orden_de_tabulacion(admin_page, viewer):
    """tabindex positivo = orden de tabulacion roto para todo el documento."""
    for path in PAGINAS:
        fetch_status(admin_page, viewer, path)
        positivos = admin_page.evaluate(
            "() => [...document.querySelectorAll('[tabindex]')]"
            ".filter(el => parseInt(el.getAttribute('tabindex'), 10) > 0).length")
        assert positivos == 0, f"{path} usa tabindex positivo"


def test_el_menu_desplegable_del_grafo_se_maneja_con_teclado(admin_page, viewer):
    fetch_status(admin_page, viewer, "/graph")
    admin_page.wait_for_selector("#graph-canvas canvas", timeout=10_000)
    with admin_page.expect_response(lambda r: "/api/graph" in r.url):
        admin_page.select_option("#limit-select", "100")
    assert admin_page.input_value("#limit-select") == "100"


# ---------------------------------------------------------------------------
# Responsive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PAGINAS_MOVIL)
def test_en_movil_la_pagina_no_se_desborda_a_lo_ancho(new_page, viewer, path):
    """Scroll horizontal en movil = contenido inalcanzable con el pulgar."""
    pg = new_page(MOBILE_VIEWPORT)
    login_as(pg, viewer, "s9admin")
    fetch_status(pg, viewer, path)
    pg.wait_for_timeout(600)
    desbordes = pg.evaluate("""() => ({
        doc: document.documentElement.scrollWidth,
        vista: window.innerWidth,
    })""")
    margen = 2                                        # tolerancia de redondeo
    assert desbordes["doc"] <= desbordes["vista"] + margen, \
        f"{path} se desborda en movil: {desbordes}"


def test_el_login_es_usable_en_movil(new_page, viewer):
    pg = new_page(MOBILE_VIEWPORT)
    pg.goto(viewer.url("/login"))
    for selector in ("#username", "#password", "#login-submit"):
        caja = pg.locator(selector).bounding_box()
        assert caja is not None, f"{selector} no es visible en movil"
        assert caja["x"] >= 0 and caja["x"] + caja["width"] <= MOBILE_VIEWPORT["width"] + 2, \
            f"{selector} se sale de la pantalla en movil: {caja}"
    assert pg.locator("#login-submit").bounding_box()["height"] >= 24, \
        "el boton de entrar es demasiado bajo para pulsarlo con el dedo"


def test_la_navegacion_sigue_disponible_en_movil(new_page, viewer):
    pg = new_page(MOBILE_VIEWPORT)
    login_as(pg, viewer, "s9admin")
    fetch_status(pg, viewer, "/")
    enlaces = pg.locator("header.topbar nav a")
    assert enlaces.count() >= 5
    assert enlaces.first.is_visible(), "la nav desaparece en movil sin alternativa"


# ---------------------------------------------------------------------------
# DEFECTOS CONOCIDOS — la prueba correcta, marcada como fallo esperado
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="ACC-01: /graph no tiene <main> ni ningun encabezado")
def test_el_grafo_tiene_landmark_principal_y_encabezado(admin_page, viewer):
    fetch_status(admin_page, viewer, "/graph")
    assert admin_page.locator("main, [role='main']").count() == 1, "/graph sin landmark <main>"
    assert admin_page.locator("h1, h2").count() >= 1, "/graph sin ningun encabezado"


@pytest.mark.xfail(strict=True, reason="ACC-02: la barra del grafo solo usa placeholder como etiqueta")
def test_los_controles_del_grafo_estan_etiquetados(admin_page, viewer):
    fetch_status(admin_page, viewer, "/graph")
    sin_etiqueta = admin_page.evaluate(JS_CONTROLES_SIN_ETIQUETA)
    assert sin_etiqueta == [], f"controles sin etiqueta en /graph: {sin_etiqueta}"


@pytest.mark.xfail(strict=True, reason="ACC-02: el filtro de /entities solo usa placeholder")
def test_los_filtros_de_entidades_estan_etiquetados(admin_page, viewer):
    fetch_status(admin_page, viewer, "/entities")
    sin_etiqueta = admin_page.evaluate(JS_CONTROLES_SIN_ETIQUETA)
    assert sin_etiqueta == [], f"controles sin etiqueta en /entities: {sin_etiqueta}"


@pytest.mark.xfail(strict=True, reason="ACC-03: texto gris #555/#666 sobre fondo oscuro (ratio 2.4-3.2)")
def test_el_texto_secundario_tiene_contraste_suficiente(admin_page, viewer):
    fetch_status(admin_page, viewer, "/entities")
    malos = admin_page.evaluate(JS_CONTRASTE)
    assert malos == [], f"textos por debajo del minimo AA: {malos[:5]}"


@pytest.mark.xfail(strict=True, reason="ACC-04: varias paginas empiezan en <h2>, sin <h1>")
def test_cada_pagina_tiene_un_unico_h1(admin_page, viewer):
    faltan = []
    for path in PAGINAS:
        fetch_status(admin_page, viewer, path)
        if admin_page.locator("h1").count() != 1:
            faltan.append((path, admin_page.locator("h1").count()))
    assert faltan == [], f"paginas sin un unico <h1>: {faltan}"


@pytest.mark.xfail(strict=True, reason="ACC-05: no hay enlace de salto al contenido")
def test_hay_un_enlace_para_saltar_al_contenido(admin_page, viewer):
    fetch_status(admin_page, viewer, "/")
    saltos = admin_page.evaluate("""
        () => [...document.querySelectorAll('a[href^="#"]')]
          .map(a => a.innerText.trim().toLowerCase())
          .filter(t => t.includes('contenido') || t.includes('saltar'))
    """)
    assert saltos, "no hay enlace «saltar al contenido» antes de la navegacion"
