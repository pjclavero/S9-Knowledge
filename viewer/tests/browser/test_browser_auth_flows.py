# -*- coding: utf-8 -*-
"""E2E de navegador: sesion, roles y revocacion.

Todo pasa por la aplicacion real: formulario de login, cookie de sesion emitida
por el servidor, guardas de rol de produccion y panel de admin de verdad. No hay
ni un mock de autorizacion: si estas pruebas pasan, es porque el producto deniega
de verdad, no porque una simulacion lo diga.
"""
from __future__ import annotations

import pytest

from e2e_support import (
    DISABLED_PW,
    create_lab_user,
    do_login,
    fetch_status,
    is_allowed,
    is_denied,
    is_logged_in,
    login_as,
)

# Rutas que un usuario autenticado con rol insuficiente NO debe poder abrir.
ADMIN_ONLY_PATHS = ["/admin/users", "/admin/audit", "/admin/partidas"]
REVIEWER_ONLY_PATHS = ["/reviews", "/sources"]


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

def test_login_correcto_entra_y_muestra_identidad(page, viewer):
    login_as(page, viewer, "s9viewer")
    assert is_logged_in(page), f"el login correcto no entro: {page.url}"
    assert "Viewer de laboratorio" in page.content()


def test_login_incorrecto_no_entra_ni_filtra_si_el_usuario_existe(page, viewer):
    do_login(page, viewer, "s9viewer", "password-que-no-es")
    assert "/login" in page.url, "credenciales malas dejaron entrar"
    contenido = page.content()
    assert "Usuario o contraseña incorrectos" in contenido
    # Mismo mensaje para usuario inexistente: no se enumera el padron.
    do_login(page, viewer, "no-existe-este-usuario", "password-que-no-es")
    assert "Usuario o contraseña incorrectos" in page.content()


def test_login_incorrecto_no_emite_cookie_de_sesion(page, viewer):
    do_login(page, viewer, "s9viewer", "password-que-no-es")
    cookies = page.context.cookies()
    sesion = [c for c in cookies if "session" in c["name"].lower()]
    assert sesion == [], f"un login fallido emitio cookie de sesion: {sesion}"


def test_logout_cierra_la_sesion_y_la_vuelta_atras_no_la_resucita(page, viewer):
    login_as(page, viewer, "s9viewer")
    assert is_logged_in(page)

    page.click("form[action='/logout'] button")
    page.wait_for_load_state("networkidle")
    assert "/login" in page.url, f"logout no llevo al login: {page.url}"

    # La cookie ya no vale: navegar de nuevo NO devuelve la sesion.
    page.goto(viewer.url("/entities"))
    page.wait_for_load_state("networkidle")
    assert "/login" in page.url, "tras el logout se seguia entrando a /entities"


def test_ruta_protegida_sin_sesion_redirige_al_login_conservando_destino(page, viewer):
    page.goto(viewer.url("/entities"))
    page.wait_for_load_state("networkidle")
    assert "/login" in page.url
    assert "next=/entities" in page.url, f"se perdio el destino: {page.url}"


def test_api_sin_sesion_responde_401_json_no_redireccion(page, viewer):
    resp = page.request.get(viewer.url("/api/entities"))
    assert resp.status == 401, f"la API sin sesion respondio {resp.status}"


# ---------------------------------------------------------------------------
# Roles: quien ve que
# ---------------------------------------------------------------------------

def test_admin_abre_el_panel_de_admin(page, viewer):
    login_as(page, viewer, "s9admin")
    page.goto(viewer.url("/admin/users"))
    page.wait_for_load_state("networkidle")
    assert "Administración de usuarios" in page.content()
    assert page.locator("table.data-table tbody tr").count() >= 4


@pytest.mark.parametrize("path", ADMIN_ONLY_PATHS)
def test_viewer_no_puede_abrir_el_panel_de_admin(new_page, viewer, path):
    pg = new_page()
    login_as(pg, viewer, "s9viewer")
    status = fetch_status(pg, viewer, path)
    assert status == 403, f"{path} devolvio {status} a un viewer"
    assert "Administración de usuarios" not in pg.content()


@pytest.mark.parametrize("path", REVIEWER_ONLY_PATHS)
def test_viewer_no_puede_abrir_las_secciones_de_reviewer(new_page, viewer, path):
    pg = new_page()
    login_as(pg, viewer, "s9viewer")
    status = fetch_status(pg, viewer, path)
    assert status == 403, f"{path} devolvio {status} a un viewer"


def test_reviewer_entra_en_reviews_pero_no_en_admin(page, viewer):
    login_as(page, viewer, "s9reviewer")
    assert is_allowed(page, viewer, "/reviews")
    assert fetch_status(page, viewer, "/admin/users") == 403


def test_la_navegacion_no_ofrece_enlaces_que_el_rol_no_puede_usar(new_page, viewer):
    pg = new_page()
    login_as(pg, viewer, "s9viewer")
    nav = pg.locator("header.topbar nav")
    hrefs = [nav.locator("a").nth(i).get_attribute("href")
             for i in range(nav.locator("a").count())]
    assert not [h for h in hrefs if h and h.startswith("/admin")], \
        f"la nav de un viewer ofrece enlaces de admin: {hrefs}"
    assert "/reviews" not in hrefs


def test_api_de_reviewer_niega_a_viewer_con_403_json(page, viewer):
    login_as(page, viewer, "s9viewer")
    resp = page.request.get(viewer.url("/api/sources"))
    assert resp.status == 403, f"/api/sources respondio {resp.status} a un viewer"


# ---------------------------------------------------------------------------
# Cuenta desactivada
# ---------------------------------------------------------------------------

def test_usuario_desactivado_no_puede_iniciar_sesion(page, viewer):
    do_login(page, viewer, "s9disabled", DISABLED_PW)
    assert "/login" in page.url, "una cuenta desactivada inicio sesion"


def test_desactivar_por_el_panel_corta_la_sesion_viva(new_page, viewer):
    """El admin desmarca "Cuenta activa"; la victima deja de pasar.

    Sin limpiar cookies, sin reiniciar el servidor, sin tocar la base a mano:
    exactamente la secuencia que ocurriria en produccion.
    """
    # Usuario propio: desactivar a s9viewer envenenaria las pruebas siguientes.
    create_lab_user(viewer, "victima_desactivada")
    victima = new_page()
    login_as(victima, viewer, "victima_desactivada")
    assert is_logged_in(victima)
    assert is_allowed(victima, viewer, "/entities")

    admin = new_page()
    login_as(admin, viewer, "s9admin")
    user_id = viewer.users["victima_desactivada"]["id"]
    admin.goto(viewer.url(f"/admin/users/{user_id}"))
    admin.wait_for_load_state("networkidle")
    admin.uncheck("input[name='is_active']")
    admin.click("button[type='submit']")
    admin.wait_for_load_state("networkidle")

    denied, status, url = is_denied(victima, viewer, "/entities")
    assert denied, (
        "una cuenta desactivada siguio navegando con la sesion vieja: "
        f"status={status} url={url}")


# ---------------------------------------------------------------------------
# REVOCACION DE SESION — la prueba que este carril existe para hacer
# ---------------------------------------------------------------------------

def test_revocar_sesiones_deniega_la_siguiente_navegacion(new_page, viewer):
    """peticion autenticada -> revocar -> siguiente peticion denegada.

    No se limpia ninguna cache, no se reinicia nada y no se toca la cookie. Si
    hubiera una cache de sesion que prolongase el permiso, esta prueba se
    pondria roja: es exactamente lo que debe detectar.
    """
    create_lab_user(viewer, "victima_revocada")
    victima = new_page()
    login_as(victima, viewer, "victima_revocada")
    assert is_allowed(victima, viewer, "/entities"), "no hubo peticion autenticada previa"
    cookies_antes = victima.context.cookies()

    admin = new_page()
    login_as(admin, viewer, "s9admin")
    user_id = viewer.users["victima_revocada"]["id"]
    admin.goto(viewer.url(f"/admin/users/{user_id}"))
    admin.wait_for_load_state("networkidle")
    admin.click("form[action$='/revoke-sessions'] button")
    admin.wait_for_load_state("networkidle")

    # La victima NO ha hecho nada: misma pestana, misma cookie.
    assert victima.context.cookies() == cookies_antes, \
        "la prueba altero las cookies de la victima; no probaria nada"

    denied, status, url = is_denied(victima, viewer, "/entities")
    assert denied, (
        "la sesion revocada siguio sirviendo contenido protegido: "
        f"status={status} url={url}")
    assert "/login" in url, f"tras revocar no se llevo al login: {url}"


def test_revocar_sesiones_tambien_corta_la_api_json(new_page, viewer):
    """La misma revocacion, comprobada en la frontera JSON (sin redirecciones)."""
    create_lab_user(viewer, "victima_revocada_api", role="reviewer")
    victima = new_page()
    login_as(victima, viewer, "victima_revocada_api")
    assert victima.request.get(viewer.url("/api/entities")).status == 200

    admin = new_page()
    login_as(admin, viewer, "s9admin")
    user_id = viewer.users["victima_revocada_api"]["id"]
    admin.goto(viewer.url(f"/admin/users/{user_id}"))
    admin.wait_for_load_state("networkidle")
    admin.click("form[action$='/revoke-sessions'] button")
    admin.wait_for_load_state("networkidle")

    resp = victima.request.get(viewer.url("/api/entities"))
    assert resp.status == 401, f"la API acepto una sesion revocada (status={resp.status})"


def test_la_revocacion_no_afecta_a_las_sesiones_de_otros_usuarios(new_page, viewer):
    """Revocar a uno no debe echar a los demas (ni de mas, ni de menos)."""
    create_lab_user(viewer, "victima_aislamiento")
    create_lab_user(viewer, "testigo_aislamiento")
    victima = new_page()
    login_as(victima, viewer, "victima_aislamiento")
    testigo = new_page()
    login_as(testigo, viewer, "testigo_aislamiento")

    admin = new_page()
    login_as(admin, viewer, "s9admin")
    admin.goto(viewer.url(f"/admin/users/{viewer.users['victima_aislamiento']['id']}"))
    admin.wait_for_load_state("networkidle")
    admin.click("form[action$='/revoke-sessions'] button")
    admin.wait_for_load_state("networkidle")

    assert is_denied(victima, viewer, "/entities")[0]
    assert is_allowed(testigo, viewer, "/entities"), \
        "revocar a un usuario echo tambien al testigo"


# ---------------------------------------------------------------------------
# Cookie de sesion: propiedades observables desde el navegador
# ---------------------------------------------------------------------------

def test_la_cookie_de_sesion_es_httponly_y_samesite(page, viewer):
    login_as(page, viewer, "s9viewer")
    cookies = [c for c in page.context.cookies() if "session" in c["name"].lower()]
    assert cookies, "no se emitio cookie de sesion tras un login correcto"
    cookie = cookies[0]
    assert cookie.get("httpOnly") is True, "la cookie de sesion es legible desde JS"
    assert cookie.get("sameSite") in ("Lax", "Strict"), \
        f"SameSite insuficiente: {cookie.get('sameSite')}"


def test_javascript_no_puede_leer_la_cookie_de_sesion(page, viewer):
    login_as(page, viewer, "s9viewer")
    visible = page.evaluate("() => document.cookie")
    assert "session" not in visible.lower(), f"document.cookie expone la sesion: {visible}"
