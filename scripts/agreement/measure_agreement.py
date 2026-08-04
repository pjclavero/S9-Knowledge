# -*- coding: utf-8 -*-
"""Medicion en SOMBRA de la precision del subconjunto-acuerdo determinista∧NVIDIA.

Pregunta del bloque (encargo del operador): sobre el MISMO gold congelado de la
puerta 4 (split `negation`, 57 claims / 56 casos evaluables), si el carril
DETERMINISTA (ablacion `local_only`, la cadena E2E real -- normalizador,
`extraction/cues.py`, motor, resolutor, writer en DRY-RUN -- la misma que mide
el 0.607 de B2) y el carril NVIDIA (ablacion `external_only`) llegan
INDEPENDIENTEMENTE al MISMO claim (mismo sujeto/objeto, predicado compatible,
evidencia anclada), ¿que tan fiable es ese subconjunto de acuerdo? Y que
fraccion del gold cubre.

Este script es SOMBRA PURA: el writer de `pipeline.runner.run_one` va siempre
en DRY-RUN (sin bandera que lo cambie), no decide ninguna politica y no toca
el gold (`load_dev_gold(verify=True)` lo verifica por hash antes de leerlo).

## Hallazgo de diseno que dicta como esta escrito este script

La primera version de este script uso `benchmarks.harness.score_extractor`
(via `pipeline.bundle.to_bundle`) para emparejar los claims predichos con el
gold, igual que hace `measure_b3.py`. Con la cadena E2E real (`local_only`,
`entry="raw"`) esa via da **cobertura estructuralmente cero**: el normalizador
acuna sus propios `episode_id` (`ep-<hash>`) a partir de los BYTES de entrada,
y `score_extractor` exige coincidencia EXACTA de `episode_id` para emparejar
menciones (`benchmarks.matching.match_spans`, `span_mode="exact"`). El
runner E2E CONGELADO que mide el 0.607 real de B2 (`artifacts/v3-final-
validation/gate4_negation_measure.py`) NO tiene este problema porque **nunca
usa `score_extractor`**: implementa su PROPIO alineamiento en tres fases
(`episode_alignment` por texto literal, `mention_alignment` por span + fallback
de superficie, `claim_alignment` por menciones-gold traducidas) precisamente
para resolver este desajuste estructural. Reimplementarlo hubiera sido
duplicar ~150 lineas ya escritas, revisadas y con tests propios; en su lugar,
este script IMPORTA esas tres funciones (mas `build_rows`, que arma una fila
por claim gold evaluable con la decision REAL del motor: `ACCEPT` / `REVIEW`
/ `REJECT` / sin cobertura) desde el runner congelado, vía
`knowledge_v3.eval._frozen_runner.load()` -- el MISMO cargador-por-ruta que ya
usan `dev_corpus.py` y `harness.py` para no fijar el nombre del split a mano.
Nunca se importa el runner como paquete ni se copia una linea de su codigo;
se usa por ruta, de solo lectura, exactamente como el resto del repo ya hace.

Consecuencia importante para la lectura de esta medicion: la fila de cada
carril trae `predicted_decision` -- el veredicto REAL del motor
(`engine/decision.py`), que YA incorpora la conexion de la puerta 6
(`review_required` + `epistemic_status_hint` degradado -> nunca `ACCEPT`,
ver docs/v3/46 P0) y la verificacion de evidencia literal
(`EVIDENCE_LITERAL_VERIFIED`). Por eso el criterio de ACUERDO de este bloque
usa `predicted_decision == "ACCEPT"` en AMBOS carriles como el filtro de
factividad+evidencia-anclada: es la MISMA puerta que ya usa produccion para
decidir si un claim se escribiria, no una reimplementacion paralela de esa
regla.

## Lo que se REUTILIZA (nada de esto es nuevo aqui)

* `knowledge_v3.eval.dev_corpus.load_dev_gold` -- el gold congelado (split
  `negation`), verificado por hash.
* `knowledge_v3.pipeline.runner.run_one` -- la via DESIGNADA en B3-gate4
  (docs/v3/40) para correr la cadena COMPLETA con un proveedor externo sobre
  el MISMO split, demostrada por `test_gate4_b3_adversarial.py`. Se invoca
  dos veces: `ablation="local_only"` (determinista real) y
  `ablation="external_only"` (NVIDIA), ambas `entry="raw"`, MISMO workspace
  que usa el runner congelado (`bench-negation`).
* `scripts.gate4.measure_b3.make_b3_port` -- retry/metering/cache del carril
  NVIDIA (backoff exponencial, timeout duro, cache en disco por hash de
  peticion). Reutilizado TAL CUAL: este script no reimplementa transporte.
* El runner E2E congelado (via `_frozen_runner.load()`, de solo lectura):
  `episode_alignment`, `mention_alignment`, `claim_alignment`, `build_rows`
  -- el alineamiento de tres fases y la fila-por-claim con la decision real
  del motor, exactamente como los usa `analyse()` para medir B0-B2.

## Lo que este script SI anade

* La particion de las filas de AMBOS carriles (alineadas al MISMO
  `gold_claim_id`, el sistema de coordenadas comun) en 4 conjuntos: acuerdo,
  solo-det, solo-nvidia, discrepancia -- mas un quinto conjunto de
  diagnostico (`degradado_no_acuerdo`) para los casos que coinciden en
  sujeto/objeto/polaridad pero que el motor NO aceptaria en al menos un
  carril (factividad o evidencia).
* Precision y recall del conjunto ACUERDO contra el gold (la metrica
  estrella del bloque), con el listado completo de casos de discrepancia.

Uso (desde la raiz del repo):

    export S9K_NVIDIA_ENABLED=true
    export S9K_NVIDIA_API_KEY=...   # nunca en la linea de comandos ni commiteada
    PYTHONPATH=data-engine/app python3 scripts/agreement/measure_agreement.py \
        --out-dir artifacts/agreement --out-name agreement-shadow \
        --cache artifacts/gate4-program/b3-cache --concurrency 2

`--mock` sustituye NVIDIA por un puerto guionizado (sin red, sin key): sirve
para probar el script y para los tests unitarios.
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
for _p in (_APP, _GATE4_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import measure_b3 as b3  # noqa: E402 -- reutiliza make_b3_port y _percentile

from knowledge_v3.benchmarks.matching import MatchConfig  # noqa: E402
from knowledge_v3.eval import _frozen_runner as _fr  # noqa: E402
from knowledge_v3.eval.dev_corpus import load_dev_gold  # noqa: E402
from knowledge_v3.pipeline.runner import run_one  # noqa: E402

#: Split y workspace, leidos del runner congelado (nunca escritos aqui a
#: mano -- misma disciplina que `measure_b3.py` y `dev_corpus.py`).
_FROZEN = _fr.load()
SPLIT = str(_FROZEN.SPLIT)
_WORKSPACE = str(_FROZEN.WORKSPACE)

#: Configuracion de emparejamiento: LA MISMA que usa `analyse()` en el runner
#: congelado (span en modo overlap, sin componentes extra en la clave del
#: claim). Copiar los VALORES, no el objeto: `MatchConfig` es inmutable y
#: publico, y construir uno propio con los mismos parametros no es indirectar
#: sobre estado interno del runner, es declarar el mismo contrato.
def _match_config(gold) -> MatchConfig:
    return MatchConfig(
        span_mode="overlap",
        overlap_threshold=0.5,
        claim_key_extra=(),
        symmetric_predicates=gold.symmetric_predicates,
    )


# --------------------------------------------------------------------------
# Vista por carril: gold_claim_id -> fila real del motor (via runner congelado)
# --------------------------------------------------------------------------
def _lane_rows(gold, result, config: MatchConfig) -> dict[str, dict[str, Any]]:
    """Filas por claim gold, alineadas y puntuadas con las funciones REALES
    del runner congelado (`episode_alignment` / `mention_alignment` /
    `claim_alignment` / `build_rows`), aplicadas al `PipelineResult` de ESTE
    carril. Ver el docstring del modulo: es la unica via que no tropieza con
    el desajuste de `episode_id` entre el normalizador y el gold.
    """
    episodes = _FROZEN.episode_alignment(gold, result)
    mentions, mention_match, fallback = _FROZEN.mention_alignment(gold, result, episodes, config)
    pairs, _claim_match = _FROZEN.claim_alignment(gold, result, mentions)
    rows = _FROZEN.build_rows(gold, result, pairs)
    by_id = {r["gold_claim_id"]: r for r in rows}
    diag = {
        "episodes_aligned": len(episodes),
        "episodes_predicted": len(result.episodes),
        "mentions_span_tp": mention_match.tp,
        "mentions_span_fp": mention_match.fp,
        "mentions_span_fn": mention_match.fn,
        "mentions_surface_fallback": fallback,
        "claims_matched": len(pairs),
        "rows": len(rows),
        "covered_rows": sum(1 for r in rows if r["covered"]),
    }
    return by_id, diag


def _predicate_compatible(det: dict[str, Any], nvidia: dict[str, Any]) -> bool:
    """Predicado top-1 de cada carril (post-motor: `predicted_predicate`).

    Si alguno de los dos carriles no cubrio el caso con predicado resuelto
    (`None`), se declara compatible-por-omision: la incompatibilidad solo se
    puede afirmar cuando AMBOS carriles se comprometen a un predicado y
    difieren -- limitacion explicita, no un acierto fabricado (docs/v3/47).
    """
    dp, np_ = det.get("predicted_predicate"), nvidia.get("predicted_predicate")
    if dp is None or np_ is None:
        return True
    return dp == np_


# --------------------------------------------------------------------------
# Los 4 (+1 diagnostico) conjuntos
# --------------------------------------------------------------------------
def compute_agreement(det_rows: dict[str, Any], nvidia_rows: dict[str, Any]) -> dict[str, Any]:
    gold_ids = sorted(det_rows.keys())
    assert gold_ids == sorted(nvidia_rows.keys()), (
        "los dos carriles corren sobre el MISMO gold: el conjunto de "
        "claim_id evaluables no puede diferir entre carriles"
    )

    acuerdo: list[dict[str, Any]] = []
    solo_det: list[dict[str, Any]] = []
    solo_nvidia: list[dict[str, Any]] = []
    discrepancia: list[dict[str, Any]] = []
    degradado_no_acuerdo: list[dict[str, Any]] = []
    sin_cubrir: list[str] = []

    for gid in gold_ids:
        d, n = det_rows[gid], nvidia_rows[gid]
        gold_negated = d["expected_negated"]  # identico en ambas filas: mismo gold

        if not d["covered"] and not n["covered"]:
            sin_cubrir.append(gid)
            continue
        if d["covered"] and not n["covered"]:
            solo_det.append({
                "claim_id": gid,
                "negated": d["predicted_negated"],
                "decision": d["predicted_decision"],
                "correct": d["predicted_negated"] == gold_negated,
            })
            continue
        if n["covered"] and not d["covered"]:
            solo_nvidia.append({
                "claim_id": gid,
                "negated": n["predicted_negated"],
                "decision": n["predicted_decision"],
                "correct": n["predicted_negated"] == gold_negated,
            })
            continue

        # Ambos carriles cubren el mismo claim gold.
        same_polarity = d["predicted_negated"] == n["predicted_negated"]
        pred_ok = _predicate_compatible(d, n)
        both_accept = d["predicted_decision"] == "ACCEPT" and n["predicted_decision"] == "ACCEPT"

        case = {
            "claim_id": gid,
            "det_negated": d["predicted_negated"],
            "nvidia_negated": n["predicted_negated"],
            "det_decision": d["predicted_decision"],
            "nvidia_decision": n["predicted_decision"],
            "det_predicate": d["predicted_predicate"],
            "nvidia_predicate": n["predicted_predicate"],
            "gold_negated": gold_negated,
        }

        if same_polarity and pred_ok:
            if both_accept:
                case["correct"] = d["predicted_negated"] == gold_negated
                acuerdo.append(case)
            else:
                # Mismo sujeto/objeto/polaridad, pero el motor NO aceptaria
                # (al menos) uno de los dos: REVIEW/REJECT por factividad
                # degradada o evidencia no verificada. Por diseno de la
                # puerta 6, esto NUNCA entra en acuerdo.
                case["reason"] = f"det={d['predicted_decision']} nvidia={n['predicted_decision']}"
                degradado_no_acuerdo.append(case)
        else:
            case["reason"] = "polaridad_incompatible" if not same_polarity else "predicado_incompatible"
            discrepancia.append(case)

    def _set_stats(cases: list[dict[str, Any]]) -> dict[str, Any]:
        tp = sum(1 for c in cases if c.get("correct"))
        fp = sum(1 for c in cases if c.get("correct") is False)
        n_cases = len(cases)
        return {"n": n_cases, "tp": tp, "fp": fp, "precision": round(tp / n_cases, 4) if n_cases else None}

    evaluable_total = len(gold_ids)
    return {
        "evaluable_total": evaluable_total,
        "acuerdo": {
            **_set_stats(acuerdo), "cases": acuerdo,
            "recall_sobre_gold": round(len(acuerdo) / evaluable_total, 4) if evaluable_total else None,
        },
        "solo_det": {**_set_stats(solo_det), "cases": solo_det},
        "solo_nvidia": {**_set_stats(solo_nvidia), "cases": solo_nvidia},
        "discrepancia": {
            "n": len(discrepancia),
            "cases": discrepancia,
            "nota": (
                "mismo claim_id gold (sujeto/objeto), pero polaridad o "
                "predicado incompatibles entre carriles; no hay una "
                "'precision' unica del conjunto porque cada carril acierta o "
                "falla por separado -- ver `gold_negated` de cada caso."
            ),
        },
        "degradado_no_acuerdo": {
            "n": len(degradado_no_acuerdo),
            "cases": degradado_no_acuerdo,
            "nota": (
                "mismo claim_id gold y misma polaridad entre carriles, pero "
                "excluido de ACUERDO porque el motor NO aceptaria (ACCEPT) "
                "el claim en al menos un carril -- REVIEW o REJECT reales por "
                "factividad degradada (puerta 6) o evidencia no verificada. "
                "Muestra cuanto 'acuerdo de polaridad' pierde la politica al "
                "exigir el mismo filtro que ya usa produccion."
            ),
        },
        "sin_cubrir": {"n": len(sin_cubrir), "claim_ids": sin_cubrir},
    }


# --------------------------------------------------------------------------
# Ejecucion de punta a punta
# --------------------------------------------------------------------------
def build_report(
    *,
    cache_dir: Optional[Path],
    mock: bool,
    timeout_seconds: int,
    concurrency: int,
    price_per_million_tokens_usd: Optional[float],
) -> dict[str, Any]:
    gold = load_dev_gold(verify=True)
    match_config = _match_config(gold)

    # --- carril determinista: cadena E2E real (misma via que mide 0.607) ---
    started_det = time.monotonic()
    _report_det, result_det = run_one(
        gold, "local_only", workspace=_WORKSPACE, entry="raw", run_id=f"agreement-{SPLIT}-local"
    )
    wall_det = int((time.monotonic() - started_det) * 1000)
    det_rows, det_diag = _lane_rows(gold, result_det, match_config)

    # --- carril NVIDIA: mismo puerto instrumentado que B3 --------------------
    port, metering = b3.make_b3_port(cache_dir=cache_dir, mock=mock, timeout_seconds=timeout_seconds)
    started_nvidia = time.monotonic()
    _report_nvidia, result_nvidia = run_one(
        gold, "external_only", workspace=_WORKSPACE, entry="raw",
        run_id=f"agreement-{SPLIT}-external", external_port=port,
    )
    wall_nvidia = int((time.monotonic() - started_nvidia) * 1000)
    nvidia_rows, nvidia_diag = _lane_rows(gold, result_nvidia, match_config)

    agreement = compute_agreement(det_rows, nvidia_rows)

    # --- coste/latencia/cache de la pasada NVIDIA (mismo vocabulario que B3) -
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
        if price_per_million_tokens_usd is not None
        else None
    )
    incidents = sorted(set(c.get("error") for c in calls if not c["ok"]))

    report = {
        "titulo": "Precision del subconjunto-acuerdo determinista ∧ NVIDIA (medicion en SOMBRA)",
        "generado_por": "scripts/agreement/measure_agreement.py",
        "split": SPLIT,
        "workspace": _WORKSPACE,
        "mock": mock,
        "gold": {"episodes": len(gold.episodes), "claims": len(gold.claims_for("extractor"))},
        "carriles": {
            "determinista": {
                "ablation": "local_only",
                "nota": "cadena E2E real (normalizador + cues.py + motor + resolutor + writer DRY-RUN), la MISMA via que mide el 0.607 de B2.",
                "wall_ms": wall_det,
                "alineamiento": det_diag,
            },
            "nvidia": {
                "ablation": "external_only",
                "nota": "carril NVIDIA en SOMBRA (nunca escribe, nunca decide), por la MISMA cadena E2E (motor, negacion, evidencia).",
                "wall_ms": wall_nvidia,
                "alineamiento": nvidia_diag,
            },
        },
        "diseno": {
            "criterio_acuerdo": (
                "mismo claim_id del gold (alineado via episode_alignment + "
                "mention_alignment + claim_alignment del runner congelado, "
                "reutilizados por ruta), predicado top-1 compatible (o "
                "ausente en algun carril), MISMA polaridad, Y AMBOS carriles "
                "con predicted_decision=='ACCEPT' -- el veredicto REAL del "
                "motor (engine/decision.py), que ya incorpora la puerta 6 "
                "(review_required + hint epistemico degradado nunca ACCEPT) "
                "y la verificacion de evidencia literal."
            ),
            "factividad": (
                "un claim que el motor no aceptaria (REVIEW o REJECT reales) "
                "en CUALQUIERA de los dos carriles NUNCA entra en acuerdo, "
                "aunque ambos coincidan en polaridad: va a "
                "'degradado_no_acuerdo', no a 'acuerdo'. Es la MISMA puerta "
                "que produccion, no una reimplementacion paralela."
            ),
            "denominador": "56 casos evaluables (convencion B0-B3: se excluye el unico ABSTAIN puro del gold, sin polaridad declarada).",
            "alineamiento_reutilizado": (
                "episode_alignment/mention_alignment/claim_alignment/build_rows "
                "del runner E2E congelado (artifacts/v3-final-validation/"
                "gate4_negation_measure.py), cargado por ruta via "
                "knowledge_v3.eval._frozen_runner.load() -- nunca copiado ni "
                "modificado. Necesario porque score_extractor (benchmarks."
                "harness) exige episode_id identico y la cadena real acuna "
                "ids propios a partir de los bytes de entrada; ver docstring "
                "del modulo."
            ),
        },
        "agreement": agreement,
        "latency": {
            "unit": "ms",
            "measured_calls": len(tanda),
            "real_calls_this_run": len(real_calls),
            "mean": round(statistics.mean(latencies), 1) if latencies else None,
            "p95": round(b3._percentile(latencies, 0.95), 1) if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "tokens": {
            "prompt_tokens_total": prompt_tokens,
            "completion_tokens_total": completion_tokens,
            "total_tokens": total_tokens,
            "price_per_million_tokens_usd": price_per_million_tokens_usd,
            "estimated_cost_usd_this_run": estimated_cost_usd,
        },
        "cache": {
            "path": str(cache_dir) if cache_dir else None,
            "calls_real": len(real_calls),
            "calls_failed": len(calls) - len(real_calls),
            "calls_served_from_cache": getattr(port, "hits", 0),
            "calls_missed_cache": getattr(port, "misses", 0),
        },
        "incidencias_api": {
            "transport_retries_used": getattr(metering.inner, "retries_used", 0)
            if hasattr(metering.inner, "retries_used") else 0,
            "hard_timeouts": getattr(metering.inner, "timeouts", 0)
            if hasattr(metering.inner, "timeouts") else 0,
            "failed_calls": len(calls) - len(real_calls),
            "distinct_errors": incidents,
        },
        "lectura_para_la_decision_del_operador": {
            "precision_acuerdo": agreement["acuerdo"]["precision"],
            "n_acuerdo": agreement["acuerdo"]["n"],
            "recall_acuerdo_sobre_gold": agreement["acuerdo"]["recall_sobre_gold"],
            "precision_solo_det": agreement["solo_det"]["precision"],
            "n_solo_det": agreement["solo_det"]["n"],
            "precision_solo_nvidia": agreement["solo_nvidia"]["precision"],
            "n_solo_nvidia": agreement["solo_nvidia"]["n"],
            "n_discrepancia": agreement["discrepancia"]["n"],
            "n_degradado_no_acuerdo": agreement["degradado_no_acuerdo"]["n"],
            "n_sin_cubrir": agreement["sin_cubrir"]["n"],
            "evaluable_total": agreement["evaluable_total"],
            "nota": (
                "cifras desnudas, sin recomendacion de politica: esa decision "
                "es del operador. n=56 evaluables es el mismo techo pequeno que "
                "ya declaro el programa de la puerta 4 (dev==test): cualquier "
                "precision de un subconjunto de este tamano tiene un intervalo "
                "ancho, no se trata como una cifra poblacional."
            ),
        },
    }
    return report


def to_markdown(report: dict[str, Any]) -> str:
    ag = report["agreement"]
    lect = report["lectura_para_la_decision_del_operador"]
    lineas = [
        "# Medicion en sombra: precision del subconjunto-acuerdo determinista ∧ NVIDIA",
        "",
        f"Split: `{report['split']}` (workspace `{report['workspace']}`) -- "
        f"{report['gold']['claims']} claims / {report['gold']['episodes']} episodios "
        "(gold congelado, verificado por hash). "
        f"Denominador evaluable: {ag['evaluable_total']} (convencion B0-B3).",
        "",
        "Generado por `scripts/agreement/measure_agreement.py`. Ninguna cifra de este",
        "documento se escribe a mano. Modo SOMBRA pura: ningun carril escribe en Neo4j",
        "ni decide politica; esto SOLO mide.",
        "",
        "## Los 4 (+1 diagnostico) conjuntos",
        "",
        "| conjunto | n | tp | fp | precision |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| acuerdo | {ag['acuerdo']['n']} | {ag['acuerdo']['tp']} | {ag['acuerdo']['fp']} | {ag['acuerdo']['precision']} |",
        f"| solo-det | {ag['solo_det']['n']} | {ag['solo_det']['tp']} | {ag['solo_det']['fp']} | {ag['solo_det']['precision']} |",
        f"| solo-nvidia | {ag['solo_nvidia']['n']} | {ag['solo_nvidia']['tp']} | {ag['solo_nvidia']['fp']} | {ag['solo_nvidia']['precision']} |",
        f"| discrepancia | {ag['discrepancia']['n']} | -- | -- | (ver nota) |",
        f"| degradado_no_acuerdo (fuera del acuerdo por factividad/evidencia) | {ag['degradado_no_acuerdo']['n']} | -- | -- | -- |",
        f"| sin_cubrir (ningun carril propuso nada emparejable) | {ag['sin_cubrir']['n']} | -- | -- | -- |",
        "",
        f"**Recall del acuerdo sobre el gold**: {ag['acuerdo']['recall_sobre_gold']} "
        f"({ag['acuerdo']['n']}/{ag['evaluable_total']} casos evaluables).",
        "",
        "## Diseno",
        "",
        f"- criterio de acuerdo: {report['diseno']['criterio_acuerdo']}",
        f"- factividad (puerta 6): {report['diseno']['factividad']}",
        f"- alineamiento reutilizado: {report['diseno']['alineamiento_reutilizado']}",
        "",
        "## Casos de discrepancia (diagnostico)",
        "",
        "| claim_id | det negated | nvidia negated | gold negated | razon |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in ag["discrepancia"]["cases"]:
        lineas.append(
            f"| {c['claim_id']} | {c['det_negated']} | {c['nvidia_negated']} | {c['gold_negated']} | {c['reason']} |"
        )
    lineas += [
        "",
        "## Casos excluidos por factividad/evidencia (mismo sujeto/objeto/polaridad, sin ACCEPT en ambos)",
        "",
        "| claim_id | det decision | nvidia decision |",
        "| --- | --- | --- |",
    ]
    for c in ag["degradado_no_acuerdo"]["cases"]:
        lineas.append(f"| {c['claim_id']} | {c['det_decision']} | {c['nvidia_decision']} |")
    lineas += [
        "",
        "## Coste / latencia / cache de la pasada NVIDIA",
        "",
        f"- llamadas medidas (tanda completa): {report['latency']['measured_calls']}",
        f"- reales en esta corrida: {report['latency']['real_calls_this_run']}",
        f"- latencia media: {report['latency']['mean']} ms, p95: {report['latency']['p95']} ms",
        f"- tokens totales: {report['tokens']['total_tokens']}",
        f"- servidas desde cache: {report['cache']['calls_served_from_cache']}",
        f"- llamadas reales (miss de cache): {report['cache']['calls_missed_cache']}",
        f"- llamadas fallidas: {report['cache']['calls_failed']}",
        f"- reintentos de transporte: {report['incidencias_api']['transport_retries_used']}",
        f"- timeouts duros: {report['incidencias_api']['hard_timeouts']}",
        f"- errores distintos: {report['incidencias_api']['distinct_errors'] or 'ninguno'}",
        "",
        "## Lectura para la decision del operador (cifras desnudas, sin recomendacion)",
        "",
        f"- precision del acuerdo: {lect['precision_acuerdo']} (n={lect['n_acuerdo']})",
        f"- recall del acuerdo sobre el gold: {lect['recall_acuerdo_sobre_gold']} ({lect['n_acuerdo']}/{lect['evaluable_total']})",
        f"- precision solo-det: {lect['precision_solo_det']} (n={lect['n_solo_det']})",
        f"- precision solo-nvidia: {lect['precision_solo_nvidia']} (n={lect['n_solo_nvidia']})",
        f"- discrepancias: {lect['n_discrepancia']}",
        f"- excluidos del acuerdo por factividad/evidencia pese a coincidir en polaridad: {lect['n_degradado_no_acuerdo']}",
        f"- sin cubrir por ningun carril: {lect['n_sin_cubrir']}",
        f"- nota: {lect['nota']}",
    ]
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Medicion en sombra del subconjunto-acuerdo determinista+NVIDIA.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="agreement-shadow")
    parser.add_argument("--cache", default="artifacts/gate4-program/b3-cache", help="dir de cache JSON (compartida con B3 para maximizar hits)")
    parser.add_argument("--mock", action="store_true", help="puerto guionizado (sin red, sin key)")
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
        cache_dir=cache_dir,
        mock=args.mock,
        timeout_seconds=args.timeout_seconds,
        concurrency=args.concurrency,
        price_per_million_tokens_usd=args.price_per_million_tokens_usd,
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
