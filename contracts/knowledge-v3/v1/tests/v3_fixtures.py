"""
fixtures.py — constructores deterministas de documentos `v3-internal-v1`.

Fuente UNICA de los ejemplos: `examples/valid/*.json` y `examples/invalid/*.json`
se generan desde aqui y un test comprueba que no han derivado (byte a byte).
Asi un ejemplo no puede quedarse obsoleto respecto al contrato sin que el gate
se ponga rojo.

Los tests de los modelos Python (data-engine) importan este mismo modulo: los
dos lados de la casa validan exactamente los mismos documentos.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

CONTRACT_DIR = Path(__file__).resolve().parent.parent

# El validador se carga con un nombre de modulo UNICO y no por `sys.path`:
# el contrato review/ingest v1 tiene otro modulo llamado `validator` y en la
# corrida conjunta el primero en importarse se llevaria al otro por delante.
_VALIDATOR_MODULE = "s9k_knowledge_v3_contract_validator"
if _VALIDATOR_MODULE in sys.modules:
    V = sys.modules[_VALIDATOR_MODULE]
else:
    _spec = importlib.util.spec_from_file_location(
        _VALIDATOR_MODULE, CONTRACT_DIR / "validator.py"
    )
    V = importlib.util.module_from_spec(_spec)
    sys.modules[_VALIDATOR_MODULE] = V
    _spec.loader.exec_module(V)

WORKSPACE = "leyenda"
ASSET_ID = "asset:manual-001"
EPISODE_ID = "episode:manual-001:p12"
COLLECTION_ID = "collection:campana-leyenda"
GAME_PROFILE = "generic"
VERSION = "1.0.0"


def h(seed: str) -> dict[str, str]:
    """Hash determinista y reproducible a partir de una semilla textual."""
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


SOURCE_HASH = h("asset:manual-001")


def trace_local(step: str, produced: list[str]) -> dict[str, Any]:
    return {
        "step": step,
        "provider": "local",
        "name": "s9k.knowledge_v3",
        "version": "3.0.0",
        "model": None,
        "produced": produced,
    }


def trace_ollama(step: str, produced: list[str]) -> dict[str, Any]:
    return {
        "step": step,
        "provider": "ollama",
        "name": "s9k.extractor.ollama",
        "version": "3.0.0",
        "model": "qwen2.5:7b",
        "produced": produced,
    }


def trace_external(step: str, produced: list[str]) -> dict[str, Any]:
    return {
        "step": step,
        "provider": "external",
        "name": "s9k.external_ai.nvidia",
        "version": "3.0.0",
        "model": "meta/llama-3.1-70b-instruct",
        "produced": produced,
    }


def envelope(**overrides: Any) -> dict[str, Any]:
    base = {
        "contract_version": VERSION,
        "workspace": WORKSPACE,
        "source_asset_id": ASSET_ID,
        "source_hash": SOURCE_HASH,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Constructores por contrato
# --------------------------------------------------------------------------
def source_asset() -> dict[str, Any]:
    return {
        "contract_id": "source-asset/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("ingest", ["content_hash", "byte_size", "mime_type"])],
        "produced_by_step": "ingest",
        "asset_id": ASSET_ID,
        "collection_id": COLLECTION_ID,
        "game_profile": GAME_PROFILE,
        "source_kind": "PDF",
        "mime_type": "application/pdf",
        "content_hash": SOURCE_HASH,
        "byte_size": 4823191,
        "original_name": "manual-de-campana.pdf",
        "original_location": "staging/media/manual-de-campana.pdf",
        "created_at": "2026-07-01T09:00:00Z",
        "ingested_at": "2026-07-27T10:15:00Z",
        "language_hint": "es",
        "privacy_class": "INTERNAL",
        "copyright_class": "COPYRIGHTED",
        "processing_policy": {
            "allow_external_providers": False,
            "allow_media_persistence": True,
            "retention_days": 365,
        },
        "metadata": {"pages": 214},
    }


def source_asset_personal_audio() -> dict[str, Any]:
    """Grabacion con datos personales: nunca sale a un proveedor externo."""
    asset_id = "asset:sesion-2026-05-11"
    content = h(asset_id)
    return {
        "contract_id": "source-asset/v3-internal-v1",
        **envelope(source_asset_id=asset_id, source_hash=content),
        "provider_trace": [trace_local("ingest", ["content_hash", "byte_size"])],
        "produced_by_step": "ingest",
        "asset_id": asset_id,
        "collection_id": COLLECTION_ID,
        "game_profile": GAME_PROFILE,
        "source_kind": "AUDIO",
        "mime_type": "audio/ogg",
        "content_hash": content,
        "byte_size": 91238411,
        "original_name": "sesion-2026-05-11.ogg",
        "original_location": "staging/media/sesion-2026-05-11.ogg",
        "created_at": "2026-05-11T18:30:00Z",
        "ingested_at": "2026-05-12T08:00:00Z",
        "language_hint": "es",
        "privacy_class": "PERSONAL_DATA",
        "copyright_class": "OWN",
        "processing_policy": {
            "allow_external_providers": False,
            "allow_media_persistence": False,
            "retention_days": 90,
        },
    }


def source_episode() -> dict[str, Any]:
    return {
        "contract_id": "source-episode/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("pdf.text", ["text", "page", "content_hash"])],
        "produced_by_step": "pdf.text",
        "episode_id": EPISODE_ID,
        "asset_id": ASSET_ID,
        "sequence": 12,
        "modality": "TEXT",
        "text": "Daiki, magistrado de la Casa del Ciervo, jamas juro lealtad al Consejo de Umbra.",
        "page": 12,
        "bbox": None,
        "time_start": None,
        "time_end": None,
        "previous_episode_id": "episode:manual-001:p11",
        "next_episode_id": "episode:manual-001:p13",
        "speaker": None,
        "turn": None,
        "table": None,
        "quality": {"score": 0.97, "flags": []},
        "content_hash": h("episode:manual-001:p12"),
    }


def source_episode_audio() -> dict[str, Any]:
    asset_id = "asset:sesion-2026-05-11"
    return {
        "contract_id": "source-episode/v3-internal-v1",
        **envelope(source_asset_id=asset_id, source_hash=h(asset_id)),
        "provider_trace": [
            trace_local("vad", ["time_start", "time_end"]),
            trace_local("asr", ["text"]),
        ],
        "produced_by_step": "asr",
        "episode_id": "episode:sesion-2026-05-11:t0042",
        "asset_id": asset_id,
        "sequence": 42,
        "modality": "ASR_TEXT",
        "text": "el magistrado nunca juro lealtad al consejo",
        "page": None,
        "bbox": None,
        "time_start": 1284.5,
        "time_end": 1291.25,
        "previous_episode_id": "episode:sesion-2026-05-11:t0041",
        "next_episode_id": None,
        "speaker": {"speaker_id": "speaker:02", "label": "Director de juego", "confidence": 0.72},
        "turn": 17,
        "table": None,
        "quality": {"score": 0.61, "flags": ["LOW_SNR"]},
        "content_hash": h("episode:sesion-2026-05-11:t0042"),
    }


def source_episode_table() -> dict[str, Any]:
    """Tabla: la representacion estructurada NO se aplana a texto."""
    return {
        "contract_id": "source-episode/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("pdf.tables", ["table", "content_hash"])],
        "produced_by_step": "pdf.tables",
        "episode_id": "episode:manual-001:p31:t0",
        "asset_id": ASSET_ID,
        "sequence": 31,
        "modality": "TABLE",
        "text": None,
        "page": 31,
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.4, "page": 31},
        "time_start": None,
        "time_end": None,
        "previous_episode_id": None,
        "next_episode_id": None,
        "speaker": None,
        "turn": None,
        "table": {
            "header": ["Casa", "Sede", "Lema"],
            "rows": [
                ["Casa del Ciervo", "Vado Alto", "Ni un paso atras"],
                ["Consejo de Umbra", "Umbra", None],
            ],
        },
        "quality": {"score": 0.83, "flags": []},
        "content_hash": h("episode:manual-001:p31:t0"),
    }


def evidence_fragment_htr() -> dict[str, Any]:
    """Manuscrito: HTR es un media_type propio, no OCR."""
    doc = evidence_fragment()
    doc.update(
        {
            "provider_trace": [trace_local("htr", ["literal_text", "bbox"])],
            "produced_by_step": "htr",
            "fragment_id": "fragment:p14:htr:0",
            "episode_id": "episode:manual-001:p14",
            "literal_text": "el pacto se firmo de noche",
            "normalized_text": "el pacto se firmo de noche",
            "start": 0,
            "end": 26,
            "bbox": {"x": 0.2, "y": 0.5, "width": 0.5, "height": 0.06, "page": 14},
            "page": 14,
            "media_type": "HTR_TEXT",
            "confidence": 0.57,
        }
    )
    return doc


def fact_assertion_conflicted() -> dict[str, Any]:
    """Estado epistemico CONFLICTED: el motor tiene que poder emitirlo."""
    doc = fact_assertion()
    doc.update(
        {
            "assertion_id": "assertion:0002",
            "epistemic_status": "CONFLICTED",
            "status": "CONTRADICTED",
            "state": "UNKNOWN",
            "confidence": 0.5,
        }
    )
    return doc


def evidence_fragment() -> dict[str, Any]:
    return {
        "contract_id": "evidence-fragment/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("anchor", ["start", "end", "literal_text"])],
        "produced_by_step": "anchor",
        "fragment_id": "fragment:p12:0",
        "episode_id": EPISODE_ID,
        "literal_text": "jamas juro lealtad al Consejo de Umbra",
        "normalized_text": "jamas juro lealtad al consejo de umbra",
        "start": 42,
        "end": 79,
        "bbox": None,
        "time_start": None,
        "time_end": None,
        "frame_id": None,
        "page": 12,
        "media_type": "EMBEDDED_TEXT",
        "confidence": 1.0,
    }


def evidence_fragment_ocr() -> dict[str, Any]:
    """OCR literal: exige bbox. Nunca se mezcla con descripcion visual."""
    return {
        "contract_id": "evidence-fragment/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("ocr", ["literal_text", "bbox"])],
        "produced_by_step": "ocr",
        "fragment_id": "fragment:p13:ocr:0",
        "episode_id": "episode:manual-001:p13",
        "literal_text": "CASA DEL CIERVO",
        "normalized_text": "casa del ciervo",
        "start": 0,
        "end": 15,
        "bbox": {"x": 0.12, "y": 0.08, "width": 0.31, "height": 0.05, "page": 13},
        "time_start": None,
        "time_end": None,
        "frame_id": None,
        "page": 13,
        "media_type": "OCR_TEXT",
        "confidence": 0.88,
    }


def entity_mention() -> dict[str, Any]:
    return {
        "contract_id": "entity-mention/v3-internal-v1",
        **envelope(),
        "provider_trace": [
            trace_local("ner.deterministic", ["surface", "start", "end"]),
            trace_ollama("ner.llm", ["type_candidates"]),
        ],
        "produced_by_step": "ner.llm",
        "mention_id": "mention:p12:0",
        "episode_id": EPISODE_ID,
        "surface": "Daiki",
        "normalized_surface": "daiki",
        "start": 0,
        "end": 5,
        "bbox": None,
        "time_start": None,
        "time_end": None,
        "type_candidates": [
            {"type": "Character", "confidence": 0.91},
            {"type": "Concept", "confidence": 0.04},
        ],
        "confidence": 0.91,
        "coreference_candidates": ["mention:p12:3"],
        "evidence_fragment_ids": ["fragment:p12:0"],
    }


def claim_proposal() -> dict[str, Any]:
    return {
        "contract_id": "claim-proposal/v3-internal-v1",
        **envelope(),
        "provider_trace": [
            trace_local("anchor", ["evidence_fragment_ids"]),
            trace_ollama("extract.claims", ["claim", "predicate_candidates"]),
        ],
        "produced_by_step": "extract.claims",
        "claim_id": "claim:p12:0",
        "episode_id": EPISODE_ID,
        "subject_mentions": ["mention:p12:0"],
        "relation_phrase": "jamas juro lealtad a",
        "object_mentions": ["mention:p12:2"],
        "predicate_candidates": [
            {"predicate": "MEMBER_OF", "confidence": 0.62},
            {"predicate": "ALLY_OF", "confidence": 0.21},
        ],
        "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.88}],
        "temporal_expressions": [],
        "negated": True,
        "epistemic_cues": ["jamas"],
        "epistemic_status_hint": "ASSERTED",
        "qualifiers": [],
        "evidence_fragment_ids": ["fragment:p12:0"],
        "confidence": 0.62,
        "alternatives": [
            {
                "predicate": "ALLY_OF",
                "direction": "UNDIRECTED",
                "confidence": 0.21,
                "reason_codes": ["LEXICAL_AMBIGUITY"],
            }
        ],
        "abstained": False,
        "review_required": True,
    }


def claim_proposal_abstained() -> dict[str, Any]:
    """Abstenerse es una salida valida y preferible a inventar."""
    doc = claim_proposal()
    doc.update(
        {
            "claim_id": "claim:p12:9",
            "predicate_candidates": [],
            "alternatives": [],
            "confidence": 0,
            "abstained": True,
            "review_required": True,
            "negated": False,
            "epistemic_cues": [],
        }
    )
    return doc


def claim_proposal_visual() -> dict[str, Any]:
    """Claim derivado de un dibujo: nace exigiendo revision."""
    doc = claim_proposal()
    doc.update(
        {
            "claim_id": "claim:p13:0",
            "episode_id": "episode:manual-001:p13",
            "provider_trace": [
                trace_local("layout", ["bbox"]),
                trace_external("extract.visual", ["predicate_candidates"]),
            ],
            "produced_by_step": "extract.visual",
            "subject_mentions": ["mention:p13:0"],
            "object_mentions": ["mention:p13:1"],
            "relation_phrase": "aparece dentro del recinto de",
            "predicate_candidates": [{"predicate": "LOCATED_IN", "confidence": 0.44}],
            "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.44}],
            "alternatives": [],
            "epistemic_status_hint": "VISUAL_INFERRED",
            "epistemic_cues": [],
            "negated": False,
            "evidence_fragment_ids": ["fragment:p13:ocr:0"],
            "confidence": 0.44,
            "review_required": True,
        }
    )
    return doc


def entity_resolution() -> dict[str, Any]:
    return {
        "contract_id": "entity-resolution/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("resolve.identity", ["action", "selected_entity_id"])],
        "produced_by_step": "resolve.identity",
        "resolution_id": "resolution:daiki",
        "mention_ids": ["mention:p12:0", "mention:p12:3"],
        "candidate_entity_ids": ["entity:daiki", "entity:daiqui"],
        "selected_entity_id": "entity:daiki",
        "assigned_entity_id": None,
        "action": "LINK_EXISTING",
        "entity_type": "Character",
        "confidence": 0.84,
        "evidence": ["fragment:p12:0"],
        "reason_codes": ["EXACT_ALIAS", "TYPE_COMPATIBLE"],
        "game_profile": GAME_PROFILE,
    }


def entity_resolution_provisional() -> dict[str, Any]:
    doc = entity_resolution()
    doc.update(
        {
            "resolution_id": "resolution:consejo-umbra",
            "mention_ids": ["mention:p12:2"],
            "candidate_entity_ids": [],
            "selected_entity_id": None,
            "assigned_entity_id": "entity:prov:consejo-umbra",
            "action": "CREATE_PROVISIONAL",
            "entity_type": "Faction",
            "confidence": 0.35,
            "reason_codes": ["NO_CANDIDATE", "LOW_SUPPORT"],
        }
    )
    return doc


def fact_assertion() -> dict[str, Any]:
    return {
        "contract_id": "fact-assertion/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("engine.decide", ["predicate", "direction", "status"])],
        "produced_by_step": "engine.decide",
        "assertion_id": "assertion:0001",
        "subject_entity_id": "entity:daiki",
        "object_entity_id": "entity:casa-del-ciervo",
        "predicate": "MEMBER_OF",
        "direction": "SUBJECT_TO_OBJECT",
        "valid_from": "1042-03-01T00:00:00Z",
        "valid_to": None,
        "recorded_at": "2026-07-27T10:20:00Z",
        "epistemic_status": "ASSERTED",
        "confidence": 0.79,
        "status": "ASSERTED",
        "state": "ACTIVE",
        "event_time": "1042-03-01T00:00:00Z",
        "calendar_id": "calendar:umbra",
        "collection_id": COLLECTION_ID,
        "game_profile": GAME_PROFILE,
        "engine_version": "3.0.0",
        "ontology_version": "core-1.4.0",
        "evidence_fragment_ids": ["fragment:p12:0"],
        "episode_ids": [EPISODE_ID],
        "supersedes": None,
        "superseded_by": None,
        "negated": False,
    }


def fact_assertion_superseded() -> dict[str, Any]:
    doc = fact_assertion()
    doc.update(
        {
            "assertion_id": "assertion:0000",
            "status": "SUPERSEDED",
            "state": "ENDED",
            "superseded_by": "assertion:0001",
            "valid_from": "1041-01-01T00:00:00Z",
            "valid_to": "1042-02-28T00:00:00Z",
            "recorded_at": "2026-06-01T09:00:00Z",
        }
    )
    return doc


def _plan_body() -> dict[str, Any]:
    return {
        "contract_id": "graph-mutation-plan/v3-internal-v1",
        **envelope(),
        "provider_trace": [trace_local("engine.plan", ["decisions", "mutation_operations"])],
        "produced_by_step": "engine.plan",
        "plan_id": "plan:manual-001:0001",
        "plan_hash": h("placeholder"),
        "snapshot_id": "snapshot:neo4j:2026-07-27T10:29:00Z",
        "engine_version": "3.0.0",
        "ontology_version": "core-1.4.0",
        "game_profile": GAME_PROFILE,
        "collection_id": COLLECTION_ID,
        "created_at": "2026-07-27T10:30:00Z",
        "expires_at": "2026-07-28T10:30:00Z",
        "decisions": [
            {
                "decision_id": "decision:0001",
                "claim_id": "claim:p12:0",
                "decision": "ACCEPT",
                "predicate": "MEMBER_OF",
                "direction": "SUBJECT_TO_OBJECT",
                "subject_entity_id": "entity:daiki",
                "object_entity_id": "entity:casa-del-ciervo",
                "epistemic_status": "ASSERTED",
                "negated": False,
                "confidence": 0.79,
                "reason_codes": ["LOCAL_APPROVED", "EVIDENCE_LITERAL", "ONTOLOGY_COMPATIBLE"],
                "evidence_fragment_ids": ["fragment:p12:0"],
            },
            {
                "decision_id": "decision:0002",
                "claim_id": "claim:p13:0",
                "decision": "ABSTAIN",
                "predicate": None,
                "direction": None,
                "subject_entity_id": None,
                "object_entity_id": None,
                "confidence": 0.44,
                "reason_codes": ["INSUFFICIENT_EVIDENCE", "VISUAL_INFERRED"],
                "evidence_fragment_ids": ["fragment:p13:ocr:0"],
            },
        ],
        "mutation_operations": [
            {
                "operation_id": "op:0001",
                "operation_type": "CREATE_ASSERTION",
                "decision_id": "decision:0001",
                "target_entity_id": None,
                "assertion_id": "assertion:0001",
                "payload": {
                    "predicate": "MEMBER_OF",
                    "subject_entity_id": "entity:daiki",
                    "object_entity_id": "entity:casa-del-ciervo",
                },
                "evidence_fragment_ids": ["fragment:p12:0"],
                "idempotency_key": "idem:sha256:" + "0" * 64,
                "expected_state": "WOULD_CREATE",
                "expected_version": None,
                "expected_hash": None,
            }
        ],
        "local_approval": {
            "approved": True,
            "decision_hash": h("placeholder"),
            "validator_chain": [
                {"validator": "structural", "version": "3.0.0", "result": "PASS"},
                {"validator": "semantic", "version": "3.0.0", "result": "PASS"},
                {"validator": "ontology", "version": "core-1.4.0", "result": "PASS"},
            ],
            "created_at": "2026-07-27T10:30:00Z",
            "approved_by": {"provider": "local", "name": "s9k.engine.local", "version": "3.0.0"},
        },
    }


def graph_mutation_plan() -> dict[str, Any]:
    """Plan sellado: `decision_hash` y `plan_hash` calculados de verdad."""
    return V.seal_plan(_plan_body())


def graph_mutation_plan_not_approved() -> dict[str, Any]:
    body = _plan_body()
    body["plan_id"] = "plan:manual-001:0002"
    body["decisions"][1]["decision"] = "REVIEW"
    body["decisions"][1]["reason_codes"] = ["REVIEW_EVIDENCE", "VISUAL_INFERRED"]
    body["local_approval"]["approved"] = False
    body["local_approval"]["validator_chain"][2]["result"] = "FAIL"
    body["local_approval"]["validator_chain"][2]["reason_codes"] = ["PREDICATE_OUT_OF_ONTOLOGY"]
    return V.seal_plan(body)


def game_profile() -> dict[str, Any]:
    profile_source = "profile:generic"
    return {
        "contract_id": "game-profile/v3-internal-v1",
        **envelope(source_asset_id=profile_source, source_hash=h(profile_source)),
        "provider_trace": [trace_local("profile.load", ["predicates", "entity_types"])],
        "produced_by_step": "profile.load",
        "profile_id": GAME_PROFILE,
        "profile_version": "1.0.0",
        "core_ontology_version": "core-1.4.0",
        "entity_types": ["Character", "Location", "Faction", "Object", "Event", "Concept"],
        "predicates": [
            {
                "predicate": "MEMBER_OF",
                "domain": ["Character"],
                "range": ["Faction"],
                "symmetric": False,
                "transitive": False,
                "functional": False,
                "inverse_of": "HAS_MEMBER",
            },
            {
                "predicate": "HAS_MEMBER",
                "domain": ["Faction"],
                "range": ["Character"],
                "symmetric": False,
                "transitive": False,
                "functional": False,
                "inverse_of": "MEMBER_OF",
            },
            {
                "predicate": "LOCATED_IN",
                "domain": ["Character", "Object", "Location", "Event"],
                "range": ["Location"],
                "symmetric": False,
                "transitive": True,
                "functional": False,
                "inverse_of": None,
            },
            {
                "predicate": "ALLY_OF",
                "domain": ["Character", "Faction"],
                "range": ["Character", "Faction"],
                "symmetric": True,
                "transitive": False,
                "functional": False,
                "inverse_of": None,
            },
        ],
        "aliases": [{"canonical": "Daiki", "variants": ["Daiqui", "daiki", "el magistrado"]}],
        "titles": ["magistrado", "senescal"],
        "factions": ["Casa del Ciervo", "Consejo de Umbra"],
        "calendars": [
            {"calendar_id": "calendar:umbra", "epoch_label": "Era del Ciervo", "units": ["ciclo", "luna"]}
        ],
        "identity_rules": [
            {
                "rule_id": "rule:never-merge-titles",
                "kind": "NEVER_MERGE_IF",
                "reason_code": "TITLE_ONLY_MATCH",
                "description": "Un titulo compartido no basta para fusionar dos personajes.",
            }
        ],
        "ambiguous_terms": ["el magistrado", "el consejo"],
        "source_priorities": [
            {"source_kind": "PDF", "priority": 80},
            {"source_kind": "AUDIO", "priority": 40},
        ],
        "evaluation_examples": [
            {
                "example_id": "example:0001",
                "text": "Daiki jamas juro lealtad al Consejo de Umbra.",
                "expected": "NEGATED MEMBER_OF(Daiki, Consejo de Umbra)",
            }
        ],
    }


#: Ejemplos VALIDOS. Nombre de fichero -> constructor.
VALID_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "source_asset_pdf": source_asset,
    "source_asset_personal_audio": source_asset_personal_audio,
    "source_episode_text": source_episode,
    "source_episode_audio": source_episode_audio,
    "source_episode_table": source_episode_table,
    "evidence_fragment_text": evidence_fragment,
    "evidence_fragment_ocr": evidence_fragment_ocr,
    "evidence_fragment_htr": evidence_fragment_htr,
    "entity_mention": entity_mention,
    "claim_proposal": claim_proposal,
    "claim_proposal_abstained": claim_proposal_abstained,
    "claim_proposal_visual": claim_proposal_visual,
    "entity_resolution_link": entity_resolution,
    "entity_resolution_provisional": entity_resolution_provisional,
    "fact_assertion": fact_assertion,
    "fact_assertion_superseded": fact_assertion_superseded,
    "fact_assertion_conflicted": fact_assertion_conflicted,
    "graph_mutation_plan_approved": graph_mutation_plan,
    "graph_mutation_plan_not_approved": graph_mutation_plan_not_approved,
    "game_profile_generic": game_profile,
}


# --------------------------------------------------------------------------
# Ejemplos INVALIDOS: cada uno es UNA mutacion documentada sobre un valido.
# Si una regla se relaja, el ejemplo correspondiente deja de ser rechazado y
# el gate se pone rojo. Ese es exactamente su proposito.
# --------------------------------------------------------------------------
def _mut(builder: Callable[[], dict[str, Any]], fn: Callable[[dict], None]) -> dict[str, Any]:
    doc = deepcopy(builder())
    fn(doc)
    return doc


def _mut_sealed(builder: Callable[[], dict[str, Any]], fn: Callable[[dict], None]) -> dict[str, Any]:
    """Muta un plan y lo VUELVE A SELLAR.

    Se usa cuando lo que se quiere ejercitar es una regla estructural del plan
    (idempotencia, decision, caducidad, firmante...) y no la deteccion de
    manipulacion. Sin resellar, el documento seria rechazado por el hash y el
    ejemplo no probaria la regla que dice probar.
    """
    return V.seal_plan(_mut(builder, fn))


def _mut_sealed_raw(builder: Callable[[], dict[str, Any]], fn: Callable[[dict], None]) -> dict[str, Any]:
    """Sella sin recalcular las claves de idempotencia.

    Necesario para ejercitar las reglas SOBRE la clave (ausente, inventada):
    si el sellado la regenerase, el ejemplo dejaria de probar nada.
    """
    return V.seal_plan(_mut(builder, fn), derive_keys=False)


def _set(key: str, value: Any) -> Callable[[dict], None]:
    def apply(doc: dict) -> None:
        doc[key] = value

    return apply


def _drop(key: str) -> Callable[[dict], None]:
    def apply(doc: dict) -> None:
        doc.pop(key, None)

    return apply


INVALID_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    # -- envelope comun ---------------------------------------------------
    "asset_unknown_field": lambda: _mut(source_asset, _set("campo_inventado", 1)),
    "asset_missing_workspace": lambda: _mut(source_asset, _drop("workspace")),
    "asset_empty_workspace": lambda: _mut(source_asset, _set("workspace", "")),
    "asset_missing_source_hash": lambda: _mut(source_asset, _drop("source_hash")),
    "asset_hash_without_algorithm": lambda: _mut(
        source_asset, _set("source_hash", {"value": "a" * 64})
    ),
    "asset_missing_provider_trace": lambda: _mut(source_asset, _drop("provider_trace")),
    "asset_empty_provider_trace": lambda: _mut(source_asset, _set("provider_trace", [])),
    "asset_unknown_provider": lambda: _mut(
        source_asset,
        _set("provider_trace", [{**trace_local("x", ["y"]), "provider": "openai"}]),
    ),
    "asset_wrong_major_version": lambda: _mut(source_asset, _set("contract_version", "2.0.0")),
    "asset_wrong_contract_id": lambda: _mut(
        source_asset, _set("contract_id", "source-asset/v3-internal-v2")
    ),
    "asset_source_hash_differs_from_content": lambda: _mut(
        source_asset, _set("source_hash", h("otro"))
    ),
    "asset_secret_in_metadata": lambda: _mut(source_asset, _set("metadata", {"api_key": "abc123"})),
    "asset_credentials_in_location": lambda: _mut(
        source_asset, _set("original_location", "https://user:pass@example.org/manual.pdf")
    ),
    "asset_personal_data_allows_external": lambda: _mut(
        source_asset_personal_audio,
        _set(
            "processing_policy",
            {"allow_external_providers": True, "allow_media_persistence": False, "retention_days": 90},
        ),
    ),
    "asset_produced_by_step_dangling": lambda: _mut(
        source_asset, _set("produced_by_step", "paso:que:no:existe")
    ),
    "asset_missing_produced_by_step": lambda: _mut(source_asset, _drop("produced_by_step")),
    # -- episodio ---------------------------------------------------------
    "episode_time_inverted": lambda: _mut(source_episode_audio, _set("time_start", 9999.0)),
    "episode_self_reference": lambda: _mut(
        source_episode, _set("previous_episode_id", EPISODE_ID)
    ),
    "episode_text_modality_without_text": lambda: _mut(source_episode, _set("text", None)),
    "episode_table_without_table_data": lambda: _mut(source_episode_table, _set("table", None)),
    "episode_speaker_turn_without_speaker": lambda: _mut(
        source_episode_audio,
        lambda d: d.update({"modality": "SPEAKER_TURN", "speaker": None}),
    ),
    # -- evidencia --------------------------------------------------------
    "fragment_offsets_inverted": lambda: _mut(evidence_fragment, _set("start", 999)),
    "fragment_ocr_without_bbox": lambda: _mut(evidence_fragment_ocr, _set("bbox", None)),
    "fragment_empty_literal_text": lambda: _mut(evidence_fragment, _set("literal_text", "")),
    # -- mencion ----------------------------------------------------------
    "mention_without_evidence": lambda: _mut(entity_mention, _set("evidence_fragment_ids", [])),
    "mention_unknown_entity_type": lambda: _mut(
        entity_mention, _set("type_candidates", [{"type": "Vehicle", "confidence": 0.9}])
    ),
    "mention_self_coreference": lambda: _mut(
        entity_mention, _set("coreference_candidates", ["mention:p12:0"])
    ),
    # -- claim ------------------------------------------------------------
    "claim_abstained_with_predicate": lambda: _mut(
        claim_proposal_abstained,
        _set("predicate_candidates", [{"predicate": "MEMBER_OF", "confidence": 0.9}]),
    ),
    "claim_predicates_unsorted": lambda: _mut(
        claim_proposal,
        _set(
            "predicate_candidates",
            [{"predicate": "ALLY_OF", "confidence": 0.21}, {"predicate": "MEMBER_OF", "confidence": 0.62}],
        ),
    ),
    "claim_predicate_not_normalized": lambda: _mut(
        claim_proposal, _set("predicate_candidates", [{"predicate": "member of", "confidence": 0.6}])
    ),
    "claim_without_evidence": lambda: _mut(claim_proposal, _set("evidence_fragment_ids", [])),
    "claim_subject_is_also_object": lambda: _mut(
        claim_proposal, _set("object_mentions", ["mention:p12:0"])
    ),
    "claim_visual_without_review": lambda: _mut(
        claim_proposal_visual, _set("review_required", False)
    ),
    "claim_confidence_gt_1": lambda: _mut(claim_proposal, _set("confidence", 1.4)),
    "claim_directions_unsorted": lambda: _mut(
        claim_proposal,
        _set(
            "direction_candidates",
            [
                {"direction": "UNDIRECTED", "confidence": 0.5},
                {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.5},
            ],
        ),
    ),
    "claim_alternatives_unsorted": lambda: _mut(
        claim_proposal,
        _set(
            "alternatives",
            [
                {"predicate": "RIVAL_OF", "direction": "UNDIRECTED", "confidence": 0.3},
                {"predicate": "ALLY_OF", "direction": "UNDIRECTED", "confidence": 0.3},
            ],
        ),
    ),
    # -- resolucion -------------------------------------------------------
    "resolution_link_to_non_candidate": lambda: _mut(
        entity_resolution, _set("selected_entity_id", "entity:desconocida")
    ),
    "resolution_review_selects_entity": lambda: _mut(
        entity_resolution, lambda d: d.update({"action": "REVIEW", "selected_entity_id": "entity:daiki"})
    ),
    "resolution_create_new_selects_entity": lambda: _mut(
        entity_resolution, _set("action", "CREATE_NEW")
    ),
    "resolution_missing_entity_type": lambda: _mut(entity_resolution, _drop("entity_type")),
    "resolution_create_without_assigned_id": lambda: _mut(
        entity_resolution_provisional, _set("assigned_entity_id", None)
    ),
    "resolution_link_with_assigned_id": lambda: _mut(
        entity_resolution, _set("assigned_entity_id", "entity:nueva")
    ),
    "resolution_assigned_id_already_candidate": lambda: _mut(
        entity_resolution_provisional,
        lambda d: d.update({"candidate_entity_ids": ["entity:prov:consejo-umbra"]}),
    ),
    # -- afirmacion -------------------------------------------------------
    "assertion_superseded_without_successor": lambda: _mut(
        fact_assertion_superseded, _set("superseded_by", None)
    ),
    "assertion_validity_inverted": lambda: _mut(
        fact_assertion, _set("valid_to", "1000-01-01T00:00:00Z")
    ),
    "assertion_without_evidence": lambda: _mut(
        fact_assertion, _set("evidence_fragment_ids", [])
    ),
    "assertion_self_relation": lambda: _mut(
        fact_assertion, _set("object_entity_id", "entity:daiki")
    ),
    "assertion_missing_state": lambda: _mut(fact_assertion, _drop("state")),
    "assertion_missing_event_time": lambda: _mut(fact_assertion, _drop("event_time")),
    "assertion_missing_negated": lambda: _mut(fact_assertion, _drop("negated")),
    "assertion_active_with_valid_to": lambda: _mut(
        fact_assertion, _set("valid_to", "1050-01-01T00:00:00Z")
    ),
    "assertion_ended_without_valid_to": lambda: _mut(
        fact_assertion_superseded, _set("valid_to", None)
    ),
    "assertion_unknown_state": lambda: _mut(fact_assertion, _set("state", "TERMINADA")),
    # -- plan de mutacion (lo que el writer debe rechazar) ----------------
    # Tres SIN resellar: prueban la deteccion de manipulacion (el hash).
    "plan_hash_tampered": lambda: _mut(graph_mutation_plan, _set("plan_hash", h("otro"))),
    "plan_workspace_changed": lambda: _mut(graph_mutation_plan, _set("workspace", "otro-workspace")),
    "plan_source_hash_changed": lambda: _mut(graph_mutation_plan, _set("source_hash", h("otro"))),
    # El resto SI resellados: prueban la regla estructural, no el hash.
    "plan_without_signature": lambda: _mut_sealed(graph_mutation_plan, _drop("local_approval")),
    "plan_signed_by_external_provider": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["local_approval"]["approved_by"].update({"provider": "external"}),
    ),
    "plan_approved_with_review_decision": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["decisions"][1].update(
            {"decision": "REVIEW", "reason_codes": ["REVIEW_EVIDENCE"]}
        ),
    ),
    "plan_decision_without_canonical_reason": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["decisions"][0].update({"reason_codes": ["ME_LO_HA_PARECIDO"]}),
    ),
    "plan_approved_with_failed_validator": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["local_approval"]["validator_chain"][0].update({"result": "FAIL"}),
    ),
    "plan_duplicate_idempotency_key": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["mutation_operations"].append(
            dict(deepcopy(d["mutation_operations"][0]), operation_id="op:0002")
        ),
    ),
    "plan_operation_without_idempotency_key": lambda: _mut_sealed_raw(
        graph_mutation_plan, lambda d: d["mutation_operations"][0].pop("idempotency_key")
    ),
    "plan_invented_idempotency_key": lambda: _mut_sealed_raw(
        graph_mutation_plan,
        lambda d: d["mutation_operations"][0].update(
            {"idempotency_key": "idem:sha256:" + "b" * 64}
        ),
    ),
    "plan_missing_snapshot": lambda: _mut_sealed(graph_mutation_plan, _drop("snapshot_id")),
    "plan_update_without_expected_version": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["mutation_operations"][0].update({"operation_type": "UPDATE_ENTITY"}),
    ),
    "plan_create_with_expected_version": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["mutation_operations"][0].update({"expected_version": 3}),
    ),
    "plan_operation_on_abstained_decision": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["mutation_operations"][0].update({"decision_id": "decision:0002"}),
    ),
    "plan_expired_before_created": lambda: _mut_sealed(
        graph_mutation_plan, _set("expires_at", "2026-07-26T10:30:00Z")
    ),
    "plan_accept_without_predicate": lambda: _mut_sealed(
        graph_mutation_plan, lambda d: d["decisions"][0].update({"predicate": None})
    ),
    "plan_secret_in_payload": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["mutation_operations"][0]["payload"].update({"token": "abc123"}),
    ),
    "plan_unknown_operation_type": lambda: _mut_sealed(
        graph_mutation_plan,
        lambda d: d["mutation_operations"][0].update({"operation_type": "DELETE_ALL"}),
    ),
    "plan_approved_without_operations": lambda: _mut_sealed(
        graph_mutation_plan, _set("mutation_operations", [])
    ),
    # -- perfil -----------------------------------------------------------
    "profile_duplicate_predicate": lambda: _mut(
        game_profile, lambda d: d["predicates"].append(deepcopy(d["predicates"][0]))
    ),
    "profile_inverse_of_unknown": lambda: _mut(
        game_profile, lambda d: d["predicates"][0].update({"inverse_of": "NO_EXISTE"})
    ),
    "profile_learned_adapter_enabled": lambda: _mut(
        game_profile, _set("learned_adapter", {"adapter_id": "adapter:x", "enabled": True})
    ),
}
