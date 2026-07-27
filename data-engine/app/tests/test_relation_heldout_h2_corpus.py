# -*- coding: utf-8 -*-
"""Integridad y sellado del corpus held-out H2 (material REAL).

H2 se construye a partir de obra con DERECHOS DE AUTOR y de una grabacion con voces
reales. Estos tests comprueban, ademas de la integridad habitual, la POLITICA LEGAL:
solo citas cortas, nada de PDF/audio/transcripcion completa, sin rutas al material
original y sin datos personales.

NO tocan B1 ni H1 y NO ejecutan el pipeline.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import jsonschema
import pytest

CORPUS = Path(__file__).resolve().parent / "data" / "relation_heldout_h2"
H1 = Path(__file__).resolve().parent / "data" / "relation_heldout"
B1 = Path(__file__).resolve().parent / "data" / "relation_benchmark"

MAX_FRAGMENT_CHARS = 400
EXPECTED_SEED = 20260727


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ground_truth() -> dict:
    return json.loads((CORPUS / "ground_truth" / "relations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases() -> dict:
    return json.loads((CORPUS / "cases" / "cases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seal() -> dict:
    return json.loads((CORPUS / "SEAL.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Esquemas
# --------------------------------------------------------------------------
def test_manifest_valida_contra_su_esquema(manifest):
    schema = json.loads((CORPUS / "schemas" / "manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)


def test_ground_truth_valida_contra_su_esquema(ground_truth):
    schema = json.loads(
        (CORPUS / "schemas" / "ground_truth.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(ground_truth, schema)


# --------------------------------------------------------------------------
# Sellado
# --------------------------------------------------------------------------
def test_hashes_de_fuentes_coinciden_con_el_manifiesto(manifest):
    for src in manifest["sources"]:
        text = (CORPUS / src["path"]).read_text(encoding="utf-8")
        assert _sha(text) == src["sha256"], f"{src['id']}: hash distinto del manifiesto"
        assert len(text) == src["chars"]
        assert len(text.encode("utf-8")) == src["bytes"]


def test_sello_coincide_con_manifiesto_ground_truth_y_casos(manifest, seal):
    man_txt = (CORPUS / "manifest.json").read_text(encoding="utf-8")
    gt_txt = (CORPUS / "ground_truth" / "relations.json").read_text(encoding="utf-8")
    cases_txt = (CORPUS / "cases" / "cases.json").read_text(encoding="utf-8")
    assert seal["manifest_sha256"] == _sha(man_txt)
    assert seal["ground_truth_sha256"] == _sha(gt_txt)
    assert seal["cases_sha256"] == _sha(cases_txt)
    assert manifest["ground_truth"]["sha256"] == _sha(gt_txt)
    assert manifest["cases"]["sha256"] == _sha(cases_txt)
    assert seal["sources_sha256"] == {s["id"]: s["sha256"] for s in manifest["sources"]}


def test_recuentos_declarados_son_ciertos(manifest, ground_truth):
    assert manifest["source_count"] == len(manifest["sources"]) == 36
    assert manifest["relation_count"] == len(ground_truth["relations"]) == 52
    assert manifest["sampling_seed"] == EXPECTED_SEED
    assert manifest["synthetic"] is False
    assert manifest["contains_private_corpus"] is False


# --------------------------------------------------------------------------
# POLITICA LEGAL Y DE PRIVACIDAD
# --------------------------------------------------------------------------
def test_solo_hay_citas_cortas_ningun_fragmento_supera_el_limite(manifest):
    for src in manifest["sources"]:
        assert src["chars"] <= MAX_FRAGMENT_CHARS, (
            f"{src['id']} tiene {src['chars']} caracteres: supera el limite de cita corta")


def test_el_corpus_entero_es_una_fraccion_minima_del_material(manifest):
    total = sum(s["chars"] for s in manifest["sources"])
    assert total < 20000, f"{total} caracteres citados: demasiado material en el repositorio"


def test_no_hay_pdf_audio_ni_transcripciones_completas():
    prohibidos = {".pdf", ".m4a", ".mp3", ".mp4", ".wav", ".vtt", ".srt"}
    for path in CORPUS.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in prohibidos, f"fichero prohibido en el repo: {path}"


def test_no_hay_rutas_al_material_original_ni_absolutas():
    patron = re.compile(r"(/home/|/mnt/|/media/|C:\\\\|nextcloud|s9k-corpus-real)", re.I)
    for path in CORPUS.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".txt", ".md", ".py"}:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                assert not patron.search(line), f"{path}:{n} filtra una ruta al material"


def test_la_procedencia_no_incluye_ficheros_solo_obra_y_pagina(manifest):
    for src in manifest["sources"]:
        prov = src["provenance"]
        assert set(prov) == {"work", "page", "window_start_sentence", "window_sentences"}
        assert "/" not in prov["work"] and "." not in prov["work"]


# --------------------------------------------------------------------------
# Coherencia del ground truth
# --------------------------------------------------------------------------
def test_offsets_de_evidencia_son_exactos(manifest, ground_truth):
    texts = {s["id"]: (CORPUS / s["path"]).read_text(encoding="utf-8") for s in manifest["sources"]}
    for rel in ground_truth["relations"]:
        text = texts[rel["source_id"]]
        assert 0 <= rel["evidence_start"] < rel["evidence_end"] <= len(text)
        assert text[rel["evidence_start"]:rel["evidence_end"]] == rel["evidence_text"], (
            f"{rel['relation_id']}: la evidencia no coincide con los offsets")


def test_menciones_aparecen_literalmente_en_su_fuente(manifest, ground_truth):
    texts = {s["id"]: (CORPUS / s["path"]).read_text(encoding="utf-8") for s in manifest["sources"]}
    for rel in ground_truth["relations"]:
        text = texts[rel["source_id"]]
        assert rel["subject_text"] in text, f"{rel['relation_id']}: sujeto no literal"
        assert rel["object_text"] in text, f"{rel['relation_id']}: objeto no literal"


def test_workspace_de_cada_relacion_es_el_de_su_fuente(manifest, ground_truth):
    ws = {s["id"]: s["workspace"] for s in manifest["sources"]}
    for rel in ground_truth["relations"]:
        assert rel["workspace"] == ws[rel["source_id"]]


def test_ids_de_relacion_unicos_y_correlativos(ground_truth):
    ids = [r["relation_id"] for r in ground_truth["relations"]]
    assert len(set(ids)) == len(ids)
    assert ids == [f"rel-{i:03d}" for i in range(1, len(ids) + 1)]


def test_toda_relacion_tiene_nota_de_anotador(ground_truth):
    for rel in ground_truth["relations"]:
        assert len(rel["annotator_notes"].strip()) >= 20, rel["relation_id"]


def test_el_ground_truth_declara_la_anotacion_de_un_solo_pase(ground_truth):
    desc = ground_truth["description"].upper()
    assert "UN SOLO PASE" in desc


def test_hay_centinelas_de_ruido_y_relaciones_negadas(ground_truth):
    rels = ground_truth["relations"]
    assert sum(1 for r in rels if r["predicate"] == "NO_RELATION") == 3
    assert sum(1 for r in rels if r["negated"]) >= 1
    assert sum(1 for r in rels if r["epistemic_status"] == "RUMORED") >= 2


def test_toda_fuente_tiene_al_menos_una_relacion(manifest, ground_truth):
    con_rel = {r["source_id"] for r in ground_truth["relations"]}
    assert con_rel == {s["id"] for s in manifest["sources"]}


# --------------------------------------------------------------------------
# Casos
# --------------------------------------------------------------------------
def test_los_casos_cubren_todas_las_fuentes_y_relaciones(manifest, ground_truth, cases):
    srcs, rels = set(), set()
    for case in cases["cases"]:
        srcs.update(case["sources"])
        rels.update(case["relations"])
        assert case["coverage"], case["case_id"]
    assert srcs == {s["id"] for s in manifest["sources"]}
    assert rels == {r["relation_id"] for r in ground_truth["relations"]}


def test_la_transcripcion_aporta_sus_etiquetas_de_habla(cases):
    habla = [c for c in cases["cases"] if "habla-sin-puntuacion" in c["coverage"]]
    assert len(habla) >= 8, "el corpus debe cubrir habla sin puntuacion"


# --------------------------------------------------------------------------
# Disyuncion con B1 y H1: H2 no puede contaminar ni ser contaminado
# --------------------------------------------------------------------------
def _corpus_ids(root: Path) -> tuple[set, set]:
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    gt = json.loads((root / man["ground_truth"]["path"]).read_text(encoding="utf-8"))
    ent = set()
    for rel in gt["relations"]:
        ent.add(rel["subject_id"])
        ent.add(rel["object_id"])
    return {s["workspace"] for s in man["sources"]}, ent


def test_h2_no_comparte_workspaces_ni_entidades_con_b1_ni_h1():
    ws2, ent2 = _corpus_ids(CORPUS)
    for otro in (B1, H1):
        ws, ent = _corpus_ids(otro)
        assert not (ws2 & ws), f"workspace compartido con {otro.name}: {ws2 & ws}"
        assert not (ent2 & ent), f"entidad compartida con {otro.name}: {ent2 & ent}"


def test_b1_y_h1_no_se_han_tocado():
    for otro in (B1, H1):
        man = json.loads((otro / "manifest.json").read_text(encoding="utf-8"))
        for src in man["sources"]:
            text = (otro / src["path"]).read_text(encoding="utf-8")
            assert _sha(text) == src["sha256"], f"{otro.name}/{src['id']} ha cambiado"


# --------------------------------------------------------------------------
# Higiene del texto citado
# --------------------------------------------------------------------------
def test_no_hay_caracteres_de_control_ni_unicode_oculto(manifest):
    for src in manifest["sources"]:
        text = (CORPUS / src["path"]).read_text(encoding="utf-8")
        for ch in text:
            assert unicodedata.category(ch) not in {"Cc", "Cf", "Co", "Cs"}, (
                f"{src['id']}: caracter de control u oculto U+{ord(ch):04X}")


def test_las_fuentes_no_contienen_secretos_ni_urls():
    patron = re.compile(r"(https?://|api[_-]?key|password|token\s*=)", re.I)
    for path in sorted((CORPUS / "sources").glob("*.txt")):
        assert not patron.search(path.read_text(encoding="utf-8")), path.name
