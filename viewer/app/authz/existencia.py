"""EXISTENCIA CANÓNICA DE UNA PARTIDA — el único sitio que lo decide.

CORTE 1. Antes de este módulo había TRES criterios repartidos:

  - `routers/admin.py`      : ninguno. El formulario aceptaba los tres campos
                              de ámbito como texto libre y `grant_partida_access`
                              escribía la fila. Conceder ERA crear existencia.
  - `routers/partida.py`    : `partida_exists(conn, partida_id)`, agnóstico de
                              workspace, más un `workspace` resuelto aparte.
  - `authz/dependencies.py` : lo mismo, resuelto otra vez por su cuenta.

El defecto medido: `partida_exists` hacía
``SELECT 1 FROM partida_access WHERE partida_id = ?`` SIN filtrar por workspace,
de modo que una concesión en un workspace inventado convertía ese `partida_id`
en «partida existente» para TODO el despliegue, incluido el workspace real. Y el
formulario, al no validar nada, era la forma de fabricar esa concesión.

LA UNIDAD DE CONTROL (decisión del operador, no se rediseña aquí):

    partida existente  !=  existe ese partida_id en algún sitio
    partida existente  ==  (workspace, partida_id) existe CANÓNICAMENTE

## Qué es «canónicamente», medido y dicho en voz alta

**La existencia canónica de una partida NO está representada en ninguna parte
de este producto.** Es un hallazgo, no una omisión de este módulo, y conviene
que quede escrito donde se decide, porque cualquiera que lea este fichero va a
suponer lo contrario:

  1. No hay tabla `partidas`, ni catálogo, ni registro. `auth/db.py` sólo tiene
     `users`, `sessions`, `audit_events`, `partida_access` y `schema_version`.
  2. No hay etiqueta `:Partida` en el grafo. `partida_id` es una PROPIEDAD de
     cadena sobre los nodos (`providers/neo4j_provider.py`), y `GraphProvider`
     expone `workspaces()` pero no `partidas()`: nadie la enumera nunca.
  3. El perfil de bóveda (`sources_catalog.py`) declara UN workspace por
     carpeta de juego y no lista partidas.
  4. Lo más parecido a un censo es el árbol de la bóveda: `vault_scope.py`
     deriva la partida del nombre de carpeta bajo `<juego>/partidas/<partida>/`
     y su propio comentario la llama «la única autoridad» — pero sólo para la
     ruta que se está mirando. No se puede preguntar «¿qué partidas hay?».

Tres sitios sin reconciliar, y ninguno consultable como censo. Por eso este
módulo NO inventa un almacén nuevo (haría falta elevarlo): se limita a **aplicar
la unidad de control sobre lo que ya hay**, que es exactamente lo que el
docstring de `partida_exists` prometía y el formulario desarmaba.

## Lo que sí se puede afirmar con lo que hay

`S9K_DEFAULT_WORKSPACE` es el ÚNICO workspace que este despliegue sabe resolver:
es el que usan `routers/partida.py` para autorizar a un jugador, el que usa
`authz/dependencies.py` en la re-verificación por petición, y el único elemento
de `allowed_workspaces` en el contexto de visibilidad. Un `workspace` distinto
no es «otro ámbito»: es un ámbito que ningún consumidor puede alcanzar. Escribir
concesiones ahí sólo produce filas muertas que el panel enseña como vivas —
falsa confirmación — y, antes de este corte, existencia para el ámbito real.

De modo que:

  - **workspace canónico** = el workspace efectivo del despliegue. Medible.
  - **partida canónica**   = par `(workspace_canónico, partida_id)` con al menos
                             una concesión. Sigue siendo el censo derivado de
                             concesiones — no hay otro — pero ya no es global.

## Lo que este módulo NO arregla, y hay que decirlo

Sin censo, **conceder una partida inventada sigue creándola** dentro del
workspace canónico: un error tipográfico en el campo «Partida» del panel es
indistinguible de una partida nueva legítima. Eso NO se puede cerrar sin una
fuente de verdad que hoy no existe. Lo que este corte cierra es el cruce entre
ámbitos y la fabricación de ámbitos: una concesión ya no puede inventar un
workspace, ni teñir de existencia a un workspace que no es el suyo.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def workspace_canonico() -> str:
    """El único workspace que este despliegue sabe resolver, o `""`.

    Devuelve cadena vacía cuando no es determinable, y todos los llamantes
    tratan eso como DENEGAR (fail-closed), igual que ya hacía
    `_still_has_access`: sin ámbito efectivo no se concede acceso.
    """
    from app.config import get_settings

    ws = get_settings().S9K_DEFAULT_WORKSPACE
    return ws.strip() if isinstance(ws, str) and ws.strip() else ""


def es_workspace_canonico(workspace: Optional[str]) -> bool:
    """¿Es `workspace` EL workspace del despliegue?

    Comparación exacta contra el valor efectivo, tras recortar espacios. No hay
    normalización de alias a propósito: `juego:leyenda` y `leyenda` son ámbitos
    distintos para todo el resto del código, y fingir aquí que son el mismo
    crearía una equivalencia que ningún otro consumidor respeta.
    """
    canonico = workspace_canonico()
    if not canonico:
        return False
    if not isinstance(workspace, str) or not workspace.strip():
        return False
    return workspace.strip() == canonico


def partida_existe(
    conn: sqlite3.Connection, workspace: Optional[str], partida_id: Optional[str]
) -> bool:
    """¿Existe CANÓNICAMENTE la partida `(workspace, partida_id)`?

    Dos condiciones, y las dos hacen falta:

      1. `workspace` es el workspace canónico del despliegue. Un workspace
         inventado no contiene partidas: no contiene nada, porque no existe.
      2. Hay al menos una concesión para ESE par en `partida_access`.

    Este es el único punto del producto que responde a la pregunta. Sus tres
    consumidores —conceder, activar y re-verificar— pasan por aquí.
    """
    if not es_workspace_canonico(workspace):
        return False
    from app.auth import db as auth_db

    return auth_db.partida_exists(conn, workspace.strip(), partida_id)
