#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_sqlite.py — migración controlada y atómica de una base SQLite legacy hacia
el state root externo (auth.db / jobs.db), preservando el estado real.

Diseño (continuidad de estado — corrección del despliegue RC1):
  - Modo PLAN por defecto: NO escribe nada. Requiere --apply Y --confirm para migrar.
  - Copia con `sqlite3 .backup` (consistente, no un simple cp) a un archivo temporal.
  - PRAGMA integrity_check sobre el temporal antes de aceptarlo.
  - Compara schema_version, nº de usuarios, nº de admins activos y nº de jobs entre
    origen y destino/temporal.
  - Rename atómico (os.replace) al destino final; permisos 0600.
  - Conserva la base legacy INTACTA (nunca la borra ni la modifica).
  - Idempotente: si el destino ya coincide con el origen (mismos conteos e
    integridad), no reescribe.
  - Rechaza symlinks y path traversal en origen y destino.
  - NUNCA imprime hashes de contraseña, tokens ni filas sensibles (solo conteos).

Uso:
  # Plan (sin cambios):
  migrate_sqlite.py --kind auth --src <legacy.db> --dst <state_root/auth/auth.db>
  # Aplicar (requiere ambas banderas):
  migrate_sqlite.py --kind auth --src <legacy.db> --dst <...> --apply --confirm

Salida: JSON con el plan/resultado (apto para logs y para el laboratorio).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Consultas de conteo por tipo de base (solo COUNT / versión; nunca filas)
# ---------------------------------------------------------------------------
_COUNTS = {
    "auth": {
        "schema_version": "SELECT COALESCE(MAX(version), 0) FROM schema_version",
        "users": "SELECT COUNT(*) FROM users",
        "active_admins": "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1",
    },
    "jobs": {
        "jobs": "SELECT COUNT(*) FROM jobs",
    },
}


def _resolve_safe(raw: str, must_exist: bool) -> Path:
    """Resuelve una ruta rechazando path traversal y symlinks."""
    p = Path(raw)
    if ".." in p.parts:
        raise ValueError(f"Path traversal detectado: {raw!r}")
    if p.is_symlink():
        raise ValueError(f"Ruta es un symlink (rechazada por seguridad): {raw!r}")
    if must_exist and not p.exists():
        raise FileNotFoundError(f"No existe: {raw!r}")
    return p


def _safe_count(conn: sqlite3.Connection, sql: str) -> Optional[int]:
    """Ejecuta un COUNT tolerando que la tabla no exista (base vacía/parcial)."""
    try:
        row = conn.execute(sql).fetchone()
        return int(row[0]) if row is not None else 0
    except sqlite3.OperationalError:
        return None  # tabla ausente


def inspect_db(path: Path, kind: str) -> dict[str, Any]:
    """Devuelve integridad + conteos de una base. Solo lectura."""
    info: dict[str, Any] = {"exists": path.exists(), "integrity": None, "counts": {}}
    if not path.exists():
        return info
    if path.stat().st_size == 0:
        # Fichero vacío: no es una base usable (posible "creación vacía" indebida).
        info["integrity"] = "empty"
        return info
    # Abrir en solo lectura (modo URI) para no crear ni tocar la base
    uri = f"file:{path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        info["integrity"] = "corrupt"
        return info
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        info["integrity"] = row[0] if row else "unknown"
        for label, sql in _COUNTS.get(kind, {}).items():
            info["counts"][label] = _safe_count(conn, sql)
    except sqlite3.DatabaseError:
        info["integrity"] = "corrupt"
        info["counts"] = {}
    finally:
        conn.close()
    return info


def _backup_to_temp(src: Path, tmp: Path) -> None:
    """Copia consistente src -> tmp usando la API .backup de SQLite."""
    src_uri = f"file:{src}?mode=ro"
    src_conn = sqlite3.connect(src_uri, uri=True)
    dst_conn = sqlite3.connect(str(tmp))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _counts_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a.get("counts") == b.get("counts")


def plan_or_apply(kind: str, src: Path, dst: Path, apply: bool, confirm: bool) -> dict[str, Any]:
    src = _resolve_safe(str(src), must_exist=True)
    dst = _resolve_safe(str(dst), must_exist=False)

    src_info = inspect_db(src, kind)
    dst_info = inspect_db(dst, kind)

    result: dict[str, Any] = {
        "kind": kind,
        "src": str(src),
        "dst": str(dst),
        "src_info": src_info,
        "dst_info_before": dst_info,
        "would_apply": bool(apply and confirm),
        "changed": False,
        "status": "PLAN",
    }

    # Gates de seguridad sobre el ORIGEN
    if src_info["integrity"] != "ok":
        result["status"] = "BLOCKED_SRC_CORRUPT"
        return result

    # Idempotencia: destino ya equivalente (existe, íntegro, mismos conteos)
    if dst_info["exists"] and dst_info["integrity"] == "ok" and _counts_match(src_info, dst_info):
        result["status"] = "ALREADY_DONE"
        result["idempotent"] = True
        return result

    # Conflicto: destino existe con conteos distintos (no sobrescribir en silencio)
    if dst_info["exists"] and not _counts_match(src_info, dst_info):
        result["status"] = "BLOCKED_DST_CONFLICT"
        return result

    if not (apply and confirm):
        result["status"] = "PLAN"  # sin cambios
        return result

    # --- APLICAR: backup a temporal, verificar, rename atómico ---
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".migrate-", dir=str(dst.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        _backup_to_temp(src, tmp)
        tmp_info = inspect_db(tmp, kind)
        if tmp_info["integrity"] != "ok":
            result["status"] = "FAILED_TEMP_CORRUPT"
            return result
        if not _counts_match(src_info, tmp_info):
            result["status"] = "FAILED_COUNT_MISMATCH"
            result["tmp_info"] = tmp_info
            return result
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        os.replace(tmp, dst)  # atómico dentro del mismo filesystem
        tmp = None  # ya movido
        result["changed"] = True
        result["status"] = "MIGRATED"
        result["dst_info_after"] = inspect_db(dst, kind)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()
    return result


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", required=True, choices=sorted(_COUNTS.keys()))
    ap.add_argument("--src", required=True, help="Base SQLite legacy (origen)")
    ap.add_argument("--dst", required=True, help="Destino en el state root")
    ap.add_argument("--apply", action="store_true", help="Aplicar (requiere --confirm)")
    ap.add_argument("--confirm", action="store_true", help="Confirmación explícita de escritura")
    args = ap.parse_args(argv)
    try:
        result = plan_or_apply(args.kind, Path(args.src), Path(args.dst), args.apply, args.confirm)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"status": "ERROR", "error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Códigos: 0 OK/plan; 3 bloqueado; 4 fallo de migración
    if result["status"].startswith("BLOCKED"):
        return 3
    if result["status"].startswith("FAILED"):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
