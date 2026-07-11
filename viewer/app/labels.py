"""Traducción de tipos de nodo y relaciones a español para el visor.

Los tipos de nodo se definen aquí. Las etiquetas de relación se intentan
importar desde ``data-engine/app/schemas/rpg_schema.py`` (fuente de verdad
del pipeline); si no está disponible, se usa un diccionario mínimo local.
Este módulo solo lee de ``rpg_schema.py``, nunca lo modifica.
"""
from __future__ import annotations

import sys
from pathlib import Path

ENTITY_TYPE_LABELS_ES: dict[str, str] = {
    "Character": "Personaje",
    "Creature": "Criatura",
    "NonHuman": "No humano",
    "Spirit": "Espíritu",
    "Demon": "Demonio",
    "Beast": "Bestia",
    "Location": "Lugar",
    "Region": "Región",
    "Faction": "Facción",
    "Clan": "Clan",
    "Family": "Familia",
    "School": "Escuela",
    "Object": "Objeto",
    "Artifact": "Artefacto",
    "Event": "Evento",
    "Encounter": "Encuentro",
    "Combat": "Combate",
    "Session": "Sesión",
    "Document": "Documento",
    "Chapter": "Capítulo",
    "Transcript": "Transcripción",
    "Image": "Imagen",
    "Concept": "Concepto",
    "Task": "Tarea",
    "Rule": "Regla",
    "Spell": "Hechizo",
    "Group": "Grupo",
}

# Diccionario mínimo local, usado solo si no se puede importar rpg_schema.py.
_RELATION_LABELS_ES_FALLBACK: dict[str, str] = {
    "MEMBER_OF": "miembro de",
    "BELONGS_TO": "pertenece a",
    "RELATED_TO": "relacionado con",
    "LOCATED_IN": "está en",
    "APPEARS_IN": "aparece en",
    "HAS_VISION_OF": "tuvo una visión de",
    "ALLY_OF": "aliado de",
    "ENEMY_OF": "enemigo de",
    "HAS_FOUGHT": "ha combatido contra",
    "HAS_SEEN": "ha visto",
    "HAS_HEARD_ABOUT": "ha oído hablar de",
    "HAS_TALKED_TO": "ha hablado con",
    "DISCOVERED": "descubrió",
    "INVESTIGATES": "investiga",
    "ATTACKED": "atacó a",
    "OCCURS_IN": "ocurre en",
    "OCCURS_DURING": "ocurre durante",
    "PARTICIPATED_IN": "participó en",
    "INVOLVES": "involucra",
}


def _load_relation_labels() -> dict[str, str]:
    """Intenta importar RELATION_LABELS_ES desde data-engine (solo lectura).

    Si data-engine no está disponible o falla el import, degrada al
    diccionario mínimo local sin romper el visor.
    """
    data_engine_app = Path(__file__).resolve().parents[2] / "data-engine"
    if str(data_engine_app) not in sys.path:
        sys.path.insert(0, str(data_engine_app))
    try:
        from app.schemas.rpg_schema import RELATION_LABELS_ES as _imported  # type: ignore
        merged = dict(_RELATION_LABELS_ES_FALLBACK)
        merged.update(_imported)
        return merged
    except Exception:
        return dict(_RELATION_LABELS_ES_FALLBACK)


RELATION_LABELS_ES: dict[str, str] = _load_relation_labels()

VISIBILITY_LABELS_ES: dict[str, str] = {
    "player": "Jugador",
    "narrator": "Narrador",
    "secret": "Secreto",
    "reference": "Referencia",
}

KNOWLEDGE_LAYER_LABELS_ES: dict[str, str] = {
    "campaign": "Campaña",
    "book": "Libro",
    "transcript": "Transcripción",
    "manual": "Manual",
    "inferred": "Inferido",
    "reviewed": "Revisado",
    "test": "Prueba",
}

REVIEW_STATUS_LABELS_ES: dict[str, str] = {
    "auto_extracted": "Extraído automáticamente",
    "needs_review": "Necesita revisión",
    "reviewed": "Revisado",
    "rejected": "Rechazado",
    "corrected": "Corregido",
}


def entity_type_label(entity_type: str | None) -> str:
    if not entity_type:
        return "Desconocido"
    return ENTITY_TYPE_LABELS_ES.get(entity_type, entity_type)


def relation_label(relation_type: str | None, relation_label_es: str | None = None) -> str:
    if relation_label_es:
        return relation_label_es
    if not relation_type:
        return ""
    return RELATION_LABELS_ES.get(relation_type, relation_type.lower().replace("_", " "))


def visibility_label(visibility: str | None) -> str:
    if not visibility:
        return ""
    return VISIBILITY_LABELS_ES.get(visibility, visibility)


def knowledge_layer_label(layer: str | None) -> str:
    if not layer:
        return ""
    return KNOWLEDGE_LAYER_LABELS_ES.get(layer, layer)


def review_status_label(status: str | None) -> str:
    if not status:
        return ""
    return REVIEW_STATUS_LABELS_ES.get(status, status)
