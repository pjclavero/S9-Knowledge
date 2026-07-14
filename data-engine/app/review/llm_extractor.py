"""Extractor LLM vía Ollama (qwen2.5:7b) para el pipeline S9 Knowledge.

Contrato:
    extract_with_llm(segments, glossary_snapshot, workspace, seed=None) -> list[Candidate]

Degrada a lista vacía (con warning) si Ollama no responde o JSON inválido.
Nunca crashea: los errores se loguean y se retorna [].

Configuración (prioridad):
    1. Parámetros directos a extract_with_llm()
    2. Variable de entorno S9K_OLLAMA_URL / S9K_OLLAMA_MODEL
    3. data-engine/config/settings.yaml (sección ollama)
    4. Valores por defecto hardcodeados
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
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


# ── Carga de configuración ────────────────────────────────────────────────────

def _load_ollama_settings() -> dict:
    """Lee la sección 'ollama' de settings.yaml; devuelve {} si no disponible."""
    settings_file = _APP_DIR.parent / "config" / "settings.yaml"
    try:
        import yaml  # type: ignore
        with settings_file.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("ollama", {})
    except Exception:
        return {}


_CFG = _load_ollama_settings()

_OLLAMA_BASE_URL: str = (
    os.environ.get("S9K_OLLAMA_URL")
    or _CFG.get("base_url", "http://192.168.1.157:11434")
).rstrip("/")

OLLAMA_URL: str = _OLLAMA_BASE_URL + "/api/generate"
OLLAMA_MODEL: str = (
    os.environ.get("S9K_OLLAMA_MODEL")
    or _CFG.get("model", "qwen2.5:7b")
)
OLLAMA_TIMEOUT: int = int(_CFG.get("request_timeout", 120))
_OLLAMA_TEMPERATURE: float = float(_CFG.get("temperature", 0.0))

_ALLOWED_TYPES = {"Character", "Location", "Faction", "Object", "Event", "Concept"}
_ALLOWED_RELATION_TYPES = {
    "MEMBER_OF", "BELONGS_TO", "KNOWS", "HAS_FOUGHT", "FOUGHT_AT",
    "ALLIED_WITH", "ENEMIES_WITH", "OWNS", "DISCOVERED", "INVESTIGATES",
    "HAS_HEARD_ABOUT", "PARTICIPATED_IN", "LOCATED_IN", "WORKS_FOR",
    "CREATED", "SEEKS", "PROTECTS", "GUARDS", "SERVES",
}
_MAX_CANDIDATES_PER_SEGMENT = 30

_SYSTEM_PROMPT = """Eres un extractor de entidades y relaciones para un juego de rol de mesa en japonés/español (Legend of the Five Rings, L5R).

SALIDA: devuelve ÚNICAMENTE JSON válido: {"entities": [], "relations": []}

ENTIDADES: {"name": "...", "type": "...", "evidence": "...", "confidence": 0.0-1.0}
- Tipos permitidos SOLO: Character, Location, Faction, Object, Event, Concept
- Prioriza nombres propios compuestos (dos+ palabras capitalizadas).
- NO incluyas artículos, pronombres, verbos, ni stopwords (todo, como, pues, vale, bueno...).

RELACIONES: {"from_entity": "...", "relation_type": "...", "to_entity": "...", "evidence": "...", "confidence": 0.0-1.0}
Tipos permitidos y su ESQUEMA (origen -> destino). NO uses ningún tipo fuera de esta lista:
- MEMBER_OF        Character -> Faction     (pertenencia a clan/facción)
- BELONGS_TO       Object    -> Character/Faction
- KNOWS            Character -> Character
- HAS_FOUGHT       Character -> Character
- FOUGHT_AT        Character -> Location
- ALLIED_WITH      Faction   -> Faction     (o Character -> Character)
- ENEMIES_WITH     Faction/Character -> Faction/Character
- OWNS             Character -> Object
- CREATED          Character -> Object
- LOCATED_IN       Location/Character -> Location
- PARTICIPATED_IN  Character -> Event
- WORKS_FOR/SERVES Character -> Character/Faction
- DISCOVERED       Character -> Object/Location
- INVESTIGATES     Character -> Concept/Event/Object
- SEEKS            Character -> Object/Concept
- PROTECTS/GUARDS  Character -> Character/Location/Object
- HAS_HEARD_ABOUT  Character -> Character/Concept

REGLA DE DOMINIO (apellido -> clan). El apellido de un personaje es evidencia textual de su clan; emite MEMBER_OF hacia el clan citando el nombre como evidence:
- Bayushi, Shosuro, Soshi, Yogo, Yojiro  -> Clan Escorpión
- Kakita, Doji, Kayama, Asahina          -> Clan Grulla
- Shinjo, Utaku, Ide, Moto, Iuchi        -> Clan Unicornio
- Akodo, Matsu, Kitsu, Ikoma             -> Clan León
- Hida, Hiruma, Kuni, Yasuki             -> Clan Cangrejo
- Isawa, Shiba, Asako, Agasha            -> Clan Fénix
- Mirumoto, Togashi, Kitsuki             -> Clan Dragón

EJEMPLOS POSITIVOS (few-shot):
- "Bayushi Hisao llegó a la corte" -> {"from_entity":"Bayushi Hisao","relation_type":"MEMBER_OF","to_entity":"Clan Escorpión","evidence":"Bayushi Hisao","confidence":0.9}
- "Kakita Asuka y Bayushi Hisao ya se conocían" -> {"from_entity":"Kakita Asuka","relation_type":"KNOWS","to_entity":"Bayushi Hisao","evidence":"ya se conocían","confidence":0.9}
- "El templo está en Ciudad Moto" -> {"from_entity":"El Templo","relation_type":"LOCATED_IN","to_entity":"Ciudad Moto","evidence":"está en Ciudad Moto","confidence":0.85}
- "lucharon en Ciudad Moto" -> {"from_entity":"Kakita Asuka","relation_type":"FOUGHT_AT","to_entity":"Ciudad Moto","evidence":"lucharon en Ciudad Moto","confidence":0.8}
- "Doji Satsume porta la Espada Ancestral" -> {"from_entity":"Doji Satsume","relation_type":"OWNS","to_entity":"Espada Ancestral","evidence":"porta la Espada Ancestral","confidence":0.85}
- "El Clan Grulla se alió con el Clan León" -> {"from_entity":"Clan Grulla","relation_type":"ALLIED_WITH","to_entity":"Clan León","evidence":"se alió con el Clan León","confidence":0.9}
- "Escorpión y Grulla son enemigos" -> {"from_entity":"Clan Escorpión","relation_type":"ENEMIES_WITH","to_entity":"Clan Grulla","evidence":"son enemigos","confidence":0.9}
- "participaron en el Torneo de la Espada" -> {"from_entity":"Kakita Asuka","relation_type":"PARTICIPATED_IN","to_entity":"Torneo de la Espada","evidence":"participaron en el Torneo","confidence":0.8}

EJEMPLOS NEGATIVOS (NO hacer):
- NO conviertas cualquier verbo narrativo en relación permanente ("caminó", "habló", "miró" no son relaciones).
- NO infieras afiliaciones sin evidencia textual (si no aparece el apellido ni el clan, no emitas MEMBER_OF).
- NO inventes entidades destino que no aparezcan en el texto.
- NO uses tipos de relación fuera de la lista (p.ej. NO "SPEAKS_TO", NO "TRAVELS", NO "ENEMY_OF").

REGLAS ESTRICTAS:
- Emite una relación SOLO si origen y destino son entidades identificables en el texto.
- Conserva nombres canónicos compuestos (usa "Bayushi Hisao", no "Hisao").
- Toda relación y entidad requiere evidence: cita textual corta del segmento.
- confidence: 0.9 inequívoco, 0.7 ambiguo, 0.5 inferencia.
- Si no hay entidades o relaciones respaldadas por el texto: {"entities": [], "relations": []}
"""


def _make_candidate_id(source_id: str, segment_id: str, kind: str, name: str) -> str:
    key = f"{source_id}|{segment_id}|{kind}|{name}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _call_ollama(
    prompt: str,
    timeout: int = OLLAMA_TIMEOUT,
    seed: Optional[int] = None,
) -> Optional[str]:
    """Llama a Ollama y retorna el texto generado, o None si hay error."""
    options: dict = {"temperature": _OLLAMA_TEMPERATURE, "num_predict": 2048}
    if seed is not None:
        options["seed"] = seed

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": options,
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
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
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


def _validate_relation(rel: Any) -> Optional[dict]:
    """Valida un dict de relación de la respuesta LLM. Retorna None si inválido."""
    if not isinstance(rel, dict):
        return None
    from_entity = rel.get("from_entity", "").strip()
    relation_type = rel.get("relation_type", "").strip().upper()
    to_entity = rel.get("to_entity", "").strip()
    evidence = rel.get("evidence", "").strip()
    confidence = rel.get("confidence", 0.5)

    if not from_entity or len(from_entity) < 2:
        return None
    if not to_entity or len(to_entity) < 2:
        return None
    if relation_type not in _ALLOWED_RELATION_TYPES:
        log.debug("LLM: tipo de relación no permitido '%s' — descartado", relation_type)
        return None
    if not evidence:
        log.debug("LLM: relación sin evidence '%s→%s' — descartada", from_entity, to_entity)
        return None
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = float(max(0.0, min(1.0, confidence)))
    return {
        "from_entity": from_entity,
        "relation_type": relation_type,
        "to_entity": to_entity,
        "evidence": evidence,
        "confidence": confidence,
    }


def extract_with_llm(
    segments: list[ClassifiedSegment],
    glossary_snapshot: list[str],
    workspace: str,
    seed: Optional[int] = None,
) -> list[Candidate]:
    """Extrae candidatos vía LLM para los segmentos con should_extract=True.

    Args:
        segments: lista de segmentos clasificados
        glossary_snapshot: lista de términos canónicos del glosario (top-N) para contexto
        workspace: nombre del workspace
        seed: semilla para Ollama (None = no seed; 42 recomendado en benchmark)

    Returns:
        Lista de Candidate; puede estar vacía si Ollama falla o no hay resultados.
    """
    extractable = [s for s in segments if s.get("should_extract")]
    if not extractable:
        return []

    log.info("LLM extractor: %d segmentos a procesar (seed=%s)", len(extractable), seed)
    all_candidates: list[Candidate] = []
    seen_ids: set[str] = set()

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
            f"Extrae entidades y relaciones relevantes del segmento anterior. Solo JSON:"
        )

        raw_response = _call_ollama(prompt, seed=seed)
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

        seg_candidates: list[Candidate] = []

        # ── Entidades ──────────────────────────────────────────────────────────
        entities_raw = parsed.get("entities", [])
        if not isinstance(entities_raw, list):
            log.warning("LLM: 'entities' no es lista en segmento %s", seg.get("segment_id"))
            entities_raw = []

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
            seg_candidates.append(Candidate(
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
            ))

        # ── Relaciones ─────────────────────────────────────────────────────────
        relations_raw = parsed.get("relations", [])
        if not isinstance(relations_raw, list):
            log.warning("LLM: 'relations' no es lista en segmento %s", seg.get("segment_id"))
            relations_raw = []

        for rel in relations_raw:
            validated_r = _validate_relation(rel)
            if validated_r is None:
                continue
            rel_key = (
                f"{validated_r['from_entity']}|"
                f"{validated_r['relation_type']}|"
                f"{validated_r['to_entity']}"
            )
            cid = _make_candidate_id(
                seg["source_id"], seg["segment_id"], "relation", rel_key
            )
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            seg_candidates.append(Candidate(
                candidate_id=cid,
                source_id=seg["source_id"],
                segment_id=seg["segment_id"],
                workspace=seg["workspace"],
                kind="relation",
                from_entity=validated_r["from_entity"],
                to_entity=validated_r["to_entity"],
                relation_type=validated_r["relation_type"],
                confidence=validated_r["confidence"],
                evidence=validated_r["evidence"][:300],
                timestamp_start=seg.get("timestamp_start", ""),
                timestamp_end=seg.get("timestamp_end", ""),
                source_kind=seg.get("source_kind", "audio"),
            ))

        if len(seg_candidates) > _MAX_CANDIDATES_PER_SEGMENT:
            log.warning(
                "LLM: %d candidatos en segmento %s (> %d) — marcando todos needs_review",
                len(seg_candidates), seg.get("segment_id"), _MAX_CANDIDATES_PER_SEGMENT,
            )
            for c in seg_candidates:
                c.confidence = min(c.confidence, 0.75)

        all_candidates.extend(seg_candidates)

    n_ent = sum(1 for c in all_candidates if c.kind == "entity")
    n_rel = sum(1 for c in all_candidates if c.kind == "relation")
    log.info("LLM extractor: %d candidatos totales (%d entidades, %d relaciones)", len(all_candidates), n_ent, n_rel)
    return all_candidates


def is_ollama_available(timeout: int = 10) -> bool:
    """Comprueba si Ollama responde en el endpoint configurado."""
    try:
        req = urllib.request.Request(
            _OLLAMA_BASE_URL + "/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False
