# -*- coding: utf-8 -*-
"""Marcas de contexto: negacion, epistemicidad y NO-FACTIVIDAD.

Modulo comun al extractor determinista y a la frontera de modelos. Existe por
una razon concreta y demostrada: *una cita puede existir literalmente en el
texto y aun asi no decir lo que la propuesta afirma*.

    texto real : "Kael no sirve a la Orden del Alba"
    cita       : "sirve a la Orden del Alba"     <- existe, es literal
    propuesta  : SERVES(Kael, Orden), negated=False

La cita pasaba el anclaje porque el anclaje solo comprueba EXISTENCIA. Lo que
falta es comprobar el SENTIDO: que el contexto real que rodea al ancla no
invierta ni suspenda lo que se esta afirmando. Eso es lo que hace
`analyze_context`.

Tres ejes, tres consecuencias distintas:

- **negacion** ("no", "nunca", "jamas"...): si el contexto niega y la propuesta
  dice `negated=False`, la propuesta esta afirmando lo contrario de la fuente.
  No se corrige: se ABSTIENE. Corregir seria decidir, y decidir es del motor;
- **no-factividad** (condicional, interrogativa, "es falso que", "nadie cree
  que", "afirmo falsamente", "salvo que"): el texto no esta afirmando el hecho,
  lo esta suponiendo, preguntando o negando su verdad. Nunca puede salir
  `ASSERTED` con `review_required=False`;
- **epistemicidad** (rumor, hipotesis, intencion): degrada la pista epistemica y
  obliga a revision, pero el hecho sigue propuesto.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .text import Token, find_phrase, phrase_tokens, tokenize

#: Marcas de negacion. Se comparan sobre la forma normalizada.
NEGATION_CUES: tuple[str, ...] = ("no", "nunca", "jamas", "tampoco", "ni")

#: Cuantos tokens antes de la frase de relacion se busca la negacion en el
#: extractor determinista. Mas lejos, la negacion suele afectar a otra cosa.
NEGATION_WINDOW = 3

#: Marcas epistemicas -> pista del contrato. Un extractor no sabe si algo es
#: cierto; si sabe que el texto lo presenta como rumor, hipotesis o intencion.
EPISTEMIC_CUES: tuple[tuple[str, str], ...] = (
    ("se rumorea", "RUMORED"),
    ("dicen que", "RUMORED"),
    ("se dice que", "RUMORED"),
    ("segun cuentan", "RUMORED"),
    ("supuestamente", "RUMORED"),
    ("al parecer", "RUMORED"),
    ("quiza", "HYPOTHETICAL"),
    ("quizas", "HYPOTHETICAL"),
    ("tal vez", "HYPOTHETICAL"),
    ("podria", "HYPOTHETICAL"),
    ("si acaso", "HYPOTHETICAL"),
    ("planea", "INTENDED"),
    ("pretende", "INTENDED"),
    ("tiene intencion de", "INTENDED"),
    ("jurara", "INTENDED"),
)

#: Frases que NIEGAN LA VERDAD del hecho o lo atribuyen a un error. No es que el
#: hecho sea dudoso: es que el texto dice que NO es asi. Un claim aqui no puede
#: salir afirmado de ninguna manera.
FALSITY_PHRASES: tuple[str, ...] = (
    "es falso que",
    "es mentira que",
    "no es cierto que",
    "no es verdad que",
    "nadie cree que",
    "nadie creia que",
    "afirmo falsamente",
    "aseguro falsamente",
    "falsamente",
    "se equivocaba al afirmar que",
)

#: Frases que SUSPENDEN el hecho: lo ponen bajo condicion o excepcion. El hecho
#: no se afirma, se hipotetiza.
CONDITIONAL_PHRASES: tuple[str, ...] = (
    "salvo que",
    "a menos que",
    "en caso de que",
    "siempre que",
    "de haber",
    "suponiendo que",
)

#: "si" solo cuenta como condicional SIN tilde y como palabra suelta: "si" y
#: "si" (afirmacion) son la misma cadena una vez normalizada, y confundirlas
#: convertiria cualquier "si" en una hipotesis.
CONDITIONAL_SI = "si"

#: Signos que delatan una interrogativa. Una pregunta no afirma nada.
INTERROGATIVE_MARKS = ("¿", "?")

#: Codigos de razon (estables, `^[A-Z][A-Z0-9_]{0,63}$`).
CODE_NEGATION_MISMATCH = "NEGATION_CONTEXT_MISMATCH"
CODE_NON_FACTIVE = "NON_FACTIVE_CONTEXT"
CODE_FALSITY = "FALSITY_CONTEXT"
CODE_CONDITIONAL = "CONDITIONAL_CONTEXT"
CODE_INTERROGATIVE = "INTERROGATIVE_CONTEXT"


@dataclass(frozen=True)
class ContextVerdict:
    """Lo que el contexto REAL dice sobre un hecho propuesto."""

    negated: bool = False
    hint: str = "ASSERTED"
    cues: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @property
    def non_factive(self) -> bool:
        """El texto no esta afirmando el hecho (lo supone, lo pregunta o lo niega)."""
        return bool(
            {CODE_FALSITY, CODE_CONDITIONAL, CODE_INTERROGATIVE} & set(self.reason_codes)
        )

    @property
    def blocks_assertion(self) -> bool:
        return self.negated or self.non_factive


def _has_phrase(tokens: Sequence[Token], phrase: str, lo: int, hi: int) -> bool:
    needle = phrase_tokens(phrase)
    return bool(needle) and bool(find_phrase(tokens, needle, lo=lo, hi=hi))


def analyze_context(
    text: str,
    tokens: Sequence[Token],
    *,
    lo: int = 0,
    hi: Optional[int] = None,
    focus: Optional[int] = None,
    negation_window: Optional[int] = None,
) -> ContextVerdict:
    """Analiza el contexto `[lo, hi)` de tokens alrededor de un hecho.

    `focus` es el token donde empieza lo afirmado (la frase de relacion o el
    ancla de la cita). La negacion se busca ANTES de ese punto: la que viene
    despues suele negar otra cosa. `negation_window` acota esa busqueda; sin
    ella se mira todo el contexto previo, que es lo correcto cuando se esta
    verificando la cita de un modelo (ahi la prudencia gana a la precision).
    """
    hi = len(tokens) if hi is None else hi
    focus = hi if focus is None else focus
    reasons: list[str] = []
    cues: list[str] = []

    neg_lo = lo if negation_window is None else max(lo, focus - negation_window)
    negated = any(tokens[i].norm in NEGATION_CUES for i in range(neg_lo, min(focus, hi)))

    for phrase in FALSITY_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            if CODE_FALSITY not in reasons:
                reasons.append(CODE_FALSITY)

    for phrase in CONDITIONAL_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            if CODE_CONDITIONAL not in reasons:
                reasons.append(CODE_CONDITIONAL)

    # "si" condicional: sin tilde y antes de lo afirmado.
    for i in range(lo, min(focus, hi)):
        if tokens[i].text.lower() == CONDITIONAL_SI:
            cues.append(CONDITIONAL_SI)
            if CODE_CONDITIONAL not in reasons:
                reasons.append(CODE_CONDITIONAL)
            break

    if any(mark in (text or "") for mark in INTERROGATIVE_MARKS):
        reasons.append(CODE_INTERROGATIVE)

    hint = "ASSERTED"
    for cue, mapped in EPISTEMIC_CUES:
        if _has_phrase(tokens, cue, lo, hi):
            cues.append(cue)
            if hint == "ASSERTED":
                hint = mapped

    if CODE_CONDITIONAL in reasons and hint == "ASSERTED":
        hint = "HYPOTHETICAL"
    if CODE_FALSITY in reasons or CODE_INTERROGATIVE in reasons:
        hint = "UNKNOWN"

    return ContextVerdict(
        negated=negated,
        hint=hint,
        cues=tuple(dict.fromkeys(cues)),
        reason_codes=tuple(reasons),
    )


def analyze_raw_text(text: str, *, focus_char: Optional[int] = None) -> ContextVerdict:
    """Version que tokeniza por su cuenta. Para contextos sueltos (fragmentos)."""
    tokens = tokenize(text or "")
    focus = len(tokens)
    if focus_char is not None:
        previos = [t.index for t in tokens if t.end <= focus_char]
        focus = (previos[-1] + 1) if previos else 0
    return analyze_context(text or "", tokens, focus=focus)


__all__ = [
    "CODE_CONDITIONAL",
    "CODE_FALSITY",
    "CODE_INTERROGATIVE",
    "CODE_NEGATION_MISMATCH",
    "CODE_NON_FACTIVE",
    "CONDITIONAL_PHRASES",
    "EPISTEMIC_CUES",
    "FALSITY_PHRASES",
    "NEGATION_CUES",
    "NEGATION_WINDOW",
    "ContextVerdict",
    "analyze_context",
    "analyze_raw_text",
]
