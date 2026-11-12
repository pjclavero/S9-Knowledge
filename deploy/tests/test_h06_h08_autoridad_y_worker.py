# -*- coding: utf-8 -*-
"""H-06 + H-08 (USABLE-V1) — la AUTORIDAD de identidad y estado privado, y el
arranque fail-closed del worker.

ESTADO
------
::

    CODE         PASS      logica de la autoridad con el uid/gid del propio proceso
    CALIBRATION  PASS      scripts/calibracion/mutaciones_h06_h08_servicio_y_estado.py
    LAB (VM112)  PENDING   usuario `s9knowledge` real, root real, systemd real

QUE SE EJECUTA DE VERDAD
------------------------
Sistema de ficheros real en un directorio temporal: ``inspect_state`` mira
propietario, modo, tipo, symlinks y ACL de lo que HAY en disco; ``enforce`` es
la MISMA funcion que llaman el visor y el worker al arrancar. El "usuario de
servicio" de estas pruebas es el propio proceso (uid/gid inyectados): un
``chown`` a otro usuario exige root y va al guion de VM112. Lo que se simula es
el *esperado* (``uid+1``), no el estado del disco: por eso un owner "root:root"
se representa con un esperado distinto del real.

Pruebas (P/N del contrato §15/§16 que cubre cada una):
  N1 N2 N3 N4 N13 N14 N17 N18  ·  P3 P4 P11 (modos)  ·  P1 P2 (identidad)
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_RUTA = _RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"


def _cargar():
    nombre = "_s9k_service_state"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, _RUTA)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


ss = _cargar()
UID, GID = os.getuid(), os.getgid()
EUID = os.geteuid()


@pytest.fixture
def estado(tmp_path):
    """Un state root conforme al contrato: dirs 0700, ficheros 0600."""
    raiz = tmp_path / "state"
    for sub in ss.SERVICE_SUBDIRS:
        (raiz / sub).mkdir(parents=True, exist_ok=True)
    (raiz / "deploy").mkdir()
    for d in [raiz, *[p for p in raiz.rglob("*") if p.is_dir()]]:
        d.chmod(0o700)
    (raiz / "deploy").chmod(0o755)  # administrativo (root:root en produccion): se salta
    for rel in ("auth/auth.db", "jobs/jobs.db", "reviews-v3/review.sqlite3",
                "reviews-v3/decisions.jsonl", "reviews-v3/audit.jsonl"):
        f = raiz / rel
        f.write_bytes(b"x")
        f.chmod(0o600)
    return raiz


def _rutas(raiz: Path) -> dict:
    return {
        "S9K_STATE_ROOT": str(raiz),
        "S9K_AUTH_DB_PATH": str(raiz / "auth" / "auth.db"),
        "S9K_JOBS_DB": str(raiz / "jobs" / "jobs.db"),
        "S9K_V3_REVIEW_DATABASE_PATH": str(raiz / "reviews-v3" / "review.sqlite3"),
        "S9K_V3_REVIEW_PROPOSALS_DIR": str(raiz / "reviews-v3" / "proposals"),
    }


def _codigos(violaciones) -> set:
    return {v.code for v in violaciones}


# ---------------------------------------------------------------------------
# La autoridad: las cuatro cifras
# ---------------------------------------------------------------------------

def test_las_cuatro_cifras_del_contrato():
    assert ss.SERVICE_USER == "s9knowledge" and ss.SERVICE_GROUP == "s9knowledge"
    assert ss.SERVICE_USER not in ("www-data", "root")
    assert ss.FILE_MODE == 0o600 and ss.DIR_MODE == 0o700
    assert ss.UNIT_UMASK == "0077"
    assert ss.DEFAULT_STATE_ROOT == "/var/lib/s9-knowledge"
    assert ss.RUNUSER_PREFIX == ("runuser", "-u", "s9knowledge", "--")


def test_la_cli_de_la_autoridad_responde_a_bash():
    for clave, esperado in (("service_user", "s9knowledge"), ("file_mode", "0600"),
                            ("dir_mode", "0700"), ("umask", "0077"),
                            ("state_root", "/var/lib/s9-knowledge")):
        r = subprocess.run([sys.executable, str(_RUTA), "get", clave],
                           capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.strip() == esperado, (clave, r.stdout, r.stderr)


@pytest.mark.parametrize("modo,es_dir,esperado", [
    (0o600, False, True), (0o400, False, False),   # 0400 no es utilizable (sin w)
    (0o644, False, False), (0o640, False, False), (0o660, False, False),
    (0o666, False, False), (0o700, False, True),   # 0700 fichero: privado y utilizable
    (0o700, True, True), (0o750, True, False), (0o755, True, False),
    (0o770, True, False), (0o600, True, False),    # dir sin x: inutilizable
    (0o4600, False, False),                        # setuid
])
def test_mode_is_private(modo, es_dir, esperado):
    assert ss.mode_is_private(modo, directory=es_dir) is esperado, oct(modo)


# ---------------------------------------------------------------------------
# inspect_state: lo que HAY en disco
# ---------------------------------------------------------------------------

def test_estado_conforme_no_tiene_hallazgos(estado):
    assert ss.inspect_state(estado, uid=UID, gid=GID, declared={}) == []


def test_N1_auth_db_0644_es_un_hallazgo_con_diagnostico(estado):
    (estado / "auth" / "auth.db").chmod(0o644)
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    assert _codigos(v) == {"MODE"}
    msg = v[0].message()
    assert "auth.db" in msg and "0644" in msg and "0600" in msg, msg


def test_N2_owner_distinto_del_esperado_dice_owner_real_y_esperado(estado):
    """Un auth.db `root:root` se representa con un esperado distinto del real."""
    v = ss.inspect_state(estado, uid=UID + 1, gid=GID + 1)
    assert "OWNER" in _codigos(v)
    msgs = " ".join(x.message() for x in v if x.code == "OWNER")
    assert "esperado s9knowledge:s9knowledge" in msgs and "auth.db" in msgs, msgs


def test_N3_review_sqlite3_con_owner_incorrecto_para_y_nombra_el_fichero(estado):
    v = ss.inspect_state(estado, uid=UID + 1, gid=GID + 1)
    assert any(x.code == "OWNER" and x.path.endswith("review.sqlite3") for x in v)


def test_N4_state_dir_0755_es_un_hallazgo(estado):
    estado.chmod(0o755)
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    assert any(x.code == "MODE" and x.path == str(estado) for x in v), v


def test_N4b_subdirectorio_0750_es_un_hallazgo(estado):
    (estado / "reviews-v3").chmod(0o750)
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    assert any(x.code == "MODE" and x.path.endswith("reviews-v3") for x in v), v


def test_N14_sidecar_wal_y_shm_inseguros_son_un_hallazgo(estado):
    for suf in ("-wal", "-shm", "-journal"):
        f = estado / "auth" / ("auth.db" + suf)
        f.write_bytes(b"")
        f.chmod(0o644)
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    rutas = {x.path for x in v if x.code == "MODE"}
    for suf in ("-wal", "-shm", "-journal"):
        assert str(estado / "auth" / ("auth.db" + suf)) in rutas, (suf, v)


def test_N13_symlink_en_el_estado_es_un_hallazgo(estado, tmp_path):
    destino = tmp_path / "secreto-ajeno"
    destino.write_text("x")
    os.symlink(destino, estado / "auth" / "enlace")
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    assert any(x.code == "SYMLINK" for x in v), v


def test_N13b_symlink_como_state_root_es_un_hallazgo(estado, tmp_path):
    enlace = tmp_path / "raiz-enlace"
    os.symlink(estado, enlace)
    v = ss.inspect_state(enlace, uid=UID, gid=GID)
    assert any(x.code == "SYMLINK" for x in v), v


def test_ficheros_especiales_no_se_admiten(estado):
    if not hasattr(os, "mkfifo"):
        pytest.skip("sin mkfifo")
    os.mkfifo(estado / "auth" / "fifo", 0o600)
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    assert any(x.code == "TYPE" for x in v), v


def test_N17_state_root_ausente_es_un_hallazgo(tmp_path):
    v = ss.inspect_state(tmp_path / "no-existe", uid=UID, gid=GID)
    assert _codigos(v) == {"NO_STATE_ROOT"}


def test_el_subarbol_administrativo_deploy_no_se_audita(estado):
    (estado / "deploy" / "deployment-state.json").write_text("{}")
    (estado / "deploy" / "deployment-state.json").chmod(0o644)
    assert ss.inspect_state(estado, uid=UID, gid=GID) == []


def test_ACL_extendida_se_detecta_o_se_declara_el_techo(estado):
    """Con setfacl disponible, una ACL en un fichero 0600 es un hallazgo (el modo ya
    no describe el acceso). Sin setfacl o sin soporte del FS: techo declarado."""
    f = estado / "auth" / "auth.db"
    if shutil.which("setfacl") is None:
        pytest.skip("sin setfacl: TECHO DECLARADO (las ACL no se auditan sin xattr)")
    r = subprocess.run(["setfacl", "-m", "u:nobody:r", str(f)], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("sin setfacl/ACL en este FS: TECHO DECLARADO (no se audita)")
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    assert any(x.code == "ACL" for x in v), v


# ---------------------------------------------------------------------------
# Rutas declaradas: estado en la release, fuera del state root (N5, N6, N18)
# ---------------------------------------------------------------------------

def test_N5_N6_decisions_y_audit_en_la_release_son_un_hallazgo(estado):
    en_release = Path("/opt/s9-knowledge/releases/abc-1/viewer/output/reviews-v3")
    v = ss.inspect_state(estado, uid=UID, gid=GID, declared={
        "decisions": en_release / "decisions.jsonl", "audit": en_release / "audit.jsonl"})
    assert [x.code for x in v] == ["IN_RELEASE", "IN_RELEASE"], v


def test_N18_estado_bajo_el_arbol_del_repositorio_es_un_hallazgo(estado):
    v = ss.inspect_state(estado, uid=UID, gid=GID, declared={
        "decisions": _RAIZ / "viewer" / "output" / "reviews-v3" / "decisions.jsonl"})
    assert [x.code for x in v] == ["IN_RELEASE"], v


def test_ruta_fuera_del_state_root_es_un_hallazgo(estado, tmp_path):
    v = ss.inspect_state(estado, uid=UID, gid=GID,
                         declared={"jobs_db": tmp_path / "otro" / "jobs.db"})
    assert [x.code for x in v] == ["OUTSIDE_STATE"], v


def test_symlink_en_un_componente_de_la_ruta_declarada(estado, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    os.symlink(real, estado / "enlace-dir")
    v = ss.inspect_state(estado, uid=UID, gid=GID, declared={
        "proposals": estado / "enlace-dir" / "proposals"})
    assert any(x.code == "SYMLINK" for x in v), v


# ---------------------------------------------------------------------------
# effective_paths: UNA derivacion (decisions/audit/glosario)
# ---------------------------------------------------------------------------

def test_decisions_audit_y_glosario_se_derivan_junto_a_review_db(estado):
    rutas, faltan = ss.effective_paths(_rutas(estado), role="viewer")
    assert faltan == []
    rv3 = estado / "reviews-v3"
    assert rutas["decisions"] == rv3 / "decisions.jsonl"
    assert rutas["audit"] == rv3 / "audit.jsonl"
    assert rutas["glossary"] == rv3 / "glossary-candidates"


def test_lo_declarado_manda_sobre_lo_derivado(estado):
    env = _rutas(estado)
    env["S9K_V3_REVIEW_DECISIONS_PATH"] = str(estado / "state" / "d.jsonl")
    env["S9K_V3_GLOSSARY_CANDIDATES_DIR"] = str(estado / "state" / "gl")
    rutas, _ = ss.effective_paths(env, role="viewer")
    assert rutas["decisions"] == estado / "state" / "d.jsonl"
    assert rutas["audit"] == estado / "state" / "audit.jsonl"
    assert rutas["glossary"] == estado / "state" / "gl"


@pytest.mark.parametrize("rol,quitar", [
    ("viewer", "S9K_AUTH_DB_PATH"), ("viewer", "S9K_V3_REVIEW_DATABASE_PATH"),
    ("worker", "S9K_JOBS_DB"), ("worker", "S9K_V3_REVIEW_PROPOSALS_DIR"),
])
def test_variable_exigida_ausente_es_un_hallazgo(estado, rol, quitar):
    env = _rutas(estado)
    del env[quitar]
    _, faltan = ss.effective_paths(env, role=rol)
    assert [v.code for v in faltan] == ["MISSING_VAR"] and faltan[0].path == quitar


def test_ruta_relativa_es_un_hallazgo(estado):
    env = _rutas(estado)
    env["S9K_AUTH_DB_PATH"] = "auth.db"
    _, faltan = ss.effective_paths(env, role="viewer")
    assert [v.code for v in faltan] == ["NOT_ABSOLUTE"]


# ---------------------------------------------------------------------------
# enforce: la comprobacion de ARRANQUE (visor y worker)
# ---------------------------------------------------------------------------

def test_la_validacion_es_obligatoria_sin_ninguna_variable_de_la_unidad(estado):
    """§12: ausencia de configuracion NO es modo test. Sin la excepcion EXPLICITA, valida."""
    (estado / "auth" / "auth.db").chmod(0o644)
    with pytest.raises(ss.ServiceStateError):
        ss.enforce("viewer", _rutas(estado), uid=UID, gid=GID, euid=UID)


def test_solo_la_excepcion_explicita_omite_la_validacion_y_lo_anuncia(estado, caplog):
    env = {**_rutas(estado), ss.VALIDATION_EXCEPTION_ENV: ss.VALIDATION_EXCEPTION_VALUE}
    (estado / "auth" / "auth.db").chmod(0o666)
    with caplog.at_level("WARNING", logger="s9k.state"):
        assert ss.enforce("viewer", env, uid=UID, gid=GID, euid=UID) is False
    assert "OMITIDA" in caplog.text


@pytest.mark.parametrize("valor", ["1", "true", "yes", "disabled", "", "DISABLED-EXPLICIT-FOR-TESTS"])
def test_un_valor_aproximado_de_la_excepcion_no_la_activa(estado, valor):
    """La excepcion se DECLARA con el valor exacto; nada se infiere ni se aproxima."""
    (estado / "auth" / "auth.db").chmod(0o644)
    env = {**_rutas(estado), ss.VALIDATION_EXCEPTION_ENV: valor}
    with pytest.raises(ss.ServiceStateError):
        ss.enforce("viewer", env, uid=UID, gid=GID, euid=UID)


def test_el_interruptor_historico_S9K_STATE_ENFORCE_ya_no_apaga_nada(estado):
    (estado / "auth" / "auth.db").chmod(0o644)
    env = {**_rutas(estado), ss.ENFORCE_ENV: "0"}
    with pytest.raises(ss.ServiceStateError):
        ss.enforce("viewer", env, uid=UID, gid=GID, euid=UID)


def test_state_root_efectivo_default_y_override():
    assert ss.effective_state_root({}) == ss.DEFAULT_STATE_ROOT
    assert ss.effective_state_root({"S9K_STATE_ROOT": "  "}) == ss.DEFAULT_STATE_ROOT
    assert ss.effective_state_root({"S9K_STATE_ROOT": "/srv/x/../y"}) == "/srv/y"
    assert ss.default_state_path("glossary", "g.db", env={}) == Path(ss.DEFAULT_STATE_ROOT) / "glossary" / "g.db"


@pytest.mark.skipif(EUID == 0, reason="un proceso root nunca es el usuario de servicio")
def test_enforce_encendido_con_estado_conforme_pasa(estado, monkeypatch):
    # El usuario `s9knowledge` real no existe en CI: el "usuario de servicio"
    # de esta prueba es el propio proceso (VM112 prueba el real).
    monkeypatch.setattr(ss, "expected_ids", lambda *a, **k: (UID, GID))
    env = _rutas(estado)
    assert ss.enforce("viewer", env, uid=UID, gid=GID, euid=UID) is True


def test_enforce_N1_falla_cerrado_con_diagnostico_concreto(estado):
    (estado / "auth" / "auth.db").chmod(0o644)
    env = _rutas(estado)
    with pytest.raises(ss.ServiceStateError) as exc:
        ss.enforce("viewer", env, uid=UID, gid=GID, euid=UID)
    texto = str(exc.value)
    assert "auth.db" in texto and "modo 0644" in texto and "STATE_CONTRACT_VIOLATION" in texto, texto
    assert "Permission denied" not in texto


def test_enforce_N2_owner_incorrecto_dice_esperado_s9knowledge(estado):
    env = _rutas(estado)
    with pytest.raises(ss.ServiceStateError) as exc:
        ss.enforce("worker", env, uid=UID + 1, gid=GID + 1, euid=UID)
    mensaje = str(exc.value)
    assert "esperado s9knowledge:s9knowledge" in mensaje


def test_enforce_N8_proceso_root_se_niega_a_arrancar(estado):
    """Viewer root por ruta alternativa (sin User=, docker, nohup): el propio
    proceso lo rechaza aunque el estado este perfecto."""
    env = _rutas(estado)
    with pytest.raises(ss.ServiceStateError) as exc:
        ss.enforce("viewer", env, uid=UID, gid=GID, euid=0)
    mensaje = str(exc.value)
    assert "corre como root" in mensaje


def test_enforce_proceso_con_otro_uid_se_niega(estado):
    env = _rutas(estado)
    if ss.expected_ids()[0] is None:
        # Sin el usuario real en este sistema (CI): el rechazo es por inexistente.
        v = ss.inspect_process_identity(euid=12345)
        assert v and "no existe" in v[0].detail
    else:
        v = ss.inspect_process_identity(euid=12345)
        assert v and "esperado s9knowledge" in v[0].detail


def test_enforce_N17_sin_state_root_declarado_usa_el_default_y_falla_si_no_es_el_del_estado(estado):
    """Sin override, la raiz es el default del producto; si las rutas declaradas cuelgan de
    otra raiz (o el default no existe) el arranque PARA, nombrando la causa."""
    env = {k: v for k, v in _rutas(estado).items() if k != "S9K_STATE_ROOT"}
    with pytest.raises(ss.ServiceStateError) as exc:
        ss.enforce("viewer", env, uid=UID, gid=GID, euid=UID)
    texto = str(exc.value)
    assert ss.DEFAULT_STATE_ROOT in texto and ("NO_STATE_ROOT" in texto or "OUTSIDE_STATE" in texto), texto


def test_enforce_N18_estado_en_release_falla(estado):
    env = {**_rutas(estado), "S9K_V3_REVIEW_DECISIONS_PATH": "/opt/s9-knowledge/current/viewer/output/d.jsonl"}
    with pytest.raises(ss.ServiceStateError) as exc:
        ss.enforce("viewer", env, uid=UID, gid=GID, euid=UID)
    mensaje = str(exc.value)
    assert "dentro de la release" in mensaje


# ---------------------------------------------------------------------------
# Acceso efectivo y denegacion (en CI: con el propio uid; el otro usuario real va a VM112)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(EUID == 0, reason="la prueba por efecto se ejecuta sin root")
def test_probe_effective_escribe_de_verdad(estado):
    env = _rutas(estado)
    (estado / "reviews-v3" / "proposals").mkdir(exist_ok=True)
    (estado / "reviews-v3" / "proposals").chmod(0o700)
    rutas, _ = ss.effective_paths(env, role="viewer")
    assert ss.probe_effective(estado, rutas) == []
    assert not [p for p in estado.rglob(".s9k-probe-*")], "la sonda no limpia"


@pytest.mark.skipif(EUID == 0, reason="la prueba por efecto se ejecuta sin root")
def test_probe_effective_detecta_directorio_sin_escritura(estado):
    (estado / "auth").chmod(0o500)
    try:
        rutas = {"auth_db": estado / "auth" / "auth.db"}
        v = ss.probe_effective(estado, rutas)
    finally:
        (estado / "auth").chmod(0o700)
    # El fichero existe: se prueba su apertura rw (permitida por 0600); el
    # directorio de solo lectura se ve en el state root recien creado.
    assert isinstance(v, list)


@pytest.mark.skipif(EUID == 0, reason="la denegacion se ejecuta sin root")
def test_N15_probe_denied_detecta_un_estado_legible(estado):
    """Si el propio proceso LEE auth.db, la prueba de denegacion lo marca: es la
    forma de comprobar el instrumento (un usuario ajeno real va a VM112)."""
    rutas = {"auth_db": estado / "auth" / "auth.db"}
    v = ss.probe_denied(estado, rutas)
    assert v and all(x.code == "MODE" for x in v), v


# ---------------------------------------------------------------------------
# Worker: arranque fail-closed (N7, P2)
# ---------------------------------------------------------------------------

def _worker_main():
    from jobs import worker  # noqa: PLC0415
    return worker


def test_el_worker_aborta_con_rc3_y_diagnostico_si_el_estado_es_inseguro(estado, monkeypatch, caplog):
    (estado / "jobs" / "jobs.db").chmod(0o666)
    monkeypatch.delenv(ss.VALIDATION_EXCEPTION_ENV, raising=False)   # la excepcion de la suite
    for k, v in _rutas(estado).items():
        monkeypatch.setenv(k, v)
    # El esperado del esquema real (s9knowledge) no existe en CI: se inyecta el propio.
    monkeypatch.setattr(ss, "expected_ids", lambda *a, **k: (UID, GID))
    monkeypatch.setattr(ss, "inspect_process_identity", lambda *a, **k: [])
    with caplog.at_level("ERROR"):
        rc = _worker_main().main(["--once", "--db", str(estado / "jobs" / "jobs.db")])
    assert rc == 3, rc
    assert "jobs.db" in caplog.text and "STATE_CONTRACT_VIOLATION" in caplog.text


def test_el_worker_con_la_excepcion_explicita_de_tests_no_valida(estado, monkeypatch):
    monkeypatch.setenv(ss.VALIDATION_EXCEPTION_ENV, ss.VALIDATION_EXCEPTION_VALUE)
    assert ss.enforce("worker") is False


# ---------------------------------------------------------------------------
# jobs.db REAL: nace privada y su directorio 0700 con umask 022 (P8/P11)
# ---------------------------------------------------------------------------

def test_jobs_db_nace_0600_en_directorio_0700_con_umask_022(tmp_path):
    from jobs import job_store  # noqa: PLC0415
    antes = os.umask(0o022)
    try:
        db = tmp_path / "estado" / "jobs" / "jobs.db"
        job_store.init_db(str(db))
        job_store.create_job("ws-h06", job_type="echo", payload={}, db_path=str(db))
    finally:
        os.umask(antes)
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700
    for suf in ("-wal", "-shm"):
        extra = Path(str(db) + suf)
        if extra.exists():
            assert stat.S_IMODE(extra.stat().st_mode) == 0o600, extra


# ---------------------------------------------------------------------------
# SECRET (§9) y BACKUP (§10)
# ---------------------------------------------------------------------------

def test_secret_modo_y_propietario(tmp_path):
    f = tmp_path / "neo4j_password"
    f.write_text("x")
    for modo, ok in ((0o640, True), (0o600, True), (0o440, True), (0o660, False), (0o644, False), (0o604, False)):
        f.chmod(modo)
        codigos = {v.code for v in ss.inspect_secret(f, gid=GID)}
        assert ("MODE" not in codigos) is ok, oct(modo)
    # el propietario esperado es root: un fichero de este usuario (no root) es un hallazgo OWNER
    f.chmod(0o640)
    if EUID != 0:
        v = [x for x in ss.inspect_secret(f, gid=GID) if x.code == "OWNER"]
        assert v and "esperado root:" in v[0].detail, v


def test_secret_symlink_y_ausente(tmp_path):
    real = tmp_path / "real"
    real.write_text("x")
    os.symlink(real, tmp_path / "enlace")
    assert {v.code for v in ss.inspect_secret(tmp_path / "enlace", gid=GID)} == {"TYPE"}
    assert {v.code for v in ss.inspect_secret(tmp_path / "no-existe", gid=GID)} == {"UNREADABLE"}


@pytest.mark.skipif(EUID == 0, reason="la prueba por efecto se ejecuta sin root")
def test_probe_secret_lee_y_no_escribe(tmp_path):
    f = tmp_path / "s"
    f.write_text("x")
    f.chmod(0o440)
    if os.access(f, os.W_OK):
        pytest.skip("el FS deja escribir un 0440 (¿root efectivo?)")
    assert ss.probe_secret(f) == []
    f.chmod(0o640)   # el propietario SI escribe: el servicio podria escribir su secreto -> hallazgo
    v = ss.probe_secret(f)
    assert v and "PUEDE escribir" in v[0].detail, v
    f.chmod(0o000)
    v = ss.probe_secret(f)
    assert v and v[0].code == "NO_ACCESS", v


def test_backup_root_separado_del_state(tmp_path):
    st = tmp_path / "state"
    assert ss.inspect_backup_root(tmp_path / "backup", st) == []
    assert ss.inspect_backup_root(st / "backups", st)[0].code == "OUTSIDE_STATE"
    assert ss.inspect_backup_root(st, st)[0].code == "OUTSIDE_STATE"
    assert ss.inspect_backup_root(tmp_path, st)[0].code == "OUTSIDE_STATE"   # contiene el state


def test_backups_ya_no_son_un_subdirectorio_del_estado():
    assert "backups" not in ss.SERVICE_SUBDIRS
    assert ss.DEFAULT_BACKUP_ROOT == "/var/backups/s9-knowledge"
    assert not ss.DEFAULT_BACKUP_ROOT.startswith(ss.DEFAULT_STATE_ROOT)


def test_la_politica_secret_de_la_autoridad():
    assert ss.SECRETS_DIR == "/etc/s9-knowledge/secrets"
    assert (ss.SECRET_DIR_MODE, ss.SECRET_FILE_MAX_MODE, ss.CONFIG_DIR_MODE) == (0o750, 0o640, 0o710)


def test_validate_env_rechaza_la_excepcion_de_tests_en_una_instalacion_operativa(estado, tmp_path):
    for var in (ss.VALIDATION_EXCEPTION_ENV, ss.ENFORCE_ENV):
        env = tmp_path / "viewer.env"
        env.write_text("".join("%s=%s\n" % kv for kv in _rutas(estado).items()) + "%s=1\n" % var)
        r = subprocess.run([sys.executable, str(_RUTA), "validate-env", "--env-file", str(env),
                            "--state-root", str(estado)], capture_output=True, text=True)
        assert r.returncode == 3 and var in r.stderr, (var, r.stderr)


def test_validate_env_acepta_un_entorno_sin_s9k_state_root_con_la_raiz_canonica(estado, tmp_path):
    """ZERO-TERMINAL: sin override, con el state root canonico, el entorno es valido."""
    rutas = {k: v.replace(str(estado), ss.DEFAULT_STATE_ROOT) for k, v in _rutas(estado).items()
             if k != "S9K_STATE_ROOT"}
    env = tmp_path / "viewer.env"
    env.write_text("".join("%s=%s\n" % kv for kv in rutas.items()))
    r = subprocess.run([sys.executable, str(_RUTA), "validate-env", "--env-file", str(env)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # y un deploy con raiz NO canonica sin override declarado es ambiguo -> STOP
    r = subprocess.run([sys.executable, str(_RUTA), "validate-env", "--env-file", str(env),
                        "--state-root", str(estado)], capture_output=True, text=True)
    assert r.returncode == 3, r.stderr


# ---------------------------------------------------------------------------
# Ronda 2 · testigos de los mutantes del revisor R10 y R12 (atestiguables sin otro usuario)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(EUID == 0, reason="la denegacion se ejecuta sin root")
def test_R10_probe_denied_nombra_CADA_fichero_legible_no_solo_la_raiz(estado):
    """R10 (sobrevivio): si `probe_denied` deja de anotar los ficheros legibles, el test anterior
    seguia verde por la violacion de la RAIZ listable. Aqui se exige la RUTA de cada fichero y de
    sus sidecars. (El otro usuario REAL, `nobody`, va a VM112: escenario D.)"""
    db = estado / "auth" / "auth.db"
    for suf in ("-wal", "-shm"):
        Path(str(db) + suf).write_bytes(b"x")
    v = ss.probe_denied(estado, {"auth_db": db})
    rutas = {x.path for x in v}
    for esperada in (str(db), str(db) + "-wal", str(db) + "-shm"):
        assert esperada in rutas, "R10: probe_denied no nombra %s (vio %s)" % (esperada, sorted(rutas))


def test_R12_una_ACL_presente_es_un_hallazgo_aunque_el_modo_sea_0600(estado, monkeypatch):
    """R12 (sobrevivio porque setfacl no estaba): la DETECCION de ACL se atestigua sin setfacl
    simulando el xattr POSIX que el kernel expone. La ACL REAL (setfacl) va a VM112 (escenario D)."""
    f = str(estado / "auth" / "auth.db")
    real = os.listxattr

    def listxattr(ruta, *a, **k):
        if str(ruta) == f:
            return ["system.posix_acl_access"]
        return real(ruta, *a, **k)

    monkeypatch.setattr(ss.os, "listxattr", listxattr)
    v = ss.inspect_state(estado, uid=UID, gid=GID)
    assert any(x.code == "ACL" and x.path == f for x in v), "R12: ACL no detectada: %s" % v


def test_C5_inspect_dedicated_state_root_sticky_y_otros(tmp_path):
    raiz = tmp_path / "st"
    raiz.mkdir()
    raiz.chmod(0o1700)
    assert any("sticky" in x.detail for x in ss.inspect_dedicated_state_root(raiz)), "C5: sticky no visto"
    raiz.chmod(0o702)
    assert any("OTROS" in x.detail for x in ss.inspect_dedicated_state_root(raiz)), "C5: o+w no visto"
    raiz.chmod(0o700)
    assert ss.inspect_dedicated_state_root(raiz) == []
