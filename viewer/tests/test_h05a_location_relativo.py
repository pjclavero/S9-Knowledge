# -*- coding: utf-8 -*-
"""H-05 corte A: las redirecciones de /panel/operations llevan Location RELATIVO.

PROPIEDAD: ninguna redirección del visor lleva un origen derivado del cliente.
Con `Host: evil.example` las cuatro rutas POST (ingestas, planes, aplicaciones,
altas) respondían `303 Location: http://evil.example/...` (informe PRE-H05).
Ahora el Location es path + query.

QUÉ MIDE: las cuatro rutas, en FALLO y en ÉXITO, con Host hostil (con y sin
puerto) y con Host legítimo como control; que un cliente que SIGUE la
redirección acaba en el mismo origen y en la página esperada; y, por AST, que
`chassis_operations.py` no contiene ningún `request.url_for`.

TECHO DECLARADO: sólo el fichero `chassis_operations.py`. Las 35 `url_for` de
las plantillas (URLs absolutas en `action=`/`href=`) y la ausencia de
`TrustedHostMiddleware` siguen abiertas (corte B). Tampoco cubre `root_path`
(el visor no se monta bajo prefijo).
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import jobs_client
from app.authz.dependencies import get_visibility_scope
from app.chassis import FEATURE_SLOTS, slot_flag_env
from app.routers import chassis_operations as panel

SLOT = next(s for s in FEATURE_SLOTS if s.key == "B")
FLAG = slot_flag_env(SLOT)
PASSWORD = "PanelBH05a_1234567890!"
REPO = Path(__file__).resolve().parents[2]
EJEMPLOS = REPO / "examples" / "ingesta-v3"
FUENTE_PY = REPO / "viewer" / "app" / "routers" / "chassis_operations.py"

HOSTS_HOSTILES = ["evil.example", "evil.example:8443"]
RUTAS = ["ingestas", "planes", "aplicaciones", "altas"]


@pytest.fixture(autouse=True)
def _grafo_de_mentira(monkeypatch):
    import grafo_doble

    return grafo_doble.instalar(monkeypatch)


@pytest.fixture(autouse=True)
def _entorno_limpio(tmp_path, monkeypatch):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last.json"))
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    yield
    for var in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_JOBS_DB",
                "S9K_INGEST_SOURCES_DIR", FLAG):
        os.environ.pop(var, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def real_app():
    from app.main import app

    return app


@pytest.fixture
def panel_on():
    os.environ[FLAG] = "true"
    yield
    os.environ.pop(FLAG, None)


@pytest.fixture
def cola(tmp_path):
    from app.config import get_settings

    db = tmp_path / "jobs.db"
    os.environ["S9K_JOBS_DB"] = str(db)
    get_settings.cache_clear()
    store = jobs_client._load_job_store()
    assert store is not None
    store.init_db(str(db))
    yield db
    get_settings.cache_clear()


@pytest.fixture
def operador_con(real_app, tmp_path):
    """Fábrica de clientes ADMIN autenticados con un `Host` dado."""
    from app.auth import db as auth_db_mod
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    get_auth_settings.cache_clear()
    auth_db_mod.ensure_migrated(db_path)
    with auth_db_mod.get_conn(db_path) as conn:
        u = auth_db_mod.create_user(
            conn, username="h05a_op", display_name="Op",
            password_hash=hash_password(PASSWORD), role="admin",
        )
        auth_db_mod.update_user(conn, u.id, must_change_password=False)
        u = auth_db_mod.get_user_by_id(conn, u.id)
        token, _ = create_session(conn, u)

    def fabrica(host: str | None = None) -> TestClient:
        c = TestClient(real_app, raise_server_exceptions=False, follow_redirects=False)
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
        c.headers.update({"accept": "text/html"})
        if host:
            c.headers["host"] = host
        return c

    return fabrica


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "la pantalla no trae token CSRF"
    return m.group(1)


class _ServicioDeMentira:
    """ReviewApplyService mínimo: el ÉXITO de planes/aplicaciones/altas."""

    def sellar(self, **_kw):
        return {}

    def aplicar(self, **_kw):
        return {}

    def aprobar_alta(self, **_kw):
        return {"nuevo": True}

    def altas(self, **_kw):
        return [], False


@pytest.fixture
def exito_de_acciones(monkeypatch):
    """La corrida es visible y el servicio responde: las acciones tienen éxito."""
    monkeypatch.setattr(panel, "_corrida_visible",
                        lambda scope, job_id: {"workspace": "bruma"})
    import app.services.v3_apply as v3

    monkeypatch.setattr(v3, "ReviewApplyService", _ServicioDeMentira)


def _enviar(cliente: TestClient, ruta: str, *, exito: bool):
    """POST a `ruta` provocando éxito o fallo. Devuelve (respuesta, pagina_esperada)."""
    html = cliente.get(SLOT.prefix).text
    csrf = _csrf(html)
    if ruta == "ingestas":
        fuente = ""
        if exito:
            opciones = re.findall(r'<option value="([^"]+)"', html)
            assert opciones, "sin fuentes que elegir en el arnés"
            fuente = opciones[0]
        data = {"fuente": fuente, "csrf_token": csrf}
    else:
        data = {"trabajo": "job-h05a" if exito else "", "csrf_token": csrf}
        if ruta == "altas":
            data.update({"entidad": "e1", "tipo": "persona"})
    return cliente.post(f"/panel/operations/{ruta}", data=data)


def _preparar(ruta: str, exito: bool, monkeypatch, request):
    if exito and ruta == "ingestas":
        monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    elif exito:
        request.getfixturevalue("exito_de_acciones")
    elif ruta == "ingestas":
        monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))


def _es_relativo(loc: str) -> None:
    partes = urlsplit(loc)
    assert loc.startswith("/") and not loc.startswith("//"), loc
    assert partes.scheme == "" and partes.netloc == "", loc
    assert "evil" not in loc.lower(), loc


@pytest.mark.parametrize("exito", [False, True], ids=["fallo", "exito"])
@pytest.mark.parametrize("ruta", RUTAS)
@pytest.mark.parametrize("host", HOSTS_HOSTILES)
def test_location_relativo_con_host_hostil(real_app, panel_on, cola, operador_con,
                                           monkeypatch, request, host, ruta, exito):
    _preparar(ruta, exito, monkeypatch, request)
    cliente = operador_con(host)
    r = _enviar(cliente, ruta, exito=exito)
    assert r.status_code == 303, (r.status_code, r.text[:200])
    _es_relativo(r.headers["location"])


@pytest.mark.parametrize("exito", [False, True], ids=["fallo", "exito"])
@pytest.mark.parametrize("ruta", RUTAS)
@pytest.mark.parametrize("host", HOSTS_HOSTILES)
def test_seguir_la_redireccion_acaba_en_el_mismo_origen(
        real_app, panel_on, cola, operador_con, monkeypatch, request, host, ruta, exito):
    """Un cliente que SIGUE el Location no sale del origen de la petición."""
    _preparar(ruta, exito, monkeypatch, request)
    cliente = operador_con(host)
    r = _enviar(cliente, ruta, exito=exito)
    assert r.status_code == 303
    destino = urlsplit(urljoin(str(r.request.url), r.headers["location"]))
    origen = urlsplit(str(r.request.url))
    assert (destino.scheme, destino.netloc) == (origen.scheme, origen.netloc)
    esperada = "/panel/operations/altas" if ruta == "altas" else "/panel/operations/"
    assert destino.path == esperada, destino
    pagina = cliente.get(r.headers["location"])
    if ruta == "altas":
        # La pantalla de altas contesta 404 (suya, con su plantilla) ante una
        # corrida inexistente: es el producto, y el 404 viene de SU página.
        esperado = 200 if exito else 404
        assert pagina.status_code == esperado, (pagina.status_code, pagina.text[:200])
        assert "Entidades nuevas" in pagina.text
    else:
        assert pagina.status_code == 200, (pagina.status_code, pagina.text[:200])
        assert 'data-role=' in pagina.text


@pytest.mark.parametrize("exito", [False, True], ids=["fallo", "exito"])
@pytest.mark.parametrize("ruta", RUTAS)
def test_control_positivo_con_host_legitimo(real_app, panel_on, cola, operador_con,
                                            monkeypatch, request, ruta, exito):
    """Con Host legítimo la ruta sigue funcionando: mismo destino, mismos params."""
    _preparar(ruta, exito, monkeypatch, request)
    cliente = operador_con(None)
    r = _enviar(cliente, ruta, exito=exito)
    assert r.status_code == 303
    _es_relativo(r.headers["location"])
    partes = urlsplit(r.headers["location"])
    esperada = "/panel/operations/altas" if ruta == "altas" else "/panel/operations/"
    assert partes.path == esperada
    assert "aviso=" in partes.query or "solicitado=" in partes.query
    esperado = 404 if (ruta == "altas" and not exito) else 200
    assert cliente.get(r.headers["location"]).status_code == esperado


def _llamadas_url_for(arbol: ast.AST) -> list[int]:
    """Líneas de toda llamada `<algo>.url_for(...)` del árbol."""
    return [
        n.lineno for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "url_for"
    ]


def test_el_censo_ast_no_encuentra_request_url_for_en_chassis_operations():
    """Censo por AST: ningún `<algo>.url_for(...)` en `chassis_operations.py`.

    TECHO: sólo ese fichero. Las plantillas (35 `url_for`) y los demás routers
    quedan fuera a propósito (corte B).
    """
    arbol = ast.parse(FUENTE_PY.read_text(encoding="utf-8"))
    llamadas = _llamadas_url_for(arbol)
    assert llamadas == [], f"`url_for` reintroducido en las líneas {llamadas}"
    # El censo no puede estar ciego: tiene que ver una llamada plantada.
    plantada = ast.parse("def f(request):\n    return request.url_for('x')\n")
    assert _llamadas_url_for(plantada), "el censo no detecta ni una llamada plantada"
    # Y las tres redirecciones usan la ruta relativa.
    fuente = FUENTE_PY.read_text(encoding="utf-8")
    assert fuente.count("request.app.url_path_for(") == 3
