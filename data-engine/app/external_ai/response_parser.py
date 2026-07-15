# -*- coding: utf-8 -*-
"""Parser y validador de respuestas JSON de modelos de IA externa.

Flujo principal:
  raw_text -> extract_json -> normalizar a lista -> validate_decision por ítem
  -> ModelReviewResponse

Modo sombra: ningún resultado escribe en Neo4j.
"""
from __future__ import annotations

import json
import re
import unicodedata

from external_ai.errors import InvalidResponseError
from external_ai.models import (
    ALLOWED_ENTITY_TYPES,
    VALID_DECISIONS,
    ModelReviewDecision,
    ModelReviewResponse,
    ReviewBatchRequest,
    ReviewItem,
)

# Versión de prompt que este parser asume como producida por prompts.py
_PROMPT_VERSION = "1.0"

# Claves permitidas en el nivel superior de un objeto review
_ALLOWED_REVIEW_KEYS = frozenset({
    "candidate_id",
    "decision",
    "canonical_name",
    "entity_type",
    "matched_existing",
    "evidence",
    "confidence",
    "reason_codes",
    "explanation",
    "warnings",
})


# ---------------------------------------------------------------------------
# Extracción de JSON crudo
# ---------------------------------------------------------------------------


def _find_balanced_json(text: str) -> str | None:
    """Busca el primer objeto JSON balanceado '{...}' o lista '[...]' en text.

    Devuelve la subcadena o None si no se encuentra.
    """
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start=start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
    return None


def extract_json(raw_text: str) -> dict:
    """Extrae y parsea el primer objeto JSON de la respuesta cruda del modelo.

    Estrategias (en orden):
    1. json.loads directo del texto completo (trimmed).
    2. Bloque de código ```json ... ``` o ``` ... ```.
    3. Búsqueda del primer '{' y último '}' con balanceo de llaves.

    Devuelve
    --------
    dict — objeto JSON parseado.

    Lanza
    -----
    InvalidResponseError si ninguna estrategia tiene éxito.
    """
    text = raw_text.strip()

    # Estrategia 1: parse directo
    try:
        result = json.loads(text)
        if isinstance(result, (dict, list)):
            return result if isinstance(result, dict) else {"reviews": result}
    except json.JSONDecodeError:
        pass

    # Estrategia 2: bloque de código con fence ```json o ```
    fence_pattern = re.compile(
        r"```(?:json)?\s*\n?(.*?)```",
        re.DOTALL | re.IGNORECASE,
    )
    for match in fence_pattern.finditer(text):
        candidate = match.group(1).strip()
        try:
            result = json.loads(candidate)
            if isinstance(result, (dict, list)):
                return result if isinstance(result, dict) else {"reviews": result}
        except json.JSONDecodeError:
            continue

    # Estrategia 3: búsqueda balanceada de {…}
    balanced = _find_balanced_json(text)
    if balanced is not None:
        try:
            result = json.loads(balanced)
            if isinstance(result, (dict, list)):
                return result if isinstance(result, dict) else {"reviews": result}
        except json.JSONDecodeError:
            pass

    raise InvalidResponseError(
        "No se pudo extraer JSON válido de la respuesta del modelo. "
        f"Primeros 200 chars: {raw_text[:200]!r}"
    )


# ---------------------------------------------------------------------------
# Normalización de texto para comparación de evidencia
# ---------------------------------------------------------------------------


def _normalize_evidence(s: str) -> str:
    """Normaliza un string para comparación de subcadenas de evidencia.

    Aplica:
    - Descomposición NFKD y eliminación de diacríticos (acentos).
    - Conversión a minúsculas.
    - Colapso de espacios en blanco múltiples.
    """
    # Descomposición NFKD + filtrar categoría Mn (marcas no espaciadoras = acentos)
    nfkd = unicodedata.normalize("NFKD", s)
    without_accents = "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")
    lowered = without_accents.lower()
    # Colapsar cualquier secuencia de espacios/tabs/newlines
    collapsed = re.sub(r"\s+", " ", lowered).strip()
    return collapsed


# ---------------------------------------------------------------------------
# Validación de una decisión individual
# ---------------------------------------------------------------------------


def validate_decision(
    raw: dict,
    item: ReviewItem,
) -> tuple[ModelReviewDecision | None, list[str]]:
    """Valida el dict crudo de una decisión de modelo contra el ReviewItem esperado.

    Parámetros
    ----------
    raw:
        Dict de una sola decisión tal como viene del modelo.
    item:
        ReviewItem original al que debe referirse.

    Devuelve
    --------
    (ModelReviewDecision, []) si todo es válido.
    (None, [errores...]) si hay algún error hard.

    Errores hard (devuelven None):
    - candidate_id ausente o no coincide.
    - decision fuera de VALID_DECISIONS.
    - confidence no numérica.
    - entity_type no nula y fuera de ALLOWED_ENTITY_TYPES.
    - evidence vacía o no encontrada literalmente en segment_text.

    Advertencias (se añaden a warnings pero no bloquean):
    - Claves no esperadas en el dict.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- candidate_id ---
    cid = raw.get("candidate_id")
    if cid is None:
        errors.append("candidate_id: ausente en la respuesta del modelo")
        return None, errors
    if str(cid) != str(item.candidate_id):
        errors.append(
            f"candidate_id: esperado {item.candidate_id!r}, recibido {cid!r}"
        )
        return None, errors

    # --- decision ---
    decision = raw.get("decision")
    if decision not in VALID_DECISIONS:
        errors.append(
            f"decision: valor inválido {decision!r}; "
            f"debe ser uno de {VALID_DECISIONS}"
        )

    # --- confidence ---
    raw_confidence = raw.get("confidence", 0.0)
    if isinstance(raw_confidence, bool):
        # bool es subclase de int en Python; tratarlo como error
        errors.append(
            f"confidence: tipo booleano no aceptado, valor={raw_confidence!r}"
        )
        confidence = 0.0
    elif isinstance(raw_confidence, (int, float)):
        # Coercionar/clamp al rango [0, 1]
        confidence = float(max(0.0, min(1.0, raw_confidence)))
    else:
        errors.append(
            f"confidence: no es un número, recibido {raw_confidence!r}"
        )
        confidence = 0.0

    # --- entity_type ---
    entity_type = raw.get("entity_type")
    if entity_type is not None and entity_type not in ALLOWED_ENTITY_TYPES:
        errors.append(
            f"entity_type: valor inválido {entity_type!r}; "
            f"debe ser uno de {ALLOWED_ENTITY_TYPES} o null"
        )

    # --- evidence: no vacía y debe aparecer literalmente en segment_text ---
    evidence = raw.get("evidence", "")
    if not isinstance(evidence, str):
        evidence = str(evidence) if evidence is not None else ""

    if not evidence.strip():
        errors.append("evidence: está vacía o ausente")
    else:
        norm_evidence = _normalize_evidence(evidence)
        norm_segment = _normalize_evidence(item.segment_text)
        if norm_evidence not in norm_segment:
            errors.append("evidence_not_in_segment")

    # --- claves inesperadas (advertencia, no error hard) ---
    unexpected = set(raw.keys()) - _ALLOWED_REVIEW_KEYS
    if unexpected:
        warnings.append(
            f"claves_inesperadas: {sorted(unexpected)}"
        )

    # Si hay errores hard, devolver None
    if errors:
        return None, errors

    # Construir ModelReviewDecision
    raw_warnings = raw.get("warnings", [])
    if isinstance(raw_warnings, list):
        all_warnings = list(raw_warnings) + warnings
    else:
        all_warnings = warnings

    reason_codes = raw.get("reason_codes", [])
    if not isinstance(reason_codes, list):
        reason_codes = [str(reason_codes)] if reason_codes else []

    decision_obj = ModelReviewDecision(
        candidate_id=str(cid),
        decision=str(decision),
        canonical_name=raw.get("canonical_name"),
        entity_type=entity_type,
        matched_existing=raw.get("matched_existing"),
        evidence=evidence,
        confidence=confidence,
        reason_codes=reason_codes,
        explanation=str(raw.get("explanation", "")),
        warnings=all_warnings,
    )
    return decision_obj, []


# ---------------------------------------------------------------------------
# Parser principal de respuesta de modelo
# ---------------------------------------------------------------------------


def parse_review_response(
    raw_text: str,
    request: ReviewBatchRequest,
    provider: str,
    model: str,
    reviewer_role: str,
) -> ModelReviewResponse:
    """Parsea la respuesta cruda del modelo y devuelve un ModelReviewResponse.

    Parámetros
    ----------
    raw_text:
        Texto completo de la respuesta del modelo (puede contener prosa + JSON).
    request:
        Lote de revisión original; se usa para saber qué candidate_ids se esperan.
    provider:
        Identificador del proveedor (p. ej. "openai", "anthropic").
    model:
        Identificador del modelo (p. ej. "gpt-4o").
    reviewer_role:
        Rol del revisor ("reviewer_a", "reviewer_b" o "adjudicator").

    Devuelve
    --------
    ModelReviewResponse con decisions válidas y validation_errors acumulados.
    Una respuesta con cero decisions válidas tiene .valid == False.
    """
    validation_errors: list[str] = []
    decisions: list[ModelReviewDecision] = []

    # --- Extraer JSON ---
    try:
        parsed = extract_json(raw_text)
    except InvalidResponseError as exc:
        validation_errors.append(f"extract_json: {exc}")
        return ModelReviewResponse(
            provider=provider,
            model=model,
            reviewer_role=reviewer_role,
            decisions=[],
            prompt_version=_PROMPT_VERSION,
            validation_errors=validation_errors,
        )

    # --- Normalizar a lista de dicts de review ---
    review_list: list[dict]

    if isinstance(parsed, dict):
        if "reviews" in parsed:
            inner = parsed["reviews"]
            if isinstance(inner, list):
                review_list = inner
            else:
                # reviews es un objeto único en vez de lista
                review_list = [inner] if isinstance(inner, dict) else []
        else:
            # El modelo devolvió un único objeto review directamente
            review_list = [parsed]
    elif isinstance(parsed, list):
        review_list = parsed
    else:
        validation_errors.append(
            f"formato_inesperado: se esperaba dict o list, "
            f"se obtuvo {type(parsed).__name__}"
        )
        return ModelReviewResponse(
            provider=provider,
            model=model,
            reviewer_role=reviewer_role,
            decisions=[],
            prompt_version=_PROMPT_VERSION,
            validation_errors=validation_errors,
        )

    # --- Indexar ReviewItems por candidate_id ---
    items_by_id: dict[str, ReviewItem] = {
        item.candidate_id: item for item in request.items
    }

    # Llevar la cuenta de qué candidatos han sido respondidos
    answered_ids: set[str] = set()

    # --- Validar cada review de la respuesta ---
    for raw_review in review_list:
        if not isinstance(raw_review, dict):
            validation_errors.append(
                f"review_no_dict: elemento no es un objeto: {str(raw_review)[:80]!r}"
            )
            continue

        cid = str(raw_review.get("candidate_id", ""))

        # Buscar el item correspondiente
        item = items_by_id.get(cid)
        if item is None:
            validation_errors.append(
                f"{cid or '(sin_id)'}: candidate_id no pertenece al lote"
            )
            continue

        decision_obj, errors = validate_decision(raw_review, item)

        if errors:
            for err in errors:
                validation_errors.append(f"{cid}: {err}")
        else:
            decisions.append(decision_obj)
            answered_ids.add(cid)

    # --- Detectar candidatos no respondidos ---
    for item in request.items:
        if item.candidate_id not in answered_ids:
            validation_errors.append(
                f"{item.candidate_id}: missing_in_response"
            )

    return ModelReviewResponse(
        provider=provider,
        model=model,
        reviewer_role=reviewer_role,
        decisions=decisions,
        prompt_version=_PROMPT_VERSION,
        validation_errors=validation_errors,
    )
