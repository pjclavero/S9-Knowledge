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
`classify_provider_declaration` tiene UN solo consumidor en producto:
`build_provider`, que es quien decide qué objeto se instancia. El aviso de
pantalla NO la llama —preguntaría por segunda vez lo que el proveedor ya
sabe—: se deriva del proveedor vivo con `estado_del_proveedor_vivo`. Dos
lecturas independientes de la misma pregunta son exactamente el patrón de
defecto que el resto del repo (ver `app/config.py::effective_env_value`)
existe para eliminar, y aquí la pregunta operativa no es "qué se declaró"
sino "qué estoy sirviendo": su única autoridad es el objeto que sirve.
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

#: Cuarto estado, SÓLO del proveedor VIVO (`estado_del_proveedor_vivo`), nunca
#: de la declaración: `S9K_GRAPH_PROVIDER` SÍ está declarado (neo4j o mock),
#: pero `build_provider` no pudo construir el objeto (p. ej. `neo4j`
#: declarado sin el driver instalado). "No declarado" y "declarado pero
#: roto" son situaciones distintas con acciones distintas para quien
#: administra —instalar algo nuevo, frente a revisar lo que ya instaló— y
#: fusionarlas bajo `PROVIDER_NOT_CONFIGURED` le pide reconfigurar lo que ya
#: configuró.
PROVIDER_DECLARED_UNAVAILABLE = "declared_unavailable"


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


def estado_de_proveedor(provider: GraphProvider) -> str:
    """Clasifica un proveedor YA CONSTRUIDO por lo que es, no por lo que se
    declaró. `name` es la identidad que el propio proveedor publica y que
    `/api/status` ya expone; `PolicyFilteredProvider` la proxya tal cual, así
    que envolver el proveedor no cambia la respuesta.

    Fail-closed: un `name` que no sea `mock` ni `neo4j` (incluido
    `not_configured` y cualquier proveedor futuro que no se reconozca aquí)
    se trata como NO configurado. Nunca al contrario: un desconocido no puede
    degradar en silencio a "sírvelo como si fuera real".
    """
    nombre = (getattr(provider, "name", "") or "").strip().lower()
    if nombre == PROVIDER_NEO4J:
        return PROVIDER_NEO4J
    if nombre == PROVIDER_MOCK_DEMO:
        return PROVIDER_MOCK_DEMO
    return PROVIDER_NOT_CONFIGURED


def estado_del_proveedor_vivo() -> str:
    """Estado del proveedor que ESTÁ atendiendo las lecturas de este proceso.

    Importa `app.deps` dentro de la función a propósito: `app.deps` importa
    este módulo, y hacerlo arriba cerraría el ciclo.

    Si `build_provider` no puede construir el objeto (p. ej. `neo4j`
    declarado sin su driver instalado), el proceso no está sirviendo NADA de
    ese proveedor. Esto NO se informa como "no configurado": la declaración
    SÍ existe, lo que falta es que el proceso pueda usarla, y eso exige una
    acción distinta de quien administra (revisar la instalación, no
    reconfigurar lo que ya configuró) — ver `PROVIDER_DECLARED_UNAVAILABLE`.

    Alcance real de esta función, medido (PR-2, ronda de revisión O1b): SÓLO
    cubre las pantallas que renderizan el partial de `base.html` sin pasar
    antes por el camino de datos del grafo (hoy `/graph` y `/reviews`). Las
    pantallas que SÍ llaman a `get_provider()` en su propio camino de datos
    (`/`, `/entities`, `/sources`, `/quality`) y `/api/status` vuelven a
    lanzar la MISMA excepción fuera de este `try` y dan 500 igual: esta
    función nunca ha evitado ese 500, sólo evita que la franja del aviso
    AÑADA un segundo fallo a una pantalla que de todos modos iba a dar 500.
    Ese 500 es preexistente a PR-2 (`build_provider` ya lanzaba antes de este
    corte) y queda fuera de su alcance.
    """
    from app.deps import get_provider

    try:
        return estado_de_proveedor(get_provider())
    except Exception:
        if classify_provider_declaration() != PROVIDER_NOT_CONFIGURED:
            return PROVIDER_DECLARED_UNAVAILABLE
        return PROVIDER_NOT_CONFIGURED


__all__ = [
    "build_provider",
    "estado_de_proveedor",
    "estado_del_proveedor_vivo",
    "GraphProvider",
    "classify_provider_declaration",
    "PROVIDER_NOT_CONFIGURED",
    "PROVIDER_MOCK_DEMO",
    "PROVIDER_NEO4J",
    "PROVIDER_DECLARED_UNAVAILABLE",
]
