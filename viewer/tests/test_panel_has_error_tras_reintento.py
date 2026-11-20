"""RC1-G02 (ronda 2): un job que fallo, se reintento y termino bien NO tiene incidencia.

Medido en la revision de la ronda 1: `mark_complete` limpiaba `error_message`
pero no `error_code`, y las dos reglas del panel que derivan la señal
(`jobs_client.redact_job` y la fila de `chassis_operations`) la calculan con
`error_message or error_code`: el job `complete` salia con incidencia.

Usa las reglas REALES del visor (no una copia) sobre una cola SQLite temporal
escrita por el `job_store` real.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import jobs_client
from app.routers.chassis_operations import _fila

CODIGO = "GRAPH_OBSERVATION_UNAVAILABLE"
_REVISOR = SimpleNamespace(sees_operational_detail=False)


@pytest.fixture
def cola(tmp_path):
    job_store = jobs_client._load_job_store()
    assert job_store is not None, "el visor no encuentra data-engine/app/jobs"
    db = str(tmp_path / "jobs.db")
    job_store.init_db(db)
    return job_store, db


def _senales(job_store, job_id, db):
    job = jobs_client.serialize_job(job_store.get_job(job_id, db_path=db))
    return (jobs_client.redact_job(job, _REVISOR)["has_error"],
            _fila(job, None)["has_error"])


def test_reintentable_y_luego_exito_sin_incidencia_en_el_panel(cola):
    job_store, db = cola
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("w1", db_path=db)
    job_store.mark_failed(job_id, f"{CODIGO}: frase", retry=True, db_path=db,
                          error_code=CODIGO)
    # Mientras se reintenta, la incidencia SI se ve (diagnostico).
    senales = _senales(job_store, job_id, db)
    assert senales == (True, True), f"RC1-G02: EL REINTENTO NO MUESTRA INCIDENCIA: {senales!r}"
    job_store.claim_next_job("w1", db_path=db)
    job_store.mark_complete(job_id, {"ok": True}, db_path=db, locked_by="w1")

    job = job_store.get_job(job_id, db_path=db)
    assert job["error_code"] is None, \
        f"RC1-G02: ERROR_CODE RANCIO TRAS EXITO: {job['error_code']!r}"
    senales = _senales(job_store, job_id, db)
    assert senales == (False, False), \
        f"RC1-G02: EL PANEL PINTA INCIDENCIA EN UN JOB COMPLETE: {senales!r}"
    assert job["status"] == "complete", f"RC1-G02: EL JOB NO TERMINA COMPLETE: {job['status']!r}"


def test_fallo_permanente_con_incidencia_en_el_panel(cola):
    job_store, db = cola
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("w1", db_path=db)
    job_store.mark_failed(job_id, "GRAPH_CREDENTIAL_UNUSABLE: frase", retry=False,
                          db_path=db, error_code="GRAPH_CREDENTIAL_UNUSABLE")
    senales = _senales(job_store, job_id, db)
    assert senales == (True, True), \
        f"RC1-G02: EL FALLO PERMANENTE NO MUESTRA INCIDENCIA: {senales!r}"
    # El revisor ve el codigo (campo publico) pero no el texto.
    job = jobs_client.serialize_job(job_store.get_job(job_id, db_path=db))
    recortado = jobs_client.redact_job(job, _REVISOR)
    assert recortado.get("error_code") == "GRAPH_CREDENTIAL_UNUSABLE", \
        f"RC1-G02: EL REVISOR NO VE EL CODIGO: {recortado.get('error_code')!r}"
    assert "error_message" not in recortado, "RC1-G02: EL REVISOR VE EL TEXTO DEL ERROR"
