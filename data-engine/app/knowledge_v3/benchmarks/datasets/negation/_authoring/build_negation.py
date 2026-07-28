# -*- coding: utf-8 -*-
"""Genera el split `negation` a partir de `cases.py`.

El contenido (textos y anotacion) esta escrito a mano en `cases.py`; aqui solo
se CALCULAN offsets, hashes y sobres. Un offset escrito a mano se equivoca; uno
calculado sobre el texto literal, no. Misma disciplina que el `authoring/` de
`dev` y el `_authoring/` del held-out.

    python -m knowledge_v3.benchmarks.datasets.negation._authoring.build_negation
    python -m ... .build_negation --check     # ¿ha derivado el dataset?
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from knowledge_v3.benchmarks.contracts_bridge import (
    CONTRACT_VERSION,
    sha256_hash,
    seal_plan,
    validate_document,
)

from . import cases as K

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_TRACE_VERSION = "1.0.0"

CREATED_AT = "2026-07-29T09:00:00Z"
INGESTED_AT = "2026-07-29T09:05:00Z"
RECORDED_AT = "2026-07-29T09:10:00Z"
PLAN_CREATED_AT = "2026-07-29T09:15:00Z"
PLAN_EXPIRES_AT = "2026-07-30T09:15:00Z"

WORLD_CALENDARS = {
    "basalto": ("calendar:basalto", "Cuenta de las Fraguas", ["ciclo", "temporada"]),
    "cirro": ("calendar:cirro", "Cuenta de los Vientos", ["ejercicio", "equinoccio"]),
    "zafiro": ("calendar:zafiro", "Cuenta Abisal", ["ciclo", "marea"]),
    "ambar": ("calendar:ambar", "Era de la Resina", ["ano", "invierno"]),
}

ENTITY_TYPE = {e[0]: e[3] for e in K.ENTITIES}
ENTITY_WORLD = {e[0]: e[1] for e in K.ENTITIES}
SYMMETRIC = {"ALLY_OF", "RIVAL_OF", "SIBLING_OF"}


def trace(step: str, produced: list[str]) -> list[dict]:
    return [
        {
            "step": step,
            "provider": "local",
            "name": "s9k.benchmarks.negation",
            "version": CONTRACT_TRACE_VERSION,
            "model": None,
            "produced": produced,
        }
    ]


def bench_meta(world: str, source_id: str) -> dict:
    return {
        "split": K.SPLIT,
        "dataset_version": K.DATASET_VERSION,
        "world": world,
        "source_id": source_id,
    }


def find_span(text: str, needle: str, occurrence: int = 0) -> tuple[int, int]:
    start = -1
    for _ in range(occurrence + 1):
        start = text.find(needle, start + 1)
        if start < 0:
            raise ValueError(f"no aparece en el episodio: {needle!r}")
    return start, start + len(needle)


def bbox_for(index: int) -> dict:
    return {
        "x": 0.08,
        "y": round(0.08 + 0.035 * (index % 20), 4),
        "width": 0.84,
        "height": 0.03,
        "page": None,
    }


def envelope(name: str, source_id: str, world: str, documents: list) -> dict:
    return {
        "benchmark_file": name,
        "split": K.SPLIT,
        "dataset_version": K.DATASET_VERSION,
        "format_version": K.FORMAT_VERSION,
        "source_id": source_id,
        "world": world,
        "documents": documents,
    }


def dump(path: Path, obj: dict) -> bytes:
    data = (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


# --------------------------------------------------------------------------
# Catalogo
# --------------------------------------------------------------------------
def build_catalog() -> dict[str, dict]:
    entities = [
        {
            "entity_id": eid,
            "world": world,
            "name": name,
            "type": etype,
            "aliases": list(aliases),
            "note": note,
        }
        for eid, world, name, etype, aliases, note in K.ENTITIES
    ]
    catalog = {
        "benchmark_file": "catalog/entities",
        "split": K.SPLIT,
        "dataset_version": K.DATASET_VERSION,
        "worlds": sorted({e[1] for e in K.ENTITIES}),
        "entities": entities,
    }

    def profile(profile_id: str, predicates: list[str]) -> dict:
        doc = {
            "contract_id": "game-profile/v3-internal-v1",
            "contract_version": CONTRACT_VERSION,
            "workspace": K.WORKSPACE,
            "source_asset_id": f"profile:{profile_id}",
            "source_hash": sha256_hash({"profile": profile_id, "split": K.SPLIT}),
            "provider_trace": trace("gold.profile", ["predicates", "entity_types"]),
            "produced_by_step": "gold.profile",
            "profile_id": profile_id,
            "profile_version": "1.0.0",
            "core_ontology_version": K.ONTOLOGY_VERSION,
            "entity_types": ["Character", "Location", "Faction", "Object", "Event", "Concept"],
            "predicates": [p for p in ONTOLOGY if p["predicate"] in predicates],
            "aliases": [],
            "titles": [],
            "factions": [],
            "calendars": [
                {"calendar_id": cid, "epoch_label": label, "units": list(units)}
                for cid, label, units in WORLD_CALENDARS.values()
            ],
            "identity_rules": [],
            "ambiguous_terms": [],
            "source_priorities": [
                {"source_kind": "MARKDOWN", "priority": 60},
                {"source_kind": "AUDIO", "priority": 40},
                {"source_kind": "IMAGE", "priority": 30},
            ],
            "evaluation_examples": [],
            "learned_adapter": None,
            "metadata": {"benchmark": bench_meta("all", "catalog")},
        }
        # `inverse_of` no puede apuntar fuera del perfil.
        known = {p["predicate"] for p in doc["predicates"]}
        for p in doc["predicates"]:
            if p.get("inverse_of") not in known:
                p["inverse_of"] = None
        return doc

    all_preds = [p["predicate"] for p in ONTOLOGY]
    narrow = ["MEMBER_OF", "HAS_MEMBER", "LOCATED_IN", "ALLY_OF"]
    return {
        "catalog/entities.json": catalog,
        "catalog/game_profile_generic.json": envelope(
            "catalog/game_profile_generic", "catalog", "all", [profile("generic", all_preds)]
        ),
        "catalog/game_profile_narrow.json": envelope(
            "catalog/game_profile_narrow", "catalog", "all", [profile("narrow", narrow)]
        ),
    }


#: Ontologia generica (los diez predicados). Copiada del perfil congelado del
#: benchmark: es ONTOLOGIA, no contenido de casos.
ONTOLOGY = [
    {"predicate": "MEMBER_OF", "domain": ["Character"], "range": ["Faction"],
     "symmetric": False, "transitive": False, "functional": False, "inverse_of": "HAS_MEMBER"},
    {"predicate": "HAS_MEMBER", "domain": ["Faction"], "range": ["Character"],
     "symmetric": False, "transitive": False, "functional": False, "inverse_of": "MEMBER_OF"},
    {"predicate": "LEADS", "domain": ["Character"], "range": ["Faction"],
     "symmetric": False, "transitive": False, "functional": True, "inverse_of": "LED_BY"},
    {"predicate": "LED_BY", "domain": ["Faction"], "range": ["Character"],
     "symmetric": False, "transitive": False, "functional": False, "inverse_of": "LEADS"},
    {"predicate": "LOCATED_IN", "domain": ["Character", "Object", "Location", "Event", "Faction"],
     "range": ["Location"], "symmetric": False, "transitive": True, "functional": False,
     "inverse_of": None},
    {"predicate": "ALLY_OF", "domain": ["Character", "Faction"], "range": ["Character", "Faction"],
     "symmetric": True, "transitive": False, "functional": False, "inverse_of": None},
    {"predicate": "RIVAL_OF", "domain": ["Character", "Faction"], "range": ["Character", "Faction"],
     "symmetric": True, "transitive": False, "functional": False, "inverse_of": None},
    {"predicate": "SIBLING_OF", "domain": ["Character"], "range": ["Character"],
     "symmetric": True, "transitive": False, "functional": False, "inverse_of": None},
    {"predicate": "OWNS", "domain": ["Character", "Faction"], "range": ["Object", "Location"],
     "symmetric": False, "transitive": False, "functional": False, "inverse_of": "OWNED_BY"},
    {"predicate": "OWNED_BY", "domain": ["Object", "Location"], "range": ["Character", "Faction"],
     "symmetric": False, "transitive": False, "functional": False, "inverse_of": "OWNS"},
]


# --------------------------------------------------------------------------
# Fuentes
# --------------------------------------------------------------------------
def build_source(src: dict) -> dict[str, dict]:
    sid = src["source_id"]
    world = src["world"]
    cases = [c for c in K.CASES if c["source"] == sid]
    asset_id = f"asset:{sid}"

    texts = [c["text"] for c in cases]
    content_hash = sha256_hash({"source_id": sid, "episodes": texts})

    asset = {
        "contract_id": "source-asset/v3-internal-v1",
        "contract_version": CONTRACT_VERSION,
        "workspace": K.WORKSPACE,
        "source_asset_id": asset_id,
        "source_hash": content_hash,
        "provider_trace": trace("gold.asset", ["content_hash", "original_name"]),
        "produced_by_step": "gold.asset",
        "asset_id": asset_id,
        "collection_id": src["collection_id"],
        "game_profile": "generic",
        "source_kind": src["source_kind"],
        "mime_type": src["mime_type"],
        "content_hash": content_hash,
        "byte_size": sum(len(t.encode("utf-8")) for t in texts),
        "original_name": f"{sid}.bench",
        "original_location": f"bench://negation/{sid}",
        "created_at": CREATED_AT,
        "ingested_at": INGESTED_AT,
        "language_hint": "es",
        "privacy_class": "PUBLIC",
        "copyright_class": "OWN",
        "processing_policy": {
            "allow_external_providers": False,
            "allow_media_persistence": True,
            "retention_days": None,
        },
        "metadata": {"benchmark": bench_meta(world, sid), "title": src["title"]},
    }

    episodes, fragments, mentions, resolutions, claims = [], [], [], [], []
    assertions, negatives, reference = [], [], []
    decisions, operations = [], []
    frag_index = 0

    for i, case in enumerate(cases, start=1):
        ep_id = f"episode:{sid}:e{i:02d}"
        text = case["text"]
        prev_ep = f"episode:{sid}:e{i - 1:02d}" if i > 1 else None
        next_ep = f"episode:{sid}:e{i + 1:02d}" if i < len(cases) else None
        is_asr = src["media_type"] == "ASR_TEXT"
        is_ocr = src["media_type"] == "OCR_TEXT"
        t0 = float((i - 1) * 30)
        t1 = t0 + 28.0

        episode = {
            "contract_id": "source-episode/v3-internal-v1",
            "contract_version": CONTRACT_VERSION,
            "workspace": K.WORKSPACE,
            "source_asset_id": asset_id,
            "source_hash": content_hash,
            "provider_trace": trace("gold.segment", ["text", "content_hash"]),
            "produced_by_step": "gold.segment",
            "episode_id": ep_id,
            "asset_id": asset_id,
            "sequence": i,
            "modality": src["modality"],
            "text": text,
            "page": (1 + (i - 1) // 3) if is_ocr else None,
            "bbox": None,
            "time_start": t0 if is_asr else None,
            "time_end": t1 if is_asr else None,
            "previous_episode_id": prev_ep,
            "next_episode_id": next_ep,
            "quality": {
                "score": 0.72 if case.get("noise") in ("ASR", "OCR") else 0.95,
                "flags": ["TRANSCRIPTION_NOISE"] if case.get("noise") in ("ASR", "OCR") else [],
            },
            "content_hash": sha256_hash({"episode_id": ep_id, "text": text}),
            "metadata": {
                "benchmark": bench_meta(world, sid),
                "phenomena": phenomena_for(case),
                "negation_case_id": case["id"],
            },
        }
        if src["modality"] == "SPEAKER_TURN":
            episode["speaker"] = {
                "speaker_id": f"speaker:{world}:s{(i % 3) + 1}",
                "label": None,
                "confidence": 0.9,
            }
            episode["turn"] = i
        episodes.append(episode)

        reference.append({"episode_id": ep_id, "text": case.get("corrected", text)})

        def make_fragment(literal: str, occurrence: int = 0) -> str:
            nonlocal frag_index
            start, end = find_span(text, literal, occurrence)
            frag_index += 1
            fid = f"fragment:{sid}:e{i:02d}:f{frag_index:03d}"
            fragments.append({
                "contract_id": "evidence-fragment/v3-internal-v1",
                "contract_version": CONTRACT_VERSION,
                "workspace": K.WORKSPACE,
                "source_asset_id": asset_id,
                "source_hash": content_hash,
                "provider_trace": trace("gold.anchor", ["literal_text", "start", "end"]),
                "produced_by_step": "gold.anchor",
                "fragment_id": fid,
                "episode_id": ep_id,
                "literal_text": literal,
                "normalized_text": literal,
                "start": start,
                "end": end,
                "bbox": bbox_for(frag_index) if is_ocr else None,
                "time_start": t0 if is_asr else None,
                "time_end": t1 if is_asr else None,
                "frame_id": None,
                "page": episode["page"],
                "media_type": src["media_type"],
                "confidence": 0.95,
                "metadata": {"benchmark": bench_meta(world, sid)},
            })
            return fid

        # --- menciones -------------------------------------------------
        wanted: list[tuple[str, str]] = []
        for cl in case["claims"]:
            wanted.append(cl["subject"])
            wanted.append(cl["object"])
        wanted += [tuple(m) for m in case.get("extra_mentions", [])]

        seen: dict[tuple[int, int], str] = {}
        mention_of: dict[tuple[str, str], str] = {}
        by_entity: dict[str, list[str]] = {}
        for surface, entity_id in wanted:
            if (surface, entity_id) in mention_of:
                continue
            span = find_span(text, surface)
            if span in seen:
                mention_of[(surface, entity_id)] = seen[span]
                continue
            mid = f"mention:{sid}:e{i:02d}:m{len(mentions) + 1:03d}"
            mfid = make_fragment(surface)
            mentions.append({
                "contract_id": "entity-mention/v3-internal-v1",
                "contract_version": CONTRACT_VERSION,
                "workspace": K.WORKSPACE,
                "source_asset_id": asset_id,
                "source_hash": content_hash,
                "provider_trace": trace("gold.mention", ["surface", "start", "end", "type_candidates"]),
                "produced_by_step": "gold.mention",
                "mention_id": mid,
                "episode_id": ep_id,
                "surface": surface,
                "normalized_surface": canonical_name(entity_id),
                "start": span[0],
                "end": span[1],
                "bbox": bbox_for(len(mentions)) if is_ocr else None,
                "time_start": t0 if is_asr else None,
                "time_end": t1 if is_asr else None,
                "type_candidates": [{"type": ENTITY_TYPE[entity_id], "confidence": 0.93}],
                "confidence": 0.93,
                "coreference_candidates": [],
                "evidence_fragment_ids": [mfid],
                "metadata": {
                    "benchmark": bench_meta(world, sid),
                    "mention_kind": "PROPER_NAME",
                    "surface_degraded": surface != canonical_name(entity_id),
                },
            })
            seen[span] = mid
            mention_of[(surface, entity_id)] = mid
            by_entity.setdefault(entity_id, []).append(mid)

        for entity_id, mids in sorted(by_entity.items()):
            resolutions.append({
                "contract_id": "entity-resolution/v3-internal-v1",
                "contract_version": CONTRACT_VERSION,
                "workspace": K.WORKSPACE,
                "source_asset_id": asset_id,
                "source_hash": content_hash,
                "provider_trace": trace("gold.resolve", ["action", "selected_entity_id"]),
                "produced_by_step": "gold.resolve",
                "resolution_id": f"resolution:{sid}:e{i:02d}:{entity_id.split(':')[-1]}",
                "mention_ids": mids,
                "candidate_entity_ids": [entity_id],
                "selected_entity_id": entity_id,
                "assigned_entity_id": None,
                "action": "LINK_EXISTING",
                "entity_type": ENTITY_TYPE[entity_id],
                "confidence": 0.8 if case.get("orthogonal_risk") == "ENTITY_FUZZY" else 0.95,
                "evidence": [mentions[[m["mention_id"] for m in mentions].index(mids[0])]["evidence_fragment_ids"][0]],
                "reason_codes": ["EXACT_NAME_MATCH"],
                "game_profile": "generic",
                "metadata": {"benchmark": bench_meta(world, sid)},
            })

        # --- claims / decisiones / afirmaciones -------------------------
        if case.get("abstained"):
            afid = make_fragment(case["anchor"])
            claim_id = f"claim:{sid}:e{i:02d}:c1"
            claims.append(claim_doc(
                case, claim_id, ep_id, asset_id, content_hash, world, sid,
                subject_ids=[], object_ids=[], predicate=None, direction=None,
                negated=False, epistemic="UNKNOWN", anchor=case["anchor"],
                fragment_id=afid, abstained=True, cues=[], role="PRIMARY",
            ))
            decisions.append(decision_doc(case, claim_id, afid, None, None, None, None, False, "UNKNOWN"))
            frag_index += 0

        for n, cl in enumerate(case["claims"], start=1):
            afid = make_fragment(cl["anchor"])
            claim_id = f"claim:{sid}:e{i:02d}:c{n}"
            subj_m = mention_of[tuple(cl["subject"])]
            obj_m = mention_of[tuple(cl["object"])]
            claims.append(claim_doc(
                case, claim_id, ep_id, asset_id, content_hash, world, sid,
                subject_ids=[subj_m], object_ids=[obj_m],
                predicate=cl["predicate"], direction=cl["direction"],
                negated=cl["negated"], epistemic=cl["epistemic"], anchor=cl["anchor"],
                fragment_id=afid, abstained=False, cues=cl["epistemic_cues"],
                role=cl["role"], claim_spec=cl,
            ))
            decisions.append(decision_doc(
                case, claim_id, afid, cl["predicate"], cl["direction"],
                cl["subject"][1], cl["object"][1], cl["negated"], cl["epistemic"],
            ))
            if case["decision"] == "AUTO_APPROVE":
                aid = f"assertion:{world}:{case['id'].lower()}-{n}"
                horizon = case.get("knowledge_horizon")
                assertions.append({
                    "contract_id": "fact-assertion/v3-internal-v1",
                    "contract_version": CONTRACT_VERSION,
                    "workspace": K.WORKSPACE,
                    "source_asset_id": asset_id,
                    "source_hash": content_hash,
                    "provider_trace": trace("gold.assert", ["predicate", "direction", "status"]),
                    "produced_by_step": "gold.assert",
                    "assertion_id": aid,
                    "subject_entity_id": cl["subject"][1],
                    "object_entity_id": cl["object"][1],
                    "predicate": cl["predicate"],
                    "direction": cl["direction"],
                    "valid_from": None,
                    "valid_to": horizon,
                    "recorded_at": RECORDED_AT,
                    "epistemic_status": cl["epistemic"],
                    "confidence": 0.9,
                    "status": "ASSERTED",
                    "state": "UNKNOWN" if horizon else "ACTIVE",
                    "event_time": CREATED_AT,
                    "calendar_id": src["calendar_id"],
                    "collection_id": src["collection_id"],
                    "game_profile": "generic",
                    "engine_version": K.ENGINE_VERSION,
                    "ontology_version": K.ONTOLOGY_VERSION,
                    "evidence_fragment_ids": [afid],
                    "episode_ids": [ep_id],
                    "supersedes": None,
                    "superseded_by": None,
                    "negated": cl["negated"],
                    "metadata": {
                        "benchmark": bench_meta(world, sid),
                        "gold_key": fact_key(cl),
                        "phenomena": phenomena_for(case),
                        "negation": {"case_id": case["id"], "family": case["family"],
                                     "knowledge_horizon": horizon},
                    },
                })
                operations.append({
                    "operation_id": f"op:{sid}:{case['id'].lower()}-{n}",
                    "operation_type": "CREATE_ASSERTION",
                    "decision_id": f"decision:{claim_id}",
                    "target_entity_id": None,
                    "assertion_id": aid,
                    "payload": {
                        "subject_entity_id": cl["subject"][1],
                        "object_entity_id": cl["object"][1],
                        "predicate": cl["predicate"],
                        "direction": cl["direction"],
                        "negated": cl["negated"],
                        "valid_from": None,
                        "valid_to": case.get("knowledge_horizon"),
                    },
                    "evidence_fragment_ids": [afid],
                    "idempotency_key": "idem:sha256:" + "0" * 64,
                    "expected_version": None,
                    "expected_hash": None,
                    "expected_state": "WOULD_CREATE",
                })

        if case["family"] == "NO_CLAIM":
            negatives.append({
                "negative_id": f"negative:{sid}:{case['id'].lower()}",
                "split": K.SPLIT,
                "episode_id": ep_id,
                "start": 0,
                "end": len(text),
                "literal_text": text,
                "kind": case["negative_kind"],
                "must_not_produce": case["must_not_produce"],
                "forbidden_predicates": case["forbidden_predicates"],
                "rationale": case["rationale"],
                "case_id": case["id"],
                "family": case["family"],
                "traps": case["traps"],
            })

    plan = {
        "contract_id": "graph-mutation-plan/v3-internal-v1",
        "contract_version": CONTRACT_VERSION,
        "workspace": K.WORKSPACE,
        "source_asset_id": asset_id,
        "source_hash": content_hash,
        "provider_trace": trace("gold.plan", ["decisions", "mutation_operations"]),
        "produced_by_step": "gold.plan",
        "plan_id": f"plan:{sid}:0001",
        "plan_hash": {"algorithm": "sha256", "value": "0" * 64},
        "snapshot_id": f"snapshot:bench:{sid}",
        "engine_version": K.ENGINE_VERSION,
        "ontology_version": K.ONTOLOGY_VERSION,
        "game_profile": "generic",
        "collection_id": src["collection_id"],
        "created_at": PLAN_CREATED_AT,
        "expires_at": PLAN_EXPIRES_AT,
        "decisions": decisions,
        "mutation_operations": operations,
        "local_approval": {
            # NUNCA aprobado: este plan es GOLD, no una aprobacion. Ademas
            # contiene decisiones REVIEW, que por contrato bloquean la aprobacion.
            "approved": False,
            "decision_hash": {"algorithm": "sha256", "value": "0" * 64},
            "validator_chain": [
                {"validator": "structural", "version": K.ENGINE_VERSION, "result": "PASS"},
                {"validator": "semantic", "version": K.ENGINE_VERSION, "result": "PASS"},
                {"validator": "ontology", "version": K.ONTOLOGY_VERSION, "result": "PASS"},
            ],
            "created_at": PLAN_CREATED_AT,
            "signature": None,
            "key_id": None,
            "approved_by": {"provider": "local", "name": "s9k.engine.local", "version": K.ENGINE_VERSION},
        },
        "metadata": {"benchmark": bench_meta(world, sid)},
    }
    plan = seal_plan(plan)

    base = f"sources/{sid}/"
    return {
        base + "source_asset.json": envelope("source_asset", sid, world, [asset]),
        base + "episodes.json": envelope("episodes", sid, world, episodes),
        base + "fragments.json": envelope("fragments", sid, world, fragments),
        base + "mentions.json": envelope("mentions", sid, world, mentions),
        base + "resolutions.json": envelope("resolutions", sid, world, resolutions),
        base + "claims.json": envelope("claims", sid, world, claims),
        base + "assertions.json": envelope("assertions", sid, world, assertions),
        base + "plans.json": envelope("plans", sid, world, [plan]),
        base + "negatives.json": envelope("negatives", sid, world, negatives),
        base + "reference_text.json": envelope("reference_text", sid, world, reference),
    }


def canonical_name(entity_id: str) -> str:
    for eid, _w, name, _t, _a, _n in K.ENTITIES:
        if eid == entity_id:
            return name
    raise KeyError(entity_id)


def fact_key(cl: dict) -> str:
    a, b = cl["subject"][1], cl["object"][1]
    if cl["predicate"] in SYMMETRIC:
        a, b = sorted([a, b])
        direction = "UNDIRECTED"
    else:
        direction = cl["direction"]
    return f"{a}|{cl['predicate']}|{b}|{direction}|{cl['negated']}"


def phenomena_for(case: dict) -> list[str]:
    out = {"NEGATION_BATTERY", case["family"]}
    if case["kind"] != "NONE":
        out.add(case["kind"])
    if case.get("noise") == "OCR":
        out.add("OCR_NOISE")
    if case.get("noise") == "ASR":
        out.add("ASR_NOISE")
    if case.get("scope") == "AMBIGUOUS":
        out.add("AMBIGUOUS_SCOPE")
    if case.get("abstained"):
        out.add("ABSTENTION")
    if case["family"] == "NO_CLAIM":
        out.add(case["negative_kind"])
    return sorted(out)


def negation_annotation(case: dict, cl_index: int | None, cl: dict | None) -> dict:
    ann = {
        "case_id": case["id"],
        "family": case["family"],
        "negation_kind": case["kind"],
        "expected_decision": case["decision"],
        "scope": case["scope"],
        "cue_position": case["cue_position"],
        "voice": case["voice"],
        "verb_form": case["verb_form"],
        "transcription_noise": case["noise"],
        "traps": case["traps"],
        "rationale": case["rationale"],
    }
    for optional in ("reading", "forbidden_outcomes", "knowledge_horizon", "orthogonal_risk"):
        if case.get(optional) is not None:
            ann[optional] = case[optional]
    if cl is not None:
        ann.update({
            "expected_negated": cl["negated"],
            "expected_subject": cl["subject"][1],
            "expected_object": cl["object"][1],
            "expected_predicate": cl["predicate"],
            "expected_direction": cl["direction"],
            "anchor_quote": cl["anchor"],
            "role_in_case": cl["role"],
        })
    else:
        ann.update({
            "expected_negated": None,
            "expected_subject": None,
            "expected_object": None,
            "expected_predicate": None,
            "expected_direction": None,
            "anchor_quote": case.get("anchor"),
            "role_in_case": "PRIMARY",
        })
    return ann


def claim_doc(case, claim_id, ep_id, asset_id, content_hash, world, sid, *,
              subject_ids, object_ids, predicate, direction, negated, epistemic,
              anchor, fragment_id, abstained, cues, role, claim_spec=None) -> dict:
    cl = claim_spec
    return {
        "contract_id": "claim-proposal/v3-internal-v1",
        "contract_version": CONTRACT_VERSION,
        "workspace": K.WORKSPACE,
        "source_asset_id": asset_id,
        "source_hash": content_hash,
        "provider_trace": trace("gold.claim", ["relation_phrase", "predicate_candidates"]),
        "produced_by_step": "gold.claim",
        "claim_id": claim_id,
        "episode_id": ep_id,
        "subject_mentions": subject_ids,
        "relation_phrase": anchor,
        "object_mentions": object_ids,
        "predicate_candidates": [] if abstained else [{"predicate": predicate, "confidence": 0.9}],
        "direction_candidates": [] if abstained else [{"direction": direction, "confidence": 0.9}],
        "temporal_expressions": [],
        "negated": negated,
        "epistemic_cues": list(cues),
        "epistemic_status_hint": epistemic,
        "qualifiers": [],
        "evidence_fragment_ids": [fragment_id],
        "confidence": 0 if abstained else 0.88,
        "alternatives": [],
        "abstained": abstained,
        # El extractor NO decide: la revision la decide el motor (docs/v3/18 §1).
        # Todo el gold sale con review_required=false a proposito.
        "review_required": False,
        "metadata": {
            "benchmark": bench_meta(world, sid),
            "gold_key": f"{case['id']}:{role}",
            "role": "EXTRACTOR_AND_ENGINE",
            "phenomena": phenomena_for(case),
            "negation": negation_annotation(case, None, cl),
        },
    }


def decision_doc(case, claim_id, fragment_id, predicate, direction,
                 subject_entity, object_entity, negated, epistemic) -> dict:
    contract_decision, reasons = K.DECISION_CONTRACT[case["decision"]]
    doc = {
        "decision_id": f"decision:{claim_id}",
        "claim_id": claim_id,
        "decision": contract_decision,
        "predicate": predicate,
        "direction": direction,
        "subject_entity_id": subject_entity,
        "object_entity_id": object_entity,
        "epistemic_status": epistemic,
        "negated": negated,
        "confidence": 0.9 if contract_decision == "ACCEPT" else 0.5,
        "reason_codes": reasons,
        "evidence_fragment_ids": [fragment_id],
    }
    return doc


# --------------------------------------------------------------------------
# Manifiesto
# --------------------------------------------------------------------------
def build(check: bool = False) -> int:
    files: dict[str, dict] = {}
    files.update(build_catalog())
    for src in K.SOURCES:
        files.update(build_source(src))

    totals: dict[str, int] = {}
    per_source = []
    for src in K.SOURCES:
        sid = src["source_id"]
        counts = {
            "episodes": len(files[f"sources/{sid}/episodes.json"]["documents"]),
            "fragments": len(files[f"sources/{sid}/fragments.json"]["documents"]),
            "mentions": len(files[f"sources/{sid}/mentions.json"]["documents"]),
            "resolutions": len(files[f"sources/{sid}/resolutions.json"]["documents"]),
            "claims": len(files[f"sources/{sid}/claims.json"]["documents"]),
            "assertions": len(files[f"sources/{sid}/assertions.json"]["documents"]),
            "plans": len(files[f"sources/{sid}/plans.json"]["documents"]),
            "negatives": len(files[f"sources/{sid}/negatives.json"]["documents"]),
            "decisions": len(files[f"sources/{sid}/plans.json"]["documents"][0]["decisions"]),
            "operations": len(files[f"sources/{sid}/plans.json"]["documents"][0]["mutation_operations"]),
            "cases": len([c for c in K.CASES if c["source"] == sid]),
        }
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
        per_source.append({
            "source_id": sid,
            "world": src["world"],
            "title": src["title"],
            "source_kind": src["source_kind"],
            "modalities": [src["modality"]],
            "description": src["description"],
            "collection_id": src["collection_id"],
            "counts": counts,
            "families": sorted({c["family"] for c in K.CASES if c["source"] == sid}),
        })

    family_counts: dict[str, int] = {}
    for c in K.CASES:
        family_counts[c["family"]] = family_counts.get(c["family"], 0) + 1
    decision_counts: dict[str, int] = {}
    for c in K.CASES:
        decision_counts[c["decision"]] = decision_counts.get(c["decision"], 0) + 1

    phenomena_index: dict[str, list[str]] = {}
    for c in K.CASES:
        for ph in phenomena_for(c):
            phenomena_index.setdefault(ph, []).append(c["id"])

    manifest = {
        "benchmark_file": "manifest",
        "split": K.SPLIT,
        "dataset_version": K.DATASET_VERSION,
        "format_version": K.FORMAT_VERSION,
        "purpose": (
            "Bateria de casos de negacion en espanol para decidir si puede retirarse el "
            "freno universal que hoy manda toda negacion a revision humana "
            "(docs/v3/18). Gold, no medicion: este split NO se ejecuta contra ningun "
            "extractor ni motor en este bloque, y NO esta conectado a ningun flujo "
            "automatico."
        ),
        "independence": {
            "escrito_por": "equipo independiente de la bateria de negaciones",
            "no_leidos": [
                "data-engine/app/knowledge_v3/extraction/cues.py",
                "data-engine/app/knowledge_v3/extraction/deterministic.py",
                "data-engine/app/knowledge_v3/extraction/payload.py",
                "data-engine/app/knowledge_v3/extraction/semantic.py",
                "data-engine/app/tests/test_knowledge_v3_semantic*.py",
                "data-engine/app/tests/test_knowledge_v3_extraction*.py",
            ],
            "no_reutiliza_mundos_de": ["leyenda", "mareas", "kestrel", "ferrovia", "micelio", "liga"],
            "leidos": [
                "contracts/knowledge-v3/v1/ (schemas y validador congelados)",
                "docs/v3/18-politica-de-aprobacion-de-negaciones.md",
                "docs/v3/08-benchmarks.md",
                "estructura (no contenido) de datasets/dev/",
            ],
        },
        "catalog_files": [
            "catalog/entities.json",
            "catalog/game_profile_generic.json",
            "catalog/game_profile_narrow.json",
        ],
        "sources": per_source,
        "totals": totals,
        "family_counts": family_counts,
        "family_quota": {**K.FAMILY_QUOTA, **K.EXTRA_QUOTA},
        "decision_counts": decision_counts,
        "negation_kinds": list(K.NEGATION_KINDS),
        "phenomena_index": {k: sorted(v) for k, v in sorted(phenomena_index.items())},
        "file_hashes": {},
    }

    # Escritura + hashes
    written: dict[str, bytes] = {}
    for rel, obj in sorted(files.items()):
        written[rel] = (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        manifest["file_hashes"][f"{K.SPLIT}/{rel}"] = hashlib.sha256(written[rel]).hexdigest()

    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")

    if check:
        drift = []
        for rel, data in written.items():
            path = ROOT / rel
            if not path.exists() or path.read_bytes() != data:
                drift.append(rel)
        if not (ROOT / "manifest.json").exists() or (ROOT / "manifest.json").read_bytes() != manifest_bytes:
            drift.append("manifest.json")
        if drift:
            print("el dataset ha derivado:", *sorted(drift), sep="\n  ")
            return 1
        print("sin derivas")
        return 0

    for rel, data in written.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (ROOT / "manifest.json").write_bytes(manifest_bytes)

    # Validacion contra los contratos congelados, aqui mismo.
    n = 0
    for rel, obj in files.items():
        for doc in obj.get("documents", []):
            if isinstance(doc, dict) and "contract_id" in doc:
                validate_document(doc)
                n += 1
    print(f"escrito split {K.SPLIT}: {len(written) + 1} ficheros, {n} documentos de contrato validados")
    print(f"casos: {len(K.CASES)} | familias: {family_counts}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    return build(check=args.check)


if __name__ == "__main__":
    sys.exit(main())
