# -*- coding: utf-8 -*-
"""CARRIL M — la divergencia local de una partida, vista POR LA PANTALLA.

QUE SE DEMUESTRA AQUI
---------------------
El mecanismo de divergencia local (`local_override_of`, M4) ya existia y
funcionaba, pero su lado de LECTURA no tenia consumidor de produccion: el
unico llamador no-test de `writer/reads.py::list_visible_assertions` eran sus
propios tests, y su docstring lo admitia. Estas pruebas cierran ese tramo y lo
hacen por donde el producto lo enseña.

POR QUE POR HTTP Y NO LLAMANDO AL PROVEEDOR
-------------------------------------------
Porque el estado que este carril viene a cerrar es, exactamente, "se puede
demostrar llamando a una API interna a mano". Una prueba que invocase
`PolicyFilteredProvider.list_assertions` directamente volveria a demostrar lo
mismo que ya estaba demostrado y seguiria sin tocar la pantalla.

Y por una razon mas concreta, ya medida en este repositorio: el punto de
inyeccion del visor esta CONGELADO --`get_filtered_provider` llama a
`get_visibility_context` como funcion normal, no via `Depends`--, asi que un
contexto inyectado a mano seria inerte y saldria verde por no morder. El
contexto de estas pruebas se construye con la cadena real: usuario en
`auth.db`, concesion de partida (`grant_partida_access`) y partida activa de
sesion (`set_session_active_partida`).

Todas las pruebas de enmascarado de este modulo piden la PAGINA
(`GET /panel/entities/item/{id}`) y afirman sobre el HTML renderizado. Es
deliberado: en esta misma sesion otro carril añadio una cabecera visible a una
pantalla y borrarla entera dejo su suite igual de verde, porque sus casos
probaban la propiedad y ninguno renderizaba la pagina.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chassis import FEATURE_SLOTS, slot_flag_env
from app.providers.base import GraphProvider

SLOT = next(s for s in FEATURE_SLOTS if s.key == "G")
FLAG = slot_flag_env(SLOT)
WS = "juego:carril-m"
PASSWORD = "Contrasena-De-Prueba-1"

#: La entidad de la que se cuentan hechos. Capa juego: su identidad es
#: workspace-global a proposito (writer/schema.py), y este carril no la toca.
SUJETO = "dios-sol"

#: Textos UNICOS. Se afirma sobre el texto y no sobre un contador porque un
#: contador no distingue "ve la version correcta" de "ve una cualquiera".
TEXTO_LORE = "el dios sol es benevolo con los navegantes"
TEXTO_DIVERGENCIA_B = "en esta partida el dios sol exige sacrificios"
TEXTO_SOLO_B = "el templo de Bryn arde desde la tercera sesion"
TEXTO_LORE_2 = "el dios sol tiene un templo en la capital"
TEXTO_DIVERGENCIA_A = "en esta partida el templo de la capital esta en ruinas"

ID_LORE = "hecho-lore-dios-sol"
ID_DIVERGENCIA_B = "hecho-partidaB-dios-sol"
ID_SOLO_B = "hecho-partidaB-templo"
#: Segundo hecho de lore, divergido por la OTRA partida. Existe por una razon
#: medida: con una sola divergencia, el acotado "solo enmascara la partida
#: ACTIVA" resultaba INDISTINGUIBLE de no acotar, porque la cascada ya retira
#: el material de la otra partida antes de que el enmascarado lo vea. La
#: mutacion que quitaba ese acotado SOBREVIVIA a la suite. Con dos
#: divergencias cruzadas y un lector que ve las dos (admin), el acotado pasa a
#: ser observable y la mutacion muere.
ID_LORE_2 = "hecho-lore-templo-capital"
ID_DIVERGENCIA_A = "hecho-partidaA-templo-capital"

PARTIDA_A = "partida-A"
PARTIDA_B = "partida-B"


# ===========================================================================
# Material: lore comun + partida A + partida B, con la divergencia de B
# ===========================================================================

def _entidad(id_: str) -> dict:
    return {
        "id": id_, "entity_id": id_, "label": id_, "canonical_name": id_,
        "type": "DEIDAD", "description": "Entidad de capa juego.",
        "workspace": WS, "scope": "juego", "visibility": "player",
        "review_status": "reviewed", "confidence": 0.9,
        "source_document": "manual.pdf",
    }


def _hecho(
    id_: str, *, texto: str, partida_id=None, local_override_of=None,
    visibility: str = "player", known_from_session=None,
) -> dict:
    h = {
        "assertion_id": id_, "id": id_,
        "predicate": texto,
        "subject_entity_id": SUJETO, "object_entity_id": "objeto-x",
        "status": "ASSERTED",
        "workspace": WS,
        "scope": "partida" if partida_id is not None else "juego",
        "partida_id": partida_id,
        "local_override_of": local_override_of,
        "visibility": visibility,
        "review_status": "reviewed", "confidence": 0.9,
    }
    if known_from_session is not None:
        h["known_from_session"] = known_from_session
    return h


#: El escenario del requisito, entero y CRUZADO:
#:   lore comun -> ID_LORE   y   ID_LORE_2      (capa juego, sin partida)
#:   partida A  -> diverge de ID_LORE_2, y NO de ID_LORE
#:   partida B  -> diverge de ID_LORE,   y NO de ID_LORE_2
#: Cruzarlas es lo que hace observable que cada partida solo se enmascara con
#: LO SUYO: cada lector tiene, en la misma pagina, un hecho de lore que debe
#: seguir viendo y otro que debe haber sido sustituido.
HECHOS: tuple[dict, ...] = (
    _hecho(ID_LORE, texto=TEXTO_LORE),
    _hecho(ID_LORE_2, texto=TEXTO_LORE_2),
    _hecho(ID_DIVERGENCIA_B, texto=TEXTO_DIVERGENCIA_B,
           partida_id=PARTIDA_B, local_override_of=ID_LORE, known_from_session=0),
    _hecho(ID_DIVERGENCIA_A, texto=TEXTO_DIVERGENCIA_A,
           partida_id=PARTIDA_A, local_override_of=ID_LORE_2, known_from_session=0),
    # Hecho privado de B SIN divergencia: sirve de control interno. Si una
    # prueba viera cero hechos en B, este distingue "enmascarado de mas" de
    # "la partida B no ve nada en absoluto".
    _hecho(ID_SOLO_B, texto=TEXTO_SOLO_B, partida_id=PARTIDA_B,
           known_from_session=0),
)


class ProveedorFalso(GraphProvider):
    """Proveedor BASE crudo. NO filtra nada: la politica real corre encima.

    Es importante que no filtre: si este objeto ya entregase el conjunto
    correcto, la prueba mediria al proveedor falso y no a la barrera.
    """

    name = "falso"

    def __init__(self, hechos=HECHOS):
        self._hechos = list(hechos)

    def is_connected(self): return True
    def workspaces(self): return [WS]
    def counts(self, workspace=None): return (1, 0)
    def entity_types(self, workspace): return []
    def search(self, workspace, q, limit=50): return []
    def graph(self, workspace, limit=300, entity_type=None, q=None): return ([], [])
    def list_sources(self, workspace): return []
    def source_detail(self, workspace, source_id): return None
    def quality_metrics(self, workspace=None): return {}

    def entity(self, entity_id, *, workspaces=None):
        return _entidad(entity_id) if entity_id == SUJETO else None

    def relations_for_entity(self, entity_id, *, workspaces=None):
        return ([], [])

    def list_entities(self, workspace, **kw):
        nodos = [_entidad(SUJETO)] if workspace == WS else []
        return nodos, len(nodos)

    def list_assertions(self, workspace, *, subject_entity_id=None):
        return [
            dict(h) for h in self._hechos
            if h.get("workspace") == workspace
            and (subject_entity_id is None
                 or h.get("subject_entity_id") == subject_entity_id)
        ]


# ===========================================================================
# Fixtures — app REAL, cadena de autorizacion REAL
# ===========================================================================

@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _entorno_limpio():
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    claves = ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE")
    previos = {k: os.environ.get(k) for k in claves}
    os.environ.pop("S9K_AUTH_ENABLED", None)
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    get_settings.cache_clear()
    get_auth_settings.cache_clear()
    yield
    for clave, valor in previos.items():
        if valor is None:
            os.environ.pop(clave, None)
        else:
            os.environ[clave] = valor
    get_settings.cache_clear()
    get_auth_settings.cache_clear()


@pytest.fixture
def con_proveedor(real_app):
    import app.deps as deps

    def instalar(proveedor=None):
        proveedor = proveedor or ProveedorFalso()
        real_app.dependency_overrides[deps.get_provider] = lambda: proveedor
        return proveedor

    yield instalar
    real_app.dependency_overrides.pop(deps.get_provider, None)


@pytest.fixture
def panel_on():
    previo = os.environ.get(FLAG)
    os.environ[FLAG] = "true"
    yield
    if previo is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = previo


@pytest.fixture
def auth_on(tmp_path):
    from app.auth.config import get_auth_settings

    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    return db_path


def _cookie(db_path: Path, username: str, *, partida_id=None, role="viewer") -> str:
    """Lector REAL. Con `partida_id`, ademas, concesion y partida activa."""
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db_mod.get_conn(db_path) as conn:
        u = auth_db_mod.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role,
        )
        auth_db_mod.update_user(conn, u.id, must_change_password=False)
        if partida_id is not None:
            auth_db_mod.grant_partida_access(
                conn, u.id, WS, partida_id, granted_by="admin",
                max_visible_session=5, character_id=None,
            )
        u = auth_db_mod.get_user_by_id(conn, u.id)
        token, sesion = create_session(conn, u)
        if partida_id is not None:
            auth_db_mod.set_session_active_partida(conn, sesion.id, partida_id)
    return token


def _cliente(app, cookie: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        from app.auth.config import get_auth_settings
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


def _ficha(app, cookie):
    """LA PANTALLA. Devuelve la respuesta HTTP de la ficha del sujeto."""
    return _cliente(app, cookie).get(f"{SLOT.prefix}/item/{SUJETO}")


def _hechos_en_pantalla(html: str) -> list[str]:
    """`assertion_id` de cada hecho REALMENTE renderizado en la ficha."""
    return re.findall(r'data-assertion-id="([^"]+)"', html)


# ===========================================================================
# LAS CUATRO GARANTIAS DEL REQUISITO
# ===========================================================================

def test_G1_la_divergencia_de_B_no_modifica_el_lore_comun(
    real_app, con_proveedor, panel_on, auth_on
):
    """Quien mira a capa juego sigue viendo el hecho ORIGINAL, intacto."""
    proveedor = con_proveedor()
    # Un admin lee sin partida activa: es la mirada a capa juego.
    cookie = _cookie(auth_on, "m_admin_juego", role="admin")
    r = _ficha(real_app, cookie)
    assert r.status_code == 200
    assert ID_LORE in _hechos_en_pantalla(r.text)
    assert TEXTO_LORE in r.text

    # Y el dato no se ha tocado: el proveedor sigue entregando el hecho de
    # capa juego con su contenido original. Enmascarar es una decision de la
    # RESPUESTA, nunca una escritura.
    crudos = {h["assertion_id"]: h for h in proveedor.list_assertions(WS)}
    assert crudos[ID_LORE]["predicate"] == TEXTO_LORE
    assert crudos[ID_LORE]["partida_id"] is None
    assert crudos[ID_LORE]["local_override_of"] is None


def test_G2_la_divergencia_de_B_no_cambia_lo_que_ve_A(
    real_app, con_proveedor, panel_on, auth_on
):
    """A sigue viendo el lore comun que B ha divergido, y NO la version de B."""
    con_proveedor()
    cookie = _cookie(auth_on, "m_lectora_a", partida_id=PARTIDA_A)
    r = _ficha(real_app, cookie)
    assert r.status_code == 200
    vistos = _hechos_en_pantalla(r.text)

    assert ID_LORE in vistos, "A debe seguir viendo el lore que diverge B"
    assert TEXTO_LORE in r.text
    # Lo de B no se le cruza NI como hecho ni como texto.
    assert ID_DIVERGENCIA_B not in vistos
    assert TEXTO_DIVERGENCIA_B not in r.text
    assert ID_SOLO_B not in vistos
    assert TEXTO_SOLO_B not in r.text
    # Y su PROPIA divergencia si se le aplica: A no ve las dos versiones.
    assert ID_DIVERGENCIA_A in vistos
    assert ID_LORE_2 not in vistos


def test_G3_B_ve_su_version_y_NO_ve_ademas_la_original(
    real_app, con_proveedor, panel_on, auth_on
):
    """Enmascarar es SUSTITUIR, no añadir: B ve su version y solo la suya.

    Esta es la garantia que mas facilmente sale verde por accidente: si el
    enmascarado no se aplicase, B veria LOS DOS hechos y una prueba que solo
    comprobara "B ve su version" seguiria pasando. Por eso se afirman las dos
    mitades, y la de ausencia va sobre el TEXTO ademas de sobre el id.
    """
    con_proveedor()
    cookie = _cookie(auth_on, "m_lectora_b", partida_id=PARTIDA_B)
    r = _ficha(real_app, cookie)
    assert r.status_code == 200
    vistos = _hechos_en_pantalla(r.text)

    assert ID_DIVERGENCIA_B in vistos, "B debe ver su divergencia"
    assert TEXTO_DIVERGENCIA_B in r.text
    assert ID_LORE not in vistos, "B NO puede ver ademas el hecho original"
    assert TEXTO_LORE not in r.text
    # Control interno: B no se ha quedado sin nada. Si viera cero hechos, la
    # afirmacion de arriba no distinguiria "enmascarado" de "no ve nada".
    assert ID_SOLO_B in vistos
    # Y el lore que B NO ha divergido le sigue llegando entero: el enmascarado
    # es puntual, no un apagon de la capa juego.
    assert ID_LORE_2 in vistos
    assert TEXTO_LORE_2 in r.text
    # La divergencia de A no le llega ni le enmascara nada.
    assert ID_DIVERGENCIA_A not in vistos


def test_G4_la_divergencia_se_marca_como_tal_en_la_pantalla(
    real_app, con_proveedor, panel_on, auth_on
):
    """docs/v3/49 §2.5 punto 4: "con indicacion de que es una divergencia local"."""
    con_proveedor()
    cookie = _cookie(auth_on, "m_lectora_b_marca", partida_id=PARTIDA_B)
    r = _ficha(real_app, cookie)
    assert r.status_code == 200
    assert 'data-role="marca-divergencia"' in r.text
    # La marca va en el hecho divergente y en NINGUN otro.
    marcados = re.findall(
        r'data-assertion-id="([^"]+)"\s+data-divergencia-local="true"', r.text
    )
    assert marcados == [ID_DIVERGENCIA_B]


# ===========================================================================
# CONTROL NEGATIVO: quien no ve, junto a quien SI ve
# ===========================================================================

def test_control_negativo_un_lector_sin_derechos_no_ve_y_otro_SI_ve(
    real_app, con_proveedor, panel_on, auth_on
):
    """"No ve nada" y "la base esta vacia" son indistinguibles por separado.

    Las dos mitades corren sobre EL MISMO material y en la MISMA prueba: si el
    proveedor estuviese vacio o el panel apagado, la mitad positiva caeria y
    la negativa dejaria de significar nada. Un cero solo prueba algo cuando
    convive con un no-cero que sale del mismo sitio.
    """
    con_proveedor()

    # (a) Lector SIN derechos: anonimo, sin cookie ninguna.
    sin_derechos = _cliente(real_app).get(f"{SLOT.prefix}/item/{SUJETO}")
    assert sin_derechos.status_code != 200
    assert TEXTO_LORE not in sin_derechos.text
    assert TEXTO_DIVERGENCIA_B not in sin_derechos.text

    # (b) Lector que SI ve, mismo material, misma peticion.
    cookie = _cookie(auth_on, "m_lectora_ok", partida_id=PARTIDA_A)
    con_derechos = _ficha(real_app, cookie)
    assert con_derechos.status_code == 200
    assert TEXTO_LORE in con_derechos.text
    assert _hechos_en_pantalla(con_derechos.text), "el material NO esta vacio"


def test_control_negativo_la_partida_ajena_no_enmascara_a_nadie(
    real_app, con_proveedor, panel_on, auth_on
):
    """Una divergencia de B no puede retirar lore de la lectura de A.

    Es el cruce cross-partida del Invariante 2 leido desde el lado de la
    lectura: el enmascarado se indexa por la partida ACTIVA, y el de otra
    partida no participa.
    """
    con_proveedor()
    for usuario, partida, ve_lore in (
        ("m_x_a", PARTIDA_A, True),
        ("m_x_b", PARTIDA_B, False),
    ):
        r = _ficha(real_app, _cookie(auth_on, usuario, partida_id=partida))
        assert r.status_code == 200
        assert (ID_LORE in _hechos_en_pantalla(r.text)) is ve_lore


def test_el_acotado_a_la_partida_activa_es_OBSERVABLE_con_un_lector_que_ve_todo(
    real_app, con_proveedor, panel_on, auth_on
):
    """El enmascarado se indexa por la partida ACTIVA, y eso se puede ver ROJO.

    POR QUE ESTA PRUEBA EXISTE, dicho sin adornos: la mutacion que quitaba el
    acotado --enmascarar con la divergencia de CUALQUIER partida-- SOBREVIVIA
    a esta suite. No porque el acotado no estuviera, sino porque para un lector
    normal es INOBSERVABLE: la cascada ya retira el material de la otra partida
    antes de que el enmascarado llegue a verlo, asi que acotar o no acotar da
    el mismo resultado.

    Un lector `admin_full` si ve el material de las dos partidas, y sobre el la
    diferencia se mide: con el acotado puesto, un admin situado en la partida B
    pierde ID_LORE (divergido por B) y CONSERVA ID_LORE_2 (divergido por A, que
    no es su partida). Sin el acotado, perderia los dos.

    Queda dicho lo que esto NO significa: el acotado no es lo que impide el
    cruce cross-partida para un jugador --eso lo hace la cascada, y lo
    comprueba la prueba de arriba--. Es defensa en profundidad, y ahora es
    defensa en profundidad MEDIDA en vez de supuesta.
    """
    con_proveedor()
    r = _ficha(real_app, _cookie(auth_on, "m_admin_en_b",
                                 partida_id=PARTIDA_B, role="admin"))
    assert r.status_code == 200
    vistos = _hechos_en_pantalla(r.text)

    # Ve las dos partidas: es admin_full. Sin esto, lo de abajo no mide nada.
    assert ID_DIVERGENCIA_A in vistos and ID_DIVERGENCIA_B in vistos

    assert ID_LORE not in vistos, "su partida activa (B) diverge de ID_LORE"
    assert ID_LORE_2 in vistos, (
        "ID_LORE_2 lo diverge la partida A, que NO es la partida activa: "
        "una divergencia ajena no puede enmascarar"
    )


# ===========================================================================
# LA CASCADA DE AUTORIZACION SIGUE INTACTA
# ===========================================================================

def test_el_enmascarado_no_puede_hacer_visible_nada(
    real_app, con_proveedor, panel_on, auth_on
):
    """Un hecho SECRETO de capa juego no se vuelve visible por enmascarar.

    El enmascarado es una RESTA sobre un conjunto ya autorizado. Se ejecuta
    despues de la cascada entera y solo puede quitar elementos, nunca añadir:
    si alguna vez pudiera añadir, seria una via de autorizacion paralela.
    """
    secreto = _hecho("hecho-secreto", texto="secreto de trama", visibility="secret")
    con_proveedor(ProveedorFalso(HECHOS + (secreto,)))
    for usuario, partida in (("m_s_a", PARTIDA_A), ("m_s_b", PARTIDA_B)):
        r = _ficha(real_app, _cookie(auth_on, usuario, partida_id=partida))
        assert r.status_code == 200
        assert "hecho-secreto" not in _hechos_en_pantalla(r.text)
        assert "secreto de trama" not in r.text


def test_una_divergencia_que_el_lector_no_puede_ver_no_le_deja_un_hueco(
    real_app, con_proveedor, panel_on, auth_on
):
    """Decision explicita: solo enmascara una divergencia VISIBLE para el lector.

    Si el enmascarado mirase el puntero sin mirar la visibilidad, este lector
    se quedaria sin el lore Y sin la sustituta: un hueco que ademas delata por
    ausencia que ahi hay una divergencia que no le corresponde ver.
    """
    oculta = _hecho("hecho-B-secreta", texto="divergencia secreta de B",
                    partida_id=PARTIDA_B, local_override_of=ID_LORE,
                    visibility="secret", known_from_session=0)
    # Solo el lore y una divergencia que B no puede ver (es `secret`).
    con_proveedor(ProveedorFalso((HECHOS[0], oculta)))
    r = _ficha(real_app, _cookie(auth_on, "m_oculta_b", partida_id=PARTIDA_B))
    assert r.status_code == 200
    vistos = _hechos_en_pantalla(r.text)
    assert "hecho-B-secreta" not in vistos
    assert "divergencia secreta de B" not in r.text
    assert ID_LORE in vistos, "sin sustituta visible, se conserva el lore comun"


def test_la_barrera_de_partida_sigue_delante_del_conocimiento(
    real_app, con_proveedor, panel_on, auth_on
):
    """`known_by` NO salta la barrera de partida, tampoco en los hechos.

    La cascada real es: workspace -> PARTIDA -> lore anonimo -> known_by ->
    nivel -> sesion. Este caso la recorre por la pantalla: un hecho de la
    partida B que nombra al personaje del lector de A sigue sin salir.
    """
    ajeno = _hecho("hecho-B-conocido", texto="hecho de B con known_by de A",
                   partida_id=PARTIDA_B, known_from_session=0)
    ajeno["known_by"] = ["PJ-de-A"]
    con_proveedor(ProveedorFalso(HECHOS + (ajeno,)))
    r = _ficha(real_app, _cookie(auth_on, "m_known_a", partida_id=PARTIDA_A))
    assert r.status_code == 200
    assert "hecho-B-conocido" not in _hechos_en_pantalla(r.text)
    assert "hecho de B con known_by de A" not in r.text


# ===========================================================================
# TESTIGO DE SUPERFICIE — que esta prueba PIDE LA PANTALLA
# ===========================================================================

def test_testigo_de_superficie_la_ficha_renderiza_el_bloque_de_hechos(
    real_app, con_proveedor, panel_on, auth_on
):
    """Si alguien borra el bloque de hechos de la plantilla, esto se pone rojo.

    Es la red contra el falso verde concreto que ya ocurrio en esta sesion:
    una garantia visible cuyos casos probaban la propiedad y no renderizaban
    la pagina, de modo que borrar el bloque entero dejaba la suite igual de
    verde. Aqui se afirma sobre marcas que SOLO existen en el HTML de la ficha.
    """
    con_proveedor()
    r = _ficha(real_app, _cookie(auth_on, "m_superficie", partida_id=PARTIDA_B))
    assert r.status_code == 200
    assert 'data-role="hechos"' in r.text, "el bloque de hechos no se renderizo"
    assert "<h3>Hechos (" in r.text
    assert _hechos_en_pantalla(r.text), "el bloque existe pero no pinto hechos"


# ===========================================================================
# TRANSPORTE — el defecto H1, que ya ocurrio en este mismo fichero
# ===========================================================================
# Las pruebas de arriba usan un proveedor falso, asi que por si solas NO
# pueden ver si el proveedor de Neo4j deja de transportar `local_override_of`.
# Ese es exactamente el defecto H1 documentado en `policies/registry.py`: el
# serializador descartaba `partida_id`, la barrera no se evaluaba nunca sobre
# datos reales, y 675 pruebas seguian verdes. Una dimension no es un campo: es
# una cadena, y esto comprueba el eslabon de TRANSPORTE.

class _NodoFalsoNeo4j:
    """Imita lo unico que `_assertion_to_dict` usa de un nodo: `dict(nodo)`."""

    def __init__(self, props: dict):
        self._props = dict(props)

    def keys(self):
        return self._props.keys()

    def __getitem__(self, k):
        return self._props[k]


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("local_override_of", "hecho-lore-x"),
        ("partida_id", "partida-Z"),
        ("assertion_id", "hecho-1"),
        ("scope", "partida"),
        ("visibility", "player"),
        ("known_by", ["PJ01"]),
        ("status", "ASSERTED"),
    ],
)
def test_la_proyeccion_de_neo4j_transporta_el_campo(campo, valor):
    """Sin transporte, el enmascarado es decorativo EN SILENCIO."""
    from app.providers.neo4j_provider import _assertion_to_dict

    proyectado = _assertion_to_dict(_NodoFalsoNeo4j({campo: valor}))
    assert campo in proyectado, f"{campo} no viaja en la proyeccion de aserciones"
    assert proyectado[campo] == valor


def test_un_campo_ausente_llega_como_None_y_no_desaparece():
    """Ausente no es inexistente. La clave viaja SIEMPRE, con `None` dentro."""
    from app.providers.neo4j_provider import _assertion_to_dict

    proyectado = _assertion_to_dict(_NodoFalsoNeo4j({"assertion_id": "h1"}))
    assert "local_override_of" in proyectado
    assert proyectado["local_override_of"] is None
    assert "partida_id" in proyectado
    assert proyectado["partida_id"] is None


def _estados_vigentes_del_motor():
    """`LIVE_STATUSES` leido del FICHERO del motor, por AST.

    Se parsea en vez de importarse porque importar `knowledge_v3.engine`
    arrastra el paquete entero, y se lee del fichero en vez de con `grep`
    porque contar apariciones de texto da falsos negativos: lo que importa es
    el VALOR asignado, no que la cadena aparezca por algun sitio.
    """
    import ast

    ruta = (
        Path(__file__).resolve().parents[2]
        / "data-engine" / "app" / "knowledge_v3" / "engine" / "config.py"
    )
    if not ruta.exists():
        return None
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Assign):
            continue
        if "LIVE_STATUSES" not in [
            t.id for t in nodo.targets if isinstance(t, ast.Name)
        ]:
            continue
        valor = nodo.value
        if isinstance(valor, ast.Call) and valor.args:  # frozenset({...})
            valor = valor.args[0]
        return {ast.literal_eval(e) for e in getattr(valor, "elts", [])}
    return None


def test_el_aviso_de_alcance_del_enmascarado_esta_en_la_pantalla(
    real_app, con_proveedor, panel_on, auth_on
):
    """La ficha AVISA de que las relaciones no reflejan la divergencia local.

    Deuda §12.4 hecha visible. El enmascarado opera sobre aserciones y no
    sobre las aristas proyectadas (no llevan `assertion_id`), asi que la ficha
    puede enseñar en "Hechos" la version de la partida y en "Relaciones" la
    version de lore que esa divergencia sustituyo. Es incoherencia, no fuga.

    Mientras la deuda siga abierta, el producto lo DICE en la pantalla. Esta
    prueba pide la pagina: si alguien retira el aviso sin cerrar la deuda,
    enrojece.
    """
    con_proveedor()
    r = _ficha(real_app, _cookie(auth_on, "m_aviso_b", partida_id=PARTIDA_B))
    assert r.status_code == 200
    assert 'data-role="aviso-alcance-enmascarado"' in r.text
    assert "no reflejan las divergencias locales" in r.text

    # Y va DENTRO del bloque de relaciones, que es donde esta la incoherencia
    # que advierte. Un aviso al pie del documento no advierte de nada: el
    # lector ya paso de largo por las relaciones cuando llega a el.
    #
    # EL CORTE SE CIERRA POR `</section>`, y esto es una correccion medida, no
    # una precaucion: la version anterior partia por el marcador de APERTURA y
    # miraba todo el sufijo, asi que un revisor movio el aviso al pie del
    # documento --fuera del bloque-- y la prueba SIGUIO VERDE. Partir por un
    # delimitador de apertura sin cerrar por el de cierre no acota nada:
    # "despues de aqui" incluye el resto del fichero.
    tras_apertura = r.text.split('data-role="relaciones"', 1)[1]
    bloque = tras_apertura.split("</section>", 1)[0]
    assert 'data-role="aviso-alcance-enmascarado"' in bloque, (
        "el aviso existe pero NO esta dentro del bloque de relaciones: si cae "
        "mas abajo, el lector ya ha pasado por las relaciones sin verlo"
    )


def test_el_proveedor_crudo_de_neo4j_solo_es_alcanzable_por_el_filtrado(real_app):
    """INVARIANTE ESTRUCTURAL: nadie lee hechos sin pasar por la politica.

    POR QUE ESTO ES UNA BARRERA Y NO HIGIENE. `Neo4jGraphProvider.
    list_assertions` entrega a proposito material CANDIDATO de todas las
    partidas del workspace: el enmascarado necesita ver a la vez el hecho de
    capa juego y la divergencia que lo sustituye, asi que no puede acotar por
    partida en Cypher. La consecuencia es que **toda** la seguridad de esa
    lectura descansa en que su unico llamador sea `PolicyFilteredProvider`.

    Ese es justo el tipo de invariante que se rompe sin que nadie lo note: un
    router futuro que pida `Depends(get_provider)` en vez de
    `Depends(get_filtered_provider)` y llame a `list_assertions` entregaria
    material cross-partida en crudo, sin cascada y sin enmascarado, y ninguna
    prueba de comportamiento lo veria porque cada pieza por separado seguiria
    estando bien.

    Se comprueba por AST --no por `grep`--: lo que importa es una LLAMADA
    real, no que la cadena aparezca en un comentario o en un docstring.
    """
    import ast

    raiz = Path(__file__).resolve().parents[1] / "app"
    infractores: list[str] = []
    llamadas_totales = 0

    for ruta in raiz.rglob("*.py"):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))

        # --- Nombres que en ESTE modulo designan al proveedor SIN filtrar.
        # Se persigue el SIMBOLO IMPORTADO, con alias incluido, y no solo la
        # cadena "get_provider". La version anterior miraba el nombre tal cual,
        # y por eso este escape pasaba con rc=0 y las dos mitades en verde:
        #
        #     from app.deps import get_provider as _gp
        #     prov = _gp()
        #     prov.list_assertions(...)          # <- proveedor crudo, sin Depends
        #
        # Hoy no hay ningun sitio asi, pero `list_assertions` entrega material
        # cross-partida A PROPOSITO, asi que es justo el invariante que no
        # puede tener agujeros: lo que lo sostiene todo es que su unico
        # llamador sea el proveedor filtrado.
        crudos: set[str] = set()
        for n in ast.walk(arbol):
            if isinstance(n, ast.ImportFrom):
                for alias in n.names:
                    if alias.name == "get_provider":
                        crudos.add(alias.asname or alias.name)
            elif isinstance(n, ast.Import):
                for alias in n.names:
                    # `import app.deps as d` -> `d.get_provider(...)`
                    if alias.name.endswith("deps"):
                        crudos.add(alias.asname or alias.name.split(".")[0])

        # --- Variables ligadas al RESULTADO de llamar a cualquiera de esos
        # nombres: `prov = _gp()` hace de `prov` un proveedor crudo.
        for n in ast.walk(arbol):
            if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call):
                continue
            f = n.value.func
            nombre = getattr(f, "id", None) or getattr(f, "attr", None)
            if nombre in crudos or nombre == "get_provider":
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        crudos.add(t.id)

        for n in ast.walk(arbol):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "list_assertions":
                llamadas_totales += 1
                # `self._base.list_assertions(...)` dentro del provider
                # filtrado es EL llamador legitimo.
                if ruta.name == "filtered_provider.py":
                    continue
                receptor = n.func.value
                nombre = getattr(receptor, "id", None) or getattr(receptor, "attr", None)
                if nombre in crudos or nombre == "get_provider":
                    infractores.append(f"{ruta}:{n.lineno} ({nombre})")

    # Control positivo: si la sonda no encuentra NINGUNA llamada, no esta
    # midiendo nada y su cero seria inerte.
    assert llamadas_totales > 0, "la sonda no encontro ninguna llamada: no mide"
    assert not infractores, (
        "alguien lee hechos de un proveedor SIN filtrar: se salta la cascada "
        f"y el enmascarado -> {infractores}"
    )


def test_ningun_router_pide_el_proveedor_crudo_en_vez_del_filtrado():
    """La otra mitad del invariante anterior: la DEPENDENCIA de los routers.

    La prueba de arriba mira quien llama; esta mira quien se hace inyectar. Un
    router que declare `Depends(get_provider)` tiene en la mano el proveedor
    sin politica, y a partir de ahi cualquier lectura que añada mañana nace
    sin cascada. La linea se traza aqui, donde se puede ver roja.
    """
    import ast

    routers = Path(__file__).resolve().parents[1] / "app" / "routers"
    infractores: list[str] = []
    vistos = 0

    for ruta in routers.rglob("*.py"):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if not isinstance(n, ast.Call):
                continue
            if getattr(n.func, "id", None) != "Depends":
                continue
            vistos += 1
            for a in n.args[:1]:
                nombre = getattr(a, "id", None) or getattr(a, "attr", None)
                if nombre == "get_provider":
                    infractores.append(f"{ruta.name}:{n.lineno}")

    assert vistos > 0, "la sonda no encontro ningun Depends(): no mide"
    assert not infractores, (
        "un router se inyecta el proveedor SIN filtrar en vez del filtrado: "
        f"{infractores}"
    )


def test_mi_suite_de_neo4j_real_es_de_esa_familia_y_esta_invocada():
    """CONTROL POSITIVO de la guarda de cobertura, sobre el modulo de ESTE carril.

    La guarda `test_la_cobertura_neo4j_del_visor_se_invoca_entera_en_ci` compara
    DERIVADOS (por AST, los modulos que leen `NEO4J_TEST_URI`) contra INVOCADOS
    (por YAML, las rutas del paso de CI). Esa comparacion cierra una direccion:
    si alguien quita mi modulo de `ci.yml`, enrojece nombrandolo --medido--.

    Pero NO cierra la otra. Si mi modulo dejara de leer la variable --por
    ejemplo porque alguien fija la URI a pelo-- saldria del conjunto DERIVADO,
    la resta `derivados - invocados` seguiria vacia, la guarda pasaria en verde
    y la cobertura habria desaparecido igual. Un conjunto que se encoge no
    dispara una guarda que solo mira lo que sobra.

    Por eso este modulo, que se ejecuta SIEMPRE (no depende de que haya Neo4j),
    ancla su suite por NOMBRE en las dos vias. Es la misma red que el repo ya
    tiene para `test_resultado_procedencia_neo4j_real.py`, y existe para que la
    lista y el descubrimiento no puedan convertirse en dos verdades distintas.

    Se vive con la ironia a proposito: aqui SI hay un nombre escrito a mano,
    porque el punto es precisamente afirmar algo sobre ESTE modulo concreto.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_resultado_procedencia import (  # noqa: E402
        _modulos_del_visor_que_exigen_neo4j_de_prueba,
        _rutas_invocadas_en_el_paso_de_neo4j,
    )

    mio = "viewer/tests/test_multipartida_divergencia_local_neo4j.py"
    derivados = _modulos_del_visor_que_exigen_neo4j_de_prueba()
    invocados = _rutas_invocadas_en_el_paso_de_neo4j()

    assert mio in derivados, (
        f"{mio} ya no lee NEO4J_TEST_URI, asi que ha salido del conjunto que "
        "la guarda de cobertura deriva: la guarda seguira VERDE y su cobertura "
        "contra Neo4j real habra desaparecido sin que nadie lo vea"
    )
    assert mio in invocados, (
        f"{mio} no esta en el paso 'Run authz integration tests' de ci.yml: "
        "en `test-viewer` saldra SKIPPED con rc=0 y el job verde"
    )


def test_los_proveedores_reales_implementan_list_assertions():
    """Red contra la degradacion silenciosa del `getattr` del provider filtrado.

    `PolicyFilteredProvider` tolera un proveedor base sin `list_assertions` y
    devuelve lista vacia, porque varios dobles de prueba son duck-typed y sin
    esa tolerancia tumbaban pantallas ajenas con un 503. Pero esa tolerancia,
    aplicada a un proveedor de PRODUCCION, seria una pantalla de hechos vacia
    para siempre y sin un solo error: el enmascarado entero volveria a ser
    decorativo, que es el estado que este carril viene a cerrar.

    Asi que los proveedores reales tienen que implementarlo DE VERDAD, no
    heredar el defecto de la clase base.
    """
    import importlib
    import pkgutil

    from app.providers.base import GraphProvider

    # DESCUBIERTOS, no enumerados. Una lista blanca escrita a mano dejaria
    # pasar en silencio a un tercer proveedor de produccion el dia que exista
    # -- y "el dia que exista" es exactamente cuando nadie se acuerda de venir
    # a tocar esta prueba. Se importa el paquete entero y se pregunta por las
    # subclases concretas.
    import app.providers as paquete

    for info in pkgutil.iter_modules(paquete.__path__):
        importlib.import_module(f"app.providers.{info.name}")

    # Acotado a los proveedores de PRODUCCION, por su modulo de origen. El
    # criterio no es el nombre de la clase --que se puede elegir para esquivar
    # un filtro-- sino DONDE vive: `app.providers.*`. Hizo falta medirlo: la
    # primera version recorria `__subclasses__()` a secas y enrojecia por
    # `CountingProvider`, un doble de otra suite de pruebas que hereda de
    # `GraphProvider`. Un doble no tiene por que leer hechos, asi que exigirselo
    # habria sido un rojo por la causa equivocada -- y un rojo por la causa
    # equivocada se lee igual que uno legitimo.
    # `__subclasses__()` solo ve subclases DIRECTAS: un proveedor que heredara
    # de otro proveedor (o de una base intermedia) no aparecia, y se le habria
    # exigido nada en silencio. Se recorre el arbol entero.
    #
    # `PolicyFilteredProvider` NO necesita excluirse por nombre: vive en
    # `app.authz.filtered_provider`, asi que el acotado por modulo ya lo deja
    # fuera. La exclusion por nombre que habia era redundante, y una condicion
    # redundante en una red es peor que inutil -- invita a creer que ahi se
    # decide algo.
    def _descendientes(clase):
        for hija in clase.__subclasses__():
            yield hija
            yield from _descendientes(hija)

    concretos = [
        c for c in _descendientes(GraphProvider)
        if c.__module__.startswith("app.providers.")
    ]
    assert concretos, "la sonda no descubrio ningun proveedor: no mide"

    defecto = vars(GraphProvider)["list_assertions"]
    for clase in concretos:
        propio = getattr(clase, "list_assertions", None)
        assert propio is not None and propio is not defecto, (
            f"{clase.__name__} hereda el defecto vacio de GraphProvider: su "
            "pantalla de hechos estaria vacia en produccion sin dar ningun "
            "error, y el enmascarado volveria a ser decorativo"
        )


def test_los_estados_vigentes_del_visor_no_se_separan_de_los_del_motor():
    """`_ESTADOS_VIGENTES` es un espejo de `LIVE_STATUSES`. Si divergen, rojo.

    El visor no importa el paquete del motor en tiempo de ejecucion, asi que
    la lista esta escrita dos veces. Lo que impide que se separen es esta
    prueba, no un import: sin ella, añadir un estado vigente al motor dejaria
    al visor ocultando hechos que si estan vigentes, y en silencio.
    """
    from app.providers.neo4j_provider import _ESTADOS_VIGENTES

    motor = _estados_vigentes_del_motor()
    assert motor is not None, "no se pudo leer LIVE_STATUSES del motor"
    assert set(_ESTADOS_VIGENTES) == motor
