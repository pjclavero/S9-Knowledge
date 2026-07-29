# -*- coding: utf-8 -*-
"""Medicion del extractor semantico sobre el split dev, con el arnes existente.

Este modulo EJECUTA el pipeline y llama al arnes de `benchmarks/`; no lo
modifica ni le anade metricas. Las metricas que el arnes no tiene y este bloque
necesita —recall top-1 y top-2 de PREDICADO, direccion top-1, entidades nuevas,
anclaje— se calculan aqui, encima de su mismo emparejamiento
(`benchmarks.matching`), para que sean comparables con las suyas.

Configuraciones (dosier del bloque):

    A   determinista solo                      (baseline, sin red)
    C1  semantico con qwen2.5:7b via Ollama    (ejecucion REAL)
    C2  semantico con llama-3.3-70b via NVIDIA (requiere API key en el entorno)
    D   A + C1, como UNION conservando origen  (sin reconciliador: a proposito)

    python -m knowledge_v3.extraction.semantic_bench --config A
    python -m knowledge_v3.extraction.semantic_bench --config C1 --cache runs/c1.json
    S9K_NVIDIA_API_KEY=... python -m knowledge_v3.extraction.semantic_bench --config C2

NUNCA toca `heldout`: el split esta cableado a `dev` y cambiarlo exige tocar
esta linea, que es justo lo que se quiere que cueste.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from ..benchmarks.harness import run as harness_run
from ..benchmarks.loader import GoldDataset, PredictionBundle, index_by, load_gold
from ..benchmarks.matching import MatchConfig, build_alignment, claim_key, match_by_key, match_spans
from ..contracts import EvidenceFragment, GameProfile, SourceEpisode
from .base import ExtractionContext, ExtractionOutput
from .lexicon import Lexicon
from .pipeline import ExtractionPipeline
from .provider_port import (
    MockProviderPort,
    NvidiaProviderPort,
    OllamaProviderPort,
    ProviderReply,
    ProviderRequest,
)
from .semantic import SemanticEpisodeExtractor
from .text import normalize

#: Split de medicion. Cableado a proposito: el held-out no se mide aqui.
SPLIT = "dev"

CONFIGS = ("A", "C1", "C2", "D")


# --------------------------------------------------------------------------
# Contexto a partir del gold
# --------------------------------------------------------------------------
def build_context(gold: GoldDataset, *, profile_id: str = "generic") -> ExtractionContext:
    """`ExtractionContext` con los documentos gold, SIN sus menciones ni claims.

    Se cargan episodios, fragmentos y perfil: exactamente lo que un extractor
    ve en produccion. El lexico sale del PERFIL, no del catalogo de entidades
    del benchmark: alimentar al extractor con las respuestas seria medir otra
    cosa.
    """
    episodes = [SourceEpisode.from_dict(dict(e), validate=False) for e in gold.episodes]
    fragments = [EvidenceFragment.from_dict(dict(f), validate=False) for f in gold.fragments]
    profile = GameProfile.from_dict(dict(gold.profiles[profile_id]), validate=False)
    return ExtractionContext(
        workspace=episodes[0].workspace,
        episodes=episodes,
        fragments=fragments,
        profile=profile,
        lexicon=Lexicon.from_profile(profile),
    )


# --------------------------------------------------------------------------
# Puerto con cache en disco
# --------------------------------------------------------------------------
class CachingPort:
    """Envuelve un puerto y guarda `prompt -> payload` en disco.

    No es una optimizacion cosmetica: una tanda real contra qwen2.5:7b cuesta
    minutos por episodio, y volver a puntuar el MISMO resultado no debe
    obligar a repetirla. La cache guarda la respuesta cruda del modelo, asi que
    una repuntuacion mide exactamente la misma tanda.
    """

    def __init__(self, inner: Any, path: Optional[Path]) -> None:
        self.inner = inner
        self.path = Path(path) if path else None
        self.provider = inner.provider
        self.model = inner.model
        self.name = getattr(inner, "name", "cached")
        self.hits = 0
        self.misses = 0
        self._data: dict[str, dict] = {}
        if self.path and self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def _key(request: ProviderRequest) -> str:
        raw = f"{request.system}\x00{request.prompt}\x00{request.purpose}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        key = self._key(request)
        cached = self._data.get(key)
        if cached is not None:
            self.hits += 1
            return ProviderReply(
                payload=cached["payload"],
                model=cached.get("model", self.model),
                provider=cached.get("provider", self.provider.value),
                latency_ms=int(cached.get("latency_ms", 0)),
                attempts=int(cached.get("attempts", 1)),
                json_retries=int(cached.get("json_retries", 0)),
                usage=cached.get("usage") or {},
            )
        self.misses += 1
        reply = self.inner.complete_json(request)
        self._data[key] = {
            "payload": reply.payload,
            "model": reply.model,
            "provider": reply.provider,
            "latency_ms": reply.latency_ms,
            "attempts": reply.attempts,
            "json_retries": reply.json_retries,
            "usage": reply.usage,
            "purpose": request.purpose,
        }
        self.flush()
        return reply

    def flush(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )


def make_port(config: str, *, cache: Optional[Path] = None, mock: bool = False) -> Any:
    if mock:
        inner: Any = MockProviderPort()
    elif config == "C1":
        inner = OllamaProviderPort()
    elif config == "C2":
        inner = NvidiaProviderPort()
    else:
        raise ValueError(f"la configuracion {config!r} no usa proveedor")
    return CachingPort(inner, cache)


# --------------------------------------------------------------------------
# Ejecucion
# --------------------------------------------------------------------------
@dataclass
class RunResult:
    """Salida de una configuracion, lista para puntuar."""

    config: str
    output: ExtractionOutput
    wall_ms: int
    performance: dict = field(default_factory=dict)
    provider: str = "local"
    model: Optional[str] = None


def run_config(
    config: str,
    ctx: ExtractionContext,
    *,
    port: Any = None,
    prior: Optional[dict[str, RunResult]] = None,
) -> RunResult:
    """Ejecuta una configuracion y devuelve sus propuestas y su coste real."""
    started = time.monotonic()
    if config == "A":
        pipeline = ExtractionPipeline.local_default()
        out = pipeline.run(ctx)
        return RunResult("A", out, int((time.monotonic() - started) * 1000))

    if config in ("C1", "C2"):
        if port is None:
            raise ValueError(f"{config} necesita un puerto de inferencia")
        extractor = SemanticEpisodeExtractor(port)
        out = extractor.extract(ctx)
        return RunResult(
            config,
            out,
            int((time.monotonic() - started) * 1000),
            performance=extractor.performance(),
            provider=extractor.info.provider.value,
            model=extractor.info.model,
        )

    if config == "D":
        # UNION, no fusion: ids separados, origen conservado, duplicados
        # incluidos. Sin reconciliador, mezclarlos aqui seria inventarse el
        # resultado del bloque siguiente.
        if not prior or "A" not in prior or "C1" not in prior:
            raise ValueError("D necesita A y C1 ya ejecutados")
        union = ExtractionOutput()
        union.extend(prior["A"].output)
        union.extend(prior["C1"].output)
        return RunResult(
            "D",
            union,
            prior["A"].wall_ms + prior["C1"].wall_ms,
            performance=prior["C1"].performance,
            provider="local+" + prior["C1"].provider,
            model=prior["C1"].model,
        )
    raise ValueError(f"configuracion desconocida: {config!r}")


# --------------------------------------------------------------------------
# Metricas propias del bloque
# --------------------------------------------------------------------------
def _gold_predicate(claim: dict) -> Optional[str]:
    cands = claim.get("predicate_candidates") or []
    return cands[0]["predicate"] if cands else None


def _gold_direction(claim: dict) -> Optional[str]:
    cands = claim.get("direction_candidates") or []
    return cands[0]["direction"] if cands else None


def block_metrics(
    gold: GoldDataset,
    pred: PredictionBundle,
    config: MatchConfig,
    lexicon: Lexicon,
) -> dict[str, Any]:
    """Metricas que el arnes no trae y este bloque necesita.

    La de cabecera es **recall top-2 de predicado**: el extractor no tiene que
    acertar el predicado final —eso lo decide el motor—, tiene que conseguir que
    el correcto LLEGUE como candidato. Se da en dos denominadores y los dos se
    publican: sobre los claims emparejados (que mide el acierto cuando el claim
    existe) y sobre el gold ENTERO (que no perdona los claims que no se
    propusieron). El segundo es el que manda.
    """
    mention_match = match_spans(gold.mentions, pred.mentions, id_field="mention_id", config=config)
    alignment = build_alignment(mention_match)
    gold_m = index_by(gold.mentions, "mention_id")
    pred_m = index_by(pred.mentions, "mention_id")
    frag_ids = {f["fragment_id"] for f in gold.fragments}
    # Texto GOLD del episodio (no el de la prediccion) mas el literal de sus
    # fragmentos: es la unica fuente contra la que tiene sentido comprobar si
    # una superficie existe. `reference_text` NO vale para esto: en los
    # episodios OCR es el texto CORREGIDO, y una superficie degradada
    # legitima ("Daiki Oliaru") parece inventada al compararla con el.
    texto_gold: dict[str, str] = {e["episode_id"]: (e.get("text") or "") for e in gold.episodes}
    for f in gold.fragments:
        texto_gold[f["episode_id"]] = texto_gold.get(f["episode_id"], "") + "\n" + (
            f.get("literal_text") or ""
        )
    normalizado = {k: normalize(v) for k, v in texto_gold.items()}

    # --- menciones -------------------------------------------------------
    conocidas = {normalize(s) for e in lexicon.entries for s in e.surfaces()}
    no_ancladas = 0
    inventadas = 0
    no_literales = 0
    ejemplos_inventadas: list[str] = []
    for m in pred.mentions:
        frags = m.get("evidence_fragment_ids") or []
        if not frags or any(f not in frag_ids for f in frags):
            no_ancladas += 1
        surface = str(m.get("surface", ""))
        texto = texto_gold.get(m["episode_id"], "")
        # Dos comprobaciones INDEPENDIENTES del extractor, y distintas:
        #  - inventada: la superficie no esta en el texto gold ni normalizando;
        #  - no literal: esta, pero lo emitido no es lo que dice el texto en
        #    ese tramo (tipico de emparejar por lexico y emitir la forma
        #    canonica). No es una alucinacion, y contarlo como tal seria
        #    exagerar; ocultarlo, tambien.
        if surface and normalize(surface) not in normalizado.get(m["episode_id"], ""):
            inventadas += 1
            if len(ejemplos_inventadas) < 8:
                ejemplos_inventadas.append(surface)
        elif surface and texto and surface not in texto:
            no_literales += 1
    nuevas = sorted(
        {
            str(m.get("surface"))
            for m in pred.mentions
            if normalize(str(m.get("surface", ""))) not in conocidas
        }
    )
    nuevas_correctas = sorted(
        {
            str(pred_m[p].get("surface"))
            for _g, p in mention_match.pairs
            if normalize(str(pred_m[p].get("surface", ""))) not in conocidas
        }
    )
    tipo_ok = sum(
        1
        for g, p in mention_match.pairs
        if (gold_m[g].get("type_candidates") or [{}])[0].get("type")
        == (pred_m[p].get("type_candidates") or [{}])[0].get("type")
    )

    # --- claims ----------------------------------------------------------
    gold_claims = gold.claims_for("extractor")
    gold_by_id = index_by(gold_claims, "claim_id")
    activos = [c for c in pred.claims if not c.get("abstained")]
    abstenidos = [c for c in pred.claims if c.get("abstained")]
    gold_keyed = [
        {"claim_id": c["claim_id"], "_key": claim_key(c, {m: m for m in gold_m}, config)}
        for c in gold_claims
    ]
    pred_keyed = [
        {"claim_id": c["claim_id"], "_key": claim_key(c, alignment, config)} for c in activos
    ]
    match = match_by_key(gold_keyed, pred_keyed, id_field="claim_id", key_fn=lambda c: c["_key"])
    pred_by_id = index_by(activos, "claim_id")

    top1 = top2 = dir_top1 = 0
    predicados_fuera = 0
    for g, p in match.pairs:
        gp = _gold_predicate(gold_by_id[g])
        cands = [c["predicate"] for c in (pred_by_id[p].get("predicate_candidates") or [])]
        if cands[:1] == [gp]:
            top1 += 1
        if gp in cands[:2]:
            top2 += 1
        gd = _gold_direction(gold_by_id[g])
        pd = (pred_by_id[p].get("direction_candidates") or [{}])[0].get("direction")
        if gd is not None and gd == pd:
            dir_top1 += 1
    ontologia = set(
        p["predicate"] for p in gold.profiles["generic"]["predicates"]
    )
    for c in activos:
        for cand in c.get("predicate_candidates") or []:
            if cand["predicate"] not in ontologia:
                predicados_fuera += 1

    claims_anclados = sum(
        1
        for c in pred.claims
        if (c.get("evidence_fragment_ids") or [])
        and all(f in frag_ids for f in c["evidence_fragment_ids"])
    )
    inventados = sum(
        1
        for c in activos
        if any(
            m not in pred_m and m not in gold_m
            for m in (c.get("subject_mentions") or []) + (c.get("object_mentions") or [])
        )
    )

    def _ratio(num: int, den: int) -> Optional[float]:
        return round(num / den, 4) if den else None

    negacion = negation_metrics(gold_claims, gold_by_id, pred, activos, pred_by_id, match)

    return {
        "mentions": {
            "gold": len(gold.mentions),
            "predicted": len(pred.mentions),
            "tp": mention_match.tp,
            "fp": mention_match.fp,
            "fn": mention_match.fn,
            "precision": _ratio(mention_match.tp, mention_match.tp + mention_match.fp),
            "recall": _ratio(mention_match.tp, mention_match.tp + mention_match.fn),
            "unanchored": no_ancladas,
            "hallucinated_surfaces": inventadas,
            "hallucinated_examples": ejemplos_inventadas,
            "surface_not_literal": no_literales,
            "type_correct_matched": tipo_ok,
            "type_accuracy_matched": _ratio(tipo_ok, mention_match.tp),
            "new_surfaces_proposed": len(nuevas),
            "new_surfaces_matching_gold": len(nuevas_correctas),
            "new_surfaces_examples": nuevas_correctas[:12],
        },
        "claims": {
            "gold": len(gold_claims),
            # Techo real de las metricas de claim ACTIVO: los claims gold que
            # son ABSTENCIONES no se pueden acertar proponiendo un claim. En dev
            # hay uno, asi que el maximo de `recall` es 19/20 = 0.95. Se declara
            # aqui para que nadie lea 0.95 como un fallo del extractor.
            "gold_active_ceiling": len([c for c in gold_claims if not c.get("abstained")]),
            "predicted_active": len(activos),
            "predicted_abstained": len(abstenidos),
            "tp": match.tp,
            "fp": match.fp,
            "fn": match.fn,
            "precision": _ratio(match.tp, match.tp + match.fp),
            "recall": _ratio(match.tp, match.tp + match.fn),
            "predicate_top1_matched": _ratio(top1, match.tp),
            "predicate_top2_matched": _ratio(top2, match.tp),
            "predicate_top1_recall": _ratio(top1, len(gold_claims)),
            "predicate_top2_recall": _ratio(top2, len(gold_claims)),
            "direction_top1_matched": _ratio(dir_top1, match.tp),
            "direction_top1_recall": _ratio(dir_top1, len(gold_claims)),
            "predicates_outside_ontology": predicados_fuera,
            "evidence_anchored": claims_anclados,
            "evidence_anchored_rate": _ratio(claims_anclados, len(pred.claims)),
            "claims_with_invented_arguments": inventados,
        },
        "negation": negacion,
    }


def negation_metrics(
    gold_claims: Sequence[dict],
    gold_by_id: dict,
    pred: PredictionBundle,
    activos: Sequence[dict],
    pred_by_id: dict,
    match: Any,
) -> dict[str, Any]:
    """Metricas de NEGACION. Cinco numeros, y el cuarto es el que importa.

    * `gold_negated`          negativos que hay en el gold;
    * `predicted_negated`     negativos propuestos como claim afirmado;
    * `correct_negated`       emparejados con un gold negativo y marcados;
    * `negated_as_abstention` negativos del gold que salieron como ABSTENCION.
      No es un acierto, pero tampoco un error grave: se vio algo y no se afirmo
      lo contrario;
    * `positive_created_for_negated_gold` **el error caro**: un gold negativo
      propuesto como relacion POSITIVA. Es exactamente lo que este bloque existe
      para que no ocurra;
    * `cessation_*`           cuantas cesaciones se detectaron y cuantas piden
      resolucion temporal, que es lo que el motor necesita para cerrar vigencias.

    `negation_kind` vive en `metadata` (excepcion documentada al contrato
    congelado), asi que se lee de ahi y de ningun otro sitio.
    """
    gold_neg = [c for c in gold_claims if c.get("negated")]
    emparejados = {g: p for g, p in match.pairs}
    correctos = 0
    positivos_erroneos = 0
    for gid in (c["claim_id"] for c in gold_neg):
        pid = emparejados.get(gid)
        if pid is None:
            continue
        if pred_by_id[pid].get("negated"):
            correctos += 1
        else:
            positivos_erroneos += 1

    abstenidos_neg = 0
    for claim in pred.claims:
        if not claim.get("abstained"):
            continue
        razones = set((claim.get("metadata") or {}).get("abstention_reasons") or ())
        if razones & {
            "NEGATION_CONTEXT_MISMATCH",
            "NEGATION_NOT_IN_EVIDENCE",
            "REVIEW_NEGATION_SCOPE",
        }:
            abstenidos_neg += 1

    kinds: dict[str, int] = {}
    for claim in activos:
        kind = (claim.get("metadata") or {}).get("negation_kind")
        if kind:
            kinds[kind] = kinds.get(kind, 0) + 1
    cesaciones = kinds.get("CESSATION", 0)
    cesaciones_con_temporal = sum(
        1
        for c in activos
        if (c.get("metadata") or {}).get("negation_kind") == "CESSATION"
        and (c.get("metadata") or {}).get("temporal_resolution_required")
    )

    return {
        "gold_negated": len(gold_neg),
        "predicted_negated": sum(1 for c in activos if c.get("negated")),
        "correct_negated": correctos,
        "negated_as_abstention": abstenidos_neg,
        "positive_created_for_negated_gold": positivos_erroneos,
        "kinds": dict(sorted(kinds.items())),
        "cessation_detected": cesaciones,
        "cessation_with_temporal_flag": cesaciones_con_temporal,
    }


def to_bundle(result: RunResult, ctx: ExtractionContext) -> PredictionBundle:
    """Propuestas -> `PredictionBundle` del arnes, con recursos reportados."""
    metadata: dict[str, Any] = {"latency_ms": result.wall_ms}
    if result.performance:
        metadata["provider_calls"] = result.performance.get("provider_calls", 0)
        metadata["performance"] = result.performance
    return PredictionBundle(
        split=SPLIT,
        ablation="local_only" if result.config == "A" else "unspecified",
        subsystem="extractor",
        run_id=f"semantic-bench-{result.config}",
        episodes=[e.to_dict() for e in ctx.episodes],
        fragments=[f.to_dict() for f in ctx.fragments],
        mentions=[m.to_dict() for m in result.output.mentions],
        claims=[c.to_dict() for c in result.output.claims],
        metadata=metadata,
    )


def score(result: RunResult, gold: GoldDataset, ctx: ExtractionContext) -> dict[str, Any]:
    bundle = to_bundle(result, ctx)
    config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
    informe = harness_run(gold, bundle, config=config)
    diagnosticos: dict[str, int] = {}
    for d in result.output.diagnostics:
        diagnosticos[d.code] = diagnosticos.get(d.code, 0) + 1
    return {
        "config": result.config,
        "provider": result.provider,
        "model": result.model,
        "wall_ms": result.wall_ms,
        "harness_extractor": informe["extractor"],
        "block_metrics": block_metrics(gold, bundle, config, ctx.lexicon),
        "performance": result.performance or {"status": "not_evaluated", "reason": "sin proveedor"},
        "diagnostics": dict(sorted(diagnosticos.items())),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="semantic_bench", description=__doc__)
    parser.add_argument("--config", action="append", choices=CONFIGS, required=True)
    parser.add_argument("--cache", type=Path, default=None, help="cache de respuestas del modelo")
    parser.add_argument("--mock", action="store_true", help="puerto guionizado (sin red)")
    parser.add_argument("--out", type=Path, default=None, help="fichero JSON de salida")
    args = parser.parse_args(argv)

    gold = load_gold(SPLIT)
    ctx = build_context(gold)
    resultados: dict[str, RunResult] = {}
    informes = []
    for config in args.config:
        port = (
            make_port(config, cache=args.cache, mock=args.mock)
            if config in ("C1", "C2")
            else None
        )
        resultados[config] = run_config(config, ctx, port=port, prior=resultados)
        informe = score(resultados[config], gold, ctx)
        if port is not None:
            informe["cache"] = {"hits": port.hits, "misses": port.misses}
            port.flush()
        informes.append(informe)
        print(json.dumps(informe, ensure_ascii=False, indent=1, sort_keys=True))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {"split": SPLIT, "reports": informes}, ensure_ascii=False, indent=1, sort_keys=True
            ),
            encoding="utf-8",
        )
    return 0


__all__ = [
    "CONFIGS",
    "SPLIT",
    "CachingPort",
    "RunResult",
    "block_metrics",
    "build_context",
    "negation_metrics",
    "make_port",
    "run_config",
    "score",
    "to_bundle",
]


if __name__ == "__main__":  # pragma: no cover - entrada de linea de comandos
    sys.exit(main())
