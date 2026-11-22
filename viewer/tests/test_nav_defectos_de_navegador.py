"""Defectos de navegador NAV-01, NAV-02, NAV-03 y NAV-06 (batería RC3).

Los cuatro salieron de abrir el visor real con un navegador. Cada garantía se
mide por ejecución HTTP contra la aplicación real y, donde la propiedad es
«TODAS las rutas», recorriendo el router (introspección), no una lista escrita a
mano: una ruta nueva que se salte la garantía pone rojo sin tocar este fichero.

 * NAV-01  toda respuesta que no sea un estático público lleva
           ``Cache-Control: no-store`` (tras «Salir», «atrás» no repinta nada).
 * NAV-02  toda pantalla HTML protegida muestra usuario, rol y «Salir».
 * NAV-03  un 403 por rol y un 404 pedidos por un navegador son HTML; la API
           sigue en JSON.
 * NAV-06  con UN solo worker, el informe de salud servido por el visor no se
           bloquea a sí mismo: el componente ``viewer`` sale HEALTHY.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from contextlib import closing

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount

PW = "contrasena-de-laboratorio-1234567890-ABCdef"
NOMBRES = {"viewer": "Lola Lectora", "reviewer": "Rafa Revisor", "admin": "Ada Admin"}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(db))
    monkeypatch.setenv("S9K_CSRF_SECRET", "clave-csrf-larga-y-aleatoria-para-tests-1234567890")
    monkeypatch.setenv("S9K_SESSION_SECURE", "false")
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last_report.json"))
    from app.auth.config import get_auth_settings

    get_auth_settings.cache_clear()
    from app.auth import db as auth_db

    auth_db.ensure_migrated(db)
    yield db
    get_auth_settings.cache_clear()


def _sesion(db, rol):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db) as conn:
        u = auth_db.create_user(conn, username=f"u_{rol}", display_name=NOMBRES[rol],
                                password_hash=hash_password(PW), role=rol,
                                must_change_password=False)
        token, _s = create_session(conn, u)
    return token


def _cliente(db, rol=None):
    from fastapi.testclient import TestClient

    from app.auth.config import get_auth_settings
    from app.main import app

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if rol:
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, _sesion(db, rol))
    return c


def _rutas_get():
    """(ruta con parámetros rellenados, plantilla) de TODAS las rutas GET montadas."""
    from app.main import app

    vistas = []
    for r in app.routes:
        if isinstance(r, Mount):
            continue
        if isinstance(r, APIRoute) and "GET" in r.methods:
            vistas.append((re.sub(r"\{[^}]+\}", "x", r.path), r.path))
        elif not isinstance(r, APIRoute) and getattr(r, "methods", None) and "GET" in r.methods:
            vistas.append((re.sub(r"\{[^}]+\}", "x", r.path), r.path))
    assert len(vistas) > 30, f"la introspección vio sólo {len(vistas)} rutas GET"
    return sorted(set(vistas))


@pytest.fixture
def salud_ligera(monkeypatch):
    """Evita sondeos de red al recorrer /admin/health: aquí no se mide la salud."""
    from app.health.models import ComponentResult, HealthReport, HealthStatus

    monkeypatch.setattr(
        "app.routers.health_admin.runner.run_report",
        lambda **k: HealthReport([ComponentResult("x", HealthStatus.HEALTHY)]),
    )


# Estáticos públicos: la ÚNICA excepción a «sin caché». No se listan rutas
# sueltas: son los montajes (`Mount`) y el icono.
def _es_estatico_publico(ruta):
    return ruta.startswith("/static") or ruta == "/favicon.ico"


# ---------------------------------------------------------------------------
# NAV-01
# ---------------------------------------------------------------------------

def test_nav01_toda_ruta_get_lleva_no_store_para_cada_rol(entorno, salud_ligera):
    sin = []
    for rol in ("admin", "reviewer", "viewer", None):
        c = _cliente(entorno, rol)
        for ruta, plantilla in _rutas_get():
            if _es_estatico_publico(ruta):
                continue
            r = c.get(ruta, headers={"accept": "text/html"})
            cc = r.headers.get("cache-control", "")
            if "no-store" not in cc:
                sin.append(f"{rol or 'anonimo'} {plantilla} -> {r.status_code} cache-control={cc!r}")
    assert not sin, "NAV-01: respuestas sin no-store: " + "; ".join(sin)


def test_nav01_la_cabecera_tambien_va_en_json_de_la_api(entorno):
    c = _cliente(entorno, "admin")
    r = c.get("/api/status", headers={"accept": "application/json"})
    assert r.status_code == 200, f"/api/status dio {r.status_code}"
    assert "no-store" in r.headers.get("cache-control", ""), (
        "NAV-01: el JSON de la API autenticada no lleva no-store")


def test_nav01_negativo_los_estaticos_siguen_cacheables(entorno):
    c = _cliente(entorno, "admin")
    r = c.get("/static/css/app.css")
    assert r.status_code == 200, f"el CSS estático dio {r.status_code}"
    assert "no-store" not in r.headers.get("cache-control", ""), (
        "NAV-01 (negativo): se aplicó no-store a un estático público")


def test_nav01_negativo_anonimo_sigue_recibiendo_302_o_401(entorno):
    c = _cliente(entorno)
    html = c.get("/entities", headers={"accept": "text/html"})
    assert html.status_code == 302, f"anónimo + navegador debía ser 302, fue {html.status_code}"
    api = c.get("/api/status", headers={"accept": "application/json"})
    assert api.status_code == 401, f"anónimo + API debía ser 401, fue {api.status_code}"


# ---------------------------------------------------------------------------
# NAV-02
# ---------------------------------------------------------------------------

# Pantallas que NO son de sesión: se sirven a quien aún no la tiene o no usan
# la barra (formulario de entrada, alta del primer administrador).
_SIN_BARRA_DE_SESION = ("/login", "/setup", "/account/change-password")


@pytest.mark.parametrize("rol", ["admin", "reviewer", "viewer"])
def test_nav02_toda_pantalla_html_protegida_muestra_usuario_rol_y_salir(
        entorno, salud_ligera, rol):
    c = _cliente(entorno, rol)
    fallos, vistas = [], 0
    for ruta, plantilla in _rutas_get():
        if _es_estatico_publico(ruta) or ruta.startswith(_SIN_BARRA_DE_SESION):
            continue
        r = c.get(ruta, headers={"accept": "text/html"})
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        vistas += 1
        falta = []
        if NOMBRES[rol] not in r.text:
            falta.append("usuario")
        if f"role-{rol}" not in r.text:
            falta.append("rol")
        if 'action="/logout"' not in r.text:
            falta.append("salir")
        if falta:
            fallos.append(f"{plantilla} sin {'/'.join(falta)}")
    assert vistas >= 8, f"el recorrido sólo vio {vistas} pantallas HTML con 200"
    assert not fallos, f"NAV-02 ({rol}): " + "; ".join(fallos)


def test_nav02_el_menu_del_rol_aparece_en_la_administracion(entorno, salud_ligera):
    c = _cliente(entorno, "admin")
    r = c.get("/admin/users", headers={"accept": "text/html"})
    assert r.status_code == 200, f"/admin/users dio {r.status_code}"
    assert 'data-nav="' in r.text and "/admin/users" in r.text and "Cuenta" in r.text, (
        "NAV-02: la barra de /admin/users no trae el menú del administrador")


# ---------------------------------------------------------------------------
# NAV-03
# ---------------------------------------------------------------------------

def test_nav03_403_por_rol_es_html_para_navegador_y_json_para_api(entorno):
    c = _cliente(entorno, "viewer")
    nav = c.get("/admin/users", headers={"accept": "text/html"})
    assert nav.status_code == 403, f"se esperaba 403, fue {nav.status_code}"
    assert "text/html" in nav.headers.get("content-type", ""), (
        f"NAV-03: el 403 del navegador no es HTML: {nav.headers.get('content-type')!r}")
    assert '{"detail"' not in nav.text, "NAV-03: el cuerpo del 403 es JSON crudo"
    api = c.get("/api/admin/health", headers={"accept": "application/json"})
    assert api.status_code == 403, f"la API debía dar 403, fue {api.status_code}"
    assert api.json().get("detail"), "la API dejó de devolver JSON con detail"
    # La API sigue en JSON aunque quien pregunte acepte HTML.
    api_html = c.get("/api/admin/health", headers={"accept": "text/html"})
    assert "application/json" in api_html.headers.get("content-type", ""), (
        "NAV-03: una ruta /api/ pasó a HTML")


@pytest.mark.parametrize("rol", ["admin", None])
def test_nav03_404_es_html_para_navegador_sin_filtrar_nada(entorno, rol):
    c = _cliente(entorno, rol)
    nav = c.get("/esta/direccion/no/existe", headers={"accept": "text/html"})
    assert nav.status_code == 404, f"se esperaba 404, fue {nav.status_code}"
    assert "text/html" in nav.headers.get("content-type", ""), (
        f"NAV-03: el 404 del navegador no es HTML: {nav.headers.get('content-type')!r}")
    for prohibido in ("Traceback", "/home/", "site-packages", ".py", "Not Found"):
        assert prohibido not in nav.text, f"NAV-03: la página de error filtra {prohibido!r}"
    json_ = c.get("/esta/direccion/no/existe", headers={"accept": "application/json"})
    assert json_.status_code == 404
    assert json_.json() == {"detail": "Not Found"}, "el 404 de un cliente JSON cambió"
    assert "no-store" in nav.headers.get("cache-control", ""), "el 404 HTML no lleva no-store"


def test_nav03_la_pagina_403_no_vuelca_el_detalle_interno(entorno):
    c = _cliente(entorno, "viewer")
    r = c.get("/admin/users", headers={"accept": "text/html"})
    assert "se requiere rol admin" not in r.text.lower(), (
        "NAV-03: la página 403 reproduce el texto interno de la excepción")


# ---------------------------------------------------------------------------
# NAV-06 — servidor REAL de un solo worker (como el servicio de producción)
# ---------------------------------------------------------------------------

def _puerto_libre() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def servidor_un_worker(entorno, monkeypatch):
    import uvicorn

    puerto = _puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    # El visor se sondea por la URL que declara su entorno, igual que el servicio.
    monkeypatch.setenv("S9K_HEALTH_VIEWER_URL", base)
    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="error", workers=1)
    server = uvicorn.Server(config)
    hilo = threading.Thread(target=server.run, daemon=True)
    hilo.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:  # pragma: no cover
        raise RuntimeError("el visor de pruebas no arrancó")
    try:
        yield base
    finally:
        server.should_exit = True
        hilo.join(timeout=10)


def _componente_viewer(informe: dict) -> dict:
    return next(c for c in informe["components"] if c["component"] == "viewer")


def test_nav06_el_informe_del_visor_no_se_bloquea_a_si_mismo(entorno, servidor_un_worker):
    import httpx

    from app.auth.config import get_auth_settings

    token = _sesion(entorno, "admin")
    cookies = {get_auth_settings().S9K_SESSION_COOKIE_NAME: token}
    t0 = time.perf_counter()
    r = httpx.get(servidor_un_worker + "/api/admin/health", cookies=cookies,
                  headers={"accept": "application/json"}, timeout=60)
    dur = time.perf_counter() - t0
    assert r.status_code == 200, f"/api/admin/health dio {r.status_code}"
    viewer = _componente_viewer(r.json())
    assert viewer["status"] == "HEALTHY", (
        f"NAV-06: el visor que sirve la petición figura como {viewer['status']} "
        f"({viewer['message']!r}) tras {dur:.1f} s")
    assert "ReadTimeout" not in viewer["message"], f"NAV-06: {viewer['message']!r}"


def test_nav06_la_pantalla_y_la_instantanea_dicen_lo_mismo(entorno, servidor_un_worker, tmp_path):
    import httpx

    from app.auth.config import get_auth_settings

    token = _sesion(entorno, "admin")
    cookies = {get_auth_settings().S9K_SESSION_COOKIE_NAME: token}
    pant = httpx.get(servidor_un_worker + "/admin/health", cookies=cookies,
                     headers={"accept": "text/html"}, timeout=60)
    assert pant.status_code == 200, f"/admin/health dio {pant.status_code}"
    assert "ReadTimeout" not in pant.text, "NAV-06: la pantalla publica ReadTimeout del propio visor"
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', pant.text)
    assert m, "la pantalla de salud no trae el formulario de instantánea"
    p = httpx.post(servidor_un_worker + "/admin/health/snapshot", cookies=cookies,
                   data={"csrf_token": m.group(1)}, timeout=60, follow_redirects=False)
    assert p.status_code == 302, f"la instantánea dio {p.status_code}"
    guardado = json.loads((tmp_path / "health" / "last_report.json").read_text(encoding="utf-8"))
    assert _componente_viewer(guardado)["status"] == "HEALTHY", (
        f"NAV-06: la instantánea guarda el visor como {_componente_viewer(guardado)['status']}")
