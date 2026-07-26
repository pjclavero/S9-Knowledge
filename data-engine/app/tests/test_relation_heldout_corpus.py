# -*- coding: utf-8 -*-
"""Test de integridad y de SELLADO del corpus HELD-OUT de relaciones (H1).

Verifica que el corpus bajo ``app/tests/data/relation_heldout/`` es
autoconsistente, compatible con el arnes unico ``relations/benchmark/`` y que
**no esta contaminado** por el corpus de desarrollo B1:

  * manifest y ground truth validos contra sus JSON Schema;
  * hashes sha256 recalculados == manifest == ``SEAL.json`` (prueba de sellado);
  * offsets exactos: ``evidence_text == source_text[start:end]``;
  * IDs unicos, workspaces presentes, tipos y enums admitidos;
  * **DISYUNCION con B1**: ni un id de entidad, ni un texto de mencion, ni un
    token de mas de 3 caracteres, ni un workspace en comun;
  * cobertura declarada de los 24 casos y presencia de los centinelas;
  * el corpus B1 NO se toca: solo se lee para comprobar la disyuncion;
  * ausencia de Unicode oculto (bidi / zero-width / BOM), de secretos y de rutas
    absolutas.

No llama a Ollama, NVIDIA, Neo4j ni a ningun servicio: solo lee ficheros del repo.
Ver ``docs/relation-engine-v2e/HELDOUT_POLICY.md``.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from relations.contracts import (  # noqa: E402
    ALLOWED_ENTITY_TYPES,
    Direction,
    EpistemicStatus,
    normalize_predicate,
)

jsonschema = pytest.importorskip("jsonschema")

CORPUS_DIR = _APP_DIR / "tests" / "data" / "relation_heldout"
B1_DIR = _APP_DIR / "tests" / "data" / "relation_benchmark"

# Centinelas documentados en el README del corpus: NO son predicados de la
# ontologia y su acierto es imposible POR CONSTRUCCION (es intencionado).
SENTINEL_PREDICATES = {"NO_RELATION", "SPONSORS"}

_FORBIDDEN_INVISIBLE = (
    set(range(0x200B, 0x2010))
    | set(range(0x202A, 0x2030))
    | set(range(0x2060, 0x2070))
    | set(range(0x2066, 0x206A))
    | {0xFEFF, 0x00AD, 0x061C, 0x180E}
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ground_truth() -> dict:
    return json.loads((CORPUS_DIR / "ground_truth" / "relations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases() -> dict:
    return json.loads((CORPUS_DIR / "cases" / "cases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seal() -> dict:
    return json.loads((CORPUS_DIR / "SEAL.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def source_texts(manifest) -> dict:
    return {s["id"]: (CORPUS_DIR / s["path"]).read_text(encoding="utf-8")
            for s in manifest["sources"]}


# ---------------------------------------------------------------------------
# Estructura y esquemas
# ---------------------------------------------------------------------------
def test_layout():
    for rel in ("manifest.json", "SEAL.json", "README.md",
                "ground_truth/relations.json", "cases/cases.json",
                "schemas/manifest.schema.json", "schemas/ground_truth.schema.json",
                "tools/build_heldout_corpus.py"):
        assert (CORPUS_DIR / rel).exists(), rel
    assert (CORPUS_DIR / "sources").is_dir()


def test_manifest_valid_against_schema(manifest):
    schema = json.loads((CORPUS_DIR / "schemas" / "manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)


def test_ground_truth_valid_against_schema(ground_truth):
    schema = json.loads((CORPUS_DIR / "schemas" / "ground_truth.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(ground_truth, schema)


def test_manifest_counts_match(manifest, ground_truth):
    assert manifest["source_count"] == len(manifest["sources"])
    assert manifest["relation_count"] == len(ground_truth["relations"])


# ---------------------------------------------------------------------------
# SELLADO: los hashes son la prueba de no contaminacion
# ---------------------------------------------------------------------------
def test_source_hashes_match_manifest(manifest):
    for s in manifest["sources"]:
        path = CORPUS_DIR / s["path"]
        data = path.read_bytes()
        assert _sha256(path) == s["sha256"], f"{s['id']} MODIFICADO respecto al manifiesto"
        assert len(data) == s["bytes"]
        assert len(data.decode("utf-8")) == s["chars"]


def test_ground_truth_and_cases_hashes_match_manifest(manifest):
    assert _sha256(CORPUS_DIR / "ground_truth" / "relations.json") == \
        manifest["ground_truth"]["sha256"]
    assert _sha256(CORPUS_DIR / "cases" / "cases.json") == manifest["cases"]["sha256"]


def test_seal_matches_manifest(manifest, seal):
    """El SELLO debe coincidir con el corpus: si no, el held-out esta QUEMADO."""
    assert seal["corpus_version"] == manifest["version"]
    assert seal["source_count"] == manifest["source_count"]
    assert seal["relation_count"] == manifest["relation_count"]
    assert seal["ground_truth_sha256"] == manifest["ground_truth"]["sha256"]
    assert seal["cases_sha256"] == manifest["cases"]["sha256"]
    assert seal["sources_sha256"] == {s["id"]: s["sha256"] for s in manifest["sources"]}
    assert seal["manifest_sha256"] == _sha256(CORPUS_DIR / "manifest.json")


def test_seal_records_at_least_one_execution(seal):
    assert seal["executions"], "el sello debe registrar cada ejecucion del held-out"
    for ex in seal["executions"]:
        for key in ("date", "checkpoint", "engine_code_sha", "profiles", "providers"):
            assert ex.get(key), key
        assert "NOT_EXECUTED" in ex["providers"]


# ---------------------------------------------------------------------------
# Contrato de las relaciones
# ---------------------------------------------------------------------------
def test_relation_and_source_ids_unique(manifest, ground_truth):
    sids = [s["id"] for s in manifest["sources"]]
    assert len(sids) == len(set(sids))
    rids = [r["relation_id"] for r in ground_truth["relations"]]
    assert len(rids) == len(set(rids))


def test_relations_point_to_existing_sources(manifest, ground_truth):
    known = {s["id"]: s["workspace"] for s in manifest["sources"]}
    for r in ground_truth["relations"]:
        assert r["source_id"] in known
        assert r["workspace"] == known[r["source_id"]]
        assert r["segment_id"].startswith(r["source_id"])


def test_offsets_match_source_exactly(ground_truth, source_texts):
    for r in ground_truth["relations"]:
        text = source_texts[r["source_id"]]
        start, end = r["evidence_start"], r["evidence_end"]
        assert 0 <= start < end <= len(text), r["relation_id"]
        assert text[start:end] == r["evidence_text"], r["relation_id"]


def test_mentions_present_in_source(ground_truth, source_texts):
    for r in ground_truth["relations"]:
        text = source_texts[r["source_id"]]
        assert r["subject_text"] in text, r["relation_id"]
        assert r["object_text"] in text, r["relation_id"]


def test_types_and_enums(ground_truth):
    for r in ground_truth["relations"]:
        assert r["subject_type"] in ALLOWED_ENTITY_TYPES
        assert r["object_type"] in ALLOWED_ENTITY_TYPES
        assert r["direction"] in {d.value for d in Direction}
        assert r["epistemic_status"] in {e.value for e in EpistemicStatus}
        assert r["temporal_status"] in ground_truth["temporal_status_values"]
        assert r["expected_decision"] in ground_truth["expected_decision_values"]
        assert normalize_predicate(r["predicate"]) == r["predicate"]
        assert r["annotator_notes"].strip(), r["relation_id"]


def test_sentinels_are_declared_and_bounded(ground_truth):
    """Los centinelas son inacertables por construccion: deben ser POCOS y estar acotados."""
    sentinels = [r for r in ground_truth["relations"]
                 if r["predicate"] in SENTINEL_PREDICATES]
    assert sentinels, "el corpus debe contener casos de ruido y de predicado desconocido"
    assert len(sentinels) <= 6, "demasiadas filas inacertables: falsearian predicate_correct"
    for r in sentinels:
        if r["predicate"] == "NO_RELATION":
            assert r["expected_decision"] == "REJECT"


# ---------------------------------------------------------------------------
# DISYUNCION con el corpus de desarrollo B1
# ---------------------------------------------------------------------------
def _entity_universe(gt: dict) -> tuple[set, set]:
    ids, texts = set(), set()
    for r in gt["relations"]:
        ids |= {r["subject_id"], r["object_id"]}
        texts |= {r["subject_text"], r["object_text"]}
    return ids, texts


@pytest.fixture(scope="module")
def b1_ground_truth() -> dict:
    return json.loads((B1_DIR / "ground_truth" / "relations.json").read_text(encoding="utf-8"))


def test_no_entity_overlap_with_b1(ground_truth, b1_ground_truth):
    ids_h, texts_h = _entity_universe(ground_truth)
    ids_b, texts_b = _entity_universe(b1_ground_truth)
    assert not (ids_h & ids_b), f"ids compartidos con B1: {sorted(ids_h & ids_b)}"
    assert not (texts_h & texts_b), f"menciones compartidas con B1: {sorted(texts_h & texts_b)}"


def test_no_name_token_overlap_with_b1(ground_truth, b1_ground_truth):
    def toks(texts):
        return {w.lower() for w in re.findall(r"\w+", " ".join(texts)) if len(w) > 3}
    _, th = _entity_universe(ground_truth)
    _, tb = _entity_universe(b1_ground_truth)
    shared = toks(th) & toks(tb)
    assert not shared, f"tokens de nombre compartidos con B1: {sorted(shared)}"


def test_no_workspace_overlap_with_b1(manifest):
    b1_manifest = json.loads((B1_DIR / "manifest.json").read_text(encoding="utf-8"))
    shared = set(manifest["workspaces"]) & set(b1_manifest["workspaces"])
    assert not shared, f"workspaces compartidos con B1: {sorted(shared)}"


# ---------------------------------------------------------------------------
# Cobertura de casos
# ---------------------------------------------------------------------------
REQUIRED_COVERAGE = {
    "voz-activa", "voz-pasiva", "sujeto-objeto-invertidos", "simetrica",
    "frases-largas", "varias-relaciones-por-segmento", "entidades-repetidas",
    "negacion", "rumor", "hipotesis", "transicion-temporal", "fecha-vaga",
    "relacion-que-cambia", "fuentes-contradictorias", "ruido", "unicode",
    "puntuacion", "texto-repetido", "fragmento-ambiguo", "alianza-terminada",
    "culpable-exonerado", "fuera-de-ficcion", "escena-multi-sesion",
    "salto-temporal", "flashback", "dos-fuentes", "fuente-retirada",
    "homonimia", "multi-workspace", "predicado-desconocido",
    "descubrimiento-posterior", "predicados-no-vistos",
}


def test_all_required_coverage_tags_present(cases):
    seen = set()
    for c in cases["cases"]:
        seen |= set(c["coverage"])
    missing = REQUIRED_COVERAGE - seen
    assert not missing, f"cobertura declarada incompleta: {sorted(missing)}"


def test_cases_reference_existing_relations_and_sources(cases, ground_truth, manifest):
    known_rel = {r["relation_id"] for r in ground_truth["relations"]}
    known_src = {s["id"] for s in manifest["sources"]}
    covered: set = set()
    for c in cases["cases"]:
        assert c["relations"], c["case_id"]
        assert c["episodes"], c["case_id"]
        for rid in c["relations"]:
            assert rid in known_rel, rid
        for sid in c["sources"]:
            assert sid in known_src, sid
        covered |= set(c["relations"])
    assert covered == known_rel, "toda relacion debe pertenecer a un caso"


def test_every_source_belongs_to_a_case(cases, manifest):
    used = {sid for c in cases["cases"] for sid in c["sources"]}
    assert used == {s["id"] for s in manifest["sources"]}


# ---------------------------------------------------------------------------
# Higiene: sintetico, sin secretos, sin Unicode oculto
# ---------------------------------------------------------------------------
def test_declared_synthetic(manifest):
    assert manifest["synthetic"] is True
    assert manifest["contains_private_corpus"] is False
    assert manifest["corpus_role"] == "held-out"


def test_no_hidden_unicode(source_texts, ground_truth):
    for sid, text in source_texts.items():
        bad = sorted({hex(ord(c)) for c in text
                      if ord(c) in _FORBIDDEN_INVISIBLE or unicodedata.category(c) == "Cf"})
        assert not bad, f"Unicode oculto en {sid}: {bad}"
    for r in ground_truth["relations"]:
        bad = sorted({hex(ord(c)) for c in r["evidence_text"]
                      if ord(c) in _FORBIDDEN_INVISIBLE or unicodedata.category(c) == "Cf"})
        assert not bad, f"Unicode oculto en {r['relation_id']}: {bad}"


def test_no_secrets_or_absolute_paths(source_texts):
    patterns = (r"/home/", r"/mnt/", r"[A-Za-z]:\\", r"(?i)password", r"(?i)api[_-]?key",
                r"(?i)secret", r"(?i)token\s*[:=]", r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    for sid, text in source_texts.items():
        for pat in patterns:
            assert not re.search(pat, text), f"{sid} contiene patron prohibido {pat}"
