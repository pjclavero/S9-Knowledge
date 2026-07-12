"""Extractor de candidatos a partir de segmentos clasificados.

Extrae entidades, relaciones, eventos, localizaciones, objetos, rumores y
session_facts de segmentos con should_extract=True.

Usa heurísticas + glosario (glossary.db). NO usa LLM ni Neo4j.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Candidate
from review.classifier import ClassifiedSegment

log = logging.getLogger(__name__)

# ── Patrones de extracción ────────────────────────────────────────────────────

# Nombres propios: secuencias de palabras capitalizadas (2-4 tokens)
# Para japonés/L5A: nombres como "Doji Satsume", "Bayushi Tsubaki"
_PROPER_NAME_RE = re.compile(
    r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){0,3})\b'
)

# Clanes L5A conocidos
_CLANS = {
    "crab": "Clan Cangrejo", "crane": "Clan Grulla", "dragon": "Clan Dragón",
    "lion": "Clan León", "phoenix": "Clan Fénix", "scorpion": "Clan Escorpión",
    "unicorn": "Clan Unicornio", "mantis": "Clan Mantis", "spider": "Clan Araña",
    "cangrejo": "Clan Cangrejo", "grulla": "Clan Grulla", "dragón": "Clan Dragón",
    "dragón clan": "Clan Dragón", "escorpión": "Clan Escorpión",
    "unicornio": "Clan Unicornio",
}

# Términos de tipo "lugar"
_LOCATION_KW = [
    "castillo", "templo", "aldea", "ciudad", "ciudad de", "palacio",
    "provincia", "región", "distrito", "fortaleza", "puerto", "río",
    "montaña", "bosque", "jardín",
]

# Términos de tipo "facción/organización"
_FACTION_KW = [
    "clan", "familia", "escuela", "orden", "gremio", "guardia",
    "magistrados", "legión",
]

# Relaciones comunes
_RELATION_PATTERNS = [
    (r'\b(\w[\w\s]{1,20})\s+(?:pertenece|pertenecen)\s+a\s+(?:el|la|los|las)?\s*([\w\s]{2,30})', "BELONGS_TO"),
    (r'\b(\w[\w\s]{1,20})\s+(?:investiga|investigan)\s+([\w\s]{2,30})', "INVESTIGATES"),
    (r'\b(\w[\w\s]{1,20})\s+(?:ataca|atacan|golpea|lucha contra)\s+([\w\s]{2,30})', "ATTACKED"),
    (r'\b(\w[\w\s]{1,20})\s+(?:habla con|hablan con|conversa con)\s+([\w\s]{2,30})', "TALKED_TO"),
    (r'\b(\w[\w\s]{1,20})\s+(?:sospecha de|sospecha que)\s+([\w\s]{2,30})', "SUSPECTS"),
    (r'\b(\w[\w\s]{1,20})\s+(?:conoce|conocen)\s+a\s+([\w\s]{2,30})', "KNOWS"),
    (r'\b(\w[\w\s]{1,20})\s+(?:trabaja para|sirve a|sirven a)\s+([\w\s]{2,30})', "WORKS_FOR"),
    (r'\b(\w[\w\s]{1,20})\s+(?:descubre|descubren|encuentra|encuentran)\s+([\w\s]{2,30})', "DISCOVERS"),
]


def _make_candidate_id(source_id: str, segment_id: str, kind: str, name: str) -> str:
    key = f"{source_id}|{segment_id}|{kind}|{name}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _load_glossary_names(repo_root: Path, workspace: str) -> set[str]:
    """Carga nombres canónicos del glosario para boost de confianza."""
    db_path = repo_root / "state" / "glossary.db"
    if not db_path.exists():
        return set()
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute(
            "SELECT canonical_term FROM glossary_terms WHERE workspace=? AND enabled=1",
            (workspace,),
        )
        names = {row[0].strip().lower() for row in cur.fetchall()}
        con.close()
        return names
    except Exception as e:
        log.warning("No se pudo cargar el glosario: %s", e)
        return set()


def _extract_entities(
    seg: ClassifiedSegment,
    glossary_names: set[str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    text = seg["text"]
    seen_names: set[str] = set()

    # Nombres propios
    for m in _PROPER_NAME_RE.finditer(text):
        name = m.group(1).strip()
        # Filtros básicos: longitud, no es solo artículo/preposición
        words = name.split()
        if len(name) < 4 or len(words) > 4:
            continue
        if name.lower() in {"esta", "este", "esos", "esas", "pero", "para"}:
            continue
        if name in seen_names:
            continue
        seen_names.add(name)

        # Determinar tipo
        lower_name = name.lower()
        if any(kw in lower_name for kw in _LOCATION_KW):
            etype = "Location"
            confidence = 0.70
        elif any(kw in lower_name for kw in _FACTION_KW):
            etype = "Faction"
            confidence = 0.72
        else:
            etype = "Character"
            confidence = 0.65

        # Boost si está en el glosario
        if lower_name in glossary_names or any(
            lower_name in gn or gn in lower_name for gn in glossary_names
        ):
            confidence = min(confidence + 0.20, 0.95)

        cid = _make_candidate_id(seg["source_id"], seg["segment_id"], "entity", name)
        c = Candidate(
            candidate_id=cid,
            source_id=seg["source_id"],
            segment_id=seg["segment_id"],
            workspace=seg["workspace"],
            kind="entity",
            name=name,
            entity_type=etype,
            confidence=confidence,
            evidence=text[:200],
            timestamp_start=seg["timestamp_start"],
            timestamp_end=seg["timestamp_end"],
            source_kind=seg["source_kind"],
        )
        candidates.append(c)

    # Clanes explícitos
    text_lower = text.lower()
    for kw, clan_name in _CLANS.items():
        if kw in text_lower and clan_name not in seen_names:
            seen_names.add(clan_name)
            cid = _make_candidate_id(seg["source_id"], seg["segment_id"], "entity", clan_name)
            c = Candidate(
                candidate_id=cid,
                source_id=seg["source_id"],
                segment_id=seg["segment_id"],
                workspace=seg["workspace"],
                kind="entity",
                name=clan_name,
                entity_type="Clan",
                confidence=0.85,
                evidence=text[:200],
                timestamp_start=seg["timestamp_start"],
                timestamp_end=seg["timestamp_end"],
                source_kind=seg["source_kind"],
            )
            candidates.append(c)

    return candidates


def _extract_relations(
    seg: ClassifiedSegment,
    entity_names: list[str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    text = seg["text"]

    for pattern, rel_type in _RELATION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            from_raw = m.group(1).strip()
            to_raw = m.group(2).strip()
            if len(from_raw) < 3 or len(to_raw) < 3:
                continue
            cid = _make_candidate_id(
                seg["source_id"], seg["segment_id"], "relation",
                f"{from_raw}|{rel_type}|{to_raw}"
            )
            c = Candidate(
                candidate_id=cid,
                source_id=seg["source_id"],
                segment_id=seg["segment_id"],
                workspace=seg["workspace"],
                kind="relation",
                from_entity=from_raw,
                to_entity=to_raw,
                relation_type=rel_type,
                confidence=0.62,
                evidence=text[:200],
                timestamp_start=seg["timestamp_start"],
                timestamp_end=seg["timestamp_end"],
                source_kind=seg["source_kind"],
            )
            candidates.append(c)

    return candidates


def extract_from_segments(
    classified: list[ClassifiedSegment],
    glossary_names: set[str],
) -> list[Candidate]:
    """Extrae candidatos de todos los segmentos marcados should_extract."""
    all_candidates: list[Candidate] = []

    for seg in classified:
        if not seg["should_extract"]:
            continue
        entities = _extract_entities(seg, glossary_names)
        entity_names = [c.name for c in entities if c.name]
        relations = _extract_relations(seg, entity_names)
        all_candidates.extend(entities)
        all_candidates.extend(relations)

    # Deduplicar por candidate_id
    seen: set[str] = set()
    unique: list[Candidate] = []
    for c in all_candidates:
        if c.candidate_id not in seen:
            seen.add(c.candidate_id)
            unique.append(c)

    log.info("Extracción: %d candidatos únicos de %d segmentos", len(unique), len(classified))
    return unique


def run(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Entry point: extrae candidatos y guarda candidates.json."""
    in_path = repo_root / "output" / "reviews" / workspace / source_id / "segments.classified.json"
    if not in_path.exists():
        raise FileNotFoundError(f"segments.classified.json no encontrado: {in_path}")

    with in_path.open(encoding="utf-8") as f:
        classified: list[ClassifiedSegment] = json.load(f)

    glossary_names = _load_glossary_names(repo_root, workspace)
    candidates = extract_from_segments(classified, glossary_names)

    out_path = in_path.parent / "candidates.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in candidates], f, ensure_ascii=False, indent=2)

    log.info("candidates.json → %s (%d candidatos)", out_path, len(candidates))
    return out_path
