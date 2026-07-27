# -*- coding: utf-8 -*-
"""Salida del arnes: JSON estable y tabla markdown.

El JSON es la fuente de verdad (se compara entre corridas byte a byte); el
markdown es para leerlo. Los dos salen del MISMO informe: no existe ningun
numero en la tabla que no este en el JSON.
"""
from __future__ import annotations

import json
from typing import Any

#: Filas de la tabla resumen: (seccion, ruta dentro de la seccion, etiqueta).
#: El orden es el del pipeline, de la fuente al grafo.
#:
#: REGLA DE SUPERFICIE: toda metrica calculada sobre una poblacion EMPAREJADA va
#: acompañada, en la propia tabla, de su cobertura y de su variante estricta
#: (denominador = gold entero). Un motor que decide sobre una de veintiuna puede
#: sacar F1=1.0 sobre lo emparejado; si la tabla no enseña que decidio sobre el
#: 4.8 %, ese 1.0 se lee como si hubiera resuelto el problema. Es la forma exacta
#: del 0.81 de V2, y no puede estar solo en el JSON.
SUMMARY_ROWS: tuple[tuple[str, str, str], ...] = (
    ("normalizer", "char_coverage", "Normalizador · cobertura de texto (contenido)"),
    ("normalizer", "episode_char_recall", "Normalizador · caracteres con episodio emitido"),
    ("normalizer", "episode_detection.recall", "Normalizador · episodios detectados (R)"),
    ("normalizer", "cer", "Normalizador · CER"),
    ("normalizer", "wer", "Normalizador · WER"),
    ("normalizer", "truncation_rate", "Normalizador · truncado"),
    ("normalizer", "page_recall", "Normalizador · paginas recuperadas"),
    ("extractor", "mentions.precision", "Extractor · menciones P"),
    ("extractor", "mentions.recall", "Extractor · menciones R"),
    ("extractor", "mentions.f1", "Extractor · menciones F1"),
    ("extractor", "type_accuracy_matched.accuracy", "Extractor · tipo (sobre emparejadas)"),
    ("extractor", "type_accuracy_strict.accuracy", "Extractor · tipo (sobre gold entero)"),
    ("extractor", "coreference.f1", "Extractor · correferencia F1"),
    ("extractor", "claims.precision", "Extractor · claims P"),
    ("extractor", "claims.recall", "Extractor · claims R"),
    ("extractor", "claims.f1", "Extractor · claims F1"),
    ("extractor", "false_candidates.traps_hit", "Extractor · trampas pisadas"),
    ("extractor", "false_candidates.traps_total", "Extractor · trampas del split"),
    ("extractor", "false_candidates.trap_hit_rate", "Extractor · trampas pisadas (tasa)"),
    (
        "extractor",
        "false_candidates.false_candidate_rate",
        "Extractor · candidatos falsos (diluible)",
    ),
    (
        "extractor",
        "false_candidates.unanchored_claims_in_trap_episodes",
        "Extractor · claims sin anclar en episodio con trampa",
    ),
    ("resolver", "resolution_groups_matched", "Resolutor · grupos emparejados"),
    ("resolver", "resolution_groups_gold", "Resolutor · grupos gold"),
    ("resolver", "resolution_coverage", "Resolutor · cobertura de grupos"),
    ("resolver", "identity_accuracy.accuracy", "Resolutor · exactitud de identidad"),
    ("resolver", "duplicate_rate", "Resolutor · duplicados"),
    ("resolver", "over_merge_rate", "Resolutor · fusiones indebidas"),
    ("resolver", "action_accuracy.accuracy", "Resolutor · accion correcta (emparejados)"),
    ("resolver", "action_accuracy_strict.accuracy", "Resolutor · accion correcta (gold entero)"),
    ("engine", "decisions_matched", "Motor · decisiones emparejadas"),
    ("engine", "decisions_gold", "Motor · decisiones gold"),
    ("engine", "decision_coverage", "Motor · cobertura de decisiones"),
    ("engine", "decision_accuracy.accuracy", "Motor · decision (emparejadas)"),
    ("engine", "decision_accuracy_strict.accuracy", "Motor · decision (gold entero)"),
    ("engine", "predicate.f1", "Motor · predicado F1 (emparejadas)"),
    ("engine", "predicate_strict.f1", "Motor · predicado F1 (gold entero)"),
    ("engine", "direction.f1", "Motor · direccion F1 (emparejadas)"),
    ("engine", "direction_strict.f1", "Motor · direccion F1 (gold entero)"),
    ("engine", "epistemic.f1", "Motor · epistemico F1 (emparejadas)"),
    ("engine", "epistemic_strict.f1", "Motor · epistemico F1 (gold entero)"),
    ("engine", "negation.precision", "Motor · negacion P (emparejadas)"),
    ("engine", "negation.recall", "Motor · negacion R (emparejadas)"),
    ("engine", "negation_strict.f1", "Motor · negacion F1 (gold entero)"),
    ("engine", "temporal.temporal_tuple_accuracy.accuracy", "Motor · temporalidad"),
    ("engine", "false_approve_rate", "Motor · aprobacion falsa"),
    ("engine", "false_reject_rate", "Motor · rechazo falso"),
    ("engine", "abstention_rate", "Motor · abstencion"),
    ("e2e", "facts.precision", "E2E · hechos P"),
    ("e2e", "facts.recall", "E2E · hechos R"),
    ("e2e", "facts.f1", "E2E · hechos F1"),
    ("e2e", "provenance_completeness.accuracy", "E2E · procedencia completa"),
    ("e2e", "duplicate_fact_rate", "E2E · hechos duplicados"),
    ("e2e", "false_approved_plan_rate", "E2E · planes aprobados en falso"),
)


def dig(section: dict[str, Any], path: str) -> Any:
    node: Any = section
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def to_json(report: dict[str, Any]) -> str:
    """JSON estable: claves ordenadas y salto final. Comparable byte a byte."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "n/d"
    if isinstance(value, bool):
        return "si" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def to_markdown(report: dict[str, Any]) -> str:
    """Tabla legible. `n/d` significa 'no habia poblacion que medir'."""
    lines: list[str] = []
    ablation = report.get("ablation") or {}
    lines.append(f"# Benchmark S9-Knowledge V3 — split `{report.get('split')}`")
    lines.append("")
    lines.append(f"- corrida: `{report.get('run_id')}`")
    lines.append(f"- subsistema declarado: `{report.get('subsystem')}`")
    lines.append(f"- ablacion: `{ablation.get('label')}` — {ablation.get('description', '')}")
    match_config = report.get("match_config") or {}
    lines.append(
        "- emparejamiento: span `{span}`, umbral {thr}, clave de claim + {extra}".format(
            span=match_config.get("span_mode"),
            thr=match_config.get("overlap_threshold"),
            extra=match_config.get("claim_key_extra") or "[]",
        )
    )
    lines.append("")

    skipped = [
        (name, section.get("reason", ""))
        for name, section in report.items()
        if isinstance(section, dict) and section.get("status") == "not_evaluated"
    ]

    lines.append("| Métrica | Valor |")
    lines.append("|---|---:|")
    for section_name, path, label in SUMMARY_ROWS:
        section = report.get(section_name)
        if not isinstance(section, dict) or section.get("status") == "not_evaluated":
            continue
        lines.append(f"| {label} | {_fmt(dig(section, path))} |")
    lines.append("")

    if skipped:
        lines.append("## Secciones no evaluadas")
        lines.append("")
        for name, reason in sorted(skipped):
            lines.append(f"- `{name}`: {reason}")
        lines.append("")

    gold = report.get("gold") or {}
    lines.append("## Gold utilizado")
    lines.append("")
    lines.append("| Elemento | Nº |")
    lines.append("|---|---:|")
    for key in (
        "sources",
        "episodes",
        "fragments",
        "mentions",
        "resolutions",
        "claims",
        "assertions",
        "decisions",
        "plans",
        "negatives",
        "entities",
    ):
        if key in gold:
            lines.append(f"| {key} | {gold[key]} |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["SUMMARY_ROWS", "dig", "to_json", "to_markdown"]
