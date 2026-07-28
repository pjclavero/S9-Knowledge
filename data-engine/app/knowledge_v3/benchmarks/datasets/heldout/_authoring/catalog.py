# -*- coding: utf-8 -*-
"""Catalogo de entidades y perfiles de juego del split HELD-OUT.

Tres mundos NUEVOS, de generos distintos entre si y disjuntos de los de `dev`:
ni corte medieval, ni archipielago marinero, ni estaciones orbitales. El
vocabulario (nombres propios, facciones, lugares, objetos) no comparte una sola
forma con el split de desarrollo: si un extractor rinde aqui, no es porque haya
memorizado un lexico.

La ONTOLOGIA (los diez predicados) si es la misma que la de `dev`, y a
proposito: el predicado canonico es la frontera de contrato contra la que se
mide, no contenido del split. Cambiarla mediria otra tarea.
"""
from __future__ import annotations

from typing import Any

from .gold import CONTRACT_VERSION, DATASET_VERSION, GAME_PROFILE, SPLIT, WORKSPACE, h, trace

WORLDS = {
    "ferrovia": "Via estrecha de montana: companias concesionarias, tuneles y talleres (siglo XIX).",
    "micelio": "Galerias de esporas: hermandades de cultivo, camaras y conclaves (biopunk subterraneo).",
    "liga": "Liga urbana de pelota: clubes, canchones y traspasos (deporte contemporaneo).",
}

ENTITIES: list[dict[str, Any]] = [
    # --- mundo ferrovia ----------------------------------------------------
    {
        "entity_id": "entity:ferrovia:maren",
        "world": "ferrovia",
        "name": "Maren Ibarrola",
        "type": "Character",
        "aliases": ["Maren", "Maren Ibarrola", "Ibarrola"],
        "note": "Primera de la cadena de direccion de la Compañía del Norte (1893-1897).",
    },
    {
        "entity_id": "entity:ferrovia:iker",
        "world": "ferrovia",
        "name": "Iker Lasalde",
        "type": "Character",
        "aliases": ["Iker", "Iker Lasalde", "el hermano de Nerea Lasalde"],
        "note": (
            "Hermano de Nerea. Su pertenencia a Trasandina Unida la afirma la memoria "
            "y la niega la carta del 9 de mayo: conflicto registrado en los dos signos."
        ),
    },
    {
        "entity_id": "entity:ferrovia:nerea",
        "world": "ferrovia",
        "name": "Nerea Lasalde",
        "type": "Character",
        "aliases": ["Nerea", "Nerea Lasalde"],
        "note": "Hermana de Iker. 'Lasalde' a secas NO desambigua y no se usa como superficie.",
    },
    {
        "entity_id": "entity:ferrovia:txomin",
        "world": "ferrovia",
        "name": "Txomin Ereña",
        "type": "Character",
        "aliases": ["Txomin Ereña"],
        "note": "Solo aparece en la tabla. El gold espera CREATE_NEW, no un enlace forzado.",
        "expected_action": "CREATE_NEW",
    },
    {
        "entity_id": "entity:ferrovia:norte",
        "world": "ferrovia",
        "name": "Compañía del Norte",
        "type": "Faction",
        "aliases": ["Compañía del Norte", "la Compañía"],
        "note": "",
    },
    {
        "entity_id": "entity:ferrovia:trasandina",
        "world": "ferrovia",
        "name": "Trasandina Unida",
        "type": "Faction",
        "aliases": ["Trasandina Unida", "la Trasandina"],
        "note": "",
    },
    {
        "entity_id": "entity:ferrovia:aizkorri",
        "world": "ferrovia",
        "name": "Túnel de Aizkorri",
        "type": "Location",
        "aliases": ["Túnel de Aizkorri"],
        "note": "",
    },
    {
        "entity_id": "entity:ferrovia:portazgo",
        "world": "ferrovia",
        "name": "Estación de Portazgo",
        "type": "Location",
        "aliases": ["Estación de Portazgo", "Portazgo"],
        "note": "El encabezado de las cartas ('Portazgo, 14 de marzo...') es lugar de emision, no mencion util.",
    },
    {
        "entity_id": "entity:ferrovia:cierzo",
        "world": "ferrovia",
        "name": "Locomotora Cierzo",
        "type": "Object",
        "aliases": ["Locomotora Cierzo", "locomotora Cierzo", "Cierzo"],
        "note": "Su propiedad es objeto de un rumor DESMENTIDO en la carta del 2 de abril.",
    },
    # --- mundo micelio -----------------------------------------------------
    {
        "entity_id": "entity:micelio:sabel",
        "world": "micelio",
        "name": "Sabel Onraita",
        "type": "Character",
        "aliases": ["Sabel", "Sabel Onraita"],
        "note": "Hermana de Leire. Aparece en dos trampas: una pregunta y un sujeto-modificador.",
    },
    {
        "entity_id": "entity:micelio:leire",
        "world": "micelio",
        "name": "Leire Onraita",
        "type": "Character",
        "aliases": ["Leire", "Leire Onraita", "La hermana de Sabel Onraita"],
        "note": "Dirige la Hermandad. Es quien manda, no Sabel: el modificador enganya.",
    },
    {
        "entity_id": "entity:micelio:hermandad",
        "world": "micelio",
        "name": "Hermandad del Esporo",
        "type": "Faction",
        "aliases": ["Hermandad del Esporo", "la Hermandad"],
        "note": "",
    },
    {
        "entity_id": "entity:micelio:conclave",
        "world": "micelio",
        "name": "Cónclave Lívido",
        "type": "Faction",
        "aliases": ["Cónclave Lívido", "el Cónclave"],
        "note": "",
    },
    {
        "entity_id": "entity:micelio:camara-honda",
        "world": "micelio",
        "name": "Cámara Honda",
        "type": "Location",
        "aliases": ["Cámara Honda", "Cárnara Honda"],
        "note": "'Cárnara Honda' es degradacion de OCR (m -> rn), no otro lugar.",
    },
    {
        "entity_id": "entity:micelio:galeria-ocre",
        "world": "micelio",
        "name": "Galería Ocre",
        "type": "Location",
        "aliases": ["Galería Ocre"],
        "note": "",
    },
    {
        "entity_id": "entity:micelio:camara-yesca",
        "world": "micelio",
        "name": "Cámara Yesca",
        "type": "Location",
        "aliases": ["Cámara Yesca"],
        "note": "Su ubicacion solo se infiere de un plano: VISUAL_INFERRED, con revision.",
    },
    {
        "entity_id": "entity:prov:micelio:0nra1ta",
        "world": "micelio",
        "name": "0nra1ta",
        "type": None,
        "aliases": ["0nra1ta"],
        "note": (
            "Entidad PROVISIONAL. Se parece a Onraita, pero hay DOS Onraita en el "
            "mundo (Sabel y Leire) y la superficie viene degradada por OCR (O->0, "
            "i->1): fundirla seria elegir hermana a cara o cruz."
        ),
        "expected_action": "CREATE_PROVISIONAL",
        "provisional": True,
    },
    # --- mundo liga --------------------------------------------------------
    {
        "entity_id": "entity:liga:vero",
        "world": "liga",
        "name": "Vero Anchorena",
        "type": "Character",
        "aliases": ["Vero", "Vero Anchorena"],
        "note": "Primera persona en el turno 0 y en el turno 2 de la mesa.",
    },
    {
        "entity_id": "entity:liga:hektor",
        "world": "liga",
        "name": "Hektor Zuloaga",
        "type": "Character",
        "aliases": ["Hektor", "Hektor Zuloaga"],
        "note": "Primera persona en el turno 1: el mismo 'Yo' que en el turno 0 designa a otra persona.",
    },
    {
        "entity_id": "entity:liga:irune",
        "world": "liga",
        "name": "Irune Basterra",
        "type": "Character",
        "aliases": ["Irune Basterra", "irune basterra"],
        "note": "Aparece solo en el audio crudo, en minusculas y sin puntuacion.",
    },
    {
        "entity_id": "entity:liga:lorea",
        "world": "liga",
        "name": "Lorea Basterra",
        "type": "Character",
        "aliases": ["Lorea Basterra", "lorea"],
        "note": "Hermana de Irune. El ASR se come la hache de 'hermana'.",
    },
    {
        "entity_id": "entity:liga:rompiente",
        "world": "liga",
        "name": "Club Rompiente",
        "type": "Faction",
        "aliases": ["Club Rompiente", "el Rompiente", "Nuestro club"],
        "note": "",
    },
    {
        "entity_id": "entity:liga:aldabra",
        "world": "liga",
        "name": "Club Aldabra",
        "type": "Faction",
        "aliases": ["Club Aldabra", "el Aldabra", "Aldabra", "club aldabra"],
        "note": "",
    },
    {
        "entity_id": "entity:liga:farol",
        "world": "liga",
        "name": "Club Farol",
        "type": "Faction",
        "aliases": ["Club Farol", "club farol", "el equipo"],
        "note": "",
    },
    {
        "entity_id": "entity:liga:canchon",
        "world": "liga",
        "name": "Canchón del Este",
        "type": "Location",
        "aliases": ["Canchón del Este"],
        "note": "",
    },
]

ENTITY_TYPE_BY_ID = {e["entity_id"]: e["type"] for e in ENTITIES}

#: Misma ontologia que el perfil `generic` de dev: es frontera de contrato, no
#: contenido del split. Lo que cambia es TODO lo demas del perfil.
_PREDICATES: list[dict[str, Any]] = [
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

SYMMETRIC_PREDICATES = frozenset(p["predicate"] for p in _PREDICATES if p.get("symmetric"))


def _profile(profile_id: str, predicates: list[dict[str, Any]], role: str) -> dict[str, Any]:
    source = f"profile:heldout:{profile_id}"
    return {
        "contract_id": "game-profile/v3-internal-v1",
        "contract_version": CONTRACT_VERSION,
        "workspace": WORKSPACE,
        "source_asset_id": source,
        "source_hash": h(source),
        "provider_trace": [trace("gold.profile", ["predicates", "entity_types"])],
        "produced_by_step": "gold.profile",
        "profile_id": profile_id,
        "profile_version": DATASET_VERSION,
        "core_ontology_version": "core-1.4.0",
        "entity_types": ["Character", "Location", "Faction", "Object", "Event", "Concept"],
        "predicates": predicates,
        "aliases": [{"canonical": e["name"], "variants": e["aliases"]} for e in ENTITIES if e["aliases"]],
        "titles": ["ingeniera jefa", "concesionario", "cultivadora mayor", "entrenador"],
        "factions": [e["name"] for e in ENTITIES if e["type"] == "Faction"],
        "calendars": [
            {"calendar_id": "calendar:ferrovia", "epoch_label": "Cuenta de concesiones",
             "units": ["temporada", "invierno"]},
            {"calendar_id": "calendar:micelio", "epoch_label": "Ciclo de siembra",
             "units": ["siembra", "solsticio"]},
            {"calendar_id": "calendar:liga", "epoch_label": "Calendario de liga",
             "units": ["temporada", "jornada"]},
        ],
        "identity_rules": [
            {
                "rule_id": "rule:modificador-no-es-sujeto",
                "kind": "NEVER_MERGE_IF",
                "reason_code": "MODIFIER_ONLY_MATCH",
                "description": "Aparecer dentro del modificador de un sujeto no convierte a nadie en ese sujeto.",
            },
            {
                "rule_id": "rule:ocr-ambiguo-revisa",
                "kind": "REQUIRE_REVIEW_IF",
                "reason_code": "OCR_DEGRADED_SURFACE",
                "description": "Superficie degradada compatible con dos entidades del catalogo: provisional y revision.",
            },
            {
                "rule_id": "rule:asr-fonetico-revisa",
                "kind": "REQUIRE_REVIEW_IF",
                "reason_code": "ASR_PHONETIC_SURFACE",
                "description": "Confusion fonetica de ASR: se enlaza solo si el alias esta declarado.",
            },
        ],
        "ambiguous_terms": [
            "la Compañía", "la Trasandina", "la Hermandad", "el Cónclave",
            "Nuestro club", "el equipo", "Lasalde", "Onraita", "Basterra",
        ],
        "source_priorities": [
            {"source_kind": "MARKDOWN", "priority": 80},
            {"source_kind": "TEXT", "priority": 75},
            {"source_kind": "TABLE", "priority": 70},
            {"source_kind": "WEB", "priority": 60},
            {"source_kind": "AUDIO", "priority": 45},
            {"source_kind": "IMAGE", "priority": 30},
        ],
        "evaluation_examples": [
            {
                "example_id": "example:coordinacion",
                "text": "A entro en la primera compania y tambien B entro en la segunda.",
                "expected": "dos MEMBER_OF cruzados NO: A con la primera, B con la segunda",
            },
            {
                "example_id": "example:modificador",
                "text": "El hermano de A firmo el arriendo.",
                "expected": "el sujeto es el hermano, no A",
            },
        ],
        "learned_adapter": {"adapter_id": "adapter:none", "enabled": False},
        "metadata": {
            "benchmark": {"split": SPLIT, "dataset_version": DATASET_VERSION, "role": role}
        },
    }


def game_profile_gold() -> dict[str, Any]:
    return _profile(GAME_PROFILE, _PREDICATES, "perfil correcto del split held-out")


def game_profile_narrow() -> dict[str, Any]:
    """Perfil incompleto para la ablacion 'perfil incorrecto' (mismo criterio que dev)."""
    keep = {"MEMBER_OF", "HAS_MEMBER", "LOCATED_IN", "ALLY_OF"}
    preds = [
        {**p, "inverse_of": p["inverse_of"] if p["inverse_of"] in keep else None}
        for p in _PREDICATES
        if p["predicate"] in keep
    ]
    return _profile("bench-narrow", preds, "perfil incompleto para la ablacion")


def entity_catalog() -> dict[str, Any]:
    return {
        "benchmark_file": "entities",
        "split": SPLIT,
        "dataset_version": DATASET_VERSION,
        "worlds": WORLDS,
        "entities": ENTITIES,
    }
