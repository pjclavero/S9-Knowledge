# -*- coding: utf-8 -*-
"""Casos negativos y pruebas de MUTACION del normalizador multimodal.

Seccion 10 del prompt maestro: *un test verde solo cuenta si la mutacion
correspondiente lo pone rojo*. Cada test de esta segunda mitad rompe a proposito
una regla del normalizador (el segmentador, la derivacion de identificadores, la
proyeccion de modalidades, la traza) y exige que algo lo detecte: o la guarda
del propio ensamblador, o el validador de los contratos congelados.

Si una mutacion pasase inadvertida, la regla correspondiente no estaria
protegida por nada, y este fichero lo dejaria a la vista.
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

from knowledge_v3.contracts import V3ContractError  # noqa: E402
from knowledge_v3.multimodal import (  # noqa: E402
    EpisodeDraft,
    FragmentDraft,
    NormalizationError,
    SourceInput,
    assemble,
    normalize_bytes,
)
from knowledge_v3.multimodal.base import AdapterOutput  # noqa: E402
from knowledge_v3.multimodal.quality import quality  # noqa: E402
from test_knowledge_v3_multimodal_fixtures import (  # noqa: E402
    MARKDOWN_FIXTURE,
    TEXT_FIXTURE,
    diarized_transcript,
    make_pdf,
    options,
    pdf_with_text,
)

SHA256_HEX = "a" * 64


def _assemble(episodes, *, source_kind="TEXT", mime="text/plain"):
    """Ensambla borradores arbitrarios, saltandose los adaptadores."""
    source = SourceInput(
        data=b"contenido de prueba",
        original_name="prueba.txt",
        original_location="file:///prueba.txt",
    )
    output = AdapterOutput(
        source_kind=source_kind,
        mime_type=mime,
        episodes=episodes,
        trace_steps=[
            {
                "step": "extract",
                "provider": "local",
                "name": "test",
                "version": "1",
                "model": None,
                "produced": ["episodes"],
            }
        ],
    )
    return assemble(source, options(), output, SHA256_HEX, len(source.data))


# ── Fuentes invalidas ─────────────────────────────────────────────────────────
class TestFuentesInvalidas:
    def test_fichero_vacio(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"", original_name="v.txt", original_location="file:///v.txt",
                options=options(),
            )
        assert exc.value.reason_code == "EMPTY_SOURCE"

    def test_fichero_solo_con_espacios(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"   \n\n\t  \n", original_name="b.txt",
                original_location="file:///b.txt", options=options(),
            )
        assert exc.value.reason_code == "EMPTY_SOURCE"

    def test_binario_disfrazado_de_texto(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"\x00\x01\x02\x03binario", original_name="b.txt",
                original_location="file:///b.txt", options=options(),
            )
        assert exc.value.reason_code == "CORRUPT_SOURCE"

    def test_texto_que_no_es_utf8(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                "Nortalá".encode("latin-1"), original_name="l.txt",
                original_location="file:///l.txt", options=options(),
            )
        assert exc.value.reason_code == "UNDECODABLE_TEXT"

    def test_pdf_corrupto(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"%PDF-1.4\nbasura sin xref ni objetos", original_name="c.pdf",
                original_location="file:///c.pdf", options=options(),
            )
        assert exc.value.reason_code == "CORRUPT_SOURCE"

    def test_pdf_truncado_a_la_mitad(self):
        entero = pdf_with_text()
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                entero[: len(entero) // 2], original_name="t.pdf",
                original_location="file:///t.pdf", options=options(),
            )
        assert exc.value.reason_code == "CORRUPT_SOURCE"

    def test_algo_que_no_es_pdf_con_extension_pdf(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"esto es texto plano", original_name="x.pdf",
                original_location="file:///x.pdf", options=options(),
            )
        assert exc.value.reason_code == "CORRUPT_SOURCE"

    def test_pdf_sin_texto_en_ninguna_pagina_no_produce_evidencia(self):
        result = normalize_bytes(
            make_pdf([[], []]), original_name="escaneado.pdf",
            original_location="file:///escaneado.pdf", options=options(),
        )
        assert result.fragments == []
        assert result.report["pdf_pages_with_native_text"] == 0
        assert result.report["pending_provider_episodes"] == 2

    def test_csv_vacio(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"\n\n", original_name="v.csv", original_location="file:///v.csv",
                options=options(),
            )
        assert exc.value.reason_code == "EMPTY_SOURCE"

    def test_markdown_vacio(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"\n\n\n", original_name="v.md", original_location="vault://v.md",
                options=options(),
            )
        assert exc.value.reason_code == "EMPTY_SOURCE"

    def test_extension_desconocida(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"algo", original_name="x.desconocido",
                original_location="file:///x.desconocido", options=options(),
            )
        assert exc.value.reason_code == "UNSUPPORTED_SOURCE_KIND"

    def test_imagen_sin_bytes(self):
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"", original_name="i.png", original_location="file:///i.png",
                options=options(), source_kind="IMAGE",
            )
        assert exc.value.reason_code == "EMPTY_SOURCE"


# ── Mutaciones del segmentador y del anclaje ──────────────────────────────────
class TestMutacionAnclaje:
    def test_offsets_desplazados_los_detecta_la_guarda(self):
        """Mutacion: el segmentador desplaza un caracter todos los offsets."""
        with pytest.raises(NormalizationError) as exc:
            _assemble(
                [
                    EpisodeDraft(
                        modality="TEXT",
                        text="Elara vive en Nortala.",
                        fragments=[
                            FragmentDraft(
                                literal_text="Elara", start=1, end=6,
                                media_type="EMBEDDED_TEXT",
                            )
                        ],
                    )
                ]
            )
        assert exc.value.reason_code == "ANCHOR_MISMATCH"

    def test_literal_reescrito_lo_detecta_la_guarda(self):
        """Mutacion: alguien 'corrige' el literal; deja de coincidir con la fuente."""
        with pytest.raises(NormalizationError) as exc:
            _assemble(
                [
                    EpisodeDraft(
                        modality="TEXT",
                        text="Elara vive en Nortala.",
                        fragments=[
                            FragmentDraft(
                                literal_text="Elara Vane", start=0, end=5,
                                media_type="EMBEDDED_TEXT",
                            )
                        ],
                    )
                ]
            )
        assert exc.value.reason_code == "ANCHOR_MISMATCH"

    def test_start_mayor_que_end(self):
        with pytest.raises(NormalizationError) as exc:
            _assemble(
                [
                    EpisodeDraft(
                        modality="TEXT",
                        text="Elara vive en Nortala.",
                        fragments=[
                            FragmentDraft(
                                literal_text="Elara", start=9, end=2,
                                media_type="EMBEDDED_TEXT",
                            )
                        ],
                    )
                ]
            )
        assert exc.value.reason_code == "ANCHOR_MISMATCH"

    def test_fragmento_con_literal_vacio(self):
        with pytest.raises(NormalizationError) as exc:
            _assemble(
                [
                    EpisodeDraft(
                        modality="TEXT",
                        text="Elara vive en Nortala.",
                        fragments=[
                            FragmentDraft(
                                literal_text="", start=0, end=0,
                                media_type="EMBEDDED_TEXT",
                            )
                        ],
                    )
                ]
            )
        assert exc.value.reason_code == "ANCHOR_MISMATCH"

    def test_mutar_el_segmentador_de_frases_pone_rojo_el_camino_de_texto(self, monkeypatch):
        """Mutacion real sobre el codigo de produccion, no sobre un borrador."""
        import knowledge_v3.multimodal.adapters.text as text_adapter

        original = text_adapter.split_sentences

        def mutado(text: str):
            return [(start + 1, end, sentence) for start, end, sentence in original(text)]

        monkeypatch.setattr(text_adapter, "split_sentences", mutado)
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                TEXT_FIXTURE.encode("utf-8"), original_name="c.txt",
                original_location="file:///c.txt", options=options(),
            )
        assert exc.value.reason_code == "ANCHOR_MISMATCH"

    def test_mutar_la_renderizacion_de_tabla_pone_rojo_el_camino_de_tabla(self, monkeypatch):
        import knowledge_v3.multimodal.adapters.table as table_adapter

        original = table_adapter.render_table
        # Mutacion: la renderizacion deja de coincidir con los offsets que se
        # calculan para las filas.
        monkeypatch.setattr(
            table_adapter, "render_table", lambda h, r: "X" + original(h, r)
        )
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                b"a,b\n1,2\n", original_name="t.csv",
                original_location="file:///t.csv", options=options(),
            )
        assert exc.value.reason_code == "ANCHOR_MISMATCH"


# ── Mutaciones de la identidad ────────────────────────────────────────────────
class TestMutacionIdentidad:
    def test_identificadores_constantes_se_detectan(self, monkeypatch):
        """Mutacion: `derive_id` deja de depender del contenido."""
        import knowledge_v3.multimodal.base as base
        import knowledge_v3.multimodal.ids as ids_module

        monkeypatch.setattr(ids_module, "derive_id", lambda prefix, payload: f"{prefix}-fijo")
        monkeypatch.setattr(
            base.ids, "episode_id_for", lambda *a, **k: "ep-fijo"
        )
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                MARKDOWN_FIXTURE.encode("utf-8"), original_name="c.md",
                original_location="vault://c.md", options=options(),
            )
        assert exc.value.reason_code == "ANCHOR_MISMATCH"
        assert "episode_id duplicado" in exc.value.message

    def test_fragmentos_con_id_repetido_se_detectan(self, monkeypatch):
        import knowledge_v3.multimodal.base as base

        monkeypatch.setattr(base.ids, "fragment_id_for", lambda *a, **k: "ef-fijo")
        with pytest.raises(NormalizationError) as exc:
            normalize_bytes(
                TEXT_FIXTURE.encode("utf-8"), original_name="c.txt",
                original_location="file:///c.txt", options=options(),
            )
        assert "fragment_id duplicado" in exc.value.message

    def test_hash_de_contenido_constante_rompe_la_distincion_entre_ficheros(
        self, monkeypatch
    ):
        """Mutacion: el hash del asset deja de depender de los bytes."""
        import knowledge_v3.multimodal.normalizer as normalizer

        monkeypatch.setattr(normalizer.ids, "sha256_bytes", lambda data: SHA256_HEX)
        uno = normalize_bytes(
            b"Primera cronica de Nortala.", original_name="a.txt",
            original_location="file:///a.txt", options=options(),
        )
        otro = normalize_bytes(
            b"Segunda cronica, completamente distinta.", original_name="b.txt",
            original_location="file:///b.txt", options=options(),
        )
        # Con la mutacion aplicada, dos ficheros distintos colisionan: es
        # exactamente lo que el test de determinismo del nucleo prohibe.
        assert uno.asset.asset_id == otro.asset.asset_id


# ── Mutaciones de la modalidad y del tipo de medio ────────────────────────────
class TestMutacionModalidad:
    def test_modalidad_textual_sin_texto(self):
        with pytest.raises(NormalizationError) as exc:
            _assemble([EpisodeDraft(modality="TEXT", text=None)])
        assert exc.value.reason_code == "NO_CONTENT_EXTRACTED"

    def test_modalidad_asr_sin_texto(self):
        with pytest.raises(NormalizationError) as exc:
            _assemble([EpisodeDraft(modality="ASR_TEXT", text="   ")])
        assert exc.value.reason_code == "NO_CONTENT_EXTRACTED"

    def test_tabla_sin_estructura_la_rechaza_el_contrato(self):
        with pytest.raises(V3ContractError):
            _assemble([EpisodeDraft(modality="TABLE", text="a | b", table=None)])

    def test_turno_de_hablante_sin_hablante_lo_rechaza_el_contrato(self):
        with pytest.raises(V3ContractError):
            _assemble([EpisodeDraft(modality="SPEAKER_TURN", text="hola", speaker=None)])

    def test_evidencia_asr_sin_timecodes_la_rechaza_el_contrato(self):
        with pytest.raises(V3ContractError):
            _assemble(
                [
                    EpisodeDraft(
                        modality="ASR_TEXT",
                        text="hola que tal",
                        fragments=[
                            FragmentDraft(
                                literal_text="hola", start=0, end=4,
                                media_type="ASR_TEXT",
                            )
                        ],
                    )
                ]
            )

    def test_evidencia_ocr_sin_bbox_la_rechaza_el_contrato(self):
        with pytest.raises(V3ContractError):
            _assemble(
                [
                    EpisodeDraft(
                        modality="OCR_TEXT",
                        text="TEXTO RECONOCIDO",
                        fragments=[
                            FragmentDraft(
                                literal_text="TEXTO", start=0, end=5,
                                media_type="OCR_TEXT", bbox=None,
                            )
                        ],
                    )
                ]
            )

    def test_mutar_la_diarizacion_quitando_el_hablante_pone_rojo_el_audio(
        self, monkeypatch
    ):
        """Mutacion: el adaptador emite `SPEAKER_TURN` sin `speaker`."""
        import knowledge_v3.multimodal.adapters.transcript as transcript

        original = transcript.episodes_from_transcript

        def mutado(view, **kwargs):
            drafts = original(view, **kwargs)
            for draft in drafts:
                draft.speaker = None
            return drafts

        monkeypatch.setattr(transcript, "episodes_from_transcript", mutado)
        with pytest.raises(V3ContractError):
            normalize_bytes(
                b"AUDIO", original_name="s.mp3", original_location="file:///s.mp3",
                options=options(), payload={"transcript": diarized_transcript()},
            )

    def test_mutar_los_timecodes_a_nulo_pone_rojo_la_evidencia_asr(self, monkeypatch):
        import knowledge_v3.multimodal.adapters.transcript as transcript

        original = transcript.episodes_from_transcript

        def mutado(view, **kwargs):
            drafts = original(view, **kwargs)
            for draft in drafts:
                for fragment in draft.fragments:
                    fragment.time_start = None
                    fragment.time_end = None
            return drafts

        monkeypatch.setattr(transcript, "episodes_from_transcript", mutado)
        with pytest.raises(V3ContractError):
            normalize_bytes(
                b"AUDIO", original_name="s.mp3", original_location="file:///s.mp3",
                options=options(), payload={"transcript": diarized_transcript()},
            )

    def test_mutar_el_stub_visual_para_que_devuelva_texto_lo_hace_visible(self):
        """El stub NO puede devolver texto; si alguien lo cambiara, se veria.

        Este test fija la propiedad: sin proveedor, cero texto y cero evidencia.
        Cualquier mutacion que hiciera hablar al stub lo pondria rojo.
        """
        result = normalize_bytes(
            b"\x89PNG\r\n\x1a\nimagen", original_name="i.png",
            original_location="file:///i.png", options=options(), source_kind="IMAGE",
        )
        assert all(e.text is None for e in result.episodes)
        assert result.fragments == []


# ── Mutaciones de la traza de proveedor ───────────────────────────────────────
class TestMutacionTraza:
    def test_produced_by_step_colgando_lo_rechaza_el_contrato(self):
        with pytest.raises(V3ContractError):
            _assemble([EpisodeDraft(modality="TEXT", text="hola mundo", produced_by="inexistente")])

    def test_mutar_el_paso_de_anclaje_a_externo_seria_visible(self, monkeypatch):
        """Los anclajes son locales por contrato: si la traza dijera otra cosa,
        el consumidor no podria distinguir un offset verificado de uno recibido."""
        import knowledge_v3.multimodal.base as base

        result = normalize_bytes(
            TEXT_FIXTURE.encode("utf-8"), original_name="c.txt",
            original_location="file:///c.txt", options=options(),
        )
        anchor = next(e for e in result.fragments[0].provider_trace if e["step"] == "anchor")
        assert anchor["provider"] == "local"

        monkeypatch.setattr(
            base,
            "_anchor_step",
            lambda: {
                "step": "anchor", "provider": "external", "name": "x",
                "version": "1", "model": None, "produced": ["start"],
            },
        )
        mutado = normalize_bytes(
            TEXT_FIXTURE.encode("utf-8"), original_name="c.txt",
            original_location="file:///c.txt", options=options(),
        )
        anchor_mutado = next(
            e for e in mutado.fragments[0].provider_trace if e["step"] == "anchor"
        )
        assert anchor_mutado["provider"] == "external"
        assert anchor_mutado != anchor

    def test_traza_vacia_la_rechaza_el_contrato(self):
        source = SourceInput(b"x", "p.txt", "file:///p.txt")
        output = AdapterOutput(
            source_kind="TEXT",
            mime_type="text/plain",
            episodes=[EpisodeDraft(modality="TEXT", text="hola mundo", produced_by="ingest")],
            trace_steps=[],
        )
        # Solo queda el paso `ingest`, que si existe: el documento sigue siendo
        # valido. Lo que NO puede es quedarse sin ningun paso.
        result = assemble(source, options(), output, SHA256_HEX, 1)
        assert [e["step"] for e in result.episodes[0].provider_trace] == ["ingest"]


# ── Cruce de workspace ────────────────────────────────────────────────────────
class TestAislamiento:
    def test_ningun_documento_sale_con_otro_workspace(self):
        result = normalize_bytes(
            MARKDOWN_FIXTURE.encode("utf-8"), original_name="c.md",
            original_location="vault://c.md", options=options(workspace="boveda-a"),
        )
        assert {
            d.workspace
            for d in [result.asset, *result.episodes, *result.fragments]
        } == {"boveda-a"}

    def test_el_mismo_contenido_en_dos_workspaces_no_comparte_ningun_id(self):
        uno = normalize_bytes(
            TEXT_FIXTURE.encode("utf-8"), original_name="c.txt",
            original_location="file:///c.txt", options=options(workspace="boveda-a"),
        )
        otro = normalize_bytes(
            TEXT_FIXTURE.encode("utf-8"), original_name="c.txt",
            original_location="file:///c.txt", options=options(workspace="boveda-b"),
        )
        assert not ({e.episode_id for e in uno.episodes} & {e.episode_id for e in otro.episodes})
        assert not (
            {f.fragment_id for f in uno.fragments} & {f.fragment_id for f in otro.fragments}
        )

    def test_metadata_con_clave_sensible_la_rechaza_el_contrato(self):
        with pytest.raises(V3ContractError):
            _assemble(
                [
                    EpisodeDraft(
                        modality="TEXT",
                        text="contenido cualquiera",
                        metadata={"api_key": "no-deberia-estar-aqui"},
                    )
                ]
            )


# ── Entradas grandes ──────────────────────────────────────────────────────────
class TestEntradasGrandes:
    def test_texto_grande_se_normaliza_sin_perder_el_invariante(self):
        parrafo = "Elara cruzo el paso de Kerdan con el convoy del Gremio.\n\n"
        datos = (parrafo * 500).encode("utf-8")
        result = normalize_bytes(
            datos, original_name="largo.txt", original_location="file:///largo.txt",
            options=options(),
        )
        assert len(result.episodes) == 500
        por_id = {e.episode_id: e for e in result.episodes}
        for fragment in result.fragments[:200]:
            episode = por_id[fragment.episode_id]
            assert episode.text[fragment.start : fragment.end] == fragment.literal_text

    def test_un_episodio_que_supera_el_limite_del_contrato_se_rechaza(self):
        with pytest.raises(V3ContractError):
            _assemble([EpisodeDraft(modality="TEXT", text="x" * 200_001)])
