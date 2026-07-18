"""make_fixtures.py — genera fixtures v1 sintéticas y ANONIMIZADAS.

Produce un documento de cada `document_type` del contrato review/ingest v1 con
datos totalmente sintéticos (nada de lore/PII/producción) y los VALIDA con el
`validator.py` del contrato antes de escribirlos en
`tests/fixtures/review_ingest_v1/`.

Ejecutar:  python3 tests/support/make_fixtures.py
Los tests de integración vuelven a validar estos ficheros como red de seguridad.
"""
from __future__ import annotations

import json
from pathlib import Path

# Import robusto tanto si se ejecuta como script como si se importa.
try:
    from support import contracts  # type: ignore
except ModuleNotFoundError:  # ejecución directa: añade tests/ al path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from support import contracts  # type: ignore

OUT_DIR = contracts.REPO_ROOT / "tests" / "fixtures" / "review_ingest_v1"

HASH_A = {"algorithm": "sha256", "value": "1" * 64}
HASH_B = {"algorithm": "sha256", "value": "2" * 64}
HASH_C = {"algorithm": "sha256", "value": "3" * 64}

PRODUCER = {"kind": "ENGINE", "name": "s9k-data-engine", "version": "0.0.0-test", "model": None}
PROVENANCE = {
    "source_id": "src_synthetic_01",
    "source_hash": HASH_A,
    "review_generation": 1,
    "pipeline_version": "0.0.0-test",
    "producer": PRODUCER,
}


def _envelope(document_type: str, document_id: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "document_type": document_type,
        "document_id": document_id,
        "created_at": "2026-01-01T00:00:00Z",
        "workspace": "workspace_demo",
        "source_id": "src_synthetic_01",
        "source_hash": HASH_A,
        "review_generation": 1,
        "producer": PRODUCER,
        "provenance": PROVENANCE,
    }


def candidate() -> dict:
    d = _envelope("review-candidate", "fixture-candidate_001")
    d.update({
        "candidate_id": "cand_synth_001",
        "segment_id": "seg_synth_001",
        "candidate_kind": "ENTITY",
        "entity_type": "Character",
        "canonical_name": "Persona Alfa",
        "display_name": "Persona Alfa",
        "aliases": ["Alfa"],
        "description": "Personaje sintético de laboratorio.",
        "attributes": {"faction": "Grupo Sintético"},
        "confidence": 0.75,
        "evidence": [
            {
                "evidence_id": "ev_synth_001",
                "quote": "Persona Alfa aparece en la escena de prueba.",
                "location": {"kind": "PAGE_RANGE", "page_start": 1, "page_end": 1},
            }
        ],
        "source_location": {"kind": "PAGE_RANGE", "page_start": 1, "page_end": 1},
        "existing_matches": [],
        "proposed_status": "REQUIRES_REVIEW",
        "policy_reasons": ["NEW_ENTITY"],
        "requires_review": True,
        "created_by": PRODUCER,
    })
    return d


def decision_human() -> dict:
    d = _envelope("review-decision", "fixture-decision_001")
    d.update({
        "decision_id": "dec_synth_001",
        "candidate_id": "cand_synth_001",
        "action": "APPROVE",
        "reviewer_type": "HUMAN",
        "reviewer_id": "operador_demo",
        "decided_at": "2026-01-01T00:05:00Z",
        "reason_code": "HUMAN_CONFIRMED",
        "comment": "confirmado en laboratorio",
        "expected_candidate_hash": HASH_A,
        "decision_hash": HASH_B,
    })
    return d


def decision_shadow_defer() -> dict:
    d = _envelope("review-decision", "fixture-decision_shadow_001")
    d.update({
        "decision_id": "dec_synth_shadow_001",
        "candidate_id": "cand_synth_001",
        "action": "DEFER",
        "reviewer_type": "EXTERNAL_AI_SHADOW",
        "reviewer_id": "shadow-demo",
        "decided_at": "2026-01-01T00:06:00Z",
        "reason_code": "SHADOW_RECOMMENDATION",
        "expected_candidate_hash": HASH_A,
        "decision_hash": HASH_C,
    })
    return d


def source_summary() -> dict:
    d = _envelope("review-source-summary", "fixture-summary_001")
    d.update({
        "source_kind": "TEXT",
        "source_document": "synthetic_01.md",
        "status": "READY",
        "segments_total": 3,
        "segments_reviewed": 3,
        "candidates_total": 3,
        "pending": 0,
        "auto_approvable": 0,
        "approved": 3,
        "edited": 0,
        "use_existing": 0,
        "deferred": 0,
        "conflicts": 0,
        "rejected": 0,
        "ready_to_plan": True,
        "blocking_reasons": [],
        "updated_at": "2026-01-01T00:09:00Z",
    })
    return d


def ingest_plan() -> dict:
    d = _envelope("ingest-plan", "fixture-plan_001")
    d.update({
        "plan_id": "plan_synth_001",
        "plan_version": "1.0.0",
        "review_document_id": "rev_synth_001",
        "review_hash": HASH_A,
        "created_by": PRODUCER,
        "status": "READY_TO_APPLY",
        "relations_enabled": False,
        "preconditions": [
            {"precondition_id": "pre_001", "kind": "REVIEW_HASH_MATCHES", "expected": HASH_A["value"]}
        ],
        "operations": [
            {
                "operation_id": "op_001",
                "operation_type": "CREATE_ENTITY",
                "candidate_id": "cand_synth_001",
                "target_entity_id": None,
                "payload": {"canonical_name": "Persona Alfa"},
                "provenance": PROVENANCE,
                "expected_state": "WOULD_CREATE",
                "idempotency_key": "idem_synth_001",
            }
        ],
        "deferred_items": [],
        "conflicts": [],
        "warnings": [],
        "summary": {
            "would_create": 1,
            "would_update": 0,
            "would_link_existing": 0,
            "deferred": 0,
            "conflicts": 0,
            "relations": 0,
        },
        "authorization": {"required": True, "granted": False},
    })
    return d


def dry_run_result() -> dict:
    d = _envelope("ingest-plan-result", "fixture-dryrun_001")
    d.update({
        "execution_id": "exec_synth_001",
        "plan_id": "plan_synth_001",
        "mode": "DRY_RUN",
        "started_at": "2026-01-01T00:10:00Z",
        "finished_at": "2026-01-01T00:10:01Z",
        "status": "SUCCEEDED",
        "operations": [
            {"operation_id": "op_001", "result": "WOULD_CREATE", "target_entity_id": None, "detail": "nuevo"}
        ],
        "summary": {
            "would_create": 1,
            "created": 0,
            "skipped": 0,
            "conflict": 0,
            "failed": 0,
            "rolled_back": 0,
        },
        "neo4j_before": {"nodes": 0, "relationships": 0},
        "neo4j_after": {"nodes": 0, "relationships": 0},
        "errors": [],
        "warnings": [],
    })
    return d


def audit_event() -> dict:
    d = _envelope("review-audit-event", "fixture-audit_001")
    d.update({
        "event_id": "evt_synth_001",
        "event_type": "DECISION_RECORDED",
        "actor_type": "HUMAN",
        "actor_id": "operador_demo",
        "timestamp": "2026-01-01T00:05:01Z",
        "candidate_id": "cand_synth_001",
        "plan_id": None,
        "request_id": "req_synth_001",
        "before_hash": HASH_A,
        "after_hash": HASH_B,
        "metadata": {"ui": "reviews"},
    })
    return d


FIXTURES = {
    "candidate_new.json": candidate,
    "decision_human_approve.json": decision_human,
    "decision_shadow_defer.json": decision_shadow_defer,
    "source_summary_ready.json": source_summary,
    "ingest_plan_ready.json": ingest_plan,
    "ingest_plan_result_dryrun.json": dry_run_result,
    "audit_event.json": audit_event,
}


def build() -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, factory in FIXTURES.items():
        doc = factory()
        contracts.validator.validate_document(doc)  # falla si no cumple el contrato
        path = OUT_DIR / name
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    paths = build()
    print(f"Generadas y validadas {len(paths)} fixtures anonimizadas en {OUT_DIR}:")
    for p in paths:
        print(f"  - {p.name}")
