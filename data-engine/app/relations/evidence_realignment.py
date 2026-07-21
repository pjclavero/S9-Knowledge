# -*- coding: utf-8 -*-
"""Realineamiento DETERMINISTA y ACOTADO de la evidencia del modelo externo (PR#95 V2).

PROBLEMA
--------
La validacion estricta del evaluador externo (``external_ai_shadow._validate_verdict``)
RECHAZA la ``evidence_text`` devuelta por el modelo si NO es subcadena LITERAL del
documento real o si los offsets no casan exactamente. Los modelos parafrasean
levemente (NFC/NFD, comillas tipograficas, colapso de espacios, CRLF vs LF) y caen
sin que la relacion sea falsa.

OBJETIVO (detras de flag, default OFF)
--------------------------------------
Cuando la evidencia NO casa literalmente, intentar REALINEARLA al documento REAL de
forma determinista y acotada, con una escalera estricta:

    exacto -> normalizado-exacto -> alineamiento por caracteres (fuzzy en ventana)
            -> rechazo por ambiguedad -> vuelta al original.

GARANTIAS DURAS
---------------
* Mapa REVERSIBLE original<->normalizado: los offsets finales se recomputan sobre el
  texto REAL, nunca sobre el normalizado.
* Umbral de alineamiento PREDECLARADO (constante nombrada ``REALIGN_SCORE_THRESHOLD``),
  jamas un numero magico ad hoc.
* Varias coincidencias equivalentes por encima del umbral => RECHAZO (fail-closed).
* La evidencia FINAL es SIEMPRE subcadena LITERAL del documento real con offsets
  coherentes: ``doc[start:end] == evidence_text`` por construccion (se devuelve el
  slice real, nunca el texto del modelo).
* SIN recuperacion semantica: nada de embeddings ni LLM; solo texto determinista.
* Trabajo ACOTADO: ventana y longitudes con cotas duras (anti-DoS / payload grande).

SEGURIDAD
---------
El realineamiento NO es un vector para aceptar evidencia inventada:
* solo devuelve rodajas LITERALES del documento real (no puede introducir texto que no
  este ya en el documento; la inyeccion de prompt en la evidencia no cambia nada);
* controles Unicode Bidi / zero-width se eliminan en la normalizacion (no pueden
  falsear visualmente un alineamiento);
* el umbral + la regla de ambiguedad impiden aceptar alineamientos falsos;
* cotas de longitud impiden trabajo desbordado con payloads grandes.

Este modulo es PURO (sin red, sin estado global, sin escritura). Determinista.
"""
from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Umbrales y cotas PREDECLARADOS (constantes nombradas; NO numeros magicos).
# ---------------------------------------------------------------------------

#: Puntuacion minima de similitud (ratio de difflib sobre las formas normalizadas)
#: para aceptar un alineamiento fuzzy en ventana. Por debajo => se rechaza.
#: Calibrado para admitir PARAFRASIS LEVE y rechazar PARAFRASIS FUERTE.
REALIGN_SCORE_THRESHOLD = 0.82

#: Margen de puntuacion dentro del cual dos candidatos fuzzy se consideran
#: EQUIVALENTES. Si dos rodajas reales distintas puntuan >= umbral y sus scores
#: distan <= EPS => AMBIGUEDAD => rechazo (fail-closed).
REALIGN_AMBIGUITY_EPS = 0.05

#: Holgura (en caracteres) que se anade a cada lado de la ventana derivada de los
#: offsets propuestos por el modelo, para el alineamiento fuzzy.
REALIGN_WINDOW_SLACK = 48

#: Cota dura del tamano de la ventana fuzzy (anti-DoS con documentos grandes).
REALIGN_MAX_WINDOW = 4000

#: Cota dura de la longitud de la evidencia admitida a realineamiento
#: (payload grande => se rechaza el realineamiento, se mantiene el rechazo base).
REALIGN_MAX_EVIDENCE = 2000


# ---------------------------------------------------------------------------
# Resultado del realineamiento
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RealignmentResult:
    """Resultado de un intento de realineamiento.

    * ``ok``: se logro un alineamiento LITERAL sobre el documento real.
    * ``evidence_text``/``start``/``end``: la rodaja real (solo si ``ok``).
    * ``tier``: peldano de la escalera que resolvio (``exact``, ``normalized``,
      ``fuzzy``) o el motivo de fallo (``ambiguous``, ``below_threshold``,
      ``too_long``, ``empty``, ``no_document``, ``no_match``).
    * ``score``: puntuacion del alineamiento (1.0 para exacto/normalizado).
    """

    ok: bool
    tier: str
    evidence_text: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None
    score: float = 0.0


# ---------------------------------------------------------------------------
# Normalizacion REVERSIBLE (texto real <-> forma normalizada)
# ---------------------------------------------------------------------------

# Comillas y apostrofes tipograficos plegados a su forma ASCII canonica.
_QUOTE_FOLD = {
    "«": '"', "»": '"',            # « »
    "“": '"', "”": '"', "„": '"', "‟": '"',  # “ ” „ ‟
    "‹": '"', "›": '"',            # ‹ ›
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # ‘ ’ ‚ ‛
    "´": "'", "`": "'",            # ´ `
    "′": "'", "″": '"',            # ′ ″
}

# Caracteres eliminados por completo en la normalizacion: controles Bidi,
# zero-width y marcas de direccion. No deben poder falsear un alineamiento ni
# spoofear visualmente. (Se eliminan en AMBOS lados por igual.)
_REMOVABLE = frozenset(
    "​‌‍⁠﻿"          # zero-width space/joiner/nbsp/BOM
    "‎‏"                            # LRM / RLM
    "‪‫‬‭‮"          # LRE RLE PDF LRO RLO (Bidi)
    "⁦⁧⁨⁩"                # LRI RLI FSI PDI (Bidi isolates)
)


def _is_ws(ch: str) -> bool:
    """Whitespace unificado (incluye NBSP, narrow NBSP, tab, CR, LF)."""
    return ch.isspace() or ch in (" ", " ", " ")


def _fold_char(ch: str) -> str:
    return _QUOTE_FOLD.get(ch, ch)


def normalize_with_map(text: str) -> tuple[str, list[int], list[int]]:
    """Normaliza ``text`` devolviendo (norm, starts, ends) con mapa REVERSIBLE.

    Para cada caracter ``norm[k]`` de la forma normalizada, ``starts[k]`` y
    ``ends[k]`` son el rango ``[start, end)`` del texto ORIGINAL del que proviene.
    Asi una coincidencia normalizada ``[i:j]`` se traduce a la rodaja real
    ``text[starts[i] : ends[j-1]]`` (siempre subcadena LITERAL del original).

    Normalizacion aplicada (idempotente y aplicada IGUAL a documento y evidencia):
      1. NFC por grupos (base + marcas combinantes) para casar NFC<->NFD.
      2. Eliminacion de controles Bidi / zero-width.
      3. Plegado de comillas/apostrofes tipograficos a ASCII.
      4. Colapso de cualquier whitespace (incl. NBSP/CRLF) a un unico espacio.
    """
    entries: list[tuple[str, int, int]] = []  # (norm_char, orig_start, orig_end)
    n = len(text)
    i = 0
    while i < n:
        # Agrupa base + marcas combinantes para que NFC pueda componer acentos.
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        group = text[i:j]
        nfc = unicodedata.normalize("NFC", group)
        for ch in nfc:
            if ch in _REMOVABLE:
                continue
            if _is_ws(ch):
                if entries and entries[-1][0] == " ":
                    prev = entries[-1]
                    entries[-1] = (" ", prev[1], j)  # colapsa el run de espacios
                else:
                    entries.append((" ", i, j))
            else:
                entries.append((_fold_char(ch), i, j))
        i = j
    norm = "".join(e[0] for e in entries)
    starts = [e[1] for e in entries]
    ends = [e[2] for e in entries]
    return norm, starts, ends


def _normalize_plain(text: str) -> str:
    """Forma normalizada (sin mapa) para comparar/puntuar la evidencia."""
    norm, _s, _e = normalize_with_map(text)
    return norm


# ---------------------------------------------------------------------------
# Escalera de realineamiento
# ---------------------------------------------------------------------------
def _all_occurrences(hay: str, needle: str) -> list[int]:
    if not needle:
        return []
    out: list[int] = []
    start = 0
    while True:
        k = hay.find(needle, start)
        if k < 0:
            break
        out.append(k)
        start = k + 1  # solapadas incluidas: deterministico y exhaustivo
    return out


def _real_span(starts: list[int], ends: list[int], k: int, length: int) -> tuple[int, int]:
    """Traduce una coincidencia normalizada [k, k+length) a offsets REALES."""
    real_s = starts[k]
    real_e = ends[k + length - 1]
    return real_s, real_e


def _tier_normalized(
    doc: str, norm_doc: str, starts: list[int], ends: list[int],
    norm_ev: str, hint_start: Optional[int],
) -> RealignmentResult:
    """Peldano NORMALIZADO-EXACTO: igualdad tras normalizar, con desambiguacion
    por proximidad a los offsets propuestos; multiples equivalentes => rechazo."""
    occ = _all_occurrences(norm_doc, norm_ev)
    if not occ:
        return RealignmentResult(False, "no_match")

    # Rodajas reales distintas (dedup por (start,end)).
    spans: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for k in occ:
        s, e = _real_span(starts, ends, k, len(norm_ev))
        if (s, e) not in seen:
            seen.add((s, e))
            spans.append((s, e))

    if len(spans) == 1:
        s, e = spans[0]
        return RealignmentResult(True, "normalized", doc[s:e], s, e, 1.0)

    # Varias ocurrencias: desambiguar por cercania al offset propuesto por el modelo.
    if hint_start is None:
        return RealignmentResult(False, "ambiguous")
    dists = sorted(spans, key=lambda se: abs(se[0] - hint_start))
    best = dists[0]
    runner = dists[1]
    if abs(best[0] - hint_start) == abs(runner[0] - hint_start):
        return RealignmentResult(False, "ambiguous")  # empate => fail-closed
    s, e = best
    return RealignmentResult(True, "normalized", doc[s:e], s, e, 1.0)


def _best_fuzzy_in(norm_win: str, target: str) -> tuple[int, int, float]:
    """Mejor subcadena de ``norm_win`` que casa ``target`` (bloques de difflib).

    Devuelve (lo, hi, score) en indices de ``norm_win``. score es el ratio de
    similitud de la rodaja frente a ``target``.
    """
    sm = difflib.SequenceMatcher(None, norm_win, target, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    if not blocks:
        return -1, -1, 0.0
    lo = blocks[0].a
    hi = blocks[-1].a + blocks[-1].size
    cand = norm_win[lo:hi]
    score = difflib.SequenceMatcher(None, cand, target, autojunk=False).ratio()
    return lo, hi, score


def _tier_fuzzy(
    doc: str, norm_ev: str, hint_start: Optional[int], hint_end: Optional[int],
) -> RealignmentResult:
    """Peldano FUZZY ACOTADO A VENTANA: alineamiento por caracteres con umbral
    predeclarado y deteccion de ambiguedad. Nunca semantico."""
    if not norm_ev:
        return RealignmentResult(False, "empty")

    # Ventana derivada de los offsets propuestos (si son usables); si no, todo el
    # documento pero acotado por REALIGN_MAX_WINDOW (cota dura anti-DoS).
    doc_len = len(doc)
    if isinstance(hint_start, int) and isinstance(hint_end, int) and 0 <= hint_start <= doc_len:
        span = max(len(norm_ev), (hint_end - hint_start) if hint_end >= hint_start else 0)
        w_start = max(0, hint_start - REALIGN_WINDOW_SLACK)
        w_end = min(doc_len, hint_start + span + REALIGN_WINDOW_SLACK)
    else:
        w_start = 0
        w_end = min(doc_len, REALIGN_MAX_WINDOW)
    if w_end - w_start > REALIGN_MAX_WINDOW:
        w_end = w_start + REALIGN_MAX_WINDOW

    win_real = doc[w_start:w_end]
    norm_win, w_starts, w_ends = normalize_with_map(win_real)
    if not norm_win:
        return RealignmentResult(False, "no_match")

    lo, hi, score = _best_fuzzy_in(norm_win, norm_ev)
    if lo < 0 or score < REALIGN_SCORE_THRESHOLD:
        return RealignmentResult(False, "below_threshold", score=score)

    # Deteccion de AMBIGUEDAD: busca un segundo candidato comparable enmascarando
    # el mejor tramo. Si puntua >= umbral y dista <= EPS y mapea a otra rodaja
    # real => rechazo fail-closed.
    masked = norm_win[:lo] + ("\x00" * (hi - lo)) + norm_win[hi:]
    lo2, hi2, score2 = _best_fuzzy_in(masked, norm_ev)
    real_s, real_e = _real_span(w_starts, w_ends, lo, hi - lo)
    if lo2 >= 0 and score2 >= REALIGN_SCORE_THRESHOLD and (score - score2) <= REALIGN_AMBIGUITY_EPS:
        r2s, r2e = _real_span(w_starts, w_ends, lo2, hi2 - lo2)
        if (r2s, r2e) != (real_s, real_e):
            return RealignmentResult(False, "ambiguous", score=score)

    return RealignmentResult(True, "fuzzy", doc[real_s:real_e], real_s, real_e, score)


def realign_evidence(
    doc: str,
    evidence_text: str,
    hint_start: Optional[int] = None,
    hint_end: Optional[int] = None,
) -> RealignmentResult:
    """Intenta realinear ``evidence_text`` al documento REAL ``doc``.

    Escalera estricta: exacto -> normalizado-exacto -> fuzzy en ventana ->
    rechazo por ambiguedad/umbral -> (el llamante vuelve al original).

    INVARIANTE de salida: si ``ok``, entonces ``doc[start:end] == evidence_text``
    y ambos offsets son coherentes con ``doc``.
    """
    # Cotas duras (anti-DoS / payload grande) y guardas basicas.
    if not isinstance(doc, str) or not doc:
        return RealignmentResult(False, "no_document")
    if not isinstance(evidence_text, str) or not evidence_text.strip():
        return RealignmentResult(False, "empty")
    if len(evidence_text) > REALIGN_MAX_EVIDENCE:
        return RealignmentResult(False, "too_long")

    # Peldano 0: EXACTO. Subcadena literal directa.
    if evidence_text in doc:
        # Si el hint casa exactamente, respetalo; si no, primera ocurrencia.
        if (isinstance(hint_start, int) and isinstance(hint_end, int)
                and 0 <= hint_start <= hint_end <= len(doc)
                and doc[hint_start:hint_end] == evidence_text):
            return RealignmentResult(True, "exact", evidence_text, hint_start, hint_end, 1.0)
        occ = _all_occurrences(doc, evidence_text)
        if len(occ) == 1:
            s = occ[0]
            return RealignmentResult(True, "exact", evidence_text, s, s + len(evidence_text), 1.0)
        # Multiples ocurrencias literales sin hint fiable: desambigua por proximidad.
        if isinstance(hint_start, int):
            dists = sorted(occ, key=lambda s: abs(s - hint_start))
            if len(dists) >= 2 and abs(dists[0] - hint_start) == abs(dists[1] - hint_start):
                return RealignmentResult(False, "ambiguous")
            s = dists[0]
            return RealignmentResult(True, "exact", evidence_text, s, s + len(evidence_text), 1.0)
        return RealignmentResult(False, "ambiguous")

    # Preparacion normalizada del documento (reutilizada por peldanos 1).
    norm_doc, d_starts, d_ends = normalize_with_map(doc)
    norm_ev = _normalize_plain(evidence_text).strip()
    if not norm_ev:
        return RealignmentResult(False, "empty")

    # Peldano 1: NORMALIZADO-EXACTO.
    r1 = _tier_normalized(doc, norm_doc, d_starts, d_ends, norm_ev, hint_start)
    if r1.ok or r1.tier == "ambiguous":
        return r1

    # Peldano 2: FUZZY ACOTADO A VENTANA.
    return _tier_fuzzy(doc, norm_ev, hint_start, hint_end)


__all__ = [
    "RealignmentResult",
    "realign_evidence",
    "normalize_with_map",
    "REALIGN_SCORE_THRESHOLD",
    "REALIGN_AMBIGUITY_EPS",
    "REALIGN_WINDOW_SLACK",
    "REALIGN_MAX_WINDOW",
    "REALIGN_MAX_EVIDENCE",
]
