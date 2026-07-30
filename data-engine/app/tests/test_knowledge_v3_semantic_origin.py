from __future__ import annotations

import copy

from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.contracts import parse_document
from knowledge_v3.engine.shadow import has_semantic_origin
from knowledge_v3.extraction.base import ExtractionOutput
from knowledge_v3.reconcile import ProposalReconciler


def _as_origin(document: dict, *, claim_id: str, step: str, provider: str):
    value = copy.deepcopy(document)
    value["claim_id"] = claim_id
    value["produced_by_step"] = step
    value["provider_trace"][0]["step"] = step
    value["provider_trace"][0]["provider"] = provider
    value["provider_trace"][0]["name"] = (
        "s9k.extraction.semantic" if step == "extract.semantic" else "rules"
    )
    value["provider_trace"][0]["model"] = "qwen2.5:7b" if step == "extract.semantic" else None
    return parse_document(value)


def test_reconciled_deterministic_primary_retains_semantic_origin():
    base = next(claim for claim in load_gold("dev").claims if not claim.get("abstained"))
    deterministic = _as_origin(
        base, claim_id="a-deterministic", step="extract.deterministic", provider="local"
    )
    semantic = _as_origin(
        base, claim_id="z-semantic", step="extract.semantic", provider="ollama"
    )

    merged = ProposalReconciler().reconcile(
        ExtractionOutput(claims=(deterministic, semantic))
    ).claims[0]

    assert merged.produced_by_step == "extract.deterministic"
    assert has_semantic_origin(merged) is True
    origins = merged.metadata["reconciliation"]["origins"]
    assert {origin["step"] for origin in origins} == {
        "extract.deterministic",
        "extract.semantic",
    }


def test_exclusively_deterministic_claim_has_no_semantic_origin():
    base = next(claim for claim in load_gold("dev").claims if not claim.get("abstained"))
    deterministic = _as_origin(
        base, claim_id="only-deterministic",
        step="extract.deterministic", provider="local",
    )
    assert has_semantic_origin(deterministic) is False


def test_model_name_alone_never_implies_semantic_origin():
    base = next(claim for claim in load_gold("dev").claims if not claim.get("abstained"))
    deterministic = _as_origin(
        base, claim_id="model-is-not-family",
        step="extract.deterministic", provider="local",
    )
    deterministic.provider_trace[0]["model"] = "semantic-looking-model"
    assert has_semantic_origin(deterministic) is False

