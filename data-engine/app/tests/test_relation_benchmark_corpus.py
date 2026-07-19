# -*- coding: utf-8 -*-
"""Test de integridad del corpus sintetico de benchmark de relaciones.

Verifica que el corpus bajo ``app/tests/data/relation_benchmark/`` es
autoconsistente y compatible con el contrato interno de relaciones:

  * manifest valido contra su JSON Schema; ground_truth valido contra el suyo;
  * hashes sha256 de las fuentes correctos (recalculados == manifest);
  * offsets correctos: evidence_text == source_text[start:end] EXACTO;
  * source IDs unicos; segment IDs presentes; relation IDs unicos;
  * workspace presente en cada relacion;
  * predicados normalizados (normalize_predicate) y tipos en ALLOWED_ENTITY_TYPES;
  * evidencia contenida literalmente en la fuente correspondiente;
  * ausencia de Unicode oculto (bidi / zero-width / BOM);
  * cero corpus privado: todo declarado sintetico/ficticio.

No llama a Ollama, NVIDIA, Neo4j ni a ningun servicio: solo lee ficheros del repo.
"""
from __future__ import annotations

import hashlib
import json
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
    RelationCandidate,
    normalize_predicate,
)

jsonschema = pytest.importorskip("jsonschema")

CORPUS_DIR = _APP_DIR / "tests" / "data" / "relation_benchmark"

# Codepoints de formato invisible prohibidos (no justificados): bidi, zero-width,
# BOM, joiners/isolates. Se admiten solo caracteres visibles (incl. CJK/runas).
_FORBIDDEN_INVISIBLE = (
    set(range(0x200B, 0x2010))  # zero-width space..hyphen family
    | set(range(0x202A, 0x2030))  # bidi embeddings/overrides
    | set(range(0x2060, 0x2070))  # word joiner / invisible ops
    | set(range(0x2066, 0x206A))  # bidi isolates
    | {0xFEFF, 0x00AD, 0x061C, 0x180E}
)


def _assert_no_hidden_unicode(text: str, where: str) -> None:
    bad = sorted({hex(ord(c)) for c in text
                  if ord(c) in _FORBIDDEN_INVISIBLE
                  or unicodedata.category(c) == "Cf"})
    assert not bad, f"Unicode oculto/no justificado en {where}: {bad}"


# ---------------------------------------------------------------------------
# Fixtures de carga
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def manifest():
    return json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ground_truth():
    return json.loads(
        (CORPUS_DIR / "ground_truth" / "relations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest_schema():
    return json.loads(
        (CORPUS_DIR / "schemas" / "manifest.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gt_schema():
    return json.loads(
        (CORPUS_DIR / "schemas" / "ground_truth.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def source_texts(manifest):
    texts = {}
    for s in manifest["sources"]:
        p = CORPUS_DIR / s["path"]
        texts[s["id"]] = p.read_text(encoding="utf-8")
    return texts


# ---------------------------------------------------------------------------
# Estructura basica
# ---------------------------------------------------------------------------
def test_corpus_dir_layout():
    assert (CORPUS_DIR / "manifest.json").is_file()
    assert (CORPUS_DIR / "ground_truth" / "relations.json").is_file()
    assert (CORPUS_DIR / "schemas" / "manifest.schema.json").is_file()
    assert (CORPUS_DIR / "schemas" / "ground_truth.schema.json").is_file()
    assert (CORPUS_DIR / "README.md").is_file()


def test_manifest_valid_against_schema(manifest, manifest_schema):
    jsonschema.validate(instance=manifest, schema=manifest_schema)


def test_ground_truth_valid_against_schema(ground_truth, gt_schema):
    jsonschema.validate(instance=ground_truth, schema=gt_schema)


def test_source_count_between_12_and_20(manifest):
    assert 12 <= manifest["source_count"] <= 20
    assert manifest["source_count"] == len(manifest["sources"])


# ---------------------------------------------------------------------------
# Integridad de ficheros (hashes, encoding, tamano)
# ---------------------------------------------------------------------------
def test_source_hashes_match(manifest):
    for s in manifest["sources"]:
        raw = (CORPUS_DIR / s["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == s["sha256"], s["id"]
        assert len(raw) == s["bytes"], s["id"]
        # encoding utf-8 real: decodifica sin error y cuenta de chars coincide.
        text = raw.decode("utf-8")
        assert len(text) == s["chars"], s["id"]
        assert s["encoding"] == "utf-8"


def test_ground_truth_hash_matches(manifest):
    raw = (CORPUS_DIR / "ground_truth" / "relations.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["ground_truth"]["sha256"]


def test_no_absolute_paths_in_manifest(manifest):
    blob = json.dumps(manifest)
    assert "/home/" not in blob and ":\\" not in blob
    for s in manifest["sources"]:
        assert s["path"].startswith("sources/")
        assert not Path(s["path"]).is_absolute()


# ---------------------------------------------------------------------------
# Unicidad de identificadores
# ---------------------------------------------------------------------------
def test_source_ids_unique(manifest):
    ids = [s["id"] for s in manifest["sources"]]
    assert len(ids) == len(set(ids))


def test_relation_ids_unique(ground_truth):
    ids = [r["relation_id"] for r in ground_truth["relations"]]
    assert len(ids) == len(set(ids))


def test_segment_ids_present_and_unique_per_relation(ground_truth):
    for r in ground_truth["relations"]:
        assert r["segment_id"].strip(), r["relation_id"]
    # Cada relacion referencia un segmento no vacio; los IDs de segmento pueden
    # repetirse (varias relaciones por segmento), pero deben existir.
    pairs = {(r["relation_id"], r["segment_id"]) for r in ground_truth["relations"]}
    assert len(pairs) == len(ground_truth["relations"])


def test_relation_source_ids_exist(manifest, ground_truth):
    known = {s["id"] for s in manifest["sources"]}
    for r in ground_truth["relations"]:
        assert r["source_id"] in known, r["relation_id"]


# ---------------------------------------------------------------------------
# Offsets y evidencia
# ---------------------------------------------------------------------------
def test_offsets_match_source_exactly(ground_truth, source_texts):
    for r in ground_truth["relations"]:
        text = source_texts[r["source_id"]]
        start, end = r["evidence_start"], r["evidence_end"]
        assert 0 <= start <= end <= len(text), r["relation_id"]
        assert text[start:end] == r["evidence_text"], (
            f"{r['relation_id']}: {text[start:end]!r} != {r['evidence_text']!r}")


def test_evidence_contained_in_source(ground_truth, source_texts):
    for r in ground_truth["relations"]:
        assert r["evidence_text"] in source_texts[r["source_id"]], r["relation_id"]


# ---------------------------------------------------------------------------
# Compatibilidad con el contrato de relaciones
# ---------------------------------------------------------------------------
def test_workspace_present_in_every_relation(ground_truth):
    for r in ground_truth["relations"]:
        assert isinstance(r["workspace"], str) and r["workspace"].strip(), r["relation_id"]


def test_predicates_normalized(ground_truth):
    for r in ground_truth["relations"]:
        p = r["predicate"]
        assert p == normalize_predicate(p), (r["relation_id"], p)


def test_entity_types_allowed(ground_truth):
    for r in ground_truth["relations"]:
        assert r["subject_type"] in ALLOWED_ENTITY_TYPES, r["relation_id"]
        assert r["object_type"] in ALLOWED_ENTITY_TYPES, r["relation_id"]


def test_enums_valid(ground_truth):
    valid_dir = {d.value for d in Direction}
    valid_epi = {e.value for e in EpistemicStatus}
    for r in ground_truth["relations"]:
        assert r["direction"] in valid_dir, r["relation_id"]
        assert r["epistemic_status"] in valid_epi, r["relation_id"]
        assert isinstance(r["negated"], bool), r["relation_id"]


def test_each_relation_builds_valid_relation_candidate(ground_truth):
    """Cada anotacion se materializa como RelationCandidate valido del contrato.

    Confirma compatibilidad real con el modelo de datos objetivo (no solo con el
    schema del corpus). subject_id != object_id se relaja para alias reflexivos
    documentales, que el corpus marca con predicado ALIAS_OF.
    """
    for r in ground_truth["relations"]:
        if r["subject_id"] == r["object_id"]:
            # Alias/identidad documental: no es una arista del grafo; se omite la
            # construccion del candidato (el contrato prohibe subject==object).
            assert r["predicate"] == "ALIAS_OF", r["relation_id"]
            continue
        cand = RelationCandidate(
            subject_id=r["subject_id"],
            subject_type=r["subject_type"],
            predicate=r["predicate"],
            object_id=r["object_id"],
            object_type=r["object_type"],
            direction=r["direction"],
            confidence=1.0,
            evidence_text=r["evidence_text"],
            evidence_start=r["evidence_start"],
            evidence_end=r["evidence_end"],
            source_id=r["source_id"],
            source_page=None,
            source_segment=r["segment_id"],
            extraction_method="HEURISTIC",
            model=None,
            negated=r["negated"],
            temporal_scope=r["temporal_status"],
            epistemic_status=r["epistemic_status"],
            workspace=r["workspace"],
        )
        cand.validate()


# ---------------------------------------------------------------------------
# Cobertura de casos dificiles
# ---------------------------------------------------------------------------
def test_hard_cases_covered(ground_truth):
    rels = ground_truth["relations"]
    notes = " ".join(r["annotator_notes"].upper() for r in rels)
    # Negacion
    assert any(r["negated"] for r in rels)
    # Rumor / hipotesis / intencion
    assert any(r["epistemic_status"] == "RUMORED" for r in rels)
    assert any(r["epistemic_status"] == "HYPOTHETICAL" for r in rels)
    assert any(r["epistemic_status"] == "INTENDED" for r in rels)
    # Temporalidad: pasado, futuro, terminada
    assert any(r["temporal_status"] == "PAST" for r in rels)
    assert any(r["temporal_status"] == "FUTURE" for r in rels)
    assert any(r["temporal_status"] == "ENDED" for r in rels)
    # Direccionalidad y simetria
    assert any(r["direction"] == "UNDIRECTED" for r in rels)
    assert any(r["direction"] == "OBJECT_TO_SUBJECT" for r in rels)
    assert any(r["direction"] == "SUBJECT_TO_OBJECT" for r in rels)
    # Multiples workspaces sinteticos
    assert len({r["workspace"] for r in rels}) >= 3
    # Casos anotados por texto: alias, pronombres, voz pasiva, contradiccion, N:N
    for token in ("ALIAS", "PRONOMBRE", "VOZ PASIVA", "CONTRADICCION",
                  "N:N", "CAMBIO DE FACCION", "MULTI-FRASE", "OMITIDO"):
        assert token in notes, f"caso dificil no cubierto: {token}"
    # Unicode visible presente en alguna evidencia
    assert any(any(ord(c) > 0x2000 and c not in "‘’“”—…" for c in r["evidence_text"])
               for r in rels)


def test_similar_names_are_distinct_entities(ground_truth):
    ids = {r["subject_id"] for r in ground_truth["relations"]}
    ids |= {r["object_id"] for r in ground_truth["relations"]}
    # Nombres parecidos deliberados: distinta identidad.
    assert "kaelin" in ids and "kaelan" in ids


# ---------------------------------------------------------------------------
# Higiene: sin secretos, sin Unicode oculto, todo sintetico
# ---------------------------------------------------------------------------
def test_no_hidden_unicode_anywhere(source_texts, ground_truth):
    for sid, text in source_texts.items():
        _assert_no_hidden_unicode(text, f"source {sid}")
    for r in ground_truth["relations"]:
        _assert_no_hidden_unicode(r["evidence_text"], r["relation_id"])
        _assert_no_hidden_unicode(r["annotator_notes"], r["relation_id"])


def test_corpus_declared_synthetic(manifest, ground_truth):
    assert manifest["synthetic"] is True
    assert manifest["contains_private_corpus"] is False
    assert "sintetic" in ground_truth["description"].lower() \
        or "ficticio" in ground_truth["description"].lower()


def test_no_secrets_or_absolute_paths_in_sources(source_texts):
    needles = ("BEGIN RSA", "BEGIN PRIVATE", "PRIVATE KEY", "password",
               "passwd", "JWT_SECRET", "api_key", "API_KEY", "/home/",
               "C:\\", "duckdns", "proxmox", "192.168.", "10.0.0.")
    for sid, text in source_texts.items():
        low = text.lower()
        for n in needles:
            assert n.lower() not in low, f"posible secreto/ruta en {sid}: {n}"
