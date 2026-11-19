# -*- coding: utf-8 -*-
"""D-2 — la declaracion del sandbox del healthcheck solo es legitima en SU unidad.

``S9K_HEALTH_VAULT_MEDICION=no-medible-sandbox`` hace que el check de la boveda diga UNMEASURABLE
en vez de medir. Con el sandbox del healthcheck es honesto; en el entorno del visor o del worker
taparia un READ_ONLY/UNAVAILABLE real. Y una declaracion sin sandbox (un drop-in lo quito) oculta
un fallo real. El nombre y el valor NO se copian aqui: se leen de su autoridad.

Capas cubiertas (la RC-E2E con root y systemd real queda fuera, ver README):
  * ``service_state.py validate-env`` (ficheros .env del visor y del worker);
  * ``service_state.py unit-check --rol`` (texto de la unidad: lo usa ``validate_deploy.sh``);
  * ``lib.sh::verificar_entorno_efectivo`` (Environment efectivo, EnvironmentFiles, drop-ins,
    /proc/<pid>/environ y sandbox efectivo), con ``systemctl`` sustituido por una funcion.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "deploy" / "scripts"
SS_PY = RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"
LIB_SH = SCRIPTS / "lib.sh"
VALIDATE_SH = SCRIPTS / "validate_deploy.sh"
U_VISOR = RAIZ / "viewer" / "systemd" / "s9-knowledge-viewer.service"
U_WORKER = RAIZ / "data-engine" / "systemd" / "s9-knowledge-worker.service"
U_HEALTH = RAIZ / "viewer" / "systemd" / "s9-knowledge-healthcheck.service"
CHECKS_PY = RAIZ / "viewer" / "app" / "health" / "checks.py"


def _cargar(nombre, ruta):
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = m
    spec.loader.exec_module(m)
    return m


ss = _cargar("_s9k_service_state", SS_PY)
VAR, VALOR = ss.health_vault_declaration()
DECLARACION = "%s=%s" % (VAR, VALOR)


def test_D2_el_nombre_y_el_valor_vienen_de_la_autoridad_no_de_una_copia():
    # son los literales de las constantes del check, leidos por AST
    texto = CHECKS_PY.read_text(encoding="utf-8")
    assert 'VAULT_MEDICION_ENV = "%s"' % VAR in texto
    assert 'VAULT_MEDICION_SANDBOX = "%s"' % VALOR in texto
    # y el modulo de despliegue no tiene los literales copiados
    codigo = SS_PY.read_text(encoding="utf-8")
    for linea in codigo.splitlines():
        if linea.lstrip().startswith("#") or linea.lstrip().startswith('"""'):
            continue
        assert VAR not in linea and VALOR not in linea, "literal copiado en: %s" % linea


def test_D2_la_autoridad_ilegible_es_un_fallo_no_un_pase(tmp_path):
    with pytest.raises(RuntimeError):
        ss.health_vault_declaration(tmp_path)
    (tmp_path / "viewer" / "app" / "health").mkdir(parents=True)
    (tmp_path / "viewer" / "app" / "health" / "checks.py").write_text("VAULT_MEDICION_ENV = 'X'\n")
    with pytest.raises(RuntimeError):
        ss.health_vault_declaration(tmp_path)


# ---------------------------------------------------------------------------
# validate-env: viewer.env y worker.env
# ---------------------------------------------------------------------------
def _validate_env(tmp: Path, rol: str, extra: str):
    state = tmp / "var" / "lib" / "s9-knowledge"
    (state / "auth").mkdir(parents=True)
    state.chmod(0o700)
    env = {
        "S9K_STATE_ROOT": str(state),
        "S9K_AUTH_DB_PATH": str(state / "auth" / "auth.db"),
        "S9K_JOBS_DB": str(state / "jobs" / "jobs.db"),
        "S9K_V3_REVIEW_DATABASE_PATH": str(state / "reviews-v3" / "review.sqlite3"),
        "S9K_V3_REVIEW_PROPOSALS_DIR": str(state / "reviews-v3" / "proposals"),
    }
    f = tmp / ("%s.env" % rol)
    f.write_text("".join("%s=%s\n" % kv for kv in env.items()) + extra, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SS_PY), "validate-env", "--env-file", str(f),
                        "--state-root", str(state), "--role", rol], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("rol", ["viewer", "worker"])
def test_D2_validate_env_rechaza_la_declaracion_y_nombra_variable_y_donde_se_permite(tmp_path, rol):
    rc, out = _validate_env(tmp_path, rol, DECLARACION + "\n")
    assert rc == 3, "NO RECHAZA la declaracion: rc=%s salida=%r" % (rc, out)
    assert VAR in out and "healthcheck" in out and "s9-knowledge-healthcheck.service" in out, out
    assert "UNMEASURABLE" in out and ("%s.env" % rol) in out, out


@pytest.mark.parametrize("rol", ["viewer", "worker"])
def test_D2_validate_env_acepta_el_entorno_sin_la_declaracion(tmp_path, rol):
    rc, out = _validate_env(tmp_path, rol, "")
    assert (rc, out) == (0, "OK\n"), "RECHAZA UN ENTORNO LIMPIO: %r" % out


def test_D2_validate_env_rechaza_la_variable_con_cualquier_valor_no_vacio(tmp_path):
    rc, out = _validate_env(tmp_path, "viewer", "%s=lo-que-sea\n" % VAR)
    assert rc == 3 and VAR in out, out


# ---------------------------------------------------------------------------
# unit-check --rol (texto de la unidad)
# ---------------------------------------------------------------------------
def test_D2_las_unidades_canonicas_cumplen():
    for rol, u in (("viewer", U_VISOR), ("worker", U_WORKER), ("health", U_HEALTH)):
        errs = ss.inspect_unit_vault_declaration(u.read_text(encoding="utf-8"), rol)
        assert errs == [], "UNIDAD %s INCUMPLE: %s" % (rol, errs)


@pytest.mark.parametrize("rol,unidad", [("viewer", U_VISOR), ("worker", U_WORKER)])
def test_D2_una_unidad_de_visor_o_worker_con_la_declaracion_se_rechaza(rol, unidad):
    t = unidad.read_text(encoding="utf-8").replace("[Service]\n", "[Service]\nEnvironment=%s\n" % DECLARACION, 1)
    errores = ss.inspect_unit_vault_declaration(t, rol)
    assert errores and VAR in errores[0] and "solo es legitima en la unidad del healthcheck" in errores[0], \
        "NO dice que solo es legitima en el healthcheck: %s" % errores


def test_D2_la_unidad_del_healthcheck_sin_sandbox_pero_con_declaracion_se_rechaza():
    t = U_HEALTH.read_text(encoding="utf-8")
    for clave in ("ProtectSystem=strict\n", "ReadOnlyPaths=/opt/s9-knowledge /etc/s9-knowledge\n", "ProtectHome=true\n"):
        assert t.count(clave) == 1, clave
        t = t.replace(clave, "")
    assert ss.sandbox_de_ficheros(ss.parse_unit(t)["Service"]) == []
    errores = ss.inspect_unit_vault_declaration(t, "health")
    assert errores and "NO tiene sandbox" in errores[0], errores


def test_D2_la_declaracion_comentada_no_cuenta():
    t = U_VISOR.read_text(encoding="utf-8").replace("[Service]\n", "[Service]\n# %s\n" % DECLARACION, 1)
    assert ss.inspect_unit_vault_declaration(t, "viewer") == []


def _unit_check(tmp: Path, texto: str, rol: str):
    f = tmp / "u.service"
    f.write_text(texto, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SS_PY), "unit-check", str(f), "--rol", rol],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_D2_unit_check_cli_con_rol(tmp_path):
    ok = U_VISOR.read_text(encoding="utf-8")
    assert _unit_check(tmp_path, ok, "viewer") == (0, "")
    mal = ok.replace("[Service]\n", "[Service]\nEnvironment=%s\n" % DECLARACION, 1)
    rc, out = _unit_check(tmp_path, mal, "viewer")
    assert rc == 3 and VAR in out, out


def test_D2_validate_deploy_sh_pasa_el_rol_a_la_autoridad(tmp_path):
    """Por efecto: `validate_deploy.sh unit` rechaza la unidad del visor con la declaracion."""
    ok = tmp_path / "ok.service"
    ok.write_text(U_VISOR.read_text(encoding="utf-8"), encoding="utf-8")
    mal = tmp_path / "mal.service"
    mal.write_text(U_VISOR.read_text(encoding="utf-8").replace(
        "[Service]\n", "[Service]\nEnvironment=%s\n" % DECLARACION, 1), encoding="utf-8")
    def corre(u, modo="unit"):
        return subprocess.run(["bash", str(VALIDATE_SH), modo, str(u)], capture_output=True, text=True)
    assert "BLOCK" not in corre(ok).stderr or VAR not in corre(ok).stderr
    r = corre(mal)
    assert r.returncode != 0 and VAR in r.stderr, (r.returncode, r.stderr)
    # la unidad del healthcheck canonica la admite; sin sandbox, no
    assert VAR not in corre(U_HEALTH, "health-unit").stderr
    sin = tmp_path / "salud.service"
    t = U_HEALTH.read_text(encoding="utf-8")
    for clave in ("ProtectSystem=strict\n", "ReadOnlyPaths=/opt/s9-knowledge /etc/s9-knowledge\n", "ProtectHome=true\n"):
        t = t.replace(clave, "")
    sin.write_text(t, encoding="utf-8")
    r = corre(sin, "health-unit")
    assert r.returncode != 0 and "NO tiene sandbox" in r.stderr, (r.returncode, r.stderr)


# ---------------------------------------------------------------------------
# verificar_entorno_efectivo (lib.sh)
# ---------------------------------------------------------------------------
def _efectivo(tmp: Path, unidad: str, *, env="", ef="", di="", pid="0", sandbox=None):
    """Ejecuta la funcion REAL de lib.sh con `systemctl` simulado."""
    sandbox = "ProtectSystem=strict\nProtectHome=yes\n" if sandbox is None else sandbox
    cuerpo = (
        'systemctl() {\n'
        '  case "$3" in\n'
        '    Environment) printf "%%s\\n" %s ;;\n'
        '    EnvironmentFiles) printf "%%s\\n" %s ;;\n'
        '    DropInPaths) printf "%%s\\n" %s ;;\n'
        '    MainPID) echo %s ;;\n'
        '    *) printf "%%b" %s ;;\n'   # `show -p A -p B ... unidad` (sandbox)
        '  esac\n'
        '}\n'
        'if verificar_entorno_efectivo %s; then echo RC=0; else echo RC=1; fi\n'
    ) % (repr(env), repr(ef), repr(di), pid, repr(sandbox), unidad)
    return subprocess.run(["bash", "-c", "set -Eeuo pipefail\nsource %s\n%s" % (LIB_SH, cuerpo)],
                          capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})


VISOR, WORKER, SALUD = ("s9-knowledge-viewer.service", "s9-knowledge-worker.service",
                        "s9-knowledge-healthcheck.service")


@pytest.mark.parametrize("unidad", [VISOR, WORKER])
def test_D2_efectivo_Environment_de_visor_o_worker_con_la_declaracion_PARA(tmp_path, unidad):
    r = _efectivo(tmp_path, unidad, env="A=1 " + DECLARACION)
    assert "RC=1" in r.stdout and VAR in r.stderr and SALUD in r.stderr, (r.stdout, r.stderr)


def test_D2_efectivo_EnvironmentFile_compartido_con_la_declaracion_PARA_tambien_en_el_healthcheck(tmp_path):
    ef = tmp_path / "viewer.env"
    ef.write_text("# nota\n%s\n" % DECLARACION)
    for unidad in (VISOR, SALUD):
        r = _efectivo(tmp_path, unidad, ef="%s (ignore_errors=no)" % ef)
        assert "RC=1" in r.stdout and "EnvironmentFile" in r.stderr and VAR in r.stderr, (unidad, r.stdout, r.stderr)


def test_D2_efectivo_EnvironmentFile_con_la_declaracion_solo_comentada_pasa(tmp_path):
    ef = tmp_path / "viewer.env"
    ef.write_text("# %s\nA=1\n" % DECLARACION)
    r = _efectivo(tmp_path, VISOR, ef="%s (ignore_errors=no)" % ef)
    assert "RC=0" in r.stdout, (r.stdout, r.stderr)


def test_D2_efectivo_drop_in_del_visor_con_la_declaracion_PARA(tmp_path):
    di = tmp_path / "override.conf"
    di.write_text("[Service]\nEnvironment=%s\n" % DECLARACION)
    r = _efectivo(tmp_path, VISOR, di=str(di))
    assert "RC=1" in r.stdout and "drop-in" in r.stderr and VAR in r.stderr, (r.stdout, r.stderr)


def test_D2_efectivo_proceso_vivo_del_worker_con_la_declaracion_PARA(tmp_path):
    # /proc/<pid>/environ real: un hijo vivo con la variable en SU entorno
    hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            env={**os.environ, VAR: VALOR})
    try:
        r = _efectivo(tmp_path, WORKER, pid=str(hijo.pid))
        assert "RC=1" in r.stdout and "VIVO" in r.stderr and VAR in r.stderr, (r.stdout, r.stderr)
    finally:
        hijo.kill()
        hijo.wait()


def test_D2_efectivo_la_unidad_del_healthcheck_con_declaracion_y_sandbox_pasa(tmp_path):
    r = _efectivo(tmp_path, SALUD, env="A=1 " + DECLARACION)
    assert "RC=0" in r.stdout, (r.stdout, r.stderr)


def test_D2_efectivo_healthcheck_con_declaracion_y_sin_sandbox_efectivo_PARA(tmp_path):
    # un drop-in quito ProtectSystem/ProtectHome conservando la declaracion
    r = _efectivo(tmp_path, SALUD, env="A=1 " + DECLARACION, sandbox="ProtectSystem=no\nProtectHome=no\nReadOnlyPaths=\n")
    assert "RC=1" in r.stdout and "sandbox de ficheros EFECTIVO" in r.stderr and VAR in r.stderr, (r.stdout, r.stderr)


def test_D2_efectivo_healthcheck_sin_declaracion_no_exige_sandbox(tmp_path):
    r = _efectivo(tmp_path, SALUD, env="A=1", sandbox="ProtectSystem=no\n")
    assert "RC=0" in r.stdout, (r.stdout, r.stderr)


def test_D2_efectivo_sin_poder_leer_la_autoridad_PARA(tmp_path):
    r = subprocess.run(["bash", "-c", "set -Eeuo pipefail\nsource %s\nS9K_SERVICE_STATE_PY=/no/existe.py\n"
                        "systemctl() { :; }\nif verificar_entorno_efectivo %s; then echo RC=0; else echo RC=1; fi\n"
                        % (LIB_SH, VISOR)], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("S9K_")})
    assert "RC=1" in r.stdout and "autoridad" in r.stderr, (r.stdout, r.stderr)


def test_D2_el_deploy_sh_sigue_parando_con_verificar_entorno_efectivo():
    t = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
    i = t.index("verificar_entorno_efectivo")
    assert "die " in t[i:i + 400] and "sandbox del healthcheck" in t[i:i + 700]
