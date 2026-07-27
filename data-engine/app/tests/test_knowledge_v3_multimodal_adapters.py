# -*- coding: utf-8 -*-
"""Un bloque de tests por adaptador, con fixtures reales pequenas.

Reglas de estas pruebas:

* las fixtures son fuentes REALES (un PDF que `pypdf` abre de verdad, un CSV que
  `csv` parsea, Markdown con tabla), generadas en codigo para que se vea que
  contienen;
* para audio NO se usa audio: se usa una transcripcion fixture, porque este
  subsistema **envuelve** transcripciones, no las produce;
* de los adaptadores visuales se prueban las DOS rutas: sin proveedor (stub
  honesto) y con un doble del puerto (proyeccion real a contratos).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(_APP_DIR), str(_TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from knowledge_v3.multimodal import NormalizationError, normalize_bytes  # noqa: E402
from knowledge_v3.multimodal.adapters.table import render_table  # noqa: E402
from knowledge_v3.multimodal.adapters.transcript import (  # noqa: E402
    SegmentView,
    coerce_transcript,
    group_segments,
)
from knowledge_v3.multimodal.adapters.visual import (  # noqa: E402
    MODE_DESCRIPTION,
    MODE_DIAGRAM,
    MODE_HTR,
    MODE_MAP,
    MODE_OCR,
    NoVisualProvider,
)
from knowledge_v3.multimodal.registry import default_registry  # noqa: E402
from test_knowledge_v3_multimodal_fixtures import (  # noqa: E402
    CSV_FIXTURE,
    MARKDOWN_FIXTURE,
    TEXT_FIXTURE,
    FakeVisualProvider,
    MultimediaArtifactLike,
    TranscriptResultLike,
    diarized_transcript,
    options,
    pdf_with_text,
    pdf_without_text,
    plain_transcript,
    untimed_transcript,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"bytes-de-imagen-de-prueba"


def _check_anclajes(result):
    """Invariante universal: los offsets recortan exactamente el literal."""
    por_id = {e.episode_id: e for e in result.episodes}
    for fragment in result.fragments:
        episode = por_id[fragment.episode_id]
        if episode.text is not None:
            assert episode.text[fragment.start : fragment.end] == fragment.literal_text


# ── Texto plano ───────────────────────────────────────────────────────────────
class TestAdaptadorTexto:
    @pytest.fixture
    def result(self):
        return normalize_bytes(
            TEXT_FIXTURE.encode("utf-8"),
            original_name="cronica.txt",
            original_location="file:///vault/cronica.txt",
            options=options(),
        )

    def test_un_episodio_por_parrafo(self, result):
        assert result.report["paragraphs"] == 2
        assert [e.modality for e in result.episodes] == ["TEXT", "TEXT"]

    def test_evidencia_por_frase_con_tipo_embebido(self, result):
        assert {f.media_type for f in result.fragments} == {"EMBEDDED_TEXT"}
        assert any(f.literal_text.startswith("Elara Vane llego") for f in result.fragments)
        _check_anclajes(result)

    def test_las_notas_usan_el_mismo_adaptador(self):
        result = normalize_bytes(
            b"Recordar: Borin debe un favor a Elara.",
            original_name="apunte.note",
            original_location="file:///apunte.note",
            options=options(),
            source_kind="NOTE",
        )
        assert result.asset.source_kind == "NOTE"
        assert result.episodes[0].modality == "TEXT"

    def test_texto_corto_se_marca_sin_invalidarse(self):
        result = normalize_bytes(
            "Elara.".encode("utf-8"),
            original_name="breve.txt",
            original_location="file:///breve.txt",
            options=options(),
        )
        assert "SHORT_TEXT" in result.episodes[0].quality["flags"]
        assert result.episodes[0].quality["score"] < 1.0

    def test_bucle_de_repeticion_se_detecta(self):
        texto = "El barco zarpa. " * 6
        result = normalize_bytes(
            texto.encode("utf-8"),
            original_name="bucle.txt",
            original_location="file:///bucle.txt",
            options=options(),
        )
        assert "REPEATED_CONTENT" in result.episodes[0].quality["flags"]


# ── Markdown ──────────────────────────────────────────────────────────────────
class TestAdaptadorMarkdown:
    @pytest.fixture
    def result(self):
        return normalize_bytes(
            MARKDOWN_FIXTURE.encode("utf-8"),
            original_name="cronica.md",
            original_location="vault://cronica.md",
            options=options(),
        )

    def test_la_tabla_sale_del_flujo_de_texto_como_episodio_table(self, result):
        tablas = [e for e in result.episodes if e.modality == "TABLE"]
        assert len(tablas) == 1
        assert tablas[0].table["header"] == ["Objeto", "Cantidad", "Duenno"]
        assert tablas[0].table["rows"][0] == ["Espada corta", "1", "Elara"]

    def test_los_encabezados_se_conservan_y_se_exponen_como_ruta(self, result):
        rutas = [e.metadata.get("heading_path") for e in result.episodes if e.metadata]
        assert ["Cronica de Nortala"] in rutas
        assert ["Cronica de Nortala", "Inventario del convoy"] in rutas
        assert any("# Cronica de Nortala" == (e.text or "") for e in result.episodes)

    def test_evidencia_de_tabla_por_fila_y_anclada(self, result):
        tabla = next(e for e in result.episodes if e.modality == "TABLE")
        fragmentos = result.fragments_of(tabla.episode_id)
        assert len(fragmentos) == 2
        assert {f.media_type for f in fragmentos} == {"TABLE"}
        _check_anclajes(result)

    def test_markdown_sin_tabla_no_produce_episodios_table(self):
        result = normalize_bytes(
            b"# Solo texto\n\nUna linea cualquiera de prosa.\n",
            original_name="simple.md",
            original_location="vault://simple.md",
            options=options(),
        )
        assert result.report["markdown_table_episodes"] == 0

    def test_una_barra_suelta_no_se_confunde_con_una_tabla(self):
        result = normalize_bytes(
            b"# T\n\n| esto no es una tabla porque no hay separador\n",
            original_name="falsa.md",
            original_location="vault://falsa.md",
            options=options(),
        )
        assert all(e.modality != "TABLE" for e in result.episodes)


# ── Tabla / CSV ───────────────────────────────────────────────────────────────
class TestAdaptadorTabla:
    @pytest.fixture
    def result(self):
        return normalize_bytes(
            CSV_FIXTURE.encode("utf-8"),
            original_name="personajes.csv",
            original_location="file:///personajes.csv",
            options=options(),
        )

    def test_un_episodio_table_con_estructura_y_renderizacion(self, result):
        episode = result.episodes[0]
        assert episode.modality == "TABLE"
        assert episode.table["header"] == ["nombre", "faccion", "ciudad"]
        assert len(episode.table["rows"]) == 2
        assert episode.text == render_table(
            episode.table["header"], episode.table["rows"]
        )

    def test_evidencia_por_fila_anclada_en_la_renderizacion(self, result):
        assert len(result.fragments) == 2
        _check_anclajes(result)

    def test_sin_cabecera_si_el_llamante_lo_declara(self):
        result = normalize_bytes(
            b"Elara,Nortala\nBorin,Kerdan\n",
            original_name="sin.csv",
            original_location="file:///sin.csv",
            options=options(),
            payload={"has_header": False},
        )
        assert result.episodes[0].table["header"] == []
        assert len(result.episodes[0].table["rows"]) == 2

    def test_delimitador_explicito(self):
        result = normalize_bytes(
            b"a;b\n1;2\n",
            original_name="pyc.csv",
            original_location="file:///pyc.csv",
            options=options(),
            payload={"delimiter": ";"},
        )
        assert result.episodes[0].table["rows"] == [["1", "2"]]

    def test_filas_desiguales_se_marcan_sin_romper(self):
        result = normalize_bytes(
            b"a,b,c\n1,2\n",
            original_name="irregular.csv",
            original_location="file:///irregular.csv",
            options=options(),
        )
        assert "RAGGED_TABLE" in result.episodes[0].quality["flags"]

    def test_solo_cabecera_no_es_contenido(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"a,b,c\n",
                original_name="vacia.csv",
                original_location="file:///vacia.csv",
                options=options(),
            )
        assert exc.value.reason_code == "NO_CONTENT_EXTRACTED"


# ── PDF ───────────────────────────────────────────────────────────────────────
class TestAdaptadorPdf:
    def test_paginas_con_texto_nativo_no_pasan_por_ocr(self):
        result = normalize_bytes(
            pdf_with_text(),
            original_name="cronica.pdf",
            original_location="file:///cronica.pdf",
            options=options(),
        )
        assert result.report["pdf_pages"] == 2
        assert result.report["pdf_pages_with_native_text"] == 2
        assert result.report["pdf_pages_pending_recognition"] == []
        assert result.report["pending_provider_episodes"] == 0

    def test_cada_episodio_lleva_su_pagina(self):
        result = normalize_bytes(
            pdf_with_text(),
            original_name="cronica.pdf",
            original_location="file:///cronica.pdf",
            options=options(),
        )
        assert {e.page for e in result.episodes} == {1, 2}
        assert all(f.page in (1, 2) for f in result.fragments)
        _check_anclajes(result)

    def test_pagina_sin_texto_queda_pendiente_de_reconocimiento(self):
        result = normalize_bytes(
            pdf_without_text(),
            original_name="escaneado.pdf",
            original_location="file:///escaneado.pdf",
            options=options(),
        )
        assert result.report["pdf_pages_pending_recognition"] == [2]
        pendiente = next(e for e in result.episodes if e.page == 2)
        assert pendiente.modality == "IMAGE"
        assert pendiente.text is None
        assert pendiente.quality["score"] == 0.0
        assert set(pendiente.quality["flags"]) == {
            "NO_NATIVE_TEXT",
            "UNPROCESSED_PENDING_PROVIDER",
        }
        assert result.fragments_of(pendiente.episode_id) == []

    def test_la_pagina_pendiente_deja_el_punto_de_enganche_explicito(self):
        result = normalize_bytes(
            pdf_without_text(),
            original_name="escaneado.pdf",
            original_location="file:///escaneado.pdf",
            options=options(),
        )
        pendiente = next(e for e in result.episodes if e.page == 2)
        assert pendiente.metadata["next_adapters"] == [
            "OCR_TEXT",
            "HTR_TEXT",
            "IMAGE_DESCRIPTION",
        ]
        assert pendiente.bbox == {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "page": 2}

    def test_el_umbral_de_texto_nativo_es_configurable_y_se_respeta(self):
        from knowledge_v3.multimodal.adapters.pdf import PdfAdapter
        from knowledge_v3.multimodal.registry import AdapterRegistry

        estricto = PdfAdapter()
        estricto.min_native_chars = 10_000
        result = normalize_bytes(
            pdf_with_text(),
            original_name="cronica.pdf",
            original_location="file:///cronica.pdf",
            options=options(),
            registry=AdapterRegistry([estricto]),
        )
        assert result.report["pdf_pages_pending_recognition"] == [1, 2]


# ── Transcripciones (audio / video / YouTube) ─────────────────────────────────
class TestAdaptadorTranscripcion:
    def _audio(self, transcript, **kwargs):
        return normalize_bytes(
            b"BYTES-DE-AUDIO-FIXTURE",
            original_name="sesion.mp3",
            original_location="file:///media/sesion.mp3",
            options=options(),
            payload={"transcript": transcript},
            **kwargs,
        )

    def test_diarizacion_produce_turnos_de_hablante(self):
        result = self._audio(diarized_transcript())
        assert [e.modality for e in result.episodes] == ["SPEAKER_TURN"] * 3
        assert [e.turn for e in result.episodes] == [0, 1, 2]
        assert result.episodes[0].speaker["label"] == "SPEAKER_00"
        assert result.episodes[1].speaker["label"] == "SPEAKER_01"

    def test_el_speaker_id_es_estable_para_el_mismo_hablante(self):
        result = self._audio(diarized_transcript())
        primero = result.episodes[0].speaker["speaker_id"]
        tercero = result.episodes[2].speaker["speaker_id"]
        assert primero == tercero  # SPEAKER_00 vuelve a hablar
        assert primero != result.episodes[1].speaker["speaker_id"]

    def test_sin_diarizacion_los_episodios_son_asr_text(self):
        result = self._audio(plain_transcript())
        assert {e.modality for e in result.episodes} == {"ASR_TEXT"}
        assert all(e.speaker is None for e in result.episodes)
        assert "NO_DIARIZATION" in result.episodes[0].quality["flags"]

    def test_la_evidencia_asr_lleva_anclaje_temporal_real(self):
        result = self._audio(diarized_transcript())
        assert {f.media_type for f in result.fragments} == {"ASR_TEXT"}
        for fragment in result.fragments:
            assert fragment.time_start is not None
            assert fragment.time_end is not None
            assert fragment.time_start <= fragment.time_end
        _check_anclajes(result)

    def test_los_tiempos_del_episodio_cubren_los_de_sus_segmentos(self):
        result = self._audio(diarized_transcript())
        for episode in result.episodes:
            fragmentos = result.fragments_of(episode.episode_id)
            assert episode.time_start == min(f.time_start for f in fragmentos)
            assert episode.time_end == max(f.time_end for f in fragmentos)

    def test_la_traza_atribuye_el_texto_al_motor_asr_no_al_normalizador(self):
        result = self._audio(diarized_transcript())
        episode = result.episodes[0]
        assert episode.produced_by_step == "asr"
        paso = next(e for e in episode.provider_trace if e["step"] == "asr")
        assert paso["name"] == "transcriber:faster-whisper"
        assert paso["model"] == "small"
        assert "speaker" in paso["produced"]

    def test_envuelve_la_forma_de_media_models_transcriptresult(self):
        result = self._audio(TranscriptResultLike(plain_transcript()))
        assert result.report["transcript_engine"] == "stub"
        assert result.report["transcript_segments"] == 4

    def test_envuelve_la_forma_de_multimedia_artifact_asr(self):
        result = self._audio(MultimediaArtifactLike(plain_transcript()))
        assert result.report["transcript_segments"] == 4
        assert {f.media_type for f in result.fragments} == {"ASR_TEXT"}

    def test_rechaza_un_artefacto_multimedia_que_no_sea_asr(self):
        artefacto = MultimediaArtifactLike(plain_transcript())
        artefacto.media_type = "OCR_TEXT"
        with pytest.raises(NormalizationError) as exc:
            self._audio(artefacto)
        assert exc.value.reason_code == "MISSING_PAYLOAD"

    def test_video_usa_la_misma_via_que_audio(self):
        result = normalize_bytes(
            b"BYTES-DE-VIDEO-FIXTURE",
            original_name="sesion.mp4",
            original_location="file:///media/sesion.mp4",
            options=options(),
            payload={"transcript": diarized_transcript()},
        )
        assert result.asset.source_kind == "VIDEO"
        assert result.report["speaker_turns"] == 3

    def test_youtube_sin_timecodes_no_los_inventa(self):
        result = normalize_bytes(
            b"",
            original_name="video-de-youtube",
            original_location="https://www.youtube.com/watch?v=xxxxxxxxxxx",
            options=options(),
            source_kind="YOUTUBE",
            payload={"transcript": untimed_transcript()},
        )
        assert result.report["episodes_without_timecodes"] == 1
        assert "NO_TIMECODES" in result.episodes[0].quality["flags"]
        assert all(f.time_start is None for f in result.fragments)
        assert {f.media_type for f in result.fragments} == {"CAPTION"}

    def test_youtube_sin_fichero_hashea_la_transcripcion_canonica(self):
        result = normalize_bytes(
            b"",
            original_name="video-de-youtube",
            original_location="https://www.youtube.com/watch?v=xxxxxxxxxxx",
            options=options(),
            source_kind="YOUTUBE",
            payload={"transcript": untimed_transcript()},
        )
        assert result.report["content_hash_basis"] == "canonical_transcript_json"
        assert result.asset.byte_size > 0

    def test_transcripcion_sin_timecodes_ni_subtitulos_no_produce_evidencia(self):
        """Sin tiempos no hay cita verificable: se pierde evidencia y se dice."""
        result = normalize_bytes(
            b"",
            original_name="video-de-youtube",
            original_location="https://www.youtube.com/watch?v=xxxxxxxxxxx",
            options=options(),
            source_kind="YOUTUBE",
            payload={"transcript": untimed_transcript(source_method="whisper")},
        )
        assert result.fragments == []
        assert result.episodes[0].text

    def test_transcripcion_truncada_y_con_hueco_se_marca(self):
        transcript = diarized_transcript()
        transcript["duration_seconds"] = 120.0
        transcript["segments"][2]["start"] = 40.0
        transcript["segments"][2]["end"] = 46.0
        transcript["segments"][3]["start"] = 46.0
        transcript["segments"][3]["end"] = 52.0
        result = self._audio(transcript)
        flags = set(result.episodes[0].quality["flags"])
        assert "LOW_ASR_COVERAGE" in flags
        assert "TRUNCATED_TAIL" in flags
        assert "TIMELINE_GAP" in flags

    def test_confianza_baja_del_proveedor_se_marca(self):
        transcript = plain_transcript()
        for segment in transcript["segments"]:
            segment["confidence"] = 0.3
        result = self._audio(transcript)
        assert "LOW_PROVIDER_CONFIDENCE" in result.episodes[0].quality["flags"]
        assert all(f.confidence == 0.3 for f in result.fragments)

    def test_sin_payload_no_hay_nada_que_envolver(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"BYTES",
                original_name="sesion.mp3",
                original_location="file:///sesion.mp3",
                options=options(),
            )
        assert exc.value.reason_code in ("MISSING_PAYLOAD", "EMPTY_SOURCE")

    def test_coerce_rechaza_transcripcion_vacia(self):
        with pytest.raises(NormalizationError) as exc:
            coerce_transcript({"segments": [], "text": ""})
        assert exc.value.reason_code == "EMPTY_SOURCE"

    def test_group_segments_corta_por_cambio_de_hablante(self):
        segmentos = [
            SegmentView(0.0, 1.0, "a", speaker="A"),
            SegmentView(1.0, 2.0, "b", speaker="A"),
            SegmentView(2.0, 3.0, "c", speaker="B"),
        ]
        assert [len(g) for g in group_segments(segmentos)] == [2, 1]

    def test_group_segments_corta_por_ventana_sin_diarizacion(self):
        segmentos = [SegmentView(float(i), float(i + 1), "x" * 400) for i in range(4)]
        grupos = group_segments(segmentos, max_chars=900)
        assert all(sum(len(s.text) for s in g) <= 900 for g in grupos[:-1])
        assert sum(len(g) for g in grupos) == 4


# ── Visual: OCR, HTR, imagen, dibujo ──────────────────────────────────────────
class TestAdaptadoresVisuales:
    @pytest.mark.parametrize(
        "kind,modos",
        [
            ("IMAGE", [MODE_OCR, MODE_DESCRIPTION]),
            ("CHARACTER_SHEET", [MODE_OCR, MODE_DESCRIPTION]),
            ("HANDWRITING", [MODE_HTR]),
            ("DIAGRAM", [MODE_DIAGRAM]),
            ("MAP", [MODE_MAP]),
        ],
    )
    def test_sin_proveedor_todo_queda_pendiente_y_declarado(self, kind, modos):
        result = normalize_bytes(
            PNG,
            original_name=f"{kind.lower()}.png",
            original_location=f"file:///{kind.lower()}.png",
            options=options(),
            source_kind=kind,
        )
        assert result.asset.source_kind == kind
        assert result.report["adapter_implementation"] == "stub"
        assert result.report["visual_modes"] == modos
        assert result.fragments == []
        for episode in result.episodes:
            assert episode.modality == "IMAGE"
            assert episode.text is None
            assert episode.quality["score"] == 0.0
            assert "UNPROCESSED_PENDING_PROVIDER" in episode.quality["flags"]
            assert episode.metadata["pending_reason"] == "NO_VISUAL_PROVIDER"

    def test_el_episodio_pendiente_declara_que_produciria(self):
        result = normalize_bytes(
            PNG,
            original_name="manuscrito.png",
            original_location="file:///manuscrito.png",
            options=options(),
            source_kind="HANDWRITING",
        )
        metadata = result.episodes[0].metadata
        assert metadata["requested_mode"] == MODE_HTR
        assert metadata["would_produce_modality"] == "HTR_TEXT"
        assert metadata["would_produce_media_type"] == "HTR_TEXT"

    def test_con_proveedor_ocr_se_proyecta_a_episodio_ocr_con_bbox(self):
        provider = FakeVisualProvider({MODE_OCR: ("HOJA DE PERSONAJE: Elara Vane", 0.82)})
        registry = default_registry(visual_provider=provider)
        result = normalize_bytes(
            PNG,
            original_name="ficha.png",
            original_location="file:///ficha.png",
            options=options(),
            source_kind="IMAGE",
            registry=registry,
        )
        ocr = [e for e in result.episodes if e.modality == "OCR_TEXT"]
        assert len(ocr) == 1
        assert ocr[0].text == "HOJA DE PERSONAJE: Elara Vane"
        assert ocr[0].bbox == {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
        fragmento = result.fragments_of(ocr[0].episode_id)[0]
        assert fragmento.media_type == "OCR_TEXT"
        assert fragmento.bbox is not None
        assert fragmento.confidence == 0.82

    def test_ocr_literal_e_interpretacion_visual_son_episodios_distintos(self):
        provider = FakeVisualProvider(
            {
                MODE_OCR: ("KERDAN", 0.9),
                MODE_DESCRIPTION: ("Mapa de un paso de montana con dos torres", 0.6),
            }
        )
        result = normalize_bytes(
            PNG,
            original_name="mapa.png",
            original_location="file:///mapa.png",
            options=options(),
            source_kind="IMAGE",
            registry=default_registry(visual_provider=provider),
        )
        modalidades = [e.modality for e in result.episodes]
        assert modalidades == ["OCR_TEXT", "IMAGE"]
        interpretacion = result.episodes[1]
        # La descripcion NUNCA se presenta como texto literal del episodio.
        assert interpretacion.text is None
        assert interpretacion.metadata["description"].startswith("Mapa de un paso")
        assert {f.media_type for f in result.fragments} == {"OCR_TEXT", "IMAGE_DESCRIPTION"}

    def test_htr_no_se_etiqueta_como_ocr(self):
        provider = FakeVisualProvider({MODE_HTR: ("nota manuscrita de Borin", 0.55)})
        result = normalize_bytes(
            PNG,
            original_name="manuscrito.png",
            original_location="file:///manuscrito.png",
            options=options(),
            source_kind="HANDWRITING",
            registry=default_registry(visual_provider=provider),
        )
        assert result.episodes[0].modality == "HTR_TEXT"
        assert result.fragments[0].media_type == "HTR_TEXT"

    def test_mapa_y_diagrama_piden_modos_distintos(self):
        provider = FakeVisualProvider(
            {MODE_MAP: ("mapa del paso", 0.7), MODE_DIAGRAM: ("esquema del gremio", 0.7)}
        )
        registry = default_registry(visual_provider=provider)
        mapa = normalize_bytes(
            PNG, original_name="m.png", original_location="file:///m.png",
            options=options(), source_kind="MAP", registry=registry,
        )
        diagrama = normalize_bytes(
            PNG, original_name="d.png", original_location="file:///d.png",
            options=options(), source_kind="DIAGRAM",
            registry=default_registry(visual_provider=provider),
        )
        assert mapa.episodes[0].modality == "MAP"
        assert mapa.fragments[0].media_type == "MAP"
        assert diagrama.episodes[0].modality == "DIAGRAM"
        assert diagrama.fragments[0].media_type == "DIAGRAM"

    def test_regiones_declaradas_generan_un_episodio_por_region(self):
        provider = FakeVisualProvider({MODE_OCR: ("texto", 0.9)})
        result = normalize_bytes(
            PNG,
            original_name="pagina.png",
            original_location="file:///pagina.png",
            options=options(),
            source_kind="HANDWRITING",
            payload={
                "regions": [
                    {"region_id": "cabecera", "bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.2}},
                    {"region_id": "cuerpo", "bbox": {"x": 0.0, "y": 0.2, "width": 1.0, "height": 0.8}},
                ]
            },
            registry=default_registry(visual_provider=provider),
        )
        assert result.report["visual_regions"] == 2
        assert [e.metadata["region_id"] for e in result.episodes] == ["cabecera", "cuerpo"]

    def test_region_sin_bbox_es_error(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                PNG,
                original_name="pagina.png",
                original_location="file:///pagina.png",
                options=options(),
                source_kind="IMAGE",
                payload={"regions": [{"region_id": "x"}]},
            )
        assert exc.value.reason_code == "MISSING_PAYLOAD"

    def test_la_traza_del_proveedor_externo_se_declara_como_externa(self):
        provider = FakeVisualProvider({MODE_HTR: ("texto leido", 0.9)}, provider="external")
        result = normalize_bytes(
            PNG,
            original_name="f.png",
            original_location="file:///f.png",
            options=options(),
            source_kind="HANDWRITING",
            registry=default_registry(visual_provider=provider),
        )
        provider_step = next(
            e for e in result.episodes[0].provider_trace if e["step"] == "vision"
        )
        assert provider_step["provider"] == "external"
        assert provider_step["name"] == "fake-visual"
        assert provider_step["model"] == "fake-model"

    def test_proveedor_que_mezcla_lectura_e_interpretacion_es_rechazado(self):
        from knowledge_v3.multimodal.adapters.visual import VisualResult

        class Mezclador:
            def recognize(self, request):
                return VisualResult(
                    mode=request.mode,
                    region_id=request.region.region_id,
                    confidence=0.9,
                    text="texto literal",
                    description="y ademas una interpretacion",
                )

        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                PNG,
                original_name="f.png",
                original_location="file:///f.png",
                options=options(),
                source_kind="HANDWRITING",
                registry=default_registry(visual_provider=Mezclador()),
            )
        assert exc.value.reason_code == "MISSING_PAYLOAD"

    def test_proveedor_que_responde_en_otro_modo_es_rechazado(self):
        from knowledge_v3.multimodal.adapters.visual import VisualResult

        class Confundido:
            def recognize(self, request):
                return VisualResult(
                    mode=MODE_DESCRIPTION,
                    region_id=request.region.region_id,
                    confidence=0.9,
                    description="algo",
                )

        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                PNG,
                original_name="f.png",
                original_location="file:///f.png",
                options=options(),
                source_kind="HANDWRITING",
                registry=default_registry(visual_provider=Confundido()),
            )
        assert exc.value.reason_code == "MISSING_PAYLOAD"

    def test_proveedor_que_devuelve_vacio_deja_el_episodio_pendiente(self):
        provider = FakeVisualProvider({MODE_HTR: ("   ", 0.9)})
        result = normalize_bytes(
            PNG,
            original_name="f.png",
            original_location="file:///f.png",
            options=options(),
            source_kind="HANDWRITING",
            registry=default_registry(visual_provider=provider),
        )
        assert result.episodes[0].modality == "IMAGE"
        assert "UNPROCESSED_PENDING_PROVIDER" in result.episodes[0].quality["flags"]

    def test_el_proveedor_ausente_es_un_caso_normal_no_una_excepcion(self):
        assert NoVisualProvider().recognize(object()) is None
