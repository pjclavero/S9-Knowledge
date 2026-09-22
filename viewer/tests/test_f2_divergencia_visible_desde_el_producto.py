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


def _contexto_de_la_peticion():
    """El contexto TAL Y COMO lo monta la dependencia de cada peticion.

    No se fabrica a mano: se llama al mismo helper que usa
    `authz/dependencies.py::viewer_context`, con los mismos ajustes. Armarlo
    aparte mediria nuestra copia, no la politica efectiva.
    """
    from app.authz.dependencies import _workspace_canonico_de_la_peticion
    from app.authz.context import build_viewer_context
    from app.config import get_settings

    return build_viewer_context(
        role="viewer",
        auth_enabled=True,
        default_workspace=_workspace_canonico_de_la_peticion(get_settings()),
    )


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
