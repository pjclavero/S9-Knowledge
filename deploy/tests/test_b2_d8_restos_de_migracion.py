# -*- coding: utf-8 -*-
"""D-8 — restos `.migrando-*` de una migracion interrumpida (SIGKILL real).

Defecto medido en la base b4e396d: si ``migrar_estado.py`` muere (SIGKILL) justo tras crear el
temporal de la copia, queda ``<dir>/.migrando-<pid>-<fichero>``. La siguiente ejecucion converge
PERO lo deja ahi para siempre (lo adopta con chown/chmod) y sin decir nada.

Contrato:
  * demostrablemente propio e incompleto/redundante -> se retira y se DICE (linea ``RESTO``);
  * no demostrable (podria ser el unico ejemplar de un dato, dueno ajeno, otra migracion
    viva) -> STOP[RESTO_DE_MIGRACION] con receta, y el fichero NO se toca;
  * el arranque nombra el resto en su diagnostico.

El SIGKILL es REAL: un proceso hijo se mata a si mismo en el punto exacto (justo despues de
``os.open`` del temporal), no se simula una excepcion.
"""
from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
MIGRAR_PY = RAIZ / "deploy" / "scripts" / "migrar_estado.py"
SS_PY = RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"
UID, GID = os.getuid(), os.getgid()


def _cargar(nombre, ruta):
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = m
    spec.loader.exec_module(m)
    return m


ss = _cargar("_s9k_service_state", SS_PY)
mg = _cargar("_s9k_migrar_estado", MIGRAR_PY)

CONTENIDO = b'{"d":1}\n' * 500


class Mundo:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.state = tmp / "state"
        self.release = tmp / "rel"
        self.rv3_rel = self.release / "viewer" / "output" / "reviews-v3"
        self.rv3 = self.state / "reviews-v3"
        self.rv3.mkdir(parents=True)
        self.rv3_rel.mkdir(parents=True)
        (self.rv3_rel / "decisions.jsonl").write_bytes(CONTENIDO)
        self.state.chmod(0o700)
        self.rv3.chmod(0o700)
        self.env = {
            "S9K_STATE_ROOT": str(self.state),
            "S9K_V3_REVIEW_DATABASE_PATH": str(self.rv3 / "review.sqlite3"),
            "S9K_V3_REVIEW_PROPOSALS_DIR": str(self.rv3 / "proposals"),
            "S9K_AUTH_DB_PATH": str(self.state / "auth" / "auth.db"),
            "S9K_JOBS_DB": str(self.state / "jobs" / "jobs.db"),
        }

    def aplicar(self, **kw):
        kw.setdefault("releases", [str(self.release)])
        kw.setdefault("release_id", "r2")
        kw.setdefault("uid", UID)
        kw.setdefault("gid", GID)
        return mg.aplicar(str(self.state), self.env, **kw)

    def resto(self, pid: int, contenido: bytes, nombre="decisions.jsonl") -> Path:
        p = self.rv3 / (".migrando-%d-%s" % (pid, nombre))
        p.write_bytes(contenido)
        p.chmod(0o600)
        return p


@pytest.fixture
def mundo(tmp_path):
    return Mundo(tmp_path)


def _pid_muerto() -> int:
    """Un PID que ya no existe (hijo terminado y recogido)."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


HIJO_SIGKILL = textwrap.dedent("""
    import os, sys, signal, importlib.util
    spec = importlib.util.spec_from_file_location("mg", sys.argv[1])
    mg = importlib.util.module_from_spec(spec); sys.modules["mg"] = mg; spec.loader.exec_module(mg)
    state, rel = sys.argv[2], sys.argv[3]
    env = {"S9K_STATE_ROOT": state,
           "S9K_V3_REVIEW_DATABASE_PATH": state + "/reviews-v3/review.sqlite3",
           "S9K_V3_REVIEW_PROPOSALS_DIR": state + "/reviews-v3/proposals",
           "S9K_AUTH_DB_PATH": state + "/auth/auth.db", "S9K_JOBS_DB": state + "/jobs/jobs.db"}
    real = os.open
    def op(p, *a, **k):
        fd = real(p, *a, **k)
        if os.path.basename(str(p)).startswith(".migrando-"):
            os.kill(os.getpid(), signal.SIGKILL)   # EXACTAMENTE tras crear el temporal
        return fd
    os.open = op
    mg.aplicar(state, env, releases=[rel], release_id="r1", uid=os.getuid(), gid=os.getgid())
    sys.exit(0)   # si llega aqui, el SIGKILL no se produjo
""")


def _matar_en_el_temporal(mundo: Mundo) -> int:
    r = subprocess.run([sys.executable, "-c", HIJO_SIGKILL, str(MIGRAR_PY), str(mundo.state),
                        str(mundo.release)], capture_output=True, text=True)
    assert r.returncode == -signal.SIGKILL, "no murio por SIGKILL en el punto: rc=%r %s" % (r.returncode, r.stderr)
    return r.returncode


def test_D8_SIGKILL_real_deja_un_resto_y_la_siguiente_ejecucion_lo_retira_y_lo_dice(mundo):
    _matar_en_el_temporal(mundo)
    restos = list(mundo.rv3.glob(".migrando-*"))
    assert len(restos) == 1, "el SIGKILL no dejo el resto que se quiere tratar: %r" % restos
    assert (mundo.rv3_rel / "decisions.jsonl").read_bytes() == CONTENIDO  # el original, intacto
    r = mundo.aplicar()
    assert r.rc == 0, r.lineas
    assert any(l.startswith("RESTO:") and restos[0].name in l and "vacio" in l for l in r.lineas), \
        "SIN LINEA RESTO: %s" % r.lineas
    assert not list(mundo.rv3.glob(".migrando-*")), "el resto sigue ahi"
    # y la migracion hizo su trabajo sin perder nada
    assert (mundo.rv3 / "decisions.jsonl").read_bytes() == CONTENIDO
    assert (mundo.rv3_rel / "decisions.jsonl.migrado-r2").read_bytes() == CONTENIDO


def test_D8_resto_parcial_prefijo_del_original_se_retira(mundo):
    resto = mundo.resto(_pid_muerto(), CONTENIDO[:777])
    r = mundo.aplicar()
    assert r.rc == 0, r.lineas
    assert not resto.exists()
    assert any("prefijo" in l and "original" in l for l in r.lineas if l.startswith("RESTO:")), r.lineas
    assert (mundo.rv3 / "decisions.jsonl").read_bytes() == CONTENIDO


def test_D8_resto_prefijo_del_destino_ya_publicado_se_retira(mundo):
    # el original ya se retiro en una ejecucion anterior; el resto sobrevivio
    (mundo.rv3 / "decisions.jsonl").write_bytes(CONTENIDO)
    (mundo.rv3 / "decisions.jsonl").chmod(0o600)
    (mundo.rv3_rel / "decisions.jsonl").unlink()
    resto = mundo.resto(_pid_muerto(), CONTENIDO[:100])
    r = mundo.aplicar()
    assert r.rc == 0, r.lineas
    assert not resto.exists()
    assert any("destino ya publicado" in l for l in r.lineas if l.startswith("RESTO:")), r.lineas


def test_D8_resto_con_contenido_que_no_se_demuestra_redundante_PARA_y_no_se_toca(mundo):
    resto = mundo.resto(_pid_muerto(), b"datos que no estan en ningun otro sitio\n")
    antes = resto.read_bytes()
    r = mundo.aplicar()
    assert r.rc == 3 and "STOP[RESTO_DE_MIGRACION]" in r.lineas[-1], "NO PARO: rc=%s %s" % (r.rc, r.lineas)
    ultima = r.lineas[-1]
    assert str(resto) in ultima and "Receta" in ultima and "unico ejemplar" in ultima, ultima
    assert resto.read_bytes() == antes, "el resto se toco (o se perdio)"
    # nada se movio: el original sigue donde estaba
    assert (mundo.rv3_rel / "decisions.jsonl").read_bytes() == CONTENIDO
    assert not (mundo.rv3 / "decisions.jsonl").exists()


def test_D8_el_stop_no_revela_contenido_del_resto(mundo):
    resto = mundo.resto(_pid_muerto(), b"CONTENIDO-SENSIBLE-123\n")
    r = mundo.aplicar()
    assert r.rc == 3 and "CONTENIDO-SENSIBLE-123" not in "\n".join(r.lineas), "NO PARO: rc=%s" % r.rc
    assert resto.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="como root el dueno 0 SI es propio")
def test_D8_resto_de_dueno_ajeno_PARA(mundo):
    resto = mundo.resto(_pid_muerto(), b"")
    # simula "ni root ni el servicio": el servicio es otro uid distinto del dueno real del fichero
    r = mundo.aplicar(uid=UID + 1, gid=GID)
    assert r.rc == 3 and "STOP[RESTO_DE_MIGRACION]" in r.lineas[-1] and "dueno" in r.lineas[-1], \
        "NO PARO: rc=%s %s" % (r.rc, r.lineas)
    assert resto.exists()


def test_D8_otra_migracion_viva_dueña_del_resto_PARA(mundo):
    # un proceso VIVO cuya linea de comandos es migrar_estado: hay otra migracion en curso
    vivo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "migrar_estado"])
    try:
        resto = mundo.resto(vivo.pid, b"")
        r = mundo.aplicar()
        assert r.rc == 3 and "STOP[RESTO_DE_MIGRACION]" in r.lineas[-1] and "en curso" in r.lineas[-1], \
            "NO PARO: rc=%s %s" % (r.rc, r.lineas)
        assert resto.exists()
    finally:
        vivo.kill()
        vivo.wait()


def test_D8_pid_reutilizado_por_otro_programa_no_bloquea(mundo):
    # vivo, pero NO es migrar_estado: el PID se reutilizo; no es otra migracion
    vivo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        resto = mundo.resto(vivo.pid, b"")
        r = mundo.aplicar()
        assert r.rc == 0 and not resto.exists(), r.lineas
    finally:
        vivo.kill()
        vivo.wait()


def test_D8_un_symlink_con_nombre_de_temporal_no_se_retira(mundo):
    objetivo = mundo.tmp / "otro.txt"
    objetivo.write_bytes(b"x")
    enlace = mundo.rv3 / (".migrando-%d-decisions.jsonl" % _pid_muerto())
    enlace.symlink_to(objetivo)
    r = mundo.aplicar()
    assert r.rc == 3, r.lineas
    assert enlace.is_symlink() and objetivo.read_bytes() == b"x"


def test_D8_sin_restos_no_cambia_nada_ni_dice_RESTO(mundo):
    r = mundo.aplicar()
    assert r.rc == 0 and not any(l.startswith("RESTO:") for l in r.lineas), r.lineas


def test_D8_el_diagnostico_de_arranque_nombra_el_resto(mundo):
    p = mundo.rv3 / (".migrando-%d-decisions.jsonl" % 4242)
    v = ss.Violation(ss.OWNER, str(p), "tiene owner root:root; esperado s9knowledge:s9knowledge")
    texto = ss.format_violations([v])
    assert "resto de una migracion interrumpida" in texto and str(p) in texto
    normal = ss.format_violations([ss.Violation(ss.MODE, str(mundo.rv3 / "decisions.jsonl"), "modo 0644")])
    assert "resto de una migracion" not in normal


def test_D8_la_copia_y_el_reconocimiento_comparten_la_autoridad_del_nombre(mundo):
    nombre = ss.MIGRATION_TEMP_TEMPLATE % (1234, "x.jsonl")
    m = ss.MIGRATION_TEMP_RE.match(nombre)
    assert m and m.group(1) == "1234" and m.group(2) == "x.jsonl"
