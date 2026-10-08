"""Aviso honesto del estado del proveedor de grafo, en TODA plantilla.

PR-2 (USABLE-V1). Antes de este corte, una instalación de fábrica sin
`S9K_GRAPH_PROVIDER` declarado servía 11 entidades y 2 fuentes inventadas en
`/entities` y `/sources`, sin ninguna marca de que fueran de muestra. La
decisión del operador exige dos cosas simétricas:

  - proveedor no configurado -> estado vacío y honesto, en TODA pantalla que
    toque el grafo, no sólo en las dos que el defecto midió.
  - `mock` explícito (modo DEMO) -> sigue sirviendo datos, pero marcado
    INEQUÍVOCAMENTE como DEMO en la propia pantalla.

Mismo patrón que `app.presentacion_etiquetas.install_label_globals` y
`app.chassis.install_nav_globals`: un global de Jinja instalado en TODOS los
entornos de plantillas descubiertos, para que ninguna pantalla nazca muda.
Se resuelve con la MISMA autoridad que decide qué proveedor se instancia
(`app.providers.classify_provider_declaration`) — nunca una segunda lectura
de `S9K_GRAPH_PROVIDER` que podría divergir de la que ya usó la fábrica.
"""
from __future__ import annotations

from typing import Iterable

from app.providers import (
    PROVIDER_MOCK_DEMO,
    PROVIDER_NEO4J,
    PROVIDER_NOT_CONFIGURED,
    classify_provider_declaration,
)
from app.providers.not_configured_provider import MENSAJE_NO_CONFIGURADO

#: Nombre del global instalado en cada entorno Jinja.
GLOBAL_ESTADO_PROVEEDOR = "estado_proveedor"


def resolver_estado_proveedor() -> dict:
    """Estado honesto del proveedor, SIN caché: un operador que edita `.env`
    y reinicia debe ver el cambio en la propia pantalla, igual criterio que
    `app.config.effective_env_value` (releer es una lectura de fichero
    pequeña en el camino de una petición HTTP local, no un coste real)."""
    estado = classify_provider_declaration()
    return {
        "configurado": estado != PROVIDER_NOT_CONFIGURED,
        "demo": estado == PROVIDER_MOCK_DEMO,
        "neo4j": estado == PROVIDER_NEO4J,
        "mensaje_no_configurado": MENSAJE_NO_CONFIGURADO,
    }


def _global_estado_proveedor() -> dict:
    """`{{ estado_proveedor() }}` — sin argumentos: no depende de la petición,
    sólo de la configuración del proceso."""
    return resolver_estado_proveedor()


def install_provider_banner_globals(envs: Iterable) -> None:
    """Instala el global en cada entorno Jinja descubierto (ver `main.py`)."""
    for env in envs:
        env.globals[GLOBAL_ESTADO_PROVEEDOR] = _global_estado_proveedor


__all__ = [
    "install_provider_banner_globals",
    "resolver_estado_proveedor",
    "GLOBAL_ESTADO_PROVEEDOR",
]
