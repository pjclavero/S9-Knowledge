# -*- coding: utf-8 -*-
"""Construccion y sellado del `GraphMutationPlan`.

Lo que sale de aqui es lo UNICO que el writer admite. Por eso este modulo:

* construye operaciones **solo** desde decisiones `ACCEPT` (el validador
  congelado ademas lo exige, asi que un fallo aqui es rojo dos veces);
* copia `expected_version` y `expected_hash` DEL SNAPSHOT, no de la nada:
  concurrencia optimista real;
* **no reimplementa ningun hash**. `idempotency_key`, `decision_hash` y
  `plan_hash` los calcula `seal_plan` del validador congelado. Reimplementar la
  formula aqui habria creado dos verdades sobre la misma firma, y el dia que
  divergiesen el writer habria rechazado planes correctos — o aceptado planes
  incorrectos;
* aprueba solo si TODA su cadena de validadores da PASS, no hay ninguna
  decision `REVIEW` y hay al menos una operacion. Si algo falla, el plan sale
  **sin aprobar**: no se lanza una excepcion y se pierde el trabajo, se
  entrega un plan explicito que dice por que no se aprueba.

Las decisiones `REVIEW` van a un plan aparte, tambien sellado y tambien valido,
con `approved: false`. Es consecuencia directa del contrato congelado (un plan
aprobado no puede llevar `REVIEW` pendientes): sin separar, un solo claim
dudoso bloquearia el lote entero y la presion por "quitar el dudoso" seria
exactamente la presion que degrada un sistema de revision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from ..contracts import GraphMutationPlan
from ..contracts.assertion import FactAssertion
from ..contracts.base import V3ContractError, provider_step, seal_plan, sha256_hash
from . import findings as F
from .config import ENGINE_NAME, ENGINE_VERSION, STEP_DECIDE, STEP_PLAN, EngineConfig
from .decision import ClaimDecision
from .errors import EnginePlanError
from .signals import RESERVED_STEPS
from .ontology import ProfileIndex, canonical_key
from .snapshot import GraphSnapshot

CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class PlanContext:
    """Todo lo que el plan necesita saber y el motor no puede inventarse."""

    workspace: str
    source_asset_id: str
    source_hash: dict
    collection_id: str
    game_profile: str
    ontology_version: str
    snapshot: GraphSnapshot
    #: Instante del plan, INYECTADO. El motor no llama a `now()`: si lo hiciera,
    #: dos ejecuciones sobre la misma entrada darian planes distintos y nada
    #: seria reproducible ni comparable en un benchmark.
    now: str
    engine_version: str = ENGINE_VERSION

    def expires_at(self, ttl_seconds: int) -> str:
        moment = datetime.strptime(self.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (moment + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_assertion_id(context: PlanContext, decision: ClaimDecision) -> str:
    """Identificador DERIVADO de la identidad logica de la afirmacion.

    La misma afirmacion, calculada dos veces, lleva el mismo id. No entra ni la
    hora, ni el claim, ni el orden del lote: si entrasen, dos ejecuciones del
    mismo corpus crearian dos afirmaciones distintas para el mismo hecho.
    """
    body = {
        "workspace": context.workspace,
        "collection_id": context.collection_id,
        "subject_entity_id": decision.subject_entity_id,
        "object_entity_id": decision.object_entity_id,
        "predicate": decision.predicate,
        "direction": decision.direction,
        "negated": decision.negated,
    }
    return "assertion:" + sha256_hash(body)["value"][:32]


def assertion_for(
    context: PlanContext, decision: ClaimDecision, proposal_step: Optional[dict]
) -> FactAssertion:
    """`FactAssertion` de una decision aceptada. Valida contra el contrato."""
    temporal = decision.temporal
    trace = [provider_step(STEP_DECIDE, "local", ENGINE_NAME, context.engine_version, ["predicate", "direction", "state", "status"])]
    if proposal_step and proposal_step.get("step") != STEP_DECIDE:
        trace.insert(0, proposal_step)
    doc = FactAssertion(
        contract_version=CONTRACT_VERSION,
        workspace=context.workspace,
        source_asset_id=context.source_asset_id,
        source_hash=context.source_hash,
        provider_trace=trace,
        produced_by_step=STEP_DECIDE,
        assertion_id=derive_assertion_id(context, decision),
        subject_entity_id=decision.subject_entity_id,
        object_entity_id=decision.object_entity_id,
        predicate=decision.predicate,
        direction=decision.direction,
        valid_from=temporal.valid_from if temporal else None,
        valid_to=temporal.valid_to if temporal else None,
        recorded_at=context.now,
        epistemic_status=decision.epistemic_status,
        confidence=decision.confidence,
        status="ASSERTED" if decision.epistemic_status == "ASSERTED" else "PROVISIONAL",
        state=temporal.state if temporal else "UNKNOWN",
        event_time=temporal.event_time if temporal else None,
        negated=decision.negated,
        collection_id=context.collection_id,
        game_profile=context.game_profile,
        engine_version=context.engine_version,
        ontology_version=context.ontology_version,
        evidence_fragment_ids=list(decision.evidence_fragment_ids),
        episode_ids=[decision.episode_id],
        # CESACION: la afirmacion negativa SUCEDE a la positiva vigente. No la
        # borra ni la reescribe: el ledger conserva la anterior con su evidencia
        # y la marca `SUPERSEDED`. Para cualquier otro caso, `None`.
        supersedes=decision.supersedes.assertion_id if decision.supersedes else None,
        superseded_by=None,
        calendar_id=temporal.calendar_id if temporal else None,
    )
    doc.validate()
    return doc


#: Campos de la afirmacion que viajan en el `payload` de la operacion.
#: `recorded_at` y la traza NO estan: son volatiles, y meterlos haria que la
#: `idempotency_key` (que se deriva del payload) cambiase en cada ejecucion —
#: es decir, destruiria la idempotencia que el contrato exige.
PAYLOAD_FIELDS = (
    "subject_entity_id",
    "object_entity_id",
    "predicate",
    "direction",
    "negated",
    "epistemic_status",
    "status",
    "state",
    "event_time",
    "valid_from",
    "valid_to",
    "calendar_id",
    "confidence",
    "collection_id",
    "game_profile",
    "ontology_version",
    "evidence_fragment_ids",
    "episode_ids",
)


def _cessation_valid_to(decision: ClaimDecision) -> Optional[str]:
    """Instante en que se cierra la vigencia anterior, si el texto lo fecha.

    Se prefiere `valid_from` de la cesacion —"desde la primavera de 1042 ya no
    lidera" cierra en la primavera de 1042— y, si no lo hay, `event_time`. Sin
    ninguno de los dos, `None`: una vigencia sin fecha de cierre es honesta; una
    fecha inventada, no.
    """
    temporal = decision.temporal
    if temporal is None:
        return None
    return temporal.valid_from or temporal.event_time


def _operations(
    context: PlanContext, decision: ClaimDecision, assertion: FactAssertion, config: EngineConfig
) -> list[dict]:
    doc = assertion.to_dict()
    payload = {k: doc[k] for k in PAYLOAD_FIELDS if k in doc}
    ops = [
        {
            "operation_id": f"op:{decision.claim_id}:assert",
            "operation_type": "CREATE_ASSERTION",
            "decision_id": decision.decision_id,
            "target_entity_id": None,
            "assertion_id": assertion.assertion_id,
            "payload": payload,
            "evidence_fragment_ids": list(decision.evidence_fragment_ids),
            "idempotency_key": "",  # lo deriva seal_plan
            "expected_state": "WOULD_CREATE",
            "expected_version": None,
            "expected_hash": None,
        }
    ]
    if decision.supersedes is not None:
        # Cierre de la vigencia anterior. Va con `expected_version` y
        # `expected_hash` de la afirmacion del snapshot: si otro proceso la
        # cambio entre el snapshot y el apply, el writer rechaza la operacion.
        # El writer EJECUTA; no interpreta que es una cesacion ni por que.
        previa = decision.supersedes
        ops.append(
            {
                "operation_id": f"op:{decision.claim_id}:supersede",
                "operation_type": "SUPERSEDE_ASSERTION",
                "decision_id": decision.decision_id,
                "target_entity_id": None,
                "assertion_id": previa.assertion_id,
                "payload": {
                    "superseded_by": assertion.assertion_id,
                    "status": "SUPERSEDED",
                    # `valid_to` sale de la temporalidad del claim de cesacion.
                    # Si el texto no la fecha, sale `None` y el cierre queda sin
                    # fecha: inventarla seria escribir una vigencia que nadie
                    # cerro.
                    "valid_to": _cessation_valid_to(decision),
                    # R1 del writer: una vigencia no se cierra sin motivo. El
                    # writer lo transporta al grafo; no lo interpreta.
                    "reason_code": "CESSATION_ASSERTED",
                },
                "evidence_fragment_ids": list(decision.evidence_fragment_ids),
                "idempotency_key": "",
                "expected_state": "WOULD_UPDATE",
                "expected_version": previa.version,
                "expected_hash": previa.state_hash,
            }
        )
    if not config.emit_projection:
        return ops
    if decision.negated:
        # Un hecho NEGATIVO no tiene arista positiva que proyectar. La
        # afirmacion queda en el ledger con `negated=true`; el grafo no aprende
        # una relacion que el texto niega.
        return ops
    node = context.snapshot.entity(decision.subject_entity_id)
    if node is None:  # pragma: no cover - la identidad ya exigio que exista
        return ops
    ops.append(
        {
            "operation_id": f"op:{decision.claim_id}:project",
            "operation_type": "PROJECT_RELATION",
            "decision_id": decision.decision_id,
            "target_entity_id": node.entity_id,
            "assertion_id": assertion.assertion_id,
            "payload": {
                "predicate": assertion.predicate,
                "direction": assertion.direction,
                "subject_entity_id": assertion.subject_entity_id,
                "object_entity_id": assertion.object_entity_id,
                "negated": assertion.negated,
            },
            "evidence_fragment_ids": list(decision.evidence_fragment_ids),
            "idempotency_key": "",
            "expected_state": "WOULD_UPDATE",
            "expected_version": node.version,
            "expected_hash": node.state_hash,
        }
    )
    return ops


def plan_is_self_consistent(operations: Sequence[dict], profile: ProfileIndex) -> bool:
    """Ninguna operacion del plan contradice o repite a otra del MISMO plan.

    Defensa en profundidad del hallazgo H1: la pasada de lote ya deberia haber
    mandado a revision cualquier par incoherente, pero este validador mira el
    artefacto FINAL —lo que de verdad se va a escribir— y no las decisiones que
    lo originaron. Si alguna vez se anade otra ruta que construya operaciones,
    la comprobacion sigue estando delante del writer.

    Se compara sobre la clave canonica, igual que el eje: decir lo mismo al
    reves, o con la inversa del predicado, no lo convierte en otra cosa.
    """
    seen: dict[tuple[str, str, str], bool] = {}
    pairs: dict[tuple[frozenset, str], tuple[str, str, str]] = {}
    for op in operations:
        if op["operation_type"] != "CREATE_ASSERTION":
            continue
        payload = op["payload"]
        key = canonical_key(
            profile,
            payload["subject_entity_id"],
            payload["object_entity_id"],
            payload["predicate"],
            payload["direction"],
        )
        negated = bool(payload["negated"])
        if key in seen:
            return False  # duplicado o contradiccion sobre la misma clave
        pair_key = (frozenset({key[0], key[2]}), key[1])
        if pair_key in pairs and pairs[pair_key] != key:
            return False  # misma pareja y predicado, orientacion contraria
        seen[key] = negated
        pairs[pair_key] = key
    return True


def _validator_chain(
    context: PlanContext,
    decisions: Sequence[ClaimDecision],
    operations: Sequence[dict],
    profile: ProfileIndex,
    structural_ok: bool,
    semantic_failures: Sequence[str],
) -> list[dict]:
    """Cadena de validadores del motor. Cada entrada dice QUE comprobo."""

    def entry(name: str, ok: bool, reasons: Iterable[str] = ()) -> dict:
        out = {"validator": name, "version": context.engine_version, "result": "PASS" if ok else "FAIL"}
        reasons = sorted(set(reasons))
        if reasons:
            out["reason_codes"] = reasons
        return out

    by_id = {d.decision_id: d for d in decisions}
    ops_from_accept = all(
        by_id.get(op["decision_id"]) is not None and by_id[op["decision_id"]].accepted
        for op in operations
    )
    accepted_complete = all(
        d.predicate and d.direction and d.subject_entity_id and d.object_entity_id
        for d in decisions
        if d.accepted
    )
    evidence_ok = all(
        any(f.code == "EVIDENCE_LITERAL_VERIFIED" for f in d.findings)
        for d in decisions
        if d.accepted
    )
    no_conflict_accepted = all(not d.conflicts for d in decisions if d.accepted) and all(
        not any(f.axis == "CONTRADICTION" and f.severity >= 2 for f in d.findings)
        for d in decisions
        if d.accepted
    ) and plan_is_self_consistent(operations, profile)
    ontology_ok = all(
        profile.spec(d.predicate) is not None for d in decisions if d.accepted and d.predicate
    ) and context.ontology_version == profile.ontology_version
    anchored = all(
        (
            op["expected_version"] is not None
            and op["expected_hash"] is not None
        )
        or op["operation_type"] in ("CREATE_ENTITY", "CREATE_ASSERTION")
        for op in operations
    )

    return [
        entry("structural", structural_ok, () if structural_ok else ["CONTRACT_VALIDATION_FAILED"]),
        entry(
            "semantic",
            not semantic_failures and accepted_complete and evidence_ok,
            semantic_failures,
        ),
        entry("ontology", ontology_ok, () if ontology_ok else ["ONTOLOGY_INCOMPATIBLE"]),
        entry(
            "contradiction",
            no_conflict_accepted,
            () if no_conflict_accepted else ["CONFLICT_WITH_EXISTING"],
        ),
        entry("authority", ops_from_accept, () if ops_from_accept else ["OPERATION_WITHOUT_ACCEPT"]),
        entry("concurrency", anchored, () if anchored else ["MISSING_EXPECTED_VERSION"]),
    ]


def _plan_body(
    context: PlanContext,
    plan_kind: str,
    decisions: Sequence[ClaimDecision],
    operations: Sequence[dict],
    chain: Sequence[dict],
    approved: bool,
    config: EngineConfig,
    extra_steps: Sequence[dict],
) -> dict:
    trace = [
        provider_step(
            STEP_PLAN, "local", ENGINE_NAME, context.engine_version, ["decisions", "mutation_operations"]
        )
    ]
    # Los pasos del motor estan RESERVADOS: una senal que se llame
    # `engine.decide` haria que la traza del plan atribuyese la decision a
    # Ollama o a un externo. `ExternalSignal` ya lo rechaza en construccion;
    # esto es la defensa del lado del plan, porque el `provider_trace` no entra
    # en el `decision_hash` y una procedencia falsa no rompe ninguna firma.
    seen = {STEP_PLAN, STEP_DECIDE}
    for step in extra_steps:
        entry = dict(step)
        if entry["step"] in RESERVED_STEPS:
            entry["step"] = f"signal.{entry['step']}"
        if entry["step"] not in seen:
            trace.append(entry)
            seen.add(entry["step"])
    body = {
        "contract_id": GraphMutationPlan.CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "workspace": context.workspace,
        "source_asset_id": context.source_asset_id,
        "source_hash": context.source_hash,
        "provider_trace": trace,
        "produced_by_step": STEP_PLAN,
        "plan_id": _plan_id(context, plan_kind, decisions),
        "plan_hash": sha256_hash("placeholder"),
        "snapshot_id": context.snapshot.snapshot_id,
        "engine_version": context.engine_version,
        "ontology_version": context.ontology_version,
        "game_profile": context.game_profile,
        "collection_id": context.collection_id,
        "created_at": context.now,
        "expires_at": context.expires_at(config.plan_ttl_seconds),
        "decisions": [d.to_contract_dict() for d in decisions],
        "mutation_operations": [dict(op) for op in operations],
        "local_approval": {
            "approved": approved,
            "decision_hash": sha256_hash("placeholder"),
            "validator_chain": list(chain),
            "created_at": context.now,
            "approved_by": {
                "provider": "local",
                "name": ENGINE_NAME,
                "version": context.engine_version,
            },
        },
    }
    return body


def _plan_id(context: PlanContext, kind: str, decisions: Sequence[ClaimDecision]) -> str:
    body = {
        "workspace": context.workspace,
        "source_asset_id": context.source_asset_id,
        "snapshot_id": context.snapshot.snapshot_id,
        "kind": kind,
        "decisions": sorted(d.decision_id for d in decisions),
    }
    return "plan:" + sha256_hash(body)["value"][:32]


@dataclass(frozen=True)
class PlanBuild:
    plan: Optional[GraphMutationPlan]
    assertions: tuple[FactAssertion, ...]
    validator_chain: tuple[dict, ...]


def build_plan(
    context: PlanContext,
    decisions: Sequence[ClaimDecision],
    profile: ProfileIndex,
    config: EngineConfig,
    *,
    kind: str = "write",
    proposal_steps: Optional[dict] = None,
    extra_steps: Sequence[dict] = (),
    decision_source: str = "effective",
) -> PlanBuild:
    """Construye un plan solo desde decisiones efectivas.

    ``decision_source`` es una invariante verificable de frontera: los
    artefactos sombra no pueden convertirse accidentalmente en el contrato que
    consume el writer.
    """
    if decision_source != "effective":
        raise EnginePlanError("el writer solo admite planes derivados de decisiones efectivas")
    decisions = list(decisions)
    if not decisions:
        return PlanBuild(None, (), ())

    proposal_steps = proposal_steps or {}
    assertions: list[FactAssertion] = []
    operations: list[dict] = []
    semantic_failures: list[str] = []

    for decision in decisions:
        if not decision.writes:
            continue
        if not any(f.code == "EVIDENCE_LITERAL_VERIFIED" for f in decision.findings):
            semantic_failures.append("EVIDENCE_LITERAL_NOT_VERIFIED")
            continue
        if decision.negated and decision.negation_kind in ("", "UNKNOWN", "SCOPE_AMBIGUOUS"):
            semantic_failures.append("NEGATION_KIND_NOT_WRITABLE")
            continue
        try:
            assertion = assertion_for(context, decision, proposal_steps.get(decision.claim_id))
        except V3ContractError:
            semantic_failures.append("ASSERTION_INVALID")
            continue
        assertions.append(assertion)
        operations.extend(_operations(context, decision, assertion, config))

    # Orden total antes de sellar: ni el orden de llegada de los claims ni el
    # de las operaciones auxiliares afecta al hash o a la idempotency key.
    assertions.sort(key=lambda assertion: assertion.assertion_id)
    operations.sort(key=lambda operation: operation["operation_id"])
    has_review = any(d.decision == "REVIEW" for d in decisions)
    chain = _validator_chain(context, decisions, operations, profile, True, semantic_failures)
    approved = (
        bool(operations)
        and not has_review
        and all(v["result"] == "PASS" for v in chain)
    )
    body = _plan_body(context, kind, decisions, operations, chain, approved, config, extra_steps)
    sealed = seal_plan(body)

    try:
        plan = GraphMutationPlan.from_dict(sealed)
    except V3ContractError as first_error:
        chain = _validator_chain(
            context, decisions, operations, profile, False, semantic_failures
        )
        body = _plan_body(context, kind, decisions, operations, chain, False, config, extra_steps)
        sealed = seal_plan(body)
        try:
            plan = GraphMutationPlan.from_dict(sealed)
        except V3ContractError as exc:
            raise EnginePlanError(
                f"el plan construido no valida contra el contrato congelado: {exc} "
                f"(primer error: {first_error})"
            ) from exc
    return PlanBuild(plan, tuple(assertions), tuple(chain))
