# -*- coding: utf-8 -*-
"""Eje TEMPORAL: de `temporal_expressions` a `state`, `event_time` y vigencia.

Dosier 11.5. Aqui se separan cuatro cosas que en V2 estaban revueltas:

* `event_time`  — cuando ocurrio el hecho narrado;
* `valid_from` / `valid_to` — durante que intervalo la afirmacion es vigente;
* `recorded_at` — cuando lo supo el sistema (lo pone el ledger, no este eje);
* `state` — el eje TEMPORAL del estado: `ACTIVE`, `ENDED`, `PLANNED`,
  `HYPOTHETICAL`, `RECURRING`, `UNKNOWN`.

**El pasado verbal no implica `ENDED`.** No es un matiz: "Daiki juro lealtad a
la Casa del Ciervo" esta en pasado y describe una pertenencia que sigue viva.
Este modulo no mira el verbo — no mira el texto en absoluto. Solo mira la
ESTRUCTURA de las expresiones temporales que el extractor ya anclo:

    kind=POINT     + valid_from            -> ACTIVE, event_time = valid_from
    kind=INTERVAL  + valid_from + valid_to -> ENDED   (hay un final EXPLICITO)
    kind=INTERVAL  + valid_from            -> ACTIVE
    kind=DURATION                          -> RECURRING si hay anclaje, si no UNKNOWN
    kind=RELATIVE  sin anclaje             -> UNKNOWN + aviso
    sin expresiones                        -> UNKNOWN

`ENDED` sale UNICAMENTE de un `valid_to` explicito, que es ademas lo que el
contrato congelado exige (`state=ENDED` sin `valid_to` es invalido, y
`state=ACTIVE` con `valid_to` tambien). Un `UNKNOWN` honesto es infinitamente
mas util que un `ENDED` inventado: el `UNKNOWN` se puede refinar despues; el
`ENDED` cierra una vigencia que nadie cerro.

El `calendar_id` se valida contra `GameProfile.calendars` — el cruce entre dos
documentos que la revision de contratos dejo anotado como pendiente del motor.
Un calendario que el perfil no conoce no se copia a la afirmacion: se manda a
revision, porque una fecha en un calendario desconocido no es una fecha.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..contracts.claim import ClaimProposal
from . import findings as F
from .ontology import ProfileIndex

STATE_ACTIVE = "ACTIVE"
STATE_ENDED = "ENDED"
STATE_PLANNED = "PLANNED"
STATE_HYPOTHETICAL = "HYPOTHETICAL"
STATE_RECURRING = "RECURRING"
STATE_UNKNOWN = "UNKNOWN"

#: Estatus epistemico -> estado temporal cuando NO hay expresiones temporales.
#: Una intencion es un hecho PLANIFICADO; una hipotesis, un hecho hipotetico.
#: Esto no es leer el verbo: es leer el estatus epistemico que ya viene tipado.
EPISTEMIC_STATE = {
    "INTENDED": STATE_PLANNED,
    "HYPOTHETICAL": STATE_HYPOTHETICAL,
}


@dataclass(frozen=True)
class TemporalOutcome:
    state: str
    event_time: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    calendar_id: Optional[str]
    findings: tuple[F.Finding, ...]


def resolve_temporality(
    claim: ClaimProposal,
    index: ProfileIndex,
    known_fragment_ids: frozenset[str],
    *,
    material_reasons: tuple[str, ...] = (),
    graduated_policy: bool = False,
) -> TemporalOutcome:
    """Mapea las expresiones temporales de un claim al eje temporal del ledger.

    Una relativa sin anclaje no es material por si sola. El llamador aporta
    razones estructurales ya resueltas por el motor: cesacion, contradiccion,
    estado sucesivo o exclusividad funcional. Si alguna concurre se revisa; si
    no, solo falta el limite exacto y se conserva como WARN. Las cronologias
    internamente incompatibles ya producen sus hallazgos REVIEW antes de llegar
    a esta clasificacion. Ante una razon desconocida, el contrato de esta
    funcion es deliberadamente estricto: cualquier valor no vacio es material.
    """
    out: list[F.Finding] = []
    expressions = list(claim.temporal_expressions)

    calendar_ids = {e.get("calendar_id") for e in expressions if e.get("calendar_id")}
    calendar_id: Optional[str] = None
    if len(calendar_ids) > 1:
        out.append(F.TEMPORAL_CALENDAR_MIXED(f"varios calendarios: {sorted(calendar_ids)}"))
    elif calendar_ids:
        candidate = next(iter(calendar_ids))
        if candidate in index.calendars:
            calendar_id = candidate
        else:
            out.append(
                F.TEMPORAL_CALENDAR_UNKNOWN(
                    f"{candidate} no esta en GameProfile.calendars {sorted(index.calendars)}"
                )
            )

    for expression in expressions:
        fragment_id = expression.get("fragment_id")
        if fragment_id is not None and fragment_id not in known_fragment_ids:
            out.append(
                F.TEMPORAL_FRAGMENT_UNKNOWN(f"la expresion cita el fragmento {fragment_id}")
            )

    if not expressions:
        out.append(F.TEMPORAL_UNSPECIFIED("sin expresiones temporales"))
        state = EPISTEMIC_STATE.get(claim.epistemic_status_hint, STATE_UNKNOWN)
        return TemporalOutcome(state, None, None, None, calendar_id, tuple(out))

    froms = {e.get("valid_from") for e in expressions if e.get("valid_from")}
    tos = {e.get("valid_to") for e in expressions if e.get("valid_to")}
    if len(froms) > 1 or len(tos) > 1:
        out.append(
            F.TEMPORAL_CONFLICTING_EXPRESSIONS(
                f"anclajes incompatibles: from={sorted(froms)} to={sorted(tos)}"
            )
        )
        return TemporalOutcome(STATE_UNKNOWN, None, None, None, calendar_id, tuple(out))

    valid_from = next(iter(froms), None)
    valid_to = next(iter(tos), None)
    kinds = {e["kind"] for e in expressions}

    if valid_from and valid_to and valid_from > valid_to:
        out.append(F.TEMPORAL_INTERVAL_INVERTED(f"{valid_from} > {valid_to}"))
        return TemporalOutcome(STATE_UNKNOWN, None, None, None, calendar_id, tuple(out))

    if not valid_from and not valid_to:
        # Expresiones sin anclar: se sabe QUE hay tiempo, no CUAL.
        if "RELATIVE" in kinds:
            if not graduated_policy:
                out.append(
                    F.TEMPORAL_UNRESOLVED_RELATIVE(
                        "expresion relativa sin anclaje absoluto: no se resuelve localmente"
                    )
                )
            elif material_reasons:
                out.append(
                    F.TEMPORAL_SCOPE_MATERIAL(
                        "expresion relativa sin anclaje cambia la decision: "
                        + ", ".join(material_reasons)
                    )
                )
            else:
                out.append(
                    F.TEMPORAL_BOUND_UNKNOWN(
                        "relacion segura; falta el limite absoluto de la expresion relativa"
                    )
                )
        else:
            out.append(F.TEMPORAL_UNSPECIFIED(f"expresiones {sorted(kinds)} sin anclaje"))
        state = EPISTEMIC_STATE.get(claim.epistemic_status_hint, STATE_UNKNOWN)
        return TemporalOutcome(state, None, None, None, calendar_id, tuple(out))

    event_time = valid_from or valid_to
    if valid_to:
        state = STATE_ENDED
    elif "DURATION" in kinds:
        state = STATE_RECURRING
    else:
        state = STATE_ACTIVE

    # El estatus epistemico manda sobre el eje temporal cuando declara que el
    # hecho aun no ha ocurrido: una intencion fechada sigue siendo PLANNED.
    forced = EPISTEMIC_STATE.get(claim.epistemic_status_hint)
    if forced is not None:
        state = forced

    if state == STATE_ACTIVE and valid_to is not None:  # pragma: no cover - invariante
        state = STATE_ENDED
    if state == STATE_ENDED and valid_to is None:  # pragma: no cover - invariante
        state = STATE_UNKNOWN

    return TemporalOutcome(state, event_time, valid_from, valid_to, calendar_id, tuple(out))
