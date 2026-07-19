# -*- coding: utf-8 -*-
"""Clasificacion EPISTEMICA determinista de relaciones (`relation-epistemic/v1`).

Este modulo separa la *clasificacion epistemica* (a cual de los cuatro valores del
enum `EpistemicStatus` pertenece una afirmacion) de la mera deteccion de rumor que
hacia `signals.signal_rumor`. Sigue el patron de `temporality.py`/`vocabulary.py`:

  * DETERMINISTA y puro: sin red, sin disco, sin LLM, sin estado global mutable, sin
    azar.
  * SIN inventar semantica: solo lexico del espanol (minusculas, sin tildes) con
    FRONTERA DE PALABRA (evita falsos positivos por subcadena).
  * Version propia (`EPISTEMIC_VERSION`) INDEPENDIENTE de `SCHEMA_VERSION`: ampliar
    los lexicos NO cambia el contrato de datos, solo esta capa de clasificacion.
  * REUTILIZA el enum `EpistemicStatus` de `relations.contracts` (NO define uno
    nuevo). Los cuatro valores son: ASSERTED, RUMORED, HYPOTHETICAL, INTENDED.

REGLA DE SEGURIDAD (invariante duro)
------------------------------------
Un RUMOR NUNCA se convierte en HECHO. De forma general: si el texto contiene
CUALQUIER cue epistemico NO-asertivo, el `status` resultante NUNCA es ASSERTED. El
estado epistemico NO se pierde: siempre se degrada a RUMORED/HYPOTHETICAL/INTENDED
segun la precedencia documentada. ASSERTED se reserva EXCLUSIVAMENTE para textos sin
ninguna marca epistemica.

Precedencia (documentada y estable)
-----------------------------------
    RUMOR / INDIRECTO / CREENCIA        -> RUMORED       (mayor prioridad)
    CONTRADICCION / DUDA / POSIBILIDAD / HIPOTESIS-CONDICIONAL -> HYPOTHETICAL
    INTENCION / PLAN                    -> INTENDED
    (ninguna marca)                     -> ASSERTED       (menor prioridad)

El rumor pesa MAS que la hipotesis: si algo es a la vez rumor Y dudoso, se marca
RUMORED (no HYPOTHETICAL). La contradiccion se DEGRADA a HYPOTHETICAL (nunca se
afirma algo en disputa).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from relations.contracts import EpistemicStatus

__all__ = [
    "EPISTEMIC_VERSION",
    "EPISTEMIC_NUANCES",
    "EpistemicClassification",
    "classify_epistemic",
    "is_epistemically_safe",
]

# Version del clasificador epistemico (independiente de SCHEMA_VERSION del contrato).
EPISTEMIC_VERSION = "relation-epistemic-1.0.0"

# Matices posibles (nuance). Cada uno se asocia de forma estable a un status del enum.
EPISTEMIC_NUANCES = (
    "rumor",
    "indirect",
    "belief",
    "doubt",
    "possibility",
    "hypothesis",
    "contradiction",
    "intention",
    "assertion",
)


# ---------------------------------------------------------------------------
# Normalizacion
# ---------------------------------------------------------------------------
def _strip_accents(text: str) -> str:
    """Quita tildes/diacriticos (NFD) preservando la longitud logica. Determinista."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# Lexicos deterministas (minusculas y SIN tildes; se comparan contra el texto
# tambien aplanado). Los cues se almacenan SIN espacios de borde: la frontera de
# palabra del regex hace ese trabajo, de modo que "si" casa "si cae" pero no
# "situado", y "segun" casa "segun fuentes" sin exigir un no-alfanumerico tras el
# espacio.
# ---------------------------------------------------------------------------
# RUMOR: informacion no confirmada que circula. -> RUMORED (nuance=rumor).
_RUMOR_CUES = (
    "se rumorea", "se dice que", "dicen que", "segun rumores", "al parecer",
    "supuestamente", "se comenta que", "corre el rumor",
)
# INDIRECTO: conocimiento de segunda mano / atribuido a terceros. -> RUMORED (indirect).
_INDIRECT_CUES = (
    "segun", "cuentan que", "se sabe por", "de acuerdo con",
)
# CREENCIA: opinion/creencia de un sujeto, no un hecho establecido. -> RUMORED (belief).
_BELIEF_CUES = (
    "cree que", "creen que", "opina que", "piensa que", "considera que",
    "sospecha que",
)
# DUDA: incertidumbre explicita. -> HYPOTHETICAL (nuance=doubt).
_DOUBT_CUES = (
    "quiza", "quizas", "tal vez", "acaso",
)
# POSIBILIDAD: modalidad potencial. -> HYPOTHETICAL (nuance=possibility).
_POSSIBILITY_CUES = (
    "puede que", "podria", "es posible", "posiblemente",
)
# HIPOTESIS/CONDICIONAL: supuesto o condicion. -> HYPOTHETICAL (nuance=hypothesis).
_HYPOTHESIS_CUES = (
    "si", "en caso de", "suponiendo", "hipoteticamente", "de ser cierto",
)
# CONTRADICCION: versiones enfrentadas / en disputa. -> HYPOTHETICAL (contradiction).
_CONTRADICTION_CUES = (
    "se contradice", "pero niega", "afirman lo contrario", "afirma lo contrario",
    "lo contrario", "version contraria", "en disputa", "version discrepante",
    "fuentes discrepan", "otros niegan",
)
# INTENCION/PLAN: proposito o plan futuro, aun no realizado. -> INTENDED (intention).
_INTENTION_CUES = (
    "planea", "pretende", "tiene intencion", "promete", "proyecta", "hara",
)


# ---------------------------------------------------------------------------
# Compilacion a regex con FRONTERAS de palabra (como en temporality).
# ---------------------------------------------------------------------------
def _compile_cues(cues) -> tuple:
    """Compila cada cue (aplanado, sin espacios de borde) a un regex con fronteras
    de palabra. Determinista. Evita falsos positivos por subcadena."""
    out = []
    for cue in cues:
        flat = _strip_accents(cue.lower()).strip()
        pat = re.compile(r"(?<!\w)" + re.escape(flat) + r"(?!\w)")
        out.append((flat, pat))
    return tuple(out)


_RUMOR_RX = _compile_cues(_RUMOR_CUES)
_INDIRECT_RX = _compile_cues(_INDIRECT_CUES)
_BELIEF_RX = _compile_cues(_BELIEF_CUES)
_DOUBT_RX = _compile_cues(_DOUBT_CUES)
_POSSIBILITY_RX = _compile_cues(_POSSIBILITY_CUES)
_HYPOTHESIS_RX = _compile_cues(_HYPOTHESIS_CUES)
_CONTRADICTION_RX = _compile_cues(_CONTRADICTION_CUES)
_INTENTION_RX = _compile_cues(_INTENTION_CUES)

# Orden de evaluacion por matiz (precedencia estable). El primer grupo con match
# determina status y nuance. RUMORED > HYPOTHETICAL > INTENDED > ASSERTED. Dentro de
# HYPOTHETICAL: contradiction > doubt > possibility > hypothesis (la contradiccion,
# por seguridad, tiene prioridad de reporte).
_PRECEDENCE = (
    ("rumor", EpistemicStatus.RUMORED, _RUMOR_RX),
    ("indirect", EpistemicStatus.RUMORED, _INDIRECT_RX),
    ("belief", EpistemicStatus.RUMORED, _BELIEF_RX),
    ("contradiction", EpistemicStatus.HYPOTHETICAL, _CONTRADICTION_RX),
    ("doubt", EpistemicStatus.HYPOTHETICAL, _DOUBT_RX),
    ("possibility", EpistemicStatus.HYPOTHETICAL, _POSSIBILITY_RX),
    ("hypothesis", EpistemicStatus.HYPOTHETICAL, _HYPOTHESIS_RX),
    ("intention", EpistemicStatus.INTENDED, _INTENTION_RX),
)


# ---------------------------------------------------------------------------
# Estructura de resultado
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EpistemicClassification:
    """Resultado inmutable de clasificar epistemicamente un texto.

    Campos:
      * ``status``  -- uno de :class:`EpistemicStatus` (ASSERTED/RUMORED/
                       HYPOTHETICAL/INTENDED).
      * ``nuance``  -- uno de :data:`EPISTEMIC_NUANCES` (rumor/indirect/belief/
                       doubt/possibility/hypothesis/contradiction/intention/assertion).
      * ``cues``    -- literales (aplanados) que dispararon la clasificacion, ordenados.
      * ``epistemic_version`` -- version del clasificador.
      * ``is_asserted`` -- True SOLO si status == ASSERTED (afirmacion de hecho).
    """

    status: EpistemicStatus
    nuance: str
    cues: tuple = field(default_factory=tuple)
    epistemic_version: str = EPISTEMIC_VERSION

    @property
    def is_asserted(self) -> bool:
        return self.status == EpistemicStatus.ASSERTED

    @property
    def has_epistemic_cue(self) -> bool:
        """True si hubo alguna marca epistemica NO-asertiva (nuance != assertion)."""
        return self.nuance != "assertion"


# ---------------------------------------------------------------------------
# Clasificacion
# ---------------------------------------------------------------------------
def _collect_cues(flat: str, compiled) -> list:
    """Cues (aplanados) presentes en `flat` como palabra/frase completa. Ordenado."""
    return sorted({cue for cue, pat in compiled if pat.search(flat)})


def classify_epistemic(text: str) -> EpistemicClassification:
    """Clasifica epistemicamente un texto de forma PURA y DETERMINISTA.

    Aplica la precedencia documentada en el modulo:

        RUMOR/INDIRECTO/CREENCIA -> RUMORED
        CONTRADICCION/DUDA/POSIBILIDAD/HIPOTESIS -> HYPOTHETICAL
        INTENCION -> INTENDED
        (sin marca) -> ASSERTED

    INVARIANTE DURO: si hay CUALQUIER cue no-asertivo, el status resultante NUNCA es
    ASSERTED. El primer grupo con match (en orden de precedencia) fija status+nuance;
    ademas se recogen TODOS los cues detectados de ese grupo como evidencia.
    """
    if not isinstance(text, str) or not text.strip():
        return EpistemicClassification(
            status=EpistemicStatus.ASSERTED, nuance="assertion", cues=(),
        )

    flat = _strip_accents(text.lower())

    for nuance, status, compiled in _PRECEDENCE:
        cues = _collect_cues(flat, compiled)
        if cues:
            return EpistemicClassification(
                status=status, nuance=nuance, cues=tuple(cues),
            )

    # Ninguna marca epistemica: afirmacion de hecho.
    return EpistemicClassification(
        status=EpistemicStatus.ASSERTED, nuance="assertion", cues=(),
    )


def is_epistemically_safe(status, has_epistemic_cue: bool) -> bool:
    """Guardia de seguridad EXPLICITA: devuelve False (INSEGURO) si hay un cue
    epistemico no-asertivo y aun asi el status es ASSERTED (un rumor convertido en
    hecho). En cualquier otro caso devuelve True.

    Es un invariante verificable: `classify_epistemic` NUNCA debe producir un estado
    inseguro. Los consumidores pueden aseverarlo para blindar el pipeline.
    """
    asserted = status == EpistemicStatus.ASSERTED or status == "ASSERTED"
    return not (bool(has_epistemic_cue) and asserted)
