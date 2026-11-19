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

import errno
import os

import pytest

from jobs import job_store, worker
from jobs.handlers import ingest_v3
from jobs.handlers.ingest_v3 import IngestV3Error
from knowledge_v3 import service_state
from knowledge_v3.driver_neo4j import DriverConfigError, read_secret

#: Longitud deliberadamente distinta de cualquier modo octal de los mensajes de
#: la politica (0600, 0640, 0644...): se comprueba que tampoco sale la longitud.
SECRETO = "S3CRETO-QUE-NO-DEBE-SALIR-9f3a-relleno-hasta-53-carac"
assert len(SECRETO) == 53


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


def _motivo_del_lector(ruta) -> str:
    """Lo que dice el LECTOR REAL (`driver_neo4j.read_secret`) de este fichero.

    Los tests no copian su frase: si #288 u otro cambio reescribe el texto o
    la politica, lo que se exige es que el job repita lo que diga el lector,
    no una cadena de hoy.
    """
    try:
        read_secret(str(ruta))
    except DriverConfigError as exc:
        return str(exc)
    except OSError as exc:  # fallo de LECTURA tras pasar la politica
        return exc.strerror
    raise AssertionError(f"el lector ACEPTA {ruta}: este caso no es un fallo")


def _comprobar_credencial(exc: IngestV3Error, ruta) -> str:
    assert exc.code == "GRAPH_CREDENTIAL_UNUSABLE", str(exc)
    assert exc.error_code == "GRAPH_CREDENTIAL_UNUSABLE"
    texto = str(exc)
    assert texto.startswith("GRAPH_CREDENTIAL_UNUSABLE:"), texto
    # NO se acusa a la conexion: esta declarada.
    assert "no tiene declarada" not in texto, texto
    assert "GRAPH_OBSERVATION_UNCONFIGURED" not in texto, texto
    # DECISION FIJADA (RC1-G02): el mensaje nombra la RUTA y el motivo...
    assert str(ruta) in texto, texto
    assert _motivo_del_lector(ruta) in texto, texto
    # ...y nunca el contenido ni la longitud del secreto.
    assert SECRETO not in texto
    assert str(len(SECRETO)) not in texto.replace(str(ruta), ""), texto
    # Permanente: un fichero mal puesto no se arregla reintentando.
    assert exc.retryable is False
    return texto


def _comprobar_politica(texto: str, ruta) -> None:
    """Cada incumplimiento que la AUTORIDAD encuentra en el fichero sale en el
    mensaje: la causa es la de la politica real, no una frase propia."""
    incumplimientos = service_state.inspect_secret_for_reading(ruta)
    assert incumplimientos, f"la politica ACEPTA {ruta}: el caso esta mal montado"
    for v in incumplimientos:
        assert v.detail in texto, (v.detail, texto)


def test_fichero_ausente_dice_credencial_y_la_ruta(conexion):
    _comprobar_credencial(_fallo(), conexion)


def test_modo_con_bits_de_otros_se_rechaza_con_el_motivo_de_la_politica(conexion):
    conexion.write_text(SECRETO, encoding="utf-8")
    conexion.chmod(0o644)
    _comprobar_politica(_comprobar_credencial(_fallo(), conexion), conexion)


@pytest.mark.skipif(os.geteuid() == 0, reason="root es el dueño admitido con bits de grupo")
def test_propio_0640_se_rechaza_porque_solo_root_del_grupo_de_servicio_puede(conexion):
    """Con la politica unica (#288), un 0640 PROPIO se rechaza por su DUEÑO
    (solo `root:<grupo de servicio>` admite bits de grupo), no por «accesible
    por grupo»."""
    conexion.write_text(SECRETO, encoding="utf-8")
    conexion.chmod(0o640)
    _comprobar_politica(_comprobar_credencial(_fallo(), conexion), conexion)


def test_fichero_vacio_dice_credencial_y_el_motivo(conexion):
    conexion.write_text("", encoding="utf-8")
    conexion.chmod(0o600)
    _comprobar_politica(_comprobar_credencial(_fallo(), conexion), conexion)


def test_enlace_simbolico_se_rechaza_aunque_el_destino_sea_valido(conexion, tmp_path):
    destino = tmp_path / "destino-real"
    destino.write_text(SECRETO, encoding="utf-8")
    destino.chmod(0o600)
    conexion.symlink_to(destino)
    _comprobar_politica(_comprobar_credencial(_fallo(), conexion), conexion)


@pytest.mark.skipif(os.geteuid() == 0, reason="root lee cualquier fichero")
def test_fichero_ilegible_para_el_worker_dice_credencial_no_grafo_caido(conexion):
    """Pasa la politica (0200 propio) y falla la LECTURA: antes salia como
    `GRAPH_OBSERVATION_UNAVAILABLE` (reintentable, «el grafo no responde»)."""
    conexion.write_text(SECRETO, encoding="utf-8")
    conexion.chmod(0o200)
    assert service_state.inspect_secret_for_reading(conexion) == []
    exc = _fallo()
    _comprobar_credencial(exc, conexion)
    assert exc.code != "GRAPH_OBSERVATION_UNAVAILABLE"


def test_contenido_no_utf8_no_vuelca_los_bytes(conexion):
    conexion.write_bytes(b"\xff\xfe" + SECRETO.encode() + b"\xff")
    conexion.chmod(0o600)
    exc = _fallo()
    assert exc.code == "GRAPH_CREDENTIAL_UNUSABLE", str(exc)
    assert exc.retryable is False
    assert str(conexion) in str(exc)
    assert SECRETO not in str(exc) and "\\xff" not in str(exc)


def test_la_politica_acepta_root_del_grupo_de_servicio_0640():
    """Control positivo del caso que deja el despliegue (`root:<grupo> 0640`).

    TECHO: sin root no se puede crear un fichero de root, asi que se ejerce la
    politica PURA de la autoridad con los valores de `stat`; el camino entero
    (fichero real -> ingesta) para este caso queda para el laboratorio.
    """
    gid = 4242
    assert service_state.secret_read_violations(
        0o100640, 0, gid, 10, euid=1000, service_gid=gid) == []
    # Contraste: el mismo modo con otro dueño o con otro grupo SI se rechaza.
    assert service_state.secret_read_violations(
        0o100640, 1000, gid, 10, euid=1000, service_gid=gid)
    assert service_state.secret_read_violations(
        0o100640, 0, gid + 1, 10, euid=1000, service_gid=gid)


# --- P3: el errno decide si es configuracion (permanente) o transitorio ---

_PERMANENTES = ("ENOENT", "ENOTDIR", "EACCES", "EPERM", "EISDIR", "ELOOP")
_TRANSITORIOS = ("EIO", "ESTALE", "ETIMEDOUT", "EAGAIN")


def _lector_que_falla(monkeypatch, nombre: str, *, en_el_stat: bool) -> None:
    """Sustituye el lector por uno que falla con ese errno, por la LECTURA
    (`OSError` crudo) o por el `stat` (envuelto en `DriverConfigError`, como
    hace `read_secret`)."""
    numero = getattr(errno, nombre)

    def _falla(ruta):
        error = OSError(numero, os.strerror(numero), ruta)
        if en_el_stat:
            raise DriverConfigError(
                f"no se pudo leer el fichero de contrasena {ruta!r}: {error.strerror}"
            ) from error
        raise error

    monkeypatch.setattr(ingest_v3, "read_secret", _falla)


@pytest.mark.parametrize("en_el_stat", [False, True], ids=["lectura", "stat"])
@pytest.mark.parametrize("nombre", _PERMANENTES)
def test_errno_de_configuracion_es_credencial_permanente(conexion, monkeypatch,
                                                         nombre, en_el_stat):
    _lector_que_falla(monkeypatch, nombre, en_el_stat=en_el_stat)
    exc = _fallo()
    assert exc.code == "GRAPH_CREDENTIAL_UNUSABLE", str(exc)
    assert exc.retryable is False
    assert str(conexion) in str(exc)
    assert os.strerror(getattr(errno, nombre)) in str(exc)


@pytest.mark.parametrize("en_el_stat", [False, True], ids=["lectura", "stat"])
@pytest.mark.parametrize("nombre", [n for n in _TRANSITORIOS if hasattr(errno, n)])
def test_errno_transitorio_sigue_siendo_reintentable(conexion, monkeypatch,
                                                     nombre, en_el_stat):
    """Un EIO/ESTALE/ETIMEDOUT/EAGAIN no es un fichero mal puesto: reintentar
    SI puede arreglarlo, como antes de RC1-G02."""
    _lector_que_falla(monkeypatch, nombre, en_el_stat=en_el_stat)
    exc = _fallo()
    assert exc.code == "GRAPH_OBSERVATION_UNAVAILABLE", str(exc)
    assert exc.retryable is True
    assert exc.error_code == "GRAPH_OBSERVATION_UNAVAILABLE"


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
    motivo = _motivo_del_lector(conexion)

    def _handler(payload):
        ingest_v3._driver_de_observacion()
        raise AssertionError("no debia llegar aqui")

    monkeypatch.setitem(worker.HANDLERS, "ingest_v3", _handler)
    db = str(tmp_path / "jobs.db")
    job_store.init_db(db)
    job_id = job_store.create_job("leyenda", job_type="ingest_v3", payload={}, db_path=db)

    worker.run("worker-test", once=True, limit=1, db_path=db)

    job = job_store.get_job(job_id, db_path=db)
    # Primero la que caza al mutante del worker; la causa por delante, en texto
    # fijo (el `repr` del job que imprime pytest no es estable).
    assert job["error_code"] == "GRAPH_CREDENTIAL_UNUSABLE", \
        f"RC1-G02: EL WORKER NO RELLENA ERROR_CODE: {job['error_code']!r}"
    assert SECRETO not in str(job), "RC1-G02: EL SECRETO SALE EN EL JOB"
    assert job["status"] == "failed", f"RC1-G02: EL JOB NO TERMINA EN FAILED: {job['status']!r}"
    assert job["attempts"] == 1, \
        f"RC1-G02: LA CREDENCIAL SE REINTENTA: attempts={job['attempts']!r}"
    assert job["error_message"].startswith("GRAPH_CREDENTIAL_UNUSABLE:"), \
        f"RC1-G02: MENSAJE CON OTRO CODIGO: {job['error_message']!r}"
    assert str(conexion) in job["error_message"], "RC1-G02: EL MENSAJE NO NOMBRA LA RUTA"
    assert motivo in job["error_message"], "RC1-G02: EL MENSAJE NO DA EL MOTIVO DEL LECTOR"


def test_el_codigo_nuevo_esta_en_el_catalogo_y_es_permanente():
    assert "GRAPH_CREDENTIAL_UNUSABLE" in ingest_v3.CODIGOS
    assert "GRAPH_CREDENTIAL_UNUSABLE" in ingest_v3.PERMANENTES, \
        "RC1-G02: LA CREDENCIAL SE DECLARA REINTENTABLE"
