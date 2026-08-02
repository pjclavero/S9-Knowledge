# -*- coding: utf-8 -*-
"""Arnes unificado de la puerta 4 (B0): mide dev y generalizacion a la par.

Dos corpus, dos profundidades de medicion, publicadas UNA AL LADO DE LA OTRA
y nunca mezcladas en un solo numero:

* **Desarrollo** (`negation`, split congelado): se mide con la cadena
  COMPLETA -- normalizador, extractores, motor, resolutor, writer en
  DRY-RUN -- reutilizando tal cual
  `artifacts/v3-final-validation/gate4_negation_measure.py` (no se copia ni se
  reimplementa: se importa). Es la corrida E2E ya existente y congelada.
* **Generalizacion** (corpus nuevo de B0): se mide a nivel de CLASIFICADOR de
  negacion (`extraction.cues.analyze_raw_text`), la misma funcion que invoca
  el extractor determinista para decidir tipo y alcance de una negacion. No
  se corre la cadena completa porque eso exigiria fabricar a mano episodios,
  menciones, resoluciones y planes con forma de contrato para 42 casos
  nuevos -- justo el trabajo de autoria propenso a sesgo que este arnes existe
  para no premiar. Medir el clasificador de verdad sobre texto nunca visto
  es mas barato, mas dificil de trucar sin querer, y answers exactamente la
  pregunta de generalizacion que motiva el bloque: ¿la logica de `cues.py`
  reconoce las mismas familias de negacion fuera de sus frases de siempre?

Esta asimetria de profundidad es una LIMITACION DECLARADA, no un defecto
escondido: `to_markdown` la dice en la cabecera del informe cada vez.
"""
from __future__ import annotations

from typing import Any

from ..extraction.cues import analyze_raw_text
from . import _frozen_runner
from .dev_corpus import load_dev_gold
from .generalization_corpus import GeneralizationItem, load_generalization

#: Clases de factividad que SI representan un hecho del mundo. Copiado del
#: mismo criterio que usa la sonda hermana
#: `artifacts/v3-final-validation/factivity_generalization_probe.py`
#: (`FACT_CLASSES`): no se reinventa el criterio, se reutiliza.
FACT_CLASSES = {"ASSERTED_FACT", "NEGATED_FACT"}

#: Familias cuya lectura correcta es "queda marcado para revision, sin
#: resolver la negacion por su cuenta" -- alcance ambiguo o doble negacion.
_REVIEW_FAMILIES = {"NEGATED_CESSATION", "SCOPE_EMBEDDED", "DOUBLE_NEGATION"}
#: Familias cuya lectura correcta es "no es un hecho del mundo, es supuesto,
#: preguntado o rumoreado" -- se juzgan por factividad, no por negacion.
_NON_FACTIVE_FAMILIES = {"QUESTION_CONDITIONAL_RUMOR"}
#: Familias de negacion MECANICA: negado/tipo deben coincidir literalmente.
_MECHANICAL_FAMILIES = {"SIMPLE", "NEVER", "CESSATION", "NOT_YET"}
#: Familia "dura" (revision post-CONFORME-CON-OBSERVACIONES): construcciones
#: de negacion espanola FUERA del vocabulario de `cues.py` (subordinada
#: exceptiva "sin que", litotes correctiva "no es que no...", cesacion
#: perifrastica "ha dejado atras", litotes cuantitativa "no pocos"). Se
#: exige que la lectura correcta se resuelva como hecho confiado
#: (`expected_asserted_fact`), no solo que la polaridad de `negated` cuadre
#: por casualidad -- ver `_score_item`. Exactitud baja aqui es el punto: es
#: el liston que B2 (reglas) y B4 (carril semantico) tienen que subir.
_HARD_FAMILIES = {"HARD_SCOPE_LITOTES"}

# --------------------------------------------------------------------------
# 1. Desarrollo: reutiliza la corrida E2E ya existente
# --------------------------------------------------------------------------
def measure_dev() -> dict[str, Any]:
    """Corre la medicion E2E congelada sobre la bateria de negaciones.

    Antes de correrla se verifica la integridad del corpus (ver
    `dev_corpus.verify_integrity`): si alguien edito el gold sin declarar el
    cambio en su manifiesto, esto rompe ANTES de producir un numero. El
    runner se reutiliza tal cual, cargado por ruta (`_frozen_runner`); no se
    copia ni se modifica una linea suya.
    """
    load_dev_gold(verify=True)  # solo para la comprobacion de integridad
    runner = _frozen_runner.load()
    report = runner.measure()
    return {
        "split": _frozen_runner.dev_split_name(),
        "layer": "pipeline_e2e",
        "coverage": report["corpus"]["coverage"],
        "evaluable_cases": report["corpus"]["evaluable_cases"],
        "covered_cases": report["corpus"]["covered_cases"],
        "metrics_global": report["metrics_global"],
        "metrics_by_family": {
            fam: {k: v for k, v in vals.items() if k not in ("cases", "covered")}
            for fam, vals in report["metrics_by_family"].items()
            if fam != "NO_CLAIM"
        },
        "families_cases": {
            fam: vals["cases"]
            for fam, vals in report["metrics_by_family"].items()
            if fam != "NO_CLAIM"
        },
        "gates": [
            {"name": g["name"], "observed": g["observed"], "status": g["status"]}
            for g in report["gates"]
        ],
    }


# --------------------------------------------------------------------------
# 2. Generalizacion: mide el clasificador de negacion directamente
# --------------------------------------------------------------------------
def _score_item(item: GeneralizationItem) -> dict[str, Any]:
    # `focus_char` tiene que apuntar al INICIO DEL OBJETO de la afirmacion
    # (nunca al negador ni al verbo): es el mismo contrato que usa
    # `classify_negation`/`analyze_context` (`focus` = donde empieza lo
    # afirmado; la negacion se busca ANTES de ese punto). Un item con el
    # ancla mal puesta (ver `generalization_corpus.GeneralizationItem` y su
    # docstring de modulo) no lanza ningun error aqui: `analyze_raw_text`
    # devuelve un veredicto igual de valido en forma pero que mide otra
    # ventana de texto, y el numero que sale de el es basura silenciosa, no
    # una excepcion. La responsabilidad de poner el ancla bien es de quien
    # escribe el caso, no de este cargador.
    verdict = analyze_raw_text(item.text, focus_char=item.focus_char)
    predicted_negated = bool(verdict.negated)
    predicted_kind = verdict.negation_kind or ""
    read_as_fact = verdict.factivity.factivity_class.value in FACT_CLASSES

    evidence_grounded = item.subject in item.text and item.object in item.text

    if item.family in _HARD_FAMILIES:
        # Aqui NO basta con que `negated` coincida por casualidad (ver
        # `gen:hard:02`, donde el clasificador da `negated=False` "bien" pero
        # por abstenerse -- SCOPE_AMBIGUOUS/UNKNOWN -- no por resolver la
        # litotes): se exige ademas que la clase de factividad resuelva un
        # hecho confiado (`ASSERTED_FACT`/`NEGATED_FACT`) cuando el gold dice
        # que deberia hacerlo.
        correct = predicted_negated == item.negated and (
            item.expected_asserted_fact is None
            or read_as_fact == item.expected_asserted_fact
        )
    elif item.family in _REVIEW_FAMILIES:
        correct = predicted_kind == "SCOPE_AMBIGUOUS"
    elif item.family in _NON_FACTIVE_FAMILIES:
        correct = read_as_fact is False
    elif item.family == "POSITIVE_CONTROL":
        correct = (not predicted_negated) and read_as_fact is True
    else:
        assert item.family in _MECHANICAL_FAMILIES, f"familia sin regla: {item.family}"
        correct = predicted_negated == item.negated and predicted_kind == item.negation_kind

    return {
        "case_id": item.case_id,
        "family": item.family,
        "domain": item.domain,
        "covered": True,  # el clasificador siempre responde; ver nota en el modulo
        "expected_negated": item.negated,
        "predicted_negated": predicted_negated,
        "expected_negation_kind": item.negation_kind,
        "predicted_negation_kind": predicted_kind,
        "expected_review_scope": item.review_scope,
        "predicted_review_scope": predicted_kind == "SCOPE_AMBIGUOUS",
        "read_as_world_fact": read_as_fact,
        "evidence_grounded": evidence_grounded,
        "correct": correct,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def measure_generalization() -> dict[str, Any]:
    """Mide el clasificador de negacion sobre el corpus de generalizacion.

    Verifica integridad primero (mismo criterio que `measure_dev`), igual de
    exigente con un corpus nuevo que con uno viejo: la disciplina anti-deriva
    no distingue antiguedad.
    """
    items = load_generalization(verify=True)
    rows = [_score_item(item) for item in items]

    coverage = _ratio(sum(1 for r in rows if r["covered"]), len(rows))

    simple_rows = [r for r in rows if r["family"] == "SIMPLE"]
    recall_simple = _ratio(sum(1 for r in simple_rows if r["correct"]), len(simple_rows))

    mechanical_rows = [r for r in rows if r["family"] in _MECHANICAL_FAMILIES]
    precision_mechanical = _ratio(
        sum(1 for r in mechanical_rows if r["correct"]), len(mechanical_rows)
    )

    scope_rows = [r for r in rows if r["family"] in _REVIEW_FAMILIES]
    scope_accuracy = _ratio(sum(1 for r in scope_rows if r["correct"]), len(scope_rows))

    non_factive_rows = [
        r for r in rows if r["family"] in _NON_FACTIVE_FAMILIES | {"POSITIVE_CONTROL"}
    ]
    non_factive_accuracy = _ratio(
        sum(1 for r in non_factive_rows if r["correct"]), len(non_factive_rows)
    )

    evidence_grounding = _ratio(sum(1 for r in rows if r["evidence_grounded"]), len(rows))

    hard_rows = [r for r in rows if r["family"] in _HARD_FAMILIES]
    hard_scope_litotes_accuracy = _ratio(sum(1 for r in hard_rows if r["correct"]), len(hard_rows))

    overall_accuracy = _ratio(sum(1 for r in rows if r["correct"]), len(rows))

    by_family: dict[str, Any] = {}
    for family in sorted({r["family"] for r in rows}):
        subset = [r for r in rows if r["family"] == family]
        by_family[family] = {
            "cases": len(subset),
            "accuracy": _ratio(sum(1 for r in subset if r["correct"]), len(subset)),
        }

    return {
        "split": "generalization",
        "layer": "negation_classifier",
        "coverage": coverage,
        "evaluable_cases": len(rows),
        "covered_cases": sum(1 for r in rows if r["covered"]),
        "metrics_global": {
            "auto_approval_recall": None,  # no aplica: no hay motor ni politica aqui
            "negation_scope_accuracy": scope_accuracy,
            "evidence_grounding": evidence_grounding,
            "negative_edge_precision": precision_mechanical,
            "recall_simple": recall_simple,
            "non_factive_accuracy": non_factive_accuracy,
            "hard_scope_litotes_accuracy": hard_scope_litotes_accuracy,
            "overall_accuracy": overall_accuracy,
        },
        "metrics_by_family": by_family,
        "rows": rows,
    }


# --------------------------------------------------------------------------
# 3. Arnes unificado
# --------------------------------------------------------------------------
def measure_gate4_program() -> dict[str, Any]:
    """Las dos corridas, lado a lado, con la misma disciplina de integridad.

    Determinista: ninguna de las dos corridas usa fecha del sistema, orden de
    diccionario inestable ni aleatoriedad. Dos ejecuciones seguidas producen
    el mismo JSON byte a byte (lo comprueba
    `tests/test_gate4_harness.py::test_determinismo`).
    """
    dev = measure_dev()
    generalization = measure_generalization()
    return {
        "gate": "4",
        "block": "B0",
        "purpose": (
            "Arnes de medicion anti-sobreajuste: publica cobertura y precision "
            "de desarrollo y de generalizacion lado a lado, sin mezclarlas en un "
            "solo numero. Ninguna mejora futura del extractor se acepta si solo "
            "sube el numero de desarrollo."
        ),
        "corpora": {"dev": dev, "generalization": generalization},
        "notes": [
            "El corpus de desarrollo se mide con la cadena COMPLETA (pipeline "
            "E2E, ablacion local_only, writer en DRY-RUN); el de generalizacion "
            "se mide a nivel del CLASIFICADOR de negacion "
            "(`extraction.cues.analyze_raw_text`), la misma funcion que invoca "
            "el extractor determinista. Es una diferencia de profundidad "
            "DECLARADA: construir fixtures de contrato completos para 42 casos "
            "nuevos es el trabajo de autoria propenso a sesgo que este arnes "
            "existe para no premiar.",
            "Por eso `coverage` no es comparable entre los dos corpus: en "
            "desarrollo mide si la cadena entera llego a proponer una decision "
            "(baja, por diseno: ablacion sin proveedores); en generalizacion mide "
            "si el clasificador de negacion respondio (siempre responde, por "
            "construccion). Lo comparable son las metricas de PRECISION Y "
            "ALCANCE dentro de cada capa.",
            "El numero honesto de este bloque es el de generalizacion: si baja "
            "mucho respecto al de desarrollo en una familia dada, esa familia "
            "esta memorizada, no entendida, exactamente como le paso al motor "
            "de relaciones v2 (predicado 0.81 en dev==test, 0.24 en real).",
            "IMPORTANTE (tras revision CONFORME CON OBSERVACIONES): la exactitud "
            "1.0 de las 9 familias originales de generalizacion significa "
            "'el clasificador de negacion generaliza a ESTAS 9 FAMILIAS "
            "CONCRETAS con entidades nuevas', NO 'el clasificador generaliza a "
            "la negacion espanola'. La bateria adversarial del agente de tests "
            "(`tests/test_gate4_harness_adversarial.py::"
            "test_documenta_fallos_del_clasificador_en_frases_nuevas_fuera_de_corpus`) "
            "prueba 8 frases nuevas fuera de ambos corpus y encuentra 4 fallos: "
            "subordinada exceptiva 'sin que', litotes correctiva 'no es que "
            "no...', cesacion perifrastica 'ha dejado atras' y litotes "
            "cuantitativa 'no pocos' -- los mismos cuatro fenomenos que ahora "
            "mide, con casos propios, la familia `HARD_SCOPE_LITOTES` de este "
            "corpus (ver mas abajo).",
            "La familia `HARD_SCOPE_LITOTES` (4 casos, dominio 'archivos', "
            "entidades nuevas que no repiten ninguna frase de la bateria "
            "adversarial) publica la exactitud de esas cuatro construcciones "
            "duras POR SEPARADO (`metrics_global.hard_scope_litotes_accuracy` "
            "y la fila `HARD_SCOPE_LITOTES` de la tabla por familia). Se espera "
            "BAJA -- es el liston que B2 (reglas) y B4 (carril semantico) "
            "tienen que subir, no un defecto de este arnes.",
            "LIMITACION CONOCIDA (TODO, ver tambien "
            "`tests/test_gate4_harness.py::"
            "test_ningun_nombre_propio_de_desarrollo_aparece_en_los_textos_de_generalizacion`): "
            "el detector de no-solapamiento inverso (nombres de desarrollo "
            "dentro de los textos de generalizacion) ignora nombres propios de "
            "menos de 6 caracteres para evitar falsos positivos por coincidir "
            "con una silaba de otra palabra. Un nombre corto de desarrollo "
            "reutilizado en generalizacion NO seria atrapado por este chequeo "
            "concreto (si lo atraparia el chequeo directo por entidad, que "
            "compara nombres completos sin umbral). Pendiente: sustituir el "
            "umbral de longitud por una lista explicita de palabras vacias.",
        ],
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    dev = report["corpora"]["dev"]
    gen = report["corpora"]["generalization"]

    add("# Puerta 4 — B0: arnes de medicion (desarrollo vs. generalizacion)")
    add("")
    add(report["purpose"])
    add("")
    add("## 1. Cobertura")
    add("")
    add("| corpus | capa | casos evaluables | cubiertos | cobertura |")
    add("| --- | --- | ---: | ---: | ---: |")
    for corpus in (dev, gen):
        cov = corpus["coverage"]
        add(
            f"| {corpus['split']} | {corpus['layer']} | {corpus['evaluable_cases']} | "
            f"{corpus['covered_cases']} | {'n/d' if cov is None else f'{cov:.3f}'} |"
        )
    add("")
    add("## 2. Metricas globales, lado a lado")
    add("")
    keys = sorted(set(dev["metrics_global"]) | set(gen["metrics_global"]))
    add("| metrica | desarrollo (E2E) | generalizacion (clasificador) |")
    add("| --- | ---: | ---: |")
    for key in keys:
        dv = dev["metrics_global"].get(key)
        gv = gen["metrics_global"].get(key)
        fmt = lambda v: "n/d" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
        add(f"| `{key}` | {fmt(dv)} | {fmt(gv)} |")
    add("")
    add("## 3. Generalizacion por familia")
    add("")
    add("| familia | casos | exactitud |")
    add("| --- | ---: | ---: |")
    for family, vals in gen["metrics_by_family"].items():
        acc = vals["accuracy"]
        add(f"| {family} | {vals['cases']} | {'n/d' if acc is None else f'{acc:.3f}'} |")
    add("")
    add("## 4. Puertas de desarrollo (heredadas del runner E2E)")
    add("")
    add("| puerta | observado | veredicto |")
    add("| --- | ---: | --- |")
    for gate in dev["gates"]:
        add(f"| {gate['name']} | {gate['observed']} | **{gate['status']}** |")
    add("")
    add("## 5. Hallazgos")
    add("")
    for note in report["notes"]:
        add(f"- {note}")
    add("")
    return "\n".join(lines)


__all__ = [
    "measure_dev",
    "measure_gate4_program",
    "measure_generalization",
    "to_markdown",
]
