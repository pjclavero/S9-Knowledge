# -*- coding: utf-8 -*-
"""Sonda ejecutada en procesos nuevos para verificar PYTHONHASHSEED."""
from __future__ import annotations

import copy
import hashlib
import json

from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.contracts import parse_document
from knowledge_v3.extraction.base import ExtractionOutput
from knowledge_v3.reconcile import ProposalReconciler


def _document(base: dict, identifier: str, step: str, provider: str):
    doc = copy.deepcopy(base)
    doc["mention_id"] = identifier
    trace = [dict(item) for item in (doc.get("provider_trace") or [])]
    if trace:
        trace[0]["step"] = step
        trace[0]["provider"] = provider
    doc["provider_trace"] = trace
    doc["produced_by_step"] = step
    return parse_document(doc)


def canonical_result() -> bytes:
    base = list(load_gold("dev").mentions)[:12]
    mentions = [
        _document(mention, f"{origin}-m-{index}", step, provider)
        for index, mention in enumerate(base)
        for origin, step, provider in (
            ("det", "extract.deterministic", "local"),
            ("sem", "extract.semantic", "ollama"),
        )
    ]
    output = ProposalReconciler().reconcile(ExtractionOutput(mentions=tuple(mentions)))
    payload = {
        "mentions": [m.to_dict() for m in output.mentions],
        "claims": [c.to_dict() for c in output.claims],
        "diagnostics": [d.to_dict() for d in output.diagnostics],
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


if __name__ == "__main__":
    print(hashlib.sha256(canonical_result()).hexdigest())
