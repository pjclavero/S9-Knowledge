"""Extractor LLM vía Ollama (qwen2.5:7b) para el pipeline S9 Knowledge.

Contrato:
    extract_with_llm(segments, glossary_snapshot, workspace) -> list[Candidate]

Degrada a lista vacía (con warning) si Ollama no responde o JSON inválido.
Nunca crashea: los errores se loguean y se retorna [].
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Candidate
from review.classifier import ClassifiedSegment

log = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
OLLAMA_URL = "http://192.168.1.157:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 120  # segundos por segmento

_ALLOWED_TYPES = {"Character", "Location", "Faction", "Object", "Event", "Concept"}
_MAX_CANDIDATES_PER_SEGMENT = 30

_SYSTEM_PROMPT = """Eres un extractor de entidades para un juego de rol de mesa en japonés/español (Legend of the Five Rings).
INSTRUCCIONES ESTRICTAS:
- Devuelve ÚNICAMENTE JSON válido con la estructura: {"entities": [], "relations": []}
- Cada entidad: {"name": "...", "type": "...", "evidence": "...", "confidence": 0.0-1.0}
- Tipos permitidos SOLO: Character, Location, Faction, Object, Event, Concept
- NO inventes timestamps (no incluyas campos de tiempo)
- NO incluyas palabras funcionales, artículos, pronombres, verbos comunes
- NO incluyas stopwords en español (todo, como, pues, vale, bueno, etc.)
- Si no hay entidades relevantes, devuelve {"entities": [], "relations": []}
- La evidence debe ser una cita textual corta del segmento que justifica la entidad
- confidence: 0.9 si el nombre es inequívoco, 0.7 si hay ambigüedad, 0.5 si es inferencia
- Entidades de nombre propio compuesto (dos+ palabras capitalizadas) reciben prioridad
- NO incluyas una entidad si no tienes evidence textual del segmento
"""


def _make_candidate_id(source_id: str, segment_id: str, kind: str, name: str) -> str:
    key = f"{source_id}|{segment_id}|{kind}|{name}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _call_ollama(prompt: str, timeout: int = OLLAMA_TIMEOUT) -> Optional[str]:
    """Llama a Ollama y retorna el texto generado, o None si hay error."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2048},
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            data = json.loads(raw)
            return data.get("response", "")
    except urllib.error.URLError as e:
        log.warning("Ollama no disponible: %s", e)
        return None
    except Exception as e:
        log.warning("Error llamando a Ollama: %s", e)
        return None


def _extract_json_from_response(text: str) -> Optional[dict]:
    """Extrae el primer bloque JSON válido de la respuesta."""
    if not text:
        return None
    # Intentar parsear directamente
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Buscar bloque JSON delimitado por ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Buscar el primer { ... } en el texto
    m2 = re.search(r"(\{.*\})", text, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(1))
        except json.JSONDecodeError:
            pass
    return None


def _validate_entity(ent: Any) -> Optional[dict]:
    """Valida un dict de entidad de la respuesta LLM. Retorna None si inválido."""
    if not isinstance(ent, dict):
        return None
    name = ent.get("name", "").strip()
    etype = ent.get("type", "").strip()
    evidence = ent.get("evidence", "").strip()
    confidence = ent.get("confidence", 0.5)

    if not name or len(name) < 2:
        return None
    if etype not in _ALLOWED_TYPES:
        log.debug("LLM: tipo no permitido '%s' para '%s' — descartado", etype, name)
        return None
    if not evidence:
        log.debug("LLM: entidad sin evidence '%s' — descartada", name)
        return None
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = float(max(0.0, min(1.0, confidence)))

    return {"name": name, "type": etype, "evidence": evidence, "confidence": confidence}


def extract_with_llm(
    segments: list[ClassifiedSegment],
    glossary_snapshot: list[str],
    workspace: str,
) -> list[Candidate]:
    """Extrae candidatos vía LLM para los segmentos con should_extract=True.

    Args:
        segments: lista de segmentos clasificados
        glossary_snapshot: lista de términos canónicos del glosario (top-N) para contexto
        workspace: nombre del workspace

    Returns:
        Lista de Candidate; puede estar vacía si Ollama falla o no hay resultados.
    """
    extractable = [s for s in segments if s.get("should_extract")]
    if not extractable:
        return []

    log.info("LLM extractor: %d segmentos a procesar", len(extractable))
    all_candidates: list[Candidate] = []
    seen_ids: set[str] = set()

    # Contexto de glosario (primeros 50 términos)
    gloss_ctx = ""
    if glossary_snapshot:
        top = glossary_snapshot[:50]
        gloss_ctx = "\nGlosario del mundo (términos canónicos conocidos):\n" + ", ".join(top)

    for seg in extractable:
        text = seg.get("text", "").strip()
        if not text:
            continue

        prompt = (
            f"{_SYSTEM_PROMPT}"
            f"{gloss_ctx}\n\n"
            f"Segmento de transcripción (workspace={workspace}):\n{text}\n\n"
            f"Extrae entidades relevantes del segmento anterior. Solo JSON:"
        )

        raw_response = _call_ollama(prompt)
        if raw_response is None:
            log.warning("LLM: Ollama no respondió para segmento %s — omitido", seg.get("segment_id"))
            continue

        parsed = _extract_json_from_response(raw_response)
        if parsed is None:
            log.warning(
                "LLM: JSON inválido en respuesta para segmento %s — descartado. Raw: %s",
                seg.get("segment_id"), raw_response[:100],
            )
            continue

        entities_raw = parsed.get("entities", [])
        if not isinstance(entities_raw, list):
            log.warning("LLM: 'entities' no es lista en segmento %s", seg.get("segment_id"))
            continue

        seg_candidates: list[Candidate] = []
        for ent in entities_raw:
            validated = _validate_entity(ent)
            if validated is None:
                continue

            cid = _make_candidate_id(
                seg["source_id"], seg["segment_id"], "entity", validated["name"]
            )
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            candidate = Candidate(
                candidate_id=cid,
                source_id=seg["source_id"],
                segment_id=seg["segment_id"],
                workspace=seg["workspace"],
                kind="entity",
                name=validated["name"],
                entity_type=validated["type"],
                confidence=validated["confidence"],
                evidence=validated["evidence"][:300],
                timestamp_start=seg.get("timestamp_start", ""),
                timestamp_end=seg.get("timestamp_end", ""),
                source_kind=seg.get("source_kind", "audio"),
            )
            seg_candidates.append(candidate)

        # Si hay demasiados candidatos en un segmento, marcarlos todos needs_review
        if len(seg_candidates) > _MAX_CANDIDATES_PER_SEGMENT:
            log.warning(
                "LLM: %d candidatos en segmento %s (> %d) — marcando todos needs_review",
                len(seg_candidates), seg.get("segment_id"), _MAX_CANDIDATES_PER_SEGMENT,
            )
            for c in seg_candidates:
                # Bajamos confidence a zona needs_review (0.60-0.84)
                c.confidence = min(c.confidence, 0.75)

        all_candidates.extend(seg_candidates)

    log.info("LLM extractor: %d candidatos totales extraídos", len(all_candidates))
    return all_candidates


def is_ollama_available(timeout: int = 10) -> bool:
    """Comprueba si Ollama responde en el endpoint configurado."""
    try:
        req = urllib.request.Request(
            "http://192.168.1.157:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False
