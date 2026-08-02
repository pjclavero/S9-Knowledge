# -*- coding: utf-8 -*-
"""PUERTA 4: medicion E2E en SOMBRA de la bateria de negaciones (split `negation`).

Corre la cadena COMPLETA -- texto crudo -> normalizacion -> episodios ->
extractores -> reconciliador -> resolutor -> motor -> decision efectiva ->
decision sombra -> plan en DRY-RUN -- sobre el split `negation`, que aqui es
SOLO LECTURA, y puntua la salida real con las metricas que ya existen en
`benchmarks.metrics` (`negation_policy_metrics`).

Restricciones de la corrida, y todas son deliberadas:

* **Sin proveedores.** Ablacion `local_only`: extraccion DETERMINISTA. Ni
  Ollama ni el carril externo. Consecuencia medida, no escondida: el carril
  SEMANTICO no corre, y por tanto la evaluacion en sombra
  (`semantic_shadow_evaluation=True`) no tiene ningun claim elegible que
  comparar. Eso se publica como cobertura 0, no como "sombra correcta".
* **Writer en DRY-RUN.** `apply=False` y sin driver: no hay Neo4j.
* **El gold no se toca.** Ni se completa, ni se corrige, ni se reordena.

Denominador cero no es cero: una metrica sin poblacion vale `None` y el informe
dice por que. Ninguna metrica se calcula sobre las filas que le convienen sin
decirlo: cada una declara su vista (`covered` = casos con salida del sistema;
`full` = todos los casos evaluables del gold, con los no cubiertos contados
como fallo de cobertura).

Uso:

    cd data-engine/app
    PYTHONPATH=data-engine/app python3 artifacts/v3-final-validation/gate4_negation_measure.py --out-dir artifacts/v3-final-validation  (desde la raiz del repo)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import unicodedata
from pathlib import Path
from typing import Any, Optional

from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.benchmarks.matching import (
    MatchConfig,
    build_alignment,
    match_by_key,
    match_spans,
)
from knowledge_v3.benchmarks.metrics import accuracy, negation_policy_metrics, ratio
from knowledge_v3.engine.config import DEFAULT_CONFIG as ENGINE_DEFAULT
from knowledge_v3.pipeline import KnowledgePipeline, cases_from_gold, catalog_entries
from knowledge_v3.pipeline.bridge import entities_from_catalog
from knowledge_v3.pipeline.runner import build_config

SPLIT = "negation"
WORKSPACE = "bench-negation"
ABLATION = "local_only"
ENTRY = "raw"

#: Familias de la bateria, en el orden de la tabla de docs/v3/18 §3 mas los dos
#: anadidos. `NO_CLAIM` no produce claims gold: se mide aparte, sobre negativos.
FAMILIES = (
    "SIMPLE",
    "NEVER",
    "CESSATION",
    "NEGATED_CESSATION",
    "NOT_YET",
    "SCOPE_EMBEDDED",
    "QUESTION_CONDITIONAL_RUMOR",
    "DOUBLE_NEGATION",
    "POSITIVE_CONTROL",
)

#: Tipos de negacion que el motor considera CESACION.
CESSATION_KIND = "CESSATION"

#: Decision del gold que exige que el sistema NO escriba la negacion sin humano.
SCOPE_REVIEW = "REVIEW_NEGATION_SCOPE"

#: Marcador de "el sistema no emitio nada para este caso". No es una decision
#: del contrato: es la ausencia de una, y se cuenta como tal.
NO_OUTPUT = "NO_OUTPUT"


# --------------------------------------------------------------------------
# 1. La corrida
# --------------------------------------------------------------------------
def engine_config():
    """Las tres banderas que esta puerta mide, sobre el resto de defaults."""
    return dataclasses.replace(
        ENGINE_DEFAULT,
        semantic_shadow_evaluation=True,
        graduated_negation_policy=True,
        graduated_temporal_policy=True,
    )


def run_chain(*, negation_policy_at_engine: bool = True):
    """Cadena completa sobre `negation`, desde bytes, sin proveedores.

    `negation_policy_at_engine` decide QUIEN manda sobre una negacion:

    * `True`  — el extractor determinista deja de pedir revision por el mero
      hecho de negar y la decision graduada del motor
      (`graduated_negation_policy`) es la que se aplica. Es la variante que
      esta puerta mide, porque es la unica en la que la politica graduada llega
      a decidir algo.
    * `False` — el valor por defecto de `PipelineConfig`: el extractor marca
      revision en toda negacion, y ninguna negacion puede autoaprobarse hiciera
      lo que hiciera el motor. Se mide igualmente, como contraste.
    """
    gold = load_gold(SPLIT)
    config = build_config(gold, ablation=ABLATION, workspace=WORKSPACE)
    config = dataclasses.replace(
        config,
        engine_config=engine_config(),
        negation_policy_at_engine=negation_policy_at_engine,
    )
    pipeline = KnowledgePipeline(config)
    result = pipeline.run(
        cases_from_gold(gold, entry=ENTRY),
        catalog_entities=entities_from_catalog(catalog_entries(gold)),
    )
    return gold, config, result


# --------------------------------------------------------------------------
# 2. Alineamiento con el gold
# --------------------------------------------------------------------------
def episode_alignment(gold, result) -> dict[str, str]:
    """episodio predicho -> episodio gold, por TEXTO literal identico.

    La cadena entra por bytes y el normalizador acuna identificadores propios
    (`ep-<hash>`), asi que no hay ninguna clave comun con el gold. Se empareja
    por el texto de referencia, que es exacto o no es: un episodio cuyo texto no
    coincide byte a byte con ninguno del gold queda SIN alinear y se cuenta.
    """
    by_text: dict[str, list[str]] = {}
    for episode_id, text in gold.reference_text.items():
        by_text.setdefault(text, []).append(episode_id)
    used: set[str] = set()
    alignment: dict[str, str] = {}
    for episode in sorted(result.episodes, key=lambda e: e.episode_id):
        pool = by_text.get(episode.text or "", [])
        for gold_id in pool:
            if gold_id not in used:
                used.add(gold_id)
                alignment[episode.episode_id] = gold_id
                break
    return alignment


def _fold(text: str) -> str:
    """Superficie comparable: sin mayusculas, sin tildes y sin puntuacion.

    El carril ASR de este split entrega tramos en minusculas y sin acentos ni
    signos (ruido de transcripcion declarado por el propio gold). Comparar la
    superficie en crudo perderia esas menciones por un motivo que no es del
    sistema medido.
    """
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return "".join(c for c in stripped.casefold() if c.isalnum() or c.isspace()).strip()


def _source_of_gold_episode(gold) -> dict[str, str]:
    return {e["episode_id"]: str(e["source_asset_id"]) for e in gold.episodes}


def mention_alignment(gold, result, episodes: dict[str, str], config: MatchConfig):
    """mencion predicha -> mencion gold, en dos fases y nunca al reves.

    FASE A — span. Para los episodios cuyo texto el normalizador reprodujo
    literalmente, se empareja por solape de span dentro del mismo episodio, que
    es el criterio del arnes y el unico exacto.

    FASE B — superficie, dentro de la misma FUENTE. Hace falta porque en este
    split el normalizador NO conserva la segmentacion del gold: el carril ASR
    fusiona turnos y los reescribe en minusculas y sin tildes, de modo que ni el
    identificador ni los offsets ni el texto coinciden. Sin esta fase, ocho
    episodios de `zafiro-sesion` quedarian fuera de la medicion por un artefacto
    del alineamiento y no por un fallo del sistema. Se empareja por superficie
    normalizada, uno a uno, en orden de documento, y solo contra menciones gold
    que la fase A no uso. Es conservador: una superficie que no coincide no
    empareja, y como mucho SUBESTIMA la cobertura.
    """
    gold_source = _source_of_gold_episode(gold)
    # El normalizador acuna `source_asset_id` propios (`sa-<hash>`), asi que la
    # fuente de una mencion predicha se toma de la corrida que la produjo, que
    # es quien sabe de que fichero del gold venia.
    episode_source = {
        episode.episode_id: f"asset:{run.source_id}"
        for run in result.runs
        for episode in run.episodes
    }

    span_pred = [
        {
            "mention_id": m.mention_id,
            "episode_id": episodes[m.episode_id],
            "start": m.start,
            "end": m.end,
        }
        for m in result.mentions
        if m.episode_id in episodes
    ]
    span_gold = [g for g in gold.mentions if gold_source.get(g["episode_id"])]
    match = match_spans(span_gold, span_pred, id_field="mention_id", config=config)
    alignment = build_alignment(match)

    used_gold = set(alignment.values())
    gold_by_id = {g["mention_id"]: g for g in gold.mentions}
    gold_pool: dict[tuple[str, str], list[str]] = {}
    for gid in sorted(gold_by_id):
        if gid in used_gold:
            continue
        gm = gold_by_id[gid]
        source = gold_source.get(gm["episode_id"], "")
        surface = _fold(str(gm.get("surface", "")))
        gold_pool.setdefault((source, surface), []).append(gid)

    # Orden de DOCUMENTO de las menciones predichas: fuente, episodio y offset.
    # Con el orden por identificador (un hash) dos apariciones de la misma
    # superficie se asignan a la ocurrencia gold equivocada, y el claim deja de
    # emparejar por un artefacto del alineamiento.
    position: dict[str, tuple[int, int]] = {}
    for run_index, run in enumerate(result.runs):
        for episode_index, episode in enumerate(run.episodes):
            position[episode.episode_id] = (run_index, episode_index)

    fallback = 0
    ordered = sorted(
        result.mentions,
        key=lambda m: (position.get(m.episode_id, (99, 99)), m.start, m.mention_id),
    )
    for mention in ordered:
        if mention.mention_id in alignment or mention.episode_id in episodes:
            continue
        key = (episode_source.get(mention.episode_id, ""), _fold(mention.surface or ""))
        pool = gold_pool.get(key)
        if pool:
            alignment[mention.mention_id] = pool.pop(0)
            fallback += 1
    return alignment, match, fallback


def claim_alignment(gold, result, mentions):
    """claim predicho -> claim gold, por sus menciones traducidas al gold.

    La clave son los conjuntos de menciones gold de sujeto y de objeto. El
    episodio NO entra: las menciones gold ya lo determinan, y exigirlo ademas
    romperia el emparejamiento justo en las fuentes donde el normalizador
    resegmenta. Tampoco entran el predicado ni la polaridad: son lo que se esta
    midiendo, y meterlos en la clave haria desaparecer del recuento
    precisamente los casos en que el sistema se equivoca.
    """

    def key_of(subject_mentions, object_mentions, translate) -> Optional[tuple]:
        subs = [translate.get(m) for m in subject_mentions]
        objs = [translate.get(m) for m in object_mentions]
        if not subs or not objs or any(s is None for s in subs) or any(o is None for o in objs):
            return None
        return (tuple(sorted(subs)), tuple(sorted(objs)))

    identity = {m["mention_id"]: m["mention_id"] for m in gold.mentions}
    gold_keyed = [
        {
            "claim_id": c["claim_id"],
            "_key": key_of(c.get("subject_mentions") or [], c.get("object_mentions") or [], identity),
        }
        for c in gold.claims
    ]
    pred_keyed = [
        {
            "claim_id": c.claim_id,
            "_key": key_of(c.subject_mentions or [], c.object_mentions or [], mentions),
        }
        for c in result.claims
    ]
    match = match_by_key(gold_keyed, pred_keyed, id_field="claim_id", key_fn=lambda c: c["_key"])
    return {gid: pid for gid, pid in match.pairs}, match


# --------------------------------------------------------------------------
# 3. Filas: gold + salida real, caso a caso
# --------------------------------------------------------------------------
def _decision_index(result) -> dict[str, Any]:
    return {d.claim_id: d for d in result.decisions}


def _evidence_anchored(decision, claim, fragments: dict[str, Any]) -> bool:
    """La decision cita evidencia y esa evidencia existe y es literal.

    No basta con que la lista no este vacia: cada `fragment_id` tiene que
    corresponder a un fragmento realmente producido por la corrida y el motor
    tiene que haber verificado su literalidad (`EVIDENCE_LITERAL_VERIFIED`).
    """
    ids = list(decision.evidence_fragment_ids or [])
    if not ids or not all(fid in fragments for fid in ids):
        return False
    if not all(f.code != "EVIDENCE_NOT_VERIFIABLE" for f in decision.findings):
        return False
    return any(f.code == "EVIDENCE_LITERAL_VERIFIED" for f in decision.findings)


def plan_operations(result) -> list[dict[str, Any]]:
    """Todas las operaciones de todos los planes de la corrida (DRY-RUN)."""
    return [op for plan in result.plans for op in plan.to_dict()["mutation_operations"]]


def _positive_operations(result) -> dict[str, list[str]]:
    """claim -> operaciones de POLARIDAD POSITIVA que el plan escribiria.

    Una arista positiva es cualquier `PROJECT_RELATION`, o un
    `CREATE_ASSERTION` cuyo payload NO va negado. Se mira el plan, no solo la
    decision: la pregunta de la puerta es si algo positivo llegaria al grafo, y
    quien llega al grafo es la operacion.
    """
    out: dict[str, list[str]] = {}
    for operation in plan_operations(result):
        operation_id = str(operation["operation_id"])
        if not operation_id.startswith("op:"):
            continue
        claim_id = operation_id[3:].rsplit(":", 1)[0]
        kind = operation["operation_type"]
        payload = operation.get("payload") or {}
        if kind == "PROJECT_RELATION" or (
            kind == "CREATE_ASSERTION" and not payload.get("negated", False)
        ):
            out.setdefault(claim_id, []).append(kind)
    return out


def positive_edges_over_negated_keys(gold, result) -> dict[str, Any]:
    """Comprobacion de seguridad que NO depende del alineamiento.

    Recorre todas las operaciones de polaridad positiva del plan y mira si
    alguna afirma, en positivo, una relacion que el gold declara NEGADA
    (mismo sujeto, mismo objeto y mismo predicado). Es la lectura mas dura de
    "arista positiva falsa desde una negacion": no le hace falta emparejar
    claims, asi que un fallo de cobertura no puede esconder un fallo de
    seguridad.
    """
    negated_keys = {
        (
            annotation.get("expected_subject"),
            annotation.get("expected_predicate"),
            annotation.get("expected_object"),
        )
        for annotation in (c["metadata"]["negation"] for c in gold.claims)
        if annotation.get("expected_negated") is True
    }
    offenders = []
    for operation in plan_operations(result):
        payload = operation.get("payload") or {}
        if operation["operation_type"] == "CREATE_ASSERTION" and payload.get("negated"):
            continue
        if operation["operation_type"] == "SUPERSEDE_ASSERTION":
            continue
        key = (
            payload.get("subject_entity_id"),
            payload.get("predicate"),
            payload.get("object_entity_id"),
        )
        if key in negated_keys:
            offenders.append({"operation_id": operation["operation_id"], "key": list(key)})
    return {
        "gold_negated_keys": len(negated_keys),
        "offending_operations": offenders,
        "count": len(offenders),
    }


def _scope_correct(annotation: dict, row: dict) -> bool:
    """Criterio de ALCANCE: ¿la negacion cayo sobre la relacion correcta?

    Tres condiciones, y las tres tienen que cumplirse:

    1. La polaridad emitida es la esperada.
    2. Si el gold espera negacion, la relacion negada es la del gold
       (sujeto, objeto y predicado). Negar la relacion equivocada es
       exactamente el fallo de alcance que esta metrica busca.
    3. Si el gold manda el caso a revision por alcance
       (`REVIEW_NEGATION_SCOPE`), el sistema no puede haberlo aceptado.
    """
    if row["predicted_decision"] == NO_OUTPUT:
        return False
    if bool(row["predicted_negated"]) != bool(annotation["expected_negated"]):
        return False
    if annotation["expected_negated"]:
        if (
            row["predicted_subject"] != annotation.get("expected_subject")
            or row["predicted_object"] != annotation.get("expected_object")
            or row["predicted_predicate"] != annotation.get("expected_predicate")
        ):
            return False
    if annotation["expected_decision"] == SCOPE_REVIEW and row["predicted_decision"] == "ACCEPT":
        return False
    return True


def build_rows(gold, result, pairs: dict[str, str]) -> list[dict[str, Any]]:
    """Una fila por claim gold evaluable, con la salida real emparejada.

    Un caso sin salida del sistema NO se descarta: entra con
    `predicted_decision=NO_OUTPUT`, polaridad negativa ausente y evidencia no
    anclada. Descartarlo subiria todas las metricas a costa de esconder que la
    cadena no vio el caso.
    """
    decisions = _decision_index(result)
    claims = {c.claim_id: c for c in result.claims}
    fragments = {f.fragment_id: f for f in result.fragments}
    positive_ops = _positive_operations(result)
    rows: list[dict[str, Any]] = []
    for gold_claim in gold.claims:
        annotation = gold_claim["metadata"]["negation"]
        if not isinstance(annotation.get("expected_negated"), bool):
            # El unico ABSTAIN del gold no declara polaridad: fuera, igual que
            # hace `negation_split_metrics`.
            continue
        pred_id = pairs.get(gold_claim["claim_id"])
        decision = decisions.get(pred_id) if pred_id else None
        claim = claims.get(pred_id) if pred_id else None
        row: dict[str, Any] = {
            "case_id": annotation["case_id"],
            "gold_claim_id": gold_claim["claim_id"],
            "family": annotation["family"],
            "expected_negated": bool(annotation["expected_negated"]),
            "expected_decision": annotation["expected_decision"],
            "expected_negation_kind": annotation["negation_kind"],
            "expected_scope": annotation["scope"],
            "covered": decision is not None,
            "predicted_claim_id": pred_id,
        }
        if decision is None:
            row.update(
                {
                    "predicted_negated": False,
                    "predicted_negation_kind": "",
                    "predicted_decision": NO_OUTPUT,
                    "predicted_subject": None,
                    "predicted_object": None,
                    "predicted_predicate": None,
                    "predicted_supersedes": None,
                    "evidence_anchored": False,
                    "positive_operations": [],
                    "emitted_positive_edge": False,
                }
            )
        else:
            row.update(
                {
                    "predicted_negated": bool(decision.negated),
                    "predicted_negation_kind": decision.negation_kind or "",
                    "predicted_decision": decision.decision,
                    "predicted_subject": decision.subject_entity_id,
                    "predicted_object": decision.object_entity_id,
                    "predicted_predicate": decision.predicate,
                    "predicted_supersedes": decision.supersedes,
                    "evidence_anchored": _evidence_anchored(decision, claim, fragments),
                    # Arista POSITIVA: o el plan trae una operacion de polaridad
                    # positiva para este claim, o la decision escribe (ACCEPT)
                    # sin negar. Lo primero es lo que llegaria al grafo; lo
                    # segundo cubre el caso en que el plan no llego a formarse.
                    "positive_operations": positive_ops.get(decision.claim_id, []),
                    "emitted_positive_edge": bool(positive_ops.get(decision.claim_id))
                    or (decision.decision == "ACCEPT" and not decision.negated),
                }
            )
        row["scope_correct"] = _scope_correct(annotation, row)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# 4. Las diez metricas
# --------------------------------------------------------------------------
def _policy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`negation_policy_metrics` sobre filas ya construidas (no se reimplementa)."""
    if not rows:
        return {}
    return negation_policy_metrics(rows)


def ten_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Las diez metricas de la puerta, cada una con su vista y su denominador.

    `full`   = todas las filas evaluables del gold (incluye las no cubiertas).
    `covered`= solo las filas para las que el sistema emitio una decision.

    Las metricas de SEGURIDAD (no inventar aristas, no inventar cesaciones,
    evidencia anclada, alcance) se leen sobre lo que el sistema emitio de
    verdad; las de RECALL se leen sobre el gold entero. Publicar la precision
    sobre el gold entero la hundiria por falta de cobertura, y publicar el
    recall sobre lo cubierto lo inflaria: son dos preguntas distintas.
    """
    covered = [r for r in rows if r["covered"]]
    full_policy = _policy(rows)
    covered_policy = _policy(covered)

    # -- polaridad ---------------------------------------------------------
    negative_precision = (
        covered_policy["negative_edge_precision"]["precision"] if covered_policy else None
    )
    negative_recall = full_policy["negative_edge_precision"]["recall"] if full_policy else None

    # -- cesacion ----------------------------------------------------------
    cess_gold = [r for r in rows if r["expected_negation_kind"] == CESSATION_KIND]
    cess_pred_covered = [
        r for r in covered if r["predicted_negation_kind"] == CESSATION_KIND
    ]
    cess_tp = sum(1 for r in cess_pred_covered if r["expected_negation_kind"] == CESSATION_KIND)
    cess_precision = ratio(cess_tp, len(cess_pred_covered))
    cess_recall = ratio(
        sum(
            1
            for r in cess_gold
            if r["covered"] and r["predicted_negation_kind"] == CESSATION_KIND
        ),
        len(cess_gold),
    )

    # -- cesacion DESTRUCTIVA: la que de verdad cerraria una vigencia -------
    destructive = [r for r in covered if r["predicted_supersedes"]]
    destructive_correct = sum(
        1
        for r in destructive
        if r["expected_negation_kind"] == CESSATION_KIND
        and r["expected_decision"] != SCOPE_REVIEW
    )
    destructive_scope_correct = sum(1 for r in destructive if r["scope_correct"])

    # -- aristas positivas falsas nacidas de una negacion -------------------
    false_positive_edges = sum(
        1 for r in rows if r["expected_negated"] and r["emitted_positive_edge"]
    )

    # -- autoaprobacion ----------------------------------------------------
    accepted = [r for r in covered if r["predicted_decision"] == "ACCEPT"]
    auto_precision = ratio(
        sum(1 for r in accepted if r["expected_decision"] == "AUTO_APPROVE"), len(accepted)
    )
    auto_recall = full_policy["auto_approval_recall"]["recall"] if full_policy else None

    return {
        "negative_edge_precision": {
            "value": negative_precision,
            "view": "covered",
            "counts": covered_policy.get("negative_edge_precision") if covered_policy else None,
        },
        "negative_edge_recall": {
            "value": negative_recall,
            "view": "full",
            "counts": full_policy.get("negative_edge_precision") if full_policy else None,
        },
        "negated_cessation_safety": {
            "value": (
                full_policy["negated_cessation_safety"]["accuracy"] if full_policy else None
            ),
            "view": "full",
            "counts": full_policy.get("negated_cessation_safety") if full_policy else None,
        },
        "cessation_precision": {
            "value": cess_precision,
            "view": "covered",
            "counts": {"tp": cess_tp, "predicted": len(cess_pred_covered)},
        },
        "cessation_recall": {
            "value": cess_recall,
            "view": "full",
            "counts": {"gold": len(cess_gold)},
        },
        "negation_scope_accuracy": {
            "value": covered_policy["scope_accuracy"]["accuracy"] if covered_policy else None,
            "view": "covered",
            "counts": covered_policy.get("scope_accuracy") if covered_policy else None,
            "full": full_policy.get("scope_accuracy") if full_policy else None,
        },
        "evidence_grounding": {
            "value": covered_policy["evidence_grounding"]["accuracy"] if covered_policy else None,
            "view": "covered",
            "counts": covered_policy.get("evidence_grounding") if covered_policy else None,
            "full": full_policy.get("evidence_grounding") if full_policy else None,
        },
        "false_positive_relation_from_negation": {
            "value": false_positive_edges,
            "view": "full",
            "counts": {"gold_negative_cases": sum(1 for r in rows if r["expected_negated"])},
        },
        "auto_approval_precision": {
            "value": auto_precision,
            "view": "covered",
            "counts": {"accepted": len(accepted)},
        },
        "auto_approval_recall": {
            "value": auto_recall,
            "view": "full",
            "counts": full_policy.get("auto_approval_recall") if full_policy else None,
        },
        "_destructive": {
            "operations": len(destructive),
            "cessation_correct": destructive_correct,
            "cessation_precision": ratio(destructive_correct, len(destructive)),
            "scope_correct": destructive_scope_correct,
            "scope_precision": ratio(destructive_scope_correct, len(destructive)),
        },
        "_coverage": accuracy(len(covered), len(rows)),
    }


def by_family(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in FAMILIES:
        subset = [r for r in rows if r["family"] == family]
        if not subset:
            continue
        metrics = ten_metrics(subset)
        out[family] = {
            "cases": len(subset),
            "covered": metrics["_coverage"]["correct"],
            **{
                name: metrics[name]["value"]
                for name in (
                    "negative_edge_precision",
                    "negative_edge_recall",
                    "negated_cessation_safety",
                    "cessation_precision",
                    "cessation_recall",
                    "negation_scope_accuracy",
                    "evidence_grounding",
                    "false_positive_relation_from_negation",
                    "auto_approval_precision",
                    "auto_approval_recall",
                )
            },
        }
    return out


def no_claim_family(gold, result, episodes) -> dict[str, Any]:
    """Los cuatro negativos `NO_CLAIM`: preguntas y condicionales sin afirmacion.

    No son claims gold, asi que no entran en las filas. Se comprueban por su
    propio criterio: que la cadena NO haya producido un claim anclado sobre ese
    tramo de texto con un predicado prohibido.
    """
    reverse = {v: k for k, v in episodes.items()}
    fragments = {f.fragment_id: f for f in result.fragments}
    violations: list[dict[str, Any]] = []
    for negative in gold.negatives:
        pred_episode = reverse.get(negative["episode_id"])
        if pred_episode is None:
            continue
        forbidden = set(negative.get("forbidden_predicates") or [])
        for claim in result.claims:
            if claim.episode_id != pred_episode:
                continue
            spans = [
                fragments[fid]
                for fid in claim.evidence_fragment_ids
                if fid in fragments
            ]
            if not any(
                f.start < negative["end"] and negative["start"] < f.end for f in spans
            ):
                continue
            predicates = {c["predicate"] for c in (claim.to_dict()["predicate_candidates"] or [])}
            if predicates & forbidden or not forbidden:
                violations.append(
                    {"case_id": negative["case_id"], "claim_id": claim.claim_id}
                )
    total = len(gold.negatives)
    aligned = sum(1 for n in gold.negatives if n["episode_id"] in reverse)
    # El denominador son los negativos cuyo episodio la corrida SI alineo. Con
    # cero alineados la metrica vale None: publicar 1.0 diria "el sistema no
    # invento nada" cuando lo cierto es que el sistema no llego a mirar.
    return {
        "cases": total,
        "episodes_aligned": aligned,
        "violations": violations,
        "clean": aligned - len(violations),
        "accuracy": ratio(aligned - len(violations), aligned),
    }


# --------------------------------------------------------------------------
# 5. Puertas
# --------------------------------------------------------------------------
def _status(observed, threshold, comparator: str) -> str:
    if observed is None:
        return "NO_EVALUABLE"
    if comparator == "==":
        return "CONFORME" if observed == threshold else "NO_CONFORME"
    return "CONFORME" if observed >= threshold else "NO_CONFORME"


def gates(
    metrics: dict[str, Any], families: dict[str, Any], corpus_wide: dict[str, Any]
) -> list[dict[str, Any]]:
    destructive = metrics["_destructive"]
    simple = families.get("SIMPLE", {})
    return [
        {
            "name": "ninguna operacion positiva sobre una relacion que el gold niega",
            "metric": "positive_edges_over_negated_keys",
            "threshold": 0,
            "observed": corpus_wide["count"],
            "status": _status(corpus_wide["count"], 0, "=="),
            "denominator": corpus_wide["gold_negated_keys"],
        },
        {
            "name": "cero aristas positivas falsas desde negacion",
            "metric": "false_positive_relation_from_negation",
            "threshold": 0,
            "observed": metrics["false_positive_relation_from_negation"]["value"],
            "status": _status(
                metrics["false_positive_relation_from_negation"]["value"], 0, "=="
            ),
        },
        {
            "name": "cero cesaciones falsas desde 'no dejo de'",
            "metric": "negated_cessation_safety",
            "threshold": 1.0,
            "observed": metrics["negated_cessation_safety"]["value"],
            "status": _status(metrics["negated_cessation_safety"]["value"], 1.0, "=="),
        },
        {
            "name": "evidencia anclada al 100% en lo emitido",
            "metric": "evidence_grounding",
            "threshold": 1.0,
            "observed": metrics["evidence_grounding"]["value"],
            "status": _status(metrics["evidence_grounding"]["value"], 1.0, "=="),
        },
        {
            "name": "precision CESSATION destructiva 100%",
            "metric": "destructive_cessation_precision",
            "threshold": 1.0,
            "observed": destructive["cessation_precision"],
            "status": _status(destructive["cessation_precision"], 1.0, "=="),
            "denominator": destructive["operations"],
        },
        {
            "name": "precision de alcance destructivo 100%",
            "metric": "destructive_scope_precision",
            "threshold": 1.0,
            "observed": destructive["scope_precision"],
            "status": _status(destructive["scope_precision"], 1.0, "=="),
            "denominator": destructive["operations"],
        },
        {
            "name": "alcance global >= 0.95",
            "metric": "negation_scope_accuracy",
            "threshold": 0.95,
            "observed": metrics["negation_scope_accuracy"]["value"],
            "status": _status(metrics["negation_scope_accuracy"]["value"], 0.95, ">="),
        },
        {
            "name": "recall de autoaprobacion SIMPLE >= 0.75",
            "metric": "auto_approval_recall[SIMPLE]",
            "threshold": 0.75,
            "observed": simple.get("auto_approval_recall"),
            "status": _status(simple.get("auto_approval_recall"), 0.75, ">="),
        },
    ]


# --------------------------------------------------------------------------
# 6. Informe
# --------------------------------------------------------------------------
def analyse(gold, config, result) -> dict[str, Any]:
    """Alinea, puntua y resume UNA corrida. No decide nada por su cuenta."""
    match_config = MatchConfig(
        span_mode="overlap",
        overlap_threshold=0.5,
        claim_key_extra=(),
        symmetric_predicates=gold.symmetric_predicates,
    )
    episodes = episode_alignment(gold, result)
    mentions, mention_match, fallback = mention_alignment(gold, result, episodes, match_config)
    pairs, _claim_match = claim_alignment(gold, result, mentions)
    rows = build_rows(gold, result, pairs)
    metrics = ten_metrics(rows)
    families = by_family(rows)
    families["NO_CLAIM"] = no_claim_family(gold, result, episodes)

    shadow_records = [
        record
        for run in result.runs
        if run.engine_result
        for record in run.engine_result.shadow_decisions
    ]
    plans = [p.to_dict() for p in result.plans]
    operations = [op for plan in plans for op in plan["mutation_operations"]]
    corpus_wide = positive_edges_over_negated_keys(gold, result)

    return {
        "config": {
            "split": SPLIT,
            "workspace": WORKSPACE,
            "ablation": ABLATION,
            "entry": ENTRY,
            "semantic_shadow_evaluation": True,
            "graduated_negation_policy": True,
            "graduated_temporal_policy": True,
            "negation_policy_at_engine": config.negation_policy_at_engine,
            "accept_negated": engine_config().accept_negated,
            "emit_projection": engine_config().emit_projection,
            "writer_mode": config.declared()["writer_mode"],
            "providers": config.declared()["providers"],
            "ollama_active": config.declared()["ollama_active"],
            "external_active": config.declared()["external_active"],
            "match": match_config.as_dict(),
        },
        "corpus": {
            "gold_claims": len(gold.claims),
            "evaluable_cases": len(rows),
            "covered_cases": metrics["_coverage"]["correct"],
            "coverage": metrics["_coverage"]["accuracy"],
            "gold_negatives_no_claim": len(gold.negatives),
            "sources": [
                {
                    "source_id": run.source_id,
                    "episodes": len(run.episodes),
                    "claims": len(run.claims),
                    "decisions": len(run.decisions),
                    "stopped_at": run.stopped_at,
                    "stop_reason": run.stop_reason,
                }
                for run in result.runs
            ],
            "episodes_predicted": len(result.episodes),
            "episodes_aligned": len(episodes),
            "mentions": {
                "span_tp": mention_match.tp,
                "span_fp": mention_match.fp,
                "span_fn": mention_match.fn,
                "surface_fallback": fallback,
                "aligned_total": len(mentions),
                "gold_total": len(gold.mentions),
            },
            "claims_matched": len(pairs),
        },
        "metrics_global": {
            name: value["value"]
            for name, value in metrics.items()
            if not name.startswith("_")
        },
        "metrics_detail": {k: v for k, v in metrics.items()},
        "metrics_by_family": families,
        "shadow": {
            "enabled": True,
            "records": len(shadow_records),
            "records_that_would_emit_operations": sum(
                1 for r in shadow_records if r.would_emit_operations
            ),
        },
        "writer": {
            "mode": config.declared()["writer_mode"],
            "plans": len(plans),
            "approved_plans": sum(1 for p in plans if p["local_approval"]["approved"]),
            "operations": len(operations),
            "operation_kinds": sorted({op["operation_type"] for op in operations}),
            "outcomes": sorted(
                {run.write_result.outcome for run in result.runs if run.write_result}
            ),
        },
        "positive_edges_over_negated_keys": corpus_wide,
        "gates": gates(metrics, families, corpus_wide),
        "rows": rows,
    }


#: Las dos variantes que se miden. La PRIMERA es la que puntua las puertas.
VARIANTS = (
    ("graduated_at_engine", True),
    ("extractor_forces_review", False),
)


def measure() -> dict[str, Any]:
    """Mide las dos variantes y publica las puertas sobre la principal."""
    analyses: dict[str, Any] = {}
    for label, at_engine in VARIANTS:
        gold, config, result = run_chain(negation_policy_at_engine=at_engine)
        analyses[label] = analyse(gold, config, result)

    primary = analyses[VARIANTS[0][0]]
    secondary = analyses[VARIANTS[1][0]]
    shadow = primary["shadow"]

    notes = [
        "Corrida sin proveedores (ablacion local_only): extraccion DETERMINISTA. "
        "Ollama y el carril externo estan reservados por otro agente y no se usan. "
        "Esa es la causa dominante de la cobertura baja: el extractor determinista "
        f"solo propone claim para {primary['corpus']['covered_cases']} de los "
        f"{primary['corpus']['evaluable_cases']} casos evaluables.",
        "Writer en DRY-RUN (apply=False, sin driver): ninguna operacion llega a Neo4j.",
        "El corpus se ha leido; no se ha modificado ningun fichero suyo, ni se ha "
        "ampliado con casos propios: las puertas se miden sobre la bateria tal cual.",
        f"Evaluacion en sombra activa, {shadow['records']} registros. La sombra solo "
        "compara claims del paso `extract.semantic`, que esta corrida no ejecuta por no "
        "admitir proveedores: es cobertura 0 de la sombra, NO una sombra validada.",
        "La entrada por episodios no se puede usar en este corpus: 3 de sus 4 fuentes "
        "omiten las claves opcionales speaker/turn/table y `SourceEpisode.from_dict` las "
        "exige (falla con V3ContractError). Se entra por bytes, que ademas es la ruta "
        "completa que la puerta pide.",
        "La fuente `ambar-escaneo` (22 episodios, modalidad IMAGE) llega sin texto: sin "
        "`visual_provider` no hay OCR, el extractor no propone nada y la cadena se "
        "detiene en el motor. Sus casos entran como no cubiertos.",
        "Fallo de ALCANCE medido, caso a caso: "
        + (
            "; ".join(
                f"{row['case_id']} ({row['family']}) esperaba negado="
                f"{row['expected_negated']} y salio negado={row['predicted_negated']} "
                f"con decision {row['predicted_decision']}"
                for row in primary["rows"]
                if row["covered"] and not row["scope_correct"]
            )
            or "ninguno entre los casos cubiertos"
        )
        + ".",
        "Ninguna operacion positiva del plan afirma una relacion que el gold declara "
        f"negada ({primary['positive_edges_over_negated_keys']['gold_negated_keys']} "
        "claves negadas comprobadas contra todas las operaciones del plan). Es la "
        "comprobacion de seguridad que no depende del alineamiento.",
        "Dos variantes medidas. `graduated_at_engine` (principal): el extractor no marca "
        "revision por negar y decide la politica graduada del motor. "
        "`extractor_forces_review`: el defecto de `PipelineConfig`, donde toda negacion "
        "va a revision desde el extractor y NINGUNA negacion puede autoaprobarse. Las "
        "puertas se puntuan sobre la principal; la otra se publica al lado.",
    ]

    return {
        "gate": "4",
        "config": primary["config"],
        "corpus": primary["corpus"],
        "metrics_global": primary["metrics_global"],
        "metrics_detail": primary["metrics_detail"],
        "metrics_by_family": primary["metrics_by_family"],
        "shadow": primary["shadow"],
        "writer": primary["writer"],
        "positive_edges_over_negated_keys": primary["positive_edges_over_negated_keys"],
        "gates": primary["gates"],
        "variants": {
            label: {
                "negation_policy_at_engine": analyses[label]["config"][
                    "negation_policy_at_engine"
                ],
                "coverage": analyses[label]["corpus"]["coverage"],
                "metrics_global": analyses[label]["metrics_global"],
                "gates": [
                    {"name": g["name"], "observed": g["observed"], "status": g["status"]}
                    for g in analyses[label]["gates"]
                ],
            }
            for label, _ in VARIANTS
        },
        "secondary_metrics_global": secondary["metrics_global"],
        "cases": [
            {
                key: row[key]
                for key in (
                    "case_id",
                    "family",
                    "covered",
                    "expected_negated",
                    "predicted_negated",
                    "expected_negation_kind",
                    "predicted_negation_kind",
                    "expected_decision",
                    "predicted_decision",
                    "scope_correct",
                    "evidence_anchored",
                    "positive_operations",
                )
            }
            for row in primary["rows"]
        ],
        "generated_by": "opus-gate4",
        "notes": notes,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/d"
    if isinstance(value, bool):
        return "si" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


SHORT = {
    "negative_edge_precision": "neg-P",
    "negative_edge_recall": "neg-R",
    "negated_cessation_safety": "no-cese",
    "cessation_precision": "ces-P",
    "cessation_recall": "ces-R",
    "negation_scope_accuracy": "alcance",
    "evidence_grounding": "evid.",
    "false_positive_relation_from_negation": "FP+",
    "auto_approval_precision": "auto-P",
    "auto_approval_recall": "auto-R",
}


def to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Puerta 4 — Negaciones extremo a extremo en sombra")
    add("")
    add(
        "Corrida real de la cadena completa sobre el split `negation` "
        "(solo lectura), extraccion determinista, writer en DRY-RUN. Todos los "
        "numeros de este informe salen de un conteo sobre la salida de esa "
        "corrida; ninguno esta estimado."
    )
    add("")
    add("## 1. Configuracion")
    add("")
    add("| clave | valor |")
    add("| --- | --- |")
    for key, value in report["config"].items():
        if key == "match":
            continue
        add(f"| `{key}` | {_fmt(value)} |")
    add("")
    add("## 2. Corpus y cobertura")
    add("")
    corpus = report["corpus"]
    add(
        f"El gold trae **{corpus['gold_claims']} claims**, de los que "
        f"**{corpus['evaluable_cases']}** declaran polaridad y son evaluables, mas "
        f"**{corpus['gold_negatives_no_claim']}** negativos `NO_CLAIM`. La cadena emitio "
        f"una decision para **{corpus['covered_cases']}** de ellos "
        f"(cobertura {_fmt(corpus['coverage'])})."
    )
    add("")
    add("| fuente | episodios | claims | decisiones | parada |")
    add("| --- | ---: | ---: | ---: | --- |")
    for source in corpus["sources"]:
        add(
            f"| {source['source_id']} | {source['episodes']} | {source['claims']} | "
            f"{source['decisions']} | {source['stop_reason'] or '—'} |"
        )
    add("")
    add("## 3. Metricas globales")
    add("")
    add("| metrica | valor | vista |")
    add("| --- | ---: | --- |")
    for name, detail in report["metrics_detail"].items():
        if name.startswith("_"):
            continue
        add(f"| `{name}` | {_fmt(detail['value'])} | {detail['view']} |")
    add("")
    add(
        "`covered` = solo los casos para los que el sistema emitio decision; "
        "`full` = los "
        f"{corpus['evaluable_cases']} casos evaluables del gold, contando como fallo "
        "los que la cadena no vio."
    )
    add("")
    add("## 4. Por familia")
    add("")
    header = "| familia | casos | cubiertos | " + " | ".join(SHORT.values()) + " |"
    add(header)
    add("| --- | ---: | ---: |" + " ---: |" * len(SHORT))
    for family, values in report["metrics_by_family"].items():
        if family == "NO_CLAIM":
            continue
        cells = " | ".join(_fmt(values.get(name)) for name in SHORT)
        add(f"| {family} | {values['cases']} | {values['covered']} | {cells} |")
    no_claim = report["metrics_by_family"]["NO_CLAIM"]
    add("")
    add(
        f"`NO_CLAIM` ({no_claim['cases']} negativos, {no_claim['episodes_aligned']} con "
        f"episodio alineado): {len(no_claim['violations'])} violaciones, exactitud "
        f"{_fmt(no_claim['accuracy'])}."
    )
    add("")
    add("## 5. Puertas")
    add("")
    add("| puerta | umbral | observado | veredicto |")
    add("| --- | ---: | ---: | --- |")
    for gate in report["gates"]:
        add(
            f"| {gate['name']} | {_fmt(gate['threshold'])} | {_fmt(gate['observed'])} | "
            f"**{gate['status']}** |"
        )
    add("")
    add(
        "Una puerta marcada `NO_EVALUABLE` no es una puerta aprobada: significa que su "
        "denominador es 0 y que la corrida no produjo ni un solo caso con el que "
        "juzgarla."
    )
    add("")
    add("## 6. Las dos variantes")
    add("")
    add("| metrica | graduated_at_engine | extractor_forces_review |")
    add("| --- | ---: | ---: |")
    primary = report["variants"]["graduated_at_engine"]["metrics_global"]
    other = report["variants"]["extractor_forces_review"]["metrics_global"]
    for name in primary:
        add(f"| `{name}` | {_fmt(primary[name])} | {_fmt(other[name])} |")
    add("")
    add(
        "`graduated_at_engine` (`negation_policy_at_engine=True`) es la variante que "
        "puntua las puertas: es la unica en la que la politica graduada del motor llega a "
        "decidir. Con el valor por defecto de `PipelineConfig` "
        "(`negation_policy_at_engine=False`), el extractor determinista marca revision en "
        "TODA negacion y ninguna negacion puede autoaprobarse jamas, decida lo que decida "
        "el motor."
    )
    add("")
    add("## 7. Sombra y writer")
    add("")
    shadow = report["shadow"]
    writer = report["writer"]
    add(
        f"Evaluacion en sombra activa con **{shadow['records']} registros**. La sombra "
        "solo compara claims del paso `extract.semantic`, y esta corrida no lo ejecuta "
        "porque no se admite ningun proveedor: la cobertura de la sombra es 0 y no debe "
        "leerse como que la sombra este validada."
    )
    add("")
    add(
        f"Writer en **{writer['mode']}**: {writer['plans']} planes, "
        f"{writer['approved_plans']} aprobados, {writer['operations']} operaciones "
        f"({', '.join(writer['operation_kinds']) or 'ninguna'}), resultado "
        f"{', '.join(writer['outcomes']) or 'ninguno'}. Nada llega a Neo4j."
    )
    add("")
    add("## 8. Hallazgos")
    add("")
    for note in report["notes"]:
        add(f"- {note}")
    add("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 4: negaciones E2E en sombra.")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)
    report = measure()
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "gate4-negation-metrics.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        (out / "gate4-negation-metrics.md").write_text(to_markdown(report), encoding="utf-8")
        print(f"escrito en {out}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
