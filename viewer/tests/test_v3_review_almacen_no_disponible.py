# -*- coding: utf-8 -*-
"""Slice 2 · Corte 4 — el SEGUNDO consumidor del almacén: `/v3/review`.

EL DEFECTO QUE ESTE MÓDULO FIJA
-------------------------------
El Corte 4 hizo que `load_proposals` LEVANTE cuando el almacén está ausente o
es ilegible, en vez de devolver lista vacía. Eso es lo correcto. Pero
`load_proposals` tiene TRES consumidores dentro de `ReviewService` —`queue()`,
`workspaces()` y `record()`— y la primera entrega sólo cubrió la superficie del
panel. El visor auxiliar quedó sin manejar, y el contrato de navegador lo
cazó::

    AssertionError: el enlace de la nav /v3/review devolvio 500
    assert 500 == 200

    viewer/app/routers/v3_review.py:101   queue
      -> viewer/app/services/v3_review.py:616   workspaces
        -> viewer/app/services/v3_review.py:419   load_proposals

Una función con dos consumidores y sólo uno actualizado. Es el patrón que esta
sesión lleva repitiendo, y por eso aquí no se prueba «la pantalla va»: se
enumeran los consumidores POR AST y se exige que cada superficie HTTP que llega
a ellos tenga su desenlace.

LO QUE NO VALE COMO ARREGLO
---------------------------
Devolver `[]`. Reintroduciría «ausencia == cero» —el defecto que el corte viene
a cerrar— y encima en la superficie que tiene las ÚNICAS escrituras de dominio:
aquí se APRUEBA y se RECHAZA. Una cola que se presenta vacía porque el almacén
no está es una cola en la que el revisor no aprueba nada y se va tranquilo.

POR QUÉ ESTA PANTALLA RESPONDE 200 Y NO 503
-------------------------------------------
Es un destino del MENÚ. La doctrina del producto para una dependencia que no se
puede consultar está ya escrita en el panel B (`chassis_operations.py`,
«AUSENCIA != CERO»): la pantalla ABRE y DECLARA que el dato no está —«no es que
no haya fuentes; es que el dato no está»— en vez de echar al operador con un
error. Se sigue esa doctrina, no se inventa otra. Lo que se prohíbe, y se fija
abajo, es presentarlo como una cola vacía.
"""
from __future__ import annotations

import ast
import inspect
import os
import re
import stat

import pytest
from fastapi.testclient import TestClient

PASSWORD = "Contrasena-De-Prueba-1"


@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _entorno_limpio():
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    yield
    for var in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH",
                "S9K_V3_REVIEW_PROPOSALS_DIR", "S9K_V3_REVIEW_DECISIONS_PATH",
                "S9K_V3_REVIEW_DATABASE_PATH"):
        os.environ.pop(var, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def almacen(tmp_path):
    """La ruta del almacén, DECLARADA pero todavía sin crear.

    `tmp_path` siempre existe, así que el subdirectorio se deja deliberadamente
    sin crear: es la única forma de que el caso «ausente» sea de verdad
    ausente y no un artefacto de la fixture.
    """
    directorio = tmp_path / "reviews-v3" / "proposals"
    os.environ["S9K_V3_REVIEW_PROPOSALS_DIR"] = str(directorio)
    os.environ["S9K_V3_REVIEW_DECISIONS_PATH"] = str(tmp_path / "decisions.jsonl")
    os.environ["S9K_V3_REVIEW_DATABASE_PATH"] = str(tmp_path / "review.sqlite3")
    return directorio


@pytest.fixture
def revisor(real_app, tmp_path):
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
        user = auth_db_mod.create_user(
            conn, username="c4_revisor", display_name="Revisor",
            password_hash=hash_password(PASSWORD), role="admin",
        )
        auth_db_mod.update_user(conn, user.id, must_change_password=False)
        user = auth_db_mod.get_user_by_id(conn, user.id)
        token, _ = create_session(conn, user)
    c = TestClient(real_app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    c.headers.update({"accept": "text/html"})
    return c


# ===========================================================================
# 1. LA REGRESIÓN MEDIDA: el enlace de la nav
# ===========================================================================

@pytest.mark.parametrize("ruta", ["/v3/review", "/v3/review/glossary-candidates"])
def test_el_almacen_ausente_no_devuelve_500(real_app, revisor, almacen, ruta):
    """Era 500. Una excepción cruda en un destino del menú.

    Se comprueba la PREMISA (el almacén no existe) antes de afirmar nada: si
    alguien creara el directorio, esta prueba dejaría de medir el caso que
    nombra y hay que enterarse.
    """
    assert not almacen.exists(), "premisa rota: el almacén no debería existir"

    r = revisor.get(ruta)
    assert r.status_code != 500, (
        f"{ruta} devuelve 500 con el almacén ausente: la excepción de "
        "`load_proposals` llega cruda al servidor"
    )
    assert r.status_code == 200, r.status_code


@pytest.mark.parametrize("ruta", ["/v3/review", "/v3/review/glossary-candidates"])
def test_el_almacen_ausente_se_declara_y_no_se_pinta_como_vacio(
    real_app, revisor, almacen, ruta
):
    """Y no vale «arreglarlo» devolviendo `[]`: eso es el defecto, no el fix."""
    r = revisor.get(ruta)
    assert 'data-state="unavailable"' in r.text, (
        f"{ruta} no declara que el almacén no está: se está pintando como si "
        "la cola estuviera vacía"
    )
    assert "PROPOSALS_STORE_MISSING" in r.text
    assert "no se sabe" in r.text
    # AUSENCIA != CERO: ninguna frase que afirme que no hay nada.
    assert "No hay candidatos propuestos" not in r.text
    assert "No quedan propuestas" not in r.text
    # Repo público: ni ruta ni traza.
    assert str(almacen) not in r.text
    assert "Traceback" not in r.text


@pytest.mark.parametrize("ruta", ["/v3/review", "/v3/review/glossary-candidates"])
def test_el_almacen_ilegible_se_distingue_del_ausente(
    real_app, revisor, almacen, ruta
):
    almacen.mkdir(parents=True)
    (almacen / "paquete.json").write_text('{"workspace":"w","items":[]}', encoding="utf-8")
    os.chmod(almacen, 0o000)
    try:
        assert almacen.exists(), "premisa: exists() sigue siendo True"
        r = revisor.get(ruta)
        assert r.status_code == 200, r.status_code
        assert "PROPOSALS_STORE_UNREADABLE" in r.text, (
            "el almacén ilegible no se distingue del ausente: llevan a "
            "acciones distintas (alinear la ruta vs. arreglar un permiso)"
        )
        assert "permisos" in r.text
        assert str(almacen) not in r.text
    finally:
        os.chmod(almacen, stat.S_IRWXU)


def test_el_almacen_vacio_legitimo_no_se_declara_no_disponible(
    real_app, revisor, almacen
):
    """El control en sentido contrario: un vacío legítimo NO es un fallo."""
    almacen.mkdir(parents=True)
    assert os.listdir(almacen) == []

    r = revisor.get("/v3/review")
    assert r.status_code == 200
    assert 'data-state="unavailable"' not in r.text, (
        "un almacén presente, legible y vacío se está declarando no disponible"
    )
    assert "PROPOSALS_STORE_MISSING" not in r.text


def test_ningun_enlace_de_la_nav_revienta_con_el_almacen_ausente(
    real_app, revisor, almacen
):
    """El contrato de navegador, SIN navegador.

    La regresión la cazó `tests/browser/test_browser_navigation.py` («cada
    enlace de la barra abre una pagina de verdad, sin 4xx/5xx»), que en esta
    máquina se SALTA porque Chromium no está instalado: 33 skipped. Una suite
    local en verde no es un check requerido en verde, y por ese hueco exacto
    se escapó el 500.

    Así que la misma afirmación se hace aquí con el cliente HTTP real: se
    ENUMERAN los enlaces de la barra tal y como los pinta el producto —no una
    lista escrita a mano, que se quedaría corta en cuanto alguien añada una
    sección— y se exige que ninguno reviente con el almacén ausente.
    """
    assert not almacen.exists(), "premisa rota: el almacén no debería existir"

    portada = revisor.get("/")
    assert portada.status_code == 200, portada.status_code
    barra = re.search(r"<header[^>]*class=\"topbar\".*?</header>", portada.text, re.S)
    assert barra, "no se encontró la barra de navegación en la portada"
    enlaces = [h for h in re.findall(r'<a[^>]+href="([^"]+)"', barra.group(0))
               if h.startswith("/")]
    assert enlaces, "la barra de navegación no tiene enlaces"
    assert any("/v3/review" in h or "/reviews" in h for h in enlaces), (
        f"la revisión ya no está en la nav; esta prueba dejaría de cubrirla: {enlaces}"
    )

    rotos = {}
    for href in enlaces:
        r = revisor.get(href)
        if r.status_code >= 500:
            rotos[href] = r.status_code
    assert not rotos, (
        f"enlaces de la nav que revientan con el almacén de propuestas "
        f"ausente: {rotos}. Una excepción de `load_proposals` sin manejar en "
        "cualquier consumidor sale por aquí."
    )


# ===========================================================================
# 2. EL TERCER CONSUMIDOR: `record()`, en la ÚNICA superficie que escribe
# ===========================================================================

def test_decidir_con_el_almacen_caido_no_culpa_al_revisor_ni_filtra_la_ruta(
    almacen, lector_por_dependencia
):
    """`decide()` mapeaba TODO `ReviewError` a 400 con `str(exc)`.

    Dos defectos en una línea, y los dos los agrava este corte:

    * **Desenlace**: 400 dice «tu petición está mal». El almacén caído no es
      culpa de quien decide; es indisponibilidad del servidor.
    * **Fuga**: el mensaje de `ProposalStoreUnavailable` lleva el DIRECTORIO
      dentro, y `detail=str(exc)` lo publica. Repositorio público.

    Se monta el router suelto con un lector legítimo —el mismo patrón que
    `test_v3_review.py`— para que lo que se ejerza sea `record()` y no la
    puerta CSRF: un 403 aquí mediría el guardián, no el desenlace.
    """
    from fastapi import FastAPI

    from app.routers import v3_review as router_module

    assert not almacen.exists(), "premisa rota: el almacén no debería existir"

    app = FastAPI()
    app.include_router(router_module.router)
    lector_por_dependencia(app)
    cliente = TestClient(app, raise_server_exceptions=False, follow_redirects=False)

    r = cliente.post("/v3/review/decide", data={
        "proposal_id": "review:loquesea",
        "workspace": "ws",
        "human_decision": "APPROVE",
        "request_id": "req-1",
        "expected_proposal_hash": "da-igual-no-se-llega-a-mirar",
        "csrf_token": "",
    })
    assert r.status_code != 500, r.status_code
    assert r.status_code == 503, (
        f"decidir con el almacén caído responde {r.status_code}: un 4xx culpa "
        "al revisor de una indisponibilidad del servidor"
    )
    assert str(almacen) not in r.text, (
        "la respuesta publica la RUTA del almacén: `detail=str(exc)` filtra el "
        "mensaje de la excepción y el repositorio es público"
    )
    # El cuerpo EXACTO que encontró la revisión, fijado para que no vuelva:
    #   {"detail":"almacen de propuestas ausente: /.../reviews-v3/proposals"}
    assert "almacen de propuestas ausente" not in r.text, (
        "vuelve a publicarse el mensaje crudo de la excepción"
    )
    # Y lo que SÍ tiene que llevar: el código estable, para poder ramificar
    # por código sin parsear prosa.
    assert "PROPOSALS_STORE_MISSING" in r.text, r.text[:300]
    assert "Traceback" not in r.text


# ===========================================================================
# 3. QUE NO SE VUELVA A QUEDAR UN CONSUMIDOR FUERA
# ===========================================================================

def test_todo_consumidor_de_load_proposals_esta_declarado():
    """Censo POR AST de quién lee el almacén. No se cuenta texto.

    Si aparece un cuarto consumidor, esta prueba se pone roja y obliga a
    decidir su desenlace en vez de descubrirlo en CI —que es exactamente como
    se descubrió el segundo—.
    """
    from app.services import v3_review

    arbol = ast.parse(inspect.getsource(v3_review))
    consumidores = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for hijo in ast.walk(nodo):
                if (isinstance(hijo, ast.Call)
                        and isinstance(hijo.func, ast.Name)
                        and hijo.func.id == "load_proposals"):
                    consumidores.add(nodo.name)

    declarados = {"queue", "workspaces", "record"}
    assert consumidores == declarados, (
        f"el censo de consumidores de load_proposals cambió: {consumidores}. "
        f"Declarados y con desenlace decidido: {declarados}. Un consumidor "
        "nuevo sin desenlace es un 500 esperando a que lo encuentre CI."
    )


def test_las_dos_superficies_dicen_lo_mismo_del_almacen_caido():
    """Panel C y visor auxiliar: un solo texto, no dos que se parecen.

    El panel mantiene su propia tabla (`chassis_review.ALMACEN_NO_DISPONIBLE`)
    y el servicio publica la canónica. Mientras existan las dos, esta prueba
    impide que DIVERJAN: dos frases distintas para el mismo hecho es cómo el
    operador acaba recibiendo consejos incompatibles según por dónde entre.
    """
    from app.routers import chassis_review
    from app.services.v3_review import PROPOSALS_STORE_MESSAGES

    del_panel = {
        codigo: texto for codigo, (texto, _estado)
        in chassis_review.ALMACEN_NO_DISPONIBLE.items()
    }
    assert del_panel == PROPOSALS_STORE_MESSAGES, (
        "el texto del almacén no disponible ha divergido entre "
        "`/panel/review` y `/v3/review`"
    )


def test_ninguna_superficie_del_almacen_publica_str_de_la_excepcion():
    """La frase sale de la tabla; `str(exc)` lleva la ruta dentro.

    Se comprueba por AST sobre el manejador de `ProposalStoreUnavailable`: un
    `detail=str(exc)` ahí volvería a publicar el directorio.
    """
    from app.routers import v3_review as router

    arbol = ast.parse(inspect.getsource(router))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.ExceptHandler) or nodo.type is None:
            continue
        nombres = [
            x.id for x in (nodo.type.elts if isinstance(nodo.type, ast.Tuple) else [nodo.type])
            if isinstance(x, ast.Name)
        ]
        if "ProposalStoreUnavailable" not in nombres:
            continue
        for hijo in ast.walk(nodo):
            if (isinstance(hijo, ast.Call) and isinstance(hijo.func, ast.Name)
                    and hijo.func.id == "str"):
                argumentos = [
                    a.id for a in hijo.args if isinstance(a, ast.Name)
                ]
                assert nodo.name not in argumentos, (
                    f"linea {hijo.lineno}: se publica `str({nodo.name})`, que "
                    "contiene la ruta del almacén"
                )
