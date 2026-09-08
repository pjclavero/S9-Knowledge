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
    #: EQUIPO 5A. Ambito de partida del plan (docs/v3/49 #0): `None` = capa
    #: juego (lore compartido), valor = partida privada. Se declara aqui, en
    #: el CONTEXTO, y no se deduce en ningun punto interior: el motor no
    #: inventa un ambito igual que no inventa un `now()`.
    #:
    #: ES EL CAMPO QUE FALTABA. `writer/executor.py` ya comparaba
    #: `partida_id` para negarse a fusionar dos partidas en una clave
    #: compartida, y `writer/admission.py` ya validaba la coherencia del
    #: bloque `scope`. Ninguna de las dos barreras se disparaba nunca porque
    #: el plan salia de aqui SIN ambito: el planificador no tenia donde
    #: leerlo. Estampar esto es lo que pone trafico en esa carretera.
    partida_id: Optional[str] = None
    #: EQUIPO 6C. Sesion de REVELACION de la corrida (T2): desde que sesion de
    #: juego puede revelarse lo que se ingiere aqui. Igual que `partida_id` y
    #: que `now`, se DECLARA en el contexto y no se deduce en ningun punto
    #: interior: el motor no tiene forma de saber en que sesion se jugo lo que
    #: hay en el fichero, y cualquier valor inventado (empezando por `0`)
    #: seria una revelacion concedida por el software y no por quien dirige.
    #:
    #: ES EL CAMPO QUE FALTABA. `writer/visibility.py::revelacion_props` exige
    #: `known_from_session` para todo lo de ambito PARTIDA desde M5b, y
    #: `writer/executor.py` lo busca en `op["payload"]`. Ningun constructor de
    #: operaciones lo ponia nunca ahi, asi que en cuanto EQUIPO 5A abrio la
    #: ruta `--partida` TODO plan de partida abortaba con
    #: `EXEC_REVELACION_NO_DECLARADA`. La guardia estaba bien; lo que no
    #: llegaba era el dato.
    known_from_session: Optional[int] = None
    engine_version: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        """FAIL CLOSED de la declaracion de ambito, en el borde del motor.

        Se comprueba AQUI, al construir el contexto, y no mas abajo, porque
        este es el primer punto donde constan a la vez el ambito y la sesion.
        Las dos incoherencias posibles se rechazan, y ninguna se degrada:

        * ambito de partida SIN sesion -> no se planifica. Degradar a capa
          juego seria publicar como lore compartido algo que se declaro
          privado de una partida; poner `0` seria declarar "conocido desde el
          inicio" en nombre del director.
        * sesion SIN ambito de partida -> tampoco. El estampado la descarta
          en capa juego (`revelacion_props` devuelve `{}` para `juego`), asi
          que aceptarla en silencio dejaria a quien la declaro creyendo que
          viaja al grafo cuando no viaja. Se falla en voz alta.
        """
        sesion = self.known_from_session
        if self.partida_id is not None and sesion is None:
            raise EnginePlanError(
                "PLAN_SESION_NO_DECLARADA: el ambito de partida "
                f"{self.partida_id!r} exige declarar `known_from_session` "
                "(0 si es conocido desde el inicio, o el numero de sesion en "
                "que se revela). No se degrada a capa juego ni se asume 0."
            )
        if self.partida_id is None and sesion is not None:
            raise EnginePlanError(
                "PLAN_SESION_SIN_AMBITO: se declaro `known_from_session="
                f"{sesion!r}` sin ambito de partida. La capa juego no esta "
                "sujeta a progresion de sesion y el estampado la descartaria: "
                "declara `--partida` o no declares sesion."
            )
        if sesion is not None and (
            isinstance(sesion, bool) or not isinstance(sesion, int) or sesion < 0
        ):
            raise EnginePlanError(
                f"PLAN_SESION_INVALIDA: known_from_session={sesion!r}; debe "
                "ser un entero no negativo."
            )

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
    # EQUIPO 5A. La ASERCION esta acotada por partida; la ENTIDAD no.
    # ---------------------------------------------------------------------
    # No es una intuicion: es lo que exige `writer/executor.py::
    # _assert_absent`, que comprueba la ausencia de un `assertion_id` SIN
    # filtro de ambito porque "dos ambitos jamas comparten el mismo id".
    # Si dos partidas del mismo juego afirman el mismo hecho, esta derivacion
    # -- que hasta ahora ignoraba el ambito -- les daba el MISMO
    # `assertion_id`, y entonces solo una de las dos podia existir: la
    # segunda chocaba, o peor, reutilizaba la de la primera. Meter el ambito
    # en la derivacion es lo que hace CIERTO el invariante que el writer ya
    # daba por cierto.
    #
    # La identidad de ENTIDAD no se toca: sigue siendo workspace-global
    # (`(workspace, entity_id)`), tal y como la fija `writer/schema.py`. Lo
    # que se acota por partida es lo que el ambito realmente privatiza --
    # aserciones y relaciones materializadas--, no el catalogo de entidades.
    #
    # Omitido cuando es nulo: un plan de capa juego produce el cuerpo de
    # siempre y, por tanto, el MISMO `assertion_id` que antes de este cambio.
    # Retrocompatibilidad byte a byte con todo lo ya sellado.
    if context.partida_id is not None:
        body["partida_id"] = context.partida_id
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


def _altas(context: PlanContext, decision: ClaimDecision) -> list[dict]:
    """`CREATE_ENTITY` para las entidades del hecho cuya alta aprobo un humano.

    POR QUE ESTA FUNCION EXISTE
    ---------------------------
    Hasta este carril, NINGUN camino del producto emitia un `CREATE_ENTITY`.
    El tipo estaba en el contrato, el executor sabia ejecutarlo y los planes
    gold lo traian escrito a mano — pero el planificador no lo producia
    jamas. Consecuencia observada contra un Neo4j real y vacio: todo plan
    salia con `CREATE_ASSERTION` + `PROJECT_RELATION` y abortaba con
    `EXEC_TARGET_MISSING` sobre entidades que nadie habia creado. La unica
    salida era sembrarlas a mano por Cypher, que es lo que el criterio de
    producto prohibe.

    LA REGLA QUE NO SE RELAJA
    -------------------------
    Un alta se emite SOLO si la entidad viene marcada `pending_creation` en
    el snapshot, y eso solo lo enciende una aprobacion humana explicita
    (`pipeline/entity_decisions.py`). Aqui no hay ningun "si no existe,
    creala": una entidad ausente y NO aprobada no llega siquiera al snapshot,
    el motor la rechaza por `ENTITY_NOT_IN_SNAPSHOT` y no hay hecho que
    planificar. `LINK_EXISTING` y `CREATE_ENTITY` siguen siendo dos
    decisiones distintas, y la frontera la cruza una persona.

    UNA SOLA VEZ POR PLAN: `_dedupe_altas` (en `build_plan`) retira las
    repetidas, porque dos hechos pueden mencionar la misma entidad nueva y el
    executor aborta con `EXEC_TARGET_EXISTS` al crearla dos veces.
    """
    ops: list[dict] = []
    vistos: set[str] = set()
    for entity_id in (decision.subject_entity_id, decision.object_entity_id):
        if not entity_id or entity_id in vistos:
            continue
        node = context.snapshot.entity(entity_id)
        if node is None or not getattr(node, "pending_creation", False):
            continue
        vistos.add(entity_id)
        ops.append(
            {
                "operation_id": f"op:alta:{entity_id}",
                "operation_type": "CREATE_ENTITY",
                "decision_id": decision.decision_id,
                "target_entity_id": entity_id,
                "payload": _payload_alta(node, entity_id),
                "evidence_fragment_ids": list(decision.evidence_fragment_ids),
                "idempotency_key": "",  # lo deriva seal_plan
                "expected_state": "WOULD_CREATE",
                "expected_version": None,
                "expected_hash": None,
            }
        )
    return ops


def _payload_alta(node, entity_id: str) -> dict:
    """El `payload` de un `CREATE_ENTITY`: como se llama la entidad que nace.

    EQUIPO 8A. Llevaba solo `entity_type` y `name`. Los alias aprobados con el
    alta se quedaban aqui, y el nodo nacia sin ninguna forma alternativa por
    la que alcanzarlo: la corrida SIGUIENTE tenia que acertar el nombre
    canonico exacto o la entidad no se reutilizaba.

    `aliases` viaja dentro de `payload`, que es la EXCEPCION DOCUMENTADA a
    `additionalProperties:false` del contrato congelado
    (`graph-mutation-plan-v3.schema.json`, `$defs/mutation_operation`): no se
    inventa ningun campo de contrato ni se firma nada nuevo. Sobrevive a
    `cypher.safe_props` porque `aliases` cumple `^[a-z][a-z0-9_]{0,63}$` y una
    LISTA de cadenas es un valor que Neo4j si almacena (lo que `safe_props`
    rechaza son `dict` y `set`).

    La clave se OMITE cuando no hay alias, en vez de mandar `[]`: una lista
    vacia entraria en el `state_hash` del nodo y haria distintos dos nodos que
    son iguales.
    """
    payload = {
        "entity_type": node.entity_type,
        "name": node.canonical_name or entity_id,
    }
    aliases = tuple(getattr(node, "aliases", ()) or ())
    if aliases:
        # Deduplicado y ordenado: el plan debe ser identico para la misma alta
        # aprobada, y el orden en que un catalogo enumere los alias no es un
        # dato del mundo. Sin esto, dos corridas iguales darian dos
        # `idempotency_key` distintas.
        payload["aliases"] = sorted({str(a) for a in aliases if str(a).strip()})
    return payload


def _dedupe_altas(operations: list[dict]) -> list[dict]:
    """Una entidad se da de alta UNA vez por plan, aunque la citen dos hechos.

    Se conserva la primera aparicion — y con ella su `decision_id`, que es
    real: esa decision si menciona la entidad. Quedarse con la ultima seria
    igual de valido y menos predecible; lo que no vale es dejar las dos, que
    aborta el plan entero en el executor.
    """
    vistos: set[str] = set()
    out: list[dict] = []
    for op in operations:
        if op["operation_type"] == "CREATE_ENTITY":
            target = op.get("target_entity_id")
            if target in vistos:
                continue
            vistos.add(target)
        out.append(op)
    return out


def _operations(
    context: PlanContext, decision: ClaimDecision, assertion: FactAssertion, config: EngineConfig
) -> list[dict]:
    doc = assertion.to_dict()
    payload = {k: doc[k] for k in PAYLOAD_FIELDS if k in doc}
    ops = _altas(context, decision)
    ops.append(
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
    )
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
    # Un extremo que se CREA en este mismo plan no tiene todavia `version` ni
    # `state_hash` en el grafo. Antes eso se resolvia NO proyectando y dejando
    # la arista para "la siguiente ingesta": es decir, un primer apply que
    # creaba entidades no materializaba nunca la relacion, y el segundo apply
    # --el que se anunciaba como NOOP-- hacia la escritura que faltaba. Eso no
    # es idempotencia: es un plan a medias que otro apply termina.
    #
    # El ancla correcta para esa arista no es una version del grafo que aun no
    # existe: es el `CREATE_ENTITY` que este MISMO plan trae por delante. La
    # proyeccion se emite con `expected_state=WOULD_CREATE` y sin version ni
    # hash esperados --exactamente lo que el contrato reserva para "la
    # operacion crea algo que aun no existe"-- y el executor exige entonces que
    # el propio plan contenga el alta del extremo y que el nodo este visible ya
    # en la transaccion. No se relaja ninguna comprobacion: se cambia el ancla.
    sujeto_nuevo = bool(getattr(node, "pending_creation", False))
    objeto = (
        context.snapshot.entity(decision.object_entity_id)
        if decision.object_entity_id
        else None
    )
    objeto_nuevo = bool(getattr(objeto, "pending_creation", False))
    en_este_plan = sujeto_nuevo or objeto_nuevo
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
            "expected_state": "WOULD_CREATE" if en_este_plan else "WOULD_UPDATE",
            "expected_version": None if sujeto_nuevo else node.version,
            "expected_hash": None if sujeto_nuevo else node.state_hash,
        }
    )
    return ops


def _stampar_revelacion(context: PlanContext, operations: list[dict]) -> list[dict]:
    """Pone la sesion de revelacion declarada en el payload de CADA operacion.

    UN SOLO PUNTO, a proposito. El writer la exige por OPERACION —dos hechos
    del mismo plan pueden revelarse en sesiones distintas—, pero hoy la unica
    fuente que existe es la declaracion de la corrida, que es por PLAN. Repartir
    ese valor desde cuatro constructores distintos (`_altas`, la asercion, la
    supersesion y la proyeccion) habria dado cuatro sitios donde olvidarlo, que
    es exactamente como nacio el defecto que esto arregla.

    En capa juego no se toca nada: `revelacion_props` no la pide y el plan sale
    byte a byte identico al de antes, con su mismo `plan_hash`.

    El valor NO acaba como propiedad cruda del nodo: `writer/executor.py::
    _validated_payload` lo retira del payload antes de calcular `props` y lo
    estampa `visibility.stamp`, que es el unico punto por el que entra al grafo.
    """
    if context.partida_id is None:
        return operations
    sesion = context.known_from_session
    # `__post_init__` ya garantiza que no es None con ambito de partida; esta
    # comprobacion es la que sobrevive si alguien construye el contexto por
    # otra via. Preferimos no planificar a planificar algo que aborta.
    if sesion is None:  # pragma: no cover - defensa en profundidad
        raise EnginePlanError(
            "PLAN_SESION_NO_DECLARADA: ambito de partida sin sesion de revelacion"
        )
    out: list[dict] = []
    for op in operations:
        nuevo = dict(op)
        nuevo["payload"] = {**(op.get("payload") or {}), "known_from_session": sesion}
        out.append(nuevo)
    return out


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
    # Altas del propio plan: son el ancla legitima de una proyeccion sobre una
    # entidad que aun no existe en el grafo. Se leen del artefacto FINAL, no de
    # las decisiones, para que el ancla sea comprobable en el plan mismo.
    altas_del_plan = {
        op.get("target_entity_id")
        for op in operations
        if op["operation_type"] == "CREATE_ENTITY"
    }

    def _anclada(op: dict) -> bool:
        if op["expected_version"] is not None and op["expected_hash"] is not None:
            return True
        if op["operation_type"] in ("CREATE_ENTITY", "CREATE_ASSERTION"):
            return True
        # Proyeccion sobre un extremo dado de alta en ESTE plan: el ancla es el
        # `CREATE_ENTITY` que va delante, no una version del grafo. Sin ese alta
        # en el plan la operacion sigue SIN anclar, que es lo que debe pasar.
        return (
            op["operation_type"] == "PROJECT_RELATION"
            and op.get("expected_state") == "WOULD_CREATE"
            and op.get("target_entity_id") in altas_del_plan
        )

    anchored = all(_anclada(op) for op in operations)

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
        # EQUIPO 5A. El ambito viaja EN el plan, que es lo unico que el writer
        # llega a ver. `GraphMutationPlan.OMIT_IF_NONE` retira ambas claves
        # cuando son nulas, asi que un plan de capa juego sigue siendo
        # identico byte a byte al de antes (y conserva su `plan_hash`).
        # El bloque `scope` NO es decorativo: `writer/admission.py::
        # _scope_incoherence` exige que raiz y `scope` concuerden y rechaza
        # con `PLAN_SCOPE_CROSS_PARTIDA` si no, de modo que declarar uno sin
        # el otro seria un plan inadmisible, no un plan a medias.
        **_scope_fields(context),
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
    # EQUIPO 5A. Mismo criterio y misma omision-si-nulo que el resto: dos
    # partidas que ingieren la misma fuente con las mismas decisiones son DOS
    # planes, no uno, y necesitan `plan_id` distinto para poder auditarse por
    # separado.
    if context.partida_id is not None:
        body["partida_id"] = context.partida_id
    return "plan:" + sha256_hash(body)["value"][:32]


def _scope_fields(context: PlanContext) -> dict:
    """Raiz `partida_id` + bloque `scope`, o nada si es capa juego.

    Los dos campos se emiten SIEMPRE JUNTOS. Emitir solo uno produce
    exactamente los dos rechazos que `writer/admission.py` ya sabe dar
    (`partida_id declarado sin bloque scope` y su espejo), asi que se
    construyen en un unico sitio para que no puedan divergir.

    `game_id` es el `workspace`: es la decision de representacion de
    docs/v3/49 #1 ("`workspace` sigue siendo el identificador del juego"),
    y `admission._scope_incoherence` compara justamente eso.
    """
    if context.partida_id is None:
        return {}
    return {
        "partida_id": context.partida_id,
        "scope": {
            "layer": "PARTIDA",
            "game_id": context.workspace,
            "partida_id": context.partida_id,
        },
    }


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
    # Las altas se emiten por HECHO (un hecho puede mencionar una entidad
    # nueva), asi que dos hechos sobre la misma entidad nueva producen dos
    # `CREATE_ENTITY` identicos. Se retiran DESPUES de ordenar, para que el
    # que sobrevive no dependa del orden de llegada de los claims. El orden
    # resultante deja `op:alta:*` antes que `op:claim:*`, que es el que el
    # executor necesita: crear antes de afirmar.
    operations = _dedupe_altas(operations)
    # EQUIPO 6C. Ultimo paso antes de sellar: la `idempotency_key` se deriva
    # del payload, asi que la sesion de revelacion entra en la firma de la
    # operacion. Es lo correcto: la misma afirmacion revelada en sesiones
    # distintas es una declaracion distinta y no debe colapsar en la misma
    # clave.
    operations = _stampar_revelacion(context, operations)
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
