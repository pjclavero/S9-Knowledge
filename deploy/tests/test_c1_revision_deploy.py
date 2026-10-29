# -*- coding: utf-8 -*-
"""C1 (USABLE-V1) · H-04 + H-18 — testigo del lado DESPLIEGUE.

ESTADO
------
::

    CODE         PASS      este modulo (+ viewer/tests/test_c1_revision_runtime.py)
    CALIBRATION  PASS      scripts/calibracion/mutaciones_c1_persistencia_revision.py
    RC-E2E       PENDING   sin systemd, sin VM limpia, sin usuario de servicio real

QUE SE EJECUTA DE VERDAD
------------------------
* El PASO 6 y el PASO 13 REALES de ``deploy/scripts/deploy.sh`` (texto entre
  marcas unicas, ejecutado con ``bash`` sobre un state root temporal), con
  ``review_store.py`` y ``preflight_ensayo_rc.py`` de verdad.
* ``review_store.py`` (la AUTORIDAD de despliegue) y el preflight, sobre bases
  SQLite reales: ausente, vacia, con decisiones, corrupta, ajena, directorio.
* Un recorrido local fresh -> decision -> upgrade con DOS releases exportadas
  del arbol (``test_e2e_local_*``).

MATRIZ (identificador -> test)
------------------------------
N1  upgrade con ruta cambiada -> preflight ROJO y deploy.sh die   test_n1_*
N4  SQLite ajeno sin human_decisions -> preflight ROJO            test_n4_*
N5  --mode fresh con BD con decisiones -> BLOCK                   test_n5_*
N6  upgrade sin BD con candidata legacy con decisiones, aun autorizado -> BLOCK  test_n6_*
N7-10  VAR "", "   ", relativa, directorio                        test_n7_n10_*
N11 BD corrupta + autorizacion -> STOP sin sobrescribir           test_n11_*
N12 schema invalido + autorizacion -> STOP                        test_n12_*
N13 permisos erroneos -> diagnostico de permisos                  test_n13_*
N14 autorizacion sin ausencia real -> se ignora y se anota        test_n14_*
N15 fresh sobre ruta con directorio -> STOP                       test_n15_*
N16 upgrade con BD presente pero vacia -> VERDE                   test_n16_*
N19 ruta con '#', '?', '%' o control -> rechazo con causa, nada creado  test_n19_*
P1  fresh: la crea el deploy, preflight VERDE                     test_p1_*
P2  upgrade normal: misma ruta con decisiones -> VERDE, nada creado   test_p2_*
P3  upgrade autorizado sin BD ni candidata: crea, anota, sigue    test_p3_*

LIMITE DECLARADO
----------------
Se ejerce como el usuario que corre la prueba; ``chown`` a ``www-data`` y el
reparto real de propietarios entre visor (root, H-08) y worker NO se ejercen
(RC-E2E PENDING). La evaluacion de permisos "como el servicio" se hace por los
bits de modo (``como=``), no con un segundo usuario real.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
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

import review_store as rs  # noqa: E402
from test_b2_fresh_install import (  # noqa: E402
    RAIZ, VALIDATE_SH, _correr_bash, _paso6, _tramo_de_deploy,
    plantilla_productiva_en, release_falsa_con_unidad)

LIB_SH = _SCRIPTS / "lib.sh"
VAR = "S9K_V3_REVIEW_DATABASE_PATH"
URL = "https://s9k.example.test"

_spec = importlib.util.spec_from_file_location(
    "preflight_ensayo_rc_c1", _SCRIPTS / "preflight_ensayo_rc.py")
pf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pf
_spec.loader.exec_module(pf)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "AUSENTE"


def _arbol(raiz: Path) -> list:
    """Nombres + hash de TODO lo que cuelga de `raiz` (detecta crear/tocar)."""
    return sorted((p.relative_to(raiz).as_posix(), _sha(p) if p.is_file() else "DIR")
                  for p in raiz.rglob("*"))


def _con_decisiones(ruta: Path, n: int = 2) -> Path:
    """Almacen creado por el DESPLIEGUE y con `n` decisiones humanas dentro."""
    res = rs.preparar("fresh", str(ruta))
    assert res.rc == 0, res.lineas
    con = sqlite3.connect(ruta)
    for i in range(n):
        registro = {"decision_id": "d%d" % i, "workspace": "ws", "proposal_id": "p%d" % i,
                    "request_id": "r%d" % i, "human_decision": "APPROVE",
                    "proposal": {"proposal_id": "p%d" % i}, "timestamp": "2026-01-0%dT00:00:00Z" % (i + 1)}
        con.execute(
            "INSERT INTO human_decisions (decision_id, workspace, proposal_id, request_id, "
            "record_json, created_at) VALUES (?,?,?,?,?,?)",
            ("d%d" % i, "ws", "p%d" % i, "r%d" % i, json.dumps(registro), registro["timestamp"]))
    con.commit()
    con.close()
    return ruta


def _ajena(ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    return ruta


def _corrupta(ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"esto no es una base sqlite " * 16)
    return ruta


def _entorno(tmp_path, *, almacen=False):
    """Visor+worker productivos en tmp. Devuelve (viewer_env, state_root, db)."""
    env, raiz = plantilla_productiva_en(tmp_path, URL, almacen=almacen)
    return env, raiz, raiz / "reviews-v3" / "review.sqlite3"


def _cambiar_db(env: Path, valor: str) -> None:
    lineas = [("%s=%s" % (VAR, valor)) if l.startswith(VAR + "=") else l
              for l in env.read_text().splitlines()]
    env.write_text("\n".join(lineas) + "\n")


def _current_con(tmp_path: Path, *, con_candidata: Path = None) -> Path:
    """`${S9K_ROOT}` con `current` -> una release; opcionalmente con una BD legacy dentro."""
    s9k = tmp_path / "opt-s9k"
    release = s9k / "releases" / "previa"
    (release / "viewer" / "output" / "reviews-v3").mkdir(parents=True)
    if con_candidata is not None:
        shutil.copy(con_candidata, release / "viewer" / "output" / "reviews-v3" / "review.sqlite3")
    (s9k / "current").symlink_to(release, target_is_directory=True)
    return s9k


def _preflight(env: Path, raiz: Path, modo: str = "upgrade", *, usuario=None):
    args = ["--grupo", "despliegue", "--modo", modo, "--env-file", str(env),
            "--state-root", str(raiz)]
    if usuario is not None:
        args += ["--usuario-servicio", str(usuario)]
    r = subprocess.run([sys.executable, str(_SCRIPTS / "preflight_ensayo_rc.py"), *args],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def _linea(salida: str, ident: str) -> str:
    return next((l for l in salida.splitlines() if ident in l), "")


# ===========================================================================
# P1 — fresh: lo crea el DEPLOY, bien hecho, y el preflight lo da por VERDE
# ===========================================================================

def test_p1_fresh_el_paso_6_crea_el_almacen_con_schema_permisos_y_propietario(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    assert not db.exists()
    rc, out = _paso6(env, raiz, modo="fresh")
    assert rc == 0 and "TRAMO_SUPERADO" in out, "P1 FRESH NO PASO\n" + out
    assert db.is_file(), "P1 FRESH NO CREO: el DESPLIEGUE tenia que crear review.sqlite3\n" + out
    assert "CREADO" in out and "VERIFICADO" in out, "P1 SIN VERIFICAR POR EFECTO\n" + out
    # schema
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"human_decisions", "decision_audit", "sealed_plans", "glossary_outbox"} <= tablas
    # permisos y propietario
    st = db.stat()
    assert (st.st_mode & 0o777) == 0o660, oct(st.st_mode)
    assert st.st_uid == os.getuid()
    # preflight VERDE por efecto, en los dos modos (ya existe)
    for modo in ("fresh", "upgrade"):
        rc, out = _preflight(env, raiz, modo)
        assert rc == 0, "P1 PREFLIGHT NO VERDE\n" + out
        assert _linea(out, "review_db.existente").startswith("VERDE"), "P1 PREFLIGHT NO VERDE\n" + out


def test_p1_fresh_es_idempotente_y_no_toca_una_base_vacia_valida(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    assert _paso6(env, raiz, modo="fresh")[0] == 0
    antes = _sha(db)
    rc, out = _paso6(env, raiz, modo="fresh")
    assert rc == 0 and "PRESERVA" in out, "P1 FRESH NO PRESERVO LA VALIDA\n" + out
    assert _sha(db) == antes


def test_p1_fresh_crea_tambien_el_directorio_con_su_modo(tmp_path):
    db = tmp_path / "estado" / "reviews-v3" / "review.sqlite3"
    res = rs.preparar("fresh", str(db))
    assert res.rc == 0, res.lineas
    assert (db.parent.stat().st_mode & 0o777) == 0o750


# ===========================================================================
# P2 — upgrade normal: misma ruta, con decisiones -> VERDE, NADA se crea
# ===========================================================================

def test_p2_upgrade_normal_con_decisiones_es_verde_y_no_crea_ni_toca_nada(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    _con_decisiones(db, 3)
    antes = _arbol(raiz)
    rc, out = _paso6(env, raiz, modo="upgrade")
    assert rc == 0 and "TRAMO_SUPERADO" in out, "P2 UPGRADE NO PASO\n" + out
    assert "PRESERVA" in out, "P2 UPGRADE NO PRESERVO\n" + out
    assert _arbol(raiz) == antes, "P2 EL UPGRADE TOCO FICHEROS: no puede crear, mover ni modificar"
    rc, out = _preflight(env, raiz, "upgrade")
    assert rc == 0 and "3 decision(es)" in out, "P2 PREFLIGHT NO VERDE\n" + out


# ===========================================================================
# P3 — upgrade AUTORIZADO sin BD ni candidata: crea, anota, sigue
# ===========================================================================

def test_p3_upgrade_autorizado_sin_bd_ni_candidata_crea_anota_y_sigue(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    assert not db.exists()
    rc, out = _paso6(env, raiz, modo="upgrade", autorizar=1)
    assert rc == 0 and "TRAMO_SUPERADO" in out, "P3 NO SIGUIO\n" + out
    assert db.is_file(), "P3 NO CREO\n" + out
    assert "ANOTACION" in out and "--autorizar-creacion-review-db" in out, (
        "P3 SIN ANOTAR: la excepcion tiene que quedar ANOTADA en el log del despliegue\n" + out)
    assert "VERIFICADO" in out, "P3 SIN VERIFICAR\n" + out


def test_upgrade_sin_bd_y_sin_autorizacion_es_stop_por_defecto(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    rc, out = _paso6(env, raiz, modo="upgrade")
    assert rc != 0 and "TRAMO_SUPERADO" not in out, "UPGRADE SIN BD NO PARO\n" + out
    assert "UPGRADE sin almacen" in out, "UPGRADE SIN BD SIN CAUSA\n" + out
    assert not db.exists(), "UPGRADE SIN BD CREO UNA"


# ===========================================================================
# N1 — upgrade con ruta cambiada: preflight ROJO y deploy.sh die
# ===========================================================================

def test_n1_upgrade_con_la_ruta_cambiada_preflight_rojo_y_deploy_die(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    _con_decisiones(db, 2)                                       # el estado REAL, en la ruta vieja
    nueva = raiz / "reviews-v3-nuevo" / "review.sqlite3"         # bajo el state root: antes daba «APTO»
    nueva.parent.mkdir()
    _cambiar_db(env, str(nueva))
    # El worker.env de la plantilla seguiria con la ruta vieja: se alinea para
    # aislar la causa (la ruta cambiada), no la divergencia visor/worker.
    worker = env.parent / "worker.env"
    worker.write_text(worker.read_text().replace(str(db), str(nueva)))

    rc, out = _preflight(env, raiz, "upgrade")
    assert rc == 2, "N1 PREFLIGHT NO ROJO (rc=%d)\n%s" % (rc, out)
    assert _linea(out, "review_db.existente").startswith("ROJO"), "N1 PREFLIGHT NO ROJO\n" + out
    assert "NO EXISTE" in _linea(out, "review_db.existente"), "N1 SIN CAUSA\n" + out

    rc, out = _paso6(env, raiz, modo="upgrade")
    assert rc != 0 and "TRAMO_SUPERADO" not in out, "N1 DEPLOY NO DIE\n" + out
    assert "STOP" in out and "UPGRADE sin almacen" in out, "N1 SIN STOP\n" + out
    assert not nueva.exists(), "ni siquiera ante la ruta cambiada se crea una BD vacia"
    assert db.exists() and rs.preparar("upgrade", str(db), solo_lectura=True).rc == 0


# ===========================================================================
# N4 — un SQLite ajeno sin human_decisions
# ===========================================================================

def test_n4_sqlite_ajeno_preflight_rojo_deploy_bloquea_y_no_se_toca(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    _ajena(db)
    antes = _sha(db)
    rc, out = _preflight(env, raiz, "upgrade")
    assert rc == 2 and "SCHEMA_INVALIDO" in _linea(out, "review_db.existente"), (
        "N4 PREFLIGHT NO ROJO (rc=%d)\n%s" % (rc, out))
    for modo in ("upgrade", "fresh"):
        rc, out = _paso6(env, raiz, modo=modo, autorizar=1)
        assert rc != 0 and "TRAMO_SUPERADO" not in out, "N4 DEPLOY NO BLOQUEO %s\n%s" % (modo, out)
        assert "SCHEMA_INVALIDO" in out, "N4 SIN CAUSA\n" + out
    assert _sha(db) == antes, "N4 SE TOCO: no se adopta, no se repara, no se toca"


# ===========================================================================
# N5 — fresh con una BD con decisiones
# ===========================================================================

def test_n5_fresh_con_bd_con_decisiones_bloquea(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    _con_decisiones(db, 2)
    antes = _sha(db)
    rc, out = _paso6(env, raiz, modo="fresh")
    assert rc != 0 and "TRAMO_SUPERADO" not in out, "N5 NO BLOQUEO\n" + out
    assert "BLOQUEO" in out and "--mode fresh" in out and "decision(es)" in out, "N5 SIN CAUSA\n" + out
    assert _sha(db) == antes, "N5 SE TOCO"
    # y tambien directamente por la herramienta, con accion BLOQUEO (no STOP)
    res = rs.preparar("fresh", str(db))
    assert res.rc == 3 and res.accion == "BLOQUEO", "N5 NO BLOQUEO %r" % ((res.rc, res.accion, res.lineas),)


# ===========================================================================
# N6 — upgrade sin BD con candidata legacy con decisiones: BLOCK aun autorizado
# ===========================================================================

@pytest.mark.parametrize("donde", ["release_previa", "legacy_root"])
@pytest.mark.parametrize("autorizar", [0, 1])
def test_n6_candidata_legacy_con_decisiones_bloquea_aun_autorizado(tmp_path, donde, autorizar):
    env, raiz, db = _entorno(tmp_path)
    legacy_db = _con_decisiones(tmp_path / "origen" / "review.sqlite3", 4)
    if donde == "release_previa":
        s9k = _current_con(tmp_path, con_candidata=legacy_db)
        legacy_root = None
    else:
        s9k = _current_con(tmp_path)
        legacy_root = tmp_path / "legacy-root"
        (legacy_root / "viewer" / "output" / "reviews-v3").mkdir(parents=True)
        shutil.copy(legacy_db, legacy_root / "viewer" / "output" / "reviews-v3" / "review.sqlite3")
    rc, out = _paso6(env, raiz, modo="upgrade", autorizar=autorizar, actual=s9k,
                     legacy_root=legacy_root)
    assert rc != 0 and "TRAMO_SUPERADO" not in out, "N6 NO BLOQUEO\n" + out
    assert "legacy" in out and "4 decision(es)" in out, "N6 SIN CAUSA\n" + out
    assert not db.exists(), "N6 CREO UNA BD VACIA: con candidata con decisiones NO se crea"


def test_n6_legacy_ambiguo_tampoco_se_decide_a_ciegas(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    corrupta = _corrupta(tmp_path / "origen" / "review.sqlite3")
    s9k = _current_con(tmp_path, con_candidata=corrupta)
    rc, out = _paso6(env, raiz, modo="upgrade", autorizar=1, actual=s9k)
    assert rc != 0 and "ambiguo" in out, "N6 AMBIGUO NO BLOQUEO\n" + out
    assert not db.exists(), "N6 AMBIGUO CREO UNA BD"


def test_n6_candidata_legacy_vacia_no_impide_la_creacion_autorizada(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    vacia = rs.preparar("fresh", str(tmp_path / "origen" / "review.sqlite3"))
    assert vacia.rc == 0
    s9k = _current_con(tmp_path, con_candidata=tmp_path / "origen" / "review.sqlite3")
    rc, out = _paso6(env, raiz, modo="upgrade", autorizar=1, actual=s9k)
    assert rc == 0 and db.is_file(), "N6 VACIA IMPIDIO LA CREACION AUTORIZADA\n" + out


# ===========================================================================
# N7-N10 — variable declarada pero inservible
# ===========================================================================

_INVALIDAS = [
    ('""', "VACIA", "VAR_VACIA"),                               # N7
    ('"   "', "VACIA", "VAR_VACIA"),                            # N8
    ("relativa/review.sqlite3", "RELATIVA", "VAR_RELATIVA"),    # N9
    ("@DIR@", "DIRECTORIO", "NO_ES_FICHERO"),                   # N10
]


@pytest.mark.parametrize("valor, palabra, causa", _INVALIDAS,
                         ids=["N7-vacia", "N8-espacios", "N9-relativa", "N10-directorio"])
def test_n7_n10_validate_viewer_env_rechaza_con_la_causa(tmp_path, valor, palabra, causa):
    env, raiz, db = _entorno(tmp_path)
    if valor == "@DIR@":
        db.parent.mkdir(parents=True, exist_ok=True)
        valor = str(db.parent)
    _cambiar_db(env, valor)
    r = subprocess.run(["bash", "-c", 'source "$1"; validate_viewer_env "$2"', "_",
                        str(VALIDATE_SH), str(env)], capture_output=True, text=True)
    assert r.returncode != 0, "N7-10 VALIDATE NO RECHAZO\n" + r.stdout + r.stderr
    assert "BLOCK(review)" in r.stderr and palabra in r.stderr, "N7-10 SIN CAUSA\n" + r.stderr


@pytest.mark.parametrize("valor, palabra, causa", _INVALIDAS,
                         ids=["N7-vacia", "N8-espacios", "N9-relativa", "N10-directorio"])
def test_n7_n10_el_paso_6_y_el_preflight_tambien_lo_rechazan(tmp_path, valor, palabra, causa):
    env, raiz, db = _entorno(tmp_path, almacen=True)
    if valor == "@DIR@":
        valor = str(db.parent)
    _cambiar_db(env, valor)
    rc, out = _paso6(env, raiz, modo="upgrade")
    assert rc != 0 and "TRAMO_SUPERADO" not in out, "N7-10 PASO 6 NO RECHAZO\n" + out
    # el preflight, solo (lee el env-file como el despliegue)
    rc, out = _preflight(env, raiz, "upgrade")
    assert rc == 2, "N7-10 PREFLIGHT NO ROJO\n" + out
    assert causa in _linea(out, "review_db.compartida"), "N7-10 SIN CAUSA\n" + out


@pytest.mark.parametrize("valor, palabra, causa", _INVALIDAS,
                         ids=["N7-vacia", "N8-espacios", "N9-relativa", "N10-directorio"])
def test_n7_n10_la_herramienta_de_despliegue_nombra_la_causa(tmp_path, valor, palabra, causa):
    if valor == "@DIR@":
        valor = str(tmp_path)
    for modo in ("fresh", "upgrade"):
        res = rs.preparar(modo, valor.strip('"'), autorizar=True)
        assert res.rc == 3 and causa in " ".join(res.lineas), (
            "N7-10 HERRAMIENTA SIN CAUSA %s %r" % (modo, res.lineas))


# ===========================================================================
# N19 — caracteres que SQLite interpreta en una URI: rechazo en DESPLIEGUE
# ===========================================================================
# P1-2 de la revision independiente: con `#` o `?` en la ruta, la URI `file:`
# construida a mano se cortaba, `mode=` se perdia y el runtime CREABA otro
# fichero (p. ej. `al` para `al#moh/review.sqlite3`) del que leia cero
# decisiones, mientras el despliegue lo daba por bueno. La frontera fail-closed
# es la DECLARACION: deploy y runtime la rechazan con su causa.

_N19 = [
    ("al#moh", "N19-almohadilla"),
    ("al?moh", "N19-interrogacion"),
    ("al%moh", "N19-porcentaje"),
    ("al\tmoh", "N19-control"),
]


def _ruta_n19(tmp_path: Path, trozo: str) -> Path:
    return tmp_path / "estado-n19" / trozo / "review.sqlite3"


@pytest.mark.parametrize("trozo", [t for t, _ in _N19], ids=[i for _, i in _N19])
def test_n19_validate_viewer_env_rechaza_caracteres_de_uri(tmp_path, trozo):
    env, raiz, db = _entorno(tmp_path)
    _cambiar_db(env, str(_ruta_n19(tmp_path, trozo)))
    r = subprocess.run(["bash", "-c", 'source "$1"; validate_viewer_env "$2"', "_",
                        str(VALIDATE_SH), str(env)], capture_output=True, text=True)
    assert r.returncode != 0, "N19 VALIDATE NO RECHAZO\n" + r.stdout + r.stderr
    assert "BLOCK(review)" in r.stderr and "caracter no permitido" in r.stderr, (
        "N19 VALIDATE SIN CAUSA\n" + r.stderr)
    assert not (tmp_path / "estado-n19").exists(), "N19: validar no crea nada"


@pytest.mark.parametrize("trozo", [t for t, _ in _N19], ids=[i for _, i in _N19])
def test_n19_la_herramienta_y_el_preflight_rechazan_y_no_crean_nada(tmp_path, trozo):
    ruta = _ruta_n19(tmp_path, trozo)
    ruta.parent.mkdir(parents=True)
    antes = _arbol(tmp_path / "estado-n19")
    for modo in ("fresh", "upgrade"):
        res = rs.preparar(modo, str(ruta), autorizar=True)
        assert res.rc == 3 and "CARACTER_NO_PERMITIDO" in " ".join(res.lineas), (
            "N19 HERRAMIENTA NO RECHAZO %s %r" % (modo, res.lineas))
    assert _arbol(tmp_path / "estado-n19") == antes, "N19 LA HERRAMIENTA CREO ALGO"
    env, raiz, _ = _entorno(tmp_path, almacen=True)
    _cambiar_db(env, str(ruta))
    rc, out = _preflight(env, raiz, "upgrade")
    assert rc == 2 and "CARACTER_NO_PERMITIDO" in _linea(out, "review_db.compartida"), (
        "N19 PREFLIGHT NO ROJO\n" + out)
    assert _arbol(tmp_path / "estado-n19") == antes, "N19 EL PREFLIGHT CREO ALGO"


def test_n19_inspeccion_con_ruta_de_uri_lee_el_almacen_real_y_no_crea_otro(tmp_path):
    """Defensa en profundidad: aunque una ruta asi llegase a `inspect_review_db`
    (costura, no declaracion), la URI escapada lee ESE fichero y no crea nada."""
    base = tmp_path / "estado-n19"
    ruta = base / "al#moh" / "review.sqlite3"
    ruta.parent.mkdir(parents=True)
    rs._store_del_visor().SQLiteReviewStore(ruta, crear=True)
    con = sqlite3.connect(ruta)
    con.execute("INSERT INTO human_decisions (decision_id, workspace, proposal_id, "
                "request_id, record_json, created_at) VALUES ('d1','ws','p1','r1','{}','t')")
    con.commit()
    con.close()
    antes = _arbol(base)
    ins = rs._review_paths().inspect_review_db(ruta)
    assert ins.valido and ins.decisiones == 1, "N19 INSPECCION NO VE EL REAL: %r" % (ins,)
    assert _arbol(base) == antes, "N19 FICHERO EXTRA: %r" % (_arbol(base),)


# ===========================================================================
# N11 / N12 — corrupta o schema invalido, CON autorizacion: STOP sin tocar
# ===========================================================================

@pytest.mark.parametrize("modo", ["upgrade", "fresh"])
def test_n11_bd_corrupta_con_autorizacion_stop_sin_sobrescribir(tmp_path, modo):
    env, raiz, db = _entorno(tmp_path)
    _corrupta(db)
    antes = _sha(db)
    rc, out = _paso6(env, raiz, modo=modo, autorizar=1)
    assert rc != 0 and "TRAMO_SUPERADO" not in out, "N11 NO PARO\n" + out
    assert "CORRUPTA" in out and "NO se sobrescribe" in out, "N11 NO SE SOBRESCRIBE FALTA\n" + out
    assert _sha(db) == antes, "N11 SOBRESCRIBIO: la autorizacion NO es un --force"


@pytest.mark.parametrize("modo", ["upgrade", "fresh"])
def test_n12_schema_invalido_con_autorizacion_stop(tmp_path, modo):
    env, raiz, db = _entorno(tmp_path)
    _ajena(db)
    antes = _sha(db)
    res = rs.preparar(modo, str(db), autorizar=True)
    assert res.rc == 3 and "SCHEMA_INVALIDO" in " ".join(res.lineas), "N12 NO PARO %r" % (res.lineas,)
    assert _sha(db) == antes, "N12 SE TOCO"
    # tambien una 'human_decisions' con las columnas equivocadas
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE human_decisions (decision_id TEXT)")
    con.commit()
    con.close()
    antes = _sha(db)
    res = rs.preparar(modo, str(db), autorizar=True)
    assert res.rc == 3 and "SCHEMA_INVALIDO" in " ".join(res.lineas), "N12 NO PARO (columnas) %r" % (res.lineas,)
    assert _sha(db) == antes, "N12 SE TOCO (columnas)"


# ===========================================================================
# N13 — permisos erroneos: diagnostico de PERMISOS, no «no existe»
# ===========================================================================

def test_n13_no_escribible_por_el_servicio_es_permisos_y_no_no_existe(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    _con_decisiones(db, 1)
    db.chmod(0o600)                       # solo el propietario (este proceso)
    otro = os.getuid() + 4242              # el «usuario del servicio»: ni dueño ni grupo
    # preflight
    rc, out = _preflight(env, raiz, "upgrade", usuario=otro)
    assert rc == 2, "N13 PREFLIGHT NO ROJO\n" + out
    fila = _linea(out, "review_db.existente")
    assert "SIN_PERMISOS" in fila and "NO EXISTE" not in fila, "N13 CAUSA EQUIVOCADA: " + fila
    # verificacion del paso 13
    res = rs.verificar(str(db), usuario=str(otro))
    assert res.rc == 3 and "SIN_PERMISOS" in " ".join(res.lineas), "N13 VERIFICAR SIN PERMISOS %r" % (res.lineas,)
    assert "NO_EXISTE" not in " ".join(res.lineas), "N13 CAUSA EQUIVOCADA"
    # y legible pero no escribible tambien se distingue
    db.chmod(0o640)
    res = rs.verificar(str(db), usuario=str(otro))
    assert res.rc == 3, "N13 LEGIBLE PERO NO ESCRIBIBLE PASO %r" % (res.lineas,)


def test_n13_con_permisos_correctos_el_mismo_usuario_pasa(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    _con_decisiones(db, 1)
    res = rs.verificar(str(db), usuario=str(os.getuid()))
    assert res.rc == 0, res.lineas
    rc, out = _preflight(env, raiz, "upgrade", usuario=os.getuid())
    assert rc == 0, out


# ===========================================================================
# N14 — autorizacion sin ausencia real: se ignora y se anota
# ===========================================================================

def test_n14_autorizacion_con_la_bd_presente_se_ignora_y_se_anota(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    _con_decisiones(db, 2)
    antes = _arbol(raiz)
    rc, out = _paso6(env, raiz, modo="upgrade", autorizar=1)
    assert rc == 0 and "TRAMO_SUPERADO" in out, "N14 NO PASO\n" + out
    assert "IGNORADA" in out and "ANOTACION" in out, "N14 IGNORADA SIN ANOTAR\n" + out
    assert _arbol(raiz) == antes, "N14 SE TOCO: la autorizacion no reescribe una BD presente"


# ===========================================================================
# N15 — fresh sobre una ruta que es un directorio
# ===========================================================================

def test_n15_fresh_sobre_ruta_con_directorio_stop(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    db.mkdir(parents=True)                                  # la ruta declarada ES un directorio
    rc, out = _paso6(env, raiz, modo="fresh")
    assert rc != 0 and "TRAMO_SUPERADO" not in out, "N15 NO PARO\n" + out
    assert "NO_ES_FICHERO" in out or "DIRECTORIO" in out, "N15 SIN CAUSA\n" + out
    assert db.is_dir() and not any(db.iterdir()), "no se crea nada dentro ni se sustituye"


# ===========================================================================
# N16 — upgrade con la BD presente pero VACIA: VERDE (vacia != ausente)
# ===========================================================================

def test_n16_upgrade_con_bd_vacia_valida_es_verde(tmp_path):
    env, raiz, db = _entorno(tmp_path, almacen=True)      # schema correcto, 0 filas
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM human_decisions").fetchone()[0] == 0
    con.close()
    antes = _arbol(raiz)
    rc, out = _paso6(env, raiz, modo="upgrade")
    assert rc == 0 and "TRAMO_SUPERADO" in out, "N16 VACIA NO ES VERDE\n" + out
    assert _arbol(raiz) == antes, "N16 SE TOCO"
    rc, out = _preflight(env, raiz, "upgrade")
    assert rc == 0 and _linea(out, "review_db.existente").startswith("VERDE"), "N16 PREFLIGHT NO VERDE\n" + out


# ===========================================================================
# Preflight: modo upgrade (estricto) vs fresh (admite AUSENTE)
# ===========================================================================

def test_preflight_upgrade_exige_existencia_y_fresh_la_admite(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    assert not db.exists()
    rc, out = _preflight(env, raiz, "upgrade")
    assert rc == 2 and _linea(out, "review_db.existente").startswith("ROJO"), (
        "PREFLIGHT upgrade NO ROJO SIN ALMACEN (rc=%d)\n%s" % (rc, out))
    rc, out = _preflight(env, raiz, "fresh")
    assert rc == 0 and _linea(out, "review_db.existente").startswith("VERDE"), (
        "PREFLIGHT fresh NO ADMITE LA AUSENCIA\n" + out)
    # y fresh NO admite lo que existe y no vale
    _corrupta(db)
    rc, out = _preflight(env, raiz, "fresh")
    assert rc == 2 and "CORRUPTA" in _linea(out, "review_db.existente"), (
        "PREFLIGHT fresh ADMITE UNA CORRUPTA\n" + out)


def test_preflight_el_modo_por_defecto_es_el_estricto(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    r = subprocess.run([sys.executable, str(_SCRIPTS / "preflight_ensayo_rc.py"),
                        "--grupo", "despliegue", "--env-file", str(env),
                        "--state-root", str(raiz)], capture_output=True, text=True)
    assert r.returncode == 2, "PREFLIGHT MODO POR DEFECTO NO ESTRICTO\n" + r.stdout + r.stderr


# ===========================================================================
# Paso 13 / worker: preparar_estado_del_worker deja la revision legible/WAL
# ===========================================================================

def test_preparar_estado_del_worker_prepara_tambien_el_almacen_de_revision(tmp_path):
    jobs = tmp_path / "estado" / "jobs" / "jobs.db"
    props = tmp_path / "estado" / "reviews-v3" / "proposals"
    review = tmp_path / "estado" / "reviews-v3" / "review.sqlite3"
    for f in (jobs, Path(str(review)), Path(str(review) + "-wal"), Path(str(review) + "-shm")):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("", encoding="utf-8")
    log = tmp_path / "llamadas.log"
    cuerpo = """
install() { echo "install $*" >> %(log)s; }
chown() { echo "chown $*" >> %(log)s; }
preparar_estado_del_worker usr grp %(jobs)s %(props)s %(review)s
""" % {"log": log, "jobs": jobs, "props": props, "review": review}
    guion = "set -Eeuo pipefail\nsource %s\n%s\n" % (LIB_SH, cuerpo)
    r = subprocess.run(["bash", "-c", guion], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    llamadas = log.read_text(encoding="utf-8")
    assert "install -d -m 0750 -o usr -g grp %s\n" % review.parent in llamadas, (
        "N17 SIN INSTALL DE LA REVISION: " + llamadas)
    for f in (review, Path(str(review) + "-wal"), Path(str(review) + "-shm")):
        assert "chown usr:grp -- %s\n" % f in llamadas, "N17 SIN CHOWN DE LA REVISION: %s\n%s" % (f, llamadas)


def test_preparar_estado_del_worker_exige_la_ruta_de_revision(tmp_path):
    guion = "set -Eeuo pipefail\nsource %s\npreparar_estado_del_worker u g /a/jobs.db /a/props\n" % LIB_SH
    r = subprocess.run(["bash", "-c", guion], capture_output=True, text=True)
    assert r.returncode != 0 and "review.sqlite3" in r.stderr, r.stderr


# ===========================================================================
# deploy.sh: el cableado (texto REAL)
# ===========================================================================

def test_deploy_sh_declara_la_excepcion_y_prepara_antes_del_preflight():
    texto = (_SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
    assert "--autorizar-creacion-review-db)" in texto
    paso6 = _tramo_de_deploy("# Paso 6: validar viewer.env", "# --- fin del paso 6 ---")
    i_prep = paso6.index("review_store.py\" preparar")
    i_pref = paso6.index("preflight_ensayo_rc.py\" --grupo despliegue")
    assert i_prep < i_pref, "el despliegue PREPARA el almacen antes de pedirle al preflight que lo vea"
    assert 'preparar --modo "${MODE}"' in paso6, (
        "MODO: deploy.sh no pasa su modo a review_store.py (fresh y upgrade no son lo mismo)")
    assert '--modo "${MODE}"' in paso6
    paso13 = _tramo_de_deploy("# Paso 13: reiniciar solo servicios afectados", "# --- fin del paso 13 ---")
    assert "review_store.py\" verificar" in paso13


def test_el_grupo_despliegue_exige_la_existencia_del_almacen():
    """El preflight que corre `deploy.sh` incluye la comprobacion de EXISTENCIA (N1)."""
    nombres = {n for n, _ in pf.GRUPOS["despliegue"]}
    assert "review_db.existente" in nombres, (
        "EXISTENCIA PERDIDA: el grupo de despliegue ya no comprueba que el almacen exista")
    assert "review_db.existente" in pf.GRUPO_DESPLIEGUE, "EXISTENCIA PERDIDA (nombres)"


def test_dry_run_no_crea_el_almacen(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    res = rs.preparar("fresh", str(db), solo_lectura=True)
    assert res.rc == 0 and res.accion == "PLAN_CREAR" and not db.exists()
    res = rs.preparar("upgrade", str(db), solo_lectura=True)
    assert res.rc == 3 and not db.exists()


def test_las_plantillas_declaran_la_misma_ruta_bajo_el_state_root():
    from preflight_https import valor_de_env_file  # noqa: PLC0415

    visor = valor_de_env_file(RAIZ / "deploy" / "config" / "viewer.env.example", VAR)
    worker = valor_de_env_file(RAIZ / "deploy" / "config" / "worker.env.example", VAR)
    assert visor == worker and visor.startswith("/var/lib/s9-knowledge/"), (visor, worker)


# ===========================================================================
# E2E LOCAL — fresh -> decision -> upgrade, con DOS releases exportadas del arbol
# ===========================================================================

def _exportar_release(destino: Path) -> Path:
    """Una release = los ficheros del arbol (trackeados + nuevos, sin ignorados)."""
    r = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "--", "data-engine", "viewer/app",
         "viewer/systemd", "deploy/scripts", "shared", "contracts"],
        cwd=RAIZ, capture_output=True, text=True, check=True)
    for rel in r.stdout.splitlines():
        if "/tests/" in rel or not (RAIZ / rel).is_file():
            continue
        (destino / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RAIZ / rel, destino / rel)
    return destino


_GUION_RELEASE = r"""
import json, sys
rel, accion = sys.argv[1], sys.argv[2]
sys.path[:0] = [rel + "/data-engine/app"]
sys.path.append(rel + "/viewer")
from knowledge_v3 import review_decisions, review_paths
out = {"canonica": str(review_paths.default_review_db())}
if accion == "decidir":
    from app.services.v3_review import ReviewService
    from pathlib import Path
    store = ReviewService(Path(sys.argv[3]) / "p", Path(sys.argv[3]) / "d.jsonl").store
    registro = {"decision_id": "human:e2e", "workspace": "ws-e2e", "proposal_id": "prop-e2e",
                "request_id": "req-e2e", "human_decision": "APPROVE", "reviewer": "ana",
                "proposal": {"proposal_id": "prop-e2e"}, "timestamp": "2026-10-27T10:00:00Z"}
    store.append_decision_and_outbox(registro, None)
    out["escrita"] = True
else:
    from app.services.v3_review import ReviewService
    from pathlib import Path
    visor = [d["decision_id"] for d in ReviewService(Path(sys.argv[3]) / "p", Path(sys.argv[3]) / "d.jsonl").store.decisions()]
    motor = sorted(k for k in review_decisions.read_active_decisions(workspace="ws-e2e"))
    out.update({"visor": visor, "motor": motor})
print(json.dumps(out))
"""


def _en_release(release: Path, env_extra: dict, accion: str, trabajo: Path) -> dict:
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    entorno.update(env_extra)
    entorno["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, "-I", "-c", _GUION_RELEASE, str(release), accion, str(trabajo)],
                       capture_output=True, text=True, env=entorno, cwd=release / "viewer")
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_e2e_local_fresh_decision_upgrade_con_dos_releases(tmp_path):
    env, raiz, db = _entorno(tmp_path)
    release_a = _exportar_release(tmp_path / "releases" / "A")
    release_b = _exportar_release(tmp_path / "releases" / "B")
    assert release_a != release_b and (release_a / "deploy" / "scripts" / "review_store.py").is_file()
    trabajo = tmp_path / "trabajo"
    (trabajo / "p").mkdir(parents=True)
    runtime = {VAR: str(db)}

    # 1. FRESH: el paso 6 REAL de deploy.sh crea el almacen (release A).
    assert not db.exists()
    rc, out = _paso6(env, raiz, modo="fresh")
    assert rc == 0 and db.is_file(), out
    # 2. El runtime de la release A lo CONSUME y toma una decision humana.
    escrito = _en_release(release_a, runtime, "decidir", trabajo)
    assert escrito["escrita"] and escrito["canonica"] == str(db)
    tras_fresh = _sha(db)
    # 3. UPGRADE a la release B: mismo paso 6 REAL en modo upgrade; no crea ni toca.
    antes = _arbol(raiz)
    rc, out = _paso6(env, raiz, modo="upgrade")
    assert rc == 0 and "PRESERVA" in out, out
    assert _arbol(raiz) == antes and _sha(db) == tras_fresh
    # 4. La release B (otro arbol de codigo) ve LA MISMA decision, visor y motor.
    vista = _en_release(release_b, runtime, "leer", trabajo)
    assert vista["canonica"] == str(db)
    assert vista["visor"] == ["human:e2e"] and vista["motor"] == ["prop-e2e"], vista
    # 5. Y un upgrade que cambia la ruta NO pasa en silencio (N1 en el recorrido).
    nueva = raiz / "otro-sitio" / "review.sqlite3"
    _cambiar_db(env, str(nueva))
    worker = env.parent / "worker.env"
    worker.write_text(worker.read_text().replace(str(db), str(nueva)))
    rc, out = _paso6(env, raiz, modo="upgrade")
    assert rc != 0 and not nueva.exists(), out
