#!/usr/bin/env python3
"""B1 (USABLE-V1) · H-03 — arnés de calibración del aislamiento por workspace
en la revisión V3.

Una garantía no cuenta hasta que hay una prueba capaz de ponerse ROJA POR LA
CAUSA CORRECTA. Este arnés aplica mutaciones de una en una sobre el árbol
COMMITEADO, corre el testigo
(`viewer/tests/test_b1_h03_aislamiento_workspace_review.py`) y exige, para
cada mutación:

  - PYTEST_RC != 0;
  - que fallen AL MENOS las pruebas declaradas, y que cada una falle con el
    fragmento de causa declarado (el 303 / la fila nueva / el 200, no un
    import ni un fixture): se lee la línea `FAILED <prueba> - <mensaje>`;
  - que el testigo se haya ejecutado de verdad: `collected > 0` y
    `skipped == 0`, en la base y en cada mutación;
  - restauración por EFECTO: árbol tracked limpio y testigo verde otra vez.

Localizador ESTRUCTURAL (`localizadores.mutar_en_funcion`, por AST): devuelve
``None`` —DETECTOR ROTO— si el ancla no está, o está más de una vez, dentro de
la función nombrada. Nunca `.replace(..., 1)` ni anclas posicionales.

TECHO DECLARADO: el caso «registro de revisión sin workspace» (M3) sólo es
alcanzable en unidad: `load_proposals` rechaza propuestas sin workspace y los
candidatos de glosario se consultan por workspace. Su testigo es la prueba de
unidad de la función única de ámbito, no una ruta HTTP.

Uso: python3 scripts/calibracion/mutaciones_b1_h03_aislamiento_workspace.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, python_sigue_siendo_valido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "viewer/tests/test_b1_h03_aislamiento_workspace_review.py"
SERVICIO = "viewer/app/services/v3_review.py"
SCOPE = "viewer/app/authz/scope.py"
ROUTER = "viewer/app/routers/v3_review.py"


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
         "--color=no", "-p", "no:randomly", "-p", "no:cacheprovider", "-rfs"],
        cwd=RAIZ, capture_output=True, text=True,
        # Sin terminal, pytest recorta el mensaje de `FAILED ... - <msg>` a 80
        # columnas y la causa podría quedar fuera de la línea que se lee.
        env={**os.environ, "COLUMNS": "4000"},
    )
    return r.returncode, r.stdout + r.stderr


def _recuento(salida: str) -> dict[str, int]:
    """Cifras de la línea final de pytest (`3 failed, 15 passed in ...`)."""
    cifras: dict[str, int] = {}
    for linea in salida.splitlines()[::-1]:
        if " in " in linea and ("passed" in linea or "failed" in linea or "error" in linea):
            for n, clave in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)", linea):
                cifras[clave.rstrip("s") if clave.startswith("error") else clave] = int(n)
            break
    return cifras


def _ejecutado_de_verdad(cifras: dict[str, int]) -> bool:
    recogidas = sum(cifras.get(k, 0) for k in ("passed", "failed", "skipped", "error"))
    return recogidas > 0 and cifras.get("skipped", 0) == 0 and cifras.get("error", 0) == 0


def _fallos(salida: str) -> dict[str, str]:
    """{nombre_de_prueba: mensaje} de las líneas `FAILED ... - mensaje`."""
    fallos: dict[str, str] = {}
    for linea in salida.splitlines():
        if not linea.startswith("FAILED "):
            continue
        cuerpo = linea[len("FAILED "):]
        ident, _, mensaje = cuerpo.partition(" - ")
        fallos[ident.split("::")[-1].strip()] = mensaje
    return fallos


# ---------------------------------------------------------------------------
# Las mutaciones
# ---------------------------------------------------------------------------
# M1 — LA MUTACIÓN OBLIGATORIA: el defecto de origen tal cual (`f6a4f18`).
# La función única de ámbito vuelve a devolver `partida_only()`.
def _m1_scoped_vuelve_a_partida_only(fichero: str, texto: str) -> str | None:
    return mutar_en_funcion(
        texto, "_scoped",
        "return (scope or UNRESTRICTED).para_corpus_de_revision()",
        "return (scope or UNRESTRICTED).partida_only()",
    )


# M2 — la ablación DENTRO de la función de scope: el ámbito de revisión se
# construye con `enforce_workspace=False` (lo que pide el encargo).
def _m2_enforce_workspace_false(fichero: str, texto: str) -> str | None:
    return mutar_en_funcion(
        texto, "para_corpus_de_revision",
        "enforce_workspace=True, workspace_obligatorio=True",
        "enforce_workspace=False, workspace_obligatorio=True",
    )


# M3 — fail-open ante un registro de revisión sin workspace.
def _m3_sin_workspace_vuelve_a_ser_capa_juego(fichero: str, texto: str) -> str | None:
    return mutar_en_funcion(
        texto, "allows_workspace",
        "return not self.workspace_obligatorio",
        "return True",
    )


# M4 — `decide` deja de exigir el workspace visible: el servicio sigue sin
# registrar (cero filas), pero el desenlace vuelve a ser un 400 que no
# distingue «no es tuyo» de «formulario mal». Calibra el contrato 404.
def _m4_decide_sin_exigir_workspace(fichero: str, texto: str) -> str | None:
    return mutar_en_funcion(
        texto, "decide",
        "        _exigir_workspace_visible(service, workspace, visibility_scope)\n",
        "",
    )


# M5 — ídem en `undo`.
def _m5_undo_sin_exigir_workspace(fichero: str, texto: str) -> str | None:
    return mutar_en_funcion(
        texto, "undo",
        "        _exigir_workspace_visible(service, workspace, scope)\n",
        "",
    )


NEGATIVOS_HTTP = {
    # prueba: fragmento de causa que TIENE que aparecer en su línea FAILED
    "test_negativo_rev_a_decide_sobre_b_no_registra_nada": "HTTP 303",
    "test_negativo_rev_a_deshace_en_b_no_registra_nada": "HTTP 303",
    "test_negativo_get_cola_de_b_no_muestra_b": "200",
    "test_negativo_panel_item_de_b_da_404": "200",
    "test_negativo_panel_lista_de_b": "200",
    "test_negativo_glossary_candidates_de_b_no_visibles": "200",
    "test_negativo_revisor_no_decide_ni_deshace_en_otro_corpus": "HTTP 303",
    "test_ambito_de_revision_exige_workspace_y_lo_compara": "assert True is False",
}

MUTACIONES = [
    ("M1 — `_scoped()` vuelve a devolver `partida_only()` (el defecto H-03 de origen)",
     SERVICIO, _m1_scoped_vuelve_a_partida_only, NEGATIVOS_HTTP),
    ("M2 — `para_corpus_de_revision` con `enforce_workspace=False` (ablación en la función única)",
     SCOPE, _m2_enforce_workspace_false, NEGATIVOS_HTTP),
    ("M3 — un registro de revisión SIN workspace vuelve a leerse como capa juego",
     SCOPE, _m3_sin_workspace_vuelve_a_ser_capa_juego,
     {"test_ambito_de_revision_exige_workspace_y_lo_compara": "assert True is False"}),
    ("M4 — `decide` deja de exigir workspace visible (vuelve el 400 indistinto)",
     ROUTER, _m4_decide_sin_exigir_workspace,
     {"test_negativo_rev_a_decide_sobre_b_no_registra_nada": "HTTP 400",
      "test_negativo_revisor_no_decide_ni_deshace_en_otro_corpus": "HTTP 400"}),
    ("M5 — `undo` deja de exigir workspace visible (vuelve el 400 indistinto)",
     ROUTER, _m5_undo_sin_exigir_workspace,
     {"test_negativo_rev_a_deshace_en_b_no_registra_nada": "HTTP 400",
      "test_negativo_revisor_no_decide_ni_deshace_en_otro_corpus": "HTTP 400"}),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de calibrar.")
        return 2

    rc, salida = _correr_testigo()
    cifras = _recuento(salida)
    if rc != 0 or not _ejecutado_de_verdad(cifras):
        print(f"ABORTA: el testigo no está verde y ejecutado en la base "
              f"(PYTEST_RC={rc}, cifras={cifras})")
        print(salida[-2000:])
        return 2
    print(f"BASE: testigo verde, PYTEST_RC={rc}, cifras={cifras}\n")

    veredictos = []
    for nombre, fichero, mutador, esperadas in MUTACIONES:
        f = RAIZ / fichero
        original = f.read_text(encoding="utf-8")
        mutado = mutador(fichero, original)
        if mutado is None or mutado == original or not python_sigue_siendo_valido(mutado):
            print(f"### {nombre}\n  DETECTOR ROTO: la mutación no se pudo aplicar "
                  f"sobre {fichero} (ancla ausente/ambigua o Python inválido). "
                  f"Un verde aquí sería FALSO.\n")
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
        causas = {
            prueba: (prueba in fallos and fragmento in fallos[prueba])
            for prueba, fragmento in esperadas.items()
        }
        limpio = _arbol_limpio_tracked()
        rc_post, salida_post = _correr_testigo()
        cifras_post = _recuento(salida_post)

        print(f"### {nombre}")
        print(f"  fichero              : {fichero}")
        print(f"  PYTEST_RC mutado     : {rc_mut}  (esperado != 0)")
        print(f"  cifras mutado        : {cifras_mut}  (skipped/errores esperados 0)")
        print(f"  pruebas en rojo      : {sorted(fallos)}")
        for prueba, ok in causas.items():
            print(f"  causa {'OK ' if ok else 'MAL'} {prueba}: "
                  f"esperado {esperadas[prueba]!r} -> {fallos.get(prueba, '(no falló)')!r}")
        print(f"  restaurado (tracked limpio): {limpio}")
        print(f"  restaurado (PYTEST_RC post): {rc_post}, cifras {cifras_post}")

        ok = (
            rc_mut != 0
            and _ejecutado_de_verdad(cifras_mut)
            and all(causas.values())
            and limpio
            and rc_post == 0
            and _ejecutado_de_verdad(cifras_post)
        )
        print(f"  VEREDICTO            : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
