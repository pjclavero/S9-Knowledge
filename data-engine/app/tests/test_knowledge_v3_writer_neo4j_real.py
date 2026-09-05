# -*- coding: utf-8 -*-
"""Writer V3 contra un Neo4j real y efimero.

Estas pruebas estan saltadas por defecto porque arrancan un contenedor Docker.
Se activan explicitamente con:

    S9K_WRITER_NEO4J_REAL=1 python -m pytest data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py -q

No aceptan una URI externa: el fixture levanta y destruye su propio Neo4j.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

pytest.importorskip("jsonschema")
neo4j = pytest.importorskip("neo4j")

from knowledge_v3.contracts.base import seal_plan  # noqa: E402
from knowledge_v3.writer import (  # noqa: E402
    GraphWriter,
    InMemoryAppliedKeys,
    InMemoryAuditSink,
    OperatorRequest,
    APPLIED_OPERATION_CONSTRAINT,
    bootstrap_writer_schema,
    codes,
)
from knowledge_v3.writer.writer import (  # noqa: E402
    OUTCOME_ABORTED,
    OUTCOME_APPLIED,
    OUTCOME_BLOCKED,
    OUTCOME_SIMULATED,
)


LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1",
)

WORKSPACE = "writer-real"
OTHER_WORKSPACE = "writer-real-otro"
SNAPSHOT = "snapshot:neo4j:real:2026-07-27T10:29:00Z"
NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
HASH_A = {"algorithm": "sha256", "value": "a" * 64}
HASH_B = {"algorithm": "sha256", "value": "b" * 64}
HASH_C = {"algorithm": "sha256", "value": "c" * 64}


def _clock():
    return NOW


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, text=True, capture_output=True, check=check)
    except FileNotFoundError as exc:
        raise RuntimeError(f"ejecutable no disponible: {cmd[0]}") from exc


@contextmanager
def neo4j_efimero(prefijo: str = "s9k-v3-writer-test"):
    """Levanta y destruye un Neo4j propio. UN solo mecanismo de arranque.

    Lo usan la fixture de sesion y cualquier prueba que necesite una SEGUNDA
    base -- por ejemplo la que comprueba que un documento de rollback sigue
    siendo ejecutable cuando los `elementId` ya no son los mismos, porque el
    `elementId` lleva dentro el UUID de la base.
    """
    image = os.environ.get("S9K_WRITER_NEO4J_IMAGE", "neo4j:5.26-community")
    name = prefijo + "-" + uuid.uuid4().hex[:12]
    port = _free_port()
    password = "s9k-writer-real-" + uuid.uuid4().hex[:12]

    try:
        docker_version = _run(["docker", "version"], check=False)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    if docker_version.returncode != 0:
        pytest.skip("Docker no esta disponible para levantar Neo4j efimero")

    cmd = [
        "docker",
        "run",
        "--rm",
        "--detach",
        "--name",
        name,
        "--publish",
        f"127.0.0.1:{port}:7687",
        "--env",
        f"NEO4J_AUTH=neo4j/{password}",
        "--env",
        "NEO4J_server_memory_heap_initial__size=128m",
        "--env",
        "NEO4J_server_memory_heap_max__size=256m",
        image,
    ]
    started = _run(cmd, check=False)
    if started.returncode != 0:
        pytest.skip(f"no se pudo arrancar Neo4j efimero: {started.stderr.strip()}")

    uri = f"bolt://127.0.0.1:{port}"
    driver = neo4j.GraphDatabase.driver(uri, auth=("neo4j", password))
    deadline = time.monotonic() + 180
    try:
        while True:
            try:
                driver.verify_connectivity()
                break
            except Exception as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Neo4j no acepto conexiones en {uri}: {exc}") from exc
                time.sleep(1)
        bootstrap_writer_schema(driver)
        yield driver
    finally:
        driver.close()
        _run(["docker", "rm", "-f", name], check=False)


@pytest.fixture(scope="session")
def neo4j_driver():
    with neo4j_efimero() as driver:
        yield driver


@dataclass
class GraphProbe:
    driver: Any

    def run(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        with self.driver.session() as session:
            return [record.data() for record in session.run(cypher, params or {})]

    def clean(self) -> None:
        self.run("MATCH (n) DETACH DELETE n")

    def counts(self) -> dict[str, int]:
        nodes = self.run("MATCH (n) RETURN count(n) AS c")[0]["c"]
        rels = self.run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
        return {"nodes": nodes, "relationships": rels}

    def knowledge_counts(self) -> dict[str, int]:
        nodes = self.run(
            "MATCH (n) WHERE n:V3Entity OR n:V3Assertion RETURN count(n) AS c"
        )[0]["c"]
        rels = self.run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
        return {"nodes": nodes, "relationships": rels}

    def applied_operations(self) -> list[dict]:
        return self.run(
            "MATCH (op:V3AppliedOperation) "
            "RETURN op.workspace AS workspace, "
            "op.idempotency_key AS idempotency_key, "
            "op.plan_hash AS plan_hash, op.operation_id AS operation_id "
            "ORDER BY workspace, idempotency_key"
        )

    def snapshot_bytes(self) -> str:
        nodes = self.run(
            "MATCH (n) "
            "RETURN labels(n) AS labels, properties(n) AS props "
            "ORDER BY labels(n), properties(n)"
        )
        rels = self.run(
            "MATCH (a)-[r]->(b) "
            "RETURN type(r) AS type, properties(r) AS props, "
            "properties(a) AS start, properties(b) AS end "
            "ORDER BY type(r), properties(r), properties(a), properties(b)"
        )
        return json.dumps({"nodes": nodes, "relationships": rels}, sort_keys=True)

    def seed_entity(
        self,
        entity_id: str,
        *,
        workspace: str = WORKSPACE,
        version: int = 1,
        state_hash: str = HASH_A["value"],
        name: str | None = None,
    ) -> None:
        self.run(
            "CREATE (:V3Entity:Character $props)",
            {
                "props": {
                    "entity_id": entity_id,
                    "workspace": workspace,
                    "version": version,
                    "state_hash": state_hash,
                    "canonical_name": name or entity_id,
                }
            },
        )

    def seed_assertion(
        self,
        assertion_id: str,
        *,
        workspace: str = WORKSPACE,
        version: int = 1,
        state_hash: str = HASH_B["value"],
        status: str = "ASSERTED",
    ) -> None:
        self.run(
            "CREATE (:V3Assertion $props)",
            {
                "props": {
                    "assertion_id": assertion_id,
                    "workspace": workspace,
                    "version": version,
                    "state_hash": state_hash,
                    "status": status,
                    "predicate": "MEMBER_OF",
                }
            },
        )

    def node(self, label: str, key: str, value: str, *, workspace: str = WORKSPACE) -> dict | None:
        rows = self.run(
            f"MATCH (n:{label} {{{key}: $value, workspace: $ws}}) RETURN properties(n) AS props",
            {"value": value, "ws": workspace},
        )
        return rows[0]["props"] if rows else None


@pytest.fixture()
def graph(neo4j_driver):
    probe = GraphProbe(neo4j_driver)
    probe.clean()
    yield probe
    probe.clean()


def decision(decision_id: str, subject: str = "entity:a", obj: str = "entity:b") -> dict:
    return {
        "decision_id": decision_id,
        "claim_id": f"claim:{decision_id}",
        "decision": "ACCEPT",
        "predicate": "MEMBER_OF",
        "direction": "SUBJECT_TO_OBJECT",
        "subject_entity_id": subject,
        "object_entity_id": obj,
        "epistemic_status": "ASSERTED",
        "negated": False,
        "confidence": 0.81,
        "reason_codes": ["LOCAL_APPROVED"],
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
    }


def op(
    op_id: str,
    op_type: str,
    decision_id: str,
    *,
    target: str | None = None,
    assertion: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_state: str,
    expected_version: int | None,
    expected_hash: dict | None,
) -> dict:
    return {
        "operation_id": op_id,
        "operation_type": op_type,
        "decision_id": decision_id,
        "target_entity_id": target,
        "assertion_id": assertion,
        "payload": payload or {},
        "evidence_fragment_ids": [f"fragment:{decision_id}"],
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": expected_state,
        "expected_version": expected_version,
        "expected_hash": expected_hash,
    }


def create_entity(op_id: str, entity_id: str, name: str, decision_id: str = "decision:1") -> dict:
    return op(
        op_id,
        "CREATE_ENTITY",
        decision_id,
        target=entity_id,
        payload={"entity_type": "Character", "canonical_name": name},
        expected_state="WOULD_CREATE",
        expected_version=None,
        expected_hash=None,
    )


def create_assertion(
    op_id: str,
    assertion_id: str,
    subject: str,
    obj: str,
    decision_id: str = "decision:1",
    *,
    predicate: str = "MEMBER_OF",
    negated: bool = False,
) -> dict:
    return op(
        op_id,
        "CREATE_ASSERTION",
        decision_id,
        assertion=assertion_id,
        payload={
            "subject_entity_id": subject,
            "object_entity_id": obj,
            "predicate": predicate,
            "negated": negated,
            "status": "ASSERTED",
        },
        expected_state="WOULD_CREATE",
        expected_version=None,
        expected_hash=None,
    )


def link_existing(
    op_id: str,
    subject: str,
    obj: str,
    *,
    decision_id: str = "decision:1",
    version: int = 1,
    state_hash: dict = HASH_A,
) -> dict:
    return op(
        op_id,
        "LINK_EXISTING",
        decision_id,
        target=subject,
        payload={"subject_entity_id": subject, "object_entity_id": obj, "predicate": "MEMBER_OF"},
        expected_state="WOULD_LINK_EXISTING",
        expected_version=version,
        expected_hash=state_hash,
    )


def update_entity(
    op_id: str,
    entity_id: str,
    *,
    decision_id: str = "decision:1",
    version: int = 1,
    state_hash: dict = HASH_A,
) -> dict:
    return op(
        op_id,
        "UPDATE_ENTITY",
        decision_id,
        target=entity_id,
        payload={
            "status": "SUPERSEDED",
            "valid_to": "2026-07-27T00:00:00Z",
            "reason_code": "COPYRIGHT_TAKEDOWN",
        },
        expected_state="WOULD_UPDATE",
        expected_version=version,
        expected_hash=state_hash,
    )


def supersede_assertion(
    op_id: str,
    assertion_id: str,
    *,
    successor: str | None = None,
    decision_id: str = "decision:1",
    version: int = 1,
    state_hash: dict = HASH_B,
) -> dict:
    payload = {
        "status": "SUPERSEDED",
        "valid_to": "2026-07-27T00:00:00Z",
        "reason_code": "COPYRIGHT_TAKEDOWN",
    }
    if successor:
        payload["superseded_by"] = successor
    return op(
        op_id,
        "SUPERSEDE_ASSERTION",
        decision_id,
        assertion=assertion_id,
        payload=payload,
        expected_state="WOULD_SUPERSEDE",
        expected_version=version,
        expected_hash=state_hash,
    )


def make_plan(
    operations: list[dict],
    *,
    workspace: str = WORKSPACE,
    decisions: list[dict] | None = None,
    plan_id: str | None = None,
    partida_id: str | None = None,
    scope: dict | None = None,
) -> dict:
    if decisions is None:
        decisions = [
            decision(decision_id)
            for decision_id in sorted({operation["decision_id"] for operation in operations})
        ]
    doc = {
        "contract_id": "graph-mutation-plan/v3-internal-v1",
        "contract_version": "1.0.0",
        "workspace": workspace,
        "source_asset_id": "asset:writer-real",
        "source_hash": {"algorithm": "sha256", "value": "d" * 64},
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
        "plan_id": plan_id or ("plan:writer-real:" + uuid.uuid4().hex[:8]),
        "plan_hash": {"algorithm": "sha256", "value": "0" * 64},
        "snapshot_id": SNAPSHOT,
        "engine_version": "3.0.0",
        "ontology_version": "core-1.4.0",
        "game_profile": "generic",
        "collection_id": "collection:writer-real",
        "created_at": "2026-07-27T10:30:00Z",
        "expires_at": "2026-07-27T12:30:00Z",
        "decisions": decisions,
        "mutation_operations": operations,
        "local_approval": {
            "approved": True,
            "decision_hash": {"algorithm": "sha256", "value": "0" * 64},
            "validator_chain": [
                {"validator": "structural", "version": "3.0.0", "result": "PASS"},
                {"validator": "semantic", "version": "3.0.0", "result": "PASS"},
            ],
            "created_at": "2026-07-27T10:30:00Z",
            "approved_by": {"provider": "local", "name": "s9k.engine.local", "version": "3.0.0"},
        },
    }
    if partida_id is not None:
        doc["partida_id"] = partida_id
    if scope is not None:
        doc["scope"] = scope
    return seal_plan(doc)


def apply_request(plan: dict, **over: Any) -> OperatorRequest:
    base = {
        "apply": True,
        "operator_id": "writer-real",
        "workspace": WORKSPACE,
        "expected_plan_hash": plan["plan_hash"]["value"],
        "max_operations": 50,
        "current_snapshot_id": SNAPSHOT,
        "env": {"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WORKSPACE},
    }
    base.update(over)
    return OperatorRequest(**base)


def dry_request(**over: Any) -> OperatorRequest:
    base = {
        "apply": False,
        "operator_id": "writer-real",
        "workspace": WORKSPACE,
        "current_snapshot_id": SNAPSHOT,
        "env": {},
    }
    base.update(over)
    return OperatorRequest(**base)


def writer(driver: Any, keys: InMemoryAppliedKeys | None = None, *, workspace: str = WORKSPACE) -> GraphWriter:
    return GraphWriter(
        workspace=workspace,
        driver=driver,
        audit=InMemoryAuditSink(),
        applied_keys=keys or InMemoryAppliedKeys(),
        clock=_clock,
    )


def test_cypher_valido_para_todas_las_operaciones_soportadas(graph: GraphProbe):
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_C["value"])
    graph.seed_assertion("assertion:vieja", version=1, state_hash=HASH_B["value"])

    ops = [
        create_entity("op:0001", "entity:nueva", "Nueva"),
        create_assertion("op:0002", "assertion:nueva", "entity:origen", "entity:destino"),
        link_existing("op:0003", "entity:origen", "entity:destino"),
        update_entity("op:0004", "entity:origen"),
        supersede_assertion("op:0005", "assertion:vieja", successor="assertion:nueva"),
    ]
    plan = make_plan(ops)

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_APPLIED, result.codes
    assert graph.knowledge_counts() == {"nodes": 5, "relationships": 1}
    assert len(graph.applied_operations()) == len(ops)
    assert graph.node("V3Entity", "entity_id", "entity:origen")["version"] == 2
    assert graph.node("V3Assertion", "assertion_id", "assertion:vieja")["status"] == "SUPERSEDED"


def test_create_only_no_sobrescribe_nodo_existente(graph: GraphProbe):
    graph.seed_entity("entity:duplicada", name="Nombre original")
    before = graph.snapshot_bytes()
    plan = make_plan([create_entity("op:0001", "entity:duplicada", "Nombre cambiado")])

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_TARGET_ALREADY_EXISTS in result.codes
    assert graph.snapshot_bytes() == before
    assert graph.node("V3Entity", "entity_id", "entity:duplicada")["canonical_name"] == "Nombre original"


def test_concurrencia_optimista_real_aborta_el_plan_entero(graph: GraphProbe):
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_C["value"])
    plan = make_plan(
        [
            create_entity("op:0001", "entity:primera-escritura", "Temporal"),
            link_existing("op:0002", "entity:origen", "entity:destino", version=1, state_hash=HASH_A),
        ]
    )
    graph.run(
        "MATCH (n:V3Entity {entity_id: $id, workspace: $ws}) "
        "SET n.version = 2, n.state_hash = $hash",
        {"id": "entity:origen", "ws": WORKSPACE, "hash": HASH_B["value"]},
    )

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_VERSION_MISMATCH in result.codes
    assert graph.node("V3Entity", "entity_id", "entity:primera-escritura") is None
    assert graph.counts() == {"nodes": 2, "relationships": 0}


def test_transaccion_real_revierte_escrituras_previas_si_falla_operacion_n(graph: GraphProbe):
    plan = make_plan(
        [
            create_entity("op:0001", "entity:misma", "Primera"),
            create_entity("op:0002", "entity:misma", "Segunda"),
        ]
    )

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_TARGET_ALREADY_EXISTS in result.codes
    assert graph.counts() == {"nodes": 0, "relationships": 0}


def test_idempotencia_real_segunda_aplicacion_no_cambia_el_grafo(graph: GraphProbe):
    plan = make_plan([create_entity("op:0001", "entity:idempotente", "Idempotente")])
    keys = InMemoryAppliedKeys()
    sut = writer(graph.driver, keys)

    first = sut.write(plan, apply_request(plan))
    before_second = graph.snapshot_bytes()
    second = sut.write(plan, apply_request(plan))

    assert first.outcome == OUTCOME_APPLIED
    assert second.outcome == OUTCOME_APPLIED
    assert second.noop_operations == 1
    assert graph.snapshot_bytes() == before_second
    assert graph.knowledge_counts() == {"nodes": 1, "relationships": 0}
    assert len(graph.applied_operations()) == 1


def test_cierre_de_vigencia_conserva_historia_y_crea_sucesor(graph: GraphProbe):
    graph.seed_assertion("assertion:vieja", version=1, state_hash=HASH_B["value"], status="ASSERTED")
    plan = make_plan(
        [
            supersede_assertion("op:0001", "assertion:vieja", successor="assertion:nueva"),
            create_assertion("op:0002", "assertion:nueva", "entity:origen", "entity:destino"),
        ]
    )

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_APPLIED, result.codes
    old = graph.node("V3Assertion", "assertion_id", "assertion:vieja")
    new = graph.node("V3Assertion", "assertion_id", "assertion:nueva")
    assert old["status"] == "SUPERSEDED"
    assert old["superseded_by"] == "assertion:nueva"
    assert old["version"] == 2
    assert new["status"] == "ASSERTED"
    assert graph.knowledge_counts() == {"nodes": 2, "relationships": 0}
    assert len(graph.applied_operations()) == 2


def test_dry_run_con_driver_real_no_toca_ni_un_byte(graph: GraphProbe):
    graph.seed_entity("entity:intacta", name="Intacta")
    before = graph.snapshot_bytes()
    plan = make_plan([create_entity("op:0001", "entity:dry-run", "Dry Run")])

    result = writer(graph.driver).write(plan, dry_request())

    assert result.outcome == OUTCOME_SIMULATED
    assert graph.snapshot_bytes() == before


@pytest.mark.parametrize(
    "request_overrides,expected_code",
    [
        ({"env": {"S9K_WRITER_WORKSPACE": WORKSPACE}}, codes.GATE_ENV_NOT_ALLOWED),
        ({"expected_plan_hash": "f" * 64}, codes.GATE_PLAN_HASH_NOT_CONFIRMED),
        (
            {
                "workspace": OTHER_WORKSPACE,
                "env": {"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": OTHER_WORKSPACE},
            },
            codes.GATE_WORKSPACE_DECLARATION_MISMATCH,
        ),
    ],
)
def test_gate_bloquea_con_base_real_disponible_y_no_escribe(
    graph: GraphProbe,
    request_overrides: dict,
    expected_code: str,
):
    before = graph.snapshot_bytes()
    plan = make_plan([create_entity("op:0001", "entity:bloqueada", "Bloqueada")])

    result = writer(graph.driver).write(plan, apply_request(plan, **request_overrides))

    assert result.outcome == OUTCOME_BLOCKED
    assert expected_code in result.codes
    assert graph.snapshot_bytes() == before


def test_aislamiento_workspace_no_toca_nodos_de_otro_workspace(graph: GraphProbe):
    graph.seed_entity(
        "entity:ajena",
        workspace=OTHER_WORKSPACE,
        version=1,
        state_hash=HASH_A["value"],
        name="Ajena",
    )
    graph.seed_entity(
        "entity:destino",
        workspace=OTHER_WORKSPACE,
        version=1,
        state_hash=HASH_C["value"],
        name="Destino ajeno",
    )
    before_other = graph.snapshot_bytes()
    plan = make_plan([link_existing("op:0001", "entity:ajena", "entity:destino")])

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_TARGET_MISSING in result.codes
    assert graph.snapshot_bytes() == before_other
    assert graph.counts() == {"nodes": 2, "relationships": 0}


# ==========================================================================
# Autoridad transaccional de idempotencia (ID-01 .. ID-08)
# ==========================================================================
def test_restriccion_compuesta_de_operacion_aplicada_existe(neo4j_driver):
    rows = GraphProbe(neo4j_driver).run(
        "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
        "WHERE name = $name "
        "RETURN name, type, labelsOrTypes, properties",
        {"name": APPLIED_OPERATION_CONSTRAINT},
    )

    assert rows == [
        {
            "name": APPLIED_OPERATION_CONSTRAINT,
            "type": "UNIQUENESS",
            "labelsOrTypes": ["V3AppliedOperation"],
            "properties": ["workspace", "idempotency_key"],
        }
    ]


def test_id_01_y_02_primera_aplicacion_y_repeticion_exacta(graph: GraphProbe):
    plan = make_plan([create_entity("op:id-01", "entity:id-01", "ID-01")])

    first = writer(graph.driver).write(plan, apply_request(plan))
    second = writer(graph.driver).write(plan, apply_request(plan))

    assert first.outcome == OUTCOME_APPLIED and first.applied_operations == 1
    assert second.outcome == OUTCOME_APPLIED and second.noop_operations == 1
    assert graph.knowledge_counts() == {"nodes": 1, "relationships": 0}
    assert len(graph.applied_operations()) == 1


def test_id_03_misma_clave_con_plan_incompatible_falla_cerrado(graph: GraphProbe):
    plan_a = make_plan(
        [create_entity("op:id-03", "entity:id-03", "ID-03")],
        plan_id="plan:id-03:a",
    )
    plan_b = dict(plan_a)
    plan_b["created_at"] = "2026-07-27T10:31:00Z"
    plan_b["plan_id"] = "plan:id-03:b"
    plan_b = seal_plan(plan_b)
    assert (
        plan_a["mutation_operations"][0]["idempotency_key"]
        == plan_b["mutation_operations"][0]["idempotency_key"]
    )

    first = writer(graph.driver).write(plan_a, apply_request(plan_a))
    original_mark = graph.applied_operations()
    second = writer(graph.driver).write(plan_b, apply_request(plan_b))

    assert first.outcome == OUTCOME_APPLIED
    assert second.outcome == OUTCOME_ABORTED
    assert codes.EXEC_IDEMPOTENCY_CONFLICT in second.codes
    assert graph.knowledge_counts() == {"nodes": 1, "relationships": 0}
    assert graph.applied_operations() == original_mark


def test_id_04_fallo_antes_de_mutacion_no_deja_marca(graph: GraphProbe):
    graph.seed_entity("entity:id-04", name="Ya existe")
    plan = make_plan([create_entity("op:id-04", "entity:id-04", "Duplicada")])

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_TARGET_ALREADY_EXISTS in result.codes
    assert graph.applied_operations() == []


def test_id_05_fallo_durante_mutacion_revierte_marca_y_escritura(graph: GraphProbe):
    plan = make_plan(
        [
            create_entity("op:id-05-a", "entity:id-05", "Primera"),
            create_entity("op:id-05-b", "entity:id-05", "Segunda"),
        ]
    )

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_ABORTED
    assert graph.knowledge_counts() == {"nodes": 0, "relationships": 0}
    assert graph.applied_operations() == []


class _FailingAppliedKeys(InMemoryAppliedKeys):
    def record(self, key: str, metadata: dict[str, Any]) -> None:
        raise RuntimeError("caida simulada tras commit")


def test_id_06_caida_tras_commit_y_cache_vacia_sigue_siendo_idempotente(
    graph: GraphProbe,
):
    plan = make_plan([create_entity("op:id-06", "entity:id-06", "ID-06")])
    first = writer(graph.driver, _FailingAppliedKeys()).write(plan, apply_request(plan))

    restarted = writer(graph.driver, InMemoryAppliedKeys())
    second = restarted.write(plan, apply_request(plan))

    assert first.outcome == OUTCOME_APPLIED
    assert second.outcome == OUTCOME_APPLIED and second.noop_operations == 1
    assert graph.knowledge_counts() == {"nodes": 1, "relationships": 0}
    assert len(graph.applied_operations()) == 1


def test_id_07_concurrencia_real_crea_una_marca_y_una_mutacion(graph: GraphProbe):
    plan = make_plan([create_entity("op:id-07", "entity:id-07", "ID-07")])
    barrier = threading.Barrier(2)

    def apply_once():
        barrier.wait(timeout=10)
        return writer(graph.driver).write(plan, apply_request(plan))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: apply_once(), range(2)))

    assert all(result.outcome == OUTCOME_APPLIED for result in results)
    assert sorted(result.applied_operations for result in results) == [0, 1]
    assert sorted(result.noop_operations for result in results) == [0, 1]
    assert graph.knowledge_counts() == {"nodes": 1, "relationships": 0}
    assert len(graph.applied_operations()) == 1


def test_id_08_misma_clave_aislada_por_workspace(graph: GraphProbe):
    operation_a = create_entity("op:id-08", "entity:id-08", "ID-08")
    operation_b = create_entity("op:id-08", "entity:id-08", "ID-08")
    plan_a = make_plan([operation_a], workspace=WORKSPACE, plan_id="plan:id-08:a")
    plan_b = make_plan([operation_b], workspace=OTHER_WORKSPACE, plan_id="plan:id-08:b")
    key_a = plan_a["mutation_operations"][0]["idempotency_key"]
    key_b = plan_b["mutation_operations"][0]["idempotency_key"]
    assert key_a != key_b

    first = writer(graph.driver, workspace=WORKSPACE).write(plan_a, apply_request(plan_a))
    second = writer(graph.driver, workspace=OTHER_WORKSPACE).write(
        plan_b,
        apply_request(
            plan_b,
            workspace=OTHER_WORKSPACE,
            env={
                "S9K_ALLOW_REAL_INGEST": "1",
                "S9K_WRITER_WORKSPACE": OTHER_WORKSPACE,
            },
        ),
    )

    assert first.outcome == second.outcome == OUTCOME_APPLIED
    assert len(graph.applied_operations()) == 2
    assert {
        (row["workspace"], row["idempotency_key"])
        for row in graph.applied_operations()
    } == {(WORKSPACE, key_a), (OTHER_WORKSPACE, key_b)}


def test_gate_global_no_hay_parejas_de_idempotencia_duplicadas(graph: GraphProbe):
    plan = make_plan([create_entity("op:gate", "entity:gate", "Gate")])
    writer(graph.driver).write(plan, apply_request(plan))
    writer(graph.driver).write(plan, apply_request(plan))

    duplicates = graph.run(
        "MATCH (op:V3AppliedOperation) "
        "WITH op.workspace AS workspace, op.idempotency_key AS idempotency_key, "
        "count(*) AS total "
        "WHERE total > 1 "
        "RETURN workspace, idempotency_key, total"
    )
    mutations_without_mark = graph.run(
        "MATCH (n) "
        "WHERE (n:V3Entity OR n:V3Assertion) AND n.idempotency_key IS NOT NULL "
        "AND NOT EXISTS { "
        "  MATCH (op:V3AppliedOperation {workspace: n.workspace, "
        "                              idempotency_key: n.idempotency_key}) "
        "} "
        "RETURN properties(n) AS mutation"
    )

    assert duplicates == []
    assert mutations_without_mark == []


# ==========================================================================
# M3 (docs/v3/49 SS2.4/SS11): ambito de partida contra un Neo4j real
# ==========================================================================
def test_m3_create_entity_de_capa_juego_no_escribe_la_propiedad_partida_id(graph: GraphProbe):
    """Pendiente senalada por el revisor de M3: verificar contra un Neo4j
    REAL, no solo contra el driver mockeado, que un CREATE con
    `partida_id=None` deja el nodo BYTE-IDENTICO a como quedaba antes de
    M3 -- sin la propiedad presente en absoluto (Neo4j omite claves `null`
    en un `CREATE (n $props)`), no con un `null` explicito.

    Gated por Docker (`S9K_WRITER_NEO4J_REAL=1`): en el resto de la suite
    queda `skipped`, y se activa sola en cuanto haya un Neo4j real
    disponible (p. ej. el despliegue V3 en VM105), sin depender de que
    nadie se acuerde de anadirla a mano en ese momento.
    """
    plan = make_plan([create_entity("op:m3-game-layer", "entity:m3-game", "Capa juego")])

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_APPLIED, result.codes
    props = graph.node("V3Entity", "entity_id", "entity:m3-game")
    assert props is not None
    # La propiedad no esta presente EN ABSOLUTO -- ni como None/null, ni con
    # ningun otro valor. `dict.get` devolveria None tanto si faltase como si
    # valiese null; `in` es la unica forma de distinguir "ausente" de "nulo".
    assert "partida_id" not in props


def test_m3_create_entity_de_partida_estampa_partida_id_real(graph: GraphProbe):
    """Gemelo en positivo del anterior: una partida SI deja la propiedad,
    con el valor exacto declarado por `scope.partida_id`."""
    plan = make_plan(
        [create_entity("op:m3-partida", "entity:m3-partida", "De partida")],
        partida_id="partida:brumal-01",
        scope={"layer": "PARTIDA", "game_id": WORKSPACE, "partida_id": "partida:brumal-01"},
    )

    result = writer(graph.driver).write(plan, apply_request(plan))

    assert result.outcome == OUTCOME_APPLIED, result.codes
    props = graph.node("V3Entity", "entity_id", "entity:m3-partida")
    assert props is not None
    assert props["partida_id"] == "partida:brumal-01"


# ==========================================================================
# Rollback con identidad durable (TANDA 2 / EQUIPO 2)
# ==========================================================================
def test_el_rollback_de_relacion_sobrevive_al_cambio_de_element_id(graph: GraphProbe):
    """El `elementId` se regenera al restaurar; la instruccion tiene que aguantar.

    Se aplica un plan en la base de sesion, se vuelca el grafo por sus
    PROPIEDADES (nunca por `elementId`) y se resiembra en OTRA base efimera:
    el `elementId` lleva el UUID de la base, asi que ahi es donde de verdad
    cambia -- dentro de la misma base los identificadores se reutilizan y la
    comparacion no mediria nada. El documento de rollback guardado antes tiene
    que seguir localizando la relacion correcta y no tocar a su vecina.
    """
    from knowledge_v3.writer.rollback import RollbackInstruction, rollback_query

    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_B["value"])
    plan = make_plan([link_existing("op:0001", "entity:origen", "entity:destino")])

    result = writer(graph.driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes
    doc = result.rollback.to_dict()
    instruccion = next(
        i for i in doc["instructions"] if i["action"] == "DELETE_RELATIONSHIP"
    )

    # Vecina: mismos extremos y mismo predicado, otra operacion. Es la que el
    # rollback NO puede tocar.
    vecina = "idem:sha256:" + "f" * 64
    graph.run(
        "MATCH (a:V3Entity {entity_id:'entity:origen', workspace:$ws}) "
        "MATCH (b:V3Entity {entity_id:'entity:destino', workspace:$ws}) "
        "CREATE (a)-[:MEMBER_OF {workspace:$ws, idempotency_key:$k}]->(b)",
        {"ws": WORKSPACE, "k": vecina},
    )
    viejos = {f["eid"] for f in graph.run("MATCH ()-[r]->() RETURN elementId(r) AS eid")}
    assert len(viejos) == 2, "el conjunto medido no puede estar vacio"
    assert instruccion["detail"]["element_id_at_write"] in viejos

    nodos = graph.run("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props")
    rels = graph.run(
        "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, properties(r) AS props, "
        "a.entity_id AS desde, b.entity_id AS hasta"
    )

    with neo4j_efimero("s9k-v3-writer-restore") as otro:
        destino = GraphProbe(otro)
        destino.clean()
        for nodo in nodos:
            destino.run(
                "CREATE (n:%s) SET n = $props" % ":".join(nodo["labels"]),
                {"props": nodo["props"]},
            )
        for rel in rels:
            destino.run(
                "MATCH (a {entity_id: $desde}) MATCH (b {entity_id: $hasta}) "
                "CREATE (a)-[r:%s]->(b) SET r = $props" % rel["tipo"],
                {"desde": rel["desde"], "hasta": rel["hasta"], "props": rel["props"]},
            )
        nuevos = {
            f["eid"] for f in destino.run("MATCH ()-[r]->() RETURN elementId(r) AS eid")
        }
        assert len(nuevos) == 2 and not (nuevos & viejos), \
            "los elementId no cambiaron: la prueba no mediria nada"
        assert destino.run(
            "MATCH ()-[r]->() WHERE elementId(r) = $eid RETURN count(*) AS c",
            {"eid": instruccion["detail"]["element_id_at_write"]},
        )[0]["c"] == 0

        query = rollback_query(
            RollbackInstruction(
                operation_id=instruccion["operation_id"],
                action=instruccion["action"],
                target_id=instruccion["target_id"],
                detail=instruccion["detail"],
            )
        )
        assert "elementId" not in query.cypher
        borradas = destino.run(query.cypher, query.params)
        assert borradas and borradas[0]["borradas"] == 1

        quedan = destino.run(
            "MATCH ()-[r]->() RETURN r.idempotency_key AS idem ORDER BY idem"
        )
        assert [f["idem"] for f in quedan] == [vecina], "borro de mas o de menos"
        assert destino.run("MATCH (n:V3Entity) RETURN count(n) AS c")[0]["c"] == 2
