# -*- coding: utf-8 -*-
"""Generacion determinista del split HELD-OUT.

    python3 build_heldout.py            # (re)escribe datasets/heldout
    python3 build_heldout.py --check    # ¿ha derivado respecto a la autoria?

Los textos y la anotacion estan escritos a mano aqui; los offsets, los hashes y
los sobres se calculan. Un offset escrito a mano se equivoca; uno calculado
sobre el texto literal, no.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # ejecucion directa como script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from _authoring.catalog import (  # type: ignore
        ENTITY_TYPE_BY_ID,
        entity_catalog,
        game_profile_gold,
        game_profile_narrow,
    )
    from _authoring.gold import (  # type: ignore
        DATASET_VERSION,
        FORMAT_VERSION,
        SPLIT,
        SourceGold,
        assertion_payload,
        create_assertion_op,
        create_entity_op,
        decision,
    )
else:  # pragma: no cover
    from .catalog import ENTITY_TYPE_BY_ID, entity_catalog, game_profile_gold, game_profile_narrow
    from .gold import (
        DATASET_VERSION,
        FORMAT_VERSION,
        SPLIT,
        SourceGold,
        assertion_payload,
        create_assertion_op,
        create_entity_op,
        decision,
    )

DATASETS_DIR = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Atajos de autoria
# --------------------------------------------------------------------------
def A(s: SourceGold, **kw: Any) -> dict[str, Any]:
    """Anade una afirmacion y devuelve el documento (no solo el id)."""
    s.assertion(**kw)
    return s.assertions[-1]


def accept(dkey: str, claim_id: str, a: dict[str, Any], *, reason: str = "LOCAL_APPROVED") -> dict[str, Any]:
    return decision(
        key=dkey,
        claim_id=claim_id,
        decision_value="ACCEPT",
        reason_codes=[reason],
        evidence_fragment_ids=a["evidence_fragment_ids"],
        predicate=a["predicate"],
        direction=a["direction"],
        subject_entity_id=a["subject_entity_id"],
        object_entity_id=a["object_entity_id"],
        epistemic_status=a["epistemic_status"],
        negated=a["negated"],
    )


def write_op(opkey: str, d: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    return create_assertion_op(
        key=opkey,
        decision_id=d["decision_id"],
        assertion_id=a["assertion_id"],
        payload=assertion_payload(a),
        evidence_fragment_ids=a["evidence_fragment_ids"],
    )


def noop_op(opkey: str, d: dict[str, Any], a: dict[str, Any], evidence: list[str]) -> dict[str, Any]:
    """Segunda fuente que repite un hecho ya conocido: existe, es idempotente, no escribe."""
    return create_assertion_op(
        key=opkey,
        decision_id=d["decision_id"],
        assertion_id=a["assertion_id"],
        payload=assertion_payload(a),
        evidence_fragment_ids=evidence,
        expected_state="NO_OP",
    )


def temporal(text: str, kind: str, calendar: str, valid_from=None, valid_to=None) -> dict[str, Any]:
    return {
        "text": text,
        "kind": kind,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "calendar_id": calendar,
        "fragment_id": None,
    }


CAL_F = "calendar:ferrovia"
CAL_M = "calendar:micelio"
CAL_L = "calendar:liga"


# ==========================================================================
# 1. ferrovia-memoria  (narrativo, markdown)
# ==========================================================================
def build_ferrovia_memoria() -> SourceGold:
    s = SourceGold(
        source_id="ferrovia-memoria",
        world="ferrovia",
        title="Memoria de la concesión del Norte",
        description="Relato narrativo: cadena de direcciones, negación a distancia, coordinación y sujeto-modificador.",
        source_kind="MARKDOWN",
        mime_type="text/markdown",
        original_name="memoria-concesion-norte.md",
        byte_size=742,
        created_at="1912-03-04T00:00:00Z",
        ingested_at="2026-07-21T09:00:00Z",
    )

    # --- e01: cadena de direcciones (supersesión encadenada) --------------
    t1 = (
        "Maren Ibarrola encabezó la Compañía del Norte desde el otoño de 1893 hasta el "
        "desprendimiento de Portazgo. Cedió la dirección en 1897 y desde entonces Iker "
        "Lasalde encabezó la Compañía. Desde el deshielo de 1901 la encabeza Nerea Lasalde."
    )
    e1 = s.episode(seq=1, modality="TEXT", text=t1, page=1,
                   phenomena=["TEMPORALITY", "SUPERSESSION", "COREFERENCE"])
    m_maren = s.mention(e1, "Maren Ibarrola", entity_type="Character")
    m_norte = s.mention(e1, "Compañía del Norte", entity_type="Faction")
    m_portazgo = s.mention(e1, "Portazgo", entity_type="Location")
    m_iker = s.mention(e1, "Iker Lasalde", entity_type="Character")
    m_comp = s.mention(e1, "la Compañía", entity_type="Faction", kind="NOMINAL",
                       context="Lasalde encabezó la Compañía.")
    m_la = s.mention(e1, "la", entity_type="Faction", kind="PRONOUN",
                     context="de 1901 la encabeza")
    m_nerea = s.mention(e1, "Nerea Lasalde", entity_type="Character")
    s.link_coreference(m_norte, m_comp, m_la)

    c1 = s.claim(e1, key="maren-leads-norte", subject_mentions=[m_maren], object_mentions=[m_norte],
                 relation_phrase="encabezó", predicate="LEADS",
                 temporal_expressions=[temporal("desde el otoño de 1893", "INTERVAL", CAL_F,
                                                valid_from="1893-10-01T00:00:00Z")],
                 phenomena=["TEMPORALITY", "SUPERSESSION"])
    c2 = s.claim(e1, key="iker-leads-norte", subject_mentions=[m_iker], object_mentions=[m_comp],
                 relation_phrase="encabezó", relation_occurrence=1, predicate="LEADS",
                 temporal_expressions=[temporal("en 1897", "POINT", CAL_F,
                                                valid_from="1897-06-01T00:00:00Z")],
                 phenomena=["TEMPORALITY", "SUPERSESSION", "COREFERENCE"])
    c3 = s.claim(e1, key="nerea-leads-norte", subject_mentions=[m_nerea], object_mentions=[m_la],
                 relation_phrase="encabeza", predicate="LEADS",
                 temporal_expressions=[temporal("Desde el deshielo de 1901", "POINT", CAL_F,
                                                valid_from="1901-04-01T00:00:00Z")],
                 phenomena=["TEMPORALITY", "SUPERSESSION", "COREFERENCE"])

    # --- e02: negación a distancia + sujeto-modificador -------------------
    t2 = (
        "El expediente de concesión no reconoció ninguna de las peticiones que Trasandina "
        "Unida presentó aquel invierno, ni siquiera la que firmaba el hermano de Nerea "
        "Lasalde para explotar el Túnel de Aizkorri."
    )
    e2 = s.episode(seq=2, modality="TEXT", text=t2, page=1,
                   phenomena=["NEGATION", "NEGATION_AT_DISTANCE", "MODIFIER_MISPAIR"])
    m2_trasandina = s.mention(e2, "Trasandina Unida", entity_type="Faction")
    m2_hermano = s.mention(e2, "el hermano de Nerea Lasalde", entity_type="Character", kind="NOMINAL")
    m2_nerea = s.mention(e2, "Nerea Lasalde", entity_type="Character")
    m2_tunel = s.mention(e2, "Túnel de Aizkorri", entity_type="Location")

    c4 = s.claim(e2, key="iker-no-owns-aizkorri", subject_mentions=[m2_hermano],
                 object_mentions=[m2_tunel], relation_phrase="para explotar", predicate="OWNS",
                 negated=True, epistemic_cues=["no reconoció ninguna", "ni siquiera"],
                 phenomena=["NEGATION", "NEGATION_AT_DISTANCE", "MODIFIER_MISPAIR"])
    s.negative_pair(e2, key="modificador-nerea-tunel",
                    literal="el hermano de Nerea Lasalde para explotar el Túnel de Aizkorri",
                    kind="MODIFIER_MISPAIR",
                    subject_mentions=[m2_nerea], object_mentions=[m2_tunel],
                    forbidden_predicates=["OWNS", "OWNED_BY"],
                    rationale=("Quien firma es el hermano, no Nerea. Emparejar a Nerea con el "
                               "túnel es el error clásico del sujeto-modificador."))

    # --- e03: coordinación + simétrica -----------------------------------
    t3 = (
        "Nerea Lasalde ingresó en la Compañía del Norte y también Iker Lasalde ingresó en "
        "Trasandina Unida. Los dos hermanos discutieron el reparto en la Estación de Portazgo."
    )
    e3 = s.episode(seq=3, modality="TEXT", text=t3, page=2,
                   phenomena=["COORDINATION_MISPAIR", "SYMMETRIC", "CONFLICT"])
    m3_nerea = s.mention(e3, "Nerea Lasalde", entity_type="Character")
    m3_norte = s.mention(e3, "Compañía del Norte", entity_type="Faction")
    m3_iker = s.mention(e3, "Iker Lasalde", entity_type="Character")
    m3_trasandina = s.mention(e3, "Trasandina Unida", entity_type="Faction")
    m3_portazgo = s.mention(e3, "Estación de Portazgo", entity_type="Location")

    c5 = s.claim(e3, key="nerea-member-norte", subject_mentions=[m3_nerea], object_mentions=[m3_norte],
                 relation_phrase="ingresó en", predicate="MEMBER_OF",
                 phenomena=["COORDINATION_MISPAIR"])
    c6 = s.claim(e3, key="iker-member-trasandina", subject_mentions=[m3_iker],
                 object_mentions=[m3_trasandina], relation_phrase="ingresó en",
                 relation_occurrence=1, predicate="MEMBER_OF",
                 phenomena=["COORDINATION_MISPAIR", "CONFLICT"])
    c7 = s.claim(e3, key="nerea-sibling-iker", subject_mentions=[m3_nerea], object_mentions=[m3_iker],
                 relation_phrase="Los dos hermanos", predicate="SIBLING_OF", direction="UNDIRECTED",
                 phenomena=["SYMMETRIC"])
    s.negative_span(e3, key="lugar-de-evento-portazgo",
                    literal="discutieron el reparto en la Estación de Portazgo",
                    kind="EVENT_LOCATION", forbidden_predicates=["LOCATED_IN"],
                    rationale=("Reunirse una vez en un sitio no ubica a nadie en el. Un "
                               "LOCATED_IN persistente sobre los hermanos seria falso."))
    s.negative_pair(e3, key="coordinacion-nerea-trasandina",
                    literal="y también Iker Lasalde ingresó en Trasandina Unida",
                    kind="COORDINATION_MISPAIR",
                    subject_mentions=[m3_nerea], object_mentions=[m3_trasandina],
                    forbidden_predicates=["MEMBER_OF"],
                    rationale=("La coordinación abre una segunda cláusula con sujeto propio: "
                               "Nerea no ingresó en Trasandina Unida."))
    s.negative_pair(e3, key="coordinacion-iker-norte",
                    literal="Nerea Lasalde ingresó en la Compañía del Norte",
                    kind="COORDINATION_MISPAIR",
                    subject_mentions=[m3_iker], object_mentions=[m3_norte],
                    forbidden_predicates=["MEMBER_OF"],
                    rationale="El objeto de la primera cláusula no pertenece al sujeto de la segunda.")

    # --- resoluciones -----------------------------------------------------
    s.link("maren", [m_maren], "entity:ferrovia:maren", "Character")
    s.link("norte", [m_norte, m_comp, m_la, m3_norte], "entity:ferrovia:norte", "Faction",
           reason_codes=["EXACT_ALIAS", "COREFERENCE_CHAIN"])
    s.link("portazgo", [m_portazgo, m3_portazgo], "entity:ferrovia:portazgo", "Location")
    s.link("iker", [m_iker, m2_hermano, m3_iker], "entity:ferrovia:iker", "Character",
           reason_codes=["EXACT_ALIAS", "KINSHIP_INFERENCE"], confidence=0.78)
    s.link("nerea", [m_nerea, m2_nerea, m3_nerea], "entity:ferrovia:nerea", "Character")
    s.link("trasandina", [m2_trasandina, m3_trasandina], "entity:ferrovia:trasandina", "Faction")
    s.link("aizkorri", [m2_tunel], "entity:ferrovia:aizkorri", "Location")

    # --- afirmaciones -----------------------------------------------------
    a1_id = "assertion:ferrovia:maren-leads-norte"
    a2_id = "assertion:ferrovia:iker-leads-norte"
    a3_id = "assertion:ferrovia:nerea-leads-norte"
    a1 = A(s, key="maren-leads-norte", subject_entity_id="entity:ferrovia:maren",
           object_entity_id="entity:ferrovia:norte", predicate="LEADS",
           episode_ids=[e1], evidence_fragment_ids=s.claims[0]["evidence_fragment_ids"],
           valid_from="1893-10-01T00:00:00Z", valid_to="1897-06-01T00:00:00Z",
           calendar_id=CAL_F, state="ENDED", status="SUPERSEDED", superseded_by=a2_id,
           phenomena=["SUPERSESSION", "TEMPORALITY"])
    a2 = A(s, key="iker-leads-norte", subject_entity_id="entity:ferrovia:iker",
           object_entity_id="entity:ferrovia:norte", predicate="LEADS",
           episode_ids=[e1], evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"],
           valid_from="1897-06-01T00:00:00Z", valid_to="1901-04-01T00:00:00Z",
           calendar_id=CAL_F, state="ENDED", status="SUPERSEDED",
           supersedes=a1_id, superseded_by=a3_id,
           phenomena=["SUPERSESSION", "TEMPORALITY"])
    a3 = A(s, key="nerea-leads-norte", subject_entity_id="entity:ferrovia:nerea",
           object_entity_id="entity:ferrovia:norte", predicate="LEADS",
           episode_ids=[e1], evidence_fragment_ids=s.claims[2]["evidence_fragment_ids"],
           valid_from="1901-04-01T00:00:00Z", calendar_id=CAL_F,
           state="ACTIVE", status="ASSERTED", supersedes=a2_id,
           phenomena=["SUPERSESSION", "TEMPORALITY"])
    a4 = A(s, key="iker-not-owns-aizkorri", subject_entity_id="entity:ferrovia:iker",
           object_entity_id="entity:ferrovia:aizkorri", predicate="OWNS",
           episode_ids=[e2], evidence_fragment_ids=s.claims[3]["evidence_fragment_ids"],
           negated=True, state="ACTIVE", status="ASSERTED",
           phenomena=["NEGATION", "NEGATION_AT_DISTANCE"])
    a5 = A(s, key="nerea-member-norte", subject_entity_id="entity:ferrovia:nerea",
           object_entity_id="entity:ferrovia:norte", predicate="MEMBER_OF",
           episode_ids=[e3], evidence_fragment_ids=s.claims[4]["evidence_fragment_ids"])
    a6 = A(s, key="iker-member-trasandina", subject_entity_id="entity:ferrovia:iker",
           object_entity_id="entity:ferrovia:trasandina", predicate="MEMBER_OF",
           episode_ids=[e3], evidence_fragment_ids=s.claims[5]["evidence_fragment_ids"],
           epistemic_status="CONFLICTED", status="CONTRADICTED", phenomena=["CONFLICT"])
    a7 = A(s, key="nerea-sibling-iker", subject_entity_id="entity:ferrovia:nerea",
           object_entity_id="entity:ferrovia:iker", predicate="SIBLING_OF",
           direction="UNDIRECTED", episode_ids=[e3],
           evidence_fragment_ids=s.claims[6]["evidence_fragment_ids"], phenomena=["SYMMETRIC"])

    pares = [("d1", c1, a1), ("d2", c2, a2), ("d3", c3, a3), ("d4", c4, a4),
             ("d5", c5, a5), ("d7", c7, a7)]
    decisions = [accept(f"ferrovia-memoria:{k}", cid, a) for k, cid, a in pares]
    d6 = accept("ferrovia-memoria:d6", c6, a6, reason="LOCAL_APPROVED_WITH_WARNINGS")
    decisions.insert(5, d6)
    ops = [write_op(f"ferrovia-memoria:{k}", d, a)
           for (k, _c, a), d in zip(pares[:5], decisions[:5])]
    ops.append(write_op("ferrovia-memoria:d6", d6, a6))
    ops.append(write_op("ferrovia-memoria:d7", decisions[6], a7))
    s.plan(key="p1", decisions=decisions, operations=ops, approved=True)
    return s


# ==========================================================================
# 2. ferrovia-cartas  (epistolar: estructura distinta a dev)
# ==========================================================================
def build_ferrovia_cartas() -> SourceGold:
    s = SourceGold(
        source_id="ferrovia-cartas",
        world="ferrovia",
        title="Correspondencia del taller de Portazgo",
        description="Epistolar: rumor sin desmentir, rumor DESMENTIDO y el reverso del conflicto.",
        source_kind="TEXT",
        mime_type="text/plain",
        original_name="cartas-portazgo-1899.txt",
        byte_size=688,
        created_at="1899-05-09T00:00:00Z",
        ingested_at="2026-07-21T09:05:00Z",
    )

    t1 = (
        "Portazgo, 14 de marzo de 1899\n"
        "A la atención de Maren Ibarrola:\n"
        "Corre por los talleres que Trasandina Unida y la Compañía del Norte se han repartido "
        "la concesión del Túnel de Aizkorri. Nadie ha visto el documento."
    )
    e1 = s.episode(seq=1, modality="TEXT", text=t1, page=1, phenomena=["RUMOR", "SYMMETRIC"])
    m_cab1 = s.mention(e1, "Portazgo", entity_type="Location")
    m_maren = s.mention(e1, "Maren Ibarrola", entity_type="Character")
    m_tras = s.mention(e1, "Trasandina Unida", entity_type="Faction")
    m_norte = s.mention(e1, "Compañía del Norte", entity_type="Faction")
    m_tunel = s.mention(e1, "Túnel de Aizkorri", entity_type="Location")
    c1 = s.claim(e1, key="trasandina-ally-norte", subject_mentions=[m_tras], object_mentions=[m_norte],
                 relation_phrase="se han repartido", predicate="ALLY_OF", direction="UNDIRECTED",
                 epistemic="RUMORED",
                 epistemic_cues=["Corre por los talleres que", "Nadie ha visto el documento"],
                 confidence=0.62,
                 alternatives=[{"predicate": "OWNS", "direction": "SUBJECT_TO_OBJECT",
                                "confidence": 0.3, "reason_codes": ["AMBIGUOUS_SEMANTICS"]}],
                 phenomena=["RUMOR", "SYMMETRIC", "ALTERNATIVE_READING"])

    t2 = (
        "Portazgo, 2 de abril de 1899\n"
        "Se dijo en la cantina que la locomotora Cierzo era propiedad de la Compañía del Norte; "
        "el libro de inventario lo desmiente sin dejar lugar a dudas."
    )
    e2 = s.episode(seq=2, modality="TEXT", text=t2, page=1, phenomena=["DENIED_RUMOR"])
    m_cab2 = s.mention(e2, "Portazgo", entity_type="Location")
    m2_cierzo = s.mention(e2, "locomotora Cierzo", entity_type="Object")
    m2_norte = s.mention(e2, "Compañía del Norte", entity_type="Faction")
    s.negative_span(e2, key="rumor-desmentido-cierzo",
                    literal="la locomotora Cierzo era propiedad de la Compañía del Norte",
                    kind="DENIED_RUMOR", forbidden_predicates=["OWNED_BY", "OWNS"],
                    rationale=("El rumor se desmiente en la misma frase que lo enuncia. Un rumor "
                               "vivo produce claim RUMORED; uno refutado en su propia fuente, "
                               "ninguno."))

    t3 = (
        "Portazgo, 9 de mayo de 1899\n"
        "Dejo constancia de que Iker Lasalde no figura como socio de Trasandina Unida en ninguno "
        "de los tres libros que he revisado. La locomotora Cierzo, en cambio, pertenece a "
        "Trasandina Unida desde el reparto."
    )
    e3 = s.episode(seq=3, modality="TEXT", text=t3, page=2, phenomena=["CONFLICT", "NEGATION"])
    m_cab3 = s.mention(e3, "Portazgo", entity_type="Location")
    m3_iker = s.mention(e3, "Iker Lasalde", entity_type="Character")
    m3_tras = s.mention(e3, "Trasandina Unida", entity_type="Faction")
    m3_cierzo = s.mention(e3, "locomotora Cierzo", entity_type="Object")
    m3_tras2 = s.mention(e3, "Trasandina Unida", entity_type="Faction", occurrence=1)
    c2 = s.claim(e3, key="iker-not-member-trasandina", subject_mentions=[m3_iker],
                 object_mentions=[m3_tras], relation_phrase="no figura como socio de",
                 predicate="MEMBER_OF", negated=True, phenomena=["NEGATION", "CONFLICT"])
    c3 = s.claim(e3, key="cierzo-owned-trasandina", subject_mentions=[m3_cierzo],
                 object_mentions=[m3_tras2], relation_phrase="pertenece a", predicate="OWNED_BY",
                 alternatives=[{"predicate": "OWNS", "direction": "OBJECT_TO_SUBJECT",
                                "confidence": 0.4, "reason_codes": ["INVERSE_READING"]}],
                 phenomena=["INVERSE_PREDICATE", "ALTERNATIVE_READING"])

    s.link("maren", [m_maren], "entity:ferrovia:maren", "Character")
    s.link("trasandina", [m_tras, m3_tras, m3_tras2], "entity:ferrovia:trasandina", "Faction")
    s.link("norte", [m_norte, m2_norte], "entity:ferrovia:norte", "Faction")
    s.link("aizkorri", [m_tunel], "entity:ferrovia:aizkorri", "Location")
    s.link("cierzo", [m2_cierzo, m3_cierzo], "entity:ferrovia:cierzo", "Object")
    s.link("iker", [m3_iker], "entity:ferrovia:iker", "Character")
    s.link("portazgo", [m_cab1, m_cab2, m_cab3], "entity:ferrovia:portazgo", "Location",
           reason_codes=["EXACT_ALIAS", "LETTERHEAD_PLACE"])

    a1 = A(s, key="trasandina-ally-norte", subject_entity_id="entity:ferrovia:trasandina",
           object_entity_id="entity:ferrovia:norte", predicate="ALLY_OF", direction="UNDIRECTED",
           episode_ids=[e1], evidence_fragment_ids=s.claims[0]["evidence_fragment_ids"],
           epistemic_status="RUMORED", status="PROVISIONAL", confidence=0.55,
           phenomena=["RUMOR", "SYMMETRIC"])
    a2 = A(s, key="iker-not-member-trasandina", subject_entity_id="entity:ferrovia:iker",
           object_entity_id="entity:ferrovia:trasandina", predicate="MEMBER_OF",
           episode_ids=[e3], evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"],
           negated=True, epistemic_status="CONFLICTED", status="CONTRADICTED",
           phenomena=["CONFLICT", "NEGATION"])
    a3 = A(s, key="cierzo-owned-trasandina", subject_entity_id="entity:ferrovia:cierzo",
           object_entity_id="entity:ferrovia:trasandina", predicate="OWNED_BY",
           episode_ids=[e3], evidence_fragment_ids=s.claims[2]["evidence_fragment_ids"],
           phenomena=["INVERSE_PREDICATE"])

    d1 = accept("ferrovia-cartas:d1", c1, a1)
    d2 = accept("ferrovia-cartas:d2", c2, a2, reason="LOCAL_APPROVED_WITH_WARNINGS")
    d3 = accept("ferrovia-cartas:d3", c3, a3)
    ops = [write_op("ferrovia-cartas:d1", d1, a1),
           write_op("ferrovia-cartas:d2", d2, a2),
           write_op("ferrovia-cartas:d3", d3, a3)]
    s.plan(key="p1", decisions=[d1, d2, d3], operations=ops, approved=True)
    return s


# ==========================================================================
# 3. ferrovia-tabla  (TABLE: duplicado entre fuentes y entidad nueva)
# ==========================================================================
def build_ferrovia_tabla(a_iker_member: dict[str, Any], a_nerea_member: dict[str, Any]) -> SourceGold:
    s = SourceGold(
        source_id="ferrovia-tabla",
        world="ferrovia",
        title="Libro de socios del taller (1902)",
        description="Tabla: repite dos hechos ya conocidos (NO_OP) y trae un socio nuevo.",
        source_kind="TABLE",
        mime_type="text/csv",
        original_name="libro-socios-1902.csv",
        byte_size=214,
        created_at="1902-01-11T00:00:00Z",
        ingested_at="2026-07-21T09:10:00Z",
    )
    table = {
        "header": ["Socio", "Compañía", "Turno", "Alta"],
        "rows": [
            ["Iker Lasalde", "Trasandina Unida", "noche", "1898"],
            ["Txomin Ereña", "Compañía del Norte", "día", "1902"],
            ["Maren Ibarrola", "Compañía del Norte", "día", "1893"],
            ["Nerea Lasalde", "Compañía del Norte", "noche", "1901"],
        ],
    }
    e1 = s.episode(seq=1, modality="TABLE", table=table, page=1,
                   phenomena=["TABLE", "DUPLICATE_ACROSS_SOURCES", "NEW_ENTITY"],
                   fragment_media_type="TABLE")
    m_iker = s.mention(e1, "Iker Lasalde", entity_type="Character", kind="CELL")
    m_tras = s.mention(e1, "Trasandina Unida", entity_type="Faction", kind="CELL")
    m_txomin = s.mention(e1, "Txomin Ereña", entity_type="Character", kind="CELL")
    m_norte1 = s.mention(e1, "Compañía del Norte", entity_type="Faction", kind="CELL")
    m_maren = s.mention(e1, "Maren Ibarrola", entity_type="Character", kind="CELL")
    m_norte2 = s.mention(e1, "Compañía del Norte", entity_type="Faction", occurrence=1, kind="CELL")
    m_nerea = s.mention(e1, "Nerea Lasalde", entity_type="Character", kind="CELL")
    m_norte3 = s.mention(e1, "Compañía del Norte", entity_type="Faction", occurrence=2, kind="CELL")

    c1 = s.claim(e1, key="iker-member-trasandina", subject_mentions=[m_iker], object_mentions=[m_tras],
                 relation_phrase="Iker Lasalde\tTrasandina Unida", predicate="MEMBER_OF",
                 temporal_expressions=[temporal("1898", "POINT", CAL_F, valid_from="1898-01-01T00:00:00Z")],
                 qualifiers=[{"key": "turno", "value": "noche"}],
                 phenomena=["TABLE", "DUPLICATE_ACROSS_SOURCES"])
    c2 = s.claim(e1, key="txomin-member-norte", subject_mentions=[m_txomin], object_mentions=[m_norte1],
                 relation_phrase="Txomin Ereña\tCompañía del Norte", predicate="MEMBER_OF",
                 temporal_expressions=[temporal("1902", "POINT", CAL_F, valid_from="1902-01-01T00:00:00Z")],
                 qualifiers=[{"key": "turno", "value": "día"}],
                 phenomena=["TABLE", "NEW_ENTITY"])
    c3 = s.claim(e1, key="maren-member-norte", subject_mentions=[m_maren], object_mentions=[m_norte2],
                 relation_phrase="Maren Ibarrola\tCompañía del Norte", predicate="MEMBER_OF",
                 temporal_expressions=[temporal("1893", "POINT", CAL_F, valid_from="1893-01-01T00:00:00Z")],
                 qualifiers=[{"key": "turno", "value": "día"}],
                 phenomena=["TABLE"])
    c4 = s.claim(e1, key="nerea-member-norte", subject_mentions=[m_nerea], object_mentions=[m_norte3],
                 relation_phrase="Nerea Lasalde\tCompañía del Norte", predicate="MEMBER_OF",
                 temporal_expressions=[temporal("1901", "POINT", CAL_F, valid_from="1901-01-01T00:00:00Z")],
                 qualifiers=[{"key": "turno", "value": "noche"}],
                 phenomena=["TABLE", "DUPLICATE_ACROSS_SOURCES"])

    s.link("iker", [m_iker], "entity:ferrovia:iker", "Character")
    s.link("trasandina", [m_tras], "entity:ferrovia:trasandina", "Faction")
    s.resolution(key="txomin", mention_ids=[m_txomin], action="CREATE_NEW", entity_type="Character",
                 assigned_entity_id="entity:ferrovia:txomin",
                 reason_codes=["NO_CANDIDATE_ABOVE_THRESHOLD"], confidence=0.9)
    s.link("norte", [m_norte1, m_norte2, m_norte3], "entity:ferrovia:norte", "Faction")
    s.link("maren", [m_maren], "entity:ferrovia:maren", "Character")
    s.link("nerea", [m_nerea], "entity:ferrovia:nerea", "Character")

    a_txomin = A(s, key="txomin-member-norte", subject_entity_id="entity:ferrovia:txomin",
                 object_entity_id="entity:ferrovia:norte", predicate="MEMBER_OF",
                 episode_ids=[e1], evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"],
                 valid_from="1902-01-01T00:00:00Z", calendar_id=CAL_F, phenomena=["NEW_ENTITY", "TABLE"])
    a_maren = A(s, key="maren-member-norte", subject_entity_id="entity:ferrovia:maren",
                object_entity_id="entity:ferrovia:norte", predicate="MEMBER_OF",
                episode_ids=[e1], evidence_fragment_ids=s.claims[2]["evidence_fragment_ids"],
                valid_from="1893-01-01T00:00:00Z", calendar_id=CAL_F, phenomena=["TABLE"])

    d1 = accept("ferrovia-tabla:d1", c1, a_iker_member, reason="LOCAL_APPROVED_WITH_WARNINGS")
    d1["evidence_fragment_ids"] = s.claims[0]["evidence_fragment_ids"]
    d2 = accept("ferrovia-tabla:d2", c2, a_txomin)
    d3 = accept("ferrovia-tabla:d3", c3, a_maren)
    d4 = accept("ferrovia-tabla:d4", c4, a_nerea_member)
    d4["evidence_fragment_ids"] = s.claims[3]["evidence_fragment_ids"]
    ops = [
        noop_op("ferrovia-tabla:d1", d1, a_iker_member, s.claims[0]["evidence_fragment_ids"]),
        create_entity_op(key="ferrovia-tabla:e-txomin", decision_id=d2["decision_id"],
                         target_entity_id="entity:ferrovia:txomin",
                         payload={"entity_id": "entity:ferrovia:txomin", "name": "Txomin Ereña",
                                  "type": "Character", "aliases": ["Txomin Ereña"]},
                         evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"]),
        write_op("ferrovia-tabla:d2", d2, a_txomin),
        write_op("ferrovia-tabla:d3", d3, a_maren),
        noop_op("ferrovia-tabla:d4", d4, a_nerea_member, s.claims[3]["evidence_fragment_ids"]),
    ]
    s.plan(key="p1", decisions=[d1, d2, d3, d4], operations=ops, approved=True)
    return s


# ==========================================================================
# 4. micelio-wiki  (estructura de ficha/wiki: distinta a dev)
# ==========================================================================
def build_micelio_wiki() -> SourceGold:
    s = SourceGold(
        source_id="micelio-wiki",
        world="micelio",
        title="Ficha de la Hermandad del Esporo",
        description="Wiki con secciones e infobox: simétrica, inversa, hipotética, pregunta y ficción interna.",
        source_kind="WEB",
        mime_type="text/html",
        original_name="hermandad-del-esporo.html",
        byte_size=980,
        created_at="2026-02-02T00:00:00Z",
        ingested_at="2026-07-21T09:20:00Z",
    )

    t1 = (
        "== Hermandad del Esporo ==\n"
        "Tipo: hermandad de cultivo\n"
        "Sede: Cámara Honda\n"
        "Rival declarada: Cónclave Lívido\n"
        "Cultivo en propiedad: Cámara Yesca\n"
        "Miembro destacada: Leire Onraita"
    )
    e1 = s.episode(seq=1, modality="TEXT", text=t1, page=1,
                   phenomena=["SYMMETRIC", "INVERSE_PREDICATE"])
    m_herm = s.mention(e1, "Hermandad del Esporo", entity_type="Faction")
    m_honda = s.mention(e1, "Cámara Honda", entity_type="Location")
    m_conc = s.mention(e1, "Cónclave Lívido", entity_type="Faction")
    m_yesca = s.mention(e1, "Cámara Yesca", entity_type="Location")
    m_leire = s.mention(e1, "Leire Onraita", entity_type="Character")
    c1 = s.claim(e1, key="hermandad-in-honda", subject_mentions=[m_herm], object_mentions=[m_honda],
                 relation_phrase="Sede:", predicate="LOCATED_IN")
    c2 = s.claim(e1, key="hermandad-rival-conclave", subject_mentions=[m_herm],
                 object_mentions=[m_conc], relation_phrase="Rival declarada:", predicate="RIVAL_OF",
                 direction="UNDIRECTED", phenomena=["SYMMETRIC"])
    c3 = s.claim(e1, key="hermandad-owns-yesca", subject_mentions=[m_herm], object_mentions=[m_yesca],
                 relation_phrase="Cultivo en propiedad:", predicate="OWNS",
                 phenomena=["INVERSE_PREDICATE"])
    c4 = s.claim(e1, key="hermandad-has-leire", subject_mentions=[m_herm], object_mentions=[m_leire],
                 relation_phrase="Miembro destacada:", predicate="HAS_MEMBER",
                 phenomena=["INVERSE_PREDICATE"])

    t2 = (
        "== Geografía ==\n"
        "La Cámara Honda se abre dentro de la Galería Ocre. Si el Cónclave Lívido llegara a "
        "ocupar la Galería Ocre, la Hermandad tendría que mudar sus cultivos. "
        "¿Llegó Sabel Onraita a presidir el Cónclave Lívido?"
    )
    e2 = s.episode(seq=2, modality="TEXT", text=t2, page=1,
                   phenomena=["TRANSITIVE", "HYPOTHETICAL", "QUESTION", "ONTOLOGY_VIOLATION"])
    m2_honda = s.mention(e2, "Cámara Honda", entity_type="Location")
    m2_ocre = s.mention(e2, "Galería Ocre", entity_type="Location")
    m2_conc = s.mention(e2, "Cónclave Lívido", entity_type="Faction")
    m2_ocre2 = s.mention(e2, "Galería Ocre", entity_type="Location", occurrence=1)
    m2_herm = s.mention(e2, "la Hermandad", entity_type="Faction", kind="NOMINAL")
    m2_sabel = s.mention(e2, "Sabel Onraita", entity_type="Character")
    m2_conc2 = s.mention(e2, "Cónclave Lívido", entity_type="Faction", occurrence=1)
    c5 = s.claim(e2, key="honda-in-ocre", subject_mentions=[m2_honda], object_mentions=[m2_ocre],
                 relation_phrase="se abre dentro de", predicate="LOCATED_IN",
                 phenomena=["TRANSITIVE"])
    c6 = s.claim(e2, key="conclave-in-ocre", subject_mentions=[m2_conc], object_mentions=[m2_ocre2],
                 relation_phrase="llegara a ocupar", predicate="LOCATED_IN",
                 epistemic="HYPOTHETICAL", epistemic_cues=["Si", "tendría que"], confidence=0.6,
                 phenomena=["HYPOTHETICAL"])
    hipo_frags = s.claims[-1]["evidence_fragment_ids"]
    c7 = s.claim(e2, key="conclave-leads-ocre-INVALID", subject_mentions=[m2_conc],
                 object_mentions=[m2_ocre2], relation_phrase="llegara a ocupar",
                 fragment_ids=hipo_frags, predicate="LEADS", confidence=0.4,
                 role="ENGINE_ONLY", phenomena=["ONTOLOGY_VIOLATION"])
    s.negative_span(e2, key="pregunta-sabel-conclave",
                    literal="¿Llegó Sabel Onraita a presidir el Cónclave Lívido?",
                    kind="QUESTION", forbidden_predicates=["LEADS", "MEMBER_OF"],
                    rationale="Una pregunta nombra a las dos entidades y no afirma nada de ellas.")

    t3 = (
        "== Cultura ==\n"
        "En la pantomima que los cultivadores representan cada solsticio, el Cónclave Lívido "
        "devora la Cámara Honda. La hermana de Sabel Onraita dirige la Hermandad del Esporo "
        "desde la última siembra; ella no ha vuelto a la Galería Ocre."
    )
    e3 = s.episode(seq=3, modality="TEXT", text=t3, page=2,
                   phenomena=["FICTION_WITHIN_FICTION", "MODIFIER_MISPAIR", "COREFERENCE",
                              "NEGATION", "SYMMETRIC"])
    m3_conc = s.mention(e3, "Cónclave Lívido", entity_type="Faction")
    m3_honda = s.mention(e3, "Cámara Honda", entity_type="Location")
    m3_hermana = s.mention(e3, "La hermana de Sabel Onraita", entity_type="Character", kind="NOMINAL")
    m3_sabel = s.mention(e3, "Sabel Onraita", entity_type="Character")
    m3_herm = s.mention(e3, "Hermandad del Esporo", entity_type="Faction")
    m3_ella = s.mention(e3, "ella", entity_type="Character", kind="PRONOUN",
                        context="siembra; ella no ha vuelto")
    m3_ocre = s.mention(e3, "Galería Ocre", entity_type="Location")
    s.link_coreference(m3_hermana, m3_ella)
    c8 = s.claim(e3, key="leire-leads-hermandad", subject_mentions=[m3_hermana],
                 object_mentions=[m3_herm], relation_phrase="dirige", predicate="LEADS",
                 temporal_expressions=[temporal("desde la última siembra", "RELATIVE", CAL_M)],
                 phenomena=["MODIFIER_MISPAIR", "TEMPORALITY"])
    c9 = s.claim(e3, key="leire-sibling-sabel", subject_mentions=[m3_hermana],
                 object_mentions=[m3_sabel], relation_phrase="La hermana de",
                 predicate="SIBLING_OF", direction="UNDIRECTED", phenomena=["SYMMETRIC"])
    c10 = s.claim(e3, key="leire-not-in-ocre", subject_mentions=[m3_ella], object_mentions=[m3_ocre],
                  relation_phrase="no ha vuelto a", predicate="LOCATED_IN", negated=True,
                  phenomena=["NEGATION", "COREFERENCE"])
    s.negative_span(e3, key="ficcion-conclave-devora",
                    literal="el Cónclave Lívido devora la Cámara Honda",
                    kind="FICTION_WITHIN_FICTION", forbidden_predicates=["LOCATED_IN", "OWNS", "RIVAL_OF"],
                    rationale="Lo que pasa dentro de la pantomima no pasa en el mundo.")
    s.negative_pair(e3, key="modificador-sabel-hermandad",
                    literal="La hermana de Sabel Onraita dirige la Hermandad del Esporo",
                    kind="MODIFIER_MISPAIR", subject_mentions=[m3_sabel], object_mentions=[m3_herm],
                    forbidden_predicates=["LEADS", "MEMBER_OF"],
                    rationale=("Quien dirige es la hermana (Leire), no Sabel. Sabel solo aparece "
                               "dentro del modificador del sujeto."))

    s.link("hermandad", [m_herm, m2_herm, m3_herm], "entity:micelio:hermandad", "Faction",
           reason_codes=["EXACT_ALIAS", "COREFERENCE_CHAIN"])
    s.link("camara-honda", [m_honda, m2_honda, m3_honda], "entity:micelio:camara-honda", "Location")
    s.link("conclave", [m_conc, m2_conc, m2_conc2, m3_conc], "entity:micelio:conclave", "Faction")
    s.link("camara-yesca", [m_yesca], "entity:micelio:camara-yesca", "Location")
    s.link("leire", [m_leire, m3_hermana, m3_ella], "entity:micelio:leire", "Character",
           reason_codes=["EXACT_ALIAS", "KINSHIP_INFERENCE", "COREFERENCE_CHAIN"], confidence=0.82)
    s.link("galeria-ocre", [m2_ocre, m2_ocre2, m3_ocre], "entity:micelio:galeria-ocre", "Location")
    s.link("sabel", [m2_sabel, m3_sabel], "entity:micelio:sabel", "Character")

    a1 = A(s, key="hermandad-in-honda", subject_entity_id="entity:micelio:hermandad",
           object_entity_id="entity:micelio:camara-honda", predicate="LOCATED_IN",
           episode_ids=[e1], evidence_fragment_ids=s.claims[0]["evidence_fragment_ids"])
    a2 = A(s, key="hermandad-rival-conclave", subject_entity_id="entity:micelio:hermandad",
           object_entity_id="entity:micelio:conclave", predicate="RIVAL_OF", direction="UNDIRECTED",
           episode_ids=[e1], evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"],
           phenomena=["SYMMETRIC"])
    a3 = A(s, key="hermandad-owns-yesca", subject_entity_id="entity:micelio:hermandad",
           object_entity_id="entity:micelio:camara-yesca", predicate="OWNS",
           episode_ids=[e1], evidence_fragment_ids=s.claims[2]["evidence_fragment_ids"],
           phenomena=["INVERSE_PREDICATE"])
    a4 = A(s, key="hermandad-has-leire", subject_entity_id="entity:micelio:hermandad",
           object_entity_id="entity:micelio:leire", predicate="HAS_MEMBER",
           episode_ids=[e1], evidence_fragment_ids=s.claims[3]["evidence_fragment_ids"],
           phenomena=["INVERSE_PREDICATE"])
    a5 = A(s, key="honda-in-ocre", subject_entity_id="entity:micelio:camara-honda",
           object_entity_id="entity:micelio:galeria-ocre", predicate="LOCATED_IN",
           episode_ids=[e2], evidence_fragment_ids=s.claims[4]["evidence_fragment_ids"],
           phenomena=["TRANSITIVE"])
    a6 = A(s, key="conclave-in-ocre", subject_entity_id="entity:micelio:conclave",
           object_entity_id="entity:micelio:galeria-ocre", predicate="LOCATED_IN",
           episode_ids=[e2], evidence_fragment_ids=s.claims[5]["evidence_fragment_ids"],
           epistemic_status="HYPOTHETICAL", status="PROVISIONAL", state="HYPOTHETICAL",
           confidence=0.5, phenomena=["HYPOTHETICAL"])
    a7 = A(s, key="leire-leads-hermandad", subject_entity_id="entity:micelio:leire",
           object_entity_id="entity:micelio:hermandad", predicate="LEADS",
           episode_ids=[e3], evidence_fragment_ids=s.claims[7]["evidence_fragment_ids"],
           calendar_id=CAL_M, phenomena=["TEMPORALITY"])
    a8 = A(s, key="leire-sibling-sabel", subject_entity_id="entity:micelio:leire",
           object_entity_id="entity:micelio:sabel", predicate="SIBLING_OF", direction="UNDIRECTED",
           episode_ids=[e3], evidence_fragment_ids=s.claims[8]["evidence_fragment_ids"],
           phenomena=["SYMMETRIC"])
    a9 = A(s, key="leire-not-in-ocre", subject_entity_id="entity:micelio:leire",
           object_entity_id="entity:micelio:galeria-ocre", predicate="LOCATED_IN",
           episode_ids=[e3], evidence_fragment_ids=s.claims[9]["evidence_fragment_ids"],
           negated=True, phenomena=["NEGATION"])

    pares = [("d1", c1, a1), ("d2", c2, a2), ("d3", c3, a3), ("d4", c4, a4), ("d5", c5, a5),
             ("d6", c6, a6), ("d8", c8, a7), ("d9", c9, a8), ("d10", c10, a9)]
    decisions = [accept(f"micelio-wiki:{k}", cid, a) for k, cid, a in pares]
    d7 = decision(key="micelio-wiki:d7", claim_id=c7, decision_value="REJECT_INVALID",
                  reason_codes=["ONTOLOGY_INCOMPATIBLE", "TYPE_INCOMPATIBLE"],
                  evidence_fragment_ids=hipo_frags, confidence=0.95)
    decisions.insert(6, d7)
    ops = [write_op(f"micelio-wiki:{k}", d, a) for (k, _c, a), d in
           zip(pares, [d for d in decisions if d["decision"] == "ACCEPT"])]
    s.plan(key="p1", decisions=decisions, operations=ops, approved=True)
    return s


# ==========================================================================
# 5. micelio-escaneo  (OCR degradado + plano)
# ==========================================================================
def build_micelio_escaneo(a_leire_leads: dict[str, Any]) -> SourceGold:
    s = SourceGold(
        source_id="micelio-escaneo",
        world="micelio",
        title="Escaneo del acta de la Cámara Honda",
        description="Imagen escaneada: OCR degradado, firma ilegible (provisional) y un plano del que solo cabe inferir.",
        source_kind="IMAGE",
        mime_type="image/png",
        original_name="acta-camara-honda.png",
        byte_size=41230,
        created_at="2026-03-18T00:00:00Z",
        ingested_at="2026-07-21T09:30:00Z",
    )

    ocr1 = ("El acta de la Cárnara Honda confirrna que Leire Onraita dirige 1a Hermandad del "
            "Esporo desde la ultima siembra.")
    ref1 = ("El acta de la Cámara Honda confirma que Leire Onraita dirige la Hermandad del "
            "Esporo desde la última siembra.")
    bbox1 = {"x": 0.07, "y": 0.11, "width": 0.72, "height": 0.06, "page": 1}
    e1 = s.episode(seq=1, modality="OCR_TEXT", text=ocr1, reference_text=ref1, page=1, bbox=bbox1,
                   quality_score=0.71, quality_flags=["OCR_DEGRADED_SURFACE"],
                   phenomena=["OCR_NOISE", "DUPLICATE_ACROSS_SOURCES"],
                   fragment_media_type="OCR_TEXT", fragment_bbox=bbox1)
    m_honda = s.mention(e1, "Cárnara Honda", entity_type="Location", confidence=0.74)
    m_leire = s.mention(e1, "Leire Onraita", entity_type="Character")
    m_herm = s.mention(e1, "Hermandad del Esporo", entity_type="Faction")
    c1 = s.claim(e1, key="leire-leads-hermandad", subject_mentions=[m_leire], object_mentions=[m_herm],
                 relation_phrase="dirige", predicate="LEADS", confidence=0.8,
                 phenomena=["OCR_NOISE", "DUPLICATE_ACROSS_SOURCES"])

    ocr2 = "La rubrica pertenece a 0nra1ta, segun el rnargen del acta."
    ref2 = "La rúbrica pertenece a Onraita, según el margen del acta."
    bbox2 = {"x": 0.07, "y": 0.34, "width": 0.55, "height": 0.06, "page": 1}
    e2 = s.episode(seq=2, modality="OCR_TEXT", text=ocr2, reference_text=ref2, page=1, bbox=bbox2,
                   quality_score=0.52, quality_flags=["OCR_DEGRADED_SURFACE"],
                   phenomena=["OCR_NOISE", "PROVISIONAL_ENTITY", "ABSTENTION"],
                   fragment_media_type="OCR_TEXT", fragment_bbox=bbox2)
    m_prov = s.mention(e2, "0nra1ta", entity_type=None, confidence=0.35)
    c2 = s.claim(e2, key="rubrica-abstencion", relation_phrase="pertenece a", predicate=None,
                 abstained=True, review_required=True,
                 epistemic_cues=["superficie degradada"], epistemic="UNKNOWN",
                 phenomena=["ABSTENTION", "OCR_NOISE"])

    plano = "Plano de galerías: la Cámara Yesca dibujada dentro del contorno de la Galería Ocre."
    bbox3 = {"x": 0.12, "y": 0.52, "width": 0.6, "height": 0.32, "page": 2}
    e3 = s.episode(seq=3, modality="DIAGRAM", text=plano, page=2, bbox=bbox3,
                   quality_score=0.6, phenomena=["VISUAL_INFERRED"],
                   fragment_media_type="DIAGRAM", fragment_bbox=bbox3)
    m3_yesca = s.mention(e3, "Cámara Yesca", entity_type="Location")
    m3_ocre = s.mention(e3, "Galería Ocre", entity_type="Location")
    c3 = s.claim(e3, key="yesca-in-ocre-visual", subject_mentions=[m3_yesca], object_mentions=[m3_ocre],
                 relation_phrase="dibujada dentro del contorno de", predicate="LOCATED_IN",
                 epistemic="VISUAL_INFERRED", review_required=True, confidence=0.55,
                 phenomena=["VISUAL_INFERRED"])

    s.link("camara-honda", [m_honda], "entity:micelio:camara-honda", "Location",
           reason_codes=["OCR_DEGRADED_SURFACE", "ALIAS_KNOWN_DEGRADATION"], confidence=0.72)
    s.link("leire", [m_leire], "entity:micelio:leire", "Character")
    s.link("hermandad", [m_herm], "entity:micelio:hermandad", "Faction")
    s.resolution(key="rubrica-provisional", mention_ids=[m_prov], action="CREATE_PROVISIONAL",
                 entity_type=None, assigned_entity_id="entity:prov:micelio:0nra1ta",
                 candidate_entity_ids=["entity:micelio:sabel", "entity:micelio:leire"],
                 reason_codes=["OCR_DEGRADED_SURFACE", "AMBIGUOUS_CANDIDATES"], confidence=0.3)
    s.link("camara-yesca", [m3_yesca], "entity:micelio:camara-yesca", "Location")
    s.link("galeria-ocre", [m3_ocre], "entity:micelio:galeria-ocre", "Location")

    d1 = accept("micelio-escaneo:d1", c1, a_leire_leads, reason="LOCAL_APPROVED_WITH_WARNINGS")
    d1["evidence_fragment_ids"] = s.claims[0]["evidence_fragment_ids"]
    d1["confidence"] = 0.8
    d2 = decision(key="micelio-escaneo:d2", claim_id=c2, decision_value="ABSTAIN",
                  reason_codes=["INSUFFICIENT_EVIDENCE", "LOW_QUALITY_EPISODE"],
                  evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"], confidence=0.2)
    d3 = decision(key="micelio-escaneo:d3", claim_id=c3, decision_value="REVIEW",
                  reason_codes=["REVIEW_EVIDENCE", "REVIEW_ENTITY"],
                  evidence_fragment_ids=s.claims[2]["evidence_fragment_ids"],
                  predicate="LOCATED_IN", direction="SUBJECT_TO_OBJECT",
                  subject_entity_id="entity:micelio:camara-yesca",
                  object_entity_id="entity:micelio:galeria-ocre",
                  epistemic_status="VISUAL_INFERRED", negated=False, confidence=0.55)
    ops = [noop_op("micelio-escaneo:d1", d1, a_leire_leads, s.claims[0]["evidence_fragment_ids"])]
    s.plan(key="p1", decisions=[d1, d2, d3], operations=ops, approved=False)
    return s


# ==========================================================================
# 6. liga-mesa  (transcripción con hablantes y primera persona)
# ==========================================================================
def build_liga_mesa() -> SourceGold:
    s = SourceGold(
        source_id="liga-mesa",
        world="liga",
        title="Mesa redonda de pretemporada",
        description="Turnos de habla: el mismo 'Yo' designa a dos personas, contrafactual y rumor.",
        source_kind="AUDIO",
        mime_type="audio/ogg",
        original_name="mesa-pretemporada.ogg",
        byte_size=98442,
        created_at="2026-06-30T00:00:00Z",
        ingested_at="2026-07-21T09:40:00Z",
    )
    sp_vero = {"speaker_id": "speaker:liga:vero", "label": "Vero", "confidence": 0.94}
    sp_hektor = {"speaker_id": "speaker:liga:hektor", "label": "Hektor", "confidence": 0.92}

    t1 = "Yo dejé el Club Aldabra en cuanto se firmó el traspaso; ahora entreno en el Canchón del Este."
    e1 = s.episode(seq=1, modality="SPEAKER_TURN", text=t1, speaker=sp_vero, turn=0,
                   time_start=0.0, time_end=9.0, phenomena=["SPEAKER_COREFERENCE", "TEMPORALITY"],
                   fragment_media_type="ASR_TEXT", fragment_times=(0.0, 9.0))
    m_yo1 = s.mention(e1, "Yo", entity_type="Character", kind="SPEAKER_SELF")
    m_ald = s.mention(e1, "Club Aldabra", entity_type="Faction")
    m_canchon = s.mention(e1, "Canchón del Este", entity_type="Location")
    c1 = s.claim(e1, key="vero-member-aldabra", subject_mentions=[m_yo1], object_mentions=[m_ald],
                 relation_phrase="dejé", predicate="MEMBER_OF",
                 temporal_expressions=[temporal("en cuanto se firmó el traspaso", "RELATIVE", CAL_L,
                                                valid_to="2026-06-15T00:00:00Z")],
                 phenomena=["SPEAKER_COREFERENCE", "TEMPORALITY"])
    c2 = s.claim(e1, key="vero-in-canchon", subject_mentions=[m_yo1], object_mentions=[m_canchon],
                 relation_phrase="entreno en", predicate="LOCATED_IN",
                 phenomena=["SPEAKER_COREFERENCE"])

    t2 = "Yo sigo en el Club Rompiente. Nuestro club y el Aldabra llevan tres temporadas enfrentados."
    e2 = s.episode(seq=2, modality="SPEAKER_TURN", text=t2, speaker=sp_hektor, turn=1,
                   time_start=9.0, time_end=18.0, phenomena=["SPEAKER_COREFERENCE", "SYMMETRIC"],
                   fragment_media_type="ASR_TEXT", fragment_times=(9.0, 18.0))
    m_yo2 = s.mention(e2, "Yo", entity_type="Character", kind="SPEAKER_SELF")
    m_romp = s.mention(e2, "Club Rompiente", entity_type="Faction")
    m_nuestro = s.mention(e2, "Nuestro club", entity_type="Faction", kind="NOMINAL")
    m_ald2 = s.mention(e2, "el Aldabra", entity_type="Faction", kind="NOMINAL")
    s.link_coreference(m_romp, m_nuestro)
    c3 = s.claim(e2, key="hektor-member-rompiente", subject_mentions=[m_yo2], object_mentions=[m_romp],
                 relation_phrase="sigo en", predicate="MEMBER_OF",
                 phenomena=["SPEAKER_COREFERENCE"])
    c4 = s.claim(e2, key="rompiente-rival-aldabra", subject_mentions=[m_nuestro],
                 object_mentions=[m_ald2], relation_phrase="llevan tres temporadas enfrentados",
                 predicate="RIVAL_OF", direction="UNDIRECTED",
                 temporal_expressions=[temporal("tres temporadas", "DURATION", CAL_L)],
                 phenomena=["SYMMETRIC", "COREFERENCE", "TEMPORALITY"])

    t3 = ("Si el Rompiente hubiera pagado la cláusula, yo estaría hoy en su plantilla. "
          "Corre el rumor de que Hektor Zuloaga volverá al Aldabra la próxima temporada.")
    e3 = s.episode(seq=3, modality="SPEAKER_TURN", text=t3, speaker=sp_vero, turn=2,
                   time_start=18.0, time_end=28.0, phenomena=["COUNTERFACTUAL", "RUMOR"],
                   fragment_media_type="ASR_TEXT", fragment_times=(18.0, 28.0))
    m3_romp = s.mention(e3, "el Rompiente", entity_type="Faction", kind="NOMINAL")
    m3_yo = s.mention(e3, "yo", entity_type="Character", kind="SPEAKER_SELF",
                      context="cláusula, yo estaría")
    m3_hektor = s.mention(e3, "Hektor Zuloaga", entity_type="Character")
    m3_ald = s.mention(e3, "Aldabra", entity_type="Faction", context="volverá al Aldabra")
    s.negative_span(e3, key="contrafactual-vero-rompiente",
                    literal="Si el Rompiente hubiera pagado la cláusula, yo estaría hoy en su plantilla",
                    kind="COUNTERFACTUAL", forbidden_predicates=["MEMBER_OF"],
                    rationale="El condicional irreal dice justamente que NO ocurrió.")
    c5 = s.claim(e3, key="hektor-member-aldabra", subject_mentions=[m3_hektor],
                 object_mentions=[m3_ald], relation_phrase="volverá al", predicate="MEMBER_OF",
                 epistemic="RUMORED", epistemic_cues=["Corre el rumor de que"], confidence=0.55,
                 temporal_expressions=[temporal("la próxima temporada", "RELATIVE", CAL_L)],
                 phenomena=["RUMOR", "TEMPORALITY"])

    s.link("vero", [m_yo1, m3_yo], "entity:liga:vero", "Character",
           reason_codes=["SPEAKER_DIARIZATION"])
    s.link("hektor", [m_yo2, m3_hektor], "entity:liga:hektor", "Character",
           reason_codes=["SPEAKER_DIARIZATION", "EXACT_ALIAS"])
    s.link("aldabra", [m_ald, m_ald2, m3_ald], "entity:liga:aldabra", "Faction")
    s.link("canchon", [m_canchon], "entity:liga:canchon", "Location")
    s.link("rompiente", [m_romp, m_nuestro, m3_romp], "entity:liga:rompiente", "Faction",
           reason_codes=["EXACT_ALIAS", "COREFERENCE_CHAIN"])

    a1 = A(s, key="vero-member-aldabra", subject_entity_id="entity:liga:vero",
           object_entity_id="entity:liga:aldabra", predicate="MEMBER_OF",
           episode_ids=[e1], evidence_fragment_ids=s.claims[0]["evidence_fragment_ids"],
           valid_to="2026-06-15T00:00:00Z", calendar_id=CAL_L, state="ENDED",
           phenomena=["TEMPORALITY"])
    a2 = A(s, key="vero-in-canchon", subject_entity_id="entity:liga:vero",
           object_entity_id="entity:liga:canchon", predicate="LOCATED_IN",
           episode_ids=[e1], evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"])
    a3 = A(s, key="hektor-member-rompiente", subject_entity_id="entity:liga:hektor",
           object_entity_id="entity:liga:rompiente", predicate="MEMBER_OF",
           episode_ids=[e2], evidence_fragment_ids=s.claims[2]["evidence_fragment_ids"])
    a4 = A(s, key="rompiente-rival-aldabra", subject_entity_id="entity:liga:rompiente",
           object_entity_id="entity:liga:aldabra", predicate="RIVAL_OF", direction="UNDIRECTED",
           episode_ids=[e2], evidence_fragment_ids=s.claims[3]["evidence_fragment_ids"],
           phenomena=["SYMMETRIC"])
    a5 = A(s, key="hektor-member-aldabra", subject_entity_id="entity:liga:hektor",
           object_entity_id="entity:liga:aldabra", predicate="MEMBER_OF",
           episode_ids=[e3], evidence_fragment_ids=s.claims[4]["evidence_fragment_ids"],
           epistemic_status="RUMORED", status="PROVISIONAL", state="PLANNED", confidence=0.5,
           phenomena=["RUMOR"])

    pares = [("d1", c1, a1), ("d2", c2, a2), ("d3", c3, a3), ("d4", c4, a4), ("d5", c5, a5)]
    decisions = [accept(f"liga-mesa:{k}", cid, a) for k, cid, a in pares]
    ops = [write_op(f"liga-mesa:{k}", d, a) for (k, _c, a), d in zip(pares, decisions)]
    s.plan(key="p1", decisions=decisions, operations=ops, approved=True)
    return s


# ==========================================================================
# 7. liga-audio-crudo  (ASR: confusiones fonéticas, sin puntuación)
# ==========================================================================
def build_liga_audio_crudo() -> SourceGold:
    s = SourceGold(
        source_id="liga-audio-crudo",
        world="liga",
        title="Corte de audio sin revisar",
        description="ASR crudo: confusiones fonéticas, sin puntuación, coordinación y condicional.",
        source_kind="AUDIO",
        mime_type="audio/ogg",
        original_name="corte-sin-revisar.ogg",
        byte_size=51120,
        created_at="2026-07-05T00:00:00Z",
        ingested_at="2026-07-21T09:50:00Z",
    )

    t1 = ("irune basterra ficho por el club farol y tan bien su ermana lorea por el club aldabra "
          "esta temporada")
    r1 = ("Irune Basterra fichó por el Club Farol y también su hermana Lorea por el Club Aldabra "
          "esta temporada.")
    e1 = s.episode(seq=1, modality="ASR_TEXT", text=t1, reference_text=r1,
                   time_start=0.0, time_end=7.5, quality_score=0.63,
                   quality_flags=["ASR_PHONETIC_SURFACE", "NO_PUNCTUATION"],
                   phenomena=["ASR_NOISE", "COORDINATION_MISPAIR", "SYMMETRIC"],
                   fragment_media_type="ASR_TEXT", fragment_times=(0.0, 7.5))
    m_irune = s.mention(e1, "irune basterra", entity_type="Character", confidence=0.8)
    m_farol = s.mention(e1, "club farol", entity_type="Faction", confidence=0.85)
    m_lorea = s.mention(e1, "lorea", entity_type="Character", confidence=0.7)
    m_ald = s.mention(e1, "club aldabra", entity_type="Faction", confidence=0.85)
    c1 = s.claim(e1, key="irune-member-farol", subject_mentions=[m_irune], object_mentions=[m_farol],
                 relation_phrase="ficho por", predicate="MEMBER_OF", confidence=0.78,
                 phenomena=["ASR_NOISE", "COORDINATION_MISPAIR"])
    c2 = s.claim(e1, key="lorea-member-aldabra", subject_mentions=[m_lorea], object_mentions=[m_ald],
                 relation_phrase="lorea por el club aldabra", predicate="MEMBER_OF", confidence=0.7,
                 phenomena=["ASR_NOISE", "COORDINATION_MISPAIR"])
    c3 = s.claim(e1, key="irune-sibling-lorea", subject_mentions=[m_irune], object_mentions=[m_lorea],
                 relation_phrase="su ermana", predicate="SIBLING_OF", direction="UNDIRECTED",
                 confidence=0.7, phenomena=["SYMMETRIC", "ASR_NOISE"])
    s.negative_pair(e1, key="coordinacion-irune-aldabra",
                    literal="y tan bien su ermana lorea por el club aldabra",
                    kind="COORDINATION_MISPAIR", subject_mentions=[m_irune], object_mentions=[m_ald],
                    forbidden_predicates=["MEMBER_OF"],
                    rationale="La segunda cláusula coordinada tiene sujeto propio: Irune no fichó por el Aldabra.")
    s.negative_pair(e1, key="coordinacion-lorea-farol",
                    literal="irune basterra ficho por el club farol",
                    kind="COORDINATION_MISPAIR", subject_mentions=[m_lorea], object_mentions=[m_farol],
                    forbidden_predicates=["MEMBER_OF"],
                    rationale="Lorea no aparece en la primera cláusula: emparejarla con el Farol es cruzar la coordinación.")

    t2 = "si el club farol asciende irune basterra dirigiria el equipo el año que biene"
    r2 = "Si el Club Farol asciende, Irune Basterra dirigiría el equipo el año que viene."
    e2 = s.episode(seq=2, modality="ASR_TEXT", text=t2, reference_text=r2,
                   time_start=7.5, time_end=13.0, quality_score=0.61,
                   quality_flags=["ASR_PHONETIC_SURFACE", "NO_PUNCTUATION"],
                   phenomena=["ASR_NOISE", "HYPOTHETICAL", "COREFERENCE"],
                   fragment_media_type="ASR_TEXT", fragment_times=(7.5, 13.0))
    m2_farol = s.mention(e2, "club farol", entity_type="Faction", confidence=0.85)
    m2_irune = s.mention(e2, "irune basterra", entity_type="Character", confidence=0.8)
    m2_equipo = s.mention(e2, "el equipo", entity_type="Faction", kind="NOMINAL", confidence=0.6)
    s.link_coreference(m2_farol, m2_equipo)
    c4 = s.claim(e2, key="irune-leads-farol", subject_mentions=[m2_irune], object_mentions=[m2_equipo],
                 relation_phrase="dirigiria", predicate="LEADS", epistemic="HYPOTHETICAL",
                 epistemic_cues=["si", "asciende"], confidence=0.55,
                 temporal_expressions=[temporal("el año que biene", "RELATIVE", CAL_L)],
                 phenomena=["HYPOTHETICAL", "ASR_NOISE", "COREFERENCE"])

    s.link("irune", [m_irune, m2_irune], "entity:liga:irune", "Character",
           reason_codes=["ASR_PHONETIC_SURFACE", "ALIAS_KNOWN_DEGRADATION"], confidence=0.8)
    s.link("farol", [m_farol, m2_farol, m2_equipo], "entity:liga:farol", "Faction",
           reason_codes=["EXACT_ALIAS", "COREFERENCE_CHAIN"])
    s.link("lorea", [m_lorea], "entity:liga:lorea", "Character",
           reason_codes=["ASR_PHONETIC_SURFACE"], confidence=0.68)
    s.link("aldabra", [m_ald], "entity:liga:aldabra", "Faction")

    a1 = A(s, key="irune-member-farol", subject_entity_id="entity:liga:irune",
           object_entity_id="entity:liga:farol", predicate="MEMBER_OF",
           episode_ids=[e1], evidence_fragment_ids=s.claims[0]["evidence_fragment_ids"],
           confidence=0.75, phenomena=["ASR_NOISE"])
    a2 = A(s, key="lorea-member-aldabra", subject_entity_id="entity:liga:lorea",
           object_entity_id="entity:liga:aldabra", predicate="MEMBER_OF",
           episode_ids=[e1], evidence_fragment_ids=s.claims[1]["evidence_fragment_ids"],
           confidence=0.68, phenomena=["ASR_NOISE"])
    a3 = A(s, key="irune-sibling-lorea", subject_entity_id="entity:liga:irune",
           object_entity_id="entity:liga:lorea", predicate="SIBLING_OF", direction="UNDIRECTED",
           episode_ids=[e1], evidence_fragment_ids=s.claims[2]["evidence_fragment_ids"],
           confidence=0.68, phenomena=["SYMMETRIC"])
    a4 = A(s, key="irune-leads-farol", subject_entity_id="entity:liga:irune",
           object_entity_id="entity:liga:farol", predicate="LEADS",
           episode_ids=[e2], evidence_fragment_ids=s.claims[3]["evidence_fragment_ids"],
           epistemic_status="HYPOTHETICAL", status="PROVISIONAL", state="HYPOTHETICAL",
           confidence=0.5, calendar_id=CAL_L, phenomena=["HYPOTHETICAL"])

    pares = [("d1", c1, a1), ("d2", c2, a2), ("d3", c3, a3), ("d4", c4, a4)]
    decisions = [accept(f"liga-audio-crudo:{k}", cid, a) for k, cid, a in pares]
    ops = [write_op(f"liga-audio-crudo:{k}", d, a) for (k, _c, a), d in zip(pares, decisions)]
    s.plan(key="p1", decisions=decisions, operations=ops, approved=True)
    return s


# ==========================================================================
# Ensamblado
# ==========================================================================
def build_sources() -> list[SourceGold]:
    memoria = build_ferrovia_memoria()
    cartas = build_ferrovia_cartas()
    by_key = {a["metadata"]["gold_key"]: a for a in memoria.assertions}
    tabla = build_ferrovia_tabla(by_key["iker-member-trasandina"], by_key["nerea-member-norte"])
    wiki = build_micelio_wiki()
    wiki_by_key = {a["metadata"]["gold_key"]: a for a in wiki.assertions}
    escaneo = build_micelio_escaneo(wiki_by_key["leire-leads-hermandad"])
    mesa = build_liga_mesa()
    audio = build_liga_audio_crudo()
    return [memoria, cartas, tabla, wiki, escaneo, mesa, audio]


SOURCE_FILES = (
    ("source_asset", None),
    ("episodes", "episodes"),
    ("fragments", "fragments"),
    ("mentions", "mentions"),
    ("resolutions", "resolutions"),
    ("claims", "claims"),
    ("assertions", "assertions"),
    ("plans", "plans"),
    ("negatives", "negatives"),
)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _wrap(kind: str, source: SourceGold | None, documents: list[Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_file": kind,
        "split": SPLIT,
        "dataset_version": DATASET_VERSION,
        "format_version": FORMAT_VERSION,
        "documents": documents,
    }
    if source is not None:
        payload["source_id"] = source.source_id
        payload["world"] = source.world
    return payload


def _phenomena(src: SourceGold) -> list[str]:
    seen: set[str] = set()
    for ep in src.episodes:
        seen.update(ep["metadata"].get("phenomena") or [])
    for c in src.claims:
        seen.update(c["metadata"].get("phenomena") or [])
    for a in src.assertions:
        seen.update(a["metadata"].get("phenomena") or [])
    for n in src.negatives:
        seen.add(n["kind"])
    return sorted(seen)


def _counts(src: SourceGold) -> dict[str, int]:
    extractor = [c for c in src.claims
                 if c["metadata"].get("role", "EXTRACTOR_AND_ENGINE") == "EXTRACTOR_AND_ENGINE"]
    return {
        "episodes": len(src.episodes),
        "fragments": len(src.fragments),
        "mentions": len(src.mentions),
        "resolutions": len(src.resolutions),
        "claims": len(src.claims),
        "claims_extractor_gold": len(extractor),
        "assertions": len(src.assertions),
        "plans": len(src.plans),
        "decisions": sum(len(p["decisions"]) for p in src.plans),
        "operations": sum(len(p["mutation_operations"]) for p in src.plans),
        "negatives": len(src.negatives),
    }


def build_dataset() -> dict[str, str]:
    sources = build_sources()
    files: dict[str, str] = {}
    files[f"{SPLIT}/catalog/entities.json"] = dumps(entity_catalog())
    files[f"{SPLIT}/catalog/game_profile_generic.json"] = dumps(
        _wrap("game_profile", None, [game_profile_gold()]))
    files[f"{SPLIT}/catalog/game_profile_narrow.json"] = dumps(
        _wrap("game_profile", None, [game_profile_narrow()]))

    manifest_sources = []
    for src in sources:
        base = f"{SPLIT}/sources/{src.source_id}"
        for kind, attr in SOURCE_FILES:
            documents = [src.asset] if attr is None else getattr(src, attr)
            files[f"{base}/{kind}.json"] = dumps(_wrap(kind, src, documents))
        files[f"{base}/reference_text.json"] = dumps(
            _wrap("reference_text", src,
                  [{"episode_id": eid, "text": txt} for eid, txt in sorted(src.reference_text.items())]))
        manifest_sources.append({
            "source_id": src.source_id,
            "world": src.world,
            "title": src.title,
            "description": src.description,
            "source_kind": src.asset["source_kind"],
            "collection_id": src.collection_id,
            "modalities": sorted({e["modality"] for e in src.episodes}),
            "counts": _counts(src),
            "phenomena": _phenomena(src),
        })

    totals: dict[str, int] = {}
    for entry in manifest_sources:
        for k, v in entry["counts"].items():
            totals[k] = totals.get(k, 0) + v

    phenomena_index: dict[str, list[str]] = {}
    for entry in manifest_sources:
        for ph in entry["phenomena"]:
            phenomena_index.setdefault(ph, []).append(entry["source_id"])

    manifest = {
        "benchmark_file": "manifest",
        "split": SPLIT,
        "dataset_version": DATASET_VERSION,
        "format_version": FORMAT_VERSION,
        "purpose": (
            "Dataset gold HELD-OUT, preparado por el equipo independiente (dosier §9). "
            "Mundos, vocabulario y redaccion disjuntos de `dev`. Quien implementa los "
            "subsistemas NO lo usa para ajustar: una cifra de dev en la columna de "
            "held-out es exactamente el error que costo 0.81 -> 0.24 en el motor v2."
        ),
        "independence": {
            "authored_by": "equipo independiente held-out",
            "double_pass": True,
            "not_read": [
                "data-engine/app/knowledge_v3/extraction/",
                "data-engine/app/knowledge_v3/engine/",
                "data-engine/app/knowledge_v3/resolution/",
            ],
            "read": [
                "contracts/knowledge-v3/v1/ (schemas y validador congelados)",
                "estructura de datasets/dev y benchmarks/loader.py",
                "docs/v3/08-benchmarks.md (§2.1.1, §2.3, §2.4, §3.6, §7) y docs/v3/01-contracts-v3.md",
            ],
        },
        "catalog_files": [
            "catalog/entities.json",
            "catalog/game_profile_generic.json",
            "catalog/game_profile_narrow.json",
        ],
        "sources": manifest_sources,
        "totals": totals,
        "phenomena_index": {k: sorted(v) for k, v in sorted(phenomena_index.items())},
        "file_hashes": {
            path: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for path, content in sorted(files.items())
        },
    }
    files[f"{SPLIT}/manifest.json"] = dumps(manifest)
    return files


def write_dataset(root: Path | None = None) -> list[Path]:
    root = root or DATASETS_DIR
    written = []
    for rel, content in sorted(build_dataset().items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def check_dataset(root: Path | None = None) -> list[str]:
    root = root or DATASETS_DIR
    drift = []
    for rel, content in sorted(build_dataset().items()):
        path = root / rel
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            drift.append(rel)
    return drift


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--check" in argv:
        drift = check_dataset()
        if drift:
            print("dataset held-out derivado respecto a la autoria:")
            for rel in drift:
                print(f"  {rel}")
            return 1
        print("dataset held-out al dia")
        return 0
    paths = write_dataset()
    print(f"escritos {len(paths)} ficheros en {DATASETS_DIR / SPLIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
