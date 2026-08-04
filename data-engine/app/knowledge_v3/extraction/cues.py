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
  que", "afirmo falsamente", "salvo que", y el marco de FICCION DENTRO DE LA
  FICCION: "en la farsa que...", "en el serial que..."): el texto no esta
  afirmando el hecho, lo esta suponiendo, preguntando, representando o negando
  su verdad. Nunca puede salir `ASSERTED` con `review_required=False`;
- **epistemicidad** (rumor, hipotesis, intencion): degrada la pista epistemica y
  obliga a revision, pero el hecho sigue propuesto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from .morphology import conjugate_regular_ar, reporting_verb_forms
from .factivity import (
    FactivityAction,
    FactivityResult,
    FactivitySignals,
    classify_factivity,
)
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
    ("corre el rumor de que", "RUMORED"),
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
    ("cabe suponer que", "HYPOTHETICAL"),
    ("barajan la posibilidad de que", "HYPOTHETICAL"),
    ("es probable que", "HYPOTHETICAL"),
    ("con la hipotesis de que", "HYPOTHETICAL"),
    ("podria ser que", "HYPOTHETICAL"),
    ("se sospecha que", "HYPOTHETICAL"),
    ("nada impide pensar que", "HYPOTHETICAL"),
    ("supongamos", "HYPOTHETICAL"),
    ("todo apunta a que", "HYPOTHETICAL"),
    ("planea", "INTENDED"),
    ("pretende", "INTENDED"),
    ("tiene intencion de", "INTENDED"),
    ("jurara", "INTENDED"),
)

# Construcciones productivas de reporte con un sintagma nominal interpuesto.
# El hueco esta acotado para no convertir cualquier "dicen ... que" remoto en
# rumor ni atravesar una clausula completa.
EPISTEMIC_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\bdicen (?:el|la|los|las) (?:\w+ ){0,6}que\b"),
        "dicen <fuente> que",
        "RUMORED",
    ),
    (
        re.compile(
            r"\bllego a oidos (?:de|del|de la|de los|de las) (?:\w+ ){0,3}que\b"
        ),
        "llego a oidos de <fuente> que",
        "RUMORED",
    ),
    (
        re.compile(r"\bcorre por (?:el|la|los|las) (?:\w+ ){0,3}que\b"),
        "corre por <lugar> que",
        "RUMORED",
    ),
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
    "mintio",
    "fingio",
    "se hacia pasar por",
    "desmiente",
    "desmienten",
    "nunca fue cierto que",
    "se falsifico",
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
    "a no ser que",
    "solo si",
    "puestos a imaginar",
)

#: Bloque B1 (puerta 6): "mientras" es AMBIGUO entre conjuncion TEMPORAL
#: ("mientras cenaban, llego X" -- indicativo, no suspende nada) y
#: CONDICIONAL ("mientras Toturi no rompa la tregua..." -- subjuntivo, "a
#: menos que"). No se puede distinguir por texto llano sin un analizador
#: morfologico de modo verbal completo, pero SI hay una regla gramatical
#: cerrada y no ad-hoc que cubre el caso que produce ambiguedad real: en
#: espanol, "mientras no" + verbo SIEMPRE toma subjuntivo (es la
#: construccion "a menos que"/"hasta que no" -- nunca temporal-indicativo).
#: `(?:\w+ ){0,4}` deja hueco para el sujeto interpuesto ("mientras Toturi
#: no rompa"). Un "mientras" SIN "no" cercano se queda fuera a proposito
#: (sigue leyendose como conjuncion de clausula en `CLAUSE_CONJUNCTIONS`,
#: nunca como condicional): forzar esa lectura convertiria un "mientras"
#: temporal en condicional, que es exactamente el falso positivo que este
#: bloque tiene prohibido introducir.
CONDITIONAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bmientras (?:\w+ ){0,4}no\b"), "mientras <sujeto> no"),
)

# Preguntas indirectas sin signos de interrogacion.
INTERROGATIVE_PHRASES: tuple[str, ...] = (
    "pregunto",
    "nadie supo responder",
    "me pregunto si",
    "interrogatorio",
)

#: Marcos de FICCION DENTRO DE LA FICCION: el texto cuenta lo que pasa en una
#: obra, farsa, serial, leyenda o relato que existe DENTRO del mundo narrado.
#: Las entidades son reales; lo que se cuenta de ellas ahi, no. Medido en dev:
#: es la trampa que un modelo grande pisa con mas naturalidad, porque la frase
#: tiene sujeto, verbo y objeto perfectamente formados.
FICTION_PHRASES: tuple[str, ...] = (
    "en la farsa",
    "en la obra",
    "en la representacion",
    "en la comedia",
    "en el drama",
    "en el serial",
    "en el relato",
    "en el cuento",
    "en la cancion",
    "en la balada",
    "en el poema",
    "en la novela",
    "en la leyenda",
    "en el mito",
    "segun la leyenda",
    "cuenta la leyenda",
    "los titiriteros representaron",
    "lo invento todo",
    "cuenta la balada",
    "sono que",
    "en el juego de cartas",
    "escenifican una version",
    "poema apocrifo",
    "en la pesadilla",
    "solo un arquetipo",
)

#: Frases DEONTICAS: prohiben u ordenan. Una prohibicion no dice que algo NO
#: ocurra, dice que no DEBE ocurrir. No es un hecho negativo del mundo.
DEONTIC_PHRASES: tuple[str, ...] = (
    "no debe",
    "no deben",
    "no debia",
    "no debera",
    "no podra",
    "no podran",
    "queda prohibido",
    "esta prohibido",
    "se prohibe",
    "no se permite",
    "no permitas",
    "ordeno que",
    "prohibido",
    "se ruega",
    "no jures",
    "debera",
)

#: Frases de DESEO. "Ojala Kael sirviera a la Orden" no afirma nada del mundo.
DESIRE_PHRASES: tuple[str, ...] = (
    "ojala",
    "quisiera que",
    "desearia que",
    "espera que",
    "esperaba que",
    "quiere que",
    "queria que",
    "desea que",
    "deseaba que",
    "anhela que",
    "suenan con",
    "le gustaria",
    "pluguiera",
    "quisiera",
)

# --------------------------------------------------------------------------
# NEGACION: tipos, alcance y clausula
# --------------------------------------------------------------------------
#: Una afirmacion negativa es INFORMACION. "relacion negada" no es lo mismo que
#: "ausencia de relacion" ni que "relacion positiva", y cada tipo de negacion
#: significa algo distinto para el motor. El extractor NO decide: detecta, marca
#: el tipo y conserva la cita.
NEGATION_KIND_SIMPLE = "SIMPLE"
NEGATION_KIND_NEVER = "NEVER"
NEGATION_KIND_CESSATION = "CESSATION"
NEGATION_KIND_NOT_YET = "NOT_YET"
#: El texto niega, pero no se sabe QUE niega (alcance sobre otro verbo, doble
#: negacion). Nunca se convierte en negacion mecanica: se abstiene o se revisa.
NEGATION_KIND_SCOPE_AMBIGUOUS = "SCOPE_AMBIGUOUS"

NEGATION_KINDS: tuple[str, ...] = (
    NEGATION_KIND_SIMPLE,
    NEGATION_KIND_NEVER,
    NEGATION_KIND_CESSATION,
    NEGATION_KIND_NOT_YET,
    NEGATION_KIND_SCOPE_AMBIGUOUS,
)

#: Negacion ABSOLUTA. Ligada al contexto temporal de la fuente: `NEVER` no
#: autoriza a inventar un intervalo infinito.
NEVER_CUES: tuple[str, ...] = ("nunca", "jamas")

#: "todavia no" NO es cesacion: no demuestra que antes lo fuera. Va antes que la
#: cesacion en la precedencia justamente para que "todavia no" no se lea como
#: "ya no".
NOT_YET_PHRASES: tuple[str, ...] = (
    "todavia no",
    "aun no",
    "no ... todavia",
)

#: CESACION: hubo relacion y termina. Ojo: la mitad de estas frases NO llevan
#: ninguna marca de negacion ("dejo de liderar", "abandono el clan"), asi que la
#: cesacion no se puede detectar mirando solo `NEGATION_CUES`.
#: Formas conjugadas del auxiliar `dejar` que abren una PERIFRASIS de cesacion.
#: Se declaran como paradigma verbal, no como frases sueltas: las perifrasis
#: `<dejar> de <infinitivo>` y `<dejar> atras <complemento>` se GENERAN a partir
#: de aqui (ver `CESSATION_PERIPHRASIS_DE` / `_ATRAS`). Escribir a mano solo la
#: conjugacion que aparecia en un caso de corpus es memorizar ese caso, no
#: describir la lengua: ese fue el defecto P0 de B2 ("ha dejado atras").
DEJAR_FORMS: tuple[str, ...] = (
    "deja", "dejan",
    "dejo", "dejaron",
    "dejaba", "dejaban",
    "dejara", "dejaran",
    "dejase", "dejasen",
    "ha dejado", "han dejado",
    "habia dejado", "habian dejado",
    "esta dejando", "estan dejando",
)

#: Mismo criterio para `cesar`.
CESAR_FORMS: tuple[str, ...] = (
    "cesa", "cesan", "ceso", "cesaron", "cesaba", "cesaban",
    "ha cesado", "han cesado",
)

#: `<dejar|cesar> de <INFINITIVO>`. Solo es cesacion RELACIONAL si el infinitivo
#: pertenece a `RELATIONAL_INFINITIVES`: "ha dejado de fumar" cierra un habito,
#: no un vinculo con ninguna entidad.
CESSATION_PERIPHRASIS_DE: tuple[str, ...] = tuple(
    f"{forma} de" for forma in (*DEJAR_FORMS, *CESAR_FORMS)
)

#: `<dejar> atras <COMPLEMENTO>`. Solo es cesacion relacional si el complemento
#: NOMBRA un vinculo (`RELATIONAL_COMPLEMENT_NOUNS`): "dejo atras el campamento"
#: es desplazamiento fisico, no ruptura de relacion.
CESSATION_PERIPHRASIS_ATRAS: tuple[str, ...] = tuple(
    f"{forma} atras" for forma in DEJAR_FORMS
)

#: Infinitivos que denotan una RELACION o un CARGO. Vocabulario cerrado: es la
#: guarda de complemento que separa "dejo de liderar el Conclave" (cesacion de
#: una relacion) de "ha dejado de fumar" (cesacion de un habito).
RELATIONAL_INFINITIVES: frozenset[str] = frozenset({
    "pertenecer", "militar", "integrar", "formar", "figurar", "constar",
    "liderar", "dirigir", "encabezar", "presidir", "capitanear", "comandar",
    "gobernar", "reinar", "mandar",
    "servir", "obedecer", "acatar", "apoyar", "colaborar", "cooperar",
    "poseer", "ostentar", "regentar", "depender", "representar",
    # copulas: "ha dejado de SER/ESTAR dirigida por X" es cesacion relacional.
    "ser", "estar",
})

#: Sustantivos que NOMBRAN un vinculo o un cargo. Vocabulario cerrado: son los
#: unicos complementos con los que `dejar atras` lee como cesacion relacional.
RELATIONAL_COMPLEMENT_NOUNS: frozenset[str] = frozenset({
    "alianza", "alianzas", "pacto", "pactos", "acuerdo", "acuerdos",
    "vinculo", "vinculos", "lazo", "lazos", "union", "sociedad",
    "amistad", "rivalidad", "enemistad", "servidumbre", "vasallaje",
    "militancia", "pertenencia", "membresia", "afiliacion", "adscripcion",
    "lealtad", "juramento", "compromiso", "obediencia", "fidelidad",
    "cargo", "puesto", "presidencia", "direccion", "jefatura", "mando",
    "liderazgo", "capitania", "regencia", "magistratura",
})

#: Determinantes y posesivos que se saltan para llegar al NUCLEO del
#: complemento ("su alianza", "el campamento").
COMPLEMENT_DETERMINERS: frozenset[str] = frozenset({
    "el", "la", "lo", "los", "las", "un", "una", "unos", "unas",
    "su", "sus", "mi", "mis", "tu", "tus", "nuestro", "nuestra",
    "nuestros", "nuestras", "este", "esta", "estos", "estas",
    "ese", "esa", "esos", "esas", "aquel", "aquella", "aquellos",
    "aquellas", "toda", "todo", "todas", "todos", "cualquier",
})

#: CESACION: hubo relacion y termina.
CESSATION_PHRASES: tuple[str, ...] = (
    "ya no",
    *CESSATION_PERIPHRASIS_DE,
    *CESSATION_PERIPHRASIS_ATRAS,
    "ceso en",
    "abandona",
    "abandono",
    "abandonaron",
    "rompio su alianza",
    "rompio la alianza",
    "rompio sus lazos",
    "renuncio a",
    "renuncio al",
    "dimitio de",
    "dimitio como",
    "fue expulsado de",
    "fue expulsada de",
    "fue destituido de",
    "fue destituida de",
    "fue abandonada por",
    "fue abandonado por",
    "se separo de",
    "perdio su puesto en",
    "salio del",
)

#: Cuantificadores de litotes positivos: "no pocos" = "muchos". Cuando "no"
#: va seguido inmediatamente de uno de estos cuantificadores, la negacion NO
#: es una marca de negacion sobre la relacion: es un recurso retorico que
#: intensifica la afirmacion. Suprimir "no" del recuento de marcas en ese caso.
LITOTES_QUANTIFIERS: frozenset[str] = frozenset({"pocos", "pocas", "pocas"})

#: Frases que abren una subordinada EXCEPTIVA. La clausula subordinada
#: resultante esta negada con certeza ("sello el pacto sin que lo ratificara"
#: = "no lo ratifico"). Se detectan como tokens ADYACENTES para no confundir
#: con "sin dinero", "sin permiso", etc.
EXCEPTIVE_SUBORDINATORS: tuple[tuple[str, str], ...] = (
    ("sin", "que"),
)

#: Preposiciones que abren un ADJUNTO nuevo. Marcan el final del alcance SEGURO
#: de la subordinada exceptiva: a partir de ahi el sintagma puede colgar del
#: verbo principal o del subordinado, y esa ambiguedad de adjuncion no se
#: resuelve con lexico. Compara:
#:
#:   "El emisario hablo sin que nadie lo interrumpiera sobre la Liga de Corvo"
#:       -> "sobre la Liga" cuelga de "hablo": la Liga NO esta negada.
#:   "El notario firmo el acta sin que el testigo la avalara ante el Concejo"
#:       -> "ante el Concejo" cuelga de "avalara": el Concejo SI lo esta.
#:
#: Las dos frases son indistinguibles token a token. La regla, por tanto, no
#: decide: dentro del tramo seguro niega; pasado el limite pide REVISION.
ADJUNCT_PREPOSITIONS: frozenset[str] = frozenset({
    "sobre", "ante", "para", "por", "desde", "hasta", "tras", "durante",
    "contra", "segun", "mediante", "acerca", "respecto", "en",
})

#: Verbos de ACTITUD o de REPORTE. Si la negacion va pegada a uno de ellos, lo
#: negado es la creencia, no la relacion: "El magistrado no cree que Toturi
#: pertenezca al clan" no dice que Toturi no pertenezca.
#:
#: Bloque B4 (puerta 4): las formas irregulares se quedan declaradas a mano
#: aqui (son las excepciones que ninguna tabla regular cubre). Los verbos de
#: reporte REGULARES -AR ("afirmar", "declarar", "asegurar", "confirmar" y
#: "negar", este ultimo con su presente irregular declarado aparte) se
#: generan por PARADIGMA morfologico en `morphology.py` y se anaden aqui via
#: `reporting_verb_forms()`, para no tener que teclear cada conjugacion a
#: mano verbo a verbo -- ver el docstring de ese modulo para el porque.
SCOPE_VERBS: tuple[str, ...] = (
    "consta", "considera", "consideraba",
    "cree", "creia", "creyo",
    "decia", "dice", "dijo",
    "imagina", "imaginaba",
    "parece", "parecia",
    "penso", "piensa", "pensaba",
    "recordaba", "recuerda",
    "sabe", "sabia", "supo",
    "sospecha", "sospechaba",
    # Bloque B1 (puerta 6): "admitir" (-IR) y "reconocer" (-ER) son verbos
    # factivos/de reconocimiento de la MISMA clase que "confirmar" (ya
    # cubierto via `reporting_verb_forms()`), pero ninguno es regular -AR, asi
    # que no los genera `morphology.conjugate_regular_ar`. Se declaran a mano,
    # solo 3a persona (singular/plural, presente/preterito/imperfecto/
    # perfecto/pluscuamperfecto), mismo criterio que "decir"/"saber" arriba:
    # paradigma de diccionario general, no una forma copiada de un caso de
    # corpus. Sin ellos, "no admitio que"/"no reconocio que" no disparaban
    # `CODE_NEGATION_SCOPE` y la familia NEGATION_OF_FACTIVE del corpus de
    # generalizacion composicional se leia como hecho (violacion fail-closed).
    "admite", "admiten", "admitio", "admitieron", "admitia", "admitian",
    "ha admitido", "han admitido", "habia admitido", "habian admitido",
    "reconoce", "reconocen", "reconocio", "reconocieron",
    "reconocia", "reconocian",
    "ha reconocido", "han reconocido", "habia reconocido", "habian reconocido",
    *reporting_verb_forms(),
)

# --------------------------------------------------------------------------
# Bloque B1 (puerta 6): operador de DISCURSO REPORTADO POR TERCERO.
# --------------------------------------------------------------------------
#: Verbos de REPORTE (acto de habla que atribuye una afirmacion a un tercero),
#: distintos de los verbos FACTIVOS/de reconocimiento de `SCOPE_VERBS`
#: ("confirmar", "admitir", "reconocer", "verificar", "aceptar"): si alguien
#: CONFIRMA/ADMITE/RECONOCE/VERIFICA/ACEPTA algo, el verbo presupone que lo
#: dicho es cierto (son "factivos-implicativos"); si alguien DICE/AFIRMA/
#: DECLARA/ASEGURA/SOSTIENE/COMENTA/RELATA/INFORMA/MENCIONA/INDICA/REPITE/
#: INSISTE/ESCRIBE/CUENTA/CONFIESA algo, el texto solo atestigua el ACTO de
#: decirlo, no la verdad de lo dicho -- por eso "confirmar" se queda fuera de
#: esta lista y "decir"/"afirmar" entran aqui. Deliberadamente NO incluye
#: "referir": el corpus dev (`fact:hecho-afirmado:08`, "El escriba refirio
#: que ... y sus libros lo confirman", gold WRITE_POSITIVE) es un caso real
#: donde un reporte SI se escribe como hecho porque el propio texto aporta
#: corroboracion independiente en la misma frase; anadir "referir" aqui lo
#: convertiria en una violacion nueva, asi que se excluye a proposito.
#:
#: Formas regulares -AR generadas por lema (nunca copiadas de un caso de
#: corpus) mas las irregulares/-ER/-IR declaradas a mano, mismo criterio que
#: `SCOPE_VERBS` de arriba.
_REPORT_VERB_AR_LEMMAS: tuple[str, ...] = (
    "afirmar", "declarar", "asegurar",
    "comentar", "relatar", "informar", "mencionar", "indicar",
)
REPORT_VERB_HAND_FORMS: tuple[str, ...] = (
    # decir (irregular): SCOPE_VERBS solo tenia el singular; aqui hacen falta
    # tambien las formas plurales para el operador de reporte.
    "dice", "dicen", "dijo", "dijeron", "decia", "decian",
    # sostener (irregular, paradigma de "tener")
    "sostiene", "sostienen", "sostuvo", "sostuvieron",
    "sostenia", "sostenian",
    "ha sostenido", "han sostenido", "habia sostenido", "habian sostenido",
    # contar (irregular, diptongacion o->ue)
    "cuenta", "cuentan", "conto", "contaron", "contaba", "contaban",
    "ha contado", "han contado", "habia contado", "habian contado",
    # repetir (irregular, e->i)
    "repite", "repiten", "repitio", "repitieron", "repetia", "repetian",
    "ha repetido", "han repetido", "habia repetido", "habian repetido",
    # confesar (irregular, e->ie)
    "confiesa", "confiesan", "confeso", "confesaron",
    "confesaba", "confesaban",
    "ha confesado", "han confesado", "habia confesado", "habian confesado",
    # escribir (regular -IR salvo el participio irregular "escrito")
    "escribe", "escriben", "escribio", "escribieron",
    "escribia", "escribian",
    "ha escrito", "han escrito", "habia escrito", "habian escrito",
    # insistir (regular -IR)
    "insiste", "insisten", "insistio", "insistieron",
    "insistia", "insistian",
    "ha insistido", "han insistido", "habia insistido", "habian insistido",
)
REPORT_VERBS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *[
                forma
                for lemma in _REPORT_VERB_AR_LEMMAS
                for forma in conjugate_regular_ar(lemma).all_forms()
            ],
            *REPORT_VERB_HAND_FORMS,
        ]
    )
)

#: Formas de REPORT_VERBS que son TAMBIEN sustantivos frecuentes en espanol.
#: Bloque B2 (puerta 6): `_reported_speech_cue` compara tokens por norma
#: contra REPORT_VERBS sin ninguna guarda de categoria gramatical. "cuenta"
#: (factura/relacion de gastos) normaliza igual que la 3a persona singular de
#: "contar" declarada en REPORT_VERB_HAND_FORMS; "cuentan" (3a plural de
#: "contar") puede aparecer como verbo factual ("las fichas que cuentan").
#: "relato" (narracion) normaliza igual que la 3a persona singular de
#: preterito de "relatar" (relato -> relato sin tilde en normalizacion).
#: Si alguno de estos tokens aparece PRECEDIDO de un determinante de
#: COMPLEMENT_DETERMINERS, es un sintagma nominal ("la cuenta que presento"),
#: no un verbo de reporte ("cuenta que presento el mercader = informa que
#: presento"), y el operador NO debe disparar.
REPORT_VERB_NOUN_HOMOGRAPHS: frozenset[str] = frozenset({"cuenta", "cuentan", "relato"})

#: Conjunciones que abren una clausula NUEVA. La negacion de la anterior no
#: viaja: "Kael no llego a tiempo, pero Mira pertenece al Gremio".
CLAUSE_CONJUNCTIONS: tuple[str, ...] = (
    "pero",
    "aunque",
    "sino",
    "mientras",
    "embargo",
)

#: Puntuacion que separa clausulas. Se busca en el HUECO entre dos tokens, no en
#: los tokens: el tokenizador es `\w+` y la puntuacion no es un token.
CLAUSE_PUNCTUATION = ",;:\n\r"

#: "si" solo cuenta como condicional SIN tilde y como palabra suelta: "si" y
#: "si" (afirmacion) son la misma cadena una vez normalizada, y confundirlas
#: convertiria cualquier "si" en una hipotesis.
CONDITIONAL_SI = "si"

#: Conectores que, INMEDIATAMENTE despues de un `SCOPE_VERB` negado, delatan
#: que lo negado es la actitud epistemica y no la relacion: la completiva
#: ("no reconocio QUE sirviera") y la interrogativa indirecta entera ("no sabe
#: SI/CUANDO/DONDE/COMO/QUIEN/CUAL/CUANTO ...").
#:
#: Es una clase gramatical CERRADA del espanol (pronombres, adverbios y
#: determinantes interrogativos), no vocabulario tomado de ningun corpus: la
#: lista es la enumeracion completa de la clase, con sus variantes de genero y
#: numero, ya normalizada (sin tilde, que es lo que produce `text.normalize`).
#: B2 solo reconocia "que"/"si", los dos que los corpus de dev y de puerta 4
#: exigieron; el resto de la clase es el MISMO fenomeno y caia en silencio al
#: camino de negacion directa (NEGATED_FACT) -- una asercion sobre el mundo
#: donde el texto solo dice que alguien ignora un dato.
INDIRECT_QUESTION_CONNECTORS: frozenset = frozenset({
    "que", "si",
    "cuando", "donde", "adonde",
    "como",
    "quien", "quienes",
    "cual", "cuales",
    "cuanto", "cuanta", "cuantos", "cuantas",
})

#: Los miembros de la clase que ocupan DOS tokens: el tokenizador es `\w+`, asi
#: que "por que" y "lo que" llegan partidos.
INDIRECT_QUESTION_CONNECTOR_PAIRS: tuple[tuple[str, str], ...] = (
    ("por", "que"),
    ("lo", "que"),
)


def indirect_question_connector(
    tokens: Sequence[Token], start: int, hi: int
) -> Optional[str]:
    """Conector de completiva/interrogativa indirecta que empieza en `start`.

    Devuelve la forma normalizada (una o dos palabras) o `None`. No decide
    nada: solo reconoce la clase gramatical.
    """
    if start >= hi:
        return None
    if start + 1 < hi:
        par = (tokens[start].norm, tokens[start + 1].norm)
        if par in INDIRECT_QUESTION_CONNECTOR_PAIRS:
            return " ".join(par)
    if tokens[start].norm in INDIRECT_QUESTION_CONNECTORS:
        return tokens[start].norm
    return None


#: Signos que delatan una interrogativa. Una pregunta no afirma nada.
INTERROGATIVE_MARKS = ("¿", "?")

#: Codigos de razon (estables, `^[A-Z][A-Z0-9_]{0,63}$`).
CODE_NEGATION_MISMATCH = "NEGATION_CONTEXT_MISMATCH"
CODE_NON_FACTIVE = "NON_FACTIVE_CONTEXT"
CODE_FALSITY = "FALSITY_CONTEXT"
CODE_CONDITIONAL = "CONDITIONAL_CONTEXT"
CODE_COUNTERFACTUAL = "COUNTERFACTUAL_CONTEXT"
CODE_INTERROGATIVE = "INTERROGATIVE_CONTEXT"
CODE_FICTION = "FICTION_WITHIN_FICTION_CONTEXT"
CODE_DEONTIC = "DEONTIC_CONTEXT"
CODE_DESIRE = "DESIRE_CONTEXT"
#: El texto niega, pero el alcance de la negacion no es la relacion extraida.
CODE_NEGATION_SCOPE = "REVIEW_NEGATION_SCOPE"
#: Bloque B1 (puerta 6): el texto atribuye la afirmacion a un TERCERO
#: ("X dijo/afirmo/declaro que P"). El acto de habla existe, pero P no esta
#: verificado por el propio texto -- es del mismo tipo epistemico que un
#: rumor (atribuido, no confirmado), asi que se trata con el MISMO
#: mecanismo que RUMORED: degrada el hint epistemico si no hay ya uno mas
#: fuerte, nunca se materializa como ASSERTED_FACT/NEGATED_FACT.
CODE_REPORTED_SPEECH = "REPORTED_SPEECH_CONTEXT"
#: La propuesta dice `negated=true` y la evidencia no lo respalda. Un proveedor
#: no puede INVENTAR una negacion, igual que no puede borrarla.
CODE_NEGATION_NOT_IN_EVIDENCE = "NEGATION_NOT_IN_EVIDENCE"


@dataclass(frozen=True)
class ContextVerdict:
    """Lo que el contexto REAL dice sobre un hecho propuesto."""

    negated: bool = False
    hint: str = "ASSERTED"
    cues: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    #: Tipo de negacion (`NEGATION_KINDS`), vacio si no hay negacion.
    negation_kind: str = ""

    @property
    def factivity(self) -> FactivityResult:
        """Resultado de la unica politica de factualidad del extractor."""
        codes = set(self.reason_codes)
        return classify_factivity(
            FactivitySignals(
                negated=self.negated,
                question=CODE_INTERROGATIVE in codes,
                conditional=CODE_CONDITIONAL in codes,
                counterfactual=CODE_COUNTERFACTUAL in codes,
                hypothetical=self.hint == "HYPOTHETICAL",
                desire=CODE_DESIRE in codes,
                command=CODE_DEONTIC in codes,
                reported_falsehood=CODE_FALSITY in codes,
                fiction_within_fiction=CODE_FICTION in codes,
                rumor=self.hint == "RUMORED",
                ambiguous_scope=CODE_NEGATION_SCOPE in codes,
            ),
            cues=self.cues,
            reasons=self.reason_codes,
            scope="AMBIGUOUS" if CODE_NEGATION_SCOPE in codes else "WORLD",
        )

    @property
    def not_a_statement(self) -> bool:
        """Deseo, orden o prohibicion: no es un hecho, pero tampoco una farsa.

        Se separa de `non_factive` a proposito. Ante un contrafactual, una
        pregunta o una ficcion interna no se emite NADA (ver
        `payload._drop_non_factive`); ante un deseo o una prohibicion si se emite
        una ABSTENCION, porque ahi el texto SI habla de esa relacion —dice que
        alguien la quiere o la prohibe— y perder el rastro seria perder
        informacion.
        """
        return self.factivity.factivity_class.value in {"COMMAND", "DESIRE"}

    @property
    def non_factive(self) -> bool:
        """El texto no esta afirmando el hecho (lo supone, lo pregunta o lo niega)."""
        return self.factivity.factivity_class.value in {
            "QUESTION",
            "CONDITIONAL",
            "COUNTERFACTUAL",
            "HYPOTHETICAL",
            "REPORTED_FALSEHOOD",
            "FICTION_WITHIN_FICTION",
        }

    @property
    def blocks_assertion(self) -> bool:
        return self.negated or self.non_factive


def _has_phrase(tokens: Sequence[Token], phrase: str, lo: int, hi: int) -> bool:
    needle = phrase_tokens(phrase)
    return bool(needle) and bool(find_phrase(tokens, needle, lo=lo, hi=hi))


def _first_phrase(
    tokens: Sequence[Token], phrases: Sequence[str], lo: int, hi: int
) -> Optional[str]:
    for phrase in phrases:
        if _has_phrase(tokens, phrase, lo, hi):
            return phrase
    return None


def _reported_speech_cue(
    tokens: Sequence[Token], lo: int, hi: int
) -> Optional[str]:
    """Primer `<verbo de reporte> que` en `[lo, hi)`, si lo hay.

    Igual que `scope_negation` busca `no <verbo de actitud>` pegados, esto
    busca `<verbo de reporte> que` pegados: el hueco cerrado (0 tokens entre
    verbo y "que") evita que un "que" remoto de otra subordinada dispare el
    operador.

    Bloque B2 (puerta 6): guarda de HOMOGRAFO. Las formas de `REPORT_VERBS`
    declaradas en `REPORT_VERB_NOUN_HOMOGRAPHS` ("cuenta", "cuentan",
    "relato") coinciden con sustantivos frecuentes del espanol. Si el token
    en cuestion va PRECEDIDO de un determinante de `COMPLEMENT_DETERMINERS`,
    es un sintagma nominal ("la cuenta que presento el mercader"), no un
    verbo de reporte completivo, y el operador NO debe disparar.
    """
    for i in range(lo, hi - 1):
        if tokens[i].norm in REPORT_VERBS and tokens[i + 1].norm == "que":
            if (
                tokens[i].norm in REPORT_VERB_NOUN_HOMOGRAPHS
                and i > lo
                and tokens[i - 1].norm in COMPLEMENT_DETERMINERS
            ):
                continue
            return f"{tokens[i].text} que"
    return None


#: Tokens de margen para decidir que una marca de negacion niega A LA FRASE DE
#: CESACION y no a otra cosa. Con 3 caben "no dejo de" y "y no la abandona".
CESSATION_NEGATION_WINDOW = 3


def cessation_complement_ok(
    tokens: Sequence[Token], phrase: str, last: int, hi: int
) -> bool:
    """¿El COMPLEMENTO de la perifrasis es una relacion, y no otra cosa?

    Las perifrasis `dejar de <X>` y `dejar atras <X>` no son cesaciones por si
    mismas: lo son o no segun QUE cierran. "Ha dejado de fumar" cierra un
    habito y "ha dejado atras el campamento" describe un desplazamiento; ni una
    ni otra dicen nada de la relacion entre el sujeto y la entidad focalizada, y
    tratarlas como cesacion inventa el cierre de una relacion que el texto no
    menciona (falso positivo de negacion, el error mas caro de este modulo).

    Las demas frases de `CESSATION_PHRASES` llevan el complemento incorporado
    ("dimitio de", "fue expulsado de") y no necesitan guarda.
    """
    if phrase in CESSATION_PERIPHRASIS_DE:
        nxt = last + 1
        return nxt < hi and tokens[nxt].norm in RELATIONAL_INFINITIVES
    if phrase in CESSATION_PERIPHRASIS_ATRAS:
        i = last + 1
        while i < hi and tokens[i].norm in COMPLEMENT_DETERMINERS:
            i += 1
        return i < hi and tokens[i].norm in RELATIONAL_COMPLEMENT_NOUNS
    return True


def cessation_matches(
    tokens: Sequence[Token], lo: int, hi: int
) -> list[tuple[str, int, int]]:
    """`(frase, primer_token, ultimo_token)` de cada cesacion, en orden de texto."""
    encontradas: list[tuple[str, int, int]] = []
    for phrase in CESSATION_PHRASES:
        needle = phrase_tokens(phrase)
        if not needle:
            continue
        for first, last in find_phrase(tokens, needle, lo=lo, hi=hi):
            if not cessation_complement_ok(tokens, phrase, last, hi):
                continue
            encontradas.append((phrase, first, last))
    return sorted(encontradas, key=lambda m: (m[1], m[2]))


def negated_cessation(
    tokens: Sequence[Token],
    matches: Sequence[tuple[str, int, int]],
    marcas_negacion: Sequence[str],
    lo: int,
) -> Optional[str]:
    """Cesacion NEGADA: `no dejo de servir` AFIRMA la relacion, no la cierra.

    Es la inversion semantica mas cara que este modulo puede cometer: leer "no
    dejo de servir a la Orden" como una cesacion propondria CERRAR la vigencia de
    la relacion que el texto esta afirmando. Y no hace falta que el `no` este
    pegado: "Elara pertenece a la Orden y no la abandona" tiene la marca dos
    tokens antes de la frase de cesacion.

    Se mira ANTES de la frase de cesacion y con ventana propia, no con el `focus`
    de la relacion: en el ejemplo de arriba la marca esta DESPUES del foco, asi
    que la ventana de negacion normal no la ve.
    """
    for phrase, first, _last in matches:
        ventana = range(max(lo, first - CESSATION_NEGATION_WINDOW), first)
        for i in ventana:
            if tokens[i].norm in marcas_negacion:
                return f"{tokens[i].text} {phrase}"
    return None


def independent_cessations(
    tokens: Sequence[Token],
    matches: Sequence[tuple[str, int, int]],
    marcas_negacion: Sequence[str],
) -> list[tuple[str, int, int]]:
    """Cesaciones que APORTAN una negacion propia al recuento.

    `ya no` NO aporta: su `no` ya se conto como marca suelta, y contarlo dos
    veces convertiria cualquier `ya no` en una doble negacion. `dejo de`,
    `abandono` o `dimitio de` si aportan: niegan la relacion sin llevar ninguna
    marca de `NEGATION_CUES` dentro.
    """
    return [
        m
        for m in matches
        if not any(tokens[i].norm in marcas_negacion for i in range(m[1], m[2] + 1))
    ]


def scope_negation(
    tokens: Sequence[Token],
    *,
    lo: int = 0,
    hi: Optional[int] = None,
    negation_cues: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """La marca `no <verbo de actitud>` en `[lo, hi)`, si la hay.

    Se busca en TODA la ventana, no solo en la ventana corta de negacion: lo que
    importa no es la distancia sino que la relacion cuelgue de una creencia
    ajena. "El magistrado no cree que Toturi pertenezca al clan" no dice que
    Toturi pertenezca ni que no pertenezca, y ese "no" esta lejos del verbo de la
    relacion.
    """
    marcas = NEGATION_CUES if negation_cues is None else tuple(negation_cues)
    hi = len(tokens) if hi is None else min(hi, len(tokens))
    for i in range(lo, hi):
        if tokens[i].norm in marcas and i + 1 < hi and tokens[i + 1].norm in SCOPE_VERBS:
            return f"{tokens[i].text} {tokens[i + 1].text}"
    return None


@dataclass(frozen=True)
class NegationVerdict:
    """Que niega el texto, de que tipo, y con que marcas."""

    negated: bool = False
    kind: str = ""
    cues: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


def exceptive_scope(
    tokens: Sequence[Token],
    *,
    inicio: int,
    hi: int,
    focus: int,
    source_text: Optional[str] = None,
) -> Optional[tuple[str, bool]]:
    """`(marca, foco_dentro_del_alcance)` de la subordinada exceptiva, si la hay.

    Devuelve `None` cuando no hay ninguna ("sin que" no aparece, o aparece
    DESPUES del foco: un hecho de la clausula PRINCIPAL enunciado antes de
    "sin que" no queda afectado por ella).

    El alcance va desde el "que" hasta el primer limite: puntuacion, conjuncion
    de clausula o preposicion de adjunto (`ADJUNCT_PREPOSITIONS`). Dentro del
    alcance la negacion es segura; fuera, la adjuncion es ambigua y el segundo
    elemento vale `False` para que quien llame pida REVISION en vez de decidir.
    """
    for t1, t2 in EXCEPTIVE_SUBORDINATORS:
        for i in range(inicio, min(focus, hi) - 1):
            if tokens[i].norm != t1 or tokens[i + 1].norm != t2:
                continue
            marca = f"{tokens[i].text} {tokens[i + 1].text}"
            fin = i + 2
            while fin < hi:
                if tokens[fin].norm in ADJUNCT_PREPOSITIONS:
                    break
                if tokens[fin].norm in CLAUSE_CONJUNCTIONS:
                    break
                if source_text is not None and fin > i + 2:
                    hueco = source_text[tokens[fin - 1].end : tokens[fin].start]
                    if any(ch in CLAUSE_PUNCTUATION for ch in hueco):
                        break
                fin += 1
            return marca, (i + 2 <= focus < fin)
    return None


def clause_start(
    tokens: Sequence[Token], *, lo: int, focus: int, source_text: Optional[str] = None
) -> int:
    """Primer token de la CLAUSULA que contiene `focus`.

    Existe por un caso concreto y medido: "Kael no llego a tiempo, pero Mira
    pertenece al Gremio". La negacion esta en la frase, pero no en la clausula de
    la relacion extraida, y contarla convertiria una afirmacion positiva en su
    contraria. Los limites son las conjunciones adversativas y la puntuacion.

    `source_text` tiene que ser el texto con los offsets ABSOLUTOS de `tokens`.
    Sin el, solo se miran las conjunciones: el tokenizador es `\\w+` y la
    puntuacion no llega aqui como token.
    """
    inicio = lo
    tope = min(focus, len(tokens))
    for i in range(lo, tope):
        if tokens[i].norm in CLAUSE_CONJUNCTIONS:
            inicio = i + 1
            continue
        if source_text is not None and i > lo:
            hueco = source_text[tokens[i - 1].end : tokens[i].start]
            if any(ch in CLAUSE_PUNCTUATION for ch in hueco):
                inicio = i
    return min(inicio, tope)


def classify_negation(
    tokens: Sequence[Token],
    *,
    lo: int = 0,
    hi: Optional[int] = None,
    focus: Optional[int] = None,
    source_text: Optional[str] = None,
    clause_scoped: bool = True,
    negation_cues: Optional[Sequence[str]] = None,
) -> NegationVerdict:
    """Clasifica la negacion que afecta a lo afirmado en `focus`.

    Precedencia, y por que ese orden:

        1. ALCANCE      "no cree que ..."  -> la negacion es de la creencia
        2. DOBLE        dos marcas         -> no se resuelve mecanicamente
        3. NOT_YET      "todavia no"       -> antes que cesacion: no demuestra
                                             que antes lo fuera
        4. CESSATION    "ya no", "dejo de" -> hubo relacion y termina
        5. NEVER        "nunca", "jamas"   -> negacion absoluta
        6. SIMPLE       "no", "tampoco"    -> negacion corriente

    Los casos 1 y 2 devuelven `negated=False` con un codigo de razon: quien llame
    debe abstenerse o pedir revision, NUNCA negar por su cuenta.
    """
    marcas_negacion = NEGATION_CUES if negation_cues is None else tuple(negation_cues)
    hi = len(tokens) if hi is None else min(hi, len(tokens))
    focus = hi if focus is None else max(lo, min(focus, hi))
    inicio = (
        clause_start(tokens, lo=lo, focus=focus, source_text=source_text)
        if clause_scoped
        else lo
    )

    # 1. alcance: la negacion va pegada a un verbo de actitud o de reporte,
    #    Y el verbo introduce una subordinada completiva ("que ...") o una
    #    interrogativa indirecta ("si/cuando/donde/como/quien/cual/cuanto/
    #    por que/lo que ...", clase gramatical cerrada declarada en
    #    `INDIRECT_QUESTION_CONNECTORS`; el rework de B2 la completo, antes
    #    solo miraba "que"/"si"). Sin ninguno de esos conectores
    #    inmediatos, el verbo toma un objeto directo y la negacion es DIRECTA
    #    (NEGATED_FACT), no de alcance ambiguo. Bloque B2 (puerta 6):
    #    "no reconocio el terreno" es una negacion directa, no SCOPE_AMBIGUOUS;
    #    "no reconocio que sirviera" y "no sabe si dirige" SI son alcance
    #    ambiguo. Esto corrige el exceso de superficie de SCOPE_VERBS anadido
    #    en B1 (admitir/reconocer/aceptar/verificar tienen un uso frecuente con
    #    objeto directo sin "que"/"si" que no es alcance epistemico), y
    #    generaliza la misma correccion a los verbos preexistentes de
    #    SCOPE_VERBS (p. ej. "no sabia el camino" es NEGATED_FACT, no
    #    SCOPE_AMBIGUOUS, pero "no sabia si llegaria" SI es SCOPE_AMBIGUOUS).
    for i in range(inicio, focus):
        if tokens[i].norm in marcas_negacion and i + 1 < hi and tokens[i + 1].norm in SCOPE_VERBS:
            if indirect_question_connector(tokens, i + 2, hi) is None:
                continue
            return NegationVerdict(
                False,
                NEGATION_KIND_SCOPE_AMBIGUOUS,
                (f"{tokens[i].text} {tokens[i + 1].text}",),
                (CODE_NEGATION_SCOPE,),
            )

    # 1b. subordinada exceptiva ("sin que"). Lo que esta negado es la
    # SUBORDINADA, no la frase entera: hay que comprobar que el foco cae dentro
    # de ella. B2 negaba en cuanto "sin que" aparecia antes del foco, lo que
    # convertia "El emisario hablo sin que nadie lo interrumpiera sobre la Liga
    # de Corvo" en una negacion de la Liga (falso positivo P0).
    exceptiva = exceptive_scope(
        tokens, inicio=inicio, hi=hi, focus=focus, source_text=source_text
    )
    if exceptiva is not None:
        marca, dentro = exceptiva
        if dentro:
            return NegationVerdict(True, NEGATION_KIND_SIMPLE, (marca,), ())
        return NegationVerdict(
            False, NEGATION_KIND_SCOPE_AMBIGUOUS, (marca,), (CODE_NEGATION_SCOPE,)
        )

    # 2. doble negacion: "ni"/"tampoco" no cuentan, son coordinacion de la misma.
    # "no pocos/pocas" es una litotes positiva: se suprime ese "no" del recuento.
    def _es_litotes(i: int) -> bool:
        return (
            tokens[i].norm == "no"
            and i + 1 < focus
            and tokens[i + 1].norm in LITOTES_QUANTIFIERS
        )

    marcas = [
        tokens[i].norm
        for i in range(inicio, focus)
        if tokens[i].norm in marcas_negacion
        and tokens[i].norm not in ("ni", "tampoco")
        and not _es_litotes(i)
    ]
    cesaciones = cessation_matches(tokens, inicio, hi)

    # 2a. CESACION NEGADA. Va antes que el recuento porque su marca puede estar
    # DESPUES del foco ("...y no la abandona") y ahi `marcas` no la ve.
    negada = negated_cessation(tokens, cesaciones, marcas_negacion, inicio)
    if negada is not None:
        return NegationVerdict(
            False, NEGATION_KIND_SCOPE_AMBIGUOUS, (negada,), (CODE_NEGATION_SCOPE,)
        )

    # 2b. Recuento. Las frases de cesacion son NEGADORES: "nunca dejo de servir"
    # lleva dos ("nunca" + "dejo de") y no es una cesacion, es una afirmacion
    # reforzada. Sin contarlas, `no` + `dejo de` sumaba UNA sola marca y caia en
    # CESSATION, que es exactamente la inversion que este bloque corrige.
    independientes = independent_cessations(tokens, cesaciones, marcas_negacion)
    if len(marcas) + len(independientes) >= 2:
        return NegationVerdict(
            False,
            NEGATION_KIND_SCOPE_AMBIGUOUS,
            tuple([*marcas, *(m[0] for m in independientes)]),
            (CODE_NEGATION_SCOPE,),
        )

    encontrada = _first_phrase(tokens, NOT_YET_PHRASES, inicio, hi)
    if encontrada:
        return NegationVerdict(True, NEGATION_KIND_NOT_YET, (encontrada,), ())

    if cesaciones:
        return NegationVerdict(
            True, NEGATION_KIND_CESSATION, (cesaciones[0][0],), ()
        )

    nunca = [tokens[i].norm for i in range(inicio, focus) if tokens[i].norm in NEVER_CUES]
    if nunca:
        return NegationVerdict(True, NEGATION_KIND_NEVER, tuple(nunca), ())

    if marcas:
        return NegationVerdict(True, NEGATION_KIND_SIMPLE, tuple(marcas), ())

    # Solo quedan "ni" y "tampoco", que se excluyeron del recuento de doble
    # negacion por ser coordinacion de la MISMA. Sueltas siguen negando. Se
    # excluyen tambien las litotes (ya filtradas en marcas arriba).
    sueltas = [
        tokens[i].norm
        for i in range(inicio, focus)
        if tokens[i].norm in marcas_negacion and not _es_litotes(i)
    ]
    if sueltas:
        return NegationVerdict(True, NEGATION_KIND_SIMPLE, tuple(sueltas), ())
    return NegationVerdict()


def analyze_context(
    text: str,
    tokens: Sequence[Token],
    *,
    lo: int = 0,
    hi: Optional[int] = None,
    focus: Optional[int] = None,
    negation_window: Optional[int] = None,
    source_text: Optional[str] = None,
    clause_scoped: bool = False,
) -> ContextVerdict:
    """Analiza el contexto `[lo, hi)` de tokens alrededor de un hecho.

    `focus` es el token donde empieza lo afirmado (la frase de relacion o el
    ancla de la cita). La negacion se busca ANTES de ese punto: la que viene
    despues suele negar otra cosa. `negation_window` acota esa busqueda; sin
    ella se mira todo el contexto previo, que es lo correcto cuando se esta
    verificando la cita de un modelo (ahi la prudencia gana a la precision).

    `clause_scoped` y `source_text` viajan a `classify_negation`: acotan la
    negacion a su CLAUSULA. Vienen en `False`/`None` por defecto para no cambiar
    el comportamiento de quien ya llamaba a esta funcion; la frontera semantica y
    el determinista los activan explicitamente.
    """
    hi = len(tokens) if hi is None else hi
    focus = hi if focus is None else focus
    reasons: list[str] = []
    cues: list[str] = []

    neg_lo = lo if negation_window is None else max(lo, focus - negation_window)
    negacion = classify_negation(
        tokens,
        lo=neg_lo,
        hi=hi,
        focus=focus,
        source_text=source_text,
        clause_scoped=clause_scoped,
    )
    negated = negacion.negated
    reasons.extend(negacion.reason_codes)
    cues.extend(negacion.cues)

    for phrase in FALSITY_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            if CODE_FALSITY not in reasons:
                reasons.append(CODE_FALSITY)

    for phrase in CONDITIONAL_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            # "de haber" presenta un mundo alternativo ya no realizado; el
            # resto de marcas suspende el hecho bajo una condicion abierta.
            code = CODE_COUNTERFACTUAL if phrase == "de haber" else CODE_CONDITIONAL
            if code not in reasons:
                reasons.append(code)
            if code == CODE_COUNTERFACTUAL and CODE_CONDITIONAL not in reasons:
                reasons.append(CODE_CONDITIONAL)

    normalized_window_cond = " ".join(token.norm for token in tokens[lo:hi])
    for pattern, cue in CONDITIONAL_PATTERNS:
        if pattern.search(normalized_window_cond):
            cues.append(cue)
            if CODE_CONDITIONAL not in reasons:
                reasons.append(CODE_CONDITIONAL)

    for phrase in FICTION_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            if CODE_FICTION not in reasons:
                reasons.append(CODE_FICTION)

    for phrase in DEONTIC_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            if CODE_DEONTIC not in reasons:
                reasons.append(CODE_DEONTIC)

    for phrase in DESIRE_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            if CODE_DESIRE not in reasons:
                reasons.append(CODE_DESIRE)

    # "si" condicional: sin tilde y antes de lo afirmado.
    for i in range(lo, min(focus, hi)):
        if tokens[i].text.lower() == CONDITIONAL_SI:
            cues.append(CONDITIONAL_SI)
            if CODE_CONDITIONAL not in reasons:
                reasons.append(CODE_CONDITIONAL)
            break

    if any(mark in (text or "") for mark in INTERROGATIVE_MARKS):
        reasons.append(CODE_INTERROGATIVE)
    for phrase in INTERROGATIVE_PHRASES:
        if _has_phrase(tokens, phrase, lo, hi):
            cues.append(phrase)
            if CODE_INTERROGATIVE not in reasons:
                reasons.append(CODE_INTERROGATIVE)

    hint = "ASSERTED"
    for cue, mapped in EPISTEMIC_CUES:
        if _has_phrase(tokens, cue, lo, hi):
            cues.append(cue)
            if hint == "ASSERTED":
                hint = mapped
    normalized_window = " ".join(token.norm for token in tokens[lo:hi])
    for pattern, cue, mapped in EPISTEMIC_PATTERNS:
        if pattern.search(normalized_window):
            cues.append(cue)
            if hint == "ASSERTED":
                hint = mapped

    # Bloque B1 (puerta 6): discurso reportado por un tercero ("X dijo que
    # P"). Se trata con el MISMO mecanismo que RUMORED -- degrada el hint si
    # todavia esta en ASSERTED, nunca lo sube de rango si ya hay algo mas
    # fuerte (falsedad, condicional-ya-convertido-en-hipotetico, etc.). Eso
    # cubre gratis el reporte de una negacion ("X informo que Y no ..."): el
    # hint pasa a RUMORED y `ContextVerdict.factivity` clasifica RUMOR antes
    # de llegar al `if signals.negated` de reserva, asi que nunca se
    # materializa como NEGATED_FACT solo porque la clausula reportada
    # contenga un "no".
    reported = _reported_speech_cue(tokens, lo, hi)
    if reported:
        cues.append(reported)
        if CODE_REPORTED_SPEECH not in reasons:
            reasons.append(CODE_REPORTED_SPEECH)
        if hint == "ASSERTED":
            hint = "RUMORED"

    if CODE_CONDITIONAL in reasons and hint == "ASSERTED":
        hint = "HYPOTHETICAL"
    if CODE_FALSITY in reasons or CODE_INTERROGATIVE in reasons or CODE_FICTION in reasons:
        hint = "UNKNOWN"

    if CODE_DEONTIC in reasons or CODE_DESIRE in reasons:
        hint = "UNKNOWN" if hint == "ASSERTED" else hint

    return ContextVerdict(
        negated=negated,
        hint=hint,
        cues=tuple(dict.fromkeys(cues)),
        reason_codes=tuple(reasons),
        negation_kind=negacion.kind,
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
    "ADJUNCT_PREPOSITIONS",
    "CESAR_FORMS",
    "CESSATION_PERIPHRASIS_ATRAS",
    "CESSATION_PERIPHRASIS_DE",
    "CESSATION_PHRASES",
    "COMPLEMENT_DETERMINERS",
    "DEJAR_FORMS",
    "RELATIONAL_COMPLEMENT_NOUNS",
    "RELATIONAL_INFINITIVES",
    "cessation_complement_ok",
    "exceptive_scope",
    "CLAUSE_CONJUNCTIONS",
    "CODE_CONDITIONAL",
    "CODE_COUNTERFACTUAL",
    "CODE_DEONTIC",
    "CODE_DESIRE",
    "CODE_FALSITY",
    "CODE_FICTION",
    "CODE_INTERROGATIVE",
    "CODE_NEGATION_MISMATCH",
    "CODE_NEGATION_NOT_IN_EVIDENCE",
    "CODE_NEGATION_SCOPE",
    "CODE_NON_FACTIVE",
    "CODE_REPORTED_SPEECH",
    "CONDITIONAL_PATTERNS",
    "CONDITIONAL_PHRASES",
    "DEONTIC_PHRASES",
    "DESIRE_PHRASES",
    "EPISTEMIC_CUES",
    "EPISTEMIC_PATTERNS",
    "FALSITY_PHRASES",
    "FICTION_PHRASES",
    "INDIRECT_QUESTION_CONNECTORS",
    "INDIRECT_QUESTION_CONNECTOR_PAIRS",
    "indirect_question_connector",
    "INTERROGATIVE_MARKS",
    "INTERROGATIVE_PHRASES",
    "NEGATION_CUES",
    "REPORT_VERBS",
    "REPORT_VERB_HAND_FORMS",
    "REPORT_VERB_NOUN_HOMOGRAPHS",
    "NEGATION_KINDS",
    "NEGATION_KIND_CESSATION",
    "NEGATION_KIND_NEVER",
    "NEGATION_KIND_NOT_YET",
    "NEGATION_KIND_SCOPE_AMBIGUOUS",
    "NEGATION_KIND_SIMPLE",
    "NEGATION_WINDOW",
    "NEVER_CUES",
    "NOT_YET_PHRASES",
    "SCOPE_VERBS",
    "ContextVerdict",
    "FactivityAction",
    "FactivityResult",
    "NegationVerdict",
    "analyze_context",
    "analyze_raw_text",
    "classify_negation",
    "clause_start",
    "scope_negation",
]
