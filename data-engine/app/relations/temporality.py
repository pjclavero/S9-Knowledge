# -*- coding: utf-8 -*-
"""Clasificacion TEMPORAL determinista de relaciones (`relation-temporality/v1`).

Este modulo separa la *clasificacion temporal* (a que clase del enum del ground
truth pertenece el alcance temporal de una relacion) de la mera deteccion de
marcadores que hacia `signals.signal_temporality`. Sigue el patron de
`vocabulary.py`:

  * DETERMINISTA y puro: sin red, sin disco, sin estado global mutable, sin azar.
  * SIN inventar semantica: solo lexico/morfologia del espanol y fechas literales.
  * Version propia (`TEMPORALITY_VERSION`) INDEPENDIENTE de `SCHEMA_VERSION`: ampliar
    los lexicos NO cambia el contrato de datos, solo esta capa de clasificacion.

Las clases (`TEMPORAL_CLASSES`) estan ALINEADAS con `temporal_status` del ground
truth (PAST/PRESENT/FUTURE/ONGOING/ENDED/ATEMPORAL). Este modulo NO decide la
relacion: solo etiqueta su alcance temporal de forma explicable y serializable.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "TEMPORALITY_VERSION",
    "TEMPORAL_CLASSES",
    "TemporalClassification",
    "classify_temporality",
    "temporal_status_of",
]

# Version del clasificador temporal (independiente de SCHEMA_VERSION del contrato).
TEMPORALITY_VERSION = "relation-temporality-1.0.0"

# Clases temporales ALINEADAS con el enum `temporal_status` del ground truth. NO
# se anaden ni renombran clases: este tuple es fuente unica para validar prefijos.
TEMPORAL_CLASSES = ("PAST", "PRESENT", "FUTURE", "ONGOING", "ENDED", "ATEMPORAL")

# Clases con marcador temporal NO trivial (las que el pipeline debe materializar
# en `temporal_scope`). PRESENT/ATEMPORAL puros se consideran "sin alcance".
_STRONG_CLASSES = frozenset({"PAST", "FUTURE", "ONGOING", "ENDED"})


# ---------------------------------------------------------------------------
# Normalizacion
# ---------------------------------------------------------------------------
def _strip_accents(text: str) -> str:
    """Quita tildes/diacriticos (NFD) preservando la longitud logica. Determinista."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# Lexicos deterministas (en minusculas y SIN tildes: se comparan contra el texto
# tambien aplanado, de modo que "podria"/"podría" o "aun"/"aún" coinciden ambos).
# ---------------------------------------------------------------------------
# ENDED: la relacion termino / se rompio (marca is_ended=True).
_ENDED_CUES = (
    "ya no", "dejo de", "dejaron de", "hasta ", "termino", "terminaron",
    "concluyo", "concluyeron", "rompio", "rompieron", "abandono", "abandonaron",
    "antiguo", "antigua", "otrora", "ex ",
)
# FUTURE: hechos por venir / expectativa / potencial. "promet"/"planea" ganan a la
# morfologia de preterito (p.ej. "prometio" es FUTURE, no PAST).
_FUTURE_CUES = (
    "sera", "seran", "seria", "serian", "planea", "planean", "pretende",
    "pretenden", "promete", "prometen", "prometio", "prometieron", "prometera",
    "prometeran", "futuro", "futura", "nombrara", "nombraran",
    "se espera", "espera que", "competira", "competiran", "heredara",
    "quiza", "quizas", "tal vez",
)
# Modalidad potencial: ademas de clasificar como FUTURE, marca is_potential=True.
_POTENTIAL_CUES = (
    "podria", "podrian", "quiza", "quizas", "tal vez", "puede que", "es probable",
    "posiblemente",
)
# ONGOING: en curso / continuidad hasta el presente.
_ONGOING_CUES = (
    "desde", "aun", "sigue", "siguen", "continua", "continuan",
    "actualmente", "todavia", "en la actualidad",
)
# PAST: cerrado en el pasado. Lexico + morfologia de preterito/imperfecto (ver regex).
_PAST_CUES = (
    "fue", "fueron", "era", "eran", "antiguo", "antigua", "en su dia",
    "tras", "despues de", "antano", "goberno", "juro", "fundo", "murio",
    "cayo", "lidero", "sirvio",
)
# PRESENT: presente simple sin otras marcas -> clase por defecto (copula/estado).
_PRESENT_CUES = (
    "es", "son", "pertenece", "pertenecen", "reside", "residen", "vive",
    "viven", "esta", "estan", "domina", "dominan",
)
# Expresiones relativas al eje temporal (evidencia adicional, refuerzan pasado).
_RELATIVE_CUES = (
    "hace anos", "hace siglos", "hace tiempo", "mas tarde", "tiempo despues",
    "en su dia", "otrora", "antano",
)

# Morfologia verbal (sobre el texto CON tildes en minusculas):
#   * Preterito 3a persona: terminacion en "o" acentuada  -> sello, lucho, fundo.
#   * Futuro simple: terminacion "ra"/"ran" acentuada      -> competira, heredara.
_PRETERITE_RE = re.compile(r"\b\w+ó\b")
_FUTURE_TENSE_RE = re.compile(r"\b\w+(?:rá|rán)\b")

# Fechas: anos de 3-4 cifras.
_YEAR_RE = re.compile(r"\b\d{3,4}\b")
# Intervalos explicitos: "entre X y Y" y "X-Y" / "X–Y" (guion o raya).
_INTERVAL_ENTRE_RE = re.compile(r"entre\s+(\d{3,4})\s+y\s+(\d{3,4})")
_INTERVAL_DASH_RE = re.compile(r"(\d{3,4})\s*[-–]\s*(\d{3,4})")


# ---------------------------------------------------------------------------
# Estructura de resultado
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TemporalClassification:
    """Resultado inmutable de clasificar temporalmente un texto.

    Campos:
      * ``temporal_class`` -- una de :data:`TEMPORAL_CLASSES`.
      * ``markers``        -- literales (aplanados) que dispararon la clase, ordenados.
      * ``dates``          -- anos detectados (strings), en orden de aparicion.
      * ``interval``       -- (ini, fin) si hay intervalo explicito, si no None.
      * ``is_ended``       -- True si hay marca explicita de cese.
      * ``is_potential``   -- True si hay modalidad potencial (podria/quiza...).
      * ``temporality_version`` -- version del clasificador.
    """

    temporal_class: str
    markers: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    interval: Optional[tuple] = None
    is_ended: bool = False
    is_potential: bool = False
    temporality_version: str = TEMPORALITY_VERSION

    @property
    def has_temporal_signal(self) -> bool:
        """True si hay alcance temporal NO trivial (clase fuerte o fechas/intervalo).

        El pipeline usa esto para decidir si materializa `temporal_scope` (string)
        o deja None: un presente simple sin fechas NO tiene alcance distintivo.
        """
        return (
            self.temporal_class in _STRONG_CLASSES
            or bool(self.dates)
            or self.interval is not None
        )

    def to_scope_string(self) -> str:
        """Serializa a un STRING estable y determinista, parseable por
        :func:`temporal_status_of`.

        Formato: ``CLASS | markers=a,b | dates=843 | interval=843-870``. Los
        segmentos vacios se omiten; la CLASE siempre encabeza para permitir el
        parseo por prefijo (round-trip garantizado).
        """
        parts = [self.temporal_class]
        if self.markers:
            parts.append("markers=" + ",".join(self.markers))
        if self.dates:
            parts.append("dates=" + ",".join(str(d) for d in self.dates))
        if self.interval is not None:
            parts.append("interval={}-{}".format(self.interval[0], self.interval[1]))
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Clasificacion
# ---------------------------------------------------------------------------
def _compile_cues(cues) -> tuple:
    """Compila cada cue a un regex con FRONTERAS de palabra (evita falsos positivos
    por subcadena, p.ej. 'era' dentro de 'cualquiera'). Determinista."""
    out = []
    for cue in cues:
        pat = re.compile(r"(?<!\w)" + re.escape(cue) + r"(?!\w)")
        out.append((cue, pat))
    return tuple(out)


_ENDED_RX = _compile_cues(_ENDED_CUES)
_FUTURE_RX = _compile_cues(_FUTURE_CUES)
_POTENTIAL_RX = _compile_cues(_POTENTIAL_CUES)
_ONGOING_RX = _compile_cues(_ONGOING_CUES)
_PAST_RX = _compile_cues(_PAST_CUES)
_PRESENT_RX = _compile_cues(_PRESENT_CUES)
_RELATIVE_RX = _compile_cues(_RELATIVE_CUES)


def _collect_markers(flat: str, compiled) -> list:
    """Cues (aplanados) presentes en `flat` como palabra/frase completa. Ordenado."""
    return sorted({cue for cue, pat in compiled if pat.search(flat)})


def classify_temporality(text: str) -> TemporalClassification:
    """Clasifica temporalmente un texto de forma PURA y DETERMINISTA.

    Prioridad de clase (documentada y estable):

        ENDED > FUTURE > ONGOING > PAST > PRESENT > ATEMPORAL

    El orden refleja que una marca de cese (ENDED) o de futuro/potencial (FUTURE)
    domina sobre la morfologia de preterito, y que el presente simple es la clase
    por defecto solo cuando NO hay ninguna marca fuerte. ATEMPORAL se reserva para
    textos vacios o sin verbo/marca alguna.
    """
    if not isinstance(text, str) or not text.strip():
        return TemporalClassification(temporal_class="ATEMPORAL")

    low = text.lower()
    flat = _strip_accents(low)

    # Evidencia comun: fechas e intervalos (independiente de la clase).
    dates = _YEAR_RE.findall(text)
    interval: Optional[tuple] = None
    m = _INTERVAL_ENTRE_RE.search(flat) or _INTERVAL_DASH_RE.search(text)
    if m:
        interval = (m.group(1), m.group(2))

    potential_markers = _collect_markers(flat, _POTENTIAL_RX)
    is_potential = bool(potential_markers)

    # Deteccion morfologica (sobre el texto CON tildes).
    has_preterite = bool(_PRETERITE_RE.search(low))
    has_future_tense = bool(_FUTURE_TENSE_RE.search(low))

    ended_markers = _collect_markers(flat, _ENDED_RX)
    future_markers = _collect_markers(flat, _FUTURE_RX)
    ongoing_markers = _collect_markers(flat, _ONGOING_RX)
    past_markers = _collect_markers(flat, _PAST_RX) + _collect_markers(flat, _RELATIVE_RX)
    present_markers = _collect_markers(flat, _PRESENT_RX)

    # --- Prioridad de clase -------------------------------------------------
    if ended_markers:
        return TemporalClassification(
            temporal_class="ENDED", markers=sorted(set(ended_markers)),
            dates=dates, interval=interval, is_ended=True, is_potential=is_potential,
        )

    if future_markers or has_future_tense or is_potential:
        markers = sorted(set(future_markers) | set(potential_markers))
        if has_future_tense and not markers:
            hit = _FUTURE_TENSE_RE.search(low)
            if hit:
                markers = [hit.group(0)]
        return TemporalClassification(
            temporal_class="FUTURE", markers=markers,
            dates=dates, interval=interval, is_ended=False, is_potential=is_potential,
        )

    if ongoing_markers:
        return TemporalClassification(
            temporal_class="ONGOING", markers=sorted(set(ongoing_markers)),
            dates=dates, interval=interval, is_ended=False, is_potential=is_potential,
        )

    if past_markers or has_preterite:
        markers = sorted(set(past_markers))
        if has_preterite and not markers:
            # Registra el token de preterito como evidencia explicita.
            hit = _PRETERITE_RE.search(low)
            if hit:
                markers = [hit.group(0)]
        return TemporalClassification(
            temporal_class="PAST", markers=markers,
            dates=dates, interval=interval, is_ended=False, is_potential=is_potential,
        )

    if present_markers:
        return TemporalClassification(
            temporal_class="PRESENT", markers=sorted(set(present_markers)),
            dates=dates, interval=interval, is_ended=False, is_potential=is_potential,
        )

    # Sin verbo ni marca: fechas sueltas -> PAST; nada -> ATEMPORAL.
    if dates or interval is not None:
        return TemporalClassification(
            temporal_class="PAST", markers=[], dates=dates, interval=interval,
        )
    return TemporalClassification(temporal_class="ATEMPORAL", dates=dates, interval=interval)


def temporal_status_of(scope) -> Optional[str]:
    """Deriva la clase temporal (una de :data:`TEMPORAL_CLASSES`) de un
    `temporal_scope` cualquiera:

      * ``None``                 -> None (sin alcance: NO clasificable).
      * string de ``to_scope_string`` -> se extrae la CLASE del prefijo.
      * string LIBRE (LLM)       -> se reclasifica con :func:`classify_temporality`.

    Devuelve None SOLO cuando el alcance es None o un texto no clasificable. Un
    `temporal_scope=None` nunca casa con PAST/FUTURE/ONGOING/ENDED: el gate mide
    CLASIFICACION correcta, no mera deteccion.
    """
    if scope is None:
        return None
    if not isinstance(scope, str):
        scope = str(scope)
    text = scope.strip()
    if not text:
        return None

    # 1) Prefijo canonico producido por to_scope_string ("CLASS" o "CLASS | ...").
    head = text.split("|", 1)[0].strip().upper()
    if head in TEMPORAL_CLASSES:
        return head

    # 2) String libre: reclasificar. ATEMPORAL/sin senal -> None (no clasificable).
    clf = classify_temporality(text)
    if clf.temporal_class == "ATEMPORAL":
        return None
    return clf.temporal_class
