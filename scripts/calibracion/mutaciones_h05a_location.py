#!/usr/bin/env python3
"""H-05 corte A — calibración de "las redirecciones de /panel/operations llevan
Location RELATIVO".

Una garantía no cuenta hasta que hay una prueba capaz de ponerse ROJA POR SU
CAUSA. Cada mutación reintroduce UN defecto sobre el código real, una cada vez
(localizador estructural por AST: `localizadores.mutar_en_funcion`; ancla
ausente o ambigua = DETECTOR ROTO, nunca un verde), corre el testigo
`viewer/tests/test_h05a_location_relativo.py` y comprueba (1) que cayeron los
casos esperados, (2) que el mensaje del rojo dice la causa, y (3) que la
restauración es real (árbol tracked limpio + testigo verde).

  M1  `request.url_for` vuelve en el FALLO de la ingesta.
  M2  `request.url_for` vuelve en el ÉXITO de la ingesta.
  M3  `request.url_for` vuelve en `_vuelta` (planes/aplicaciones/altas).
  M4  `_vuelta` devuelve el origen del cliente (`request.base_url` + path), sin
      pasar por `url_for`: el censo AST no lo ve, el test de comportamiento sí.
  M5  el censo AST deja de mirar `url_for` (helper ciego) -> el control de
      «censo no ciego» del propio test lo delata.

TECHO DECLARADO: calibra sólo `chassis_operations.py`. Las 35 `url_for` de las
plantillas y la ausencia de TrustedHost (corte B) no están medidas aquí.

Uso: python3 scripts/calibracion/mutaciones_h05a_location.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, python_sigue_siendo_valido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "viewer/tests/test_h05a_location_relativo.py"
OPERACIONES = "viewer/app/routers/chassis_operations.py"
CENSO = TESTIGO

CENSO_AST = "test_el_censo_ast_no_encuentra_request_url_for_en_chassis_operations"
HOSTILES = ("evil.example", "evil.example:8443")


def _sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = _sh(["git", "status", "--porcelain", "--untracked-files=no"])
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigo() -> tuple[int, str]:
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TESTIGO, "-q", "--no-header",
         "--color=no", "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _fallos(salida: str) -> list[str]:
    return sorted({
        linea.split("::", 1)[-1].split(" ")[0]
        for linea in salida.splitlines() if linea.startswith("FAILED")
    })


def _casos(prueba: str, rutas: tuple[str, ...], tramos: tuple[str, ...]) -> list[str]:
    return [f"{prueba}[{h}-{r}-{t}]" for h in HOSTILES for r in rutas for t in tramos]


def _m1(t: str) -> str | None:
    return mutar_en_funcion(
        t, "solicitar_ingesta",
        "{request.app.url_path_for('chassis_operations')}?aviso=",
        "{request.url_for('chassis_operations')}?aviso=")


def _m2(t: str) -> str | None:
    return mutar_en_funcion(
        t, "solicitar_ingesta",
        "{request.app.url_path_for('chassis_operations')}?solicitado=",
        "{request.url_for('chassis_operations')}?solicitado=")


def _m3(t: str) -> str | None:
    return mutar_en_funcion(
        t, "_vuelta",
        "base = request.app.url_path_for(destino)",
        "base = request.url_for(destino)")


def _m4(t: str) -> str | None:
    return mutar_en_funcion(
        t, "_vuelta",
        "base = request.app.url_path_for(destino)",
        'base = str(request.base_url).rstrip("/") + request.app.url_path_for(destino)')


def _m5(t: str) -> str | None:
    return mutar_en_funcion(
        t, "_llamadas_url_for",
        'and n.func.attr == "url_for"',
        'and n.func.attr == "url_for_ciego"')


ACCIONES = ("planes", "aplicaciones", "altas")
LOC = "test_location_relativo_con_host_hostil"
SEG = "test_seguir_la_redireccion_acaba_en_el_mismo_origen"

MUTACIONES = [
    ("M1 — `request.url_for` vuelve en el FALLO de la ingesta", OPERACIONES, _m1,
     _casos(LOC, ("ingestas",), ("fallo",)) + _casos(SEG, ("ingestas",), ("fallo",))
     + [CENSO_AST],
     "evil.example"),
    ("M2 — `request.url_for` vuelve en el ÉXITO de la ingesta", OPERACIONES, _m2,
     _casos(LOC, ("ingestas",), ("exito",)) + _casos(SEG, ("ingestas",), ("exito",))
     + [CENSO_AST],
     "evil.example"),
    ("M3 — `request.url_for` vuelve en `_vuelta` (planes/aplicaciones/altas)",
     OPERACIONES, _m3,
     _casos(LOC, ACCIONES, ("fallo", "exito")) + _casos(SEG, ACCIONES, ("fallo", "exito"))
     + [CENSO_AST],
     "evil.example"),
    ("M4 — `_vuelta` devuelve el origen del cliente (base_url + path)",
     OPERACIONES, _m4,
     _casos(LOC, ACCIONES, ("fallo", "exito")) + _casos(SEG, ACCIONES, ("fallo", "exito")),
     "evil.example"),
    ("M5 — el censo AST deja de mirar `url_for` (instrumento ciego)", CENSO, _m5,
     [CENSO_AST], "el censo no detecta ni una llamada plantada"),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de calibrar.")
        return 2
    rc, salida = _correr_testigo()
    if rc != 0:
        print(f"ABORTA: el testigo no está verde en la base (PYTEST_RC={rc})")
        print(salida[-2000:])
        return 2
    print(f"BASE: testigo verde, PYTEST_RC={rc}\n")

    veredictos = []
    for nombre, fichero, mutador, esperadas, fragmento in MUTACIONES:
        f = RAIZ / fichero
        original = f.read_text(encoding="utf-8")
        mutado = mutador(original)
        if mutado is None or mutado == original or not python_sigue_siendo_valido(mutado):
            print(f"### {nombre}\n  DETECTOR ROTO: la mutación no se pudo aplicar sobre "
                  f"{fichero} (ancla ausente/ambigua o Python inválido).\n")
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue
        f.write_text(mutado, encoding="utf-8")
        try:
            rc_mut, salida_mut = _correr_testigo()
        finally:
            f.write_text(original, encoding="utf-8")
        fallos = _fallos(salida_mut)
        mensaje_ok = fragmento in salida_mut
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigo()
        faltan = sorted(set(esperadas) - set(fallos))
        print(f"### {nombre}")
        print(f"  fichero            : {fichero}")
        print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
        print(f"  rojos              : {len(fallos)}")
        print(f"  esperados ausentes : {faltan}")
        print(f"  MENSAJE contiene   : {fragmento!r} -> {mensaje_ok}")
        print(f"  restaurado (tracked limpio): {limpio}")
        print(f"  restaurado (PYTEST_RC post): {rc_post}  (esperado 0)")
        ok = rc_mut != 0 and not faltan and mensaje_ok and limpio and rc_post == 0
        print(f"  VEREDICTO          : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
