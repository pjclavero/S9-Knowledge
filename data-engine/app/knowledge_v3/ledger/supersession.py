# -*- coding: utf-8 -*-
"""Matriz de transiciones de `status` y derivacion de versiones.

Dos ejes que NO se mezclan (dosier 11.5 y contrato `fact-assertion`):

- `status`  : ciclo de vida en el ledger (PROVISIONAL...RETRACTED).
- `state`   : eje temporal del hecho narrado (ACTIVE, ENDED, PLANNED, ...).

Una afirmacion `ENDED` puede seguir siendo `CONFIRMED`, y una `SUPERSEDED` puede
seguir siendo `ACTIVE` en el mundo (se sustituyo el registro, no termino el
hecho). Confundirlos es el error clasico: cerrar la vigencia de un hecho porque
llego una version mejor del registro.

La matriz es CERRADA: lo que no esta explicitamente permitido, se rechaza. Una
matriz por lista negra deja transiciones nuevas coladas por omision cada vez que
alguien anade un estado.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, FrozenSet, Optional

from ..contracts import AssertionStatus
from .entries import LedgerOperation
from .errors import LedgerError, LedgerTransitionError
from .timeline import before_or_equal, same_instant

S = AssertionStatus

#: Estados TERMINALES: no admiten ninguna transicion posterior.
#:
#: `SUPERSEDED` es terminal a proposito. Una version ya sustituida no puede
#: retractarse ni confirmarse: quien quiera corregirla debe actuar sobre la
#: CABEZA de la cadena, que es la version vigente. Permitir tocar el pasado
#: convertiria la cadena en un grafo con dos verdades simultaneas.
TERMINAL_STATUSES: FrozenSet[AssertionStatus] = frozenset({S.SUPERSEDED, S.RETRACTED})

#: Estados con los que puede NACER una afirmacion.
CREATION_STATUSES: FrozenSet[AssertionStatus] = frozenset({S.PROVISIONAL, S.ASSERTED})

#: Matriz legal de transiciones. Clave `None` = creacion.
STATUS_TRANSITIONS: Dict[Optional[AssertionStatus], FrozenSet[AssertionStatus]] = {
    None: CREATION_STATUSES,
    S.PROVISIONAL: frozenset(
        {S.ASSERTED, S.CONFIRMED, S.LIMITED, S.SUPERSEDED, S.CONTRADICTED, S.RETRACTED}
    ),
    S.ASSERTED: frozenset(
        {S.CONFIRMED, S.LIMITED, S.SUPERSEDED, S.CONTRADICTED, S.RETRACTED}
    ),
    S.CONFIRMED: frozenset(
        {S.CONFIRMED, S.LIMITED, S.SUPERSEDED, S.CONTRADICTED, S.RETRACTED}
    ),
    S.LIMITED: frozenset(
        {S.CONFIRMED, S.LIMITED, S.SUPERSEDED, S.CONTRADICTED, S.RETRACTED}
    ),
    S.CONTRADICTED: frozenset(
        {S.CONFIRMED, S.LIMITED, S.CONTRADICTED, S.SUPERSEDED, S.RETRACTED}
    ),
    S.SUPERSEDED: frozenset(),
    S.RETRACTED: frozenset(),
}

#: Estado destino que produce cada operacion sobre la afirmacion AFECTADA.
#: `ASSERT` no aparece: su destino lo elige quien crea (dentro de
#: `CREATION_STATUSES`), no la operacion.
OPERATION_TARGET_STATUS: Dict[LedgerOperation, AssertionStatus] = {
    LedgerOperation.CONFIRM: S.CONFIRMED,
    LedgerOperation.SUPERSEDE: S.SUPERSEDED,
    LedgerOperation.CONTRADICT: S.CONTRADICTED,
    LedgerOperation.RETRACT: S.RETRACTED,
}

#: Razones canonicas admisibles por operacion. Conjunto CERRADO: un motivo de
#: texto libre convierte la auditoria del ledger en prosa no agregable (mismo
#: criterio que `CANONICAL_REASON_CODES` del validador de contratos).
CANONICAL_REASONS: Dict[LedgerOperation, FrozenSet[str]] = {
    LedgerOperation.ASSERT: frozenset(
        {
            "INITIAL_ASSERTION",
            "NEW_EVIDENCE",
            "REINSTATED_AFTER_REVIEW",
            #: M4 (docs/v3/49-multipartida-diseno.md §2.5): la afirmacion de
            #: partida que diverge del lore de capa juego nace como un ASSERT
            #: normal -- no un SUPERSEDE, porque el hecho de capa juego no se
            #: sustituye, sigue vivo para cualquier otra partida. Este es el
            #: motivo canonico que la distingue de una asercion inicial
            #: corriente.
            "LOCAL_DIVERGENCE",
        }
    ),
    LedgerOperation.CONFIRM: frozenset(
        {"CORROBORATING_EVIDENCE", "SECOND_SOURCE", "HUMAN_REVIEW_CONFIRMED"}
    ),
    LedgerOperation.SUPERSEDE: frozenset(
        {"SUPERSEDED_BY_NEWER", "VALIDITY_CLOSED", "CORRECTED_EXTRACTION"}
    ),
    LedgerOperation.CONTRADICT: frozenset(
        {"CONTRADICTORY_EVIDENCE", "MUTUALLY_EXCLUSIVE_FACTS", "CONFLICTING_SOURCES"}
    ),
    LedgerOperation.RETRACT: frozenset(
        {
            "EXTRACTION_ERROR",
            "EVIDENCE_INVALID",
            "SOURCE_WITHDRAWN",
            "OPERATOR_RETRACTION",
            "COPYRIGHT_TAKEDOWN",
        }
    ),
}

#: Estados que siguen contando como conocimiento del sistema. `CONTRADICTED`
#: SIGUE dentro: una contradiccion no destruye nada, marca. Quien consulte debe
#: verla y decidir, no encontrarsela desaparecida.
LIVE_STATUSES: FrozenSet[AssertionStatus] = frozenset(
    {S.PROVISIONAL, S.ASSERTED, S.CONFIRMED, S.LIMITED, S.CONTRADICTED}
)


def _as_status(value: "AssertionStatus | str") -> AssertionStatus:
    if isinstance(value, AssertionStatus):
        return value
    try:
        return AssertionStatus(value)
    except ValueError as exc:
        raise LedgerTransitionError(f"status desconocido: {value!r}") from exc


def check_transition(
    current: "AssertionStatus | str | None",
    target: "AssertionStatus | str",
    *,
    operation: Optional[LedgerOperation] = None,
    assertion_id: str = "",
) -> None:
    """Valida una transicion contra la matriz cerrada. Lanza si no es legal."""
    cur = None if current is None else _as_status(current)
    tgt = _as_status(target)
    allowed = STATUS_TRANSITIONS.get(cur)
    if allowed is None:
        raise LedgerTransitionError(f"estado de origen no contemplado: {cur}")
    if tgt not in allowed:
        origen = "creacion" if cur is None else cur.value
        raise LedgerTransitionError(
            f"transicion ilegal {origen} -> {tgt.value}"
            + (f" en {assertion_id}" if assertion_id else "")
            + (f" (operacion {operation.value})" if operation else "")
            + f"; legales desde {origen}: {sorted(s.value for s in allowed) or 'ninguna (estado terminal)'}"
        )


def check_reason(operation: LedgerOperation, reason_code: str) -> None:
    """Valida el motivo contra el catalogo cerrado de la operacion."""
    allowed = CANONICAL_REASONS[operation]
    if reason_code not in allowed:
        raise LedgerError(
            f"reason_code {reason_code!r} no es canonico para {operation.value}; "
            f"admitidos: {sorted(allowed)}"
        )


def is_live(status: "AssertionStatus | str") -> bool:
    """True si la afirmacion sigue formando parte del conocimiento vigente."""
    return _as_status(status) in LIVE_STATUSES


# --------------------------------------------------------------------------
# Derivacion de versiones
# --------------------------------------------------------------------------
#: Nombre del paso que el ledger anade a `provider_trace`. El ledger es codigo
#: local determinista: `provider = local` SIEMPRE. Ningun proveedor externo
#: puede aparecer como productor de un cambio de ciclo de vida.
LEDGER_STEP_NAME = "s9k.knowledge_v3.ledger"


def ledger_step(operation: LedgerOperation, seq: int, produced: list[str], version: str) -> dict:
    """Paso de traza del ledger, con `step` unico por numero de entrada.

    El `seq` va en el identificador porque `provider_trace` prohibe pasos
    repetidos: dos supersesiones sobre la misma afirmacion colisionarian.
    """
    return {
        "step": f"ledger.{operation.value.lower()}.{seq:08d}",
        "provider": "local",
        "name": LEDGER_STEP_NAME,
        "version": version,
        "model": None,
        "produced": list(produced),
    }


def derive_version(
    previous: dict,
    *,
    operation: LedgerOperation,
    seq: int,
    recorded_at: str,
    changes: Dict[str, Any],
    produced: list[str],
    engine_version: str,
) -> dict:
    """Nueva revision de una afirmacion a partir de la anterior.

    NO muta `previous`: devuelve un documento nuevo. `assertion_id` se conserva
    (es la identidad del registro); lo que avanza es la REVISION en el ledger.
    `recorded_at` del documento se alinea con el de la entrada: el tiempo de
    transaccion es uno solo y no puede discrepar entre entrada y documento.
    """
    doc = deepcopy(previous)
    doc.update(changes)
    doc["recorded_at"] = recorded_at
    step = ledger_step(operation, seq, produced, engine_version)
    doc["provider_trace"] = list(doc.get("provider_trace") or []) + [step]
    doc["produced_by_step"] = step["step"]
    return doc


def close_validity(
    previous: dict,
    *,
    successor_id: str,
    valid_to: Optional[str],
) -> Dict[str, Any]:
    """Cambios que CIERRAN la vigencia de una afirmacion superada.

    Reglas:

    - Si la afirmacion ya tenia `valid_to`, no se mueve. Reabrir o desplazar una
      vigencia ya cerrada seria reescribir el pasado con otro nombre; si el
      llamante pide otro `valid_to`, es un error, no un ajuste silencioso.
    - `state` solo cambia de `ACTIVE` a `ENDED`, porque el contrato prohibe
      `ACTIVE` con `valid_to`. `PLANNED`, `RECURRING` o `HYPOTHETICAL` se
      conservan: el ledger no tiene informacion para reclasificar el eje
      temporal de un hecho, y adivinarlo seria inventar.
    """
    existing = previous.get("valid_to")
    if existing is not None:
        if valid_to is not None and not same_instant(existing, valid_to):
            raise LedgerError(
                f"la vigencia de {previous['assertion_id']} ya estaba cerrada en "
                f"{existing}; moverla a {valid_to} seria reescribir el pasado"
            )
        closing = existing
    else:
        if valid_to is None:
            raise LedgerError(
                f"supersesion de {previous['assertion_id']} sin `valid_to`: no se "
                "puede cerrar una vigencia sin decir cuando termina (ni se puede "
                "deducir de una afirmacion nueva sin `valid_from`)"
            )
        closing = valid_to
    if not before_or_equal(previous.get("valid_from"), closing):
        raise LedgerError(
            f"valid_to {closing} anterior a valid_from {previous.get('valid_from')} "
            f"en {previous['assertion_id']}"
        )
    state = previous.get("state")
    return {
        "status": S.SUPERSEDED.value,
        "superseded_by": successor_id,
        "valid_to": closing,
        "state": "ENDED" if state == "ACTIVE" else state,
    }


def chain_from(entries_by_id: Dict[str, dict], assertion_id: str) -> list[str]:
    """Cadena de supersesion hacia adelante desde `assertion_id`.

    Detecta ciclos de forma explicita: una cadena que se muerde la cola es un
    ledger corrupto, no un caso raro que convenga ignorar.
    """
    chain: list[str] = []
    seen: set[str] = set()
    current: Optional[str] = assertion_id
    while current is not None:
        if current in seen:
            raise LedgerError(f"cadena de supersesion ciclica en {current}")
        seen.add(current)
        chain.append(current)
        doc = entries_by_id.get(current)
        if doc is None:
            break
        current = doc.get("superseded_by")
    return chain


__all__ = [
    "CANONICAL_REASONS",
    "CREATION_STATUSES",
    "LEDGER_STEP_NAME",
    "LIVE_STATUSES",
    "OPERATION_TARGET_STATUS",
    "STATUS_TRANSITIONS",
    "TERMINAL_STATUSES",
    "chain_from",
    "check_reason",
    "check_transition",
    "close_validity",
    "derive_version",
    "is_live",
    "ledger_step",
]
