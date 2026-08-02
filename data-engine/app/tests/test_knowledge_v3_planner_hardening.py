# -*- coding: utf-8 -*-
"""Puerta 3 del programa de validacion final V3: ENDURECIMIENTO DEL PLANNER.

Quince casos contra el planner REAL de `knowledge_v3/engine/planner.py`. No hay
dobles del planner en ningun sitio de este fichero: lo que se mide es el codigo
que construye y sella el `GraphMutationPlan` que el writer va a ejecutar.

La division es deliberada:

* casos 1-7 y 15 atacan al **planner**: pureza, determinismo, indiferencia al
  orden, autoridad de la decision, negacion y cesacion;
* casos 8-14 atacan a la **frontera plan->writer**: un plan manipulado,
  caducado, de otro workspace o de otro firmante no se aplica. Se apoyan en la
  admision y en el writer con driver falso — SIN Neo4j, sin red y sin
  credenciales, igual que `test_knowledge_v3_writer.py`.

Los fixtures salen del corpus gold del motor (`test_knowledge_v3_engine_gold`),
que ya garantiza coherencia entre episodio, cita, tipos y perfil. Fabricar aqui
un corpus paralelo habria producido tests que pasan sobre datos que el motor
nunca veria.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts.base import seal_plan, sha256_hash  # noqa: E402
from knowledge_v3.engine import DEFAULT_CONFIG, EngineConfig  # noqa: E402
from knowledge_v3.engine.decision import ClaimDecision  # noqa: E402
from knowledge_v3.engine.ontology import ProfileIndex  # noqa: E402
from knowledge_v3.engine.planner import PlanContext, build_plan  # noqa: E402
from knowledge_v3.writer import (  # noqa: E402
    AdmissionContext,
    InMemoryAppliedKeys,
    admit,
    codes,
)

from test_knowledge_v3_engine_gold import (  # noqa: E402,I100 - modulo hermano de fixtures
    ASSET_ID,
    COLLECTION_ID,
    NOW,
    ONTOLOGY,
    PROFILE_ID,
    SNAPSHOT_ID,
    SOURCE_HASH,
    WORKSPACE,
    claim,
    profile,
    run,
    snapshot,
    vigente,
)
from test_knowledge_v3_writer import (  # noqa: E402,I100 - dobles del writer, no Neo4j
    FakeDriver,
    apply_request,
    make_plan,
    make_writer,
)


# ==========================================================================
# Utillaje
# ==========================================================================
def canon(value) -> str:
    """Serializacion canonica: el unico criterio de igualdad de este fichero.

    `sort_keys=True` a proposito — comparar el `repr` de un dict compararia
    tambien su orden de insercion, que es justo lo que varios casos declaran
    irrelevante.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def decisions_fingerprint(decisions) -> str:
    """Huella COMPLETA de las decisiones, findings incluidos.

    `to_contract_dict()` por si solo no vale: no lleva los findings, y una
    mutacion del planner que solo anadiese un finding pasaria desapercibida.
    """
    return canon(
        [
            {
                **d.to_contract_dict(),
                "findings": [(f.axis, f.code, f.detail) for f in d.findings],
                "negation_kind": d.negation_kind,
                "duplicate_in_batch": d.duplicate_in_batch,
                "supersedes": d.supersedes.assertion_id if d.supersedes else None,
                "confidence": d.confidence,
            }
            for d in decisions
        ]
    )


def canonical_plan(plan) -> str:
    """Plan normalizado por CONTENIDO, no por orden de lote.

    Se ordenan decisiones y operaciones por su identificador, y se quitan los
    campos que dependen legitimamente del lote (`plan_id` y las dos firmas se
    derivan del conjunto y de su orden). Lo que queda es lo que de verdad se va
    a escribir en el grafo: si eso cambia al barajar la entrada, el planner no
    es indiferente al orden.
    """
    doc = deepcopy(plan.to_dict())
    doc["decisions"] = sorted(doc["decisions"], key=lambda d: d["decision_id"])
    doc["mutation_operations"] = sorted(
        doc["mutation_operations"], key=lambda o: o["operation_id"]
    )
    for field in ("plan_id", "plan_hash"):
        doc.pop(field, None)
    doc["local_approval"].pop("decision_hash", None)
    # La `idempotency_key` la deriva `seal_plan` del plan completo, orden
    # incluido: no forma parte del contenido que se compara aqui.
    for op in doc["mutation_operations"]:
        op.pop("idempotency_key", None)
    return canon(doc)


def plan_context(**over) -> PlanContext:
    base = dict(
        workspace=WORKSPACE,
        source_asset_id=ASSET_ID,
        source_hash=SOURCE_HASH,
        collection_id=COLLECTION_ID,
        game_profile=PROFILE_ID,
        ontology_version=ONTOLOGY,
        snapshot=snapshot(),
        now=NOW,
    )
    base.update(over)
    return PlanContext(**base)


def index() -> ProfileIndex:
    return ProfileIndex(profile())


def accepted_decisions(claims=None, **over):
    """Decisiones REALES del motor sobre el gold. Nunca fabricadas a mano."""
    result = run(claims if claims is not None else [claim()], **over)
    return result.decisions


def ops_of(plan, operation_type: str) -> list[dict]:
    if plan is None:
        return []
    return [o for o in plan.mutation_operations if o["operation_type"] == operation_type]


def clock_at(moment: datetime):
    return lambda: moment


#: Reloj situado justo despues del `NOW` del gold: dentro del TTL del plan.
INSIDE_TTL = datetime(2026, 7, 27, 10, 31, 0, tzinfo=timezone.utc)


def admission_ctx(**over) -> AdmissionContext:
    base = dict(
        workspace=WORKSPACE, current_snapshot_id=SNAPSHOT_ID, clock=clock_at(INSIDE_TTL)
    )
    base.update(over)
    return AdmissionContext(**base)


def engine_plan_doc() -> dict:
    """Plan APROBADO construido por el motor real sobre el gold, ya sellado."""
    build = build_plan(plan_context(), accepted_decisions(), index(), DEFAULT_CONFIG)
    assert build.plan is not None and build.plan.approved, "el gold debe producir plan aprobado"
    return build.plan.to_dict()


def test_el_plan_del_gold_es_admisible_de_partida():
    """Control: sin esto, los casos 8-14 podrian pasar por el motivo equivocado.

    Un plan que ya fuese inadmisible haria que cada manipulacion "bloquease" sin
    demostrar nada.
    """
    assert admit(engine_plan_doc(), admission_ctx()).admitted


# ==========================================================================
# 1-3, 15. Pureza, determinismo e indiferencia al orden
# ==========================================================================
def test_1_build_plan_no_muta_las_decisiones_que_recibe():
    decisions = accepted_decisions()
    before = decisions_fingerprint(decisions)

    build = build_plan(plan_context(), decisions, index(), DEFAULT_CONFIG)
    between = decisions_fingerprint(decisions)

    # Una segunda pasada sobre las MISMAS decisiones: si la primera hubiese
    # dejado estado pegado en ellas, la segunda lo revelaria.
    build_plan(plan_context(), decisions, index(), DEFAULT_CONFIG)
    after = decisions_fingerprint(decisions)

    assert build.plan is not None
    assert before == between, "build_plan mutó las decisiones durante la construcción"
    assert between == after, "una segunda construcción mutó las decisiones"


def test_2_dos_llamadas_identicas_producen_el_mismo_plan_byte_a_byte():
    first = build_plan(plan_context(), accepted_decisions(), index(), DEFAULT_CONFIG).plan
    second = build_plan(plan_context(), accepted_decisions(), index(), DEFAULT_CONFIG).plan

    assert first is not None and second is not None
    assert canon(first.to_dict()) == canon(second.to_dict())
    # La firma es lo que el writer confirma con el operador: tiene que coincidir.
    assert first.plan_hash == second.plan_hash


def test_3_barajar_el_orden_de_los_claims_no_cambia_el_plan_canonico():
    claims = [
        claim(claim_id="claim:gold:a"),
        claim(claim_id="claim:gold:b", object_mentions=["mention:consejo"],
              predicate_candidates=[{"predicate": "SERVES", "confidence": 0.84}],
              evidence_fragment_ids=["fragment:gold:0"]),
    ]
    straight = build_plan(plan_context(), accepted_decisions(claims), index(), DEFAULT_CONFIG).plan
    shuffled = build_plan(
        plan_context(), accepted_decisions(list(reversed(claims))), index(), DEFAULT_CONFIG
    ).plan

    assert straight is not None and shuffled is not None
    assert canonical_plan(straight) == canonical_plan(shuffled)


def test_15_el_orden_de_las_claves_de_los_diccionarios_no_cambia_la_firma():
    """El sellado serializa con `sort_keys`: un dict equivalente firma igual.

    Importa porque `source_hash` y el snapshot llegan de JSON, y el orden de
    claves de un JSON no es informacion.
    """
    natural = plan_context(source_hash={"algorithm": "sha256", "value": SOURCE_HASH["value"]})
    inverted_keys = {"value": SOURCE_HASH["value"], "algorithm": "sha256"}
    assert list(inverted_keys) != list(natural.source_hash), "el test no probaria nada"
    inverted = plan_context(source_hash=inverted_keys)

    a = build_plan(natural, accepted_decisions(), index(), DEFAULT_CONFIG).plan
    b = build_plan(inverted, accepted_decisions(), index(), DEFAULT_CONFIG).plan

    assert a is not None and b is not None
    assert a.plan_hash == b.plan_hash
    assert canon(a.to_dict()) == canon(b.to_dict())


# ==========================================================================
# 4. Autoridad: un ACCEPT fabricado no compra un plan aplicable
# ==========================================================================
def fabricated_accept() -> ClaimDecision:
    """ACCEPT construido A MANO, saltandose `decide_claim` y sus invariantes.

    Es el ataque que importa: `decision.py` garantiza que no hay ACCEPT sin
    `EVIDENCE_LITERAL_VERIFIED`, pero esa garantia vive en el eje, no en el
    planner. Si alguna vez se anade otra ruta que produzca decisiones, el
    planner es lo ultimo que hay antes del writer.
    """
    return ClaimDecision(
        claim_id="claim:fabricado",
        decision="ACCEPT",
        findings=[],  # <- ni un solo finding: no hay evidencia verificada
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:daiki",
        object_entity_id="entity:casa-ciervo",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.95,
        evidence_fragment_ids=["fragment:gold:0"],
        episode_id="episode:gold-001:p01",
    )


# HALLAZGO P3-1 (demostrado en main d50c931, xfail estricto): el planner
# aprobaba y sellaba un ACCEPT fabricado sin EVIDENCE_LITERAL_VERIFIED —
# `_validator_chain` solo miraba que `evidence_fragment_ids` no estuviera
# vacia. Corregido por el endurecimiento del planner (encargo C): ahora exige
# el finding. Este test queda como regresion positiva de esa correccion.
def test_4_un_accept_fabricado_sin_evidencia_verificada_no_produce_plan_aplicable():
    build = build_plan(plan_context(), [fabricated_accept()], index(), DEFAULT_CONFIG)
    assert build.plan is None or not build.plan.approved


# ==========================================================================
# 5-7. Negacion y cesacion
# ==========================================================================
def test_5_un_claim_negativo_jamas_proyecta_una_relacion_positiva():
    negated = claim(
        negated=True,
        metadata={"negation_kind": "SIMPLE"},
        evidence_fragment_ids=["fragment:gold:1"],
        object_mentions=["mention:consejo"],
        predicate_candidates=[{"predicate": "SERVES", "confidence": 0.84}],
        relation_phrase="jamas sirvio al",
    )
    decisions = accepted_decisions([negated])
    build = build_plan(plan_context(), decisions, index(), DEFAULT_CONFIG)

    assert build.plan is not None
    assert ops_of(build.plan, "PROJECT_RELATION") == [], (
        "un hecho negativo no puede aprender una arista positiva en el grafo"
    )
    # Y la afirmacion negativa SI queda en el ledger, con su marca.
    creates = ops_of(build.plan, "CREATE_ASSERTION")
    assert creates and all(op["payload"]["negated"] is True for op in creates)


def test_6_un_tipo_de_negacion_desconocido_no_produce_ninguna_operacion():
    unknown = claim(
        negated=True,
        metadata={"negation_kind": "CESATION"},  # errata por CESSATION: no existe
        evidence_fragment_ids=["fragment:gold:1"],
    )
    with pytest.warns(RuntimeWarning, match="negation_kind"):
        decisions = accepted_decisions([unknown], snap=snapshot())

    assert decisions[0].decision == "REVIEW"
    assert decisions[0].negation_kind == "UNKNOWN"

    build = build_plan(plan_context(), decisions, index(), DEFAULT_CONFIG)
    assert build.plan is not None
    assert build.plan.mutation_operations == []
    assert not build.plan.approved


def test_7_una_cesacion_con_dos_positivas_vigentes_no_supersede_a_ciegas():
    """Con dos candidatas vigentes, cerrar UNA es elegir sin criterio.

    El motor no puede saber cual de las dos cierra el texto; supersederlas a
    ciegas dejaria una vigencia abierta que nadie cerro, o cerraria la que no
    era. Lo correcto es no superseder nada y mandarlo a revision.
    """
    two_active = snapshot(
        [
            vigente(assertion_id="assertion:vigente-a", version=1),
            vigente(assertion_id="assertion:vigente-b", version=2),
        ]
    )
    cessation = claim(
        negated=True,
        metadata={"negation_kind": "CESSATION"},
        evidence_fragment_ids=["fragment:gold:1"],
    )
    decisions = accepted_decisions([cessation], snap=two_active)
    # Que no haya supersesion tiene que ser una NEGATIVA RAZONADA, no un efecto
    # colateral de que el claim se cayese por otro motivo cualquiera.
    assert "CESSATION_MULTIPLE_ACTIVE" in set(decisions[0].reason_codes())
    assert decisions[0].supersedes is None

    build = build_plan(plan_context(snapshot=two_active), decisions, index(), DEFAULT_CONFIG)

    assert ops_of(build.plan, "SUPERSEDE_ASSERTION") == [], (
        "con dos positivas vigentes el planner eligió una supersesión sin criterio"
    )


# ==========================================================================
# 8-9, 12-14. Frontera plan -> writer: la admision, sin Neo4j
# ==========================================================================
def test_8_un_hash_manipulado_bloquea_la_aplicacion():
    doc = engine_plan_doc()
    doc["plan_hash"] = sha256_hash("otra cosa")  # firma que no corresponde

    result = admit(doc, admission_ctx())
    assert not result.admitted
    assert codes.PLAN_CONTRACT_INVALID in result.codes or (
        codes.PLAN_SIGNATURE_MISMATCH in result.codes
    )


def test_8b_tocar_una_operacion_sin_resellar_bloquea_la_aplicacion():
    """El ataque util no es cambiar el hash: es cambiar lo que se va a escribir."""
    doc = engine_plan_doc()
    doc["mutation_operations"][0]["payload"]["object_entity_id"] = "entity:consejo-umbra"

    result = admit(doc, admission_ctx())
    assert not result.admitted


def test_9_una_version_de_contrato_no_soportada_bloquea_la_aplicacion():
    doc = engine_plan_doc()
    doc["contract_version"] = "2.0.0"

    result = admit(doc, admission_ctx())
    assert not result.admitted
    assert (
        codes.PLAN_CONTRACT_VERSION_UNSUPPORTED in result.codes
        or codes.PLAN_CONTRACT_INVALID in result.codes
    )


def test_12_un_plan_de_otro_workspace_no_lo_escribe_este_writer():
    result = admit(engine_plan_doc(), admission_ctx(workspace="otra-campana"))
    assert not result.admitted
    assert codes.PLAN_WORKSPACE_MISMATCH in result.codes


def test_13_un_plan_caducado_no_se_aplica_aunque_la_firma_sea_correcta():
    doc = engine_plan_doc()
    late = datetime(2030, 1, 1, tzinfo=timezone.utc)

    result = admit(doc, admission_ctx(clock=clock_at(late)))
    assert not result.admitted
    assert result.codes == [codes.PLAN_EXPIRED], "la firma seguia siendo correcta"


def test_14_un_plan_firmado_por_un_externo_no_se_aplica():
    """El contrato exige que quien aprueba sea el motor LOCAL.

    Se vuelve a sellar despues de cambiar el firmante: sin resellar, el rechazo
    vendria de la firma rota y no probaria la politica.

    Quien lo caza es el SCHEMA congelado, que fija `approved_by.provider` en
    `"local"` — igual que pasa con la cadena de validadores vacia. La
    comprobacion propia del writer (`PLAN_NOT_SIGNED_LOCALLY`) es defensa en
    profundidad y hoy no llega a ejecutarse por esta via; se ejerce en el test
    siguiente.
    """
    doc = engine_plan_doc()
    doc["local_approval"]["approved_by"] = {
        "provider": "external",
        "name": "nvidia.nim",
        "version": "1.0.0",
    }
    doc = seal_plan(doc)

    result = admit(doc, admission_ctx())
    assert not result.admitted
    assert result.codes == [codes.PLAN_CONTRACT_INVALID]


def test_14c_la_regla_de_firmante_del_writer_bloquea_por_si_sola(monkeypatch):
    """Si el schema aflojase, el writer seguiria negandose.

    Se fuerza `signed_locally()` a False sobre un plan por lo demas impecable:
    lo unico que puede rechazarlo entonces es la regla del writer.
    """
    from knowledge_v3.contracts import GraphMutationPlan

    monkeypatch.setattr(GraphMutationPlan, "signed_locally", lambda self: False)

    result = admit(engine_plan_doc(), admission_ctx())
    assert not result.admitted
    assert result.codes == [codes.PLAN_NOT_SIGNED_LOCALLY]


def test_14b_un_plan_sin_aprobar_no_se_aplica():
    build = build_plan(
        plan_context(),
        accepted_decisions([claim(review_required=True)]),
        index(),
        DEFAULT_CONFIG,
    )
    assert build.plan is not None and not build.plan.approved

    result = admit(build.plan.to_dict(), admission_ctx())
    assert not result.admitted
    assert codes.PLAN_NOT_APPROVED in result.codes


# ==========================================================================
# 10-11. Ejecucion: atomicidad e idempotencia, con driver falso
# ==========================================================================
def test_10_el_fallo_de_una_operacion_no_deja_escritura_parcial():
    """Tres operaciones, la ejecucion se cae a mitad: no debe quedar nada.

    `fail_at` hace estallar al driver en la n-esima consulta. Lo que se exige es
    `rollback` y NINGUN commit: una escritura parcial dejaria el grafo en un
    estado que ningun plan describe y que nadie podria auditar.
    """
    from test_knowledge_v3_writer import op_create_assertion, op_create_entity

    operations = [
        op_create_entity("op:0001", "decision:0001", "entity:daiki"),
        op_create_entity("op:0002", "decision:0001", "entity:sira"),
        op_create_assertion(
            "op:0003", "decision:0001", "assertion:x", "entity:daiki", "entity:casa-del-ciervo"
        ),
    ]
    plan = make_plan(operations=operations)
    driver = FakeDriver(fail_at=2)
    writer = make_writer(driver, applied_keys=InMemoryAppliedKeys())

    result = writer.write(plan, apply_request(plan))

    assert not result.ok
    assert driver.rolled_back is True
    assert driver.committed is False


def test_11_aplicar_dos_veces_el_mismo_plan_es_idempotente():
    """La segunda pasada no vuelve a escribir: las claves ya estan registradas."""
    plan = make_plan()
    keys = InMemoryAppliedKeys()

    first_driver = FakeDriver()
    first = make_writer(first_driver, applied_keys=keys).write(plan, apply_request(plan))
    assert first.ok
    assert first_driver.writes, "la primera pasada tenia que escribir"

    second_driver = first_driver
    second = make_writer(second_driver, applied_keys=keys).write(plan, apply_request(plan))

    assert second.ok
    assert len(second_driver.writes) == 1, "la segunda pasada volvió a escribir el mismo plan"
