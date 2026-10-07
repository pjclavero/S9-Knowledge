#!/usr/bin/env python3
"""PR-1 (USABLE-V1) — arnés de calibración de "`/review-console` apagada por
defecto".

Mismo principio que `corte1_existencia_partida.py`: una garantía no cuenta
hasta que hay una prueba capaz de ponerse ROJA POR LA CAUSA CORRECTA. Aplica
mutaciones de una en una sobre el árbol COMMITEADO, corre el testigo
(`viewer/tests/test_review_console_apagada_por_defecto.py`) y comprueba que
se pone rojo, QUÉ pruebas fallan y que el mensaje de la causa es el esperado.
Restaura siempre, comprobando por EFECTO (árbol tracked limpio + suite verde).

Localizador ESTRUCTURAL (no texto anclado a posición ni a indentación): las
mutaciones usan `localizadores.mutar_en_funcion`/`mutar_unico`, que devuelven
``None`` --DETECTOR ROTO-- en vez de elegir una ocurrencia ambigua.

Uso: python3 scripts/calibracion/mutaciones_pr1_review_console_apagada.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, mutar_unico, python_sigue_siendo_valido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "viewer/tests/test_review_console_apagada_por_defecto.py"
FICHERO = "viewer/app/routers/reviews_console.py"


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


# ---------------------------------------------------------------------------
# Las mutaciones
# ---------------------------------------------------------------------------
# M1 es LA MUTACIÓN OBLIGATORIA del encargo: "como mínimo una mutación que
# reactive el montaje y ponga rojo el testigo". `_exigir_encendido` deja de
# comprobar nada -> la consola vuelve a servirse siempre, exactamente el
# defecto que este PR cierra.
def _mutar_exigir_encendido_noop(texto: str) -> str | None:
    return mutar_en_funcion(
        texto,
        "_exigir_encendido",
        "    if not _encendido():\n        raise HTTPException(status_code=404, detail=APAGADA)",
        "    if False:\n        raise HTTPException(status_code=404, detail=APAGADA)",
    )


# M2: `_encendido` deja de mirar `chassis.FLAG_ON_VALUES` y usa un criterio
# propio (vuelve la segunda autoridad que S-3 ya eliminó para los otros
# interruptores del chasis). Cualquier valor no vacío enciende.
def _mutar_encendido_segunda_autoridad(texto: str) -> str | None:
    return mutar_en_funcion(
        texto,
        "_encendido",
        "    valores = getattr(chassis, \"FLAG_ON_VALUES\", frozenset())\n    return raw.strip().lower() in valores",
        "    return bool(raw)",
    )


# M3: el `POST .../decide` deja de exigir el interruptor (se borra SÓLO esa
# llamada, dejando las otras dos rutas intactas). Es el caso que de verdad
# importa -- el que escribe --, aislado del resto del espacio de URL.
def _mutar_solo_el_post_decide(texto: str) -> str | None:
    return mutar_en_funcion(
        texto,
        "decide",
        "    guard = _guard(request)\n    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):\n        return guard\n    _exigir_encendido()\n    if not _check_csrf(request, csrf_token):",
        "    guard = _guard(request)\n    if guard is not None and isinstance(guard, (RedirectResponse, HTMLResponse)):\n        return guard\n    if not _check_csrf(request, csrf_token):",
    )


MUTACIONES = [
    (
        "M1 — `_exigir_encendido` deja de exigir nada (LA MUTACIÓN "
        "OBLIGATORIA: reactiva el montaje de las tres rutas, incluido el "
        "`POST` que escribe)",
        _mutar_exigir_encendido_noop,
        ["test_sin_la_clave_en_el_entorno_get_inbox_da_404",
         "test_sin_la_clave_en_el_entorno_get_detalle_da_404",
         "test_sin_la_clave_en_el_entorno_post_decide_da_404",
         "test_valores_que_no_encienden_siguen_dando_404"],
        "404",
    ),
    (
        "M2 — `_encendido` abandona `chassis.FLAG_ON_VALUES` (segunda "
        "autoridad: cualquier valor no vacío enciende, no sólo "
        "'true'/'1')",
        _mutar_encendido_segunda_autoridad,
        ["test_valores_que_no_encienden_siguen_dando_404"],
        "404",
    ),
    (
        "M3 — sólo el `POST …/decide` deja de exigir el interruptor "
        "(las otras dos rutas siguen apagadas; la que escribe no)",
        _mutar_solo_el_post_decide,
        ["test_sin_la_clave_en_el_entorno_post_decide_da_404"],
        "404",
    ),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de "
              "calibrar.")
        return 2

    rc, salida = _correr_testigo()
    if rc != 0:
        print(f"ABORTA: el testigo no está verde en la base (PYTEST_RC={rc})")
        print(salida[-2000:])
        return 2
    print(f"BASE: testigo verde, PYTEST_RC={rc}\n")

    f = RAIZ / FICHERO
    original = f.read_text(encoding="utf-8")

    veredictos = []
    for nombre, mutador, esperadas, fragmento in MUTACIONES:
        mutado = mutador(original)
        if mutado is None or mutado == original or not python_sigue_siendo_valido(mutado):
            print(f"### {nombre}\n  DETECTOR ROTO: la mutación no se pudo "
                  f"aplicar sobre {FICHERO} (ancla ausente/ambigua, o el "
                  f"resultado no es Python válido). Un verde aquí sería "
                  f"FALSO.\n")
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue

        f.write_text(mutado, encoding="utf-8")
        rc_mut, salida_mut = _correr_testigo()
        fallos = _fallos(salida_mut)
        mensaje_ok = fragmento in salida_mut

        f.write_text(original, encoding="utf-8")
        _purgar_pycache()
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigo()

        print(f"### {nombre}")
        print(f"  fichero            : {FICHERO}")
        print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
        print(f"  pruebas en rojo    : {fallos}")
        print(f"  esperadas (subset) : {sorted(esperadas)}")
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
