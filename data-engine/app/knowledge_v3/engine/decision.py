# -*- coding: utf-8 -*-
"""Decision del motor sobre UN claim: agregacion determinista de los ejes.

Las doce etapas del dosier 11.2 se recorren siempre, en orden y completas: no
hay cortocircuito. Un claim que ya se sabe que ira a revision sigue pasando por
temporalidad y contradiccion, porque la decision tiene que llevar TODAS sus
razones, no solo la primera que aparecio. Un motor que corta en el primer
"no" produce explicaciones que dependen del orden de evaluacion, y eso no es
auditable.

Despues de los ejes hay una capa de INVARIANTES. No es decoracion defensiva:
es el sitio donde viven las reglas que no admiten umbral.

    1. no hay ACCEPT sin evidencia literal VERIFICADA;
    2. no hay ACCEPT con una contradiccion vigente NI con una contradiccion
       dentro del propio lote (la segunda mitad faltaba: hallazgo H1);
    3. no hay ACCEPT sin predicado, direccion, sujeto y objeto fijados;
    4. no hay ACCEPT por debajo del suelo duro de confianza
       (`HARD_CONFIDENCE_FLOOR`), pase lo que pase en la configuracion.

Ninguna tiene flag en `EngineConfig`, y hay tests de mutacion que lo demuestran
quitandolas.

La contradiccion tiene DOS pasadas y la segunda no puede vivir aqui: comparar
un claim con los demas del lote exige verlos todos. Por eso el motor decide
claim a claim y despues llama a `apply_batch_contradictions` sobre el conjunto,
ANTES de construir ningun plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..contracts.claim import ClaimProposal
from . import findings as F
from . import signals as sig
from .config import HARD_CONFIDENCE_FLOOR, EngineConfig
from .contradiction import (
    BatchClaimKey,
    ContradictionOutcome,
    batch_conflicts,
    check_contradictions,
)
from .evidence import EvidenceIndex, evidence_confidence, verify_evidence
from .identity import ResolutionIndex, Role, resolve_identity
from .negation import NegationOutcome, resolve_negation
from .ontology import ProfileIndex, canonical_key, resolve_direction, resolve_predicate
from .snapshot import GraphSnapshot, SnapshotAssertion
from .temporal import TemporalOutcome, resolve_temporality

#: Estatus epistemico de una decision en conflicto. El contrato tiene el valor
#: `CONFLICTED` precisamente para esto: la relacion no es que sea dudosa, es que
#: el corpus dice dos cosas.
CONFLICTED = "CONFLICTED"


@dataclass
class ClaimDecision:
    """Decision del motor sobre un claim, con todo lo necesario para explicarla."""

    claim_id: str
    decision: str
    findings: list[F.Finding]
    predicate: Optional[str] = None
    direction: Optional[str] = None
    subject_entity_id: Optional[str] = None
    object_entity_id: Optional[str] = None
    epistemic_status: str = "UNKNOWN"
    negated: bool = False
    confidence: float = 0.0
    evidence_fragment_ids: list[str] = field(default_factory=list)
    episode_id: str = ""
    temporal: Optional[TemporalOutcome] = None
    conflicts: tuple[SnapshotAssertion, ...] = ()
    duplicate_of: Optional[SnapshotAssertion] = None
    #: Aceptada, pero otro claim del MISMO lote ya escribe exactamente esto.
    #: No es un rechazo: es que la escritura ya esta cubierta.
    duplicate_in_batch: bool = False
    #: Tipo de negacion leido de `metadata.negation_kind` (vacio si no niega).
    negation_kind: str = ""
    #: Afirmacion POSITIVA vigente que una CESACION propone cerrar. No es un
    #: conflicto: es una transicion, y el plan la materializa con un
    #: `SUPERSEDE_ASSERTION` ademas de la afirmacion negativa.
    supersedes: Optional[SnapshotAssertion] = None

    @property
    def decision_id(self) -> str:
        """Derivado del claim: la misma entrada produce el mismo identificador."""
        return f"decision:{self.claim_id}"

    @property
    def accepted(self) -> bool:
        return self.decision == "ACCEPT"

    @property
    def writes(self) -> bool:
        """Aceptada Y no duplicada — ni contra el grafo ni dentro del lote."""
        return self.accepted and self.duplicate_of is None and not self.duplicate_in_batch

    def canonical_key(self, index: ProfileIndex) -> Optional[tuple[str, str, str]]:
        """Clave canonica de lo que esta decision escribiria, si escribe algo."""
        if not (self.predicate and self.direction and self.subject_entity_id and self.object_entity_id):
            return None
        return canonical_key(
            index, self.subject_entity_id, self.object_entity_id, self.predicate, self.direction
        )

    def reason_codes(self) -> list[str]:
        return F.reason_codes_for(self.findings, self.decision)

    def explanation(self) -> list[str]:
        """Razones legibles, en el orden de los ejes. Para el humano, no para el hash."""
        return [f"[{f.axis}/{f.severity.name}] {f.code}: {f.detail}" for f in self.findings]

    def to_contract_dict(self) -> dict:
        """Bloque `decisions[]` del `GraphMutationPlan`."""
        return {
            "decision_id": self.decision_id,
            "claim_id": self.claim_id,
            "decision": self.decision,
            "predicate": self.predicate,
            "direction": self.direction,
            "subject_entity_id": self.subject_entity_id,
            "object_entity_id": self.object_entity_id,
            "epistemic_status": self.epistemic_status,
            "negated": self.negated,
            "confidence": self.confidence,
            "reason_codes": self.reason_codes(),
            "evidence_fragment_ids": list(self.evidence_fragment_ids),
        }


def _confidence(*values: float) -> float:
    """Confianza del motor: el MINIMO de las confianzas que la sostienen.

    Entran TODAS: la del claim, la del predicado, la de la direccion, las de
    las dos resoluciones de identidad y —desde el hallazgo H3— la del fragmento
    de evidencia y la calidad del episodio. Faltaban las dos ultimas, y con
    ellas fuera un claim de 0.99 anclado en evidencia de 0.50 escribia 0.99:
    cualquier consumidor que filtrase por confianza quedaba enganado sobre la
    calidad de la fuente.

    Nunca por encima de ninguna de sus partes. Multiplicarlas seria mas
    "elegante" y castigaria dos veces lo mismo; promediarlas dejaria que una
    identidad dudosa quedase tapada por un predicado seguro. El minimo dice lo
    que de verdad importa: la cadena vale lo que su eslabon mas debil.
    """
    return round(min(values), 6)


def _authority_findings(claim: ClaimProposal) -> list[F.Finding]:
    """Quien PROPUSO el claim. No cambia quien decide, pero se hace constar."""
    provider = claim.producing_provider().get("provider")
    if provider == "external":
        return [F.EXTERNAL_PROPOSAL(f"claim propuesto por {claim.producing_provider().get('name')}")]
    if provider == "ollama":
        return [F.OLLAMA_PROPOSAL(f"claim propuesto por {claim.producing_provider().get('name')}")]
    return []


def _epistemic_findings(claim: ClaimProposal, config: EngineConfig) -> list[F.Finding]:
    hint = claim.epistemic_status_hint
    if hint in config.acceptable_epistemic_status:
        return []
    if hint == "VISUAL_INFERRED":
        return [F.EPISTEMIC_VISUAL_INFERRED("lectura de un dibujo/diagrama, no una afirmacion")]
    if hint == "UNKNOWN":
        return [F.EPISTEMIC_UNKNOWN("el extractor no supo situar la afirmacion")]
    return [F.EPISTEMIC_NOT_ASSERTED(f"estatus {hint}: no es una afirmacion del mundo")]


def _enforce_invariants(
    decision: str,
    findings: list[F.Finding],
    predicate: Optional[str],
    direction: Optional[str],
    subject: Role,
    obj: Role,
    contradictions: ContradictionOutcome,
    confidence: float = 1.0,
) -> str:
    """Las reglas sin umbral. Solo pueden endurecer la decision."""
    if decision != "ACCEPT":
        return decision
    extra: list[F.Finding] = []
    if confidence < HARD_CONFIDENCE_FLOOR:
        extra.append(
            F.CONFIDENCE_BELOW_HARD_FLOOR(
                f"{confidence:.3f} < suelo duro {HARD_CONFIDENCE_FLOOR}: ningun umbral "
                "configurable puede bajar de aqui"
            )
        )
    if not any(f.code == "EVIDENCE_LITERAL_VERIFIED" for f in findings):
        extra.append(
            F.EVIDENCE_NOT_VERIFIABLE("invariante: ACCEPT exige una cita cotejada contra el episodio")
        )
        extra.append(F.CLAIM_LOW_CONFIDENCE("sin evidencia verificada no se aprueba"))
    if contradictions.has_conflict:  # pragma: no cover - el eje ya lo marca
        extra.append(F.CONTRADICTS_VIGENTE("invariante: una contradiccion nunca se auto-aprueba"))
    if not (predicate and direction and subject.entity_id and obj.entity_id):
        extra.append(
            F.PREDICATE_ABSENT("invariante: ACCEPT exige predicado, direccion, sujeto y objeto")
        )
    if not extra:
        return decision
    findings.extend(extra)
    return F.decision_for(findings)


def decide_claim(
    claim: ClaimProposal,
    *,
    resolutions: ResolutionIndex,
    evidence: EvidenceIndex,
    profile: ProfileIndex,
    snapshot: GraphSnapshot,
    config: EngineConfig,
    claim_signals: Sequence[sig.ExternalSignal] = (),
) -> ClaimDecision:
    """Recorre los ejes y agrega. Funcion pura: no escribe nada, no consulta red."""
    findings: list[F.Finding] = []

    # 1-2. existencia e identidad
    identity = resolve_identity(claim, resolutions, snapshot, config)
    findings.extend(identity.findings)

    # 3. evidencia
    findings.extend(verify_evidence(claim, evidence, config))
    evidence_floor = evidence_confidence(claim, evidence)
    if claim.confidence < config.min_claim_confidence and not claim.abstained:
        findings.append(
            F.CLAIM_LOW_CONFIDENCE(f"{claim.confidence} < {config.min_claim_confidence}")
        )
    if claim.review_required:
        findings.append(F.EXTRACTOR_REQUESTED_REVIEW("el extractor marco review_required"))

    # 4. predicado
    predicate_outcome = resolve_predicate(
        claim.predicate_candidates,
        profile,
        identity.subject.entity_type,
        identity.object.entity_type,
        config,
    )
    findings.extend(predicate_outcome.findings)

    # 5. direccion
    direction: Optional[str] = None
    direction_confidence = 0.0
    spec = profile.spec(predicate_outcome.predicate) if predicate_outcome.predicate else None
    if spec is not None:
        direction_outcome = resolve_direction(
            claim.direction_candidates,
            spec,
            identity.subject.entity_type,
            identity.object.entity_type,
            config,
        )
        findings.extend(direction_outcome.findings)
        direction = direction_outcome.direction
        direction_confidence = direction_outcome.confidence

    # 6. negacion  7. epistemicidad
    #
    # La negacion ya no es un booleano: `engine/negation.py` distingue SIMPLE,
    # NEVER, CESSATION, NOT_YET y el alcance ambiguo, y en la cesacion busca la
    # positiva vigente que se cerraria. Se resuelve ANTES de la contradiccion
    # porque una cesacion NO es una contradiccion con lo que cierra: es una
    # transicion, y tratarla como choque mandaria a revision toda evolucion
    # temporal legitima del grafo.
    negation = resolve_negation(
        claim,
        index=profile,
        snapshot=snapshot,
        subject_entity_id=identity.subject.entity_id,
        object_entity_id=identity.object.entity_id,
        predicate=predicate_outcome.predicate,
        direction=direction,
        config=config,
    )
    findings.extend(negation.findings)
    findings.extend(_epistemic_findings(claim, config))

    # 8. temporalidad
    temporal = resolve_temporality(claim, profile, frozenset(evidence.fragments))
    findings.extend(temporal.findings)

    # 9-11. contradiccion contra el grafo vigente
    contradictions = ContradictionOutcome((), None, ())
    if predicate_outcome.predicate and direction and identity.subject.entity_id and identity.object.entity_id:
        contradictions = check_contradictions(
            profile,
            snapshot,
            identity.subject.entity_id,
            identity.object.entity_id,
            predicate_outcome.predicate,
            direction,
            claim.negated,
            # La afirmacion que la cesacion cierra queda FUERA del eje: separadas
            # en el tiempo, la positiva y la negativa no se contradicen. Lo que
            # NO queda fuera es ninguna otra: una cesacion sigue pudiendo chocar
            # con el resto del grafo.
            skip_assertion_ids=(
                frozenset({negation.closes.assertion_id}) if negation.closes else frozenset()
            ),
        )
        findings.extend(contradictions.findings)

    # Autoridad: quien propuso, y que opinan las senales no locales.
    findings.extend(_authority_findings(claim))
    findings.extend(
        sig.contribute(
            claim_signals,
            local_predicate=predicate_outcome.predicate,
            local_direction=direction,
        )
    )

    # 12. decision
    confidence = _confidence(
        claim.confidence,
        predicate_outcome.confidence,
        direction_confidence,
        identity.subject.confidence,
        identity.object.confidence,
        evidence_floor,
    )
    decision = F.decision_for(findings)
    decision = _enforce_invariants(
        decision,
        findings,
        predicate_outcome.predicate,
        direction,
        identity.subject,
        identity.object,
        contradictions,
        confidence,
    )

    epistemic = CONFLICTED if contradictions.has_conflict else claim.epistemic_status_hint
    return ClaimDecision(
        claim_id=claim.claim_id,
        decision=decision,
        findings=findings,
        predicate=predicate_outcome.predicate,
        direction=direction,
        subject_entity_id=identity.subject.entity_id,
        object_entity_id=identity.object.entity_id,
        epistemic_status=epistemic,
        negated=claim.negated,
        confidence=confidence,
        evidence_fragment_ids=list(claim.evidence_fragment_ids),
        episode_id=claim.episode_id,
        temporal=temporal,
        conflicts=contradictions.conflicts,
        duplicate_of=contradictions.duplicate_of,
        negation_kind=negation.kind,
        supersedes=negation.closes,
    )


# --------------------------------------------------------------------------
# Segunda pasada de contradiccion: el lote contra si mismo
# --------------------------------------------------------------------------
def apply_batch_contradictions(
    decisions: Sequence[ClaimDecision], profile: ProfileIndex
) -> list[ClaimDecision]:
    """Contrasta las decisiones del lote entre si y las endurece si procede.

    Necesaria porque `decide_claim` ve UN claim: puede contrastarlo contra todo
    el grafo y no contra su vecino de pagina. Sin esta pasada, un documento que
    afirma y niega lo mismo producia dos `ACCEPT` y un plan firmado, valido para
    el contrato congelado, que dejaba el grafo incoherente de una sentada
    (hallazgo H1 de la revision independiente).

    Solo entran en la comparacion las decisiones que ESCRIBIRIAN algo: una que
    ya va a revision no puede volver a estropear nada, y arrastrarla aqui haria
    que un claim rechazado degradase a uno bueno.

    Endurece, nunca ablanda: se anaden hallazgos y se recalcula la decision con
    la misma funcion de agregacion. Como todos los hallazgos nuevos son `REVIEW`
    o `WARN`, el resultado solo puede quedarse igual o ponerse mas estricto.
    """
    decisions = list(decisions)
    by_ref = {d.decision_id: d for d in decisions}
    items: list[BatchClaimKey] = []
    for decision in decisions:
        if not decision.writes:
            continue
        key = decision.canonical_key(profile)
        if key is None:  # pragma: no cover - `writes` ya lo garantiza
            continue
        spec = profile.spec(key[1])
        items.append(
            BatchClaimKey(
                ref=decision.decision_id,
                key=key,
                negated=decision.negated,
                functional=bool(spec and spec.functional),
            )
        )

    for ref, new_findings in batch_conflicts(profile, items).items():
        decision = by_ref[ref]
        decision.findings.extend(new_findings)
        if any(f.code == "DUPLICATE_IN_BATCH" for f in new_findings):
            decision.duplicate_in_batch = True
        if any(f.severity is F.Severity.REVIEW for f in new_findings):
            decision.epistemic_status = CONFLICTED
        decision.decision = F.decision_for(decision.findings)
    return decisions
