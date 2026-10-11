#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B2 (USABLE-V1) — arnés de calibración de la familia «fresh install».

Una garantía no cuenta hasta que hay una prueba CAPAZ DE PONERSE ROJA, y roja
POR SU CAUSA. Cada mutación reintroduce UN defecto real de la familia sobre el
código commiteado, corre el testigo (`deploy/tests/test_b2_fresh_install.py`)
y exige:

  - PYTEST_RC != 0 y las pruebas nombradas en rojo, cada una con su
    FRAGMENTO de causa en la línea `FAILED ... - <mensaje>`;
  - que el testigo se ejecutó de verdad: `collected > 0`, `skipped == 0`,
    `errors == 0`, en la base, en cada mutación y tras restaurar;
  - restauración verificada: árbol tracked limpio y PYTEST_RC post = 0.

Las cinco mutaciones del encargo (M1-M5) y cuatro más de la familia:

  M1  deploy.sh vuelve a decidir el paso 4 con GLOBAL_STATE (H-01/H-43)
  M2  `_usable(jobs)` vuelve a exigir jobs > 0 (H-43)
  M3  la plantilla productiva vuelve a `mock` (H-44 / D-MOCK)
  M3b la plantilla del visor vuelve a `mock` (H-44 / D-MOCK)
  M4  CRITICAL_ENV_VARS sin S9K_V3_REVIEW_* (H-04 lado deploy)
  M5  el GATE A acepta `status != 403` (5xx/200 pasarían por CSRF funcional)
  M6  fresh deja de bloquear sobre estado existente (sobrescribir / corrupta)
  M7  el CSRF ausente vuelve a bloquear el despliegue (H-49, contradice #248)
  M8  deploy.sh deja de invocar `preflight_ensayo_rc.py --grupo despliegue`
  M9  la cadena de estados promociona sin la evidencia de un eslabón

LOCALIZADORES
-------------
Python: `localizadores.mutar_en_funcion` (AST; DETECTOR ROTO si el ancla no
es única dentro de la función). Bash y plantillas: `localizadores.mutar_unico`
—sustitución de TEXTO con ancla ÚNICA EN EL FICHERO (bash no tiene AST que
usar aquí)— y se comprueba `bash -n` sobre el resultado. Si un ancla deja de
ser única, la mutación da DETECTOR ROTO, nunca muta «la primera».

TECHO DE ESTE CALIBRADOR
------------------------
* Muta por sustitución de texto exacto; no ve alias ni una segunda copia de la
  lógica en otro módulo.
* Calibra el testigo RÁPIDO. El testigo E2E local
  (`deploy/tests/test_b2_primera_release.py`, visor real por TLS) no se
  re-ejecuta por mutación: cuesta un arranque de uvicorn por caso.
* Nada de esto es el ensayo RC (nginx, systemd, VM limpia): RC-E2E PENDING.

Uso: python3 scripts/calibracion/mutaciones_b2_fresh_install.py
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
TESTIGO = "deploy/tests/test_b2_fresh_install.py"
DEPLOY_SH = "deploy/scripts/deploy.sh"
DETECT = "deploy/scripts/detect_state.py"
VALIDATE = "deploy/scripts/validate_deploy.sh"
PLANTILLA_PROD = "deploy/config/viewer.env.example"
PLANTILLA_VISOR = "viewer/.env.example"
SETUP_ADMIN = "deploy/scripts/preflight_setup_admin.py"
ESTADOS = "deploy/scripts/estado_instalacion.py"


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
        [sys.executable, "-m", "pytest", TESTIGO, "-q", "--no-header",
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

def _m1_paso4_por_global_state(texto: str):
    # El defecto de origen tal cual: el case sobre GLOBAL_STATE delante.
    return mutar_unico(
        texto,
        'paso4_migrar_o_validar_estado "${STATE_JSON}"\n',
        'case "${GLOBAL_STATE}" in\n'
        '    EMPTY_STATE|CONFLICTING_STATE|CORRUPT_STATE)\n'
        '        die "estado ${GLOBAL_STATE}: BLOQUEA (nunca crear auth.db vacía ni elegir DB en silencio)" ;;\n'
        'esac\n'
        'paso4_migrar_o_validar_estado "${STATE_JSON}"\n',
    )


def _m2_usable_jobs_exige_filas(texto: str):
    return mutar_en_funcion(texto, "_usable",
                            '        return counts.get("jobs") is not None',
                            '        return (counts.get("jobs") or 0) > 0')


def _m3_plantilla_mock(texto: str):
    return mutar_unico(texto, "S9K_GRAPH_PROVIDER=not_configured\n", "S9K_GRAPH_PROVIDER=mock\n")


def _m4_criticas_sin_revision(texto: str):
    return mutar_unico(
        texto,
        'S9K_AUTH_ENABLED S9K_V3_REVIEW_DATABASE_PATH S9K_V3_REVIEW_PROPOSALS_DIR"',
        'S9K_AUTH_ENABLED"')


def _m5_gate_a_status_distinto_de_403(texto: str):
    return mutar_en_funcion(
        texto, "comprobar_csrf_funcional",
        "    if estado == 400 and MENSAJE_VALIDACION_USUARIO_VACIO in html \\",
        "    if estado != 403 or MENSAJE_VALIDACION_USUARIO_VACIO in html \\")


def _m6_fresh_no_bloquea(texto: str):
    return mutar_en_funcion(texto, "detect",
                            '            if d["state"] in _BLOCKING_FRESH.get(kind, set()):',
                            '            if False:')


def _m7_csrf_ausente_bloquea(texto: str):
    return mutar_unico(
        texto,
        "autogenera (0600) junto a la auth DB en el primer arranque\\n' >&2\n        return 0\n",
        "autogenera (0600) junto a la auth DB en el primer arranque\\n' >&2\n        return 1\n")


def _m8_deploy_sin_preflight_de_revision(texto: str):
    return mutar_unico(
        texto,
        'python3 "${HERE}/preflight_ensayo_rc.py" --grupo despliegue \\\n',
        'true || python3 "${HERE}/preflight_ensayo_rc.py" --grupo despliegue \\\n')


def _m9_estado_se_salta_un_eslabon(texto: str):
    return mutar_en_funcion(
        texto, "estado_alcanzado",
        "        if not all(_verdadera(evidencia, e) for e in EVIDENCIA_POR_ESTADO[estado]):\n            break",
        "        if not all(_verdadera(evidencia, e) for e in EVIDENCIA_POR_ESTADO[estado]):\n            continue")


_PROMOCION = "test_ningun_estado_se_promociona_sin_toda_la_evidencia"

MUTACIONES = [
    ("M1 — deploy.sh vuelve a decidir el paso 4 con GLOBAL_STATE (H-01/H-43)",
     DEPLOY_SH, _m1_paso4_por_global_state,
     {"test_paso4_fresh_en_maquina_limpia_no_bloquea_por_la_ausencia_esperada": "H-01",
      "test_paso4_upgrade_con_jobs_ausente_o_vacia_no_bloquea[ausente]": "H-43",
      "test_paso4_ya_no_decide_por_el_estado_global": "GLOBAL_STATE"}),
    ("M2 — `_usable(jobs)` vuelve a exigir jobs > 0 (H-43)",
     DETECT, _m2_usable_jobs_exige_filas,
     {"test_h43_una_jobs_db_vacia_es_estado_usable_no_empty": "H-43"}),
    ("M3 — la plantilla productiva vuelve a `mock` (H-44 / D-MOCK)",
     PLANTILLA_PROD, _m3_plantilla_mock,
     {"test_la_plantilla_de_fabrica_no_arranca_en_mock[deploy-viewer.env.example]": "D-MOCK"}),
    ("M3b — la plantilla del visor vuelve a `mock` (H-44 / D-MOCK)",
     PLANTILLA_VISOR, _m3_plantilla_mock,
     {"test_la_plantilla_de_fabrica_no_arranca_en_mock[viewer-.env.example]": "D-MOCK"}),
    ("M4 — CRITICAL_ENV_VARS sin S9K_V3_REVIEW_* (H-04 lado deploy)",
     VALIDATE, _m4_criticas_sin_revision,
     {"test_critical_env_vars_incluye_el_estado_de_revision": "H-04",
      "test_paso6_sin_estado_de_revision_bloquea_con_la_causa[S9K_V3_REVIEW_DATABASE_PATH]": "NOMBRAR",
      "test_paso6_sin_estado_de_revision_bloquea_con_la_causa[S9K_V3_REVIEW_PROPOSALS_DIR]": "NOMBRAR"}),
    ("M5 — el GATE A acepta `status != 403` (un 5xx pasaría por CSRF funcional)",
     SETUP_ADMIN, _m5_gate_a_status_distinto_de_403,
     {"test_gate_a_no_acepta_lo_que_no_es_la_validacion[500-ERROR_DE_SERVIDOR]": "status != 403",
      "test_gate_a_no_acepta_lo_que_no_es_la_validacion[200-VALIDACION_INESPERADA]": "status != 403",
      "test_gate_a_400_sin_el_mensaje_exacto_no_basta": "VALIDACION_INESPERADA"}),
    ("M6 — fresh deja de bloquear sobre estado existente (usuarios o corrupta)",
     DETECT, _m6_fresh_no_bloquea,
     {"test_fresh_con_usuarios_bloquea": "BLOCK",
      "test_paso4_fresh_sobre_auth_con_usuarios_bloquea_y_no_toca_nada": "NO BLOQUEO",
      # Una corrupta en fresh la sigue parando el `*) die ... incoherente`
      # del paso 4 (defensa propia de lib.sh): el rojo se lee en detect.
      "test_corrupta_bloquea_en_los_dos_modos[fresh]": "BLOCK"}),
    ("M7 — el CSRF ausente vuelve a bloquear el despliegue (H-49, contradice #248)",
     VALIDATE, _m7_csrf_ausente_bloquea,
     {"test_paso6_acepta_la_plantilla_productiva_literal": "plantilla productiva copiada tal cual"}),
    ("M8 — deploy.sh deja de invocar preflight_ensayo_rc --grupo despliegue (H-04/H-18)",
     DEPLOY_SH, _m8_deploy_sin_preflight_de_revision,
     {"test_paso6_estado_de_revision_fuera_del_state_root_bloquea": "NO BLOQUEO"}),
    ("M9 — la cadena de estados promociona sin la evidencia de un eslabón",
     ESTADOS, _m9_estado_se_salta_un_eslabon,
     {_PROMOCION + "[evidencia5-FIRST_ADMIN_PENDING]": "INSTALLATION_COMPLETE",
      _PROMOCION + "[evidencia6-DEPLOY_OK]": "INSTALLATION_COMPLETE"}),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de calibrar "
              "(la restauración escribe sobre el fichero).")
        return 2

    rc, salida = _correr_testigo()
    cifras = _recuento(salida)
    if rc != 0 or not _ejecutado_de_verdad(cifras):
        print("ABORTA: el testigo no está verde y ejecutado en la base "
              "(PYTEST_RC=%s, cifras=%s)" % (rc, cifras))
        print(salida[-3000:])
        return 2
    print("BASE: testigo verde, PYTEST_RC=%s, cifras=%s\n" % (rc, cifras))

    veredictos = []
    for nombre, fichero, mutador, esperadas in MUTACIONES:
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
            rc_mut, salida_mut = _correr_testigo()
        finally:
            f.write_text(original, encoding="utf-8")
            _purgar_pycache()
        cifras_mut = _recuento(salida_mut)
        fallos = _fallos(salida_mut)
        causas = {p: (p in fallos and frag in fallos[p]) for p, frag in esperadas.items()}
        limpio = _arbol_limpio_tracked()
        rc_post, salida_post = _correr_testigo()
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
    print("  TOTAL: %d/%d" % (total, len(MUTACIONES)))
    return 0 if total == len(MUTACIONES) else 1


if __name__ == "__main__":
    sys.exit(main())
