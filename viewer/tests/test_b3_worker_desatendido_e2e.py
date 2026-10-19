# -*- coding: utf-8 -*-
"""B3 (USABLE-V1) · H-02 — WEB -> WORKER COMO SERVICIO -> WEB, sin un solo comando.

ESTADO
------
::

    CODE         PASS      visor real (TestClient) + worker REAL en su propio proceso
    CALIBRATION  PASS      scripts/calibracion/mutaciones_b3_worker.py
    RC-E2E       PENDING   systemd real, nginx, navegador, reinicio de maquina

EL CRITERIO FUNCIONAL (no «--loop se queda vivo»)
-------------------------------------------------
1. se crea un job desde ``/panel/operations`` por la web (formulario + CSRF);
2. sin ningun comando manual: la prueba NO llama a ``worker.run`` ni a
   ``run_ingest``; el unico proceso que procesa es el worker;
3. el worker arranca COMO LO ARRANCARIA SU UNIDAD: los flags son los de
   ``ExecStart`` de ``data-engine/systemd/s9-knowledge-worker.service``
   (leidos del fichero, no copiados aqui), su entorno es la plantilla
   ``deploy/config/worker.env.example`` (su EnvironmentFile) y su directorio
   el de ``WorkingDirectory``; lo detecta;
4. lo procesa;
5. persiste el resultado: ``jobs.db`` y el paquete de propuestas en el
   almacen de ``worker.env``, que es EL MISMO que resuelve el visor por
   ``review_paths``;
6. la web lo refleja: ``/jobs``, ``/jobs/{id}``, ``/panel/operations`` y las
   propuestas en ``/panel/review``;
7. reinicio del servicio (SIGTERM, como ``systemctl restart``: sale con rc=0);
8. otro job desde la web;
9. se procesa automaticamente.

SIN NEO4J: el abridor de conexion del handler lleva el grafo de mentira de
``grafo_doble`` (instalado por ``data-engine/app/tests/lanzador_worker_b3.py``
en el proceso del worker). La ingesta web es dry-run; con eso basta para B3.
TECHO: systemd de verdad (``enable``, ``Restart=always`` del gestor, usuario
del servicio), reinicio de maquina y Neo4j/apply no se ejercen aqui.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs_client
from app.chassis import FEATURE_SLOTS

SLOT_B = next(s for s in FEATURE_SLOTS if s.key == "B")
SLOT_C = next(s for s in FEATURE_SLOTS if s.key == "C")
FLAG_B = "S9K_PANEL_B_ENABLED"
FLAG_C = "S9K_PANEL_C_ENABLED"
PASSWORD = "Contrasena-De-Prueba-1"

REPO = Path(__file__).resolve().parents[2]
EJEMPLOS = REPO / "examples" / "ingesta-v3"
UNIDAD = REPO / "data-engine" / "systemd" / "s9-knowledge-worker.service"
WORKER_ENV_EJEMPLO = REPO / "deploy" / "config" / "worker.env.example"
VIEWER_ENV_EJEMPLO = REPO / "deploy" / "config" / "viewer.env.example"
LANZADOR = REPO / "data-engine" / "app" / "tests" / "lanzador_worker_b3.py"
STATE_ROOT_DE_PLANTILLA = "/var/lib/s9-knowledge"
CURRENT = "/opt/s9-knowledge/current"


# ---------------------------------------------------------------------------
# La unidad y sus plantillas, LEIDAS (no copiadas a mano en la prueba)
# ---------------------------------------------------------------------------

def _valor_unidad(clave: str) -> str:
    vals = [l.split("=", 1)[1] for l in UNIDAD.read_text(encoding="utf-8").splitlines()
            if l.startswith(clave + "=")]
    assert len(vals) == 1, (clave, vals)
    return vals[0]


def _execstart() -> tuple[dict, list]:
    tokens = shlex.split(_valor_unidad("ExecStart"))
    assert tokens[0] == "/usr/bin/env", tokens
    asignaciones, i = {}, 1
    while "=" in tokens[i] and not tokens[i].startswith("/"):
        k, v = tokens[i].split("=", 1)
        asignaciones[k] = v
        i += 1
    assert tokens[i + 1] == CURRENT + "/data-engine/app/jobs/worker.py", tokens
    return asignaciones, tokens[i + 2:]


def _env_de_plantilla(plantilla: Path, state_root: Path) -> dict:
    datos = {}
    for linea in plantilla.read_text(encoding="utf-8").splitlines():
        if linea.strip() and not linea.lstrip().startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            datos[k.strip()] = v.strip().replace(STATE_ROOT_DE_PLANTILLA, str(state_root))
    return datos


class _Servicio:
    """El worker arrancado COMO SU UNIDAD: flags de ExecStart, entorno de su
    EnvironmentFile, directorio de WorkingDirectory, proceso propio."""

    def __init__(self, tmp: Path, worker_env: dict, *, grafo: str = "doble",
                 flags_extra: tuple = (), nombre: str = "servicio"):
        asignaciones, flags = _execstart()
        self.flags = [*flags, *flags_extra]
        env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
        env.update(worker_env)
        env.update(asignaciones)
        env.update({"S9K_B3_GRAFO": grafo, "PYTHONDONTWRITEBYTECODE": "1"})
        wd = _valor_unidad("WorkingDirectory")
        assert wd.startswith(CURRENT + "/"), wd
        self.log = tmp / ("%s-%d.log" % (nombre, time.monotonic_ns()))
        self._fh = open(self.log, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, str(LANZADOR), *self.flags],
            cwd=str(REPO / wd[len(CURRENT) + 1:]), env=env,
            stdout=self._fh, stderr=subprocess.STDOUT,
        )

    def vivo(self) -> bool:
        return self.proc.poll() is None

    def parar(self, segundos: float = 30) -> int:
        """`systemctl stop`: SIGTERM y espera."""
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=segundos)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._fh.close()
        return self.proc.returncode

    def texto(self) -> str:
        if not self._fh.closed:  # tras `parar()` el fichero ya esta cerrado (F8)
            self._fh.flush()
        return self.log.read_text(encoding="utf-8", errors="replace")[-4000:]


def _esperar(condicion, segundos: float, paso: float = 0.3):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        valor = condicion()
        if valor:
            return valor
        time.sleep(paso)
    return condicion()


# ---------------------------------------------------------------------------
# Fixtures: app real, auth real, estado del despliegue en tmp
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _entorno_limpio():
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    yield
    for var in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_JOBS_DB",
                "S9K_INGEST_SOURCES_DIR", FLAG_B, FLAG_C):
        os.environ.pop(var, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def despliegue(tmp_path, monkeypatch) -> dict:
    """El estado del despliegue bajo un state root temporal.

    VISOR y WORKER salen de SUS plantillas productivas con el mismo state root:
    si las plantillas divergieran (cola o almacen), esta prueba se pondria roja.
    """
    raiz = tmp_path / "var-lib-s9k"
    visor = _env_de_plantilla(VIEWER_ENV_EJEMPLO, raiz)
    worker_env = _env_de_plantilla(WORKER_ENV_EJEMPLO, raiz)
    for var in ("S9K_JOBS_DB", "S9K_V3_REVIEW_PROPOSALS_DIR", "S9K_V3_REVIEW_DATABASE_PATH"):
        monkeypatch.setenv(var, visor[var])
    monkeypatch.setenv("S9K_V3_REVIEW_DECISIONS_PATH", str(raiz / "reviews-v3" / "decisions.jsonl"))
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last.json"))
    Path(visor["S9K_JOBS_DB"]).parent.mkdir(parents=True, exist_ok=True)
    from app.config import get_settings
    get_settings.cache_clear()

    fuentes = tmp_path / "fuentes"
    shutil.copytree(EJEMPLOS, fuentes)
    shutil.copy(fuentes / "nota-cofradia-de-ambar.md", fuentes / "nota-cofradia-segunda.md")
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(fuentes))
    os.environ[FLAG_B] = "true"
    os.environ[FLAG_C] = "true"
    return {"visor": visor, "worker_env": worker_env, "fuentes": fuentes, "tmp": tmp_path}


@pytest.fixture
def operador(despliegue, tmp_path):
    from app.auth import db as auth_db_mod
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session
    from app.main import app

    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    get_auth_settings.cache_clear()
    auth_db_mod.ensure_migrated(db_path)
    with auth_db_mod.get_conn(db_path) as conn:
        user = auth_db_mod.create_user(conn, username="b3_operador", display_name="B3",
                                       password_hash=hash_password(PASSWORD), role="admin")
        auth_db_mod.update_user(conn, user.id, must_change_password=False)
        user = auth_db_mod.get_user_by_id(conn, user.id)
        token, _ = create_session(conn, user)
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    c.headers.update({"accept": "text/html"})
    return c


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]*)"', html)
    assert m, "el formulario no trae token CSRF"
    return m.group(1)


def _opciones(html: str) -> list[str]:
    bloque = re.search(r'data-role="selector-fuente".*?</select>', html, re.S)
    assert bloque, "no hay selector de fuente en la pantalla"
    return re.findall(r'<option value="([^"]+)"', bloque.group(0))


def _pedir_ingesta(operador, despliegue, indice: int = 0) -> tuple[str, str]:
    """Paso 1: el operador pide la ingesta EN LA WEB. Devuelve (job_id, destino)."""
    store = jobs_client._load_job_store()
    db = despliegue["visor"]["S9K_JOBS_DB"]
    antes = {j["job_id"] for j in store.list_jobs(db_path=db)} if Path(db).exists() else set()
    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    opciones = _opciones(pantalla.text)
    assert len(opciones) > indice, opciones
    envio = operador.post("/panel/operations/ingestas",
                          data={"fuente": opciones[indice], "csrf_token": _csrf(pantalla.text)})
    assert envio.status_code == 303, envio.text[:300]
    nuevos = [j for j in store.list_jobs(db_path=db) if j["job_id"] not in antes]
    assert len(nuevos) == 1 and nuevos[0]["status"] == "pending", nuevos
    return nuevos[0]["job_id"], envio.headers["location"]


def _job(despliegue, job_id: str) -> dict:
    return jobs_client._load_job_store().get_job(job_id, db_path=despliegue["visor"]["S9K_JOBS_DB"])


def _propuestas_de(almacen: Path, job_id: str) -> list[str]:
    ids = []
    for fichero in sorted(almacen.glob("*.json")) if almacen.exists() else []:
        paquete = json.loads(fichero.read_text(encoding="utf-8"))
        if (paquete.get("run") or {}).get("job_id") == job_id:
            ids.extend(item["proposal_id"] for item in paquete.get("items", []))
    return ids


def _fila_de_operations(html: str, job_id: str) -> str:
    m = re.search(r'<tr data-job-id="%s">(.*?)</tr>' % re.escape(job_id), html, re.S)
    assert m, "el job %s no aparece en la cola de /panel/operations" % job_id
    return m.group(1)


# ===========================================================================
# EL RECORRIDO: los nueve pasos
# ===========================================================================

def test_un_trabajo_creado_desde_la_web_se_procesa_sin_intervencion_manual(
        operador, despliegue):
    from app.services.v3_review import default_proposals_dir

    tmp = despliegue["tmp"]
    worker_env = despliegue["worker_env"]
    almacen = Path(worker_env["S9K_V3_REVIEW_PROPOSALS_DIR"])
    # El almacen donde escribe el worker ES el que el visor resuelve (review_paths).
    assert default_proposals_dir() == almacen, (default_proposals_dir(), almacen)
    assert worker_env["S9K_JOBS_DB"] == despliegue["visor"]["S9K_JOBS_DB"]

    # 1. la web encola
    job1, destino1 = _pedir_ingesta(operador, despliegue, 0)

    # 2-4. el SERVICIO lo detecta y lo procesa; nadie llama a nada mas
    servicio = _Servicio(tmp, worker_env, nombre="arranque-1")
    try:
        assert "--loop" in servicio.flags and "--limit" not in servicio.flags, servicio.flags
        hecho = _esperar(lambda: _job(despliegue, job1)["status"] in ("complete", "failed"), 120)
        estado1 = _job(despliegue, job1)
        assert hecho and estado1["status"] == "complete", (
            "el servicio no proceso el job pedido desde la web: %s\n%s"
            % (estado1, servicio.texto()))
        assert servicio.vivo(), "el servicio termino tras procesar:\n" + servicio.texto()

        # 5. persistencia: jobs.db y el paquete de propuestas en el almacen declarado
        resultado = json.loads(estado1["result_json"])
        assert resultado["handler"] == "ingest_v3" and resultado["revision"], resultado
        propuestas1 = _propuestas_de(almacen, job1)
        assert propuestas1, "el worker no dejo propuestas de %s en %s" % (job1, almacen)
        workspace = resultado["revision"]["workspace"]

        # 6. la web lo refleja
        lista = operador.get("/jobs")
        assert lista.status_code == 200 and job1[:8] in lista.text, lista.status_code
        detalle = operador.get("/jobs/%s" % job1)
        assert detalle.status_code == 200 and "complete" in detalle.text
        acuse = operador.get(destino1)
        assert acuse.status_code == 200
        assert 'data-resultado-estado="ok"' in acuse.text, acuse.text[-1500:]
        fila = _fila_de_operations(operador.get(SLOT_B.prefix).text, job1)
        assert 'data-status="complete"' in fila, fila
        revision = operador.get("%s?workspace=%s" % (SLOT_C.prefix, workspace))
        assert revision.status_code == 200
        ausentes = [p for p in propuestas1 if p not in revision.text]
        assert not ausentes, "propuestas de la corrida que /panel/review no ensena: %s" % ausentes

        # 7. reinicio del servicio: parada limpia, como `systemctl restart`
        rc = servicio.parar()
        assert rc == 0, "la parada del servicio no fue limpia (rc=%s):\n%s" % (rc, servicio.texto())
    finally:
        servicio.parar()

    servicio = _Servicio(tmp, worker_env, nombre="arranque-2")
    try:
        # 8. otro job desde la web
        job2, destino2 = _pedir_ingesta(operador, despliegue, 1)
        # 9. se procesa solo
        hecho = _esperar(lambda: _job(despliegue, job2)["status"] in ("complete", "failed"), 120)
        estado2 = _job(despliegue, job2)
        assert hecho and estado2["status"] == "complete", (estado2, servicio.texto())
        assert _propuestas_de(almacen, job2), "sin propuestas del segundo job"
        assert 'data-resultado-estado="ok"' in operador.get(destino2).text
        assert _job(despliegue, job1)["status"] == "complete", "el primer job cambio"
    finally:
        assert servicio.parar() == 0, servicio.texto()


# ===========================================================================
# NEGATIVOS
# ===========================================================================

def test_con_el_worker_parado_el_trabajo_espera_en_la_cola(operador, despliegue):
    """Worker parado: `pending`, visible, sin error; y al arrancar se procesa."""
    job_id, destino = _pedir_ingesta(operador, despliegue, 0)
    time.sleep(4)
    estado = _job(despliegue, job_id)
    assert estado["status"] == "pending" and not estado["error_message"], estado
    assert "Se ha solicitado la ingesta" in operador.get(destino).text
    fila = _fila_de_operations(operador.get(SLOT_B.prefix).text, job_id)
    assert 'data-status="pending"' in fila and 'data-has-error="false"' in fila, fila

    servicio = _Servicio(despliegue["tmp"], despliegue["worker_env"])
    try:
        assert _esperar(lambda: _job(despliegue, job_id)["status"] == "complete", 120), (
            _job(despliegue, job_id), servicio.texto())
    finally:
        servicio.parar()


def test_un_error_permanente_se_ve_en_la_web_y_no_se_reintenta(operador, despliegue):
    job_id, destino = _pedir_ingesta(operador, despliegue, 0)
    for fichero in despliegue["fuentes"].glob("*.md"):
        fichero.unlink()                    # fallo REAL del handler: fuente ausente
    servicio = _Servicio(despliegue["tmp"], despliegue["worker_env"])
    try:
        assert _esperar(lambda: _job(despliegue, job_id)["status"] == "failed", 60), (
            _job(despliegue, job_id), servicio.texto())
        time.sleep(3)
    finally:
        servicio.parar()
    estado = _job(despliegue, job_id)
    assert estado["attempts"] == 1, "un error permanente no se reintenta: %s" % estado
    acuse = operador.get(destino).text
    assert 'data-resultado-estado="error"' in acuse
    assert "El paquete de la fuente no es valido." in acuse
    fila = _fila_de_operations(operador.get(SLOT_B.prefix).text, job_id)
    assert 'data-status="failed"' in fila and 'data-has-error="true"' in fila, fila
    assert "SOURCE_PACKAGE_INVALID" in operador.get("/jobs").text


def test_un_error_transitorio_reintenta_acotado_y_acaba_en_error_visible(operador, despliegue):
    """GRAPH_OBSERVATION_UNAVAILABLE (reintentable): attempts crece, la web lo
    marca, y al agotar max_attempts el job queda `failed`, nunca en bucle.

    Unica desviacion de la unidad, DECLARADA: retroceso 0 para no esperar
    30 s + 60 s de reloj.
    """
    job_id, destino = _pedir_ingesta(operador, despliegue, 0)
    servicio = _Servicio(despliegue["tmp"], despliegue["worker_env"], grafo="caido",
                         flags_extra=("--retry-backoff-seconds", "0"))
    try:
        assert _esperar(lambda: _job(despliegue, job_id)["status"] == "failed", 60), (
            _job(despliegue, job_id), servicio.texto())
        time.sleep(3)
        assert servicio.vivo(), "el servicio murio por un error del handler"
    finally:
        servicio.parar()
    estado = _job(despliegue, job_id)
    assert estado["attempts"] == estado["max_attempts"] == 3, estado
    acuse = operador.get(destino).text
    assert 'data-resultado-estado="error"' in acuse
    assert "No se ha podido consultar el grafo" in acuse
    fila = _fila_de_operations(operador.get(SLOT_B.prefix).text, job_id)
    assert 'data-attempts="3"' in fila and 'data-has-error="true"' in fila, fila
