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

Reglas de bloqueo en modo FRESH (--mode fresh, B2 · USABLE-V1: PRIMERA release):
  - fresh significa «máquina limpia»: SOLO procede si auth es EMPTY_STATE (no
    hay base, o la hay sin ningún usuario). Cualquier otro estado de auth
    BLOQUEA: con usuarios hay que usar --mode upgrade, y CORRUPT/CONFLICTING
    bloquean igual que en upgrade. fresh NUNCA sobrescribe ni migra auth.
  - jobs: CORRUPT_STATE, CONFLICTING_STATE y LEGACY_STATE BLOQUEAN (un layout
    legacy con datos no es una máquina limpia).
  - Con auth EMPTY el alta del primer administrador se CEDE a /setup/admin:
    la salida lo declara en `primer_admin_pendiente` (FIRST_ADMIN_PENDING).

AUTORIDAD (B2, H-01/H-43): `decision` es la ÚNICA respuesta a «¿se puede
seguir?». `global_state` es INFORMATIVO (lo peor de las dos bases): una
jobs.db ausente lo pone en EMPTY_STATE aunque el despliegue pueda seguir, y
por eso `deploy.sh` no lo usa para decidir.

Uso:
  detect_state.py --legacy-auth <path> --legacy-jobs <path> \
                  --new-auth <path> --new-jobs <path> [--mode upgrade|fresh]

Salida: JSON con estado global, por-base y decisión (proceed/block + motivo).
Código de salida: 0 = puede proceder; 3 = BLOQUEADO.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

# Reutilizamos la inspección de solo lectura del migrador
sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_sqlite import inspect_db  # noqa: E402

#: Clave del SELLO de instalación del producto. MISMO literal que
#: `viewer/app/auth/db.py::BOOTSTRAP_KEY`; el testigo de B2 cruza los dos.
#: Se replica porque este guion corre en el host, fuera del venv del visor.
BOOTSTRAP_KEY = "bootstrap_completed"


def sello_de_instalacion(path: Optional[str]) -> Optional[bool]:
    """¿Está puesto el sello `install_state['bootstrap_completed']`? Solo lectura.

    Es el ESTADO DEL PRODUCTO que decide si `/setup/admin` existe
    (`viewer/app/auth/bootstrap.py`). ``None`` = no se puede saber (base
    ausente, vacía, ilegible, o anterior al esquema v4 sin la tabla): AUSENCIA
    != «no sellado». Nunca crea ni migra nada.
    """
    if not path:
        return None
    ruta = Path(path)
    if not ruta.is_file() or ruta.stat().st_size == 0:
        return None
    try:
        conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        fila = conn.execute(
            "SELECT value FROM install_state WHERE key = ?", (BOOTSTRAP_KEY,)
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return fila is not None and str(fila[0]).lower() == "true"


def _usable(info: dict[str, Any], kind: str) -> bool:
    """La base existe, es íntegra y tiene contenido con sentido.

    auth: sin usuarios no hay nada que conservar (una base migrada y vacía es
    el estado de fábrica). jobs: la COLA puede estar legítimamente vacía (un
    host que nunca encoló un trabajo, o que purgó la cola); lo que la hace
    usable es que la tabla exista, no que tenga filas (H-43).
    """
    if not info["exists"] or info["integrity"] != "ok":
        return False
    counts = info["counts"]
    if kind == "auth":
        return bool(counts.get("users"))
    if kind == "jobs":
        return counts.get("jobs") is not None
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
    if kind == "jobs":
        # Una cola VACÍA no compite con una que tiene trabajos: manda la que
        # los tiene. Conserva lo que ya pasaba antes de H-43, cuando la vacía
        # ni siquiera contaba como usable (y la migración sigue negándose a
        # pisar un destino distinto: BLOCKED_DST_CONFLICT).
        if not legacy["counts"].get("jobs"):
            return "NEW_STATE"
        if not new["counts"].get("jobs"):
            return "LEGACY_STATE"
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
# Estados que BLOQUEAN en fresh (primera release sobre máquina limpia):
#   - auth: todo lo que NO sea EMPTY. Con usuarios, fresh sería sobrescribir o
#     ignorar una instalación existente: se usa --mode upgrade.
#   - jobs: corrupción, conflicto o datos del layout legacy.
_BLOCKING_FRESH = {
    "auth": {"CORRUPT_STATE", "CONFLICTING_STATE", "LEGACY_STATE",
             "NEW_STATE", "MIXED_EQUIVALENT_STATE"},
    "jobs": {"CORRUPT_STATE", "CONFLICTING_STATE", "LEGACY_STATE"},
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
    sello_nuevo = sello_de_instalacion(new_auth)
    sello_legacy = sello_de_instalacion(legacy_auth)
    per["auth"]["sello"] = {"legacy": sello_legacy, "new": sello_nuevo}

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
    elif mode == "fresh":
        for kind, d in per.items():
            if d["state"] in _BLOCKING_FRESH.get(kind, set()):
                block = True
                reasons.append(
                    f"{kind}: {d['state']} bloquea en fresh (fresh es solo para "
                    "máquina limpia; con estado existente use --mode upgrade)")
        # Sin usuarios NO basta para ser fábrica: el SELLO del producto es
        # irreversible. Una base sellada y vaciada no es una instalación nueva
        # y /setup/admin no se va a reabrir (bootstrap.py): fresh no procede.
        if sello_nuevo or sello_legacy:
            block = True
            reasons.append(
                "auth: el sello de instalación (install_state) ya está puesto; "
                "esto no es una máquina limpia y /setup/admin no se reabre")

    return {
        "mode": mode,
        # INFORMATIVO: no gobierna nada. Ver la cabecera del módulo.
        "global_state": global_state,
        "per_kind": per,
        "decision": "BLOCK" if block else "PROCEED",
        "reasons": reasons,
        # FIRST_ADMIN_PENDING: primera release sin ningún usuario; el alta se
        # cede a /setup/admin (no la hace el instalador).
        # Se decide por ESTADO DEL PRODUCTO: sin usuarios y sin sello.
        "primer_admin_pendiente": (not block and mode == "fresh"
                                   and per["auth"]["state"] == "EMPTY_STATE"
                                   and not sello_nuevo and not sello_legacy),
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
