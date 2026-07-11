"""Schema Pydantic para extracción de entidades RPG narrativas."""
from __future__ import annotations
import logging
import unicodedata
from typing import Optional
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.5.0"

ALLOWED_NODE_TYPES: frozenset[str] = frozenset({
    # Personajes y seres
    "Character", "Creature", "NonHuman", "Spirit", "Demon", "Beast",
    # Lugares
    "Location", "Region",
    # Grupos y organizaciones
    "Faction", "Clan", "Family", "School", "Group",
    # Objetos y saber
    "Object", "Artifact", "Spell", "Rule", "Concept",
    # Acontecimientos
    "Event", "Encounter", "Combat", "Task",
    # Estructura de campaña y fuentes
    "Session", "Document", "Chapter", "Transcript", "Image",
})

ALLOWED_RELATION_TYPES: frozenset[str] = frozenset({
    "CONTAINS", "MENTIONS", "APPEARS_IN", "BELONGS_TO", "MEMBER_OF",
    "ALLIED_WITH", "ENEMY_OF", "RELATED_TO", "LOCATED_IN", "OCCURS_IN",
    "OWNS", "USES", "TEACHES", "LEARNS", "CREATED_BY", "DESCENDANT_OF",
    "PARENT_OF", "SERVES", "GOVERNS", "AFFECTS", "REQUIRES", "CONTRADICTS",
    # Tipos narrativos para transcripciones de sesión
    "DECIDES", "SUSPECTS", "AGREES_TO", "HAS_VISION_OF", "SEES_IN_VISION",
    "WARNED_BY", "WARNS", "INVESTIGATES", "SEARCHES_FOR", "INTERROGATES",
    "CHECKS", "HAS_SYMBOL_OF", "HOLDS", "DISAPPEARED_NEAR",
    "TASK_ASSIGNED_TO", "TASK_TARGETS",
    # Tipos de encuentro e interacción social
    "MEETS", "KNOWS",
    # Tipos narrativos adicionales para poder político y trama
    "ORDERS", "FALLS_TO", "PLOTS_AGAINST",
    # ── Relaciones entre personajes (Fase 3) ──────────────────────────────────
    # (ENEMY_OF ya existe arriba y se reutiliza para personajes)
    "ALLY_OF", "RIVAL_OF", "FRIEND_OF", "FAMILY_OF",
    "SPOUSE_OF", "PROTECTS", "MENTOR_OF", "STUDENT_OF", "BETRAYS",
    "OWES_DEBT_TO", "COMMANDS", "WORKS_FOR", "THREATENS", "BLACKMAILS",
    "LOVES", "FEARS", "TRUSTS", "DISTRUSTS",
    # ── Relaciones de criaturas/no-humanos/enemigos (Fase 3) ──────────────────
    "SEEN_IN", "ENCOUNTERED_AT", "FOUGHT_AT", "DEFEATED_AT", "KILLED_AT",
    "ESCAPED_FROM", "GUARDS", "HAUNTS", "SUMMONED_BY", "CORRUPTED_BY",
    "ATTACKED", "HELPED", "TALKED_TO",
    # ── Relaciones con lugares (Fase 3) ───────────────────────────────────────
    "FOUND_IN", "HIDDEN_IN", "TRAVELS_TO", "COMES_FROM", "RULES_OVER",
    # ── Relaciones de eventos/sesiones (Fase 3) ───────────────────────────────
    "OCCURS_DURING", "PARTICIPATES_IN", "CAUSES", "LEADS_TO", "DISCOVERS",
    "REVEALS", "CHANGES_STATUS_OF", "STARTS_TASK", "COMPLETES_TASK",
    "FAILS_TASK",
    # ── Relaciones de tareas (Fase 3) ─────────────────────────────────────────
    "ASSIGNED_TO", "BLOCKED_BY", "COMPLETED_BY",
    # ── Relaciones de documentos/fuentes (Fase 3) ─────────────────────────────
    "SOURCE_OF", "EXTRACTED_FROM", "HAS_IMAGE", "HAS_TRANSCRIPT",
    # ── Relaciones de conocimiento por personaje (Fase conocimiento) ──────────
    "KNOWS_ABOUT", "HAS_SEEN", "HAS_MET", "HAS_HEARD_ABOUT", "HAS_FOUGHT",
    "HAS_TALKED_TO", "DISCOVERED", "WAS_PRESENT_AT", "PARTICIPATED_IN",
    "WITNESSED", "WAS_TOLD_BY", "TELLS", "TELLS_ABOUT", "SHARED_WITH",
    "KNOWN_BY_PARTY", "KNOWN_PUBLICLY", "INVOLVES",
})

# ── Vocabularios controlados para propiedades de entidad (Fase 2) ─────────────
# Valores permitidos. Si el LLM devuelve otro valor, se degrada al valor seguro
# por defecto (nunca aborta la extracción).
ALLOWED_ATTITUDE: frozenset[str] = frozenset({
    "ally", "enemy", "neutral", "unknown", "temporary_ally", "potential_threat",
})
ALLOWED_STATUS: frozenset[str] = frozenset({
    "unknown", "active", "defeated", "dead", "escaped", "captured", "sealed",
    "banished", "ally", "neutral", "hostile", "redeemed",
})
ALLOWED_DANGER_LEVEL: frozenset[str] = frozenset({
    "unknown", "low", "medium", "high", "extreme",
})
ALLOWED_VISIBILITY: frozenset[str] = frozenset({
    "player", "narrator", "secret", "reference",
})
ALLOWED_KNOWLEDGE_LAYER: frozenset[str] = frozenset({
    "campaign", "book", "transcript", "manual", "inferred", "reviewed", "test",
})
ALLOWED_REVIEW_STATUS: frozenset[str] = frozenset({
    "auto_extracted", "needs_review", "reviewed", "rejected", "corrected",
})
# ── Conocimiento por personaje (Fase conocimiento) ────────────────────────────
ALLOWED_KNOWN_BY_SCOPE: frozenset[str] = frozenset({
    "character", "party", "public", "narrator", "admin_only",
})
ALLOWED_KNOWLEDGE_QUALITY: frozenset[str] = frozenset({
    "seen", "met", "fought", "talked_to", "heard_about", "discovered",
    "witnessed", "inferred", "rumor", "confirmed",
})


def _coerce_vocab(value, allowed: frozenset[str], default):
    """Normaliza un valor a un vocabulario controlado sin abortar.

    Devuelve None si el valor es None. Si el valor (en minúsculas) está en el
    vocabulario, lo devuelve normalizado. Si no, degrada a `default` y loguea.
    """
    if value is None:
        return None
    v = str(value).strip().lower().replace(" ", "_")
    if not v:
        return None
    if v in allowed:
        return v
    log.warning("[schema] valor '%s' no está en el vocabulario %s → usando '%s'",
                value, sorted(allowed)[:6], default)
    return default

# ── Etiquetas visibles en español ─────────────────────────────────────────────
# Idioma de uso: español. Identificadores internos: técnicos y estables.
# Presentación al usuario: español (ver ARCHITECTURE.md).
RELATION_LABELS_ES: dict[str, str] = {
    "MEMBER_OF": "pertenece a",
    "BELONGS_TO": "pertenece a",
    "ALLIED_WITH": "aliado con",
    "ENEMY_OF": "enemigo de",
    "RELATED_TO": "está relacionado con",
    "LOCATED_IN": "se ubica en",
    "OCCURS_IN": "ocurre en",
    "APPEARS_IN": "aparece en",
    "CONTAINS": "contiene",
    "MENTIONS": "menciona",
    "OWNS": "posee",
    "USES": "usa",
    "TEACHES": "enseña a",
    "LEARNS": "aprende de",
    "CREATED_BY": "fue creado por",
    "DESCENDANT_OF": "desciende de",
    "PARENT_OF": "es padre/madre de",
    "SERVES": "sirve a",
    "GOVERNS": "gobierna",
    "AFFECTS": "afecta a",
    "REQUIRES": "requiere",
    "CONTRADICTS": "contradice",
    "DECIDES": "decide",
    "SUSPECTS": "sospecha de",
    "AGREES_TO": "acuerda",
    "HAS_VISION_OF": "tuvo una visión de",
    "SEES_IN_VISION": "vio en una visión",
    "WARNED_BY": "fue advertido por",
    "WARNS": "advierte a",
    "INVESTIGATES": "investiga",
    "SEARCHES_FOR": "busca",
    "INTERROGATES": "interroga a",
    "CHECKS": "comprueba",
    "HAS_SYMBOL_OF": "tiene el símbolo de",
    "HOLDS": "sostiene",
    "DISAPPEARED_NEAR": "desapareció cerca de",
    "TASK_ASSIGNED_TO": "tarea asignada a",
    "TASK_TARGETS": "tiene como objetivo",
    "MEETS": "se encuentra con",
    "KNOWS": "conoce a",
    "ORDERS": "ordena a",
    "FALLS_TO": "recae en",
    "PLOTS_AGAINST": "conspira contra",
    # ── Relaciones entre personajes (Fase 4) ──────────────────────────────────
    "ALLY_OF": "aliado de",
    "RIVAL_OF": "rival de",
    "FRIEND_OF": "amigo de",
    "FAMILY_OF": "familiar de",
    "SPOUSE_OF": "cónyuge de",
    "PROTECTS": "protege a",
    "MENTOR_OF": "mentor de",
    "STUDENT_OF": "alumno de",
    "BETRAYS": "traiciona a",
    "OWES_DEBT_TO": "tiene una deuda con",
    "COMMANDS": "manda sobre",
    "WORKS_FOR": "trabaja para",
    "THREATENS": "amenaza a",
    "BLACKMAILS": "chantajea a",
    "LOVES": "ama a",
    "FEARS": "teme a",
    "TRUSTS": "confía en",
    "DISTRUSTS": "desconfía de",
    # ── Relaciones de criaturas/no-humanos/enemigos ───────────────────────────
    "SEEN_IN": "visto en",
    "ENCOUNTERED_AT": "encontrado en",
    "FOUGHT_AT": "combatido en",
    "DEFEATED_AT": "derrotado en",
    "KILLED_AT": "muerto en",
    "ESCAPED_FROM": "escapó de",
    "GUARDS": "guarda",
    "HAUNTS": "acecha",
    "SUMMONED_BY": "invocado por",
    "CORRUPTED_BY": "corrompido por",
    "ATTACKED": "atacó a",
    "HELPED": "ayudó a",
    "TALKED_TO": "habló con",
    # ── Relaciones con lugares ────────────────────────────────────────────────
    "FOUND_IN": "encontrado en",
    "HIDDEN_IN": "oculto en",
    "TRAVELS_TO": "viaja a",
    "COMES_FROM": "viene de",
    "RULES_OVER": "gobierna",
    # ── Relaciones de eventos/sesiones ────────────────────────────────────────
    "OCCURS_DURING": "ocurre durante",
    "PARTICIPATES_IN": "participa en",
    "CAUSES": "causa",
    "LEADS_TO": "lleva a",
    "DISCOVERS": "descubre",
    "REVEALS": "revela",
    "CHANGES_STATUS_OF": "cambia el estado de",
    "STARTS_TASK": "inicia tarea",
    "COMPLETES_TASK": "completa tarea",
    "FAILS_TASK": "falla tarea",
    # ── Relaciones de tareas ──────────────────────────────────────────────────
    "ASSIGNED_TO": "asignado a",
    "BLOCKED_BY": "bloqueado por",
    "COMPLETED_BY": "completado por",
    # ── Relaciones de documentos/fuentes ──────────────────────────────────────
    "SOURCE_OF": "fuente de",
    "EXTRACTED_FROM": "extraído de",
    "HAS_IMAGE": "tiene imagen",
    "HAS_TRANSCRIPT": "tiene transcripción",
    # ── Relaciones de conocimiento por personaje ──────────────────────────────
    "KNOWS_ABOUT": "sabe de",
    "HAS_SEEN": "ha visto",
    "HAS_MET": "ha conocido",
    "HAS_HEARD_ABOUT": "ha oído hablar de",
    "HAS_FOUGHT": "ha combatido contra",
    "HAS_TALKED_TO": "ha hablado con",
    "DISCOVERED": "descubrió",
    "WAS_PRESENT_AT": "estuvo presente en",
    "PARTICIPATED_IN": "participó en",
    "WITNESSED": "fue testigo de",
    "WAS_TOLD_BY": "fue informado por",
    "TELLS": "cuenta a",
    "TELLS_ABOUT": "cuenta sobre",
    "SHARED_WITH": "compartido con",
    "KNOWN_BY_PARTY": "conocido por el grupo",
    "KNOWN_PUBLICLY": "conocido públicamente",
    "INVOLVES": "involucra a",
}


def _strip_accents(s: str) -> str:
    """Elimina tildes y diacríticos para comparación robusta."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _normalize_key(s: str) -> str:
    """Convierte a minúsculas sin tildes, reemplaza guiones/underscores por espacio."""
    s = s.lower().strip()
    s = _strip_accents(s)
    s = s.replace("_", " ").replace("-", " ")
    # colapsar espacios múltiples
    return " ".join(s.split())


# ── Mapa de normalización ampliado ────────────────────────────────────────────
# Claves en minúsculas sin tildes (la función de lookup normaliza la entrada).
# Cubre tipos en español libre, verbos conjugados, frases complejas.
# Los casos detectados en el run de prueba están marcados con [DETECTADO].
_RAW_NORMALIZE: list[tuple[str, str]] = [
    # ── WARNED_BY / WARNS ─────────────────────────────────────────────────────
    ("recibio advertencia", "WARNED_BY"),          # [DETECTADO]
    ("recibio una advertencia", "WARNED_BY"),
    ("recibe advertencia", "WARNED_BY"),
    ("advertido por", "WARNED_BY"),
    ("fue advertido por", "WARNED_BY"),
    ("warned by", "WARNED_BY"),
    ("advirtio", "WARNS"),
    ("advierte", "WARNS"),
    ("advierte a", "WARNS"),
    ("advirtio a", "WARNS"),
    ("dio una advertencia", "WARNS"),
    ("warns", "WARNS"),

    # ── HAS_VISION_OF / SEES_IN_VISION ────────────────────────────────────────
    ("tiene vision de", "HAS_VISION_OF"),
    ("tiene una vision de", "HAS_VISION_OF"),
    ("vision de", "HAS_VISION_OF"),
    ("tuvo una vision de", "HAS_VISION_OF"),
    ("tuvo vision de", "HAS_VISION_OF"),
    ("ha visionado", "HAS_VISION_OF"),
    ("vio en una vision", "SEES_IN_VISION"),
    ("vio en vision", "SEES_IN_VISION"),
    ("vista sosten fragmento", "SEES_IN_VISION"),  # [DETECTADO]
    ("vista sosten", "SEES_IN_VISION"),
    ("ve en vision", "SEES_IN_VISION"),
    ("aparece en vision", "SEES_IN_VISION"),
    ("aparece en una vision", "SEES_IN_VISION"),
    ("has vision of", "HAS_VISION_OF"),
    ("sees in vision", "SEES_IN_VISION"),

    # ── HAS_SYMBOL_OF ─────────────────────────────────────────────────────────
    ("vista mascara", "HAS_SYMBOL_OF"),            # [DETECTADO]
    ("mascara con simbolo", "HAS_SYMBOL_OF"),
    ("tiene el simbolo de", "HAS_SYMBOL_OF"),
    ("tiene simbolo de", "HAS_SYMBOL_OF"),
    ("simbolo de", "HAS_SYMBOL_OF"),
    ("simbolo del", "HAS_SYMBOL_OF"),
    ("lleva el simbolo de", "HAS_SYMBOL_OF"),
    ("has symbol of", "HAS_SYMBOL_OF"),

    # ── INVESTIGATES ──────────────────────────────────────────────────────────
    ("investigacion", "INVESTIGATES"),             # [DETECTADO]
    ("investigacion de", "INVESTIGATES"),
    ("investiga", "INVESTIGATES"),
    ("investiga a", "INVESTIGATES"),
    ("decidio investigar", "INVESTIGATES"),
    ("decide investigar", "INVESTIGATES"),
    ("investiga el", "INVESTIGATES"),
    ("investiga la", "INVESTIGATES"),
    ("investigates", "INVESTIGATES"),

    # ── SEARCHES_FOR ──────────────────────────────────────────────────────────
    ("busca rastros", "SEARCHES_FOR"),
    ("buscar rastros", "SEARCHES_FOR"),
    ("busca a", "SEARCHES_FOR"),
    ("busca", "SEARCHES_FOR"),
    ("searches for", "SEARCHES_FOR"),

    # ── AGREES_TO ─────────────────────────────────────────────────────────────
    ("acordo tarea", "AGREES_TO"),                 # [DETECTADO]
    ("acuerda tarea", "AGREES_TO"),
    ("acordaron", "AGREES_TO"),
    ("acordaron hacer", "AGREES_TO"),
    ("acordaron realizar", "AGREES_TO"),
    ("acuerda", "AGREES_TO"),
    ("llego a un acuerdo sobre", "AGREES_TO"),
    ("agrees to", "AGREES_TO"),

    # ── SUSPECTS ──────────────────────────────────────────────────────────────
    ("sospecha", "SUSPECTS"),
    ("sospecha de", "SUSPECTS"),
    ("sospecha que", "SUSPECTS"),
    ("sospechoso", "SUSPECTS"),
    ("oculta informacion", "SUSPECTS"),
    ("sospecha sobre", "SUSPECTS"),
    ("suspects", "SUSPECTS"),

    # ── HOLDS ─────────────────────────────────────────────────────────────────
    ("sostiene", "HOLDS"),
    ("sosteniendo", "HOLDS"),
    ("tiene en su poder", "HOLDS"),
    ("porta", "HOLDS"),
    ("lleva consigo", "HOLDS"),
    ("holds", "HOLDS"),

    # ── DECIDES ───────────────────────────────────────────────────────────────
    ("decide", "DECIDES"),
    ("decidio", "DECIDES"),
    ("tomo la decision de", "DECIDES"),
    ("decides", "DECIDES"),

    # ── INTERROGATES ──────────────────────────────────────────────────────────
    ("interrogar", "INTERROGATES"),
    ("interroga", "INTERROGATES"),
    ("interroga a", "INTERROGATES"),
    ("interrogates", "INTERROGATES"),

    # ── CHECKS ────────────────────────────────────────────────────────────────
    ("comprobar", "CHECKS"),
    ("comprueba", "CHECKS"),
    ("verificar", "CHECKS"),
    ("verifica", "CHECKS"),
    ("checks", "CHECKS"),

    # ── TASK_TARGETS / TASK_ASSIGNED_TO ───────────────────────────────────────
    ("tarea sobre", "TASK_TARGETS"),
    ("objetivo de tarea", "TASK_TARGETS"),
    ("tarea dirigida a", "TASK_TARGETS"),
    ("task targets", "TASK_TARGETS"),
    ("tarea asignada a", "TASK_ASSIGNED_TO"),
    ("task assigned to", "TASK_ASSIGNED_TO"),

    # ── DISAPPEARED_NEAR ──────────────────────────────────────────────────────
    ("desaparecio cerca de", "DISAPPEARED_NEAR"),
    ("desaparecieron cerca de", "DISAPPEARED_NEAR"),
    ("desaparecido cerca de", "DISAPPEARED_NEAR"),
    ("disappeared near", "DISAPPEARED_NEAR"),

    # ── MEETS ─────────────────────────────────────────────────────────────────
    ("meets", "MEETS"),
    ("se encuentra con", "MEETS"),
    ("se encontro con", "MEETS"),
    ("tiene un encuentro con", "MEETS"),
    ("tuvo un encuentro con", "MEETS"),
    ("se reunio con", "MEETS"),
    ("se reune con", "MEETS"),

    # ── KNOWS ─────────────────────────────────────────────────────────────────
    ("knows", "KNOWS"),
    ("conoce", "KNOWS"),
    ("conoce a", "KNOWS"),
    ("conocia a", "KNOWS"),
    ("conocia", "KNOWS"),
    ("es conocido por", "KNOWS"),
    ("se conocen", "KNOWS"),

    # ── ORDERS ────────────────────────────────────────────────────────────────
    ("ordeno a", "ORDERS"),
    ("ordena a", "ORDERS"),
    ("ordeno", "ORDERS"),
    ("ordena", "ORDERS"),
    ("ordered", "ORDERS"),
    ("orders", "ORDERS"),

    # ── FALLS_TO ──────────────────────────────────────────────────────────────
    ("recayo en", "FALLS_TO"),
    ("recae en", "FALLS_TO"),
    ("pasa a", "FALLS_TO"),
    ("falls to", "FALLS_TO"),

    # ── PLOTS_AGAINST ─────────────────────────────────────────────────────────
    ("conspira contra", "PLOTS_AGAINST"),
    ("traza un plan contra", "PLOTS_AGAINST"),
    ("formula un plan contra", "PLOTS_AGAINST"),
    ("formulo un plan contra", "PLOTS_AGAINST"),
    ("formulates plan against", "PLOTS_AGAINST"),
    ("plots against", "PLOTS_AGAINST"),

    # ── MEMBER_OF / BELONGS_TO ────────────────────────────────────────────────
    ("miembro de", "MEMBER_OF"),
    ("pertenece a", "BELONGS_TO"),
    ("es miembro de", "MEMBER_OF"),
    ("member of", "MEMBER_OF"),
    ("belongs to", "BELONGS_TO"),

    # ── ALLIED_WITH / ENEMY_OF ────────────────────────────────────────────────
    ("aliado con", "ALLIED_WITH"),
    ("aliado de", "ALLIED_WITH"),
    ("enemigo de", "ENEMY_OF"),
    ("allied with", "ALLIED_WITH"),
    ("enemy of", "ENEMY_OF"),

    # ── RELATED_TO ────────────────────────────────────────────────────────────
    ("relacionado con", "RELATED_TO"),
    ("relacionada con", "RELATED_TO"),
    ("related to", "RELATED_TO"),

    # ── LOCATED_IN ────────────────────────────────────────────────────────────
    ("localizado en", "LOCATED_IN"),
    ("ubicado en", "LOCATED_IN"),
    ("se encuentra en", "LOCATED_IN"),
    ("located in", "LOCATED_IN"),

    # ── APPEARS_IN ────────────────────────────────────────────────────────────
    ("aparece en", "APPEARS_IN"),
    ("appears in", "APPEARS_IN"),

    # ── CONTAINS / MENTIONS ───────────────────────────────────────────────────
    ("contiene", "CONTAINS"),
    ("menciona", "MENTIONS"),
    ("contains", "CONTAINS"),
    ("mentions", "MENTIONS"),

    # ═══ Fase 5: relaciones sociales entre personajes ═════════════════════════
    ("es amigo de", "FRIEND_OF"),
    ("amigo de", "FRIEND_OF"),
    ("amiga de", "FRIEND_OF"),
    ("has friend", "FRIEND_OF"),
    ("aliado de", "ALLY_OF"),
    ("aliada de", "ALLY_OF"),
    ("ally of", "ALLY_OF"),
    ("rival de", "RIVAL_OF"),
    ("rival of", "RIVAL_OF"),
    ("familiar de", "FAMILY_OF"),
    ("pariente de", "FAMILY_OF"),
    ("family of", "FAMILY_OF"),
    ("esposa de", "SPOUSE_OF"),
    ("esposo de", "SPOUSE_OF"),
    ("marido de", "SPOUSE_OF"),
    ("mujer de", "SPOUSE_OF"),
    ("conyuge de", "SPOUSE_OF"),
    ("casado con", "SPOUSE_OF"),
    ("casada con", "SPOUSE_OF"),
    ("has wife", "SPOUSE_OF"),
    ("has husband", "SPOUSE_OF"),
    ("spouse of", "SPOUSE_OF"),
    ("protege a", "PROTECTS"),
    ("protege", "PROTECTS"),
    ("protects", "PROTECTS"),
    ("maestro de", "MENTOR_OF"),
    ("mentor de", "MENTOR_OF"),
    ("mentor of", "MENTOR_OF"),
    ("alumno de", "STUDENT_OF"),
    ("alumna de", "STUDENT_OF"),
    ("aprendiz de", "STUDENT_OF"),
    ("discipulo de", "STUDENT_OF"),
    ("student of", "STUDENT_OF"),
    ("traiciona a", "BETRAYS"),
    ("traiciono a", "BETRAYS"),
    ("betrays", "BETRAYS"),
    ("debe a", "OWES_DEBT_TO"),
    ("tiene deuda con", "OWES_DEBT_TO"),
    ("tiene una deuda con", "OWES_DEBT_TO"),
    ("owes debt to", "OWES_DEBT_TO"),
    ("manda sobre", "COMMANDS"),
    ("comanda a", "COMMANDS"),
    ("commands", "COMMANDS"),
    ("trabaja para", "WORKS_FOR"),
    ("works for", "WORKS_FOR"),
    ("works at", "LOCATED_IN"),
    ("amenaza a", "THREATENS"),
    ("amenazo a", "THREATENS"),
    ("threatens", "THREATENS"),
    ("chantajea a", "BLACKMAILS"),
    ("blackmails", "BLACKMAILS"),
    ("ama a", "LOVES"),
    ("loves", "LOVES"),
    ("teme a", "FEARS"),
    ("fears", "FEARS"),
    ("confia en", "TRUSTS"),
    ("trusts", "TRUSTS"),
    ("desconfia de", "DISTRUSTS"),
    ("distrusts", "DISTRUSTS"),

    # ═══ Fase 5: criaturas / no-humanos / enemigos ════════════════════════════
    ("visto en", "SEEN_IN"),
    ("vista en", "SEEN_IN"),
    ("avistado en", "SEEN_IN"),
    ("seen in", "SEEN_IN"),
    ("encontrado a", "ENCOUNTERED_AT"),
    ("encuentro en", "ENCOUNTERED_AT"),
    ("encountered at", "ENCOUNTERED_AT"),
    ("combatido en", "FOUGHT_AT"),
    ("lucho en", "FOUGHT_AT"),
    ("lucho dentro de", "FOUGHT_AT"),
    ("lucho dentro del", "FOUGHT_AT"),
    ("combatio en", "FOUGHT_AT"),
    ("combatio dentro de", "FOUGHT_AT"),
    ("peleo en", "FOUGHT_AT"),
    ("fought at", "FOUGHT_AT"),
    # "luchó contra <ser/grupo>" → ataque entre seres (destino no es lugar)
    ("lucho contra", "ATTACKED"),
    ("luchan contra", "ATTACKED"),
    ("pelea contra", "ATTACKED"),
    ("peleo contra", "ATTACKED"),
    ("combatio contra", "ATTACKED"),
    ("se enfrento a", "ATTACKED"),
    ("se enfrentaron a", "ATTACKED"),
    ("derrotado en", "DEFEATED_AT"),
    ("vencido en", "DEFEATED_AT"),
    ("defeated at", "DEFEATED_AT"),
    ("muerto en", "KILLED_AT"),
    ("murio en", "KILLED_AT"),
    ("asesinado en", "KILLED_AT"),
    ("killed at", "KILLED_AT"),
    ("escapo de", "ESCAPED_FROM"),
    ("escapo hacia", "ESCAPED_FROM"),
    ("huyo de", "ESCAPED_FROM"),
    ("escaped from", "ESCAPED_FROM"),
    ("guarda", "GUARDS"),
    ("custodia", "GUARDS"),
    ("guards", "GUARDS"),
    ("acecha", "HAUNTS"),
    ("ronda", "HAUNTS"),
    ("haunts", "HAUNTS"),
    ("invocado por", "SUMMONED_BY"),
    ("convocado por", "SUMMONED_BY"),
    ("summoned by", "SUMMONED_BY"),
    ("corrompido por", "CORRUPTED_BY"),
    ("corrupted by", "CORRUPTED_BY"),
    ("ataco a", "ATTACKED"),
    ("atacaron a", "ATTACKED"),
    ("atacaron al", "ATTACKED"),
    ("ataco al", "ATTACKED"),
    ("attacked", "ATTACKED"),
    ("ayudo a", "HELPED"),
    ("ayudaron a", "HELPED"),
    ("ayudo al", "HELPED"),
    ("ayudaron al", "HELPED"),
    ("helped", "HELPED"),
    ("hablo con", "TALKED_TO"),
    ("hablaron con", "TALKED_TO"),
    ("converso con", "TALKED_TO"),
    ("talked to", "TALKED_TO"),

    # ═══ Fase 5: lugares ══════════════════════════════════════════════════════
    ("hallado en", "FOUND_IN"),
    ("found in", "FOUND_IN"),
    ("oculto en", "HIDDEN_IN"),
    ("escondido en", "HIDDEN_IN"),
    ("hidden in", "HIDDEN_IN"),
    ("viaja a", "TRAVELS_TO"),
    ("viajo a", "TRAVELS_TO"),
    ("viajaron a", "TRAVELS_TO"),
    ("se dirige a", "TRAVELS_TO"),
    ("travels to", "TRAVELS_TO"),
    ("viene de", "COMES_FROM"),
    ("proviene de", "COMES_FROM"),
    ("procede de", "COMES_FROM"),
    ("comes from", "COMES_FROM"),
    ("gobierna sobre", "RULES_OVER"),
    ("gobierna", "RULES_OVER"),
    ("rules over", "RULES_OVER"),
    ("vive en", "LOCATED_IN"),
    ("lives in", "LOCATED_IN"),

    # ═══ Fase 5: eventos / sesiones ═══════════════════════════════════════════
    ("ocurre durante", "OCCURS_DURING"),
    ("sucede durante", "OCCURS_DURING"),
    ("occurs during", "OCCURS_DURING"),
    ("participa en", "PARTICIPATES_IN"),
    ("participo en", "PARTICIPATES_IN"),
    ("participaron en", "PARTICIPATES_IN"),
    ("participates in", "PARTICIPATES_IN"),
    ("causa", "CAUSES"),
    ("causo", "CAUSES"),
    ("provoca", "CAUSES"),
    ("provoco", "CAUSES"),
    ("causes", "CAUSES"),
    ("lleva a", "LEADS_TO"),
    ("conduce a", "LEADS_TO"),
    ("leads to", "LEADS_TO"),
    ("descubre", "DISCOVERS"),
    ("descubrio", "DISCOVERS"),
    ("discovers", "DISCOVERS"),
    ("revela", "REVEALS"),
    ("revelo", "REVEALS"),
    ("reveals", "REVEALS"),
    ("cambia el estado de", "CHANGES_STATUS_OF"),
    ("changes status of", "CHANGES_STATUS_OF"),

    # ═══ Fase 5: tareas ═══════════════════════════════════════════════════════
    ("asignado a", "ASSIGNED_TO"),
    ("asignada a", "ASSIGNED_TO"),
    ("assigned to", "ASSIGNED_TO"),
    ("bloqueado por", "BLOCKED_BY"),
    ("bloqueada por", "BLOCKED_BY"),
    ("blocked by", "BLOCKED_BY"),
    ("completado por", "COMPLETED_BY"),
    ("completada por", "COMPLETED_BY"),
    ("completed by", "COMPLETED_BY"),

    # ═══ Fase 5: fuentes / documentos ═════════════════════════════════════════
    ("extraido de", "EXTRACTED_FROM"),
    ("extracted from", "EXTRACTED_FROM"),
    ("fuente de", "SOURCE_OF"),
    ("source of", "SOURCE_OF"),
    ("tiene imagen", "HAS_IMAGE"),
    ("has image", "HAS_IMAGE"),
    ("tiene transcripcion", "HAS_TRANSCRIPT"),
    ("has transcript", "HAS_TRANSCRIPT"),

    # ═══ Conocimiento por personaje (frases ES) ═══════════════════════════════
    ("sabe de", "KNOWS_ABOUT"),
    ("sabe sobre", "KNOWS_ABOUT"),
    ("conoce la existencia de", "KNOWS_ABOUT"),
    ("knows about", "KNOWS_ABOUT"),
    ("vio a", "HAS_SEEN"),
    ("ha visto a", "HAS_SEEN"),
    ("ha visto", "HAS_SEEN"),
    ("avisto a", "HAS_SEEN"),
    ("has seen", "HAS_SEEN"),
    ("ha conocido a", "HAS_MET"),
    ("conocio a", "HAS_MET"),
    ("has met", "HAS_MET"),
    ("ha oido hablar de", "HAS_HEARD_ABOUT"),
    ("oyo hablar de", "HAS_HEARD_ABOUT"),
    ("oyeron hablar de", "HAS_HEARD_ABOUT"),
    ("has heard about", "HAS_HEARD_ABOUT"),
    ("ha combatido contra", "HAS_FOUGHT"),
    ("ha luchado contra", "HAS_FOUGHT"),
    ("has fought", "HAS_FOUGHT"),
    ("ha hablado con", "HAS_TALKED_TO"),
    ("has talked to", "HAS_TALKED_TO"),
    ("ha descubierto", "DISCOVERED"),
    ("discovered", "DISCOVERED"),
    ("estuvo presente en", "WAS_PRESENT_AT"),
    ("estuvieron presentes en", "WAS_PRESENT_AT"),
    ("was present at", "WAS_PRESENT_AT"),
    ("ha participado en", "PARTICIPATED_IN"),
    ("participated in", "PARTICIPATED_IN"),
    ("fue testigo de", "WITNESSED"),
    ("presencio", "WITNESSED"),
    ("witnessed", "WITNESSED"),
    ("fue informado por", "WAS_TOLD_BY"),
    ("was told by", "WAS_TOLD_BY"),
    ("le conto a", "TELLS"),
    ("conto a", "TELLS"),
    ("cuenta a", "TELLS"),
    ("tells", "TELLS"),
    ("cuenta sobre", "TELLS_ABOUT"),
    ("conto lo de", "TELLS_ABOUT"),
    ("tells about", "TELLS_ABOUT"),
    ("compartido con", "SHARED_WITH"),
    ("comparte con", "SHARED_WITH"),
    ("compartio con", "SHARED_WITH"),
    ("shared with", "SHARED_WITH"),
    ("conocido por el grupo", "KNOWN_BY_PARTY"),
    ("known by party", "KNOWN_BY_PARTY"),
    ("conocido publicamente", "KNOWN_PUBLICLY"),
    ("known publicly", "KNOWN_PUBLICLY"),
    ("involucra a", "INVOLVES"),
    ("involucra", "INVOLVES"),
    ("involves", "INVOLVES"),

    # ═══ Fase 5: compatibilidad de códigos ingleses del LLM ═══════════════════
    ("es in", "LOCATED_IN"),
    ("researches", "INVESTIGATES"),
    ("relates to", "RELATED_TO"),
    ("learns from", "LEARNS"),
    ("formulates plan against", "PLOTS_AGAINST"),
]

# Pre-compilar el mapa con claves ya normalizadas
RELATION_TYPE_NORMALIZE: dict[str, str] = {
    _normalize_key(k): v for k, v in _RAW_NORMALIZE
}


def normalize_relation_type(v: str) -> str:
    """Normalización básica usada por RelationshipBase validator (sin contexto)."""
    if v in ALLOWED_RELATION_TYPES:
        return v
    key = _normalize_key(v)
    mapped = RELATION_TYPE_NORMALIZE.get(key)
    if mapped and mapped in ALLOWED_RELATION_TYPES:
        return mapped
    return v


def normalize_relation_type_full(
    raw_relation_type: str,
    source: str = "",
    target: str = "",
    evidence: str = "",
    chunk_id: int = 0,
    pages: list[int] | None = None,
) -> tuple[str | None, str | None]:
    """Normaliza un tipo de relación libre al tipo canónico en inglés.

    Devuelve (normalized_type, warning_message).
    Si ya es canónico: (tipo, None).
    Si se normaliza: (tipo_canónico, warning_informativo).
    Si no se puede normalizar: (None, warning_de_descarte).

    La función usa source, target y evidence para desambiguar casos ambiguos.
    No inventa relaciones nuevas: solo mapea lo que el LLM ya intentó crear.
    """
    pages = pages or []

    # Paso 1: ya es canónico
    if raw_relation_type in ALLOWED_RELATION_TYPES:
        return raw_relation_type, None

    # Paso 2: normalizar clave y buscar en mapa
    key = _normalize_key(raw_relation_type)
    mapped = RELATION_TYPE_NORMALIZE.get(key)

    # Paso 3: si no hay match exacto, buscar por prefijo/contenido
    if not mapped:
        for norm_key, canon in RELATION_TYPE_NORMALIZE.items():
            if key.startswith(norm_key) or norm_key in key:
                mapped = canon
                break

    # Paso 4: desambiguación contextual para tipos ambiguos
    if mapped in ("SEES_IN_VISION", "HAS_SYMBOL_OF", "HAS_VISION_OF"):
        src_l = _normalize_key(source)
        tgt_l = _normalize_key(target)
        ev_l = _normalize_key(evidence)

        # "vista mascara" + target contiene clan → HAS_SYMBOL_OF
        if "mascara" in key or "simbolo" in key:
            if "clan" in tgt_l or "simbolo" in ev_l:
                mapped = "HAS_SYMBOL_OF"
            else:
                mapped = "SEES_IN_VISION"

        # "vista sosten fragmento" + evidence contiene "sosteniendo" → SEES_IN_VISION
        elif "sosten" in key or "fragmento" in key:
            if "sosteniendo" in ev_l or "sostiene" in ev_l:
                mapped = "SEES_IN_VISION"

        # origen Kimi + vision → HAS_VISION_OF
        elif "kimi" in src_l and "vision" in key:
            mapped = "HAS_VISION_OF"

    # Paso 5: resultado
    if mapped and mapped in ALLOWED_RELATION_TYPES:
        warn = (
            f"[normalizer] Chunk {chunk_id} pp.{pages}: "
            f"'{raw_relation_type}' → '{mapped}' "
            f"(src='{source}', tgt='{target}', ev='{evidence[:60]}')"
        )
        log.info(warn)
        return mapped, warn

    # No mapeado
    warn = (
        f"[normalizer] Chunk {chunk_id} pp.{pages}: "
        f"DESCARTADO tipo '{raw_relation_type}' sin mapeo "
        f"(src='{source}', tgt='{target}', ev='{evidence[:60]}')"
    )
    log.warning(warn)
    return None, warn


# ── Entidades colectivas reconocidas ─────────────────────────────────────────
# Términos que el LLM puede usar como sujeto colectivo en perfil transcript.
# Se resuelven a la entidad canónica "Grupo de la sesión".
COLLECTIVE_ENTITY_REFS: frozenset[str] = frozenset({
    "grupo", "el grupo", "los personajes", "los protagonistas",
    "los investigadores", "los magistrados", "el grupo de personajes",
    "personajes", "protagonistas", "investigadores", "magistrados",
    "los aventureros", "aventureros", "el partido", "partido",
})

# Nombres demasiado genéricos para alias automático
_GENERIC_NAMES: frozenset[str] = frozenset({
    "clan", "señor", "dama", "maestro", "sensei", "lord", "lady",
    "el", "la", "los", "las", "un", "una",
})


def add_auto_aliases(entity) -> "EntityBase":
    """Para Character con nombre de dos o más palabras, añade alias con el último término.

    Ejemplos: Kakita Asuka → alias 'Asuka'
    No actúa si ya tiene ese alias o si el último término es genérico.
    Devuelve el mismo objeto con aliases ampliado (mutable en place via object.__setattr__).
    """
    if entity.entity_type != "Character":
        return entity
    parts = entity.canonical_name.strip().split()
    if len(parts) < 2:
        return entity
    last = parts[-1]
    if _normalize_key(last) in _GENERIC_NAMES:
        return entity
    current = list(entity.aliases)
    if last not in current and last.lower() not in [a.lower() for a in current]:
        current.append(last)
        object.__setattr__(entity, "aliases", current)
    return entity


def make_collective_entity(workspace: str, source_document: str,
                           source_pages: list | None = None) -> "EntityBase":
    """Crea la entidad colectiva canónica para el grupo de personajes de la sesión."""
    return EntityBase(
        canonical_name="Grupo de la sesión",
        display_name="Grupo de la sesión",
        aliases=["Grupo", "el grupo", "los personajes", "los protagonistas"],
        description="Conjunto de personajes jugadores que participan en la sesión.",
        entity_type="Concept",
        workspace=workspace,
        source_document=source_document,
        source_pages=source_pages or [],
        confidence=0.95,
    )


def resolve_entity_ref(
    raw_name: str,
    chunk_entities: list,
    workspace: str,
    neo4j_writer=None,
    chunk_id: int = 0,
    pages: list | None = None,
) -> tuple[str | None, str | None]:
    """Resuelve una referencia de entidad libre al canonical_name correcto.

    Busca primero en chunk_entities (entidades ya validadas del chunk),
    luego opcionalmente en Neo4j si neo4j_writer está disponible.

    Estrategias en orden de confianza:
    1. Coincidencia exacta.
    2. Coincidencia case-insensitive.
    3. Coincidencia sin tildes.
    4. Coincidencia por alias.
    5. Coincidencia por último término del nombre (apellido/primer-nombre).
    6. Coincidencia por subcadena segura (solo si es única).

    Devuelve (canonical_name, warning).
    - Si resuelto sin ambigüedad: (canonical, None) o (canonical, info_warn).
    - Si ambiguo: (None, warning_ambiguous).
    - Si no resuelto: (None, None) — el llamador decide qué hacer.

    No inventa entidades nuevas.
    """
    pages = pages or []
    raw_key = _normalize_key(raw_name)

    candidates: list[tuple[str, str]] = []  # (canonical_name, match_reason)

    # Entidades del chunk + la entidad colectiva si aplica
    search_pool = list(chunk_entities)

    for entity in search_pool:
        c = entity.canonical_name
        c_key = _normalize_key(c)

        # 1. Exacta
        if c == raw_name:
            return c, None

        # 2. Case-insensitive
        if c.lower() == raw_name.lower():
            candidates.append((c, "case-insensitive"))
            continue

        # 3. Sin tildes
        if c_key == raw_key:
            candidates.append((c, "sin-tildes"))
            continue

        # 4. Por alias
        for alias in getattr(entity, "aliases", []):
            if _normalize_key(alias) == raw_key:
                candidates.append((c, f"alias:{alias}"))
                break

        # 5. Por último término del nombre canónico
        c_parts = c.strip().split()
        if c_parts and _normalize_key(c_parts[-1]) == raw_key:
            candidates.append((c, f"apellido:{c_parts[-1]}"))
            continue

        # 6. Subcadena segura: raw es subcadena del canónico o viceversa
        if len(raw_key) >= 3:
            if raw_key in c_key or c_key in raw_key:
                candidates.append((c, "subcadena"))

    # Deduplicar manteniendo el primero
    seen: dict[str, str] = {}
    for name, reason in candidates:
        if name not in seen:
            seen[name] = reason
    unique = list(seen.items())

    if not unique:
        return None, None

    if len(unique) == 1:
        resolved, reason = unique[0]
        warn = (
            f"[resolver] Chunk {chunk_id} pp.{pages}: "
            f"'{raw_name}' → '{resolved}' (método: {reason})"
        )
        log.info(warn)
        return resolved, warn

    # Ambiguo: más de un candidato
    names_str = ", ".join(f"'{n}'" for n, _ in unique)
    warn = (
        f"[resolver] Chunk {chunk_id} pp.{pages}: "
        f"AMBIGUO '{raw_name}' → candidatos: {names_str} — no se resuelve"
    )
    log.warning(warn)
    return None, warn


# Campos opcionales de entidad (Fase 2/7/8/9/11). Todos seguros y opcionales:
# solo se escriben en Neo4j si tienen valor, para no sobrescribir nodos antiguos.
_OPTIONAL_ENTITY_FIELDS: tuple[str, ...] = (
    # descriptivos
    "subtype", "species", "role",
    # estado y clasificación narrativa
    "attitude", "status", "danger_level", "is_human", "is_unique",
    # visibilidad y capa de conocimiento
    "visibility", "knowledge_layer",
    # metadatos temporales / cronología (Fase 7)
    "first_seen_session", "first_seen_date",
    "last_seen_session", "last_seen_date",
    "source_session", "source_date", "chronology_order",
    # Session como nodo (Fase 8)
    "session_number", "session_title", "session_date",
    "campaign_arc", "summary",
    # imágenes (Fase 9)
    "image_path", "thumbnail_path", "media_source",
    # revisión (Fase 11)
    "review_status", "manual_review_required",
    "requires_metadata", "created_from_relation",
    # conocimiento por personaje (Fase conocimiento)
    "known_by_scope", "known_by_characters", "known_by_users",
    "known_by_party", "known_publicly", "known_from_session",
    "known_from_date", "knowledge_quality", "knowledge_confidence",
    "shared_from_character", "shared_to_character", "shared_at_session",
)


class EntityBase(BaseModel):
    canonical_name: str = Field(..., min_length=1, max_length=500)
    display_name: str = Field(..., min_length=1, max_length=500)
    aliases: list[str] = Field(default_factory=list)
    description: str = Field(default="")
    entity_type: str
    workspace: str = Field(..., min_length=1)
    source_document: str = Field(default="")
    source_pages: list[int] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: str = Field(default="")

    # ── Campos opcionales (Fase 2) — descriptivos ─────────────────────────────
    subtype: Optional[str] = None
    species: Optional[str] = None
    role: Optional[str] = None
    # ── Estado y clasificación (vocabulario controlado, degradación segura) ──
    attitude: Optional[str] = None
    status: Optional[str] = None
    danger_level: Optional[str] = None
    is_human: Optional[bool] = None
    is_unique: Optional[bool] = None
    # ── Visibilidad y capa de conocimiento ────────────────────────────────────
    visibility: Optional[str] = None
    knowledge_layer: Optional[str] = None
    # ── Metadatos temporales / cronología (Fase 7) ────────────────────────────
    first_seen_session: Optional[int] = None
    first_seen_date: Optional[str] = None
    last_seen_session: Optional[int] = None
    last_seen_date: Optional[str] = None
    source_session: Optional[int] = None
    source_date: Optional[str] = None
    chronology_order: Optional[int] = None
    # ── Session como nodo (Fase 8) ────────────────────────────────────────────
    session_number: Optional[int] = None
    session_title: Optional[str] = None
    session_date: Optional[str] = None
    campaign_arc: Optional[str] = None
    summary: Optional[str] = None
    # ── Imágenes (Fase 9) ─────────────────────────────────────────────────────
    image_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    media_source: Optional[str] = None
    # ── Estado de revisión (Fase 11) ──────────────────────────────────────────
    review_status: Optional[str] = "auto_extracted"
    manual_review_required: Optional[bool] = None
    requires_metadata: Optional[bool] = None
    created_from_relation: Optional[bool] = None
    # ── Conocimiento por personaje (Fase conocimiento) ────────────────────────
    known_by_scope: Optional[str] = None
    known_by_characters: Optional[list[str]] = None
    known_by_users: Optional[list[str]] = None
    known_by_party: Optional[bool] = None
    known_publicly: Optional[bool] = None
    known_from_session: Optional[int] = None
    known_from_date: Optional[str] = None
    knowledge_quality: Optional[str] = None
    knowledge_confidence: Optional[float] = None
    shared_from_character: Optional[str] = None
    shared_to_character: Optional[str] = None
    shared_at_session: Optional[int] = None

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        if v not in ALLOWED_NODE_TYPES:
            raise ValueError(
                f"entity_type '{v}' no permitido. Permitidos: {sorted(ALLOWED_NODE_TYPES)}"
            )
        return v

    @field_validator("canonical_name")
    @classmethod
    def sanitize_canonical_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("attitude")
    @classmethod
    def _v_attitude(cls, v):
        return _coerce_vocab(v, ALLOWED_ATTITUDE, "unknown")

    @field_validator("status")
    @classmethod
    def _v_status(cls, v):
        return _coerce_vocab(v, ALLOWED_STATUS, "unknown")

    @field_validator("danger_level")
    @classmethod
    def _v_danger(cls, v):
        return _coerce_vocab(v, ALLOWED_DANGER_LEVEL, "unknown")

    @field_validator("visibility")
    @classmethod
    def _v_visibility(cls, v):
        return _coerce_vocab(v, ALLOWED_VISIBILITY, "narrator")

    @field_validator("knowledge_layer")
    @classmethod
    def _v_klayer(cls, v):
        return _coerce_vocab(v, ALLOWED_KNOWLEDGE_LAYER, "inferred")

    @field_validator("review_status")
    @classmethod
    def _v_review(cls, v):
        if v is None:
            return "auto_extracted"
        return _coerce_vocab(v, ALLOWED_REVIEW_STATUS, "auto_extracted")

    @field_validator("known_by_scope")
    @classmethod
    def _v_scope(cls, v):
        return _coerce_vocab(v, ALLOWED_KNOWN_BY_SCOPE, "character")

    @field_validator("knowledge_quality")
    @classmethod
    def _v_kquality(cls, v):
        return _coerce_vocab(v, ALLOWED_KNOWLEDGE_QUALITY, "inferred")

    def to_neo4j_params(self) -> dict:
        params = {
            "canonical_name": self.canonical_name,
            "display_name": self.display_name,
            "aliases": self.aliases,
            "description": self.description,
            "entity_type": self.entity_type,
            "workspace": self.workspace,
            "source_document": self.source_document,
            "source_pages": self.source_pages,
            "confidence": self.confidence,
        }
        # Solo incluir campos opcionales con valor (no null-sobrescribir)
        for f in _OPTIONAL_ENTITY_FIELDS:
            val = getattr(self, f, None)
            if val is not None:
                params[f] = val
        return params

    def optional_neo4j_fields(self) -> dict:
        """Devuelve solo los campos opcionales con valor (para SET dinámico)."""
        out = {}
        for f in _OPTIONAL_ENTITY_FIELDS:
            val = getattr(self, f, None)
            if val is not None:
                out[f] = val
        return out


# Campos opcionales de relación (conocimiento). Solo se escriben si tienen valor.
_OPTIONAL_RELATION_FIELDS: tuple[str, ...] = (
    "known_by_scope", "knowledge_quality", "known_from_session",
    "known_from_date", "shared_from_character", "shared_to_character",
    "shared_at_session",
)


class RelationshipBase(BaseModel):
    source_canonical: str = Field(..., min_length=1)
    relation_type: str
    target_canonical: str = Field(..., min_length=1)
    evidence: str = Field(default="")
    source_document: str = Field(default="")
    source_pages: list[int] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    # Campo de presentación: etiqueta visible en español
    relation_label_es: str = Field(default="")
    # ── Conocimiento por personaje (opcional) ─────────────────────────────────
    known_by_scope: Optional[str] = None
    knowledge_quality: Optional[str] = None
    known_from_session: Optional[int] = None
    known_from_date: Optional[str] = None
    shared_from_character: Optional[str] = None
    shared_to_character: Optional[str] = None
    shared_at_session: Optional[int] = None

    @field_validator("known_by_scope")
    @classmethod
    def _v_rel_scope(cls, v):
        return _coerce_vocab(v, ALLOWED_KNOWN_BY_SCOPE, "character")

    @field_validator("knowledge_quality")
    @classmethod
    def _v_rel_kquality(cls, v):
        return _coerce_vocab(v, ALLOWED_KNOWLEDGE_QUALITY, "inferred")

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        # Intentar normalización básica (sin contexto) antes de rechazar
        normalized = normalize_relation_type(v)
        if normalized not in ALLOWED_RELATION_TYPES:
            raise ValueError(
                f"relation_type '{v}' no permitido. Permitidos: {sorted(ALLOWED_RELATION_TYPES)}"
            )
        return normalized

    def model_post_init(self, __context) -> None:
        # Rellenar relation_label_es si no viene del LLM
        if not self.relation_label_es:
            object.__setattr__(
                self, "relation_label_es",
                RELATION_LABELS_ES.get(self.relation_type, self.relation_type.lower().replace("_", " "))
            )

    def to_neo4j_params(self) -> dict:
        params = {
            "source_canonical": self.source_canonical,
            "relation_type": self.relation_type,
            "target_canonical": self.target_canonical,
            "evidence": self.evidence,
            "source_document": self.source_document,
            "source_pages": self.source_pages,
            "confidence": self.confidence,
            "relation_label_es": self.relation_label_es,
        }
        for f in _OPTIONAL_RELATION_FIELDS:
            val = getattr(self, f, None)
            if val is not None:
                params[f] = val
        return params


class ExtractionResult(BaseModel):
    entities: list[EntityBase] = Field(default_factory=list)
    relationships: list[RelationshipBase] = Field(default_factory=list)
    raw_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentMeta(BaseModel):
    path: str
    workspace: str
    sha256: str
    size_bytes: int
    num_pages: int
    model: str
    schema_version: str = SCHEMA_VERSION
    prompt_version: str = "1.4.0"
