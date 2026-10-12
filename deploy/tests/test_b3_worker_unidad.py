# -*- coding: utf-8 -*-
"""B3 (USABLE-V1) · H-02 / H-37 — la unidad CANONICA del worker y su instalacion.

ESTADO
------
::

    CODE         PASS      pasos 7 y 13 REALES de deploy.sh, unidad validada por efecto
    CALIBRATION  PASS      scripts/calibracion/mutaciones_b3_worker.py
    RC-E2E       PENDING   systemd real (enable/restart en una maquina), reinicio de maquina

ANTES (base 7841f85): `git log --all -- '*worker*.service'` vacio -- NUNCA
existio unidad ni timer del worker en ningun ref --; `deploy.sh` solo creaba
el venv del visor; `scripts/run-jobs-worker.sh` apuntaba al layout legacy y
buscaba un venv que nadie creaba; cuatro defaults de `jobs.db` (H-37).

QUE SE EJECUTA DE VERDAD
------------------------
* ``validate_worker_unit`` de ``validate_deploy.sh`` sobre la unidad del
  repositorio y una release de prueba con el venv del motor: el interprete de
  ``ExecStart`` se busca EN DISCO (una unidad que apunta a un venv inexistente
  tiene texto correcto y no corre nada).
* ``systemd-analyze verify`` sobre la unidad (exigido: no se omite).
* Los flags de ``ExecStart`` se parsean con el ``build_parser()`` REAL del
  worker.
* Los PASOS 7 y 13 de ``deploy.sh`` (texto real entre marcas unicas), con
  ``systemctl`` sustituido por una funcion que registra las llamadas.

LIMITE DECLARADO: la lectura de la unidad es textual (systemd no tiene AST);
``systemctl enable/restart`` reales y el reinicio de maquina son RC-E2E.
"""
from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from test_b2_fresh_install import _correr_bash, _tramo_de_deploy  # noqa: E402

RAIZ = _TESTS.parents[1]
_SCRIPTS = RAIZ / "deploy" / "scripts"
_DE_APP = RAIZ / "data-engine" / "app"
if str(_DE_APP) not in sys.path:
    sys.path.insert(0, str(_DE_APP))

from jobs import job_store  # noqa: E402

UNIDAD = RAIZ / "data-engine" / "systemd" / "s9-knowledge-worker.service"
UNIDAD_VISOR = RAIZ / "viewer" / "systemd" / "s9-knowledge-viewer.service"
VALIDATE_SH = _SCRIPTS / "validate_deploy.sh"
DEPLOY_SH = _SCRIPTS / "deploy.sh"
WORKER_ENV_EJEMPLO = RAIZ / "deploy" / "config" / "worker.env.example"
VIEWER_ENV_EJEMPLO = RAIZ / "deploy" / "config" / "viewer.env.example"
ROL_SYSTEMD = RAIZ / "deploy" / "ansible" / "roles" / "systemd"
ROL_COMMON_DEFAULTS = RAIZ / "deploy" / "ansible" / "roles" / "common" / "defaults" / "main.yml"
CURRENT = "/opt/s9-knowledge/current"
STATE_ROOT = "/var/lib/s9-knowledge"


# ---------------------------------------------------------------------------
# Lectura de la unidad
# ---------------------------------------------------------------------------

def _valor(texto: str, clave: str) -> str:
    vals = [l.split("=", 1)[1] for l in texto.splitlines() if l.startswith(clave + "=")]
    assert len(vals) == 1, "la unidad declara %s %d veces" % (clave, len(vals))
    return vals[0]


def _exec_start(texto: str) -> tuple:
    """(asignaciones env, interprete, script, flags) de ExecStart."""
    tokens = shlex.split(_valor(texto, "ExecStart"))
    assert tokens[0] == "/usr/bin/env", tokens
    asignaciones = {}
    i = 1
    while "=" in tokens[i] and not tokens[i].startswith("/"):
        k, v = tokens[i].split("=", 1)
        asignaciones[k] = v
        i += 1
    return asignaciones, tokens[i], tokens[i + 1], tokens[i + 2:]


def _env_de(fichero: Path) -> dict:
    datos = {}
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        if linea.strip() and not linea.lstrip().startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            datos[k.strip()] = v.strip()
    return datos


@pytest.fixture
def release(tmp_path) -> Path:
    """Una release con lo que la unidad necesita EN DISCO: el venv del motor
    (un python ejecutable de verdad) y el script del worker."""
    rel = tmp_path / "releases" / "abc1234-20261012"
    venv_bin = rel / "data-engine" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    os.symlink(sys.executable, venv_bin / "python")
    (rel / "data-engine" / "app" / "jobs").mkdir(parents=True)
    shutil.copy(_DE_APP / "jobs" / "worker.py", rel / "data-engine" / "app" / "jobs" / "worker.py")
    (rel / "data-engine" / "systemd").mkdir(parents=True)
    shutil.copy(UNIDAD, rel / "data-engine" / "systemd" / UNIDAD.name)
    (rel / "viewer" / "systemd").mkdir(parents=True)
    shutil.copy(UNIDAD_VISOR, rel / "viewer" / "systemd" / UNIDAD_VISOR.name)
    return rel


def _validar_unidad(unidad: Path, release: Path, worker_env: Path = None):
    guion = '. "%s"; rc=0; validate_worker_unit "%s" "%s" "%s" "%s" || rc=$?; echo "RC=${rc}"' % (
        VALIDATE_SH, unidad, CURRENT, release, worker_env or "")
    r = subprocess.run(["bash", "-c", guion], capture_output=True, text=True, timeout=60)
    rc = [int(l[3:]) for l in r.stdout.splitlines() if l.startswith("RC=")]
    assert rc, "el validador no devolvio rc: %r %r" % (r.stdout, r.stderr)
    return rc[0], r.stderr


# ===========================================================================
# 1. LA UNIDAD CANONICA, POR EFECTO
# ===========================================================================

def test_la_unidad_canonica_pasa_su_validador_por_efecto(release):
    rc, err = _validar_unidad(UNIDAD, release, WORKER_ENV_EJEMPLO)
    assert rc == 0, "la unidad canonica no pasa validate_worker_unit: %s" % err.replace("\n", " | ")


def test_sin_venv_del_motor_la_unidad_bloquea(release):
    """El defecto de B2: nadie creaba el venv del motor."""
    shutil.rmtree(release / "data-engine" / ".venv")
    rc, err = _validar_unidad(UNIDAD, release)
    assert rc == 1 and "no existe o no es ejecutable" in err, err


_DEFECTOS = [
    ("\nUser=www-data\n", "\nUser=root\n", "User="),
    ("\nUMask=0077\n", "\nUMask=0022\n", "UMask"),
    ("\nRestart=always\n", "\nRestart=on-failure\n", "Restart"),
    (" --loop ", " ", "--loop"),
    (" --loop ", " --loop --limit 1 ", "--limit"),
    (" --release-stale-seconds 600", "", "--release-stale-seconds"),
    ("EnvironmentFile=/etc/s9-knowledge/worker.env\n", "", "EnvironmentFile"),
    ("/data-engine/app/jobs/worker.py", "/data-engine/app/jobs/otro.py", "worker.py"),
]


@pytest.mark.parametrize("viejo,nuevo,causa", _DEFECTOS, ids=[d[2] + "->" + d[1].strip()[:20] for d in _DEFECTOS])
def test_cada_defecto_de_la_unidad_bloquea_con_su_causa(tmp_path, release, viejo, nuevo, causa):
    texto = UNIDAD.read_text(encoding="utf-8")
    assert texto.count(viejo) == 1, "DETECTOR ROTO: ancla %r no unica" % viejo
    mala = tmp_path / UNIDAD.name
    mala.write_text(texto.replace(viejo, nuevo), encoding="utf-8")
    rc, err = _validar_unidad(mala, release)
    assert rc == 1 and causa in err, "no bloqueo por %s:\n%s" % (causa, err)


def test_el_secreto_de_worker_env_distinto_del_de_la_unidad_bloquea(tmp_path, release):
    env = tmp_path / "worker.env"
    env.write_text("S9K_NEO4J_PASSWORD_FILE=/etc/s9-knowledge/secrets/otro\n", encoding="utf-8")
    rc, err = _validar_unidad(UNIDAD, release, env)
    assert rc == 1 and "secreto" in err, err


def test_systemd_analyze_verify_acepta_la_unidad_y_rechaza_un_binario_inexistente(tmp_path):
    """El paso 10 de deploy.sh, ejecutado. No se omite si falta la herramienta:
    un verify que no corre en CI seria un verde de papel."""
    assert shutil.which("systemd-analyze"), "systemd-analyze no disponible: el paso 10 no se mide"
    copia = tmp_path / UNIDAD.name
    shutil.copy(UNIDAD, copia)
    r = subprocess.run(["systemd-analyze", "verify", str(copia)], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    mala = tmp_path / "rota" / UNIDAD.name
    mala.parent.mkdir()
    mala.write_text(UNIDAD.read_text(encoding="utf-8").replace(
        "ExecStart=/usr/bin/env ", "ExecStart=/usr/bin/no-existe-b3 "), encoding="utf-8")
    r = subprocess.run(["systemd-analyze", "verify", str(mala)], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode != 0, "verify no distingue un ExecStart inexistente: %s" % r.stderr


def test_los_flags_de_execstart_son_los_del_worker_real():
    """Los flags se PARSEAN con el parser real: un flag que el worker no
    conoce haria morir el servicio en cada arranque."""
    from jobs import worker

    asignaciones, interprete, script, flags = _exec_start(UNIDAD.read_text(encoding="utf-8"))
    args = worker.build_parser().parse_args(flags)
    assert args.loop and not args.once, flags
    assert args.release_stale_seconds and args.release_stale_seconds > 0, flags
    assert "--limit" not in flags, flags
    assert interprete == CURRENT + "/data-engine/.venv/bin/python", interprete
    assert script == CURRENT + "/data-engine/app/jobs/worker.py", script
    # El latido por defecto cabe varias veces en el plazo de stale.
    assert min(30.0, args.release_stale_seconds / 4.0) * 2 < args.release_stale_seconds


# ===========================================================================
# 2. UNA SOLA FUENTE Y UN SOLO USUARIO (no repetir H-08)
# ===========================================================================

def test_hay_una_sola_plantilla_de_la_unidad_del_worker():
    encontradas = sorted(
        str(p.relative_to(RAIZ)) for p in RAIZ.rglob("*worker*.service*")
        if not {".git", ".claude"} & set(p.relative_to(RAIZ).parts))
    assert encontradas == ["data-engine/systemd/s9-knowledge-worker.service"], encontradas


def test_ansible_instala_la_misma_unidad_que_deploy_sh():
    tareas = yaml.safe_load((ROL_SYSTEMD / "tasks" / "main.yml").read_text(encoding="utf-8"))
    defaults = yaml.safe_load((ROL_SYSTEMD / "defaults" / "main.yml").read_text(encoding="utf-8"))
    assert defaults["s9k_worker_service"] == UNIDAD.name
    copias = [t["ansible.builtin.copy"] for t in tareas if "ansible.builtin.copy" in t
              and "worker" in str(t["ansible.builtin.copy"].get("dest"))]
    assert len(copias) == 1, copias
    copia = copias[0]
    assert copia["src"] == "{{ s9k_root }}/current/data-engine/systemd/{{ s9k_worker_service }}"
    assert copia.get("remote_src") is True
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    assert 'WORKER_UNIT_NAME="%s"' % UNIDAD.name in texto
    assert 'WORKER_UNIT_SRC="${RELEASE_DIR}/data-engine/systemd/${WORKER_UNIT_NAME}"' in texto


def test_el_usuario_de_la_unidad_es_el_usuario_del_servicio():
    texto = UNIDAD.read_text(encoding="utf-8")
    comunes = yaml.safe_load(ROL_COMMON_DEFAULTS.read_text(encoding="utf-8"))
    user, group = _valor(texto, "User"), _valor(texto, "Group")
    assert user != "root" and user == comunes["s9k_service_user"], user
    assert group == comunes["s9k_service_group"], group
    assert _valor(texto, "UMask") == "0077"
    previo = shlex.split(_valor(texto, "ExecStartPre").lstrip("+-"))
    assert previo[previo.index("-o") + 1] == user and previo[previo.index("-g") + 1] == group, previo


def test_el_secreto_que_copia_la_unidad_es_el_de_la_plantilla():
    texto = UNIDAD.read_text(encoding="utf-8")
    previo = shlex.split(_valor(texto, "ExecStartPre").lstrip("+-"))
    origen, destino = previo[-2], previo[-1]
    assert origen == _env_de(WORKER_ENV_EJEMPLO)["S9K_NEO4J_PASSWORD_FILE"], origen
    asignaciones, *_ = _exec_start(texto)
    assert asignaciones["S9K_NEO4J_PASSWORD_FILE"] == destino
    assert destino.startswith("/run/%s/" % _valor(texto, "RuntimeDirectory")), destino


# ===========================================================================
# 3. LOS PASOS REALES DE deploy.sh
# ===========================================================================

def test_paso2_crea_el_venv_del_motor_que_usa_la_unidad():
    tramo = _tramo_de_deploy("# Paso 2: verificar release", "# Paso 3: detectar layout/estado")
    _, interprete, _, _ = _exec_start(UNIDAD.read_text(encoding="utf-8"))
    venv = interprete[len(CURRENT) + 1:].rsplit("/bin/", 1)[0]
    assert 'python3 -m venv "${RELEASE_DIR}/%s"' % venv in tramo, (
        "deploy.sh no crea el venv que ejecuta la unidad (%s)" % venv)
    assert '"${RELEASE_DIR}/%s/bin/pip" install --quiet -r "${RELEASE_DIR}/data-engine/requirements.lock"' % venv in tramo


def _paso7(release: Path, worker_env: Path):
    cuerpo = """
HERE=%s
RELEASE_DIR=%s
S9K_ROOT=/opt/s9-knowledge
WORKER_ENV=%s
WORKER_UNIT_NAME=%s
%s
echo "WORKER_USER=${WORKER_USER} WORKER_GROUP=${WORKER_GROUP}"
""" % (_SCRIPTS, release, worker_env, UNIDAD.name,
       _tramo_de_deploy("# Paso 7: validar unidad nueva", "# --- fin del paso 7 ---"))
    r = _correr_bash(cuerpo, {})
    return r.returncode, r.stdout + r.stderr


def test_paso7_real_valida_la_unidad_y_lee_el_usuario_de_ella(release):
    rc, out = _paso7(release, WORKER_ENV_EJEMPLO)
    assert rc == 0 and "TRAMO_SUPERADO" in out, out
    assert "WORKER_USER=www-data WORKER_GROUP=www-data" in out, out


def test_paso7_real_bloquea_sin_el_venv_del_motor(release):
    shutil.rmtree(release / "data-engine" / ".venv")
    rc, out = _paso7(release, WORKER_ENV_EJEMPLO)
    assert rc != 0 and "TRAMO_SUPERADO" not in out, out
    assert "no existe o no es ejecutable" in out, out


def _paso13(tmp: Path, modo: str = "upgrade", jobs_previa: bool = True):
    import grp
    import pwd

    state = tmp / "state"
    jobs_db = Path(job_store.ruta_de_despliegue(str(state)))
    if jobs_previa:
        jobs_db.parent.mkdir(parents=True)
        jobs_db.write_text("", encoding="utf-8")
        jobs_db.chmod(0o644)
    props = state / "reviews-v3" / "proposals"
    worker_env = tmp / "worker.env"
    worker_env.write_text("S9K_V3_REVIEW_PROPOSALS_DIR=%s\n" % props, encoding="utf-8")
    llamadas = tmp / "systemctl.log"
    cuerpo = """
systemctl() { echo "$*" >> %s; }
sleep() { :; }
MODE=%s
NEW_JOBS_DB=%s
WORKER_ENV=%s
WORKER_UNIT_NAME=%s
WORKER_USER=%s
WORKER_GROUP=%s
%s
""" % (llamadas, modo, jobs_db, worker_env, UNIDAD.name,
       pwd.getpwuid(os.getuid()).pw_name, grp.getgrgid(os.getgid()).gr_name,
       _tramo_de_deploy("# Paso 13: reiniciar solo servicios afectados", "# --- fin del paso 13 ---"))
    r = _correr_bash(cuerpo, {})
    lineas = llamadas.read_text(encoding="utf-8").splitlines() if llamadas.exists() else []
    return r.returncode, r.stdout + r.stderr, lineas, jobs_db, props


@pytest.mark.parametrize("modo", ["upgrade", "fresh"])
def test_paso13_real_habilita_y_arranca_el_worker_antes_que_el_visor(tmp_path, modo):
    rc, out, llamadas, jobs_db, props = _paso13(tmp_path, modo)
    assert rc == 0 and "TRAMO_SUPERADO" in out, out
    w_enable = "enable %s" % UNIDAD.name
    w_restart = "restart %s" % UNIDAD.name
    assert w_enable in llamadas, ("el worker no se habilita en %s: no volveria tras "
                                  "reiniciar la maquina: %s" % (modo, llamadas))
    assert w_restart in llamadas, llamadas
    v_restart = llamadas.index("restart s9-knowledge-viewer.service")
    assert llamadas.index(w_restart) < v_restart, llamadas
    assert props.is_dir() and jobs_db.parent.is_dir()
    assert (jobs_db.parent.stat().st_mode & 0o777) == 0o750


def test_worker_activo_exige_active_en_todas_las_lecturas(tmp_path):
    marca = tmp_path / "n"
    cuerpo = """
systemctl() { n=$(cat %s 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > %s; [ "$n" -ne 2 ]; }
sleep() { :; }
if worker_activo s9-knowledge-worker.service 3 0; then echo ACTIVO; else echo NO_ACTIVO; fi
""" % (marca, marca)
    r = _correr_bash(cuerpo, {})
    assert "NO_ACTIVO" in r.stdout, r.stdout + r.stderr


# ===========================================================================
# 4. H-37: UNA SOLA AUTORIDAD SOBRE LA RUTA DE jobs.db
# ===========================================================================

def test_deploy_sh_pide_la_ruta_de_jobs_db_a_job_store(tmp_path):
    tramo = _tramo_de_deploy('JOB_STORE_PY="${HERE}/../../data-engine/app/jobs/job_store.py"',
                             '|| die "job_store no resolvió la ruta de jobs.db del despliegue"')
    raiz = tmp_path / "otro-state-root"
    cuerpo = 'HERE=%s\nS9K_STATE_ROOT=%s\n%s\necho "NEW_JOBS_DB=${NEW_JOBS_DB}"\n' % (
        _SCRIPTS, raiz, tramo)
    r = _correr_bash(cuerpo, {})
    assert r.returncode == 0, r.stdout + r.stderr
    esperado = job_store.ruta_de_despliegue(str(raiz))
    assert "NEW_JOBS_DB=%s\n" % esperado in r.stdout, (
        "DEFAULT DIVERGENTE: deploy.sh resuelve jobs.db a algo distinto de "
        "job_store.ruta_de_despliegue (%s):\n%s" % (esperado, r.stdout))


def test_las_plantillas_declaran_la_ruta_de_job_store():
    esperado = job_store.ruta_de_despliegue(STATE_ROOT)
    visor, worker_env = _env_de(VIEWER_ENV_EJEMPLO), _env_de(WORKER_ENV_EJEMPLO)
    assert visor["S9K_JOBS_DB"] == esperado, ("DEFAULT DIVERGENTE en viewer.env.example: %s"
                                              % visor["S9K_JOBS_DB"])
    assert worker_env["S9K_JOBS_DB"] == esperado, ("DEFAULT DIVERGENTE en worker.env.example: %s"
                                                   % worker_env["S9K_JOBS_DB"])
    assert worker_env["S9K_V3_REVIEW_PROPOSALS_DIR"] == visor["S9K_V3_REVIEW_PROPOSALS_DIR"]


def test_ningun_otro_modulo_del_producto_define_un_default_de_jobs_db():
    """Por AST: una constante que termina en `jobs.db` con ruta, fuera de la
    autoridad, es un quinto default. El lanzador legacy ya no existe."""
    assert not (RAIZ / "scripts" / "run-jobs-worker.sh").exists(), (
        "scripts/run-jobs-worker.sh (layout legacy, su propio default) ha vuelto")
    autoridad = (_DE_APP / "jobs" / "job_store.py").resolve()
    culpables = []
    for raiz in (RAIZ / "data-engine" / "app", RAIZ / "viewer" / "app"):
        for f in raiz.rglob("*.py"):
            if "tests" in f.parts or f.resolve() == autoridad:
                continue
            for nodo in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
                        and re.search(r"[/\\]jobs\.db$", nodo.value)):
                    culpables.append("%s:%s" % (f.relative_to(RAIZ), nodo.lineno))
    assert not culpables, culpables
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    literales = [l for l in texto.splitlines() if "jobs.db" in l and not l.lstrip().startswith("#")
                 and "LEGACY" not in l and "job_store" not in l]
    assert not literales, "deploy.sh escribe su propio jobs.db: %s" % literales
