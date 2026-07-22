# -*- coding: utf-8 -*-
"""Resolucion de DIRECCION semantica de una relacion (motor v2, Bloque 3).

Modulo PURO, DETERMINISTA y OFFLINE. Dado un predicado canonico, las posiciones
de las dos menciones del par (sujeto textual = mencion previa; objeto textual =
mencion siguiente, tal y como las canonicaliza `relations.pairs`) y el texto del
segmento, decide la orientacion semantica:

  * ``SUBJECT_TO_OBJECT`` : la mencion SUJETO (la primera del par) es la FUENTE
    semantica del predicado dirigido.
  * ``OBJECT_TO_SUBJECT`` : la FUENTE semantica es la mencion OBJETO (la segunda);
    la lectura textual esta invertida respecto a la semantica (pasiva con agente,
    expresion inversa: "hijo de", "pertenece a", ...).
  * ``UNDIRECTED``        : el predicado es SIMETRICO; el orden de almacenamiento
    canonico NO es direccion semantica.

Orden de prioridad de las senales (spec B3), de mas fiable a menos:

  1. Sujeto gramatical vs objeto (sintaxis heuristica de `relations.syntax`), SOLO
     en clausulas en voz ACTIVA (en pasiva el sujeto gramatical es el paciente, no
     la fuente: la senal se cede al paso 2).
  2. Voz pasiva + agente ("... por X"): el agente introducido por "por" es la
     FUENTE. Se ANCLA a las menciones del par: solo decide si el agente ES una de
     las dos menciones (si es una tercera entidad, se abstiene).
  3. Expresion INVERSA de la ontologia (fuente unica `relations.ontology`): las
     `passive_expressions` de un predicado dirigido codifican la lectura inversa
     ("hijo de" -> el complemento es el PADRE = fuente). El complemento (mencion
     posterior a la expresion) es la fuente.
  4. Simetria: predicado simetrico -> UNDIRECTED (invariante del predicado; se
     comprueba como guarda al principio porque domina a las demas senales).
  5. Preposicion/estructura y expresion ACTIVA: la `active_expressions` situa la
     fuente en la mencion ANTERIOR a la expresion.
  6. Correferencia/pronombre (basico): un pronombre sujeto al inicio de la clausula
     se resuelve a la mencion previa mas cercana del par.
  7. Orden textual = fallback DEBIL: sujeto (primera mencion) como fuente.

NO usa frases calcadas del corpus: se apoya en gramatica GENERAL del espanol
(pasiva perifrastica "ser + participio + por", nucleos relacionales inversos) y en
la ontologia (unica fuente de expresiones activas/pasivas y de la simetria). Mismo
input -> misma salida, mismos scores, sin red, sin disco, sin estado mutable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from relations import ontology, signals
from relations.contracts import Direction

DIRECTION_VERSION = "relation-direction-1.0.0"

# Predicado generico: sin direccion semantica (paridad con el pipeline).
GENERIC_PREDICATE = "RELATED_TO"

# Confianzas ordinales por senal (no son probabilidades calibradas).
CONF_SYMMETRIC = 0.9
CONF_PASSIVE_AGENT = 0.85
CONF_INVERSE_EXPR = 0.8
CONF_GRAMMATICAL = 0.75
CONF_ACTIVE_EXPR = 0.7
CONF_COREF = 0.6
CONF_TEXTUAL = 0.5
CONF_GENERIC = 0.5

# Palabras funcion que pueden intercalarse entre "por"/una expresion y la mencion
# sin romper el anclaje (articulos, preposiciones ligeras). GENERALES del espanol.
_STOP_BETWEEN = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "al", "del", "de", "a", "su", "sus",
})

# Pronombres sujeto para la correferencia basica (paso 6).
_SUBJECT_PRONOUNS = frozenset({
    "el", "ella", "ellos", "ellas", "quien", "quienes", "este", "esta",
    "ese", "esa", "aquel", "aquella",
})

# Terminaciones de participio regular en espanol (deteccion de pasiva lexica).
_PARTICIPLE_SUFFIXES = ("ado", "ada", "ados", "adas", "ido", "ida", "idos", "idas")
# Participios irregulares frecuentes (base sin genero/numero).
_IRREGULAR_PARTICIPLES = frozenset({
    "hecho", "hecha", "dicho", "dicha", "escrito", "escrita", "roto", "rota",
    "puesto", "puesta", "visto", "vista", "abierto", "abierta", "muerto",
    "muerta", "cubierto", "cubierta", "resuelto", "resuelta", "impuesto",
})

# Traduccion 1:1 (misma longitud) para plegar acentos sin desalinear offsets.
_FOLD_MAP = {
    ord("á"): "a", ord("é"): "e", ord("í"): "i", ord("ó"): "o", ord("ú"): "u",
    ord("ü"): "u", ord("ñ"): "n",
    ord("Á"): "a", ord("É"): "e", ord("Í"): "i", ord("Ó"): "o", ord("Ú"): "u",
    ord("Ü"): "u", ord("Ñ"): "n",
}


def _fold(text: str) -> str:
    """Minusculas + acentos plegados PRESERVANDO longitud (offsets alineados)."""
    return text.lower().translate(_FOLD_MAP)


@dataclass(frozen=True)
class DirectionResult:
    """Direccion resuelta + confianza + traza de la regla que decidio."""

    direction: Direction
    confidence: float
    rationale: str


def _window_bounds(seg_text: str, s_start: int, s_end: int,
                   o_start: int, o_end: int) -> tuple[int, int]:
    """Limites [lo, hi) de la(s) frase(s) que contienen ambas menciones.

    Reutiliza `signals._sentence_bounds` (misma frontera de frase que el resto del
    subsistema): no se duplica el criterio.
    """
    s_ini, s_fin = signals._sentence_bounds(seg_text, s_start, s_end)
    o_ini, o_fin = signals._sentence_bounds(seg_text, o_start, o_end)
    return min(s_ini, o_ini), max(s_fin, o_fin)


def _looks_like_participle(word: str) -> bool:
    w = word.strip(".,;:()[]\"'")
    if not w:
        return False
    if w in _IRREGULAR_PARTICIPLES:
        return True
    return any(w.endswith(suf) for suf in _PARTICIPLE_SUFFIXES) and len(w) >= 5


def _mention_immediately_after(folded: str, pos: int,
                               mentions: tuple) -> Optional[str]:
    """Rol ("subject"/"object") de la mencion del par que sigue INMEDIATAMENTE a
    `pos`, admitiendo solo palabras funcion intercaladas. None si la siguiente
    entidad no es ninguna de las dos menciones del par (agente de tercero).
    """
    after = [(start, role) for (start, end, role) in mentions if start >= pos]
    if not after:
        return None
    start, role = min(after, key=lambda m: m[0])
    gap = folded[pos:start]
    for tok in gap.replace(",", " ").split():
        if tok not in _STOP_BETWEEN:
            return None
    return role


def _passive_agent_source(folded: str, lo: int, hi: int,
                          mentions: tuple, passive_hint: bool) -> Optional[str]:
    """Paso 2: agente de una pasiva perifrastica ("... por AGENTE").

    Solo decide si el agente coincide con una mencion del par. Requiere evidencia
    de pasiva: participio inmediatamente anterior a "por" o `passive_hint` de la
    sintaxis. Devuelve el rol FUENTE (el agente) o None.
    """
    idx = lo
    while True:
        p = folded.find(" por ", idx, hi)
        if p == -1:
            break
        por_end = p + len(" por ")
        # Evidencia de pasiva: participio como ultima palabra antes de "por".
        prefix = folded[lo:p].split()
        is_passive = passive_hint or (prefix and _looks_like_participle(prefix[-1]))
        if is_passive:
            role = _mention_immediately_after(folded, por_end, mentions)
            if role is not None:
                return role
        idx = p + 1
    return None


def _find_expression(folded: str, lo: int, hi: int,
                     expressions: tuple) -> Optional[tuple]:
    """Primera aparicion (start, end) de cualquiera de `expressions` en [lo, hi)."""
    best: Optional[tuple] = None
    for expr in expressions:
        if not expr:
            continue
        pos = folded.find(_fold(expr), lo, hi)
        if pos != -1 and (best is None or pos < best[0]):
            best = (pos, pos + len(expr))
    return best


def _lexical_source(folded: str, lo: int, hi: int, mentions: tuple,
                    ont) -> Optional[tuple]:
    """Pasos 3 y 5: expresion INVERSA (pasiva) o ACTIVA de la ontologia.

    * Expresion pasiva/inversa presente y NO hay activa -> la fuente es la mencion
      POSTERIOR a la expresion (el complemento; p.ej. "hijo de Aldric" -> Aldric).
    * Expresion activa presente y NO hay pasiva -> la fuente es la mencion ANTERIOR
      a la expresion (p.ej. "Aldric, padre de Draven" -> Aldric).
    * Ambas o ninguna -> se abstiene (None): senal ambigua, la decide otro paso.

    Devuelve (role, confidence, rationale) o None.
    """
    active_hit = _find_expression(folded, lo, hi, tuple(ont.active_expressions))
    passive_hit = _find_expression(folded, lo, hi, tuple(ont.passive_expressions))

    if passive_hit and not active_hit:
        role = _mention_after_span(mentions, passive_hit[1])
        if role is not None:
            return role, CONF_INVERSE_EXPR, "inverse_expression"
    if active_hit and not passive_hit:
        role = _mention_before_span(mentions, active_hit[0])
        if role is not None:
            return role, CONF_ACTIVE_EXPR, "active_expression"
    return None


def _mention_after_span(mentions: tuple, pos: int) -> Optional[str]:
    after = [(start, role) for (start, end, role) in mentions if start >= pos]
    if not after:
        return None
    return min(after, key=lambda m: m[0])[1]


def _mention_before_span(mentions: tuple, pos: int) -> Optional[str]:
    before = [(end, role) for (start, end, role) in mentions if end <= pos]
    if not before:
        return None
    return max(before, key=lambda m: m[0])[1]


def _sentence_for(syntax: Any, s_start: int, o_start: int) -> Optional[Any]:
    """Frase de la sintaxis que cubre ambas menciones (o None)."""
    if syntax is None:
        return None
    sents = getattr(syntax, "sentences", ()) or ()
    lo = min(s_start, o_start)
    hi = max(s_start, o_start)
    for sent in sents:
        if sent.start <= lo and hi < sent.end:
            return sent
    return None


def _token_span(sent: Any, token_index: Optional[int]) -> Optional[tuple]:
    if token_index is None:
        return None
    for tok in getattr(sent, "tokens", ()) or ():
        if tok.index == token_index:
            return (tok.start, tok.end)
    return None


def _overlaps_role(span: Optional[tuple], mentions: tuple) -> Optional[str]:
    """Rol de la mencion que solapa `span` (o None)."""
    if span is None:
        return None
    ts, te = span
    for (start, end, role) in mentions:
        if ts < end and start < te:
            return role
    return None


def _grammatical_source(sent: Any, mentions: tuple) -> Optional[tuple]:
    """Paso 1: sujeto/objeto gramatical en voz ACTIVA (abstiene en pasiva)."""
    if sent is None or getattr(sent, "passive", False):
        return None
    subj_role = _overlaps_role(_token_span(sent, sent.subject_index), mentions)
    obj_role = _overlaps_role(_token_span(sent, sent.object_index), mentions)
    if subj_role and obj_role and subj_role != obj_role:
        return subj_role, CONF_GRAMMATICAL, "grammatical_subject"
    return None


def _coref_source(sent: Any, folded: str, mentions: tuple) -> Optional[tuple]:
    """Paso 6: pronombre sujeto al inicio -> mencion previa mas cercana del par.

    Correferencia MINIMA: si el sujeto gramatical es un pronombre personal, la
    fuente es la ultima mencion del par que lo precede en el texto.
    """
    if sent is None:
        return None
    subj_span = _token_span(sent, sent.subject_index)
    if subj_span is None:
        return None
    subj_word = folded[subj_span[0]:subj_span[1]].strip()
    if subj_word not in _SUBJECT_PRONOUNS:
        return None
    role = _mention_before_span(mentions, subj_span[0])
    if role is not None:
        return role, CONF_COREF, "coref_pronoun"
    return None


def _direction_from_role(role: str) -> Direction:
    return Direction.SUBJECT_TO_OBJECT if role == "subject" else Direction.OBJECT_TO_SUBJECT


def resolve_direction(predicate: str,
                      subject_start: int, subject_end: int,
                      object_start: int, object_end: int,
                      seg_text: str,
                      syntax: Any = None) -> DirectionResult:
    """Resuelve la direccion semantica de un par (funcion pura, determinista).

    `subject_*` es la mencion PREVIA del par (sujeto textual) y `object_*` la
    siguiente, como las entrega `relations.pairs`. `syntax` es un
    `SyntaxAnalysis` opcional (duck-typed): si falta, se resuelve solo con lexico y
    orden textual, sin romper.
    """
    # Paso 4 (guarda): simetria domina; el orden de almacenamiento no es direccion.
    if ontology.is_symmetric(predicate):
        return DirectionResult(Direction.UNDIRECTED, CONF_SYMMETRIC, "symmetric_undirected")

    # Predicado generico o desconocido: sin direccion semantica (paridad pipeline).
    ont = ontology.get(predicate)
    if predicate == GENERIC_PREDICATE or ont is None:
        return DirectionResult(Direction.UNDIRECTED, CONF_GENERIC, "generic_undirected")

    lo, hi = _window_bounds(seg_text, subject_start, subject_end,
                            object_start, object_end)
    folded = _fold(seg_text)
    # (start, end, role) de cada mencion del par, en el marco absoluto del segmento.
    mentions = (
        (subject_start, subject_end, "subject"),
        (object_start, object_end, "object"),
    )
    sent = _sentence_for(syntax, subject_start, object_start)
    passive_hint = bool(getattr(sent, "passive", False)) if sent is not None else False

    # Paso 1: sujeto/objeto gramatical (voz activa).
    gram = _grammatical_source(sent, mentions)
    if gram is not None:
        role, conf, rat = gram
        return DirectionResult(_direction_from_role(role), conf, rat)

    # Paso 2: pasiva + agente ("... por AGENTE"), anclado a las menciones del par.
    agent_role = _passive_agent_source(folded, lo, hi, mentions, passive_hint)
    if agent_role is not None:
        return DirectionResult(_direction_from_role(agent_role),
                               CONF_PASSIVE_AGENT, "passive_agent")

    # Pasos 3 y 5: expresion inversa (pasiva) o activa de la ontologia.
    lex = _lexical_source(folded, lo, hi, mentions, ont)
    if lex is not None:
        role, conf, rat = lex
        return DirectionResult(_direction_from_role(role), conf, rat)

    # Paso 6: correferencia/pronombre basico.
    coref = _coref_source(sent, folded, mentions)
    if coref is not None:
        role, conf, rat = coref
        return DirectionResult(_direction_from_role(role), conf, rat)

    # Paso 7: fallback DEBIL por orden textual (sujeto = fuente).
    return DirectionResult(Direction.SUBJECT_TO_OBJECT, CONF_TEXTUAL, "textual_order")


def direction_for_pair(predicate: str, pair: Any, seg_text: str,
                       syntax: Any = None) -> DirectionResult:
    """Adaptador para el pipeline: extrae offsets del `CandidatePair` y delega.

    NO muta nada. `pair` expone subject_start/subject_end/object_start/object_end.
    """
    return resolve_direction(
        predicate,
        pair.subject_start, pair.subject_end,
        pair.object_start, pair.object_end,
        seg_text,
        syntax=syntax,
    )


__all__ = [
    "DIRECTION_VERSION",
    "GENERIC_PREDICATE",
    "DirectionResult",
    "resolve_direction",
    "direction_for_pair",
    "CONF_SYMMETRIC",
    "CONF_PASSIVE_AGENT",
    "CONF_INVERSE_EXPR",
    "CONF_GRAMMATICAL",
    "CONF_ACTIVE_EXPR",
    "CONF_COREF",
    "CONF_TEXTUAL",
]
