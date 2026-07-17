# -*- coding: utf-8 -*-
"""Tests de check_backups.

El fallo que motiva esta suite: el check contaba solo FICHEROS de primer nivel,
pero el layout real guarda cada backup como un DIRECTORIO. Resultado: 'sin
backups' y un UNHEALTHY global falso con todo lo demas sano.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from app.health import checks
from app.health.models import HealthStatus


# ---------------------------------------------------------------------------
# Utillaje
# ---------------------------------------------------------------------------

def _sqlite(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"x{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    path.chmod(0o600)


def _backup_set(root: Path, name: str = "pre-deploy-20260716-010942",
                with_sums: bool = True, sums_name: str = "SHA256SUMS") -> Path:
    """Reproduce el layout REAL de VM105: un directorio con las bases dentro."""
    d = root / name
    d.mkdir(parents=True)
    _sqlite(d / "auth.db")
    _sqlite(d / "jobs.db")
    if with_sums:
        lines = []
        for db in ("auth.db", "jobs.db"):
            h = hashlib.sha256((d / db).read_bytes()).hexdigest()
            lines.append(f"{h}  {db}")
        (d / sums_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        (d / sums_name).chmod(0o600)
    d.chmod(0o700)
    return d


def _age(path: Path, hours: float) -> None:
    """Envejece el conjunto: sus FICHEROS y, de paso, el directorio.

    La edad la marcan los ficheros (el mtime del directorio es manipulable), asi
    que un helper que solo tocara el directorio no envejeceria nada.
    """
    t = time.time() - hours * 3600
    if path.is_dir():
        for p in path.iterdir():
            if p.is_file():
                os.utime(p, (t, t))
    os.utime(path, (t, t))


def _check(root: Path, **kw):
    return checks.check_backups(backup_root=str(root), **kw)


# ---------------------------------------------------------------------------
# La regresion que motiva el hotfix
# ---------------------------------------------------------------------------

def test_backup_en_subdirectorio_es_healthy(tmp_path):
    """EL FALSO FALLO DE RC2: backups como directorios daban 'sin backups'."""
    _backup_set(tmp_path)
    r = _check(tmp_path)
    assert r.status == HealthStatus.HEALTHY, r.message
    assert r.details["latest"] == "pre-deploy-20260716-010942"
    assert sorted(r.details["dbs"]) == ["auth.db", "jobs.db"]


def test_encontrar_directorio_no_basta_para_healthy(tmp_path):
    """Un directorio con una base corrupta no puede salir HEALTHY."""
    d = _backup_set(tmp_path, with_sums=False)
    (d / "auth.db").write_bytes(b"esto no es una base sqlite" * 40)
    (d / "auth.db").chmod(0o600)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "auth.db" in r.message


# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------

def test_sin_configurar_es_unknown():
    assert checks.check_backups(backup_root=None).status == HealthStatus.UNKNOWN


def test_raiz_inexistente_es_unhealthy(tmp_path):
    r = _check(tmp_path / "no-existe")
    assert r.status == HealthStatus.UNHEALTHY


def test_raiz_vacia_es_unhealthy(tmp_path):
    assert _check(tmp_path).status == HealthStatus.UNHEALTHY


def test_backup_antiguo_es_degraded(tmp_path):
    d = _backup_set(tmp_path)
    _age(d, 30)
    r = _check(tmp_path, warn_age_hours=26, max_age_hours=48)
    assert r.status == HealthStatus.DEGRADED
    assert r.details["age_hours"] >= 29


def test_backup_rancio_es_unhealthy(tmp_path):
    d = _backup_set(tmp_path)
    _age(d, 100)
    r = _check(tmp_path, warn_age_hours=26, max_age_hours=48)
    assert r.status == HealthStatus.UNHEALTHY
    assert "rancio" in r.message


def test_checksum_incorrecto_es_unhealthy(tmp_path):
    d = _backup_set(tmp_path)
    (d / "SHA256SUMS").write_text(f"{'0' * 64}  auth.db\n", encoding="utf-8")
    (d / "SHA256SUMS").chmod(0o600)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "checksum incorrecto" in r.message


def test_manifiesto_invalido_es_unhealthy(tmp_path):
    d = _backup_set(tmp_path)
    (d / "manifest.json").write_text("{ no es json", encoding="utf-8")
    (d / "manifest.json").chmod(0o600)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "manifiesto" in r.message


def test_manifiesto_valido_se_reporta(tmp_path):
    d = _backup_set(tmp_path)
    (d / "manifest.json").write_text(json.dumps({"tipo": "pre-deploy"}), encoding="utf-8")
    (d / "manifest.json").chmod(0o600)
    r = _check(tmp_path)
    assert r.status == HealthStatus.HEALTHY
    assert r.details["manifest"] is True


def test_permisos_inseguros_es_unhealthy(tmp_path):
    d = _backup_set(tmp_path)
    (d / "auth.db").chmod(0o644)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "permisos" in r.message


def test_directorio_accesible_a_terceros_es_unhealthy(tmp_path):
    """El control que de verdad protege: el modo del directorio."""
    d = _backup_set(tmp_path)
    d.chmod(0o755)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "accesible a terceros" in r.message


def test_ficheros_no_sensibles_a_0644_no_son_un_fallo(tmp_path):
    """Los backups REALES traen .service y .md a 0644 dentro de un dir 0700.

    Marcarlos era un falso UNHEALTHY: no son secretos y nadie salvo root llega
    a ellos. Solo lo sensible (.db, .env) exige 0600.
    """
    d = _backup_set(tmp_path)
    (d / "s9-knowledge-viewer.service.bak").write_text("[Unit]\n", encoding="utf-8")
    (d / "s9-knowledge-viewer.service.bak").chmod(0o644)
    (d / "estado-anterior.txt").write_text("nota\n", encoding="utf-8")
    (d / "estado-anterior.txt").chmod(0o644)
    r = _check(tmp_path)
    assert r.status == HealthStatus.HEALTHY, r.message


def test_env_de_backup_a_0644_si_es_un_fallo(tmp_path):
    """…pero un .env legible es un secreto expuesto de verdad."""
    d = _backup_set(tmp_path)
    (d / "legacy-viewer.env.bak").write_text("S9K_CSRF_SECRET=x\n", encoding="utf-8")
    (d / "legacy-viewer.env.bak").chmod(0o644)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "legacy-viewer.env.bak" in r.message


def test_base_vacia_es_unhealthy(tmp_path):
    d = _backup_set(tmp_path, with_sums=False)
    (d / "jobs.db").write_bytes(b"")
    (d / "jobs.db").chmod(0o600)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "vacia" in r.message


def test_symlink_inesperado_es_unhealthy(tmp_path):
    d = _backup_set(tmp_path)
    (d / "colado").symlink_to("/etc/passwd")
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "symlink" in r.message


def test_sin_sumas_sigue_siendo_healthy(tmp_path):
    """No todo backup trae sumas; su ausencia se reporta pero no es un fallo."""
    _backup_set(tmp_path, with_sums=False)
    r = _check(tmp_path)
    assert r.status == HealthStatus.HEALTHY
    assert "sin fichero de sumas" in r.details["checksums"]


def test_nombre_alternativo_de_sumas(tmp_path):
    """El layout real usa SHA256SUMS en un backup y checksums.sha256 en otro."""
    _backup_set(tmp_path, sums_name="checksums.sha256")
    r = _check(tmp_path)
    assert r.status == HealthStatus.HEALTHY
    assert "verificados" in r.details["checksums"]


# ---------------------------------------------------------------------------
# Escaneo
# ---------------------------------------------------------------------------

def test_elige_el_conjunto_mas_reciente(tmp_path):
    viejo = _backup_set(tmp_path, name="pre-deploy-20260101-000000")
    nuevo = _backup_set(tmp_path, name="predeploy-rc2-20260717-092653")
    _age(viejo, 200)
    _age(nuevo, 1)
    r = _check(tmp_path)
    assert r.details["latest"] == "predeploy-rc2-20260717-092653"
    assert r.details["sets"] == 2
    assert r.status == HealthStatus.HEALTHY


def test_profundidad_acotada(tmp_path):
    """Mas alla de max_scan_depth no se busca: el escaneo no puede desbocarse."""
    hondo = tmp_path / "a" / "b" / "c"
    hondo.mkdir(parents=True)
    _backup_set(hondo, name="pre-deploy-20260716-010942")
    assert _check(tmp_path, max_scan_depth=1).status == HealthStatus.UNHEALTHY
    assert _check(tmp_path, max_scan_depth=5).status == HealthStatus.HEALTHY


def test_no_modifica_los_backups(tmp_path):
    """Invariante del encargo: el healthcheck no crea, borra ni modifica nada."""
    d = _backup_set(tmp_path)
    antes = {p.name: (p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_mode)
             for p in sorted(d.iterdir())}
    inodos = sorted(p.name for p in d.iterdir())
    assert _check(tmp_path).status == HealthStatus.HEALTHY
    despues = {p.name: (p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_mode)
               for p in sorted(d.iterdir())}
    assert antes == despues, "el check alteró el backup"
    # Ni journals ni ficheros -wal/-shm colados por abrir SQLite en escritura.
    assert sorted(p.name for p in d.iterdir()) == inodos


def test_base_en_modo_wal_no_deja_artefactos(tmp_path):
    """REGRESION: `mode=ro` a secas creaba -shm/-wal dentro del backup.

    Con una base en modo WAL (el caso real), abrirla para leer bastaba para que
    SQLite escribiera en el conjunto y alterara el mtime del directorio. Este
    test falla si el check vuelve a ensuciar un backup.
    """
    d = tmp_path / "pre-deploy-wal"
    d.mkdir()
    conn = sqlite3.connect(d / "auth.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t (id) VALUES (1)")
    conn.commit()
    conn.close()
    for p in d.iterdir():          # el cierre limpio ya deja solo el .db
        if p.name != "auth.db":
            p.unlink()
    (d / "auth.db").chmod(0o600)
    d.chmod(0o700)

    antes = sorted(p.name for p in d.iterdir())
    mtime_dir_antes = d.stat().st_mtime_ns
    r = _check(tmp_path)
    despues = sorted(p.name for p in d.iterdir())

    assert r.status == HealthStatus.HEALTHY, r.message
    assert antes == despues, f"el check dejo artefactos: {set(despues) - set(antes)}"
    assert d.stat().st_mtime_ns == mtime_dir_antes, "el check altero el mtime del directorio"


def test_wal_con_datos_es_unhealthy(tmp_path):
    """Un -wal con contenido = copia no consolidada; no puede pasar por buena."""
    d = _backup_set(tmp_path, with_sums=False)
    (d / "auth.db-wal").write_bytes(b"\x00" * 4096)
    (d / "auth.db-wal").chmod(0o600)
    r = _check(tmp_path)
    assert r.status == HealthStatus.UNHEALTHY
    assert "sin consolidar" in r.message


def test_edad_se_mide_por_los_ficheros_no_por_el_directorio(tmp_path):
    """Tocar el directorio no puede rejuvenecer un backup rancio."""
    d = _backup_set(tmp_path)
    for p in d.iterdir():
        _age(p, 100)
    _age(d, 100)
    os.utime(d, None)              # alguien crea/borra algo dentro: dir "nuevo"
    r = _check(tmp_path, warn_age_hours=26, max_age_hours=48)
    assert r.status == HealthStatus.UNHEALTHY, r.message
    assert r.details["age_hours"] >= 99


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora los permisos de lectura")
def test_raiz_inaccesible_es_unknown(tmp_path):
    root = tmp_path / "backups"
    _backup_set(root)
    root.chmod(0o000)
    try:
        assert _check(root).status == HealthStatus.UNKNOWN
    finally:
        root.chmod(0o700)


def test_nombre_antiguo_backup_dir_sigue_funcionando(tmp_path):
    """Compatibilidad: quien pase el parametro viejo no se queda sin check."""
    _backup_set(tmp_path)
    assert checks.check_backups(backup_dir=str(tmp_path)).status == HealthStatus.HEALTHY
