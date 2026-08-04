# -*- coding: utf-8 -*-
"""Puerta 4, bloque B3: que aporta un carril semantico REAL (NVIDIA) en SOMBRA.

Pregunta del bloque: sobre el MISMO gold congelado de la puerta 4 (split
`negation`, 57 claims / 56 casos evaluables que ya miden B0-B2), si se anade un
carril semantico apoyado en NVIDIA NIM (`meta/llama-3.3-70b-instruct`) junto al
extractor determinista, ¿sube la cobertura y el recall de la familia SIMPLE sin
romper la precision? El carril NVIDIA es SIEMPRE SOMBRA: se compara contra el
gold y contra el determinista, nunca escribe en Neo4j, nunca decide, nunca se
activa en produccion. Ese contrato lo cumple el extractor semantico y su
reconciliador, que este script REUTILIZA en vez de reimplementar (ver
`test_b3_shadow_no_writer.py`).

Lo que se REUTILIZA sin tocar una linea:

* `knowledge_v3.eval.dev_corpus.load_dev_gold` -- el MISMO gold verificado por
  hash que usan `measure.py`/`measure_b2.py` (split `negation`, congelado).
* `knowledge_v3.extraction.semantic_bench` -- `build_context`, `run_config`,
  `score`, `to_bundle` y `CachingPort`: el carril semantico episodico agnostico
  del proveedor (config `A` = determinista, `C2` = NVIDIA) y la UNION
  reconciliada (`D` + `D-R` via `knowledge_v3.reconcile.ProposalReconciler`,
  el MISMO reconciliador de fusion coreferente que uso B2).
* `knowledge_v3.extraction.provider_port.NvidiaProviderPort` y
  `external_processing.providers.nvidia.NvidiaProcessingProvider` -- el cliente
  HTTP NVIDIA ya implementado, auditado y saneado de secretos (nunca se abre un
  socket propio aqui).
* `knowledge_v3.benchmarks.matching` -- el emparejamiento gold/prediccion, para
  el desglose por familia que el arnes generico no trae.

Lo que este script SI anade (no existia antes de B3):

* Metering del carril NVIDIA (latencia real por llamada, p95, tokens de
  entrada/salida, llamadas reales vs servidas desde cache) -- `MeteringPort`.
* Reintentos con backoff exponencial ante fallos transitorios del transporte
  (429/5xx/timeout ya vienen mapeados a `ProviderUnavailable` por el puerto) y
  timeout duro por episodio -- `RetryingPort`.
* Cache en disco de las respuestas NVIDIA por hash de peticion (SIN la key en
  ningun campo), para que repetir la medicion no vuelva a facturar.
* La lectura de puertas en vocabulario de la puerta 4 (cobertura, recall de la
  familia SIMPLE, precision, falsos positivos) para las TRES vistas: NVIDIA
  sola, determinista solo, union reconciliada -- `family_recall`, `b3_gates`.

Uso (desde la raiz del repo, con la API key en el entorno -- nunca en la
linea de comandos ni en un fichero versionado):

    export S9K_NVIDIA_ENABLED=true
    export S9K_NVIDIA_API_KEY=...   # nunca se imprime ni se commitea
    PYTHONPATH=data-engine/app python3 scripts/gate4/measure_b3.py \
        --out-dir artifacts/gate4-program --out-name b3-nvidia-shadow \
        --cache artifacts/gate4-program/b3-cache --concurrency 2

`--mock` sustituye NVIDIA por un puerto guionizado (sin red, sin key): sirve
para probar el script y para los tests unitarios.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

_APP = Path(__file__).resolve().parents[2] / "data-engine" / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from knowledge_v3.benchmarks.matching import (
    MatchConfig,
    build_alignment,
    claim_key,
    match_by_key,
    match_spans,
)
from knowledge_v3.benchmarks.loader import GoldDataset, index_by
from knowledge_v3.eval.dev_corpus import load_dev_gold
from knowledge_v3.extraction import semantic_bench as bench
from knowledge_v3.extraction.provider_port import (
    MockProviderPort,
    NvidiaProviderPort,
    ProviderPortError,
    ProviderReply,
    ProviderRequest,
    ProviderUnavailable,
)

#: Split que mide este bloque: el MISMO que B0-B2. El nombre NO se escribe
#: aqui como literal: se lee del runner E2E congelado, exactamente igual que
#: hace `knowledge_v3.eval.dev_corpus` y por la misma razon que impone
#: `test_knowledge_v3_negation_battery.py::test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico`
#: -- enchufar la bateria a un flujo debe ser una decision visible, nunca el
#: efecto colateral de copiar una cadena.
from knowledge_v3.eval import _frozen_runner as _fr  # noqa: E402

SPLIT = _fr.dev_split_name()

#: Familias del gold de negacion (identicas a las de `eval/harness.py`).
_MECHANICAL_FAMILIES = {"SIMPLE", "NEVER", "CESSATION", "NOT_YET"}
_REVIEW_FAMILIES = {"NEGATED_CESSATION", "SCOPE_EMBEDDED", "DOUBLE_NEGATION"}
_SIMPLE_FAMILY = "SIMPLE"

#: Umbrales del programa (mismo documento de encargo que B0-B2). B3 no cambia
#: el liston: mide si el carril NVIDIA ayuda a alcanzarlo, no lo redefine.
UMBRAL_COBERTURA_DEV = 0.60
UMBRAL_RECALL_SIMPLE = 0.70

#: Reintentos del transporte. El puerto ya mapea 429/5xx/timeout a
#: `ProviderUnavailable` (ver `provider_port.NvidiaProviderPort`); aqui solo se
#: decide CUANTAS veces reintentar y cuanto esperar entre intentos.
MAX_TRANSPORT_RETRIES = 4
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
EPISODE_TIMEOUT_SECONDS = 60


# --------------------------------------------------------------------------
# Puertos de instrumentacion (nuevos en B3; el transporte NO es nuevo)
# --------------------------------------------------------------------------
class RetryingPort:
    """Envuelve un `ProviderPort` con backoff exponencial y timeout duro.

    Reintenta SOLO `ProviderUnavailable` (fallo de transporte: red, 429, 5xx,
    timeout -- ver `NvidiaProviderPort.complete_json`). Un `ProviderBadJSON`
    (el modelo contesto pero mal) no se reintenta aqui: eso ya lo gestiona el
    propio puerto (`json_retries`) y reintentarlo otra vez seria pagar una
    llamada mas por un problema que un reintento adicional no arregla.
    """

    def __init__(self, inner: Any, *, max_retries: int = MAX_TRANSPORT_RETRIES,
                 base_backoff: float = BASE_BACKOFF_SECONDS,
                 max_backoff: float = MAX_BACKOFF_SECONDS,
                 timeout_seconds: int = EPISODE_TIMEOUT_SECONDS,
                 sleep: Any = time.sleep) -> None:
        self.inner = inner
        self.provider = inner.provider
        self.model = inner.model
        self.name = getattr(inner, "name", "retrying")
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep
        self.retries_used = 0
        self.timeouts = 0
        self.transport_errors: list[str] = []

    def _backoff(self, attempt: int) -> float:
        return min(self._base_backoff * (2 ** attempt), self._max_backoff)

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        last: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.inner.complete_json, request)
                try:
                    return future.result(timeout=self._timeout_seconds)
                except concurrent.futures.TimeoutError:
                    self.timeouts += 1
                    last = ProviderUnavailable(
                        f"timeout duro de {self._timeout_seconds}s en el episodio"
                    )
                    self.transport_errors.append("EPISODE_TIMEOUT")
                except ProviderUnavailable as exc:
                    last = exc
                    self.transport_errors.append(str(exc))
                # ProviderBadJSON y cualquier otro ProviderPortError suben tal
                # cual: no son transitorios, reintentarlos no cambia nada.
            if attempt < self._max_retries:
                self.retries_used += 1
                self._sleep(self._backoff(attempt))
        raise last or ProviderUnavailable("reintentos agotados sin respuesta")


class MeteringPort:
    """Mide cada llamada REAL (nunca las servidas desde cache, que van fuera).

    Se coloca DEBAJO de `CachingPort`: un acierto de cache no pasa por aqui,
    asi que `self.calls` cuenta exactamente las llamadas que se facturaron.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.provider = inner.provider
        self.model = inner.model
        self.name = getattr(inner, "name", "metered")
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        started = time.monotonic()
        try:
            reply = self.inner.complete_json(request)
        except ProviderPortError as exc:
            self.calls.append({
                "purpose": request.purpose,
                "ok": False,
                "error": type(exc).__name__,
                "wall_ms": int((time.monotonic() - started) * 1000),
            })
            raise
        usage = reply.usage or {}
        self.calls.append({
            "purpose": request.purpose,
            "ok": True,
            "latency_ms": reply.latency_ms,
            "wall_ms": int((time.monotonic() - started) * 1000),
            "attempts": reply.attempts,
            "json_retries": reply.json_retries,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        })
        return reply


def make_b3_port(*, cache_dir: Optional[Path], mock: bool, timeout_seconds: int) -> tuple[Any, MeteringPort]:
    """Construye el puerto NVIDIA en sombra: metering -> reintentos -> cache."""
    if mock:
        base: Any = MockProviderPort()
        metering = MeteringPort(base)
        return bench.CachingPort(metering, cache_dir), metering

    from external_processing.providers.nvidia import NvidiaProcessingProvider

    repo_root = Path(__file__).resolve().parents[2]
    client = NvidiaProcessingProvider(repo_root, timeout_seconds=timeout_seconds)
    base = NvidiaProviderPort(client=client, repo_root=str(repo_root))
    retrying = RetryingPort(base, timeout_seconds=timeout_seconds)
    metering = MeteringPort(retrying)
    cached = bench.CachingPort(metering, cache_dir)
    return cached, metering


# --------------------------------------------------------------------------
# Metricas en vocabulario de la puerta 4 (cobertura / recall SIMPLE / FP)
# --------------------------------------------------------------------------
def _family_match(gold: GoldDataset, bundle, config: MatchConfig):
    # Igual que `semantic_bench.block_metrics`: primero se emparejan MENCIONES
    # (mismo span exacto), y esa alineacion pred->gold es la que traduce las
    # menciones de un claim predicho a menciones gold antes de comparar claves
    # de claim. Sin este paso, `claim_key` no encuentra correspondencia y
    # cuenta cualquier claim predicho como "no evaluable" -- justo el sesgo
    # que este arnes existe para no cometer.
    gold_m = index_by(gold.mentions, "mention_id")
    mention_match = match_spans(gold.mentions, bundle.mentions, id_field="mention_id", config=config)
    alignment = build_alignment(mention_match)

    gold_claims = gold.claims_for("extractor")
    gold_by_id = index_by(gold_claims, "claim_id")
    activos = [c for c in bundle.claims if not c.get("abstained")]
    gold_keyed = [
        {"claim_id": c["claim_id"], "_key": claim_key(c, {m: m for m in gold_m}, config)}
        for c in gold_claims
    ]
    pred_keyed = [
        {"claim_id": c["claim_id"], "_key": claim_key(c, alignment, config)} for c in activos
    ]
    match = match_by_key(gold_keyed, pred_keyed, id_field="claim_id", key_fn=lambda c: c["_key"])
    pred_by_id = index_by(activos, "claim_id")
    return gold_claims, gold_by_id, match, pred_by_id


def family_recall(gold: GoldDataset, bundle, config: MatchConfig) -> dict[str, Any]:
    """Recall por familia de negacion, MATCH exacto de clave sujeto/objeto/dir.

    Un `match.pairs` cuenta como acierto de familia si el gold empareja Y el
    `negated` de la prediccion coincide con el del gold: emparejar la relacion
    correcta pero invertir su polaridad no es "cobertura", es el error que
    todo este programa mide.
    """
    gold_claims, gold_by_id, match, pred_by_id = _family_match(gold, bundle, config)
    matched_gold = {g for g, _p in match.pairs}
    correct_gold: set[str] = set()
    for g, p in match.pairs:
        if bool(gold_by_id[g].get("negated")) == bool(pred_by_id[p].get("negated")):
            correct_gold.add(g)

    by_family: dict[str, Any] = {}
    for family in sorted({c["metadata"]["negation"]["family"] for c in gold_claims}):
        subset = [c["claim_id"] for c in gold_claims if c["metadata"]["negation"]["family"] == family]
        total = len(subset)
        covered = sum(1 for cid in subset if cid in matched_gold)
        correct = sum(1 for cid in subset if cid in correct_gold)
        by_family[family] = {
            "cases": total,
            "coverage": round(covered / total, 4) if total else None,
            "recall": round(correct / total, 4) if total else None,
        }

    total = len(gold_claims)
    covered_total = len(matched_gold)
    correct_total = len(correct_gold)
    false_positives = sum(
        1
        for c in bundle.claims
        if not c.get("abstained")
        and c["claim_id"] not in {p for _g, p in match.pairs}
    )
    return {
        "coverage": round(covered_total / total, 4) if total else None,
        "recall_overall": round(correct_total / total, 4) if total else None,
        "recall_simple": by_family.get(_SIMPLE_FAMILY, {}).get("recall"),
        "precision": round(correct_total / (correct_total + false_positives), 4)
        if (correct_total + false_positives)
        else None,
        "false_positives": false_positives,
        "by_family": by_family,
        "evaluable_cases": total,
        "covered_cases": covered_total,
    }


def b3_gates(name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    cobertura = metrics.get("coverage")
    recall_simple = metrics.get("recall_simple")
    return {
        "lane": name,
        "cobertura_e2e_dev": {
            "umbral": UMBRAL_COBERTURA_DEV,
            "observado": cobertura,
            "veredicto": "CONFORME" if (cobertura or 0) >= UMBRAL_COBERTURA_DEV else "NO_CONFORME",
        },
        "recall_simple": {
            "umbral": UMBRAL_RECALL_SIMPLE,
            "observado": recall_simple,
            "veredicto": "CONFORME"
            if (recall_simple is not None and recall_simple >= UMBRAL_RECALL_SIMPLE)
            else "NO_CONFORME",
        },
    }


# --------------------------------------------------------------------------
# Ejecucion de punta a punta
# --------------------------------------------------------------------------
#: Campos de `SourceEpisode` que son `Optional[...]` por TIPO pero que el
#: contrato exige presentes como CLAVE (ver `contracts.base.V3Document.from_dict`:
#: solo se libra de "obligatorio" un campo con `default` de dataclass, no un
#: campo tipado Optional). El gold de `negation` se autoro para el runner E2E
#: congelado (que no pasa por `SourceEpisode.from_dict`) y por eso omite estas
#: claves. Rellenarlas a `None` aqui es un AJUSTE DE COMPATIBILIDAD declarado,
#: no una edicion del gold: no se toca ni un byte de los ficheros en disco
#: (la integridad ya se comprobo por hash en `load_dev_gold`), solo se
#: completa una copia en memoria para poder reutilizar el mismo extractor
#: semantico que ya corre sobre el split `dev`.
_EPISODE_OPTIONAL_BY_TYPE = ("speaker", "turn", "table")


def _episode_for_semantic_pipeline(episode: dict) -> dict:
    out = dict(episode)
    for field in _EPISODE_OPTIONAL_BY_TYPE:
        out.setdefault(field, None)
    return out


def _build_context_negation(gold: GoldDataset):
    """`semantic_bench.build_context`, con el ajuste de compatibilidad de
    episodios (ver `_episode_for_semantic_pipeline`). Reutiliza el resto tal
    cual: fragmentos, perfil y lexico salen exactamente igual que en `dev`.
    """
    from knowledge_v3.contracts import EvidenceFragment, GameProfile, SourceEpisode

    episodes = [
        SourceEpisode.from_dict(_episode_for_semantic_pipeline(e), validate=False)
        for e in gold.episodes
    ]
    fragments = [EvidenceFragment.from_dict(dict(f), validate=False) for f in gold.fragments]
    profile = GameProfile.from_dict(dict(gold.profiles["generic"]), validate=False)
    return bench.ExtractionContext(
        workspace=episodes[0].workspace,
        episodes=episodes,
        fragments=fragments,
        profile=profile,
        lexicon=bench.Lexicon.from_profile(profile),
    )


def build_report(
    *,
    cache_dir: Optional[Path],
    mock: bool,
    timeout_seconds: int,
    concurrency: int,
    price_per_million_tokens_usd: Optional[float],
) -> dict[str, Any]:
    # OJO: no se toca `bench.SPLIT` (estado global de otro modulo; mutarlo
    # contaminaria cualquier otro consumidor del mismo proceso, tests
    # incluidos). El unico uso que este script hace de ese literal es el campo
    # `split` informativo de los bundles de `bench.to_bundle`, que
    # `family_recall` no consulta.
    gold = load_dev_gold(verify=True)
    ctx = _build_context_negation(gold)
    match_config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)

    port, metering = make_b3_port(cache_dir=cache_dir, mock=mock, timeout_seconds=timeout_seconds)

    results: dict[str, bench.RunResult] = {}
    started_a = time.monotonic()
    results["A"] = bench.run_config("A", ctx, prior=results)
    wall_a = int((time.monotonic() - started_a) * 1000)

    started_c2 = time.monotonic()
    results["C2"] = bench.run_config("C2", ctx, port=port, prior=results)
    wall_c2 = int((time.monotonic() - started_c2) * 1000)

    results["D"] = bench.RunResult(
        "D",
        _union(results["A"].output, results["C2"].output),
        results["A"].wall_ms + results["C2"].wall_ms,
        performance=results["C2"].performance,
        provider="local+" + results["C2"].provider,
        model=results["C2"].model,
    )
    from knowledge_v3.reconcile import ProposalReconciler

    reconciled = ProposalReconciler().reconcile(results["D"].output)
    results["D-R"] = bench.RunResult(
        "D-R",
        reconciled,
        results["D"].wall_ms,
        performance=results["D"].performance,
        provider=results["D"].provider + "+reconciler",
        model=results["D"].model,
    )

    lanes: dict[str, Any] = {}
    label = {"A": "determinista", "C2": "nvidia", "D-R": "union_reconciliada"}
    for key in ("A", "C2", "D-R"):
        bundle = bench.to_bundle(results[key], ctx)
        metrics = family_recall(gold, bundle, match_config)
        lanes[label[key]] = {
            "config": key,
            "metrics": metrics,
            "gates": b3_gates(label[key], metrics),
            "wall_ms": results[key].wall_ms,
        }

    calls = metering.calls
    real_calls = [c for c in calls if c["ok"]]
    latencies = sorted(c["latency_ms"] for c in real_calls) if real_calls else []
    prompt_tokens = sum(c.get("prompt_tokens", 0) for c in real_calls)
    completion_tokens = sum(c.get("completion_tokens", 0) for c in real_calls)
    total_tokens = sum(c.get("total_tokens", 0) for c in real_calls) or (prompt_tokens + completion_tokens)
    n_episodes = len(ctx.episodes)
    tokens_per_episode = total_tokens / n_episodes if n_episodes and real_calls else None
    extrapolation_1000 = tokens_per_episode * 1000 if tokens_per_episode is not None else None

    cost_note = (
        "sin precio documentado en el repo: se reporta solo tokens; pasa "
        "--price-per-million-tokens-usd para estimar coste"
        if price_per_million_tokens_usd is None
        else None
    )
    estimated_cost_usd = (
        round(total_tokens / 1_000_000 * price_per_million_tokens_usd, 4)
        if price_per_million_tokens_usd is not None
        else None
    )
    estimated_cost_1000_episodes_usd = (
        round(extrapolation_1000 / 1_000_000 * price_per_million_tokens_usd, 4)
        if price_per_million_tokens_usd is not None and extrapolation_1000 is not None
        else None
    )

    cache_wrapper = port  # CachingPort
    incidents = sorted(set(c.get("error") for c in calls if not c["ok"]))

    report = {
        "gate": "4",
        "block": "B3",
        "titulo": "Carril semantico NVIDIA en modo sombra (nunca escribe, nunca decide)",
        "generado_por": "scripts/gate4/measure_b3.py",
        "split": SPLIT,
        "mock": mock,
        "concurrency_requested": concurrency,
        "gold": {
            "episodes": len(gold.episodes),
            "claims": len(gold.claims_for("extractor")),
        },
        "lanes": lanes,
        "latency": {
            "unit": "ms",
            "real_calls": len(real_calls),
            "mean": round(statistics.mean(latencies), 1) if latencies else None,
            "p95": round(_percentile(latencies, 0.95), 1) if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "tokens": {
            "prompt_tokens_total": prompt_tokens,
            "completion_tokens_total": completion_tokens,
            "total_tokens": total_tokens,
            "episodes_measured": n_episodes,
            "tokens_per_episode_mean": round(tokens_per_episode, 1) if tokens_per_episode else None,
            "extrapolation_1000_episodes_tokens": round(extrapolation_1000, 1)
            if extrapolation_1000 is not None
            else None,
            "price_per_million_tokens_usd": price_per_million_tokens_usd,
            "estimated_cost_usd_this_run": estimated_cost_usd,
            "estimated_cost_usd_1000_episodes": estimated_cost_1000_episodes_usd,
            "note": cost_note,
        },
        "cache": {
            "path": str(cache_dir) if cache_dir else None,
            "calls_real": len(real_calls),
            "calls_failed": len(calls) - len(real_calls),
            "calls_served_from_cache": getattr(cache_wrapper, "hits", 0),
            "calls_missed_cache": getattr(cache_wrapper, "misses", 0),
        },
        "incidencias_api": {
            "transport_retries_used": getattr(metering.inner, "retries_used", 0)
            if hasattr(metering.inner, "retries_used")
            else 0,
            "hard_timeouts": getattr(metering.inner, "timeouts", 0)
            if hasattr(metering.inner, "timeouts")
            else 0,
            "failed_calls": len(calls) - len(real_calls),
            "distinct_errors": incidents,
        },
        "wall_ms": {"A": wall_a, "C2": wall_c2},
    }
    return report


def _union(a, c):
    from knowledge_v3.extraction.base import ExtractionOutput

    union = ExtractionOutput()
    union.extend(a)
    union.extend(c)
    return union


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def to_markdown(report: dict[str, Any]) -> str:
    lineas = [
        "# Puerta 4 - B3: carril semantico NVIDIA en sombra",
        "",
        f"Split: `{report['split']}` -- {report['gold']['claims']} claims / "
        f"{report['gold']['episodes']} episodios (gold congelado, verificado por hash).",
        "",
        "Generado por `scripts/gate4/measure_b3.py`. Ninguna cifra de este documento",
        "se escribe a mano. Modo SOMBRA: el carril NVIDIA nunca escribe en Neo4j ni",
        "decide; solo se compara contra el gold y contra el determinista.",
        "",
        "## Carriles",
        "",
        "| carril | cobertura | recall_simple | recall_overall | precision | falsos positivos |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, datos in report["lanes"].items():
        m = datos["metrics"]
        lineas.append(
            f"| {name} | {m['coverage']} | {m['recall_simple']} | {m['recall_overall']} "
            f"| {m['precision']} | {m['false_positives']} |"
        )
    lineas += ["", "## Puertas (umbral del programa, no redefinido por B3)", ""]
    lineas.append("| carril | puerta | umbral | observado | veredicto |")
    lineas.append("| --- | --- | --- | --- | --- |")
    for name, datos in report["lanes"].items():
        for gate_name, gate in datos["gates"].items():
            if gate_name == "lane":
                continue
            lineas.append(
                f"| {name} | {gate_name} | {gate['umbral']} | {gate['observado']} | {gate['veredicto']} |"
            )
    lat = report["latency"]
    tok = report["tokens"]
    cache = report["cache"]
    inc = report["incidencias_api"]
    lineas += [
        "",
        "## Latencia del carril NVIDIA (llamadas REALES, no servidas desde cache)",
        "",
        f"- llamadas reales: {lat['real_calls']}",
        f"- media: {lat['mean']} ms",
        f"- p95: {lat['p95']} ms",
        f"- maxima: {lat['max']} ms",
        "",
        "## Tokens y extrapolacion",
        "",
        f"- tokens de entrada (total): {tok['prompt_tokens_total']}",
        f"- tokens de salida (total): {tok['completion_tokens_total']}",
        f"- tokens totales: {tok['total_tokens']}",
        f"- tokens medios por episodio: {tok['tokens_per_episode_mean']}",
        f"- extrapolacion a 1000 episodios (tokens): {tok['extrapolation_1000_episodes_tokens']}",
        f"- precio USD/millon de tokens: {tok['price_per_million_tokens_usd']}",
        f"- coste estimado de esta corrida: {tok['estimated_cost_usd_this_run']}",
        f"- coste estimado por 1000 episodios: {tok['estimated_cost_usd_1000_episodes']}",
    ]
    if tok.get("note"):
        lineas.append(f"- nota: {tok['note']}")
    lineas += [
        "",
        "## Cache y llamadas reales vs servidas",
        "",
        f"- servidas desde cache: {cache['calls_served_from_cache']}",
        f"- llamadas reales (miss de cache): {cache['calls_missed_cache']}",
        f"- llamadas reales OK: {cache['calls_real']}",
        f"- llamadas reales fallidas: {cache['calls_failed']}",
        "",
        "## Incidencias con la API NVIDIA",
        "",
        f"- reintentos de transporte usados: {inc['transport_retries_used']}",
        f"- timeouts duros ({EPISODE_TIMEOUT_SECONDS}s): {inc['hard_timeouts']}",
        f"- llamadas fallidas tras agotar reintentos: {inc['failed_calls']}",
        f"- errores distintos observados: {inc['distinct_errors'] or 'ninguno'}",
    ]
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 4 (B3): carril NVIDIA en sombra.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="b3-nvidia-shadow")
    parser.add_argument("--cache", default="artifacts/gate4-program/b3-cache", help="dir de cache JSON")
    parser.add_argument("--mock", action="store_true", help="puerto guionizado (sin red, sin key)")
    parser.add_argument("--timeout-seconds", type=int, default=EPISODE_TIMEOUT_SECONDS)
    parser.add_argument("--concurrency", type=int, default=2, help="informativo: el carril NVIDIA se ejecuta secuencial por episodio dentro del extractor; se documenta como techo, no se paraleliza mas alla de 2 para no gatillar rate limits")
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
