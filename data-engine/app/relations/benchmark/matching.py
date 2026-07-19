# -*- coding: utf-8 -*-
"""Emparejamiento DETERMINISTA prediccion <-> ground truth (benchmark de relaciones).

Este modulo NO ejecuta el pipeline ni reimplementa ninguna etapa de R8: solo
COMPARA las predicciones ya producidas por `relations.pipeline.run_pipeline`
contra el ground truth del corpus B1. Todo el criterio de emparejamiento esta
documentado explicitamente en `docs/41-relation-benchmark-plan.md` y replicado en
los docstrings de este modulo para evitar cualquier "matching laxo no documentado".

Criterio de emparejamiento PRIMARIO (existencia de relacion)
-----------------------------------------------------------
Una prediccion P empareja con una relacion de ground truth G si y solo si:

  * mismo `source_id`  (P.source_id == G.source_id), y
  * mismo `workspace`  (P.workspace == G.workspace), y
  * MISMO PAR DE ENTIDADES NO ORDENADO:
        {P.subject_id, P.object_id} == {G.subject_id, G.object_id}.

Se usa el par NO ORDENADO porque el generador de pares de R8 canonicaliza el
"sujeto" como la mencion que aparece ANTES en el texto (orden textual), que no
tiene por que coincidir con el sujeto semantico del ground truth. La direccion
semantica (subject->object) se evalua APARTE, como atributo estructural, no como
condicion de existencia.

Asignacion 1:1 (greedy determinista)
------------------------------------
Un mismo par de entidades puede tener varias relaciones en el ground truth (p.ej.
segmentos contradictorios). R8 produce como maximo UN candidato por par y segmento
(deduplicacion interna), por lo que puede haber menos predicciones que relaciones
para un mismo par. Se recorren las relaciones de ground truth en orden de
`relation_id` y cada una toma la MEJOR prediccion aun libre del mismo grupo,
desempatando de forma determinista por (predicado correcto, direccion correcta,
candidate_id). Las relaciones sin prediccion son FN; las predicciones sin relacion
son FP.

Atributos estructurales (solo sobre los TP)
-------------------------------------------
Sobre cada par emparejado se evaluan, por separado y sin afectar a la existencia:
predicado, direccion, tipos de sujeto/objeto, negacion, temporalidad, estado
epistemico, evidencia y offsets, y la decision de consenso. La definicion exacta
de cada comprobacion vive en `structural_flags`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from relations.contracts import normalize_predicate

# Umbral de solape de spans de evidencia para considerarla "correcta" (IoU).
EVIDENCE_IOU_THRESHOLD = 0.5

# Estados temporales del ground truth que implican un marcador temporal NO trivial
# (es decir, que el pipeline deberia captar en `temporal_scope`). PRESENT/ATEMPORAL
# se consideran "sin marcador" a efectos de esta comprobacion coarse.
_TEMPORAL_EXPECTED = frozenset({"PAST", "FUTURE", "ONGOING", "ENDED"})

# Mapa recomendacion de consenso -> decision esperada del ground truth.
RECO_TO_DECISION = {
    "propose": "ACCEPT",
    "reject": "REJECT",
    "human": "REVIEW",
}


def unordered_pair_key(subject_id: str, object_id: str) -> tuple[str, str]:
    """Clave canonica del par NO ORDENADO de ids de entidad."""
    return tuple(sorted((str(subject_id), str(object_id))))  # type: ignore[return-value]


def _span_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> tuple[int, int]:
    """Devuelve (interseccion, union) de dos spans [start, end)."""
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter, max(union, 0)


def structural_flags(pred: dict, gt: dict) -> dict:
    """Comprobaciones estructurales deterministas de un par emparejado.

    Cada clave es un booleano explicito. Ninguna comprobacion es "laxa": los
    criterios son los documentados en el docstring del modulo y en docs/41.
    """
    pred_predicate = normalize_predicate(pred["predicate"])
    gt_predicate = normalize_predicate(gt["predicate"])

    inter, union = _span_overlap(
        int(pred["evidence_start"]),
        int(pred["evidence_end"]),
        int(gt["evidence_start"]),
        int(gt["evidence_end"]),
    )
    iou = (inter / union) if union > 0 else 0.0

    # Temporalidad: comprobacion coarse de DETECCION (no de vocabulario). El
    # pipeline emite `temporal_scope` como texto libre o None; el ground truth usa
    # un vocabulario cerrado. Se comprueba que el pipeline detecte marcador temporal
    # exactamente cuando el ground truth lo tiene.
    gt_temporal_expected = gt["temporal_status"] in _TEMPORAL_EXPECTED
    pred_temporal_detected = pred.get("temporal_scope") is not None

    # Direccion: exacta contra el ground truth (UNDIRECTED / SUBJECT_TO_OBJECT /
    # OBJECT_TO_SUBJECT). Como el sujeto textual puede estar invertido respecto al
    # semantico, tambien se registra la version "tolerante a inversion" para
    # relaciones dirigidas emparejadas con par invertido.
    pred_dir = pred["direction"]
    gt_dir = gt["direction"]
    swapped = str(pred["subject_id"]) != str(gt["subject_id"])
    dir_exact = pred_dir == gt_dir
    if swapped and gt_dir in ("SUBJECT_TO_OBJECT", "OBJECT_TO_SUBJECT"):
        inverted = "OBJECT_TO_SUBJECT" if gt_dir == "SUBJECT_TO_OBJECT" else "SUBJECT_TO_OBJECT"
        dir_orientation_ok = pred_dir == inverted or pred_dir == gt_dir
    else:
        dir_orientation_ok = dir_exact

    decision_pred = RECO_TO_DECISION.get(pred.get("recommendation"))

    # Tipos: el par puede venir invertido (sujeto textual != sujeto semantico), por
    # lo que se comparan como CONJUNTO NO ORDENADO de tipos de las dos entidades.
    types_correct = sorted(
        [pred.get("subject_type"), pred.get("object_type")], key=lambda x: (x is None, x)
    ) == sorted(
        [gt.get("subject_type"), gt.get("object_type")], key=lambda x: (x is None, x)
    )

    return {
        "predicate_correct": pred_predicate == gt_predicate,
        "direction_correct": dir_exact,
        "direction_orientation_ok": dir_orientation_ok,
        "types_correct": types_correct,
        "negation_correct": bool(pred["negated"]) == bool(gt["negated"]),
        "temporal_correct": pred_temporal_detected == gt_temporal_expected,
        "epistemic_correct": pred["epistemic_status"] == gt["epistemic_status"],
        "evidence_overlap_iou": round(iou, 4),
        "evidence_correct": iou >= EVIDENCE_IOU_THRESHOLD,
        "offsets_correct": inter > 0,
        "workspace_correct": pred["workspace"] == gt["workspace"],
        "decision_pred": decision_pred,
        "decision_correct": decision_pred == gt["expected_decision"],
    }


@dataclass
class MatchResult:
    """Resultado del emparejamiento de un conjunto de predicciones vs ground truth."""

    true_positives: list = field(default_factory=list)   # [{gt, pred, flags}]
    false_positives: list = field(default_factory=list)  # [pred]
    false_negatives: list = field(default_factory=list)  # [gt]

    @property
    def tp(self) -> int:
        return len(self.true_positives)

    @property
    def fp(self) -> int:
        return len(self.false_positives)

    @property
    def fn(self) -> int:
        return len(self.false_negatives)


def _pred_sort_key(pred: dict) -> tuple:
    return (
        str(pred.get("source_id")),
        str(pred.get("subject_id")),
        str(pred.get("object_id")),
        str(pred.get("predicate")),
        str(pred.get("candidate_id")),
    )


def match_predictions(predictions: list[dict], gt_relations: list[dict]) -> MatchResult:
    """Empareja predicciones contra ground truth de forma DETERMINISTA.

    No muta las entradas. El resultado es estable e independiente del orden de
    entrada (se ordena por claves canonicas antes de emparejar).
    """
    # Indice de predicciones por (source_id, par_no_ordenado), en orden estable.
    buckets: dict[tuple, list[dict]] = {}
    for pred in sorted(predictions, key=_pred_sort_key):
        key = (str(pred["source_id"]), unordered_pair_key(pred["subject_id"], pred["object_id"]))
        buckets.setdefault(key, []).append(pred)

    used: set[int] = set()
    result = MatchResult()

    for gt in sorted(gt_relations, key=lambda g: str(g["relation_id"])):
        key = (str(gt["source_id"]), unordered_pair_key(gt["subject_id"], gt["object_id"]))
        candidates = buckets.get(key, [])
        best_idx: Optional[int] = None
        best_rank: Optional[tuple] = None
        for idx, pred in enumerate(candidates):
            if id(pred) in used:
                continue
            flags = structural_flags(pred, gt)
            # Preferimos la prediccion con predicado correcto, luego direccion, luego
            # candidate_id (desempate determinista).
            rank = (
                0 if flags["predicate_correct"] else 1,
                0 if flags["direction_correct"] else 1,
                str(pred.get("candidate_id")),
            )
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_idx = idx
        if best_idx is None:
            result.false_negatives.append(gt)
        else:
            pred = candidates[best_idx]
            used.add(id(pred))
            result.true_positives.append(
                {"gt": gt, "pred": pred, "flags": structural_flags(pred, gt)}
            )

    # Predicciones no usadas -> falsos positivos.
    for pred in sorted(predictions, key=_pred_sort_key):
        if id(pred) not in used:
            result.false_positives.append(pred)

    return result


__all__ = [
    "EVIDENCE_IOU_THRESHOLD",
    "RECO_TO_DECISION",
    "MatchResult",
    "unordered_pair_key",
    "structural_flags",
    "match_predictions",
]
