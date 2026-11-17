# -*- coding: utf-8 -*-
"""SECRETOS — UNA politica de lectura, la de la autoridad (``service_state.py``).

Defecto (base b4e396d): ``preparar_secretos_del_servicio`` (paso 5b) deja cada secreto
``root:s9knowledge`` 0640, y ``driver_neo4j.read_secret`` rechazaba cualquier bit de grupo
(``hazlo 0600``): el worker no podia leer el secreto que el propio despliegue le preparaba.
Dos piezas verdes por separado, rotas juntas (costura).

Contrato: se aceptan EXACTAMENTE (a) un fichero del propio usuario 0600 o mas restrictivo y
(b) ``root:<grupo de servicio>`` 0640 o mas restrictivo. Se rechazan bits de «otros», escritura
de grupo, grupo ajeno con bits de grupo, symlink y vacio, sin revelar contenido ni longitud.

No cubierto aqui (necesita root real): dueno root + grupo ``s9knowledge`` verdaderos y la lectura
como ``s9knowledge`` por el camino real del worker contra un Neo4j (RC-E2E).
"""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SS_PY = RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"
LIB_SH = RAIZ / "deploy" / "scripts" / "lib.sh"
PREFLIGHT = RAIZ / "deploy" / "scripts" / "preflight_ensayo_rc.py"
APP = RAIZ / "data-engine" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from knowledge_v3 import service_state as ss  # noqa: E402
from knowledge_v3.driver_neo4j import DriverConfigError, read_secret  # noqa: E402

SVC_GID = 4242          # gid «de servicio» ficticio
AJENO_GID = 4343
YO = 1000               # euid ficticio del proceso


def _v(mode, uid, gid, size=10, *, regular=True):
    return ss.secret_read_violations(mode, uid, gid, size, euid=YO, service_gid=SVC_GID, is_regular=regular)


# ---------------------------------------------------------------------------
# la politica, pura
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode,uid,gid", [
    (0o600, YO, 5555),            # (a) propio usuario 0600
    (0o400, YO, 5555),            # (a) mas restrictivo
    (0o640, 0, SVC_GID),          # (b) lo que deja el despliegue
    (0o440, 0, SVC_GID),
    (0o400, YO, SVC_GID),
])
def test_politica_acepta(mode, uid, gid):
    v = _v(mode, uid, gid)
    assert v == [], "RECHAZA %s: %s" % (oct(mode), [x.detail for x in v])


@pytest.mark.parametrize("mode,uid,gid,causa", [
    (0o644, 0, SVC_GID, "OTROS"),
    (0o604, YO, 5555, "OTROS"),
    (0o660, 0, SVC_GID, "ESCRIBIR"),
    (0o620, 0, SVC_GID, "ESCRIBIR"),
    (0o640, 0, AJENO_GID, "root:s9knowledge"),   # grupo ajeno con bit de grupo
    (0o640, YO, SVC_GID, "root:s9knowledge"),    # no es root
    (0o640, YO, 5555, "root:s9knowledge"),       # propio, con bit de grupo: no es (a) ni (b)
    (0o700, YO, 5555, "maximo"),                 # bit de ejecucion
    (0o600, 7777, 5555, "propio usuario"),       # 0600 de OTRO usuario
])
def test_politica_rechaza(mode, uid, gid, causa):
    det = " ".join(v.detail for v in _v(mode, uid, gid))
    assert causa in det, "no detecta %s en modo %s: %r" % (causa, oct(mode), det)


def test_politica_rechaza_vacio_y_no_regular():
    assert any("vacio" in v.detail for v in _v(0o600, YO, 5555, size=0)), "no detecta vacio"
    assert any("no es un fichero regular" in v.detail for v in _v(0o600, YO, 5555, regular=False))


def test_sin_grupo_de_servicio_no_hay_lectura_por_grupo():
    v = ss.secret_read_violations(0o640, 0, SVC_GID, 1, euid=YO, service_gid=None)
    assert v


def test_la_politica_toma_el_modo_maximo_de_la_autoridad():
    assert ss.SECRET_FILE_MAX_MODE == 0o640
    # por encima del maximo de la autoridad, rechazo; en el maximo, aceptado
    assert _v(ss.SECRET_FILE_MAX_MODE, 0, SVC_GID) == []
    assert _v(ss.SECRET_FILE_MAX_MODE | 0o001, 0, SVC_GID)


# ---------------------------------------------------------------------------
# read_secret sobre ficheros reales
# ---------------------------------------------------------------------------
def _fichero(tmp_path, modo, contenido="s3cr3t-xyz\n", nombre="pass"):
    f = tmp_path / nombre
    f.write_text(contenido, encoding="utf-8")
    f.chmod(modo)
    return f


def test_read_secret_acepta_el_0600_propio(tmp_path):
    assert read_secret(str(_fichero(tmp_path, 0o600))) == "s3cr3t-xyz"


@pytest.mark.parametrize("modo", [0o644, 0o660, 0o604, 0o640, 0o700])
def test_read_secret_rechaza_sin_revelar_nada(tmp_path, modo):
    # 0640 de un fichero que NO es root:<grupo de servicio> (aqui, del propio usuario) tampoco vale
    f = _fichero(tmp_path, modo)
    with pytest.raises(DriverConfigError) as exc:
        read_secret(str(f))
    msg = str(exc.value)
    assert "s3cr3t-xyz" not in msg and "politica SECRET" in msg


def test_read_secret_rechaza_symlink_y_vacio(tmp_path):
    real = _fichero(tmp_path, 0o600)
    enlace = tmp_path / "enlace"
    enlace.symlink_to(real)
    with pytest.raises(DriverConfigError):
        read_secret(str(enlace))
    with pytest.raises(DriverConfigError):
        read_secret(str(_fichero(tmp_path, 0o600, contenido="", nombre="vacio")))


def test_read_secret_acepta_root_grupo_de_servicio_0640(tmp_path, monkeypatch):
    """Lo que deja el despliegue. Sin root real se simula SOLO el dueno que devuelve ``lstat``."""
    f = _fichero(tmp_path, 0o640)
    real = os.lstat

    def falso(p, *a, **k):
        st = real(p, *a, **k)
        if str(p) == str(f):
            vals = list(st)
            vals[stat.ST_UID], vals[stat.ST_GID] = 0, SVC_GID
            return os.stat_result(vals)
        return st

    monkeypatch.setattr(os, "lstat", falso)
    monkeypatch.setattr(ss, "expected_ids", lambda *a, **k: (None, SVC_GID))
    assert read_secret(str(f)) == "s3cr3t-xyz"
    # mismo fichero pero grupo ajeno -> rechazo
    monkeypatch.setattr(ss, "expected_ids", lambda *a, **k: (None, AJENO_GID))
    with pytest.raises(DriverConfigError):
        read_secret(str(f))


# ---------------------------------------------------------------------------
# COSTURA: lo que deja el despliegue es lo que acepta el lector
# ---------------------------------------------------------------------------
def test_COSTURA_el_modo_y_el_dueno_que_deja_preparar_secretos_los_acepta_el_lector(tmp_path):
    cfg = tmp_path / "etc"
    (cfg / "secrets").mkdir(parents=True)
    f = cfg / "secrets" / "neo4j_worker_password"
    f.write_text("abc\n")
    f.chmod(0o644)                       # estado «de partida» inseguro
    registro = tmp_path / "chown.log"
    cuerpo = (
        "set -Eeuo pipefail\n"
        "source %s\n"
        # sin root: chown/chgrp se REGISTRAN (el modo lo aplica el chmod real);
        # `secret-check` exige dueno root, asi que se omite aqui (lo cubre su propio test).
        'chown() { echo "$*" >> %s; }\n'
        "chgrp() { :; }\n"
        'python3() { if [ "${2:-}" = secret-check ]; then return 0; fi; command python3 "$@"; }\n'
        "preparar_secretos_del_servicio %s\n"
    ) % (LIB_SH, registro, cfg)
    r = subprocess.run(["bash", "-c", cuerpo], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})
    assert r.returncode == 0, (r.stdout, r.stderr)
    dueno_grupo = registro.read_text().split()[0]
    assert dueno_grupo == "root:%s" % ss.SERVICE_GROUP, dueno_grupo
    modo = stat.S_IMODE(f.stat().st_mode)
    assert modo == ss.SECRET_FILE_MAX_MODE, oct(modo)
    # con ESE dueno (root), ESE grupo y ESE modo, la politica del lector acepta
    v = ss.secret_read_violations(modo, 0, SVC_GID, 4, euid=YO, service_gid=SVC_GID)
    assert v == [], "EL LECTOR RECHAZA LO QUE DEJA EL DESPLIEGUE: %s" % [x.detail for x in v]
    # y la misma cifra que consume bash es la que usa el lector
    cifra = subprocess.run([sys.executable, str(SS_PY), "get", "secret_file_mode"],
                           capture_output=True, text=True).stdout.strip()
    assert int(cifra, 8) == ss.SECRET_FILE_MAX_MODE


def test_COSTURA_el_lector_no_conserva_su_propia_cifra_de_modos():
    fuente = (APP / "knowledge_v3" / "driver_neo4j.py").read_text(encoding="utf-8")
    assert "S_IRWXG" not in fuente and "S_IRWXO" not in fuente
    assert "inspect_secret_for_reading" in fuente


def test_el_preflight_del_ensayo_usa_la_misma_politica_y_no_exige_0600():
    t = PREFLIGHT.read_text(encoding="utf-8")
    assert "inspect_secret_for_reading" in t
    assert "se exige 0600" not in t
