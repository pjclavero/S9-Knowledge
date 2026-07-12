"""Extractor de candidatos a partir de segmentos clasificados (v2 — endurecido).

Mejoras respecto a v1:
- Integra stopwords.py: filtra/baja confianza en candidatos débiles
- Anti-Character débil: una sola palabra capitalizada a inicio de frase NO es Character
  con confianza alta; solo sube si: 2+ tokens capitalizados, match en glosario, o
  patrón de evidencia explícita ("soy X", "se llama X", "el personaje X").
- Glosario POR WORKSPACE: carga state/glossary.db con el workspace real recibido.
- Ninguna stopword puede salir con confidence >= 0.85.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Optional

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Candidate
from review.classifier import ClassifiedSegment
from review.stopwords import is_stopword, is_weak_single_token

log = logging.getLogger(__name__)

# ── Patrones de extracción ────────────────────────────────────────────────────

# Nombres propios: secuencias de palabras capitalizadas (2-4 tokens)
# Para japonés/L5A: nombres como "Doji Satsume", "Bayushi Tsubaki"
_PROPER_NAME_RE = re.compile(
    r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){0,3})\b'
)

# Patrones de evidencia explícita de personaje
_CHAR_EVIDENCE_PATTERNS = [
    re.compile(r'\bsoy\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*)\b', re.IGNORECASE),
    re.compile(r'\bme\s+llamo\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*)\b', re.IGNORECASE),
    re.compile(r'\bse\s+llama\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*)\b', re.IGNORECASE),
    re.compile(r'\bel\s+personaje\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*)\b', re.IGNORECASE),
    re.compile(r'\bla\s+personaje\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*)\b', re.IGNORECASE),
    re.compile(r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*)\s+del\s+Clan\b', re.IGNORECASE),
    re.compile(r'\bpersonaje\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*)\b', re.IGNORECASE),
]

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


def _normalize_for_compare(text: str) -> str:
    """Minúsculas + elimina diacríticos."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _make_candidate_id(source_id: str, segment_id: str, kind: str, name: str) -> str:
    key = f"{source_id}|{segment_id}|{kind}|{name}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _load_glossary(repo_root: Path, workspace: str) -> dict[str, str]:
    """Carga glosario del workspace → {normalized_name: canonical_term}.

    Usa el workspace real recibido (no hardcodeado). Si glossary.db no existe
    o el workspace no tiene términos, retorna dict vacío y funciona con más
    conservadurismo (sin boosts de glosario).
    """
    db_path = repo_root / "state" / "glossary.db"
    if not db_path.exists():
        log.debug("glossary.db no encontrado en %s — modo sin glosario", db_path)
        return {}
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute(
            "SELECT canonical_term, normalized_term FROM glossary_terms WHERE workspace=? AND enabled=1",
            (workspace,),
        )
        result = {}
        for canonical, normalized in cur.fetchall():
            # Guardar por normalized (ya lo trae la DB) y también por nuestra normalización
            result[normalized.strip().lower()] = canonical.strip()
            result[_normalize_for_compare(canonical)] = canonical.strip()
        con.close()
        log.debug("Glosario cargado: %d términos para workspace '%s'", len(result), workspace)
        return result
    except Exception as e:
        log.warning("No se pudo cargar el glosario para workspace '%s': %s", workspace, e)
        return {}


def _glossary_snapshot(repo_root: Path, workspace: str, limit: int = 100) -> list[str]:
    """Retorna lista de canonical_term del glosario para el workspace (top por priority)."""
    db_path = repo_root / "state" / "glossary.db"
    if not db_path.exists():
        return []
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute(
            "SELECT canonical_term FROM glossary_terms WHERE workspace=? AND enabled=1 ORDER BY priority DESC, confidence DESC LIMIT ?",
            (workspace, limit),
        )
        terms = [row[0] for row in cur.fetchall()]
        con.close()
        return terms
    except Exception as e:
        log.warning("No se pudo obtener snapshot de glosario: %s", e)
        return []


def _has_explicit_char_evidence(name: str, text: str) -> bool:
    """True si el texto contiene un patrón de evidencia explícita para el nombre como personaje."""
    for pattern in _CHAR_EVIDENCE_PATTERNS:
        for m in pattern.finditer(text):
            matched = m.group(1).strip()
            if _normalize_for_compare(matched) == _normalize_for_compare(name):
                return True
            # Suficiencia parcial: el nombre está contenido en el match
            if _normalize_for_compare(name) in _normalize_for_compare(matched):
                return True
    return False


def _is_compound_proper_name(name: str) -> bool:
    """True si el nombre tiene 2+ tokens todos capitalizados (nombre propio compuesto)."""
    tokens = name.strip().split()
    if len(tokens) < 2:
        return False
    return all(t[0].isupper() for t in tokens if t)


def _character_confidence(name: str, text: str, glossary: dict[str, str], base_conf: float) -> float:
    """Calcula la confidence final de un candidato Character con reglas anti-débil.

    Reglas:
    1. Stopword → max 0.40 (weak)
    2. Single-token débil → max 0.50 (weak)
    3. Single-token no en glosario, sin evidencia explícita → max 0.70 (needs_review)
    4. Compound name (2+ tokens) → sube base
    5. Match en glosario → boost +0.20
    6. Evidencia explícita → boost +0.15
    Ninguna stopword puede superar 0.85.
    """
    norm = _normalize_for_compare(name)

    # Regla 1: stopword
    if is_stopword(name):
        return min(base_conf, 0.40)

    # Regla 2: single token débil (stopword o <3 chars)
    if is_weak_single_token(name):
        return min(base_conf, 0.50)

    conf = base_conf
    in_glossary = norm in glossary or any(
        norm in k or k in norm for k in glossary if len(k) > 3
    )

    # Regla 3: single token sin glosario y sin evidencia → cap 0.70
    tokens = name.strip().split()
    is_single = len(tokens) == 1
    has_evidence = _has_explicit_char_evidence(name, text)

    if is_single and not in_glossary and not has_evidence:
        conf = min(conf, 0.70)

    # Regla 4: compound name boost
    if _is_compound_proper_name(name):
        conf = min(conf + 0.05, 0.95)

    # Regla 5: glosario boost
    if in_glossary:
        conf = min(conf + 0.20, 0.95)

    # Regla 6: evidencia explícita boost
    if has_evidence:
        conf = min(conf + 0.15, 0.95)

    return round(conf, 3)


def _extract_entities(
    seg: ClassifiedSegment,
    glossary: dict[str, str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    text = seg["text"]
    seen_names: set[str] = set()

    for m in _PROPER_NAME_RE.finditer(text):
        name = m.group(1).strip()
        words = name.split()

        # Filtro básico: longitud mínima, no demasiado largo
        if len(name) < 4 or len(words) > 4:
            continue

        # Filtro: stopword pura → skip si la confidence resultante sería <= 0.40
        # (no vale la pena emitir basura aunque sea con flag weak)
        if is_stopword(name) and len(words) == 1:
            log.debug("Extractor: '%s' es stopword — descartado", name)
            continue

        if name in seen_names:
            continue
        seen_names.add(name)

        lower_name = name.lower()
        norm_name = _normalize_for_compare(name)

        # Determinar tipo base
        if any(kw in lower_name for kw in _LOCATION_KW):
            etype = "Location"
            base_conf = 0.70
        elif any(kw in lower_name for kw in _FACTION_KW):
            etype = "Faction"
            base_conf = 0.72
        else:
            etype = "Character"
            base_conf = 0.65

        # Aplicar reglas de confianza según tipo
        if etype == "Character":
            confidence = _character_confidence(name, text, glossary, base_conf)
        else:
            # Para Location y Faction: boost de glosario
            in_gloss = norm_name in glossary or any(
                norm_name in k or k in norm_name for k in glossary if len(k) > 3
            )
            if in_gloss:
                base_conf = min(base_conf + 0.20, 0.95)
            # Canonicalizar si está en glosario
            canonical = glossary.get(norm_name)
            if canonical and canonical != name:
                name = canonical
            confidence = base_conf

        # Canonicalizar nombre si está en glosario (Character también)
        if etype == "Character":
            canonical = glossary.get(norm_name)
            if canonical and canonical != name:
                log.debug("Extractor: canonicalizando '%s' → '%s'", name, canonical)
                name = canonical

        # Garantía final: ninguna stopword puede superar 0.85
        if is_stopword(name):
            confidence = min(confidence, 0.84)

        # Flag weak para el agente B (auto_decider puede usar esto)
        weak = confidence <= 0.50 or is_stopword(name) or is_weak_single_token(name)

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
        # Añadir flag weak en el dict al serializar (Candidate no tiene el campo pero lo añadimos
        # al to_dict vía un atributo dinámico — solo lo usará el serializado JSON)
        if weak:
            c._weak = True  # type: ignore[attr-defined]
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
    glossary: dict[str, str],
) -> list[Candidate]:
    """Extrae candidatos de todos los segmentos marcados should_extract."""
    all_candidates: list[Candidate] = []

    for seg in classified:
        if not seg["should_extract"]:
            continue
        entities = _extract_entities(seg, glossary)
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

    log.info("Extracción heurística: %d candidatos únicos de %d segmentos", len(unique), len(classified))
    return unique


def run(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Entry point: extrae candidatos y guarda candidates.json."""
    in_path = repo_root / "output" / "reviews" / workspace / source_id / "segments.classified.json"
    if not in_path.exists():
        raise FileNotFoundError(f"segments.classified.json no encontrado: {in_path}")

    with in_path.open(encoding="utf-8") as f:
        classified: list[ClassifiedSegment] = json.load(f)

    glossary = _load_glossary(repo_root, workspace)
    candidates = extract_from_segments(classified, glossary)

    out_path = in_path.parent / "candidates.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in candidates], f, ensure_ascii=False, indent=2)

    log.info("candidates.json → %s (%d candidatos)", out_path, len(candidates))
    return out_path
