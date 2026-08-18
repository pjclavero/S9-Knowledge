"""Hueco G del chasis — Panel de Entidades, SOLO LECTURA.

REGLA DE ESTA SUITE, heredada de `test_chassis_mount_contract.py` y de la del
hueco C: todo lo que sea HTTP se prueba contra la aplicación REAL
(`app.main.app`). Aquí no se construye ningún `FastAPI()` de mentira, salvo en
las dos calibraciones del propio gate de prefijo, donde el objeto medido ES el
censo y no el montaje.

PUNTO DE INYECCIÓN — esto es lo que hace que estas medidas signifiquen algo
-------------------------------------------------------------------------
`get_visibility_context` se llama como FUNCIÓN NORMAL desde
`get_filtered_provider` (`app/authz/dependencies.py`), así que sustituirlo con
`dependency_overrides` es INERTE: saldría verde sin morder. Ese punto está
CONGELADO y esta suite no lo toca.

Lo que se sustituye es el proveedor BASE (`app.deps.get_provider`), de modo que
la cadena de autorización real —`get_filtered_provider` →
`get_visibility_context` → `build_viewer_context` → `PolicyFilteredProvider` →
`VisibilityPolicy`— se atraviesa ENTERA en cada petición. Ninguna regla de
visibilidad se simula. Y que el control puede COLAPSAR se exige con un test
(`test_el_control_de_autorizacion_COLAPSA`): si cambiar el principal no cambiara
el resultado, todo lo demás sería adorno.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chassis import FEATURE_SLOTS, route_index, slot_flag_env
from app.routers import chassis_entities as panel

SLOT = next(s for s in FEATURE_SLOTS if s.key == "G")
FLAG = slot_flag_env(SLOT)
WS = "alpha"
WS_AJENO = "beta"
PASSWORD = "PanelGTest_1234567890!"

#: Texto completo que sólo aparece en la ficha del lore de capa juego. Sirve
#: para afirmar que la ficha entrega el CONTENIDO, no sólo un 200.
TEXTO_LORE = "La ciudad de Bruma resiste el invierno de sangre"


# ===========================================================================
# Material: la matriz de la política, un nodo por barrera
# ===========================================================================

def nodo(
    id_: str,
    *,
    workspace: str = WS,
    scope: str | None = "juego",
    visibility: str | None = "player",
    partida_id: str | None = None,
    known_from_session=None,
    known_by=None,
    tipo: str = "PERSONAJE",
    review_status: str = "reviewed",
    confidence: float | None = 0.9,
    description: str = "",
) -> dict:
    n = {
        "id": id_,
        "entity_id": id_,
        "label": id_,
        "type": tipo,
        "description": description,
        "workspace": workspace,
        "review_status": review_status,
        "confidence": confidence,
        "source_document": "manual.pdf",
        "canonical_name": id_,
    }
    if scope is not None:
        n["scope"] = scope
    if visibility is not None:
        n["visibility"] = visibility
    if partida_id is not None:
        n["partida_id"] = partida_id
    if known_from_session is not None:
        n["known_from_session"] = known_from_session
    if known_by is not None:
        n["known_by"] = known_by
    return n


#: Un nodo por celda de la tabla de `docs/77 §3`. El nombre dice la barrera.
MATRIZ: tuple[dict, ...] = (
    nodo("lore-player", description=TEXTO_LORE),
    nodo("lore-secreto", visibility="secret"),
    nodo("lore-narrador", visibility="narrator"),
    nodo("lore-referencia", visibility="reference"),
    nodo("lore-futuro", known_from_session=3),
    nodo("partida-A", scope="partida", partida_id="partida-A", known_from_session=1),
    nodo("workspace-ajeno", workspace=WS_AJENO),
    nodo("sin-scope", scope=None),
    nodo("visibilidad-rara", visibility="publico"),
    nodo("visibilidad-deny", visibility="deny"),
    nodo("known-by-malformado", known_by="PJ01"),
)

ARISTAS: tuple[dict, ...] = (
    {"id": "r1", "from": "lore-player", "to": "lore-secreto", "type": "CONOCE",
     "workspace": WS, "scope": "juego", "visibility": "player"},
    {"id": "r2", "from": "lore-player", "to": "partida-A", "type": "APARECE_EN",
     "workspace": WS, "scope": "juego", "visibility": "player"},
)

#: Lo que el panel DEBE mostrar a un anónimo con auth desactivada. Escrito a
#: mano, no derivado del motor: si se derivara del propio sistema que se está
#: midiendo, el test no podría discrepar con él nunca.
#:
#: LORE-ANÓNIMO-DENEGADO (decisión del operador, V3 RC, 2026-08-14). Aquí ponía
#: `{"lore-player"}`: el lore de capa juego con visibilidad `player` SÍ se
#: entregaba a un contexto anónimo, y lo único que se lo concedía era NO TENER
#: PARTIDA. La decisión cierra esa vía —una ausencia no puede conceder— así que
#: el conjunto es VACÍO y la tabla de abajo pasa de 1 de 11 a 0 de 11.
VISIBLES_PARA_ANONIMO: set[str] = set()

#: Lo que un LECTOR LEGÍTIMO (viewer autenticado, partida `partida-A` activa,
#: tope de sesión 5) sí ve de la misma matriz. Es la otra mitad de la tabla, y
#: no es decorativa: sin ella, "0 de 11" sería indistinguible de un panel roto
#: que no pinta nada, que es la forma más fácil de aprobar una prueba de
#: aislamiento. Cuatro de once, y cada uno por una barrera distinta:
#:   lore-player     -> capa juego, la llave `can_view_lore` que el anónimo NO tiene
#:   lore-referencia -> nivel `reference`, llave `can_view_reference`
#:   lore-futuro     -> capa juego con revelación 3, bajo un tope de 5
#:   partida-A       -> su propia partida
VISIBLES_PARA_LECTOR_LEGITIMO = {
    "lore-player", "lore-referencia", "lore-futuro", "partida-A",
}


class ProveedorFalso:
    """Proveedor BASE de mentira: entrega el material CRUDO, sin filtrar nada.

    Es deliberadamente tonto. Toda la autorización la pone
    `PolicyFilteredProvider` encima, que es el código real que se quiere medir:
    si este objeto filtrase algo, estaría midiendo su propio filtro.

    Registra cada método invocado en `llamadas` para poder afirmar que el panel
    sólo hace lecturas.
    """

    name = "falso"

    def __init__(self, nodos=MATRIZ, aristas=ARISTAS):
        self.nodos = list(nodos)
        self.aristas = list(aristas)
        self.llamadas: list[str] = []

    def _apunta(self, metodo: str) -> None:
        self.llamadas.append(metodo)

    def is_connected(self):
        self._apunta("is_connected")
        return True

    def workspaces(self):
        self._apunta("workspaces")
        return sorted({n["workspace"] for n in self.nodos})

    def counts(self, workspace=None):
        self._apunta("counts")
        return len(self.nodos), len(self.aristas)

    def entity_types(self, workspace):
        self._apunta("entity_types")
        tipos: dict[str, int] = {}
        for n in self.nodos:
            if n.get("workspace") == workspace:
                tipos[n["type"]] = tipos.get(n["type"], 0) + 1
        return [{"entity_type": t, "count": c} for t, c in sorted(tipos.items())]

    def search(self, workspace, q, limit=50):
        self._apunta("search")
        return [n for n in self.nodos if q.lower() in n["label"].lower()][:limit]

    def graph(self, workspace, limit=300, entity_type=None, q=None):
        self._apunta("graph")
        nodos = [n for n in self.nodos if n.get("workspace") == workspace][:limit]
        return nodos, list(self.aristas)

    def entity(self, entity_id, *, workspaces=None):
        self._apunta("entity")
        for n in self.nodos:
            if n["id"] == entity_id:
                if workspaces is not None and n.get("workspace") not in workspaces:
                    return None
                return n
        return None

    def relations_for_entity(self, entity_id, **kw):
        self._apunta("relations_for_entity")
        return (
            [e for e in self.aristas if e["from"] == entity_id],
            [e for e in self.aristas if e["to"] == entity_id],
        )

    def list_entities(self, workspace, *, q="", entity_type=None, source_kind=None,
                      review_status=None, visibility=None, quality_status=None,
                      min_confidence=None, sort="canonical_name", order="asc",
                      limit=50, offset=0):
        self._apunta("list_entities")
        items = [n for n in self.nodos if n.get("workspace") == workspace]
        if q:
            items = [n for n in items if q.lower() in n["label"].lower()]
        if entity_type:
            items = [n for n in items if n.get("type") == entity_type]
        if review_status:
            items = [n for n in items if n.get("review_status") == review_status]
        if min_confidence is not None:
            items = [n for n in items if (n.get("confidence") or 0) >= min_confidence]
        items.sort(key=lambda n: str(n.get("canonical_name", "")), reverse=(order == "desc"))
        return items[offset:offset + limit], len(items)

    def list_sources(self, workspace):
        self._apunta("list_sources")
        return []

    def source_detail(self, workspace, source_id):
        self._apunta("source_detail")
        return None

    def quality_metrics(self, workspace=None):
        self._apunta("quality_metrics")
        return {}

    def escribir(self):
        """Método de ESCRITURA que la interfaz `GraphProvider` NO declara.

        Existe sólo aquí y sólo para que la calibración pueda inyectar el
        defecto (caso G13): sin algo que el espía pueda cazar,
        `test_recorrer_el_panel_solo_invoca_lecturas_del_proveedor` sería una
        comprobación incapaz de ponerse roja. El panel no lo invoca — eso es
        justo lo que esa prueba afirma.
        """
        self._apunta("escribir")


class ProveedorQueRevienta(ProveedorFalso):
    """Proveedor caído. El mensaje trae una RUTA a propósito: no puede salir."""

    RUTA_SECRETA = "/srv/s9k/neo4j/bolt://usuario:clave@10.0.0.5:7687"

    def list_entities(self, *a, **kw):
        raise RuntimeError(f"no se pudo abrir {self.RUTA_SECRETA}")

    def entity(self, *a, **kw):
        raise RuntimeError(f"no se pudo abrir {self.RUTA_SECRETA}")


# ===========================================================================
# Fixtures — app REAL, cadena de autorización REAL
# ===========================================================================

@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _entorno_limpio():
    """Workspace por defecto fijado y cachés de settings limpias a ida y vuelta."""
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    previos = {k: os.environ.get(k) for k in
               ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE")}
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
    """Sustituye el proveedor BASE. La política real corre encima, entera."""
    import app.deps as deps

    instalado: list[ProveedorFalso] = []

    def instalar(proveedor=None):
        proveedor = proveedor or ProveedorFalso()
        real_app.dependency_overrides[deps.get_provider] = lambda: proveedor
        instalado.append(proveedor)
        return proveedor

    yield instalar
    real_app.dependency_overrides.pop(deps.get_provider, None)


@pytest.fixture
def panel_on():
    """Enciende SOLO el hueco G. Los interruptores fallan cerrados."""
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


def ids_de_la_lista(html: str) -> list[str]:
    return re.findall(r'data-entity-id="([^"]+)"', html)


# ===========================================================================
# 0. El arnés muerde. Sin esto, todo lo demás es adorno.
# ===========================================================================

def test_el_arnes_no_pasa_con_cero_casos(real_app, auth_on, panel_on, con_proveedor):
    """Un arnés que pasa con 0 casos está roto: aquí se exige material.

    Se comprueba en las dos capas: el material existe en el proveedor BASE (11
    nodos, uno por barrera) y la pantalla llega a renderizar filas.

    LORE-ANÓNIMO-DENEGADO: quien pide ahora es un LECTOR LEGÍTIMO, no el
    anónimo. Con la vía cerrada un anónimo no pinta ninguna fila, y este test
    —que existe precisamente para que el arnés no se apruebe a sí mismo con
    cero casos— se habría convertido en el ejemplo de lo que denuncia.
    """
    proveedor = con_proveedor()
    assert len(proveedor.nodos) == 11, "la matriz de la política perdió casos"
    assert len({n["id"] for n in proveedor.nodos}) == 11, "hay ids repetidos"
    r = client(real_app, _cookie_de_lector_legitimo(auth_on)).get(SLOT.prefix)
    assert r.status_code == 200
    assert ids_de_la_lista(r.text), "la pantalla no pintó ni una fila: el arnés no mide nada"


def test_el_control_de_autorizacion_COLAPSA(real_app, panel_on, con_proveedor, auth_on):
    """CONTROL DE COLAPSO. Va primero a propósito.

    Si cambiar el principal no cambiara lo que el panel entrega, la cadena de
    autorización estaría inerte y todas las comprobaciones negativas de abajo
    pasarían sin demostrar nada — el modo de fallo silencioso clásico.

    Se exige que un `admin` (que sí tiene `admin_full`) vea lo que un `viewer`
    no ve, POR HTTP y sobre la app real.
    """
    con_proveedor()
    vista_admin = ids_de_la_lista(
        client(real_app, login_cookie(auth_on, "g_admin", "admin")).get(SLOT.prefix).text
    )
    vista_viewer = ids_de_la_lista(
        client(real_app, login_cookie(auth_on, "g_viewer", "viewer")).get(SLOT.prefix).text
    )
    assert "lore-secreto" in vista_admin, (
        "el admin no recibe la potestad total: el instrumento no puede colapsar"
    )
    assert set(vista_viewer) < set(vista_admin), (
        f"cambiar el principal no cambia el resultado: admin={vista_admin} "
        f"viewer={vista_viewer}"
    )


# ===========================================================================
# 1. Montaje sobre el chasis: contrato publicado, no una ruta inventada
# ===========================================================================

def test_el_panel_se_monta_en_el_prefijo_del_contrato(real_app):
    index = route_index(real_app)
    assert index[SLOT.route_name] == "/panel/entities"
    assert index[panel.ITEM_ROUTE_NAME] == "/panel/entities/item/{entity_id}"


def test_la_ficha_no_es_una_entrada_de_menu():
    """La ficha de detalle NO está en NAV: se llega desde la lista."""
    from app.chassis import NAV
    assert panel.ITEM_ROUTE_NAME not in {n.route_name for n in NAV}


def test_las_plantillas_no_llevan_urls_escritas_a_mano():
    """Un enlace literal no avisa cuando la ruta cambia.

    Los comentarios Jinja (`{# ... #}`) se retiran antes de mirar: una ruta
    MENCIONADA en un comentario no crea ningún enlace, y contarla sería el falso
    positivo de "citar es afirmar" ya registrado en este repo.
    """
    base = Path(panel.__file__).resolve().parent.parent / "templates" / "chassis"
    for nombre in ("entities.html", "entities_item.html"):
        texto = (base / nombre).read_text(encoding="utf-8")
        marcado = re.sub(r"\{#.*?#\}", "", texto, flags=re.S)
        assert SLOT.prefix not in marcado, f"{nombre} escribe {SLOT.prefix!r} a mano"
        assert "url_for(" in marcado


def test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura(real_app):
    """SOLO LECTURA también en la INTERFAZ: ni un formulario que no sea GET.

    No es redundante con la enumeración de rutas: aquella prueba que nadie
    puede escribir; ésta, que el panel no OFRECE hacerlo. Un botón que promete
    fusionar y no puede es una funcionalidad anunciada y ausente.
    """
    base = Path(panel.__file__).resolve().parent.parent / "templates" / "chassis"
    formularios_vistos: dict[str, list[str]] = {}
    for nombre in ("entities.html", "entities_item.html"):
        marcado = re.sub(
            r"\{#.*?#\}", "",
            (base / nombre).read_text(encoding="utf-8"), flags=re.S,
        )
        formularios = re.findall(r"<form[^>]*>", marcado)
        formularios_vistos[nombre] = formularios
        for f in formularios:
            assert 'method="get"' in f, f"{nombre} declara un formulario no-GET: {f}"
        for verbo in ("editar", "fusionar", "renombrar", "borrar", "eliminar"):
            assert verbo not in marcado.lower(), (
                f"{nombre} ofrece la acción {verbo!r}, que este panel no puede cumplir"
            )

    # CONTROL DE QUE EL BUCLE HA EJERCIDO ALGO. Sin esto, la comprobación de
    # arriba es de la misma familia que el suelo autocumplido ya cazado en la
    # prueba de contadores: `for f in []` no ejecuta nada y pasa en VERDE.
    # Medido: hoy `entities_item.html` tiene CERO formularios, así que su vuelta
    # del bucle ya es vacía (ahí la vacuidad coincide con lo correcto), y si
    # alguien convirtiera también el formulario de filtros de `entities.html` en
    # un `<div>`, la comprobación entera quedaría vacía y seguiría verde —
    # comprobado inyectando justo eso.
    #
    # No se exige un número por plantilla: eso congelaría el producto (un
    # formulario GET nuevo es legítimo). Se exige que el conjunto de plantillas
    # del panel aporte AL MENOS UN formulario que el bucle haya llegado a mirar.
    total = sum(len(v) for v in formularios_vistos.values())
    assert total >= 1, (
        f"el bucle no ha mirado ni un formulario ({formularios_vistos}): la "
        "comprobación se está cumpliendo sola"
    )


# ===========================================================================
# 2. Interruptor del hueco: apagado por defecto, y DESPUÉS de la guarda
# ===========================================================================

def test_sin_el_interruptor_el_panel_no_se_sirve(real_app, con_proveedor):
    """Ausente el flag, 404: igual que una ruta que no existe."""
    os.environ.pop(FLAG, None)
    con_proveedor()
    assert client(real_app).get(SLOT.prefix).status_code == 404
    assert client(real_app).get(f"{SLOT.prefix}/item/lore-player").status_code == 404


@pytest.mark.parametrize("valor", ["", "false", "0", "quizas", "TRUE ", "yes"])
def test_solo_true_y_1_encienden_el_panel(real_app, con_proveedor, valor):
    """Un valor que no se entiende es un dato ausente, no un permiso."""
    con_proveedor()
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
    """Con auth activa, el anónimo recibe LO MISMO esté encendido o apagado.

    El interruptor se evalúa DESPUÉS de la guarda a propósito: si se evaluara
    antes, comparar 404 contra 302 diría qué paneles están encendidos.
    """
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
# 3. Autorización: la actual manda. Es el rol MÁS BAJO de los cuatro huecos.
# ===========================================================================

def test_con_auth_activa_el_anonimo_va_a_login(real_app, auth_on, panel_on, con_proveedor):
    con_proveedor()
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 302 and "/login" in r.headers["location"]


def test_con_auth_activa_el_rol_publicado_entra(real_app, auth_on, panel_on, con_proveedor):
    """`viewer` es el rol publicado, y es el MÍNIMO del sistema.

    No hay ningún rol por debajo con el que probar la denegación por rol
    insuficiente — la misma razón por la que el contrato del chasis deja
    `test_slot_denies_insufficient_role[G]` en skip. Lo que sí se prueba es que
    el rol publicado entra y que el anónimo no.
    """
    con_proveedor()
    cookie = login_cookie(auth_on, "g_publicado", "viewer")
    assert client(real_app, cookie).get(SLOT.prefix).status_code == 200


def test_sin_auth_no_reaparece_el_comportamiento_permisivo(real_app, panel_on, con_proveedor):
    """EL TEST DE ESTE CARRIL, en su dirección restrictiva.

    Con `S9K_AUTH_ENABLED` desactivado no hay principal, luego no hay autoridad:
    el contexto es anónimo de mínimo privilegio (docs/75). Antes ese mismo caso
    producía `admin_full=True` y el visor entero era público. Si alguien reabre
    esa vía, este test se pone rojo: material de partida, secretos, capa de
    narrador, referencia, futuro, workspace ajeno y datos malformados NO se
    entregan ni en la lista, ni en los contadores, ni por ID.
    """
    from app.authz.dependencies import get_visibility_context

    con_proveedor()
    cliente = client(real_app)
    lista = cliente.get(SLOT.prefix)
    assert lista.status_code == 200

    mostrados = set(ids_de_la_lista(lista.text))
    assert mostrados == VISIBLES_PARA_ANONIMO == set(), (
        f"lo que ve un anónimo cambió: {sorted(mostrados)}"
    )
    # Contadores: sólo cuentan lo autorizado, y lo autorizado es CERO.
    assert '<span data-count="visible">0</span>' in lista.text
    # Y por ID tampoco: la barrera no depende de por dónde se entre.
    for oculto in {n["id"] for n in MATRIZ} - VISIBLES_PARA_ANONIMO:
        assert cliente.get(f"{SLOT.prefix}/item/{oculto}").status_code == 404, oculto

    # El contexto que produce el productor real, no uno fabricado a mano.
    class _Peticion:
        class state:  # noqa: D106
            user = None
            session = None

    assert get_visibility_context(_Peticion()).admin_full is False, (
        "el contexto anónimo con auth desactivada volvió a conceder admin_full"
    )


#: LA TABLA de `docs/77 §3`, MEDIDA: una fila por caso, y en cada fila los DOS
#: veredictos que la hacen bidireccional.
#:
#:      (entidad, la ve un ANÓNIMO, la ve un LECTOR LEGÍTIMO)
#:
#: La columna del anónimo es hoy 0 de 11 (LORE-ANÓNIMO-DENEGADO, 2026-08-14);
#: antes era 1 de 11 —`lore-player`—, medido por este carril y por el F sobre
#: huecos distintos. La columna del lector legítimo es 4 de 11 y existe para que
#: la primera no pueda cumplirse apagando el panel: si mañana se ocultara de
#: más, esta tabla se pone roja por la segunda columna.
#:
#: Sigue sin derivarse del motor. Se escribe a mano justamente para poder
#: discrepar de él.
TABLA_ANONIMO_VS_LECTOR: tuple[tuple[str, bool, bool], ...] = (
    ("lore-player",         False, True),
    ("lore-secreto",        False, False),
    ("lore-narrador",       False, False),
    ("lore-referencia",     False, True),
    ("lore-futuro",         False, True),
    ("partida-A",           False, True),
    ("workspace-ajeno",     False, False),
    ("sin-scope",           False, False),
    ("visibilidad-rara",    False, False),
    ("visibilidad-deny",    False, False),
    ("known-by-malformado", False, False),
)


def _cookie_de_lector_legitimo(auth_db_path) -> str:
    """`viewer` autenticado, con `partida-A` activa y tope de sesión 5.

    Se construye con la cadena real —usuario en `auth.db`, concesión de partida
    y sesión— y no fabricando un contexto: el punto de inyección de este visor
    está congelado (`get_filtered_provider` llama a `get_visibility_context`
    como función normal, no vía `Depends`), así que un contexto inyectado sería
    inerte y saldría verde por no morder.
    """
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db_mod.get_conn(auth_db_path) as conn:
        u = auth_db_mod.create_user(
            conn, username="g_lector_legitimo", display_name="Lectora",
            password_hash=hash_password(PASSWORD), role="viewer",
        )
        auth_db_mod.update_user(conn, u.id, must_change_password=False)
        auth_db_mod.grant_partida_access(
            conn, u.id, WS, "partida-A", granted_by="admin",
            max_visible_session=5, character_id=None,
        )
        u = auth_db_mod.get_user_by_id(conn, u.id)
        token, sesion = create_session(conn, u)
        auth_db_mod.set_session_active_partida(conn, sesion.id, "partida-A")
    return token


def _cookie_de_lector_sin_partida(auth_db_path) -> str:
    """`viewer` autenticado SIN partida activa: sólo la capa juego.

    Es el contraste exacto de la decisión: el anónimo y este lector se
    diferencian ÚNICAMENTE en tener principal —ninguno de los dos tiene
    partida—. Si la capa juego siguiera concediéndose por la ausencia de
    partida, los dos verían lo mismo.
    """
    return login_cookie(auth_db_path, "g_lector_sin_partida", "viewer")


@pytest.mark.parametrize(
    "entidad,visible_anon,visible_lector", TABLA_ANONIMO_VS_LECTOR,
    ids=[c[0] for c in TABLA_ANONIMO_VS_LECTOR],
)
def test_tabla_de_lo_que_ve_un_anonimo_con_auth_desactivada(
    real_app, panel_on, con_proveedor, entidad, visible_anon, visible_lector
):
    """LA TABLA de `docs/77 §3`, celda a celda y BIDIRECCIONAL.

    Qué cambió, y por qué no es un ajuste de la pantalla:

    Antes, con la autenticación desactivada, el material CON `partida_id`
    quedaba oculto **pero el lore de capa juego con visibilidad `player` era
    visible y su ficha respondía 200 con el texto completo** — 1 de 11. Se midió
    aquí y, por separado, en el carril F sobre otro hueco, con el mismo
    veredicto y la misma proporción. No era un defecto de este panel: era la
    política heredada aplicada de forma consistente, y la llave de la capa juego
    era, literalmente, no tener partida.

    El operador decidió (V3 RC, 2026-08-14) que LORE_ANÓNIMO = DENEGADO: la
    ausencia de partida no concede visibilidad adicional, porque lo contrario
    reintroduce una vía permisiva implícita justo donde ya se decidió que «auth
    desactivada ≠ acceso total». La capa juego pasa a exigir llave propia
    (`can_view_lore`, declarada en el registro M5b). La tabla es ahora 0 de 11.

    BIDIRECCIONAL, y esto importa más que antes: una tabla de once "no" se
    satisface con un panel roto que no pinta nada nunca. Por eso cada fila trae
    también lo que ve un lector legítimo, y cuatro de las once dicen SÍ por esa
    columna. El test falla en las dos direcciones: si se entregara de más al
    anónimo, y si se ocultara de más al que tiene derecho.
    """
    con_proveedor()

    # --- dirección 1: el anónimo con la autenticación desactivada
    cliente = client(real_app)
    en_la_lista = entidad in ids_de_la_lista(cliente.get(SLOT.prefix).text)
    assert en_la_lista is visible_anon, (
        f"{entidad}: el anónimo lo ve en la lista={en_la_lista}, "
        f"esperado={visible_anon}"
    )
    ficha = cliente.get(f"{SLOT.prefix}/item/{entidad}")
    assert ficha.status_code == (200 if visible_anon else 404), (
        f"{entidad}: la ficha respondió {ficha.status_code} a un anónimo"
    )
    assert TEXTO_LORE not in ficha.text, (
        f"{entidad}: el texto completo del lore ha llegado a un anónimo"
    )


@pytest.mark.parametrize(
    "entidad,visible_anon,visible_lector", TABLA_ANONIMO_VS_LECTOR,
    ids=[c[0] for c in TABLA_ANONIMO_VS_LECTOR],
)
def test_tabla_la_misma_fila_para_un_lector_legitimo(
    real_app, auth_on, panel_on, con_proveedor, entidad, visible_anon,
    visible_lector
):
    """CONTROL DE COLAPSO, fila a fila: la segunda columna de la MISMA tabla.

    Un `viewer` autenticado con su partida activa sigue viendo lo suyo. Si la
    denegación al anónimo se hubiera llevado por delante a quien sí tiene
    derecho —el modo de fallo que más fácilmente se confunde con seguridad—,
    esta mitad se pone roja y dice exactamente qué fila se perdió.
    """
    con_proveedor()
    cliente = client(real_app, _cookie_de_lector_legitimo(auth_on))

    en_la_lista = entidad in ids_de_la_lista(cliente.get(SLOT.prefix).text)
    assert en_la_lista is visible_lector, (
        f"{entidad}: el lector legítimo lo ve en la lista={en_la_lista}, "
        f"esperado={visible_lector}"
    )
    ficha = cliente.get(f"{SLOT.prefix}/item/{entidad}")
    assert ficha.status_code == (200 if visible_lector else 404), (
        f"{entidad}: la ficha respondió {ficha.status_code} al lector legítimo"
    )
    if entidad == "lore-player":
        assert TEXTO_LORE in ficha.text, (
            "la ficha del lore no entrega su contenido a quien SÍ tiene "
            "derecho: el 200 no dice nada por sí solo"
        )


def test_la_tabla_tiene_las_dos_direcciones_representadas():
    """Suelo de la tabla, y no autocumplido.

    Se exige lo que hace falta para que el parametrizado distinga un panel
    correcto de uno roto: que el anónimo no vea NADA (0 de 11, el veredicto
    nuevo) y que el lector legítimo SÍ vea algo y no todo. Si alguien
    "arreglara" un futuro fallo apagando el panel, la segunda condición cae.
    """
    anonimo = [c[0] for c in TABLA_ANONIMO_VS_LECTOR if c[1]]
    lector = [c[0] for c in TABLA_ANONIMO_VS_LECTOR if c[2]]
    assert anonimo == [], (
        f"la tabla concede algo a un anónimo: {anonimo}. LORE_ANÓNIMO = "
        f"DENEGADO (V3 RC): la ausencia de partida no concede visibilidad"
    )
    assert 0 < len(lector) < len(TABLA_ANONIMO_VS_LECTOR), (
        "el lector legítimo no ve nada, o lo ve todo: en ninguno de los dos "
        "casos la tabla distingue una autorización de una pantalla averiada"
    )
    assert sorted(lector) == sorted(VISIBLES_PARA_LECTOR_LEGITIMO)
    assert len(TABLA_ANONIMO_VS_LECTOR) == 11, "la tabla dejó de ser 1 fila por caso"
    assert {c[0] for c in TABLA_ANONIMO_VS_LECTOR} == {n["id"] for n in MATRIZ}, (
        "la tabla y la matriz de la política se han desincronizado: hay un caso "
        "sin fila o una fila sin caso"
    )


def test_un_viewer_autenticado_ve_MAS_que_un_anonimo(real_app, auth_on, panel_on, con_proveedor):
    """Contrapeso de la tabla: "casi todo oculto" no puede ser un panel roto.

    Un `viewer` autenticado tiene `can_view_reference=True` y el anónimo no
    (`app/authz/context.py`), así que el material de referencia distingue a los
    dos. Sin este contraste, la tabla de arriba sería compatible con un panel
    que simplemente no muestra nada nunca.
    """
    con_proveedor()
    cookie = login_cookie(auth_on, "g_viewer_ref", "viewer")
    vistos = set(ids_de_la_lista(client(real_app, cookie).get(SLOT.prefix).text))
    assert "lore-referencia" in vistos, (
        f"el viewer autenticado no ve el material de referencia: {sorted(vistos)}"
    )
    assert vistos > VISIBLES_PARA_ANONIMO


def test_una_partida_activa_abre_su_material_y_solo_el_suyo(
    real_app, auth_on, panel_on, con_proveedor
):
    """El aislamiento entre partidas se aplica igual desde este panel.

    No es una regla nueva: la evalúa `PolicyFilteredProvider`. Lo que se fija
    aquí es que el panel no la esquiva por ningún camino, ni en lista ni por ID.
    """
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    con_proveedor()
    with auth_db_mod.get_conn(auth_on) as conn:
        u = auth_db_mod.create_user(
            conn, username="g_jugadora", display_name="Jugadora",
            password_hash=hash_password(PASSWORD), role="viewer",
        )
        auth_db_mod.update_user(conn, u.id, must_change_password=False)
        auth_db_mod.grant_partida_access(
            conn, u.id, WS, "partida-A", granted_by="admin",
            max_visible_session=5, character_id=None,
        )
        u = auth_db_mod.get_user_by_id(conn, u.id)
        token, sesion = create_session(conn, u)
        auth_db_mod.set_session_active_partida(conn, sesion.id, "partida-A")

    cliente = client(real_app, token)
    vistos = set(ids_de_la_lista(cliente.get(SLOT.prefix).text))
    assert "partida-A" in vistos, f"su propia partida no se entrega: {sorted(vistos)}"
    assert cliente.get(f"{SLOT.prefix}/item/partida-A").status_code == 200
    # Y sigue sin ver lo que ninguna partida abre.
    assert "lore-secreto" not in vistos
    assert cliente.get(f"{SLOT.prefix}/item/lore-secreto").status_code == 404


def test_el_panel_no_declara_vocabulario_propio_de_autorizacion():
    """Ni una segunda tabla de rangos, ni un `admin_full` local, ni un `role ==`.

    La guarda tiene que ser la del chasis (`slot_guard`) y el filtro de
    contenido el proveedor de `get_filtered_provider`. Se comprueba sobre el
    AST, no leyendo el fichero: una mención en un comentario no cuenta ni a
    favor ni en contra.
    """
    import ast

    arbol = ast.parse(Path(panel.__file__).read_text(encoding="utf-8"))
    nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
    atributos = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
    cadenas = {n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant)
               and isinstance(n.value, str)}
    assert "admin_full" not in nombres | atributos | cadenas
    assert "slot_guard" in nombres
    assert "get_filtered_provider" in nombres
    # Ni el punto de inyección congelado, ni un ámbito fabricado.
    assert "UNRESTRICTED" not in nombres | cadenas
    for rol in ("admin", "reviewer", "viewer", "anonymous"):
        assert rol not in cadenas, f"El router compara el rol {rol!r} por su cuenta"
    # Ni vocabulario paralelo de visibilidad: esas dimensiones no se evalúan aquí.
    for dimension in ("known_by", "can_view_secret", "allowed_partida_ids",
                      "max_visible_session", "partida_in_scope"):
        assert dimension not in nombres | atributos | cadenas, (
            f"El router evalúa {dimension!r} por su cuenta en vez de delegar"
        )


def test_el_panel_usa_el_proveedor_filtrado_y_no_el_crudo():
    """`get_provider` (crudo) no puede estar ni importado aquí.

    Tenerlo al lado invita a usarlo por error, y esa vía se salta la
    autorización entera. Es la misma nota que encabeza `routers/readonly.py`.
    """
    import ast

    arbol = ast.parse(Path(panel.__file__).read_text(encoding="utf-8"))
    importados = {
        alias.name
        for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)
        for alias in n.names
    }
    assert "get_provider" not in importados
    assert "get_filtered_provider" in importados


# ===========================================================================
# 4. SOLO LECTURA: frontera dura, comprobada por enumeración
# ===========================================================================

METODOS_DE_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}

#: Métodos del `GraphProvider` que LEEN. La interfaz no declara ninguno que
#: escriba, así que la lista es la interfaz entera: cualquier método invocado
#: fuera de aquí es un método que no existía cuando se escribió esta prueba.
METODOS_DE_LECTURA = {
    "is_connected", "workspaces", "counts", "entity_types", "search", "graph",
    "entity", "relations_for_entity", "list_entities", "list_sources",
    "source_detail", "quality_metrics",
}


def rutas_del_espacio_del_panel(app) -> list:
    """Todas las rutas de la APP bajo `/panel/entities`, a cualquier profundidad.

    Es el patrón que dejó medido el hueco C (docs/76 §4bis), y las razones son
    suyas palabra por palabra:

    1. Se recorre **la app**, no `panel.router.routes`. La frontera de solo
       lectura es del ESPACIO DE URL, no del módulo: un
       `@app.post("/panel/entities/fusionar")` escrito desde `app/main.py` —o
       desde cualquier otro carril— cuelga escritura en este prefijo sin tocar
       este fichero, y una enumeración del propio router lo daría por bueno.
    2. Se recorre **recursivamente**, con el mismo `iter_mounted_routes` que usa
       el barrido de autorización del chasis. Un barrido de primer nivel sobre
       `app.routes` devuelve CERO rutas de este prefijo, y un arnés que enumera
       0 elementos habría "demostrado" cualquier cosa: de ahí el suelo de
       plausibilidad de abajo.
    3. El `path` comparado es el EFECTIVO (`iter_mounted_routes` compone el
       prefijo de cada `Mount`), y la pertenencia se pregunta a
       `route_in_prefix`, que falla cerrado ante un path irresoluble y compara
       por SEGMENTOS. Lo segundo importa especialmente aquí: `/panel/entities`
       es vecino textual de nada, pero `/entities` sí existe en el visor y una
       frontera de texto mal escrita los mezclaría.
    """
    from app.chassis import iter_mounted_routes, route_in_prefix

    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]


def test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia(real_app):
    """Suelo de plausibilidad: 0 rutas no es "no hay defecto", es "no he mirado".

    El recuento sólo cuenta rutas con path RESOLUBLE. `route_in_prefix` falla
    cerrado, así que una ristra de rutas con path indeterminable caería "dentro"
    del prefijo y podría satisfacer el suelo sin que el censo viese nada real:
    el suelo se estaría autocumpliendo con el propio fallo cerrado.
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
    # Las que este carril declara, NOMBRADAS: el suelo no se satisface con
    # cualquier ruta que pase por ahí.
    assert SLOT.prefix in caminos
    assert f"{SLOT.prefix}/item/{{entity_id}}" in caminos


def test_el_gate_no_acusa_a_un_vecino_de_prefijo():
    """FALSO POSITIVO: la frontera es de SEGMENTO, no de texto.

    `POST /panel/entitiesXYZ/borrar` no está en el espacio de URL de este panel
    y el gate no puede reportarlo. Un rojo por el motivo equivocado es más
    peligroso que un verde: entrena a ignorar el gate.
    """
    from fastapi import FastAPI

    vecino = FastAPI()

    @vecino.post(f"{SLOT.prefix}XYZ/borrar")
    def _borrar():  # pragma: no cover - nunca se invoca
        return {"ok": True}

    @vecino.post(f"{SLOT.prefix}-legacy/borrar")
    def _borrar_legacy():  # pragma: no cover
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

    @propio.post(f"{SLOT.prefix}/fusionar")
    def _fusionar():  # pragma: no cover
        return {"ok": True}

    caminos = [getattr(r, "path", "") for r in rutas_del_espacio_del_panel(propio)]
    assert caminos == [f"{SLOT.prefix}/fusionar"], caminos


def test_ninguna_ruta_del_espacio_del_panel_acepta_escritura(real_app):
    """LA frontera: nadie cuelga escritura bajo `/panel/entities`, venga de donde venga.

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
    """El MÓDULO tampoco, comprobado aparte del espacio de URL.

    Redundante por construcción con el test anterior; se conserva porque
    LOCALIZA el fallo: dice que el POST lo puso ESTE fichero, no otro.
    """
    for ruta in panel.router.routes:
        assert not (set(getattr(ruta, "methods", set())) & METODOS_DE_ESCRITURA), (
            f"{getattr(ruta, 'path', ruta)} monta métodos de escritura"
        )


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_los_metodos_de_escritura_son_rechazados_por_http(  # noqa: D401
    # NO ES UNA GARANTÍA: sondea SÓLO el prefijo raíz. Un POST colgado en
    # cualquier subruta lo deja verde (medido en el hueco C). Se conserva como
    # redundancia inofensiva; la defensa es la enumeración del espacio de URL.
    real_app, panel_on, con_proveedor, metodo
):
    con_proveedor()
    r = getattr(client(real_app), metodo)(SLOT.prefix)
    assert r.status_code in (404, 405), f"{metodo.upper()} devolvió {r.status_code}"


def test_recorrer_el_panel_solo_invoca_lecturas_del_proveedor(
    real_app, panel_on, con_proveedor
):
    """Ningún efecto lateral, tampoco desde un GET.

    La enumeración de rutas prueba que nadie puede ENTRAR por un método de
    escritura. Esta prueba cubre la otra mitad: que el camino GET que sí existe
    no ejerce ninguna escritura sobre la fuente de datos. El proveedor espía
    registra cada método invocado y se exige que todos sean de lectura.
    """
    proveedor = con_proveedor()
    cliente = client(real_app)
    cliente.get(SLOT.prefix)
    cliente.get(f"{SLOT.prefix}/item/lore-player")
    cliente.get(f"{SLOT.prefix}/item/no-existe")

    assert proveedor.llamadas, "el panel no llamó al proveedor: la prueba no mide nada"
    ajenas = sorted(set(proveedor.llamadas) - METODOS_DE_LECTURA)
    assert not ajenas, f"el panel invocó métodos que no son de lectura: {ajenas}"


# ===========================================================================
# 5. Indistinguibilidad: no autorizado == inexistente
# ===========================================================================

def test_no_autorizado_e_inexistente_dan_EL_MISMO_404(real_app, panel_on, con_proveedor):
    """Con el rol más bajo de los cuatro, ésta es la garantía más mirada.

    Se comparan CÓDIGO y CUERPO, no sólo el código: dos 404 con cuerpos
    distintos siguen diciendo cuál de los dos recursos existe. Un 403 aquí diría
    "existe pero no es tuya", que es justo el dato que no se entrega.
    """
    con_proveedor()
    cliente = client(real_app)
    inexistente = cliente.get(f"{SLOT.prefix}/item/no-existe-en-ninguna-parte")
    for oculto in sorted({n["id"] for n in MATRIZ} - VISIBLES_PARA_ANONIMO):
        prohibido = cliente.get(f"{SLOT.prefix}/item/{oculto}")
        assert (prohibido.status_code, prohibido.text) == (
            inexistente.status_code, inexistente.text
        ), f"{oculto} es distinguible de un id inexistente"
    assert inexistente.status_code == 404


def test_un_id_con_barra_no_llega_al_handler_y_TAMPOCO_distingue(
    real_app, panel_on, con_proveedor
):
    """Menor declarado, con la medida delante.

    Un id que contiene `/` no encaja en `/panel/entities/item/{entity_id}`, así
    que lo rechaza el ENRUTADO de Starlette antes de llegar a este panel: el
    cuerpo es el genérico de 22 bytes, no el 404 de 34 bytes del handler. Medido:

        'no-existe'                  404, 34 bytes, sha256 0219103e…
        'lore-secreto'               404, 34 bytes, sha256 0219103e…  (idéntico)
        '<script>alert(1)</script>'  404, 22 bytes, sha256 37ec4665…
        'a/b'                        404, 22 bytes, sha256 37ec4665…  (idéntico)

    Nótese que el caso de `<script>` NO es una particularidad del marcado: lo
    que lo desvía es la barra de la etiqueta de cierre. Y lo importante es que
    **no rompe la indistinguibilidad**, porque la diferencia la marca la FORMA
    del identificador y no la existencia del recurso: una entidad que SÍ existe
    y cuyo id lleva barra recibe exactamente la misma respuesta que una que no
    existe. Eso es lo que este test fija, y no la mera constatación del 404.
    """
    import hashlib

    con_proveedor(ProveedorFalso(
        nodos=[nodo("con/barra", description=TEXTO_LORE), nodo("lore-player")],
        aristas=[],
    ))
    cliente = client(real_app)

    existe_con_barra = cliente.get(f"{SLOT.prefix}/item/con/barra")
    no_existe_con_barra = cliente.get(f"{SLOT.prefix}/item/otra/barra")
    assert existe_con_barra.status_code == no_existe_con_barra.status_code == 404
    assert hashlib.sha256(existe_con_barra.content).hexdigest() == \
        hashlib.sha256(no_existe_con_barra.content).hexdigest(), (
            "un id con barra que SÍ existe se distingue de uno que no: la forma "
            "del identificador estaría filtrando la existencia del recurso"
        )
    # Y el contenido de la entidad no se escapa por esa vía.
    assert TEXTO_LORE not in existe_con_barra.text

    # Control positivo: el 404 del HANDLER (sin barra) es otro cuerpo, y es el
    # que sostiene la indistinguibilidad de la prueba de al lado. Sin esta
    # comparación, lo de arriba sería compatible con que TODO diese 22 bytes.
    del_handler = cliente.get(f"{SLOT.prefix}/item/no-existe")
    assert del_handler.status_code == 404
    assert del_handler.content != no_existe_con_barra.content


def test_el_cuerpo_del_404_no_nombra_la_entidad_pedida(real_app, panel_on, con_proveedor):
    """Reflejar el id en el error lo convertiría en un eco, no en una fuga —
    pero un cuerpo que varía con la petición ya no es un cuerpo idéntico, y la
    indistinguibilidad de arriba dejaría de poder afirmarse."""
    con_proveedor()
    r = client(real_app).get(f"{SLOT.prefix}/item/lore-secreto")
    assert r.status_code == 404
    assert "lore-secreto" not in r.text


# ===========================================================================
# 6. Contadores: DESPUÉS de autorizar, del conjunto AUTORIZADO, y no son 0
# ===========================================================================

def contadores(html: str) -> dict[str, int]:
    return {
        clave: int(valor)
        for clave, valor in re.findall(r'data-count="([^"]+)">(\d+)<', html)
    }


def test_los_contadores_son_del_conjunto_autorizado(
    real_app, auth_on, panel_on, con_proveedor
):
    """El total es "cuántas autorizadas hay", nunca "cuántas hay en la base".

    Es la misma doctrina que `app/graph_view.py` y docs/73: un total calculado
    antes de filtrar revelaría POR DIFERENCIA la existencia de lo que la
    política acaba de ocultar.
    """
    proveedor = con_proveedor()

    # LORE-ANÓNIMO-DENEGADO. El contador del ANÓNIMO (que ahora es 0, no 1) se
    # mide en `test_sin_auth_no_reaparece_el_comportamiento_permisivo`, y tiene
    # que medirse allí: con la autenticación ACTIVA —que es lo que este test
    # necesita para poder autenticar a alguien— un anónimo recibe la redirección
    # al login y no hay ninguna cifra que leer. Medirlo aquí daría un 302 y un
    # `KeyError`, no un cero.
    #
    # Aquí se mide la otra mitad, que es la que este test siempre quiso decir:
    # el total publicado es el del CONJUNTO AUTORIZADO de quien pregunta, ni el
    # total crudo del proveedor ni cero.
    c_lector = contadores(
        client(real_app, _cookie_de_lector_legitimo(auth_on)).get(SLOT.prefix).text
    )
    assert c_lector["visible"] == len(VISIBLES_PARA_LECTOR_LEGITIMO) == 4
    assert c_lector["visible"] != len(
        [n for n in proveedor.nodos if n["workspace"] == WS]
    ), "el contador publica el total crudo: fuga por diferencia"


@pytest.mark.parametrize("limite", [1, 2, 5, 50, 200, 2000])
def test_barrer_el_tope_de_pagina_no_mueve_el_total(
    real_app, panel_on, con_proveedor, auth_on, limite
):
    """La comprobación de docs/73, repetida aquí porque este panel publica cifras.

    Allí se barrió el límite de 1 a 2000 y se comprobó que el total no filtra:
    si el contador es propiedad del conjunto AUTORIZADO, moverlo no puede
    cambiarlo. Se mide con un principal que ve varias entidades — con una sola
    fila el barrido sería trivialmente constante y no diría nada.
    """
    con_proveedor()
    cookie = login_cookie(auth_on, f"g_barrido_{limite}", "viewer")
    r = client(real_app, cookie).get(f"{SLOT.prefix}?limit={limite}")
    c = contadores(r.text)
    autorizadas = len({"lore-player", "lore-referencia"})
    assert c["visible"] == autorizadas, f"limit={limite} movió el total: {c}"
    assert c["filtered"] == autorizadas
    # Lo MOSTRADO sí depende del tope (y del tope máximo del visor); el total no.
    assert c["shown"] <= autorizadas


def test_la_ausencia_de_datos_no_se_publica_como_cero(real_app, panel_on, con_proveedor):
    """Si el proveedor falla, la pantalla NO publica ningún contador.

    Un `0` en esa situación sería una afirmación falsa: "hay cero entidades
    autorizadas" cuando lo cierto es "no se pudo saber". Ausencia no es cero.
    """
    con_proveedor(ProveedorQueRevienta())
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 503
    assert 'data-state="error"' in r.text
    assert "data-count" not in r.text, "publicó contadores sin haber podido contar"


def test_un_contador_no_aparece_antes_de_autorizar(real_app, auth_on, panel_on, con_proveedor):
    """Un anónimo con auth activa no recibe NINGUNA cifra: recibe la redirección.

    Publicar contadores antes de la guarda convertiría el panel en un
    enumerador para quien ni siquiera se ha identificado.

    SUELO AUTOCUMPLIDO, evitado a propósito: la mitad negativa de esta prueba
    —«un 302 no trae contadores»— es cierta por construcción, porque una
    redirección no tiene cuerpo. Sola, pasaría con el panel desmontado, con la
    plantilla vacía o con los contadores borrados del producto. Por eso lleva
    pegado el control POSITIVO: la MISMA petición, con un principal válido, sí
    tiene que traer cifras. Lo que se afirma entonces no es «no hay cuerpo»,
    sino que la diferencia la pone la autorización.
    """
    con_proveedor()
    anonimo = client(real_app).get(SLOT.prefix)
    assert anonimo.status_code == 302
    assert "data-count" not in anonimo.text

    cookie = login_cookie(auth_on, "g_contador_control", "viewer")
    autorizado = client(real_app, cookie).get(SLOT.prefix)
    assert autorizado.status_code == 200
    assert contadores(autorizado.text), (
        "el control positivo no ve contadores: la mitad negativa de esta prueba "
        "se estaría cumpliendo sola"
    )


# ===========================================================================
# 7. Errores y estados desconocidos: fallo cerrado, sin fugas
# ===========================================================================

def test_un_proveedor_caido_da_503_sin_filtrar_rutas(real_app, panel_on, con_proveedor):
    """El detalle es `type(exc).__name__`, nunca `str(exc)`.

    El mensaje del proveedor de esta prueba lleva una URI con credenciales a
    propósito: si saliera a la pantalla, este test lo vería.
    """
    con_proveedor(ProveedorQueRevienta())
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 503
    assert "RuntimeError" in r.text
    assert ProveedorQueRevienta.RUTA_SECRETA not in r.text
    assert "Traceback" not in r.text

    ficha = client(real_app).get(f"{SLOT.prefix}/item/lore-player")
    assert ficha.status_code == 503
    assert ProveedorQueRevienta.RUTA_SECRETA not in ficha.text


def test_un_estado_de_revision_desconocido_se_marca_en_la_pantalla(
    real_app, auth_on, panel_on, con_proveedor
):
    """Fallo cerrado: un estado fuera del vocabulario canónico NO se pinta como
    si fuera legítimo. La decisión vive en `app/labels.py` contra el contrato
    `review-status/v1`; aquí no hay una segunda lista.

    Pide un lector legítimo: es una prueba de ETIQUETADO, y a un anónimo ya no
    se le pinta ninguna fila que etiquetar (LORE-ANÓNIMO-DENEGADO).
    """
    con_proveedor(ProveedorFalso(
        nodos=[nodo("lore-player", review_status="aprobadisimo")], aristas=[]
    ))
    texto = client(real_app, _cookie_de_lector_sin_partida(auth_on)).get(SLOT.prefix).text
    assert "no reconocido (aprobadisimo)" in texto


def test_un_orden_desconocido_no_revienta_ni_amplia_nada(real_app, panel_on, con_proveedor):
    """La lista blanca de ordenaciones es la de `/entities`, importada.

    Un `sort` no reconocido se normaliza (no es un error del usuario) y un
    `order` inválido es un 400. Lo importante es que ninguno de los dos es una
    vía para colar texto hacia el proveedor.
    """
    con_proveedor()
    cliente = client(real_app)
    assert cliente.get(f"{SLOT.prefix}?sort=RETURN+1").status_code == 200
    assert cliente.get(f"{SLOT.prefix}?order=DROP").status_code == 400


def test_sin_material_se_pinta_el_estado_vacio_no_una_excepcion(
    real_app, panel_on, con_proveedor
):
    """Una BD vacía entra por `empty`, que es el camino por defecto del chasis."""
    con_proveedor(ProveedorFalso(nodos=[], aristas=[]))
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 200
    assert 'data-state="empty"' in r.text


def test_un_panel_vacio_para_un_anonimo_es_correcto(real_app, panel_on, con_proveedor):
    """Fija la lectura, no sólo el comportamiento.

    Sin lore de capa juego, un anónimo con auth desactivada recibe una pantalla
    VACÍA — y eso es el resultado correcto de la autorización actual, no una
    pantalla que arreglar.
    """
    con_proveedor(ProveedorFalso(
        nodos=[n for n in MATRIZ if n["id"] != "lore-player"], aristas=[]
    ))
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 200
    assert 'data-state="empty"' in r.text
    assert contadores(r.text)["visible"] == 0


# ===========================================================================
# 8. Relaciones: el otro extremo también pasa por la política
# ===========================================================================

def test_la_ficha_no_revela_relaciones_hacia_lo_que_no_se_ve(
    real_app, auth_on, panel_on, con_proveedor
):
    """`lore-player` tiene aristas hacia `lore-secreto` y hacia `partida-A`.

    Ninguna de las dos puede asomar: `relations_for_entity` del proveedor
    filtrado exige que el otro extremo sea visible. Aquí se comprueba que el
    panel no vuelve a pedirlas por otro camino ni pinta el id del extremo
    oculto.

    El sujeto pasa a ser un lector legítimo SIN partida activa: ve `lore-player`
    y sigue sin ver ni `lore-secreto` ni `partida-A`, que es justo el par que
    esta prueba necesita. Con un anónimo la ficha ya no responde 200 y el test
    se habría cumplido por no llegar a pintarse nada.
    """
    con_proveedor()
    r = client(real_app, _cookie_de_lector_sin_partida(auth_on)).get(
        f"{SLOT.prefix}/item/lore-player")
    assert r.status_code == 200
    assert "lore-secreto" not in r.text
    assert "partida-A" not in r.text
    assert 'data-role="relaciones"' in r.text


def test_un_admin_SI_ve_esas_relaciones(real_app, auth_on, panel_on, con_proveedor):
    """Control positivo de la prueba anterior.

    Sin él, "no aparecen las relaciones" sería compatible con un panel que
    nunca pinta relaciones.
    """
    con_proveedor()
    cookie = login_cookie(auth_on, "g_admin_rel", "admin")
    r = client(real_app, cookie).get(f"{SLOT.prefix}/item/lore-player")
    assert r.status_code == 200
    assert "lore-secreto" in r.text, "el admin tampoco ve las relaciones: el panel no las pinta"
