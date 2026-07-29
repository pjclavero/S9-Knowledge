# -*- coding: utf-8 -*-
"""La bateria de negaciones (split `negation`).

Este test NO mide nada: no ejecuta el extractor ni el motor contra la bateria.
Medirla es del bloque siguiente y con otros ojos. Aqui solo se defiende que el
GOLD es un gold: que carga con el loader real, que valida contra los contratos
congelados, que la distribucion por familia cuadra con la tabla de
docs/v3/18 §3, que no hay claves de hecho duplicadas y que la bateria no esta
enchufada a ningun flujo automatico.

Ver `docs/v3/19-bateria-de-negaciones.md`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.benchmarks.contracts_bridge import validate_document  # noqa: E402
from knowledge_v3.benchmarks.datasets.negation._authoring import cases as K  # noqa: E402
from knowledge_v3.benchmarks.datasets.negation._authoring import (  # noqa: E402
    build_negation as build_module,
)
from knowledge_v3.benchmarks.loader import (  # noqa: E402
    SOURCE_FILES,
    available_splits,
    contract_documents,
    load_gold,
)

SPLIT = "negation"

#: La tabla de docs/v3/18 §3, copiada A MANO aqui. Si el dataset cambia su
#: reparto, el que falla es el dataset: la cuota vive en el documento, no en el
#: fichero que se esta comprobando.
QUOTA = {
    "SIMPLE": 10,
    "NEVER": 6,
    "CESSATION": 10,
    "NEGATED_CESSATION": 8,
    "NOT_YET": 5,
    "SCOPE_EMBEDDED": 5,
    "QUESTION_CONDITIONAL_RUMOR": 4,
    "DOUBLE_NEGATION": 2,
}
EXTRA_QUOTA = {"POSITIVE_CONTROL": 6, "NO_CLAIM": 4}
POLICY_DECISIONS = {
    "AUTO_APPROVE",
    "REVIEW_NEGATION_CESSATION",
    "REVIEW_NEGATION_SCOPE",
    "ABSTAIN",
    "NO_DECISION",
}
SYMMETRIC = {"ALLY_OF", "RIVAL_OF", "SIBLING_OF"}


@pytest.fixture(scope="module")
def gold():
    return load_gold(SPLIT)


@pytest.fixture(scope="module")
def annotations(gold):
    """Anotacion de negacion de cada claim, indexada por claim_id."""
    return {c["claim_id"]: c["metadata"]["negation"] for c in gold.claims}


# --------------------------------------------------------------------------
# 1. Carga con el loader real y contratos congelados
# --------------------------------------------------------------------------
def test_la_bateria_carga_con_el_loader_real(gold):
    assert gold.split == SPLIT
    assert [s.source_id for s in gold.sources] == [s["source_id"] for s in K.SOURCES]
    assert SPLIT in available_splits()
    for src in gold.sources:
        for name in SOURCE_FILES:
            assert (
                build_module.ROOT / "sources" / src.source_id / f"{name}.json"
            ).exists(), f"{src.source_id}/{name}.json"


def test_todo_el_gold_valida_contra_los_contratos_congelados(gold):
    docs = contract_documents(gold)
    assert len(docs) > 500, "la bateria perdio documentos"
    for doc in docs:
        validate_document(doc)


def test_doble_marca_de_split(gold):
    for doc in contract_documents(gold):
        assert doc["metadata"]["benchmark"]["split"] == SPLIT, doc.get("contract_id")
    for neg in gold.negatives:
        assert neg["split"] == SPLIT


def test_el_gold_se_regenera_byte_a_byte():
    assert build_module.build(check=True) == 0, (
        "el dataset en disco no coincide con lo que produce su generador: "
        "alguien edito el JSON a mano"
    )


# --------------------------------------------------------------------------
# 2. La distribucion cuadra con la tabla
# --------------------------------------------------------------------------
def test_la_distribucion_por_familia_cuadra_con_la_tabla():
    counts: dict[str, int] = {}
    for case in K.CASES:
        counts[case["family"]] = counts.get(case["family"], 0) + 1
    for family, expected in QUOTA.items():
        assert counts.get(family) == expected, f"{family}: {counts.get(family)} != {expected}"
    assert sum(QUOTA[f] for f in QUOTA) == 50
    assert sum(counts[f] for f in QUOTA) == 50


def test_los_anadidos_van_aparte_de_los_cincuenta():
    counts: dict[str, int] = {}
    for case in K.CASES:
        counts[case["family"]] = counts.get(case["family"], 0) + 1
    for family, expected in EXTRA_QUOTA.items():
        assert counts.get(family) == expected
    assert len(K.CASES) == 50 + sum(EXTRA_QUOTA.values()) == 60
    assert set(counts) == set(QUOTA) | set(EXTRA_QUOTA)


def test_los_identificadores_de_caso_son_unicos():
    ids = [c["id"] for c in K.CASES]
    assert len(ids) == len(set(ids))


def test_la_distribucion_del_manifiesto_coincide_con_los_casos(gold):
    counts: dict[str, int] = {}
    for case in K.CASES:
        counts[case["family"]] = counts.get(case["family"], 0) + 1
    assert gold.manifest["family_counts"] == counts
    assert gold.manifest["family_quota"] == {**QUOTA, **EXTRA_QUOTA}


# --------------------------------------------------------------------------
# 3. Cada caso declara lo que la politica necesita
# --------------------------------------------------------------------------
def test_cada_caso_declara_una_decision_de_la_politica():
    for case in K.CASES:
        assert case["decision"] in POLICY_DECISIONS, case["id"]
        assert case["scope"] in ("UNAMBIGUOUS", "AMBIGUOUS", "NOT_APPLICABLE"), case["id"]
        assert case["kind"] in K.NEGATION_KINDS, case["id"]
        assert case["rationale"].strip(), case["id"]


def test_solo_los_casos_sin_claim_carecen_de_decision():
    for case in K.CASES:
        sin_decision = case["decision"] == "NO_DECISION"
        assert sin_decision == (case["family"] == "NO_CLAIM"), case["id"]


def test_cada_claim_declara_sujeto_objeto_predicado_y_cita(gold, annotations):
    for claim in gold.claims:
        ann = annotations[claim["claim_id"]]
        assert ann["case_id"]
        assert ann["anchor_quote"]
        if claim["abstained"]:
            assert ann["expected_predicate"] is None
            continue
        assert ann["expected_subject"] and ann["expected_object"]
        assert ann["expected_predicate"] in {p["predicate"] for p in build_module.ONTOLOGY}
        assert ann["expected_direction"] in (
            "SUBJECT_TO_OBJECT", "OBJECT_TO_SUBJECT", "UNDIRECTED",
        )
        assert isinstance(ann["expected_negated"], bool)
        assert ann["expected_negated"] == claim["negated"]


def test_la_decision_del_plan_coincide_con_la_decision_esperada(gold, annotations):
    contract_of = {d["claim_id"]: d for d in gold.decisions}
    assert set(contract_of) == {c["claim_id"] for c in gold.claims}
    for claim in gold.claims:
        ann = annotations[claim["claim_id"]]
        esperado, razones = K.DECISION_CONTRACT[ann["expected_decision"]]
        decision = contract_of[claim["claim_id"]]
        assert decision["decision"] == esperado, claim["claim_id"]
        assert set(razones) <= set(decision["reason_codes"]), claim["claim_id"]


def test_ninguna_negacion_de_cesacion_se_aprueba_ni_se_lee_como_cesacion(annotations):
    """'no dejo de X' NUNCA puede convertirse en 'dejo de X' (docs/v3/18 §4)."""
    vistos = 0
    for ann in annotations.values():
        if ann["family"] != "NEGATED_CESSATION":
            continue
        vistos += 1
        assert ann["expected_decision"] == "REVIEW_NEGATION_SCOPE", ann["case_id"]
        assert ann["negation_kind"] == "NEGATED_CESSATION"
        assert ann["expected_negated"] is False, ann["case_id"]
        assert "CESSATION" in ann["forbidden_outcomes"], ann["case_id"]
        assert "CLOSE_ASSERTION" in ann["forbidden_outcomes"], ann["case_id"]
    assert vistos == QUOTA["NEGATED_CESSATION"]


def test_todas_las_cesaciones_van_a_revision_de_cesacion(annotations):
    familias = [a for a in annotations.values() if a["family"] == "CESSATION"]
    assert len(familias) == QUOTA["CESSATION"]
    for ann in familias:
        assert ann["expected_decision"] == "REVIEW_NEGATION_CESSATION", ann["case_id"]
        assert ann["expected_negated"] is True


def test_los_never_declaran_hasta_cuando_sabe_la_fuente(gold, annotations):
    """Un 'nunca' sin horizonte es una afirmacion sobre el futuro (docs/v3/18 §2)."""
    never = [a for a in annotations.values() if a["family"] == "NEVER"]
    assert len(never) == QUOTA["NEVER"]
    for ann in never:
        assert ann["knowledge_horizon"], ann["case_id"]
    for assertion in gold.assertions:
        horizon = assertion["metadata"]["negation"]["knowledge_horizon"]
        if assertion["metadata"]["negation"]["family"] == "NEVER":
            assert assertion["valid_to"] == horizon
            assert assertion["state"] == "UNKNOWN"


def test_los_controles_positivos_no_llevan_negacion(annotations):
    positivos = [a for a in annotations.values() if a["family"] == "POSITIVE_CONTROL"]
    assert len(positivos) == EXTRA_QUOTA["POSITIVE_CONTROL"]
    for ann in positivos:
        assert ann["negation_kind"] == "NONE", ann["case_id"]
        assert ann["expected_negated"] is False, ann["case_id"]
        assert ann["expected_decision"] == "AUTO_APPROVE", ann["case_id"]


def test_los_casos_sin_claim_no_producen_ningun_claim(gold):
    sin_claim = [c for c in K.CASES if c["family"] == "NO_CLAIM"]
    assert len(sin_claim) == EXTRA_QUOTA["NO_CLAIM"]
    assert len(gold.negatives) == EXTRA_QUOTA["NO_CLAIM"]
    episodios_negativos = {n["episode_id"] for n in gold.negatives}
    for claim in gold.claims:
        assert claim["episode_id"] not in episodios_negativos, (
            f"{claim['claim_id']} pisa una trampa del propio gold"
        )
    for neg in gold.negatives:
        assert neg["must_not_produce"] == "claim"
        assert neg["forbidden_predicates"]
        assert neg["rationale"].strip()


# --------------------------------------------------------------------------
# 4. Sin claves de hecho duplicadas
# --------------------------------------------------------------------------
def _fact_key(doc: dict) -> tuple:
    a, b, direction = doc["subject_entity_id"], doc["object_entity_id"], doc["direction"]
    if doc["predicate"] in SYMMETRIC:
        a, b = sorted([a, b])
        direction = "UNDIRECTED"
    return (a, doc["predicate"], b, direction, doc["negated"])


def test_no_hay_claves_de_hecho_duplicadas(gold):
    keys = [_fact_key(a) for a in gold.assertions]
    duplicadas = {k for k in keys if keys.count(k) > 1}
    assert not duplicadas, f"claves de hecho repetidas: {sorted(duplicadas)}"
    assert len(keys) == len(gold.assertions) > 0


def test_solo_lo_autoaprobable_llega_a_afirmacion(gold, annotations):
    por_caso = {a["metadata"]["negation"]["case_id"] for a in gold.assertions}
    for case in K.CASES:
        if case["decision"] == "AUTO_APPROVE":
            assert case["id"] in por_caso, case["id"]
        else:
            assert case["id"] not in por_caso, case["id"]


def test_ningun_plan_de_la_bateria_esta_aprobado(gold):
    for plan in gold.plans:
        assert plan["local_approval"]["approved"] is False, plan["plan_id"]


# --------------------------------------------------------------------------
# 5. Anclaje literal: la cita esta donde dice que esta
# --------------------------------------------------------------------------
def test_toda_evidencia_esta_anclada_literalmente(gold):
    textos = {e["episode_id"]: e["text"] for e in gold.episodes}
    for frag in gold.fragments:
        texto = textos[frag["episode_id"]]
        assert texto[frag["start"]:frag["end"]] == frag["literal_text"], frag["fragment_id"]


def test_la_cita_que_ancla_cada_claim_es_su_evidencia(gold, annotations):
    frags = {f["fragment_id"]: f for f in gold.fragments}
    for claim in gold.claims:
        ann = annotations[claim["claim_id"]]
        anclas = [frags[f]["literal_text"] for f in claim["evidence_fragment_ids"]]
        assert ann["anchor_quote"] in anclas, claim["claim_id"]


def test_sujeto_y_objeto_aparecen_en_el_texto(gold):
    menciones = {m["mention_id"]: m for m in gold.mentions}
    textos = {e["episode_id"]: e["text"] for e in gold.episodes}
    for claim in gold.claims:
        for mid in claim["subject_mentions"] + claim["object_mentions"]:
            m = menciones[mid]
            assert m["surface"] in textos[m["episode_id"]], mid


def test_las_menciones_estan_resueltas_a_entidades_del_catalogo(gold):
    catalogo = gold.catalog_entity_ids
    resueltas = gold.mention_to_entity()
    for mention in gold.mentions:
        entidad = resueltas.get(mention["mention_id"])
        assert entidad is not None, mention["mention_id"]
        assert entidad in catalogo, entidad


# --------------------------------------------------------------------------
# 6. Variedad exigida
# --------------------------------------------------------------------------
def test_se_usan_los_diez_predicados_de_la_ontologia_generica(gold):
    usados = {
        c["metadata"]["negation"]["expected_predicate"]
        for c in gold.claims
        if not c["abstained"]
    }
    todos = {p["predicate"] for p in build_module.ONTOLOGY}
    assert len(todos) == 10
    assert usados == todos, f"predicados sin usar: {sorted(todos - usados)}"


def test_hay_casos_con_errores_de_transcripcion_realistas():
    ruidosos = [c for c in K.CASES if c["noise"] in ("OCR", "ASR")]
    assert len(ruidosos) >= 5, len(ruidosos)
    assert {c["noise"] for c in ruidosos} == {"OCR", "ASR"}


def test_hay_negaciones_antes_y_despues_del_foco():
    posiciones = {c["cue_position"] for c in K.CASES}
    assert {"BEFORE_FOCUS", "AFTER_FOCUS", "BETWEEN_ARGUMENTS"} <= posiciones


def test_hay_voz_pasiva_y_formas_verbales_variadas():
    assert len([c for c in K.CASES if c["voice"] == "PASSIVE"]) >= 5
    formas = {c["verb_form"] for c in K.CASES}
    assert len(formas) >= 8, sorted(formas)
    assert any("SUBJUNTIVO" in f for f in formas)
    assert any("INFINITIVO" in f for f in formas)
    assert any("PERIFRASIS" in f or "PERFECTO" in f for f in formas)


def test_los_mundos_son_nuevos(gold):
    prohibidos = {"leyenda", "mareas", "kestrel", "ferrovia", "micelio", "liga"}
    mundos = {s.world for s in gold.sources}
    assert not (mundos & prohibidos), mundos
    assert len(mundos) >= 3


def test_los_casos_no_son_variaciones_del_mismo_esqueleto():
    """Ningun texto se repite y ningun par (sujeto, objeto, predicado) se repite."""
    textos = [c["text"] for c in K.CASES]
    assert len(textos) == len(set(textos))
    tripletas = [
        (cl["subject"][1], cl["predicate"], cl["object"][1])
        for c in K.CASES
        for cl in c["claims"]
    ]
    repetidas = {t for t in tripletas if tripletas.count(t) > 1}
    assert not repetidas, f"tripletas repetidas: {sorted(repetidas)}"
    longitudes = [len(t) for t in textos]
    assert min(longitudes) < 60 and max(longitudes) > 200, (min(longitudes), max(longitudes))


# --------------------------------------------------------------------------
# 7. La bateria NO esta conectada a ningun flujo automatico
# --------------------------------------------------------------------------
#: Formas en que un modulo cargaria, mediria o instalaria este split. La palabra
#: "negation" suelta no cuenta: aparece por todas partes como nombre de fenomeno.
_ENCHUFE = re.compile(
    r"""load_gold\(\s*["']negation["']"""
    r"""|SPLIT\s*=\s*["']negation["']"""
    r"""|split\s*=\s*["']negation["']"""
    r"""|["']split["']\s*:\s*["']negation["']"""
    r"""|--split\s+negation"""
    r"""|datasets[./]negation"""
)


def test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico():
    repo = Path(__file__).resolve().parents[3]
    propio = {Path(__file__).resolve()}
    culpables = []
    for carpeta in ("data-engine", "scripts", "deploy", "shared", "tests"):
        base = repo / carpeta
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.resolve() in propio or "datasets/negation" in path.as_posix():
                continue
            if _ENCHUFE.search(path.read_text(encoding="utf-8")):
                culpables.append(path.relative_to(repo).as_posix())
    assert not culpables, (
        "algo fuera de la bateria carga o mide el split 'negation': la bateria es "
        f"gold, no un paso de pipeline: {culpables}"
    )
