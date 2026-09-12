# -*- coding: utf-8 -*-
"""Sonda: QUE deja en el grafo un CREATE_ENTITY del writer.

Importa porque `PROJECT_RELATION` copia `expected_version`/`expected_hash` del
snapshot y el executor los contrasta con `n.version`/`n.state_hash` del nodo. Si
un alta recien aplicada no deja esos dos campos, ninguna relacion podra
proyectarse despues sobre ella. Esto se OBSERVA, no se presume.

    S9K_WRITER_NEO4J_REAL=1 python3 artifacts/carril-b/sonda_create_entity.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "data-engine" / "app"))
sys.path.insert(0, str(RAIZ / "data-engine" / "app" / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero  # noqa: E402

from knowledge_v3.contracts.base import seal_plan  # noqa: E402
from knowledge_v3.writer import GraphWriter, InMemoryAppliedKeys  # noqa: E402
from knowledge_v3.writer.gate import OperatorRequest  # noqa: E402

WS = "sonda"
CERO = {"algorithm": "sha256", "value": "0" * 64}


def plan_de_alta() -> dict:
    return seal_plan({
        "contract_id": "graph-mutation-plan/v3-internal-v1",
        "contract_version": "1.0.0",
        "workspace": WS,
        "source_asset_id": "asset:sonda",
        "source_hash": CERO,
        "provider_trace": [{
            "step": "sonda", "provider": "local", "name": "sonda",
            "version": "1", "produced": ["mutation_operations"],
        }],
        "produced_by_step": "sonda",
        "plan_id": "plan:sonda",
        "plan_hash": CERO,
        "snapshot_id": "snapshot:sonda",
        "engine_version": "engine-1.0.0",
        "ontology_version": "core-1.4.0",
        "game_profile": "generic",
        "collection_id": "collection:sonda",
        "created_at": "2026-09-06T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "decisions": [{
            "decision_id": "decision:sonda",
            "claim_id": "claim:sonda",
            "decision": "REVIEW",
            "confidence": 0.9,
            "reason_codes": ["REVIEW_ENTITY", "HUMAN_APPROVED_ENTITY_CREATION"],
            "evidence_fragment_ids": ["fragment:sonda"],
        }],
        "mutation_operations": [{
            "operation_id": "op:sonda",
            "operation_type": "CREATE_ENTITY",
            "decision_id": "decision:sonda",
            "target_entity_id": "entity:sonda",
            "payload": {"entity_type": "Character", "name": "Sonda"},
            "evidence_fragment_ids": ["fragment:sonda"],
            "idempotency_key": "",
            "expected_state": "WOULD_CREATE",
            "expected_version": None,
            "expected_hash": None,
        }],
        "local_approval": {
            "approved": True,
            "approved_by": {"provider": "local", "name": "engine", "version": "1"},
            "created_at": "2026-09-06T00:00:00Z",
            "decision_hash": CERO,
            "validator_chain": [
                {"validator": "structural", "version": "1", "result": "PASS"},
            ],
        },
    })


def main() -> int:
    plan = plan_de_alta()
    with neo4j_efimero("s9k-carril-b-sonda") as driver:
        writer = GraphWriter(workspace=WS, driver=driver,
                             applied_keys=InMemoryAppliedKeys())
        res = writer.write(plan, OperatorRequest(
            apply=True, operator_id="sonda", workspace=WS,
            expected_plan_hash=plan["plan_hash"]["value"],
            current_snapshot_id=plan["snapshot_id"],
            env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS},
        ))
        print("outcome:", res.outcome, "codes:", json.dumps(res.codes))
        for r in res.rejections:
            print("  ->", r.code, "|", r.message)
        with driver.session() as s:
            filas = [r.data() for r in s.run(
                "MATCH (n:V3Entity {workspace: $ws}) "
                "RETURN labels(n) AS labels, properties(n) AS props", {"ws": WS})]
        print(json.dumps(filas, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
