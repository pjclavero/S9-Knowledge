"""RC1-G02 (ronda 2): `error_code` y `error_message` se escriben y se limpian JUNTOS.

Medido en la revision de la ronda 1: `mark_failed` empezo a escribir
`error_code`, pero `mark_complete` solo limpiaba `error_message`. Un job que
fallaba de forma reintentable y luego terminaba bien quedaba `complete` con
`error_code` rancio, y el panel (`has_error = error_message or error_code`)
lo pintaba con incidencia.

Politica (la que ya tenia `error_message` en main, el codigo la acompaña):
- `mark_complete` limpia los dos;
- `mark_failed` reescribe los dos (sin codigo, el codigo queda a NULL);
- `claim_next_job`, `mark_running` y `mark_cancelled` conservan los dos (el
  ultimo fallo sigue visible para diagnostico mientras se reintenta);
- `mark_skipped`, `release_stale_jobs`, `set_status(error_message=...)` y
  `update_job(error_message=...)` (reencolado de la CLI) escriben un mensaje
  sin codigo: el codigo anterior se limpia.

Arnes local: SQLite temporal, sin Neo4j.
"""
from __future__ import annotations

import pytest

from jobs import job_store

CODIGO = "GRAPH_OBSERVATION_UNAVAILABLE"


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "jobs.db")
    job_store.init_db(path)
    return path


def _campos(job_id, db):
    job = job_store.get_job(job_id, db_path=db)
    return job["status"], job["error_code"], job["error_message"]


def _fallado_reintentable_y_reclamado(db, codigo=CODIGO):
    """Un job que fallo con codigo, volvio a `pending` y se ha reclamado otra vez."""
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    assert job_store.claim_next_job("w1", db_path=db)["job_id"] == job_id
    assert job_store.mark_failed(job_id, f"{codigo}: frase", retry=True, db_path=db,
                                 error_code=codigo)
    assert _campos(job_id, db) == ("pending", codigo, f"{codigo}: frase")
    assert job_store.claim_next_job("w1", db_path=db)["job_id"] == job_id
    return job_id


def test_reintentable_y_luego_exito_no_deja_error_code(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.mark_complete(job_id, {"ok": True}, db_path=db, locked_by="w1")
    assert _campos(job_id, db) == ("complete", None, None)


def test_fallo_permanente_guarda_codigo_y_mensaje_coherentes(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("w1", db_path=db)
    assert job_store.mark_failed(job_id, "GRAPH_CREDENTIAL_UNUSABLE: frase",
                                 retry=False, db_path=db,
                                 error_code="GRAPH_CREDENTIAL_UNUSABLE")
    status, codigo, mensaje = _campos(job_id, db)
    assert status == "failed"
    assert codigo == "GRAPH_CREDENTIAL_UNUSABLE"
    assert mensaje.startswith(codigo + ":")


def test_al_reclamar_y_al_marcar_running_se_conservan_los_dos(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert _campos(job_id, db) == ("running", CODIGO, f"{CODIGO}: frase")
    assert job_store.mark_running(job_id, "w2", db_path=db)
    assert _campos(job_id, db) == ("running", CODIGO, f"{CODIGO}: frase")


def test_un_fallo_nuevo_sin_codigo_no_hereda_el_anterior(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.mark_failed(job_id, "otro fallo", retry=True, db_path=db)
    assert _campos(job_id, db) == ("pending", None, "otro fallo")


def test_un_fallo_nuevo_con_otro_codigo_lo_sustituye(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.mark_failed(job_id, "GRAPH_CREDENTIAL_UNUSABLE: f", retry=False,
                                 db_path=db, error_code="GRAPH_CREDENTIAL_UNUSABLE")
    assert _campos(job_id, db) == ("failed", "GRAPH_CREDENTIAL_UNUSABLE",
                                   "GRAPH_CREDENTIAL_UNUSABLE: f")


def test_cancelar_conserva_los_dos(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.mark_cancelled(job_id, db_path=db)
    assert _campos(job_id, db) == ("cancelled", CODIGO, f"{CODIGO}: frase")


def test_skipped_escribe_su_mensaje_y_limpia_el_codigo(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.mark_skipped(job_id, "sin handler", db_path=db)
    assert _campos(job_id, db) == ("skipped", None, "sin handler")


def test_skipped_sin_mensaje_limpia_los_dos(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.mark_skipped(job_id, "", db_path=db)
    assert _campos(job_id, db) == ("skipped", None, None)


@pytest.mark.parametrize("max_attempts,estado", [(5, "pending"), (2, "failed")])
def test_liberar_huerfano_limpia_el_codigo_anterior(db, max_attempts, estado):
    job_id = job_store.create_job("leyenda", job_type="echo", max_attempts=max_attempts,
                                  db_path=db)
    job_store.claim_next_job("w1", db_path=db)
    job_store.mark_failed(job_id, f"{CODIGO}: frase", retry=True, db_path=db,
                          error_code=CODIGO)
    job_store.claim_next_job("w1", db_path=db)
    # timeout negativo: cualquier `locked_at` es anterior al corte.
    assert job_store.release_stale_jobs(-60, db_path=db) == [job_id]
    status, codigo, mensaje = _campos(job_id, db)
    assert status == estado
    assert codigo is None
    assert "stale" in mensaje


def test_set_status_con_mensaje_limpia_el_codigo(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.set_status(job_id, "failed", error_message="manual", db_path=db)
    assert _campos(job_id, db) == ("failed", None, "manual")


def test_set_status_sin_mensaje_no_toca_ninguno(db):
    job_id = _fallado_reintentable_y_reclamado(db)
    assert job_store.set_status(job_id, "running", db_path=db)
    assert _campos(job_id, db) == ("running", CODIGO, f"{CODIGO}: frase")


def test_reencolado_de_la_cli_limpia_los_dos(db):
    """`cli/jobs.py retry` hace `update_job(status='pending', attempts=0,
    error_message=None)`: sin la regla, el codigo sobreviviria al reencolado."""
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("w1", db_path=db)
    job_store.mark_failed(job_id, f"{CODIGO}: frase", retry=False, db_path=db,
                          error_code=CODIGO)
    assert job_store.update_job(job_id, status="pending", attempts=0,
                                error_message=None, db_path=db)
    assert _campos(job_id, db) == ("pending", None, None)


def test_update_job_con_codigo_explicito_lo_respeta(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    assert job_store.update_job(job_id, error_message="X: y", error_code="X", db_path=db)
    assert _campos(job_id, db) == ("pending", "X", "X: y")
