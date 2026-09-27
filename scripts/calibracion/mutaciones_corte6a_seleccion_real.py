#!/usr/bin/env python3
"""CORTE 6A — «seleccion real de contexto» (partidas descubiertas por la boveda).

Arnes de calibracion: una garantia no cuenta hasta que hay una prueba capaz de
ponerse ROJA POR LA CAUSA CORRECTA. Aplica mutaciones de una en una sobre el
arbol COMMITEADO, corre los testigos y comprueba tres cosas por mutacion:

  1. que la suite se pone roja (color),
  2. QUE pruebas fallan (no basta con que falle algo),
  3. que el MENSAJE del rojo dice la causa esperada.

Y despues restaura, comprobando la restauracion POR EFECTO: arbol limpio en lo
TRACKED *y* la suite verde otra vez.

Cubre tres formas de romper la propiedad:

  M1 — `partidas_descubiertas_en_boveda` deja de filtrar por `workspace`: una
       partida de OTRO workspace se ofrece/acepta como si fuera del canonico.
  M2 — `/admin/partidas/grant` deja de re-validar `partida_id` contra la
       enumeracion en el servidor (la pantalla sigue pintando un `<select>`
       correcto, pero un POST manipulado ya no se rechaza): la guarda vive
       SOLO en el cliente, que es exactamente lo que el corte cierra.
  3 — M3: el estado cero (ninguna partida descubrible) deja de excluir el
       `<select>`/input de la pantalla: volveria a pedir un identificador
       inventado en vez de ofrecer el camino web.

Uso: python3 scripts/calibracion/mutaciones_corte6a_seleccion_real.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TESTIGOS = [
    "viewer/tests/test_corte6a_seleccion_real_contexto.py",
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
        "M1 — `partidas_descubiertas_en_boveda` deja de filtrar por workspace: "
        "ofrece/acepta partidas de OTRO workspace",
        "viewer/app/sources_catalog.py",
        "        if pid and ws_fuente == ws:",
        "        if pid:",
        ["test_partidas_descubiertas_no_cruza_workspaces"],
        "cruzó una partida de otro workspace",
    ),
    (
        "M2 — `/admin/partidas/grant` deja de re-validar `partida_id` en el "
        "SERVIDOR (la guarda queda solo en el cliente)",
        "viewer/app/routers/admin.py",
        # OBJETIVO ESTABLE, NO EL MENSAJE. Antes esta mutacion copiaba el
        # bloque ENTERO, mensaje de error incluido, y el corte 6B-1 —que hizo
        # pasar ese mensaje por el resolvedor de etiquetas— lo movio: la
        # mutacion dejo de aplicarse y el calibrador dijo DETECTOR ROTO (bien
        # dicho: un verde ahi seria falso). La PROPIEDAD atacada no cambia
        # —que el POST deje de revalidar `partida_id` contra la enumeracion—,
        # pero ahora se ataca la GUARDA, que es la linea estable, y no su
        # redaccion. El bloque del `raise` sigue ahi, inalcanzable.
        "    if partida_id not in descubribles:",
        "    if False:  # M2: ya no se revalida partida_id contra la enumeracion",
        ["test_post_con_partida_id_fuera_de_la_enumeracion_se_rechaza"],
        "un partida_id que la bóveda no declara se aceptó",
    ),
    (
        "M3 — el estado cero deja de ocultar el campo `partida_id`: vuelve a "
        "pedir un identificador tecleado a mano",
        "viewer/app/templates/auth/admin/partidas.html",
        '    {% elif not partidas_descubribles %}',
        '    {% elif False %}',
        ["test_boveda_real_vacia_de_partidas_se_distingue_de_sin_boveda"],
        "con cero partidas descubribles se sigue pintando",
    ),
    (
        # RONDA 2 DE REVISION sobre PR #253: M1 muta la funcion COMPARTIDA por
        # pantalla y servidor, asi que las dos puntas se mueven a la vez y esa
        # mutacion NO PUEDE demostrar una divergencia entre "lo ofrecido" y "lo
        # aceptado" -- por construccion. Esta mutacion toca SOLO la pantalla
        # (el GET), alimentandola otra vez del eco viejo (`partida_access`) en
        # UNION con la enumeracion real, mientras el POST sigue validando
        # SOLO contra la boveda real, sin tocar. Si esto ocurriera de verdad
        # en produccion, la pantalla ofreceria una opcion que el servidor
        # rechazaria -- exactamente la falsa confirmacion que el corte cierra.
        "M4 — LA PANTALLA (y sólo la pantalla) vuelve a alimentarse del eco "
        "de `partida_access`, divergiendo de lo que el servidor acepta",
        "viewer/app/routers/admin.py",
        "        partidas_descubribles = sources_catalog.partidas_descubiertas_en_boveda(ws)",
        (
            "        partidas_descubribles = sorted(set(\n"
            "            sources_catalog.partidas_descubiertas_en_boveda(ws)\n"
            "        ) | {\n"
            "            a.partida_id for a in access\n"
            "            if a.partida_id and a.workspace == ws\n"
            "        })"
        ),
        ["test_lo_ofrecido_es_exactamente_la_enumeracion_compartida_no_access"],
        "divergieron",
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
