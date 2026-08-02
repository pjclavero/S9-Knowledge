# -*- coding: utf-8 -*-
"""Puerta 4, bloque B1 (carril OCR): bateria ADVERSARIAL del agente de tests.

Estas pruebas NO tocan el codigo entregado; solo lo ponen a prueba desde
angulos que la suite del implementador no cubria: byte-identidad de B0,
trampas en el renderizado sintetico, fail-closed ante proveedores mentirosos
o alucinados, el borde exacto del umbral de confianza 0.5, la bandera
`render_ocr_images` fuera de eval/tests, y si el ruido OCR simulado del gold
rompe la extraccion determinista.
"""
from __future__ import annotations

import inspect
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

try:  # pragma: no cover - rama de plataforma
    import resource as _resource  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    sys.modules["resource"] = SimpleNamespace(RUSAGE_SELF=0)

from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.eval.ocr_lane import SOURCE_ID, SPLIT, measure_ocr_lane
from knowledge_v3.multimodal.adapters.visual import MODE_OCR, VisualResult
from knowledge_v3.pipeline import sources as sources_mod
from knowledge_v3.pipeline.ocr_render import render_source_image

REPO_ROOT = Path(__file__).resolve().parents[3]


def _gold_texts() -> dict[str, str]:
    gold = load_gold(SPLIT)
    source = next(s for s in gold.sources if s.source_id == SOURCE_ID)
    return {e["episode_id"]: e["text"] for e in source.episodes}


class _FixedTextProvider:
    """Proveedor de pruebas que IGNORA la region y devuelve siempre el mismo
    texto, sin importar que banda de la imagen se le pida -- simula un OCR
    que alucina (o un OCR mal cableado que confunde regiones)."""

    provider_kind = "local"

    def __init__(self, text: str, *, confidence: float = 0.95) -> None:
        self._text = text
        self._confidence = confidence

    def recognize(self, request):
        if request.mode != MODE_OCR:
            return None
        return VisualResult(
            mode=MODE_OCR,
            region_id=request.region.region_id,
            confidence=self._confidence,
            text=self._text,
            provider="local",
            name="fixed-text-fake-ocr",
            version="1",
        )


class _EmptyTextProvider:
    """Proveedor que reconoce la region pero no obtiene texto (folio en blanco,
    reconocimiento fallido) -- debe degradar a pendiente, nunca a texto vacio
    fingido."""

    provider_kind = "local"

    def recognize(self, request):
        if request.mode != MODE_OCR:
            return None
        return VisualResult(
            mode=MODE_OCR,
            region_id=request.region.region_id,
            confidence=0.9,
            text="",
            provider="local",
            name="empty-fake-ocr",
            version="1",
        )


class _ConfidenceProvider:
    """Proveedor de confianza configurable, con el texto gold real."""

    provider_kind = "local"

    def __init__(self, texts: dict[str, str], confidence: float) -> None:
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


# ---------------------------------------------------------------------------
# 1. Baseline B0: byte-identico con y sin --with-ocr
# ---------------------------------------------------------------------------
def _run_measure(tmp_path: Path, extra_args: list[str]) -> tuple[Path, Path]:
    out_name = "adv-baseline"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "gate4" / "measure.py"),
        "--out-dir",
        str(tmp_path),
        "--out-name",
        out_name,
        *extra_args,
    ]
    env = {"PYTHONPATH": str(REPO_ROOT / "data-engine" / "app")}
    import os

    full_env = dict(os.environ)
    full_env.update(env)
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=full_env, capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, result.stderr
    return tmp_path / f"{out_name}.json", tmp_path / f"{out_name}.md"


def test_b0_baseline_byte_identical_to_committed_artifact_without_flag(tmp_path):
    committed = REPO_ROOT / "artifacts" / "gate4-program" / "b0-baseline.json"
    assert committed.exists()
    json_path, _ = _run_measure(tmp_path, [])
    assert json_path.read_bytes() == committed.read_bytes()


def test_with_ocr_flag_only_adds_corpora_ocr_lane_leaves_b0_untouched(tmp_path):
    committed = REPO_ROOT / "artifacts" / "gate4-program" / "b0-baseline.json"
    baseline = json.loads(committed.read_bytes())
    json_path, _ = _run_measure(tmp_path, ["--with-ocr"])
    with_ocr = json.loads(json_path.read_text())

    assert "ocr_lane" in with_ocr["corpora"]
    # Todo lo demas del informe (incluido el resto de `corpora`) debe ser
    # identico al baseline B0, campo a campo.
    stripped_corpora = dict(with_ocr["corpora"])
    del stripped_corpora["ocr_lane"]
    stripped_report = dict(with_ocr)
    stripped_report["corpora"] = stripped_corpora
    assert stripped_report == baseline


# ---------------------------------------------------------------------------
# 2. El renderizado PIL no hace trampa (sin canal lateral con el texto gold)
# ---------------------------------------------------------------------------
def test_rendered_png_has_real_nontrivial_pixels_and_no_side_channel():
    from PIL import Image

    texts = _gold_texts()
    gold = load_gold(SPLIT)
    source = next(s for s in gold.sources if s.source_id == SOURCE_ID)
    episodes = sorted(source.episodes, key=lambda e: e["sequence"])

    png, regions = render_source_image(episodes)

    # No metadatos de texto/comentario incrustados en el PNG (tEXt/iTXt/zTXt).
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        info = dict(image.info or {})
        combined_gold = " ".join(texts.values())
        for key, value in info.items():
            rendered = str(value)
            assert not any(
                gold_text and gold_text in rendered for gold_text in texts.values()
            ), f"metadato PNG {key!r} filtra texto gold: {rendered!r}"
        # El histograma no puede ser trivial (una imagen en blanco no tiene
        # nada que un OCR pueda leer).
        histogram = image.histogram()
        nonzero_buckets = sum(1 for count in histogram if count > 0)
        assert nonzero_buckets > 1, "histograma trivial: la imagen esta en blanco"
        assert image.size[0] > 0 and image.size[1] > 0

    # El texto gold tampoco puede colarse por el nombre de fichero/atributos
    # de las regiones devueltas (solo deben llevar bbox/mode/region_id/page).
    for region in regions:
        assert set(region.keys()) == {"region_id", "bbox", "mode", "page"}
        assert combined_gold not in json.dumps(region)


# ---------------------------------------------------------------------------
# 3. Fail-closed real: vacio y alucinado
# ---------------------------------------------------------------------------
def test_provider_returning_empty_text_produces_zero_claims_not_fake_text():
    report = measure_ocr_lane(visual_provider=_EmptyTextProvider())
    assert report["provider"]["bound"] is True
    # Texto vacio => el adaptador degrada a pendiente (IMAGE), no a OCR_TEXT.
    assert report["episodes"]["ocr_text_produced"] == 0
    assert report["claims"]["produced"] == 0
    assert report["claims"]["golden_rule_violations"] == []


def test_hallucinated_ocr_text_is_only_grounded_against_itself_not_the_image():
    """Un proveedor que devuelve SIEMPRE el mismo texto fijo (ignorando la
    imagen real) sigue produciendo episodios "anclados": el sistema no tiene
    forma de comprobar la fidelidad del OCR contra los pixeles, solo que el
    claim no cite mas alla de lo que el proveedor dijo. Esto es un LIMITE DE
    DISENO esperado (no hay grounding contra la imagen), no un fallo del
    carril -- pero conviene dejarlo documentado con numeros: si se alimentase
    un texto que SI dispara la bateria de negacion (aunque no sea el gold real
    de esa banda), el carril lo trata igual que si fuera correcto.
    """
    fixed_text = (
        "Doria Ferro nunca presidio el Concejo del Puente, segun las actas."
    )
    report = measure_ocr_lane(visual_provider=_FixedTextProvider(fixed_text, confidence=0.95))
    texts = _gold_texts()
    assert report["episodes"]["ocr_text_produced"] == len(texts)
    # Ninguna banda recupera el texto gold real (todas devuelven el fijo).
    assert report["episodes"]["exact_literal_recovery"] == 0
    # Pero cualquier claim que SI se produzca sigue marcado como "anclado":
    # el anclaje es interno (claim cita texto de su propio episodio), no
    # una verificacion cruzada con la imagen.
    for row in report["rows"]:
        assert row["evidence_anchored"] is True


# ---------------------------------------------------------------------------
# 4. Regla de oro en el borde exacto 0.5
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("confidence", [0.3])
def test_golden_rule_low_confidence_all_claims_review(confidence):
    texts = _gold_texts()
    report = measure_ocr_lane(visual_provider=_ConfidenceProvider(texts, confidence))
    assert report["episodes"]["ocr_text_produced"] == len(texts)
    produced = report["claims"]["produced"]
    assert produced > 0, "se esperaban claims para poder verificar la regla de oro"
    for row in report["rows"]:
        assert row["low_confidence_episode"] is True
        assert row["review_required"] is True
    assert report["claims"]["golden_rule_violations"] == []


def test_golden_rule_boundary_exactly_at_threshold_0_50():
    """En 0.50 exacto NINGUNA de las dos comprobaciones de "confianza baja"
    dispara (`LOW_PROVIDER_CONFIDENCE` compara con `<` estricto en
    `multimodal/quality.py::LOW_CONFIDENCE_THRESHOLD`, y `low_quality()` en
    `extraction/base.py` tambien usa `<` estricto): 0.50 cuenta como "buena".
    Documentado con numeros observados, no asumido.
    """
    texts = _gold_texts()
    report = measure_ocr_lane(visual_provider=_ConfidenceProvider(texts, 0.50))
    assert report["episodes"]["ocr_text_produced"] == len(texts)
    for row in report["rows"]:
        assert row["low_confidence_episode"] is False


def test_golden_rule_boundary_just_above_threshold_0_51():
    texts = _gold_texts()
    report = measure_ocr_lane(visual_provider=_ConfidenceProvider(texts, 0.51))
    for row in report["rows"]:
        assert row["low_confidence_episode"] is False


def test_golden_rule_boundary_just_below_threshold_0_49():
    texts = _gold_texts()
    report = measure_ocr_lane(visual_provider=_ConfidenceProvider(texts, 0.49))
    for row in report["rows"]:
        assert row["low_confidence_episode"] is True
        assert row["review_required"] is True


# ---------------------------------------------------------------------------
# 5. El flag OFF por defecto, en TODAS las firmas, y sin llamadores fuera de
#    eval/tests que lo enciendan.
# ---------------------------------------------------------------------------
def test_render_ocr_images_defaults_to_false_everywhere():
    for fn in (
        sources_mod.reconstruct_bytes,
        sources_mod.from_raw,
        sources_mod.cases_from_gold,
    ):
        sig = inspect.signature(fn)
        assert "render_ocr_images" in sig.parameters
        assert sig.parameters["render_ocr_images"].default is False


def test_render_ocr_images_true_only_used_in_eval_lane():
    import re

    pattern = re.compile(r"render_ocr_images\s*=\s*True")
    hits: list[str] = []
    for py_file in (REPO_ROOT / "data-engine" / "app").rglob("*.py"):
        if "__pycache__" in py_file.parts or "tests" in py_file.parts:
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            hits.append(str(py_file.relative_to(REPO_ROOT)))
    allowed = {"data-engine/app/knowledge_v3/eval/ocr_lane.py"}
    assert set(hits) <= allowed, f"render_ocr_images=True fuera de lo esperado: {hits}"


# ---------------------------------------------------------------------------
# 6. Ruido OCR del gold: ¿rompe la extraccion determinista?
# ---------------------------------------------------------------------------
def test_noisy_gold_text_extraction_rate_is_measured_honestly():
    """El gold de `ambar-escaneo` incluye ruido OCR simulado a mano
    (`rniembro`, `e1`, `1as`, `Trerne`/`de1`...) y varios casos declaran
    `decision=AUTO_APPROVE` pese al ruido. Aqui NO se asume que la extraccion
    determinista lo tolera: se mide, con el texto CON RUIDO tal cual esta en
    el gold, cuantos episodios producen al menos un claim.
    """
    gold = load_gold(SPLIT)
    source = next(s for s in gold.sources if s.source_id == SOURCE_ID)
    texts = {e["episode_id"]: e["text"] for e in source.episodes}

    report = measure_ocr_lane(visual_provider=_ConfidenceProvider(texts, 0.95))
    assert report["episodes"]["ocr_text_produced"] == len(texts)
    assert report["episodes"]["exact_literal_recovery"] == len(texts)

    claims_by_episode = {}
    for row in report["rows"]:
        claims_by_episode.setdefault(row["episode_id"], 0)
        claims_by_episode[row["episode_id"]] += 1

    episodes_with_claim = len(claims_by_episode)
    total_episodes = len(texts)
    # Documenta el numero real observado (no lo fija a 100%): el ruido
    # tipografico puede legitimamente costar cobertura en algunos episodios.
    coverage = episodes_with_claim / total_episodes if total_episodes else 0.0
    print(
        f"[gate4-b1-adversarial] cobertura de extraccion sobre texto CON ruido "
        f"OCR: {episodes_with_claim}/{total_episodes} = {coverage:.2f}; "
        f"claims totales = {report['claims']['produced']}"
    )
    # La unica invariante dura: el carril nunca inventa evidencia aunque el
    # texto este corrompido.
    assert report["claims"]["golden_rule_violations"] == []
    for row in report["rows"]:
        assert row["evidence_anchored"] is True
