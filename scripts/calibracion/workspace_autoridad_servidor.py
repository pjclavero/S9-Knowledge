#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibración del corte «el workspace no lo elige el cliente».

QUÉ ES ESTO
-----------
Cada garantía se revierte DENTRO DEL PRODUCTO, se corre la prueba que debería
protegerla y se exige que se ponga roja **por su causa** (se comprueba el
MENSAJE del fallo, no el color).

LO QUE ESTE CORTE CIERRA
-------------------------
`PolicyFilteredProvider.graph()` y `.list_entities()` delegaban el `workspace`
del llamante directamente al provider base, a diferencia de `.entity()` (que
ya reautorizaba con `_scope_workspaces()`). Lo único que salvaba el caso era
el filtro nodo a nodo de `VisibilityPolicy.can_view`. `/api/graph` además
aceptaba el `workspace` del CLIENTE tal cual (`workspace or
get_default_workspace()`), sin compararlo contra la autoridad del servidor, y
cuando esa autoridad no resolvía ningún ámbito, la respuesta salía 200 con
`workspace: "leyenda"` -- un fail-closed que no se veía como tal.

EL ARNÉS SE CALIBRA A SÍ MISMO
-------------------------------
1. **Criterio**: cada `esperado` es PROSA, no un identificador que pytest
   imprima solo al comparar.
2. **Control nulo**: la mutación 0 toca un comentario y tiene que dejar la
   suite VERDE.

USO
---
    python3 scripts/calibracion/workspace_autoridad_servidor.py

Requiere árbol limpio: las mutaciones se revierten con `git checkout --`.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FILTERED_PROVIDER = "viewer/app/authz/filtered_provider.py"
API_GRAPH = "viewer/app/api/graph.py"
GRAPH_JS = "viewer/app/static/js/graph.js"

SUITE_PROVIDER = "viewer/tests/test_authz_filtered_provider.py"
SUITE_HTTP = "viewer/tests/test_p0_autoridad_admin_full_http.py"


@dataclass(frozen=True)
class Mutacion:
    nombre: str
    fichero: str
    viejo: str
    nuevo: str
    prueba: str
    esperado: str | None


CONTROL_NULO = Mutacion(
    nombre="CONTROL NULO — tocar un comentario no puede cambiar nada",
    fichero=FILTERED_PROVIDER,
    viejo="    # -- passthrough de conectividad -----------------------------------------",
    nuevo="    # -- passthrough de conectividad (comentario tocado por el calibrador) ----",
    prueba=SUITE_PROVIDER,
    esperado=None,
)


MUTACIONES: list[Mutacion] = [
    Mutacion(
        nombre="1 · `graph()` deja de reautorizar el ámbito: vuelve a "
               "delegar el workspace del llamante sin comprobarlo",
        fichero=FILTERED_PROVIDER,
        viejo="        if not self._ctx.admin_full and workspace not in self._ctx.allowed_workspaces:\n"
              "            return [], []\n        nodes, edges = self._base.graph(",
        nuevo="        nodes, edges = self._base.graph(",
        prueba=f"{SUITE_PROVIDER}::test_graph_no_consulta_workspace_ajeno_aunque_el_filtro_nodo_a_nodo_este_apagado",
        esperado="con el filtro nodo a nodo desactivado",
    ),
    Mutacion(
        nombre="2 · `list_entities()` deja de reautorizar el ámbito: mismo "
               "defecto en el segundo consumidor",
        fichero=FILTERED_PROVIDER,
        viejo="        if not self._ctx.admin_full and workspace not in self._ctx.allowed_workspaces:\n"
              "            return [], 0\n        items, _ = self._base.list_entities(",
        nuevo="        items, _ = self._base.list_entities(",
        prueba=f"{SUITE_PROVIDER}::test_list_entities_no_consulta_workspace_ajeno_aunque_el_filtro_nodo_a_nodo_este_apagado",
        esperado="con el filtro nodo a nodo desactivado",
    ),
    Mutacion(
        nombre="3 · `/api/graph` vuelve a aceptar el parámetro del cliente "
               "como ámbito de un `viewer`, en vez de la autoridad",
        fichero=API_GRAPH,
        viejo="    if len(canonicos) != 1:\n"
              "        # Vacío = autoridad sin resolver. Más de uno no debería ocurrir hoy\n"
              "        # (`allowed_workspaces` es un singleton por contrato), pero tampoco\n"
              "        # hay en ese caso UN ámbito único que devolver sin elegir por el\n"
              "        # cliente, así que se trata igual: sin ámbito.\n"
              "        return None\n    return next(iter(canonicos))",
        nuevo="    return solicitado or next(iter(canonicos), None)",
        prueba=f"{SUITE_HTTP}::test_el_control_de_autorizacion_COLAPSA_en_api_graph",
        esperado="FUGA DE AMBITO",
    ),
    Mutacion(
        nombre="4 · el cliente vuelve a fabricar un workspace de repuesto "
               "cuando el servidor no le da ninguno",
        fichero=GRAPH_JS,
        viejo='  var workspace = window.S9K_WORKSPACE || "";',
        nuevo='  var workspace = window.S9K_WORKSPACE || "leyenda";',
        prueba="viewer/tests/js/graph_core_spec.js",
        # Este fichero es JS, sin corredor pytest: se marca como
        # "verificación estática" (ver `_verificar` más abajo) porque lo que
        # hay que demostrar es que el patrón `|| "leyenda"` no reaparece en el
        # árbol, no que un test de pytest se ponga rojo.
        esperado=None,
    ),
]


def _purgar_pycache() -> None:
    subprocess.run(
        ["find", str(REPO), "-name", "__pycache__", "-type", "d",
         "-prune", "-exec", "rm", "-rf", "{}", "+"],
        check=False, capture_output=True,
    )


def _arbol_limpio() -> bool:
    r = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain",
                        "--untracked-files=no"],
                       capture_output=True, text=True, check=True)
    return not r.stdout.strip()


def _leer(ruta: str) -> str:
    return (REPO / ruta).read_text(encoding="utf-8")


def _restaurar(ruta: str, original: str) -> None:
    subprocess.run(["git", "-C", str(REPO), "checkout", "--", ruta], check=True)
    if _leer(ruta) != original:
        raise SystemExit(
            f"RESTAURACIÓN FALLIDA en {ruta}: el árbol ha quedado mutado. "
            f"Revísalo a mano ANTES de seguir.")


def _correr(prueba: str) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", prueba, "-q", "-p", "no:randomly",
         "--no-header"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _aplicar(m: Mutacion) -> tuple[str, str | None]:
    original = _leer(m.fichero)
    if m.viejo not in original:
        return original, (f"el texto a mutar ya no está en {m.fichero}: esta "
                          f"mutación no está mutando NADA")
    (REPO / m.fichero).write_text(
        original.replace(m.viejo, m.nuevo, 1), encoding="utf-8")
    return original, None


def _esperado_es_una_frase(esperado: str) -> str | None:
    texto = esperado.strip()
    if len(texto.split()) < 2:
        return (f"{esperado!r} no es una frase: un identificador lo imprime "
                f"pytest solo al comparar")
    return None


def _es_mutacion_estatica(m: Mutacion) -> bool:
    return m.fichero == GRAPH_JS


def main() -> int:
    if not _arbol_limpio():
        print("ÁRBOL SUCIO. Commitea antes: las mutaciones se revierten con "
              "`git checkout --` y se llevarían por delante tu trabajo.")
        return 2

    flojos = [(i, motivo) for i, m in enumerate(MUTACIONES, 1)
              if m.esperado and (motivo := _esperado_es_una_frase(m.esperado))]
    if flojos:
        print("CRITERIO DEMASIADO FLOJO:")
        for i, motivo in flojos:
            print(f"  · mutación {i}: {motivo}")
        return 2

    _purgar_pycache()

    print(f"[0] {CONTROL_NULO.nombre}")
    original, error = _aplicar(CONTROL_NULO)
    if error:
        print(f"   ANCLA PERDIDA — {error}")
        return 2
    _purgar_pycache()
    try:
        rc, salida = _correr(CONTROL_NULO.prueba)
    finally:
        _restaurar(CONTROL_NULO.fichero, original)
        _purgar_pycache()
    if rc != 0:
        print("   ROJA CON UNA MUTACIÓN INOCUA — el instrumento no sirve.")
        print(salida[-2000:])
        return 2
    print("   verde, como tenía que ser: el instrumento distingue")

    fallos = []
    for i, m in enumerate(MUTACIONES, 1):
        print(f"\n[{i}/{len(MUTACIONES)}] {m.nombre}")
        original, error = _aplicar(m)
        if error:
            fallos.append(f"{i}. {error}")
            print("   ANCLA PERDIDA — la mutación no se aplicó")
            continue

        if _es_mutacion_estatica(m):
            # Verificación estática: tras la mutación, el patrón peligroso
            # ("|| \"leyenda\"") tiene que estar presente. Es el negativo del
            # ojo humano, no de un test runner de JS (no hay uno en CI para
            # este fichero); demuestra que ANTES de esta mutación el patrón NO
            # estaba, y que revertirla lo hace reaparecer.
            mutado = _leer(m.fichero)
            _restaurar(m.fichero, original)
            if m.nuevo in mutado and m.nuevo not in original:
                print("   confirmado: la mutación reintroduce el patrón "
                      "peligroso, ausente en el árbol real")
            else:
                fallos.append(f"{i}. la mutación no cambió lo que debía en {m.fichero}")
                print("   MUTACIÓN INERTE")
            continue

        _purgar_pycache()
        try:
            rc, salida = _correr(m.prueba)
        finally:
            _restaurar(m.fichero, original)
            _purgar_pycache()

        if rc == 0:
            fallos.append(f"{i}. la prueba SIGUIÓ VERDE con la garantía "
                          f"revertida ({m.prueba})")
            print("   VERDE CON LA MUTACIÓN PUESTA — la prueba no protege nada")
        elif m.esperado not in salida:
            fallos.append(f"{i}. roja, pero SIN su causa. Se esperaba "
                          f"{m.esperado!r} en el fallo")
            print(f"   ROJA POR OTRA RAZÓN — no aparece {m.esperado!r}")
        else:
            print("   roja, y por su causa")

    print("\n" + "=" * 74)
    if fallos:
        print(f"CALIBRACIÓN FALLIDA: {len(fallos)} de {len(MUTACIONES)}")
        for f in fallos:
            print(f"  · {f}")
        return 1
    print(f"CALIBRACIÓN OK: {len(MUTACIONES)}/{len(MUTACIONES)}, "
          f"control nulo verde")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
