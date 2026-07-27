# -*- coding: utf-8 -*-
"""Errores del subsistema de resolucion de identidad.

Se distinguen dos familias porque tienen destinatarios distintos:

- `ResolutionInputError`: la ENTRADA no permite emitir un documento valido
  (menciones de workspaces distintos, grupo vacio, sin evidencia...). Es un
  fallo del llamante y se lanza; no se degrada en silencio ni se inventa un
  documento incompleto.
- `ResolutionConfigError`: la CONFIGURACION es incoherente (umbrales fuera de
  orden, paso desconocido en el orden de cascada). Se detecta al construir la
  configuracion, no a mitad de una resolucion.
"""
from __future__ import annotations


class ResolutionError(Exception):
    """Raiz de los errores del resolutor."""


class ResolutionInputError(ResolutionError):
    """La entrada no permite producir una `EntityResolution` valida."""


class ResolutionConfigError(ResolutionError):
    """La configuracion de la cascada es incoherente."""


__all__ = ["ResolutionError", "ResolutionInputError", "ResolutionConfigError"]
