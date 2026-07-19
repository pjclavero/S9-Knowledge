# -*- coding: utf-8 -*-
"""Tests del generador determinista de pares candidatos (A-REL-2).

Cubren: determinismo byte a byte, exclusion de autorrelaciones, deduplicacion,
limite max_pairs / anti-explosion, preservacion de workspace y procedencia,
ventana de distancia y contexto (frase/parrafo), pares vacios sin contexto,
reproducibilidad de pair_id y direccion doble.

No usan red, ni Neo4j, ni LLM: el generador es puramente estructural.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from relations.pairs import (  # noqa: E402
    CandidatePair,
    PairConfig,
    PairGenerationError,
    PairGenerationResult,
    generate_pairs,
    stable_pair_id,
)


# --- Helpers de fixtures ---------------------------------------------------
def _seg(text, seg_id="seg-1", workspace="ws-a", source_id="doc-1", source_page=3):
    return {
        "id": seg_id,
        "text": text,
        "workspace": workspace,
        "source_id": source_id,
        "source_page": source_page,
    }


def _ent(ent_id, start, end, type_=None, workspace=None):
    d = {"id": ent_id, "start": start, "end": end}
    if type_ is not None:
        d["type"] = type_
    if workspace is not None:
        d["workspace"] = workspace
    return d


# Texto de trabajo: dos frases, una entidad repetida.
#           0         1         2         3         4
#           0123456789012345678901234567890123456789012345678
TEXT = "Alice met Bob near the gate. Carol saw Alice later."
E_ALICE1 = _ent("alice", 0, 5, "Character")
E_BOB = _ent("bob", 10, 13, "Character")
E_CAROL = _ent("carol", 29, 34, "Character")
E_ALICE2 = _ent("alice", 39, 44, "Character")


# --- Determinismo ----------------------------------------------------------
def test_determinism_byte_identical_regardless_of_input_order():
    seg = _seg(TEXT)
    cfg = PairConfig(context_mode="segment")
    order_a = [E_ALICE1, E_BOB, E_CAROL, E_ALICE2]
    order_b = [E_ALICE2, E_CAROL, E_BOB, E_ALICE1]

    r1 = generate_pairs(order_a, seg, config=cfg)
    r2 = generate_pairs(order_b, seg, config=cfg)

    assert r1.to_json() == r2.to_json()
    # y estable al repetir con la misma entrada
    r3 = generate_pairs(order_a, seg, config=cfg)
    assert r1.to_json() == r3.to_json()


def test_result_is_a_result_of_pairs():
    r = generate_pairs([E_ALICE1, E_BOB], _seg(TEXT), config=PairConfig(context_mode="segment"))
    assert isinstance(r, PairGenerationResult)
    assert all(isinstance(p, CandidatePair) for p in r.pairs)


# --- Exclusion de autorrelaciones -----------------------------------------
def test_self_relations_excluded_by_default():
    # alice aparece dos veces -> par (alice, alice) NO debe emitirse.
    seg = _seg(TEXT)
    r = generate_pairs([E_ALICE1, E_ALICE2], seg, config=PairConfig(context_mode="segment"))
    assert r.pairs == ()  # solo habia una pareja posible y es autorrelacion


def test_self_relations_allowed_when_reflexive_predicates_present():
    seg = _seg(TEXT)
    cfg = PairConfig(context_mode="segment", reflexive_predicates=("SAME_AS",))
    r = generate_pairs([E_ALICE1, E_ALICE2], seg, config=cfg)
    assert len(r.pairs) == 1
    p = r.pairs[0]
    assert p.subject_id == p.object_id == "alice"
    assert p.reflexive is True


# --- Deduplicacion ---------------------------------------------------------
def test_dedup_keeps_single_pair_per_unordered_combination():
    # alice(x2) y bob -> par logico (alice, bob) una sola vez pese a 2 menciones.
    seg = _seg(TEXT)
    r = generate_pairs([E_ALICE1, E_BOB, E_ALICE2], seg, config=PairConfig(context_mode="segment"))
    keys = [(p.subject_id, p.object_id) for p in r.pairs]
    assert keys == sorted(set(keys))
    assert ("alice", "bob") in keys
    assert keys.count(("alice", "bob")) == 1


def test_dedup_keeps_closest_mention():
    # alice esta cerca de bob en la primera frase y lejos en la segunda mencion.
    seg = _seg(TEXT)
    r = generate_pairs([E_ALICE1, E_BOB, E_ALICE2], seg, config=PairConfig(context_mode="segment"))
    pair = next(p for p in r.pairs if (p.subject_id, p.object_id) == ("alice", "bob"))
    # la mencion mas cercana usa alice@0 (dist bob.start 10 - alice.end 5 = 5)
    assert pair.subject_start == 0
    assert pair.distance == 5


# --- Contexto: frase / parrafo --------------------------------------------
def test_sentence_context_splits_pairs():
    # En modo frase, Bob (frase 1) y Carol (frase 2) NO forman par.
    seg = _seg(TEXT)
    r = generate_pairs([E_ALICE1, E_BOB, E_CAROL, E_ALICE2], seg, config=PairConfig(context_mode="sentence"))
    keys = {(p.subject_id, p.object_id) for p in r.pairs}
    assert ("alice", "bob") in keys          # misma frase 1
    assert ("carol", "alice") in keys        # misma frase 2
    assert ("bob", "carol") not in keys      # frases distintas
    assert ("bob", "alice") not in keys      # bob frase 1, alice2 frase 2


def test_paragraph_context():
    text = "Alice knows Bob.\n\nCarol knows Dave."
    a = _ent("alice", 0, 5)
    b = _ent("bob", 12, 15)
    c = _ent("carol", 18, 23)
    d = _ent("dave", 30, 34)
    r = generate_pairs([a, b, c, d], _seg(text), config=PairConfig(context_mode="paragraph"))
    keys = {(p.subject_id, p.object_id) for p in r.pairs}
    assert ("alice", "bob") in keys
    assert ("carol", "dave") in keys
    assert ("bob", "carol") not in keys  # parrafos distintos


# --- Ventana / distancia ---------------------------------------------------
def test_distance_window_char_filters_far_pairs():
    seg = _seg(TEXT)
    cfg = PairConfig(context_mode="segment", window="char", max_distance=6)
    r = generate_pairs([E_ALICE1, E_BOB, E_CAROL, E_ALICE2], seg, config=cfg)
    for p in r.pairs:
        assert p.distance <= 6
        assert p.distance_unit == "char"


def test_distance_mode_requires_max_distance():
    with pytest.raises(PairGenerationError):
        PairConfig(context_mode="distance")  # sin max_distance


def test_token_window_counts_tokens():
    cfg = PairConfig(context_mode="segment", window="token", max_distance=1)
    seg = _seg(TEXT)
    r = generate_pairs([E_ALICE1, E_BOB], seg, config=cfg)
    # "Alice met Bob": entre alice y bob hay 1 token ("met")
    assert len(r.pairs) == 1
    assert r.pairs[0].distance == 1
    assert r.pairs[0].distance_unit == "token"


def test_empty_when_no_context():
    # distancia imposible -> ningun par.
    seg = _seg(TEXT)
    cfg = PairConfig(context_mode="distance", max_distance=0)
    r = generate_pairs([E_ALICE1, E_CAROL], seg, config=cfg)
    assert r.pairs == ()
    assert r.total_before_truncation == 0


def test_empty_with_single_entity():
    r = generate_pairs([E_ALICE1], _seg(TEXT), config=PairConfig(context_mode="segment"))
    assert r.pairs == ()


# --- max_pairs / anti-explosion -------------------------------------------
def _many_entities(n, gap=3):
    text = " ".join(f"e{i}" for i in range(n))
    ents = []
    pos = 0
    for i in range(n):
        tok = f"e{i}"
        ents.append(_ent(f"ent{i:03d}", pos, pos + len(tok)))
        pos += len(tok) + 1
    return text, ents


def test_max_pairs_truncates_deterministically_no_explosion():
    text, ents = _many_entities(30)  # 30*29/2 = 435 combinaciones posibles
    seg = _seg(text)
    cfg = PairConfig(context_mode="segment", max_pairs=10)
    r = generate_pairs(ents, seg, config=cfg)
    assert len(r.pairs) <= 10
    assert r.truncated is True
    assert r.total_before_truncation == 435
    assert any("truncated" in w for w in r.warnings)
    # determinista: misma entrada -> mismo recorte byte a byte
    r2 = generate_pairs(list(reversed(ents)), seg, config=cfg)
    assert r.to_json() == r2.to_json()


def test_max_pairs_not_exceeded_bound():
    text, ents = _many_entities(50)
    r = generate_pairs(ents, _seg(text), config=PairConfig(context_mode="segment", max_pairs=25))
    assert len(r.pairs) <= 25


def test_strict_max_pairs_raises():
    text, ents = _many_entities(10)  # 45 combinaciones
    cfg = PairConfig(context_mode="segment", max_pairs=5, strict_max_pairs=True)
    with pytest.raises(PairGenerationError):
        generate_pairs(ents, _seg(text), config=cfg)


def test_no_truncation_when_under_limit():
    r = generate_pairs([E_ALICE1, E_BOB], _seg(TEXT), config=PairConfig(context_mode="segment", max_pairs=100))
    assert r.truncated is False
    assert r.warnings == ()


# --- Preservacion de workspace y procedencia -------------------------------
def test_preserves_workspace_and_provenance():
    seg = _seg(TEXT, seg_id="seg-99", workspace="my-ws", source_id="doc-42", source_page=7)
    r = generate_pairs([E_ALICE1, E_BOB], seg, config=PairConfig(context_mode="segment"))
    assert len(r.pairs) == 1
    p = r.pairs[0]
    assert p.workspace == "my-ws"
    assert p.source_id == "doc-42"
    assert p.source_segment == "seg-99"
    assert p.source_page == 7


def test_source_id_defaults_to_segment_id():
    seg = {"id": "seg-x", "text": TEXT, "workspace": "ws"}
    r = generate_pairs([E_ALICE1, E_BOB], seg, config=PairConfig(context_mode="segment"))
    assert r.pairs[0].source_id == "seg-x"
    assert r.pairs[0].source_page is None


def test_entities_from_different_workspaces_not_paired():
    seg = _seg(TEXT, workspace="ws-a")
    a = _ent("alice", 0, 5, workspace="ws-a")
    b = _ent("bob", 10, 13, workspace="ws-b")
    r = generate_pairs([a, b], seg, config=PairConfig(context_mode="segment"))
    assert r.pairs == ()


# --- pair_id reproducible --------------------------------------------------
def test_pair_id_reproducible_and_matches_helper():
    seg = _seg(TEXT, seg_id="segZ", workspace="wsZ")
    r = generate_pairs([E_ALICE1, E_BOB], seg, config=PairConfig(context_mode="segment"))
    p = r.pairs[0]
    expected = stable_pair_id("wsZ", "alice", "bob", "segZ")
    assert p.pair_id == expected
    # el helper es puro y estable
    assert stable_pair_id("wsZ", "alice", "bob", "segZ") == expected


# --- Direccion doble -------------------------------------------------------
def test_emit_both_directions():
    seg = _seg(TEXT)
    cfg = PairConfig(context_mode="segment", emit_both_directions=True)
    r = generate_pairs([E_ALICE1, E_BOB], seg, config=cfg)
    keys = {(p.subject_id, p.object_id) for p in r.pairs}
    assert ("alice", "bob") in keys
    assert ("bob", "alice") in keys


def test_undirected_default_one_direction_only():
    seg = _seg(TEXT)
    r = generate_pairs([E_ALICE1, E_BOB], seg, config=PairConfig(context_mode="segment"))
    keys = {(p.subject_id, p.object_id) for p in r.pairs}
    assert keys == {("alice", "bob")}  # canonico por orden textual


# --- Validacion de entrada -------------------------------------------------
def test_invalid_entity_missing_id():
    with pytest.raises(PairGenerationError):
        generate_pairs([{"start": 0, "end": 3}], _seg(TEXT), config=PairConfig(context_mode="segment"))


def test_invalid_segment_missing_workspace():
    with pytest.raises(PairGenerationError):
        generate_pairs([E_ALICE1, E_BOB], {"id": "s", "text": TEXT}, config=PairConfig(context_mode="segment"))


def test_invalid_start_gt_end():
    with pytest.raises(PairGenerationError):
        generate_pairs([_ent("x", 10, 5)], _seg(TEXT), config=PairConfig(context_mode="segment"))
