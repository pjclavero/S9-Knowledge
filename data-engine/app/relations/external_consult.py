# -*- coding: utf-8 -*-
"""La IA externa como CONSULTOR, nunca como autoridad (Bloque 7).

Que problema resuelve
---------------------
Hasta este bloque, la evaluacion externa entraba en el consenso como UNA FUENTE MAS
con voto: `consensus_adapter._compute_consensus_v1` emite ``STRONG_CONSENSUS`` cuando
"dos proveedores presentes coinciden", y una de esas dos fuentes es la IA externa.
Como `relations.review_policy` marca ``AUTO_PROPOSABLE`` exigiendo exactamente
``state == STRONG_CONSENSUS`` + >= 1 proveedor presente, el voto externo era
CO-SUFICIENTE para el estado que habilita proponer sin revision. Eso es autoridad, y
B7 la retira.

Modelo de este modulo
---------------------
La externa puede hacer TRES cosas, y ninguna es decidir:

  * ``REINFORCE`` -- confirma y aporta EVIDENCIA que el motor local valida. Se ANOTA.
    **No cambia la decision.**
  * ``ABSTAIN``   -- no aporta nada utilizable (incierto, invalido, sin evidencia
    validable). **No cambia nada.**
  * ``DISSENT``   -- contradice. Puede **DEGRADAR** ``propose -> human``. **Jamas
    fabrica un ``reject``**: rechazar es decidir, y la externa no decide.

Y una garantia de estado por encima de las tres: con consulta externa presente,
``STRONG_CONSENSUS`` se rebaja a ``PARTIAL_CONSENSUS`` (``EXTERNAL_MAX_STATE``). Es la
muerte ESTRUCTURAL de la auto-aprobacion por via externa, no una convencion.

Validacion local OBLIGATORIA
----------------------------
`validate_external_verdict` es el UNICO camino por el que una salida externa entra en
el motor, y es fail-closed en cada paso: estructura -> resolucion de evidencia
(fragmentos > literal unica > realineamiento restringido) -> REVERIFICACION final de
que ``document[start:end] == evidence_text``. Si algo no encaja: ``INVALID`` y
``ABSTAIN``. Nunca "se acepta con dudas".

Principios duros
----------------
  * DETERMINISTA y PURO: sin red, sin disco, sin reloj, sin azar, sin escritura.
  * `apply_consultation` es la UNICA puerta y SOLO DEGRADA. No existe rama que
    devuelva ``propose`` si la entrada no lo era, ni que suba el estado. Verificado
    por barrido EXHAUSTIVO en `tests/test_relation_v2_b7_external.py`.
  * La evidencia aceptada es SIEMPRE una rodaja LITERAL del documento real: el texto
    que manda el modelo nunca se propaga tal cual. Una inyeccion de prompt puede, como
    mucho, hacer que se cite otra parte del propio documento.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from external_ai.models import (
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)

from relations import evidence_realignment as _realign
from relations import fragment_protocol as _frag

CONSULT_VERSION = "relation-external-consult-1.0.0"
CONSULT_SCHEMA = "relation-external-consult/v1"

# ---------------------------------------------------------------------------
# Catalogos CERRADOS
# ---------------------------------------------------------------------------
#: Postura de la consulta externa respecto de la decision local.
STANCE_ABSTAIN = "ABSTAIN"
STANCE_DISSENT = "DISSENT"
STANCE_REINFORCE = "REINFORCE"
STANCES: tuple = (STANCE_ABSTAIN, STANCE_DISSENT, STANCE_REINFORCE)

#: Resultado de la validacion local de la salida externa.
STATUS_ACCEPTED = "ACCEPTED"        # evidencia resuelta y literal
STATUS_NO_EVIDENCE = "NO_EVIDENCE"  # el modelo no aporta evidencia utilizable
STATUS_INVALID = "INVALID"          # la salida externa no supera la validacion local
CONSULT_STATUSES: tuple = (STATUS_ACCEPTED, STATUS_INVALID, STATUS_NO_EVIDENCE)

#: Protocolo que resolvio la evidencia.
PROTOCOL_FRAGMENTS = "fragments"        # via PREFERIDA (V3): literalidad por construccion
PROTOCOL_LITERAL = "literal"            # cita literal y UNICA en el documento
PROTOCOL_REALIGNMENT = "realignment"    # fallback RESTRINGIDO (V2), unico y no ambiguo
PROTOCOL_NONE = "none"
CONSULT_PROTOCOLS: tuple = (
    PROTOCOL_FRAGMENTS, PROTOCOL_LITERAL, PROTOCOL_NONE, PROTOCOL_REALIGNMENT,
)

#: Verdictos que el modelo externo puede emitir (mismo catalogo que
#: `external_ai_shadow.VALID_VERDICTS`; se declara aqui para no crear un import
#: circular, y hay un test que verifica que ambos catalogos coinciden).
VERDICT_CONFIRM = "confirm"
VERDICT_REFINE = "refine"
VERDICT_REJECT = "reject"
VERDICT_UNCERTAIN = "uncertain"
CONSULT_VERDICTS: tuple = (
    VERDICT_CONFIRM, VERDICT_REFINE, VERDICT_REJECT, VERDICT_UNCERTAIN,
)

#: Postura que corresponde a cada verdicto ANTES de exigir evidencia. Un `confirm`
#: sin evidencia validada NO refuerza (ver `_stance_for`).
_VERDICT_STANCE = {
    VERDICT_CONFIRM: STANCE_REINFORCE,
    VERDICT_REFINE: STANCE_REINFORCE,
    VERDICT_REJECT: STANCE_DISSENT,
    VERDICT_UNCERTAIN: STANCE_ABSTAIN,
}

#: Recomendaciones sombra de `external_ai_shadow` -> postura.
_SHADOW_RECO_STANCE = {
    "confirm": STANCE_REINFORCE,
    "refine": STANCE_REINFORCE,
    "reject": STANCE_DISSENT,
    "human": STANCE_ABSTAIN,
    "uncertain": STANCE_ABSTAIN,
}

#: TECHO DE ESTADO de cualquier consulta externa. Con la externa presente el motor no
#: puede quedar en `STRONG_CONSENSUS`, luego `review_policy.AUTO_PROPOSABLE` (que lo
#: exige literalmente) es INALCANZABLE por via externa.
EXTERNAL_MAX_STATE = PARTIAL_CONSENSUS

#: Estados que NADIE reinterpreta (misma regla que `abstention.apply_verdict`).
_UNTOUCHABLE_STATES: frozenset = frozenset({INVALID_RESPONSES, MODEL_CONFLICT})


class ExternalConsultError(ValueError):
    """Configuracion de consulta externa invalida."""


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExternalConsultConfig:
    """Que protocolo se usa y que fallbacks se permiten. Inmutable.

    `protocol` = ``"fragments"`` es la via PREFERIDA (el modelo elige ids, el sistema
    reconstruye offsets). ``"legacy"`` mantiene el contrato clasico (el modelo manda
    la cita) y es el DEFAULT, para que el comportamiento por defecto no cambie.
    """

    protocol: str = "legacy"                 # "legacy" | "fragments"
    allow_realignment_fallback: bool = True  # fallback V2 RESTRINGIDO (unico/no ambiguo)
    max_fragments: int = _frag.DEFAULT_MAX_FRAGMENTS
    name: str = "external-consult-default-1.0.0"

    def __post_init__(self) -> None:
        if self.protocol not in ("legacy", "fragments"):
            raise ExternalConsultError(
                f"protocol {self.protocol!r} no valido (legacy|fragments)"
            )
        if not isinstance(self.allow_realignment_fallback, bool):
            raise ExternalConsultError("allow_realignment_fallback debe ser bool")
        if (not isinstance(self.max_fragments, int)
                or isinstance(self.max_fragments, bool) or self.max_fragments < 1):
            raise ExternalConsultError("max_fragments debe ser un entero >= 1")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ExternalConsultError("name debe ser una cadena no vacia")

    @property
    def uses_fragments(self) -> bool:
        return self.protocol == "fragments"

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "allow_realignment_fallback": self.allow_realignment_fallback,
            "max_fragments": self.max_fragments,
            "name": self.name,
        }


DEFAULT_CONSULT_CONFIG = ExternalConsultConfig()
FRAGMENT_CONSULT_CONFIG = ExternalConsultConfig(
    protocol="fragments", name="external-consult-fragments-1.0.0"
)


# ---------------------------------------------------------------------------
# Resultado de la consulta (serializable, determinista)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExternalConsultation:
    """Salida externa YA VALIDADA localmente. Nunca es una decision."""

    stance: str
    status: str
    protocol: str = PROTOCOL_NONE
    verdict: str = ""
    evidence_text: str = ""
    evidence_start: int = -1
    evidence_end: int = -1
    fragment_ids: tuple = ()
    errors: tuple = ()
    reason_codes: tuple = ()
    version: str = CONSULT_VERSION
    schema: str = CONSULT_SCHEMA

    def __post_init__(self) -> None:
        if self.stance not in STANCES:
            raise ValueError(f"stance desconocida: {self.stance!r}")
        if self.status not in CONSULT_STATUSES:
            raise ValueError(f"status desconocido: {self.status!r}")
        if self.protocol not in CONSULT_PROTOCOLS:
            raise ValueError(f"protocol desconocido: {self.protocol!r}")
        # Barrera dura: solo un ACCEPTED puede llevar evidencia.
        if self.status != STATUS_ACCEPTED and self.evidence_text:
            raise ValueError("solo un ACCEPTED puede transportar evidencia")

    @property
    def has_evidence(self) -> bool:
        return self.status == STATUS_ACCEPTED and bool(self.evidence_text)

    def to_dict(self) -> dict:
        return {
            "stance": self.stance,
            "status": self.status,
            "protocol": self.protocol,
            "verdict": self.verdict,
            "evidence_text": self.evidence_text,
            "evidence_start": self.evidence_start,
            "evidence_end": self.evidence_end,
            "fragment_ids": list(self.fragment_ids),
            "errors": list(self.errors),
            "reason_codes": list(self.reason_codes),
            "version": self.version,
            "schema": self.schema,
        }


def _abstained(status: str, errors: list, codes: list) -> ExternalConsultation:
    return ExternalConsultation(
        stance=STANCE_ABSTAIN, status=status,
        errors=tuple(errors), reason_codes=tuple(sorted(set(codes))),
    )


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_offset(value: Any) -> int:
    """Offset entero de traza. Cualquier cosa no entera es `-1` (no consta)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return -1
    return value


# ---------------------------------------------------------------------------
# Resolucion de evidencia (fragmentos > literal unica > realineamiento restringido)
# ---------------------------------------------------------------------------
@dataclass
class _Evidence:
    ok: bool
    protocol: str = PROTOCOL_NONE
    text: str = ""
    start: int = -1
    end: int = -1
    fragment_ids: tuple = ()
    errors: list = field(default_factory=list)
    codes: list = field(default_factory=list)


def _resolve_evidence(document: str, raw: dict,
                      config: ExternalConsultConfig) -> _Evidence:
    """Resuelve la evidencia de un verdicto crudo contra el DOCUMENTO REAL.

    Prioridad:
      1. ``fragment_ids`` (via PREFERIDA, solo si el protocolo es "fragments"): el
         sistema reconstruye los offsets; el modelo no cuenta caracteres.
      2. ``evidence_text`` que aparezca LITERALMENTE y UNA SOLA VEZ en el documento.
      3. Fallback RESTRINGIDO de realineamiento (`realign_evidence_unique`): solo
         diferencias tipograficas y solo con coincidencia unica; ambiguo => rechazo.

    Los offsets que manda el modelo NO se usan en ninguna rama: son la fuente medida
    del falso anclaje. Se ignoran deliberadamente.
    """
    # --- 1. Fragmentos (via preferida) ----------------------------------------
    if config.uses_fragments:
        fids = raw.get("fragment_ids")
        if fids is None:
            return _Evidence(
                False, errors=["fragment_ids ausente con protocolo de fragmentos"],
                codes=["fragment_ids_missing"],
            )
        fragments = _frag.fragment_document(document, max_fragments=config.max_fragments)
        index = _frag.build_fragment_index(fragments)
        rec = _frag.reconstruct_evidence(document, index, fids)
        if not rec.ok:
            return _Evidence(False, errors=list(rec.errors), codes=["fragment_invalid"])
        return _Evidence(
            True, PROTOCOL_FRAGMENTS, rec.text, rec.start, rec.end,
            tuple(rec.fragment_ids),
        )

    # --- 2/3. Protocolo clasico: cita del modelo -------------------------------
    ev = raw.get("evidence_text")
    if not isinstance(ev, str) or not ev.strip():
        return _Evidence(False, errors=["evidence_text vacia o ausente"],
                         codes=["evidence_missing"])

    result = _realign.realign_evidence_unique(document, ev)
    if result.ok and result.tier == _realign.TIER_EXACT:
        return _Evidence(True, PROTOCOL_LITERAL, result.evidence_text,
                         result.start, result.end)
    if result.ok:
        if not config.allow_realignment_fallback:
            return _Evidence(
                False, errors=["realineamiento desactivado por configuracion"],
                codes=["realignment_disabled"],
            )
        return _Evidence(True, PROTOCOL_REALIGNMENT, result.evidence_text,
                         result.start, result.end, codes=[f"realign_{result.tier}"])
    return _Evidence(False, errors=[f"evidencia no anclable ({result.tier})"],
                     codes=[f"evidence_{result.tier}"])


def _stance_for(verdict: str, has_evidence: bool) -> str:
    """Postura final. Un ``confirm``/``refine` SIN evidencia validada NO refuerza.

    Reforzar es el unico caso en el que la externa "aporta"; si lo que aporta no se
    puede anclar en el documento, no aporta nada y la postura honesta es ABSTAIN.
    Un ``reject`` SI disiente sin evidencia: disentir solo degrada, y degradar sin
    pruebas es conservador, no peligroso.
    """
    stance = _VERDICT_STANCE.get(verdict, STANCE_ABSTAIN)
    if stance == STANCE_REINFORCE and not has_evidence:
        return STANCE_ABSTAIN
    return stance


# ---------------------------------------------------------------------------
# API: validacion local OBLIGATORIA de la salida externa
# ---------------------------------------------------------------------------
def validate_external_verdict(
    document: Optional[str],
    candidate: Any,
    raw_verdict: Any,
    *,
    candidate_id: Optional[str] = None,
    config: ExternalConsultConfig = DEFAULT_CONSULT_CONFIG,
) -> ExternalConsultation:
    """Valida LOCALMENTE un verdicto externo crudo contra el DOCUMENTO REAL.

    `document` es el TEXTO del segmento, no su identificador. Pasar el identificador
    (defecto P0 del programa anterior, vivo en esta rama antes de B7) produce aqui un
    `INVALID`/`ABSTAIN` con `evidence_*`: el defecto se vuelve VISIBLE en vez de
    disfrazarse de "el modelo externo rechaza todo".

    Devuelve SIEMPRE una `ExternalConsultation`; nunca lanza por culpa del contenido
    externo (fail-closed por candidato).
    """
    if not isinstance(config, ExternalConsultConfig):
        raise ExternalConsultError("config debe ser una ExternalConsultConfig")

    if not isinstance(document, str) or not document.strip():
        return _abstained(STATUS_INVALID, ["documento ausente o vacio"],
                          ["document_missing"])
    if not isinstance(raw_verdict, dict):
        return _abstained(STATUS_INVALID, ["verdicto externo no es un objeto"],
                          ["verdict_not_object"])

    errors: list = []
    codes: list = []

    # --- Identidad: el verdicto debe hablar del candidato que se pregunto ------
    expected = candidate_id if candidate_id is not None else _get(candidate, "candidate_id")
    if expected is None:
        subject = _get(candidate, "subject_id")
        predicate = _get(candidate, "predicate")
        obj = _get(candidate, "object_id")
        if subject is not None and predicate is not None and obj is not None:
            expected = f"{subject}|{predicate}|{obj}"
    got = raw_verdict.get("candidate_id")
    if expected is not None:
        if got is None:
            return _abstained(STATUS_INVALID, ["candidate_id ausente"],
                              ["candidate_id_missing"])
        if str(got) != str(expected):
            return _abstained(
                STATUS_INVALID,
                [f"candidate_id no coincide: esperado {expected!r}, recibido {str(got)!r}"],
                ["candidate_id_mismatch"],
            )

    # --- Verdicto dentro del catalogo cerrado ---------------------------------
    verdict = raw_verdict.get("verdict")
    if verdict not in CONSULT_VERDICTS:
        return _abstained(STATUS_INVALID, [f"verdict invalido: {verdict!r}"],
                          ["verdict_invalid"])

    # --- `negated` explicito y booleano ---------------------------------------
    negated = raw_verdict.get("negated", False)
    if not isinstance(negated, bool):
        return _abstained(STATUS_INVALID, ["negated debe ser bool explicito"],
                          ["negated_not_bool"])

    # --- Incertidumbre: no se le pide evidencia --------------------------------
    if verdict == VERDICT_UNCERTAIN:
        return ExternalConsultation(
            stance=STANCE_ABSTAIN, status=STATUS_NO_EVIDENCE, verdict=verdict,
            reason_codes=("external_uncertain",),
        )

    # --- Evidencia: resuelta SIEMPRE por el sistema ----------------------------
    ev = _resolve_evidence(document, raw_verdict, config)
    errors.extend(ev.errors)
    codes.extend(ev.codes)

    if not ev.ok:
        # Sin evidencia validable la externa no puede aportar. Solo el disenso
        # sobrevive (y disentir unicamente degrada).
        stance = _stance_for(verdict, has_evidence=False)
        return ExternalConsultation(
            stance=stance, status=STATUS_NO_EVIDENCE, verdict=verdict,
            errors=tuple(errors), reason_codes=tuple(sorted(set(codes))),
        )

    # --- REVERIFICACION FINAL de literalidad (barrera estructural) -------------
    # Aunque cada via ya la garantiza, se vuelve a comprobar aqui: es la unica
    # afirmacion que este modulo hace hacia fuera y no debe depender de que el
    # resolutor sea correcto.
    if not (0 <= ev.start <= ev.end <= len(document)
            and document[ev.start:ev.end] == ev.text
            and ev.text in document):
        return _abstained(
            STATUS_INVALID,
            ["literalidad no verificable: document[start:end] != evidence_text"],
            codes + ["literality_check_failed"],
        )

    return ExternalConsultation(
        stance=_stance_for(verdict, has_evidence=True),
        status=STATUS_ACCEPTED,
        protocol=ev.protocol,
        verdict=verdict,
        evidence_text=ev.text,
        evidence_start=ev.start,
        evidence_end=ev.end,
        fragment_ids=tuple(ev.fragment_ids),
        errors=tuple(errors),
        reason_codes=tuple(sorted(set(codes))),
    )


def consultation_from_evaluation(evaluation: Any) -> Optional[ExternalConsultation]:
    """Deriva la POSTURA de una `RelationExternalEvaluation` ya emitida.

    Se usa en el consenso (B6) y en el ensemble, donde lo que llega es la evaluacion
    completa y no el verdicto crudo. Fail-closed: cualquier cosa que no se reconozca
    es `ABSTAIN` (no cambia nada), nunca un refuerzo.
    """
    if evaluation is None:
        return None
    reco = _get(evaluation, "shadow_recommendation")
    state = _get(evaluation, "state")
    verdict_obj = _get(evaluation, "verdict") or {}
    verdict = _get(verdict_obj, "verdict", "") or ""
    if state == INVALID_RESPONSES:
        return ExternalConsultation(
            stance=STANCE_ABSTAIN, status=STATUS_INVALID,
            reason_codes=("external_invalid_response",),
        )
    stance = _SHADOW_RECO_STANCE.get(reco, STANCE_ABSTAIN)
    # Un refuerzo exige que la evaluacion traiga un verdicto validado: sin el, la
    # evaluacion no ha aportado evidencia y no refuerza nada.
    if stance == STANCE_REINFORCE and not verdict_obj:
        stance = STANCE_ABSTAIN
    return ExternalConsultation(
        stance=stance,
        status=STATUS_ACCEPTED if verdict_obj else STATUS_NO_EVIDENCE,
        protocol=PROTOCOL_NONE,
        verdict=str(verdict),
        evidence_text=(str(_get(verdict_obj, "evidence_text", "") or "")
                       if verdict_obj else ""),
        evidence_start=_as_offset(_get(verdict_obj, "evidence_start", -1)),
        evidence_end=_as_offset(_get(verdict_obj, "evidence_end", -1)),
        reason_codes=("external_" + str(reco),) if isinstance(reco, str) else (),
    )


# ---------------------------------------------------------------------------
# UNICA puerta. SOLO DEGRADA.
# ---------------------------------------------------------------------------
def apply_consultation(
    state: str,
    recommendation: str,
    consultation: Optional[ExternalConsultation],
    *,
    human_recommendation: str = "human",
    propose_recommendation: str = "propose",
) -> tuple:
    """Devuelve `(state, recommendation)` tras la consulta externa. SOLO DEGRADA.

    Reglas (en orden; todas verificadas por barrido EXHAUSTIVO):

      1. Sin consulta (`None`) no cambia nada. La ausencia no es una opinion.
      2. ``INVALID_RESPONSES`` y ``MODEL_CONFLICT`` son INTOCABLES (misma regla que
         `abstention.apply_verdict`): la externa no reinterpreta una invalidacion ni
         resuelve un conflicto entre fuentes.
      3. **Techo de estado**: con consulta presente, ``STRONG_CONSENSUS`` se rebaja a
         ``EXTERNAL_MAX_STATE`` (= ``PARTIAL_CONSENSUS``). `review_policy` exige
         literalmente ``STRONG_CONSENSUS`` para ``AUTO_PROPOSABLE``, de modo que la
         auto-proposicion por via externa queda ESTRUCTURALMENTE cerrada.
      4. ``DISSENT`` sobre una recomendacion ``propose`` -> ``(HUMAN_REQUIRED,
         human)``. Sobre cualquier otra recomendacion no cambia nada: un ``reject``
         local NO se ablanda y un ``human`` no empeora.
      5. ``REINFORCE`` y ``ABSTAIN`` no mueven la recomendacion. Refuerzo es
         anotacion, no promocion.

    NO existe rama que devuelva ``propose`` cuando la entrada no lo era, ni que eleve
    el estado. Esa es la barrera anti-autoridad del bloque.
    """
    if consultation is None:
        return (state, recommendation)
    if not isinstance(consultation, ExternalConsultation):
        raise ExternalConsultError("consultation debe ser una ExternalConsultation")
    if state in _UNTOUCHABLE_STATES:
        return (state, recommendation)

    capped = EXTERNAL_MAX_STATE if state == STRONG_CONSENSUS else state

    if (consultation.stance == STANCE_DISSENT
            and recommendation == propose_recommendation):
        return (HUMAN_REQUIRED, human_recommendation)
    return (capped, recommendation)


def summarize(consultation: Optional[ExternalConsultation]) -> str:
    """Frase corta y ESTABLE (traza, nunca criterio)."""
    if consultation is None:
        return "Sin consulta externa."
    if consultation.stance == STANCE_DISSENT:
        return "La IA externa disiente; la decision local baja a revision humana."
    if consultation.stance == STANCE_REINFORCE:
        return (f"La IA externa refuerza con evidencia literal validada "
                f"(protocolo {consultation.protocol}); la decision NO cambia.")
    return "La IA externa se abstiene o no aporta evidencia validable."


__all__ = [
    "CONSULT_PROTOCOLS",
    "CONSULT_SCHEMA",
    "CONSULT_STATUSES",
    "CONSULT_VERDICTS",
    "CONSULT_VERSION",
    "DEFAULT_CONSULT_CONFIG",
    "EXTERNAL_MAX_STATE",
    "FRAGMENT_CONSULT_CONFIG",
    "ExternalConsultConfig",
    "ExternalConsultError",
    "ExternalConsultation",
    "PROTOCOL_FRAGMENTS",
    "PROTOCOL_LITERAL",
    "PROTOCOL_NONE",
    "PROTOCOL_REALIGNMENT",
    "STANCES",
    "STANCE_ABSTAIN",
    "STANCE_DISSENT",
    "STANCE_REINFORCE",
    "STATUS_ACCEPTED",
    "STATUS_INVALID",
    "STATUS_NO_EVIDENCE",
    "apply_consultation",
    "consultation_from_evaluation",
    "summarize",
    "validate_external_verdict",
]
