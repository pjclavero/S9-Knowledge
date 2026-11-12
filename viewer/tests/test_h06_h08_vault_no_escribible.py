# -*- coding: utf-8 -*-
"""H-06/H-08 fase 2b · BOVEDA = EXTERNAL OPERATOR CONTENT (quinta categoria del inventario).

`S9K_VAULT_ROOT` y `perfil-operador.json` son contenido del operador, FUERA del state root.
La aplicacion escribe SOLO si el sistema de ficheros ya concede permiso al usuario de servicio:
nunca chown/chmod, nunca fallback ni copia bajo el STATE, nunca root. Si no puede: error
CONTROLADO y ESPECIFICO («perfil-operador.json no es escribible por el usuario s9knowledge»),
SIN cambios parciales, y la boveda no escribible NO impide arrancar.

P1 · N1 · N2 · N3 · N4 · N5 · N6 (§4 del contrato de fase 2b). El caso con root:root real va a
VM112 (escenario H).
"""
from __future__ import annotations

import ast
import hashlib
import os
import stat
from pathlib import Path

import pytest

from test_admin_label_6b2 import WS, _cliente, _csrf, _perfil_path, entorno  # noqa: F401

EUID = os.geteuid()
MENSAJE = "perfil-operador.json no es escribible por el usuario s9knowledge"
RAIZ = Path(__file__).resolve().parents[2]


def _post(c, tok, fp, label="Nombre nuevo"):
    return c.post("/admin/partidas/label", data={
        "workspace": WS, "label": label, "fingerprint": fp, "csrf_token": tok})


def _huella(p: Path):
    st = p.stat()
    return hashlib.sha256(p.read_bytes()).hexdigest(), st.st_ino, stat.S_IMODE(st.st_mode), st.st_uid


def _sin_temporales(carpeta: Path):
    return [p.name for p in carpeta.iterdir() if p.name.startswith(".") or p.name.endswith(".tmp")]


def test_P1_boveda_escribible_por_el_servicio_actualiza_el_perfil(entorno):  # noqa: F811
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    r = _post(c, tok, fp, "La Mesa de los Jueves")
    assert r.status_code == 302, (r.status_code, r.text[:300])
    assert "La Mesa de los Jueves" in _perfil_path(boveda).read_text(encoding="utf-8")


@pytest.mark.skipif(EUID == 0, reason="root escribe en cualquier sitio: el caso real va a VM112 (H)")
def test_N1_perfil_no_escribible_error_controlado_sin_modificacion_parcial(entorno):  # noqa: F811
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    perfil = _perfil_path(boveda)
    antes = _huella(perfil)
    perfil.chmod(0o444)   # directorio escribible, fichero NO: un rename lo "reemplazaria"
    try:
        r = _post(c, tok, fp)
        despues = _huella(perfil)
    finally:
        perfil.chmod(antes[2])
    assert r.status_code == 409 and MENSAJE in r.text, (r.status_code, r.text[:300])
    # ni contenido, ni inodo (no se reemplazo por rename), ni modo, ni propietario cambian
    assert despues == (antes[0], antes[1], 0o444, antes[3]), (antes, despues)
    assert _sin_temporales(perfil.parent) == []


@pytest.mark.skipif(EUID == 0, reason="root escribe en cualquier sitio: el caso real va a VM112 (H)")
def test_N2_directorio_no_escribible_error_controlado(entorno):  # noqa: F811
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    carpeta = _perfil_path(boveda).parent
    antes = _huella(_perfil_path(boveda))
    modo = stat.S_IMODE(carpeta.stat().st_mode)
    carpeta.chmod(0o555)
    try:
        r = _post(c, tok, fp)
        despues = _huella(_perfil_path(boveda))
    finally:
        carpeta.chmod(modo)
    assert r.status_code == 409 and MENSAJE in r.text, (r.status_code, r.text[:300])
    assert despues == antes
    assert stat.S_IMODE(carpeta.stat().st_mode) == modo, "la aplicacion cambio el modo de la bóveda"


@pytest.mark.skipif(EUID == 0, reason="root escribe en cualquier sitio: el caso root:root real va a VM112 (H)")
def test_N3_un_perfil_ajeno_no_se_apropia_ni_se_cambian_sus_permisos(entorno):  # noqa: F811
    """Simula «fichero que el servicio no puede escribir» con 0400 (el root:root 0600 real, en
    VM112): la app NO se lo apropia (mismo inodo, mismo modo, mismo propietario)."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    perfil = _perfil_path(boveda)
    perfil.chmod(0o400)
    antes = _huella(perfil)
    try:
        r = _post(c, tok, fp)
        despues = _huella(perfil)
    finally:
        perfil.chmod(0o644)
    assert r.status_code == 409 and MENSAJE in r.text
    assert despues == antes


def test_N4_symlink_inesperado_se_rechaza_segun_la_politica_actual(entorno):  # noqa: F811
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    perfil = _perfil_path(boveda)
    real = perfil.parent / "real.json"
    real.write_bytes(perfil.read_bytes())
    perfil.unlink()
    os.symlink(real, perfil)
    antes = real.read_bytes()
    r = _post(c, tok, fp)
    assert r.status_code in (400, 422), (r.status_code, r.text[:200])
    assert real.read_bytes() == antes and perfil.is_symlink()


def test_N5_boveda_ausente_comportamiento_actual_y_sin_state_alternativo(entorno, monkeypatch, tmp_path):  # noqa: F811
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    antes = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    monkeypatch.delenv("S9K_VAULT_ROOT", raising=False)
    r = _post(c, tok, fp)
    assert r.status_code in (400, 404, 409), (r.status_code, r.text[:200])
    despues = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    nuevos = [x for x in despues if x not in antes and "auth.db" not in x]
    assert nuevos == [], "se creo estado alternativo: %s" % nuevos


@pytest.mark.skipif(EUID == 0, reason="root escribe en cualquier sitio")
def test_N6_un_fallo_de_escritura_no_deja_copia_silenciosa_en_ningun_sitio(entorno, tmp_path):  # noqa: F811
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    carpeta = _perfil_path(boveda).parent
    modo = stat.S_IMODE(carpeta.stat().st_mode)
    carpeta.chmod(0o555)
    try:
        r = _post(c, tok, fp)
    finally:
        carpeta.chmod(modo)
    assert r.status_code == 409
    copias = [p for p in tmp_path.rglob("perfil-operador*") if p != _perfil_path(boveda)]
    assert copias == [], "copia del perfil fuera de la boveda: %s" % copias


def test_un_oserror_inesperado_del_escritor_es_409_nombrado(entorno, monkeypatch):  # noqa: F811
    from app import vault_writer

    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    def falla(*a, **k):
        raise PermissionError(13, "Permission denied", "perfil-operador.json")

    monkeypatch.setattr(vault_writer, "escribir_label_workspace", falla)
    r = _post(c, tok, fp, "Otro")
    assert r.status_code == 409 and MENSAJE in r.text, (r.status_code, r.text[:300])


def test_la_boveda_no_forma_parte_del_state_ni_del_arranque():
    """La boveda opcional no escribible NO impide arrancar: ninguna ruta de la boveda participa en
    la validacion de arranque (rutas de estado) y la app jamas llama a chown/chmod sobre ella."""
    from app import service_identity

    ss = service_identity.service_state()
    assert not [v for v in ss.STATE_PATH_VARS if "VAULT" in v]
    codigo = ast.parse((RAIZ / "viewer" / "app" / "vault_writer.py").read_text(encoding="utf-8"))
    llamadas = {n.func.attr for n in ast.walk(codigo)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not (llamadas & {"chown", "lchown", "chmod", "lchmod", "fchown", "fchmod"}), llamadas
    # el escritor jamas importa la autoridad de estado: no hay fallback hacia el state root
    fuente = (RAIZ / "viewer" / "app" / "vault_writer.py").read_text(encoding="utf-8")
    assert "service_state" not in fuente and "service_identity" not in fuente
