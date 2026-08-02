# -*- coding: utf-8 -*-
"""Puerta 4, bloque B1: cableado del carril OCR (proveedor FALSO, sin binario).

Estas pruebas NO necesitan Tesseract instalado: usan un `VisualProvider` de
mentira que declara su propio texto y confianza, exactamente el mismo puerto
que usaria un proveedor real (`multimodal.adapters.visual.VisualProvider`).
Lo que se comprueba es el CABLEADO: que una fuente `ambar-escaneo` renderizada
a imagen (`pipeline.ocr_render`) y pasada por `visual_provider` llega a
producir episodios `OCR_TEXT`, claims deterministas y evidencia anclada -- y
que sin proveedor (o con uno de confianza baja) el sistema es fail-closed:
nunca inventa texto y nunca autoaprueba lo que no puede respaldar.

Las pruebas REALES con Tesseract de verdad (imagenes sinteticas, PIL, frases
de negacion nuevas) viven en `test_gate4_b1_ocr_real.py` y se saltan si el
binario no esta instalado.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

# `pipeline.__init__` importa un reportero de RSS opcional que no existe en
# Windows; el mismo shim que usan las pruebas multimodales reales.
try:  # pragma: no cover - rama de plataforma
    import resource as _resource  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    sys.modules["resource"] = SimpleNamespace(RUSAGE_SELF=0)

from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.eval.ocr_lane import SOURCE_ID, SPLIT, measure_ocr_lane
from knowledge_v3.multimodal.adapters.visual import MODE_DESCRIPTION, MODE_OCR, VisualResult
from knowledge_v3.pipeline.ocr_render import render_source_image, renderable


def _gold_texts() -> dict[str, str]:
    gold = load_gold(SPLIT)
    source = next(s for s in gold.sources if s.source_id == SOURCE_ID)
    return {e["episode_id"]: e["text"] for e in source.episodes}


class _FakeVisualProvider:
    """Proveedor de pruebas: devuelve el texto gold con la confianza pedida."""

    provider_kind = "local"

    def __init__(self, texts: dict[str, str], *, confidence: float = 0.95) -> None:
        self._texts = texts
        self._confidence = confidence

    def recognize(self, request):
        if request.mode != MODE_OCR:
            return None
        text = self._texts.get(request.region.region_id, "")
        if not text:
            return None
        return VisualResult(
            mode=MODE_OCR,
            region_id=request.region.region_id,
            confidence=self._confidence,
            text=text,
            provider="local",
            name="fake-ocr",
            version="1",
        )


# --------------------------------------------------------------------------
# 1. `ocr_render`: la imagen sintetica es real y sus regiones son coherentes
# --------------------------------------------------------------------------
def test_render_source_image_produces_a_real_decodable_png():
    from PIL import Image
    import io

    texts = _gold_texts()
    gold = load_gold(SPLIT)
    source = next(s for s in gold.sources if s.source_id == SOURCE_ID)
    episodes = sorted(source.episodes, key=lambda e: e["sequence"])
    assert renderable(episodes)

    png, regions = render_source_image(episodes)
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        assert image.size[1] >= len(episodes)

    assert len(regions) == len(episodes)
    for region, episode in zip(regions, episodes):
        assert region["mode"] == "OCR"
        assert region["region_id"] == episode["episode_id"]
        bbox = region["bbox"]
        assert 0.0 <= bbox["y"] < 1.0
        assert bbox["height"] == 1.0 / len(episodes)


def test_render_source_image_rejects_mixed_or_empty_episodes():
    import pytest
    from knowledge_v3.pipeline.ocr_render import render_source_image

    with pytest.raises(ValueError):
        render_source_image([{"text": "", "modality": "OCR_TEXT", "episode_id": "e1"}])
    with pytest.raises(ValueError):
        render_source_image(
            [{"text": "algo", "modality": "IMAGE", "episode_id": "e1"}]
        )


# --------------------------------------------------------------------------
# 2. Fail-closed: sin proveedor, cero claims y ningun texto inventado
# --------------------------------------------------------------------------
def test_without_visual_provider_the_lane_stays_fail_closed():
    report = measure_ocr_lane(visual_provider=None)
    assert report["provider"]["bound"] is False
    assert report["episodes"]["ocr_text_produced"] == 0
    assert report["claims"]["produced"] == 0
    # Ni una sola fuga: cero claims tambien es cero violaciones de la regla de
    # oro, no una casilla vacia por casualidad.
    assert report["claims"]["golden_rule_violations"] == []


# --------------------------------------------------------------------------
# 3. Con proveedor de pruebas: el carril completo produce claims anclados
# --------------------------------------------------------------------------
def test_with_fake_visual_provider_the_lane_recovers_text_and_anchors_claims():
    texts = _gold_texts()
    report = measure_ocr_lane(visual_provider=_FakeVisualProvider(texts, confidence=0.95))

    assert report["provider"]["bound"] is True
    assert report["episodes"]["ocr_text_produced"] == len(texts)
    assert report["episodes"]["exact_literal_recovery"] == len(texts)
    assert report["claims"]["produced"] > 0
    # Regla de oro corpus-wide: TODO claim producido por este carril esta
    # anclado a texto OCR real y ninguno viola la disciplina de revision.
    assert report["claims"]["evidence_anchored"] == report["claims"]["produced"]
    assert report["claims"]["golden_rule_violations"] == []
    for row in report["rows"]:
        assert row["evidence_anchored"] is True
        assert row["golden_rule_respected"] is True


# --------------------------------------------------------------------------
# 4. Regla de oro: confianza OCR baja => revision obligatoria, nunca autoaprobado
# --------------------------------------------------------------------------
def test_low_confidence_ocr_forces_review_never_auto_approved():
    texts = _gold_texts()
    report = measure_ocr_lane(
        visual_provider=_FakeVisualProvider(texts, confidence=0.2)
    )
    assert report["episodes"]["ocr_text_produced"] == len(texts)
    if report["claims"]["produced"] == 0:
        # Con confianza tan baja el determinista puede preferir no proponer
        # nada; sigue siendo fail-closed (cero es una respuesta valida).
        assert report["claims"]["golden_rule_violations"] == []
        return
    for row in report["rows"]:
        assert row["low_confidence_episode"] is True
        assert row["review_required"] is True
        assert row["golden_rule_respected"] is True


# --------------------------------------------------------------------------
# 5. `measure_ocr_lane_with_tesseract` no revienta si el binario no esta
# --------------------------------------------------------------------------
def test_measure_with_tesseract_degrades_cleanly_without_binary(monkeypatch):
    from knowledge_v3.eval import ocr_lane

    def _boom():
        raise ocr_lane.OcrLaneUnavailable("tesseract no encontrado (prueba)")

    monkeypatch.setattr(ocr_lane, "_tesseract_provider", _boom)
    report = ocr_lane.measure_ocr_lane_with_tesseract()
    assert report["provider"]["bound"] is False
    assert "unavailable_reason" in report["provider"]
    assert report["claims"]["produced"] == 0
