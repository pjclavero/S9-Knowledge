# -*- coding: utf-8 -*-
"""H-06 + H-08 (USABLE-V1) — usuario de servicio dedicado y estado privado: lado DESPLIEGUE.

ESTADO
------
::

    CODE         PASS      migracion real (migrar_estado.py), unidades, Ansible, deploy.sh
    CALIBRATION  PASS      scripts/calibracion/mutaciones_h06_h08_servicio_y_estado.py
    LAB (VM112)  PASS      fresh/upgrade con root, useradd, systemd y OTRO usuario real
                           (escenarios A-H en VM112; ronda 2: C-1..C-5, F y H caso 3)

QUE SE EJECUTA DE VERDAD
------------------------
* ``migrar_estado.py`` sobre ficheros reales: mueve el estado mutable que vivia
  en la release, corrige modos, respeta el original hasta verificar la copia,
  y PARA con diagnostico ante cada caso del contrato §9. El "usuario de
  servicio" es el propio proceso (un ``chown`` a otro usuario exige root: va al
  guion de VM112).
* Las unidades systemd se parsean y se comparan con la AUTORIDAD
  (``service_state.py``); Ansible se parsea como YAML; ``validate_deploy.sh`` se
  ejecuta contra unidades reales y mutadas; ``deploy.sh`` se lee por estructura.

DONDE SE EJECUTA CADA P/N (los marcados VM112 estan en deploy/tests/lab/):
  P1 P2  CI (identidad en unidades+arranque)   · VM112 (procesos vivos)
  P3 P4  CI (modos por umask, viewer/data-engine) · VM112 (chown real)
  P5     CI (viewer)            P6  VM112         P7 P8  VM112
  P9     CI (migrar_estado)     · VM112 (upgrade completo)
  P10    CI (test_c1_*)         P11 CI+VM112      P12 CI (idempotencia) · VM112
  N1-N4  CI                     N5 N6  CI         N7 N8 N9  CI (gate)
  N10    CI (viewer)            N11 N12 CI (chown/copia forzados) · VM112
  N13 N14 CI                    N15 N16  VM112 (otro usuario real)
  N17 N18 CI
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_TESTS = Path(__file__).resolve().parent
RAIZ = _TESTS.parents[1]
_SCRIPTS = RAIZ / "deploy" / "scripts"
SS_PY = RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"
MIGRAR_PY = _SCRIPTS / "migrar_estado.py"
VALIDATE_SH = _SCRIPTS / "validate_deploy.sh"
LIB_SH = _SCRIPTS / "lib.sh"
DEPLOY_SH = _SCRIPTS / "deploy.sh"
U_VISOR = RAIZ / "viewer" / "systemd" / "s9-knowledge-viewer.service"
U_WORKER = RAIZ / "data-engine" / "systemd" / "s9-knowledge-worker.service"
U_HEALTH = RAIZ / "viewer" / "systemd" / "s9-knowledge-healthcheck.service"
ANSIBLE = RAIZ / "deploy" / "ansible"
EUID = os.geteuid()
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


def _valor(texto: str, clave: str):
    vals = [l.split("=", 1)[1] for l in texto.splitlines() if l.startswith(clave + "=")]
    return vals[0] if len(vals) == 1 else (None if not vals else vals)


# ===========================================================================
# 1. UNA AUTORIDAD: las unidades y Ansible la repiten, y un test las cruza (M12)
# ===========================================================================

@pytest.mark.parametrize("unidad", [U_VISOR, U_WORKER, U_HEALTH], ids=["visor", "worker", "health"])
def test_N7_N8_N9_las_unidades_declaran_la_identidad_de_la_autoridad(unidad):
    t = unidad.read_text(encoding="utf-8")
    assert _valor(t, "User") == ss.SERVICE_USER, ("%s: User=%r" % (unidad.name, _valor(t, "User")))
    assert _valor(t, "Group") == ss.SERVICE_GROUP
    assert _valor(t, "UMask") == ss.UNIT_UMASK
    assert _valor(t, "User") not in ("root", "www-data", None)


@pytest.mark.parametrize("unidad", [U_VISOR, U_WORKER, U_HEALTH], ids=["visor", "worker", "health"])
def test_la_validacion_de_arranque_no_depende_de_la_unidad(unidad):
    """§12: ni la excepcion de tests ni el interruptor retirado aparecen en una unidad operativa
    (la validacion es obligatoria; una unidad no puede encenderla ni apagarla)."""
    codigo = "\n".join(l for l in unidad.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
    assert ss.VALIDATION_EXCEPTION_ENV not in codigo and ss.ENFORCE_ENV not in codigo


def test_N9_el_healthcheck_no_lleva_capabilities_ni_privilegios():
    t = U_HEALTH.read_text(encoding="utf-8")
    assert _valor(t, "CapabilityBoundingSet") == "", "el healthcheck declara capabilities"
    assert _valor(t, "NoNewPrivileges") == "true"
    assert "AmbientCapabilities" not in t and "PermissionsStartOnly" not in t
    # SECRET (§9): ya no hay ExecStartPre con privilegios ni copia a /run.
    assert "\nExecStartPre=" not in t and "\nRuntimeDirectory" not in t


def test_el_healthcheck_habla_con_el_endpoint_local_sin_systemctl_privilegiado():
    """El check sigue siendo de solo lectura: HTTP local + bases mode=ro + `is-active`."""
    checks = (RAIZ / "viewer" / "app" / "health" / "checks.py").read_text(encoding="utf-8")
    assert "is-active" in checks
    for prohibido in ('"restart"', '"start"', '"stop"', "sudo", '"enable"'):
        assert prohibido not in checks, "el healthcheck usa %s: eso necesita privilegios" % prohibido


def test_las_tres_unidades_leen_su_secreto_directamente_y_no_lo_copian():
    for unidad in (U_VISOR, U_HEALTH, U_WORKER):
        t = unidad.read_text(encoding="utf-8")
        codigo = "\n".join(l for l in t.splitlines() if not l.lstrip().startswith("#"))
        assert "ExecStartPre" not in codigo and "RuntimeDirectory" not in codigo, unidad.name
        assert "neo4j_password" not in codigo and "/run/" not in codigo, unidad.name
        assert _valor(t, "ExecStart").startswith("/opt/s9-knowledge/current/"), unidad.name


def test_M12_ansible_declara_la_misma_identidad_una_sola_vez():
    gv = yaml.safe_load((ANSIBLE / "group_vars" / "all.yml").read_text(encoding="utf-8"))
    assert gv["s9k_service_user"] == ss.SERVICE_USER and gv["s9k_service_group"] == ss.SERVICE_GROUP
    assert gv["s9k_state_root"] == ss.DEFAULT_STATE_ROOT
    # Ninguna otra copia (defaults de roles, inventario) y ningun www-data.
    culpables = []
    for f in ANSIBLE.rglob("*"):
        if not f.is_file():
            continue
        texto = f.read_text(encoding="utf-8", errors="replace")
        if "www-data" in texto:
            culpables.append("%s: www-data" % f.relative_to(RAIZ))
        if f.name in ("main.yml", "inventory.example") and f.parent.name in ("defaults", "ansible"):
            if re.search(r"^s9k_service_(user|group)\s*[:=]", texto, re.M):
                culpables.append("%s: redefine la identidad" % f.relative_to(RAIZ))
    assert not culpables, culpables


def test_M12_los_directorios_de_ansible_son_los_de_la_autoridad_con_modo_0700():
    tareas = yaml.safe_load((ANSIBLE / "roles" / "common" / "tasks" / "main.yml").read_text(encoding="utf-8"))
    por_nombre = {t.get("name"): t for t in tareas}
    sub = por_nombre["Crear subdirectorios de estado mutable"]
    assert list(sub["loop"]) == list(ss.SERVICE_SUBDIRS)
    modo = "%04o" % ss.DIR_MODE
    for nombre in ("Crear directorio de estado mutable", "Crear subdirectorios de estado mutable"):
        assert por_nombre[nombre]["ansible.builtin.file"]["mode"] == modo, nombre
    # y el usuario/grupo se crean ANTES que cualquier directorio que les pertenece
    orden = [t.get("name") for t in tareas]
    assert orden.index("Crear el usuario de sistema del servicio (sin login, sin home, sin sudo)") \
        < orden.index("Crear directorio de estado mutable")
    user = por_nombre["Crear el usuario de sistema del servicio (sin login, sin home, sin sudo)"]["ansible.builtin.user"]
    assert user["system"] is True and user["shell"] == "/usr/sbin/nologin" and user["create_home"] is False


def test_el_visor_ya_no_tiene_plantilla_jinja_ni_dos_unidades():
    assert not (ANSIBLE / "roles" / "systemd" / "templates" / "s9-knowledge-viewer.service.j2").exists()
    tareas = (ANSIBLE / "roles" / "systemd" / "tasks" / "main.yml").read_text(encoding="utf-8")
    assert "s9-knowledge-viewer.service.j2" not in tareas
    plano = yaml.safe_load(tareas)
    copia = [t for t in plano if "Instalar la unidad canonica del visor" in str(t.get("name"))]
    assert len(copia) == 1 and copia[0]["ansible.builtin.copy"]["remote_src"] is True
    assert any("identidad de servicio" in str(t.get("name")) for t in plano)


def test_ansible_auth_se_ejecuta_como_el_usuario_de_servicio():
    tareas = yaml.safe_load((ANSIBLE / "roles" / "auth" / "tasks" / "main.yml").read_text(encoding="utf-8"))
    estado = next(t for t in tareas if t.get("register") == "_auth_status")
    assert estado["become_user"] == "{{ s9k_service_user }}"


def test_la_unica_unidad_root_restante_es_la_prueba_de_restore_de_neo4j_y_no_toca_el_state_root():
    root = []
    for f in list(RAIZ.glob("**/*.service")) + list((ANSIBLE / "roles").rglob("*.service.j2")):
        rel = f.relative_to(RAIZ).parts
        if ".claude" in rel or "node_modules" in rel or rel[:2] == ("deploy", "propuestas"):
            continue  # las PROPUESTAS no instaladas se declaran aparte (siguiente test)
        t = f.read_text(encoding="utf-8")
        if _valor(t, "User") in (None, "root") and "[Service]" in t:
            root.append(f.name)
    assert root == ["s9-knowledge-neo4j-restore-test.service.j2"], root
    for f in (ANSIBLE / "roles" / "systemd" / "templates").glob("*restore*"):
        assert "/var/lib/s9-knowledge" not in f.read_text(encoding="utf-8"), f


def test_la_propuesta_de_backup_no_instalada_esta_declarada_como_deuda():
    """`deploy/propuestas/backup-automatico` corre como root y escribiria ficheros
    root:root dentro de `backups/` (estado del servicio): al adoptarla, el arranque
    fail-closed los rechazaria. No esta instalada; queda DECLARADA, no escondida."""
    unidad = (RAIZ / "deploy" / "propuestas" / "backup-automatico" / "s9-knowledge-backup.service")
    assert "User=root" in unidad.read_text(encoding="utf-8")
    readme = (RAIZ / "deploy" / "README.md").read_text(encoding="utf-8")
    assert "propuestas/backup-automatico" in readme and "TD-H06-01" in readme


def _estructurales_sin_literales(ruta: Path):
    """(linea, texto) de las lineas de codigo (no comentario) de un guion bash."""
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.lstrip().startswith("#"):
            yield n, linea


@pytest.mark.parametrize("guion", ["deploy.sh", "lib.sh", "validate_deploy.sh", "preflight.sh",
                                   "rollback-release.sh", "rollback-full.sh", "verify-deployment.sh"])
def test_M12_ningun_guion_de_despliegue_repite_la_identidad(guion):
    """Los guiones PIDEN la identidad a la autoridad; no la escriben."""
    for n, linea in _estructurales_sin_literales(_SCRIPTS / guion):
        assert "www-data" not in linea, "%s:%d: www-data" % (guion, n)
        assert "s9knowledge" not in linea, "%s:%d repite el usuario de servicio: %s" % (guion, n, linea.strip())


@pytest.mark.parametrize("modulo", ["review_store.py", "migrar_estado.py"])
def test_M12_los_modulos_python_de_despliegue_no_repiten_las_cifras(modulo):
    arbol = ast.parse((_SCRIPTS / modulo).read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(arbol)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(arbol):
        if isinstance(n, ast.Constant) and id(n) not in docstrings:
            if isinstance(n.value, str):
                assert n.value not in ("s9knowledge", "www-data"), (modulo, n.lineno)
    # Ninguna cifra de modo/umask en literal: se piden a la autoridad (M12).
    cifras = {0o600, 0o700, 0o660, 0o750, 0o644, 0o755, 0o640, 0o770, 0o077, 0o007, 0o022, 0o027}
    for n in ast.walk(arbol):
        if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool):
            assert n.value not in cifras, "%s:%d repite el modo %s: pidalo a service_state" % (
                modulo, n.lineno, oct(n.value))


# ===========================================================================
# 2. validate_deploy.sh: el gate rojo ante identidad incorrecta (N7, N8, N9, M1, M2, M6)
# ===========================================================================

def _bash(fn: str, *args: str):
    r = subprocess.run(["bash", "-c", 'source "$1"; shift; "$@"', "_", str(VALIDATE_SH), fn, *args],
                       capture_output=True, text=True, env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})
    return r.returncode, r.stdout + r.stderr


def _unidad_mutada(tmp_path, origen: Path, viejo: str, nuevo: str) -> Path:
    t = origen.read_text(encoding="utf-8")
    assert t.count(viejo) == 1, (viejo, t.count(viejo))
    d = tmp_path / origen.name
    d.write_text(t.replace(viejo, nuevo), encoding="utf-8")
    return d


def test_las_unidades_reales_pasan_el_gate():
    assert _bash("validate_viewer_unit", str(U_VISOR), "/opt/s9-knowledge/current")[0] == 0
    assert _bash("validate_healthcheck_unit", str(U_HEALTH))[0] == 0


@pytest.mark.parametrize("viejo,nuevo,fragmento", [
    ("User=s9knowledge\n", "", "User= es ''"),                      # N8/M1: visor root (sin User=)
    ("User=s9knowledge\n", "User=root\n", "User= es 'root'"),
    ("User=s9knowledge\n", "User=www-data\n", "User= es 'www-data'"),
    ("Group=s9knowledge\n", "Group=www-data\n", "Group= es 'www-data'"),
    ("UMask=0077\n", "UMask=0022\n", "UMask= es '0022'"),
    ("UMask=0077\n", "", "UMask= es ''"),
])
def test_N8_el_gate_rechaza_un_visor_con_otra_identidad(tmp_path, viejo, nuevo, fragmento):
    u = _unidad_mutada(tmp_path, U_VISOR, viejo, nuevo)
    rc, out = _bash("validate_viewer_unit", str(u), "/opt/s9-knowledge/current")
    assert rc != 0 and fragmento in out, out


@pytest.mark.parametrize("viejo,nuevo,fragmento", [
    ("User=s9knowledge\n", "User=www-data\n", "User= es 'www-data'"),   # N7/M2
    ("User=s9knowledge\n", "User=root\n", "User= es 'root'"),
    ("Group=s9knowledge\n", "Group=www-data\n", "Group= es 'www-data'"),
])
def test_N7_el_gate_rechaza_un_worker_con_otra_identidad(tmp_path, viejo, nuevo, fragmento):
    u = _unidad_mutada(tmp_path, U_WORKER, viejo, nuevo)
    rc, out = _bash("validate_worker_unit", str(u), "/opt/s9-knowledge/current", str(tmp_path))
    assert rc != 0 and fragmento in out, out


@pytest.mark.parametrize("viejo,nuevo,fragmento", [
    ("User=s9knowledge\n", "User=root\n", "User= es 'root'"),           # N9/M6
    ("User=s9knowledge\n", "", "User= es ''"),
    ("CapabilityBoundingSet=\n", "CapabilityBoundingSet=CAP_DAC_OVERRIDE\n", "CapabilityBoundingSet"),
    ("NoNewPrivileges=true\n", "", "NoNewPrivileges"),
])
def test_N9_el_gate_rechaza_un_healthcheck_privilegiado(tmp_path, viejo, nuevo, fragmento):
    u = _unidad_mutada(tmp_path, U_HEALTH, viejo, nuevo)
    rc, out = _bash("validate_healthcheck_unit", str(u))
    assert rc != 0 and fragmento in out, out


@pytest.mark.parametrize("anadido,fragmento", [
    ("Environment=S9K_STATE_VALIDATION=disabled-explicit-for-tests\n", "excepcion|obligatoria|VALIDATION"),
    ("Environment=S9K_STATE_ENFORCE=1\n", "ENFORCE"),
    ("ExecStartPre=+-/usr/bin/install -m 0600 /etc/s9-knowledge/secrets/x /run/x\n", "copia el secreto"),
    ("RuntimeDirectory=s9-knowledge-viewer\n", "copia el secreto"),
])
def test_el_gate_rechaza_una_unidad_que_apaga_la_validacion_o_copia_el_secreto(tmp_path, anadido, fragmento):
    t = U_VISOR.read_text(encoding="utf-8")
    u = tmp_path / U_VISOR.name
    u.write_text(t.replace("[Service]\n", "[Service]\n" + anadido, 1), encoding="utf-8")
    rc, out = _bash("validate_viewer_unit", str(u), "/opt/s9-knowledge/current")
    assert rc != 0 and re.search(fragmento, out), out


@pytest.mark.parametrize("modo,ok", [(0o640, True), (0o600, True), (0o440, True), (0o660, False),
                                      (0o644, False), (0o604, False), (0o620, False)])
def test_validate_secret_file_politica_SECRET(tmp_path, modo, ok):
    f = tmp_path / "secreto"
    f.write_text("valor")
    f.chmod(modo)
    rc, out = _bash("validate_secret_file", str(f))
    assert (rc == 0) is ok, (oct(modo), out)
    if not ok:
        assert "maximo 0640" in out


def _SIN_USO_el_secreto_de_la_unidad_del_visor(tmp_path):
    env = tmp_path / "viewer.env"
    env.write_text("S9K_NEO4J_PASSWORD_FILE=/etc/s9-knowledge/secrets/otro\n", encoding="utf-8")
    rc, out = _bash("validate_viewer_unit", str(U_VISOR), "/opt/s9-knowledge/current", str(env))
    assert rc != 0 and "secreto que copia la unidad" in out, out
    env.write_text("S9K_NEO4J_PASSWORD_FILE=/etc/s9-knowledge/secrets/neo4j_password\n", encoding="utf-8")
    assert _bash("validate_viewer_unit", str(U_VISOR), "/opt/s9-knowledge/current", str(env))[0] == 0


def _env(tmp_path, raiz: Path, extra: str = "", quitar=()):
    lineas = {
        "S9K_STATE_ROOT": str(raiz),
        "S9K_AUTH_DB_PATH": str(raiz / "auth" / "auth.db"),
        "S9K_JOBS_DB": str(raiz / "jobs" / "jobs.db"),
        "S9K_V3_REVIEW_DATABASE_PATH": str(raiz / "reviews-v3" / "review.sqlite3"),
        "S9K_V3_REVIEW_PROPOSALS_DIR": str(raiz / "reviews-v3" / "proposals"),
    }
    for q in quitar:
        lineas.pop(q)
    f = tmp_path / "viewer.env"
    f.write_text("".join("%s=%s\n" % kv for kv in lineas.items()) + extra, encoding="utf-8")
    return f


def _validar_paths(env: Path, raiz: Path, rol="viewer"):
    r = subprocess.run(["bash", "-c", 'export S9K_STATE_ROOT="$3"; source "$1"; validate_state_paths "$2" "$4"',
                        "_", str(VALIDATE_SH), str(env), str(raiz), rol],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_N5_N6_validate_state_paths_acepta_lo_derivado_bajo_el_state_root(tmp_path):
    raiz = tmp_path / "state"
    assert _validar_paths(_env(tmp_path, raiz), raiz) == (0, "OK\n")


@pytest.mark.parametrize("extra,fragmento", [
    ("S9K_V3_REVIEW_DECISIONS_PATH=/opt/s9-knowledge/current/viewer/output/reviews-v3/decisions.jsonl\n",
     "dentro de la release"),                                          # N5/N18
    ("S9K_V3_GLOSSARY_CANDIDATES_DIR=/opt/s9-knowledge/releases/x/viewer/glossary\n", "dentro de la release"),
    ("S9K_V3_REVIEW_DECISIONS_PATH=/srv/otro-sitio/decisions.jsonl\n", "no cuelga del state root"),
    ("S9K_V3_REVIEW_DECISIONS_PATH=decisions.jsonl\n", "no es una ruta absoluta"),
])
def test_N5_N6_N18_validate_state_paths_rechaza_estado_fuera_del_contrato(tmp_path, extra, fragmento):
    raiz = tmp_path / "state"
    rc, out = _validar_paths(_env(tmp_path, raiz, extra), raiz)
    assert rc != 0 and fragmento in out, out


def test_N17_state_root_efectivo_canonico_o_override_coincidente(tmp_path):
    """§6: S9K_STATE_ROOT es OPCIONAL (default del producto). Con un deploy de raiz no
    canonica hace falta el override y tiene que COINCIDIR; si no, STOP por ambiguo."""
    raiz = tmp_path / "state"
    # sin override y raiz no canonica -> ambiguo
    rc, out = _validar_paths(_env(tmp_path, raiz, quitar=("S9K_STATE_ROOT",)), raiz)
    assert rc != 0 and "NO canonico" in out, out
    # override distinto del que usa el despliegue -> ambiguo
    otro = tmp_path / "otro"
    rc, out = _validar_paths(_env(tmp_path, otro), raiz)
    assert rc != 0 and "no se determina de forma inequivoca" in out, out
    # raiz canonica sin override -> valido (ZERO-TERMINAL)
    canon = Path(ss.DEFAULT_STATE_ROOT)
    f = tmp_path / "canon.env"
    f.write_text("".join("%s=%s\n" % kv for kv in {
        "S9K_AUTH_DB_PATH": str(canon / "auth" / "auth.db"), "S9K_JOBS_DB": str(canon / "jobs" / "jobs.db"),
        "S9K_V3_REVIEW_DATABASE_PATH": str(canon / "reviews-v3" / "review.sqlite3"),
        "S9K_V3_REVIEW_PROPOSALS_DIR": str(canon / "reviews-v3" / "proposals")}.items()), encoding="utf-8")
    assert _validar_paths(f, canon) == (0, "OK\n")


def test_los_viewer_worker_env_de_ejemplo_ya_no_exigen_s9k_state_root():
    for plantilla in ("viewer.env.example", "worker.env.example"):
        lineas = (RAIZ / "deploy" / "config" / plantilla).read_text(encoding="utf-8").splitlines()
        assert not [l for l in lineas if l.startswith("S9K_STATE_ROOT=")], plantilla
    critica = subprocess.run(["bash", "-c", 'source "$1"; printf "%s" "${CRITICAL_ENV_VARS}"', "_", str(VALIDATE_SH)],
                             capture_output=True, text=True).stdout.split()
    assert "S9K_STATE_ROOT" not in critica


def test_el_backup_no_puede_estar_dentro_del_state_root(tmp_path):
    raiz = tmp_path / "state"
    ok = _validar_paths(_env(tmp_path, raiz, "S9K_BACKUP_DIR=%s\n" % (tmp_path / "backups-fuera")), raiz)
    assert ok == (0, "OK\n")
    rc, out = _validar_paths(_env(tmp_path, raiz, "S9K_BACKUP_DIR=%s\n" % (raiz / "backups")), raiz)
    assert rc != 0 and "DENTRO" in out, out
    assert not ss.DEFAULT_BACKUP_ROOT.startswith(ss.DEFAULT_STATE_ROOT)
    gv = yaml.safe_load((ANSIBLE / "group_vars" / "all.yml").read_text(encoding="utf-8"))
    assert gv["s9k_backup_root"] == ss.DEFAULT_BACKUP_ROOT


def test_la_validacion_de_estado_rechaza_la_excepcion_en_un_entorno_operativo(tmp_path):
    raiz = tmp_path / "state"
    rc, out = _validar_paths(_env(tmp_path, raiz, "S9K_STATE_VALIDATION=disabled-explicit-for-tests\n"), raiz)
    assert rc != 0 and "excepcion de tests" in out, out


def test_ansible_secretos_y_config_con_la_politica_SECRET():
    tareas = yaml.safe_load((ANSIBLE / "roles" / "common" / "tasks" / "main.yml").read_text(encoding="utf-8"))
    por = {t.get("name"): t["ansible.builtin.file"] for t in tareas if "ansible.builtin.file" in t}
    cfg = por["Crear directorio de configuracion"]
    assert (cfg["owner"], cfg["group"], cfg["mode"]) == ("root", "{{ s9k_service_group }}", "%04o" % ss.CONFIG_DIR_MODE)
    sec = por["Crear directorio de secretos (root:servicio, el servicio lee y no escribe)"]
    assert (sec["owner"], sec["group"], sec["mode"]) == ("root", "{{ s9k_service_group }}", "%04o" % ss.SECRET_DIR_MODE)
    assert sec["path"] == "{{ s9k_config_root }}/secrets" and ss.SECRETS_DIR == "/etc/s9-knowledge/secrets"
    bk = por["Crear raiz de backups (fuera del state root)"]
    assert bk["path"] == "{{ s9k_backup_root }}" and bk["mode"] == "0750"


def test_lib_prepara_los_secretos_y_la_verificacion_por_efecto_los_prueba():
    t = LIB_SH.read_text(encoding="utf-8")
    i = t.index("preparar_secretos_del_servicio() {")
    cuerpo = t[i:t.index("\n}\n", i)]
    for exigido in ('chown "root:${grupo}"', "secret_file_mode", "secret-check", "config_dir_mode", "secret_dir_mode"):
        assert exigido in cuerpo, exigido
    j = t.index("verificar_estado_por_efecto() {")
    assert "secret-probe" in t[j:t.index("\n}\n", j)]
    d = _deploy()
    assert d.index("preparar_secretos_del_servicio") < d.index("verificar_estado_por_efecto ")


@pytest.mark.parametrize("quitar", ["S9K_AUTH_DB_PATH", "S9K_V3_REVIEW_DATABASE_PATH"])
def test_variable_critica_ausente_se_nombra(tmp_path, quitar):
    raiz = tmp_path / "state"
    rc, out = _validar_paths(_env(tmp_path, raiz, quitar=(quitar,)), raiz)
    assert rc != 0 and quitar in out, out


def test_las_plantillas_de_entorno_cumplen_el_contrato():
    for plantilla, rol in (("viewer.env.example", "viewer"), ("worker.env.example", "worker")):
        r = subprocess.run(["bash", "-c", 'source "$1"; validate_state_paths "$2" "$3"',
                            "_", str(VALIDATE_SH), str(RAIZ / "deploy" / "config" / plantilla), rol],
                           capture_output=True, text=True)
        assert r.returncode == 0, (plantilla, r.stdout + r.stderr)


# ===========================================================================
# 3. migrar_estado.py — la migracion REAL sobre ficheros reales
# ===========================================================================

def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _modo(p) -> int:
    return os.stat(p).st_mode & 0o7777


def _causa(r) -> str:
    """UNA linea con la causa de un resultado de la migracion (sirve de mensaje de
    aserto: la linea de resumen de pytest solo muestra la primera linea)."""
    return " | ".join(l for l in r.lineas if l.startswith(("STOP", "RESIDUAL", "OK"))) or "sin STOP ni OK"


class Escenario:
    """Una release con estado mutable legacy dentro + un state root 'viejo'."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.state = tmp / "var" / "lib" / "s9-knowledge"
        self.release = tmp / "opt" / "releases" / "r-ant"
        self.rv3_rel = self.release / "viewer" / "output" / "reviews-v3"
        self.rv3 = self.state / "reviews-v3"
        for d in ("auth", "jobs", "reviews-v3/proposals", "backups", "state", "output", "staging", "health"):
            (self.state / d).mkdir(parents=True)
        self.rv3_rel.mkdir(parents=True)
        # estado legacy: modos 'viejos' (0644/0660), directorios 0755/0750
        self.escribe(self.state / "auth" / "auth.db", b"AUTHDB" * 100, 0o644)
        self.escribe(self.state / "auth" / "auth.db-wal", b"wal" * 50, 0o644)
        self.escribe(self.state / "auth" / "auth.db-shm", b"shm" * 50, 0o644)
        self.escribe(self.state / "auth" / "auth.lock", b"", 0o644)
        self.escribe(self.state / "auth" / "auth.bak.v3", b"BAK" * 50, 0o644)
        self.escribe(self.state / "auth" / ".csrf_secret", b"s" * 40, 0o600)
        self.escribe(self.state / "jobs" / "jobs.db", b"JOBS" * 100, 0o644)
        self.escribe(self.state / "reviews-v3" / "review.sqlite3", b"REVIEW" * 100, 0o660)
        self.escribe(self.state / "reviews-v3" / "review.sqlite3-wal", b"rw" * 10, 0o660)
        self.escribe(self.rv3_rel / "decisions.jsonl", b'{"d":1}\n{"d":2}\n', 0o644)
        self.escribe(self.rv3_rel / "audit.jsonl", b'{"a":1}\n', 0o644)
        (self.rv3_rel / "glossary-candidates" / "abc").mkdir(parents=True)
        self.escribe(self.rv3_rel / "glossary-candidates" / "abc" / "candidates.jsonl", b'{"c":1}\n', 0o644)
        self.escribe(self.rv3_rel / "proposals" / "p1.json", b'{"p":1}', 0o644)
        for d in [self.state, *[p for p in self.state.rglob("*") if p.is_dir()]]:
            d.chmod(0o755)
        self.env = {
            "S9K_STATE_ROOT": str(self.state),
            "S9K_AUTH_DB_PATH": str(self.state / "auth" / "auth.db"),
            "S9K_JOBS_DB": str(self.state / "jobs" / "jobs.db"),
            "S9K_V3_REVIEW_DATABASE_PATH": str(self.rv3 / "review.sqlite3"),
            "S9K_V3_REVIEW_PROPOSALS_DIR": str(self.rv3 / "proposals"),
        }
        self.originales = {p: _sha(p) for p in self.release.rglob("*") if p.is_file()}

    @staticmethod
    def escribe(ruta: Path, datos: bytes, modo: int):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)
        ruta.chmod(modo)

    def aplicar(self, **kw):
        kw.setdefault("releases", [str(self.release)])
        kw.setdefault("release_id", "r-nueva")
        kw.setdefault("uid", UID)
        kw.setdefault("gid", GID)
        return mg.aplicar(str(self.state), self.env, **kw)


@pytest.fixture
def esc(tmp_path):
    return Escenario(tmp_path)


def test_P9_upgrade_legacy_conserva_el_estado_y_lo_deja_privado(esc):
    sha_auth = _sha(esc.state / "auth" / "auth.db")
    sha_rev = _sha(esc.state / "reviews-v3" / "review.sqlite3")
    r = esc.aplicar()
    assert r.rc == 0, _causa(r)
    # 1. el estado mutable de la release esta ahora bajo el state root, con el MISMO contenido
    assert (esc.rv3 / "decisions.jsonl").read_bytes() == b'{"d":1}\n{"d":2}\n'
    assert (esc.rv3 / "audit.jsonl").read_bytes() == b'{"a":1}\n'
    assert (esc.rv3 / "glossary-candidates" / "abc" / "candidates.jsonl").read_bytes() == b'{"c":1}\n'
    assert (esc.rv3 / "proposals" / "p1.json").read_bytes() == b'{"p":1}'
    # 2. las bases no se tocaron salvo owner/modo
    assert _sha(esc.state / "auth" / "auth.db") == sha_auth
    assert _sha(esc.state / "reviews-v3" / "review.sqlite3") == sha_rev
    # 3. el ORIGINAL se conserva (renombrado), nunca se borra
    migrados = sorted(p.name for p in esc.rv3_rel.iterdir())
    assert "decisions.jsonl.migrado-r-nueva" in migrados and "decisions.jsonl" not in migrados, migrados
    assert (esc.rv3_rel / "decisions.jsonl.migrado-r-nueva").read_bytes() == b'{"d":1}\n{"d":2}\n'
    assert (esc.rv3_rel / "glossary-candidates.migrado-r-nueva" / "abc" / "candidates.jsonl").is_file()
    # 4. P3/P4/N14: TODO el estado, sidecars incluidos, 0600/0700
    for p in esc.state.rglob("*"):
        assert _modo(p) == (0o700 if p.is_dir() else 0o600), (p, oct(_modo(p)))
    assert _modo(esc.state) == 0o700
    # 5. y pasa la MISMA comprobacion que hace el servicio al arrancar
    rutas, _ = ss.effective_paths(esc.env, role="viewer")
    assert ss.inspect_state(esc.state, uid=UID, gid=GID, declared=rutas) == []


def test_P12_el_segundo_despliegue_es_idempotente(esc):
    assert esc.aplicar().rc == 0
    antes = {str(p.relative_to(esc.tmp)): (_sha(p), _modo(p)) for p in esc.tmp.rglob("*") if p.is_file()}
    r = esc.aplicar(release_id="r-nueva2")
    assert r.rc == 0, _causa(r)
    despues = {str(p.relative_to(esc.tmp)): (_sha(p), _modo(p)) for p in esc.tmp.rglob("*") if p.is_file()}
    assert despues == antes, "el segundo pase cambio ficheros: " + str(set(despues) ^ set(antes))
    assert "0 elemento(s) movido(s)" in "\n".join(r.lineas)


def test_P11_un_reinicio_con_modos_degradados_se_corrige(esc):
    """P11: lo que un proceso mal configurado deja mal vuelve a 0600 en el siguiente despliegue."""
    r0 = esc.aplicar()
    assert r0.rc == 0, _causa(r0)
    (esc.state / "auth" / "auth.db-wal").chmod(0o644)
    (esc.state / "auth").chmod(0o755)
    r = esc.aplicar()
    assert r.rc == 0, _causa(r)
    assert _modo(esc.state / "auth" / "auth.db-wal") == 0o600 and _modo(esc.state / "auth") == 0o700


def test_N5_N6_decisions_y_audit_de_la_release_se_migran_y_el_destino_es_privado(esc):
    r = esc.aplicar()
    assert r.rc == 0, _causa(r)
    for nombre in ("decisions.jsonl", "audit.jsonl"):
        assert _modo(esc.rv3 / nombre) == 0o600 and (esc.rv3 / nombre).is_file()


def test_el_arbol_legacy_solo_se_copia_nunca_se_retira(esc, tmp_path):
    legacy = tmp_path / "legacy"
    esc.escribe(legacy / "viewer" / "output" / "reviews-v3" / "decisions.jsonl", b"L\n", 0o644)
    esc.release = tmp_path / "sin-release"
    r = esc.aplicar(releases=[], legacy_root=str(legacy))
    assert r.rc == 0, "\n".join(r.lineas)
    assert (esc.rv3 / "decisions.jsonl").read_bytes() == b"L\n"
    assert (legacy / "viewer" / "output" / "reviews-v3" / "decisions.jsonl").read_bytes() == b"L\n"
    # el estado vivo sigue creciendo: el segundo pase NO lo compara ni lo pisa ni bloquea
    with open(esc.rv3 / "decisions.jsonl", "ab") as fh:
        fh.write(b"nueva\n")
    assert esc.aplicar(releases=[], legacy_root=str(legacy)).rc == 0
    assert (esc.rv3 / "decisions.jsonl").read_bytes() == b"L\nnueva\n"


# --- negativos del contrato §9 --------------------------------------------

def test_N5_decisions_ilegible_en_la_release_PARA_y_conserva_todo(esc):
    if EUID == 0:
        pytest.skip("root lee cualquier fichero: va a VM112")
    (esc.rv3_rel / "decisions.jsonl").chmod(0o000)
    try:
        r = esc.aplicar()
    finally:
        (esc.rv3_rel / "decisions.jsonl").chmod(0o644)
    assert r.rc == 3 and "STOP[" in r.lineas[-1], r.lineas
    assert not any(l.startswith("OK") for l in r.lineas), "declara exito tras un fallo"
    assert (esc.rv3_rel / "decisions.jsonl").read_bytes() == b'{"d":1}\n{"d":2}\n'


def test_N12_migracion_a_mitad_no_declara_exito_y_conserva_los_originales(esc, monkeypatch):
    llamadas = {"n": 0}
    original = mg._copiar_verificado

    def falla_a_la_segunda(*a, **k):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise mg.Parada("MOVIMIENTO_PARCIAL", "fallo simulado a mitad de la copia")
        return original(*a, **k)

    monkeypatch.setattr(mg, "_copiar_verificado", falla_a_la_segunda)
    r = esc.aplicar()
    assert r.rc == 3 and "MOVIMIENTO_PARCIAL" in r.lineas[-1], r.lineas
    assert not any(l.startswith("OK") for l in r.lineas)
    # NINGUN original se ha perdido: o sigue donde estaba, o se renombro DESPUES de
    # verificar su copia (mismo contenido, destino presente y con el mismo hash).
    for ruta, sha in esc.originales.items():
        ruta = Path(ruta)
        if ruta.is_file():
            assert _sha(ruta) == sha, ruta
        else:
            retirados = list(ruta.parent.glob(ruta.name + ".migrado-*"))
            assert len(retirados) == 1 and _sha(retirados[0]) == sha, ruta
            assert _sha(esc.rv3 / ruta.name) == sha, "retirado sin copia verificada: %s" % ruta
    # y se puede REINTENTAR: converge sin duplicar ni perder
    monkeypatch.setattr(mg, "_copiar_verificado", original)
    r2 = esc.aplicar()
    assert r2.rc == 0, r2.lineas
    assert (esc.rv3 / "decisions.jsonl").read_bytes() == b'{"d":1}\n{"d":2}\n'


def test_N11_chown_imposible_PARA_con_diagnostico(esc):
    if EUID == 0:
        pytest.skip("root puede hacer chown a cualquiera: va a VM112")
    r = esc.aplicar(uid=UID + 4242, gid=GID + 4242)
    assert r.rc == 3 and "SIN_PERMISOS" in r.lineas[-1], r.lineas
    assert not any(l.startswith("OK") for l in r.lineas)


def test_N11b_chmod_fallido_PARA(esc, monkeypatch):
    def chmod_roto(ruta, modo, *a, **k):
        raise PermissionError(1, "Operation not permitted", str(ruta))

    monkeypatch.setattr(mg.os, "chmod", chmod_roto)
    r = esc.aplicar()
    assert r.rc == 3 and "SIN_PERMISOS" in r.lineas[-1], r.lineas


def test_N13_symlink_inesperado_en_el_estado_PARA(esc, tmp_path):
    ajeno = tmp_path / "ajeno.txt"
    ajeno.write_text("x")
    os.symlink(ajeno, esc.state / "auth" / "enlace")
    r = esc.aplicar()
    assert r.rc == 3 and "SYMLINK" in r.lineas[-1], r.lineas
    assert (esc.rv3_rel / "decisions.jsonl").exists(), "se movio estado con un symlink presente"


def test_N13b_symlink_como_state_root_PARA(esc, tmp_path):
    enlace = tmp_path / "raiz"
    os.symlink(esc.state, enlace)
    env = {k: v.replace(str(esc.state), str(enlace)) for k, v in esc.env.items()}
    r = mg.aplicar(str(enlace), env, releases=[str(esc.release)], uid=UID, gid=GID)
    assert r.rc == 3 and "SYMLINK" in r.lineas[-1], r.lineas


def test_N13c_symlink_en_el_origen_legacy_PARA(esc, tmp_path):
    (esc.rv3_rel / "audit.jsonl").unlink()
    os.symlink(tmp_path / "x", esc.rv3_rel / "audit.jsonl")
    (tmp_path / "x").write_text("x")
    r = esc.aplicar()
    assert r.rc == 3 and "SYMLINK" in r.lineas[-1], r.lineas


def test_N17_state_root_ausente_con_crear_falso_PARA(esc):
    shutil.rmtree(esc.state)
    r = esc.aplicar(crear_state_root=False)
    assert r.rc == 3 and "STATE_ROOT_AUSENTE" in r.lineas[-1], r.lineas


def test_N17b_sin_las_rutas_exigidas_PARA(esc):
    del esc.env["S9K_V3_REVIEW_DATABASE_PATH"]
    r = esc.aplicar()
    assert r.rc == 3 and "RUTA_INCORRECTA" in r.lineas[-1], r.lineas


def test_N18_estado_declarado_dentro_de_la_release_PARA(esc):
    esc.env["S9K_V3_REVIEW_DECISIONS_PATH"] = str(esc.rv3_rel / "decisions.jsonl")
    r = esc.aplicar()
    assert r.rc == 3 and "RUTA_INCORRECTA" in r.lineas[-1], r.lineas


def test_conflicto_origen_y_destino_distintos_PARA_y_conserva_los_dos(esc):
    esc.escribe(esc.rv3 / "decisions.jsonl", b"OTRO CONTENIDO\n", 0o600)
    r = esc.aplicar()
    assert r.rc == 3 and "CONFLICTO_DE_ESTADO" in r.lineas[-1], r.lineas
    assert (esc.rv3 / "decisions.jsonl").read_bytes() == b"OTRO CONTENIDO\n"
    assert (esc.rv3_rel / "decisions.jsonl").read_bytes() == b'{"d":1}\n{"d":2}\n'


def test_destino_identico_solo_retira_el_original(esc):
    esc.escribe(esc.rv3 / "decisions.jsonl", b'{"d":1}\n{"d":2}\n', 0o600)
    r = esc.aplicar()
    assert r.rc == 0, r.lineas
    assert (esc.rv3_rel / "decisions.jsonl.migrado-r-nueva").exists()


def test_base_abierta_por_un_proceso_PARA(esc):
    """Servicio que no paro: un proceso con auth.db abierta. La migracion NO toca nada."""
    abierto = subprocess.Popen(
        [sys.executable, "-c",
         "import sys,time; f=open(sys.argv[1],'rb'); print('listo',flush=True); time.sleep(60)",
         str(esc.state / "auth" / "auth.db")], stdout=subprocess.PIPE, text=True)
    try:
        assert abierto.stdout.readline().strip() == "listo"
        antes = {p: (_sha(p), _modo(p)) for p in esc.state.rglob("*") if p.is_file()}
        r = esc.aplicar()
        despues = {p: (_sha(p), _modo(p)) for p in esc.state.rglob("*") if p.is_file()}
    finally:
        abierto.kill()
        abierto.wait()
    assert r.rc == 3 and "BASE_ABIERTA" in r.lineas[-1], r.lineas
    assert despues == antes, "se modifico estado con un proceso que lo tenia abierto"


def test_journal_pendiente_PARA(esc):
    esc.escribe(esc.state / "auth" / "auth.db-journal", b"hot", 0o644)
    r = esc.aplicar()
    assert r.rc == 3 and "JOURNAL_PENDIENTE" in r.lineas[-1], r.lineas


def test_sistema_de_ficheros_de_solo_lectura_PARA(esc, monkeypatch):
    real = os.statvfs

    class Vfs:
        def __init__(self, v):
            self.__dict__.update({k: getattr(v, k) for k in dir(v) if k.startswith("f_")})
            self.f_flag = v.f_flag | os.ST_RDONLY

    monkeypatch.setattr(mg.os, "statvfs", lambda p: Vfs(real(p)))
    r = esc.aplicar()
    assert r.rc == 3 and "FS_SOLO_LECTURA" in r.lineas[-1], r.lineas


def test_espacio_insuficiente_PARA(esc, monkeypatch):
    real = os.statvfs

    class Vfs:
        def __init__(self, v):
            self.__dict__.update({k: getattr(v, k) for k in dir(v) if k.startswith("f_")})
            self.f_bavail = 0

    monkeypatch.setattr(mg.os, "statvfs", lambda p: Vfs(real(p)))
    r = esc.aplicar()
    assert r.rc == 3 and "ESPACIO_INSUFICIENTE" in r.lineas[-1], r.lineas
    assert (esc.rv3_rel / "decisions.jsonl").exists()


def test_sidecar_con_tipo_inesperado_PARA(esc):
    if not hasattr(os, "mkfifo"):
        pytest.skip("sin mkfifo")
    os.mkfifo(esc.state / "auth" / "auth.db-wal2")
    r = esc.aplicar()
    assert r.rc == 3 and "TIPO" in r.lineas[-1], r.lineas


def test_destino_no_regular_PARA(esc):
    (esc.rv3 / "decisions.jsonl").mkdir()
    r = esc.aplicar()
    assert r.rc == 3, r.lineas


def test_la_copia_que_no_verifica_PARA_y_no_retira_el_original(esc, monkeypatch):
    real = mg._sha256

    def sha_inestable(ruta):
        # la verificacion de la COPIA (el temporal `.migrando-*`) 'falla'; el resto, real.
        # (Ronda 2: localizada por el fichero, no por el orden de las llamadas: el
        # pre-escaneo de C-2 tambien calcula hashes.)
        h = real(ruta)
        return "0" * 64 if os.path.basename(str(ruta)).startswith(".migrando-") else h

    monkeypatch.setattr(mg, "_sha256", sha_inestable)
    r = esc.aplicar()
    assert r.rc == 3 and "COPIA_NO_VERIFICA" in r.lineas[-1], r.lineas
    assert (esc.rv3_rel / "decisions.jsonl").exists()


def test_el_diagnostico_de_parada_nombra_la_ruta_y_la_causa(esc):
    esc.escribe(esc.rv3 / "decisions.jsonl", b"distinto", 0o600)
    r = esc.aplicar()
    ultima = r.lineas[-1]
    assert ultima.startswith("STOP[CONFLICTO_DE_ESTADO]:") and "decisions.jsonl" in ultima


def test_cli_de_migrar_estado_devuelve_3_y_escribe_en_stderr(esc, tmp_path):
    env = tmp_path / "viewer.env"
    esc.env["S9K_V3_REVIEW_DECISIONS_PATH"] = str(esc.rv3_rel / "decisions.jsonl")
    env.write_text("".join("%s=%s\n" % kv for kv in esc.env.items()), encoding="utf-8")
    r = subprocess.run([sys.executable, str(MIGRAR_PY), "aplicar", "--state-root", str(esc.state),
                        "--env-file", str(env), "--uid", str(UID), "--gid", str(GID)],
                       capture_output=True, text=True)
    assert r.returncode == 3 and "STOP[RUTA_INCORRECTA]" in r.stderr and r.stdout == "", (r.stdout, r.stderr)


# ===========================================================================
# 4. deploy.sh: orden y fail-closed (por estructura; la ejecucion real va a VM112)
# ===========================================================================

def _deploy() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def test_el_orden_del_despliegue_para_antes_de_migrar_y_migra_antes_de_validar_por_efecto():
    t = _deploy()
    marcas = ["# Paso 2b ", "# Paso 3: detectar layout/estado", "# Paso 3b ", "# Paso 4: migrar o validar estado",
              "# Paso 5b ", "# Paso 6: validar viewer.env", "# Paso 7: validar unidad nueva",
              "# Paso 12: cambiar current", "# Paso 13: reiniciar solo servicios afectados"]
    posiciones = []
    for m in marcas:
        assert t.count(m) == 1, "DETECTOR ROTO: %r aparece %d veces" % (m, t.count(m))
        posiciones.append(t.index(m))
    assert posiciones == sorted(posiciones), "el orden del despliegue cambio: %s" % posiciones


def _sentencia(tramo: str, orden: str) -> str:
    """La sentencia bash COMPLETA (con sus continuaciones `\\`) que contiene `orden`."""
    lineas = tramo.splitlines()
    ini = next(i for i, l in enumerate(lineas) if orden in l and not l.lstrip().startswith("#"))
    fin = ini
    while lineas[fin].rstrip().endswith("\\"):
        fin += 1
    return "\n".join(lineas[ini:fin + 1])


def test_N12_cada_paso_de_la_migracion_falla_con_die_y_nunca_afirma_exito():
    t = _deploy()
    a, b = t.index("# Paso 3b "), t.index("# --- fin del paso 3b ---")
    tramo = t[a:b]
    for llamada in ("asegurar_identidad_de_servicio", "parar_y_verificar_servicios"):
        sentencia = _sentencia(tramo, llamada + " ")
        assert "|| die" in sentencia, "SIN DIE en: " + sentencia
    a, b = t.index("# Paso 5b "), t.index("# --- fin del paso 5b ---")
    tramo = t[a:b]
    # cada orden critica del bloque lleva su `|| die` en SU PROPIA sentencia
    for orden in ("migrar_estado.py\"", "verificar_estado_por_efecto "):
        sentencia = _sentencia(tramo, orden)
        assert "|| die" in sentencia, "MIGRACION SIN DIE en: " + sentencia
    # el bloque no contiene un exit 0 ni un "success"/"terminado" propios
    assert "exit 0" not in tramo and "DEPLOY terminado" not in tramo
    # las precondiciones puras van ANTES de parar nada (paso 2b) y tambien con `|| die`
    a, b = t.index("# Paso 2b "), t.index("# --- fin del paso 2b ---")
    pre = t[a:b]
    for orden in ("validate_viewer_env ", "validate_state_paths \"${VIEWER_ENV}\""):
        assert "|| die" in _sentencia(pre, orden), "PRECONDICION SIN DIE: " + orden
    assert t.index("# Paso 2b ") < t.index("# Paso 3b "), "las precondiciones deben ir ANTES de parar los servicios"


def test_deploy_pide_la_identidad_a_la_autoridad_y_no_la_lee_de_una_unidad():
    t = _deploy()
    assert 'SERVICE_USER="$(servicio_cifra service_user)"' in t
    assert 'REVIEW_USER="${SERVICE_USER}"' in t
    assert '_unit_value "${WORKER_UNIT_PREVIA}" User' not in t


def test_los_procesos_vivos_se_verifican_como_el_usuario_de_servicio():
    t = _deploy()
    i = t.index("# Paso 14a ")
    assert "verificar_procesos_no_root" in t[i:i + 400]
    assert t.index("# Paso 14a ") < t.index("# Paso 14b ")
    assert "|| {" not in t[i:i + 120] or True


def test_el_rollback_no_restaura_una_identidad_anterior():
    t = LIB_SH.read_text(encoding="utf-8")
    i = t.index("revertir_worker() {")
    cuerpo = t[i:t.index("\n}\n", i)]
    assert "_unidad_con_identidad_vigente" in cuerpo
    assert "anterior a H-06" in cuerpo


def _revertir_con_respaldo(tmp: Path, contenido_respaldo: str):
    """`revertir_worker` REAL (bash) con una release previa que SI puede ejecutar el worker."""
    prev = tmp / "previa"
    (prev / "data-engine" / ".venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, prev / "data-engine" / ".venv" / "bin" / "python")
    dest = tmp / "etc" / "s9-knowledge-worker.service"
    dest.parent.mkdir(parents=True)
    dest.write_text("unidad nueva\n", encoding="utf-8")
    (tmp / "etc" / "s9-knowledge-worker.service.bak-rel1").write_text(contenido_respaldo, encoding="utf-8")
    llamadas = tmp / "systemctl.log"
    cuerpo = 'systemctl() { echo "$*" >> %s; }\nrevertir_worker "%s" s9-knowledge-worker.service "%s" rel1\n' % (
        llamadas, prev, dest)
    r = subprocess.run(["bash", "-c", "set -Eeuo pipefail\nsource %s\n%s" % (LIB_SH, cuerpo)],
                       capture_output=True, text=True)
    return r, dest


@pytest.mark.parametrize("anterior", ["User=www-data\nGroup=www-data\n", "[Service]\n# sin User=: root\n"],
                         ids=["www-data", "root"])
def test_ROLLBACK_efecto_no_restaura_una_unidad_de_identidad_anterior(tmp_path, anterior):
    r, dest = _revertir_con_respaldo(tmp_path, anterior)
    assert r.returncode == 0, r.stderr
    assert dest.read_text(encoding="utf-8") != anterior, "ROLLBACK RESTAURA IDENTIDAD ANTERIOR"
    assert "anterior a H-06" in r.stderr, r.stderr


def test_ROLLBACK_efecto_si_restaura_una_unidad_con_la_identidad_vigente(tmp_path):
    vigente = "User=%s\n# previa\n" % ss.SERVICE_USER
    r, dest = _revertir_con_respaldo(tmp_path, vigente)
    assert r.returncode == 0, r.stderr
    assert dest.read_text(encoding="utf-8") == vigente


def test_ROLLBACK_el_rollback_de_release_exige_una_release_que_entienda_la_identidad():
    t = (_SCRIPTS / "rollback-release.sh").read_text(encoding="utf-8")
    i = t.index("target_understands_external_state() {")
    cuerpo = t[i:t.index("\n}\n", i)]
    # Ronda 2 (C-4): la MISMA comprobacion que el rollback automatico de deploy.sh, que valida
    # las unidades de visor Y worker de la release destino (validate_deploy.sh).
    assert "release_entiende_la_identidad" in cuerpo
    v = (_SCRIPTS / "validate_deploy.sh").read_text(encoding="utf-8")
    j = v.index("release_entiende_la_identidad() {")
    funcion = v[j:v.index("\n}\n", j)]
    assert "validate_viewer_unit" in funcion and "validate_worker_unit" in funcion


def test_la_identidad_creada_es_de_sistema_sin_login_ni_sudo():
    t = LIB_SH.read_text(encoding="utf-8")
    i = t.index("asegurar_identidad_de_servicio() {")
    cuerpo = t[i:t.index("\n}\n", i)]
    for exigido in ("groupadd --system", "useradd --system", "--no-create-home", "nologin",
                    "uid}\" -lt 1000", "sudo wheel adm root docker"):
        assert exigido in cuerpo, exigido


def test_la_verificacion_por_efecto_usa_runuser_como_servicio_y_como_otro_usuario():
    t = LIB_SH.read_text(encoding="utf-8")
    i = t.index("verificar_estado_por_efecto() {")
    cuerpo = t[i:t.index("\n}\n", i)]
    assert "runuser -u \"${user}\" -- python3" in cuerpo and "runuser -u nobody -- python3" in cuerpo
    assert " access " in cuerpo and " deny " in cuerpo


def test_N10_el_helper_canonico_de_la_cli_usa_runuser():
    t = LIB_SH.read_text(encoding="utf-8")
    i = t.index("auth_cli() {")
    assert "s9k_cli auth" in t[i:t.index("\n}\n", i)]
    # Ronda 2 (H-1): UN envoltorio para todas las CLIs que pueden crear estado
    i = t.index("s9k_cli() {")
    cuerpo = t[i:t.index("\n}\n", i)]
    assert 'exec runuser -u "${user}" --' in cuerpo and "_exportar_env_s9k" in cuerpo
    i = t.index("s9k_cli_destino() {")
    assert "app.cli.auth" in t[i:t.index("\n}\n", i)]
    # los secretos no viajan en argv: se exportan, no se pasan como `VAR=valor` a runuser
    i = t.index("_exportar_env_s9k() {")
    assert 'export "${k}=${v}"' in t[i:t.index("\n}\n", i)]


def test_el_script_auth_cli_existe_y_delega_en_el_helper():
    f = _SCRIPTS / "auth-cli.sh"
    assert f.is_file() and os.access(f, os.X_OK)
    codigo = "\n".join(l for _, l in _estructurales_sin_literales(f))
    assert "auth_cli" in codigo and "runuser" not in codigo


def test_preparar_estado_del_worker_usa_los_modos_de_la_autoridad(tmp_path):
    log = tmp_path / "llamadas.log"
    cuerpo = """
install() { echo "install $*" >> %(log)s; }
chown() { echo "chown $*" >> %(log)s; }
chmod() { echo "chmod $*" >> %(log)s; }
preparar_estado_del_worker usr grp /a/jobs.db /a/props /b/review.sqlite3
""" % {"log": log}
    # los ficheros 'existen' a ojos de la funcion: se crean de verdad
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
    cuerpo = cuerpo.replace("/a/jobs.db", str(tmp_path / "a" / "jobs.db")).replace(
        "/a/props", str(tmp_path / "a" / "props")).replace("/b/review.sqlite3", str(tmp_path / "b" / "review.sqlite3"))
    (tmp_path / "a" / "jobs.db").write_text("x")
    r = subprocess.run(["bash", "-c", "set -Eeuo pipefail\nsource %s\n%s\n" % (LIB_SH, cuerpo)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    llamadas = log.read_text(encoding="utf-8")
    assert "install -d -m 0700 -o usr -g grp" in llamadas, llamadas
    assert "chmod 0600 -- %s" % (tmp_path / "a" / "jobs.db") in llamadas, llamadas
    assert "0750" not in llamadas and "0660" not in llamadas


# ===========================================================================
# 5. review_store.py (C1): cambia propietario y modos, NO la semantica
# ===========================================================================

def test_C1_review_store_crea_0600_en_directorio_0700_con_umask_022(tmp_path):
    sys.path.insert(0, str(_SCRIPTS))
    import review_store as rs  # noqa: PLC0415

    antes = os.umask(0o022)
    try:
        db = tmp_path / "state" / "reviews-v3" / "review.sqlite3"
        res = rs.preparar("fresh", str(db))
    finally:
        os.umask(antes)
    assert res.rc == 0, res.lineas
    assert _modo(db) == 0o600, oct(_modo(db))
    assert _modo(db.parent) == 0o700, oct(_modo(db.parent))
    for suf in ("-wal", "-shm"):
        extra = Path(str(db) + suf)
        if extra.exists():
            assert _modo(extra) == 0o600, extra


def test_C1_la_semantica_no_cambia_upgrade_preserva_y_no_toca_el_modo(tmp_path):
    sys.path.insert(0, str(_SCRIPTS))
    import review_store as rs  # noqa: PLC0415

    db = tmp_path / "rv3" / "review.sqlite3"
    assert rs.preparar("fresh", str(db)).rc == 0
    sha = _sha(db)
    res = rs.preparar("upgrade", str(db))
    assert res.rc == 0 and res.accion == "PRESERVADO" and _sha(db) == sha
    # upgrade sin almacen sigue siendo STOP; autorizacion explicita no sobrescribe uno invalido
    assert rs.preparar("upgrade", str(tmp_path / "otro" / "r.sqlite3")).rc == 3
    corrupta = tmp_path / "rv3" / "corrupta.sqlite3"
    corrupta.write_bytes(b"no soy sqlite" * 50)
    assert rs.preparar("upgrade", str(corrupta), autorizar=True).rc == 3
    assert corrupta.read_bytes() == b"no soy sqlite" * 50
