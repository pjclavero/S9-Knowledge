# -*- coding: utf-8 -*-
"""H-06/H-08 ronda 2b · el RESPALDO de la escritura en el sitio (caso b, perfil ajeno escribible)
NUNCA destruye ni hace retroceder contenido que no sea una escritura inacabada de S9-Knowledge.

EL DEFECTO (revisión acotada de la ronda 2, P1 H-R2-1)
------------------------------------------------------
El respaldo se creaba con ``O_EXCL`` y se llenaba DESPUÉS, y la siguiente escritura lo
restauraba A CIEGAS: (i) un SIGKILL/ENOSPC entre crear y llenar dejaba un respaldo de 0 bytes
que la siguiente escritura «restauraba» (perfil destruido); (iii) un SIGKILL tras escribir y
antes de borrar el respaldo, más una edición manual del operador, y la siguiente escritura
devolvía el respaldo viejo (edición perdida).

LA GARANTÍA
-----------
* Publicación ATÓMICA: temporal propio -> sobre completo + fsync -> ``link`` al nombre
  definitivo. Nunca hay un respaldo a medias con el nombre definitivo.
* El sobre lleva la identidad de la operación (original y nuevo previsto, con sha256). Al
  empezar: perfil == nuevo -> se borra; == original -> se borra; prefijo estricto del nuevo
  (resto de ESTA escritura) -> se restaura verificando el sha; cualquier otra cosa -> 409 sin
  tocar nada.

QUÉ SE EJECUTA DE VERDAD
------------------------
El escritor REAL en un proceso REAL que se mata con SIGKILL en cada punto (temporal del
respaldo creado; respaldo publicado y antes de escribir; a mitad de escritura; escrito y antes
de borrar el respaldo). El "otro dueño" se simula en la decisión (``_es_del_proceso``) porque
sin root no hay otro dueño; el real (``s9test``) va a VM112 (escenario H). Se comprueban inodo,
dueño, grupo, modo y contenido.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from test_vault_writer_6b2 import _PERFIL_CONFORME, _escribir_perfil

RAIZ = Path(__file__).resolve().parents[2]
EUID = os.geteuid()

#: (punto, codigo que se inyecta en el proceso hijo antes de escribir)
_PUNTOS = {
    "tmp_respaldo": (
        "def _p(tmp, respaldo):\n    os.kill(os.getpid(), signal.SIGKILL)\nvw._publicar = _p\n"),
    "publicado": (
        "def _v(fd, c):\n    os.kill(os.getpid(), signal.SIGKILL)\nvw._volcar = _v\n"),
    "mitad": (
        "def _v(fd, c):\n    os.lseek(fd, 0, 0)\n    os.ftruncate(fd, 0)\n    os.write(fd, c[: len(c) // 3])\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\nvw._volcar = _v\n"),
    "escrito": (
        "def _b(r):\n    os.kill(os.getpid(), signal.SIGKILL)\nvw._borrar_respaldo = _b\n"),
}

_HIJO = """
import json, os, signal, sys
sys.path.insert(0, sys.argv[2])
sys.path.append(sys.argv[3])
from pathlib import Path
from app import vault_writer as vw
vw._es_del_proceso = lambda st: False
exec(sys.argv[4])
ruta = Path(sys.argv[1])
datos = json.loads(ruta.read_text(encoding="utf-8"))
datos.setdefault("metadata", {})["label"] = "A medias"
vw._escribir_atomico(ruta, datos)
"""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _meta(p: Path):
    st = p.stat()
    return st.st_ino, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)


def _efimeros(carpeta: Path):
    return sorted(p.name for p in carpeta.iterdir() if p.name.startswith(".s9k-probe-"))


@pytest.fixture
def perfil(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    p = carpeta / "perfil-operador.json"
    p.chmod(0o664)
    return p


def _matar(perfil: Path, punto: str):
    r = subprocess.run([sys.executable, "-c", _HIJO, str(perfil), str(RAIZ / "viewer"),
                        str(RAIZ / "data-engine" / "app"), _PUNTOS[punto]],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == -9, (punto, r.returncode, r.stderr[-600:])


def _siguiente(vw, perfil: Path, huella):
    return vw.escribir_label_workspace(perfil.parent, "Siguiente escritura", huella)


ESTADO_TRAS_EL_CORTE = {
    # punto: (¿respaldo publicado?, relación del perfil con el original/nuevo)
    "tmp_respaldo": (False, "original"),
    "publicado": (True, "original"),
    "mitad": (True, "prefijo"),
    "escrito": (True, "nuevo"),
}


@pytest.mark.parametrize("punto", list(_PUNTOS))
def test_SIGKILL_en_cada_punto_y_la_siguiente_escritura_converge(perfil, punto, monkeypatch):
    from app import vault_writer as vw

    original = perfil.read_bytes()
    meta = _meta(perfil)
    huella_original = vw.huella_de(perfil)
    _matar(perfil, punto)
    publicado, relacion = ESTADO_TRAS_EL_CORTE[punto]
    respaldo = vw.ruta_respaldo(perfil)
    assert respaldo.exists() is publicado, (punto, "respaldo publicado: %s" % respaldo.exists())
    actual = perfil.read_bytes()
    if relacion == "original":
        assert actual == original
    elif relacion == "nuevo":
        assert b"A medias" in actual and json.loads(actual)
    else:
        assert actual != original and b"A medias" not in actual   # a medias: prefijo del nuevo
    if publicado:
        sobre = json.loads(respaldo.read_bytes())   # nunca un respaldo a medias con nombre definitivo
        assert sobre["sha_original"] == _sha(original)
    monkeypatch.setattr(vw, "_es_del_proceso", lambda st: False)
    huella = vw.huella_de(perfil) if relacion != "prefijo" else huella_original
    _siguiente(vw, perfil, huella)
    final = perfil.read_text(encoding="utf-8")
    assert "Siguiente escritura" in final and json.loads(final)
    assert _meta(perfil) == meta, "inodo/dueño/grupo/modo cambiaron"
    assert not respaldo.exists() and _efimeros(perfil.parent) == [], _efimeros(perfil.parent)


@pytest.mark.parametrize("punto", ["publicado", "mitad", "escrito"])
def test_una_edicion_del_operador_tras_el_corte_NO_se_pierde(perfil, punto, monkeypatch):
    """(iii) del revisor: tras el corte el operador edita el perfil a mano. La siguiente escritura
    de S9K NO lo hace retroceder: 409 «respaldo pendiente» y la edición sigue en disco."""
    from app import vault_writer as vw

    _matar(perfil, punto)
    editado = dict(_PERFIL_CONFORME, metadata=dict(_PERFIL_CONFORME.get("metadata") or {}, nota_del_operador="EDITADO A MANO"))
    with open(perfil, "r+", encoding="utf-8") as fh:   # edición EN EL SITIO (mismo inodo)
        fh.truncate(0)
        fh.write(json.dumps(editado, indent=2))
    contenido = perfil.read_bytes()
    monkeypatch.setattr(vw, "_es_del_proceso", lambda st: False)
    with pytest.raises(vw.RespaldoPendienteError) as exc:
        _siguiente(vw, perfil, vw.huella_de(perfil))
    assert "respaldo pendiente" in str(exc.value) and vw.ruta_respaldo(perfil).name in str(exc.value)
    assert perfil.read_bytes() == contenido, "EDICION DEL OPERADOR PERDIDA"
    assert vw.ruta_respaldo(perfil).exists(), "se borró el respaldo sin resolver"


def test_tras_el_temporal_del_respaldo_la_edicion_del_operador_se_conserva(perfil, monkeypatch):
    from app import vault_writer as vw

    _matar(perfil, "tmp_respaldo")
    editado = dict(_PERFIL_CONFORME, metadata=dict(_PERFIL_CONFORME.get("metadata") or {}, nota_del_operador="EDITADO A MANO"))
    perfil.write_text(json.dumps(editado, indent=2), encoding="utf-8")
    monkeypatch.setattr(vw, "_es_del_proceso", lambda st: False)
    _siguiente(vw, perfil, vw.huella_de(perfil))
    final = perfil.read_text(encoding="utf-8")
    assert "EDITADO A MANO" in final and "Siguiente escritura" in final
    assert _efimeros(perfil.parent) == []


def test_ENOSPC_al_llenar_el_respaldo_deja_el_perfil_intacto_y_sin_respaldo(perfil, monkeypatch):
    from app import vault_writer as vw

    antes = (perfil.read_bytes(), _meta(perfil))

    def lleno(fd, contenido):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(vw, "_es_del_proceso", lambda st: False)
    monkeypatch.setattr(vw, "_escribir_todo", lleno)
    datos = dict(_PERFIL_CONFORME, metadata={"label": "No cabe"})
    with pytest.raises(vw.RespaldoNoPosibleError):
        vw._escribir_atomico(perfil, datos)
    assert (perfil.read_bytes(), _meta(perfil)) == antes
    assert not vw.ruta_respaldo(perfil).exists() and _efimeros(perfil.parent) == []


def test_X2_un_error_a_mitad_de_escribir_restaura_el_original_en_el_sitio(perfil, monkeypatch):
    """X2 (mutante del revisor): si el caso (b) no restaura el original tras un error, el perfil
    queda a medias. Aquí el fallo es una excepción normal (no SIGKILL): se restaura YA."""
    from app import vault_writer as vw

    original = perfil.read_bytes()
    meta = _meta(perfil)
    real = vw._volcar
    n = {"v": 0}

    def falla_la_primera(fd, contenido):
        n["v"] += 1
        if n["v"] == 1:
            os.lseek(fd, 0, 0)
            os.ftruncate(fd, 0)
            os.write(fd, contenido[:7])
            raise OSError(errno.EIO, "fallo simulado a mitad")
        return real(fd, contenido)

    monkeypatch.setattr(vw, "_es_del_proceso", lambda st: False)
    monkeypatch.setattr(vw, "_volcar", falla_la_primera)
    with pytest.raises(OSError):
        vw._escribir_atomico(perfil, dict(_PERFIL_CONFORME, metadata={"label": "X"}))
    assert perfil.read_bytes() == original, "X2: EL ORIGINAL NO SE RESTAURO TRAS EL ERROR"
    assert _meta(perfil) == meta and not vw.ruta_respaldo(perfil).exists()


@pytest.mark.parametrize("plantado", ["vacio", "symlink", "de_otro_usuario", "invalido", "obsoleto_propio"])
def test_un_respaldo_no_fiable_NUNCA_se_restaura(perfil, plantado, monkeypatch, tmp_path):
    from app import vault_writer as vw

    respaldo = vw.ruta_respaldo(perfil)
    if plantado == "vacio":
        respaldo.write_bytes(b"")
    elif plantado == "symlink":
        (tmp_path / "fuera.json").write_text("{}")
        os.symlink(tmp_path / "fuera.json", respaldo)
    elif plantado == "invalido":
        respaldo.write_text(json.dumps({"version": "s9k-respaldo-v2", "sha_original": "0" * 64,
                                        "sha_nuevo": "0" * 64, "original_b64": "", "nuevo_b64": ""}))
    else:
        # un respaldo bien formado pero de OTRA operación: el perfil no es ni su original, ni
        # su nuevo, ni un resto de ella (V8c del revisor: un respaldo viejo del propio servicio)
        viejo = b'{"viejo": 1}\n'
        otro = b'{"otro": 2}\n'
        import base64
        respaldo.write_text(json.dumps({
            "version": "s9k-respaldo-v2", "sha_original": _sha(viejo), "sha_nuevo": _sha(otro),
            "original_b64": base64.b64encode(viejo).decode(), "nuevo_b64": base64.b64encode(otro).decode()}))
    if plantado == "de_otro_usuario":
        # un sobre VALIDO cuyo «nuevo» es justo el perfil actual: solo la comprobacion del dueño
        # impide que se acepte (X6); sin ella se borraria y se daria por resuelto
        import base64
        tercero, actual = b'{"tercero": 1}\n', perfil.read_bytes()
        respaldo.write_text(json.dumps({
            "version": "s9k-respaldo-v2", "sha_original": _sha(tercero), "sha_nuevo": _sha(actual),
            "original_b64": base64.b64encode(tercero).decode(), "nuevo_b64": base64.b64encode(actual).decode()}))
        monkeypatch.setattr(vw, "_respaldo_es_propio", lambda st: False)
    antes = (perfil.read_bytes(), _meta(perfil))
    monkeypatch.setattr(vw, "_es_del_proceso", lambda st: False)
    with pytest.raises(vw.RespaldoPendienteError):
        _siguiente(vw, perfil, vw.huella_de(perfil))
    assert (perfil.read_bytes(), _meta(perfil)) == antes, "RESTAURACION A CIEGAS: el perfil cambió"
    assert os.path.lexists(respaldo), "se borró un respaldo que no era nuestro/fiable"


def test_respaldo_pendiente_es_un_conflicto_409_del_endpoint():
    """El 409 del endpoint: `RespaldoPendienteError` ES un `ConflictoEscrituraError`, que el
    router mapea a 409 con su texto (sin 500, sin PermissionError sin contexto)."""
    from app import vault_writer as vw

    assert issubclass(vw.RespaldoPendienteError, vw.ConflictoEscrituraError)
    fuente = (RAIZ / "viewer" / "app" / "routers" / "admin.py").read_text(encoding="utf-8")
    assert "except vault_writer.ConflictoEscrituraError as exc:\n        raise HTTPException(status_code=409" in fuente
