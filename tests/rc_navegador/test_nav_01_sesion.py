# -*- coding: utf-8 -*-
"""Sesión: entrar, salir, contraseña errónea, sin cookie, bloqueo y cambio forzoso.

Contrato: E7 (7.M1 inicio y cierre de sesión, 7.M2 contraseña errónea y
bloqueo), E6 (6.01–6.03 vistos desde el navegador), E1 (1.M1/N9: la
configuración inicial ya no está abierta) y la regresión 15 (navegador).

Ninguna prueba de este módulo necesita Neo4j.

Cada prueba que INICIA sesión usa una cuenta propia (``sesion``, ``bloqueo``,
``cambio``, ``inactivo``): el producto revoca las sesiones anteriores del
usuario en cada entrada, y eso no puede tumbar las sesiones compartidas de las
demás pruebas.
"""
from __future__ import annotations

import secrets

import pytest

from soporte import (
    cadena_de_redirecciones,
    enviar_login,
    fetch_en_pagina,
    iniciar_sesion,
    ir,
    rellenar_login,
    ruta_de,
    texto_visible,
)

pytestmark = [pytest.mark.sin_grafo]

COOKIE_SESION = "s9k_session"
COOKIE_CSRF_LOGIN = "_s9k_login_csrf"
MENSAJE_CREDENCIALES = "Usuario o contraseña incorrectos."


def _cookie(ctx, nombre: str):
    return next((c for c in ctx.cookies() if c["name"] == nombre), None)


# ---------------------------------------------------------------------------
# Sin sesión
# ---------------------------------------------------------------------------

@pytest.mark.cubre("6.03", "extra.sesion", "REG-15")
@pytest.mark.parametrize("ruta", ["/", "/entities", "/jobs", "/account", "/admin/users", "/v3/review"])
def test_sin_cookie_las_pantallas_llevan_al_login(pagina_anonima, cfg, evidencia, ruta):
    respuesta = ir(pagina_anonima, cfg, ruta)
    cadena = cadena_de_redirecciones(respuesta)
    evidencia.paso(pagina_anonima, f"sin sesion {ruta}", estado=respuesta.status)
    evidencia.dato("cadena", cadena)
    assert cadena[0][0] == 302, f"SIN_SESION: {ruta} respondió {cadena[0][0]}, se esperaba 302 al login"
    assert ruta_de(pagina_anonima) == "/login", (
        f"SIN_SESION: {ruta} acabó en {ruta_de(pagina_anonima)}, no en el formulario de entrada"
    )
    assert pagina_anonima.locator("#login-form").count() == 1, "SIN_SESION: no se pintó el formulario de entrada"
    assert pagina_anonima.locator("header.topbar nav a").count() == 0, (
        "SIN_SESION: el formulario de entrada ofrece navegación a quien no ha entrado"
    )


@pytest.mark.cubre("6.01", "REG-15")
@pytest.mark.parametrize("ruta", ["/api/status", "/api/entities", "/api/jobs", "/api/admin/health"])
def test_sin_cookie_la_api_responde_401_sin_redirigir(pagina_anonima, cfg, evidencia, ruta):
    ir(pagina_anonima, cfg, "/login")
    r = fetch_en_pagina(pagina_anonima, "GET", ruta)
    evidencia.dato(f"fetch {ruta}", r)
    assert r["estado"] == 401, f"API_SIN_SESION: {ruta} respondió {r['estado']}, se esperaba 401"
    assert not r["redirigida"], f"API_SIN_SESION: {ruta} redirigió en vez de responder 401"
    assert "json" in r["tipo"], f"API_SIN_SESION: {ruta} respondió {r['tipo']}, no JSON"


@pytest.mark.cubre("6.02", "N9", "REG-15")
def test_la_configuracion_inicial_esta_cerrada(pagina_anonima, cfg, evidencia):
    respuesta = ir(pagina_anonima, cfg, "/setup/admin")
    evidencia.paso(pagina_anonima, "setup admin cerrado", estado=respuesta.status)
    assert respuesta.status == 404, (
        f"SETUP_ABIERTO: /setup/admin respondió {respuesta.status} en una instalación con administrador"
    )
    assert pagina_anonima.locator("input[type=password]").count() == 0, (
        "SETUP_ABIERTO: la respuesta ofrece un campo de contraseña"
    )


@pytest.mark.cubre("1.28", "1.29", "REG-15")
def test_http_plano_redirige_a_https(pagina_anonima, cfg, evidencia):
    respuesta = pagina_anonima.goto(f"http://{cfg.host}/login", wait_until="domcontentloaded")
    cadena = cadena_de_redirecciones(respuesta)
    evidencia.paso(pagina_anonima, "http plano", estado=respuesta.status)
    evidencia.dato("cadena", cadena)
    assert cadena[0][0] in (301, 308), f"HTTP_PLANO: el puerto 80 respondió {cadena[0][0]}, no una redirección permanente"
    assert pagina_anonima.url.startswith("https://"), f"HTTP_PLANO: se acabó en {pagina_anonima.url}"
    assert respuesta.headers.get("strict-transport-security"), "HTTP_PLANO: la respuesta https no trae HSTS"


# ---------------------------------------------------------------------------
# Entrar y salir
# ---------------------------------------------------------------------------

@pytest.mark.cubre("7.M1", "7.09", "7.10", "REG-15")
def test_entrar_emite_una_cookie_de_sesion_protegida(contexto, cfg, evidencia):
    ctx = contexto("sesion")
    pagina = ctx.new_page()
    cuenta = cfg.cuenta("sesion")
    rellenar_login(pagina, cfg, cuenta["username"], cuenta["password"])
    evidencia.paso(pagina, "formulario relleno")
    assert _cookie(ctx, COOKIE_SESION) is None, "ENTRAR: había cookie de sesión antes de entrar"
    respuesta = enviar_login(pagina)
    evidencia.paso(pagina, "tras entrar", estado=respuesta.status)
    assert respuesta.status == 302, f"ENTRAR: POST /login respondió {respuesta.status}, se esperaba 302"
    assert ruta_de(pagina) == "/", f"ENTRAR: se acabó en {ruta_de(pagina)}, no en el inicio"

    sesion = _cookie(ctx, COOKIE_SESION)
    assert sesion is not None, "ENTRAR: el navegador no guardó la cookie de sesión"
    evidencia.dato("atributos de la cookie de sesión",
                   {k: sesion[k] for k in ("httpOnly", "secure", "sameSite", "path", "domain")})
    assert sesion["httpOnly"] is True, "ENTRAR: la cookie de sesión no es HttpOnly"
    assert sesion["secure"] is True, "ENTRAR: la cookie de sesión no es Secure"
    assert sesion["sameSite"] == "Lax", f"ENTRAR: SameSite es {sesion['sameSite']}, se esperaba Lax"
    assert sesion["path"] == "/", f"ENTRAR: la cookie de sesión tiene path {sesion['path']}"
    assert _cookie(ctx, COOKIE_CSRF_LOGIN) is None, "ENTRAR: el testigo CSRF del formulario sigue vivo tras entrar"
    visibles_js = pagina.evaluate("document.cookie")
    assert COOKIE_SESION not in visibles_js, "ENTRAR: el JavaScript de la página puede leer la cookie de sesión"

    barra = texto_visible(pagina, "header.topbar")
    assert "viewer" in barra and "Salir" in barra, f"ENTRAR: la barra no muestra el rol ni «Salir»: {barra!r}"
    assert pagina.locator("header.topbar .role-badge").inner_text().strip() == "viewer", (
        "ENTRAR: la insignia de rol no dice viewer"
    )


@pytest.mark.cubre("7.M1", "REG-15")
def test_salir_cierra_la_sesion_en_el_servidor(contexto, cfg, evidencia, navegador):
    ctx = contexto("sesion")
    pagina = ctx.new_page()
    iniciar_sesion(pagina, cfg, cfg.cuenta("sesion"))
    cookie_vieja = _cookie(ctx, COOKIE_SESION)
    assert cookie_vieja is not None, "SALIR: preparación: no se pudo entrar"
    protegida = ir(pagina, cfg, "/")
    evidencia.paso(pagina, "dentro")
    evidencia.dato("cabeceras de caché de la pantalla protegida", {
        c: protegida.headers.get(c) for c in ("cache-control", "pragma", "expires")
    })

    with pagina.expect_navigation():
        pagina.click("header.topbar form[action='/logout'] button")
    evidencia.paso(pagina, "tras salir")
    assert ruta_de(pagina) == "/login", f"SALIR: se acabó en {ruta_de(pagina)}, no en el formulario de entrada"
    assert _cookie(ctx, COOKIE_SESION) is None, "SALIR: el navegador conserva la cookie de sesión"

    respuesta = ir(pagina, cfg, "/account")
    assert ruta_de(pagina) == "/login", "SALIR: tras salir se sigue viendo /account"
    evidencia.paso(pagina, "account tras salir", estado=respuesta.status)

    # La sesión se cierra EN EL SERVIDOR, no sólo borrando la cookie: quien
    # conserve el valor antiguo (otro navegador, una copia) tampoco entra.
    copia = contexto("copia-de-la-cookie")
    copia.add_cookies([cookie_vieja])
    pagina_copia = copia.new_page()
    respuesta = ir(pagina_copia, cfg, "/account")
    evidencia.paso(pagina_copia, "cookie antigua reutilizada", estado=respuesta.status)
    assert ruta_de(pagina_copia) == "/login", (
        "SALIR: la cookie de una sesión cerrada sigue dando acceso a /account"
    )


@pytest.mark.cubre("7.M1", "REG-15")
@pytest.mark.parametrize("ruta", ["/entities", "/jobs", "/status", "/account"])
def test_el_boton_atras_tras_salir_no_devuelve_la_pantalla_protegida(contexto, cfg, evidencia, ruta):
    """7.M1: «tras el logout no se ve contenido protegido», tampoco con el
    botón «atrás» del navegador, que sirve la pantalla desde su caché si el
    producto no la marca como no almacenable.

    Recorrido: entrar → la pantalla → inicio → «Salir» → atrás, atrás. Lo
    que se juzga es la SEGUNDA vuelta, que cae en la pantalla medida."""
    ctx = contexto("sesion")
    pagina = ctx.new_page()
    iniciar_sesion(pagina, cfg, cfg.cuenta("sesion"))
    protegida = ir(pagina, cfg, ruta)
    evidencia.paso(pagina, f"{ruta} antes de salir", estado=protegida.status)
    antes = texto_visible(pagina, "main")
    cabeceras = {c: protegida.headers.get(c) for c in ("cache-control", "pragma", "expires")}
    evidencia.dato("cabeceras de caché de la pantalla protegida", cabeceras)
    ir(pagina, cfg, "/")
    with pagina.expect_navigation():
        pagina.click("header.topbar form[action='/logout'] button")
    assert ruta_de(pagina) == "/login", f"ATRÁS: preparación: salir llevó a {ruta_de(pagina)}"
    pagina.go_back(wait_until="domcontentloaded")
    evidencia.paso(pagina, "primer atrás (inicio)")
    inicio_visible = pagina.locator("#login-form").count() == 0 and ruta_de(pagina) == "/"
    pagina.go_back(wait_until="domcontentloaded")
    evidencia.paso(pagina, "segundo atrás (la pantalla medida)")
    cuerpo = texto_visible(pagina)
    visible = pagina.locator("#login-form").count() == 0 and ruta_de(pagina) == ruta
    evidencia.dato("tras el botón atrás", {
        "ruta": ruta_de(pagina), "pantalla_protegida_visible": visible,
        "inicio_visible_en_el_primer_atras": inicio_visible, "texto": cuerpo[:300],
    })
    assert not visible, (
        f"ATRÁS: tras salir, el botón «atrás» vuelve a mostrar {ruta} sin pedir entrar "
        f"(Cache-Control de esa pantalla: {cabeceras['cache-control']!r}): {cuerpo[:140]!r}"
    )
    assert not inicio_visible, (
        "ATRÁS: tras salir, el botón «atrás» vuelve a mostrar el inicio con la barra de sesión"
    )
    assert antes, "ATRÁS: preparación: la pantalla medida no tenía contenido"


@pytest.mark.cubre("extra.sesion", "REG-15")
def test_tras_entrar_se_vuelve_a_la_pantalla_pedida(contexto, cfg, evidencia):
    ctx = contexto("sesion")
    pagina = ctx.new_page()
    ir(pagina, cfg, "/jobs")
    assert ruta_de(pagina) == "/login", "VOLVER: preparación: /jobs sin sesión no llevó al login"
    assert "next=/jobs" in pagina.url, f"VOLVER: el login no recuerda la pantalla pedida: {pagina.url}"
    cuenta = cfg.cuenta("sesion")
    pagina.fill("#username", cuenta["username"])
    pagina.fill("#password", cuenta["password"])
    enviar_login(pagina)
    evidencia.paso(pagina, "tras entrar desde jobs")
    assert ruta_de(pagina) == "/jobs", f"VOLVER: tras entrar se acabó en {ruta_de(pagina)}, no en /jobs"


@pytest.mark.cubre("extra.sesion", "REG-15")
def test_una_entrada_nueva_revoca_la_sesion_anterior(contexto, cfg, evidencia):
    primero = contexto("primer-navegador")
    p1 = primero.new_page()
    iniciar_sesion(p1, cfg, cfg.cuenta("sesion"))
    ir(p1, cfg, "/account")
    assert ruta_de(p1) == "/account", "ROTACIÓN: preparación: el primer navegador no entró"

    segundo = contexto("segundo-navegador")
    p2 = segundo.new_page()
    iniciar_sesion(p2, cfg, cfg.cuenta("sesion"))
    ir(p2, cfg, "/account")
    evidencia.paso(p2, "segundo navegador dentro")
    assert ruta_de(p2) == "/account", "ROTACIÓN: el segundo navegador no entró"

    ir(p1, cfg, "/account")
    evidencia.paso(p1, "primer navegador tras la segunda entrada")
    assert ruta_de(p1) == "/login", (
        "ROTACIÓN: la sesión anterior sigue viva después de una entrada nueva del mismo usuario"
    )


# ---------------------------------------------------------------------------
# Credenciales que no valen
# ---------------------------------------------------------------------------

@pytest.mark.cubre("7.M2", "REG-15")
@pytest.mark.parametrize("caso", ["contrasena_erronea", "usuario_inexistente", "cuenta_desactivada"])
def test_credenciales_que_no_valen(contexto, cfg, evidencia, redactor, caso):
    ctx = contexto(caso)
    pagina = ctx.new_page()
    if caso == "contrasena_erronea":
        usuario, clave = cfg.cuenta("sesion")["username"], "no-es-" + secrets.token_urlsafe(9)
    elif caso == "usuario_inexistente":
        usuario, clave = "rc3nav_nadie_" + secrets.token_hex(3), "no-es-" + secrets.token_urlsafe(9)
    else:
        usuario, clave = cfg.cuenta("inactivo")["username"], cfg.cuenta("inactivo")["password"]
    redactor.registrar(clave)
    rellenar_login(pagina, cfg, usuario, clave)
    respuesta = enviar_login(pagina)
    evidencia.paso(pagina, caso, estado=respuesta.status)
    assert respuesta.status == 401, f"NO_VALE[{caso}]: POST /login respondió {respuesta.status}, se esperaba 401"
    assert ruta_de(pagina) == "/login", f"NO_VALE[{caso}]: se acabó en {ruta_de(pagina)}"
    aviso = pagina.locator("[role=alert]")
    assert aviso.count() == 1, f"NO_VALE[{caso}]: no hay un único aviso de error"
    # El MISMO texto en los tres casos: la pantalla no dice si el usuario
    # existe ni si la cuenta está desactivada.
    assert aviso.inner_text().strip() == MENSAJE_CREDENCIALES, (
        f"NO_VALE[{caso}]: el aviso dice {aviso.inner_text().strip()!r}"
    )
    assert _cookie(ctx, COOKIE_SESION) is None, f"NO_VALE[{caso}]: se emitió cookie de sesión"
    assert pagina.input_value("#password") == "", f"NO_VALE[{caso}]: la contraseña se repinta en el formulario"
    ir(pagina, cfg, "/account")
    assert ruta_de(pagina) == "/login", f"NO_VALE[{caso}]: tras el rechazo se ve /account"


@pytest.mark.cubre("extra.sesion", "REG-15")
def test_escribir_y_pulsar_intro_en_los_campos_no_envia(contexto, cfg, evidencia):
    """Contrato de envío explícito del formulario: sólo el botón envía."""
    ctx = contexto("intro")
    pagina = ctx.new_page()
    envios = []
    pagina.on("request", lambda r: envios.append(r.url) if r.method == "POST" else None)
    rellenar_login(pagina, cfg, cfg.cuenta("sesion")["username"], "incompleta")
    pagina.press("#password", "Enter")
    pagina.wait_for_timeout(800)
    evidencia.paso(pagina, "intro en el campo de contraseña")
    assert envios == [], f"ENVÍO_IMPLÍCITO: Intro dentro del campo envió el formulario: {envios}"
    assert ruta_de(pagina) == "/login", "ENVÍO_IMPLÍCITO: la página navegó"


@pytest.mark.cubre("extra.sesion", "REG-15")
def test_formulario_sin_testigo_csrf_se_rechaza(pagina_anonima, cfg, evidencia):
    ir(pagina_anonima, cfg, "/login")
    cuenta = cfg.cuenta("sesion")
    r = fetch_en_pagina(pagina_anonima, "POST", "/login", formulario={
        "username": cuenta["username"], "password": cuenta["password"],
        "csrf_token": "falsificado", "next": "/",
    })
    evidencia.dato("POST /login con testigo falsificado", {"estado": r["estado"], "url": r["url"]})
    assert r["estado"] == 403, f"CSRF_LOGIN: un testigo falsificado obtuvo {r['estado']}, se esperaba 403"
    assert "Error de seguridad" in r["texto"], "CSRF_LOGIN: la respuesta no explica el rechazo"
    ir(pagina_anonima, cfg, "/account")
    assert ruta_de(pagina_anonima) == "/login", "CSRF_LOGIN: el envío falsificado abrió sesión"


# ---------------------------------------------------------------------------
# Bloqueo por intentos y desbloqueo por el administrador
# ---------------------------------------------------------------------------

@pytest.mark.cubre("7.M2", "REG-15")
def test_bloqueo_por_intentos_y_desbloqueo_desde_la_administracion(
        contexto, pagina_como, cfg, evidencia, redactor):
    cuenta = cfg.cuenta("bloqueo")
    ctx = contexto("bloqueo")
    pagina = ctx.new_page()

    # Punto de partida conocido: la cuenta entra.
    r = iniciar_sesion(pagina, cfg, cuenta)
    assert r.status == 302, (
        f"BLOQUEO: preparación: la cuenta no entra antes de empezar (POST {r.status}); "
        "¿quedó bloqueada de una tanda anterior? Vuelve a ejecutar usuarios_de_prueba.py crear"
    )
    ctx.clear_cookies()

    mala = "no-es-" + secrets.token_urlsafe(9)
    redactor.registrar(mala)
    for intento in range(1, cfg.max_intentos + 1):
        rellenar_login(pagina, cfg, cuenta["username"], mala)
        r = enviar_login(pagina)
        assert r.status == 401, f"BLOQUEO: el intento fallido {intento} respondió {r.status}"
    evidencia.paso(pagina, f"tras {cfg.max_intentos} intentos fallidos", estado=r.status)

    r = iniciar_sesion(pagina, cfg, cuenta)
    evidencia.paso(pagina, "contraseña correcta con la cuenta bloqueada", estado=r.status)
    assert r.status == 401, (
        f"BLOQUEO: tras {cfg.max_intentos} fallos la contraseña CORRECTA obtuvo {r.status}: la cuenta no se bloqueó"
    )
    assert pagina.locator("[role=alert]").inner_text().strip() == MENSAJE_CREDENCIALES, (
        "BLOQUEO: el aviso de una cuenta bloqueada difiere del de credenciales erróneas"
    )

    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/users")
    fila = admin.locator("table.data-table tbody tr", has=admin.locator(f"td:text-is('{cuenta['username']}')"))
    assert fila.count() == 1, "BLOQUEO: la cuenta no aparece en la administración de usuarios"
    evidencia.paso(admin, "administración con la cuenta bloqueada")
    assert fila.locator("td").nth(5).inner_text().strip() == "Sí", (
        "BLOQUEO: la administración no muestra la cuenta como bloqueada"
    )
    with admin.expect_navigation():
        fila.locator("form[action$='/unlock'] button").click()
    ir(admin, cfg, "/admin/users")
    fila = admin.locator("table.data-table tbody tr", has=admin.locator(f"td:text-is('{cuenta['username']}')"))
    evidencia.paso(admin, "tras desbloquear")
    assert fila.locator("td").nth(5).inner_text().strip() == "No", (
        "BLOQUEO: tras pulsar «Desbloquear» la cuenta sigue figurando como bloqueada"
    )

    r = iniciar_sesion(pagina, cfg, cuenta)
    evidencia.paso(pagina, "entra tras el desbloqueo", estado=r.status)
    assert r.status == 302 and ruta_de(pagina) == "/", (
        f"BLOQUEO: tras el desbloqueo la cuenta no entra (POST {r.status}, {ruta_de(pagina)})"
    )


# ---------------------------------------------------------------------------
# Cambio de contraseña obligatorio
# ---------------------------------------------------------------------------

@pytest.mark.cubre("extra.sesion", "REG-15")
def test_cambio_de_contrasena_obligatorio_al_primer_acceso(contexto, cfg, evidencia, redactor):
    """La cuenta ``cambio`` se crea con la obligación de cambiar la contraseña.

    Al terminar, la prueba deja la contraseña ORIGINAL (la del fichero de
    credenciales); la obligación ya no vuelve sola: antes de repetir la tanda
    hay que ejecutar ``usuarios_de_prueba.py crear``, que la repone.
    """
    cuenta = cfg.cuenta("cambio")
    ctx = contexto("cambio")
    pagina = ctx.new_page()
    r = iniciar_sesion(pagina, cfg, cuenta, siguiente="/jobs")
    evidencia.paso(pagina, "primer acceso", estado=r.status)
    assert r.status == 302, f"CAMBIO: preparación: la cuenta no entra (POST {r.status})"
    assert ruta_de(pagina) == "/account/change-password", (
        f"CAMBIO: el primer acceso llevó a {ruta_de(pagina)}, no a la pantalla de cambio de contraseña "
        "(si la cuenta ya cambió su contraseña en una tanda anterior, repón la obligación con "
        "usuarios_de_prueba.py crear)"
    )

    # Mientras no cambie, el resto del producto no se sirve.
    ir(pagina, cfg, "/jobs")
    evidencia.paso(pagina, "intento de ir a jobs sin cambiar")
    assert ruta_de(pagina) == "/account/change-password", (
        f"CAMBIO: con el cambio pendiente se pudo abrir {ruta_de(pagina)}"
    )
    r_api = fetch_en_pagina(pagina, "GET", "/api/entities")
    evidencia.dato("api con el cambio pendiente", {"estado": r_api["estado"], "url": r_api["url"]})
    assert r_api["estado"] != 200 or "/account/change-password" in r_api["url"], (
        "CAMBIO: con el cambio pendiente la API respondió datos"
    )

    nueva = secrets.token_urlsafe(18)
    redactor.registrar(nueva)

    # Contraseña actual equivocada: no cambia nada.
    pagina.fill("#current_password", "no-es-" + nueva[:10])
    pagina.fill("#new_password", nueva)
    pagina.fill("#confirm_password", nueva)
    with pagina.expect_navigation():
        pagina.click("form[action='/account/change-password'] button[type=submit]")
    evidencia.paso(pagina, "contraseña actual equivocada")
    assert pagina.locator("main [role=alert]").count() == 1, "CAMBIO: una contraseña actual equivocada no produjo aviso"
    assert ruta_de(pagina) == "/account/change-password", "CAMBIO: se salió de la pantalla con la actual equivocada"

    # Confirmación distinta: tampoco.
    pagina.fill("#current_password", cuenta["password"])
    pagina.fill("#new_password", nueva)
    pagina.fill("#confirm_password", nueva + "x")
    with pagina.expect_navigation():
        pagina.click("form[action='/account/change-password'] button[type=submit]")
    evidencia.paso(pagina, "confirmación distinta")
    assert pagina.locator("main [role=alert]").count() == 1, "CAMBIO: una confirmación distinta no produjo aviso"

    # Cambio correcto.
    pagina.fill("#current_password", cuenta["password"])
    pagina.fill("#new_password", nueva)
    pagina.fill("#confirm_password", nueva)
    with pagina.expect_navigation():
        pagina.click("form[action='/account/change-password'] button[type=submit]")
    evidencia.paso(pagina, "tras cambiar")
    evidencia.dato("destino tras cambiar", ruta_de(pagina))

    # La contraseña antigua ya no entra; la nueva sí, y sin pantalla de cambio.
    ctx.clear_cookies()
    r = iniciar_sesion(pagina, cfg, cuenta)
    assert r.status == 401, f"CAMBIO: la contraseña ANTIGUA sigue entrando (POST {r.status})"
    r = iniciar_sesion(pagina, cfg, {"username": cuenta["username"], "password": nueva})
    evidencia.paso(pagina, "entra con la nueva", estado=r.status)
    assert r.status == 302 and ruta_de(pagina) == "/", (
        f"CAMBIO: la contraseña nueva no entra limpia (POST {r.status}, {ruta_de(pagina)})"
    )

    # Reposición: vuelve a la contraseña del fichero de credenciales.
    ir(pagina, cfg, "/account/change-password")
    pagina.fill("#current_password", nueva)
    pagina.fill("#new_password", cuenta["password"])
    pagina.fill("#confirm_password", cuenta["password"])
    with pagina.expect_navigation():
        pagina.click("form[action='/account/change-password'] button[type=submit]")
    ctx.clear_cookies()
    r = iniciar_sesion(pagina, cfg, cuenta)
    assert r.status == 302, (
        "CAMBIO: REPOSICIÓN fallida: la cuenta no volvió a su contraseña original; "
        "ejecuta usuarios_de_prueba.py crear antes de repetir"
    )
