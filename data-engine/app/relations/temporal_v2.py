# -*- coding: utf-8 -*-
"""Resolucion TEMPORAL y de VIGENCIA de relaciones (motor v2, Bloque 4).

Modulo PURO, DETERMINISTA y OFFLINE. Amplia la clasificacion temporal historica
(`relations.temporality`, que sigue INTACTA y da servicio al camino v1) con:

  * un **estado de vigencia** rico (`TemporalState`): ACTIVE / ENDED / PLANNED /
    HYPOTHETICAL / RECURRING / UNKNOWN, mas expresivo que el enum del ground truth;
  * **senales temporales** estructuradas (`TemporalSignals`): valid_from/valid_to,
    event_time, temporal_expression, relative_to, is_potential, is_recurring,
    is_negated_pending -- lo que el texto permite derivar de forma segura; el resto
    queda None (nunca se inventa una fecha ni un tiempo de asercion inexistente);
  * el **estado temporal del contrato** (`temporal_status`, uno de
    `temporality.TEMPORAL_CLASSES`) que DIRIGE la metrica del arnes: se serializa
    como PREFIJO de `to_scope_string()` para que `temporality.temporal_status_of`
    lo lea sin reclasificar.

Diferencia de diseno frente a v1 (por que sube la cifra de forma legitima)
--------------------------------------------------------------------------
`temporality.classify_temporality` marca `has_temporal_signal=False` para el
presente simple (copula/estado sin fecha) y el pipeline lo materializa como
`temporal_scope=None`. Contra un ground truth donde la clase PRESENT es real,
`temporal_status_of(None)` devuelve None y NUNCA casa con PRESENT: toda relacion
en presente puntua mal por construccion. v2 corrige esa laguna emitiendo la clase
PRESENT (o RECURRING/ONGOING para genericos habituales) y ampliando la morfologia
de pasado (preterito PLURAL e IMPERFECTO, que la regex `\\w+o` de v1 no cubre).

CERO CALCOS DEL CORPUS: todo el lexico y la morfologia son GENERALES del espanol
(copula en presente de indicativo, terminaciones verbales -aron/-ieron/-aba,
adverbios de continuidad/cese, cuantificadores universales). No hay una sola
frase concreta del benchmark cableada. Mismo input -> misma salida, sin red, sin
disco, sin estado mutable, sin azar.

NO SOBRESCRIBIR HISTORIA: una transicion (aliado ACTIVE -> aliado ENDED -> enemigo
ACTIVE) se representa como una SECUENCIA ordenada de fases
(`segment_transitions`), no colapsando un estado sobre otro. Cada relacion
candidata recibe su propia resolucion inmutable: resolver una NUNCA muta otra.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from relations import signals as _signals
from relations import temporality

__all__ = [
    "TEMPORAL_V2_VERSION",
    "TemporalState",
    "STATE_TO_STATUS",
    "TemporalSignals",
    "TemporalResolution",
    "resolve_temporal",
    "resolve_for_pair",
    "segment_transitions",
]

# Version del resolutor v2 (independiente de SCHEMA_VERSION del contrato y de la
# TEMPORALITY_VERSION de v1: ampliar este modulo NO cambia el contrato de datos).
TEMPORAL_V2_VERSION = "relation-temporal-v2-1.0.0"


class TemporalState:
    """Estado de VIGENCIA de una relacion (mas rico que el enum del ground truth).

    * ``ACTIVE``       -- en vigor en el momento de la asercion (presente/estado).
    * ``ENDED``        -- concluida: relacion terminada o evento pasado cerrado.
    * ``PLANNED``      -- prevista/por venir o "todavia no" ocurrida.
    * ``HYPOTHETICAL`` -- condicional/potencial ("podria", "es posible que").
    * ``RECURRING``    -- habitual/generica ("todo X", "siempre", "cada").
    * ``UNKNOWN``      -- sin senal temporal resoluble.
    """

    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    PLANNED = "PLANNED"
    HYPOTHETICAL = "HYPOTHETICAL"
    RECURRING = "RECURRING"
    UNKNOWN = "UNKNOWN"


# Mapeo ESTADO -> clase temporal del contrato (una de temporality.TEMPORAL_CLASSES).
# Es la clave de coherencia con el arnes: `temporal_status_of` mide contra estas
# clases. El estado ACTIVE se resuelve a PRESENT u ONGOING segun haya o no marca de
# continuidad (ver `resolve_temporal`), por eso ACTIVE no aparece aqui como unico.
STATE_TO_STATUS = {
    TemporalState.ENDED: "ENDED",
    TemporalState.PLANNED: "FUTURE",
    TemporalState.HYPOTHETICAL: "FUTURE",
    TemporalState.RECURRING: "ONGOING",
    TemporalState.UNKNOWN: "ATEMPORAL",
    # ACTIVE -> PRESENT | ONGOING (resuelto dinamicamente).
}


# ---------------------------------------------------------------------------
# Normalizacion (acentos plegados; se compara contra texto tambien aplanado)
# ---------------------------------------------------------------------------
def _flatten(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# Lexicos GENERALES del espanol (minusculas, sin tildes)
# ---------------------------------------------------------------------------
# Cese explicito -> ENDED (la relacion se rompio / termino / caduco).
_ENDED_CUES = (
    "ya no", "dejo de", "dejaron de", "termino", "terminaron", "concluyo",
    "concluyeron", "rompio", "rompieron", "abandono", "abandonaron",
    "renuncio", "renunciaron", "disolvio", "disolvieron", "caduco", "expiro",
    "antiguo", "antigua", "antiguos", "antiguas", "otrora", "ex ", "difunto",
    "difunta", "fallecido", "fallecida", "extinto", "extinta",
)
# "hasta <fecha/algo>" cierra un intervalo por la derecha -> valid_to + ENDED.
_UNTIL_CUE = "hasta"

# Futuro / planificado -> PLANNED (status FUTURE).
_FUTURE_CUES = (
    "sera", "seran", "planea", "planean", "planeado", "planeada", "preve",
    "preven", "pretende", "pretenden", "promete", "prometen", "prometio",
    "prometieron", "futuro", "futura", "futuros", "futuras", "proximamente",
    "se espera", "espera que", "por venir", "venidero", "venidera",
    "nombrara", "nombraran", "heredara", "heredaran", "competira", "competiran",
)
# "todavia no" / "aun no" -> aun no ha ocurrido -> PLANNED (pendiente).
_NOT_YET_CUES = ("todavia no", "aun no")
# Potencial / condicional -> HYPOTHETICAL.
_POTENTIAL_CUES = (
    "podria", "podrian", "quiza", "quizas", "tal vez", "puede que",
    "es posible que", "es probable", "posiblemente", "acaso", "si acaso",
    "en caso de", "de ser asi", "hipoteticamente",
)
# Continuidad hasta el presente -> ONGOING (relacion aun en curso).
_ONGOING_CUES = (
    "desde", "sigue", "siguen", "continua", "continuan", "actualmente",
    "todavia", "aun", "en la actualidad", "hoy en dia", "a dia de hoy",
    "sin interrupcion", "ininterrumpidamente",
)
# Habitualidad / genericidad -> RECURRING (status ONGOING).
_RECURRING_CUES = (
    "todo ", "toda ", "todos ", "todas ", "cada ", "siempre", "cada vez",
    "habitualmente", "de costumbre", "por norma", "suele", "suelen",
    "acostumbra", "acostumbran", "periodicamente", "anualmente", "cada ano",
)
# Pasado lexico (evento/estado cerrado) -> PAST.
_PAST_CUES = (
    "fue", "fueron", "era", "eran", "en su dia", "tras ", "despues de",
    "antano", "hace anos", "hace siglos", "hace tiempo", "mas tarde",
    "tiempo despues", "en el pasado", "una vez", "antiguamente",
)
# Presente copulativo/relacional -> PRESENT.
_PRESENT_CUES = (
    "es ", "son ", "esta ", "estan ", "pertenece", "pertenecen", "reside",
    "residen", "vive", "viven", "habita", "habitan", "posee", "poseen",
    "ostenta", "ostentan", "domina", "dominan", "lidera", "lideran",
    "encabeza", "encabezan", "preside", "presiden", "custodia", "custodian",
    "guarda", "guardan", "protege", "protegen",
)
# Expresiones relativas al eje (no fechan pero situan) -> relative_to.
_RELATIVE_CUES = (
    "antes de", "despues de", "mas tarde", "tiempo despues", "sesion anterior",
    "sesion previa", "capitulo anterior", "hace anos", "hace siglos",
    "hace tiempo", "meses despues", "anos despues", "dias despues",
    "semanas despues", "la vispera", "al dia siguiente", "poco despues",
)
# "desde <X>" abre un intervalo por la izquierda -> valid_from.
_SINCE_CUE = "desde"

# Morfologia verbal (sobre texto CON tildes, minusculas):
#   * preterito 3sg    -> terminacion "-ó"          (sello, fundo, lidero)
#   * preterito 3pl    -> "-aron/-ieron/-eron"      (participaron, sirvieron)
#   * imperfecto       -> "-aba/-aban/-abamos"      (lideraba, gobernaban)
#   * futuro simple    -> "-rá/-rán"                (competira, heredara)
_PRETERITE_SG_RE = re.compile(r"\b\w+ó\b")
_PRETERITE_PL_RE = re.compile(r"\b\w+(?:aron|ieron|eron)\b")
_IMPERFECT_RE = re.compile(r"\b\w+(?:aba|abas|aban|ábamos|abamos)\b")
_FUTURE_TENSE_RE = re.compile(r"\b\w+(?:rá|rán)\b")

# Fechas: anos de 3-4 cifras (evento/valido). Intervalos explicitos.
_YEAR_RE = re.compile(r"\b\d{3,4}\b")
_INTERVAL_ENTRE_RE = re.compile(r"entre\s+(\d{3,4})\s+y\s+(\d{3,4})")
_INTERVAL_DASH_RE = re.compile(r"(\d{3,4})\s*[-–]\s*(\d{3,4})")


def _compile_cues(cues) -> tuple:
    """Compila cada cue con fronteras que evitan falsos positivos por subcadena.

    Los cues que YA terminan en espacio (p.ej. "es ", "todo ") conservan ese
    espacio como frontera derecha explicita; el resto usa `(?!\\w)`.
    """
    out = []
    for cue in cues:
        left = r"(?<!\w)"
        core = re.escape(cue.rstrip())
        right = r"(?!\w)"
        out.append((cue.strip(), re.compile(left + core + right)))
    return tuple(out)


_ENDED_RX = _compile_cues(_ENDED_CUES)
_FUTURE_RX = _compile_cues(_FUTURE_CUES)
_NOT_YET_RX = _compile_cues(_NOT_YET_CUES)
_POTENTIAL_RX = _compile_cues(_POTENTIAL_CUES)
_ONGOING_RX = _compile_cues(_ONGOING_CUES)
_RECURRING_RX = _compile_cues(_RECURRING_CUES)
_PAST_RX = _compile_cues(_PAST_CUES)
_PRESENT_RX = _compile_cues(_PRESENT_CUES)
_RELATIVE_RX = _compile_cues(_RELATIVE_CUES)


def _hits(flat: str, compiled) -> list:
    """Cues presentes en `flat` como palabra/frase completa, ordenados y unicos."""
    return sorted({cue for cue, pat in compiled if pat.search(flat)})


# ---------------------------------------------------------------------------
# Estructuras de resultado (inmutables)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TemporalSignals:
    """Senales temporales estructuradas derivadas del texto (las no resolubles
    quedan None; NUNCA se inventan)."""

    valid_from: Optional[str] = None       # inicio del intervalo de vigencia
    valid_to: Optional[str] = None         # fin del intervalo de vigencia
    event_time: Optional[str] = None       # instante/ano del evento
    source_time: Optional[str] = None      # tiempo de la fuente (no disponible offline)
    asserted_at: Optional[str] = None      # tiempo de asercion (no disponible offline)
    temporal_expression: tuple = ()        # literales temporales detectados
    relative_to: tuple = ()                # anclas relativas ("antes de", ...)
    is_potential: bool = False             # modalidad potencial/condicional
    is_recurring: bool = False             # habitual/generico
    is_pending: bool = False               # "todavia no" / aun no ocurrido

    def to_dict(self) -> dict:
        return {
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "event_time": self.event_time,
            "source_time": self.source_time,
            "asserted_at": self.asserted_at,
            "temporal_expression": list(self.temporal_expression),
            "relative_to": list(self.relative_to),
            "is_potential": self.is_potential,
            "is_recurring": self.is_recurring,
            "is_pending": self.is_pending,
        }


@dataclass(frozen=True)
class TemporalResolution:
    """Resolucion temporal completa e inmutable de un texto/relacion.

    * ``state``           -- estado de vigencia (`TemporalState`).
    * ``temporal_status`` -- clase del contrato (una de temporality.TEMPORAL_CLASSES),
      es la que DIRIGE la metrica del arnes.
    * ``markers``         -- literales (aplanados) que dispararon la decision.
    * ``dates``           -- anos detectados, en orden.
    * ``interval``        -- (ini, fin) si hay intervalo explicito.
    * ``signals``         -- `TemporalSignals` estructuradas.
    * ``rationale``       -- regla que decidio (traza estable).
    """

    state: str
    temporal_status: str
    markers: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    interval: Optional[tuple] = None
    signals: TemporalSignals = field(default_factory=TemporalSignals)
    rationale: str = ""
    version: str = TEMPORAL_V2_VERSION

    @property
    def has_temporal_signal(self) -> bool:
        """True salvo estado UNKNOWN sin fechas (texto sin alcance resoluble)."""
        return self.state != TemporalState.UNKNOWN or bool(self.dates) or self.interval is not None

    def to_scope_string(self) -> str:
        """STRING estable parseable por `temporality.temporal_status_of`.

        La CLASE del contrato (`temporal_status`) SIEMPRE encabeza, de modo que el
        arnes deriva la clase por prefijo sin reclasificar. Se anexa el estado rico
        y las senales no vacias para trazabilidad (el arnes las ignora).
        """
        parts = [self.temporal_status, "state=" + self.state]
        if self.markers:
            parts.append("markers=" + ",".join(self.markers))
        if self.dates:
            parts.append("dates=" + ",".join(str(d) for d in self.dates))
        if self.interval is not None:
            parts.append("interval={}-{}".format(self.interval[0], self.interval[1]))
        if self.signals.valid_from:
            parts.append("valid_from=" + str(self.signals.valid_from))
        if self.signals.valid_to:
            parts.append("valid_to=" + str(self.signals.valid_to))
        if self.signals.relative_to:
            parts.append("relative_to=" + ",".join(self.signals.relative_to))
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Resolucion principal
# ---------------------------------------------------------------------------
def resolve_temporal(text: str) -> TemporalResolution:
    """Resuelve estado de vigencia + clase temporal de un texto (puro, determinista).

    Prioridad de decision (documentada y estable):

        ENDED > (todavia-no -> PLANNED) > FUTURE > ONGOING(continuidad) >
        PAST(morfologia/lexico/fecha) > HYPOTHETICAL > RECURRING > PRESENT

    El presente relacional NO marcado cae en PRESENT (default para una asercion de
    relacion en espanol), NO en ATEMPORAL: solo el texto vacio/sin contenido es
    UNKNOWN/ATEMPORAL. Ese es el cambio central respecto a v1.
    """
    if not isinstance(text, str) or not text.strip():
        return TemporalResolution(
            state=TemporalState.UNKNOWN, temporal_status="ATEMPORAL",
            rationale="empty",
        )

    low = text.lower()
    flat = _flatten(low)

    # --- Evidencia comun: fechas, intervalos, relativas ---------------------
    dates = _YEAR_RE.findall(text)
    interval: Optional[tuple] = None
    m = _INTERVAL_ENTRE_RE.search(flat) or _INTERVAL_DASH_RE.search(text)
    if m:
        interval = (m.group(1), m.group(2))
    relative = tuple(_hits(flat, _RELATIVE_RX))

    # "desde X" / "hasta X": limites de vigencia.
    valid_from = None
    valid_to = None
    if _SINCE_CUE in flat.split():
        # ano tras "desde" si lo hay, si no marca abierta.
        mfrom = re.search(r"desde\s+(?:el\s+ano\s+|el\s+|)(\d{3,4})", flat)
        valid_from = mfrom.group(1) if mfrom else "abierto"
    has_until = bool(re.search(r"(?<!\w)hasta(?!\w)", flat))
    if has_until:
        mto = re.search(r"hasta\s+(?:el\s+ano\s+|el\s+|)(\d{3,4})", flat)
        valid_to = mto.group(1) if mto else "cierre"

    # --- Marcas lexicas -----------------------------------------------------
    ended = _hits(flat, _ENDED_RX)
    not_yet = _hits(flat, _NOT_YET_RX)
    future = _hits(flat, _FUTURE_RX)
    potential = _hits(flat, _POTENTIAL_RX)
    ongoing = _hits(flat, _ONGOING_RX)
    recurring = _hits(flat, _RECURRING_RX)
    past = _hits(flat, _PAST_RX)
    present = _hits(flat, _PRESENT_RX)

    # --- Morfologia (texto CON tildes) --------------------------------------
    has_preterite = bool(_PRETERITE_SG_RE.search(low) or _PRETERITE_PL_RE.search(low))
    has_imperfect = bool(_IMPERFECT_RE.search(low))
    has_future_tense = bool(_FUTURE_TENSE_RE.search(low))

    is_potential = bool(potential)
    is_recurring = bool(recurring)
    event_time = dates[0] if dates else None

    def _sig(**over) -> TemporalSignals:
        base = dict(
            valid_from=valid_from, valid_to=valid_to, event_time=event_time,
            temporal_expression=tuple(sorted(set(
                list(ended) + list(future) + list(ongoing) + list(past)
                + list(present) + list(recurring) + list(not_yet) + list(potential)
            ))),
            relative_to=relative, is_potential=is_potential,
            is_recurring=is_recurring, is_pending=bool(not_yet),
        )
        base.update(over)
        return TemporalSignals(**base)

    def _mk(state: str, status: str, markers, rationale: str) -> TemporalResolution:
        return TemporalResolution(
            state=state, temporal_status=status, markers=sorted(set(markers)),
            dates=dates, interval=interval, signals=_sig(), rationale=rationale,
        )

    # --- Prioridad de decision ---------------------------------------------
    # 1) Cese explicito -> ENDED. Un "hasta <ano>" tambien cierra la vigencia.
    if ended:
        return _mk(TemporalState.ENDED, "ENDED", ended, "ended_cue")
    if has_until and (dates or valid_to):
        return _mk(TemporalState.ENDED, "ENDED", [_UNTIL_CUE], "until_bound")

    # 2) "todavia no" / "aun no" -> pendiente -> PLANNED (FUTURE).
    if not_yet:
        return _mk(TemporalState.PLANNED, "FUTURE", not_yet, "not_yet")

    # 3) Futuro / planificado -> PLANNED (FUTURE). Si ademas hay potencial, el
    #    estado es HYPOTHETICAL pero la clase sigue siendo FUTURE.
    if future or has_future_tense:
        state = TemporalState.HYPOTHETICAL if is_potential else TemporalState.PLANNED
        markers = list(future)
        if has_future_tense and not markers:
            hit = _FUTURE_TENSE_RE.search(low)
            if hit:
                markers = [hit.group(0)]
        return _mk(state, "FUTURE", markers, "future")

    # 4) Continuidad hasta el presente -> ONGOING (ACTIVE en curso).
    if ongoing:
        return _mk(TemporalState.ACTIVE, "ONGOING", ongoing, "ongoing_cue")

    # 5) Pasado (morfologia preterito/imperfecto, lexico o solo fecha) -> PAST.
    if has_preterite or has_imperfect or past:
        markers = list(past)
        if not markers:
            hit = (_PRETERITE_SG_RE.search(low) or _PRETERITE_PL_RE.search(low)
                   or _IMPERFECT_RE.search(low))
            if hit:
                markers = [hit.group(0)]
        return _mk(TemporalState.ENDED, "PAST", markers, "past_morphology")

    # 6) Potencial/condicional sin marca de futuro ni continuidad -> HYPOTHETICAL.
    #    El condicional ("podria desencadenar") es inherentemente NO actual: la
    #    clase es FUTURE (aun no realizada). La continuidad (ONGOING) ya se resolvio
    #    en el paso 4, de modo que aqui una hipotesis nunca es presente. NO se toma
    #    el presente copulativo como senal: el plegado de acentos confunde el verbo
    #    "esta" con el demostrativo "esta/esa", que no fecha nada.
    if is_potential:
        return _mk(TemporalState.HYPOTHETICAL, "FUTURE", potential, "hypothetical")

    # 7) Habitual/generico -> RECURRING (ONGOING).
    if is_recurring:
        return _mk(TemporalState.RECURRING, "ONGOING", recurring, "recurring")

    # 8) Fecha suelta sin verbo/marca -> evento pasado.
    if (dates or interval is not None) and not present:
        return _mk(TemporalState.ENDED, "PAST", [], "date_only")

    # 9) Presente relacional (copula/estado o default de asercion) -> PRESENT.
    return _mk(TemporalState.ACTIVE, "PRESENT", present, "present_default")


# ---------------------------------------------------------------------------
# Adaptador para el pipeline (camino v2)
# ---------------------------------------------------------------------------
def resolve_for_pair(seg_text: str, pair: Any) -> TemporalResolution:
    """Resuelve la temporalidad de una relacion candidata acotando la VENTANA a la
    frase que contiene ambas menciones (misma frontera que el resto del subsistema,
    `signals._sentence_bounds`). NO muta nada; funcion pura.
    """
    s_ini, s_fin = _signals._sentence_bounds(seg_text, pair.subject_start, pair.subject_end)
    o_ini, o_fin = _signals._sentence_bounds(seg_text, pair.object_start, pair.object_end)
    lo, hi = min(s_ini, o_ini), max(s_fin, o_fin)
    return resolve_temporal(seg_text[lo:hi])


def temporal_scope_for_pair(seg_text: str, pair: Any) -> Optional[str]:
    """`temporal_scope` (string canonico) para el pipeline v2, o None si no hay
    alcance resoluble. El prefijo es la clase del contrato: el arnes lo lee sin
    reclasificar."""
    res = resolve_for_pair(seg_text, pair)
    return res.to_scope_string() if res.has_temporal_signal else None


# ---------------------------------------------------------------------------
# Transiciones (no sobrescribir historia)
# ---------------------------------------------------------------------------
# Conectores que separan FASES temporales sucesivas dentro de un mismo texto.
_TRANSITION_SPLIT_RE = re.compile(
    r"(?<!\w)(?:ya no|dejo de|dejaron de|mas tarde|despues|luego|"
    r"posteriormente|con el tiempo|hasta que|ahora|actualmente|hoy)(?!\w)"
)


@dataclass(frozen=True)
class TemporalPhase:
    """Una fase temporal dentro de una transicion (fragmento + su resolucion)."""

    order: int
    text: str
    resolution: TemporalResolution


def segment_transitions(text: str) -> list:
    """Descompone un texto con transicion (aliado->enemigo, cargo->ex-cargo, ...) en
    una SECUENCIA ORDENADA de fases, cada una con su propia resolucion temporal.

    NO colapsa ni sobrescribe: devuelve tantas fases como fragmentos separen los
    conectores de transicion. Un texto sin conector devuelve una unica fase. Esto
    permite representar ALLY_OF/ACTIVE -> ALLY_OF/ENDED -> ENEMY_OF/ACTIVE como
    estados SEPARADOS, no machacando el historico.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    flat = _flatten(text)
    cuts = [0]
    for m in _TRANSITION_SPLIT_RE.finditer(flat):
        if m.start() > cuts[-1]:
            cuts.append(m.start())
    cuts.append(len(text))
    phases: list = []
    order = 0
    for a, b in zip(cuts, cuts[1:]):
        frag = text[a:b].strip(" ,.;:-")
        if not frag:
            continue
        phases.append(TemporalPhase(order=order, text=frag, resolution=resolve_temporal(frag)))
        order += 1
    if not phases:
        phases.append(TemporalPhase(order=0, text=text.strip(), resolution=resolve_temporal(text)))
    return phases
