# -*- coding: utf-8 -*-
"""RC1-05 · el `decision=BLOCK` de detect_state se aplica en el paso 3, ANTES de parar (3b).

Defecto: `deploy.sh` calculaba `DECISION` en el paso 3 y no la aplicaba hasta el paso 4, despues
de `parar_y_verificar_servicios`: un BLOCK de pura deteccion dejaba visor y worker parados.
QUE SE EJECUTA: el texto REAL de los pasos 3-4 de `deploy.sh` (marcas unicas) con la identidad y
la PARADA sustituidas por un testigo que deja una marca. El mutante se aplica sobre una copia.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import detect_state as ds  # noqa: E402
from test_b2_fresh_install import (  # noqa: E402
    DEPLOY_SH, LIB_SH, VALIDATE_SH, _auth_de_producto, _corrupta)


def _tramo(texto: str, ini: str, fin: str) -> str:
    for m in (ini, fin):
        assert texto.count(m) == 1, f"DETECTOR ROTO: la marca {m!r} aparece {texto.count(m)} veces"
    a = texto.index(ini)
    return texto[a:texto.index(fin, a) + len(fin)]


def _correr(cuerpo: str):
    guion = "set -Eeuo pipefail\nsource %s\nsource %s\n%s\necho TRAMO_SUPERADO\n" % (LIB_SH, VALIDATE_SH, cuerpo)
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    r = subprocess.run(["bash", "-c", guion], capture_output=True, text=True, env=env, timeout=120)
    return r.returncode, r.stdout + r.stderr


def _tramo_3_a_4(texto: str = None) -> str:
    texto = texto if texto is not None else DEPLOY_SH.read_text(encoding="utf-8")
    return _tramo(texto, "# Paso 3: detectar layout/estado", "# --- fin del paso 4 ---")


def _paso3_4_con_testigo(tmp: Path, modo: str, new_auth: Path, new_jobs: Path, *, texto: str = None):
    """Paso 3-4 REAL; la identidad y la PARADA se sustituyen por un testigo que deja una marca."""
    marca = tmp / "MARCA_PARADA"
    cuerpo = """
HERE=%(here)s
MODE=%(modo)s
SERVICE_USER=usuario-de-prueba
asegurar_identidad_de_servicio() { :; }
parar_y_verificar_servicios() { echo PARADOS >> %(marca)s; }
LEGACY_AUTH_DB=%(la)s
LEGACY_JOBS_DB=%(lj)s
NEW_AUTH_DB=%(na)s
NEW_JOBS_DB=%(nj)s
detect_layout_report() {
    python3 "${HERE}/detect_state.py" \\
        --legacy-auth "${LEGACY_AUTH_DB}" --legacy-jobs "${LEGACY_JOBS_DB}" \\
        --new-auth "${NEW_AUTH_DB}" --new-jobs "${NEW_JOBS_DB}" --mode "${MODE}"
}
%(tramo)s
""" % {"here": _SCRIPTS, "modo": modo, "marca": marca, "la": tmp / "ln" / "auth.db", "lj": tmp / "ln" / "jobs.db",
       "na": new_auth, "nj": new_jobs, "tramo": _tramo_3_a_4(texto)}
    rc, out = _correr(cuerpo)
    return rc, out, marca.exists()


def test_RC105_B1_block_de_fresh_sobre_instalacion_con_usuarios_no_para_nada(tmp_path):
    """Esperado: rc != 0 «bloquea en fresh» y la parada NO se ejecuta (marca ausente)."""
    na = _auth_de_producto(tmp_path / "s/auth/auth.db", usuarios=1)
    rc, out, parado = _paso3_4_con_testigo(tmp_path, "fresh", na, tmp_path / "s/jobs/jobs.db")
    # La parada va PRIMERO: es la propiedad de RC1-05 y la causa que busca el calibrador.
    assert not parado, "RC1-05: LA PARADA OCURRIO ANTES DEL BLOCK: %s" % out
    assert rc != 0 and "bloquea en fresh" in out, "RC1-05: NO BLOQUEA EN FRESH: %s" % out
    assert "visor y worker siguen en marcha" in out, "RC1-05: EL STOP NO DICE QUE NADA SE HA PARADO: %s" % out


def test_RC105_B2_auth_corrupta_no_para_nada(tmp_path):
    """Esperado: rc != 0 con CORRUPT_STATE y sin parada."""
    na = _corrupta(tmp_path / "s/auth/auth.db")
    rc, out, parado = _paso3_4_con_testigo(tmp_path, "upgrade", na, tmp_path / "s/jobs/jobs.db")
    assert rc != 0 and "CORRUPT_STATE" in out and not parado, out


def test_RC105_B3_jobs_de_0_bytes_en_upgrade_no_para_nada(tmp_path):
    """Esperado: el caso de la RC (n16-vacia): jobs.db de 0 bytes -> BLOCK en el paso 3, sin parada."""
    na = _auth_de_producto(tmp_path / "s/auth/auth.db", usuarios=1)
    nj = tmp_path / "s/jobs/jobs.db"
    nj.parent.mkdir(parents=True)
    nj.write_bytes(b"")
    rc, out, parado = _paso3_4_con_testigo(tmp_path, "upgrade", na, nj)
    assert rc != 0 and "CORRUPT_STATE" in out and not parado, out


def test_RC105_C1_control_un_estado_que_procede_SI_para_y_sigue(tmp_path):
    """Esperado: rc 0, TRAMO_SUPERADO y la parada SE ejecuta (el gate no bloquea lo legitimo)."""
    na = _auth_de_producto(tmp_path / "s/auth/auth.db", usuarios=1)
    rc, out, parado = _paso3_4_con_testigo(tmp_path, "upgrade", na, tmp_path / "s/jobs/jobs.db")
    assert rc == 0 and "TRAMO_SUPERADO" in out and parado, out


def test_RC105_G1_el_paso_4_conserva_la_segunda_barrera():
    """Esperado: `paso4_migrar_o_validar_estado` sigue llamando a exigir_decision_de_estado."""
    lib = LIB_SH.read_text(encoding="utf-8")
    cuerpo = lib[lib.index("\npaso4_migrar_o_validar_estado() {"):]
    cuerpo = cuerpo[:cuerpo.index("\n}\n")]
    assert "exigir_decision_de_estado" in cuerpo


def test_RC105_Z0_cero_bytes_se_clasifica_hoy_CORRUPT_decision_pendiente(tmp_path):
    """CARACTERIZACION (no es un deseo): un jobs.db de 0 bytes es CORRUPT_STATE y BLOQUEA en upgrade
    (`migrate_sqlite.inspect_db`: «posible creacion vacia indebida»), mientras `deploy/README.md`
    (N16 / tabla de detect_state) dice «ausente o vacia no bloquea (H-43)». Este test fija el
    comportamiento ACTUAL para que cambiarlo sea una decision explicita, no un efecto lateral.
    Ver las dos opciones propuestas en la entrega."""
    nj = tmp_path / "jobs.db"
    nj.write_bytes(b"")
    r = ds.detect(None, None, str(_auth_de_producto(tmp_path / "a.db", usuarios=1)), str(nj), "upgrade")
    assert r["per_kind"]["jobs"]["state"] == "CORRUPT_STATE" and r["decision"] == "BLOCK", r


# ---------------------------------------------------------------------------
# Mutante
# ---------------------------------------------------------------------------
def test_RC105_M1_sin_el_gate_de_decision_la_parada_ocurre_antes_del_BLOCK(tmp_path):
    """Esperado: sin la llamada de paso 3 (el defecto RC1-05), el arnes ve la parada: B1 en rojo."""
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    mut = texto.replace('exigir_decision_de_estado "${STATE_JSON}" " — nada se ha parado ni tocado: visor y worker siguen en marcha"\n', "")
    assert mut != texto
    na = _auth_de_producto(tmp_path / "s/auth/auth.db", usuarios=1)
    _rc, _out, parado = _paso3_4_con_testigo(tmp_path, "fresh", na, tmp_path / "s/jobs/jobs.db", texto=mut)
    assert parado, "el mutante deberia dejar parar antes del BLOCK"


