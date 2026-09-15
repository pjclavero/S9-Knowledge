# -*- coding: utf-8 -*-
"""EL PLAN QUE EL OPERADOR REVISO, sellado como snapshot inmutable.

EL HUECO QUE ESTE MODULO CIERRA
-------------------------------
Hasta aqui NO EXISTIA un plan aprobado durable. Medido sobre `main`:

  * `Pipeline.write()` aplica INLINE, dentro de la misma corrida;
  * `run.plan` / `run.review_plan` viven en memoria y mueren con el job;
  * `ingest_v3.py` persiste SOLO un resumen curado;
  * `plan.json` lo escribe UNICAMENTE el CLI, y solo con `--out-dir`;
  * `review_export.py` exporta PROPUESTAS, no un plan.

Y `apply_v3(...)` --la unica definicion de «aplicar V3»-- estaba completa con
CERO llamadores desde `viewer/`. Es decir: el operador podia revisar y aprobar,
y no habia ningun artefacto que aplicar.

LA DECISION ARQUITECTONICA QUE ESTE MODULO IMPLEMENTA
-----------------------------------------------------
No se reejecuta el pipeline para obtener el plan en el momento de Apply.
Aunque el pipeline fuese determinista hoy, aplicar un plan RECALCULADO seria
aplicar algo distinto de lo que la persona reviso. El plan se deriva
EXCLUSIVAMENTE de:

  * las PROPUESTAS PERSISTIDAS de la corrida (el almacen de propuestas), y
  * las DECISIONES EFECTIVAS ya persistidas (`human_decisions`, Corte 2).

Este modulo es la funcion pura que hace esa derivacion. No lee el reloj, no
abre ficheros, no toca SQLite y no habla con Neo4j: recibe datos y devuelve un
documento de plan sellado. Quien lo persiste es el visor
(`app.services.v3_review_store`), en la MISMA base que ya es autoridad de las
decisiones, para no reabrir el problema de las dos verdades.

DE DONDE SALE CADA PIEZA -- Y POR QUE NINGUNA SE INVENTA
--------------------------------------------------------
Un `graph-mutation-plan/v3-internal-v1` exige mas de lo que una propuesta
contiene (`snapshot_id`, `source_hash`, `collection_id`, `game_profile`,
`evidence_fragment_ids`...). Nada de eso se fabrica aqui: viaja en el SOBRE del
paquete de propuestas, bloque `plan_context`, que la propia corrida escribe a
partir de su plan de revision (`run.review_plan`). Es el mismo almacen, escrito
por el mismo acto, y por eso no es una segunda autoridad: es el resto del
artefacto que la corrida ya producia y tiraba.

Lo que el operador REVISO manda sobre lo que el motor dedujo en un unico punto,
y esta declarado: la IDENTIDAD de sujeto y objeto sale de `resolution` de la
propuesta --el par de entidades que se le enseno en pantalla-- y no de la
decision del motor, que para una propuesta en REVIEW puede traerlas a `null`
(`ENTITY_RESOLUTION_DEFERRED`) precisamente porque decidio no resolverlas.

QUE NO SE EMITE, Y POR QUE NO ES UN OLVIDO
-------------------------------------------
Solo se emiten operaciones `CREATE_ASSERTION`. NO se emite `PROJECT_RELATION`
ni `CREATE_ENTITY`, y la razon es una propiedad observada del writer, no una
preferencia:

  * `PROJECT_RELATION` exige que los DOS extremos existan ya en el grafo y, sin
    ancla en el propio plan, compara `expected_version`/`expected_hash` contra
    el estado observado (`writer/executor.py`, `_check_expected_state`). Ese
    estado NO esta en lo que el operador reviso: ni la propuesta ni la decision
    lo contienen. Rellenarlo con un valor plausible seria presumir una version
    del grafo en vez de observarla, y el writer tiene razon en rechazarlo.
  * `CREATE_ENTITY` solo lo autoriza un alta aprobada (`pending_creation` en el
    snapshot, `pipeline/entity_decisions.py`). Aprobar una propuesta de
    revision NO es aprobar el alta de una entidad: son dos decisiones
    distintas y la frontera la cruza una persona.

Consecuencia honesta y declarada: aplicar desde la UI MATERIALIZA LA
AFIRMACION (el nodo `V3Assertion`, que es donde vive la verdad de V3), no la
arista proyectada. La proyeccion queda como deuda REGISTRADA, no disimulada.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from .contracts.assertion import FactAssertion
from .contracts.base import (
    CONTRACT_VERSION,
    V3ContractError,
    provider_step,
    seal_plan,
    sha256_hash,
)
from .contracts.mutation_plan import GraphMutationPlan
from .engine.planner import PAYLOAD_FIELDS, assertion_identity

__all__ = [
    "PLAN_CONTEXT_KEY",
    "SEAL_CODES",
    "ReviewPlanError",
    "SealedPlanBuild",
    "ExcludedProposal",
    "plan_context_from_run",
    "seal_review_plan",
]

#: Nombre del bloque del SOBRE del paquete de propuestas donde la corrida deja
#: lo que un plan necesita y una propuesta no contiene. Se nombra una sola vez.
PLAN_CONTEXT_KEY = "plan_context"

#: Paso declarado como productor del plan sellado. NO es `engine.plan`: no lo
#: produjo el planificador del motor sobre una corrida, lo produjo la revision
#: humana sobre propuestas ya persistidas. Atribuirselo al motor falsearia la
#: procedencia del documento.
STEP_SEAL = "review.seal"

#: Nombre del productor, para `approved_by.name`. El `provider` es `local` por
#: contrato congelado.
SEALER_NAME = "s9k.review.seal"
SEALER_VERSION = "1"

#: Codigo de razon que se ANADE a la decision para que el documento diga, por
#: enumeracion y no por prosa, que esta operacion existe porque una persona la
#: aprobo. Cumple el patron `reason_code` del contrato congelado.
REASON_HUMAN_APPROVED = "HUMAN_APPROVED"

#: Razones CANONICAS de un `ACCEPT` segun el contrato congelado
#: (`contracts/knowledge-v3/v1/validator.py::CANONICAL_REASON_CODES`). El
#: validador rechaza un `ACCEPT` que no lleve una de las dos: sin ella la
#: decision del dosier 11.7 no es reconstruible.
#:
#: Cual de las dos se emite NO es cosmetico. Si el motor habia mandado la
#: reclamacion a revision -- que es el caso normal aqui, porque es justamente lo
#: que el operador revisa -- sus reservas siguen siendo ciertas y viajan en
#: `reason_codes`: entonces la aprobacion es CON ADVERTENCIAS, y decir
#: `LOCAL_APPROVED` a secas ocultaria que se aprobo algo que el motor no daba
#: por bueno. `LOCAL_APPROVED` limpio solo cuando el motor tampoco tenia nada
#: que objetar.
REASON_LOCAL_APPROVED = "LOCAL_APPROVED"
REASON_LOCAL_APPROVED_WITH_WARNINGS = "LOCAL_APPROVED_WITH_WARNINGS"

#: Vida del plan sellado, en segundos. Es el mismo valor que el motor usa para
#: sus planes (`EngineConfig.plan_ttl_seconds`): un plan sellado no es mas
#: eterno que uno del pipeline, y si caduca el writer lo rechaza con su propio
#: codigo en vez de aplicar algo revisado hace una semana.
PLAN_TTL_SECONDS = 86400

#: Motivos ENUMERABLES por los que una propuesta aprobada NO entra en el plan.
#: Son codigos estables: la pantalla los convierte en frases, y ninguna
#: exclusion puede ocurrir en silencio.
SEAL_CODES = {
    "PROPOSAL_WITHOUT_RUN_CONTEXT": (
        "la corrida que produjo esta propuesta no dejo el contexto de plan "
        "(paquete anterior a este corte)"
    ),
    "PROPOSAL_WITHOUT_DECISION": (
        "la corrida no dejo decision de motor para esta propuesta"
    ),
    "PROPOSAL_IDENTITY_UNRESOLVED": (
        "la propuesta no tiene sujeto y objeto resueltos a entidades"
    ),
    "PROPOSAL_PREDICATE_UNKNOWN": (
        "la propuesta no declara un predicado o una direccion aplicables"
    ),
    "PROPOSAL_WITHOUT_EVIDENCE": (
        "la propuesta no cita ningun fragmento de evidencia"
    ),
    "PROPOSAL_NOT_REPRESENTABLE": (
        "la afirmacion derivada no valida contra el contrato congelado"
    ),
}

#: Valor centinela que el exportador de propuestas usa cuando NO sabe algo. No
#: es un identificador: es la declaracion de una ausencia, y tratarlo como id
#: escribiria en el grafo un nodo llamado «not_available».
NOT_AVAILABLE = "not_available"

#: Lo que `direction`/`predicate` valen cuando el motor no pudo determinarlos.
UNKNOWN = "UNKNOWN"


class ReviewPlanError(RuntimeError):
    """No hay plan que sellar. Lleva un codigo estable, nunca una ruta."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class ExcludedProposal:
    """Una propuesta aprobada que NO entra en el plan, y por que.

    Existe para que «se aprobaron 3 y el plan trae 1» sea una frase que el
    producto puede decir, y no una diferencia que nadie nota.
    """

    __slots__ = ("proposal_id", "code")

    def __init__(self, proposal_id: str, code: str):
        self.proposal_id = proposal_id
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"proposal_id": self.proposal_id, "code": self.code}

    def __repr__(self) -> str:  # pragma: no cover - diagnostico
        return f"ExcludedProposal({self.proposal_id!r}, {self.code!r})"


class SealedPlanBuild:
    """El plan sellado y la cuenta completa de lo que entro y lo que no."""

    __slots__ = ("plan_doc", "included_proposal_ids", "excluded", "decision_ids")

    def __init__(
        self,
        plan_doc: dict[str, Any],
        included_proposal_ids: tuple[str, ...],
        excluded: tuple[ExcludedProposal, ...],
        decision_ids: tuple[str, ...],
    ):
        self.plan_doc = plan_doc
        self.included_proposal_ids = included_proposal_ids
        self.excluded = excluded
        self.decision_ids = decision_ids


# ---------------------------------------------------------------------------
# Lado ESCRITOR: lo que la corrida deja en el sobre del paquete
# ---------------------------------------------------------------------------

#: Campos del plan de la corrida que el plan sellado NO puede deducir de una
#: propuesta y que, por tanto, tienen que viajar. Lista cerrada a proposito:
#: un campo nuevo del plan no se publica solo por aparecer.
CONTEXT_FIELDS = (
    "workspace",
    "source_asset_id",
    "source_hash",
    "snapshot_id",
    "collection_id",
    "game_profile",
    "ontology_version",
    "engine_version",
    "contract_version",
    "partida_id",
)


def plan_context_from_run(
    plan_doc: Optional[Mapping[str, Any]],
    decisions_by_claim: Mapping[str, Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """El bloque `plan_context` del sobre, o `None` si la corrida no lo tiene.

    `plan_doc` es el plan que la corrida SI produjo (`run.review_plan`, o
    `run.plan` si aquel no existe): de ahi salen el `snapshot_id`, el
    `source_hash` y el resto de anclas que la propuesta no lleva dentro.

    `decisions_by_claim` son las decisiones del motor en forma de contrato,
    indexadas por `claim_id`. Se guarda la del claim de cada propuesta, y NO
    solo las de veredicto REVIEW: el paquete tambien exporta `ABSTAIN` y
    `REJECT_INVALID`, y si esas se quedaran sin decision, aprobarlas mas tarde
    no produciria nada y el operador no sabria por que.

    Devuelve `None` --y entonces el sobre no gana ninguna clave-- cuando la
    corrida no dejo plan: sin anclas no hay contexto que publicar, y publicar
    uno a medias seria peor que no publicarlo.
    """
    if not plan_doc:
        return None
    contexto: dict[str, Any] = {}
    for campo in CONTEXT_FIELDS:
        valor = plan_doc.get(campo)
        if valor is not None:
            contexto[campo] = valor
    if not contexto.get("workspace") or not contexto.get("snapshot_id"):
        return None
    por_propuesta: dict[str, Any] = {}
    for documento in documents:
        identificador = documento.get("proposal_id")
        decision = decisions_by_claim.get(str(documento.get("claim_id") or ""))
        if identificador and decision:
            por_propuesta[str(identificador)] = dict(decision)
    contexto["decisions"] = por_propuesta
    return contexto


# ---------------------------------------------------------------------------
# Lado LECTOR: el sellado
# ---------------------------------------------------------------------------

def _identidad(valor: Any) -> Optional[str]:
    """Un id de entidad utilizable, o `None`. `not_available` NO es un id."""
    texto = str(valor or "").strip()
    if not texto or texto == NOT_AVAILABLE:
        return None
    return texto


def _resuelto(proposal: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Sujeto y objeto TAL Y COMO SE LE ENSENARON al operador.

    Se lee `resolution` --el bloque que la pantalla pinta como identidad
    resuelta-- y, solo si falta, el par `proposal.subject`/`proposal.object`,
    que es de donde `review_export` lo copia cuando la resolucion existe.
    """
    resolucion = proposal.get("resolution") or {}
    cuerpo = proposal.get("proposal") or {}
    sujeto = _identidad(resolucion.get("subject")) or _identidad(cuerpo.get("subject"))
    objeto = _identidad(resolucion.get("object")) or _identidad(cuerpo.get("object"))
    return sujeto, objeto


def _fragmentos(decision: Mapping[str, Any]) -> list[str]:
    return [str(f) for f in (decision.get("evidence_fragment_ids") or []) if f]


def _razones(decision: Mapping[str, Any]) -> list[str]:
    """Los motivos del motor, CONSERVADOS, mas los de la aprobacion humana.

    No se limpian los `REVIEW_*`: son ciertos --el motor si tuvo esa duda-- y
    borrarlos convertiria el plan en un documento que no permite reconstruir
    por que existio la revision. Lo que se anade es lo que el contrato exige y
    lo que la aprobacion aporta.
    """
    codigos = {str(c) for c in (decision.get("reason_codes") or []) if c}
    codigos.add(REASON_HUMAN_APPROVED)
    if str(decision.get("decision") or "") == "ACCEPT":
        codigos.add(REASON_LOCAL_APPROVED)
    else:
        codigos.add(REASON_LOCAL_APPROVED_WITH_WARNINGS)
    return sorted(codigos)


def _afirmacion(
    contexto: Mapping[str, Any],
    proposal: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    subject: str,
    object_: str,
    predicate: str,
    direction: str,
    now: str,
) -> FactAssertion:
    """La `FactAssertion` de una propuesta aprobada. Valida contra el contrato.

    La traza declara DOS pasos y ninguno miente: el del motor que produjo la
    reclamacion, si la decision lo trae, y el del sellado humano. Atribuir la
    afirmacion entera al motor ocultaria que la escribe una aprobacion.
    """
    negado = bool((proposal.get("proposal") or {}).get("negated", False))
    epistemico = str(decision.get("epistemic_status") or UNKNOWN)
    documento = FactAssertion(
        contract_version=str(contexto.get("contract_version") or CONTRACT_VERSION),
        workspace=str(contexto["workspace"]),
        source_asset_id=str(contexto["source_asset_id"]),
        source_hash=dict(contexto["source_hash"]),
        provider_trace=[
            provider_step(
                STEP_SEAL,
                "local",
                SEALER_NAME,
                SEALER_VERSION,
                ["predicate", "direction", "subject_entity_id", "object_entity_id"],
            )
        ],
        produced_by_step=STEP_SEAL,
        assertion_id=assertion_identity(
            workspace=str(contexto["workspace"]),
            collection_id=str(contexto["collection_id"]),
            subject_entity_id=subject,
            object_entity_id=object_,
            predicate=predicate,
            direction=direction,
            negated=negado,
            partida_id=contexto.get("partida_id"),
        ),
        subject_entity_id=subject,
        object_entity_id=object_,
        predicate=predicate,
        direction=direction,
        # TEMPORALIDAD: no se inventa. La propuesta no lleva vigencias y la
        # decision del motor tampoco viaja con ellas en su forma de contrato.
        # Una fecha plausible aqui seria una vigencia que nadie declaro.
        valid_from=None,
        valid_to=None,
        recorded_at=now,
        epistemic_status=epistemico,
        confidence=float(decision.get("confidence") or 0.0),
        status="ASSERTED" if epistemico == "ASSERTED" else "PROVISIONAL",
        state=UNKNOWN,
        event_time=None,
        negated=negado,
        collection_id=str(contexto["collection_id"]),
        game_profile=str(contexto["game_profile"]),
        engine_version=str(contexto["engine_version"]),
        ontology_version=str(contexto["ontology_version"]),
        evidence_fragment_ids=_fragmentos(decision),
        episode_ids=[str(proposal.get("episode_id") or "")],
        # SUPERSESION: este camino NO la ejerce. Cerrar la vigencia de otra
        # afirmacion es una decision aparte, con su propia operacion y su
        # propio motivo; deducirla de un «aprobar» seria decidir por el
        # operador algo que no se le pregunto.
        supersedes=None,
        superseded_by=None,
        calendar_id=None,
    )
    documento.validate()
    return documento


def _plan_id(
    contexto: Mapping[str, Any],
    job_id: str,
    revision: int,
    decision_ids: Sequence[str],
) -> str:
    """Identidad INTERNA del plan sellado. Nunca se le pide al operador.

    Distingue lo que tiene que distinguir: la corrida, la revision del plan
    dentro de esa corrida, el ancla de estado y el conjunto exacto de
    decisiones humanas que lo componen. Dos sellados del mismo conjunto en la
    misma corrida y con la misma revision son el mismo plan; en cuanto una
    decision cambia, es otro.
    """
    body = {
        "workspace": contexto.get("workspace"),
        "job_id": job_id,
        "revision": revision,
        "snapshot_id": contexto.get("snapshot_id"),
        "decision_ids": sorted(decision_ids),
    }
    if contexto.get("partida_id") is not None:
        body["partida_id"] = contexto["partida_id"]
    return "plan:" + sha256_hash(body)["value"][:32]


def _scope_fields(contexto: Mapping[str, Any]) -> dict[str, Any]:
    """Raiz `partida_id` + bloque `scope`, o nada. Misma regla que el motor.

    `writer/admission.py::_scope_incoherence` exige que los dos concuerden y
    rechaza si no, asi que se construyen juntos o no se construye ninguno.
    """
    partida = contexto.get("partida_id")
    if partida is None:
        return {}
    return {
        "partida_id": partida,
        "scope": {
            "layer": "PARTIDA",
            "game_id": contexto.get("workspace"),
            "partida_id": partida,
        },
    }


def _expira(now: str) -> str:
    from datetime import datetime, timedelta, timezone

    momento = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (momento + timedelta(seconds=PLAN_TTL_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def seal_review_plan(
    *,
    workspace: str,
    job_id: str,
    revision: int,
    approved: Sequence[Mapping[str, Any]],
    decision_ids: Mapping[str, str],
    now: str,
) -> SealedPlanBuild:
    """Sella el plan de UNA corrida desde sus propuestas APROBADAS.

    `approved` son las propuestas ya cargadas del almacen (el formato que
    devuelve `load_proposals`, con su `plan_context_by_run` puesto por el
    cargador) cuya decision humana ACTIVA es `APPROVE`. `decision_ids` ata cada
    `proposal_id` al `decision_id` de esa decision: es lo que hace que el plan
    quede ligado a UN conjunto concreto de decisiones y no a «las que hubiera».

    `now` se INYECTA. Este modulo no lee el reloj: si lo leyera, sellar dos
    veces el mismo conjunto daria dos planes distintos y nada seria
    comparable.

    Levanta `ReviewPlanError` cuando no hay nada aplicable. No devuelve un plan
    vacio: un plan con cero operaciones es un plan que el writer admitiria y
    que no escribiria nada, es decir, un exito que no hace nada.
    """
    if not approved:
        raise ReviewPlanError("NO_APPROVED_PROPOSALS", "no hay propuestas aprobadas")

    contexto: Optional[dict[str, Any]] = None
    incluidas: list[str] = []
    excluidas: list[ExcludedProposal] = []
    operaciones: list[dict[str, Any]] = []
    decisiones: list[dict[str, Any]] = []
    usadas: list[str] = []

    for propuesta in sorted(approved, key=lambda p: str(p.get("proposal_id") or "")):
        identificador = str(propuesta.get("proposal_id") or "")
        por_corrida = propuesta.get("plan_context_by_run") or {}
        bloque = por_corrida.get(job_id)
        if not isinstance(bloque, Mapping) or not bloque.get("snapshot_id"):
            excluidas.append(ExcludedProposal(identificador, "PROPOSAL_WITHOUT_RUN_CONTEXT"))
            continue
        if contexto is None:
            contexto = {k: v for k, v in bloque.items() if k != "decisions"}
        decision = (bloque.get("decisions") or {}).get(identificador)
        if not isinstance(decision, Mapping):
            excluidas.append(ExcludedProposal(identificador, "PROPOSAL_WITHOUT_DECISION"))
            continue
        sujeto, objeto = _resuelto(propuesta)
        if not sujeto or not objeto:
            excluidas.append(ExcludedProposal(identificador, "PROPOSAL_IDENTITY_UNRESOLVED"))
            continue
        cuerpo = propuesta.get("proposal") or {}
        predicado = str(cuerpo.get("predicate") or decision.get("predicate") or "")
        direccion = str(cuerpo.get("direction") or decision.get("direction") or "")
        if not predicado or predicado == UNKNOWN or not direccion or direccion == UNKNOWN:
            excluidas.append(ExcludedProposal(identificador, "PROPOSAL_PREDICATE_UNKNOWN"))
            continue
        if not _fragmentos(decision):
            excluidas.append(ExcludedProposal(identificador, "PROPOSAL_WITHOUT_EVIDENCE"))
            continue
        try:
            afirmacion = _afirmacion(
                contexto, propuesta, decision,
                subject=sujeto, object_=objeto,
                predicate=predicado, direction=direccion, now=now,
            )
        except (V3ContractError, KeyError, TypeError, ValueError):
            excluidas.append(ExcludedProposal(identificador, "PROPOSAL_NOT_REPRESENTABLE"))
            continue

        documento = afirmacion.to_dict()
        # LA DECISION QUE VIAJA EN EL PLAN ES LA HUMANA, no la del motor. Se
        # parte de la del motor para no perder su traza (`claim_id`, motivos,
        # confianza) y se sobreescribe lo que la persona resolvio: veredicto
        # ACCEPT, e identidad y predicado TAL Y COMO SE LE ENSENARON.
        decisiones.append({
            "decision_id": decision["decision_id"],
            "claim_id": decision["claim_id"],
            "decision": "ACCEPT",
            "predicate": predicado,
            "direction": direccion,
            "subject_entity_id": sujeto,
            "object_entity_id": objeto,
            "epistemic_status": documento["epistemic_status"],
            "negated": documento["negated"],
            "confidence": documento["confidence"],
            "reason_codes": _razones(decision),
            "evidence_fragment_ids": documento["evidence_fragment_ids"],
        })
        operaciones.append({
            "operation_id": f"op:{decision['claim_id']}:assert",
            "operation_type": "CREATE_ASSERTION",
            "decision_id": decision["decision_id"],
            "target_entity_id": None,
            "assertion_id": afirmacion.assertion_id,
            "payload": {k: documento[k] for k in PAYLOAD_FIELDS if k in documento},
            "evidence_fragment_ids": documento["evidence_fragment_ids"],
            "idempotency_key": "",  # la deriva `seal_plan`
            "expected_state": "WOULD_CREATE",
            "expected_version": None,
            "expected_hash": None,
        })
        incluidas.append(identificador)
        usadas.append(decision_ids.get(identificador, ""))

    if contexto is None or not operaciones:
        raise ReviewPlanError(
            "NO_APPLICABLE_PROPOSALS",
            "ninguna propuesta aprobada produce una operacion aplicable",
        )

    # Orden total antes de sellar. Sin el, el orden en que el almacen devuelva
    # las propuestas cambiaria el `plan_hash` de un plan identico.
    operaciones.sort(key=lambda op: op["operation_id"])
    decisiones.sort(key=lambda d: d["decision_id"])

    cuerpo = {
        "contract_id": GraphMutationPlan.CONTRACT_ID,
        "contract_version": str(contexto.get("contract_version") or CONTRACT_VERSION),
        "workspace": str(contexto["workspace"]),
        "source_asset_id": str(contexto["source_asset_id"]),
        "source_hash": dict(contexto["source_hash"]),
        "provider_trace": [
            provider_step(
                STEP_SEAL, "local", SEALER_NAME, SEALER_VERSION,
                ["decisions", "mutation_operations"],
            )
        ],
        "produced_by_step": STEP_SEAL,
        "plan_id": _plan_id(contexto, job_id, revision, [d["decision_id"] for d in decisiones]),
        "plan_hash": sha256_hash("placeholder"),
        "snapshot_id": str(contexto["snapshot_id"]),
        "engine_version": str(contexto["engine_version"]),
        "ontology_version": str(contexto["ontology_version"]),
        "game_profile": str(contexto["game_profile"]),
        "collection_id": str(contexto["collection_id"]),
        "created_at": now,
        **_scope_fields(contexto),
        "expires_at": _expira(now),
        "decisions": decisiones,
        "mutation_operations": operaciones,
        "local_approval": {
            "approved": True,
            "decision_hash": sha256_hash("placeholder"),
            # LA CADENA DICE SOLO LO QUE SE COMPROBO. No se copia la del motor:
            # aquella valido un plan con OTRAS operaciones, y arrastrarla aqui
            # seria firmar como verificado algo que nadie verifico en este
            # documento. `structural` es cierto porque `GraphMutationPlan.
            # from_dict` valida abajo contra el schema congelado, y
            # `human_review` es cierto porque hay decisiones `APPROVE`
            # persistidas que lo sostienen.
            "validator_chain": [
                {"validator": "structural", "version": CONTRACT_VERSION, "result": "PASS"},
                {"validator": "human_review", "version": SEALER_VERSION, "result": "PASS"},
            ],
            "created_at": now,
            "approved_by": {
                "provider": "local",
                "name": SEALER_NAME,
                "version": SEALER_VERSION,
            },
        },
    }
    sellado = seal_plan(cuerpo)
    # VALIDACION, NO CONFIANZA: si el documento no valida, no se persiste nada
    # y no se ofrece ningun Apply. Un plan que el writer va a rechazar es mejor
    # descubrirlo aqui que delante del operador.
    GraphMutationPlan.from_dict(sellado)
    return SealedPlanBuild(
        plan_doc=sellado,
        included_proposal_ids=tuple(incluidas),
        excluded=tuple(excluidas),
        decision_ids=tuple(sorted({d for d in usadas if d})),
    )
