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
