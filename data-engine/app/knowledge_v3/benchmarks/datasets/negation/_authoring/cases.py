# -*- coding: utf-8 -*-
"""Bateria de negaciones: CONTENIDO escrito a mano (split `negation`).

Escrito por el equipo independiente SIN leer la implementacion de la extraccion
(`extraction/cues.py`, `deterministic.py`, `payload.py`, `semantic.py` ni sus
tests). Los casos salen del espanol, no del codigo: si se escribiesen mirando
las listas lexicas del extractor, la bateria mediria el propio codigo y daria un
verde vacio. Ver `docs/v3/19-bateria-de-negaciones.md`.

Aqui solo hay TEXTO y ANOTACION. Los offsets, hashes y sobres los calcula
`build_negation.py`: un offset escrito a mano se equivoca; uno calculado sobre
el texto literal, no.
"""
from __future__ import annotations

SPLIT = "negation"
DATASET_VERSION = "1.0.0"
FORMAT_VERSION = "1.0.0"
WORKSPACE = "bench-negation"
ONTOLOGY_VERSION = "core-1.4.0"
ENGINE_VERSION = "3.0.0-bench"

#: Vocabulario de `negation_kind` DECLARADO por esta bateria. Solo `CESSATION`
#: viene literalmente de docs/v3/18; el resto son nombres propios de este gold.
#: Lo vinculante es el par (negated esperado, decision esperada); quien mida
#: debe mapear su vocabulario sobre esta tabla, no al reves.
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

#: Las ocho familias de la tabla de docs/v3/18 §3, mas los dos anadidos.
FAMILY_QUOTA = {
    "SIMPLE": 10,
    "NEVER": 6,
    "CESSATION": 10,
    "NEGATED_CESSATION": 8,
    "NOT_YET": 5,
    "SCOPE_EMBEDDED": 5,
    "QUESTION_CONDITIONAL_RUMOR": 4,
    "DOUBLE_NEGATION": 2,
}
EXTRA_QUOTA = {"POSITIVE_CONTROL": 6, "NO_CLAIM": 4}

#: Las cuatro decisiones que la politica de docs/v3/18 admite para una negacion.
DECISIONS = (
    "AUTO_APPROVE",
    "REVIEW_NEGATION_CESSATION",
    "REVIEW_NEGATION_SCOPE",
    "ABSTAIN",
    "NO_DECISION",  # solo para los casos sin claim
)

#: Mapa de la decision de politica al par (decision del contrato, razones).
#: `REVIEW_NEGATION_*` no son codigos canonicos del validador congelado, asi que
#: cada decision lleva TAMBIEN su razon canonica; el validador exige al menos una.
DECISION_CONTRACT = {
    "AUTO_APPROVE": ("ACCEPT", ["LOCAL_APPROVED"]),
    "REVIEW_NEGATION_CESSATION": (
        "REVIEW",
        ["REVIEW_TEMPORALITY", "REVIEW_NEGATION_CESSATION"],
    ),
    "REVIEW_NEGATION_SCOPE": (
        "REVIEW",
        ["REVIEW_PREDICATE", "REVIEW_NEGATION_SCOPE"],
    ),
    "ABSTAIN": ("ABSTAIN", ["AMBIGUOUS_SEMANTICS"]),
}

# --------------------------------------------------------------------------
# Catalogo de entidades. Cuatro mundos NUEVOS: ninguno de dev (leyenda, mareas,
# kestrel) ni del held-out (ferrovia, micelio, liga).
# --------------------------------------------------------------------------
# (entity_id, world, name, type, aliases, note)
ENTITIES = [
    # --- basalto: archipielago volcanico de ordenes y talleres ---------------
    ("entity:basalto:harun-vell", "basalto", "Harun Vell", "Character", [], "forjador"),
    ("entity:basalto:sira-delantre", "basalto", "Sira Delantre", "Character", [], "capataz"),
    ("entity:basalto:olmo-quiral", "basalto", "Olmo Quiral", "Character", [], "vigia"),
    ("entity:basalto:nerea-tossa", "basalto", "Nerea Tossa", "Character", [], "cartografa"),
    ("entity:basalto:beltran-osk", "basalto", "Beltran Osk", "Character", ["Beltrán Osk"], "consejero"),
    ("entity:basalto:mira-cauce", "basalto", "Mira Cauce", "Character", [], "sopladora"),
    ("entity:basalto:teo-ravasi", "basalto", "Teo Ravasi", "Character", [], "maestre"),
    ("entity:basalto:ilde-varona", "basalto", "Ilde Varona", "Character", [], "escriba"),
    ("entity:basalto:kaspar-nune", "basalto", "Kaspar Nune", "Character", ["Kaspar Nuñe"], "herrero"),
    ("entity:basalto:runa-belisa", "basalto", "Runa Belisa", "Character", [], "arriera"),
    ("entity:basalto:orden-obsidiana", "basalto", "Orden de la Obsidiana", "Faction", [], "orden militar"),
    ("entity:basalto:gremio-fundidores", "basalto", "Gremio de Fundidores", "Faction", [], "gremio"),
    ("entity:basalto:casa-verrant", "basalto", "Casa Verrant", "Faction", [], "casa mercante"),
    ("entity:basalto:conclave-ceniza", "basalto", "Conclave de la Ceniza", "Faction", ["Cónclave de la Ceniza"], "asamblea"),
    ("entity:basalto:hermandad-fumarola", "basalto", "Hermandad de la Fumarola", "Faction", [], "hermandad"),
    ("entity:basalto:puerto-escoria", "basalto", "Puerto Escoria", "Location", [], "puerto"),
    ("entity:basalto:isla-tenaza", "basalto", "Isla Tenaza", "Location", [], "isla"),
    ("entity:basalto:foso-humeante", "basalto", "Foso Humeante", "Location", [], "foso"),
    ("entity:basalto:yunque-negro", "basalto", "Yunque Negro", "Object", [], "reliquia"),
    ("entity:basalto:sello-lava", "basalto", "Sello de Lava", "Object", [], "sello"),
    # --- cirro: ciudad aerea de consejos y companias -------------------------
    ("entity:cirro:dagna-hoill", "cirro", "Dagna Hoill", "Character", [], "presidenta"),
    ("entity:cirro:pol-arriaga", "cirro", "Pol Arriaga", "Character", [], "fletador"),
    ("entity:cirro:vera-luntz", "cirro", "Vera Luntz", "Character", [], "velera"),
    ("entity:cirro:ismael-corvo", "cirro", "Ismael Corvo", "Character", [], "astillero"),
    ("entity:cirro:tanit-pereo", "cirro", "Tanit Pereo", "Character", [], "aerostera"),
    ("entity:cirro:hugo-marlen", "cirro", "Hugo Marlen", "Character", ["Hugo Marlén"], "piloto"),
    ("entity:cirro:selva-ondiz", "cirro", "Selva Ondiz", "Character", [], "corredora"),
    ("entity:cirro:radi-oster", "cirro", "Radi Oster", "Character", [], "directora"),
    ("entity:cirro:noa-quimper", "cirro", "Noa Quimper", "Character", [], "armadora"),
    ("entity:cirro:consejo-vientos", "cirro", "Consejo de los Vientos", "Faction", [], "consejo"),
    ("entity:cirro:compania-arrecife", "cirro", "Compania del Arrecife", "Faction", ["Compañía del Arrecife"], "compania"),
    ("entity:cirro:cofradia-velas", "cirro", "Cofradia de las Velas", "Faction", ["Cofradía de las Velas"], "cofradia"),
    ("entity:cirro:junta-astilleros", "cirro", "Junta de Astilleros", "Faction", [], "junta"),
    ("entity:cirro:sociedad-aerostatos", "cirro", "Sociedad de Aerostatos", "Faction", [], "sociedad"),
    ("entity:cirro:torre-anemos", "cirro", "Torre Anemos", "Location", [], "torre"),
    ("entity:cirro:muelle-alto", "cirro", "Muelle Alto", "Location", [], "muelle"),
    ("entity:cirro:carta-fletes", "cirro", "Carta de Fletes", "Object", [], "documento"),
    # --- zafiro: estaciones de buceo profundo --------------------------------
    ("entity:zafiro:brixa-omal", "zafiro", "Brixa Omal", "Character", [], "buzo"),
    ("entity:zafiro:andres-lupo", "zafiro", "Andres Lupo", "Character", ["Andrés Lupo"], "tecnico"),
    ("entity:zafiro:kena-drovic", "zafiro", "Kena Drovic", "Character", [], "sondista"),
    ("entity:zafiro:tomas-esquil", "zafiro", "Tomas Esquil", "Character", ["Tomás Esquil"], "perlero"),
    ("entity:zafiro:lira-fenn", "zafiro", "Lira Fenn", "Character", [], "instructora"),
    ("entity:zafiro:goran-ute", "zafiro", "Goran Ute", "Character", [], "capataz"),
    ("entity:zafiro:paz-ontiveros", "zafiro", "Paz Ontiveros", "Character", [], "delegada"),
    ("entity:zafiro:sindicato-abisal", "zafiro", "Sindicato Abisal", "Faction", [], "sindicato"),
    ("entity:zafiro:escuela-corriente", "zafiro", "Escuela de la Corriente", "Faction", [], "escuela"),
    ("entity:zafiro:flota-perlera", "zafiro", "Flota Perlera", "Faction", [], "flota"),
    ("entity:zafiro:circulo-sonda", "zafiro", "Circulo de la Sonda", "Faction", ["Círculo de la Sonda"], "circulo"),
    ("entity:zafiro:domo-tres", "zafiro", "Domo Tres", "Location", [], "domo"),
    ("entity:zafiro:fosa-clara", "zafiro", "Fosa Clara", "Location", [], "fosa"),
    ("entity:zafiro:sonda-madre", "zafiro", "Sonda Madre", "Object", [], "sonda"),
    # --- ambar: archivo escaneado de un reino resinoso -----------------------
    ("entity:ambar:veli-ardun", "ambar", "Veli Ardun", "Character", ["Veli Ardún"], "legado"),
    ("entity:ambar:jonas-treme", "ambar", "Jonas Treme", "Character", ["Jonás Treme"], "canciller"),
    ("entity:ambar:sabela-orin", "ambar", "Sabela Orin", "Character", ["Sabela Orín"], "dama"),
    ("entity:ambar:cirilo-nadal", "ambar", "Cirilo Nadal", "Character", [], "escudero"),
    ("entity:ambar:otilia-vasque", "ambar", "Otilia Vasque", "Character", [], "condestable"),
    ("entity:ambar:corte-resina", "ambar", "Corte de la Resina", "Faction", [], "corte"),
    ("entity:ambar:cofradia-lacre", "ambar", "Cofradia del Lacre", "Faction", ["Cofradía del Lacre"], "cofradia"),
    ("entity:ambar:mesnada-ocre", "ambar", "Mesnada Ocre", "Faction", [], "mesnada"),
    ("entity:ambar:villa-savia", "ambar", "Villa Savia", "Location", [], "villa"),
    ("entity:ambar:anillo-ambar", "ambar", "Anillo de Ambar", "Object", ["Anillo de Ámbar"], "joya"),
]

# --------------------------------------------------------------------------
# Fuentes
# --------------------------------------------------------------------------
SOURCES = [
    {
        "source_id": "basalto-cronica",
        "world": "basalto",
        "title": "Cronica de las fraguas",
        "source_kind": "MARKDOWN",
        "mime_type": "text/markdown",
        "modality": "TEXT",
        "media_type": "EMBEDDED_TEXT",
        "collection_id": "collection:basalto",
        "calendar_id": "calendar:basalto",
        "description": "Cronica en prosa. Negacion simple, NEVER, negacion de cesacion y doble negacion.",
    },
    {
        "source_id": "cirro-actas",
        "world": "cirro",
        "title": "Actas del Consejo de los Vientos",
        "source_kind": "MARKDOWN",
        "mime_type": "text/markdown",
        "modality": "TEXT",
        "media_type": "EMBEDDED_TEXT",
        "collection_id": "collection:cirro",
        "calendar_id": "calendar:cirro",
        "description": "Actas administrativas. Cesaciones, negaciones de cesacion y alcance en subordinadas.",
    },
    {
        "source_id": "zafiro-sesion",
        "world": "zafiro",
        "title": "Sesion grabada del Domo Tres",
        "source_kind": "AUDIO",
        "mime_type": "audio/ogg",
        "modality": "SPEAKER_TURN",
        "media_type": "ASR_TEXT",
        "collection_id": "collection:zafiro",
        "calendar_id": "calendar:zafiro",
        "description": "Turnos de habla transcritos por ASR. NOT_YET, alcance y ruido fonetico.",
    },
    {
        "source_id": "ambar-escaneo",
        "world": "ambar",
        "title": "Escaneo del archivo de Villa Savia",
        "source_kind": "IMAGE",
        "mime_type": "image/tiff",
        "modality": "OCR_TEXT",
        "media_type": "OCR_TEXT",
        "collection_id": "collection:ambar",
        "calendar_id": "calendar:ambar",
        "description": "Paginas escaneadas con OCR degradado. Rumores, condicionales y casos sin claim.",
    },
]


def _c(
    subject,
    predicate,
    obj,
    anchor,
    *,
    negated,
    direction="SUBJECT_TO_OBJECT",
    epistemic="ASSERTED",
    role="PRIMARY",
    cues=(),
):
    """Un claim gold: (superficie, entidad) de sujeto y objeto, mas su cita."""
    return {
        "role": role,
        "subject": subject,
        "object": obj,
        "predicate": predicate,
        "direction": direction,
        "negated": negated,
        "epistemic": epistemic,
        "anchor": anchor,
        "epistemic_cues": list(cues),
    }


# Atajos de superficie/entidad
B = "entity:basalto:"
C = "entity:cirro:"
Z = "entity:zafiro:"
A = "entity:ambar:"

# --------------------------------------------------------------------------
# LOS 60 CASOS
# --------------------------------------------------------------------------
CASES = [
    # =====================================================================
    # basalto-cronica  (18): SIMPLE x6, NEVER x4, NEGATED_CESSATION x4,
    #                        DOUBLE_NEGATION x2, POSITIVE_CONTROL x2
    # =====================================================================
    {
        "id": "NEG-SIMPLE-01",
        "source": "basalto-cronica",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": (
            "Conviene dejarlo dicho de una vez, porque la copia de Puerto Escoria lo "
            "arrastra mal desde hace tres ciclos: Harun Vell no pertenece a la Orden "
            "de la Obsidiana."
        ),
        "claims": [
            _c(("Harun Vell", B + "harun-vell"), "MEMBER_OF",
               ("Orden de la Obsidiana", B + "orden-obsidiana"),
               "Harun Vell no pertenece a la Orden de la Obsidiana", negated=True),
        ],
        "extra_mentions": [("Puerto Escoria", B + "puerto-escoria")],
        "traps": ["marca de negacion tras dos puntos, al final de un periodo largo"],
        "rationale": "Negacion simple canonica: una marca, una clausula, alcance cerrado.",
    },
    {
        "id": "NEG-SIMPLE-02",
        "source": "basalto-cronica",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "PASSIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": (
            "La Hermandad de la Fumarola no es dirigida por Sira Delantre, y el "
            "registro de mando de la temporada lo confirma."
        ),
        "claims": [
            _c(("Hermandad de la Fumarola", B + "hermandad-fumarola"), "LED_BY",
               ("Sira Delantre", B + "sira-delantre"),
               "La Hermandad de la Fumarola no es dirigida por Sira Delantre",
               negated=True),
        ],
        "extra_mentions": [],
        "traps": ["pasiva perifrastica: el sujeto sintactico es la faccion, no la persona"],
        "rationale": "La voz pasiva invierte el orden superficial; el predicado inverso (LED_BY) lo absorbe.",
    },
    {
        "id": "NEG-SIMPLE-03",
        "source": "basalto-cronica",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "AFTER_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "Nerea Tossa, hermana de Beltrán Osk, no lo es.",
        "claims": [
            _c(("Nerea Tossa", B + "nerea-tossa"), "SIBLING_OF",
               ("Beltrán Osk", B + "beltran-osk"),
               "Nerea Tossa, hermana de Beltrán Osk, no lo es",
               negated=True, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": [
            "la marca de negacion va DESPUES del foco",
            "el predicado aparece en un inciso afirmativo y se niega con un pronombre atono",
        ],
        "rationale": "Topicalizacion con negacion final: leer solo hasta el inciso da la relacion invertida.",
    },
    {
        "id": "NEG-SIMPLE-04",
        "source": "basalto-cronica",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "PERIFRASIS_MAS_SUBJUNTIVO",
        "noise": "NONE",
        "text": (
            "El Gremio de Fundidores acaba de desmentir por escrito que Mira Cauce "
            "figure entre sus miembros."
        ),
        "claims": [
            _c(("Gremio de Fundidores", B + "gremio-fundidores"), "HAS_MEMBER",
               ("Mira Cauce", B + "mira-cauce"),
               "El Gremio de Fundidores acaba de desmentir por escrito que Mira Cauce "
               "figure entre sus miembros",
               negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "negacion LEXICA: no aparece la palabra 'no'",
            "perifrasis 'acaba de' + subjuntivo en la subordinada",
        ],
        "rationale": (
            "'Desmentir que P' niega P de forma factiva. Un detector basado en la palabra "
            "'no' se lo pierde entero."
        ),
    },
    {
        "id": "NEG-SIMPLE-05",
        "source": "basalto-cronica",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": (
            "El censo de la temporada trae poco nuevo. Se confirma la reparacion del "
            "malecon, se anota el traslado de dos hornos y se corrige la grafia de tres "
            "apellidos. Entre las correcciones importa una: el Sello de Lava no es "
            "propiedad de Teo Ravasi, por mas que asi figurase en la copia anterior."
        ),
        "claims": [
            _c(("Sello de Lava", B + "sello-lava"), "OWNED_BY",
               ("Teo Ravasi", B + "teo-ravasi"),
               "el Sello de Lava no es propiedad de Teo Ravasi", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "parrafo largo con tres oraciones afirmativas antes de la negacion",
            "coletilla concesiva posterior ('por mas que asi figurase') que reafirma lo contrario",
        ],
        "rationale": "Longitud y ruido administrativo alrededor de la unica relacion que importa.",
    },
    {
        "id": "NEG-SIMPLE-06",
        "source": "basalto-cronica",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BETWEEN_ARGUMENTS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "En Isla Tenaza no tiene sede la Casa Verrant, aunque muchos lo den por hecho.",
        "claims": [
            _c(("Casa Verrant", B + "casa-verrant"), "LOCATED_IN",
               ("Isla Tenaza", B + "isla-tenaza"),
               "En Isla Tenaza no tiene sede la Casa Verrant", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "orden invertido: el objeto abre la oracion y el sujeto la cierra",
            "la marca queda ENTRE los dos argumentos",
        ],
        "rationale": "Si el mapeo sujeto/objeto se hace por orden de aparicion, este caso lo rompe.",
    },
    {
        "id": "NEG-NEVER-01",
        "source": "basalto-cronica",
        "family": "NEVER",
        "kind": "NEVER",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "knowledge_horizon": "1041-12-31T00:00:00Z",
        "text": (
            "Ilde Varona nunca pertenecio al Conclave de la Ceniza. Esta cronica cubre "
            "desde la fundacion hasta el ciclo 41 y no dice nada de lo que venga despues."
        ),
        "claims": [
            _c(("Ilde Varona", B + "ilde-varona"), "MEMBER_OF",
               ("Conclave de la Ceniza", B + "conclave-ceniza"),
               "Ilde Varona nunca pertenecio al Conclave de la Ceniza", negated=True),
        ],
        "extra_mentions": [],
        "traps": ["la fuente declara su propio horizonte de conocimiento en la frase siguiente"],
        "rationale": (
            "NEVER con horizonte explicito: la afirmacion se cierra en el ciclo 41. "
            "Sin ese anclaje, el 'nunca' se convertiria en una afirmacion sobre el futuro."
        ),
    },
    {
        "id": "NEG-NEVER-02",
        "source": "basalto-cronica",
        "family": "NEVER",
        "kind": "NEVER",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "PASSIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "knowledge_horizon": "1041-12-31T00:00:00Z",
        "text": (
            "La Orden de la Obsidiana jamas fue dirigida por Kaspar Nune, ni siquiera "
            "durante el interregno del ciclo 38."
        ),
        "claims": [
            _c(("Orden de la Obsidiana", B + "orden-obsidiana"), "LED_BY",
               ("Kaspar Nune", B + "kaspar-nune"),
               "La Orden de la Obsidiana jamas fue dirigida por Kaspar Nune",
               negated=True),
        ],
        "extra_mentions": [],
        "traps": ["'jamas' en vez de 'nunca'", "pasiva + refuerzo concesivo 'ni siquiera'"],
        "rationale": "Misma familia, otra marca lexica y otra voz.",
    },
    {
        "id": "NEG-NEVER-03",
        "source": "basalto-cronica",
        "family": "NEVER",
        "kind": "NEVER",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "knowledge_horizon": "1041-12-31T00:00:00Z",
        "text": (
            "En ningun momento de las cuatro generaciones que cubre esta cronica el "
            "Yunque Negro estuvo en manos del Gremio de Fundidores."
        ),
        "claims": [
            _c(("Yunque Negro", B + "yunque-negro"), "OWNED_BY",
               ("Gremio de Fundidores", B + "gremio-fundidores"),
               "En ningun momento de las cuatro generaciones que cubre esta cronica el "
               "Yunque Negro estuvo en manos del Gremio de Fundidores", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "la marca es una locucion ('en ningun momento'), no un adverbio simple",
            "veintiun caracteres de adverbial antepuesto antes del sujeto",
        ],
        "rationale": "NEVER expresado como cuantificacion temporal negativa antepuesta.",
    },
    {
        "id": "NEG-NEVER-04",
        "source": "basalto-cronica",
        "family": "NEVER",
        "kind": "NEVER",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BETWEEN_ARGUMENTS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "knowledge_horizon": "1041-12-31T00:00:00Z",
        "text": (
            "Runa Belisa y Beltrán Osk no fueron hermanos en ningun caso: los padrones "
            "los separan por dos linajes distintos."
        ),
        "claims": [
            _c(("Runa Belisa", B + "runa-belisa"), "SIBLING_OF",
               ("Beltrán Osk", B + "beltran-osk"),
               "Runa Belisa y Beltrán Osk no fueron hermanos en ningun caso",
               negated=True, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": [
            "predicado SIMETRICO negado: (A,B) y (B,A) son el mismo hecho negativo",
            "doble marca ('no' + 'en ningun caso') que NO se cancela: es refuerzo",
        ],
        "rationale": (
            "Concordancia negativa del espanol: dos marcas refuerzan, no cancelan. "
            "Es la trampa espejo de la doble negacion real."
        ),
    },
    {
        "id": "NEG-NEGCESS-01",
        "source": "basalto-cronica",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "reading": "CONTINUITY",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
        "text": (
            "Sira Delantre no dejo de servir a la Casa Verrant cuando estallo el motin "
            "de los hornos; siguio en su puesto hasta el final de la temporada."
        ),
        "claims": [
            _c(("Sira Delantre", B + "sira-delantre"), "MEMBER_OF",
               ("Casa Verrant", B + "casa-verrant"),
               "Sira Delantre no dejo de servir a la Casa Verrant", negated=False),
        ],
        "extra_mentions": [],
        "traps": ["'no dejo de' contiene literalmente la marca de cesacion 'dejo de'"],
        "rationale": (
            "El caso que define el bloque: 'no dejo de X' NUNCA puede convertirse en "
            "'dejo de X'. Aqui la lectura es continuidad, no cesacion ni arista negativa."
        ),
    },
    {
        "id": "NEG-NEGCESS-02",
        "source": "basalto-cronica",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_IMPERFECTO",
        "noise": "NONE",
        "reading": "CONTINUITY",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
        "text": "No es cierto que Olmo Quiral abandonase el Foso Humeante.",
        "claims": [
            _c(("Olmo Quiral", B + "olmo-quiral"), "LOCATED_IN",
               ("Foso Humeante", B + "foso-humeante"),
               "No es cierto que Olmo Quiral abandonase el Foso Humeante", negated=False),
        ],
        "extra_mentions": [],
        "traps": [
            "la negacion esta en la matriz y la cesacion en la subordinada",
            "subjuntivo imperfecto ('abandonase')",
        ],
        "rationale": "Negacion de una cesacion con la marca a dos clausulas de distancia del verbo de cese.",
    },
    {
        "id": "NEG-NEGCESS-03",
        "source": "basalto-cronica",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "PASSIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "reading": "CONTINUITY",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
        "text": (
            "La Hermandad de la Fumarola no fue abandonada por Nerea Tossa, por mucho "
            "que el panfleto lo repita."
        ),
        "claims": [
            _c(("Hermandad de la Fumarola", B + "hermandad-fumarola"), "HAS_MEMBER",
               ("Nerea Tossa", B + "nerea-tossa"),
               "La Hermandad de la Fumarola no fue abandonada por Nerea Tossa",
               negated=False),
        ],
        "extra_mentions": [],
        "traps": ["cesacion en pasiva ('fue abandonada por') bajo negacion"],
        "rationale": "Pasiva + cesacion negada: dos transformaciones a la vez sobre la misma relacion.",
    },
    {
        "id": "NEG-NEGCESS-04",
        "source": "basalto-cronica",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "reading": "CONTINUITY",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
        "text": (
            "Beltrán Osk dimitio de tres cargos menores aquel invierno, pero no dejo de "
            "liderar el Conclave de la Ceniza."
        ),
        "claims": [
            _c(("Beltrán Osk", B + "beltran-osk"), "LEADS",
               ("Conclave de la Ceniza", B + "conclave-ceniza"),
               "no dejo de liderar el Conclave de la Ceniza", negated=False),
        ],
        "extra_mentions": [],
        "traps": [
            "una cesacion REAL ('dimitio de tres cargos') en la clausula anterior",
            "la cesacion real y la negada comparten sujeto",
        ],
        "rationale": (
            "Dos cesaciones en la misma frase, una verdadera y otra negada, con el mismo "
            "sujeto. Cerrar la relacion equivocada es el fallo caro."
        ),
    },
    {
        "id": "NEG-DOUBLE-01",
        "source": "basalto-cronica",
        "family": "DOUBLE_NEGATION",
        "kind": "DOUBLE_NEGATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PRESENTE",
        "noise": "NONE",
        "reading": "NET_POSITIVE",
        "forbidden_outcomes": ["NEGATIVE_EDGE"],
        "text": "No es falso que Mira Cauce sea aliada de Ilde Varona.",
        "claims": [
            _c(("Mira Cauce", B + "mira-cauce"), "ALLY_OF",
               ("Ilde Varona", B + "ilde-varona"),
               "No es falso que Mira Cauce sea aliada de Ilde Varona",
               negated=False, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": ["dos negaciones que SI se cancelan: la lectura neta es afirmativa"],
        "rationale": (
            "'No es falso que P' equivale a P. Emitir una arista negativa aqui es "
            "invertir el hecho."
        ),
    },
    {
        "id": "NEG-DOUBLE-02",
        "source": "basalto-cronica",
        "family": "DOUBLE_NEGATION",
        "kind": "DOUBLE_NEGATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INFINITIVO_MAS_INDICATIVO",
        "noise": "NONE",
        "reading": "NET_NEGATIVE",
        "forbidden_outcomes": ["POSITIVE_EDGE"],
        "text": (
            "Nadie puede negar que el Puerto Escoria no esta bajo el control del Gremio "
            "de Fundidores."
        ),
        "claims": [
            _c(("Puerto Escoria", B + "puerto-escoria"), "OWNED_BY",
               ("Gremio de Fundidores", B + "gremio-fundidores"),
               "Nadie puede negar que el Puerto Escoria no esta bajo el control del "
               "Gremio de Fundidores", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "TRES marcas ('Nadie', 'negar', 'no') y la lectura neta sigue siendo NEGATIVA",
            "es el reverso exacto de NEG-DOUBLE-01: contar marcas y aplicar paridad falla aqui",
        ],
        "rationale": (
            "Un sistema que resuelva la doble negacion contando marcas modulo dos acierta "
            "DOUBLE-01 y falla este. Van en pareja a proposito."
        ),
    },
    {
        "id": "NEG-POS-01",
        "source": "basalto-cronica",
        "family": "POSITIVE_CONTROL",
        "kind": "NONE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "NONE",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "Teo Ravasi lidera el Gremio de Fundidores desde el ciclo 39.",
        "claims": [
            _c(("Teo Ravasi", B + "teo-ravasi"), "LEADS",
               ("Gremio de Fundidores", B + "gremio-fundidores"),
               "Teo Ravasi lidera el Gremio de Fundidores", negated=False),
        ],
        "extra_mentions": [],
        "traps": [],
        "rationale": "Control positivo limpio: si la politica de negacion lo toca, contamina el camino positivo.",
    },
    {
        "id": "NEG-POS-02",
        "source": "basalto-cronica",
        "family": "POSITIVE_CONTROL",
        "kind": "NONE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "NONE",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": (
            "Harun Vell no llego a tiempo al conclave de invierno, pero Sira Delantre "
            "pertenece a la Orden de la Obsidiana desde hace siete ciclos."
        ),
        "claims": [
            _c(("Sira Delantre", B + "sira-delantre"), "MEMBER_OF",
               ("Orden de la Obsidiana", B + "orden-obsidiana"),
               "Sira Delantre pertenece a la Orden de la Obsidiana", negated=False),
        ],
        "extra_mentions": [("Harun Vell", B + "harun-vell")],
        "traps": [
            "hay una marca de negacion en el episodio que NO afecta a la relacion anotada",
            "'conclave de invierno' en minuscula NO es el Conclave de la Ceniza",
        ],
        "rationale": (
            "Negacion en una clausula ajena. Si el alcance se calcula por episodio y no "
            "por clausula, esta relacion positiva sale negada."
        ),
    },

    # =====================================================================
    # cirro-actas (16): CESSATION x7, NEGATED_CESSATION x4,
    #                   SCOPE_EMBEDDED x3, POSITIVE_CONTROL x2
    # =====================================================================
    {
        "id": "NEG-CESS-01",
        "source": "cirro-actas",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "Dagna Hoill ya no lidera el Consejo de los Vientos.",
        "claims": [
            _c(("Dagna Hoill", C + "dagna-hoill"), "LEADS",
               ("Consejo de los Vientos", C + "consejo-vientos"),
               "Dagna Hoill ya no lidera el Consejo de los Vientos", negated=True),
        ],
        "extra_mentions": [],
        "traps": [],
        "rationale": "Cesacion canonica. Puede cerrar una afirmacion existente: revision siempre en esta fase.",
    },
    {
        "id": "NEG-CESS-02",
        "source": "cirro-actas",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "text": "Pol Arriaga dejo de pertenecer a la Compania del Arrecife el pasado equinoccio.",
        "claims": [
            _c(("Pol Arriaga", C + "pol-arriaga"), "MEMBER_OF",
               ("Compania del Arrecife", C + "compania-arrecife"),
               "Pol Arriaga dejo de pertenecer a la Compania del Arrecife", negated=True),
        ],
        "extra_mentions": [],
        "traps": ["fecha relativa ('el pasado equinoccio') sin ancla absoluta"],
        "rationale": "Cesacion con temporalidad relativa: requiere resolucion temporal antes de cerrar nada.",
    },
    {
        "id": "NEG-CESS-03",
        "source": "cirro-actas",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "PASSIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "text": "La Cofradia de las Velas fue abandonada por Vera Luntz tras el tercer laudo.",
        "claims": [
            _c(("Cofradia de las Velas", C + "cofradia-velas"), "HAS_MEMBER",
               ("Vera Luntz", C + "vera-luntz"),
               "La Cofradia de las Velas fue abandonada por Vera Luntz", negated=True),
        ],
        "extra_mentions": [],
        "traps": ["cesacion en pasiva SIN ninguna marca de negacion explicita"],
        "rationale": "La cesacion no siempre trae un 'no' delante: aqui la marca es el verbo.",
    },
    {
        "id": "NEG-CESS-04",
        "source": "cirro-actas",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "PASSIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "text": (
            "Ismael Corvo fue destituido de la presidencia de la Junta de Astilleros por "
            "unanimidad de la sala."
        ),
        "claims": [
            _c(("Ismael Corvo", C + "ismael-corvo"), "LEADS",
               ("Junta de Astilleros", C + "junta-astilleros"),
               "Ismael Corvo fue destituido de la presidencia de la Junta de Astilleros",
               negated=True),
        ],
        "extra_mentions": [],
        "traps": ["'destituido de' como cesacion; el cargo aparece como sustantivo, no como verbo"],
        "rationale": "Cesacion nominalizada: 'la presidencia de X' hay que mapearla al predicado LEADS.",
    },
    {
        "id": "NEG-CESS-05",
        "source": "cirro-actas",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "text": (
            "Punto cuarto del orden del dia. Se leyo el informe de fletes, se aprobo sin "
            "enmiendas y se paso a la cuestion pendiente. Tanit Pereo ceso en su "
            "condicion de miembro de la Sociedad de Aerostatos con efecto inmediato, y "
            "asi se hara constar."
        ),
        "claims": [
            _c(("Tanit Pereo", C + "tanit-pereo"), "MEMBER_OF",
               ("Sociedad de Aerostatos", C + "sociedad-aerostatos"),
               "Tanit Pereo ceso en su condicion de miembro de la Sociedad de Aerostatos",
               negated=True),
        ],
        "extra_mentions": [],
        "traps": ["parrafo de acta con tres oraciones de tramite antes de la cesacion"],
        "rationale": "Cesacion enterrada en prosa administrativa larga.",
    },
    {
        "id": "NEG-CESS-06",
        "source": "cirro-actas",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "text": (
            "El Muelle Alto salio del patrimonio de la Compania del Arrecife cuando se "
            "ejecuto la garantia."
        ),
        "claims": [
            _c(("Muelle Alto", C + "muelle-alto"), "OWNED_BY",
               ("Compania del Arrecife", C + "compania-arrecife"),
               "El Muelle Alto salio del patrimonio de la Compania del Arrecife",
               negated=True),
        ],
        "extra_mentions": [],
        "traps": ["cesacion expresada como movimiento ('salio del patrimonio de')"],
        "rationale": "Ni 'dejo de' ni 'ya no': la cesacion viaja en una metafora patrimonial.",
    },
    {
        "id": "NEG-CESS-07",
        "source": "cirro-actas",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "text": "Hugo Marlén y Selva Ondiz rompieron su alianza el mismo dia en que se sello el laudo.",
        "claims": [
            _c(("Hugo Marlén", C + "hugo-marlen"), "ALLY_OF",
               ("Selva Ondiz", C + "selva-ondiz"),
               "Hugo Marlén y Selva Ondiz rompieron su alianza",
               negated=True, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": ["cesacion de un predicado SIMETRICO: cierra el hecho en los dos sentidos"],
        "rationale": "Romper una alianza simetrica no es 'A deja de ser aliado de B' solamente.",
    },
    {
        "id": "NEG-NEGCESS-05",
        "source": "cirro-actas",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "reading": "CONTINUITY",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
        "text": (
            "Radi Oster no ceso en la direccion de la Cofradia de las Velas, pese al acta "
            "que circulo por el Muelle Alto."
        ),
        "claims": [
            _c(("Radi Oster", C + "radi-oster"), "LEADS",
               ("Cofradia de las Velas", C + "cofradia-velas"),
               "Radi Oster no ceso en la direccion de la Cofradia de las Velas",
               negated=False),
        ],
        "extra_mentions": [("Muelle Alto", C + "muelle-alto")],
        "traps": ["'no ceso en' con el verbo de cese distinto de 'dejar de'"],
        "rationale": "Misma trampa que 'no dejo de', con otro verbo de cesacion.",
    },
    {
        "id": "NEG-NEGCESS-06",
        "source": "cirro-actas",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_COMPUESTO",
        "noise": "NONE",
        "reading": "NO_RECORD",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE", "POSITIVE_EDGE"],
        "text": "No consta que Noa Quimper haya abandonado la Junta de Astilleros.",
        "claims": [
            _c(("Noa Quimper", C + "noa-quimper"), "MEMBER_OF",
               ("Junta de Astilleros", C + "junta-astilleros"),
               "No consta que Noa Quimper haya abandonado la Junta de Astilleros",
               negated=False, epistemic="UNKNOWN",
               cues=["No consta que"]),
        ],
        "extra_mentions": [],
        "traps": [
            "'no consta que' NO afirma continuidad: afirma ausencia de registro",
            "es la unica NEGATED_CESSATION cuya lectura no es continuidad",
        ],
        "rationale": (
            "Confundir 'no consta que se fuera' con 'sigue' es inventar evidencia. "
            "Ni cesacion ni continuidad: falta de dato."
        ),
    },
    {
        "id": "NEG-NEGCESS-07",
        "source": "cirro-actas",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "AFTER_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INFINITIVO_ANTEPUESTO",
        "noise": "NONE",
        "reading": "CONTINUITY",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
        "text": "Dejar el Consejo de los Vientos, Vera Luntz no lo dejo.",
        "claims": [
            _c(("Vera Luntz", C + "vera-luntz"), "MEMBER_OF",
               ("Consejo de los Vientos", C + "consejo-vientos"),
               "Dejar el Consejo de los Vientos, Vera Luntz no lo dejo", negated=False),
        ],
        "extra_mentions": [],
        "traps": [
            "el infinitivo de cesacion ABRE la frase y la negacion la CIERRA",
            "el objeto aparece antes que el sujeto y antes que la marca",
        ],
        "rationale": (
            "Si la ventana de alcance mira solo hacia adelante desde la marca, aqui no "
            "encuentra ni el verbo ni el objeto."
        ),
    },
    {
        "id": "NEG-NEGCESS-08",
        "source": "cirro-actas",
        "family": "NEGATED_CESSATION",
        "kind": "NEGATED_CESSATION",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "PASSIVE",
        "verb_form": "PERFECTO_COMPUESTO",
        "noise": "NONE",
        "reading": "CONTINUITY",
        "forbidden_outcomes": ["CESSATION", "CLOSE_ASSERTION", "NEGATIVE_EDGE"],
        "text": (
            "La Sociedad de Aerostatos no ha dejado de estar dirigida por Ismael Corvo en "
            "ningun momento de este ejercicio."
        ),
        "claims": [
            _c(("Sociedad de Aerostatos", C + "sociedad-aerostatos"), "LED_BY",
               ("Ismael Corvo", C + "ismael-corvo"),
               "La Sociedad de Aerostatos no ha dejado de estar dirigida por Ismael Corvo "
               "en ningun momento de este ejercicio", negated=False),
        ],
        "extra_mentions": [],
        "traps": [
            "TRES elementos negativos: 'no', 'dejado de' y 'en ningun momento'",
            "encima, en pasiva y con perfecto compuesto",
        ],
        "rationale": (
            "Acumulacion maxima de marcas con lectura neta de continuidad. Es el caso "
            "que mas facilmente produce un cierre falso."
        ),
    },
    {
        "id": "NEG-SCOPE-01",
        "source": "cirro-actas",
        "family": "SCOPE_EMBEDDED",
        "kind": "SCOPE_EMBEDDED",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PRESENTE",
        "noise": "NONE",
        "reading": "ATTITUDE_NOT_FACT",
        "forbidden_outcomes": ["NEGATIVE_EDGE"],
        "text": "Pol Arriaga no cree que Tanit Pereo pertenezca a la Cofradia de las Velas.",
        "claims": [
            _c(("Tanit Pereo", C + "tanit-pereo"), "MEMBER_OF",
               ("Cofradia de las Velas", C + "cofradia-velas"),
               "Pol Arriaga no cree que Tanit Pereo pertenezca a la Cofradia de las Velas",
               negated=False, epistemic="UNKNOWN", cues=["no cree que"]),
        ],
        "extra_mentions": [("Pol Arriaga", C + "pol-arriaga")],
        "traps": [
            "la negacion afecta al verbo de actitud, no a la relacion",
            "hay un tercer personaje en la frase que NO participa en la relacion",
        ],
        "rationale": (
            "El ejemplo textual de docs/v3/18: 'A no cree que B pertenezca a C'. La fuente "
            "no niega la pertenencia; reporta una incredulidad."
        ),
    },
    {
        "id": "NEG-SCOPE-02",
        "source": "cirro-actas",
        "family": "SCOPE_EMBEDDED",
        "kind": "SCOPE_EMBEDDED",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PRESENTE",
        "noise": "NONE",
        "reading": "UNDETERMINED",
        "forbidden_outcomes": ["NEGATIVE_EDGE", "POSITIVE_EDGE"],
        "text": "Nadie en la Torre Anemos ha afirmado que Hugo Marlén no dirija la Junta de Astilleros.",
        "claims": [
            _c(("Hugo Marlén", C + "hugo-marlen"), "LEADS",
               ("Junta de Astilleros", C + "junta-astilleros"),
               "Nadie en la Torre Anemos ha afirmado que Hugo Marlén no dirija la Junta "
               "de Astilleros", negated=False, epistemic="UNKNOWN",
               cues=["Nadie", "ha afirmado que"]),
        ],
        "extra_mentions": [("Torre Anemos", C + "torre-anemos")],
        "traps": [
            "una marca en la matriz y otra en la subordinada, en clausulas distintas",
            "la lectura neta no es ni afirmativa ni negativa: es indeterminada",
        ],
        "rationale": "Dos alcances anidados sobre el mismo hecho. Aqui abstenerse o revisar es lo unico honesto.",
    },
    {
        "id": "NEG-SCOPE-03",
        "source": "cirro-actas",
        "family": "SCOPE_EMBEDDED",
        "kind": "SCOPE_EMBEDDED",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PRESENTE",
        "noise": "NONE",
        "reading": "ATTRIBUTED_DENIAL",
        "forbidden_outcomes": [],
        "text": "Selva Ondiz nego que la Carta de Fletes sea propiedad del Consejo de los Vientos.",
        "claims": [
            _c(("Carta de Fletes", C + "carta-fletes"), "OWNED_BY",
               ("Consejo de los Vientos", C + "consejo-vientos"),
               "Selva Ondiz nego que la Carta de Fletes sea propiedad del Consejo de los "
               "Vientos", negated=True, epistemic="UNKNOWN", cues=["nego que"]),
        ],
        "extra_mentions": [("Selva Ondiz", C + "selva-ondiz")],
        "traps": [
            "negacion ATRIBUIDA a un hablante: quien niega no es la fuente, es un personaje",
            "compara con NEG-SCOPE-01: alli la matriz negada NO niega el hecho; aqui SI",
        ],
        "rationale": (
            "'X nego que P' si niega P, pero atribuido. La procedencia cambia el estatus "
            "epistemico, no la polaridad. Va a revision porque el alcance depende de "
            "resolver quien afirma."
        ),
    },
    {
        "id": "NEG-POS-03",
        "source": "cirro-actas",
        "family": "POSITIVE_CONTROL",
        "kind": "NONE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "NONE",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "Vera Luntz y Radi Oster son rivales declarados desde el litigio del muelle.",
        "claims": [
            _c(("Vera Luntz", C + "vera-luntz"), "RIVAL_OF",
               ("Radi Oster", C + "radi-oster"),
               "Vera Luntz y Radi Oster son rivales declarados",
               negated=False, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": ["predicado simetrico afirmativo: control de que la simetria no arrastra negacion"],
        "rationale": "Control positivo sobre un predicado simetrico.",
    },
    {
        "id": "NEG-POS-04",
        "source": "cirro-actas",
        "family": "POSITIVE_CONTROL",
        "kind": "NONE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "NONE",
        "voice": "PASSIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "La Compania del Arrecife esta dirigida por Noa Quimper.",
        "claims": [
            _c(("Compania del Arrecife", C + "compania-arrecife"), "LED_BY",
               ("Noa Quimper", C + "noa-quimper"),
               "La Compania del Arrecife esta dirigida por Noa Quimper", negated=False),
        ],
        "extra_mentions": [],
        "traps": ["pasiva AFIRMATIVA, identica en forma a NEG-SIMPLE-02 salvo por el 'no'"],
        "rationale": "Par minimo con NEG-SIMPLE-02: una sola palabra separa el positivo del negativo.",
    },

    # =====================================================================
    # zafiro-sesion (15): SIMPLE x4, NOT_YET x5, SCOPE_EMBEDDED x2,
    #                     CESSATION x2, POSITIVE_CONTROL x2
    # =====================================================================
    {
        "id": "NEG-SIMPLE-07",
        "source": "zafiro-sesion",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "ASR",
        "text": "no brixa omal no forma parte del sindicato abisal eso fue un error del acta anterior",
        "corrected": (
            "No, Brixa Omal no forma parte del Sindicato Abisal. Eso fue un error del "
            "acta anterior."
        ),
        "claims": [
            _c(("brixa omal", Z + "brixa-omal"), "MEMBER_OF",
               ("sindicato abisal", Z + "sindicato-abisal"),
               "brixa omal no forma parte del sindicato abisal", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "ASR sin puntuacion ni mayusculas",
            "el PRIMER 'no' es un marcador de discurso, no una negacion de la relacion",
            "hay dos 'no' en el turno y solo uno cuenta",
        ],
        "rationale": (
            "Contar marcas de negacion aqui da dos y la paridad diria 'afirmativo'. "
            "Es negativo: el primer 'no' responde a la pregunta anterior."
        ),
    },
    {
        "id": "NEG-SIMPLE-08",
        "source": "zafiro-sesion",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "ASR",
        "orthogonal_risk": "ENTITY_FUZZY",
        "text": "Que quede claro en acta: Goran Hute no es aliado del Circulo de la Zonda.",
        "corrected": "Que quede claro en acta: Goran Ute no es aliado del Circulo de la Sonda.",
        "claims": [
            _c(("Goran Hute", Z + "goran-ute"), "ALLY_OF",
               ("Circulo de la Zonda", Z + "circulo-sonda"),
               "Goran Hute no es aliado del Circulo de la Zonda",
               negated=True, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": [
            "ASR fonetico: 'Hute' por 'Ute' (hache muda) y 'Zonda' por 'Sonda' (seseo)",
            "las dos entidades llegan degradadas a la vez",
        ],
        "rationale": (
            "El eje que mide este caso es la negacion, no la identidad. Si se revisa por "
            "duda de entidad, eso NO cuenta como fallo de la politica de negacion."
        ),
    },
    {
        "id": "NEG-SIMPLE-09",
        "source": "zafiro-sesion",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "Paz Ontiveros no pertenece a la Flota Perlera; quien si figura en su rol es Tomás Esquil.",
        "claims": [
            _c(("Paz Ontiveros", Z + "paz-ontiveros"), "MEMBER_OF",
               ("Flota Perlera", Z + "flota-perlera"),
               "Paz Ontiveros no pertenece a la Flota Perlera", negated=True),
            _c(("Tomás Esquil", Z + "tomas-esquil"), "MEMBER_OF",
               ("Flota Perlera", Z + "flota-perlera"),
               "quien si figura en su rol es Tomás Esquil",
               negated=False, role="SECONDARY"),
        ],
        "extra_mentions": [],
        "traps": [
            "DOS relaciones en el mismo episodio, una negada y otra afirmada",
            "comparten objeto: la Flota Perlera aparece una sola vez en el texto",
            "el segundo sujeto se recupera por una relativa ('quien si figura en su rol')",
        ],
        "rationale": (
            "El alcance de la negacion tiene que pararse en el punto y coma. Si no, la "
            "pertenencia de Tomas sale negada tambien."
        ),
    },
    {
        "id": "NEG-SIMPLE-10",
        "source": "zafiro-sesion",
        "family": "SIMPLE",
        "kind": "SIMPLE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "AFTER_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": (
            "Lo repito porque en la sesion anterior se anoto al reves: el Domo Tres, en "
            "la Fosa Clara, no se encuentra."
        ),
        "claims": [
            _c(("Domo Tres", Z + "domo-tres"), "LOCATED_IN",
               ("Fosa Clara", Z + "fosa-clara"),
               "el Domo Tres, en la Fosa Clara, no se encuentra", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "la marca va al final, despues de los dos argumentos",
            "el inciso locativo parece afirmar la contencion espacial",
        ],
        "rationale": "Contencion espacial negada con la marca en posicion final.",
    },
    {
        "id": "NEG-NOTYET-01",
        "source": "zafiro-sesion",
        "family": "NOT_YET",
        "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "reading": "NEGATIVE_NOW_OPEN_LATER",
        "forbidden_outcomes": ["PERMANENT_NEGATIVE_EDGE"],
        "text": "Lira Fenn todavia no lidera la Escuela de la Corriente; la votacion es el mes que viene.",
        "claims": [
            _c(("Lira Fenn", Z + "lira-fenn"), "LEADS",
               ("Escuela de la Corriente", Z + "escuela-corriente"),
               "Lira Fenn todavia no lidera la Escuela de la Corriente", negated=True),
        ],
        "extra_mentions": [],
        "traps": ["'todavia no' implica que se espera que SI ocurra: la negacion tiene fecha de caducidad"],
        "rationale": (
            "Un NOT_YET escrito como negacion permanente es falso a partir de la votacion. "
            "Por eso no es autoaprobable."
        ),
    },
    {
        "id": "NEG-NOTYET-02",
        "source": "zafiro-sesion",
        "family": "NOT_YET",
        "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "reading": "NEGATIVE_NOW_OPEN_LATER",
        "forbidden_outcomes": ["PERMANENT_NEGATIVE_EDGE"],
        "text": "Aun no pertenece Tomás Esquil al Sindicato Abisal.",
        "claims": [
            _c(("Tomás Esquil", Z + "tomas-esquil"), "MEMBER_OF",
               ("Sindicato Abisal", Z + "sindicato-abisal"),
               "Aun no pertenece Tomás Esquil al Sindicato Abisal", negated=True),
        ],
        "extra_mentions": [],
        "traps": ["'aun no' antepuesto y sujeto pospuesto al verbo"],
        "rationale": "Mismo fenomeno con otra marca y orden verbo-sujeto.",
    },
    {
        "id": "NEG-NOTYET-03",
        "source": "zafiro-sesion",
        "family": "NOT_YET",
        "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BETWEEN_ARGUMENTS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "ASR",
        "reading": "NEGATIVE_NOW_OPEN_LATER",
        "forbidden_outcomes": ["PERMANENT_NEGATIVE_EDGE"],
        "text": "kena drovic no es todavia duena de la sonda madre falta la firma del sindicato",
        "corrected": "Kena Drovic no es todavia dueña de la Sonda Madre; falta la firma del sindicato.",
        "claims": [
            _c(("kena drovic", Z + "kena-drovic"), "OWNS",
               ("sonda madre", Z + "sonda-madre"),
               "kena drovic no es todavia duena de la sonda madre", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "ASR sin tildes ni puntuacion y con 'duena' por 'dueña'",
            "'no ... todavia' con las dos piezas separadas por el verbo",
            "'del sindicato' es un sustantivo de rol truncado: NO se anota como mencion",
        ],
        "rationale": "NOT_YET discontinuo sobre texto degradado.",
    },
    {
        "id": "NEG-NOTYET-04",
        "source": "zafiro-sesion",
        "family": "NOT_YET",
        "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "PASSIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "reading": "NEGATIVE_NOW_OPEN_LATER",
        "forbidden_outcomes": ["PERMANENT_NEGATIVE_EDGE"],
        "text": "La Flota Perlera no esta aun dirigida por Brixa Omal.",
        "claims": [
            _c(("Flota Perlera", Z + "flota-perlera"), "LED_BY",
               ("Brixa Omal", Z + "brixa-omal"),
               "La Flota Perlera no esta aun dirigida por Brixa Omal", negated=True),
        ],
        "extra_mentions": [],
        "traps": ["NOT_YET en pasiva, con 'aun' intercalado dentro de la perifrasis"],
        "rationale": "NOT_YET + pasiva: dos transformaciones sobre la misma relacion.",
    },
    {
        "id": "NEG-NOTYET-05",
        "source": "zafiro-sesion",
        "family": "NOT_YET",
        "kind": "NOT_YET",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "AFTER_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PRESENTE",
        "noise": "NONE",
        "reading": "NEGATIVE_NOW_OPEN_LATER",
        "forbidden_outcomes": ["PERMANENT_NEGATIVE_EDGE"],
        "text": "Que Paz Ontiveros y Goran Ute sean aliados no ha ocurrido todavia.",
        "claims": [
            _c(("Paz Ontiveros", Z + "paz-ontiveros"), "ALLY_OF",
               ("Goran Ute", Z + "goran-ute"),
               "Que Paz Ontiveros y Goran Ute sean aliados no ha ocurrido todavia",
               negated=True, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": [
            "la relacion va en una completiva antepuesta en subjuntivo",
            "la marca esta al final, detras de los dos argumentos y del predicado",
            "predicado simetrico",
        ],
        "rationale": "NOT_YET con la relacion tematizada al principio y la negacion al final.",
    },
    {
        "id": "NEG-SCOPE-04",
        "source": "zafiro-sesion",
        "family": "SCOPE_EMBEDDED",
        "kind": "SCOPE_EMBEDDED",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PRESENTE",
        "noise": "NONE",
        "reading": "ATTITUDE_NOT_FACT",
        "forbidden_outcomes": ["NEGATIVE_EDGE"],
        "text": "Andrés Lupo no admite que la Sonda Madre este en el Domo Tres.",
        "claims": [
            _c(("Sonda Madre", Z + "sonda-madre"), "LOCATED_IN",
               ("Domo Tres", Z + "domo-tres"),
               "Andrés Lupo no admite que la Sonda Madre este en el Domo Tres",
               negated=False, epistemic="UNKNOWN", cues=["no admite que"]),
        ],
        "extra_mentions": [("Andrés Lupo", Z + "andres-lupo")],
        "traps": ["verbo de actitud distinto de 'creer' y objeto no humano"],
        "rationale": "Mismo alcance de subordinada, otro verbo y otros tipos de entidad.",
    },
    {
        "id": "NEG-SCOPE-05",
        "source": "zafiro-sesion",
        "family": "SCOPE_EMBEDDED",
        "kind": "SCOPE_EMBEDDED",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PRESENTE",
        "noise": "NONE",
        "reading": "UNDETERMINED",
        "forbidden_outcomes": ["NEGATIVE_EDGE"],
        "text": "Nadie sostiene que Lira Fenn no sea hermana de Kena Drovic.",
        "claims": [
            _c(("Lira Fenn", Z + "lira-fenn"), "SIBLING_OF",
               ("Kena Drovic", Z + "kena-drovic"),
               "Nadie sostiene que Lira Fenn no sea hermana de Kena Drovic",
               negated=False, direction="UNDIRECTED", epistemic="UNKNOWN",
               cues=["Nadie sostiene que"]),
        ],
        "extra_mentions": [],
        "traps": [
            "marca negativa en la matriz ('Nadie') y otra en la subordinada ('no sea')",
            "predicado simetrico bajo doble alcance",
        ],
        "rationale": (
            "Parece una doble negacion cancelable, pero las marcas viven en clausulas "
            "distintas y no se cancelan: nadie afirma lo contrario no es lo mismo que si."
        ),
    },
    {
        "id": "NEG-CESS-08",
        "source": "zafiro-sesion",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "Tomás Esquil ya no es rival de Paz Ontiveros; hicieron las paces en el Domo Tres.",
        "claims": [
            _c(("Tomás Esquil", Z + "tomas-esquil"), "RIVAL_OF",
               ("Paz Ontiveros", Z + "paz-ontiveros"),
               "Tomás Esquil ya no es rival de Paz Ontiveros",
               negated=True, direction="UNDIRECTED"),
        ],
        "extra_mentions": [("Domo Tres", Z + "domo-tres")],
        "traps": ["cesacion de un predicado simetrico con confirmacion posterior en otra clausula"],
        "rationale": "Cesacion simetrica: cerrar (A,B) tiene que cerrar tambien (B,A).",
    },
    {
        "id": "NEG-CESS-09",
        "source": "zafiro-sesion",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "ASR",
        "text": "goran ute abandono la escuela de la corriente el ciclo pasado",
        "corrected": "Goran Ute abandonó la Escuela de la Corriente el ciclo pasado.",
        "claims": [
            _c(("goran ute", Z + "goran-ute"), "MEMBER_OF",
               ("escuela de la corriente", Z + "escuela-corriente"),
               "goran ute abandono la escuela de la corriente", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "ASR sin tildes ni puntuacion: 'abandono' es ambiguo entre presente y pasado",
            "cesacion SIN ninguna marca de negacion",
        ],
        "rationale": "Cesacion lexica sobre texto degradado y con ambiguedad de tiempo verbal.",
    },
    {
        "id": "NEG-POS-05",
        "source": "zafiro-sesion",
        "family": "POSITIVE_CONTROL",
        "kind": "NONE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "NONE",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "Brixa Omal es hermana de Kena Drovic.",
        "claims": [
            _c(("Brixa Omal", Z + "brixa-omal"), "SIBLING_OF",
               ("Kena Drovic", Z + "kena-drovic"),
               "Brixa Omal es hermana de Kena Drovic",
               negated=False, direction="UNDIRECTED"),
        ],
        "extra_mentions": [],
        "traps": [],
        "rationale": "Control positivo minimo, sin ninguna marca en el episodio.",
    },
    {
        "id": "NEG-POS-06",
        "source": "zafiro-sesion",
        "family": "POSITIVE_CONTROL",
        "kind": "NONE",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "NONE",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "text": "El Sindicato Abisal posee la Sonda Madre.",
        "claims": [
            _c(("Sindicato Abisal", Z + "sindicato-abisal"), "OWNS",
               ("Sonda Madre", Z + "sonda-madre"),
               "El Sindicato Abisal posee la Sonda Madre", negated=False),
        ],
        "extra_mentions": [],
        "traps": ["mismo objeto que NEG-NOTYET-03, con otro sujeto y sin negacion"],
        "rationale": "Control positivo que comparte objeto con un caso NOT_YET.",
    },

    # =====================================================================
    # ambar-escaneo (11): NEVER x2, CESSATION x1,
    #                     QUESTION_CONDITIONAL_RUMOR x4, NO_CLAIM x4
    # =====================================================================
    {
        "id": "NEG-NEVER-05",
        "source": "ambar-escaneo",
        "family": "NEVER",
        "kind": "NEVER",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "OCR",
        "knowledge_horizon": "0214-12-31T00:00:00Z",
        "text": (
            "Veli Ardún nunca fue rniembro de la Corte de la Resina, segun e1 padron "
            "cerrado en 1as visperas del ano 214."
        ),
        "corrected": (
            "Veli Ardún nunca fue miembro de la Corte de la Resina, segun el padron "
            "cerrado en las visperas del ano 214."
        ),
        "claims": [
            _c(("Veli Ardún", A + "veli-ardun"), "MEMBER_OF",
               ("Corte de la Resina", A + "corte-resina"),
               "Veli Ardún nunca fue rniembro de la Corte de la Resina", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "OCR rn/m: 'rniembro' por 'miembro' rompe la palabra clave del predicado",
            "OCR l/1: 'e1' y '1as'",
            "el horizonte de conocimiento (ano 214) va en la misma frase, degradado",
        ],
        "rationale": (
            "NEVER con el nucleo del predicado corrompido por OCR. La cita literal que "
            "ancla es la degradada, no la corregida."
        ),
    },
    {
        "id": "NEG-NEVER-06",
        "source": "ambar-escaneo",
        "family": "NEVER",
        "kind": "NEVER",
        "decision": "AUTO_APPROVE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "NONE",
        "knowledge_horizon": "0216-12-31T00:00:00Z",
        "text": "El Anillo de Ámbar jamas pertenecio a la Mesnada Ocre.",
        "claims": [
            _c(("Anillo de Ámbar", A + "anillo-ambar"), "OWNED_BY",
               ("Mesnada Ocre", A + "mesnada-ocre"),
               "El Anillo de Ámbar jamas pertenecio a la Mesnada Ocre", negated=True),
        ],
        "extra_mentions": [],
        "traps": ["el horizonte de conocimiento NO esta en el texto: lo pone la fecha del escaneo"],
        "rationale": (
            "Contraste con NEG-NEVER-05: aqui el limite temporal viene de la procedencia, "
            "no del enunciado. Un NEVER sin horizonte es una afirmacion sobre el futuro."
        ),
    },
    {
        "id": "NEG-CESS-10",
        "source": "ambar-escaneo",
        "family": "CESSATION",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDEFINIDO",
        "noise": "OCR",
        "text": "Jonás Trerne dejo de encabezar la Cofradia de1 Lacre en el invierno de 216.",
        "corrected": "Jonás Treme dejo de encabezar la Cofradia del Lacre en el invierno de 216.",
        "claims": [
            _c(("Jonás Trerne", A + "jonas-treme"), "LEADS",
               ("Cofradia de1 Lacre", A + "cofradia-lacre"),
               "Jonás Trerne dejo de encabezar la Cofradia de1 Lacre", negated=True),
        ],
        "extra_mentions": [],
        "traps": [
            "OCR m/rn en el nombre propio ('Trerne') y l/1 en el de la faccion ('de1')",
            "'encabezar' como sinonimo de liderar",
        ],
        "rationale": "Cesacion con las dos entidades degradadas y el predicado en sinonimo.",
    },
    {
        "id": "NEG-RUMOR-01",
        "source": "ambar-escaneo",
        "family": "QUESTION_CONDITIONAL_RUMOR",
        "kind": "SIMPLE",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "reading": "RUMORED_NEGATIVE",
        "forbidden_outcomes": ["AUTO_APPROVE"],
        "text": "Corre por Villa Savia el rumor de que Sabela Orín no es hermana de Cirilo Nadal.",
        "claims": [
            _c(("Sabela Orín", A + "sabela-orin"), "SIBLING_OF",
               ("Cirilo Nadal", A + "cirilo-nadal"),
               "Sabela Orín no es hermana de Cirilo Nadal",
               negated=True, direction="UNDIRECTED", epistemic="RUMORED",
               cues=["Corre por Villa Savia el rumor de que"]),
        ],
        "extra_mentions": [("Villa Savia", A + "villa-savia")],
        "traps": [
            "el ALCANCE es inequivoco pero el estatus epistemico bloquea la autoaprobacion",
            "es la unica trampa de la bateria que falla SOLO por la condicion 5 de docs/v3/18",
        ],
        "rationale": (
            "Un rumor SI produce claim (docs/v3/08 §2.2), pero no puede autoaprobarse. "
            "Registrar el rumor como rumor es correcto; borrarlo es perder informacion."
        ),
    },
    {
        "id": "NEG-RUMOR-02",
        "source": "ambar-escaneo",
        "family": "QUESTION_CONDITIONAL_RUMOR",
        "kind": "CESSATION",
        "decision": "REVIEW_NEGATION_CESSATION",
        "scope": "UNAMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "OCR",
        "reading": "RUMORED_CESSATION",
        "forbidden_outcomes": ["AUTO_APPROVE", "CLOSE_ASSERTION"],
        "text": "Se dice en la Corte de 1a Resina que 0tilia Vasque ya no dirige la Mesnada Ocre.",
        "corrected": "Se dice en la Corte de la Resina que Otilia Vasque ya no dirige la Mesnada Ocre.",
        "claims": [
            _c(("0tilia Vasque", A + "otilia-vasque"), "LEADS",
               ("Mesnada Ocre", A + "mesnada-ocre"),
               "0tilia Vasque ya no dirige la Mesnada Ocre",
               negated=True, epistemic="RUMORED", cues=["Se dice en la Corte de 1a Resina que"]),
        ],
        "extra_mentions": [("Corte de 1a Resina", A + "corte-resina")],
        "traps": [
            "OCR O/0 en el nombre y l/1 en la faccion",
            "rumor Y cesacion a la vez: dos motivos independientes para no autoaprobar",
        ],
        "rationale": (
            "Cuando concurren rumor y cesacion, manda la cesacion: es la que puede cerrar "
            "una afirmacion existente."
        ),
    },
    {
        "id": "NEG-COND-01",
        "source": "ambar-escaneo",
        "family": "QUESTION_CONDITIONAL_RUMOR",
        "kind": "SIMPLE",
        "decision": "REVIEW_NEGATION_SCOPE",
        "scope": "AMBIGUOUS",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "CONDICIONAL_REAL",
        "noise": "NONE",
        "reading": "HYPOTHETICAL_NEGATIVE",
        "forbidden_outcomes": ["AUTO_APPROVE", "NEGATIVE_EDGE"],
        "text": (
            "Si el proximo lacre no confirma a Cirilo Nadal al frente de la Cofradia del "
            "Lacre, habra que convocar otra vez a las casas."
        ),
        "claims": [
            _c(("Cirilo Nadal", A + "cirilo-nadal"), "LEADS",
               ("Cofradia del Lacre", A + "cofradia-lacre"),
               "Si el proximo lacre no confirma a Cirilo Nadal al frente de la Cofradia "
               "del Lacre", negated=True, epistemic="HYPOTHETICAL", cues=["Si"]),
        ],
        "extra_mentions": [],
        "traps": [
            "condicional REAL (no contrafactual): produce claim hipotetico, no caso negativo",
            "comparar con NEG-NOCLAIM-02, que si es contrafactual y no produce nada",
        ],
        "rationale": (
            "La frontera entre condicional real e irreal decide si hay claim. Los dos "
            "casos estan en la bateria, uno al lado del otro."
        ),
    },
    {
        "id": "NEG-ABST-01",
        "source": "ambar-escaneo",
        "family": "QUESTION_CONDITIONAL_RUMOR",
        "kind": "SIMPLE",
        "decision": "ABSTAIN",
        "scope": "AMBIGUOUS",
        "cue_position": "BETWEEN_ARGUMENTS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "abstained": True,
        "reading": "UNDETERMINED",
        "forbidden_outcomes": ["AUTO_APPROVE", "NEGATIVE_EDGE", "POSITIVE_EDGE"],
        "text": "¿Sigue o no sigue Sabela Orín en la Mesnada Ocre? El escribano no lo anoto.",
        "anchor": "¿Sigue o no sigue Sabela Orín en la Mesnada Ocre?",
        "claims": [],
        "extra_mentions": [
            ("Sabela Orín", A + "sabela-orin"),
            ("Mesnada Ocre", A + "mesnada-ocre"),
        ],
        "traps": [
            "pregunta disyuntiva que contiene la afirmacion Y su negacion",
            "la frase siguiente declara explicitamente que no hay respuesta",
        ],
        "rationale": (
            "Las entidades existen y la relacion se nombra, pero la fuente dice que no lo "
            "sabe. Abstenerse es la salida correcta, y tiene que poder emparejarse."
        ),
    },
    {
        "id": "NEG-NOCLAIM-01",
        "source": "ambar-escaneo",
        "family": "NO_CLAIM",
        "kind": "NONE",
        "decision": "NO_DECISION",
        "scope": "NOT_APPLICABLE",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "negative_kind": "QUESTION",
        "must_not_produce": "claim",
        "forbidden_predicates": ["MEMBER_OF", "HAS_MEMBER"],
        "text": "¿Acaso Veli Ardún no pertenece a la Cofradia del Lacre?",
        "claims": [],
        "extra_mentions": [
            ("Veli Ardún", A + "veli-ardun"),
            ("Cofradia del Lacre", A + "cofradia-lacre"),
        ],
        "traps": ["pregunta retorica que contiene una negacion simple perfectamente formada"],
        "rationale": (
            "Formalmente identica a NEG-SIMPLE-01 salvo por los signos de interrogacion. "
            "No hay claim: nadie ha afirmado nada."
        ),
    },
    {
        "id": "NEG-NOCLAIM-02",
        "source": "ambar-escaneo",
        "family": "NO_CLAIM",
        "kind": "NONE",
        "decision": "NO_DECISION",
        "scope": "NOT_APPLICABLE",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "SUBJUNTIVO_PLUSCUAMPERFECTO",
        "noise": "NONE",
        "negative_kind": "COUNTERFACTUAL",
        "must_not_produce": "claim",
        "forbidden_predicates": ["MEMBER_OF", "HAS_MEMBER", "LOCATED_IN"],
        "text": (
            "Si Jonás Treme no hubiera abandonado la Corte de la Resina, hoy la sala "
            "tendria otro dueno."
        ),
        "claims": [],
        "extra_mentions": [
            ("Jonás Treme", A + "jonas-treme"),
            ("Corte de la Resina", A + "corte-resina"),
        ],
        "traps": [
            "contrafactual con negacion de cesacion dentro",
            "par minimo con NEG-COND-01, que si produce claim",
        ],
        "rationale": (
            "El contrafactual presupone que la cesacion SI ocurrio, pero no la afirma en "
            "este enunciado. Registrar aqui una continuidad seria inventar."
        ),
    },
    {
        "id": "NEG-NOCLAIM-03",
        "source": "ambar-escaneo",
        "family": "NO_CLAIM",
        "kind": "NONE",
        "decision": "NO_DECISION",
        "scope": "NOT_APPLICABLE",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "INDICATIVO_PRESENTE",
        "noise": "NONE",
        "negative_kind": "FICTION_WITHIN_FICTION",
        "must_not_produce": "claim",
        "forbidden_predicates": ["OWNS", "OWNED_BY"],
        "text": (
            "En el entremes que representaron los comicos, el falso legado declamaba: "
            "«Otilia Vasque no es duena de Villa Savia»."
        ),
        "claims": [],
        "extra_mentions": [
            ("Otilia Vasque", A + "otilia-vasque"),
            ("Villa Savia", A + "villa-savia"),
        ],
        "traps": [
            "negacion literal y bien formada DENTRO de una ficcion representada",
            "'los comicos' y 'el falso legado' son sustantivos de rol: no se anotan",
        ],
        "rationale": "Ficcion dentro de la ficcion: la cita es literal y aun asi no es un hecho del mundo.",
    },
    {
        "id": "NEG-NOCLAIM-04",
        "source": "ambar-escaneo",
        "family": "NO_CLAIM",
        "kind": "NONE",
        "decision": "NO_DECISION",
        "scope": "NOT_APPLICABLE",
        "cue_position": "BEFORE_FOCUS",
        "voice": "ACTIVE",
        "verb_form": "IMPERATIVO",
        "noise": "NONE",
        "negative_kind": "IMPERATIVE",
        "must_not_produce": "claim",
        "forbidden_predicates": ["MEMBER_OF", "HAS_MEMBER"],
        "text": "No inscribais a Cirilo Nadal en la Mesnada Ocre hasta que llegue la cedula.",
        "claims": [],
        "extra_mentions": [
            ("Cirilo Nadal", A + "cirilo-nadal"),
            ("Mesnada Ocre", A + "mesnada-ocre"),
        ],
        "traps": [
            "ORDEN negativa: docs/v3/18 la nombra como descalificador y no tenia caso propio",
            "extiende el vocabulario de `kind` de negativos con IMPERATIVE",
        ],
        "rationale": (
            "Una orden no describe el mundo: lo pide. Ni afirma ni niega la pertenencia, "
            "y ademas presupone que hoy no existe."
        ),
    },
]
