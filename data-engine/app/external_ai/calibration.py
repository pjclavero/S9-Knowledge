# -*- coding: utf-8 -*-
"""Calibración de métricas del subsistema de IA externa (shadow mode).

Compara shadow_recommendation con decisiones humanas reales para medir
alineación, detectar errores graves y evaluar umbrales de calidad.
Nunca activa la autoaprobación ni modifica Neo4j.
"""
from __future__ import annotations

from collections import defaultdict

from external_ai.models import (
    STRONG_CONSENSUS,
    MODEL_CONFLICT,
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    ConsensusResult,
)

# Mínimo de muestras para que un grupo sea representativo.
_MIN_SUPPORT = 30

# Umbrales de activación (solo evaluados; nunca activan nada).
_THRESHOLD_PRECISION = 0.98
_THRESHOLD_EVIDENCE_VALID = 1.0
_THRESHOLD_WORKSPACE_CORRECT = 1.0

# Decisiones que implican aceptar la entidad.
_ACCEPTING = frozenset({"accept", "edit", "use_existing"})

# Mapa de acción humana a etiqueta canónica.
_HUMAN_ACTION_MAP: dict[str, str] = {
    "approve": "accept",
    "approve_unchanged": "accept",
    "accept": "accept",
    "use_existing": "use_existing",
    "edit": "edit",
    "reject": "reject",
    "uncertain": "uncertain",
}


def _map_human(action: str) -> str:
    """Convierte la acción humana a la etiqueta canónica de comparación."""
    return _HUMAN_ACTION_MAP.get(action.strip().lower(), action.strip().lower())


def _is_grave_error(shadow: str, human_label: str, decision_a: str | None,
                    evidence_a: str, evidence_b: str) -> bool:
    """Determina si la comparación constituye un error grave.

    Criterios de error grave:
    - Shadow acepta (accept/edit/use_existing) pero humano rechaza.
    - Shadow es use_existing pero humano no lo es (falsa fusión).
    - Evidencia ausente en reviewer_a o reviewer_b.
    """
    shadow_accepting = shadow in _ACCEPTING
    human_rejecting = human_label == "reject"
    if shadow_accepting and human_rejecting:
        return True
    if shadow == "use_existing" and human_label != "use_existing":
        return True
    if not evidence_a or not evidence_b:
        return True
    return False


def _precision_recall(
    label: str,
    predictions: list[str],
    truths: list[str],
) -> tuple[float, float]:
    """Calcula precision y recall para una etiqueta concreta."""
    tp = sum(1 for p, t in zip(predictions, truths) if p == label and t == label)
    fp = sum(1 for p, t in zip(predictions, truths) if p == label and t != label)
    fn = sum(1 for p, t in zip(predictions, truths) if p != label and t == label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return round(precision, 4), round(recall, 4)


def calibrate(
    consensus_results: list[ConsensusResult],
    human_decisions: dict,
    hybrid_decisions: dict | None = None,
    meta: dict | None = None,
) -> dict:
    """Calibra las métricas del motor de consenso contra decisiones humanas.

    Parámetros
    ----------
    consensus_results:
        Lista de ConsensusResult generada por compute_consensus().
    human_decisions:
        ``{candidate_id: {"action": "approve|use_existing|edit|reject", ...}}``.
        Campos opcionales: workspace, entity_type, source_kind.
    hybrid_decisions:
        ``{candidate_id: str}`` — decisión del pipeline híbrido (opcional).
    meta:
        ``{candidate_id: {"workspace":…, "entity_type":…, "source_kind":…}}``
        Metadatos adicionales por candidato (enriquece agrupación).

    Retorna
    -------
    dict con métricas completas, umbrales y flag shadow_mode=True.
    """
    if meta is None:
        meta = {}
    if hybrid_decisions is None:
        hybrid_decisions = {}

    # Indexar resultados por candidate_id.
    result_by_id: dict[str, ConsensusResult] = {r.candidate_id: r for r in consensus_results}

    # Candidatos presentes en ambos conjuntos.
    common_ids = [cid for cid in human_decisions if cid in result_by_id]

    # Listas paralelas para cálculos globales.
    shadows: list[str] = []
    humans: list[str] = []
    hybrids: list[str] = []
    grave_errors: list[dict] = []

    # Acumuladores de grupos.
    # Estructura: {group_key: {dimension_value: {shadow: [...], human: [...], ...}}}
    group_data: dict[str, dict[str, dict]] = {
        "workspace": defaultdict(lambda: {"shadow": [], "human": [], "state": [], "grave": []}),
        "entity_type": defaultdict(lambda: {"shadow": [], "human": [], "state": [], "grave": []}),
        "source_kind": defaultdict(lambda: {"shadow": [], "human": [], "state": [], "grave": []}),
        "model": defaultdict(lambda: {"shadow": [], "human": [], "state": [], "grave": []}),
        "consensus_rule": defaultdict(lambda: {"shadow": [], "human": [], "state": [], "grave": []}),
    }

    for cid in common_ids:
        human_raw = human_decisions[cid]
        human_action = human_raw.get("action", "") if isinstance(human_raw, dict) else str(human_raw)
        human_label = _map_human(human_action)

        cr = result_by_id[cid]
        shadow = cr.shadow_recommendation

        # Evidencias de reviewer_a y reviewer_b.
        ev_a = (cr.reviewer_a or {}).get("evidence", "")
        ev_b = (cr.reviewer_b or {}).get("evidence", "")
        decision_a_str = (cr.reviewer_a or {}).get("decision")

        grave = _is_grave_error(shadow, human_label, decision_a_str, ev_a, ev_b)
        if grave:
            grave_errors.append({
                "candidate_id": cid,
                "shadow": shadow,
                "human": human_label,
                "state": cr.state,
                "evidence_a": ev_a,
                "evidence_b": ev_b,
            })

        shadows.append(shadow)
        humans.append(human_label)

        if cid in hybrid_decisions:
            hybrids.append(hybrid_decisions[cid])

        # Metadatos para agrupación.
        cid_meta = meta.get(cid, {})
        workspace = (
            cid_meta.get("workspace")
            or (human_raw.get("workspace") if isinstance(human_raw, dict) else None)
            or "unknown"
        )
        entity_type = (
            cid_meta.get("entity_type")
            or (human_raw.get("entity_type") if isinstance(human_raw, dict) else None)
            or (cr.reviewer_a or {}).get("entity_type")
            or "unknown"
        )
        source_kind = (
            cid_meta.get("source_kind")
            or (human_raw.get("source_kind") if isinstance(human_raw, dict) else None)
            or "unknown"
        )
        model = (
            cid_meta.get("model")
            or "unknown"
        )
        consensus_rule = cr.state

        for dim, val in [
            ("workspace", workspace),
            ("entity_type", entity_type),
            ("source_kind", source_kind),
            ("model", model),
            ("consensus_rule", consensus_rule),
        ]:
            bucket = group_data[dim][val]
            bucket["shadow"].append(shadow)
            bucket["human"].append(human_label)
            bucket["state"].append(cr.state)
            bucket["grave"].append(grave)

    # ------------------------------------------------------------------
    # Métricas globales
    # ------------------------------------------------------------------
    n = len(common_ids)

    def _accuracy(preds: list[str], truths: list[str]) -> float:
        if not truths:
            return 0.0
        return round(sum(p == t for p, t in zip(preds, truths)) / len(truths), 4)

    overall_accuracy = _accuracy(shadows, humans)

    # agreement_rate: shadow coincide con humano entre los que tienen human label.
    agreement_count = sum(1 for s, h in zip(shadows, humans) if s == h)
    agreement_rate = round(agreement_count / n, 4) if n else 0.0

    # Precision y recall por etiqueta.
    all_labels = sorted(set(shadows) | set(humans))
    per_label_metrics: dict[str, dict] = {}
    for lbl in all_labels:
        prec, rec = _precision_recall(lbl, shadows, humans)
        support = humans.count(lbl)
        per_label_metrics[lbl] = {"precision": prec, "recall": rec, "support": support}

    # Confusion matrix: {human_label: {shadow_label: count}}.
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s, h in zip(shadows, humans):
        confusion[h][s] += 1
    confusion_matrix = {k: dict(v) for k, v in confusion.items()}

    # strong_consensus_coverage entre candidatos comunes.
    strong_ids = {
        cid for cid in common_ids
        if result_by_id[cid].state == STRONG_CONSENSUS
    }
    strong_consensus_coverage = round(len(strong_ids) / n, 4) if n else 0.0

    # conflict_rate.
    conflict_count = sum(
        1 for cid in common_ids if result_by_id[cid].state == MODEL_CONFLICT
    )
    conflict_rate = round(conflict_count / n, 4) if n else 0.0

    # human_review_reduction_potential: fracción de STRONG_CONSENSUS cuyo shadow
    # coincide con el humano → decisiones que no habrían necesitado revisión.
    strong_match = sum(
        1 for cid in strong_ids
        if result_by_id[cid].shadow_recommendation == _map_human(
            (human_decisions[cid].get("action", "") if isinstance(human_decisions[cid], dict)
             else str(human_decisions[cid]))
        )
    )
    human_review_reduction_potential = (
        round(strong_match / len(strong_ids), 4) if strong_ids else 0.0
    )

    # Hybrid accuracy (opcional).
    hybrid_accuracy: float | None = None
    if hybrids:
        # Solo candidatos con hybrid disponible.
        hyb_common = [cid for cid in common_ids if cid in hybrid_decisions]
        hyb_preds = [hybrid_decisions[cid] for cid in hyb_common]
        hyb_truths = [
            _map_human(
                human_decisions[cid].get("action", "") if isinstance(human_decisions[cid], dict)
                else str(human_decisions[cid])
            )
            for cid in hyb_common
        ]
        hybrid_accuracy = _accuracy(hyb_preds, hyb_truths)

    # ------------------------------------------------------------------
    # Métricas por grupo
    # ------------------------------------------------------------------
    def _group_metrics(bucket: dict) -> dict:
        s_list = bucket["shadow"]
        h_list = bucket["human"]
        g_list = bucket["grave"]
        sup = len(h_list)
        acc = _accuracy(s_list, h_list)
        g_count = sum(g_list)
        lbls = sorted(set(s_list) | set(h_list))
        per_lbl = {}
        for lbl in lbls:
            pr, rc = _precision_recall(lbl, s_list, h_list)
            per_lbl[lbl] = {"precision": pr, "recall": rc, "support": h_list.count(lbl)}
        return {
            "support": sup,
            "accuracy": acc,
            "grave_errors": g_count,
            "per_label": per_lbl,
        }

    grouped: dict[str, dict] = {}
    for dim, buckets in group_data.items():
        grouped[dim] = {val: _group_metrics(b) for val, b in buckets.items()}

    # ------------------------------------------------------------------
    # Evaluación de umbrales (solo informa; nunca activa nada)
    # ------------------------------------------------------------------
    thresholds = evaluate_thresholds({
        "per_label": per_label_metrics,
        "grave_errors": len(grave_errors),
        "support": n,
        "grouped": grouped,
    })

    return {
        "shadow_mode": True,
        "note": "no activa autoaprobacion",
        "n_evaluated": n,
        "overall_accuracy": overall_accuracy,
        "agreement_rate": agreement_rate,
        "hybrid_accuracy": hybrid_accuracy,
        "per_label": per_label_metrics,
        "confusion_matrix": confusion_matrix,
        "strong_consensus_coverage": strong_consensus_coverage,
        "conflict_rate": conflict_rate,
        "human_review_reduction_potential": human_review_reduction_potential,
        "grave_errors": grave_errors,
        "grave_error_count": len(grave_errors),
        "grouped": grouped,
        "thresholds": thresholds,
    }


def evaluate_thresholds(metrics: dict) -> dict:
    """Evalúa si los grupos calificarían para autoaprobación hipotética.

    IMPORTANTE: Este análisis es puramente informativo. ``would_qualify=True``
    NO activa ninguna autoaprobación ni modificación productiva.

    Un grupo califica SOLO si cumple TODOS:
    - precision >= 0.98 en la etiqueta relevante.
    - grave_errors == 0.
    - support >= 30.
    - evidence_valid == 1.0 (no implementado en este nivel; se asume 1.0 si
      grave_errors == 0, ya que errores de evidencia generan grave_errors).
    - workspace_correct == 1.0 (no computable aquí; se conserva como placeholder).

    Retorna
    -------
    dict con evaluaciones por etiqueta y un resumen global.
    """
    per_label: dict = metrics.get("per_label", {})
    grave_errors: int = metrics.get("grave_errors", 0)
    support: int = metrics.get("support", 0)

    label_evals: dict[str, dict] = {}
    any_qualifies = False

    for lbl, lbl_metrics in per_label.items():
        prec = lbl_metrics.get("precision", 0.0)
        lbl_support = lbl_metrics.get("support", 0)

        if lbl_support < _MIN_SUPPORT:
            label_evals[lbl] = {
                "would_qualify": False,
                "status": "INSUFFICIENT_SAMPLE",
                "precision": prec,
                "support": lbl_support,
                "grave_errors": grave_errors,
            }
            continue

        qualifies = (
            prec >= _THRESHOLD_PRECISION
            and grave_errors == 0
            and lbl_support >= _MIN_SUPPORT
        )

        status = "QUALIFIES_HYPOTHETICALLY" if qualifies else "DOES_NOT_QUALIFY"
        if qualifies:
            any_qualifies = True

        label_evals[lbl] = {
            "would_qualify": qualifies,
            "status": status,
            "precision": prec,
            "support": lbl_support,
            "grave_errors": grave_errors,
            "note": (
                "Solo informativo. No activa ninguna accion productiva."
                if qualifies else ""
            ),
        }

    # Evaluación global.
    if support < _MIN_SUPPORT:
        global_status = "INSUFFICIENT_SAMPLE"
        global_qualifies = False
    else:
        global_qualifies = any_qualifies and grave_errors == 0
        global_status = (
            "SOME_LABELS_QUALIFY_HYPOTHETICALLY"
            if global_qualifies
            else "DOES_NOT_QUALIFY"
        )

    return {
        "shadow_mode": True,
        "note": "no activa autoaprobacion",
        "global": {
            "would_qualify": global_qualifies,
            "status": global_status,
            "support": support,
            "grave_errors": grave_errors,
        },
        "per_label": label_evals,
    }


def render_markdown(metrics: dict) -> str:
    """Genera un informe Markdown conciso de las métricas de calibración.

    Parámetros
    ----------
    metrics:
        Dict devuelto por calibrate().

    Retorna
    -------
    str con el informe en formato Markdown.
    """
    lines: list[str] = []
    lines.append("# Informe de Calibración — Shadow Mode")
    lines.append("")
    lines.append(
        "> **MODO SOMBRA**: Las métricas son informativas. "
        "Ninguna recomendación activa decisiones productivas."
    )
    lines.append("")

    # Resumen global.
    n = metrics.get("n_evaluated", 0)
    lines.append(f"## Resumen global (n={n})")
    lines.append("")
    lines.append(f"| Métrica | Valor |")
    lines.append(f"|---------|-------|")
    lines.append(f"| Accuracy (shadow vs humano) | {metrics.get('overall_accuracy', 0):.2%} |")
    lines.append(f"| Agreement rate | {metrics.get('agreement_rate', 0):.2%} |")
    lines.append(f"| Strong consensus coverage | {metrics.get('strong_consensus_coverage', 0):.2%} |")
    lines.append(f"| Conflict rate | {metrics.get('conflict_rate', 0):.2%} |")
    lines.append(f"| Reducción potencial de revisión humana | {metrics.get('human_review_reduction_potential', 0):.2%} |")
    lines.append(f"| Errores graves | {metrics.get('grave_error_count', 0)} |")

    hybrid_acc = metrics.get("hybrid_accuracy")
    if hybrid_acc is not None:
        lines.append(f"| Accuracy híbrida | {hybrid_acc:.2%} |")

    lines.append("")

    # Métricas por etiqueta.
    per_label = metrics.get("per_label", {})
    if per_label:
        lines.append("## Precision / Recall por etiqueta")
        lines.append("")
        lines.append("| Etiqueta | Precision | Recall | Soporte |")
        lines.append("|----------|-----------|--------|---------|")
        for lbl, lm in sorted(per_label.items()):
            lines.append(
                f"| {lbl} | {lm['precision']:.2%} | {lm['recall']:.2%} | {lm['support']} |"
            )
        lines.append("")

    # Errores graves.
    grave_errors = metrics.get("grave_errors", [])
    if grave_errors:
        lines.append("## Errores graves")
        lines.append("")
        lines.append(
            "| candidate_id | shadow | humano | estado |"
        )
        lines.append("|---|---|---|---|")
        for ge in grave_errors[:20]:  # mostrar máx. 20
            lines.append(
                f"| {ge['candidate_id']} | {ge['shadow']} | {ge['human']} | {ge['state']} |"
            )
        if len(grave_errors) > 20:
            lines.append(f"| … | ({len(grave_errors) - 20} más) | | |")
        lines.append("")

    # Evaluación de umbrales.
    thresholds = metrics.get("thresholds", {})
    glbl = thresholds.get("global", {})
    if glbl:
        lines.append("## Evaluación de umbrales (hipotética)")
        lines.append("")
        lines.append(f"**Estado global**: `{glbl.get('status', 'N/A')}`")
        lines.append("")
        lbl_evals = thresholds.get("per_label", {})
        if lbl_evals:
            lines.append("| Etiqueta | ¿Calificaría? | Estado | Precision | Soporte |")
            lines.append("|----------|--------------|--------|-----------|---------|")
            for lbl, ev in sorted(lbl_evals.items()):
                qualifies = "Sí" if ev.get("would_qualify") else "No"
                lines.append(
                    f"| {lbl} | {qualifies} | {ev.get('status','')} "
                    f"| {ev.get('precision', 0):.2%} | {ev.get('support', 0)} |"
                )
        lines.append("")
        lines.append(
            "> `would_qualify=True` es solo un indicador hipotetico. "
            "No activa ninguna autoaprobacion."
        )
        lines.append("")

    # Nota final.
    lines.append("---")
    lines.append(f"*{metrics.get('note', 'no activa autoaprobacion')}*")
    lines.append("")

    return "\n".join(lines)
