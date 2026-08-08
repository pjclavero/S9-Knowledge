"""7a RONDA -- un testigo HTTP por cada dimension declarada en el registro.

El sexto dictamen encontro el defecto estructural: el registro DECLARA la
semantica que queremos, y nada probaba que el MOTOR la cumpliera sobre una
peticion real. El caso limite es H6-5: poner `active_character=None` en
`viewer/app/authz/dependencies.py` dejaba 806 tests verdes, porque la unica
prueba de la concesion de personaje consultaba `partida_progress` directamente
en vez de pasar por HTTP. Toda la maquinaria `known_by` podia estar inerte en
produccion con el CI en verde.

Reutiliza el entorno de `test_autorizacion_e2e_http` (auth activa, base
temporal, proveedor falso): aqui tampoco se construye ningun `ViewerContext`.
"""
from __future__ import annotations

from tests.test_autorizacion_e2e_http import (  # noqa: F401  (fixtures)
    NODOS,
    PARTIDA,
    WS,
    _cliente,
    _ids_listados,
    _jugadora,
    _limpia_settings,
    entorno,
)


# --- active_character: la concesion de personaje TIENE efecto (H6-5) --------

def test_la_concesion_de_personaje_abre_su_secreto_por_HTTP(entorno):
    """H6-5. Si `dependencies.py` dejara de poblar `active_character`, este
    test se pone rojo -- y antes NINGUNO lo hacia."""
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana")
    ids = _ids_listados(_cliente(app, token))
    assert "secreto_del_pj" in ids, (
        "la concesion de personaje no llega al motor: `known_by` esta inerte"
    )


def test_sin_personaje_concedido_el_mismo_secreto_queda_oculto(entorno):
    """La otra mitad: si estuviera visible sin conceder personaje, el test de
    arriba pasaria por una razon equivocada."""
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5, personaje=None)
    assert "secreto_del_pj" not in _ids_listados(_cliente(app, token))


def test_el_secreto_de_otra_PJ_no_se_abre_con_mi_personaje(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana")
    assert "secreto_ajeno" not in _ids_listados(_cliente(app, token))


def test_revocar_el_personaje_retira_el_secreto_EN_LA_SIGUIENTE_PETICION(entorno):
    """H6-5: la revocacion se comprobaba leyendo la tabla, no pidiendo por HTTP."""
    db_path, auth_db, app = entorno
    u, token = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana")
    cliente = _cliente(app, token)
    assert "secreto_del_pj" in _ids_listados(cliente)

    with auth_db.get_conn(db_path) as conn:
        auth_db.grant_partida_access(conn, u.id, WS, PARTIDA, max_visible_session=5)

    assert "secreto_del_pj" not in _ids_listados(cliente), (
        "revocar el personaje no tuvo efecto sobre la peticion siguiente"
    )


def test_known_by_characters_tambien_concede_por_HTTP(entorno):
    """Segundo nombre del mismo dato (lo escribe `ingest_rpg`)."""
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana")
    assert "secreto_por_known_by_characters" in _ids_listados(_cliente(app, token))


def test_known_by_malformado_deniega_el_nodo_por_HTTP(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana")
    assert "known_by_corrupto" not in _ids_listados(_cliente(app, token))


# --- known_from_session: la ausencia deniega (H6-1) -------------------------

def test_contenido_de_partida_SIN_revelacion_no_se_lista(entorno):
    """H6-1 por HTTP. `if desde is not None:` dejaba pasar la ausencia entera."""
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=99, personaje="pc:ana")
    ids = _ids_listados(_cliente(app, token))
    assert "partida_sin_revelacion" not in ids, (
        "un nodo de partida sin `known_from_session` se salta la regla entera"
    )


def test_el_acceso_por_ID_al_nodo_sin_revelacion_tampoco_lo_abre(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=99)
    r = _cliente(app, token).get("/api/entities/partida_sin_revelacion",
                                 headers={"accept": "application/json"})
    assert r.status_code == 404


# --- max_visible_session sin partida activa (H6-9) --------------------------

def test_un_autenticado_SIN_partida_activa_no_ve_mas_que_con_ella(entorno):
    """H6-9. `dependencies.py` devolvia `None` (= sin tope) cuando no habia
    partida activa, dejando al autenticado MENOS restringido que un anonimo,
    que recibe 0. Un permiso que crece al quitarle contexto al lector es un
    fallo abierto por definicion.
    """
    db_path, auth_db, app = entorno
    _, con = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana",
                       usuario="con_partida")
    _, sin = _jugadora(auth_db, db_path, tope=5, personaje="pc:ana",
                       usuario="sin_partida", activar=False)

    ids_con = _ids_listados(_cliente(app, con))
    ids_sin = _ids_listados(_cliente(app, sin))
    assert ids_sin <= ids_con, (
        f"sin partida activa se ve MAS que con ella: {sorted(ids_sin - ids_con)}"
    )
    de_partida = {n["id"] for n in NODOS if n.get("scope") == "partida"}
    assert not (ids_sin & de_partida), (
        "sin partida activa no puede verse ningun material de partida"
    )


# --- ambito, workspace y visibilidad, atravesando HTTP ----------------------

def test_el_workspace_ajeno_no_se_lista_por_HTTP(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    assert "otro_ws" not in _ids_listados(_cliente(app, token))


def test_un_dato_sin_scope_declarado_no_se_lista_por_HTTP(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    assert "sin_scope" not in _ids_listados(_cliente(app, token))


def test_partida_id_en_blanco_NO_se_degrada_a_lore_compartido(entorno):
    """H6-2: un ambito de partida con identificador ilegible no se resuelve
    hacia la capa juego, que es la mas abierta."""
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    assert "partida_id_en_blanco" not in _ids_listados(_cliente(app, token))


def test_una_partida_activa_en_blanco_no_es_un_comodin(entorno):
    """El otro extremo del mismo hallazgo: una partida activa ilegible no puede
    abrir ni el dato con `partida_id` en blanco ni la partida real."""
    db_path, auth_db, app = entorno
    u, _ = _jugadora(auth_db, db_path, tope=5, activar=False)

    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        token, sesion = create_session(conn, u)
        auth_db.set_session_active_partida(conn, sesion.id, "   ")

    ids = _ids_listados(_cliente(app, token))
    assert "partida_id_en_blanco" not in ids
    assert "revelado_s2" not in ids, "una partida en blanco activo la partida real"


def test_una_visibilidad_corrupta_no_se_lista_por_HTTP(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    assert "visibilidad_corrupta" not in _ids_listados(_cliente(app, token))


def test_el_material_de_otra_partida_no_se_lista_por_HTTP(entorno):
    db_path, auth_db, app = entorno
    _, token = _jugadora(auth_db, db_path, tope=5)
    assert "de_otra_partida" not in _ids_listados(_cliente(app, token))


# --- capacidades de rol (can_view_secret / can_view_future) -----------------

def test_can_view_secret_es_lo_unico_que_abre_un_secreto_ajeno(entorno):
    """El viewer no lo ve; el admin (que si tiene la capacidad) si."""
    db_path, auth_db, app = entorno
    _, viewer = _jugadora(auth_db, db_path, tope=99, usuario="jugadora")
    _, admin = _jugadora(auth_db, db_path, tope=99, usuario="gm", role="admin")
    assert "secreto_ajeno" not in _ids_listados(_cliente(app, viewer))
    assert "secreto_ajeno" in _ids_listados(_cliente(app, admin))


def test_can_view_future_es_lo_unico_que_salta_el_tope(entorno):
    db_path, auth_db, app = entorno
    _, viewer = _jugadora(auth_db, db_path, tope=5, usuario="jugadora")
    _, revisor = _jugadora(auth_db, db_path, tope=5, usuario="revisora",
                           role="reviewer")
    assert "spoiler_s40" not in _ids_listados(_cliente(app, viewer))
    assert "spoiler_s40" in _ids_listados(_cliente(app, revisor))
