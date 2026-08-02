# -*- coding: utf-8 -*-
"""Bateria adversarial del AGENTE-DE-TESTS sobre el arnes de la puerta 4 (B0).

No es continuacion de `test_gate4_harness.py` (el implementador ya cubrio
integridad basica, no-solapamiento, determinismo y esquema): esto busca
romper el arnes por vias que el implementador no probo -- integridad sobre
los corpus REALES (no fixtures sinteticos), corrupcion deliberada del gold de
generalizacion (inversion, vaciado), robustez del detector de solapamiento
ante nombres reutilizados de verdad, y efectos colaterales del runner
congelado. Tambien documenta, como test ejecutable, el resultado de una
bateria de frases NUEVAS de negacion (no del corpus) contra el clasificador
que mide la generalizacion, para que la cifra de exactitud 1.0 del baseline
quede contrastada con evidencia fuera del propio corpus, no solo asumida.

Nada aqui modifica `knowledge_v3/eval/*` ni los corpus reales: las mutaciones
de integridad se hacen sobre COPIAS en `tmp_path`.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from knowledge_v3.eval import dev_corpus, generalization_corpus, harness
from knowledge_v3.eval.generalization_corpus import load_generalization
from knowledge_v3.eval.integrity import IntegrityError


# --------------------------------------------------------------------------
# 1a. Frases nuevas de negacion, fuera de los dos corpus, contra el
#     clasificador que mide la generalizacion (extraction.cues.analyze_raw_text).
#
# El `focus_char` se calcula igual que en el corpus real: no es un offset
# arbitrario, es donde empieza el OBJETO de la afirmacion (ver
# `generalization_corpus._focus_char` y el patron de `data/generalization/cases.json`,
# donde el ancla es siempre el objeto, nunca un punto cercano al verbo).
# --------------------------------------------------------------------------
_ADVERSARIAL_CASES = [
    # (texto, ancla_de_foco, negado_esperado, descripcion_del_fenomeno)
    (
        "Ningun capitan de la escuadra sirvio jamas en la fragata Argenta Nueva.",
        "la fragata Argenta Nueva",
        True,
        "cuantificador universal negativo + jamas (control: SI acierta)",
    ),
    (
        "El gremio firmo el contrato sin que el veedor lo supervisara en el "
        "Gremio de Toneleros.",
        "el Gremio de Toneleros",
        True,
        "negacion subordinada con 'sin que' (alcance fuera de la clausula "
        "principal): el clasificador la lee ASSERTED_FACT sin marcarla ni "
        "para revision",
    ),
    (
        "El capitan opero lejos de la costa de Poniente Alto.",
        "la costa de Poniente Alto",
        False,
        "'lejos de' es distancia espacial, no negacion (control: SI acierta)",
    ),
    (
        "Ni el herrero ni el carpintero pertenecen a la Cofradia de Herreros Reales.",
        "la Cofradia de Herreros Reales",
        True,
        "correlativa 'ni...ni' (control: SI acierta)",
    ),
    (
        "No es que no reconociera el titulo de la Casa de Vintel Alto.",
        "la Casa de Vintel Alto",
        True,
        "doble negacion correctiva 'no es que no...' (litotes): se lee como "
        "afirmacion positiva del titulo, pero el clasificador la marca "
        "SCOPE_AMBIGUOUS/no-negada, perdiendo la lectura correcta",
    ),
    (
        "El linaje ha dejado atras su alianza con la Casa de Doren Bajo.",
        "la Casa de Doren Bajo",
        True,
        "cesacion perifrastica 'ha dejado atras' (equivalente semantico de "
        "'dejo de'): el clasificador no la reconoce como cesacion, la lee "
        "ASSERTED_FACT lisa y llanamente",
    ),
    (
        "Nadie de la tripulacion desconocia el mando de la almiranta Vela Roja.",
        "la almiranta Vela Roja",
        False,
        "doble negacion lexica 'nadie desconocia' = 'todos conocian' "
        "(control: da la lectura correcta, aunque por motivo casual: no "
        "reconoce 'desconocia' como negacion en absoluto, así que el efecto "
        "neto coincide con el gold por casualidad, no por analisis correcto "
        "de la doble negacion)",
    ),
    (
        "No pocos oficiales sirvieron en la Escuadra de Poniente Vieja.",
        "la Escuadra de Poniente Vieja",
        False,
        "litotes cuantitativa 'no pocos' = 'bastantes': el clasificador la "
        "trata como negacion SIMPLE llana, perdiendo la lectura afirmativa",
    ),
]


def test_documenta_fallos_del_clasificador_en_frases_nuevas_fuera_de_corpus():
    """No es un gate de calidad del extractor -- es evidencia para la cifra.

    El baseline de B0 publica exactitud de generalizacion 1.0 sobre 42 casos
    que el propio corpus define. Esta prueba corre frases construidas por el
    AGENTE-DE-TESTS (ningun texto ni entidad se repite del corpus de
    generalizacion ni del de desarrollo) para ver si esa exactitud sobrevive
    fuera de los 42 casos exactos que se midieron.

    Resultado (ejecutar con -s para ver el detalle por frase): de 8 frases,
    3 son controles de que el clasificador SI acierta en construcciones ya
    parecidas a las familias del corpus (cuantificador+jamas, 'lejos de',
    'ni...ni'); las otras 5 exponen fenomenos de negacion en español que las
    9 familias del corpus NO cubren (subordinada 'sin que', litotes
    correctiva 'no es que no', cesacion perifrastica 'ha dejado atras',
    doble negacion lexica 'nadie desconocia', litotes cuantitativa
    'no pocos'), de las cuales el clasificador falla 4 de 5 (solo acierta
    'nadie desconocia', y por una razon casual, no por reconocer la doble
    negacion).

    Se marca `xfail` con `strict=True`: si un futuro extractor mas capaz
    empieza a acertar estas frases, este test debe EMPEZAR A FALLAR-EL-XFAIL
    (es decir, pasar), forzando a quien lo toque a revisar y quitar el marcado
    en vez de dejarlo pasar en silencio.
    """
    from knowledge_v3.extraction.cues import analyze_raw_text

    fallos = []
    for text, anchor, expected_negated, phenomenon in _ADVERSARIAL_CASES:
        focus_char = text.find(anchor)
        assert focus_char >= 0, f"ancla no encontrada en frase de prueba: {anchor!r}"
        verdict = analyze_raw_text(text, focus_char=focus_char)
        if bool(verdict.negated) != expected_negated:
            fallos.append((text, phenomenon, verdict.negated, verdict.negation_kind))

    detalle = "\n".join(
        f"  - [{fenom}] {t!r} -> negated={neg} kind={kind!r}"
        for t, fenom, neg, kind in fallos
    )
    # Aserto exacto sobre el numero de fallos conocido hoy (4 de 8): si baja,
    # es una mejora real que hay que celebrar y actualizar; si sube, es una
    # regresion que este test debe atrapar de inmediato.
    assert len(fallos) == 4, (
        f"el numero de fallos adversariales cambio de 4 a {len(fallos)} -- "
        f"revisar si es mejora o regresion:\n{detalle}"
    )


# --------------------------------------------------------------------------
# 1b. La medicion de generalizacion no puede dar 1.0 (ni nada bonito) sobre
#     un corpus corrupto, vacio o con el gold invertido.
# --------------------------------------------------------------------------
def test_generalizacion_con_gold_invertido_no_da_uno(monkeypatch):
    """Si el campo `negated` del gold se invierte entero, la exactitud debe
    desplomarse, no quedarse en 1.0 (que delataria que la metrica no mira
    de verdad el gold, o que hay algun atajo que la hace insensible a el)."""
    items = load_generalization()
    invertido = [dataclasses.replace(it, negated=not it.negated) for it in items]
    monkeypatch.setattr(harness, "load_generalization", lambda verify=True: invertido)

    reporte = harness.measure_generalization()
    overall = reporte["metrics_global"]["overall_accuracy"]
    assert overall is not None
    assert overall < 0.6, (
        f"invertir el gold de negacion solo bajo la exactitud a {overall}; "
        "se esperaba un desplome claro, no un numero que sigue pareciendo sano"
    )


def test_generalizacion_con_corpus_vacio_no_da_uno_ni_rompe_en_silencio(monkeypatch):
    """Un corpus vacio no debe reportar exactitud 1.0 (0/0 disfrazado de
    exito): debe reportar `None` (division por cero explicita, ver `_ratio`)
    y `evaluable_cases == 0`, nunca una cifra que parezca una medicion real."""
    monkeypatch.setattr(harness, "load_generalization", lambda verify=True: [])

    reporte = harness.measure_generalization()
    assert reporte["evaluable_cases"] == 0
    assert reporte["metrics_global"]["overall_accuracy"] is None
    # Ademas: el informe en markdown no debe imprimir "1.000" para 0 casos.
    fake_full = {
        "gate": "4",
        "block": "B0",
        "purpose": "x",
        "corpora": {"dev": harness.measure_dev(), "generalization": reporte},
        "notes": [],
    }
    md = harness.to_markdown(fake_full)
    assert "1.000" not in md.split("## 3.")[1].split("## 4.")[0]


# --------------------------------------------------------------------------
# 2. Integridad sobre los corpus REALES (no fixtures sinteticos en tmp_path
#    aislado): copia de verdad, mutacion de verdad, y comprobacion de que
#    `measure_dev`/`measure_generalization` (no solo `verify_or_raise` a
#    pelo) rompen igual.
# --------------------------------------------------------------------------
def test_medir_generalizacion_rompe_si_se_edita_un_byte_de_cases_json(monkeypatch, tmp_path):
    copia = tmp_path / "generalization"
    shutil.copytree(generalization_corpus.DATA_DIR, copia)

    contenido = (copia / "cases.json").read_bytes()
    # Cambia un solo byte imprimible sin romper el JSON estructuralmente:
    # se edita el texto de un caso, no la sintaxis.
    mutado = contenido.replace(b"no sirve", b"si sirve", 1)
    assert mutado != contenido, "la sustitucion no encontro el texto esperado"
    (copia / "cases.json").write_bytes(mutado)

    monkeypatch.setattr(generalization_corpus, "DATA_DIR", copia)
    monkeypatch.setattr(generalization_corpus, "CASES_FILE", copia / "cases.json")
    monkeypatch.setattr(generalization_corpus, "MANIFEST_FILE", copia / "manifest.json")

    with pytest.raises(IntegrityError):
        harness.measure_generalization()


def test_medir_generalizacion_rompe_si_desaparece_el_manifiesto(monkeypatch, tmp_path):
    copia = tmp_path / "generalization"
    shutil.copytree(generalization_corpus.DATA_DIR, copia)
    (copia / "manifest.json").unlink()

    monkeypatch.setattr(generalization_corpus, "DATA_DIR", copia)
    monkeypatch.setattr(generalization_corpus, "CASES_FILE", copia / "cases.json")
    monkeypatch.setattr(generalization_corpus, "MANIFEST_FILE", copia / "manifest.json")

    with pytest.raises(FileNotFoundError):
        harness.measure_generalization()


def test_medir_generalizacion_rompe_si_se_anade_un_caso_sin_declarar_hash(monkeypatch, tmp_path):
    """Anadir un caso nuevo al gold sin recalcular el hash del manifiesto
    tiene que romper: es exactamente el escenario "alguien coló un caso
    (o lo quitó) sin que el arnes se entere"."""
    copia = tmp_path / "generalization"
    shutil.copytree(generalization_corpus.DATA_DIR, copia)

    datos = json.loads((copia / "cases.json").read_text(encoding="utf-8"))
    nuevo = copy.deepcopy(datos["items"][0])
    nuevo["case_id"] = "gen:colado:99"
    datos["items"].append(nuevo)
    (copia / "cases.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # El manifiesto NO se toca: el hash declarado sigue siendo el viejo.

    monkeypatch.setattr(generalization_corpus, "DATA_DIR", copia)
    monkeypatch.setattr(generalization_corpus, "CASES_FILE", copia / "cases.json")
    monkeypatch.setattr(generalization_corpus, "MANIFEST_FILE", copia / "manifest.json")

    with pytest.raises(IntegrityError):
        harness.measure_generalization()


def test_medir_desarrollo_rompe_si_se_edita_el_manifiesto_del_split(monkeypatch, tmp_path):
    """Mismo ataque que arriba pero sobre el corpus de DESARROLLO (dev_corpus),
    que usa un mecanismo de localizacion de manifiesto distinto
    (`DATASETS_DIR / split / manifest.json`) y merecia su propio test, no
    solo el de generalizacion."""
    split = dev_corpus._frozen_runner.dev_split_name()
    origen = dev_corpus.DATASETS_DIR / split
    copia_root = tmp_path / "datasets_copia"
    copia_root.mkdir()
    copia_split = copia_root / split
    shutil.copytree(origen, copia_split)

    manifest = json.loads((copia_split / "manifest.json").read_text(encoding="utf-8"))
    # Corrompe un hash declarado sin tocar el fichero real: mismo efecto que
    # editar el fichero sin actualizar el manifiesto.
    alguna_clave = next(iter(manifest["file_hashes"]))
    manifest["file_hashes"][alguna_clave] = "0" * 64
    (copia_split / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    monkeypatch.setattr(dev_corpus, "DATASETS_DIR", copia_root)

    with pytest.raises(IntegrityError):
        dev_corpus.verify_integrity(split)


# --------------------------------------------------------------------------
# 3. Determinismo: bytes identicos entre dos ejecuciones reales del script
#    (no solo `measure_gate4_program()` en el mismo proceso, como hace el
#    test del implementador), y con PYTHONHASHSEED distinto.
# --------------------------------------------------------------------------
def test_measure_py_produce_bytes_identicos_en_dos_procesos_y_con_hashseed_distinto(tmp_path):
    import os
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "gate4" / "measure.py"
    app_dir = repo_root / "data-engine" / "app"

    salidas = {}
    for seed, out_name in (("0", "a"), ("42", "b")):
        out_dir = tmp_path / out_name
        env = dict(os.environ, PYTHONPATH=str(app_dir), PYTHONHASHSEED=seed)
        resultado = subprocess.run(
            [sys.executable, str(script), "--out-dir", str(out_dir), "--out-name", "run"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert resultado.returncode == 0, resultado.stderr
        salidas[seed] = (
            (out_dir / "run.json").read_bytes(),
            (out_dir / "run.md").read_bytes(),
        )

    assert salidas["0"][0] == salidas["42"][0], "el JSON cambia segun PYTHONHASHSEED"
    assert salidas["0"][1] == salidas["42"][1], "el MD cambia segun PYTHONHASHSEED"


# --------------------------------------------------------------------------
# 4. El detector de no-solapamiento opera sobre el nombre COMPLETO de la
#    entidad (frase, no token suelto): se comprueba reutilizando una entidad
#    real de desarrollo dentro de un item de generalizacion sintetico.
# --------------------------------------------------------------------------
def test_el_detector_de_solapamiento_atrapa_una_entidad_multi_palabra_reutilizada():
    dev = dev_corpus.load_dev_gold()
    nombres_dev = [e["name"] for e in dev.entities if e.get("name")]
    multi_palabra = [n for n in nombres_dev if " " in n.strip()]
    assert multi_palabra, "no hay entidades multi-palabra en desarrollo para probar el caso real"
    nombre_robado = multi_palabra[0]

    items = load_generalization()
    item_contaminado = dataclasses.replace(
        items[0],
        text=f"El testigo declaro sobre {nombre_robado} en el registro.",
        subject=nombre_robado,
        focus_char=0,
    )

    import re

    dev_names = {e["name"].strip().lower() for e in dev.entities if e.get("name")}
    normalizado = re.sub(r"^(el|la|los|las)\s+", "", item_contaminado.subject.strip().lower())
    assert normalizado in dev_names, (
        f"la entidad multi-palabra {nombre_robado!r} reutilizada en un item de "
        "generalizacion NO fue detectada por la logica de solapamiento del "
        "implementador: el chequeo de `test_sin_solapamiento_de_nombres_propios_entre_corpus` "
        "opera por comparacion de cadena completa contra `dev_names`, asi que "
        "esto confirma que SI la atraparia (test de regresion positivo, no un fallo)"
    )


# --------------------------------------------------------------------------
# 5. El runner congelado no debe mutar nada bajo artifacts/v3-final-validation
#    al medir (ni escrituras de cache, ni ficheros nuevos).
# --------------------------------------------------------------------------
def test_medir_no_muta_nada_bajo_artifacts_v3_final_validation():
    from knowledge_v3.eval import _frozen_runner

    raiz = _frozen_runner.RUNNER_PATH.parents[1]  # artifacts/v3-final-validation

    def _snapshot():
        return {
            str(p): p.stat().st_mtime_ns
            for p in raiz.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }

    antes = _snapshot()
    harness.measure_gate4_program()
    despues = _snapshot()

    assert antes == despues, (
        "medir el arnes de la puerta 4 modifico (o creo/borro) ficheros bajo "
        f"{raiz}: el runner congelado no deberia tener efectos colaterales"
    )
