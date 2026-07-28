# -*- coding: utf-8 -*-
"""Extractor SEMANTICO: ontologia compilada, candidatos, anclaje y puerto agnostico.

La suite NO toca la red: el puerto de inferencia es inyectable y aqui se inyecta
un doble guionizado. Lo que se fija es el COMPORTAMIENTO, no la calidad: la
calidad la mide `semantic_bench` contra el split dev y se publica en
docs/v3/measurements/.

Cuatro familias, en orden de importancia:

1. **anti-alucinacion**: superficie inexistente, cita inexistente, fecha
   inventada, argumentos sin anclar. Nada de eso puede salir;
2. **ontologia**: el predicado sale del perfil o no sale; los candidatos
   sobreviven en orden; un candidato malo no tira los buenos;
3. **contrato congelado**: todo documento valida, `UNRESOLVED` no se cuela como
   direccion, y los campos que no existen viajan en `metadata`;
4. **agnosticismo del proveedor**: el mismo prompt y la misma salida con dos
   adaptadores distintos.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import Provider  # noqa: E402
from knowledge_v3.extraction import (  # noqa: E402
    ExtractionPipeline,
    Lexicon,
    LexiconEntry,
    SemanticEpisodeExtractor,
)
from knowledge_v3.extraction.ontology_prompt import (  # noqa: E402
    CORE_PREDICATE_DEFINITIONS,
    compile_ontology,
    render_prompt,
)
from knowledge_v3.extraction.payload import (  # noqa: E402
    UNRESOLVED_DIRECTION,
    anchor_in_episode,
    normalize_semantic_payload,
)
from knowledge_v3.extraction.provider_port import (  # noqa: E402
    MockProviderPort,
    OllamaProviderPort,
    ProviderBadJSON,
    ProviderRequest,
    ProviderUnavailable,
)
from knowledge_v3.extraction.semantic import SEMANTIC_STEP  # noqa: E402
from knowledge_v3.extraction.temporal import (  # noqa: E402
    TEMPORAL_AMBIGUOUS,
    TEMPORAL_NONE,
    TEMPORAL_RESOLVED,
    resolve_locally,
    validate_model_expressions,
)

from test_knowledge_v3_extraction import (  # noqa: E402
    GOLD_LEXICON,
    make_profile,
    single_context,
)

TEXT = "Elara pertenece a la Orden del Alba desde el año 300."


def context(text: str = TEXT, *, episode_id: str = "ep:sem", **over):
    return single_context(episode_id, text, profile=make_profile(), **over)


def port_returning(payload, **over) -> MockProviderPort:
    return MockProviderPort(handler=lambda request: payload, **over)


def run(payload, text: str = TEXT, **over):
    ctx, episode = context(text)
    extractor = SemanticEpisodeExtractor(port_returning(payload), **over)
    return extractor, extractor.extract_episode(ctx, episode)


def mention(ref: str, surface: str, tipo: str = "Character", quote: str = TEXT) -> dict:
    return {
        "local_ref": ref,
        "surface": surface,
        "type_candidates": [{"type": tipo, "confidence": 0.9}],
        "evidence_quote": quote,
    }


def claim(**over) -> dict:
    base = {
        "subject_ref": "m1",
        "object_ref": "m2",
        "relation_phrase": "pertenece a",
        "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.8}],
        "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.8}],
        "evidence_quote": TEXT,
        "negated": False,
        "epistemic_status": "ASSERTED",
        "temporal_expressions": [],
        "temporal_resolution_required": False,
    }
    base.update(over)
    return base


BASE_MENTIONS = [mention("m1", "Elara"), mention("m2", "Orden del Alba", "Faction")]


def asserted(out) -> list:
    return [c for c in out.claims if not c.abstained]


def abstained(out) -> list:
    return [c for c in out.claims if c.abstained]


def codes(out) -> set:
    return {d.code for d in out.diagnostics}


# ==========================================================================
# 1. Ontologia compilada
# ==========================================================================
class TestOntologiaCompilada:
    def test_se_compila_del_perfil_y_no_del_codigo(self):
        onto = compile_ontology(make_profile(), lexicon=GOLD_LEXICON)
        assert set(onto.predicate_names) == {
            p["predicate"] for p in make_profile().predicates
        }

    def test_cada_predicado_lleva_definicion(self):
        onto = compile_ontology(make_profile())
        for spec in onto.predicates:
            assert spec.definition
            if spec.predicate in CORE_PREDICATE_DEFINITIONS:
                assert spec.definition == CORE_PREDICATE_DEFINITIONS[spec.predicate]

    def test_predicado_fuera_del_nucleo_recibe_definicion_derivada(self):
        profile = make_profile(
            predicates=[
                {"predicate": "PATROLS", "domain": ["Character"], "range": ["Location"]}
            ]
        )
        spec = compile_ontology(profile).predicates[0]
        assert "derivada del perfil" in spec.definition

    def test_confundibles_se_calculan_no_se_escriben(self):
        onto = compile_ontology(make_profile())
        member = next(p for p in onto.predicates if p.predicate == "MEMBER_OF")
        # Mismo dominio y mismo rango que MEMBER_OF: es la confusion real.
        assert "LEADS" in member.confusable_with
        assert "MEMBER_OF" not in member.confusable_with

    def test_sin_perfil_no_hay_ontologia(self):
        with pytest.raises(ValueError):
            compile_ontology(None)

    def test_el_perfil_puede_restringir_los_tipos(self):
        profile = make_profile(entity_types=["Character", "Faction"])
        onto = compile_ontology(profile, entity_types=("Character", "Faction"))
        assert onto.entity_types == ("Character", "Faction")

    def test_el_prompt_lleva_ontologia_texto_y_esquema(self):
        ctx, episode = context()
        prompt = render_prompt(
            compile_ontology(make_profile(), lexicon=GOLD_LEXICON),
            episode,
            ctx.index_of(episode),
        )
        assert "MEMBER_OF" in prompt and "no confundir con" in prompt
        assert TEXT in prompt
        assert "predicate_candidates" in prompt and "direction_candidates" in prompt
        # Los fragment_id NO se le ensenan al modelo: no puede aportarlos.
        assert "frag:ep:sem:0" not in prompt

    def test_las_entidades_conocidas_no_son_una_lista_cerrada(self):
        prompt_onto = compile_ontology(make_profile(), lexicon=GOLD_LEXICON).render()
        assert "no para limitarte a ellas" in prompt_onto
        assert "Elara" in prompt_onto

    def test_el_prompt_es_determinista(self):
        ctx, episode = context()
        onto = compile_ontology(make_profile(), lexicon=GOLD_LEXICON)
        index = ctx.index_of(episode)
        assert render_prompt(onto, episode, index) == render_prompt(onto, episode, index)


# ==========================================================================
# 2. Anti-alucinacion (la frontera que NO se toca)
# ==========================================================================
class TestAntiAlucinacion:
    def test_superficie_inexistente_se_descarta(self):
        _ex, out = run(
            {"mentions": [mention("m1", "Kaelthorn el Invisible")], "claims": [], "abstentions": []}
        )
        assert out.mentions == []
        assert "HALLUCINATED_MENTION" in codes(out)

    def test_cita_inexistente_tumba_la_mencion(self):
        _ex, out = run(
            {
                "mentions": [mention("m1", "Elara", quote="Elara gobierna Nara")],
                "claims": [],
                "abstentions": [],
            }
        )
        assert out.mentions == []
        assert "HALLUCINATED_QUOTE" in codes(out)

    def test_claim_sin_cita_se_abstiene(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [claim(evidence_quote="")],
                "abstentions": [],
            }
        )
        assert asserted(out) == []
        assert "CLAIM_WITHOUT_QUOTE" in abstained(out)[0].metadata["abstention_reasons"]

    def test_argumento_no_anclado_no_crea_mencion_de_apoyo(self):
        _ex, out = run(
            {
                "mentions": [mention("m1", "Elara")],
                "claims": [claim(object_ref="m2")],
                "abstentions": [],
            }
        )
        assert len(out.mentions) == 1
        assert asserted(out) == []
        assert "OBJECT_NOT_GROUNDED" in codes(out)

    def test_contexto_que_niega_impide_afirmar(self):
        texto = "Elara no pertenece a la Orden del Alba."
        _ex, out = run(
            {
                "mentions": [
                    mention("m1", "Elara", quote=texto),
                    mention("m2", "Orden del Alba", "Faction", quote=texto),
                ],
                "claims": [claim(evidence_quote=texto, negated=False)],
                "abstentions": [],
            },
            text=texto,
        )
        assert asserted(out) == []
        assert "NEGATION_CONTEXT_MISMATCH" in abstained(out)[0].metadata["abstention_reasons"]

    def test_fecha_inventada_no_entra(self):
        expresiones, codigos = validate_model_expressions(
            [{"text": "el 4 de mayo de 1999", "kind": "POINT"}],
            _index(),
        )
        assert expresiones == []
        assert "HALLUCINATED_TEMPORAL_EXPRESSION" in codigos

    def test_la_confianza_del_modelo_esta_acotada(self):
        _ex, out = run(
            {
                "mentions": [
                    dict(mention("m1", "Elara"), type_candidates=[{"type": "Character", "confidence": 1.0}]),
                    mention("m2", "Orden del Alba", "Faction"),
                ],
                "claims": [claim(predicate_candidates=[{"predicate": "MEMBER_OF", "confidence": 0.99}])],
                "abstentions": [],
            }
        )
        assert out.mentions[0].confidence <= 0.7
        assert asserted(out)[0].confidence <= 0.7

    def test_ninguna_salida_aprueba_nada(self):
        _ex, out = run({"mentions": BASE_MENTIONS, "claims": [claim()], "abstentions": []})
        for c in out.claims:
            assert c.review_required is True
            assert c.produced_by_step == SEMANTIC_STEP


def _index():
    ctx, episode = context()
    return ctx.index_of(episode)


# ==========================================================================
# 3. Anclaje por episodio con evidencia debajo
# ==========================================================================
class TestAnclaje:
    def test_una_cita_de_frase_completa_ancla_aunque_cruce_fragmentos(self):
        ctx, episode = single_context("ep:frag", TEXT, profile=make_profile())
        index = ctx.index_of(episode)
        assert anchor_in_episode(index, TEXT) is not None

    def test_una_cita_que_no_esta_no_ancla(self):
        assert anchor_in_episode(_index(), "Elara gobierna Nara") is None

    def test_los_offsets_los_calcula_el_sistema_local(self):
        anchor = anchor_in_episode(_index(), "Orden del Alba")
        assert TEXT[anchor.start:anchor.end] == "Orden del Alba"

    def test_sin_fragmento_debajo_no_hay_anclaje(self):
        # Fragmento que solo cubre el principio: la cita del final no tiene
        # evidencia real detras y no puede salir.
        from test_knowledge_v3_extraction import make_episode, make_fragment
        from knowledge_v3.extraction import ExtractionContext

        episode = make_episode("ep:parcial", text=TEXT)
        fragment = make_fragment(episode, "frag:ep:parcial:0", "Elara", 0)
        ctx = ExtractionContext(
            workspace=episode.workspace,
            episodes=[episode],
            fragments=[fragment],
            profile=make_profile(),
        )
        index = ctx.index_of(episode)
        assert anchor_in_episode(index, "Elara") is not None
        assert anchor_in_episode(index, "Orden del Alba") is None


# ==========================================================================
# 4. Ontologia cerrada y candidatos multiples
# ==========================================================================
class TestPredicadosYCandidatos:
    def test_candidatos_multiples_sobreviven_ordenados(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [
                    claim(
                        predicate_candidates=[
                            {"predicate": "MEMBER_OF", "confidence": 0.8},
                            {"predicate": "LEADS", "confidence": 0.4},
                        ]
                    )
                ],
                "abstentions": [],
            }
        )
        candidatos = [c["predicate"] for c in asserted(out)[0].predicate_candidates]
        assert candidatos == ["MEMBER_OF", "LEADS"]

    def test_un_candidato_fuera_de_la_ontologia_no_tira_los_buenos(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [
                    claim(
                        predicate_candidates=[
                            {"predicate": "MEMBER_OF", "confidence": 0.8},
                            {"predicate": "PERTENECE_MUCHO", "confidence": 0.6},
                        ]
                    )
                ],
                "abstentions": [],
            }
        )
        assert [c["predicate"] for c in asserted(out)[0].predicate_candidates] == ["MEMBER_OF"]
        assert asserted(out)[0].metadata["dropped_predicates"] == ["PERTENECE_MUCHO"]

    def test_sin_ningun_predicado_valido_se_abstiene(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [claim(predicate_candidates=[{"predicate": "INVENTADO", "confidence": 0.9}])],
                "abstentions": [],
            }
        )
        assert asserted(out) == []
        assert "PREDICATE_NOT_IN_PROFILE" in abstained(out)[0].metadata["abstention_reasons"]

    def test_el_tope_de_candidatos_se_respeta(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [
                    claim(
                        predicate_candidates=[
                            {"predicate": "MEMBER_OF", "confidence": 0.8},
                            {"predicate": "LEADS", "confidence": 0.7},
                            {"predicate": "LIVES_IN", "confidence": 0.6},
                            {"predicate": "OWNS", "confidence": 0.5},
                        ]
                    )
                ],
                "abstentions": [],
            }
        )
        assert len(asserted(out)[0].predicate_candidates) == 3


class TestDireccion:
    def test_la_direccion_la_dice_el_modelo(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [
                    claim(direction_candidates=[{"direction": "OBJECT_TO_SUBJECT", "confidence": 0.9}])
                ],
                "abstentions": [],
            }
        )
        assert asserted(out)[0].best_direction() == "OBJECT_TO_SUBJECT"

    def test_unresolved_no_se_convierte_en_una_direccion_inventada(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [
                    claim(direction_candidates=[{"direction": UNRESOLVED_DIRECTION, "confidence": 0.5}])
                ],
                "abstentions": [],
            }
        )
        propuesta = asserted(out)[0]
        assert propuesta.direction_candidates == []
        assert propuesta.metadata["direction_unresolved"] is True

    def test_una_direccion_desconocida_se_diagnostica(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [claim(direction_candidates=[{"direction": "HACIA_ARRIBA", "confidence": 0.5}])],
                "abstentions": [],
            }
        )
        assert "UNKNOWN_DIRECTION" in codes(out)


# ==========================================================================
# 5. Temporalidad escalonada
# ==========================================================================
class TestTemporalidadEscalonada:
    def test_lo_explicito_se_resuelve_sin_llamar_al_modelo(self):
        ctx, episode = context("Kael lideró la Orden desde 1200 hasta 1250.")
        resolucion = resolve_locally(ctx.index_of(episode))
        assert resolucion.status == TEMPORAL_RESOLVED
        assert resolucion.needs_model is False

    def test_sin_tiempo_no_hay_nada_que_resolver(self):
        ctx, episode = context("Elara pertenece a la Orden del Alba.")
        assert resolve_locally(ctx.index_of(episode)).status == TEMPORAL_NONE

    def test_lo_relativo_sin_ancla_queda_ambiguo(self):
        ctx, episode = context("Elara lideró la Orden del Alba entonces.")
        resolucion = resolve_locally(ctx.index_of(episode))
        assert resolucion.status == TEMPORAL_AMBIGUOUS
        assert resolucion.needs_model is True

    def test_la_segunda_llamada_solo_se_gasta_si_hay_ambiguedad(self):
        texto = "Elara pertenece a la Orden del Alba desde 1200 hasta 1250."
        ctx, episode = context(texto)
        port = port_returning(
            {
                "mentions": [
                    mention("m1", "Elara", quote=texto),
                    mention("m2", "Orden del Alba", "Faction", quote=texto),
                ],
                "claims": [claim(evidence_quote=texto)],
                "abstentions": [],
            }
        )
        extractor = SemanticEpisodeExtractor(port)
        extractor.extract_episode(ctx, episode)
        assert extractor.runs[0].temporal_calls == 0
        assert [r.purpose for r in port.requests] == ["extraction"]

    def test_el_resultado_temporal_del_modelo_se_valida_en_local(self):
        expresiones, _codigos = validate_model_expressions(
            [{"text": "el año 300", "kind": "POINT"}], _index()
        )
        assert expresiones and expresiones[0]["text"] == "el año 300"


# ==========================================================================
# 6. Contrato congelado
# ==========================================================================
class TestContratoCongelado:
    def test_todo_lo_emitido_valida(self):
        _ex, out = run(
            {
                "mentions": BASE_MENTIONS,
                "claims": [claim()],
                "abstentions": [{"evidence_quote": TEXT, "reason": "no lo veo claro"}],
            }
        )
        for doc in [*out.mentions, *out.claims]:
            doc.validate()
        assert "CONTRACT_VIOLATION" not in codes(out)

    def test_los_campos_que_no_existen_viajan_en_metadata(self):
        _ex, out = run({"mentions": BASE_MENTIONS, "claims": [claim()], "abstentions": []})
        propuesta = asserted(out)[0]
        assert "temporal_resolution_required" in propuesta.metadata
        assert "untrusted_origin" in propuesta.metadata
        # y NO como campo del documento
        assert "temporal_resolution_required" not in propuesta.to_dict()
        assert "untrusted_origin" not in propuesta.to_dict()

    def test_la_razon_de_abstencion_es_un_codigo_estable(self):
        _ex, out = run(
            {
                "mentions": [],
                "claims": [],
                "abstentions": [{"evidence_quote": TEXT, "reason": "no se leerlo"}],
            }
        )
        assert abstained(out)[0].metadata["abstention_reasons"] == ["NO_SE_LEERLO"]

    def test_los_identificadores_son_deterministas(self):
        payload = {"mentions": BASE_MENTIONS, "claims": [claim()], "abstentions": []}
        _a, primera = run(payload)
        _b, segunda = run(payload)
        assert [m.mention_id for m in primera.mentions] == [m.mention_id for m in segunda.mentions]
        assert [c.claim_id for c in primera.claims] == [c.claim_id for c in segunda.claims]

    def test_la_traza_dice_la_verdad(self):
        _ex, out = run({"mentions": BASE_MENTIONS, "claims": [claim()], "abstentions": []})
        traza = out.mentions[0].provider_trace[0]
        assert traza["step"] == SEMANTIC_STEP
        assert traza["model"] == "mock"


# ==========================================================================
# 7. Puerto agnostico del proveedor
# ==========================================================================
class TestPuertoAgnostico:
    def test_el_mismo_payload_da_lo_mismo_con_dos_puertos(self):
        payload = {"mentions": BASE_MENTIONS, "claims": [claim()], "abstentions": []}
        ctx, episode = context()

        salidas = []
        for puerto in (
            MockProviderPort(handler=lambda r: payload, model="mock"),
            MockProviderPort(handler=lambda r: payload, model="otro-modelo"),
        ):
            extractor = SemanticEpisodeExtractor(puerto)
            out = extractor.extract_episode(ctx, episode)
            salidas.append(
                [(m.surface, m.start, m.end) for m in out.mentions]
                + [(c.best_predicate(), c.best_direction()) for c in out.claims]
            )
        assert salidas[0] == salidas[1]

    def test_el_prompt_no_depende_del_proveedor(self):
        payload = {"mentions": [], "claims": [], "abstentions": []}
        ctx, episode = context()
        prompts = []
        for modelo in ("qwen-de-prueba", "llama-de-prueba"):
            puerto = MockProviderPort(handler=lambda r: payload, model=modelo)
            SemanticEpisodeExtractor(puerto).extract_episode(ctx, episode)
            prompts.append(puerto.requests[0].prompt)
        assert prompts[0] == prompts[1]

    def test_proveedor_caido_produce_abstencion_no_resultado(self):
        ctx, episode = context()
        puerto = MockProviderPort(responses=[ProviderUnavailable("sin red")])
        out = SemanticEpisodeExtractor(puerto).extract_episode(ctx, episode)
        assert out.mentions == []
        assert abstained(out)[0].metadata["abstention_reasons"] == ["PROVIDER_UNAVAILABLE"]

    def test_json_invalido_produce_abstencion_no_resultado(self):
        ctx, episode = context()
        puerto = MockProviderPort(responses=[ProviderBadJSON("no es json")])
        out = SemanticEpisodeExtractor(puerto).extract_episode(ctx, episode)
        assert "PROVIDER_INVALID_JSON" in codes(out)
        assert asserted(out) == []

    def test_el_puerto_ollama_reintenta_una_vez_el_json(self):
        from test_knowledge_v3_extraction_ollama import client_with

        puerto = OllamaProviderPort(client=client_with(["esto no es json", '{"mentions":[]}']))
        respuesta = puerto.complete_json(ProviderRequest(system="s", prompt="p"))
        assert respuesta.json_retries == 1
        assert respuesta.payload == {"mentions": []}

    def test_el_puerto_ollama_declara_su_proveedor_real(self):
        from test_knowledge_v3_extraction_ollama import client_with

        puerto = OllamaProviderPort(client=client_with(['{"mentions":[]}']))
        assert puerto.provider is Provider.OLLAMA

    def test_el_mock_no_se_disfraza_de_proveedor(self):
        assert MockProviderPort().provider is Provider.LOCAL


class FakeNvidiaClient:
    """Doble del cliente NVIDIA ya existente. No toca la red ni pide API key."""

    def __init__(self, parsed, *, model="meta/llama-3.3-70b-instruct"):
        self.parsed = parsed
        self.model = model
        self.calls = []

    def chat_json(self, messages, *, model=None, max_tokens=1024):
        self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        if isinstance(self.parsed, Exception):
            raise self.parsed
        return {
            "parsed": self.parsed,
            "model": self.model,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }


class TestPuertoNvidia:
    """El carril externo se prueba con doble: la key solo existe en VM105."""

    def test_traduce_la_peticion_a_mensajes_de_chat(self):
        from knowledge_v3.extraction.provider_port import NvidiaProviderPort

        cliente = FakeNvidiaClient({"mentions": [], "claims": []})
        puerto = NvidiaProviderPort(client=cliente)
        puerto.complete_json(ProviderRequest(system="SIS", prompt="USUARIO", max_tokens=2048))
        roles = [m["role"] for m in cliente.calls[0]["messages"]]
        assert roles == ["system", "user"]
        assert cliente.calls[0]["max_tokens"] == 2048

    def test_declara_proveedor_externo_y_reporta_consumo(self):
        from knowledge_v3.extraction.provider_port import NvidiaProviderPort

        puerto = NvidiaProviderPort(client=FakeNvidiaClient({"mentions": []}))
        respuesta = puerto.complete_json(ProviderRequest(system="s", prompt="p"))
        assert puerto.provider is Provider.EXTERNAL
        assert respuesta.usage["total_tokens"] == 120
        assert respuesta.model == "meta/llama-3.3-70b-instruct"

    def test_un_fallo_del_proveedor_no_devuelve_datos(self):
        from knowledge_v3.extraction.provider_port import NvidiaProviderPort

        puerto = NvidiaProviderPort(client=FakeNvidiaClient(RuntimeError("caido")))
        with pytest.raises(ProviderUnavailable):
            puerto.complete_json(ProviderRequest(system="s", prompt="p"))

    def test_el_extractor_no_distingue_el_carril(self):
        """Misma salida con el puerto externo que con el local: ese es el punto."""
        from knowledge_v3.extraction.provider_port import NvidiaProviderPort

        payload = {"mentions": BASE_MENTIONS, "claims": [claim()], "abstentions": []}
        ctx, episode = context()
        externo = SemanticEpisodeExtractor(NvidiaProviderPort(client=FakeNvidiaClient(payload)))
        local = SemanticEpisodeExtractor(port_returning(payload))
        salida_externa = externo.extract_episode(ctx, episode)
        salida_local = local.extract_episode(ctx, episode)
        assert [(m.surface, m.start, m.end) for m in salida_externa.mentions] == [
            (m.surface, m.start, m.end) for m in salida_local.mentions
        ]
        assert [c.best_predicate() for c in salida_externa.claims] == [
            c.best_predicate() for c in salida_local.claims
        ]
        # y la traza NO miente sobre quien lo produjo
        assert salida_externa.claims[0].provider_trace[0]["provider"] == "external"


# ==========================================================================
# 8. Pipelines documentados
# ==========================================================================
class TestPipelines:
    def test_el_gate_determinista_sigue_intacto(self):
        pasos = [e.info.step for e in ExtractionPipeline.local_default().extractors]
        assert SEMANTIC_STEP not in pasos

    def test_produccion_local_suma_el_semantico_sin_quitar_el_determinista(self):
        pasos = [
            e.info.step for e in ExtractionPipeline.production_local(MockProviderPort()).extractors
        ]
        assert "extract.deterministic" in pasos and SEMANTIC_STEP in pasos

    def test_produccion_externa_es_la_misma_cadena_con_otro_puerto(self):
        local = [e.info.step for e in ExtractionPipeline.production_local(MockProviderPort()).extractors]
        externa = [
            e.info.step for e in ExtractionPipeline.production_external(MockProviderPort()).extractors
        ]
        assert local == externa

    def test_la_union_conserva_el_origen_de_cada_propuesta(self):
        payload = {"mentions": BASE_MENTIONS, "claims": [claim()], "abstentions": []}
        ctx, _episode = context()
        out = ExtractionPipeline.production_local(port_returning(payload)).run(ctx)
        pasos = {m.produced_by_step for m in out.mentions}
        assert "extract.deterministic" in pasos and SEMANTIC_STEP in pasos
        # ids separados: no se funde nada
        assert len({m.mention_id for m in out.mentions}) == len(out.mentions)


# ==========================================================================
# 9. Rendimiento: se registra, no se maquilla
# ==========================================================================
class TestRendimiento:
    def test_se_registra_una_entrada_por_episodio_salga_bien_o_mal(self):
        ctx, episode = context()
        puerto = MockProviderPort(responses=[ProviderUnavailable("caido")])
        extractor = SemanticEpisodeExtractor(puerto)
        extractor.extract_episode(ctx, episode)
        rendimiento = extractor.performance()
        assert rendimiento["episodes"] == 1
        assert rendimiento["episodes_ok"] == 0
        assert rendimiento["valid_json_rate"] == 0.0

    def test_sin_ejecucion_no_se_inventan_cifras(self):
        assert SemanticEpisodeExtractor(MockProviderPort()).performance()["status"] == "not_evaluated"


# ==========================================================================
# 10. Mutaciones: si al romper la regla la suite sigue verde, no sostenia nada
# ==========================================================================
class TestMutaciones:
    def test_sin_filtro_de_ontologia_entraria_un_predicado_inventado(self, monkeypatch):
        ctx, episode = context()
        from knowledge_v3.extraction import payload as payload_mod

        payload = {
            "mentions": BASE_MENTIONS,
            "claims": [claim(predicate_candidates=[{"predicate": "INVENTADO", "confidence": 0.9}])],
            "abstentions": [],
        }
        salida = normalize_semantic_payload(
            payload,
            ctx=ctx,
            episode=episode,
            info=SemanticEpisodeExtractor(MockProviderPort()).info,
            ontology=compile_ontology(make_profile()),
        )
        assert [c for c in salida.claims if not c.abstained] == []

        class OntologiaSinPredicados:
            entity_types = ("Character", "Faction")
            predicate_names = ()

        # Sin ontologia que filtrar, el mismo payload SI colaria el predicado:
        # eso demuestra que el filtro es quien lo impide.
        colada = normalize_semantic_payload(
            payload,
            ctx=ctx,
            episode=episode,
            info=SemanticEpisodeExtractor(MockProviderPort()).info,
            ontology=OntologiaSinPredicados(),
        )
        assert [c.best_predicate() for c in colada.claims if not c.abstained] == ["INVENTADO"]

    def test_sin_verificacion_de_cita_entraria_una_mencion_inventada(self):
        ctx, episode = context()
        index = ctx.index_of(episode)
        assert anchor_in_episode(index, "Kaelthorn") is None
        # Y con la cita real, entra.
        assert anchor_in_episode(index, "Elara") is not None
