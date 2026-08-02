# -*- coding: utf-8 -*-
"""Pruebas del writer V3: admision, gate de operador, ejecucion y rollback.

El driver de Neo4j esta MOCKEADO en todos los casos. Aqui no se abre una
conexion, no se lee una credencial y no se escribe en ningun grafo real: el
writer recibe el driver por inyeccion, y estas pruebas le pasan uno falso que
ademas registra cada consulta para poder afirmar cosas sobre ellas.

`ExplodingDriver` merece una nota: es un driver que estalla en cuanto alguien lo
toca. Es la unica forma honesta de demostrar que el dry-run no escribe — no
comprobar que «no parece» escribir, sino que no puede.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts.base import seal_plan  # noqa: E402
from knowledge_v3.writer import (  # noqa: E402
    AdmissionContext,
    GraphWriter,
    InMemoryAppliedKeys,
    InMemoryAuditSink,
    JsonlAppliedKeys,
    JsonlAuditSink,
    OperatorRequest,
    WriterAbort,
    admit,
    assert_safe,
    codes,
)
from knowledge_v3.writer.writer import (  # noqa: E402
    MODE_APPLY,
    MODE_DRY_RUN,
    OUTCOME_ABORTED,
    OUTCOME_APPLIED,
    OUTCOME_ATTEMPTED,
    OUTCOME_BLOCKED,
    OUTCOME_REJECTED,
    OUTCOME_SIMULATED,
)

WORKSPACE = "leyenda"
SNAPSHOT = "snapshot:neo4j:2026-07-27T10:29:00Z"
NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
HASH_A = {"algorithm": "sha256", "value": "a" * 64}
HASH_B = {"algorithm": "sha256", "value": "b" * 64}


def clock_at(moment: datetime = NOW):
    return lambda: moment


# ==========================================================================
# Constructores de plan
# ==========================================================================
def accept_decision(decision_id: str, subject: str, obj: str, predicate: str = "MEMBER_OF") -> dict:
    return {
        "decision_id": decision_id,
        "claim_id": f"claim:{decision_id}",
        "decision": "ACCEPT",
        "predicate": predicate,
        "direction": "SUBJECT_TO_OBJECT",
        "subject_entity_id": subject,
        "object_entity_id": obj,
        "epistemic_status": "ASSERTED",
        "negated": False,
        "confidence": 0.81,
        "reason_codes": ["LOCAL_APPROVED"],
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
    }


def op_create_entity(op_id: str, decision_id: str, entity_id: str, name: str = "Daiki") -> dict:
    return {
        "operation_id": op_id,
        "operation_type": "CREATE_ENTITY",
        "decision_id": decision_id,
        "target_entity_id": entity_id,
        "assertion_id": None,
        "payload": {"entity_type": "Character", "canonical_name": name},
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": "WOULD_CREATE",
        "expected_version": None,
        "expected_hash": None,
    }


def op_create_assertion(op_id: str, decision_id: str, assertion_id: str, subject: str, obj: str) -> dict:
    return {
        "operation_id": op_id,
        "operation_type": "CREATE_ASSERTION",
        "decision_id": decision_id,
        "target_entity_id": None,
        "assertion_id": assertion_id,
        "payload": {
            "subject_entity_id": subject,
            "object_entity_id": obj,
            "predicate": "MEMBER_OF",
        },
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": "WOULD_CREATE",
        "expected_version": None,
        "expected_hash": None,
    }


def op_link(op_id: str, decision_id: str, subject: str, obj: str, version: int = 3) -> dict:
    return {
        "operation_id": op_id,
        "operation_type": "LINK_EXISTING",
        "decision_id": decision_id,
        "target_entity_id": subject,
        "assertion_id": None,
        "payload": {
            "subject_entity_id": subject,
            "object_entity_id": obj,
            "predicate": "MEMBER_OF",
        },
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": "WOULD_LINK_EXISTING",
        "expected_version": version,
        "expected_hash": HASH_A,
    }


def op_supersede(
    op_id: str,
    decision_id: str,
    assertion_id: str,
    version: int = 2,
    reason_code: str = "COPYRIGHT_TAKEDOWN",
    with_reason: bool = True,
) -> dict:
    payload: dict = {"status": "SUPERSEDED", "valid_to": "2026-07-27T00:00:00Z"}
    if with_reason:
        payload["reason_code"] = reason_code
    return {
        "operation_id": op_id,
        "operation_type": "SUPERSEDE_ASSERTION",
        "decision_id": decision_id,
        "target_entity_id": None,
        "assertion_id": assertion_id,
        "payload": payload,
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": "WOULD_SUPERSEDE",
        "expected_version": version,
        "expected_hash": HASH_B,
    }


def make_plan(
    *,
    workspace: str = WORKSPACE,
    snapshot_id: str = SNAPSHOT,
    operations: list | None = None,
    decisions: list | None = None,
    approved: bool = True,
    expires_at: str = "2026-07-28T10:30:00Z",
    created_at: str = "2026-07-27T10:30:00Z",
    contract_version: str = "1.0.0",
    validator_chain: list | None = None,
    metadata: dict | None = None,
    seal: bool = True,
) -> dict:
    """Plan sellado por el 'motor local'. Sellar es la operacion normal."""
    if operations is None:
        operations = [op_create_entity("op:0001", "decision:0001", "entity:daiki")]
    if decisions is None:
        needed = sorted({o["decision_id"] for o in operations}) or ["decision:0001"]
        decisions = [
            accept_decision(d, "entity:daiki", "entity:casa-del-ciervo") for d in needed
        ]
    doc = {
        "contract_id": "graph-mutation-plan/v3-internal-v1",
        "contract_version": contract_version,
        "workspace": workspace,
        "source_asset_id": "asset:manual-001",
        "source_hash": {"algorithm": "sha256", "value": "c" * 64},
        "provider_trace": [
            {
                "step": "engine.plan",
                "provider": "local",
                "name": "s9k.knowledge_v3",
                "version": "3.0.0",
                "model": None,
                "produced": ["decisions", "mutation_operations"],
            }
        ],
        "produced_by_step": "engine.plan",
        "plan_id": "plan:manual-001:0001",
        "plan_hash": {"algorithm": "sha256", "value": "0" * 64},
        "snapshot_id": snapshot_id,
        "engine_version": "3.0.0",
        "ontology_version": "core-1.4.0",
        "game_profile": "generic",
        "collection_id": "collection:campana-leyenda",
        "created_at": created_at,
        "expires_at": expires_at,
        "decisions": decisions,
        "mutation_operations": operations,
        "local_approval": {
            "approved": approved,
            "decision_hash": {"algorithm": "sha256", "value": "0" * 64},
            "validator_chain": validator_chain
            or [
                {"validator": "structural", "version": "3.0.0", "result": "PASS"},
                {"validator": "semantic", "version": "3.0.0", "result": "PASS"},
            ],
            "created_at": created_at,
            "approved_by": {
                "provider": "local",
                "name": "s9k.engine.local",
                "version": "3.0.0",
            },
        },
    }
    if metadata is not None:
        doc["metadata"] = metadata
    return seal_plan(doc) if seal else doc


# ==========================================================================
# Driver mockeado
# ==========================================================================
class FakeResult:
    def __init__(self, record):
        self._record = record

    def single(self):
        return self._record


class FakeTx:
    def __init__(self, driver: "FakeDriver"):
        self.driver = driver
        self.committed = False
        self.rolled_back = False
        self.pending_marks: dict[tuple[str, str], dict] = {}

    def run(self, cypher: str, params: dict):
        self.driver.queries.append((cypher, params))
        n = len(self.driver.queries)
        if self.driver.fail_at is not None and n == self.driver.fail_at:
            raise RuntimeError("el driver se cayo (simulado)")
        if "RETURN n.version AS version" in cypher:
            kind = "assertion" if "V3Assertion" in cypher else "entity"
            state = self.driver.nodes.get((kind, params["id"]))
            return FakeResult(dict(state) if state is not None else None)
        if "V3AppliedOperation" in cypher:
            identity = (params["ws"], params["key"])
            mark = self.driver.applied_marks.get(identity) or self.pending_marks.get(identity)
            if mark is None:
                mark = {
                    "plan_hash": params["plan_hash"],
                    "operation_id": params["operation_id"],
                    "claim_token": params["claim_token"],
                }
                self.pending_marks[identity] = mark
            return FakeResult({
                "plan_hash": mark["plan_hash"],
                "operation_id": mark["operation_id"],
                "created": mark["claim_token"] == params["claim_token"],
            })
        self.driver.writes.append((cypher, params))
        return FakeResult({"id": params.get("props", {}).get("entity_id")
                           or params.get("props", {}).get("assertion_id")
                           or params.get("id")
                           or "rel:1"})

    def commit(self):
        self.committed = True
        self.driver.committed = True
        self.driver.applied_marks.update(self.pending_marks)

    def rollback(self):
        self.rolled_back = True
        self.driver.rolled_back = True


class FakeSession:
    def __init__(self, driver: "FakeDriver"):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin_transaction(self):
        tx = FakeTx(self.driver)
        self.driver.transactions.append(tx)
        return tx


class FakeDriver:
    """Driver de mentira con estado consultable. Nunca habla con Neo4j."""

    def __init__(self, nodes: dict | None = None, fail_at: int | None = None):
        self.nodes = nodes or {}
        self.fail_at = fail_at
        self.queries: list = []
        self.writes: list = []
        self.transactions: list = []
        self.committed = False
        self.rolled_back = False
        self.applied_marks: dict[tuple[str, str], dict] = {}

    def session(self):
        return FakeSession(self)


class ExplodingDriver:
    """Estalla en cuanto alguien lo toca. Prueba de que el dry-run no escribe."""

    def session(self):
        raise AssertionError("el dry-run ha tocado el driver")

    def __getattr__(self, name):
        raise AssertionError(f"el dry-run ha tocado el driver ({name})")


# ==========================================================================
# Peticiones
# ==========================================================================
def apply_env(workspace: str = WORKSPACE) -> dict:
    return {"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": workspace}


def apply_request(plan: dict, **over) -> OperatorRequest:
    """Peticion de APPLY para las pruebas.

    OJO: lee el hash DEL PROPIO PLAN, que es exactamente lo que un operador no
    debe hacer nunca — así la confirmacion no confirma nada. Aqui vale porque el
    plan lo acaba de construir el test y no hay nada que confirmar; en operacion
    real el hash se teclea desde el canal por el que se reviso el plan. Los tests
    que prueban esa condicion pasan el hash a mano.
    """
    base = dict(
        apply=True,
        operator_id="pjc",
        workspace=WORKSPACE,
        expected_plan_hash=plan["plan_hash"]["value"],
        max_operations=50,
        current_snapshot_id=SNAPSHOT,
        env=apply_env(),
    )
    base.update(over)
    return OperatorRequest(**base)


def dry_request(**over) -> OperatorRequest:
    base = dict(apply=False, operator_id="pjc", workspace=WORKSPACE,
                current_snapshot_id=SNAPSHOT, env={})
    base.update(over)
    return OperatorRequest(**base)


def make_writer(driver=None, **over) -> GraphWriter:
    base = dict(workspace=WORKSPACE, driver=driver, audit=InMemoryAuditSink(),
                applied_keys=InMemoryAppliedKeys(), clock=clock_at())
    base.update(over)
    return GraphWriter(**base)


def entity_state(entity_id: str, version: int = 3, state_hash: str = HASH_A["value"]) -> dict:
    return {("entity", entity_id): {"version": version, "state_hash": state_hash}}


# ==========================================================================
# 1. Admision
# ==========================================================================
def ctx(**over) -> AdmissionContext:
    base = dict(workspace=WORKSPACE, current_snapshot_id=SNAPSHOT, clock=clock_at())
    base.update(over)
    return AdmissionContext(**base)


def test_un_plan_sellado_vigente_y_del_workspace_es_admitido():
    result = admit(make_plan(), ctx())
    assert result.admitted
    assert result.view is not None
    assert result.view.workspace == WORKSPACE


def test_plan_no_aprobado_no_se_admite():
    plan = make_plan(approved=False)
    result = admit(plan, ctx())
    assert codes.PLAN_NOT_APPROVED in result.codes


def test_cadena_de_validadores_sin_pass_se_denuncia():
    # Con approved=false el validador congelado no mira la cadena, asi que la
    # comprobacion que se ejerce aqui es la del writer, no la del contrato.
    plan = make_plan(
        approved=False,
        validator_chain=[{"validator": "semantic", "version": "3.0.0", "result": "FAIL"}],
    )
    result = admit(plan, ctx())
    assert codes.PLAN_VALIDATOR_CHAIN_NOT_PASS in result.codes


def test_cadena_de_validadores_vacia_la_caza_el_schema():
    # `minItems: 1` en el contrato congelado. El writer tiene su propia
    # comprobacion por si el schema afloja, pero hoy no llega a ejecutarse.
    plan = make_plan(approved=False, validator_chain=[])
    plan["local_approval"]["validator_chain"] = []
    plan = seal_plan(plan)
    result = admit(plan, ctx())
    assert result.codes == [codes.PLAN_CONTRACT_INVALID]


def test_plan_caducado_se_rechaza_aunque_la_firma_sea_correcta():
    plan = make_plan(expires_at="2026-07-27T11:00:00Z")  # el reloj marca las 12:00
    result = admit(plan, ctx())
    assert result.codes == [codes.PLAN_EXPIRED]


def test_plan_vigente_por_un_minuto_se_admite():
    plan = make_plan(expires_at="2026-07-27T12:01:00Z")
    assert admit(plan, ctx()).admitted


def test_ataque_extender_la_caducidad_sin_resellar_rompe_el_hash():
    plan = make_plan(expires_at="2026-07-27T11:00:00Z")
    plan["expires_at"] = "2027-01-01T00:00:00Z"  # el ataque, sin volver a sellar
    result = admit(plan, ctx())
    assert codes.PLAN_CONTRACT_INVALID in result.codes


def test_ataque_sustituir_la_provider_trace_sin_resellar_rompe_el_hash():
    plan = make_plan()
    plan["provider_trace"] = [
        {
            "step": "engine.plan",
            "provider": "external",
            "name": "nvidia",
            "version": "1",
            "model": "x",
            "produced": ["decisions"],
        }
    ]
    result = admit(plan, ctx())
    assert codes.PLAN_CONTRACT_INVALID in result.codes


def test_ataque_anadir_una_operacion_sin_resellar_rompe_el_hash():
    plan = make_plan()
    plan["mutation_operations"].append(
        op_create_entity("op:9999", "decision:0001", "entity:colado")
    )
    result = admit(plan, ctx())
    assert codes.PLAN_CONTRACT_INVALID in result.codes


def test_un_plan_de_otro_workspace_no_se_admite():
    plan = make_plan(workspace="otra-campana")
    result = admit(plan, ctx())
    assert codes.PLAN_WORKSPACE_MISMATCH in result.codes


def test_snapshot_desfasado_no_se_admite():
    plan = make_plan(snapshot_id="snapshot:neo4j:2020-01-01T00:00:00Z")
    result = admit(plan, ctx())
    assert codes.PLAN_SNAPSHOT_STALE in result.codes


def test_sin_snapshot_declarado_no_hay_testigo_externo_y_no_se_admite():
    result = admit(make_plan(), ctx(current_snapshot_id=None))
    assert codes.PLAN_SNAPSHOT_UNDECLARED in result.codes


def test_plan_aprobado_sin_operaciones_no_se_admite():
    plan = make_plan(approved=False, operations=[], decisions=[
        accept_decision("decision:0001", "entity:daiki", "entity:casa")
    ])
    result = admit(plan, ctx())
    assert codes.PLAN_NO_OPERATIONS in result.codes


def test_version_mayor_de_contrato_no_soportada():
    plan = make_plan(contract_version="2.0.0")
    result = admit(plan, ctx())
    # El validador congelado la caza primero; el writer tiene su propia red.
    assert codes.PLAN_CONTRACT_INVALID in result.codes


def test_documento_que_no_es_un_plan_se_rechaza_con_codigo():
    result = admit({"contract_id": "fact-assertion/v3-internal-v1"}, ctx())
    assert result.codes == [codes.PLAN_CONTRACT_INVALID]


def test_la_admision_no_lanza_nunca_sino_que_devuelve_rechazos():
    for basura in ({}, {"contract_id": None}, {"contract_id": "graph-mutation-plan/v3-internal-v1"}):
        assert not admit(basura, ctx()).admitted


def test_firma_intacta_es_condicion_redundante_pero_real(monkeypatch):
    # El validador congelado ya recalcula los hashes; el writer NO delega en el.
    from knowledge_v3.contracts import GraphMutationPlan

    monkeypatch.setattr(GraphMutationPlan, "signature_is_intact", lambda self: False)
    result = admit(make_plan(), ctx())
    assert codes.PLAN_SIGNATURE_MISMATCH in result.codes


def test_claves_de_idempotencia_no_derivadas_se_denuncian(monkeypatch):
    import knowledge_v3.writer.admission as admission_mod

    monkeypatch.setattr(admission_mod, "compute_idempotency_key", lambda d, o: "idem:sha256:" + "f" * 64)
    result = admit(make_plan(), ctx())
    assert codes.PLAN_IDEMPOTENCY_KEY_UNDERIVED in result.codes


def test_caducidad_ilegible_se_denuncia(monkeypatch):
    import knowledge_v3.writer.admission as admission_mod

    def boom(_value):
        raise ValueError("ilegible")

    monkeypatch.setattr(admission_mod, "parse_iso_utc", boom)
    result = admit(make_plan(), ctx())
    assert codes.PLAN_EXPIRY_UNREADABLE in result.codes


def test_firmante_no_local_se_denuncia(monkeypatch):
    from knowledge_v3.contracts import GraphMutationPlan

    monkeypatch.setattr(GraphMutationPlan, "signed_locally", lambda self: False)
    result = admit(make_plan(), ctx())
    assert codes.PLAN_NOT_SIGNED_LOCALLY in result.codes


def test_la_admision_acumula_todos_los_motivos_no_solo_el_primero():
    plan = make_plan(workspace="otra", snapshot_id="snapshot:viejo", approved=False)
    result = admit(plan, ctx())
    assert {
        codes.PLAN_NOT_APPROVED,
        codes.PLAN_WORKSPACE_MISMATCH,
        codes.PLAN_SNAPSHOT_STALE,
    } <= set(result.codes)


# ==========================================================================
# 2. Gate de operador: las nueve condiciones, en positivo y en negativo
# ==========================================================================
def test_gate_en_positivo_permite_el_apply():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED


def test_gate_1_sin_la_variable_de_entorno_no_se_escribe():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    env = apply_env()
    env["S9K_ALLOW_REAL_INGEST"] = "true"  # ni "true", ni "yes": exactamente "1"
    result = writer.write(plan, apply_request(plan, env=env))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_ENV_NOT_ALLOWED in result.codes


def test_gate_2_el_modo_por_defecto_es_dry_run():
    plan = make_plan()
    writer = make_writer(ExplodingDriver())
    result = writer.write(plan, dry_request())
    assert result.outcome == OUTCOME_SIMULATED
    assert result.mode == MODE_DRY_RUN


def test_gate_2_apply_debe_pedirse_explicitamente():
    from knowledge_v3.writer.gate import evaluate

    plan = make_plan()
    view = admit(plan, ctx()).view
    gate = evaluate(
        view,
        OperatorRequest(
            apply=False,
            operator_id="pjc",
            workspace=WORKSPACE,
            expected_plan_hash=plan["plan_hash"]["value"],
            env=apply_env(),
        ),
        audit_available=True,
    )
    assert codes.GATE_APPLY_NOT_REQUESTED in gate.codes


def test_gate_3_sin_operador_no_se_escribe():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan, operator_id=None))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_OPERATOR_MISSING in result.codes


def test_gate_4_operador_con_forma_inadmisible_no_se_escribe():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan, operator_id="pj c; DROP"))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_OPERATOR_INVALID in result.codes


def test_gate_5_sin_confirmar_el_hash_del_plan_no_se_escribe():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan, expected_plan_hash=None))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_PLAN_HASH_NOT_CONFIRMED in result.codes


def test_gate_5_confirmar_otro_hash_no_vale():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan, expected_plan_hash="d" * 64))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_PLAN_HASH_NOT_CONFIRMED in result.codes


def test_gate_5_el_hash_se_admite_tambien_como_bloque_completo():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan, expected_plan_hash=plan["plan_hash"]))
    assert result.outcome == OUTCOME_APPLIED


def test_gate_6_el_limite_de_operaciones_se_respeta():
    ops = [
        op_create_entity(f"op:{i:04d}", "decision:0001", f"entity:e{i}")
        for i in range(4)
    ]
    plan = make_plan(operations=ops)
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan, max_operations=3))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_OPERATION_LIMIT_EXCEEDED in result.codes


def test_gate_6_un_plan_dentro_del_limite_pasa():
    ops = [
        op_create_entity(f"op:{i:04d}", "decision:0001", f"entity:e{i}")
        for i in range(3)
    ]
    plan = make_plan(operations=ops)
    writer = make_writer(FakeDriver())
    result = writer.write(plan, apply_request(plan, max_operations=3))
    assert result.outcome == OUTCOME_APPLIED
    assert result.applied_operations == 3


def test_gate_7_sin_la_segunda_declaracion_del_workspace_no_se_escribe():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    env = apply_env()
    env.pop("S9K_WRITER_WORKSPACE")
    result = writer.write(plan, apply_request(plan, env=env))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_WORKSPACE_NOT_DECLARED in result.codes


def test_gate_8_las_dos_declaraciones_del_workspace_deben_coincidir():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    env = apply_env(workspace="otra-campana")
    result = writer.write(plan, apply_request(plan, env=env))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_WORKSPACE_DECLARATION_MISMATCH in result.codes


def test_gate_8_el_argumento_tiene_que_ser_el_del_writer():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(
        plan, apply_request(plan, workspace="otra", env=apply_env("otra"))
    )
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_WORKSPACE_DECLARATION_MISMATCH in result.codes


def test_gate_9_sin_registro_de_auditoria_no_se_escribe():
    plan = make_plan()
    sink = InMemoryAuditSink()
    sink._available = False
    writer = make_writer(FakeDriver(), audit=sink)
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_AUDIT_UNAVAILABLE in result.codes


def test_el_gate_acumula_todas_las_condiciones_incumplidas():
    plan = make_plan()
    writer = make_writer(FakeDriver())
    result = writer.write(
        plan, apply_request(plan, operator_id=None, expected_plan_hash=None, env={})
    )
    assert {
        codes.GATE_ENV_NOT_ALLOWED,
        codes.GATE_OPERATOR_MISSING,
        codes.GATE_PLAN_HASH_NOT_CONFIRMED,
        codes.GATE_WORKSPACE_NOT_DECLARED,
    } <= set(result.codes)


def test_un_plan_bloqueado_por_el_gate_no_toca_el_driver():
    plan = make_plan()
    writer = make_writer(ExplodingDriver())
    result = writer.write(plan, apply_request(plan, env={}))
    assert result.outcome == OUTCOME_BLOCKED


def test_la_admision_va_antes_que_el_gate():
    # Un plan de otro workspace con el gate perfecto sigue siendo REJECTED, no
    # BLOCKED: primero se juzga el plan, y solo despues al operador.
    plan = make_plan(workspace="otra")
    writer = make_writer(ExplodingDriver())
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_REJECTED
    assert codes.PLAN_WORKSPACE_MISMATCH in result.codes


# ==========================================================================
# 3. Dry-run
# ==========================================================================
def test_el_dry_run_no_toca_el_driver_ni_con_un_plan_perfecto():
    plan = make_plan()
    writer = make_writer(ExplodingDriver())
    result = writer.write(plan, dry_request())
    assert result.outcome == OUTCOME_SIMULATED
    assert result.applied_operations == 1
    assert result.created_ids == []


def test_el_dry_run_tambien_rechaza_un_plan_inadmisible():
    plan = make_plan(expires_at="2026-07-27T11:00:00Z")
    writer = make_writer(ExplodingDriver())
    result = writer.write(plan, dry_request())
    assert result.outcome == OUTCOME_REJECTED
    assert codes.PLAN_EXPIRED in result.codes


def test_el_dry_run_no_registra_claves_como_aplicadas():
    plan = make_plan()
    keys = InMemoryAppliedKeys()
    writer = make_writer(ExplodingDriver(), applied_keys=keys)
    writer.write(plan, dry_request())
    assert keys.entries == {}


def test_el_dry_run_cuenta_como_no_op_lo_ya_aplicado():
    plan = make_plan()
    keys = InMemoryAppliedKeys()
    keys.record(plan["mutation_operations"][0]["idempotency_key"], {})
    writer = make_writer(ExplodingDriver(), applied_keys=keys)
    result = writer.write(plan, dry_request())
    assert result.noop_operations == 1
    assert result.applied_operations == 0


# ==========================================================================
# 4. Ejecucion
# ==========================================================================
def test_apply_crea_la_entidad_y_confirma_la_transaccion():
    plan = make_plan()
    driver = FakeDriver()
    writer = make_writer(driver)
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED
    assert driver.committed and not driver.rolled_back
    assert result.created_ids == ["entity:daiki"]
    assert any("CREATE (n:V3Entity:Character" in q for q, _ in driver.writes)


def test_ninguna_consulta_ejecutada_es_destructiva():
    ops = [
        op_create_entity("op:0001", "decision:0001", "entity:nueva"),
        op_create_assertion("op:0002", "decision:0001", "assertion:1", "entity:daiki", "entity:casa"),
        op_link("op:0003", "decision:0001", "entity:daiki", "entity:casa"),
        op_supersede("op:0004", "decision:0001", "assertion:vieja"),
    ]
    plan = make_plan(operations=ops)
    nodes = {
        ("entity", "entity:daiki"): {"version": 3, "state_hash": HASH_A["value"]},
        ("assertion", "assertion:vieja"): {"version": 2, "state_hash": HASH_B["value"]},
    }
    driver = FakeDriver(nodes=nodes)
    writer = make_writer(driver)
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes
    for query, _ in driver.queries:
        assert_safe(query)  # no lanza
        upper = query.upper()
        for prohibido in ("MERGE", "DELETE", "DETACH", "REMOVE", "DROP"):
            if prohibido == "MERGE" and "V3APPLIEDOPERATION" in upper:
                continue
            assert prohibido not in upper


def test_el_reason_code_viaja_al_grafo_r1():
    ops = [op_supersede("op:0001", "decision:0001", "assertion:vieja",
                        reason_code="COPYRIGHT_TAKEDOWN")]
    plan = make_plan(operations=ops)
    driver = FakeDriver(nodes={("assertion", "assertion:vieja"):
                               {"version": 2, "state_hash": HASH_B["value"]}})
    writer = make_writer(driver)
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes
    _, params = driver.writes[0]
    assert params["set_reason_code"] == "COPYRIGHT_TAKEDOWN"


def test_un_cierre_de_vigencia_sin_reason_code_aborta_el_plan_r1():
    ops = [op_supersede("op:0001", "decision:0001", "assertion:vieja", with_reason=False)]
    plan = make_plan(operations=ops)
    driver = FakeDriver(nodes={("assertion", "assertion:vieja"):
                               {"version": 2, "state_hash": HASH_B["value"]}})
    writer = make_writer(driver)
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_REASON_CODE_MISSING in result.codes
    assert not driver.committed


def test_las_razones_de_la_decision_viajan_a_lo_creado():
    plan = make_plan()
    driver = FakeDriver()
    make_writer(driver).write(plan, apply_request(plan))
    _, params = driver.writes[0]
    assert params["props"]["reason_codes"] == ["LOCAL_APPROVED"]


def test_el_snapshot_viaja_al_grafo_como_testigo_r2():
    plan = make_plan()
    driver = FakeDriver()
    make_writer(driver).write(plan, apply_request(plan))
    _, params = driver.writes[0]
    assert params["props"]["written_snapshot_id"] == SNAPSHOT
    assert params["props"]["written_by_plan_hash"] == plan["plan_hash"]["value"]


def test_el_snapshot_queda_registrado_fuera_del_ledger_r2(tmp_path):
    plan = make_plan()
    keys = JsonlAppliedKeys(tmp_path / "keys.jsonl")
    driver = FakeDriver()
    make_writer(driver, applied_keys=keys).write(plan, apply_request(plan))
    entry = keys.get(plan["mutation_operations"][0]["idempotency_key"])
    assert entry["snapshot_id"] == SNAPSHOT
    assert entry["plan_hash"] == plan["plan_hash"]["value"]


def test_el_operador_y_el_instante_quedan_en_lo_escrito():
    plan = make_plan()
    driver = FakeDriver()
    make_writer(driver).write(plan, apply_request(plan))
    _, params = driver.writes[0]
    assert params["props"]["written_by_operator"] == "pjc"
    assert params["props"]["written_at"] == "2026-07-27T12:00:00Z"


def test_crear_algo_que_ya_existe_aborta_el_plan():
    plan = make_plan()
    driver = FakeDriver(nodes=entity_state("entity:daiki"))
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_TARGET_ALREADY_EXISTS in result.codes
    assert driver.writes == []


def test_operar_sobre_algo_que_no_existe_aborta_el_plan():
    plan = make_plan(operations=[op_link("op:0001", "decision:0001", "entity:x", "entity:y")])
    driver = FakeDriver(nodes={})
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_TARGET_MISSING in result.codes


def test_desajuste_de_version_aborta_el_plan_entero():
    ops = [
        op_link("op:0001", "decision:0001", "entity:daiki", "entity:casa", version=3),
        op_create_entity("op:0002", "decision:0001", "entity:nueva"),
    ]
    plan = make_plan(operations=ops)
    driver = FakeDriver(nodes=entity_state("entity:daiki", version=7))
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_VERSION_MISMATCH in result.codes
    assert driver.writes == []
    assert driver.rolled_back and not driver.committed


def test_desajuste_de_hash_de_estado_aborta_el_plan():
    plan = make_plan(operations=[op_link("op:0001", "decision:0001", "entity:daiki", "entity:casa")])
    driver = FakeDriver(nodes=entity_state("entity:daiki", state_hash="e" * 64))
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_HASH_MISMATCH in result.codes


def test_version_y_hash_correctos_dejan_pasar_la_operacion():
    plan = make_plan(operations=[op_link("op:0001", "decision:0001", "entity:daiki", "entity:casa")])
    driver = FakeDriver(nodes=entity_state("entity:daiki"))
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes


def test_el_cierre_de_vigencia_sube_la_version():
    plan = make_plan(operations=[op_supersede("op:0001", "decision:0001", "assertion:vieja", version=2)])
    driver = FakeDriver(nodes={("assertion", "assertion:vieja"):
                               {"version": 2, "state_hash": HASH_B["value"]}})
    make_writer(driver).write(plan, apply_request(plan))
    _, params = driver.writes[0]
    assert params["set_version"] == 3


def test_un_payload_que_pisa_una_propiedad_reservada_aborta():
    op = op_create_entity("op:0001", "decision:0001", "entity:daiki")
    op["payload"]["written_by_operator"] = "otro"
    plan = make_plan(operations=[op])
    driver = FakeDriver()
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_UNSUPPORTED_PAYLOAD in result.codes


def test_el_dry_run_rechaza_el_mismo_payload_reservado_que_apply():
    """REGRESION F7-2: simular no puede ocultar un payload inejecutable."""
    operation = op_create_entity("op:0001", "decision:0001", "entity:daiki")
    operation["payload"]["written_by_operator"] = "otro"
    plan = make_plan(operations=[operation])

    result = make_writer(ExplodingDriver()).write(plan, dry_request())

    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_UNSUPPORTED_PAYLOAD in result.codes


def test_una_etiqueta_con_forma_rara_aborta_en_vez_de_interpolarse():
    op = op_create_entity("op:0001", "decision:0001", "entity:daiki")
    op["payload"]["entity_type"] = "Character) DETACH DELETE (n"
    plan = make_plan(operations=[op])
    driver = FakeDriver()
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_UNSUPPORTED_PAYLOAD in result.codes
    assert driver.writes == []


def test_un_predicado_con_forma_rara_aborta():
    op = op_link("op:0001", "decision:0001", "entity:daiki", "entity:casa")
    op["payload"]["predicate"] = "MEMBER_OF]->() DELETE n //"
    plan = make_plan(operations=[op])
    driver = FakeDriver(nodes=entity_state("entity:daiki"))
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_UNSUPPORTED_PAYLOAD in result.codes


def test_la_guardia_bloquea_cualquier_consulta_destructiva():
    for destructiva in (
        "MATCH (n) DETACH DELETE n",
        "MERGE (n:V3Entity {id: $id})",
        "MATCH (n) REMOVE n:V3Entity",
        "MATCH (n) SET n = $props",
        "MATCH (n) SET n += $props",
        "DROP INDEX foo",
        "CALL apoc.periodic.iterate('x','y',{})",
    ):
        with pytest.raises(WriterAbort) as exc:
            assert_safe(destructiva)
        assert exc.value.code == codes.EXEC_DESTRUCTIVE_QUERY_BLOCKED


def test_apply_sin_driver_no_inventa_una_conexion():
    plan = make_plan()
    writer = make_writer(driver=None)
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_DRIVER_FAILURE in result.codes


# ==========================================================================
# 5. Idempotencia
# ==========================================================================
def test_reaplicar_el_mismo_plan_no_escribe_dos_veces():
    plan = make_plan()
    keys = InMemoryAppliedKeys()
    primero = FakeDriver()
    r1 = make_writer(primero, applied_keys=keys).write(plan, apply_request(plan))
    assert r1.outcome == OUTCOME_APPLIED and r1.applied_operations == 1
    writes_after_first = list(primero.writes)

    segundo = primero
    r2 = make_writer(segundo, applied_keys=keys).write(plan, apply_request(plan))
    assert r2.outcome == OUTCOME_APPLIED
    assert r2.applied_operations == 0
    assert r2.noop_operations == 1
    assert segundo.writes == writes_after_first


def test_la_misma_clave_con_plan_distinto_falla_cerrado():
    # Misma identidad logica, distinto plan_id y created_at: la clave se deriva
    # de (workspace, snapshot, identidad de la operacion), no del plan.
    plan_a = make_plan()
    plan_b = make_plan(created_at="2026-07-27T10:31:00Z")
    plan_b["plan_id"] = "plan:otro:0002"
    plan_b = seal_plan(plan_b)
    assert (
        plan_a["mutation_operations"][0]["idempotency_key"]
        == plan_b["mutation_operations"][0]["idempotency_key"]
    )
    keys = InMemoryAppliedKeys()
    driver = FakeDriver()
    # Neo4j is authoritative. Simulate the committed marker surviving while
    # the local cache is shared by copying the transactional mark.
    first_driver = FakeDriver()
    make_writer(first_driver, applied_keys=keys).write(plan_a, apply_request(plan_a))
    driver.applied_marks.update(first_driver.applied_marks)
    result = make_writer(driver, applied_keys=keys).write(plan_b, apply_request(plan_b))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_IDEMPOTENCY_CONFLICT in result.codes
    assert driver.writes == []


def test_la_idempotencia_sobrevive_a_reiniciar_el_writer(tmp_path):
    plan = make_plan()
    path = tmp_path / "applied.jsonl"
    driver = FakeDriver()
    make_writer(driver, applied_keys=JsonlAppliedKeys(path)).write(
        plan, apply_request(plan)
    )
    writes_after_first = list(driver.writes)
    # Otro proceso, otro almacen cargado del mismo fichero.
    result = make_writer(driver, applied_keys=JsonlAppliedKeys(path)).write(
        plan, apply_request(plan)
    )
    assert result.noop_operations == 1
    assert driver.writes == writes_after_first


def test_un_plan_abortado_no_deja_claves_registradas():
    ops = [
        op_create_entity("op:0001", "decision:0001", "entity:uno"),
        op_link("op:0002", "decision:0001", "entity:fantasma", "entity:casa"),
    ]
    plan = make_plan(operations=ops)
    keys = InMemoryAppliedKeys()
    driver = FakeDriver(nodes={})
    result = make_writer(driver, applied_keys=keys).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert keys.entries == {}


def test_el_almacen_persistente_no_duplica_una_clave(tmp_path):
    store = JsonlAppliedKeys(tmp_path / "k.jsonl")
    store.record("idem:sha256:" + "1" * 64, {"a": 1})
    store.record("idem:sha256:" + "1" * 64, {"a": 2})
    lines = (tmp_path / "k.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert store.get("idem:sha256:" + "1" * 64)["a"] == 1


# ==========================================================================
# 6. Transaccionalidad y rollback
# ==========================================================================
def test_un_fallo_en_la_operacion_n_no_deja_nada_escrito():
    ops = [
        op_create_entity("op:0001", "decision:0001", "entity:uno"),
        op_create_entity("op:0002", "decision:0001", "entity:dos"),
        op_create_entity("op:0003", "decision:0001", "entity:tres"),
    ]
    plan = make_plan(operations=ops)
    # Cada CREATE hace 2 consultas (comprobar ausencia + crear). La 4a es la
    # comprobacion de la segunda operacion: revienta con una escritura hecha.
    driver = FakeDriver(fail_at=4)
    keys = InMemoryAppliedKeys()
    result = make_writer(driver, applied_keys=keys).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_DRIVER_FAILURE in result.codes
    assert driver.rolled_back is True
    assert driver.committed is False
    assert keys.entries == {}
    assert result.created_ids == []


def test_el_rollback_se_pide_siempre_que_la_transaccion_no_confirma():
    plan = make_plan(operations=[op_link("op:0001", "decision:0001", "entity:x", "entity:y")])
    driver = FakeDriver(nodes={})
    make_writer(driver).write(plan, apply_request(plan))
    assert driver.transactions[0].rolled_back is True


def test_el_writer_sabe_generar_las_instrucciones_inversas():
    ops = [
        op_create_entity("op:0001", "decision:0001", "entity:daiki"),
        op_link("op:0002", "decision:0001", "entity:daiki", "entity:casa"),
        op_supersede("op:0003", "decision:0001", "assertion:vieja"),
    ]
    plan = make_plan(operations=ops)
    nodes = {
        ("entity", "entity:daiki"): {"version": 3, "state_hash": HASH_A["value"]},
        ("assertion", "assertion:vieja"): {"version": 2, "state_hash": HASH_B["value"]},
    }
    # entity:daiki no existe para el CREATE pero si para el LINK: se resuelve
    # creando el plan con el CREATE sobre otra entidad.
    ops[0] = op_create_entity("op:0001", "decision:0001", "entity:nueva")
    plan = make_plan(operations=ops)
    driver = FakeDriver(nodes=nodes)
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes
    acciones = [i.action for i in result.rollback.instructions]
    # Orden inverso: primero se deshace lo ultimo que se hizo.
    assert acciones == ["RESTORE_PROPERTIES", "DELETE_RELATIONSHIP", "DELETE_NODE"]


def test_el_rollback_declara_lo_que_no_puede_restaurar():
    plan = make_plan(operations=[op_supersede("op:0001", "decision:0001", "assertion:vieja")])
    driver = FakeDriver(nodes={("assertion", "assertion:vieja"):
                               {"version": 2, "state_hash": HASH_B["value"]}})
    result = make_writer(driver).write(plan, apply_request(plan))
    # `status`, `valid_to` y `reason_code` no se leyeron antes de escribirlos:
    # el documento lo dice en vez de fingir que puede devolverlos.
    assert result.rollback.unrecoverable


def test_el_rollback_no_ejecuta_nada_por_su_cuenta():
    plan = make_plan()
    driver = FakeDriver()
    result = make_writer(driver).write(plan, apply_request(plan))
    assert len(driver.writes) == 1  # solo la creacion; ninguna instruccion inversa
    assert result.rollback.instructions[0].action == "DELETE_NODE"
    assert json.dumps(result.rollback.to_dict())  # es un documento serializable


# ==========================================================================
# 7. Auditoria
# ==========================================================================
def test_se_audita_el_intento_aceptado():
    plan = make_plan()
    sink = InMemoryAuditSink()
    make_writer(FakeDriver(), audit=sink).write(plan, apply_request(plan))
    # Dos lineas: la del intento (antes de tocar el grafo) y la del desenlace.
    assert [r["outcome"] for r in sink.records] == [OUTCOME_ATTEMPTED, OUTCOME_APPLIED]
    assert sink.records[-1]["mode"] == MODE_APPLY
    assert sink.records[-1]["operator_id"] == "pjc"


def test_el_intento_se_anota_antes_de_tocar_el_grafo():
    """Si el proceso muere a mitad de la transaccion, la linea ATTEMPTED es lo
    unico que dice que alguien lo intento. Por eso va primero."""
    plan = make_plan()
    sink = InMemoryAuditSink()
    driver = FakeDriver(fail_at=1)
    result = make_writer(driver, audit=sink).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert sink.records[0]["outcome"] == OUTCOME_ATTEMPTED
    assert sink.records[0]["detail"] == {"operations": 1}


def test_el_dry_run_no_anota_intento_porque_no_intenta_nada():
    plan = make_plan()
    sink = InMemoryAuditSink()
    make_writer(ExplodingDriver(), audit=sink).write(plan, dry_request())
    assert [r["outcome"] for r in sink.records] == [OUTCOME_SIMULATED]


def test_se_audita_el_intento_rechazado_en_admision():
    plan = make_plan(workspace="otra")
    sink = InMemoryAuditSink()
    make_writer(FakeDriver(), audit=sink).write(plan, apply_request(plan))
    assert sink.records[0]["outcome"] == OUTCOME_REJECTED
    assert sink.records[0]["rejections"][0]["code"] == codes.PLAN_WORKSPACE_MISMATCH


def test_se_audita_el_intento_bloqueado_por_el_gate():
    plan = make_plan()
    sink = InMemoryAuditSink()
    make_writer(FakeDriver(), audit=sink).write(plan, apply_request(plan, env={}))
    assert sink.records[0]["outcome"] == OUTCOME_BLOCKED
    assert sink.records[0]["rejections"]


def test_se_audita_el_intento_abortado():
    plan = make_plan(operations=[op_link("op:0001", "decision:0001", "entity:x", "entity:y")])
    sink = InMemoryAuditSink()
    make_writer(FakeDriver(nodes={}), audit=sink).write(plan, apply_request(plan))
    assert sink.records[-1]["outcome"] == OUTCOME_ABORTED


def test_se_audita_tambien_el_dry_run():
    plan = make_plan()
    sink = InMemoryAuditSink()
    make_writer(ExplodingDriver(), audit=sink).write(plan, dry_request())
    assert sink.records[0]["outcome"] == OUTCOME_SIMULATED
    assert sink.records[0]["mode"] == MODE_DRY_RUN


def test_el_registro_de_auditoria_es_append_only(tmp_path):
    path = tmp_path / "audit.jsonl"
    plan = make_plan()
    sink = JsonlAuditSink(path)
    writer = make_writer(FakeDriver(), audit=sink)
    writer.write(plan, dry_request())
    writer.write(plan, apply_request(plan, env={}))
    writer.write(plan, apply_request(plan))
    lineas = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 4
    outcomes = [json.loads(l)["outcome"] for l in lineas]
    assert outcomes == [
        OUTCOME_SIMULATED,
        OUTCOME_BLOCKED,
        OUTCOME_ATTEMPTED,
        OUTCOME_APPLIED,
    ]


def test_el_sink_real_se_declara_no_disponible_si_no_puede_escribir(tmp_path):
    imposible = tmp_path / "fichero.txt"
    imposible.write_text("no soy un directorio", encoding="utf-8")
    sink = JsonlAuditSink(imposible / "sub" / "audit.jsonl")
    assert sink.available() is False


# ==========================================================================
# 7bis. Lo que el revisor independiente encontro
# ==========================================================================
class SinkQueMiente:
    """Se declara disponible y luego falla al escribir.

    La condicion 9 del gate comprueba disponibilidad, que es una PROMESA. Este
    sink la rompe: es la unica forma de probar que el writer no se fia de ella.
    """

    def __init__(self, fallar_desde: int = 1):
        self.fallar_desde = fallar_desde
        self.intentos = 0
        self.records: list = []

    def available(self) -> bool:
        return True

    def append(self, record) -> None:
        self.intentos += 1
        if self.intentos >= self.fallar_desde:
            raise OSError("disco lleno (simulado)")
        self.records.append(record.to_dict())

    def read_all(self) -> list:
        return list(self.records)


def test_el_limite_del_writer_aplica_aunque_la_peticion_no_opine():
    """M1: con `max_operations` por defecto en la peticion, el limite del writer
    era inaplicable y se colaban 60 operaciones con un writer de 50."""
    ops = [
        op_create_entity(f"op:{i:04d}", "decision:0001", f"entity:e{i}")
        for i in range(10)
    ]
    plan = make_plan(operations=ops)
    driver = FakeDriver()
    writer = make_writer(driver, max_operations=3)
    result = writer.write(
        plan,
        OperatorRequest(
            apply=True,
            operator_id="pjc",
            workspace=WORKSPACE,
            expected_plan_hash=plan["plan_hash"]["value"],
            current_snapshot_id=SNAPSHOT,
            env=apply_env(),
        ),
    )
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_OPERATION_LIMIT_EXCEEDED in result.codes
    assert driver.writes == []


def test_manda_el_menor_de_los_dos_limites():
    """Ninguno de los dos puede relajar al otro."""
    ops = [
        op_create_entity(f"op:{i:04d}", "decision:0001", f"entity:e{i}")
        for i in range(5)
    ]
    plan = make_plan(operations=ops)
    # Peticion generosa, writer estrecho.
    r1 = make_writer(FakeDriver(), max_operations=3).write(
        plan, apply_request(plan, max_operations=50)
    )
    assert codes.GATE_OPERATION_LIMIT_EXCEEDED in r1.codes
    # Writer generoso, peticion estrecha.
    r2 = make_writer(FakeDriver(), max_operations=50).write(
        plan, apply_request(plan, max_operations=3)
    )
    assert codes.GATE_OPERATION_LIMIT_EXCEEDED in r2.codes
    # Los dos holgados: pasa.
    r3 = make_writer(FakeDriver(), max_operations=50).write(
        plan, apply_request(plan, max_operations=10)
    )
    assert r3.outcome == OUTCOME_APPLIED, r3.codes


def test_un_limite_booleano_no_cuela_como_limite_de_uno():
    """B3: en Python `True` es un `int`, y `max_operations=True` valia 1."""
    plan = make_plan()
    result = make_writer(FakeDriver()).write(plan, apply_request(plan, max_operations=True))
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_OPERATION_LIMIT_EXCEEDED in result.codes


def test_si_no_se_puede_anotar_el_intento_no_se_escribe():
    """M2: un sink que se declara disponible y luego falla dejaba una escritura
    real sin una sola linea de rastro."""
    plan = make_plan()
    driver = FakeDriver()
    result = make_writer(driver, audit=SinkQueMiente(fallar_desde=1)).write(
        plan, apply_request(plan)
    )
    assert result.outcome == OUTCOME_BLOCKED
    assert codes.GATE_AUDIT_UNAVAILABLE in result.codes
    assert driver.writes == []


def test_si_falla_la_linea_del_desenlace_el_operador_se_entera():
    """El intento si quedo anotado, asi que se escribe; pero el resultado dice
    que su linea final no esta."""
    plan = make_plan()
    driver = FakeDriver()
    result = make_writer(driver, audit=SinkQueMiente(fallar_desde=2)).write(
        plan, apply_request(plan)
    )
    assert result.outcome == OUTCOME_APPLIED
    assert len(driver.writes) == 1
    assert codes.AUDIT_APPEND_FAILED in result.codes


def test_un_plan_hash_que_no_es_un_bloque_no_deja_el_intento_sin_linea():
    """M3: `(plan_doc.get("plan_hash") or {}).get("value")` reventaba con
    AttributeError, sin codigo y sin auditoria."""
    plan = make_plan()
    plan["plan_hash"] = "no-es-un-bloque"
    sink = InMemoryAuditSink()
    result = make_writer(FakeDriver(), audit=sink).write(
        plan, apply_request(make_plan(), expected_plan_hash="d" * 64)
    )
    assert result.outcome == OUTCOME_REJECTED
    assert codes.PLAN_CONTRACT_INVALID in result.codes
    assert len(sink.records) == 1
    assert sink.records[0]["plan_hash"] == "'no-es-un-bloque'"


def test_ningun_documento_deforme_deja_un_intento_sin_auditar():
    deformes = [
        {},
        {"contract_id": "graph-mutation-plan/v3-internal-v1", "plan_hash": []},
        {"contract_id": "graph-mutation-plan/v3-internal-v1", "plan_id": ["a"]},
        {"contract_id": "graph-mutation-plan/v3-internal-v1", "plan_hash": 7},
        {"contract_id": None, "snapshot_id": {"raro": True}},
    ]
    for doc in deformes:
        sink = InMemoryAuditSink()
        result = make_writer(FakeDriver(), audit=sink).write(doc, apply_request(make_plan()))
        assert result.outcome == OUTCOME_REJECTED
        assert result.codes
        assert len(sink.records) == 1


def test_la_query_destructiva_muere_en_el_constructor():
    """M5: quitar `assert_safe` de `Query.__post_init__` dejaba la suite verde.
    Este test usa el camino publico —construir una Query— y lo pone rojo."""
    from knowledge_v3.writer.cypher import Query

    for destructiva in (
        "MATCH (n) DETACH DELETE n",
        "MERGE (n:V3Entity {entity_id: $id})",
        "MATCH (n) SET n += $props",
    ):
        with pytest.raises(WriterAbort) as exc:
            Query(destructiva, {})
        assert exc.value.code == codes.EXEC_DESTRUCTIVE_QUERY_BLOCKED


def test_un_salto_de_linea_final_no_cuela_por_ninguna_de_las_cuatro_regex():
    """B1: `$` casa antes de un `\\n` final; con `\\Z` no."""
    plan = make_plan()
    r1 = make_writer(FakeDriver()).write(plan, apply_request(plan, operator_id="pjc\n"))
    assert codes.GATE_OPERATOR_INVALID in r1.codes

    op = op_create_entity("op:0001", "decision:0001", "entity:daiki")
    op["payload"]["entity_type"] = "Character\n"
    r2 = make_writer(FakeDriver()).write(
        (p := make_plan(operations=[op])), apply_request(p)
    )
    assert codes.EXEC_UNSUPPORTED_PAYLOAD in r2.codes

    sup = op_supersede("op:0001", "decision:0001", "assertion:vieja")
    sup["payload"]["reason_code"] = "COPYRIGHT_TAKEDOWN\n"
    plan3 = make_plan(operations=[sup])
    driver = FakeDriver(nodes={("assertion", "assertion:vieja"):
                               {"version": 2, "state_hash": HASH_B["value"]}})
    r3 = make_writer(driver).write(plan3, apply_request(plan3))
    assert codes.EXEC_REASON_CODE_MISSING in r3.codes


def test_la_fabrica_de_driver_no_se_invoca_si_el_gate_bloquea():
    """B2: la CLI construia el driver ANTES del gate, gastando credenciales y
    una sesion en un intento que todavia podia bloquearse."""
    llamadas = []

    def fabrica():
        llamadas.append(1)
        return FakeDriver()

    plan = make_plan()
    writer = GraphWriter(
        workspace=WORKSPACE,
        driver_factory=fabrica,
        audit=InMemoryAuditSink(),
        applied_keys=InMemoryAppliedKeys(),
        clock=clock_at(),
    )
    assert writer.write(plan, apply_request(plan, env={})).outcome == OUTCOME_BLOCKED
    assert llamadas == []
    assert writer.write(plan, apply_request(plan)).outcome == OUTCOME_APPLIED
    assert llamadas == [1]


def test_una_fabrica_que_falla_aborta_con_codigo():
    def fabrica():
        raise RuntimeError("no hay Neo4j al otro lado")

    plan = make_plan()
    writer = GraphWriter(
        workspace=WORKSPACE,
        driver_factory=fabrica,
        audit=InMemoryAuditSink(),
        applied_keys=InMemoryAppliedKeys(),
        clock=clock_at(),
    )
    result = writer.write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_DRIVER_FAILURE in result.codes


def test_la_auditoria_conserva_los_campos_que_el_writer_no_puede_usar():
    """M4: la doc prometia que el documento informativo llegaba al registro.
    Ahora llega de verdad: describir sin decidir exige conservarlos."""
    plan = make_plan(metadata={"origen": "revision manual"})
    plan = seal_plan(plan)
    sink = InMemoryAuditSink()
    make_writer(FakeDriver(), audit=sink).write(plan, apply_request(plan))
    unsigned = sink.records[-1]["unsigned"]
    assert unsigned["plan_id"] == plan["plan_id"]
    assert unsigned["created_at"] == plan["created_at"]
    assert unsigned["metadata"] == {"origen": "revision manual"}
    assert unsigned["provider_trace"] == plan["provider_trace"]


# ==========================================================================
# 8. Higiene: nada de conexiones ni credenciales
# ==========================================================================
def test_el_paquete_del_writer_no_importa_neo4j_ni_lleva_credenciales():
    from pathlib import Path

    import knowledge_v3.writer as pkg

    raiz = Path(pkg.__file__).parent
    prohibidos = ("import neo4j", "from neo4j", "bolt://", "neo4j://", "password=")
    for fichero in sorted(raiz.glob("*.py")):
        texto = fichero.read_text(encoding="utf-8")
        for prohibido in prohibidos:
            assert prohibido not in texto, f"{fichero.name} contiene {prohibido!r}"


def test_la_cli_no_abre_ninguna_conexion_por_defecto():
    from knowledge_v3.writer.cli import no_driver

    with pytest.raises(NotImplementedError):
        no_driver()


def test_un_writer_sin_workspace_no_existe():
    with pytest.raises(ValueError):
        GraphWriter(workspace="")
