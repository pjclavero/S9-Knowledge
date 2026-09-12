# -*- coding: utf-8 -*-
"""El `state_hash` de un nodo: UNA definicion, y recomputable desde el grafo.

QUE EXIGE EL CONTRATO CONGELADO
-------------------------------
`graph-mutation-plan-v3.schema.json` declara `expected_version` y
`expected_hash` como "null SOLO en creaciones", y el validador congelado lo
hace cumplir: toda operacion que no crea y no los trae se rechaza con
*"modifica algo existente sin expected_version/expected_hash"*. `SnapshotEntity`
dice de donde salen ("son los que el plan copia a `expected_version` /
`expected_hash`") y `Neo4jReadOnlyGraphSnapshot` cierra el circulo en su
clausula 3: el grafo debe DEVOLVER `version` y `state_hash` por nodo.

De ahi el contrato real, que es mas ancho que "escribe un hash al crear":

    una entidad que el producto crea sale del CREATE con TODO el estado
    durable que el planificador y el writer le van a exigir despues.

Si no, la entidad nace incapaz de anclar un control optimista y ninguna
operacion posterior sobre ella puede validar. No es una limitacion del carril
que la crea: es una limitacion de la entidad, para siempre.

POR QUE ESTA DEFINICION Y NO OTRA
---------------------------------
El hash es el estado REALMENTE PERSISTIDO, no un resumen plausible de el:
`sha256` del JSON canonico de las propiedades del nodo, sin el propio
`state_hash`. Dos consecuencias buscadas:

* **se recomputa desde el grafo**: quien lea el nodo puede rehacer el hash y
  comprobar que describe lo que hay. Un hash derivado de `{entity_id, type,
  version}` -- el que usa `SnapshotEntity.of` para los tests -- es plausible y
  FALSO: no cambiaria aunque cambiase el contenido del nodo, y el control
  optimista dejaria pasar el cambio que existe para detectar;
* **cualquier cambio real de estado lo mueve**, que es justo lo que
  `_check_expected_state` necesita comparar.

Se descartan los valores `None` porque Neo4j NO ALMACENA una propiedad nula:
incluirlos daria un hash que el propio grafo no puede reproducir al releerse.
El `sha256` no se reimplementa aqui; se toma del validador congelado.

Formato: en el grafo viaja el HEXADECIMAL desnudo, porque es lo que
`pipeline/graph_catalog.py` ya espera leer (`graph_state_hash`) para envolverlo
en el `{algorithm, value}` del contrato. Envolver o desenvolver es de
`hash_doc` / `hash_value`; nadie mas debe hacerlo a mano.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from ..contracts.base import sha256_hash

#: Nunca entra en el hash: es el propio resultado.
_EXCLUIDAS = frozenset({"state_hash"})


def hashable_props(props: Mapping[str, Any]) -> dict[str, Any]:
    """Lo que de verdad queda escrito en el nodo, y por tanto entra en el hash."""
    return {
        k: v
        for k, v in props.items()
        if k not in _EXCLUIDAS and v is not None
    }


def state_hash_value(props: Mapping[str, Any]) -> str:
    """Hexadecimal del `sha256` del estado persistido de un nodo."""
    return sha256_hash(hashable_props(props))["value"]


def hash_doc(value: Optional[str]) -> Optional[dict[str, str]]:
    """Hexadecimal -> `{algorithm, value}` del contrato. `None` sigue siendo `None`."""
    if value is None:
        return None
    return {"algorithm": "sha256", "value": value}


def hash_value(hash_or_doc: Any) -> Optional[str]:
    """`{algorithm, value}` o hexadecimal -> hexadecimal. Para PODER comparar.

    El plan trae el hash como documento (asi lo exige el contrato) y el grafo
    lo devuelve como cadena. Comparar las dos formas sin normalizar da SIEMPRE
    desigual -- un falso conflicto de concurrencia que ni un cambio real ni su
    ausencia distinguirian. Normalizar NO es relajar: un valor ausente sigue
    siendo ausente, y una forma que no se reconoce se devuelve tal cual para
    que la comparacion la rechace.
    """
    if hash_or_doc is None:
        return None
    if isinstance(hash_or_doc, Mapping):
        return hash_or_doc.get("value")
    return hash_or_doc


__all__ = ["hashable_props", "state_hash_value", "hash_doc", "hash_value"]
