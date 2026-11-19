# -*- coding: utf-8 -*-
"""D-1 (P2) · carrera TOCTOU de STATE_RUNTIME con ficheros efimeros (-wal/-shm de SQLite).

Una entrada ya listada por `scandir` que da ENOENT al inspeccionarla DESAPARECIO durante la
inspeccion: no es hallazgo. Cualquier otro error (EACCES...) y cualquier defecto real (modo,
dueño, symlink) SIGUEN siendolo. La inspeccion es la MISMA que usa la validacion de arranque.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from test_h06_h08_vault_criterios import EUID, _fija_entorno_de_estado, _state_conforme

EFIMEROS = ("jobs.db-wal", "jobs.db-shm")


def _estado_con_sidecars(tmp_path):
    ss, st, env = _state_conforme(tmp_path)
    jobs = Path(env["S9K_JOBS_DB"])
    for f in EFIMEROS:
        fd = os.open(str(jobs.parent / f), os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
    return ss, st, env, jobs.parent


class _Ent:
    """DirEntry de mentira: el listado ya lo devolvio, el `stat` falla como se pida."""

    def __init__(self, real, fallo):
        self._r, self._f = real, fallo
        self.name, self.path = real.name, real.path

    def stat(self, follow_symlinks=True):
        if self.name in self._f:
            raise self._f[self.name]
        return self._r.stat(follow_symlinks=follow_symlinks)

    def __getattr__(self, n):
        return getattr(self._r, n)


def _escanea_con(monkeypatch, carpeta, accion=None, fallo=None):
    """Tras listar `carpeta`: ejecuta `accion()` (p. ej. borrar los sidecars) y/o hace que el
    `stat` de ciertas entradas falle con `fallo`."""
    real = os.scandir

    class Envoltura:
        def __init__(self, p):
            self.it, self.p = real(p), str(p)

        def __enter__(self):
            self.it.__enter__()
            return self

        def __exit__(self, *a):
            return self.it.__exit__(*a)

        def __iter__(self):
            ents = list(self.it)
            if self.p == str(carpeta):
                if accion:
                    accion()
                if fallo:
                    ents = [_Ent(e, fallo) for e in ents]
            return iter(ents)

    monkeypatch.setattr(os, "scandir", Envoltura)


def _borra_sidecars(carpeta):
    def f():
        for n in EFIMEROS:
            os.unlink(str(carpeta / n))
    return f


def test_D1_sidecar_desaparecido_entre_scandir_y_stat_no_es_hallazgo(tmp_path, monkeypatch):
    ss, st, env, jdir = _estado_con_sidecars(tmp_path)
    assert ss.inspect_state(st, uid=os.geteuid(), gid=os.getegid()) == []
    _escanea_con(monkeypatch, jdir, accion=_borra_sidecars(jdir))
    viol = [v.message() for v in ss.inspect_state(st, uid=os.geteuid(), gid=os.getegid())]
    assert viol == [], "D-1: FALSO HALLAZGO POR FICHERO EFIMERO DESAPARECIDO: %s" % viol


def test_D1_subdirectorio_desaparecido_antes_de_abrirlo_no_es_hallazgo(tmp_path, monkeypatch):
    import shutil

    ss, st, env, jdir = _estado_con_sidecars(tmp_path)
    tmpd = st / "efimero"
    tmpd.mkdir(mode=0o700)
    real = os.scandir

    def scandir(p):
        if str(p) == str(tmpd):
            shutil.rmtree(tmpd)
        return real(p)

    monkeypatch.setattr(os, "scandir", scandir)
    viol = [v.message() for v in ss.inspect_state(st, uid=os.geteuid(), gid=os.getegid())]
    assert viol == [], "D-1: FALSO HALLAZGO POR SUBDIRECTORIO DESAPARECIDO: %s" % viol


def test_D1_la_raiz_que_desaparece_sigue_siendo_hallazgo(tmp_path, monkeypatch):
    ss, st, env, jdir = _estado_con_sidecars(tmp_path)
    real = os.scandir

    def scandir(p):
        if str(p) == str(st):
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(p))
        return real(p)

    monkeypatch.setattr(os, "scandir", scandir)
    viol = ss.inspect_state(st, uid=os.geteuid(), gid=os.getegid())
    assert [v.code for v in viol] == [ss.UNREADABLE], viol


@pytest.mark.parametrize("codigo", [errno.EACCES, errno.EIO])
def test_D1_otro_error_al_inspeccionar_SIGUE_siendo_hallazgo(tmp_path, monkeypatch, codigo):
    ss, st, env, jdir = _estado_con_sidecars(tmp_path)
    _escanea_con(monkeypatch, jdir, fallo={
        "jobs.db-wal": OSError(codigo, os.strerror(codigo), str(jdir / "jobs.db-wal"))})
    viol = ss.inspect_state(st, uid=os.geteuid(), gid=os.getegid())
    assert [(v.code, os.path.basename(v.path)) for v in viol] == [(ss.UNREADABLE, "jobs.db-wal")], \
        "D-1: UN ERROR REAL (%s) YA NO ES HALLAZGO: %s" % (errno.errorcode[codigo], viol)


def test_D1_modo_incorrecto_y_symlink_siguen_siendo_hallazgo_aunque_haya_carrera(tmp_path, monkeypatch):
    ss, st, env, jdir = _estado_con_sidecars(tmp_path)
    (jdir / "jobs.db-wal").chmod(0o644)
    os.symlink(str(tmp_path / "no-existe"), str(jdir / "colgante"))
    _escanea_con(monkeypatch, jdir, accion=lambda: os.unlink(str(jdir / "jobs.db-shm")))
    viol = ss.inspect_state(st, uid=os.geteuid(), gid=os.getegid())
    tipos = sorted((v.code, os.path.basename(v.path)) for v in viol)
    assert tipos == [(ss.MODE, "jobs.db-wal"), (ss.SYMLINK, "colgante")], tipos


@pytest.mark.skipif(EUID == 0, reason="como root el dueño esperado no es el del proceso")
def test_D1_check_state_runtime_con_carrera_es_HEALTHY_y_con_modo_malo_sigue_UNHEALTHY(tmp_path, monkeypatch):
    from app.health import checks
    from app.health.models import HealthStatus

    ss, st, env, jdir = _estado_con_sidecars(tmp_path)
    _fija_entorno_de_estado(monkeypatch, ss, env)
    monkeypatch.setattr(ss, "expected_ids", lambda *a, **k: (os.geteuid(), os.getegid()))
    _escanea_con(monkeypatch, jdir, accion=_borra_sidecars(jdir))
    r = checks.check_state_runtime()
    assert r.status == HealthStatus.HEALTHY and r.details["state_runtime"] == "OK", \
        "D-1: STATE_RUNTIME FALSO UNHEALTHY POR LA CARRERA: %s" % r.message


@pytest.mark.skipif(EUID == 0, reason="como root el dueño esperado no es el del proceso")
def test_D1_check_state_runtime_con_modo_malo_sigue_UNHEALTHY(tmp_path, monkeypatch):
    from app.health import checks
    from app.health.models import HealthStatus

    ss, st, env, jdir = _estado_con_sidecars(tmp_path)
    _fija_entorno_de_estado(monkeypatch, ss, env)
    monkeypatch.setattr(ss, "expected_ids", lambda *a, **k: (os.geteuid(), os.getegid()))
    _escanea_con(monkeypatch, jdir, accion=_borra_sidecars(jdir))
    Path(env["S9K_AUTH_DB_PATH"]).chmod(0o644)
    mal = checks.check_state_runtime()
    assert mal.status == HealthStatus.UNHEALTHY and "auth.db" in mal.message, mal.message

