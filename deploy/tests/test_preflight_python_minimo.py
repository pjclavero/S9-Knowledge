# -*- coding: utf-8 -*-
"""preflight.sh: el minimo de Python es la TUPLA 3.12.0 que exige el lock del motor.

`data-engine/requirements.lock` fija numpy 2.5.1 (`requires_python` >= 3.12) y soupsieve 4.0
(>= 3.11.5). El preflight comparaba solo major.minor (3.11+) y despues declaro 3.11.5: un host
con 3.11.x pasaba el preflight y fallaba despues en `pip install`. El gate D6 lo detecto al
comparar la tupla completa contra el mayor Requires-Python de los locks. Se ejecuta el bloque REAL del guion (extraido de su texto, con sus
`ok`/`bloq`) contra un `python3` simulado que solo cambia `sys.version_info`.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PREFLIGHT = RAIZ / "deploy" / "scripts" / "preflight.sh"
LOCK = RAIZ / "data-engine" / "requirements.lock"


def _bloque_python() -> str:
    texto = PREFLIGHT.read_text(encoding="utf-8")
    m = re.search(r"^# 2\. Python.*?^# 3\. ", texto, re.S | re.M)
    assert m, "no se encontro el bloque de Python del preflight"
    return m.group(0).rsplit("\n", 2)[0]


def _python_simulado(tmp_path: Path, version: str) -> Path:
    """`python3` que ejecuta el codigo de `-c` con el python real y `sys.version_info` = version."""
    d = tmp_path / "bin"
    d.mkdir()
    shim = d / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "-c" ] || exec "%s" "$@"\n'
        'codigo="$2"; shift 2\n'
        'exec "%s" -c \'import sys; v = tuple(int(x) for x in "%s".split(".")); '
        'sys.version_info = v + ("final", 0); c = sys.argv[1]; sys.argv = ["-c"] + sys.argv[2:]; '
        'exec(compile(c, "<preflight>", "exec"))\' "$codigo" "$@"\n'
        % (sys.executable, sys.executable, version), encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return d


def _ejecuta(tmp_path: Path, version: str):
    guion = (
        "log() { echo \"$*\"; }; err() { echo \"$*\"; }; warns=0; blocks=0\n"
        "ok()   { log \"OK   $*\"; }\n"
        "bloq() { err  \"STOP $*\"; blocks=$((blocks + 1)); }\n"
        + _bloque_python() + "\necho \"BLOCKS=${blocks}\"\n")
    env = {**os.environ, "PATH": "%s:%s" % (_python_simulado(tmp_path, version), os.environ["PATH"])}
    return subprocess.run(["bash", "-c", guion], capture_output=True, text=True, env=env, timeout=60)


@pytest.mark.parametrize("version,pasa", [
    ("3.11.2", False), ("3.11.5", False), ("3.10.14", False),
    ("3.12.0", True), ("3.12.7", True), ("3.13.5", True),
])
def test_el_preflight_exige_python_3_12_0_por_tupla(tmp_path, version, pasa):
    r = _ejecuta(tmp_path, version)
    assert r.returncode == 0, r.stderr
    if pasa:
        assert "BLOCKS=0" in r.stdout and ("OK   Python %s" % version) in r.stdout, r.stdout
    else:
        assert "BLOCKS=1" in r.stdout, "PYTHON %s PASA EL PREFLIGHT: %s" % (version, r.stdout)
        linea = [l for l in r.stdout.splitlines() if l.startswith("STOP Python")][0]
        # dice la version encontrada, la exigida y POR QUE (el lock del motor)
        assert version in linea and "3.12.0" in linea and "requirements.lock" in linea, linea


def test_el_minimo_del_preflight_cubre_el_requires_python_del_lock():
    """El minimo declarado en el preflight no puede ser menor que el que exigen numpy y soupsieve
    del lock (la comparacion completa contra TODOS los paquetes la hace el gate D6 en CI)."""
    m = re.search(r'^PY_MINIMO="(\d+)\.(\d+)\.(\d+)"', PREFLIGHT.read_text(encoding="utf-8"), re.M)
    assert m, "el preflight no declara PY_MINIMO"
    minimo = tuple(int(x) for x in m.groups())
    sv = re.search(r"^soupsieve==(\d+)", LOCK.read_text(encoding="utf-8"), re.M)
    if sv and int(sv.group(1)) >= 3:
        assert minimo >= (3, 11, 5), minimo
    np = re.search(r"^numpy==(\d+)\.(\d+)", LOCK.read_text(encoding="utf-8"), re.M)
    if np and (int(np.group(1)), int(np.group(2))) >= (2, 5):
        assert minimo >= (3, 12, 0), minimo
