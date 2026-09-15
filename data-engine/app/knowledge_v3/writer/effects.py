# -*- coding: utf-8 -*-
"""QUE EFECTO DECLARA CADA OPERACION, y como se OBSERVA que ocurrio.

EL DEFECTO QUE CIERRA
---------------------
Medido sobre la base de este carril: despues de aplicar, NADIE volvia a mirar
el grafo. El desenlace de un apply se derivaba enteramente de lo que el propio
writer DIJO haber hecho (`WriteResult.applied_operations`, sus rechazos y su
`mode`). Eso contesta a "¿el writer creyo escribir?", no a "¿esta escrito?".

Son preguntas distintas en cuanto hay DOS almacenes y DOS transacciones:

  * el plan se ejecuta en su transaccion;
  * la procedencia se vuelca en OTRA, despues, a proposito
    (`apply.py` paso 3: un fallo de procedencia no puede revertir
    conocimiento ya aceptado);
  * y el estado durable del plan vive en SQLite, en un tercer almacen.

No hay --ni puede haber-- una transaccion ACID unica sobre los tres. La
respuesta a eso NO es fingir atomicidad: es ESTADO EXPLICITO +
RECONCILIACION IDEMPOTENTE. Y para que el estado pueda ser explicito, alguien
tiene que MIRAR. Este modulo es ese alguien.

LA REGLA, TAL Y COMO LA FIJA EL PRODUCTO
----------------------------------------
No toda afirmacion produce una arista. Algunas operaciones materializan una
entidad, otras un atributo, otras un cierre de vigencia. La regla correcta no
es "siempre tiene que haber arista", sino:

    Toda operacion del plan debe producir EXACTAMENTE el efecto materializado
    que declara su TIPO, y ese efecto debe ser TRAZABLE.

`EFECTO_DECLARADO` es esa tabla, enumerada y cerrada. Un tipo de operacion que
no este en ella hace fallar la verificacion con `EFFECT_TYPE_UNDECLARED` en vez
de pasar de largo: un tipo nuevo no se da por bueno por no estar previsto.

COMO SE MIDE (y los tres errores que NO se cometen)
---------------------------------------------------
1. **Una consulta por cosa contada.** Dos `MATCH` sueltos en la misma consulta
   producen el producto cartesiano de dos conjuntos y, si uno esta vacio,
   CERO filas -- que se lee igual que "no esta" aunque lo este. Aqui cada
   efecto tiene su consulta, con su patron encadenado en una sola fila.
2. **Comparacion por IDENTIDAD DURABLE**, nunca por `elementId`: `entity_id`,
   `assertion_id`, `idempotency_key`. El `elementId` se regenera al restaurar
   un dump y no identifica nada.
3. **Ausencia != cero.** Una consulta que no devuelve filas se reporta como
   efecto AUSENTE, con su identidad, no como "0 y seguimos".

ATRIBUCION
----------
Una arista que existe no basta: tiene que ser LA de esta operacion. Todo lo
que el writer escribe lleva estampada la `idempotency_key` de su operacion
(`executor._provenance`), que es la identidad LOGICA de la operacion segun el
contrato congelado. Las aristas se comprueban por esa clave. Asi, una arista
correcta escrita por OTRO plan no pone verde a este.

QUE NO HACE
-----------
No escribe. No abre conexiones. No toca el gate, ni el writer, ni el esquema,
ni el contrato. Recibe un driver ya abierto y el documento del plan que se
aplico, y devuelve lo que vio.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .cypher import LABEL_ASSERTION, LABEL_ENTITY, Query, safe_token
from .provenance import trace_query

#: Un tipo de operacion cuyo efecto este modulo no sabe observar. NO se
#: silencia: un tipo nuevo sin verificador es una propiedad que dejariamos de
#: comprobar sin que nadie lo note, y eso es exactamente el falso exito que
#: este modulo existe para impedir.
CODE_TYPE_UNDECLARED = "EFFECT_TYPE_UNDECLARED"

#: El efecto declarado no aparece en el grafo.
CODE_EFFECT_MISSING = "EFFECT_MISSING"

#: El efecto aparece, pero NO atribuido a esta operacion (otra clave de
#: idempotencia). Atribucion cruzada: se dice aparte porque su causa es otra.
CODE_EFFECT_NOT_ATTRIBUTED = "EFFECT_NOT_ATTRIBUTED"

#: La afirmacion esta escrita y CITA evidencia, pero el recorrido de
#: procedencia no llega desde ella hasta esa evidencia.
CODE_PROVENANCE_UNREACHABLE = "PROVENANCE_UNREACHABLE"

#: Lo que cada tipo de operacion MATERIALIZA, en una frase que el producto
#: puede decir. Tabla CERRADA: ver `CODE_TYPE_UNDECLARED`.
EFECTO_DECLARADO: dict[str, str] = {
    "CREATE_ENTITY": "un nodo de entidad con su identidad durable",
    "CREATE_ASSERTION": "un nodo de afirmacion con su identidad durable",
    "PROJECT_RELATION": "una arista navegable entre las dos entidades",
    "LINK_EXISTING": "una arista navegable entre las dos entidades",
    "SUPERSEDE_ASSERTION": "la afirmacion anterior con su vigencia cerrada",
    "UPDATE_ENTITY": "la entidad con su version avanzada",
}


@dataclass(frozen=True)
class EfectoAusente:
    """Un efecto declarado que NO se observo. Lleva su por que y su identidad."""

    operation_id: str
    operation_type: str
    code: str
    identity: str
    detail: str = ""
    #: Identidades durables concretas que faltan --hoy, los fragmentos de
    #: evidencia que la afirmacion cita y a los que el recorrido no llega--.
    #: Van APARTE del texto a proposito: `detail` es una frase para un humano
    #: y quien tenga que DECIDIR sobre esto no puede hacerlo buscando
    #: subcadenas dentro de una redaccion que manana cambia.
    missing_ids: tuple = ()

    def to_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "code": self.code,
            "identity": self.identity,
            "detail": self.detail,
            "missing_ids": list(self.missing_ids),
        }


@dataclass
class EffectReport:
    """Lo que se VIO al mirar el grafo despues de aplicar."""

    #: Operaciones cuyo efecto declarado SI se observo, por `operation_id`.
    observed: tuple = ()
    #: Efectos declarados que NO se observaron. No vacio = apply PARCIAL.
    missing: tuple = ()
    #: Aserciones cuya evidencia citada no es alcanzable por el recorrido.
    provenance_missing: tuple = ()

    @property
    def complete(self) -> bool:
        """TODO lo declarado esta materializado y es trazable.

        Es la unica condicion bajo la que un apply puede anunciarse como
        exito completo. Se calcula de lo observado, nunca de lo esperado.
        """
        return not self.missing and not self.provenance_missing

    @property
    def codes(self) -> list:
        vistos: list = []
        for ausente in tuple(self.missing) + tuple(self.provenance_missing):
            if ausente.code not in vistos:
                vistos.append(ausente.code)
        return vistos

    def to_dict(self) -> dict:
        return {
            "complete": self.complete,
            "observed": list(self.observed),
            "missing": [m.to_dict() for m in self.missing],
            "provenance_missing": [m.to_dict() for m in self.provenance_missing],
        }


# --- Una consulta POR COSA CONTADA -----------------------------------------
def _nodo(label: str, campo: str, valor: str, workspace: str) -> Query:
    return Query(
        f"MATCH (n:{label} {{{campo}: $id, workspace: $ws}}) "
        f"RETURN n.{campo} AS id, n.idempotency_key AS clave, n.status AS status, "
        "n.version AS version "
        "LIMIT 1",
        {"id": valor, "ws": workspace},
    )


def _arista(predicate: str, subject: str, obj: str, workspace: str) -> Query:
    """La arista entre DOS entidades concretas, en UN patron encadenado.

    Un solo `MATCH` con el camino completo: sujeto, arista y objeto en la
    MISMA fila. Partirlo en dos `MATCH` daria el producto cartesiano de los
    dos conjuntos y cero filas en cuanto uno estuviera vacio.
    """
    rel = safe_token(predicate, "predicate")
    return Query(
        f"MATCH (a:{LABEL_ENTITY} {{entity_id: $s, workspace: $ws}})"
        f"-[r:{rel}]->(b:{LABEL_ENTITY} {{entity_id: $o, workspace: $ws}}) "
        "RETURN r.idempotency_key AS clave",
        {"s": subject, "o": obj, "ws": workspace},
    )


def _run(driver: Any, query: Query) -> list:
    with driver.session() as sesion:
        return [dict(r) for r in sesion.run(query.cypher, **query.params)]


def _payload(op: dict) -> dict:
    valor = op.get("payload")
    return valor if isinstance(valor, dict) else {}


def _verificar_operacion(driver: Any, op: dict, workspace: str) -> Optional[EfectoAusente]:
    """El efecto de UNA operacion, observado. `None` = esta donde dice estar."""
    tipo = str(op.get("operation_type") or "")
    op_id = str(op.get("operation_id") or "")
    clave = str(op.get("idempotency_key") or "")

    if tipo not in EFECTO_DECLARADO:
        return EfectoAusente(
            op_id, tipo, CODE_TYPE_UNDECLARED, "",
            "este tipo de operacion no declara efecto observable: no se puede "
            "afirmar que se materializo",
        )

    if tipo == "CREATE_ENTITY":
        identidad = str(op.get("target_entity_id") or "")
        filas = _run(driver, _nodo(LABEL_ENTITY, "entity_id", identidad, workspace))
        if not filas:
            return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                                 "la entidad no esta en el grafo")
        return None

    if tipo == "CREATE_ASSERTION":
        identidad = str(op.get("assertion_id") or "")
        filas = _run(driver, _nodo(LABEL_ASSERTION, "assertion_id", identidad, workspace))
        if not filas:
            return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                                 "la afirmacion no esta en el grafo")
        # ATRIBUCION: existe, pero ¿la escribio ESTA operacion? Una afirmacion
        # identica escrita por otro plan tiene otra clave de idempotencia.
        if clave and filas[0].get("clave") not in (None, clave):
            return EfectoAusente(
                op_id, tipo, CODE_EFFECT_NOT_ATTRIBUTED, identidad,
                "la afirmacion existe pero la escribio otra operacion",
            )
        return None

    if tipo in ("PROJECT_RELATION", "LINK_EXISTING"):
        payload = _payload(op)
        sujeto = str(payload.get("subject_entity_id") or "")
        objeto = str(payload.get("object_entity_id") or "")
        predicado = str(payload.get("predicate") or "")
        identidad = f"{sujeto} -{predicado}-> {objeto}"
        if not (sujeto and objeto and predicado):
            return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                                 "la operacion no nombra los dos extremos y el predicado")
        filas = _run(driver, _arista(predicado, sujeto, objeto, workspace))
        if not filas:
            return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                                 "la arista no esta en el grafo")
        if clave and not any(f.get("clave") == clave for f in filas):
            return EfectoAusente(
                op_id, tipo, CODE_EFFECT_NOT_ATTRIBUTED, identidad,
                "hay arista entre esos extremos pero ninguna la escribio esta "
                "operacion",
            )
        return None

    if tipo == "SUPERSEDE_ASSERTION":
        identidad = str(op.get("assertion_id") or "")
        filas = _run(driver, _nodo(LABEL_ASSERTION, "assertion_id", identidad, workspace))
        if not filas:
            return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                                 "la afirmacion que se iba a cerrar no esta en el grafo")
        if str(filas[0].get("status") or "") != "SUPERSEDED":
            return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                                 "la afirmacion sigue sin su vigencia cerrada")
        return None

    # UPDATE_ENTITY
    identidad = str(op.get("target_entity_id") or "")
    filas = _run(driver, _nodo(LABEL_ENTITY, "entity_id", identidad, workspace))
    if not filas:
        return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                             "la entidad que se iba a actualizar no esta en el grafo")
    esperada = op.get("expected_version")
    try:
        if esperada is not None and int(filas[0].get("version") or 0) <= int(esperada):
            return EfectoAusente(op_id, tipo, CODE_EFFECT_MISSING, identidad,
                                 "la version de la entidad no avanzo")
    except (TypeError, ValueError):  # pragma: no cover - fila corrupta
        pass
    return None


def _evidencia_alcanzable(driver: Any, assertion_id: str, workspace: str) -> set:
    """Fragmentos a los que SE LLEGA desde la afirmacion, por el CAMINO.

    Se usa `trace_query`, que ya recorre
    `afirmacion -SUPPORTED_BY-> evidencia <-HAS_FRAGMENT- episodio
     <-HAS_EPISODE- fuente`
    en un solo patron encadenado. Comprobar solo el `SUPPORTED_BY` diria que
    hay procedencia cuando la cadena esta rota mas arriba y el operador no
    puede llegar a la fuente.
    """
    return {
        str(f.get("fragment_id"))
        for f in _run(driver, trace_query(workspace, assertion_id))
        if f.get("fragment_id")
    }


def verify_effects(
    driver: Any,
    plan_doc: Any,
    *,
    workspace: str,
    check_provenance: bool = True,
) -> EffectReport:
    """Mira el grafo y contesta: ¿esta materializado lo que el plan declaro?

    `check_provenance` permite medir SOLO los efectos del plan. Se deja
    explicito para que apagarlo sea una decision visible en el llamador y no
    un descuido: con `False`, esta funcion NO afirma nada sobre la
    navegabilidad de la evidencia.
    """
    operaciones = []
    if isinstance(plan_doc, dict):
        operaciones = [
            op for op in (plan_doc.get("mutation_operations") or [])
            if isinstance(op, dict)
        ]

    vistas: list = []
    ausentes: list = []
    for op in operaciones:
        fallo = _verificar_operacion(driver, op, workspace)
        if fallo is None:
            vistas.append(str(op.get("operation_id") or ""))
        else:
            ausentes.append(fallo)

    sin_procedencia: list = []
    if check_provenance:
        for op in operaciones:
            if op.get("operation_type") != "CREATE_ASSERTION":
                continue
            assertion_id = str(op.get("assertion_id") or "")
            citados = {
                str(f) for f in (op.get("evidence_fragment_ids") or []) if f
            }
            if not assertion_id or not citados:
                # Sin evidencia citada no hay nada que alcanzar. NO es un
                # aprobado por ausencia: es que esta operacion no prometio
                # procedencia ninguna.
                continue
            alcanzables = _evidencia_alcanzable(driver, assertion_id, workspace)
            colgando = sorted(citados - alcanzables)
            if colgando:
                sin_procedencia.append(
                    EfectoAusente(
                        str(op.get("operation_id") or ""),
                        "CREATE_ASSERTION",
                        CODE_PROVENANCE_UNREACHABLE,
                        assertion_id,
                        "la afirmacion cita evidencia a la que el recorrido no "
                        "llega: " + ", ".join(colgando),
                        missing_ids=tuple(colgando),
                    )
                )

    return EffectReport(
        observed=tuple(vistas),
        missing=tuple(ausentes),
        provenance_missing=tuple(sin_procedencia),
    )


__all__ = [
    "CODE_EFFECT_MISSING",
    "CODE_EFFECT_NOT_ATTRIBUTED",
    "CODE_PROVENANCE_UNREACHABLE",
    "CODE_TYPE_UNDECLARED",
    "EFECTO_DECLARADO",
    "EfectoAusente",
    "EffectReport",
    "verify_effects",
]
