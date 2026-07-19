# -*- coding: utf-8 -*-
"""Adaptador de CONSENSO para relaciones (`relation-consensus/v1`).

Este modulo COMBINA las distintas fuentes del pipeline de relaciones sobre UN
candidato y emite un estado de consenso. NO crea un segundo sistema de estados:
REUTILIZA la taxonomia canonica de `external_ai.models.CONSENSUS_STATES`
(STRONG_CONSENSUS / PARTIAL_CONSENSUS / MODEL_CONFLICT / INVALID_RESPONSES /
HUMAN_REQUIRED).

Por que un adaptador y no `external_ai.consensus.compute_consensus` directamente
------------------------------------------------------------------------------
`external_ai.consensus.compute_consensus` es el motor canonico de consenso, pero
esta especializado en un caso distinto:

  * Combina EXACTAMENTE DOS revisores homogeneos (`ModelReviewResponse`) que
    deciden sobre ENTIDADES con un vocabulario fijo de decision
    (accept/edit/use_existing/reject/uncertain) y comparan canonical_name.
  * Trata la AUSENCIA de una decision como INVALID_RESPONSES (la decision falta).
  * No conoce el concepto de `workspace`, ni de negacion / temporalidad / estado
    epistemico, ni distingue "proveedor ausente" de "voto negativo".

El consenso de relaciones necesita:

  * Combinar fuentes HETEROGENEAS y de distinto peso: senales heuristicas (R2,
    evidencia, NO decision), sintaxis opcional (R3, estructura), recomendacion de
    LLM local (R5) y recomendacion externa (R6), mas el propio contrato de la
    relacion (evidencia, tipos, negacion, temporalidad, estado epistemico).
  * Diferenciar "proveedor AUSENTE" (abstencion) de "voto NEGATIVO" (reject).
  * INVALIDAR la mezcla de workspaces.
  * Preservar negacion / temporalidad / estado epistemico del candidato.

Ese conjunto de necesidades NO es representable con la firma de dos revisores
homogeneos de `compute_consensus` sin deformar sus contratos. Por eso este modulo
es una CAPA ESPECIFICA (adaptador) que DELEGA los ESTADOS comunes en
`external_ai.models` y NO define estados paralelos equivalentes.

Garantias (verificadas por los tests):

  * El candidato original es INMUTABLE: este modulo NUNCA lo modifica.
  * DETERMINISTA: misma entrada -> misma salida.
  * INDEPENDIENTE DEL ORDEN de las senales de entrada.
  * "Proveedor ausente" != "voto negativo".
  * SIN autoaprobacion: la recomendacion jamas aprueba/escribe/aplica.
  * CERO red, CERO Neo4j, CERO escritura, CERO LLM.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Sequence

# --- Reutilizacion de la taxonomia canonica de consenso (NO se duplica) ------
from external_ai.models import (
    CONSENSUS_STATES,
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)

# --- Contrato de la relacion (solo lectura/validacion sobre una COPIA) -------
from relations.contracts import (
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
    RelationContractError,
)

MODULE_VERSION = "relation-consensus-1.0.0"

# Recomendaciones permitidas del adaptador. NINGUNA aprueba, escribe ni aplica.
RECO_PROPOSE = "propose"   # sugerir la relacion (positiva) a humano/ensemble
RECO_REJECT = "reject"     # sugerir descartar (negativa)
RECO_HUMAN = "human"       # requiere revision humana
RELATION_RECOMMENDATIONS = (RECO_PROPOSE, RECO_REJECT, RECO_HUMAN)

# Barrera anti-aprobacion: valores que jamas pueden emitirse como recomendacion.
_FORBIDDEN_RECOMMENDATIONS = frozenset({
    "approve", "approved", "auto_approve", "auto_approved", "accept",
    "write", "apply", "commit", "merge",
})

# Polaridades internas de una recomendacion de proveedor.
_POS = "positive"
_NEG = "negative"
_ABSTAIN = "abstain"   # el proveedor pide revision humana / uncertain (NO ausente)

# Mapa de recomendacion del LLM local (R5) -> polaridad.
_LOCAL_POLARITY = {
    "recommend_propose": _POS,
    "recommend_reject": _NEG,
    "recommend_human_review": _ABSTAIN,
}
# Mapa de recomendacion externa (R6) -> polaridad.
_EXTERNAL_POLARITY = {
    "confirm": _POS,
    "refine": _POS,
    "reject": _NEG,
    "human": _ABSTAIN,
    "uncertain": _ABSTAIN,
}


# ---------------------------------------------------------------------------
# Resultado del adaptador (serializable y determinista)
# ---------------------------------------------------------------------------
@dataclass
class RelationConsensus:
    """Resultado del consenso para UN candidato de relacion.

    `state` es uno de `external_ai.models.CONSENSUS_STATES` (REUTILIZADO, no
    duplicado). `recommendation` pertenece a `RELATION_RECOMMENDATIONS` y NUNCA
    es una aprobacion/escritura.
    """

    state: str
    recommendation: str
    subject_id: str
    predicate: str
    object_id: str
    workspace: str
    # Se PRESERVAN del candidato (nunca se pierden en la combinacion):
    negated: bool
    epistemic_status: str
    temporal_scope: Optional[Any]
    # Trazabilidad (ordenada -> independiente del orden de entrada):
    sources_present: list = field(default_factory=list)
    signals_considered: list = field(default_factory=list)
    reason_codes: list = field(default_factory=list)
    reason: str = ""
    consensus_states_source: str = "external_ai.models.CONSENSUS_STATES"
    version: str = MODULE_VERSION
    shadow: bool = True

    def __post_init__(self) -> None:
        # Barreras duras (defensa en profundidad).
        if self.state not in CONSENSUS_STATES:
            raise ValueError(f"state {self.state!r} no pertenece a CONSENSUS_STATES")
        if self.recommendation not in RELATION_RECOMMENDATIONS:
            raise ValueError(
                f"recommendation {self.recommendation!r} no es valida "
                f"(permitidas: {RELATION_RECOMMENDATIONS})"
            )
        if self.recommendation.lower() in _FORBIDDEN_RECOMMENDATIONS:
            raise ValueError("recomendacion prohibida (aprobacion/escritura no permitida)")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Lectura tolerante de objetos o dicts (sin mutar nada)
# ---------------------------------------------------------------------------
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _signal_map(signals: Optional[Sequence[Any]]) -> dict:
    """Mapa {name: value} INDEPENDIENTE DEL ORDEN de la lista de senales.

    Si un mismo nombre aparece con valores distintos, se elige de forma
    determinista (menor repr) para no depender del orden de aparicion.
    """
    grouped: dict[str, list] = {}
    for s in signals or ():
        name = _get(s, "name")
        if name is None:
            continue
        grouped.setdefault(name, []).append(_get(s, "value"))
    out: dict[str, Any] = {}
    for name, values in grouped.items():
        out[name] = values[0] if len(values) == 1 else sorted(values, key=repr)[0]
    return out


def _as_validated_copy(candidate: Any) -> RelationCandidate:
    """Devuelve una COPIA validada del candidato SIN tocar el original.

    Reconstruye desde su dict; la validacion del contrato (evidencia, tipos,
    offsets, workspace, negated...) se aplica sobre la copia. El objeto original
    nunca se muta.
    """
    if isinstance(candidate, RelationCandidate):
        data = candidate.to_dict()
    elif isinstance(candidate, dict):
        data = dict(candidate)
    else:
        raise RelationContractError("candidate debe ser RelationCandidate o dict")
    return RelationCandidate.from_dict(data, validate=True)


def _original_fingerprint(candidate: Any) -> Optional[str]:
    if isinstance(candidate, RelationCandidate):
        return candidate.to_json()
    if isinstance(candidate, dict):
        import json
        return json.dumps(candidate, sort_keys=True, ensure_ascii=False)
    return None


def _source_valid(src: Any, is_local: bool) -> bool:
    """True si un proveedor PRESENTE es estructuralmente valido.

    Un proveedor ausente (None) NO llega aqui: ausente != invalido.
    """
    if _get(src, "state") == INVALID_RESPONSES:
        return False
    if _get(src, "validation_errors"):
        return False
    if is_local and _get(src, "validation_status", "VALID") == "INVALID":
        return False
    return True


def _has_evidence(cand: RelationCandidate) -> bool:
    """Evidencia REAL: texto no vacio Y un span de longitud positiva.

    El contrato admite `evidence_start == evidence_end` (span de longitud cero),
    pero eso no es evidencia utilizable: aunque el campo de texto tenga contenido,
    un span vacio no ancla nada. Aqui se penaliza (mas estricto que el contrato).
    """
    if cand.extraction_method == ExtractionMethod.ONTOLOGY:
        return True
    txt = cand.evidence_text
    if not (isinstance(txt, str) and txt.strip()):
        return False
    return cand.evidence_end > cand.evidence_start


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------
def compute_relation_consensus(
    candidate: Any,
    *,
    signals: Optional[Sequence[Any]] = None,
    syntax: Optional[Any] = None,
    local: Optional[Any] = None,
    external: Optional[Any] = None,
) -> RelationConsensus:
    """Combina las fuentes de un candidato de relacion y emite el consenso.

    Parametros
    ----------
    candidate:
        `RelationCandidate` (o su dict). INMUTABLE: nunca se modifica.
    signals:
        Secuencia de senales heuristicas (R2). Evidencia, NO decisiones. El
        resultado es INDEPENDIENTE DEL ORDEN de esta lista.
    syntax:
        Analisis sintactico opcional (R3). Estructura, NO decision.
    local:
        Recomendacion del LLM local (R5), opcional. Ausente != rechazo.
    external:
        Recomendacion externa (R6), opcional. Ausente != rechazo.

    Retorna
    -------
    RelationConsensus con un `state` de `CONSENSUS_STATES` (reutilizado) y una
    `recommendation` que NUNCA aprueba/escribe.
    """
    fingerprint = _original_fingerprint(candidate)

    # -- Validacion de contrato sobre una COPIA (penaliza evidencia inexistente,
    #    tipos malformados, workspace vacio, etc.) -----------------------------
    try:
        cand = _as_validated_copy(candidate)
    except RelationContractError as exc:
        return _finish(candidate, fingerprint, _invalid_stub(candidate),
                       INVALID_RESPONSES, RECO_HUMAN,
                       reason_codes=["candidate_contract_invalid"],
                       reason=f"Candidato invalido: {exc}",
                       signals=signals, local=local, external=external)

    ref_ws = cand.workspace

    # -- Fuentes presentes (ausente != negativo) --------------------------------
    local_present = local is not None
    external_present = external is not None
    sources_present = sorted(
        ([f"local_llm:{_get(local, 'provider', 'unknown')}"] if local_present else [])
        + ([f"external_ai:{_get(external, 'provider', 'unknown')}"] if external_present else [])
        + (["syntax"] if syntax is not None else [])
        + (["heuristics"] if signals else [])
    )
    sig = _signal_map(signals)
    signals_considered = sorted(sig.keys())

    reason_codes: list[str] = []

    # -- (1) Mezcla de workspaces -> INVALIDA -----------------------------------
    ws_values = {ref_ws}
    local_ws = _get(_get(local, "candidate"), "workspace") if local_present else None
    if local_ws is not None:
        ws_values.add(local_ws)
    ext_ws = _get(external, "workspace") if external_present else None
    if ext_ws is not None:
        ws_values.add(ext_ws)
    if len(ws_values) > 1:
        return _build(cand, INVALID_RESPONSES, RECO_HUMAN,
                      sources_present, signals_considered,
                      reason_codes=["workspace_mismatch"],
                      reason=f"Mezcla de workspaces: {sorted(ws_values)}",
                      fingerprint=fingerprint, original=candidate)

    # -- (2) Proveedor PRESENTE pero invalido -> INVALIDA -----------------------
    if local_present and not _source_valid(local, is_local=True):
        return _build(cand, INVALID_RESPONSES, RECO_HUMAN,
                      sources_present, signals_considered,
                      reason_codes=["local_source_invalid"],
                      reason="El proveedor local presente es invalido.",
                      fingerprint=fingerprint, original=candidate)
    if external_present and not _source_valid(external, is_local=False):
        return _build(cand, INVALID_RESPONSES, RECO_HUMAN,
                      sources_present, signals_considered,
                      reason_codes=["external_source_invalid"],
                      reason="El proveedor externo presente es invalido.",
                      fingerprint=fingerprint, original=candidate)

    # -- (3) Evidencia inexistente -> INVALIDA (penalizacion dura) ---------------
    if not _has_evidence(cand):
        return _build(cand, INVALID_RESPONSES, RECO_HUMAN,
                      sources_present, signals_considered,
                      reason_codes=["missing_evidence"],
                      reason="El candidato no aporta evidencia textual.",
                      fingerprint=fingerprint, original=candidate)

    # -- Lectura de senales/sintaxis (evidencia, no decisiones) -----------------
    neg_signal = sig.get("negation")
    rumor_signal = sig.get("rumor")
    type_compat = sig.get("type_compatibility")
    structural = bool(
        sig.get("same_clause") or sig.get("same_sentence") or sig.get("svo_pattern")
    )
    if syntax is not None:
        structural = structural or _syntax_structural(syntax)

    # -- Contradicciones (evidencia contradictoria) -----------------------------
    negation_contradiction = (
        isinstance(neg_signal, bool) and neg_signal != cand.negated
    )
    if syntax is not None and _syntax_negation(syntax) != cand.negated:
        negation_contradiction = True
    epistemic_contradiction = (
        bool(rumor_signal) and cand.epistemic_status == EpistemicStatus.ASSERTED
    )

    both_types = cand.subject_type is not None and cand.object_type is not None
    type_incompatible = both_types and isinstance(type_compat, list) and type_compat == []

    # -- Polaridad de los proveedores PRESENTES ---------------------------------
    local_pol = _LOCAL_POLARITY.get(_get(local, "recommendation")) if local_present else None
    external_pol = (
        _EXTERNAL_POLARITY.get(_get(external, "shadow_recommendation"))
        if external_present else None
    )
    decisive = [p for p in (local_pol, external_pol) if p in (_POS, _NEG)]
    pos_votes = decisive.count(_POS)
    neg_votes = decisive.count(_NEG)
    n_decision_sources = int(local_present) + int(external_present)

    # -- (4) MODEL_CONFLICT: contradiccion real ---------------------------------
    if pos_votes and neg_votes:
        reason_codes.append("provider_polarity_conflict")
    if negation_contradiction:
        reason_codes.append("negation_contradiction")
    if epistemic_contradiction:
        reason_codes.append("epistemic_contradiction")
    if reason_codes:
        return _build(cand, MODEL_CONFLICT, RECO_HUMAN,
                      sources_present, signals_considered,
                      reason_codes=sorted(reason_codes),
                      reason="Contradiccion entre fuentes/candidato.",
                      fingerprint=fingerprint, original=candidate)

    # -- (5) HUMAN_REQUIRED: tipos incompatibles o sin senal decisiva -----------
    if type_incompatible:
        return _build(cand, HUMAN_REQUIRED, RECO_HUMAN,
                      sources_present, signals_considered,
                      reason_codes=["type_incompatible"],
                      reason="Tipos incompatibles con la ontologia; requiere humano.",
                      fingerprint=fingerprint, original=candidate)

    all_abstain = n_decision_sources > 0 and not decisive
    weak_heuristics = not (structural and _has_evidence(cand))
    if all_abstain or (n_decision_sources == 0 and weak_heuristics):
        return _build(cand, HUMAN_REQUIRED, RECO_HUMAN,
                      sources_present, signals_considered,
                      reason_codes=["insufficient_support"],
                      reason="Sin senal decisiva suficiente; requiere humano.",
                      fingerprint=fingerprint, original=candidate)

    # -- Polaridad de consenso (todas las decisivas coinciden aqui) -------------
    polarity = _POS if pos_votes else (_NEG if neg_votes else _POS)
    recommendation = RECO_PROPOSE if polarity == _POS else RECO_REJECT

    # -- (6) STRONG: dos proveedores presentes, misma polaridad y soporte pleno --
    both_present_agree = (
        n_decision_sources == 2
        and len(decisive) == 2
        and pos_votes in (0, 2)  # 2 positivos o 2 negativos (no mezcla)
    )
    strong_support = structural and _has_evidence(cand) and not type_incompatible
    if both_present_agree and strong_support:
        return _build(cand, STRONG_CONSENSUS, recommendation,
                      sources_present, signals_considered,
                      reason_codes=["full_agreement"],
                      reason="Acuerdo pleno de ambos proveedores con evidencia y estructura.",
                      fingerprint=fingerprint, original=candidate)

    # -- (7) PARTIAL: corroboracion parcial (incluye heuristicas fuertes) -------
    if n_decision_sources == 0:
        code = "heuristics_only_support"
        text = "Solo senales heuristicas: corroboracion parcial, sin proveedores."
    elif n_decision_sources == 1:
        code = "single_provider_support"
        text = "Un unico proveedor presente (el otro ausente, no un rechazo)."
    else:
        code = "agreement_without_full_support"
        text = "Ambos proveedores coinciden pero falta estructura/evidencia plena."
    return _build(cand, PARTIAL_CONSENSUS, recommendation,
                  sources_present, signals_considered,
                  reason_codes=[code], reason=text,
                  fingerprint=fingerprint, original=candidate)


# ---------------------------------------------------------------------------
# Ayudas de sintaxis (R3)
# ---------------------------------------------------------------------------
def _syntax_structural(syntax: Any) -> bool:
    for sent in _get(syntax, "sentences", ()) or ():
        subj = _get(sent, "subject_index")
        verb = _get(sent, "main_verb_index")
        obj = _get(sent, "object_index")
        if subj is not None and verb is not None and obj is not None:
            return True
    return False


def _syntax_negation(syntax: Any) -> bool:
    for sent in _get(syntax, "sentences", ()) or ():
        if _get(sent, "negated"):
            return True
    return False


# ---------------------------------------------------------------------------
# Construccion del resultado (preserva negacion/temporalidad/epistemico)
# ---------------------------------------------------------------------------
def _build(
    cand: RelationCandidate,
    state: str,
    recommendation: str,
    sources_present: list,
    signals_considered: list,
    *,
    reason_codes: list,
    reason: str,
    fingerprint: Optional[str],
    original: Any,
) -> RelationConsensus:
    result = RelationConsensus(
        state=state,
        recommendation=recommendation,
        subject_id=cand.subject_id,
        predicate=cand.predicate,
        object_id=cand.object_id,
        workspace=cand.workspace,
        negated=cand.negated,
        epistemic_status=(
            cand.epistemic_status.value
            if isinstance(cand.epistemic_status, EpistemicStatus)
            else cand.epistemic_status
        ),
        temporal_scope=cand.temporal_scope,
        sources_present=list(sources_present),
        signals_considered=list(signals_considered),
        reason_codes=list(reason_codes),
        reason=reason,
    )
    # Verificacion de inmutabilidad del candidato original (defensa en profundidad).
    if fingerprint is not None:
        assert _original_fingerprint(original) == fingerprint, (
            "el candidato original NO debe mutar durante el consenso"
        )
    return result


def _invalid_stub(candidate: Any) -> RelationCandidate:
    """Stub minimo cuando el candidato no valida el contrato pero necesitamos
    emitir un RelationConsensus INVALID trazable."""
    return RelationCandidate(
        subject_id=str(_get(candidate, "subject_id", "?") or "?"),
        subject_type=None,
        predicate=str(_get(candidate, "predicate", "INVALID") or "INVALID"),
        object_id=str(_get(candidate, "object_id", "?") or "?"),
        object_type=None,
        direction=None,
        confidence=0.0,
        evidence_text="",
        evidence_start=0,
        evidence_end=0,
        source_id="?",
        source_page=None,
        source_segment="?",
        extraction_method=None,
        model=None,
        negated=bool(_get(candidate, "negated", False)),
        temporal_scope=_get(candidate, "temporal_scope"),
        epistemic_status=EpistemicStatus.ASSERTED,
        workspace=str(_get(candidate, "workspace", "?") or "?"),
    )


def _finish(
    original: Any,
    fingerprint: Optional[str],
    stub: RelationCandidate,
    state: str,
    recommendation: str,
    *,
    reason_codes: list,
    reason: str,
    signals: Optional[Sequence[Any]],
    local: Any,
    external: Any,
) -> RelationConsensus:
    """Emite un RelationConsensus para candidatos que NO validan el contrato."""
    sources_present = sorted(
        (["local_llm"] if local is not None else [])
        + (["external_ai"] if external is not None else [])
        + (["heuristics"] if signals else [])
    )
    result = RelationConsensus(
        state=state,
        recommendation=recommendation,
        subject_id=stub.subject_id,
        predicate=stub.predicate,
        object_id=stub.object_id,
        workspace=stub.workspace,
        negated=stub.negated,
        epistemic_status=stub.epistemic_status.value,
        temporal_scope=stub.temporal_scope,
        sources_present=sources_present,
        signals_considered=sorted(_signal_map(signals).keys()),
        reason_codes=list(reason_codes),
        reason=reason,
    )
    if fingerprint is not None:
        assert _original_fingerprint(original) == fingerprint, (
            "el candidato original NO debe mutar durante el consenso"
        )
    return result
