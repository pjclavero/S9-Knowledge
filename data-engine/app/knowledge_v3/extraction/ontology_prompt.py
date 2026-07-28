# -*- coding: utf-8 -*-
"""Ontologia COMPILADA desde el `GameProfile` y prompt que la lleva al modelo.

La diferencia con el camino anterior no es de redaccion, es de arquitectura. El
prompt generico de `ollama.py` no dice que predicados existen: deja que el
modelo invente uno y despues se tira la propuesta con `PREDICATE_NOT_IN_PROFILE`
—se paga la llamada entera para descartarla—. Aqui el modelo recibe la
ontologia REAL del workspace y ELIGE dentro de ella, o se abstiene.

Que se compila, y de donde sale cada cosa:

    predicados         GameProfile.predicates (dominio, rango, simetria, inverso)
    definicion         catalogo del nucleo (`CORE_PREDICATE_DEFINITIONS`) y, si
                       el predicado no esta, una definicion DERIVADA de su
                       dominio/rango. Nunca se deja un predicado sin explicar
    confundible_con    CALCULADO: inverso, simetricos hermanos y predicados que
                       comparten dominio y rango. Es lo que hace que el modelo
                       distinga MEMBER_OF de LEADS en vez de jugarselo a suerte
    tipos de entidad   GameProfile.entity_types; si el perfil no los declara, el
                       catalogo canonico de `base.ALLOWED_ENTITY_TYPES`
    glosario           `Lexicon` del workspace (glosario V1 + alias del perfil)
    entidades conocidas del glosario, para RECONOCERLAS. Se dice explicitamente
                       que la lista no es cerrada: descubrir entidades nuevas es
                       el objetivo, no un efecto colateral

Limite del contrato congelado (documentado, no rodeado): `game-profile/
v3-internal-v1` no tiene campo `definition` ni `confusable_with`. Por eso la
definicion viene del catalogo del nucleo y la confundibilidad se calcula. Si un
dia el perfil los declara, este modulo los prefiere sin cambiar el prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from ..contracts import SourceEpisode
from .base import ALLOWED_ENTITY_TYPES
from .text import EvidenceIndex

#: Version del compilador de ontologia. Va en la traza: dos ejecuciones con
#: prompts distintos no son comparables, y hay que poder verlo en el informe.
ONTOLOGY_PROMPT_VERSION = "1.1.0"

#: Definiciones del nucleo comun. Son ONTOLOGICAS (que significa el predicado),
#: no instrucciones de estilo: describen la relacion, no como contestar.
CORE_PREDICATE_DEFINITIONS: dict[str, str] = {
    "MEMBER_OF": "el sujeto pertenece al grupo, casa u organizacion del objeto",
    "HAS_MEMBER": "el grupo sujeto cuenta al objeto entre sus miembros",
    "LEADS": "el sujeto dirige, manda o encabeza al objeto",
    "LED_BY": "el grupo sujeto esta dirigido por el objeto",
    "RULES": "el sujeto gobierna el territorio o dominio del objeto",
    "LOCATED_IN": "el sujeto se encuentra fisicamente dentro del lugar objeto",
    "LIVES_IN": "el sujeto reside habitualmente en el lugar objeto",
    "ALLY_OF": "sujeto y objeto estan aliados; la relacion vale en los dos sentidos",
    "RIVAL_OF": "sujeto y objeto se oponen o compiten; vale en los dos sentidos",
    "ENEMY_OF": "sujeto y objeto son enemigos declarados; vale en los dos sentidos",
    "SIBLING_OF": "sujeto y objeto son hermanos; vale en los dos sentidos",
    "PARENT_OF": "el sujeto es progenitor del objeto",
    "CHILD_OF": "el sujeto es descendiente directo del objeto",
    "OWNS": "el sujeto posee el objeto",
    "OWNED_BY": "el sujeto pertenece como propiedad al objeto",
    "SERVES": "el sujeto sirve o jura lealtad al objeto sin ser necesariamente miembro",
    "KILLED": "el sujeto dio muerte al objeto",
    "FOUNDED": "el sujeto fundo o creo el objeto",
    "WORKS_FOR": "el sujeto trabaja para el objeto sin afirmar pertenencia formal",
}


@dataclass(frozen=True)
class PredicateSpec:
    """Un predicado permitido, tal y como lo ve el modelo."""

    predicate: str
    definition: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    symmetric: bool = False
    transitive: bool = False
    functional: bool = False
    inverse_of: Optional[str] = None
    confusable_with: tuple[str, ...] = ()

    def render(self) -> str:
        partes = [
            f"- {self.predicate}: {self.definition}",
            f"    sujeto: {', '.join(self.domain)} | objeto: {', '.join(self.range)}",
        ]
        rasgos = []
        if self.symmetric:
            rasgos.append("simetrico (da igual el orden)")
        if self.transitive:
            rasgos.append("transitivo")
        if self.functional:
            rasgos.append("funcional (un solo objeto valido a la vez)")
        if self.inverse_of:
            rasgos.append(f"inverso de {self.inverse_of}")
        if rasgos:
            partes.append(f"    rasgos: {'; '.join(rasgos)}")
        if self.confusable_with:
            # No basta con avisar de que se confunden: hay que decirle QUE HACER
            # con esa lista. Medido en dev: con "no confundir con" el modelo
            # devolvia siempre UN solo candidato, asi que la capacidad de
            # desempate del motor no se ejercitaba nunca.
            partes.append(
                f"    no confundir con (y por eso mismo, CANDIDATOS ALTERNATIVOS "
                f"obligatorios si dudas): {', '.join(self.confusable_with)}"
            )
        return "\n".join(partes)


@dataclass(frozen=True)
class OntologySpec:
    """Ontologia efectiva de un workspace, lista para renderizar."""

    profile_id: str
    entity_types: tuple[str, ...]
    predicates: tuple[PredicateSpec, ...]
    known_entities: tuple[tuple[str, Optional[str]], ...] = ()
    titles: tuple[str, ...] = ()
    ambiguous_terms: tuple[str, ...] = ()
    calendars: tuple[dict, ...] = ()
    version: str = ONTOLOGY_PROMPT_VERSION

    @property
    def predicate_names(self) -> tuple[str, ...]:
        return tuple(p.predicate for p in self.predicates)

    def render(self, *, max_entities: int = 60) -> str:
        """Bloque de ontologia del prompt. Determinista: mismo perfil, mismo texto."""
        lineas = [
            f"ONTOLOGIA DEL WORKSPACE (perfil {self.profile_id}, v{self.version})",
            "",
            f"TIPOS DE ENTIDAD PERMITIDOS: {', '.join(self.entity_types)}",
            "",
            "PREDICADOS PERMITIDOS (elige SOLO de esta lista, o abstente):",
        ]
        lineas.extend(p.render() for p in self.predicates)
        if self.known_entities:
            conocidas = [
                f"{name} ({etype})" if etype else name
                for name, etype in self.known_entities[:max_entities]
            ]
            lineas += [
                "",
                "ENTIDADES YA CONOCIDAS (para RECONOCERLAS, no para limitarte a ellas;",
                "encontrar entidades nuevas que no esten en esta lista es parte del trabajo):",
                "  " + "; ".join(conocidas),
            ]
        if self.titles:
            lineas += [
                "",
                "CARGOS Y TITULOS (no son entidades por si solos): " + ", ".join(self.titles),
            ]
        if self.ambiguous_terms:
            lineas += [
                "",
                "TERMINOS AMBIGUOS (no decidas a quien se refieren; marcalos igual "
                "como mencion): " + ", ".join(self.ambiguous_terms),
            ]
        if self.calendars:
            marcas = [
                f"{c.get('epoch_label')} ({', '.join(c.get('units') or [])})"
                for c in self.calendars
                if c.get("epoch_label")
            ]
            if marcas:
                lineas += ["", "CALENDARIOS DEL MUNDO: " + "; ".join(marcas)]
        return "\n".join(lineas)


def _generic_definition(predicate: str, domain: Sequence[str], rango: Sequence[str]) -> str:
    """Definicion DERIVADA para un predicado que el nucleo no describe.

    Fea a proposito: se lee como lo que es (una definicion generada), para que
    nadie la confunda con una definicion curada. Antes que dejar un predicado
    sin explicar, se explica con lo unico que el perfil garantiza.
    """
    legible = predicate.replace("_", " ").lower()
    return (
        f"relacion '{legible}' entre un sujeto de tipo "
        f"{'/'.join(domain)} y un objeto de tipo {'/'.join(rango)} "
        "(definicion derivada del perfil: el perfil no declara una descripcion)"
    )


def _confusables(entry: dict, todos: Sequence[dict]) -> tuple[str, ...]:
    """Predicados con los que este se confunde, CALCULADO desde el perfil.

    Tres familias, todas verificables: el inverso declarado, los que comparten
    dominio y rango (mismo hueco de tipos = misma trampa) y los que invierten
    dominio y rango (misma frase leida al reves). Sin esto, un modelo que ve
    MEMBER_OF y LEADS con el mismo dominio y el mismo rango no tiene ninguna
    razon para preferir uno.
    """
    nombre = entry["predicate"]
    dom, rng = set(entry["domain"]), set(entry["range"])
    fuera: set[str] = set()
    if entry.get("inverse_of"):
        fuera.add(str(entry["inverse_of"]))
    for otro in todos:
        if otro["predicate"] == nombre:
            continue
        odom, orng = set(otro["domain"]), set(otro["range"])
        if (dom & odom and rng & orng) or (dom & orng and rng & odom):
            fuera.add(otro["predicate"])
    return tuple(sorted(fuera))


def compile_ontology(
    profile: Any,
    *,
    lexicon: Any = None,
    entity_types: Sequence[str] = ALLOWED_ENTITY_TYPES,
    max_entities: int = 60,
) -> OntologySpec:
    """Compila el `GameProfile` (y el lexico del workspace) en una `OntologySpec`.

    Sin perfil no hay ontologia y no hay extraccion semantica: devolver una
    lista vacia de predicados seria pedirle al modelo que invente, que es
    exactamente el fallo que este bloque corrige. Quien llama debe tratarlo.
    """
    if profile is None:
        raise ValueError(
            "no hay GameProfile: sin ontologia el extractor semantico no puede "
            "pedir un predicado cerrado y volveria a inventarlo"
        )
    crudos = [dict(p) for p in getattr(profile, "predicates", ()) or ()]
    if not crudos:
        raise ValueError("el GameProfile no declara predicados")

    specs: list[PredicateSpec] = []
    for entry in sorted(crudos, key=lambda p: str(p["predicate"])):
        nombre = str(entry["predicate"])
        dom = tuple(entry.get("domain") or ())
        rng = tuple(entry.get("range") or ())
        definicion = (
            str(entry.get("definition"))
            if entry.get("definition")
            else CORE_PREDICATE_DEFINITIONS.get(nombre) or _generic_definition(nombre, dom, rng)
        )
        confundibles = (
            tuple(entry["confusable_with"])
            if entry.get("confusable_with")
            else _confusables(entry, crudos)
        )
        specs.append(
            PredicateSpec(
                predicate=nombre,
                definition=definicion,
                domain=dom,
                range=rng,
                symmetric=bool(entry.get("symmetric")),
                transitive=bool(entry.get("transitive")),
                functional=bool(entry.get("functional")),
                inverse_of=entry.get("inverse_of") or None,
                confusable_with=confundibles,
            )
        )

    tipos = tuple(getattr(profile, "entity_types", ()) or ()) or tuple(entity_types)
    conocidas: list[tuple[str, Optional[str]]] = []
    vistas: set[str] = set()
    for e in getattr(lexicon, "entries", ()) or ():
        canonico = getattr(e, "canonical", None)
        if not canonico or canonico.lower() in vistas:
            continue
        vistas.add(canonico.lower())
        conocidas.append((canonico, getattr(e, "entity_type", None)))
    conocidas.sort(key=lambda x: x[0])

    return OntologySpec(
        profile_id=str(getattr(profile, "profile_id", "generic")),
        entity_types=tipos,
        predicates=tuple(specs),
        known_entities=tuple(conocidas[:max_entities]),
        titles=tuple(getattr(profile, "titles", ()) or ()),
        ambiguous_terms=tuple(getattr(profile, "ambiguous_terms", ()) or ()),
        calendars=tuple(dict(c) for c in getattr(profile, "calendars", ()) or ()),
    )


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "Eres un extractor de conocimiento sobre textos de ficcion y partidas de rol. "
    "Respondes UNICAMENTE con un objeto JSON valido: sin texto antes ni despues, "
    "sin markdown, sin comentarios.\n"
    "\n"
    "Reglas inviolables:\n"
    "1. Solo puedes usar texto que aparezca LITERALMENTE en el TEXTO del episodio. "
    "Copia superficies y citas caracter a caracter. No traduzcas, no corrijas "
    "erratas y no completes nombres.\n"
    "2. No inventas identificadores, ni offsets, ni fechas, ni entidades. Tu unica "
    "prueba admisible es una CITA literal del texto.\n"
    "3. Los predicados salen SOLO de la ontologia que se te da. Si ninguno encaja, "
    "no elijas 'el mas parecido': abstente y explica por que.\n"
    "4. OBLIGATORIO: 'predicate_candidates' lleva AL MENOS DOS predicados cuando la "
    "lectura admita mas de una. Y casi siempre admite mas de una: cada predicado de "
    "la ontologia trae su lista de confundibles, y si el que has elegido tiene "
    "confundibles compatibles con los tipos de sujeto y objeto, EVALUALOS y ponlos "
    "como segundo candidato con su confianza. Solo puedes dar UN candidato cuando el "
    "texto sea inequivoco; en ese caso dilo escribiendo en 'relation_phrase' la frase "
    "exacta que lo hace inequivoco. Un unico candidato por pereza es un error.\n"
    "5. La direccion es explicita: SUBJECT_TO_OBJECT, OBJECT_TO_SUBJECT, UNDIRECTED "
    "o UNRESOLVED si el texto no lo deja claro. Si la frase esta en voz pasiva, o el "
    "predicado tiene inverso, o el orden de los argumentos podria leerse al reves, "
    "anade TAMBIEN la direccion alternativa como segundo candidato.\n"
    "6. Si el texto niega, condiciona, pregunta o atribuye a un rumor, dilo en "
    "'negated' y en 'epistemic_status'. No conviertas un desmentido en un hecho.\n"
    "7. NO EXTRAIGAS COMO CLAIM lo que el texto no afirma. Nada de esto es un hecho "
    "del mundo, por muy bien formada que este la frase:\n"
    "   - condicional o contrafactual: 'Si X dirigiera...', 'de haber sido...', "
    "'a menos que...';\n"
    "   - interrogativo: cualquier frase entre '¿' y '?';\n"
    "   - ficcion dentro de la ficcion: lo que ocurre en una obra, farsa, serial, "
    "leyenda, cancion o relato que se cuenta DENTRO del texto;\n"
    "   - rumor desmentido o afirmacion que el propio texto contradice "
    "('el guionista lo invento todo', 'es falso que...', 'nadie ha visto el "
    "documento');\n"
    "   - lo que alguien dice y el texto niega o pone en duda.\n"
    "   Las ENTIDADES de esas frases si existen y se listan en 'mentions'. La "
    "relacion, no. Ponla en 'abstentions' con su cita y su razon, o no la pongas.\n"
    "8. No decides nada: no apruebas, no fusionas entidades, no cierras vigencias. "
    "Propones. Otro sistema verifica cada cita contra el texto real y descarta lo "
    "que no aparezca.\n"
    "9. 'confidence' es tu confianza real entre 0 y 1. No copies los numeros del "
    "ejemplo. Los candidatos van ordenados de mayor a menor confianza."
)

#: Forma EXACTA de la respuesta. Va en el prompt como esquema, con valores de
#: relleno evidentes para que no se copien.
RESPONSE_SCHEMA = """{
  "mentions": [
    {"local_ref": "m1", "surface": "texto literal del texto",
     "type_candidates": [{"type": "Character", "confidence": 0.0}],
     "evidence_quote": "frase literal del texto que contiene la superficie"}
  ],
  "claims": [
    {"subject_ref": "m1", "object_ref": "m2",
     "relation_phrase": "frase literal que expresa la relacion",
     "predicate_candidates": [{"predicate": "PREDICADO_DE_LA_ONTOLOGIA", "confidence": 0.0},
                              {"predicate": "SEGUNDO_PREDICADO_CONFUNDIBLE", "confidence": 0.0}],
     "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.0},
                              {"direction": "OBJECT_TO_SUBJECT", "confidence": 0.0}],
     "evidence_quote": "frase literal completa que sostiene la relacion",
     "negated": false, "epistemic_status": "ASSERTED",
     "temporal_expressions": ["texto literal de tiempo, si lo hay"],
     "temporal_resolution_required": false}
  ],
  "abstentions": [
    {"evidence_quote": "frase literal donde ves algo que no sabes leer",
     "reason": "POR_QUE_NO_TE_ATREVES"}
  ]
}"""

#: EJEMPLOS (few-shot). No son decorado: son la unica parte del prompt que
#: ensena la FORMA con dos candidatos. Sin ellos, medido sobre dev con
#: qwen2.5:7b y con llama-3.3-70b, el modelo devolvia UN solo candidato de
#: predicado siempre (top-2 = top-1) por mucho que la regla 4 se lo pidiese.
#:
#: Los nombres son deliberadamente ajenos a cualquier corpus ("Zenobia Trask",
#: "Hermandad del Yunque", "Puerto Nix"): si el modelo los copiase, el anclaje
#: local los tumbaria como `HALLUCINATED_MENTION` y se veria en el informe.
FEW_SHOT_EXAMPLES = """EJEMPLOS DE FORMA (NO son el texto a analizar; no copies de aqui
ninguna entidad ni ninguna cita, y usa SIEMPRE los predicados de la ontologia
de arriba, no los de estos ejemplos):

EJEMPLO 1 — lectura AMBIGUA: dos candidatos de predicado, obligatorio.
  texto de ejemplo: "Zenobia Trask lleva el estandarte de la Hermandad del Yunque."
  claim:
  {"subject_ref": "m1", "object_ref": "m2",
   "relation_phrase": "lleva el estandarte de la Hermandad del Yunque",
   "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.55},
                            {"predicate": "LEADS", "confidence": 0.35}],
   "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.8}],
   "evidence_quote": "Zenobia Trask lleva el estandarte de la Hermandad del Yunque.",
   "negated": false, "epistemic_status": "ASSERTED",
   "temporal_expressions": [], "temporal_resolution_required": false}
  por que dos: "llevar el estandarte" puede ser pertenecer o encabezar, y
  MEMBER_OF y LEADS estan declarados como confundibles. Las confianzas no suman
  1: son dos lecturas de la misma frase, ordenadas.

EJEMPLO 2 — voz pasiva: dos candidatos de DIRECCION.
  texto de ejemplo: "Puerto Nix fue tomado por la Hermandad del Yunque."
  "direction_candidates": [{"direction": "OBJECT_TO_SUBJECT", "confidence": 0.6},
                           {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.3}]
  por que dos: en pasiva el agente va detras, y quien lea la frase al reves se
  equivoca de sentido. Si de verdad no puedes decidirlo, usa
  [{"direction": "UNRESOLVED", "confidence": 0.0}] y no te inventes una.

EJEMPLO 3 — lectura INEQUIVOCA: un solo candidato, y se dice por que.
  texto de ejemplo: "Puerto Nix se encuentra dentro de la provincia de Sarn."
  "predicate_candidates": [{"predicate": "LOCATED_IN", "confidence": 0.7}]
  con "se encuentra dentro de" no hay segunda lectura posible: la frase exacta
  que lo hace inequivoco va en "relation_phrase".

EJEMPLO 4 — NEGATIVO: aqui NO hay claim, por mucho que la frase parezca uno.
  texto de ejemplo: "En la balada que cantan en las tabernas, Zenobia Trask
  entrega Puerto Nix a la Hermandad del Yunque; el juglar se lo invento entero.
  Si Zenobia Trask mandara hoy, la flota no habria zarpado. ¿Juro Zenobia Trask
  lealtad a la Hermandad del Yunque?"
  respuesta correcta: "mentions" con Zenobia Trask, Puerto Nix y Hermandad del
  Yunque (las entidades SI son reales), "claims": [] y, como mucho:
  "abstentions": [
    {"evidence_quote": "En la balada que cantan en las tabernas, Zenobia Trask entrega Puerto Nix a la Hermandad del Yunque",
     "reason": "FICTION_WITHIN_FICTION"}]
  ni el condicional ni la pregunta producen nada: no se afirman."""

#: Limite del texto que se manda. No es un adorno: recortar mas abajo perderia
#: la frase que sostiene la cita, y el claim se caeria en la verificacion local
#: por un fallo nuestro, no del modelo.
DEFAULT_MAX_CHARS = 6000


def render_prompt(
    ontology: OntologySpec,
    episode: SourceEpisode,
    index: EvidenceIndex,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Prompt completo de un episodio: ontologia + texto real + esquema.

    Los `fragment_id` NO se mandan. El modelo no puede aportarlos (los calcula
    el sistema local a partir de la cita), asi que ensenarselos solo le da algo
    mas que alucinar.
    """
    texto = (episode.text or "")[:max_chars]
    if not texto:
        texto = "\n".join(f.literal_text for f in index.fragments)[:max_chars]
    return (
        f"{ontology.render()}\n\n"
        f"EPISODIO: {episode.episode_id}\n"
        f"MODALIDAD: {episode.modality}\n\n"
        f"TEXTO (unica fuente admisible; copia de aqui, literalmente):\n"
        f"\"\"\"\n{texto}\n\"\"\"\n\n"
        "TAREA:\n"
        "1. Lista TODAS las entidades mencionadas en el texto, esten o no en la lista "
        "de conocidas. Cada una con su superficie literal y su cita.\n"
        "2. Lista las relaciones entre esas entidades que el texto AFIRME, usando "
        "solo predicados de la ontologia y citando la frase completa. Para cada una, "
        "DOS candidatos de predicado salvo que la lectura sea inequivoca, y la "
        "direccion alternativa si la frase admite leerse al reves.\n"
        "3. NO propongas claim para lo condicional, lo contrafactual, lo "
        "interrogativo, lo que ocurre dentro de una obra/farsa/serial/leyenda "
        "contada en el texto, ni para lo que el propio texto desmiente. Sus "
        "entidades si van en 'mentions'.\n"
        "4. Si ves una relacion que no encaja en ningun predicado, ponla en "
        "'abstentions' con su cita.\n\n"
        f"{FEW_SHOT_EXAMPLES}\n\n"
        "Devuelve exactamente esta forma JSON:\n"
        f"{RESPONSE_SCHEMA}"
    )


#: Segunda llamada, SOLO para lo que quedo temporalmente ambiguo. No se hace
#: para todos los claims: la temporalidad explicita se resuelve localmente y
#: gratis (ver `temporal.resolve_locally`).
TEMPORAL_SYSTEM_PROMPT = (
    "Resuelves expresiones de tiempo sobre un texto dado. Respondes UNICAMENTE con "
    "un objeto JSON valido.\n"
    "Reglas: solo puedes usar texto que aparezca LITERALMENTE en el fragmento; no "
    "inventas fechas ni las conviertes a otro calendario; si la expresion no basta "
    "para saber cuando empieza o termina algo, devuelves kind UNKNOWN. No decides "
    "vigencias ni estados."
)

TEMPORAL_RESPONSE_SCHEMA = """{
  "temporal_expressions": [
    {"text": "texto literal de tiempo", "kind": "POINT|INTERVAL|DURATION|RELATIVE|UNKNOWN"}
  ],
  "still_ambiguous": false
}"""


def render_temporal_prompt(quote: str, expressions: Sequence[str], context: str) -> str:
    """Prompt de la segunda pasada temporal, acotado a UNA cita."""
    vistas = "; ".join(dict.fromkeys(e for e in expressions if e)) or "(ninguna detectada)"
    return (
        f"FRAGMENTO:\n\"\"\"\n{context}\n\"\"\"\n\n"
        f"AFIRMACION: \"{quote}\"\n"
        f"EXPRESIONES DE TIEMPO YA DETECTADAS LOCALMENTE: {vistas}\n\n"
        "TAREA: clasifica cada expresion de tiempo que afecte a la afirmacion. "
        "Copia el texto de cada expresion LITERALMENTE del fragmento. Si sigue sin "
        "poder determinarse, marca still_ambiguous=true.\n\n"
        "Devuelve exactamente esta forma JSON:\n"
        f"{TEMPORAL_RESPONSE_SCHEMA}"
    )


__all__ = [
    "CORE_PREDICATE_DEFINITIONS",
    "DEFAULT_MAX_CHARS",
    "FEW_SHOT_EXAMPLES",
    "ONTOLOGY_PROMPT_VERSION",
    "OntologySpec",
    "PredicateSpec",
    "RESPONSE_SCHEMA",
    "SYSTEM_PROMPT",
    "TEMPORAL_RESPONSE_SCHEMA",
    "TEMPORAL_SYSTEM_PROMPT",
    "compile_ontology",
    "render_prompt",
    "render_temporal_prompt",
]
