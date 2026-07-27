# -*- coding: utf-8 -*-
"""Las tres fuentes de texto/markdown del dataset, una por mundo.

Tres mundos deliberadamente lejanos entre si (corte medieval, archipielago
gremial, estaciones orbitales) y tres registros de escritura distintos
(cronica, nota de campo, informe administrativo). Ninguna frase repite la
formulacion de otra: si el mismo fenomeno se dice siempre igual, medir deja de
distinguir entre entender y memorizar.
"""
from __future__ import annotations

from typing import Any

from .common import (
    SourceGold,
    create_assertion_op,
    decision,
    h,
    supersede_assertion_op,
)

# ==========================================================================
# Mundo 1 — "leyenda": cronica de corte
# ==========================================================================
L1 = (
    "Ilaria Vandreth dirigió la Casa del Ciervo desde el invierno de 1041 hasta la "
    "caída de Vado Alto. Cuando entregó el bastón de mando, el cargo recayó en Daiki "
    "Oharu, que lo conserva desde la primavera de 1042."
)
L2 = (
    "Daiki Oharu ha negado en cada asamblea su pertenencia al Consejo de Umbra. "
    "El magistrado repitió la negativa incluso ante los emisarios llegados de Umbra."
)
L3 = (
    "Corre el rumor de que la Casa del Ciervo y el Consejo de Umbra firmaron un pacto "
    "secreto la noche de la última luna; nadie ha visto el documento. En la farsa que "
    "los titiriteros representaron en la plaza, el ciervo degollaba al búho. ¿Llegó "
    "Ilaria Vandreth a jurar lealtad al Consejo de Umbra?"
)


def build_leyenda() -> SourceGold:
    s = SourceGold(
        source_id="leyenda-cronica",
        world="leyenda",
        title="Crónica de la Casa del Ciervo",
        description="Markdown de cronica: sucesion de cargos, negacion explicita y rumor.",
        source_kind="MARKDOWN",
        mime_type="text/markdown",
        original_name="cronica-casa-del-ciervo.md",
        byte_size=len((L1 + L2 + L3).encode("utf-8")),
        created_at="2026-01-14T08:00:00Z",
        ingested_at="2026-07-20T09:00:00Z",
    )

    e1 = s.episode(seq=1, modality="TEXT", text=L1, page=1, phenomena=["TEMPORALITY", "SUPERSESSION"])
    e2 = s.episode(seq=2, modality="TEXT", text=L2, page=1, phenomena=["NEGATION", "COREFERENCE"])
    e3 = s.episode(
        seq=3,
        modality="TEXT",
        text=L3,
        page=2,
        phenomena=["RUMOR", "SYMMETRIC", "FICTION_WITHIN_FICTION", "QUESTION"],
    )

    # --- episodio 1: sucesion en el cargo (supersesion temporal) -----------
    m_ilaria_1 = s.mention(e1, "Ilaria Vandreth", entity_type="Character", page=1)
    m_casa_1 = s.mention(e1, "Casa del Ciervo", entity_type="Faction", page=1)
    m_vado_1 = s.mention(e1, "Vado Alto", entity_type="Location", page=1)
    m_daiki_1 = s.mention(e1, "Daiki Oharu", entity_type="Character", page=1)

    c_ilaria_leads = s.claim(
        e1,
        key="ilaria-leads-casa",
        subject_mentions=[m_ilaria_1],
        object_mentions=[m_casa_1],
        relation_phrase="dirigió la Casa del Ciervo desde el invierno de 1041",
        predicate="LEADS",
        temporal_expressions=[
            {
                "text": "desde el invierno de 1041 hasta la caída de Vado Alto",
                "kind": "INTERVAL",
                "valid_from": "1041-12-01T00:00:00Z",
                "valid_to": "1042-03-20T00:00:00Z",
                "calendar_id": "calendar:leyenda",
                "fragment_id": None,
            }
        ],
        phenomena=["TEMPORALITY"],
    )
    c_daiki_leads = s.claim(
        e1,
        key="daiki-leads-casa",
        subject_mentions=[m_daiki_1],
        object_mentions=[m_casa_1],
        relation_phrase="el cargo recayó en Daiki Oharu",
        predicate="LEADS",
        temporal_expressions=[
            {
                "text": "desde la primavera de 1042",
                "kind": "POINT",
                "valid_from": "1042-03-21T00:00:00Z",
                "valid_to": None,
                "calendar_id": "calendar:leyenda",
                "fragment_id": None,
            }
        ],
        phenomena=["TEMPORALITY", "SUPERSESSION"],
    )

    # --- episodio 2: negacion y correferencia nominal ----------------------
    m_daiki_2 = s.mention(e2, "Daiki Oharu", entity_type="Character", page=1)
    m_consejo_2 = s.mention(e2, "Consejo de Umbra", entity_type="Faction", page=1)
    m_magistrado = s.mention(
        e2, "El magistrado", entity_type="Character", kind="NOMINAL", page=1
    )
    s.link_coreference(m_daiki_2, m_magistrado)

    c_daiki_no_consejo = s.claim(
        e2,
        key="daiki-not-member-consejo",
        subject_mentions=[m_daiki_2],
        object_mentions=[m_consejo_2],
        relation_phrase="ha negado en cada asamblea su pertenencia al Consejo de Umbra",
        predicate="MEMBER_OF",
        negated=True,
        epistemic_cues=["ha negado"],
        phenomena=["NEGATION"],
    )

    # --- episodio 3: rumor simetrico, ficcion y pregunta -------------------
    m_casa_3 = s.mention(e3, "Casa del Ciervo", entity_type="Faction", page=2)
    m_consejo_3 = s.mention(e3, "Consejo de Umbra", entity_type="Faction", page=2)
    m_ilaria_3 = s.mention(e3, "Ilaria Vandreth", entity_type="Character", page=2)
    m_consejo_3b = s.mention(
        e3, "Consejo de Umbra", entity_type="Faction", occurrence=1, page=2
    )
    s.link_coreference(m_consejo_3, m_consejo_3b)

    c_pacto = s.claim(
        e3,
        key="casa-ally-consejo-rumor",
        subject_mentions=[m_casa_3],
        object_mentions=[m_consejo_3],
        relation_phrase="firmaron un pacto secreto la noche de la última luna",
        predicate="ALLY_OF",
        direction="UNDIRECTED",
        epistemic="RUMORED",
        epistemic_cues=["Corre el rumor de que"],
        review_required=True,
        confidence=0.55,
        phenomena=["RUMOR", "SYMMETRIC"],
    )

    s.negative(
        e3,
        key="farsa-titiriteros",
        literal="En la farsa que los titiriteros representaron en la plaza, el ciervo degollaba al búho.",
        kind="FICTION_WITHIN_FICTION",
        rationale=(
            "Lo narrado ocurre dentro de una representacion teatral: no es un hecho del "
            "mundo, por mucho que la frase tenga sujeto, verbo y objeto."
        ),
        forbidden_predicates=["RIVAL_OF"],
    )
    s.negative(
        e3,
        key="pregunta-lealtad",
        literal="¿Llegó Ilaria Vandreth a jurar lealtad al Consejo de Umbra?",
        kind="QUESTION",
        rationale=(
            "Una pregunta no afirma nada. Las menciones si existen; la relacion, no."
        ),
        forbidden_predicates=["ALLY_OF", "MEMBER_OF"],
    )

    # --- identidad ---------------------------------------------------------
    s.resolution(
        key="daiki",
        mention_ids=[m_daiki_1, m_daiki_2, m_magistrado],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:leyenda:daiki",
        candidate_entity_ids=["entity:leyenda:daiki", "entity:leyenda:ilaria"],
        reason_codes=["EXACT_ALIAS", "TITLE_SUPPORTED"],
    )
    s.resolution(
        key="ilaria",
        mention_ids=[m_ilaria_1, m_ilaria_3],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:leyenda:ilaria",
        candidate_entity_ids=["entity:leyenda:ilaria", "entity:leyenda:daiki"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="casa-ciervo",
        mention_ids=[m_casa_1, m_casa_3],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:leyenda:casa-ciervo",
        candidate_entity_ids=["entity:leyenda:casa-ciervo"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="consejo-umbra",
        mention_ids=[m_consejo_2, m_consejo_3, m_consejo_3b],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:leyenda:consejo-umbra",
        candidate_entity_ids=["entity:leyenda:consejo-umbra"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="vado-alto",
        mention_ids=[m_vado_1],
        action="LINK_EXISTING",
        entity_type="Location",
        selected_entity_id="entity:leyenda:vado-alto",
        candidate_entity_ids=["entity:leyenda:vado-alto"],
        reason_codes=["EXACT_ALIAS"],
    )

    # --- ledger ------------------------------------------------------------
    f_ilaria = _fragment_of(s, c_ilaria_leads)
    f_daiki = _fragment_of(s, c_daiki_leads)
    f_neg = _fragment_of(s, c_daiki_no_consejo)
    f_pacto = _fragment_of(s, c_pacto)

    a_ilaria = s.assertion(
        key="ilaria-leads-casa",
        subject_entity_id="entity:leyenda:ilaria",
        object_entity_id="entity:leyenda:casa-ciervo",
        predicate="LEADS",
        episode_ids=[e1],
        evidence_fragment_ids=[f_ilaria],
        valid_from="1041-12-01T00:00:00Z",
        valid_to="1042-03-20T00:00:00Z",
        event_time="1041-12-01T00:00:00Z",
        calendar_id="calendar:leyenda",
        state="ENDED",
        status="SUPERSEDED",
        superseded_by="assertion:leyenda:daiki-leads-casa",
        phenomena=["TEMPORALITY", "SUPERSESSION"],
    )
    a_daiki = s.assertion(
        key="daiki-leads-casa",
        subject_entity_id="entity:leyenda:daiki",
        object_entity_id="entity:leyenda:casa-ciervo",
        predicate="LEADS",
        episode_ids=[e1],
        evidence_fragment_ids=[f_daiki],
        valid_from="1042-03-21T00:00:00Z",
        event_time="1042-03-21T00:00:00Z",
        calendar_id="calendar:leyenda",
        state="ACTIVE",
        status="ASSERTED",
        supersedes=a_ilaria,
        phenomena=["TEMPORALITY", "SUPERSESSION"],
    )
    a_neg = s.assertion(
        key="daiki-not-member-consejo",
        subject_entity_id="entity:leyenda:daiki",
        object_entity_id="entity:leyenda:consejo-umbra",
        predicate="MEMBER_OF",
        episode_ids=[e2],
        evidence_fragment_ids=[f_neg],
        negated=True,
        state="ACTIVE",
        status="ASSERTED",
        phenomena=["NEGATION"],
    )
    a_pacto = s.assertion(
        key="casa-ally-consejo-rumor",
        subject_entity_id="entity:leyenda:casa-ciervo",
        object_entity_id="entity:leyenda:consejo-umbra",
        predicate="ALLY_OF",
        direction="UNDIRECTED",
        episode_ids=[e3],
        evidence_fragment_ids=[f_pacto],
        epistemic_status="RUMORED",
        status="PROVISIONAL",
        state="ACTIVE",
        confidence=0.55,
        phenomena=["RUMOR", "SYMMETRIC"],
    )

    d1 = decision(
        key="leyenda-0001",
        claim_id=c_ilaria_leads,
        decision_value="ACCEPT",
        predicate="LEADS",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:leyenda:ilaria",
        object_entity_id="entity:leyenda:casa-ciervo",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.9,
        reason_codes=["LOCAL_APPROVED", "EVIDENCE_LITERAL"],
        evidence_fragment_ids=[f_ilaria],
    )
    d2 = decision(
        key="leyenda-0002",
        claim_id=c_daiki_leads,
        decision_value="ACCEPT",
        predicate="LEADS",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:leyenda:daiki",
        object_entity_id="entity:leyenda:casa-ciervo",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.9,
        reason_codes=["LOCAL_APPROVED", "FUNCTIONAL_PREDICATE_SUPERSEDES"],
        evidence_fragment_ids=[f_daiki],
    )
    d3 = decision(
        key="leyenda-0003",
        claim_id=c_daiki_no_consejo,
        decision_value="ACCEPT",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:leyenda:daiki",
        object_entity_id="entity:leyenda:consejo-umbra",
        epistemic_status="ASSERTED",
        negated=True,
        confidence=0.88,
        reason_codes=["LOCAL_APPROVED", "NEGATION_EXPLICIT"],
        evidence_fragment_ids=[f_neg],
    )
    d4 = decision(
        key="leyenda-0004",
        claim_id=c_pacto,
        decision_value="ACCEPT",
        predicate="ALLY_OF",
        direction="UNDIRECTED",
        subject_entity_id="entity:leyenda:casa-ciervo",
        object_entity_id="entity:leyenda:consejo-umbra",
        epistemic_status="RUMORED",
        negated=False,
        confidence=0.55,
        reason_codes=["LOCAL_APPROVED_WITH_WARNINGS", "EPISTEMIC_DOWNGRADED"],
        evidence_fragment_ids=[f_pacto],
    )

    s.plan(
        key="0001",
        approved=True,
        decisions=[d1, d2, d3, d4],
        operations=[
            create_assertion_op(
                key="leyenda-0001",
                decision_id=d1["decision_id"],
                assertion_id=a_ilaria,
                payload={
                    "predicate": "LEADS",
                    "subject_entity_id": "entity:leyenda:ilaria",
                    "object_entity_id": "entity:leyenda:casa-ciervo",
                    "valid_from": "1041-12-01T00:00:00Z",
                },
                evidence_fragment_ids=[f_ilaria],
            ),
            create_assertion_op(
                key="leyenda-0002",
                decision_id=d2["decision_id"],
                assertion_id=a_daiki,
                payload={
                    "predicate": "LEADS",
                    "subject_entity_id": "entity:leyenda:daiki",
                    "object_entity_id": "entity:leyenda:casa-ciervo",
                    "valid_from": "1042-03-21T00:00:00Z",
                },
                evidence_fragment_ids=[f_daiki],
            ),
            supersede_assertion_op(
                key="leyenda-0003",
                decision_id=d2["decision_id"],
                assertion_id=a_ilaria,
                payload={"superseded_by": a_daiki, "valid_to": "1042-03-20T00:00:00Z"},
                evidence_fragment_ids=[f_daiki],
                expected_version=1,
                expected_hash_seed="state:assertion:leyenda:ilaria-leads-casa:v1",
            ),
            create_assertion_op(
                key="leyenda-0004",
                decision_id=d3["decision_id"],
                assertion_id=a_neg,
                payload={
                    "predicate": "MEMBER_OF",
                    "subject_entity_id": "entity:leyenda:daiki",
                    "object_entity_id": "entity:leyenda:consejo-umbra",
                    "negated": True,
                },
                evidence_fragment_ids=[f_neg],
            ),
            create_assertion_op(
                key="leyenda-0005",
                decision_id=d4["decision_id"],
                assertion_id=a_pacto,
                payload={
                    "predicate": "ALLY_OF",
                    "subject_entity_id": "entity:leyenda:casa-ciervo",
                    "object_entity_id": "entity:leyenda:consejo-umbra",
                    "epistemic_status": "RUMORED",
                },
                evidence_fragment_ids=[f_pacto],
            ),
        ],
    )
    return s


# ==========================================================================
# Mundo 2 — "mareas": archipielago gremial
# ==========================================================================
M1 = (
    "El Gremio de Faros y la Cofradía de Ámbar llevan enfrentados desde la marea negra; "
    "ninguna de las dos casas acepta ya el arbitraje del puerto."
)
M2 = (
    "Sela Marrec nació en Amarra Vieja, un barrio de Puerto Quilla, y allí conserva "
    "todavía su taller de ámbar."
)
M3 = (
    "Si Torv Marrec dirigiera hoy la Cofradía de Ámbar, la flota no habría zarpado con "
    "la marea de invierno. El maestre de puerto, en cambio, planea entregar a Torv el "
    "bastón de la Cofradía de Ámbar en el próximo ciclo."
)


def build_mareas() -> SourceGold:
    s = SourceGold(
        source_id="mareas-cuaderno",
        world="mareas",
        title="Cuaderno de puerto de Puerto Quilla",
        description="Nota de campo: rivalidad simetrica, contencion espacial e hipotesis.",
        source_kind="MARKDOWN",
        mime_type="text/markdown",
        original_name="cuaderno-puerto-quilla.md",
        byte_size=len((M1 + M2 + M3).encode("utf-8")),
        created_at="2026-02-02T10:00:00Z",
        ingested_at="2026-07-20T09:05:00Z",
    )
    e1 = s.episode(seq=1, modality="TEXT", text=M1, page=1, phenomena=["SYMMETRIC"])
    e2 = s.episode(seq=2, modality="TEXT", text=M2, page=1, phenomena=["COREFERENCE", "TRANSITIVE"])
    e3 = s.episode(seq=3, modality="TEXT", text=M3, page=2, phenomena=["COUNTERFACTUAL", "HYPOTHETICAL"])

    m_gremio = s.mention(e1, "Gremio de Faros", entity_type="Faction", page=1)
    m_cofradia_1 = s.mention(e1, "Cofradía de Ámbar", entity_type="Faction", page=1)
    c_rival = s.claim(
        e1,
        key="gremio-rival-cofradia",
        subject_mentions=[m_gremio],
        object_mentions=[m_cofradia_1],
        relation_phrase="llevan enfrentados desde la marea negra",
        predicate="RIVAL_OF",
        direction="UNDIRECTED",
        temporal_expressions=[
            {
                "text": "desde la marea negra",
                "kind": "RELATIVE",
                "valid_from": None,
                "valid_to": None,
                "calendar_id": "calendar:mareas",
                "fragment_id": None,
            }
        ],
        phenomena=["SYMMETRIC"],
    )

    m_sela = s.mention(e2, "Sela Marrec", entity_type="Character", page=1)
    m_amarra = s.mention(e2, "Amarra Vieja", entity_type="Location", page=1)
    m_quilla = s.mention(e2, "Puerto Quilla", entity_type="Location", page=1)
    m_alli = s.mention(e2, "allí", entity_type="Location", kind="PRONOUN", page=1)
    s.link_coreference(m_amarra, m_alli)

    c_barrio = s.claim(
        e2,
        key="amarra-in-quilla",
        subject_mentions=[m_amarra],
        object_mentions=[m_quilla],
        relation_phrase="un barrio de Puerto Quilla",
        predicate="LOCATED_IN",
        phenomena=["TRANSITIVE"],
    )

    m_torv_1 = s.mention(e3, "Torv Marrec", entity_type="Character", page=2)
    m_cofradia_2 = s.mention(e3, "Cofradía de Ámbar", entity_type="Faction", page=2)
    m_torv_2 = s.mention(e3, "Torv", entity_type="Character", occurrence=1, page=2)
    m_cofradia_3 = s.mention(
        e3, "Cofradía de Ámbar", entity_type="Faction", occurrence=1, page=2
    )
    s.link_coreference(m_torv_1, m_torv_2)
    s.link_coreference(m_cofradia_2, m_cofradia_3)

    s.negative(
        e3,
        key="condicional-torv",
        literal=(
            "Si Torv Marrec dirigiera hoy la Cofradía de Ámbar, la flota no habría "
            "zarpado con la marea de invierno."
        ),
        kind="COUNTERFACTUAL",
        rationale=(
            "Condicional contrafactual: describe un mundo que no ocurrio. Aceptarlo "
            "escribiria en el grafo justo lo contrario de lo que dice el texto."
        ),
        forbidden_predicates=["LEADS"],
    )

    c_plan = s.claim(
        e3,
        key="torv-leads-cofradia-plan",
        subject_mentions=[m_torv_2],
        object_mentions=[m_cofradia_3],
        relation_phrase="planea entregar a Torv el bastón de la Cofradía de Ámbar en el próximo ciclo",
        predicate="LEADS",
        epistemic="HYPOTHETICAL",
        epistemic_cues=["planea"],
        review_required=True,
        confidence=0.5,
        temporal_expressions=[
            {
                "text": "en el próximo ciclo",
                "kind": "RELATIVE",
                "valid_from": None,
                "valid_to": None,
                "calendar_id": "calendar:mareas",
                "fragment_id": None,
            }
        ],
        phenomena=["HYPOTHETICAL", "TEMPORALITY"],
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
        key="cofradia-ambar",
        mention_ids=[m_cofradia_1, m_cofradia_2, m_cofradia_3],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:mareas:cofradia-ambar",
        candidate_entity_ids=["entity:mareas:cofradia-ambar"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="sela",
        mention_ids=[m_sela],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:mareas:sela",
        candidate_entity_ids=["entity:mareas:sela", "entity:mareas:torv"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="amarra-vieja",
        mention_ids=[m_amarra, m_alli],
        action="LINK_EXISTING",
        entity_type="Location",
        selected_entity_id="entity:mareas:amarra-vieja",
        candidate_entity_ids=["entity:mareas:amarra-vieja", "entity:mareas:puerto-quilla"],
        reason_codes=["EXACT_ALIAS", "COREFERENCE_RESOLVED"],
    )
    s.resolution(
        key="puerto-quilla",
        mention_ids=[m_quilla],
        action="LINK_EXISTING",
        entity_type="Location",
        selected_entity_id="entity:mareas:puerto-quilla",
        candidate_entity_ids=["entity:mareas:puerto-quilla"],
        reason_codes=["EXACT_ALIAS"],
    )
    s.resolution(
        key="torv",
        mention_ids=[m_torv_1, m_torv_2],
        action="LINK_EXISTING",
        entity_type="Character",
        selected_entity_id="entity:mareas:torv",
        candidate_entity_ids=["entity:mareas:torv", "entity:mareas:sela"],
        reason_codes=["EXACT_ALIAS"],
    )

    f_rival = _fragment_of(s, c_rival)
    f_barrio = _fragment_of(s, c_barrio)
    f_plan = _fragment_of(s, c_plan)

    a_rival = s.assertion(
        key="gremio-rival-cofradia",
        subject_entity_id="entity:mareas:gremio-faros",
        object_entity_id="entity:mareas:cofradia-ambar",
        predicate="RIVAL_OF",
        direction="UNDIRECTED",
        episode_ids=[e1],
        evidence_fragment_ids=[f_rival],
        calendar_id="calendar:mareas",
        state="ACTIVE",
        status="ASSERTED",
        phenomena=["SYMMETRIC"],
    )
    a_barrio = s.assertion(
        key="amarra-in-quilla",
        subject_entity_id="entity:mareas:amarra-vieja",
        object_entity_id="entity:mareas:puerto-quilla",
        predicate="LOCATED_IN",
        episode_ids=[e2],
        evidence_fragment_ids=[f_barrio],
        state="ACTIVE",
        status="ASSERTED",
        phenomena=["TRANSITIVE"],
    )
    a_plan = s.assertion(
        key="torv-leads-cofradia-plan",
        subject_entity_id="entity:mareas:torv",
        object_entity_id="entity:mareas:cofradia-ambar",
        predicate="LEADS",
        episode_ids=[e3],
        evidence_fragment_ids=[f_plan],
        epistemic_status="HYPOTHETICAL",
        status="PROVISIONAL",
        state="PLANNED",
        confidence=0.5,
        calendar_id="calendar:mareas",
        phenomena=["HYPOTHETICAL"],
    )

    d1 = decision(
        key="mareas-0001",
        claim_id=c_rival,
        decision_value="ACCEPT",
        predicate="RIVAL_OF",
        direction="UNDIRECTED",
        subject_entity_id="entity:mareas:gremio-faros",
        object_entity_id="entity:mareas:cofradia-ambar",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.9,
        reason_codes=["LOCAL_APPROVED", "SYMMETRIC_PREDICATE"],
        evidence_fragment_ids=[f_rival],
    )
    d2 = decision(
        key="mareas-0002",
        claim_id=c_barrio,
        decision_value="ACCEPT",
        predicate="LOCATED_IN",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:mareas:amarra-vieja",
        object_entity_id="entity:mareas:puerto-quilla",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.92,
        reason_codes=["LOCAL_APPROVED", "EVIDENCE_LITERAL"],
        evidence_fragment_ids=[f_barrio],
    )
    d3 = decision(
        key="mareas-0003",
        claim_id=c_plan,
        decision_value="ACCEPT",
        predicate="LEADS",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:mareas:torv",
        object_entity_id="entity:mareas:cofradia-ambar",
        epistemic_status="HYPOTHETICAL",
        negated=False,
        confidence=0.5,
        reason_codes=["LOCAL_APPROVED_WITH_WARNINGS", "EPISTEMIC_DOWNGRADED"],
        evidence_fragment_ids=[f_plan],
    )
    s.plan(
        key="0001",
        approved=True,
        decisions=[d1, d2, d3],
        operations=[
            create_assertion_op(
                key="mareas-0001",
                decision_id=d1["decision_id"],
                assertion_id=a_rival,
                payload={
                    "predicate": "RIVAL_OF",
                    "subject_entity_id": "entity:mareas:gremio-faros",
                    "object_entity_id": "entity:mareas:cofradia-ambar",
                    "direction": "UNDIRECTED",
                },
                evidence_fragment_ids=[f_rival],
            ),
            create_assertion_op(
                key="mareas-0002",
                decision_id=d2["decision_id"],
                assertion_id=a_barrio,
                payload={
                    "predicate": "LOCATED_IN",
                    "subject_entity_id": "entity:mareas:amarra-vieja",
                    "object_entity_id": "entity:mareas:puerto-quilla",
                },
                evidence_fragment_ids=[f_barrio],
            ),
            create_assertion_op(
                key="mareas-0003",
                decision_id=d3["decision_id"],
                assertion_id=a_plan,
                payload={
                    "predicate": "LEADS",
                    "subject_entity_id": "entity:mareas:torv",
                    "object_entity_id": "entity:mareas:cofradia-ambar",
                    "state": "PLANNED",
                },
                evidence_fragment_ids=[f_plan],
            ),
        ],
    )
    return s


# ==========================================================================
# Mundo 3 — "kestrel": estaciones orbitales
# ==========================================================================
K1 = (
    "Vania Ostrow figura como jefa de operaciones del Consorcio Halcyon a bordo de la "
    "Estación Kestrel."
)
K2 = (
    "El informe de tripulación del ciclo 2387 no incluye a Nadir Boone entre el "
    "personal del Consorcio Halcyon."
)
K3 = (
    "En el serial que emiten los turnos de noche, Halcyon vende la estación a una flota "
    "pirata; el guionista lo inventó todo. Se rumorea, en cambio, que el Núcleo Bruma "
    "pertenece al Consorcio Halcyon desde el traslado."
)


def build_kestrel() -> SourceGold:
    s = SourceGold(
        source_id="kestrel-informe",
        world="kestrel",
        title="Informe de estación Kestrel",
        description="Informe administrativo: negacion documental, ficcion emitida y rumor.",
        source_kind="MARKDOWN",
        mime_type="text/markdown",
        original_name="informe-kestrel.md",
        byte_size=len((K1 + K2 + K3).encode("utf-8")),
        created_at="2026-03-11T07:30:00Z",
        ingested_at="2026-07-20T09:10:00Z",
    )
    e1 = s.episode(seq=1, modality="TEXT", text=K1, page=1)
    e2 = s.episode(seq=2, modality="TEXT", text=K2, page=1, phenomena=["NEGATION", "CONFLICT"])
    e3 = s.episode(
        seq=3,
        modality="TEXT",
        text=K3,
        page=2,
        phenomena=["FICTION_WITHIN_FICTION", "RUMOR", "ONTOLOGY_VIOLATION"],
    )

    m_vania = s.mention(e1, "Vania Ostrow", entity_type="Character", page=1)
    m_halcyon_1 = s.mention(e1, "Consorcio Halcyon", entity_type="Faction", page=1)
    m_estacion = s.mention(e1, "Estación Kestrel", entity_type="Location", page=1)
    c_vania_member = s.claim(
        e1,
        key="vania-member-halcyon",
        subject_mentions=[m_vania],
        object_mentions=[m_halcyon_1],
        relation_phrase="figura como jefa de operaciones del Consorcio Halcyon",
        predicate="MEMBER_OF",
    )
    c_vania_located = s.claim(
        e1,
        key="vania-in-kestrel",
        subject_mentions=[m_vania],
        object_mentions=[m_estacion],
        relation_phrase="a bordo de la Estación Kestrel",
        predicate="LOCATED_IN",
    )

    m_nadir = s.mention(e2, "Nadir Boone", entity_type="Character", page=1)
    m_halcyon_2 = s.mention(e2, "Consorcio Halcyon", entity_type="Faction", page=1)
    c_nadir_neg = s.claim(
        e2,
        key="nadir-not-member-halcyon",
        subject_mentions=[m_nadir],
        object_mentions=[m_halcyon_2],
        relation_phrase="no incluye a Nadir Boone entre el personal del Consorcio Halcyon",
        predicate="MEMBER_OF",
        negated=True,
        epistemic_cues=["no incluye"],
        temporal_expressions=[
            {
                "text": "del ciclo 2387",
                "kind": "POINT",
                "valid_from": "2387-01-01T00:00:00Z",
                "valid_to": None,
                "calendar_id": "calendar:kestrel",
                "fragment_id": None,
            }
        ],
        phenomena=["NEGATION", "CONFLICT"],
    )

    m_halcyon_fic = s.mention(e3, "Halcyon", entity_type="Faction", page=2)
    m_estacion_fic = s.mention(
        e3, "la estación", entity_type="Location", kind="NOMINAL", page=2
    )
    m_nucleo = s.mention(e3, "Núcleo Bruma", entity_type="Object", page=2)
    m_halcyon_3 = s.mention(e3, "Consorcio Halcyon", entity_type="Faction", page=2)
    s.link_coreference(m_halcyon_fic, m_halcyon_3)

    s.negative(
        e3,
        key="serial-nocturno",
        literal=(
            "En el serial que emiten los turnos de noche, Halcyon vende la estación a "
            "una flota pirata"
        ),
        kind="FICTION_WITHIN_FICTION",
        rationale=(
            "Ficcion emitida dentro del mundo. Las entidades son reales; la "
            "transaccion, no. El propio texto lo desmiente en la frase siguiente."
        ),
        forbidden_predicates=["OWNS", "OWNED_BY"],
    )

    c_nucleo = s.claim(
        e3,
        key="nucleo-owned-by-halcyon",
        subject_mentions=[m_nucleo],
        object_mentions=[m_halcyon_3],
        relation_phrase="pertenece al Consorcio Halcyon desde el traslado",
        predicate="OWNED_BY",
        epistemic="RUMORED",
        epistemic_cues=["Se rumorea"],
        review_required=True,
        confidence=0.48,
        phenomena=["RUMOR"],
    )
    # Propuesta plausible pero INCORRECTA: MEMBER_OF exige un Character como
    # sujeto. Existe para que el motor tenga algo que rechazar; no se le pide
    # al extractor que la produzca.
    c_ontologia = s.claim(
        e3,
        key="nucleo-member-halcyon-invalido",
        subject_mentions=[m_nucleo],
        object_mentions=[m_halcyon_3],
        relation_phrase="pertenece al Consorcio Halcyon",
        predicate="MEMBER_OF",
        confidence=0.31,
        role="ENGINE_ONLY",
        phenomena=["ONTOLOGY_VIOLATION"],
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
        mention_ids=[m_halcyon_1, m_halcyon_2, m_halcyon_fic, m_halcyon_3],
        action="LINK_EXISTING",
        entity_type="Faction",
        selected_entity_id="entity:kestrel:halcyon",
        candidate_entity_ids=["entity:kestrel:halcyon", "entity:kestrel:vela"],
        reason_codes=["EXACT_ALIAS", "SHORT_FORM_ALIAS"],
    )
    s.resolution(
        key="estacion",
        mention_ids=[m_estacion, m_estacion_fic],
        action="LINK_EXISTING",
        entity_type="Location",
        selected_entity_id="entity:kestrel:estacion",
        candidate_entity_ids=["entity:kestrel:estacion"],
        reason_codes=["EXACT_ALIAS", "COREFERENCE_RESOLVED"],
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
        key="nucleo-bruma",
        mention_ids=[m_nucleo],
        action="LINK_EXISTING",
        entity_type="Object",
        selected_entity_id="entity:kestrel:nucleo-bruma",
        candidate_entity_ids=["entity:kestrel:nucleo-bruma"],
        reason_codes=["EXACT_ALIAS"],
    )

    f_member = _fragment_of(s, c_vania_member)
    f_located = _fragment_of(s, c_vania_located)
    f_neg = _fragment_of(s, c_nadir_neg)
    f_nucleo = _fragment_of(s, c_nucleo)
    f_onto = _fragment_of(s, c_ontologia)

    a_member = s.assertion(
        key="vania-member-halcyon",
        subject_entity_id="entity:kestrel:vania",
        object_entity_id="entity:kestrel:halcyon",
        predicate="MEMBER_OF",
        episode_ids=[e1],
        evidence_fragment_ids=[f_member],
        state="ACTIVE",
        status="ASSERTED",
    )
    a_located = s.assertion(
        key="vania-in-kestrel",
        subject_entity_id="entity:kestrel:vania",
        object_entity_id="entity:kestrel:estacion",
        predicate="LOCATED_IN",
        episode_ids=[e1],
        evidence_fragment_ids=[f_located],
        state="ACTIVE",
        status="ASSERTED",
    )
    # El conflicto NO se resuelve en el ledger: se registra en los dos sentidos.
    s.assertion(
        key="nadir-not-member-halcyon",
        subject_entity_id="entity:kestrel:nadir",
        object_entity_id="entity:kestrel:halcyon",
        predicate="MEMBER_OF",
        episode_ids=[e2],
        evidence_fragment_ids=[f_neg],
        negated=True,
        epistemic_status="CONFLICTED",
        status="CONTRADICTED",
        state="UNKNOWN",
        valid_from="2387-01-01T00:00:00Z",
        event_time="2387-01-01T00:00:00Z",
        calendar_id="calendar:kestrel",
        confidence=0.5,
        phenomena=["NEGATION", "CONFLICT"],
    )
    a_nucleo = s.assertion(
        key="nucleo-owned-by-halcyon",
        subject_entity_id="entity:kestrel:nucleo-bruma",
        object_entity_id="entity:kestrel:halcyon",
        predicate="OWNED_BY",
        episode_ids=[e3],
        evidence_fragment_ids=[f_nucleo],
        epistemic_status="RUMORED",
        status="PROVISIONAL",
        state="ACTIVE",
        confidence=0.48,
        phenomena=["RUMOR"],
    )

    d1 = decision(
        key="kestrel-0001",
        claim_id=c_vania_member,
        decision_value="ACCEPT",
        predicate="MEMBER_OF",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:kestrel:vania",
        object_entity_id="entity:kestrel:halcyon",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.93,
        reason_codes=["LOCAL_APPROVED", "EVIDENCE_LITERAL"],
        evidence_fragment_ids=[f_member],
    )
    d2 = decision(
        key="kestrel-0002",
        claim_id=c_vania_located,
        decision_value="ACCEPT",
        predicate="LOCATED_IN",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:kestrel:vania",
        object_entity_id="entity:kestrel:estacion",
        epistemic_status="ASSERTED",
        negated=False,
        confidence=0.9,
        reason_codes=["LOCAL_APPROVED"],
        evidence_fragment_ids=[f_located],
    )
    d3 = decision(
        key="kestrel-0003",
        claim_id=c_nadir_neg,
        decision_value="REVIEW",
        epistemic_status="CONFLICTED",
        negated=True,
        confidence=0.5,
        reason_codes=["CONFLICT_WITH_EXISTING", "SOURCE_DISAGREEMENT"],
        evidence_fragment_ids=[f_neg],
    )
    d4 = decision(
        key="kestrel-0004",
        claim_id=c_nucleo,
        decision_value="ACCEPT",
        predicate="OWNED_BY",
        direction="SUBJECT_TO_OBJECT",
        subject_entity_id="entity:kestrel:nucleo-bruma",
        object_entity_id="entity:kestrel:halcyon",
        epistemic_status="RUMORED",
        negated=False,
        confidence=0.48,
        reason_codes=["LOCAL_APPROVED_WITH_WARNINGS", "EPISTEMIC_DOWNGRADED"],
        evidence_fragment_ids=[f_nucleo],
    )
    d5 = decision(
        key="kestrel-0005",
        claim_id=c_ontologia,
        decision_value="REJECT_INVALID",
        confidence=0.31,
        reason_codes=["TYPE_INCOMPATIBLE"],
        evidence_fragment_ids=[f_onto],
    )

    s.plan(
        key="0001",
        approved=False,
        decisions=[d1, d2, d3, d4, d5],
        operations=[
            create_assertion_op(
                key="kestrel-0001",
                decision_id=d1["decision_id"],
                assertion_id=a_member,
                payload={
                    "predicate": "MEMBER_OF",
                    "subject_entity_id": "entity:kestrel:vania",
                    "object_entity_id": "entity:kestrel:halcyon",
                },
                evidence_fragment_ids=[f_member],
            ),
            create_assertion_op(
                key="kestrel-0002",
                decision_id=d2["decision_id"],
                assertion_id=a_located,
                payload={
                    "predicate": "LOCATED_IN",
                    "subject_entity_id": "entity:kestrel:vania",
                    "object_entity_id": "entity:kestrel:estacion",
                },
                evidence_fragment_ids=[f_located],
            ),
            create_assertion_op(
                key="kestrel-0003",
                decision_id=d4["decision_id"],
                assertion_id=a_nucleo,
                payload={
                    "predicate": "OWNED_BY",
                    "subject_entity_id": "entity:kestrel:nucleo-bruma",
                    "object_entity_id": "entity:kestrel:halcyon",
                    "epistemic_status": "RUMORED",
                },
                evidence_fragment_ids=[f_nucleo],
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


def _fragment_of(source: SourceGold, claim_id: str) -> str:
    """Primer fragmento de evidencia del claim indicado."""
    for c in source.claims:
        if c["claim_id"] == claim_id:
            return c["evidence_fragment_ids"][0]
    raise KeyError(claim_id)


__all__ = ["build_kestrel", "build_leyenda", "build_mareas", "h"]
