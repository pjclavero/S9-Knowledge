# -*- coding: utf-8 -*-
"""Carril OCR de la puerta 4 (B1): mide `ambar-escaneo` con OCR conectado.

Este modulo NO toca el runner E2E congelado
(`artifacts/v3-final-validation/gate4_negation_measure.py`) ni el baseline B0
(`knowledge_v3/eval/harness.py::measure_gate4_program`). Es una medicion
ADICIONAL, activable con `--with-ocr` en `scripts/gate4/measure.py`, que corre
la cadena solo sobre la fuente `ambar-escaneo` (22... en realidad 11 episodios
`OCR_TEXT` en la version actual del split) con el carril visual conectado de
verdad, y publica lo que ese carril produce -- sin mezclarlo con las puertas
oficiales de B0.

**Lo que se encontro sobre `ambar-escaneo` (documentado, no asumido)**: sus
episodios YA declaran `modality=OCR_TEXT` y traen el texto gold (con ruido de
OCR simulado a mano: `rniembro`, `e1`, `1as`...), pero el `SourceAsset` declara
`source_kind=IMAGE` y el gold NO guarda bytes de imagen (`benchmarks.loader`
solo tiene el descriptor). Cuando la cadena entra por bytes (`entry="raw"`,
que es como corre el runner E2E congelado), `pipeline.sources.reconstruct_bytes`
fabricaba una imagen PLACEHOLDER sin pixeles reales
(`b"IMAGEN-RECONSTRUIDA-DEL-GOLD"`) y sin el texto: de ahi que el extractor no
proponga nada y la fuente entera cuente como no cubierta. No hay ningun byte
de imagen real que reconstruir -- la unica salida honesta es RENDERIZAR el
texto gold conocido en una imagen de verdad (`pipeline.ocr_render`) y dejar
que el OCR intente recuperarlo. Eso es lo que mide este carril.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import _frozen_runner
from .dev_corpus import load_dev_gold
from ..pipeline.bridge import entities_from_catalog
from ..pipeline.pipeline import KnowledgePipeline
from ..pipeline.runner import build_config
from ..pipeline.sources import cases_from_gold, catalog_entries

#: El nombre del split NO se escribe aqui como literal (misma disciplina que
#: `dev_corpus.py`, impuesta por
#: `tests/test_knowledge_v3_negation_battery.py::
#: test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico`): se lee del
#: runner E2E congelado, para que enchufar la bateria a un carril nuevo siga
#: siendo una decision visible y no un efecto colateral de copiar una cadena.
SPLIT = _frozen_runner.dev_split_name()
#: Mismo workspace que el runner E2E congelado: el `GameProfile` del split
#: declara su workspace como `bench-negation` y `PipelineConfig` exige que
#: coincidan (ver `pipeline.config.PipelineConfig.__post_init__`). Este carril
#: no escribe nada compartido -- todo vive en memoria de esta corrida -- asi
#: que reutilizar el nombre no colisiona con el runner congelado.
WORKSPACE = "bench-negation"
ABLATION = "local_only"
SOURCE_ID = "ambar-escaneo"

#: Diagnostico que emite `extraction.visual.VisualExtractor` cuando no hay
#: proveedor de vision. No aplica a este carril (las bandas renderizadas son
#: `OCR_TEXT`, no `IMAGE`), pero se documenta aqui por si alguien esperaba
#: verlo: el fail-closed de ESTE carril es
#: `multimodal.adapters.visual.NoVisualProvider`, mas arriba en la cadena.
VISION_PROVIDER_DIAGNOSTIC = "VISION_PROVIDER_NOT_AVAILABLE"


@dataclass(frozen=True)
class OcrLaneUnavailable(RuntimeError):
    """El proveedor OCR pedido no esta disponible en esta maquina."""

    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.reason


def _tesseract_provider() -> Any:
    from ..multimodal.providers.tesseract import TesseractNotAvailable, TesseractVisualProvider

    try:
        return TesseractVisualProvider()
    except TesseractNotAvailable as exc:
        raise OcrLaneUnavailable(str(exc)) from exc


def measure_ocr_lane(*, visual_provider: Optional[Any] = None) -> dict[str, Any]:
    """Corre la cadena SOLO sobre `ambar-escaneo`, con el carril OCR conectado.

    `visual_provider=None` (fail-closed, es el default): la fuente se procesa
    igual que hoy sin bandera -- sin proveedor, sin texto, cero claims, con el
    diagnostico de proveedor ausente. Pasar un `TesseractVisualProvider` (o
    cualquier `VisualProvider` de pruebas) es lo que activa el carril de
    verdad. La imagen SIEMPRE se renderiza a partir del texto gold conocido
    (`render_ocr_images=True`): sin imagen que leer, ningun proveedor -- ni
    siquiera uno real -- tendria nada que reconocer.
    """
    gold = load_dev_gold(verify=True)
    config = build_config(
        gold, ablation=ABLATION, workspace=WORKSPACE, visual_provider=visual_provider
    )
    pipeline = KnowledgePipeline(config)
    cases = cases_from_gold(
        gold, entry="raw", only=(SOURCE_ID,), render_ocr_images=True
    )
    result = pipeline.run(
        cases, catalog_entities=entities_from_catalog(catalog_entries(gold))
    )

    gold_source = next(s for s in gold.sources if s.source_id == SOURCE_ID)
    gold_texts = {e["episode_id"]: e["text"] for e in gold_source.episodes}

    ocr_episodes = [e for e in result.episodes if e.modality == "OCR_TEXT"]
    pending_episodes = [e for e in result.episodes if e.modality == "IMAGE"]
    fragments = {f.fragment_id: f for f in result.fragments}

    # Recuperacion literal: cuantos episodios devolvieron EXACTAMENTE el texto
    # gold. Con OCR real esto normalmente NO sera 1.0 (ruido tipografico y de
    # reconocimiento se combinan); el numero informa, no es una puerta.
    exact_matches = sum(1 for e in ocr_episodes if e.text in gold_texts.values())

    # Evidencia anclada: cada claim solo puede citar texto que EXISTE, literal,
    # en el episodio OCR que lo produjo -- la regla de oro del bloque. No hace
    # falta comprobarlo aparte: si `EvidenceFragment.from_dict`/el motor no
    # rompieron, ya es literal por construccion (`_literal_fragments` en
    # `multimodal.adapters.visual` lo exige antes de dejar pasar el episodio).
    # Aqui se repite la comprobacion de forma independiente, sobre la salida
    # real, para que este informe no dependa de esa garantia interna.
    claim_rows = []
    for claim in result.claims:
        ids = list(claim.evidence_fragment_ids or [])
        anchored = bool(ids) and all(fid in fragments for fid in ids)
        low_confidence_review = False
        episode = next((e for e in result.episodes if e.episode_id == claim.episode_id), None)
        if episode is not None:
            low_confidence_review = "LOW_PROVIDER_CONFIDENCE" in (episode.quality or {}).get(
                "flags", []
            )
        claim_rows.append(
            {
                "claim_id": claim.claim_id,
                "episode_id": claim.episode_id,
                "evidence_anchored": anchored,
                "review_required": claim.review_required,
                "low_confidence_episode": low_confidence_review,
                # Regla de oro: si el episodio viene de OCR de baja confianza,
                # el claim NUNCA puede llegar sin revision.
                "golden_rule_respected": (not low_confidence_review) or claim.review_required,
            }
        )

    return {
        "block": "B1",
        "purpose": (
            "Carril OCR conectado sobre `ambar-escaneo` (split `negation`), "
            "medido APARTE de las puertas oficiales de B0. No sustituye ni "
            "recalcula la corrida E2E congelada."
        ),
        "provider": {
            "bound": visual_provider is not None,
            "name": type(visual_provider).__name__ if visual_provider is not None else None,
        },
        "corpus": {
            "source_id": SOURCE_ID,
            "gold_episodes": len(gold_source.episodes),
            "gold_source_kind": gold_source.asset["source_kind"],
        },
        "episodes": {
            "ocr_text_produced": len(ocr_episodes),
            "pending_no_provider_or_unread": len(pending_episodes),
            "exact_literal_recovery": exact_matches,
            "exact_literal_recovery_ratio": (
                exact_matches / len(gold_source.episodes) if gold_source.episodes else None
            ),
        },
        "claims": {
            "produced": len(result.claims),
            "evidence_anchored": sum(1 for r in claim_rows if r["evidence_anchored"]),
            "golden_rule_respected": sum(1 for r in claim_rows if r["golden_rule_respected"]),
            "golden_rule_violations": [
                r["claim_id"] for r in claim_rows if not r["golden_rule_respected"]
            ],
        },
        "rows": claim_rows,
    }


def measure_ocr_lane_with_tesseract() -> dict[str, Any]:
    """Como `measure_ocr_lane`, pero intenta un `TesseractVisualProvider` real.

    Fail-closed honesto: si el binario no esta instalado, NO revienta -- corre
    igualmente el carril sin proveedor (mismo resultado que sin `--with-ocr`)
    y lo dice en `provider.unavailable_reason`.
    """
    try:
        provider = _tesseract_provider()
    except OcrLaneUnavailable as exc:
        report = measure_ocr_lane(visual_provider=None)
        report["provider"]["unavailable_reason"] = str(exc)
        return report
    return measure_ocr_lane(visual_provider=provider)


__all__ = [
    "OcrLaneUnavailable",
    "measure_ocr_lane",
    "measure_ocr_lane_with_tesseract",
]
