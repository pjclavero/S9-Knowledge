"""Hueco B del chasis — Operations. Propiedad del carril B.

Montado y VACÍO: sustituye el cuerpo del handler manteniendo el contrato
declarado en `app/chassis.py` (prefijo, nombre de ruta, rol, plantilla).
"""
from __future__ import annotations

from app.chassis import FEATURE_SLOTS
from app.routers.chassis_slot import build_slot_router

SLOT = next(s for s in FEATURE_SLOTS if s.key == "B")
router = build_slot_router(SLOT)
