# -*- coding: utf-8 -*-
"""Errores del orquestador.

El orquestador NO decide. Cuando algo va mal, o bien deja que el error del
subsistema suba tal cual —porque el subsistema ya sabe decir lo que pasa— o
bien lo envuelve en `PipelineError` indicando la etapa. Nunca lo convierte en
un modo degradado silencioso: un tramo de la cadena que falla y sigue como si
nada es exactamente la clase de fallo que este bloque existe para detectar.
"""
from __future__ import annotations


class PipelineError(RuntimeError):
    """Fallo del orquestador, con la etapa en la que ocurrio."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message


__all__ = ["PipelineError"]
