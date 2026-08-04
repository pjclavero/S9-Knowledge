# -*- coding: utf-8 -*-
"""Bateria adversarial / anti-enchufe del arnes de la puerta 6 (B0).

Mismo espiritu que `test_gate4_harness_adversarial.py`: no repite lo que ya
cubre `test_gate6_harness.py` (integridad basica, no-solapamiento,
determinismo, esquema). Busca romper el arnes por vias que un implementador
apurado podria dejar abiertas:

1. Que nadie pueda apuntar el runner a otro split/corpus sin que un test lo
   detecte (el "anti-enchufe" propiamente dicho): las rutas de los corpus
   estan fijadas por modulo, no por argumento de linea de comandos, y ese
   hecho esta comprobado aqui.
2. Que la corrupcion deliberada del gold (invertir `expected_class`, vaciar
   el corpus, un `family` fuera del catalogo) rompe la carga o cambia el
   veredicto de forma detectable, nunca se cuela en silencio.
3. Frases NUEVAS de composicion (fuera de los dos corpus) contra la politica,
   documentando el resultado como test ejecutable en vez de solo asumirlo.
4. Que el CLI (`scripts/gate6/measure.py`) no admite ningun flag para
   sustituir el corpus por otro fichero: la unica forma de medir otra cosa es
   editar el codigo, un cambio visible en el diff, no un flag oculto.

Nada aqui modifica `knowledge_v3/eval/*` ni los corpus reales: las mutaciones
de integridad se hacen sobre COPIAS en `tmp_path`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from knowledge_v3.eval import gate6_dev_corpus, gate6_generalization_corpus, gate6_harness
from knowledge_v3.eval.gate6_generalization_corpus import load_generalization
from knowledge_v3.extraction.cues import analyze_raw_text
from knowledge_v3.eval.integrity import IntegrityError


REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------
# 1. Anti-enchufe: las rutas de los corpus no son parametrizables
# --------------------------------------------------------------------------
def test_las_rutas_de_los_corpus_estan_fijadas_por_modulo_no_por_argumento():
    """`gate6_dev_corpus`/`gate6_generalization_corpus` no exponen ningun
    parametro de ruta en `load_dev_cases`/`load_generalization`: la unica
    forma de medir un corpus distinto es editar `DATA_DIR`/`CASES_FILE` en el
    modulo (un cambio visible en el diff), nunca pasar un argumento en tiempo
    de ejecucion. Esto es justamente lo que impide "apuntar el runner a otro
    split" por accidente o de forma encubierta."""
    import inspect

    dev_params = set(inspect.signature(gate6_dev_corpus.load_dev_cases).parameters)
    assert dev_params == {"verify"}, (
        f"load_dev_cases gano un parametro nuevo ({dev_params}): si es una "
        "ruta o split parametrizable, reabre la puerta al enchufe silencioso"
    )

    gen_params = set(
        inspect.signature(gate6_generalization_corpus.load_generalization).parameters
    )
    assert gen_params == {"verify"}, (
        f"load_generalization gano un parametro nuevo ({gen_params}): misma "
        "razon que arriba"
    )


def test_el_cli_no_admite_flag_para_sustituir_el_corpus():
    """El runner (`scripts/gate6/measure.py`) solo admite `--out-dir` y
    `--out-name`: ningun flag de ruta de corpus, split o dataset. Se
    comprueba pidiendo `--help` y buscando que no aparezca ninguna palabra
    sugestiva de "otro corpus"."""
    result = subprocess.run(
        [sys.executable, "scripts/gate6/measure.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "data-engine/app"},
        timeout=30,
    )
    assert result.returncode == 0
    help_text = result.stdout.lower()
    for palabra_prohibida in ("--corpus", "--split", "--dataset", "--cases"):
        assert palabra_prohibida not in help_text, (
            f"el CLI expone {palabra_prohibida!r}: eso permitiria apuntar el "
            "runner a otro corpus sin dejar rastro en el codigo"
        )


def test_medir_el_programa_completo_usa_siempre_los_mismos_dos_corpus():
    """`measure_gate6_program` no acepta argumentos: no hay forma de pedirle
    que use un corpus distinto desde fuera del modulo."""
    import inspect

    params = set(inspect.signature(gate6_harness.measure_gate6_program).parameters)
    assert params == set()


# --------------------------------------------------------------------------
# 2. Corrupcion deliberada del gold
# --------------------------------------------------------------------------
def test_invertir_expected_class_cambia_el_veredicto_de_forma_detectable(
    tmp_path, monkeypatch
):
    """Si alguien invierte `expected_class` de un caso NON_FACTIVE a
    ASSERTED_FACT sin razon, la exactitud medida cambia (no se queda igual
    por casualidad ni la carga lo ignora en silencio)."""
    original = json.loads(
        (gate6_generalization_corpus.DATA_DIR / "cases.json").read_text(encoding="utf-8")
    )
    items = original["items"]
    target = next(i for i in items if i["expected_class"] == "NON_FACTIVE")
    before_pred = analyze_raw_text(target["text"]).factivity.factivity_class.value
    before_correct = before_pred not in gate6_generalization_corpus.FACT_CLASSES

    corrupted = json.loads(json.dumps(original))
    for entry in corrupted["items"]:
        if entry["case_id"] == target["case_id"]:
            entry["expected_class"] = "ASSERTED_FACT"

    corrupted_dir = tmp_path / "gate6_generalization"
    corrupted_dir.mkdir()
    (corrupted_dir / "cases.json").write_text(
        json.dumps(corrupted, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate6_generalization_corpus, "DATA_DIR", corrupted_dir)
    monkeypatch.setattr(
        gate6_generalization_corpus, "CASES_FILE", corrupted_dir / "cases.json"
    )

    items_loaded = load_generalization(verify=False)
    corrupted_item = next(i for i in items_loaded if i.case_id == target["case_id"])
    assert corrupted_item.expected_class == "ASSERTED_FACT"

    after_correct = before_pred == "ASSERTED_FACT"
    # La corrupcion es DETECTABLE: si antes acertaba (non-factive real) y el
    # veredicto predicho no es ASSERTED_FACT, tras invertir el gold pasa a
    # fallar (o viceversa) -- el numero se mueve, no queda ciego al cambio.
    assert before_correct != after_correct or before_pred == "ASSERTED_FACT"


def test_vaciar_el_corpus_de_generalizacion_rompe_la_integridad(tmp_path, monkeypatch):
    """Un corpus vaciado (0 items) no cuadra con el hash declarado en el
    manifiesto: rompe alto y claro, no produce un informe con 0 casos que
    parezca "100% de acierto" por division vacia."""
    empty_dir = tmp_path / "gate6_generalization"
    empty_dir.mkdir()
    (empty_dir / "cases.json").write_text(
        json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8"
    )
    manifest = json.loads(
        (gate6_generalization_corpus.DATA_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    (empty_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(gate6_generalization_corpus, "DATA_DIR", empty_dir)
    monkeypatch.setattr(gate6_generalization_corpus, "CASES_FILE", empty_dir / "cases.json")
    monkeypatch.setattr(gate6_generalization_corpus, "MANIFEST_FILE", empty_dir / "manifest.json")

    with pytest.raises(IntegrityError):
        load_generalization(verify=True)


def test_family_desconocida_rompe_la_carga(tmp_path, monkeypatch):
    original = json.loads(
        (gate6_generalization_corpus.DATA_DIR / "cases.json").read_text(encoding="utf-8")
    )
    corrupted = json.loads(json.dumps(original))
    corrupted["items"][0]["family"] = "FAMILIA_INVENTADA_QUE_NO_EXISTE"

    corrupted_dir = tmp_path / "gate6_generalization"
    corrupted_dir.mkdir()
    (corrupted_dir / "cases.json").write_text(
        json.dumps(corrupted, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(gate6_generalization_corpus, "DATA_DIR", corrupted_dir)
    monkeypatch.setattr(
        gate6_generalization_corpus, "CASES_FILE", corrupted_dir / "cases.json"
    )

    with pytest.raises(gate6_generalization_corpus.GenerationCorpusError):
        load_generalization(verify=False)


# --------------------------------------------------------------------------
# 3. Frases nuevas de composicion, fuera de los dos corpus (documentadas)
# --------------------------------------------------------------------------
_ADVERSARIAL_COMPOSITIONAL_CASES = [
    # (texto, ¿debe leerse como hecho del mundo?, descripcion)
    (
        "Se dice que, salvo que el veedor lo impida, Marín Costoya heredará el "
        "cargo de recaudador del muelle nuevo.",
        False,
        "rumor + condicional excepcional anidado, entidades fuera de ambos corpus",
    ),
    (
        "El escribano declaró que su ayudante insistió en que Doria Venzal "
        "administra el almacén de resinas.",
        False,
        "reporte anidado con verbos ('declaró que'/'insistió en que') fuera del "
        "vocabulario de cues.py",
    ),
    (
        "El tribunal no reconoció que Feles Ondarra hubiera pagado el tributo "
        "del embarcadero.",
        False,
        "negacion de un verbo factivo institucional ('reconocer')",
    ),
]


def test_documenta_fallos_de_la_politica_en_composiciones_nuevas_fuera_de_corpus():
    """No es un gate que deba pasar en verde: documenta, como test ejecutable,
    cuantas de estas frases NUEVAS (ni en el corpus dev ni en el de
    generalizacion de B0) la politica sigue leyendo mal. Sirve de evidencia
    externa de que el baseline de generalizacion composicional no es un
    artefacto de estos 42 casos concretos."""
    from knowledge_v3.extraction.cues import analyze_raw_text as analyze

    fails = []
    for text, should_be_fact, description in _ADVERSARIAL_COMPOSITIONAL_CASES:
        verdict = analyze(text)
        read_as_fact = verdict.factivity.factivity_class.value in (
            "ASSERTED_FACT",
            "NEGATED_FACT",
        )
        if read_as_fact != should_be_fact:
            fails.append((text, description, verdict.factivity.factivity_class.value))

    # Se documenta el conteo real, no se exige un numero concreto: esto es
    # evidencia externa, no un gate de aceptacion de B0 (B0 no toca la
    # politica). Solo se exige que al menos una de las tres frases FALLE --
    # si las tres empezaran a acertar, seria señal de que alguien ya cambio
    # `cues.py`/`factivity.py` y el hallazgo de B0 necesita re-medirse.
    assert fails, (
        "las tres frases adversariales de composicion, fuera de ambos "
        "corpus, acertaron: si esto es real (no un bug del test), la "
        "politica de factividad ya no tiene el problema de composicion que "
        "motiva el programa de la puerta 6 y B0 deberia re-medirse"
    )
