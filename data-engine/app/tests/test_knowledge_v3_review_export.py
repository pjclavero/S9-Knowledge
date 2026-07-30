from dataclasses import dataclass, field

from knowledge_v3.review_export import export_review_package, review_documents


@dataclass
class Value:
    value: dict

    def to_dict(self):
        return self.value


@dataclass
class Run:
    source_id: str = "source-1"
    episodes: list = field(default_factory=lambda: [Value({
        "episode_id": "episode-1", "text": "Ariadna protege Bruma."
    })])
    fragments: list = field(default_factory=lambda: [Value({
        "fragment_id": "fragment-1", "start_offset": 8, "end_offset": 22
    })])
    claims: list = field(default_factory=lambda: [Value({
        "claim_id": "claim-1", "episode_id": "episode-1",
        "subject_mention_id": "mention-a", "object_mention_id": "mention-b",
        "predicate": "PROTECTS", "evidence_fragment_ids": ["fragment-1"],
        "provider_trace": [{"step": "extract", "provider": "local", "model": None}],
    })])
    resolutions: list = field(default_factory=lambda: [
        Value({"mention_id": "mention-a", "resolved_entity_id": "entity:a"}),
        Value({"mention_id": "mention-b", "resolved_entity_id": "entity:b"}),
    ])
    decisions: tuple = (Value({
        "claim_id": "claim-1", "episode_id": "episode-1",
        "decision": "REVIEW", "reason_codes": ["LOW_CONFIDENCE"],
    }),)
    shadow_decisions: tuple = (Value({
        "claim_id": "claim-1",
        "effective_decision": "REVIEW",
        "shadow_decision": "ACCEPT",
        "ignored_findings": ["EXTRACTOR_REQUESTED_REVIEW"],
        "effective_findings": ["EXTRACTOR_REQUESTED_REVIEW"],
        "shadow_findings": ["EVIDENCE_LITERAL_VERIFIED"],
        "would_emit_operations": True,
        "operation_kinds": ["CREATE_ASSERTION"],
        "provider": "ollama",
        "model": "qwen2.5:7b",
    }),)


@dataclass
class Result:
    config_declared: dict = field(default_factory=dict)
    runs: list = field(default_factory=lambda: [Run()])


def test_real_result_export_is_deterministic_complete_and_idempotent(tmp_path):
    result = Result()
    first = review_documents(result, workspace="alpha")
    second = review_documents(result, workspace="alpha")
    assert first == second
    assert first[0]["engine_decision"]["decision"] == "REVIEW"
    assert first[0]["engine_decision"]["effective_decision"] == "REVIEW"
    assert first[0]["engine_decision"]["shadow_decision"] == "ACCEPT"
    assert first[0]["engine_decision"]["provider"] == "ollama"
    assert first[0]["proposal_hash"]
    assert set(first[0]) >= {
        "proposal_id", "workspace", "source_id", "episode_id", "episode_text",
        "evidence", "proposal", "engine_decision", "resolution", "alternatives",
        "provenance", "ontology_version", "engine_version", "prompt_version",
        "profile_version", "proposal_hash",
    }
    path = export_review_package(result, tmp_path, workspace="alpha")
    assert export_review_package(result, tmp_path, workspace="alpha") == path
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_proposal_id_is_stable_while_version_hash_changes():
    result = Result()
    before = review_documents(result, workspace="alpha")[0]
    result.runs[0].decisions = (Value({
        "claim_id": "claim-1", "episode_id": "episode-1",
        "decision": "REVIEW", "reason_codes": ["DIFFERENT_REASON"],
    }),)
    after = review_documents(result, workspace="alpha")[0]
    assert before["proposal_id"] == after["proposal_id"]
    assert before["proposal_hash"] != after["proposal_hash"]
