# -*- coding: utf-8 -*-
"""Puerta 4, bloque B1: ciclo COMPLETO imagen -> OCR real -> claims -> evidencia.

Se salta limpio si Tesseract no esta instalado en la maquina (no lo esta hoy
en esta maquina de desarrollo): se ejecutara de verdad el dia que el operador
instale el binario, igual que ya hace `test_knowledge_v3_multimodal_real.py`
para las pruebas de OCR a nivel de adaptador.

Lo que anade esta suite respecto a esas pruebas de adaptador: el ciclo
completo hasta CLAIM, sobre frases de negacion del estilo de la bateria del
split `negation` (no las mismas frases -- son nuevas, para no medir memoria),
renderizadas con PIL desde texto CONOCIDO y reconocidas por Tesseract de
verdad. El literal que ancla cada claim tiene que existir, byte a byte, en el
texto que el OCR realmente devolvio -- nunca en el texto que se penso dibujar.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

try:  # pragma: no cover - rama de plataforma
    import resource as _resource  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    sys.modules["resource"] = SimpleNamespace(RUSAGE_SELF=0)

from knowledge_v3.eval.ocr_lane import measure_ocr_lane
from knowledge_v3.multimodal.providers.tesseract import (
    TesseractNotAvailable,
    TesseractVisualProvider,
)
from knowledge_v3.pipeline.ocr_render import render_source_image


@pytest.fixture(scope="module")
def tesseract() -> TesseractVisualProvider:
    try:
        return TesseractVisualProvider()
    except TesseractNotAvailable as exc:
        pytest.skip(str(exc))


def test_ocr_lane_recovers_negation_phrases_end_to_end(tesseract):
    """El carril completo sobre `ambar-escaneo`, con Tesseract de verdad."""
    report = measure_ocr_lane(visual_provider=tesseract)

    assert report["provider"]["bound"] is True
    # Recuperacion literal EXACTA no se exige (Tesseract introduce su propio
    # ruido): lo que se exige es que produzca texto reconocible para todos los
    # episodios y que lo que llegue a claim este anclado a ESE texto.
    assert report["episodes"]["ocr_text_produced"] > 0
    assert report["claims"]["golden_rule_violations"] == []
    for row in report["rows"]:
        assert row["evidence_anchored"] is True
        assert row["golden_rule_respected"] is True


def _render_and_recognize(tesseract: TesseractVisualProvider, phrases: list[str]):
    """Renderiza frases NUEVAS (no las del split) y las hace pasar por OCR real."""
    episodes = [
        {"episode_id": f"synthetic-e{i:02d}", "text": phrase, "modality": "OCR_TEXT", "page": 1}
        for i, phrase in enumerate(phrases)
    ]
    png, regions = render_source_image(episodes)
    from knowledge_v3.multimodal.adapters.visual import MODE_OCR, VisualRegion, VisualRequest

    results = []
    for region_dict in regions:
        region = VisualRegion(
            bbox=region_dict["bbox"],
            region_id=region_dict["region_id"],
            page=region_dict["page"],
        )
        result = tesseract.recognize(
            VisualRequest(mode=MODE_OCR, region=region, data=png, mime_type="image/png", language_hint="es")
        )
        results.append(result)
    return results


def test_real_tesseract_recovers_new_negation_phrases_never_seen_in_the_split(tesseract):
    """Frases NUEVAS (no las de `ambar-escaneo`) para comprobar que el carril
    no memoriza el corpus: son negaciones del mismo estilo, con entidades
    inventadas para esta prueba.
    """
    phrases = [
        "Doria Ferro nunca presidio el Concejo del Puente.",
        "El Sello de Bruma dejo de pertenecer al gremio en el ano 88.",
    ]
    results = _render_and_recognize(tesseract, phrases)
    assert len(results) == len(phrases)
    for result in results:
        assert result is not None
        assert result.text
    # Palabras clave del literal deben sobrevivir al reconocimiento; el texto
    # completo puede diferir en puntuacion o mayusculas concretas.
    assert "Concejo" in results[0].text or "concejo" in results[0].text.lower()
    assert "Bruma" in results[1].text or "bruma" in results[1].text.lower()
