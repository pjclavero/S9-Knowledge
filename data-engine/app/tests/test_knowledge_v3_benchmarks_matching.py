# -*- coding: utf-8 -*-
"""Emparejamiento: donde se hacen las trampas sin querer.

Cada test de este fichero defiende una propiedad concreta del emparejamiento.
Los marcados como MUTACION son los importantes: comprueban que relajar la regla
convierte una prediccion equivocada en un acierto, es decir, que la regla esta
haciendo trabajo de verdad y no es decorativa.
"""
from __future__ import annotations

import pytest

from knowledge_v3.benchmarks.matching import (
    MatchConfig,
    build_alignment,
    canonical_endpoints,
    claim_key,
    fact_key,
    match_by_key,
    match_spans,
    pair_set,
    spans_overlap,
)


def m(mid: str, episode: str, start: int, end: int) -> dict:
    return {"mention_id": mid, "episode_id": episode, "start": start, "end": end}


EXACT = MatchConfig()
LAXO = MatchConfig(span_mode="overlap", overlap_threshold=0.1)


# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------
def test_el_modo_de_span_desconocido_se_rechaza():
    with pytest.raises(ValueError):
        MatchConfig(span_mode="parecido")


def test_el_umbral_fuera_de_rango_se_rechaza():
    with pytest.raises(ValueError):
        MatchConfig(span_mode="overlap", overlap_threshold=0)


def test_la_configuracion_viaja_al_informe():
    cfg = MatchConfig(claim_key_extra=("predicate",), symmetric_predicates=frozenset({"ALLY_OF"}))
    assert cfg.as_dict() == {
        "span_mode": "exact",
        "overlap_threshold": 0.5,
        "claim_key_extra": ["predicate"],
        "fact_key_includes_validity": False,
        "symmetric_predicates": ["ALLY_OF"],
    }


def test_el_valor_por_defecto_es_el_estricto():
    assert MatchConfig().span_mode == "exact"
    assert MatchConfig().claim_key_extra == ()


# --------------------------------------------------------------------------
# Span exacto
# --------------------------------------------------------------------------
def test_span_exacto_empareja_solo_lo_identico():
    gold = [m("g1", "e1", 0, 5), m("g2", "e1", 10, 20)]
    pred = [m("p1", "e1", 0, 5), m("p2", "e1", 11, 20)]
    r = match_spans(gold, pred, id_field="mention_id", config=EXACT)
    assert (r.tp, r.fp, r.fn) == (1, 1, 1)
    assert r.pairs == [("g1", "p1")]


def test_span_exacto_distingue_episodios():
    gold = [m("g1", "e1", 0, 5)]
    pred = [m("p1", "e2", 0, 5)]
    r = match_spans(gold, pred, id_field="mention_id", config=EXACT)
    assert (r.tp, r.fp, r.fn) == (0, 1, 1)


# --------------------------------------------------------------------------
# MUTACION: el emparejamiento laxo aprueba lo que el estricto suspende
# --------------------------------------------------------------------------
def test_mutacion_un_span_desplazado_no_es_un_acierto():
    """Prediccion mal anclada: con la regla real es fallo; relajarla la aprueba."""
    gold = [m("g1", "e1", 0, 20)]
    pred = [m("p1", "e1", 2, 20)]

    estricto = match_spans(gold, pred, id_field="mention_id", config=EXACT)
    assert estricto.tp == 0, "el emparejamiento estricto no puede aceptar otro span"

    laxo = match_spans(gold, pred, id_field="mention_id", config=LAXO)
    assert laxo.tp == 1, (
        "si esta linea falla, el modo laxo dejo de ser laxo y este test ya no "
        "demuestra nada: revisar antes de tocar el estricto"
    )


def test_mutacion_repetir_la_misma_prediccion_no_sube_el_recall():
    """Uno a uno: cien copias de un acierto siguen siendo un acierto."""
    gold = [m("g1", "e1", 0, 5), m("g2", "e1", 6, 9)]
    pred = [m(f"p{i}", "e1", 0, 5) for i in range(100)]
    r = match_spans(gold, pred, id_field="mention_id", config=EXACT)
    assert r.tp == 1
    assert r.fp == 99
    assert r.fn == 1


def test_mutacion_uno_a_uno_tambien_en_modo_laxo():
    gold = [m("g1", "e1", 0, 10)]
    pred = [m("p1", "e1", 0, 10), m("p2", "e1", 1, 10), m("p3", "e1", 2, 10)]
    r = match_spans(gold, pred, id_field="mention_id", config=LAXO)
    assert r.tp == 1 and r.fp == 2


def test_el_modo_laxo_respeta_su_umbral():
    gold = [m("g1", "e1", 0, 100)]
    pred = [m("p1", "e1", 90, 100)]
    r = match_spans(gold, pred, id_field="mention_id", config=MatchConfig(span_mode="overlap", overlap_threshold=0.5))
    assert r.tp == 0, "un solape del 10% no puede pasar un umbral del 50%"


# --------------------------------------------------------------------------
# Determinismo
# --------------------------------------------------------------------------
def test_el_resultado_no_depende_del_orden_de_entrada():
    gold = [m("g1", "e1", 0, 5), m("g2", "e1", 6, 9), m("g3", "e2", 0, 4)]
    pred = [m("p1", "e1", 0, 5), m("p2", "e2", 0, 4), m("p3", "e1", 6, 9)]
    a = match_spans(gold, pred, id_field="mention_id", config=EXACT).as_dict()
    b = match_spans(gold[::-1], pred[::-1], id_field="mention_id", config=EXACT).as_dict()
    assert a == b


def test_el_desempate_es_determinista_con_solapes_iguales():
    gold = [m("g1", "e1", 0, 10)]
    pred = [m("pb", "e1", 0, 10), m("pa", "e1", 0, 10)]
    r1 = match_spans(gold, pred, id_field="mention_id", config=LAXO)
    r2 = match_spans(gold, pred[::-1], id_field="mention_id", config=LAXO)
    assert r1.pairs == r2.pairs == [("g1", "pa")]


# --------------------------------------------------------------------------
# Claves de claim
# --------------------------------------------------------------------------
def _claim(cid, subs, objs, predicate="MEMBER_OF", negated=False):
    return {
        "claim_id": cid,
        "episode_id": "e1",
        "subject_mentions": subs,
        "object_mentions": objs,
        "predicate_candidates": [{"predicate": predicate, "confidence": 0.9}],
        "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.9}],
        "negated": negated,
    }


def test_la_clave_de_claim_no_incluye_el_predicado_por_defecto():
    alineado = {"a": "a", "b": "b"}
    c1 = _claim("c1", ["a"], ["b"], predicate="MEMBER_OF")
    c2 = _claim("c2", ["a"], ["b"], predicate="ALLY_OF")
    assert claim_key(c1, alineado, EXACT) == claim_key(c2, alineado, EXACT)


def test_la_clave_de_claim_puede_incluir_el_predicado_de_forma_explicita():
    cfg = MatchConfig(claim_key_extra=("predicate",))
    alineado = {"a": "a", "b": "b"}
    c1 = _claim("c1", ["a"], ["b"], predicate="MEMBER_OF")
    c2 = _claim("c2", ["a"], ["b"], predicate="ALLY_OF")
    assert claim_key(c1, alineado, cfg) != claim_key(c2, alineado, cfg)


def test_un_claim_con_mencion_no_alineada_no_es_evaluable():
    assert claim_key(_claim("c1", ["x"], ["b"]), {"b": "b"}, EXACT) is None


def test_una_mencion_no_evaluable_cuenta_como_fallo_no_se_ignora():
    gold = [{"claim_id": "g1", "_key": ("e1", ("a",), ("b",))}]
    pred = [{"claim_id": "p1", "_key": None}]
    r = match_by_key(gold, pred, id_field="claim_id", key_fn=lambda c: c["_key"])
    assert (r.tp, r.fp, r.fn) == (0, 1, 1)


def test_la_abstencion_es_emparejable():
    vacio = {
        "claim_id": "c1",
        "episode_id": "e1",
        "subject_mentions": [],
        "object_mentions": [],
    }
    assert claim_key(vacio, {}, EXACT) == ("e1", (), (), "ABSTAINED")


def test_intercambiar_sujeto_y_objeto_cambia_la_clave():
    alineado = {"a": "a", "b": "b"}
    directo = claim_key(_claim("c1", ["a"], ["b"]), alineado, EXACT)
    invertido = claim_key(_claim("c2", ["b"], ["a"]), alineado, EXACT)
    assert directo != invertido


# --------------------------------------------------------------------------
# Claves de hecho y simetria
# --------------------------------------------------------------------------
SIM = MatchConfig(symmetric_predicates=frozenset({"ALLY_OF"}))


def _fact(subj, obj, predicate, direction="SUBJECT_TO_OBJECT", negated=False, **kw):
    doc = {
        "subject_entity_id": subj,
        "object_entity_id": obj,
        "predicate": predicate,
        "direction": direction,
        "negated": negated,
    }
    doc.update(kw)
    return doc


def test_un_predicado_simetrico_canoniza_sus_extremos():
    a = fact_key(_fact("X", "Y", "ALLY_OF", direction="UNDIRECTED"), SIM)
    b = fact_key(_fact("Y", "X", "ALLY_OF", direction="UNDIRECTED"), SIM)
    assert a == b


def test_un_predicado_asimetrico_no_canoniza_nada():
    a = fact_key(_fact("X", "Y", "MEMBER_OF"), SIM)
    b = fact_key(_fact("Y", "X", "MEMBER_OF"), SIM)
    assert a != b, "invertir una relacion asimetrica es un error, no una variante"


def test_mutacion_declarar_simetrico_lo_asimetrico_borra_el_error_de_direccion():
    mal = MatchConfig(symmetric_predicates=frozenset({"MEMBER_OF"}))
    a = fact_key(_fact("X", "Y", "MEMBER_OF"), mal)
    b = fact_key(_fact("Y", "X", "MEMBER_OF"), mal)
    assert a == b, (
        "esta igualdad es la trampa que el test anterior vigila: si el perfil "
        "declarase simetrico un predicado que no lo es, el eje 'direccion' "
        "dejaria de medir nada"
    )


def test_la_negacion_siempre_forma_parte_del_hecho():
    afirmado = fact_key(_fact("X", "Y", "MEMBER_OF"), SIM)
    negado = fact_key(_fact("X", "Y", "MEMBER_OF", negated=True), SIM)
    assert afirmado != negado


def test_la_vigencia_solo_entra_si_se_pide():
    base = _fact("X", "Y", "MEMBER_OF", valid_from="1000-01-01T00:00:00Z", valid_to=None)
    otro = _fact("X", "Y", "MEMBER_OF", valid_from="2000-01-01T00:00:00Z", valid_to=None)
    assert fact_key(base, SIM) == fact_key(otro, SIM)
    con_vigencia = MatchConfig(fact_key_includes_validity=True)
    assert fact_key(base, con_vigencia) != fact_key(otro, con_vigencia)


def test_un_hecho_sin_extremos_no_es_evaluable():
    assert fact_key(_fact(None, "Y", "MEMBER_OF"), SIM) is None


def test_canonical_endpoints_solo_ordena_lo_simetrico():
    assert canonical_endpoints("b", "a", "ALLY_OF", SIM) == ("a", "b")
    assert canonical_endpoints("b", "a", "MEMBER_OF", SIM) == ("b", "a")


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def test_los_pares_de_correferencia_ignoran_los_singletons():
    assert pair_set([["a"], ["b", "c"]]) == {("b", "c")}


def test_agrupar_todo_con_todo_dispara_los_pares():
    assert len(pair_set([["a", "b", "c", "d"]])) == 6


def test_solape_de_intervalos_semiabiertos():
    assert spans_overlap(0, 5, 4, 9)
    assert not spans_overlap(0, 5, 5, 9)


def test_build_alignment_va_de_prediccion_a_gold():
    gold = [m("g1", "e1", 0, 5)]
    pred = [m("p1", "e1", 0, 5)]
    r = match_spans(gold, pred, id_field="mention_id", config=EXACT)
    assert build_alignment(r) == {"p1": "g1"}
    assert r.gold_of("p1") == "g1"
    assert r.pred_of("g1") == "p1"
