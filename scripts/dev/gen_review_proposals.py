# -*- coding: utf-8 -*-
"""Genera propuestas REALES para el entorno temporal review-v3-test.

Ruta completa: bytes -> normalizador -> extractores -> reconciliador ->
resolutor -> motor -> exportador de revision. Sin Neo4j y sin writer
(driver que estalla si alguien lo mira). Uso puntual del orquestador;
NO forma parte de la suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent
for p in (str(_APP), str(_APP / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_knowledge_v3_e2e_fixtures import (  # noqa: E402
    NOW,
    WORKSPACE,
    ExplodingDriver,
    base_config,
    gold_dev,
    snapshot_entities,
)

from knowledge_v3.multimodal.base import IngestOptions, SourceInput  # noqa: E402
from knowledge_v3.pipeline import KnowledgePipeline  # noqa: E402
from knowledge_v3.pipeline.pipeline import SourceCase  # noqa: E402

TEXTS = {
    "rev-01-negacion": "Daiki Oharu no pertenece a la Casa del Ciervo.",
    "rev-02-cesacion": "Ilaria Vandreth ya no lidera la Casa del Ciervo.",
    "rev-03-no-dejo": "Mira Cauce no dejó de servir a la Orden del Alba.",
    "rev-04-hecho": "Daiki Oharu pertenece a la Casa del Ciervo.",
    "rev-05-nunca": "Runa Belisa nunca perteneció al Gremio de los Faroles.",
}


def case(source_id: str, text: str) -> SourceCase:
    return SourceCase(
        source_id=source_id,
        source=SourceInput(
            data=text.encode("utf-8"),
            original_name=f"{source_id}.md",
            original_location=f"mem://{source_id}",
            mime_type="text/markdown",
            source_kind="MARKDOWN",
        ),
        ingest_options=IngestOptions(
            workspace=WORKSPACE,
            collection_id="collection:review-v3-test",
            ingested_at=NOW,
            created_at=NOW,
        ),
    )


def main(out_dir: str) -> None:
    gold = gold_dev()
    entities = snapshot_entities(gold)
    pipeline = KnowledgePipeline(base_config(gold, writer_driver=ExplodingDriver()))
    result = pipeline.run(
        [case(sid, text) for sid, text in TEXTS.items()],
        catalog_entities=entities,
        review_proposals_dir=Path(out_dir),
    )
    for run in result.runs:
        print(run.source_id, [d.decision for d in run.decisions])


if __name__ == "__main__":
    main(sys.argv[1])
