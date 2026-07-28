# -*- coding: utf-8 -*-
"""Errores y estructura de rechazo del writer.

Un rechazo NUNCA es una excepcion suelta con un mensaje: es un `Rejection` con
codigo estable, y viaja al registro de auditoria tal cual. El mensaje es para
humanos; el codigo es para el sistema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class WriterError(Exception):
    """Fallo del writer con codigo de rechazo asociado."""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail or {}

    def as_rejection(self) -> "Rejection":
        return Rejection(code=self.code, message=self.message, detail=dict(self.detail))


class WriterAbort(WriterError):
    """Aborta el plan ENTERO a mitad de ejecucion.

    Existe como clase propia porque su semantica no es «esta operacion falla»
    sino «esta transaccion no se confirma»: el writer no aplica planes a medias.
    """


@dataclass(frozen=True)
class Rejection:
    """Motivo de rechazo con codigo estable."""

    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}


__all__ = ["WriterError", "WriterAbort", "Rejection"]
