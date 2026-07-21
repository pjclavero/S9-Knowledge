# -*- coding: utf-8 -*-
"""Runner del benchmark de extraccion de relaciones (B2).

Ejecuta el pipeline R8 **REAL** (`relations.pipeline.run_pipeline`) sobre el corpus
B1 **REAL** (`app/tests/data/relation_benchmark/`) y compara sus predicciones
contra el ground truth. REGLA CRITICA: este modulo NO reimplementa ninguna etapa
de R8 (pares, senales, sintaxis, consenso) ni simula resultados finales. Importa y
llama a `run_pipeline`.

Derivacion de la ENTRADA del pipeline (construccion de benchmark, NO simulacion)
--------------------------------------------------------------------------------
El pipeline necesita `segments` con `entities` (id, tipo y offsets de caracter),
pero el corpus da las fuentes como TEXTO plano. Las entidades de entrada se
DERIVAN de forma DETERMINISTA a partir de las MENCIONES del ground truth de cada
fuente (sujetos y objetos, con su texto):

  * Cada fuente se representa como UN unico segmento cuyo texto es la fuente
    completa; `segment_id == source_id`. Asi los offsets del ground truth (que son
    indices de caracter en la fuente completa) son directamente comparables con los
    de la evidencia que emite el pipeline.
  * Para cada relacion del ground truth de la fuente se localiza el `subject_text`
    y el `object_text`:
        1. Primero DENTRO del span de evidencia `[evidence_start, evidence_end)`.
        2. Si no aparece ahi (sujeto elidido, pronombre resuelto a otra mencion,
           etc.), en la PRIMERA aparicion en la fuente completa.
        3. Si no aparece en absoluto, la mencion se OMITE y se registra en
           `derivation_notes` (no se inventa posicion).
  * Cada mencion produce una entidad `{id, text, type, start, end}` con offsets de
    caracter. Menciones identicas (mismo id y misma posicion) se deduplican.

Esta derivacion NO decide ninguna relacion: solo aporta las entidades y sus
posiciones. Que R8 empareje esas entidades, elija predicado, direccion, evidencia,
negacion, temporalidad, estado epistemico y consenso es responsabilidad EXCLUSIVA
del pipeline real.

Modos del benchmark (via PipelineConfig REAL, sin reimplementar etapas)
-----------------------------------------------------------------------
El pipeline R8 es MONOLITICO: cada ejecucion corre siempre pares -> senales
heuristicas -> sintaxis -> consenso. No expone banderas para desactivar la sintaxis
o el consenso, y reimplementarlas esta PROHIBIDO. Por tanto los tres modos del
benchmark se materializan como presets REALES de `PipelineConfig` que varian el
UNICO parametro de etapa que R8 expone en modo offline: el modo de contexto del
emparejamiento (amplitud de los pares). Los proveedores local y externo estan
SIEMPRE deshabilitados (jamas Ollama/NVIDIA reales, jamas red):

  * ``baseline1`` : context_mode="sentence"  (par en la misma frase; el mas
                    restrictivo). Pares + heuristicas + sintaxis + consenso.
  * ``baseline2`` : context_mode="paragraph" (par en el mismo parrafo; amplia la
                    cobertura de pares).
  * ``full_offline`` : context_mode="segment" (cualquier par del segmento; maxima
                    cobertura offline).

docs/41 documenta esta correspondencia y su limitacion con total transparencia: no
es posible aislar "solo heuristicas" frente a "heuristicas+sintaxis" a traves del
pipeline real sin reimplementar etapas. El dictamen del benchmark se emite sobre el
modo `baseline1` (el mas conservador, menor riesgo de contaminacion de pares).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# --- Pipeline R8 REAL (importado, NO copiado) ------------------------------
from relations.pipeline import (
    PIPELINE_VERSION,
    PipelineConfig,
    run_pipeline,
)
from relations import pipeline as _r8_pipeline  # referencia explicita al modulo real
from relations import ensemble as _r8_ensemble  # combinador calibrado REAL (B6)

# Presets de modo -> PipelineConfig REAL (proveedores SIEMPRE off).
#
# `MODES` contiene EXCLUSIVAMENTE modos OFFLINE y CI-safe: ninguno de ellos puede
# abrir red bajo ninguna circunstancia. `--all-modes` y los tests iteran ESTE
# diccionario; por eso los modos con proveedor viven aparte en `PROVIDER_MODES`.
MODES: dict[str, dict] = {
    "baseline1": {"context_mode": "sentence"},
    "baseline2": {"context_mode": "paragraph"},
    "full_offline": {"context_mode": "segment"},
    # Mismo context_mode que baseline1 para que la comparativa sea directa: lo
    # UNICO que cambia es que el consenso se recalibra con `relations.ensemble`.
    "ensemble_offline": {"context_mode": "sentence"},
}
DEFAULT_MODE = "baseline1"

# Modos cuyo extractor de predicciones recalibra el consenso con B6 (ensemble).
ENSEMBLE_MODES: frozenset = frozenset({"ensemble_offline", "ensemble_full"})

# ---------------------------------------------------------------------------
# Modos CON PROVEEDOR REAL (Ollama / NVIDIA) -- DOBLE LLAVE OBLIGATORIA
# ---------------------------------------------------------------------------
# Estos modos NO estan en `MODES` a proposito: asi ni `--all-modes` ni ningun
# test que itere `MODES` puede ejecutarlos por accidente. Para usarlos hacen
# falta DOS llaves independientes (ver `require_provider_authorization`):
#   1. la bandera CLI `--enable-providers`
#   2. la variable de entorno `S9K_BENCH_PROVIDERS=1`
# Si falta cualquiera de las dos se aborta con `BenchmarkError` ANTES de
# construir ningun transporte, es decir, antes de tocar la red.
PROVIDER_MODES: dict[str, dict] = {
    "ollama_shadow": {"context_mode": "sentence", "local_llm_enabled": True},
    "nvidia_shadow": {"context_mode": "sentence", "external_ai_enabled": True},
    "ensemble_full": {
        "context_mode": "sentence",
        "local_llm_enabled": True,
        "external_ai_enabled": True,
    },
}

# Variable de entorno de la segunda llave.
PROVIDERS_ENV_VAR = "S9K_BENCH_PROVIDERS"

# Timeout (segundos) del LLM local en los modos con proveedor.
#
# POR QUE >= 120 s: `LocalLLMConfig.timeout` vale 30 s por defecto, pensado para
# tests con transporte inyectado (latencia ~0). Con 30 s una fraccion grande de
# las llamadas expiraria y el benchmark mediria TIMEOUTS, no CALIDAD del modelo.
# El transporte que construye `providers.py` aplica ESTE timeout (el pipeline
# construye su `LocalLLMConfig` internamente y no se puede modificar desde aqui,
# pero cuando se inyecta `transport` el timeout efectivo es el del transporte).
#
# POR QUE 300 s (ronda 2): el comentario anterior afirmaba "p50 real de Ollama
# 10-65 s"; la MEDICION real lo refuta: p50 = 97,8 s y maximo observado 175,7 s.
# El valor anterior (180 s) quedaba a 4,3 s del maximo medido, es decir sin
# margen: cualquier cola algo peor se contabilizaria como fallo de transporte y
# el run abortaria por infraestructura. 300 s = 175,7 s (max medido) x ~1,7, un
# margen de ~124 s sobre el peor caso observado.
PROVIDER_LOCAL_TIMEOUT_S = 300

# Tasa MAXIMA tolerada de fallos de TRANSPORTE en un run con proveedor real.
#
# POR QUE 10%: un fallo de transporte (404, timeout, JSON no parseable, respuesta
# sin la forma OpenAI) NO mide la calidad del modelo: mide que la infraestructura
# no contesto. Emitir un dictamen ("NO APTO") a partir de llamadas que nunca
# llegaron al modelo es exactamente el error de medicion que este bloque debe
# eliminar. Un proveedor sano practicamente nunca falla en transporte, asi que el
# umbral no pretende ser una tolerancia "estadistica" sino un margen para un
# hipo puntual (un reintento agotado, un corte de un segundo) sin invalidar una
# pasada larga. Por encima de eso el run se ABORTA RUIDOSAMENTE con
# `BenchmarkError` y NO se emite dictamen alguno.
PROVIDER_TRANSPORT_ERROR_MAX_RATE = 0.10

# Muestra minima para aplicar el umbral de TASA: con 1-2 llamadas la tasa es
# ruido puro.
#
# CUIDADO (B3): "muestra pequena" NO puede significar "se perdona". Con el
# comportamiento anterior, 9 de las 16 fuentes emitian "APTO" con 1-2 llamadas
# TODAS fallidas, o con 0 llamadas. La regla correcta es ENDURECER: por debajo
# del minimo cualquier error de transporte aborta igualmente (no hay muestra
# suficiente para distinguir un hipo de una caida). Eso lo aplica
# `check_provider_transport_health(..., strict_small_sample=True)`, que es como
# lo invoca SIEMPRE `run_benchmark`.
PROVIDER_TRANSPORT_MIN_CALLS = 3

# Muestra minima para aplicar la TASA en una comprobacion INTERMEDIA (N1).
#
# El chequeo acumulado corre tras CADA fuente. Con `min_calls=3` bastaba UN fallo
# en la llamada #1 de 36 para abortar con "1/5 = 20% > 10%", pese a que la tasa
# final habria sido 2,8%: el umbral EFECTIVO no era el documentado, sino
# "cualquier fallo temprano". Con 20 llamadas la tasa tiene resolucion suficiente
# para que un hipo puntual (1-2 fallos = 5-10%) no supere el umbral. Por debajo
# de esa muestra la tasa NO se aplica en las comprobaciones intermedias; se
# aplica siempre en la comprobacion FINAL (con `min_calls`) y ademas siguen
# vigentes dos cortocircuitos que no dependen de la tasa: muestra por debajo del
# minimo con errores (endurecimiento B3) y carril con el 100% de llamadas
# fallidas (proveedor demostrablemente caido).
PROVIDER_TRANSPORT_MIN_RATE_SAMPLE = 20

# Ruta del corpus B1 (relativa a data-engine/app).
_APP_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DIR = _APP_DIR / "tests" / "data" / "relation_benchmark"


class BenchmarkError(RuntimeError):
    """Error fatal del runner del benchmark (corpus invalido, etc.)."""


# ---------------------------------------------------------------------------
# Carga e integridad del corpus
# ---------------------------------------------------------------------------
def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Corpus:
    corpus_dir: Path
    manifest: dict
    ground_truth: dict
    sources: dict  # source_id -> text
    workspace_by_source: dict  # source_id -> workspace
    corpus_hashes: dict  # source_id -> sha256 (recomputado)

    @property
    def relations(self) -> list[dict]:
        return self.ground_truth["relations"]


def load_corpus(corpus_dir: Optional[Path] = None, *, verify: bool = True) -> Corpus:
    """Carga el corpus B1 y (por defecto) verifica su integridad sha256."""
    corpus_dir = Path(corpus_dir) if corpus_dir else DEFAULT_CORPUS_DIR
    if not corpus_dir.is_dir():
        raise BenchmarkError(f"corpus no encontrado: {corpus_dir}")

    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    gt_rel_path = corpus_dir / manifest["ground_truth"]["path"]
    ground_truth = json.loads(gt_rel_path.read_text(encoding="utf-8"))

    sources: dict[str, str] = {}
    workspace_by_source: dict[str, str] = {}
    corpus_hashes: dict[str, str] = {}
    for s in manifest["sources"]:
        sid = s["id"]
        path = corpus_dir / s["path"]
        digest = _sha256_file(path)
        corpus_hashes[sid] = digest
        if verify and digest != s["sha256"]:
            raise BenchmarkError(
                f"sha256 no coincide para {sid}: manifest={s['sha256']} recomputado={digest}"
            )
        sources[sid] = path.read_text(encoding="utf-8")
        workspace_by_source[sid] = s["workspace"]

    if verify:
        gt_digest = _sha256_file(gt_rel_path)
        if gt_digest != manifest["ground_truth"]["sha256"]:
            raise BenchmarkError(
                f"sha256 del ground truth no coincide: manifest="
                f"{manifest['ground_truth']['sha256']} recomputado={gt_digest}"
            )

    return Corpus(
        corpus_dir=corpus_dir,
        manifest=manifest,
        ground_truth=ground_truth,
        sources=sources,
        workspace_by_source=workspace_by_source,
        corpus_hashes=corpus_hashes,
    )


# ---------------------------------------------------------------------------
# Derivacion determinista de entidades de entrada
# ---------------------------------------------------------------------------
def _locate(text: str, mention: str, ev_start: int, ev_end: int) -> int:
    """Localiza `mention` en `text`: primero dentro de la evidencia, luego global."""
    if mention:
        idx = text.find(mention, ev_start, ev_end)
        if idx >= 0:
            return idx
        idx = text.find(mention)
        if idx >= 0:
            return idx
    return -1


def derive_entities(source_id: str, text: str, relations: list[dict]) -> tuple[list[dict], list[dict]]:
    """Deriva entidades de entrada (con offsets) desde las menciones del GT.

    Devuelve (entities, notes). Determinista: entidades ordenadas por
    (start, end, id, type). `notes` registra menciones no localizadas.
    """
    seen: dict[tuple, dict] = {}
    notes: list[dict] = []
    for r in sorted(relations, key=lambda x: str(x["relation_id"])):
        if r["source_id"] != source_id:
            continue
        for role in ("subject", "object"):
            mention = r[f"{role}_text"]
            eid = r[f"{role}_id"]
            etype = r[f"{role}_type"]
            pos = _locate(text, mention, int(r["evidence_start"]), int(r["evidence_end"]))
            if pos < 0:
                notes.append(
                    {"relation_id": r["relation_id"], "role": role, "id": eid,
                     "text": mention, "reason": "mention_not_found"}
                )
                continue
            key = (eid, pos, pos + len(mention))
            if key not in seen:
                seen[key] = {
                    "id": eid,
                    "text": mention,
                    "type": etype,
                    "start": pos,
                    "end": pos + len(mention),
                }
    entities = sorted(seen.values(), key=lambda e: (e["start"], e["end"], e["id"], e["type"] or ""))
    return entities, notes


def build_payload(source_id: str, text: str, workspace: str, entities: list[dict]) -> dict:
    """Construye el payload de entrada al pipeline REAL (un segmento por fuente)."""
    return {
        "source_id": source_id,
        "workspace": workspace,
        "segments": [
            {
                "segment_id": source_id,
                "text": text,
                "workspace": workspace,
                "source_id": source_id,
                "entities": entities,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Extraccion de predicciones desde la salida REAL del pipeline
# ---------------------------------------------------------------------------
def extract_predictions(output: dict) -> list[dict]:
    """Extrae predicciones planas desde el resultado REAL de run_pipeline.

    NO recalcula nada: lee `output['results']` (candidato + consenso reales).
    """
    preds: list[dict] = []
    for rec in output["results"]:
        c = rec["candidate"]
        cons = rec.get("consensus") or {}
        preds.append({
            "candidate_id": rec["candidate_id"],
            "source_id": c["source_id"],
            "workspace": c["workspace"],
            "subject_id": c["subject_id"],
            "object_id": c["object_id"],
            "subject_type": c["subject_type"],
            "object_type": c["object_type"],
            "predicate": c["predicate"],
            "direction": c["direction"],
            "negated": c["negated"],
            "temporal_scope": c["temporal_scope"],
            "epistemic_status": c["epistemic_status"],
            "evidence_text": c["evidence_text"],
            "evidence_start": c["evidence_start"],
            "evidence_end": c["evidence_end"],
            "consensus_state": cons.get("state"),
            "recommendation": cons.get("recommendation"),
        })
    return preds


# ---------------------------------------------------------------------------
# Extraccion de predicciones RECALIBRADA con el ensemble B6 (aditiva)
# ---------------------------------------------------------------------------
def segment_context(output: dict) -> dict:
    """Indexa `pair_id -> {"signals": [...], "syntax": {...}}` desde la salida REAL.

    Las senales y el analisis sintactico los emite el pipeline por SEGMENTO; el
    ensemble los necesita por candidato. Aqui solo se re-indexa lo YA calculado:
    no se recalcula ninguna senal ni se vuelve a analizar ningun texto.
    """
    index: dict[str, dict] = {}
    for doc in output.get("documents", []) or []:
        for seg in doc.get("segments", []) or []:
            syntax = seg.get("syntax")
            signals_by_pair = seg.get("signals") or {}
            for pair_id, sigs in signals_by_pair.items():
                index[pair_id] = {"signals": sigs, "syntax": syntax}
    return index


def extract_predictions_ensemble(output: dict, ensemble_config: Any = None) -> list[dict]:
    """Predicciones planas con el consenso RECALIBRADO por `relations.ensemble`.

    Mismo esquema que `extract_predictions` (que NO se modifica), pero
    `consensus_state`/`recommendation` provienen de `EnsembleDecision` en lugar
    del consenso base del pipeline. Se anaden dos campos de trazabilidad
    (`base_consensus_state`, `ensemble_score`).

    `ensemble.combine` acepta evaluaciones YA CALCULADAS (o None) y NUNCA abre
    red: aqui se le pasan las senales/sintaxis del segmento y los payloads
    local/external que el propio pipeline ya produjo.
    """
    kwargs = {}
    if ensemble_config is not None:
        kwargs["config"] = ensemble_config

    ctx = segment_context(output)
    preds: list[dict] = []
    for rec in output["results"]:
        c = rec["candidate"]
        base = rec.get("consensus") or {}
        seg_ctx = ctx.get(rec.get("pair_id"), {})
        decision = _r8_ensemble.combine(
            c,
            signals=seg_ctx.get("signals"),
            syntax=seg_ctx.get("syntax"),
            local=rec.get("local"),
            external=rec.get("external"),
            local_availability=rec.get("local_status"),
            external_availability=rec.get("external_status"),
            **kwargs,
        )
        preds.append({
            "candidate_id": rec["candidate_id"],
            "source_id": c["source_id"],
            "workspace": c["workspace"],
            "subject_id": c["subject_id"],
            "object_id": c["object_id"],
            "subject_type": c["subject_type"],
            "object_type": c["object_type"],
            "predicate": c["predicate"],
            "direction": c["direction"],
            "negated": c["negated"],
            "temporal_scope": c["temporal_scope"],
            "epistemic_status": c["epistemic_status"],
            "evidence_text": c["evidence_text"],
            "evidence_start": c["evidence_start"],
            "evidence_end": c["evidence_end"],
            "consensus_state": decision.state,
            "recommendation": decision.recommendation,
            "base_consensus_state": base.get("state"),
            "ensemble_score": round(float(decision.score), 6),
        })
    return preds


def collect_provider_payloads(run: "BenchmarkRun") -> list[dict]:
    """Volcado CRUDO por candidato (candidato + senales + sintaxis + proveedores).

    Permite RECOMBINAR el ensemble offline mas tarde sin volver a pagar llamadas
    a Ollama/NVIDIA (sustituye a la cache inexistente). Ver `recombine_from_payloads`.
    """
    out: list[dict] = []
    for sr in run.source_runs:
        ctx = segment_context(sr.output)
        for rec in sr.output["results"]:
            seg_ctx = ctx.get(rec.get("pair_id"), {})
            out.append({
                "source_id": sr.source_id,
                "candidate_id": rec["candidate_id"],
                "pair_id": rec.get("pair_id"),
                "candidate": rec["candidate"],
                "consensus": rec.get("consensus"),
                "signals": seg_ctx.get("signals"),
                "syntax": seg_ctx.get("syntax"),
                "local": rec.get("local"),
                "local_status": rec.get("local_status"),
                "external": rec.get("external"),
                "external_status": rec.get("external_status"),
            })
    return out


# Limites DUROS del fichero de payloads recombinable (B4). Sin ellos,
# `--recombine-from` aceptaba un JSONL de tamano y numero de registros
# arbitrarios procedente de una fuente no confiable.
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024      # 64 MiB
MAX_PAYLOAD_RECORDS = 100_000

# Campos minimos que debe traer CADA registro de payload.
_PAYLOAD_REQUIRED = ("source_id", "candidate_id", "candidate")
_CANDIDATE_REQUIRED = (
    "source_id", "workspace", "subject_id", "object_id", "subject_type",
    "object_type", "predicate", "direction", "negated", "temporal_scope",
    "epistemic_status", "evidence_text", "evidence_start", "evidence_end",
)


def validate_payload_records(records: list) -> list[dict]:
    """Valida el ESQUEMA de los registros de payload. Rechaza EN BLOQUE (B4).

    Un JSONL de payloads es entrada NO CONFIABLE: se demostro que uno forjado
    producia P=R=F1=1.0 con rc=0 y latencias inventadas de 99.999 ms. Aqui no se
    juzga la veracidad (eso lo hace el manifiesto con sha256 en `cli`), pero si
    la FORMA: cualquier registro invalido invalida el fichero entero, en vez de
    colarse como una prediccion mas.
    """
    if not isinstance(records, list):
        raise BenchmarkError("el fichero de payloads no contiene una lista de registros")
    if len(records) > MAX_PAYLOAD_RECORDS:
        raise BenchmarkError(
            f"fichero de payloads con demasiados registros: {len(records)} > "
            f"{MAX_PAYLOAD_RECORDS}"
        )
    problemas: list[str] = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            problemas.append(f"linea {i + 1}: no es un objeto JSON")
            continue
        for key in _PAYLOAD_REQUIRED:
            if key not in rec:
                problemas.append(f"linea {i + 1}: falta '{key}'")
        cand = rec.get("candidate")
        if not isinstance(cand, dict):
            problemas.append(f"linea {i + 1}: 'candidate' no es un objeto")
        else:
            for key in _CANDIDATE_REQUIRED:
                if key not in cand:
                    problemas.append(f"linea {i + 1}: candidate sin '{key}'")
        for key in ("local", "external"):
            val = rec.get(key)
            if val is not None and not isinstance(val, dict):
                problemas.append(f"linea {i + 1}: '{key}' no es objeto ni null")
        if problemas and len(problemas) > 25:
            problemas.append("... (truncado)")
            break
    if problemas:
        raise BenchmarkError(
            "fichero de payloads RECHAZADO por esquema invalido (no se recombina "
            "nada): " + "; ".join(problemas[:26])
        )
    return list(records)


def recombine_from_payloads(records: list[dict], ensemble_config: Any = None) -> list[dict]:
    """Recombina el ensemble OFFLINE a partir de payloads volcados previamente.

    `records` son las lineas del JSONL producido por `collect_provider_payloads`.
    Coste: CERO llamadas a proveedores. Devuelve predicciones con el mismo
    esquema que `extract_predictions_ensemble`.
    """
    fake_output = {
        "results": [
            {
                "candidate_id": r["candidate_id"],
                "pair_id": r.get("pair_id"),
                "candidate": r["candidate"],
                "consensus": r.get("consensus"),
                "local": r.get("local"),
                "local_status": r.get("local_status"),
                "external": r.get("external"),
                "external_status": r.get("external_status"),
            }
            for r in records
        ],
        "documents": [
            {
                "segments": [
                    {
                        "signals": {r["pair_id"]: r.get("signals") or []},
                        "syntax": r.get("syntax"),
                    }
                    for r in records
                    if r.get("pair_id")
                ]
            }
        ],
    }
    return extract_predictions_ensemble(fake_output, ensemble_config=ensemble_config)


# ---------------------------------------------------------------------------
# Ejecucion por fuente y por corpus
# ---------------------------------------------------------------------------
@dataclass
class SourceRun:
    source_id: str
    workspace: str
    output: dict
    predictions: list[dict]
    entities: list[dict]
    derivation_notes: list[dict]
    elapsed_ms: float


def mode_preset(mode: str) -> dict:
    """Preset REAL de PipelineConfig del modo (offline o con proveedor)."""
    if mode in MODES:
        return dict(MODES[mode])
    if mode in PROVIDER_MODES:
        return dict(PROVIDER_MODES[mode])
    raise BenchmarkError(
        f"modo desconocido: {mode!r}; validos: {sorted(MODES)} "
        f"(con proveedor, doble llave: {sorted(PROVIDER_MODES)})"
    )


def is_provider_mode(mode: str) -> bool:
    return mode in PROVIDER_MODES


def uses_ensemble(mode: str) -> bool:
    return mode in ENSEMBLE_MODES


# Placeholder que trae por DEFECTO `PipelineConfig.external_model` (pipeline.py).
# El carril externo (NVIDIA) enviaria esta cadena literal a `_post_chat` si nadie
# fija el id real del modelo -> HTTP 404 -> `ProviderNotFoundError` 5/5, disfrazado
# de "fallo de INFRAESTRUCTURA". El benchmark existe para impedir esa mentira: un
# id de modelo ausente es un error de CONFIGURACION, no de transporte.
PLACEHOLDER_EXTERNAL_MODEL = "external-model"


def mode_enables_external(mode: str) -> bool:
    """`True` si el preset del modo habilita la IA externa (carril NVIDIA)."""
    return bool(mode_preset(mode).get("external_ai_enabled"))


def require_external_model(mode: str, external_model: Optional[str]) -> None:
    """FAIL-CLOSED de CONFIGURACION: si el modo habilita IA externa, exige un id de
    modelo externo REAL antes de tocar la red.

    Un `external_model` ausente, vacio o igual al placeholder `"external-model"`
    haria que el carril externo enviase el placeholder a NVIDIA (404), y el runner
    lo presentaria como un fallo de TRANSPORTE 5/5. Eso es exactamente la clase de
    "fallo de INFRAESTRUCTURA" falso que este bloque debe impedir: se aborta ANTES
    de construir transporte/proveedor con un `BenchmarkError` que nombra la causa
    real (configuracion), no una caida de red inventada.
    """
    if not mode_enables_external(mode):
        return
    val = (external_model or "").strip()
    if not val or val == PLACEHOLDER_EXTERNAL_MODEL:
        raise BenchmarkError(
            f"modo {mode!r} habilita la IA externa pero falta el id REAL del modelo "
            f"externo (external_model={external_model!r}). Sin el, el carril externo "
            f"enviaria el placeholder {PLACEHOLDER_EXTERNAL_MODEL!r} a NVIDIA, que "
            "responde 404, y el run abortaria disfrazado de 'fallo de "
            "INFRAESTRUCTURA (transporte)' 5/5. Esto es un error de CONFIGURACION, "
            "no de red: pasa --external-model <id> (p.ej. "
            "meta/llama-3.3-70b-instruct) o define S9K_NVIDIA_REVIEW_MODELS. "
            "ABORTADO ANTES DE CONSTRUIR TRANSPORTE, sin tocar la red."
        )


def require_provider_authorization(mode: str, *, enable_providers: bool,
                                   env: Optional[dict] = None) -> None:
    """DOBLE LLAVE para los modos con proveedor. Se comprueba ANTES de tocar red.

    Requiere simultaneamente la bandera CLI `--enable-providers` y la variable
    de entorno `S9K_BENCH_PROVIDERS=1`. Si falta cualquiera -> `BenchmarkError`.
    Para los modos offline no hace nada (nunca hay red que autorizar).
    """
    if not is_provider_mode(mode):
        return
    env = os.environ if env is None else env
    env_ok = str(env.get(PROVIDERS_ENV_VAR, "")).strip() == "1"
    if not enable_providers or not env_ok:
        faltan = []
        if not enable_providers:
            faltan.append("--enable-providers")
        if not env_ok:
            faltan.append(f"{PROVIDERS_ENV_VAR}=1")
        raise BenchmarkError(
            f"modo con proveedor {mode!r} requiere DOBLE LLAVE; falta: "
            f"{', '.join(faltan)}. ABORTADO ANTES DE ABRIR RED "
            "(ninguna llamada a Ollama/NVIDIA realizada)."
        )


def required_providers(mode: str) -> tuple:
    """(`needs_local`, `needs_external`) segun el preset REAL del modo."""
    preset = mode_preset(mode)
    return bool(preset.get("local_llm_enabled")), bool(preset.get("external_ai_enabled"))


def authorize_provider_run(mode: str, *, enable_providers: bool = False,
                           local_transport: Any = None, external_provider: Any = None,
                           env: Optional[dict] = None) -> None:
    """LLAVE DEL NUCLEO (B1). Se ejecuta ANTES de construir `PipelineConfig`.

    Defecto corregido: `require_provider_authorization` solo se invocaba en
    `cli.main()`, pero `run_benchmark`/`run_source` son API PUBLICA exportada en
    `relations.benchmark.__init__`. Llamarlas con `mode="nvidia_shadow"` ponia
    `external_ai_enabled=True` y, con `external_provider=None`, el pipeline
    delegaba en el registry de `external_ai`, que lee la clave del entorno y
    abre conexiones REALES contra `integrate.api.nvidia.com:443` sin bandera ni
    variable de entorno (demostrado: 5 intentos; 10 si ademas se pedia
    `check_determinism=True`).

    Regla (fallo CERRADO, defecto SEGURO):

      1. Modo offline -> no hay nada que autorizar.
      2. Modo con proveedor -> por CADA proveedor que el preset habilita, el
         objeto correspondiente DEBE estar inyectado. Si falta, `BenchmarkError`:
         el nucleo NUNCA delega la resolucion del proveedor en el registry, que
         es la unica via por la que se abria red sin autorizacion.
      3. Ademas, si el llamante NO inyecta todos los proveedores del modo, se
         exige la DOBLE LLAVE explicita; la CLI la concede tras validarla y es
         quien construye los transportes.

    Consecuencia: un llamante que no sabe nada de la doble llave y llama
    `run_benchmark(corpus, mode="nvidia_shadow")` obtiene un `BenchmarkError` y
    CERO conexiones. El unico camino a red es inyectar un transporte real de
    forma explicita (lo que hace la CLI tras la doble llave).
    """
    if not is_provider_mode(mode):
        return
    needs_local, needs_external = required_providers(mode)
    faltan = []
    if needs_local and local_transport is None:
        faltan.append("local_transport")
    if needs_external and external_provider is None:
        faltan.append("external_provider")
    if faltan:
        # Se comprueba la doble llave PRIMERO para que el mensaje sea el correcto
        # cuando ademas falta autorizacion.
        require_provider_authorization(mode, enable_providers=enable_providers, env=env)
        raise BenchmarkError(
            f"modo con proveedor {mode!r} sin proveedor INYECTADO: falta "
            f"{', '.join(faltan)}. FALLO CERRADO: el runner NO resuelve el "
            "proveedor por el registry (esa via abria red leyendo la clave del "
            "entorno, sin bandera ni doble llave). Construye el transporte de "
            "forma explicita (ver `relations.benchmark.providers`) y pasalo. "
            "ABORTADO ANTES DE ABRIR RED."
        )


class ProviderTransportError(BenchmarkError):
    """El proveedor no respondio: NO se puede emitir dictamen de calidad.

    Subclase de `BenchmarkError` para que la CLI la trate igual (codigo de salida
    2, sin traza), pero distinguible por los llamantes que quieran diferenciar
    "fallo de infraestructura" de "uso incorrecto del benchmark".
    """


def check_provider_transport_health(
    results: list,
    *,
    mode: str,
    max_rate: float = PROVIDER_TRANSPORT_ERROR_MAX_RATE,
    min_calls: int = PROVIDER_TRANSPORT_MIN_CALLS,
    min_rate_sample: int = PROVIDER_TRANSPORT_MIN_RATE_SAMPLE,
    strict_small_sample: bool = True,
    final: bool = False,
) -> dict:
    """Aborta RUIDOSAMENTE si demasiadas llamadas fallaron en TRANSPORTE.

    Devuelve las estadisticas de transporte si el run es evaluable. Si la tasa
    supera `max_rate` lanza `ProviderTransportError`: jamas se emite un veredicto
    de calidad (`NO APTO` u otro) construido sobre llamadas que nunca llegaron al
    modelo. Ver `PROVIDER_TRANSPORT_ERROR_MAX_RATE` para la justificacion.

    `strict_small_sample` (B3): con muestra por debajo de `min_calls` NO se
    relaja, se ENDURECE -- CUALQUIER error de transporte aborta. Desde la ronda 3
    el valor POR DEFECTO es `True` (N1): la variante permisiva era un
    comportamiento que ningun llamante del bloque usaba y que solo servia para
    que un run con 1-2 llamadas todas fallidas pareciera sano.

    N1 -- umbral EFECTIVO = umbral DOCUMENTADO. La tasa agregada solo se aplica
    cuando la muestra alcanza `min_rate_sample` (o en la comprobacion FINAL, con
    `final=True`, donde basta `min_calls`). Antes, corriendo tras cada fuente,
    un unico fallo en la llamada #1 de 36 abortaba con "1/5 = 20% > 10%" aunque
    la tasa final fuese del 2,8%. Siguen abortando SIEMPRE, sin depender de la
    tasa: (a) muestra por debajo del minimo con errores, y (b) un carril con el
    100% de sus llamadas fallidas (proveedor demostrablemente caido).

    N2 -- la tasa se aplica tambien POR PROVEEDOR, no solo agregada: un carril
    local al 14,3% diluido con el externo al 0% daba un agregado del 4,76% y un
    dictamen APTO. Cada proveedor con muestra suficiente debe cumplir el umbral.

    Las estadisticas devueltas incluyen `sample_below_minimum`, `rate_applied`,
    `indeterminate` y `evaluable` para que el informe declare el alcance real.
    """
    from . import metrics as _bench_metrics  # import local: evita ciclo de imports

    stats = _bench_metrics.provider_transport_errors(list(results or []))
    attempted = int(stats.get("total_attempted", 0))
    errors = int(stats.get("total_errors", 0))
    rate = float(stats.get("rate", 0.0))
    stats["min_calls"] = int(min_calls)
    stats["min_rate_sample"] = int(min_rate_sample)
    stats["final_check"] = bool(final)
    stats["sample_below_minimum"] = attempted < int(min_calls)
    rate_applied = attempted >= int(min_calls) if final else attempted >= int(min_rate_sample)
    stats["rate_applied"] = bool(rate_applied)

    responded = int(stats.get("total_responded",
                              attempted - errors - int(stats.get("total_indeterminate", 0))))
    stats["total_responded"] = responded

    def _lanes_sobre_umbral() -> list:
        malos = []
        for key in ("local", "external"):
            d = stats[key]
            att = int(d["attempted"])
            if not att:
                continue
            umbral_muestra = int(min_calls) if final else int(min_rate_sample)
            if att >= umbral_muestra and float(d["rate"]) > max_rate:
                malos.append(key)
            elif att >= int(min_calls) and int(d["errors"]) == att:
                malos.append(key)  # carril COMPLETAMENTE caido
        return malos

    lanes_malos = _lanes_sobre_umbral()
    # Un run con 0 llamadas contabilizadas NO ha medido a ningun proveedor; y uno
    # con 0 respuestas CONFIRMADAS tampoco (bloqueante 1): el punto de contacto con
    # el modelo es cero en ambos casos. `responded>0` es candado imprescindible.
    stats["evaluable"] = bool(
        attempted >= int(min_calls) and responded > 0
        and rate <= max_rate and not lanes_malos)
    if strict_small_sample and attempted < int(min_calls) and errors:
        raise ProviderTransportError(
            f"modo {mode!r} ABORTADO: {errors}/{attempted} llamadas fallaron en "
            f"TRANSPORTE con una muestra POR DEBAJO del minimo ({min_calls}). "
            "Con tan pocas llamadas no se puede distinguir un hipo puntual de una "
            "caida total, asi que la muestra pequena ENDURECE el criterio en vez "
            "de relajarlo: no se emite dictamen. Revisa el endpoint y el servicio "
            "y repite la pasada."
        )

    def _detalle() -> str:
        partes = []
        for key in ("local", "external"):
            d = stats[key]
            if d["errors"]:
                partes.append(
                    f"{key}: {d['errors']}/{d['attempted']} fallidas "
                    f"({d['rate'] * 100:.1f}%), tipos={d['by_type']}"
                )
        return "; ".join(partes) or "sin desglose"

    _COLA = (
        ". Estos fallos son de TRANSPORTE (red, servidor, autenticacion, timeout, "
        "respuesta sin la forma OpenAI): la llamada NO llego a obtener una "
        "respuesta del modelo, asi que es un fallo de INFRAESTRUCTURA y no una "
        "medida de la calidad del modelo. NO se emite dictamen. Revisa el "
        "endpoint (¿termina en /v1/chat/completions?), que el modelo exista en el "
        "servidor y que el servicio este arriba, y repite la pasada."
    )
    if lanes_malos:
        raise ProviderTransportError(
            f"modo {mode!r} ABORTADO por el umbral POR PROVEEDOR "
            f"({max_rate * 100:.0f}%): carril(es) {lanes_malos} por encima del "
            f"maximo tolerado (agregado: {errors}/{attempted} = "
            f"{rate * 100:.1f}%, que por si solo NO lo habria detectado). "
            + _detalle() + _COLA
        )
    if rate_applied and rate > max_rate:
        raise ProviderTransportError(
            f"modo {mode!r} ABORTADO: {errors}/{attempted} llamadas "
            f"({rate * 100:.1f}%) fallaron en TRANSPORTE, por encima del "
            f"maximo tolerado ({max_rate * 100:.0f}%). " + _detalle() + _COLA
        )
    return stats


def _config_for_mode(mode: str, external_model: Optional[str] = None) -> PipelineConfig:
    preset = mode_preset(mode)
    base = {"local_llm_enabled": False, "external_ai_enabled": False}
    base.update(preset)
    # El id del modelo externo NO viaja en el transporte inyectado (a diferencia
    # del local): lo lee `pipeline._run_external` de `PipelineConfig.external_model`.
    # Si el llamante lo aporta, entra en `base` ANTES de construir la config; de lo
    # contrario se conserva el default de `PipelineConfig` (el placeholder), que la
    # guarda `require_external_model` habra rechazado ya para los modos externos.
    if external_model is not None and str(external_model).strip():
        base["external_model"] = str(external_model).strip()
    return PipelineConfig(**base)


def run_source(corpus: Corpus, source_id: str, *, mode: str = DEFAULT_MODE,
               local_transport: Any = None, external_provider: Any = None,
               ensemble_config: Any = None,
               enable_providers: bool = False,
               external_model: Optional[str] = None) -> SourceRun:
    """Ejecuta el pipeline REAL sobre una fuente.

    Proveedores SIEMPRE off salvo que el llamante inyecte explicitamente
    `local_transport`/`external_provider` (solo los modos de `PROVIDER_MODES`,
    y solo tras superar la doble llave). La llave se comprueba AQUI, en el
    nucleo, ANTES de construir `PipelineConfig` (B1).
    """
    authorize_provider_run(mode, enable_providers=enable_providers,
                           local_transport=local_transport,
                           external_provider=external_provider)
    # Config del modelo externo: fail-closed ANTES de construir nada (ver arriba).
    require_external_model(mode, external_model)
    text = corpus.sources[source_id]
    workspace = corpus.workspace_by_source[source_id]
    entities, notes = derive_entities(source_id, text, corpus.relations)
    payload = build_payload(source_id, text, workspace, entities)
    config = _config_for_mode(mode, external_model=external_model)

    t0 = time.perf_counter()
    # Sin inyeccion (caso por defecto) => jamas red, jamas Ollama/NVIDIA.
    output = run_pipeline(payload, config=config,
                          local_transport=local_transport,
                          external_provider=external_provider)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if uses_ensemble(mode):
        preds = extract_predictions_ensemble(output, ensemble_config=ensemble_config)
    else:
        preds = extract_predictions(output)
    return SourceRun(
        source_id=source_id,
        workspace=workspace,
        output=output,
        predictions=preds,
        entities=entities,
        derivation_notes=notes,
        elapsed_ms=elapsed_ms,
    )


def _code_sha() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_APP_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        return None
    return None


@dataclass
class BenchmarkRun:
    mode: str
    config: dict
    versions: dict
    source_runs: list[SourceRun]
    corpus_hashes: dict
    code_sha: Optional[str]
    # --- Campos aditivos (con default: no rompen construcciones existentes) ---
    source_ids: list = field(default_factory=list)
    provider_status: dict = field(default_factory=dict)
    ensemble: bool = False
    # Salud del TRANSPORTE de los proveedores (D1). Vacio en modos offline.
    provider_transport: dict = field(default_factory=dict)
    # Atestacion auditable de los endpoints usados: `esquema://host:puerto` SIN
    # credenciales (B5). Vacio en modos offline.
    provider_endpoints: dict = field(default_factory=dict)

    @property
    def results(self) -> list[dict]:
        """Registros crudos por candidato de todas las fuentes (orden determinista)."""
        out: list[dict] = []
        for sr in self.source_runs:
            out.extend(sr.output.get("results", []))
        return out

    @property
    def predictions(self) -> list[dict]:
        out: list[dict] = []
        for sr in self.source_runs:
            out.extend(sr.predictions)
        return out

    @property
    def source_summaries(self) -> list[dict]:
        return [sr.output["summary"] for sr in self.source_runs]

    @property
    def timings(self) -> list[dict]:
        return [{"source_id": sr.source_id, "elapsed_ms": round(sr.elapsed_ms, 3)}
                for sr in self.source_runs]

    def result_hashes(self) -> dict:
        return {sr.source_id: sr.output["result_hash"] for sr in self.source_runs}


def select_sources(corpus: Corpus, source_ids: Optional[list] = None) -> list[str]:
    """Submuestra de fuentes a PROCESAR. El corpus se carga y verifica IGUAL.

    Este filtro NO altera el corpus ni el ground truth en disco: solo acota que
    fuentes se ejecutan. El informe declara siempre que fuentes se usaron.
    """
    todas = sorted(corpus.sources)
    if not source_ids:
        return todas
    pedidas = [s.strip() for s in source_ids if str(s).strip()]
    desconocidas = [s for s in pedidas if s not in corpus.sources]
    if desconocidas:
        raise BenchmarkError(
            f"source_ids desconocidos: {sorted(desconocidas)}; disponibles: {todas}"
        )
    return [s for s in todas if s in set(pedidas)]


def should_watch_transport(mode: str, local_transport: Any = None,
                           external_provider: Any = None) -> bool:
    """¿Hay que vigilar la salud del TRANSPORTE en este run? (mutation check B2)

    El criterio es EL MODO, no si el llamante inyecto algo. El criterio anterior
    (`local_transport is not None or external_provider is not None`) dejaba el
    umbral MUERTO en el carril externo, porque `build_external_provider` devolvia
    siempre `None`: `--mode nvidia_shadow` emitia dictamen de calidad con
    `transport_error_rate = 1.0`.

    Se expone como funcion para poder MATAR esa mutacion con un test directo: hoy
    `authorize_provider_run` exige inyeccion en los modos con proveedor, asi que
    end-to-end ambos criterios coinciden y la mutacion queda enmascarada. Aqui no.
    """
    return is_provider_mode(mode)


def run_benchmark(corpus: Corpus, *, mode: str = DEFAULT_MODE,
                  source_ids: Optional[list] = None,
                  local_transport: Any = None, external_provider: Any = None,
                  ensemble_config: Any = None,
                  enable_providers: bool = False,
                  provider_endpoints: Optional[dict] = None,
                  max_run_seconds: Optional[float] = None,
                  external_model: Optional[str] = None) -> BenchmarkRun:
    """Ejecuta el pipeline REAL sobre el corpus (o una submuestra), determinista.

    La llave de proveedores se comprueba AQUI, en el nucleo, antes de construir
    ninguna `PipelineConfig` (B1): ver `authorize_provider_run`.
    """
    authorize_provider_run(mode, enable_providers=enable_providers,
                           local_transport=local_transport,
                           external_provider=external_provider)
    # Config del modelo externo: fail-closed ANTES del bucle y de tocar la red.
    require_external_model(mode, external_model)
    source_runs: list[SourceRun] = []
    versions: dict = {}
    selected = select_sources(corpus, source_ids)
    provider_status: dict = {}
    # B2: la salud del transporte se vigila en TODO modo con proveedor, no solo
    # cuando "se inyecto algo". El criterio anterior
    # (`local_transport is not None or external_provider is not None`) dejaba el
    # umbral MUERTO en el carril externo, porque `build_external_provider`
    # devolvia siempre `None`: `--mode nvidia_shadow` emitia dictamen de calidad
    # con transport_error_rate = 1.0.
    vigilar_transporte = should_watch_transport(mode, local_transport, external_provider)
    transport_stats: dict = {}
    # N11: deadline GLOBAL de run, comprobado entre fuentes. El deadline por
    # llamada no acota el total: con 300 s por llamada, un servidor que se atasca
    # 1 de cada 10 llamadas anade 300 s por atasco sin superar el umbral del 10%.
    t_inicio = time.monotonic()
    for sid in selected:
        if max_run_seconds is not None and time.monotonic() - t_inicio > float(max_run_seconds):
            raise BenchmarkError(
                f"presupuesto de tiempo del run agotado (--max-run-seconds="
                f"{max_run_seconds}): procesadas {len(source_runs)}/{len(selected)} "
                "fuentes. ABORTADO antes de pagar mas llamadas; las fuentes ya "
                "ejecutadas NO producen dictamen (muestra incompleta)."
            )
        sr = run_source(corpus, sid, mode=mode,
                        local_transport=local_transport,
                        external_provider=external_provider,
                        ensemble_config=ensemble_config,
                        enable_providers=enable_providers,
                        external_model=external_model)
        source_runs.append(sr)
        if not versions:
            versions = dict(sr.output["versions"])
        if not provider_status:
            provider_status = dict(sr.output.get("provider_status") or {})
        if vigilar_transporte:
            # FAIL FAST: se comprueba tras CADA fuente para no seguir pagando
            # llamadas a un proveedor que ya se ha demostrado caido. Muestra
            # pequena => criterio ENDURECIDO (B3).
            acumulados = [rec for s in source_runs for rec in s.output.get("results", [])]
            transport_stats = check_provider_transport_health(
                acumulados, mode=mode, strict_small_sample=True)
    if vigilar_transporte:
        # Comprobacion FINAL sobre la muestra COMPLETA: aqui la tasa se aplica
        # siempre (N1). Las intermedias solo son un cortacircuitos.
        acumulados = [rec for s in source_runs for rec in s.output.get("results", [])]
        transport_stats = check_provider_transport_health(
            acumulados, mode=mode, strict_small_sample=True, final=True)
    return BenchmarkRun(
        mode=mode,
        config=_config_for_mode(mode, external_model=external_model).to_dict(),
        versions=versions,
        source_runs=source_runs,
        corpus_hashes=dict(corpus.corpus_hashes),
        code_sha=_code_sha(),
        source_ids=list(selected),
        provider_status=provider_status,
        ensemble=uses_ensemble(mode),
        provider_transport=transport_stats,
        provider_endpoints=dict(provider_endpoints or {}),
    )


# Confirmacion en tiempo de import de que usamos el pipeline REAL, no un espejo.
assert run_pipeline is _r8_pipeline.run_pipeline, (
    "el runner debe usar relations.pipeline.run_pipeline REAL"
)


__all__ = [
    "MODES",
    "PROVIDER_MODES",
    "ENSEMBLE_MODES",
    "PROVIDERS_ENV_VAR",
    "PROVIDER_LOCAL_TIMEOUT_S",
    "PROVIDER_TRANSPORT_ERROR_MAX_RATE",
    "PROVIDER_TRANSPORT_MIN_CALLS",
    "PROVIDER_TRANSPORT_MIN_RATE_SAMPLE",
    "should_watch_transport",
    "DEFAULT_MODE",
    "PIPELINE_VERSION",
    "BenchmarkError",
    "ProviderTransportError",
    "check_provider_transport_health",
    "Corpus",
    "SourceRun",
    "BenchmarkRun",
    "load_corpus",
    "derive_entities",
    "build_payload",
    "extract_predictions",
    "extract_predictions_ensemble",
    "segment_context",
    "collect_provider_payloads",
    "recombine_from_payloads",
    "validate_payload_records",
    "MAX_PAYLOAD_BYTES",
    "MAX_PAYLOAD_RECORDS",
    "mode_preset",
    "is_provider_mode",
    "mode_enables_external",
    "require_external_model",
    "PLACEHOLDER_EXTERNAL_MODEL",
    "uses_ensemble",
    "require_provider_authorization",
    "authorize_provider_run",
    "required_providers",
    "select_sources",
    "run_source",
    "run_benchmark",
]
