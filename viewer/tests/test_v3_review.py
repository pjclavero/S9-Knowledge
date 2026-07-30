from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import v3_review as router_module
from app.services.v3_review import (
    HistoryIntegrityError,
    ReviewError,
    ReviewService,
    read_history,
    reason_label,
    StaleReviewError,
)


def proposal(
    proposal_id: str,
    *,
    workspace: str = "alpha",
    source_id: str = "source-1",
    decision: str = "REVIEW",
    reason_codes: list[str] | None = None,
) -> dict:
    episode = "Ariadna protege la ciudad de Bruma durante el invierno."
    literal = "protege la ciudad de Bruma"
    start = episode.index(literal)
    return {
        "proposal_id": proposal_id,
        "workspace": workspace,
        "source_id": source_id,
        "episode_id": f"episode-{proposal_id}",
        "episode_text": episode,
        "evidence": {
            "start": start,
            "end": start + len(literal),
            "literal_text": literal,
        },
        "proposal": {
            "subject": "Ariadna",
            "predicate": "PROTECTS",
            "object": "Bruma",
            "direction": "SUBJECT_TO_OBJECT",
            "negation": {"negated": False, "type": "NONE"},
            "scope": "durante el invierno",
        },
        "engine_decision": {
            "decision": decision,
            "reason_codes": reason_codes or ["AMBIGUOUS_PREDICATE"],
        },
        "alternatives": {
            "predicates": [
                {"value": "GUARDS", "confidence": 0.71, "extractor": "semantic-local"}
            ],
            "directions": [
                {
                    "value": "OBJECT_TO_SUBJECT",
                    "confidence": 0.33,
                    "extractor": "rule-local",
                }
            ],
        },
        "ontology": {
            "version": "bruma-ontology-v1",
            "allowed_predicates": ["PROTECTS", "GUARDS"],
        },
        "ontology_version": "bruma-ontology-v1",
        "engine_version": "knowledge-v3-test",
        "provider_trace": [{"name": "semantic-local"}],
        "metadata": {"reconciliation": {"support": []}},
    }


@pytest.fixture
def review_files(tmp_path: Path) -> tuple[Path, Path]:
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    documents = [
        proposal("p2", workspace="alpha", source_id="source-2"),
        proposal("p1", workspace="alpha", source_id="source-1"),
        proposal("foreign", workspace="beta", source_id="source-0"),
    ]
    (proposals_dir / "queue.json").write_text(
        json.dumps({"items": documents}, ensure_ascii=False),
        encoding="utf-8",
    )
    return proposals_dir, tmp_path / "decisions.jsonl"


def test_queue_is_workspace_scoped_and_stably_sorted(review_files):
    proposals_dir, decisions = review_files
    view = ReviewService(proposals_dir, decisions).queue("alpha")
    assert [item["proposal_id"] for item in view.items] == ["p1", "p2"]
    assert all(item["workspace"] == "alpha" for item in view.items)
    assert "foreign" not in json.dumps(view.items)


def test_source_and_engine_decision_filters_remain_workspace_scoped(review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    assert [item["proposal_id"] for item in service.queue("alpha", source_id="source-2").items] == ["p2"]
    assert service.queue("alpha", engine_decision="ABSTAIN").items == []


def test_each_request_appends_exactly_once_even_after_reload_retry(review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    first = service.record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="APPROVE",
        request_id="browser-request-1",
    )
    second = ReviewService(proposals_dir, decisions).record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="APPROVE",
        request_id="browser-request-1",
    )
    assert first == second
    assert len(decisions.read_text(encoding="utf-8").splitlines()) == 1
    assert len(read_history(decisions)) == 1


def test_request_id_cannot_be_replayed_for_another_workspace(review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    service.record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="APPROVE",
        request_id="one-use-token",
    )
    with pytest.raises(ReviewError, match="request_id reutilizado"):
        service.record(
            proposal_id="foreign",
            workspace="beta",
            reviewer="mara",
            human_decision="APPROVE",
            request_id="one-use-token",
        )
    assert len(read_history(decisions)) == 1


def test_correction_supersedes_without_deleting_previous_entry(review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    original = service.record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="APPROVE",
        request_id="approve-1",
    )
    corrected = service.record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="CORRECT",
        request_id="correct-1",
        correction={"predicate": "GUARDS"},
        supersedes_decision_id=original["decision_id"],
    )
    history = read_history(decisions)
    assert len(history) == 2
    assert history[0] == original
    assert history[1] == corrected
    assert corrected["supersedes_decision_id"] == original["decision_id"]


def test_tampered_append_only_history_is_detected(review_files):
    proposals_dir, decisions = review_files
    ReviewService(proposals_dir, decisions).record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="REJECT",
        request_id="reject-1",
    )
    record = json.loads(decisions.read_text(encoding="utf-8"))
    record["rationale"] = "texto alterado"
    decisions.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(HistoryIntegrityError, match="hash inválido"):
        read_history(decisions)


def test_service_never_calls_neo4j_and_human_approval_is_not_a_plan(review_files):
    class ExplodingDriver:
        def __getattr__(self, name):
            raise AssertionError(f"Neo4j called through {name}")

    proposals_dir, decisions = review_files
    record = ReviewService(
        proposals_dir,
        decisions,
        graph_driver=ExplodingDriver(),
    ).record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="APPROVE",
        request_id="approve-without-writer",
    )
    assert record["human_decision"] == "APPROVE"
    assert "mutation_operations" not in record
    assert "plan_hash" not in record
    assert "authorization" not in record


def test_highlight_uses_exact_episode_offsets(review_files):
    proposals_dir, decisions = review_files
    item = ReviewService(proposals_dir, decisions).queue("alpha").items[0]
    rebuilt = item["evidence_before"] + item["evidence_literal"] + item["evidence_after"]
    evidence = item["evidence"]
    assert rebuilt == item["episode_text"]
    assert item["evidence_literal"] == item["episode_text"][evidence["start"]:evidence["end"]]


def test_unknown_reason_code_is_shown_verbatim(review_files):
    proposals_dir, decisions = review_files
    raw = proposal("unknown", reason_codes=["NEW_ENGINE_REASON"])
    (proposals_dir / "queue.json").write_text(json.dumps(raw), encoding="utf-8")
    item = ReviewService(proposals_dir, decisions).queue("alpha").items[0]
    assert item["reason_explanations"] == [
        {"code": "NEW_ENGINE_REASON", "label": "NEW_ENGINE_REASON"}
    ]
    assert reason_label("NEW_ENGINE_REASON") == "NEW_ENGINE_REASON"


def test_real_reconciliation_candidate_origin_shape_is_presented(review_files):
    proposals_dir, decisions = review_files
    raw = proposal("reconciled")
    raw.pop("alternatives")
    raw["metadata"]["reconciliation"].update({
        "predicate_candidate_origins": [{
            "predicate": "GUARDS",
            "confidence": 0.64,
            "proposal_id": "provider-claim-1",
            "origin": {"provider": "local", "name": "rules-es"},
        }],
        "direction_candidate_origins": [{
            "direction": "OBJECT_TO_SUBJECT",
            "confidence": 0.41,
            "proposal_id": "provider-claim-2",
            "origin": {"provider": "local", "name": "semantic-es"},
        }],
    })
    (proposals_dir / "queue.json").write_text(json.dumps(raw), encoding="utf-8")
    item = ReviewService(proposals_dir, decisions).queue("alpha").items[0]
    assert item["predicate_alternatives"] == [{
        "value": "GUARDS",
        "confidence": 0.64,
        "extractor": "rules-es",
        "proposal_id": "provider-claim-1",
    }]
    assert item["direction_alternatives"][0]["extractor"] == "semantic-es"


def test_undo_is_a_new_superseding_entry_and_restores_pending(review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    approved = service.record(
        proposal_id="p1",
        workspace="alpha",
        reviewer="mara",
        human_decision="APPROVE",
        request_id="approve-before-undo",
    )
    assert [item["proposal_id"] for item in service.queue("alpha").items] == ["p2"]
    undo = service.undo_last(workspace="alpha", reviewer="mara", request_id="undo-1")
    assert undo["supersedes_decision_id"] == approved["decision_id"]
    assert undo["correction"] == {"undo": True, "restores": "PENDING"}
    assert len(read_history(decisions)) == 2
    assert [item["proposal_id"] for item in service.queue("alpha").items] == ["p1", "p2"]


def test_html_contains_exact_mark_and_unknown_reason(monkeypatch, tmp_path):
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    (proposals_dir / "one.json").write_text(
        json.dumps(proposal("html", reason_codes=["UNRECOGNIZED_BY_UI"])),
        encoding="utf-8",
    )
    service = ReviewService(proposals_dir, tmp_path / "decisions.jsonl")
    monkeypatch.setattr(router_module, "_service", lambda: service)

    app = FastAPI()
    app.include_router(router_module.router)
    response = TestClient(app).get("/v3/review?workspace=alpha")
    assert response.status_code == 200
    assert "<mark>protege la ciudad de Bruma</mark>" in response.text
    assert "UNRECOGNIZED_BY_UI" in response.text
    assert "semantic-local" in response.text


def test_post_reload_does_not_duplicate_decision(monkeypatch, review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    monkeypatch.setattr(router_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(router_module.router)
    client = TestClient(app)
    item = next(i for i in service.queue("alpha").items if i["proposal_id"] == "p1")
    form = {
        "workspace": "alpha",
        "proposal_id": "p1",
        "human_decision": "APPROVE",
        "request_id": "same-browser-submit",
        "expected_proposal_hash": item["proposal_hash"],
        "csrf_token": "",
    }
    # Sin hash, la ruta HTTP rechaza: el control de revisión obsoleta es obligatorio.
    sin_hash = {k: v for k, v in form.items() if k != "expected_proposal_hash"}
    assert client.post("/v3/review/decide", data=sin_hash, follow_redirects=False).status_code == 400
    assert client.post("/v3/review/decide", data=form, follow_redirects=False).status_code == 303
    assert client.post("/v3/review/decide", data=form, follow_redirects=False).status_code == 303
    assert len(read_history(decisions)) == 1


def test_stale_review_is_audited_without_changing_valid_history(review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    with pytest.raises(StaleReviewError, match="STALE_REVIEW"):
        service.record(
            proposal_id="p1", workspace="alpha", reviewer="mara",
            human_decision="APPROVE", request_id="stale-1",
            expected_proposal_hash="0" * 64,
        )
    assert read_history(decisions) == []
    audit = json.loads((decisions.parent / "audit.jsonl").read_text(encoding="utf-8"))
    assert audit["event"] == "STALE_REVIEW"
    assert audit["expected_proposal_hash"] == "0" * 64


def test_explicit_alias_correction_proposes_but_never_applies_glossary(review_files):
    proposals_dir, decisions = review_files
    service = ReviewService(proposals_dir, decisions)
    item = service.queue("alpha").items[0]
    record = service.record(
        proposal_id=item["proposal_id"], workspace="alpha", reviewer="mara",
        human_decision="CORRECT", request_id="alias-1",
        expected_proposal_hash=item["proposal_hash"],
        correction={"subject_alias": "Ari"},
    )
    from app.services.v3_glossary_candidates import GlossaryCandidateStore
    candidates = GlossaryCandidateStore(
        decisions.parent / "glossary-candidates"
    ).list("alpha")
    assert len(candidates) == 1
    assert candidates[0]["candidate_type"] == "ALIAS_CANDIDATE"
    assert candidates[0]["origin"]["human_decision_ids"] == [record["decision_id"]]
    assert candidates[0]["status"] == "PROPOSED"
    assert "apply" not in candidates[0]
