# -*- coding: utf-8 -*-
"""`PipelineResult` -> `PredictionBundle` del arnes.

El arnes de `benchmarks/` no ejecuta nada: puntua un fichero de predicciones
contra el gold. Este modulo es la pieza que faltaba entre "el sistema corrio" y
"el arnes puede puntuarlo", y no hace mas que serializar: cada documento sale
con `to_dict()` del contrato, sin filtrar, sin reordenar y sin corregir.

Recursos (`latency_ms`, `provider_calls`, ...) se copian de la corrida real. El
arnes los publica tal cual y nunca los estima; si se inventaran aqui, la regla
"todo numero sale de un conteo" quedaria rota justo en el punto donde nadie
mira.
"""
from __future__ import annotations

import resource
from typing import Any, Optional

from ..benchmarks.loader import PredictionBundle
from .pipeline import PipelineResult


def peak_rss_mb() -> float:
    """RSS maximo del proceso, medido. En Linux `ru_maxrss` viene en KiB."""
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 3)


def to_bundle(
    result: PipelineResult,
    *,
    split: str,
    run_id: str,
    subsystem: str = "e2e",
    ablation: Optional[str] = None,
    external_cost_usd: float = 0.0,
    extra_metadata: Optional[dict[str, Any]] = None,
) -> PredictionBundle:
    """Serializa la corrida en el formato que `harness.run()` acepta.

    `split` lo declara quien corre: el orquestador no lo deduce del gold, para
    que medir un split contra otro siga siendo el error duro que el arnes ya
    detecta en vez de un acierto accidental.

    LOS EPISODIOS Y FRAGMENTOS NO SIEMPRE VIAJAN. Si la cadena entro por
    episodios (`SourceCase` sin bytes), esos documentos son el GOLD, no una
    prediccion: publicarlos daria un normalizador con 1.0 en deteccion de
    episodios y 1.0 en cobertura sin que el normalizador se hubiera ejecutado.
    Es exactamente la mentira que este bloque existe para no contar, asi que la
    seccion sale `not_evaluated` y el informe dice por que.
    """
    entered_at_episodes = any(
        any(d["code"] == "PIPELINE_ENTERED_AT_EPISODES" for d in r.diagnostics)
        for r in result.runs
    )
    metadata: dict[str, Any] = {
        "latency_ms": round(result.latency_ms, 3),
        "peak_rss_mb": peak_rss_mb(),
        "provider_calls": result.provider_calls,
        "external_cost_usd": external_cost_usd,
        "pipeline": dict(result.config_declared),
        "sources": [r.summary() for r in result.runs],
        "normalizer_executed": not entered_at_episodes,
    }
    if entered_at_episodes:
        metadata["normalizer_omitted_reason"] = (
            "la cadena entro por episodios: esos documentos son el gold, no una "
            "prediccion, y publicarlos puntuaria un normalizador que no corrio"
        )
    if extra_metadata:
        metadata.update(extra_metadata)

    return PredictionBundle(
        split=split,
        ablation=ablation or result.config_declared.get("ablation", "unspecified"),
        subsystem=subsystem,
        run_id=run_id,
        episodes=[] if entered_at_episodes else [e.to_dict() for e in result.episodes],
        fragments=[] if entered_at_episodes else [f.to_dict() for f in result.fragments],
        mentions=[m.to_dict() for m in result.mentions],
        resolutions=[r.to_dict() for r in result.resolutions],
        claims=[c.to_dict() for c in result.claims],
        decisions=[d.to_contract_dict() for d in result.decisions],
        assertions=[a.to_dict() for a in result.assertions],
        plans=[p.to_dict() for p in result.plans],
        metadata=metadata,
    )


__all__ = ["peak_rss_mb", "to_bundle"]
