"""Traducción de tipos de nodo y relaciones a español para el visor.

Los tipos de nodo se definen aquí. Las etiquetas de relación se intentan
importar desde ``data-engine/app/schemas/rpg_schema.py`` (fuente de verdad
del pipeline); si no está disponible, se usa un diccionario mínimo local.
Este módulo solo lee de ``rpg_schema.py``, nunca lo modifica.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Modulo frontera UNICO hacia `contracts/review-status/v1` (ver su docstring).
# Las etiquetas se DERIVAN del vocabulario canonico; este modulo no lo declara.
from app import review_status_contract


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


# ===========================================================================
# EL SIGNO DE UN HECHO (negación) — AUTORIDAD ÚNICA
# ===========================================================================
# «Sela Marrec NO pertenece al Consejo de Umbra» no puede reaparecer en
# ninguna pantalla como «Sela Marrec pertenece al Consejo de Umbra». El dato
# que lo impide —`negated`— ya viaja desde la extracción hasta el nodo
# `:V3Assertion`; lo que faltaba era que el visor lo publicara.
#
# TRES ESTADOS, NO DOS. Éste es el punto delicado del módulo:
#
#   negated is True     -> NEGADO         el hecho niega la relación
#   negated is False    -> AFIRMATIVO     el hecho la afirma
#   cualquier otra cosa -> NO_DISPONIBLE
#
# AUSENCIA NO ES CERO. Un hecho antiguo escrito antes de que el writer
# estampara `negated`, una proyección que pierda el campo o un valor que no sea
# booleano NO son «afirmativos»: son «no se sabe». Colapsar el tercer estado
# sobre el segundo es exactamente el error simétrico del defecto —pintar como
# afirmativo algo cuyo signo nadie ha leído— y por eso la conversión es
# ESTRICTA (`is True` / `is False`) y no una verdad de Python: `1`, `"false"`,
# `"no"` o `[]` no son booleanos y aquí no se interpretan.
#
# DECISIÓN DECLARADA para el tercer estado: la pantalla lo DICE, y no calla.
# Callar sería indistinguible de «afirmativo», que es el defecto.

#: Códigos publicables. Son códigos, no frases: la UI los traduce con
#: `negation_label`, y un código que no se supiera traducir se NOMBRA.
NEGACION_NEGADO = "HECHO_NEGADO"
NEGACION_AFIRMATIVO = "HECHO_AFIRMATIVO"
NEGACION_NO_DISPONIBLE = "HECHO_SIGNO_NO_DISPONIBLE"

NEGACION_LABELS_ES = {
    NEGACION_NEGADO: "este hecho NIEGA la relación",
    NEGACION_AFIRMATIVO: "este hecho afirma la relación",
    NEGACION_NO_DISPONIBLE: "no consta si este hecho afirma o niega la relación",
}


def negation_code(negated: object) -> str:
    """El signo de un hecho, como CÓDIGO. Conversión estricta: ver arriba."""
    if negated is True:
        return NEGACION_NEGADO
    if negated is False:
        return NEGACION_AFIRMATIVO
    return NEGACION_NO_DISPONIBLE


#: LA CLASE DE NEGACIÓN, que NO es el signo.
#:
#: El signo dice SI la frase niega; la clase dice CÓMO. Son dos campos y en la
#: ficha del chasis ahora son dos filas, porque antes la clase se pintaba bajo
#: el rótulo «Negación» y un hecho negado cuya clase el motor no resolvió salía
#: como «no disponible».
#:
#: Al subir la clase a campo de primera clase hay que aplicarle la regla de la
#: casa: se publican CÓDIGOS y se TRADUCEN. `SIMPLE`, `CESSATION` o `NOT_YET`
#: en crudo son vocabulario del motor, no español para quien decide.
#:
#: El vocabulario es el de `knowledge_v3.engine.negation` (SIMPLE, NEVER,
#: CESSATION, NOT_YET, SCOPE_AMBIGUOUS) más el `UNKNOWN` que el exportador
#: escribe cuando no la resolvió. NO se importa de allí: el visor no depende
#: del motor. Si el motor añadiera una clase, aquí NO se descarta —se NOMBRA—,
#: que es justo lo que hace `negation_kind_label`.
NEGACION_CLASE_LABELS_ES = {
    "SIMPLE": "negación simple",
    "NEVER": "negación absoluta (nunca)",
    "CESSATION": "cese (hubo relación y terminó)",
    "NOT_YET": "todavía no",
    "SCOPE_AMBIGUOUS": "alcance ambiguo",
    "UNKNOWN": "no consta de qué clase",
}


def negation_kind_label(kind: str | None) -> str:
    """Traducción de la CLASE. Una clase desconocida se NOMBRA, no se descarta.

    Descartarla dejaría el hueco en blanco, y en esta pantalla un hueco en
    blanco se lee como «no hay nada que saber» — que es la misma puerta de
    atrás que el signo tiene cerrada.
    """
    if not kind:
        return NEGACION_CLASE_LABELS_ES["UNKNOWN"]
    etiqueta = NEGACION_CLASE_LABELS_ES.get(str(kind).strip().upper())
    if etiqueta is None:
        return f"clase no reconocida ({kind})"
    return etiqueta


def negation_label(code: str | None) -> str:
    """Traducción del código. Un código desconocido se NOMBRA, no se descarta.

    Descartarlo dejaría el hueco en blanco, y un hueco en blanco en esta
    pantalla se lee como «afirmativo» — el error simétrico otra vez, ahora por
    la puerta de atrás.
    """
    if not code:
        return NEGACION_LABELS_ES[NEGACION_NO_DISPONIBLE]
    etiqueta = NEGACION_LABELS_ES.get(code)
    if etiqueta is None:
        return f"signo no reconocido ({code})"
    return etiqueta
