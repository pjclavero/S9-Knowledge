# -*- coding: utf-8 -*-
"""H-06/H-08 (TD-H06-02) — `vault_writer` queda EXTERNO_SIN_DECIDIR (sin cambiar su comportamiento
de escritura), pero con el visor como `s9knowledge` una boveda no escribible tiene que ser un error
CONTROLADO y NOMBRADO, nunca un 500."""
from __future__ import annotations

import os
import stat

import pytest

from test_admin_label_6b2 import WS, _cliente, _csrf, _perfil_path, entorno  # noqa: F401

EUID = os.geteuid()


@pytest.mark.skipif(EUID == 0, reason="root escribe en cualquier directorio")
def test_boveda_de_solo_lectura_da_409_nombrado_y_no_500(entorno):  # noqa: F811
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    carpeta = _perfil_path(boveda).parent
    antes = _perfil_path(boveda).read_bytes()
    modo = stat.S_IMODE(carpeta.stat().st_mode)
    carpeta.chmod(0o555)
    try:
        r = c.post("/admin/partidas/label", data={
            "workspace": WS, "label": "Nombre nuevo", "fingerprint": fp, "csrf_token": tok})
    finally:
        carpeta.chmod(modo)
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert "escritura" in r.text.lower() or "escribible" in r.text.lower(), r.text[:300]
    assert _perfil_path(boveda).read_bytes() == antes, "el perfil cambio pese al fallo"


def test_un_oserror_inesperado_del_escritor_es_409_nombrado(entorno, monkeypatch):  # noqa: F811
    from app import vault_writer

    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)

    def falla(*a, **k):
        raise PermissionError(13, "Permission denied", "perfil-operador.json")

    monkeypatch.setattr(vault_writer, "escribir_label_workspace", falla)
    r = c.post("/admin/partidas/label", data={
        "workspace": WS, "label": "Otro", "fingerprint": fp, "csrf_token": tok})
    assert r.status_code == 409 and "bóveda no es escribible" in r.text, (r.status_code, r.text[:300])
