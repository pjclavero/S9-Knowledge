# -*- coding: utf-8 -*-
"""Las DIEZ pruebas conjuntas del §8 del prompt maestro, sobre el dataset dev.

    1. normalizador + extractor
    2. extractor + motor
    3. motor + ledger
    4. cadena completa
    5. cadena completa CON externo
    6. cadena completa SIN externo
    7. cadena completa SIN Ollama
    8. proveedor corrupto
    9. workspace incorrecto
   10. plan no firmado

Todas sobre material REAL del split `dev`. Ninguna fabrica documentos para si
misma: si una prueba conjunta pasara con material hecho a su medida, no diria
nada sobre la cadena.

Ninguna abre una conexion: Ollama y el externo entran por su gancho de
TRANSPORTE y el writer va en dry-run. Donde hay que demostrar que no se toca el
grafo, se le pasa un driver que estalla.
"""
from __future__ import annotations

import dataclasses
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
    HOSTILE_EXTERNAL_PAYLOADS,
    NOW,
    OLLAMA_HOSTILE,
    OLLAMA_PAYLOAD_E01,
    OTHER_WORKSPACE,
    WORKSPACE,
    ExplodingDriver,
    ExplodingExternalPort,
    ScriptedExternalPort,
    base_config,
    external_payload_for,
    gold_dev,
    ollama_client,
    pipeline,
    snapshot_entities,
    source_named,
)

from knowledge_v3.contracts.base import V3ContractError, seal_plan  # noqa: E402
from knowledge_v3.contracts.game_profile import GameProfile  # noqa: E402
from knowledge_v3.contracts.mutation_plan import GraphMutationPlan  # noqa: E402
from knowledge_v3.engine.errors import EngineInputError  # noqa: E402
from knowledge_v3.extraction.base import ExtractionError  # noqa: E402
from knowledge_v3.pipeline import (  # noqa: E402
    KnowledgePipeline,
    PipelineError,
    cases_from_gold,
    from_episodes,
    from_raw,
    profile_of,
)
from knowledge_v3.resolution.provisional import normalize_surface  # noqa: E402
from knowledge_v3.writer.admission import AdmissionContext, admit  # noqa: E402


@pytest.fixture(scope="module")
def gold():
    return gold_dev()


@pytest.fixture(scope="module")
def entities(gold):
    return snapshot_entities(gold)


def _run_all(gold, entities, **overrides):
    p = pipeline(gold, **overrides)
    return p, p.run(cases_from_gold(gold, entry="episodes"), catalog_entities=entities)


# ===========================================================================
# 1. NORMALIZADOR + EXTRACTOR
# ===========================================================================
class TestConjunta01NormalizadorExtractor:
    """La salida del normalizador entra en el extractor SIN retoques.

    Esta es la unica prueba que arranca de bytes. Lo que comprueba no es que
    coincida con unos identificadores gold —no puede, ver 11-e2e.md §5— sino
    que el extractor se sostiene sobre lo que el normalizador produce de
    verdad: offsets validos, anclaje intacto y menciones dentro de fragmentos.
    """

    @pytest.mark.parametrize(
        "source_id", ["leyenda-cronica", "mareas-cuaderno", "kestrel-informe"]
    )
    def test_el_extractor_ancla_en_los_fragmentos_del_normalizador(
        self, gold, entities, source_id
    ):
        p = pipeline(gold)
        run = p.run_source(
            from_raw(source_named(gold, source_id)), catalog_entities=entities
        )
        assert run.episodes, "el normalizador no produjo episodios"
        assert run.fragments, "el normalizador no produjo evidencias"

        by_id = {e.episode_id: e for e in run.episodes}
        frag_by_id = {f.fragment_id: f for f in run.fragments}
        assert run.mentions, "el extractor no encontro nada en la salida real"

        for mention in run.mentions:
            episode = by_id[mention.episode_id]
            texto = episode.text or ""
            assert 0 <= mention.start < mention.end <= len(texto), (
                "la mencion apunta fuera del texto del normalizador"
            )
            assert normalize_surface(texto[mention.start : mention.end]) == (
                normalize_surface(mention.surface)
            ), "el tramo del documento y la superficie no son la misma cosa"
            assert mention.evidence_fragment_ids, "mencion sin evidencia"
            for fid in mention.evidence_fragment_ids:
                assert fid in frag_by_id, "mencion anclada a una evidencia inexistente"
                fragmento = frag_by_id[fid]
                assert fragmento.start <= mention.start and mention.end <= fragmento.end, (
                    "la mencion no cae dentro del fragmento que la sostiene"
                )

    def test_defecto_D8_la_superficie_no_es_el_texto_del_documento(self, gold, entities):
        """REGRESION DOCUMENTADA, no deseada (11-e2e.md, defecto D-8).

        `EntityMention.surface` sale del lexico, no del documento:
        `lexicon.py:164` copia la forma ALMACENADA en la entrada y
        `deterministic.py:215` la propaga tal cual, mientras `start`/`end`
        vienen de los tokens reales. Con diacriticos, `texto[start:end]` y
        `surface` dejan de coincidir: el documento dice "Cofradía de Ámbar" y
        la mencion dice "Cofradia de Ambar".

        No se parchea aqui —no es nuestro subsistema— pero si se deja probado,
        para que la afirmacion de la documentacion tenga respaldo y para que el
        dia que se arregle esta prueba avise.
        """
        p = pipeline(gold)
        run = p.run_source(
            from_raw(source_named(gold, "mareas-cuaderno")), catalog_entities=entities
        )
        by_id = {e.episode_id: e for e in run.episodes}
        discrepantes = [
            m
            for m in run.mentions
            if (by_id[m.episode_id].text or "")[m.start : m.end] != m.surface
        ]
        assert discrepantes, (
            "el defecto D-8 ya no se reproduce: actualizar docs/v3/11-e2e.md"
        )

    def test_el_anclaje_del_normalizador_se_sostiene(self, gold, entities):
        p = pipeline(gold)
        run = p.run_source(
            from_raw(source_named(gold, "leyenda-cronica")), catalog_entities=entities
        )
        by_id = {e.episode_id: e for e in run.episodes}
        for fragment in run.fragments:
            texto = by_id[fragment.episode_id].text or ""
            assert texto[fragment.start : fragment.end] == fragment.literal_text

    def test_la_tabla_y_el_audio_tambien_recorren_normalizador_y_extractor(
        self, gold, entities
    ):
        for source_id in ("kestrel-tripulacion", "mareas-sesion"):
            p = pipeline(gold)
            run = p.run_source(
                from_raw(source_named(gold, source_id)), catalog_entities=entities
            )
            assert run.episodes, f"{source_id}: sin episodios"
            assert run.normalization_report.get("adapter"), (
                f"{source_id}: el informe no dice que adaptador corrio"
            )

    def test_la_traza_de_proveedor_del_normalizador_llega_a_la_mencion(
        self, gold, entities
    ):
        """La procedencia no se pierde entre subsistemas: se acumula."""
        p = pipeline(gold)
        run = p.run_source(
            from_raw(source_named(gold, "leyenda-cronica")), catalog_entities=entities
        )
        for mention in run.mentions:
            pasos = {s["step"] for s in mention.provider_trace}
            assert pasos, "mencion sin traza de proveedor"
            assert all(s["provider"] == "local" for s in mention.provider_trace), (
                "una corrida local no puede declarar pasos de proveedor externo"
            )


# ===========================================================================
# 2. EXTRACTOR + MOTOR
# ===========================================================================
class TestConjunta02ExtractorMotor:
    """Lo que el extractor propone es exactamente lo que el motor juzga."""

    def test_el_motor_decide_sobre_todos_los_claims_del_extractor(self, gold, entities):
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_PAYLOAD_E01]),
            ablation="unspecified",
        )
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        assert run.claims, "sin claims no hay nada que probar aqui"
        assert len(run.decisions) == len(run.claims)
        assert {d.claim_id for d in run.decisions} == {c.claim_id for c in run.claims}

    def test_el_motor_no_inventa_predicados_fuera_del_perfil(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        permitidos = set(profile_of(gold, "generic").predicate_names())
        for decision in result.decisions:
            if decision.predicate is not None:
                assert decision.predicate in permitidos

    def test_la_autoridad_es_del_motor_no_del_extractor(self, gold, entities):
        """Un claim con confianza 0.99 propuesto por Ollama NO se aprueba solo.

        El tope de confianza del extractor Ollama es 0.7 y sus claims viajan con
        `review_required`. Que el motor pueda aprobar algo asi seria la mayor
        de las regresiones posibles.
        """
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_PAYLOAD_E01]),
            ablation="unspecified",
        )
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        de_ollama = [
            c
            for c in run.claims
            if any(s["provider"] == "ollama" for s in c.provider_trace)
        ]
        assert de_ollama, "el doble de Ollama no llego a producir ningun claim"
        for claim in de_ollama:
            assert claim.confidence <= 0.7
            assert claim.review_required

    def test_los_casos_negativos_del_split_no_se_convierten_en_decisiones_ACCEPT(
        self, gold, entities
    ):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        prohibidos = {
            n["episode_id"]: n for n in gold.negatives
        }
        episodios_aceptados = {
            d.episode_id for d in result.decisions if d.decision == "ACCEPT"
        }
        for episode_id, negativo in prohibidos.items():
            if episode_id not in episodios_aceptados:
                continue
            # Si se acepta algo en un episodio con trampa, el predicado
            # aceptado no puede ser uno de los prohibidos.
            for decision in result.decisions:
                if decision.episode_id == episode_id and decision.decision == "ACCEPT":
                    assert decision.predicate not in set(
                        negativo.get("forbidden_predicates") or ()
                    )


# ===========================================================================
# 3. MOTOR + LEDGER
# ===========================================================================
class TestConjunta03MotorLedger:
    """Al ledger llega lo aprobado, y el ledger alimenta al motor de vuelta."""

    def test_solo_lo_aprobado_entra_en_el_ledger(self, gold, entities):
        p, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        registradas = {e.assertion_id for e in p.ledger.entries()}
        aprobadas = {
            a.assertion_id
            for run in result.runs
            if run.plan is not None and run.plan.approved
            for a in run.assertions
        }
        assert registradas <= aprobadas, (
            "el ledger guardo algo que ningun plan aprobado contenia"
        )
        assert registradas, "ningun hecho llego al ledger: no hay nada que probar"

    def test_el_plan_no_aprobado_no_deja_rastro_en_el_ledger(self, gold, entities):
        """Sin claims aprobables, el ledger se queda vacio y lo dice."""
        p = pipeline(gold)  # local_only: el determinista no propone nada en dev
        result = p.run(cases_from_gold(gold, entry="episodes"), catalog_entities=entities)
        assert len(p.ledger) == 0
        codigos = {d["code"] for run in result.runs for d in run.diagnostics}
        assert "PIPELINE_STOPPED" in codigos or "LEDGER_SKIPPED_PLAN_NOT_APPROVED" in codigos

    def test_el_snapshot_del_ledger_alimenta_al_motor(self, gold, entities):
        """El `snapshot_id` del plan es el del ledger, no uno inventado."""
        p, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        assert result.plans, "sin planes no hay ancla que comprobar"
        for plan in result.plans:
            assert plan.snapshot_id.startswith("snapshot:"), plan.snapshot_id

    def test_el_ledger_avanza_entre_fuentes(self, gold, entities):
        """Lo que aprueba la fuente n esta en el grafo que ve la fuente n+1."""
        p, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        anclas = [r.plan.snapshot_id for r in result.runs if r.plan is not None]
        assert len(set(anclas)) > 1, (
            "todas las fuentes vieron el mismo snapshot: el ledger no avanzo"
        )

    def test_la_cadena_de_hashes_del_ledger_es_verificable(self, gold, entities):
        p, _ = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        assert p.ledger.verify_chain(validate_documents=True)


# ===========================================================================
# 4. CADENA COMPLETA
# ===========================================================================
class TestConjunta04CadenaCompleta:
    """De la fuente al writer, sin saltarse una etapa."""

    def test_la_cadena_llega_al_writer_en_dry_run(self, gold, entities):
        p, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
            writer_driver=None,
        )
        con_plan = [r for r in result.runs if r.plan is not None]
        assert con_plan, "ninguna fuente produjo plan"
        for run in con_plan:
            assert run.write_result is not None
            assert run.write_result.mode == "DRY_RUN"

    def test_el_dry_run_no_toca_el_driver(self, gold, entities):
        """Se le pasa un driver que estalla. Si el dry-run lo abre, revienta."""
        config = dataclasses.replace(
            base_config(
                gold,
                entity_source="gold",
                claim_source="gold",
                ablation="unspecified",
            ),
            writer_driver=ExplodingDriver(),
        )
        p = KnowledgePipeline(config)
        result = p.run(cases_from_gold(gold, entry="episodes"), catalog_entities=entities)
        assert any(r.write_result is not None for r in result.runs)

    def test_un_plan_aprobado_se_simula_sin_rechazo(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        aprobados = [
            r for r in result.runs if r.plan is not None and r.plan.approved
        ]
        assert aprobados, "ningun plan se aprobo: la cadena no llega al final"
        for run in aprobados:
            assert run.write_result.outcome == "SIMULATED", run.write_result.codes

    def test_la_procedencia_llega_entera_hasta_la_afirmacion(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        assert result.assertions
        for assertion in result.assertions:
            assert assertion.evidence_fragment_ids, "afirmacion sin evidencia"
            assert assertion.episode_ids, "afirmacion sin episodio"
            assert assertion.provider_trace, "afirmacion sin traza"
            assert assertion.workspace == WORKSPACE

    def test_la_cadena_es_determinista(self, gold, entities):
        """Dos corridas identicas producen los mismos planes, byte a byte."""
        _, primera = _run_all(
            gold, entities, entity_source="gold", claim_source="gold", ablation="unspecified"
        )
        _, segunda = _run_all(
            gold, entities, entity_source="gold", claim_source="gold", ablation="unspecified"
        )
        assert [p.to_dict() for p in primera.plans] == [
            p.to_dict() for p in segunda.plans
        ]


# ===========================================================================
# 5. CADENA COMPLETA CON EXTERNO
# ===========================================================================
class TestConjunta05ConExterno:
    """El externo propone; no aprueba, no escribe y no puede parecer local."""

    def _con_externo(self, gold):
        port = ScriptedExternalPort(external_payload_for(gold, "leyenda-cronica"))
        return port, pipeline(
            gold,
            providers="local_plus_external",
            external_port=port,
            ablation="local_plus_external",
        )

    def test_el_externo_llega_a_proponer_y_la_cadena_lo_recoge(self, gold, entities):
        port, p = self._con_externo(gold)
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        assert port.requests, "el externo no fue invocado"
        externos = [
            c for c in run.claims
            if any(s["provider"] == "external" for s in c.provider_trace)
        ]
        assert externos, "ningun claim externo sobrevivio al filtro"

    def test_la_traza_externa_viaja_hasta_el_claim(self, gold, entities):
        _, p = self._con_externo(gold)
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        pasos = [
            s
            for c in run.claims
            for s in c.provider_trace
            if s["provider"] == "external"
        ]
        assert pasos
        for paso in pasos:
            assert not paso["name"].startswith("s9k.extraction."), (
                "un paso externo no puede usar el prefijo reservado de lo local"
            )

    def test_el_externo_no_puede_aprobar(self, gold, entities):
        """Aunque proponga con confianza 0.9, el tope externo es 0.6."""
        _, p = self._con_externo(gold)
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        externos = [
            c for c in run.claims
            if any(s["provider"] == "external" for s in c.provider_trace)
        ]
        for claim in externos:
            assert claim.confidence <= 0.6
        if run.plan is not None:
            assert run.plan.local_approval["approved_by"]["provider"] == "local"

    def test_el_plan_lo_firma_siempre_el_motor_local(self, gold, entities):
        """Con el externo participando, TODOS los planes siguen siendo locales.

        Se recorre el split entero en vez de una sola fuente: asi la prueba no
        depende de que una fuente concreta llegue a producir plan, y un salto
        silencioso deja de ser un resultado aceptable.
        """
        port = ScriptedExternalPort(external_payload_for(gold, "leyenda-cronica"))
        p = pipeline(
            gold,
            providers="local_plus_external",
            external_port=port,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        result = p.run(cases_from_gold(gold, entry="episodes"), catalog_entities=entities)
        assert port.requests, "el externo no fue invocado en ninguna fuente"
        assert result.plans, "ninguna fuente produjo plan"
        for plan in result.plans:
            assert plan.signed_locally()
            assert plan.signature_is_intact()
            assert plan.local_approval["approved_by"]["name"] == "s9k.engine.local"


# ===========================================================================
# 6. CADENA COMPLETA SIN EXTERNO
# ===========================================================================
class TestConjunta06SinExterno:
    """Sin proveedor externo la cadena funciona y NO declara pasos externos."""

    def test_sin_externo_no_hay_ni_un_paso_externo_en_la_traza(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        for doc in (*result.mentions, *result.assertions):
            proveedores = {s["provider"] for s in doc.provider_trace}
            assert "external" not in proveedores

    def test_el_puerto_externo_no_enlazado_se_anota_y_no_tumba_la_cadena(
        self, gold, entities
    ):
        """`providers=no_ollama` sin puerto: la cadena sigue y lo declara."""
        config = base_config(gold, providers="no_ollama", ablation="no_ollama")
        assert config.wants_external is False
        assert config.declared()["external_active"] is False
        p = KnowledgePipeline(config)
        result = p.run(cases_from_gold(gold, entry="episodes"), catalog_entities=entities)
        assert result.runs

    def test_la_cadena_sin_externo_sigue_produciendo_planes(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        assert result.plans


# ===========================================================================
# 7. CADENA COMPLETA SIN OLLAMA
# ===========================================================================
class TestConjunta07SinOllama:
    """Sin Ollama la cadena entera sigue siendo una cadena."""

    def test_sin_ollama_no_hay_ni_un_paso_ollama_en_la_traza(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        for doc in (*result.mentions, *result.claims, *result.assertions):
            proveedores = {s["provider"] for s in doc.provider_trace}
            assert "ollama" not in proveedores

    def test_la_ablacion_no_ollama_apaga_ollama_aunque_haya_cliente(self, gold):
        """El cliente esta enlazado y aun asi no participa: manda la ablacion."""
        config = base_config(
            gold, ollama_client=ollama_client([OLLAMA_PAYLOAD_E01])
        ).for_ablation("no_ollama")
        assert config.ollama_client is not None
        assert config.wants_ollama is False
        assert config.declared()["ollama_active"] is False

    def test_la_cadena_sin_ollama_aprueba_y_escribe_igual(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        aprobados = [r for r in result.runs if r.plan is not None and r.plan.approved]
        assert aprobados
        assert all(r.write_result.outcome == "SIMULATED" for r in aprobados)

    def test_una_configuracion_sin_ningun_extractor_falla_en_voz_alta(self, gold):
        """`external_only` sin puerto no deja extractor: no es un modo degradado."""
        with pytest.raises(PipelineError) as exc:
            KnowledgePipeline(base_config(gold, providers="external_only"))
        assert "extractor" in str(exc.value)


# ===========================================================================
# 8. PROVEEDOR CORRUPTO
# ===========================================================================
class TestConjunta08ProveedorCorrupto:
    """La cadena sobrevive a un proveedor hostil y NO se contamina."""

    def test_ollama_con_json_invalido_no_tumba_la_cadena(self, gold, entities):
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_HOSTILE]),
            ablation="unspecified",
        )
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        codigos = {d["code"] for d in run.diagnostics}
        # `PROVIDER_INVALID_JSON` es el codigo del puerto agnostico; el antiguo
        # `OLLAMA_INVALID_JSON` era del extractor legacy, que ya no se monta.
        assert {
            "PROVIDER_INVALID_JSON",
            "OLLAMA_INVALID_JSON",
            "MODEL_PAYLOAD_MALFORMED",
        } & codigos, codigos

    def test_la_respuesta_hostil_no_produce_ni_una_mencion(self, gold, entities):
        p = pipeline(
            gold,
            providers="local_plus_external",
            ollama_client=ollama_client([OLLAMA_HOSTILE]),
            ablation="unspecified",
        )
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        de_ollama = [
            m for m in run.mentions
            if any(s["provider"] == "ollama" for s in m.provider_trace)
        ]
        assert de_ollama == []

    @pytest.mark.parametrize("payload", HOSTILE_EXTERNAL_PAYLOADS)
    def test_el_externo_hostil_no_contamina_la_cadena(self, gold, entities, payload):
        port = ScriptedExternalPort(payload)
        p = pipeline(
            gold,
            providers="local_plus_external",
            external_port=port,
            ablation="unspecified",
        )
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        for doc in (*run.mentions, *run.claims):
            assert doc.workspace == WORKSPACE
            for step in doc.provider_trace:
                assert not step["name"].startswith("s9k.extraction.") or (
                    step["provider"] == "local"
                )
        if run.plan is not None:
            assert run.plan.local_approval["approved_by"]["provider"] == "local"
            assert run.plan.signature_is_intact()

    def test_el_externo_caido_se_anota_y_la_cadena_sigue(self, gold, entities):
        p = pipeline(
            gold,
            providers="local_plus_external",
            external_port=ExplodingExternalPort(),
            ablation="unspecified",
        )
        run = p.run_source(
            from_episodes(source_named(gold, "leyenda-cronica")),
            catalog_entities=entities,
        )
        codigos = {d["code"] for d in run.diagnostics}
        # Mismo hecho, codigo del puerto agnostico: el externo se cayo, se anota
        # y la cadena sigue. `EXTERNAL_PROVIDER_FAILED` era del legacy.
        assert "PROVIDER_UNAVAILABLE" in codigos, codigos

    def test_un_proveedor_corrupto_nunca_produce_un_plan_aprobado_de_mas(
        self, gold, entities
    ):
        """Comparado con la corrida limpia, el hostil no aprueba NADA nuevo."""
        limpio = pipeline(gold, ablation="local_only")
        r_limpio = limpio.run(
            cases_from_gold(gold, entry="episodes"), catalog_entities=entities
        )
        sucio = pipeline(
            gold,
            providers="local_plus_external",
            external_port=ScriptedExternalPort(HOSTILE_EXTERNAL_PAYLOADS[1]),
            ablation="unspecified",
        )
        r_sucio = sucio.run(
            cases_from_gold(gold, entry="episodes"), catalog_entities=entities
        )
        aprobados_limpio = sum(1 for p in r_limpio.plans if p.approved)
        aprobados_sucio = sum(1 for p in r_sucio.plans if p.approved)
        assert aprobados_sucio <= aprobados_limpio


# ===========================================================================
# 9. WORKSPACE INCORRECTO
# ===========================================================================
class TestConjunta09WorkspaceIncorrecto:
    """El aislamiento no es un parametro: TODO el flujo rechaza."""

    def test_la_configuracion_rechaza_un_perfil_de_otro_workspace(self, gold):
        profile = profile_of(gold, "generic")
        ajeno = GameProfile.from_dict(
            {**profile.to_dict(), "workspace": OTHER_WORKSPACE}, validate=False
        )
        with pytest.raises(PipelineError) as exc:
            base_config(gold, profile=ajeno)
        assert "workspace" in str(exc.value)

    def test_el_extractor_rechaza_episodios_de_otro_workspace(self, gold, entities):
        p = pipeline(gold, workspace=OTHER_WORKSPACE, profile=self._profile(gold))
        with pytest.raises(ExtractionError):
            p.run_source(
                from_episodes(source_named(gold, "leyenda-cronica")),
                catalog_entities=entities,
            )

    def _profile(self, gold):
        profile = profile_of(gold, "generic")
        return GameProfile.from_dict(
            {**profile.to_dict(), "workspace": OTHER_WORKSPACE}, validate=False
        )

    def test_el_motor_rechaza_un_snapshot_de_otro_workspace(self, gold, entities):
        from knowledge_v3.engine.snapshot import empty_snapshot
        from knowledge_v3.pipeline.pipeline import SourceRun

        p = pipeline(
            gold, entity_source="gold", claim_source="gold", ablation="unspecified"
        )
        case = from_episodes(source_named(gold, "leyenda-cronica"))
        run = SourceRun(
            source_id=case.source_id,
            episodes=list(case.episodes),
            fragments=list(case.fragments),
        )
        with pytest.raises(EngineInputError) as exc:
            p.decide(run, empty_snapshot(OTHER_WORKSPACE), case.gold)
        assert "workspace" in str(exc.value)

    def test_el_writer_rechaza_un_plan_de_otro_workspace(self, gold, entities):
        from test_knowledge_v3_e2e_fixtures import frozen_clock

        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        plan = next(p for p in result.plans if p.approved)
        veredicto = admit(
            plan.to_dict(),
            AdmissionContext(
                workspace=OTHER_WORKSPACE,
                current_snapshot_id=plan.snapshot_id,
                clock=frozen_clock(),
            ),
        )
        assert not veredicto.admitted
        assert "PLAN_WORKSPACE_MISMATCH" in veredicto.codes

    def test_ninguna_etapa_deja_pasar_documentos_de_otro_workspace(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        todos = (
            *result.mentions,
            *result.claims,
            *result.resolutions,
            *result.assertions,
            *result.plans,
        )
        assert todos
        assert {d.workspace for d in todos} == {WORKSPACE}


# ===========================================================================
# 10. PLAN NO FIRMADO
# ===========================================================================
class TestConjunta10PlanNoFirmado:
    """El writer solo acepta un plan sellado por el motor local."""

    @pytest.fixture()
    def plan(self, gold, entities):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        return next(p for p in result.plans if p.approved)

    def _admit(self, doc, plan):
        from test_knowledge_v3_e2e_fixtures import frozen_clock

        return admit(
            doc,
            AdmissionContext(
                workspace=WORKSPACE,
                current_snapshot_id=plan.snapshot_id,
                clock=frozen_clock(),
            ),
        )

    def test_el_plan_intacto_si_se_admite(self, plan):
        veredicto = self._admit(plan.to_dict(), plan)
        assert veredicto.admitted, veredicto.codes

    def test_un_plan_sin_firma_se_rechaza(self, plan):
        doc = plan.to_dict()
        doc["local_approval"] = dict(doc["local_approval"])
        doc["local_approval"].pop("decision_hash", None)
        veredicto = self._admit(doc, plan)
        assert not veredicto.admitted

    def test_un_plan_con_operaciones_anadidas_despues_de_firmar_se_rechaza(self, plan):
        """La firma es verificable: tocar el contenido la rompe."""
        doc = plan.to_dict()
        doc["mutation_operations"] = list(doc["mutation_operations"]) + [
            dict(doc["mutation_operations"][0])
        ]
        veredicto = self._admit(doc, plan)
        assert not veredicto.admitted
        assert veredicto.codes  # rompe firma o clave de idempotencia

    def test_un_plan_que_dice_venir_de_ollama_se_rechaza(self, plan):
        doc = plan.to_dict()
        doc["local_approval"] = dict(doc["local_approval"])
        doc["local_approval"]["approved_by"] = {
            "provider": "ollama",
            "name": "s9k.extractor.ollama",
            "version": "1.0.0",
        }
        resellado = seal_plan(doc)
        veredicto = self._admit(resellado, plan)
        assert not veredicto.admitted
        # El contrato congelado fija `approved_by.provider` con `const: "local"`,
        # asi que el rechazo llega antes, en la validacion de esquema. Vale
        # cualquiera de los dos: lo que importa es que no entra.
        assert {"PLAN_NOT_SIGNED_LOCALLY", "PLAN_CONTRACT_INVALID"} & set(
            veredicto.codes
        ), veredicto.codes

    def test_un_plan_marcado_aprobado_a_mano_se_rechaza(self, plan):
        """Aprobarlo por fuera no basta: la cadena de validadores viaja firmada."""
        doc = plan.to_dict()
        doc["local_approval"] = dict(doc["local_approval"])
        doc["local_approval"]["approved"] = True
        doc["local_approval"]["validator_chain"] = []
        veredicto = self._admit(doc, plan)
        assert not veredicto.admitted

    def test_la_cadena_entrega_al_writer_planes_con_la_firma_intacta(
        self, gold, entities
    ):
        _, result = _run_all(
            gold,
            entities,
            entity_source="gold",
            claim_source="gold",
            ablation="unspecified",
        )
        assert result.plans
        for plan in result.plans:
            assert plan.signature_is_intact()
            assert plan.signed_locally()
            assert plan.is_authenticated() is False, (
                "hoy no hay firma criptografica: si esto cambia, actualizar la doc"
            )
