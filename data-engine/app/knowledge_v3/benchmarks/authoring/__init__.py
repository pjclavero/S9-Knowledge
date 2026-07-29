# -*- coding: utf-8 -*-
"""Autoria del dataset gold.

El CONTENIDO (textos, anotaciones, trampas) esta escrito a mano en los modulos
``world_*.py`` / ``source_*.py``. Este paquete solo calcula lo mecanico:
offsets, hashes, envelopes y trazas de proveedor. Un offset escrito a mano se
equivoca; uno calculado sobre el texto literal, no.
"""
from __future__ import annotations

__all__ = ["common", "build"]
