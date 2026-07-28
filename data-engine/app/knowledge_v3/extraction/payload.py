# -*- coding: utf-8 -*-
"""Normalizacion de propuestas producidas por un MODELO (Ollama, externo, vision).

Este modulo es la frontera de confianza del subsistema. Todo lo que llega de un
modelo entra por aqui y sale convertido en documentos `v3-internal-v1` o no sale.

Reglas, en orden de importancia:

1. **El modelo no aporta offsets ni identificadores de fragmento.** Aporta
   CITAS. Los offsets los calcula el motor local buscando la cita en el texto
   real (`EvidenceIndex._locate`), y el `fragment_id` sale del fragmento que
   contiene esa cita. Si el modelo propone un `fragment_id`, se trata como una
   pista que hay que verificar, nunca como un dato.
2. **Una mencion cuya superficie no aparece literalmente en un fragmento real se
   descarta.** Es el filtro que evita el fallo clasico: nombres plausibles que
   el modelo genera solo porque encajan en el mundo.
3. **Un claim cuyos argumentos no son menciones ancladas se descarta o se
   convierte en abstencion.** Nunca se crea una mencion "de apoyo" para salvar
   un claim: eso seria fabricar la evidencia que faltaba.
4. **Todo claim afirmado necesita CITA, y la cita se comprueba en contexto.**
   Que exista no basta: una cita parcial puede invertir el sentido del texto
   ("Kael **no** sirve a la Orden" citado como "sirve a la Orden"). Antes de
   aceptar `negated=False` se analiza el texto real que rodea al ancla
   (`cues.analyze_context`); si el contexto niega, condiciona, pregunta o
   desmiente, el claim se ABSTIENE. Sin cita no hay claim afirmado: sin ella no
   hay nada que comprobar, y una propuesta que no se puede comprobar no es una
   propuesta, es una invencion con formato correcto.
5. **Un ancla ambigua (`AMBIGUOUS_ANCHOR`) tampoco vale para afirmar.** La misma
   cita en dos fragmentos puede estar afirmada en uno y negada en el otro.
6. **La confianza del modelo se limita** (`confidence_cap`) y sus claims nacen
   con `review_required=True`. Un LLM propone; no aprueba.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ..contracts import SourceEpisode
from .base import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_EPISTEMIC,
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    ExtractorInfo,
    abstention_claim,
    build_claim,
    build_mention,
    clamp,
    emit,
    is_number,
    low_quality,
)
from .cues import (
    CODE_NEGATION_MISMATCH,
    CODE_NON_FACTIVE,
    ContextVerdict,
    analyze_context,
)
from .text import EvidenceIndex, normalize

_PREDICATE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_NON_PREDICATE_CHARS = re.compile(r"[^A-Za-z0-9]+")

#: Tope de confianza de una propuesta de modelo. No es pesimismo gratuito: la
#: confianza declarada por un LLM no esta calibrada contra nada, y hasta que el
#: benchmark la mida no puede competir con una regla determinista verificada.
DEFAULT_CONFIDENCE_CAP = 0.7

#: Maximo de propuestas aceptadas por episodio. Un modelo que devuelve cien
#: menciones en un parrafo no esta extrayendo, esta generando.
MAX_MENTIONS_PER_EPISODE = 64
MAX_CLAIMS_PER_EPISODE = 32


class PayloadError(ValueError):
    """El payload del modelo no tiene la forma pactada."""


def normalize_predicate(raw: str) -> Optional[str]:
    """`raw` -> predicado canonico `^[A-Z][A-Z0-9_]{0,63}$`, o None.

    Misma normalizacion de forma que `relations.contracts.normalize_predicate`
    (MAYUSCULAS con guion bajo). No se importa de alli para no acoplar el
    subsistema V3 a la frontera intocable de V1/V2; el adaptador es quien cruza.
    """
    if not raw or not isinstance(raw, str):
        return None
    cleaned = _NON_PREDICATE_CHARS.sub("_", raw.strip()).strip("_").upper()
    if not cleaned or not _PREDICATE_RE.match(cleaned):
        return None
    return cleaned


def check_payload_shape(payload: Any) -> dict:
    """Comprueba la forma minima del payload. Lanza `PayloadError` si no cuadra."""
    if not isinstance(payload, dict):
        raise PayloadError(f"el payload no es un objeto JSON: {type(payload).__name__}")
    mentions = payload.get("mentions", [])
    claims = payload.get("claims", [])
    if not isinstance(mentions, list) or not isinstance(claims, list):
        raise PayloadError("'mentions' y 'claims' deben ser listas")
    if not all(isinstance(x, dict) for x in mentions):
        raise PayloadError("todas las menciones deben ser objetos")
    if not all(isinstance(x, dict) for x in claims):
        raise PayloadError("todos los claims deben ser objetos")
    return {"mentions": mentions, "claims": claims}


@dataclass
class _Grounded:
    """Mencion del modelo ya verificada contra la evidencia real."""

    mention_id: str
    normalized_surface: str
    fragment_id: str
    entity_type: Optional[str] = None


def _anchor_or_none(index: EvidenceIndex, quote: str, claimed: Optional[str]):
    if not quote:
        return None
    return index.anchor_quote(quote, claimed if isinstance(claimed, str) else None)


def verify_quote_context(index: EvidenceIndex, anchor, claimed_negated: bool) -> ContextVerdict:
    """Comprueba que el contexto real del ancla no contradiga lo que se afirma.

    Sin `negation_window`: al verificar la cita de un modelo se mira TODO el
    contexto previo dentro de la frase. Aqui la prudencia gana a la precision,
    porque el resultado de dudar es abstenerse, no equivocarse.
    """
    text, tokens, lo, hi, focus = index.context_window(anchor)
    verdict = analyze_context(text, tokens, lo=lo, hi=hi, focus=focus)
    if verdict.negated and not claimed_negated:
        return ContextVerdict(
            negated=True,
            hint=verdict.hint,
            cues=verdict.cues,
            reason_codes=(CODE_NEGATION_MISMATCH, *verdict.reason_codes),
        )
    return verdict


def normalize_payload(  # noqa: C901 - una comprobacion por regla anti-alucinacion
    payload: Any,
    *,
    ctx: ExtractionContext,
    episode: SourceEpisode,
    info: ExtractorInfo,
    confidence_cap: float = DEFAULT_CONFIDENCE_CAP,
    force_review: bool = True,
    epistemic_override: Optional[str] = None,
    emit_abstentions: bool = True,
) -> ExtractionOutput:
    """Convierte el payload de un modelo en propuestas validadas y ancladas."""
    out = ExtractionOutput()
    index = ctx.index_of(episode)
    try:
        shaped = check_payload_shape(payload)
    except PayloadError as exc:
        out.diagnostics.append(
            Diagnostic("MODEL_PAYLOAD_MALFORMED", info.step, episode.episode_id, str(exc))
        )
        return out

    profile_predicates = ctx.profile_predicates()
    grounded: dict[str, _Grounded] = {}

    # --- menciones -------------------------------------------------------
    for raw in shaped["mentions"][:MAX_MENTIONS_PER_EPISODE]:
        surface = str(raw.get("surface") or "").strip()
        if not surface:
            out.diagnostics.append(
                Diagnostic("MENTION_WITHOUT_SURFACE", info.step, episode.episode_id, "")
            )
            continue
        anchor = _anchor_or_none(index, surface, raw.get("fragment_id"))
        if anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_MENTION", info.step, episode.episode_id,
                    f"{surface!r} no aparece en ningun fragmento real del episodio",
                )
            )
            continue
        quote = str(raw.get("quote") or "").strip()
        if quote and _anchor_or_none(index, quote, raw.get("fragment_id")) is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_QUOTE", info.step, episode.episode_id,
                    f"la cita de {surface!r} no existe en el episodio",
                )
            )
            continue
        raw_confidence = raw.get("confidence", 0.5)
        if not is_number(raw_confidence):
            out.diagnostics.append(
                Diagnostic(
                    "INVALID_CONFIDENCE", info.step, episode.episode_id,
                    f"{surface!r}: {str(raw_confidence)[:32]!r} no es un numero",
                )
            )
        confidence = min(clamp(raw_confidence, default=0.0), confidence_cap)
        raw_type = raw.get("type")
        types = []
        if isinstance(raw_type, str) and raw_type in ALLOWED_ENTITY_TYPES:
            types.append({"type": raw_type, "confidence": confidence})
        elif raw_type not in (None, "", "null"):
            out.diagnostics.append(
                Diagnostic(
                    "UNKNOWN_ENTITY_TYPE", info.step, episode.episode_id, str(raw_type)[:64]
                )
            )
        mention = build_mention(
            info=info,
            episode=episode,
            surface=surface,
            start=anchor.start,
            end=anchor.end,
            evidence_fragment_ids=[anchor.fragment_id],
            type_candidates=types,
            confidence=confidence,
            basis=anchor.basis,
            metadata={
                "model_proposed": True,
                "anchor_reason_codes": list(anchor.reason_codes),
            },
        )
        if emit(mention, out, info, episode.episode_id):
            key = normalize(surface)
            previo = grounded.get(key)
            if previo is not None and previo.entity_type != mention.best_type():
                # La misma superficie tipada de dos formas distintas en el mismo
                # episodio: el modelo se contradice. Se conserva la primera (el
                # id es determinista) y se deja constancia; el motor local vera
                # el conflicto en vez de heredarlo en silencio.
                out.diagnostics.append(
                    Diagnostic(
                        "CONFLICTING_MENTION_TYPES", info.step, episode.episode_id,
                        f"{surface!r}: {previo.entity_type} vs {mention.best_type()}",
                    )
                )
            grounded.setdefault(
                key,
                _Grounded(mention.mention_id, key, anchor.fragment_id, mention.best_type()),
            )

    # --- claims ----------------------------------------------------------
    for raw in shaped["claims"][:MAX_CLAIMS_PER_EPISODE]:
        subject = normalize(str(raw.get("subject") or ""))
        obj = normalize(str(raw.get("object") or ""))
        quote = str(raw.get("quote") or "").strip()
        anchor = _anchor_or_none(index, quote, raw.get("fragment_id")) if quote else None
        if quote and anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "HALLUCINATED_QUOTE", info.step, episode.episode_id,
                    "la cita del claim no existe en ningun fragmento real",
                )
            )
            continue
        subj_hit = grounded.get(subject)
        obj_hit = grounded.get(obj)
        if subj_hit is None or obj_hit is None or subj_hit.mention_id == obj_hit.mention_id:
            missing = [
                code
                for code, hit in (("SUBJECT_NOT_GROUNDED", subj_hit), ("OBJECT_NOT_GROUNDED", obj_hit))
                if hit is None
            ] or ["SUBJECT_EQUALS_OBJECT"]
            out.diagnostics.append(
                Diagnostic(missing[0], info.step, episode.episode_id, f"{subject!r} / {obj!r}")
            )
            continue
        fragments = [
            f for f in (
                anchor.fragment_id if anchor else None,
                subj_hit.fragment_id,
                obj_hit.fragment_id,
            ) if f
        ]
        predicate = normalize_predicate(str(raw.get("predicate") or ""))
        reasons: list[str] = []
        if predicate is None:
            reasons.append("PREDICATE_NOT_NORMALIZABLE")
        elif profile_predicates and predicate not in profile_predicates:
            reasons.append("PREDICATE_NOT_IN_PROFILE")
        hint = epistemic_override or str(raw.get("epistemic") or "ASSERTED")
        if hint not in ALLOWED_EPISTEMIC:
            reasons.append("UNKNOWN_EPISTEMIC_STATUS")
            hint = "UNKNOWN"
        relation_phrase = str(raw.get("relation") or "")[:2000]
        negated = bool(raw.get("negated", False))

        # --- la cita es OBLIGATORIA para afirmar --------------------------
        # Sin cita no hay nada que verificar: el claim se apoyaria solo en dos
        # menciones que existen y en un predicado que el modelo se saco de
        # donde fuera. Dos menciones ancladas no sostienen la relacion entre
        # ellas.
        if anchor is None:
            reasons.append("CLAIM_WITHOUT_QUOTE")
        else:
            if anchor.ambiguous:
                reasons.append("AMBIGUOUS_ANCHOR")
            verdict = verify_quote_context(index, anchor, negated)
            if CODE_NEGATION_MISMATCH in verdict.reason_codes:
                reasons.append(CODE_NEGATION_MISMATCH)
            if verdict.non_factive:
                reasons.append(CODE_NON_FACTIVE)
                reasons.extend(
                    c for c in verdict.reason_codes if c != CODE_NEGATION_MISMATCH
                )
            elif verdict.hint != "ASSERTED" and hint == "ASSERTED":
                # El contexto real dice rumor/hipotesis/intencion aunque el
                # modelo dijera ASSERTED: manda el texto, no el modelo.
                hint = verdict.hint
        if reasons:
            if not emit_abstentions:
                out.diagnostics.append(
                    Diagnostic(reasons[0], info.step, episode.episode_id, relation_phrase[:120])
                )
                continue
            claim = abstention_claim(
                info=info,
                episode=episode,
                evidence_fragment_ids=fragments or [subj_hit.fragment_id],
                reason_codes=reasons,
                relation_phrase=relation_phrase,
                subject_mentions=[subj_hit.mention_id],
                object_mentions=[obj_hit.mention_id],
                metadata={"model_proposed": True, "raw_predicate": str(raw.get("predicate"))[:64]},
            )
            emit(claim, out, info, episode.episode_id)
            continue
        confidence = min(clamp(raw.get("confidence", 0.5)), confidence_cap)
        claim = build_claim(
            info=info,
            episode=episode,
            evidence_fragment_ids=fragments,
            subject_mentions=[subj_hit.mention_id],
            object_mentions=[obj_hit.mention_id],
            relation_phrase=relation_phrase,
            predicate_candidates=[{"predicate": predicate, "confidence": confidence}],
            direction_candidates=[{"direction": "SUBJECT_TO_OBJECT", "confidence": confidence}],
            negated=negated,
            epistemic_cues=[str(c)[:256] for c in (raw.get("cues") or []) if str(c).strip()],
            epistemic_status_hint=hint,
            confidence=confidence,
            abstained=False,
            review_required=bool(force_review or low_quality(episode)),
            metadata={
                "model_proposed": True,
                "anchor_reason_codes": list(anchor.reason_codes) if anchor else [],
            },
        )
        emit(claim, out, info, episode.episode_id)

    return out


__all__ = [
    "DEFAULT_CONFIDENCE_CAP",
    "MAX_CLAIMS_PER_EPISODE",
    "MAX_MENTIONS_PER_EPISODE",
    "PayloadError",
    "check_payload_shape",
    "normalize_payload",
    "normalize_predicate",
]
