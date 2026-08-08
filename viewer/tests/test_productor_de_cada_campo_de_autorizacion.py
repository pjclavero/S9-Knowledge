"""La red que faltaba: todo campo de autorizacion debe tener un PRODUCTOR real.

Cuatro dictamenes independientes seguidos encontraron la misma forma de fallo:

    H1/H2  la proyeccion no transportaba un campo que el motor leia
    G3     idem, escondido dentro de la red puesta para impedirlo
    T1     el motor leia `party`/`is_public`/`session_index` y NADIE los escribia
    H-A    el motor leia `max_visible_session` del contexto, el contexto lo leia
           de `partida_access`, y NADIE escribia esa columna

Siempre lo mismo: una barrera deja de evaluarse y nada se pone rojo. El test de
contrato existente cubre el tramo `proyeccion -> motor`. Este cubre el tramo que
faltaba, `productor -> dato`, que es por donde entraron T1 y H-A.

La regla: si el motor decide con un campo, alguien tiene que poder escribirlo, y
tiene que existir una prueba que lo demuestre de punta a punta. Un campo que
solo aparece en el lector es una barrera decorativa.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.policies.engine import VisibilityPolicy
from app.policies.models import ViewerContext

POLICY = VisibilityPolicy()


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app.auth import db as auth_db

    ruta = tmp_path / "auth.db"
    auth_db.migrate(ruta)
    return auth_db, ruta


def _usuario(auth_db, conn, nombre="jugadora"):
    return auth_db.create_user(
        conn, username=nombre, display_name=nombre,
        password_hash="no-es-un-hash-real", role="viewer",
    )


def test_la_concesion_escribe_de_verdad_la_progresion_de_campana(db):
    """H-A: el esquema y el lector existian; el escritor, no.

    `grant_partida_access` no fijaba las columnas, la migracion las deja a NULL,
    y `None` significa "sin tope": la regla de sesion de revelacion no llegaba a
    evaluarse en NINGUNA peticion real, con la suite en verde.
    """
    auth_db, ruta = db
    with auth_db.get_conn(ruta) as conn:
        u = _usuario(auth_db, conn)
        auth_db.grant_partida_access(
            conn, u.id, "ws", "partida:alfa", granted_by="admin",
            max_visible_session=7, character_id="pc:ana",
        )
        assert auth_db.partida_progress(conn, u.id, "ws", "partida:alfa") == (7, "pc:ana")


def test_subir_el_tope_de_una_concesion_existente_tiene_efecto(db):
    """La progresion CAMBIA con cada sesion jugada.

    `INSERT OR IGNORE` no actualiza una fila existente: sin el UPDATE, el
    operador subiria el tope, no pasaria nada, y creeria haberlo subido.
    """
    auth_db, ruta = db
    with auth_db.get_conn(ruta) as conn:
        u = _usuario(auth_db, conn)
        auth_db.grant_partida_access(conn, u.id, "ws", "partida:alfa",
                                     max_visible_session=3, character_id="pc:ana")
        auth_db.grant_partida_access(conn, u.id, "ws", "partida:alfa",
                                     max_visible_session=9)
        tope, pj = auth_db.partida_progress(conn, u.id, "ws", "partida:alfa")
        assert tope == 9
        assert pj == "pc:ana"   # no se pierde lo que no se vuelve a declarar


def test_un_tope_corrupto_cierra_en_vez_de_abrir(db):
    """H-B: degradar un valor ilegible a `None` ABRIA la barrera.

    `None` significa "sin tope", asi que tratar un dato corrupto como `None` es
    justo lo contrario de fail-closed: quien pueda escribir basura en esa
    columna levanta la proteccion. Ahora un valor ilegible es el tope mas
    restrictivo posible.
    """
    auth_db, ruta = db
    with auth_db.get_conn(ruta) as conn:
        u = _usuario(auth_db, conn)
        auth_db.grant_partida_access(conn, u.id, "ws", "partida:alfa", max_visible_session=5)
        conn.execute("UPDATE partida_access SET max_visible_session = -5")
        conn.commit()
        tope, _ = auth_db.partida_progress(conn, u.id, "ws", "partida:alfa")
        assert tope == 0, "un tope ilegible no puede significar 'sin tope'"


def test_la_concesion_rechaza_una_progresion_invalida(db):
    auth_db, ruta = db
    with auth_db.get_conn(ruta) as conn:
        u = _usuario(auth_db, conn)
        for malo in (-1, "tres", 3.5, True):
            with pytest.raises(ValueError):
                auth_db.grant_partida_access(conn, u.id, "ws", f"p:{malo}",
                                             max_visible_session=malo)


def test_el_tope_escrito_llega_a_apagar_contenido_no_revelado(db):
    """De punta a punta: lo que escribe el admin decide lo que ve el jugador."""
    auth_db, ruta = db
    with auth_db.get_conn(ruta) as conn:
        u = _usuario(auth_db, conn)
        auth_db.grant_partida_access(conn, u.id, "ws", "partida:alfa",
                                     max_visible_session=5, character_id="pc:ana")
        tope, personaje = auth_db.partida_progress(conn, u.id, "ws", "partida:alfa")

    ctx = ViewerContext(
        role="viewer", allowed_workspaces=frozenset({"ws"}),
        active_partida="partida:alfa", allowed_partida_ids=frozenset({"partida:alfa"}),
        max_visible_session=tope, active_character=personaje,
    )
    nodo = {"id": "n", "workspace": "ws", "scope": "partida",
            "partida_id": "partida:alfa", "visibility": "player"}
    assert POLICY.can_view({**nodo, "known_from_session": 3}, ctx).visible
    futuro = POLICY.can_view({**nodo, "known_from_session": 9}, ctx)
    assert not futuro.visible and futuro.reason == "future_session"
    # Y el personaje concedido hace que `knows()` deje de ser inerte.
    assert ctx.knows({**nodo, "known_by": ["pc:ana"]})


def test_cada_campo_de_autorizacion_tiene_un_productor_en_el_repositorio():
    """Red generica contra la reincidencia.

    Si el motor empieza a decidir con un campo nuevo y nadie lo escribe, esto se
    pone rojo. Es deliberadamente tosco --busca el nombre en el codigo de
    escritura-- porque el fallo que persigue tambien lo es: el campo sencillamente
    NO EXISTE fuera del lector.
    """
    raiz = Path(__file__).resolve().parents[2]
    productores = [
        raiz / "data-engine" / "app",
        raiz / "viewer" / "app" / "auth",
        raiz / "viewer" / "app" / "routers",
    ]
    fuente = ""
    for base in productores:
        for py in base.rglob("*.py"):
            if "test" in py.parts:
                continue
            fuente += py.read_text(encoding="utf-8", errors="ignore")

    from tests.test_provider_authz_fields_contract import CAMPOS_AUTORIZACION_NODO

    sin_productor = [c for c in CAMPOS_AUTORIZACION_NODO if c not in fuente]
    assert not sin_productor, (
        f"el motor decide con {sin_productor} y nadie los escribe: son barreras "
        f"decorativas. Paso con `party`, `is_public` y `session_index` (T1) y con "
        f"`max_visible_session` (H-A)."
    )
