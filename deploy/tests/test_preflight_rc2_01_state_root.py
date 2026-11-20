# -*- coding: utf-8 -*-
"""RC2-01: `preflight.sh` no bloquea la PRIMERA instalacion por el state root ausente.

`deploy.sh --mode fresh` crea el state root; exigirlo antes bloqueaba justo el camino que la
guia manda seguir. Se ejecuta el bloque REAL de la seccion 10 del guion (extraido de su texto,
con `ok`/`avso`/`bloq` del propio guion), como hace `test_preflight_python_minimo.py`.

Contrato: sin state root NI instalacion previa -> aviso; con state root presente -> todo igual
que antes; con instalacion previa (o un objeto que no es directorio) y sin state root -> bloqueo.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PREFLIGHT = RAIZ / "deploy" / "scripts" / "preflight.sh"


def _bloque_estado() -> str:
    texto = PREFLIGHT.read_text(encoding="utf-8")
    m = re.search(r"^# 10\. .*?^# 11\. ", texto, re.S | re.M)
    assert m, "RC2-01: NO SE ENCONTRO LA SECCION 10 DEL PREFLIGHT"
    return m.group(0).rsplit("\n", 2)[0]


def _ejecuta(tmp_path: Path, *, entorno: str = "production", estado: str = "ausente",
             instalacion: str = "ninguna") -> str:
    s9k = tmp_path / "opt"
    state = tmp_path / "var-lib"
    s9k.mkdir()
    if instalacion == "current":
        (s9k / "releases" / "r1").mkdir(parents=True)
        (s9k / "current").symlink_to(s9k / "releases" / "r1")
    elif instalacion == "releases":
        (s9k / "releases" / "r1").mkdir(parents=True)
    elif instalacion == "releases-vacio":
        (s9k / "releases").mkdir()
    if estado == "directorio":
        state.mkdir()
    elif estado == "fichero":
        state.write_text("no soy un directorio", encoding="utf-8")
    elif estado == "enlace-roto":
        state.symlink_to(tmp_path / "no-existe")
    guion = (
        "log() { echo \"$*\"; }; err() { echo \"$*\"; }; warn() { echo \"$*\"; }\n"
        "warns=0; blocks=0\n"
        "ok()   { log \"OK   $*\"; }\n"
        "avso() { warn \"WARN $*\"; warns=$((warns + 1)); }\n"
        "bloq() { err  \"STOP $*\"; blocks=$((blocks + 1)); }\n"
        "servicio_cifra() { :; }\n"
        f"ENVIRONMENT='{entorno}'\n"
        f"S9K_ROOT='{s9k}'; S9K_STATE_ROOT='{state}'; S9K_CONFIG_ROOT='{tmp_path / 'etc'}'\n"
        + _bloque_estado() + "\necho \"BLOCKS=${blocks} WARNS=${warns}\"\n")
    r = subprocess.run(["bash", "-c", guion], capture_output=True, text=True,
                       env={**os.environ}, timeout=60)
    assert r.returncode == 0, "RC2-01: EL BLOQUE DEL GUION NO SE EJECUTA: %s" % r.stderr
    return r.stdout


def test_maquina_limpia_no_bloquea_y_lo_dice(tmp_path):
    out = _ejecuta(tmp_path)
    assert "BLOCKS=0" in out, "RC2-01: LA MAQUINA LIMPIA SIGUE BLOQUEADA: %s" % out
    assert "se creará en el despliegue" in out, "RC2-01: NO DICE QUE SE CREARA: %s" % out


def test_maquina_limpia_con_releases_vacio_no_bloquea(tmp_path):
    out = _ejecuta(tmp_path, instalacion="releases-vacio")
    assert "BLOCKS=0" in out, "RC2-01: LA MAQUINA LIMPIA SIGUE BLOQUEADA: %s" % out


def test_state_root_presente_se_comprueba_como_antes(tmp_path):
    out = _ejecuta(tmp_path, estado="directorio")
    assert "BLOCKS=0" in out and "OK   directorio de estado:" in out, \
        "RC2-01: CON STATE ROOT PRESENTE YA NO SE COMPRUEBA COMO ANTES: %s" % out
    assert "se creará en el despliegue" not in out, \
        "RC2-01: AVISA DE CREACION CON EL STATE ROOT PRESENTE: %s" % out


@pytest.mark.parametrize("instalacion", ["current", "releases"])
def test_instalacion_previa_sin_state_root_bloquea(tmp_path, instalacion):
    out = _ejecuta(tmp_path, instalacion=instalacion)
    assert "BLOCKS=1" in out and "STOP directorio de estado no existe" in out, \
        "RC2-01: INSTALACION PREVIA SIN STATE ROOT NO BLOQUEA: %s" % out


@pytest.mark.parametrize("estado", ["fichero", "enlace-roto"])
def test_state_root_que_no_es_directorio_bloquea(tmp_path, estado):
    out = _ejecuta(tmp_path, estado=estado)
    assert "BLOCKS=1" in out, "RC2-01: UN STATE ROOT QUE NO ES DIRECTORIO NO BLOQUEA: %s" % out


def test_el_laboratorio_conserva_su_aviso(tmp_path):
    out = _ejecuta(tmp_path, entorno="lab", instalacion="current")
    assert "BLOCKS=0" in out and "lab: se puede crear" in out, \
        "RC2-01: CAMBIO EL COMPORTAMIENTO DE LAB: %s" % out
