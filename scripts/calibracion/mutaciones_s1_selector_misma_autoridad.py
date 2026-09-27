#!/usr/bin/env python3
"""CORTE S1 — «el selector no ofrece lo que el producto rechaza».

Arnés de calibración: una garantía no cuenta hasta que hay una prueba capaz de
ponerse ROJA POR LA CAUSA CORRECTA. Aplica mutaciones de una en una sobre el
árbol COMMITEADO, corre los testigos y comprueba tres cosas por mutación:

  1. que la suite se pone roja (color),
  2. QUÉ pruebas fallan (no basta con que falle algo),
  3. que el MENSAJE del rojo dice la causa esperada.

Y después restaura, comprobando la restauración POR EFECTO: árbol limpio en lo
TRACKED *y* la suite verde otra vez.

Cubre cuatro formas de romper la propiedad:

  M1 — el defecto ORIGINAL medido en 9110b67: el middleware vuelve a pintar el
       selector con una lectura sin filtrar por workspace.
  M2 — la autoridad compartida (`existencia.partidas_seleccionables`) deja de
       filtrar por workspace para un usuario normal.
  M3 — esa misma autoridad deja de darle al admin las concesiones de OTROS
       usuarios en el workspace canónico (pierde algo que hoy tiene).
  M4 — la partida activa invalidada SOBREVIVE en `sessions.active_partida`
       (`authz.dependencies._clear_active_partida` se vuelve un no-op): el
       selector podría dejar de ofrecerla mientras el resto del producto
       sigue operando bajo un contexto que el usuario ya no puede elegir.
       Este testigo corre TAMBIÉN sobre `test_multipartida_m5a_adversarial.py`
       porque ese es el mecanismo YA EXISTENTE que cierra este caso -- no se
       duplica la lógica, se calibra la que hay.

Uso: python3 scripts/calibracion/mutaciones_s1_selector_misma_autoridad.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TESTIGOS = [
    "viewer/tests/test_s1_selector_misma_autoridad.py",
    "viewer/tests/test_multipartida_m5a_adversarial.py",
]


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                        cwd=RAIZ, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigos() -> tuple[int, str]:
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTIGOS, "-q", "--no-header",
         "--color=no", "-p", "no:randomly"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _fallos(salida: str) -> list[str]:
    return sorted({
        linea.split("::")[-1].split(" ")[0]
        for linea in salida.splitlines()
        if linea.startswith("FAILED") or "FAILED " in linea
    })


MUTACIONES = [
    (
        "M1 — el middleware vuelve a pintar el selector SIN filtrar por "
        "workspace (el defecto original de 9110b67, recreado literalmente)",
        "viewer/app/auth/middleware.py",
        """                            request.state.user_partidas = existencia.partidas_seleccionables(
                                conn, user, existencia.workspace_canonico(),
                            )""",
        """                            request.state.user_partidas = auth_db.list_partida_access(
                                conn, user_id=user.id,
                            )""",
        ["test_concesion_en_otro_workspace_no_aparece_en_el_selector",
         "test_sin_partidas_ofrecibles_la_pantalla_es_veraz",
         "test_partida_invalidada_no_aparece_en_el_selector_ni_sobrevive_en_la_sesion"],
        "el selector ofrece una partida concedida en un workspace",
    ),
    (
        "M2 — `partidas_seleccionables` deja de filtrar por workspace para un "
        "usuario normal (segunda autoridad, no la de /partida/select)",
        "viewer/app/authz/existencia.py",
        "        filas = auth_db.list_partida_access(conn, user_id=user.id, workspace=ws)",
        "        filas = auth_db.list_partida_access(conn, user_id=user.id)",
        ["test_concesion_en_otro_workspace_no_aparece_en_el_selector",
         "test_sin_partidas_ofrecibles_la_pantalla_es_veraz"],
        "el selector ofrece una partida concedida en un workspace",
    ),
    (
        "M3 — el admin deja de ver las concesiones de OTROS usuarios en el "
        "workspace canónico (pierde algo que hoy podía elegir)",
        "viewer/app/authz/existencia.py",
        "        filas = auth_db.list_partida_access(conn, workspace=ws)",
        "        filas = auth_db.list_partida_access(conn, user_id=user.id, workspace=ws)",
        ["test_admin_ve_las_partidas_del_workspace_canonico_aunque_no_sean_suyas"],
        "el admin pierde una partida que hoy podía elegir",
    ),
    (
        "M4 — la partida activa invalidada SOBREVIVE en `sessions.active_partida` "
        "(`_clear_active_partida` se vuelve un no-op): el mecanismo ya "
        "existente que cierra este caso, calibrado aquí",
        "viewer/app/authz/dependencies.py",
        """    try:
        with auth_db.get_conn(db_path) as conn:
            auth_db.set_session_active_partida(conn, session.id, None)
    except Exception:
        pass  # el contexto ya degradó a capa juego; la limpieza es best-effort""",
        """    try:
        pass  # M4: ya no se limpia sessions.active_partida
    except Exception:
        pass  # el contexto ya degradó a capa juego; la limpieza es best-effort""",
        ["test_partida_invalidada_no_aparece_en_el_selector_ni_sobrevive_en_la_sesion",
         "test_revocar_partida_tambien_limpia_la_sesion",
         "test_reverificacion_no_cruza_desde_otro_workspace"],
        "sobrevivió a su invalidación",
    ),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de "
              "calibrar — el checkout del arnés borra lo no commiteado.")
        return 2

    rc, salida = _correr_testigos()
    if rc != 0:
        print(f"ABORTA: los testigos no están verdes en la base (PYTEST_RC={rc})")
        print(salida[-3000:])
        return 2
    print(f"BASE: testigos verdes, PYTEST_RC={rc}\n")

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
        rc_mut, salida_mut = _correr_testigos()
        fallos = _fallos(salida_mut)
        mensaje_ok = fragmento in salida_mut

        f.write_text(original, encoding="utf-8")
        _purgar_pycache()
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigos()

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
