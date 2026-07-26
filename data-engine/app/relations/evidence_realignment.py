# -*- coding: utf-8 -*-
"""Realineamiento RESTRINGIDO de la evidencia externa (Bloque 7) — fallback, no via principal.

Para que existe
---------------
La via PREFERIDA del bloque 7 es el protocolo de fragmentos
(``relations.fragment_protocol``): el modelo elige ``fragment_ids`` y el sistema
reconstruye los offsets, de modo que la literalidad es POR CONSTRUCCION. Este modulo
es el FALLBACK para el protocolo clasico (el modelo devuelve una cita), y solo cubre
diferencias TIPOGRAFICAS triviales: NFC/NFD, comillas y apostrofes tipograficos,
colapso de blancos (incl. NBSP y CRLF) y controles Bidi / zero-width.

Diferencia CRITICA con la version de referencia
-----------------------------------------------
Procedencia: adaptado de ``exp/pr95-v2-deterministic-realignment`` (``b47497f``,
``relations/evidence_realignment.py``), leida en SOLO LECTURA. Aquella version tenia
una escalera ``exacto -> normalizado -> FUZZY en ventana`` y desambiguaba entre varias
coincidencias por PROXIMIDAD a los offsets que proponia el propio modelo. En el banco
sintetico del programa anterior midio **18 % de falso anclaje** (anclar en un span
erroneo). Aqui se restringe:

  * **No hay peldano fuzzy.** Nada de ``difflib``, nada de umbrales de similitud: eso
    es adivinar el ancla.
  * **No hay desambiguacion por los offsets del modelo.** La firma
    ``realign_evidence_unique(document, evidence_text)`` NI SIQUIERA ACEPTA offsets,
    de modo que confiar en ellos es sintacticamente imposible, no solo desaconsejado.
  * **Coincidencia UNICA y NO AMBIGUA, o rechazo.** Dos spans reales distintos que
    casen => ``ambiguous`` => se rechaza en vez de elegir uno.
  * **Solo ``exact`` ancla (Bloque 1 de V2E).** El peldano ``normalized`` se calcula
    pero NO acepta: era una segunda envolvente de aceptacion, alcanzable solo por el
    camino de API y no por el camino real del motor. Se cerro por el lado estricto.

Garantias duras
---------------
  * Mapa REVERSIBLE original<->normalizado: los offsets finales se calculan sobre el
    texto REAL, nunca sobre el normalizado.
  * La evidencia devuelta es SIEMPRE ``document[start:end]`` (la rodaja real), nunca el
    texto que mando el modelo: es imposible introducir texto que no este ya en el
    documento, luego una inyeccion de prompt en la evidencia no puede colarse.
  * Los controles Bidi / zero-width se ELIMINAN en la normalizacion: no pueden falsear
    visualmente un alineamiento.
  * Cotas duras de longitud (anti-DoS con payloads grandes).
  * Modulo PURO: sin red, sin estado global, sin escritura. Determinista.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Cotas PREDECLARADAS (constantes nombradas; NO numeros magicos en el flujo).
# ---------------------------------------------------------------------------

#: Cota dura de la longitud de evidencia admitida a realineamiento. Por encima se
#: rechaza (se mantiene el rechazo base): un payload enorme no debe consumir trabajo.
REALIGN_MAX_EVIDENCE = 2000

#: Cota dura del tamano de documento admitido a realineamiento normalizado.
REALIGN_MAX_DOCUMENT = 200_000

#: Peldanos posibles (catalogo CERRADO). ``exact`` y ``normalized`` son exitos; el
#: resto son motivos de fallo.
TIER_EXACT = "exact"
TIER_NORMALIZED = "normalized"
TIER_AMBIGUOUS = "ambiguous"
TIER_NO_MATCH = "no_match"
TIER_EMPTY = "empty"
TIER_NO_DOCUMENT = "no_document"
TIER_TOO_LONG = "too_long"
REALIGN_TIERS: tuple = (
    TIER_AMBIGUOUS, TIER_EMPTY, TIER_EXACT, TIER_NORMALIZED,
    TIER_NO_DOCUMENT, TIER_NO_MATCH, TIER_TOO_LONG,
)
#: Peldanos que constituyen un realineamiento ACEPTADO.
#:
#: **CERRADO A ``exact`` (Bloque 1 de V2E).** Antes valia tambien ``normalized``,
#: pero SOLO era alcanzable por el camino de API (`external_consult`), nunca por el
#: camino real del motor (`external_ai_shadow`), que exige subcadena LITERAL antes
#: de llamar aqui. Habia, por tanto, DOS envolventes de aceptacion para la misma
#: garantia. La divergencia se cierra por el lado ESTRICTO: ``normalized`` deja de
#: aceptarse y pasa a ser un MOTIVO DE FALLO diagnosticado (se sigue calculando el
#: peldano para poder decir "casaba salvo tipografia", pero NO se ancla con el).
#: Nunca al reves: relajar el camino real para igualarlo estaba prohibido.
REALIGN_OK_TIERS: frozenset = frozenset({TIER_EXACT})


@dataclass(frozen=True)
class RealignmentResult:
    """Resultado de un intento de realineamiento restringido.

    * ``ok``: se logro un alineamiento LITERAL y UNICO sobre el documento real.
    * ``evidence_text``/``start``/``end``: la rodaja REAL (solo si ``ok``).
    * ``tier``: peldano que resolvio (``exact``/``normalized``) o motivo del fallo.
    """

    ok: bool
    tier: str
    evidence_text: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None

    def __post_init__(self) -> None:
        if self.tier not in REALIGN_TIERS:
            raise ValueError(f"tier desconocido: {self.tier!r}")
        if self.ok and self.tier not in REALIGN_OK_TIERS:
            raise ValueError(f"tier {self.tier!r} no puede reportar ok=True")

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tier": self.tier,
            "evidence_text": self.evidence_text,
            "start": self.start,
            "end": self.end,
        }


# ---------------------------------------------------------------------------
# Normalizacion REVERSIBLE (texto real <-> forma normalizada)
# ---------------------------------------------------------------------------

# Comillas y apostrofes tipograficos plegados a su forma ASCII canonica.
_QUOTE_FOLD = {
    "«": '"', "»": '"',
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‹": '"', "›": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "´": "'", "`": "'",
    "′": "'", "″": '"',
}

# Caracteres ELIMINADOS por completo: zero-width, BOM, marcas y controles Bidi. No
# deben poder falsear un alineamiento ni spoofear visualmente. Se eliminan en AMBOS
# lados por igual (documento y evidencia).
# NOTA: se escriben como ESCAPES, no como caracteres literales. Incrustarlos
# literalmente hace saltar (con razon) el control anti-Trojan-Source del CI, y
# la forma escapada es identica en tiempo de ejecucion y ademas legible en una
# revision de codigo.
_REMOVABLE = frozenset(
    "\u200b\u200c\u200d\u2060\ufeff"      # zero-width space/joiner/word-joiner/BOM
    "\u200e\u200f"                        # LRM / RLM
    "\u202a\u202b\u202c\u202d\u202e"      # LRE RLE PDF LRO RLO
    "\u2066\u2067\u2068\u2069"            # LRI RLI FSI PDI
)


def _is_ws(ch: str) -> bool:
    """Whitespace unificado (incluye NBSP y NNBSP, tab, CR, LF)."""
    return ch.isspace() or ch in (" ", " ", " ")


def normalize_with_map(text: str) -> tuple:
    """Normaliza ``text`` devolviendo ``(norm, starts, ends)`` con mapa REVERSIBLE.

    Para cada caracter ``norm[k]``, ``starts[k]``/``ends[k]`` delimitan el rango del
    texto ORIGINAL del que proviene. Asi una coincidencia normalizada ``[i:j]`` se
    traduce a la rodaja REAL ``text[starts[i]:ends[j-1]]``, siempre subcadena literal
    del original.

    Normalizacion (idempotente, aplicada IGUAL a documento y evidencia):
      1. NFC por grupos (base + marcas combinantes), para casar NFC<->NFD.
      2. Eliminacion de controles Bidi / zero-width.
      3. Plegado de comillas/apostrofes tipograficos a ASCII.
      4. Colapso de cualquier whitespace (incl. NBSP/CRLF) a un unico espacio.
    """
    entries: list = []          # (norm_char, orig_start, orig_end)
    n = len(text)
    i = 0
    while i < n:
        # Agrupa base + marcas combinantes para que NFC pueda componer acentos.
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        nfc = unicodedata.normalize("NFC", text[i:j])
        for ch in nfc:
            if ch in _REMOVABLE:
                continue
            if _is_ws(ch):
                if entries and entries[-1][0] == " ":
                    prev = entries[-1]
                    entries[-1] = (" ", prev[1], j)     # colapsa el run de blancos
                else:
                    entries.append((" ", i, j))
            else:
                entries.append((_QUOTE_FOLD.get(ch, ch), i, j))
        i = j
    norm = "".join(e[0] for e in entries)
    starts = [e[1] for e in entries]
    ends = [e[2] for e in entries]
    return norm, starts, ends


def normalize_plain(text: str) -> str:
    """Forma normalizada (sin mapa) de un texto."""
    norm, _s, _e = normalize_with_map(text)
    return norm


def _all_occurrences(hay: str, needle: str) -> list:
    """TODAS las ocurrencias (incluidas las solapadas). Exhaustivo y determinista."""
    if not needle:
        return []
    out: list = []
    start = 0
    while True:
        k = hay.find(needle, start)
        if k < 0:
            break
        out.append(k)
        start = k + 1
    return out


# ---------------------------------------------------------------------------
# Escalera RESTRINGIDA: exacto-unico -> normalizado-unico -> rechazo
# ---------------------------------------------------------------------------
def realign_evidence_unique(document: str, evidence_text: str) -> RealignmentResult:
    """Realinea ``evidence_text`` al documento REAL, SOLO si la coincidencia es UNICA.

    UN SOLO peldano de ACEPTACION (sin fuzzy y sin pistas del modelo):

      1. ``exact``      -- ``evidence_text`` aparece LITERALMENTE **una sola vez**.
         Es el UNICO caso con ``ok=True`` (ver ``REALIGN_OK_TIERS``).
      2. ``normalized`` -- DIAGNOSTICO, no aceptacion: tras normalizar ambos lados el
         texto casa y mapea a una sola rodaja real, pero **no** es subcadena literal.
         Devuelve ``ok=False, tier="normalized"`` para que el llamador pueda decir
         "casaba salvo tipografia" sin anclar nada.

    En cualquier otro caso se RECHAZA (``ambiguous`` / ``no_match`` / ...): no se
    elige "la mas cercana", porque la unica pista disponible seria el offset que el
    modelo cuenta mal, que es exactamente el origen del falso anclaje.

    INVARIANTE de salida: si ``ok``, entonces ``tier == "exact"`` y
    ``document[start:end] == evidence_text`` (el texto devuelto es la rodaja REAL).
    """
    if not isinstance(document, str) or not document:
        return RealignmentResult(False, TIER_NO_DOCUMENT)
    if not isinstance(evidence_text, str) or not evidence_text.strip():
        return RealignmentResult(False, TIER_EMPTY)
    if len(evidence_text) > REALIGN_MAX_EVIDENCE:
        return RealignmentResult(False, TIER_TOO_LONG)
    if len(document) > REALIGN_MAX_DOCUMENT:
        return RealignmentResult(False, TIER_TOO_LONG)

    # --- Peldano 1: EXACTO con ocurrencia UNICA -------------------------------
    occ = _all_occurrences(document, evidence_text)
    if len(occ) == 1:
        s = occ[0]
        e = s + len(evidence_text)
        return RealignmentResult(True, TIER_EXACT, document[s:e], s, e)
    if len(occ) > 1:
        # Cita literal pero AMBIGUA: aparece varias veces y no hay forma honesta de
        # saber cual. Se rechaza (fail-closed).
        return RealignmentResult(False, TIER_AMBIGUOUS)

    # --- Peldano 2: NORMALIZADO-EXACTO con rodaja real UNICA -------------------
    norm_doc, starts, ends = normalize_with_map(document)
    norm_ev = normalize_plain(evidence_text).strip()
    if not norm_ev:
        return RealignmentResult(False, TIER_EMPTY)

    hits = _all_occurrences(norm_doc, norm_ev)
    if not hits:
        return RealignmentResult(False, TIER_NO_MATCH)

    spans: list = []
    seen: set = set()
    for k in hits:
        real_s = starts[k]
        real_e = ends[k + len(norm_ev) - 1]
        if (real_s, real_e) not in seen:
            seen.add((real_s, real_e))
            spans.append((real_s, real_e))

    if len(spans) != 1:
        return RealignmentResult(False, TIER_AMBIGUOUS)

    s, e = spans[0]
    if not (0 <= s <= e <= len(document)):
        return RealignmentResult(False, TIER_NO_MATCH)
    # Casa tras normalizacion tipografica y de forma unica... pero NO es subcadena
    # literal. Se DIAGNOSTICA (`tier=normalized`) y se RECHAZA: ver REALIGN_OK_TIERS.
    return RealignmentResult(False, TIER_NORMALIZED)


__all__ = [
    "REALIGN_MAX_DOCUMENT",
    "REALIGN_MAX_EVIDENCE",
    "REALIGN_OK_TIERS",
    "REALIGN_TIERS",
    "RealignmentResult",
    "TIER_AMBIGUOUS",
    "TIER_EMPTY",
    "TIER_EXACT",
    "TIER_NORMALIZED",
    "TIER_NO_DOCUMENT",
    "TIER_NO_MATCH",
    "TIER_TOO_LONG",
    "normalize_plain",
    "normalize_with_map",
    "realign_evidence_unique",
]
