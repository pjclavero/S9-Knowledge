# -*- coding: utf-8 -*-
"""FUENTE UNICA de ontologia de predicados de relacion (motor v2, Bloque 1).

Este modulo centraliza, por predicado CANONICO, todo lo que hasta ahora estaba
DISPERSO entre `relations/pipeline.py`, `relations/signals.py`,
`relations/vocabulary.py`, `relations/prompts/templates.py` y
`schemas/rpg_schema.py`:

    canonical, aliases, family, domain (tipos de sujeto validos),
    range (tipos de objeto validos), inverse, symmetric, active_expressions,
    passive_expressions, confusable_with, temporality_hint.

REGLA DURA — METRIC-NEUTRAL (Bloque 1)
--------------------------------------
Esta ontologia es una ESTRUCTURA DE DATOS declarativa que consumiran B2/B3/B4.
En B1 NADIE la usa en el camino de puntuacion del benchmark: NO se cambia
`vocabulary.predicates_match`, NI `PREDICATE_ALIASES`, NI `_choose_predicate`,
NI el pipeline de decision. El benchmark debe dar EXACTAMENTE los mismos hashes
antes y despues de introducir este modulo (A/B plano).

Los canonicos aqui son los del GROUND TRUTH y del contrato
(`schemas.rpg_schema.ALLOWED_RELATION_TYPES`), NO los de `vocabulary.py`. Cuando
ambos DIVERGEN (p.ej. `vocabulary` aliasa `LIVES_IN -> LOCATED_IN`, que el
Bloque 0 decidio mantener como canonico DISTINTO), la divergencia se DOCUMENTA
en `VOCABULARY_DIVERGENCES` para revision aislada; NO se "arregla" aqui, porque
consolidar la fuente unica que afecta a puntuacion mueve metricas y es sensible.

Derivacion de dominio/rango/simetria/inversa
--------------------------------------------
  * dominio/rango: derivados de forma CONSERVADORA de (a) los tipos observados
    en el ground truth del corpus de benchmark, (b) los `subject_types`/
    `object_types` de las plantillas de prompt, generalizados a grupos
    semanticos coherentes dentro de `ALLOWED_NODE_TYPES`. Son ADVISORY (los
    consumira la validacion ontologica de B3/B4), no intervienen en la
    puntuacion de B1.
  * simetria: predicados no orientados (ALLIED_WITH, ENEMY_OF, SIBLING_OF,
    MARRIED_TO, ALIAS_OF). KNOWS se marca DIRIGIDO (el GT lo anota
    SUBJECT_TO_OBJECT); ver nota en `_SYMMETRY_NOTES`.
  * inversa: dentro del conjunto CERRADO de canonicos del GT no hay pares
    reciprocos limpios (CHILD_OF no es canonico; SUCCESSOR_OF no pertenece al
    conjunto), por lo que `inverse` es None para todos. El mecanismo queda
    listo para que B2+ anada pares con reciprocidad verificada por el test.

DETERMINISTA y puro: sin red, sin disco, sin estado global mutable.
"""
from __future__ import annotations

from dataclasses import dataclass

from relations.contracts import normalize_predicate
from schemas.rpg_schema import ALLOWED_NODE_TYPES

ONTOLOGY_VERSION = "relation-ontology-2.0.0"

# ---------------------------------------------------------------------------
# Grupos semanticos de tipos de nodo (subconjuntos de ALLOWED_NODE_TYPES).
# Se usan SOLO para componer dominio/rango de forma legible y conservadora.
# ---------------------------------------------------------------------------
_PERSON: frozenset = frozenset({"Character", "Creature", "NonHuman", "Spirit", "Demon", "Beast"})
_ORG: frozenset = frozenset({"Faction", "Clan", "Family", "School", "Group"})
_PLACE: frozenset = frozenset({"Location", "Region"})
_THING: frozenset = frozenset({"Object", "Artifact", "Spell"})
_HAPPENING: frozenset = frozenset({"Event", "Encounter", "Combat", "Task", "Session"})
_ACTOR: frozenset = _PERSON | _ORG

# Valores permitidos de `temporality_hint`.
TEMPORALITY_HINTS: frozenset = frozenset({"stative", "punctual", "atemporal"})

# Valores permitidos de `family`.
FAMILIES: frozenset = frozenset({
    "kinship", "alliance", "enmity", "membership", "leadership", "location",
    "residence", "possession", "creation", "foundation", "participation",
    "mentorship", "succession", "causality", "guardianship", "cognition",
    "trust", "identity",
})


@dataclass(frozen=True)
class PredicateOntology:
    """Descripcion ontologica AUTORITATIVA de un predicado canonico.

    Campos:
      * `canonical`: predicado canonico (MAYUSCULAS_CON_GUION_BAJO).
      * `family`: familia semantica (ver `FAMILIES`).
      * `domain`: tipos de nodo validos como SUJETO (subconjunto de
        ALLOWED_NODE_TYPES).
      * `range`: tipos de nodo validos como OBJETO.
      * `symmetric`: True si el predicado es no orientado (UNDIRECTED).
      * `inverse`: canonico inverso dentro de la ontologia, o None.
      * `aliases`: sinonimos SIN PERDIDA de significado que resuelven a este
        canonico (segun ESTA ontologia; puede DIVERGIR de `vocabulary`).
      * `active_expressions`: pistas lexicas en voz activa (sujeto->objeto).
      * `passive_expressions`: pistas lexicas en voz pasiva/inversa.
      * `confusable_with`: canonicos con los que se confunde con frecuencia.
      * `temporality_hint`: clase temporal por defecto (ver `TEMPORALITY_HINTS`).
    """

    canonical: str
    family: str
    domain: frozenset
    range: frozenset
    symmetric: bool
    inverse: str | None
    aliases: frozenset
    active_expressions: tuple
    passive_expressions: tuple
    confusable_with: frozenset
    temporality_hint: str


def _p(
    canonical: str,
    family: str,
    domain: frozenset,
    rng: frozenset,
    *,
    symmetric: bool = False,
    inverse: str | None = None,
    aliases: frozenset = frozenset(),
    active: tuple = (),
    passive: tuple = (),
    confusable: frozenset = frozenset(),
    temporality_hint: str = "stative",
) -> PredicateOntology:
    return PredicateOntology(
        canonical=canonical,
        family=family,
        domain=domain,
        range=rng,
        symmetric=symmetric,
        inverse=inverse,
        aliases=aliases,
        active_expressions=active,
        passive_expressions=passive,
        confusable_with=confusable,
        temporality_hint=temporality_hint,
    )


# ---------------------------------------------------------------------------
# Definicion de la ontologia: los 20 canonicos del ground truth + nucleo comun.
# ---------------------------------------------------------------------------
_ONTOLOGY_LIST: tuple[PredicateOntology, ...] = (
    _p(
        "MEMBER_OF", "membership", _PERSON, _ORG,
        aliases=frozenset({"MEMBER", "BELONGS_TO"}),
        active=("miembro de", "es miembro de", "pertenece a", "del clan", "member of"),
        passive=("tiene como miembro a", "cuenta entre sus filas con"),
        confusable=frozenset({"ALLIED_WITH", "LEADS", "PARTICIPATED_IN", "SUCCEEDED"}),
    ),
    _p(
        "LEADS", "leadership", _PERSON, _ORG | frozenset({"Concept"}),
        aliases=frozenset({"COMMANDS"}),
        active=("lidera", "dirige", "manda sobre", "encabeza", "leads"),
        passive=("liderado por", "dirigido por"),
        confusable=frozenset({"MEMBER_OF", "FOUNDED", "OWNS", "GUARDS"}),
    ),
    _p(
        "ALLIED_WITH", "alliance", _ACTOR, _ACTOR,
        symmetric=True,
        aliases=frozenset({"ALLY_OF"}),
        active=("aliado con", "aliado de", "sello una alianza con", "alianza con",
                "una alianza con", "su alianza con", "allied with"),
        passive=("aliado con", "en alianza con", "alianza"),
        confusable=frozenset({"MEMBER_OF", "MARRIED_TO", "ENEMY_OF"}),
    ),
    _p(
        "ENEMY_OF", "enmity", _ACTOR, _ACTOR,
        symmetric=True,
        aliases=frozenset({"ENEMIES_WITH", "ENEMY_WITH"}),
        active=("enemigo de", "enemigo declarado", "enemigo", "en guerra con",
                "rival de", "enemy of"),
        passive=("enemigo de", "enfrentado a"),
        confusable=frozenset({"ALLIED_WITH", "PARTICIPATED_IN"}),
    ),
    _p(
        "PARENT_OF", "kinship", _PERSON, _PERSON,
        active=("padre de", "madre de", "progenitor de", "parent of"),
        passive=("hijo de", "hija de", "descendiente de", "nacio", "de esa union nacio"),
        confusable=frozenset({"SIBLING_OF", "MENTOR_OF", "MARRIED_TO"}),
    ),
    _p(
        "SIBLING_OF", "kinship", _PERSON, _PERSON,
        symmetric=True,
        aliases=frozenset({"BROTHER_OF", "SISTER_OF"}),
        active=("hermano de", "hermana de", "sibling of"),
        passive=("hermano de", "hermana de"),
        confusable=frozenset({"PARENT_OF", "MARRIED_TO", "ALLIED_WITH"}),
    ),
    _p(
        "MARRIED_TO", "kinship", _PERSON, _PERSON,
        symmetric=True,
        aliases=frozenset({"SPOUSE_OF"}),
        active=("casado con", "casada con", "esposo de", "esposa de", "married to"),
        passive=("casado con", "conyuge de"),
        confusable=frozenset({"SIBLING_OF", "ALLIED_WITH", "PARENT_OF"}),
    ),
    _p(
        "LOCATED_IN", "location", _ACTOR | _THING | _HAPPENING, _PLACE,
        active=("ubicado en", "situado en", "se encuentra en", "se celebra en",
                "located in"),
        passive=("alberga", "contiene"),
        confusable=frozenset({"LIVES_IN", "PARTICIPATED_IN", "GUARDS"}),
    ),
    _p(
        "LIVES_IN", "residence", _PERSON, _PLACE,
        active=("vive en", "viva en", "vivia en", "habita en", "reside en", "lives in"),
        passive=("habitado por", "residencia de"),
        # confusable con LOCATED_IN: es la divergencia central con vocabulary
        # (residencia vs. ubicacion). Ver VOCABULARY_DIVERGENCES.
        confusable=frozenset({"LOCATED_IN"}),
    ),
    _p(
        "OWNS", "possession", _ACTOR | frozenset({"Concept"}), _THING,
        aliases=frozenset({"HOLDS"}),
        active=("posee", "porta", "empuna", "es dueno de", "owns"),
        passive=("propiedad de", "en poder de", "pertenece a", "pertenece al",
                 "robado por", "robada por"),
        confusable=frozenset({"CREATED", "GUARDS", "LEADS"}),
    ),
    _p(
        "CREATED", "creation", _ACTOR, _THING | _ORG | _PLACE,
        aliases=frozenset({"CREATED_BY"}),
        active=("creo", "forjo", "forja", "construyo", "created"),
        passive=("creado por", "creada por", "forjado por", "forjada por", "obra de"),
        confusable=frozenset({"FOUNDED", "OWNS"}),
        temporality_hint="punctual",
    ),
    _p(
        "FOUNDED", "foundation", _PERSON | _ORG, _ORG | _PLACE,
        active=("fundo", "funda", "establecio", "founded"),
        passive=("fundado por", "fundada por", "establecido por"),
        confusable=frozenset({"CREATED", "LEADS", "MEMBER_OF"}),
        temporality_hint="punctual",
    ),
    _p(
        "PARTICIPATED_IN", "participation", _ACTOR, _HAPPENING,
        active=("participo en", "participaron", "participar", "participa",
                "lucho en", "asistio a", "compitio en", "competira en",
                "participated in"),
        passive=("conto con la participacion de",),
        confusable=frozenset({"LOCATED_IN", "CAUSED", "ENEMY_OF"}),
        temporality_hint="punctual",
    ),
    _p(
        "MENTOR_OF", "mentorship", _PERSON, _PERSON,
        aliases=frozenset({"TEACHES"}),
        active=("mentor de", "maestro de", "maestra de", "maestro", "maestra",
                "entreno a", "enseno el", "enseno a", "le enseno", "mentor of"),
        passive=("alumno de", "discipulo de", "aprendiz de"),
        confusable=frozenset({"PARENT_OF"}),
    ),
    _p(
        "KNOWS", "cognition", _PERSON | frozenset({"Concept"}),
        _ACTOR | _THING | frozenset({"Concept"}),
        active=("conoce a", "sabe de", "domina", "knows"),
        passive=("es conocido por",),
        confusable=frozenset({"TRUSTS", "MENTOR_OF"}),
    ),
    _p(
        "TRUSTS", "trust", _PERSON, _ACTOR,
        active=("confia en", "confio en", "trusts"),
        passive=("goza de la confianza de",),
        confusable=frozenset({"KNOWS", "ALLIED_WITH"}),
    ),
    _p(
        "SUCCEEDED", "succession", _PERSON, _PERSON | _ORG,
        aliases=frozenset({"SUCCESSOR_OF"}),
        active=("sucedio a", "sucede a", "heredo de", "hereda", "herede",
                "heredar", "succeeded"),
        passive=("sucedido por", "reemplazado por"),
        confusable=frozenset({"PARENT_OF", "MEMBER_OF", "LEADS"}),
        temporality_hint="punctual",
    ),
    _p(
        "CAUSED", "causality", _HAPPENING | _ACTOR | frozenset({"Concept"}), _HAPPENING,
        active=("causo", "provoco", "desencadeno", "desencadenar", "caused"),
        passive=("causado por", "provocado por"),
        confusable=frozenset({"PARTICIPATED_IN"}),
        temporality_hint="punctual",
    ),
    _p(
        "GUARDS", "guardianship", _ACTOR | _PLACE, _THING | _PLACE | _PERSON,
        aliases=frozenset({"PROTECTS"}),
        active=("guarda", "custodia", "protege", "vigila", "guards"),
        passive=("guardado por", "guardada por", "custodiado por", "custodiada por"),
        confusable=frozenset({"OWNS", "LOCATED_IN"}),
    ),
    _p(
        "ALIAS_OF", "identity", _ACTOR, _ACTOR,
        symmetric=True,
        active=("es alias de", "tambien conocido como", "conocido como",
                "conocida como", "apodado", "apodada", "alias of"),
        passive=("es alias de", "conocido tambien como"),
        confusable=frozenset({"MEMBER_OF"}),
        temporality_hint="atemporal",
    ),
)

ONTOLOGY: dict[str, PredicateOntology] = {o.canonical: o for o in _ONTOLOGY_LIST}

# Canonicos que forman la ontologia (fuente unica).
CANONICAL_PREDICATES: frozenset = frozenset(ONTOLOGY)

# Predicados simetricos derivados de la propia ontologia (fuente unica).
SYMMETRIC_PREDICATES: frozenset = frozenset(
    o.canonical for o in _ONTOLOGY_LIST if o.symmetric
)

# Mapa alias -> canonico segun ESTA ontologia (normalizado tipograficamente).
ALIAS_TO_CANONICAL: dict[str, str] = {}
for _o in _ONTOLOGY_LIST:
    for _a in _o.aliases:
        ALIAS_TO_CANONICAL[normalize_predicate(_a)] = _o.canonical

# ---------------------------------------------------------------------------
# DIVERGENCIAS con vocabulary.py — DOCUMENTADAS, NO APLICADAS (metric-neutral).
#
# Cada entrada: canonico_ontologia -> como lo trata `vocabulary` hoy. Estas
# divergencias afectan a la PUNTUACION (el arnes usa `vocabulary.predicates_match`)
# y su consolidacion es SENSIBLE: se hara con aprobacion explicita fuera de B1.
# ---------------------------------------------------------------------------
VOCABULARY_DIVERGENCES: dict[str, dict] = {
    # `vocabulary` aliasa LIVES_IN -> LOCATED_IN; el Bloque 0 lo mantiene como
    # canonico DISTINTO (residencia vs. ubicacion). Da CREDITO POR ALIAS en el
    # benchmark: predicts LOCATED_IN casan con GT LIVES_IN.
    "LIVES_IN": {"kind": "alias_collapse", "vocab_canonical": "LOCATED_IN"},
    # `vocabulary` aliasa ENEMY_OF -> ENEMIES_WITH (variante lexica). El GT y el
    # contrato usan ENEMY_OF como canonico.
    "ENEMY_OF": {"kind": "alias_rename", "vocab_canonical": "ENEMIES_WITH"},
    # `vocabulary` aliasa SUCCEEDED -> SUCCESSOR_OF. El GT usa SUCCEEDED.
    "SUCCEEDED": {"kind": "alias_rename", "vocab_canonical": "SUCCESSOR_OF"},
    # Canonicos del GT que `vocabulary` marca `out_of_vocab` (canonical=None):
    # `predicates_match` NO da credito ni siquiera al MATCH EXACTO de estos
    # predicados (None != None). Es la infra-contabilizacion que corrige
    # `predicate_exact_strict`.
    "ALIAS_OF": {"kind": "out_of_vocab", "vocab_canonical": None},
    "CREATED": {"kind": "out_of_vocab", "vocab_canonical": None},
    "FOUNDED": {"kind": "out_of_vocab", "vocab_canonical": None},
    "GUARDS": {"kind": "out_of_vocab", "vocab_canonical": None},
    "KNOWS": {"kind": "out_of_vocab", "vocab_canonical": None},
    "LEADS": {"kind": "out_of_vocab", "vocab_canonical": None},
    "MARRIED_TO": {"kind": "out_of_vocab", "vocab_canonical": None},
    "MENTOR_OF": {"kind": "out_of_vocab", "vocab_canonical": None},
    "PARENT_OF": {"kind": "out_of_vocab", "vocab_canonical": None},
    "SIBLING_OF": {"kind": "out_of_vocab", "vocab_canonical": None},
    "TRUSTS": {"kind": "out_of_vocab", "vocab_canonical": None},
}

# Nota de simetria pendiente de revision (no altera puntuacion): KNOWS podria
# considerarse simetrico (conocimiento mutuo) pero el GT lo anota dirigido
# (SUBJECT_TO_OBJECT); se respeta el GT y se marca DIRIGIDO.
_SYMMETRY_NOTES: dict[str, str] = {
    "KNOWS": "GT lo anota SUBJECT_TO_OBJECT; simetria social pendiente de revision.",
}


# ---------------------------------------------------------------------------
# API de consulta (NO conectada al camino de puntuacion en B1).
# ---------------------------------------------------------------------------
def get(canonical: str) -> PredicateOntology | None:
    """Devuelve la entrada ontologica del canonico, o None si no existe."""
    return ONTOLOGY.get(normalize_predicate(canonical))


def resolve_alias(raw: str) -> str | None:
    """Resuelve un predicado crudo a su canonico SEGUN ESTA ontologia.

    Independiente de `vocabulary`: no interviene en la puntuacion del benchmark.
    Devuelve el canonico si `raw` es canonico o alias conocido; si no, None.
    """
    norm = normalize_predicate(raw)
    if norm in ONTOLOGY:
        return norm
    return ALIAS_TO_CANONICAL.get(norm)


def is_symmetric(canonical: str) -> bool:
    """True si el canonico es simetrico segun la ontologia."""
    o = get(canonical)
    return bool(o and o.symmetric)


def inverse_of(canonical: str) -> str | None:
    """Devuelve el canonico inverso segun la ontologia, o None."""
    o = get(canonical)
    return o.inverse if o else None


def predicate_exact_strict(pred_a: str, pred_b: str) -> bool:
    """Igualdad canonica ESTRICTA de predicados, SIN resolucion de alias.

    Normaliza SOLO tipograficamente (`contracts.normalize_predicate`: espacios/
    guiones -> `_`, MAYUSCULAS) y compara por igualdad. A diferencia de
    `vocabulary.predicates_match` (alias-aware):

      * NO concede credito por alias que colapsa a otro canonico
        (p.ej. strict(LIVES_IN, LOCATED_IN) = False, pero
        predicates_match(LIVES_IN, LOCATED_IN) = True).
      * SI reconoce el match EXACTO de predicados que `vocabulary` marca
        `out_of_vocab` (p.ej. strict(MENTOR_OF, MENTOR_OF) = True, mientras
        predicates_match(MENTOR_OF, MENTOR_OF) = False porque ambos canonicos
        son None).

    B2 usa esta funcion para NO autoenganarse al medir acierto de predicado.
    NO sustituye al gate ni a `predicates_match` en B1 (metric-neutral).
    """
    return normalize_predicate(pred_a) == normalize_predicate(pred_b)


__all__ = [
    "ONTOLOGY_VERSION",
    "PredicateOntology",
    "ONTOLOGY",
    "CANONICAL_PREDICATES",
    "SYMMETRIC_PREDICATES",
    "ALIAS_TO_CANONICAL",
    "FAMILIES",
    "TEMPORALITY_HINTS",
    "VOCABULARY_DIVERGENCES",
    "get",
    "resolve_alias",
    "is_symmetric",
    "inverse_of",
    "predicate_exact_strict",
]
