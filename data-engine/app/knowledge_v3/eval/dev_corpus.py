# -*- coding: utf-8 -*-
"""Corpus de DESARROLLO de la puerta 4: la bateria de negaciones, congelada.

No es un corpus nuevo: es el mismo que usa el runner E2E congelado de la
puerta 4, cargado por el mismo `benchmarks.loader.load_gold`. Lo unico que
anade este modulo es la comprobacion de integridad: antes de entregar el
dataset, recalcula el hash de sus 500+ ficheros contra su `manifest.json` y
rompe si alguno no cuadra. Ni una frase del gold se toca aqui -- solo se lee
y se comprueba.

El nombre del split NO se escribe aqui como literal: se lee de
`_frozen_runner.dev_split_name()`, que a su vez lo toma del runner congelado.
Es la misma regla que ya impone
`tests/test_knowledge_v3_negation_battery.py::test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico`:
nada fuera de la bateria fija ese nombre a mano, para que enchufarla a un
flujo automatico siga siendo una decision visible, nunca un efecto
colateral de copiar una cadena.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..benchmarks.loader import DATASETS_DIR, GoldDataset, load_gold
from . import _frozen_runner
from .integrity import verify_or_raise


def _manifest_path(split: str) -> Path:
    return DATASETS_DIR / split / "manifest.json"


def read_manifest(split: Optional[str] = None) -> dict[str, Any]:
    return json.loads(_manifest_path(split or _frozen_runner.dev_split_name()).read_text(encoding="utf-8"))


def verify_integrity(split: Optional[str] = None) -> None:
    """Rompe si algun fichero del corpus de desarrollo no cuadra con su hash."""
    split = split or _frozen_runner.dev_split_name()
    manifest = read_manifest(split)
    verify_or_raise(
        DATASETS_DIR,
        manifest.get("file_hashes", {}),
        label=f"corpus de desarrollo (bateria de negaciones, split `{split}`)",
    )


def load_dev_gold(*, split: Optional[str] = None, verify: bool = True) -> GoldDataset:
    """El gold de desarrollo, con la integridad comprobada por defecto.

    `verify=False` existe solo para diagnostico manual (por ejemplo, inspeccionar
    un corpus que se sabe roto); el arnes de medicion (`harness.py`) siempre
    llama con `verify=True`.
    """
    split = split or _frozen_runner.dev_split_name()
    if verify:
        verify_integrity(split)
    return load_gold(split)


__all__ = ["load_dev_gold", "read_manifest", "verify_integrity"]
