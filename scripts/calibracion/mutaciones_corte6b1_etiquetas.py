#!/usr/bin/env python3
"""CORTE 6B-1 — resolver y mostrar nombres humanos, con ámbito de servidor.

Arnes de calibracion: aplica mutaciones de una en una sobre el arbol
COMMITEADO, corre los testigos, y comprueba (1) que se ponen ROJOS, (2) QUE
pruebas fallan, (3) que el mensaje del rojo dice la causa esperada. Despues
restaura y comprueba la restauracion POR EFECTO (arbol tracked limpio y suite
verde otra vez).

Cubre las dos formas de romper la propiedad de este corte:

  M1 — el resolvedor deja de comprobar el ambito autorizado antes de leer el
       perfil: un workspace fuera de ambito revela su label. Es la fuga con
       otra cara del corte #254.
  M2 — el fallback deja de usar el identificador y empieza a INVENTAR un
       nombre a partir de el (la falsa confirmacion que el programa lleva un
       mes eliminando).
  M3 — UNA PLANTILLA SE SALTA EL RESOLVEDOR y pinta el identificador crudo.
       En la ronda 1 esto dejaba la suite VERDE: cualquiera podia revertir una
       pantalla y nadie se enteraba.
  M4 — EL AMBITO VUELVE A SER TAUTOLOGICO: el global de Jinja pasa como
       ambito el propio workspace que va a pintar (`[workspace]`), que era
       exactamente el defecto de la ronda 1 — una guarda que nunca se ejecuta
       y por eso parece proteccion sin serlo.

Uso: python3 scripts/calibracion/mutaciones_corte6b1_etiquetas.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TESTIGOS = [
    "viewer/tests/test_corte6b1_etiquetas_presentacion.py",
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
        "M1 — el resolvedor deja de comprobar el ámbito autorizado: un "
        "workspace FUERA de ámbito revela su label (la fuga de #254 con "
        "otra cara)",
        "viewer/app/presentacion_etiquetas.py",
        "    if workspace not in _normaliza_ambito(ambito_permitido):\n"
        "        return workspace\n\n"
        "    carpeta = _carpeta_de_juego(workspace, env, lector)\n"
        "    if carpeta is None:\n"
        "        return workspace\n\n"
        "    datos = _leer_json_objeto(carpeta / sources_catalog.NOMBRE_PERFIL, lector)",
        "    carpeta = _carpeta_de_juego(workspace, env, lector)\n"
        "    if carpeta is None:\n"
        "        return workspace\n\n"
        "    datos = _leer_json_objeto(carpeta / sources_catalog.NOMBRE_PERFIL, lector)",
        ["test_fuera_de_ambito_no_confirma_ni_niega_existencia"],
        "assert",
    ),
    (
        "M2 — el fallback deja de usar el identificador y lo CAPITALIZA como "
        "si fuera un nombre inventado a partir de él",
        "viewer/app/presentacion_etiquetas.py",
        "    return _label_declarado(datos) or partida_id",
        "    return _label_declarado(datos) or partida_id.replace(':', ' ').title()",
        ["test_nunca_deriva_un_nombre_del_identificador_con_manifiesto_sin_label"],
        "assert",
    ),
    (
        "M3 — una plantilla SE SALTA el resolvedor unico y pinta el "
        "identificador crudo en una superficie de operador",
        "viewer/app/templates/entities.html",
        "{{ etiqueta_workspace(workspace) }}",
        "{{ workspace }}",
        ["test_ninguna_plantilla_se_salta_el_resolvedor"],
        "no estan declaradas como protocolo",
    ),
    (
        "M4 — el ambito vuelve a ser TAUTOLOGICO: el global pasa como ambito "
        "el propio workspace que va a pintar",
        "viewer/app/presentacion_etiquetas.py",
        "    return resolvedor_de_peticion(ctx.get(\"request\")).workspace(workspace)",
        "    return etiqueta_workspace(workspace, [workspace])",
        ["test_la_plantilla_no_puede_elegir_su_propio_ambito"],
        "FUGA DE AMBITO",
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
