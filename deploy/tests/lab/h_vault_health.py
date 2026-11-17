# -*- coding: utf-8 -*-
"""Sonda del escenario H.8 (COMO el usuario de servicio con `runuser -u s9knowledge --`).

Ejecuta el componente de salud REAL `vault` (`checks.check_vault`) sobre la boveda dada y escribe
una linea JSON: {"vault": AVAILABLE|READ_ONLY|UNAVAILABLE, "status": HEALTHY|DEGRADED|..., ...}.
Es de solo lectura: no crea nada en la boveda (lo comprueba el propio escenario por inodos).

uso: h_vault_health.py <raiz-del-repo> <S9K_VAULT_ROOT> [require_mount=0]
"""
from __future__ import annotations

import json
import sys

raiz, vault = sys.argv[1], sys.argv[2]
montaje = sys.argv[3] if len(sys.argv) > 3 else "0"
sys.path.insert(0, raiz + "/viewer")
sys.path.append(raiz + "/data-engine/app")

from app.health import checks  # noqa: E402

r = checks.check_vault(vault, montaje)
print(json.dumps({"vault": r.details["vault"], "status": r.status.value, "message": r.message}))
