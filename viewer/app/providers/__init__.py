"""Fábrica de proveedores de grafo, seleccionada por S9K_GRAPH_PROVIDER.

PR-2 (USABLE-V1): antes de este corte, no declarar `S9K_GRAPH_PROVIDER` caía
en `mock` en silencio (el default de `Settings`, pensado para que un `python
-m pytest` sin `.env` no abortara). Eso convertía "nadie ha configurado esta
instalación" en "aquí tienes 11 entidades de muestra sin ninguna marca",
que es la falsa confirmación que este corte cierra.

``classify_provider_declaration`` es la ÚNICA autoridad sobre qué significa
el valor de `S9K_GRAPH_PROVIDER`, y lee con `effective_env_value` — NUNCA con
`settings.S9K_GRAPH_PROVIDER`, cuyo valor siempre es una cadena (el default
de pydantic) y no puede distinguir "no declarado" de "declarado = mock".
Tanto `build_provider` (qué proveedor se instancia) como los globals de
plantilla que pintan el aviso DEMO/no-configurado (`app.provider_banner`)
llaman a esta misma función: dos lecturas independientes de la misma
pregunta son exactamente el patrón de defecto que el resto del repo (ver
`app/config.py::effective_env_value`) existe para eliminar.
"""
from __future__ import annotations

from pathlib import Path

from app.config import Settings, effective_env_value
from app.providers.base import GraphProvider
from app.providers.mock_provider import MockGraphProvider
from app.providers.not_configured_provider import NotConfiguredGraphProvider

#: Los tres estados posibles de la declaración. "unknown" (valor presente
#: pero que no es ni "mock" ni "neo4j", p.ej. una errata) se trata como
#: "not_configured": fail-closed. Aceptar cualquier cadena no reconocida como
#: si fuera "mock" sería la misma falsa confirmación con otra cara —una
#: errata de tecleo no puede degradar en silencio a "sírveme datos de
#: muestra como si fueran reales".
PROVIDER_NOT_CONFIGURED = "not_configured"
PROVIDER_MOCK_DEMO = "mock"
PROVIDER_NEO4J = "neo4j"


def classify_provider_declaration(raw: str | None = None) -> str:
    """Clasifica la declaración EFECTIVA de `S9K_GRAPH_PROVIDER`.

    ``raw`` se acepta como parámetro sólo para los tests que quieren fijar el
    valor sin tocar el entorno; en producto, SIEMPRE se llama sin argumento y
    se lee de `effective_env_value` (entorno > `.env` > nada), igual
    precedencia que el resto del visor.
    """
    if raw is None:
        raw = effective_env_value("S9K_GRAPH_PROVIDER")
    valor = (raw or "").strip().lower()
    if valor == PROVIDER_NEO4J:
        return PROVIDER_NEO4J
    if valor == PROVIDER_MOCK_DEMO:
        return PROVIDER_MOCK_DEMO
    return PROVIDER_NOT_CONFIGURED


def build_provider(settings: Settings) -> GraphProvider:
    estado = classify_provider_declaration()

    if estado == PROVIDER_NEO4J:
        from app.providers.neo4j_provider import Neo4jGraphProvider

        return Neo4jGraphProvider(
            uri=settings.S9K_NEO4J_URI,
            user=settings.S9K_NEO4J_USER,
            password=settings.neo4j_password,
        )

    if estado == PROVIDER_MOCK_DEMO:
        sample_path = Path(settings.S9K_SAMPLE_GRAPH_PATH)
        if not sample_path.is_absolute():
            sample_path = Path(__file__).resolve().parents[2] / sample_path
        return MockGraphProvider(sample_path)

    # PROVIDER_NOT_CONFIGURED: de fábrica no se sirve ni un dato mock.
    return NotConfiguredGraphProvider()


__all__ = [
    "build_provider",
    "GraphProvider",
    "classify_provider_declaration",
    "PROVIDER_NOT_CONFIGURED",
    "PROVIDER_MOCK_DEMO",
    "PROVIDER_NEO4J",
]
