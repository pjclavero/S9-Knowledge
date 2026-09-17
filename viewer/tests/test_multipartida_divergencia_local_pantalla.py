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

ID_LORE = "hecho-lore-dios-sol"
ID_DIVERGENCIA_B = "hecho-partidaB-dios-sol"
ID_SOLO_B = "hecho-partidaB-templo"

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


#: El escenario del requisito, entero:
#:   lore comun  -> ID_LORE          (capa juego, sin partida)
#:   partida A   -> ninguna divergencia: debe seguir viendo el lore comun
#:   partida B   -> ID_DIVERGENCIA_B, que apunta a ID_LORE
HECHOS: tuple[dict, ...] = (
    _hecho(ID_LORE, texto=TEXTO_LORE),
    _hecho(ID_DIVERGENCIA_B, texto=TEXTO_DIVERGENCIA_B,
           partida_id=PARTIDA_B, local_override_of=ID_LORE, known_from_session=0),
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
    """A sigue viendo el lore comun, y NO la version de B."""
    con_proveedor()
    cookie = _cookie(auth_on, "m_lectora_a", partida_id=PARTIDA_A)
    r = _ficha(real_app, cookie)
    assert r.status_code == 200
    vistos = _hechos_en_pantalla(r.text)

    assert ID_LORE in vistos, "A debe seguir viendo el lore comun"
    assert TEXTO_LORE in r.text
    # Lo de B no se le cruza NI como hecho ni como texto.
    assert ID_DIVERGENCIA_B not in vistos
    assert TEXTO_DIVERGENCIA_B not in r.text
    assert ID_SOLO_B not in vistos
    assert TEXTO_SOLO_B not in r.text


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
