#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H-06 + H-08 (USABLE-V1) — arnés de calibración del usuario de servicio y el estado privado.

Una garantía no cuenta hasta que hay una prueba CAPAZ DE PONERSE ROJA, y roja
POR SU CAUSA. Cada mutación reintroduce UN defecto real de H-06/H-08 sobre el
código commiteado, corre las pruebas nombradas de sus testigos y exige:

  - PYTEST_RC != 0 y cada prueba nombrada en rojo con su FRAGMENTO de causa en
    la línea `FAILED ... - <mensaje>`;
  - que el testigo se ejecutó de verdad: `collected > 0`, `skipped == 0`,
    `errors == 0`, en la base, en cada mutación y tras restaurar;
  - restauración verificada: árbol tracked limpio y PYTEST_RC post = 0.

Testigos (cada uno en su PROPIO proceso de pytest: visor y motor publican dos
paquetes `app` y no se mezclan):
  deploy/tests/test_h06_h08_servicio_y_estado.py     (unidades, Ansible, migrar_estado, deploy.sh)
  deploy/tests/test_h06_h08_inventario_escrituras.py (inventario estructural de escrituras)
  deploy/tests/test_c1_revision_deploy.py            (regresión de C1)
  data-engine/app/tests/test_h06_h08_autoridad_y_worker.py
  viewer/tests/test_h06_h08_estado_privado.py

Mutaciones (M1–M12 del contrato §17 + tres de refuerzo):

  M1  el visor vuelve a correr como root (unidad sin/otro `User=`)
  M2  el worker vuelve a `www-data`
  M3  `auth.db` nace 0644 (modo del código del producto)
  M4  `review.sqlite3` vuelve a 0660
  M5  el state dir se deja 0755 (la migración deja de fijar el modo de directorios)
  M6  el healthcheck vuelve a root
  M7  la CLI de auth deja de rechazar a root (escribe estado como root)
  M8  `decisions.jsonl` vuelve a caer en la release
  M9  se elimina la comprobación de PROPIETARIO del estado
  M10 el upgrade omite chown/chmod (la migración no corrige nada)
  M11 `deploy.sh` no para si la migración falla (`|| die` -> `|| warn`)
  M12 segunda autoridad: Ansible declara otra identidad que la unidad/autoridad
  M13 (refuerzo) una escritura persistente nueva sin declarar en el inventario
  M14 (refuerzo) el visor deja de ejecutar la comprobación de arranque
  M15 (refuerzo) el rollback vuelve a restaurar una unidad de identidad anterior

LOCALIZADORES: Python con `localizadores.mutar_en_funcion` (AST, ancla única
DENTRO de la función); bash, unidades y YAML con `mutar_unico` (ancla ÚNICA en
el fichero; no tienen AST que usar aquí) y `bash -n` sobre el resultado. Ancla
ausente o ambigua = DETECTOR ROTO, nunca «la primera». Nada de `.replace(...,1)`
ni de orden de texto.

REGLAS DE USO (memoria del programa): NO en la máquina de orquestación (ia-server);
EN SERIE (nunca dos calibradores a la vez sobre el mismo árbol); con el árbol
COMMITEADO (la restauración escribe sobre el fichero). `--solo-aplicar` comprueba
SOLO que las 15 anclas se aplican (sin ejecutar pytest): es lo único que se
ejecuta en la máquina de orquestación.

TECHO: no ejerce systemd ni root reales; muta por sustitución de texto exacto y no
ve una segunda copia de la lógica fuera del fichero mutado.

Uso: python3 scripts/calibracion/mutaciones_h06_h08_servicio_y_estado.py [--solo-aplicar]
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

T_DEPLOY = "deploy/tests/test_h06_h08_servicio_y_estado.py"
T_INV = "deploy/tests/test_h06_h08_inventario_escrituras.py"
T_C1 = "deploy/tests/test_c1_revision_deploy.py"
T_DE = "data-engine/app/tests/test_h06_h08_autoridad_y_worker.py"
T_VIEWER = "viewer/tests/test_h06_h08_estado_privado.py"
TESTIGOS = [T_DEPLOY, T_INV, T_C1, T_DE, T_VIEWER]

U_VISOR = "viewer/systemd/s9-knowledge-viewer.service"
U_WORKER = "data-engine/systemd/s9-knowledge-worker.service"
U_HEALTH = "viewer/systemd/s9-knowledge-healthcheck.service"
AUTH_DB = "viewer/app/auth/db.py"
REVIEW_STORE = "deploy/scripts/review_store.py"
MIGRAR = "deploy/scripts/migrar_estado.py"
CLI_AUTH = "viewer/app/cli/auth.py"
V3_REVIEW = "viewer/app/services/v3_review.py"
SERVICE_STATE = "data-engine/app/knowledge_v3/service_state.py"
DEPLOY_SH = "deploy/scripts/deploy.sh"
GROUP_VARS = "deploy/ansible/group_vars/all.yml"
HEALTH_STORAGE = "viewer/app/health/storage.py"
MAIN_VISOR = "viewer/app/main.py"
LIB_SH = "deploy/scripts/lib.sh"


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


def _correr(testigo: str, nombres: list | None = None):
    _purgar_pycache()
    cmd = [sys.executable, "-m", "pytest", testigo, "-q", "--no-header", "--color=no",
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


def _ejecutado_de_verdad(cifras: dict, permite_skip: bool = False) -> bool:
    recogidas = sum(cifras.get(k, 0) for k in ("passed", "failed", "skipped", "error"))
    return recogidas > 0 and (permite_skip or cifras.get("skipped", 0) == 0) and cifras.get("error", 0) == 0


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
    if fichero.endswith((".yml", ".yaml")):
        try:
            import yaml  # noqa: PLC0415
            yaml.safe_load(texto)
            return True
        except Exception:  # noqa: BLE001
            return False
    return True


# ---------------------------------------------------------------------------
# Mutaciones
# ---------------------------------------------------------------------------

def _m1_visor_root(t):
    return mutar_unico(t, "\nUser=s9knowledge\n", "\nUser=root\n")


def _m2_worker_www_data(t):
    return mutar_unico(t, "\nUser=s9knowledge\n", "\nUser=www-data\n")


def _m3_auth_db_0644(t):
    return mutar_en_funcion(t, "_crear_privado_si_falta",
                            "                     service_identity.file_mode())\n",
                            "                     0o644)\n")


def _m4_review_0660(t):
    return mutar_en_funcion(t, "_crear", "        os.chmod(db, ss.FILE_MODE)\n",
                            "        os.chmod(db, 0o660)\n")


def _m5_state_dir_0755(t):
    return mutar_en_funcion(t, "_corregir",
                            "            modo = _ss().DIR_MODE if es_dir else _ss().FILE_MODE\n",
                            "            modo = 0o755 if es_dir else _ss().FILE_MODE\n")


def _m6_health_root(t):
    return mutar_unico(t, "\nUser=s9knowledge\n", "\nUser=root\n")


def _m7_cli_root(t):
    return mutar_en_funcion(t, "rechazar_si_root", "    if os.geteuid() != 0:\n",
                            "    if True:\n")


def _m8_decisions_en_release(t):
    return mutar_en_funcion(t, "default_decisions_path",
                            "    if derivada is not None:\n",
                            "    if derivada is not None and False:\n")


def _m9_sin_comprobacion_de_owner(t):
    return mutar_en_funcion(
        t, "_revisar_entrada",
        "    if (uid is not None and st.st_uid != uid) or (gid is not None and st.st_gid != gid):\n",
        "    if False:\n")


def _m10_upgrade_sin_chown_chmod(t):
    paso1 = mutar_en_funcion(t, "_corregir", "    arreglar(raiz, True)\n", "    pass\n")
    if paso1 is None:
        return None
    return mutar_en_funcion(paso1, "_corregir", "            arreglar(e.path, es_dir)\n",
                            "            pass\n")


def _m11_deploy_afirma_exito(t):
    return mutar_unico(
        t, '|| die "migración del estado a ${SERVICE_USER} PARADA (causa arriba)',
        '|| warn "migración del estado a ${SERVICE_USER} PARADA (causa arriba)')


def _m12_segunda_autoridad(t):
    return mutar_unico(t, "s9k_service_user: s9knowledge\n", "s9k_service_user: www-data\n")


def _m13_escritura_sin_declarar(t):
    return mutar_en_funcion(
        t, "load_last",
        "    if not path.exists():\n        return None\n",
        "    open('/tmp/h06-escritura-nueva', 'w').close()\n    if not path.exists():\n        return None\n")


def _m14_visor_sin_comprobacion_de_arranque(t):
    return mutar_unico(t, "    service_identity.service_state().enforce(\"viewer\")\n",
                       "    pass\n")


def _m15_rollback_restaura_identidad_anterior(t):
    return mutar_unico(
        t, '    if [ -f "${respaldo}" ] && ! _unidad_con_identidad_vigente "${respaldo}"; then\n',
        '    if [ -f "${respaldo}" ] && false; then\n')


#: (nombre, fichero mutado, mutador, testigo, {prueba: fragmento de la causa})
MUTACIONES = [
    ("M1 — el visor vuelve a correr como root (User=root)",
     U_VISOR, _m1_visor_root, T_DEPLOY,
     {"test_N7_N8_N9_las_unidades_declaran_la_identidad_de_la_autoridad[visor]": "'root'"}),
    ("M2 — el worker vuelve a www-data",
     U_WORKER, _m2_worker_www_data, T_DEPLOY,
     {"test_N7_N8_N9_las_unidades_declaran_la_identidad_de_la_autoridad[worker]": "'www-data'"}),
    ("M3 — auth.db nace 0644",
     AUTH_DB, _m3_auth_db_0644, T_VIEWER,
     {"test_auth_db_nace_0600_en_directorio_0700_con_umask_022": "0o644"}),
    ("M4 — review.sqlite3 vuelve a 0660",
     REVIEW_STORE, _m4_review_0660, T_DEPLOY,
     {"test_C1_review_store_crea_0600_en_directorio_0700_con_umask_022": "0o660"}),
    ("M5 — la migración deja los directorios del estado en 0755",
     MIGRAR, _m5_state_dir_0755, T_DEPLOY,
     {"test_P9_upgrade_legacy_conserva_el_estado_y_lo_deja_privado": "0755"}),
    ("M6 — el healthcheck vuelve a root",
     U_HEALTH, _m6_health_root, T_DEPLOY,
     {"test_N7_N8_N9_las_unidades_declaran_la_identidad_de_la_autoridad[health]": "'root'"}),
    ("M7 — la CLI de auth deja de rechazar a root (escribiría estado como root:root)",
     CLI_AUTH, _m7_cli_root, T_VIEWER,
     {"test_N10_la_cli_rechaza_root_y_muestra_el_comando_canonico": "None",
      "test_N10b_root_no_llega_a_crear_estado": "== 4"}),
    ("M8 — decisions.jsonl vuelve a caer en la release",
     V3_REVIEW, _m8_decisions_en_release, T_VIEWER,
     {"test_decisions_jsonl_ya_no_cae_en_la_release_si_el_despliegue_declara_review_db": "decisions.jsonl"}),
    ("M9 — se elimina la comprobación de propietario",
     SERVICE_STATE, _m9_sin_comprobacion_de_owner, T_DE,
     {"test_N2_owner_distinto_del_esperado_dice_owner_real_y_esperado": "OWNER",
      "test_enforce_N2_owner_incorrecto_dice_esperado_s9knowledge": "esperado s9knowledge"}),
    ("M10 — el upgrade omite chown/chmod",
     MIGRAR, _m10_upgrade_sin_chown_chmod, T_DEPLOY,
     {"test_P9_upgrade_legacy_conserva_el_estado_y_lo_deja_privado": "MODE",
      "test_P11_un_reinicio_con_modos_degradados_se_corrige": "MODE"}),
    ("M11 — deploy.sh sigue adelante (avisa) si la migración falla",
     DEPLOY_SH, _m11_deploy_afirma_exito, T_DEPLOY,
     {"test_N12_cada_paso_de_la_migracion_falla_con_die_y_nunca_afirma_exito": "MIGRACION SIN DIE"}),
    ("M12 — segunda autoridad: Ansible declara otra identidad que unidades y autoridad",
     GROUP_VARS, _m12_segunda_autoridad, T_DEPLOY,
     {"test_M12_ansible_declara_la_misma_identidad_una_sola_vez": "www-data"}),
    ("M13 — escritura persistente nueva sin declarar en el inventario",
     HEALTH_STORAGE, _m13_escritura_sin_declarar, T_INV,
     {"test_ninguna_escritura_persistente_nueva_fuera_de_lo_declarado": "ESCRITURA PERSISTENTE NUEVA"}),
    ("M14 — el visor no ejecuta la comprobación de arranque (fail-open)",
     MAIN_VISOR, _m14_visor_sin_comprobacion_de_arranque, T_VIEWER,
     {"test_el_startup_del_visor_llama_a_la_comprobacion_antes_de_abrir_la_auth_db": "pass"}),
    ("M15 — el rollback vuelve a restaurar una unidad de identidad anterior a H-06",
     LIB_SH, _m15_rollback_restaura_identidad_anterior, T_DEPLOY,
     {"test_ROLLBACK_efecto_no_restaura_una_unidad_de_identidad_anterior[www-data]": "ROLLBACK RESTAURA IDENTIDAD ANTERIOR"}),
]


def main() -> int:
    if "--solo-aplicar" in sys.argv[1:]:
        return _solo_aplicar()
    inicio = time.monotonic()
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de calibrar "
              "(la restauración escribe sobre el fichero).")
        return 2

    # Base: cada testigo en su propio proceso. Se admiten skips (setfacl, root...) pero
    # tiene que haberse EJECUTADO algo y sin errores ni rojos.
    for testigo in TESTIGOS:
        rc, salida = _correr(testigo)
        cifras = _recuento(salida)
        if rc != 0 or not _ejecutado_de_verdad(cifras, permite_skip=True):
            print("ABORTA: el testigo %s no está verde y ejecutado en la base "
                  "(PYTEST_RC=%s, cifras=%s)" % (testigo, rc, cifras))
            print(salida[-3000:])
            return 2
        print("BASE %-62s PYTEST_RC=%s cifras=%s" % (testigo, rc, cifras))
    print()

    veredictos = []
    for nombre, fichero, mutador, testigo, esperadas in MUTACIONES:
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
            rc_mut, salida_mut = _correr(testigo, list(esperadas))
        finally:
            f.write_text(original, encoding="utf-8")
            _purgar_pycache()
        cifras_mut = _recuento(salida_mut)
        fallos = _fallos(salida_mut)
        causas = {p: (p in fallos and frag in fallos[p]) for p, frag in esperadas.items()}
        limpio = _arbol_limpio_tracked()
        rc_post, salida_post = _correr(testigo, list(esperadas))
        cifras_post = _recuento(salida_post)

        print("### %s" % nombre)
        print("  fichero              : %s" % fichero)
        print("  testigo              : %s" % testigo)
        print("  PYTEST_RC mutado     : %s  (esperado != 0)" % rc_mut)
        print("  cifras mutado        : %s  (errores esperados 0)" % cifras_mut)
        print("  pruebas en rojo      : %s" % sorted(fallos))
        for p, ok in causas.items():
            print("  causa %s %s: esperado %r -> %r" % (
                "OK " if ok else "MAL", p, esperadas[p], fallos.get(p, "(no falló)")[:300]))
        print("  restaurado (tracked limpio): %s" % limpio)
        print("  restaurado (PYTEST_RC post): %s, cifras %s" % (rc_post, cifras_post))
        ok = (rc_mut != 0 and _ejecutado_de_verdad(cifras_mut, permite_skip=True)
              and cifras_mut.get("error", 0) == 0 and all(causas.values())
              and limpio and rc_post == 0 and _ejecutado_de_verdad(cifras_post, permite_skip=True))
        print("  VEREDICTO            : %s\n" % ("CALIBRADA" if ok else "NO CALIBRADA"))
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print("  %-14s %s" % (v, nombre))
    total = sum(1 for _, v in veredictos if v == "CALIBRADA")
    print("  TOTAL: %d/%d  (%.0f s)" % (total, len(MUTACIONES), time.monotonic() - inicio))
    return 0 if total == len(MUTACIONES) else 1


def _solo_aplicar() -> int:
    """Comprueba SOLO que cada ancla se aplica y deja un fichero válido (sin pytest)."""
    malas = []
    for nombre, fichero, mutador, _testigo, _esperadas in MUTACIONES:
        original = (RAIZ / fichero).read_text(encoding="utf-8")
        mutado = mutador(original)
        bien = mutado is not None and mutado != original and _valido(fichero, mutado)
        print("%-14s %s" % ("APLICA" if bien else "DETECTOR ROTO", nombre))
        if not bien:
            malas.append(nombre)
    print("TOTAL: %d/%d anclas aplicables" % (len(MUTACIONES) - len(malas), len(MUTACIONES)))
    return 0 if not malas else 1


if __name__ == "__main__":
    sys.exit(main())
