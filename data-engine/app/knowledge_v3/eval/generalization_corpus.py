# -*- coding: utf-8 -*-
"""Corpus de GENERALIZACION de la puerta 4 (B0).

Frases NUEVAS, en cuatro dominios ausentes del corpus de desarrollo (historia
naval, gremios de oficio, linajes, archivos monasticos), con entidades
inventadas para este corpus. Ninguna entidad ni sintagma verbatim aparece en
el split `negation` (comprobado por
`tests/test_gate4_harness.py::test_sin_solapamiento_de_nombres_propios_entre_corpus`
y companeras). Incluye una familia "dura" (`HARD_SCOPE_LITOTES`, ver mas
abajo) donde la exactitud se espera BAJA a proposito.

El contenido vive en `data/generalization/cases.json`, con su propio
manifiesto de integridad (`data/generalization/manifest.json`). El offset
donde empieza "lo afirmado" (`focus_char`, el mismo concepto que usa
`extraction.cues.analyze_raw_text`) NO se guarda como numero: se declara como
`focus_anchor`, el literal donde debe empezar, y se calcula aqui buscandolo en
el texto. Guardar el offset ya calculado invitaria a que quedase obsoleto si
alguien retoca la frase sin tocar el numero; calcularlo en cada carga hace que
un texto editado sin cuidado falle alto y claro, no que produzca un foco
desplazado y una metrica silenciosamente incorrecta.

**INSTRUCCION PARA QUIEN ANADA CASOS (B2+), LEER ANTES DE ESCRIBIR UN ITEM**:
`focus_anchor` (y por tanto `focus_char`) tiene que apuntar al INICIO DEL
OBJETO de la afirmacion -- el sintagma que seria el `object` del claim gold
(p.ej. "la Escuadra de Poniente" en "Ilan Bracer no sirve en la Escuadra de
Poniente") -- NUNCA al negador ni al verbo. Es el mismo contrato que usa
`extraction.cues.analyze_context`/`classify_negation`: `focus` marca donde
EMPIEZA lo afirmado, y la negacion se busca ANTES de ese punto. Un ancla
puesta en el verbo, en el sujeto o en cualquier punto que no sea el objeto
mueve la ventana de busqueda de la negacion y produce un veredicto que
PARECE una medicion valida -- no lanza excepcion, no sale `None`, sale un
`negated`/`negation_kind` cualquiera -- pero que no mide el fenomeno que el
item dice medir. No hay comprobacion automatica de que el ancla este "bien
puesta" semanticamente (solo se comprueba que el literal EXISTE en el texto,
ver `_focus_char`): la disciplina aqui es de quien escribe el caso, no del
cargador. Ante la duda, poner el ancla en el sintagma nominal completo del
objeto (con su articulo) tal y como aparece literalmente en el texto.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .integrity import verify_or_raise

DATA_DIR = Path(__file__).resolve().parent / "data" / "generalization"
CASES_FILE = DATA_DIR / "cases.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"


class GeneralizationCorpusError(RuntimeError):
    """El corpus de generalizacion esta mal formado."""


@dataclass(frozen=True)
class GeneralizationItem:
    """Un caso evaluable del corpus de generalizacion."""

    case_id: str
    family: str
    domain: str
    text: str
    focus_char: int
    subject: str
    predicate: str
    object: str
    negated: bool
    negation_kind: str
    review_scope: bool
    non_factive: bool
    why_evaluable: str
    #: Solo lo declaran los items de `HARD_SCOPE_LITOTES`: si la lectura
    #: correcta deberia resolverse como hecho confiado (`ASSERTED_FACT` o
    #: `NEGATED_FACT`), en vez de quedar en revision/ambiguo. `None` en el
    #: resto de familias, donde no hace falta este matiz.
    expected_asserted_fact: Optional[bool] = None


def _focus_char(text: str, anchor: str, case_id: str) -> int:
    idx = text.find(anchor)
    if idx < 0:
        raise GeneralizationCorpusError(
            f"{case_id}: el ancla de foco {anchor!r} no aparece literalmente en el texto"
        )
    return idx


def verify_integrity() -> None:
    """Rompe si `cases.json` no coincide con el hash de `manifest.json`."""
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    verify_or_raise(
        DATA_DIR.parent,
        manifest.get("file_hashes", {}),
        label="corpus de generalizacion (puerta 4, B0)",
    )


def load_generalization(*, verify: bool = True) -> list[GeneralizationItem]:
    """Carga el corpus de generalizacion, con integridad comprobada por defecto."""
    if verify:
        verify_integrity()
    raw = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    items: list[GeneralizationItem] = []
    seen_ids: set[str] = set()
    for entry in raw["items"]:
        case_id = entry["case_id"]
        if case_id in seen_ids:
            raise GeneralizationCorpusError(f"case_id duplicado: {case_id}")
        seen_ids.add(case_id)
        gold = entry["gold"]
        text = entry["text"]
        items.append(
            GeneralizationItem(
                case_id=case_id,
                family=entry["family"],
                domain=entry["domain"],
                text=text,
                focus_char=_focus_char(text, entry["focus_anchor"], case_id),
                subject=gold["subject"],
                predicate=gold["predicate"],
                object=gold["object"],
                negated=bool(gold["negated"]),
                negation_kind=gold.get("negation_kind", ""),
                review_scope=bool(gold.get("review_scope", False)),
                non_factive=bool(gold.get("non_factive", False)),
                why_evaluable=entry["why_evaluable"],
                expected_asserted_fact=(
                    bool(gold["expected_asserted_fact"])
                    if "expected_asserted_fact" in gold
                    else None
                ),
            )
        )
    return items


def family_counts(items: list[GeneralizationItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item.family] = out.get(item.family, 0) + 1
    return out


__all__ = [
    "DATA_DIR",
    "GeneralizationCorpusError",
    "GeneralizationItem",
    "family_counts",
    "load_generalization",
    "verify_integrity",
]
