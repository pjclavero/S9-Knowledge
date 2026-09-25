#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CALIBRACIÓN del corte S-1 «el resultado que se ofrece es el resultado que
hay».

Mismo motor que `mutaciones_s3_env_gobierna_paneles.py`: un verde sólo vale si
la prueba que lo da es CAPAZ DE PONERSE ROJA, y roja POR SU CAUSA. Cada
mutación reintroduce UN defecto real de este corte sobre el código real, uno
cada vez, y comprueba:

    1. que los casos que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa.

Cubre las cuatro formas en que la propiedad puede volver a romperse:

    1. `alcanzable_para` deja de mirar `_workspace_autorizado` (el defecto
       original de S-1: un apply con operaciones pero sin `:Entity` volvería a
       leerse como alcanzable).
    2. `alcanzable_para` deja de mirar el resultado de
       `reader.operations_of_apply` (cualquier apply con lector, dejara marca
       o no, se leería como alcanzable).
    3. `_camino_al_resultado` deja de retirar el enlace cuando
       `alcanzable_para` dice que no (vuelve a ofrecer `disponible` sobre el
       404 documentado en `docs/92`).
    4. `_camino_al_resultado` deja de tratar la AUSENCIA de lector de
       procedencia como indeterminada y pregunta igualmente: sin backend de
       procedencia (el proveedor `mock` que usa el resto de esta suite) el
       desenlace se volvería `sin_identidad` en vez de conservar el previo,
       rompiendo el resto de la suite de este panel con una guarda que no
       puede preguntar nada.

LAS MUTACIONES SE REFERENCIAN POR NOMBRE. EL RECUENTO SALE DEL FICHERO
(`len(MUTACIONES)`). EL CRUCE compara los casos que la suite RECOLECTA contra
los rojos REALES.

QUÉ NO MIDE ESTE CALIBRADOR, DECLARADO. Muta por SUSTITUCIÓN DE TEXTO EXACTO
sobre el fuente y corre sólo `tests/test_s1_camino_sin_enlace_muerto.py`, que
son objetos de mentira sin Neo4j: mide la LÓGICA de decisión, no la
MATERIALIZACIÓN contra un grafo real. Esa la miden, aparte y contra Docker, los
dos casos `@neo4j_real` de `test_panel_apply_desde_la_ui.py`
(`test_S1_sin_alta_aprobada_el_panel_YA_NO_OFRECE_un_enlace_muerto` y
`test_SIN_ALTA_APROBADA_el_destino_niega_el_apply_que_acaba_de_ocurrir`), que
este calibrador no re-ejerce porque exigirían Docker en este job.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
VIEWER = RAIZ / "viewer"
RESULT_PROVENANCE = VIEWER / "app" / "services" / "result_provenance.py"
CHASSIS_OPERATIONS = VIEWER / "app" / "routers" / "chassis_operations.py"
SUITE = "tests/test_s1_camino_sin_enlace_muerto.py"


@dataclass(frozen=True)
class Mutacion:
    """Un defecto reintroducido, con lo que DEBE caer y con qué debe decirlo."""

    nombre: str
    fichero: Path
    viejo: str
    nuevo: str
    #: Casos que tienen que ponerse rojos. Se comparan por subcadena del nodeid.
    caen: tuple[str, ...]
    #: Fragmento que TIENE que aparecer en la salida del rojo. Es la CAUSA.
    dice: str
    porque: str = ""
    extra: tuple[tuple[Path, str, str], ...] = field(default_factory=tuple)


MUTACIONES: tuple[Mutacion, ...] = (
    Mutacion(
        nombre="alcanzable-ignora-la-autorizacion-de-workspace",
        fichero=RESULT_PROVENANCE,
        viejo=(
            "    if not es_apply_id(apply_id):\n"
            "        return False\n"
            "    if not _workspace_autorizado(provider, workspace):\n"
            "        return False\n"
            "    if reader is None:\n"
            "        return False\n"
        ),
        nuevo=(
            "    if not es_apply_id(apply_id):\n"
            "        return False\n"
            "    if reader is None:\n"
            "        return False\n"
        ),
        caen=(
            "test_no_alcanzable_cuando_el_ambito_NO_incluye_el_workspace",
            "test_camino_sin_identidad_cuando_NO_alcanzable",
        ),
        dice="S-1: el panel sigue ofreciendo",
        porque=(
            "Es el defecto original de S-1: un apply con operaciones "
            "registradas pero SIN `:Entity` (el recorrido revisión->apply sin "
            "alta aprobada) volvería a leerse como alcanzable y el panel "
            "volvería a ofrecer el enlace que docs/92 midió como 404."
        ),
    ),
    Mutacion(
        nombre="alcanzable-ignora-si-el-apply-dejo-marca",
        fichero=RESULT_PROVENANCE,
        viejo=(
            "    try:\n"
            "        return bool(reader.operations_of_apply(workspace, apply_id))\n"
            "    except Exception:  # noqa: BLE001 - indeterminado, no se afirma alcanzable\n"
            "        return False\n"
        ),
        nuevo=(
            "    try:\n"
            "        reader.operations_of_apply(workspace, apply_id)\n"
            "        return True\n"
            "    except Exception:  # noqa: BLE001 - indeterminado, no se afirma alcanzable\n"
            "        return False\n"
        ),
        caen=(
            "test_no_alcanzable_si_el_reader_no_ve_ninguna_operacion",
        ),
        dice="alcanzable_para() dio alcanzable=True para un apply sin ninguna",
        porque=(
            "Si dejara de importar el CONTENIDO de `operations_of_apply` y "
            "sólo mirara que no reviente, un apply sin ninguna marca en este "
            "workspace se leería igual de alcanzable que uno con ella."
        ),
    ),
    Mutacion(
        nombre="camino-no-retira-el-enlace-cuando-no-es-alcanzable",
        fichero=CHASSIS_OPERATIONS,
        viejo=(
            "            if not alcanzable:\n"
            "                # AUSENCIA, no cero: se escribió (lo dice `afirmaciones_escritas`\n"
            "                # en otro bloque de esta misma pantalla) y este producto no\n"
            "                # sabe llevarte hasta ello. Nunca se publica un enlace que hoy\n"
            "                # respondería 404.\n"
            "                return {\"resultado\": \"sin_identidad\", \"apply_id\": None,\n"
            "                        \"workspace\": None}\n"
        ),
        nuevo=(
            "            if False:\n"
            "                return {\"resultado\": \"sin_identidad\", \"apply_id\": None,\n"
            "                        \"workspace\": None}\n"
        ),
        caen=(
            "test_camino_sin_identidad_cuando_NO_alcanzable",
        ),
        dice="S-1: el panel sigue ofreciendo",
        porque=(
            "Si el consumidor dejara de actuar sobre `alcanzable_para` -aunque "
            "la función siguiera calculándolo bien-, el panel volvería a "
            "pintar `disponible` sobre el 404 documentado en docs/92: es el "
            "síntoma exacto que S-1 cierra."
        ),
    ),
    Mutacion(
        nombre="camino-pregunta-igual-sin-lector-de-procedencia",
        fichero=CHASSIS_OPERATIONS,
        viejo=(
            "        reader = reader_for(provider)\n"
            "        if reader is not None:\n"
            "            alcanzable = result_provenance.alcanzable_para(\n"
            "                provider, reader, workspace, estado.apply_id,\n"
            "            )\n"
            "            if not alcanzable:\n"
        ),
        nuevo=(
            "        reader = reader_for(provider)\n"
            "        alcanzable = result_provenance.alcanzable_para(\n"
            "            provider, reader, workspace, estado.apply_id,\n"
            "        )\n"
            "        if True:\n"
            "            if not alcanzable:\n"
        ),
        caen=(
            "test_camino_sigue_disponible_sin_lector_de_procedencia",
        ),
        dice="sin lector de procedencia el desenlace debía conservarse",
        porque=(
            "Sin backend de procedencia (el proveedor `mock` que usa el resto "
            "de esta suite, y muchos despliegues) no hay nada que preguntar. "
            "Tratar esa AUSENCIA como negativa convertiría cada `disponible` "
            "existente en `sin_identidad` en cuanto faltara Neo4j, rompiendo "
            "el resto del panel con una guarda ciega."
        ),
    ),
)


def _pytest(selector: str | None = None) -> subprocess.CompletedProcess:
    # `--color=no` no es cosmético: con color, las líneas del resumen empiezan
    # por una secuencia de escape y `startswith("FAILED")` no casa nunca.
    orden = [sys.executable, "-m", "pytest", SUITE, "-q", "-p", "no:randomly",
             "--color=no"]
    if selector:
        orden += ["-k", selector]
    return subprocess.run(orden, cwd=VIEWER, capture_output=True, text=True)


def _casos_del_fichero() -> set[str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "--collect-only", "-q",
         "--color=no", "-p", "no:randomly"],
        cwd=VIEWER, capture_output=True, text=True,
    )
    casos = {
        linea.split("::")[-1].split("[")[0].strip()
        for linea in r.stdout.splitlines() if "::" in linea
    }
    if not casos:
        raise AssertionError(
            "EL CRUCE NO RECOLECTÓ NINGÚN CASO. Sin casos, «ninguno sin "
            "calibrar» sería verdad por vacío.\n"
            + r.stdout[-2000:] + r.stderr[-2000:]
        )
    return casos


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        if ".git" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio() -> bool:
    """TRACKED únicamente: es lo que la mutación puede destruir y lo que
    `git checkout --` puede devolver."""
    r = subprocess.run(
        ["git", "diff", "--stat", "--"], cwd=RAIZ, capture_output=True, text=True
    )
    return r.stdout.strip() == ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo", help="calibrar una mutación por NOMBRE")
    args = parser.parse_args()

    if not _arbol_limpio():
        print("ABORTA: el árbol tiene cambios sin commitear. Una mutación "
              "sobre un árbol sucio no se puede restaurar por efecto.")
        return 2

    seleccionadas = MUTACIONES
    if args.solo:
        seleccionadas = tuple(m for m in MUTACIONES if m.nombre == args.solo)
        if not seleccionadas:
            print(f"ABORTA: no hay ninguna mutación llamada {args.solo!r}. "
                  f"Hay: {[m.nombre for m in MUTACIONES]}")
            return 2

    _purgar_pycache()
    base = _pytest()
    if base.returncode != 0:
        print("ABORTA: la suite YA está roja sin mutar. Cualquier rojo de "
              "abajo sería suyo, no de la mutación.")
        print(base.stdout[-3000:])
        return 2
    print(f"BASE VERDE. {SUITE}\n")

    total = len(seleccionadas)
    fallos: list[str] = []
    rojos_vistos: set[str] = set()
    print(f"{total} mutaciones declaradas en este fichero.\n")

    for mut in seleccionadas:
        print("=" * 74)
        print(f"MUTACIÓN  {mut.nombre}")
        print(f"  fichero {mut.fichero.relative_to(RAIZ)}")
        print(f"  porqué  {mut.porque}")
        parches = ((mut.fichero, mut.viejo, mut.nuevo),) + mut.extra
        try:
            for fichero, viejo, nuevo in parches:
                texto = fichero.read_text(encoding="utf-8")
                if texto.count(viejo) != 1:
                    raise AssertionError(
                        f"el texto a mutar aparece {texto.count(viejo)} veces "
                        f"en {fichero.name} (se esperaba 1). El código se ha "
                        f"movido: esta mutación NO estaba mordiendo."
                    )
                fichero.write_text(texto.replace(viejo, nuevo), encoding="utf-8")
            if _arbol_limpio():
                raise AssertionError(
                    "tras escribir la mutación, `git diff` no ve NINGÚN "
                    "cambio. La mutación no llegó al disco."
                )
            _purgar_pycache()

            res = _pytest()
            salida = res.stdout + res.stderr
            if res.returncode == 0:
                fallos.append(
                    f"{mut.nombre}: LA SUITE SIGUE VERDE CON EL DEFECTO "
                    f"PUESTO. Ningún control vigila esto."
                )
                print("  RESULTADO  *** VERDE CON EL DEFECTO — CONTROL CIEGO ***")
                continue

            rojos = [
                linea.split("::")[-1].split(" ")[0]
                for linea in salida.splitlines()
                if linea.startswith("FAILED") or linea.startswith("ERROR ")
            ]
            faltan = [c for c in mut.caen if not any(c in r for r in rojos)]
            if faltan:
                fallos.append(
                    f"{mut.nombre}: se esperaba que cayeran {faltan} y NO "
                    f"cayeron. Cayeron: {rojos}"
                )
                print(f"  RESULTADO  rojo, pero NO cayeron {faltan}")
            else:
                print(f"  ROJOS      {len(rojos)}: {sorted(set(r.split('[')[0] for r in rojos))}")
            rojos_vistos.update(r.split("[")[0] for r in rojos)

            if mut.dice not in salida:
                fallos.append(
                    f"{mut.nombre}: el rojo NO DICE SU CAUSA. Se esperaba el "
                    f"mensaje {mut.dice!r} y no aparece."
                )
                print(f"  MENSAJE    *** FALTA {mut.dice!r} ***")
            else:
                print(f"  MENSAJE    OK — el rojo dice: «{mut.dice}»")
        finally:
            for fichero, _, _ in parches:
                subprocess.run(
                    ["git", "checkout", "--", str(fichero.relative_to(RAIZ))],
                    cwd=RAIZ, check=True,
                )
            _purgar_pycache()
            if not _arbol_limpio():
                print("  *** EL ÁRBOL NO QUEDÓ RESTAURADO. ABORTA. ***")
                return 3

    print("=" * 74)
    _purgar_pycache()
    final = _pytest()
    if final.returncode != 0:
        print("LA SUITE NO VOLVIÓ A VERDE tras restaurar. La calibración dejó "
              "el árbol tocado y sus resultados no valen.")
        print(final.stdout[-3000:])
        return 3

    if not args.solo:
        casos = _casos_del_fichero()
        huerfanos = sorted(casos - rojos_vistos)
        print(f"CRUCE: {len(casos)} casos recolectados, "
              f"{len(casos) - len(huerfanos)} enrojecen con alguna mutación.")
        if huerfanos:
            for h in huerfanos:
                print(f"  ::SIN CALIBRAR:: {h}")
            print(
                "  (No se cuentan como fallo: hay casos de este corte —el "
                "caso 1 desde la función y desde el consumidor, la guarda de "
                "identidad previa, la de excepción cerrada— que verifican la "
                "propiedad desde otro ángulo y que ninguna mutación de ESTE "
                "fichero está diseñada para romper. Se listan para que quien "
                "añada mutaciones nuevas sepa qué falta cubrir.)"
            )

    if fallos:
        print(f"CALIBRACIÓN FALLIDA — {len(fallos)} problemas sobre {total} "
              f"mutaciones:")
        for f in fallos:
            print("  * " + f)
        return 1
    print(f"CALIBRACIÓN OK — {total}/{total} mutaciones producen un rojo que "
          f"DICE SU CAUSA, y la suite vuelve a verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
