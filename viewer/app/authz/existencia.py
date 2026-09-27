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
    # RONDA 3: la autoridad es el PERFIL DE LA BOVEDA, no el entorno.
    #
    # Este es el otro extremo del mismo hueco que `authz/dependencies.py`:
    # mientras esto leyera el entorno, `/admin/partidas` seguia ofreciendo un
    # workspace distinto de aquel donde acaba el conocimiento, y conceder
    # acceso al workspace real devolvia 400.
    #
    # La unidad de control del Corte 1 NO cambia: sigue habiendo UN workspace
    # canonico y sigue siendo comparacion exacta. Lo que cambia es quien lo
    # declara. Y `""` (sin autoridad resoluble) sigue significando DENEGAR.
    from app.authz import autoridad_workspace  # noqa: PLC0415

    return autoridad_workspace.resolver_por_peticion().valor


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


def partidas_seleccionables(conn: sqlite3.Connection, user, workspace: Optional[str]) -> list:
    """¿Qué partidas puede ELEGIR `user` ahora mismo, en `workspace`?

    S1. Antes de esta función el selector de `base.html` se pintaba con
    ``auth_db.list_partida_access(conn, user_id=user.id)`` -- SIN filtrar por
    workspace -- mientras ``/partida/select`` autorizaba con
    ``user_allowed_partidas(..., workspace=canónico)``. El resultado medido:
    una concesión hecha en un workspace ajeno al canónico seguía apareciendo en
    el selector, y elegirla daba 403 ("No tienes asignada esa partida").

    Esta función es la ÚNICA respuesta a "¿qué puede elegir este usuario?":
    tanto pintar el selector (`AuthMiddleware`) como decidir si aceptar una
    elección (`routers.partida.select_partida`) pasan por aquí. Una segunda
    interpretación paralela de la misma pregunta es exactamente la divergencia
    que este corte cierra -- no se repite.

    Sin workspace efectivo determinable (fail-closed, igual que el resto de
    este módulo): ninguna partida es seleccionable.

    Un admin no tiene por qué tener concesiones propias (`admin_full`), pero
    tampoco puede fijar una partida inventada -- ver `partida_existe` -- así
    que su lista es la de partidas que EXISTEN canónicamente en el workspace
    (concedidas a cualquier usuario), no solo las suyas. Deduplicada por
    `partida_id`: la misma partida puede estar concedida a varios usuarios y
    el selector pinta una opción por partida, no por fila de concesión.
    """
    if not workspace or not isinstance(workspace, str) or not workspace.strip():
        return []
    from app.auth import db as auth_db

    ws = workspace.strip()
    if getattr(user, "is_admin", None) is not None and user.is_admin():
        filas = auth_db.list_partida_access(conn, workspace=ws)
    else:
        filas = auth_db.list_partida_access(conn, user_id=user.id, workspace=ws)

    vistas: set[str] = set()
    resultado = []
    for fila in filas:
        if fila.partida_id in vistas:
            continue
        vistas.add(fila.partida_id)
        resultado.append(fila)
    return resultado
