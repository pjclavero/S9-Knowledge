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
  deploy/tests/test_h06_h08_autoridad_y_worker.py
  viewer/tests/test_h06_h08_estado_privado.py

Mutaciones (M1–M12 del contrato §17 + refuerzo M13–M15 + fase 2 M16–M18):

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
  M16–M18 (fase 2) validación opcional · SECRET 0644 · backup dentro del state

RONDA 2 (tras la revisión NO APTO): M19–M24 H-1 (CLIs/escritores como root y modos de la
umask; M24 = R14), M25–M28 H-2 (bóveda: modo, apropiación, respaldo, huérfanos), M29–M41
C-1…C-7 (M39 = R8, M40 = R13, M38 = la línea duplicada de M1) y M42–M45 los mutantes
supervivientes del revisor (R2, R3, R10, R12). M1/M2/M6 usan `mutar_clave_unidad`: una
clave de identidad DUPLICADA en la unidad es DETECTOR ROTO, no «la primera».

Testigos de la ronda 2 (cada uno en su proceso): deploy/tests/test_h06_h08_cli_root.py,
deploy/tests/test_h06_h08_ronda2_contrato.py, viewer/tests/test_h06_h08_vault_no_escribible.py.

LOCALIZADORES: Python con `localizadores.mutar_en_funcion` (AST, ancla única
DENTRO de la función); bash, unidades y YAML con `mutar_unico` (ancla ÚNICA en
el fichero; no tienen AST que usar aquí) y `bash -n` sobre el resultado. Ancla
ausente o ambigua = DETECTOR ROTO, nunca «la primera». Nada de `.replace(...,1)`
ni de orden de texto.

REGLAS DE USO (memoria del programa): NO en la máquina de orquestación (ia-server);
EN SERIE (nunca dos calibradores a la vez sobre el mismo árbol); con el árbol
COMMITEADO (la restauración escribe sobre el fichero). `--solo-aplicar` comprueba
SOLO que las anclas (45) se aplican (sin ejecutar pytest): es lo único que se
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
T_DE = "deploy/tests/test_h06_h08_autoridad_y_worker.py"
T_VIEWER = "viewer/tests/test_h06_h08_estado_privado.py"
# ronda 2
T_CLI = "deploy/tests/test_h06_h08_cli_root.py"
T_R2 = "deploy/tests/test_h06_h08_ronda2_contrato.py"
T_VAULT = "viewer/tests/test_h06_h08_vault_no_escribible.py"
TESTIGOS = [T_DEPLOY, T_INV, T_C1, T_DE, T_VIEWER, T_CLI, T_R2, T_VAULT]

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
CLI_HEALTH = "viewer/app/cli/health.py"
CLI_JOBS = "data-engine/app/cli/jobs.py"
GLOSSARY_STORE = "data-engine/app/glossary/glossary_store.py"
VAULT_WRITER = "viewer/app/vault_writer.py"
HEALTH_CHECKS = "viewer/app/health/checks.py"


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

def _clave_de_linea(linea: str):
    s = linea.strip()
    if not s or s[0] in "#;" or "=" not in s:
        return None
    return s.split("=", 1)[0].strip()


def mutar_clave_unidad(texto: str, clave: str, nueva_linea, *, insertar_despues: bool = False):
    """Localizador ESTRUCTURAL de unidades systemd (ronda 2, C-7): la ÚNICA línea de
    ``[Service]`` cuya clave (con la semántica de systemd: espacios alrededor de ``=``) es
    ``clave``. Cero o MÁS de una -> ``None`` (DETECTOR ROTO): una línea de identidad
    duplicada YA es un defecto, y mutar "la primera" sería medir la equivocada (el
    revisor plantó ``User=`` dos veces y el localizador por subcadena no lo vio).
    ``nueva_linea=None`` borra la línea; ``insertar_despues`` añade ``nueva_linea`` tras ella.
    """
    lineas = texto.splitlines(keepends=True)
    seccion, sitios = None, []
    for i, l in enumerate(lineas):
        s = l.strip()
        if s.startswith("[") and s.endswith("]"):
            seccion = s[1:-1]
            continue
        if seccion == "Service" and _clave_de_linea(l) == clave:
            sitios.append(i)
    if len(sitios) != 1:
        return None
    i = sitios[0]
    if insertar_despues:
        lineas.insert(i + 1, nueva_linea + "\n")
    elif nueva_linea is None:
        del lineas[i]
    else:
        lineas[i] = nueva_linea + "\n"
    return "".join(lineas)


def _m1_visor_root(t):
    return mutar_clave_unidad(t, "User", "User=root")


def _m2_worker_www_data(t):
    return mutar_clave_unidad(t, "User", "User=www-data")


def _m3_auth_db_0644(t):
    return mutar_en_funcion(t, "_crear_privado_si_falta",
                            "    service_identity.create_private_file(path)\n",
                            "    os.close(os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644))\n")


def _m4_review_0660(t):
    return mutar_en_funcion(t, "_crear", "        os.chmod(db, ss.FILE_MODE)\n",
                            "        os.chmod(db, 0o660)\n")


def _m5_state_dir_0755(t):
    return mutar_en_funcion(t, "_corregir",
                            "            modo = _ss().DIR_MODE if es_dir else _ss().FILE_MODE\n",
                            "            modo = 0o755 if es_dir else _ss().FILE_MODE\n")


def _m6_health_root(t):
    return mutar_clave_unidad(t, "User", "User=root")


def _m7_cli_root(t):
    return mutar_en_funcion(t, "rechazar_si_root",
                            '    return service_identity.service_state().cli_root_rejection("auth")\n',
                            "    return None\n")


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


def _m16_validacion_opcional(t):
    return mutar_en_funcion(t, "enforce", "    if exception_declared(env):\n",
                            "    if exception_declared(env) or not env.get(STATE_ROOT_ENV):\n")


def _m17_secreto_0644(t):
    return mutar_en_funcion(t, "inspect_secret",
                            "    if stat.S_IMODE(st.st_mode) & ~SECRET_FILE_MAX_MODE:\n",
                            "    if stat.S_IMODE(st.st_mode) & ~0o644:\n")


def _m18_backup_dentro_del_state(t):
    return mutar_en_funcion(t, "inspect_backup_root",
                            "    if br == sr or _bajo(br, sr) or _bajo(sr, br):\n",
                            "    if False:\n")


# --- ronda 2: H-1 (CLIs y escritores) -----------------------------------------

def _m19_cli_salud_sin_guarda(t):
    return mutar_en_funcion(t, "main",
                            '    rechazo = service_identity.service_state().cli_root_rejection("health")\n',
                            "    rechazo = None\n")


def _m20_cli_jobs_sin_guarda(t):
    return mutar_unico(t, "    reject_root_cli('jobs')\n", "    pass\n")


def _m21_glosario_con_la_umask(t):
    return mutar_en_funcion(t, "__init__", "        service_state.create_private_file(self.db_path)\n",
                            "        pass\n")


def _m22_sin_estrangulamiento_root(t):
    return mutar_en_funcion(t, "refuse_root_state_write",
                            "    if euid == 0 and _bajo_state_root(ruta, env):\n", "    if False:\n")


def _m23_directorios_con_la_umask(t):
    paso = mutar_en_funcion(t, "ensure_private_dir", "            os.mkdir(d, DIR_MODE)\n",
                            "            os.mkdir(d, 0o755)\n")
    if paso is None:
        return None
    return mutar_en_funcion(paso, "ensure_private_dir", "        os.chmod(d, DIR_MODE)\n", "        pass\n")


def _m24_health_tmp_con_la_umask(t):
    return mutar_en_funcion(t, "save_report",
                            "    fd = service_identity.service_state().open_private_write(tmp)\n",
                            "    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)\n")


# --- ronda 2: H-2 (boveda) ----------------------------------------------------

def _m25_reemplazo_no_conserva_el_modo(t):
    return mutar_en_funcion(t, "_reemplazo_atomico_propio",
                            "            os.fchmod(fd, stat.S_IMODE(st_previo.st_mode))\n",
                            "            pass\n")


def _m26_se_apropia_del_perfil_ajeno(t):
    return mutar_en_funcion(t, "_escribir_atomico",
                            "    if st is not None and not _es_del_proceso(st):\n", "    if False:\n")


def _m27_no_restaura_el_respaldo(t):
    return mutar_en_funcion(t, "_preparar_escritura", "    restaurar_respaldo_pendiente(ruta)\n",
                            "    pass\n")


def _m28_no_limpia_huerfanos(t):
    return mutar_en_funcion(t, "_preparar_escritura", "    limpiar_efimeros_huerfanos(ruta.parent)\n",
                            "    pass\n")


# --- ronda 2: C-1 ... C-7 -----------------------------------------------------

def _m29_validate_env_ignora_backups_en_el_state(t):
    return mutar_en_funcion(t, "main", "            viol += inspect_legacy_backups(args.state_root)\n",
                            "            pass\n")


def _m30_alias_backup_root_ignorado(t):
    return mutar_unico(t, 'BACKUP_ENVS = ("S9K_BACKUP_ROOT", _BACKUP_ENV)\n', "BACKUP_ENVS = (_BACKUP_ENV,)\n")


def _m31_sin_preescaneo(t):
    return mutar_en_funcion(t, "_mover_legacy", "    _preescanear_legacy(rutas, fuentes, res)\n",
                            "    pass\n")


def _m32_duplicado_legacy_distinto_aceptado(t):
    return mutar_en_funcion(t, "_preescanear_legacy", "                if contenido_otro != contenido:\n",
                            "                if False:\n")


def _m33_migracion_sin_state_root_dedicado(t):
    return mutar_en_funcion(t, "aplicar",
                            "        no_dedicado = ss.inspect_dedicated_state_root(state_root, rutas)\n",
                            "        no_dedicado = []\n")


def _m34_sticky_no_se_ve(t):
    return mutar_en_funcion(t, "inspect_dedicated_state_root", "    if modo & stat.S_ISVTX:\n",
                            "    if False:\n")


def _m35_rollback_sin_puerta_de_identidad(t):
    return mutar_unico(t, '    if release_entiende_la_identidad "${prev}"; then\n', "    if true; then\n")


def _m36_deploy_ignora_drop_ins(t):
    return mutar_unico(
        t, "            if grep -vE '^[[:space:]]*[#;]' \"${f}\" | grep -qE 'S9K_STATE_(VALIDATION|ENFORCE)'; then\n"
           "                err \"${unit}: el drop-in",
        "            if false; then\n                err \"${unit}: el drop-in")


def _m37_health_ignora_el_entorno_de_la_unidad(t):
    return mutar_en_funcion(t, "check_state_validation", '                if (v + "=") in env:\n',
                            "                if False:\n")


def _m38_identidad_duplicada_no_se_ve(t):
    return mutar_en_funcion(t, "inspect_unit_identity", "        if n > 1:\n", "        if False:\n")


def _m39_visor_con_ambient_capabilities(t):
    return mutar_clave_unidad(t, "NoNewPrivileges", "AmbientCapabilities=CAP_DAC_READ_SEARCH",
                              insertar_despues=True)


def _m40_worker_no_new_privileges_false(t):
    return mutar_clave_unidad(t, "NoNewPrivileges", "NoNewPrivileges=false")


def _m41_prefijo_mas_aceptado(t):
    return mutar_en_funcion(t, "inspect_unit_identity", '            if "+" in prefijo or "!" in prefijo:\n',
                            "            if False:\n")


# --- ronda 2: testigos de los mutantes del revisor que sobrevivieron ------------

def _m42_r2_la_parada_no_para_el_worker(t):
    return mutar_unico(
        t, '    for unit in "${HEALTH_UNIT_NAME}" "${WORKER_UNIT_NAME_LIB}" "${VIEWER_UNIT_NAME}"; do\n'
           '        if systemctl is-active',
        '    for unit in "${HEALTH_UNIT_NAME}" "${VIEWER_UNIT_NAME}"; do\n        if systemctl is-active')


def _m43_r3_chmod_sin_chown(t):
    return mutar_en_funcion(t, "arreglar", "                os.lchown(ruta, uid, gid)\n", "                pass\n")


def _m44_r10_probe_denied_no_anota_ficheros(t):
    return mutar_en_funcion(
        t, "probe_denied",
        '                out.append(Violation(MODE, candidato, "%s: un usuario ajeno LEE esta "\n',
        '                (Violation(MODE, candidato, "%s: un usuario ajeno LEE esta "\n')


def _m45_r12_acl_ignorada(t):
    return mutar_en_funcion(t, "_revisar_entrada", "    if _acl_presente(path):\n", "    if False:\n")


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
    ("M16 — (fase 2 §12) la validacion de arranque vuelve a ser opcional (fail-open sin configuracion)",
     SERVICE_STATE, _m16_validacion_opcional, T_DE,
     {"test_enforce_N17_sin_state_root_declarado_usa_el_default_y_falla_si_no_es_el_del_estado": "DID NOT RAISE"}),
    ("M17 — (fase 2 §9) la politica SECRET admite 0644",
     SERVICE_STATE, _m17_secreto_0644, T_DE,
     {"test_secret_modo_y_propietario": "0o644"}),
    ("M18 — (fase 2 §10) el backup puede vivir dentro del state root",
     SERVICE_STATE, _m18_backup_dentro_del_state, T_DE,
     {"test_backup_root_separado_del_state": "IndexError"}),
    # ---- ronda 2 · H-1 -------------------------------------------------------
    ("M19 — (H-1) la CLI de salud deja de rechazar a root (health.json root:root)",
     CLI_HEALTH, _m19_cli_salud_sin_guarda, T_VIEWER,
     {"test_N10_la_cli_de_salud_rechaza_root_sin_crear_health_json": "['check']"}),
    ("M20 — (H-1) una CLI del motor (jobs) pierde la guarda de root",
     CLI_JOBS, _m20_cli_jobs_sin_guarda, T_CLI,
     {"test_toda_cli_que_alcanza_estado_llama_a_la_guarda_canonica": "CLI SIN GUARDA",
      "test_N10_cada_cli_como_root_sale_con_4_sin_crear_nada[jobs]": "('jobs'"}),
    ("M21 — (H-1) glossary.db vuelve a nacer con la umask (0644)",
     GLOSSARY_STORE, _m21_glosario_con_la_umask, T_CLI,
     {"test_P8_glossary_por_el_camino_correcto_con_umask_022_crea_0700_0600": "0o644"}),
    ("M22 — (H-1) los escritores dejan de rechazar a root bajo el state root",
     SERVICE_STATE, _m22_sin_estrangulamiento_root, T_CLI,
     {"test_refuse_root_state_write_solo_actua_como_root_y_bajo_el_state_root": "DID NOT RAISE"}),
    ("M23 — (H-1) los directorios de estado vuelven a nacer con la umask (0755)",
     SERVICE_STATE, _m23_directorios_con_la_umask, T_CLI,
     {"test_ensure_private_dir_crea_cada_componente_0700_y_no_toca_lo_existente": "0o755"}),
    ("M24 — (R14) el temporal de health.json nace con la umask (0644) antes de publicarse",
     HEALTH_STORAGE, _m24_health_tmp_con_la_umask, T_VIEWER,
     {"test_R14_health_json_es_0600_ANTES_de_publicarse_con_umask_022": "0o644"}),
    # ---- ronda 2 · H-2 -------------------------------------------------------
    ("M25 — (H-2a) el reemplazo atomico endurece el perfil propio a 0600",
     VAULT_WRITER, _m25_reemplazo_no_conserva_el_modo, T_VAULT,
     {"test_H2a_perfil_propio_conserva_su_modo_y_grupo": "0o600"}),
    ("M26 — (H-2b) vuelve a apropiarse del perfil ajeno (rename en vez de en el sitio)",
     VAULT_WRITER, _m26_se_apropia_del_perfil_ajeno, T_VAULT,
     {"test_H2b_perfil_de_otro_dueno_escribible_se_escribe_en_el_sitio": "inodo/dueño/grupo/modo cambiaron"}),
    ("M27 — (H-2b) la siguiente escritura no restaura el respaldo de un SIGKILL",
     VAULT_WRITER, _m27_no_restaura_el_respaldo, T_VAULT,
     {"test_H2b_SIGKILL_a_mitad_deja_respaldo_y_la_siguiente_escritura_restaura_primero": "EscrituraRechazadaError"}),
    ("M28 — (H-2) los efimeros huerfanos de un SIGKILL no se limpian",
     VAULT_WRITER, _m28_no_limpia_huerfanos, T_VAULT,
     {"test_H2_los_efimeros_huerfanos_de_un_SIGKILL_se_limpian_en_la_siguiente_escritura": ".s9k-probe-"}),
    # ---- ronda 2 · C-1 ... C-7 -------------------------------------------------
    ("M29 — (C-1) <state>/backups con contenido ya no para en las precondiciones",
     SERVICE_STATE, _m29_validate_env_ignora_backups_en_el_state, T_R2,
     {"test_C1_backups_con_contenido_en_el_state_PARA_en_las_precondiciones": "OK"}),
    ("M30 — (C-1) S9K_BACKUP_ROOT dentro del state no se valida (solo el alias antiguo)",
     SERVICE_STATE, _m30_alias_backup_root_ignorado, T_R2,
     {"test_C1_la_raiz_de_backups_dentro_del_state_PARA_por_cualquiera_de_sus_dos_nombres[S9K_BACKUP_ROOT]": "OK"}),
    ("M31 — (C-2) sin pre-escaneo: se mueve antes de ver el symlink legacy",
     MIGRAR, _m31_sin_preescaneo, T_R2,
     {"test_C2_un_symlink_legacy_PARA_sin_mover_el_primer_fichero": "MOVIO ANTES DEL PRE-ESCANEO"}),
    ("M32 — (C-3) estado legacy en dos sitios con contenido DISTINTO se acepta en silencio",
     MIGRAR, _m32_duplicado_legacy_distinto_aceptado, T_R2,
     {"test_C3_estado_legacy_en_dos_sitios_con_contenido_distinto_PARA": "OK"}),
    ("M33 — (C-5) la migracion se apropia de un state root no dedicado (1777, ajeno)",
     MIGRAR, _m33_migracion_sin_state_root_dedicado, T_R2,
     {"test_C5_senuelo_del_revisor_raiz_1777_con_ficheros_ajenos_PARA_sin_tocar_nada": "C5 NO DEDICADO NO VISTO"}),
    ("M34 — (C-5) un state root con sticky bit pasa por dedicado",
     SERVICE_STATE, _m34_sticky_no_se_ve, T_DE,
     {"test_C5_inspect_dedicated_state_root_sticky_y_otros": "C5: sticky no visto"}),
    ("M35 — (C-4) el rollback automatico reactiva una release anterior a H-06",
     LIB_SH, _m35_rollback_sin_puerta_de_identidad, T_R2,
     {"test_C4_rollback_a_una_release_anterior_a_H06_NO_se_reactiva_y_para_los_servicios": "RC=0"}),
    ("M36 — (C-6) deploy no mira los drop-ins (la excepcion de tests entra por la puerta de atras)",
     LIB_SH, _m36_deploy_ignora_drop_ins, T_R2,
     {"test_C6_la_excepcion_en_un_drop_in_PARA": "RC=0"}),
    ("M37 — (C-6) el healthcheck no mira el Environment efectivo de las unidades",
     HEALTH_CHECKS, _m37_health_ignora_el_entorno_de_la_unidad, T_VIEWER,
     {"test_C6_el_healthcheck_es_UNHEALTHY_si_la_excepcion_esta_en_el_entorno_de_una_unidad": "HEALTHY"}),
    ("M38 — (C-7) una clave de identidad duplicada pasa el gate (M1 de linea duplicada)",
     SERVICE_STATE, _m38_identidad_duplicada_no_se_ve, T_R2,
     {"test_C7_el_gate_rechaza_identidad_y_privilegios_con_semantica_de_ultimo_valor[visor-dup-user]": "AssertionError: []"}),
    ("M39 — (R8) la unidad del visor gana AmbientCapabilities",
     U_VISOR, _m39_visor_con_ambient_capabilities, T_R2,
     {"test_C7_R8_R13_las_unidades_reales_no_tienen_hallazgos_de_identidad[visor]": "AmbientCapabilities"}),
    ("M40 — (R13) la unidad del worker con NoNewPrivileges=false",
     U_WORKER, _m40_worker_no_new_privileges_false, T_R2,
     {"test_C7_R8_R13_las_unidades_reales_no_tienen_hallazgos_de_identidad[worker]": "NoNewPrivileges"}),
    ("M41 — (C-7) ExecStart con prefijo '+' (privilegios completos) pasa el gate",
     SERVICE_STATE, _m41_prefijo_mas_aceptado, T_R2,
     {"test_C7_el_gate_rechaza_identidad_y_privilegios_con_semantica_de_ultimo_valor[visor-plus]": "AssertionError: []"}),
    # ---- ronda 2 · testigos de los mutantes supervivientes del revisor ---------
    ("M42 — (R2) la parada previa a migrar no para el worker",
     LIB_SH, _m42_r2_la_parada_no_para_el_worker, T_R2,
     {"test_R2_la_parada_para_visor_worker_y_healthcheck_y_lo_verifica": "PARADA NO VERIFICADA"}),
    ("M43 — (R3) la migracion aplica chmod pero no chown",
     MIGRAR, _m43_r3_chmod_sin_chown, T_R2,
     {"test_R3_la_migracion_hace_chown_de_cada_entrada_ajena_no_solo_chmod": "LCHOWN NO LLAMADO"}),
    ("M44 — (R10) probe_denied deja de anotar los ficheros legibles por otro usuario",
     SERVICE_STATE, _m44_r10_probe_denied_no_anota_ficheros, T_DE,
     {"test_R10_probe_denied_nombra_CADA_fichero_legible_no_solo_la_raiz": "R10: probe_denied no nombra"}),
    ("M45 — (R12) una ACL POSIX presente deja de ser un hallazgo",
     SERVICE_STATE, _m45_r12_acl_ignorada, T_DE,
     {"test_R12_una_ACL_presente_es_un_hallazgo_aunque_el_modo_sea_0600": "R12: ACL no detectada"}),
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
