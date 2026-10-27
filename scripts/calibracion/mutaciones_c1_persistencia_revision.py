#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C1 (USABLE-V1) · H-04 + H-18 — arnés de calibración de la persistencia de
decisiones humanas (`review.sqlite3`).

Una garantía no cuenta hasta que hay una prueba CAPAZ DE PONERSE ROJA, y roja
POR SU CAUSA. Cada mutación reintroduce UN defecto real de la familia sobre el
código commiteado, corre los dos testigos

    deploy/tests/test_c1_revision_deploy.py     (lado despliegue)
    viewer/tests/test_c1_revision_runtime.py     (lado runtime)

y exige:

  - PYTEST_RC != 0 y las pruebas nombradas en rojo, cada una con su FRAGMENTO
    de causa en la línea `FAILED ... - <mensaje>`;
  - que el testigo se ejecutó de verdad: `collected > 0`, `skipped == 0`,
    `errors == 0`, en la base, en cada mutación y tras restaurar;
  - restauración verificada: árbol tracked limpio y PYTEST_RC post = 0.

Las diez mutaciones del encargo (M1-M10) y las de apoyo:

  M1  el visor vuelve a derivar su ruta de `review.sqlite3`           (N18)
  M2  `if not exists: return {}` reintroducido en la lectura del motor (N2)
  M3  SQLiteReviewStore recupera `mkdir` con la ruta declarada         (N3)
  M3b SQLiteReviewStore recupera la creación del fichero               (N3)
  M3c ReviewService abre con creación aunque la ruta esté declarada    (N3)
  M4  el preflight del despliegue pierde la exigencia de existencia    (N1)
  M5  el preflight trata upgrade como fresh                            (N1)
  M6  deploy.sh crea también en upgrade                                (N1/P2)
  M7  el almacén adopta un SQLite sin `human_decisions`                (N4/N12)
  M8  fresh ignora una BD existente                                    (N5)
  M9  `preparar_estado_del_worker` deja de preparar la revisión        (N17)
  M9b ... y deja de dar sus ficheros -wal/-shm al worker               (N17)
  M10 la autorización sobrescribe una BD no vacía/corrupta             (N11/N12)
  M11 `validate_viewer_env` deja de juzgar el VALOR de la variable     (N7-N10)
  M12 la ingesta no comprueba el almacén antes de gastar la corrida    (N2)
  M13 `VAR=""` deja de ser una declaración inválida                    (N7/N8)
  M14 el candidato legacy con decisiones ya no impide crear            (N6)
  M15 la autorización crea aunque la BD ya exista (se aplica a fresh)  (N14)

LOCALIZADORES
-------------
Python: `localizadores.mutar_en_funcion` (AST; DETECTOR ROTO si el ancla no es
única dentro de la función). Bash: `localizadores.mutar_unico` —sustitución de
TEXTO con ancla ÚNICA EN EL FICHERO— y `bash -n` sobre el resultado. Si un
ancla deja de ser única la mutación da DETECTOR ROTO, nunca muta «la primera».

TECHO DE ESTE CALIBRADOR
------------------------
* Muta por sustitución de texto exacto; no ve alias ni una segunda copia de la
  lógica en otro módulo.
* Calibra los testigos de arnés local. systemd, el usuario de servicio real, la
  VM limpia y el reinicio de máquina NO se ejercen (RC-E2E PENDING).

Uso: python3 scripts/calibracion/mutaciones_c1_persistencia_revision.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, mutar_unico, python_sigue_siendo_valido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGOS = [
    "deploy/tests/test_c1_revision_deploy.py",
    "viewer/tests/test_c1_revision_runtime.py",
]
DEPLOY_SH = "deploy/scripts/deploy.sh"
LIB_SH = "deploy/scripts/lib.sh"
VALIDATE = "deploy/scripts/validate_deploy.sh"
REVIEW_STORE = "deploy/scripts/review_store.py"
PREFLIGHT = "deploy/scripts/preflight_ensayo_rc.py"
PATHS = "data-engine/app/knowledge_v3/review_paths.py"
DECISIONS = "data-engine/app/knowledge_v3/review_decisions.py"
STORE = "viewer/app/services/v3_review_store.py"
SERVICE = "viewer/app/services/v3_review.py"
HANDLER = "data-engine/app/jobs/handlers/ingest_v3.py"


def _sh(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        if ".claude" in d.parts:
            continue
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = _sh(["git", "status", "--porcelain", "--untracked-files=no"])
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigo():
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTIGOS, "-q", "--no-header",
         "--color=no", "-p", "no:randomly", "-p", "no:cacheprovider", "-rfs"],
        cwd=RAIZ, capture_output=True, text=True,
        env={**os.environ, "COLUMNS": "4000", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return r.returncode, r.stdout + r.stderr


def _recuento(salida: str) -> dict:
    cifras: dict = {}
    for linea in salida.splitlines()[::-1]:
        if " in " in linea and ("passed" in linea or "failed" in linea or "error" in linea):
            for n, clave in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)", linea):
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


# ---------------------------------------------------------------------------
# Mutaciones
# ---------------------------------------------------------------------------

def _m1_visor_deriva_su_ruta(texto: str):
    return mutar_en_funcion(
        texto, "default_database_path",
        "    return _engine_review_paths().default_review_db()",
        '    return default_decisions_path().with_name("review.sqlite3")')


def _m2_vacio_si_no_existe(texto: str):
    return mutar_en_funcion(
        texto, "verify_decisions_store",
        "    if not declarada and not path.exists():",
        "    if not path.exists():")


def _m3_store_recupera_mkdir(texto: str):
    return mutar_en_funcion(
        texto, "__init__", "        if crear:\n            path.parent.mkdir(",
        "        if True:\n            path.parent.mkdir(")


def _m3b_store_recupera_la_creacion(texto: str):
    return mutar_en_funcion(
        texto, "connect", "        if self._crear:\n", "        if True:\n")


def _m3c_servicio_abre_con_creacion(texto: str):
    return mutar_en_funcion(texto, "store", "        if self._declarada:\n", "        if False:\n")


def _m4_grupo_sin_existencia(texto: str):
    return mutar_unico(texto, '    "review_db.existente",\n    "estado.persistente",\n})',
                       '    "estado.persistente",\n})')


def _m5_upgrade_como_fresh(texto: str):
    return mutar_en_funcion(
        texto, "review_db_existente",
        '    if ins.causa == resolvedor.CAUSA_NO_EXISTE and ctx.modo == "fresh":',
        "    if ins.causa == resolvedor.CAUSA_NO_EXISTE:")


def _m6_deploy_crea_en_upgrade(texto: str):
    return mutar_unico(texto, 'preparar --modo "${MODE}" \\\n', 'preparar --modo fresh \\\n')


def _m7_adopta_sqlite_ajeno(texto: str):
    paso1 = mutar_en_funcion(
        texto, "inspect_review_db",
        "        if not COLUMNAS_HUMAN_DECISIONS <= columnas:",
        "        if False:")
    if paso1 is None:
        return None
    return mutar_en_funcion(
        paso1, "inspect_review_db",
        '            filas = conexion.execute(\n'
        '                "SELECT COUNT(*) FROM human_decisions").fetchone()[0]',
        '            filas = 0')


def _m8_fresh_ignora_la_existente(texto: str):
    return mutar_en_funcion(texto, "preparar", "    if ins.valido:\n",
                            '    if ins.valido and modo != "fresh":\n')


def _m9_worker_sin_revision(texto: str):
    return mutar_unico(
        texto,
        '    install -d -m 0750 -o "${user}" -g "${group}" "$(dirname -- "${review_db}")"\n', "")


def _m9b_worker_sin_wal_de_revision(texto: str):
    return mutar_unico(
        texto, ' "${review_db}" "${review_db}-wal" "${review_db}-shm"; do', '; do')


def _m10_autorizacion_sobrescribe(texto: str):
    return mutar_en_funcion(
        texto, "preparar", "    if ins.causa != rp.CAUSA_NO_EXISTE:\n",
        "    if ins.causa != rp.CAUSA_NO_EXISTE and not autorizar:\n")


def _m11_validate_ignora_el_valor(texto: str):
    return mutar_unico(texto, '    validate_review_db_var "${env_file}" || return 1\n',
                       '    true\n')


def _m12_ingesta_sin_comprobar_el_almacen(texto: str):
    return mutar_unico(
        texto,
        "    _exigir_almacen_de_decisiones()\n\n    # LA OBSERVACION SE ABRE",
        "    pass\n\n    # LA OBSERVACION SE ABRE")


def _m13_vacia_deja_de_ser_invalida(texto: str):
    return mutar_en_funcion(
        texto, "validar_declaracion",
        '    if crudo is None or crudo.strip() == "":',
        "    if crudo is None:")


def _m14_candidata_legacy_no_impide(texto: str):
    return mutar_en_funcion(
        texto, "preparar", "    impide = _candidata_con_decisiones(rp, candidatas)\n",
        "    impide = None\n")


def _m15_autorizacion_con_la_bd_presente(texto: str):
    return mutar_en_funcion(
        texto, "preparar", "        if autorizar:\n            res.decir(\"ANOTACION\", \"--autorizar-creacion-review-db IGNORADA",
        "        if False:\n            res.decir(\"ANOTACION\", \"--autorizar-creacion-review-db IGNORADA")


_D = "deploy"
MUTACIONES = [
    ("M1 — el visor vuelve a derivar su ruta de review.sqlite3 (N18)",
     [(SERVICE, _m1_visor_deriva_su_ruta)],
     {"test_n18_visor_motor_y_canonica_resuelven_la_misma_ruta[declarada]": "VISOR DIVERGE",
      "test_n18_visor_motor_y_canonica_resuelven_la_misma_ruta[declarada-y-decisions]": "VISOR DIVERGE"}),
    ("M2 — `if not exists: return {}` reintroducido en la lectura del motor (N2)",
     [(DECISIONS, _m2_vacio_si_no_existe)],
     {"test_n2_motor_con_ruta_declarada_inexistente_levanta": "DID NOT RAISE",
      "test_n2_resolved_proposal_ids_tampoco_cae_en_vacio": "DID NOT RAISE",
      "test_n2_la_ingesta_termina_failed_sin_publicar_paquete": "N2 INGESTA NO FALLO POR EL ALMACEN"}),
    ("M3 — SQLiteReviewStore recupera el mkdir con la ruta declarada (N3)",
     [(STORE, _m3_store_recupera_mkdir)],
     {"test_n3_el_store_sin_crear_no_hace_mkdir_ni_fichero": "N3 STORE: crear=False no puede hacer mkdir"}),
    ("M3b — SQLiteReviewStore recupera la creación del fichero (N3)",
     [(STORE, _m3b_store_recupera_la_creacion)],
     {"test_n3_el_store_sin_crear_no_hace_mkdir_ni_fichero": "N3 STORE: crear=False no puede crear la base"}),
    ("M3c — ReviewService abre con creación aunque la ruta esté declarada (N3)",
     [(SERVICE, _m3c_servicio_abre_con_creacion)],
     {"test_n3_servicio_con_ruta_declarada_ausente_no_crea_nada": "DID NOT RAISE",
      "test_n3_las_dos_superficies_http_lo_declaran_y_no_lo_pintan_vacio": "N3 HTTP NO DECLARA EL ALMACEN AUSENTE"}),
    ("M4 — el preflight del despliegue pierde la exigencia de existencia (N1)",
     [(PREFLIGHT, _m4_grupo_sin_existencia)],
     {"test_n1_upgrade_con_la_ruta_cambiada_preflight_rojo_y_deploy_die": "N1 PREFLIGHT NO ROJO",
      "test_el_grupo_despliegue_exige_la_existencia_del_almacen": "EXISTENCIA PERDIDA"}),
    ("M5 — el preflight trata upgrade como fresh (N1)",
     [(PREFLIGHT, _m5_upgrade_como_fresh)],
     {"test_n1_upgrade_con_la_ruta_cambiada_preflight_rojo_y_deploy_die": "N1 PREFLIGHT NO ROJO",
      "test_preflight_upgrade_exige_existencia_y_fresh_la_admite": "PREFLIGHT upgrade NO ROJO SIN ALMACEN"}),
    ("M6 — deploy.sh crea también en upgrade (N1/P2)",
     [(DEPLOY_SH, _m6_deploy_crea_en_upgrade)],
     {"test_upgrade_sin_bd_y_sin_autorizacion_es_stop_por_defecto": "UPGRADE SIN BD NO PARO",
      "test_p2_upgrade_normal_con_decisiones_es_verde_y_no_crea_ni_toca_nada": "P2 UPGRADE NO PASO",
      "test_deploy_sh_declara_la_excepcion_y_prepara_antes_del_preflight": "MODO"}),
    ("M7 — el almacén adopta un SQLite sin human_decisions (N4/N12)",
     [(PATHS, _m7_adopta_sqlite_ajeno)],
     {"test_n4_un_sqlite_ajeno_sin_human_decisions_no_se_adopta": "DID NOT RAISE",
      "test_n4_sqlite_ajeno_preflight_rojo_deploy_bloquea_y_no_se_toca": "N4 PREFLIGHT NO ROJO",
      "test_n12_schema_invalido_con_autorizacion_stop[upgrade]": "N12 NO PARO"}),
    ("M8 — fresh ignora una BD existente (N5)",
     [(REVIEW_STORE, _m8_fresh_ignora_la_existente)],
     {"test_n5_fresh_con_bd_con_decisiones_bloquea": "N5 SIN CAUSA",
      "test_p1_fresh_es_idempotente_y_no_toca_una_base_vacia_valida": "P1 FRESH NO PRESERVO LA VALIDA"}),
    ("M9 — preparar_estado_del_worker deja de preparar la revisión (N17)",
     [(LIB_SH, _m9_worker_sin_revision)],
     {"test_preparar_estado_del_worker_prepara_tambien_el_almacen_de_revision": "N17 SIN INSTALL DE LA REVISION"}),
    ("M9b — ... y deja de dar sus ficheros -wal/-shm al worker (N17)",
     [(LIB_SH, _m9b_worker_sin_wal_de_revision)],
     {"test_preparar_estado_del_worker_prepara_tambien_el_almacen_de_revision": "N17 SIN CHOWN DE LA REVISION"}),
    ("M10 — la autorización sobrescribe una BD corrupta o ajena (N11/N12)",
     [(REVIEW_STORE, _m10_autorizacion_sobrescribe)],
     {"test_n11_bd_corrupta_con_autorizacion_stop_sin_sobrescribir[upgrade]": "N11 NO SE SOBRESCRIBE FALTA",
      "test_n12_schema_invalido_con_autorizacion_stop[upgrade]": "N12 NO PARO",
      "test_n4_sqlite_ajeno_preflight_rojo_deploy_bloquea_y_no_se_toca": "N4 DEPLOY NO BLOQUEO"}),
    ("M11 — validate_viewer_env deja de juzgar el VALOR de la variable (N7-N10)",
     [(VALIDATE, _m11_validate_ignora_el_valor)],
     {"test_n7_n10_validate_viewer_env_rechaza_con_la_causa[N7-vacia]": "N7-10 VALIDATE NO RECHAZO",
      "test_n7_n10_validate_viewer_env_rechaza_con_la_causa[N9-relativa]": "N7-10 VALIDATE NO RECHAZO",
      "test_n7_n10_validate_viewer_env_rechaza_con_la_causa[N10-directorio]": "N7-10 VALIDATE NO RECHAZO"}),
    ("M12 — la ingesta no comprueba el almacén antes de gastar la corrida (N2)",
     [(HANDLER, _m12_ingesta_sin_comprobar_el_almacen)],
     {"test_n2_la_ingesta_termina_failed_sin_publicar_paquete": "N2 INGESTA NO FALLO POR EL ALMACEN",
      "test_n17_worker_sin_lectura_del_directorio_falla_con_causa_permisos": "N17 INGESTA NO FALLO POR PERMISOS"}),
    ("M13 — VAR=\"\" deja de ser una declaración inválida (N7/N8)",
     [(PATHS, _m13_vacia_deja_de_ser_invalida)],
     {"test_n7_n10_variable_invalida_nombra_la_causa_real[N7-vacia]": "VAR_VACIA",
      "test_n7_n10_variable_invalida_nombra_la_causa_real[N8-espacios]": "VAR_VACIA",
      "test_n7_n10_la_herramienta_de_despliegue_nombra_la_causa[N7-vacia]": "N7-10 HERRAMIENTA SIN CAUSA"}),
    ("M14 — la candidata legacy con decisiones ya no impide crear (N6)",
     [(REVIEW_STORE, _m14_candidata_legacy_no_impide)],
     {"test_n6_candidata_legacy_con_decisiones_bloquea_aun_autorizado[1-release_previa]": "N6 NO BLOQUEO",
      "test_n6_legacy_ambiguo_tampoco_se_decide_a_ciegas": "N6 AMBIGUO NO BLOQUEO"}),
    ("M15 — la autorización con la BD presente ya no se ignora ni se anota (N14)",
     [(REVIEW_STORE, _m15_autorizacion_con_la_bd_presente)],
     {"test_n14_autorizacion_con_la_bd_presente_se_ignora_y_se_anota": "N14 IGNORADA SIN ANOTAR"}),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de calibrar "
              "(la restauración escribe sobre el fichero).")
        return 2

    rc, salida = _correr_testigo()
    cifras = _recuento(salida)
    if rc != 0 or not _ejecutado_de_verdad(cifras):
        print("ABORTA: los testigos no están verdes y ejecutados en la base "
              "(PYTEST_RC=%s, cifras=%s)" % (rc, cifras))
        print(salida[-3000:])
        return 2
    print("BASE: testigos verdes, PYTEST_RC=%s, cifras=%s\n" % (rc, cifras))

    veredictos = []
    for nombre, cambios, esperadas in MUTACIONES:
        originales = {}
        mutados = {}
        roto = False
        for fichero, mutador in cambios:
            original = (RAIZ / fichero).read_text(encoding="utf-8")
            mutado = mutador(original)
            if mutado is None or mutado == original or not _valido(fichero, mutado):
                roto = True
                print("### %s\n  DETECTOR ROTO: la mutación no se pudo aplicar sobre %s "
                      "(ancla ausente/ambigua o resultado inválido). Un verde aquí "
                      "sería FALSO.\n" % (nombre, fichero))
                break
            originales[fichero] = original
            mutados[fichero] = mutado
        if roto:
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue
        try:
            for fichero, texto in mutados.items():
                (RAIZ / fichero).write_text(texto, encoding="utf-8")
            rc_mut, salida_mut = _correr_testigo()
        finally:
            for fichero, texto in originales.items():
                (RAIZ / fichero).write_text(texto, encoding="utf-8")
            _purgar_pycache()
        cifras_mut = _recuento(salida_mut)
        fallos = _fallos(salida_mut)
        causas = {p: (p in fallos and frag in fallos[p]) for p, frag in esperadas.items()}
        limpio = _arbol_limpio_tracked()
        rc_post, salida_post = _correr_testigo()
        cifras_post = _recuento(salida_post)

        print("### %s" % nombre)
        print("  ficheros             : %s" % ", ".join(f for f, _ in cambios))
        print("  PYTEST_RC mutado     : %s  (esperado != 0)" % rc_mut)
        print("  cifras mutado        : %s  (skipped/errores esperados 0)" % cifras_mut)
        print("  pruebas en rojo      : %s" % sorted(fallos))
        for p, ok in causas.items():
            print("  causa %s %s: esperado %r -> %r" % (
                "OK " if ok else "MAL", p, esperadas[p], fallos.get(p, "(no falló)")[:300]))
        print("  restaurado (tracked limpio): %s" % limpio)
        print("  restaurado (PYTEST_RC post): %s, cifras %s" % (rc_post, cifras_post))
        ok = (rc_mut != 0 and _ejecutado_de_verdad(cifras_mut) and len(fallos) > 0
              and all(causas.values()) and limpio and rc_post == 0
              and _ejecutado_de_verdad(cifras_post))
        print("  VEREDICTO            : %s\n" % ("CALIBRADA" if ok else "NO CALIBRADA"))
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print("  %-14s %s" % (v, nombre))
    total = sum(1 for _, v in veredictos if v == "CALIBRADA")
    print("  TOTAL: %d/%d" % (total, len(MUTACIONES)))
    return 0 if total == len(MUTACIONES) else 1


if __name__ == "__main__":
    sys.exit(main())
