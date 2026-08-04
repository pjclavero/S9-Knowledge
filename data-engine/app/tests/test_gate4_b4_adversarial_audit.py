# -*- coding: utf-8 -*-
"""Puerta 4, bloque B4: bateria adversarial del AGENTE-DE-TESTS independiente.

Este fichero NO es del implementador de B4; es la auditoria adversarial que
el programa exige antes de dar el bloque por CONFORME. Cubre tres cosas que
la bateria del propio implementador (`test_gate4_b4_morphology.py`) no fija
como regresion:

1. Equivalencia funcional: las 3 formas literales de "afirmar" que
   `cues.SCOPE_VERBS` tenia ANTES de B4 ("afirma", "afirmaba", "afirmo")
   siguen todas presentes en el conjunto generado por
   `morphology.conjugate_regular_ar("afirmar")`. Si algun dia se retoca la
   tabla de desinencias y se pierde una de esas 3 formas, esto revienta:
   seria una regresion silenciosa exactamente del tipo que la sustitucion
   de un lexico literal por un generador corre el riesgo de introducir.

2. Guarda de cambio ortografico: hoy `REPORTING_LEMMAS_AR` no contiene
   ningun verbo -car/-gar/-zar (los que sufren c->qu / g->gu / z->c), asi
   que la clase de defecto "el paradigma regular genera una forma con
   ortografia incorrecta" esta descartada por AUSENCIA de esos verbos en la
   lista, no porque `conjugate_regular_ar` sepa aplicar la regla
   ortografica (no la aplica: solo concatena raiz + desinencia). Este test
   fija ese hecho como regresion: si alguien anade "buscar"/"pagar"/"cazar"
   sin revisar, hay que saber que las formas de 3a persona generadas aqui
   (presente/preterito/imperfecto/participio) SI son ortograficamente
   correctas incluso para esos verbos -- el cambio c->qu/g->gu/z->c solo
   afecta a la 1a persona del singular del preterito/subjuntivo ("busque",
   "pague", "goce"), que este modulo NUNCA genera (alcance declarado: solo
   3a persona). Se fija con un caso concreto para que quede evidenciado,
   no solo argumentado en prosa.

3. Regresion de cir:e13/e14 (el "candidato morfologico que no lo era",
   documentado en `b4-taxonomia.md`): fija que el cuantificador negativo
   "Nadie" like sujeto de un verbo de reporte compuesto ("ha afirmado")
   sigue sin activar `scope_negation` hoy. Si un futuro bloque cambia
   `scope_negation` para buscar el patron en toda la clausula (no solo
   adyacente), este test debe fallar y forzar una decision consciente
   sobre si "Nadie ha afirmado que X no Y" pasa a leerse como alcance de
   creencia (correcto) o como negacion directa de la relacion (incorrecto,
   el defecto que este mismo caso ilustra).

Hallazgos que este fichero NO puede convertir en test reproducible (se
documentan en el informe del agente en vez de aqui, para no fabricar una
medicion donde no la hay):

  - La cifra "precision 0.5 (2/4 aciertos + 3 variantes sinteticas propias)"
    de la regla de coordinacion candidata (b4-taxonomia.md, categoria C) no
    tiene script, fixture ni test en el repo. Es una afirmacion de prosa sin
    evidencia ejecutable. Ver el informe del agente de tests.
"""
from __future__ import annotations

from knowledge_v3.extraction.cues import SCOPE_VERBS, analyze_raw_text
from knowledge_v3.extraction.morphology import (
    REPORTING_LEMMAS_AR,
    conjugate_regular_ar,
)


# ---------------------------------------------------------------------------
# 1. Equivalencia funcional: nada del lexico literal sustituido se perdio.
# ---------------------------------------------------------------------------

def test_las_formas_literales_de_afirmar_pre_b4_siguen_generadas():
    """Antes de B4, `cues.SCOPE_VERBS` declaraba a mano
    "afirma", "afirmaba", "afirmo" (ver commit anterior a B4). B4 las quito
    del literal y las sustituyo por `morphology.conjugate_regular_ar`. Las 3
    tienen que seguir estando en el conjunto generado: perder una seria una
    regresion silenciosa de cobertura para "afirmar" en singular/preterito/
    imperfecto, el verbo que mas casos de reporte cubre en el corpus.
    """
    formas_literales_pre_b4 = {"afirma", "afirmaba", "afirmo"}
    formas_generadas = set(conjugate_regular_ar("afirmar").all_forms())
    perdidas = formas_literales_pre_b4 - formas_generadas
    assert not perdidas, (
        f"el paradigma regular ya no genera estas formas literales previas: "
        f"{perdidas!r} -- regresion de cobertura respecto al lexico anterior a B4"
    )


def test_todas_las_formas_literales_pre_b4_siguen_en_scope_verbs():
    """Mismo chequeo pero a nivel del lexico final que usa el clasificador
    (`SCOPE_VERBS`), no solo del generador aislado: asegura que la
    sustitucion en `cues.py` no dejo caer nada en el camino.
    """
    formas_literales_pre_b4 = {"afirma", "afirmaba", "afirmo"}
    for forma in formas_literales_pre_b4:
        assert forma in SCOPE_VERBS, (
            f"{forma!r} estaba en el lexico literal anterior a B4 y ya no "
            "esta en SCOPE_VERBS tras la sustitucion por morfologia"
        )


# ---------------------------------------------------------------------------
# 2. Guarda de cambio ortografico c->qu / g->gu / z->c (-car/-gar/-zar).
# ---------------------------------------------------------------------------

def test_ningun_lema_declarado_es_car_gar_zar_sin_revisar():
    """La puerta 6 (B1, docs/v3/44) anadio "verificar" a `REPORTING_LEMMAS_AR`
    (mismo criterio que "confirmar": verbo factivo/de reconocimiento regular
    -AR, necesario para cerrar la familia NEGATION_OF_FACTIVE del corpus de
    generalizacion composicional). Es justo el caso que este test avisaba
    que llegaria: un lema -car. Se reviso el siguiente test
    (`test_conjugar_un_verbo_car_gar_zar_no_declarado_es_correcto_en_3a_persona`,
    que demuestra que el cambio ortografico c->qu SOLO afecta a la 1a
    persona/subjuntivo, ninguno de los cuales genera este modulo) antes de
    aceptar "verificar": la 3a persona ("verifica"/"verifico"/"verificaron")
    no lleva "qu" y no hereda el defecto. Este test ya NO exige la lista
    vacia; exige que la UNICA excepcion -car/-gar/-zar sea la revisada y
    declarada aqui -- si aparece una lema DISTINTA sin pasar por esta
    revision, el test rompe.
    """
    car_gar_zar = tuple(l for l in REPORTING_LEMMAS_AR if l.endswith(("car", "gar", "zar")))
    assert car_gar_zar == ("verificar",), (
        f"lemas -car/-gar/-zar declarados sin verificar el cambio ortografico: {car_gar_zar!r}"
    )
    # La propia excepcion, comprobada aqui otra vez (no solo en el test de
    # abajo): la 3a persona de "verificar" no lleva "qu".
    p = conjugate_regular_ar("verificar")
    assert not any("qu" in forma for forma in p.all_forms())


def test_conjugar_un_verbo_car_gar_zar_no_declarado_es_correcto_en_3a_persona():
    """Documenta (no fija como regla de negocio) que la 3a persona de un
    verbo -car/-gar/-zar SI sale bien con la tabla actual, porque el cambio
    ortografico c->qu/g->gu/z->c solo afecta a la 1a persona del singular
    del preterito ("busque", no "*busco") y a todo el subjuntivo, ninguno de
    los cuales genera este modulo (alcance declarado: solo 3a persona,
    indicativo). Sirve de evidencia de que, SI alguien declarase "buscar" en
    `REPORTING_LEMMAS_AR` manana, no heredaria automaticamente un defecto
    ortografico en las formas que de verdad usa `SCOPE_VERBS` -- el riesgo
    real de anadir un verbo asi sin revisar es CERO en la superficie que
    este modulo expone, contra lo que el docstring del modulo podria sugerir
    a un lector apresurado.
    """
    p = conjugate_regular_ar("buscar")
    assert p.presente == ("busca", "buscan")
    assert p.preterito == ("busco", "buscaron")  # 3a persona: SIN cambio ortografico
    assert p.imperfecto == ("buscaba", "buscaban")
    assert p.participio == "buscado"
    # Ninguna forma generada contiene "qu" (la alternancia que si aplicaria
    # a la 1a persona del singular, "busque", que este modulo no genera).
    assert not any("qu" in forma for forma in p.all_forms())


# ---------------------------------------------------------------------------
# 3. Regresion de cir:e13/e14 (cuantificador negativo "Nadie" como sujeto).
# ---------------------------------------------------------------------------

def test_nadie_ha_afirmado_que_no_activa_scope_negation_hoy():
    """cirro-actas:e13. Texto real del corpus de desarrollo (episode
    `episode:cirro-actas:e13`, familia SCOPE_EMBEDDED). B4 demostro que
    ampliar `SCOPE_VERBS` con la conjugacion completa de "afirmar" NO mueve
    este caso: el sujeto de "ha afirmado" es el cuantificador negativo
    "Nadie", y `scope_negation` exige un "no" INMEDIATAMENTE adyacente al
    verbo de reporte (cues.py:642), que aqui no existe. Se fija como
    regresion: si esto empieza a dar SCOPE_AMBIGUOUS/negated=False sin que
    nadie haya implementado a proposito el reconocimiento de cuantificador
    negativo como sujeto (bloque candidato a B5, segun b4-taxonomia.md),
    hay una via de escape no auditada en `scope_negation` o en `SCOPE_VERBS`.
    """
    texto = "Nadie en la Torre Anemos ha afirmado que Hugo Marlén no dirija la Junta de Astilleros."
    focus_char = texto.find("dirija")
    v = analyze_raw_text(texto, focus_char=focus_char)
    assert v.negated is True
    assert v.negation_kind == "SIMPLE"


def test_selva_ondiz_nego_que_es_scope_no_negacion_directa():
    """cirro-actas:e14 real (episode `episode:cirro-actas:e14`, familia
    SCOPE_EMBEDDED): "Selva Ondiz nego que la Carta de Fletes sea propiedad
    del Consejo de los Vientos." Aviso -- HALLAZGO DE AUDITORIA: pese a lo
    que sugiere la prosa de `b4-taxonomia.md` ("cir:e14 ... mismo patron con
    negó", y mas abajo "e14 es análogo con 'negó'" del mismo texto que e13),
    el texto real de e14 NO tiene "Nadie" como sujeto ni ninguna otra forma
    de cuantificador negativo: es "Selva Ondiz negó que..." con sujeto
    nombrado normal. La taxonomia describe e14 como si tuviera el MISMO
    fenomeno estructural que e13 (cuantificador negativo como sujeto de un
    verbo de reporte); el texto fuente (`cirro-actas/claims.json`,
    `gold_key: "NEG-SCOPE-03:PRIMARY"`) demuestra que no lo tiene. Sea cual
    sea la razon real por la que e14 no esta cubierto en el pipeline E2E, NO
    es la que documenta la taxonomia para este caso. Se fija aqui el
    comportamiento real observado (negated=False, negation_kind='' -- ni
    siquiera SCOPE_AMBIGUOUS, resultado distinto del que la taxonomia
    implica) para que quede como evidencia ejecutable de la discrepancia.
    """
    texto = "Selva Ondiz nego que la Carta de Fletes sea propiedad del Consejo de los Vientos."
    focus_char = texto.find("sea propiedad")
    v = analyze_raw_text(texto, focus_char=focus_char)
    assert v.negated is False
    assert v.negation_kind == ""
