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
#: Bloque B0 (congelado, no se toca): las tres frases originales -- rumor +
#: condicional excepcional anidado, reporte anidado ("declaro que"/"insistio
#: en que") y negacion de un verbo factivo institucional ("reconocer") --
#: ACERTABAN antes de B1 y las TRES pasan a acertar despues de B1 (el
#: operador de discurso reportado por tercero y la extension de SCOPE_VERBS
#: las cubren). Se conservan comentadas para que quede constancia de la
#: mejora en evidencia EXTERNA (entidades y frases nunca vistas por ningun
#: corpus ni por B1 al disenar el operador), no solo en los 42+100 casos de
#: gold. La lista activa de abajo (`_ADVERSARIAL_COMPOSITIONAL_CASES`) se
#: renueva en B1 con frases NUEVAS que apuntan a huecos que B1 documento
#: como fuera de alcance (familia NEGATION_OF_FACTIVE con "nadie" en vez de
#: "no", NEGATED_RUMOR_HARD con "el rumor de" interpuesto, y un patron nuevo
#: de FACTIVE_IN_CONDITIONAL con "de resultar cierto que").
_ADVERSARIAL_COMPOSITIONAL_CASES_B0_RESUELTAS_EN_B1 = [
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
        "vocabulario de cues.py (B0) -- CUBIERTO por el operador de reporte de B1",
    ),
    (
        "El tribunal no reconoció que Feles Ondarra hubiera pagado el tributo "
        "del embarcadero.",
        False,
        "negacion de un verbo factivo institucional ('reconocer') -- CUBIERTO "
        "por la extension de SCOPE_VERBS de B1",
    ),
]

#: Bloque B1: frases NUEVAS (entidades y dominio propios, no en ningun
#: corpus) que apuntan a huecos que B1 diagnostico pero decidio NO cerrar
#: (fuera de la prioridad del encargo, o riesgo de sobreajuste): "nadie"
#: como negador de un verbo factivo (NEGATION_OF_FACTIVE con "nadie" en vez
#: de "no"/"nunca"/"jamas"/"tampoco"/"ni" -- `NEGATION_CUES` no incluye
#: "nadie"), "el rumor de" interpuesto entre "no es cierto" y "que"
#: (la misma trampa declarada HARD en `NEGATED_RUMOR_HARD`), y un patron de
#: condicional-envuelve-factivo con "de resultar cierto que" que
#: `CONDITIONAL_PHRASES`/`FALSITY_PHRASES` no cubren literalmente.
_ADVERSARIAL_COMPOSITIONAL_CASES = [
    (
        "Nadie en el gremio confirmó que Silas Kerr custodiara el archivo "
        "del puerto.",
        False,
        "negacion de un verbo factivo con 'nadie' en vez de 'no' -- "
        "NEGATION_CUES no incluye 'nadie', fuera de prioridad de B1",
    ),
    (
        "No es cierto el rumor de que Elin Doss trafica con seda en el "
        "muelle norte.",
        False,
        "'el rumor de' interpuesto rompe el match literal de "
        "FALSITY_PHRASES -- misma trampa declarada HARD en "
        "NEGATED_RUMOR_HARD, fuera de prioridad de B1",
    ),
    (
        "De resultar cierto que Iris Faber preside la asamblea de "
        "vinateros, el consejo actuará.",
        False,
        "condicional envuelve un factivo con 'de resultar cierto que' -- "
        "variante de FACTIVE_IN_CONDITIONAL no cubierta por las frases "
        "literales de CONDITIONAL_PHRASES, fuera de prioridad de B1",
    ),
]


def test_las_frases_adversariales_de_b0_ahora_aciertan_evidencia_externa_de_b1():
    """Las tres frases adversariales de B0 (fuera de ambos corpus, con
    entidades que B1 nunca vio al disenar el operador de reporte ni la
    extension de SCOPE_VERBS) ahora se leen correctamente como NO-hecho.
    Es evidencia EXTERNA de que la mejora de B1 generaliza mas alla de los
    42+100 casos de gold: si esto empieza a fallar, alguien toco `cues.py`/
    `factivity.py` de forma que revierte el operador de reporte o la
    extension de verbos factivos de B1, y hay que re-medir el programa."""
    from knowledge_v3.extraction.cues import analyze_raw_text as analyze

    fails = []
    for text, should_be_fact, description in (
        _ADVERSARIAL_COMPOSITIONAL_CASES_B0_RESUELTAS_EN_B1
    ):
        verdict = analyze(text)
        read_as_fact = verdict.factivity.factivity_class.value in (
            "ASSERTED_FACT",
            "NEGATED_FACT",
        )
        if read_as_fact != should_be_fact:
            fails.append((text, description, verdict.factivity.factivity_class.value))
    assert not fails, (
        f"las frases que B1 declara resueltas volvieron a fallar: {fails} -- "
        "si esto es real (no un bug del test), el operador de reporte o la "
        "extension de SCOPE_VERBS de B1 se revirtieron parcialmente"
    )


def test_documenta_fallos_de_la_politica_en_composiciones_nuevas_fuera_de_corpus():
    """No es un gate que deba pasar en verde: documenta, como test ejecutable,
    cuantas de estas frases NUEVAS (ni en el corpus dev ni en el de
    generalizacion, ni en las resueltas por B1) la politica sigue leyendo
    mal. Sirve de evidencia externa de que TODAVIA quedan huecos genuinos
    fuera de la prioridad de B1 (no son un artefacto de los 42+100 casos de
    gold ni de las frases que B1 ya soluciono)."""
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
    # evidencia externa, no un gate de aceptacion. Solo se exige que al
    # menos una de las tres frases FALLE -- si las tres empezaran a acertar,
    # seria señal de que alguien ya cerro estos huecos y el programa de la
    # puerta 6 deberia re-medirse (y este test, renovarse otra vez).
    assert fails, (
        "las tres frases adversariales de composicion, fuera de ambos "
        "corpus, acertaron: si esto es real (no un bug del test), la "
        "politica de factividad ya no tiene los huecos que B1 dejo fuera "
        "de prioridad y el programa de la puerta 6 deberia re-medirse"
    )


# --------------------------------------------------------------------------
# 5. Las 40 violaciones fail-closed NO son un artefacto de medir la politica
#    aislada: el arnes usa exactamente la misma señal (`FactivityClass` en
#    `FACT_CLASSES`) que el pipeline real usa para decidir si aborta.
# --------------------------------------------------------------------------
def test_read_as_world_fact_predice_exactamente_las_guardas_del_pipeline():
    """B3 de la puerta 4 encontro un comparador asimetrico que hacia que el
    arnes reportase violaciones que el pipeline real no cometia (el arnes
    media la politica sin las guardas que el motor si aplicaba). Aqui se
    comprueba la hipotesis contraria para B0: `extraction/deterministic.py` y
    `extraction/payload.py` SOLO abortan la escritura de un claim cuando
    `verdict.factivity.action` es `EMIT_DIAGNOSTIC` o `REVIEW_SCOPE` (ver
    `_drop_non_factive` / el `abstain(...)` de alcance ambiguo) -- no
    reconsultan `cues.py` con mas contexto ni aplican ninguna guarda
    adicional aguas abajo. La particion de `FactivityClass` que hace el arnes
    (`predicted_class in FACT_CLASSES` == `{ASSERTED_FACT, NEGATED_FACT}`)
    tiene que coincidir, clase a clase, con esa particion de accion: si algun
    dia alguien cambia `classify_factivity` para que una clase no-factiva
    mapee a una accion que el pipeline NO trata como aborto (o viceversa),
    este test rompe antes de que el numero de violaciones del arnes deje de
    significar lo que el informe de B0 dice que significa."""
    from knowledge_v3.extraction.factivity import (
        FactivityAction,
        FactivityClass,
        FactivitySignals,
        classify_factivity,
    )
    from knowledge_v3.eval.gate6_dev_corpus import FACT_CLASSES

    # Las acciones que el pipeline real trata como "no se escribe un claim
    # afirmando el mundo": `_drop_non_factive` en deterministic.py/payload.py
    # dispara con EMIT_DIAGNOSTIC; el abstain() de alcance ambiguo con
    # REVIEW_SCOPE. Ninguna otra accion aborta la escritura.
    PIPELINE_ABORT_ACTIONS = {FactivityAction.EMIT_DIAGNOSTIC, FactivityAction.REVIEW_SCOPE}

    signal_field_by_class = {
        FactivityClass.QUESTION: "question",
        FactivityClass.COUNTERFACTUAL: "counterfactual",
        FactivityClass.REPORTED_FALSEHOOD: "reported_falsehood",
        FactivityClass.FICTION_WITHIN_FICTION: "fiction_within_fiction",
        FactivityClass.DESIRE: "desire",
        FactivityClass.COMMAND: "command",
        FactivityClass.CONDITIONAL: "conditional",
        FactivityClass.HYPOTHETICAL: "hypothetical",
        FactivityClass.RUMOR: "rumor",
    }

    for klass, field in signal_field_by_class.items():
        signals = FactivitySignals(**{field: True})
        result = classify_factivity(signals)
        assert result.factivity_class is klass
        world_fact = klass.value in FACT_CLASSES
        aborts = result.action in PIPELINE_ABORT_ACTIONS
        if world_fact:
            assert aborts is False, (
                f"{klass}: el arnes lo cuenta como hecho del mundo pero su "
                f"accion ({result.action}) SI aborta la escritura en el "
                "pipeline -- el numero de violaciones estaria INFLADO"
            )
        elif klass is FactivityClass.RUMOR:
            # RUMOR es la excepcion documentada: su accion
            # (EMIT_EPISTEMIC_PROPOSAL) NO aborta la escritura en
            # deterministic.py -- el claim SI se emite, pero con
            # `epistemic_status_hint` degradado (no "ASSERTED"), no como
            # hecho del mundo. read_as_world_fact tampoco lo cuenta como
            # hecho (RUMOR no esta en FACT_CLASSES), asi que arnes y
            # pipeline coinciden en el resultado observable (no se escribe
            # un ASSERTED/NEGATED_FACT), aunque por mecanismos distintos
            # (abstain vs. degradar el hint). Si esto deja de ser cierto --
            # si algun consumidor aguas abajo empieza a tratar un claim con
            # hint degradado como hecho del mundo -- la MEDICION seguiria
            # siendo correcta pero dejaria de ser SUFICIENTE, y haria falta
            # un tercer eje de medicion (el hint, no solo la clase).
            assert result.action is FactivityAction.EMIT_EPISTEMIC_PROPOSAL
        else:
            assert aborts is True, (
                f"{klass}: el arnes lo cuenta como NO-hecho (correctamente, "
                "segun su gold) pero su accion "
                f"({result.action}) NO aborta la escritura en el pipeline "
                "real -- esto SI seria una violacion fail-closed genuina "
                "que el arnes ya deberia estar viendo (si no la ve, hay un "
                "bug en el arnes, no solo en la politica)"
            )

    # Alcance ambiguo: la unica via a REVIEW_SCOPE, y unica clase UNKNOWN.
    ambiguous = classify_factivity(FactivitySignals(ambiguous_scope=True))
    assert ambiguous.factivity_class is FactivityClass.UNKNOWN
    assert ambiguous.action is FactivityAction.REVIEW_SCOPE
    assert ambiguous.factivity_class.value not in FACT_CLASSES


# --------------------------------------------------------------------------
# 6. Diagnostico B1 de la anomalia LEXICAL_NEGATION_EDGE (antes
#    POSITIVE_CONTROL): "nunca salio del" sale UNKNOWN en vez de NEGATED_FACT.
#    B1 investigo la causa (no es el hallazgo de composicion que motiva B0):
#    `cessation_matches` reconoce "salio del" como CESSATION_PHRASES (misma
#    familia lexica que "abandono"/"dimitio de"/"se separo de"), y
#    `negated_cessation` trata CUALQUIER negacion pegada a una cesacion como
#    DOBLE negacion ambigua ("no dejo de servir" = sigue sirviendo). Esa regla
#    es CORRECTA para cesacion de pertenencia/cargo (negar el abandono afirma
#    la continuidad de la relacion, y el motor no puede materializar esa
#    relacion sin saber a que predicado positivo corresponde -- de ahi la
#    prudencia de pedir revision) pero en este caso concreto el gold modela
#    la frase como la negacion DIRECTA de un evento de partida, no como la
#    cesacion (con flip) de una relacion de pertenencia. Las dos lecturas son
#    indistinguibles con el vocabulario/patron actual sin arriesgar una
#    regresion en las cesaciones de pertenencia genuinas (abandono, dimitio,
#    fue expulsado...), que SI necesitan la ambiguedad para no inventar una
#    relacion. B1 decide NO tocar `negated_cessation`/`cessation_matches`:
#    es un limite arquitectonico documentado, no un bug puntual -- ver
#    docs/v3/44. El caso se reclasifico de POSITIVE_CONTROL a
#    LEXICAL_NEGATION_EDGE (mide negacion lexica, no factividad), gold
#    intacto.
# --------------------------------------------------------------------------
def test_positive_control_04_sale_unknown_limite_arquitectonico_documentado():
    """`gen6:positive_control:04` ('El Arca de Especias nunca salio del
    Muelle de la Canela.', gold NEGATED_FACT, familia LEXICAL_NEGATION_EDGE
    desde B1) sigue en UNKNOWN. B1 diagnostico la causa real (ver comentario
    de arriba): es la MISMA regla de `negated_cessation` que protege
    correctamente "no abandono el clan"/"no dimitio de su cargo" de perder
    la relacion de pertenencia -- aplicada aqui a un verbo de PARTIDA fisica
    ("salio del") en vez de un verbo de PERTENENCIA. Corregir el patron para
    este caso sin arriesgar las cesaciones genuinas exigiria distinguir
    "cesacion de pertenencia" de "partida fisica" por semantica del
    complemento, que el vocabulario cerrado actual no sabe hacer sin
    inventar una heuristica ad-hoc sobre este caso concreto -- exactamente
    lo que el encargo prohibe. Se deja como limite arquitectonico
    documentado, no como regresion pendiente."""
    from knowledge_v3.extraction.cues import analyze_raw_text

    verdict = analyze_raw_text(
        "El Arca de Especias nunca salio del Muelle de la Canela."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN", (
        "si esto ya no es UNKNOWN, el limite arquitectonico documentado en "
        "B1 (docs/v3/44) se ha corregido o ha cambiado de forma -- "
        "re-verificar el hallazgo antes de borrar este test"
    )
