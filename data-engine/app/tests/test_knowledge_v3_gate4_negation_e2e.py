# -*- coding: utf-8 -*-
"""PUERTA 4 — negaciones extremo a extremo en sombra: defensa del resultado.

Este fichero NO mide. La medicion vive fuera del arbol de codigo, en
`artifacts/v3-final-validation/gate4_negation_measure.py`, y por una razon dura:
la bateria de negaciones es GOLD, y el repo tiene un guardian
(`test_knowledge_v3_negation_battery.py::
test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico`) que prohibe que
nada bajo `data-engine/`, `scripts/`, `deploy/`, `shared/` o `tests/` la cargue
o la puntue. Aqui solo se hacen dos cosas:

1. **Defender el artefacto publicado.** Que declare la configuracion que dice
   medir, que sus diez metricas esten, que cada veredicto de puerta se pueda
   recalcular a partir del numero observado (un CONFORME escrito a mano no
   sobrevive), y que los invariantes de SEGURIDAD que la corrida demostro sigan
   demostrados.
2. **Defender el codigo que produjo esos numeros**, con casos sinteticos: si la
   aritmetica de la medicion se rompe, el informe miente aunque el sistema este
   bien.

Las dos puertas que la corrida SUSPENDE estan aqui como `xfail(strict=True)`.
No se relaja el umbral ni se toca el corpus para que salgan verdes: el fallo es
real y se deja escrito como fallo. Si algun dia dejan de fallar, `strict` obliga
a venir aqui y quitarlas.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO / "artifacts" / "v3-final-validation"
MEASURE = ARTIFACT_DIR / "gate4_negation_measure.py"
REPORT_JSON = ARTIFACT_DIR / "gate4-negation-metrics.json"
REPORT_MD = ARTIFACT_DIR / "gate4-negation-metrics.md"

#: Las diez metricas que la puerta 4 tiene que publicar. La lista vive aqui a
#: mano: si el medidor deja de publicar una, el que falla es el medidor.
TEN = (
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
    "NO_CLAIM",
)


# --------------------------------------------------------------------------
# Utillaje: el artefacto y el modulo de medicion
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def report() -> dict:
    """El informe publicado. Si no existe, se genera ejecutando el medidor."""
    if not REPORT_JSON.exists():  # pragma: no cover - solo en un arbol limpio
        subprocess.run(
            [sys.executable, str(MEASURE), "--out-dir", str(ARTIFACT_DIR)],
            cwd=str(REPO),
            env={"PYTHONPATH": str(REPO / "data-engine" / "app"), "PATH": "/usr/bin:/bin"},
            check=True,
            timeout=900,
        )
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def measure_module():
    """El medidor, importado por ruta: no vive en el arbol de paquetes."""
    spec = importlib.util.spec_from_file_location("gate4_negation_measure", MEASURE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# 1. El artefacto dice lo que dice medir
# --------------------------------------------------------------------------
def test_el_artefacto_existe_en_sus_dos_formatos():
    assert REPORT_JSON.exists(), "falta el JSON de la puerta 4"
    assert REPORT_MD.exists(), "falta el informe legible de la puerta 4"


def test_declara_las_tres_banderas_que_la_puerta_exige(report):
    config = report["config"]
    assert config["semantic_shadow_evaluation"] is True
    assert config["graduated_negation_policy"] is True
    assert config["graduated_temporal_policy"] is True


def test_ningun_proveedor_real_participo_en_la_medicion(report):
    """Ollama y el carril externo estaban reservados: no podian encenderse."""
    config = report["config"]
    assert config["ollama_active"] is False
    assert config["external_active"] is False
    assert config["providers"] == "local_only"


def test_el_writer_nunca_salio_de_dry_run(report):
    assert report["config"]["writer_mode"] == "DRY_RUN"
    assert report["writer"]["mode"] == "DRY_RUN"
    assert set(report["writer"]["outcomes"]) <= {"SIMULATED"}, (
        "un plan se ejecuto de verdad: la puerta 4 no toca Neo4j"
    )


def test_publica_las_diez_metricas(report):
    assert set(report["metrics_global"]) == set(TEN)


def test_publica_las_diez_metricas_por_familia(report):
    families = report["metrics_by_family"]
    assert set(families) == set(FAMILIES)
    for family, values in families.items():
        if family == "NO_CLAIM":
            continue
        assert set(TEN) <= set(values), f"{family} no publica las diez"


def test_el_corpus_declarado_cuadra_con_lo_que_se_midio(report):
    corpus = report["corpus"]
    assert corpus["evaluable_cases"] == len(report["cases"])
    assert corpus["covered_cases"] == sum(1 for c in report["cases"] if c["covered"])
    assert 0 < corpus["covered_cases"] <= corpus["evaluable_cases"]
    assert sum(
        values["cases"] for family, values in report["metrics_by_family"].items()
        if family != "NO_CLAIM"
    ) == corpus["evaluable_cases"]


# --------------------------------------------------------------------------
# 2. Los veredictos no estan escritos a mano
# --------------------------------------------------------------------------
def _recompute(observed, threshold) -> str:
    if observed is None:
        return "NO_EVALUABLE"
    if isinstance(threshold, int) and not isinstance(threshold, bool):
        return "CONFORME" if observed == threshold else "NO_CONFORME"
    if threshold == 1.0:
        return "CONFORME" if observed == threshold else "NO_CONFORME"
    return "CONFORME" if observed >= threshold else "NO_CONFORME"


def test_cada_veredicto_se_recalcula_a_partir_de_su_numero(report):
    """Un CONFORME solo vale si el numero observado lo sostiene."""
    assert report["gates"], "la puerta 4 no publica ninguna puerta"
    for gate in report["gates"]:
        assert gate["status"] == _recompute(gate["observed"], gate["threshold"]), gate


def test_una_puerta_sin_denominador_no_se_declara_conforme(report):
    for gate in report["gates"]:
        if gate.get("denominator") == 0 and gate["observed"] is None:
            assert gate["status"] == "NO_EVALUABLE", (
                f"{gate['name']} se declara conforme sin poblacion que lo sostenga"
            )


def test_las_puertas_observadas_coinciden_con_las_metricas_publicadas(report):
    metrics = report["metrics_global"]
    for gate in report["gates"]:
        if gate["metric"] in metrics:
            assert gate["observed"] == metrics[gate["metric"]], gate["name"]


# --------------------------------------------------------------------------
# 3. Los invariantes de SEGURIDAD que la corrida demostro
# --------------------------------------------------------------------------
def test_cero_aristas_positivas_nacidas_de_una_negacion(report):
    assert report["metrics_global"]["false_positive_relation_from_negation"] == 0


def test_ninguna_operacion_positiva_sobre_una_relacion_negada_por_el_gold(report):
    corpus_wide = report["positive_edges_over_negated_keys"]
    assert corpus_wide["gold_negated_keys"] > 0, "sin claves negadas no hay nada que probar"
    assert corpus_wide["offending_operations"] == []


def test_ninguna_cesacion_falsa_desde_un_no_dejo_de(report):
    assert report["metrics_global"]["negated_cessation_safety"] == 1.0


def test_toda_decision_emitida_va_anclada_a_su_evidencia(report):
    assert report["metrics_global"]["evidence_grounding"] == 1.0
    for case in report["cases"]:
        if case["covered"]:
            assert case["evidence_anchored"], case["case_id"]


def test_ninguna_decision_negativa_proyecta_relacion(report):
    """Un hecho negado no proyecta arista, ni aunque se autoapruebe."""
    for case in report["cases"]:
        if case["predicted_negated"]:
            assert "PROJECT_RELATION" not in case["positive_operations"], case["case_id"]


def test_la_sombra_no_emitiria_operaciones(report):
    shadow = report["shadow"]
    assert shadow["enabled"] is True
    assert shadow["records_that_would_emit_operations"] == 0


def test_la_sombra_declara_su_cobertura_cero_en_vez_de_presumir(report):
    """0 registros no es 'sombra correcta', y el informe tiene que decirlo."""
    assert report["shadow"]["records"] == 0
    assert any("sombra" in note.lower() for note in report["notes"])


# --------------------------------------------------------------------------
# 4. Lo que SUSPENDE, escrito como suspenso
# --------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "SUSPENSO REAL. Alcance global 0.875 < 0.95 sobre los casos cubiertos. El unico "
        "fallo medido es NEG-SIMPLE-01: 'Harun Vell no pertenece a la Orden de la "
        "Obsidiana', precedido de una subordinada larga con una tercera entidad (Puerto "
        "Escoria), donde el extractor determinista propone claim pero ABSTIENE con "
        "PREDICATE_ABSENT y pierde la negacion. La misma construccion sin tercera "
        "entidad (NEG-SIMPLE-09) si se resuelve. No se toca el umbral ni el corpus."
    ),
)
def test_alcance_global_alcanza_el_umbral(report):
    assert report["metrics_global"]["negation_scope_accuracy"] >= 0.95


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SUSPENSO REAL. Recall de autoaprobacion SIMPLE 0.1 < 0.75. Con extraccion "
        "determinista (unica permitida: los proveedores estaban reservados) la cadena "
        "solo ve 2 de los 11 casos SIMPLE y solo autoaprueba 1. Es un techo de "
        "COBERTURA del extractor, no un fallo de la politica graduada, y no se arregla "
        "bajando el umbral."
    ),
)
def test_recall_de_autoaprobacion_simple_alcanza_el_umbral(report):
    assert report["metrics_by_family"]["SIMPLE"]["auto_approval_recall"] >= 0.75


# GATE4-03 CORREGIDO: `speaker`, `turn` y `table` no estan en `required` del
# JSON Schema congelado, pero el dataclass los declaraba sin default y
# `from_dict` los exigia. Ahora llevan default=None. El `xfail(strict=True)`
# se retira junto con su entrada de `.github/xfail-registro.txt`: dejarla
# pondria el gate en rojo por la segunda direccion (entrada sin xfail).
def test_un_episodio_sin_las_claves_opcionales_deberia_cargar():
    from knowledge_v3.contracts.episode import SourceEpisode

    documento = {
        "contract_id": "source-episode/v3-internal-v1",
        "contract_version": "1.0.0",
        "workspace": "bench-gate4",
        "episode_id": "episode:gate4:e01",
        "asset_id": "asset:gate4",
        "source_asset_id": "asset:gate4",
        "source_hash": {"algorithm": "sha256", "value": "0" * 64},
        "content_hash": {"algorithm": "sha256", "value": "1" * 64},
        "provider_trace": [
            {
                "step": "gold.segment",
                "provider": "local",
                "name": "s9k.gate4",
                "version": "1.0.0",
                "model": None,
                "produced": ["text"],
            }
        ],
        "produced_by_step": "gold.segment",
        "modality": "TEXT",
        "sequence": 1,
        "text": "Un episodio sin speaker, sin turn y sin table.",
        "quality": {"score": 0.9, "flags": []},
        "metadata": {},
        "bbox": None,
        "page": None,
        "time_start": None,
        "time_end": None,
        "previous_episode_id": None,
        "next_episode_id": None,
    }
    assert SourceEpisode.from_dict(documento).episode_id == "episode:gate4:e01"


# --------------------------------------------------------------------------
# 5. La aritmetica de la medicion, con casos sinteticos
# --------------------------------------------------------------------------
def _row(**overrides) -> dict:
    base = {
        "case_id": "SINTETICO",
        "family": "SIMPLE",
        "expected_negated": True,
        "expected_decision": "AUTO_APPROVE",
        "expected_negation_kind": "SIMPLE",
        "expected_scope": "UNAMBIGUOUS",
        "covered": True,
        "predicted_negated": True,
        "predicted_negation_kind": "SIMPLE",
        "predicted_decision": "ACCEPT",
        "predicted_subject": "entity:a",
        "predicted_object": "entity:b",
        "predicted_predicate": "MEMBER_OF",
        "predicted_supersedes": None,
        "evidence_anchored": True,
        "positive_operations": [],
        "emitted_positive_edge": False,
        "scope_correct": True,
    }
    base.update(overrides)
    return base


def test_un_caso_no_cubierto_no_infla_la_precision(measure_module):
    """La precision se lee sobre lo emitido; el recall, sobre el gold entero."""
    rows = [_row()] + [
        _row(
            case_id=f"NO-VISTO-{i}",
            covered=False,
            predicted_negated=False,
            predicted_negation_kind="",
            predicted_decision="NO_OUTPUT",
            evidence_anchored=False,
            scope_correct=False,
        )
        for i in range(9)
    ]
    metrics = measure_module.ten_metrics(rows)
    assert metrics["negative_edge_precision"]["value"] == 1.0
    assert metrics["negative_edge_recall"]["value"] == 0.1
    assert metrics["evidence_grounding"]["value"] == 1.0
    assert metrics["_coverage"]["accuracy"] == 0.1


def test_una_arista_positiva_sobre_un_caso_negado_se_cuenta(measure_module):
    rows = [
        _row(
            predicted_negated=False,
            predicted_negation_kind="",
            positive_operations=["PROJECT_RELATION"],
            emitted_positive_edge=True,
            scope_correct=False,
        )
    ]
    metrics = measure_module.ten_metrics(rows)
    assert metrics["false_positive_relation_from_negation"]["value"] == 1


def test_una_cesacion_falsa_desde_no_dejo_de_hunde_la_seguridad(measure_module):
    rows = [
        _row(
            family="NEGATED_CESSATION",
            expected_negated=False,
            expected_negation_kind="NEGATED_CESSATION",
            predicted_negation_kind="CESSATION",
            predicted_decision="REVIEW",
        )
    ]
    metrics = measure_module.ten_metrics(rows)
    assert metrics["negated_cessation_safety"]["value"] == 0.0


def test_el_alcance_falla_si_se_niega_la_relacion_equivocada(measure_module):
    annotation = {
        "expected_negated": True,
        "expected_decision": "AUTO_APPROVE",
        "expected_subject": "entity:a",
        "expected_object": "entity:b",
        "expected_predicate": "MEMBER_OF",
    }
    correcta = measure_module._scope_correct(annotation, _row())
    equivocada = measure_module._scope_correct(
        annotation, _row(predicted_object="entity:otro")
    )
    assert correcta is True
    assert equivocada is False


def test_el_alcance_falla_si_se_acepta_lo_que_el_gold_manda_a_revision(measure_module):
    annotation = {
        "expected_negated": True,
        "expected_decision": "REVIEW_NEGATION_SCOPE",
        "expected_subject": "entity:a",
        "expected_object": "entity:b",
        "expected_predicate": "MEMBER_OF",
    }
    assert measure_module._scope_correct(annotation, _row(predicted_decision="REVIEW")) is True
    assert measure_module._scope_correct(annotation, _row(predicted_decision="ACCEPT")) is False


def test_un_caso_sin_salida_nunca_cuenta_como_alcance_correcto(measure_module):
    annotation = {
        "expected_negated": False,
        "expected_decision": "AUTO_APPROVE",
    }
    row = _row(covered=False, predicted_negated=False, predicted_decision="NO_OUTPUT")
    assert measure_module._scope_correct(annotation, row) is False


def test_las_puertas_suspenden_cuando_el_numero_no_llega(measure_module):
    """La funcion de puertas no puede aprobar por debajo del umbral."""
    rows = [_row(scope_correct=False, predicted_decision="REVIEW")]
    metrics = measure_module.ten_metrics(rows)
    families = measure_module.by_family(rows)
    corpus_wide = {"gold_negated_keys": 1, "offending_operations": [], "count": 0}
    veredictos = {g["metric"]: g for g in measure_module.gates(metrics, families, corpus_wide)}
    assert veredictos["negation_scope_accuracy"]["status"] == "NO_CONFORME"
    assert veredictos["auto_approval_recall[SIMPLE]"]["status"] == "NO_CONFORME"
    assert veredictos["positive_edges_over_negated_keys"]["status"] == "CONFORME"


def test_las_operaciones_positivas_se_detectan_por_su_tipo_y_su_payload(measure_module):
    class FakePlan:
        def __init__(self, operations):
            self._operations = operations

        def to_dict(self):
            return {"mutation_operations": self._operations}

    class FakeResult:
        plans = [
            FakePlan(
                [
                    {
                        "operation_id": "op:claim:uno:assert",
                        "operation_type": "CREATE_ASSERTION",
                        "payload": {"negated": True},
                    },
                    {
                        "operation_id": "op:claim:dos:assert",
                        "operation_type": "CREATE_ASSERTION",
                        "payload": {"negated": False},
                    },
                    {
                        "operation_id": "op:claim:dos:project",
                        "operation_type": "PROJECT_RELATION",
                        "payload": {"negated": False},
                    },
                    {
                        "operation_id": "op:claim:tres:supersede",
                        "operation_type": "SUPERSEDE_ASSERTION",
                        "payload": {},
                    },
                ]
            )
        ]

    positivas = measure_module._positive_operations(FakeResult())
    assert "claim:uno" not in positivas
    assert positivas["claim:dos"] == ["CREATE_ASSERTION", "PROJECT_RELATION"]
    assert "claim:tres" not in positivas
