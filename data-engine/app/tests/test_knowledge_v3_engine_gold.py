# -*- coding: utf-8 -*-
"""Corpus gold PEQUENO del motor local V3 + tests de que el propio gold es gold.

Por que un corpus propio y no el de contratos: el de contratos existe para
ejercitar el SCHEMA (documentos validos e invalidos), y sus offsets, tipos y
entidades no tienen por que ser coherentes entre si. El motor decide sobre la
COHERENCIA entre documentos — que la cita este de verdad en el episodio, que el
tipo de la entidad encaje con el dominio del predicado, que el calendario
exista en el perfil — asi que necesita un corpus donde eso sea cierto por
construccion, y donde romperlo sea un acto deliberado y visible.

Es pequeno a proposito: seis entidades, dos episodios, un perfil. Un corpus
grande esconde los casos; uno pequeno los obliga a estar escritos.

Todos los constructores son deterministas y aceptan `**overrides`: cada test
declara EXACTAMENTE la desviacion que esta probando y hereda el resto.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from knowledge_v3.contracts import (
    ClaimProposal,
    EntityResolution,
    EvidenceFragment,
    GameProfile,
    SourceEpisode,
)
from knowledge_v3.engine import (
    InMemoryGraphSnapshot,
    LocalKnowledgeEngine,
    SnapshotAssertion,
    SnapshotEntity,
)

WORKSPACE = "leyenda"
ASSET_ID = "asset:gold-001"
COLLECTION_ID = "collection:gold"
PROFILE_ID = "generic"
ONTOLOGY = "core-1.4.0"
VERSION = "1.0.0"
NOW = "2026-07-27T10:30:00Z"
SNAPSHOT_ID = "snapshot:gold:0001"

EPISODE_TEXT = "Daiki juro lealtad a la Casa del Ciervo y jamas sirvio al Consejo de Umbra."
EPISODE_ID = "episode:gold-001:p01"
EPISODE_VISUAL_ID = "episode:gold-001:p02"

QUOTE = "Daiki juro lealtad a la Casa del Ciervo"
QUOTE_START = EPISODE_TEXT.index(QUOTE)
QUOTE_END = QUOTE_START + len(QUOTE)

QUOTE_NEG = "jamas sirvio al Consejo de Umbra"
QUOTE_NEG_START = EPISODE_TEXT.index(QUOTE_NEG)
QUOTE_NEG_END = QUOTE_NEG_START + len(QUOTE_NEG)


def h(seed: str) -> dict[str, str]:
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


SOURCE_HASH = h(ASSET_ID)


def trace(step: str, produced: list[str], provider: str = "local", model=None) -> dict[str, Any]:
    return {
        "step": step,
        "provider": provider,
        "name": f"s9k.test.{provider}",
        "version": "3.0.0",
        "model": model,
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
# Perfil
# --------------------------------------------------------------------------
def profile_dict(**overrides: Any) -> dict[str, Any]:
    doc = {
        "contract_id": GameProfile.CONTRACT_ID,
        **envelope(source_asset_id="profile:gold", source_hash=h("profile:gold")),
        "provider_trace": [trace("profile.load", ["predicates"])],
        "produced_by_step": "profile.load",
        "profile_id": PROFILE_ID,
        "profile_version": "1.0.0",
        "core_ontology_version": ONTOLOGY,
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
                "predicate": "ALLY_OF",
                "domain": ["Character", "Faction"],
                "range": ["Character", "Faction"],
                "symmetric": True,
                "transitive": False,
                "functional": False,
                "inverse_of": None,
            },
            {
                "predicate": "LOCATED_IN",
                "domain": ["Character", "Object", "Event", "Location"],
                "range": ["Location"],
                "symmetric": False,
                "transitive": True,
                "functional": True,
                "inverse_of": None,
            },
            {
                "predicate": "OWES_TO",
                "domain": ["Character", "Faction"],
                "range": ["Character", "Faction"],
                "symmetric": False,
                "transitive": False,
                "functional": False,
                "inverse_of": None,
            },
            {
                "predicate": "SERVES",
                "domain": ["Character"],
                "range": ["Faction"],
                "symmetric": False,
                "transitive": False,
                "functional": False,
                "inverse_of": None,
            },
        ],
        "aliases": [],
        "titles": [],
        "factions": ["Casa del Ciervo", "Consejo de Umbra"],
        "calendars": [{"calendar_id": "calendar:umbra", "epoch_label": "Era del Ciervo"}],
        "identity_rules": [],
        "ambiguous_terms": [],
        "source_priorities": [],
        "evaluation_examples": [],
    }
    doc.update(overrides)
    return doc


def profile(**overrides: Any) -> GameProfile:
    return GameProfile.from_dict(profile_dict(**overrides))


# --------------------------------------------------------------------------
# Episodios y evidencia
# --------------------------------------------------------------------------
def episode_dict(**overrides: Any) -> dict[str, Any]:
    doc = {
        "contract_id": SourceEpisode.CONTRACT_ID,
        **envelope(),
        "provider_trace": [trace("pdf.text", ["text"])],
        "produced_by_step": "pdf.text",
        "episode_id": EPISODE_ID,
        "asset_id": ASSET_ID,
        "sequence": 1,
        "modality": "TEXT",
        "text": EPISODE_TEXT,
        "page": 1,
        "bbox": None,
        "time_start": None,
        "time_end": None,
        "previous_episode_id": None,
        "next_episode_id": None,
        "speaker": None,
        "turn": None,
        "table": None,
        "quality": {"score": 0.95, "flags": []},
        "content_hash": h(EPISODE_ID),
    }
    doc.update(overrides)
    return doc


def episode(**overrides: Any) -> SourceEpisode:
    return SourceEpisode.from_dict(episode_dict(**overrides))


def episode_visual(**overrides: Any) -> SourceEpisode:
    doc = episode_dict(
        episode_id=EPISODE_VISUAL_ID,
        sequence=2,
        modality="IMAGE",
        text=None,
        content_hash=h(EPISODE_VISUAL_ID),
    )
    doc.update(overrides)
    return SourceEpisode.from_dict(doc)


def fragment_dict(**overrides: Any) -> dict[str, Any]:
    doc = {
        "contract_id": EvidenceFragment.CONTRACT_ID,
        **envelope(),
        "provider_trace": [trace("anchor", ["literal_text"])],
        "produced_by_step": "anchor",
        "fragment_id": "fragment:gold:0",
        "episode_id": EPISODE_ID,
        "literal_text": QUOTE,
        "normalized_text": QUOTE.lower(),
        "start": QUOTE_START,
        "end": QUOTE_END,
        "bbox": None,
        "time_start": None,
        "time_end": None,
        "frame_id": None,
        "page": 1,
        "media_type": "EMBEDDED_TEXT",
        "confidence": 0.98,
    }
    doc.update(overrides)
    return doc


def fragment(**overrides: Any) -> EvidenceFragment:
    return EvidenceFragment.from_dict(fragment_dict(**overrides))


def fragment_negated(**overrides: Any) -> EvidenceFragment:
    doc = fragment_dict(
        fragment_id="fragment:gold:1",
        literal_text=QUOTE_NEG,
        normalized_text=QUOTE_NEG.lower(),
        start=QUOTE_NEG_START,
        end=QUOTE_NEG_END,
    )
    doc.update(overrides)
    return EvidenceFragment.from_dict(doc)


def fragment_visual(**overrides: Any) -> EvidenceFragment:
    doc = fragment_dict(
        fragment_id="fragment:gold:visual",
        episode_id=EPISODE_VISUAL_ID,
        literal_text="mapa con el estandarte del ciervo sobre la torre",
        normalized_text="mapa con el estandarte del ciervo sobre la torre",
        start=0,
        end=48,
        media_type="MAP",
        bbox={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2, "page": 2},
        page=2,
    )
    doc.update(overrides)
    return EvidenceFragment.from_dict(doc)


# --------------------------------------------------------------------------
# Resoluciones de identidad
# --------------------------------------------------------------------------
def resolution_dict(**overrides: Any) -> dict[str, Any]:
    doc = {
        "contract_id": EntityResolution.CONTRACT_ID,
        **envelope(),
        "provider_trace": [trace("resolve.identity", ["action"])],
        "produced_by_step": "resolve.identity",
        "resolution_id": "resolution:daiki",
        "mention_ids": ["mention:daiki"],
        "candidate_entity_ids": ["entity:daiki"],
        "selected_entity_id": "entity:daiki",
        "assigned_entity_id": None,
        "action": "LINK_EXISTING",
        "entity_type": "Character",
        "confidence": 0.91,
        "evidence": ["fragment:gold:0"],
        "reason_codes": ["EXACT_ALIAS"],
        "game_profile": PROFILE_ID,
    }
    doc.update(overrides)
    return doc


def resolution(**overrides: Any) -> EntityResolution:
    return EntityResolution.from_dict(resolution_dict(**overrides))


def resolution_casa(**overrides: Any) -> EntityResolution:
    doc = resolution_dict(
        resolution_id="resolution:casa",
        mention_ids=["mention:casa"],
        candidate_entity_ids=["entity:casa-ciervo"],
        selected_entity_id="entity:casa-ciervo",
        entity_type="Faction",
        confidence=0.88,
    )
    doc.update(overrides)
    return EntityResolution.from_dict(doc)


def resolution_consejo(**overrides: Any) -> EntityResolution:
    doc = resolution_dict(
        resolution_id="resolution:consejo",
        mention_ids=["mention:consejo"],
        candidate_entity_ids=["entity:consejo-umbra"],
        selected_entity_id="entity:consejo-umbra",
        entity_type="Faction",
        confidence=0.86,
    )
    doc.update(overrides)
    return EntityResolution.from_dict(doc)


def resolution_puerto(**overrides: Any) -> EntityResolution:
    doc = resolution_dict(
        resolution_id="resolution:puerto",
        mention_ids=["mention:puerto"],
        candidate_entity_ids=["entity:puerto-sal"],
        selected_entity_id="entity:puerto-sal",
        entity_type="Location",
        confidence=0.9,
    )
    doc.update(overrides)
    return EntityResolution.from_dict(doc)


def resolution_torre(**overrides: Any) -> EntityResolution:
    doc = resolution_dict(
        resolution_id="resolution:torre",
        mention_ids=["mention:torre"],
        candidate_entity_ids=["entity:torre-umbra"],
        selected_entity_id="entity:torre-umbra",
        entity_type="Location",
        confidence=0.9,
    )
    doc.update(overrides)
    return EntityResolution.from_dict(doc)


DEFAULT_RESOLUTIONS = lambda: [  # noqa: E731 - constructor, no logica
    resolution(),
    resolution_casa(),
    resolution_consejo(),
    resolution_torre(),
]


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def claim_dict(**overrides: Any) -> dict[str, Any]:
    doc = {
        "contract_id": ClaimProposal.CONTRACT_ID,
        **envelope(),
        "provider_trace": [trace("extract.claims", ["predicate_candidates"])],
        "produced_by_step": "extract.claims",
        "claim_id": "claim:gold:0",
        "episode_id": EPISODE_ID,
        "subject_mentions": ["mention:daiki"],
        "relation_phrase": "juro lealtad a",
        "object_mentions": ["mention:casa"],
        "predicate_candidates": [
            {"predicate": "MEMBER_OF", "confidence": 0.82},
            {"predicate": "ALLY_OF", "confidence": 0.20},
        ],
        "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.9}],
        "temporal_expressions": [],
        "negated": False,
        "epistemic_cues": [],
        "epistemic_status_hint": "ASSERTED",
        "qualifiers": [],
        "evidence_fragment_ids": ["fragment:gold:0"],
        "confidence": 0.82,
        "alternatives": [],
        "abstained": False,
        "review_required": False,
    }
    doc.update(overrides)
    return doc


def claim(**overrides: Any) -> ClaimProposal:
    return ClaimProposal.from_dict(claim_dict(**overrides))


def claim_raw(**overrides: Any) -> ClaimProposal:
    """Claim SIN validar contra el contrato.

    Solo para construir entradas deliberadamente invalidas y comprobar que el
    motor las bloquea en vez de decidir sobre ellas.
    """
    return ClaimProposal.from_dict(claim_dict(**overrides), validate=False)


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------
GOLD_ENTITIES = (
    ("entity:daiki", "Character", 3),
    ("entity:casa-ciervo", "Faction", 2),
    ("entity:consejo-umbra", "Faction", 1),
    ("entity:torre-umbra", "Location", 1),
    ("entity:puerto-sal", "Location", 1),
    ("entity:reliquia", "Object", 1),
)


def snapshot(assertions=(), entities=None, **overrides: Any) -> InMemoryGraphSnapshot:
    nodes = [
        SnapshotEntity.of(entity_id, entity_type, version)
        for entity_id, entity_type, version in (entities or GOLD_ENTITIES)
    ]
    return InMemoryGraphSnapshot.build(
        snapshot_id=overrides.get("snapshot_id", SNAPSHOT_ID),
        workspace=overrides.get("workspace", WORKSPACE),
        entities=nodes,
        assertions=assertions,
    )


def vigente(**overrides: Any) -> SnapshotAssertion:
    """Afirmacion vigente en el grafo (por defecto: MEMBER_OF positiva)."""
    base = dict(
        assertion_id="assertion:vigente",
        subject_entity_id="entity:daiki",
        object_entity_id="entity:casa-ciervo",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        negated=False,
        status="ASSERTED",
        state="ACTIVE",
        version=1,
    )
    base.update(overrides)
    return SnapshotAssertion(**base)


# --------------------------------------------------------------------------
# Motor listo para usar
# --------------------------------------------------------------------------
def engine(config=None, **profile_overrides) -> LocalKnowledgeEngine:
    from knowledge_v3.engine import DEFAULT_CONFIG

    return LocalKnowledgeEngine(profile(**profile_overrides), config or DEFAULT_CONFIG)


def run(
    claims=None,
    *,
    resolutions=None,
    fragments=None,
    episodes=None,
    snap=None,
    config=None,
    signals=(),
    now: str = NOW,
    eng=None,
):
    """Corrida estandar del motor sobre el corpus gold."""
    engine_ = eng or engine(config)
    return engine_.run(
        claims=claims if claims is not None else [claim()],
        resolutions=resolutions if resolutions is not None else DEFAULT_RESOLUTIONS(),
        fragments=fragments
        if fragments is not None
        else [fragment(), fragment_negated(), fragment_visual()],
        episodes=episodes if episodes is not None else [episode(), episode_visual()],
        snapshot=snap if snap is not None else snapshot(),
        collection_id=COLLECTION_ID,
        now=now,
        signals=signals,
    )


def only(result):
    """Decision unica de una corrida de un solo claim."""
    assert len(result.decisions) == 1
    return result.decisions[0]


def codes(decision) -> set[str]:
    return set(decision.reason_codes())


# ==========================================================================
# El gold tiene que ser gold: si estas comprobaciones fallan, ningun test del
# motor significa nada, porque estaria midiendo un corpus roto.
# ==========================================================================
def test_gold_documents_validate_against_frozen_contracts():
    for document in (
        profile(),
        episode(),
        episode_visual(),
        fragment(),
        fragment_negated(),
        fragment_visual(),
        claim(),
        *DEFAULT_RESOLUTIONS(),
    ):
        document.validate()


def test_gold_quote_is_really_in_the_episode():
    assert EPISODE_TEXT[QUOTE_START:QUOTE_END] == QUOTE
    assert EPISODE_TEXT[QUOTE_NEG_START:QUOTE_NEG_END] == QUOTE_NEG


def test_gold_snapshot_types_match_the_resolutions():
    snap = snapshot()
    for resolution_ in DEFAULT_RESOLUTIONS():
        node = snap.entity(resolution_.entity_id())
        assert node is not None, resolution_.resolution_id
        assert node.entity_type == resolution_.entity_type


def test_gold_builders_are_deterministic():
    assert claim_dict() == claim_dict()
    assert deepcopy(profile_dict()) == profile_dict()
