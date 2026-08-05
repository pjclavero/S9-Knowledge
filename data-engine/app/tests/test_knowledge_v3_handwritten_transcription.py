# -*- coding: utf-8 -*-
"""Criterios de aceptacion del carril TRANSCRIBED_TEXT (encargo V3/29)."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from knowledge_v3.multimodal import IngestOptions, normalize_bytes  # noqa: E402
from knowledge_v3.multimodal.registry import default_registry  # noqa: E402
from knowledge_v3.multimodal.transcription import (  # noqa: E402
    COHERENCE_PROMPT,
    TRANSCRIPTION_FAMILY,
    TRANSCRIPTION_PROMPT,
    CoherenceRequest,
    NvidiaCoherenceReviewer,
    NvidiaVisionTranscriber,
    TranscriptionCascade,
    TranscriptionReading,
    literal_diff,
    risk_spans,
)

IMAGE = b"\x89PNG\r\n\x1a\nmanuscrito-real-simulado-en-el-puerto"
BASE_GLOSSARY = {
    "la", "puerta", "sigue", "cerrada", "el", "grupo", "llega", "al",
    "amanecer", "linea", "sin", "duda", "ve", "a", "en", "norte",
    "es", "aliada", "hoy", "nota", "dice", "que", "sale",
}


class ScriptedVLM:
    def __init__(self, model: str, *texts: str) -> None:
        self.model = model
        self.texts = list(texts)
        self.requests = []

    def transcribe(self, request):
        self.requests.append(request)
        text = self.texts[min(len(self.requests) - 1, len(self.texts) - 1)]
        return TranscriptionReading(
            text=text,
            model=self.model,
            provider="external",
            name="scripted-vlm",
            version="test",
        )


class ScriptedCoherence:
    model = "text-coherence-model"

    def __init__(self, coherent: bool) -> None:
        self.coherent = coherent
        self.requests: list[CoherenceRequest] = []

    def review(self, request: CoherenceRequest) -> bool:
        self.requests.append(request)
        return self.coherent


def cascade(
    first: str,
    second: str | None = None,
    *,
    coherent: bool = True,
    glossary=BASE_GLOSSARY,
):
    primary = ScriptedVLM("vision-primary", first)
    secondary = ScriptedVLM("vision-secondary", second if second is not None else first)
    reviewer = ScriptedCoherence(coherent)
    built = TranscriptionCascade(
        primary, secondary, reviewer, glossary=frozenset(glossary)
    )
    return built, primary, secondary, reviewer


def options(**overrides):
    values = {
        "workspace": "transcription-tests",
        "collection_id": "notes",
        "ingested_at": "2026-07-29T12:00:00Z",
        "privacy_class": "INTERNAL",
        "allow_external_providers": True,
        "language_hint": "es",
    }
    values.update(overrides)
    return IngestOptions(**values)


def normalize(provider, *, payload=None, ingest_options=None):
    return normalize_bytes(
        IMAGE,
        original_name="sesion-12-pj.png",
        original_location="file:///notas/sesion-12-pj.png",
        source_kind="HANDWRITING",
        mime_type="image/png",
        payload={"ingested_by": "pj", **(payload or {})},
        options=ingest_options or options(),
        registry=default_registry(visual_provider=provider),
    )


def review_fragments(result):
    return [f for f in result.fragments if (f.metadata or {}).get("review_required")]


def test_01_imprenta_limpia_no_escala_y_revision_cero():
    provider, _, secondary, _ = cascade("la puerta sigue cerrada")
    result = normalize(provider)
    assert not secondary.requests
    assert not review_fragments(result)
    assert result.report["transcription_metrics"]["s9_transcription_review_fraction"] == 0


def test_02_incoherencia_escala_una_palabra_emborronada():
    provider, _, secondary, _ = cascade(
        "la puerta [ilegible] cerrada", coherent=False
    )
    normalize(provider)
    assert len(secondary.requests) == 1


def test_03_nombre_propio_coherente_escala_por_riesgo():
    provider, _, secondary, _ = cascade(
        "el grupo ve a Narek", glossary=BASE_GLOSSARY | {"narek"}
    )
    normalize(provider)
    assert len(secondary.requests) == 1


@pytest.mark.parametrize("text", ["el grupo llega en 1247", "el grupo llega 12/03/1247"])
def test_04_numero_o_fecha_siempre_escala(text):
    provider, _, secondary, _ = cascade(text)
    normalize(provider)
    assert len(secondary.requests) == 1


def test_05_termino_fuera_del_glosario_escala():
    provider, _, secondary, _ = cascade("la puerta zharakai")
    normalize(provider)
    assert len(secondary.requests) == 1


def test_06_dos_lecturas_identicas_aceptan_sin_revision():
    provider, _, _, _ = cascade("el grupo ve a Narek")
    result = normalize(provider)
    assert not review_fragments(result)
    assert result.report["transcription_metrics"]["s9_transcription_disagreed_total"] == 0


def test_07_dos_lecturas_distintas_marcan_solo_la_palabra():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    result = normalize(provider)
    marked = review_fragments(result)
    assert [item.literal_text for item in marked] == ["Narek"]
    assert any(not (f.metadata or {}).get("review_required") for f in result.fragments)
    assert not result.episodes[0].metadata.get("review_required")


def test_08_cuarenta_lineas_dos_dudas_dejan_38_lineas_limpias():
    lines = [f"linea sin duda {i}" for i in range(1, 41)]
    first = "\n".join(lines)
    second_lines = list(lines)
    second_lines[9] = "linea sin duda diez"
    second_lines[29] = "linea sin duda treinta"
    provider, _, _, _ = cascade(first, "\n".join(second_lines))
    result = normalize(provider)
    marked_lines = {(f.metadata or {}).get("line") for f in review_fragments(result)}
    clean_lines = {
        (f.metadata or {}).get("line")
        for f in result.fragments
        if not (f.metadata or {}).get("review_required")
    }
    assert marked_lines == {10, 30}
    assert len(clean_lines - marked_lines) == 38


def test_09_tramo_dudoso_no_bloquea_ingesta():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    result = normalize(provider)
    assert result.episodes[0].text == "el grupo ve a Narek"
    assert review_fragments(result)[0].confidence == 0.5
    result.validate()


def test_10_ilegible_se_conserva_y_no_se_adivina():
    provider, _, _, _ = cascade("la puerta [ilegible] cerrada")
    result = normalize(provider)
    assert "[ilegible]" in result.episodes[0].text
    assert "plausible" not in result.episodes[0].text


def test_11_prompt_prohibe_normalizar_y_exige_preservacion_literal():
    lower = TRANSCRIPTION_PROMPT.lower()
    assert all(word in lower for word in ("no interpretes", "no resumas", "no normalices"))
    assert "no completes" in lower and "[ilegible]" in lower
    assert all(word in lower for word in ("ortografia", "mayusculas", "puntuacion"))


def test_12_diff_literal_no_invoca_ningun_modelo():
    assert literal_diff("Narek llega", "Narok llega")[0].start == 0


def test_13_codigo_no_contiene_validacion_contra_grafo():
    source = (_APP_DIR / "knowledge_v3/multimodal/transcription.py").read_text("utf-8")
    assert "neo4j" not in source.casefold()
    assert "graph" not in source.casefold()
    assert "resolution" not in source.casefold()


def test_14_nombre_conocido_no_aumenta_confianza():
    known, _, _, _ = cascade(
        "el grupo ve a Narek", "el grupo ve a Narok", glossary=BASE_GLOSSARY | {"narek"}
    )
    unknown, _, _, _ = cascade(
        "el grupo ve a Narek", "el grupo ve a Narok", glossary=BASE_GLOSSARY
    )
    assert review_fragments(normalize(known))[0].confidence == 0.5
    assert review_fragments(normalize(unknown))[0].confidence == 0.5


def test_15_peticion_vlm_no_tiene_bboxes_ni_coordenadas():
    provider, primary, _, _ = cascade("la puerta sigue cerrada")
    normalize(provider)
    request = primary.requests[0]
    assert not hasattr(request, "bbox")
    assert "coordenadas" in request.prompt.lower()
    assert "devuelvas coordenadas" in request.prompt.lower()


def test_16_offsets_son_de_transcripcion_y_hash_es_propio_del_episodio():
    text = "el grupo ve a Narek"
    provider, _, _, _ = cascade(text, "el grupo ve a Narok")
    result = normalize(provider)
    episode = result.episodes[0]
    for fragment in result.fragments:
        assert episode.text[fragment.start:fragment.end] == fragment.literal_text
        assert fragment.bbox is None
        assert fragment.metadata["anchor"] == "transcription_offsets"
    assert episode.content_hash["value"] != result.asset.content_hash["value"]


def test_17_metadata_funciona_sin_campos_opcionales():
    provider, _, _, _ = cascade("la puerta sigue cerrada")
    metadata = normalize(provider).episodes[0].metadata
    assert metadata["source_file"] == "sesion-12-pj.png"
    assert metadata["ingested_by"] == "pj"
    assert not any(
        key in metadata
        for key in ("author_hint", "perspective_hint", "session_id", "in_game_date")
    )


def test_18_autor_y_perspectiva_se_conservan_separados():
    provider, _, _, _ = cascade("la puerta sigue cerrada")
    metadata = normalize(
        provider,
        payload={"author_hint": "master", "perspective_hint": "Elara"},
    ).episodes[0].metadata
    assert metadata["author_hint"] == "master"
    assert metadata["perspective_hint"] == "Elara"


def test_19_contratos_congelados_mantienen_su_hash():
    # M0 (docs/v3/49-multipartida-diseno.md §8): `partida_id`/`scope` se
    # anadieron de forma aditiva a los contratos v1 (SourceAsset,
    # ClaimProposal, GraphMutationPlan). El tag `v3-contracts-frozen-1.0.0`
    # sigue existiendo e intacto para quien ancle contra el estado previo;
    # M0 avanzo al checkpoint `v3-contracts-frozen-1.0.0-m0`.
    #
    # M2 (docs/v3/49-multipartida-diseno.md, "Politica de version de
    # contratos v1 del programa"): `partida_id` opcional, mismo criterio
    # aditivo, ahora tambien en EntityMention/EntityResolution (el resolutor
    # necesitaba el campo para acotar el ambito visible). Nuevo checkpoint:
    # `v3-contracts-frozen-1.0.0-m2`.
    #
    # M3 (docs/v3/49-multipartida-diseno.md SS11 "M3 implementado"): sin
    # cambios de ESQUEMA (M3 no toco JSON Schema ni dataclasses de
    # contratos) -- el freeze avanza solo porque `validator.py`
    # (DECISION_HASH_FIELDS/IDEMPOTENCY_KEY_FIELDS) y `mutation_plan.py`
    # ganaron comentarios que documentan, con verificacion, por que esos dos
    # huecos heredados de M0 se dejan abiertos en M3 (writer/admission.py ya
    # consume partida_id/scope, pero ningun dataset congelado lo declara
    # hoy). Nuevo checkpoint: `v3-contracts-frozen-1.0.0-m3`.
    #
    # M4 (docs/v3/49-multipartida-diseno.md SS12 "M4 implementado"):
    # `FactAssertion` gana `local_override_of` (aditivo, opcional, mismo
    # patron que M0/M2) en `contracts/assertion.py` y en
    # `fact-assertion-v3.schema.json`, mas un chequeo semantico de
    # autoreferencia en `validator.py`. Nuevo checkpoint:
    # `v3-contracts-frozen-1.0.0-m4`.
    frozen_ref = "v3-contracts-frozen-1.0.0-m4"
    roots = [
        _REPO_ROOT / "contracts/knowledge-v3/v1",
        _REPO_ROOT / "data-engine/app/knowledge_v3/contracts",
    ]
    files = sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and "tests" not in path.parts
        and "examples" not in path.parts
    )

    relative_paths = [path.relative_to(_REPO_ROOT).as_posix() for path in files]
    frozen_paths = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            frozen_ref,
            "--",
            "contracts/knowledge-v3/v1",
            "data-engine/app/knowledge_v3/contracts",
        ],
        cwd=_REPO_ROOT,
        text=True,
    ).splitlines()
    frozen_paths = [
        path
        for path in frozen_paths
        if "__pycache__" not in path.split("/")
        and "tests" not in path.split("/")
        and "examples" not in path.split("/")
    ]

    def digest(contents):
        result = hashlib.sha256()
        for relative_path, content in zip(relative_paths, contents, strict=True):
            result.update(relative_path.encode())
            result.update(b"\0")
            result.update(content.replace(b"\r\n", b"\n"))
        return result.hexdigest()

    assert len(files) == 23
    assert relative_paths == frozen_paths
    current_digest = digest(path.read_bytes() for path in files)
    frozen_digest = digest(
        subprocess.check_output(
            ["git", "show", f"{frozen_ref}:{relative_path}"],
            cwd=_REPO_ROOT,
        )
        for relative_path in frozen_paths
    )
    assert current_digest == frozen_digest


def test_20_determinismo_en_diez_pasadas():
    outputs = []
    for _ in range(10):
        provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
        result = normalize(provider)
        outputs.append(
            (
                [episode.to_json() for episode in result.episodes],
                [fragment.to_json() for fragment in result.fragments],
            )
        )
    assert all(output == outputs[0] for output in outputs)


def test_familia_y_modelos_distintos_quedan_declarados():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    metadata = normalize(provider).episodes[0].metadata
    assert metadata["family"] == TRANSCRIPTION_FAMILY
    assert metadata["transcription_models"] == ["vision-primary", "vision-secondary"]


def test_no_se_permiten_dos_lecturas_del_mismo_modelo():
    with pytest.raises(ValueError, match="modelos distintos"):
        TranscriptionCascade(
            ScriptedVLM("same", "texto"),
            ScriptedVLM("same", "texto"),
            ScriptedCoherence(True),
        )


def test_revision_de_coherencia_solo_recibe_texto():
    provider, _, _, reviewer = cascade("la puerta sigue cerrada")
    normalize(provider)
    request = reviewer.requests[0]
    assert request.text == "la puerta sigue cerrada"
    assert not hasattr(request, "data")
    assert "conocimiento externo" in COHERENCE_PROMPT.lower()


def test_contenido_privado_se_bloquea_antes_del_primer_vlm():
    provider, primary, _, _ = cascade("la puerta sigue cerrada")
    with pytest.raises(Exception, match="privacy_class=PERSONAL_DATA"):
        normalize(
            provider,
            ingest_options=options(
                privacy_class="PERSONAL_DATA", allow_external_providers=True
            ),
        )
    assert not primary.requests


def test_metricas_obligatorias_estan_expuestas():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    metrics = normalize(provider).report["transcription_metrics"]
    assert set(metrics) == {
        "s9_transcription_pages_total",
        "s9_transcription_spans_total",
        "s9_transcription_escalated_total",
        "s9_transcription_disagreed_total",
        "s9_transcription_to_review_total",
        "s9_transcription_review_fraction",
        's9_stage_duration_seconds{stage="transcription"}',
    }
    assert metrics["s9_transcription_review_fraction"] == pytest.approx(1 / 5)


class FakeNvidiaClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.guarded = []
        self.messages = []

    def _assert_safe_to_send(self, payload):
        self.guarded.append(payload)

    def chat_json(self, messages, *, model, max_tokens):
        self.messages.append((messages, model, max_tokens))
        return self.responses.pop(0)


def test_adaptadores_nvidia_usan_guarda_y_no_mandan_imagen_al_revisor():
    client = FakeNvidiaClient(
        [
            {"parsed": {"transcription": "Texto literal"}, "model": "vision"},
            {"parsed": {"coherent": True}, "model": "text"},
        ]
    )
    reading = NvidiaVisionTranscriber(client, model="vision").transcribe(
        type("R", (), {
            "data": IMAGE,
            "mime_type": "image/png",
            "language_hint": "es",
            "prompt": TRANSCRIPTION_PROMPT,
        })()
    )
    coherent = NvidiaCoherenceReviewer(client, model="text").review(
        CoherenceRequest(reading.text)
    )
    assert coherent is True
    assert "data:image/png;base64," in str(client.messages[0][0])
    assert "data:image" not in str(client.messages[1][0])
    assert len(client.guarded) == 2
