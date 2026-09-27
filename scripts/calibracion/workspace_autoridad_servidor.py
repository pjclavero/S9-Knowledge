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
La propiedad tiene dos mitades y las dos son del PRODUCTO, no de un endpoint:

  1. el ámbito de una consulta lo decide la autoridad del servidor, nunca un
     valor que fabrique el cliente ni el entorno;
  2. cuando la autoridad no resuelve, la respuesta no puede presentarse como
     un workspace normal y vacío.

En el proveedor filtrado, la reautorización del ámbito vivía sólo en `graph()`
y `list_entities()`: los helpers `_visible_nodes` / `_visible_graph` llamaban
al provider base directamente, así que `search`, `entity_types`,
`list_sources`, `source_detail`, `counts` y `quality_metrics` seguían
entregando el workspace ajeno con el filtro nodo a nodo apagado. En la capa
HTTP, trece sitios repetían `workspace or S9K_DEFAULT_WORKSPACE`.

EL ARNÉS SE CALIBRA A SÍ MISMO
-------------------------------
1. **Criterio**: cada `esperado` es PROSA, no un identificador que pytest
   imprima solo al comparar.
2. **Control nulo**: la mutación 0 toca un comentario y tiene que dejar la
   suite VERDE.
3. **Ninguna mutación inerte**: toda mutación nombra un caso concreto de
   pytest (`fichero::nombre`) y ese caso SE EJECUTA. Una que sólo comprobara
   que la sustitución de texto ocurrió es un `grep` disfrazado -- no puede
   ponerse roja, luego no mide nada -- y `_mutaciones_sin_prueba_ejecutable`
   lo rechaza antes de empezar.
4. **Node obligatorio**: dos mutaciones corren la especificación JS. Sin Node
   ese caso se auto-omitiría con rc=0 y el arnés leería un falso verde, así
   que aborta.

USO
---
    python3 scripts/calibracion/workspace_autoridad_servidor.py

Requiere árbol limpio: las mutaciones se revierten con `git checkout --`.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FILTERED_PROVIDER = "viewer/app/authz/filtered_provider.py"
API_GRAPH = "viewer/app/api/graph.py"
AMBITO = "viewer/app/authz/ambito.py"
READONLY = "viewer/app/routers/readonly.py"
MAIN = "viewer/app/main.py"
GRAPH_JS = "viewer/app/static/js/graph.js"
GRAPH_CORE_JS = "viewer/app/static/js/graph-core.js"

SUITE_PROVIDER = "viewer/tests/test_authz_filtered_provider.py"
SUITE_HTTP = "viewer/tests/test_p0_autoridad_admin_full_http.py"
SUITE_AMBITO = "viewer/tests/test_ambito_autoridad_http.py"
SUITE_JS = "viewer/tests/test_graph_ux_v2.py"


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
    # --- los OCHO caminos del proveedor -----------------------------------
    Mutacion(
        nombre="1 · `graph()` deja de reautorizar el ámbito: vuelve a "
               "delegar el workspace del llamante sin comprobarlo",
        fichero=FILTERED_PROVIDER,
        viejo="        # Reautorización del ámbito (ver `_ambito_autorizado`).\n"
              "        if not self._ambito_autorizado(workspace):\n"
              "            return [], []\n"
              "        nodes, edges = self._base.graph(workspace, limit=_ALL, entity_type=entity_type, q=q)",
        nuevo="        nodes, edges = self._base.graph(workspace, limit=_ALL, entity_type=entity_type, q=q)",
        prueba=f"{SUITE_PROVIDER}::test_ningun_metodo_entrega_el_workspace_ajeno_con_el_filtro_apagado",
        esperado="FUGA DE AMBITO en `graph`",
    ),
    Mutacion(
        nombre="2 · `list_entities()` deja de reautorizar el ámbito",
        fichero=FILTERED_PROVIDER,
        viejo="        # Reautorización del ámbito (ver `_ambito_autorizado`).\n"
              "        if not self._ambito_autorizado(workspace):\n"
              "            return [], 0",
        nuevo="",
        prueba=f"{SUITE_PROVIDER}::test_ningun_metodo_entrega_el_workspace_ajeno_con_el_filtro_apagado",
        esperado="FUGA DE AMBITO en `list_entities`",
    ),
    Mutacion(
        nombre="3 · `_visible_nodes` vuelve a llamar al provider base sin "
               "reautorizar (arrastra entity_types, list_sources y source_detail)",
        fichero=FILTERED_PROVIDER,
        viejo="        if not self._ambito_autorizado(workspace):\n"
              "            return []\n"
              "        nodes, _ = self._base.list_entities(workspace, limit=_ALL, offset=0)",
        nuevo="        nodes, _ = self._base.list_entities(workspace, limit=_ALL, offset=0)",
        prueba=f"{SUITE_PROVIDER}::test_ningun_metodo_entrega_el_workspace_ajeno_con_el_filtro_apagado",
        esperado="FUGA DE AMBITO en `entity_types`",
    ),
    Mutacion(
        nombre="4 · `_visible_graph` vuelve a llamar al provider base sin "
               "reautorizar (arrastra counts y quality_metrics)",
        fichero=FILTERED_PROVIDER,
        viejo="        if not self._ambito_autorizado(workspace):\n"
              "            return [], []\n"
              "        nodes, edges = self._base.graph(workspace, limit=_ALL)",
        nuevo="        nodes, edges = self._base.graph(workspace, limit=_ALL)",
        prueba=f"{SUITE_PROVIDER}::test_ningun_metodo_entrega_el_workspace_ajeno_con_el_filtro_apagado",
        esperado="FUGA DE AMBITO en `counts`",
    ),
    Mutacion(
        nombre="5 · `search()` deja de reautorizar el ámbito",
        fichero=FILTERED_PROVIDER,
        viejo="        if not self._ambito_autorizado(workspace):\n"
              "            return []\n"
              "        raw = self._base.search(workspace, q, limit=_ALL)",
        nuevo="        raw = self._base.search(workspace, q, limit=_ALL)",
        prueba=f"{SUITE_PROVIDER}::test_ningun_metodo_entrega_el_workspace_ajeno_con_el_filtro_apagado",
        esperado="FUGA DE AMBITO en `search`",
    ),
    Mutacion(
        nombre="6 · la reautorización se retira ENTERA: control de que el "
               "control positivo de los ocho sigue midiendo algo",
        fichero=FILTERED_PROVIDER,
        viejo="        return self._ctx.admin_full or workspace in self._ctx.allowed_workspaces",
        nuevo="        return False",
        prueba=f"{SUITE_PROVIDER}::test_control_positivo_los_ocho_siguen_viendo_el_workspace_propio",
        esperado="el banco no esta midiendo una ausencia",
    ),

    # --- la autoridad del ÁMBITO, por HTTP ---------------------------------
    Mutacion(
        nombre="7 · la autoridad vuelve a aceptar el parámetro del cliente "
               "para un no-admin (el defecto original, ahora en un solo sitio)",
        fichero=AMBITO,
        viejo="    if len(canonicos) != 1:",
        nuevo="    if solicitado:\n        return solicitado\n    if len(canonicos) != 1:",
        prueba=f"{SUITE_AMBITO}::test_el_parametro_ajeno_NO_decide_el_ambito_de_un_no_admin",
        esperado="FUGA DE AMBITO en /api/search",
    ),
    Mutacion(
        nombre="8 · el fail-closed deja de verse: sin ámbito se devuelve la "
               "cadena vacía en vez de 409",
        fichero=AMBITO,
        viejo="    ws = ambito_de_la_peticion(ctx, solicitado)\n"
              "    if ws is None:\n"
              "        raise HTTPException(status_code=ESTADO_SIN_AMBITO, detail=MENSAJE_SIN_AMBITO)\n"
              "    return ws",
        nuevo="    return ambito_de_la_peticion(ctx, solicitado) or \"\"",
        prueba=f"{SUITE_AMBITO}::test_sin_autoridad_resuelta_ningun_endpoint_finge_un_workspace_vacio",
        esperado="presenta el fail-closed como un workspace normal y vacio",
    ),
    Mutacion(
        nombre="9 · `admin_full` pierde su selector declarado de workspace",
        fichero=AMBITO,
        viejo="        return solicitado or next(iter(canonicos), None)",
        nuevo="        return next(iter(canonicos), None)",
        prueba=f"{SUITE_AMBITO}::test_admin_full_conserva_el_selector_de_workspace",
        esperado="el selector que la decision declarada le concede",
    ),
    Mutacion(
        nombre="10 · las pantallas HTML vuelven a pintar la falta de ámbito "
               "como una página normal y vacía",
        fichero=READONLY,
        viejo="        status_code=409,\n    )",
        nuevo="        status_code=200,\n    )",
        prueba=f"{SUITE_AMBITO}::test_las_pantallas_HTML_usan_el_mismo_criterio",
        esperado="con la autoridad sin resolver",
    ),
    Mutacion(
        nombre="11 · `/graph` vuelve a leer el ENTORNO para `admin_full`: el "
               "segundo lector fuera de la autoridad (regresión de F-2)",
        fichero=MAIN,
        viejo="    return next(iter(scope.ctx.allowed_workspaces), \"\")\n"
              "\n\n@app.get(\"/graph\", response_class=HTMLResponse)",
        nuevo="    if scope.ctx.admin_full:\n"
              "        return get_settings().S9K_DEFAULT_WORKSPACE\n"
              "    return next(iter(scope.ctx.allowed_workspaces), \"\")\n"
              "\n\n@app.get(\"/graph\", response_class=HTMLResponse)",
        prueba=f"{SUITE_AMBITO}::test_la_pagina_del_grafo_arranca_en_lo_que_dice_la_autoridad_no_el_entorno",
        esperado="SEGUNDO LECTOR DEL ENTORNO",
    ),

    # --- el cliente ---------------------------------------------------------
    Mutacion(
        nombre="12 · el cliente vuelve a fabricar un workspace de repuesto "
               "cuando el servidor no le da ninguno",
        fichero=GRAPH_JS,
        viejo='  var workspace = window.S9K_WORKSPACE || "";',
        nuevo='  var workspace = window.S9K_WORKSPACE || "leyenda";',
        prueba=f"{SUITE_JS}::test_el_cliente_no_fabrica_un_workspace_de_repuesto",
        esperado="fabrica un workspace de repuesto",
    ),
    Mutacion(
        nombre="13 · el 409 pierde su familia propia en el cliente: la falta "
               "de ámbito se pinta como un error genérico",
        fichero=GRAPH_CORE_JS,
        viejo='    if (code === 409) return "no_scope";\n',
        nuevo="",
        # Corre la especificacion JS DE VERDAD con Node (es el mismo fichero
        # que ejecuta el job «Especificacion JS del grafo (Node obligatorio)»).
        # La ronda 1 declaro aqui una prueba que NUNCA se corria.
        prueba=f"{SUITE_JS}::test_graph_core_js_spec",
        esperado="la especificación JS ha fallado",
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


def _mutaciones_sin_prueba_ejecutable(mutaciones: list[Mutacion]) -> list[str]:
    """Ninguna mutación puede quedarse en «comprobar que el texto cambió».

    La ronda 1 tenía una que hacía exactamente eso: sustituía texto, comprobaba
    que la sustitución había ocurrido y declaraba un fichero de prueba que NO
    se ejecutaba nunca. Eso es un `grep` disfrazado: no puede ponerse roja, así
    que no mide nada. Este gate lo impide por construcción -- toda mutación
    declara un caso de pytest concreto (`fichero::nombre`) y ese caso se corre.
    """
    malas = []
    for i, m in enumerate(mutaciones, 1):
        if "::" not in m.prueba:
            malas.append(f"mutación {i}: `{m.prueba}` no nombra un caso "
                         f"concreto de pytest, así que no ejecuta nada")
        if not m.esperado:
            malas.append(f"mutación {i}: sin causa esperada, sólo mediría el "
                         f"color del fallo")
    return malas


def main() -> int:
    if shutil.which("node") is None:
        # Sin Node, `test_graph_core_js_spec` se auto-omite y pytest sale
        # rc=0: el calibrador leeria «verde con la mutacion puesta» y no
        # sabria distinguirlo de una garantia rota. Mejor no medir que medir
        # mal.
        print("FALTA NODE: la mutacion del cliente no se puede calibrar y su "
              "caso se omitiria en silencio. Instala Node y repite.")
        return 2
    if not _arbol_limpio():
        print("ÁRBOL SUCIO. Commitea antes: las mutaciones se revierten con "
              "`git checkout --` y se llevarían por delante tu trabajo.")
        return 2

    inertes = _mutaciones_sin_prueba_ejecutable(MUTACIONES)
    if inertes:
        print("MUTACIONES QUE NO EJECUTAN NADA:")
        for motivo in inertes:
            print(f"  · {motivo}")
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
