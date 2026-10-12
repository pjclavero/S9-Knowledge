# -*- coding: utf-8 -*-
"""B3 (USABLE-V1) · H-02 — el worker de la cola es operable DESATENDIDO.

ESTADO
------
::

    CODE         PASS      worker REAL en subproceso contra jobs.db temporal
    CALIBRATION  PASS      scripts/calibracion/mutaciones_b3_worker.py
    RC-E2E       PENDING   systemd real, reinicio de maquina

LOS DEFECTOS, REPRODUCIDOS ANTES DEL CAMBIO (base 7841f85)
---------------------------------------------------------
* ``timeout 10 worker.py --loop --sleep-seconds 1`` -> rc=0 al instante,
  ``Jobs procesados: 0`` (`if once or limit` con ``--limit`` = 1 por defecto);
  solo ``--loop --limit 0`` vivia (rc=124).
* ``release_stale_jobs`` x5 seguidas sobre el mismo job -> ``pending``,
  ``attempts`` = 0: un job que mata al proceso se reintenta para siempre.
* ``next_retry_at`` en 2999 -> el job se reclamaba igual.
* ``mark_cancelled`` y despues ``mark_complete`` -> ``complete``.
* ``heartbeat()`` sin un solo llamador fuera de su envoltorio.

COMO SE MIDE
------------
Los casos de comportamiento del DAEMON corren el worker REAL
(``data-engine/app/jobs/worker.py`` o ``lanzador_worker_b3.py``, que llama al
mismo ``worker.main``) en un PROCESO PROPIO: se le mata con SIGKILL, se le
para con SIGTERM y se le re-arranca como haria ``Restart=always``. El rc se
lee del proceso, no de un envoltorio. Cada caso usa su propio ``jobs.db``.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from jobs import job_store, worker

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
WORKER_PY = APP / "jobs" / "worker.py"
LANZADOR = Path(__file__).with_name("lanzador_worker_b3.py")


# ---------------------------------------------------------------------------
# Utillaje
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path) -> str:
    ruta = str(tmp_path / "jobs.db")
    job_store.init_db(ruta)
    return ruta


def _entorno(db: str, contador: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    env.update({
        "S9K_JOBS_DB": db,
        "PYTHONDONTWRITEBYTECODE": "1",
        "S9K_B3_HANDLERS_DE_PRUEBA": "1",
        "S9K_B3_CONTADOR_DIR": str(contador),
    })
    return env


class _Worker:
    """Un worker REAL en su propio proceso, con su log en fichero."""

    def __init__(self, tmp: Path, db: str, *flags: str, nombre: str = "w"):
        self.contador = tmp / "contador"
        self.contador.mkdir(exist_ok=True)
        self.log = tmp / ("%s-%d.log" % (nombre, time.monotonic_ns()))
        self._fh = open(self.log, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, str(LANZADOR), *flags], cwd=str(REPO / "data-engine"),
            env=_entorno(db, self.contador), stdout=self._fh, stderr=subprocess.STDOUT,
        )

    def invocaciones(self, handler: str) -> int:
        ruta = self.contador / handler
        return ruta.read_text(encoding="utf-8").count("x") if ruta.exists() else 0

    def esperar_salida(self, segundos: float) -> int | None:
        try:
            return self.proc.wait(timeout=segundos)
        except subprocess.TimeoutExpired:
            return None

    def parar(self) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._fh.close()
        return self.proc.returncode

    def texto(self) -> str:
        self._fh.flush()
        return self.log.read_text(encoding="utf-8", errors="replace")


def _esperar(condicion, segundos: float, paso: float = 0.2):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        valor = condicion()
        if valor:
            return valor
        time.sleep(paso)
    return condicion()


def _job(db: str, job_id: str) -> dict:
    return job_store.get_job(job_id, db_path=db)


# ===========================================================================
# 1. `--loop` ES UN DAEMON; `--once` NO
# ===========================================================================

def test_loop_es_un_daemon_con_la_cola_vacia(db):
    """El defecto de origen: `--loop` terminaba al instante con rc=0.

    Se mide con `timeout` REAL: si el worker sigue vivo al vencer el plazo,
    `timeout` devuelve 124. Un rc=0 aqui es exactamente el defecto.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    inicio = time.monotonic()
    r = subprocess.run(
        ["timeout", "6", sys.executable, str(WORKER_PY), "--loop", "--sleep-seconds", "1",
         "--db", db],
        capture_output=True, text=True, env=env, timeout=60,
    )
    duracion = time.monotonic() - inicio
    assert r.returncode == 124, (
        "DAEMON ROTO: `--loop` con la cola vacia termino solo (rc=%s en %.1fs) en vez "
        "de seguir esperando trabajo hasta que `timeout` lo parase (rc=124).\n%s"
        % (r.returncode, duracion, r.stdout[-2000:] + r.stderr[-2000:]))
    assert duracion >= 5.5, "el worker no vivio el plazo medido: %.1fs" % duracion


def test_once_termina_con_rc0(db):
    """Control del control: `--once` SI termina (no se ha roto el modo manual)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    job_id = job_store.create_job("leyenda", job_type="noop", db_path=db)
    r = subprocess.run(
        ["timeout", "30", sys.executable, str(WORKER_PY), "--once", "--db", db],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == "Jobs procesados: 1", r.stdout
    assert _job(db, job_id)["status"] == "complete"


def test_el_daemon_atiende_un_job_que_llega_despues(tmp_path, db):
    """Lo que hace util al daemon: el job llega con el worker YA corriendo."""
    w = _Worker(tmp_path, db, "--loop", "--sleep-seconds", "1")
    try:
        time.sleep(1.5)
        assert w.proc.poll() is None, "el daemon termino antes de llegar trabajo:\n" + w.texto()
        job_id = job_store.create_job("leyenda", job_type="echo", payload={"m": 1}, db_path=db)
        final = _esperar(lambda: _job(db, job_id)["status"] == "complete", 20)
        assert final, "el daemon no proceso el job: %s\n%s" % (_job(db, job_id), w.texto())
        assert w.proc.poll() is None, "el daemon termino tras procesar un job"
    finally:
        rc = w.parar()
    assert rc == 0, "SIGTERM no paro limpio el daemon (rc=%s):\n%s" % (rc, w.texto())


def test_sigterm_con_un_job_en_curso_lo_termina_antes_de_salir(tmp_path, db):
    """Parar el servicio no deja un `running` huerfano si el job acaba a tiempo."""
    job_id = job_store.create_job("leyenda", job_type="b3_dormir",
                                  payload={"segundos": 3}, db_path=db)
    w = _Worker(tmp_path, db, "--loop", "--sleep-seconds", "1")
    try:
        assert _esperar(lambda: _job(db, job_id)["status"] == "running", 15), w.texto()
        w.proc.send_signal(signal.SIGTERM)
        rc = w.esperar_salida(30)
    finally:
        w.parar()
    assert rc == 0, "rc=%s\n%s" % (rc, w.texto())
    assert _job(db, job_id)["status"] == "complete", _job(db, job_id)


# ===========================================================================
# 2. WORKER PARADO: el job ESPERA, no desaparece ni falla
# ===========================================================================

def test_worker_parado_el_job_sigue_pending(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    time.sleep(2)
    job = _job(db, job_id)
    assert job is not None, "el job desaparecio sin worker"
    assert job["status"] == "pending", job
    assert job["attempts"] == 0 and job["error_message"] is None, job


# ===========================================================================
# 3. STALE GASTA UN INTENTO; next_retry_at SE RESPETA (nivel cola)
# ===========================================================================

def test_stale_gasta_un_intento_y_acaba_en_failed(db):
    """Cinco liberaciones seguidas: antes `pending` con attempts=0 (bucle)."""
    job_id = job_store.create_job("leyenda", job_type="echo", max_attempts=3, db_path=db)
    vistos = []
    for _ in range(5):
        if job_store.claim_next_job("w-muerto", db_path=db) is None:
            break
        time.sleep(2.2)  # locked_at se trunca a segundos
        job_store.release_stale_jobs(1, db_path=db)
        j = _job(db, job_id)
        vistos.append((j["status"], j["attempts"]))
    assert vistos == [("pending", 1), ("pending", 2), ("failed", 3)], (
        "STALE SIN INTENTOS: la liberacion de un job huerfano no gasta intentos; "
        "un job que mata al worker volveria a la cola para siempre: %s" % vistos)


def test_un_reintento_con_next_retry_at_futuro_no_se_reclama(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    assert job_store.claim_next_job("w1", db_path=db)["job_id"] == job_id
    assert job_store.mark_failed(job_id, "transitorio", retry=True, db_path=db,
                                 retry_delay_seconds=3600, locked_by="w1")
    j = _job(db, job_id)
    assert j["status"] == "pending" and j["next_retry_at"], j
    assert job_store.claim_next_job("w2", db_path=db) is None, (
        "NEXT_RETRY_AT IGNORADO: se reclamo un job cuyo reintento es dentro de una hora")
    job_store.update_job(job_id, next_retry_at="2000-01-01T00:00:00Z", db_path=db)
    assert job_store.claim_next_job("w2", db_path=db)["job_id"] == job_id, (
        "un reintento vencido tiene que volver a reclamarse")


def test_cerrar_un_job_ajeno_no_tiene_efecto(db):
    """La guardia de propietario: cancelado no vuelve a complete."""
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("w1", db_path=db)
    job_store.mark_cancelled(job_id, db_path=db)
    assert job_store.mark_complete(job_id, result={"x": 1}, db_path=db, locked_by="w1") is False
    assert _job(db, job_id)["status"] == "cancelled"


# ===========================================================================
# 4. ERROR DEL HANDLER: observable, intentos acotados, sin bucle (subproceso)
# ===========================================================================

def test_handler_con_error_reintenta_acotado_y_queda_failed(tmp_path, db):
    job_id = job_store.create_job("leyenda", job_type="b3_fallar", max_attempts=3, db_path=db)
    w = _Worker(tmp_path, db, "--loop", "--sleep-seconds", "1", "--retry-backoff-seconds", "0")
    try:
        final = _esperar(lambda: _job(db, job_id)["status"] == "failed", 30)
        assert final, ("HANDLER QUE SE TRAGA EL ERROR: el job no llego a `failed` (%s)\n%s"
                       % (_job(db, job_id), w.texto()))
        time.sleep(3)  # ¿sigue reintentando despues de `failed`?
        invocaciones = w.invocaciones("fallar")
        vivo = w.proc.poll() is None
    finally:
        w.parar()
    j = _job(db, job_id)
    assert j["attempts"] == 3, j
    assert j["error_message"] == "B3_FALLO_DE_PRUEBA: el handler ha fallado a proposito", j
    assert invocaciones == 3, "el handler corrio %s veces: sin bucle son 3" % invocaciones
    assert vivo, "el daemon murio por el error de un handler"


def test_el_reintento_respeta_el_retroceso(tmp_path, db):
    """Con retroceso, el segundo intento NO es inmediato (next_retry_at manda)."""
    job_id = job_store.create_job("leyenda", job_type="b3_fallar", max_attempts=3, db_path=db)
    w = _Worker(tmp_path, db, "--loop", "--sleep-seconds", "1", "--retry-backoff-seconds", "30")
    try:
        assert _esperar(lambda: w.invocaciones("fallar") >= 1, 20), w.texto()
        time.sleep(4)
        invocaciones = w.invocaciones("fallar")
    finally:
        w.parar()
    j = _job(db, job_id)
    assert invocaciones == 1, (
        "NEXT_RETRY_AT IGNORADO: con 30 s de retroceso el handler corrio %s veces en 4 s"
        % invocaciones)
    assert j["status"] == "pending" and j["attempts"] == 1 and j["next_retry_at"], j


# ===========================================================================
# 5. WORKER MATADO A MITAD: stale -> attempts+1 -> se re-procesa
# ===========================================================================

def test_worker_matado_a_mitad_se_libera_y_se_reprocesa(tmp_path, db):
    job_id = job_store.create_job("leyenda", job_type="b3_dormir_una_vez",
                                  payload={"segundos": 120}, max_attempts=3, db_path=db)
    flags = ("--loop", "--sleep-seconds", "1", "--release-stale-seconds", "2",
             "--retry-backoff-seconds", "0")
    a = _Worker(tmp_path, db, *flags, nombre="a")
    try:
        assert _esperar(lambda: _job(db, job_id)["status"] == "running", 15), a.texto()
        a.proc.kill()                      # SIGKILL a mitad del job
        a.proc.wait(timeout=10)
    finally:
        a.parar()
    assert _job(db, job_id)["status"] == "running", "el job huerfano debia quedar running"

    b = _Worker(tmp_path, db, *flags, nombre="b")   # «Restart=always»
    try:
        final = _esperar(lambda: _job(db, job_id)["status"] == "complete", 30)
    finally:
        b.parar()
    j = _job(db, job_id)
    assert final, "el huerfano no se libero ni re-proceso: %s\n%s" % (j, b.texto())
    assert j["attempts"] == 1, "morir a mitad de un job tiene que gastar un intento: %s" % j
    assert json.loads(j["result_json"])["invocacion"] == 2, j


def test_un_job_que_mata_al_worker_agota_intentos_y_falla(tmp_path, db):
    """El bucle infinito de H-02: cada intento tumba el proceso."""
    job_id = job_store.create_job("leyenda", job_type="b3_matar", max_attempts=2, db_path=db)
    flags = ("--loop", "--sleep-seconds", "1", "--release-stale-seconds", "1",
             "--retry-backoff-seconds", "0")
    estados = []
    contador = tmp_path / "contador"
    for n in range(5):                       # cinco «reinicios» de systemd
        if _job(db, job_id)["status"] == "failed":
            break
        w = _Worker(tmp_path, db, *flags, nombre="r%d" % n)
        try:
            w.esperar_salida(8)
        finally:
            w.parar()
        estados.append((_job(db, job_id)["status"], _job(db, job_id)["attempts"]))
    j = _job(db, job_id)
    invocaciones = (contador / "matar").read_text().count("x") if (contador / "matar").exists() else 0
    assert j["status"] == "failed", (
        "STALE SIN INTENTOS: tras 5 reinicios el job que mata al worker sigue %s "
        "(trayectoria %s): bucle infinito" % (j["status"], estados))
    assert j["attempts"] == 2 and invocaciones == 2, (j, invocaciones, estados)
    assert j["error_message"] == "fallido: worker sin actividad (stale) y sin reintentos", j


# ===========================================================================
# 6. CANCELACION COOPERATIVA Y LATIDO (en proceso: hace falta tocar el handler)
# ===========================================================================

def test_cancelado_mientras_corre_no_se_sobrescribe(monkeypatch, db):
    def cancelarse(payload, *, job_id=None):
        job_store.mark_cancelled(job_id, db_path=db)
        return {"ok": True}

    monkeypatch.setitem(worker.HANDLERS, "b3_cancelarse", cancelarse)
    job_id = job_store.create_job("leyenda", job_type="b3_cancelarse", db_path=db)
    assert worker.process_one("w-coop", None, None, db) is True
    assert _job(db, job_id)["status"] == "cancelled", (
        "CANCELACION NO COOPERATIVA: el worker sobrescribio un job cancelado: %s"
        % _job(db, job_id))


def test_el_latido_mantiene_vivo_un_job_largo(monkeypatch, db):
    """Sin latido, un job vivo y largo se liberaria como huerfano."""
    monkeypatch.setitem(worker.HANDLERS, "b3_lento", lambda payload: time.sleep(4.5) or {"ok": 1})
    job_id = job_store.create_job("leyenda", job_type="b3_lento", db_path=db)
    hilo = threading.Thread(target=worker.process_one,
                            args=("w-lento", None, None, db, 0, 0.5))
    hilo.start()
    try:
        time.sleep(3.5)
        liberados = job_store.release_stale_jobs(2, db_path=db)
    finally:
        hilo.join(timeout=20)
    assert job_id not in liberados, "un job con latido se libero como huerfano"
    assert _job(db, job_id)["status"] == "complete", _job(db, job_id)
