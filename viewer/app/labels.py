"""Traducción de tipos de nodo y relaciones a español para el visor.

Los tipos de nodo se definen aquí. Las etiquetas de relación se intentan
importar desde ``data-engine/app/schemas/rpg_schema.py`` (fuente de verdad
del pipeline); si no está disponible, se usa un diccionario mínimo local.
Este módulo solo lee de ``rpg_schema.py``, nunca lo modifica.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# --- Vocabulario canonico de `review_status` -------------------------------
# Se carga por ruta del contrato compartido. Este modulo NO puede importar
# `data-engine`, y por eso llevaba una copia manual del vocabulario: dos listas
# del mismo vocabulario, mantenidas por separado, es como se derivan en
# silencio. Ahora las etiquetas se DERIVAN del canonico y la exhaustividad es
# comprobable (ver `test_calidad_de_datos_v2.py`).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RS_PATH = _REPO_ROOT / "contracts" / "review-status" / "v1" / "model.py"
_RS_MODULE = "s9k_review_status_v1_model"
if _RS_MODULE in sys.modules:  # pragma: no cover - cache entre imports
    review_status_contract = sys.modules[_RS_MODULE]
else:  # pragma: no cover - trivial
    _spec = importlib.util.spec_from_file_location(_RS_MODULE, _RS_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"no se pudo cargar review-status/v1 en {_RS_PATH}")
    review_status_contract = importlib.util.module_from_spec(_spec)
    sys.modules[_RS_MODULE] = review_status_contract
    _spec.loader.exec_module(review_status_contract)

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

    Usa data-engine/app/ (no data-engine/) + import top-level `schemas.X`,
    NO `app.schemas.X`: el visor ya tiene su propio paquete `app` (viewer/app/),
    y una vez que `sys.modules['app']` queda ligado a ese paquete, importar
    `app.schemas...` fallaría en silencio (capturado por el except de abajo).
    """
    data_engine_app_dir = Path(__file__).resolve().parents[2] / "data-engine" / "app"
    if str(data_engine_app_dir) not in sys.path:
        sys.path.insert(0, str(data_engine_app_dir))
    try:
        from schemas.rpg_schema import RELATION_LABELS_ES as _imported  # type: ignore
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

#: Traducciones al español. NO es la definición del vocabulario: la definición
#: vive en `contracts/review-status/v1`. Este mapa se CONSTRUYE recorriendo el
#: vocabulario canónico, así que un estado nuevo allí revienta aquí en el
#: import en vez de aparecer sin etiqueta en la interfaz, y un estado retirado
#: allí desaparece de aquí solo.
_TRADUCCIONES_REVIEW_STATUS_ES: dict[str, str] = {
    "auto_extracted": "Extraído automáticamente",
    "needs_review": "Necesita revisión",
    "reviewed": "Revisado",
    "rejected": "Rechazado",
    "corrected": "Corregido",
}


def _construir_etiquetas_review_status() -> dict[str, str]:
    faltan = sorted(
        review_status_contract.CANONICAL_VALUES - set(_TRADUCCIONES_REVIEW_STATUS_ES)
    )
    if faltan:
        raise RuntimeError(
            "review-status/v1 declara estados sin traducción al español: "
            f"{faltan}. Añádelas a _TRADUCCIONES_REVIEW_STATUS_ES."
        )
    return {
        valor: _TRADUCCIONES_REVIEW_STATUS_ES[valor]
        for valor in sorted(review_status_contract.CANONICAL_VALUES)
    }


REVIEW_STATUS_LABELS_ES: dict[str, str] = _construir_etiquetas_review_status()


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
    """Etiqueta en español de un `review_status`.

    Un valor fuera del vocabulario canónico NO se muestra tal cual: se marca
    como no reconocido. Devolver la cadena cruda hacía que un `review_status`
    corrupto se leyera en la interfaz como si fuera un estado legítimo del
    sistema, que es la forma que tiene un dato malo de pasar por bueno.
    """
    if not status:
        return ""
    etiqueta = review_status_contract.etiquetar(status, REVIEW_STATUS_LABELS_ES)
    if etiqueta is None:
        return f"no reconocido ({status})"
    return etiqueta
