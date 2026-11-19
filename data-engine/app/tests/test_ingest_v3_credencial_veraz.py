"""RC1-G02: el mensaje del operador nombra la causa REAL de un fallo de credencial.

Medido en la RC: un worker que no podia usar el fichero del secreto de Neo4j
acababa con `GRAPH_OBSERVATION_UNCONFIGURED: ... no tiene declarada la
conexion`, cuando la conexion SI estaba declarada, y con `error_code` a NULL.
Un rojo por la causa equivocada: el operador revisaria una configuracion que
esta bien.

Arnes local: sin Neo4j, sin red. Los fallos de credencial ocurren ANTES de abrir
ningun driver; el control positivo sustituye la fabrica por un doble.
"""
from __future__ import annotations

import os

import pytest

from jobs import job_store, worker
from jobs.handlers import ingest_v3
from jobs.handlers.ingest_v3 import IngestV3Error

SECRETO = "S3CRETO-QUE-NO-DEBE-SALIR-9f3a"


@pytest.fixture
def conexion(monkeypatch, tmp_path):
    """Conexion declarada; devuelve el camino del fichero del secreto."""
    ruta = tmp_path / "neo4j-password"
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:7687")
    monkeypatch.setenv("S9K_NEO4J_USER", "neo4j")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(ruta))
    return ruta


def _fallo() -> IngestV3Error:
    with pytest.raises(IngestV3Error) as info:
        ingest_v3._driver_de_observacion()
    return info.value


def _comprobar_credencial(exc: IngestV3Error, ruta, motivo: str) -> None:
    assert exc.code == "GRAPH_CREDENTIAL_UNUSABLE", str(exc)
    assert exc.error_code == "GRAPH_CREDENTIAL_UNUSABLE"
    texto = str(exc)
    assert texto.startswith("GRAPH_CREDENTIAL_UNUSABLE:"), texto
    # NO se acusa a la conexion: esta declarada.
    assert "no tiene declarada" not in texto, texto
    assert "GRAPH_OBSERVATION_UNCONFIGURED" not in texto, texto
    # La causa: ruta del fichero y motivo.
    assert str(ruta) in texto, texto
    assert motivo in texto, texto
    # Permanente: un fichero mal puesto no se arregla reintentando.
    assert exc.retryable is False
    assert SECRETO not in texto


def test_fichero_ausente_dice_credencial_y_la_ruta(conexion):
    _comprobar_credencial(_fallo(), conexion, "No such file")


def test_modo_accesible_por_grupo_u_otros_dice_credencial_y_el_motivo(conexion):
    conexion.write_text(SECRETO, encoding="utf-8")
    conexion.chmod(0o644)
    _comprobar_credencial(_fallo(), conexion, "accesible por grupo u otros")


def test_fichero_vacio_dice_credencial_y_el_motivo(conexion):
    conexion.write_text("", encoding="utf-8")
    conexion.chmod(0o600)
    _comprobar_credencial(_fallo(), conexion, "vacio")


@pytest.mark.skipif(os.geteuid() == 0, reason="root lee cualquier fichero")
def test_fichero_ilegible_para_el_worker_dice_credencial_no_grafo_caido(conexion):
    """Pasa el `stat` y el modo, y falla la LECTURA: antes salia como
    `GRAPH_OBSERVATION_UNAVAILABLE` (reintentable, «el grafo no responde»)."""
    conexion.write_text(SECRETO, encoding="utf-8")
    conexion.chmod(0o200)
    exc = _fallo()
    _comprobar_credencial(exc, conexion, "Permission denied")
    assert exc.code != "GRAPH_OBSERVATION_UNAVAILABLE"


def test_contenido_no_utf8_no_vuelca_los_bytes(conexion):
    conexion.write_bytes(b"\xff\xfe" + SECRETO.encode() + b"\xff")
    conexion.chmod(0o600)
    exc = _fallo()
    assert exc.code == "GRAPH_CREDENTIAL_UNUSABLE", str(exc)
    assert str(conexion) in str(exc)
    assert SECRETO not in str(exc) and "\\xff" not in str(exc)


def test_conexion_no_declarada_sigue_siendo_la_de_siempre(monkeypatch):
    """El caso que SI es «no declarada» conserva su codigo y su frase."""
    for variable in ("S9K_NEO4J_URI", "S9K_NEO4J_USER", "S9K_NEO4J_PASSWORD_FILE"):
        monkeypatch.delenv(variable, raising=False)
    exc = _fallo()
    assert exc.code == "GRAPH_OBSERVATION_UNCONFIGURED", str(exc)
    assert "no tiene declarada la conexion" in str(exc)
    assert exc.retryable is False
    assert exc.detail is None


def test_control_positivo_credencial_valida_no_falla(conexion, monkeypatch):
    """Sin esto, rechazar TODA credencial pasaria igual de verde."""
    conexion.write_text(SECRETO + "\n", encoding="utf-8")
    conexion.chmod(0o600)

    class _Driver:
        def verify_connectivity(self):
            return None

        def close(self):
            return None

    driver = _Driver()
    monkeypatch.setattr(ingest_v3, "build_driver_factory",
                        lambda config: (lambda: driver))
    assert ingest_v3._driver_de_observacion() is driver


def test_el_job_guarda_error_code_coherente_con_el_mensaje(conexion, monkeypatch, tmp_path):
    """Por el camino real del worker: `error_code` relleno, mensaje veraz, sin
    reintento y sin fuga del secreto."""
    conexion.write_text(SECRETO, encoding="utf-8")
    conexion.chmod(0o644)

    def _handler(payload):
        ingest_v3._driver_de_observacion()
        raise AssertionError("no debia llegar aqui")

    monkeypatch.setitem(worker.HANDLERS, "ingest_v3", _handler)
    db = str(tmp_path / "jobs.db")
    job_store.init_db(db)
    job_id = job_store.create_job("leyenda", job_type="ingest_v3", payload={}, db_path=db)

    worker.run("worker-test", once=True, limit=1, db_path=db)

    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "failed", job
    assert job["attempts"] == 1, job  # permanente: sin reintento
    assert job["error_code"] == "GRAPH_CREDENTIAL_UNUSABLE", job
    assert job["error_message"].startswith("GRAPH_CREDENTIAL_UNUSABLE:"), job
    assert str(conexion) in job["error_message"]
    assert SECRETO not in str(job)


def test_el_codigo_nuevo_esta_en_el_catalogo_y_es_permanente():
    assert "GRAPH_CREDENTIAL_UNUSABLE" in ingest_v3.CODIGOS
    assert "GRAPH_CREDENTIAL_UNUSABLE" in ingest_v3.PERMANENTES
