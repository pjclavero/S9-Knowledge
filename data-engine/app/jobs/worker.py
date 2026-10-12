#!/usr/bin/env python3
"""Worker genérico de la cola de jobs (Fase v0.2.4 "jobs worker and jobs panel").

Reclama jobs 'pending' de job_store, los despacha a un handler según
`job_type`, y marca el resultado (complete/failed/skipped). Los handlers
reales de multimedia (media_probe, audio_extract, transcribe, ...) se
añadirán en fases futuras.

Handlers registrados hoy:
  * `noop`, `echo`  — de prueba, validan la cola sin tocar datos reales;
  * `ingest_v3`     — REAL: ingesta V3 de una fuente, en dry-run. Reutiliza
                      `knowledge_v3.pipeline.ingest_cli.run_ingest`, el mismo
                      núcleo que invoca la CLI.

LEE Neo4j, PERO NO ESCRIBE (Slice 2 · Corte 5). La distinción es del código,
no de la buena voluntad: `ingest_v3` corre con `apply=False` --que es lo único
que gobierna la escritura, porque `run_ingest` pasa
`writer_driver=driver if apply else None`-- y abre un driver que usa para UNA
cosa: la consulta de sólo lectura del catálogo del workspace. Esa observación
es lo que marca las anclas del plan como `observed`, y sin ella el sellado
omite toda proyección con `PROJECTION_ANCHOR_NOT_OBSERVED`.

Hasta este corte esta línea decía «NO escribe en Neo4j: [...] y sin driver», y
la segunda mitad dejó de ser cierta. Se corrige aquí porque un comentario que
afirma lo contrario de lo que hace el código manda a perseguir un fantasma.

La frontera de confianza del worker se ensancha, por tanto, a LECTURA del
grafo: necesita conectividad, credencial y contexto, y falla cerrado si le
falta cualquiera (ver `deploy/README.md`).

Ejecución manual:
    python data-engine/app/jobs/worker.py --once --limit 1
    python data-engine/app/jobs/worker.py --loop --sleep-seconds 5

Ejecución desatendida (B3 · H-02): la unidad canónica
`data-engine/systemd/s9-knowledge-worker.service`, que instala `deploy.sh`
(y el rol Ansible `systemd`, copiando ESE mismo fichero), corre `--loop` con
`--release-stale-seconds` y se reinicia sola (`Restart=always`).
"""
from __future__ import annotations

import inspect
import argparse
import logging
import signal
import sys
import threading
import uuid
from pathlib import Path

# ── Bootstrap de path: data-engine/app como raíz de imports (top-level) ───────
_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from jobs import job_store  # noqa: E402

log = logging.getLogger("jobs.worker")


class JobHandlerError(RuntimeError):
    """Error controlado de un handler; el worker lo captura y marca failed."""


# ── Handlers de prueba ─────────────────────────────────────────────────────
def handle_noop(payload: dict) -> dict:
    """No hace nada; sirve para probar la cola end-to-end."""
    return {"ok": True, "handler": "noop"}


def handle_echo(payload: dict) -> dict:
    """Devuelve el payload recibido tal cual, como result."""
    return {"echo": payload}


# ── Handlers REALES ────────────────────────────────────────────────────────
# `ingest_v3` es el primer trabajo de produccion que entra en esta cola. Antes
# solo habia handlers de prueba, y por eso el panel de operaciones pintaba
# fielmente una cola en la que nada real podia entrar.
#
# El import es PEREZOSO y tolerante: el worker de la cola generica tiene que
# poder arrancar en un despliegue donde `knowledge_v3` no este instalado (el
# visor y el motor se despliegan por separado). Si no se puede importar, el
# job_type simplemente no tiene handler y `dispatch` lo marca 'skipped' con su
# mensaje — que es exactamente el comportamiento correcto y ya existente, no
# un fallo nuevo que haya que inventar.
def _cargar_ingest_v3():
    try:
        from jobs.handlers.ingest_v3 import handle_ingest_v3

        return handle_ingest_v3
    except Exception:  # noqa: BLE001 - motor ausente: la cola sigue viva
        log.warning("handler 'ingest_v3' no disponible en este despliegue",
                    exc_info=True)
        return None


HANDLERS = {
    "noop": handle_noop,
    "echo": handle_echo,
}

_INGEST_V3 = _cargar_ingest_v3()
if _INGEST_V3 is not None:
    HANDLERS["ingest_v3"] = _INGEST_V3


def dispatch(job: dict) -> dict:
    """Ejecuta el handler correspondiente a job['job_type']. Lanza JobHandlerError
    si no hay handler registrado (el llamador decide si eso es 'skipped' o 'failed').
    """
    job_type = job.get("job_type")
    handler = HANDLERS.get(job_type)
    if handler is None:
        raise JobHandlerError(f"job_type '{job_type}' no tiene handler implementado todavía")

    payload = {}
    if job.get("payload_json"):
        import json

        try:
            payload = json.loads(job["payload_json"])
        except (TypeError, ValueError) as exc:
            raise JobHandlerError(f"payload_json inválido: {exc}") from exc

    # LA IDENTIDAD DE LA CORRIDA LA PONE LA COLA, NO EL PAYLOAD.
    #
    # El payload lo construye el panel al encolar y es dato del operador; el
    # `job_id` es dato del almacen de jobs. Por eso NO se mete dentro del
    # payload: hacerlo se lo cuela a TODOS los handlers como si fuera un campo
    # que el operador envio (medido: el handler `echo` lo devolvia en su eco),
    # y ademas dejaria que un payload con `job_id` propio atribuyera una
    # propuesta a una corrida que no la produjo.
    #
    # Se entrega como ARGUMENTO, y solo a quien lo DECLARA en su firma. Un
    # handler que no lo pide se sigue llamando exactamente igual que antes.
    if "job_id" in inspect.signature(handler).parameters:
        return handler(payload, job_id=job.get("job_id"))
    return handler(payload)


class ColaInutilizable(RuntimeError):
    """La cola no se puede escribir (solo lectura, corrupta, inaccesible).

    B3 · H-02 (revision independiente, F2): con un `jobs.db` de solo lectura
    el daemon seguia `active`, cada vuelta fallaba en el log y el job se
    quedaba `pending` sin error en la web: un silencio en verde. Ahora el
    worker SALE con rc != 0 (al arrancar o tras `max_vueltas_fallidas`
    vueltas fallidas seguidas) para que `Restart=always`, `systemctl
    is-active` y `deploy.sh::worker_activo` lo vean.
    """


#: Vueltas fallidas SEGUIDAS tras las que el daemon se rinde (rc=3).
MAX_VUELTAS_FALLIDAS = 5

#: Techo del retroceso entre reintentos (segundos). Un retroceso sin techo
#: dejaria un job "pendiente" durante horas sin que nada lo explique.
RETRY_BACKOFF_MAX_SECONDS = 3600


def retroceso(base_seconds: float, intentos_previos: int) -> float:
    """Espera antes del siguiente intento: ``base * 2**intentos_previos``, con techo.

    ``base_seconds <= 0`` es "reintento inmediato" (el comportamiento de
    siempre para quien llama a ``run`` sin pedir otra cosa).
    """
    if not base_seconds or base_seconds <= 0:
        return 0
    return min(RETRY_BACKOFF_MAX_SECONDS, base_seconds * (2 ** max(0, intentos_previos)))


class _Latido:
    """Heartbeat del job en curso, en un hilo aparte (B3 · H-02).

    `job_store.heartbeat` existia y NADIE lo llamaba: un job largo sin latido
    es indistinguible de uno huerfano, asi que con `--release-stale-seconds`
    un worker vivo veria su propio trabajo liberado y re-reclamado. El latido
    refresca `locked_at` mientras el handler corre; si deja de surtir efecto
    (el job ya no es de este worker: cancelado o liberado) lo anota en
    `perdido`, y el resultado del handler NO se escribe encima.
    """

    def __init__(self, job_id: str, worker_id: str, db_path: str, cada: float):
        self.job_id = job_id
        self.worker_id = worker_id
        self.db_path = db_path
        self.cada = cada
        self.perdido = False
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, name="latido-%s" % job_id[:8],
                                      daemon=True)

    def _bucle(self) -> None:
        while not self._parar.wait(self.cada):
            try:
                if not job_store.heartbeat(self.job_id, self.worker_id, db_path=self.db_path):
                    self.perdido = True
                    log.warning("El job %s ya no es de este worker (cancelado o "
                                "liberado); su resultado se descartara", self.job_id)
                    return
            except Exception:  # noqa: BLE001 - un latido fallido no tumba el job
                log.warning("latido fallido para %s", self.job_id, exc_info=True)

    def __enter__(self) -> "_Latido":
        if self.cada and self.cada > 0:
            self._hilo.start()
        return self

    def __exit__(self, *exc) -> bool:
        self._parar.set()
        if self._hilo.is_alive():
            self._hilo.join(timeout=5)
        return False


def process_one(worker_id: str, job_types: list | None, workspace: str | None,
                db_path: str, retry_backoff_seconds: float = 0,
                heartbeat_seconds: float | None = None) -> bool:
    """Reclama y procesa un job. Devuelve True si procesó alguno, False si no había.

    B3 · H-02: el cierre del job (complete/failed/skipped) se escribe con
    ``locked_by=worker_id``: solo si el job SIGUE siendo de este worker. Un job
    cancelado mientras corria, o liberado por stale y reclamado por otro, no
    se sobrescribe (la cancelacion es cooperativa: el handler no se
    interrumpe, pero su resultado se descarta).
    """
    job = job_store.claim_next_job(worker_id, job_types=job_types, workspace=workspace,
                                   db_path=db_path)
    if job is None:
        return False

    job_id = job["job_id"]
    job_type = job.get("job_type")
    log.info("Job reclamado: %s (job_type=%s, workspace=%s, intento=%s/%s)", job_id, job_type,
             job["workspace"], (job.get("attempts") or 0) + 1, job.get("max_attempts"))

    try:
        with _Latido(job_id, worker_id, db_path, heartbeat_seconds or 0):
            result = dispatch(job)
    except JobHandlerError as exc:
        # job_type sin implementar (o payload roto): no es un fallo transitorio,
        # no tiene sentido reintentar. Se marca 'skipped' con mensaje claro.
        if not job_store.mark_skipped(job_id, message=str(exc), db_path=db_path,
                                      locked_by=worker_id):
            log.warning("Job %s ya no es de este worker; no se marca 'skipped'", job_id)
        log.warning("Job omitido (%s): %s", job_id, exc)
        return True
    except Exception as exc:  # noqa: BLE001 - cualquier excepción del handler → failed
        # UN ERROR PERMANENTE NO SE REINTENTA. `retry=True` devuelve el job a
        # 'pending' hasta agotar `max_attempts` (3 por defecto), lo cual es
        # correcto para un fallo transitorio y ABSURDO para uno que no puede
        # cambiar: una fuente inválida lo seguirá siendo en el segundo intento
        # y en el tercero.
        #
        # Y no es sólo ruido: mientras el job rebota entre 'pending' y
        # 'running', la consola del operador enseña "sigue en la cola". El
        # operador no ve ERROR hasta el tercer intento, de modo que el
        # desenlace que el panel promete ("termina OK o ERROR") llegaba tarde
        # o no llegaba.
        #
        # El handler es quien sabe si su error puede cambiar, así que lo
        # DECLARA: `retryable = False` en la excepción. Por defecto se
        # reintenta, que es el comportamiento anterior y el correcto cuando
        # nadie afirma nada.
        reintentar = bool(getattr(exc, "retryable", True))
        espera = retroceso(retry_backoff_seconds, job.get("attempts") or 0) if reintentar else 0
        if not job_store.mark_failed(job_id, error_message=str(exc), retry=reintentar,
                                     db_path=db_path, retry_delay_seconds=espera,
                                     locked_by=worker_id):
            log.warning("Job %s ya no es de este worker; su fallo no se escribe", job_id)
        log.exception("Job fallido (%s, reintentable=%s, espera=%ss)", job_id, reintentar, espera)
        return True

    if not job_store.mark_complete(job_id, result=result, db_path=db_path, locked_by=worker_id):
        log.warning("Job %s ya no es de este worker (cancelado o liberado): resultado "
                    "descartado", job_id)
        return True
    log.info("Job completado: %s", job_id)
    return True


def _liberar_huerfanos(stale_timeout_seconds, db_path, retry_backoff_seconds) -> None:
    released = job_store.release_stale_jobs(
        stale_timeout_seconds, db_path=db_path,
        retry_delay_seconds=retroceso(retry_backoff_seconds, 0))
    if released:
        log.warning("Jobs 'running' huerfanos liberados (gastan un intento): %s", released)


def run(
    worker_id: str,
    once: bool = True,
    limit: int = 1,
    sleep_seconds: int = 5,
    job_type: str | None = None,
    workspace: str | None = None,
    dry_run: bool = False,
    stale_timeout_seconds: int | None = None,
    db_path: str | None = None,
    retry_backoff_seconds: float = 0,
    heartbeat_seconds: float | None = None,
    stop_event: threading.Event | None = None,
    max_vueltas_fallidas: int = MAX_VUELTAS_FALLIDAS,
) -> int:
    """Bucle principal del worker. Devuelve el número de jobs procesados.

    ``once=True``: procesa hasta ``limit`` jobs y vuelve (``limit`` solo
    gobierna este modo). ``once=False``: DAEMON. Sigue reclamando hasta que se
    active ``stop_event`` (SIGTERM/SIGINT en ``main``), durmiendo
    ``sleep_seconds`` con la cola vacia; una cola vacia NO lo termina.

    B3 · H-02: antes la rama era ``if once or limit`` con ``limit`` = 1 por
    defecto, asi que ``--loop`` entraba en la rama de una pasada y terminaba
    al instante con rc=0 (medido). El daemon solo existia por el camino oculto
    ``--loop --limit 0``.
    """
    db_path = job_store.resolve_db_path(db_path)
    try:
        job_store.init_db(db_path)
        if not dry_run:
            job_store.comprobar_escritura(db_path)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo aqui es cola inutilizable
        raise ColaInutilizable("la cola %s no se puede escribir: %s" % (db_path, exc)) from exc
    job_types = [job_type] if job_type else None
    if heartbeat_seconds is None and stale_timeout_seconds:
        # El latido tiene que caber varias veces en el plazo de stale: si no,
        # un job vivo y largo se liberaria como huerfano.
        heartbeat_seconds = max(1.0, min(30.0, stale_timeout_seconds / 4.0))

    if stale_timeout_seconds:
        _liberar_huerfanos(stale_timeout_seconds, db_path, retry_backoff_seconds)

    if dry_run:
        pending = job_store.list_jobs(status="pending", job_type=job_type, workspace=workspace,
                                      limit=limit, db_path=db_path)
        for j in pending:
            log.info("[dry-run] Procesaría: %s (job_type=%s)", j["job_id"], j.get("job_type"))
        return len(pending)

    processed = 0
    if once:
        for _ in range(limit if limit else 1):
            if not process_one(worker_id, job_types, workspace, db_path,
                               retry_backoff_seconds, heartbeat_seconds):
                break
            processed += 1
        return processed

    # DAEMON: hasta que lo paren. Ni la cola vacia ni un error de la base lo
    # terminan; un error se registra y se reintenta tras dormir.
    parar = stop_event or threading.Event()
    log.info("Worker %s en modo continuo (db=%s, sondeo=%ss, stale=%s)", worker_id, db_path,
             sleep_seconds, stale_timeout_seconds)
    fallidas = 0
    while not parar.is_set():
        did_work = False
        try:
            if stale_timeout_seconds:
                # En CADA vuelta, no solo al arrancar: el huerfano de un worker
                # que murio hace un momento aun no es stale cuando arranca el
                # siguiente, y sin esto se quedaria 'running' para siempre.
                _liberar_huerfanos(stale_timeout_seconds, db_path, retry_backoff_seconds)
            did_work = process_one(worker_id, job_types, workspace, db_path,
                                   retry_backoff_seconds, heartbeat_seconds)
            fallidas = 0
        except Exception as exc:  # noqa: BLE001 - una vuelta fallida no mata el daemon...
            fallidas += 1
            log.exception("Vuelta del worker fallida (%s/%s seguidas); se reintenta en %ss",
                          fallidas, max_vueltas_fallidas, sleep_seconds)
            # ...pero N seguidas si: es una cola rota, no un tropiezo, y un
            # daemon `active` que no puede trabajar es peor que uno caido.
            if max_vueltas_fallidas and fallidas >= max_vueltas_fallidas:
                raise ColaInutilizable("%s vueltas fallidas seguidas: %s" % (fallidas, exc)) from exc
        if did_work:
            processed += 1
        else:
            parar.wait(sleep_seconds)
    log.info("Worker %s detenido limpiamente tras %s jobs", worker_id, processed)
    return processed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Worker genérico de la cola de jobs S9 Knowledge. "
                    "No escribe en Neo4j; `ingest_v3` sí lo LEE (sólo lectura) "
                    "para observar el catálogo del workspace."
    )
    parser.add_argument("--once", action="store_true",
                        help="Procesar hasta --limit jobs y salir (por defecto).")
    parser.add_argument("--loop", action="store_true",
                        help="Modo continuo: sigue reclamando jobs hasta Ctrl+C, "
                             "durmiendo --sleep-seconds cuando no hay trabajo.")
    parser.add_argument("--limit", type=int, default=1,
                        help="Máximo de jobs a procesar en --once (en --loop no aplica).")
    parser.add_argument("--sleep-seconds", type=int, default=5,
                        help="Segundos de espera entre sondeos en --loop.")
    parser.add_argument("--worker-id", default=None, help="Identificador del worker.")
    parser.add_argument("--job-type", default=None, help="Filtrar por tipo de job.")
    parser.add_argument("--workspace", default=None, help="Filtrar por workspace.")
    parser.add_argument("--dry-run", action="store_true",
                        help="No reclama ni modifica jobs; solo muestra qué haría.")
    parser.add_argument("--release-stale-seconds", type=int, default=None,
                        help="Si se indica, libera (gastando un intento) los jobs "
                             "'running' sin latido desde hace más de N segundos: al "
                             "arrancar y, en --loop, en cada vuelta.")
    parser.add_argument("--retry-backoff-seconds", type=float, default=30,
                        help="Espera base antes de reintentar un job fallido "
                             "(se dobla por intento, techo %ss; 0 = inmediato)."
                             % RETRY_BACKOFF_MAX_SECONDS)
    parser.add_argument("--max-vueltas-fallidas", type=int, default=MAX_VUELTAS_FALLIDAS,
                        help="En --loop, vueltas fallidas SEGUIDAS tras las que el worker "
                             "sale con rc=3 (0 = nunca).")
    parser.add_argument("--heartbeat-seconds", type=float, default=None,
                        help="Cada cuántos segundos se refresca el latido del job en "
                             "curso (por defecto: un cuarto de --release-stale-seconds, "
                             "máx. 30).")
    parser.add_argument("--db", default=None,
                        help="Ruta a jobs.db (por defecto: S9K_JOBS_DB o el default del módulo).")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    worker_id = args.worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    once = args.once or not args.loop  # por defecto: comportamiento --once

    # PARADA LIMPIA (systemd manda SIGTERM al parar o reiniciar la unidad). No
    # se corta un job a medias: se termina el que este en curso y se sale. Si
    # tarda mas que `TimeoutStopSec`, systemd lo mata y el job queda huerfano;
    # el siguiente arranque lo libera con `--release-stale-seconds` gastando
    # un intento, que es exactamente para lo que existe.
    parar = threading.Event()
    if not once:
        def _al_recibir(signum, _frame):
            log.info("Señal %s recibida: el worker termina tras el job en curso", signum)
            parar.set()

        signal.signal(signal.SIGTERM, _al_recibir)
        signal.signal(signal.SIGINT, _al_recibir)

    try:
        processed = _run_desde_cli(args, worker_id, once, parar)
    except ColaInutilizable as exc:
        log.error("WORKER DETENIDO: %s", exc)
        print("ERROR: %s" % exc, file=sys.stderr)
        return 3
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}Jobs procesados: {processed}")
    return 0


def _run_desde_cli(args, worker_id, once, parar) -> int:
    return run(
        worker_id,
        once=once,
        limit=args.limit,
        sleep_seconds=args.sleep_seconds,
        job_type=args.job_type,
        workspace=args.workspace,
        dry_run=args.dry_run,
        stale_timeout_seconds=args.release_stale_seconds,
        db_path=args.db,
        retry_backoff_seconds=args.retry_backoff_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
        stop_event=parar,
        max_vueltas_fallidas=args.max_vueltas_fallidas,
    )


if __name__ == "__main__":
    sys.exit(main())
