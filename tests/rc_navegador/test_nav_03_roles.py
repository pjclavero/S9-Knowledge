# -*- coding: utf-8 -*-
"""Autorización y visibilidad por rol: qué menú, qué pantallas, qué botones.

Contrato: E7 (autorización por rol), E6 (6.M1–6.M2: `/admin/health`, `/jobs`,
paneles) y regresión 15. Los roles del producto son tres: ``viewer`` (lector),
``reviewer`` (revisor, el único intermedio) y ``admin``.

Lo que se espera se DERIVA de dos cosas y no de una tabla pegada a mano por
pantalla: el rol mínimo de cada ruta (el del registro del chasis del producto)
y las capacidades que la instalación declara (un panel no declarado tiene que
responder 404 aunque el rol alcance; uno declarado tiene que responder 200).
Así la misma prueba vale para la instalación base y para la del ensayo, y la
declaración de capacidades queda contrastada con la instalación en los dos
sentidos.

Ninguna prueba de este módulo necesita Neo4j.
"""
from __future__ import annotations

import pytest

from soporte import (
    cadena_de_redirecciones,
    enlaces_de_navegacion,
    fetch_en_pagina,
    ir,
    ruta_de,
    texto_visible,
)

pytestmark = [pytest.mark.sin_grafo]

ORDEN = {"viewer": 0, "reviewer": 1, "admin": 2}
ROL_DE = {"lector": "viewer", "revisor": "reviewer", "admin": "admin"}

#: (ruta, rol mínimo, capacidad que la enciende o None, nombre en el menú o None)
RUTAS = (
    ("/", "viewer", None, "home"),
    ("/entities", "viewer", None, "entities_page"),
    ("/graph", "viewer", None, "graph_view"),
    ("/jobs", "viewer", None, "jobs_view"),
    ("/status", "viewer", None, "status_view"),
    ("/account", "viewer", None, None),
    ("/sources", "reviewer", None, "sources_page"),
    ("/reviews", "reviewer", None, "reviews_view"),
    ("/v3/review", "reviewer", None, "v3_review_queue"),
    ("/panel/review", "reviewer", "panel_c", "chassis_review"),
    ("/panel/operations", "admin", "panel_b", "chassis_operations"),
    ("/panel/sources", "reviewer", "panel_f", "chassis_sources"),
    ("/panel/entities", "viewer", "panel_g", "chassis_entities"),
    ("/admin/users", "admin", None, "admin_users"),
    ("/admin/partidas", "admin", None, "admin_partidas"),
    ("/admin/users/new", "admin", None, None),
    ("/admin/audit", "admin", None, None),
    ("/admin/health", "admin", None, None),
)


def _esperado(cfg, rol: str, minimo: str, capacidad) -> int:
    if ORDEN[rol] < ORDEN[minimo]:
        return 403
    if capacidad is not None and capacidad not in cfg.capacidades:
        return 404
    return 200


@pytest.mark.cubre("extra.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor", "admin"])
def test_el_menu_ofrece_exactamente_lo_que_el_rol_puede_abrir(pagina_como, cfg, evidencia, cuenta):
    rol = ROL_DE[cuenta]
    pagina = pagina_como(cuenta)
    respuesta = ir(pagina, cfg, "/")
    evidencia.paso(pagina, f"inicio como {cuenta}", estado=respuesta.status)
    assert respuesta.status == 200, f"MENÚ[{cuenta}]: el inicio respondió {respuesta.status}"
    ofrecido = enlaces_de_navegacion(pagina)
    esperado = [nombre for ruta, minimo, capacidad, nombre in RUTAS
                if nombre and _esperado(cfg, rol, minimo, capacidad) == 200]
    evidencia.dato("menú", {"ofrecido": ofrecido, "esperado": esperado})
    assert sorted(ofrecido) == sorted(esperado), (
        f"MENÚ[{cuenta}]: el menú ofrece {sorted(ofrecido)} y a este rol le corresponde {sorted(esperado)}"
    )
    assert pagina.locator("header.topbar .role-badge").inner_text().strip() == rol, (
        f"MENÚ[{cuenta}]: la insignia de rol no dice {rol}"
    )
    # Cada enlace ofrecido se abre de verdad: ningún enlace del menú lleva a
    # un rechazo ni a una pantalla inexistente.
    rotos = []
    for href in pagina.eval_on_selector_all("header.topbar nav a[data-nav]", "els => els.map(e => e.getAttribute('href'))"):
        r = ir(pagina, cfg, href)
        if r.status != 200:
            rotos.append((href, r.status))
    assert not rotos, f"MENÚ[{cuenta}]: enlaces del menú que no abren: {rotos}"


@pytest.mark.cubre("extra.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor", "admin"])
def test_la_barra_de_sesion_y_el_menu_del_rol_estan_en_todas_las_pantallas(pagina_como, cfg, evidencia, cuenta):
    """En cualquier pantalla que el rol puede abrir tienen que estar su menú
    (el mismo que en el inicio), quién es, su rol y «Salir»."""
    rol = ROL_DE[cuenta]
    pagina = pagina_como(cuenta)
    ir(pagina, cfg, "/")
    menu_del_inicio = sorted(enlaces_de_navegacion(pagina))
    sin_barra, otro_menu = [], []
    for ruta, minimo, capacidad, _ in RUTAS:
        if ruta == "/" or _esperado(cfg, rol, minimo, capacidad) != 200:
            continue
        ir(pagina, cfg, ruta)
        if (pagina.locator("header.topbar .role-badge").count() == 0
                or pagina.locator("header.topbar form[action='/logout']").count() == 0):
            sin_barra.append(ruta)
            evidencia.paso(pagina, f"sin barra de sesión {ruta}")
        menu = sorted(enlaces_de_navegacion(pagina))
        if menu != menu_del_inicio:
            otro_menu.append(f"{ruta}: faltan {sorted(set(menu_del_inicio) - set(menu))}")
    evidencia.dato("pantallas", {"sin_barra_de_sesion": sin_barra, "con_otro_menu": otro_menu})
    assert not sin_barra and not otro_menu, (
        f"BARRA[{cuenta}]: pantallas sin usuario, rol ni «Salir» en la barra: {sin_barra}; "
        f"pantallas con un menú distinto del del inicio: {otro_menu}"
    )


@pytest.mark.cubre("extra.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor", "admin"])
def test_cada_pantalla_responde_segun_el_rol(pagina_como, cfg, evidencia, cuenta):
    rol = ROL_DE[cuenta]
    pagina = pagina_como(cuenta)
    discrepancias = []
    tabla = []
    for ruta, minimo, capacidad, _ in RUTAS:
        respuesta = ir(pagina, cfg, ruta)
        esperado = _esperado(cfg, rol, minimo, capacidad)
        cadena = cadena_de_redirecciones(respuesta)
        evidencia.paso(pagina, f"{cuenta} {ruta}", estado=respuesta.status)
        tabla.append({"ruta": ruta, "esperado": esperado, "obtenido": respuesta.status, "cadena": cadena})
        if respuesta.status != esperado or ruta_de(pagina) == "/login":
            discrepancias.append(f"{ruta}: esperado {esperado}, obtenido {cadena}")
    evidencia.dato("matriz", tabla)
    assert not discrepancias, f"ACCESO[{cuenta}]: " + "; ".join(discrepancias)


@pytest.mark.cubre("extra.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor"])
def test_un_rechazo_por_rol_se_explica_en_una_pantalla_del_producto(pagina_como, cfg, evidencia, cuenta):
    """Quien abre a mano una dirección que no le corresponde tiene que ver una
    pantalla del producto que lo diga, con su barra y un camino de vuelta; no
    el cuerpo crudo de una respuesta de API."""
    rol = ROL_DE[cuenta]
    pagina = pagina_como(cuenta)
    crudas = []
    for ruta, minimo, capacidad, _ in RUTAS:
        if _esperado(cfg, rol, minimo, capacidad) != 403:
            continue
        respuesta = ir(pagina, cfg, ruta)
        tipo = respuesta.headers.get("content-type", "")
        evidencia.paso(pagina, f"rechazo {ruta}", estado=respuesta.status)
        if "text/html" not in tipo or pagina.locator("header.topbar").count() == 0:
            crudas.append(f"{ruta} ({tipo.split(';')[0]}: {texto_visible(pagina)[:80]})")
    evidencia.dato("rechazos sin pantalla", crudas)
    assert not crudas, (
        f"RECHAZO_CRUDO[{cuenta}]: estas direcciones responden 403 sin pantalla del producto: " + "; ".join(crudas)
    )


@pytest.mark.cubre("extra.roles", "REG-15")
def test_una_direccion_inexistente_se_explica_en_una_pantalla_del_producto(pagina_como, cfg, evidencia):
    pagina = pagina_como("lector")
    respuesta = ir(pagina, cfg, "/no-existe-rc3nav")
    evidencia.paso(pagina, "dirección inexistente", estado=respuesta.status)
    assert respuesta.status == 404, f"NO_EXISTE: respondió {respuesta.status}"
    assert "text/html" in respuesta.headers.get("content-type", "") and pagina.locator("header.topbar").count() == 1, (
        "NO_EXISTE_CRUDO: una dirección inexistente responde el cuerpo crudo de la API, sin pantalla "
        f"ni camino de vuelta: {texto_visible(pagina)[:80]!r}"
    )


# ---------------------------------------------------------------------------
# Botones: quién puede escribir
# ---------------------------------------------------------------------------

#: Formularios de escritura que puede ver cualquier usuario con sesión.
_PROPIOS = {"/logout", "/partida/select", "/account/change-password"}
_DE_REVISOR = {"/v3/review/decide", "/v3/review/undo"}


def _formularios_post(pagina) -> list[str]:
    return pagina.eval_on_selector_all(
        "form",
        "els => els.filter(f => (f.getAttribute('method') || 'get').toLowerCase() === 'post')"
        ".map(f => new URL(f.getAttribute('action') || location.href, location.href).pathname)",
    )


@pytest.mark.cubre("extra.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor"])
def test_las_pantallas_no_ofrecen_botones_de_escritura_que_el_rol_no_tiene(pagina_como, cfg, evidencia, cuenta):
    rol = ROL_DE[cuenta]
    permitidos = set(_PROPIOS)
    if rol == "reviewer":
        permitidos |= _DE_REVISOR
    pagina = pagina_como(cuenta)
    sobran = []
    vistos = {}
    for ruta, minimo, capacidad, _ in RUTAS + (("/account/change-password", "viewer", None, None),):
        if _esperado(cfg, rol, minimo, capacidad) != 200:
            continue
        ir(pagina, cfg, ruta)
        acciones = sorted(set(_formularios_post(pagina)))
        vistos[ruta] = acciones
        for accion in acciones:
            if accion not in permitidos and not accion.startswith("/reviews/"):
                sobran.append(f"{ruta} ofrece {accion}")
    evidencia.dato("formularios de escritura por pantalla", vistos)
    assert not sobran, f"BOTONES[{cuenta}]: " + "; ".join(sobran)


def _testigo(pagina) -> str:
    return pagina.locator("header.topbar form[action='/logout'] input[name=csrf_token]").get_attribute("value") or ""


@pytest.mark.cubre("extra.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor"])
def test_un_envio_fabricado_no_salta_el_rol(pagina_como, cfg, evidencia, cuenta):
    """Con su sesión y su testigo CSRF reales, quien no es administrador
    fabrica los envíos de administración: todos se rechazan y nada cambia."""
    pagina = pagina_como(cuenta)
    ir(pagina, cfg, "/")
    testigo = _testigo(pagina)
    assert testigo, "FABRICADO: PRECONDICIÓN: la página no trae testigo CSRF de sesión"
    usuario_fantasma = "rc3nav_fabricado_" + cuenta
    envios = [
        ("/admin/users/new", {"username": usuario_fantasma, "display_name": "x", "role": "admin",
                              "password": "no-se-crea-" + "x" * 12}),
        ("/admin/health/snapshot", {}),
        ("/admin/partidas/grant", {"user_id": "1", "workspace": "x", "partida_id": "x"}),
        ("/admin/partidas/label", {"workspace": "x", "label": "x", "fingerprint": "x"}),
        ("/panel/operations/ingestas", {"fuente": "x"}),
        ("/panel/operations/planes", {"trabajo": "x"}),
        ("/panel/operations/aplicaciones", {"trabajo": "x"}),
        ("/panel/operations/altas", {"trabajo": "x", "entidad": "x"}),
    ]
    if cuenta == "lector":
        envios.append(("/v3/review/decide", {"workspace": "x", "proposal_id": "x", "human_decision": "APPROVE",
                                              "expected_proposal_hash": "x", "request_id": "x"}))
    pasaron = []
    registro = []
    for ruta, campos in envios:
        r = fetch_en_pagina(pagina, "POST", ruta, formulario={"csrf_token": testigo, **campos})
        registro.append({"ruta": ruta, "estado": r["estado"], "url_final": r["url"]})
        if r["estado"] != 403:
            pasaron.append(f"{ruta} -> {r['estado']}")
    evidencia.dato("envíos fabricados", registro)
    assert not pasaron, f"FABRICADO[{cuenta}]: envíos de administración no rechazados con 403: {pasaron}"
    # La sesión sigue siendo la suya y no ganó nada.
    ir(pagina, cfg, "/admin/users")
    assert pagina.locator("table.data-table").count() == 0, f"FABRICADO[{cuenta}]: tras los envíos ve la administración"


@pytest.mark.cubre("extra.roles", "REG-15")
def test_el_usuario_fabricado_no_existe(pagina_como, cfg, evidencia):
    """Efecto de la prueba anterior visto por el administrador: nadie creó
    las cuentas que los envíos fabricados pedían."""
    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/users")
    evidencia.paso(admin, "usuarios tras los envíos fabricados")
    nombres = admin.eval_on_selector_all("table.data-table tbody tr td:nth-child(2)", "els => els.map(e => e.textContent.trim())")
    fantasmas = [n for n in nombres if n.startswith("rc3nav_fabricado_")]
    assert nombres, "FABRICADO: PRECONDICIÓN: la administración no lista usuarios"
    assert not fantasmas, f"FABRICADO: existen cuentas creadas por un envío sin permiso: {fantasmas}"


# ---------------------------------------------------------------------------
# Ámbito: un lector acotado a una partida no ve la otra
# ---------------------------------------------------------------------------

def _conceder(admin, cfg, usuario: str, partida: str) -> None:
    ir(admin, cfg, "/admin/partidas")
    formulario = admin.locator("form[action='/admin/partidas/grant']")
    opcion = formulario.locator("#user_id option", has_text=usuario + " (")
    assert opcion.count() == 1, f"ÁMBITO: PREPARACIÓN: {usuario} no aparece en el selector de usuarios"
    formulario.locator("#user_id").select_option(value=opcion.get_attribute("value"))
    formulario.locator("#partida_id").select_option(value=partida)
    with admin.expect_navigation():
        formulario.locator("button[type=submit]").click()


def _revocar_todo(admin, cfg, usuarios: list[str]) -> None:
    for _ in range(20):
        ir(admin, cfg, "/admin/partidas")
        filas = admin.locator("table.data-table tbody tr")
        pendiente = None
        for i in range(filas.count()):
            if filas.nth(i).locator("td").first.inner_text().strip() in usuarios:
                pendiente = filas.nth(i)
                break
        if pendiente is None:
            return
        with admin.expect_navigation():
            pendiente.locator("form[action$='/revoke'] button").click()


def _partidas_ofrecidas(pagina) -> list[str]:
    return pagina.eval_on_selector_all(
        "header.topbar form.partida-selector select option", "els => els.map(o => o.value).filter(v => v)"
    )


@pytest.mark.cubre("extra.ambito", "REG-15")
@pytest.mark.requiere("boveda", "partidas")
def test_un_lector_acotado_a_una_partida_no_ve_ni_puede_elegir_la_otra(pagina_como, cfg, evidencia):
    assert cfg.partida_a and cfg.partida_b and cfg.partida_a != cfg.partida_b, (
        "ÁMBITO: declara S9K_RC_NAV_PARTIDA_A y S9K_RC_NAV_PARTIDA_B (dos partidas distintas de la bóveda)"
    )
    lector_a, lector_b = cfg.cuenta("lector")["username"], cfg.cuenta("lector_b")["username"]
    admin = pagina_como("admin")
    _revocar_todo(admin, cfg, [lector_a, lector_b])
    try:
        # Sin concesión: sólo la capa de juego, ningún selector de partida.
        pa = pagina_como("lector")
        ir(pa, cfg, "/")
        evidencia.paso(pa, "lector sin ninguna partida concedida")
        assert _partidas_ofrecidas(pa) == [], "ÁMBITO: un lector sin concesiones ve partidas en su selector"

        _conceder(admin, cfg, lector_a, cfg.partida_a)
        _conceder(admin, cfg, lector_b, cfg.partida_b)
        evidencia.paso(admin, "concesiones hechas")

        ir(pa, cfg, "/")
        pb = pagina_como("lector_b")
        ir(pb, cfg, "/")
        evidencia.paso(pa, "selector del lector A")
        evidencia.paso(pb, "selector del lector B")
        assert _partidas_ofrecidas(pa) == [cfg.partida_a], (
            f"ÁMBITO: al lector A se le ofrecen {_partidas_ofrecidas(pa)}, sólo tiene concedida {cfg.partida_a}"
        )
        assert _partidas_ofrecidas(pb) == [cfg.partida_b], (
            f"ÁMBITO: al lector B se le ofrecen {_partidas_ofrecidas(pb)}, sólo tiene concedida {cfg.partida_b}"
        )

        # El lector A elige la suya con el selector, como una persona.
        with pa.expect_navigation():
            pa.select_option("header.topbar #partida_id", value=cfg.partida_a)
        evidencia.paso(pa, "lector A con su partida activa")
        assert pa.input_value("header.topbar #partida_id") == cfg.partida_a, "ÁMBITO: la partida propia no quedó activa"

        # Y no puede activar la ajena aunque fabrique el envío.
        r = fetch_en_pagina(pa, "POST", "/partida/select",
                            formulario={"csrf_token": _testigo(pa), "partida_id": cfg.partida_b, "next": "/"})
        evidencia.dato("lector A pide la partida de B", {"estado": r["estado"], "texto": r["texto"][:200]})
        assert r["estado"] == 403, f"ÁMBITO: pedir la partida ajena respondió {r['estado']}, se esperaba 403"
        ir(pa, cfg, "/")
        assert pa.input_value("header.topbar #partida_id") == cfg.partida_a, (
            "ÁMBITO: tras pedir la partida ajena, la activa ya no es la propia"
        )
    finally:
        _revocar_todo(admin, cfg, [lector_a, lector_b])
    ir(pa, cfg, "/")
    evidencia.paso(pa, "lector A tras revocar")
    assert _partidas_ofrecidas(pa) == [], "ÁMBITO: tras revocar, el lector sigue viendo la partida"
