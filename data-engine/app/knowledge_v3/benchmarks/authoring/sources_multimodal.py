# -*- coding: utf-8 -*-
"""Las tres fuentes NO textuales del dataset: tabla, transcripcion y escaneo OCR.

Cada una existe para romper una comodidad distinta del pipeline:

- la TABLA no tiene prosa, asi que obliga a anclar evidencia sobre un render
  acordado y a resolver identidad sin contexto sintactico;
- la TRANSCRIPCION tiene hablantes, asi que obliga a resolver el "yo";
- el ESCANEO trae errores de OCR realistas, asi que obliga a distinguir entre
  una variante degradada de un nombre conocido y un nombre que no se conoce.
"""
from __future__ import annotations

from typing import Any

from .common import (
    SourceGold,
    create_assertion_op,
    create_entity_op,
    decision,
)
from .sources_text import _fragment_of

# ==========================================================================
# Fuente 4 — tabla (mundo kestrel): registro de tripulacion
# ==========================================================================
CREW_TABLE: dict[str, Any] = {
    "header": ["Tripulante", "Afiliación", "Puesto", "Ciclo"],
    "rows": [
        ["Nadir Boone", "Consorcio Halcyon", "Sensores", "2387"],
        ["Vania Ostrow", "Consorcio Halcyon", "Operaciones", "2387"],
        ["Ruta Simm", "Cooperativa Vela", "Carga", "2387"],
    ],
}


def build_table() -> SourceGold:
    s = SourceGold(
        source_id="kestrel-tripulacion",
        world="kestrel",
        title="Registro de tripulación del ciclo 2387",
        description="Tabla: contradice al informe, repite un hecho ya conocido y trae un tripulante nuevo.",
        source_kind="TABLE",
        mime_type="text/csv",
        original_name="tripulacion-2387.csv",
        byte_size=512,
        created_at="2026-03-12T06:00:00Z",
        ingested_at="2026-07-20T09:15:00Z",
    )
    e1 = s.episode(
        seq=1,
        modality="TABLE",
        text=None,
        table=CREW_TABLE,
        page=1,
        quality_score=0.99,
        phenomena=["TABLE", "CONFLICT", "DUPLICATE_ACROSS_SOURCES", "NEW_ENTITY"],
    )

    m_nadir = s.mention(e1, "Nadir Boone", entity_type="Character", media_type="TABLE", page=1)
    m_halcyon_1 = s.mention(
        e1, "Consorcio Halcyon", entity_type="Faction", media_type="TABLE", page=1, kind="CELL"
    )
    m_vania = s.mention(e1, "Vania Ostrow", entity_type="Character", media_type="TABLE", page=1)
    m_halcyon_2 = s.mention(
        e1,
        "Consorcio Halcyon",
        entity_type="Faction",
        occurrence=1,
        media_type="TABLE",
        page=1,
        kind="CELL",
    )
    m_ruta = s.mention(e1, "Ruta Simm", entity_type="Character", media_type="TABLE", page=1)
    m_vela = s.mention(
        e1, "Cooperativa Vela", entity_type="Faction", media_type="TABLE", page=1, kind="CELL"
    )
    s.link_coreference(m_halcyon_1, m_halcyon_2)

    c_nadir = s.claim(
        e1,
        key="nadir-member-halcyon",
        subject_mentions=[m_nadir],
        object_mentions=[m_halcyon_1],
        relation_phrase="Nadir Boone\tConsorcio Halcyon",
        predicate="MEMBER_OF",
        temporal_expressions=[
            {
                "text": "2387",
                "kind": "POINT",
                "valid_from": "2387-01-01T00:00:00Z",
                "valid_to": None,
                "calendar_id": "calendar:kestrel",
                "fragment_id": None,
            }
        ],
        phenomena=["TABLE", "CONFLICT"],
    )
    c_vania = s.claim(
        e1,
        key="vania-member-halcyon-dup",
        subject_mentions=[m_vania],
        object_mentions=[m_halcyon_2],
        relation_phrase="Vania Ostrow\tConsorcio Halcyon",
        predicate="MEMBER_OF",
        phenomena=["TABLE", "DUPLICATE_ACROSS_SOURCES"],
    )
    c_ruta = s.claim(
        e1,
        key="ruta-member-vela",
        subject_mentions=[m_ruta],
        object_mentions=[m_vela],
        relation_phrase="Ruta Simm\tCooperativa Vela",
        predicate="MEMBER_OF",
        phenomena=["TABLE", "NEW_ENTITY"],
    )

    s.resolution(
        key="nadir",
        mention_ids=[m_nadir],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:kestrel:nadir",
        candidate_entity_ids=["entity:kestrel:nadir"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="vania",
        mention_ids=[m_vania],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:kestrel:vania",
        candidate_entity_ids=["entity:kestrel:vania"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="halcyon",
        mention_ids=[m_halcyon_1, m_halcyon_2],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:kestrel:halcyon",
        candidate_entity_ids=["entity:kestrel:halcyon", "entity:kestrel:vela"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="vela",
        mention_ids=[m_vela],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:kestrel:vela",
        candidate_entity_ids=["entity:kestrel:vela", "entity:kestrel:halcyon"],
        reason_codes=["EXACT_ALIAS"],
    )
    # Tripulante que el grafo no conoce todavia: se crea, no se fuerza a
    # parecerse a nadie.
    s.resolution(
        key="ruta-simm",
        mention_ids=[m_ruta],
        action="CREATE_NEW",
        entity_type="Character",
        assigned_entity_id="entity:kestrel:ruta-simm",
        candidate_entity_ids=[],
        reason_codes=["NO_CANDIDATE", "TABLE_ROW_SUPPORT"],
        confidence=0.8,
    )

    f_nadir = _fragment_of(s, c_nadir)
    f_vania = _fragment_of(s, c_vania)
    f_ruta = _fragment_of(s, c_ruta)

    s.assertion(
        key="nadir-member-halcyon",
        subject_entity_id="entity:kestrel:nadir",
        object_entity_id="entity:kestrel:halcyon",
        predicate="MEMBER_OF",
        episode_ids=[e1],
        evidence_fragment_ids=[f_nadir],
        epistemic_status="CONFLICTED",
        status="CONTRADICTED",
        state="UNKNOWN",
        valid_from="2387-01-01T00:00:00Z",
        event_time="2387-01-01T00:00:00Z",
        calendar_id="calendar:kestrel",
        confidence=0.5,
        phenomena=["CONFLICT"],
    )
    a_ruta = s.assertion(
        key="ruta-member-vela",
        subject_entity_id="entity:kestrel:ruta-simm",
        object_entity_id="entity:kestrel:vela",
        predicate="MEMBER_OF",
        episode_ids=[e1],
        evidence_fragment_ids=[f_ruta],
        state="ACTIVE",
        status="ASSERTED",
        phenomena=["NEW_ENTITY"],
    )

    d1 = decision(
        key="tabla-0001",
        claim_id=c_nadir,
        decision_value="REVIEW",
        epistemic_status="CONFLICTED",
        negated=False,
        confidence=0.5,
        reason_codes=["CONFLICT_WITH_EXISTING", "SOURCE_DISAGREEMENT"],
        evidence_fragment_ids=[f_nadir],
    )
    d2 = decision(
        key="tabla-0002",
        claim_id=c_vania,
        decision_value="ACCEPT",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:kestrel:vania",
        object_entity_id="entity:kestrel:halcyon",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.95,
        reason_codes=["LOCAL_APPROVED", "ALREADY_KNOWN"],
        evidence_fragment_ids=[f_vania],
    )
    d3 = decision(
        key="tabla-0003",
        claim_id=c_ruta,
        decision_value="ACCEPT",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:kestrel:ruta-simm",
        object_entity_id="entity:kestrel:vela",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.9,
        reason_codes=["LOCAL_APPROVED", "TABLE_ROW_SUPPORT"],
        evidence_fragment_ids=[f_ruta],
    )
    s.plan(
        key="0001",
        approved=False,
        decisions=[d1, d2, d3],
        operations=[
            create_assertion_op(
                key="tabla-0001",
                decision_id=d2["decision_id"],
                assertion_id="assertion:kestrel:vania-member-halcyon",
                payload={
                    "predicate": "MEMBER_OF",
                    "subject_entity_id": "entity:kestrel:vania",
                    "object_entity_id": "entity:kestrel:halcyon",
                },
                evidence_fragment_ids=[f_vania],
                expected_state="NO_OP",
            ),
            create_entity_op(
                key="tabla-0002",
                decision_id=d3["decision_id"],
                target_entity_id="entity:kestrel:ruta-simm",
                payload={"name": "Ruta Simm", "entity_type": "Character"},
                evidence_fragment_ids=[f_ruta],
            ),
            create_assertion_op(
                key="tabla-0003",
                decision_id=d3["decision_id"],
                assertion_id=a_ruta,
                payload={
                    "predicate": "MEMBER_OF",
                    "subject_entity_id": "entity:kestrel:ruta-simm",
                    "object_entity_id": "entity:kestrel:vela",
                },
                evidence_fragment_ids=[f_ruta],
            ),
        ],
        validator_chain=[
            {"validator": "structural", "version": "3.0.0-bench", "result": "PASS"},
            {"validator": "semantic", "version": "3.0.0-bench", "result": "PASS"},
            {
                "validator": "conflict",
                "version": "3.0.0-bench",
                "result": "FAIL",
                "reason_codes": ["CONFLICT_WITH_EXISTING"],
            },
        ],
    )
    return s


# ==========================================================================
# Fuente 5 — transcripcion con hablantes (mundo mareas)
# ==========================================================================
T1 = "Yo nunca he trabajado para la Cofradía de Ámbar, por mucho que lo repitan en el muelle."
T2 = "Mi hermana Sela lleva el taller de Amarra Vieja desde antes de la marea negra."
T3 = (
    "Dicen los estibadores que el Gremio de Faros compró Amarra Vieja el invierno "
    "pasado, pero yo no he visto la escritura."
)

SPEAKER_SELA = {"speaker_id": "speaker:sela", "label": "Sela", "confidence": 0.94}
SPEAKER_TORV = {"speaker_id": "speaker:torv", "label": "Torv", "confidence": 0.91}


def build_transcript() -> SourceGold:
    s = SourceGold(
        source_id="mareas-sesion",
        world="mareas",
        title="Transcripción de sesión en Puerto Quilla",
        description="Turnos de habla con diarizacion: el 'yo' cambia de referente segun quien hable.",
        source_kind="AUDIO",
        mime_type="audio/ogg",
        original_name="sesion-puerto-quilla.ogg",
        byte_size=14_882_301,
        created_at="2026-04-05T19:00:00Z",
        ingested_at="2026-07-20T09:20:00Z",
        privacy_class="PERSONAL_DATA",
        allow_external_providers=False,
    )
    e1 = s.episode(
        seq=1,
        modality="SPEAKER_TURN",
        text=T1,
        speaker=SPEAKER_SELA,
        turn=0,
        time_start=12.0,
        time_end=19.5,
        quality_score=0.86,
        quality_flags=["LOW_SNR"],
        phenomena=["NEGATION", "SPEAKER_COREFERENCE"],
    )
    e2 = s.episode(
        seq=2,
        modality="SPEAKER_TURN",
        text=T2,
        speaker=SPEAKER_TORV,
        turn=1,
        time_start=20.0,
        time_end=27.0,
        quality_score=0.9,
        phenomena=["SYMMETRIC", "SPEAKER_COREFERENCE"],
    )
    e3 = s.episode(
        seq=3,
        modality="SPEAKER_TURN",
        text=T3,
        speaker=SPEAKER_SELA,
        turn=2,
        time_start=28.5,
        time_end=36.0,
        quality_score=0.88,
        phenomena=["RUMOR", "SPEAKER_COREFERENCE"],
    )

    m_yo_1 = s.mention(
        e1,
        "Yo",
        entity_type="Character",
        kind="SPEAKER_SELF",
        media_type="ASR_TEXT",
        time_start=12.0,
        time_end=12.4,
    )
    m_cofradia = s.mention(
        e1,
        "Cofradía de Ámbar",
        entity_type="Faction",
        media_type="ASR_TEXT",
        time_start=14.0,
        time_end=15.2,
    )
    c_sela_neg = s.claim(
        e1,
        key="sela-not-member-cofradia",
        subject_mentions=[m_yo_1],
        object_mentions=[m_cofradia],
        relation_phrase="nunca he trabajado para la Cofradía de Ámbar",
        predicate="MEMBER_OF",
        negated=True,
        epistemic_cues=["nunca"],
        fragment_ids=[
            s.fragment(
                e1,
                "nunca he trabajado para la Cofradía de Ámbar",
                media_type="ASR_TEXT",
                time_start=12.5,
                time_end=15.2,
                confidence=0.86,
            )
        ],
        phenomena=["NEGATION", "SPEAKER_COREFERENCE"],
    )

    m_mi = s.mention(
        e2,
        "Mi",
        entity_type="Character",
        kind="SPEAKER_SELF",
        media_type="ASR_TEXT",
        time_start=20.0,
        time_end=20.3,
    )
    m_sela_2 = s.mention(
        e2,
        "Sela",
        entity_type="Character",
        media_type="ASR_TEXT",
        time_start=20.8,
        time_end=21.4,
    )
    m_amarra_2 = s.mention(
        e2,
        "Amarra Vieja",
        entity_type="Location",
        media_type="ASR_TEXT",
        time_start=23.0,
        time_end=24.1,
    )
    c_hermanos = s.claim(
        e2,
        key="torv-sibling-sela",
        subject_mentions=[m_mi],
        object_mentions=[m_sela_2],
        relation_phrase="Mi hermana Sela",
        predicate="SIBLING_OF",
        direction="UNDIRECTED",
        fragment_ids=[
            s.fragment(
                e2,
                "Mi hermana Sela",
                media_type="ASR_TEXT",
                time_start=20.0,
                time_end=21.4,
                confidence=0.9,
            )
        ],
        phenomena=["SYMMETRIC", "SPEAKER_COREFERENCE"],
    )

    m_gremio = s.mention(
        e3,
        "Gremio de Faros",
        entity_type="Faction",
        media_type="ASR_TEXT",
        time_start=30.0,
        time_end=31.2,
    )
    m_amarra_3 = s.mention(
        e3,
        "Amarra Vieja",
        entity_type="Location",
        media_type="ASR_TEXT",
        time_start=31.6,
        time_end=32.5,
    )
    m_yo_3 = s.mention(
        e3,
        "yo",
        entity_type="Character",
        kind="SPEAKER_SELF",
        media_type="ASR_TEXT",
        time_start=34.0,
        time_end=34.3,
    )
    s.link_coreference(m_yo_1, m_sela_2, m_yo_3)

    c_rumor = s.claim(
        e3,
        key="gremio-owns-amarra-rumor",
        subject_mentions=[m_gremio],
        object_mentions=[m_amarra_3],
        relation_phrase="el Gremio de Faros compró Amarra Vieja el invierno pasado",
        predicate="OWNS",
        epistemic="RUMORED",
        epistemic_cues=["Dicen los estibadores que", "no he visto la escritura"],
        review_required=True,
        confidence=0.45,
        temporal_expressions=[
            {
                "text": "el invierno pasado",
                "kind": "RELATIVE",
                "valid_from": None,
                "valid_to": None,
                "calendar_id": "calendar:mareas",
                "fragment_id": None,
            }
        ],
        fragment_ids=[
            s.fragment(
                e3,
                "el Gremio de Faros compró Amarra Vieja el invierno pasado",
                media_type="ASR_TEXT",
                time_start=29.5,
                time_end=33.0,
                confidence=0.84,
            )
        ],
        phenomena=["RUMOR"],
    )

    s.resolution(
        key="sela",
        mention_ids=[m_yo_1, m_sela_2, m_yo_3],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:mareas:sela",
        candidate_entity_ids=["entity:mareas:sela", "entity:mareas:torv"],
        reason_codes=["SPEAKER_IDENTITY", "EXACT_ALIAS"],
        confidence=0.88,
    )
    s.resolution(
        key="torv",
        mention_ids=[m_mi],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:mareas:torv",
        candidate_entity_ids=["entity:mareas:torv", "entity:mareas:sela"],
        reason_codes=["SPEAKER_IDENTITY"],
        confidence=0.86,
    )
    s.resolution(
        key="cofradia-ambar",
        mention_ids=[m_cofradia],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:mareas:cofradia-ambar",
        candidate_entity_ids=["entity:mareas:cofradia-ambar"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="gremio-faros",
        mention_ids=[m_gremio],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:mareas:gremio-faros",
        candidate_entity_ids=["entity:mareas:gremio-faros"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="amarra-vieja",
        mention_ids=[m_amarra_2, m_amarra_3],
        action="LINK_EXISTING",
        entity_type="Location",
        selected_entity_id="entity:mareas:amarra-vieja",
        candidate_entity_ids=["entity:mareas:amarra-vieja"],
        reason_codes=["EXACT_ALIAS"],
    )

    f_neg = _fragment_of(s, c_sela_neg)
    f_herm = _fragment_of(s, c_hermanos)
    f_rumor = _fragment_of(s, c_rumor)

    a_neg = s.assertion(
        key="sela-not-member-cofradia",
        subject_entity_id="entity:mareas:sela",
        object_entity_id="entity:mareas:cofradia-ambar",
        predicate="MEMBER_OF",
        episode_ids=[e1],
        evidence_fragment_ids=[f_neg],
        negated=True,
        state="ACTIVE",
        status="ASSERTED",
        confidence=0.85,
        phenomena=["NEGATION"],
    )
    a_herm = s.assertion(
        key="torv-sibling-sela",
        subject_entity_id="entity:mareas:torv",
        object_entity_id="entity:mareas:sela",
        predicate="SIBLING_OF",
        direction="UNDIRECTED",
        episode_ids=[e2],
        evidence_fragment_ids=[f_herm],
        state="ACTIVE",
        status="ASSERTED",
        phenomena=["SYMMETRIC"],
    )
    a_rumor = s.assertion(
        key="gremio-owns-amarra-rumor",
        subject_entity_id="entity:mareas:gremio-faros",
        object_entity_id="entity:mareas:amarra-vieja",
        predicate="OWNS",
        episode_ids=[e3],
        evidence_fragment_ids=[f_rumor],
        epistemic_status="RUMORED",
        status="PROVISIONAL",
        state="ACTIVE",
        confidence=0.45,
        phenomena=["RUMOR"],
    )

    d1 = decision(
        key="sesion-0001",
        claim_id=c_sela_neg,
        decision_value="ACCEPT",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:mareas:sela",
        object_entity_id="entity:mareas:cofradia-ambar",
        epistemic_status="ASSERTED",
        negated=True,
        confidence=0.85,
        reason_codes=["LOCAL_APPROVED", "NEGATION_EXPLICIT"],
        evidence_fragment_ids=[f_neg],
    )
    d2 = decision(
        key="sesion-0002",
        claim_id=c_hermanos,
        decision_value="ACCEPT",
        predicate="SIBLING_OF",
        direction="UNDIRECTED",
        subject_entity_id="entity:mareas:torv",
        object_entity_id="entity:mareas:sela",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.9,
        reason_codes=["LOCAL_APPROVED", "SYMMETRIC_PREDICATE"],
        evidence_fragment_ids=[f_herm],
    )
    d3 = decision(
        key="sesion-0003",
        claim_id=c_rumor,
        decision_value="ACCEPT",
        predicate="OWNS",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:mareas:gremio-faros",
        object_entity_id="entity:mareas:amarra-vieja",
        epistemic_status="RUMORED",
        negated=False,
        confidence=0.45,
        reason_codes=["LOCAL_APPROVED_WITH_WARNINGS", "EPISTEMIC_DOWNGRADED"],
        evidence_fragment_ids=[f_rumor],
    )
    s.plan(
        key="0001",
        approved=True,
        decisions=[d1, d2, d3],
        operations=[
            create_assertion_op(
                key="sesion-0001",
                decision_id=d1["decision_id"],
                assertion_id=a_neg,
                payload={
                    "predicate": "MEMBER_OF",
                    "subject_entity_id": "entity:mareas:sela",
                    "object_entity_id": "entity:mareas:cofradia-ambar",
                    "negated": True,
                },
                evidence_fragment_ids=[f_neg],
            ),
            create_assertion_op(
                key="sesion-0002",
                decision_id=d2["decision_id"],
                assertion_id=a_herm,
                payload={
                    "predicate": "SIBLING_OF",
                    "subject_entity_id": "entity:mareas:torv",
                    "object_entity_id": "entity:mareas:sela",
                    "direction": "UNDIRECTED",
                },
                evidence_fragment_ids=[f_herm],
            ),
            create_assertion_op(
                key="sesion-0003",
                decision_id=d3["decision_id"],
                assertion_id=a_rumor,
                payload={
                    "predicate": "OWNS",
                    "subject_entity_id": "entity:mareas:gremio-faros",
                    "object_entity_id": "entity:mareas:amarra-vieja",
                    "epistemic_status": "RUMORED",
                },
                evidence_fragment_ids=[f_rumor],
            ),
        ],
    )
    return s


# ==========================================================================
# Fuente 6 — escaneo con errores de OCR (mundo leyenda)
# ==========================================================================
#: Degradaciones tipicas de un escaneo: rn->m, l->1, o->0, O<->0, li->h.
O1_RAW = "Daiki Oliaru fue nornbrado magistrado de la Casa de1 Ciervo en el año 1O42."
O1_REF = "Daiki Oharu fue nombrado magistrado de la Casa del Ciervo en el año 1042."
O2_RAW = "El escriba V4ndreth firmo el acta junto a1 senescal de Vado A1to."
O2_REF = "El escriba Vandreth firmó el acta junto al senescal de Vado Alto."
O3_CAPTION = "Plano del vado: el recinto de la Casa del Ciervo dentro de Vado Alto."

_BBOX_1 = {"x": 0.08, "y": 0.12, "width": 0.7, "height": 0.05, "page": 1}
_BBOX_2 = {"x": 0.08, "y": 0.31, "width": 0.66, "height": 0.05, "page": 1}
_BBOX_3 = {"x": 0.15, "y": 0.55, "width": 0.55, "height": 0.3, "page": 2}


def build_ocr() -> SourceGold:
    s = SourceGold(
        source_id="leyenda-escaneo",
        world="leyenda",
        title="Escaneo del acta de Vado Alto",
        description="Imagen escaneada: OCR degradado y un plano del que solo cabe inferir.",
        source_kind="IMAGE",
        mime_type="image/png",
        original_name="acta-vado-alto.png",
        byte_size=3_112_004,
        created_at="1042-04-02T00:00:00Z",
        ingested_at="2026-07-20T09:25:00Z",
        copyright_class="UNKNOWN",
    )
    e1 = s.episode(
        seq=1,
        modality="OCR_TEXT",
        text=O1_RAW,
        reference_text=O1_REF,
        page=1,
        bbox=_BBOX_1,
        quality_score=0.62,
        quality_flags=["OCR_DEGRADED"],
        step="gold.ocr",
        phenomena=["OCR_NOISE"],
    )
    e2 = s.episode(
        seq=2,
        modality="OCR_TEXT",
        text=O2_RAW,
        reference_text=O2_REF,
        page=1,
        bbox=_BBOX_2,
        quality_score=0.44,
        quality_flags=["OCR_DEGRADED", "LOW_CONTRAST"],
        step="gold.ocr",
        phenomena=["OCR_NOISE", "PROVISIONAL_ENTITY", "ABSTENTION"],
    )
    e3 = s.episode(
        seq=3,
        modality="DIAGRAM",
        text=O3_CAPTION,
        page=2,
        bbox=_BBOX_3,
        quality_score=0.55,
        step="gold.layout",
        phenomena=["VISUAL_INFERRED"],
    )

    m_daiki = s.mention(
        e1,
        "Daiki Oliaru",
        entity_type="Character",
        normalized="daiki oharu",
        media_type="OCR_TEXT",
        bbox=_BBOX_1,
        page=1,
        confidence=0.71,
    )
    m_casa = s.mention(
        e1,
        "Casa de1 Ciervo",
        entity_type="Faction",
        normalized="casa del ciervo",
        media_type="OCR_TEXT",
        bbox=_BBOX_1,
        page=1,
        confidence=0.69,
    )
    c_ocr = s.claim(
        e1,
        key="daiki-member-casa-ocr",
        subject_mentions=[m_daiki],
        object_mentions=[m_casa],
        relation_phrase="fue nornbrado magistrado de la Casa de1 Ciervo",
        predicate="MEMBER_OF",
        confidence=0.68,
        temporal_expressions=[
            {
                "text": "en el año 1O42",
                "kind": "POINT",
                "valid_from": "1042-01-01T00:00:00Z",
                "valid_to": None,
                "calendar_id": "calendar:leyenda",
                "fragment_id": None,
            }
        ],
        fragment_ids=[
            s.fragment(
                e1,
                "fue nornbrado magistrado de la Casa de1 Ciervo",
                media_type="OCR_TEXT",
                bbox=_BBOX_1,
                page=1,
                confidence=0.66,
                normalized="fue nombrado magistrado de la casa del ciervo",
            )
        ],
        phenomena=["OCR_NOISE"],
    )

    m_vandreth = s.mention(
        e2,
        "V4ndreth",
        entity_type="Character",
        media_type="OCR_TEXT",
        bbox=_BBOX_2,
        page=1,
        confidence=0.38,
    )
    m_vado = s.mention(
        e2,
        "Vado A1to",
        entity_type="Location",
        normalized="vado alto",
        media_type="OCR_TEXT",
        bbox=_BBOX_2,
        page=1,
        confidence=0.61,
    )
    c_abstain = s.claim(
        e2,
        key="acta-abstencion",
        subject_mentions=[],
        object_mentions=[],
        relation_phrase="firmo el acta junto a1 senescal",
        predicate=None,
        abstained=True,
        review_required=True,
        confidence=0,
        fragment_ids=[
            s.fragment(
                e2,
                "firmo el acta junto a1 senescal",
                media_type="OCR_TEXT",
                bbox=_BBOX_2,
                page=1,
                confidence=0.4,
            )
        ],
        phenomena=["ABSTENTION", "OCR_NOISE"],
    )

    m_casa_diagram = s.mention(
        e3,
        "Casa del Ciervo",
        entity_type="Faction",
        media_type="DIAGRAM",
        bbox=_BBOX_3,
        page=2,
        confidence=0.6,
    )
    m_vado_diagram = s.mention(
        e3,
        "Vado Alto",
        entity_type="Location",
        media_type="DIAGRAM",
        bbox=_BBOX_3,
        page=2,
        confidence=0.6,
    )
    c_visual = s.claim(
        e3,
        key="casa-in-vado-visual",
        subject_mentions=[m_casa_diagram],
        object_mentions=[m_vado_diagram],
        relation_phrase="el recinto de la Casa del Ciervo dentro de Vado Alto",
        predicate="LOCATED_IN",
        epistemic="VISUAL_INFERRED",
        review_required=True,
        confidence=0.42,
        fragment_ids=[
            s.fragment(
                e3,
                "el recinto de la Casa del Ciervo dentro de Vado Alto",
                media_type="DIAGRAM",
                bbox=_BBOX_3,
                page=2,
                confidence=0.5,
            )
        ],
        phenomena=["VISUAL_INFERRED"],
    )

    s.resolution(
        key="daiki-ocr",
        mention_ids=[m_daiki],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:leyenda:daiki",
        candidate_entity_ids=["entity:leyenda:daiki", "entity:leyenda:ilaria"],
        reason_codes=["FUZZY_ALIAS", "OCR_DEGRADED_SURFACE"],
        confidence=0.72,
    )
    s.resolution(
        key="casa-ocr",
        mention_ids=[m_casa, m_casa_diagram],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:leyenda:casa-ciervo",
        candidate_entity_ids=["entity:leyenda:casa-ciervo"],
        reason_codes=["FUZZY_ALIAS", "OCR_DEGRADED_SURFACE"],
        confidence=0.74,
    )
    s.resolution(
        key="vado-ocr",
        mention_ids=[m_vado, m_vado_diagram],
        action="LINK_EXISTING",
        entity_type="Location",
        selected_entity_id="entity:leyenda:vado-alto",
        candidate_entity_ids=["entity:leyenda:vado-alto"],
        reason_codes=["FUZZY_ALIAS", "OCR_DEGRADED_SURFACE"],
        confidence=0.7,
    )
    # Trampa deliberada: 'V4ndreth' se PARECE a Ilaria Vandreth, pero una
    # superficie degradada no basta para fundir identidades. El gold exige
    # entidad provisional, no enlace.
    s.resolution(
        key="v4ndreth-provisional",
        mention_ids=[m_vandreth],
        action="CREATE_PROVISIONAL",
        entity_type=None,
        assigned_entity_id="entity:prov:leyenda:v4ndreth",
        candidate_entity_ids=["entity:leyenda:ilaria"],
        reason_codes=["OCR_DEGRADED_SURFACE", "LOW_SUPPORT"],
        confidence=0.31,
    )

    f_ocr = _fragment_of(s, c_ocr)
    f_abstain = _fragment_of(s, c_abstain)
    f_visual = _fragment_of(s, c_visual)

    a_ocr = s.assertion(
        key="daiki-member-casa",
        subject_entity_id="entity:leyenda:daiki",
        object_entity_id="entity:leyenda:casa-ciervo",
        predicate="MEMBER_OF",
        episode_ids=[e1],
        evidence_fragment_ids=[f_ocr],
        valid_from="1042-01-01T00:00:00Z",
        event_time="1042-01-01T00:00:00Z",
        calendar_id="calendar:leyenda",
        state="ACTIVE",
        status="ASSERTED",
        confidence=0.68,
        phenomena=["OCR_NOISE"],
    )

    d1 = decision(
        key="escaneo-0001",
        claim_id=c_ocr,
        decision_value="ACCEPT",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:leyenda:daiki",
        object_entity_id="entity:leyenda:casa-ciervo",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.68,
        reason_codes=["LOCAL_APPROVED_WITH_WARNINGS", "OCR_DEGRADED_SURFACE"],
        evidence_fragment_ids=[f_ocr],
    )
    d2 = decision(
        key="escaneo-0002",
        claim_id=c_abstain,
        decision_value="ABSTAIN",
        confidence=0,
        reason_codes=["INSUFFICIENT_EVIDENCE", "LOW_QUALITY_EPISODE"],
        evidence_fragment_ids=[f_abstain],
    )
    d3 = decision(
        key="escaneo-0003",
        claim_id=c_visual,
        decision_value="REVIEW",
        epistemic_status="VISUAL_INFERRED",
        negated=False,
        confidence=0.42,
        reason_codes=["REVIEW_EVIDENCE", "VISUAL_INFERRED"],
        evidence_fragment_ids=[f_visual],
    )
    s.plan(
        key="0001",
        approved=False,
        decisions=[d1, d2, d3],
        operations=[
            create_assertion_op(
                key="escaneo-0001",
                decision_id=d1["decision_id"],
                assertion_id=a_ocr,
                payload={
                    "predicate": "MEMBER_OF",
                    "subject_entity_id": "entity:leyenda:daiki",
                    "object_entity_id": "entity:leyenda:casa-ciervo",
                },
                evidence_fragment_ids=[f_ocr],
            )
        ],
        validator_chain=[
            {"validator": "structural", "version": "3.0.0-bench", "result": "PASS"},
            {"validator": "semantic", "version": "3.0.0-bench", "result": "PASS"},
            {
                "validator": "visual",
                "version": "3.0.0-bench",
                "result": "FAIL",
                "reason_codes": ["VISUAL_INFERRED"],
            },
        ],
    )
    return s


__all__ = ["build_ocr", "build_table", "build_transcript"]
