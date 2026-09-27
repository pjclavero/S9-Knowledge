# -*- coding: utf-8 -*-
"""RESOLVEDOR UNICO DE NOMBRES HUMANOS — CORTE 6B-1.

## LA PROPIEDAD

La identidad interna (`workspace = ws-cofradia`, `partida_id = mesa1`) sigue
siendo la que gobierna URL, API, campos ocultos y JSON: **esto no cambia, y no
es el objetivo de este corte**. Lo que cambia es que la SUPERFICIE DE OPERADOR
puede pintar, en su lugar, un nombre humano — sin derivarlo del identificador
y sin crear una segunda autoridad capaz de divergir de la primera.

## EL FALLBACK

    label explicito -> se muestra el label
    label ausente    -> se muestra el IDENTIFICADOR CANONICO
    nunca            -> se inventa un nombre a partir del identificador

Generar «Mesa1» a partir de `partida:mesa1` esta PROHIBIDO: seria la misma
falsa confirmacion que el programa lleva un mes eliminando, con otra cara.

## DONDE VIVE EL LABEL (diagnosticado antes de este corte, no rediseñado aqui)

  - **Workspace**: en `metadata.label`, dentro del `perfil-operador.json` de
    la carpeta de juego que declara ese workspace. `metadata` es el bloque que
    el propio contrato declara abierto (EXCEPCION DOCUMENTADA a
    `additionalProperties: false`), y un label ahi VALIDA: en el primer nivel
    del perfil, no.
  - **Partida**: en `metadata.label`, dentro de
    `<juego>/partidas/<p>/manifiesto-partida.json` — la MISMA exencion de
    lista blanca que ya tiene `perfil-operador.json`
    (`sources_catalog._NO_SON_FUENTES`). NO en `partida_access`: ahi el label
    seria una fila por usuario, y la deduplicacion de
    `existencia.partidas_seleccionables` se queda con la PRIMERA fila que
    llegue — una segunda autoridad que puede divergir de si misma por azar de
    ordenacion.

NO hay tabla `partidas(id, nombre)`. Seria la segunda autoridad que este corte
existe para evitar.

## LA ESCRITURA NO ENTRA AQUI (6B-2)

Nadie escribe estos ficheros desde el producto hoy: el operador los edita a
mano. Un escritor de boveda (atomicidad, concurrencia, permisos, auditoria) es
6B-2. Este modulo SOLO LEE.

## EL NEGATIVO QUE MAS IMPORTA — AMBITO, NO SOLO FORMATO

El corte #254 cerro la propiedad: todo camino que recibe una identidad del
cliente la resuelve de nuevo desde la autoridad del servidor, dentro del
AMBITO AUTORIZADO de quien pregunta. Un resolvedor de labels que conteste
"¿como se llama `ws-ajeno`?" a quien no tiene ese ambito es la MISMA fuga con
otra cara — y ademas confirma que `ws-ajeno` existe, aunque no diga su nombre.

Por eso las dos funciones publicas de este modulo EXIGEN el ambito autorizado
de quien pregunta (`ambito_permitido`) como argumento, y lo comprueban ANTES
de tocar el disco:

    workspace fuera de `ambito_permitido` -> se devuelve el identificador,
    EXACTAMENTE la misma respuesta que "no hay label" dentro de ambito. No hay
    una tercera respuesta que distinga "no tiene label" de "no tienes acceso":
    esa distincion YA ES la fuga.

## UN UNICO RESOLVEDOR

Las superficies de presentacion NO implementan cada una su propia conversion
identificador -> nombre. Todas llaman a `etiqueta_workspace` /
`etiqueta_partida` (instaladas como globals de Jinja, ver
`install_label_globals`). Sesenta conversiones locales serian sesenta
autoridades; el AST de la suite de calibracion lo comprueba.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import FrozenSet, Iterable, Optional

from app import sources_catalog

#: Nombres de los globals de Jinja instalados por `install_label_globals`.
GLOBAL_ETIQUETA_WORKSPACE = "etiqueta_workspace"
GLOBAL_ETIQUETA_PARTIDA = "etiqueta_partida"


def _normaliza_ambito(ambito_permitido: Optional[Iterable[object]]) -> FrozenSet[str]:
    """El conjunto de workspaces que quien pregunta puede ver. Nunca None."""
    if not ambito_permitido:
        return frozenset()
    return frozenset(
        w.strip() for w in ambito_permitido if isinstance(w, str) and w.strip()
    )


def _leer_json_objeto(ruta: Path) -> Optional[dict]:
    """El contenido de `ruta` como objeto JSON, o `None` si no se puede leer.

    Cualquier fallo (ausente, ilegible, JSON invalido, no es un objeto) cae en
    `None`: aqui no hay autoridad que perder por no encontrar un manifiesto,
    solo el fallback al identificador.
    """
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _label_declarado(datos: dict) -> str:
    """`metadata.label` si es una cadena no vacia; si no, `""`.

    NUNCA se deriva de otro campo. Un `label` en el primer nivel del objeto
    (fuera de `metadata`) se ignora a proposito: no es donde el contrato
    declaro la excepcion de lista blanca.
    """
    metadata = datos.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    label = metadata.get("label")
    return label.strip() if isinstance(label, str) and label.strip() else ""


def _carpeta_de_juego(workspace: str, env: Optional[dict] = None) -> Optional[Path]:
    """La carpeta de boveda cuyo `perfil-operador.json` declara `workspace`.

    Reutiliza los resolvedores de rutas de `sources_catalog` (los mismos que
    alimentan el ambito real de una fuente): no re-deriva ninguna ruta, para
    no abrir una segunda lectura de "donde esta la boveda de este workspace".
    """
    raiz = sources_catalog.raiz_de_bovedas(env)
    if raiz is not None:
        try:
            carpetas = sorted(p for p in raiz.iterdir() if p.is_dir())
        except OSError:
            return None
        for carpeta in carpetas:
            perfil = carpeta / sources_catalog.NOMBRE_PERFIL
            try:
                ws = sources_catalog._workspace_declarado(perfil)
            except Exception:
                continue
            if ws == workspace:
                return carpeta
        return None

    if not sources_catalog.ubicacion_declarada(env):
        # Sin boveda declarada, el perfil que hubiera bajo `examples/` es
        # material del repositorio: no declara nada, ni aqui ni en la ingesta.
        return None

    plano = sources_catalog.directorio_de_fuentes(env)
    perfil = plano / sources_catalog.NOMBRE_PERFIL
    try:
        ws = sources_catalog._workspace_declarado(perfil)
    except Exception:
        return None
    return plano if ws == workspace else None


def etiqueta_workspace(
    workspace: Optional[str],
    ambito_permitido: Optional[Iterable[object]],
    env: Optional[dict] = None,
) -> str:
    """El nombre humano de `workspace`, o el propio `workspace` si no hay uno.

    Devuelve SIEMPRE el mismo identificador de entrada cuando:
      - `workspace` esta vacio o no es una cadena;
      - `workspace` NO esta en `ambito_permitido` (fuera de ambito: la misma
        respuesta que "no tiene label", nunca una tercera que confirme
        existencia);
      - no hay perfil de boveda legible para ese workspace;
      - el perfil no declara `metadata.label`.
    """
    if not isinstance(workspace, str) or not workspace.strip():
        return workspace or ""
    workspace = workspace.strip()

    if workspace not in _normaliza_ambito(ambito_permitido):
        return workspace

    carpeta = _carpeta_de_juego(workspace, env)
    if carpeta is None:
        return workspace

    datos = _leer_json_objeto(carpeta / sources_catalog.NOMBRE_PERFIL)
    if datos is None:
        return workspace

    return _label_declarado(datos) or workspace


def etiqueta_partida(
    workspace: Optional[str],
    partida_id: Optional[str],
    ambito_permitido: Optional[Iterable[object]],
    env: Optional[dict] = None,
) -> str:
    """El nombre humano de `(workspace, partida_id)`, o `partida_id` si no hay.

    Mismo contrato de ambito que `etiqueta_workspace`: `workspace` fuera de
    `ambito_permitido` devuelve `partida_id` tal cual, sin distinguir "no
    tiene label" de "no tienes acceso a ese workspace".
    """
    if not isinstance(partida_id, str) or not partida_id.strip():
        return partida_id or ""
    partida_id = partida_id.strip()

    if not isinstance(workspace, str) or not workspace.strip():
        return partida_id
    workspace = workspace.strip()

    if workspace not in _normaliza_ambito(ambito_permitido):
        return partida_id

    carpeta = _carpeta_de_juego(workspace, env)
    if carpeta is None:
        return partida_id

    manifiesto = (
        carpeta / "partidas" / partida_id / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    )
    datos = _leer_json_objeto(manifiesto)
    if datos is None:
        return partida_id

    return _label_declarado(datos) or partida_id


def install_label_globals(envs: Iterable) -> None:
    """Instala `etiqueta_workspace`/`etiqueta_partida` en cada entorno Jinja.

    Igual patron que `chassis.install_nav_globals`: cada router trae su propia
    `Jinja2Templates`, y un global puesto solo en el entorno de `main` dejaria
    a la mitad de las pantallas pintando el identificador crudo en vez de
    llamar al resolvedor unico.
    """
    for env in envs:
        env.globals[GLOBAL_ETIQUETA_WORKSPACE] = etiqueta_workspace
        env.globals[GLOBAL_ETIQUETA_PARTIDA] = etiqueta_partida
