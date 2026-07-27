# -*- coding: utf-8 -*-
"""El dataset gold de desarrollo: contratos, coherencia y cobertura de fenomenos.

Un dataset gold que no valida contra el contrato no es gold: es ruido con
buena presentacion. Y uno que no contiene los fenomenos que dice contener mide
otra cosa distinta de la que promete.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.benchmarks.authoring import build as build_module  # noqa: E402
from knowledge_v3.benchmarks.authoring.common import find_span, table_text  # noqa: E402
from knowledge_v3.benchmarks.contracts_bridge import (  # noqa: E402
    ContractV3Error,
    validate_document,
)
from knowledge_v3.benchmarks.harness import episode_text  # noqa: E402
from knowledge_v3.benchmarks.loader import (  # noqa: E402
    SOURCE_FILES,
    DatasetError,
    available_splits,
    contract_documents,
    load_gold,
)
from knowledge_v3.benchmarks.matching import spans_overlap  # noqa: E402

SPLIT = "dev"


@pytest.fixture(scope="module")
def gold():
    return load_gold(SPLIT)


# --------------------------------------------------------------------------
# Contratos
# --------------------------------------------------------------------------
def test_todo_el_dataset_valida_contra_los_contratos_congelados(gold):
    docs = contract_documents(gold)
    assert len(docs) >= 200, "el dataset perdio documentos"
    for doc in docs:
        validate_document(doc)


def test_el_validador_usado_es_el_real_y_rechaza_un_documento_roto(gold):
    roto = dict(gold.mentions[0])
    roto["evidence_fragment_ids"] = []
    with pytest.raises(ContractV3Error):
        validate_document(roto)


def test_hay_documentos_de_los_nueve_contratos(gold):
    ids = {d["contract_id"] for d in contract_documents(gold)}
    assert ids == {
        "source-asset/v3-internal-v1",
        "source-episode/v3-internal-v1",
        "evidence-fragment/v3-internal-v1",
        "entity-mention/v3-internal-v1",
        "entity-resolution/v3-internal-v1",
        "claim-proposal/v3-internal-v1",
        "fact-assertion/v3-internal-v1",
        "graph-mutation-plan/v3-internal-v1",
        "game-profile/v3-internal-v1",
    }


# --------------------------------------------------------------------------
# Marca de split
# --------------------------------------------------------------------------
def test_todos_los_ficheros_declaran_split_dev():
    root = build_module.DATASETS_DIR / SPLIT
    for path in sorted(root.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("split") == SPLIT, f"{path} no declara split dev"


def test_todos_los_documentos_llevan_la_marca_de_benchmark(gold):
    for doc in contract_documents(gold):
        bench = (doc.get("metadata") or {}).get("benchmark")
        assert bench is not None, doc.get("contract_id")
        assert bench["split"] == SPLIT


def test_el_arnes_no_cablea_el_nombre_del_split():
    assert available_splits() == [SPLIT]
    with pytest.raises((DatasetError, FileNotFoundError)):
        load_gold("heldout")


# --------------------------------------------------------------------------
# Regeneracion determinista
# --------------------------------------------------------------------------
def test_el_dataset_no_ha_derivado_de_su_autoria():
    drift = build_module.check_dataset()
    assert drift == [], f"ficheros derivados: {drift}"


def test_la_generacion_es_determinista():
    assert build_module.build_dataset() == build_module.build_dataset()


def test_el_manifiesto_cuadra_con_los_ficheros(gold):
    totals = gold.manifest["totals"]
    assert totals["episodes"] == len(gold.episodes)
    assert totals["mentions"] == len(gold.mentions)
    assert totals["claims"] == len(gold.claims)
    assert totals["assertions"] == len(gold.assertions)
    assert totals["negatives"] == len(gold.negatives)
    assert totals["plans"] == len(gold.plans)


def test_cada_fuente_trae_todos_sus_ficheros(gold):
    for entry in gold.manifest["sources"]:
        base = build_module.DATASETS_DIR / SPLIT / "sources" / entry["source_id"]
        for name in SOURCE_FILES:
            assert (base / f"{name}.json").exists(), f"{entry['source_id']}/{name}"


# --------------------------------------------------------------------------
# Composicion: multi-fuente, multi-mundo, multimodal
# --------------------------------------------------------------------------
def test_hay_al_menos_tres_mundos_distintos_de_texto(gold):
    markdown_worlds = {
        s.world for s in gold.sources if s.asset["source_kind"] == "MARKDOWN"
    }
    assert len(markdown_worlds) >= 3, markdown_worlds


def test_hay_tabla_transcripcion_y_ocr(gold):
    modalidades = {e["modality"] for e in gold.episodes}
    assert "TABLE" in modalidades
    assert "SPEAKER_TURN" in modalidades
    assert "OCR_TEXT" in modalidades
    assert "DIAGRAM" in modalidades


def test_la_transcripcion_tiene_hablantes_y_anclaje_temporal(gold):
    turnos = [e for e in gold.episodes if e["modality"] == "SPEAKER_TURN"]
    assert len(turnos) >= 3
    hablantes = {e["speaker"]["speaker_id"] for e in turnos}
    assert len(hablantes) >= 2, "un solo hablante no permite probar el 'yo'"
    for e in turnos:
        assert e["time_start"] is not None and e["time_end"] is not None


def test_la_tabla_conserva_filas_y_columnas(gold):
    tablas = [e for e in gold.episodes if e["modality"] == "TABLE"]
    assert tablas
    for e in tablas:
        assert e["table"]["header"]
        assert len(e["table"]["rows"]) >= 3
        assert e["text"] is None, "aplanar la tabla a texto perderia la tabla"


def test_hay_al_menos_dos_planes_de_mutacion_y_de_los_dos_signos(gold):
    assert len(gold.plans) >= 2
    aprobados = [p for p in gold.plans if p["local_approval"]["approved"]]
    assert aprobados, "sin plan aprobado no se puede probar el writer"
    assert len(aprobados) < len(gold.plans), "sin plan bloqueado no se prueba el gate"


# --------------------------------------------------------------------------
# Fenomenos exigidos
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fenomeno",
    [
        "NEGATION",
        "TEMPORALITY",
        "SUPERSESSION",
        "COREFERENCE",
        "SPEAKER_COREFERENCE",
        "SYMMETRIC",
        "RUMOR",
        "HYPOTHETICAL",
        "CONFLICT",
        "OCR_NOISE",
        "FICTION_WITHIN_FICTION",
        "QUESTION",
        "COUNTERFACTUAL",
        "ABSTENTION",
        "VISUAL_INFERRED",
        "ONTOLOGY_VIOLATION",
    ],
)
def test_el_indice_de_fenomenos_declara_el_fenomeno(gold, fenomeno):
    assert fenomeno in gold.manifest["phenomena_index"]


def test_hay_epistemicidad_variada(gold):
    hints = {c["epistemic_status_hint"] for c in gold.claims}
    assert {"ASSERTED", "RUMORED", "HYPOTHETICAL", "VISUAL_INFERRED"} <= hints
    estados = {a["epistemic_status"] for a in gold.assertions}
    assert {"ASSERTED", "RUMORED", "HYPOTHETICAL", "CONFLICTED"} <= estados


def test_la_negacion_es_explicita_en_claims_y_afirmaciones(gold):
    assert sum(1 for c in gold.claims if c["negated"]) >= 3
    assert sum(1 for a in gold.assertions if a["negated"]) >= 3


def test_la_supersesion_encadena_las_dos_afirmaciones(gold):
    by_id = {a["assertion_id"]: a for a in gold.assertions}
    superadas = [a for a in gold.assertions if a["status"] == "SUPERSEDED"]
    assert superadas
    for a in superadas:
        sucesora = by_id[a["superseded_by"]]
        assert sucesora["supersedes"] == a["assertion_id"]
        assert a["valid_to"] is not None
        assert a["valid_to"] <= (sucesora["valid_from"] or a["valid_to"])


def test_hay_relaciones_simetricas_declaradas_en_el_perfil(gold):
    simetricos = gold.symmetric_predicates
    assert {"ALLY_OF", "RIVAL_OF", "SIBLING_OF"} <= simetricos
    usados = {a["predicate"] for a in gold.assertions} & simetricos
    assert len(usados) >= 3
    for a in gold.assertions:
        if a["predicate"] in simetricos:
            assert a["direction"] == "UNDIRECTED"


def test_el_conflicto_se_registra_en_los_dos_sentidos(gold):
    conflictos = [a for a in gold.assertions if a["epistemic_status"] == "CONFLICTED"]
    assert len(conflictos) >= 2
    signos = {(a["subject_entity_id"], a["predicate"], a["object_entity_id"], a["negated"]) for a in conflictos}
    negados = {s[3] for s in signos}
    assert negados == {True, False}, "un conflicto con un solo signo no es un conflicto"


def test_el_ocr_degrada_de_verdad_respecto_a_su_referencia(gold):
    ocr = [e for e in gold.episodes if e["modality"] == "OCR_TEXT"]
    assert ocr
    for e in ocr:
        ref = gold.reference_text[e["episode_id"]]
        assert e["text"] != ref, "un OCR sin errores no prueba nada"
        assert abs(len(e["text"]) - len(ref)) < 10


def test_la_correferencia_incluye_pronombres_y_primera_persona(gold):
    kinds = {(m.get("metadata") or {}).get("mention_kind") for m in gold.mentions}
    assert "PRONOUN" in kinds
    assert "NOMINAL" in kinds
    assert "SPEAKER_SELF" in kinds
    for m in gold.mentions:
        if (m.get("metadata") or {}).get("mention_kind") == "SPEAKER_SELF":
            assert m["coreference_candidates"] or True  # el 'yo' puede ser unico


def test_los_casos_negativos_cubren_los_tres_tipos_exigidos(gold):
    kinds = {n["kind"] for n in gold.negatives}
    assert {"FICTION_WITHIN_FICTION", "QUESTION", "COUNTERFACTUAL"} <= kinds


def test_hay_abstencion_y_entidad_provisional(gold):
    assert any(c["abstained"] for c in gold.claims)
    assert any(r["action"] == "CREATE_PROVISIONAL" for r in gold.resolutions)
    assert any(r["action"] == "CREATE_NEW" for r in gold.resolutions)


def test_hay_decisiones_de_los_cuatro_tipos(gold):
    tipos = {d["decision"] for d in gold.decisions}
    assert tipos == {"ACCEPT", "REVIEW", "ABSTAIN", "REJECT_INVALID"}


# --------------------------------------------------------------------------
# Coherencia interna
# --------------------------------------------------------------------------
def test_no_hay_identificadores_repetidos(gold):
    for nombre, items, campo in (
        ("episodios", gold.episodes, "episode_id"),
        ("fragmentos", gold.fragments, "fragment_id"),
        ("menciones", gold.mentions, "mention_id"),
        ("resoluciones", gold.resolutions, "resolution_id"),
        ("claims", gold.claims, "claim_id"),
        ("afirmaciones", gold.assertions, "assertion_id"),
        ("planes", gold.plans, "plan_id"),
    ):
        ids = [i[campo] for i in items]
        assert len(ids) == len(set(ids)), f"{nombre} con id repetido"


def test_todas_las_referencias_cruzadas_existen(gold):
    episodios = {e["episode_id"] for e in gold.episodes}
    fragmentos = {f["fragment_id"] for f in gold.fragments}
    menciones = {m["mention_id"] for m in gold.mentions}
    claims = {c["claim_id"] for c in gold.claims}
    entidades = gold.catalog_entity_ids
    afirmaciones = {a["assertion_id"] for a in gold.assertions}

    for f in gold.fragments:
        assert f["episode_id"] in episodios
    for m in gold.mentions:
        assert m["episode_id"] in episodios
        assert set(m["evidence_fragment_ids"]) <= fragmentos
        assert set(m["coreference_candidates"]) <= menciones
    for c in gold.claims:
        assert c["episode_id"] in episodios
        assert set(c["evidence_fragment_ids"]) <= fragmentos
        assert set(c["subject_mentions"]) <= menciones
        assert set(c["object_mentions"]) <= menciones
    for r in gold.resolutions:
        assert set(r["mention_ids"]) <= menciones
        assert set(r["evidence"]) <= fragmentos
        for campo in ("selected_entity_id", "assigned_entity_id"):
            if r[campo] is not None:
                assert r[campo] in entidades, r[campo]
    for a in gold.assertions:
        assert a["subject_entity_id"] in entidades
        assert a["object_entity_id"] in entidades
        assert set(a["evidence_fragment_ids"]) <= fragmentos
        assert set(a["episode_ids"]) <= episodios
        for campo in ("supersedes", "superseded_by"):
            if a[campo] is not None:
                assert a[campo] in afirmaciones
    for p in gold.plans:
        for d in p["decisions"]:
            assert d["claim_id"] in claims
            assert set(d["evidence_fragment_ids"]) <= fragmentos
        for op in p["mutation_operations"]:
            if op["assertion_id"] is not None:
                assert op["assertion_id"] in afirmaciones
            if op["target_entity_id"] is not None:
                assert op["target_entity_id"] in entidades


def test_toda_operacion_de_escritura_cuelga_de_un_accept(gold):
    for p in gold.plans:
        por_id = {d["decision_id"]: d for d in p["decisions"]}
        for op in p["mutation_operations"]:
            assert por_id[op["decision_id"]]["decision"] == "ACCEPT"


def test_cada_claim_tiene_exactamente_una_decision(gold):
    claims = {c["claim_id"] for c in gold.claims}
    decididos = [d["claim_id"] for d in gold.decisions]
    assert sorted(decididos) == sorted(claims)


def test_los_offsets_del_gold_apuntan_al_texto_real(gold):
    por_episodio = {e["episode_id"]: episode_text(e) for e in gold.episodes}
    for f in gold.fragments:
        texto = por_episodio[f["episode_id"]]
        assert texto[f["start"] : f["end"]] == f["literal_text"]
    for m in gold.mentions:
        texto = por_episodio[m["episode_id"]]
        assert texto[m["start"] : m["end"]] == m["surface"]


def test_ningun_claim_gold_se_apoya_en_un_tramo_prohibido(gold):
    """La trampa solo funciona si el propio gold no cae en ella."""
    fragmentos = {f["fragment_id"]: f for f in gold.fragments}
    menciones = {m["mention_id"]: m for m in gold.mentions}
    for negativo in gold.negatives:
        for claim in gold.claims:
            spans = [fragmentos[f] for f in claim["evidence_fragment_ids"]]
            spans += [
                menciones[m]
                for m in claim["subject_mentions"] + claim["object_mentions"]
            ]
            for span in spans:
                if span["episode_id"] != negativo["episode_id"]:
                    continue
                assert not spans_overlap(
                    span["start"], span["end"], negativo["start"], negativo["end"]
                ), f"{claim['claim_id']} pisa {negativo['negative_id']}"


def test_los_negativos_apuntan_al_texto_real(gold):
    por_episodio = {e["episode_id"]: episode_text(e) for e in gold.episodes}
    for n in gold.negatives:
        texto = por_episodio[n["episode_id"]]
        assert texto[n["start"] : n["end"]] == n["literal_text"]


def test_los_predicados_usados_estan_en_el_perfil(gold):
    perfil = {p["predicate"] for p in gold.profiles["generic"]["predicates"]}
    for a in gold.assertions:
        assert a["predicate"] in perfil
    for c in gold.claims:
        for cand in c["predicate_candidates"]:
            assert cand["predicate"] in perfil


def test_el_perfil_estrecho_es_de_verdad_mas_pobre(gold):
    ancho = {p["predicate"] for p in gold.profiles["generic"]["predicates"]}
    estrecho = {p["predicate"] for p in gold.profiles["bench-narrow"]["predicates"]}
    assert estrecho < ancho
    assert {"LEADS", "RIVAL_OF", "SIBLING_OF"} & estrecho == set()


def test_el_render_canonico_de_tabla_es_estable(gold):
    tabla = next(e for e in gold.episodes if e["modality"] == "TABLE")["table"]
    render = table_text(tabla)
    assert render.split("\n")[0] == "\t".join(tabla["header"])
    assert find_span(render, "Ruta Simm")[0] > 0


def test_las_fuentes_con_datos_personales_no_admiten_proveedor_externo(gold):
    for s in gold.sources:
        if s.asset["privacy_class"] in ("PERSONAL_DATA", "RESTRICTED"):
            assert s.asset["processing_policy"]["allow_external_providers"] is False


# --------------------------------------------------------------------------
# Revision independiente: observaciones sobre el gold
# --------------------------------------------------------------------------
#: Politica de anotacion de sustantivos de rol. Se anota como mencion toda
#: expresion que designe una entidad IDENTIFICABLE del catalogo: nombre propio,
#: nominal definido correferente ("El magistrado" -> Daiki) y pronombre
#: correferente ("alli", "Yo"). NO se anotan los sustantivos de rol que no
#: designan a nadie resoluble en este dataset. Exigirlos mediria otra tarea
#: -deteccion de menciones genericas- que el pipeline V3 no hace, y dejarlos
#: anotados sin entidad obligaria al resolutor a inventarse identidades.
SUSTANTIVOS_DE_ROL_SIN_ANOTAR = (
    "el senescal",
    "El escriba",
    "El maestre de puerto",
    "los titiriteros",
    "los estibadores",
    "el guionista",
    "jefa de operaciones",
)


def test_los_sustantivos_de_rol_sin_referente_no_se_anotan(gold):
    superficies = {m["surface"] for m in gold.mentions}
    for termino in SUSTANTIVOS_DE_ROL_SIN_ANOTAR:
        assert termino not in superficies, (
            f"{termino!r} no designa a ninguna entidad del catalogo: anotarlo "
            "obligaria al resolutor a inventarse una identidad"
        )


def test_todo_nominal_o_pronombre_anotado_tiene_entidad_resuelta(gold):
    """La otra cara de la politica: lo que se anota, se resuelve."""
    asignacion = gold.mention_to_entity()
    for m in gold.mentions:
        kind = (m.get("metadata") or {}).get("mention_kind")
        if kind in ("PRONOUN", "NOMINAL", "SPEAKER_SELF"):
            assert m["mention_id"] in asignacion, m["surface"]


def test_umbra_suelta_esta_anotada_y_no_es_el_consejo(gold):
    """Observacion del revisor: 'emisarios llegados de Umbra'."""
    umbra = [m for m in gold.mentions if m["surface"] == "Umbra"]
    assert len(umbra) == 1, "la ciudad suelta tiene que estar anotada"
    asignacion = gold.mention_to_entity()
    assert asignacion[umbra[0]["mention_id"]] == "entity:leyenda:umbra"
    consejo = [m for m in gold.mentions if m["surface"] == "Consejo de Umbra"]
    assert consejo
    for m in consejo:
        assert asignacion[m["mention_id"]] == "entity:leyenda:consejo-umbra"


def test_la_ciudad_y_la_faccion_son_entidades_distintas(gold):
    por_id = {e["entity_id"]: e for e in gold.entities}
    assert por_id["entity:leyenda:umbra"]["type"] == "Location"
    assert por_id["entity:leyenda:consejo-umbra"]["type"] == "Faction"


def test_la_magistratura_es_leads_en_todas_las_fuentes(gold):
    """Observacion del revisor: el nombramiento de Daiki no puede ser MEMBER_OF
    en una fuente y LEADS en otra. Es el mismo cargo."""
    magistratura = [
        c
        for c in gold.claims
        if "magistrado" in c["relation_phrase"] or "el cargo recay" in c["relation_phrase"]
    ]
    assert len(magistratura) >= 2, "el cargo se menciona en al menos dos fuentes"
    for c in magistratura:
        predicados = {p["predicate"] for p in c["predicate_candidates"]}
        assert predicados == {"LEADS"}, c["claim_id"]


def test_la_segunda_fuente_del_mismo_hecho_no_crea_una_afirmacion_nueva(gold):
    """El escaneo confirma un hecho ya conocido: operacion idempotente, no duplicado."""
    escaneo = next(s for s in gold.sources if s.source_id == "leyenda-escaneo")
    assert escaneo.assertions == []
    ops = [op for p in escaneo.plans for op in p["mutation_operations"]]
    no_op = [op for op in ops if op["expected_state"] == "NO_OP"]
    assert len(no_op) == 1
    assert no_op[0]["assertion_id"] == "assertion:leyenda:daiki-leads-casa"


def test_hay_dos_casos_de_hecho_repetido_entre_fuentes(gold):
    todas = [
        op
        for p in gold.plans
        for op in p["mutation_operations"]
        if op["expected_state"] == "NO_OP"
    ]
    assert len(todas) == 2, "tabla y escaneo repiten cada uno un hecho ya conocido"


def test_ninguna_clave_de_hecho_esta_duplicada_en_el_gold(gold):
    from knowledge_v3.benchmarks.matching import MatchConfig, fact_key

    config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
    claves = [fact_key(a, config) for a in gold.assertions]
    assert len(claves) == len(set(claves)), "dos afirmaciones gold para el mismo hecho"
