"""Corte «instalación cerrada de fábrica».

Mide la propiedad completa: `cp .env.example .env` -> arrancar -> sin editar
nada más -> auth ACTIVADA, CSRF disponible sin terminal, `/setup/admin`
accesible mientras el bootstrap está pendiente, `/reviews` / `/entities` /
`/jobs` / `/v3/review` NO anónimos, y el simétrico: `S9K_AUTH_ENABLED=false`
explícito sigue siendo un opt-out de laboratorio legítimo que no se confunde
con el default de producto.

Cada test aquí tiene su mutación correspondiente en
`scripts/calibracion/mutaciones_instalacion_fabrica.py`, referenciada por
NOMBRE de test (no por índice). El arnés de calibración exige que cada uno
de estos casos se ponga rojo con su defecto correspondiente y que el mensaje
del rojo diga la causa.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ENV_KEYS = (
    "S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_CSRF_SECRET",
    "S9K_SESSION_SECURE", "S9K_GRAPH_PROVIDER",
)


@pytest.fixture(autouse=True)
def _entorno_limpio():
    """Ninguna de estas pruebas hereda config de otro test o del shell."""
    previos = {k: os.environ.get(k) for k in _ENV_KEYS}
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    yield
    for k, v in previos.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()


@pytest.fixture
def instalacion_de_fabrica(tmp_path):
    """Exactamente lo que deja `cp .env.example .env` sin editar nada más:
    ninguna variable de auth fijada salvo la ruta de la DB (que en un arranque
    real resuelve DEFAULT_AUTH_DB_PATH; aquí se apunta a un tmp_path para no
    tocar el repo, que es la única concesión al hecho de ser un test)."""
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    return tmp_path


def _client():
    from starlette.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _csrf_de(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "la pantalla no trae csrf_token: no se puede continuar el flujo"
    return m.group(1)


# ---------------------------------------------------------------------------
# 1) El default de producto y de plantilla es auth ACTIVADA
# ---------------------------------------------------------------------------

def test_default_de_fabrica_auth_activada(instalacion_de_fabrica):
    from app.auth.config import get_auth_settings
    cfg = get_auth_settings()
    assert cfg.S9K_AUTH_ENABLED is True, (
        "el default de config debe ser True: una instalación de fábrica sin "
        "tocar nada debe quedar autenticada."
    )


def test_auth_db_path_vacio_resuelve_a_ruta_absoluta_del_repo():
    """Sin fijar S9K_AUTH_DB_PATH (el estado tras `cp .env.example .env`
    literal, que trae la clave vacía), la ruta debe resolver a un absoluto
    anclado al repo, NO a la ruta relativa histórica."""
    from app.auth.config import AuthSettings, DEFAULT_AUTH_DB_PATH
    cfg = AuthSettings()
    assert cfg.S9K_AUTH_DB_PATH == DEFAULT_AUTH_DB_PATH
    assert Path(cfg.S9K_AUTH_DB_PATH).is_absolute()


def test_auth_db_path_explicitamente_vacio_tambien_resuelve():
    """`.env.example` fija `S9K_AUTH_DB_PATH=` (vacío, explícito): debe
    resolver igual que si no estuviera la línea."""
    os.environ["S9K_AUTH_DB_PATH"] = ""
    from app.auth.config import AuthSettings, DEFAULT_AUTH_DB_PATH
    cfg = AuthSettings()
    assert cfg.S9K_AUTH_DB_PATH == DEFAULT_AUTH_DB_PATH


def test_env_example_del_viewer_trae_auth_enabled_true():
    plantilla = Path(__file__).resolve().parents[1] / ".env.example"
    texto = plantilla.read_text(encoding="utf-8")
    assert "S9K_AUTH_ENABLED=true" in texto, (
        "la PLANTILLA que copia la persona nueva debe traer auth activada; "
        "el código puede defaultear a True, pero si el fichero real que se "
        "copia dice `false`, la instalación de fábrica queda sin auth."
    )


# ---------------------------------------------------------------------------
# 2) CSRF sin terminal: bootstrap seguro en disco
# ---------------------------------------------------------------------------

def test_csrf_secret_se_autogenera_sin_terminal(instalacion_de_fabrica):
    from app.auth.config import get_auth_settings
    cfg = get_auth_settings()
    assert cfg.S9K_CSRF_SECRET, "CSRF_SECRET sigue vacío: el arranque abortaría"
    assert len(cfg.S9K_CSRF_SECRET) >= 32

    secreto_path = instalacion_de_fabrica / ".csrf_secret"
    assert secreto_path.exists(), "el secreto generado debe persistirse en disco"
    modo = stat.S_IMODE(secreto_path.stat().st_mode)
    assert modo == 0o600, f"permisos del secreto CSRF deben ser 0600, son {oct(modo)}"


def test_csrf_secret_persiste_entre_arranques(instalacion_de_fabrica):
    from app.auth.config import get_auth_settings
    cfg1 = get_auth_settings()
    secreto1 = cfg1.S9K_CSRF_SECRET
    assert secreto1, "el primer arranque debe dejar un secreto no vacío"
    get_auth_settings.cache_clear()
    cfg2 = get_auth_settings()
    assert cfg2.S9K_CSRF_SECRET == secreto1, (
        "un reinicio con el mismo S9K_AUTH_DB_PATH debe reutilizar el mismo "
        "secreto; si cambiara en cada arranque invalidaría todas las "
        "sesiones vivas en silencio."
    )


def test_csrf_secret_explicito_gana_y_no_se_persiste(instalacion_de_fabrica):
    os.environ["S9K_CSRF_SECRET"] = "un-secreto-explicito-de-produccion-1234567890"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    cfg = get_auth_settings()
    assert cfg.S9K_CSRF_SECRET == "un-secreto-explicito-de-produccion-1234567890"
    assert not (instalacion_de_fabrica / ".csrf_secret").exists(), (
        "con secreto explícito no se debe tocar disco: quien lo fija a mano "
        "conserva la última palabra."
    )


def test_csrf_secret_no_aparece_en_ningun_mensaje_de_error(instalacion_de_fabrica, caplog):
    """El secreto nunca se imprime, ni siquiera cuando algo falla alrededor."""
    from app.auth.config import get_auth_settings
    cfg = get_auth_settings()
    secreto = cfg.S9K_CSRF_SECRET
    # Fuerza una ruta de error habitual: base ausente vuelta a comprobar.
    from app.auth import security
    with caplog.at_level("DEBUG"):
        security.enforce_auth_security(cfg)
    for registro in caplog.records:
        assert secreto not in registro.getMessage()


# ---------------------------------------------------------------------------
# 3) Negativos decisivos: arranque de fábrica exacto
# ---------------------------------------------------------------------------

def test_setup_admin_accesible_mientras_bootstrap_pendiente(instalacion_de_fabrica):
    with _client() as c:
        r = c.get("/setup/admin")
        assert r.status_code == 200, (
            "sin ningún administrador todavía, /setup/admin debe servir la "
            "pantalla de configuración inicial."
        )


@pytest.mark.parametrize("ruta", ["/reviews", "/entities", "/jobs", "/v3/review"])
def test_rutas_de_producto_no_son_anonimas_de_fabrica(instalacion_de_fabrica, ruta):
    with _client() as c:
        r = c.get(ruta, follow_redirects=False)
        assert r.status_code != 200, (
            f"{ruta} respondió 200 anónimo en una instalación de fábrica: "
            "la propiedad que este corte cierra exige que NO sea así."
        )


def test_flujo_completo_bootstrap_login_y_acceso(instalacion_de_fabrica):
    with _client() as c:
        r = c.get("/setup/admin")
        csrf = _csrf_de(r.text)
        r2 = c.post(
            "/setup/admin",
            data={
                "username": "admin",
                "display_name": "Admin",
                "password": "SuperSecreta_1234567890!",
                "password_confirm": "SuperSecreta_1234567890!",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert r2.status_code == 303, r2.text

        # Sellado: /setup/admin ya no existe (garantía de PR #247, intacta).
        r3 = c.get("/setup/admin")
        assert r3.status_code == 404

        rl = c.get("/login")
        csrf2 = _csrf_de(rl.text)
        rlp = c.post(
            "/login",
            data={
                "username": "admin",
                "password": "SuperSecreta_1234567890!",
                "csrf_token": csrf2,
                "next": "/",
            },
            follow_redirects=False,
        )
        assert rlp.status_code == 302

        r4 = c.get("/reviews", follow_redirects=False)
        assert r4.status_code == 200, (
            "tras el login, la ruta que antes era anónima debe quedar "
            "accesible según autorización."
        )


# ---------------------------------------------------------------------------
# 4) Negativo simétrico: opt-out explícito de laboratorio
# ---------------------------------------------------------------------------

def test_opt_out_explicito_conserva_el_modo_sin_auth(instalacion_de_fabrica):
    os.environ["S9K_AUTH_ENABLED"] = "false"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    cfg = get_auth_settings()
    assert cfg.S9K_AUTH_ENABLED is False
    # El opt-out no dispara el bootstrap de CSRF: no hay auth que proteger.
    assert cfg.S9K_CSRF_SECRET == ""
    assert not (instalacion_de_fabrica / ".csrf_secret").exists()

    with _client() as c:
        r = c.get("/reviews", follow_redirects=False)
        assert r.status_code == 200, (
            "con el opt-out explícito, el comportamiento de laboratorio "
            "(sin auth) debe seguir disponible: cerrar producción no puede "
            "romper el camino de desarrollo."
        )


def test_opt_out_no_se_confunde_con_el_default(instalacion_de_fabrica):
    """El opt-out exige la variable EXPLÍCITA; no fijarla nunca da `false`."""
    from app.auth.config import get_auth_settings
    cfg_sin_fijar = get_auth_settings()
    assert cfg_sin_fijar.S9K_AUTH_ENABLED is True


# ---------------------------------------------------------------------------
# 5) Fail-closed: una base corrupta sigue siendo fail-closed, no "primera vez"
# ---------------------------------------------------------------------------

def test_base_corrupta_no_es_primera_instalacion(instalacion_de_fabrica):
    db_path = Path(os.environ["S9K_AUTH_DB_PATH"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("esto no es una base sqlite", encoding="utf-8")

    from app.auth.db import ensure_migrated
    from app.auth.schema_compat import SchemaVersionUnknown
    with pytest.raises(SchemaVersionUnknown):
        ensure_migrated(db_path)


def test_fallo_de_escritura_del_secreto_csrf_es_fail_closed(tmp_path):
    """Si el directorio de la auth DB no es escribible, no hay secreto "de
    emergencia" en memoria: se propaga un error, fail-closed."""
    solo_lectura = tmp_path / "solo_lectura"
    solo_lectura.mkdir()
    db_path = solo_lectura / "auth.db"
    os.chmod(solo_lectura, 0o500)
    try:
        from app.auth.csrf_bootstrap import resolve_csrf_secret, CsrfSecretBootstrapError
        with pytest.raises(CsrfSecretBootstrapError):
            resolve_csrf_secret("", str(db_path))
    finally:
        os.chmod(solo_lectura, 0o700)


def test_secreto_csrf_vacio_en_disco_se_regenera(instalacion_de_fabrica):
    """Un fichero de secreto presente pero vacío/corrupto no es un secreto
    válido: se trata como ausente y se regenera, en vez de arrancar con un
    CSRF_SECRET vacío."""
    secreto_path = instalacion_de_fabrica / ".csrf_secret"
    secreto_path.parent.mkdir(parents=True, exist_ok=True)
    secreto_path.write_text("", encoding="utf-8")

    from app.auth.csrf_bootstrap import resolve_csrf_secret
    resultado = resolve_csrf_secret("", str(instalacion_de_fabrica / "auth.db"))
    assert resultado, "un fichero vacío debe regenerar el secreto, no devolver vacío"
    assert len(resultado) >= 32
