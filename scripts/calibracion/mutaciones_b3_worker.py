#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B3 (USABLE-V1) · H-02 — arnés de calibración del worker DESATENDIDO.

Una garantía no cuenta hasta que hay una prueba CAPAZ DE PONERSE ROJA, y roja
POR SU CAUSA. Cada mutación reintroduce UN defecto real de H-02/H-37 sobre el
código commiteado, corre las pruebas nombradas de sus testigos y exige:

  - PYTEST_RC != 0 y cada prueba nombrada en rojo con su FRAGMENTO de causa
    en la línea `FAILED ... - <mensaje>`;
  - que el testigo se ejecutó de verdad: `collected > 0`, `skipped == 0`,
    `errors == 0`, en la base, en cada mutación y tras restaurar;
  - restauración verificada: árbol tracked limpio y PYTEST_RC post = 0.

Testigos:
  data-engine/app/tests/test_b3_worker_desatendido.py   (worker REAL en subproceso)
  deploy/tests/test_b3_worker_unidad.py                 (unidad + pasos 2/7/13 de deploy.sh)
  viewer/tests/test_b3_worker_desatendido_e2e.py        (web -> servicio -> web)
  deploy/tests/test_worker_env_validacion.py            (estado compartido de worker.env)

Mutaciones (las seis del encargo, M1-M6, cinco de la familia y diez de la revisión):

  M1  `--loop` vuelve a `if once or limit` (el daemon termina al instante)
  M2  `release_stale_jobs` deja de gastar un intento (bucle infinito)
  M3  `claim_next_job` ignora `next_retry_at`
  M4  el worker se traga la excepción del handler (job `running`, sin error)
  M5  la unidad apunta a un intérprete inexistente
  M6  `deploy.sh` reintroduce su propio default de `jobs.db` (H-37)
  M6b la plantilla del worker declara otra `jobs.db` (H-37)
  M7  el cierre del job deja de exigir que el worker siga siendo su dueño
      (un `cancelled` vuelve a `complete`)
  M8  el latido no se arranca (un job vivo y largo se libera como huérfano)
  M9  `deploy.sh` deja de habilitar el worker (no vuelve tras reiniciar)
  M10 `deploy.sh` deja de crear el venv del motor

Y las de la ronda de corrección de la revisión independiente de #273:

  MA  el worker no atiende SIGTERM          MF  huérfanos solo al arrancar
  ME  una vuelta con error mata el daemon   MC  `mark_failed` sin guardia de dueño
  MD  retroceso sin techo                   MG  sin sonda de escritura al arrancar
  MH  sin límite de vueltas fallidas        MI  la receta de primera release sin worker.env
  MJ  el rollback no deshabilita el worker  MK  decisiones humanas no compartidas

LOCALIZADORES: Python con `localizadores.mutar_en_funcion` (AST, ancla única
DENTRO de la función; para `job_store.py`, cuyos nombres se repiten como
métodos de `JobStore`, la variante de nivel de módulo de este fichero); bash, unidad y plantillas con `mutar_unico` (ancla
ÚNICA en el fichero; bash y systemd no tienen AST que usar aquí) y `bash -n`
sobre el resultado. Ancla ausente o ambigua = DETECTOR ROTO, nunca «la primera».

COSTE: la base corre los tres testigos completos (~1,5 min); cada mutación
corre SOLO sus pruebas nombradas (mutada y restaurada). Total medido < 10 min.

TECHO: no ejerce systemd real ni el reinicio de máquina (RC-E2E PENDING); muta
por sustitución de texto exacto y no ve una segunda copia de la lógica.

Uso: python3 scripts/calibracion/mutaciones_b3_worker.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, mutar_unico, python_sigue_siendo_valido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
T_DE = "data-engine/app/tests/test_b3_worker_desatendido.py"
T_DEPLOY = "deploy/tests/test_b3_worker_unidad.py"
T_E2E = "viewer/tests/test_b3_worker_desatendido_e2e.py"
WORKER = "data-engine/app/jobs/worker.py"
JOB_STORE = "data-engine/app/jobs/job_store.py"
UNIDAD = "data-engine/systemd/s9-knowledge-worker.service"
DEPLOY_SH = "deploy/scripts/deploy.sh"
WORKER_ENV = "deploy/config/worker.env.example"
T_ENV = "deploy/tests/test_worker_env_validacion.py"
LIB_SH = "deploy/scripts/lib.sh"
VALIDATE_SH = "deploy/scripts/validate_deploy.sh"
README = "deploy/README.md"


def _sh(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        if ".claude" in d.relative_to(RAIZ).parts:
            continue
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = _sh(["git", "status", "--porcelain", "--untracked-files=no"])
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr(testigos: list, nombres: list | None = None):
    _purgar_pycache()
    cmd = [sys.executable, "-m", "pytest", *testigos, "-q", "--no-header", "--color=no",
           "-p", "no:randomly", "-p", "no:cacheprovider", "-rfs"]
    if nombres:
        cmd += ["-k", " or ".join(sorted({n.split("[")[0] for n in nombres}))]
    r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True,
                       env={**os.environ, "COLUMNS": "4000", "PYTHONDONTWRITEBYTECODE": "1"})
    return r.returncode, r.stdout + r.stderr


def _recuento(salida: str) -> dict:
    cifras: dict = {}
    for linea in salida.splitlines()[::-1]:
        if " in " in linea and ("passed" in linea or "failed" in linea or "error" in linea):
            for n, clave in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected)", linea):
                cifras[clave.rstrip("s") if clave.startswith("error") else clave] = int(n)
            break
    return cifras


def _ejecutado_de_verdad(cifras: dict) -> bool:
    recogidas = sum(cifras.get(k, 0) for k in ("passed", "failed", "skipped", "error"))
    return recogidas > 0 and cifras.get("skipped", 0) == 0 and cifras.get("error", 0) == 0


def _fallos(salida: str) -> dict:
    fallos: dict = {}
    for linea in salida.splitlines():
        if not linea.startswith("FAILED "):
            continue
        ident, _, mensaje = linea[len("FAILED "):].partition(" - ")
        fallos[ident.split("::")[-1].strip()] = mensaje
    return fallos


def _valido(fichero: str, texto: str) -> bool:
    if fichero.endswith(".py"):
        return python_sigue_siendo_valido(texto)
    if fichero.endswith(".sh"):
        r = subprocess.run(["bash", "-n"], input=texto, capture_output=True, text=True)
        return r.returncode == 0
    return True


def _mutar_en_funcion_de_modulo(texto: str, nombre: str, viejo: str, nuevo: str):
    """`mutar_en_funcion`, pero SOLO entre las funciones de NIVEL DE MODULO.

    `job_store.py` repite cada nombre como metodo de su envoltorio `JobStore`
    (que delega en la funcion del modulo), y `span_de_funcion` exige un unico
    `def` con ese nombre en todo el arbol: daba DETECTOR ROTO, medido. La
    funcion atacada es la del modulo; el ancla sigue teniendo que ser unica
    DENTRO de ella.
    """
    import ast

    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return None
    nodos = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == nombre]
    if len(nodos) != 1:
        return None
    lineas = texto.splitlines(keepends=True)
    inicio = sum(len(l) for l in lineas[: nodos[0].lineno - 1])
    fin = sum(len(l) for l in lineas[: nodos[0].end_lineno])
    cuerpo = texto[inicio:fin]
    if cuerpo.count(viejo) != 1:
        return None
    mutado = texto[:inicio] + cuerpo.replace(viejo, nuevo, 1) + texto[fin:]
    return None if mutado == texto else mutado


# ---------------------------------------------------------------------------
# Mutaciones
# ---------------------------------------------------------------------------

def _m1_loop_vuelve_a_once_or_limit(t):
    return mutar_en_funcion(t, "run", "    if once:\n", "    if once or limit:\n")


def _m2_stale_sin_intentos(t):
    return _mutar_en_funcion_de_modulo(t, "release_stale_jobs",
                            '            attempts = (row["attempts"] or 0) + 1\n',
                            '            attempts = row["attempts"] or 0\n')


def _m3_next_retry_at_ignorado(t):
    return _mutar_en_funcion_de_modulo(
        t, "claim_next_job",
        '    clauses = ["status = \'pending\'", "(next_retry_at IS NULL OR next_retry_at <= ?)"]\n'
        '    params = [now]\n',
        '    clauses = ["status = \'pending\'"]\n    params = []\n')


def _m4_se_traga_la_excepcion(t):
    return mutar_en_funcion(
        t, "process_one",
        "        if not job_store.mark_failed(job_id, error_message=str(exc), retry=reintentar,\n"
        "                                     db_path=db_path, retry_delay_seconds=espera,\n"
        "                                     locked_by=worker_id):\n",
        "        if False:\n")


def _m5_interprete_inexistente(t):
    return mutar_unico(t, "/opt/s9-knowledge/current/data-engine/.venv/bin/python /opt",
                       "/opt/s9-knowledge/current/data-engine/.venv/bin/python3.99 /opt")


def _m6_deploy_default_propio(t):
    return mutar_unico(
        t,
        'NEW_JOBS_DB="$(python3 "${JOB_STORE_PY}" --ruta-despliegue --state-root "${S9K_STATE_ROOT}")" \\\n',
        'NEW_JOBS_DB="${S9K_STATE_ROOT}/state/jobs.db"; true \\\n')


def _m6b_plantilla_worker_diverge(t):
    return mutar_unico(t, "\nS9K_JOBS_DB=/var/lib/s9-knowledge/jobs/jobs.db\n",
                       "\nS9K_JOBS_DB=/var/lib/s9-knowledge/state/jobs.db\n")


def _m7_cierre_sin_dueno(t):
    return mutar_en_funcion(
        t, "process_one",
        "    if not job_store.mark_complete(job_id, result=result, db_path=db_path, locked_by=worker_id):\n",
        "    if not job_store.mark_complete(job_id, result=result, db_path=db_path):\n")


def _m8_sin_latido(t):
    return mutar_en_funcion(t, "process_one",
                            "        with _Latido(job_id, worker_id, db_path, heartbeat_seconds or 0):\n",
                            "        with _Latido(job_id, worker_id, db_path, 0):\n")


def _m9_deploy_no_habilita_el_worker(t):
    return mutar_unico(t, 'systemctl enable "${WORKER_UNIT_NAME}" || die "no se pudo habilitar el worker"\n',
                       'true\n')


def _m10_deploy_sin_venv_del_motor(t):
    return mutar_unico(t, 'python3 -m venv "${RELEASE_DIR}/data-engine/.venv"\n', ':\n')


# --- Ronda de correccion de la revision independiente de #273 ---

def _ma_sin_sigterm(t):
    return mutar_en_funcion(t, "main", "        signal.signal(signal.SIGTERM, _al_recibir)\n", "        pass\n")


def _mf_stale_solo_al_arrancar(t):
    return mutar_en_funcion(
        t, "run",
        "                _liberar_huerfanos(stale_timeout_seconds, db_path, retry_backoff_seconds)\n",
        "                pass\n")


def _me_vuelta_fallida_mata(t):
    return mutar_en_funcion(
        t, "run",
        '            log.exception("Vuelta del worker fallida (%s/%s seguidas); se reintenta en %ss",\n',
        '            raise\n            log.exception("Vuelta del worker fallida (%s/%s seguidas); se reintenta en %ss",\n')


def _mc_mark_failed_sin_guardia(t):
    return _mutar_en_funcion_de_modulo(t, "mark_failed",
                                       "    guardia, extra = _guardia_de_propietario(locked_by)\n",
                                       '    guardia, extra = "", ()\n')


def _md_retroceso_sin_techo(t):
    return mutar_en_funcion(
        t, "retroceso",
        "    return min(RETRY_BACKOFF_MAX_SECONDS, base_seconds * (2 ** max(0, intentos_previos)))\n",
        "    return base_seconds * (2 ** max(0, intentos_previos))\n")


def _mg_sin_sonda_de_escritura(t):
    return mutar_en_funcion(t, "run", "            job_store.comprobar_escritura(db_path)\n",
                            "            pass\n")


def _mh_sin_limite_de_vueltas(t):
    return mutar_en_funcion(t, "run",
                            "            if max_vueltas_fallidas and fallidas >= max_vueltas_fallidas:\n",
                            "            if False:\n")


def _mi_receta_sin_worker_env(t):
    return mutar_unico(t, "install -m 0600 deploy/config/worker.env.example /etc/s9-knowledge/worker.env\n",
                       "")


def _mj_rollback_no_deshabilita(t):
    return mutar_unico(t, '    systemctl disable --now "${unit}" || warn "no se pudo deshabilitar ${unit}"\n',
                       "    :\n")


def _mk_sin_decisiones_compartidas(t):
    return mutar_unico(
        t, "    for var in S9K_JOBS_DB S9K_V3_REVIEW_PROPOSALS_DIR S9K_V3_REVIEW_DATABASE_PATH; do\n",
        "    for var in S9K_JOBS_DB S9K_V3_REVIEW_PROPOSALS_DIR; do\n")


MUTACIONES = [
    ("M1 — `--loop` vuelve a `if once or limit` (daemon que termina al instante)",
     WORKER, _m1_loop_vuelve_a_once_or_limit, [T_DE, T_E2E],
     {"test_loop_es_un_daemon_con_la_cola_vacia": "DAEMON ROTO",
      "test_un_trabajo_creado_desde_la_web_se_procesa_sin_intervencion_manual":
          "el servicio termino tras procesar"}),
    ("M2 — `release_stale_jobs` deja de gastar un intento (bucle infinito)",
     JOB_STORE, _m2_stale_sin_intentos, [T_DE],
     {"test_stale_gasta_un_intento_y_acaba_en_failed": "STALE SIN INTENTOS",
      "test_un_job_que_mata_al_worker_agota_intentos_y_falla": "STALE SIN INTENTOS"}),
    ("M3 — `claim_next_job` ignora `next_retry_at`",
     JOB_STORE, _m3_next_retry_at_ignorado, [T_DE],
     {"test_un_reintento_con_next_retry_at_futuro_no_se_reclama": "NEXT_RETRY_AT IGNORADO",
      "test_el_reintento_respeta_el_retroceso": "NEXT_RETRY_AT IGNORADO"}),
    ("M4 — el worker se traga la excepción del handler (job sin error)",
     WORKER, _m4_se_traga_la_excepcion, [T_DE],
     {"test_handler_con_error_reintenta_acotado_y_queda_failed": "HANDLER QUE SE TRAGA EL ERROR"}),
    ("M5 — la unidad apunta a un intérprete inexistente",
     UNIDAD, _m5_interprete_inexistente, [T_DEPLOY],
     {"test_la_unidad_canonica_pasa_su_validador_por_efecto": "no existe o no es ejecutable"}),
    ("M6 — deploy.sh reintroduce su propio default de jobs.db (H-37)",
     DEPLOY_SH, _m6_deploy_default_propio, [T_DEPLOY],
     {"test_deploy_sh_pide_la_ruta_de_jobs_db_a_job_store": "DEFAULT DIVERGENTE",
      "test_ningun_otro_modulo_del_producto_define_un_default_de_jobs_db":
          "deploy.sh escribe su propio jobs.db"}),
    ("M6b — la plantilla del worker declara otra jobs.db (H-37)",
     WORKER_ENV, _m6b_plantilla_worker_diverge, [T_DEPLOY],
     {"test_las_plantillas_declaran_la_ruta_de_job_store": "DEFAULT DIVERGENTE en worker.env.example"}),
    ("M7 — cerrar un job deja de exigir que el worker siga siendo su dueño",
     WORKER, _m7_cierre_sin_dueno, [T_DE],
     {"test_cancelado_mientras_corre_no_se_sobrescribe": "CANCELACION NO COOPERATIVA"}),
    ("M8 — el latido no se arranca",
     WORKER, _m8_sin_latido, [T_DE],
     {"test_el_latido_mantiene_vivo_un_job_largo": "se libero como huerfano"}),
    ("M9 — deploy.sh deja de habilitar el worker",
     DEPLOY_SH, _m9_deploy_no_habilita_el_worker, [T_DEPLOY],
     {"test_paso13_real_habilita_y_arranca_el_worker_antes_que_el_visor[upgrade]":
          "no volveria tras reiniciar"}),
    ("M10 — deploy.sh deja de crear el venv del motor",
     DEPLOY_SH, _m10_deploy_sin_venv_del_motor, [T_DEPLOY],
     {"test_paso2_crea_el_venv_del_motor_que_usa_la_unidad": "no crea el venv"}),
    # --- Ronda de correccion de la revision independiente de #273 ---
    ("MA — el worker no atiende SIGTERM (parada sucia)",
     WORKER, _ma_sin_sigterm, [T_DE],
     {"test_sigterm_con_un_job_en_curso_lo_termina_antes_de_salir": "PARADA SUCIA"}),
    ("MF — los huerfanos solo se liberan al arrancar",
     WORKER, _mf_stale_solo_al_arrancar, [T_DE],
     {"test_worker_matado_a_mitad_se_libera_y_se_reprocesa": "el huerfano no se libero"}),
    ("ME — una vuelta con error mata el daemon",
     WORKER, _me_vuelta_fallida_mata, [T_DE],
     {"test_una_vuelta_con_error_no_mata_el_daemon": "VUELTA FALLIDA MATA EL DAEMON"}),
    ("MC — mark_failed sin guardia de dueño",
     JOB_STORE, _mc_mark_failed_sin_guardia, [T_DE],
     {"test_mark_failed_de_un_worker_que_ya_no_es_dueno_no_tiene_efecto": "MARK_FAILED SIN GUARDIA"}),
    ("MD — retroceso sin techo",
     WORKER, _md_retroceso_sin_techo, [T_DE],
     {"test_el_retroceso_tiene_techo": "RETROCESO SIN TECHO"}),
    ("MG — sin sonda de escritura al arrancar (F2)",
     WORKER, _mg_sin_sonda_de_escritura, [T_DE],
     {"test_una_cola_de_solo_lectura_para_el_worker_al_arrancar": "COLA ROTA EN SILENCIO"}),
    ("MH — sin limite de vueltas fallidas seguidas (F2)",
     WORKER, _mh_sin_limite_de_vueltas, [T_DE],
     {"test_n_vueltas_fallidas_seguidas_terminan_el_daemon": "COLA ROTA EN SILENCIO"}),
    ("MI — la receta de primera release no crea worker.env (F1)",
     README, _mi_receta_sin_worker_env, [T_DEPLOY],
     {"test_la_receta_de_primera_release_crea_worker_env_y_su_secreto": "RECETA INCOMPLETA"}),
    ("MJ — el rollback no deshabilita el worker (F3)",
     LIB_SH, _mj_rollback_no_deshabilita, [T_DEPLOY],
     {"test_rollback_a_una_release_sin_venv_deshabilita_el_worker[sin-unidad-previa]":
          "ROLLBACK DEJA EL WORKER HABILITADO"}),
    ("MK — worker.env y viewer.env pueden divergir en las decisiones humanas (F5)",
     VALIDATE_SH, _mk_sin_decisiones_compartidas, [T_ENV],
     {"test_estado_distinto_del_visor_BLOQUEA[S9K_V3_REVIEW_DATABASE_PATH-/var/lib/s9-knowledge/otras/review.sqlite3]":
          "NO BLOQUEO"}),
]


def main() -> int:
    inicio = time.monotonic()
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de calibrar "
              "(la restauración escribe sobre el fichero).")
        return 2

    rc, salida = _correr([T_DE, T_DEPLOY, T_E2E, T_ENV])
    cifras = _recuento(salida)
    if rc != 0 or not _ejecutado_de_verdad(cifras):
        print("ABORTA: los testigos no están verdes y ejecutados en la base "
              "(PYTEST_RC=%s, cifras=%s)" % (rc, cifras))
        print(salida[-3000:])
        return 2
    print("BASE: testigos verdes, PYTEST_RC=%s, cifras=%s\n" % (rc, cifras))

    veredictos = []
    for nombre, fichero, mutador, testigos, esperadas in MUTACIONES:
        f = RAIZ / fichero
        original = f.read_text(encoding="utf-8")
        mutado = mutador(original)
        if mutado is None or mutado == original or not _valido(fichero, mutado):
            print("### %s\n  DETECTOR ROTO: la mutación no se pudo aplicar sobre %s "
                  "(ancla ausente/ambigua o resultado inválido). Un verde aquí "
                  "sería FALSO.\n" % (nombre, fichero))
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue
        try:
            f.write_text(mutado, encoding="utf-8")
            rc_mut, salida_mut = _correr(testigos, list(esperadas))
        finally:
            f.write_text(original, encoding="utf-8")
            _purgar_pycache()
        cifras_mut = _recuento(salida_mut)
        fallos = _fallos(salida_mut)
        causas = {p: (p in fallos and frag in fallos[p]) for p, frag in esperadas.items()}
        limpio = _arbol_limpio_tracked()
        rc_post, salida_post = _correr(testigos, list(esperadas))
        cifras_post = _recuento(salida_post)

        print("### %s" % nombre)
        print("  fichero              : %s" % fichero)
        print("  PYTEST_RC mutado     : %s  (esperado != 0)" % rc_mut)
        print("  cifras mutado        : %s  (skipped/errores esperados 0)" % cifras_mut)
        print("  pruebas en rojo      : %s" % sorted(fallos))
        for p, ok in causas.items():
            print("  causa %s %s: esperado %r -> %r" % (
                "OK " if ok else "MAL", p, esperadas[p], fallos.get(p, "(no falló)")[:300]))
        print("  restaurado (tracked limpio): %s" % limpio)
        print("  restaurado (PYTEST_RC post): %s, cifras %s" % (rc_post, cifras_post))
        ok = (rc_mut != 0 and _ejecutado_de_verdad(cifras_mut) and all(causas.values())
              and limpio and rc_post == 0 and _ejecutado_de_verdad(cifras_post))
        print("  VEREDICTO            : %s\n" % ("CALIBRADA" if ok else "NO CALIBRADA"))
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print("  %-14s %s" % (v, nombre))
    total = sum(1 for _, v in veredictos if v == "CALIBRADA")
    print("  TOTAL: %d/%d  (%.0f s)" % (total, len(MUTACIONES), time.monotonic() - inicio))
    return 0 if total == len(MUTACIONES) else 1


if __name__ == "__main__":
    sys.exit(main())
