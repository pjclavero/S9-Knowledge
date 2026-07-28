# -*- coding: utf-8 -*-
"""Maquinaria de autoria del split HELD-OUT (equipo independiente, dosier §9).

Este modulo NO importa `knowledge_v3.benchmarks.authoring`: el split held-out
se construye con su propia maquinaria para que no herede por accidente ninguna
constante del split de desarrollo (workspace, marca de split, textos, catalogo).
Lo unico que comparte con `dev` es lo que DEBE compartir: los contratos
congelados de `contracts/knowledge-v3/v1` y su validador.

Lo mecanico se calcula (offsets, hashes, sobre); lo que se escribe a mano es lo
unico que de verdad es gold: el texto de cada fuente y su anotacion.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Iterable

#: `data-engine/app` en el path, para poder usar el validador REAL.
APP_DIR = Path(__file__).resolve().parents[5]
if str(APP_DIR) not in sys.path:  # pragma: no cover - trivial
    sys.path.insert(0, str(APP_DIR))

from knowledge_v3.contracts.base import schema_validator as _V  # noqa: E402

seal_plan = _V.seal_plan
validate_document = _V.validate_document
ContractV3Error = _V.ContractV3Error

SPLIT = "heldout"
WORKSPACE = "bench-heldout"
DATASET_VERSION = "1.0.0"
FORMAT_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"
GAME_PROFILE = "generic"
ENGINE_VERSION = "3.0.0-bench"
ONTOLOGY_VERSION = "core-1.4.0"

RECORDED_AT = "2026-07-27T18:00:00Z"
PLAN_CREATED_AT = "2026-07-27T18:30:00Z"
PLAN_EXPIRES_AT = "2026-07-28T18:30:00Z"


def h(seed: str) -> dict[str, str]:
    """Hash determinista a partir de una semilla textual."""
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


def find_span(text: str, needle: str, occurrence: int = 0, context: str | None = None) -> tuple[int, int]:
    """Offsets [start, end) de `needle` en `text`.

    `context` es la defensa contra el error mas silencioso de un gold escrito a
    mano: pedir la enesima aparicion de una superficie corta ("la", "Yo") y
    contarla mal. Con `context` se localiza primero un tramo unico y se busca
    dentro; el indice deja de depender de contar ocurrencias de memoria.
    """
    base = 0
    if context is not None:
        cpos = text.find(context)
        if cpos < 0:
            raise ValueError(f"el contexto {context!r} no aparece en el episodio")
        if text.find(context, cpos + 1) >= 0:
            raise ValueError(f"el contexto {context!r} no es unico en el episodio")
        base = cpos
        text = text[cpos : cpos + len(context)]
    pos = -1
    for _ in range(occurrence + 1):
        pos = text.find(needle, pos + 1)
        if pos < 0:
            raise ValueError(f"la ocurrencia {occurrence} de {needle!r} no aparece en el texto")
    return base + pos, base + pos + len(needle)


def normalize_surface(text: str) -> str:
    """Normalizacion minima y explicita: minusculas y espacios colapsados."""
    return " ".join(text.lower().split())


def table_text(table: dict[str, Any]) -> str:
    """Render canonico TSV (mismo acuerdo documentado en docs/v3/08-benchmarks.md §2.4)."""
    lines = []
    header = table.get("header") or []
    if header:
        lines.append("\t".join(header))
    for row in table.get("rows") or []:
        lines.append("\t".join("" if c is None else c for c in row))
    return "\n".join(lines)


def trace(step: str, produced: list[str]) -> dict[str, Any]:
    return {
        "step": step,
        "provider": "local",
        "name": "s9k.benchmarks.gold.heldout",
        "version": DATASET_VERSION,
        "model": None,
        "produced": produced,
    }


class SourceGold:
    """Cadena gold completa de UNA fuente del split held-out."""

    def __init__(
        self,
        *,
        source_id: str,
        world: str,
        title: str,
        description: str,
        source_kind: str,
        mime_type: str,
        original_name: str,
        byte_size: int,
        created_at: str,
        ingested_at: str,
        privacy_class: str = "INTERNAL",
        copyright_class: str = "OWN",
        language_hint: str | None = "es",
        allow_external_providers: bool = True,
    ) -> None:
        self.source_id = source_id
        self.world = world
        self.title = title
        self.description = description
        self.collection_id = f"collection:{world}"
        self.asset_id = f"asset:{source_id}"
        self.source_hash = h(self.asset_id)

        self.episodes: list[dict[str, Any]] = []
        self.fragments: list[dict[str, Any]] = []
        self.mentions: list[dict[str, Any]] = []
        self.resolutions: list[dict[str, Any]] = []
        self.claims: list[dict[str, Any]] = []
        self.assertions: list[dict[str, Any]] = []
        self.plans: list[dict[str, Any]] = []
        self.negatives: list[dict[str, Any]] = []

        self.reference_text: dict[str, str] = {}
        self._anchor: dict[str, str] = {}
        self._frag_n: dict[str, int] = {}
        self._mention_n: dict[str, int] = {}
        self._claim_n: dict[str, int] = {}
        #: por episodio: bbox/tiempos/media_type por defecto de sus fragmentos.
        self._anchor_defaults: dict[str, dict[str, Any]] = {}

        self.asset = {
            "contract_id": "source-asset/v3-internal-v1",
            "contract_version": CONTRACT_VERSION,
            "workspace": WORKSPACE,
            "source_asset_id": self.asset_id,
            "source_hash": self.source_hash,
            "provider_trace": [trace("gold.ingest", ["content_hash", "byte_size", "mime_type"])],
            "produced_by_step": "gold.ingest",
            "asset_id": self.asset_id,
            "collection_id": self.collection_id,
            "game_profile": GAME_PROFILE,
            "source_kind": source_kind,
            "mime_type": mime_type,
            "content_hash": self.source_hash,
            "byte_size": byte_size,
            "original_name": original_name,
            "original_location": f"benchmarks/heldout/{source_id}/{original_name}",
            "created_at": created_at,
            "ingested_at": ingested_at,
            "language_hint": language_hint,
            "privacy_class": privacy_class,
            "copyright_class": copyright_class,
            "processing_policy": {
                "allow_external_providers": allow_external_providers,
                "allow_media_persistence": True,
                "retention_days": 365,
            },
            "metadata": self._meta({"title": title, "description": description}),
        }

    # -- infraestructura ---------------------------------------------------
    def _meta(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "benchmark": {
                "split": SPLIT,
                "dataset_version": DATASET_VERSION,
                "world": self.world,
                "source_id": self.source_id,
            }
        }
        if extra:
            meta.update(extra)
        return meta

    def _envelope(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "workspace": WORKSPACE,
            "source_asset_id": self.asset_id,
            "source_hash": self.source_hash,
        }

    @staticmethod
    def _next(counters: dict[str, int], key: str) -> int:
        n = counters.get(key, 0)
        counters[key] = n + 1
        return n

    # -- episodios ---------------------------------------------------------
    def episode(
        self,
        *,
        seq: int,
        modality: str,
        text: str | None = None,
        reference_text: str | None = None,
        page: int | None = None,
        bbox: dict[str, Any] | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        speaker: dict[str, Any] | None = None,
        turn: int | None = None,
        table: dict[str, Any] | None = None,
        quality_score: float = 0.97,
        quality_flags: Iterable[str] = (),
        phenomena: Iterable[str] = (),
        fragment_media_type: str = "EMBEDDED_TEXT",
        fragment_bbox: dict[str, Any] | None = None,
        fragment_times: tuple[float, float] | None = None,
    ) -> str:
        episode_id = f"episode:{self.source_id}:e{seq:02d}"
        previous_id = self.episodes[-1]["episode_id"] if self.episodes else None
        doc = {
            "contract_id": "source-episode/v3-internal-v1",
            **self._envelope(),
            "provider_trace": [trace("gold.segment", ["text", "content_hash"])],
            "produced_by_step": "gold.segment",
            "episode_id": episode_id,
            "asset_id": self.asset_id,
            "sequence": seq,
            "modality": modality,
            "text": text,
            "page": page,
            "bbox": bbox,
            "time_start": time_start,
            "time_end": time_end,
            "previous_episode_id": previous_id,
            "next_episode_id": None,
            "speaker": speaker,
            "turn": turn,
            "table": table,
            "quality": {"score": quality_score, "flags": sorted(quality_flags)},
            "content_hash": h(f"{episode_id}|{text or ''}"),
            "metadata": self._meta({"phenomena": sorted(phenomena)}),
        }
        if self.episodes:
            self.episodes[-1]["next_episode_id"] = episode_id
        self.episodes.append(doc)
        anchor = text if text is not None else (table_text(table) if table else "")
        self._anchor[episode_id] = anchor
        self.reference_text[episode_id] = reference_text if reference_text is not None else anchor
        self._anchor_defaults[episode_id] = {
            "media_type": fragment_media_type,
            "bbox": fragment_bbox,
            "page": page,
            "times": fragment_times,
        }
        return episode_id

    def anchor_text(self, episode_id: str) -> str:
        return self._anchor[episode_id]

    # -- evidencia ---------------------------------------------------------
    def fragment(
        self,
        episode_id: str,
        literal: str,
        *,
        occurrence: int = 0,
        context: str | None = None,
        confidence: float = 1.0,
        normalized: str | None = None,
    ) -> str:
        start, end = find_span(self._anchor[episode_id], literal, occurrence, context)
        d = self._anchor_defaults[episode_id]
        idx = self._next(self._frag_n, episode_id)
        fragment_id = f"fragment:{episode_id.split(':', 1)[1]}:f{idx:02d}"
        times = d["times"] or (None, None)
        self.fragments.append(
            {
                "contract_id": "evidence-fragment/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace("gold.anchor", ["literal_text", "start", "end"])],
                "produced_by_step": "gold.anchor",
                "fragment_id": fragment_id,
                "episode_id": episode_id,
                "literal_text": literal,
                "normalized_text": normalized if normalized is not None else normalize_surface(literal),
                "start": start,
                "end": end,
                "bbox": d["bbox"],
                "time_start": times[0],
                "time_end": times[1],
                "frame_id": None,
                "page": d["page"],
                "media_type": d["media_type"],
                "confidence": confidence,
                "metadata": self._meta(),
            }
        )
        return fragment_id

    # -- menciones ---------------------------------------------------------
    def mention(
        self,
        episode_id: str,
        surface: str,
        *,
        entity_type: str | None,
        occurrence: int = 0,
        context: str | None = None,
        normalized: str | None = None,
        confidence: float = 1.0,
        kind: str = "NAME",
    ) -> str:
        start, end = find_span(self._anchor[episode_id], surface, occurrence, context)
        fid = self.fragment(episode_id, surface, occurrence=occurrence, context=context)
        idx = self._next(self._mention_n, episode_id)
        mention_id = f"mention:{episode_id.split(':', 1)[1]}:m{idx:02d}"
        types = [] if entity_type is None else [{"type": entity_type, "confidence": 1.0}]
        self.mentions.append(
            {
                "contract_id": "entity-mention/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace("gold.mention", ["surface", "start", "end", "type_candidates"])],
                "produced_by_step": "gold.mention",
                "mention_id": mention_id,
                "episode_id": episode_id,
                "surface": surface,
                "normalized_surface": normalized if normalized is not None else normalize_surface(surface),
                "start": start,
                "end": end,
                "bbox": self._anchor_defaults[episode_id]["bbox"],
                "time_start": (self._anchor_defaults[episode_id]["times"] or (None, None))[0],
                "time_end": (self._anchor_defaults[episode_id]["times"] or (None, None))[1],
                "type_candidates": types,
                "confidence": confidence,
                "coreference_candidates": [],
                "evidence_fragment_ids": [fid],
                "metadata": self._meta({"mention_kind": kind}),
            }
        )
        return mention_id

    def link_coreference(self, *mention_ids: str) -> None:
        by_id = {m["mention_id"]: m for m in self.mentions}
        for mid in mention_ids:
            cand = by_id[mid]["coreference_candidates"]
            for other in mention_ids:
                if other != mid and other not in cand:
                    cand.append(other)
            cand.sort()

    # -- resoluciones ------------------------------------------------------
    def resolution(
        self,
        *,
        key: str,
        mention_ids: Iterable[str],
        action: str,
        entity_type: str | None,
        selected_entity_id: str | None = None,
        assigned_entity_id: str | None = None,
        candidate_entity_ids: Iterable[str] = (),
        reason_codes: Iterable[str] = ("EXACT_ALIAS",),
        confidence: float = 0.95,
    ) -> str:
        mention_ids = list(mention_ids)
        by_id = {m["mention_id"]: m for m in self.mentions}
        evidence: list[str] = []
        for mid in mention_ids:
            for fid in by_id[mid]["evidence_fragment_ids"]:
                if fid not in evidence:
                    evidence.append(fid)
        doc = {
            "contract_id": "entity-resolution/v3-internal-v1",
            **self._envelope(),
            "provider_trace": [trace("gold.resolve", ["action", "selected_entity_id"])],
            "produced_by_step": "gold.resolve",
            "resolution_id": f"resolution:{self.source_id}:{key}",
            "mention_ids": mention_ids,
            "candidate_entity_ids": list(candidate_entity_ids),
            "selected_entity_id": selected_entity_id,
            "assigned_entity_id": assigned_entity_id,
            "action": action,
            "entity_type": entity_type,
            "confidence": confidence,
            "evidence": evidence,
            "reason_codes": list(reason_codes),
            "game_profile": GAME_PROFILE,
            "metadata": self._meta(),
        }
        self.resolutions.append(doc)
        return doc["resolution_id"]

    def link(self, key: str, mention_ids: Iterable[str], entity_id: str, entity_type: str | None, **kw) -> str:
        """Atajo para el caso mayoritario: enlazar con una entidad del catalogo."""
        return self.resolution(
            key=key,
            mention_ids=mention_ids,
            action="LINK_EXISTING",
            entity_type=entity_type,
            selected_entity_id=entity_id,
            candidate_entity_ids=[entity_id],
            **kw,
        )

    # -- claims ------------------------------------------------------------
    def claim(
        self,
        episode_id: str,
        *,
        key: str,
        subject_mentions: Iterable[str] = (),
        object_mentions: Iterable[str] = (),
        relation_phrase: str,
        predicate: str | None,
        direction: str = "SUBJECT_TO_OBJECT",
        negated: bool = False,
        epistemic: str = "ASSERTED",
        epistemic_cues: Iterable[str] = (),
        temporal_expressions: Iterable[dict[str, Any]] = (),
        qualifiers: Iterable[dict[str, Any]] = (),
        fragment_ids: Iterable[str] | None = None,
        relation_occurrence: int = 0,
        relation_context: str | None = None,
        confidence: float = 0.95,
        alternatives: Iterable[dict[str, Any]] = (),
        abstained: bool = False,
        review_required: bool = False,
        phenomena: Iterable[str] = (),
        role: str = "EXTRACTOR_AND_ENGINE",
    ) -> str:
        if fragment_ids is None:
            fragment_ids = [
                self.fragment(
                    episode_id,
                    relation_phrase,
                    occurrence=relation_occurrence,
                    context=relation_context,
                )
            ]
        claim_id = (
            f"claim:{episode_id.split(':', 1)[1]}:c{self._next(self._claim_n, episode_id):02d}"
        )
        preds = [] if predicate is None else [{"predicate": predicate, "confidence": confidence}]
        self.claims.append(
            {
                "contract_id": "claim-proposal/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace("gold.claim", ["predicate_candidates", "relation_phrase"])],
                "produced_by_step": "gold.claim",
                "claim_id": claim_id,
                "episode_id": episode_id,
                "subject_mentions": list(subject_mentions),
                "relation_phrase": relation_phrase,
                "object_mentions": list(object_mentions),
                "predicate_candidates": preds,
                "direction_candidates": []
                if abstained
                else [{"direction": direction, "confidence": confidence}],
                "temporal_expressions": list(temporal_expressions),
                "negated": negated,
                "epistemic_cues": list(epistemic_cues),
                "epistemic_status_hint": epistemic,
                "qualifiers": list(qualifiers),
                "evidence_fragment_ids": list(fragment_ids),
                "confidence": 0 if abstained else confidence,
                "alternatives": list(alternatives),
                "abstained": abstained,
                "review_required": review_required,
                "metadata": self._meta({"gold_key": key, "phenomena": sorted(phenomena), "role": role}),
            }
        )
        return claim_id

    # -- afirmaciones ------------------------------------------------------
    def assertion(
        self,
        *,
        key: str,
        subject_entity_id: str,
        object_entity_id: str,
        predicate: str,
        episode_ids: Iterable[str],
        evidence_fragment_ids: Iterable[str],
        direction: str = "SUBJECT_TO_OBJECT",
        valid_from: str | None = None,
        valid_to: str | None = None,
        event_time: str | None = None,
        calendar_id: str | None = None,
        epistemic_status: str = "ASSERTED",
        status: str = "ASSERTED",
        state: str = "ACTIVE",
        negated: bool = False,
        confidence: float = 0.9,
        supersedes: str | None = None,
        superseded_by: str | None = None,
        phenomena: Iterable[str] = (),
    ) -> str:
        assertion_id = f"assertion:{self.world}:{key}"
        self.assertions.append(
            {
                "contract_id": "fact-assertion/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace("gold.assert", ["predicate", "direction", "status"])],
                "produced_by_step": "gold.assert",
                "assertion_id": assertion_id,
                "subject_entity_id": subject_entity_id,
                "object_entity_id": object_entity_id,
                "predicate": predicate,
                "direction": direction,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "recorded_at": RECORDED_AT,
                "epistemic_status": epistemic_status,
                "confidence": confidence,
                "status": status,
                "state": state,
                "event_time": event_time,
                "calendar_id": calendar_id,
                "collection_id": self.collection_id,
                "game_profile": GAME_PROFILE,
                "engine_version": ENGINE_VERSION,
                "ontology_version": ONTOLOGY_VERSION,
                "evidence_fragment_ids": list(evidence_fragment_ids),
                "episode_ids": list(episode_ids),
                "supersedes": supersedes,
                "superseded_by": superseded_by,
                "negated": negated,
                "metadata": self._meta({"gold_key": key, "phenomena": sorted(phenomena)}),
            }
        )
        return assertion_id

    # -- casos negativos ---------------------------------------------------
    def negative_span(
        self,
        episode_id: str,
        *,
        key: str,
        literal: str,
        kind: str,
        rationale: str,
        forbidden_predicates: Iterable[str] = (),
        occurrence: int = 0,
        context: str | None = None,
    ) -> str:
        """Tramo que NO debe producir ningun claim (trampa clasica de span)."""
        start, end = find_span(self._anchor[episode_id], literal, occurrence, context)
        negative_id = f"negative:{self.source_id}:{key}"
        self.negatives.append(
            {
                "negative_id": negative_id,
                "split": SPLIT,
                "episode_id": episode_id,
                "start": start,
                "end": end,
                "literal_text": literal,
                "kind": kind,
                "must_not_produce": "CLAIM",
                "forbidden_predicates": sorted(forbidden_predicates),
                "forbidden_subject_mentions": [],
                "forbidden_object_mentions": [],
                "rationale": rationale,
            }
        )
        return negative_id

    def negative_pair(
        self,
        episode_id: str,
        *,
        key: str,
        literal: str,
        kind: str,
        rationale: str,
        subject_mentions: Iterable[str],
        object_mentions: Iterable[str],
        forbidden_predicates: Iterable[str] = (),
        occurrence: int = 0,
        context: str | None = None,
    ) -> str:
        """Trampa de PAR, no de tramo.

        La coordinacion ("X ... y tambien Y ...") y el sujeto-modificador ("el
        hermano de X ...") no se pueden anotar como tramo prohibido: el tramo
        que contiene el par equivocado contiene tambien las menciones del par
        correcto, asi que una trampa de span prohibiria el claim bueno. Lo que
        esta prohibido es UNIR ESAS DOS MENCIONES, y eso es lo que se anota.
        """
        start, end = find_span(self._anchor[episode_id], literal, occurrence, context)
        negative_id = f"negative:{self.source_id}:{key}"
        self.negatives.append(
            {
                "negative_id": negative_id,
                "split": SPLIT,
                "episode_id": episode_id,
                "start": start,
                "end": end,
                "literal_text": literal,
                "kind": kind,
                "must_not_produce": "CLAIM_FOR_PAIR",
                "forbidden_predicates": sorted(forbidden_predicates),
                "forbidden_subject_mentions": sorted(subject_mentions),
                "forbidden_object_mentions": sorted(object_mentions),
                "rationale": rationale,
            }
        )
        return negative_id

    # -- plan --------------------------------------------------------------
    def plan(
        self,
        *,
        key: str,
        decisions: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        approved: bool,
    ) -> dict[str, Any]:
        chain = [
            {"validator": "structural", "version": ENGINE_VERSION, "result": "PASS"},
            {"validator": "semantic", "version": ENGINE_VERSION, "result": "PASS"},
            {"validator": "ontology", "version": ONTOLOGY_VERSION, "result": "PASS"},
        ]
        if not approved:
            chain = chain[:2] + [
                {
                    "validator": "ontology",
                    "version": ONTOLOGY_VERSION,
                    "result": "SKIPPED",
                    "reason_codes": ["REVIEW_PENDING"],
                }
            ]
        body = {
            "contract_id": "graph-mutation-plan/v3-internal-v1",
            **self._envelope(),
            "provider_trace": [trace("gold.plan", ["decisions", "mutation_operations"])],
            "produced_by_step": "gold.plan",
            "plan_id": f"plan:{self.source_id}:{key}",
            "plan_hash": h("placeholder"),
            "snapshot_id": f"snapshot:heldout:{self.source_id}",
            "engine_version": ENGINE_VERSION,
            "ontology_version": ONTOLOGY_VERSION,
            "game_profile": GAME_PROFILE,
            "collection_id": self.collection_id,
            "created_at": PLAN_CREATED_AT,
            "expires_at": PLAN_EXPIRES_AT,
            "decisions": decisions,
            "mutation_operations": operations,
            "local_approval": {
                "approved": approved,
                "decision_hash": h("placeholder"),
                "validator_chain": chain,
                "created_at": PLAN_CREATED_AT,
                "approved_by": {
                    "provider": "local",
                    "name": "s9k.engine.local",
                    "version": ENGINE_VERSION,
                },
            },
            "metadata": self._meta(),
        }
        sealed = seal_plan(body)
        self.plans.append(sealed)
        return sealed


# --------------------------------------------------------------------------
# Decisiones y operaciones
# --------------------------------------------------------------------------
def decision(
    *,
    key: str,
    claim_id: str,
    decision_value: str,
    reason_codes: list[str],
    evidence_fragment_ids: list[str],
    predicate: str | None = None,
    direction: str | None = None,
    subject_entity_id: str | None = None,
    object_entity_id: str | None = None,
    epistemic_status: str | None = None,
    negated: bool | None = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "decision_id": f"decision:{key}",
        "claim_id": claim_id,
        "decision": decision_value,
        "predicate": predicate,
        "direction": direction,
        "subject_entity_id": subject_entity_id,
        "object_entity_id": object_entity_id,
        "confidence": confidence,
        "reason_codes": list(reason_codes),
        "evidence_fragment_ids": list(evidence_fragment_ids),
    }
    if epistemic_status is not None:
        doc["epistemic_status"] = epistemic_status
    if negated is not None:
        doc["negated"] = negated
    return doc


def assertion_payload(assertion: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_entity_id": assertion["subject_entity_id"],
        "predicate": assertion["predicate"],
        "object_entity_id": assertion["object_entity_id"],
        "direction": assertion["direction"],
        "negated": assertion["negated"],
        "epistemic_status": assertion["epistemic_status"],
        "state": assertion["state"],
        "status": assertion["status"],
        "valid_from": assertion["valid_from"],
        "valid_to": assertion["valid_to"],
    }


def create_assertion_op(
    *,
    key: str,
    decision_id: str,
    assertion_id: str,
    payload: dict[str, Any],
    evidence_fragment_ids: list[str],
    expected_state: str = "WOULD_CREATE",
) -> dict[str, Any]:
    return {
        "operation_id": f"op:{key}",
        "operation_type": "CREATE_ASSERTION",
        "decision_id": decision_id,
        "target_entity_id": None,
        "assertion_id": assertion_id,
        "payload": payload,
        "evidence_fragment_ids": list(evidence_fragment_ids),
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": expected_state,
        "expected_version": None,
        "expected_hash": None,
    }


def create_entity_op(
    *,
    key: str,
    decision_id: str,
    target_entity_id: str,
    payload: dict[str, Any],
    evidence_fragment_ids: list[str],
) -> dict[str, Any]:
    return {
        "operation_id": f"op:{key}",
        "operation_type": "CREATE_ENTITY",
        "decision_id": decision_id,
        "target_entity_id": target_entity_id,
        "assertion_id": None,
        "payload": payload,
        "evidence_fragment_ids": list(evidence_fragment_ids),
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": "WOULD_CREATE",
        "expected_version": None,
        "expected_hash": None,
    }
