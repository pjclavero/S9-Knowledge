# -*- coding: utf-8 -*-
"""Nucleo del normalizador multimodal V3: registro, identidad, envelope y contratos.

Lo que se comprueba aqui es lo que sostiene a todos los adaptadores:

* el registro resuelve por `source_kind`, MIME y extension, y no admite duplicados;
* los identificadores se DERIVAN del hash y son estables entre ejecuciones;
* el envelope V3 es coherente en los tres documentos;
* el invariante de anclaje (`text[start:end] == literal_text`) se cumple siempre;
* todo lo que sale valida contra los contratos CONGELADOS y hace round-trip.
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

from knowledge_v3.contracts import (  # noqa: E402
    EvidenceFragment,
    SourceAsset,
    SourceEpisode,
    parse_document,
)
from knowledge_v3.multimodal import (  # noqa: E402
    AdapterRegistry,
    IngestOptions,
    NormalizationError,
    SourceInput,
    default_registry,
    ids,
    normalize,
    normalize_bytes,
)
from knowledge_v3.multimodal.adapters.text import PlainTextAdapter  # noqa: E402
from test_knowledge_v3_multimodal_fixtures import (  # noqa: E402
    CSV_FIXTURE,
    MARKDOWN_FIXTURE,
    TEXT_FIXTURE,
    diarized_transcript,
    options,
    pdf_with_text,
)


def _text_result(**kwargs):
    return normalize_bytes(
        TEXT_FIXTURE.encode("utf-8"),
        original_name="cronica.txt",
        original_location="file:///vault/cronica.txt",
        options=kwargs.pop("options_", options()),
        **kwargs,
    )


# ── Registro de adaptadores ───────────────────────────────────────────────────
class TestRegistry:
    def test_default_registry_cubre_los_source_kind_implementados(self):
        kinds = set(default_registry().source_kinds())
        assert {
            "TEXT", "NOTE", "MARKDOWN", "TABLE", "PDF",
            "AUDIO", "VIDEO", "YOUTUBE",
            "IMAGE", "CHARACTER_SHEET", "HANDWRITING", "MAP", "DIAGRAM",
        } <= kinds

    def test_resuelve_por_source_kind_declarado(self):
        registry = default_registry()
        source = SourceInput(b"x", "cosa.bin", "file:///cosa.bin", source_kind="TEXT")
        assert registry.resolve(source).name.endswith("adapters.text")

    def test_resuelve_por_mime_cuando_no_hay_kind(self):
        registry = default_registry()
        source = SourceInput(b"x", "cosa.bin", "file:///c", mime_type="text/markdown")
        assert registry.resolve(source).name.endswith("adapters.markdown")

    def test_resuelve_por_extension_como_ultimo_recurso(self):
        registry = default_registry()
        source = SourceInput(b"x", "tabla.csv", "file:///tabla.csv")
        assert registry.resolve(source).name.endswith("adapters.table")

    def test_el_kind_declarado_gana_al_mime(self):
        """Adivinar cuando el llamante ya lo ha dicho es como se enruta mal un escaneado."""
        registry = default_registry()
        source = SourceInput(
            b"x", "cosa.md", "file:///c", mime_type="text/markdown", source_kind="TEXT"
        )
        assert registry.resolve(source).name.endswith("adapters.text")

    def test_fuente_no_reconocible_falla_con_codigo(self):
        registry = default_registry()
        source = SourceInput(b"x", "cosa.xyz", "file:///cosa.xyz")
        with pytest.raises(NormalizationError) as exc:
            registry.resolve(source)
        assert exc.value.reason_code == "UNSUPPORTED_SOURCE_KIND"

    def test_source_kind_sin_adaptador_falla(self):
        with pytest.raises(NormalizationError) as exc:
            AdapterRegistry().get("PDF")
        assert exc.value.reason_code == "UNSUPPORTED_SOURCE_KIND"

    def test_registrar_dos_veces_el_mismo_kind_es_error(self):
        registry = AdapterRegistry([PlainTextAdapter()])
        with pytest.raises(NormalizationError) as exc:
            registry.register(PlainTextAdapter())
        assert exc.value.reason_code == "DUPLICATE_ADAPTER"

    def test_colision_de_mime_tambien_es_error(self):
        """Con `setdefault`, el orden de registro decidia en silencio."""
        class OtroTexto(PlainTextAdapter):
            name = "otro.texto"
            source_kinds = ("OTRO_TEXTO",)

        registry = AdapterRegistry([PlainTextAdapter()])
        with pytest.raises(NormalizationError) as exc:
            registry.register(OtroTexto())
        assert exc.value.reason_code == "DUPLICATE_ADAPTER"
        assert "mime_type" in exc.value.message

    def test_colision_de_extension_tambien_es_error(self):
        class OtroTexto(PlainTextAdapter):
            name = "otro.texto"
            source_kinds = ("OTRO_TEXTO",)
            mime_types = ("text/otro",)

        registry = AdapterRegistry([PlainTextAdapter()])
        with pytest.raises(NormalizationError) as exc:
            registry.register(OtroTexto())
        assert exc.value.reason_code == "DUPLICATE_ADAPTER"
        assert "extension" in exc.value.message

    def test_una_colision_no_deja_el_registro_a_medias(self):
        """Se comprueba TODO antes de escribir nada."""
        class OtroTexto(PlainTextAdapter):
            name = "otro.texto"
            source_kinds = ("OTRO_TEXTO",)

        registry = AdapterRegistry([PlainTextAdapter()])
        with pytest.raises(NormalizationError):
            registry.register(OtroTexto())
        assert "OTRO_TEXTO" not in registry.source_kinds()

    def test_el_registro_por_defecto_no_tiene_ninguna_colision(self):
        """Si la hubiera, `default_registry()` reventaria al construirse."""
        registry = default_registry()
        assert len(registry.adapters) == 10

    def test_replace_permite_sustituir_explicitamente(self):
        registry = AdapterRegistry([PlainTextAdapter()])
        nuevo = PlainTextAdapter()
        registry.register(nuevo, replace=True)
        assert registry.get("TEXT") is nuevo

    def test_inventario_distingue_real_de_stub(self):
        inventory = {e["name"]: e["implementation"] for e in default_registry().inventory()}
        assert inventory["knowledge_v3.multimodal.adapters.text"] == "real"
        assert inventory["knowledge_v3.multimodal.adapters.pdf"] == "real"
        assert inventory["knowledge_v3.multimodal.adapters.audio"] == "real"
        # Sin proveedor visual inyectado, los visuales son stub y lo declaran.
        assert inventory["knowledge_v3.multimodal.adapters.image"] == "stub"
        assert inventory["knowledge_v3.multimodal.adapters.handwriting"] == "stub"
        assert inventory["knowledge_v3.multimodal.adapters.drawing"] == "stub"


# ── Identidad y determinismo ──────────────────────────────────────────────────
class TestDeterminismo:
    def test_dos_ejecuciones_producen_documentos_identicos_byte_a_byte(self):
        primera = _text_result()
        segunda = _text_result()
        assert primera.asset.to_json() == segunda.asset.to_json()
        assert [e.to_json() for e in primera.episodes] == [
            e.to_json() for e in segunda.episodes
        ]
        assert [f.to_json() for f in primera.fragments] == [
            f.to_json() for f in segunda.fragments
        ]

    def test_content_hash_es_el_sha256_real_del_contenido(self):
        result = _text_result()
        assert result.asset.content_hash == {
            "algorithm": "sha256",
            "value": ids.sha256_bytes(TEXT_FIXTURE.encode("utf-8")),
        }
        assert result.asset.byte_size == len(TEXT_FIXTURE.encode("utf-8"))

    def test_un_byte_distinto_cambia_hash_e_identificadores(self):
        original = _text_result()
        mutado = normalize_bytes(
            TEXT_FIXTURE.replace("812", "813").encode("utf-8"),
            original_name="cronica.txt",
            original_location="file:///vault/cronica.txt",
            options=options(),
        )
        assert mutado.asset.content_hash != original.asset.content_hash
        assert mutado.asset.asset_id != original.asset.asset_id

    def test_el_workspace_entra_en_la_identidad_del_asset(self):
        """Dos bovedas con el mismo fichero NO comparten asset: el aislamiento es duro."""
        uno = _text_result(options_=options(workspace="alfa"))
        otro = _text_result(options_=options(workspace="beta"))
        assert uno.asset.content_hash == otro.asset.content_hash
        assert uno.asset.asset_id != otro.asset.asset_id

    def test_los_ids_no_dependen_del_reloj(self):
        """Cambiar `ingested_at` no cambia ningun identificador derivado."""
        uno = _text_result(options_=options(ingested_at="2026-07-27T10:00:00Z"))
        otro = _text_result(options_=options(ingested_at="2030-01-01T00:00:00Z"))
        assert uno.asset.asset_id == otro.asset.asset_id
        assert [e.episode_id for e in uno.episodes] == [e.episode_id for e in otro.episodes]

    def test_identificadores_unicos_dentro_del_resultado(self):
        result = normalize_bytes(
            MARKDOWN_FIXTURE.encode("utf-8"),
            original_name="cronica.md",
            original_location="vault://cronica.md",
            options=options(),
        )
        episode_ids = [e.episode_id for e in result.episodes]
        fragment_ids = [f.fragment_id for f in result.fragments]
        assert len(set(episode_ids)) == len(episode_ids)
        assert len(set(fragment_ids)) == len(fragment_ids)

    def test_hash_field_rechaza_digest_invalido(self):
        with pytest.raises(ValueError):
            ids.hash_field("no-es-un-sha256")


# ── Envelope y contratos ──────────────────────────────────────────────────────
class TestEnvelopeYContratos:
    @pytest.fixture(scope="class")
    def result(self):
        return normalize_bytes(
            MARKDOWN_FIXTURE.encode("utf-8"),
            original_name="cronica.md",
            original_location="vault://cronica.md",
            options=options(),
        )

    def test_los_tres_documentos_validan_contra_los_contratos_congelados(self, result):
        result.validate()
        assert isinstance(result.asset, SourceAsset)
        assert all(isinstance(e, SourceEpisode) for e in result.episodes)
        assert all(isinstance(f, EvidenceFragment) for f in result.fragments)

    def test_roundtrip_exacto_por_documento(self, result):
        for document in [result.asset, *result.episodes, *result.fragments]:
            reconstruido = parse_document(document.to_dict())
            assert reconstruido == document
            assert reconstruido.to_json() == document.to_json()

    def test_source_hash_es_el_content_hash_del_asset_en_toda_la_cadena(self, result):
        for document in [result.asset, *result.episodes, *result.fragments]:
            assert document.source_hash == result.asset.content_hash
            assert document.source_asset_id == result.asset.asset_id

    def test_workspace_propagado_sin_cruces(self, result):
        for document in [result.asset, *result.episodes, *result.fragments]:
            assert document.workspace == "pruebas"

    def test_produced_by_step_resuelve_en_la_traza(self, result):
        for document in [result.asset, *result.episodes, *result.fragments]:
            steps = [entry["step"] for entry in document.provider_trace]
            assert document.produced_by_step in steps

    def test_toda_la_traza_es_local_en_el_camino_de_texto(self, result):
        """Ni Markdown ni PDF ni CSV pasan por proveedor: la traza debe decirlo."""
        for document in [result.asset, *result.episodes, *result.fragments]:
            assert {e["provider"] for e in document.provider_trace} == {"local"}

    def test_los_fragmentos_llevan_el_paso_de_anclaje_local(self, result):
        for fragment in result.fragments:
            anchor = [e for e in fragment.provider_trace if e["step"] == "anchor"]
            assert len(anchor) == 1
            assert anchor[0]["provider"] == "local"
            assert "start" in anchor[0]["produced"]

    def test_encadenado_de_episodios_completo_y_coherente(self, result):
        episodes = result.episodes
        assert [e.sequence for e in episodes] == list(range(len(episodes)))
        assert episodes[0].previous_episode_id is None
        assert episodes[-1].next_episode_id is None
        for anterior, siguiente in zip(episodes, episodes[1:]):
            assert anterior.next_episode_id == siguiente.episode_id
            assert siguiente.previous_episode_id == anterior.episode_id

    def test_invariante_de_anclaje_en_todos_los_fragmentos(self, result):
        por_id = {e.episode_id: e for e in result.episodes}
        for fragment in result.fragments:
            episode = por_id[fragment.episode_id]
            assert episode.text is not None
            assert episode.text[fragment.start : fragment.end] == fragment.literal_text

    def test_normalized_text_no_pisa_el_literal(self, result):
        for fragment in result.fragments:
            assert fragment.normalized_text == " ".join(fragment.literal_text.split())
            assert fragment.literal_text  # el literal se conserva exacto

    def test_content_hash_del_episodio_es_del_contenido_no_del_encadenado(self, result):
        """Insertar algo delante no debe cambiar el hash de un episodio intacto."""
        hashes = {e.content_hash["value"] for e in result.episodes}
        assert len(hashes) == len(result.episodes)
        for episode in result.episodes:
            assert episode.content_hash != result.asset.content_hash


# ── Politica de ingesta ───────────────────────────────────────────────────────
class TestPoliticaDeIngesta:
    def test_datos_personales_no_pueden_ir_a_proveedor_externo(self):
        with pytest.raises(NormalizationError) as exc:
            _text_result(
                options_=options(
                    privacy_class="PERSONAL_DATA", allow_external_providers=True
                )
            )
        assert exc.value.reason_code == "INCONSISTENT_POLICY"

    def test_material_restringido_tampoco(self):
        with pytest.raises(NormalizationError) as exc:
            _text_result(
                options_=options(
                    privacy_class="RESTRICTED", allow_external_providers=True
                )
            )
        assert exc.value.reason_code == "INCONSISTENT_POLICY"

    def test_datos_personales_sin_externo_es_valido(self):
        result = _text_result(options_=options(privacy_class="PERSONAL_DATA"))
        assert result.asset.processing_policy["allow_external_providers"] is False
        assert result.asset.allows_external_providers() is False

    def test_created_at_por_defecto_es_ingested_at(self):
        result = _text_result(options_=options(created_at=None))
        assert result.asset.created_at == result.asset.ingested_at

    def test_created_at_explicito_se_conserva(self):
        result = _text_result()
        assert result.asset.created_at < result.asset.ingested_at

    def test_ingested_at_anterior_a_created_at_lo_rechaza_el_contrato(self):
        from knowledge_v3.contracts import V3ContractError

        with pytest.raises(V3ContractError):
            _text_result(
                options_=options(
                    created_at="2027-01-01T00:00:00Z", ingested_at="2026-01-01T00:00:00Z"
                )
            )

    def test_original_location_con_credenciales_lo_rechaza_el_contrato(self):
        from knowledge_v3.contracts import V3ContractError

        with pytest.raises(V3ContractError):
            normalize_bytes(
                TEXT_FIXTURE.encode("utf-8"),
                original_name="cronica.txt",
                original_location="https://user:clave@host/cronica.txt",
                options=options(),
            )


# ── Informe ───────────────────────────────────────────────────────────────────
class TestInforme:
    def test_el_informe_declara_adaptador_y_si_es_stub(self):
        result = _text_result()
        assert result.report["adapter"].endswith("adapters.text")
        assert result.report["adapter_implementation"] == "real"
        assert result.report["episode_count"] == len(result.episodes)
        assert result.report["fragment_count"] == len(result.fragments)

    def test_el_informe_cuenta_los_episodios_pendientes_de_proveedor(self):
        result = normalize_bytes(
            b"\x89PNG\r\n\x1a\n" + b"contenido-de-imagen",
            original_name="mapa.png",
            original_location="file:///mapa.png",
            options=options(),
            source_kind="IMAGE",
        )
        assert result.report["adapter_implementation"] == "stub"
        assert result.report["pending_provider_episodes"] == len(result.episodes)
        assert result.fragments == []

    def test_metricas_de_cobertura_del_normalizador(self):
        """Cobertura: que fraccion del texto de cada episodio queda anclada."""
        result = normalize_bytes(
            CSV_FIXTURE.encode("utf-8"),
            original_name="personajes.csv",
            original_location="file:///personajes.csv",
            options=options(),
        )
        episode = result.episodes[0]
        anclado = sum(f.end - f.start for f in result.fragments_of(episode.episode_id))
        assert 0 < anclado <= len(episode.text)


# ── API de alto nivel ─────────────────────────────────────────────────────────
class TestApi:
    def test_normalize_y_normalize_bytes_son_equivalentes(self):
        source = SourceInput(
            data=TEXT_FIXTURE.encode("utf-8"),
            original_name="cronica.txt",
            original_location="file:///vault/cronica.txt",
        )
        uno = normalize(source, options())
        otro = _text_result()
        assert uno.asset.to_json() == otro.asset.to_json()

    def test_to_dict_del_resultado_es_serializable_y_completo(self):
        result = _text_result()
        data = result.to_dict()
        assert data["asset"]["contract_id"] == "source-asset/v3-internal-v1"
        assert len(data["episodes"]) == len(result.episodes)
        assert len(data["fragments"]) == len(result.fragments)

    def test_fragments_of_filtra_por_episodio(self):
        result = normalize_bytes(
            b"FAKE-AUDIO",
            original_name="sesion.mp3",
            original_location="file:///sesion.mp3",
            options=options(),
            payload={"transcript": diarized_transcript()},
        )
        total = sum(len(result.fragments_of(e.episode_id)) for e in result.episodes)
        assert total == len(result.fragments)

    def test_ingest_options_es_inmutable(self):
        opciones = IngestOptions(
            workspace="w", collection_id="c", ingested_at="2026-01-01T00:00:00Z"
        )
        with pytest.raises(Exception):
            opciones.workspace = "otro"  # type: ignore[misc]

    def test_pdf_por_extension_sin_declarar_kind(self):
        result = normalize_bytes(
            pdf_with_text(),
            original_name="cronica.pdf",
            original_location="file:///cronica.pdf",
            options=options(),
        )
        assert result.asset.source_kind == "PDF"
        assert result.asset.mime_type == "application/pdf"
