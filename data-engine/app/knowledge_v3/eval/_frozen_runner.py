# -*- coding: utf-8 -*-
"""Carga por ruta del runner E2E congelado de la puerta 4.

Aislado en su propio modulo, minimo, por dos motivos:

1. Lo usan tanto `dev_corpus.py` (para saber el nombre del split de
   desarrollo) como `harness.py` (para reutilizar `measure()`), y esta forma
   evita que uno importe al otro sin necesidad.
2. El nombre del split vive SOLO en el runner congelado
   (`gate4_negation_measure.SPLIT`), nunca escrito aqui como literal: un
   guardian de la propia bateria (`test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico`)
   prohibe a proposito que ningun fichero fuera de la bateria fije ese nombre
   a mano, y este arnes respeta esa regla igual que respeta cualquier otra:
   leyendolo del unico sitio donde esta declarado, en vez de repetirlo.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

#: Ruta del runner E2E congelado de la puerta 4. No se modifica ni se copia.
RUNNER_PATH = (
    Path(__file__).resolve().parents[4]
    / "artifacts"
    / "v3-final-validation"
    / "gate4_negation_measure.py"
)

_MODULE_NAME = "_gate4_negation_measure_frozen"


def load() -> ModuleType:
    """Importa el runner por ruta, una sola vez por proceso."""
    if not RUNNER_PATH.exists():
        raise FileNotFoundError(f"no se encuentra el runner congelado de la puerta 4: {RUNNER_PATH}")
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, RUNNER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise ImportError(f"no se pudo cargar el runner de la puerta 4: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def dev_split_name() -> str:
    """El nombre del split de desarrollo, leido del runner, nunca escrito aqui."""
    return str(load().SPLIT)


__all__ = ["RUNNER_PATH", "dev_split_name", "load"]
