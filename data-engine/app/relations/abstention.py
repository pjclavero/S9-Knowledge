# -*- coding: utf-8 -*-
"""Abstencion y rechazo JUSTIFICADOS del consenso de relaciones (Bloque 6).

Problema que resuelve
---------------------
El consenso v1 (`relations.consensus_adapter`) solo podia emitir `reject` cuando un
PROVEEDOR presente votaba en contra. En modo offline (sin Ollama/NVIDIA) no hay
proveedores, luego `reject` era INALCANZABLE por construccion: un techo mecanico
identico al que el Bloque 2 encontro en el predicado. Ademas, las senales que los
Bloques 2/3/4 ya calculaban (abstencion del selector de predicado, confianza de
direccion, estado de vigencia temporal) NO llegaban a la decision: el motor podia
recomendar `propose` sobre un candidato cuyo PROPIO selector habia declarado dudoso
el predicado.

Que hace este modulo
--------------------
Convierte esas senales YA CALCULADAS en MOTIVOS ESTRUCTURADOS (`DecisionReason`,
catalogo CERRADO de codigos) y en un VEREDICTO (`Assessment.verdict`):

  * ``NEUTRAL``  -- ninguna senal se pronuncia; la decision v1 queda intacta.
  * ``ABSTAIN``  -- hay motivo BLOQUEANTE: la relacion NO puede proponerse, pero
    tampoco hay base para rechazarla -> revision humana.
  * ``REJECT``   -- hay motivo RECHAZANTE: la evidencia dice que la relacion NO se
    sostiene (p.ej. el texto la NIEGA) -> rechazo justificado.

Principios duros
----------------
  * DETERMINISTA y PURO: sin red, sin disco, sin reloj, sin aleatoriedad, sin
    estado mutable. Recibe valores YA CALCULADOS y no invoca a ningun proveedor.
  * NUNCA MEJORA UNA DECISION. `apply_verdict` solo puede degradar
    (`propose` -> `human`/`reject`) o dejar igual. No existe ningun camino por el
    que una abstencion produzca `propose`, `STRONG_CONSENSUS` o una aprobacion.
    La garantia es estructural (ver `apply_verdict`) y esta verificada por tests
    exhaustivos sobre TODAS las combinaciones (estado x recomendacion x veredicto).
  * NO TOCA NINGUN UMBRAL. No lee ni modifica los umbrales del ensemble ni de
    `review_policy`; no participa en la calibracion de scores.
  * MOTIVOS ESTRUCTURADOS, NO CADENAS LIBRES: cada motivo tiene `code` (catalogo
    cerrado), `severity`, `source` (bloque de origen) y un `detail` legible que es
    trazabilidad, nunca el criterio.

Que NO hace (decisiones tomadas Y MEDIDAS, no omisiones)
-------------------------------------------------------
  * NO rechaza por estado temporal ``ENDED``. Se midio en el banco B1: el
    resolutor temporal v2 marca ENDED todo lo que va en pasado, y 18 de las 30
    relaciones ACCEPT emparejadas caen ahi. Un `reject` por ENDED habria fabricado
    13 rechazos falsos sobre ACCEPT para ganar 0 aciertos netos. La regla existe en
    la politica (`reject_on_temporal_ended`) pero esta DESACTIVADA por defecto y
    documentada como contraproducente con el resolutor temporal actual.
  * NO veta por confianza de direccion baja POR DEFECTO. Medido: la resolucion
    debil (orden textual / predicado generico, confianza 0.5) dispara en 21 de 43
    emparejados y acierta la direccion en 18 de esas 21. Vetar ahi habria mandado a
    humano una mayoria de direcciones CORRECTAS. La senal se REGISTRA como motivo
    INFORMATIVO (queda en la traza y puede consumirla un bloque futuro con la
    confianza ya calibrada) y la regla bloqueante existe pero esta desactivada
    (`veto_on_direction`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from external_ai.models import (
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
)

from relations import ontology as _ontology
from relations.direction import REVIEW_DIRECTION_FLAG
from relations.predicate_selector import REVIEW_PREDICATE_FLAG
from relations.temporal_v2 import TemporalState

ABSTENTION_VERSION = "relation-abstention-1.0.0"
ABSTENTION_SCHEMA = "relation-abstention/v1"

# ---------------------------------------------------------------------------
# Severidades (catalogo CERRADO, ordenado)
# ---------------------------------------------------------------------------
#: El motivo se registra pero NO cambia la decision (trazabilidad/calibracion).
SEVERITY_INFORMATIVE = "INFORMATIVE"
#: El motivo IMPIDE proponer (veta `propose`), pero no justifica rechazar.
SEVERITY_BLOCKING = "BLOCKING"
#: El motivo justifica un `reject` (la evidencia dice que la relacion NO se sostiene).
SEVERITY_REJECTING = "REJECTING"
SEVERITIES: tuple = (SEVERITY_BLOCKING, SEVERITY_INFORMATIVE, SEVERITY_REJECTING)

# ---------------------------------------------------------------------------
# Fuentes (bloque del motor v2 que produjo la senal)
# ---------------------------------------------------------------------------
SOURCE_PREDICATE = "predicate_selector"   # B2
SOURCE_DIRECTION = "direction"            # B3
SOURCE_TEMPORAL = "temporal"              # B4
SOURCE_EPISTEMIC = "epistemic"
SOURCE_NEGATION = "negation"
SOURCE_ONTOLOGY = "ontology"
REASON_SOURCES: tuple = (
    SOURCE_DIRECTION, SOURCE_EPISTEMIC, SOURCE_NEGATION, SOURCE_ONTOLOGY,
    SOURCE_PREDICATE, SOURCE_TEMPORAL,
)

# ---------------------------------------------------------------------------
# Codigos de motivo (catalogo CERRADO)
# ---------------------------------------------------------------------------
REASON_PREDICATE_ABSTAINED = "predicate_abstained"
REASON_DIRECTION_LOW_CONFIDENCE = "direction_low_confidence"
REASON_EPISTEMIC_NOT_ASSERTED = "epistemic_not_asserted"
REASON_TEMPORAL_NOT_IN_FORCE = "temporal_not_in_force"
REASON_TEMPORAL_UNRESOLVED = "temporal_unresolved"
REASON_TEMPORAL_ENDED = "temporal_ended"
REASON_NEGATED_RELATION = "negated_relation"
REASON_TYPE_INCOMPATIBLE = "type_incompatible"
REASON_CODES: tuple = (
    REASON_DIRECTION_LOW_CONFIDENCE,
    REASON_EPISTEMIC_NOT_ASSERTED,
    REASON_NEGATED_RELATION,
    REASON_PREDICATE_ABSTAINED,
    REASON_TEMPORAL_ENDED,
    REASON_TEMPORAL_NOT_IN_FORCE,
    REASON_TEMPORAL_UNRESOLVED,
    REASON_TYPE_INCOMPATIBLE,
)

# ---------------------------------------------------------------------------
# Veredictos (catalogo CERRADO)
# ---------------------------------------------------------------------------
VERDICT_NEUTRAL = "NEUTRAL"
VERDICT_ABSTAIN = "ABSTAIN"
VERDICT_REJECT = "REJECT"
VERDICTS: tuple = (VERDICT_ABSTAIN, VERDICT_NEUTRAL, VERDICT_REJECT)

#: Estados de vigencia (B4) que significan "la relacion NO esta en vigor todavia /
#: es meramente potencial". No son un rechazo: son una razon para NO proponer.
_NOT_IN_FORCE_STATES: frozenset = frozenset({
    TemporalState.HYPOTHETICAL, TemporalState.PLANNED,
})

#: Estado epistemico que SI admite proponer. Cualquier otro (RUMORED, HYPOTHETICAL,
#: INTENDED, ...) es una asercion no factual: se puede registrar, no proponer.
ASSERTED = "ASSERTED"


class AbstentionPolicyError(ValueError):
    """Politica de abstencion invalida (campo desconocido o tipo incorrecto)."""


# ---------------------------------------------------------------------------
# Motivo estructurado
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DecisionReason:
    """UN motivo de decision, ESTRUCTURADO (nunca una cadena libre).

    `code` pertenece al catalogo cerrado `REASON_CODES`, `severity` a `SEVERITIES`
    y `source` a `REASON_SOURCES`. `detail` es trazabilidad legible: NUNCA es el
    criterio (ningun consumidor debe parsearlo).
    """

    code: str
    severity: str
    source: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.code not in REASON_CODES:
            raise ValueError(f"codigo de motivo desconocido: {self.code!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"severidad desconocida: {self.severity!r}")
        if self.source not in REASON_SOURCES:
            raise ValueError(f"fuente de motivo desconocida: {self.source!r}")

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "source": self.source,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Politica (que motivo pesa y como)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AbstentionPolicy:
    """Que senales se consumen y con que severidad. Inmutable y versionada.

    Los valores por defecto son los MEDIDOS en el banco B1 (ver docstring del
    modulo): las reglas contraproducentes existen pero nacen DESACTIVADAS, para que
    activarlas sea un acto explicito y medible, no un olvido.
    """

    veto_on_predicate_abstention: bool = True
    veto_on_epistemic: bool = True
    veto_on_temporal_not_in_force: bool = True
    veto_on_type_incompatible: bool = True
    veto_on_direction: bool = False
    reject_on_negation: bool = True
    reject_on_temporal_ended: bool = False
    #: Si el selector de predicado se abstuvo, NO se puede rechazar tampoco: no se
    #: rechaza una proposicion que el motor no sabe formular. Precedencia medida:
    #: con ella, 2 rechazos falsos sobre GT-ACCEPT en vez de 3.
    predicate_abstention_blocks_reject: bool = True
    name: str = "abstention-default-1.0.0"

    def __post_init__(self) -> None:
        for field_name in (
            "veto_on_predicate_abstention", "veto_on_epistemic",
            "veto_on_temporal_not_in_force", "veto_on_type_incompatible",
            "veto_on_direction", "reject_on_negation", "reject_on_temporal_ended",
            "predicate_abstention_blocks_reject",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise AbstentionPolicyError(f"{field_name} debe ser bool")
        if not isinstance(self.name, str) or not self.name.strip():
            raise AbstentionPolicyError("name debe ser una cadena no vacia")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "veto_on_predicate_abstention": self.veto_on_predicate_abstention,
            "veto_on_epistemic": self.veto_on_epistemic,
            "veto_on_temporal_not_in_force": self.veto_on_temporal_not_in_force,
            "veto_on_type_incompatible": self.veto_on_type_incompatible,
            "veto_on_direction": self.veto_on_direction,
            "reject_on_negation": self.reject_on_negation,
            "reject_on_temporal_ended": self.reject_on_temporal_ended,
            "predicate_abstention_blocks_reject": self.predicate_abstention_blocks_reject,
        }


DEFAULT_POLICY = AbstentionPolicy()


# ---------------------------------------------------------------------------
# Evaluacion
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Assessment:
    """Motivos + veredicto para UN candidato. Serializable y determinista."""

    verdict: str
    reasons: tuple = field(default_factory=tuple)
    policy: str = DEFAULT_POLICY.name
    version: str = ABSTENTION_VERSION
    schema: str = ABSTENTION_SCHEMA

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"veredicto desconocido: {self.verdict!r}")

    @property
    def codes(self) -> tuple:
        return tuple(r.code for r in self.reasons)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reasons": [r.to_dict() for r in self.reasons],
            "policy": self.policy,
            "version": self.version,
            "schema": self.schema,
        }


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _flags(candidate: Any) -> frozenset:
    raw = _get(candidate, "validation_flags") or ()
    try:
        return frozenset(f for f in raw if isinstance(f, str))
    except TypeError:            # fail-closed: flags no iterables -> sin flags
        return frozenset()


def _epistemic_value(candidate: Any) -> str:
    status = _get(candidate, "epistemic_status")
    value = getattr(status, "value", status)
    return value if isinstance(value, str) else ""


def temporal_state_of(temporal_scope: Any) -> str:
    """Estado de vigencia (B4) codificado en el `temporal_scope` del candidato.

    `temporal_v2.TemporalResolution.to_scope_string()` emite
    ``"<CLASE> | state=<ESTADO> | ..."``. Se lee el segmento ``state=`` SIN
    reclasificar nada: si no esta (alcance de v1, `None`, o cadena arbitraria) el
    estado es ``UNKNOWN``, que es lo honesto -- "no consta", no "no hay".
    """
    if not isinstance(temporal_scope, str):
        return TemporalState.UNKNOWN
    for part in temporal_scope.split("|"):
        part = part.strip()
        if part.startswith("state="):
            state = part[len("state="):].strip()
            if state in (TemporalState.ACTIVE, TemporalState.ENDED,
                         TemporalState.PLANNED, TemporalState.HYPOTHETICAL,
                         TemporalState.RECURRING, TemporalState.UNKNOWN):
                return state
    return TemporalState.UNKNOWN


def _types_incompatible(candidate: Any) -> bool:
    """¿Los tipos del par CONTRADICEN el dominio/rango del predicado en B1?

    Solo devuelve True cuando hay una contradiccion DEMOSTRABLE: el predicado esta
    en la ontologia autoritativa (`relations.ontology`), declara dominio/rango, y
    el tipo de sujeto u objeto queda fuera. En cualquier otro caso -- predicado
    desconocido, tipos ausentes, dominio/rango sin declarar -- devuelve False:
    "no consta" NO es "incompatible". Ausencia de informacion nunca es un veto.
    """
    predicate = _get(candidate, "predicate") or _get(candidate, "relation_type")
    subject_type = _get(candidate, "subject_type")
    object_type = _get(candidate, "object_type")
    if not isinstance(predicate, str) or subject_type is None or object_type is None:
        return False
    try:
        entry = _ontology.get(predicate)
    except Exception:            # predicado fuera de la ontologia: no se juzga
        return False
    if entry is None:
        return False
    domain = getattr(entry, "domain", None)
    range_ = getattr(entry, "range", None)
    if domain and subject_type not in domain:
        return True
    if range_ and object_type not in range_:
        return True
    return False


def _signal_value(signals: Optional[Sequence[Any]], name: str) -> Any:
    for s in signals or ():
        if _get(s, "name") == name:
            return _get(s, "value")
    return None


def assess(candidate: Any, *, signals: Optional[Sequence[Any]] = None,
           policy: AbstentionPolicy = DEFAULT_POLICY) -> Assessment:
    """Deriva los motivos estructurados y el veredicto de UN candidato.

    Lee EXCLUSIVAMENTE valores ya calculados por el pipeline (flags de validacion,
    `negated`, `epistemic_status`, `temporal_scope` y, opcionalmente, la senal de
    compatibilidad de tipos). No muta el candidato ni recalcula ninguna etapa.

    Precedencia del veredicto (documentada y verificada por tests):

      1. Si el SELECTOR DE PREDICADO se abstuvo y la politica lo declara
         bloqueante-de-rechazo, el veredicto es ``ABSTAIN`` aunque haya motivos
         rechazantes: no se rechaza una proposicion cuyo predicado el propio motor
         no sabe formular.
      2. Si hay algun motivo ``REJECTING`` -> ``REJECT``.
      3. Si hay algun motivo ``BLOCKING`` -> ``ABSTAIN``.
      4. En otro caso -> ``NEUTRAL``.
    """
    if not isinstance(policy, AbstentionPolicy):
        raise AbstentionPolicyError("policy debe ser una AbstentionPolicy")

    reasons: list = []
    flags = _flags(candidate)

    # --- B2: abstencion del selector de predicado -----------------------------
    predicate_abstained = REVIEW_PREDICATE_FLAG in flags
    if predicate_abstained:
        reasons.append(DecisionReason(
            REASON_PREDICATE_ABSTAINED,
            SEVERITY_BLOCKING if policy.veto_on_predicate_abstention
            else SEVERITY_INFORMATIVE,
            SOURCE_PREDICATE,
            f"el selector de predicado marco {REVIEW_PREDICATE_FLAG!r}: "
            f"predicado {_get(candidate, 'predicate')!r} sin margen suficiente",
        ))

    # --- B3: confianza de direccion -------------------------------------------
    if REVIEW_DIRECTION_FLAG in flags:
        reasons.append(DecisionReason(
            REASON_DIRECTION_LOW_CONFIDENCE,
            SEVERITY_BLOCKING if policy.veto_on_direction else SEVERITY_INFORMATIVE,
            SOURCE_DIRECTION,
            "la direccion se resolvio por debajo del umbral de confianza "
            "(orden textual o predicado sin direccion semantica)",
        ))

    # --- B4: estado de vigencia ------------------------------------------------
    state = temporal_state_of(_get(candidate, "temporal_scope"))
    if state in _NOT_IN_FORCE_STATES:
        reasons.append(DecisionReason(
            REASON_TEMPORAL_NOT_IN_FORCE,
            SEVERITY_BLOCKING if policy.veto_on_temporal_not_in_force
            else SEVERITY_INFORMATIVE,
            SOURCE_TEMPORAL,
            f"estado de vigencia {state}: la relacion no consta en vigor",
        ))
    elif state == TemporalState.UNKNOWN:
        reasons.append(DecisionReason(
            REASON_TEMPORAL_UNRESOLVED, SEVERITY_INFORMATIVE, SOURCE_TEMPORAL,
            "sin estado de vigencia resoluble en la evidencia",
        ))
    elif state == TemporalState.ENDED:
        reasons.append(DecisionReason(
            REASON_TEMPORAL_ENDED,
            SEVERITY_REJECTING if policy.reject_on_temporal_ended
            else SEVERITY_INFORMATIVE,
            SOURCE_TEMPORAL,
            "estado de vigencia ENDED (relacion concluida o evento cerrado)",
        ))

    # --- Estado epistemico -----------------------------------------------------
    epistemic = _epistemic_value(candidate)
    if epistemic and epistemic != ASSERTED:
        reasons.append(DecisionReason(
            REASON_EPISTEMIC_NOT_ASSERTED,
            SEVERITY_BLOCKING if policy.veto_on_epistemic else SEVERITY_INFORMATIVE,
            SOURCE_EPISTEMIC,
            f"estado epistemico {epistemic}: la evidencia no afirma el hecho",
        ))

    # --- Negacion: la evidencia dice que la relacion NO se sostiene ------------
    if bool(_get(candidate, "negated")):
        reasons.append(DecisionReason(
            REASON_NEGATED_RELATION,
            SEVERITY_REJECTING if policy.reject_on_negation else SEVERITY_INFORMATIVE,
            SOURCE_NEGATION,
            "la evidencia NIEGA la relacion (negated=True)",
        ))

    # --- Tipos incompatibles con la ontologia ----------------------------------
    # FUENTE: `relations.ontology` (B1), que es la AUTORIDAD del programa y define
    # dominio/rango POR PREDICADO. NO se usa `signals.type_compatibility`: esa
    # senal se calcula sobre `TYPE_ONTOLOGY`, una ontologia deliberadamente MINIMA
    # cuya propia documentacion dice "NO descarta la relacion; solo informa", y que
    # ni siquiera contempla el par (Character, Character) -- justo el de los
    # predicados familiares y sociales que B0 anadio en este programa. Tratar su
    # lista vacia como "incompatible" bloqueaba 23 de 52 candidatos (44%) por una
    # laguna de cobertura, no por una incompatibilidad real.
    if _types_incompatible(candidate):
        reasons.append(DecisionReason(
            REASON_TYPE_INCOMPATIBLE,
            SEVERITY_BLOCKING if policy.veto_on_type_incompatible
            else SEVERITY_INFORMATIVE,
            SOURCE_ONTOLOGY,
            "los tipos de sujeto/objeto no son compatibles con la ontologia",
        ))

    ordered = tuple(sorted(reasons, key=lambda r: (r.code, r.source)))
    severities = {r.severity for r in ordered}

    # `predicate_abstention_blocks_reject` es INDEPENDIENTE de
    # `veto_on_predicate_abstention`: son dos decisiones distintas (una veta
    # proponer, la otra veta rechazar) y acoplarlas hacia que desactivar el veto
    # desactivara en silencio tambien la guarda contra rechazos infundados.
    blocked_by_predicate = (
        predicate_abstained and policy.predicate_abstention_blocks_reject
    )
    rejecting = SEVERITY_REJECTING in severities
    blocking = SEVERITY_BLOCKING in severities
    if rejecting and not blocked_by_predicate:
        verdict = VERDICT_REJECT
    elif rejecting or blocking:
        # Un rechazo SUPRIMIDO por la guarda no se convierte en "todo bien": queda
        # en abstencion (revision humana), que es lo honesto.
        verdict = VERDICT_ABSTAIN
    else:
        verdict = VERDICT_NEUTRAL

    return Assessment(verdict=verdict, reasons=ordered, policy=policy.name)


# ---------------------------------------------------------------------------
# Aplicacion del veredicto (UNICA puerta; solo degrada)
# ---------------------------------------------------------------------------
def apply_verdict(state: str, recommendation: str, assessment: Assessment, *,
                  reject_recommendation: str = "reject",
                  human_recommendation: str = "human",
                  propose_recommendation: str = "propose") -> tuple:
    """Devuelve `(state, recommendation)` tras aplicar el veredicto. SOLO DEGRADA.

    Reglas (en orden, todas verificadas por test exhaustivo):

      1. ``INVALID_RESPONSES`` es intocable: una invalidacion no se reinterpreta.
      2. ``MODEL_CONFLICT`` es intocable: si las fuentes se contradicen entre si,
         ni proponer ni rechazar; ya esta en manos de un humano.
      3. Veredicto ``REJECT`` -> ``(PARTIAL_CONSENSUS, reject)``. Nunca
         ``STRONG_CONSENSUS``: sin proveedor presente no hay consenso fuerte, y el
         techo del rechazo no puede superar al de la propuesta.
      4. Veredicto ``ABSTAIN`` -> solo actua si la recomendacion era ``propose``,
         y entonces la degrada a ``(HUMAN_REQUIRED, human)``. Un ``reject`` previo
         (voto negativo real de un proveedor) NO se ablanda a humano: seguiria sin
         escribirse nada y se perderia una senal negativa.
      5. Veredicto ``NEUTRAL`` -> nada cambia.

    No existe rama alguna que devuelva `propose` cuando la entrada no lo era, ni
    que eleve el estado. Esa es la barrera anti-mejora del bloque.
    """
    if state in (INVALID_RESPONSES, MODEL_CONFLICT):
        return (state, recommendation)
    if assessment.verdict == VERDICT_REJECT:
        return (PARTIAL_CONSENSUS, reject_recommendation)
    if (assessment.verdict == VERDICT_ABSTAIN
            and recommendation == propose_recommendation):
        return (HUMAN_REQUIRED, human_recommendation)
    return (state, recommendation)


def summarize(assessment: Assessment) -> str:
    """Frase corta y ESTABLE derivada de los motivos (no es el criterio)."""
    if not assessment.reasons:
        return "Sin motivos de abstencion ni rechazo."
    codes = ", ".join(sorted({r.code for r in assessment.reasons}))
    if assessment.verdict == VERDICT_REJECT:
        return f"Rechazo justificado por evidencia contradictoria: {codes}."
    if assessment.verdict == VERDICT_ABSTAIN:
        return f"Abstencion informativa: {codes}."
    return f"Motivos informativos: {codes}."


__all__ = [
    "ABSTENTION_VERSION",
    "ABSTENTION_SCHEMA",
    "SEVERITIES",
    "SEVERITY_BLOCKING",
    "SEVERITY_INFORMATIVE",
    "SEVERITY_REJECTING",
    "REASON_CODES",
    "REASON_SOURCES",
    "REASON_DIRECTION_LOW_CONFIDENCE",
    "REASON_EPISTEMIC_NOT_ASSERTED",
    "REASON_NEGATED_RELATION",
    "REASON_PREDICATE_ABSTAINED",
    "REASON_TEMPORAL_ENDED",
    "REASON_TEMPORAL_NOT_IN_FORCE",
    "REASON_TEMPORAL_UNRESOLVED",
    "REASON_TYPE_INCOMPATIBLE",
    "VERDICTS",
    "VERDICT_ABSTAIN",
    "VERDICT_NEUTRAL",
    "VERDICT_REJECT",
    "AbstentionPolicy",
    "AbstentionPolicyError",
    "DEFAULT_POLICY",
    "DecisionReason",
    "Assessment",
    "assess",
    "apply_verdict",
    "summarize",
    "temporal_state_of",
]
