# -*- coding: utf-8 -*-
"""Corpus de GENERALIZACION COMPOSICIONAL de la puerta 6 (B0).

La sonda `factivity_generalization_probe.py` (fase 3 de la validacion V3) ya
demostro que la politica de factualidad memoriza VOCABULARIO: acierta 100 %
en el corpus dev y 23,1 % fuera de el con marcadores no-factivos nuevos. Ese
hallazgo mide el eje "vocabulario nuevo, un solo operador por frase".

Este corpus mide un eje DISTINTO y complementario: COMPOSICION de operadores
ya conocidos (rumor, condicional, negacion, reporte) unos dentro de otros --
condicional dentro de rumor, reporte anidado, negacion de un verbo factivo
("confirmar", "admitir", "reconocer"), un factivo dentro de un condicional,
un rumor negado, y el reporte de una negacion. `classify_factivity` en
`extraction/factivity.py` es una precedencia PLANA sobre senales booleanas
detectadas por un escaneo de superficie (`cues.analyze_raw_text`): no hay
seguimiento real de alcance sintactico ni de anidamiento. La hipotesis que
prueba este corpus es que esa arquitectura falla especificamente cuando dos
operadores se combinan, incluso si cada uno por separado esta bien resuelto.

Entidades y dominio (diplomacia especiera) NUEVOS, ausentes del corpus dev
(`benchmarks/datasets/factivity/cases.json`, dominio de facciones y objetos
medievales-fantasticos): comprobado por
`tests/test_gate6_harness.py::test_sin_solapamiento_de_ngramas_con_el_corpus_dev`
(n-gramas >= 3, cero comparticion). No hay `focus_char`: a diferencia de la
puerta 4 (donde el clasificador mide alcance de negacion sobre un punto de
anclaje), aqui `analyze_raw_text` se llama sobre la frase COMPLETA -- la
composicion es justamente sobre la frase entera, no sobre una ventana.

El contenido vive en `data/gate6_generalization/cases.json`, con su propio
manifiesto de integridad (`data/gate6_generalization/manifest.json`), misma
disciplina que `eval/generalization_corpus.py` de la puerta 4.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .integrity import verify_or_raise

DATA_DIR = Path(__file__).resolve().parent / "data" / "gate6_generalization"
CASES_FILE = DATA_DIR / "cases.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

#: Familias que representan composicion genuina de al menos dos operadores de
#: factividad. `POSITIVE_CONTROL` es la excepcion deliberada: no compone nada,
#: existe para comprobar que el clasificador sigue funcionando bien en el
#: caso simple con este vocabulario/dominio nuevo (si fallase ahi tambien, el
#: problema no seria composicion, seria vocabulario, y hay que poder
#: distinguir los dos fallos).
_EXPECTED_FAMILIES = {
    "CONDITIONAL_IN_RUMOR",
    "NESTED_REPORT",
    "NEGATION_OF_FACTIVE",
    "FACTIVE_IN_CONDITIONAL",
    "NEGATED_RUMOR_HARD",
    "REPORT_OF_NEGATION",
    "POSITIVE_CONTROL",
}

#: Familia "dura": se declara por adelantado que se ESPERA una exactitud baja
#: (ver docstring de cada item `NEGATED_RUMOR_HARD` en `cases.json`: la
#: construccion "no es cierto el rumor de que" no es substring literal de
#: ninguna `FALSITY_PHRASE` de `cues.py` por la interposicion de "el rumor
#: de", asi que se espera que la cue no dispare). No se ajusta el gold para
#: que el sistema "acierte": el gold es la lectura correcta segun la politica
#: fail-closed (no materializar sin revisar), y el baseline honesto es
#: publicar la exactitud real, sea la que sea.
HARD_FAMILIES = {"NEGATED_RUMOR_HARD"}

#: Clases que SI representan un hecho del mundo. Mismo criterio que
#: `gate6_dev_corpus.FACT_CLASSES` y `eval/harness.py::FACT_CLASSES`.
FACT_CLASSES = {"ASSERTED_FACT", "NEGATED_FACT"}

_VALID_EXPECTED_CLASSES = FACT_CLASSES | {"NON_FACTIVE"}


class GenerationCorpusError(RuntimeError):
    """El corpus de generalizacion composicional esta mal formado."""


@dataclass(frozen=True)
class CompositionalItem:
    """Un caso evaluable del corpus de generalizacion composicional."""

    case_id: str
    family: str
    domain: str
    text: str
    subject: str
    object: str
    expected_class: str
    hard: bool
    why_evaluable: str


def verify_integrity() -> None:
    """Rompe si `cases.json` no coincide con el hash de `manifest.json`."""
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    verify_or_raise(
        DATA_DIR,
        manifest.get("file_hashes", {}),
        label="corpus de generalizacion composicional (puerta 6, B0)",
    )


def load_generalization(*, verify: bool = True) -> list[CompositionalItem]:
    """Carga el corpus de generalizacion, con integridad comprobada por defecto."""
    if verify:
        verify_integrity()
    raw = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    items: list[CompositionalItem] = []
    seen_ids: set[str] = set()
    for entry in raw["items"]:
        case_id = entry["case_id"]
        if case_id in seen_ids:
            raise GenerationCorpusError(f"case_id duplicado: {case_id}")
        seen_ids.add(case_id)
        family = entry["family"]
        if family not in _EXPECTED_FAMILIES:
            raise GenerationCorpusError(f"{case_id}: familia desconocida {family!r}")
        expected_class = entry["expected_class"]
        if expected_class not in _VALID_EXPECTED_CLASSES:
            raise GenerationCorpusError(
                f"{case_id}: expected_class invalida {expected_class!r}"
            )
        text = entry["text"]
        subject = entry["subject"]
        obj = entry["object"]
        if subject not in text or obj not in text:
            raise GenerationCorpusError(
                f"{case_id}: subject/object no aparecen literalmente en el texto"
            )
        items.append(
            CompositionalItem(
                case_id=case_id,
                family=family,
                domain=entry["domain"],
                text=text,
                subject=subject,
                object=obj,
                expected_class=expected_class,
                hard=bool(entry.get("hard", False)),
                why_evaluable=entry["why_evaluable"],
            )
        )
    return items


def family_counts(items: list[CompositionalItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item.family] = out.get(item.family, 0) + 1
    return out


__all__ = [
    "CASES_FILE",
    "DATA_DIR",
    "FACT_CLASSES",
    "HARD_FAMILIES",
    "CompositionalItem",
    "GenerationCorpusError",
    "family_counts",
    "load_generalization",
    "verify_integrity",
]
