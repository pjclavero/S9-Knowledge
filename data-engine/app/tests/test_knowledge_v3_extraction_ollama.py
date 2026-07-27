# -*- coding: utf-8 -*-
"""Extractor Ollama: cliente MOCKEADO + un humo real opcional.

La suite unitaria no toca la red **nunca**: el transporte del cliente es
inyectable y aqui se inyecta un doble. Un gate que dependa de que un servidor
este vivo no es un gate.

El unico test que sale a la red es `TestLiveOllama`, marcado
`@pytest.mark.live_ollama` y saltado salvo que `S9K_LIVE_OLLAMA=1`. Es solo
inferencia (lectura): no escribe en ningun sitio.
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.extraction import (  # noqa: E402
    OllamaClient,
    OllamaConfig,
    OllamaExtractor,
    OllamaUnavailable,
    build_prompt,
    parse_strict_json,
)
from knowledge_v3.extraction.ollama_client import (  # noqa: E402
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_TIMEOUT,
    OllamaBadResponse,
    redact_url,
)

from test_knowledge_v3_extraction import single_context  # noqa: E402

TEXT = "Kael vive en Valdor y sirve a la Orden del Alba."


def fake_transport(responses):
    """Doble del transporte HTTP. Devuelve las respuestas dadas, en orden."""
    calls = []

    def transport(url, payload, timeout):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return {"response": item, "model": payload["model"]}

    transport.calls = calls
    return transport


def client_with(responses, **over) -> OllamaClient:
    config = OllamaConfig(url="http://ollama.invalid:11434", model="modelo-de-prueba", **over)
    return OllamaClient(config=config, transport=fake_transport(responses))


VALID_PAYLOAD = json.dumps(
    {
        "mentions": [
            {"surface": "Kael", "type": "Character", "confidence": 0.9,
             "fragment_id": "frag:ep:llm:0", "quote": "Kael vive en Valdor"},
            {"surface": "Valdor", "type": "Location", "confidence": 0.9,
             "fragment_id": "frag:ep:llm:0", "quote": "Kael vive en Valdor"},
        ],
        "claims": [
            {"subject": "Kael", "object": "Valdor", "predicate": "LIVES_IN",
             "relation": "vive en", "negated": False, "epistemic": "ASSERTED",
             "confidence": 0.95, "fragment_id": "frag:ep:llm:0",
             "quote": "Kael vive en Valdor"},
        ],
    }
)


class TestConfig:
    def test_valores_por_defecto_documentados(self, monkeypatch):
        for var in ("S9K_OLLAMA_URL", "S9K_OLLAMA_MODEL", "S9K_OLLAMA_TIMEOUT"):
            monkeypatch.delenv(var, raising=False)
        config = OllamaConfig.from_env()
        assert config.url == DEFAULT_OLLAMA_URL == "http://192.168.1.157:11434"
        assert config.model == DEFAULT_OLLAMA_MODEL == "qwen2.5:7b"

    def test_el_entorno_manda(self, monkeypatch):
        monkeypatch.setenv("S9K_OLLAMA_URL", "http://otro-host:11434/")
        monkeypatch.setenv("S9K_OLLAMA_MODEL", "otro-modelo")
        monkeypatch.setenv("S9K_OLLAMA_TIMEOUT", "5")
        config = OllamaConfig.from_env()
        assert config.generate_endpoint == "http://otro-host:11434/api/generate"
        assert (config.model, config.timeout) == ("otro-modelo", 5.0)

    def test_timeout_invalido_no_rompe_el_arranque(self, monkeypatch):
        monkeypatch.setenv("S9K_OLLAMA_TIMEOUT", "no-es-un-numero")
        assert OllamaConfig.from_env().timeout == DEFAULT_TIMEOUT == 300.0

    def test_los_errores_no_filtran_el_host(self):
        assert redact_url("http://192.168.1.157:11434/api/generate") == (
            "http://<host>/api/generate"
        )


class TestClient:
    def test_pide_json_y_temperatura_cero(self):
        client = client_with(['{"mentions":[],"claims":[]}'])
        client.generate("hola", system="s")
        payload = client._transport.calls[0]["payload"]
        assert payload["format"] == "json"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.0
        assert payload["system"] == "s"

    def test_reintenta_los_fallos_de_transporte(self):
        client = client_with([OllamaUnavailable("caido"), '{"mentions":[],"claims":[]}'])
        response = client.generate("hola")
        assert response.attempts == 2

    def test_falla_cerrado_cuando_no_hay_servidor(self):
        client = client_with([OllamaUnavailable("caido")], retries=0)
        with pytest.raises(OllamaUnavailable):
            client.generate("hola")

    def test_respuesta_sin_campo_response(self):
        def transport(url, payload, timeout):
            return {"otra_cosa": 1}

        client = OllamaClient(
            config=OllamaConfig(url="http://x:1", retries=0), transport=transport
        )
        with pytest.raises(OllamaBadResponse):
            client.generate("hola")


class TestJSONParsing:
    @pytest.mark.parametrize(
        "raw",
        [
            '{"mentions":[],"claims":[]}',
            '```json\n{"mentions":[],"claims":[]}\n```',
            'Claro, aqui tienes:\n{"mentions":[],"claims":[]}\nEspero que sirva.',
        ],
    )
    def test_repara_solo_la_sintaxis(self, raw):
        assert parse_strict_json(raw) == {"mentions": [], "claims": []}

    @pytest.mark.parametrize("raw", ["", "   ", "no hay json aqui", "[1,2,3]", "{roto"])
    def test_lo_que_no_es_json_no_se_adivina(self, raw):
        with pytest.raises(Exception):
            parse_strict_json(raw)


class TestOllamaExtractor:
    def test_extraccion_valida_anclada_y_trazada(self):
        ctx, episode = single_context("ep:llm", TEXT)
        extractor = OllamaExtractor(client_with([VALID_PAYLOAD]))
        out = extractor.extract(ctx)
        claim = [c for c in out.claims if not c.abstained][0]
        assert claim.best_predicate() == "LIVES_IN"
        assert claim.producing_provider()["provider"] == "ollama"
        assert claim.producing_provider()["model"] == "modelo-de-prueba"
        assert claim.review_required is True
        assert claim.confidence <= 0.7
        assert claim.evidence_fragment_ids == ["frag:ep:llm:0"]
        for doc in [*out.mentions, *out.claims]:
            doc.validate()

    def test_json_invalido_reintenta_una_vez_y_luego_se_abstiene(self):
        client = client_with(["no soy json", "sigo sin ser json"])
        ctx, _ = single_context("ep:llm", TEXT)
        out = OllamaExtractor(client).extract(ctx)
        assert client._transport.calls.__len__() == 2
        assert "OLLAMA_INVALID_JSON" in out.codes()
        assert out.claims[0].abstained is True
        assert out.claims[0].confidence == 0.0

    def test_el_reintento_recupera_una_respuesta_valida(self):
        client = client_with(["basura", VALID_PAYLOAD])
        ctx, _ = single_context("ep:llm", TEXT)
        out = OllamaExtractor(client).extract(ctx)
        assert [c for c in out.claims if not c.abstained]

    def test_servidor_caido_produce_abstencion_no_error(self):
        client = client_with([OllamaUnavailable("caido")], retries=0)
        ctx, _ = single_context("ep:llm", TEXT)
        out = OllamaExtractor(client).extract(ctx)
        assert "OLLAMA_UNAVAILABLE" in out.codes()
        assert out.claims[0].abstained is True

    def test_no_se_fia_de_los_fragment_id_del_modelo(self):
        payload = json.dumps(
            {
                "mentions": [
                    {"surface": "Kael", "type": "Character",
                     "fragment_id": "frag:que-no-existe"},
                    {"surface": "Melkor", "type": "Character",
                     "fragment_id": "frag:tampoco-existe"},
                ],
                "claims": [],
            }
        )
        ctx, _ = single_context("ep:llm", TEXT)
        out = OllamaExtractor(client_with([payload])).extract(ctx)
        assert [m.surface for m in out.mentions] == ["Kael"]
        assert out.mentions[0].evidence_fragment_ids == ["frag:ep:llm:0"]
        assert "HALLUCINATED_MENTION" in out.codes()

    def test_el_prompt_lleva_los_fragmentos_reales(self):
        ctx, episode = single_context("ep:llm", TEXT)
        prompt = build_prompt(episode, ctx.index_of(episode))
        assert "frag:ep:llm:0" in prompt
        assert TEXT in prompt
        assert "mentions" in prompt and "claims" in prompt

    def test_un_episodio_sin_texto_no_se_manda_al_modelo(self):
        from test_knowledge_v3_extraction import ExtractionContext, WORKSPACE, make_episode, make_fragment

        episode = make_episode("ep:img", text=None, modality="IMAGE")
        frag = make_fragment(episode, "frag:img", "un mapa", 0, media_type="TABLE")
        ctx = ExtractionContext(WORKSPACE, [episode], [frag])
        client = client_with([VALID_PAYLOAD])
        out = OllamaExtractor(client).extract(ctx)
        assert client._transport.calls == []
        assert (out.mentions, out.claims) == ([], [])


@pytest.mark.live_ollama
@pytest.mark.skipif(
    os.environ.get("S9K_LIVE_OLLAMA") != "1",
    reason="humo real contra Ollama: se activa con S9K_LIVE_OLLAMA=1",
)
class TestLiveOllama:
    """Humo REAL contra el servidor configurado. Solo inferencia, solo lectura.

    No exige calidad de extraccion: exige que la cadena completa (cliente,
    prompt, JSON estricto, anclaje, contratos) funcione contra el modelo de
    verdad y que NADA sin anclaje llegue a emitirse.
    """

    def test_el_servidor_responde_y_tiene_el_modelo(self):
        client = OllamaClient()
        modelos = client.list_models()
        assert modelos, "el servidor no declara ningun modelo"
        assert client.config.model in modelos

    def test_extraccion_real_ancla_todo_lo_que_emite(self):
        ctx, episode = single_context("ep:live", TEXT)
        out = OllamaExtractor(OllamaClient()).extract(ctx)
        reales = {f.fragment_id for f in ctx.fragments_of(episode.episode_id)}
        for doc in [*out.mentions, *out.claims]:
            doc.validate()
            assert set(doc.evidence_fragment_ids) <= reales
        for mention in out.mentions:
            assert episode.text[mention.start:mention.end] == mention.surface
        for claim in out.claims:
            if not claim.abstained:
                assert claim.review_required is True
                assert claim.confidence <= 0.7
        print(
            "\n[humo ollama] menciones=%d claims=%d abstenidos=%d diagnosticos=%s"
            % (
                len(out.mentions),
                len(out.claims),
                len([c for c in out.claims if c.abstained]),
                sorted(set(out.codes())),
            )
        )
