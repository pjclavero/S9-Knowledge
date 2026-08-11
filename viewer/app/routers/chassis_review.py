"""Hueco C del chasis — Review. Propiedad del carril C.

Montado y VACÍO: sustituye el cuerpo del handler manteniendo el contrato
declarado en `app/chassis.py` (prefijo, nombre de ruta, rol, plantilla).
"""
from __future__ import annotations

from app.chassis import FEATURE_SLOTS
from app.routers.chassis_slot import build_slot_router

SLOT = next(s for s in FEATURE_SLOTS if s.key == "C")
router = build_slot_router(SLOT)
