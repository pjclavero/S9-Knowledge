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
_ENV_KEYS = (
    "S9K_GRAPH_PROVIDER", "S9K_AUTH_ENABLED", "S9K_SESSION_SECURE",
    "S9K_AUTH_DB_PATH",
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
    assert classify_provider_declaration() == PROVIDER_NOT_CONFIGURED


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
        assert "DEMO" not in r.text
        assert "no configurada" not in r.text.lower()
