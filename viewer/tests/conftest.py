import os
import sys
from pathlib import Path

import pytest

VIEWER_ROOT = Path(__file__).resolve().parents[1]
if str(VIEWER_ROOT) not in sys.path:
    sys.path.insert(0, str(VIEWER_ROOT))

# En corrida combinada (data-engine + viewer), pytest carga data-engine/app
# primero y lo registra en sys.modules['app']. Cuando llega a colectar los
# tests del viewer, la importación top-level `from app.main import app`
# resuelve contra el 'app' cacheado de data-engine en lugar del viewer.
# Limpiamos todos los submodulos de 'app' de data-engine para forzar la
# resolución correcta desde VIEWER_ROOT/app.
_viewer_app = VIEWER_ROOT / 'app'
_stale = [
    mod_name for mod_name, mod in list(sys.modules.items())
    if mod_name == 'app' or mod_name.startswith('app.')
    if not (hasattr(mod, '__file__') and mod.__file__
            and str(_viewer_app) in str(mod.__file__))
]
for _mod_name in _stale:
    sys.modules.pop(_mod_name, None)

# Debe fijarse antes de que algo importe app.config / app.deps (Settings se
# construye con lru_cache, así que el primer valor leído es el que queda).
os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")
os.environ.setdefault("S9K_DEFAULT_WORKSPACE", "leyenda")
os.environ.setdefault(
    "S9K_SAMPLE_GRAPH_PATH", str(VIEWER_ROOT / "examples" / "sample_graph.json")
)
# Secreto CSRF fuerte por defecto para los tests: sin él, cualquier test que
# active auth y arranque la app (enforce_auth_security) abortaría por "secreto
# por defecto". Los tests del validador de secreto crean su propia config.
import secrets as _secrets  # noqa: E402
os.environ.setdefault("S9K_CSRF_SECRET", _secrets.token_urlsafe(48))
# El TestClient habla HTTP (http://testserver); una cookie Secure no se
# reenviaría, rompiendo el round-trip de la cookie CSRF de login. En el entorno
# de test desactivamos Secure por defecto; el test dedicado de "cookie Secure"
# lo activa explícitamente e inspecciona la cabecera Set-Cookie.
os.environ.setdefault("S9K_SESSION_SECURE", "false")


@pytest.fixture
def lector_por_dependencia():
    """Instala un LECTOR LEGÍTIMO sustituyendo las dependencias que SÍ muerden.

    LORE-ANÓNIMO-DENEGADO (V3 RC, 2026-08-14): las suites que piden sin
    autenticar dejan de recibir material, porque la capa juego ya no se concede
    por la ausencia de partida. Las que sólo comprueban la FORMA de una
    respuesta o de una pantalla necesitan un lector con derecho.

    Aquí se sustituyen `get_filtered_provider` y `get_visibility_scope`, que
    entran por `Depends` de verdad en los routers. NO se sustituye
    `get_visibility_context`: ése es el punto CONGELADO —`get_filtered_provider`
    lo llama como función normal— y sustituirlo es inerte, sale verde por no
    morder y ya produjo aquí cifras ciertas por no mirar.

    El contexto lo produce `build_viewer_context`, el productor único; no se
    fabrica un `ViewerContext` a mano.
    """
    from app.authz.context import build_viewer_context
    from app.authz.dependencies import get_filtered_provider, get_visibility_scope
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.authz.scope import VisibilityScope
    from app.config import get_settings
    from app.deps import get_provider

    instalados = []

    def instalar(app, *, role="reviewer"):
        ctx = build_viewer_context(
            role=role, auth_enabled=True,
            default_workspace=get_settings().S9K_DEFAULT_WORKSPACE,
        )
        assert ctx.can_view_lore is True, (
            "el lector de este ayudante no tiene la llave de la capa juego: "
            "estaria instalando el mismo ambito que ya tiene el anonimo y las "
            "pruebas seguirian sin ejercer nada"
        )
        app.dependency_overrides[get_filtered_provider] = (
            lambda: PolicyFilteredProvider(get_provider(), ctx)
        )
        app.dependency_overrides[get_visibility_scope] = lambda: VisibilityScope(ctx)
        instalados.append(app)
        return ctx

    yield instalar

    for app in instalados:
        app.dependency_overrides.pop(get_filtered_provider, None)
        app.dependency_overrides.pop(get_visibility_scope, None)


@pytest.fixture
def cliente_lector(tmp_path):
    """Cliente HTTP de un LECTOR LEGÍTIMO: usuario real, sesión real, rol real.

    LORE-ANÓNIMO-DENEGADO (decisión del operador, V3 RC, 2026-08-14). Muchas
    suites de este visor pedían sin autenticar y recibían material: con
    `S9K_AUTH_ENABLED` apagado el contexto es anónimo, y hasta ahora el anónimo
    SÍ veía la capa juego porque la llave de la capa juego era, literalmente,
    NO TENER PARTIDA. Cerrada esa vía, un visitante sin principal no recibe
    nada, y esas suites —que no miden autorización sino la FORMA de la API y de
    las pantallas— se quedaban sin material que comprobar.

    Este ayudante les devuelve un lector con derecho: enciende la
    autenticación contra una `auth.db` temporal, crea el usuario con el rol que
    se pida y devuelve un `TestClient` con su cookie de sesión.

    Se autentica DE VERDAD en vez de inyectar un contexto a propósito: el punto
    de inyección de este visor está congelado (`get_filtered_provider` llama a
    `get_visibility_context` como función normal, no vía `Depends`), así que un
    contexto inyectado sería inerte y saldría verde por no morder.
    """
    from fastapi.testclient import TestClient

    creados = []

    def construir(app, *, role="reviewer", username="lector_legitimo"):
        from app.auth import db as auth_db
        from app.auth.config import get_auth_settings
        from app.auth.passwords import hash_password
        from app.auth.sessions import create_session
        from app.config import get_settings

        db_path = tmp_path / "auth_lector.db"
        os.environ["S9K_AUTH_ENABLED"] = "true"
        os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
        get_auth_settings.cache_clear()
        get_settings.cache_clear()
        auth_db.ensure_migrated(db_path)

        with auth_db.get_conn(db_path) as conn:
            user = auth_db.create_user(
                conn, username=username, display_name=username.title(),
                password_hash=hash_password("TestPass_1234567890!"), role=role,
            )
            auth_db.update_user(conn, user.id, must_change_password=False)
            user = auth_db.get_user_by_id(conn, user.id)
            token, _ = create_session(conn, user)

        c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
        creados.append(c)
        return c

    yield construir

    from app.auth.config import get_auth_settings
    from app.config import get_settings

    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Limpia el lru_cache de get_settings antes y después de cada test.

    Sin esto, el primer test que llame a get_settings() fija el valor en caché
    y los tests siguientes ven el mismo Settings aunque hayan cambiado variables
    de entorno vía monkeypatch (ej: S9K_JOBS_DB apuntando a una ruta inexistente).
    """
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
