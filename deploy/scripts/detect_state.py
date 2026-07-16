#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_state.py — clasifica la continuidad de estado entre el layout LEGACY y el
state root NUEVO antes de un despliegue (corrección RC1).

Estados (obligatorios):
  LEGACY_STATE           solo el layout legacy tiene datos usables
  NEW_STATE              solo el state root nuevo tiene datos usables
  MIXED_EQUIVALENT_STATE ambos existen y sus conteos coinciden (migración ya hecha)
  CONFLICTING_STATE      ambos existen y divergen -> requiere decisión humana
  EMPTY_STATE            ninguno tiene datos usables
  CORRUPT_STATE          alguna base falla integrity_check

Reglas de bloqueo en modo UPGRADE (--mode upgrade):
  - auth (crítica): EMPTY_STATE, CONFLICTING_STATE y CORRUPT_STATE BLOQUEAN.
  - jobs (opcional; el panel /jobs puede estar vacío): CONFLICTING_STATE y
    CORRUPT_STATE BLOQUEAN; EMPTY_STATE NO bloquea.
  - 0 administradores activos BLOQUEA.
  - Nunca se crea automáticamente una auth.db vacía.
  - Nunca se elige en silencio entre la DB legacy y la nueva.

Uso:
  detect_state.py --legacy-auth <path> --legacy-jobs <path> \
                  --new-auth <path> --new-jobs <path> [--mode upgrade|fresh]

Salida: JSON con estado global, por-base y decisión (proceed/block + motivo).
Código de salida: 0 = puede proceder; 3 = BLOQUEADO.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

# Reutilizamos la inspección de solo lectura del migrador
sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_sqlite import inspect_db  # noqa: E402


def _usable(info: dict[str, Any], kind: str) -> bool:
    """La base existe, es íntegra y tiene contenido con sentido."""
    if not info["exists"] or info["integrity"] != "ok":
        return False
    counts = info["counts"]
    if kind == "auth":
        return bool(counts.get("users"))
    if kind == "jobs":
        return (counts.get("jobs") or 0) > 0
    return False


def classify_pair(legacy: dict[str, Any], new: dict[str, Any], kind: str) -> str:
    if legacy["exists"] and legacy["integrity"] not in (None, "ok"):
        return "CORRUPT_STATE"
    if new["exists"] and new["integrity"] not in (None, "ok"):
        return "CORRUPT_STATE"
    lu, nu = _usable(legacy, kind), _usable(new, kind)
    if not lu and not nu:
        return "EMPTY_STATE"
    if lu and not nu:
        return "LEGACY_STATE"
    if nu and not lu:
        return "NEW_STATE"
    # ambos usables
    if legacy["counts"] == new["counts"]:
        return "MIXED_EQUIVALENT_STATE"
    return "CONFLICTING_STATE"


# Prioridad para el estado GLOBAL: lo peor manda
_SEVERITY = {
    "CORRUPT_STATE": 5,
    "CONFLICTING_STATE": 4,
    "EMPTY_STATE": 3,
    "LEGACY_STATE": 2,
    "MIXED_EQUIVALENT_STATE": 1,
    "NEW_STATE": 0,
}
# Estados que BLOQUEAN en upgrade, POR TIPO de base:
#   - auth es crítica: EMPTY (crearía auth vacía / sin admin), CONFLICTING y CORRUPT bloquean.
#   - jobs es opcional y puede estar legítimamente vacía (el panel /jobs es opcional):
#     solo CONFLICTING y CORRUPT bloquean; EMPTY no bloquea.
_BLOCKING_UPGRADE = {
    "auth": {"CORRUPT_STATE", "CONFLICTING_STATE", "EMPTY_STATE"},
    "jobs": {"CORRUPT_STATE", "CONFLICTING_STATE"},
}


def detect(
    legacy_auth: Optional[str], legacy_jobs: Optional[str],
    new_auth: Optional[str], new_jobs: Optional[str], mode: str,
) -> dict[str, Any]:
    per: dict[str, Any] = {}
    globals_states: list[str] = []

    def pair(kind: str, legacy_p: Optional[str], new_p: Optional[str]) -> None:
        li = inspect_db(Path(legacy_p), kind) if legacy_p else {"exists": False, "integrity": None, "counts": {}}
        ni = inspect_db(Path(new_p), kind) if new_p else {"exists": False, "integrity": None, "counts": {}}
        st = classify_pair(li, ni, kind)
        per[kind] = {"state": st, "legacy": li, "new": ni}
        globals_states.append(st)

    pair("auth", legacy_auth, new_auth)
    pair("jobs", legacy_jobs, new_jobs)

    global_state = max(globals_states, key=lambda s: _SEVERITY[s])

    reasons: list[str] = []
    block = False
    if mode == "upgrade":
        for kind, d in per.items():
            if d["state"] in _BLOCKING_UPGRADE.get(kind, set()):
                block = True
                reasons.append(f"{kind}: {d['state']} bloquea en upgrade")
        # 0 admins activos bloquea (mirando la fuente autoritativa de auth)
        auth = per["auth"]
        src = auth["legacy"] if auth["state"] in ("LEGACY_STATE", "MIXED_EQUIVALENT_STATE", "CONFLICTING_STATE") else auth["new"]
        active_admins = (src.get("counts") or {}).get("active_admins")
        if active_admins is not None and active_admins < 1:
            block = True
            reasons.append("0 administradores activos en la fuente de auth")

    return {
        "mode": mode,
        "global_state": global_state,
        "per_kind": per,
        "decision": "BLOCK" if block else "PROCEED",
        "reasons": reasons,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--legacy-auth")
    ap.add_argument("--legacy-jobs")
    ap.add_argument("--new-auth")
    ap.add_argument("--new-jobs")
    ap.add_argument("--mode", choices=["upgrade", "fresh"], default="upgrade")
    args = ap.parse_args(argv)
    result = detect(args.legacy_auth, args.legacy_jobs, args.new_auth, args.new_jobs, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 3 if result["decision"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
