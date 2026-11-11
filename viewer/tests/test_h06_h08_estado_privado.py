# -*- coding: utf-8 -*-
"""H-06 + H-08 (USABLE-V1) — el VISOR crea su estado PRIVADO y se niega a arrancar si no lo es.

ESTADO
------
::

    CODE         PASS      auth.db REAL del producto + sidecars, lock, bak, CSRF, JSONL
    CALIBRATION  PASS      scripts/calibracion/mutaciones_h06_h08_servicio_y_estado.py
    LAB (VM112)  PENDING   usuario `s9knowledge` real, otro usuario real leyendo, systemd

QUE SE EJECUTA DE VERDAD
------------------------
SQLite real en disco, con la **umask del proceso a 022** (la peor: la que daba
`auth.db` 0644). Se crea la base con el codigo REAL del producto
(``auth_db.ensure_migrated``), se obliga a SQLite a crear ``-wal``/``-shm`` con
una conexion abierta, se fuerza una migracion para que nazca la copia
``.bak.vN`` y se generan el ``.lock`` y el secreto CSRF. TODO tiene que ser
0600. No basta ``chmod`` textual: el modo se mide en el disco.

P3 · N1 · N10 · N13 · N14 · P5 · P7 · P11
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

EUID = os.geteuid()


def _modo(p) -> int:
    return stat.S_IMODE(Path(p).stat().st_mode)


@pytest.fixture
def umask_022():
    antes = os.umask(0o022)
    yield
    os.umask(antes)


@pytest.fixture(autouse=True)
def _limpia_entorno(monkeypatch):
    for k in ("S9K_STATE_ENFORCE", "S9K_STATE_ROOT"):
        monkeypatch.delenv(k, raising=False)
    try:
        from app.auth.config import get_auth_settings
        get_auth_settings.cache_clear()
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# P3 · N1 · N14 · P11: auth.db REAL del producto y todo lo que cuelga de ella
# ---------------------------------------------------------------------------

def test_auth_db_nace_0600_en_directorio_0700_con_umask_022(tmp_path, umask_022):
    from app.auth import db as auth_db
    db = tmp_path / "estado" / "auth" / "auth.db"
    db.parent.mkdir(parents=True)
    os.chmod(db.parent, 0o755)  # el directorio lo crea quien instala; el producto no lo abre
    auth_db.ensure_migrated(db)
    assert _modo(db) == 0o600, oct(_modo(db))


def test_sidecars_wal_shm_lock_y_bak_son_0600(tmp_path, umask_022):
    """N14: el modo de los sidecars se mide con una conexion VIVA que los obliga a existir."""
    from app.auth import db as auth_db
    db = tmp_path / "auth" / "auth.db"
    db.parent.mkdir()
    auth_db.ensure_migrated(db)

    conn = auth_db._connect(db)  # WAL: crea -wal/-shm mientras la conexion vive
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS h06_probe (x)")
        conn.execute("INSERT INTO h06_probe VALUES (1)")
        conn.commit()
        sidecars = [Path(str(db) + s) for s in ("-wal", "-shm")]
        assert any(p.exists() for p in sidecars), "SQLite no creo sidecars: el test no mide nada"
        for p in sidecars:
            if p.exists():
                assert _modo(p) == 0o600, (p, oct(_modo(p)))
    finally:
        conn.close()

    # .lock y .bak.vN: se fuerza una migracion con una version anterior registrada.
    c = sqlite3.connect(str(db))
    c.execute("UPDATE schema_version SET version = ?", (auth_db.SCHEMA_VERSION - 1,))
    c.commit()
    c.close()
    auth_db.migrate(db)
    lock = db.with_suffix(".lock")
    assert lock.exists() and _modo(lock) == 0o600, oct(_modo(lock))
    baks = list(db.parent.glob("auth.bak.v*"))
    assert baks, "la migracion no dejo copia .bak: el test no mide nada"
    for b in baks:
        assert _modo(b) == 0o600, (b, oct(_modo(b)))


def test_secreto_csrf_autogenerado_es_0600(tmp_path, umask_022):
    from app.auth import csrf_bootstrap
    db = tmp_path / "auth" / "auth.db"
    db.parent.mkdir()
    secreto = csrf_bootstrap.resolve_csrf_secret("", str(db))
    assert secreto
    ruta = csrf_bootstrap.secret_file_path(str(db))
    assert _modo(ruta) == 0o600, oct(_modo(ruta))


def test_una_base_preexistente_y_vacia_no_se_reabre_con_otro_modo(tmp_path, umask_022):
    """Idempotencia (P12): ensure_migrated sobre una base ya privada no cambia su modo."""
    from app.auth import db as auth_db
    db = tmp_path / "auth.db"
    auth_db.ensure_migrated(db)
    antes = _modo(db)
    auth_db.ensure_migrated(db)
    assert _modo(db) == antes == 0o600


# ---------------------------------------------------------------------------
# P5: decisions.jsonl / audit.jsonl / glosario escribibles por la app, y privados
# ---------------------------------------------------------------------------

def test_los_jsonl_de_decisiones_auditoria_y_candidatos_nacen_0600(tmp_path, umask_022):
    from app import service_identity
    from app.services.v3_glossary_candidates import GlossaryCandidateStore

    for nombre in ("decisions.jsonl", "audit.jsonl"):
        ruta = tmp_path / "reviews-v3" / nombre
        with service_identity.open_private_append(ruta, newline="\n") as fh:
            fh.write("{}\n")
        assert _modo(ruta) == 0o600, (nombre, oct(_modo(ruta)))
    assert _modo(tmp_path / "reviews-v3") == 0o700

    almacen = GlossaryCandidateStore(tmp_path / "glossary-candidates")
    almacen.propose(
        workspace="ws", candidate_type=sorted(__import__("app.services.v3_glossary_candidates", fromlist=["TYPES"]).TYPES)[0], canonical_value="a", candidate_value="b",
        entity_type=None, resolved_entity_id=None, source_id="s", episode_id="e",
        evidence={"k": "v"}, decision_id="d", proposal_id="p")
    ficheros = [p for p in (tmp_path / "glossary-candidates").rglob("*") if p.is_file()]
    assert ficheros, "el almacen de glosario no escribio nada"
    for f in ficheros:
        assert _modo(f) == 0o600, (f, oct(_modo(f)))
    for d in [p for p in (tmp_path / "glossary-candidates").rglob("*") if p.is_dir()]:
        assert _modo(d) == 0o700, (d, oct(_modo(d)))


def test_decisions_jsonl_ya_no_cae_en_la_release_si_el_despliegue_declara_review_db(tmp_path, monkeypatch):
    """N5/N6: con la review.sqlite3 declarada bajo el state root, decisions.jsonl y
    audit.jsonl salen JUNTO a ella, no dentro de la release."""
    from app.services import v3_review

    monkeypatch.delenv("S9K_V3_REVIEW_DECISIONS_PATH", raising=False)
    monkeypatch.setenv("S9K_V3_REVIEW_DATABASE_PATH", str(tmp_path / "state" / "reviews-v3" / "review.sqlite3"))
    assert v3_review.default_decisions_path() == tmp_path / "state" / "reviews-v3" / "decisions.jsonl"
    assert v3_review.default_audit_path() == tmp_path / "state" / "reviews-v3" / "audit.jsonl"
    assert v3_review.default_glossary_root() == tmp_path / "state" / "reviews-v3" / "glossary-candidates"


def test_lo_declarado_para_decisions_manda(tmp_path, monkeypatch):
    from app.services import v3_review

    monkeypatch.setenv("S9K_V3_REVIEW_DECISIONS_PATH", str(tmp_path / "d" / "decisions.jsonl"))
    monkeypatch.setenv("S9K_V3_REVIEW_DATABASE_PATH", str(tmp_path / "otro" / "review.sqlite3"))
    assert v3_review.default_decisions_path() == tmp_path / "d" / "decisions.jsonl"


# ---------------------------------------------------------------------------
# N10: la CLI de auth NO la usa root
# ---------------------------------------------------------------------------

def test_N10_la_cli_rechaza_root_y_muestra_el_comando_canonico(monkeypatch, capsys):
    from app.cli import auth as cli

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    mensaje = cli.rechazar_si_root()
    assert mensaje is not None
    assert "runuser -u s9knowledge --" in mensaje, mensaje
    assert "auth-cli.sh" in mensaje
    monkeypatch.setattr(sys, "argv", ["auth", "status"])
    assert cli.main() == 4
    assert "RECHAZADO" in capsys.readouterr().err


@pytest.mark.skipif(EUID == 0, reason="este test mide al usuario sin privilegios")
def test_la_cli_no_rechaza_a_un_usuario_normal():
    from app.cli import auth as cli

    assert cli.rechazar_si_root() is None


def test_N10b_root_no_llega_a_crear_estado(tmp_path, monkeypatch, capsys):
    """Root pide `status`: la CLI sale con 4 ANTES de abrir la base (no crea auth.db)."""
    from app.cli import auth as cli

    db = tmp_path / "auth" / "auth.db"
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(db))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["auth", "status"])
    assert cli.main() == 4
    assert not db.exists() and not db.parent.exists()


# ---------------------------------------------------------------------------
# N17 · N1 · N8: el ARRANQUE del visor es fail-closed (la funcion real del startup)
# ---------------------------------------------------------------------------

def test_el_startup_del_visor_llama_a_la_comprobacion_antes_de_abrir_la_auth_db():
    """Por AST: el primer statement efectivo de ``_startup_auth`` es la comprobacion."""
    import ast
    from app import main as visor

    arbol = ast.parse(Path(visor.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arbol)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_startup_auth")
    cuerpo = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    primero = ast.unparse(cuerpo[0])
    assert "service_state().enforce('viewer')" in primero, primero


def test_el_visor_no_arranca_si_la_comprobacion_falla(tmp_path, monkeypatch):
    """N17: ENFORCE encendido y sin S9K_STATE_ROOT -> el startup ABORTA con el diagnostico."""
    from app import main as visor, service_identity

    monkeypatch.setenv("S9K_STATE_ENFORCE", "1")
    monkeypatch.delenv("S9K_STATE_ROOT", raising=False)
    ss = service_identity.service_state()
    with pytest.raises(ss.ServiceStateError) as exc:
        asyncio.run(visor._startup_auth())
    assert "S9K_STATE_ROOT" in str(exc.value)


@pytest.mark.skipif(EUID == 0, reason="un proceso root nunca es el usuario de servicio")
def test_N1_el_visor_no_arranca_con_auth_db_0644(tmp_path, monkeypatch):
    from app import main as visor, service_identity

    ss = service_identity.service_state()
    raiz = tmp_path / "state"
    for sub in ("auth", "jobs", "reviews-v3", "reviews-v3/proposals"):
        (raiz / sub).mkdir(parents=True)
    for d in [raiz, *raiz.rglob("*")]:
        d.chmod(0o700)
    for rel in ("auth/auth.db", "jobs/jobs.db", "reviews-v3/review.sqlite3"):
        (raiz / rel).write_bytes(b"x")
        (raiz / rel).chmod(0o600)
    (raiz / "auth" / "auth.db").chmod(0o644)
    monkeypatch.setattr(ss, "expected_ids", lambda *a, **k: (os.getuid(), os.getgid()))
    for k, v in {"S9K_STATE_ENFORCE": "1", "S9K_STATE_ROOT": str(raiz),
                 "S9K_AUTH_DB_PATH": str(raiz / "auth" / "auth.db"),
                 "S9K_JOBS_DB": str(raiz / "jobs" / "jobs.db"),
                 "S9K_V3_REVIEW_DATABASE_PATH": str(raiz / "reviews-v3" / "review.sqlite3"),
                 "S9K_V3_REVIEW_PROPOSALS_DIR": str(raiz / "reviews-v3" / "proposals")}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ss.ServiceStateError) as exc:
        asyncio.run(visor._startup_auth())
    assert "auth.db" in str(exc.value) and "modo 0644" in str(exc.value), str(exc.value)


def test_N8_el_visor_root_se_niega_a_arrancar(tmp_path, monkeypatch):
    """Viewer root por ruta alternativa: la propia comprobacion lo rechaza."""
    from app import main as visor, service_identity

    ss = service_identity.service_state()
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setenv("S9K_STATE_ENFORCE", "1")
    monkeypatch.setenv("S9K_STATE_ROOT", str(tmp_path))
    with pytest.raises(ss.ServiceStateError) as exc:
        asyncio.run(visor._startup_auth())
    assert "corre como root" in str(exc.value)


def test_sin_enforce_el_visor_arranca_como_siempre(tmp_path, monkeypatch):
    """Desarrollo/CI (techo declarado): sin S9K_STATE_ENFORCE no hay comprobacion."""
    from app import service_identity

    monkeypatch.delenv("S9K_STATE_ENFORCE", raising=False)
    assert service_identity.service_state().enforce("viewer") is False
