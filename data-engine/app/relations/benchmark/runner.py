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

# Presets de modo -> PipelineConfig REAL (proveedores SIEMPRE off).
MODES: dict[str, dict] = {
    "baseline1": {"context_mode": "sentence"},
    "baseline2": {"context_mode": "paragraph"},
    "full_offline": {"context_mode": "segment"},
}
DEFAULT_MODE = "baseline1"

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


def _config_for_mode(mode: str) -> PipelineConfig:
    if mode not in MODES:
        raise BenchmarkError(f"modo desconocido: {mode!r}; validos: {sorted(MODES)}")
    return PipelineConfig(
        local_llm_enabled=False,
        external_ai_enabled=False,
        **MODES[mode],
    )


def run_source(corpus: Corpus, source_id: str, *, mode: str = DEFAULT_MODE) -> SourceRun:
    """Ejecuta el pipeline REAL sobre una fuente. Proveedores SIEMPRE off."""
    text = corpus.sources[source_id]
    workspace = corpus.workspace_by_source[source_id]
    entities, notes = derive_entities(source_id, text, corpus.relations)
    payload = build_payload(source_id, text, workspace, entities)
    config = _config_for_mode(mode)

    t0 = time.perf_counter()
    # Proveedores en sombra NO inyectados => jamas red, jamas Ollama/NVIDIA.
    output = run_pipeline(payload, config=config, local_transport=None, external_provider=None)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

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


def run_benchmark(corpus: Corpus, *, mode: str = DEFAULT_MODE) -> BenchmarkRun:
    """Ejecuta el pipeline REAL sobre TODO el corpus, en orden determinista."""
    source_runs: list[SourceRun] = []
    versions: dict = {}
    for sid in sorted(corpus.sources):
        sr = run_source(corpus, sid, mode=mode)
        source_runs.append(sr)
        if not versions:
            versions = dict(sr.output["versions"])
    return BenchmarkRun(
        mode=mode,
        config=_config_for_mode(mode).to_dict(),
        versions=versions,
        source_runs=source_runs,
        corpus_hashes=dict(corpus.corpus_hashes),
        code_sha=_code_sha(),
    )


# Confirmacion en tiempo de import de que usamos el pipeline REAL, no un espejo.
assert run_pipeline is _r8_pipeline.run_pipeline, (
    "el runner debe usar relations.pipeline.run_pipeline REAL"
)


__all__ = [
    "MODES",
    "DEFAULT_MODE",
    "PIPELINE_VERSION",
    "BenchmarkError",
    "Corpus",
    "SourceRun",
    "BenchmarkRun",
    "load_corpus",
    "derive_entities",
    "build_payload",
    "extract_predictions",
    "run_source",
    "run_benchmark",
]
