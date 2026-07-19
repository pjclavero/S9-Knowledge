# -*- coding: utf-8 -*-
"""Vocabulario CANONICO de predicados de relacion (normalizacion semantica).

Este modulo separa la normalizacion *semantica* de predicados (sinonimos,
canonicalizacion, tipos permitidos, simetria) de la normalizacion meramente
*tipografica* que ya provee `relations.contracts.normalize_predicate`
(espacios/guiones -> `_`, MAYUSCULAS). Aqui NO se reescribe esa funcion: se
reutiliza como paso previo.

Principios:

  * DETERMINISTA y puro: sin red, sin disco, sin estado global mutable.
  * SIN inventar semantica: los alias son sinonimos SIN PERDIDA de significado.
    Un predicado del dominio que no tiene canonico claro en v1 se envia a
    revision humana (`out_of_vocab`) en lugar de forzar un mapeo dudoso.
  * FUENTE UNICA de los canonicos: se reutiliza `prompts.KNOWN_PREDICATES` y los
    tipos permitidos se derivan de las propias plantillas (`prompts.TEMPLATES`),
    para no duplicar a mano la ontologia.

Version del vocabulario (`VOCAB_VERSION`) INDEPENDIENTE de `SCHEMA_VERSION`:
ampliar el vocabulario (p.ej. mover predicados de `OUT_OF_VOCAB_V1` a canonicos
en v2) no cambia el contrato de datos, solo esta capa de mapeo.
"""
from __future__ import annotations

from dataclasses import dataclass

from relations.contracts import normalize_predicate
from relations.prompts import KNOWN_PREDICATES, TEMPLATES

# ---------------------------------------------------------------------------
# Version del vocabulario (independiente de SCHEMA_VERSION del contrato).
# ---------------------------------------------------------------------------
VOCAB_VERSION = "relation-vocab-1.0.0"

# ---------------------------------------------------------------------------
# Predicados canonicos: fuente unica reutilizada de las plantillas de prompt.
# ---------------------------------------------------------------------------
CANONICAL_PREDICATES: frozenset = frozenset(KNOWN_PREDICATES)

# ---------------------------------------------------------------------------
# Alias: SINONIMOS SIN PERDIDA de significado -> canonico.
#
# Solo variantes lexicas/morfologicas de un canonico existente. NO se incluye
# ningun predicado que aporte matiz semantico nuevo (esos van a OUT_OF_VOCAB_V1).
# Las claves se normalizan tipograficamente para robustez ante la entrada.
# ---------------------------------------------------------------------------
_RAW_ALIASES: dict[str, str] = {
    "ENEMY_OF": "ENEMIES_WITH",
    "ENEMY_WITH": "ENEMIES_WITH",
    "SUCCEEDED": "SUCCESSOR_OF",
    # NOTA: "SUCCEEDED_BY" NO se aliasa: es la INVERSA de SUCCESSOR_OF (invierte
    # sujeto/objeto), no un sinonimo sin perdida. Las inversas se tratan aparte
    # (INVERSE_PREDICATES / inverse_of), no como alias.
    "LIVES_IN": "LOCATED_IN",
    "ALLY_OF": "ALLIED_WITH",
    "MEMBER": "MEMBER_OF",
}
PREDICATE_ALIASES: dict[str, str] = {
    normalize_predicate(k): v for k, v in _RAW_ALIASES.items()
}

# ---------------------------------------------------------------------------
# Predicados simetricos (UNDIRECTED por defecto en las plantillas).
# ---------------------------------------------------------------------------
SYMMETRIC_PREDICATES: frozenset = frozenset({"ALLIED_WITH", "ENEMIES_WITH", "KIN_OF"})

# ---------------------------------------------------------------------------
# Inversas canonicas.
#
# Mecanismo: si `A INVERSE_PREDICATES B`, entonces "sujeto A objeto" equivale a
# "objeto B sujeto". En v1 NO hay pares de canonicos que sean inversos entre si
# (PRECEDES/SUCCESSOR_OF NO lo son: uno es orden temporal, el otro sucesion de
# cargo), por lo que el mapa queda VACIO y `inverse_of` devuelve None. Se deja
# el mecanismo definido para que v2 pueda anadir pares sin cambiar la API.
# ---------------------------------------------------------------------------
INVERSE_PREDICATES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Predicados conocidos del dominio SIN canonico en v1 -> fallback humano.
#
# Candidatos a vocabulario v2 (requeriria plantillas de prompt nuevas). NO se
# mapean a ningun canonico porque aportan semantica que ninguno cubre sin
# perdida. Se normalizan tipograficamente para la comparacion.
# ---------------------------------------------------------------------------
_RAW_OUT_OF_VOCAB_V1 = {
    "MENTOR_OF",
    "GUARDS",
    "FOUNDED",
    "ALIAS_OF",
    "TRUSTS",
    "LEADS",
    "KNOWS",
    "CREATED",
    "PARENT_OF",
    "SIBLING_OF",
    "MARRIED_TO",
    "CHILD_OF",
    "SPOUSE_OF",
}
OUT_OF_VOCAB_V1: frozenset = frozenset(
    normalize_predicate(p) for p in _RAW_OUT_OF_VOCAB_V1
)

# ---------------------------------------------------------------------------
# Compatibilidad de tipos por canonico: (subject_types, object_types).
#
# Derivada de las plantillas de prompt (fuente unica), NO tecleada a mano.
# ---------------------------------------------------------------------------
TYPE_COMPATIBILITY: dict[str, tuple[frozenset, frozenset]] = {
    tpl.predicate: (frozenset(tpl.subject_types), frozenset(tpl.object_types))
    for tpl in TEMPLATES.values()
}


@dataclass(frozen=True)
class PredicateCanonicalization:
    """Resultado de canonicalizar un predicado crudo.

    Campos:
      * `raw`: entrada literal recibida.
      * `normalized`: `normalize_predicate(raw)` (normalizacion tipografica).
      * `canonical`: predicado canonico resuelto, o None si no hay.
      * `status`: uno de {"canonical", "alias", "out_of_vocab", "unknown"}.
      * `rule`: etiqueta de la regla que decidio el resultado.
      * `vocab_version`: version del vocabulario aplicada.
      * `requires_human`: True si el predicado no tiene canonico y debe ir a
        revision humana (status in {"out_of_vocab", "unknown"}).
    """

    raw: str
    normalized: str
    canonical: str | None
    status: str
    rule: str
    vocab_version: str
    requires_human: bool


def canonicalize_predicate(raw: str) -> PredicateCanonicalization:
    """Canonicaliza un predicado crudo a su forma canonica o a fallback humano.

    Orden de decision (determinista):
      1. Normaliza tipograficamente con `normalize_predicate`.
      2. Si ya es canonico -> status="canonical".
      3. Si es un alias sin perdida -> status="alias", canonical = destino.
      4. Si es un predicado conocido sin canonico en v1 -> status="out_of_vocab",
         requires_human=True.
      5. En otro caso -> status="unknown", requires_human=True.
    """
    normalized = normalize_predicate(raw)

    if normalized in CANONICAL_PREDICATES:
        return PredicateCanonicalization(
            raw=raw,
            normalized=normalized,
            canonical=normalized,
            status="canonical",
            rule="exact-canonical",
            vocab_version=VOCAB_VERSION,
            requires_human=False,
        )

    if normalized in PREDICATE_ALIASES:
        return PredicateCanonicalization(
            raw=raw,
            normalized=normalized,
            canonical=PREDICATE_ALIASES[normalized],
            status="alias",
            rule="alias-synonym",
            vocab_version=VOCAB_VERSION,
            requires_human=False,
        )

    if normalized in OUT_OF_VOCAB_V1:
        return PredicateCanonicalization(
            raw=raw,
            normalized=normalized,
            canonical=None,
            status="out_of_vocab",
            rule="out-of-vocab-v1",
            vocab_version=VOCAB_VERSION,
            requires_human=True,
        )

    return PredicateCanonicalization(
        raw=raw,
        normalized=normalized,
        canonical=None,
        status="unknown",
        rule="unknown",
        vocab_version=VOCAB_VERSION,
        requires_human=True,
    )


def predicates_match(pred_a: str, pred_b: str) -> bool:
    """True si ambos predicados resuelven al MISMO canonico.

    Canonicaliza ambos lados (incluye alias). Un predicado sin canonico (None)
    NUNCA empareja, ni siquiera None == None: dos predicados fuera de vocabulario
    no se consideran iguales a efectos de metricas, porque su significado no esta
    determinado.
    """
    ca = canonicalize_predicate(pred_a).canonical
    cb = canonicalize_predicate(pred_b).canonical
    if ca is None or cb is None:
        return False
    return ca == cb


def is_symmetric(pred: str) -> bool:
    """True si el canonico del predicado es simetrico (UNDIRECTED)."""
    canonical = canonicalize_predicate(pred).canonical
    return canonical in SYMMETRIC_PREDICATES if canonical is not None else False


def inverse_of(pred: str) -> str | None:
    """Devuelve el canonico inverso del predicado, o None si no hay.

    En v1 `INVERSE_PREDICATES` esta vacio (no hay inversas canonicas claras), por
    lo que siempre devuelve None. El mecanismo queda listo para v2.
    """
    canonical = canonicalize_predicate(pred).canonical
    if canonical is None:
        return None
    return INVERSE_PREDICATES.get(canonical)


def types_compatible(pred: str, subject_type, object_type) -> bool:
    """True si el canonico admite (subject_type, object_type).

    Para predicados simetricos se aceptan AMBOS ordenes de los tipos (el par no
    esta orientado). Si el predicado no es canonico -> False. Tipos None nunca
    son compatibles (no se puede verificar la ontologia sin tipo).
    """
    canonical = canonicalize_predicate(pred).canonical
    if canonical is None or canonical not in TYPE_COMPATIBILITY:
        return False
    if subject_type is None or object_type is None:
        return False
    subj_ok, obj_ok = TYPE_COMPATIBILITY[canonical]
    if subject_type in subj_ok and object_type in obj_ok:
        return True
    if canonical in SYMMETRIC_PREDICATES:
        # Par no orientado: acepta el orden inverso.
        return object_type in subj_ok and subject_type in obj_ok
    return False


__all__ = [
    "VOCAB_VERSION",
    "CANONICAL_PREDICATES",
    "PREDICATE_ALIASES",
    "SYMMETRIC_PREDICATES",
    "INVERSE_PREDICATES",
    "OUT_OF_VOCAB_V1",
    "TYPE_COMPATIBILITY",
    "PredicateCanonicalization",
    "canonicalize_predicate",
    "predicates_match",
    "is_symmetric",
    "inverse_of",
    "types_compatible",
]
