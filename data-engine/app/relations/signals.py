# -*- coding: utf-8 -*-
"""Senales heuristicas EXPLICABLES para relaciones (`relation-signals/v1`).

Este modulo produce SENALES, nunca DECISIONES. Cada senal es una funcion pura y
determinista que, dada una evidencia (segmento de texto + offsets del par de
entidades + metadatos opcionales), devuelve un objeto `Signal` con:

    * ``name``        -- identificador estable de la senal
    * ``value``       -- valor numerico o categorico (JSON-serializable)
    * ``evidence``    -- span / cita LITERAL tomada del segmento
    * ``explanation`` -- texto breve legible por humanos
    * ``version``     -- version del contrato de senal

NINGUNA senal decide la relacion ni el consenso: solo aporta evidencia
explicable. La agregacion/consenso (por ejemplo el ensemble) es responsabilidad
de OTRO subsistema (R7); aqui no se toma ninguna decision.

Restricciones cumplidas: SIN LLM, SIN NVIDIA, SIN red, SIN Neo4j, SIN escritura,
SIN efectos secundarios. Solo lee `relations.contracts` (fuente de los tipos de
entidad permitidos) sin modificarlo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

# El unico catalogo canonico que reutilizamos es el de tipos de entidad. No se
# modifica el contrato; solo se lee.
from relations.contracts import ALLOWED_ENTITY_TYPES
from relations import temporality

# Version del contrato de senal. Cada `Signal` la expone en su campo `version`.
SIGNALS_VERSION = "relation-signals-1.0.0"


# ---------------------------------------------------------------------------
# Estructuras de datos
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Signal:
    """Una senal heuristica explicable. NO es una decision.

    Es inmutable (frozen) para reforzar la ausencia de efectos secundarios.
    """

    name: str
    value: Any
    evidence: str
    explanation: str
    version: str = SIGNALS_VERSION

    def to_dict(self) -> dict:
        """Dict determinista (JSON-serializable) con los cinco campos."""
        value = self.value
        if isinstance(value, tuple):
            value = list(value)
        return {
            "name": self.name,
            "value": value,
            "evidence": self.evidence,
            "explanation": self.explanation,
            "version": self.version,
        }


@dataclass(frozen=True)
class SignalContext:
    """Evidencia de entrada para calcular senales sobre UN par de entidades.

    ``segment`` es el texto completo del segmento. Los offsets son posiciones de
    caracter [start, end) dentro de ``segment`` para la mencion del sujeto y del
    objeto. Los tipos ontologicos son opcionales (segun `ALLOWED_ENTITY_TYPES`).

    ``occurrences`` son citas LITERALES (una por co-ocurrencia documental de la
    misma pareja, incluida la presente) usadas por la senal de repeticion. Si se
    deja vacia, se asume una unica ocurrencia (el propio segmento).
    """

    segment: str
    subject_start: int
    subject_end: int
    object_start: int
    object_end: int
    subject_type: Optional[str] = None
    object_type: Optional[str] = None
    occurrences: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Validacion minima y determinista de offsets. No hay red ni escritura.
        if not isinstance(self.segment, str):
            raise ValueError("segment debe ser str")
        n = len(self.segment)
        for label, val in (
            ("subject_start", self.subject_start),
            ("subject_end", self.subject_end),
            ("object_start", self.object_start),
            ("object_end", self.object_end),
        ):
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValueError(f"{label} debe ser int")
            if val < 0 or val > n:
                raise ValueError(f"{label}={val} fuera de rango [0,{n}]")
        if self.subject_start > self.subject_end:
            raise ValueError("subject_start > subject_end")
        if self.object_start > self.object_end:
            raise ValueError("object_start > object_end")
        for label, val in (("subject_type", self.subject_type), ("object_type", self.object_type)):
            if val is not None and val not in ALLOWED_ENTITY_TYPES:
                raise ValueError(f"{label}={val!r} no es un tipo valido {ALLOWED_ENTITY_TYPES}")

    # -- Ayudas derivadas (puras) -----------------------------------------
    @property
    def subject_text(self) -> str:
        return self.segment[self.subject_start:self.subject_end]

    @property
    def object_text(self) -> str:
        return self.segment[self.object_start:self.object_end]

    def ordered_offsets(self) -> tuple[int, int, int, int]:
        """Devuelve (first_start, first_end, second_start, second_end) en orden
        de lectura (por posicion de inicio)."""
        if self.subject_start <= self.object_start:
            return (self.subject_start, self.subject_end, self.object_start, self.object_end)
        return (self.object_start, self.object_end, self.subject_start, self.subject_end)


# ---------------------------------------------------------------------------
# Ontologia minima de compatibilidad de tipos
# ---------------------------------------------------------------------------
# Documentada y deliberadamente pequena. Mapea CATEGORIAS semanticas de relacion
# a los pares de tipos (subject_type, object_type) que son plausibles. Es una
# senal, NO una regla dura: si un par no aparece, la senal informa
# "no compatible" sin descartar nada por su cuenta. Los tipos provienen de
# `ALLOWED_ENTITY_TYPES` = (Character, Location, Faction, Object, Event, Concept).
TYPE_ONTOLOGY: dict[str, frozenset[tuple[str, str]]] = {
    # Pertenencia: un personaje/faccion pertenece a una faccion.
    "MEMBERSHIP": frozenset({
        ("Character", "Faction"),
        ("Faction", "Faction"),
    }),
    # Ubicacion: algo situado en un lugar.
    "LOCATION": frozenset({
        ("Character", "Location"),
        ("Object", "Location"),
        ("Event", "Location"),
        ("Faction", "Location"),
    }),
    # Posesion: un agente posee un objeto o un concepto.
    "POSSESSION": frozenset({
        ("Character", "Object"),
        ("Faction", "Object"),
        ("Character", "Concept"),
    }),
    # Participacion: un agente participa en un evento.
    "PARTICIPATION": frozenset({
        ("Character", "Event"),
        ("Faction", "Event"),
    }),
}


# ---------------------------------------------------------------------------
# Lexicos deterministas (incluyen variantes con y sin tilde para robustez)
# ---------------------------------------------------------------------------
_MEMBERSHIP_CUES = (
    "miembro de", "miembros de", "pertenece a", "pertenecen a", "pertenecia a",
    "forma parte de", "forman parte de", "afiliado a", "afiliada a",
)
_POSSESSION_CUES = (
    "posee", "poseen", "propietario de", "propietaria de", "dueno de", "dueno de",
    "en posesion de", "en posesion de", "su ", "sus ",
)
_LOCATION_CUES = (
    "vive en", "viven en", "situado en", "situada en", "ubicado en", "ubicada en",
    "localizado en", "reside en", "residen en", "se encuentra en", "en la", "en el",
    " en ",
)
_NEGATION_CUES = (
    "no ", "nunca", "jamas", "jamas", "tampoco", "ni ", "sin ",
)
_TEMPORAL_CUES = (
    "antes de", "despues de", "despues de", "durante", "tras ", "mientras",
    "desde ", "hasta ", "cuando ", "en el ano", "en el ano", "siglo ",
)
_MODALITY_CUES = (
    "podria", "podria", "puede que", "quiza", "quizas", "quizas", "tal vez",
    "debe ", "deberia", "deberia", "tiene que", "es probable", "posiblemente",
)
_RUMOR_CUES = (
    "se dice que", "segun rumores", "segun rumores", "se rumorea", "dicen que",
    "al parecer", "supuestamente", "se cree que", "se comenta que",
)
# Cues verbales (SVO) frecuentes en descripciones de relaciones.
_VERB_CUES = (
    "es", "son", "era", "fue", "esta", "estan", "tiene", "posee", "lidera",
    "gobierna", "pertenece", "sirve", "protege", "ataca", "vive", "reside",
    "fundo", "creo", "controla", "manda", "dirige", "guarda", "porta", "lleva",
)
# Regex para anos de 3-4 cifras (fechas simples).
_YEAR_RE = re.compile(r"\b\d{3,4}\b")


def _find_first_cue(haystack_lower: str, original: str, cues: Sequence[str]) -> Optional[tuple[str, int]]:
    """Busca la primera aparicion de cualquier cue (case-insensitive por lower,
    que preserva la longitud en espanol) y devuelve (literal_original, index).

    Determinista: recorre cues en orden y elige el match de menor posicion. El
    literal devuelto se corta del texto ORIGINAL para conservar mayusculas/tildes.
    """
    best: Optional[tuple[str, int]] = None
    for cue in cues:
        idx = haystack_lower.find(cue)
        if idx != -1:
            if best is None or idx < best[1]:
                best = (original[idx:idx + len(cue)], idx)
    return best


def _sentence_bounds(segment: str, start: int, end: int) -> tuple[int, int]:
    """Devuelve (ini, fin) de la frase que contiene el rango [start, end).

    Fronteras de frase: `.`, `!`, `?` y salto de linea. Puro y determinista.
    """
    boundaries = set(".!?\n")
    ini = 0
    for i in range(min(start, len(segment)) - 1, -1, -1):
        if segment[i] in boundaries:
            ini = i + 1
            break
    fin = len(segment)
    for i in range(min(end, len(segment)), len(segment)):
        if segment[i] in boundaries:
            fin = i + 1
            break
    return ini, fin


def _clause_index(segment: str, pos: int, sent_ini: int, sent_fin: int) -> int:
    """Indice de clausula (dentro de la frase) para una posicion dada.

    Las clausulas se separan por comas, punto y coma o dos puntos. Determinista.
    """
    clause_sep = set(",;:")
    idx = 0
    for i in range(sent_ini, min(pos, sent_fin)):
        if segment[i] in clause_sep:
            idx += 1
    return idx


# ===========================================================================
# SENALES (cada una: name + value + evidence + explanation + version)
# ===========================================================================
def signal_distance(ctx: SignalContext) -> Signal:
    """Distancia (caracteres y tokens) entre las dos menciones.

    value: dict {"chars": int, "tokens": int} (numerico). Menor distancia suele
    correlacionar con relacion mas plausible, pero NO decide nada.
    """
    fs, fe, ss, se = ctx.ordered_offsets()
    gap = ctx.segment[fe:ss]  # texto literal entre ambas menciones
    char_dist = max(0, ss - fe)
    tokens = [t for t in re.split(r"\s+", gap.strip()) if t]
    token_dist = len(tokens)
    return Signal(
        name="distance",
        value={"chars": char_dist, "tokens": token_dist},
        evidence=gap,
        explanation=(
            f"{char_dist} caracteres y {token_dist} tokens separan las dos "
            "menciones en el segmento."
        ),
    )


def signal_same_sentence(ctx: SignalContext) -> Signal:
    """Si ambas menciones caen en la misma frase.

    value: bool (categorico). evidence: la frase que las contiene (o ambas frases).
    """
    s_ini, s_fin = _sentence_bounds(ctx.segment, ctx.subject_start, ctx.subject_end)
    o_ini, o_fin = _sentence_bounds(ctx.segment, ctx.object_start, ctx.object_end)
    same = (s_ini, s_fin) == (o_ini, o_fin)
    if same:
        evidence = ctx.segment[s_ini:s_fin].strip()
    else:
        lo = min(s_ini, o_ini)
        hi = max(s_fin, o_fin)
        evidence = ctx.segment[lo:hi].strip()
    return Signal(
        name="same_sentence",
        value=bool(same),
        evidence=evidence,
        explanation=(
            "Ambas menciones estan en la misma frase."
            if same else
            "Las menciones estan en frases distintas."
        ),
    )


def signal_same_clause(ctx: SignalContext) -> Signal:
    """Si ambas menciones caen en la misma clausula (dentro de la misma frase).

    value: bool (categorico).
    """
    s_ini, s_fin = _sentence_bounds(ctx.segment, ctx.subject_start, ctx.subject_end)
    o_ini, o_fin = _sentence_bounds(ctx.segment, ctx.object_start, ctx.object_end)
    same_sent = (s_ini, s_fin) == (o_ini, o_fin)
    if same_sent:
        c_subj = _clause_index(ctx.segment, ctx.subject_start, s_ini, s_fin)
        c_obj = _clause_index(ctx.segment, ctx.object_start, o_ini, o_fin)
        same = c_subj == c_obj
        evidence = ctx.segment[s_ini:s_fin].strip()
    else:
        same = False
        evidence = ""
    return Signal(
        name="same_clause",
        value=bool(same),
        evidence=evidence,
        explanation=(
            "Ambas menciones comparten clausula (sin comas/;/: entre ellas)."
            if same else
            "Las menciones no comparten clausula."
        ),
    )


def signal_type_compatibility(ctx: SignalContext) -> Signal:
    """Compatibilidad de tipos segun la ontologia minima documentada.

    value: lista de categorias compatibles (categorico). Vacia si no hay tipos o
    ninguna categoria admite el par. NO descarta la relacion; solo informa.
    """
    pair = (ctx.subject_type, ctx.object_type)
    if ctx.subject_type is None or ctx.object_type is None:
        return Signal(
            name="type_compatibility",
            value=[],
            evidence="",
            explanation="Tipos no aportados; no se puede evaluar compatibilidad.",
        )
    compatible = sorted(
        cat for cat, pairs in TYPE_ONTOLOGY.items() if pair in pairs
    )
    return Signal(
        name="type_compatibility",
        value=compatible,
        evidence=f"{ctx.subject_type} -> {ctx.object_type}",
        explanation=(
            "Par de tipos compatible con: " + ", ".join(compatible)
            if compatible else
            f"El par ({ctx.subject_type}, {ctx.object_type}) no encaja en "
            "ninguna categoria de la ontologia minima."
        ),
    )


def signal_svo(ctx: SignalContext) -> Signal:
    """Patron sujeto-verbo-objeto heuristico (sin parser).

    Busca un verbo-cue entre la primera y la segunda mencion (en orden de
    lectura). value: bool (categorico). evidence: el verbo literal hallado.
    """
    fs, fe, ss, se = ctx.ordered_offsets()
    between = ctx.segment[fe:ss]
    between_lower = between.lower()
    tokens_lower = re.findall(r"[a-zaeiouñ]+", between_lower, flags=re.IGNORECASE)
    found = None
    for verb in _VERB_CUES:
        if verb in tokens_lower:
            found = verb
            break
    likely = found is not None
    return Signal(
        name="svo_pattern",
        value=bool(likely),
        evidence=(found or "").strip(),
        explanation=(
            f"Verbo-cue '{found}' entre ambas menciones sugiere estructura "
            "sujeto-verbo-objeto."
            if likely else
            "No se encontro verbo-cue entre las menciones."
        ),
    )


def _cue_signal(ctx: SignalContext, name: str, cues: Sequence[str], desc: str) -> Signal:
    """Fabrica generica para senales basadas en lexico dentro de la frase del par."""
    s_ini, s_fin = _sentence_bounds(ctx.segment, ctx.subject_start, ctx.subject_end)
    o_ini, o_fin = _sentence_bounds(ctx.segment, ctx.object_start, ctx.object_end)
    lo, hi = min(s_ini, o_ini), max(s_fin, o_fin)
    window = ctx.segment[lo:hi]
    hit = _find_first_cue(window.lower(), window, cues)
    present = hit is not None
    return Signal(
        name=name,
        value=bool(present),
        evidence=(hit[0] if present else ""),
        explanation=(
            f"{desc}: marcador '{hit[0]}' presente." if present
            else f"{desc}: sin marcador lexico."
        ),
    )


def signal_membership(ctx: SignalContext) -> Signal:
    """Pertenencia: 'miembro de', 'pertenece a', 'forma parte de'."""
    return _cue_signal(ctx, "membership", _MEMBERSHIP_CUES, "Pertenencia")


def signal_possession(ctx: SignalContext) -> Signal:
    """Posesion: 'posee', 'propietario de', genitivo 'de'/'su'."""
    return _cue_signal(ctx, "possession", _POSSESSION_CUES, "Posesion")


def signal_location(ctx: SignalContext) -> Signal:
    """Ubicacion: 'en', 'vive en', 'situado en'."""
    return _cue_signal(ctx, "location", _LOCATION_CUES, "Ubicacion")


def signal_negation(ctx: SignalContext) -> Signal:
    """Negacion: marcadores 'no', 'nunca', 'jamas' que invalidan la afirmacion.

    value: bool. Si True, la afirmacion positiva NO debe darse por confirmada
    (pero la decision final NO es de esta senal).
    """
    return _cue_signal(ctx, "negation", _NEGATION_CUES, "Negacion")


def signal_temporality(ctx: SignalContext) -> Signal:
    """Temporalidad: 'antes de', 'durante', 'tras', fechas/anos.

    value: dict {"markers": [...], "years": [...]} (preserva el alcance temporal).
    """
    s_ini, s_fin = _sentence_bounds(ctx.segment, ctx.subject_start, ctx.subject_end)
    o_ini, o_fin = _sentence_bounds(ctx.segment, ctx.object_start, ctx.object_end)
    lo, hi = min(s_ini, o_ini), max(s_fin, o_fin)
    window = ctx.segment[lo:hi]
    window_lower = window.lower()
    markers = sorted({
        window[idx:idx + len(cue)]
        for cue in _TEMPORAL_CUES
        for idx in [window_lower.find(cue)]
        if idx != -1
    })
    years = _YEAR_RE.findall(window)
    present = bool(markers or years)
    evidence_parts = list(markers) + list(years)
    # Enriquecimiento class-aware (retrocompatible): se delega la CLASIFICACION
    # temporal en `temporality.classify_temporality` sobre la misma ventana, sin
    # alterar las claves historicas markers/years que otros consumidores esperan.
    clf = temporality.classify_temporality(window)
    # `scope`: STRING canonico (to_scope_string) SOLO si hay alcance temporal no
    # trivial; None en caso contrario (presente simple sin fechas). El pipeline lo
    # usa tal cual para `temporal_scope` sin reclasificar.
    scope = clf.to_scope_string() if clf.has_temporal_signal else None
    return Signal(
        name="temporality",
        value={
            "markers": markers,
            "years": years,
            "class": clf.temporal_class,
            "dates": list(clf.dates),
            "interval": clf.interval,
            "scope": scope,
        },
        evidence="; ".join(evidence_parts),
        explanation=(
            "Alcance temporal detectado (marcadores/fechas): " + "; ".join(evidence_parts)
            if present else
            "Sin marcadores temporales ni fechas."
        ),
    )


def signal_modality(ctx: SignalContext) -> Signal:
    """Modalidad: probabilidad/obligacion ('podria', 'debe', 'quiza')."""
    return _cue_signal(ctx, "modality", _MODALITY_CUES, "Modalidad")


def signal_rumor(ctx: SignalContext) -> Signal:
    """Estado epistemico de rumor: 'se dice que', 'segun rumores'.

    value: bool. Si True, la afirmacion es RUMORED, no ASSERTED (la senal solo
    marca; no decide el epistemic_status final).
    """
    return _cue_signal(ctx, "rumor", _RUMOR_CUES, "Rumor")


def signal_repetition(ctx: SignalContext) -> Signal:
    """Repeticion documental: la misma pareja aparece varias veces.

    value: int (numero de ocurrencias). evidence: citas literales de cada
    co-ocurrencia. Mas ocurrencias = mas soporte documental (no es una decision).
    """
    occ = tuple(ctx.occurrences) if ctx.occurrences else (ctx.segment,)
    count = len(occ)
    # Evidencia: hasta las citas literales aportadas (todas, deterministas).
    evidence = " || ".join(o.strip() for o in occ)
    return Signal(
        name="repetition",
        value=count,
        evidence=evidence,
        explanation=(
            f"La pareja co-ocurre {count} vez/veces en el material aportado."
        ),
    )


# Orden estable y determinista de todas las senales.
ALL_SIGNAL_FUNCS = (
    signal_distance,
    signal_same_sentence,
    signal_same_clause,
    signal_type_compatibility,
    signal_svo,
    signal_membership,
    signal_possession,
    signal_location,
    signal_negation,
    signal_temporality,
    signal_modality,
    signal_rumor,
    signal_repetition,
)


def compute_all_signals(ctx: SignalContext) -> list[Signal]:
    """Calcula TODAS las senales para un contexto, en orden estable.

    Devuelve una lista de `Signal`. Es una coleccion de EVIDENCIAS explicables;
    la decision (consenso/relacion) corresponde a otro subsistema (R7).
    """
    return [func(ctx) for func in ALL_SIGNAL_FUNCS]
