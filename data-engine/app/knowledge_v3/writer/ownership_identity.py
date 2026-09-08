# -*- coding: utf-8 -*-
"""`ownership_id`: propiedad DURABLE de los efectos de un apply.

QUE PROBLEMA CIERRA
-------------------
`apply_identity.compute_apply_id` deriva de `plan_hash`. Y `plan_hash` cubre el
documento entero salvo a si mismo, incluidos `created_at` y `expires_at`, que
son RELOJ. Consecuencia MEDIDA (dos procesos, mismo apply logico, unico cambio
el instante inyectado con `--ahora`)::

    created_at     CAMBIA
    expires_at     CAMBIA
    plan_hash      CAMBIA
    decision_hash  CAMBIA      <- tambien: `expires_at` esta DENTRO de
                                  DECISION_HASH_FIELDS
    apply_id       CAMBIA      <- hereda el reloj via plan_hash
    ---------------------------------------------------------------
    workspace      IGUAL
    snapshot_id    IGUAL
    idempotency_key de cada operacion   IGUAL

Por eso `apply_id` es identidad de INTENTO (`attempt`), no de propiedad: el
mismo apply logico reejecutado --o replanificado tras un restore-- produce otro
`apply_id`, y la clasificacion del rollback que se apoya en el deja de
reconocer lo que ella misma creo.

DE DONDE SALE LA AUTORIDAD (derivado del contrato, no elegido a gusto)
---------------------------------------------------------------------
No vale cualquier campo estable. Hace falta un campo estable QUE EL WRITER
PUEDA USAR COMO AUTORIDAD. El contrato congelado y `writer/view.py` acotan ese
conjunto:

* `view.py` (`UNSIGNED_FIELDS`) deja fuera `created_at`, `plan_id`,
  `provider_trace` y `metadata`: *«No es que no deban leerlos: es que no los
  tienen.»* `plan_id` es estable --lo confirma la medida-- pero esta
  EXPLICITAMENTE excluido de lo que el writer puede tomar por autoridad, asi
  que no es candidato.
* `mutation_operations` SI esta en `DECISION_HASH_FIELDS`
  (`contracts/knowledge-v3/v1/validator.py`): esta sellado y llega al
  `SignedView`.
* `IDEMPOTENCY_KEY_FIELDS` es la declaracion que el propio contrato hace de la
  IDENTIDAD LOGICA de una operacion: *«Campos que definen la IDENTIDAD LOGICA
  de una operacion. `operation_id` NO esta: la misma operacion calculada en dos
  planes distintos debe producir la misma clave de idempotencia.»* Es
  exactamente la propiedad que la propiedad de los efectos necesita.
* Y esa clave no se cree por que venga escrita: `writer/admission.py` la
  RE-DERIVA y la compara operacion por operacion, rechazando el plan con
  `PLAN_IDEMPOTENCY_KEY_UNDERIVED` si alguna no deriva de su operacion. Es
  decir: el writer ya trata la `idempotency_key` como autoridad verificada
  fail-closed, al contrario que `plan_id`.

De ahi el material de este modulo, y de nada mas:

    workspace   + ambito(partida_id) + snapshot_id
                + el CONJUNTO de idempotency_key de las operaciones del apply

Ninguna de esas piezas es reloj, ninguna lleva el UUID de la base, y todas
estan selladas o son re-derivables por el writer.

QUE NO ES
---------
* NO es `elementId`: eso lleva el UUID de la base y se regenera al restaurar.
* NO es `plan_id`: estable, pero excluido a proposito de la autoridad del
  writer. Este modulo no lo lee ni lo recibe.
* NO es un gate. No impide ninguna escritura ni ningun borrado. Igual que
  `apply_id`, ESTRECHA el conjunto candidato del rollback; nunca lo amplia. La
  condicion de cero referencias vivas sigue viviendo DENTRO del `DELETE`
  atomico y no se relaja aqui.

RELACION CON `apply_id`
-----------------------
Conviven, y cada uno contesta a su pregunta::

    attempt_id (= apply_id)  -> que INTENTO concreto escribio esto
    ownership_id             -> a que apply LOGICO pertenecen los efectos
    plan_id                  -> identidad documental existente, NO autoridad

`apply_id` se conserva tal cual: es util en auditoria para distinguir dos
intentos. Lo que cambia es que la PROPIEDAD deja de apoyarse en el.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional

#: Propiedad que lleva la marca en los nodos y en `V3AppliedOperation`.
OWNERSHIP_ID_FIELD = "ownership_id"

#: Prefijo legible, distinto del de `apply_id` para que un acta no los confunda.
OWNERSHIP_ID_PREFIX = "own:"

_DIGEST_LEN = 32

#: Misma codificacion de ambito que `apply_identity`: la AUSENCIA del campo no
#: es lo mismo que `None`. `None` es la capa juego --un ambito concreto--; la
#: ausencia es «no se declaro». Si los dos se codificaran igual, dos applies de
#: ambitos distintos compartirian `ownership_id`.
_SIN_PARTIDA = "\x00partida:capa-juego"
_PARTIDA_AUSENTE = "\x00partida:ausente"

_AUSENTE = object()


def _campo(valor: Any) -> str:
    """Un campo del resumen, precedido de su longitud.

    Sin el prefijo de longitud, ``("ab", "c")`` y ``("a", "bc")`` producirian
    la misma cadena y, por tanto, el mismo `ownership_id` para dos applies
    distintos.
    """
    texto = "" if valor is None else str(valor)
    return f"{len(texto)}:{texto}"


def compute_ownership_id(
    *,
    workspace: str,
    snapshot_id: str,
    idempotency_keys: Iterable[str],
    partida_id: Any = _AUSENTE,
) -> str:
    """`ownership_id` durable. Determinista, sin reloj y sin `elementId`.

    `idempotency_keys` se ORDENA: el conjunto de operaciones de un apply es un
    conjunto, no una lista. Si el orden entrase, replanificar el mismo apply
    con las operaciones emitidas en otro orden daria otra propiedad.

    Falta alguna pieza -> se niega a inventar identidad. Una marca de propiedad
    vacia autorizaria despues a borrar por una propiedad que no distingue nada.
    """
    faltan = [
        nombre
        for nombre, valor in (("workspace", workspace), ("snapshot_id", snapshot_id))
        if not (isinstance(valor, str) and valor.strip())
    ]
    if faltan:
        raise ValueError(
            f"ownership_id: faltan {faltan}; sin identidad completa del apply no "
            "se estampa propiedad (una marca vacia no distingue nada)"
        )

    claves = sorted(idempotency_keys)
    if not claves:
        raise ValueError(
            "ownership_id: el apply no declara ninguna operacion; un apply que "
            "no crea nada no posee nada, y una propiedad vacia igualaria a "
            "todos los applies vacios entre si"
        )
    if not all(isinstance(k, str) and k.strip() for k in claves):
        raise ValueError(
            "ownership_id: hay idempotency_key vacias o no textuales; la "
            "identidad logica de la operacion no es opcional"
        )

    if partida_id is _AUSENTE:
        ambito = _PARTIDA_AUSENTE
    elif partida_id is None:
        ambito = _SIN_PARTIDA
    elif isinstance(partida_id, str) and partida_id.strip():
        ambito = partida_id
    else:
        raise ValueError(
            f"ownership_id: 'partida_id' malformado ({partida_id!r}); ambito "
            "incoherente no produce identidad"
        )

    material = "".join(
        _campo(v) for v in (workspace, ambito, snapshot_id, str(len(claves)), *claves)
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:_DIGEST_LEN]
    return f"{OWNERSHIP_ID_PREFIX}{digest}"


def is_ownership_id(valor: Any) -> bool:
    """Forma admisible de un `ownership_id`. Se comprueba, no se presume."""
    return (
        isinstance(valor, str)
        and valor.startswith(OWNERSHIP_ID_PREFIX)
        and len(valor) == len(OWNERSHIP_ID_PREFIX) + _DIGEST_LEN
        and all(c in "0123456789abcdef" for c in valor[len(OWNERSHIP_ID_PREFIX):])
    )


def require_ownership_id(valor: Any, *, contexto: str) -> str:
    """`ownership_id` con forma admisible, o excepcion. Fail-closed.

    Se usa en el camino de reversion: un documento que dice poseer algo con una
    marca malformada no autoriza a borrar nada.
    """
    if not is_ownership_id(valor):
        raise ValueError(
            f"{contexto}: {OWNERSHIP_ID_FIELD}={valor!r} no tiene forma "
            "admisible; sin propiedad declarada no se borra"
        )
    return valor


def ownership_id_for_view(view: Any, *, partida_id: Any = _AUSENTE) -> Optional[str]:
    """`ownership_id` de un `SignedView`, o `None` si el view no lo permite.

    Devuelve `None` en vez de lanzar porque hay caminos --simulaciones, planes
    sin operaciones-- en los que no hay apply que posea nada. Quien reciba
    `None` debe tratarlo como «este apply no estampa propiedad», nunca como
    comodin.

    Solo lee campos que el `SignedView` tiene; por construccion, ninguno de los
    `UNSIGNED_FIELDS` esta a su alcance.
    """
    if partida_id is _AUSENTE:
        partida_id = getattr(view, "partida_id", _AUSENTE)
    operaciones = getattr(view, "mutation_operations", ()) or ()
    try:
        claves = [op["idempotency_key"] for op in operaciones]
    except (TypeError, KeyError):
        return None
    try:
        return compute_ownership_id(
            workspace=getattr(view, "workspace", "") or "",
            snapshot_id=getattr(view, "snapshot_id", "") or "",
            idempotency_keys=claves,
            partida_id=partida_id,
        )
    except ValueError:
        return None


__all__ = [
    "OWNERSHIP_ID_FIELD",
    "OWNERSHIP_ID_PREFIX",
    "compute_ownership_id",
    "is_ownership_id",
    "ownership_id_for_view",
    "require_ownership_id",
]
