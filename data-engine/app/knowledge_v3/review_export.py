"""Export immutable pipeline results for the decoupled V3 review viewer.

Direction is deliberately one way::

    PipelineResult -> immutable review package -> proposals/ -> viewer

The viewer never imports the engine and this module never imports the viewer.
Policy: REVIEW is always exported. ABSTAIN and REJECT_INVALID are exported to
the same package (and remain filterable) so that no engine outcome disappears
silently. ACCEPT is omitted because it is not a human-review claim.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .contracts.base import canonical_json, sha256_hash


EXPORTED_DECISIONS = frozenset({"REVIEW", "ABSTAIN", "REJECT_INVALID"})


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    for method in ("to_contract_dict", "to_dict"):
        fn = getattr(value, method, None)
        if fn:
            return fn()
    return dict(vars(value))


def _semantic_hash(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k not in {"proposal_id", "proposal_hash"}}
    result = sha256_hash(body)
    return result["value"] if isinstance(result, dict) else str(result)


def _lookup(items: list[Any], key: str, value: Any) -> dict[str, Any]:
    for item in items:
        raw = _dict(item)
        if raw.get(key) == value:
            return raw
    return {}


def _mention_and_resolution(
    mention_ids: Any,
    mentions: list[Any],
    resolutions: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the first claim mention using the real plural contracts."""
    mention_id = next(iter(mention_ids or []), None)
    mention = _lookup(mentions, "mention_id", mention_id)
    for resolution_value in resolutions:
        resolution = _dict(resolution_value)
        if mention_id is not None and mention_id in (resolution.get("mention_ids") or []):
            return mention, resolution
    return mention, {}


def _resolved_entity_id(resolution: dict[str, Any]) -> Any:
    return (
        resolution.get("selected_entity_id")
        or resolution.get("assigned_entity_id")
        or "not_available"
    )


def review_documents(result: Any, *, workspace: str) -> list[dict[str, Any]]:
    """Adapt a real PipelineResult without inventing absent data."""
    documents: list[dict[str, Any]] = []
    config = getattr(result, "config_declared", {}) or {}
    for run in getattr(result, "runs", ()):
        episodes = list(getattr(run, "episodes", ()))
        claims = list(getattr(run, "claims", ()))
        mentions = list(getattr(run, "mentions", ()))
        resolutions = list(getattr(run, "resolutions", ()))
        fragments = list(getattr(run, "fragments", ()))
        for decision_value in getattr(run, "decisions", ()):
            decision = _dict(decision_value)
            outcome = str(decision.get("decision") or "UNKNOWN")
            if outcome not in EXPORTED_DECISIONS:
                continue
            claim_id = decision.get("claim_id")
            claim = _lookup(claims, "claim_id", claim_id)
            episode_id = decision.get("episode_id") or claim.get("episode_id") or "not_available"
            episode = _lookup(episodes, "episode_id", episode_id)
            episode_text = episode.get("text") or episode.get("content") or ""
            fragment_id = next(iter(claim.get("evidence_fragment_ids") or []), None)
            fragment = _lookup(fragments, "fragment_id", fragment_id)
            start = fragment.get("start_offset", fragment.get("start", 0))
            end = fragment.get("end_offset", fragment.get("end", start))
            try:
                start, end = int(start), int(end)
            except (TypeError, ValueError):
                start = end = 0
            if not (0 <= start <= end <= len(episode_text)):
                start = end = 0
            subject_mention, subject_resolution = _mention_and_resolution(
                claim.get("subject_mentions"), mentions, resolutions
            )
            object_mention, object_resolution = _mention_and_resolution(
                claim.get("object_mentions"), mentions, resolutions
            )
            subject_entity = _resolved_entity_id(subject_resolution)
            object_entity = _resolved_entity_id(object_resolution)
            proposal = {
                "subject": (
                    subject_entity
                    if subject_entity != "not_available"
                    else subject_mention.get("surface") or "not_available"
                ),
                "predicate": decision.get("predicate") or claim.get("predicate") or "UNKNOWN",
                "object": (
                    object_entity
                    if object_entity != "not_available"
                    else object_mention.get("surface") or "not_available"
                ),
                "direction": decision.get("direction") or claim.get("direction") or "UNKNOWN",
                "negated": claim.get("negated", False),
                "negation_kind": claim.get("negation_kind") or "UNKNOWN",
                "scope": claim.get("scope") or "not_available",
                "epistemic_status": claim.get("epistemic_status") or "UNKNOWN",
                "temporal_status": claim.get("temporal_status") or "UNKNOWN",
            }
            trace = claim.get("provider_trace") or []
            document: dict[str, Any] = {
                "workspace": workspace,
                "source_id": getattr(run, "source_id", None) or "not_available",
                "episode_id": episode_id,
                "episode_text": episode_text,
                "evidence": {
                    "start": start,
                    "end": end,
                    "literal_text": episode_text[start:end],
                },
                "proposal": proposal,
                "engine_decision": {
                    "decision": outcome,
                    "reason_codes": decision.get("reason_codes") or [],
                    "confidence": decision.get("confidence"),
                    "effective_decision": decision.get("effective_decision") or outcome,
                    "shadow_decision": decision.get("shadow_decision"),
                },
                "resolution": {
                    "subject": subject_entity,
                    "object": object_entity,
                },
                "alternatives": {
                    "predicates": claim.get("predicate_alternatives") or [],
                    "directions": claim.get("direction_alternatives") or [],
                },
                "provenance": {
                    "extractors": sorted({str(x.get("step") or "not_available") for x in trace}),
                    "providers": sorted({str(x.get("provider") or "not_available") for x in trace}),
                    "models": sorted({str(x.get("model") or "not_available") for x in trace}),
                    "independent_families": sorted({
                        str(x.get("independent_family") or "not_available") for x in trace
                    }),
                },
                "ontology_version": config.get("ontology_version"),
                "engine_version": config.get("engine_version") or "knowledge-v3",
                "prompt_version": config.get("prompt_version"),
                "profile_version": config.get("profile_version") or config.get("profile_id"),
            }
            digest = _semantic_hash(document)
            document["proposal_id"] = f"review:{digest}"
            hashed = sha256_hash(document)
            document["proposal_hash"] = hashed["value"] if isinstance(hashed, dict) else str(hashed)
            documents.append(document)
    return sorted(documents, key=lambda x: (x["source_id"], x["episode_id"], x["proposal_id"]))


def export_review_package(result: Any, output_dir: Path, *, workspace: str) -> Path:
    """Atomically write one content-addressed immutable package; reruns dedup."""
    documents = review_documents(result, workspace=workspace)
    package_body = {"workspace": workspace, "items": documents}
    package_hash = sha256_hash(package_body)
    digest = package_hash["value"] if isinstance(package_hash, dict) else str(package_hash)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{workspace}--{digest}.json"
    if target.exists():
        return target
    fd, temporary = tempfile.mkstemp(prefix=".review-", suffix=".tmp", dir=output_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(package_body) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


__all__ = ["EXPORTED_DECISIONS", "export_review_package", "review_documents"]
