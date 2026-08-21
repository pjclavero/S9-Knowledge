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
 6. Un usuario **autenticado NO admin**, con un CSRF **válido de su propia
    sesión**, tampoco puede tomar la instantánea: 403 y **sin escribir**.

El punto 6 existe porque el 5 no basta y se midió: quitando `require_admin` del
POST, la suite seguía en verde. Al anónimo no lo para el guardián de admin sino
que **no consigue token CSRF** (lo acuña un `GET` que ya es admin-only), así que
la autorización del POST estaba sostenida por el CSRF y **nadie probaba al
guardián de admin**. Por eso aquí el token se **acuña desde la propia sesión del
no-admin** —igual que hace el middleware, a partir de su `session_id` y su
`session_hash`— y NO se lee del panel de administración: si se leyera de ahí, el
caso volvería a medir el CSRF en lugar del rol.

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


@pytest.fixture
def cliente_no_admin(_entorno_auth, monkeypatch):
    """TestClient de un usuario autenticado con rol `viewer` (NO admin).

    Devuelve `(cliente, csrf_propio)`. El CSRF es un token **real de su propia
    sesión**, y lo emite la **propia aplicación** en `GET /account`, que es una
    página que este usuario SÍ puede abrir. No se toma del panel de salud ni de
    ninguna página admin: el objetivo del caso es el guardián de rol, no el CSRF.

    Se usa el token que emite la app en vez de recalcularlo aquí para que el
    caso no pueda **derivar en falso verde**: si mañana cambiara la derivación
    del middleware, un token recalculado a mano dejaría de ser válido y el POST
    seguiría dando 403 —pero por CSRF, no por rol—, que es justo el fallo que
    este caso existe para no repetir. Aun así se comprueba de forma cruzada que
    el token emitido coincide con la derivación documentada.
    """
    import hashlib
    import hmac

    from fastapi.testclient import TestClient

    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.csrf import get_csrf_token_for_session
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
        u = auth_db.create_user(conn, username="no_adm_health", display_name="curioso",
                                password_hash=hash_password("x" * 14), role="viewer")
        token, sesion = create_session(conn, u)
    assert not u.is_admin(), "el caso exige un usuario NO admin"

    cfg = get_auth_settings()
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(cfg.S9K_SESSION_COOKIE_NAME, token)

    # Token emitido por la app en una página NO admin de este mismo usuario.
    r = c.get("/account")
    assert r.status_code == 200, f"/account no accesible para el no-admin: {r.status_code}"
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "/account no trae token CSRF: el caso no podría medir el rol"
    csrf_propio = m.group(1)

    # Comprobación cruzada: es exactamente la derivación del middleware.
    csrf_raw = hmac.new(
        cfg.S9K_CSRF_SECRET.encode(),
        f"csrf:{sesion.id}:{sesion.session_hash[:8]}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert csrf_propio == get_csrf_token_for_session(
        sesion.id, csrf_raw, secret=cfg.S9K_CSRF_SECRET
    ), "el token de /account no es el de la sesión del no-admin"
    return c, csrf_propio


def test_el_no_admin_no_puede_tomar_la_instantanea(cliente_no_admin, informe):
    """Con CSRF VÁLIDO propio, al no-admin lo para `require_admin` y sólo él.

    Calibrado en las dos direcciones: quitando `require_admin` del POST este
    caso se pone ROJO (el no-admin escribiría, 302 + fichero en disco); con el
    guardián en su sitio, verde. Sin este caso, quitar `require_admin` no lo
    cazaba nadie.
    """
    cliente, csrf_propio = cliente_no_admin
    # El CSRF acuñado es REALMENTE válido para su sesión: si no lo fuera, el
    # caso mediría el CSRF y no el rol, y pasaría por buena razón equivocada.
    r_control = cliente.post("/admin/health/snapshot", data={"csrf_token": csrf_propio})
    assert r_control.status_code == 403, r_control.status_code
    assert "CSRF" not in (r_control.text or ""), (
        "lo paró el CSRF, no el guardián de admin: el token acuñado no era válido"
    )
    assert not informe.exists(), "un usuario no admin escribió el informe de salud"


def test_el_no_admin_ni_siquiera_ve_el_panel_que_acuna_el_csrf(cliente_no_admin):
    """Por qué el token hay que acuñarlo: el panel que lo daba es admin-only."""
    cliente, _ = cliente_no_admin
    r = cliente.get("/admin/health")
    assert r.status_code in (403, 302, 303), r.status_code


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
