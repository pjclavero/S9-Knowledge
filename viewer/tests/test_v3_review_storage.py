from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from app.services.v3_review import (
    ReviewError,
    ReviewService,
    StaleReviewError,
    load_proposals,
)


def _proposal(
    proposal_id: str = "logical-1",
    *,
    workspace: str = "alpha",
    confidence: float = 0.4,
) -> dict:
    text = "A protege B."
    return {
        "proposal_id": proposal_id,
        "workspace": workspace,
        "source_id": "source-1",
        "episode_id": "episode-1",
        "episode_text": text,
        "evidence": {"start": 2, "end": 10, "literal_text": "protege "},
        "proposal": {"subject": "A", "predicate": "PROTECTS", "object": "B"},
        "engine_decision": {
            "decision": "REVIEW",
            "effective_decision": "REVIEW",
            "shadow_decision": "ACCEPT",
            "confidence": confidence,
        },
        "prompt_version": "prompt-v1",
    }


def _write_package(path: Path, proposals: list[dict]) -> None:
    path.write_text(json.dumps({"items": proposals}), encoding="utf-8")


def _record_worker(
    proposals: str,
    decisions: str,
    request_id: str,
    decision: str,
    output: multiprocessing.Queue,
) -> None:
    try:
        item = ReviewService(Path(proposals), Path(decisions)).queue(
            "alpha", include_decided=True
        ).items[0]
        record = ReviewService(Path(proposals), Path(decisions)).record(
            proposal_id=item["proposal_id"],
            workspace="alpha",
            reviewer="worker",
            human_decision=decision,
            request_id=request_id,
            expected_proposal_hash=item["proposal_hash"],
            correction={"subject_alias": "Ari"} if decision == "CORRECT" else {},
        )
        output.put(("ok", record["decision_id"]))
    except Exception as exc:  # pragma: no cover - asserted in parent
        output.put(("error", type(exc).__name__, str(exc)))


def test_identical_and_partially_overlapping_packages_are_deduplicated(tmp_path):
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    one, two = _proposal("one"), _proposal("two")
    _write_package(proposals / "a.json", [one, two])
    _write_package(proposals / "b.json", [one])

    loaded = load_proposals(proposals)

    assert [item["proposal_id"] for item in loaded] == ["one", "two"]
    duplicate = next(item for item in loaded if item["proposal_id"] == "one")
    assert duplicate["package_origins"] == ["a.json", "b.json"]


def test_same_logical_proposal_new_hash_has_one_active_version_and_stales(tmp_path):
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    _write_package(proposals / "a-old.json", [_proposal(confidence=0.4)])
    old = ReviewService(proposals, tmp_path / "decisions.jsonl").queue("alpha").items[0]
    _write_package(proposals / "z-new.json", [_proposal(confidence=0.8)])
    service = ReviewService(proposals, tmp_path / "decisions.jsonl")
    current = service.queue("alpha").items

    assert len(current) == 1
    assert current[0]["proposal_id"] == old["proposal_id"]
    assert current[0]["proposal_hash"] != old["proposal_hash"]
    with pytest.raises(StaleReviewError):
        service.record(
            proposal_id=old["proposal_id"],
            workspace="alpha",
            reviewer="mara",
            human_decision="APPROVE",
            request_id="stale-version",
            expected_proposal_hash=old["proposal_hash"],
        )


def test_same_local_id_in_two_workspaces_is_isolated(tmp_path):
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    _write_package(
        proposals / "both.json",
        [_proposal(workspace="alpha"), _proposal(workspace="beta")],
    )
    loaded = load_proposals(proposals)
    assert {(item["workspace"], item["proposal_id"]) for item in loaded} == {
        ("alpha", "logical-1"),
        ("beta", "logical-1"),
    }


def test_corrupt_package_fails_closed(tmp_path):
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    (proposals / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(ReviewError, match="corrupto"):
        load_proposals(proposals)


def test_same_request_id_is_multiprocess_idempotent(tmp_path):
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    _write_package(proposals / "queue.json", [_proposal()])
    decisions = tmp_path / "decisions.jsonl"
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    processes = [
        context.Process(
            target=_record_worker,
            args=(str(proposals), str(decisions), "same-request", "APPROVE", output),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    results = [output.get(timeout=5) for _ in processes]
    assert {result[0] for result in results} == {"ok"}, results
    assert len({result[1] for result in results}) == 1
    assert len(ReviewService(proposals, decisions).store.decisions()) == 1


def test_outbox_projection_survives_restart_without_duplicate(tmp_path):
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    _write_package(proposals / "queue.json", [_proposal()])
    decisions = tmp_path / "decisions.jsonl"
    service = ReviewService(proposals, decisions)
    item = service.queue("alpha").items[0]
    service.record(
        proposal_id=item["proposal_id"],
        workspace="alpha",
        reviewer="mara",
        human_decision="CORRECT",
        request_id="candidate-request",
        expected_proposal_hash=item["proposal_hash"],
        correction={"subject_alias": "Ari"},
    )

    restarted = ReviewService(proposals, decisions)
    restarted.store.project_outbox("alpha", "2026-07-30T00:00:00Z")
    restarted.store.project_outbox("alpha", "2026-07-30T00:00:01Z")
    candidates = restarted.glossary_candidates("alpha")

    assert len(candidates) == 1
    assert candidates[0]["status"] == "PROPOSED"
    assert candidates[0]["occurrence_count"] == 1
