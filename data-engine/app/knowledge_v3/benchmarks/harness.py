# -*- coding: utf-8 -*-
"""Arnes de medicion por subsistema (dosier 13).

Entrada: `(salida_de_subsistema, gold)`. Salida: un informe con conteos y
metricas, determinista y serializable.

Lo que el arnes NO hace, a proposito: no ejecuta el pipeline, no llama a
proveedores, no escribe en Neo4j y no rellena huecos. Si un subsistema no
entrego nada que medir, su seccion sale con ``status: not_evaluated`` y el
motivo; nunca con un cero que parezca un resultado.
"""
from __future__ import annotations

from typing import Any, Iterable

from . import BENCHMARK_FORMAT_VERSION
from .ablations import Ablation, resolve as resolve_ablation
from .loader import GoldDataset, PredictionBundle, index_by
from .matching import (
    MatchConfig,
    build_alignment,
    claim_key,
    fact_key,
    match_by_key,
    match_spans,
    pair_set,
    spans_overlap,
)
from .authoring.common import table_text
from .metrics import (
    accuracy,
    align_clusters,
    duplicate_rate,
    error_rate,
    over_merge_rate,
    prf,
    ratio,
    repetition_score,
    set_prf,
)

#: Tolerancia de truncado: por debajo de este porcentaje de la longitud de
#: referencia, el episodio se considera truncado. Es un umbral EXPLICITO.
TRUNCATION_TOLERANCE = 0.95

_ACTION_ID_FIELD = {
    "LINK_EXISTING": "selected_entity_id",
    "CREATE_NEW": "assigned_entity_id",
    "CREATE_PROVISIONAL": "assigned_entity_id",
}


def episode_text(episode: dict[str, Any]) -> str:
    """Texto evaluable de un episodio.

    Una tabla no lleva prosa: su contenido es la tabla, y se evalua sobre el
    render canonico TSV documentado en docs/v3/08-benchmarks.md. Puntuar una
    tabla como si su texto fuese vacio castigaria al normalizador por hacer lo
    correcto.
    """
    text = episode.get("text")
    if text:
        return text
    table = episode.get("table")
    if table:
        return table_text(table)
    return ""


def _skip(reason: str) -> dict[str, Any]:
    return {"status": "not_evaluated", "reason": reason}


def _top(candidates: list[dict[str, Any]] | None, field: str) -> Any:
    if not candidates:
        return None
    return candidates[0].get(field)


def _assignment(resolutions: Iterable[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for res in resolutions:
        field_name = _ACTION_ID_FIELD.get(res.get("action"))
        if field_name is None:
            continue
        entity_id = res.get(field_name)
        if entity_id is None:
            continue
        for mid in res.get("mention_ids") or []:
            out[mid] = entity_id
    return out


# --------------------------------------------------------------------------
# Normalizador
# --------------------------------------------------------------------------
def score_normalizer(gold: GoldDataset, pred: PredictionBundle) -> dict[str, Any]:
    if not pred.episodes:
        return _skip("la prediccion no trae episodios")
    reference = gold.reference_text
    match = match_by_key(
        gold.episodes,
        pred.episodes,
        id_field="episode_id",
        key_fn=lambda e: (str(e["source_asset_id"]), int(e["sequence"])),
    )
    gold_by_id = index_by(gold.episodes, "episode_id")
    pred_by_id = index_by(pred.episodes, "episode_id")

    total_ref_chars = sum(len(reference.get(e["episode_id"], "")) for e in gold.episodes)
    detected_chars = 0
    matched_chars = 0
    char_edits = char_ref = word_edits = word_ref = 0
    truncated = repeated = 0
    bbox_expected = bbox_present = 0
    time_expected = time_present = 0

    for gid, pid in sorted(match.pairs):
        g = gold_by_id[gid]
        p = pred_by_id[pid]
        ref = reference.get(gid, "")
        hyp = episode_text(p)
        detected_chars += len(ref)
        ce, cr = error_rate(ref, hyp, unit="char")
        # Caracteres de referencia REALMENTE recuperados: los que sobreviven a
        # la distancia de edicion. Un episodio detectado con el texto entero
        # equivocado aporta 0, no aporta su longitud.
        matched_chars += max(0, len(ref) - ce)
        we, wr = error_rate(ref, hyp, unit="word")
        char_edits += ce
        char_ref += cr
        word_edits += we
        word_ref += wr
        if ref and len(hyp) < TRUNCATION_TOLERANCE * len(ref):
            truncated += 1
        if repetition_score(hyp):
            repeated += 1
        if g.get("bbox") is not None:
            bbox_expected += 1
            if p.get("bbox") is not None:
                bbox_present += 1
        if g.get("time_start") is not None:
            time_expected += 1
            if p.get("time_start") is not None:
                time_present += 1

    gold_pages = {e["page"] for e in gold.episodes if e.get("page") is not None}
    pred_pages = {e.get("page") for e in pred.episodes if e.get("page") is not None}

    return {
        "status": "scored",
        "episode_detection": prf(match.tp, match.fp, match.fn),
        # OJO: son dos cosas distintas y por eso tienen dos nombres.
        # `episode_char_recall` solo dice si se emitio un episodio para ese
        # texto; no mira lo que dice. `char_coverage` mide contenido: cae a 0
        # si el texto emitido no se parece a la referencia.
        "episode_char_recall": ratio(detected_chars, total_ref_chars),
        "char_coverage": ratio(matched_chars, total_ref_chars),
        "cer": ratio(char_edits, char_ref),
        "wer": ratio(word_edits, word_ref),
        "truncated_episodes": truncated,
        "truncation_rate": ratio(truncated, match.tp),
        "repetition_episodes": repeated,
        "repetition_rate": ratio(repeated, match.tp),
        "page_recall": ratio(len(gold_pages & pred_pages), len(gold_pages)),
        "pages_gold": sorted(gold_pages),
        "pages_predicted": sorted(p for p in pred_pages if p is not None),
        "bbox_completeness": ratio(bbox_present, bbox_expected),
        "timecode_completeness": ratio(time_present, time_expected),
    }


# --------------------------------------------------------------------------
# Extractor
# --------------------------------------------------------------------------
def score_extractor(
    gold: GoldDataset, pred: PredictionBundle, config: MatchConfig
) -> dict[str, Any]:
    if not pred.mentions and not pred.claims:
        return _skip("la prediccion no trae ni menciones ni claims")

    out: dict[str, Any] = {"status": "scored"}

    mention_match = match_spans(
        gold.mentions, pred.mentions, id_field="mention_id", config=config
    )
    alignment = build_alignment(mention_match)  # pred -> gold
    out["mentions"] = prf(mention_match.tp, mention_match.fp, mention_match.fn)

    gold_m = index_by(gold.mentions, "mention_id")
    pred_m = index_by(pred.mentions, "mention_id")
    correct_type = 0
    for gid, pid in mention_match.pairs:
        if _top(gold_m[gid].get("type_candidates"), "type") == _top(
            pred_m[pid].get("type_candidates"), "type"
        ):
            correct_type += 1
    out["type_accuracy_matched"] = accuracy(correct_type, mention_match.tp)
    #: Version severa: una mencion no detectada es tambien un tipo no acertado.
    out["type_accuracy_strict"] = accuracy(correct_type, len(gold.mentions))

    # --- correferencia ---------------------------------------------------
    gold_pairs = {
        p
        for p in pair_set(gold.coreference_clusters())
        if p[0] in {g for g, _ in mention_match.pairs}
        and p[1] in {g for g, _ in mention_match.pairs}
    }
    pred_clusters = clusters_from_candidates(pred.mentions)
    translated = []
    dropped = 0
    for cluster in pred_clusters:
        mapped = [alignment.get(m) for m in cluster]
        dropped += sum(1 for m in mapped if m is None)
        translated.append([m for m in mapped if m is not None])
    pred_pairs = pair_set(translated)
    coref = set_prf(gold_pairs, pred_pairs)
    coref["pairs_dropped_unaligned"] = dropped
    coref["universe"] = "menciones alineadas con el gold; las no alineadas no forman par"
    out["coreference"] = coref

    # --- claims -----------------------------------------------------------
    gold_claims = gold.claims_for("extractor")
    gold_keyed = [
        {"claim_id": c["claim_id"], "_key": claim_key(c, {m: m for m in gold_m}, config)}
        for c in gold_claims
    ]
    pred_keyed = [
        {"claim_id": c["claim_id"], "_key": claim_key(c, alignment, config)}
        for c in pred.claims
    ]
    claim_match = match_by_key(
        gold_keyed, pred_keyed, id_field="claim_id", key_fn=lambda c: c["_key"]
    )
    out["claims"] = prf(claim_match.tp, claim_match.fp, claim_match.fn)
    out["claims_unevaluable"] = sum(1 for c in pred_keyed if c["_key"] is None)

    # --- candidatos falsos: claims sobre tramos que NO deben producir nada --
    out["false_candidates"] = _false_candidates(gold, pred)
    return out


def clusters_from_candidates(mentions: list[dict[str, Any]]) -> list[list[str]]:
    """Cierre transitivo de `coreference_candidates` (grafo no dirigido)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for m in mentions:
        mid = m["mention_id"]
        find(mid)
        for other in m.get("coreference_candidates") or []:
            union(mid, other)
    groups: dict[str, list[str]] = {}
    for node in sorted(parent):
        groups.setdefault(find(node), []).append(node)
    return sorted([sorted(g) for g in groups.values() if len(g) > 1])


def _false_candidates(gold: GoldDataset, pred: PredictionBundle) -> dict[str, Any]:
    """Claims predichos que pisan un tramo marcado como 'no debe producir claim'.

    Se miran los spans de la EVIDENCIA del claim y los de sus menciones: un
    claim anclado dentro de una ficcion, de una pregunta o de un contrafactual
    es exactamente el error que estas trampas existen para cazar.
    """
    negatives = gold.negatives
    if not negatives:
        return _skip("el split no declara casos negativos")
    frag_index = index_by(pred.fragments or gold.fragments, "fragment_id")
    mention_index = index_by(pred.mentions or gold.mentions, "mention_id")

    hits: list[str] = []
    traps_hit: set[str] = set()
    unanchored: list[str] = []
    per_kind: dict[str, int] = {}
    for claim in pred.claims:
        spans: list[dict[str, Any]] = []
        for fid in claim.get("evidence_fragment_ids") or []:
            frag = frag_index.get(fid)
            if frag is not None:
                spans.append(frag)
        for mid in (claim.get("subject_mentions") or []) + (
            claim.get("object_mentions") or []
        ):
            mention = mention_index.get(mid)
            if mention is not None:
                spans.append(mention)
        if not spans:
            # Evasion: un claim cuya evidencia y cuyas menciones no vienen
            # declaradas en el bundle no se puede anclar, asi que no se puede
            # descartar que pise una trampa. NO cuenta como limpio: cuenta como
            # no evaluable, y sale a la superficie del informe.
            if any(
                str(n["episode_id"]) == str(claim.get("episode_id")) for n in negatives
            ):
                unanchored.append(claim["claim_id"])
            continue
        for neg in negatives:
            for span in spans:
                if str(span.get("episode_id")) != str(neg["episode_id"]):
                    continue
                if spans_overlap(
                    int(span["start"]), int(span["end"]), int(neg["start"]), int(neg["end"])
                ):
                    hits.append(claim["claim_id"])
                    traps_hit.add(neg["negative_id"])
                    per_kind[neg["kind"]] = per_kind.get(neg["kind"], 0) + 1
                    break
            else:
                continue
            break
    return {
        "status": "scored",
        "negatives_in_split": len(negatives),
        "false_candidate_claims": len(hits),
        # DILUIBLE a proposito y con aviso: el denominador son los claims
        # emitidos, asi que emitir mas claims correctos baja la tasa sin haber
        # mejorado nada en las trampas. Por eso NO es la cifra de cabecera.
        "false_candidate_rate": ratio(len(hits), len(pred.claims)),
        # NO diluible: cuantas de las trampas del split se han pisado. El
        # denominador lo fija el dataset, no el sistema medido.
        "traps_hit": len(traps_hit),
        "traps_total": len(negatives),
        "trap_hit_rate": ratio(len(traps_hit), len(negatives)),
        "trap_ids_hit": sorted(traps_hit),
        # Claims en un episodio con trampa que el bundle no permite anclar.
        "unanchored_claims_in_trap_episodes": len(unanchored),
        "by_kind": dict(sorted(per_kind.items())),
        "claim_ids": sorted(hits),
    }


# --------------------------------------------------------------------------
# Resolutor
# --------------------------------------------------------------------------
def score_resolver(
    gold: GoldDataset, pred: PredictionBundle, config: MatchConfig
) -> dict[str, Any]:
    if not pred.resolutions:
        return _skip("la prediccion no trae resoluciones")

    if pred.mentions:
        alignment = build_alignment(
            match_spans(gold.mentions, pred.mentions, id_field="mention_id", config=config)
        )
    else:
        # El resolutor puede alimentarse de las menciones gold; entonces los
        # identificadores YA son los del gold y no hay nada que alinear.
        alignment = {m["mention_id"]: m["mention_id"] for m in gold.mentions}

    gold_assign = gold.mention_to_entity()
    raw_pred_assign = _assignment(pred.resolutions)
    pred_assign = {
        alignment[m]: e for m, e in raw_pred_assign.items() if m in alignment
    }
    mapping = align_clusters(gold_assign, pred_assign, pinned=gold.catalog_entity_ids)

    correct = 0
    for mention, gold_entity in gold_assign.items():
        pred_entity = pred_assign.get(mention)
        if pred_entity is not None and mapping.get(pred_entity) == gold_entity:
            correct += 1

    # --- accion (enlazar / crear / crear provisional) ----------------------
    def action_key(res: dict[str, Any], align: dict[str, str] | None) -> tuple | None:
        ids = res.get("mention_ids") or []
        if align is not None:
            mapped = [align.get(m) for m in ids]
            if any(m is None for m in mapped):
                return None
            ids = [m for m in mapped if m]
        return tuple(sorted(ids))

    gold_actions = {action_key(r, None): r["action"] for r in gold.resolutions}
    matched = correct_action = 0
    for res in pred.resolutions:
        key = action_key(res, alignment)
        if key in gold_actions:
            matched += 1
            if gold_actions[key] == res.get("action"):
                correct_action += 1

    return {
        "status": "scored",
        "identity_accuracy": accuracy(correct, len(gold_assign)),
        "mentions_unassigned_by_prediction": len(gold_assign)
        - len([m for m in gold_assign if m in pred_assign]),
        **duplicate_rate(gold_assign, pred_assign),
        **over_merge_rate(gold_assign, pred_assign),
        "action_accuracy": accuracy(correct_action, matched),
        # Exactitud de accion sobre el gold ENTERO: no resolver un grupo no
        # puede salir gratis en la tabla.
        "action_accuracy_strict": accuracy(correct_action, len(gold.resolutions)),
        "resolution_groups_matched": matched,
        "resolution_groups_gold": len(gold.resolutions),
        "resolution_coverage": ratio(matched, len(gold.resolutions)),
        "cluster_alignment": {
            "strategy": "voraz por solape descendente; los ids del catalogo quedan fijados",
            "mapping_size": len(mapping),
        },
    }


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------
_ACCEPT = "ACCEPT"


def _accept_tuple(d: dict[str, Any]) -> tuple:
    return (
        d.get("predicate"),
        d.get("direction"),
        d.get("subject_entity_id"),
        d.get("object_entity_id"),
        bool(d.get("negated")),
    )


def score_engine(gold: GoldDataset, pred: PredictionBundle) -> dict[str, Any]:
    decisions = pred.decisions or [d for p in pred.plans for d in p.get("decisions", [])]
    if not decisions:
        return _skip("la prediccion no trae decisiones del motor (ni sueltas ni en plan)")

    gold_decisions = gold.decisions
    match = match_by_key(
        gold_decisions,
        decisions,
        id_field="decision_id",
        key_fn=lambda d: str(d["claim_id"]),
    )
    gold_by_id = index_by(gold_decisions, "decision_id")
    pred_by_id = index_by(decisions, "decision_id")
    pairs = [(gold_by_id[g], pred_by_id[p]) for g, p in sorted(match.pairs)]

    axes = {
        "predicate": lambda d: d.get("predicate"),
        "direction": lambda d: d.get("direction"),
        "epistemic": lambda d: d.get("epistemic_status"),
    }
    #: Decisiones gold que ninguna prediccion cubrio, y predicciones que no
    #: cubren ningun gold. Los ejes ESTRICTOS las cuentan; los emparejados no.
    gold_sin_cubrir = [gold_by_id[g] for g in match.unmatched_gold]
    pred_sin_gold = [pred_by_id[p] for p in match.unmatched_pred]

    axis_scores: dict[str, Any] = {}
    for name, getter in axes.items():
        tp = fp = fn = 0
        for g, p in pairs:
            gv, pv = getter(g), getter(p)
            if pv is not None and gv is not None and pv == gv:
                tp += 1
            else:
                if pv is not None:
                    fp += 1
                if gv is not None:
                    fn += 1
        axis_scores[name] = prf(tp, fp, fn)
        # Variante ESTRICTA: el denominador es el gold ENTERO. Un motor que
        # solo decide sobre una de veintiuna no puede publicar F1=1.0.
        axis_scores[f"{name}_strict"] = prf(
            tp,
            fp + sum(1 for d in pred_sin_gold if getter(d) is not None),
            fn + sum(1 for d in gold_sin_cubrir if getter(d) is not None),
        )

    # Negacion: es una deteccion binaria, no una etiqueta entre muchas.
    tp = sum(1 for g, p in pairs if g.get("negated") and p.get("negated"))
    fp = sum(1 for g, p in pairs if not g.get("negated") and p.get("negated"))
    fn = sum(1 for g, p in pairs if g.get("negated") and not p.get("negated"))
    axis_scores["negation"] = prf(tp, fp, fn)
    axis_scores["negation_strict"] = prf(
        tp,
        fp + sum(1 for d in pred_sin_gold if d.get("negated")),
        fn + sum(1 for d in gold_sin_cubrir if d.get("negated")),
    )

    correct_decision = sum(1 for g, p in pairs if g["decision"] == p["decision"])
    pred_accepts = [(g, p) for g, p in pairs if p["decision"] == _ACCEPT]
    gold_accepts = [(g, p) for g, p in pairs if g["decision"] == _ACCEPT]
    false_approve = [
        p["decision_id"]
        for g, p in pred_accepts
        if g["decision"] != _ACCEPT or _accept_tuple(g) != _accept_tuple(p)
    ]
    false_reject = [
        p["decision_id"] for g, p in gold_accepts if p["decision"] == "REJECT_INVALID"
    ]
    abstained = [(g, p) for g, p in pairs if p["decision"] == "ABSTAIN"]
    reviewed = [(g, p) for g, p in pairs if p["decision"] == "REVIEW"]

    gold_frag_ids = {f["fragment_id"] for f in gold.fragments}
    with_evidence = sum(
        1
        for d in decisions
        if d.get("evidence_fragment_ids")
        and all(f in gold_frag_ids for f in d["evidence_fragment_ids"])
    )

    result: dict[str, Any] = {
        "status": "scored",
        "decisions_matched": len(pairs),
        "decisions_gold": len(gold_decisions),
        "decisions_predicted": len(decisions),
        "decisions_unmatched_predicted": match.fp,
        "decisions_missing": match.fn,
        "decision_coverage": ratio(len(pairs), len(gold_decisions)),
        "decision_accuracy": accuracy(correct_decision, len(pairs)),
        # Exactitud sobre el gold ENTERO: no decidir es no acertar.
        "decision_accuracy_strict": accuracy(correct_decision, len(gold_decisions)),
        **axis_scores,
        "false_approve_count": len(false_approve),
        "false_approve_rate": ratio(len(false_approve), len(pred_accepts)),
        "false_approve_decision_ids": sorted(false_approve),
        "false_reject_count": len(false_reject),
        "false_reject_rate": ratio(len(false_reject), len(gold_accepts)),
        "abstention_rate": ratio(len(abstained), len(pairs)),
        "abstention_agreement": accuracy(
            sum(1 for g, _p in abstained if g["decision"] == "ABSTAIN"), len(abstained)
        ),
        "review_rate": ratio(len(reviewed), len(pairs)),
        "review_agreement": accuracy(
            sum(1 for g, _p in reviewed if g["decision"] == "REVIEW"), len(reviewed)
        ),
        "evidence_validity": accuracy(with_evidence, len(decisions)),
        "temporal": _score_temporal(gold, pred),
    }
    return result


def _score_temporal(gold: GoldDataset, pred: PredictionBundle) -> dict[str, Any]:
    """Eje temporal: se materializa en las afirmaciones, no en las decisiones."""
    if not pred.assertions:
        return _skip("la prediccion no trae afirmaciones; el eje temporal no se puede medir")
    config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
    gold_keyed = [
        {"assertion_id": a["assertion_id"], "_key": fact_key(a, config), "_doc": a}
        for a in gold.assertions
    ]
    pred_keyed = [
        {"assertion_id": a["assertion_id"], "_key": fact_key(a, config), "_doc": a}
        for a in pred.assertions
    ]
    match = match_by_key(
        gold_keyed, pred_keyed, id_field="assertion_id", key_fn=lambda a: a["_key"]
    )
    gold_by_id = {a["assertion_id"]: a["_doc"] for a in gold_keyed}
    pred_by_id = {a["assertion_id"]: a["_doc"] for a in pred_keyed}

    fields = ("valid_from", "valid_to", "event_time", "state")
    correct = 0
    per_field = {f: 0 for f in fields}
    for gid, pid in match.pairs:
        g, p = gold_by_id[gid], pred_by_id[pid]
        ok = True
        for f in fields:
            if g.get(f) == p.get(f):
                per_field[f] += 1
            else:
                ok = False
        correct += 1 if ok else 0
    # Supersesion por CLAVE DE HECHO, nunca por identificador: exigir el
    # `assertion_id` literal del gold haria que un sistema real perfecto, que
    # nombra sus propias afirmaciones, sacase 0.0.
    gold_assert_by_id = {a["assertion_id"]: a for a in gold.assertions}
    pred_assert_by_id = {a["assertion_id"]: a for a in pred.assertions}
    pred_by_key: dict[Any, list[dict[str, Any]]] = {}
    for a in pred.assertions:
        k = fact_key(a, config)
        if k is not None:
            pred_by_key.setdefault(k, []).append(a)

    supersession_gold = [a for a in gold.assertions if a.get("superseded_by")]
    supersession_ok = 0
    for a in supersession_gold:
        sucesora_gold = gold_assert_by_id.get(a["superseded_by"])
        clave = fact_key(a, config)
        clave_sucesora = fact_key(sucesora_gold, config) if sucesora_gold else None
        for candidata in pred_by_key.get(clave, []):
            sucesora_pred = pred_assert_by_id.get(candidata.get("superseded_by"))
            if sucesora_pred is None:
                continue
            if fact_key(sucesora_pred, config) == clave_sucesora:
                supersession_ok += 1
                break
    return {
        "status": "scored",
        "assertions_matched": len(match.pairs),
        "temporal_tuple_accuracy": accuracy(correct, len(match.pairs)),
        "per_field_accuracy": {
            f: ratio(per_field[f], len(match.pairs)) for f in fields
        },
        "supersession_recall": accuracy(supersession_ok, len(supersession_gold)),
    }


# --------------------------------------------------------------------------
# Extremo a extremo
# --------------------------------------------------------------------------
def score_e2e(gold: GoldDataset, pred: PredictionBundle, config: MatchConfig) -> dict[str, Any]:
    if not pred.assertions:
        return _skip("la prediccion no trae afirmaciones")

    gold_keys = {k for k in (fact_key(a, config) for a in gold.assertions) if k is not None}
    pred_key_list = [fact_key(a, config) for a in pred.assertions]
    pred_keys = {k for k in pred_key_list if k is not None}
    facts = set_prf(gold_keys, pred_keys)

    gold_frag_ids = {f["fragment_id"] for f in gold.fragments}
    gold_episode_ids = {e["episode_id"] for e in gold.episodes}
    complete = dangling = 0
    for a in pred.assertions:
        frags = a.get("evidence_fragment_ids") or []
        eps = a.get("episode_ids") or []
        unknown = [f for f in frags if f not in gold_frag_ids] + [
            e for e in eps if e not in gold_episode_ids
        ]
        if unknown:
            dangling += 1
        if frags and eps and not unknown:
            complete += 1

    approved_plans = [p for p in pred.plans if (p.get("local_approval") or {}).get("approved")]
    gold_decision_by_claim = {d["claim_id"]: d for d in gold.decisions}
    false_plans = []
    for plan in approved_plans:
        for d in plan.get("decisions", []):
            if d.get("decision") != _ACCEPT:
                continue
            g = gold_decision_by_claim.get(d.get("claim_id"))
            if g is None or g["decision"] != _ACCEPT or _accept_tuple(g) != _accept_tuple(d):
                false_plans.append(plan["plan_id"])
                break

    return {
        "status": "scored",
        "facts": facts,
        "gold_facts": len(gold_keys),
        "predicted_facts": len(pred_keys),
        "unevaluable_predicted_assertions": sum(1 for k in pred_key_list if k is None),
        "duplicate_fact_rate": ratio(
            len(pred_key_list) - len(pred_keys), len(pred_key_list)
        ),
        "provenance_completeness": accuracy(complete, len(pred.assertions)),
        "dangling_provenance": dangling,
        "approved_plans": len(approved_plans),
        "false_approved_plans": len(set(false_plans)),
        "false_approved_plan_rate": ratio(len(set(false_plans)), len(approved_plans)),
    }


# --------------------------------------------------------------------------
# Orquestacion
# --------------------------------------------------------------------------
def gold_summary(gold: GoldDataset) -> dict[str, Any]:
    return {
        "split": gold.split,
        "dataset_version": gold.manifest.get("dataset_version"),
        "sources": len(gold.sources),
        "worlds": sorted({s.world for s in gold.sources}),
        "episodes": len(gold.episodes),
        "fragments": len(gold.fragments),
        "mentions": len(gold.mentions),
        "resolutions": len(gold.resolutions),
        "claims": len(gold.claims),
        "claims_extractor_gold": len(gold.claims_for("extractor")),
        "assertions": len(gold.assertions),
        "plans": len(gold.plans),
        "decisions": len(gold.decisions),
        "negatives": len(gold.negatives),
        "entities": len(gold.entities),
    }


def run(
    gold: GoldDataset,
    pred: PredictionBundle,
    *,
    config: MatchConfig | None = None,
    ablation: Ablation | str | None = None,
) -> dict[str, Any]:
    """Puntua una prediccion contra el gold y devuelve el informe completo."""
    if pred.split != gold.split:
        raise ValueError(
            f"la prediccion declara split {pred.split!r} y el gold es {gold.split!r}: "
            "medir una cosa contra otra es exactamente el error que este arnes evita"
        )
    abl = ablation if isinstance(ablation, Ablation) else resolve_ablation(
        ablation or pred.ablation
    )
    config = config or MatchConfig(symmetric_predicates=gold.symmetric_predicates)

    return {
        "benchmark_format_version": BENCHMARK_FORMAT_VERSION,
        "split": gold.split,
        "run_id": pred.run_id,
        "subsystem": pred.subsystem,
        "ablation": abl.as_dict(),
        "match_config": config.as_dict(),
        "gold": gold_summary(gold),
        "prediction": {
            "episodes": len(pred.episodes),
            "fragments": len(pred.fragments),
            "mentions": len(pred.mentions),
            "resolutions": len(pred.resolutions),
            "claims": len(pred.claims),
            "decisions": len(pred.decisions),
            "assertions": len(pred.assertions),
            "plans": len(pred.plans),
        },
        "normalizer": score_normalizer(gold, pred),
        "extractor": score_extractor(gold, pred, config),
        "resolver": score_resolver(gold, pred, config),
        "engine": score_engine(gold, pred),
        "e2e": score_e2e(gold, pred, config),
        "resources": _resources(pred),
    }


def _resources(pred: PredictionBundle) -> dict[str, Any]:
    """Latencia, RAM, llamadas y coste los MIDE quien ejecuta, no el arnes.

    Se copian tal cual si vienen; jamas se estiman. Un coste inventado en un
    informe es peor que no tener coste.
    """
    reported = {
        k: v
        for k, v in (pred.metadata or {}).items()
        if k in ("latency_ms", "peak_rss_mb", "provider_calls", "external_cost_usd")
    }
    if not reported:
        return _skip("el ejecutor no reporto recursos; el arnes no los estima")
    return {"status": "reported_by_runner", **reported}


__all__ = [
    "TRUNCATION_TOLERANCE",
    "clusters_from_candidates",
    "episode_text",
    "gold_summary",
    "run",
    "score_e2e",
    "score_engine",
    "score_extractor",
    "score_normalizer",
    "score_resolver",
]
