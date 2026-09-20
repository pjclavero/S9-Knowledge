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

QUE SE EMITE, Y BAJO QUE CONDICION OBSERVADA
---------------------------------------------
Este modulo emitia SOLO `CREATE_ASSERTION`. La razon declarada era que
`PROJECT_RELATION` compara `expected_version`/`expected_hash` contra el estado
observado y que ese estado "no esta en lo que el operador reviso". La primera
mitad es cierta; la segunda era una carencia de PLOMERIA, no una imposibilidad:
esos dos valores salen del SNAPSHOT DE LA CORRIDA --`engine/planner.py` los
copia de `context.snapshot.entity(...)`-- que es EXACTAMENTE la misma
procedencia que `snapshot_id` y `source_hash`, ya publicados en el sobre. El
snapshot se construia en `run_source`, se usaba y se tiraba. Ahora se conserva
(`SourceRun.snapshot`) y sus anclas viajan en el sobre, igual que el resto.

Con eso, la regla pasa a ser una PROPIEDAD OBSERVADA por propuesta, no una
renuncia global:

  * se emite `PROJECT_RELATION` cuando el sobre trae ancla para los DOS
    extremos y ninguno esta `pending_creation`, es decir, cuando los dos
    existen de verdad en el grafo que el operador reviso. La version y el hash
    se COPIAN de esa ancla: no se rellenan con un valor plausible.
  * NO se emite --y se dice, con codigo enumerable de `PROJECTION_CODES`--
    cuando falta ancla, cuando un extremo esta `pending_creation` o cuando el
    hecho es NEGATIVO. Un extremo `pending_creation` exige un `CREATE_ENTITY`,
    y eso solo lo autoriza un alta aprobada (`pipeline/entity_decisions.py`):
    aprobar una propuesta de revision NO es aprobar el alta de una entidad, y
    esa frontera la cruza una persona, no este modulo.

La omision de una proyeccion NO es un silencio: viaja en `projections_omitted`
y el apply la cuenta. Lo que NO puede pasar --y es lo que este carril cierra--
es que un apply anuncie exito completo habiendo declarado una arista que no
materializo.

LA IDENTIDAD DEL PLAN NO CAMBIA
-------------------------------
`_plan_id` se compone de workspace, corrida, revision, `snapshot_id` y
decisiones: ninguno de sus insumos cambia por emitir mas operaciones. El
`plan_hash` es un hash de CONTENIDO y por tanto distingue --como debe-- un plan
con proyeccion de uno sin ella; el algoritmo (`contracts.base.seal_plan`) no se
toca. No se altera ningun esquema de identidad durable.

LA PROCEDENCIA VIAJA EN EL SOBRE
--------------------------------
`apply_v3` solo persiste procedencia si se le da el PAQUETE (los documentos de
fuente, episodios y fragmentos). Ese paquete lo produce la corrida y moria con
ella: por la ruta de la UI, aplicar dejaba siempre
`APPLY_PROVENANCE_NOT_PERSISTED` y aserciones citando fragmentos inexistentes.
Ahora el sobre publica ese material --acotado a los fragmentos que las
propuestas exportadas CITAN, no la corrida entera-- y `provenance_from_context`
lo devuelve en la forma que `ProvenanceBundle.from_dict` admite.
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
    "ALTAS_KEY",
    "ALTA_CODES",
    "ANCHORS_KEY",
    "PLAN_CONTEXT_KEY",
    "PROVENANCE_KEY",
    "PROJECTION_CODES",
    "SEAL_CODES",
    "ReviewPlanError",
    "SealedPlanBuild",
    "ExcludedProposal",
    "OmittedProjection",
    "OmittedAlta",
    "plan_context_from_run",
    "provenance_from_context",
    "seal_review_plan",
]

#: Nombre del bloque del SOBRE del paquete de propuestas donde la corrida deja
#: lo que un plan necesita y una propuesta no contiene. Se nombra una sola vez.
PLAN_CONTEXT_KEY = "plan_context"

#: Anclas de estado POR ENTIDAD dentro de `plan_context`. Es lo que
#: `engine/planner.py` copia a `expected_version`/`expected_hash`, con la misma
#: procedencia que `snapshot_id`: el snapshot de la corrida.
ANCHORS_KEY = "entity_anchors"

#: Los DOCUMENTOS de procedencia dentro de `plan_context`: lo que el plan NO
#: lleva dentro y sin lo cual `apply_v3` no puede persistir procedencia.
PROVENANCE_KEY = "provenance"

#: Las ALTAS DE ENTIDAD que la corrida dejo pendientes, dentro de
#: `plan_context`. Es la PREGUNTA, no la respuesta: quien contesta es una
#: persona y su respuesta vive en el almacen de revision, no aqui. Un sobre
#: sin esta clave significa "esta corrida no publico altas", que no es lo
#: mismo que "no hay ninguna": la distincion la sostiene la AUSENCIA de la
#: clave frente a un diccionario vacio.
ALTAS_KEY = "entity_altas"

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

#: Motivos ENUMERABLES por los que una propuesta INCLUIDA en el plan no trae
#: ademas su arista proyectada. No es lo mismo que `SEAL_CODES`: alli la
#: propuesta queda FUERA del plan; aqui su afirmacion entra y lo que falta es
#: la proyeccion. Confundirlos diria que no se escribio nada cuando si se
#: escribio la afirmacion.
PROJECTION_CODES = {
    "PROJECTION_NO_ANCHOR": (
        "la corrida no dejo ancla de estado para los extremos de este hecho "
        "(paquete anterior a este corte)"
    ),
    "PROJECTION_ANCHOR_NOT_OBSERVED": (
        "el estado de los extremos viene de un catalogo declarado en fichero, "
        "no leido del grafo: no hay con que anclar la arista sin presumir una "
        "version que nadie ha observado"
    ),
    "PROJECTION_ENTITY_NOT_IN_GRAPH": (
        "alguno de los dos extremos no existe todavia en el grafo: su alta es "
        "una decision aparte que nadie ha aprobado"
    ),
    "PROJECTION_NEGATED_FACT": (
        "el hecho es negativo: el grafo no aprende una relacion que el texto "
        "niega"
    ),
}


#: Motivos ENUMERABLES por los que un alta APROBADA por una persona no llega a
#: producir un `CREATE_ENTITY` en el plan. Ninguno de los tres es un silencio:
#: los tres significan que alguien aprobo algo y el plan no lo trae.
ALTA_CODES = {
    "ALTA_NOT_DECLARED_IN_RUN": (
        "la corrida no declaro esta alta en su sobre, asi que el plan no sabe "
        "con que tipo ni con que nombre habria que crearla"
    ),
    "ALTA_NOT_REFERENCED": (
        "ninguna de las afirmaciones que entran en el plan menciona esta "
        "entidad: crearla dejaria un nodo suelto que nada sostiene"
    ),
    "ALTA_WITHOUT_TYPE": (
        "el alta no declara tipo de entidad, y el tipo no se inventa: quien "
        "aprueba tiene que declararlo"
    ),
}


class OmittedAlta:
    """Un alta APROBADA que no produce `CREATE_ENTITY`. Y por que.

    Mismo patron y misma razon que `ExcludedProposal` y `OmittedProjection`:
    la enumeracion esta CERRADA por construccion, asi que no se puede emitir
    un motivo que la pantalla no sepa traducir. Y no se confunde con las
    otras dos: aqui lo que falta no es una propuesta ni una arista, sino la
    entidad, y decir "se excluyo una propuesta" cuando lo que falta es un
    nodo mandaria a mirar al sitio equivocado.
    """

    __slots__ = ("entity_id", "code")

    def __init__(self, entity_id: str, code: str):
        if code not in ALTA_CODES:
            raise ReviewPlanError(
                "ALTA_CODE_NOT_DECLARED",
                f"motivo de omision no declarado en ALTA_CODES: {code}",
            )
        self.entity_id = entity_id
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"entity_id": self.entity_id, "code": self.code}

    def __repr__(self) -> str:  # pragma: no cover - diagnostico
        return f"OmittedAlta({self.entity_id!r}, {self.code!r})"


class OmittedProjection:
    """Una afirmacion que SI entra en el plan y cuya arista NO. Y por que.

    Existe por la misma razon que `ExcludedProposal`: para que la diferencia
    entre "se escribio la afirmacion" y "se escribio ademas la arista" sea una
    frase que el producto pueda decir, y no una ausencia que nadie nota. El
    motivo se valida contra `PROJECTION_CODES` al construirlo, asi que la
    enumeracion esta CERRADA por construccion.
    """

    __slots__ = ("proposal_id", "code")

    def __init__(self, proposal_id: str, code: str):
        if code not in PROJECTION_CODES:
            raise ReviewPlanError(
                "PROJECTION_CODE_NOT_DECLARED",
                f"motivo de omision no declarado en PROJECTION_CODES: {code}",
            )
        self.proposal_id = proposal_id
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"proposal_id": self.proposal_id, "code": self.code}

    def __repr__(self) -> str:  # pragma: no cover - diagnostico
        return f"OmittedProjection({self.proposal_id!r}, {self.code!r})"


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

    EL MOTIVO SE VALIDA CONTRA `SEAL_CODES` AL CONSTRUIRLO. Esa tabla estaba
    exportada y sin un solo llamador, es decir, era prosa: nada impedia emitir
    un motivo que no estuviera en ella, y un motivo que la pantalla no sabe
    traducir es una exclusion muda. Ahora la enumeracion esta CERRADA por
    construccion y el fallo es inmediato, no un hueco en la pantalla.
    """

    __slots__ = ("proposal_id", "code")

    def __init__(self, proposal_id: str, code: str):
        if code not in SEAL_CODES:
            raise ReviewPlanError(
                "SEAL_CODE_NOT_DECLARED",
                f"motivo de exclusion no declarado en SEAL_CODES: {code}",
            )
        self.proposal_id = proposal_id
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"proposal_id": self.proposal_id, "code": self.code}

    def __repr__(self) -> str:  # pragma: no cover - diagnostico
        return f"ExcludedProposal({self.proposal_id!r}, {self.code!r})"


class SealedPlanBuild:
    """El plan sellado y la cuenta completa de lo que entro y lo que no."""

    __slots__ = (
        "plan_doc", "included_proposal_ids", "excluded", "decision_ids",
        "projections_omitted", "altas_included", "altas_omitted",
    )

    def __init__(
        self,
        plan_doc: dict[str, Any],
        included_proposal_ids: tuple[str, ...],
        excluded: tuple[ExcludedProposal, ...],
        decision_ids: tuple[str, ...],
        projections_omitted: tuple = (),
        altas_included: tuple = (),
        altas_omitted: tuple = (),
    ):
        self.plan_doc = plan_doc
        self.included_proposal_ids = included_proposal_ids
        self.excluded = excluded
        self.decision_ids = decision_ids
        #: Afirmaciones INCLUIDAS cuya arista no se emitio, con su motivo.
        #: Distinto de `excluded`: alli la propuesta no entra en el plan.
        self.projections_omitted = projections_omitted
        #: Los `entity_id` que este plan DA DE ALTA, y los aprobados que no.
        self.altas_included = altas_included
        self.altas_omitted = altas_omitted


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
    *,
    entity_anchors: Optional[Mapping[str, Mapping[str, Any]]] = None,
    entity_altas: Optional[Mapping[str, Mapping[str, Any]]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
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
    # LAS ANCLAS Y LOS DOCUMENTOS DE PROCEDENCIA, si la corrida los trae.
    # Se publican por SEPARADO de `decisions` y solo si no estan vacios: un
    # bloque vacio diria "la corrida no tenia entidades" cuando lo que pasa es
    # que no se le paso el material, y esas dos cosas se distinguen.
    if entity_anchors:
        contexto[ANCHORS_KEY] = {
            str(k): dict(v) for k, v in entity_anchors.items() if isinstance(v, Mapping)
        }
    # LAS ALTAS PENDIENTES, si la corrida las declaro. Mismo criterio que las
    # anclas: solo si no esta vacio. Un bloque vacio diria "esta corrida no
    # necesita ningun alta" cuando lo que puede pasar es que nadie se lo
    # preguntara, y esas dos cosas se distinguen por la AUSENCIA de la clave.
    if entity_altas:
        contexto[ALTAS_KEY] = {
            str(k): dict(v) for k, v in entity_altas.items() if isinstance(v, Mapping)
        }
    if provenance and (
        provenance.get("source_asset")
        or provenance.get("episodes")
        or provenance.get("fragments")
    ):
        contexto[PROVENANCE_KEY] = {
            "source_asset": provenance.get("source_asset"),
            "episodes": [dict(e) for e in (provenance.get("episodes") or ())],
            "fragments": [dict(f) for f in (provenance.get("fragments") or ())],
        }
    return contexto


def provenance_from_context(contexto: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """El paquete de procedencia del sobre, en la forma que `apply_v3` admite.

    Devuelve EXACTAMENTE las tres claves que `ProvenanceBundle.from_dict`
    acepta --que rechaza cualquier otra-- o `None` si el sobre no trae
    material. `None` no es "no hay procedencia": es "esta corrida no publico
    ninguna", y quien llama tiene que decirlo, no taparlo.
    """
    if not isinstance(contexto, Mapping):
        return None
    bloque = contexto.get(PROVENANCE_KEY)
    if not isinstance(bloque, Mapping):
        return None
    paquete = {
        "source_asset": bloque.get("source_asset") or None,
        "episodes": [dict(e) for e in (bloque.get("episodes") or ())],
        "fragments": [dict(f) for f in (bloque.get("fragments") or ())],
    }
    if not (paquete["source_asset"] or paquete["episodes"] or paquete["fragments"]):
        return None
    return paquete


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


def _ancla(contexto: Mapping[str, Any], entity_id: str) -> Optional[Mapping[str, Any]]:
    """El ancla de estado de UNA entidad, o `None`. Nunca se fabrica una.

    Sin ancla no se proyecta: rellenar `expected_version` con un valor
    plausible seria presumir una version del grafo en vez de copiarla del
    snapshot, y el writer tiene razon en rechazar eso.
    """
    anclas = contexto.get(ANCHORS_KEY)
    if not isinstance(anclas, Mapping):
        return None
    ancla = anclas.get(entity_id)
    return ancla if isinstance(ancla, Mapping) else None


def _proyeccion(
    contexto: Mapping[str, Any],
    afirmacion: Any,
    decision: Mapping[str, Any],
    documento: Mapping[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """La arista de un hecho aprobado, o el CODIGO por el que no la hay.

    Mismas dos reglas que `engine/planner.py`, no unas propias:

    * un hecho NEGADO no proyecta --el grafo no aprende una relacion que el
      texto niega--;
    * una entidad `pending_creation` no se proyecta sin el `CREATE_ENTITY`
      que la ancla, y ese alta es una decision humana distinta de aprobar la
      propuesta. Sin ella, emitir la arista solo conseguiria que el executor
      abortase con `EXEC_TARGET_MISSING` -- es decir, cambiar un efecto que
      falta por un apply entero que revienta.

    La version y el hash se COPIAN del ancla del snapshot. Es la misma
    procedencia que `snapshot_id`, que este mismo sobre ya publicaba.
    """
    if documento.get("negated"):
        return None, "PROJECTION_NEGATED_FACT"
    sujeto = documento["subject_entity_id"]
    objeto = documento["object_entity_id"]
    ancla_sujeto = _ancla(contexto, sujeto)
    ancla_objeto = _ancla(contexto, objeto)
    if ancla_sujeto is None or ancla_objeto is None:
        return None, "PROJECTION_NO_ANCHOR"
    if ancla_sujeto.get("pending_creation") or ancla_objeto.get("pending_creation"):
        return None, "PROJECTION_ENTITY_NOT_IN_GRAPH"
    # OBSERVADA, no declarada. Un catalogo en fichero da `version` por defecto
    # y un `state_hash` DERIVADO del propio id (`bridge.entities_from_catalog`),
    # que es plausible y falso: copiarlo a `expected_hash` seria presumir el
    # estado del grafo, y contra un nodo real da `EXEC_HASH_MISMATCH` --es
    # decir, cambiaria "falta una arista" por "el apply entero aborta".
    if not (ancla_sujeto.get("observed") and ancla_objeto.get("observed")):
        return None, "PROJECTION_ANCHOR_NOT_OBSERVED"
    version = ancla_sujeto.get("version")
    state_hash = ancla_sujeto.get("state_hash")
    if version is None or not isinstance(state_hash, Mapping) or not state_hash.get("value"):
        return None, "PROJECTION_NO_ANCHOR"
    return (
        {
            "operation_id": f"op:{decision['claim_id']}:project",
            "operation_type": "PROJECT_RELATION",
            "decision_id": decision["decision_id"],
            "target_entity_id": sujeto,
            "assertion_id": afirmacion.assertion_id,
            "payload": {
                "predicate": documento["predicate"],
                "direction": documento["direction"],
                "subject_entity_id": sujeto,
                "object_entity_id": objeto,
                "negated": documento["negated"],
            },
            "evidence_fragment_ids": documento["evidence_fragment_ids"],
            "idempotency_key": "",  # la deriva `seal_plan`
            "expected_state": "WOULD_UPDATE",
            "expected_version": version,
            "expected_hash": dict(state_hash),
        },
        None,
    )


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


def _altas_aprobadas(
    contexto: Mapping[str, Any],
    approved_entities: Sequence[Mapping[str, Any]],
    decisiones: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[OmittedAlta]]:
    """Los `CREATE_ENTITY` de las altas APROBADAS. Ni uno mas.

    TRES CONDICIONES, Y LAS TRES SE COMPRUEBAN AQUI, en el servidor:

    1. **APROBADA.** Solo se mira lo que llega en `approved_entities`. Esta
       funcion no lee el sobre buscando altas que emitir: el sobre solo puede
       DECLARAR candidatas, y una candidata no aprobada no produce nada.
    2. **DECLARADA POR ESTA CORRIDA.** Un id que el sobre de esta corrida no
       declara no se crea, aunque venga aprobado. Es lo que hace que un alta
       de OTRO workspace --u otra corrida, o un id inventado-- no se cuele por
       el formulario: el sobre es de la corrida, y la corrida es del
       workspace. Se dice con `ALTA_NOT_DECLARED_IN_RUN`.
    3. **REFERENCIADA POR EL PLAN.** La entidad tiene que ser sujeto u objeto
       de alguna afirmacion que entra. Crear un nodo que ninguna afirmacion
       menciona seria escribir en el grafo algo que nadie reviso.

    El `decision_id` de cada alta NO se inventa: es el de una decision REAL
    del plan que menciona esa entidad. El validador congelado exige que toda
    operacion tenga su decision asociada, y atarla a una decision que no la
    nombra falsearia la procedencia del nodo.
    """
    declaradas = contexto.get(ALTAS_KEY)
    declaradas = declaradas if isinstance(declaradas, Mapping) else {}
    por_entidad: dict[str, Mapping[str, Any]] = {}
    for decision in decisiones:
        for campo in ("subject_entity_id", "object_entity_id"):
            entity_id = str(decision.get(campo) or "")
            if entity_id:
                por_entidad.setdefault(entity_id, decision)
    ops: list[dict[str, Any]] = []
    incluidas: list[str] = []
    omitidas: list[OmittedAlta] = []
    vistas: set[str] = set()
    for alta in sorted(approved_entities, key=lambda a: str(a.get("entity_id") or "")):
        entity_id = str(alta.get("entity_id") or "")
        if not entity_id or entity_id in vistas:
            # REPETIR UNA APROBACION NO DUPLICA NADA. Dos veces el mismo id
            # producen UN `CREATE_ENTITY`; dos abortarian el apply entero con
            # `EXEC_TARGET_EXISTS`, que es el mismo motivo por el que el motor
            # tiene `_dedupe_altas`.
            continue
        vistas.add(entity_id)
        declarada = declaradas.get(entity_id)
        if not isinstance(declarada, Mapping):
            omitidas.append(OmittedAlta(entity_id, "ALTA_NOT_DECLARED_IN_RUN"))
            continue
        decision = por_entidad.get(entity_id)
        if decision is None:
            omitidas.append(OmittedAlta(entity_id, "ALTA_NOT_REFERENCED"))
            continue
        tipo = str(alta.get("entity_type") or declarada.get("entity_type") or "")
        if not tipo:
            omitidas.append(OmittedAlta(entity_id, "ALTA_WITHOUT_TYPE"))
            continue
        payload: dict[str, Any] = {
            "entity_type": tipo,
            "name": str(declarada.get("name") or entity_id),
        }
        alias = sorted({
            str(a) for a in (declarada.get("aliases") or ()) if str(a).strip()
        })
        if alias:
            # La clave se OMITE cuando no hay alias, igual que en
            # `engine/planner._payload_alta`: una lista vacia entraria en el
            # `state_hash` del nodo y haria distintos dos nodos iguales.
            payload["aliases"] = alias
        ops.append({
            "operation_id": f"op:alta:{entity_id}",
            "operation_type": "CREATE_ENTITY",
            "decision_id": decision["decision_id"],
            "target_entity_id": entity_id,
            "payload": payload,
            "evidence_fragment_ids": list(decision.get("evidence_fragment_ids") or ()),
            "idempotency_key": "",  # la deriva `seal_plan`
            "expected_state": "WOULD_CREATE",
            "expected_version": None,
            "expected_hash": None,
        })
        incluidas.append(entity_id)
    return ops, incluidas, omitidas


def seal_review_plan(
    *,
    workspace: str,
    job_id: str,
    revision: int,
    approved: Sequence[Mapping[str, Any]],
    decision_ids: Mapping[str, str],
    now: str,
    approved_entities: Sequence[Mapping[str, Any]] = (),
) -> SealedPlanBuild:
    """Sella el plan de UNA corrida desde sus propuestas APROBADAS.

    `approved` son las propuestas ya cargadas del almacen (el formato que
    devuelve `load_proposals`, con su `plan_context_by_run` puesto por el
    cargador) cuya decision humana ACTIVA es `APPROVE`. `decision_ids` ata cada
    `proposal_id` al `decision_id` de esa decision: es lo que hace que el plan
    quede ligado a UN conjunto concreto de decisiones y no a «las que hubiera».

    `approved_entities` son las ALTAS DE ENTIDAD que una persona aprobo, una a
    una y por su id, en la autoridad de revision. Es la SEGUNDA decision, y es
    la unica cosa que enciende un `CREATE_ENTITY` en este plan: sin ella se
    emiten exactamente cero, por muchas propuestas aprobadas que haya. La
    frontera que la cabecera de este modulo declara --aprobar una propuesta NO
    es aprobar un alta-- no se relaja: se le da su propio canal.

    Cada elemento es `{"entity_id": ..., "entity_type": ... opcional}`. El tipo
    declarado por quien aprueba MANDA sobre el que la corrida dedujo, porque en
    un grafo nuevo el resolutor no tiene contra que inferirlo y sale `None`;
    sin ninguno de los dos no se crea nada y se DICE (`ALTA_WITHOUT_TYPE`).

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
    omitidas: list[OmittedProjection] = []
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
        # LA PROYECCION, si el sobre trae con que anclarla. Reutiliza el tipo
        # de operacion que el writer YA sabe ejecutar: aqui no hay proyector
        # nuevo ni segundo grafo, solo una operacion mas en el mismo plan.
        proyeccion, motivo = _proyeccion(contexto, afirmacion, decision, documento)
        if proyeccion is not None:
            operaciones.append(proyeccion)
        else:
            omitidas.append(OmittedProjection(identificador, motivo or ""))
        incluidas.append(identificador)
        usadas.append(decision_ids.get(identificador, ""))

    if contexto is None or not operaciones:
        raise ReviewPlanError(
            "NO_APPLICABLE_PROPOSALS",
            "ninguna propuesta aprobada produce una operacion aplicable",
        )

    # LAS ALTAS DE ENTIDAD APROBADAS, y SOLO esas. Se emiten al final, cuando
    # ya se sabe que afirmaciones entran: un alta cuya entidad no menciona
    # ninguna afirmacion del plan crearia un nodo suelto.
    altas_ops, altas_incluidas, altas_omitidas = _altas_aprobadas(
        contexto, approved_entities, decisiones,
    )
    operaciones.extend(altas_ops)

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
        projections_omitted=tuple(omitidas),
        altas_included=tuple(altas_incluidas),
        altas_omitted=tuple(altas_omitidas),
    )
