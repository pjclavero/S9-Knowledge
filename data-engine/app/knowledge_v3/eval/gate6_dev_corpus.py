# -*- coding: utf-8 -*-
"""Corpus de DESARROLLO de la puerta 6: la bateria de no-factividad, congelada.

No es un corpus nuevo: es el mismo `benchmarks/datasets/factivity/cases.json`
(100 frases, `dev-synthetic/opus-2026-07-30`) que ya midio la fase 3 de la
validacion V3 (ver `artifacts/v3-final-validation/gate6_factivity_runner.py` y
`gate6-findings.md`, seccion F6-7: "79/100 correctas"). Este modulo NO edita
ni una frase del gold: solo lo congela, con el mismo mecanismo de integridad
que ya usa el arnes de la puerta 4 (`eval/dev_corpus.py`,
`eval/generalization_corpus.py`) -- un `manifest.json` hermano con el sha256
del fichero, comprobado ANTES de leer el contenido.

El `manifest.json` de este corpus no existia antes de B0 (el corpus se uso en
la validacion V3 sin manifiesto de integridad, cargado a mano por el runner de
fase 3). B0 lo formaliza como dataset versionado, sin tocar su contenido: el
hash congelado aqui es el de `cases.json` tal y como quedo tras el ciclo de
correccion de la puerta 6.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .integrity import verify_or_raise

DATA_DIR = (
    Path(__file__).resolve().parents[1] / "benchmarks" / "datasets" / "factivity"
)
CASES_FILE = DATA_DIR / "cases.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

#: Clases de factividad que SI representan un hecho del mundo (mismo criterio
#: que `eval/harness.py::FACT_CLASSES` de la puerta 4 y que
#: `factivity_generalization_probe.py::FACT_CLASSES`): no se reinventa.
FACT_CLASSES = {"ASSERTED_FACT", "NEGATED_FACT"}


class FactivityDevCorpusError(RuntimeError):
    """El corpus de desarrollo de la puerta 6 esta mal formado."""


def verify_integrity() -> None:
    """Rompe si `cases.json` no coincide con el hash de `manifest.json`."""
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    verify_or_raise(
        DATA_DIR,
        manifest.get("file_hashes", {}),
        label="corpus de desarrollo (puerta 6, no-factividad dev-synthetic)",
    )


def load_dev_cases(*, verify: bool = True) -> dict[str, Any]:
    """Carga el corpus crudo (`dict` con `cases`, `families`, `provenance`...).

    `verify=True` por defecto, igual que `dev_corpus.load_dev_gold` de la
    puerta 4: la comprobacion de integridad es el comportamiento por defecto,
    no un extra que hay que acordarse de pedir.
    """
    if verify:
        verify_integrity()
    raw = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    seen_ids: set[str] = set()
    for case in raw["cases"]:
        case_id = case["case_id"]
        if case_id in seen_ids:
            raise FactivityDevCorpusError(f"case_id duplicado: {case_id}")
        seen_ids.add(case_id)
    return raw


def expected_world_fact(case: dict[str, Any]) -> bool:
    """Si el gold del caso dice que DEBE leerse como hecho del mundo.

    Se deriva del campo `expected` (`WRITE_POSITIVE`/`WRITE_NEGATIVE` frente a
    `ABSTAIN`/`DIAGNOSTIC`), no del campo `world_fact` en solitario: `expected`
    es la decision de ESCRITURA declarada por el corpus (¿se escribiria una
    relacion?), que es la pregunta que hace este gate. Los dos campos NO
    coinciden en las 100 filas: las 4 de `ALCANCE_COMPLEJO` tienen
    `world_fact=true` (el mundo SI tiene un hecho ahi) pero `expected=DIAGNOSTIC`
    (el alcance es ambiguo, asi que la decision correcta es revisar, no
    escribir a ciegas). Ese desacuerdo documentado es la razon por la que se
    usa `expected`, no `world_fact`: mide lo que el gate realmente evalua
    (¿se materializaria la relacion?), no si "en el fondo" hay un hecho.
    """
    return case["expected"] in ("WRITE_POSITIVE", "WRITE_NEGATIVE")


__all__ = [
    "CASES_FILE",
    "DATA_DIR",
    "FACT_CLASSES",
    "FactivityDevCorpusError",
    "MANIFEST_FILE",
    "expected_world_fact",
    "load_dev_cases",
    "verify_integrity",
]
