# -*- coding: utf-8 -*-
"""CORTE F-2 · PIEZA 4 — la divergencia se ve ANTES de operar, y desde el producto.

Hasta este corte el unico sitio que comparaba declaraciones de workspace era
`deploy/scripts/preflight_ensayo_rc.py`, que **un arranque cualquiera no
ejecuta**. Un despliegue con el perfil de la boveda y el entorno diciendo cosas
distintas arrancaba sin una sola senal y se comportaba asi:

  - `/admin/partidas` pintaba el workspace del ENTORNO en un campo de solo
    lectura;
  - conceder acceso al workspace del PERFIL —donde acaba el conocimiento—
    devolvia 400 con un texto generico que no mencionaba la divergencia.

Aqui se fija que eso ya no pasa. LOS TESTIGOS DE UNA PANTALLA PIDEN LA PANTALLA:
todo lo que se afirma sobre lo que el operador ve se comprueba sobre el HTML de
un `GET`, no sobre un diccionario de servicio.

TECHO: estas pruebas miden el aviso y el diagnostico. NO miden que el
conocimiento acabe en un workspace u otro — eso lo mide
`test_f2_vault_workspace_hasta_neo4j.py` contra Neo4j real.
"""
from __future__ import annotations

import json
import os
import re

import pytest

#: Lo que declara el ENTORNO (hoy, la autoridad de `/admin/partidas`).
WS_ENTORNO = "ws-del-entorno"
#: Lo que declara el PERFIL de la boveda (la autoridad del conocimiento).
WS_PERFIL = "ws-del-perfil"


@pytest.fixture
def entorno(tmp_path):
    """Despliegue con las DOS autoridades declarando cosas distintas."""
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    fuentes = tmp_path / "fuentes"
    fuentes.mkdir()
    (fuentes / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS_PERFIL}), encoding="utf-8"
    )

    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS_ENTORNO
    os.environ["S9K_INGEST_SOURCES_DIR"] = str(fuentes)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-de-test-1234567890"
    get_auth_settings.cache_clear()
    get_settings.cache_clear()

    from app.auth import db as auth_db

    db_path = tmp_path / "auth.db"
    auth_db.ensure_migrated(db_path)
    from app.main import app

    yield db_path, auth_db, app, fuentes

    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE",
              "S9K_INGEST_SOURCES_DIR", "S9K_CSRF_SECRET"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _admin(auth_db, db_path):
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        admin = auth_db.create_user(
            conn, username="gm", display_name="GM",
            password_hash=hash_password("TestPass_1234567890!"), role="admin",
        )
        jugadora = auth_db.create_user(
            conn, username="ana", display_name="Ana",
            password_hash=hash_password("TestPass_1234567890!"), role="viewer",
        )
        token, _ = create_session(conn, admin)
    return jugadora, token


def _cliente(app, token):
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set("s9k_session", token)
    return c


def _pantalla(cliente) -> tuple[str, str]:
    """EL HTML de verdad, mas su csrf. Nada de diccionarios de servicio."""
    r = cliente.get("/admin/partidas")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    assert m, "el formulario no trae csrf_token"
    return r.text, m.group(1)


def _conceder(cliente, user_id, workspace, csrf):
    return cliente.post("/admin/partidas/grant", data={
        "user_id": user_id, "workspace": workspace, "partida_id": "partida:mesa1",
        "csrf_token": csrf, "max_visible_session": "5", "character_id": "",
    })


# ---------------------------------------------------------------------------
# LA PANTALLA AVISA
# ---------------------------------------------------------------------------

def test_la_pantalla_de_partidas_avisa_de_la_divergencia(entorno):
    db_path, auth_db, app, _ = entorno
    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))

    assert "aviso-autoridad-workspace" in html, (
        "la pantalla NO avisa de que las dos autoridades declaran workspaces "
        "distintos: el operador ve el del entorno y nada mas, que es el estado "
        "que este corte existe para eliminar"
    )
    # EL MENSAJE, no el color: tiene que nombrar el codigo y LAS DOS
    # declaraciones, o el aviso no sirve para corregir nada.
    assert "WORKSPACE_AUTHORITY_DIVERGENT" in html
    assert WS_PERFIL in html and WS_ENTORNO in html


def test_el_aviso_no_publica_rutas_internas(entorno):
    """Repo publico: se publican CODIGOS, no rutas ni texto libre del motor."""
    db_path, auth_db, app, fuentes = entorno
    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))

    assert str(fuentes) not in html, "la pantalla publica la ruta del almacen"
    assert "perfil-operador.json" not in html


# ---------------------------------------------------------------------------
# EL PUNTO DE OPERACION DICE LA CAUSA
# ---------------------------------------------------------------------------

def test_un_workspace_inventado_se_rechaza_SIN_inventar_una_causa(entorno):
    """NO SE FABRICA CAUSALIDAD.

    Con una errata cualquiera el producto no sabe por que se tecleo eso, asi
    que NO dice «divergencia». Si dijera lo mismo para los dos casos, el
    diagnostico no distinguiria nada y el test anterior seria un falso verde.
    """
    db_path, auth_db, app, _ = entorno
    jugadora, token = _admin(auth_db, db_path)
    cliente = _cliente(app, token)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, jugadora.id, "ws-que-nadie-declara", csrf)

    assert r.status_code == 400
    assert "WORKSPACE_AUTHORITY_DIVERGENT" not in r.text, (
        "se atribuye a la divergencia un rechazo que no tiene nada que ver: "
        "eso es fabricar causalidad"
    )


def test_el_workspace_del_ENTORNO_ya_no_se_concede(entorno):
    """CONSECUENCIA ESPERADA de la ronda 3, y se dice por que.

    Esta prueba afirmaba lo contrario —que conceder en el workspace del
    ENTORNO funciona—, y era correcta mientras el entorno era la autoridad.
    Ahora la autoridad es el perfil, asi que el workspace del entorno es
    exactamente lo que `es_workspace_canonico` tiene que rechazar. El control
    positivo de la tabla lo hace ahora `test_R3_conceder_en_el_workspace_del_
    perfil_YA_FUNCIONA`, que comprueba que el endpoint no rechaza TODO.
    """
    db_path, auth_db, app, _ = entorno
    jugadora, token = _admin(auth_db, db_path)
    cliente = _cliente(app, token)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, jugadora.id, WS_ENTORNO, csrf)
    assert r.status_code == 400, (
        "conceder en el workspace del ENTORNO sigue funcionando: el entorno "
        f"no ha dejado de ser autoridad ({r.status_code})"
    )


# ---------------------------------------------------------------------------
# SIMETRICO — sin divergencia no hay aviso
# ---------------------------------------------------------------------------

def test_simetrico_una_configuracion_coherente_no_ensena_ningun_aviso(entorno):
    """Un gate que se pone rojo siempre no guarda, molesta."""
    from app.config import get_settings

    db_path, auth_db, app, fuentes = entorno
    (fuentes / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS_ENTORNO}), encoding="utf-8"
    )
    get_settings.cache_clear()

    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))

    assert "aviso-autoridad-workspace" not in html, (
        "se avisa de una divergencia que no existe: perfil y entorno declaran "
        "lo mismo"
    )
    assert "WORKSPACE_AUTHORITY_DIVERGENT" not in html


def test_simetrico_un_despliegue_sin_perfil_tampoco_avisa(entorno):
    """Sin boveda solo habla el entorno: es el fallback, no una divergencia."""
    from app.config import get_settings

    db_path, auth_db, app, fuentes = entorno
    (fuentes / "perfil-operador.json").unlink()
    get_settings.cache_clear()

    _, token = _admin(auth_db, db_path)
    html, _ = _pantalla(_cliente(app, token))
    assert "aviso-autoridad-workspace" not in html


# ===========================================================================
# RONDA 2 · D1 — LAS OTRAS DOS PANTALLAS, QUE ESTABAN MUDAS
# ===========================================================================
# El aviso existia en `/admin/partidas` y en NINGUNA otra parte. `/v3/review` y
# el panel de operaciones seguian en silencio — y `/v3/review` es la peor de
# las tres para estarlo: aqui el dano no es un 400 recuperable, sino una
# decision humana que MUTA material de un workspace que el revisor no ve.
#
# LOS TESTIGOS DE UNA PANTALLA PIDEN LA PANTALLA: todo lo de abajo es un GET
# del HTML. Ningun diccionario de servicio.


@pytest.fixture
def revisor(entorno):
    """Sesion de revisor sobre el MISMO despliegue divergente."""
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    db_path, auth_db, app, _ = entorno
    with auth_db.get_conn(db_path) as conn:
        usuario = auth_db.create_user(
            conn, username="rev", display_name="Rev",
            password_hash=hash_password("TestPass_1234567890!"), role="reviewer",
        )
        token, _ = create_session(conn, usuario)
    return _cliente(app, token)


@pytest.fixture
def paneles_on():
    """Enciende el hueco B por su LETRA, que es lo unico que el chasis acepta."""
    import os as _os
    from app.config import get_settings

    previos = {k: _os.environ.get(k) for k in ("S9K_PANEL_B_ENABLED",)}
    _os.environ["S9K_PANEL_B_ENABLED"] = "true"
    get_settings.cache_clear()
    yield
    for k, v in previos.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v
    get_settings.cache_clear()


def _html(cliente, ruta: str) -> str:
    r = cliente.get(ruta)
    assert r.status_code == 200, f"{ruta} -> {r.status_code}"
    return r.text


def test_D1_la_cola_de_revision_avisa_de_la_divergencia(revisor):
    """LA PANTALLA DONDE EL DANO ES UNA MUTACION, no un 400.

    Si esta prueba se pone roja, el revisor vuelve a decidir sobre material de
    otro workspace sin una sola senal.
    """
    html = _html(revisor, "/v3/review")

    assert "aviso-autoridad-workspace" in html, (
        "/v3/review sigue MUDA ante la divergencia: es la pantalla con las "
        "unicas escrituras de dominio y la que el propio corte senala como "
        "sitio donde un revisor muta material de un workspace que no ve"
    )
    assert "WORKSPACE_AUTHORITY_DIVERGENT" in html
    assert WS_PERFIL in html and WS_ENTORNO in html, (
        "el aviso no nombra las dos declaraciones: el revisor no puede saber "
        "de que ambito es lo que tiene delante"
    )


def test_D1_el_panel_de_operaciones_avisa_de_la_divergencia(operador_cliente, paneles_on):
    """Donde se lanza la ingesta que decide DONDE acaba el conocimiento."""
    html = _html(operador_cliente, "/panel/operations")

    assert "aviso-autoridad-workspace" in html, (
        "el panel de operaciones sigue MUDO: desde aqui se lanza la ingesta "
        "que materializa en el workspace del perfil mientras el visor mira otro"
    )
    assert "WORKSPACE_AUTHORITY_DIVERGENT" in html


@pytest.fixture
def operador_cliente(entorno):
    db_path, auth_db, app, _ = entorno
    _, token = _admin(auth_db, db_path)
    return _cliente(app, token)


def test_D1_las_TRES_pantallas_avisan_a_la_vez(operador_cliente, revisor, paneles_on):
    """La condicion 2 es sobre EL PRODUCTO, no sobre una pantalla.

    «Una divergencia que se nota en una pantalla y sigue silenciosa en las
    otras no cumple la condicion.» Esta prueba es esa frase, ejecutable.
    """
    mudas = []
    for cliente, ruta in (
        (operador_cliente, "/admin/partidas"),
        (revisor, "/v3/review"),
        (operador_cliente, "/panel/operations"),
    ):
        if "aviso-autoridad-workspace" not in _html(cliente, ruta):
            mudas.append(ruta)
    assert not mudas, f"pantallas que siguen mudas ante la divergencia: {mudas}"


def test_D1_el_aviso_tiene_UN_solo_productor(entorno):
    """Y no cuatro copias, que es como nacio el hueco.

    TECHO DECLARADO: es una red AST sobre las plantillas y sobre el modulo de
    autoridad. NO ve un aviso montado a mano en un router sin usar el partial
    ni el productor; para eso esta la tabla de pantallas de arriba, que mira el
    HTML servido.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "app" / "templates"
    con_testid = sorted(
        p.relative_to(raiz).as_posix()
        for p in raiz.rglob("*.html")
        if "aviso-autoridad-workspace" in p.read_text(encoding="utf-8")
    )
    assert con_testid == ["_aviso_autoridad_workspace.html"], (
        "el cartel esta duplicado en plantillas: la siguiente pantalla nacera "
        f"muda o con otro texto. Lo llevan: {con_testid}"
    )


# ---------------------------------------------------------------------------
# SIMETRICO de D1 — ninguna de las tres molesta si la configuracion es legitima
# ---------------------------------------------------------------------------

def test_D1_simetrico_sin_divergencia_ninguna_pantalla_avisa(
    entorno, operador_cliente, revisor, paneles_on
):
    """Un gate que se pone rojo siempre no guarda, molesta — en las TRES."""
    from app.config import get_settings

    _db, _auth, _app, fuentes = entorno
    (fuentes / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS_ENTORNO}), encoding="utf-8"
    )
    get_settings.cache_clear()

    ruidosas = []
    for cliente, ruta in (
        (operador_cliente, "/admin/partidas"),
        (revisor, "/v3/review"),
        (operador_cliente, "/panel/operations"),
    ):
        if "aviso-autoridad-workspace" in _html(cliente, ruta):
            ruidosas.append(ruta)
    assert not ruidosas, (
        f"se avisa de una divergencia que no existe en: {ruidosas}"
    )


def test_D1_simetrico_las_tres_pantallas_siguen_sirviendo_200(
    operador_cliente, revisor, paneles_on
):
    """CONTROL POSITIVO: el aviso no rompe ni bloquea lo que ya funcionaba.

    Sin esto, todas las pruebas de ausencia de aviso saldrian verdes si las
    pantallas hubieran pasado a devolver 500 o 302.
    """
    for cliente, ruta in (
        (operador_cliente, "/admin/partidas"),
        (revisor, "/v3/review"),
        (operador_cliente, "/panel/operations"),
    ):
        r = cliente.get(ruta)
        assert r.status_code == 200, f"{ruta} dejo de servirse: {r.status_code}"


def test_D1_el_aviso_de_las_nuevas_pantallas_no_publica_rutas(revisor, entorno):
    """Repo publico: codigos, no rutas ni nombres de fichero internos."""
    _db, _auth, _app, fuentes = entorno
    html = _html(revisor, "/v3/review")
    assert str(fuentes) not in html
    assert "perfil-operador.json" not in html


def test_D1_los_acuses_de_sellado_y_apply_aterrizan_en_pantalla_avisada(
    operador_cliente, paneles_on
):
    """LOS ACUSES ENTRAN, y no hacia falta una superficie nueva. MEDIDO.

    `chassis_operations.py:989` y `:1111` construyen el destino de los POST de
    sellado y de apply como `url_for('chassis_operations') + "?aviso=<CODIGO>"`.
    Es decir: el acuse NO es una pantalla propia — es un parametro sobre EL
    PANEL, que es justo la pantalla a la que este corte le acaba de poner el
    aviso. Asi que el operador que acaba de sellar o de aplicar aterriza viendo
    la divergencia.

    Esto se MIDE en vez de declararse: se pide la pantalla con la forma exacta
    de la URL de aterrizaje y se comprueba que el cartel esta. Si alguien
    moviera los acuses a una pantalla propia, esta prueba seguiria verde y
    dejaria de cubrir el caso — por eso se nombra el limite aqui, en vez de
    fingir que cubre todos los acuses posibles.
    """
    for codigo in ("PLAN_SEALED", "PLAN_SEALED_SIN_PROYECCION", "PLAN_APPLIED",
                   "APPLY_NOT_ENABLED"):
        html = _html(operador_cliente, f"/panel/operations?aviso={codigo}")
        assert "aviso-autoridad-workspace" in html, (
            f"tras el acuse '{codigo}' el operador aterriza en una pantalla que "
            "NO avisa de la divergencia: acaba de decidir sobre un ambito que "
            "puede no ser el que cree"
        )


# ---------------------------------------------------------------------------
# RONDA 3 — LA PROPIEDAD QUE CIERRA LA 1a Y LA 5a, QUE SON LA MISMA
# ---------------------------------------------------------------------------
# En las rondas 1 y 2 aqui vivian dos pruebas que afirmaban lo contrario: que
# `allowed_workspaces` sale del ENTORNO. Eran la MEDICION DEL DEFECTO, no una
# garantia, y por eso se han sustituido — dejarlas verdes ahora significaria
# que el defecto sigue.
#
# TODO LO DE ABAJO SE MIDE CON LA DIVERGENCIA PUESTA (`perfil=A`, `env=B`), que
# es el caso que fallaba. Con los valores alineados el defecto es INVISIBLE, de
# modo que una prueba con A == B no puede cazarlo.


def _contexto_de_la_peticion(cliente=None):
    """El contexto EFECTIVO de una peticion, por la dependencia de verdad.

    LA POLITICA EFECTIVA, NO NUESTRA COPIA — y esto costo un rojo del propio
    calibrador. La primera version llamaba al helper
    `_workspace_canonico_de_la_peticion` por su cuenta y armaba el contexto a
    mano. Parecia lo mismo, pero SALTABA la linea que decide: con la mutacion
    10 puesta —el entorno gobernando otra vez `allowed_workspaces`— esta prueba
    seguia VERDE, es decir, no protegia nada. Lo caz la calibracion, no una
    lectura.

    Ahora se ejecuta `get_visibility_context(request)`, que es exactamente la
    dependencia que FastAPI invoca en cada peticion, sobre una `Request`
    minima. Si alguien cambia de donde sale `default_workspace`, este camino lo
    nota.
    """
    from starlette.requests import Request as _Request

    from app.authz.dependencies import get_visibility_context

    ambito = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    peticion = _Request(ambito)
    return get_visibility_context(peticion)


def test_R3_authz_resuelve_el_workspace_del_PERFIL_con_la_divergencia_puesta(
    entorno, capsys
):
    """`perfil=A / env=B` -> `allowed_workspaces == {A}`. EL LISTON."""
    contexto = _contexto_de_la_peticion()
    efectivo = sorted(contexto.allowed_workspaces)
    print(f"[F-2 R3] allowed_workspaces = {efectivo}; perfil='{WS_PERFIL}'; "
          f"entorno='{WS_ENTORNO}'")

    assert efectivo == [WS_PERFIL], (
        "la autorizacion NO resuelve el workspace del perfil con la "
        f"divergencia puesta: perfil='{WS_PERFIL}', entorno='{WS_ENTORNO}', "
        f"allowed_workspaces={efectivo}. El entorno vuelve a gobernar y el "
        "conocimiento seguiria materializandose donde nadie puede verlo"
    )
    assert WS_ENTORNO not in efectivo, (
        f"'{WS_ENTORNO}' (la declaracion secundaria) sigue gobernando la "
        "autorizacion"
    )


def test_R3_el_singleton_NO_cambia_de_modelo(entorno):
    """CONDICION 4: nada de usuario -> varios workspaces.

    `allowed_workspaces` sigue teniendo EXACTAMENTE un elemento para todo rol.
    Si esta prueba se pone roja, se ha abierto la pluralidad y hay que parar.
    """
    from app.authz.dependencies import _workspace_canonico_de_la_peticion
    from app.authz.context import build_viewer_context
    from app.config import get_settings

    for rol in ("viewer", "reviewer", "admin"):
        ctx = build_viewer_context(
            role=rol, auth_enabled=True,
            default_workspace=_workspace_canonico_de_la_peticion(get_settings()),
        )
        assert len(ctx.allowed_workspaces) == 1, (
            f"`allowed_workspaces` dejo de ser un singleton para '{rol}': "
            f"{sorted(ctx.allowed_workspaces)}. Eso es el cambio de modelo "
            "vetado para F-2"
        )


def test_R3_la_divergencia_NO_se_oculta_aunque_el_perfil_mande(entorno):
    """CONDICION 3: resolver al perfil NO es normalizar en silencio.

    El veredicto y el diagnostico son ortogonales: `resuelto` y `diverge` a la
    vez. Si alguien "simplificara" el resolvedor haciendo que dejara de marcar
    la discrepancia, esto se pone rojo — y el aviso de las tres pantallas se
    apagaria sin que nadie se enterase.
    """
    from app.authz import autoridad_workspace as autoridad

    resuelta = autoridad.resolver()
    assert resuelta.resuelto and resuelta.valor == WS_PERFIL, resuelta.diagnostico()
    assert resuelta.configuracion_divergente, (
        "el resolvedor manda al perfil pero YA NO DICE que el entorno lo "
        "contradice: la divergencia se ha normalizado en silencio, que es "
        "justo lo que la pieza 5 prohibe"
    )
    assert resuelta.declarado_por_entorno == WS_ENTORNO
    assert WS_ENTORNO in resuelta.diagnostico()


def test_R3_ausencia_de_perfil_NO_se_reporta_como_divergencia(tmp_path):
    """Y la otra mitad de la regla: AUSENCIA != DIVERGENCIA.

    Un despliegue sin bovedas no tiene una discrepancia: tiene una ausencia.
    Pintarlo como «configuracion divergente» seria el falso aviso que el
    simetrico existe para impedir.
    """
    from app.authz import autoridad_workspace as autoridad

    vacio = tmp_path / "sin-bovedas"
    vacio.mkdir()
    env = {"S9K_INGEST_SOURCES_DIR": str(vacio), "S9K_DEFAULT_WORKSPACE": WS_ENTORNO}
    resuelta = autoridad.resolver(env)

    assert not resuelta.configuracion_divergente, (
        "una ausencia de perfil se esta reportando como divergencia"
    )
    assert resuelta.codigo == autoridad.COD_FALLBACK
    assert resuelta.valor == WS_ENTORNO, (
        "sin perfil, el contrato permite el fallback al entorno — y esta "
        "decision esta declarada en el docstring del modulo"
    )


def test_R3_la_cache_por_peticion_no_se_queda_rancia(tmp_path):
    """CONTROL POSITIVO de la cache: una autoridad rancia seria peor que el coste.

    Se resuelve, se EDITA el perfil, y se vuelve a resolver por el camino
    cacheado. Si devolviera el valor viejo, el producto seguiria autorizando
    sobre un workspace que ya no declara nadie.
    """
    from app.authz import autoridad_workspace as autoridad

    raiz = tmp_path / "fuentes"
    raiz.mkdir()
    perfil = raiz / "perfil-operador.json"
    perfil.write_text(json.dumps({"workspace": "ws-antes"}), encoding="utf-8")
    env = {"S9K_INGEST_SOURCES_DIR": str(raiz)}

    assert autoridad.resolver_por_peticion(env).valor == "ws-antes"
    perfil.write_text(json.dumps({"workspace": "ws-despues"}), encoding="utf-8")
    assert autoridad.resolver_por_peticion(env).valor == "ws-despues", (
        "la cache devolvio una autoridad RANCIA: el producto autorizaria "
        "sobre un workspace que el perfil ya no declara"
    )


def test_R3_conceder_en_el_workspace_del_perfil_YA_FUNCIONA(entorno):
    """La consecuencia visible en el producto: el 400 desaparece.

    Este es el defecto nº1 del diagnostico original —«desde la web no se puede
    conceder acceso de partida al workspace donde esta el conocimiento»— y
    cierra aqui. La guarda del Corte 1 NO se relajo: lo que cambio es cual es
    el workspace canonico.
    """
    db_path, auth_db, app, _ = entorno
    jugadora, token = _admin(auth_db, db_path)
    cliente = _cliente(app, token)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, jugadora.id, WS_PERFIL, csrf)
    assert r.status_code in (302, 303), (
        "conceder acceso al workspace del PERFIL —donde acaba el "
        f"conocimiento— sigue rechazandose: {r.status_code}"
    )


def test_R3_un_workspace_inventado_SIGUE_rechazandose(entorno):
    """CONTROL NEGATIVO del anterior: la guarda no se ha abierto.

    Sin esto, el test de arriba saldria verde igual si hubieramos quitado la
    comprobacion en vez de corregir la autoridad.
    """
    db_path, auth_db, app, _ = entorno
    jugadora, token = _admin(auth_db, db_path)
    cliente = _cliente(app, token)
    _, csrf = _pantalla(cliente)

    r = _conceder(cliente, jugadora.id, "ws-que-nadie-declara", csrf)
    assert r.status_code == 400, (
        "la unidad de control del Corte 1 se ha relajado: un workspace "
        f"inventado ya no se rechaza ({r.status_code})"
    )


def test_R3_con_perfil_y_entorno_de_acuerdo_todo_funciona(entorno):
    """EL SIMETRICO DEL NEGATIVO ANTI-REGRESION, y la mitad que le da sentido.

    Con `A == B` el producto funciona **aunque el entorno vuelva a gobernar**.
    Por eso el defecto es INVISIBLE con los valores alineados, y por eso la
    unica prueba capaz de cazarlo es una que conserve la divergencia puesta.

    El arnes de calibracion corre esta prueba CON la mutacion 10 aplicada y
    exige que siga VERDE (`CONTROLES_VERDES`). Si se pusiera roja, significaria
    que la prueba que caza el defecto no necesitaba la divergencia — y entonces
    no estaria midiendo lo que dice medir.
    """
    from app.config import get_settings

    _db, _auth, _app, fuentes = entorno
    (fuentes / "perfil-operador.json").write_text(
        json.dumps({"workspace": WS_ENTORNO}), encoding="utf-8"
    )
    get_settings.cache_clear()

    contexto = _contexto_de_la_peticion()
    assert sorted(contexto.allowed_workspaces) == [WS_ENTORNO], (
        "con perfil y entorno DE ACUERDO el producto no resuelve ese valor: "
        f"{sorted(contexto.allowed_workspaces)}"
    )
