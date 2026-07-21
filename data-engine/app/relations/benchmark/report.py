# -*- coding: utf-8 -*-
"""Ensamblado de resultados, GATES y dictamen del benchmark de relaciones.

Los gates se evaluan por SEPARADO (no se declara aptitud solo por el F1 global).
El dictamen pertenece a un vocabulario CERRADO y NUNCA usa "APTO PARA INGESTA
REAL". Los numeros que se reportan son los REALES del pipeline; no se maquillan.
"""
from __future__ import annotations

from typing import Any, Optional

from . import matching as _matching
from . import metrics as _metrics
from .matching import match_predictions
from .runner import BenchmarkRun
from .runner import is_provider_mode as _is_provider_mode

# Dictamenes permitidos (vocabulario cerrado). "APTO PARA INGESTA REAL" PROHIBIDO.
VERDICTS = (
    "APTO PARA CONTINUAR EN MODO SOMBRA",
    "APTO CON REVISION DE CASOS CONFLICTIVOS",
    "APTO CON REVISION HUMANA TOTAL",
    "NO APTO",
    # B2: no es un dictamen de calidad, es la AUSENCIA de dictamen. Se emite
    # cuando el modo tiene proveedor y el transporte no permitio medir nada
    # (0 llamadas contabilizadas, o muestra insuficiente). "NO APTO" seria una
    # afirmacion falsa sobre el pipeline: no se ha medido.
    "SIN DICTAMEN: PROVEEDOR NO MEDIDO",
)

# Umbrales de los gates de calidad (deterministas y documentados en docs/50).
THRESHOLDS = {
    "simple_relations_recall": 0.80,
    "evidence": 0.80,
    "offsets": 0.90,
    "negation": 0.80,
    "temporality": 0.60,
    "rumors": 0.60,
    "predicate_structural": 0.50,
}


def _status(value: float, threshold: float, *, partial: float = 0.6) -> str:
    if value >= threshold:
        return "PASS"
    if value >= threshold * partial:
        return "PARTIAL"
    return "FAIL"


def evaluate_gates(match, struct: dict, contamination: dict, determinism: dict,
                   provider_transport: Optional[dict] = None,
                   operational: Optional[dict] = None) -> dict:
    """Evalua los gates por separado. Devuelve dict gate -> {status, value, ...}.

    `provider_transport` (B2) solo se pasa en modos con proveedor: son las
    estadisticas de transporte REALES del run (`BenchmarkRun.provider_transport`).
    Genera un gate DURO adicional que gobierna `decide_verdict`.
    """
    sub = struct["subgroups"]
    gates: dict[str, dict] = {}

    if provider_transport is not None:
        attempted = int(provider_transport.get("total_attempted", 0))
        errors = int(provider_transport.get("total_errors", 0))
        indeterminadas = int(provider_transport.get("total_indeterminate", 0))
        respondidas = int(provider_transport.get(
            "total_responded", attempted - errors - indeterminadas))
        # N7: fallos NO CATALOGADOS. `provider_fail_closed` cuenta candidatos que
        # un proveedor habilitado no llego a evaluar; NO dejan payload, asi que
        # no aparecen en `attempted` ni en `errors` (un carril entero muerto daba
        # rate 0.0 y gate PASS). Se contrasta explicitamente con `attempted`.
        fail_closed = int(((operational or {}).get("counters") or {})
                          .get("provider_fail_closed", 0) or 0)
        motivos: list[str] = []
        if attempted == 0:
            estado = "NOT_MEASURED"
            if fail_closed:
                motivos.append(
                    f"{fail_closed} candidatos con proveedor FALLIDO CERRADO y 0 "
                    "llamadas contabilizadas")
        elif respondidas == 0:
            # BLOQUEANTE 1 (ronda 4): CERO respuestas confirmadas pese a haber
            # intentos. Simetrico con `attempted==0`: el punto de contacto con el
            # modelo es cero, asi que NO hay medicion. Antes, un carril 100%
            # INDETERMINADO (rate=0.0) salia PARTIAL -> APTO -> rc=0. Candado
            # independiente de la CATEGORIA: cierra el vector sea cual sea la razon
            # (envio BLOQUEADO por secreto, config invalida, error base...).
            estado = "NOT_MEASURED"
            motivos.append(
                f"{attempted} llamadas intentadas pero 0 RESPUESTAS confirmadas "
                f"({errors} transporte, {indeterminadas} indeterminadas): ningun "
                "proveedor llego a contestar, no hay calidad que medir")
        elif not provider_transport.get("evaluable"):
            estado = "FAIL"
        else:
            estado = "PASS" if errors == 0 else "PARTIAL"
            if errors:
                motivos.append(
                    f"{errors}/{attempted} llamadas fallaron en TRANSPORTE "
                    f"({float(provider_transport.get('rate', 0.0)) * 100:.1f}%), "
                    "por debajo del maximo tolerado pero NO nulo")
            if indeterminadas:
                estado = "PARTIAL"
                motivos.append(
                    f"{indeterminadas}/{attempted} llamadas INDETERMINADAS "
                    "('provider_error' generico: no consta si el proveedor "
                    "respondio); no cuentan como transporte ni como calidad")
            if fail_closed:
                estado = "PARTIAL"
                motivos.append(
                    f"{fail_closed} candidatos que el proveedor no llego a evaluar "
                    "(provider_fail_closed), invisibles para attempted/errors")
        gates["provider_transport"] = {
            "status": estado,
            "hard": True,
            "value": float(provider_transport.get("rate", 0.0)),
            "threshold": 0.0,
            "indeterminate": indeterminadas,
            "fail_closed": fail_closed,
            "degraded_reasons": motivos,
            "detail": dict(provider_transport),
        }

    # --- Gates DUROS (seguridad) ---
    # D7: `deterministic is None` significa NO COMPROBADO (--no-determinism o
    # modo con proveedor), no "comprobado y fallido". Marcarlo como FAIL forzaba
    # `NO APTO` en toda la comparativa --all-modes y en cualquier ejecucion rapida:
    # un veredicto de calidad falso derivado de una comprobacion que no se hizo.
    det_value = determinism.get("deterministic")
    if det_value is None:
        det_status = "NOT_EVALUATED"
    else:
        det_status = "PASS" if det_value else "FAIL"
    gates["determinism"] = {
        "status": det_status,
        "hard": True,
        "evaluated": det_value is not None,
        "detail": determinism,
    }
    gates["workspace_contamination"] = {
        "status": "PASS" if contamination["clean"] else "FAIL",
        "hard": True,
        "detail": contamination,
    }

    # --- Gates de CALIDAD ---
    simple = sub["simple_relations"]["evidence_correct"]["rate"]
    gates["simple_relations"] = {
        "status": _status(simple, THRESHOLDS["simple_relations_recall"]),
        "value": simple, "threshold": THRESHOLDS["simple_relations_recall"],
        "detail": sub["simple_relations"],
    }
    gates["evidence"] = {
        "status": _status(struct["evidence_correct"]["rate"], THRESHOLDS["evidence"]),
        "value": struct["evidence_correct"]["rate"], "threshold": THRESHOLDS["evidence"],
        "detail": struct["evidence_correct"],
    }
    gates["offsets"] = {
        "status": _status(struct["offsets_correct"]["rate"], THRESHOLDS["offsets"]),
        "value": struct["offsets_correct"]["rate"], "threshold": THRESHOLDS["offsets"],
        "detail": struct["offsets_correct"],
    }
    neg = sub["negated_relations"]["negation_correct"]["rate"]
    gates["negation"] = {
        "status": _status(neg, THRESHOLDS["negation"]),
        "value": neg, "threshold": THRESHOLDS["negation"],
        "detail": sub["negated_relations"],
    }
    temp = sub["temporal_relations"]["temporal_correct"]["rate"]
    gates["temporality"] = {
        "status": _status(temp, THRESHOLDS["temporality"]),
        "value": temp, "threshold": THRESHOLDS["temporality"],
        "detail": sub["temporal_relations"],
    }
    rum = sub["rumored_relations"]["epistemic_correct"]["rate"]
    gates["rumors"] = {
        "status": _status(rum, THRESHOLDS["rumors"]),
        "value": rum, "threshold": THRESHOLDS["rumors"],
        "detail": sub["rumored_relations"],
    }
    gates["predicate_structural"] = {
        "status": _status(struct["predicate_correct"]["rate"], THRESHOLDS["predicate_structural"]),
        "value": struct["predicate_correct"]["rate"],
        "threshold": THRESHOLDS["predicate_structural"],
        "detail": struct["predicate_correct"],
    }
    return gates


def decide_verdict(gates: dict) -> tuple[str, str]:
    """Deriva el dictamen del benchmark del ESTADO REAL de los gates.

    Devuelve (dictamen, justificacion). No se usa "APTO PARA INGESTA REAL".

    B2: si existe el gate `provider_transport` (solo en modos con proveedor) y su
    estado no es PASS ni PARTIAL, NO se emite dictamen de calidad: el proveedor
    no respondio (o no se midio nada), asi que no hay nada que juzgar. El gate lo
    construye `evaluate_gates` a partir de las llamadas REALMENTE contabilizadas.
    """
    pt = gates.get("provider_transport")
    if pt is not None and pt.get("status") not in ("PASS", "PARTIAL"):
        return ("SIN DICTAMEN: PROVEEDOR NO MEDIDO",
                "gate duro 'provider_transport' en "
                f"{pt.get('status')}: el proveedor no respondio lo suficiente "
                "(llamadas contabilizadas="
                f"{(pt.get('detail') or {}).get('total_attempted', 0)}, "
                f"errores={(pt.get('detail') or {}).get('total_errors', 0)}). "
                "NO se emite dictamen de CALIDAD sobre llamadas que nunca "
                "llegaron al modelo; esto es un fallo de INFRAESTRUCTURA o una "
                "medicion inexistente, no una medida del pipeline.")
    # Gates duros: si fallan (comprobados y en FAIL), NO APTO. Un gate duro NO
    # EVALUADO no es un fallo de calidad: no se puede convertir en dictamen, pero
    # tampoco se oculta -- se declara en la justificacion y en `verdict_scope`.
    for name in ("determinism", "workspace_contamination"):
        if gates[name]["status"] == "FAIL":
            return "NO APTO", f"gate duro '{name}' en FAIL"
    no_evaluados = [n for n in ("determinism", "workspace_contamination")
                    if gates[n]["status"] == "NOT_EVALUATED"]
    aviso = (f" [gates duros NO EVALUADOS: {no_evaluados}; dictamen PARCIAL, "
             "no cubre esas comprobaciones]") if no_evaluados else ""
    # N3: `PARTIAL` en el transporte se DECLARA. Si "no comprobado" consta en el
    # alcance (D7), "comprobado y degradado" tambien: emitir un dictamen normal
    # sin mencionar el transporte degradado era la misma clase de silencio.
    if pt is not None and pt.get("status") == "PARTIAL":
        aviso += (" [TRANSPORTE DEGRADADO: "
                  + "; ".join(pt.get("degraded_reasons") or ["sin desglose"])
                  + ". El dictamen se emite sobre las llamadas que SI midieron "
                    "al modelo]")

    quality = ["simple_relations", "evidence", "offsets", "negation",
               "temporality", "rumors", "predicate_structural"]
    passed = [g for g in quality if gates[g]["status"] == "PASS"]
    failed = [g for g in quality if gates[g]["status"] == "FAIL"]

    # La calidad estructural del predicado (heuristica) y la direccion suelen ser
    # bajas: el pipeline es un PROPOSITOR en sombra, no un extractor autonomo.
    evidence_ok = gates["evidence"]["status"] != "FAIL" and gates["offsets"]["status"] == "PASS"
    predicate_ok = gates["predicate_structural"]["status"] == "PASS"

    if not failed and predicate_ok and evidence_ok:
        return ("APTO PARA CONTINUAR EN MODO SOMBRA",
                "sin gates de calidad en FAIL y predicado/evidencia solidos" + aviso)
    if evidence_ok and not predicate_ok:
        return ("APTO CON REVISION HUMANA TOTAL",
                "evidencia/offsets fiables pero el predicado heuristico es debil: "
                "toda relacion requiere revision humana antes de considerarse" + aviso)
    if len(failed) <= 2 and evidence_ok:
        return ("APTO CON REVISION DE CASOS CONFLICTIVOS",
                f"gates en FAIL acotados a casos dificiles: {failed}" + aviso)
    return ("APTO CON REVISION HUMANA TOTAL",
            f"multiples gates de calidad en FAIL ({failed}); revision humana total" + aviso)


def _verdict_scope(gates: dict) -> str:
    """Alcance REAL del dictamen a partir del estado de los gates duros."""
    pt = gates.get("provider_transport")
    if pt is not None and pt.get("status") == "NOT_MEASURED":
        det = pt.get("detail") or {}
        att = int(det.get("total_attempted", 0))
        resp = int(det.get("total_responded",
                           att - int(det.get("total_errors", 0))
                           - int(det.get("total_indeterminate", 0))))
        if att and resp == 0:
            # BLOQUEANTE 1 (ronda 4): hubo intentos pero 0 respuestas confirmadas
            # (todo transporte/indeterminado). El punto de contacto con el modelo
            # es cero igual que con 0 llamadas: NO MEDIDO, no PARCIAL.
            return ("NO MEDIDO (modo con proveedor: "
                    f"{att} llamadas intentadas pero 0 RESPUESTAS confirmadas; "
                    "ningun proveedor llego a contestar, el dictamen NO evalua "
                    "calidad)")
        return ("NO MEDIDO (modo con proveedor y 0 llamadas contabilizadas: "
                "ningun proveedor fue medido; el dictamen NO evalua calidad)")
    if pt is not None and pt.get("status") == "FAIL":
        return ("NO MEDIDO (el transporte del proveedor fallo por encima de lo "
                "tolerado: no hay medicion de calidad)")
    partes: list[str] = []
    if pt is not None and pt.get("status") == "PARTIAL":
        # N3: el alcance declara el transporte DEGRADADO, no solo lo no medido.
        partes.append("transporte del proveedor DEGRADADO: "
                      + "; ".join(pt.get("degraded_reasons") or ["sin desglose"]))
    no_evaluados = [n for n in ("determinism", "workspace_contamination")
                    if gates[n]["status"] == "NOT_EVALUATED"]
    if no_evaluados:
        partes.append("gates duros no evaluados: " + ", ".join(no_evaluados))
    if partes:
        return "PARCIAL (" + " | ".join(partes) + ")"
    return "COMPLETO"


def _contamination_report(run: BenchmarkRun, corpus) -> dict:
    """Comprueba contaminacion entre workspaces (cero cruces permitidos)."""
    cross = []
    for pred in run.predictions:
        expected_ws = corpus.workspace_by_source.get(pred["source_id"])
        if pred["workspace"] != expected_ws:
            cross.append(pred)
    # Errores de mezcla de workspace registrados por el propio pipeline.
    mix_errors = 0
    for sr in run.source_runs:
        for e in sr.output.get("errors", []):
            if e.get("code") == "workspace_mismatch":
                mix_errors += 1
    return {
        "clean": len(cross) == 0,
        "cross_workspace_predictions": len(cross),
        "workspace_mismatch_errors": mix_errors,
    }


def determinism_report(corpus, mode: str, reference: BenchmarkRun) -> dict:
    """Ejecuta el pipeline REAL una segunda vez y compara determinismo.

    N4 + B1: en un modo CON PROVEEDOR esta segunda pasada NO se hace. Antes se
    relanzaba `run_benchmark` SIN los transportes del run original, lo que tenia
    dos efectos: (a) duplicaba las conexiones reales (5 -> 10 intentos contra
    NVIDIA, porque el registry resolvia el proveedor por su cuenta) y (b) para un
    llamante de libreria producia `deterministic=False` ESPURIO -- y con el gate
    duro, un `NO APTO` falso. Con proveedor no comparable, la respuesta honesta
    es "no evaluado".
    """
    from .runner import run_benchmark

    if _is_provider_mode(mode):
        return {
            "deterministic": None,
            "skipped": True,
            "reason": ("modo con proveedor: la segunda pasada no es comparable "
                       "(y duplicaria llamadas reales); determinismo NO EVALUADO"),
        }

    # La segunda ejecucion debe usar EXACTAMENTE la misma submuestra de fuentes.
    second = run_benchmark(corpus, mode=mode,
                           source_ids=list(getattr(reference, "source_ids", []) or []) or None)
    ref_hashes = reference.result_hashes()
    sec_hashes = second.result_hashes()
    hashes_equal = ref_hashes == sec_hashes

    ref_match = match_predictions(reference.predictions, corpus.relations)
    sec_match = match_predictions(second.predictions, corpus.relations)
    metrics_equal = _metrics.global_metrics(ref_match) == _metrics.global_metrics(sec_match)

    preds_equal = reference.predictions == second.predictions
    return {
        "deterministic": bool(hashes_equal and metrics_equal and preds_equal),
        "hashes_equal": hashes_equal,
        "metrics_equal": metrics_equal,
        "predictions_equal": preds_equal,
        "result_hashes": ref_hashes,
    }


# N5: `_PROVIDER_LABEL` era un mapa IDENTIDAD (etiqueta -> la misma etiqueta) que
# sugeria una traduccion inexistente. Eliminado: el estado se publica tal cual lo
# emite el pipeline, con `NOT_EXECUTED` como unico valor por defecto.


def _providers_block(run: BenchmarkRun) -> dict:
    """Estado REAL de los proveedores, DERIVADO de la salida del pipeline.

    El pipeline publica `output['provider_status']`; aqui NO se escribe ningun
    literal: si un proveedor se ejecuto de verdad, el informe lo dice.

    B2 -- el campo `network` se deriva de las llamadas REALMENTE CONTABILIZADAS
    (`provider_transport.total_attempted`), NO de si un objeto es `None`. Antes,
    `--mode nvidia_shadow` publicaba "Red: none" tras 5 POST reales contra NVIDIA
    porque `external_provider` valia `None`: una atestacion de seguridad FALSA.
    Cuando el estado no se puede determinar con certeza se publica como
    DESCONOCIDO, nunca como `none`.

    NOTA de alcance: el literal `FAILED_CLOSED` de `provider_status` lo calcula
    `relations/pipeline.py` (FUERA DE ALCANCE de este bloque) como
    `EXECUTED if external_provider is not None else FAILED_CLOSED`. Aqui no se
    toca; se contrasta con las llamadas contabilizadas y, si se contradicen, el
    informe lo declara en `status_consistency` en vez de publicar una
    atestacion que se sabe falsa.
    """
    status = dict(getattr(run, "provider_status", None) or {})
    local = status.get("local_llm") or "NOT_EXECUTED"
    external = status.get("external_ai") or "NOT_EXECUTED"
    transport = dict(getattr(run, "provider_transport", None) or {})
    attempted = int(transport.get("total_attempted", 0) or 0)
    provider_mode = _is_provider_mode(run.mode)

    if attempted > 0:
        network = (f"yes ({attempted} llamadas a proveedor contabilizadas; "
                   f"{int(transport.get('total_errors', 0) or 0)} fallos de transporte)")
    elif local == "EXECUTED" or external == "EXECUTED":
        # Sin llamadas contabilizadas no se puede afirmar que NO hubo red: se
        # publica del lado conservador (afirmar red), nunca como "none".
        network = "yes (proveedores ejecutados)"
    elif provider_mode:
        network = ("unknown (modo con proveedor y 0 llamadas contabilizadas: el "
                   "estado de red NO es verificable desde el informe)")
    else:
        network = "none"

    # N8: la comprobacion se hace en las DOS direcciones. La direccion original
    # ("llamadas contabilizadas pero ningun EXECUTED") es hoy INALCANZABLE en un
    # run real, porque `authorize_provider_run` exige el proveedor inyectado y
    # `pipeline.py` publica EXECUTED en cuanto el objeto no es None: se conservaba
    # como si fuera una mitigacion activa siendo codigo muerto. La direccion
    # contraria ("EXECUTED pero CERO llamadas contabilizadas") SI ocurre en runs
    # reales (fuentes sin candidatos, proveedor que nunca llego a invocarse) y es
    # justo el caso en que la atestacion "proveedor EXECUTED" induce a error.
    consistencia = "OK"
    ejecutados = [n for n, v in (("local_llm", local), ("external_ai", external))
                  if v == "EXECUTED"]
    if provider_mode and attempted > 0 and not ejecutados:
        consistencia = (
            "INCONSISTENTE: hubo llamadas contabilizadas pero provider_status dice "
            f"local={local}/external={external}. El literal lo calcula "
            "relations/pipeline.py (fuera de alcance de este bloque) a partir de si "
            "el objeto proveedor es None; NO refleja si hubo llamadas."
        )
    elif provider_mode and attempted == 0 and ejecutados:
        consistencia = (
            f"INCONSISTENTE: provider_status declara EXECUTED ({', '.join(ejecutados)}) "
            "pero NO se contabilizo ninguna llamada. El literal lo calcula "
            "relations/pipeline.py (fuera de alcance) a partir de si el objeto "
            "proveedor es None: 'EXECUTED' NO significa que el proveedor fuese "
            "invocado. No hay medicion de ningun proveedor."
        )
    return {
        "local_llm": local,
        "external_ai": external,
        "network": network,
        "network_calls_counted": attempted,
        "status_consistency": consistencia,
        "endpoints": dict(getattr(run, "provider_endpoints", None) or {}),
        "writes": "none (dry-run, sin Neo4j)",
        # D3: el estado crudo se expone con nombre directo (`provider_status`) y no
        # solo bajo el sufijo `_raw`; `provider_status_raw` se conserva por
        # compatibilidad con los consumidores existentes.
        "provider_status": status,
        "provider_status_raw": status,
        "transport": transport,
    }


def build_report(corpus, run: BenchmarkRun, *, check_determinism: bool = True) -> dict:
    """Ensambla el informe COMPLETO de resultados del benchmark."""
    # Submuestra (--sources): el corpus se carga entero, pero el ground truth que
    # se evalua es el de las fuentes REALMENTE ejecutadas (si no, las fuentes no
    # procesadas contarian como falsos negativos y el informe seria enganoso).
    used = list(getattr(run, "source_ids", []) or sorted(corpus.sources))
    used_set = set(used)
    ground_truth = [r for r in corpus.relations if r["source_id"] in used_set]
    match = match_predictions(run.predictions, ground_truth)

    glob = _metrics.global_metrics(match)
    strict = _metrics.strict_metrics(match)
    per_pred = _metrics.per_predicate_metrics(match)
    pred_dist = _metrics.predicted_predicate_distribution(run.predictions)
    struct = _metrics.structural_quality(match)
    decision_conf = _metrics.decision_confusion(match)
    operational = _metrics.aggregate_operational(run.source_summaries, run.timings)
    cost = _metrics.provider_cost(getattr(run, "results", []), run.source_summaries)

    contamination = _contamination_report(run, corpus)
    if check_determinism:
        determinism = determinism_report(corpus, run.mode, run)
    else:
        determinism = {"deterministic": None, "skipped": True}

    transport = dict(getattr(run, "provider_transport", None) or {})
    gates = evaluate_gates(
        match, struct, contamination, determinism,
        provider_transport=transport if _is_provider_mode(run.mode) else None,
        operational=operational)
    verdict, justification = decide_verdict(gates)

    false_positives = [
        {k: p[k] for k in ("source_id", "workspace", "subject_id", "object_id",
                           "predicate", "direction", "evidence_text", "consensus_state",
                           "recommendation")}
        for p in match.false_positives
    ]
    false_negatives = [
        {k: g[k] for k in ("relation_id", "source_id", "workspace", "subject_id",
                           "object_id", "predicate", "expected_decision", "annotator_notes")}
        for g in match.false_negatives
    ]

    derivation_notes = [n for sr in run.source_runs for n in sr.derivation_notes]

    return {
        "benchmark": "relation-benchmark-runner-v1",
        "mode": run.mode,
        "config": run.config,
        "versions": run.versions,
        "pipeline_version": run.versions.get("pipeline"),
        "code_sha": run.code_sha,
        "corpus": {
            "version": corpus.manifest.get("version"),
            "source_count": corpus.manifest.get("source_count"),
            "relation_count": corpus.manifest.get("relation_count"),
            "corpus_hashes": run.corpus_hashes,
            "ground_truth_sha256": corpus.manifest["ground_truth"]["sha256"],
        },
        "providers": _providers_block(run),
        # D3: tambien en la raiz del JSON, para que no haya que bucear en
        # `providers.provider_status_raw` (donde antes quedaba enterrado).
        "provider_status": dict(getattr(run, "provider_status", None) or {}),
        "provider_transport": dict(getattr(run, "provider_transport", None) or {}),
        # D7: alcance real del dictamen. Si un gate DURO no se ha comprobado, el
        # dictamen es PARCIAL y aqui se dice, en vez de fingir un FAIL.
        # B3: si el modo tiene proveedor y no se contabilizo NINGUNA llamada, el
        # alcance es NO MEDIDO: no hay dictamen normal que dar.
        "verdict_scope": _verdict_scope(gates),
        # N3: `max_time_per_candidate_ms` esta DECLARADO en `PipelineConfig` y se
        # serializa en `config`, pero `relations/pipeline.py` (fuera de alcance)
        # NUNCA lo usa. Se documenta aqui para no publicarlo como si fuera un
        # control efectivo.
        "config_notes": {
            "max_time_per_candidate_ms": (
                "DECLARADO PERO NO APLICADO: el pipeline no lo comprueba en ningun "
                "punto; no limita el tiempo por candidato. No es un control "
                "efectivo (la correccion vive en relations/pipeline.py, fuera del "
                "alcance del Bloque 7)."
            ),
        },
        "sources_used": used,
        "sources_available": sorted(corpus.sources),
        "ensemble": bool(getattr(run, "ensemble", False)),
        "metrics": {
            "global_existence": glob,
            "strict_predicate": strict,
            "per_predicate": per_pred,
            "predicted_predicate_distribution": pred_dist,
            "structural_quality": struct,
            "decision_confusion": decision_conf,
            "operational": operational,
            "provider_cost": cost,
        },
        "gates": gates,
        "verdict": verdict,
        "verdict_justification": justification,
        "errors": {
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "derivation_notes": derivation_notes,
        },
        "determinism": determinism,
        "result_hashes": run.result_hashes(),
    }


__all__ = [
    "VERDICTS",
    "THRESHOLDS",
    "evaluate_gates",
    "decide_verdict",
    "determinism_report",
    "build_report",
]
