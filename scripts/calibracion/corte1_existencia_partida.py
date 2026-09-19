#!/usr/bin/env python3
"""CORTE 1 — arnés de calibración. Una garantía no cuenta hasta que hay una
prueba capaz de ponerse ROJA POR LA CAUSA CORRECTA.

Aplica mutaciones de una en una sobre el árbol COMMITEADO, corre el testigo y
comprueba tres cosas por mutación:

  1. que la suite se pone roja (color),
  2. QUÉ pruebas fallan (no basta con que falle algo),
  3. que el MENSAJE del rojo dice la causa esperada (un rojo por la causa
     equivocada se lee igual que uno legítimo).

Y después restaura, **comprobando la restauración POR EFECTO**: árbol limpio en
lo TRACKED *y* la suite verde otra vez. Purga `__pycache__` antes de cada
ejecución: en esta sesión un `.pyc` de igual tamaño sobrevivió a un revert y el
intérprete siguió ejecutando el código mutado con `git status` limpio.

Uso: python3 scripts/calibracion/corte1_existencia_partida.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "viewer/tests/test_corte1_existencia_canonica_partida.py"


def _sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    """El trinquete mira lo TRACKED: es lo que la mutación puede destruir."""
    r = _sh(["git", "status", "--porcelain", "--untracked-files=no"])
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigo() -> tuple[int, str]:
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TESTIGO, "-q", "--no-header", "-p", "no:randomly"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _fallos(salida: str) -> list[str]:
    return sorted({
        linea.split("::")[-1].split(" ")[0]
        for linea in salida.splitlines()
        if linea.startswith("FAILED") or "FAILED " in linea
    })


# --- Las mutaciones: (nombre, fichero, texto_original, texto_mutado,
#                      pruebas_que_deben_enrojecer, fragmento_del_mensaje) ---
MUTACIONES = [
    (
        "M1 — `partida_exists` vuelve a la forma AGNÓSTICA de workspace "
        "(la mutación obligatoria: es literalmente el defecto medido)",
        "viewer/app/auth/db.py",
        '''        "SELECT 1 FROM partida_access WHERE workspace = ? AND partida_id = ? LIMIT 1",
        (workspace.strip(), partida_id.strip()),''',
        '''        "SELECT 1 FROM partida_access WHERE partida_id = ? LIMIT 1",
        (partida_id.strip(),),''',
        ["test_EL_CRUCE_workspace_B_partida_X_inexistente_NO_valida_en_B",
         "test_activar_X_en_workspace_incorrecto_es_RECHAZADO",
         "test_la_concesion_FANTASMA_no_altera_la_existencia_de_ninguna_canonica",
         "test_reverificar_una_concesion_CRUZADA_es_RECHAZADO",
         "test_un_workspace_inventado_no_contiene_partidas_ni_las_suyas"],
        "el cruce no está cerrado",
    ),
    (
        "M2 — el panel deja de validar el workspace al conceder "
        "(vuelve el texto libre por debajo de la pantalla)",
        "viewer/app/routers/admin.py",
        "    if not existencia.es_workspace_canonico(workspace):",
        "    if False and not existencia.es_workspace_canonico(workspace):",
        ["test_conceder_con_workspace_inventado_NO_crea_existencia"],
        "se guardó igual que antes",
    ),
    (
        "M3 — la re-verificación por petición vuelve a ignorar el workspace",
        "viewer/app/authz/dependencies.py",
        "                return existencia.partida_existe(conn, workspace, partida_id)",
        "                return auth_db.partida_exists(conn, partida_id, partida_id)",
        ["test_los_tres_consumidores_entran_por_app_authz_existencia",
         "test_reverificar_una_concesion_CRUZADA_es_RECHAZADO"],
        "sin pasar por app.authz.existencia",
    ),
    (
        "M4 — `workspace` vuelve a ser opcional en la firma "
        "(un llamante viejo colaría un fail-closed MUDO en vez de romper)",
        "viewer/app/auth/db.py",
        "def partida_exists(conn: sqlite3.Connection, workspace: str, partida_id: str) -> bool:",
        "def partida_exists(conn: sqlite3.Connection, workspace: str = \"\", partida_id: str = \"\") -> bool:",
        ["test_partida_exists_exige_el_workspace_y_no_lo_hace_opcional"],
        "tiene default",
    ),
    (
        "M5 — LA PANTALLA: se borra el campo de sólo lectura y la lista de "
        "partidas. Si la garantía es visible, el testigo tiene que PEDIRLA: "
        "borrarla entera no puede dejar la suite igual de verde",
        "viewer/app/templates/auth/admin/partidas.html",
        '''             value="{{ workspace_canonico | e }}" readonly aria-readonly="true">''',
        '''             placeholder="juego:leyenda" required>''',
        ["test_el_formulario_ya_no_pide_el_workspace_de_memoria"],
        "sigue siendo texto libre",
    ),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de "
              "calibrar — el checkout del arnés borra lo no commiteado.")
        return 2

    rc, salida = _correr_testigo()
    if rc != 0:
        print(f"ABORTA: el testigo no está verde en la base (PYTEST_RC={rc})")
        print(salida[-2000:])
        return 2
    print(f"BASE: testigo verde, PYTEST_RC={rc}\n")

    veredictos = []
    for nombre, rel, viejo, nuevo, esperadas, fragmento in MUTACIONES:
        f = RAIZ / rel
        original = f.read_text(encoding="utf-8")
        if viejo not in original:
            print(f"### {nombre}\n  DETECTOR ROTO: el texto a mutar no está en "
                  f"{rel}. La mutación no se aplicó: un verde aquí sería FALSO.\n")
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue

        f.write_text(original.replace(viejo, nuevo, 1), encoding="utf-8")
        rc_mut, salida_mut = _correr_testigo()
        fallos = _fallos(salida_mut)
        mensaje_ok = fragmento in salida_mut

        # Restaurar SIEMPRE, y verificar por efecto.
        f.write_text(original, encoding="utf-8")
        _purgar_pycache()
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigo()

        print(f"### {nombre}")
        print(f"  fichero            : {rel}")
        print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
        print(f"  pruebas en rojo    : {fallos}")
        print(f"  esperadas          : {sorted(esperadas)}")
        print(f"  MENSAJE contiene   : {fragmento!r} -> {mensaje_ok}")
        print(f"  restaurado (tracked limpio): {limpio}")
        print(f"  restaurado (PYTEST_RC post): {rc_post}  (esperado 0)")

        ok = (
            rc_mut != 0
            and set(esperadas).issubset(set(fallos))
            and mensaje_ok
            and limpio
            and rc_post == 0
        )
        print(f"  VEREDICTO          : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre.splitlines()[0]}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
