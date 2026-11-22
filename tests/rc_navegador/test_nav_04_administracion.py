# -*- coding: utf-8 -*-
"""Administración de usuarios desde la web y su efecto sobre sesiones vivas.

Contrato: E7 (autenticación, sesiones y persistencia; GATE B deja un
administrador que gestiona al resto) y regresión 15. Ninguna prueba necesita
Neo4j.

Estas pruebas crean UNA cuenta nueva por tanda desde la pantalla de
administración (``rc3nav_web_<aleatorio>``) y la dejan DESACTIVADA al
terminar: el producto no ofrece borrar usuarios. Su contraseña se genera en la
prueba y no se guarda en ningún sitio.
"""
from __future__ import annotations

import secrets

import pytest

from soporte import enlaces_de_navegacion, iniciar_sesion, ir, ruta_de, texto_visible

pytestmark = [pytest.mark.sin_grafo]


def _fila(admin, usuario: str):
    return admin.locator("table.data-table tbody tr", has=admin.locator(f"td:text-is('{usuario}')"))


def _celdas(fila) -> list[str]:
    return [c.strip() for c in fila.locator("td").all_inner_texts()]


def _enviar(pagina) -> None:
    with pagina.expect_navigation():
        pagina.click("main form button[type=submit].btn-primary")


@pytest.mark.cubre("extra.admin", "REG-15")
def test_alta_de_usuario_con_datos_que_no_valen(pagina_como, cfg, evidencia, redactor):
    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/users/new")
    corta = "corta-" + secrets.token_hex(2)          # menos de 12 caracteres
    redactor.registrar(corta)
    nombre = "rc3nav_web_nulo_" + secrets.token_hex(2)
    admin.fill("#username", nombre)
    admin.fill("#display_name", "No se crea")
    admin.fill("#password", corta)
    _enviar(admin)
    evidencia.paso(admin, "contraseña demasiado corta")
    assert admin.locator("main [role=alert]").count() == 1, "ALTA_INVÁLIDA: una contraseña corta no produjo aviso"
    assert "12" in admin.locator("main [role=alert]").inner_text(), "ALTA_INVÁLIDA: el aviso no dice el mínimo exigido"

    # Usuario que ya existe.
    existente = cfg.cuenta("lector")["username"]
    larga = secrets.token_urlsafe(18)
    redactor.registrar(larga)
    ir(admin, cfg, "/admin/users/new")
    admin.fill("#username", existente)
    admin.fill("#display_name", "Duplicado")
    admin.fill("#password", larga)
    _enviar(admin)
    evidencia.paso(admin, "usuario duplicado")
    assert admin.locator("main [role=alert]").count() == 1, "ALTA_INVÁLIDA: un usuario duplicado no produjo aviso"

    ir(admin, cfg, "/admin/users")
    assert _fila(admin, nombre).count() == 0, "ALTA_INVÁLIDA: la cuenta con contraseña corta se creó"
    assert _fila(admin, existente).count() == 1, "ALTA_INVÁLIDA: el duplicado creó una segunda fila"


@pytest.mark.cubre("extra.admin", "REG-15")
def test_ciclo_de_vida_de_un_usuario_desde_la_administracion(pagina_como, contexto, cfg, evidencia, redactor):
    admin = pagina_como("admin")
    usuario = "rc3nav_web_" + secrets.token_hex(3)
    clave = secrets.token_urlsafe(18)
    redactor.registrar(clave)
    cuenta = {"username": usuario, "password": clave}

    # --- alta ---------------------------------------------------------------
    ir(admin, cfg, "/admin/users")
    with admin.expect_navigation():
        admin.click("a[href='/admin/users/new']")
    assert admin.is_checked("input[name=must_change_password]"), (
        "CICLO: el alta no propone por defecto «debe cambiar contraseña al primer acceso»"
    )
    admin.fill("#username", usuario)
    admin.fill("#display_name", "Creada desde la web")
    admin.select_option("#role", value="viewer")
    admin.fill("#password", clave)
    admin.uncheck("input[name=must_change_password]")
    evidencia.paso(admin, "formulario de alta")
    _enviar(admin)
    evidencia.paso(admin, "tras el alta")
    assert admin.locator("main [role=alert]").count() == 0, (
        f"CICLO: el alta produjo un aviso: {texto_visible(admin, 'main [role=alert]')}"
    )
    ir(admin, cfg, "/admin/users")
    fila = _fila(admin, usuario)
    assert fila.count() == 1, "CICLO: la cuenta recién creada no aparece en la administración"
    celdas = _celdas(fila)
    evidencia.dato("fila recién creada", celdas[:6])
    assert celdas[3] == "viewer" and celdas[4] == "Sí" and celdas[5] == "No", (
        f"CICLO: la fila no dice viewer / activo / sin bloqueo: {celdas[:6]}"
    )
    id_usuario = celdas[0]

    try:
        # --- la cuenta entra, como lector -----------------------------------
        ctx = contexto("usuario-nuevo")
        nuevo = ctx.new_page()
        r = iniciar_sesion(nuevo, cfg, cuenta)
        evidencia.paso(nuevo, "la cuenta nueva entra", estado=r.status)
        assert r.status == 302 and ruta_de(nuevo) == "/", (
            f"CICLO: la cuenta nueva no entra (POST {r.status}, {ruta_de(nuevo)})"
        )
        menu_lector = enlaces_de_navegacion(nuevo)
        assert "admin_users" not in menu_lector and "sources_page" not in menu_lector, (
            f"CICLO: una cuenta viewer recién creada ve {menu_lector}"
        )

        # --- cambio de rol: surte efecto en la sesión viva --------------------
        ir(admin, cfg, f"/admin/users/{id_usuario}")
        admin.select_option("#role", value="reviewer")
        _enviar(admin)
        ir(nuevo, cfg, "/")
        evidencia.paso(nuevo, "tras subir a revisor")
        menu_revisor = enlaces_de_navegacion(nuevo)
        evidencia.dato("menú antes y después", {"viewer": menu_lector, "reviewer": menu_revisor})
        assert "sources_page" in menu_revisor and "admin_users" not in menu_revisor, (
            f"CICLO: tras pasar a reviewer el menú es {menu_revisor}"
        )
        ir(admin, cfg, f"/admin/users/{id_usuario}")
        admin.select_option("#role", value="viewer")
        _enviar(admin)
        r = ir(nuevo, cfg, "/sources")
        assert r.status == 403, f"CICLO: tras volver a viewer, /sources respondió {r.status} a la sesión viva"

        # --- revocar sesiones -----------------------------------------------
        ir(admin, cfg, f"/admin/users/{id_usuario}")
        with admin.expect_navigation():
            admin.click("form[action$='/revoke-sessions'] button")
        evidencia.paso(admin, "sesiones revocadas")
        ir(nuevo, cfg, "/account")
        evidencia.paso(nuevo, "la sesión revocada ya no vale")
        assert ruta_de(nuevo) == "/login", "CICLO: tras «Revocar sesiones activas» la sesión sigue abriendo /account"
        r = iniciar_sesion(nuevo, cfg, cuenta)
        assert r.status == 302, "CICLO: tras revocar sesiones la cuenta no puede volver a entrar"

        # --- desactivar ------------------------------------------------------
        ir(admin, cfg, f"/admin/users/{id_usuario}")
        admin.uncheck("input[name=is_active]")
        _enviar(admin)
        ir(admin, cfg, "/admin/users")
        evidencia.paso(admin, "cuenta desactivada")
        assert _celdas(_fila(admin, usuario))[4] == "No", "CICLO: la administración no muestra la cuenta como inactiva"
        ir(nuevo, cfg, "/account")
        evidencia.paso(nuevo, "sesión de una cuenta desactivada")
        assert ruta_de(nuevo) == "/login", "CICLO: la sesión viva de una cuenta desactivada sigue abriendo /account"
        r = iniciar_sesion(nuevo, cfg, cuenta)
        evidencia.paso(nuevo, "la cuenta desactivada no entra", estado=r.status)
        assert r.status == 401, f"CICLO: una cuenta desactivada obtuvo {r.status} al entrar"
    finally:
        # Pase lo que pase, la cuenta no queda activa.
        ir(admin, cfg, f"/admin/users/{id_usuario}")
        if admin.locator("input[name=is_active]").count() and admin.is_checked("input[name=is_active]"):
            admin.uncheck("input[name=is_active]")
            _enviar(admin)

    # --- auditoría ----------------------------------------------------------
    # Las acciones de administración se anotan a nombre de QUIEN las hace.
    ir(admin, cfg, f"/admin/audit?user_param={cfg.cuenta('admin')['username']}")
    evidencia.paso(admin, "auditoría del administrador")
    eventos = admin.eval_on_selector_all(
        "table.data-table tbody tr",
        "els => els.map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim()))",
    )
    tipos = {e[2] for e in eventos if len(e) >= 4}
    evidencia.dato("eventos auditados del administrador", sorted(tipos))
    faltan = {"USER_CREATED", "ROLE_CHANGED", "SESSIONS_REVOKED", "USER_DISABLED"} - tipos
    assert not faltan, f"CICLO: la auditoría no recoge {sorted(faltan)} del ciclo de vida de la cuenta"
    cuerpo = admin.content()
    assert clave not in cuerpo, "CICLO: la auditoría muestra la contraseña de la cuenta"
    # Dato, sin contrato escrito: ¿dice la pantalla SOBRE QUIÉN fue cada acción?
    evidencia.dato("la auditoría por pantalla nombra la cuenta afectada", usuario in cuerpo)
