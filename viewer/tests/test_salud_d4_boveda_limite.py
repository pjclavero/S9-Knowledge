# -*- coding: utf-8 -*-
"""D-4 (P3) · limites del diagnostico de la boveda basado en `os.access`.

(a) un montaje de red caido NO cuelga el health: el sondeo tiene tiempo maximo y, al agotarlo,
    informa UNAVAILABLE con el motivo «sin respuesta en N s» (nunca UNHEALTHY; opcional);
(b) el mensaje de AVAILABLE no afirma mas de lo medido: es permiso efectivo (`os.access`), NO una
    escritura probada (la sonda de escritura esta prohibida por contrato en la boveda).
"""
from __future__ import annotations

import threading
import time

import pytest


@pytest.fixture
def boveda(tmp_path):
    raiz = tmp_path / "bovedas"
    juego = raiz / "l5r"
    juego.mkdir(parents=True)
    (juego / "perfil-operador.json").write_text('{"workspace": "leyenda"}', encoding="utf-8")
    return raiz


@pytest.fixture
def montaje_colgado(monkeypatch):
    """`vault_mount.inspeccionar` se bloquea (como un `stat` sobre un NFS caido) hasta soltarlo."""
    from app import vault_mount

    suelta = threading.Event()
    real = vault_mount.inspeccionar

    def colgada(*a, **k):
        suelta.wait(30)
        return real(*a, **k)

    monkeypatch.setattr(vault_mount, "inspeccionar", colgada)
    yield suelta
    suelta.set()
    for h in threading.enumerate():
        if h.name == "s9k-vault-probe":
            h.join(5)


def test_D4a_un_montaje_colgado_no_cuelga_el_health_y_dice_sin_respuesta(boveda, montaje_colgado):
    from app.health import checks
    from app.health.models import HealthStatus

    t0 = time.monotonic()
    r = checks.check_vault(str(boveda), "0", timeout=0.4)
    dt = time.monotonic() - t0
    assert dt < 5, "D-4: EL SONDEO DE LA BOVEDA COLGO EL HEALTH (%.1f s)" % dt
    assert r.details["vault"] == checks.VAULT_UNAVAILABLE, r.message
    assert "sin respuesta en 0.4 s" in r.message, r.message
    assert r.status == HealthStatus.DEGRADED, "UNAVAILABLE de una dependencia opcional no es UNHEALTHY"


def test_D4a_no_se_acumulan_hilos_mientras_el_montaje_sigue_colgado(boveda, montaje_colgado):
    from app.health import checks

    checks.check_vault(str(boveda), "0", timeout=0.2)
    t0 = time.monotonic()
    r = checks.check_vault(str(boveda), "0", timeout=30)  # no debe esperar: ya hay uno en vuelo
    assert time.monotonic() - t0 < 2, "D-4: SE LANZO OTRO SONDEO SOBRE UN MONTAJE COLGADO"
    assert "sondeo anterior" in r.message and r.details["vault"] == checks.VAULT_UNAVAILABLE, r.message
    vivos = [h for h in threading.enumerate() if h.name == "s9k-vault-probe" and h.is_alive()]
    assert len(vivos) == 1, vivos


def test_D4a_cuando_el_montaje_responde_de_nuevo_vuelve_a_medir(boveda, montaje_colgado):
    from app.health import checks

    checks.check_vault(str(boveda), "0", timeout=0.2)
    montaje_colgado.set()
    for h in threading.enumerate():
        if h.name == "s9k-vault-probe":
            h.join(5)
    r = checks.check_vault(str(boveda), "0")
    assert r.details["vault"] == checks.VAULT_AVAILABLE, r.message


def test_D4a_el_sondeo_normal_no_depende_del_limite(boveda):
    from app.health import checks

    r = checks.check_vault(str(boveda), "0", timeout=5)
    assert r.details["vault"] == checks.VAULT_AVAILABLE and r.status.value == "HEALTHY", r.message


def test_D4b_AVAILABLE_no_afirma_una_escritura_que_no_se_ha_probado(boveda):
    from app.health import checks

    r = checks.check_vault(str(boveda), "0")
    assert r.details["vault"] == checks.VAULT_AVAILABLE
    assert "segun permisos" in r.message and "no se ha probado una escritura" in r.message, \
        "D-4: AVAILABLE AFIRMA MAS DE LO MEDIDO: %s" % r.message
    (boveda / "l5r" / "perfil-operador.json").unlink()
    r2 = checks.check_vault(str(boveda), "0")
    assert "segun permisos" in r2.details["motivo"] or "segun permisos" in r2.details["carpetas"]["l5r"], r2.details


def test_D4b_el_sondeo_no_crea_nada_en_la_boveda(boveda):
    from app.health import checks

    antes = sorted(p.relative_to(boveda).as_posix() for p in boveda.rglob("*"))
    checks.check_vault(str(boveda), "0")
    assert sorted(p.relative_to(boveda).as_posix() for p in boveda.rglob("*")) == antes
