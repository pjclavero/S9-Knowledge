# -*- coding: utf-8 -*-
"""Catalogo gold de entidades y perfiles de juego del dataset de desarrollo.

El catalogo de entidades NO es un contrato `v3-internal-v1`: los contratos
describen lo que produce el pipeline, y una entidad canonica es un dato de
referencia del benchmark. Tiene por tanto schema propio, minimo y documentado
en docs/v3/08-benchmarks.md.

Las entidades son de MUNDO, no de fuente: el mismo personaje aparece en la
cronica, en la transcripcion y en la tabla, y esa es justamente la gracia.
"""
from __future__ import annotations

from typing import Any

from ..contracts_bridge import CONTRACT_VERSION
from .common import DATASET_VERSION, GAME_PROFILE, WORKSPACE, h, trace

#: Los tres mundos del dataset de desarrollo. Deliberadamente distintos entre
#: si (corte medieval, archipielago gremial, estaciones orbitales) para que un
#: extractor no pueda acertar por memorizar un unico vocabulario.
WORLDS = {
    "leyenda": "Cronica de corte medieval: casas, cargos y juramentos.",
    "mareas": "Archipielago de gremios marineros, mareas y talleres.",
    "kestrel": "Estaciones orbitales, consorcios y registros de tripulacion.",
}

#: entity_id -> ficha. `aliases` incluye las formas de superficie que el gold
#: espera ver resueltas a esta entidad, incluidas las degradadas por OCR.
ENTITIES: list[dict[str, Any]] = [
    # --- mundo leyenda -----------------------------------------------------
    {
        "entity_id": "entity:leyenda:daiki",
        "world": "leyenda",
        "name": "Daiki Oharu",
        "type": "Character",
        "aliases": ["Daiki", "Daiki Oharu", "Oharu", "Daiki Oliaru"],
        "note": "Magistrado desde 1042. 'Daiki Oliaru' es una degradacion de OCR, no otra persona.",
    },
    {
        "entity_id": "entity:leyenda:ilaria",
        "world": "leyenda",
        "name": "Ilaria Vandreth",
        "type": "Character",
        "aliases": ["Ilaria", "Ilaria Vandreth", "Vandreth"],
        "note": "Predecesora de Daiki al frente de la Casa del Ciervo.",
    },
    {
        "entity_id": "entity:leyenda:casa-ciervo",
        "world": "leyenda",
        "name": "Casa del Ciervo",
        "type": "Faction",
        "aliases": ["Casa del Ciervo", "la Casa", "Casa de1 Ciervo"],
        "note": "'Casa de1 Ciervo' es degradacion de OCR (l -> 1).",
    },
    {
        "entity_id": "entity:leyenda:consejo-umbra",
        "world": "leyenda",
        "name": "Consejo de Umbra",
        "type": "Faction",
        "aliases": ["Consejo de Umbra", "el Consejo"],
        "note": "",
    },
    {
        "entity_id": "entity:leyenda:vado-alto",
        "world": "leyenda",
        "name": "Vado Alto",
        "type": "Location",
        "aliases": ["Vado Alto"],
        "note": "",
    },
    # --- mundo mareas ------------------------------------------------------
    {
        "entity_id": "entity:mareas:sela",
        "world": "mareas",
        "name": "Sela Marrec",
        "type": "Character",
        "aliases": ["Sela", "Sela Marrec", "la tallista"],
        "note": "Hermana de Torv. Habla en primera persona en la transcripcion.",
    },
    {
        "entity_id": "entity:mareas:torv",
        "world": "mareas",
        "name": "Torv Marrec",
        "type": "Character",
        "aliases": ["Torv", "Torv Marrec"],
        "note": "",
    },
    {
        "entity_id": "entity:mareas:gremio-faros",
        "world": "mareas",
        "name": "Gremio de Faros",
        "type": "Faction",
        "aliases": ["Gremio de Faros", "el Gremio"],
        "note": "",
    },
    {
        "entity_id": "entity:mareas:cofradia-ambar",
        "world": "mareas",
        "name": "Cofradia de Ambar",
        "type": "Faction",
        "aliases": ["Cofradia de Ambar", "la Cofradia"],
        "note": "",
    },
    {
        "entity_id": "entity:mareas:puerto-quilla",
        "world": "mareas",
        "name": "Puerto Quilla",
        "type": "Location",
        "aliases": ["Puerto Quilla"],
        "note": "",
    },
    {
        "entity_id": "entity:mareas:amarra-vieja",
        "world": "mareas",
        "name": "Amarra Vieja",
        "type": "Location",
        "aliases": ["Amarra Vieja"],
        "note": "Barrio dentro de Puerto Quilla.",
    },
    # --- mundo kestrel -----------------------------------------------------
    {
        "entity_id": "entity:kestrel:vania",
        "world": "kestrel",
        "name": "Vania Ostrow",
        "type": "Character",
        "aliases": ["Vania", "Vania Ostrow", "Ostrow"],
        "note": "",
    },
    {
        "entity_id": "entity:kestrel:nadir",
        "world": "kestrel",
        "name": "Nadir Boone",
        "type": "Character",
        "aliases": ["Nadir", "Nadir Boone", "Boone"],
        "note": "Su pertenencia al Consorcio la niega el informe y la afirma la tabla.",
    },
    {
        "entity_id": "entity:kestrel:halcyon",
        "world": "kestrel",
        "name": "Consorcio Halcyon",
        "type": "Faction",
        "aliases": ["Consorcio Halcyon", "Halcyon", "el Consorcio"],
        "note": "",
    },
    {
        "entity_id": "entity:kestrel:vela",
        "world": "kestrel",
        "name": "Cooperativa Vela",
        "type": "Faction",
        "aliases": ["Cooperativa Vela", "Vela"],
        "note": "",
    },
    {
        "entity_id": "entity:kestrel:estacion",
        "world": "kestrel",
        "name": "Estacion Kestrel",
        "type": "Location",
        "aliases": ["Estacion Kestrel", "la estacion"],
        "note": "",
    },
    {
        "entity_id": "entity:kestrel:nucleo-bruma",
        "world": "kestrel",
        "name": "Nucleo Bruma",
        "type": "Object",
        "aliases": ["Nucleo Bruma"],
        "note": "",
    },
    {
        "entity_id": "entity:kestrel:ruta-simm",
        "world": "kestrel",
        "name": "Ruta Simm",
        "type": "Character",
        "aliases": ["Ruta Simm"],
        "note": "Solo aparece en la tabla. El gold espera CREATE_NEW, no un enlace forzado.",
        "expected_action": "CREATE_NEW",
    },
    {
        "entity_id": "entity:prov:leyenda:v4ndreth",
        "world": "leyenda",
        "name": "V4ndreth",
        "type": None,
        "aliases": ["V4ndreth"],
        "note": (
            "Entidad PROVISIONAL. Se parece a Ilaria Vandreth, pero una superficie "
            "degradada por OCR no autoriza a fundir identidades: la regla de "
            "identidad del perfil exige revision."
        ),
        "expected_action": "CREATE_PROVISIONAL",
        "provisional": True,
    },
]

#: Predicados del perfil gold. `symmetric` importa para el emparejamiento de
#: hechos: en un predicado simetrico, (A,B) y (B,A) son el MISMO hecho.
_PREDICATES: list[dict[str, Any]] = [
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
        "predicate": "LEADS",
        "domain": ["Character"],
        "range": ["Faction"],
        "symmetric": False,
        "transitive": False,
        "functional": True,
        "inverse_of": "LED_BY",
    },
    {
        "predicate": "LED_BY",
        "domain": ["Faction"],
        "range": ["Character"],
        "symmetric": False,
        "transitive": False,
        "functional": False,
        "inverse_of": "LEADS",
    },
    {
        "predicate": "LOCATED_IN",
        "domain": ["Character", "Object", "Location", "Event", "Faction"],
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
    {
        "predicate": "RIVAL_OF",
        "domain": ["Character", "Faction"],
        "range": ["Character", "Faction"],
        "symmetric": True,
        "transitive": False,
        "functional": False,
        "inverse_of": None,
    },
    {
        "predicate": "SIBLING_OF",
        "domain": ["Character"],
        "range": ["Character"],
        "symmetric": True,
        "transitive": False,
        "functional": False,
        "inverse_of": None,
    },
    {
        "predicate": "OWNS",
        "domain": ["Character", "Faction"],
        "range": ["Object", "Location"],
        "symmetric": False,
        "transitive": False,
        "functional": False,
        "inverse_of": "OWNED_BY",
    },
    {
        "predicate": "OWNED_BY",
        "domain": ["Object", "Location"],
        "range": ["Character", "Faction"],
        "symmetric": False,
        "transitive": False,
        "functional": False,
        "inverse_of": "OWNS",
    },
]

#: Predicados simetricos, derivados del perfil. El arnes los necesita para
#: canonizar hechos; se derivan, no se cablean.
SYMMETRIC_PREDICATES = frozenset(p["predicate"] for p in _PREDICATES if p.get("symmetric"))

#: Pares inversos declarados en el perfil.
INVERSE_PREDICATES = {
    p["predicate"]: p["inverse_of"] for p in _PREDICATES if p.get("inverse_of")
}


def _profile(
    profile_id: str, predicates: list[dict[str, Any]], note: str
) -> dict[str, Any]:
    source = f"profile:{profile_id}"
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
        "aliases": [
            {"canonical": e["name"], "variants": e["aliases"]}
            for e in ENTITIES
            if e["aliases"]
        ],
        "titles": ["magistrado", "senescal", "maestra de faros", "jefa de operaciones"],
        "factions": [e["name"] for e in ENTITIES if e["type"] == "Faction"],
        "calendars": [
            {
                "calendar_id": "calendar:leyenda",
                "epoch_label": "Era del Ciervo",
                "units": ["ciclo", "luna"],
            },
            {
                "calendar_id": "calendar:mareas",
                "epoch_label": "Cuenta de Mareas",
                "units": ["marea", "temporada"],
            },
            {
                "calendar_id": "calendar:kestrel",
                "epoch_label": "Ciclo orbital",
                "units": ["ciclo", "turno"],
            },
        ],
        "identity_rules": [
            {
                "rule_id": "rule:titulo-no-funde",
                "kind": "NEVER_MERGE_IF",
                "reason_code": "TITLE_ONLY_MATCH",
                "description": "Compartir cargo no basta para fundir dos personajes.",
            },
            {
                "rule_id": "rule:ocr-revisa",
                "kind": "REQUIRE_REVIEW_IF",
                "reason_code": "OCR_DEGRADED_SURFACE",
                "description": "Una superficie degradada por OCR se revisa antes de fundirla.",
            },
        ],
        "ambiguous_terms": ["el Consejo", "la Casa", "el Gremio", "la Cofradia", "la estacion"],
        "source_priorities": [
            {"source_kind": "MARKDOWN", "priority": 80},
            {"source_kind": "TABLE", "priority": 70},
            {"source_kind": "AUDIO", "priority": 50},
            {"source_kind": "IMAGE", "priority": 30},
        ],
        "evaluation_examples": [
            {
                "example_id": "example:negacion",
                "text": "El registro no incluye a ese tripulante entre el personal del consorcio.",
                "expected": "NEGATED MEMBER_OF",
            },
            {
                "example_id": "example:simetrica",
                "text": "Los dos gremios llevan una temporada enfrentados.",
                "expected": "RIVAL_OF (simetrica)",
            },
        ],
        "learned_adapter": {"adapter_id": "adapter:none", "enabled": False},
        "metadata": {
            "benchmark": {
                "split": "dev",
                "dataset_version": DATASET_VERSION,
                "role": note,
            }
        },
    }


def game_profile_gold() -> dict[str, Any]:
    """Perfil correcto: el que el motor debe usar en la corrida nominal."""
    return _profile(GAME_PROFILE, _PREDICATES, "perfil correcto del dataset")


def game_profile_narrow() -> dict[str, Any]:
    """Perfil DELIBERADAMENTE incompleto, para la ablacion 'perfil incorrecto'.

    Se queda sin LEADS, sin RIVAL_OF y sin SIBLING_OF: un motor que corra con
    el debe abstenerse o pedir revision, no inventarse el predicado mas
    parecido. La ablacion sirve precisamente para medir eso.
    """
    keep = {"MEMBER_OF", "HAS_MEMBER", "LOCATED_IN", "ALLY_OF"}
    preds = [
        {**p, "inverse_of": p["inverse_of"] if p["inverse_of"] in keep else None}
        for p in _PREDICATES
        if p["predicate"] in keep
    ]
    return _profile("bench-narrow", preds, "perfil incompleto para la ablacion")


def entity_catalog() -> dict[str, Any]:
    """Fichero de catalogo, con su marca de split."""
    return {
        "benchmark_file": "entities",
        "split": "dev",
        "dataset_version": DATASET_VERSION,
        "worlds": WORLDS,
        "entities": ENTITIES,
    }


ENTITY_TYPE_BY_ID = {e["entity_id"]: e["type"] for e in ENTITIES}

__all__ = [
    "ENTITIES",
    "ENTITY_TYPE_BY_ID",
    "INVERSE_PREDICATES",
    "SYMMETRIC_PREDICATES",
    "WORLDS",
    "entity_catalog",
    "game_profile_gold",
    "game_profile_narrow",
]
