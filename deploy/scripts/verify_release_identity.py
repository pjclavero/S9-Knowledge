#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_release_identity.py — confirma que el PROCESO VIVO ejecuta la release
autorizada. Cambiar el symlink `current` no basta: si el proceso sigue con el
CWD, el venv o los módulos del layout legacy, la identidad es INVALID.

Un venv creado con symlinks (el modo por omisión de `python -m venv`) hace que
/proc/<pid>/exe resuelva SIEMPRE al intérprete del sistema. Eso no es un fallo:
es la semántica normal del venv. Por eso la identidad no se decide con /proc/exe,
sino con la conjunción de varios indicadores.

Indicadores (críticos salvo donde se indica):
  - current apunta a la release esperada
  - manifest release_id correcto
  - manifest git_commit correcto
  - /proc/<pid>/cwd dentro de la release
  - cmdline usa el entrypoint del venv de la release
  - intérprete: dentro del venv, o la base declarada por su pyvenv.cfg
  - módulos de la aplicación cargados desde la release
  - ausencia de módulos del layout legacy
  - EnvironmentFile correcto (informativo)
  - schema_versions presentes (informativo)

Veredictos:
  VALID
      todos los indicadores críticos pasan y el intérprete está dentro del venv.
  VALID_WITH_SYSTEM_INTERPRETER_SYMLINK
      todos los indicadores críticos pasan, pero /proc/exe resuelve al intérprete
      del sistema PORQUE es la base declarada en el pyvenv.cfg del venv esperado.
      No se acepta un /usr/bin/python cualquiera: debe ser esa base exacta, y
      cmdline, cwd y módulos deben demostrar el uso del venv y de la release.
  INVALID
      cwd legacy, módulos legacy, commit distinto, manifest distinto, current
      incorrecto, intérprete ajeno al venv esperado o mezcla de releases.
  UNKNOWN
      no se puede determinar (PID inexistente, /proc ilegible por permisos).

Uso:
  verify_release_identity.py --root /opt/s9-knowledge \
      [--expected-release <id>] [--expected-commit <sha>] \
      [--pid <pid> | --unit s9-knowledge-viewer.service] \
      [--legacy-root /opt/knowledge-services/s9-knowledge-repo]

Salida: JSON con indicadores y veredicto.
Códigos: 0 VALID / VALID_WITH_SYSTEM_INTERPRETER_SYMLINK · 1 INVALID · 2 UNKNOWN.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

DEFAULT_LEGACY_ROOT = "/opt/knowledge-services/s9-knowledge-repo"

VERDICT_VALID = "VALID"
VERDICT_VALID_SYMLINK = "VALID_WITH_SYSTEM_INTERPRETER_SYMLINK"
VERDICT_INVALID = "INVALID"
VERDICT_UNKNOWN = "UNKNOWN"

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNKNOWN = 2


# ---------------------------------------------------------------------------
# Hechos observados (separados de la lógica para poder testear sin /proc real)
# ---------------------------------------------------------------------------

@dataclass
class ProcessFacts:
    """Lo que se observa del proceso vivo. `None` = no observable."""
    pid: Optional[int] = None
    alive: bool = False
    cwd: Optional[str] = None            # ya resuelto (realpath)
    exe: Optional[str] = None            # ya resuelto (realpath)
    cmdline: list[str] = field(default_factory=list)
    module_paths: list[str] = field(default_factory=list)
    environ_file: Optional[str] = None
    proc_readable: bool = True           # False => permisos insuficientes


@dataclass
class ReleaseFacts:
    """Lo que se observa del layout en disco."""
    current_is_symlink: bool = False
    active_dir: Optional[str] = None     # ya resuelto (realpath)
    active_id: Optional[str] = None
    manifest: Optional[dict[str, Any]] = None
    venv_dir: Optional[str] = None       # ya resuelto (realpath)
    venv_base_interpreter: Optional[str] = None  # de pyvenv.cfg, ya resuelto


# ---------------------------------------------------------------------------
# Lectura del disco
# ---------------------------------------------------------------------------

def _read_manifest(release_dir: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _venv_base_interpreter(venv_dir: Path) -> Optional[str]:
    """Intérprete base declarado por el pyvenv.cfg del venv.

    Es la única forma honesta de saber a qué python DEBE resolver /proc/exe
    cuando el venv usa symlinks. Sin esto habría que aceptar cualquier python
    del sistema, que es justo lo que no queremos.
    """
    cfg = venv_dir / "pyvenv.cfg"
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return None
    home = None
    base_exe = None
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key == "base-executable":     # lo escriben las versiones recientes
            base_exe = value
        elif key == "home":
            home = value
    if base_exe:
        return os.path.realpath(base_exe)
    if not home:
        return None
    # Sin base-executable: deducirlo del symlink del propio venv.
    for name in ("python3", "python"):
        p = venv_dir / "bin" / name
        if p.exists():
            resolved = os.path.realpath(p)
            if resolved.startswith(os.path.realpath(home)):
                return resolved
    return None


def gather_release_facts(root: Path) -> ReleaseFacts:
    facts = ReleaseFacts()
    current = root / "current"
    facts.current_is_symlink = current.is_symlink()
    if not current.exists():
        return facts
    active = Path(os.path.realpath(current))
    facts.active_dir = str(active)
    facts.active_id = active.name
    facts.manifest = _read_manifest(active)
    venv = active / "viewer" / ".venv"
    if venv.exists():
        facts.venv_dir = os.path.realpath(venv)
        facts.venv_base_interpreter = _venv_base_interpreter(venv)
    return facts


# ---------------------------------------------------------------------------
# Lectura de /proc
# ---------------------------------------------------------------------------

def _pid_from_unit(unit: str) -> Optional[int]:
    try:
        out = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", unit],
                             capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip() or "0") or None
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return None


def _environment_file_from_unit(unit: str) -> Optional[str]:
    try:
        out = subprocess.run(["systemctl", "show", "-p", "EnvironmentFiles", "--value", unit],
                             capture_output=True, text=True, timeout=10)
        value = out.stdout.strip()
        # formato: "/ruta/al/fichero (ignore_errors=no)"
        return value.split(" ")[0] or None if value else None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def gather_process_facts(pid: Optional[int], unit: Optional[str]) -> ProcessFacts:
    if pid is None and unit:
        pid = _pid_from_unit(unit)
    facts = ProcessFacts(pid=pid)
    if not pid:
        return facts
    if not Path(f"/proc/{pid}").exists():
        return facts
    facts.alive = True
    try:
        facts.cwd = os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
        facts.exe = os.path.realpath(os.readlink(f"/proc/{pid}/exe"))
    except PermissionError:
        facts.proc_readable = False
        return facts
    except OSError:
        facts.alive = False
        return facts
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        facts.cmdline = [a for a in raw.decode("utf-8", "replace").split("\0") if a]
    except OSError:
        facts.proc_readable = False
    try:
        maps = Path(f"/proc/{pid}/maps").read_text()
        paths = set()
        for line in maps.splitlines():
            parts = line.split(None, 5)
            if len(parts) == 6 and parts[5].startswith("/"):
                paths.add(parts[5])
        facts.module_paths = sorted(paths)
    except OSError:
        facts.proc_readable = False
    if unit:
        facts.environ_file = _environment_file_from_unit(unit)
    return facts


# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------

def _resolve_dir_keep_name(path: Optional[str]) -> Optional[str]:
    """Resuelve el directorio contenedor pero NO el propio binario.

    Necesario por dos motivos simultáneos:
      - el entrypoint llega por `current/...`, symlink que sí hay que resolver;
      - `.venv/bin/python3` es a su vez un symlink al python del sistema, y
        resolverlo borraría justo la prueba de que se ejecuta desde el venv.
    """
    if not path:
        return None
    p = Path(path)
    try:
        return str(Path(os.path.realpath(p.parent)) / p.name)
    except OSError:
        return path


def _under(path: Optional[str], root: Optional[str]) -> bool:
    """True si `path` cuelga de `root`. Compara por componentes: evita que
    /opt/s9-knowledge/releases/X-old case con /opt/s9-knowledge/releases/X."""
    if not path or not root:
        return False
    try:
        Path(path).relative_to(Path(root))
        return True
    except ValueError:
        return False


def classify(
    release: ReleaseFacts,
    proc: ProcessFacts,
    expected_release: Optional[str] = None,
    expected_commit: Optional[str] = None,
    legacy_root: str = DEFAULT_LEGACY_ROOT,
) -> dict[str, Any]:
    indicators: list[dict[str, Any]] = []

    def add(name: str, ok: Optional[bool], detail: str, critical: bool = True) -> None:
        indicators.append({"indicator": name, "ok": ok, "critical": critical, "detail": detail})

    # --- estado del layout ---
    add("current_is_symlink", release.current_is_symlink, str(release.active_dir), critical=False)
    add("current_resolves", release.active_dir is not None, str(release.active_dir))
    add("manifest_present", release.manifest is not None, str(release.active_dir))

    if expected_release:
        add("active_is_expected_release", release.active_id == expected_release,
            f"{release.active_id} vs {expected_release}")
    if release.manifest is not None:
        if expected_release:
            add("manifest_release_id", release.manifest.get("release_id") == expected_release,
                f"{release.manifest.get('release_id')} vs {expected_release}")
        if expected_commit:
            mc = str(release.manifest.get("git_commit", ""))
            # El encargo circula a veces con el sha truncado: prefijo por cualquier lado.
            matches = bool(mc) and (mc.startswith(expected_commit) or expected_commit.startswith(mc))
            add("manifest_git_commit", matches, f"{mc} vs {expected_commit}")
        add("schema_versions_present", bool(release.manifest.get("schema_versions")),
            json.dumps(release.manifest.get("schema_versions")), critical=False)

    # --- proceso ---
    if not proc.alive:
        add("process_alive", False, f"pid={proc.pid}: no existe o no se pudo determinar")
        return _verdict(indicators, unknown=True, reason="proceso no observable")
    add("process_alive", True, f"pid={proc.pid}")

    if not proc.proc_readable:
        add("proc_readable", False, f"pid={proc.pid}: /proc ilegible (permisos insuficientes)")
        return _verdict(indicators, unknown=True, reason="/proc ilegible")
    add("proc_readable", True, "ok", critical=False)

    # cwd dentro de la release (y no en legacy)
    cwd_ok = _under(proc.cwd, release.active_dir)
    add("proc_cwd_under_release", cwd_ok, f"cwd={proc.cwd}")
    add("proc_cwd_not_legacy", not _under(proc.cwd, legacy_root), f"cwd={proc.cwd}")

    # cmdline: el entrypoint debe salir del venv de la release
    # Basta con que alguno de los dos primeros argumentos salga del venv: systemd
    # arranca `<venv>/bin/python3 <venv>/bin/uvicorn ...`, y el segundo llega por
    # la ruta de `current`.
    entry_candidates = [_resolve_dir_keep_name(a) for a in proc.cmdline[:2]]
    add("cmdline_entrypoint_in_venv",
        any(_under(c, release.venv_dir) for c in entry_candidates),
        f"cmdline[:2]={proc.cmdline[:2]} -> {entry_candidates}")

    # módulos: alguno de la release, ninguno del legacy
    from_release = [p for p in proc.module_paths if _under(p, release.active_dir)]
    from_legacy = [p for p in proc.module_paths if _under(p, legacy_root)]
    other_releases = []
    if release.active_dir:
        releases_root = str(Path(release.active_dir).parent)
        other_releases = [
            p for p in proc.module_paths
            if _under(p, releases_root) and not _under(p, release.active_dir)
        ]
    add("modules_from_release", bool(from_release),
        f"{len(from_release)} rutas bajo la release")
    add("modules_not_legacy", not from_legacy,
        f"{len(from_legacy)} rutas bajo {legacy_root}")
    add("modules_not_mixed", not other_releases,
        f"{len(other_releases)} rutas de OTRA release: {other_releases[:3]}")

    # intérprete
    interp_in_venv = _under(proc.exe, release.venv_dir)
    is_venv_base = (
        release.venv_base_interpreter is not None
        and proc.exe == release.venv_base_interpreter
    )
    if interp_in_venv:
        add("interpreter_identity", True, f"exe={proc.exe} (dentro del venv, modo --copies)")
    elif is_venv_base:
        # Correcto y esperado con venv por symlinks. No es "cualquier python":
        # es exactamente la base que declara el pyvenv.cfg de ESTE venv.
        add("interpreter_identity", True,
            f"exe={proc.exe} (base declarada por el pyvenv.cfg del venv esperado)")
    else:
        add("interpreter_identity", False,
            f"exe={proc.exe} ajeno al venv {release.venv_dir} "
            f"(base esperada: {release.venv_base_interpreter})")

    # EnvironmentFile (informativo: no todo despliegue lo expone)
    if proc.environ_file is not None:
        add("environment_file", proc.environ_file == "/etc/s9-knowledge/viewer.env",
            f"EnvironmentFile={proc.environ_file}", critical=False)

    return _verdict(indicators, symlink_interpreter=(not interp_in_venv and is_venv_base))


def _verdict(indicators: list[dict[str, Any]], symlink_interpreter: bool = False,
             unknown: bool = False, reason: str = "") -> dict[str, Any]:
    failed = [i["indicator"] for i in indicators if i["critical"] and i["ok"] is False]
    if unknown:
        verdict = VERDICT_UNKNOWN
    elif failed:
        verdict = VERDICT_INVALID
    elif symlink_interpreter:
        verdict = VERDICT_VALID_SYMLINK
    else:
        verdict = VERDICT_VALID
    out: dict[str, Any] = {"verdict": verdict, "failed_indicators": failed,
                           "indicators": indicators}
    if reason:
        out["reason"] = reason
    return out


def verdict_exit_code(verdict: str) -> int:
    if verdict in (VERDICT_VALID, VERDICT_VALID_SYMLINK):
        return EXIT_OK
    if verdict == VERDICT_INVALID:
        return EXIT_INVALID
    return EXIT_UNKNOWN


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Verifica la identidad del proceso vivo.")
    ap.add_argument("--root", default=os.environ.get("S9K_ROOT", "/opt/s9-knowledge"))
    ap.add_argument("--expected-release")
    ap.add_argument("--expected-commit")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--unit", default="s9-knowledge-viewer.service")
    ap.add_argument("--legacy-root", default=DEFAULT_LEGACY_ROOT)
    args = ap.parse_args(argv)

    release = gather_release_facts(Path(args.root))
    proc = gather_process_facts(args.pid, args.unit)
    result = classify(release, proc, args.expected_release, args.expected_commit,
                      args.legacy_root)
    result["root"] = str(args.root)
    result["active_release"] = release.active_id
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return verdict_exit_code(result["verdict"])


if __name__ == "__main__":
    raise SystemExit(main())
