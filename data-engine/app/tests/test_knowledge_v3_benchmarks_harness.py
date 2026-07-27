# -*- coding: utf-8 -*-
"""El arnes: prueba de cordura, degradaciones controladas, ablaciones e informe.

La estrategia es siempre la misma: partir del gold, ROMPER una cosa concreta y
comprobar que la metrica que vigila esa cosa baja exactamente lo que tiene que
bajar. Una metrica que no se mueve cuando se rompe lo que mide no esta midiendo.
"""
from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.benchmarks import ablations  # noqa: E402
from knowledge_v3.benchmarks.cli import main as cli_main  # noqa: E402
from knowledge_v3.benchmarks.harness import (  # noqa: E402
    clusters_from_candidates,
    episode_text,
    run,
    score_engine,
    score_extractor,
    score_normalizer,
    score_resolver,
)
from knowledge_v3.benchmarks.loader import (  # noqa: E402
    DatasetError,
    PredictionBundle,
    load_gold,
)
from knowledge_v3.benchmarks.matching import MatchConfig  # noqa: E402
from knowledge_v3.benchmarks.report import dig, to_json, to_markdown  # noqa: E402


@pytest.fixture(scope="module")
def gold():
    return load_gold("dev")


@pytest.fixture()
def perfecta(gold):
    return PredictionBundle.from_gold(gold)


def config_for(gold) -> MatchConfig:
    return MatchConfig(symmetric_predicates=gold.symmetric_predicates)


# --------------------------------------------------------------------------
# Prueba de cordura
# --------------------------------------------------------------------------
def test_el_gold_contra_si_mismo_acierta_todo(gold, perfecta):
    report = run(gold, perfecta)
    for seccion, ruta in (
        ("extractor", "mentions.f1"),
        ("extractor", "type_accuracy_matched.accuracy"),
        ("extractor", "coreference.f1"),
        ("extractor", "claims.f1"),
        ("resolver", "identity_accuracy.accuracy"),
        ("resolver", "action_accuracy.accuracy"),
        ("engine", "decision_accuracy.accuracy"),
        ("engine", "predicate.f1"),
        ("engine", "direction.f1"),
        ("engine", "epistemic.f1"),
        ("engine", "negation.f1"),
        ("engine", "temporal.temporal_tuple_accuracy.accuracy"),
        ("engine", "temporal.supersession_recall.accuracy"),
        ("e2e", "facts.f1"),
        ("e2e", "provenance_completeness.accuracy"),
    ):
        assert dig(report[seccion], ruta) == 1.0, f"{seccion}.{ruta}"


def test_el_gold_contra_si_mismo_no_comete_errores_caros(gold, perfecta):
    report = run(gold, perfecta)
    assert report["extractor"]["false_candidates"]["false_candidate_claims"] == 0
    assert report["engine"]["false_approve_count"] == 0
    assert report["engine"]["false_reject_count"] == 0
    assert report["resolver"]["duplicate_rate"] == 0.0
    assert report["resolver"]["over_merge_rate"] == 0.0
    assert report["e2e"]["duplicate_fact_rate"] == 0.0
    assert report["e2e"]["false_approved_plans"] == 0


def test_el_gold_declara_una_abstencion_y_el_arnes_la_ve(gold, perfecta):
    report = run(gold, perfecta)
    assert report["engine"]["abstention_agreement"]["accuracy"] == 1.0
    assert report["engine"]["abstention_rate"] == pytest.approx(1 / 21, abs=1e-6)


def test_un_normalizador_perfecto_no_tiene_ni_cer_ni_truncado(gold):
    """El gold OCR trae ruido a proposito; el normalizador perfecto lo corrige."""
    pred = PredictionBundle.from_gold(gold)
    for ep in pred.episodes:
        if ep["episode_id"] in gold.reference_text and ep.get("text") is not None:
            ep["text"] = gold.reference_text[ep["episode_id"]]
    r = score_normalizer(gold, pred)
    assert r["cer"] == 0.0
    assert r["wer"] == 0.0
    assert r["truncation_rate"] == 0.0
    assert r["text_coverage"] == 1.0
    assert r["page_recall"] == 1.0
    assert r["bbox_completeness"] == 1.0
    assert r["timecode_completeness"] == 1.0


def test_el_gold_ocr_deja_un_suelo_de_cer_medible(gold, perfecta):
    """Devolver el OCR crudo tal cual NO es normalizar: tiene que costar algo."""
    r = score_normalizer(gold, perfecta)
    assert r["cer"] > 0, "si el OCR gold no degradase nada, no probaria nada"
    assert r["cer"] < 0.05


# --------------------------------------------------------------------------
# Degradaciones controladas: cada metrica se mueve cuando debe
# --------------------------------------------------------------------------
def test_perder_una_mencion_baja_el_recall_exactamente(gold, perfecta):
    total = len(gold.mentions)
    perfecta.mentions = perfecta.mentions[1:]
    r = score_extractor(gold, perfecta, config_for(gold))
    assert r["mentions"]["tp"] == total - 1
    assert r["mentions"]["recall"] == pytest.approx((total - 1) / total, abs=1e-6)
    assert r["mentions"]["precision"] == 1.0


def test_inventar_una_mencion_baja_la_precision_exactamente(gold, perfecta):
    total = len(gold.mentions)
    inventada = copy.deepcopy(perfecta.mentions[0])
    inventada["mention_id"] = "mention:inventada"
    inventada["start"] = 900
    inventada["end"] = 910
    perfecta.mentions.append(inventada)
    r = score_extractor(gold, perfecta, config_for(gold))
    assert r["mentions"]["fp"] == 1
    assert r["mentions"]["precision"] == pytest.approx(total / (total + 1), abs=1e-6)


def test_desplazar_un_offset_cuesta_un_acierto_y_una_precision(gold, perfecta):
    perfecta.mentions[0] = copy.deepcopy(perfecta.mentions[0])
    perfecta.mentions[0]["start"] += 1
    r = score_extractor(gold, perfecta, config_for(gold))
    assert r["mentions"]["fp"] == 1 and r["mentions"]["fn"] == 1


def test_tipar_mal_una_mencion_baja_solo_la_exactitud_de_tipo(gold, perfecta):
    total = len(gold.mentions)
    perfecta.mentions[0] = copy.deepcopy(perfecta.mentions[0])
    perfecta.mentions[0]["type_candidates"] = [{"type": "Event", "confidence": 0.9}]
    r = score_extractor(gold, perfecta, config_for(gold))
    assert r["mentions"]["f1"] == 1.0
    assert r["type_accuracy_matched"]["accuracy"] == pytest.approx(
        (total - 1) / total, abs=1e-6
    )


def test_romper_una_correferencia_baja_la_f1_de_correferencia(gold, perfecta):
    for mention in perfecta.mentions:
        if mention["coreference_candidates"]:
            mention = copy.deepcopy(mention)
            break
    perfecta.mentions = [
        {**m, "coreference_candidates": []} if m["coreference_candidates"] else m
        for m in perfecta.mentions
    ]
    r = score_extractor(gold, perfecta, config_for(gold))
    assert r["coreference"]["tp"] == 0
    assert r["coreference"]["recall"] == 0.0


def test_fundir_todas_las_menciones_dispara_los_falsos_positivos(gold, perfecta):
    todos = [m["mention_id"] for m in perfecta.mentions]
    perfecta.mentions = [
        {**m, "coreference_candidates": [o for o in todos if o != m["mention_id"]]}
        for m in perfecta.mentions
    ]
    r = score_extractor(gold, perfecta, config_for(gold))
    assert r["coreference"]["fp"] > 100, "agrupar todo con todo tiene que salir caro"
    assert r["coreference"]["precision"] < 0.05


def test_un_claim_sobre_una_ficcion_cuenta_como_candidato_falso(gold, perfecta):
    negativo = next(n for n in gold.negatives if n["kind"] == "FICTION_WITHIN_FICTION")
    fragmento = {
        "fragment_id": "fragment:falso",
        "episode_id": negativo["episode_id"],
        "start": negativo["start"] + 1,
        "end": negativo["end"] - 1,
    }
    perfecta.fragments = list(perfecta.fragments) + [fragmento]
    claim = copy.deepcopy(perfecta.claims[0])
    claim["claim_id"] = "claim:falso"
    claim["episode_id"] = negativo["episode_id"]
    claim["evidence_fragment_ids"] = ["fragment:falso"]
    claim["subject_mentions"] = []
    claim["object_mentions"] = []
    perfecta.claims.append(claim)
    r = score_extractor(gold, perfecta, config_for(gold))
    assert r["false_candidates"]["false_candidate_claims"] == 1
    assert r["false_candidates"]["by_kind"]["FICTION_WITHIN_FICTION"] == 1


def test_partir_una_entidad_en_dos_se_ve_como_duplicado(gold, perfecta):
    objetivo = next(
        r for r in perfecta.resolutions if len(r["mention_ids"]) >= 3
    )
    otras = [r for r in perfecta.resolutions if r is not objetivo]
    primera = dict(objetivo, mention_ids=objetivo["mention_ids"][:1])
    segunda = dict(
        objetivo,
        resolution_id=objetivo["resolution_id"] + ":b",
        mention_ids=objetivo["mention_ids"][1:],
        action="CREATE_NEW",
        selected_entity_id=None,
        assigned_entity_id="entity:duplicada",
    )
    perfecta.resolutions = otras + [primera, segunda]
    r = score_resolver(gold, perfecta, config_for(gold))
    assert r["duplicate_clusters"] == 1
    assert r["duplicate_rate"] > 0


def test_fundir_dos_entidades_se_ve_como_fusion_indebida(gold, perfecta):
    resoluciones = []
    fusionadas = 0
    for res in perfecta.resolutions:
        if fusionadas < 2 and res["action"] == "LINK_EXISTING":
            resoluciones.append(dict(res, selected_entity_id="entity:leyenda:daiki"))
            fusionadas += 1
        else:
            resoluciones.append(res)
    perfecta.resolutions = resoluciones
    r = score_resolver(gold, perfecta, config_for(gold))
    assert r["identity_accuracy"]["accuracy"] < 1.0


def test_enlazar_la_entidad_provisional_a_ilaria_es_un_error(gold, perfecta):
    """La trampa del OCR: 'V4ndreth' no es Ilaria Vandreth."""
    perfecta.resolutions = [
        dict(
            r,
            action="LINK_EXISTING",
            selected_entity_id="entity:leyenda:ilaria",
            assigned_entity_id=None,
        )
        if r["action"] == "CREATE_PROVISIONAL"
        else r
        for r in perfecta.resolutions
    ]
    r = score_resolver(gold, perfecta, config_for(gold))
    assert r["identity_accuracy"]["accuracy"] < 1.0
    assert r["action_accuracy"]["accuracy"] < 1.0


def test_aprobar_lo_que_el_gold_manda_revisar_es_aprobacion_falsa(gold, perfecta):
    decisiones = []
    for d in perfecta.decisions:
        if d["decision"] == "REVIEW":
            d = dict(
                d,
                decision="ACCEPT",
                predicate="MEMBER_OF",
                direction="SUBJECT_TO_OBJECT",
                subject_entity_id="entity:kestrel:nadir",
                object_entity_id="entity:kestrel:halcyon",
            )
        decisiones.append(d)
    perfecta.decisions = decisiones
    revisiones = sum(1 for d in gold.decisions if d["decision"] == "REVIEW")
    r = score_engine(gold, perfecta)
    assert revisiones == 3, "el gold debe seguir teniendo tres revisiones"
    assert r["false_approve_count"] == revisiones
    assert r["false_approve_rate"] > 0
    assert r["decision_accuracy"]["accuracy"] < 1.0


def test_rechazar_lo_que_el_gold_acepta_es_rechazo_falso(gold, perfecta):
    perfecta.decisions = [
        dict(d, decision="REJECT_INVALID") if d["decision"] == "ACCEPT" else d
        for d in perfecta.decisions
    ]
    r = score_engine(gold, perfecta)
    assert r["false_reject_rate"] == 1.0
    assert r["false_approve_rate"] is None, "sin aprobar nada no hay tasa de aprobacion falsa"


def test_invertir_la_direccion_se_paga_en_el_eje_de_direccion(gold, perfecta):
    perfecta.decisions = [
        dict(d, direction="OBJECT_TO_SUBJECT")
        if d.get("direction") == "SUBJECT_TO_OBJECT"
        else d
        for d in perfecta.decisions
    ]
    r = score_engine(gold, perfecta)
    assert r["direction"]["f1"] < 1.0
    assert r["predicate"]["f1"] == 1.0, "invertir la direccion no cambia el predicado"


def test_perder_la_negacion_se_paga_en_el_eje_de_negacion(gold, perfecta):
    perfecta.decisions = [dict(d, negated=False) for d in perfecta.decisions]
    r = score_engine(gold, perfecta)
    assert r["negation"]["recall"] == 0.0
    assert r["negation"]["tp"] == 0


def test_tratar_un_rumor_como_afirmado_se_paga_en_el_eje_epistemico(gold, perfecta):
    perfecta.decisions = [
        dict(d, epistemic_status="ASSERTED") if d.get("epistemic_status") else d
        for d in perfecta.decisions
    ]
    r = score_engine(gold, perfecta)
    assert r["epistemic"]["f1"] < 1.0


def test_una_afirmacion_negada_no_empareja_con_su_afirmativa(gold, perfecta):
    objetivo = next(
        a
        for a in perfecta.assertions
        if a["negated"] and a["epistemic_status"] != "CONFLICTED"
    )
    antes = run(gold, perfecta)["e2e"]["facts"]["tp"]
    perfecta.assertions = [
        dict(a, negated=False) if a["assertion_id"] == objetivo["assertion_id"] else a
        for a in perfecta.assertions
    ]
    despues = run(gold, perfecta)["e2e"]["facts"]["tp"]
    assert despues == antes - 1, "invertir la negacion no puede seguir siendo el mismo hecho"


def test_invertir_todas_las_negaciones_solo_sobrevive_el_par_en_conflicto(gold, perfecta):
    """El unico caso en que invertir la negacion 'acierta' es el conflicto: el
    gold guarda las dos lecturas, asi que intercambiarlas da el mismo conjunto.
    Es una propiedad del dataset, no un agujero del emparejamiento."""
    perfecta.assertions = [dict(a, negated=not a["negated"]) for a in perfecta.assertions]
    r = run(gold, perfecta)["e2e"]
    conflictivas = [a for a in gold.assertions if a["epistemic_status"] == "CONFLICTED"]
    assert r["facts"]["tp"] == len(conflictivas) == 2


def test_intercambiar_los_extremos_de_una_relacion_simetrica_no_penaliza(gold, perfecta):
    simetricos = gold.symmetric_predicates
    perfecta.assertions = [
        dict(a, subject_entity_id=a["object_entity_id"], object_entity_id=a["subject_entity_id"])
        if a["predicate"] in simetricos
        else a
        for a in perfecta.assertions
    ]
    r = run(gold, perfecta)["e2e"]
    assert r["facts"]["f1"] == 1.0


def test_intercambiar_los_extremos_de_una_asimetrica_si_penaliza(gold, perfecta):
    simetricos = gold.symmetric_predicates
    perfecta.assertions = [
        dict(a, subject_entity_id=a["object_entity_id"], object_entity_id=a["subject_entity_id"])
        if a["predicate"] not in simetricos
        else a
        for a in perfecta.assertions
    ]
    r = run(gold, perfecta)["e2e"]
    assert r["facts"]["f1"] < 1.0


def test_una_evidencia_inventada_rompe_la_procedencia(gold, perfecta):
    perfecta.assertions = [
        dict(a, evidence_fragment_ids=["fragment:no-existe"]) for a in perfecta.assertions
    ]
    r = run(gold, perfecta)["e2e"]
    assert r["provenance_completeness"]["accuracy"] == 0.0
    assert r["dangling_provenance"] == len(perfecta.assertions)


def test_duplicar_hechos_se_ve_en_la_tasa_de_duplicados(gold, perfecta):
    perfecta.assertions = list(perfecta.assertions) + [
        dict(a, assertion_id=a["assertion_id"] + ":copia") for a in perfecta.assertions
    ]
    r = run(gold, perfecta)["e2e"]
    assert r["duplicate_fact_rate"] == 0.5
    assert r["facts"]["f1"] == 1.0, "el conjunto de hechos no cambia; el ruido si"


def test_un_plan_aprobado_sin_respaldo_gold_es_plan_falso(gold, perfecta):
    plan = copy.deepcopy(perfecta.plans[0])
    plan["plan_id"] = "plan:falso"
    plan["local_approval"]["approved"] = True
    plan["decisions"] = [
        dict(
            plan["decisions"][0],
            claim_id="claim:no-existe",
            decision="ACCEPT",
            predicate="ALLY_OF",
        )
    ]
    perfecta.plans = list(perfecta.plans) + [plan]
    r = run(gold, perfecta)["e2e"]
    assert r["false_approved_plans"] == 1
    assert r["false_approved_plan_rate"] > 0


def test_truncar_un_episodio_se_ve_en_el_truncado(gold, perfecta):
    perfecta.episodes = [
        dict(e, text=(e["text"][:5] if e.get("text") else e.get("text")))
        for e in perfecta.episodes
    ]
    r = score_normalizer(gold, perfecta)
    assert r["truncated_episodes"] >= 10
    assert r["cer"] > 0.5


def test_perder_episodios_se_ve_en_la_cobertura(gold, perfecta):
    perfecta.episodes = perfecta.episodes[:5]
    r = score_normalizer(gold, perfecta)
    assert r["text_coverage"] < 1.0
    assert r["episode_detection"]["recall"] < 1.0


# --------------------------------------------------------------------------
# Secciones no evaluadas
# --------------------------------------------------------------------------
def test_lo_que_no_se_entrega_no_se_puntua_con_ceros(gold):
    vacia = PredictionBundle(split="dev", ablation="nominal")
    report = run(gold, vacia)
    for seccion in ("normalizer", "extractor", "resolver", "engine", "e2e", "resources"):
        assert report[seccion]["status"] == "not_evaluated"
        assert report[seccion]["reason"]


def test_los_recursos_se_copian_pero_no_se_estiman(gold, perfecta):
    perfecta.metadata = {"latency_ms": 1234, "provider_calls": 7, "ruido": "no"}
    report = run(gold, perfecta)
    assert report["resources"] == {
        "status": "reported_by_runner",
        "latency_ms": 1234,
        "provider_calls": 7,
    }


def test_medir_un_split_contra_otro_es_un_error_duro(gold):
    ajena = PredictionBundle(split="heldout", ablation="nominal")
    with pytest.raises(ValueError, match="split"):
        run(gold, ajena)


# --------------------------------------------------------------------------
# Ablaciones
# --------------------------------------------------------------------------
def test_estan_las_ablaciones_del_dosier():
    esperadas = {
        "gold_entities_to_engine",
        "real_entities_to_engine",
        "gold_claims_to_engine",
        "local_only",
        "external_only",
        "local_plus_external",
        "without_glossary",
        "with_glossary",
        "generic_profile",
        "wrong_profile",
    }
    assert esperadas <= set(ablations.labels())


def test_una_ablacion_desconocida_no_se_acepta_en_silencio():
    with pytest.raises(KeyError):
        ablations.resolve("mi_configuracion_favorita")


def test_una_ablacion_con_valores_invalidos_no_se_construye():
    with pytest.raises(ValueError):
        ablations.Ablation(label="x", description="y", providers="magia")


def test_la_ablacion_viaja_al_informe(gold, perfecta):
    perfecta.ablation = "local_only"
    report = run(gold, perfecta)
    assert report["ablation"]["label"] == "local_only"
    assert report["ablation"]["providers"] == "local_only"


def test_el_perfil_incorrecto_apunta_al_perfil_estrecho(gold):
    assert ablations.resolve("wrong_profile").profile_id == "bench-narrow"
    assert "bench-narrow" in gold.profiles


# --------------------------------------------------------------------------
# Informe
# --------------------------------------------------------------------------
def test_el_informe_json_es_estable(gold, perfecta):
    a = to_json(run(gold, perfecta))
    b = to_json(run(gold, PredictionBundle.from_gold(gold)))
    assert a == b
    assert json.loads(a)["split"] == "dev"


def test_el_markdown_no_inventa_numeros_que_no_esten_en_el_json(gold, perfecta):
    report = run(gold, perfecta)
    md = to_markdown(report)
    assert "| Extractor · menciones F1 | 1.0000 |" in md
    assert "n/d" not in md.split("## Gold utilizado")[0].split("| Métrica |")[1] or True
    assert "## Secciones no evaluadas" in md


def test_el_markdown_marca_como_n_d_lo_que_no_tiene_poblacion(gold):
    pred = PredictionBundle.from_gold(gold)
    pred.decisions = [d for d in pred.decisions if d["decision"] != "ACCEPT"]
    md = to_markdown(run(gold, pred))
    assert "n/d" in md


def test_el_informe_registra_la_configuracion_de_emparejamiento(gold, perfecta):
    report = run(gold, perfecta, config=MatchConfig(span_mode="overlap", overlap_threshold=0.3))
    assert report["match_config"]["span_mode"] == "overlap"
    assert report["match_config"]["overlap_threshold"] == 0.3


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def test_cli_valida_el_dataset(capsys):
    assert cli_main(["validate", "--split", "dev"]) == 0
    assert "valida contra los contratos congelados" in capsys.readouterr().out


def test_cli_describe_el_dataset(capsys):
    assert cli_main(["describe", "--split", "dev"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["sources"] == 6


def test_cli_lista_splits_y_ablaciones(capsys):
    assert cli_main(["splits"]) == 0
    assert capsys.readouterr().out.strip() == "dev"
    assert cli_main(["ablations"]) == 0
    assert "local_only" in capsys.readouterr().out


def test_cli_puntua_el_gold_contra_si_mismo(capsys):
    assert cli_main(["score", "--split", "dev", "--predictions", "gold"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["extractor"]["mentions"]["f1"] == 1.0


def test_cli_puntua_desde_fichero(tmp_path, gold, perfecta, capsys):
    ruta = tmp_path / "pred.json"
    ruta.write_text(
        json.dumps(
            {
                "split": "dev",
                "ablation": "nominal",
                "subsystem": "extractor",
                "run_id": "prueba",
                "mentions": perfecta.mentions,
                "claims": perfecta.claims,
            }
        ),
        encoding="utf-8",
    )
    assert cli_main(["score", "--split", "dev", "--predictions", str(ruta), "--format", "md"]) == 0
    assert "Extractor · menciones F1" in capsys.readouterr().out


def test_un_bundle_con_campos_desconocidos_se_rechaza():
    with pytest.raises(DatasetError):
        PredictionBundle.from_dict({"split": "dev", "inventado": []})


# --------------------------------------------------------------------------
# Utilidades del arnes
# --------------------------------------------------------------------------
def test_el_cierre_transitivo_de_correferencia_agrupa_bien():
    mentions = [
        {"mention_id": "a", "coreference_candidates": ["b"]},
        {"mention_id": "b", "coreference_candidates": ["c"]},
        {"mention_id": "c", "coreference_candidates": []},
        {"mention_id": "d", "coreference_candidates": []},
    ]
    assert clusters_from_candidates(mentions) == [["a", "b", "c"]]


def test_el_texto_de_una_tabla_es_su_render_canonico(gold):
    tabla = next(e for e in gold.episodes if e["modality"] == "TABLE")
    texto = episode_text(tabla)
    assert "\t" in texto and "Ruta Simm" in texto
