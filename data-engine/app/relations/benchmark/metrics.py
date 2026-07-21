# -*- coding: utf-8 -*-
"""Metricas DETERMINISTAS del benchmark de relaciones.

Consume el resultado de `matching.match_predictions` (y los contadores
operativos agregados del pipeline REAL) y produce metricas globales, por tipo de
predicado y de calidad estructural. NO ejecuta el pipeline ni reimplementa nada.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from relations.contracts import normalize_predicate

from .matching import MatchResult


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def global_metrics(match: MatchResult) -> dict:
    """P/R/F1 globales sobre el criterio de existencia (par no ordenado)."""
    return _prf(match.tp, match.fp, match.fn)


def strict_metrics(match: MatchResult) -> dict:
    """P/R/F1 con criterio ESTRICTO: par correcto Y predicado exacto.

    Un TP de existencia con predicado incorrecto degrada a FP (prediccion errada)
    y a FN (la relacion de ground truth queda sin cubrir con su predicado).
    """
    tp = sum(1 for m in match.true_positives if m["flags"]["predicate_correct"])
    predicate_wrong = match.tp - tp
    fp = match.fp + predicate_wrong
    fn = match.fn + predicate_wrong
    return _prf(tp, fp, fn)


def per_predicate_metrics(match: MatchResult) -> dict:
    """Metricas por predicado del GROUND TRUTH.

    Para cada predicado del ground truth reporta:
      * support           : nº de relaciones de ground truth con ese predicado.
      * existence_tp      : cuantas fueron emparejadas (par correcto).
      * exact_tp          : cuantas ademas con predicado exacto.
      * recall_existence  : existence_tp / support.
      * recall_exact      : exact_tp / support.
    """
    support: dict[str, int] = defaultdict(int)
    existence_tp: dict[str, int] = defaultdict(int)
    exact_tp: dict[str, int] = defaultdict(int)

    for gt in match.false_negatives:
        support[normalize_predicate(gt["predicate"])] += 1
    for m in match.true_positives:
        p = normalize_predicate(m["gt"]["predicate"])
        support[p] += 1
        existence_tp[p] += 1
        if m["flags"]["predicate_correct"]:
            exact_tp[p] += 1

    out: dict[str, dict] = {}
    for p in sorted(support):
        s = support[p]
        out[p] = {
            "support": s,
            "existence_tp": existence_tp[p],
            "exact_tp": exact_tp[p],
            "recall_existence": round(existence_tp[p] / s, 4) if s else 0.0,
            "recall_exact": round(exact_tp[p] / s, 4) if s else 0.0,
        }
    return out


def predicted_predicate_distribution(predictions: list[dict]) -> dict:
    """Distribucion de predicados PREDICHOS (para ver el sesgo del heuristico)."""
    dist: dict[str, int] = defaultdict(int)
    for pred in predictions:
        dist[normalize_predicate(pred["predicate"])] += 1
    return dict(sorted(dist.items()))


def structural_quality(match: MatchResult) -> dict:
    """Tasas de calidad estructural sobre los TP (par correcto).

    Cada tasa es correctos/total_TP. Ademas subgrupos condicionados (negacion,
    temporalidad, rumor) para los gates.
    """
    tp = match.true_positives
    n = len(tp)

    def rate(flag: str) -> dict:
        ok = sum(1 for m in tp if m["flags"][flag])
        return {"ok": ok, "total": n, "rate": round(ok / n, 4) if n else 0.0}

    # Subgrupos para gates.
    negated_gt = [m for m in tp if bool(m["gt"]["negated"])]
    temporal_gt = [m for m in tp if m["gt"]["temporal_status"] in ("PAST", "FUTURE", "ONGOING", "ENDED")]
    rumor_gt = [m for m in tp if m["gt"]["epistemic_status"] == "RUMORED"]
    simple_gt = [
        m for m in tp
        if not bool(m["gt"]["negated"])
        and m["gt"]["epistemic_status"] == "ASSERTED"
        and m["gt"]["expected_decision"] == "ACCEPT"
    ]

    def subgroup_rate(subset: list, flag: str) -> dict:
        k = len(subset)
        ok = sum(1 for m in subset if m["flags"][flag])
        return {"ok": ok, "total": k, "rate": round(ok / k, 4) if k else 0.0}

    return {
        "predicate_correct": rate("predicate_correct"),
        "direction_correct": rate("direction_correct"),
        "direction_orientation_ok": rate("direction_orientation_ok"),
        "types_correct": rate("types_correct"),
        "negation_correct": rate("negation_correct"),
        "temporal_correct": rate("temporal_correct"),
        "epistemic_correct": rate("epistemic_correct"),
        "evidence_correct": rate("evidence_correct"),
        "offsets_correct": rate("offsets_correct"),
        "workspace_correct": rate("workspace_correct"),
        "decision_correct": rate("decision_correct"),
        "subgroups": {
            "simple_relations": {
                "count": len(simple_gt),
                "evidence_correct": subgroup_rate(simple_gt, "evidence_correct"),
            },
            "negated_relations": {
                "count": len(negated_gt),
                "negation_correct": subgroup_rate(negated_gt, "negation_correct"),
            },
            "temporal_relations": {
                "count": len(temporal_gt),
                "temporal_correct": subgroup_rate(temporal_gt, "temporal_correct"),
            },
            "rumored_relations": {
                "count": len(rumor_gt),
                "epistemic_correct": subgroup_rate(rumor_gt, "epistemic_correct"),
            },
        },
    }


def decision_confusion(match: MatchResult) -> dict:
    """Matriz de confusion decision_pred vs expected_decision (sobre TP)."""
    labels = ["ACCEPT", "REJECT", "REVIEW", None]
    conf: dict[str, dict[str, int]] = {
        str(g): {str(p): 0 for p in labels} for g in ["ACCEPT", "REJECT", "REVIEW"]
    }
    for m in match.true_positives:
        gt_dec = m["gt"]["expected_decision"]
        pred_dec = m["flags"]["decision_pred"]
        conf[str(gt_dec)][str(pred_dec)] += 1
    return conf


def aggregate_operational(source_summaries: list[dict], timings: list[dict]) -> dict:
    """Agrega los contadores OPERATIVOS del resumen del pipeline REAL por fuente.

    `source_summaries` son los `output['summary']` reales de cada ejecucion; no se
    recalcula nada, solo se suman.
    """
    keys = [
        "documents", "segments", "segments_processed", "segments_failed",
        "entities", "pairs_potential", "pairs_generated", "pairs_discarded",
        "candidates_evaluated", "results_strong", "results_partial",
        "results_conflict", "results_invalid", "results_human",
        "local_calls_simulated", "external_calls_simulated",
        "provider_fail_closed", "timeouts", "errors", "chars_processed",
        "bytes_processed",
    ]
    agg = {k: 0 for k in keys}
    for s in source_summaries:
        for k in keys:
            agg[k] += int(s.get(k, 0))

    # Alias sin el sufijo enganoso "_simulated" (defecto D6). El nombre original
    # nace en `relations/pipeline.py` (fuera de alcance de este bloque) y se
    # conserva para no romper el contrato del pipeline; el alias es ADITIVO y deja
    # claro que esas llamadas son REALES cuando hay transporte inyectado.
    agg["local_calls"] = agg["local_calls_simulated"]
    agg["external_calls"] = agg["external_calls_simulated"]

    total_ms = sum(t["elapsed_ms"] for t in timings)
    n_docs = len(timings) or 1
    n_cand = agg["candidates_evaluated"] or 1
    agg_time = {
        "total_ms": round(total_ms, 3),
        "per_doc_ms": round(total_ms / n_docs, 3),
        "per_candidate_ms": round(total_ms / n_cand, 3),
    }

    consensus_total = (
        agg["results_strong"] + agg["results_partial"] + agg["results_conflict"]
        + agg["results_invalid"] + agg["results_human"]
    ) or 1
    rates = {
        "human_rate": round((agg["results_human"]) / consensus_total, 4),
        "conflict_rate": round((agg["results_conflict"]) / consensus_total, 4),
        "invalid_rate": round((agg["results_invalid"]) / consensus_total, 4),
    }
    return {"counters": agg, "timings": agg_time, "consensus_rates": rates}


# ---------------------------------------------------------------------------
# Fallos de TRANSPORTE vs respuestas invalidas del MODELO  (defecto D1)
# ---------------------------------------------------------------------------
# El pipeline R8 degrada CUALQUIER problema de un proveedor al mismo estado
# canonico `INVALID_RESPONSES`, de modo que un endpoint que devuelve 404 y un
# modelo que contesta JSON malformado acaban indistinguibles en
# `results_invalid`. Eso convierte un fallo de INFRAESTRUCTURA en un dictamen de
# CALIDAD, que es exactamente el error de medicion que este bloque debe eliminar.
#
# Aqui NO se reimplementa nada del pipeline: se LEEN los marcadores que el propio
# evaluador ya escribe en el payload (`validation_errors` en local,
# `reason_codes` en external) y se reclasifican en dos categorias disjuntas:
#
#   * FALLO DE TRANSPORTE  -> la llamada nunca obtuvo una respuesta utilizable:
#       - `transport_error:*`         excepcion del transporte (HTTP, timeout, DNS,
#                                     JSON no parseable, forma OpenAI ausente)
#       - `provider_error:*`          error del proveedor (ExternalAIError)
#       - `response_structure_invalid` la respuesta no trae choices[0].message.content
#       - `response_content_not_str`   el contenido no es texto
#   * RESPUESTA INVALIDA DEL MODELO -> el proveedor SI respondio, pero el
#     contenido no supera la validacion (`parse:*`, campos invalidos, demasiado
#     grande...). ESO si es senal de calidad.
TRANSPORT_ERROR_PREFIXES = ("transport_error:",)
TRANSPORT_ERROR_CODES = frozenset({
    "response_structure_invalid",
    "response_content_not_str",
})

# ---------------------------------------------------------------------------
# B1 (ronda 3) -- `provider_error` NO es sinonimo de "fallo de transporte"
# ---------------------------------------------------------------------------
# Tanto `local_llm_shadow` (`validation_errors=["provider_error:<Excepcion>"]`)
# como `external_ai_shadow` (`reason_codes=["provider_error"]` +
# `validation_errors=["<Excepcion>"]`) marcan con la MISMA etiqueta cosas
# radicalmente distintas, porque su `except` agrupa toda la familia
# `ExternalAIError`. En particular `InvalidResponseError` se emite cuando el
# modelo SI contesto (HTTP 200) pero su contenido no es utilizable:
#
#   * `{"relations": []}`               -> "la respuesta no contiene ningun verdicto"
#   * texto libre no-JSON ("no puedo…") -> el extractor de JSON falla
#
# Esas son las averias de CALIDAD canonicas (las mismas que el carril local
# clasifica como `no_relation_extracted`). Contarlas como TRANSPORTE abortaba el
# run con un diagnostico de "fallo de INFRAESTRUCTURA" falso.
#
# La discriminacion es posible SIN tocar `external_ai_shadow` porque ambos
# emisores dejan el NOMBRE de la excepcion subyacente en el payload. Se usa esa
# via (opcion 1 del dictamen). Cuando el nombre no permite decidir (excepcion
# generica `ExternalAIError`, nombre ausente o desconocido) el benchmark NO
# afirma lo que no sabe: la llamada queda INDETERMINADA -- ni transporte (no
# aborta el run) ni calidad (no se presenta como medida del modelo) -- y se
# publica como tal.
CATEGORY_TRANSPORT = "TRANSPORT"
CATEGORY_RESPONDED = "RESPONDED"
CATEGORY_INDETERMINATE = "INDETERMINATE"

# Excepciones que SI implican que la llamada nunca obtuvo respuesta utilizable
# del modelo: red, servidor, autenticacion, ratelimit, timeout, endpoint ausente.
TRANSPORT_EXCEPTION_NAMES = frozenset({
    "ProviderTimeoutError", "ProviderServerError", "ProviderAuthError",
    "ProviderNotFoundError", "RateLimitError", "ProviderTransportError",
    "URLError", "HTTPError", "TimeoutError", "ConnectionError",
    "ConnectionResetError", "ConnectionRefusedError", "socket.timeout",
})
# Excepciones que implican que el proveedor RESPONDIO y el contenido es lo que
# falla: eso es CALIDAD del modelo, la senal que el benchmark debe medir.
QUALITY_EXCEPTION_NAMES = frozenset({
    "InvalidResponseError",
})


# Codigos de `reason_codes` que positivamente indican CONTACTO con el modelo:
#   * `invalid_response`: el modelo respondio (HTTP 200) pero el contenido no es
#     utilizable. Es CALIDAD, no transporte. -> RESPONDED.
QUALITY_REASON_CODES = frozenset({"invalid_response"})

# Codigos de `reason_codes` que indican que la llamada NO llego a contactar el
# modelo, aunque no sean un fallo de transporte de red:
#   * `invalid_candidate`: `RelationContractError`, el candidato se rechazo ANTES
#     de construir la peticion -> contacto CERO. Simetrico con `attempted==0`:
#     nunca puede presentarse como respuesta del modelo. -> INDETERMINATE.
NON_CONTACT_REASON_CODES = frozenset({"invalid_candidate"})

# Campos del payload que solo existen tras un round-trip cronometrado con el
# modelo (los emiten los dos carriles al EJECUTAR la llamada). Sirven de evidencia
# POSITIVA de contacto cuando no hay ningun marcador explicito (defensa en
# profundidad: `latency_ms` puede ser 0 en una respuesta instantanea).
_RESPONSE_EVIDENCE_KEYS = (
    "response_hash", "request_hash", "input_hash", "prompt_hash", "validation_status",
)


def _provider_error_category(name: str) -> str:
    if name in TRANSPORT_EXCEPTION_NAMES:
        return CATEGORY_TRANSPORT
    if name in QUALITY_EXCEPTION_NAMES:
        return CATEGORY_RESPONDED
    return CATEGORY_INDETERMINATE


def _has_response_evidence(payload: dict) -> bool:
    """`True` si el payload prueba POSITIVAMENTE que hubo respuesta del modelo.

    Un round-trip cronometrado (`latency_ms>0`) o cualquier hash de peticion/
    respuesta que el evaluador solo escribe DESPUES de contactar el modelo. Un
    payload sin ninguna de estas senales no autoriza a afirmar que respondio.
    """
    lat = payload.get("latency_ms")
    if isinstance(lat, (int, float)) and not isinstance(lat, bool) and lat > 0:
        return True
    return any(payload.get(k) for k in _RESPONSE_EVIDENCE_KEYS)


def _bare_exception_name(payload: dict) -> str:
    """Nombre de excepcion que `external_ai_shadow` deja en `validation_errors`."""
    for err in payload.get("validation_errors") or ():
        text = str(err).strip()
        if ":" not in text and text.endswith("Error"):
            return text
    return ""


def classify_provider_outcome(payload: Any) -> tuple:
    """Clasifica una llamada en (categoria, tipo). Ver `CATEGORY_*`.

    * `CATEGORY_TRANSPORT`     : la llamada nunca obtuvo respuesta del modelo.
    * `CATEGORY_RESPONDED`     : el proveedor respondio (el contenido puede ser
                                 malo: eso es calidad, no transporte).
    * `CATEGORY_INDETERMINATE` : el marcador del payload NO permite decidir; el
                                 benchmark se abstiene en vez de inventar.

    DEFENSA EN PROFUNDIDAD (ronda 4): el DEFAULT para un payload sin marcador
    reconocido es INDETERMINATE, no RESPONDED. Solo se afirma RESPONDED cuando algo
    indica POSITIVAMENTE que el modelo contesto: un marcador de CALIDAD conocido
    (`validation_errors` no de transporte, p.ej. `parse:*`, campos invalidos, o
    `reason_codes` de calidad), o evidencia de un round-trip cronometrado
    (`_has_response_evidence`). Asi un payload sintetico como `{}` o uno con
    `reason_codes=["invalid_candidate"]` (un `RelationContractError`, que ocurre
    ANTES de contactar el modelo -> contacto cero) ya NO cuenta como respondida; por
    el candado `responded>0` del gate, lleva a NOT_MEASURED en vez de a un APTO
    falso. El candado deja de depender de que ese vector sea inalcanzable.
    """
    if not isinstance(payload, dict):
        # Un payload que ni siquiera es un objeto no autoriza a afirmar nada.
        return (CATEGORY_INDETERMINATE, "no_dict")
    for err in payload.get("validation_errors") or ():
        text = str(err)
        if text.startswith("transport_error:"):
            return (CATEGORY_TRANSPORT, "transport_error")
        if text.startswith("provider_error:"):
            name = text.split(":", 1)[1].strip()
            return (_provider_error_category(name),
                    f"provider_error({name or 'desconocido'})")
        if text in TRANSPORT_ERROR_CODES:
            return (CATEGORY_TRANSPORT, text)
    reason_codes = {str(c) for c in payload.get("reason_codes") or ()}
    for code in reason_codes:
        if code == "provider_error":
            name = _bare_exception_name(payload)
            return (_provider_error_category(name),
                    f"provider_error({name or 'desconocido'})")
    # Contacto CERO explicito: el candidato se rechazo antes de llamar al modelo.
    if reason_codes & NON_CONTACT_REASON_CODES:
        return (CATEGORY_INDETERMINATE, "invalid_candidate")
    # Senal POSITIVA de que el modelo respondio (y el contenido es lo que falla, si
    # falla): esto es CALIDAD, la senal que el benchmark debe medir.
    #   (a) `validation_errors` presentes que NO son de transporte (se descarto
    #       arriba): el modelo produjo contenido que la validacion rechazo
    #       (`parse:*`, `response_too_large`, `predicate_invalid`, ...).
    #   (b) `reason_codes` de calidad conocidos (`invalid_response`).
    #   (c) evidencia de un round-trip cronometrado.
    if payload.get("validation_errors"):
        return (CATEGORY_RESPONDED, None)
    if reason_codes & QUALITY_REASON_CODES:
        return (CATEGORY_RESPONDED, None)
    if _has_response_evidence(payload):
        return (CATEGORY_RESPONDED, None)
    # DEFAULT SEGURO: sin evidencia de contacto, el benchmark se abstiene.
    return (CATEGORY_INDETERMINATE, "sin_evidencia_de_respuesta")


def classify_provider_payload(payload: Any) -> Optional[str]:
    """Tipo de FALLO DE TRANSPORTE, o `None` si NO es transporte.

    `None` ya NO significa "respondio": puede ser tambien INDETERMINADO. Para
    distinguirlo usa `classify_provider_outcome`.
    """
    category, kind = classify_provider_outcome(payload)
    return kind if category == CATEGORY_TRANSPORT else None


def provider_transport_errors(results: list[dict]) -> dict:
    """Contadores de fallos de TRANSPORTE por proveedor, con desglose por tipo.

    `attempted` son las llamadas con payload presente (respondidas o fallidas);
    `errors` las que fallaron en transporte; `responded` la diferencia. La `rate`
    es errors/attempted y es la magnitud que gobierna el aborto ruidoso del
    runner (ver `runner.PROVIDER_TRANSPORT_ERROR_MAX_RATE`).
    """
    out: dict[str, Any] = {}
    indeterminate: dict[str, Any] = {}
    total_att = 0
    total_err = 0
    total_ind = 0
    for key in ("local", "external"):
        attempted = 0
        by_type: dict[str, int] = {}
        ind_by_type: dict[str, int] = {}
        for rec in results or ():
            payload = rec.get(key)
            if not isinstance(payload, dict):
                continue
            attempted += 1
            category, kind = classify_provider_outcome(payload)
            if category == CATEGORY_TRANSPORT and kind:
                by_type[kind] = by_type.get(kind, 0) + 1
            elif category == CATEGORY_INDETERMINATE and kind:
                ind_by_type[kind] = ind_by_type.get(kind, 0) + 1
        errors = sum(by_type.values())
        inds = sum(ind_by_type.values())
        total_att += attempted
        total_err += errors
        total_ind += inds
        out[key] = {
            "attempted": attempted,
            # `responded` excluye tanto los fallos de transporte como las
            # llamadas INDETERMINADAS: no consta que respondieran.
            "responded": attempted - errors - inds,
            "errors": errors,
            "rate": round(errors / attempted, 4) if attempted else 0.0,
            "by_type": dict(sorted(by_type.items())),
        }
        indeterminate[key] = {
            "count": inds,
            "rate": round(inds / attempted, 4) if attempted else 0.0,
            "by_type": dict(sorted(ind_by_type.items())),
        }
    out["total_attempted"] = total_att
    out["total_errors"] = total_err
    # RESPONDIDAS CONFIRMADAS (ronda 4, bloqueante 1): intentadas que NO fueron ni
    # fallo de transporte ni INDETERMINADAS. Es el unico contador que prueba que
    # ALGUN proveedor llego a contestar. Un run con `total_attempted>0` pero
    # `total_responded==0` (p.ej. 100% INDETERMINADAS por `SecretLeakError` /
    # `ConfigError` / `ExternalAIError` base) NO ha medido a ningun modelo: el
    # punto de contacto es cero, igual que con `total_attempted==0`.
    out["total_responded"] = total_att - total_err - total_ind
    out["rate"] = round(total_err / total_att, 4) if total_att else 0.0
    # B1: tercera categoria EXPLICITA. NO cuenta como transporte (no aborta el
    # run) y NO se presenta como calidad. Se publica tal cual.
    indeterminate["total"] = total_ind
    indeterminate["rate"] = round(total_ind / total_att, 4) if total_att else 0.0
    indeterminate["note"] = (
        "llamadas cuyo marcador ('provider_error' generico) NO permite decidir si "
        "el proveedor respondio: NO se cuentan como transporte ni como calidad"
    )
    out["indeterminate"] = indeterminate
    out["total_indeterminate"] = total_ind
    return out


def _percentile(values: list[float], q: float) -> Optional[float]:
    """Percentil por interpolacion lineal (determinista). None si no hay datos."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return round(float(xs[0]), 3)
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return round(float(xs[lo] + (xs[hi] - xs[lo]) * frac), 3)


def _latency_block(values: list[float]) -> dict:
    return {
        "samples": len(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": round(float(max(values)), 3) if values else None,
    }


def provider_cost(results: list[dict], source_summaries: list[dict]) -> dict:
    """Coste y latencia REALES por proveedor (local / external).

    * `calls`   : llamadas contadas por el PROPIO pipeline
                  (`local_calls_simulated` / `external_calls_simulated`; el
                  contador se llama "simulated" por historia del pipeline, pero
                  se incrementa tambien -- y sobre todo -- cuando las llamadas son
                  REALES: ver `calls_counter_note`).
    * `payloads`: nº de candidatos con evaluacion presente (payload no nulo).
    * latencias : p50 / p95 / maximo de `latency_ms` SOLO de las llamadas que el
                  proveedor RESPONDIO. Las latencias de fallos de transporte
                  (404 inmediato, timeout) no describen al modelo y se reportan
                  aparte en `transport_errors`; mezclarlas produce el p50 de 0 ms
                  que motivo el defecto D1.
    * `transport_errors`: fallos de TRANSPORTE (infraestructura), disjuntos de las
                  respuestas invalidas del MODELO. Ver `provider_transport_errors`.

    Con los proveedores DESACTIVADOS (caso por defecto y unico en CI) devuelve
    ceros y `None` limpios: sin muestras no se inventa ninguna latencia.
    """
    calls = {"local": 0, "external": 0}
    for s in source_summaries or ():
        calls["local"] += int(s.get("local_calls_simulated", 0) or 0)
        calls["external"] += int(s.get("external_calls_simulated", 0) or 0)

    transport = provider_transport_errors(results or [])

    fail_closed = sum(int(s.get("provider_fail_closed", 0) or 0)
                      for s in source_summaries or ())

    latencies: dict[str, list[float]] = {"local": [], "external": []}
    failed_latencies: dict[str, list[float]] = {"local": [], "external": []}
    indeterminate_latencies: dict[str, list[float]] = {"local": [], "external": []}
    payloads = {"local": 0, "external": 0}
    statuses: dict[str, dict[str, int]] = {"local": {}, "external": {}}
    for rec in results or ():
        for key in ("local", "external"):
            status = rec.get(f"{key}_status")
            if status:
                statuses[key][str(status)] = statuses[key].get(str(status), 0) + 1
            payload = rec.get(key)
            if not isinstance(payload, dict):
                continue
            payloads[key] += 1
            lat = payload.get("latency_ms")
            if isinstance(lat, (int, float)) and not isinstance(lat, bool):
                category, _kind = classify_provider_outcome(payload)
                bucket = {
                    CATEGORY_TRANSPORT: failed_latencies,
                    CATEGORY_INDETERMINATE: indeterminate_latencies,
                }.get(category, latencies)
                bucket[key].append(float(lat))

    out = {}
    for key in ("local", "external"):
        out[key] = {
            "calls": calls[key],
            "payloads": payloads[key],
            "statuses": dict(sorted(statuses[key].items())),
            "latency": _latency_block(latencies[key]),
            "failed_latency": _latency_block(failed_latencies[key]),
            "indeterminate_latency": _latency_block(indeterminate_latencies[key]),
            "transport_errors": transport[key],
            "transport_error_rate": transport[key]["rate"],
            "indeterminate": transport["indeterminate"][key],
        }
    out["total_calls"] = calls["local"] + calls["external"]
    out["transport_errors"] = transport
    out["transport_error_rate"] = transport["rate"]
    out["indeterminate"] = transport["indeterminate"]
    out["indeterminate_rate"] = transport["indeterminate"]["rate"]
    # N7: fallos NO CATALOGADOS. El pipeline cuenta en `provider_fail_closed` las
    # veces que un proveedor habilitado no pudo evaluar un candidato; esas
    # llamadas no dejan payload, asi que no aparecen ni como `attempted` ni como
    # `errors` (rate 0.0 y gate PASS con el carril entero muerto). Se publica
    # junto a `attempted` para que el gate pueda contrastarlo.
    out["fail_closed"] = fail_closed
    out["fail_closed_note"] = (
        "candidatos que un proveedor habilitado no llego a evaluar (sin payload): "
        "NO aparecen en attempted ni en errors; contrastar con attempted"
    )
    out["calls_counter_note"] = (
        "calls proviene de summary.local_calls_simulated/external_calls_simulated "
        "del pipeline: el sufijo '_simulated' es historico y NO implica simulacion; "
        "cuenta llamadas REALES cuando hay transporte/proveedor inyectado."
    )
    return out


__all__ = [
    "global_metrics",
    "strict_metrics",
    "per_predicate_metrics",
    "predicted_predicate_distribution",
    "structural_quality",
    "decision_confusion",
    "aggregate_operational",
    "provider_cost",
    "provider_transport_errors",
    "classify_provider_payload",
    "classify_provider_outcome",
    "CATEGORY_TRANSPORT",
    "CATEGORY_RESPONDED",
    "CATEGORY_INDETERMINATE",
    "TRANSPORT_EXCEPTION_NAMES",
    "QUALITY_EXCEPTION_NAMES",
    "QUALITY_REASON_CODES",
    "NON_CONTACT_REASON_CODES",
    "TRANSPORT_ERROR_PREFIXES",
    "TRANSPORT_ERROR_CODES",
]
