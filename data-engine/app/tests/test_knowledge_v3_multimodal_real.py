"""Real local OCR and multimodal gold acceptance tests."""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# pipeline.__init__ imports its optional RSS reporter. Windows has no resource
# module; this minimal import shim is never called by these tests.
try:  # pragma: no cover - platform branch
    import resource as _resource  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - exercised on Windows
    sys.modules["resource"] = SimpleNamespace(RUSAGE_SELF=0)

from knowledge_v3.benchmarks.metrics import error_rate, ratio  # noqa: E402
from knowledge_v3.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    Provider,
    provider_step,
    sha256_hash,
)
from knowledge_v3.contracts.game_profile import GameProfile  # noqa: E402
from knowledge_v3.contracts.mutation_plan import GraphMutationPlan  # noqa: E402
from knowledge_v3.engine.snapshot import SnapshotEntity  # noqa: E402
from knowledge_v3.extraction.lexicon import Lexicon, LexiconEntry  # noqa: E402
from knowledge_v3.multimodal import (  # noqa: E402
    IngestOptions,
    NormalizationError,
    SourceInput,
    normalize_bytes,
)
from knowledge_v3.multimodal.adapters.visual import (  # noqa: E402
    MODE_OCR,
    VisualResult,
    VisualTextSpan,
)
from knowledge_v3.multimodal.providers.tesseract import (  # noqa: E402
    TesseractNotAvailable,
    TesseractVisualProvider,
)
from knowledge_v3.multimodal.registry import default_registry  # noqa: E402
from knowledge_v3.pipeline import KnowledgePipeline, PipelineConfig, SourceCase  # noqa: E402
from knowledge_v3.resolution.catalog import (  # noqa: E402
    CatalogEntity,
    InMemoryEntityCatalog,
)

WORKSPACE = "multimodal-bruma"
NOW = "2026-07-29T12:00:00Z"
GOLD_DIR = REPO_ROOT / "benchmarks" / "datasets" / "multimodal"


def options(**overrides) -> IngestOptions:
    values = {
        "workspace": WORKSPACE,
        "collection_id": "collection:multimodal-real",
        "ingested_at": NOW,
        "created_at": NOW,
        "language_hint": "en",
    }
    values.update(overrides)
    return IngestOptions(**values)


def image_bytes(
    text: str,
    *,
    width: int = 1500,
    height: int = 360,
    background: int = 255,
) -> bytes:
    image = Image.new("L", (width, height), background)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 52)
    except OSError:
        font = ImageFont.load_default(size=52)
    y = 55
    for line in text.splitlines():
        draw.text((55, y), line, font=font, fill=0)
        y += 76
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture(scope="module")
def tesseract() -> TesseractVisualProvider:
    try:
        return TesseractVisualProvider()
    except TesseractNotAvailable as exc:
        pytest.skip(str(exc))


def ocr_result(data: bytes, provider: TesseractVisualProvider):
    return normalize_bytes(
        data,
        original_name="bruma.png",
        original_location="fixture://bruma.png",
        source_kind="IMAGE",
        mime_type="image/png",
        options=options(),
        registry=default_registry(visual_provider=provider),
    )


def test_real_ocr_returns_anchored_text_and_word_bboxes(tesseract):
    result = ocr_result(
        image_bytes("Liora Vale es aliada de Narek Sol.\nLa alianza sigue vigente."),
        tesseract,
    )
    episode = next(item for item in result.episodes if item.modality == "OCR_TEXT")
    assert "Liora Vale" in episode.text
    assert "Narek Sol" in episode.text
    fragments = result.fragments_of(episode.episode_id)
    assert len(fragments) == 2
    for fragment in fragments:
        assert episode.text[fragment.start:fragment.end] == fragment.literal_text
        assert fragment.media_type == "OCR_TEXT"
        assert fragment.metadata["anchor"] == "text+bbox"
        assert 0.0 <= fragment.bbox["x"] < 1.0
        assert 0.0 <= fragment.bbox["y"] < 1.0
        assert fragment.bbox["x"] + fragment.bbox["width"] <= 1.0 + 1e-9
        assert fragment.bbox["y"] + fragment.bbox["height"] <= 1.0 + 1e-9
    provider_steps = [
        step
        for step in episode.provider_trace
        if step["step"] == "vision"
    ]
    assert provider_steps
    assert provider_steps[0]["provider"] == "local"
    assert provider_steps[0]["name"] == "tesseract"


def test_real_ocr_blank_image_emits_diagnostic_without_text(tesseract):
    result = ocr_result(image_bytes("", background=255), tesseract)
    assert not [item for item in result.episodes if item.modality == "OCR_TEXT"]
    pending = [
        item for item in result.episodes
        if "UNPROCESSED_PENDING_PROVIDER" in item.quality["flags"]
    ]
    assert pending
    assert any(
        item.metadata["pending_reason"] == "OCR_NO_TEXT_DETECTED"
        for item in pending
    )
    assert result.fragments == []


def test_real_ocr_unreadable_image_does_not_break_batch_or_invent_text(tesseract):
    result = ocr_result(b"not-an-image", tesseract)
    assert result.fragments == []
    assert any(
        item.metadata["pending_reason"] == "OCR_UNREADABLE_IMAGE"
        for item in result.episodes
    )
    assert all(item.text is None for item in result.episodes)


def test_provider_mixing_literal_ocr_and_description_is_rejected():
    class MixedProvider:
        provider_kind = "local"

        def recognize(self, request):
            if request.mode != MODE_OCR:
                return None
            return VisualResult(
                mode=MODE_OCR,
                region_id=request.region.region_id,
                confidence=0.9,
                text="texto literal",
                description="interpretación visual",
                provider="local",
            )

    with pytest.raises(NormalizationError):
        ocr_result(image_bytes("texto literal"), MixedProvider())


def test_out_of_range_word_confidence_is_rejected_not_clipped():
    class InvalidConfidenceProvider:
        provider_kind = "local"

        def recognize(self, request):
            if request.mode != MODE_OCR:
                return None
            return VisualResult(
                mode=MODE_OCR,
                region_id=request.region.region_id,
                confidence=0.9,
                text="texto",
                provider="local",
                spans=(
                    VisualTextSpan(
                        text="texto",
                        start=0,
                        end=5,
                        bbox={"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2},
                        confidence=1.01,
                    ),
                ),
            )

    with pytest.raises(NormalizationError) as caught:
        ocr_result(image_bytes("texto"), InvalidConfidenceProvider())
    assert caught.value.reason_code == "PROVIDER_CONFIDENCE_OUT_OF_RANGE"


def test_bbox_outside_image_is_rejected():
    class InvalidBboxProvider:
        provider_kind = "local"

        def recognize(self, request):
            if request.mode != MODE_OCR:
                return None
            return VisualResult(
                mode=MODE_OCR,
                region_id=request.region.region_id,
                confidence=0.9,
                text="texto",
                provider="local",
                spans=(
                    VisualTextSpan(
                        text="texto",
                        start=0,
                        end=5,
                        bbox={"x": 0.9, "y": 0.1, "width": 0.2, "height": 0.2},
                        confidence=0.9,
                    ),
                ),
            )

    with pytest.raises(NormalizationError) as caught:
        ocr_result(image_bytes("texto"), InvalidBboxProvider())
    assert caught.value.reason_code == "ANCHOR_MISMATCH"


def test_no_provider_keeps_existing_stub_behavior():
    result = normalize_bytes(
        image_bytes("Liora Vale"),
        original_name="stub.png",
        original_location="fixture://stub.png",
        source_kind="IMAGE",
        options=options(),
    )
    assert result.report["adapter_implementation"] == "stub"
    assert result.fragments == []
    assert all(
        item.metadata["pending_reason"] == "NO_VISUAL_PROVIDER"
        for item in result.episodes
    )


def _profile() -> GameProfile:
    profile = GameProfile(
        contract_version=CONTRACT_VERSION,
        workspace=WORKSPACE,
        source_asset_id="profile:multimodal-bruma",
        source_hash=sha256_hash("profile:multimodal-bruma"),
        provider_trace=[
            provider_step(
                "profile",
                Provider.LOCAL,
                "multimodal-test-profile",
                "1.0.0",
                ["predicates"],
            )
        ],
        produced_by_step="profile",
        profile_id="multimodal-bruma",
        profile_version="1.0.0",
        core_ontology_version="1.0.0",
        entity_types=["Character", "Location", "Faction", "Object", "Event", "Concept"],
        predicates=[
            {
                "predicate": "ALLY_OF",
                "domain": ["Character"],
                "range": ["Character"],
                "symmetric": True,
            }
        ],
        aliases=[],
        titles=[],
        factions=[],
        calendars=[],
        identity_rules=[],
        ambiguous_terms=[],
        source_priorities=[],
        evaluation_examples=[],
    )
    profile.validate()
    return profile


class ExplodingDriver:
    def __getattr__(self, name):
        raise AssertionError(f"dry-run touched Neo4j through {name}")


def test_real_image_runs_full_pipeline_to_mutation_plan_dry_run(tesseract):
    lexicon = Lexicon([
        LexiconEntry("Liora Vale", "Character", confidence=0.99, origin="multimodal-gold"),
        LexiconEntry("Narek Sol", "Character", confidence=0.99, origin="multimodal-gold"),
    ])
    catalog = InMemoryEntityCatalog([
        CatalogEntity("entity:liora-vale", WORKSPACE, "Character", "Liora Vale"),
        CatalogEntity("entity:narek-sol", WORKSPACE, "Character", "Narek Sol"),
    ])
    snapshot_entities = [
        SnapshotEntity.of("entity:liora-vale", "Character"),
        SnapshotEntity.of("entity:narek-sol", "Character"),
    ]
    pipeline = KnowledgePipeline(PipelineConfig(
        workspace=WORKSPACE,
        collection_id="collection:multimodal-real",
        profile=_profile(),
        now=NOW,
        ingested_at=NOW,
        providers="local_only",
        visual_provider=tesseract,
        lexicon=lexicon,
        catalog=catalog,
        writer_driver=ExplodingDriver(),
        writer_clock=lambda: datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
        ablation="multimodal-real",
    ))
    source = (GOLD_DIR / "sources" / "bruma-scan.png").read_bytes()
    run = pipeline.run_source(
        SourceCase(
            source_id="bruma-real-ocr",
            source=SourceInput(
                data=source,
                original_name="bruma-real-ocr.png",
                original_location="fixture://bruma-real-ocr.png",
                mime_type="image/png",
                source_kind="IMAGE",
                payload=None,
            ),
            ingest_options=options(),
        ),
        catalog_entities=snapshot_entities,
    )
    assert len(run.episodes) >= 1
    assert len(run.fragments) >= 1
    assert len(run.mentions) >= 2
    assert len(run.claims) >= 1
    assert len(run.resolutions) >= 2
    assert len(run.decisions) == len(run.claims)
    plan = run.plan or run.review_plan
    assert isinstance(plan, GraphMutationPlan)
    measurements = {
        "ocr_characters": sum(
            len(episode.text or "")
            for episode in run.episodes
            if episode.modality == "OCR_TEXT"
        ),
        "episodes": len(run.episodes),
        "fragments": len(run.fragments),
        "mentions": len(run.mentions),
        "claims": len(run.claims),
        "resolutions": len(run.resolutions),
        "decisions": len(run.decisions),
        "plan": "write" if run.plan is not None else "review",
        "writer_mode": run.write_result.mode if run.write_result is not None else None,
    }
    print("PIPELINE_MEASUREMENTS=" + json.dumps(measurements, sort_keys=True))
    assert run.write_result is not None
    assert run.write_result.mode == "DRY_RUN"


def _normalize_gold_modality(entry: dict, tesseract: TesseractVisualProvider):
    path = GOLD_DIR / entry["path"]
    if entry["kind"] == "TEXT":
        return normalize_bytes(
            path.read_bytes(),
            original_name=path.name,
            original_location=str(path),
            source_kind="TEXT",
            options=options(),
        )
    if entry["kind"] == "PDF":
        return normalize_bytes(
            path.read_bytes(),
            original_name=path.name,
            original_location=str(path),
            source_kind="PDF",
            mime_type="application/pdf",
            options=options(),
        )
    if entry["kind"] == "IMAGE":
        return normalize_bytes(
            path.read_bytes(),
            original_name=path.name,
            original_location=str(path),
            source_kind="IMAGE",
            mime_type="image/png",
            options=options(),
            registry=default_registry(visual_provider=tesseract),
        )
    transcript = json.loads(path.read_text(encoding="utf-8"))
    return normalize_bytes(
        b"simulated-asr-fixture",
        original_name="bruma-audio.wav",
        original_location=str(path),
        source_kind="AUDIO",
        mime_type="audio/wav",
        payload={"transcript": transcript},
        options=options(),
    )


def test_four_gold_modalities_validate_and_share_semantic_gold(tesseract):
    manifest = json.loads((GOLD_DIR / "manifest.json").read_text(encoding="utf-8"))
    semantic_gold = json.loads(
        (GOLD_DIR / manifest["semantic_gold"]).read_text(encoding="utf-8")
    )
    assert len(manifest["modalities"]) == 4
    assert semantic_gold["claims"] == [{
        "subject": "entity:liora-vale",
        "predicate": "ALLY_OF",
        "object": "entity:narek-sol",
        "direction": "SUBJECT_TO_OBJECT",
        "negated": False,
    }]
    results = {
        entry["source_id"]: _normalize_gold_modality(entry, tesseract)
        for entry in manifest["modalities"]
    }
    assert set(results) == {
        "bruma-text",
        "bruma-pdf-native",
        "bruma-scan",
        "bruma-audio",
    }
    assert all(result.validate() is result for result in results.values())
    assert any(
        episode.modality == "OCR_TEXT"
        for episode in results["bruma-scan"].episodes
    )
    for source_id, result in results.items():
        recovered = " ".join(
            episode.text or ""
            for episode in result.episodes
            if episode.text
        ).lower()
        assert "liora vale" in recovered, source_id
        assert "narek sol" in recovered, source_id
        assert "es aliada de" in recovered, source_id


def test_real_scan_reports_measured_ocr_loss_with_existing_metrics(tesseract):
    reference = (GOLD_DIR / "sources" / "bruma.txt").read_text(encoding="utf-8").strip()
    result = _normalize_gold_modality(
        {
            "source_id": "bruma-scan",
            "kind": "IMAGE",
            "path": "sources/bruma-scan.png",
        },
        tesseract,
    )
    hypothesis = "\n".join(
        episode.text or ""
        for episode in result.episodes
        if episode.modality == "OCR_TEXT"
    ).strip()
    char_edits, reference_chars = error_rate(reference, hypothesis, unit="char")
    word_edits, reference_words = error_rate(reference, hypothesis, unit="word")
    measurements = {
        "reference_characters": reference_chars,
        "ocr_characters": len(hypothesis),
        "cer_edits": char_edits,
        "cer": ratio(char_edits, reference_chars),
        "wer_edits": word_edits,
        "wer": ratio(word_edits, reference_words),
        "episodes": len(result.episodes),
        "fragments": len(result.fragments),
    }
    print("OCR_MEASUREMENTS=" + json.dumps(measurements, sort_keys=True))
    assert measurements["reference_characters"] > 0
    assert measurements["ocr_characters"] > 0
    assert measurements["cer"] is not None
    assert measurements["wer"] is not None
