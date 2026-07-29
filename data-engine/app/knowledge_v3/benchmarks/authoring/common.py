# -*- coding: utf-8 -*-
"""Constructor determinista de fuentes gold.

`SourceGold` acumula los documentos de UNA fuente y los emite ya conformes con
los contratos congelados. Todo lo mecanico se calcula:

- los offsets de fragmentos y menciones salen de buscar el texto literal en el
  texto del episodio (`str.index` sobre la ocurrencia pedida);
- los hashes salen de `sha256` sobre una semilla textual estable;
- el envelope (`workspace`, `source_asset_id`, `source_hash`, `provider_trace`,
  `produced_by_step`) se rellena igual en los nueve contratos.

Asi el autor del gold solo escribe lo que de verdad es gold: el texto de la
fuente y la anotacion.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

from ..contracts_bridge import CONTRACT_VERSION, sha256_hash

#: Workspace unico del dataset de benchmarks. El aislamiento por workspace se
#: prueba en seguridad; aqui un solo workspace mantiene el gold legible.
WORKSPACE = "bench-dev"

#: Version del dataset. Va en cada fichero y en cada documento.
DATASET_VERSION = "1.0.0"

#: Perfil de juego activo en el gold.
GAME_PROFILE = "generic"

ENGINE_VERSION = "3.0.0-bench"
ONTOLOGY_VERSION = "core-1.4.0"


def h(seed: str) -> dict[str, str]:
    """Hash determinista y reproducible a partir de una semilla textual."""
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


def find_span(text: str, needle: str, occurrence: int = 0) -> tuple[int, int]:
    """Offsets [start, end) de la `occurrence`-esima aparicion de `needle`.

    Lanza si no aparece: un gold que apunta a un texto inexistente es un gold
    roto, y debe romperse en la generacion, no en el consumo.
    """
    pos = -1
    for _ in range(occurrence + 1):
        pos = text.find(needle, pos + 1)
        if pos < 0:
            raise ValueError(
                f"la ocurrencia {occurrence} de {needle!r} no aparece en el texto del episodio"
            )
    return pos, pos + len(needle)


def normalize_surface(text: str) -> str:
    """Normalizacion minima y explicita: minusculas y espacios colapsados.

    NO quita acentos ni corrige OCR: el gold de correccion de OCR es un dato
    anotado a mano, no el resultado de una heuristica del arnes.
    """
    return " ".join(text.lower().split())


def table_text(table: dict[str, Any]) -> str:
    """Render canonico de una tabla: TSV por filas, cabecera primero.

    Una tabla no tiene offsets propios. Para poder anclar evidencia sobre ella
    hace falta UN render acordado; este es el del dataset y esta documentado en
    docs/v3/08-benchmarks.md. Las celdas nulas se renderizan como cadena vacia.
    """
    lines = []
    header = table.get("header") or []
    if header:
        lines.append("\t".join(header))
    for row in table.get("rows") or []:
        lines.append("\t".join("" if c is None else c for c in row))
    return "\n".join(lines)


def trace(step: str, produced: list[str], provider: str = "local") -> dict[str, Any]:
    """Traza de proveedor del gold. Todo el gold es de autoria local."""
    return {
        "step": step,
        "provider": provider,
        "name": "s9k.benchmarks.gold",
        "version": DATASET_VERSION,
        "model": None,
        "produced": produced,
    }


class SourceGold:
    """Acumulador de la cadena gold completa de UNA fuente."""

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

        #: texto de referencia por episodio: lo que el normalizador DEBERIA
        #: haber extraido. Para OCR es la transcripcion corregida a mano.
        self.reference_text: dict[str, str] = {}
        #: texto sobre el que se calculan los offsets (para TABLE, el render TSV).
        self._anchor_text: dict[str, str] = {}
        self._frag_counter: dict[str, int] = {}
        self._mention_counter: dict[str, int] = {}
        self._claim_counter: dict[str, int] = {}

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
            "original_location": f"benchmarks/dev/{source_id}/{original_name}",
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
            "metadata": self._bench_meta({"title": title, "description": description}),
        }

    # ------------------------------------------------------------------
    # infraestructura
    # ------------------------------------------------------------------
    def _bench_meta(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = {
            "benchmark": {
                "split": "dev",
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

    def _next(self, counters: dict[str, int], key: str) -> int:
        n = counters.get(key, 0)
        counters[key] = n + 1
        return n

    # ------------------------------------------------------------------
    # episodios
    # ------------------------------------------------------------------
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
        quality_score: float = 0.98,
        quality_flags: Iterable[str] = (),
        step: str = "gold.segment",
        phenomena: Iterable[str] = (),
    ) -> str:
        """Anade un episodio y devuelve su `episode_id`."""
        episode_id = f"episode:{self.source_id}:e{seq:02d}"
        previous_id = self.episodes[-1]["episode_id"] if self.episodes else None
        doc = {
            "contract_id": "source-episode/v3-internal-v1",
            **self._envelope(),
            "provider_trace": [trace(step, ["text", "content_hash"])],
            "produced_by_step": step,
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
            "quality": {"score": quality_score, "flags": list(quality_flags)},
            "content_hash": h(f"{episode_id}|{text or ''}"),
            "metadata": self._bench_meta({"phenomena": sorted(phenomena)}),
        }
        if self.episodes:
            self.episodes[-1]["next_episode_id"] = episode_id
        self.episodes.append(doc)
        anchor = text if text is not None else (table_text(table) if table else "")
        self._anchor_text[episode_id] = anchor
        self.reference_text[episode_id] = (
            reference_text if reference_text is not None else anchor
        )
        return episode_id

    # ------------------------------------------------------------------
    # evidencia
    # ------------------------------------------------------------------
    def fragment(
        self,
        episode_id: str,
        literal: str,
        *,
        occurrence: int = 0,
        media_type: str = "EMBEDDED_TEXT",
        bbox: dict[str, Any] | None = None,
        page: int | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        confidence: float = 1.0,
        normalized: str | None = None,
        step: str = "gold.anchor",
    ) -> str:
        start, end = find_span(self._anchor_text[episode_id], literal, occurrence)
        idx = self._next(self._frag_counter, episode_id)
        fragment_id = f"fragment:{episode_id.split(':', 1)[1]}:f{idx:02d}"
        self.fragments.append(
            {
                "contract_id": "evidence-fragment/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace(step, ["literal_text", "start", "end"])],
                "produced_by_step": step,
                "fragment_id": fragment_id,
                "episode_id": episode_id,
                "literal_text": literal,
                "normalized_text": normalized
                if normalized is not None
                else normalize_surface(literal),
                "start": start,
                "end": end,
                "bbox": bbox,
                "time_start": time_start,
                "time_end": time_end,
                "frame_id": None,
                "page": page,
                "media_type": media_type,
                "confidence": confidence,
                "metadata": self._bench_meta(),
            }
        )
        return fragment_id

    # ------------------------------------------------------------------
    # menciones
    # ------------------------------------------------------------------
    def mention(
        self,
        episode_id: str,
        surface: str,
        *,
        entity_type: str,
        occurrence: int = 0,
        normalized: str | None = None,
        coreference: Iterable[str] = (),
        fragment_ids: Iterable[str] | None = None,
        confidence: float = 1.0,
        bbox: dict[str, Any] | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        media_type: str = "EMBEDDED_TEXT",
        page: int | None = None,
        kind: str = "NAME",
        step: str = "gold.mention",
    ) -> str:
        """Anade una mencion (y su fragmento de evidencia, si no se pasa uno).

        `kind` es anotacion del gold, no del contrato: NAME, PRONOUN, NOMINAL,
        SPEAKER_SELF o CELL. Sirve para poder desglosar la correferencia por
        tipo de mencion sin tener que adivinarla del texto.
        """
        start, end = find_span(self._anchor_text[episode_id], surface, occurrence)
        if fragment_ids is None:
            fragment_ids = [
                self.fragment(
                    episode_id,
                    surface,
                    occurrence=occurrence,
                    media_type=media_type,
                    bbox=bbox,
                    page=page,
                    time_start=time_start,
                    time_end=time_end,
                )
            ]
        idx = self._next(self._mention_counter, episode_id)
        mention_id = f"mention:{episode_id.split(':', 1)[1]}:m{idx:02d}"
        self.mentions.append(
            {
                "contract_id": "entity-mention/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace(step, ["surface", "start", "end", "type_candidates"])],
                "produced_by_step": step,
                "mention_id": mention_id,
                "episode_id": episode_id,
                "surface": surface,
                "normalized_surface": normalized
                if normalized is not None
                else normalize_surface(surface),
                "start": start,
                "end": end,
                "bbox": bbox,
                "time_start": time_start,
                "time_end": time_end,
                "type_candidates": [{"type": entity_type, "confidence": 1.0}],
                "confidence": confidence,
                "coreference_candidates": list(coreference),
                "evidence_fragment_ids": list(fragment_ids),
                "metadata": self._bench_meta({"mention_kind": kind}),
            }
        )
        return mention_id

    def link_coreference(self, *mention_ids: str) -> None:
        """Marca un grupo de menciones como correferentes (grafo simetrico)."""
        by_id = {m["mention_id"]: m for m in self.mentions}
        for mid in mention_ids:
            others = [o for o in mention_ids if o != mid]
            cand = by_id[mid]["coreference_candidates"]
            for o in others:
                if o not in cand:
                    cand.append(o)
            cand.sort()

    # ------------------------------------------------------------------
    # resoluciones de identidad
    # ------------------------------------------------------------------
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
        split_groups: Iterable[Iterable[str]] | None = None,
        step: str = "gold.resolve",
    ) -> str:
        mention_ids = list(mention_ids)
        resolution_id = f"resolution:{self.source_id}:{key}"
        evidence = []
        by_id = {m["mention_id"]: m for m in self.mentions}
        for mid in mention_ids:
            for fid in by_id[mid]["evidence_fragment_ids"]:
                if fid not in evidence:
                    evidence.append(fid)
        doc = {
            "contract_id": "entity-resolution/v3-internal-v1",
            **self._envelope(),
            "provider_trace": [trace(step, ["action", "selected_entity_id"])],
            "produced_by_step": step,
            "resolution_id": resolution_id,
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
            "metadata": self._bench_meta(),
        }
        if split_groups is not None:
            doc["split_groups"] = [list(g) for g in split_groups]
        self.resolutions.append(doc)
        return resolution_id

    # ------------------------------------------------------------------
    # claims
    # ------------------------------------------------------------------
    def claim(
        self,
        episode_id: str,
        *,
        key: str,
        subject_mentions: Iterable[str],
        object_mentions: Iterable[str],
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
        confidence: float = 0.95,
        alternatives: Iterable[dict[str, Any]] = (),
        abstained: bool = False,
        review_required: bool = False,
        phenomena: Iterable[str] = (),
        role: str = "EXTRACTOR_AND_ENGINE",
        step: str = "gold.claim",
    ) -> str:
        """Anade un claim gold.

        `role` distingue dos poblaciones que NO son la misma:

        - ``EXTRACTOR_AND_ENGINE`` (por defecto): claim que un buen extractor
          DEBE proponer y que ademas entra al motor.
        - ``ENGINE_ONLY``: propuesta plausible pero incorrecta (p.ej. viola el
          dominio del predicado). No cuenta en la cobertura del extractor —
          exigirla seria pedirle que se equivoque — pero SI es entrada del
          motor, porque sin ella no hay forma de medir `false_reject_rate`.
        """
        if fragment_ids is None:
            fragment_ids = [
                self.fragment(episode_id, relation_phrase, occurrence=relation_occurrence)
            ]
        claim_id = f"claim:{episode_id.split(':', 1)[1]}:c{self._next(self._claim_counter, episode_id):02d}"
        preds = [] if predicate is None else [{"predicate": predicate, "confidence": confidence}]
        self.claims.append(
            {
                "contract_id": "claim-proposal/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace(step, ["predicate_candidates", "relation_phrase"])],
                "produced_by_step": step,
                "claim_id": claim_id,
                "episode_id": episode_id,
                "subject_mentions": list(subject_mentions),
                "relation_phrase": relation_phrase,
                "object_mentions": list(object_mentions),
                "predicate_candidates": preds,
                "direction_candidates": [{"direction": direction, "confidence": confidence}]
                if not abstained
                else [],
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
                "metadata": self._bench_meta(
                    {"gold_key": key, "phenomena": sorted(phenomena), "role": role}
                ),
            }
        )
        return claim_id

    # ------------------------------------------------------------------
    # assertions
    # ------------------------------------------------------------------
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
        recorded_at: str = "2026-07-27T12:00:00Z",
        phenomena: Iterable[str] = (),
        step: str = "gold.assert",
    ) -> str:
        assertion_id = f"assertion:{self.world}:{key}"
        self.assertions.append(
            {
                "contract_id": "fact-assertion/v3-internal-v1",
                **self._envelope(),
                "provider_trace": [trace(step, ["predicate", "direction", "status"])],
                "produced_by_step": step,
                "assertion_id": assertion_id,
                "subject_entity_id": subject_entity_id,
                "object_entity_id": object_entity_id,
                "predicate": predicate,
                "direction": direction,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "recorded_at": recorded_at,
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
                "metadata": self._bench_meta({"gold_key": key, "phenomena": sorted(phenomena)}),
            }
        )
        return assertion_id

    # ------------------------------------------------------------------
    # casos negativos
    # ------------------------------------------------------------------
    def negative(
        self,
        episode_id: str,
        *,
        key: str,
        literal: str,
        kind: str,
        rationale: str,
        forbidden_predicates: Iterable[str] = (),
        occurrence: int = 0,
    ) -> str:
        """Trampa: un tramo que NO debe producir ningun claim.

        No es un contrato V3 (el contrato describe lo que se produce, no lo que
        no se debe producir): es anotacion propia del benchmark, con su propio
        schema local documentado en docs/v3/08-benchmarks.md.
        """
        start, end = find_span(self._anchor_text[episode_id], literal, occurrence)
        negative_id = f"negative:{self.source_id}:{key}"
        self.negatives.append(
            {
                "negative_id": negative_id,
                "split": "dev",
                "episode_id": episode_id,
                "start": start,
                "end": end,
                "literal_text": literal,
                "kind": kind,
                "must_not_produce": "CLAIM",
                "forbidden_predicates": sorted(forbidden_predicates),
                "rationale": rationale,
            }
        )
        return negative_id

    # ------------------------------------------------------------------
    # plan de mutacion
    # ------------------------------------------------------------------
    def plan(
        self,
        *,
        key: str,
        decisions: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        approved: bool,
        created_at: str = "2026-07-27T12:30:00Z",
        expires_at: str = "2026-07-28T12:30:00Z",
        validator_chain: list[dict[str, Any]] | None = None,
        step: str = "gold.plan",
    ) -> dict[str, Any]:
        from ..contracts_bridge import seal_plan

        chain = validator_chain or [
            {"validator": "structural", "version": ENGINE_VERSION, "result": "PASS"},
            {"validator": "semantic", "version": ENGINE_VERSION, "result": "PASS"},
            {"validator": "ontology", "version": ONTOLOGY_VERSION, "result": "PASS"},
        ]
        body = {
            "contract_id": "graph-mutation-plan/v3-internal-v1",
            **self._envelope(),
            "provider_trace": [trace(step, ["decisions", "mutation_operations"])],
            "produced_by_step": step,
            "plan_id": f"plan:{self.source_id}:{key}",
            "plan_hash": h("placeholder"),
            "snapshot_id": f"snapshot:bench:{self.source_id}",
            "engine_version": ENGINE_VERSION,
            "ontology_version": ONTOLOGY_VERSION,
            "game_profile": GAME_PROFILE,
            "collection_id": self.collection_id,
            "created_at": created_at,
            "expires_at": expires_at,
            "decisions": decisions,
            "mutation_operations": operations,
            "local_approval": {
                "approved": approved,
                "decision_hash": h("placeholder"),
                "validator_chain": chain,
                "created_at": created_at,
                "approved_by": {
                    "provider": "local",
                    "name": "s9k.engine.local",
                    "version": ENGINE_VERSION,
                },
            },
            "metadata": self._bench_meta(),
        }
        sealed = seal_plan(body)
        self.plans.append(sealed)
        return sealed


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
    """Decision gold del motor sobre un claim."""
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


def create_assertion_op(
    *,
    key: str,
    decision_id: str,
    assertion_id: str,
    payload: dict[str, Any],
    evidence_fragment_ids: list[str],
    expected_state: str = "WOULD_CREATE",
) -> dict[str, Any]:
    """Operacion de creacion de afirmacion.

    `expected_state="NO_OP"` cubre el caso real de la segunda fuente que dice
    exactamente lo mismo: la operacion existe, es idempotente y no escribe.
    """
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


def supersede_assertion_op(
    *,
    key: str,
    decision_id: str,
    assertion_id: str,
    payload: dict[str, Any],
    evidence_fragment_ids: list[str],
    expected_version: int,
    expected_hash_seed: str,
) -> dict[str, Any]:
    return {
        "operation_id": f"op:{key}",
        "operation_type": "SUPERSEDE_ASSERTION",
        "decision_id": decision_id,
        "target_entity_id": None,
        "assertion_id": assertion_id,
        "payload": payload,
        "evidence_fragment_ids": list(evidence_fragment_ids),
        "idempotency_key": "idem:sha256:" + "0" * 64,
        "expected_state": "WOULD_SUPERSEDE",
        "expected_version": expected_version,
        "expected_hash": h(expected_hash_seed),
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


__all__ = [
    "DATASET_VERSION",
    "ENGINE_VERSION",
    "GAME_PROFILE",
    "ONTOLOGY_VERSION",
    "SourceGold",
    "WORKSPACE",
    "create_assertion_op",
    "create_entity_op",
    "decision",
    "find_span",
    "h",
    "normalize_surface",
    "sha256_hash",
    "supersede_assertion_op",
    "table_text",
    "trace",
]
