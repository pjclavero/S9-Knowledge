"""Hueco F del chasis — Panel de Fuentes, SOLO LECTURA.

REGLA DE ESTA SUITE, heredada de `test_chassis_mount_contract.py` y de la del
hueco C: todo lo que sea HTTP se prueba contra la aplicación REAL
(`app.main.app`). Aquí no se construye ningún `FastAPI()` de mentira salvo para
calibrar el instrumento (los dos controles de frontera de prefijo), y cuando se
hace se dice.

PUNTO DE INYECCIÓN — leer antes de tocar nada
---------------------------------------------
`get_visibility_context` se llama como FUNCIÓN NORMAL desde
`get_filtered_provider` (`app/authz/dependencies.py`), así que sobrescribirlo
con `dependency_overrides` es INERTE: sale verde sin morder. Hay un test que lo
DEMUESTRA (`test_sustituir_get_visibility_context_es_inerte`) en vez de
limitarse a advertirlo, porque una advertencia en un comentario no impide que
el siguiente carril la use.

Lo que sí entra por `Depends` en este router es `get_filtered_provider`, y es lo
que se sustituye, con control de colapso
(`test_la_sustitucion_del_proveedor_muerde`): sin la sustitución el resultado
tiene que CAMBIAR. Un arnés que no puede cambiar el resultado no prueba nada.

Y para las pruebas de AUTORIZACIÓN no se sustituye ninguna de las dos: se
sustituye el proveedor BASE (`app.deps.get_provider`), de modo que la política
real, con el contexto real que produce la petición real, es la que decide. Es la
única forma de que "con la autenticación desactivada no reaparece el
comportamiento permisivo" signifique algo.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.chassis import FEATURE_SLOTS, route_index, slot_flag_env
from app.deps import get_provider
from app.providers.base import GraphProvider
from app.routers import chassis_sources as panel

SLOT = next(s for s in FEATURE_SLOTS if s.key == "F")
FLAG = slot_flag_env(SLOT)
PASSWORD = "PanelFTest_1234567890!"
WORKSPACE = "leyenda"  # el `S9K_DEFAULT_WORKSPACE` del conftest del visor

#: Un identificador de fuente que ES una ruta del servidor. Es el caso que la
#: pantalla no puede publicar.
RUTA_SENSIBLE = "/srv/s9k/originales/2024/campaña-privada/manuscrito-secreto.pdf"
NOMBRE_SENSIBLE = "manuscrito-secreto.pdf"


# ---------------------------------------------------------------------------
# Material de prueba: nodos del grafo tal y como los lee la política
# ---------------------------------------------------------------------------

def nodo(
    node_id: str,
    *,
    source: Any = "Sesión 4 - transcripción",
    workspace: str = WORKSPACE,
    scope: str = "juego",
    partida: str | None = None,
    visibility: str = "player",
    review_status: Any = "needs_review",
    tipo: str = "Character",
    source_kind: str | None = None,
    known_from_session: int | None = None,
) -> dict[str, Any]:
    n: dict[str, Any] = {
        "id": node_id, "entity_id": node_id, "label": node_id.title(),
        "type": tipo, "workspace": workspace, "scope": scope,
        "visibility": visibility, "review_status": review_status,
    }
    if source is not None:
        n["source_document"] = source
    if partida is not None:
        n["partida_id"] = partida
    if source_kind is not None:
        n["source_kind"] = source_kind
    if known_from_session is not None:
        n["known_from_session"] = known_from_session
    return n


class BaseFalso(GraphProvider):
    """Proveedor base de mentira: devuelve nodos y REGISTRA qué se le pide.

    El registro no es decorativo: es el instrumento con el que se comprueba la
    frontera de solo lectura por el lado del backend. Un panel de fuentes que
    "sólo mira" pero llama a un método de reingesta seguiría pasando cualquier
    enumeración de métodos HTTP.
    """

    name = "falso"

    def __init__(self, nodos: list[dict[str, Any]]):
        self._nodos = list(nodos)
        self.llamadas: list[str] = []

    def _reg(self, metodo: str) -> None:
        self.llamadas.append(metodo)

    def is_connected(self) -> bool:
        self._reg("is_connected")
        return True

    def workspaces(self) -> list[str]:
        self._reg("workspaces")
        return sorted({n["workspace"] for n in self._nodos if n.get("workspace")})

    def counts(self, workspace: str | None = None):
        self._reg("counts")
        return (len(self._nodos), 0)

    def entity_types(self, workspace: str):
        self._reg("entity_types")
        return []

    def search(self, workspace: str, q: str, limit: int = 50):
        self._reg("search")
        return []

    def graph(self, workspace: str, limit: int = 300, entity_type=None, q=None):
        self._reg("graph")
        return ([n for n in self._nodos if n.get("workspace") == workspace], [])

    def entity(self, entity_id: str, *, workspaces=None):
        self._reg("entity")
        return None

    def relations_for_entity(self, entity_id: str):
        self._reg("relations_for_entity")
        return ([], [])

    def list_entities(self, workspace: str, **kwargs):
        self._reg("list_entities")
        items = [n for n in self._nodos if n.get("workspace") == workspace]
        return items, len(items)

    def list_sources(self, workspace: str):
        self._reg("list_sources")
        return []

    def source_detail(self, workspace: str, source_id: str):
        self._reg("source_detail")
        return None

    def quality_metrics(self, workspace: str | None = None):
        self._reg("quality_metrics")
        return {}


class BaseQueRevienta(BaseFalso):
    """Proveedor que falla con un mensaje que CONTIENE una ruta del servidor.

    Es el caso realista: `OSError`/`ServiceUnavailable` traen en `str(exc)` la
    ruta del fichero o el URI del servidor. Si la pantalla publicara `str(exc)`,
    publicaría eso.
    """

    def list_entities(self, workspace: str, **kwargs):
        self._reg("list_entities")
        raise RuntimeError(f"no se pudo abrir {RUTA_SENSIBLE} en bolt://10.9.0.5:7687")


# ---------------------------------------------------------------------------
# Fixtures — app REAL, interruptor REAL
# ---------------------------------------------------------------------------

@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _reset_auth_settings():
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    yield
    os.environ.pop("S9K_AUTH_ENABLED", None)
    os.environ.pop("S9K_AUTH_DB_PATH", None)
    get_auth_settings.cache_clear()


@pytest.fixture
def panel_on():
    """Enciende SOLO el hueco F. Los interruptores fallan cerrados."""
    previo = os.environ.get(FLAG)
    os.environ[FLAG] = "true"
    yield
    if previo is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = previo


@pytest.fixture
def con_base(real_app):
    """Sustituye el proveedor BASE. La política y el contexto siguen siendo los
    reales: es lo que hace que las pruebas de autorización midan algo.
    """
    def instalar(nodos: list[dict[str, Any]]) -> BaseFalso:
        base = BaseFalso(nodos)
        real_app.dependency_overrides[get_provider] = lambda: base
        return base

    yield instalar
    real_app.dependency_overrides.pop(get_provider, None)


@pytest.fixture
def con_base_rota(real_app):
    def instalar() -> BaseQueRevienta:
        # Con un nodo dentro: `workspaces()` tiene que devolver algo para que
        # se llegue a pedir el listado. Un proveedor vacío no llegaría a
        # reventar y el test saldría verde sin ejercitar el camino de error.
        base = BaseQueRevienta([nodo("a", source="x")])
        real_app.dependency_overrides[get_provider] = lambda: base
        return base

    yield instalar
    real_app.dependency_overrides.pop(get_provider, None)


@pytest.fixture
def auth_on(tmp_path):
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    return db_path


def login_cookie(db_path: Path, username: str, role: str) -> str:
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db_mod.get_conn(db_path) as conn:
        user = auth_db_mod.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role,
        )
        auth_db_mod.update_user(conn, user.id, must_change_password=False)
        user = auth_db_mod.get_user_by_id(conn, user.id)
        token, _ = create_session(conn, user)
    return token


def client(app, cookie: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        from app.auth.config import get_auth_settings
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


def _asas(html: str) -> list[str]:
    return re.findall(r'<tr data-source-handle="([^"]+)"', html)


def _etiquetas(html: str) -> list[str]:
    return re.findall(r'\?workspace=[^"]*">([^<]+)</a>', html)


# ===========================================================================
# 0. El arnés muerde. Sin esto, todo lo demás es adorno.
# ===========================================================================

def test_el_arnes_no_pasa_con_cero_casos(real_app, panel_on, con_base):
    """Un arnés que pasa con 0 casos está roto: aquí se exige material."""
    con_base([nodo("a", source="uno"), nodo("b", source="dos"), nodo("c", source="dos")])
    html = client(real_app).get(SLOT.prefix).text
    assert len(_asas(html)) == 2, html
    assert '<span data-count="entities">3</span>' in html


def test_la_sustitucion_del_proveedor_muerde(real_app, panel_on):
    """Con la sustitución la fuente aparece; SIN ella, NO.

    Éste es el control de colapso exigido: se sustituye `get_filtered_provider`,
    que es lo que este router recibe por `Depends`. Si quitar la sustitución no
    cambiara el resultado, el punto de inyección no estaría haciendo nada y
    ninguna prueba de ámbito de esta suite valdría.
    """
    from app.authz.dependencies import get_filtered_provider

    marca = "fuente-que-solo-existe-en-el-arnes"
    real_app.dependency_overrides[get_filtered_provider] = (
        lambda: BaseFalso([nodo("x", source=marca)])
    )
    try:
        con = client(real_app).get(SLOT.prefix).text
    finally:
        real_app.dependency_overrides.pop(get_filtered_provider, None)
    sin = client(real_app).get(SLOT.prefix).text

    assert marca in con
    assert marca not in sin, (
        "El proveedor sustituido no cambia el resultado: el arnés no muerde."
    )


def test_sustituir_get_visibility_context_es_inerte(real_app, panel_on, con_base):
    """CONTROL NEGATIVO CONOCIDO del punto de inyección congelado.

    `get_visibility_context` NO entra por `Depends` en el camino de este panel:
    `get_filtered_provider` lo llama como función normal. Sustituirlo sale
    VERDE sin morder, y por eso no se usa para nada en esta suite. Se demuestra
    aquí en vez de advertirlo en un comentario: si algún día pasara a entrar por
    `Depends`, este test se pone rojo y habrá que revisar qué más cambió.
    """
    from app.authz.context import build_viewer_context
    from app.authz.dependencies import get_visibility_context

    con_base([nodo("a", source="visible-igualmente")])
    antes = client(real_app).get(SLOT.prefix).text

    # Un contexto que, si mordiera, no dejaría ver NADA (workspace ajeno).
    real_app.dependency_overrides[get_visibility_context] = lambda: build_viewer_context(
        role=None, auth_enabled=True, default_workspace="workspace-inexistente",
    )
    try:
        despues = client(real_app).get(SLOT.prefix).text
    finally:
        real_app.dependency_overrides.pop(get_visibility_context, None)

    assert "visible-igualmente" in antes
    assert "visible-igualmente" in despues, (
        "Sustituir `get_visibility_context` ha mordido: ya no es un punto de "
        "inyección inerte y esta suite tiene que revisarse entera."
    )


# ===========================================================================
# 1. Montaje sobre el chasis: contrato publicado, no una ruta inventada
# ===========================================================================

def test_el_panel_se_monta_en_el_prefijo_del_contrato(real_app):
    index = route_index(real_app)
    assert index[SLOT.route_name] == "/panel/sources"
    assert index[panel.ITEM_ROUTE_NAME] == "/panel/sources/ficha/{handle}"


def test_la_ficha_no_es_una_entrada_de_menu():
    from app.chassis import NAV
    assert panel.ITEM_ROUTE_NAME not in {n.route_name for n in NAV}


def test_las_plantillas_no_llevan_urls_escritas_a_mano():
    """Fallo nº 2 del chasis: un enlace literal no avisa cuando la ruta cambia.

    Los comentarios Jinja se retiran antes de mirar: una ruta MENCIONADA en un
    comentario no crea ningún enlace, y contarla sería el falso positivo de
    "citar es afirmar" ya registrado en este repo.
    """
    base = Path(panel.__file__).resolve().parent.parent / "templates" / "chassis"
    for nombre in ("sources.html", "sources_ficha.html"):
        texto = (base / nombre).read_text(encoding="utf-8")
        marcado = re.sub(r"\{#.*?#\}", "", texto, flags=re.S)
        assert SLOT.prefix not in marcado, f"{nombre} escribe {SLOT.prefix!r} a mano"
        assert "/sources/" not in marcado, f"{nombre} enlaza el visor viejo a mano"
        assert "url_for(" in marcado


# ===========================================================================
# 2. Interruptor del hueco: apagado por defecto, y DESPUÉS de la guarda
# ===========================================================================

def test_sin_el_interruptor_el_panel_no_se_sirve(real_app, con_base):
    os.environ.pop(FLAG, None)
    con_base([nodo("a")])
    cliente = client(real_app)
    assert cliente.get(SLOT.prefix).status_code == 404
    assert cliente.get(f"{SLOT.prefix}/ficha/{panel.asa_de('x')}").status_code == 404


@pytest.mark.parametrize("valor", ["", "false", "0", "quizas", "TRUE ", "yes"])
def test_solo_true_y_1_encienden_el_panel(real_app, con_base, valor):
    """Un valor que no se entiende es un dato ausente, no un permiso."""
    con_base([nodo("a")])
    previo = os.environ.get(FLAG)
    os.environ[FLAG] = valor
    try:
        esperado = 200 if valor.strip().lower() in {"true", "1"} else 404
        assert client(real_app).get(SLOT.prefix).status_code == esperado
    finally:
        if previo is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previo


def test_un_anonimo_no_puede_enumerar_si_el_panel_esta_encendido(real_app, auth_on):
    """Con auth activa, el anónimo recibe LO MISMO esté encendido o apagado."""
    respuestas = []
    previo = os.environ.get(FLAG)
    try:
        for valor in ("true", "false"):
            os.environ[FLAG] = valor
            r = client(real_app).get(SLOT.prefix)
            respuestas.append((r.status_code, r.headers.get("location")))
    finally:
        if previo is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previo
    assert respuestas[0] == respuestas[1], (
        f"El anónimo distingue encendido de apagado: {respuestas}"
    )
    assert respuestas[0][0] == 302


# ===========================================================================
# 3. Autorización: la actual manda. Sin auth = anónimo SIN permisos.
# ===========================================================================

def test_con_auth_activa_el_anonimo_va_a_login(real_app, auth_on, panel_on, con_base):
    con_base([nodo("a")])
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 302 and "/login" in r.headers["location"]


def test_con_auth_activa_el_rol_inferior_al_publicado_no_entra(
    real_app, auth_on, panel_on, con_base
):
    """El rol del contrato es MÍNIMO: el inmediatamente inferior recibe 403."""
    inferior = {"admin": "reviewer", "reviewer": "viewer"}[SLOT.role]
    con_base([nodo("a")])
    cookie = login_cookie(auth_on, "panelf_inferior", inferior)
    assert client(real_app, cookie).get(SLOT.prefix).status_code == 403


def test_con_auth_activa_el_rol_publicado_entra(real_app, auth_on, panel_on, con_base):
    con_base([nodo("a")])
    cookie = login_cookie(auth_on, "panelf_declarado", SLOT.role)
    assert client(real_app, cookie).get(SLOT.prefix).status_code == 200


def test_sin_auth_no_reaparece_el_comportamiento_permisivo(
    real_app, panel_on, con_base
):
    """EL TEST DE ESTE CARRIL, dirección 1: sin principal no hay autoridad.

    Hubo un tiempo en que `S9K_AUTH_ENABLED=false` producía un contexto
    `admin_full`: sin auth se veía TODO. El P0 de autoridad (docs/75) lo cerró.
    Aquí se fija sobre el camino REAL (proveedor base sustituido, política y
    contexto de verdad): el material de partida no se entrega, ni en la lista,
    ni en los contadores, ni por su asa.

    Que el panel salga vacío en un banco sin auth es, por tanto, el
    comportamiento CORRECTO. No es una pantalla que arreglar.
    """
    con_base([
        nodo("secreto", source=RUTA_SENSIBLE, scope="partida",
             partida="partida-A", known_from_session=1),
        nodo("otro", source="otra-fuente-de-partida", scope="partida",
             partida="partida-B", known_from_session=1),
    ])
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 200
    assert 'data-state="empty"' in r.text
    assert NOMBRE_SENSIBLE not in r.text and "otra-fuente-de-partida" not in r.text
    assert '<span data-count="sources">0</span>' in r.text
    assert '<span data-count="entities">0</span>' in r.text
    # Tampoco por su asa: la barrera no depende de por dónde se entre.
    asa = panel.asa_de(RUTA_SENSIBLE)
    assert client(real_app).get(f"{SLOT.prefix}/ficha/{asa}").status_code == 404


def test_sin_auth_la_capa_juego_SI_es_visible_y_eso_tambien_es_la_politica(
    real_app, panel_on, con_base
):
    """EL TEST DE ESTE CARRIL, dirección 2. El matiz que se lee al revés.

    "Sin auth el panel sale vacío" es CONTINGENTE, no absoluto: depende de que
    el material tenga partida. La capa juego es lore compartido del workspace y
    SÍ se entrega. Sin este contrapeso, el test de al lado seguiría verde
    aunque el panel se hubiera roto y no mostrara nunca nada — que es la forma
    más fácil de "aprobar" una prueba de aislamiento.
    """
    con_base([
        nodo("de-partida", source="fuente-de-partida", scope="partida",
             partida="partida-A", known_from_session=1),
        nodo("lore", source="lore-compartido"),
    ])
    html = client(real_app).get(SLOT.prefix).text
    assert "lore-compartido" in html
    assert "fuente-de-partida" not in html
    assert '<span data-count="sources">1</span>' in html


def test_la_barrera_de_partida_es_real_no_un_panel_siempre_vacio(
    real_app, auth_on, panel_on, con_base
):
    """Contrapeso fuerte: alguien con autoridad SÍ ve el material de partida.

    Si nadie lo viera nunca, "el anónimo no lo ve" no diría nada sobre la
    autorización: diría que el panel no sabe pintar ese material. Con una
    sesión de administrador la misma fuente aparece, así que lo que separa los
    dos resultados es la autoridad y no un defecto de la pantalla.
    """
    con_base([
        nodo("secreto", source=RUTA_SENSIBLE, scope="partida",
             partida="partida-A", known_from_session=1),
    ])
    sin_partida = client(
        real_app, login_cookie(auth_on, "panelf_sin_partida", SLOT.role)
    ).get(SLOT.prefix)
    assert sin_partida.status_code == 200
    assert 'data-state="empty"' in sin_partida.text

    cookie = login_cookie(auth_on, "panelf_autoridad", "admin")
    con_autoridad = client(real_app, cookie).get(SLOT.prefix)
    assert con_autoridad.status_code == 200
    assert NOMBRE_SENSIBLE in con_autoridad.text, (
        "Ni con autoridad se ve la fuente: el panel no pinta ese material y el "
        "test de aislamiento de al lado no estaba midiendo la autorización."
    )


#: TABLA MEDIDA del anónimo con la autenticación desactivada. No es una cita de
#: la política: es lo que ESTE panel entrega, caso por caso, medido contra la
#: app real con el proveedor base sustituido. Coincide con la tabla que midió el
#: carril G sobre su propio hueco, y eso importa: dos huecos distintos sobre la
#: misma autorización tienen que dar el mismo veredicto, o uno de los dos está
#: aplicando una política suya.
#:
#: Si mañana aparece aquí un `True` nuevo, NO se "arregla" cambiando el panel:
#: se mide, se declara y se pregunta.
TABLA_ANONIMO_SIN_AUTH: tuple[tuple[str, dict[str, Any], bool], ...] = (
    ("capa juego, player", dict(scope="juego", visibility="player"), True),
    ("capa juego, reference", dict(scope="juego", visibility="reference"), False),
    ("capa juego, secret", dict(scope="juego", visibility="secret"), False),
    ("capa juego, narrator", dict(scope="juego", visibility="narrator"), False),
    ("capa juego, deny", dict(scope="juego", visibility="deny"), False),
    ("visibilidad invalida", dict(scope="juego", visibility="verde"), False),
    ("sin ambito declarado", dict(scope=None, visibility="player"), False),
    ("partida ajena", dict(scope="partida", partida="p-A",
                           known_from_session=1, visibility="player"), False),
    ("partida sin sesion de revelacion", dict(scope="partida", partida="p-A",
                                              visibility="player"), False),
    ("sesion futura", dict(scope="juego", visibility="player",
                           known_from_session=9), False),
    ("workspace ajeno", dict(scope="juego", visibility="player",
                             workspace="otro-workspace"), False),
)


@pytest.mark.parametrize(
    "nombre,atributos,visible", TABLA_ANONIMO_SIN_AUTH, ids=[c[0] for c in TABLA_ANONIMO_SIN_AUTH]
)
def test_tabla_medida_del_anonimo_con_auth_desactivada(
    real_app, panel_on, con_base, nombre, atributos, visible
):
    """Caso por caso, y con los dos veredictos representados.

    Una tabla de once "no visible" se satisfaría con un panel roto que no
    pintara nunca nada; una de once "visible", con un panel que no filtrara. La
    tabla trae los dos, y el test de abajo exige que la proporción sea la
    medida y no otra.
    """
    fuente = f"fuente-{nombre}"
    n = nodo("n1", source=fuente, **atributos)
    if atributos.get("scope") is None:
        n.pop("scope", None)
    con_base([n])
    html = client(real_app).get(SLOT.prefix).text
    assert (fuente in html) is visible, (
        f"{nombre}: el panel {'oculta' if visible else 'entrega'} este material "
        "con la autenticación desactivada, y la tabla medida dice lo contrario"
    )


def test_la_tabla_del_anonimo_no_es_unanime():
    """Suelo de la tabla: si todos los casos apuntaran al mismo lado, el
    parametrizado de arriba no distinguiría un panel correcto de uno roto."""
    veredictos = {c[2] for c in TABLA_ANONIMO_SIN_AUTH}
    assert veredictos == {True, False}
    visibles = [c[0] for c in TABLA_ANONIMO_SIN_AUTH if c[2]]
    assert visibles == ["capa juego, player"], visibles


def test_el_panel_no_declara_vocabulario_propio_de_autorizacion():
    """Ni una segunda tabla de rangos, ni un `admin_full` local, ni un `role ==`.

    Se comprueba sobre el AST, no leyendo el fichero: una mención en un
    comentario no cuenta ni a favor ni en contra.
    """
    import ast

    arbol = ast.parse(Path(panel.__file__).read_text(encoding="utf-8"))
    nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
    atributos = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
    constantes = {n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant)
                  if isinstance(n.value, str)}
    assert "admin_full" not in nombres | atributos | constantes
    assert "slot_guard" in nombres
    assert "get_filtered_provider" in nombres
    for rol in ("admin", "reviewer", "viewer", "anonymous"):
        assert rol not in constantes, f"El router compara el rol {rol!r} por su cuenta"


# ===========================================================================
# 4. SOLO LECTURA: frontera dura, comprobada por enumeración
# ===========================================================================

METODOS_DE_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}


def rutas_del_espacio_del_panel(app) -> list:
    """Todas las rutas de la APP bajo `/panel/sources`, a cualquier profundidad.

    Se recorre **la app**, no `panel.router.routes`: la frontera de solo lectura
    es del ESPACIO DE URL, no del módulo. Un `@app.post("/panel/sources/subir")`
    escrito desde `app/main.py` —o desde cualquier otro carril— cuelga escritura
    en este prefijo sin tocar este fichero, y una enumeración del propio router
    lo daría por bueno (medido en el hueco C: la suite entera salía verde
    mientras la ruta respondía 200 sin autenticar).

    Se usa `iter_mounted_routes` (aplana routers incluidos y compone el prefijo
    de cada `Mount`) y `route_in_prefix` (tri-estado del path y frontera de
    SEGMENTO). Ambos son del chasis: el mismo censo que usa el barrido de
    autorización, para que una ruta no pueda estar en un censo y faltar del otro.
    """
    from app.chassis import iter_mounted_routes, route_in_prefix

    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]


def test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia(real_app):
    """Suelo de plausibilidad: 0 rutas no es "no hay defecto", es "no he mirado".

    Sólo cuentan las rutas con path RESOLUBLE. `route_in_prefix` falla cerrado,
    así que una ristra de rutas con path indeterminable caería "dentro" del
    prefijo y satisfaría el suelo sin que el censo viese nada real: el suelo se
    estaría autocumpliendo con el propio fallo cerrado.
    """
    from app.chassis import effective_path

    rutas = rutas_del_espacio_del_panel(real_app)
    caminos = {getattr(r, "path", "") for r in rutas}
    resolubles = [r for r in rutas if effective_path(r) is not None]
    assert len(resolubles) >= 3, (
        f"La enumeración de {SLOT.prefix} sólo ve {len(resolubles)} rutas con "
        f"path resoluble ({caminos}): el barrido no está aplanando los routers "
        "incluidos"
    )
    # Los paths de ESTE carril, nombrados: el suelo no se satisface con
    # cualquier ruta que pase por ahí.
    assert SLOT.prefix in caminos
    assert f"{SLOT.prefix}/" in caminos
    assert f"{SLOT.prefix}/ficha/{{handle}}" in caminos


def test_el_gate_no_acusa_a_un_vecino_de_prefijo():
    """FALSO POSITIVO: la frontera es de SEGMENTO, no de texto.

    `POST /panel/sources-legacy/borrar` no está en el espacio de URL de este
    panel y el gate no puede reportarlo. Si el gate acusa a quien no es suyo,
    entrena a ignorarlo, y un rojo por el motivo equivocado es más peligroso
    que un verde. (App sintética: se calibra el INSTRUMENTO.)
    """
    from fastapi import FastAPI

    vecino = FastAPI()

    @vecino.post(f"{SLOT.prefix}-legacy/borrar")
    def _borrar():  # pragma: no cover - nunca se invoca
        return {"ok": True}

    @vecino.post(f"{SLOT.prefix}XYZ/borrar")
    def _borrar_xyz():  # pragma: no cover
        return {"ok": True}

    caminos = [getattr(r, "path", "") for r in rutas_del_espacio_del_panel(vecino)]
    assert caminos == [], (
        f"El gate reclama como suyas rutas que no están bajo {SLOT.prefix}: {caminos}"
    )


def test_el_gate_si_reclama_lo_que_es_suyo():
    """Contrapeso del anterior: la frontera de segmento no lo apaga.

    Sin este control, `path_in_prefix` podría devolver `False` siempre y el test
    del vecino seguiría verde mientras el gate dejaba de mirar.
    """
    from fastapi import FastAPI

    propio = FastAPI()

    @propio.post(f"{SLOT.prefix}/reingestar")
    def _reingestar():  # pragma: no cover
        return {"ok": True}

    caminos = [getattr(r, "path", "") for r in rutas_del_espacio_del_panel(propio)]
    assert caminos == [f"{SLOT.prefix}/reingestar"], caminos


def test_ninguna_ruta_del_espacio_del_panel_acepta_escritura(real_app):
    """LA frontera: nadie cuelga escritura bajo `/panel/sources`, venga de donde venga.

    La superficie de escritura se pregunta a `app.chassis.write_methods`, que
    FALLA CERRADO: una ruta sin `methods` enumerables (un WebSocket, un `Mount`
    opaco) se declara capaz de escribir en lugar de darse por buena.
    """
    from app.chassis import route_path, write_methods

    culpables = [
        (route_path(r), list(write_methods(r)))
        for r in rutas_del_espacio_del_panel(real_app)
        if write_methods(r)
    ]
    assert not culpables, (
        f"Hay escritura montada bajo {SLOT.prefix}: {culpables}. "
        "Este panel es de solo lectura y su espacio de URL también."
    )


def test_el_panel_no_monta_ningun_metodo_de_escritura(real_app):
    """El MÓDULO tampoco. Redundante por construcción con el anterior, y se
    conserva porque LOCALIZA el fallo: dice que el POST lo puso este fichero."""
    for ruta in panel.router.routes:
        assert not (set(getattr(ruta, "methods", set())) & METODOS_DE_ESCRITURA), (
            f"{getattr(ruta, 'path', ruta)} monta métodos de escritura"
        )


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_los_metodos_de_escritura_son_rechazados_por_http(
    # NO ES UNA GARANTÍA: sondea SÓLO el prefijo raíz. Un POST colgado en
    # cualquier subruta lo deja verde. Se conserva como redundancia inofensiva;
    # la defensa es la enumeración del espacio de URL.
    real_app, panel_on, con_base, metodo
):
    con_base([nodo("a")])
    r = getattr(client(real_app), metodo)(SLOT.prefix)
    assert r.status_code in (404, 405), f"{metodo.upper()} devolvió {r.status_code}"


def test_el_panel_solo_invoca_metodos_de_LECTURA_del_proveedor(
    real_app, panel_on, con_base
):
    """La otra mitad de la frontera: por debajo del HTTP tampoco se escribe.

    Un panel de fuentes es el sitio donde más tienta llamar a "reingestar esta
    fuente" desde un GET. Aquí se enumera qué se le pide de verdad al
    proveedor, y la lista permitida está escrita a mano: cualquier método nuevo
    —incluso de lectura— obliga a una decisión visible en este test.
    """
    LECTURA = {"workspaces", "list_entities"}
    base = con_base([nodo("a"), nodo("b", source=RUTA_SENSIBLE)])
    cliente = client(real_app)
    cliente.get(SLOT.prefix)
    cliente.get(f"{SLOT.prefix}/ficha/{panel.asa_de(RUTA_SENSIBLE)}")
    assert base.llamadas, "el arnés no registró ni una llamada: no mide nada"
    ajenas = sorted(set(base.llamadas) - LECTURA)
    assert not ajenas, f"El panel invocó métodos del proveedor fuera de {LECTURA}: {ajenas}"


# ===========================================================================
# 5. Contadores DESPUÉS de la autorización
# ===========================================================================

def test_los_contadores_no_incluyen_lo_que_el_espectador_no_ve(
    real_app, auth_on, panel_on, con_base
):
    """Un total que cuente lo invisible lo revela por diferencia.

    Misma fuente, dos entidades: una de capa juego y otra de una partida ajena.
    El lector sin partida activa tiene que ver `1`, no `2` — y no un `2` con
    una fila que sólo lista una.
    """
    con_base([
        nodo("visible", source="fuente-mixta"),
        nodo("ajena", source="fuente-mixta", scope="partida",
             partida="partida-ajena", known_from_session=1),
    ])
    cookie = login_cookie(auth_on, "panelf_contadores", SLOT.role)
    html = client(real_app, cookie).get(SLOT.prefix).text
    assert '<span data-count="entities">1</span>' in html
    assert '<span data-count="entities">2</span>' not in html


def test_la_ficha_tampoco_cuenta_lo_invisible(real_app, auth_on, panel_on, con_base):
    con_base([
        nodo("visible", source="fuente-mixta"),
        nodo("ajena", source="fuente-mixta", scope="partida",
             partida="partida-ajena", known_from_session=1),
    ])
    cookie = login_cookie(auth_on, "panelf_ficha_contadores", SLOT.role)
    html = client(real_app, cookie).get(
        f"{SLOT.prefix}/ficha/{panel.asa_de('fuente-mixta')}").text
    assert '<span data-count="entities">1</span>' in html


def test_la_pantalla_declara_que_los_recuentos_son_de_lo_visible(
    real_app, panel_on, con_base
):
    """Ausencia ≠ cero, y un recuento parcial sin decirlo es una afirmación
    falsa de producto (docs/73). La pantalla dice de qué son sus números."""
    con_base([nodo("a")])
    html = client(real_app).get(SLOT.prefix).text
    assert 'data-scope="visible"' in html
    assert 'data-role="alcance"' in html


# ===========================================================================
# 6. Rutas y nombres de fichero: dato sensible que no sale del servidor
# ===========================================================================

def test_la_ruta_de_origen_no_aparece_nunca_en_el_html(real_app, panel_on, con_base):
    con_base([nodo("a", source=RUTA_SENSIBLE)])
    cliente = client(real_app)
    listado = cliente.get(SLOT.prefix)
    ficha = cliente.get(f"{SLOT.prefix}/ficha/{panel.asa_de(RUTA_SENSIBLE)}")
    for r in (listado, ficha):
        assert r.status_code == 200
        assert RUTA_SENSIBLE not in r.text
        assert "/srv/" not in r.text
        assert "campaña-privada" not in r.text
        # Y lo que SÍ se publica es el nombre, no un hueco: sin esto, "no
        # aparece la ruta" se cumpliría con una pantalla en blanco.
        assert NOMBRE_SENSIBLE in r.text
        assert 'data-path-redacted="true"' in r.text


def test_la_url_de_la_ficha_no_lleva_la_ruta(real_app, panel_on, con_base):
    """El asa es opaca: la ruta no viaja en la URL, ni al historial, ni a los
    logs de acceso de un proxy."""
    con_base([nodo("a", source=RUTA_SENSIBLE)])
    html = client(real_app).get(SLOT.prefix).text
    asas = _asas(html)
    assert asas == [panel.asa_de(RUTA_SENSIBLE)]
    assert all(RUTA_SENSIBLE not in a and NOMBRE_SENSIBLE not in a for a in asas)
    assert re.fullmatch(r"[0-9a-f]{16}", asas[0])


def test_una_fuente_sin_ruta_no_se_marca_como_redactada(real_app, panel_on, con_base):
    """Falso positivo del marcador: un nombre suelto no lleva ruta que ocultar.

    Sin esto, marcar SIEMPRE "ruta oculta" pasaría el test de arriba mientras el
    aviso pierde todo significado.
    """
    con_base([nodo("a", source="Sesión 4 - transcripción")])
    html = client(real_app).get(SLOT.prefix).text
    assert 'data-path-redacted="false"' in html
    assert "Sesión 4 - transcripción" in html


@pytest.mark.parametrize("crudo,esperado", [
    ("/srv/datos/a.pdf", "a.pdf"),
    ("C:\\Usuarios\\gm\\secreto.docx", "secreto.docx"),
    ("relativo/con/dirs/x.md", "x.md"),
    ("sin-directorios.txt", "sin-directorios.txt"),
])
def test_la_etiqueta_es_el_ultimo_segmento_con_los_dos_separadores(crudo, esperado):
    """Ablación directa sobre la unidad, con `\\` incluido: un identificador
    escrito en una máquina Windows no se escapa de la redacción por usar el
    otro separador."""
    etiqueta, recortado = panel.etiqueta_de(crudo)
    assert etiqueta == esperado
    assert recortado == (crudo != esperado)


def test_un_identificador_que_es_solo_directorio_no_se_pinta_entero():
    """Degradado NO permisivo: si tras recortar no queda nombre, no se cae
    hacia atrás publicando la ruta entera."""
    etiqueta, recortado = panel.etiqueta_de("/srv/s9k/originales/")
    assert "/srv" not in etiqueta
    assert recortado is True


def test_el_asa_no_es_reversible_ni_contiene_el_identificador():
    asa = panel.asa_de(RUTA_SENSIBLE)
    assert RUTA_SENSIBLE not in asa and NOMBRE_SENSIBLE not in asa
    assert asa == panel.asa_de(RUTA_SENSIBLE), "el asa no es estable"
    assert asa != panel.asa_de(RUTA_SENSIBLE + "x")


def test_la_fila_publicada_no_contiene_el_identificador_crudo():
    """Más fuerte que "la plantilla no lo imprime": no lo tiene.

    La plantilla no puede filtrar por descuido un dato que no está en su
    contexto. Se comprueba sobre el agregado, que es donde se decide.
    """
    filas = panel.agregar_fuentes([nodo("a", source=RUTA_SENSIBLE)])
    plano = repr(filas)
    assert RUTA_SENSIBLE not in plano
    assert "/srv/" not in plano


# ===========================================================================
# 7. Ausencia ≠ cero
# ===========================================================================

def test_las_entidades_sin_fuente_se_declaran_no_se_pierden(real_app, panel_on, con_base):
    """Descartarlas en silencio haría que la suma de las filas no cuadrase con
    la realidad y nadie se enteraría."""
    con_base([nodo("a", source="con-nombre"), nodo("b", source=None)])
    html = client(real_app).get(SLOT.prefix).text
    assert "sin fuente declarada" in html
    assert 'data-source-declared="false"' in html
    assert '<span data-count="sources">2</span>' in html
    assert '<span data-count="entities">2</span>' in html


def test_un_identificador_de_fuente_que_no_es_texto_va_al_cubo_de_ausencia():
    """Un `source_document` numérico o una lista no son un identificador
    legible: tratarlos como tal inventaría una fuente."""
    filas = panel.agregar_fuentes([
        nodo("a", source=1234), nodo("b", source=["x"]), nodo("c", source="  "),
    ])
    assert len(filas) == 1
    assert filas[0]["sin_fuente"] is True
    assert filas[0]["entity_count"] == 3


def test_una_procedencia_ausente_se_dice_no_se_inventa(real_app, panel_on, con_base):
    con_base([nodo("a", source="x", source_kind=None)])
    html = client(real_app).get(SLOT.prefix).text
    assert panel.NO_DISPONIBLE in html


def test_una_procedencia_presente_si_se_muestra(real_app, panel_on, con_base):
    """Contrapeso: sin esto, escribir "no disponible" siempre pasaría el test
    de arriba."""
    con_base([nodo("a", source="x", source_kind="manuscrito")])
    html = client(real_app).get(SLOT.prefix).text
    assert "manuscrito" in html


def test_un_estado_de_revision_ausente_no_se_funde_con_otro(real_app, panel_on, con_base):
    con_base([nodo("a", source="x", review_status=None),
              nodo("b", source="x", review_status="reviewed")])
    html = client(real_app).get(SLOT.prefix).text
    assert "no declarado (1)" in html
    assert "Revisado (1)" in html


# ===========================================================================
# 8. Estados desconocidos: FALLO CERRADO
# ===========================================================================

def test_un_estado_desconocido_no_se_declara_conocido():
    filas = panel.agregar_fuentes([nodo("a", source="x", review_status="aprobada_por_la_casa")])
    estado = filas[0]["estados"][0]
    assert estado["conocido"] is False
    assert "no reconocido" in estado["etiqueta"]


def test_los_estados_canonicos_si_se_reconocen():
    """Contrapeso: si `conocido` fuera siempre False, el test de arriba pasaría
    y el marcador no significaría nada."""
    from app import review_status_contract

    for valor in sorted(review_status_contract.CANONICAL_VALUES):
        filas = panel.agregar_fuentes([nodo("a", source="x", review_status=valor)])
        assert filas[0]["estados"][0]["conocido"] is True, valor


def test_un_estado_desconocido_se_marca_en_la_pantalla(real_app, panel_on, con_base):
    """No se pinta con el aspecto de un estado bueno, ni agregado como si lo
    fuera: la pantalla lo dice."""
    con_base([nodo("a", source="x", review_status="aprobada_por_la_casa")])
    html = client(real_app).get(SLOT.prefix).text
    assert 'data-status-known="false"' in html
    assert "no reconocido (aprobada_por_la_casa)" in html


# ===========================================================================
# 9. Recurso no autorizado indistinguible de inexistente
# ===========================================================================

def test_asa_inexistente_y_fuera_de_ambito_dan_el_mismo_404(
    real_app, auth_on, panel_on, con_base
):
    """Mismo código y mismo cuerpo: la pantalla no dice "existe pero no es tuya"."""
    con_base([
        nodo("mio", source="fuente-propia"),
        nodo("ajeno", source=RUTA_SENSIBLE, scope="partida",
             partida="partida-ajena", known_from_session=1),
    ])
    cookie = login_cookie(auth_on, "panelf_404", SLOT.role)
    cliente = client(real_app, cookie)
    fuera = cliente.get(f"{SLOT.prefix}/ficha/{panel.asa_de(RUTA_SENSIBLE)}")
    inexistente = cliente.get(f"{SLOT.prefix}/ficha/{'0' * 16}")
    assert fuera.status_code == inexistente.status_code == 404
    assert fuera.text == inexistente.text
    # Y el que SÍ es suyo responde: si todo diera 404 esto no probaría nada.
    assert cliente.get(f"{SLOT.prefix}/ficha/{panel.asa_de('fuente-propia')}").status_code == 200


def test_un_workspace_fuera_de_ambito_es_404_como_uno_inexistente(
    real_app, panel_on, con_base
):
    con_base([nodo("a", source="x")])
    cliente = client(real_app)
    a = cliente.get(SLOT.prefix, params={"workspace": "otro-workspace"})
    b = cliente.get(SLOT.prefix, params={"workspace": "no-existe-jamas"})
    assert a.status_code == b.status_code == 404
    assert a.text == b.text


# ===========================================================================
# 10. Errores sin fuga
# ===========================================================================

def test_un_fallo_del_proveedor_da_503_sin_filtrar_rutas(
    real_app, panel_on, con_base_rota
):
    con_base_rota()
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 503
    assert 'data-state="error"' in r.text
    assert RUTA_SENSIBLE not in r.text
    assert "/srv/" not in r.text
    assert "bolt://" not in r.text
    assert "Traceback" not in r.text
    # Lo que sí se publica: el NOMBRE del tipo, que orienta sin filtrar nada.
    assert "RuntimeError" in r.text


def test_un_fallo_del_proveedor_en_la_ficha_tampoco_filtra(
    real_app, panel_on, con_base_rota
):
    con_base_rota()
    r = client(real_app).get(f"{SLOT.prefix}/ficha/{panel.asa_de('x')}")
    assert r.status_code == 503
    assert RUTA_SENSIBLE not in r.text and "bolt://" not in r.text


# ===========================================================================
# 11. Estado vacío: es el camino por defecto, no el olvidado
# ===========================================================================

def test_sin_material_se_pinta_el_estado_vacio_no_una_excepcion(
    real_app, panel_on, con_base
):
    con_base([])
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 200
    assert 'data-state="empty"' in r.text
    assert 'data-state="error"' not in r.text


def test_con_material_se_pinta_el_estado_listo(real_app, panel_on, con_base):
    """Contrapeso del vacío: una pantalla que sale siempre vacía también pasaría
    el test de arriba."""
    con_base([nodo("a", source="x")])
    r = client(real_app).get(SLOT.prefix)
    assert 'data-state="ready"' in r.text
    assert 'data-state="empty"' not in r.text
