# -*- coding: utf-8 -*-
"""Pruebas propias del contrato `review-status/v1`.

Existen por la misma razon que las de `review-ingest/v1` y `knowledge-v3/v1`:
un contrato compartido tiene que poder comprobarse SIN arrancar el visor ni el
motor. Aqui se cargan sus consumidores a proposito lo menos posible --solo la
libreria estandar-- porque la restriccion de importacion del modulo (no
depender de `viewer.app` ni de `pydantic_settings`) es parte del contrato: si
alguien la rompe, este fichero deja de poder importarlo y se pone rojo.

Lo que se comprueba en el visor (derivacion de etiquetas, fronteras de
escritura) vive en `viewer/tests/test_calidad_de_datos_v2.py`. Aqui solo el
contrato en si.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
MODEL_PATH = HERE.parent / "model.py"


def _cargar():
    nombre = "s9k_review_status_v1_model"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, MODEL_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod


RS = _cargar()


def test_el_modulo_no_depende_de_ninguna_aplicacion():
    """Restriccion de importacion del contrato, comprobada sobre el fuente.

    El contrato lo cargan por ruta el visor Y el motor. Si empezara a importar
    de cualquiera de los dos arboles, la direccion de dependencia se invertiria
    y el otro dejaria de poder usarlo.
    """
    fuente = MODEL_PATH.read_text(encoding="utf-8")
    codigo = "\n".join(
        ln for ln in fuente.splitlines() if not ln.lstrip().startswith("#")
    )
    for prohibido in ("viewer.app", "from app.", "import app", "pydantic",
                      "data_engine", "knowledge_v3"):
        assert prohibido not in codigo, (
            f"el contrato importa '{prohibido}': deja de ser cargable de forma "
            f"aislada por los dos arboles"
        )


def test_el_vocabulario_es_cerrado_y_no_vacio():
    assert RS.CANONICAL_VALUES
    assert RS.CANONICAL_VALUES == frozenset(s.value for s in RS.ReviewStatus)
    assert RS.HUMAN_REVIEWED < RS.CANONICAL_VALUES
    assert RS.LEGACY_MACHINE_APPROVED not in RS.CANONICAL_VALUES


def test_no_hay_estado_de_aprobado_por_maquina():
    """Un hecho que ningun humano ha mirado no puede afirmar estar revisado."""
    for valor in RS.CANONICAL_VALUES:
        if RS.is_human_reviewed(valor):
            assert valor in ("reviewed", "corrected")
    assert not RS.is_human_reviewed("auto_extracted")


@pytest.mark.parametrize("valor", sorted(RS.CANONICAL_VALUES))
def test_ida_y_vuelta(valor):
    assert RS.normalize(valor).value == valor


@pytest.mark.parametrize(
    "basura",
    [None, "", " ", "REVIEWED", " reviewed ", "auto_approved", "MAGIC", 0, [], {}],
)
def test_normalize_es_fail_closed(basura):
    with pytest.raises(RS.ReviewStatusError):
        RS.normalize(basura)


def test_el_adaptador_de_candidatos_cubre_el_enum_del_contrato_hermano():
    schema = json.loads(
        (REPO_ROOT / "contracts" / "review-ingest" / "v1" / "_common-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    enum = set(schema["$defs"]["candidate_status"]["enum"])
    assert enum, "no se pudo leer candidate_status"
    assert enum <= RS.candidate_statuses_cubiertos()


@pytest.mark.parametrize(
    "adaptador",
    ["from_candidate_status", "from_pipeline_decision", "from_review_manual_status"],
)
def test_todo_adaptador_produce_solo_valores_canonicos(adaptador):
    fn = getattr(RS, adaptador)
    dominio = {
        "from_candidate_status": RS.candidate_statuses_cubiertos(),
        "from_pipeline_decision": RS.decisiones_cubiertas(),
        "from_review_manual_status": RS.estados_de_revision_manual_cubiertos(),
    }[adaptador]
    assert dominio
    for entrada in sorted(dominio):
        assert fn(entrada).value in RS.CANONICAL_VALUES


@pytest.mark.parametrize(
    "adaptador",
    ["from_candidate_status", "from_pipeline_decision", "from_review_manual_status"],
)
@pytest.mark.parametrize("basura", [None, "", "MAGIC", 7, "auto_approved"])
def test_ningun_adaptador_tiene_default(adaptador, basura):
    with pytest.raises(RS.ReviewStatusError):
        getattr(RS, adaptador)(basura)


def test_etiquetar_no_devuelve_el_valor_crudo_como_respaldo():
    labels = {"reviewed": "Revisado"}
    assert RS.etiquetar("reviewed", labels) == "Revisado"
    assert RS.etiquetar("approved", labels) is None
    assert RS.etiquetar(None, labels) is None
