# -*- coding: utf-8 -*-
"""
Laboratorio de continuidad de estado (corrección RC1) — 25 escenarios.

Usa fixtures SQLite equivalentes al esquema real (auth: schema_version/users con
role+is_active; jobs: tabla jobs). NUNCA toca producción. Ejecutable en CI.

Cobertura (TAREA 3):
  1 LEGACY_STATE - 2 migración auth - 3 migración jobs - 4 integridad -
  5 conserva usuario - 6 conserva admin - 7 conserva job - 8 legacy usa estado
  externo/bridge - 9 unidad basada en current - 10 activación de release -
  11 commit ejecutado - 12 idempotencia - 13 mixed equivalente - 14 mixed
  divergente - 15 DB ausente - 16 DB corrupta - 17 0 admins - 18 fallo backup -
  19 fallo antes de rename - 20 fallo de unidad - 21 fallo de arranque -
  22 auto-revert - 23 rollback compatible - 24 rollback incompatible -
  25 dry-run sin cambios.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import detect_state as ds  # noqa: E402
import migrate_sqlite as ms  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_NEW_UNIT = _REPO / "viewer" / "systemd" / "s9-knowledge-viewer.service"


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------
def make_auth(path: Path, n_users: int, n_active_admins: int) -> None:
    if path.exists():
        path.unlink()
    c = sqlite3.connect(str(path))
    c.executescript(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,"
        " display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'viewer',"
        " is_active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0);"
    )
    c.execute("INSERT INTO schema_version VALUES (1, '2026-01-01T00:00:00Z')")
    for i in range(n_users):
        role = "admin" if i < n_active_admins else "viewer"
        c.execute(
            "INSERT INTO users (username, display_name, password_hash, role, is_active) VALUES (?,?,?,?,1)",
            (f"u{i}", f"User {i}", "h" * 60, role),
        )
    c.commit()
    c.close()


def make_jobs(path: Path, n: int) -> None:
    if path.exists():
        path.unlink()
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY, status TEXT, created_at TEXT)")
    for i in range(n):
        c.execute("INSERT INTO jobs VALUES (?,?,?)", (f"job{i}", "completed", "2026-01-01"))
    c.commit()
    c.close()


def det(**kw):
    return ds.detect(
        kw.get("legacy_auth"), kw.get("legacy_jobs"),
        kw.get("new_auth"), kw.get("new_jobs"), kw.get("mode", "upgrade"),
    )


# ===========================================================================
# 1-7: detección y migración con preservación
# ===========================================================================
def test_01_legacy_state(tmp_path):
    la = tmp_path / "legacy_auth.db"; make_auth(la, 1, 1)
    r = det(legacy_auth=str(la), new_auth=str(tmp_path / "new_auth.db"), mode="upgrade")
    assert r["per_kind"]["auth"]["state"] == "LEGACY_STATE"


def test_02_migrate_auth(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 3, 1)
    dst = tmp_path / "state" / "auth.db"
    res = ms.plan_or_apply("auth", la, dst, apply=True, confirm=True)
    assert res["status"] == "MIGRATED" and dst.exists()


def test_03_migrate_jobs(tmp_path):
    lj = tmp_path / "lj.db"; make_jobs(lj, 5)
    dst = tmp_path / "state" / "jobs.db"
    res = ms.plan_or_apply("jobs", lj, dst, apply=True, confirm=True)
    assert res["status"] == "MIGRATED"


def test_04_integrity_ok(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 1, 1)
    assert ms.inspect_db(la, "auth")["integrity"] == "ok"


def test_05_preserva_usuarios(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 4, 2)
    dst = tmp_path / "s" / "auth.db"
    res = ms.plan_or_apply("auth", la, dst, True, True)
    assert res["dst_info_after"]["counts"]["users"] == 4


def test_06_preserva_admin(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 4, 2)
    dst = tmp_path / "s" / "auth.db"
    res = ms.plan_or_apply("auth", la, dst, True, True)
    assert res["dst_info_after"]["counts"]["active_admins"] == 2


def test_07_preserva_jobs(tmp_path):
    lj = tmp_path / "lj.db"; make_jobs(lj, 7)
    dst = tmp_path / "s" / "jobs.db"
    res = ms.plan_or_apply("jobs", lj, dst, True, True)
    assert res["dst_info_after"]["counts"]["jobs"] == 7


# ===========================================================================
# 8-9: unidad basada en current / legacy usa estado externo
# ===========================================================================
def _validate_unit(unit_path: Path) -> int:
    return subprocess.run(
        ["bash", str(_SCRIPTS / "validate_deploy.sh"), "unit", str(unit_path)],
        capture_output=True, text=True,
    ).returncode


def test_08_legacy_unit_rechazada(tmp_path):
    legacy = tmp_path / "legacy.service"
    legacy.write_text(
        "[Service]\nWorkingDirectory=/opt/knowledge-services/s9-knowledge-repo/viewer\n"
        "ExecStart=/opt/knowledge-services/s9-knowledge-repo/viewer/.venv/bin/uvicorn app.main:app\n"
    )
    assert _validate_unit(legacy) != 0  # legacy no entiende estado externo


def test_09_current_based_unit_ok():
    assert _validate_unit(_NEW_UNIT) == 0


# ===========================================================================
# 10-11: activación / commit ejecutado (verificador de identidad)
# ===========================================================================
def _make_release(root: Path, release_id: str, commit: str) -> Path:
    rel = root / "releases" / release_id
    (rel / "viewer" / ".venv" / "bin").mkdir(parents=True)
    (rel / "manifest.json").write_text(json.dumps({
        "release_id": release_id, "git_commit": commit,
        "schema_versions": {"auth_db": 1, "job_store": 1},
    }))
    cur = root / "current"
    if cur.exists() or cur.is_symlink():
        cur.unlink()
    cur.symlink_to(rel)
    return rel


def test_10_activacion_release(tmp_path):
    import verify_release_identity as vri
    _make_release(tmp_path, "abc1234-20260101-000000", "abc1234deadbeef")
    r = vri.verify(tmp_path, "abc1234-20260101-000000", None, pid=None, unit="nope.service")
    assert r["active_release"] == "abc1234-20260101-000000"
    # release_id coincide aunque el proceso no esté vivo en el lab
    assert any(c["check"] == "active_is_expected_release" and c["ok"] for c in r["checks"])


def test_11_commit_ejecutado_match(tmp_path):
    import verify_release_identity as vri
    _make_release(tmp_path, "r1", "abc1234deadbeef")
    r = vri.verify(tmp_path, "r1", "abc1234", pid=None, unit="nope.service")
    assert any(c["check"] == "git_commit_matches" and c["ok"] for c in r["checks"])


# ===========================================================================
# 12-17: idempotencia y estados
# ===========================================================================
def test_12_idempotente(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 2, 1)
    dst = tmp_path / "s" / "auth.db"
    ms.plan_or_apply("auth", la, dst, True, True)
    res2 = ms.plan_or_apply("auth", la, dst, True, True)
    assert res2["status"] == "ALREADY_DONE"


def test_13_mixed_equivalente(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 2, 1)
    na = tmp_path / "na.db"; make_auth(na, 2, 1)
    r = det(legacy_auth=str(la), new_auth=str(na), mode="upgrade")
    assert r["per_kind"]["auth"]["state"] == "MIXED_EQUIVALENT_STATE"
    assert r["decision"] == "PROCEED"


def test_14_mixed_divergente(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 2, 1)
    na = tmp_path / "na.db"; make_auth(na, 5, 1)
    r = det(legacy_auth=str(la), new_auth=str(na), mode="upgrade")
    assert r["per_kind"]["auth"]["state"] == "CONFLICTING_STATE"
    assert r["decision"] == "BLOCK"


def test_15_db_ausente_empty(tmp_path):
    r = det(new_auth=str(tmp_path / "nope.db"), mode="upgrade")
    assert r["per_kind"]["auth"]["state"] == "EMPTY_STATE"
    assert r["decision"] == "BLOCK"


def test_16_db_corrupta(tmp_path):
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"this is not a sqlite database " * 5)
    info = ms.inspect_db(bad, "auth")
    assert info["integrity"] == "corrupt"
    r = det(legacy_auth=str(bad), mode="upgrade")
    assert r["per_kind"]["auth"]["state"] == "CORRUPT_STATE"
    assert r["decision"] == "BLOCK"


def test_17_cero_admins(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 3, 0)  # 3 users, 0 active admins
    lj = tmp_path / "lj.db"; make_jobs(lj, 1)
    r = det(legacy_auth=str(la), legacy_jobs=str(lj), mode="upgrade")
    assert r["decision"] == "BLOCK"
    assert any("administradores activos" in x for x in r["reasons"])


# ===========================================================================
# 18-22: fallos simulados y auto-revert
# ===========================================================================
def test_18_fallo_backup(tmp_path, monkeypatch):
    la = tmp_path / "la.db"; make_auth(la, 1, 1)
    dst = tmp_path / "s" / "auth.db"

    def boom(src, tmp):
        raise sqlite3.OperationalError("backup simulado falla")

    monkeypatch.setattr(ms, "_backup_to_temp", boom)
    with pytest.raises(sqlite3.OperationalError):
        ms.plan_or_apply("auth", la, dst, True, True)
    assert not dst.exists()  # no se dejó destino a medias


def test_19_fallo_antes_de_rename(tmp_path, monkeypatch):
    la = tmp_path / "la.db"; make_auth(la, 2, 1)
    dst = tmp_path / "s" / "auth.db"

    # Simular que la copia temporal sale con conteos distintos -> no hay rename
    real_inspect = ms.inspect_db
    calls = {"n": 0}

    def fake_inspect(path, kind):
        info = real_inspect(path, kind)
        # alterar SOLO la inspección del temporal (dentro de dst.parent, prefijo .migrate-)
        if path.name.startswith(".migrate-"):
            info = dict(info)
            info["counts"] = {"users": 999, "active_admins": 1, "schema_version": 1}
        return info

    monkeypatch.setattr(ms, "inspect_db", fake_inspect)
    res = ms.plan_or_apply("auth", la, dst, True, True)
    assert res["status"] == "FAILED_COUNT_MISMATCH"
    assert not dst.exists()


def test_20_fallo_de_unidad(tmp_path):
    legacy = tmp_path / "u.service"
    legacy.write_text("[Service]\nWorkingDirectory=/opt/knowledge-services/s9-knowledge-repo/viewer\n")
    assert _validate_unit(legacy) != 0


def test_21_fallo_arranque_mismatch(tmp_path):
    import verify_release_identity as vri
    _make_release(tmp_path, "r1", "abc1234")
    # PID de este proceso de test: su cwd NO cuelga de la release -> MISMATCH
    r = vri.verify(tmp_path, "r1", "abc1234", pid=os.getpid(), unit="x")
    assert r["verdict"] == "MISMATCH"


def test_22_auto_revert_decision(tmp_path):
    import verify_release_identity as vri
    _make_release(tmp_path, "r1", "abc1234")
    r = vri.verify(tmp_path, "r_esperada_distinta", "abc1234", pid=None, unit="x")
    # release activa != esperada -> MISMATCH -> deploy.sh dispararía auto-revert
    assert r["verdict"] == "MISMATCH"


# ===========================================================================
# 23-24: rollback compatible / incompatible
# ===========================================================================
def test_23_rollback_compatible():
    # una release cuyo unit está basado en current entiende el estado externo
    assert _validate_unit(_NEW_UNIT) == 0


def test_24_rollback_incompatible(tmp_path):
    legacy = tmp_path / "legacy.service"
    legacy.write_text(
        "[Service]\nWorkingDirectory=/opt/knowledge-services/s9-knowledge-repo/viewer\n"
        "ExecStart=/opt/knowledge-services/s9-knowledge-repo/viewer/.venv/bin/uvicorn app.main:app\n"
    )
    assert _validate_unit(legacy) != 0  # rollback directo bloqueado -> requiere bridge


# ===========================================================================
# 25: dry-run sin cambios
# ===========================================================================
def test_25_dry_run_sin_cambios(tmp_path):
    la = tmp_path / "la.db"; make_auth(la, 1, 1)
    dst = tmp_path / "s" / "auth.db"
    res = ms.plan_or_apply("auth", la, dst, apply=False, confirm=False)
    assert res["status"] == "PLAN" and res["changed"] is False
    assert not dst.exists()  # el plan NO crea el destino


# ===========================================================================
# Gate de secretos (CSRF / fichero de contraseña)
# ===========================================================================
_VALIDATE = _SCRIPTS / "validate_deploy.sh"


def _write_env(tmp_path, csrf=None, neo4j_user="neo4j", pwfile=None):
    lines = [f"S9K_NEO4J_USER={neo4j_user}"]
    if pwfile is not None:
        lines.append(f"S9K_NEO4J_PASSWORD_FILE={pwfile}")
    if csrf is not None:
        lines.append(f"S9K_CSRF_SECRET={csrf}")
    p = tmp_path / "viewer.env"
    p.write_text("\n".join(lines) + "\n")
    return p


def _run_validate(sub, arg):
    return subprocess.run(["bash", str(_VALIDATE), sub, str(arg)], capture_output=True, text=True)


def test_csrf_placeholder_rechazado(tmp_path):
    for ph in ("change-me-in-host", "CHANGE-ME", "secret", "default", "changeme"):
        env = _write_env(tmp_path, csrf=ph)
        assert _run_validate("csrf", env).returncode != 0, ph


def test_csrf_vacio_rechazado(tmp_path):
    env = _write_env(tmp_path, csrf="")
    assert _run_validate("csrf", env).returncode != 0


def test_csrf_corto_rechazado(tmp_path):
    env = _write_env(tmp_path, csrf="abc123")  # < 32
    assert _run_validate("csrf", env).returncode != 0


def test_csrf_baja_entropia_rechazado(tmp_path):
    env = _write_env(tmp_path, csrf="a" * 40)  # >=32 pero 1 solo carácter
    assert _run_validate("csrf", env).returncode != 0


def test_csrf_valido_aceptado(tmp_path):
    good = "9f3a2b7c8d1e4f5a6b0c9d8e7f60a1b2c3d4e5f6"  # 40 hex, alta entropía
    env = _write_env(tmp_path, csrf=good)
    assert _run_validate("csrf", env).returncode == 0


def test_csrf_igual_a_usuario_rechazado(tmp_path):
    val = "ZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZm"
    env = _write_env(tmp_path, csrf=val, neo4j_user=val)
    assert _run_validate("csrf", env).returncode != 0


def test_csrf_valor_no_aparece_en_logs(tmp_path):
    env = _write_env(tmp_path, csrf="abc123")  # se rechaza por corto
    r = _run_validate("csrf", env)
    assert "abc123" not in (r.stdout + r.stderr)


def test_secret_file_inexistente_rechazado(tmp_path):
    r = _run_validate("secret-file", tmp_path / "no_existe")
    assert r.returncode != 0


def test_secret_file_permisos_inseguros_rechazado(tmp_path):
    f = tmp_path / "pw"; f.write_text("x"); f.chmod(0o644)
    assert _run_validate("secret-file", f).returncode != 0


def test_secret_file_seguro_aceptado(tmp_path):
    f = tmp_path / "pw"; f.write_text("x"); f.chmod(0o600)
    assert _run_validate("secret-file", f).returncode == 0


def test_template_proxy_headers_false():
    txt = (_REPO / "deploy" / "config" / "viewer.env.example").read_text()
    assert "S9K_AUTH_TRUST_PROXY_HEADERS=false" in txt
    assert "S9K_AUTH_TRUST_PROXY_HEADERS=true" not in txt


def test_template_csrf_no_placeholder():
    txt = (_REPO / "deploy" / "config" / "viewer.env.example").read_text()
    # el valor no debe estar activo con un placeholder; debe ir comentado/vacío
    assert "S9K_CSRF_SECRET=change-me-in-host" not in txt
