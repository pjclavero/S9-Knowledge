# -*- coding: utf-8 -*-
"""ACUERDO-2: repite la medicion de `measure_agreement.py` sobre el corpus
NUEVO `agreement-eval2` (42 casos / 37 claims evaluables, entidades y frases
nunca vistas, ver docs/v3/48) en vez del split `negation` (56 casos).

Es una copia deliberada de `measure_agreement.py`, no una generalizacion con
flag: el criterio del bloque anterior (docs/v3/47) fue evitar que un cambio
de parametro silencioso reabra el split congelado; aqui se aplica la misma
disciplina al reves -- este script es un split DISTINTO, con su propio
gold, su propio workspace (`bench-agreement-eval2`) y su propia cache
(nunca comparte `artifacts/agreement/cache/` de la medicion 1, por la misma
razon de contaminacion cruzada documentada en `measure_agreement.py`).

Reutiliza TAL CUAL: `knowledge_v3.eval._frozen_runner` (alineamiento de tres
fases + `build_rows`, generico sobre `gold`/`result`, no atado al split
`negation`), `knowledge_v3.pipeline.runner.run_one` (acepta `workspace`
arbitrario), `scripts.gate4.measure_b3.make_b3_port` (transporte NVIDIA),
y el CRITERIO de acuerdo (`compute_agreement`) importado directamente de
`measure_agreement.py` para no duplicar 150 lineas ya revisadas.

Uso (desde la raiz del repo):

    export S9K_NVIDIA_ENABLED=true
    export S9K_NVIDIA_API_KEY=...
    PYTHONPATH=data-engine/app python3 scripts/agreement/measure_agreement2.py \
        --out-dir artifacts/agreement --out-name agreement-eval2 \
        --cache artifacts/agreement/cache2 --concurrency 2

`--mock` sustituye NVIDIA por un puerto guionizado, igual que en el bloque 1.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

_APP = Path(__file__).resolve().parents[2] / "data-engine" / "app"
_GATE4_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "gate4"
_AGREEMENT_SCRIPTS = Path(__file__).resolve().parent
for _p in (_APP, _GATE4_SCRIPTS, _AGREEMENT_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import measure_b3 as b3  # noqa: E402
import measure_agreement as m1  # noqa: E402 -- reutiliza compute_agreement, _match_config, etc.

from knowledge_v3.eval import _frozen_runner as _fr  # noqa: E402
from knowledge_v3.eval.dev_corpus import load_dev_gold  # noqa: E402
from knowledge_v3.pipeline.runner import run_one  # noqa: E402

_FROZEN = _fr.load()

#: Split y workspace de ESTE bloque, no del `negation` congelado: se leen del
#: propio corpus (manifest + `_authoring/cases.py`), nunca copiados a mano.
SPLIT = "agreement-eval2"
_WORKSPACE = "bench-agreement-eval2"


def build_report(
    *, cache_dir: Optional[Path], mock: bool, timeout_seconds: int,
    concurrency: int, price_per_million_tokens_usd: Optional[float],
) -> dict[str, Any]:
    gold = load_dev_gold(split=SPLIT, verify=True)
    match_config = m1._match_config(gold)

    started_det = time.monotonic()
    _report_det, result_det = run_one(
        gold, "local_only", workspace=_WORKSPACE, entry="raw", run_id=f"agreement2-{SPLIT}-local"
    )
    wall_det = int((time.monotonic() - started_det) * 1000)
    det_rows, det_diag = m1._lane_rows(gold, result_det, match_config)

    port, metering = b3.make_b3_port(cache_dir=cache_dir, mock=mock, timeout_seconds=timeout_seconds)
    started_nvidia = time.monotonic()
    _report_nvidia, result_nvidia = run_one(
        gold, "external_only", workspace=_WORKSPACE, entry="raw",
        run_id=f"agreement2-{SPLIT}-external", external_port=port,
    )
    wall_nvidia = int((time.monotonic() - started_nvidia) * 1000)
    nvidia_rows, nvidia_diag = m1._lane_rows(gold, result_nvidia, match_config)

    agreement = m1.compute_agreement(det_rows, nvidia_rows)

    calls = metering.calls
    real_calls = [c for c in calls if c["ok"]]
    tanda = list(getattr(port, "_data", {}).values()) or real_calls
    latencies = sorted(int(c.get("latency_ms", 0)) for c in tanda) if tanda else []

    def _usage(entry: dict, key: str) -> int:
        usage = entry.get("usage")
        if isinstance(usage, dict):
            return int(usage.get(key, 0) or 0)
        return int(entry.get(key, 0) or 0)

    prompt_tokens = sum(_usage(c, "prompt_tokens") for c in tanda)
    completion_tokens = sum(_usage(c, "completion_tokens") for c in tanda)
    total_tokens = sum(_usage(c, "total_tokens") for c in tanda) or (prompt_tokens + completion_tokens)
    estimated_cost_usd = (
        round(total_tokens / 1_000_000 * price_per_million_tokens_usd, 4)
        if price_per_million_tokens_usd is not None else None
    )
    incidents = sorted(set(c.get("error") for c in calls if not c["ok"]))

    report = {
        "titulo": "ACUERDO-2: precision del subconjunto-acuerdo determinista ∧ NVIDIA sobre corpus NUEVO (medicion en SOMBRA)",
        "generado_por": "scripts/agreement/measure_agreement2.py",
        "split": SPLIT,
        "workspace": _WORKSPACE,
        "mock": mock,
        "gold": {"episodes": len(gold.episodes), "claims": len(gold.claims_for("extractor"))},
        "carriles": {
            "determinista": {"ablation": "local_only", "wall_ms": wall_det, "alineamiento": det_diag},
            "nvidia": {"ablation": "external_only", "wall_ms": wall_nvidia, "alineamiento": nvidia_diag},
        },
        "agreement": agreement,
        "latency": {
            "unit": "ms", "measured_calls": len(tanda), "real_calls_this_run": len(real_calls),
            "mean": round(statistics.mean(latencies), 1) if latencies else None,
            "p95": round(b3._percentile(latencies, 0.95), 1) if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "tokens": {
            "prompt_tokens_total": prompt_tokens, "completion_tokens_total": completion_tokens,
            "total_tokens": total_tokens, "price_per_million_tokens_usd": price_per_million_tokens_usd,
            "estimated_cost_usd_this_run": estimated_cost_usd,
        },
        "cache": {
            "path": str(cache_dir) if cache_dir else None, "calls_real": len(real_calls),
            "calls_failed": len(calls) - len(real_calls),
            "calls_served_from_cache": getattr(port, "hits", 0),
            "calls_missed_cache": getattr(port, "misses", 0),
        },
        "incidencias_api": {
            "transport_retries_used": getattr(metering.inner, "retries_used", 0) if hasattr(metering.inner, "retries_used") else 0,
            "hard_timeouts": getattr(metering.inner, "timeouts", 0) if hasattr(metering.inner, "timeouts") else 0,
            "failed_calls": len(calls) - len(real_calls),
            "distinct_errors": incidents,
        },
        "lectura_para_la_decision_del_operador": {
            "precision_acuerdo_contenido": agreement["acuerdo_contenido"]["precision"],
            "n_acuerdo_contenido": agreement["acuerdo_contenido"]["n"],
            "recall_acuerdo_contenido_sobre_gold": agreement["acuerdo_contenido"]["recall_sobre_gold"],
            "desglose_acuerdo_contenido_por_par_de_decisiones": agreement["acuerdo_contenido"]["desglose_por_par_de_decisiones"],
            "precision_acuerdo_con_accept_tautologico": agreement["acuerdo_con_accept"]["precision"],
            "n_acuerdo_con_accept_tautologico": agreement["acuerdo_con_accept"]["n"],
            "precision_solo_det": agreement["solo_det"]["precision"], "n_solo_det": agreement["solo_det"]["n"],
            "precision_solo_nvidia": agreement["solo_nvidia"]["precision"], "n_solo_nvidia": agreement["solo_nvidia"]["n"],
            "n_polaridades_opuestas_activas": agreement["discrepancia"]["polaridades_opuestas_activas"]["n"],
            "n_abstain_vs_afirma": agreement["discrepancia"]["abstain_vs_afirma"]["n"],
            "n_predicado_incompatible": agreement["discrepancia"]["predicado_incompatible"]["n"],
            "n_sin_cubrir": agreement["sin_cubrir"]["n"],
            "evaluable_total": agreement["evaluable_total"],
            "nota": (
                "corpus NUEVO (42 casos / 37 claims evaluables): frases y entidades "
                "nunca vistas en ningun otro split del repo. Ninguna cifra se "
                "escribe a mano. No se recomienda politica: eso es del operador."
            ),
        },
    }
    return report


def to_markdown(report: dict[str, Any]) -> str:
    ag = report["agreement"]
    lect = report["lectura_para_la_decision_del_operador"]
    lineas = [
        "# ACUERDO-2: medicion en sombra sobre corpus NUEVO (agreement-eval2)",
        "",
        f"Split: `{report['split']}` (workspace `{report['workspace']}`) -- "
        f"{report['gold']['claims']} claims / {report['gold']['episodes']} episodios "
        "(gold nuevo, verificado por hash). "
        f"Denominador evaluable: {ag['evaluable_total']}.",
        "",
        "Generado por `scripts/agreement/measure_agreement2.py`. Modo SOMBRA pura.",
        "",
        "## Vista PRINCIPAL: acuerdo a nivel de CONTENIDO, por par de decisiones",
        "",
        f"n={ag['acuerdo_contenido']['n']}, precision={ag['acuerdo_contenido']['precision']}, "
        f"recall sobre el gold={ag['acuerdo_contenido']['recall_sobre_gold']} "
        f"({ag['acuerdo_contenido']['n']}/{ag['evaluable_total']}).",
        "",
        "| par de decisiones (det/nvidia) | n | tp | fp | precision |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for pair, stats in ag["acuerdo_contenido"]["desglose_por_par_de_decisiones"].items():
        lineas.append(f"| {pair} | {stats['n']} | {stats['tp']} | {stats['fp']} | {stats['precision']} |")
    lineas += [
        "",
        "## Otros conjuntos",
        "",
        "| conjunto | n | tp | fp | precision |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| solo-det | {ag['solo_det']['n']} | {ag['solo_det']['tp']} | {ag['solo_det']['fp']} | {ag['solo_det']['precision']} |",
        f"| solo-nvidia | {ag['solo_nvidia']['n']} | {ag['solo_nvidia']['tp']} | {ag['solo_nvidia']['fp']} | {ag['solo_nvidia']['precision']} |",
        f"| discrepancia: polaridades opuestas ACTIVAS | {ag['discrepancia']['polaridades_opuestas_activas']['n']} | {ag['discrepancia']['polaridades_opuestas_activas']['tp']} | {ag['discrepancia']['polaridades_opuestas_activas']['fp']} | {ag['discrepancia']['polaridades_opuestas_activas']['precision']} |",
        f"| discrepancia: abstain vs afirma | {ag['discrepancia']['abstain_vs_afirma']['n']} | -- | -- | -- |",
        f"| discrepancia: predicado incompatible | {ag['discrepancia']['predicado_incompatible']['n']} | -- | -- | -- |",
        f"| sin_cubrir | {ag['sin_cubrir']['n']} | -- | -- | -- |",
        "",
        "## Casos: polaridades opuestas ACTIVAS",
        "",
        "| claim_id | det negated | nvidia negated | gold negated |",
        "| --- | --- | --- | --- |",
    ]
    for c in ag["discrepancia"]["polaridades_opuestas_activas"]["cases"]:
        lineas.append(f"| {c['claim_id']} | {c['det_negated']} | {c['nvidia_negated']} | {c['gold_negated']} |")
    lineas += [
        "",
        "## Casos: abstain vs afirma",
        "",
        "| claim_id | det decision | nvidia decision | det negated | nvidia negated | gold negated |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in ag["discrepancia"]["abstain_vs_afirma"]["cases"]:
        lineas.append(
            f"| {c['claim_id']} | {c['det_decision']} | {c['nvidia_decision']} | "
            f"{c['det_negated']} | {c['nvidia_negated']} | {c['gold_negated']} |"
        )
    lineas += [
        "",
        "## Coste / latencia / cache de la pasada NVIDIA",
        "",
        f"- llamadas medidas: {report['latency']['measured_calls']}",
        f"- reales en esta corrida: {report['latency']['real_calls_this_run']}",
        f"- latencia media: {report['latency']['mean']} ms, p95: {report['latency']['p95']} ms",
        f"- tokens totales: {report['tokens']['total_tokens']}",
        f"- servidas desde cache: {report['cache']['calls_served_from_cache']}",
        f"- llamadas fallidas: {report['cache']['calls_failed']}",
        f"- errores distintos: {report['incidencias_api']['distinct_errors'] or 'ninguno'}",
        "",
        "## Lectura para la decision del operador",
        "",
        f"- precision del acuerdo de CONTENIDO: {lect['precision_acuerdo_contenido']} (n={lect['n_acuerdo_contenido']})",
        f"- recall sobre el gold: {lect['recall_acuerdo_contenido_sobre_gold']} ({lect['n_acuerdo_contenido']}/{lect['evaluable_total']})",
        f"- precision solo-det: {lect['precision_solo_det']} (n={lect['n_solo_det']})",
        f"- precision solo-nvidia: {lect['precision_solo_nvidia']} (n={lect['n_solo_nvidia']})",
        f"- polaridades opuestas activas: {lect['n_polaridades_opuestas_activas']}",
        f"- abstain vs afirma: {lect['n_abstain_vs_afirma']}",
        f"- predicado incompatible: {lect['n_predicado_incompatible']}",
        f"- sin cubrir: {lect['n_sin_cubrir']}",
        f"- nota: {lect['nota']}",
    ]
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ACUERDO-2: medicion en sombra sobre el corpus nuevo agreement-eval2.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="agreement-eval2")
    parser.add_argument("--cache", default="artifacts/agreement/cache2")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=b3.EPISODE_TIMEOUT_SECONDS)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--price-per-million-tokens-usd", type=float, default=None)
    args = parser.parse_args(argv)

    if args.concurrency > 2:
        parser.error("--concurrency no puede superar 2 (para no gatillar rate limits de NVIDIA)")

    if not args.mock and os.environ.get("S9K_NVIDIA_API_KEY", "").strip() == "":
        print("ERROR: S9K_NVIDIA_API_KEY ausente en el entorno; usa --mock para probar sin red.", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache) if args.cache else None
    if cache_dir:
        cache_dir = cache_dir / "responses.json" if cache_dir.is_dir() or not cache_dir.suffix else cache_dir

    report = build_report(
        cache_dir=cache_dir, mock=args.mock, timeout_seconds=args.timeout_seconds,
        concurrency=args.concurrency, price_per_million_tokens_usd=args.price_per_million_tokens_usd,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.out_name}.json").write_text(payload, encoding="utf-8")
        (out / f"{args.out_name}.md").write_text(to_markdown(report), encoding="utf-8")
        print(f"escrito en {out}/{args.out_name}.{{json,md}}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
