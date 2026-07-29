# -*- coding: utf-8 -*-
"""Aritmetica de las metricas. Calcula; no estima.

Dos reglas que atraviesan todo el modulo:

1. **Denominador cero no es cero.** Si no hay nada que medir, la metrica vale
   ``None`` y el informe dice por que. Publicar 0.0 cuando no habia poblacion
   miente en la direccion mas facil de creer.
2. **Todo numero sale de un conteo.** No hay constantes, ni valores por
   defecto "razonables", ni suavizado.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

#: Redondeo de la salida. Suficiente para comparar corridas sin arrastrar
#: ruido de coma flotante al JSON.
ROUND = 6


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), ROUND)


def ratio(numerator: int, denominator: int) -> float | None:
    """`numerator/denominator`, o None si el denominador es cero."""
    if denominator == 0:
        return None
    return _r(numerator / denominator)


def prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    """Precision, recall y F1 con sus conteos.

    Precision es None si no se predijo nada (no hubo nada que acertar o fallar);
    recall es None si no habia gold. F1 es None si falta cualquiera de las dos.
    """
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    # F1 se calcula sobre los valores SIN redondear: redondear antes arrastra
    # el error a la tercera cifra y dos corridas identicas dejan de coincidir.
    if (tp + fp) == 0 or (tp + fn) == 0:
        f1 = None
    elif tp == 0:
        f1 = 0.0
    else:
        exact_p = tp / (tp + fp)
        exact_r = tp / (tp + fn)
        f1 = _r(2 * exact_p * exact_r / (exact_p + exact_r))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def accuracy(correct: int, total: int) -> dict[str, Any]:
    return {"correct": correct, "total": total, "accuracy": ratio(correct, total)}


# --------------------------------------------------------------------------
# Distancia de edicion (CER / WER)
# --------------------------------------------------------------------------
def levenshtein(a: Sequence[Any], b: Sequence[Any]) -> int:
    """Distancia de edicion clasica. Sobre caracteres o sobre palabras."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (0 if ca == cb else 1),
                )
            )
        previous = current
    return previous[-1]


def error_rate(reference: str, hypothesis: str, *, unit: str = "char") -> tuple[int, int]:
    """(ediciones, longitud de referencia) para CER o WER."""
    if unit == "char":
        ref: Sequence[Any] = reference
        hyp: Sequence[Any] = hypothesis
    elif unit == "word":
        ref = reference.split()
        hyp = hypothesis.split()
    else:  # pragma: no cover - guardia
        raise ValueError(f"unidad desconocida: {unit!r}")
    return levenshtein(ref, hyp), len(ref)


def repetition_score(text: str, *, block: int = 24, threshold: int = 3) -> bool:
    """True si algun bloque de `block` caracteres se repite `threshold` veces.

    Detecta el bucle tipico de un ASR o de un LLM que se engancha. Es un
    criterio explicito y reproducible, no un juicio.
    """
    if len(text) < block * threshold:
        return False
    counts: dict[str, int] = {}
    for i in range(len(text) - block + 1):
        chunk = text[i : i + block]
        counts[chunk] = counts.get(chunk, 0) + 1
        if counts[chunk] >= threshold:
            return True
    return False


# --------------------------------------------------------------------------
# Alineamiento de agrupaciones (identidad)
# --------------------------------------------------------------------------
def align_clusters(
    gold_assignment: dict[str, str],
    pred_assignment: dict[str, str],
    *,
    pinned: Iterable[str] = (),
) -> dict[str, str]:
    """Mapea cada cluster predicho a como mucho UN gold, de forma determinista.

    - Los identificadores `pinned` (los que ya existen en el catalogo gold: un
      LINK_EXISTING nombra una entidad real) se mapean a si mismos. Dejarlos
      libres permitiria que un resolutor que enlaza a la entidad equivocada se
      "corrija" por el alineamiento.
    - El resto se asigna de forma VORAZ por solape descendente, con desempate
      por identificador. Voraz nunca supera al optimo: la exactitud de identidad
      puede quedarse corta, nunca inflarse.
    """
    pinned = set(pinned)
    overlap: dict[tuple[str, str], int] = {}
    for mention, gold_entity in gold_assignment.items():
        pred_entity = pred_assignment.get(mention)
        if pred_entity is None:
            continue
        overlap[(pred_entity, gold_entity)] = overlap.get((pred_entity, gold_entity), 0) + 1

    mapping: dict[str, str] = {}
    used_gold: set[str] = set()
    gold_ids = set(gold_assignment.values())
    for pred_entity in sorted(set(pred_assignment.values())):
        if pred_entity in pinned and pred_entity in gold_ids:
            mapping[pred_entity] = pred_entity
            used_gold.add(pred_entity)

    candidates = sorted(
        (
            (-count, pred_entity, gold_entity)
            for (pred_entity, gold_entity), count in overlap.items()
            if pred_entity not in mapping
        )
    )
    for _neg, pred_entity, gold_entity in candidates:
        if pred_entity in mapping or gold_entity in used_gold:
            continue
        mapping[pred_entity] = gold_entity
        used_gold.add(gold_entity)
    return mapping


def duplicate_rate(
    gold_assignment: dict[str, str], pred_assignment: dict[str, str]
) -> dict[str, Any]:
    """Cuantos nodos de mas crea el resolutor para las mismas entidades gold.

    Por cada entidad gold, todo cluster predicho que la toque mas alla del
    primero es un duplicado. Es la medida directa de "el grafo se llena de
    copias del mismo personaje".
    """
    per_gold: dict[str, set[str]] = {}
    for mention, gold_entity in gold_assignment.items():
        pred_entity = pred_assignment.get(mention)
        if pred_entity is None:
            continue
        per_gold.setdefault(gold_entity, set()).add(pred_entity)
    covered = len(per_gold)
    duplicates = sum(max(0, len(v) - 1) for v in per_gold.values())
    return {
        "gold_entities_covered": covered,
        "duplicate_clusters": duplicates,
        "duplicate_rate": ratio(duplicates, covered),
    }


def over_merge_rate(
    gold_assignment: dict[str, str], pred_assignment: dict[str, str]
) -> dict[str, Any]:
    """Cuantos clusters predichos mezclan entidades gold distintas."""
    per_pred: dict[str, set[str]] = {}
    for mention, gold_entity in gold_assignment.items():
        pred_entity = pred_assignment.get(mention)
        if pred_entity is None:
            continue
        per_pred.setdefault(pred_entity, set()).add(gold_entity)
    merged = sum(1 for v in per_pred.values() if len(v) > 1)
    return {
        "predicted_clusters": len(per_pred),
        "over_merged_clusters": merged,
        "over_merge_rate": ratio(merged, len(per_pred)),
    }


def set_prf(gold: set[Any], pred: set[Any]) -> dict[str, Any]:
    """P/R/F1 sobre conjuntos (hechos deduplicados)."""
    tp = len(gold & pred)
    return prf(tp, len(pred - gold), len(gold - pred))


def negation_policy_metrics(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Calcula las cinco puertas de la politica sobre casos del split negation.

    Cada fila empareja gold y salida real mediante estos campos:
    ``expected_negated``, ``predicted_negated``, ``family``,
    ``expected_decision``, ``predicted_decision``, ``evidence_anchored`` y
    ``scope_correct``. La funcion no modifica ni completa el gold. En especial,
    el recall de autoaprobacion conserva su denominador aunque el motor no
    apruebe nada: 0 de N vale 0.0, nunca ``None``.
    """
    negative_gold = [case for case in cases if case["expected_negated"]]
    predicted_negative = [case for case in cases if case["predicted_negated"]]
    negative_tp = sum(case["expected_negated"] for case in predicted_negative)
    negative_fp = len(predicted_negative) - negative_tp
    false_positive_edges = sum(
        case["expected_negated"] and not case["predicted_negated"] for case in cases
    )
    negated_cessation = [
        case for case in cases if case.get("family") == "NEGATED_CESSATION"
    ]
    false_cessations = sum(
        case.get("predicted_negation_kind") == "CESSATION" for case in negated_cessation
    )
    anchored = sum(bool(case["evidence_anchored"]) for case in cases)
    scope_correct = sum(bool(case["scope_correct"]) for case in cases)
    auto_gold = [
        case
        for case in negative_gold
        if case["expected_decision"] == "AUTO_APPROVE"
    ]
    auto_approved = sum(
        case["predicted_decision"] == "ACCEPT" for case in auto_gold
    )
    return {
        "negative_edge_precision": {
            **prf(negative_tp, negative_fp, len(negative_gold) - negative_tp),
            "false_positive_positive_edges": false_positive_edges,
            "passes": negative_fp == 0 and false_positive_edges == 0,
        },
        "negated_cessation_safety": {
            "correct": len(negated_cessation) - false_cessations,
            "total": len(negated_cessation),
            "false_cessations": false_cessations,
            "accuracy": ratio(
                len(negated_cessation) - false_cessations, len(negated_cessation)
            ),
            "passes": false_cessations == 0,
        },
        "evidence_grounding": {
            **accuracy(anchored, len(cases)),
            "passes": bool(cases) and anchored == len(cases),
        },
        "scope_accuracy": {
            **accuracy(scope_correct, len(cases)),
            "passes": bool(cases) and scope_correct == len(cases),
        },
        "auto_approval_recall": {
            "auto_approved": auto_approved,
            "auto_approvable": len(auto_gold),
            "recall": ratio(auto_approved, len(auto_gold)),
            "passes": bool(auto_gold) and auto_approved == len(auto_gold),
        },
    }


def negation_split_metrics(gold: Any, predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Empareja salidas por ``case_id`` con el gold inmutable del split.

    El adaptador solo lee `GoldDataset`; no completa predicciones ausentes ni
    escribe anotaciones. Exige una salida para cada claim evaluable, evitando
    que una corrida parcial infle las cinco metricas.
    """
    if gold.split != "negation":
        raise ValueError(f"se esperaba split 'negation', recibido {gold.split!r}")
    rows: list[dict[str, Any]] = []
    for claim in gold.claims:
        annotation = claim["metadata"]["negation"]
        # El unico ABSTAIN del gold no declara polaridad de arista: no entra en
        # ninguna de las cinco metricas de aprobacion/escritura.
        if not isinstance(annotation.get("expected_negated"), bool):
            continue
        case_id = annotation["case_id"]
        prediction_key = claim["claim_id"] if claim["claim_id"] in predictions else case_id
        if prediction_key not in predictions:
            raise ValueError(f"falta prediccion para {claim['claim_id']} ({case_id})")
        predicted = predictions[prediction_key]
        rows.append(
            {
                "family": annotation["family"],
                "expected_negated": annotation["expected_negated"],
                "predicted_negated": bool(predicted["negated"]),
                "predicted_negation_kind": predicted.get("negation_kind", ""),
                "expected_decision": annotation["expected_decision"],
                "predicted_decision": predicted["decision"],
                "evidence_anchored": bool(predicted["evidence_anchored"]),
                "scope_correct": bool(predicted["scope_correct"]),
            }
        )
    return negation_policy_metrics(rows)


__all__ = [
    "ROUND",
    "accuracy",
    "align_clusters",
    "duplicate_rate",
    "error_rate",
    "levenshtein",
    "negation_policy_metrics",
    "negation_split_metrics",
    "over_merge_rate",
    "prf",
    "ratio",
    "repetition_score",
    "set_prf",
]
