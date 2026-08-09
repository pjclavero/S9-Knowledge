"""Los caminos FAIL-CLOSED de `authz/dependencies.py`, probados de verdad.

Sexto dictamen, H6-6 y H6-7: `_progresion_de_campana` tiene tres retornos
fail-closed y `_still_has_access` otros tres, y NINGUNO tenia prueba. Un
fail-closed sin prueba es una declaracion de intenciones: se puede cambiar a
`return None` --que en esa funcion significaba "sin tope"-- sin que nada se
ponga rojo. Es exactamente la forma de fallo que llevamos siete rondas
persiguiendo, esta vez en las funciones que la contienen.

Aqui se fuerza cada rama --sin usuario, sin base, base ilegible, workspace no
determinable-- y se comprueba el valor concreto que devuelve.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.policies.models import NO_APLICA


@pytest.fixture(autouse=True)
def _entorno(tmp_path):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    os.environ["S9K_DEFAULT_WORKSPACE"] = "juego:pruebas"
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    yield tmp_path
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _peticion(user=None, session=None):
    return SimpleNamespace(state=SimpleNamespace(user=user, session=session))


# --- H6-6: `_progresion_de_campana` ----------------------------------------

def test_sin_partida_activa_el_tope_es_NO_APLICABLE_y_no_None():
    """El estado declarado. `None` significaba tres cosas y el motor lo leia
    como "sin tope": es el hallazgo H6-9."""
    from app.authz.dependencies import _progresion_de_campana

    tope, pj = _progresion_de_campana(_peticion(), None)
    assert tope is NO_APLICA
    assert pj is None


def test_sin_usuario_en_la_peticion_el_tope_es_CERO():
    from app.authz.dependencies import _progresion_de_campana

    assert _progresion_de_campana(_peticion(user=None), "partida:alfa") == (0, None)


def test_un_usuario_sin_id_tampoco_concede_progresion():
    from app.authz.dependencies import _progresion_de_campana

    user = SimpleNamespace(id=None)
    assert _progresion_de_campana(_peticion(user=user), "partida:alfa") == (0, None)


def test_sin_base_de_datos_el_tope_es_CERO():
    from app.authz.dependencies import _progresion_de_campana

    user = SimpleNamespace(id=1)
    # El fixture apunta a una ruta que no existe todavia.
    assert _progresion_de_campana(_peticion(user=user), "partida:alfa") == (0, None)


def test_si_la_base_no_se_puede_leer_el_tope_es_CERO(monkeypatch, tmp_path):
    from app.auth import db as auth_db
    from app.authz import dependencies

    (tmp_path / "auth.db").write_text("no soy una base sqlite")

    def revienta(*a, **kw):
        raise RuntimeError("base ilegible")

    monkeypatch.setattr(auth_db, "get_conn", revienta)
    user = SimpleNamespace(id=1)
    assert dependencies._progresion_de_campana(_peticion(user=user), "partida:alfa") == (0, None)


# --- H6-7: `_still_has_access` ---------------------------------------------

def test_sin_workspace_efectivo_no_hay_acceso(monkeypatch):
    """Fail-closed declarado en el codigo y jamas ejercitado."""
    from app.authz import dependencies

    class _Settings:
        S9K_DEFAULT_WORKSPACE = "   "

    monkeypatch.setattr(dependencies, "get_settings", lambda: _Settings())
    assert dependencies._still_has_access(SimpleNamespace(id=1), "partida:alfa") is False


def test_sin_fichero_de_base_no_hay_acceso():
    from app.authz.dependencies import _still_has_access

    assert _still_has_access(SimpleNamespace(id=1), "partida:alfa") is False


def test_si_la_consulta_revienta_no_hay_acceso(monkeypatch, tmp_path):
    from app.auth import db as auth_db
    from app.authz import dependencies

    (tmp_path / "auth.db").write_text("no soy una base sqlite")

    def revienta(*a, **kw):
        raise RuntimeError("base ilegible")

    monkeypatch.setattr(auth_db, "get_conn", revienta)
    assert dependencies._still_has_access(SimpleNamespace(id=1), "partida:alfa") is False


def test_un_admin_no_puede_activar_una_partida_inventada(tmp_path):
    """El unico camino que SI concede sin asignacion propia, acotado."""
    from app.auth import db as auth_db
    from app.authz.dependencies import _still_has_access

    db_path = tmp_path / "auth.db"
    auth_db.ensure_migrated(db_path)
    admin = SimpleNamespace(id=1, is_admin=lambda: True)
    assert _still_has_access(admin, "partida:inventada") is False
