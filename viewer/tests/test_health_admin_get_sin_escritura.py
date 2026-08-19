"""Los `GET` de salud NO escriben; guardar la instantánea es un POST.

Decisión del operador (2026-08-19), tras el censo de métodos de escritura
(docs/84): *«si esos dos GET provocan escritura, el defecto está en las rutas,
no en la puerta»*. Ninguna exención, ninguna whitelist: se arregló la ruta.

Lo que se afirma aquí, y **por ejecución HTTP contra la app real**, no leyendo
el módulo:

 1. `GET /api/admin/health` con admin devuelve 200 y **no crea** el fichero del
    informe.
 2. `GET /admin/health` con admin devuelve 200 y **no crea** el fichero.
 3. `POST /admin/health/snapshot` con CSRF válido **sí** lo crea y redirige.
 4. Ese POST sin CSRF válido da 403 **y no escribe**.
 5. Anónimo: el POST no escribe (401 o redirección a login).

El punto 3 no es decorativo: si la instantánea dejara de poder guardarse, el
panel de operaciones se quedaría sin fuente desde la interfaz. Se comprueba que
la capacidad **sigue existiendo**, sólo que en un verbo mutador.
"""
from __future__ import annotations

import os
import re

import pytest

pytestmark = pytest.mark.usefixtures("_entorno_auth")


@pytest.fixture
def _entorno_auth(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    informe = tmp_path / "health" / "last_report.json"
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(db))
    monkeypatch.setenv("S9K_CSRF_SECRET", "clave-csrf-larga-y-aleatoria-para-tests-1234567890")
    monkeypatch.setenv("S9K_SESSION_SECURE", "false")
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(informe))

    from app.auth.config import get_auth_settings

    get_auth_settings.cache_clear()
    from app.auth import db as auth_db

    auth_db.ensure_migrated(db)
    yield db, informe
    get_auth_settings.cache_clear()


@pytest.fixture
def informe(_entorno_auth):
    from app.health import storage

    _db, ruta = _entorno_auth
    # La ruta efectiva sale del entorno, no de una constante de este test.
    assert storage.default_report_path() == ruta
    assert not ruta.exists()
    return ruta


@pytest.fixture
def cliente_admin(_entorno_auth, monkeypatch):
    """TestClient con sesión de admin y un informe LIGERO (sin red)."""
    from fastapi.testclient import TestClient

    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session
    from app.health.models import ComponentResult, HealthReport, HealthStatus
    from app.main import app

    monkeypatch.setattr(
        "app.routers.health_admin.runner.run_report",
        lambda **k: HealthReport([ComponentResult("x", HealthStatus.HEALTHY)]),
    )
    db, _informe = _entorno_auth
    with auth_db.get_conn(db) as conn:
        u = auth_db.create_user(conn, username="adm_health", display_name="adm",
                                password_hash=hash_password("x" * 14), role="admin")
        token, _sesion = create_session(conn, u)
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    return c


def _csrf_del_panel(cliente) -> str:
    r = cliente.get("/admin/health")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el panel de salud no trae el formulario de instantánea"
    return m.group(1)


def test_get_api_no_escribe(cliente_admin, informe):
    r = cliente_admin.get("/api/admin/health", headers={"accept": "application/json"})
    assert r.status_code == 200, r.status_code
    assert r.json()["overall"] == "HEALTHY"
    assert not informe.exists(), "GET /api/admin/health dejó un fichero en disco"


def test_get_panel_no_escribe(cliente_admin, informe):
    r = cliente_admin.get("/admin/health")
    assert r.status_code == 200, r.status_code
    assert not informe.exists(), "GET /admin/health dejó un fichero en disco"


def test_el_post_de_instantanea_si_guarda(cliente_admin, informe):
    """La capacidad no se pierde: cambia de verbo."""
    token = _csrf_del_panel(cliente_admin)
    assert not informe.exists()
    r = cliente_admin.post("/admin/health/snapshot", data={"csrf_token": token})
    assert r.status_code == 302, r.status_code
    assert r.headers.get("location") == "/admin/health"
    assert informe.exists(), "el POST de instantánea no guardó el informe"


def test_el_post_sin_csrf_ni_escribe_ni_pasa(cliente_admin, informe):
    r = cliente_admin.post("/admin/health/snapshot", data={"csrf_token": "falso"})
    assert r.status_code == 403, r.status_code
    assert not informe.exists(), "un POST con CSRF inválido escribió igualmente"


def test_el_post_anonimo_no_escribe(informe):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    r = c.post("/admin/health/snapshot", data={"csrf_token": "loquesea"})
    assert r.status_code in (401, 302, 303, 403), r.status_code
    assert not informe.exists(), "un anónimo consiguió escribir el informe"


def test_el_get_no_admite_escritura_por_ningun_verbo(cliente_admin):
    """La superficie de los GET de salud es cerrada: nada de alias mutadores."""
    for metodo in ("post", "put", "patch", "delete"):
        for url in ("/admin/health", "/api/admin/health"):
            r = getattr(cliente_admin, metodo)(url)
            assert r.status_code in (404, 405), f"{metodo.upper()} {url} -> {r.status_code}"


def test_el_entorno_no_deja_residuo(informe):
    """Control del propio test: sin peticiones, no hay fichero."""
    assert not informe.exists()
    assert not os.path.exists(str(informe))
