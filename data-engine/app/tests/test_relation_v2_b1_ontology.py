# -*- coding: utf-8 -*-
"""Bloque 1 (motor de relaciones v2) — FUENTE UNICA de ontologia.

Tests REALES (sin skip/xfail, sin bajar umbrales, asserts efectivos) que fijan
las garantias del Bloque 1:

  * La ontologia es CONSISTENTE: cada canonico tiene family/domain/range validos,
    inversas reciprocas, simetricos sin inversa contradictoria.
  * Cubre los 20 predicados del ground truth.
  * dominio/rango usan SOLO tipos de `ALLOWED_NODE_TYPES`, y son coherentes con
    los pares (subject_type, object_type) observados en el GT.
  * `predicate_exact_strict` distingue alias de exacto: quita el credito por
    alias (LIVES_IN vs LOCATED_IN) que hoy concede `vocabulary.predicates_match`,
    y reconoce el match exacto que `vocabulary` infra-contabiliza (out_of_vocab).
  * Las divergencias con `vocabulary.py` estan DOCUMENTADAS (no aplicadas).
"""
from __future__ import annotations

import json
from pathlib import Path

from relations import ontology as O
from relations import vocabulary as V
from schemas.rpg_schema import ALLOWED_NODE_TYPES

_GT_PATH = (
    Path(__file__).resolve().parent
    / "data" / "relation_benchmark" / "ground_truth" / "relations.json"
)

# Los 20 tipos de predicado del ground truth del corpus de benchmark.
_GT_PREDICATES = frozenset({
    "ALIAS_OF", "ALLIED_WITH", "CAUSED", "CREATED", "ENEMY_OF", "FOUNDED",
    "GUARDS", "KNOWS", "LEADS", "LIVES_IN", "LOCATED_IN", "MARRIED_TO",
    "MEMBER_OF", "MENTOR_OF", "OWNS", "PARENT_OF", "PARTICIPATED_IN",
    "SIBLING_OF", "SUCCEEDED", "TRUSTS",
})


def _load_gt() -> list[dict]:
    return json.loads(_GT_PATH.read_text(encoding="utf-8"))["relations"]


# ---------------------------------------------------------------------------
# Consistencia estructural de la ontologia
# ---------------------------------------------------------------------------
def test_every_predicate_has_family_domain_range():
    """Cada canonico tiene family valida y dominio/rango no vacios."""
    assert O.ONTOLOGY, "ontologia vacia"
    for canonical, o in O.ONTOLOGY.items():
        assert o.canonical == canonical
        assert o.family in O.FAMILIES, f"{canonical}: family invalida {o.family!r}"
        assert o.domain, f"{canonical}: dominio vacio"
        assert o.range, f"{canonical}: rango vacio"
        assert o.temporality_hint in O.TEMPORALITY_HINTS, (
            f"{canonical}: temporality_hint invalido {o.temporality_hint!r}"
        )


def test_domain_and_range_are_allowed_node_types():
    """dominio y rango usan SOLO tipos de ALLOWED_NODE_TYPES."""
    for canonical, o in O.ONTOLOGY.items():
        bad_domain = sorted(o.domain - ALLOWED_NODE_TYPES)
        bad_range = sorted(o.range - ALLOWED_NODE_TYPES)
        assert bad_domain == [], f"{canonical}: tipos de dominio no permitidos {bad_domain}"
        assert bad_range == [], f"{canonical}: tipos de rango no permitidos {bad_range}"


def test_confusable_targets_are_canonical():
    """Cada predicado en `confusable_with` es a su vez un canonico de la ontologia."""
    for canonical, o in O.ONTOLOGY.items():
        for target in o.confusable_with:
            assert target in O.ONTOLOGY, f"{canonical}: confusable {target!r} no es canonico"
            assert target != canonical, f"{canonical}: no puede confundirse consigo mismo"


def test_inverses_are_reciprocal():
    """Si p.inverse == q, entonces q existe y q.inverse == p (reciprocidad)."""
    for canonical, o in O.ONTOLOGY.items():
        if o.inverse is None:
            continue
        assert o.inverse in O.ONTOLOGY, f"{canonical}: inversa {o.inverse!r} no es canonico"
        assert O.ONTOLOGY[o.inverse].inverse == canonical, (
            f"inversa no reciproca: {canonical} -> {o.inverse}"
        )


def test_symmetric_predicates_have_no_contradictory_inverse():
    """Un predicado simetrico es su propia inversa: `inverse` debe ser None o el mismo."""
    for canonical, o in O.ONTOLOGY.items():
        if o.symmetric:
            assert o.inverse in (None, canonical), (
                f"{canonical} simetrico con inversa contradictoria {o.inverse!r}"
            )


def test_symmetric_domain_equals_range():
    """En un predicado simetrico el par no esta orientado: dominio == rango."""
    for canonical, o in O.ONTOLOGY.items():
        if o.symmetric:
            assert o.domain == o.range, (
                f"{canonical} simetrico pero dominio != rango"
            )


def test_symmetric_set_matches_flags():
    """`SYMMETRIC_PREDICATES` coincide con las entradas marcadas `symmetric`."""
    expected = frozenset(c for c, o in O.ONTOLOGY.items() if o.symmetric)
    assert O.SYMMETRIC_PREDICATES == expected
    # Los simetricos esperados del dominio RPG estan presentes.
    assert {"ALLIED_WITH", "ENEMY_OF", "SIBLING_OF", "MARRIED_TO", "ALIAS_OF"} <= (
        O.SYMMETRIC_PREDICATES
    )
    # KNOWS se mantiene DIRIGIDO (anotado asi en el GT).
    assert "KNOWS" not in O.SYMMETRIC_PREDICATES


# ---------------------------------------------------------------------------
# Cobertura de los 20 predicados del ground truth
# ---------------------------------------------------------------------------
def test_covers_all_20_ground_truth_predicates():
    """La ontologia cubre exactamente los 20 tipos de predicado del GT."""
    assert len(_GT_PREDICATES) == 20
    missing = sorted(_GT_PREDICATES - O.CANONICAL_PREDICATES)
    assert missing == [], f"predicados del GT no cubiertos por la ontologia: {missing}"
    # Verificacion contra el GT real (no una lista tecleada).
    gt = _load_gt()
    gt_preds = {r["predicate"] for r in gt}
    assert gt_preds == _GT_PREDICATES
    assert gt_preds <= O.CANONICAL_PREDICATES


def test_ground_truth_type_pairs_fit_domain_range():
    """Cada par (subject_type, object_type) del GT encaja en dominio/rango.

    Se acepta cualquiera de las dos orientaciones (el par puede almacenarse
    invertido, y los simetricos no estan orientados).
    """
    gt = _load_gt()
    misfits = []
    for r in gt:
        o = O.ONTOLOGY[r["predicate"]]
        s, t = r["subject_type"], r["object_type"]
        ok = (s in o.domain and t in o.range) or (t in o.domain and s in o.range)
        if not ok:
            misfits.append((r["predicate"], s, t))
    assert misfits == [], f"pares del GT que no encajan en dominio/rango: {sorted(set(misfits))}"


# ---------------------------------------------------------------------------
# predicate_exact_strict: distingue alias de exacto
# ---------------------------------------------------------------------------
def test_strict_rejects_alias_credit():
    """En estricto, un alias que colapsa a otro canonico NO empareja.

    Contraste con `vocabulary.predicates_match`, que SI da ese credito.
    """
    # LIVES_IN vs LOCATED_IN: la divergencia central (13% del GT).
    assert O.predicate_exact_strict("LIVES_IN", "LOCATED_IN") is False
    assert V.predicates_match("LIVES_IN", "LOCATED_IN") is True
    # ENEMY_OF vs ENEMIES_WITH (alias de renombrado en vocabulary).
    assert O.predicate_exact_strict("ENEMY_OF", "ENEMIES_WITH") is False
    assert V.predicates_match("ENEMY_OF", "ENEMIES_WITH") is True
    # SUCCEEDED vs SUCCESSOR_OF (alias de renombrado en vocabulary).
    assert O.predicate_exact_strict("SUCCEEDED", "SUCCESSOR_OF") is False
    assert V.predicates_match("SUCCEEDED", "SUCCESSOR_OF") is True


def test_strict_recognizes_exact_match_of_out_of_vocab():
    """En estricto, el match EXACTO de un predicado out_of_vocab SI vale.

    `vocabulary.predicates_match` lo infra-contabiliza (canonical None != None).
    """
    for pred in ("MENTOR_OF", "PARENT_OF", "GUARDS", "TRUSTS", "SIBLING_OF"):
        assert O.predicate_exact_strict(pred, pred) is True
        # vocabulary NO reconoce ni el match exacto de estos (out_of_vocab).
        assert V.predicates_match(pred, pred) is False


def test_strict_is_typographically_robust_and_reflexive():
    """El estricto normaliza tipograficamente y es reflexivo para todo canonico."""
    assert O.predicate_exact_strict("member of", "MEMBER_OF") is True
    assert O.predicate_exact_strict("MEMBER-OF", "MEMBER_OF") is True
    for canonical in O.CANONICAL_PREDICATES:
        assert O.predicate_exact_strict(canonical, canonical) is True


def test_strict_distinct_canonicals_do_not_match():
    """Dos canonicos distintos NUNCA emparejan en estricto."""
    assert O.predicate_exact_strict("MEMBER_OF", "LEADS") is False
    assert O.predicate_exact_strict("PARENT_OF", "SIBLING_OF") is False
    assert O.predicate_exact_strict("LIVES_IN", "MEMBER_OF") is False


# ---------------------------------------------------------------------------
# Divergencias con vocabulary.py — documentadas, no aplicadas
# ---------------------------------------------------------------------------
def test_documented_divergences_match_reality():
    """Cada divergencia declarada refleja el comportamiento REAL de vocabulary."""
    for canonical, info in O.VOCABULARY_DIVERGENCES.items():
        assert canonical in O.ONTOLOGY, f"divergencia sobre no-canonico {canonical}"
        vocab_canon = V.canonicalize_predicate(canonical).canonical
        assert vocab_canon == info["vocab_canonical"], (
            f"{canonical}: vocab canoniza a {vocab_canon!r}, "
            f"documentado {info['vocab_canonical']!r}"
        )
        # Divergencia real: la ontologia lo trata como canonico propio, vocabulary no.
        assert vocab_canon != canonical


def test_alias_credit_dependency_is_13_percent_of_gt():
    """Los GT que reciben CREDITO POR ALIAS (colapso a otro canonico) son ~13%.

    Son los predicados que `vocabulary` canoniza a un string DISTINTO no None
    (LIVES_IN, ENEMY_OF, SUCCEEDED): con `predicates_match` un pred con el
    canonico-destino casaria con el GT, credito que `predicate_exact_strict`
    elimina.
    """
    gt = _load_gt()
    alias_collapse_preds = {
        c for c in O.CANONICAL_PREDICATES
        if (vc := V.canonicalize_predicate(c).canonical) is not None and vc != c
    }
    assert alias_collapse_preds == {"LIVES_IN", "ENEMY_OF", "SUCCEEDED"}
    n_alias = sum(1 for r in gt if r["predicate"] in alias_collapse_preds)
    assert n_alias == 7, f"se esperaban 7 relaciones con credito por alias, hay {n_alias}"
    fraction = n_alias / len(gt)
    assert 0.12 <= fraction <= 0.14, f"fraccion de credito por alias fuera de rango: {fraction:.3f}"


def test_ontology_does_not_touch_scoring_path():
    """B1 es metric-neutral: la ontologia NO altera vocabulary de puntuacion.

    `vocabulary.PREDICATE_ALIASES` y `SYMMETRIC_PREDICATES` conservan sus valores
    (la ontologia nueva es una estructura de datos separada).
    """
    assert V.PREDICATE_ALIASES == {
        "ENEMY_OF": "ENEMIES_WITH",
        "ENEMY_WITH": "ENEMIES_WITH",
        "SUCCEEDED": "SUCCESSOR_OF",
        "LIVES_IN": "LOCATED_IN",
        "ALLY_OF": "ALLIED_WITH",
        "MEMBER": "MEMBER_OF",
    }
    assert V.SYMMETRIC_PREDICATES == frozenset({"ALLIED_WITH", "ENEMIES_WITH", "KIN_OF"})
