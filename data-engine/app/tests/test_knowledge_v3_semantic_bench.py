# -*- coding: utf-8 -*-
"""Arnes de medicion del extractor semantico sobre el split dev.

Lo que se fija aqui NO son las cifras del modelo (esas viven en
docs/v3/measurements/ y cambian con el modelo): es que el MEDIDOR no mienta.
Un medidor que se equivoca hacia arriba es peor que no medir.

Se comprueba, en concreto:

- el contexto se construye del gold sin colarle las respuestas (ni menciones ni
  claims gold entran en la entrada del extractor);
- el lexico sale del PERFIL, no del catalogo de entidades del benchmark;
- las metricas del bloque coinciden con las del arnes en lo que ambos miden;
- el recall top-2 de predicado no puede superar al top-2 sobre el gold entero;
- `D` es una UNION que conserva el origen y no funde nada;
- el split esta cableado a dev.
"""
from __future__ import annotations

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.benchmarks.loader import load_gold  # noqa: E402
from knowledge_v3.benchmarks.matching import MatchConfig  # noqa: E402
from knowledge_v3.extraction.provider_port import MockProviderPort  # noqa: E402
from knowledge_v3.extraction.semantic_bench import (  # noqa: E402
    CONFIGS,
    SPLIT,
    CachingPort,
    block_metrics,
    build_context,
    run_config,
    score,
    to_bundle,
)


@pytest.fixture(scope="module")
def gold():
    return load_gold(SPLIT)


@pytest.fixture(scope="module")
def ctx(gold):
    return build_context(gold)


class TestContexto:
    def test_el_split_es_dev_y_esta_cableado(self):
        assert SPLIT == "dev"

    def test_el_contexto_no_lleva_las_respuestas(self, ctx, gold):
        assert len(ctx.episodes) == len(gold.episodes)
        assert len(ctx.fragments) == len(gold.fragments)
        assert not hasattr(ctx, "mentions")

    def test_el_lexico_sale_del_perfil_no_del_catalogo(self, ctx, gold):
        superficies = {e.canonical for e in ctx.lexicon.entries}
        del_perfil = {a["canonical"] for a in gold.profiles["generic"]["aliases"]}
        assert superficies <= del_perfil | set(gold.profiles["generic"]["factions"])

    def test_hay_ontologia_en_el_contexto(self, ctx):
        assert ctx.profile is not None
        assert ctx.profile_predicates()


class TestBaseline:
    def test_la_configuracion_A_no_toca_la_red(self, ctx):
        resultado = run_config("A", ctx)
        assert resultado.provider == "local"
        assert resultado.performance == {}

    def test_la_configuracion_A_es_reproducible(self, ctx):
        primera = run_config("A", ctx)
        segunda = run_config("A", ctx)
        assert [m.mention_id for m in primera.output.mentions] == [
            m.mention_id for m in segunda.output.mentions
        ]


class TestMetricasDelBloque:
    def test_el_gold_contra_si_mismo_da_recall_uno(self, gold, ctx):
        from knowledge_v3.benchmarks.loader import PredictionBundle

        bundle = PredictionBundle.from_gold(gold)
        config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
        metricas = block_metrics(gold, bundle, config, ctx.lexicon)
        assert metricas["mentions"]["recall"] == 1.0
        # 19 de 20, no 20 de 20, y el motivo se declara: uno de los claims gold
        # ES una abstencion (`claim:leyenda-escaneo:e02:c00`), y las metricas de
        # claim ACTIVO no la cuentan. El techo real de esta medida es 0.95;
        # publicar 1.0 exigiria contar una abstencion como acierto de claim.
        assert metricas["claims"]["recall"] == 0.95
        assert metricas["claims"]["predicate_top1_recall"] == 0.95
        assert metricas["claims"]["predicate_top2_recall"] == 0.95
        assert metricas["mentions"]["hallucinated_surfaces"] == 0

    def test_top2_nunca_es_menor_que_top1(self, gold, ctx):
        from knowledge_v3.benchmarks.loader import PredictionBundle

        bundle = PredictionBundle.from_gold(gold)
        config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
        claims = block_metrics(gold, bundle, config, ctx.lexicon)["claims"]
        assert claims["predicate_top2_recall"] >= claims["predicate_top1_recall"]

    def test_el_baseline_no_inventa_superficies(self, gold, ctx):
        resultado = run_config("A", ctx)
        informe = score(resultado, gold, ctx)
        assert informe["block_metrics"]["mentions"]["hallucinated_surfaces"] == 0

    def test_las_cifras_de_menciones_coinciden_con_las_del_arnes(self, gold, ctx):
        resultado = run_config("A", ctx)
        informe = score(resultado, gold, ctx)
        assert (
            informe["block_metrics"]["mentions"]["tp"]
            == informe["harness_extractor"]["mentions"]["tp"]
        )

    def test_un_predicado_fuera_de_la_ontologia_se_cuenta(self, gold, ctx):
        from knowledge_v3.benchmarks.loader import PredictionBundle

        bundle = PredictionBundle.from_gold(gold)
        bundle.claims = [dict(c) for c in bundle.claims]
        bundle.claims[0]["predicate_candidates"] = [
            {"predicate": "INVENTADO", "confidence": 0.9}
        ]
        config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
        metricas = block_metrics(gold, bundle, config, ctx.lexicon)
        assert metricas["claims"]["predicates_outside_ontology"] == 1


class TestUnion:
    def test_D_necesita_A_y_C1(self, ctx):
        with pytest.raises(ValueError):
            run_config("D", ctx, prior={})

    def test_D_conserva_el_origen_y_no_funde(self, ctx):
        a = run_config("A", ctx)
        c1 = run_config("C1", ctx, port=MockProviderPort())
        union = run_config("D", ctx, prior={"A": a, "C1": c1})
        assert len(union.output.mentions) == len(a.output.mentions) + len(c1.output.mentions)
        assert union.provider.startswith("local+")

    def test_D_R_necesita_D(self, ctx):
        with pytest.raises(ValueError):
            run_config("D-R", ctx, prior={})

    def test_D_R_reconcilia_la_union(self, ctx):
        a = run_config("A", ctx)
        c1 = run_config("C1", ctx, port=MockProviderPort())
        d = run_config("D", ctx, prior={"A": a, "C1": c1})
        dr = run_config("D-R", ctx, prior={"D": d})
        assert len(dr.output.mentions) <= len(d.output.mentions)
        assert dr.provider.endswith("+reconciler")

    def test_configuraciones_declaradas(self):
        assert CONFIGS == ("A", "C1", "C2", "D", "D-R")


class TestCache:
    def test_la_cache_devuelve_la_misma_respuesta_sin_volver_a_llamar(self, tmp_path):
        from knowledge_v3.extraction.provider_port import ProviderRequest

        interno = MockProviderPort(handler=lambda r: {"mentions": [], "claims": []})
        puerto = CachingPort(interno, tmp_path / "cache.json")
        peticion = ProviderRequest(system="s", prompt="p")
        primera = puerto.complete_json(peticion)
        segunda = CachingPort(interno, tmp_path / "cache.json").complete_json(peticion)
        assert primera.payload == segunda.payload
        assert puerto.misses == 1 and puerto.hits == 0

    def test_la_cache_distingue_prompts(self, tmp_path):
        from knowledge_v3.extraction.provider_port import ProviderRequest

        puerto = CachingPort(MockProviderPort(handler=lambda r: {"mentions": []}), tmp_path / "c.json")
        puerto.complete_json(ProviderRequest(system="s", prompt="uno"))
        puerto.complete_json(ProviderRequest(system="s", prompt="dos"))
        assert puerto.misses == 2


class TestBundle:
    def test_el_bundle_declara_su_split(self, ctx):
        bundle = to_bundle(run_config("A", ctx), ctx)
        assert bundle.split == SPLIT
        assert bundle.subsystem == "extractor"

    def test_el_bundle_no_reporta_recursos_inventados(self, ctx):
        bundle = to_bundle(run_config("A", ctx), ctx)
        assert "external_cost_usd" not in bundle.metadata
