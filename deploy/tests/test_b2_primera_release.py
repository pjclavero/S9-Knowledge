# -*- coding: utf-8 -*-
"""Testigo E2E LOCAL de B2 (USABLE-V1): de maquina limpia a INSTALLATION_COMPLETE.

ESTADO
------
::

    CODE         PASS      recorrido completo contra el VISOR REAL por TLS local
    CALIBRATION  PASS      (las garantias de cada tramo, en el testigo rapido)
    RC-E2E       PENDING   sin nginx, sin systemd, sin VM, sin navegador, sin CA real

QUE ES REAL AQUI
----------------
* La CONFIGURACION: la plantilla productiva ``deploy/config/viewer.env.example``
  LITERAL, cambiando solo el prefijo del state root (ruta de host) y la URL
  publica (lo unico que la plantilla dice que hay que cambiar) y declarando el
  ``S9K_TLS_CA_FILE`` del autofirmado. ``S9K_SESSION_SECURE=true``, sin
  ``S9K_CSRF_SECRET``, proveedor ``not_configured``. Se carga en el visor
  igual que lo haria ``EnvironmentFile``: con el lector del despliegue.
* El TEXTO de ``deploy.sh``: pasos 3-4 (decision), 6 (validacion del
  ``viewer.env``) y 16b-17 (HTTPS por efecto, GATE A, linea de estado),
  extraidos entre marcas UNICAS y ejecutados con ``bash``.
* ``current``: lo pone ``lib.sh::atomic_symlink`` y el visor arranca CON
  ``current/viewer`` como directorio de trabajo.
* El VISOR: ``app.main:app`` como proceso separado por ``uvicorn`` con TLS
  autofirmado. El reinicio MATA el proceso y arranca otro.
* Las credenciales del GATE B: generadas por el TESTIGO (que hace de
  operador) y entregadas por fichero ``0600``. El instalador no inventa
  ninguna.

QUE NO ES REAL (y por eso RC-E2E sigue PENDING)
------------------------------------------------
La release no se clona ni se construye su venv (``releases/<id>/viewer`` es
un enlace al arbol del repositorio y el interprete es el del testigo): eso
exige red y pip. No hay systemd (pasos 7-13), ni nginx, ni una CA real, ni un
navegador, ni una VM limpia, ni reinicio de MAQUINA.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SCRIPTS = _TESTS.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import detect_state as ds  # noqa: E402
import preflight_ensayo_rc as rc_mod  # noqa: E402
import preflight_setup_admin as ps  # noqa: E402
from test_b2_fresh_install import (  # noqa: E402
    LIB_SH, PLANTILLA_VISOR, _correr_bash, _paso4, _paso6, _tramo_de_deploy,
    plantilla_productiva_en)
from test_preflight_setup_admin import (  # noqa: E402
    VisorReal, _certificado, _puerto_libre)

RAIZ = Path(__file__).resolve().parents[2]
VIEWER = RAIZ / "viewer"


class VisorDesdeCurrent(VisorReal):
    """El visor real arrancado DESDE ``current/viewer`` con el entorno dado.

    Reutiliza la espera por PID y por condicion final, y la parada, de
    ``VisorReal`` (#267). Cambia lo que el despliegue fija: el directorio de
    trabajo, el entorno (el ``viewer.env``, no el del testigo) y un puerto
    estable a traves del reinicio (la URL publica lo nombra).
    """

    def __init__(self, cwd: Path, entorno: dict, cert, puerto: int):
        self.cwd = cwd
        self.entorno_fijo = dict(entorno)
        self.puerto_fijo = puerto
        super().__init__(db_path=None, cert=cert)

    def _entorno(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
        env.update(self.entorno_fijo)
        env["PYTHONPATH"] = str(self.cwd)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def _arrancar(self) -> None:
        self.puerto = self.puerto_fijo
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
               "--host", "127.0.0.1", "--port", str(self.puerto), "--log-level", "error"]
        if self.cert:
            cmd += ["--ssl-certfile", str(self.cert[0]), "--ssl-keyfile", str(self.cert[1])]
        self.proc = subprocess.Popen(cmd, cwd=str(self.cwd), env=self._entorno(),
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self._esperar_a_que_conteste()


def _usuarios_y_sello(auth_db: Path):
    con = sqlite3.connect("file:%s?mode=ro" % auth_db, uri=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        con.close()
    return n, ds.sello_de_instalacion(str(auth_db))


def _credenciales_0600(tmp: Path) -> Path:
    """La contrasena la APORTA el operador (aqui, el testigo). Nunca el instalador."""
    f = tmp / "cred.json"
    f.write_text('{"usuario": "lab-admin-%s", "password": "lab-%s-%s"}' % (
        secrets.token_hex(3), secrets.token_hex(8), secrets.token_hex(4)))
    f.chmod(0o600)
    return f


def _tramo_final(env: Path, raiz: Path, s9k_root: Path, *, ambiente: str,
                 primer_admin_pendiente: str):
    """Pasos 16b a 17 de deploy.sh, TEXTO REAL, contra el visor vivo."""
    cuerpo = """
HERE=%s
VIEWER_ENV=%s
ENVIRONMENT=%s
MODE=fresh
DECISION=PROCEED
RELEASE_ID=b2-e2e
PRIMER_ADMIN_PENDIENTE=%s
S9K_STATE_ROOT=%s
S9K_ROOT=%s
S9K_DEPLOY_STATE_FILE=%s/deploy/deployment-state.json
%s
""" % (_SCRIPTS, env, ambiente, primer_admin_pendiente, raiz, s9k_root, raiz,
       _tramo_de_deploy("# Paso 16b: vía HTTPS, VERIFICADA POR EFECTO.",
                        'INSTALLATION_COMPLETE solo tras el GATE B --modo persistencia DESPUÉS de un reinicio."\nfi'))
    r = _correr_bash(cuerpo, {})
    return r.returncode, r.stdout + r.stderr


def _activar_current(s9k_root: Path) -> Path:
    """Una release cuyo contenido es el del repositorio, y `current` -> ella."""
    release = s9k_root / "releases" / "b2-e2e"
    release.mkdir(parents=True)
    (release / "viewer").symlink_to(VIEWER, target_is_directory=True)
    r = subprocess.run(["bash", "-c", 'source "$1"; atomic_symlink "$2" "$3"', "_",
                        str(LIB_SH), str(release), str(s9k_root / "current")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    current = s9k_root / "current"
    assert current.is_symlink() and current.resolve() == release.resolve()
    return current


@pytest.fixture
def cert_localhost(tmp_path):
    return _certificado(tmp_path, "localhost", "b2e2e")


def test_de_maquina_limpia_a_installation_complete(tmp_path, cert_localhost):
    """El recorrido entero, con cada estado medido y ninguno adelantado."""
    cert, _ = cert_localhost
    puerto = _puerto_libre()
    url = "https://localhost:%d" % puerto
    env, raiz = plantilla_productiva_en(tmp_path, url, ca_file=str(cert))
    entorno = rc_mod.entorno_desde_env_file(env)
    auth_db = Path(entorno["S9K_AUTH_DB_PATH"])
    jobs_db = Path(entorno["S9K_JOBS_DB"])
    assert entorno["S9K_SESSION_SECURE"] == "true"
    assert "S9K_CSRF_SECRET" not in entorno
    assert entorno["S9K_GRAPH_PROVIDER"] == "not_configured"
    s9k_root = tmp_path / "opt-s9k"

    # Pasos 3-4: maquina limpia + --mode fresh -> sigue, primer admin PENDIENTE.
    rc, out = _paso4(tmp_path, "fresh", new_auth=auth_db, new_jobs=jobs_db)
    assert rc == 0 and "FIRST_ADMIN_PENDING" in out, out
    # Paso 6: la plantilla literal pasa.
    rc, out = _paso6(env, raiz)
    assert rc == 0, out
    # Paso 12: `current` activo.
    current = _activar_current(s9k_root)

    visor = VisorDesdeCurrent(current / "viewer", entorno, cert_localhost, puerto)
    try:
        # El visor crea su base (vacia, sin sello) y el secreto CSRF 0600.
        assert _usuarios_y_sello(auth_db) == (0, False)
        secreto = auth_db.parent / ".csrf_secret"
        assert secreto.is_file() and (secreto.stat().st_mode & 0o077) == 0, (
            "el secreto CSRF autogenerado tiene que quedar 0600 junto a la auth DB")

        # Pasos 16b-17: HTTPS por efecto + GATE A + linea de estado.
        rc, out = _tramo_final(env, raiz, s9k_root, ambiente="production",
                               primer_admin_pendiente="true")
        assert rc == 0, out
        assert "OK (GATE A)" in out, out
        assert "ESTADO_INSTALACION=FIRST_ADMIN_PENDING" in out, out
        assert "INSTALLATION_COMPLETE" not in out.replace(
            "INSTALLATION_COMPLETE solo tras", ""), (
            "deploy.sh terminado sin administrador NO es instalacion completa")
        # GATE A NO escribe: ni usuarios ni sello.
        assert _usuarios_y_sello(auth_db) == (0, False), "el GATE A no puede crear nada"

        registro = raiz / "deploy" / "instalacion.json"
        cred = _credenciales_0600(tmp_path)

        # GATE B (1): recorrido completo con la contrasena aportada.
        r = subprocess.run([sys.executable, str(_SCRIPTS / "preflight_setup_admin.py"),
                            "--env-file", str(env), "--modo", "bootstrap",
                            "--credenciales-desde", str(cred), "--registro", str(registro)],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ESTADO_INSTALACION=FIRST_ADMIN_VERIFIED" in r.stdout, r.stdout
        assert cred.read_text().split('"password": "')[1].split('"')[0] not in r.stdout + r.stderr
        usuarios, sello = _usuarios_y_sello(auth_db)
        assert usuarios == 1 and sello is True

        # El ESTADO DEL PRODUCTO distingue ahora upgrade de fresh.
        assert ds.detect(None, None, str(auth_db), str(jobs_db), "upgrade")["decision"] == "PROCEED"
        assert ds.detect(None, None, str(auth_db), str(jobs_db), "fresh")["decision"] == "BLOCK"

        # GATE B (2): parar -> arrancar -> el login sigue y el sello tambien.
        visor.reiniciar()
        r = subprocess.run([sys.executable, str(_SCRIPTS / "preflight_setup_admin.py"),
                            "--env-file", str(env), "--modo", "persistencia",
                            "--credenciales-desde", str(cred), "--registro", str(registro)],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ESTADO_INSTALACION=INSTALLATION_COMPLETE" in r.stdout, r.stdout
    finally:
        visor.parar()


def test_http_plano_reproduce_el_fallo_y_no_se_declara_completo(tmp_path):
    """Plantilla literal servida por HTTP plano con Secure=true (D3 intacta)."""
    puerto = _puerto_libre()
    env, raiz = plantilla_productiva_en(tmp_path, "http://localhost:%d" % puerto)
    entorno = rc_mod.entorno_desde_env_file(env)
    auth_db = Path(entorno["S9K_AUTH_DB_PATH"])
    s9k_root = tmp_path / "opt-s9k"
    current = _activar_current(s9k_root)
    visor = VisorDesdeCurrent(current / "viewer", entorno, None, puerto)
    try:
        # El fallo conocido, reproducido por efecto: GET impecable, POST 403.
        cliente = ps.ClienteConCookies(visor.base_url, timeout=20.0)
        rec = ps.Recorrido()
        assert ps.comprobar_get_del_formulario(cliente, rec) is None
        assert rec.cookie_secure is True
        hallazgo = ps.comprobar_csrf_funcional(cliente, rec)
        assert rec.csrf_validacion == 403, rec
        assert hallazgo is not None and hallazgo.causa == "COOKIE_SECURE_SOBRE_HTTP", (
            "sobre HTTP plano el GATE A tiene que nombrar la cookie Secure que no "
            "vuelve, no un CSRF roto; dio %s" % (hallazgo,))

        # Y deploy.sh NO llega a la linea de estado: muere en 16b.
        rc, out = _tramo_final(env, raiz, s9k_root, ambiente="production",
                               primer_admin_pendiente="true")
        assert rc != 0, out
        assert "INSTALACIÓN NO COMPLETA" in out, out
        assert "ESTADO_INSTALACION=" not in out, out
        assert _usuarios_y_sello(auth_db) == (0, False)
    finally:
        visor.parar()


def test_la_plantilla_de_desarrollo_literal_pasa_el_gate_a_por_https(tmp_path, cert_localhost):
    """`cp viewer/.env.example .env` tal cual, servido por HTTPS: CSRF funcional.

    Solo se fijan las RUTAS de estado (la plantilla las deja vacias y caerian
    dentro del arbol del repositorio que el testigo no debe ensuciar).
    """
    cert, _ = cert_localhost
    puerto = _puerto_libre()
    entorno = rc_mod.entorno_desde_env_file(PLANTILLA_VISOR)
    assert entorno["S9K_SESSION_SECURE"] == "true"
    assert entorno["S9K_GRAPH_PROVIDER"] == "not_configured"
    assert "S9K_CSRF_SECRET" not in entorno
    estado = tmp_path / "estado"
    (estado / "reviews-v3" / "proposals").mkdir(parents=True)
    entorno.update({
        "S9K_AUTH_DB_PATH": str(estado / "auth.db"),
        "S9K_JOBS_DB": str(estado / "jobs.db"),
        "S9K_V3_REVIEW_DATABASE_PATH": str(estado / "reviews-v3" / "review.sqlite3"),
        "S9K_V3_REVIEW_PROPOSALS_DIR": str(estado / "reviews-v3" / "proposals"),
    })
    visor = VisorDesdeCurrent(VIEWER, entorno, cert_localhost, puerto)
    try:
        hallazgos, rec = ps.verificar_gate_a(ps.Entrada(
            url=visor.base_url, session_secure=True,
            credenciales=ps.Credenciales("-", ""), ca_file=str(cert),
            modo="gate-a", timeout=30.0))
        assert hallazgos == [], [str(h) for h in hallazgos]
        assert rec.csrf_validacion == 400
        assert _usuarios_y_sello(estado / "auth.db") == (0, False)
    finally:
        visor.parar()
