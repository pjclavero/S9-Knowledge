# -*- coding: utf-8 -*-
"""ACUERDO-2: corpus de evaluacion NUEVO para la medicion del acuerdo
determinista <> NVIDIA (bloque ACUERDO-2, docs/v3/48).

Escrito para ampliar el n=56 del gold `negation` (demasiado pequeno: mismo
techo dev==test que ya engano al motor v2, ver
project_s9k_motor_v2e_heldout). Frases y entidades NUEVAS: tres mundos
("vitral", "salitre", "brumal") que no existen en NINGUN otro corpus del
repo (ni `negation` -- basalto/cirro/zafiro/ambar -- ni `dev` -- leyenda/
mareas/kestrel -- ni `heldout` -- ferrovia/micelio/liga). Ningun nombre de
entidad, ninguna frase completa, se copia de esos corpus.

Regla de autoria seguida: las frases se escriben primero por naturalidad
narrativa; el gold (predicado, polaridad, decision esperada) se etiqueta
DESPUES por semantica, no al reves. Las superficies de relacion SI se toman
literalmente de `extraction/deterministic.RELATION_RULES` (vocabulario de
dominio permitido por el encargo) porque sin ellas el carril determinista no
emite nada y el acuerdo no se puede medir -- pero la frase que las rodea, el
mundo, los nombres y la puntuacion son originales de este corpus.

Mismo formato EXACTO que `negation/_authoring/cases.py`: lo unico que anade
`build_agreement_eval2.py` es el calculo de offsets/hashes/sobres.
"""
from __future__ import annotations

SPLIT = "agreement-eval2"
DATASET_VERSION = "1.0.0"
FORMAT_VERSION = "1.0.0"
WORKSPACE = "bench-agreement-eval2"
ONTOLOGY_VERSION = "core-1.4.0"
ENGINE_VERSION = "3.0.0-bench"

NEGATION_KINDS = (
    "NONE",
    "SIMPLE",
    "NEVER",
    "CESSATION",
    "NEGATED_CESSATION",
    "NOT_YET",
    "SCOPE_EMBEDDED",
    "DOUBLE_NEGATION",
)

FAMILY_QUOTA = {
    "SIMPLE": 8,
    "NEVER": 4,
    "CESSATION": 6,
    "NEGATED_CESSATION": 5,
    "NOT_YET": 4,
    "SCOPE_EMBEDDED": 4,
    "QUESTION_CONDITIONAL_RUMOR": 5,
    "DOUBLE_NEGATION": 2,
}
EXTRA_QUOTA = {"POSITIVE_CONTROL": 8, "NO_CLAIM": 4}

DECISIONS = (
    "AUTO_APPROVE",
    "REVIEW_NEGATION_CESSATION",
    "REVIEW_NEGATION_SCOPE",
    "ABSTAIN",
    "NO_DECISION",
)

DECISION_CONTRACT = {
    "AUTO_APPROVE": ("ACCEPT", ["LOCAL_APPROVED"]),
    "REVIEW_NEGATION_CESSATION": ("REVIEW", ["REVIEW_TEMPORALITY", "REVIEW_NEGATION_CESSATION"]),
    "REVIEW_NEGATION_SCOPE": ("REVIEW", ["REVIEW_PREDICATE", "REVIEW_NEGATION_SCOPE"]),
    "ABSTAIN": ("ABSTAIN", ["AMBIGUOUS_SEMANTICS"]),
}

# --------------------------------------------------------------------------
# Catalogo de entidades. Tres mundos NUEVOS.
# --------------------------------------------------------------------------
ENTITIES = [
    # --- vitral: ciudad-taller de vidrieros y cofradias de luz --------------
    ("entity:vitral:ilan-boreta", "vitral", "Ilan Boreta", "Character", [], "maestro vidriero"),
    ("entity:vitral:nadia-ferrus", "vitral", "Nadia Ferrus", "Character", [], "templadora"),
    ("entity:vitral:costas-delmira", "vitral", "Costas Delmira", "Character", [], "cristalera"),
    ("entity:vitral:renzo-aubier", "vitral", "Renzo Aubier", "Character", ["Renzo Aubièr"], "tasador"),
    ("entity:vitral:tilde-marconne", "vitral", "Tilde Marconne", "Character", [], "vigilante"),
    ("entity:vitral:ossian-vetra", "vitral", "Ossian Vetra", "Character", [], "archivero"),
    ("entity:vitral:calla-rindin", "vitral", "Calla Rindin", "Character", [], "aprendiza"),
    ("entity:vitral:uxue-somara", "vitral", "Uxue Somara", "Character", [], "portavoz"),
    ("entity:vitral:bram-oletti", "vitral", "Bram Oletti", "Character", [], "fundidor"),
    ("entity:vitral:serin-vaudal", "vitral", "Serin Vaudal", "Character", ["Serín Vaudal"], "notaria"),
    ("entity:vitral:camara-vidrio", "vitral", "Camara del Vidrio", "Faction", ["Cámara del Vidrio"], "gremio rector"),
    ("entity:vitral:ronda-faroles", "vitral", "Ronda de los Faroles", "Faction", [], "guardia nocturna"),
    ("entity:vitral:liga-sopladores", "vitral", "Liga de Sopladores", "Faction", [], "liga de oficio"),
    ("entity:vitral:terraza-cristal", "vitral", "Terraza Cristal", "Location", [], "plaza elevada"),
    ("entity:vitral:muelle-prisma", "vitral", "Muelle Prisma", "Location", [], "muelle"),
    ("entity:vitral:copa-alba", "vitral", "Copa del Alba", "Object", [], "reliquia de taller"),
    # --- salitre: caravanas de las llanuras de sal --------------------------
    ("entity:salitre:deza-corvel", "salitre", "Deza Corvel", "Character", [], "guia de caravana"),
    ("entity:salitre:matias-hurel", "salitre", "Matias Hurel", "Character", ["Matías Hurel"], "cargador"),
    ("entity:salitre:iva-brontes", "salitre", "Iva Brontes", "Character", [], "rastreadora"),
    ("entity:salitre:orell-cascan", "salitre", "Orell Cascan", "Character", [], "mercader"),
    ("entity:salitre:petra-lumis", "salitre", "Petra Lumis", "Character", [], "veedora"),
    ("entity:salitre:hakon-driel", "salitre", "Hakon Driel", "Character", [], "arriero"),
    ("entity:salitre:noor-alcaz", "salitre", "Noor Alcaz", "Character", [], "escriba de ruta"),
    ("entity:salitre:tobal-mencia", "salitre", "Tobal Mencia", "Character", ["Tobal Mencía"], "capataz"),
    ("entity:salitre:caravana-blanca", "salitre", "Caravana Blanca", "Faction", [], "convoy"),
    ("entity:salitre:sindicato-sal", "salitre", "Sindicato de la Sal", "Faction", [], "sindicato"),
    ("entity:salitre:orden-polvo", "salitre", "Orden del Polvo", "Faction", [], "orden itinerante"),
    ("entity:salitre:paso-cuarzo", "salitre", "Paso del Cuarzo", "Location", [], "desfiladero"),
    ("entity:salitre:pozo-hondo", "salitre", "Pozo Hondo", "Location", [], "pozo de agua"),
    ("entity:salitre:carro-plomo", "salitre", "Carro de Plomo", "Object", [], "carro blindado"),
    # --- brumal: paramo de faros y guardianes de niebla ---------------------
    ("entity:brumal:edda-solveig", "brumal", "Edda Solveig", "Character", [], "farera"),
    ("entity:brumal:janek-orum", "brumal", "Janek Orum", "Character", [], "guardian"),
    ("entity:brumal:lys-kordan", "brumal", "Lys Kordan", "Character", [], "cartografa"),
    ("entity:brumal:garret-eisen", "brumal", "Garret Eisen", "Character", [], "campanero"),
    ("entity:brumal:sonia-halvard", "brumal", "Sonia Halvard", "Character", [], "medica de paramo"),
    ("entity:brumal:token-arild", "brumal", "Torvald Arild", "Character", [], "batelero"),
    ("entity:brumal:mira-eskuld", "brumal", "Mira Eskuld", "Character", [], "vigia de faro"),
    ("entity:brumal:orden-faro-negro", "brumal", "Orden del Faro Negro", "Faction", [], "orden de guardianes"),
    ("entity:brumal:cofradia-niebla", "brumal", "Cofradia de la Niebla", "Faction", ["Cofradía de la Niebla"], "cofradia"),
    ("entity:brumal:consejo-paramo", "brumal", "Consejo del Paramo", "Faction", ["Consejo del Páramo"], "consejo"),
    ("entity:brumal:faro-ceniciento", "brumal", "Faro Ceniciento", "Location", [], "faro"),
    ("entity:brumal:puente-neblina", "brumal", "Puente de Neblina", "Location", [], "puente"),
    ("entity:brumal:campana-honda", "brumal", "Campana Honda", "Object", [], "campana ritual"),
]

# --------------------------------------------------------------------------
# Fuentes
# --------------------------------------------------------------------------
SOURCES = [
    {
        "source_id": "vitral-taller",
        "world": "vitral",
        "title": "Cuadernos del taller de vitral",
        "source_kind": "MARKDOWN",
        "mime_type": "text/markdown",
        "modality": "TEXT",
        "media_type": "EMBEDDED_TEXT",
        "collection_id": "collection:vitral",
        "calendar_id": "calendar:vitral",
        "description": "Prosa de taller. Negacion simple, cesacion, doble negacion y control positivo.",
    },
    {
        "source_id": "salitre-ruta",
        "world": "salitre",
        "title": "Diario de ruta de la Caravana Blanca",
        "source_kind": "MARKDOWN",
        "mime_type": "text/markdown",
        "modality": "TEXT",
        "media_type": "EMBEDDED_TEXT",
        "collection_id": "collection:salitre",
        "calendar_id": "calendar:salitre",
        "description": "Diario administrativo. Cesaciones, negacion de cesacion, alcance ambiguo.",
    },
    {
        "source_id": "brumal-bitacora",
        "world": "brumal",
        "title": "Bitacora hablada del Faro Ceniciento",
        "source_kind": "AUDIO",
        "mime_type": "audio/ogg",
        "modality": "SPEAKER_TURN",
        "media_type": "ASR_TEXT",
        "collection_id": "collection:brumal",
        "calendar_id": "calendar:brumal",
        "description": "Turnos de habla transcritos por ASR. NEVER, NOT_YET, rumor y condicional.",
    },
]


def _c(subject, predicate, obj, anchor, *, negated, direction="SUBJECT_TO_OBJECT",
       epistemic="ASSERTED", role="PRIMARY", cues=()):
    return {
        "role": role, "subject": subject, "object": obj, "predicate": predicate,
        "direction": direction, "negated": negated, "epistemic": epistemic,
        "anchor": anchor, "epistemic_cues": list(cues),
    }


V = "entity:vitral:"
S = "entity:salitre:"
Br = "entity:brumal:"

CASES = [
    # =====================================================================
    # vitral-taller (16 casos): SIMPLE, NEGATED_CESSATION, DOUBLE_NEGATION,
    #                           POSITIVE_CONTROL, NO_CLAIM
    # =====================================================================
    {
        "id": "AE2-SIMPLE-01", "source": "vitral-taller", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": (
            "Que quede escrito para que nadie lo dude en la proxima inspeccion: "
            "Ilan Boreta no pertenece a la Camara del Vidrio, por mas que su banco "
            "de trabajo siga en Terraza Cristal."
        ),
        "claims": [_c(("Ilan Boreta", V + "ilan-boreta"), "MEMBER_OF",
                       ("Camara del Vidrio", V + "camara-vidrio"),
                       "Ilan Boreta no pertenece a la Camara del Vidrio", negated=True)],
        "extra_mentions": [("Terraza Cristal", V + "terraza-cristal")],
        "traps": ["clausula final que menciona el taller sin afirmar pertenencia"],
        "rationale": "Negacion simple canonica, una marca, alcance cerrado.",
    },
    {
        "id": "AE2-SIMPLE-02", "source": "vitral-taller", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Nadia Ferrus pertenece a la Liga de Sopladores desde el ultimo censo del taller.",
        "claims": [_c(("Nadia Ferrus", V + "nadia-ferrus"), "MEMBER_OF",
                       ("Liga de Sopladores", V + "liga-sopladores"),
                       "Nadia Ferrus pertenece a la Liga de Sopladores", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Control afirmativo de la misma familia lexica.",
    },
    {
        "id": "AE2-SIMPLE-03", "source": "vitral-taller", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": (
            "Costas Delmira lidera la Ronda de los Faroles, y el libro de guardias "
            "asi lo asienta cada noche."
        ),
        "claims": [_c(("Costas Delmira", V + "costas-delmira"), "LEADS",
                       ("Ronda de los Faroles", V + "ronda-faroles"),
                       "Costas Delmira lidera la Ronda de los Faroles", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Afirmativo simple, predicado funcional LEADS.",
    },
    {
        "id": "AE2-SIMPLE-04", "source": "vitral-taller", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Renzo Aubier no lidera la Camara del Vidrio, y todo tasador nuevo lo confunde al llegar.",
        "claims": [_c(("Renzo Aubier", V + "renzo-aubier"), "LEADS",
                       ("Camara del Vidrio", V + "camara-vidrio"),
                       "Renzo Aubier no lidera la Camara del Vidrio", negated=True)],
        "extra_mentions": [], "traps": ["clausula final irrelevante tras la negacion"],
        "rationale": "Negacion simple sobre predicado funcional.",
    },
    {
        "id": "AE2-SIMPLE-05", "source": "vitral-taller", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Tilde Marconne es aliada de Ossian Vetra desde que ambos entraron de aprendices.",
        "claims": [_c(("Tilde Marconne", V + "tilde-marconne"), "ALLY_OF",
                       ("Ossian Vetra", V + "ossian-vetra"),
                       "Tilde Marconne es aliada de Ossian Vetra", negated=False, direction="UNDIRECTED")],
        "extra_mentions": [], "traps": [], "rationale": "Predicado simetrico, control afirmativo.",
    },
    {
        "id": "AE2-SIMPLE-06", "source": "vitral-taller", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Calla Rindin no es aliada de Uxue Somara, aunque compartan mesa en cada asamblea.",
        "claims": [_c(("Calla Rindin", V + "calla-rindin"), "ALLY_OF",
                       ("Uxue Somara", V + "uxue-somara"),
                       "Calla Rindin no es aliada de Uxue Somara", negated=True, direction="UNDIRECTED")],
        "extra_mentions": [], "traps": ["concesiva que sugiere cercania sin afirmar alianza"],
        "rationale": "Negacion simple sobre predicado simetrico.",
    },
    {
        "id": "AE2-DOUBLE-01", "source": "vitral-taller", "family": "DOUBLE_NEGATION", "kind": "DOUBLE_NEGATION",
        "decision": "AUTO_APPROVE", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE", "scope_note": "doble negacion",
        "text": (
            "Nadie puede negar que Bram Oletti no pertenece a la Liga de Sopladores; "
            "el registro del taller lo repite cada temporada."
        ),
        "claims": [_c(("Bram Oletti", V + "bram-oletti"), "MEMBER_OF",
                       ("Liga de Sopladores", V + "liga-sopladores"),
                       "Nadie puede negar que Bram Oletti no pertenece a la Liga de Sopladores",
                       negated=True, role="PRIMARY")],
        "extra_mentions": [], "traps": ["negacion externa (nadie puede negar) mas negacion interna (no pertenece)"],
        "rationale": "Doble negacion: la negacion externa reafirma la interna, resultado neto negado.",
    },
    {
        "id": "AE2-DOUBLE-02", "source": "vitral-taller", "family": "DOUBLE_NEGATION", "kind": "DOUBLE_NEGATION",
        "decision": "AUTO_APPROVE", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": (
            "No es cierto que Serin Vaudal no sirve a la Camara del Vidrio: firma sus "
            "actas cada equinoccio."
        ),
        "claims": [_c(("Serin Vaudal", V + "serin-vaudal"), "SERVES",
                       ("Camara del Vidrio", V + "camara-vidrio"),
                       "No es cierto que Serin Vaudal no sirve a la Camara del Vidrio",
                       negated=False)],
        "extra_mentions": [], "traps": ["negacion externa cancela la interna: resultado neto afirmativo"],
        "rationale": "Doble negacion que se cancela: la relacion queda AFIRMADA, no negada.",
    },
    {
        "id": "AE2-NEGCESS-01", "source": "vitral-taller", "family": "NEGATED_CESSATION", "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO_MAS_INFINITIVO", "noise": "NONE",
        "text": "Uxue Somara no dejo de servir a la Ronda de los Faroles, ni siquiera cuando cambio de taller.",
        "claims": [_c(("Uxue Somara", V + "uxue-somara"), "SERVES",
                       ("Ronda de los Faroles", V + "ronda-faroles"),
                       "Uxue Somara no dejo de servir a la Ronda de los Faroles", negated=False)],
        "extra_mentions": [], "traps": ["negacion de cesacion: la relacion sigue vigente"],
        "rationale": "'No dejo de X' niega el cese: la relacion continua, va a revision por temporalidad.",
    },
    {
        "id": "AE2-NEGCESS-02", "source": "vitral-taller", "family": "NEGATED_CESSATION", "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO_MAS_INFINITIVO", "noise": "NONE",
        "text": "Ilan Boreta no ceso de liderar la Camara del Vidrio pese a los rumores del ultimo censo.",
        "claims": [_c(("Ilan Boreta", V + "ilan-boreta"), "LEADS",
                       ("Camara del Vidrio", V + "camara-vidrio"),
                       "Ilan Boreta no ceso de liderar la Camara del Vidrio", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Misma familia con verbo cesar y predicado funcional.",
    },
    {
        "id": "AE2-CESS-01", "source": "vitral-taller", "family": "CESSATION", "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO", "noise": "NONE",
        "text": "Nadia Ferrus dejo de pertenecer a la Liga de Sopladores tras el cierre del ultimo horno.",
        "claims": [_c(("Nadia Ferrus", V + "nadia-ferrus"), "MEMBER_OF",
                       ("Liga de Sopladores", V + "liga-sopladores"),
                       "Nadia Ferrus dejo de pertenecer a la Liga de Sopladores", negated=True)],
        "extra_mentions": [], "traps": [], "rationale": "Cesacion: la relacion estuvo vigente y ya no.",
    },
    {
        "id": "AE2-CESS-02", "source": "vitral-taller", "family": "CESSATION", "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO", "noise": "NONE",
        "text": "Costas Delmira dejo de dirigir la Ronda de los Faroles cuando se traslado a Muelle Prisma.",
        "claims": [_c(("Costas Delmira", V + "costas-delmira"), "LEADS",
                       ("Ronda de los Faroles", V + "ronda-faroles"),
                       "Costas Delmira dejo de dirigir la Ronda de los Faroles", negated=True)],
        "extra_mentions": [("Muelle Prisma", V + "muelle-prisma")], "traps": [],
        "rationale": "Cesacion de liderazgo, con complemento locativo tras la marca.",
    },
    {
        "id": "AE2-POS-01", "source": "vitral-taller", "family": "POSITIVE_CONTROL", "kind": "NONE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Ossian Vetra vive en Terraza Cristal desde que se hizo cargo del archivo del taller.",
        "claims": [_c(("Ossian Vetra", V + "ossian-vetra"), "LIVES_IN",
                       ("Terraza Cristal", V + "terraza-cristal"),
                       "Ossian Vetra vive en Terraza Cristal", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Control positivo sin negacion, LIVES_IN.",
    },
    {
        "id": "AE2-POS-02", "source": "vitral-taller", "family": "POSITIVE_CONTROL", "kind": "NONE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Bram Oletti posee la Copa del Alba desde que la rescato del horno viejo.",
        "claims": [_c(("Bram Oletti", V + "bram-oletti"), "OWNS",
                       ("Copa del Alba", V + "copa-alba"),
                       "Bram Oletti posee la Copa del Alba", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Control positivo, OWNS.",
    },
    {
        "id": "AE2-NOCLAIM-01", "source": "vitral-taller", "family": "NO_CLAIM", "kind": "NONE",
        "decision": "NO_DECISION", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "IMPERATIVO", "noise": "NONE",
        "abstained": False,
        "text": "Templa el vidrio antes de que el horno pierda calor, y no dejes sola la pieza.",
        "anchor": "Templa el vidrio antes de que el horno pierda calor",
        "claims": [], "extra_mentions": [], "negative_kind": "IMPERATIVE",
        "must_not_produce": ["cualquier relacion entre personas o facciones"],
        "forbidden_predicates": ["MEMBER_OF", "LEADS", "ALLY_OF"],
        "traps": ["imperativo con negacion final que no niega ninguna relacion"],
        "rationale": "Instruccion de taller, sin sujeto ni relacion asertable.",
    },
    {
        "id": "AE2-NOCLAIM-02", "source": "vitral-taller", "family": "NO_CLAIM", "kind": "NONE",
        "decision": "NO_DECISION", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "CONDICIONAL", "noise": "NONE",
        "abstained": False,
        "text": "Si Renzo Aubier hubiera pertenecido a la Camara del Vidrio, otro habria firmado el tasado.",
        "anchor": "Si Renzo Aubier hubiera pertenecido a la Camara del Vidrio",
        "claims": [], "extra_mentions": [], "negative_kind": "COUNTERFACTUAL",
        "must_not_produce": ["MEMBER_OF(Renzo Aubier, Camara del Vidrio)"],
        "forbidden_predicates": ["MEMBER_OF"],
        "traps": ["condicional contrafactico con la misma frase de relacion que AE2-SIMPLE-01/02"],
        "rationale": "Contrafactico: el texto afirma justo lo contrario de lo que el condicional describe.",
    },
    # =====================================================================
    # salitre-ruta (16 casos): CESSATION, NEGATED_CESSATION, SCOPE_EMBEDDED,
    #                          SIMPLE, POSITIVE_CONTROL, NO_CLAIM
    # =====================================================================
    {
        "id": "AE2-SIMPLE-07", "source": "salitre-ruta", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Deza Corvel milita en el Sindicato de la Sal, segun consta en el diario de ruta de este ciclo.",
        "claims": [_c(("Deza Corvel", S + "deza-corvel"), "MEMBER_OF",
                       ("Sindicato de la Sal", S + "sindicato-sal"),
                       "Deza Corvel milita en el Sindicato de la Sal", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Afirmativo con verbo 'militar en'.",
    },
    {
        "id": "AE2-SIMPLE-08", "source": "salitre-ruta", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Matias Hurel no milita en la Orden del Polvo, contra lo que se comento en el ultimo relevo.",
        "claims": [_c(("Matias Hurel", S + "matias-hurel"), "MEMBER_OF",
                       ("Orden del Polvo", S + "orden-polvo"),
                       "Matias Hurel no milita en la Orden del Polvo", negated=True)],
        "extra_mentions": [], "traps": ["referencia a un comentario ajeno tras la negacion"],
        "rationale": "Negacion simple, misma familia lexica que AE2-SIMPLE-07.",
    },
    {
        "id": "AE2-SIMPLE-09", "source": "salitre-ruta", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Iva Brontes es hermana de Orell Cascan, y ambos comparten carro desde Pozo Hondo.",
        "claims": [_c(("Iva Brontes", S + "iva-brontes"), "SIBLING_OF",
                       ("Orell Cascan", S + "orell-cascan"),
                       "Iva Brontes es hermana de Orell Cascan", negated=False, direction="UNDIRECTED")],
        "extra_mentions": [("Pozo Hondo", S + "pozo-hondo")], "traps": [],
        "rationale": "Control afirmativo, predicado simetrico.",
    },
    {
        "id": "AE2-SIMPLE-10", "source": "salitre-ruta", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "AFTER_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Petra Lumis, veedora de la Caravana Blanca desde el paso anterior, no lo es ya.",
        "claims": [_c(("Petra Lumis", S + "petra-lumis"), "MEMBER_OF",
                       ("Caravana Blanca", S + "caravana-blanca"),
                       "Petra Lumis, veedora de la Caravana Blanca desde el paso anterior, no lo es ya",
                       negated=True)],
        "extra_mentions": [], "traps": ["negacion final con pronombre atono tras un inciso afirmativo"],
        "rationale": "Topicalizacion con negacion final: leer solo el inciso invierte la lectura.",
    },
    {
        "id": "AE2-CESS-03", "source": "salitre-ruta", "family": "CESSATION", "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO", "noise": "NONE",
        "text": "Hakon Driel dejo de servir a la Orden del Polvo cuando el convoy cruzo el Paso del Cuarzo.",
        "claims": [_c(("Hakon Driel", S + "hakon-driel"), "SERVES",
                       ("Orden del Polvo", S + "orden-polvo"),
                       "Hakon Driel dejo de servir a la Orden del Polvo", negated=True)],
        "extra_mentions": [("Paso del Cuarzo", S + "paso-cuarzo")], "traps": [], "rationale": "Cesacion con SERVES.",
    },
    {
        "id": "AE2-CESS-04", "source": "salitre-ruta", "family": "CESSATION", "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO", "noise": "NONE",
        "text": "Noor Alcaz dejo de pertenecer al Sindicato de la Sal tras el reparto del ultimo cargamento.",
        "claims": [_c(("Noor Alcaz", S + "noor-alcaz"), "MEMBER_OF",
                       ("Sindicato de la Sal", S + "sindicato-sal"),
                       "Noor Alcaz dejo de pertenecer al Sindicato de la Sal", negated=True)],
        "extra_mentions": [], "traps": [], "rationale": "Cesacion con forma 'pertenecer al'.",
    },
    {
        "id": "AE2-CESS-05", "source": "salitre-ruta", "family": "CESSATION", "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO", "noise": "NONE",
        "text": "Tobal Mencia dejo de dirigir la Caravana Blanca despues de perder dos carros en la travesia.",
        "claims": [_c(("Tobal Mencia", S + "tobal-mencia"), "LEADS",
                       ("Caravana Blanca", S + "caravana-blanca"),
                       "Tobal Mencia dejo de dirigir la Caravana Blanca", negated=True)],
        "extra_mentions": [], "traps": [], "rationale": "Cesacion de liderazgo.",
    },
    {
        "id": "AE2-NEGCESS-03", "source": "salitre-ruta", "family": "NEGATED_CESSATION", "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO_MAS_INFINITIVO", "noise": "NONE",
        "text": "Deza Corvel no dejo de pertenecer al Sindicato de la Sal, pese al rumor que corrio en Pozo Hondo.",
        "claims": [_c(("Deza Corvel", S + "deza-corvel"), "MEMBER_OF",
                       ("Sindicato de la Sal", S + "sindicato-sal"),
                       "Deza Corvel no dejo de pertenecer al Sindicato de la Sal", negated=False)],
        "extra_mentions": [("Pozo Hondo", S + "pozo-hondo")], "traps": ["mencion de un rumor sin que el texto lo confirme"],
        "rationale": "Negacion de cesacion: la relacion continua vigente.",
    },
    {
        "id": "AE2-NEGCESS-04", "source": "salitre-ruta", "family": "NEGATED_CESSATION", "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "PRETERITO_MAS_INFINITIVO", "noise": "NONE",
        "text": "Orell Cascan no ceso de servir al Sindicato de la Sal ni cuando cambio de carro.",
        "claims": [_c(("Orell Cascan", S + "orell-cascan"), "SERVES",
                       ("Sindicato de la Sal", S + "sindicato-sal"),
                       "Orell Cascan no ceso de servir al Sindicato de la Sal", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Negacion de cesacion con verbo cesar.",
    },
    {
        "id": "AE2-SCOPE-01", "source": "salitre-ruta", "family": "SCOPE_EMBEDDED", "kind": "SCOPE_EMBEDDED",
        "decision": "REVIEW_NEGATION_SCOPE", "scope": "AMBIGUOUS", "cue_position": "EMBEDDED",
        "voice": "ACTIVE", "verb_form": "SUBJUNTIVO", "noise": "NONE",
        "text": (
            "El veedor anoto que no cree que Hakon Driel pertenezca al Sindicato de la Sal, "
            "aunque el propio Hakon lo firmara el ciclo pasado."
        ),
        "claims": [_c(("Hakon Driel", S + "hakon-driel"), "MEMBER_OF",
                       ("Sindicato de la Sal", S + "sindicato-sal"),
                       "no cree que Hakon Driel pertenezca al Sindicato de la Sal",
                       negated=True, epistemic="ASSERTED", role="PRIMARY")],
        "extra_mentions": [], "traps": ["negacion de un verbo de opinion ajena sobre una subordinada",
                                          "clausula final que contradice la opinion negada"],
        "rationale": (
            "El alcance de la negacion es dudoso: niega la CREENCIA del veedor, no "
            "necesariamente el hecho, y el propio texto lo contradice a continuacion. "
            "Caso disenado para discrepancia potencial entre carriles."
        ),
    },
    {
        "id": "AE2-SCOPE-02", "source": "salitre-ruta", "family": "SCOPE_EMBEDDED", "kind": "SCOPE_EMBEDDED",
        "decision": "REVIEW_NEGATION_SCOPE", "scope": "AMBIGUOUS", "cue_position": "EMBEDDED",
        "voice": "ACTIVE", "verb_form": "INDICATIVO", "noise": "NONE",
        "text": (
            "No es que Noor Alcaz no sirva al Sindicato de la Sal; es que reparte su "
            "tiempo tambien con la Orden del Polvo."
        ),
        "claims": [_c(("Noor Alcaz", S + "noor-alcaz"), "SERVES",
                       ("Sindicato de la Sal", S + "sindicato-sal"),
                       "No es que Noor Alcaz no sirva al Sindicato de la Sal", negated=False)],
        "extra_mentions": [], "traps": ["negacion metalinguistica de una negacion implicita ('no es que no')",
                                          "segunda relacion (Orden del Polvo) sugerida pero no asertada"],
        "rationale": "Correccion metalinguistica: cancela la negacion, la relacion se mantiene AFIRMADA.",
    },
    {
        "id": "AE2-POS-03", "source": "salitre-ruta", "family": "POSITIVE_CONTROL", "kind": "NONE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Petra Lumis posee el Carro de Plomo desde que lo gano en la subasta del ultimo relevo.",
        "claims": [_c(("Petra Lumis", S + "petra-lumis"), "OWNS",
                       ("Carro de Plomo", S + "carro-plomo"),
                       "Petra Lumis posee el Carro de Plomo", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Control positivo, OWNS.",
    },
    {
        "id": "AE2-POS-04", "source": "salitre-ruta", "family": "POSITIVE_CONTROL", "kind": "NONE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "text": "Tobal Mencia se encuentra en Pozo Hondo desde que el convoy hizo alto para reponer agua.",
        "claims": [_c(("Tobal Mencia", S + "tobal-mencia"), "LOCATED_IN",
                       ("Pozo Hondo", S + "pozo-hondo"),
                       "Tobal Mencia se encuentra en Pozo Hondo", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Control positivo, LOCATED_IN.",
    },
    {
        "id": "AE2-NOCLAIM-03", "source": "salitre-ruta", "family": "NO_CLAIM", "kind": "NONE",
        "decision": "NO_DECISION", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "INTERROGATIVO", "noise": "NONE",
        "abstained": False,
        "text": "¿Sigue Matias Hurel en la Orden del Polvo, o ya se paso al Sindicato de la Sal?",
        "anchor": "¿Sigue Matias Hurel en la Orden del Polvo",
        "claims": [], "extra_mentions": [], "negative_kind": "QUESTION",
        "must_not_produce": ["MEMBER_OF(Matias Hurel, Orden del Polvo)", "MEMBER_OF(Matias Hurel, Sindicato de la Sal)"],
        "forbidden_predicates": ["MEMBER_OF"],
        "traps": ["pregunta disyuntiva que menciona dos facciones sin afirmar ninguna"],
        "rationale": "Interrogativa: no afirma ninguna pertenencia, solo pregunta.",
    },
    {
        "id": "AE2-NOCLAIM-04", "source": "salitre-ruta", "family": "NO_CLAIM", "kind": "NONE",
        "decision": "NO_DECISION", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "NONE",
        "abstained": False,
        "text": "En la copla que cantan los arrieros, Iva Brontes dirige media caravana desde una duna que no existe.",
        "anchor": "En la copla que cantan los arrieros, Iva Brontes dirige media caravana",
        "claims": [], "extra_mentions": [], "negative_kind": "FICTION_WITHIN_FICTION",
        "must_not_produce": ["LEADS(Iva Brontes, *)"],
        "forbidden_predicates": ["LEADS"],
        "traps": ["marco de ficcion dentro de la ficcion ('en la copla que cantan')"],
        "rationale": "Ficcion enmarcada: el texto describe una copla, no un hecho del mundo narrado.",
    },
    # =====================================================================
    # brumal-bitacora (13 casos, ASR): NEVER, NOT_YET,
    #                                  QUESTION_CONDITIONAL_RUMOR, SIMPLE
    # =====================================================================
    {
        "id": "AE2-NEVER-01", "source": "brumal-bitacora", "family": "NEVER", "kind": "NEVER",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Edda Solveig nunca sirvio a la Cofradia de la Niebla, y eso que se lo ofrecieron dos veces.",
        "claims": [_c(("Edda Solveig", Br + "edda-solveig"), "SERVES",
                       ("Cofradia de la Niebla", Br + "cofradia-niebla"),
                       "Edda Solveig nunca sirvio a la Cofradia de la Niebla", negated=True)],
        "extra_mentions": [], "traps": [], "rationale": "NEVER canonico: niega la relacion en todo momento.",
    },
    {
        "id": "AE2-NEVER-02", "source": "brumal-bitacora", "family": "NEVER", "kind": "NEVER",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Janek Orum jamas fue aliado de la Orden del Faro Negro, ni cuando compartian ronda.",
        "claims": [_c(("Janek Orum", Br + "janek-orum"), "ALLY_OF",
                       ("Orden del Faro Negro", Br + "orden-faro-negro"),
                       "Janek Orum jamas fue aliado de la Orden del Faro Negro",
                       negated=True, direction="UNDIRECTED")],
        "extra_mentions": [], "traps": [], "rationale": "NEVER con predicado simetrico.",
    },
    {
        "id": "AE2-NOTYET-01", "source": "brumal-bitacora", "family": "NOT_YET", "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Lys Kordan aun no pertenece al Consejo del Paramo, aunque ya la proponen para el proximo relevo.",
        "claims": [_c(("Lys Kordan", Br + "lys-kordan"), "MEMBER_OF",
                       ("Consejo del Paramo", Br + "consejo-paramo"),
                       "Lys Kordan aun no pertenece al Consejo del Paramo", negated=True)],
        "extra_mentions": [], "traps": ["clausula final que sugiere que la relacion es inminente"],
        "rationale": "NOT_YET: niega el presente pero deja abierta la expectativa futura.",
    },
    {
        "id": "AE2-NOTYET-02", "source": "brumal-bitacora", "family": "NOT_YET", "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Garret Eisen todavia no dirige la Cofradia de la Niebla, aunque ya firma media correspondencia.",
        "claims": [_c(("Garret Eisen", Br + "garret-eisen"), "LEADS",
                       ("Cofradia de la Niebla", Br + "cofradia-niebla"),
                       "Garret Eisen todavia no dirige la Cofradia de la Niebla", negated=True)],
        "extra_mentions": [], "traps": [], "rationale": "NOT_YET sobre predicado funcional.",
    },
    {
        "id": "AE2-SIMPLE-11", "source": "brumal-bitacora", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Sonia Halvard reside en el Faro Ceniciento desde que releva a los guardianes heridos.",
        "claims": [_c(("Sonia Halvard", Br + "sonia-halvard"), "LIVES_IN",
                       ("Faro Ceniciento", Br + "faro-ceniciento"),
                       "Sonia Halvard reside en el Faro Ceniciento", negated=False)],
        "extra_mentions": [], "traps": [], "rationale": "Afirmativo simple, LIVES_IN.",
    },
    {
        "id": "AE2-SIMPLE-12", "source": "brumal-bitacora", "family": "SIMPLE", "kind": "SIMPLE",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Torvald Arild no reside en el Puente de Neblina, contra lo que anoto el ultimo relevo.",
        "claims": [_c(("Torvald Arild", Br + "token-arild"), "LIVES_IN",
                       ("Puente de Neblina", Br + "puente-neblina"),
                       "Torvald Arild no reside en el Puente de Neblina", negated=True)],
        "extra_mentions": [], "traps": [], "rationale": "Negacion simple, LIVES_IN.",
    },
    {
        "id": "AE2-RUMOR-01", "source": "brumal-bitacora", "family": "QUESTION_CONDITIONAL_RUMOR",
        "kind": "SIMPLE", "decision": "ABSTAIN", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "abstained": True, "anchor": "se rumorea que Mira Eskuld lidera en secreto la Cofradia de la Niebla",
        "text": "Por el paramo se rumorea que Mira Eskuld lidera en secreto la Cofradia de la Niebla.",
        "claims": [], "extra_mentions": [("Mira Eskuld", Br + "mira-eskuld"), ("Cofradia de la Niebla", Br + "cofradia-niebla")],
        "traps": ["marca epistemica RUMORED sobre una relacion de liderazgo verosimil"],
        "rationale": "Rumor puro: no debe autoaprobarse aunque el hecho sea plausible y este bien anclado.",
    },
    {
        "id": "AE2-COND-01", "source": "brumal-bitacora", "family": "QUESTION_CONDITIONAL_RUMOR",
        "kind": "SIMPLE", "decision": "ABSTAIN", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "CONDICIONAL", "noise": "ASR",
        "abstained": True, "anchor": "Si el faro se apagara, Janek Orum tendria que dirigir el Consejo del Paramo",
        "text": "Si el faro se apagara, Janek Orum tendria que dirigir el Consejo del Paramo, dijo el vigia.",
        "claims": [], "extra_mentions": [("Janek Orum", Br + "janek-orum"), ("Consejo del Paramo", Br + "consejo-paramo")],
        "traps": ["condicional hipotetico presentado como cita de un tercero"],
        "rationale": "Condicional puro, nunca escribible: el liderazgo depende de una hipotesis no cumplida.",
    },
    {
        "id": "AE2-RUMOR-02", "source": "brumal-bitacora", "family": "QUESTION_CONDITIONAL_RUMOR",
        "kind": "NONE", "decision": "NO_DECISION", "scope": "UNAMBIGUOUS", "cue_position": "NONE",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR", "abstained": False,
        "text": "Dicen que Sonia Halvard curo a un guardian que nunca existio, segun la copla del faro.",
        "anchor": "Dicen que Sonia Halvard curo a un guardian que nunca existio",
        "claims": [], "extra_mentions": [("Sonia Halvard", Br + "sonia-halvard")],
        "negative_kind": "COUNTERFACTUAL",
        "must_not_produce": ["cualquier relacion de Sonia Halvard con un tercero inventado"],
        "forbidden_predicates": ["LOCATED_IN", "ALLY_OF"],
        "traps": ["cita atribuida ('dicen que') sobre un hecho explicitamente irreal"],
        "rationale": "Reporte de un hecho que el propio texto declara inexistente: no hay relacion que anclar.",
    },
    {
        "id": "AE2-NEVER-03", "source": "brumal-bitacora", "family": "NEVER", "kind": "NEVER",
        "decision": "AUTO_APPROVE", "scope": "UNAMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Garret Eisen nunca fue enemigo de Edda Solveig, ni siquiera cuando discutian por el turno de campana.",
        "claims": [_c(("Garret Eisen", Br + "garret-eisen"), "ENEMY_OF",
                       ("Edda Solveig", Br + "edda-solveig"),
                       "Garret Eisen nunca fue enemigo de Edda Solveig",
                       negated=True, direction="UNDIRECTED")],
        "extra_mentions": [], "traps": ["clausula final que sugiere friccion sin afirmar enemistad"],
        "rationale": "NEVER con predicado simetrico ENEMY_OF.",
    },
    {
        "id": "AE2-NOTYET-03", "source": "brumal-bitacora", "family": "NOT_YET", "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE", "scope": "AMBIGUOUS", "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE", "verb_form": "INDICATIVO_PRESENTE", "noise": "ASR",
        "text": "Mira Eskuld aun no vive en el Faro Ceniciento, aunque ya guarda turno alli tres noches por semana.",
        "claims": [_c(("Mira Eskuld", Br + "mira-eskuld"), "LIVES_IN",
                       ("Faro Ceniciento", Br + "faro-ceniciento"),
                       "Mira Eskuld aun no vive en el Faro Ceniciento", negated=True)],
        "extra_mentions": [], "traps": [], "rationale": "NOT_YET sobre LIVES_IN.",
    },
]
