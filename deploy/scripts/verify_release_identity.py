#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_release_identity.py — confirma que el PROCESO VIVO ejecuta la release
autorizada, no que baste con haber cambiado el symlink `current` (corrección RC1).

Comprueba:
  - manifest.json de la release activa: release_id, git_commit, schema_versions.
  - Que `current` apunta a la release esperada (--expected-release / --expected-commit).
  - Para el PID del servicio (o --pid): /proc/<pid>/cwd resuelto cae bajo la release
    activa; el ejecutable Python (/proc/<pid>/exe) pertenece al .venv de current;
    y, cuando es viable, alguna ruta de módulo cargado cuelga de current.

No basta con que el symlink haya cambiado: si el proceso sigue con el CWD/venv del
layout legacy, se reporta MISMATCH.

Uso:
  verify_release_identity.py --root /opt/s9-knowledge \
      [--expected-release <id>] [--expected-commit <sha>] \
      [--pid <pid> | --unit s9-knowledge-viewer.service]

Salida: JSON con checks y veredicto. Código: 0 OK; 1 MISMATCH; 2 error de entrada.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


def _load_manifest(release_dir: Path) -> Optional[dict[str, Any]]:
    mf = release_dir / "manifest.json"
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _pid_from_unit(unit: str) -> Optional[int]:
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "MainPID", "--value", unit],
            capture_output=True, text=True, timeout=10,
        )
        pid = int(out.stdout.strip() or "0")
        return pid or None
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return None


def _proc_link(pid: int, name: str) -> Optional[str]:
    try:
        return os.readlink(f"/proc/{pid}/{name}")
    except OSError:
        return None


def verify(
    root: Path, expected_release: Optional[str], expected_commit: Optional[str],
    pid: Optional[int], unit: Optional[str],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    current = root / "current"
    active_dir = Path(os.path.realpath(current)) if current.exists() else None
    active_id = active_dir.name if active_dir else None
    add("current_is_symlink", current.is_symlink(), str(current))
    add("current_resolves", active_dir is not None, str(active_dir))

    manifest = _load_manifest(active_dir) if active_dir else None
    add("manifest_present", manifest is not None, str(active_dir))
    if manifest:
        if expected_release:
            add("release_id_matches", manifest.get("release_id") == expected_release,
                f"{manifest.get('release_id')} vs {expected_release}")
        if expected_commit:
            mc = str(manifest.get("git_commit", ""))
            add("git_commit_matches", mc.startswith(expected_commit) or expected_commit.startswith(mc),
                f"{mc} vs {expected_commit}")
        add("schema_versions_present", bool(manifest.get("schema_versions")),
            json.dumps(manifest.get("schema_versions")))

    if expected_release and active_id:
        add("active_is_expected_release", active_id == expected_release,
            f"{active_id} vs {expected_release}")

    # --- proceso vivo ---
    if pid is None and unit:
        pid = _pid_from_unit(unit)
    if pid:
        cwd = _proc_link(pid, "cwd")
        exe = _proc_link(pid, "exe")
        add("pid_alive", cwd is not None, f"pid={pid}")
        if active_dir and cwd:
            add("proc_cwd_under_current", os.path.realpath(cwd).startswith(str(active_dir)),
                f"cwd={cwd}")
        if active_dir and exe:
            venv = str(active_dir / "viewer" / ".venv")
            add("proc_python_under_current_venv", os.path.realpath(exe).startswith(os.path.realpath(venv)),
                f"exe={exe}")
        # rutas de módulos cargados (best-effort, si el mapa es legible)
        try:
            maps = Path(f"/proc/{pid}/maps").read_text()
            uses_current = active_dir is not None and str(active_dir) in maps
            uses_legacy = "/opt/knowledge-services/s9-knowledge-repo" in maps
            add("modules_reference_current", uses_current and not uses_legacy,
                f"current={uses_current} legacy={uses_legacy}")
        except OSError:
            pass  # no siempre legible; no bloquea
    else:
        add("pid_alive", False, "no se pudo determinar el PID del servicio")

    verdict = "OK" if all(c["ok"] for c in checks) else "MISMATCH"
    return {"root": str(root), "active_release": active_id, "verdict": verdict, "checks": checks}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=os.environ.get("S9K_ROOT", "/opt/s9-knowledge"))
    ap.add_argument("--expected-release")
    ap.add_argument("--expected-commit")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--unit", default="s9-knowledge-viewer.service")
    args = ap.parse_args(argv)
    result = verify(Path(args.root), args.expected_release, args.expected_commit, args.pid, args.unit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
