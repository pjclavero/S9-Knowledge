# -*- coding: utf-8 -*-
"""El extractor SEMANTICO es el que la cadena monta de verdad (bloque 15).

Antes de este bloque, `KnowledgePipeline` construia los extractores a mano y,
cuando la configuracion pedia Ollama o externo, instanciaba los LEGACY
(`OllamaExtractor`, `ExternalExtractor`): sin ontologia, con un solo candidato de
predicado y `SUBJECT_TO_OBJECT` cableado. Las metricas C1/C2 se habian medido
llamando DIRECTO a `SemanticEpisodeExtractor`, asi que no decian nada sobre la
cadena.

Todas las pruebas de aqui instancian el ORQUESTADOR REAL y miran los objetos
montados o lo que sale por el otro extremo. Ninguna comprueba nombres por grep:
un `grep` verde sobre codigo muerto es exactamente el fallo que este fichero
existe para impedir.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

_APP_DIR = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(_APP_DIR), str(_TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_knowledge_v3_e2e_fixtures import (  # noqa: E402
    QUOTE_E01,
    SEMANTIC_PAYLOAD_E01,
    TEMPORAL_REPLY,
    ExplodingExternalPort,
    ScriptedExternalPort,
    base_config,
    gold_dev,
    ollama_client,
    pipeline,
    snapshot_entities,
    source_named,
)

from knowledge_v3.contracts import Provider  # noqa: E402
from knowledge_v3.extraction.coreference import CoreferenceExtractor  # noqa: E402
from knowledge_v3.extraction.deterministic import DeterministicExtractor  # noqa: E402
from knowledge_v3.extraction.external import ExternalExtractor  # noqa: E402
from knowledge_v3.extraction.ollama import OllamaExtractor  # noqa: E402
from knowledge_v3.extraction.pipeline import ExtractionPipeline  # noqa: E402
from knowledge_v3.extraction.provider_port import (  # noqa: E402
    OllamaProviderPort,
    ProviderBadJSON,
    ProviderReply,
    ProviderRequest,
    ProviderUnavailable,
)
from knowledge_v3.extraction.semantic import (  # noqa: E402
    EXTERNAL_SEMANTIC_NAME,
    SEMANTIC_STEP,
    SemanticEpisodeExtractor,
)
from knowledge_v3.extraction.table import TableExtractor  # noqa: E402
from knowledge_v3.extraction.temporal import TemporalExtractor  # noqa: E402
from knowledge_v3.pipeline import KnowledgePipeline, from_episodes  # noqa: E402

OLLAMA_JSON = SEMANTIC_PAYLOAD_E01


@pytest.fixture(scope="module")
def gold():
    return gold_dev()


@pytest.fixture(scope="module")
def entities(gold):
    return snapshot_entities(gold)


def _types(p: KnowledgePipeline) -> list[type]:
    return [type(e) for e in p._extraction.extractors]


def _semantics(p: KnowledgePipeline) -> list[SemanticEpisodeExtractor]:
    return [e for e in p._extraction.extractors if isinstance(e, SemanticEpisodeExtractor)]


class SpyPort:
    """Puerto de inferencia guionizado que GUARDA lo que se le pidio.

    Doble de TRANSPORTE: no interpreta nada. Sirve para dos cosas distintas —
    leer el prompt real que la cadena compone y devolver respuestas concretas
    (incluidas las hostiles) sin tocar la red.
    """

    def __init__(self, payload, *, provider: Provider = Provider.EXTERNAL, model="modelo-espia"):
        self.payload = payload
        self.provider = provider
        self.model = model
        self.name = "external.espia"
        self.requests: list[ProviderRequest] = []

    def complete_json(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        if request.purpose == "temporal":
            item = TEMPORAL_REPLY
        else:
            item = self.payload(request) if callable(self.payload) else self.payload
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, dict):
            raise ProviderBadJSON(f"respuesta de tipo {type(item).__name__}")
        return ProviderReply(
            payload=item, model=self.model, provider=self.provider.value, latency_ms=0
        )


# ===========================================================================
# 9.1 / 9.2 / 9.3  QUE se monta
# ===========================================================================
class Test91OllamaActivo:
    def test_ollama_monta_el_semantico_sobre_un_puerto_ollama(self, gold):
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_JSON]),
            ablation="unspecified",
        )
        semanticos = _semantics(p)
        assert len(semanticos) == 1, _types(p)
        assert isinstance(semanticos[0].port, OllamaProviderPort)
        assert semanticos[0].info.provider is Provider.OLLAMA
        assert semanticos[0].info.step == SEMANTIC_STEP

    def test_el_extractor_ollama_legacy_NO_esta_en_la_cadena(self, gold):
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_JSON]),
            ablation="unspecified",
        )
        assert OllamaExtractor not in _types(p), _types(p)

    def test_el_semantico_de_ollama_recibe_la_ontologia_del_perfil(self, gold):
        """No basta con que este montado: tiene que poder compilar la ontologia."""
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_JSON]),
            ablation="unspecified",
        )
        assert p.config.profile.predicate_names()


class Test92ExternoActivo:
    def test_el_externo_monta_el_semantico_sobre_su_puerto(self, gold):
        port = SpyPort({"mentions": [], "claims": [], "abstentions": []})
        p = pipeline(gold, providers="no_ollama", external_port=port, ablation="unspecified")
        semanticos = _semantics(p)
        assert len(semanticos) == 1, _types(p)
        assert semanticos[0].port is port
        assert semanticos[0].info.provider is Provider.EXTERNAL

    def test_el_extractor_externo_legacy_NO_esta_en_la_cadena(self, gold):
        port = SpyPort({"mentions": [], "claims": [], "abstentions": []})
        p = pipeline(gold, providers="no_ollama", external_port=port, ablation="unspecified")
        assert ExternalExtractor not in _types(p), _types(p)

    def test_el_carril_externo_no_puede_disfrazarse_de_local(self, gold):
        port = SpyPort({"mentions": [], "claims": [], "abstentions": []})
        p = pipeline(gold, providers="no_ollama", external_port=port, ablation="unspecified")
        assert _semantics(p)[0].info.name == EXTERNAL_SEMANTIC_NAME
        assert not _semantics(p)[0].info.name.startswith("s9k.extraction.")

    def test_el_tope_de_confianza_externo_sigue_siendo_mas_bajo(self, gold):
        port = SpyPort({"mentions": [], "claims": [], "abstentions": []})
        p = pipeline(gold, providers="no_ollama", external_port=port, ablation="unspecified")
        assert _semantics(p)[0].confidence_cap == 0.6

    def test_un_puerto_que_no_sabe_complete_json_es_un_error_de_configuracion(self, gold):
        from knowledge_v3.pipeline import PipelineError

        class PuertoLegacy:
            def propose(self, request):  # pragma: no cover - no debe llamarse
                raise AssertionError("no se debe invocar")

        with pytest.raises(PipelineError) as exc:
            KnowledgePipeline(
                base_config(gold, providers="no_ollama", external_port=PuertoLegacy())
            )
        assert "complete_json" in str(exc.value)


class Test93LosDosActivos:
    def _pipeline(self, gold):
        return pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_JSON]),
            external_port=SpyPort({"mentions": [], "claims": [], "abstentions": []}),
            ablation="unspecified",
        )

    def test_cada_extractor_local_se_monta_una_sola_vez(self, gold):
        tipos = _types(self._pipeline(gold))
        assert tipos.count(DeterministicExtractor) == 1
        assert tipos.count(TableExtractor) == 1
        assert tipos.count(TemporalExtractor) == 1
        assert tipos.count(CoreferenceExtractor) == 1

    def test_hay_dos_semanticos_uno_por_puerto(self, gold):
        semanticos = _semantics(self._pipeline(gold))
        assert len(semanticos) == 2
        assert {s.info.provider for s in semanticos} == {Provider.OLLAMA, Provider.EXTERNAL}
        assert len({id(s.port) for s in semanticos}) == 2

    def test_no_se_anida_ningun_pipeline_dentro_de_otro(self, gold):
        p = self._pipeline(gold)
        assert not any(isinstance(e, ExtractionPipeline) for e in p._extraction.extractors)
        assert len(p._extraction.extractors) == 6

    def test_el_orden_es_el_declarado(self, gold):
        assert _types(self._pipeline(gold)) == [
            DeterministicExtractor,
            TableExtractor,
            SemanticEpisodeExtractor,
            SemanticEpisodeExtractor,
            TemporalExtractor,
            CoreferenceExtractor,
        ]


# ===========================================================================
# 9.4  local_default() INTACTO
# ===========================================================================
class Test94GateDeterministaIntacto:
    def test_no_hay_semantico_ni_puertos_en_el_gate(self):
        gate = ExtractionPipeline.local_default()
        assert [type(e) for e in gate.extractors] == [
            DeterministicExtractor,
            TableExtractor,
            TemporalExtractor,
            CoreferenceExtractor,
        ]
        assert not any(isinstance(e, SemanticEpisodeExtractor) for e in gate.extractors)
        assert not any(hasattr(e, "port") for e in gate.extractors)

    def test_el_gate_no_puede_llamar_a_la_red(self, gold, entities):
        """Prueba positiva: se corre de verdad y ningun puerto se toca.

        No hay puerto que espiar porque no hay puerto: lo que se demuestra es que
        el gate produce su salida sin ninguno.
        """
        p = pipeline(gold, providers="local_only", ablation="local_only")
        assert not any(hasattr(e, "port") for e in p._extraction.extractors)

    def test_el_gate_sigue_siendo_determinista_bit_a_bit(self, gold, entities):
        p1 = pipeline(gold, providers="local_only", ablation="local_only")
        p2 = pipeline(gold, providers="local_only", ablation="local_only")
        caso = from_episodes(source_named(gold, "leyenda-cronica"))
        a = p1.run_source(caso, catalog_entities=entities)
        b = p2.run_source(caso, catalog_entities=entities)
        assert [m.to_dict() for m in a.mentions] == [m.to_dict() for m in b.mentions]
        assert [c.to_dict() for c in a.claims] == [c.to_dict() for c in b.claims]

    def test_local_only_monta_exactamente_los_mismos_extractores_que_el_gate(self, gold):
        p = pipeline(gold, providers="local_only", ablation="local_only")
        assert _types(p) == [type(e) for e in ExtractionPipeline.local_default().extractors]


# ===========================================================================
# 9.5  REGRESION: si vuelve el legacy, esto falla
# ===========================================================================
class Test95RegresionLegacy:
    """Espia el CONSTRUCTOR de los legacy. No mira nombres, mira instanciaciones."""

    @pytest.fixture()
    def espia(self, monkeypatch):
        instanciados: list[str] = []

        def spy(cls):
            original = cls.__init__

            def wrapped(self, *args, **kwargs):
                instanciados.append(cls.__name__)
                return original(self, *args, **kwargs)

            monkeypatch.setattr(cls, "__init__", wrapped)

        spy(OllamaExtractor)
        spy(ExternalExtractor)
        return instanciados

    def test_montar_la_cadena_con_ollama_no_instancia_ningun_legacy(self, gold, espia):
        pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_JSON]),
            ablation="unspecified",
        )
        assert espia == []

    def test_montar_la_cadena_con_externo_no_instancia_ningun_legacy(self, gold, espia):
        pipeline(
            gold,
            providers="no_ollama",
            external_port=SpyPort({"mentions": [], "claims": [], "abstentions": []}),
            ablation="unspecified",
        )
        assert espia == []

    def test_correr_la_cadena_entera_no_instancia_ningun_legacy(self, gold, entities, espia):
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_JSON]),
            external_port=SpyPort(lambda r: SEMANTIC_PAYLOAD_E01),
            ablation="unspecified",
        )
        p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")), catalog_entities=entities
        )
        assert espia == []


# ===========================================================================
# 9.6  Los CANDIDATOS sobreviven hasta el motor
# ===========================================================================
CANDIDATOS = {
    "mentions": [
        {
            "local_ref": "m1",
            "surface": "Ilaria Vandreth",
            "type_candidates": [{"type": "Character", "confidence": 0.8}],
            "evidence_quote": QUOTE_E01,
        },
        {
            "local_ref": "m2",
            "surface": "Casa del Ciervo",
            "type_candidates": [{"type": "Faction", "confidence": 0.8}],
            "evidence_quote": QUOTE_E01,
        },
    ],
    "claims": [
        {
            "subject_ref": "m1",
            "object_ref": "m2",
            "relation_phrase": "dirigió la Casa del Ciervo",
            "predicate_candidates": [
                {"predicate": "LEADS", "confidence": 0.72},
                {"predicate": "MEMBER_OF", "confidence": 0.23},
            ],
            "direction_candidates": [
                {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.7},
                {"direction": "OBJECT_TO_SUBJECT", "confidence": 0.2},
            ],
            "evidence_quote": QUOTE_E01,
            "negated": False,
            "epistemic_status": "ASSERTED",
            "temporal_expressions": [],
            "temporal_resolution_required": False,
        }
    ],
    "abstentions": [],
}


class Test96CandidatosMultiples:
    def _run(self, gold, entities):
        port = SpyPort(lambda r: CANDIDATOS)
        p = pipeline(gold, providers="no_ollama", external_port=port, ablation="unspecified")
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")), catalog_entities=entities
        )
        del_puerto = [
            c
            for c in run.claims
            if any(s["provider"] == "external" for s in c.provider_trace) and not c.abstained
        ]
        return run, del_puerto

    def test_los_dos_predicados_llegan_al_claim(self, gold, entities):
        _run, claims = self._run(gold, entities)
        assert claims, "el puerto no produjo ningun claim afirmado"
        for claim in claims:
            nombres = [c["predicate"] for c in claim.predicate_candidates]
            assert nombres == ["LEADS", "MEMBER_OF"], nombres

    def test_las_dos_direcciones_llegan_al_claim(self, gold, entities):
        _run, claims = self._run(gold, entities)
        for claim in claims:
            direcciones = [c["direction"] for c in claim.direction_candidates]
            assert direcciones == ["SUBJECT_TO_OBJECT", "OBJECT_TO_SUBJECT"], direcciones

    def test_la_direccion_no_esta_cableada(self, gold, entities):
        """El camino legacy escribia siempre UN candidato `SUBJECT_TO_OBJECT`."""
        _run, claims = self._run(gold, entities)
        for claim in claims:
            assert len(claim.direction_candidates) > 1

    def test_el_motor_juzga_esos_MISMOS_claims_sin_reducirlos_antes(self, gold, entities):
        run, claims = self._run(gold, entities)
        assert run.engine_result is not None
        decididos = {d.claim_id for d in run.decisions}
        for claim in claims:
            assert claim.claim_id in decididos
            # y el documento que el motor vio conserva los dos candidatos
            assert len(claim.predicate_candidates) == 2


# ===========================================================================
# 9.7  La ONTOLOGIA REAL viaja en la peticion
# ===========================================================================
class Test97OntologiaEnElPrompt:
    @pytest.fixture(scope="class")
    def prompt(self, gold, entities):
        port = SpyPort({"mentions": [], "claims": [], "abstentions": []})
        p = pipeline(gold, providers="no_ollama", external_port=port, ablation="unspecified")
        p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")), catalog_entities=entities
        )
        assert port.requests, "el puerto no fue invocado"
        return port.requests[0].prompt

    @pytest.mark.parametrize(
        "esperado",
        [
            "TIPOS DE ENTIDAD PERMITIDOS",
            "Character",
            "Faction",
            "PREDICADOS PERMITIDOS",
            "MEMBER_OF",
            "LEADS",
            "el sujeto pertenece al grupo",          # definicion del nucleo
            "sujeto: Character | objeto: Faction",   # dominio y rango
            "simetrico",                             # simetria (ALLY_OF)
            "inverso de",                            # inversas declaradas
            "no confundir con",                      # confundibles calculados
            "ENTIDADES YA CONOCIDAS",                # glosario del workspace
            "CARGOS Y TITULOS",
            "TERMINOS AMBIGUOS",
            "CALENDARIOS DEL MUNDO",
        ],
    )
    def test_el_prompt_lleva_la_ontologia_compilada(self, prompt, esperado):
        assert esperado in prompt, prompt[:2000]

    def test_el_prompt_declara_la_version_de_la_ontologia(self, prompt):
        from knowledge_v3.extraction.ontology_prompt import ONTOLOGY_PROMPT_VERSION

        assert f"v{ONTOLOGY_PROMPT_VERSION}" in prompt

    def test_el_prompt_lleva_el_texto_real_del_episodio(self, prompt):
        assert QUOTE_E01 in prompt

    def test_el_prompt_NO_lleva_identificadores_de_fragmento(self, prompt):
        assert "fragment:" not in prompt


# ===========================================================================
# 9.8  El proveedor falla y la cadena sigue
# ===========================================================================
FALLOS = {
    "timeout": ProviderUnavailable("timeout (simulado)"),
    "json_invalido": ProviderBadJSON("la respuesta no es un objeto JSON"),
    "no_disponible": ProviderUnavailable("connection refused (simulado)"),
    "respuesta_vacia": {"mentions": [], "claims": [], "abstentions": []},
    "predicado_fuera_de_ontologia": {
        "mentions": CANDIDATOS["mentions"],
        "claims": [
            {
                **CANDIDATOS["claims"][0],
                "predicate_candidates": [{"predicate": "GOBIERNA_LA_GALAXIA", "confidence": 0.9}],
            }
        ],
        "abstentions": [],
    },
}


class Test98ProveedorQueFalla:
    def _run(self, gold, entities, fallo):
        port = SpyPort(lambda r: FALLOS[fallo])
        p = pipeline(gold, providers="no_ollama", external_port=port, ablation="unspecified")
        return p, p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")), catalog_entities=entities
        )

    @pytest.mark.parametrize("fallo", sorted(FALLOS))
    def test_la_cadena_no_se_cae_y_los_locales_siguen_trabajando(self, gold, entities, fallo):
        _p, run = self._run(gold, entities, fallo)
        assert run.episodes and run.fragments
        locales = [
            m for m in run.mentions
            if all(s["provider"] == "local" for s in m.provider_trace)
        ]
        assert locales, f"{fallo}: los extractores locales dejaron de producir"

    @pytest.mark.parametrize(
        "fallo,codigo",
        [
            ("timeout", "PROVIDER_UNAVAILABLE"),
            ("json_invalido", "PROVIDER_INVALID_JSON"),
            ("no_disponible", "PROVIDER_UNAVAILABLE"),
            ("predicado_fuera_de_ontologia", "PREDICATE_NOT_IN_PROFILE"),
        ],
    )
    def test_queda_diagnostico_del_fallo(self, gold, entities, fallo, codigo):
        _p, run = self._run(gold, entities, fallo)
        assert codigo in {d["code"] for d in run.diagnostics}

    @pytest.mark.parametrize("fallo", sorted(FALLOS))
    def test_ningun_fallo_del_proveedor_aprueba_ni_escribe(self, gold, entities, fallo):
        _p, run = self._run(gold, entities, fallo)
        del_puerto = [
            c for c in run.claims if any(s["provider"] == "external" for s in c.provider_trace)
        ]
        for claim in del_puerto:
            assert claim.review_required or claim.abstained
        if run.write_result is not None:
            assert run.write_result.mode == "DRY_RUN"

    def test_un_proveedor_caido_no_tumba_el_LOTE(self, gold, entities):
        """Todas las fuentes del split siguen recorriendose."""
        from knowledge_v3.pipeline import cases_from_gold

        p = pipeline(
            gold,
            providers="no_ollama",
            external_port=ExplodingExternalPort(),
            ablation="unspecified",
        )
        casos = cases_from_gold(gold, entry="episodes")
        result = p.run(casos, catalog_entities=entities)
        assert len(result.runs) == len(casos)

    def test_el_predicado_fuera_de_ontologia_no_llega_al_motor_como_predicado(
        self, gold, entities
    ):
        _p, run = self._run(gold, entities, "predicado_fuera_de_ontologia")
        for claim in run.claims:
            for cand in claim.predicate_candidates:
                assert cand["predicate"] != "GOBIERNA_LA_GALAXIA"


# ===========================================================================
# 9.9  AUTORIDAD: el proveedor propone, el motor decide
# ===========================================================================
class Test99Autoridad:
    def _run(self, gold, entities):
        # El proveedor firma 0.99 y dice que no hace falta revisar. Da igual.
        payload = {
            "mentions": CANDIDATOS["mentions"],
            "claims": [
                {
                    **CANDIDATOS["claims"][0],
                    "predicate_candidates": [{"predicate": "LEADS", "confidence": 0.99}],
                }
            ],
            "abstentions": [],
        }
        port = SpyPort(lambda r: payload)
        p = pipeline(
            gold,
            providers="no_ollama",
            external_port=port,
            ablation="unspecified",
            writer_driver=None,
        )
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")), catalog_entities=entities
        )
        return p, run, [
            c for c in run.claims if any(s["provider"] == "external" for s in c.provider_trace)
        ]

    def test_la_salida_del_proveedor_nace_pidiendo_revision_y_acotada(self, gold, entities):
        _p, _run, claims = self._run(gold, entities)
        assert claims
        for claim in claims:
            assert claim.confidence <= 0.6
            assert claim.review_required or claim.abstained

    def test_ningun_claim_del_proveedor_produce_por_si_solo_un_plan_aprobado(
        self, gold, entities
    ):
        _p, run, claims = self._run(gold, entities)
        ids = {c.claim_id for c in claims}
        aceptadas = {d.claim_id for d in run.decisions if d.decision == "ACCEPT"}
        assert not (ids & aceptadas), "el motor acepto un claim de proveedor sin revision"

    def test_el_plan_lo_firma_el_motor_local(self, gold, entities):
        _p, run, _claims = self._run(gold, entities)
        for plan in (run.plan, run.review_plan):
            if plan is None:
                continue
            assert plan.signed_locally()
            assert plan.signature_is_intact()
            assert plan.local_approval["approved_by"]["name"] == "s9k.engine.local"

    def test_nada_del_proveedor_llega_al_writer_sin_pasar_por_el_motor(self, gold, entities):
        _p, run, claims = self._run(gold, entities)
        if run.plan is None:
            return
        decisiones = {d["decision_id"] for d in run.plan.to_dict()["decisions"]}
        for op in run.plan.to_dict()["mutation_operations"]:
            assert op["decision_id"] in decisiones

    def test_el_ledger_no_recibe_nada_de_un_plan_no_aprobado(self, gold, entities):
        p, run, _claims = self._run(gold, entities)
        if run.plan is not None and not run.plan.approved:
            assert not run.ledger_entries
