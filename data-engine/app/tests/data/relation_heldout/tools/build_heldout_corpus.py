# -*- coding: utf-8 -*-
"""Generador DETERMINISTA del corpus HELD-OUT de relaciones (H1).

Escribe `sources/*.txt`, `ground_truth/relations.json`, `cases/cases.json` y
`manifest.json` en el directorio del corpus. Es la herramienta de *sellado*: la
regeneracion debe producir EXACTAMENTE los mismos sha256. Si un cambio mueve un
hash, el corpus ha cambiado y exige una VERSION NUEVA (ver HELDOUT_POLICY.md).

Todo el contenido es FICTICIO e INVENTADO para este corpus. No contiene material
con derechos de autor, ni datos personales, ni transcripciones de partidas
reales, ni rutas absolutas, ni secretos.

Uso:
    PYTHONDONTWRITEBYTECODE=1 python3 tools/build_heldout_corpus.py

NO ejecuta el motor, NO abre red, NO escribe fuera del directorio del corpus.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent.parent
CORPUS_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Sentinelas de predicado
# ---------------------------------------------------------------------------
# NO_RELATION: el par de entidades COEXISTE en el texto pero NO hay relacion
#   alguna entre ellas (charla de mesa, ruido). Ningun predicado es correcto:
#   por construccion el motor NO puede acertar el predicado de estas filas, y
#   eso es intencionado (mide que el motor NO deberia afirmar nada). Se reportan
#   siempre por separado (ver HELDOUT_POLICY.md §6).
# SPONSORS / EXONERATED_BY: predicados que NO existen en la ontologia del motor.
#   Miden cobertura, no habilidad: tambien son inacertables por construccion.

# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
# Cada relacion: (segmento, sujeto, predicado, objeto, evidencia, ...).
# `ev_n` = ocurrencia (1-based) de la evidencia literal dentro del texto.


def R(seg, s, p, o, ev, *, ev_n=1, neg=False, temp="PRESENT", epi="ASSERTED",
      dirn="SUBJECT_TO_OBJECT", dec="ACCEPT", note="", case="", episode=""):
    return {
        "seg": seg, "s": s, "p": p, "o": o, "ev": ev, "ev_n": ev_n,
        "neg": neg, "temp": temp, "epi": epi, "dir": dirn, "dec": dec,
        "note": note, "case": case, "episode": episode,
    }


C = "Character"
F = "Faction"
L = "Location"
O = "Object"
E = "Event"
K = "Concept"

# Entidades (id, texto de mencion, tipo)
odalys = ("odalys", "Odalys", C)
mirek = ("mirek", "Mirek", C)
tessaly = ("tessaly", "Tessaly", C)
bricio = ("bricio", "Bricio", C)
rutger = ("rutger", "Rutger", C)
ximena = ("ximena", "Ximena", C)
nauel = ("nauel", "Nauel", C)
halvard_fv = ("halvard-ferrovia", "Halvard", C)
halvard_mr = ("halvard-mareas", "Halvard", C)
corvala = ("corvala", "Corvala", C)
duna = ("duna", "Duná", C)
ferran = ("ferran", "Ferrán", C)
ianthe = ("ianthe", "Ianthe", C)
zayd = ("zayd", "Zayd", C)

yunque = ("yunque-frio", "Compañía del Yunque Frío", F)
turmalina = ("sindicato-turmalina", "Sindicato Turmalina", F)
salobre = ("legion-salobre", "Legión Salobre", F)
faros = ("cofradia-faros", "Cofradía de Faros", F)
quebranto_casa = ("casa-quebranto", "Casa Quebranto", F)
hollin = ("hermandad-hollin", "Hermandad del Hollín", F)
armada = ("armada-salitre", "Armada Salitre", F)
mareal = ("casa-mareal", "Casa Mareal", F)
vortice = ("consorcio-vortice", "Consorcio Vórtice", F)

ciudadela = ("ciudadela-estano", "Ciudadela de Estaño", L)
vega = ("vega-tulm", "Vega de Tulm", L)
meseta = ("meseta-ocre", "Meseta Ocre", L)
astillero = ("astillero-bajo", "Astillero Bajo", L)
mina = ("mina-quebranto", "Mina Quebranto", L)
fondeadero = ("fondeadero-malva", "Fondeadero Malva", L)
okeanos = ("okeanos", "Ὠκεανός", L)

yelmo = ("yelmo-turmalina", "Yelmo de Turmalina", O)
brujula = ("brujula-sal", "Brújula de Sal", O)
diario = ("diario-odalys", "diario de Odalys", O)
lanza = ("lanza-nictalope", "Lanza Nictálope", O)
zarya = ("zarya-7", "Заря-7", O)

motin = ("motin-estano", "Motín de Estaño", E)
descarrilamiento = ("descarrilamiento", "descarrilamiento del correo nocturno", E)
colapso = ("colapso-presa", "Colapso de la Presa", E)
asamblea = ("asamblea-mareas", "Asamblea de Mareas", E)

FV = "ferrovia"
MR = "mareas"
OR_ = "orbita"

SOURCES: list[dict] = []


def S(sid, fname, title, ws, text, relations):
    SOURCES.append({"id": sid, "file": fname, "title": title,
                    "workspace": ws, "text": text, "relations": relations})


# --- H-01 · alianza que termina y se vuelve enemistad -----------------------
S("src-01", "src-01-pacto-roto.txt", "El pacto del primer invierno", FV,
  "Durante el primer invierno la Compañía del Yunque Frío y el Sindicato Turmalina "
  "rubricaron un pacto de defensa mutua. Tres estaciones más tarde el pacto quedó "
  "sin efecto. Desde aquel día la Compañía del Yunque Frío hostiga sin descanso al "
  "Sindicato Turmalina.\n",
  [
      R("src-01#s1", yunque, "ALLIED_WITH", turmalina,
        "la Compañía del Yunque Frío y el Sindicato Turmalina rubricaron un pacto de defensa mutua",
        temp="ENDED", dirn="UNDIRECTED", dec="ACCEPT",
        note="Alianza simetrica que TERMINA: el mismo par vuelve a aparecer como enemistad.",
        case="H-01", episode="ses-01"),
      R("src-01#s3", yunque, "ENEMY_OF", turmalina,
        "la Compañía del Yunque Frío hostiga sin descanso al Sindicato Turmalina",
        temp="ONGOING", dirn="UNDIRECTED", dec="ACCEPT",
        note="Enemistad simetrica VIGENTE que sustituye a la alianza anterior.",
        case="H-01", episode="ses-01"),
  ])

# --- H-02 · voz pasiva + sujeto/objeto invertidos ---------------------------
S("src-02", "src-02-voz-pasiva.txt", "Actas de fundación y custodia", FV,
  "La Ciudadela de Estaño fue fundada por Odalys mucho antes de que el ferrocarril "
  "llegara a la Meseta Ocre. El Yelmo de Turmalina fue velado durante décadas por la "
  "Compañía del Yunque Frío.\n",
  [
      R("src-02#s1", odalys, "FOUNDED", ciudadela,
        "La Ciudadela de Estaño fue fundada por Odalys",
        temp="PAST", note="Voz pasiva: el objeto semantico aparece ANTES que el sujeto.",
        case="H-02", episode="ses-01"),
      R("src-02#s2", yunque, "GUARDS", yelmo,
        "El Yelmo de Turmalina fue velado durante décadas por la Compañía del Yunque Frío",
        temp="PAST", note="Voz pasiva con complemento agente al final de la oracion.",
        case="H-02", episode="ses-01"),
  ])

# --- H-03 · rumor (sesión 4) ------------------------------------------------
S("src-03", "src-03-rumor-taller.txt", "Lo que se murmura en los talleres", FV,
  "En los talleres se murmura que Mirek figura en el censo del Sindicato Turmalina. "
  "Nadie ha enseñado jamás un papel que lo sostenga.\n",
  [
      R("src-03#s1", mirek, "MEMBER_OF", turmalina,
        "Mirek figura en el censo del Sindicato Turmalina",
        temp="PRESENT", epi="RUMORED", dec="REVIEW",
        note="Rumor sin fuente: nunca llega a ser hecho (ver src-04).",
        case="H-03", episode="ses-04"),
  ])

# --- H-04 · el rumor NO se confirma (sesión 9) + negación -------------------
S("src-04", "src-04-rumor-desmentido.txt", "Cinco sesiones después", FV,
  "Cinco sesiones después el asunto sigue igual: Mirek no aparece en el censo del "
  "Sindicato Turmalina, y el archivero lo confirmó por escrito.\n",
  [
      R("src-04#s1", mirek, "MEMBER_OF", turmalina,
        "Mirek no aparece en el censo del Sindicato Turmalina",
        temp="PRESENT", neg=True, dec="REJECT",
        note="Negacion explicita: el rumor de src-03 no cuaja nunca.",
        case="H-03", episode="ses-09"),
  ])

# --- H-05 · culpable aparente (sesión 2) ------------------------------------
S("src-05", "src-05-culpable-aparente.txt", "El correo nocturno", FV,
  "Tres testigos señalaron a Rutger como responsable del descarrilamiento del correo "
  "nocturno. El juez de vía lo detuvo esa misma noche en la Vega de Tulm.\n",
  [
      R("src-05#s1", rutger, "CAUSED", descarrilamiento,
        "Rutger como responsable del descarrilamiento del correo nocturno",
        temp="PAST", dec="REVIEW",
        note="Culpabilidad APARENTE apoyada solo en testigos: revision humana, no aceptacion.",
        case="H-04", episode="ses-02"),
  ])

# --- H-06 · exoneración posterior (sesión 6) --------------------------------
S("src-06", "src-06-exoneracion.txt", "El peritaje del eje", FV,
  "El peritaje del eje cerró el caso: Rutger no provocó el descarrilamiento del correo "
  "nocturno. La Legión Salobre había limado los pernos la víspera.\n",
  [
      R("src-06#s1", rutger, "CAUSED", descarrilamiento,
        "Rutger no provocó el descarrilamiento del correo nocturno",
        temp="PAST", neg=True, dec="REJECT",
        note="Exoneracion: la atribucion de src-05 queda desmentida por un peritaje.",
        case="H-04", episode="ses-06"),
      R("src-06#s2", salobre, "CAUSED", descarrilamiento,
        "La Legión Salobre había limado los pernos",
        temp="PAST", dec="ACCEPT",
        note="La causa real aparece en la misma escena que la exoneracion.",
        case="H-04", episode="ses-06"),
  ])

# --- H-07 · salto de tres meses + relación que cambia -----------------------
S("src-07", "src-07-salto-tres-meses.txt", "Tres meses después", FV,
  "Tres meses después de la última escena, Tessaly ya no encabeza la Cofradía de Faros. "
  "Hoy es Bricio quien encabeza la Cofradía de Faros.\n",
  [
      R("src-07#s1", tessaly, "LEADS", faros,
        "Tessaly ya no encabeza la Cofradía de Faros",
        temp="ENDED", neg=True, dec="REJECT",
        note="Salto temporal explicito de tres meses; el mando ANTERIOR ya no esta vigente.",
        case="H-05", episode="ses-11"),
      R("src-07#s2", bricio, "LEADS", faros,
        "Bricio quien encabeza la Cofradía de Faros",
        temp="PRESENT", dec="ACCEPT",
        note="Mando VIGENTE tras el relevo.",
        case="H-05", episode="ses-11"),
  ])

# --- H-08 · flashback -------------------------------------------------------
S("src-08", "src-08-flashback.txt", "Flashback: la sala de diagramas", FV,
  "Retrocedemos muchos años, a una época anterior al Motín de Estaño. En aquella sala "
  "Odalys instruyó a Tessaly en la lectura de diagramas, y Tessaly tomó parte en el "
  "Motín de Estaño mucho más tarde.\n",
  [
      R("src-08#s2", odalys, "MENTOR_OF", tessaly,
        "Odalys instruyó a Tessaly en la lectura de diagramas",
        temp="PAST", dec="ACCEPT",
        note="Flashback: la relacion es pasada aunque se narre en el presente de la mesa.",
        case="H-06", episode="ses-12"),
      R("src-08#s2", tessaly, "PARTICIPATED_IN", motin,
        "Tessaly tomó parte en el Motín de Estaño",
        temp="PAST", dec="ACCEPT",
        note="Dentro del mismo flashback conviven dos marcos temporales distintos.",
        case="H-06", episode="ses-12"),
  ])

# --- H-09 · conversación no relacionada (ruido) -----------------------------
S("src-09", "src-09-charla-mesa.txt", "Charla de mesa", FV,
  "—¿Alguien ha visto mi dado de ocho? —preguntó Ximena mientras rebuscaba bajo la silla. "
  "Nauel contestó que no y siguió repartiendo pizza. Nadie estaba jugando ya.\n",
  [
      R("src-09#s1", ximena, "NO_RELATION", nauel,
        "preguntó Ximena mientras rebuscaba bajo la silla. Nauel contestó que no",
        temp="ATEMPORAL", dec="REJECT",
        note="RUIDO: dos personas coexisten en la charla, pero NO hay relacion de mundo. "
             "Ningun predicado es correcto por construccion.",
        case="H-07", episode="ses-13"),
  ])

# --- H-10 · mismo nombre en dos workspaces (1/2) ----------------------------
S("src-10", "src-10-halvard-ferrovia.txt", "Halvard, el de las vías", FV,
  "Halvard responde ante la Hermandad del Hollín desde que aprendió el oficio. Halvard "
  "no ha pisado nunca el mar.\n",
  [
      R("src-10#s1", halvard_fv, "MEMBER_OF", hollin,
        "Halvard responde ante la Hermandad del Hollín",
        temp="ONGOING", dec="ACCEPT",
        note="Homonimia entre workspaces: este Halvard es 'halvard-ferrovia'.",
        case="H-08", episode="ses-03"),
  ])

# --- H-11 · mismo nombre en dos workspaces (2/2) ----------------------------
S("src-11", "src-11-halvard-mareas.txt", "Halvard, el del Fondeadero", MR,
  "En el Fondeadero Malva, Halvard cuida del faro por encargo de la Armada Salitre. "
  "Este Halvard jamás ha visto una locomotora.\n",
  [
      R("src-11#s1", halvard_mr, "MEMBER_OF", armada,
        "Halvard cuida del faro por encargo de la Armada Salitre",
        temp="ONGOING", dec="ACCEPT",
        note="Homonimia: mismo nombre, workspace distinto, entidad DISTINTA "
             "('halvard-mareas'). No debe fusionarse con src-10.",
        case="H-08", episode="ses-03"),
      R("src-11#s1", halvard_mr, "LIVES_IN", fondeadero,
        "En el Fondeadero Malva, Halvard cuida del faro",
        temp="ONGOING", dirn="SUBJECT_TO_OBJECT", dec="ACCEPT",
        note="Residencia inferida del encargo; el lugar precede al sujeto en el texto.",
        case="H-08", episode="ses-03"),
  ])

# --- H-12 · Unicode y puntuación --------------------------------------------
S("src-12", "src-12-unicode.txt", "Bitácora de la Заря-7", OR_,
  "«La Заря-7 —anotó Ianthe— quedó amarrada en Ὠκεανός…» El Consorcio Vórtice reclamó "
  "la Заря-7 como propiedad suya; Zayd, en cambio, se limitó a callar.\n",
  [
      R("src-12#s1", zarya, "LOCATED_IN", okeanos,
        "La Заря-7 —anotó Ianthe— quedó amarrada en Ὠκεανός",
        temp="PAST", dec="ACCEPT",
        note="Cirilico + griego + comillas latinas + raya + puntos suspensivos en la evidencia.",
        case="H-09", episode="ses-21"),
      R("src-12#s2", vortice, "OWNS", zarya,
        "El Consorcio Vórtice reclamó la Заря-7 como propiedad suya",
        temp="PRESENT", dec="REVIEW",
        note="Reclamacion de propiedad, no propiedad probada: revision.",
        case="H-09", episode="ses-21"),
  ])

# --- H-13 · texto repetido ---------------------------------------------------
S("src-13", "src-13-texto-repetido.txt", "El acta que se copió dos veces", MR,
  "Corvala vela por la Brújula de Sal. Corvala vela por la Brújula de Sal. El escribano "
  "copió el renglón dos veces por error.\n",
  [
      R("src-13#s1", corvala, "GUARDS", brujula,
        "Corvala vela por la Brújula de Sal",
        ev_n=1, temp="ONGOING", dec="ACCEPT",
        note="Frase DUPLICADA literalmente: debe producir UNA relacion, no dos. "
             "La evidencia esperada es la PRIMERA ocurrencia.",
        case="H-10", episode="ses-22"),
  ])

# --- H-14 · frase muy larga --------------------------------------------------
S("src-14", "src-14-frase-larga.txt", "Informe extenso del Astillero Bajo", MR,
  "Aunque el informe del inspector, redactado tras catorce jornadas de inventario en "
  "los muelles y revisado por dos escribanos que discreparon sobre casi todo, dedica "
  "páginas enteras a la humedad de los almacenes, al precio de la brea y a la falta de "
  "cuerda de cáñamo, lo único que importa para la crónica es que la Casa Mareal "
  "administra el Astillero Bajo desde la temporada pasada.\n",
  [
      R("src-14#s1", mareal, "OWNS", astillero,
        "la Casa Mareal administra el Astillero Bajo",
        temp="ONGOING", dec="ACCEPT",
        note="La unica relacion aparece al final de una oracion muy larga con "
             "subordinadas y enumeraciones que no aportan relaciones.",
        case="H-11", episode="ses-23"),
  ])

# --- H-15 · fragmento ambiguo ------------------------------------------------
S("src-15", "src-15-fragmento-ambiguo.txt", "Fragmento ambiguo", MR,
  "Duná se sentó junto a Ferrán. Ella dijo que la Casa Mareal la había expulsado, "
  "aunque no quedó claro a quién se refería.\n",
  [
      R("src-15#s2", duna, "MEMBER_OF", mareal,
        "la Casa Mareal la había expulsado",
        temp="ENDED", neg=True, dec="REVIEW",
        note="Pronombre AMBIGUO ('la'): el referente puede ser Duná o Ferrán. "
             "La anotacion humana deja la resolucion en REVIEW a proposito.",
        case="H-12", episode="ses-23"),
  ])

# --- H-16 · hipótesis de jugador ---------------------------------------------
S("src-16", "src-16-hipotesis-jugador.txt", "Teoría del jugador de Bricio", FV,
  "El jugador de Bricio lanzó su teoría en voz alta: si Odalys fuese la madre de Bricio, "
  "la herencia de la Ciudadela de Estaño cuadraría. Nadie en la ficción ha dicho tal cosa.\n",
  [
      R("src-16#s1", odalys, "PARENT_OF", bricio,
        "si Odalys fuese la madre de Bricio",
        temp="PRESENT", epi="HYPOTHETICAL", dec="REJECT",
        note="HIPOTESIS DE JUGADOR (fuera de ficcion): no debe entrar al grafo.",
        case="H-13", episode="ses-14"),
  ])

# --- H-17 · fecha vaga -------------------------------------------------------
S("src-17", "src-17-fecha-vaga.txt", "En algún momento del último ciclo", FV,
  "En algún momento del último ciclo, quizá antes de las lluvias, Ximena pasó a formar "
  "parte de la Legión Salobre.\n",
  [
      R("src-17#s1", ximena, "MEMBER_OF", salobre,
        "Ximena pasó a formar parte de la Legión Salobre",
        temp="PAST", dec="REVIEW",
        note="FECHA VAGA ('en algun momento del ultimo ciclo, quiza antes de las lluvias'): "
             "hay marca temporal pero no fecha; el pasado es la clase esperada.",
        case="H-14", episode="ses-15"),
  ])

# --- H-18 · predicado desconocido para la ontología --------------------------
S("src-18", "src-18-predicado-desconocido.txt", "Mecenazgo", FV,
  "Nauel apadrina desde hace años a la Casa Quebranto y le paga los carbones.\n",
  [
      R("src-18#s1", nauel, "SPONSORS", quebranto_casa,
        "Nauel apadrina desde hace años a la Casa Quebranto",
        temp="ONGOING", dec="ACCEPT",
        note="PREDICADO DESCONOCIDO: 'SPONSORS' no existe en la ontologia del motor. "
             "Mide COBERTURA, no habilidad: es inacertable por construccion.",
        case="H-15", episode="ses-16"),
  ])

# --- H-19 · descubrimiento posterior de un evento antiguo --------------------
S("src-19", "src-19-descubrimiento-antiguo.txt", "Lo que dormía en los archivos", FV,
  "Doscientos años después alguien abrió por fin el legajo: la Hermandad del Hollín "
  "estuvo detrás del Colapso de la Presa. Nadie lo sabía hasta esta sesión.\n",
  [
      R("src-19#s1", hollin, "CAUSED", colapso,
        "la Hermandad del Hollín estuvo detrás del Colapso de la Presa",
        temp="PAST", dec="ACCEPT",
        note="DESCUBRIMIENTO POSTERIOR: el hecho es antiquisimo, el conocimiento es de hoy. "
             "El estado temporal esperado es el del HECHO (PAST), no el del hallazgo.",
        case="H-16", episode="ses-24"),
  ])

# --- H-20 · confirmación por dos fuentes (1/2) -------------------------------
S("src-20", "src-20-confirmacion-a.txt", "Registro portuario", MR,
  "El registro portuario deja constancia de que Ferrán encabeza la Armada Salitre.\n",
  [
      R("src-20#s1", ferran, "LEADS", armada,
        "Ferrán encabeza la Armada Salitre",
        temp="PRESENT", dec="ACCEPT",
        note="Primera de DOS fuentes independientes que afirman lo mismo.",
        case="H-17", episode="ses-25"),
  ])

# --- H-21 · confirmación por dos fuentes (2/2) -------------------------------
S("src-21", "src-21-confirmacion-b.txt", "Carta del cónsul", MR,
  "El cónsul escribe en su carta que quien manda hoy en la Armada Salitre es Ferrán, "
  "y añade que lo ha visto firmar las órdenes.\n",
  [
      R("src-21#s1", ferran, "LEADS", armada,
        "quien manda hoy en la Armada Salitre es Ferrán",
        temp="PRESENT", dec="ACCEPT",
        note="Segunda fuente INDEPENDIENTE con orden sujeto/objeto INVERTIDO respecto a src-20.",
        case="H-17", episode="ses-26"),
  ])

# --- H-22 · relación contradicha por otra fuente -----------------------------
S("src-22", "src-22-contradiccion.txt", "El desmentido del contramaestre", MR,
  "El contramaestre lo niega de plano: Ferrán no manda en la Armada Salitre, sino que "
  "obedece a Corvala.\n",
  [
      R("src-22#s1", ferran, "LEADS", armada,
        "Ferrán no manda en la Armada Salitre",
        temp="PRESENT", neg=True, dec="REVIEW",
        note="CONTRADICCION frontal con src-20/src-21. Con dos fuentes a favor y una en "
             "contra, la anotacion humana es REVIEW, no REJECT.",
        case="H-18", episode="ses-27"),
      R("src-22#s1", corvala, "LEADS", ferran,
        "obedece a Corvala",
        temp="PRESENT", dec="REVIEW",
        note="Cadena de mando alternativa afirmada por la misma fuente contradictoria.",
        case="H-18", episode="ses-27"),
  ])

# --- H-23 · fuente retirada ---------------------------------------------------
S("src-23", "src-23-fuente-retirada.txt", "Fuente retirada del canon", FV,
  "AVISO DEL DIRECTOR DE JUEGO: el diario de Odalys queda retirado del canon. Lo que allí "
  "se leía —que Odalys poseía la Lanza Nictálope— deja de valer.\n",
  [
      R("src-23#s2", odalys, "OWNS", lanza,
        "Odalys poseía la Lanza Nictálope",
        temp="ENDED", epi="RUMORED", dec="REJECT",
        note="FUENTE RETIRADA: el enunciado existe en el texto pero su fuente fue "
             "descanonizada. Debe rechazarse aunque la frase parezca asertiva.",
        case="H-19", episode="ses-17"),
  ])

# --- H-24 · escena en varias sesiones (1/2) ----------------------------------
S("src-24", "src-24-asamblea-parte-1.txt", "Asamblea de Mareas, primera parte", MR,
  "La Asamblea de Mareas se abrió al anochecer. Corvala tomó parte en la Asamblea de "
  "Mareas desde el primer momento; la sesión terminó sin que se votara nada.\n",
  [
      R("src-24#s1", corvala, "PARTICIPATED_IN", asamblea,
        "Corvala tomó parte en la Asamblea de Mareas",
        temp="PAST", dec="ACCEPT",
        note="ESCENA PARTIDA: primera mitad, la misma escena continua en src-25.",
        case="H-20", episode="ses-28"),
  ])

# --- H-25 · escena en varias sesiones (2/2) ----------------------------------
S("src-25", "src-25-asamblea-parte-2.txt", "Asamblea de Mareas, segunda parte", MR,
  "Continuamos donde lo dejamos. En la misma Asamblea de Mareas, ya de madrugada, Duná "
  "tomó parte en la Asamblea de Mareas y arrancó a la Casa Mareal el voto que faltaba.\n",
  [
      R("src-25#s2", duna, "PARTICIPATED_IN", asamblea,
        "Duná tomó parte en la Asamblea de Mareas",
        temp="PAST", dec="ACCEPT",
        note="ESCENA PARTIDA: segunda mitad, misma escena que src-24, sesion distinta.",
        case="H-20", episode="ses-29"),
      R("src-25#s2", duna, "MEMBER_OF", mareal,
        "arrancó a la Casa Mareal el voto que faltaba",
        temp="PAST", dec="REJECT",
        note="TRAMPA de coocurrencia: arrancar un voto NO implica pertenencia. "
             "El par existe en el texto pero la relacion de pertenencia es falsa.",
        case="H-20", episode="ses-29"),
  ])

# --- H-26 · entidades repetidas + varias relaciones por segmento -------------
S("src-26", "src-26-entidades-repetidas.txt", "Retrato de Tessaly", FV,
  "Tessaly nació en la Meseta Ocre. Tessaly guarda la Brújula de Sal de su madre. "
  "Tessaly conoce a Rutger desde niña y Tessaly se fía de Rutger más que de nadie. "
  "Tessaly vuelve cada verano a la Meseta Ocre.\n",
  [
      R("src-26#s1", tessaly, "LIVES_IN", meseta,
        "Tessaly nació en la Meseta Ocre",
        temp="PAST", dec="REVIEW",
        note="Nacer en un sitio no equivale a residir: revision humana.",
        case="H-21", episode="ses-18"),
      R("src-26#s2", tessaly, "OWNS", brujula,
        "Tessaly guarda la Brújula de Sal de su madre",
        temp="PRESENT", dec="ACCEPT",
        note="Entidad repetida 5 veces en la fuente; multiples relaciones por segmento.",
        case="H-21", episode="ses-18"),
      R("src-26#s3", tessaly, "KNOWS", rutger,
        "Tessaly conoce a Rutger desde niña",
        temp="ONGOING", dec="ACCEPT",
        note="Predicado dirigido segun el GT (KNOWS no es simetrico en la ontologia).",
        case="H-21", episode="ses-18"),
  ])

# --- H-27 · familia en voz activa, varias relaciones -------------------------
S("src-27", "src-27-familia.txt", "La familia de Nauel", FV,
  "Nauel desposó a Ximena en la Vega de Tulm. De aquel matrimonio vino Bricio. Nauel "
  "comparte sangre con Rutger: son hermanos de padre.\n",
  [
      R("src-27#s1", nauel, "MARRIED_TO", ximena,
        "Nauel desposó a Ximena",
        temp="PAST", dirn="UNDIRECTED", dec="ACCEPT",
        note="Relacion SIMETRICA en voz activa.",
        case="H-22", episode="ses-19"),
      R("src-27#s2", nauel, "PARENT_OF", bricio,
        "De aquel matrimonio vino Bricio",
        temp="PAST", dec="REVIEW",
        note="Filiacion IMPLICITA (elipsis del progenitor): revision humana.",
        case="H-22", episode="ses-19"),
      R("src-27#s3", nauel, "SIBLING_OF", rutger,
        "Nauel comparte sangre con Rutger: son hermanos de padre",
        temp="ATEMPORAL", dirn="UNDIRECTED", dec="ACCEPT",
        note="Simetrica, expresada sin el verbo habitual ('ser hermano de').",
        case="H-22", episode="ses-19"),
  ])

# --- H-28 · intención futura --------------------------------------------------
S("src-28", "src-28-intencion-futura.txt", "Planes para la primavera", FV,
  "Bricio ha dicho que en primavera piensa alistarse en la Legión Salobre, aunque de "
  "momento no ha firmado nada.\n",
  [
      R("src-28#s1", bricio, "MEMBER_OF", salobre,
        "en primavera piensa alistarse en la Legión Salobre",
        temp="FUTURE", epi="INTENDED", dec="REVIEW",
        note="INTENCION en futuro, no hecho: transicion temporal hacia adelante.",
        case="H-23", episode="ses-19"),
  ])

# --- H-29 · alias ------------------------------------------------------------
S("src-29", "src-29-alias.txt", "El Fogonero", FV,
  "En la Mina Quebranto a Rutger lo llaman el Fogonero, y con ese apodo firma los partes.\n",
  [
      R("src-29#s1", rutger, "ALIAS_OF", ("el-fogonero", "el Fogonero", C),
        "a Rutger lo llaman el Fogonero",
        temp="ATEMPORAL", dirn="UNDIRECTED", dec="ACCEPT",
        note="Alias simetrico entre una entidad y su apodo.",
        case="H-24", episode="ses-20"),
      R("src-29#s1", rutger, "LOCATED_IN", mina,
        "En la Mina Quebranto a Rutger lo llaman el Fogonero",
        temp="PRESENT", dec="REVIEW",
        note="Localizacion DEBIL: el lugar es escenario del apodo, no residencia probada.",
        case="H-24", episode="ses-20"),
  ])

# --- H-30 · ruido puro, segundo caso -----------------------------------------
S("src-30", "src-30-ruido-reglas.txt", "Discusión de reglas", OR_,
  "—Ianthe, ¿la Заря-7 cuenta como vehículo pesado para el modificador? —Zayd abrió el "
  "manual y se puso a discutir la tabla de la página 88 durante veinte minutos.\n",
  [
      R("src-30#s1", ianthe, "NO_RELATION", zayd,
        "Ianthe, ¿la Заря-7 cuenta como vehículo pesado para el modificador? —Zayd abrió el manual",
        temp="ATEMPORAL", dec="REJECT",
        note="RUIDO: discusion de reglas fuera de ficcion. Ninguna relacion de mundo.",
        case="H-07", episode="ses-30"),
      R("src-30#s1", ianthe, "NO_RELATION", zarya,
        "la Заря-7 cuenta como vehículo pesado",
        temp="ATEMPORAL", dec="REJECT",
        note="RUIDO: mencion de una entidad dentro de una pregunta de reglas.",
        case="H-07", episode="ses-30"),
  ])


# ---------------------------------------------------------------------------
# Casos (metadatos fuera del ground truth para no alterar su contrato)
# ---------------------------------------------------------------------------
CASES = [
    ("H-01", "Alianza que termina y se vuelve enemistad",
     ["alianza-terminada", "relacion-que-cambia", "simetrica", "transicion-temporal",
      "varias-relaciones-por-segmento", "voz-activa"]),
    ("H-02", "Voz pasiva con sujeto y objeto invertidos",
     ["voz-pasiva", "sujeto-objeto-invertidos"]),
    ("H-03", "Rumor que nunca se vuelve hecho",
     ["rumor", "negacion", "fuentes-en-sesiones-distintas"]),
    ("H-04", "Culpable aparente exonerado despues",
     ["culpable-exonerado", "negacion", "relacion-que-cambia", "fuentes-contradictorias"]),
    ("H-05", "Salto de tres meses y relevo de mando",
     ["salto-temporal", "relacion-que-cambia", "negacion"]),
    ("H-06", "Flashback con dos marcos temporales",
     ["flashback", "transicion-temporal", "varias-relaciones-por-segmento"]),
    ("H-07", "Conversacion no relacionada (ruido)",
     ["ruido", "sin-relacion", "puntuacion"]),
    ("H-08", "Mismo nombre en dos workspaces",
     ["homonimia", "multi-workspace"]),
    ("H-09", "Unicode y puntuacion",
     ["unicode", "puntuacion"]),
    ("H-10", "Texto repetido literalmente",
     ["texto-repetido", "offsets"]),
    ("H-11", "Frase muy larga con una sola relacion",
     ["frases-largas"]),
    ("H-12", "Fragmento ambiguo con pronombre sin referente claro",
     ["fragmento-ambiguo", "negacion"]),
    ("H-13", "Hipotesis de jugador fuera de ficcion",
     ["hipotesis", "fuera-de-ficcion"]),
    ("H-14", "Fecha vaga",
     ["fecha-vaga", "transicion-temporal"]),
    ("H-15", "Predicado desconocido para la ontologia",
     ["predicado-desconocido", "cobertura"]),
    ("H-16", "Descubrimiento posterior de un evento antiguo",
     ["descubrimiento-posterior", "transicion-temporal"]),
    ("H-17", "Relacion confirmada por dos fuentes independientes",
     ["dos-fuentes", "sujeto-objeto-invertidos"]),
    ("H-18", "Relacion contradicha por una tercera fuente",
     ["fuentes-contradictorias", "negacion"]),
    ("H-19", "Fuente retirada del canon",
     ["fuente-retirada"]),
    ("H-20", "Escena que ocupa varias sesiones",
     ["escena-multi-sesion", "coocurrencia-enganosa"]),
    ("H-21", "Entidades repetidas y varias relaciones por segmento",
     ["entidades-repetidas", "varias-relaciones-por-segmento", "predicados-no-vistos"]),
    ("H-22", "Familia en voz activa con relaciones simetricas",
     ["voz-activa", "simetrica", "varias-relaciones-por-segmento"]),
    ("H-23", "Intencion futura no consumada",
     ["intencion", "futuro"]),
    ("H-24", "Alias y localizacion debil",
     ["alias", "simetrica", "localizacion-debil"]),
]


# ---------------------------------------------------------------------------
# Construccion
# ---------------------------------------------------------------------------
def build() -> None:
    sources_dir = CORPUS_DIR / "sources"
    gt_dir = CORPUS_DIR / "ground_truth"
    cases_dir = CORPUS_DIR / "cases"

    relations: list[dict] = []
    manifest_sources: list[dict] = []
    case_index: dict[str, dict] = {cid: {"case_id": cid, "title": t, "coverage": cov,
                                         "sources": [], "episodes": [], "relations": []}
                                   for cid, t, cov in CASES}
    n = 0
    for src in SOURCES:
        text = src["text"]
        path = sources_dir / src["file"]
        path.write_text(text, encoding="utf-8")
        data = path.read_bytes()
        manifest_sources.append({
            "id": src["id"],
            "path": f"sources/{src['file']}",
            "title": src["title"],
            "workspace": src["workspace"],
            "encoding": "utf-8",
            "bytes": len(data),
            "chars": len(text),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
        for rel in src["relations"]:
            n += 1
            ev = rel["ev"]
            start = -1
            pos = 0
            for _ in range(rel["ev_n"]):
                start = text.find(ev, pos)
                if start < 0:
                    raise SystemExit(
                        f"evidencia no encontrada en {src['id']}: {ev!r}")
                pos = start + 1
            end = start + len(ev)
            assert text[start:end] == ev
            sid, stext, stype = rel["s"]
            oid, otext, otype = rel["o"]
            for mention in (stext, otext):
                if mention not in text:
                    raise SystemExit(
                        f"mencion no encontrada en {src['id']}: {mention!r}")
            rid = f"rel-{n:03d}"
            relations.append({
                "relation_id": rid,
                "source_id": src["id"],
                "workspace": src["workspace"],
                "segment_id": rel["seg"],
                "subject_id": sid,
                "subject_text": stext,
                "subject_type": stype,
                "predicate": rel["p"],
                "object_id": oid,
                "object_text": otext,
                "object_type": otype,
                "evidence_text": ev,
                "evidence_start": start,
                "evidence_end": end,
                "negated": rel["neg"],
                "temporal_status": rel["temp"],
                "epistemic_status": rel["epi"],
                "direction": rel["dir"],
                "expected_decision": rel["dec"],
                "annotator_notes": rel["note"],
            })
            c = case_index[rel["case"]]
            c["relations"].append(rid)
            if src["id"] not in c["sources"]:
                c["sources"].append(src["id"])
            if rel["episode"] not in c["episodes"]:
                c["episodes"].append(rel["episode"])

    ground_truth = {
        "corpus_version": CORPUS_VERSION,
        "description": (
            "Ground truth del corpus HELD-OUT de relaciones (H1). Sintetico e "
            "inventado. Anotacion de un solo pase con notas explicitas por relacion. "
            "NO se usa para escribir reglas ni para ajustar expresiones del motor: "
            "ver docs/relation-engine-v2e/HELDOUT_POLICY.md."
        ),
        "temporal_status_values": ["PAST", "PRESENT", "FUTURE", "ONGOING", "ENDED", "ATEMPORAL"],
        "expected_decision_values": ["ACCEPT", "REJECT", "REVIEW"],
        "relations": relations,
    }
    gt_path = gt_dir / "relations.json"
    gt_path.write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2,
                                  sort_keys=False) + "\n", encoding="utf-8")

    cases_doc = {
        "corpus_version": CORPUS_VERSION,
        "description": (
            "Indice de CASOS del corpus held-out: cada caso agrupa fuentes, episodios "
            "(sesiones de juego ficticias) y relaciones esperadas. Este fichero es "
            "METADATO: el arnes `relations/benchmark/` no lo lee."
        ),
        "cases": [case_index[cid] for cid, _, _ in CASES],
    }
    cases_path = cases_dir / "cases.json"
    cases_path.write_text(json.dumps(cases_doc, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    workspaces = sorted({s["workspace"] for s in SOURCES})
    manifest = {
        "corpus": "relation-benchmark",
        "corpus_role": "held-out",
        "version": CORPUS_VERSION,
        "synthetic": True,
        "contains_private_corpus": False,
        "workspaces": workspaces,
        "encoding": "utf-8",
        "source_count": len(SOURCES),
        "relation_count": len(relations),
        "sources": manifest_sources,
        "ground_truth": {
            "path": "ground_truth/relations.json",
            "sha256": hashlib.sha256(gt_path.read_bytes()).hexdigest(),
        },
        "cases": {
            "path": "cases/cases.json",
            "sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        },
    }
    (CORPUS_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"fuentes={len(SOURCES)} relaciones={len(relations)} casos={len(CASES)} "
          f"workspaces={','.join(workspaces)}")


if __name__ == "__main__":
    build()
