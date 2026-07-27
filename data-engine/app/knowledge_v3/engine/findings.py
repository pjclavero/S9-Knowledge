# -*- coding: utf-8 -*-
"""Hallazgos de los ejes del motor y su traduccion a una decision del contrato.

Un `Finding` es la unidad de explicacion del motor: QUE eje lo produjo, con
QUE gravedad, con QUE codigo canonico del contrato y con que codigo descriptivo
propio. Una decision del motor no es mas que la agregacion determinista de los
hallazgos de un claim.

Por que asi y no un `bool` con un mensaje: porque el contrato exige
`reason_codes` canonicos y enumerables, y porque una decision sin sus razones
no es auditable. La prosa no se agrega; los codigos si.

Precedencia de gravedad (de mas a menos restrictiva):

    REJECT  >  ABSTAIN  >  REVIEW  >  WARN  >  INFO

`ABSTAIN` por encima de `REVIEW` es una decision consciente y discutible: si el
motor no logra siquiera anclar el claim en evidencia verificable, no hay nada
que un humano pueda adjudicar, y mandarlo a revision solo inunda la cola — que
es exactamente como V2 se hizo inutil (auditoria 00: ~170 falsos positivos por
acierto). Un claim BIEN anclado pero ambiguo si va a revision.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

#: Ejes del motor (dosier 11.2). Un hallazgo pertenece a uno y solo uno.
AXIS_INPUT = "INPUT"
AXIS_EXISTENCE = "EXISTENCE"
AXIS_EVIDENCE = "EVIDENCE"
AXIS_PREDICATE = "PREDICATE"
AXIS_DIRECTION = "DIRECTION"
AXIS_NEGATION = "NEGATION"
AXIS_EPISTEMIC = "EPISTEMIC"
AXIS_TEMPORAL = "TEMPORAL"
AXIS_CONTRADICTION = "CONTRADICTION"
AXIS_AUTHORITY = "AUTHORITY"

AXES = (
    AXIS_INPUT,
    AXIS_EXISTENCE,
    AXIS_EVIDENCE,
    AXIS_PREDICATE,
    AXIS_DIRECTION,
    AXIS_NEGATION,
    AXIS_EPISTEMIC,
    AXIS_TEMPORAL,
    AXIS_CONTRADICTION,
    AXIS_AUTHORITY,
)


class Severity(IntEnum):
    """Gravedad de un hallazgo. El orden del valor ES la precedencia."""

    INFO = 0
    WARN = 1
    REVIEW = 2
    ABSTAIN = 3
    REJECT = 4


#: Gravedad -> decision del contrato (`ENGINE_DECISION_MAP` del validador usa
#: los mismos cuatro valores). INFO y WARN no cambian la decision: un claim sin
#: hallazgos por encima de WARN se acepta.
SEVERITY_DECISION = {
    Severity.REJECT: "REJECT_INVALID",
    Severity.ABSTAIN: "ABSTAIN",
    Severity.REVIEW: "REVIEW",
    Severity.WARN: "ACCEPT",
    Severity.INFO: "ACCEPT",
}


@dataclass(frozen=True)
class Finding:
    """Un hallazgo de un eje.

    `canonical` es el `reason_code` del contrato que representa este hallazgo
    SI acaba siendo el que manda. `code` es el codigo descriptivo propio del
    motor, que viaja siempre. `detail` es prosa para el humano y NO entra en
    ninguna decision ni en ningun hash de decision del motor.
    """

    axis: str
    severity: Severity
    canonical: str | None
    code: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.axis not in AXES:
            raise ValueError(f"eje desconocido: {self.axis!r}")


def _f(axis: str, severity: Severity, canonical: str | None, code: str):
    def build(detail: str = "") -> Finding:
        return Finding(axis=axis, severity=severity, canonical=canonical, code=code, detail=detail)

    return build


# --------------------------------------------------------------------------
# Catalogo de hallazgos. Uno por regla: si una regla no tiene hallazgo propio,
# su decision no es explicable.
# --------------------------------------------------------------------------
# -- existencia / identidad -------------------------------------------------
UNRESOLVED_MENTION = _f(AXIS_EXISTENCE, Severity.REVIEW, "REVIEW_ENTITY", "UNRESOLVED_MENTION")
ENTITY_NOT_IN_SNAPSHOT = _f(AXIS_EXISTENCE, Severity.REVIEW, "REVIEW_ENTITY", "ENTITY_NOT_IN_SNAPSHOT")
ENTITY_PROVISIONAL = _f(AXIS_EXISTENCE, Severity.REVIEW, "REVIEW_ENTITY", "ENTITY_PROVISIONAL")
ENTITY_RESOLUTION_DEFERRED = _f(AXIS_EXISTENCE, Severity.REVIEW, "REVIEW_ENTITY", "ENTITY_RESOLUTION_DEFERRED")
ENTITY_LOW_CONFIDENCE = _f(AXIS_EXISTENCE, Severity.REVIEW, "REVIEW_ENTITY", "ENTITY_LOW_CONFIDENCE")
ENTITY_ROLE_AMBIGUOUS = _f(AXIS_EXISTENCE, Severity.REVIEW, "REVIEW_ENTITY", "ENTITY_ROLE_AMBIGUOUS")
ENTITY_TYPE_UNKNOWN = _f(AXIS_EXISTENCE, Severity.REVIEW, "REVIEW_ENTITY", "ENTITY_TYPE_UNKNOWN")
SELF_RELATION = _f(AXIS_EXISTENCE, Severity.REJECT, "DEMONSTRABLY_FALSE", "SELF_RELATION")
CLAIM_ABSTAINED_UPSTREAM = _f(AXIS_EXISTENCE, Severity.ABSTAIN, "INSUFFICIENT_EVIDENCE", "CLAIM_ABSTAINED_UPSTREAM")

# -- evidencia --------------------------------------------------------------
EVIDENCE_FRAGMENT_UNKNOWN = _f(AXIS_EVIDENCE, Severity.ABSTAIN, "INSUFFICIENT_EVIDENCE", "EVIDENCE_FRAGMENT_UNKNOWN")
EVIDENCE_EPISODE_UNKNOWN = _f(AXIS_EVIDENCE, Severity.ABSTAIN, "INSUFFICIENT_EVIDENCE", "EVIDENCE_EPISODE_UNKNOWN")
EVIDENCE_FOREIGN_ASSET = _f(AXIS_EVIDENCE, Severity.REJECT, "DEMONSTRABLY_FALSE", "EVIDENCE_FOREIGN_ASSET")
EVIDENCE_TEXT_MISMATCH = _f(AXIS_EVIDENCE, Severity.REVIEW, "REVIEW_EVIDENCE", "EVIDENCE_TEXT_MISMATCH")
EVIDENCE_OFFSETS_OUT_OF_RANGE = _f(AXIS_EVIDENCE, Severity.REVIEW, "REVIEW_EVIDENCE", "EVIDENCE_OFFSETS_OUT_OF_RANGE")
EVIDENCE_NOT_VERIFIABLE = _f(AXIS_EVIDENCE, Severity.WARN, None, "EVIDENCE_NOT_VERIFIABLE")
EVIDENCE_LOW_CONFIDENCE = _f(AXIS_EVIDENCE, Severity.WARN, None, "EVIDENCE_LOW_CONFIDENCE")
#: Suelo DURO de confianza para aprobar, por debajo de cualquier umbral
#: configurable. Existe porque una configuracion con todos los umbrales a 0
#: convertia el motor en un sello de goma.
CONFIDENCE_BELOW_HARD_FLOOR = _f(AXIS_EVIDENCE, Severity.REVIEW, "REVIEW_EVIDENCE", "CONFIDENCE_BELOW_HARD_FLOOR")
EVIDENCE_LITERAL_VERIFIED = _f(AXIS_EVIDENCE, Severity.INFO, None, "EVIDENCE_LITERAL_VERIFIED")
LOW_QUALITY_EPISODE = _f(AXIS_EVIDENCE, Severity.ABSTAIN, "LOW_QUALITY_EPISODE", "LOW_QUALITY_EPISODE")
CLAIM_LOW_CONFIDENCE = _f(AXIS_EVIDENCE, Severity.REVIEW, "REVIEW_EVIDENCE", "CLAIM_LOW_CONFIDENCE")
EXTRACTOR_REQUESTED_REVIEW = _f(AXIS_EVIDENCE, Severity.REVIEW, "REVIEW_EVIDENCE", "EXTRACTOR_REQUESTED_REVIEW")

# -- predicado --------------------------------------------------------------
PREDICATE_ABSENT = _f(AXIS_PREDICATE, Severity.ABSTAIN, "AMBIGUOUS_SEMANTICS", "PREDICATE_ABSENT")
PREDICATE_OUT_OF_ONTOLOGY = _f(AXIS_PREDICATE, Severity.REJECT, "ONTOLOGY_INCOMPATIBLE", "PREDICATE_OUT_OF_ONTOLOGY")
PREDICATE_TYPE_INCOMPATIBLE = _f(AXIS_PREDICATE, Severity.REJECT, "TYPE_INCOMPATIBLE", "PREDICATE_TYPE_INCOMPATIBLE")
PREDICATE_AMBIGUOUS = _f(AXIS_PREDICATE, Severity.REVIEW, "REVIEW_PREDICATE", "PREDICATE_AMBIGUOUS")
PREDICATE_LOW_CONFIDENCE = _f(AXIS_PREDICATE, Severity.REVIEW, "REVIEW_PREDICATE", "PREDICATE_LOW_CONFIDENCE")
PREDICATE_DEMOTED = _f(AXIS_PREDICATE, Severity.WARN, None, "PREDICATE_DEMOTED")

# -- direccion --------------------------------------------------------------
DIRECTION_UNDETERMINED = _f(AXIS_DIRECTION, Severity.REVIEW, "REVIEW_DIRECTION", "DIRECTION_UNDETERMINED")
DIRECTION_LOW_CONFIDENCE = _f(AXIS_DIRECTION, Severity.REVIEW, "REVIEW_DIRECTION", "DIRECTION_LOW_CONFIDENCE")
DIRECTION_TYPE_MISMATCH = _f(AXIS_DIRECTION, Severity.REVIEW, "REVIEW_DIRECTION", "DIRECTION_TYPE_MISMATCH")
DIRECTION_AMBIGUOUS = _f(AXIS_DIRECTION, Severity.REVIEW, "REVIEW_DIRECTION", "DIRECTION_AMBIGUOUS")
SYMMETRIC_PREDICATE = _f(AXIS_DIRECTION, Severity.INFO, None, "SYMMETRIC_PREDICATE")

# -- negacion ---------------------------------------------------------------
NEGATED_CLAIM = _f(AXIS_NEGATION, Severity.WARN, None, "NEGATED_CLAIM")
NEGATION_NOT_ACCEPTED = _f(AXIS_NEGATION, Severity.REVIEW, "REVIEW_EVIDENCE", "NEGATION_NOT_ACCEPTED")

# -- epistemicidad ----------------------------------------------------------
EPISTEMIC_NOT_ASSERTED = _f(AXIS_EPISTEMIC, Severity.REVIEW, "REVIEW_EVIDENCE", "EPISTEMIC_NOT_ASSERTED")
EPISTEMIC_VISUAL_INFERRED = _f(AXIS_EPISTEMIC, Severity.REVIEW, "REVIEW_EVIDENCE", "EPISTEMIC_VISUAL_INFERRED")
EPISTEMIC_UNKNOWN = _f(AXIS_EPISTEMIC, Severity.ABSTAIN, "AMBIGUOUS_SEMANTICS", "EPISTEMIC_UNKNOWN")

# -- temporalidad -----------------------------------------------------------
TEMPORAL_UNSPECIFIED = _f(AXIS_TEMPORAL, Severity.INFO, None, "TEMPORAL_UNSPECIFIED")
TEMPORAL_UNRESOLVED_RELATIVE = _f(AXIS_TEMPORAL, Severity.WARN, None, "TEMPORAL_UNRESOLVED_RELATIVE")
TEMPORAL_CONFLICTING_EXPRESSIONS = _f(AXIS_TEMPORAL, Severity.REVIEW, "REVIEW_TEMPORALITY", "TEMPORAL_CONFLICTING_EXPRESSIONS")
TEMPORAL_INTERVAL_INVERTED = _f(AXIS_TEMPORAL, Severity.REVIEW, "REVIEW_TEMPORALITY", "TEMPORAL_INTERVAL_INVERTED")
TEMPORAL_CALENDAR_UNKNOWN = _f(AXIS_TEMPORAL, Severity.REVIEW, "REVIEW_TEMPORALITY", "TEMPORAL_CALENDAR_UNKNOWN")
TEMPORAL_FRAGMENT_UNKNOWN = _f(AXIS_TEMPORAL, Severity.REVIEW, "REVIEW_TEMPORALITY", "TEMPORAL_FRAGMENT_UNKNOWN")
TEMPORAL_CALENDAR_MIXED = _f(AXIS_TEMPORAL, Severity.REVIEW, "REVIEW_TEMPORALITY", "TEMPORAL_CALENDAR_MIXED")

# -- contradiccion ----------------------------------------------------------
# Contra el SNAPSHOT (lo que el grafo ya dice)...
CONTRADICTS_VIGENTE = _f(AXIS_CONTRADICTION, Severity.REVIEW, "CONFLICT_WITH_EXISTING", "CONTRADICTS_VIGENTE_ASSERTION")
DIRECTION_CONFLICT = _f(AXIS_CONTRADICTION, Severity.REVIEW, "CONFLICT_WITH_EXISTING", "DIRECTION_CONFLICT_WITH_VIGENTE")
FUNCTIONAL_CONFLICT = _f(AXIS_CONTRADICTION, Severity.REVIEW, "CONFLICT_WITH_EXISTING", "FUNCTIONAL_PREDICATE_CONFLICT")
ALREADY_ASSERTED = _f(AXIS_CONTRADICTION, Severity.WARN, None, "ALREADY_ASSERTED")
#: Reafirmar una de las dos caras de un conflicto que un humano marco como
#: CONTRADICTED y todavia no ha resuelto. No es un duplicado: es colarse por
#: delante de la cola de revision reprocesando el asset.
UNRESOLVED_CONFLICT = _f(AXIS_CONTRADICTION, Severity.REVIEW, "CONFLICT_WITH_EXISTING", "REAFFIRMS_CONTRADICTED_ASSERTION")

# ...y contra el PROPIO LOTE (lo que este mismo plan esta a punto de escribir).
# Sin esta familia, dos claims opuestos del mismo documento se aprueban los dos
# y el grafo queda internamente incoherente en una sola escritura.
BATCH_CONTRADICTION = _f(AXIS_CONTRADICTION, Severity.REVIEW, "CONFLICT_WITH_EXISTING", "CONTRADICTS_CLAIM_IN_BATCH")
BATCH_DIRECTION_CONFLICT = _f(AXIS_CONTRADICTION, Severity.REVIEW, "CONFLICT_WITH_EXISTING", "DIRECTION_CONFLICT_IN_BATCH")
BATCH_FUNCTIONAL_CONFLICT = _f(AXIS_CONTRADICTION, Severity.REVIEW, "CONFLICT_WITH_EXISTING", "FUNCTIONAL_CONFLICT_IN_BATCH")
BATCH_DUPLICATE = _f(AXIS_CONTRADICTION, Severity.WARN, None, "DUPLICATE_IN_BATCH")

# -- autoridad --------------------------------------------------------------
EXTERNAL_PROPOSAL = _f(AXIS_AUTHORITY, Severity.WARN, None, "EXTERNAL_PROPOSAL")
OLLAMA_PROPOSAL = _f(AXIS_AUTHORITY, Severity.WARN, None, "OLLAMA_PROPOSAL")
EXTERNAL_SIGNAL_CONSULTED = _f(AXIS_AUTHORITY, Severity.INFO, None, "EXTERNAL_SIGNAL_CONSULTED")
EXTERNAL_SIGNAL_DISSENTS = _f(AXIS_AUTHORITY, Severity.REVIEW, "REVIEW_PREDICATE", "EXTERNAL_SIGNAL_DISSENTS")


def worst(findings: Iterable[Finding]) -> Severity:
    """Gravedad maxima de un conjunto de hallazgos (INFO si esta vacio)."""
    return max((f.severity for f in findings), default=Severity.INFO)


def decision_for(findings: Iterable[Finding]) -> str:
    """Decision del contrato que corresponde a estos hallazgos."""
    return SEVERITY_DECISION[worst(findings)]


def reason_codes_for(findings: Iterable[Finding], decision: str) -> list[str]:
    """`reason_codes` de la decision: canonico ganador + descriptivos.

    Reglas:
      * se incluye el canonico de CADA hallazgo cuya gravedad es la ganadora
        (asi una decision con dos motivos canonicos los lleva los dos);
      * se incluyen TODOS los codigos descriptivos, tambien los de gravedad
        inferior: un aviso que no cambio la decision sigue siendo parte de la
        explicacion;
      * el resultado va ordenado y sin duplicados, para que el `decision_hash`
        no dependa del orden de evaluacion.
    """
    findings = list(findings)
    top = worst(findings)
    codes = {f.code for f in findings}
    codes |= {f.canonical for f in findings if f.severity is top and f.canonical}
    if decision == "ACCEPT":
        # El contrato exige un canonico de ACCEPT; con avisos, es el "con avisos".
        has_warning = any(f.severity is Severity.WARN for f in findings)
        codes.add("LOCAL_APPROVED_WITH_WARNINGS" if has_warning else "LOCAL_APPROVED")
    return sorted(codes)
