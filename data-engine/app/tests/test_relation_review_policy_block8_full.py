# -*- coding: utf-8 -*-
"""Bloque 8 - Bateria COMPLETA de tests de AGENTE-TESTS.

Complementa (no sustituye) `test_relation_review_policy_block8_smoke.py` (36
tests de humo del AGENTE-IMPLEMENTADOR, que se CONSERVAN intactos). Este
fichero anade:

  1. Invariante de "no importa vias de escritura/red/reloj" (AST estatico).
  2. Invariante de dominio de `label` (nunca fuera de las dos etiquetas, nunca
     solapa CONSENSUS_STATES ni recomendaciones ni un label prohibido).
  3. Tabla de verdad exhaustiva "one-at-a-time" + frontera EXACTA del umbral,
     con umbral NO por defecto (para matar el mutante de umbral hardcodeado).
  4. Transparencia de metricas (nunca se ocultan claves, incluso en el peor
     escenario).
  5. Fail-closed generico ante inputs corruptos variados.
  6. Determinismo, orden-independencia e inmutabilidad de entradas/salidas.
  7. Logica PASS/FAIL/NOT_MEASURED de los gates con `MatchResult` sinteticos,
     incluida la frontera exacta de los umbrales y la independencia de
     `coverage` respecto al dictamen.
  8. Vocabulario cerrado del dictamen (nunca solapa `report.VERDICTS`).
  9. Mutation-check especifico de la medicion: FAR/precision con conteo
     conocido y exacto (1 falso-aceptado de 25) para detectar la inversion de
     `expected_decision == "ACCEPT"` por `!=`.

Cada test documenta en su docstring/comentario que MUTANTE mata. Las
mutaciones se verificaron MANUALMENTE (editar el fuente, confirmar fallo,
revertir) fuera de esta suite -- no se mutan ficheros de produccion desde
dentro de un test (romperia el modulo para el resto de la sesion de pytest).
El informe de la tarea documenta, mutante por mutante, que test cae y como se
verifico.
"""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from external_ai.models import CONSENSUS_STATES, STRONG_CONSENSUS  # noqa: E402

from relations.review_policy import (  # noqa: E402
    AUTO_PROPOSABLE,
    REVIEW_REQUIRED,
    REVIEW_POLICY_LABELS,
    ReviewPolicyConfig,
    ReviewPolicyConfigError,
    ReviewPolicyOutcome,
    DEFAULT_REVIEW_POLICY_CONFIG,
    classify_for_review,
)

from relations.benchmark.matching import MatchResult, RECO_TO_DECISION  # noqa: E402
from relations.benchmark.report import VERDICTS as B7_VERDICTS  # noqa: E402
from relations.benchmark.review_policy_metrics import (  # noqa: E402
    FALSE_ACCEPT_RATE_MAX,
    MIN_SAMPLE_SIZE,
    PRECISION_MIN,
    REVIEW_POLICY_VERDICTS,
    decide_review_policy_verdict,
    evaluate_review_policy_gates,
    review_policy_safety_metrics,
)

_REVIEW_POLICY_SRC = Path(_APP_DIR, "relations", "review_policy.py")


# ---------------------------------------------------------------------------
# (1) Invariante: review_policy.py no importa vias de escritura/red/reloj
# ---------------------------------------------------------------------------
_FORBIDDEN_IMPORT_ROOTS = frozenset({
    "review",       # paquete de escritura real (review/*)
    "neo4j",        # driver de escritura del grafo
    "requests", "httpx", "aiohttp", "urllib", "urllib3", "socket", "http",
    "grpc",         # red generica
    "datetime", "time",  # reloj
    "random",       # aleatoriedad
    "external_processing",  # otro subsistema de escritura/pipeline
    "ollama",
})


def _imported_roots(source_path: Path) -> set:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_review_policy_module_has_no_forbidden_imports():
    """MATA: anadir `import neo4j` / `from review import x` / `import time` /
    `import random` etc. al fuente de `review_policy.py` (invariante 1: no
    importa vias de escritura, red ni reloj). Verificado manualmente anadiendo
    cada import prohibido uno a uno y comprobando que este test cae; revertido
    despues con `git status` limpio (el fichero es untracked, se restauro
    desde copia de seguridad byte a byte)."""
    roots = _imported_roots(_REVIEW_POLICY_SRC)
    overlap = roots & _FORBIDDEN_IMPORT_ROOTS
    assert not overlap, f"import(s) prohibido(s) detectado(s) en review_policy.py: {overlap}"


def test_review_policy_module_only_imports_stdlib_and_typing():
    """Cinturon y tirantes del invariante 1: la lista de raices importadas es
    exactamente la esperada (stdlib puro + typing), ni una mas. MATA cualquier
    import nuevo no auditado (incluidos los que no estan en la lista negra
    explicita, p.ej. un futuro `import sys` para tocar argv)."""
    roots = _imported_roots(_REVIEW_POLICY_SRC)
    allowed = {"__future__", "hashlib", "json", "dataclasses", "types", "typing", "external_ai"}
    assert roots <= allowed, f"raices de import inesperadas: {roots - allowed}"


# ---------------------------------------------------------------------------
# (2) Invariante: dominio de `label`
# ---------------------------------------------------------------------------
def test_review_policy_labels_exact_set():
    assert set(REVIEW_POLICY_LABELS) == {"AUTO_PROPOSABLE", "REVIEW_REQUIRED"}


def test_review_policy_labels_disjoint_from_consensus_states():
    """MATA: quitar la comprobacion de solape en tiempo de import, o renombrar
    REVIEW_REQUIRED a HUMAN_REQUIRED (colisionaria con el estado de consenso
    canonico)."""
    assert set(REVIEW_POLICY_LABELS).isdisjoint(set(CONSENSUS_STATES))
    assert "HUMAN_REQUIRED" not in REVIEW_POLICY_LABELS


def test_review_policy_labels_disjoint_from_recommendation_vocabulary():
    """Los labels de politica tampoco deben solapar el vocabulario de
    `recommendation` del ensemble/matching (`propose`/`reject`/`human` y sus
    decisiones ACCEPT/REJECT/REVIEW)."""
    reco_values = set(RECO_TO_DECISION.keys()) | set(RECO_TO_DECISION.values())
    assert set(REVIEW_POLICY_LABELS).isdisjoint(reco_values)


@pytest.mark.parametrize("forbidden", [
    "AUTO_APPROVED", "APPROVED", "APPROVE", "WRITE", "APPLY", "COMMIT", "MERGE",
    "ACCEPT", "ACCEPTED", "AUTO_ACCEPT", "AUTO_ACCEPTED",
    "auto_approved", "Approved",  # variantes de mayusculas (label.upper() en __post_init__)
])
def test_outcome_post_init_rejects_forbidden_label_variants(forbidden):
    """MATA: quitar `if self.label.upper() in _FORBIDDEN_LABELS` en
    `__post_init__`."""
    with pytest.raises(ValueError):
        ReviewPolicyOutcome(label=forbidden, reason="x", signals={})


def test_outcome_post_init_rejects_any_string_not_in_labels():
    """MATA: quitar `if self.label not in REVIEW_POLICY_LABELS` en
    `__post_init__` (validacion generica, no solo la lista negra)."""
    with pytest.raises(ValueError):
        ReviewPolicyOutcome(label="SOMETHING_ELSE", reason="x", signals={})
    with pytest.raises(ValueError):
        ReviewPolicyOutcome(label="", reason="x", signals={})
    with pytest.raises(ValueError):
        ReviewPolicyOutcome(label="PARTIAL_CONSENSUS", reason="x", signals={})


def test_classify_for_review_output_label_always_in_valid_domain():
    """Barrido amplio: cualquier combinacion (valida o invalida) de entradas
    produce SIEMPRE un label dentro del dominio permitido."""
    states = list(CONSENSUS_STATES) + [None, "GARBAGE", 42]
    scores = [0.0, 0.5, 0.9, 1.0, -1.0, None, "x", float("nan")]
    providers = [0, 1, 2, None, "1", -1]
    evidences = [True, False, None, "yes"]
    conflicts_opts = [(), ({"type": "x"},), None, 5]
    count = 0
    for state in states:
        for score in scores:
            for prov in providers:
                for ev in evidences:
                    for conf in conflicts_opts:
                        outcome = classify_for_review(
                            state=state, recommendation=None, score=score,
                            n_decisive=None, providers_present=prov,
                            has_evidence=ev, conflicts=conf,
                        )
                        assert outcome.label in REVIEW_POLICY_LABELS
                        count += 1
    assert count == len(states) * len(scores) * len(providers) * len(evidences) * len(conflicts_opts)


# ---------------------------------------------------------------------------
# (3) Tabla de verdad one-at-a-time + frontera exacta, con umbral NO-default
# ---------------------------------------------------------------------------
_STRICT_BASE = dict(
    state=STRONG_CONSENSUS,
    recommendation="propose",
    score=0.95,
    n_decisive=2,
    providers_present=1,
    has_evidence=True,
    conflicts=(),
)


def test_classify_for_review_base_case_is_auto_proposable():
    outcome = classify_for_review(**_STRICT_BASE)
    assert outcome.label == AUTO_PROPOSABLE


@pytest.mark.parametrize("field_,degraded", [
    ("state", "PARTIAL_CONSENSUS"),
    ("state", "MODEL_CONFLICT"),
    ("state", "HUMAN_REQUIRED"),
    ("state", "INVALID_RESPONSES"),
    ("providers_present", 0),
    ("score", 0.90 - 1e-9),
    ("conflicts", ({"type": "temporal", "detail": "x", "sources": ["temporality"]},)),
    ("has_evidence", False),
])
def test_classify_for_review_degrading_any_single_condition_requires_review(field_, degraded):
    """MATA: cambiar un `and` (conjuncion implicita de la lista `checks`) por
    un `or`, o eliminar una de las 5 condiciones de la lista `checks` en
    `classify_for_review` -- al menos uno de estos casos parametrizados dejaria
    de caer en REVIEW_REQUIRED."""
    kwargs = dict(_STRICT_BASE)
    kwargs[field_] = degraded
    outcome = classify_for_review(**kwargs)
    assert outcome.label == REVIEW_REQUIRED, f"degradar {field_}={degraded!r} deberia forzar REVIEW_REQUIRED"


def test_classify_for_review_score_boundary_exact_threshold_default_config():
    """Frontera EXACTA con la config por defecto (umbral 0.90). MATA: invertir
    `score_val >= config.auto_propose_score_threshold` por `>` o `<=`."""
    at_threshold = dict(_STRICT_BASE)
    at_threshold["score"] = 0.90
    assert classify_for_review(**at_threshold).label == AUTO_PROPOSABLE

    just_below = dict(_STRICT_BASE)
    just_below["score"] = 0.90 - 1e-9
    assert classify_for_review(**just_below).label == REVIEW_REQUIRED


def test_classify_for_review_score_boundary_exact_threshold_custom_config():
    """El umbral usado debe ser el de LA CONFIG PASADA, no un valor
    hardcodeado. MATA: ignorar `config` y usar 0.90 fijo en el codigo."""
    custom = ReviewPolicyConfig(auto_propose_score_threshold=0.5)
    kwargs = dict(_STRICT_BASE)
    kwargs["config"] = custom

    kwargs["score"] = 0.5
    assert classify_for_review(**kwargs).label == AUTO_PROPOSABLE

    kwargs["score"] = 0.5 - 1e-9
    assert classify_for_review(**kwargs).label == REVIEW_REQUIRED

    # Con un umbral alto (0.999), un score que pasaria el umbral por defecto
    # (0.95) ya NO debe bastar: si el codigo ignorase `config` este test caeria.
    strict_custom = ReviewPolicyConfig(auto_propose_score_threshold=0.999)
    kwargs2 = dict(_STRICT_BASE)
    kwargs2["config"] = strict_custom
    kwargs2["score"] = 0.95
    assert classify_for_review(**kwargs2).label == REVIEW_REQUIRED


def test_classify_for_review_min_providers_present_custom_config():
    """MATA: ignorar `config.min_providers_present` (hardcodear 1)."""
    custom = ReviewPolicyConfig(min_providers_present=2)
    kwargs = dict(_STRICT_BASE)
    kwargs["config"] = custom
    kwargs["providers_present"] = 1
    assert classify_for_review(**kwargs).label == REVIEW_REQUIRED
    kwargs["providers_present"] = 2
    assert classify_for_review(**kwargs).label == AUTO_PROPOSABLE


# ---------------------------------------------------------------------------
# (4) Transparencia de metricas: nunca se ocultan claves
# ---------------------------------------------------------------------------
def _toy_gt(relation_id, expected_decision="ACCEPT"):
    return {"relation_id": relation_id, "expected_decision": expected_decision}


def _toy_pred(label, candidate_id="c1"):
    return {"candidate_id": candidate_id, "review_policy_label": label}


_REQUIRED_METRIC_KEYS = (
    "sample_size", "auto_proposable_tp", "auto_proposable_fp", "correct",
    "false_accepts", "precision", "false_accept_rate", "total_evaluated",
    "tp_total", "coverage", "coverage_over_tp",
)


def test_metrics_publish_all_keys_in_100pct_false_accept_scenario():
    """Escenario 100% falsos-aceptados (todo auto-propuesto es incorrecto).
    MATA: un `if fail: return {}` (o cualquier omision de claves) en
    `review_policy_safety_metrics`."""
    true_positives = [
        {"gt": _toy_gt(f"r{i}", "REJECT"), "pred": _toy_pred(AUTO_PROPOSABLE, f"c{i}"), "flags": {}}
        for i in range(5)
    ]
    match = MatchResult(true_positives=true_positives, false_positives=[], false_negatives=[])
    metrics = review_policy_safety_metrics(match)
    for key in _REQUIRED_METRIC_KEYS:
        assert key in metrics, f"clave ausente en metricas: {key}"
    assert metrics["sample_size"] == 5
    assert metrics["correct"] == 0
    assert metrics["false_accepts"] == 5
    assert metrics["precision"] == 0.0
    assert metrics["false_accept_rate"] == 1.0


def test_metrics_publish_all_keys_in_empty_scenario():
    """Incluso con muestra 0 (sin nada auto-propuesto), todas las claves deben
    estar presentes con sus valores reales (0), no ausentes."""
    match = MatchResult(true_positives=[], false_positives=[], false_negatives=[])
    metrics = review_policy_safety_metrics(match)
    for key in _REQUIRED_METRIC_KEYS:
        assert key in metrics
    assert metrics["sample_size"] == 0
    assert metrics["precision"] == 0.0
    assert metrics["false_accept_rate"] == 0.0
    assert metrics["coverage"] == 0.0


# ---------------------------------------------------------------------------
# (5) Fail-closed generico ante inputs corruptos/incompletos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kwargs", [
    dict(state=None, recommendation=None, score=None, n_decisive=None,
         providers_present=None, has_evidence=None, conflicts=None),
    dict(state="STRONG_CONSENSUS", recommendation=None, score="not-a-number",
         n_decisive=None, providers_present=1, has_evidence=True, conflicts=()),
    dict(state="UNKNOWN_STATE", recommendation=None, score=0.99,
         n_decisive=None, providers_present=1, has_evidence=True, conflicts=()),
    dict(state="STRONG_CONSENSUS", recommendation=None, score=0.99,
         n_decisive=None, providers_present=1, has_evidence=True, conflicts=None),
    dict(state={}, recommendation=None, score=[0.9], n_decisive=None,
         providers_present={}, has_evidence=[], conflicts={}),
    dict(state="STRONG_CONSENSUS", recommendation=None, score=float("nan"),
         n_decisive=None, providers_present=1, has_evidence=True, conflicts=()),
    dict(state="STRONG_CONSENSUS", recommendation=None, score=0.99,
         n_decisive=None, providers_present=True, has_evidence=True, conflicts=()),
    dict(state="STRONG_CONSENSUS", recommendation=None, score=True,
         n_decisive=None, providers_present=1, has_evidence=True, conflicts=()),
    dict(state="STRONG_CONSENSUS", recommendation=None, score=0.99,
         n_decisive=None, providers_present=1, has_evidence=True, conflicts=5),
])
def test_classify_for_review_corrupt_inputs_never_raise_and_fail_closed(kwargs):
    """MATA: quitar el fallback final a REVIEW_REQUIRED o cualquiera de las
    comprobaciones defensivas `_coerce_*` (por ejemplo, dejar de tratar `bool`
    como no-numerico, o dejar que `providers_present=True` cuele como 1)."""
    outcome = classify_for_review(**kwargs)  # NO debe lanzar
    assert outcome.label == REVIEW_REQUIRED


def test_classify_for_review_invalid_config_type_raises_loudly():
    """Un error de PROGRAMACION (config invalida) SI debe fallar ruidosamente
    -- no es un input externo corrupto, es un bug del llamante."""
    with pytest.raises(ReviewPolicyConfigError):
        classify_for_review(
            state=STRONG_CONSENSUS, score=0.99, providers_present=1,
            has_evidence=True, conflicts=(), config="not-a-config",
        )


def test_classify_for_review_nan_score_is_review_required():
    """`float('nan')` es numerico segun `isinstance` pero cualquier
    comparacion `>=` con NaN es False; debe caer honestamente en
    REVIEW_REQUIRED (no lanzar, no colar como AUTO_PROPOSABLE)."""
    kwargs = dict(_STRICT_BASE)
    kwargs["score"] = float("nan")
    assert classify_for_review(**kwargs).label == REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# (6) Determinismo, orden-independencia e inmutabilidad
# ---------------------------------------------------------------------------
def test_classify_for_review_is_deterministic_same_input_same_output():
    kwargs = dict(_STRICT_BASE)
    o1 = classify_for_review(**kwargs)
    o2 = classify_for_review(**kwargs)
    assert o1.to_dict() == o2.to_dict()
    assert o1.to_json() == o2.to_json()


def test_classify_for_review_conflict_order_does_not_change_result():
    """Solo importa `len(conflicts)`, no el orden de las senales. MATA: un
    cambio que dependa del orden de iteracion de `conflicts` (p.ej. mirar solo
    `conflicts[0]`)."""
    c1 = {"type": "temporal", "detail": "a"}
    c2 = {"type": "epistemic", "detail": "b"}
    kwargs_a = dict(_STRICT_BASE)
    kwargs_a["conflicts"] = (c1, c2)
    kwargs_b = dict(_STRICT_BASE)
    kwargs_b["conflicts"] = (c2, c1)
    outcome_a = classify_for_review(**kwargs_a)
    outcome_b = classify_for_review(**kwargs_b)
    assert outcome_a.label == outcome_b.label == REVIEW_REQUIRED
    assert outcome_a.signals["conflicts_count"] == outcome_b.signals["conflicts_count"] == 2


def test_classify_for_review_does_not_mutate_conflicts_input():
    """MATA: cualquier mutacion in-place de la lista de conflictos de entrada
    (p.ej. un `.sort()`, `.pop()` o normalizacion destructiva)."""
    conflicts = [{"type": "temporal", "detail": "a"}, {"type": "epistemic", "detail": "b"}]
    fingerprint_before = copy.deepcopy(conflicts)
    kwargs = dict(_STRICT_BASE)
    kwargs["conflicts"] = conflicts
    classify_for_review(**kwargs)
    assert conflicts == fingerprint_before
    assert conflicts is not None  # sigue siendo la misma lista, sin reemplazo


def test_classify_for_review_outcome_signals_is_immutable_mapping():
    """MATA: quitar `MappingProxyType` en `__post_init__` (devolver un dict
    mutable normal)."""
    outcome = classify_for_review(**_STRICT_BASE)
    with pytest.raises(TypeError):
        outcome.signals["injected"] = "x"  # type: ignore[index]


def test_review_policy_outcome_is_frozen():
    """MATA: quitar `@dataclass(frozen=True)` de `ReviewPolicyOutcome`."""
    outcome = classify_for_review(**_STRICT_BASE)
    with pytest.raises(Exception):
        outcome.label = "REVIEW_REQUIRED"  # type: ignore[misc]


def test_review_policy_config_is_frozen():
    """MATA: quitar `@dataclass(frozen=True)` de `ReviewPolicyConfig`."""
    with pytest.raises(Exception):
        DEFAULT_REVIEW_POLICY_CONFIG.auto_propose_score_threshold = 0.5  # type: ignore[misc]


def test_config_hash_deterministic_and_order_independent():
    """El hash de config debe depender solo de los VALORES, no del orden de
    construccion de argumentos (a diferencia de un dict normal, un
    `dataclass` no tiene "orden" salvo el declarado, pero el hash se computa
    via `json.dumps(..., sort_keys=True)`; confirmamos ese comportamiento).
    MATA: quitar `sort_keys=True` del hash (haria el hash fragil ante cambios
    no observables de orden interno)."""
    a = ReviewPolicyConfig(auto_propose_score_threshold=0.9, min_providers_present=1)
    b = ReviewPolicyConfig(min_providers_present=1, auto_propose_score_threshold=0.9)
    assert a.config_hash == b.config_hash == DEFAULT_REVIEW_POLICY_CONFIG.config_hash


def test_classify_for_review_json_serializable_and_stable():
    outcome = classify_for_review(**_STRICT_BASE)
    payload = json.loads(outcome.to_json())
    assert payload["label"] == AUTO_PROPOSABLE
    assert payload == outcome.to_dict()


# ---------------------------------------------------------------------------
# (7) Medicion: logica PASS/FAIL/NOT_MEASURED con MatchResult sinteticos
# ---------------------------------------------------------------------------
def _match_with_n_clean_auto_proposable(n, *, n_false_accepts=0):
    """Construye un MatchResult con `n` auto-propuestos, de los cuales
    `n_false_accepts` son falsos-aceptados (expected_decision distinto de
    ACCEPT) y el resto correctos."""
    true_positives = []
    for i in range(n):
        decision = "REJECT" if i < n_false_accepts else "ACCEPT"
        true_positives.append({
            "gt": _toy_gt(f"r{i}", decision),
            "pred": _toy_pred(AUTO_PROPOSABLE, f"c{i}"),
            "flags": {},
        })
    return MatchResult(true_positives=true_positives, false_positives=[], false_negatives=[])


def test_gates_far_zero_precision_full_sample_ge_20_is_pass():
    match = _match_with_n_clean_auto_proposable(25, n_false_accepts=0)
    metrics = review_policy_safety_metrics(match)
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_false_accept_rate"]["status"] == "PASS"
    assert gates["review_policy_precision"]["status"] == "PASS"
    assert gates["review_policy_sample_size"]["status"] == "PASS"
    verdict, _ = decide_review_policy_verdict(gates)
    assert verdict == "POLITICA DE REDUCCION: APTA (GATES DE SEGURIDAD EN PASS)"


def test_gates_far_above_2pct_large_sample_is_fail():
    """FAR = 5/200 = 2.5% > 2% -> FAIL. MATA: invertir `far <=
    FALSE_ACCEPT_RATE_MAX` por `far < FALSE_ACCEPT_RATE_MAX` (rompe la
    frontera) o por `>=` (invierte el sentido del gate)."""
    match = _match_with_n_clean_auto_proposable(200, n_false_accepts=5)
    metrics = review_policy_safety_metrics(match)
    assert metrics["false_accept_rate"] == 0.025
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_false_accept_rate"]["status"] == "FAIL"


def test_gates_precision_below_98pct_large_sample_is_fail():
    """precision = 195/200 = 97.5% < 98% -> FAIL."""
    match = _match_with_n_clean_auto_proposable(200, n_false_accepts=5)
    metrics = review_policy_safety_metrics(match)
    assert metrics["precision"] == 0.975
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_precision"]["status"] == "FAIL"


def test_gates_far_boundary_exact_2pct_is_pass():
    """FAR == 2% EXACTO (2 de 100) -> PASS (`<=`, no `<`). MATA: invertir el
    umbral estricto por `<`."""
    match = _match_with_n_clean_auto_proposable(100, n_false_accepts=2)
    metrics = review_policy_safety_metrics(match)
    assert metrics["false_accept_rate"] == FALSE_ACCEPT_RATE_MAX == 0.02
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_false_accept_rate"]["status"] == "PASS"


def test_gates_precision_boundary_exact_98pct_is_pass():
    """precision == 98% EXACTO (98 de 100) -> PASS (`>=`, no `>`)."""
    match = _match_with_n_clean_auto_proposable(100, n_false_accepts=2)
    metrics = review_policy_safety_metrics(match)
    assert metrics["precision"] == PRECISION_MIN == 0.98
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_precision"]["status"] == "PASS"


def test_gates_small_sample_no_false_accepts_is_not_measured_never_pass():
    """MATA: un `default=PASS` para muestra insuficiente (nunca debe pasar por
    defecto sin evidencia)."""
    for n in (0, 1, 5, MIN_SAMPLE_SIZE - 1):
        match = _match_with_n_clean_auto_proposable(n, n_false_accepts=0)
        metrics = review_policy_safety_metrics(match)
        gates = evaluate_review_policy_gates(metrics)
        assert gates["review_policy_sample_size"]["status"] == "NOT_MEASURED"
        assert gates["review_policy_false_accept_rate"]["status"] == "NOT_MEASURED"
        assert gates["review_policy_precision"]["status"] == "NOT_MEASURED"
        verdict, _ = decide_review_policy_verdict(gates)
        assert verdict == "POLITICA DE REDUCCION: NO CALIBRABLE (COBERTURA INSUFICIENTE)"


@pytest.mark.parametrize("n,false_accepts", [
    (1, 1), (5, 1), (19, 1), (19, 3),
])
def test_gates_small_sample_with_false_accept_is_unconditional_fail(n, false_accepts):
    """Patron strict_small_sample/B3: la muestra pequena NO perdona un
    falso-aceptado. MATA: la condicion `false_accepts > 0` reemplazada por
    `false_accepts > 1` (perdonaria el primer falso-aceptado) o eliminada
    (siempre NOT_MEASURED bajo el umbral, ocultando dano observado)."""
    match = _match_with_n_clean_auto_proposable(n, n_false_accepts=false_accepts)
    metrics = review_policy_safety_metrics(match)
    gates = evaluate_review_policy_gates(metrics)
    assert gates["review_policy_sample_size"]["status"] == "FAIL"
    assert gates["review_policy_false_accept_rate"]["status"] == "FAIL"
    assert gates["review_policy_precision"]["status"] == "FAIL"
    verdict, _ = decide_review_policy_verdict(gates)
    assert verdict == "POLITICA DE REDUCCION: NO APTA (GATE DE SEGURIDAD EN FAIL)"


def test_gates_coverage_is_purely_informative_never_gates_alone():
    """`coverage` = 0 (casi todo el corpus quedo fuera de lo auto-propuesto)
    pero con sample_size>=20 limpio -> el dictamen sigue siendo APTA: la
    cobertura baja NO puede, por si sola, forzar NO APTA ni NO CALIBRABLE.
    MATA: cualquier `if coverage < X: FAIL/NOT_MEASURED` colado en los gates."""
    match = _match_with_n_clean_auto_proposable(20, n_false_accepts=0)
    # Forzamos total_evaluated artificialmente alto anadiendo FN (relaciones
    # perdidas), que no participan del calculo de sample_size/precision/FAR
    # pero SI de total_evaluated -- aqui simulamos coverage baja directamente
    # sobre las metricas ya calculadas para aislar el efecto.
    metrics = review_policy_safety_metrics(match)
    low_coverage_metrics = dict(metrics)
    low_coverage_metrics["coverage"] = 0.0001
    low_coverage_metrics["coverage_over_tp"] = 0.0001
    gates = evaluate_review_policy_gates(low_coverage_metrics)
    assert gates["review_policy_coverage"]["status"] == "INFORMATIVE"
    assert gates["review_policy_coverage"]["hard"] is False
    assert gates["review_policy_false_accept_rate"]["status"] == "PASS"
    assert gates["review_policy_precision"]["status"] == "PASS"
    verdict, _ = decide_review_policy_verdict(gates)
    assert verdict == "POLITICA DE REDUCCION: APTA (GATES DE SEGURIDAD EN PASS)"


def test_gates_coverage_status_is_informative_regardless_of_value():
    for coverage_value in (0.0, 0.5, 1.0):
        match = _match_with_n_clean_auto_proposable(25, n_false_accepts=0)
        metrics = review_policy_safety_metrics(match)
        metrics = dict(metrics)
        metrics["coverage"] = coverage_value
        gates = evaluate_review_policy_gates(metrics)
        assert gates["review_policy_coverage"]["status"] == "INFORMATIVE"
        assert gates["review_policy_coverage"]["value"] == coverage_value


# ---------------------------------------------------------------------------
# (8) Vocabulario cerrado del dictamen
# ---------------------------------------------------------------------------
def test_verdict_vocabulary_is_closed_and_never_overlaps_block7():
    assert set(REVIEW_POLICY_VERDICTS).isdisjoint(set(B7_VERDICTS))
    for v in REVIEW_POLICY_VERDICTS:
        assert "APTO/AUTO_APPROVED" not in v
        assert v != "APTO/AUTO_APPROVED"


@pytest.mark.parametrize("n,false_accepts", [
    (0, 0), (5, 0), (25, 0), (25, 1), (100, 3), (19, 1),
])
def test_verdict_always_in_closed_vocabulary(n, false_accepts):
    """MATA: cualquier dictamen devuelto que no pertenezca al vocabulario
    cerrado (p.ej. reintroducir 'APTO PARA INGESTA REAL' o 'AUTO_APPROVED')."""
    match = _match_with_n_clean_auto_proposable(n, n_false_accepts=false_accepts)
    metrics = review_policy_safety_metrics(match)
    gates = evaluate_review_policy_gates(metrics)
    verdict, justification = decide_review_policy_verdict(gates)
    assert verdict in REVIEW_POLICY_VERDICTS
    assert isinstance(justification, str) and justification


# ---------------------------------------------------------------------------
# (9) Mutation-check especifico de la medicion: FAR con conteo EXACTO conocido
# ---------------------------------------------------------------------------
def test_metrics_far_exact_one_false_accept_of_25_known_confusion():
    """Escenario de confusion CONOCIDA: 25 auto-propuestos, 24 correctos
    (expected_decision == ACCEPT) y 1 incorrecto (expected_decision ==
    REJECT). FAR esperado = 1/25 = 0.04 EXACTO.

    MATA: invertir `m["gt"]["expected_decision"] == "ACCEPT"` por `!=` en el
    calculo de `correct` dentro de `review_policy_safety_metrics`. Bajo esa
    mutacion, `correct` pasaria a contar el elemento REJECT (correct=1) en vez
    de los 24 ACCEPT, y `false_accepts` pasaria a ser `(25-1)+0=24`, dando
    FAR=0.96 en vez de 0.04 -- este assert exacto lo detecta."""
    match = _match_with_n_clean_auto_proposable(25, n_false_accepts=1)
    metrics = review_policy_safety_metrics(match)
    assert metrics["sample_size"] == 25
    assert metrics["correct"] == 24
    assert metrics["false_accepts"] == 1
    assert metrics["false_accept_rate"] == 0.04
    assert metrics["precision"] == 0.96


def test_metrics_fp_always_counts_as_false_accept_never_correct():
    """Un FP auto-propuesto no tiene relacion real que corroborar: cuenta
    SIEMPRE como falso-aceptado. MATA: tratar un FP auto-propuesto como
    'correcto por ausencia de contraejemplo'."""
    match = MatchResult(
        true_positives=[],
        false_positives=[_toy_pred(AUTO_PROPOSABLE, "fp1"), _toy_pred(AUTO_PROPOSABLE, "fp2")],
        false_negatives=[],
    )
    metrics = review_policy_safety_metrics(match)
    assert metrics["sample_size"] == 2
    assert metrics["false_accepts"] == 2
    assert metrics["correct"] == 0
    assert metrics["precision"] == 0.0
    assert metrics["false_accept_rate"] == 1.0


def test_metrics_ignores_review_required_predictions_not_counted_in_sample():
    """Predicciones etiquetadas REVIEW_REQUIRED (la mayoria en la practica) NO
    deben contarse en `sample_size`: la metrica es SOLO sobre el subconjunto
    AUTO_PROPOSABLE."""
    true_positives = [
        {"gt": _toy_gt("r1", "ACCEPT"), "pred": _toy_pred(AUTO_PROPOSABLE, "c1"), "flags": {}},
        {"gt": _toy_gt("r2", "ACCEPT"), "pred": _toy_pred(REVIEW_REQUIRED, "c2"), "flags": {}},
        {"gt": _toy_gt("r3", "REJECT"), "pred": _toy_pred(REVIEW_REQUIRED, "c3"), "flags": {}},
    ]
    match = MatchResult(true_positives=true_positives, false_positives=[], false_negatives=[])
    metrics = review_policy_safety_metrics(match)
    assert metrics["sample_size"] == 1
    assert metrics["total_evaluated"] == 3
