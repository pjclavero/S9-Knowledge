"""Clasificador de segmentos de transcripción.

Clasifica cada Segment en una categoría narrativa y decide si se deben
extraer entidades (should_extract).

Categorías:
  session_play, lore, rules_explanation, combat, travel,
  dialogue, table_talk, intro_outro, noise, unknown

Heurísticas basadas en keywords en español e inglés.
"""
from __future__ import annotations
import json
import logging
import re
import sys
from pathlib import Path
from typing import TypedDict

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Segment

log = logging.getLogger(__name__)

# ── Definición de categorías ──────────────────────────────────────────────────

CATEGORIES = [
    "session_play", "lore", "rules_explanation", "combat", "travel",
    "dialogue", "table_talk", "intro_outro", "noise", "unknown",
]

# Categorías donde should_extract = False
NO_EXTRACT = {"intro_outro", "noise", "table_talk"}

# Palabras clave por categoría (minúsculas, coincidencia parcial)
_KW: dict[str, list[str]] = {
    "intro_outro": [
        "hola buenas", "bienvenidos", "suscribete", "suscríbete", "like",
        "canal", "nuevo vídeo", "nuevo video", "hasta la próxima",
        "nos vemos", "hasta pronto", "patreon", "pausa publicitaria",
        "intro", "outro", "presentación", "recordad que", "esta semana",
        "últimas sesiones", "os recomiendo", "anterior capítulo",
    ],
    "table_talk": [
        "máster", "master dice", "voy a tirar", "tirada de", "dado",
        "d10", "d6", "d20", "ventaja", "desventaja", "me sale",
        "fallo crítico", "éxito crítico", "puntos de guardia",
        "mecánica", "regla", "hoja de personaje", "xp", "experiencia",
        "fuera de juego", "off game", "ooc", "out of character",
        "perdona", "un momento", "espera", "pausa",
    ],
    "rules_explanation": [
        "la regla dice", "según las reglas", "en el reglamento",
        "mecánica de", "acción de", "tirada de skill", "dificultad",
        "la mecánica", "funciona así", "técnicamente", "por las reglas",
    ],
    "combat": [
        "ataque", "ataca", "golpe", "herida", "daño", "muerte",
        "batalla", "combate", "lucha", "espada", "flecha", "disparo",
        "huye", "huyen", "defiende", "bloquea", "esquiva",
        "cae al suelo", "derrota", "sangre",
    ],
    "lore": [
        "según la leyenda", "se dice que", "la historia cuenta",
        "clan", "familia", "dinastía", "linaje", "antiguo", "templo",
        "profecía", "kami", "elemental", "bushido", "honor",
        "el imperio", "rokugán", "rokugan", "jade", "obsidiana",
        "corte imperial", "shogun", "daimyo", "samurai", "ronin",
    ],
    "travel": [
        "viajan", "viajamos", "camino a", "en ruta", "llegamos",
        "se dirigen", "cruzamos", "atraviesan", "aldea", "ciudad",
        "pueblo", "posada", "mansión", "castillo",
    ],
    "dialogue": [
        "dice", "responde", "pregunta", "contesta", "añade",
        "exclama", "susurra", "explica", "propone", "le dice",
    ],
    "noise": [
        "[inaudible]", "[ruido]", "[música]", "[silencio]", "...",
        "hmm", "ehh", "ahh", "mmm",
    ],
}

# Pesos de categoría (para desempate)
_PRIORITY = {
    "intro_outro": 10,
    "noise": 9,
    "table_talk": 8,
    "rules_explanation": 5,
    "combat": 4,
    "lore": 4,
    "travel": 3,
    "dialogue": 2,
    "session_play": 1,
    "unknown": 0,
}


class ClassifiedSegment(TypedDict):
    segment_id: str
    source_id: str
    source_kind: str
    workspace: str
    timestamp_start: str
    timestamp_end: str
    text: str
    lines: list
    category: str
    should_extract: bool
    category_scores: dict


def _score_text(text: str) -> dict[str, int]:
    t = text.lower()
    scores: dict[str, int] = {}
    for cat, kws in _KW.items():
        hit = sum(1 for kw in kws if kw in t)
        if hit:
            scores[cat] = hit
    return scores


def classify_segment(seg: Segment) -> ClassifiedSegment:
    scores = _score_text(seg.text)

    if not scores:
        category = "session_play" if len(seg.text) > 200 else "unknown"
    else:
        # Elegir categoría con mayor score, desempate por prioridad
        category = max(
            scores,
            key=lambda c: (scores[c], _PRIORITY.get(c, 0)),
        )

    should_extract = category not in NO_EXTRACT
    # rules_explanation: solo si el segmento es largo (aporta entidades)
    if category == "rules_explanation" and len(seg.text) < 300:
        should_extract = False

    return ClassifiedSegment(
        segment_id=seg.segment_id,
        source_id=seg.source_id,
        source_kind=seg.source_kind,
        workspace=seg.workspace,
        timestamp_start=seg.timestamp_start,
        timestamp_end=seg.timestamp_end,
        text=seg.text,
        lines=seg.lines,
        category=category,
        should_extract=should_extract,
        category_scores=scores,
    )


def classify_segments(segments: list[Segment]) -> list[ClassifiedSegment]:
    return [classify_segment(s) for s in segments]


def run(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Entry point: clasifica y guarda segments.classified.json."""
    in_path = repo_root / "output" / "reviews" / workspace / source_id / "segments.json"
    if not in_path.exists():
        raise FileNotFoundError(f"segments.json no encontrado: {in_path}")

    with in_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    segments = [Segment.from_dict(d) for d in raw]
    classified = classify_segments(segments)

    out_path = in_path.parent / "segments.classified.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(classified, f, ensure_ascii=False, indent=2)

    total = len(classified)
    extractable = sum(1 for c in classified if c["should_extract"])
    log.info(
        "Clasificación: %d segmentos, %d extraíbles, %d omitidos",
        total, extractable, total - extractable,
    )
    return out_path
