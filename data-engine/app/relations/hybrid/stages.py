# -*- coding: utf-8 -*-
"""Etapas PURAS y componibles del motor hibrido (PR#95 V4).

Cada etapa es una funcion sin efectos secundarios, sin red y sin estado
compartido: recibe entradas explicitas y devuelve estructuras nuevas. Las etapas
NO reimplementan las heuristicas del pipeline: reciben por inyeccion las
funciones canonicas existentes (`_choose_predicate`, `_confidence`,
`_temporal_scope`, `_epistemic_status`) para reutilizarlas literalmente.

Cada etapa es DESACTIVABLE por flag; el valor por DEFECTO de cada flag reproduce
EXACTAMENTE el comportamiento de la base. Desactivar una etapa produce un efecto
medible (ablation), documentado en cada docstring.

Este modulo NO importa `relations.pipeline` (evita import circular): las
dependencias del pipeline se inyectan desde `engine.py`.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from relations.contracts import Direction, EpistemicStatus
from relations.hybrid.models import EvidenceBundle, RelationHypothesis

# Predicado generico usado cuando la etapa de predicado esta DESACTIVADA. Debe
# coincidir con `pipeline.GENERIC_PREDICATE` (predicado canonico no vacio).
GENERIC_PREDICATE = "RELATED_TO"


# ---------------------------------------------------------------------------
# Etapa 1 -- Ranking de menciones / pares (top-k acotado)
# ---------------------------------------------------------------------------
def stage_rank_mentions(hypotheses: list, top_k: Optional[int]) -> tuple[list, bool]:
    """Ordena por score y ACOTA a top-k (anti-explosion de candidatos).

    DEFAULT (`top_k` None o <= 0): IDENTIDAD. Se devuelve la lista intacta, en el
    mismo orden base, sin truncar -> reproduce la base (no hay ranking extra).

    ACTIVADA (`top_k` > 0): se conservan las `top_k` hipotesis de mayor `score`
    (desempate determinista por `pair_id`), pero SE DEVUELVEN EN EL ORDEN BASE
    (estable) para no alterar el orden de salida mas alla del recorte. Devuelve
    `(hipotesis, truncated)`.

    Ablation: activar con `top_k` pequeno reduce el numero de candidatos de forma
    acotada; NUNCA lo aumenta. Invariante anti-explosion: len(salida) <=
    min(top_k, len(entrada)).
    """
    items = list(hypotheses)
    if top_k is None or top_k <= 0:
        return items, False
    ranked = sorted(items, key=lambda h: (-float(h.score), h.pair_id))
    keep_ids = {h.pair_id for h in ranked[:top_k]}
    result = [h for h in items if h.pair_id in keep_ids]
    return result, len(result) < len(items)


# ---------------------------------------------------------------------------
# Etapa 2 -- Hipotesis estructural (par -> RelationHypothesis con score)
# ---------------------------------------------------------------------------
def stage_hypothesis(pair: Any, sigmap: dict, confidence_fn: Callable[[dict], float]) -> RelationHypothesis:
    """Construye la hipotesis estructural a partir del par y sus senales.

    El `score` es la confianza heuristica canonica (`confidence_fn` = el
    `_confidence` de la base): senal ordinal determinista, reutilizada, NO
    reimplementada. Predicado/direccion se resuelven en la etapa 3 (aqui quedan
    como marcador generico). `reasoning` recoge el "por que" estructural, separado
    de cualquier cita literal.
    """
    score = float(confidence_fn(sigmap))
    return RelationHypothesis(
        pair_id=pair.pair_id,
        subject_id=pair.subject_id,
        object_id=pair.object_id,
        subject_type=pair.subject_type,
        object_type=pair.object_type,
        subject_start=pair.subject_start,
        subject_end=pair.subject_end,
        object_start=pair.object_start,
        object_end=pair.object_end,
        predicate=GENERIC_PREDICATE,
        direction=Direction.UNDIRECTED.value,
        score=score,
        reasoning=(f"hipotesis estructural score={score}",),
    )


# ---------------------------------------------------------------------------
# Etapa 3 -- Predicado / direccion
# ---------------------------------------------------------------------------
def stage_predicate_direction(
    hyp: RelationHypothesis,
    sigmap: dict,
    *,
    enabled: bool,
    choose_predicate: Callable[[dict], str],
    dir_by_pred: dict,
) -> RelationHypothesis:
    """Resuelve predicado y direccion.

    DEFAULT (enabled=True): usa `choose_predicate` (= `_choose_predicate` base) y
    `dir_by_pred` (= `_DIR_BY_PRED` base). Reproduce la base.

    ABLATION (enabled=False): degrada a predicado generico y direccion
    UNDIRECTED. Efecto medible: los predicados especificos (MEMBER_OF, OWNS,
    LOCATED_IN...) desaparecen -> cae la precision/recall por predicado.
    """
    if not enabled:
        return hyp.with_predicate(
            GENERIC_PREDICATE,
            Direction.UNDIRECTED.value,
            why="etapa predicado DESACTIVADA -> generico",
        )
    pred = choose_predicate(sigmap)
    direction = dir_by_pred.get(pred, Direction.UNDIRECTED)
    dval = direction.value if hasattr(direction, "value") else str(direction)
    return hyp.with_predicate(pred, dval, why=f"predicado={pred} por senales lexico-tipologicas")


# ---------------------------------------------------------------------------
# Etapa 4 -- Evidencia (span literal)
# ---------------------------------------------------------------------------
def stage_evidence(hyp: RelationHypothesis, seg_text: str, *, enabled: bool) -> EvidenceBundle:
    """Corta el span de evidencia LITERAL del segmento.

    DEFAULT (enabled=True): span [min(inicios), max(fines)] que cubre AMBAS
    menciones -- identico al de la base (`_build_candidate`).

    ABLATION (enabled=False): span degradado a SOLO la mencion del sujeto. La cita
    deja de cubrir el objeto -> caen `evidence_correct`/`offsets_correct`.

    La `reasoning` (por que) va SEPARADA de `evidence_text` (la cita literal).
    """
    if enabled:
        start = min(hyp.subject_start, hyp.object_start)
        end = max(hyp.subject_end, hyp.object_end)
        why = "span literal que cubre sujeto y objeto"
    else:
        start, end = hyp.subject_start, hyp.subject_end
        why = "etapa evidencia DESACTIVADA -> span degradado (solo sujeto)"
    covers_subject = start <= hyp.subject_start and end >= hyp.subject_end
    covers_object = start <= hyp.object_start and end >= hyp.object_end
    return EvidenceBundle(
        evidence_text=seg_text[start:end],
        evidence_start=start,
        evidence_end=end,
        verified=False,
        covers_subject=covers_subject,
        covers_object=covers_object,
        reasoning=(why,),
    )


# ---------------------------------------------------------------------------
# Etapa 5 -- Verificacion de la evidencia
# ---------------------------------------------------------------------------
def stage_verification(bundle: EvidenceBundle, *, enabled: bool) -> tuple[EvidenceBundle, bool, Optional[str]]:
    """Verifica que la evidencia es real (span no vacio, no en blanco).

    DEFAULT (enabled=True): span vacio (`evidence_span_empty`), solo espacios
    (`evidence_blank`) o que NO cubre ambas menciones
    (`evidence_incomplete_coverage`) => rechazo. Devuelve
    `(bundle_verificado, ok, reason_code)`. Cuando ok, `verified=True`. En el
    camino base el span SIEMPRE cubre ambas menciones (span [min,max]), asi que la
    comprobacion de cobertura no rechaza nada en default: reproduce la base.

    ABLATION (enabled=False): NO verifica; acepta el span tal cual con
    `verified=False`. Efecto medible: candidatos con evidencia degradada (p.ej. el
    span solo-sujeto que produce la etapa de evidencia desactivada) que la
    verificacion rechazaria pasan igualmente (baja la calidad estructural).
    """
    if not enabled:
        marked = EvidenceBundle(
            evidence_text=bundle.evidence_text,
            evidence_start=bundle.evidence_start,
            evidence_end=bundle.evidence_end,
            verified=False,
            covers_subject=bundle.covers_subject,
            covers_object=bundle.covers_object,
            reasoning=bundle.reasoning + ("etapa verificacion DESACTIVADA -> sin verificar",),
        )
        return marked, True, None

    if bundle.evidence_end <= bundle.evidence_start:
        return bundle, False, "evidence_span_empty"
    if not bundle.evidence_text.strip():
        return bundle, False, "evidence_blank"
    if not (bundle.covers_subject and bundle.covers_object):
        return bundle, False, "evidence_incomplete_coverage"

    verified = EvidenceBundle(
        evidence_text=bundle.evidence_text,
        evidence_start=bundle.evidence_start,
        evidence_end=bundle.evidence_end,
        verified=True,
        covers_subject=bundle.covers_subject,
        covers_object=bundle.covers_object,
        reasoning=bundle.reasoning + ("verificada: span no vacio y con contenido",),
    )
    return verified, True, None


# ---------------------------------------------------------------------------
# Etapa 6 -- Temporal / epistemica
# ---------------------------------------------------------------------------
def stage_temporal_epistemic(
    sigmap: dict,
    *,
    enabled: bool,
    temporal_fn: Callable[[dict], Any],
    epistemic_fn: Callable[[dict], EpistemicStatus],
) -> tuple[Any, EpistemicStatus, str]:
    """Resuelve alcance temporal y estatus epistemico.

    DEFAULT (enabled=True): usa `temporal_fn` (= `_temporal_scope`) y
    `epistemic_fn` (= `_epistemic_status`). Reproduce la base, incluida la
    garantia dura "un rumor NUNCA se convierte en hecho".

    ABLATION (enabled=False): temporal_scope=None y epistemic=ASSERTED. Efecto
    medible Y RELEVANTE PARA SEGURIDAD: rumores/hipoteticos se marcarian como
    ASSERTED. Por eso esta etapa se documenta como sensible: desactivarla es una
    regresion de seguridad, no solo de calidad.
    """
    if not enabled:
        return None, EpistemicStatus.ASSERTED, "etapa temporal/epistemica DESACTIVADA -> ASSERTED"
    return temporal_fn(sigmap), epistemic_fn(sigmap), "temporal+epistemico por senales class-aware"


__all__ = [
    "GENERIC_PREDICATE",
    "stage_rank_mentions",
    "stage_hypothesis",
    "stage_predicate_direction",
    "stage_evidence",
    "stage_verification",
    "stage_temporal_epistemic",
]
