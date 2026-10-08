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

AUTORIDAD ÚNICA — se le pregunta al PROVEEDOR VIVO
--------------------------------------------------
La primera versión de este módulo releía la DECLARACIÓN
(`classify_provider_declaration`) en cada petición, mientras el proveedor se
construye UNA sola vez (`app.deps.get_provider` es `@lru_cache`). Eran dos
lecturas independientes de la misma pregunta —"¿qué estoy sirviendo?"— y
divergían de verdad: con `mock` declarado al arrancar y la declaración
RETIRADA EN CALIENTE, sin reiniciar, la pantalla decía «Base de conocimiento
no configurada» Y SEGUÍA SIRVIENDO las 11 entidades de muestra, sin marca
DEMO. Una falsa confirmación más fuerte que la que este corte vino a cerrar.

Ahora el aviso se deriva del objeto que efectivamente atiende las lecturas:
`app.deps.get_provider().name`. Esa es la MISMA fuente que publica
`/api/status` (`provider.name`), así que pantalla y API no pueden discrepar.
La declaración sigue siendo la autoridad de UN SOLO sitio —la fábrica
(`build_provider`), que es quien la consulta para decidir qué instanciar—, y
el aviso ya no la relee: describe el proveedor, no la intención.
"""
from __future__ import annotations

from typing import Iterable

from app.providers import (
    PROVIDER_MOCK_DEMO,
    PROVIDER_NEO4J,
    PROVIDER_NOT_CONFIGURED,
    estado_del_proveedor_vivo,
)
from app.providers.not_configured_provider import MENSAJE_NO_CONFIGURADO

#: Nombre del global instalado en cada entorno Jinja.
GLOBAL_ESTADO_PROVEEDOR = "estado_proveedor"


def resolver_estado_proveedor() -> dict:
    """Estado honesto de lo que el visor ESTÁ SIRVIENDO ahora mismo.

    No relee `S9K_GRAPH_PROVIDER`: le pregunta al proveedor vivo (ver el
    docstring del módulo). Consecuencia declarada y deliberada: el proveedor
    queda FIJADO al arrancar el proceso, así que un cambio de `.env` en
    caliente no mueve ni los datos ni el aviso —ambos a la vez— y el operador
    necesita reiniciar para que el cambio tenga efecto. Eso es exactamente lo
    que se quiere: el cartel describe el proveedor que atiende las lecturas,
    nunca una intención que el proceso todavía no ha recogido.
    """
    estado = estado_del_proveedor_vivo()
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
