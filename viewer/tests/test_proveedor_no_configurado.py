"""PR-2 (USABLE-V1): «proveedor no configurado -> estado vacío y honesto».

El defecto medido (segunda falsa confirmación de producto, justo detrás de
PR-1): `S9K_GRAPH_PROVIDER` sin declarar caía en `mock` EN SILENCIO, y una
instalación recién hecha mostraba 11 entidades y 2 fuentes INVENTADAS en
`/entities` y `/sources`, sin ninguna marca de que eran muestra.

Decisión del operador, cerrada:

    proveedor real no configurado -> ESTADO VACÍO Y HONESTO
    mock                          -> SÓLO con modo DEMO explícito, marcado

Cada test tiene su mutación correspondiente en
`scripts/calibracion/mutaciones_proveedor_no_configurado.py`, referenciada
por NOMBRE.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

#: También se limpian las que usa `_admin_client`: un test que deja
#: `S9K_AUTH_ENABLED=true` puesto (y sobre todo `get_auth_settings` sin
#: volver a limpiar su caché) filtraría al siguiente test, que cree estar
#: probando el camino anónimo.
#: `S9K_NEO4J_URI` está en la lista porque
#: `test_neo4j_no_configurado_...` la pone con `setdefault`: sin restaurarla,
#: quedaba puesta para el RESTO de la sesión de pytest. Es exactamente la
#: familia de fuga que este corte vino a limpiar en los otros cinco ficheros
#: de la suite, y una fuga de una línea cuenta igual que una de veinte.
_ENV_KEYS = (
    "S9K_GRAPH_PROVIDER", "S9K_AUTH_ENABLED", "S9K_SESSION_SECURE",
    "S9K_AUTH_DB_PATH", "S9K_NEO4J_URI",
)


def _limpiar_singletons_de_proveedor() -> None:
    """`app.deps.get_provider` es `@lru_cache`: UN proveedor para todo el
    proceso, a propósito (es el singleton de producción — igual criterio que
    `get_settings`, que exige reiniciar el proceso para recoger un cambio de
    `.env`). En esta suite, donde un mismo proceso de pytest ejercita a
    propósito varias declaraciones de `S9K_GRAPH_PROVIDER`, hay que vaciar la
    caché cada vez o el segundo escenario sigue viendo el proveedor del
    primero aunque el entorno ya diga otra cosa."""
    from app.deps import get_provider
    get_provider.cache_clear()
    from app.config import get_settings
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _entorno_proveedor_limpio():
    """Esta suite decide su propio `S9K_GRAPH_PROVIDER` caso a caso: no debe
    heredar el `setdefault("mock")` global de `tests/conftest.py`."""
    previos = {k: os.environ.get(k) for k in _ENV_KEYS}
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    _limpiar_singletons_de_proveedor()
    yield
    for k, v in previos.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _limpiar_singletons_de_proveedor()
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()


def _client():
    from starlette.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _csrf_de(html: str) -> str:
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "la pantalla no trae csrf_token"
    return m.group(1)


@contextmanager
def _admin_client(tmp_path):
    """Cliente autenticado como ADMIN: bypassa el filtro de visibilidad, así
    que es el único que puede afirmar "ninguna entidad inventada" sin que la
    propia política de autorización anónima enmascare el resultado (un
    anónimo, en este producto, no ve NINGUNA entidad de la muestra ni con el
    defecto puesto ni sin él — no discrimina nada).

    Es un CONTEXT MANAGER, no un valor suelto: dos `TestClient` abiertos sin
    cerrar en el mismo proceso de pytest (misma `app` global) dejaban al
    SEGUNDO admin —sesión y cookie nuevas, pero mismo proceso— viendo 0
    entidades con un proveedor `mock` que sí tenía datos: el primer cliente,
    sin `__exit__`, no liberaba el estado de lifespan/sesión que el segundo
    necesitaba. Cerrar cada cliente con `with` antes de abrir el siguiente
    es lo que evita esa fuga entre tests.
    """
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    _limpiar_singletons_de_proveedor()
    with _client() as c:
        r = c.get("/setup/admin")
        csrf = _csrf_de(r.text)
        r2 = c.post(
            "/setup/admin",
            data={
                "username": "admin", "display_name": "Admin",
                "password": "SuperSecreta_1234567890!",
                "password_confirm": "SuperSecreta_1234567890!",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert r2.status_code == 303, r2.text
        rl = c.get("/login")
        csrf2 = _csrf_de(rl.text)
        rlp = c.post(
            "/login",
            data={"username": "admin", "password": "SuperSecreta_1234567890!",
                  "csrf_token": csrf2, "next": "/"},
            follow_redirects=False,
        )
        assert rlp.status_code == 302, rlp.text
        yield c
    get_auth_settings.cache_clear()


def _settings_sin_cache():
    from app.config import get_settings
    get_settings.cache_clear()
    return get_settings()


# ---------------------------------------------------------------------------
# 1) La autoridad de clasificación
# ---------------------------------------------------------------------------

def test_sin_declarar_clasifica_como_no_configurado():
    from app.providers import PROVIDER_NOT_CONFIGURED, classify_provider_declaration
    assert classify_provider_declaration() == PROVIDER_NOT_CONFIGURED, (
        "sin declaración efectiva de proveedor, la clasificación debe ser "
        "not_configured: caer en mock es la falsa confirmación original"
    )


def test_valor_desconocido_tambien_es_no_configurado():
    """Una errata (`"mok"`, `"Neo4J"` con mayúscula atípica no reconocida tal
    cual, etc.) NO degrada a mock: fail-closed, no "lo que no entiendo, lo
    sirvo como demo"."""
    from app.providers import PROVIDER_NOT_CONFIGURED, classify_provider_declaration
    assert classify_provider_declaration("algo-mal-escrito") == PROVIDER_NOT_CONFIGURED


def test_mock_explicito_clasifica_como_demo():
    from app.providers import PROVIDER_MOCK_DEMO, classify_provider_declaration
    assert classify_provider_declaration("mock") == PROVIDER_MOCK_DEMO


def test_neo4j_explicito_clasifica_como_neo4j():
    from app.providers import PROVIDER_NEO4J, classify_provider_declaration
    assert classify_provider_declaration("neo4j") == PROVIDER_NEO4J


def test_build_provider_sin_declarar_no_es_mock():
    """La fábrica real, no sólo el clasificador: `build_provider` no debe
    devolver `MockGraphProvider` cuando nadie declaró el proveedor."""
    from app.providers import build_provider
    from app.providers.not_configured_provider import NotConfiguredGraphProvider
    settings = _settings_sin_cache()
    provider = build_provider(settings)
    assert isinstance(provider, NotConfiguredGraphProvider)
    assert provider.name == "not_configured"
    assert provider.is_connected() is False


# ---------------------------------------------------------------------------
# 2) El NEGATIVO decisivo: ninguna entidad inventada en ninguna superficie
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/entities", "/sources", "/quality", "/status", "/"])
def test_sin_proveedor_ninguna_entidad_inventada(ruta, tmp_path):
    """Las cinco superficies que consumen el proveedor NO deben traer el
    nombre de ninguna entidad de muestra (`examples/sample_graph.json`)
    cuando el proveedor no está configurado — ni siquiera para un ADMIN, que
    es el rol que SÍ vería la muestra entera si el proveedor mock estuviera
    activo (confirmado en `test_demo_explicito_admin_ve_la_muestra_marcada_demo`)."""
    with _admin_client(tmp_path) as c:
        r = c.get(ruta)
        assert r.status_code in (200, 503), f"{ruta} -> {r.status_code} inesperado"
        assert "Agasha Tamori" not in r.text
        assert "Togashi Mitsu" not in r.text


def test_api_entities_sin_proveedor_no_trae_entidades(tmp_path):
    with _admin_client(tmp_path) as c:
        r = c.get("/api/entities")
        assert r.status_code == 200
        assert r.json()["items"] == []


def test_api_sources_sin_proveedor_no_trae_fuentes(tmp_path):
    with _admin_client(tmp_path) as c:
        r = c.get("/api/sources")
        assert r.status_code == 200
        assert r.json()["sources"] == []


# ---------------------------------------------------------------------------
# 3) Estado vacío != error: ni 500, ni un cuerpo de fallo
# ---------------------------------------------------------------------------

def test_sin_proveedor_entities_responde_200_no_500():
    os.environ["S9K_AUTH_ENABLED"] = "false"
    with _client() as c:
        r = c.get("/entities")
        assert r.status_code == 200, (
            "una instalación sin proveedor no está rota: no debe dar 500."
        )


def test_sin_proveedor_mensaje_honesto_sin_nombrar_variables_s9k():
    """El mensaje visible dice algo humano y NO nombra ninguna variable
    `S9K_*`: quien lo lee no tiene por qué saber el nombre interno."""
    os.environ["S9K_AUTH_ENABLED"] = "false"
    with _client() as c:
        r = c.get("/entities")
        assert "no configurada" in r.text.lower()
        assert "S9K_" not in r.text


def test_sin_proveedor_api_status_dice_la_causa():
    os.environ["S9K_AUTH_ENABLED"] = "false"
    with _client() as c:
        cuerpo = c.get("/api/status").json()
        assert cuerpo["provider"] == "not_configured"
        assert cuerpo["nodes"] == 0
        assert cuerpo["relationships"] == 0


# ---------------------------------------------------------------------------
# 4) El modo DEMO explícito: sigue funcionando, marcado sin ambigüedad
# ---------------------------------------------------------------------------

def test_demo_explicito_sirve_datos_de_muestra():
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    from app.providers import build_provider
    settings = _settings_sin_cache()
    provider = build_provider(settings)
    items, total = provider.list_entities("leyenda")
    assert total > 0, "el modo DEMO explícito debe seguir sirviendo la muestra"


def test_demo_explicito_se_marca_en_la_pantalla():
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    os.environ["S9K_AUTH_ENABLED"] = "false"
    _limpiar_singletons_de_proveedor()
    with _client() as c:
        r = c.get("/")
        assert "DEMO" in r.text, "el modo DEMO debe marcarse en la propia pantalla"


def test_demo_explicito_admin_ve_la_muestra_marcada_demo(tmp_path):
    """La prueba E2E completa: con `S9K_GRAPH_PROVIDER=mock`, la entidad de
    muestra SÍ aparece (el modo DEMO sigue funcionando) Y la pantalla la
    acompaña de la marca DEMO — las dos cosas a la vez, nunca una sin la
    otra."""
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    with _admin_client(tmp_path) as c:
        r = c.get("/entities")
        assert "Agasha Tamori" in r.text, (
            "el modo DEMO explícito debe seguir sirviendo la muestra a quien "
            "puede verla"
        )
        assert "DEMO" in r.text, (
            "la muestra no puede aparecer sin su marca DEMO en la misma pantalla"
        )


def test_sin_proveedor_no_se_marca_como_demo():
    """El simétrico: sin proveedor, NO aparece la marca DEMO (no hay nada que
    demostrar) — sólo el aviso de no configurado."""
    os.environ["S9K_AUTH_ENABLED"] = "false"
    with _client() as c:
        r = c.get("/")
        assert "DEMO" not in r.text


def test_neo4j_no_configurado_no_se_marca_ni_como_demo_ni_como_no_configurado():
    """Con proveedor real declarado, ninguno de los dos avisos se pinta — el
    simétrico de siempre: ningún cartel cuando no hace falta ninguno."""
    os.environ["S9K_GRAPH_PROVIDER"] = "neo4j"
    os.environ["S9K_AUTH_ENABLED"] = "false"
    os.environ.setdefault("S9K_NEO4J_URI", "bolt://127.0.0.1:7687")
    _limpiar_singletons_de_proveedor()
    with _client() as c:
        r = c.get("/")
        assert "DEMO" not in r.text, (
            "con proveedor real declarado no se pinta la marca DEMO: ningún "
            "cartel cuando no hace falta ninguno"
        )
        assert "no configurada" not in r.text.lower(), (
            "con proveedor real declarado NO se pinta el aviso de no "
            "configurada: ningún cartel cuando no hace falta ninguno"
        )


# ---------------------------------------------------------------------------
# 5) UNA SOLA AUTORIDAD sobre "qué estoy sirviendo" (O1 de la revisión)
# ---------------------------------------------------------------------------
#
# El defecto medido en la primera versión de este corte: el aviso releía la
# DECLARACIÓN en cada petición y el proveedor se construía UNA vez
# (`@lru_cache`). Retirando la declaración EN CALIENTE, sin reiniciar, la
# pantalla decía «Base de conocimiento no configurada» Y SEGUÍA SIRVIENDO las
# 11 entidades de muestra, sin marca DEMO: una falsa confirmación MÁS FUERTE
# que la que este corte cierra. Estos testigos la fijan.

def test_aviso_y_datos_no_discrepan_al_quitar_la_declaracion_en_caliente(tmp_path):
    """EL testigo de la divergencia. Arranca con `mock`, hace una petición
    (que construye y CACHEA el proveedor), retira `S9K_GRAPH_PROVIDER` SIN
    vaciar ninguna caché —exactamente lo que pasa cuando alguien edita el
    entorno de un proceso vivo— y vuelve a pedir la pantalla.

    La propiedad no es "qué cartel sale", es que el cartel y los datos
    cuenten LA MISMA historia: si en la pantalla hay entidades de muestra,
    tiene que llevar la marca DEMO y NO puede decir que no hay nada
    configurado.
    """
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    with _admin_client(tmp_path) as c:
        r0 = c.get("/entities")
        assert "Agasha Tamori" in r0.text, "preparación: el modo DEMO debe servir la muestra"
        assert "DEMO" in r0.text, "preparación: la muestra debe llegar marcada DEMO"

        # --- la declaración se retira EN CALIENTE, sin reiniciar nada ---
        os.environ.pop("S9K_GRAPH_PROVIDER", None)
        r1 = c.get("/entities")

        sirve_muestra = "Agasha Tamori" in r1.text
        dice_no_configurada = "no configurada" in r1.text.lower()
        marca_demo = "DEMO" in r1.text

        assert not (sirve_muestra and dice_no_configurada), (
            "DIVERGENCIA DE AUTORIDADES: la pantalla dice «no configurada» "
            "mientras SIRVE entidades de muestra. El aviso y los datos deben "
            "salir de la misma autoridad (el proveedor vivo), no de dos "
            "lecturas independientes de la declaración."
        )
        assert not (sirve_muestra and not marca_demo), (
            "DIVERGENCIA DE AUTORIDADES: se sirven entidades de muestra SIN "
            "marca DEMO. El aviso debe derivarse del proveedor que atiende "
            "las lecturas."
        )


def test_el_aviso_se_deriva_del_proveedor_vivo_no_de_la_declaracion():
    """El mismo invariante a la altura de la función, sin HTTP: el estado que
    pinta el aviso coincide SIEMPRE con el proveedor que `app.deps` entrega,
    incluso cuando la declaración ya dice otra cosa."""
    from app.deps import get_provider
    from app.provider_banner import resolver_estado_proveedor
    from app.providers import PROVIDER_MOCK_DEMO, estado_de_proveedor

    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    _limpiar_singletons_de_proveedor()
    assert estado_de_proveedor(get_provider()) == PROVIDER_MOCK_DEMO

    os.environ.pop("S9K_GRAPH_PROVIDER", None)  # en caliente, sin vaciar cachés
    estado = resolver_estado_proveedor()
    vivo = estado_de_proveedor(get_provider())
    assert estado["demo"] is (vivo == PROVIDER_MOCK_DEMO), (
        "DIVERGENCIA DE AUTORIDADES: el aviso debe describir el PROVEEDOR "
        f"VIVO; aquí describe la declaración (aviso={estado}, vivo={vivo})"
    )
    assert estado["configurado"] is True, (
        "DIVERGENCIA DE AUTORIDADES: el proveedor vivo sigue sirviendo la "
        "muestra, el aviso no puede declarar la instalación sin configurar"
    )


def test_la_autoridad_de_la_declaracion_es_la_efectiva_no_el_default_de_settings():
    """`settings.S9K_GRAPH_PROVIDER` SIEMPRE trae una cadena (el default de
    pydantic, `mock`) y no puede distinguir "no declarado" de "declarado =
    mock". Si la fábrica volviera a leer de ahí, toda la clase de defecto
    regresaría de golpe."""
    from app.providers import PROVIDER_NOT_CONFIGURED, classify_provider_declaration

    settings = _settings_sin_cache()
    assert settings.S9K_GRAPH_PROVIDER, (
        "preparación: el default de Settings debe ser una cadena no vacía, "
        "que es justo lo que lo hace inservible como autoridad"
    )
    assert classify_provider_declaration() == PROVIDER_NOT_CONFIGURED, (
        "la autoridad debe ser la declaración EFECTIVA (entorno > .env), no "
        "el default de Settings: ese default no distingue 'no declarado' de "
        "'declarado = mock'"
    )


# ---------------------------------------------------------------------------
# 6) Las API que sirven datos del proveedor DICEN en qué modo están (O2)
# ---------------------------------------------------------------------------

_APIS_CON_DATOS_DEL_PROVEEDOR = ("/api/entities?limit=1000", "/api/graph")


@pytest.mark.parametrize("ruta", _APIS_CON_DATOS_DEL_PROVEEDOR)
def test_api_declara_el_modo_demo_en_su_propia_respuesta(ruta, tmp_path):
    """Las 12 superficies HTML llevan la marca, pero `/api/entities` y
    `/api/graph` devolvían las entidades inventadas SIN ninguna marca en el
    JSON: un consumidor necesitaba una SEGUNDA llamada a `/api/status` para
    saber que eran de muestra. La respuesta que trae los datos debe decir en
    qué modo está, con la MISMA clave y el MISMO valor que `/api/status`."""
    os.environ["S9K_GRAPH_PROVIDER"] = "mock"
    with _admin_client(tmp_path) as c:
        cuerpo = c.get(ruta).json()
        declarado_en_status = c.get("/api/status").json()["provider"]
        assert cuerpo.get("provider") == "mock", (
            f"{ruta} sirve datos de muestra sin declarar el modo en su propia "
            f"respuesta: provider={cuerpo.get('provider')!r}"
        )
        assert cuerpo.get("provider") == declarado_en_status, (
            f"{ruta} y /api/status no coinciden en el modo publicado: "
            f"{cuerpo.get('provider')!r} vs {declarado_en_status!r}"
        )


@pytest.mark.parametrize("ruta", _APIS_CON_DATOS_DEL_PROVEEDOR)
def test_api_declara_el_modo_no_configurado_en_su_propia_respuesta(ruta, tmp_path):
    with _admin_client(tmp_path) as c:
        cuerpo = c.get(ruta).json()
        assert cuerpo.get("provider") == "not_configured", (
            f"{ruta} debe declarar 'not_configured' en su propia respuesta, "
            f"no obligar a una segunda llamada: {cuerpo.get('provider')!r}"
        )


# ---------------------------------------------------------------------------
# 7) LOS 13 MÉTODOS DEL CONTRATO: ninguno lanza, todos vacíos (O3)
# ---------------------------------------------------------------------------
#
# El recorrido se DERIVA de `GraphProvider` (inspección de la clase), no de
# una lista escrita a mano: cuando el contrato crezca, el método nuevo entra
# en el recorrido por construcción. TECHO DECLARADO: si un método nuevo trae
# un parámetro obligatorio cuyo tipo no se sabe sintetizar, el testigo FALLA
# en voz alta (`_valor_para_parametro` lanza) en vez de saltárselo en
# silencio; y el recorrido comprueba AUSENCIA de datos y AUSENCIA de
# excepción, no la semántica de cada método.

def _metodos_del_contrato() -> dict:
    """Métodos públicos que `GraphProvider` define como su contrato de
    lectura, abstractos o no (`list_assertions` no es abstracto a propósito,
    ver `app/providers/base.py`)."""
    import inspect

    from app.providers.base import GraphProvider

    metodos = {}
    for nombre, miembro in inspect.getmembers(GraphProvider, predicate=inspect.isfunction):
        if nombre.startswith("_"):
            continue
        metodos[nombre] = miembro
    return metodos


def _valor_para_parametro(nombre: str, anotacion) -> object:
    texto = str(anotacion)
    if "str" in texto:
        return "" if nombre == "q" else "ninguno"
    if "int" in texto:
        return 1
    if "float" in texto:
        return 0.5
    if "bool" in texto:
        return False
    raise AssertionError(
        "TECHO DEL RECORRIDO: el contrato trae un parámetro obligatorio que "
        f"este testigo no sabe sintetizar ({nombre}: {anotacion!r}). "
        "Amplía `_valor_para_parametro` — no lo saltes: un método sin "
        "recorrer es un método sin defensa."
    )


def _sin_datos(valor, ruta: str) -> list[str]:
    """Hallazgos (lista vacía = honesto). Un `dict` es honesto si TODA hoja
    numérica vale 0 y TODA hoja de colección está vacía; las hojas de texto
    se admiten porque son etiquetas o ecos del argumento (p. ej. la clave
    `workspace` de `quality_metrics`), nunca datos del grafo."""
    hallazgos: list[str] = []
    if valor is None:
        return hallazgos
    if isinstance(valor, bool):
        if valor is not False:
            hallazgos.append(f"{ruta}: True (sin proveedor nada esta conectado)")
        return hallazgos
    if isinstance(valor, int):
        if valor != 0:
            hallazgos.append(f"{ruta}: {valor} (se esperaba 0)")
        return hallazgos
    if isinstance(valor, str):
        return hallazgos
    if isinstance(valor, (list, set, frozenset)):
        if len(valor) != 0:
            hallazgos.append(f"{ruta}: {len(valor)} elementos (se esperaba vacio)")
        return hallazgos
    if isinstance(valor, tuple):
        for i, v in enumerate(valor):
            hallazgos += _sin_datos(v, f"{ruta}[{i}]")
        return hallazgos
    if isinstance(valor, dict):
        for k, v in valor.items():
            hallazgos += _sin_datos(v, f"{ruta}.{k}")
        return hallazgos
    hallazgos.append(f"{ruta}: tipo inesperado {type(valor).__name__}")
    return hallazgos


def test_los_13_metodos_del_contrato_no_lanzan_y_devuelven_vacio():
    """`NotConfiguredGraphProvider` existe para garantizar VACÍO, NO
    EXCEPCIÓN. Antes de este testigo sólo tres métodos (`is_connected`,
    `graph`, `list_entities`) estaban defendidos: con `quality_metrics` o
    `source_detail` lanzando, la suite entera del visor daba CERO rojos, y
    esos métodos SÍ se ejercitan en producto (`/sources` y `/quality`)."""
    import inspect

    from app.providers.not_configured_provider import NotConfiguredGraphProvider

    provider = NotConfiguredGraphProvider()
    contrato = _metodos_del_contrato()
    assert len(contrato) == 13, (
        "el contrato de `GraphProvider` ha cambiado de tamaño "
        f"({len(contrato)} métodos, antes 13). No es un fallo del proveedor: "
        "revisa que el método nuevo esté defendido y actualiza este número."
    )

    lanzaron: list[str] = []
    con_datos: list[str] = []
    for nombre, funcion in sorted(contrato.items()):
        firma = inspect.signature(funcion)
        kwargs = {}
        for pnombre, p in firma.parameters.items():
            if pnombre == "self" or p.default is not inspect.Parameter.empty:
                continue
            kwargs[pnombre] = _valor_para_parametro(pnombre, p.annotation)
        try:
            resultado = getattr(provider, nombre)(**kwargs)
        except Exception as exc:
            lanzaron.append(f"{nombre}: {type(exc).__name__}: {exc}")
            continue
        con_datos += _sin_datos(resultado, nombre)

    assert not lanzaron, (
        "NINGUN METODO DEL CONTRATO PUEDE LANZAR sin proveedor configurado "
        "-una instalacion sin configurar no esta rota, esta sin "
        f"configurar-: {lanzaron}"
    )
    assert not con_datos, (
        "TODOS LOS METODOS DEL CONTRATO DEBEN DEVOLVER VACIO sin proveedor "
        f"configurado: {con_datos}"
    )
