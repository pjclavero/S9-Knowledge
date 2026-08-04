# -*- coding: utf-8 -*-
"""Puerta 4, bloque B4: conjugador morfologico REGULAR para verbos -AR.

Existe por un mandato explicito del programa: `SCOPE_VERBS` (en `cues.py`) es
un lexico CERRADO de formas conjugadas escritas a mano, verbo a verbo. Eso
funciona para los pocos verbos irregulares que ya cubre ("decir" -> "dijo",
"saber" -> "supo"), pero no escala: cada verbo de reporte nuevo ("declarar",
"sostener", "admitir"...) obligaria a teclear su paradigma entero a ojo, y
tarde o temprano alguien copiaria solo la forma que aparecia en un caso de
corpus -- exactamente el defecto P0 que B2 tuvo que corregir dos veces
("ha dejado atras").

Este modulo generaliza la parte de ese lexico que SI es mecanica: los verbos
regulares de la primera conjugacion (-AR) siguen una tabla de desinencias
fija. Declarar el LEMA basta; las formas salen de la tabla, no de la memoria
de ningun caso de corpus. Los verbos irregulares (decir, saber, creer, ...)
se quedan donde estaban, en `cues.SCOPE_VERBS`, como paradigma irregular
declarado explicitamente -- generarlos "por analogia" seria inventar
morfologia que el espanol no tiene, y esa es justo la clase de heuristica
que el encargo prohibe (la nota que prohibe "-ria" como marca de condicional
por sufijo es un caso particular de esta regla general: ninguna desinencia
suelta vale como prueba sin saber a que paradigma pertenece el verbo).

Alcance deliberadamente estrecho: SOLO se generan las personas que un verbo
de REPORTE necesita para que `classify_negation`/`scope_negation` reconozcan
"no <verbo> que ..." o "<verbo> que ...": 3a persona singular y plural, en
presente, preterito indefinido e imperfecto de indicativo, mas las formas
compuestas de perfecto ("ha/han/habia/habian <participio>"). No se generan
subjuntivo, imperativo ni 1a/2a persona: no son las formas en las que un
verbo de reporte introduce una subordinada factual de tercero, que es el
unico fenomeno que este modulo ataca.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Desinencias regulares de la primera conjugacion (-AR), 3a persona.
#: Fuente: paradigma de "hablar" en la RAE (Nueva gramatica de la lengua
#: espanola, cap. de morfologia verbal). No son cifras del corpus.
_AR_PRESENTE = ("a", "an")
_AR_PRETERITO = ("o", "aron")
_AR_IMPERFECTO = ("aba", "aban")
_AR_PARTICIPIO = "ado"
_HABER_PERFECTO = ("ha", "han")
_HABER_PLUSCUAMPERFECTO = ("habia", "habian")


@dataclass(frozen=True)
class VerbParadigm:
    """Formas 3a persona (singular, plural) de un verbo regular -AR."""

    lemma: str
    presente: tuple[str, str]
    preterito: tuple[str, str]
    imperfecto: tuple[str, str]
    participio: str
    perfecto: tuple[str, str]
    pluscuamperfecto: tuple[str, str]

    def all_forms(self) -> tuple[str, ...]:
        """Todas las formas simples y compuestas, sin duplicados, orden estable."""
        formas = [
            *self.presente,
            *self.preterito,
            *self.imperfecto,
            f"{self.perfecto[0]} {self.participio}",
            f"{self.perfecto[1]} {self.participio}",
            f"{self.pluscuamperfecto[0]} {self.participio}",
            f"{self.pluscuamperfecto[1]} {self.participio}",
        ]
        vistas: list[str] = []
        for f in formas:
            if f not in vistas:
                vistas.append(f)
        return tuple(vistas)


def conjugate_regular_ar(lemma: str) -> VerbParadigm:
    """Conjuga un verbo REGULAR de la 1a conjugacion (-AR) en 3a persona.

    No valida que `lemma` sea realmente regular: esa comprobacion es
    responsabilidad de quien declara `REPORTING_LEMMAS_AR` (ver mas abajo),
    exactamente igual que `DEJAR_FORMS`/`CESAR_FORMS` en `cues.py` se declaran
    a mano porque son las excepciones que la tabla no cubre.
    """
    if not lemma.endswith("ar"):
        raise ValueError(f"'{lemma}' no es un lema de la 1a conjugacion (-ar)")
    raiz = lemma[:-2]
    return VerbParadigm(
        lemma=lemma,
        presente=tuple(raiz + d for d in _AR_PRESENTE),  # type: ignore[arg-type]
        preterito=tuple(raiz + d for d in _AR_PRETERITO),  # type: ignore[arg-type]
        imperfecto=tuple(raiz + d for d in _AR_IMPERFECTO),  # type: ignore[arg-type]
        participio=raiz + _AR_PARTICIPIO,
        perfecto=_HABER_PERFECTO,
        pluscuamperfecto=_HABER_PLUSCUAMPERFECTO,
    )


#: Lemas de verbos de REPORTE/ACTITUD regulares -AR que se suman a
#: `cues.SCOPE_VERBS`. Declarados por LEMA, no por forma: la lista crece sin
#: que nadie tenga que escribir "declaro"/"declararon"/"declaraba"/... a mano.
#: Cada lema se comprobo manualmente regular (sin diptongacion, sin cambio
#: ortografico irregular más alla de los ya cubiertos por la tabla) antes de
#: declararlo aqui; ninguno se tomo de una frase del corpus de desarrollo o
#: generalizacion -- son el vocabulario cerrado de verbos de reporte que
#: cualquier diccionario de espanol general lista como tales.
REPORTING_LEMMAS_AR: tuple[str, ...] = (
    "afirmar",
    "declarar",
    "asegurar",
    "confirmar",
    "negar_IRREGULAR_SKIP",  # "negar" diptonga (niega/niego): no es regular, ver abajo
)

# "negar" es -AR pero diptonga (e -> ie) en presente ("niega", no "*nega"); el
# preterito e imperfecto SI son regulares ("nego", "negaba"). Declararlo en la
# tabla regular produciria "*nega"/"*negan", formas que no existen en espanol:
# eso seria inventar morfologia, la heuristica que el encargo prohibe. Se
# quita de `REPORTING_LEMMAS_AR` y se declara aparte, a mano, solo con sus
# formas REALES (igual que "decir"/"saber" en `cues.py`).
REPORTING_LEMMAS_AR = tuple(l for l in REPORTING_LEMMAS_AR if not l.endswith("_SKIP"))

NEGAR_FORMS: tuple[str, ...] = (
    "niega", "niegan",
    "nego", "negaron",
    "negaba", "negaban",
    "ha negado", "han negado",
    "habia negado", "habian negado",
)


def reporting_verb_forms() -> tuple[str, ...]:
    """Todas las formas de reporte generadas por morfologia (regulares + irregulares declaradas).

    Se usa para EXTENDER `cues.SCOPE_VERBS`, nunca para sustituirlo: los verbos
    irregulares que ya vivian alli (creer, decir, saber, pensar, ...) siguen
    siendo responsabilidad de `cues.py`.
    """
    formas: list[str] = []
    for lemma in REPORTING_LEMMAS_AR:
        for forma in conjugate_regular_ar(lemma).all_forms():
            if forma not in formas:
                formas.append(forma)
    for forma in NEGAR_FORMS:
        if forma not in formas:
            formas.append(forma)
    return tuple(formas)


__all__ = [
    "NEGAR_FORMS",
    "REPORTING_LEMMAS_AR",
    "VerbParadigm",
    "conjugate_regular_ar",
    "reporting_verb_forms",
]
