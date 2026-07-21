# -*- coding: utf-8 -*-
"""CLI del benchmark de relaciones: ejecuta el pipeline R8 REAL y emite salidas.

Salidas:
  * JSON de resultados (informe completo).
  * JSONL de predicciones (una linea por prediccion del pipeline REAL).
  * Resumen Markdown (para docs/50) con metricas globales, por tipo, gates y
    dictamen.

Uso:
    python -m relations.benchmark.cli --mode baseline1 \
        --out-json /tmp/results.json --out-jsonl /tmp/preds.jsonl \
        --out-md docs/50-relation-benchmark-results.md

NUNCA abre red, NUNCA ejecuta Ollama/NVIDIA reales, NUNCA escribe en Neo4j.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Optional

from . import metrics as bench_metrics
from .matching import match_predictions
from .report import build_report
from .runner import (
    DEFAULT_MODE,
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_RECORDS,
    MODES,
    PROVIDER_MODES,
    PROVIDERS_ENV_VAR,
    BenchmarkError,
    collect_provider_payloads,
    is_provider_mode,
    load_corpus,
    mode_enables_external,
    recombine_from_payloads,
    require_provider_authorization,
    run_benchmark,
    validate_payload_records,
)
from .runner import _code_sha

# Version del manifiesto de payloads (B4).
PAYLOAD_MANIFEST_VERSION = "relation-benchmark-payloads-manifest-v1"
MANIFEST_SUFFIX = ".manifest.json"


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _mode_row(mode_name: str, rep: dict) -> dict:
    """Fila de la comparativa multi-modo: P/R/F1, tasa humana, conflictos y coste.

    Se usa TANTO para el Markdown como para la clave `all_modes` del JSON, para
    que ambas salidas no puedan divergir.
    """
    m = rep["metrics"]
    g = m["global_existence"]
    s = m["strict_predicate"]
    op = m["operational"]
    cost = m.get("provider_cost", {})
    local = cost.get("local", {})
    external = cost.get("external", {})
    return {
        "mode": mode_name,
        "context_mode": rep["config"]["context_mode"],
        "precision": g["precision"],
        "recall": g["recall"],
        "f1": g["f1"],
        "tp": g["tp"], "fp": g["fp"], "fn": g["fn"],
        "strict_f1": s["f1"],
        "pairs_generated": op["counters"]["pairs_generated"],
        "candidates_evaluated": op["counters"]["candidates_evaluated"],
        "human_rate": op["consensus_rates"]["human_rate"],
        "conflict_rate": op["consensus_rates"]["conflict_rate"],
        "results_conflict": op["counters"]["results_conflict"],
        "total_ms": op["timings"]["total_ms"],
        "per_candidate_ms": op["timings"]["per_candidate_ms"],
        "provider_calls": cost.get("total_calls", 0),
        "local_calls": local.get("calls", 0),
        "external_calls": external.get("calls", 0),
        "local_p50_ms": (local.get("latency") or {}).get("p50_ms"),
        "local_p95_ms": (local.get("latency") or {}).get("p95_ms"),
        "external_p50_ms": (external.get("latency") or {}).get("p50_ms"),
        "external_p95_ms": (external.get("latency") or {}).get("p95_ms"),
        "verdict": rep["verdict"],
        "providers": rep.get("providers", {}),
    }


def render_markdown(report: dict, *, all_modes: Optional[dict] = None) -> str:
    """Renderiza el resumen Markdown determinista del benchmark."""
    m = report["metrics"]
    g = m["global_existence"]
    s = m["strict_predicate"]
    lines: list[str] = []
    A = lines.append

    A("# 50 - Benchmark de extraccion de relaciones: resultados (v1)")
    A("")
    A("Ejecucion del pipeline R8 **REAL** (`relations.pipeline.run_pipeline`) sobre el")
    A("corpus B1 **REAL** (`app/tests/data/relation_benchmark/`), comparado contra el")
    A("ground truth. El runner NO reimplementa ninguna etapa de R8 ni simula resultados.")
    A("El plan, el criterio de emparejamiento y la derivacion de entidades se documentan")
    A("en `docs/41-relation-benchmark-plan.md`.")
    A("")
    A("## Confirmacion de seguridad")
    A("")
    # DERIVADO de la salida REAL del pipeline (`output['provider_status']`), NO
    # un literal: si los proveedores se ejecutaron, aqui se dice.
    prov = report.get("providers", {})
    A(f"- Ollama real: **{prov.get('local_llm', 'NOT_EXECUTED')}**")
    A(f"- NVIDIA real: **{prov.get('external_ai', 'NOT_EXECUTED')}**")
    # `network` se DERIVA de las llamadas realmente contabilizadas (B2): nunca se
    # publica "none" por el hecho de que un objeto proveedor sea None.
    A(f"- Red: **{prov.get('network', 'unknown (no derivable)')}**")
    A(f"- Llamadas a proveedor contabilizadas: **{prov.get('network_calls_counted', 0)}**")
    endpoints = prov.get("endpoints") or {}
    if endpoints:
        A("- Endpoints (host:puerto normalizado, SIN credenciales): "
          + ", ".join(f"`{k}={v}`" for k, v in sorted(endpoints.items())))
    if prov.get("status_consistency") and prov.get("status_consistency") != "OK":
        A(f"- ATENCION: {prov['status_consistency']}")
    A(f"- Escritura / Neo4j: **{prov.get('writes', 'none (dry-run, sin Neo4j)')}**")
    A(f"- Pipeline: `{report['pipeline_version']}` | code SHA: `{report['code_sha']}`")
    A("")
    A("## Configuracion")
    A("")
    A(f"- Modo del dictamen: `{report['mode']}` (config real: `{json.dumps(report['config'], sort_keys=True)}`)")
    for campo, nota in sorted((report.get("config_notes") or {}).items()):
        # N3: hay campos de `PipelineConfig` que se serializan pero NO son un
        # control efectivo; se dice explicitamente en vez de publicarlos como si
        # lo fueran.
        A(f"  - `{campo}`: {nota}")
    used = report.get("sources_used") or []
    avail = report.get("sources_available") or []
    submuestra = " (SUBMUESTRA `--sources`)" if used and len(used) != len(avail) else ""
    A(f"- Fuentes ejecutadas{submuestra}: {len(used)}/{len(avail)} -> `{', '.join(used)}`")
    A(f"- Consenso recalibrado con ensemble (B6): `{report.get('ensemble', False)}`")
    A(f"- Corpus v{report['corpus']['version']}: {report['corpus']['source_count']} fuentes, "
      f"{report['corpus']['relation_count']} relaciones de ground truth")
    A(f"- Ground truth sha256: `{report['corpus']['ground_truth_sha256']}`")
    A(f"- Versiones de componentes: `{json.dumps(report['versions'], sort_keys=True)}`")
    A("")

    A("## Dictamen del benchmark")
    A("")
    A(f"### **{report['verdict']}**")
    A("")
    A(f"> {report['verdict_justification']}")
    A("")
    A("Nota: el vocabulario de dictamen NO incluye \"APTO PARA INGESTA REAL\". El")
    A("pipeline es un propositor en modo sombra / dry-run: nunca aprueba ni escribe.")
    A("")

    A("## Metricas globales (criterio de existencia: par no ordenado)")
    A("")
    A("| Metrica | Precision | Recall | F1 | TP | FP | FN |")
    A("|---|---|---|---|---|---|---|")
    A(f"| Existencia de relacion | {_fmt_pct(g['precision'])} | {_fmt_pct(g['recall'])} | "
      f"{_fmt_pct(g['f1'])} | {g['tp']} | {g['fp']} | {g['fn']} |")
    A(f"| Estricta (par + predicado exacto) | {_fmt_pct(s['precision'])} | {_fmt_pct(s['recall'])} | "
      f"{_fmt_pct(s['f1'])} | {s['tp']} | {s['fp']} | {s['fn']} |")
    A("")

    if all_modes:
        A("### Comparativa por modo (config real de PipelineConfig)")
        A("")
        A("| Modo | context_mode | P (exist.) | R (exist.) | F1 | pares generados | "
          "tasa humana | conflictos | llamadas LLM | p95 local (ms) |")
        A("|---|---|---|---|---|---|---|---|---|---|")
        for mode_name in sorted(all_modes):
            row = _mode_row(mode_name, all_modes[mode_name])
            A(f"| {row['mode']} | {row['context_mode']} | {_fmt_pct(row['precision'])} | "
              f"{_fmt_pct(row['recall'])} | {_fmt_pct(row['f1'])} | {row['pairs_generated']} | "
              f"{_fmt_pct(row['human_rate'])} | {row['results_conflict']} | "
              f"{row['provider_calls']} | {row['local_p95_ms'] if row['local_p95_ms'] is not None else '-'} |")
        A("")

    A("## Metricas por tipo de relacion (predicado del ground truth)")
    A("")
    A("| Predicado | Soporte | Recall existencia | Recall predicado exacto |")
    A("|---|---|---|---|")
    for pred, d in m["per_predicate"].items():
        A(f"| {pred} | {d['support']} | {_fmt_pct(d['recall_existence'])} | "
          f"{_fmt_pct(d['recall_exact'])} |")
    A("")
    A("### Distribucion de predicados PREDICHOS por el heuristico")
    A("")
    A("| Predicado predicho | Nº |")
    A("|---|---|")
    for pred, cnt in m["predicted_predicate_distribution"].items():
        A(f"| {pred} | {cnt} |")
    A("")

    A("## Calidad estructural (sobre los TP de existencia)")
    A("")
    sq = m["structural_quality"]
    A("| Atributo | Correctos / Total | Tasa |")
    A("|---|---|---|")
    for key in ("predicate_correct", "direction_correct", "direction_orientation_ok",
                "types_correct", "negation_correct", "temporal_correct",
                "epistemic_correct", "evidence_correct", "offsets_correct",
                "workspace_correct", "decision_correct"):
        d = sq[key]
        A(f"| {key} | {d['ok']}/{d['total']} | {_fmt_pct(d['rate'])} |")
    A("")

    A("## Metricas operativas (contadores REALES del pipeline)")
    A("")
    op = m["operational"]
    c = op["counters"]
    A("| Contador | Valor |")
    A("|---|---|")
    for key in ("documents", "segments", "segments_processed", "segments_failed",
                "entities", "pairs_potential", "pairs_generated", "pairs_discarded",
                "candidates_evaluated", "results_strong", "results_partial",
                "results_conflict", "results_invalid", "results_human", "errors"):
        A(f"| {key} | {c[key]} |")
    A(f"| tiempo total (ms) | {op['timings']['total_ms']} |")
    A(f"| tiempo por doc (ms) | {op['timings']['per_doc_ms']} |")
    A(f"| tiempo por candidato (ms) | {op['timings']['per_candidate_ms']} |")
    A(f"| tasa humana | {_fmt_pct(op['consensus_rates']['human_rate'])} |")
    A(f"| tasa conflicto | {_fmt_pct(op['consensus_rates']['conflict_rate'])} |")
    A(f"| tasa invalida | {_fmt_pct(op['consensus_rates']['invalid_rate'])} |")
    A("")

    A("## Coste y latencia por proveedor")
    A("")
    A("Las latencias son SOLO de llamadas RESPONDIDAS: un 404 inmediato o un timeout")
    A("no describe al modelo y se contabiliza aparte como fallo de transporte.")
    A("")
    cost = m.get("provider_cost", {})
    A("| Proveedor | Llamadas | Payloads | p50 (ms) | p95 (ms) | max (ms) |")
    A("|---|---|---|---|---|---|")
    for key, label in (("local", "LLM local (Ollama)"), ("external", "IA externa (NVIDIA)")):
        d = cost.get(key, {})
        lat = d.get("latency", {})

        def _n(v):
            return "-" if v is None else v

        A(f"| {label} | {d.get('calls', 0)} | {d.get('payloads', 0)} | "
          f"{_n(lat.get('p50_ms'))} | {_n(lat.get('p95_ms'))} | {_n(lat.get('max_ms'))} |")
    A("")

    A("### Fallos de TRANSPORTE (infraestructura, NO calidad del modelo)")
    A("")
    A("Tres categorias DISJUNTAS: TRANSPORTE (la llamada no obtuvo respuesta del")
    A("modelo), RESPONDIDA (el proveedor contesto; la calidad del contenido se mide")
    A("aparte) e INDETERMINADA (el marcador `provider_error` generico no permite")
    A("saber cual de las dos fue: el benchmark NO lo cuenta como transporte ni lo")
    A("presenta como calidad).")
    A("")
    A("| Proveedor | Intentadas | Respondidas | Fallos de transporte | Tasa | Tipos | Indeterminadas |")
    A("|---|---|---|---|---|---|---|")
    for key, label in (("local", "LLM local (Ollama)"), ("external", "IA externa (NVIDIA)")):
        d = cost.get(key, {}) or {}
        t = d.get("transport_errors", {}) or {}
        ind = d.get("indeterminate", {}) or {}
        tipos = ", ".join(f"{k}={v}" for k, v in (t.get("by_type") or {}).items()) or "-"
        tipos_ind = ", ".join(f"{k}={v}" for k, v in (ind.get("by_type") or {}).items())
        A(f"| {label} | {t.get('attempted', 0)} | {t.get('responded', 0)} | "
          f"{t.get('errors', 0)} | {_fmt_pct(t.get('rate', 0.0))} | {tipos} | "
          f"{ind.get('count', 0)}{(' (' + tipos_ind + ')') if tipos_ind else ''} |")
    A("")
    fc = cost.get("fail_closed", 0)
    if fc:
        A(f"- ATENCION: {fc} candidatos con proveedor FALLIDO CERRADO "
          "(`provider_fail_closed`): NO dejan payload, asi que no cuentan como "
          "intentadas ni como fallidas. Se declaran aparte para que no queden "
          "invisibles tras una tasa del 0%.")
        A("")
    pt_gate = report["gates"].get("provider_transport") or {}
    if pt_gate.get("degraded_reasons"):
        A("- TRANSPORTE DEGRADADO (gate `provider_transport` = "
          f"{pt_gate.get('status')}): " + "; ".join(pt_gate["degraded_reasons"]))
        A("")

    A("## Gates (evaluados por separado)")
    A("")
    A("| Gate | Estado | Valor | Umbral | Tipo |")
    A("|---|---|---|---|---|")
    for name in ("determinism", "workspace_contamination", "provider_transport",
                 "simple_relations", "evidence", "offsets", "negation",
                 "temporality", "rumors", "predicate_structural"):
        gate = report["gates"].get(name)
        if gate is None:  # provider_transport solo existe en modos con proveedor
            continue
        val = gate.get("value")
        val_s = _fmt_pct(val) if isinstance(val, (int, float)) else "-"
        thr = gate.get("threshold")
        thr_s = _fmt_pct(thr) if isinstance(thr, (int, float)) else "-"
        hard = "DURO" if gate.get("hard") else "calidad"
        A(f"| {name} | **{gate['status']}** | {val_s} | {thr_s} | {hard} |")
    A("")

    A("## Determinismo")
    A("")
    det = report["determinism"]
    if det.get("deterministic") is None:
        # D7: "no comprobado" no es "comprobado y fallido"; se declara como tal.
        A("- Determinista (2 ejecuciones): **NO EVALUADO** (segunda ejecucion omitida)")
        A(f"- Alcance del dictamen: **{report.get('verdict_scope', 'COMPLETO')}**")
    else:
        A(f"- Determinista (2 ejecuciones): **{det.get('deterministic')}**")
    A(f"- Hashes iguales: {det.get('hashes_equal')} | Metricas iguales: {det.get('metrics_equal')} | "
      f"Predicciones iguales: {det.get('predictions_equal')}")
    A("")

    A("## Errores destacados")
    A("")
    fn = report["errors"]["false_negatives"]
    fp = report["errors"]["false_positives"]
    notes = report["errors"]["derivation_notes"]
    A(f"- Falsos negativos (relaciones de GT no cubiertas): **{len(fn)}**")
    A(f"- Falsos positivos (predicciones sin GT): **{len(fp)}**")
    A(f"- Menciones no localizadas en la derivacion de entidades: **{len(notes)}**")
    A("")
    if fn:
        A("### Falsos negativos (primeros 20)")
        A("")
        A("| relation_id | source | predicado | sujeto->objeto | motivo |")
        A("|---|---|---|---|---|")
        for r in fn[:20]:
            A(f"| {r['relation_id']} | {r['source_id']} | {r['predicate']} | "
              f"{r['subject_id']}->{r['object_id']} | {r['annotator_notes'][:60]} |")
        A("")
    if fp:
        A("### Falsos positivos (primeros 20)")
        A("")
        A("| source | predicado | sujeto->objeto | consenso |")
        A("|---|---|---|---|")
        for r in fp[:20]:
            A(f"| {r['source_id']} | {r['predicate']} | {r['subject_id']}->{r['object_id']} | "
              f"{r['consensus_state']} |")
        A("")

    return "\n".join(lines) + "\n"


def render_predictions_jsonl(report_predictions: list[dict]) -> str:
    lines = [json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
             for p in report_predictions]
    return "\n".join(lines) + ("\n" if lines else "")


def render_jsonl(records: list[dict]) -> str:
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
             for r in records]
    return "\n".join(lines) + ("\n" if lines else "")


def _build_providers(args) -> tuple:
    """Construye los transportes SOLO para modos con proveedor ya autorizados.

    Se llama DESPUES de `require_provider_authorization`; para modos offline
    devuelve `(None, None, {})` sin importar `providers.py` siquiera.

    Devuelve `(local_transport, external_provider, endpoints)`, donde `endpoints`
    es la ATESTACION auditable (`esquema://host:puerto`, sin credenciales) que se
    publica en el informe (B5).
    """
    if not is_provider_mode(args.mode):
        return None, None, {}
    from . import providers as _providers  # import perezoso: nunca en modo offline

    preset = PROVIDER_MODES[args.mode]
    local_transport = None
    external_provider = None
    endpoints: dict = {}
    if preset.get("local_llm_enabled"):
        # N13: el endpoint se resuelve AQUI (argumento o entorno) y se pasa
        # EXPLICITO a la fabrica, que ya no lee el entorno por su cuenta. Asi el
        # destino que se publica en la atestacion es exactamente el que se usa.
        endpoint = (getattr(args, "local_endpoint", None)
                    or os.environ.get(_providers.LOCAL_ENDPOINT_ENV) or "")
        local_transport = _providers.build_local_transport(
            endpoint,
            model=getattr(args, "local_model", None),
        )
        endpoints["local_llm"] = _providers.endpoint_attestation(endpoint)
    if preset.get("external_ai_enabled"):
        external_provider = _providers.build_external_provider()
        endpoints["external_ai"] = _providers.external_endpoint_attestation()
    return local_transport, external_provider, endpoints


def _resolve_external_model(args) -> Optional[str]:
    """Id del modelo externo para los modos con IA externa: `--external-model` o,
    si se omite, el primer id de `S9K_NVIDIA_REVIEW_MODELS` (via el registry). No
    hardcodea ningun id. Devuelve `None` si el modo no usa IA externa o si no hay
    ninguna fuente; la guarda `require_external_model` del nucleo decide entonces.
    """
    if not is_provider_mode(args.mode) or not mode_enables_external(args.mode):
        return None
    explicit = getattr(args, "external_model", None)
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    # Fallback NO hardcodeado: primer modelo de review declarado en el entorno.
    try:
        from external_ai import registry as _registry
        review = _registry.nvidia_config().get("review_models") or []
    except Exception:  # noqa: BLE001 - ausencia de registry/env => sin fallback
        review = []
    for m in review:
        if str(m).strip():
            return str(m).strip()
    return None


# ---------------------------------------------------------------------------
# B4 -- manifiesto de los payloads recombinables
# ---------------------------------------------------------------------------
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_path_for(payloads_path) -> Path:
    return Path(str(payloads_path) + MANIFEST_SUFFIX)


MANIFEST_HMAC_KEY_ENV = "S9K_BENCH_MANIFEST_HMAC_KEY"


def _manifest_hmac(manifest: dict, key: str) -> str:
    """HMAC-SHA256 del manifiesto SIN el propio campo `hmac_sha256` (B3).

    Es la UNICA parte de la cadena que aporta AUTENTICIDAD, y solo si el operador
    define la clave. Sin clave, el manifiesto demuestra integridad interna (que el
    JSONL no ha cambiado desde que se emitio ESE manifiesto), NO procedencia.
    """
    cuerpo = {k: v for k, v in manifest.items() if k != "hmac_sha256"}
    payload = json.dumps(cuerpo, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def build_payload_manifest(text: str, *, report: dict, records: list,
                           hmac_key: Optional[str] = None) -> dict:
    """Manifiesto de integridad y procedencia del JSONL de payloads (B4/B3)."""
    data = text.encode("utf-8")
    manifest = {
        "manifest": PAYLOAD_MANIFEST_VERSION,
        "payloads_sha256": _sha256_bytes(data),
        "payloads_bytes": len(data),
        "records": len(records),
        "mode": report["mode"],
        "code_sha": report.get("code_sha"),
        "pipeline_version": report.get("pipeline_version"),
        "ground_truth_sha256": report["corpus"]["ground_truth_sha256"],
        # B3: los hashes del corpus se acotan a las fuentes DECLARADAS y deben
        # cubrirlas exactamente; `corpus_hashes: {}` (o un subconjunto) dejaba la
        # atadura al corpus sin efecto, porque la verificacion iteraba las claves
        # del propio manifiesto.
        "corpus_hashes": {sid: sha
                          for sid, sha in (report["corpus"]["corpus_hashes"] or {}).items()
                          if sid in set(report.get("sources_used") or [])},
        "source_ids": list(report.get("sources_used") or []),
    }
    key = hmac_key if hmac_key is not None else os.environ.get(MANIFEST_HMAC_KEY_ENV)
    if key:
        manifest["hmac_sha256"] = _manifest_hmac(manifest, key)
    return manifest


def _load_verified_payloads(args) -> tuple:
    """Carga el JSONL de payloads EXIGIENDO su manifiesto. Falla en bloque.

    El corpus verificaba sha256 pero los payloads no verificaban NADA: un JSONL
    forjado producia P=R=F1=1.0 con rc=0 y latencias inventadas de 99.999 ms que
    nunca ocurrieron; ademas, el ground truth con el que se puntuaba se elegia a
    partir de los `source_id` del PROPIO fichero, asi que el atacante escogia su
    examen. Ahora:

      * se exige un manifiesto (`<payloads>.manifest.json`, o `--recombine-manifest`)
        y se verifica el sha256 del JSONL, el numero de registros, el hash del
        ground truth y los hashes del corpus;
      * los `source_ids` evaluados salen del MANIFIESTO, no del fichero;
      * se aplican limites de tamano y de numero de lineas;
      * cualquier registro con esquema invalido rechaza el fichero ENTERO.
    """
    path = Path(args.recombine_from)
    if not path.is_file():
        raise BenchmarkError(f"fichero de payloads no encontrado: {path}")
    size = path.stat().st_size
    if size > MAX_PAYLOAD_BYTES:
        raise BenchmarkError(
            f"fichero de payloads demasiado grande: {size} bytes > {MAX_PAYLOAD_BYTES}")
    raw = path.read_bytes()

    man_path = Path(args.recombine_manifest) if getattr(args, "recombine_manifest", None) \
        else manifest_path_for(path)
    if not man_path.is_file():
        raise BenchmarkError(
            f"falta el manifiesto de procedencia del JSONL de payloads: {man_path}. "
            "`--recombine-from` es entrada NO CONFIABLE: sin manifiesto verificado "
            "no se recombina nada (un JSONL forjado produciria P=R=F1=1.0). "
            "El manifiesto lo emite `--out-payloads`."
        )
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"manifiesto ilegible ({type(exc).__name__}): {man_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("manifest") != PAYLOAD_MANIFEST_VERSION:
        raise BenchmarkError(f"manifiesto de version desconocida: {man_path}")


    digest = _sha256_bytes(raw)
    if digest != manifest.get("payloads_sha256"):
        raise BenchmarkError(
            "sha256 del JSONL de payloads NO coincide con el manifiesto: "
            f"manifiesto={manifest.get('payloads_sha256')} recomputado={digest}. "
            "El fichero ha sido modificado o no corresponde a este manifiesto."
        )
    if int(manifest.get("payloads_bytes", -1)) != len(raw):
        raise BenchmarkError("tamano del JSONL de payloads distinto del declarado")

    lines = [ln for ln in raw.decode("utf-8").splitlines() if ln.strip()]
    if len(lines) > MAX_PAYLOAD_RECORDS:
        raise BenchmarkError(
            f"JSONL de payloads con demasiadas lineas: {len(lines)} > {MAX_PAYLOAD_RECORDS}")
    try:
        records = [json.loads(ln) for ln in lines]
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(
            f"JSONL de payloads malformado ({type(exc).__name__}): no se recombina nada"
        ) from exc
    if len(records) != int(manifest.get("records", -1)):
        raise BenchmarkError(
            f"numero de registros distinto del declarado: {len(records)} != "
            f"{manifest.get('records')}")
    # --- B3: el manifiesto no puede ser un sello construido con datos publicos --
    # Todo lo que sigue son ataduras COMPROBABLES contra el proceso que recombina.
    # Ninguna de ellas es autenticidad (ver `provenance.verified`): sin la clave
    # HMAC del operador, cualquiera con el repositorio puede emitir un manifiesto
    # valido. Lo que si se impide es que el fichero elija su propio examen.
    key = os.environ.get(MANIFEST_HMAC_KEY_ENV)
    hmac_estado = "AUSENTE (sin clave de operador: NO hay autenticidad)"
    if key:
        declarado = manifest.get("hmac_sha256")
        if not declarado:
            raise BenchmarkError(
                f"{MANIFEST_HMAC_KEY_ENV} definida pero el manifiesto NO trae "
                "hmac_sha256: no se puede autenticar su procedencia. RECHAZADO.")
        if not hmac.compare_digest(str(declarado), _manifest_hmac(manifest, key)):
            raise BenchmarkError(
                "HMAC del manifiesto INVALIDO: el manifiesto no fue emitido con la "
                "clave de operador configurada. RECHAZADO.")
        hmac_estado = "VERIFICADO con la clave de operador"
    elif manifest.get("hmac_sha256"):
        hmac_estado = (f"PRESENTE pero NO verificado ({MANIFEST_HMAC_KEY_ENV} no "
                       "definida en este proceso)")

    modo = str(manifest.get("mode") or "")
    if modo not in set(MODES) | set(PROVIDER_MODES):
        raise BenchmarkError(
            f"el manifiesto declara un modo desconocido: {modo!r}")

    # `code_sha`: debe coincidir con el del proceso que recombina. Antes no se
    # contrastaba con NADA (un manifiesto forjado con 40 ceros era aceptado).
    #
    # ORDEN (ronda 3, defecto de ordenacion): PRIMERO se exige que ESTE proceso
    # tenga un `code_sha` determinable, y solo DESPUES se compara con el del
    # manifiesto. Con el orden inverso, un arbol sin git (`code_sha_actual is
    # None`) frente a un manifiesto que declarase `code_sha: null` pasaba la
    # comparacion de igualdad (None == None) y el rechazo quedaba a merced de la
    # guarda posterior: la seguridad dependia de que la comparacion de igualdad
    # no cambiara nunca. Un `!=` convertido en cualquier otra comprobacion (o un
    # manifiesto que evitase la clave) dejaba pasar un fichero SIN atadura
    # alguna al codigo. La ausencia de atadura es un motivo de rechazo POR SI
    # MISMO, no un empate afortunado.
    code_sha_actual = _code_sha()
    if code_sha_actual is None:
        raise BenchmarkError(
            "no se puede determinar el code_sha del proceso que recombina (¿arbol "
            "sin git?): sin esa atadura el manifiesto no se puede contrastar con "
            "nada. RECHAZADO.")
    if manifest.get("code_sha") != code_sha_actual:
        raise BenchmarkError(
            "el manifiesto no corresponde a ESTE codigo: code_sha del manifiesto="
            f"{manifest.get('code_sha')!r}, code_sha del proceso que recombina="
            f"{code_sha_actual!r}. Recombinar payloads producidos por otra version "
            "del pipeline (o con un code_sha inventado) no mide este codigo. "
            "RECHAZADO.")

    hashes = manifest.get("corpus_hashes")
    ids = [str(s) for s in (manifest.get("source_ids") or [])]
    if not isinstance(hashes, dict) or not hashes:
        raise BenchmarkError(
            "el manifiesto no declara corpus_hashes (o los declara vacios): un "
            "`corpus_hashes: {}` DESACTIVABA por completo la atadura al corpus, "
            "porque la comprobacion iteraba las claves del propio manifiesto. "
            "RECHAZADO.")
    if sorted(hashes) != sorted(set(ids)) or not ids:
        raise BenchmarkError(
            "corpus_hashes del manifiesto no cubre EXACTAMENTE sus source_ids: "
            f"hashes={sorted(hashes)} source_ids={sorted(set(ids))}. RECHAZADO.")
    manifest["_hmac_status"] = hmac_estado

    validate_payload_records(records)
    return records, manifest, digest


def _recombine(args) -> int:
    """Recombina el ensemble OFFLINE desde un JSONL de payloads. CERO llamadas."""
    records, manifest, digest = _load_verified_payloads(args)
    corpus = load_corpus(args.corpus_dir)

    # El ground truth debe ser el MISMO contra el que se produjeron los payloads.
    if manifest.get("ground_truth_sha256") != corpus.manifest["ground_truth"]["sha256"]:
        raise BenchmarkError(
            "el ground truth actual no es el del manifiesto de payloads "
            f"(manifiesto={manifest.get('ground_truth_sha256')}, "
            f"corpus={corpus.manifest['ground_truth']['sha256']})")
    for sid, sha in (manifest.get("corpus_hashes") or {}).items():
        if corpus.corpus_hashes.get(sid) != sha:
            raise BenchmarkError(f"la fuente {sid} del corpus no coincide con el manifiesto")

    # Los source_ids evaluados salen del MANIFIESTO: el fichero no elige su examen.
    used = sorted(manifest.get("source_ids") or [])
    if not used:
        raise BenchmarkError("el manifiesto no declara source_ids")
    ajenos = sorted({r.get("source_id") for r in records} - set(used))
    if ajenos:
        raise BenchmarkError(
            f"el JSONL contiene fuentes no declaradas en el manifiesto: {ajenos}")

    predictions = recombine_from_payloads(records)
    ground_truth = [r for r in corpus.relations if r["source_id"] in set(used)]
    match = match_predictions(predictions, ground_truth)

    # BLOQUEANTE 2 (ronda 4): DOBLE LLAVE de AUTENTICIDAD, simetrica a la de red.
    # El manifiesto solo prueba INTEGRIDAD (el JSONL no cambio y ata corpus/GT/
    # code_sha), NO AUTENTICIDAD (quien lo emitio y que los payloads vengan de
    # llamadas reales). Todo lo que ata el manifiesto -- ground_truth_sha256,
    # corpus_hashes, code_sha de HEAD -- es PUBLICO: cualquiera con el repositorio
    # fabrica un manifiesto valido y un JSONL que copia el ground truth, y hoy eso
    # daba P=R=F1=1.0 con rc=0. La UNICA prueba de autenticidad es el HMAC con la
    # clave de operador (S9K_BENCH_MANIFEST_HMAC_KEY). Sin ese HMAC verificado la
    # recombinacion NO puede presentarse como medicion fiable: se marca
    # AUTENTICIDAD NO VERIFICADA y el proceso termina FAIL-CLOSED (rc!=0) para que
    # una automatizacion que lea el rc no trague una entrada forjada, SALVO que el
    # operador reconozca explicitamente el modo no autenticado con
    # --accept-unauthenticated-recombine (entonces rc=0, pero con la marca bien
    # visible en el JSON de salida).
    autenticado = str(manifest.get("_hmac_status") or "").startswith("VERIFICADO")
    reconocido = bool(getattr(args, "accept_unauthenticated_recombine", False))
    if autenticado:
        authenticity = "VERIFICADA (HMAC de operador)"
    elif reconocido:
        authenticity = ("NO VERIFICADA (reconocida explicitamente con "
                        "--accept-unauthenticated-recombine)")
    else:
        authenticity = "NO VERIFICADA"

    out = {
        "benchmark": "relation-benchmark-recombine-v1",
        "source": str(args.recombine_from),
        "sources_used": used,
        "candidates": len(predictions),
        "providers_called": 0,
        # BLOQUEANTE 2: marca de autenticidad SIEMPRE presente y en la cabecera.
        "authenticity": authenticity,
        "authenticity_verified": autenticado,
        "authenticity_note": (
            "El manifiesto prueba INTEGRIDAD (el JSONL no cambio, ata corpus, "
            "ground_truth y code_sha), NO AUTENTICIDAD. Sin HMAC de operador "
            "(S9K_BENCH_MANIFEST_HMAC_KEY) cualquiera con el repositorio puede "
            "forjar un manifiesto valido desde datos publicos: estas cifras NO "
            "son una medicion fiable."
        ) if not autenticado else (
            "HMAC de operador verificado: la procedencia del manifiesto esta "
            "autenticada. La INTEGRIDAD (sha256, corpus, ground_truth, code_sha) "
            "tambien; sigue sin probarse que los payloads vengan de llamadas "
            "reales a un proveedor."
        ),
        # Procedencia: estas metricas NO son un run nuevo, son una recombinacion
        # de payloads previamente volcados y verificados.
        "provenance": {
            "recombined": True,
            "payloads_sha256": digest,
            # B3: vocabulario REBAJADO a lo que de verdad se comprueba. El
            # manifiesto ata el JSONL a un sha256, a un corpus, a un ground truth
            # y al code_sha de ESTE proceso; nada de eso demuestra QUIEN lo emitio.
            # Sin la clave HMAC del operador NO hay cadena de custodia.
            "verified": "integridad interna, NO autenticidad",
            "verified_detail": (
                "comprobado: sha256 y tamano del JSONL, numero de registros, "
                "esquema de cada registro, ground_truth_sha256, corpus_hashes no "
                "vacios que cubren exactamente los source_ids, y code_sha igual al "
                "del proceso que recombina. NO comprobado: quien emitio el "
                "manifiesto (cualquiera con el repositorio puede fabricar uno "
                "valido), ni que los payloads procedan de llamadas reales a un "
                "proveedor."
            ),
            "hmac": manifest.get("_hmac_status"),
            "manifest": {k: v for k, v in manifest.items() if k != "_hmac_status"},
        },
        "metrics": {
            "global_existence": bench_metrics.global_metrics(match),
            "strict_predicate": bench_metrics.strict_metrics(match),
            "per_predicate": bench_metrics.per_predicate_metrics(match),
            "structural_quality": bench_metrics.structural_quality(match),
            "provider_cost": bench_metrics.provider_cost(records, []),
        },
    }
    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    if args.out_jsonl:
        Path(args.out_jsonl).write_text(render_jsonl(predictions), encoding="utf-8")
    g = out["metrics"]["global_existence"]
    print(f"recombine from={args.recombine_from} candidatos={len(predictions)} llamadas=0")
    print(f"global P={g['precision']} R={g['recall']} F1={g['f1']}")
    print(f"authenticity={authenticity}")

    # BLOQUEANTE 2: FAIL-CLOSED. Sin HMAC verificado la salida es forjable; el JSON
    # ya la marca como AUTENTICIDAD NO VERIFICADA, pero el rc tambien debe delatarla
    # para que una automatizacion no la trague. Solo el reconocimiento explicito del
    # operador (--accept-unauthenticated-recombine) devuelve rc=0.
    if not autenticado and not reconocido:
        print(
            "ERROR: recombinacion con AUTENTICIDAD NO VERIFICADA "
            f"(hmac={manifest.get('_hmac_status')}). El manifiesto solo prueba "
            "integridad, no quien lo emitio: con datos publicos del repo se puede "
            "forjar un JSONL que da P=R=F1=1.0. Define "
            f"{MANIFEST_HMAC_KEY_ENV} y emite el manifiesto con HMAC, o reconoce el "
            "modo no autenticado con --accept-unauthenticated-recombine. NO se "
            "emite una medicion fiable.",
            file=sys.stderr,
        )
        return EXIT_BENCHMARK_ERROR
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de relaciones (pipeline R8 REAL)")
    parser.add_argument("--mode", default=DEFAULT_MODE,
                        choices=sorted(MODES) + sorted(PROVIDER_MODES),
                        help="modo (config real de PipelineConfig) para el dictamen; "
                             f"los modos {sorted(PROVIDER_MODES)} exigen DOBLE LLAVE "
                             f"(--enable-providers y {PROVIDERS_ENV_VAR}=1)")
    parser.add_argument("--all-modes", action="store_true",
                        help="ejecutar tambien los demas modos OFFLINE para la comparativa "
                             "(nunca incluye modos con proveedor)")
    parser.add_argument("--sources", default=None,
                        help="submuestra: source_ids separados por comas. El corpus se carga "
                             "y verifica igual; solo se acotan las fuentes procesadas")
    parser.add_argument("--enable-providers", action="store_true",
                        help=f"primera llave para los modos con proveedor (la segunda es "
                             f"{PROVIDERS_ENV_VAR}=1)")
    parser.add_argument("--local-endpoint", default=None,
                        help="endpoint OpenAI-compatible del LLM local (solo modos con proveedor)")
    parser.add_argument("--local-model", default=None,
                        help="modelo del LLM local (solo modos con proveedor)")
    parser.add_argument("--external-model", default=None,
                        help="id REAL del modelo de la IA externa/NVIDIA (p.ej. "
                             "meta/llama-3.3-70b-instruct) para los modos que la "
                             "habilitan (nvidia_shadow, ensemble_full). El carril "
                             "externo lo lee de PipelineConfig.external_model, NO del "
                             "transporte inyectado; sin un id real se enviaria el "
                             "placeholder 'external-model' (404). Si se omite, se toma "
                             "el primer id de S9K_NVIDIA_REVIEW_MODELS; si tampoco hay, "
                             "se aborta con error de CONFIGURACION antes de tocar red")
    parser.add_argument("--out-payloads", default=None,
                        help="JSONL con los payloads CRUDOS local/external por candidato "
                             "(para recombinar el ensemble despues sin repetir llamadas)")
    parser.add_argument("--recombine-from", default=None,
                        help="recombina el ensemble OFFLINE desde un JSONL de --out-payloads "
                             "(cero llamadas a proveedores). EXIGE el manifiesto "
                             f"'<jsonl>{MANIFEST_SUFFIX}' y lo verifica")
    parser.add_argument("--recombine-manifest", default=None,
                        help="ruta explicita del manifiesto de los payloads "
                             f"(por defecto '<jsonl>{MANIFEST_SUFFIX}')")
    parser.add_argument("--accept-unauthenticated-recombine", action="store_true",
                        help="RECONOCE explicitamente que la recombinacion se hace SIN "
                             "autenticidad verificada (sin HMAC de operador). Por defecto "
                             "una recombinacion no autenticada es FAIL-CLOSED (rc!=0) "
                             "porque el manifiesto se puede forjar con datos PUBLICOS del "
                             f"repo. Con {MANIFEST_HMAC_KEY_ENV} definida el HMAC se exige "
                             "y esta bandera no hace falta. La marca AUTENTICIDAD NO "
                             "VERIFICADA sigue apareciendo en el JSON de salida.")
    parser.add_argument("--max-run-seconds", type=float, default=None,
                        help="presupuesto GLOBAL de tiempo del run (N11). El deadline "
                             "por llamada no acota el total: un servidor que se atasca "
                             "1 de cada 10 llamadas anade el timeout entero por atasco "
                             "sin superar el umbral de fallos. Comprobado entre fuentes")
    parser.add_argument("--corpus-dir", default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-jsonl", default=None)
    parser.add_argument("--out-md", default=None)
    parser.add_argument("--no-determinism", action="store_true",
                        help="omitir la segunda ejecucion de determinismo (mas rapido)")
    args = parser.parse_args(argv)

    if args.recombine_from:
        return _recombine(args)

    # --- DOBLE LLAVE: se comprueba ANTES de cargar nada y ANTES de tocar red ---
    require_provider_authorization(args.mode, enable_providers=args.enable_providers)

    # D4: el guard de --all-modes se evalua AQUI, junto a la doble llave y ANTES
    # de `_build_providers`. Antes vivia despues del run: con la doble llave
    # concedida se ejecutaba el benchmark COMPLETO contra proveedores reales
    # (llamadas pagadas) y solo despues se abortaba, tirando todo el trabajo.
    if args.all_modes and is_provider_mode(args.mode):
        raise BenchmarkError(
            "--all-modes solo recorre modos OFFLINE; no se combina con modos con "
            "proveedor. ABORTADO ANTES DE CONSTRUIR NINGUN TRANSPORTE "
            "(ninguna llamada a Ollama/NVIDIA realizada)."
        )

    source_ids = [s.strip() for s in args.sources.split(",")] if args.sources else None

    local_transport, external_provider, endpoints = _build_providers(args)
    external_model = _resolve_external_model(args)

    corpus = load_corpus(args.corpus_dir)
    run = run_benchmark(corpus, mode=args.mode, source_ids=source_ids,
                        local_transport=local_transport,
                        external_provider=external_provider,
                        enable_providers=args.enable_providers,
                        provider_endpoints=endpoints,
                        max_run_seconds=args.max_run_seconds,
                        external_model=external_model)
    # Con proveedores reales el determinismo NO aplica (y duplicaria el coste).
    check_determinism = not args.no_determinism and not is_provider_mode(args.mode)
    report = build_report(corpus, run, check_determinism=check_determinism)

    all_modes = None
    if args.all_modes:
        all_modes = {}
        for mode_name in sorted(MODES):  # SOLO modos offline: nunca PROVIDER_MODES
            r = run if mode_name == args.mode else run_benchmark(
                corpus, mode=mode_name, source_ids=source_ids)
            all_modes[mode_name] = build_report(corpus, r, check_determinism=False)

    predictions = run.predictions

    if args.out_json:
        payload = dict(report)
        if all_modes:
            # La comparativa multi-modo tambien va al JSON (antes solo al MD).
            payload["all_modes"] = {name: _mode_row(name, rep)
                                    for name, rep in sorted(all_modes.items())}
        Path(args.out_json).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    if args.out_jsonl:
        Path(args.out_jsonl).write_text(render_predictions_jsonl(predictions), encoding="utf-8")
    if args.out_payloads:
        records = collect_provider_payloads(run)
        texto = render_jsonl(records)
        Path(args.out_payloads).write_text(texto, encoding="utf-8")
        # B4: junto al JSONL se emite SIEMPRE su manifiesto de integridad y
        # procedencia; `--recombine-from` lo exige y lo verifica.
        manifest_path_for(args.out_payloads).write_text(
            json.dumps(build_payload_manifest(texto, report=report, records=records),
                       indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(render_markdown(report, all_modes=all_modes), encoding="utf-8")

    g = report["metrics"]["global_existence"]
    print(f"mode={report['mode']} verdict={report['verdict']!r}")
    print(f"global P={g['precision']} R={g['recall']} F1={g['f1']} TP={g['tp']} FP={g['fp']} FN={g['fn']}")
    print(f"deterministic={report['determinism'].get('deterministic')}")
    cost = report["metrics"]["provider_cost"]
    print(f"providers local={report['providers']['local_llm']} "
          f"external={report['providers']['external_ai']} "
          f"llamadas={cost['total_calls']}")
    print(f"transport_errors={cost.get('transport_errors', {}).get('total_errors', 0)} "
          f"rate={cost.get('transport_error_rate', 0.0)}")
    print(f"verdict_scope={report.get('verdict_scope', 'COMPLETO')}")
    print(f"sources={','.join(report['sources_used'])}")

    # B2/B3: en un modo con proveedor, si no se midio nada (o el transporte fallo
    # por encima de lo tolerado) NO hay dictamen: el proceso debe terminar con
    # codigo de error, no con 0. Las salidas ya escritas documentan el intento.
    estado_transporte = (report["gates"].get("provider_transport") or {}).get("status")
    if is_provider_mode(args.mode) and estado_transporte not in ("PASS", "PARTIAL"):
        print(
            f"ERROR: modo con proveedor {args.mode!r} SIN DICTAMEN "
            f"(provider_transport={estado_transporte}): "
            f"{report.get('verdict_scope')}. No se ha medido calidad alguna.",
            file=sys.stderr,
        )
        return EXIT_BENCHMARK_ERROR
    return 0


# Codigo de salida unico para los errores de uso/infraestructura del benchmark.
EXIT_BENCHMARK_ERROR = 2


def run_cli(argv: Optional[list[str]] = None) -> int:
    """Punto de entrada con CODIGO DE SALIDA homogeneo (defecto D5).

    `main()` sigue PROPAGANDO `BenchmarkError` a proposito: importado como
    funcion, un abort de la doble llave o de salud del transporte debe ser una
    excepcion visible, no un entero que el llamante puede ignorar. Lo que faltaba
    era un punto de entrada unico que tradujera esa excepcion SIEMPRE al mismo
    codigo de salida, en vez de tener el try/except enterrado bajo
    `if __name__ == "__main__"`. Ese punto es este, y `__main__` lo usa.
    """
    try:
        return main(argv)
    except BenchmarkError as exc:  # error de uso/infraestructura: sin traza
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_BENCHMARK_ERROR


if __name__ == "__main__":
    raise SystemExit(run_cli())
