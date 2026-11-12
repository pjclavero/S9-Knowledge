# -*- coding: utf-8 -*-
"""H-06 + H-08 · RONDA 2 — defectos ligados al contrato (C-1…C-7) y testigos de los
mutantes del revisor que sobrevivieron (R2, R3, R8, R13).

QUE SE EJECUTA DE VERDAD
------------------------
* ``migrar_estado.aplicar`` y ``service_state.py validate-env`` sobre ficheros reales
  (C-1, C-2, C-3, C-5): el STOP llega ANTES de mover/chown-ear nada, y se comprueba
  en el disco que nada se movió.
* ``lib.sh`` REAL en bash con un ``systemctl`` falso que registra llamadas (C-4, C-6,
  R2): la función que usa ``deploy.sh``, no una copia.
* ``service_state.py unit-check`` / ``validate_deploy.sh`` sobre unidades reales y
  mutadas (C-7, R8, R13).

TECHO: no hay systemd ni root reales; lo real (drop-in auténtico, rollback a una release
anterior a H-06, otro usuario) va a VM112 (escenarios C y E).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
RAIZ = _TESTS.parents[1]
SCRIPTS = RAIZ / "deploy" / "scripts"
SS_PY = RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"
LIB_SH = SCRIPTS / "lib.sh"
VALIDATE_SH = SCRIPTS / "validate_deploy.sh"
DEPLOY_SH = SCRIPTS / "deploy.sh"
U_VISOR = RAIZ / "viewer" / "systemd" / "s9-knowledge-viewer.service"
U_WORKER = RAIZ / "data-engine" / "systemd" / "s9-knowledge-worker.service"
U_HEALTH = RAIZ / "viewer" / "systemd" / "s9-knowledge-healthcheck.service"
UID, GID = os.getuid(), os.getgid()
EUID = os.geteuid()


def _cargar(nombre, ruta):
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = m
    spec.loader.exec_module(m)
    return m


ss = _cargar("_s9k_service_state", SS_PY)
mg = _cargar("_s9k_migrar_estado", SCRIPTS / "migrar_estado.py")


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _causa(r) -> str:
    return " | ".join(l for l in r.lineas if l.startswith(("STOP", "RESIDUAL", "OK"))) or "sin STOP ni OK"


def _foto(raiz: Path):
    return sorted((p.relative_to(raiz).as_posix(), stat.S_IMODE(os.lstat(p).st_mode), p.is_symlink())
                  for p in raiz.rglob("*"))


class Esc:
    """State root legacy (0755/0644) + release con decisions/audit/candidatos/propuestas."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.state = tmp / "var" / "lib" / "s9-knowledge"
        self.release = tmp / "opt" / "releases" / "r-ant"
        self.rv3_rel = self.release / "viewer" / "output" / "reviews-v3"
        self.rv3 = self.state / "reviews-v3"
        for d in ("auth", "jobs", "reviews-v3/proposals", "health"):
            (self.state / d).mkdir(parents=True)
        self.escribe(self.state / "auth" / "auth.db", b"AUTH" * 10, 0o644)
        self.escribe(self.rv3 / "review.sqlite3", b"REVIEW" * 10, 0o660)
        self.escribe(self.rv3_rel / "decisions.jsonl", b'{"d":1}\n', 0o644)
        self.escribe(self.rv3_rel / "audit.jsonl", b'{"a":1}\n', 0o644)
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

    def env_file(self, extra: str = "") -> Path:
        f = self.tmp / "viewer.env"
        f.write_text("".join("%s=%s\n" % kv for kv in self.env.items()) + extra, encoding="utf-8")
        return f


@pytest.fixture
def esc(tmp_path):
    return Esc(tmp_path)


def _validate_env(env_file: Path, raiz: Path, rol="viewer"):
    r = subprocess.run([sys.executable, str(SS_PY), "validate-env", "--env-file", str(env_file),
                        "--state-root", str(raiz), "--role", rol], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ===========================================================================
# C-1 · backups dentro del state: precondición ANTES de parar nada (validate-env, paso 2b)
# ===========================================================================

def test_C1_backups_con_contenido_en_el_state_PARA_en_las_precondiciones(esc):
    esc.escribe(esc.state / "backups" / "copia-2026.tar", b"x", 0o600)
    rc, out = _validate_env(esc.env_file(), esc.state)
    assert rc != 0 and "backups viven FUERA" in out and "RECETA" in out, out
    # solo lectura: la copia sigue ahi (la decision es del operador)
    assert (esc.state / "backups" / "copia-2026.tar").exists()


def test_C1_backups_vacio_no_bloquea_las_precondiciones(esc):
    (esc.state / "backups").mkdir()
    assert _validate_env(esc.env_file(), esc.state) == (0, "OK\n")


@pytest.mark.parametrize("var", ["S9K_BACKUP_ROOT", "S9K_BACKUP_DIR"])
def test_C1_la_raiz_de_backups_dentro_del_state_PARA_por_cualquiera_de_sus_dos_nombres(esc, var):
    rc, out = _validate_env(esc.env_file("%s=%s\n" % (var, esc.state / "copias")), esc.state)
    assert rc != 0 and ("%s=" % var) in out and "DENTRO" in out, out
    ok = _validate_env(esc.env_file("%s=%s\n" % (var, esc.tmp / "backups-fuera")), esc.state)
    assert ok == (0, "OK\n"), ok


def test_C1_deploy_valida_las_precondiciones_del_disco_antes_de_parar():
    """El paso 2b (antes de 3b, que para los servicios) llama a validate_state_paths del visor,
    que es `validate-env --role viewer` (backups + state root dedicado)."""
    t = DEPLOY_SH.read_text(encoding="utf-8")
    a, b = t.index("# Paso 2b "), t.index("# --- fin del paso 2b ---")
    assert 'validate_state_paths "${VIEWER_ENV}" viewer' in t[a:b]
    assert t.index("# Paso 2b ") < t.index("# Paso 3b ")
    assert "S9K_BACKUP_ROOT" in t[t.index("# Paso 5b "):t.index("# --- fin del paso 5b ---")]


# ===========================================================================
# C-2 · pre-escaneo COMPLETO: un symlink/conflicto legacy PARA sin haber movido nada
# ===========================================================================

def test_C2_un_symlink_legacy_PARA_sin_mover_el_primer_fichero(esc):
    (esc.rv3_rel / "audit.jsonl").unlink()
    (esc.tmp / "fuera.txt").write_text("ajeno")
    os.symlink(esc.tmp / "fuera.txt", esc.rv3_rel / "audit.jsonl")
    antes_rel, antes_state = _foto(esc.release), _foto(esc.state)
    r = esc.aplicar()
    assert r.rc == 3 and "STOP[SYMLINK]" in r.lineas[-1], _causa(r)
    assert _foto(esc.release) == antes_rel and _foto(esc.state) == antes_state, (
        "MOVIO ANTES DEL PRE-ESCANEO: %s" % [l for l in r.lineas if l.startswith("MOVIDO")])


def test_C2_un_conflicto_en_el_segundo_elemento_PARA_sin_mover_el_primero(esc):
    esc.escribe(esc.rv3 / "audit.jsonl", b"OTRO\n", 0o600)
    antes_rel = _foto(esc.release)
    r = esc.aplicar()
    assert r.rc == 3 and "CONFLICTO_DE_ESTADO" in r.lineas[-1], _causa(r)
    assert _foto(esc.release) == antes_rel and not (esc.rv3 / "decisions.jsonl").exists(), (
        "MOVIO ANTES DEL PRE-ESCANEO")


def test_C2_un_symlink_dentro_de_un_directorio_legacy_PARA_sin_mover_nada(esc):
    (esc.tmp / "fuera.json").write_text("{}")
    os.symlink(esc.tmp / "fuera.json", esc.rv3_rel / "proposals" / "enlace.json")
    antes_rel = _foto(esc.release)
    r = esc.aplicar()
    assert r.rc == 3 and "STOP[SYMLINK]" in r.lineas[-1], _causa(r)
    assert _foto(esc.release) == antes_rel and not (esc.rv3 / "decisions.jsonl").exists()


# ===========================================================================
# C-3 · el estado legacy en DOS sitios: distinto -> STOP; idéntico -> se acepta y se anota
# ===========================================================================

def _legacy_root(esc, contenido: bytes) -> Path:
    legacy = esc.tmp / "legacy"
    esc.escribe(legacy / "viewer" / "output" / "reviews-v3" / "decisions.jsonl", contenido, 0o644)
    return legacy


def test_C3_estado_legacy_en_dos_sitios_con_contenido_distinto_PARA(esc):
    legacy = _legacy_root(esc, b'{"d":"OTRA"}\n')
    antes_rel = _foto(esc.release)
    r = esc.aplicar(legacy_root=str(legacy))
    assert r.rc == 3 and "ESTADO_LEGACY_DUPLICADO" in r.lineas[-1], _causa(r)
    assert _foto(esc.release) == antes_rel and not (esc.rv3 / "decisions.jsonl").exists()
    assert (legacy / "viewer" / "output" / "reviews-v3" / "decisions.jsonl").read_bytes() == b'{"d":"OTRA"}\n'


def test_C3_estado_legacy_en_dos_sitios_identico_por_hash_se_acepta_y_se_anota(esc):
    legacy = _legacy_root(esc, b'{"d":1}\n')
    r = esc.aplicar(legacy_root=str(legacy))
    assert r.rc == 0, _causa(r)
    assert any("MISMO contenido" in l for l in r.lineas), r.lineas
    assert (esc.rv3 / "decisions.jsonl").read_bytes() == b'{"d":1}\n'


# ===========================================================================
# C-5 · el state root es DEDICADO: ni del sistema, ni compartido, ni con contenido ajeno
# ===========================================================================

def test_C5_senuelo_del_revisor_raiz_1777_con_ficheros_ajenos_PARA_sin_tocar_nada(esc):
    senuelo = esc.tmp / "compartido"
    senuelo.mkdir()
    (senuelo / "de-otro-usuario.txt").write_text("ajeno")
    (senuelo / "de-otro-usuario.txt").chmod(0o644)
    senuelo.chmod(0o1777)
    env = {k: v.replace(str(esc.state), str(senuelo)) for k, v in esc.env.items()}
    antes = _foto(senuelo)
    r = mg.aplicar(str(senuelo), env, releases=[str(esc.release)], uid=UID, gid=GID)
    assert r.rc == 3 and "STATE_ROOT_NO_DEDICADO" in r.lineas[-1], "C5 NO DEDICADO NO VISTO: " + _causa(r)
    assert _foto(senuelo) == antes and stat.S_IMODE(senuelo.stat().st_mode) == 0o1777, (
        "la migracion toco un state root no dedicado")


@pytest.mark.parametrize("raiz", ["/", "/var/lib", "/tmp", "/srv", "/opt", "/home", "/etc"])
def test_C5_un_directorio_del_sistema_no_es_un_state_root(esc, raiz):
    env = {k: v.replace(str(esc.state), raiz.rstrip("/") or "/x") for k, v in esc.env.items()}
    f = esc.tmp / "sistema.env"
    f.write_text("".join("%s=%s\n" % kv for kv in env.items()), encoding="utf-8")
    rc, out = _validate_env(f, Path(raiz))
    assert rc != 0 and "SISTEMA" in out, out


def test_C5_entradas_de_primer_nivel_ajenas_PARAN_en_validate_env_y_en_la_migracion(esc):
    (esc.state / "otra-aplicacion").mkdir()
    rc, out = _validate_env(esc.env_file(), esc.state)
    assert rc != 0 and "AJENAS" in out and "otra-aplicacion" in out, out
    r = esc.aplicar()
    assert r.rc == 3 and "STATE_ROOT_NO_DEDICADO" in r.lineas[-1], _causa(r)
    assert stat.S_IMODE((esc.state / "auth" / "auth.db").stat().st_mode) == 0o644, "chmod antes del STOP"


def test_C5_escribible_por_otros_PARA(esc):
    esc.state.chmod(0o757)
    rc, out = _validate_env(esc.env_file(), esc.state)
    assert rc != 0 and "OTROS" in out, out


def test_C5_lo_declarado_por_el_entorno_y_los_residuos_de_sonda_no_son_ajenos(esc):
    esc.env["S9K_HEALTH_REPORT_PATH"] = str(esc.state / "informes" / "health.json")
    (esc.state / "informes").mkdir()
    (esc.state / ".s9k-probe-4242").write_text("")
    assert _validate_env(esc.env_file(), esc.state) == (0, "OK\n")
    assert ss.inspect_dedicated_state_root(esc.tmp / "no-existe") == []


# ===========================================================================
# C-4 · el rollback AUTOMÁTICO no reactiva una release anterior a H-06
# ===========================================================================

def _release(tmp: Path, nombre: str, visor: str, worker: str) -> Path:
    d = tmp / nombre
    (d / "viewer" / "systemd").mkdir(parents=True)
    (d / "data-engine" / "systemd").mkdir(parents=True)
    (d / "data-engine" / ".venv" / "bin").mkdir(parents=True)
    (d / "data-engine" / "app" / "jobs").mkdir(parents=True)
    os.symlink(sys.executable, d / "data-engine" / ".venv" / "bin" / "python")
    (d / "data-engine" / "app" / "jobs" / "worker.py").write_text("")
    (d / "viewer" / "systemd" / "s9-knowledge-viewer.service").write_text(visor, encoding="utf-8")
    (d / "data-engine" / "systemd" / "s9-knowledge-worker.service").write_text(worker, encoding="utf-8")
    return d


def _rollback_permitido(tmp: Path, prev: Path):
    log = tmp / "systemctl.log"
    cuerpo = ('systemctl() { echo "$*" >> %s; }\n'
              'if rollback_permitido "%s"; then echo "RC=0"; else echo "RC=$?"; fi\n'
              'echo "RESULTADO=${S9K_ROLLBACK_RESULTADO}"\n') % (log, prev)
    r = subprocess.run(["bash", "-c", "set -Eeuo pipefail\nsource %s\nsource %s\n%s" % (LIB_SH, VALIDATE_SH, cuerpo)],
                       capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})
    llamadas = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return r, llamadas


def test_C4_rollback_a_una_release_anterior_a_H06_NO_se_reactiva_y_para_los_servicios(tmp_path):
    visor_root = U_VISOR.read_text(encoding="utf-8").replace("User=s9knowledge\n", "")
    worker_www = U_WORKER.read_text(encoding="utf-8").replace("User=s9knowledge\n", "User=www-data\n")
    prev = _release(tmp_path, "previa-pre-h06", visor_root, worker_www)
    r, llamadas = _rollback_permitido(tmp_path, prev)
    assert "RC=1" in r.stdout, (r.stdout, r.stderr[-600:])
    assert "rollback NO ejecutado" in r.stdout and "PARADOS" in r.stdout, r.stdout
    assert "stop s9-knowledge-viewer.service" in llamadas and "stop s9-knowledge-worker.service" in llamadas, (
        "ROLLBACK A CIEGAS: %s" % llamadas)


def test_C4_rollback_a_una_release_con_la_identidad_vigente_si_se_reactiva(tmp_path):
    prev = _release(tmp_path, "previa-h06", U_VISOR.read_text(encoding="utf-8"),
                    U_WORKER.read_text(encoding="utf-8"))
    r, llamadas = _rollback_permitido(tmp_path, prev)
    assert "RC=0" in r.stdout and "rollback ejecutado" in r.stdout, (r.stdout, r.stderr[-800:])
    assert not [l for l in llamadas if l.startswith("stop")], llamadas


def test_C4_los_cuatro_rollbacks_de_deploy_pasan_por_la_puerta_y_no_afirman_exito():
    t = DEPLOY_SH.read_text(encoding="utf-8")
    puerta = '[ -n "${PREV_RELEASE_DIR}" ] && [ -d "${PREV_RELEASE_DIR}" ] && rollback_permitido "${PREV_RELEASE_DIR}" && {'
    assert t.count(puerta) == 4, t.count(puerta)
    assert t.count("${S9K_ROLLBACK_RESULTADO}") == 4
    assert "; rollback ejecutado\"" not in t, "un die afirma 'rollback ejecutado' sin saberlo"
    rr = (SCRIPTS / "rollback-release.sh").read_text(encoding="utf-8")
    i = rr.index("target_understands_external_state() {")
    assert "release_entiende_la_identidad" in rr[i:rr.index("\n}\n", i)]


# ===========================================================================
# C-6 · la excepción de tests no entra por drop-in / EnvironmentFile / proceso vivo
# ===========================================================================

def _entorno_efectivo(tmp: Path, env_val: str = "", ef_val: str = "", di_val: str = ""):
    cuerpo = ('systemctl() {\n'
              '  case "$3" in\n'
              '    Environment) printf "%%s\\n" %s ;;\n'
              '    EnvironmentFiles) printf "%%s\\n" %s ;;\n'
              '    DropInPaths) printf "%%s\\n" %s ;;\n'
              '    MainPID) echo 0 ;;\n'
              '  esac\n'
              '}\n'
              'if verificar_entorno_efectivo s9-knowledge-viewer.service; then echo RC=0; else echo RC=1; fi\n'
              ) % (repr(env_val), repr(ef_val), repr(di_val))
    return subprocess.run(["bash", "-c", "set -Eeuo pipefail\nsource %s\n%s" % (LIB_SH, cuerpo)],
                          capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})


def test_C6_entorno_efectivo_limpio_pasa(tmp_path):
    ef = tmp_path / "viewer.env"
    ef.write_text("S9K_AUTH_ENABLED=true\n")
    r = _entorno_efectivo(tmp_path, "A=1 B=2", "%s (ignore_errors=no)" % ef, "")
    assert "RC=0" in r.stdout, (r.stdout, r.stderr)


def test_C6_la_excepcion_en_Environment_efectivo_PARA(tmp_path):
    r = _entorno_efectivo(tmp_path, "A=1 S9K_STATE_VALIDATION=disabled-explicit-for-tests")
    assert "RC=1" in r.stdout and "entorno EFECTIVO" in r.stderr, (r.stdout, r.stderr)


def test_C6_la_excepcion_en_un_EnvironmentFile_extra_PARA(tmp_path):
    extra = tmp_path / "extra.env"
    extra.write_text("# lab\nS9K_STATE_ENFORCE=0\n")
    r = _entorno_efectivo(tmp_path, "", "-%s (ignore_errors=yes)" % extra)
    assert "RC=1" in r.stdout and "EnvironmentFile" in r.stderr, (r.stdout, r.stderr)


def test_C6_la_excepcion_en_un_drop_in_PARA(tmp_path):
    dropin = tmp_path / "override.conf"
    dropin.write_text("[Service]\nEnvironment=S9K_STATE_VALIDATION=disabled-explicit-for-tests\n")
    r = _entorno_efectivo(tmp_path, "", "", str(dropin))
    assert "RC=1" in r.stdout and "drop-in" in r.stderr, (r.stdout, r.stderr)


def test_C6_deploy_verifica_el_entorno_efectivo_con_los_procesos_vivos_y_para():
    t = DEPLOY_SH.read_text(encoding="utf-8")
    i, j = t.index("# Paso 14a "), t.index("# Paso 14b ")
    tramo = t[i:j]
    assert "verificar_entorno_efectivo" in tramo and "die " in tramo.split("verificar_entorno_efectivo", 1)[1]


# ===========================================================================
# C-7 · gate de unidad con la semántica de systemd (R8, R13 y la línea duplicada de M1)
# ===========================================================================

@pytest.mark.parametrize("unidad", [U_VISOR, U_WORKER, U_HEALTH], ids=["visor", "worker", "health"])
def test_C7_R8_R13_las_unidades_reales_no_tienen_hallazgos_de_identidad(unidad):
    errores = ss.inspect_unit_identity(unidad.read_text(encoding="utf-8"))
    assert errores == [], "%s: %s" % (unidad.name, errores)


def _con(texto: str, viejo: str, nuevo: str) -> str:
    assert texto.count(viejo) == 1, viejo
    return texto.replace(viejo, nuevo)


@pytest.mark.parametrize("viejo,nuevo,fragmento", [
    ("User=s9knowledge\n", "User=s9knowledge\nUser=s9knowledge\n", "duplicada"),     # M1: linea duplicada
    ("User=s9knowledge\n", "User=s9knowledge\nUser=root\n", "'root'"),                # el ULTIMO manda
    ("User=s9knowledge\n", "User = root\n", "'root'"),                                # espacios alrededor de =
    ("NoNewPrivileges=true\n", "NoNewPrivileges=true\nAmbientCapabilities=CAP_DAC_READ_SEARCH\n", "AmbientCapabilities"),  # R8
    ("NoNewPrivileges=true\n", "NoNewPrivileges=false\n", "NoNewPrivileges"),          # R13
    ("CapabilityBoundingSet=\n", "CapabilityBoundingSet=CAP_DAC_OVERRIDE\n", "CapabilityBoundingSet"),
    ("CapabilityBoundingSet=\n", "", "CapabilityBoundingSet"),
    ("ExecStart=/opt", "ExecStart=+/opt", "prefijo '+'"),
    ("ExecStart=/opt", "ExecStart=!/opt", "prefijo '!'"),
    ("ExecStart=/opt", "ExecStart=/usr/bin/sudo /opt", "lanza sudo"),
    ("Group=s9knowledge\n", "Group=s9knowledge\nSupplementaryGroups=adm docker\n", "grupo privilegiado"),
    ("Group=s9knowledge\n", "Group=s9knowledge\nDynamicUser=yes\n", "DynamicUser"),
    ("UMask=0077\n", "UMask=0077\nUMask=0022\n", "duplicada"),
], ids=["dup-user", "ultimo-root", "espacios", "ambient", "nnp", "capbs", "capbs-ausente", "plus", "bang",
        "sudo", "grupos", "dynamic", "dup-umask"])
@pytest.mark.parametrize("unidad", [U_VISOR, U_WORKER], ids=["visor", "worker"])
def test_C7_el_gate_rechaza_identidad_y_privilegios_con_semantica_de_ultimo_valor(unidad, viejo, nuevo, fragmento):
    errores = ss.inspect_unit_identity(_con(unidad.read_text(encoding="utf-8"), viejo, nuevo))
    assert any(fragmento in e for e in errores), errores


def test_C7_validate_viewer_unit_usa_la_misma_funcion(tmp_path):
    u = tmp_path / U_VISOR.name
    u.write_text(_con(U_VISOR.read_text(encoding="utf-8"), "User=s9knowledge\n",
                      "User=s9knowledge\nUser=root\n"), encoding="utf-8")
    r = subprocess.run(["bash", "-c", 'source "$1"; validate_viewer_unit "$2" /opt/s9-knowledge/current',
                        "_", str(VALIDATE_SH), str(u)], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})
    assert r.returncode != 0 and "duplicada" in r.stderr, r.stderr


def test_C7_si_la_autoridad_no_responde_la_unidad_no_se_da_por_buena(tmp_path):
    roto = tmp_path / "ss_roto.py"
    roto.write_text("import sys\nsys.exit(9)\n")
    r = subprocess.run(["bash", "-c", 'export S9K_SERVICE_STATE_PY="$3"; source "$1"; validate_viewer_unit "$2" /opt/s9-knowledge/current',
                        "_", str(VALIDATE_SH), str(U_VISOR), str(roto)], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})
    assert r.returncode != 0 and "no se da por buena" in r.stderr, r.stderr


# ===========================================================================
# Testigos de los mutantes supervivientes del revisor: R2 y R3
# ===========================================================================

def test_R2_la_parada_para_visor_worker_y_healthcheck_y_lo_verifica(tmp_path):
    """`parar_y_verificar_servicios` REAL con un systemctl con estado: cada unidad está activa
    hasta que se la para. Si no se para el worker, el estado se tocaria con el worker vivo."""
    estado = tmp_path / "activos"
    estado.mkdir()
    for u in ("s9-knowledge-viewer.service", "s9-knowledge-worker.service", "s9-knowledge-healthcheck.service"):
        (estado / u).write_text("")
    log = tmp_path / "systemctl.log"
    cuerpo = ('sleep() { :; }\n'
              'systemctl() {\n'
              '  echo "$*" >> %(log)s\n'
              '  case "$1" in\n'
              '    is-active) [ "$2" = "--quiet" ] && shift; [ -e "%(est)s/$2" ] ;;\n'
              '    stop) rm -f "%(est)s/$2" ;;\n'
              '    show) echo 0 ;;\n'
              '  esac\n'
              '}\n'
              'if parar_y_verificar_servicios; then echo RC=0; else echo RC=1; fi\n') % {"log": log, "est": estado}
    r = subprocess.run(["bash", "-c", "set -Eeuo pipefail\nsource %s\n%s" % (LIB_SH, cuerpo)],
                       capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})
    llamadas = log.read_text(encoding="utf-8").splitlines()
    assert "RC=0" in r.stdout, "R2: PARADA NO VERIFICADA: " + r.stderr[-300:].replace("\n", " | ")
    for u in ("s9-knowledge-worker.service", "s9-knowledge-viewer.service", "s9-knowledge-healthcheck.service"):
        assert "stop %s" % u in llamadas, "R2: NO PARA %s: %s" % (u, llamadas)
    assert list(estado.iterdir()) == []


def test_R3_la_migracion_hace_chown_de_cada_entrada_ajena_no_solo_chmod(esc, monkeypatch):
    """R3 (mutante del revisor): chmod aplicado pero chown no. Se registra `lchown` con un
    propietario esperado DISTINTO del real (sin root no se puede cambiar de verdad)."""
    vistos = []
    monkeypatch.setattr(mg.os, "lchown", lambda ruta, u, g: vistos.append((str(ruta), u, g)))
    monkeypatch.setattr(mg.os, "chown", lambda ruta, u, g: None)   # directorios/copias del paso 7
    esc.aplicar(uid=UID + 4242, gid=GID + 4242)
    rutas = {r for r, _u, _g in vistos}
    esperadas = {str(esc.state), str(esc.state / "auth" / "auth.db"), str(esc.rv3 / "review.sqlite3"),
                 str(esc.rv3 / "decisions.jsonl")}
    assert esperadas <= rutas, "LCHOWN NO LLAMADO para %s" % sorted(esperadas - rutas)
    assert all((u, g) == (UID + 4242, GID + 4242) for _r, u, g in vistos)


# ===========================================================================
# Ronda 2b · C-5: `lost+found` de un FS DEDICADO (root:root 0700) no es contenido ajeno
# ===========================================================================

def _st(modo, uid=0, gid=0):
    return os.stat_result((modo, 1, 1, 2, uid, gid, 4096, 0, 0, 0))


@pytest.mark.parametrize("nombre,st,esperado", [
    ("lost+found", _st(stat.S_IFDIR | 0o700), True),
    ("lost+found", _st(stat.S_IFDIR | 0o755), False),          # modo distinto
    ("lost+found", _st(stat.S_IFDIR | 0o700, uid=1000), False),  # dueño distinto
    ("lost+found", _st(stat.S_IFDIR | 0o700, gid=4), False),     # grupo distinto
    ("lost+found", _st(stat.S_IFREG | 0o700), False),            # no es directorio
    ("lost+found", _st(stat.S_IFLNK | 0o777), False),            # symlink
    ("lost+found2", _st(stat.S_IFDIR | 0o700), False),           # otro nombre
])
def test_C5_lost_found_solo_con_sus_atributos_exactos(nombre, st, esperado):
    assert ss.es_lost_found_del_fs(nombre, st) is esperado


def test_C5_lost_found_del_fs_no_bloquea_ni_se_toca_y_nada_mas_se_admite(esc, monkeypatch):
    """Sin root no se puede crear un `lost+found` de root: se planta uno 0700 propio y la
    decisión «es del FS» se acota a ESE directorio (el predicado exacto se prueba arriba; el
    real, root:root, en VM112). Validate-env, migración y arranque lo ignoran y NO lo tocan;
    un `lost+found` con otro modo sigue siendo ajeno."""
    lf = esc.state / "lost+found"
    lf.mkdir()
    lf.chmod(0o700)
    (lf / "#123").write_text("bloque huerfano de fsck")
    (lf / "#123").chmod(0o644)
    real = ss.es_lost_found_del_fs
    monkeypatch.setattr(ss, "es_lost_found_del_fs",
                        lambda nombre, st: nombre == "lost+found" and stat.S_ISDIR(st.st_mode)
                        and stat.S_IMODE(st.st_mode) == 0o700)
    monkeypatch.setattr(mg, "_ss", lambda: ss)
    assert ss.inspect_dedicated_state_root(esc.state, {}) == []
    r = esc.aplicar()
    assert r.rc == 0, _causa(r)
    assert stat.S_IMODE(lf.stat().st_mode) == 0o700 and stat.S_IMODE((lf / "#123").stat().st_mode) == 0o644, (
        "la migracion toco lost+found")
    assert ss.inspect_state(esc.state, uid=UID, gid=GID) == []
    lf.chmod(0o755)
    monkeypatch.setattr(ss, "es_lost_found_del_fs", real)
    assert any(v.code == "FOREIGN" for v in ss.inspect_dedicated_state_root(esc.state, {}))


# ===========================================================================
# Ronda 2b · testigos de los mutantes X3 y X4 del revisor
# ===========================================================================

def test_X3_un_symlink_PROFUNDO_dentro_de_un_directorio_legacy_PARA_sin_mover_nada(esc):
    """X3: un pre-escaneo que solo mira el primer nivel no ve el symlink de un subdirectorio."""
    sub = esc.rv3_rel / "proposals" / "lote" / "dentro"
    sub.mkdir(parents=True)
    (esc.tmp / "fuera.json").write_text("{}")
    os.symlink(esc.tmp / "fuera.json", sub / "enlace.json")
    antes_rel = _foto(esc.release)
    r = esc.aplicar()
    assert r.rc == 3 and "STOP[SYMLINK]" in r.lineas[-1], _causa(r)
    assert _foto(esc.release) == antes_rel and not (esc.rv3 / "decisions.jsonl").exists(), (
        "X3: MOVIO ANTES DE VER EL SYMLINK PROFUNDO")


def test_X4_rollback_a_una_release_SIN_unidad_del_visor_NO_se_reactiva(tmp_path):
    prev = _release(tmp_path, "previa-sin-unidad", U_VISOR.read_text(encoding="utf-8"),
                    U_WORKER.read_text(encoding="utf-8"))
    (prev / "viewer" / "systemd" / "s9-knowledge-viewer.service").unlink()
    r, llamadas = _rollback_permitido(tmp_path, prev)
    assert "RC=1" in r.stdout, "X4: SE REACTIVA UNA RELEASE SIN UNIDAD: " + r.stdout[-200:]
    assert "stop s9-knowledge-viewer.service" in llamadas
