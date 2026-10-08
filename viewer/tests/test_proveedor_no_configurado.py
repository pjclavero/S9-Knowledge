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

import pytest

_ENV_KEYS = ("S9K_GRAPH_PROVIDER",)


@pytest.fixture(autouse=True)
def _entorno_proveedor_limpio():
    """Esta suite decide su propio `S9K_GRAPH_PROVIDER` caso a caso: no debe
    heredar el `setdefault("mock")` global de `tests/conftest.py`."""
    previos = {k: os.environ.get(k) for k in _ENV_KEYS}
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    yield
    for k, v in previos.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _client():
    from starlette.testclient import TestClient
    from app.main import app
    return TestClient(app)


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
def test_sin_proveedor_ninguna_entidad_inventada(ruta):
    """Las cinco superficies que consumen el proveedor NO deben traer el
    nombre de ninguna entidad de muestra (`examples/sample_graph.json`)
    cuando el proveedor no está configurado."""
    os.environ["S9K_AUTH_ENABLED"] = "false"
    with _client() as c:
        r = c.get(ruta)
        assert r.status_code in (200, 503), f"{ruta} -> {r.status_code} inesperado"
        assert "Agasha Tamori" not in r.text
        assert "Clan Dragón" not in r.text


def test_api_entities_sin_proveedor_no_trae_entidades():
    os.environ["S9K_AUTH_ENABLED"] = "false"
    with _client() as c:
        r = c.get("/api/entities")
        assert r.status_code == 200
        assert r.json()["items"] == []


def test_api_sources_sin_proveedor_no_trae_fuentes():
    os.environ["S9K_AUTH_ENABLED"] = "false"
    with _client() as c:
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
    with _client() as c:
        r = c.get("/")
        assert "DEMO" in r.text, "el modo DEMO debe marcarse en la propia pantalla"


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
    with _client() as c:
        r = c.get("/")
        assert "DEMO" not in r.text
        assert "no configurada" not in r.text.lower()
