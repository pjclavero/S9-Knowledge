# -*- coding: utf-8 -*-
"""Testigo RAPIDO de B2 (USABLE-V1): familia fresh install (H-01, H-43, H-44, H-49).

ESTADO
------
::

    CODE         PASS      paso 4 y paso 6 REALES de deploy.sh, plantillas, GATE A
    CALIBRATION  PASS      scripts/calibracion/mutaciones_b2_fresh_install.py
    RC-E2E       PENDING   sin nginx, sin systemd, sin VM, sin navegador

QUE SE EJECUTA DE VERDAD
------------------------
* El PASO 4 de ``deploy/scripts/deploy.sh`` (y el 3, que lo alimenta): se
  extrae el TEXTO REAL del guion entre sus marcas (``# Paso 3: detectar
  layout/estado`` y ``# --- fin del paso 4 ---``, cada una UNICA en el
  fichero: si dejan de serlo, el testigo lo dice en vez de elegir) y se
  ejecuta con ``bash`` sobre un state root temporal, con las funciones de
  ``lib.sh``. No es un ``bash -n``: corre ``detect_state.py`` y, si toca,
  ``migrate_sqlite.py`` contra bases SQLite de verdad.
* El PASO 6 de ``deploy.sh`` igual (marcas ``# Paso 6:`` y ``# --- fin del
  paso 6 ---``), contra la PLANTILLA PRODUCTIVA LITERAL: la unica diferencia
  con ``deploy/config/viewer.env.example`` es el prefijo del state root (una
  ruta de host) y la URL publica (lo unico que la plantilla dice que hay que
  cambiar). El testigo COMPRUEBA que no hay ninguna otra diferencia.
* El GATE A contra endpoints TLS de laboratorio (el stub de #267): mide la
  capacidad de DISTINGUIR del preflight. Contra el VISOR REAL lo ejerce
  ``test_b2_primera_release.py``.

LIMITE DECLARADO
----------------
La extraccion por marcas es textual (bash no tiene AST que usar aqui): se
exige unicidad de cada marca y se declara. Los pasos 1-2 (lock, clone, venv,
pip) y 7-16 (systemd) NO se ejecutan: necesitan red, root y systemd.
"""
from __future__ import annotations

import ast
import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import detect_state as ds  # noqa: E402
import estado_instalacion as ei  # noqa: E402
import preflight_setup_admin as ps  # noqa: E402
from preflight_https import valor_de_env_file  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
DEPLOY_SH = _SCRIPTS / "deploy.sh"
LIB_SH = _SCRIPTS / "lib.sh"
VALIDATE_SH = _SCRIPTS / "validate_deploy.sh"
PLANTILLA_PRODUCTIVA = RAIZ / "deploy" / "config" / "viewer.env.example"
PLANTILLA_VISOR = RAIZ / "viewer" / ".env.example"
ROL_COMMON = RAIZ / "deploy" / "ansible" / "roles" / "common" / "tasks" / "main.yml"
STATE_ROOT_DE_PLANTILLA = "/var/lib/s9-knowledge"
URL_DE_PLANTILLA = "https://cambiar.por.el.nombre.real"


# ---------------------------------------------------------------------------
# Bases SQLite: las del PRODUCTO cuando el producto sabe crearlas
# ---------------------------------------------------------------------------

def _auth_de_producto(path: Path, usuarios: int = 0, sello: bool = False) -> Path:
    """Base de auth creada por `app.auth.db.ensure_migrated` (la del producto)."""
    import app.auth.db as auth_db  # noqa: PLC0415 - viewer en sys.path (conftest raiz)

    path.parent.mkdir(parents=True, exist_ok=True)
    auth_db.ensure_migrated(path)
    with auth_db.get_conn(path) as con:
        for i in range(usuarios):
            # El alta del PRODUCTO (la de la CLI), que no sella: el sello lo
            # infiere el visor la primera vez que consulta.
            auth_db.create_user(con, "u%d" % i, "U%d" % i, "h" * 60, role="admin")
        if sello:
            con.execute("INSERT OR REPLACE INTO install_state (key, value, set_at) "
                        "VALUES (?, 'true', '2026-01-01T00:00:00Z')", (ds.BOOTSTRAP_KEY,))
        con.commit()
    return path


def _jobs(path: Path, n: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, status TEXT, created_at TEXT)")
    for i in range(n):
        con.execute("INSERT INTO jobs VALUES (?, 'completed', '2026-01-01')", ("j%d" % i,))
    con.commit()
    con.close()
    return path


def _corrupta(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"esto no es una base sqlite " * 8)
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "AUSENTE"


# ---------------------------------------------------------------------------
# Extraccion del texto REAL de deploy.sh entre marcas UNICAS
# ---------------------------------------------------------------------------

def _tramo_de_deploy(inicio: str, fin: str) -> str:
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    for marca in (inicio, fin):
        n = texto.count(marca)
        assert n == 1, (
            "DETECTOR ROTO: la marca %r aparece %d veces en deploy.sh; el "
            "testigo no elige una a ciegas" % (marca, n))
    a = texto.index(inicio)
    b = texto.index(fin, a) + len(fin)
    return texto[a:b]


def _correr_bash(cuerpo: str, env_extra: dict) -> subprocess.CompletedProcess:
    guion = "set -Eeuo pipefail\nsource %s\nsource %s\n%s\necho TRAMO_SUPERADO\n" % (
        LIB_SH, VALIDATE_SH, cuerpo)
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    env.update(env_extra)
    return subprocess.run(["bash", "-c", guion], capture_output=True, text=True,
                          env=env, timeout=120)


def _paso4(tmp: Path, modo: str, *, new_auth: Path, new_jobs: Path,
           legacy_auth: Path = None, legacy_jobs: Path = None):
    cuerpo = """
HERE=%(here)s
MODE=%(modo)s
LEGACY_AUTH_DB=%(la)s
LEGACY_JOBS_DB=%(lj)s
NEW_AUTH_DB=%(na)s
NEW_JOBS_DB=%(nj)s
detect_layout_report() {
    python3 "${HERE}/detect_state.py" \\
        --legacy-auth "${LEGACY_AUTH_DB}" --legacy-jobs "${LEGACY_JOBS_DB}" \\
        --new-auth "${NEW_AUTH_DB}" --new-jobs "${NEW_JOBS_DB}" --mode "${MODE}"
}
%(tramo)s
""" % {
        "here": _SCRIPTS, "modo": modo,
        "la": legacy_auth or (tmp / "legacy-no-existe" / "auth.db"),
        "lj": legacy_jobs or (tmp / "legacy-no-existe" / "jobs.db"),
        "na": new_auth, "nj": new_jobs,
        "tramo": _tramo_de_deploy("# Paso 3: detectar layout/estado",
                                  "# --- fin del paso 4 ---"),
    }
    r = _correr_bash(cuerpo, {})
    return r.returncode, r.stdout + r.stderr


# ===========================================================================
# 1. detect_state: el ESTADO DEL PRODUCTO decide fresh / upgrade
# ===========================================================================

def test_h43_una_jobs_db_vacia_es_estado_usable_no_empty(tmp_path):
    """H-43: una cola vacia es estado legitimo, no EMPTY_STATE."""
    r = ds.detect(None, None, str(_auth_de_producto(tmp_path / "a.db", usuarios=1)),
                  str(_jobs(tmp_path / "j.db", 0)), "upgrade")
    estado_jobs = r["per_kind"]["jobs"]["state"]
    assert estado_jobs == "NEW_STATE", (
        "H-43: una jobs.db existente, integra y VACIA tiene que leerse como "
        "estado usable (NEW_STATE), no como %s" % estado_jobs)
    assert r["global_state"] == "NEW_STATE", r["global_state"]
    assert r["decision"] == "PROCEED", r["reasons"]


def test_una_cola_vacia_no_compite_con_una_llena(tmp_path):
    """Legacy vacia + nueva con trabajos: manda la que tiene trabajos."""
    r = ds.detect(None, str(_jobs(tmp_path / "lj.db", 0)), None,
                  str(_jobs(tmp_path / "nj.db", 3)), "upgrade")
    assert r["per_kind"]["jobs"]["state"] == "NEW_STATE"


def test_fresh_en_maquina_limpia_procede_y_cede_el_alta(tmp_path):
    r = ds.detect(None, None, str(tmp_path / "no" / "auth.db"),
                  str(tmp_path / "no" / "jobs.db"), "fresh")
    assert r["decision"] == "PROCEED", r["reasons"]
    assert r["primer_admin_pendiente"] is True


def test_fresh_con_la_base_de_fabrica_del_producto_procede(tmp_path):
    """Estado realista: el visor arranco una vez y migro su base vacia."""
    r = ds.detect(None, None, str(_auth_de_producto(tmp_path / "a.db")),
                  str(_jobs(tmp_path / "j.db", 0)), "fresh")
    assert r["per_kind"]["auth"]["state"] == "EMPTY_STATE"
    assert r["per_kind"]["auth"]["sello"]["new"] is False
    assert r["decision"] == "PROCEED", r["reasons"]
    assert r["primer_admin_pendiente"] is True


def test_fresh_con_usuarios_bloquea(tmp_path):
    r = ds.detect(None, None, str(_auth_de_producto(tmp_path / "a.db", usuarios=1)),
                  None, "fresh")
    assert r["decision"] == "BLOCK"
    assert r["primer_admin_pendiente"] is False


def test_fresh_con_sello_y_sin_usuarios_bloquea(tmp_path):
    """El sello es irreversible: una base vaciada NO es una maquina limpia."""
    r = ds.detect(None, None, str(_auth_de_producto(tmp_path / "a.db", sello=True)),
                  None, "fresh")
    assert r["decision"] == "BLOCK", r
    assert any("sello" in m for m in r["reasons"]), r["reasons"]
    assert r["primer_admin_pendiente"] is False


@pytest.mark.parametrize("modo", ["fresh", "upgrade"])
def test_corrupta_bloquea_en_los_dos_modos(tmp_path, modo):
    r = ds.detect(None, None, str(_corrupta(tmp_path / "a.db")), None, modo)
    assert r["per_kind"]["auth"]["state"] == "CORRUPT_STATE"
    assert r["decision"] == "BLOCK"


def test_el_literal_del_sello_es_el_del_producto():
    import app.auth.db as auth_db  # noqa: PLC0415
    assert ds.BOOTSTRAP_KEY == auth_db.BOOTSTRAP_KEY


# ===========================================================================
# 2. EL PASO 4 REAL de deploy.sh
# ===========================================================================

def test_paso4_fresh_en_maquina_limpia_no_bloquea_por_la_ausencia_esperada(tmp_path):
    """H-01: auth.db y jobs.db inexistentes + --mode fresh -> sigue."""
    rc, out = _paso4(tmp_path, "fresh", new_auth=tmp_path / "s/auth/auth.db",
                     new_jobs=tmp_path / "s/jobs/jobs.db")
    assert rc == 0 and "TRAMO_SUPERADO" in out, (
        "H-01: el paso 4 de deploy.sh tiene que dejar seguir una primera "
        "release en maquina limpia; salida:\n%s" % out)
    assert "FIRST_ADMIN_PENDING" in out, out
    assert not (tmp_path / "s/auth/auth.db").exists(), (
        "el paso 4 no puede crear una auth.db: eso lo hace el visor al arrancar")


@pytest.mark.parametrize("jobs", ["ausente", "vacia"])
def test_paso4_upgrade_con_jobs_ausente_o_vacia_no_bloquea(tmp_path, jobs):
    """H-43: un host sano que nunca encolo un trabajo se puede actualizar."""
    na = _auth_de_producto(tmp_path / "s/auth/auth.db", usuarios=1)
    nj = tmp_path / "s/jobs/jobs.db"
    if jobs == "vacia":
        _jobs(nj, 0)
    rc, out = _paso4(tmp_path, "upgrade", new_auth=na, new_jobs=nj)
    assert rc == 0 and "TRAMO_SUPERADO" in out, (
        "H-43: upgrade con auth usable y jobs.db %s no debe morir en el paso "
        "4; salida:\n%s" % (jobs, out))


def test_paso4_upgrade_migra_el_layout_legacy(tmp_path):
    la = _auth_de_producto(tmp_path / "legacy/auth.db", usuarios=2)
    na = tmp_path / "s/auth/auth.db"
    rc, out = _paso4(tmp_path, "upgrade", new_auth=na,
                     new_jobs=tmp_path / "s/jobs/jobs.db", legacy_auth=la)
    assert rc == 0, out
    con = sqlite3.connect(na)
    try:
        assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    finally:
        con.close()


def test_paso4_fresh_sobre_auth_con_usuarios_bloquea_y_no_toca_nada(tmp_path):
    na = _auth_de_producto(tmp_path / "s/auth/auth.db", usuarios=1)
    antes = _hash(na)
    rc, out = _paso4(tmp_path, "fresh", new_auth=na, new_jobs=tmp_path / "s/jobs/jobs.db")
    assert rc != 0 and "TRAMO_SUPERADO" not in out, out
    assert "bloquea en fresh" in out, out
    assert _hash(na) == antes, "fresh NUNCA sobrescribe una auth.db existente"


@pytest.mark.parametrize("modo", ["fresh", "upgrade"])
def test_paso4_corrupta_bloquea(tmp_path, modo):
    na = _corrupta(tmp_path / "s/auth/auth.db")
    rc, out = _paso4(tmp_path, modo, new_auth=na, new_jobs=tmp_path / "s/jobs/jobs.db")
    assert rc != 0 and "CORRUPT_STATE" in out, out


def test_paso4_upgrade_distingue_ausencia_de_corrupcion(tmp_path):
    """Upgrade sin auth.db: BLOCK por EMPTY (ausencia), no por corrupcion."""
    rc, out = _paso4(tmp_path, "upgrade", new_auth=tmp_path / "s/auth/auth.db",
                     new_jobs=tmp_path / "s/jobs/jobs.db")
    assert rc != 0, out
    assert "auth: EMPTY_STATE bloquea en upgrade" in out, out
    assert "CORRUPT" not in out, out


def test_paso4_ya_no_decide_por_el_estado_global():
    """El texto real del paso 4 no gobierna con `global_state`."""
    tramo = _tramo_de_deploy("# Paso 4: migrar o validar estado", "# --- fin del paso 4 ---")
    assert "paso4_migrar_o_validar_estado" in tramo
    assert 'case "${GLOBAL_STATE}"' not in tramo, tramo


# ===========================================================================
# 3. EL PASO 6 REAL de deploy.sh contra la PLANTILLA PRODUCTIVA LITERAL
# ===========================================================================

def _directorios_de_ansible() -> list:
    """Subdirectorios del state root que crea el rol `common` (YAML parseado)."""
    import yaml  # noqa: PLC0415

    tareas = yaml.safe_load(ROL_COMMON.read_text(encoding="utf-8"))
    for t in tareas:
        if t.get("name") == "Crear subdirectorios de estado mutable":
            return list(t["loop"])
    raise AssertionError("DETECTOR ROTO: el rol common ya no tiene la tarea de subdirectorios")


def plantilla_productiva_en(tmp: Path, url: str, *, ca_file: str = None,
                            quitar: tuple = ()) -> tuple:
    """La plantilla LITERAL con solo el state root y la URL de este host.

    Devuelve ``(viewer_env, state_root)``. Crea los directorios que crearia el
    rol Ansible `common`, ni uno mas.
    """
    state_root = tmp / "var-lib-s9k"
    texto = PLANTILLA_PRODUCTIVA.read_text(encoding="utf-8")
    nuevo = texto.replace(STATE_ROOT_DE_PLANTILLA, str(state_root)).replace(
        "S9K_PUBLIC_BASE_URL=%s" % URL_DE_PLANTILLA, "S9K_PUBLIC_BASE_URL=%s" % url)
    if ca_file:
        nuevo = nuevo.replace("#S9K_TLS_CA_FILE=/etc/s9-knowledge/tls/ca.pem",
                              "S9K_TLS_CA_FILE=%s" % ca_file)
    lineas = [l for l in nuevo.splitlines()
              if not any(l.startswith(v + "=") for v in quitar)]
    nuevo = "\n".join(lineas) + "\n"
    distintas = [(a, b) for a, b in zip(texto.splitlines(), nuevo.splitlines()) if a != b]
    for a, _ in distintas:
        assert (STATE_ROOT_DE_PLANTILLA in a or a.startswith("S9K_PUBLIC_BASE_URL=")
                or a.startswith("#S9K_TLS_CA_FILE=") or quitar), (
            "la plantilla ejercida ya no es la literal: cambia %r" % a)
    env = tmp / "viewer.env"
    env.write_text(nuevo, encoding="utf-8")
    env.chmod(0o600)
    state_root.mkdir(parents=True, exist_ok=True)
    for sub in _directorios_de_ansible():
        (state_root / sub).mkdir(parents=True, exist_ok=True)
    return env, state_root


def _paso6(env: Path, state_root: Path, ambiente: str = "production"):
    cuerpo = """
HERE=%s
VIEWER_ENV=%s
ENVIRONMENT=%s
S9K_STATE_ROOT=%s
S9K_CONFIG_ROOT=%s
%s
""" % (_SCRIPTS, env, ambiente, state_root, env.parent,
       _tramo_de_deploy("# Paso 6: validar viewer.env", "# --- fin del paso 6 ---"))
    r = _correr_bash(cuerpo, {})
    return r.returncode, r.stdout + r.stderr


def test_paso6_acepta_la_plantilla_productiva_literal(tmp_path):
    """Sin CSRF manual, sin mock, con el estado de revision fuera de la release."""
    env, raiz = plantilla_productiva_en(tmp_path, "https://s9k.example.test")
    rc, out = _paso6(env, raiz)
    assert rc == 0 and "TRAMO_SUPERADO" in out, (
        "la plantilla productiva copiada tal cual (cambiando solo la URL) "
        "tiene que pasar el paso 6 de deploy.sh; salida:\n%s" % out)
    assert "INFO(csrf)" in out, "el CSRF ausente tiene que aceptarse NOMBRANDO la autogeneracion"
    assert "APTO" in out, out


@pytest.mark.parametrize("variable", ["S9K_V3_REVIEW_DATABASE_PATH", "S9K_V3_REVIEW_PROPOSALS_DIR"])
def test_paso6_sin_estado_de_revision_bloquea_con_la_causa(tmp_path, variable):
    """H-04 (lado deploy): sin las rutas de revision, deploy.sh BLOQUEA."""
    env, raiz = plantilla_productiva_en(tmp_path, "https://s9k.example.test",
                                        quitar=(variable,))
    rc, out = _paso6(env, raiz)
    assert rc != 0 and "TRAMO_SUPERADO" not in out, (
        "H-04: sin %s el despliegue tiene que BLOQUEAR; salida:\n%s" % (variable, out))
    assert "faltan variables críticas" in out and variable in out, (
        "el bloqueo tiene que NOMBRAR la variable que falta (%s):\n%s" % (variable, out))


def test_paso6_estado_de_revision_fuera_del_state_root_bloquea(tmp_path):
    env, raiz = plantilla_productiva_en(tmp_path, "https://s9k.example.test")
    fuera = tmp_path / "otro-sitio"
    fuera.mkdir()
    texto = env.read_text().replace(
        "S9K_V3_REVIEW_PROPOSALS_DIR=%s/reviews-v3/proposals" % raiz,
        "S9K_V3_REVIEW_PROPOSALS_DIR=%s" % fuera)
    env.write_text(texto)
    rc, out = _paso6(env, raiz)
    assert rc != 0 and "fuera del state root" in out, out


def test_paso6_csrf_explicito_debil_sigue_bloqueando(tmp_path):
    env, raiz = plantilla_productiva_en(tmp_path, "https://s9k.example.test")
    env.write_text(env.read_text() + "S9K_CSRF_SECRET=change-me\n")
    rc, out = _paso6(env, raiz)
    assert rc != 0 and "BLOCK(csrf)" in out, out


def test_paso6_csrf_ausente_con_auth_db_relativa_bloquea(tmp_path):
    env, raiz = plantilla_productiva_en(tmp_path, "https://s9k.example.test")
    env.write_text(env.read_text().replace(
        "S9K_AUTH_DB_PATH=%s/auth/auth.db" % raiz, "S9K_AUTH_DB_PATH=auth.db"))
    rc, out = _paso6(env, raiz)
    assert rc != 0 and "no puede autogenerar" in out, out


def test_paso6_http_plano_en_produccion_no_se_declara_completo(tmp_path):
    env, raiz = plantilla_productiva_en(tmp_path, "http://s9k.example.test")
    rc, out = _paso6(env, raiz)
    assert rc != 0 and "COOKIE_SECURE_SOBRE_HTTP" in out, out


# ===========================================================================
# 4. Plantillas: coherentes con #248 / #264 y con CRITICAL_ENV_VARS
# ===========================================================================

def _critical_env_vars() -> list:
    r = subprocess.run(["bash", "-c", 'source "$1"; printf "%s" "${CRITICAL_ENV_VARS}"',
                        "_", str(VALIDATE_SH)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


@pytest.mark.parametrize("plantilla", [PLANTILLA_PRODUCTIVA, PLANTILLA_VISOR],
                         ids=["deploy-viewer.env.example", "viewer-.env.example"])
def test_la_plantilla_de_fabrica_no_arranca_en_mock(plantilla):
    """H-44/D-MOCK: de fabrica, vacio honesto. Decide el clasificador del PRODUCTO."""
    from app.providers import (  # noqa: PLC0415
        PROVIDER_NOT_CONFIGURED, classify_provider_declaration)

    valor = valor_de_env_file(plantilla, "S9K_GRAPH_PROVIDER")
    clase = classify_provider_declaration(valor)
    assert clase == PROVIDER_NOT_CONFIGURED, (
        "la plantilla %s declara S9K_GRAPH_PROVIDER=%r, que el producto "
        "clasifica como %r: una instalacion de fabrica no puede servir datos "
        "de muestra como si fueran reales (D-MOCK, #264)"
        % (plantilla.relative_to(RAIZ), valor, clase))
    assert (valor or "").strip() == PROVIDER_NOT_CONFIGURED, valor


def test_critical_env_vars_incluye_el_estado_de_revision():
    criticas = _critical_env_vars()
    faltan = {"S9K_V3_REVIEW_DATABASE_PATH", "S9K_V3_REVIEW_PROPOSALS_DIR"} - set(criticas)
    assert not faltan, "H-04: CRITICAL_ENV_VARS no exige %s" % sorted(faltan)


def test_la_plantilla_productiva_declara_toda_variable_critica():
    criticas = _critical_env_vars()
    faltan = [v for v in criticas if not valor_de_env_file(PLANTILLA_PRODUCTIVA, v)]
    assert not faltan, "la plantilla productiva no declara %s" % faltan


def test_la_plantilla_productiva_no_lleva_comentarios_en_linea():
    """`VAR=valor  # nota` metia la nota en el valor (medido)."""
    malas = [l for l in PLANTILLA_PRODUCTIVA.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#") and "#" in l]
    assert not malas, malas


def test_la_plantilla_productiva_no_exige_csrf_manual():
    assert not valor_de_env_file(PLANTILLA_PRODUCTIVA, "S9K_CSRF_SECRET")
    texto = PLANTILLA_PRODUCTIVA.read_text(encoding="utf-8")
    assert "debe definirse en el host" not in texto, "contradice #248 (H-49)"


def test_ansible_crea_los_directorios_que_la_plantilla_declara():
    subdirs = set(_directorios_de_ansible())
    for var in ("S9K_V3_REVIEW_DATABASE_PATH", "S9K_V3_REVIEW_PROPOSALS_DIR",
                "S9K_AUTH_DB_PATH", "S9K_JOBS_DB"):
        ruta = Path(valor_de_env_file(PLANTILLA_PRODUCTIVA, var))
        relativo = ruta.relative_to(STATE_ROOT_DE_PLANTILLA)
        directorio = relativo if var.endswith("_DIR") else relativo.parent
        assert str(directorio) in subdirs, (
            "%s=%s: el rol common no crea %s" % (var, ruta, directorio))


# ===========================================================================
# 5. GATE A: CSRF funcional, distinguido de «la cookie Secure no vuelve»
# ===========================================================================

from test_preflight_setup_admin import _StubSetup, _certificado  # noqa: E402

_FORM_400 = ('<form method="post"><input type="hidden" name="csrf_token" '
             'value="tok-nuevo"></form><li>%s</li>' % ps.MENSAJE_VALIDACION_USUARIO_VACIO).encode()


@pytest.fixture
def cert_localhost(tmp_path):
    return _certificado(tmp_path, "localhost", "b2gatea")


def _gate_a(stub, ca):
    return ps.verificar_gate_a(ps.Entrada(
        url=stub.base_url, session_secure=True,
        credenciales=ps.Credenciales("-", ""), ca_file=str(ca), modo="gate-a",
        timeout=10.0))


def test_gate_a_pasa_solo_con_la_validacion_exacta(cert_localhost):
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, estado_post=400, cuerpo_post=_FORM_400)
    try:
        hallazgos, rec = _gate_a(stub, cert)
        assert hallazgos == [], [str(h) for h in hallazgos]
        assert rec.csrf_validacion == 400
        assert rec.cookie_secure is True
    finally:
        stub.cerrar()


@pytest.mark.parametrize("estado,causa", [
    (500, "ERROR_DE_SERVIDOR"), (502, "ERROR_DE_SERVIDOR"),
    (503, "ALMACEN_DE_AUTH_NO_DISPONIBLE"), (200, "VALIDACION_INESPERADA"),
    (303, "ALTA_INVALIDA_ACEPTADA")])
def test_gate_a_no_acepta_lo_que_no_es_la_validacion(cert_localhost, estado, causa):
    """«status != 403» NO es un CSRF funcional: un 5xx no es PASS."""
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, estado_post=estado, cuerpo_post=b"<p>x</p>")
    try:
        hallazgos, rec = _gate_a(stub, cert)
        causas = [h.causa for h in hallazgos]
        assert causa in causas, (
            "GATE A ante un POST %d tiene que fallar con %s; dio %s (un "
            "'status != 403' lo habria aceptado)" % (estado, causa, causas))
        assert ps.codigo_de_salida(hallazgos) != 0
    finally:
        stub.cerrar()


def test_gate_a_400_sin_el_mensaje_exacto_no_basta(cert_localhost):
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, estado_post=400, cuerpo_post=b"<p>otro 400</p>")
    try:
        hallazgos, _ = _gate_a(stub, cert)
        assert "VALIDACION_INESPERADA" in [h.causa for h in hallazgos]
    finally:
        stub.cerrar()


def test_gate_a_403_por_https_es_csrf_roto_no_cookie_secure(cert_localhost):
    """La cookie SI viajo (HTTPS): un 403 es un CSRF roto de verdad."""
    cert, clave = cert_localhost
    stub = _StubSetup(cert, clave, estado_post=403)
    try:
        causas = [h.causa for h in _gate_a(stub, cert)[0]]
        assert "CSRF_RECHAZADO_CON_COOKIE" in causas, causas
        assert "COOKIE_SECURE_SOBRE_HTTP" not in causas, causas
    finally:
        stub.cerrar()


def test_gate_a_http_plano_nombra_la_causa_de_preflight_https_y_no_sondea():
    hallazgos, rec = ps.verificar_gate_a(ps.Entrada(
        url="http://127.0.0.1:9", session_secure=True,
        credenciales=ps.Credenciales("-", ""), modo="gate-a"))
    causas = [h.causa for h in hallazgos]
    assert "COOKIE_SECURE_SOBRE_HTTP" in causas, causas
    assert "CSRF_RECHAZADO_CON_COOKIE" not in causas, causas
    assert rec.get_formulario is None, "no se puede sondear http:// (D3)"


def test_gate_a_no_pide_credenciales(monkeypatch, capsys):
    class _Prohibido:
        def read(self):  # pragma: no cover - si se llama, falla
            raise AssertionError("GATE A no debe leer credenciales")
    monkeypatch.setattr(sys, "stdin", _Prohibido())
    rc = ps.main(["--modo", "gate-a", "--url", "http://127.0.0.1:9",
                  "--session-secure", "true"])
    assert rc != 0
    assert "COOKIE_SECURE_SOBRE_HTTP" in capsys.readouterr().out


def _constantes_de(funcion: str, fichero: Path) -> set:
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == funcion:
            return {n.value for n in ast.walk(nodo)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    raise AssertionError("no se encontro %s en %s" % (funcion, fichero))


def test_los_literales_del_gate_a_son_los_del_producto():
    setup = RAIZ / "viewer" / "app" / "routers" / "setup.py"
    assert ps.MENSAJE_VALIDACION_USUARIO_VACIO in _constantes_de("setup_admin_submit", setup)
    from app.routers import setup as producto  # noqa: PLC0415
    for msg in (producto.MENSAJE_CSRF_SIN_COOKIE, producto.MENSAJE_CSRF_INVALIDO):
        assert msg.startswith(ps.PREFIJO_MENSAJE_CSRF)
    assert ps.PREFIJO_MENSAJE_CSRF not in ps.MENSAJE_VALIDACION_USUARIO_VACIO


def test_el_mensaje_del_setup_nombra_la_causa_y_no_culpa_a_safari():
    """H-35: la causa real (http sin cifrar + cookie Secure), sin degradar nada."""
    from app.routers import setup as producto  # noqa: PLC0415
    plantilla = (RAIZ / "viewer/app/templates/auth/setup_admin.html").read_text(encoding="utf-8")
    assert "Safari" not in plantilla
    assert "https://" in plantilla and "Secure" in plantilla
    assert "http://" in producto.MENSAJE_CSRF_SIN_COOKIE
    assert "Secure" in producto.MENSAJE_CSRF_SIN_COOKIE


# ===========================================================================
# 6. Estados: ninguno se promociona sin la evidencia de todos los anteriores
# ===========================================================================

def _ev(**kw):
    return {k: {"ok": v, "t": i} for i, (k, v) in enumerate(kw.items())}


@pytest.mark.parametrize("evidencia,esperado", [
    ({}, ei.NINGUNO),
    (_ev(deploy_ok=True), "DEPLOY_OK"),
    (_ev(deploy_ok=True, https_verificado=True), "DEPLOY_OK"),
    (_ev(deploy_ok=True, https_verificado=True, gate_a=True), "HTTPS_BOOTSTRAP_PATH_VERIFIED"),
    (_ev(deploy_ok=True, https_verificado=True, gate_a=True, setup_abierto=True), "FIRST_ADMIN_PENDING"),
    # deploy terminado SIN administrador NO es instalacion completa:
    (_ev(deploy_ok=True, https_verificado=True, gate_a=True, setup_abierto=True,
         gate_b_persistencia=True), "FIRST_ADMIN_PENDING"),
    (_ev(deploy_ok=True, https_verificado=False, gate_a=True, setup_abierto=True,
         gate_b_bootstrap=True, gate_b_persistencia=True), "DEPLOY_OK"),
    (_ev(deploy_ok=True, https_verificado=True, gate_a=True, setup_abierto=True,
         gate_b_bootstrap=True), "FIRST_ADMIN_VERIFIED"),
    (_ev(deploy_ok=True, https_verificado=True, gate_a=True, setup_abierto=True,
         gate_b_bootstrap=True, gate_b_persistencia=True), "INSTALLATION_COMPLETE"),
    (_ev(https_verificado=True, gate_a=True, setup_abierto=True,
         gate_b_bootstrap=True, gate_b_persistencia=True), ei.NINGUNO),
])
def test_ningun_estado_se_promociona_sin_toda_la_evidencia(evidencia, esperado):
    assert ei.estado_alcanzado(evidencia) == esperado


def test_la_persistencia_anterior_al_alta_no_completa_la_instalacion():
    ev = _ev(deploy_ok=True, https_verificado=True, gate_a=True, setup_abierto=True)
    ev["gate_b_persistencia"] = {"ok": True, "t": 10}
    ev["gate_b_bootstrap"] = {"ok": True, "t": 20}
    assert ei.estado_alcanzado(ev) == "FIRST_ADMIN_VERIFIED"


def test_deploy_sh_nunca_anota_evidencia_del_gate_b():
    """deploy.sh no crea administradores: su techo es FIRST_ADMIN_PENDING."""
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    assert "gate_b_" not in texto
    assert "--modo bootstrap" not in texto.replace(
        "(preflight_setup_admin.py --modo bootstrap|persistencia", "")


def test_el_registro_rechaza_evidencia_inventada(tmp_path):
    with pytest.raises(ValueError):
        ei.registrar(tmp_path / "r.json", instalado=True)


def test_fresh_reinicia_el_registro(tmp_path):
    r = tmp_path / "r.json"
    ei.registrar(r, deploy_ok=True, gate_b_bootstrap=True)
    datos = ei.registrar(r, reiniciar=True, deploy_ok=True)
    assert set(datos) == {"deploy_ok"}
