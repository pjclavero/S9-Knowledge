# -*- coding: utf-8 -*-
"""Identidad durable de PROCEDENCIA DEL APPLY: quien creo que.

EL PROBLEMA QUE CIERRA
----------------------
Un rollback no debe borrar «todo lo que encuentre dentro de la fuente o del
workspace». Debe saber que creo REALMENTE el apply que esta revirtiendo. La
propiedad que se exige es literal::

    apply X    -> posee EXACTAMENTE el conjunto PX
    rollback X -> puede eliminar PX, salvo lo compartido todavia vivo
               -> NO puede eliminar P-noX

Hasta aqui el producto no podia expresar esa frase. El barrido de procedencia
(`rollback.add_provenance_sweep`) llevaba ``scope: "run"`` y la lista entera de
fragmentos de la corrida, asi que revertir un apply que solo creo UNA arista
barria los 6 episodios y las 6 evidencias que ese apply NO creo. Nada vivo se
perdia --la guarda de cero referencias vivas retiene lo compartido-- pero la
fuente dejaba de ser navegable: la ``V3Source`` se quedaba con 1 de 7
episodios. El radio era la corrida; tenia que ser la operacion.

POR QUE NO VALE `elementId`
---------------------------
`elementId` contiene el UUID de la base y se regenera al restaurar un dump: una
identidad de propiedad basada en el deja de identificar justo cuando hace falta
--durante una recuperacion--. Ademas es opaco: dos bases distintas dan valores
distintos para el MISMO contenido. La identidad de este modulo es una FUNCION
DEL CONTENIDO: la misma cadena en cualquier base, antes y despues de un restore.

DE QUE SE DERIVA
----------------
De lo que ya identifica durablemente a un apply, y de nada mas:

* ``workspace`` -- mitad de la identidad de producto.
* ``partida_id`` -- el ambito. La AUSENCIA del campo no es lo mismo que `None`:
  `None` es la capa juego y se codifica como tal. (Equipo 5A esta estampando
  `partida_id` aguas arriba; este modulo ya lo consume, y cuando llegue de
  verdad el `apply_id` de dos partidas dejara de coincidir sin tocar nada aqui.)
* ``snapshot_id`` -- sobre que estado se decidio.
* ``plan_hash`` -- QUE se decidio. Dos applies distintos sobre la misma fuente
  llevan planes distintos, luego `plan_hash` distinto, luego `apply_id`
  distinto. Y un REPLAY del mismo plan da el mismo `apply_id`, que es lo
  correcto: un replay es un no-op y no crea nada que poseer.

QUE ES Y QUE NO ES
------------------
Es una MARCA DE CREACION, no una marca de uso. Se estampa en el `CREATE` y
solo ahi: un nodo de procedencia que un apply posterior REUTILIZA conserva el
`apply_id` de quien lo creo. Por eso la marca contesta «quien lo creo» y no
«quien lo toco», que es exactamente la pregunta que el rollback necesita.

NO es un gate: no impide ninguna escritura ni ningun borrado. Es la propiedad
por la que el borrado se ACOTA. La condicion de borrado sigue siendo la de
siempre --cero referencias vivas, DENTRO del propio `DELETE`-- y no se relaja:
la propiedad ESTRECHA el conjunto candidato, nunca lo amplia.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

#: Propiedad que lleva la marca en los nodos de procedencia. Nombre estable:
#: aparece en el grafo, en los documentos de rollback y en las actas.
APPLY_ID_FIELD = "apply_id"

#: Prefijo legible. Un valor de este campo se reconoce a simple vista y no se
#: puede confundir con un `elementId`, que es justamente lo que no queremos.
APPLY_ID_PREFIX = "apply:"

#: Longitud del resumen. 32 hex = 128 bits: de sobra para que dos applies
#: distintos no colisionen, y corto para que quepa en un acta legible.
_DIGEST_LEN = 32

#: Codificacion del ambito AUSENTE frente al ambito `None`. `None` es la capa
#: juego --un ambito concreto--; la ausencia es «no se declaro». Si los dos se
#: codificaran igual, dos applies de ambitos distintos compartirian `apply_id`.
_SIN_PARTIDA = "\x00partida:capa-juego"
_PARTIDA_AUSENTE = "\x00partida:ausente"

_AUSENTE = object()


def _campo(valor: Any) -> str:
    """Un campo del resumen, sin ambiguedad de separadores.

    Cada campo va precedido de su longitud: sin eso, ``("ab", "c")`` y
    ``("a", "bc")`` producirian la misma cadena y, por tanto, el mismo
    `apply_id` para dos applies distintos.
    """
    texto = "" if valor is None else str(valor)
    return f"{len(texto)}:{texto}"


def compute_apply_id(
    *,
    workspace: str,
    snapshot_id: str,
    plan_hash: str,
    partida_id: Any = _AUSENTE,
) -> str:
    """`apply_id` durable de un apply. Determinista y sin `elementId`.

    Exige las tres piezas que identifican la decision. Falta alguna -> se
    niega a inventar una identidad: una marca de propiedad vacia autorizaria
    despues a borrar por una propiedad que no distingue nada.
    """
    faltan = [
        nombre
        for nombre, valor in (
            ("workspace", workspace),
            ("snapshot_id", snapshot_id),
            ("plan_hash", plan_hash),
        )
        if not (isinstance(valor, str) and valor.strip())
    ]
    if faltan:
        raise ValueError(
            f"apply_id: faltan {faltan}; sin identidad completa del apply no se "
            "estampa propiedad (una marca vacia no distingue nada)"
        )
    if partida_id is _AUSENTE:
        ambito = _PARTIDA_AUSENTE
    elif partida_id is None:
        ambito = _SIN_PARTIDA
    elif isinstance(partida_id, str) and partida_id.strip():
        ambito = partida_id
    else:
        raise ValueError(
            f"apply_id: 'partida_id' malformado ({partida_id!r}); ambito "
            "incoherente no produce identidad"
        )
    material = "".join(
        _campo(v) for v in (workspace, ambito, snapshot_id, plan_hash)
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:_DIGEST_LEN]
    return f"{APPLY_ID_PREFIX}{digest}"


def is_apply_id(valor: Any) -> bool:
    """Forma admisible de un `apply_id`. Se comprueba, no se presume."""
    return (
        isinstance(valor, str)
        and valor.startswith(APPLY_ID_PREFIX)
        and len(valor) == len(APPLY_ID_PREFIX) + _DIGEST_LEN
        and all(c in "0123456789abcdef" for c in valor[len(APPLY_ID_PREFIX):])
    )


def require_apply_id(valor: Any, *, contexto: str) -> str:
    """`apply_id` con forma admisible, o excepcion. Fail-closed.

    Se usa en el camino de reversion: un documento que dice poseer algo con una
    marca malformada no autoriza a borrar nada.
    """
    if not is_apply_id(valor):
        raise ValueError(
            f"{contexto}: {APPLY_ID_FIELD}={valor!r} no tiene forma admisible; "
            "sin propiedad declarada no se borra"
        )
    return valor


def apply_id_for_view(view: Any, *, partida_id: Any = _AUSENTE) -> Optional[str]:
    """`apply_id` de un `SignedView`, o `None` si el view no lo permite.

    Devuelve `None` en vez de lanzar porque hay caminos --simulaciones, planes
    sin snapshot-- en los que no hay apply que poseer nada. Quien reciba `None`
    debe tratarlo como «este apply no estampa propiedad», nunca como comodin.
    """
    if partida_id is _AUSENTE:
        partida_id = getattr(view, "partida_id", _AUSENTE)
    try:
        return compute_apply_id(
            workspace=getattr(view, "workspace", "") or "",
            snapshot_id=getattr(view, "snapshot_id", "") or "",
            plan_hash=getattr(view, "plan_hash_value", "") or "",
            partida_id=partida_id,
        )
    except ValueError:
        return None


__all__ = [
    "APPLY_ID_FIELD",
    "APPLY_ID_PREFIX",
    "apply_id_for_view",
    "compute_apply_id",
    "is_apply_id",
    "require_apply_id",
]
