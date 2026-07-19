# -*- coding: utf-8 -*-
"""Evaluador de RELACIONES con IA externa (NVIDIA NIM / OpenAI-compatible).

MODO SOMBRA ESTRICTO (Fase A):
  * Ninguna evaluacion es una decision productiva: solo produce una
    ``shadow_recommendation`` que SIEMPRE requiere revision humana.
  * NUNCA existe el estado AUTO_APPROVED.
  * NUNCA escribe en Neo4j ni activa ingesta.
  * En tests NUNCA hay red: el transporte HTTP se inyecta/mockea.

REUTILIZACION (NO se duplica nada de ``external_ai/**``):
  * Cliente/transporte HTTP, reintentos con backoff, timeout, rate-limit y
    control de concurrencia: ``external_ai.openai_compatible`` via el proveedor
    ``external_ai.nvidia_nim.NvidiaNimProvider`` (metodo ``_post_chat``).
  * Configuracion, endpoint explicito y API key por secreto:
    ``external_ai.registry`` (la key nunca se guarda como atributo ni se serializa).
  * Redaccion/guarda de secretos: ``external_ai.security.assert_no_secrets``.
  * Extraccion robusta de JSON de la respuesta cruda: ``external_ai.response_parser``.
  * Estados de consenso y guarda de modo sombra: ``external_ai.models`` /
    ``external_ai.require_shadow``.
  * Contrato de la relacion y su validacion: ``relations.contracts`` /
    ``relations.prompts`` (system prompt, delimitadores, sanitizacion).

Este modulo es un ENVOLTORIO fino: adapta la entrada (una relacion candidata)
y la salida (verdicto por candidato) al cliente ya existente, sin reescribir
clientes, modelos, estados, consenso, validadores, redaccion ni errores.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# --- Reutilizacion de external_ai (fuente canonica; NO se duplica) ----------
from external_ai import require_shadow
from external_ai.errors import (
    ExternalAIError,
    InvalidResponseError,
    ProviderAuthError,
    ProviderNotFoundError,
    ProviderServerError,
    ProviderTimeoutError,
    RateLimitError,
    SecretLeakError,
)
from external_ai.models import (
    CONSENSUS_STATES,
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)
from external_ai.security import assert_no_secrets

# --- Reutilizacion de relations (contrato + prompts) ------------------------
from relations.contracts import (
    ALLOWED_ENTITY_TYPES,
    RelationCandidate,
    RelationContractError,
    normalize_predicate,
)
from relations.prompts import (
    DEFAULT_SUITE,
    INPUT_CLOSE,
    INPUT_OPEN,
    PROMPT_SUITE_VERSION,
    build_system_prompt,
    sanitize_document,
)
from relations.contracts import SCHEMA_VERSION as RELATION_SCHEMA_VERSION

logger = logging.getLogger("relations.external_ai_shadow")

# Verdictos que el modelo externo puede emitir sobre una relacion propuesta.
VALID_VERDICTS = ("confirm", "refine", "reject", "uncertain")

# Recomendaciones sombra permitidas. AUTO_APPROVED esta PROHIBIDO por diseno.
SHADOW_RECOMMENDATIONS = ("confirm", "refine", "reject", "human")
_FORBIDDEN_RECOMMENDATION = "AUTO_APPROVED"

# Errores de proveedor que NO se reintentan (el cliente ya decide reintentos;
# aqui solo los clasificamos por candidato de forma aislada).
_PROVIDER_ERRORS = (
    RateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderAuthError,
    ProviderNotFoundError,
    InvalidResponseError,
    SecretLeakError,
    ExternalAIError,
)


class RelationVolumeError(ValueError):
    """Se supero el limite de volumen (numero maximo de candidatos por lote)."""


# ---------------------------------------------------------------------------
# Configuracion (endpoint explicito; API key SOLO por secreto de entorno)
# ---------------------------------------------------------------------------
@dataclass
class RelationExternalConfig:
    """Configuracion del evaluador externo de relaciones (modo sombra).

    La API key NUNCA se almacena aqui: el proveedor la obtiene por demanda del
    entorno (``external_ai.registry.get_api_key``). ``endpoint`` es informativo;
    el base_url real lo resuelve el registry a partir del entorno explicito.
    """

    model: str
    provider_name: str = "nvidia"
    suite: str = DEFAULT_SUITE
    max_candidates: int = 25          # control de volumen
    shadow_mode: bool = True          # obligatorio True en Fase A
    repo_root: Optional[Path] = None
    # Proveedor ya construido (reutiliza external_ai). En tests se inyecta un
    # mock con `_post_chat`; en produccion se construye via registry.
    provider: Optional[Any] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["repo_root"] = str(self.repo_root) if self.repo_root else None
        # El proveedor no se serializa (podria arrastrar referencias); solo su tipo.
        d["provider"] = type(self.provider).__name__ if self.provider is not None else None
        return d


# ---------------------------------------------------------------------------
# Resultado por candidato (trazabilidad de modelo/version; sin secretos)
# ---------------------------------------------------------------------------
@dataclass
class RelationExternalEvaluation:
    """Evaluacion externa (sombra) de UNA relacion candidata.

    ``state`` es uno de ``external_ai.models.CONSENSUS_STATES`` (reutilizado, no
    duplicado). ``shadow_recommendation`` nunca es AUTO_APPROVED: siempre exige
    intervencion humana antes de cualquier escritura.
    """

    candidate_id: str
    state: str                       # uno de CONSENSUS_STATES
    shadow_recommendation: str       # confirm|refine|reject|human
    provider: str
    model: str
    prompt_suite_version: str = PROMPT_SUITE_VERSION
    schema_version: str = RELATION_SCHEMA_VERSION
    verdict: Optional[dict] = None   # verdicto del modelo, ya validado y saneado
    reason: str = ""
    reason_codes: list = field(default_factory=list)
    validation_errors: list = field(default_factory=list)
    latency_ms: int = 0
    request_hash: str = ""
    response_hash: str = ""
    shadow_mode: bool = True

    def __post_init__(self) -> None:
        # Invariante de seguridad: jamas AUTO_APPROVED, jamas fuera del catalogo.
        if self.shadow_recommendation == _FORBIDDEN_RECOMMENDATION:
            raise AssertionError("AUTO_APPROVED esta prohibido en modo sombra")
        if self.state not in CONSENSUS_STATES:
            raise AssertionError(f"estado no canonico: {self.state!r}")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------
def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate_id(cand: RelationCandidate) -> str:
    """ID estable de un candidato de relacion (subject|predicate|object)."""
    return f"{cand.subject_id}|{cand.predicate}|{cand.object_id}"


def _coerce_candidate(obj: Any) -> RelationCandidate:
    """Normaliza la entrada a RelationCandidate (acepta instancia o dict)."""
    if isinstance(obj, RelationCandidate):
        return obj
    if isinstance(obj, dict):
        # from_dict valida el contrato interno-v1 (rechaza campos desconocidos).
        return RelationCandidate.from_dict(obj, validate=True)
    raise RelationContractError(
        f"candidato no soportado: se esperaba RelationCandidate o dict, "
        f"recibido {type(obj).__name__}"
    )


def _iter_candidates(candidate_or_pair: Any) -> list[RelationCandidate]:
    if isinstance(candidate_or_pair, (list, tuple)):
        return [_coerce_candidate(c) for c in candidate_or_pair]
    return [_coerce_candidate(candidate_or_pair)]


def _extract_verdicts(raw_text: str) -> list[dict]:
    """Extrae la lista de verdictos del texto crudo del modelo.

    Reutiliza ``external_ai.response_parser.extract_json`` para el parseo robusto
    (bloques markdown, JSON balanceado, etc.) y adapta la forma a relaciones.
    """
    from external_ai import response_parser  # import perezoso (reutilizacion)

    parsed = response_parser.extract_json(raw_text)  # dict o {"reviews": [...]}
    if isinstance(parsed, dict):
        for key in ("verdicts", "relations", "reviews"):
            if key in parsed and isinstance(parsed[key], list):
                return [v for v in parsed[key] if isinstance(v, dict)]
        # Objeto unico devuelto directamente.
        return [parsed]
    if isinstance(parsed, list):
        return [v for v in parsed if isinstance(v, dict)]
    raise InvalidResponseError("formato de respuesta inesperado (ni dict ni list)")


def _build_messages(cand: RelationCandidate, cid: str, suite: str) -> list[dict]:
    """Construye los mensajes chat reutilizando el prompt de sistema de relaciones."""
    system = build_system_prompt(suite)
    proposed = {
        "candidate_id": cid,
        "subject_id": cand.subject_id,
        "subject_type": cand.subject_type,
        "predicate": cand.predicate,
        "object_id": cand.object_id,
        "object_type": cand.object_type,
        "direction": cand.direction.value if hasattr(cand.direction, "value") else cand.direction,
        "negated": cand.negated,
    }
    verdicts_txt = " | ".join(VALID_VERDICTS)
    types_txt = " | ".join(ALLOWED_ENTITY_TYPES)
    schema_txt = (
        '{"candidate_id": <string>, '
        f'"verdict": <uno de: {verdicts_txt}>, '
        '"predicate": <MAYUSCULAS_CON_GUION_BAJO>, '
        f'"subject_type": <{types_txt} o null>, '
        f'"object_type": <{types_txt} o null>, '
        '"negated": <bool>, '
        '"evidence_text": <cita LITERAL copiada del DOCUMENTO, NUNCA inventada>, '
        '"evidence_start": <offset int >=0>, "evidence_end": <offset int >= start>, '
        '"confidence": <0.0..1.0>, "reason_codes": <lista de strings>, '
        '"explanation": <string breve>}'
    )
    user = (
        "Evalua la RELACION PROPUESTA contra el DOCUMENTO delimitado. No la "
        "extraigas de nuevo: juzga si el documento la sustenta.\n\n"
        "Relacion propuesta (JSON):\n" + json.dumps(proposed, ensure_ascii=False) + "\n\n"
        f"DOCUMENTO {INPUT_OPEN}\n{sanitize_document(cand.source_segment)}\n{INPUT_CLOSE}\n\n"
        'Devuelve UNICAMENTE JSON con la forma {"verdicts": [<objeto>]} y UN objeto '
        f'para candidate_id="{cid}" con EXACTAMENTE estas claves:\n' + schema_txt
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Validacion estricta del verdicto por candidato
# ---------------------------------------------------------------------------
def _validate_verdict(raw: dict, cand: RelationCandidate, cid: str) -> tuple[Optional[dict], list[str]]:
    """Valida un verdicto crudo. Devuelve (verdicto_saneado, errores).

    Rechaza (errores hard, devuelven None):
      * candidate_id ausente o que no coincide.
      * verdict fuera de VALID_VERDICTS.
      * confidence no numerica.
      * subject_type/object_type no nulos y fuera de ALLOWED_ENTITY_TYPES (tipo incompatible).
      * evidence vacia, inexistente en el segmento (evidencia inexistente).
      * offsets no enteros, fuera de rango, o que no casan con la cita (offsets invalidos).
      * negated no booleano.
    """
    errors: list[str] = []

    got_cid = raw.get("candidate_id")
    if got_cid is None:
        return None, ["candidate_id ausente en el verdicto"]
    if str(got_cid) != str(cid):
        return None, [f"candidate_id no coincide: esperado {cid!r}, recibido {str(got_cid)!r}"]

    verdict = raw.get("verdict")
    if verdict not in VALID_VERDICTS:
        errors.append(f"verdict invalido {verdict!r}; debe ser uno de {VALID_VERDICTS}")

    # confidence
    conf = raw.get("confidence", 0.0)
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        errors.append(f"confidence no numerica: {conf!r}")
        conf = 0.0
    else:
        conf = float(max(0.0, min(1.0, conf)))

    # negated explicito
    negated = raw.get("negated", False)
    if not isinstance(negated, bool):
        errors.append("negated debe ser bool explicito")

    # tipos ontologicos (tipo incompatible)
    for label in ("subject_type", "object_type"):
        val = raw.get(label)
        if val is not None and val not in ALLOWED_ENTITY_TYPES:
            errors.append(f"{label} tipo incompatible: {val!r} no en {ALLOWED_ENTITY_TYPES}")

    # predicate normalizado (si viene)
    pred = raw.get("predicate")
    if pred is not None:
        if not isinstance(pred, str) or not pred.strip():
            errors.append("predicate vacio o no string")
        elif pred != normalize_predicate(pred):
            errors.append(f"predicate no normalizado: {pred!r}")

    # evidencia + offsets ESTRICTOS contra el segmento del candidato
    seg = cand.source_segment or ""
    ev = raw.get("evidence_text")
    start = raw.get("evidence_start")
    end = raw.get("evidence_end")

    if not isinstance(ev, str) or not ev.strip():
        errors.append("evidence_text vacia o ausente")
    elif ev not in seg:
        errors.append("evidencia_inexistente: evidence_text no es subcadena literal del segmento")

    off_ok = True
    for label, off in (("evidence_start", start), ("evidence_end", end)):
        if not isinstance(off, int) or isinstance(off, bool):
            errors.append(f"{label} debe ser int")
            off_ok = False
    if off_ok:
        if start < 0 or end < 0 or start > end or end > len(seg):
            errors.append(f"offsets_invalidos: fuera de rango [0,{len(seg)}] o start>end")
        elif isinstance(ev, str) and seg[start:end] != ev:
            errors.append("offsets_invalidos: segmento[start:end] no coincide con evidence_text")

    if errors:
        return None, errors

    # Verdicto saneado (solo claves conocidas; sin secretos ni campos extra).
    clean = {
        "candidate_id": str(cid),
        "verdict": str(verdict),
        "predicate": pred,
        "subject_type": raw.get("subject_type"),
        "object_type": raw.get("object_type"),
        "negated": bool(negated),
        "evidence_text": ev,
        "evidence_start": int(start),
        "evidence_end": int(end),
        "confidence": conf,
        "reason_codes": list(raw.get("reason_codes", [])) if isinstance(raw.get("reason_codes"), list) else [],
        "explanation": str(raw.get("explanation", "")),
    }
    return clean, []


def _classify(cand: RelationCandidate, verdict: dict) -> tuple[str, str, str]:
    """Mapea un verdicto valido a (state, shadow_recommendation, reason).

    Estados reutilizados de external_ai.models. Nunca AUTO_APPROVED; en modo
    sombra incluso el acuerdo fuerte exige revision humana antes de escribir.
    """
    v = verdict["verdict"]
    if v == "uncertain":
        return HUMAN_REQUIRED, "human", "El modelo externo reporta incertidumbre."

    if v == "reject":
        return (
            MODEL_CONFLICT,
            "reject",
            "El modelo externo rechaza la relacion propuesta por el pipeline interno.",
        )

    # confirm | refine: comprobamos coherencia con la propuesta interna.
    negation_flip = bool(verdict["negated"]) != bool(cand.negated)
    if negation_flip:
        return (
            MODEL_CONFLICT,
            "human",
            "Conflicto de negacion: el modelo invierte la polaridad de la relacion.",
        )

    model_pred = verdict.get("predicate")
    same_predicate = model_pred is None or model_pred == cand.predicate
    types_match = (
        (verdict.get("subject_type") in (None, cand.subject_type))
        and (verdict.get("object_type") in (None, cand.object_type))
    )

    if v == "confirm" and same_predicate and types_match:
        return (
            STRONG_CONSENSUS,
            "confirm",
            "El modelo confirma la relacion con evidencia literal valida (requiere revision humana).",
        )

    # confirm con matices, o refine explicito -> consenso parcial.
    return (
        PARTIAL_CONSENSUS,
        "refine",
        "El modelo apoya la relacion pero sugiere ajustes (predicado/tipos).",
    )


def _get_provider(config: RelationExternalConfig):
    """Devuelve el proveedor a usar: el inyectado o uno del registry (reutilizado)."""
    if config.provider is not None:
        return config.provider
    from external_ai import registry  # import perezoso (reutilizacion)

    repo_root = config.repo_root or Path.cwd()
    return registry.get_provider(config.provider_name, repo_root=repo_root)


def _provider_name(provider, fallback: str) -> str:
    return getattr(provider, "provider_name", None) or fallback


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def evaluate_relation_external(
    candidate_or_pair: Any,
    *,
    config: RelationExternalConfig,
) -> list[RelationExternalEvaluation]:
    """Evalua una o varias relaciones candidatas con IA externa, EN SOMBRA.

    Parametros
    ----------
    candidate_or_pair:
        Un ``RelationCandidate`` (o dict del contrato interno-v1), o una lista
        de ellos.
    config:
        ``RelationExternalConfig``. En tests se inyecta ``config.provider`` con
        un ``_post_chat`` mockeado; NUNCA hay red.

    Devuelve
    --------
    Lista de ``RelationExternalEvaluation`` (una por candidato). El fallo de un
    candidato queda AISLADO: no aborta al resto (se registra como
    INVALID_RESPONSES con la causa, sin exponer secretos).

    Garantias de seguridad
    ----------------------
    * ``require_shadow`` aborta si ``shadow_mode`` no es True.
    * Nunca escribe en Neo4j; nunca activa ingesta.
    * ``assert_no_secrets`` bloquea el envio si el payload contiene credenciales.
    * La API key nunca se registra ni se serializa.
    * ``shadow_recommendation`` nunca es AUTO_APPROVED.
    """
    require_shadow(config.shadow_mode)

    if not config.model or not str(config.model).strip():
        raise ValueError("config.model es obligatorio (id del modelo externo)")

    candidates = _iter_candidates(candidate_or_pair)

    # Control de volumen: nada se descarta en silencio.
    if len(candidates) > config.max_candidates:
        raise RelationVolumeError(
            f"volumen excedido: {len(candidates)} candidatos > max_candidates={config.max_candidates}"
        )

    provider = _get_provider(config)
    prov_name = _provider_name(provider, config.provider_name)
    results: list[RelationExternalEvaluation] = []

    for cand in candidates:
        cid = _candidate_id(cand)
        # Fallo AISLADO por candidato: cualquier excepcion se convierte en un
        # resultado INVALID_RESPONSES, nunca propaga y aborta el lote.
        try:
            messages = _build_messages(cand, cid, config.suite)

            # Guarda de secretos ANTES de cualquier envio (redaccion de external_ai).
            assert_no_secrets(messages)

            response_json, latency_ms = provider._post_chat(config.model, messages)

            try:
                raw_text = response_json["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise InvalidResponseError(
                    f"estructura inesperada en la respuesta: {type(exc).__name__}"
                ) from exc

            verdict_list = _extract_verdicts(raw_text)
            verdict_raw = _pick_verdict(verdict_list, cid)

            clean_verdict, errors = _validate_verdict(verdict_raw, cand, cid)
            request_hash = _sha256_text(json.dumps(messages, ensure_ascii=False, sort_keys=True))
            response_hash = _sha256_text(raw_text)

            if errors:
                results.append(RelationExternalEvaluation(
                    candidate_id=cid,
                    state=INVALID_RESPONSES,
                    shadow_recommendation="human",
                    provider=prov_name,
                    model=config.model,
                    reason="Respuesta invalida o incompleta del modelo.",
                    reason_codes=["invalid_response"],
                    validation_errors=errors,
                    latency_ms=latency_ms,
                    request_hash=request_hash,
                    response_hash=response_hash,
                ))
                continue

            state, recommendation, reason = _classify(cand, clean_verdict)
            results.append(RelationExternalEvaluation(
                candidate_id=cid,
                state=state,
                shadow_recommendation=recommendation,
                provider=prov_name,
                model=config.model,
                verdict=clean_verdict,
                reason=reason,
                reason_codes=list(clean_verdict.get("reason_codes", [])),
                latency_ms=latency_ms,
                request_hash=request_hash,
                response_hash=response_hash,
            ))

        except _PROVIDER_ERRORS as exc:
            # Errores de proveedor/red/seguridad: aislados, sin exponer la key.
            logger.warning(
                "fallo de proveedor en candidato %s: %s", cid, type(exc).__name__
            )
            results.append(RelationExternalEvaluation(
                candidate_id=cid,
                state=INVALID_RESPONSES,
                shadow_recommendation="human",
                provider=prov_name,
                model=config.model,
                reason=f"Error de proveedor: {type(exc).__name__}",
                reason_codes=["provider_error"],
                validation_errors=[type(exc).__name__],
            ))
        except RelationContractError as exc:
            logger.warning("candidato invalido %s: %s", cid, type(exc).__name__)
            results.append(RelationExternalEvaluation(
                candidate_id=cid,
                state=INVALID_RESPONSES,
                shadow_recommendation="human",
                provider=prov_name,
                model=config.model,
                reason=f"Candidato invalido: {type(exc).__name__}",
                reason_codes=["invalid_candidate"],
                validation_errors=[str(exc)[:200]],
            ))

    return results


def _pick_verdict(verdict_list: list[dict], cid: str) -> dict:
    """Elige el verdicto cuyo candidate_id coincide; si no, el primero."""
    if not verdict_list:
        raise InvalidResponseError("la respuesta no contiene ningun verdicto")
    for v in verdict_list:
        if str(v.get("candidate_id", "")) == str(cid):
            return v
    return verdict_list[0]


def summarize(results: Iterable[RelationExternalEvaluation]) -> dict:
    """Estadisticas agregadas (modo sombra). No escribe nada."""
    results = list(results)
    total = len(results)
    counts: dict[str, int] = {s: 0 for s in CONSENSUS_STATES}
    for r in results:
        counts[r.state] = counts.get(r.state, 0) + 1
    return {
        "total": total,
        "by_state": counts,
        "shadow_mode": True,
        "auto_approved": 0,  # invariante: nunca hay auto-aprobacion
    }


__all__ = [
    "RelationExternalConfig",
    "RelationExternalEvaluation",
    "RelationVolumeError",
    "VALID_VERDICTS",
    "SHADOW_RECOMMENDATIONS",
    "evaluate_relation_external",
    "summarize",
]
