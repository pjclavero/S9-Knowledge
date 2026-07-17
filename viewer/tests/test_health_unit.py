# -*- coding: utf-8 -*-
"""Tests de las unidades systemd del healthcheck.

Motivo: tras desplegar RC2 la unidad seguia apuntando al layout legacy
(/opt/knowledge-services/s9-knowledge-repo), asi que habria ejecutado codigo y
configuracion equivocados si se hubiera activado el timer.
"""
from __future__ import annotations

import configparser
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parents[1] / "systemd"
SERVICE = UNITS / "s9-knowledge-healthcheck.service"
TIMER = UNITS / "s9-knowledge-healthcheck.timer"

LEGACY_ROOT = "/opt/knowledge-services"
CURRENT = "/opt/s9-knowledge/current"


def _parse(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False)
    cp.optionxform = str          # systemd distingue mayusculas
    cp.read_string(path.read_text(encoding="utf-8"))
    return cp


@pytest.mark.parametrize("unit", [SERVICE, TIMER], ids=["service", "timer"])
def test_sin_rutas_legacy(unit):
    """LA REGRESION: ni una sola referencia al layout legacy, ni en comentarios."""
    assert LEGACY_ROOT not in unit.read_text(encoding="utf-8")


def test_working_directory_bajo_current():
    cp = _parse(SERVICE)
    wd = cp["Service"]["WorkingDirectory"]
    assert wd.startswith(CURRENT), wd


def test_environment_file_es_el_productivo():
    cp = _parse(SERVICE)
    assert cp["Service"]["EnvironmentFile"] == "/etc/s9-knowledge/viewer.env"


def test_execstart_usa_el_venv_de_current():
    cp = _parse(SERVICE)
    exec_start = cp["Service"]["ExecStart"]
    assert exec_start.startswith(f"{CURRENT}/viewer/.venv/bin/python"), exec_start
    assert "app.cli.health" in exec_start


def test_es_oneshot_con_umask_restrictivo():
    cp = _parse(SERVICE)
    assert cp["Service"]["Type"] == "oneshot"
    assert cp["Service"]["UMask"] == "0077"


def test_no_puede_quedarse_colgada():
    """Sin timeout, una ejecucion colgada bloquearia todos los disparos."""
    cp = _parse(SERVICE)
    assert "TimeoutStartSec" in cp["Service"]


def test_asserts_de_prerrequisitos():
    """Si falta `current` o el env, la unidad no debe arrancar a ciegas."""
    text = SERVICE.read_text(encoding="utf-8")
    assert f"AssertPathExists={CURRENT}/viewer" in text
    assert "AssertPathExists=/etc/s9-knowledge/viewer.env" in text


def test_contencion_del_sandbox():
    cp = _parse(SERVICE)
    svc = cp["Service"]
    assert svc["ProtectSystem"] == "strict"
    assert svc["NoNewPrivileges"] == "true"
    assert svc["CapabilityBoundingSet"] == ""
    # /opt y /etc en solo lectura: la unidad no puede reescribir la release.
    assert CURRENT.split("/current")[0] in svc["ReadOnlyPaths"]
    assert "/etc/s9-knowledge" in svc["ReadOnlyPaths"]


def test_el_estado_es_el_unico_escribible():
    """No debe poder escribir fuera de /var/lib/s9-knowledge."""
    cp = _parse(SERVICE)
    rw = cp["Service"]["ReadWritePaths"].split()
    assert rw == ["/var/lib/s9-knowledge"], rw


def test_timer_apunta_al_servicio_correcto():
    cp = _parse(TIMER)
    assert cp["Timer"]["Unit"] == "s9-knowledge-healthcheck.service"


def test_timer_no_se_solapa():
    """OnUnitActiveSec cuenta desde la ultima activacion: sin solape."""
    cp = _parse(TIMER)
    assert "OnUnitActiveSec" in cp["Timer"]
    assert "OnCalendar" not in cp["Timer"]


def test_exitos_aceptados_reflejan_los_estados():
    """0 healthy y 1 degraded son ejecuciones correctas; 2 y 3 no."""
    cp = _parse(SERVICE)
    assert cp["Service"]["SuccessExitStatus"] == "0 1"
