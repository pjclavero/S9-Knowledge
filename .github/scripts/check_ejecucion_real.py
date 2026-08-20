#!/usr/bin/env python3
"""Lo que un job EJECUTO de verdad, contra el inventario de suites.

POR QUE EXISTE ESTA CAPA (y por que no es "una superficie mas")
==============================================================
Las tres rondas anteriores de este carril cerraron, una por una, las vias de
apagar una suite critica desde `ci.yml`: los ARGUMENTOS (`--ignore`, `-k`,
`--deselect`, `-m`, `addopts`) y luego las nueve superficies de ENTORNO
(SUP-1..SUP-9 en `check_suite_inventory.py`). En cada ronda un revisor
independiente encontro superficie NUEVA: `container.options` con `-e`, `uses:`
a nivel de JOB, un nombre construido por concatenacion de comillas en vez de
con `$`...

No fue descuido: la superficie es ABIERTA. Cinco niveles de `env:`, cuatro
formas de asignar en shell, `$GITHUB_ENV`, construccion de nombres,
`container.options`, `uses:`, y lo que GitHub anada el mes que viene. Enumerar
causas es perseguir un blanco que se mueve.

Para los ARGUMENTOS, prohibir fue lo correcto: son un conjunto cerrado y viven
en la linea que el gate ya parsea. Para el ENTORNO lo que gana es verificar el
RESULTADO, no la causa: si `viewer/tests/test_parcialidad_declarada.py` no
reporta sus pruebas en el job que tiene que ejecutarlas, ROJO, SIN IMPORTAR POR
QUE. `PYTEST_ADDOPTS`, `container.options`, un `sitecustomize.py`, un `uses:` a
un workflow reutilizable, o el vector que nadie ha imaginado todavia: todos
producen el mismo efecto observable, y este control mira el efecto.

Es la misma logica que `test-neo4j-authz` ya usaba con acierto
(`grep -qi skipped` -> `::error::`), generalizada a modulo por modulo.

NO SUSTITUYE a los nueve SUP: se SUMA. Aquellos siguen puestos y siguen
calibrados; pasan de ser la unica linea a ser defensa en profundidad. Una capa
que mira la CAUSA avisa antes y dice QUE se rompio; una que mira el RESULTADO
no se puede rodear. Hacen falta las dos.

QUE COMPARA
===========
`--junitxml` es el informe de ejecucion de pytest: una entrada `<testcase>` por
prueba que el job llego a EJECUTAR, con su modulo en `classname`. Frente a el
se pone `.github/suite-inventario.json`, que NO es una lista escrita a mano
sino la MEDIDA de la coleccion real (ver `check_suite_inventory.py`).

  * modulo obligatorio que reporta CERO pruebas  -> ROJO
  * informe entero vacio, o sin fichero          -> ROJO (fail-closed)

POR QUE **NO** SE COMPARAN LOS RECUENTOS, dicho antes de que alguien lo pida
============================================================================
La primera version de este control comparaba tambien el numero de pruebas por
modulo, y al medirla contra una corrida real salio ROJA en 9 modulos que estan
perfectamente sanos. La causa no era un fallo del CI: `en_pie` cuenta FUNCIONES
de test (`def test_...`, que es lo que mide la coleccion de
`check_suite_inventory.py`) y JUnit cuenta INSTANCIAS ejecutadas, que con
`parametrize` son muchas mas. Medido en este arbol: 5352 funciones declaradas
frente a 7961 instancias reportadas, ratio 1.49. Son unidades distintas y
compararlas es comparar peras con kilos.

Se podria haber "arreglado" bajando el umbral hasta que dejara de protestar.
Eso habria sido un numero elegido para que el control callara, no una medida.
Asi que el recuento NO se compara aqui y se dice por que: la garantia de ESTA
capa es la DESAPARICION —ningun modulo obligatorio puede quedarse sin una sola
prueba en el informe—, que es justo lo que producen `--ignore`, `-k`, `-m`,
`--deselect` y todo lo que los inyecte. El recorte PARCIAL tiene ya su propio
control y su propia calibracion en otra capa: el trinquete de recuento (control
D de `check_suite_inventory.py`), que compara coleccion contra coleccion, o sea
unidades iguales contra unidades iguales.

Los modulos que el inventario declara con 0 pruebas (ficheros de fixtures sin
tests propios) quedan fuera de la obligacion: exigirles una prueba seria un
rojo falso permanente, y un gate que grita sin motivo acaba desactivado.

Cuenta la prueba REPORTADA sea cual sea su resultado, tambien `skipped`: apagar
por `skip` ya lo cazan los controles A y G de `check_suite_inventory.py`, y
duplicarlo aqui solo enturbiaria de que rojo viene cada cosa. Lo que ESTE
control ve es la DESAPARICION: `--ignore`, `-k`, `--deselect`, `-m` y todo lo
que inyecte esas opciones sacan la prueba del informe por completo.

Los modulos DELEGADOS (los que solo corren en el job que instala Chromium) se
excluyen de la obligacion: aqui su `importorskip` los deja sin ninguna entrada,
y exigirselos seria un rojo falso permanente. Su trinquete es el de PRESENCIA
en `check_suite_inventory.py`, no este.

ABLACION
========
`S9K_EJECUCION_ABLACION=1` desactiva la comparacion contra el inventario y deja
solo la guardia anti-cero. Existe para que la calibracion demuestre que quitar
esta capa devuelve a VERDE los casos que con ella salen ROJOS. Fuera de la
calibracion no se usa, y el control lo GRITA en la salida.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INVENTARIO = REPO / ".github" / "suite-inventario.json"

ABLACION = os.environ.get("S9K_EJECUCION_ABLACION", "").strip() == "1"


def _modulo_a_prefijo(ruta: str) -> str:
    """`viewer/tests/test_x.py` -> `viewer.tests.test_x`, que es el `classname`
    que pytest escribe en el informe JUnit."""
    sin_ext = ruta[:-3] if ruta.endswith(".py") else ruta
    return sin_ext.replace("/", ".")


def _ficheros_junit(entradas: list[str]) -> list[Path]:
    ficheros: list[Path] = []
    for entrada in entradas:
        ruta = Path(entrada)
        if not ruta.is_absolute():
            ruta = REPO / ruta
        if ruta.is_dir():
            ficheros.extend(sorted(ruta.rglob("*.xml")))
        elif ruta.exists():
            ficheros.append(ruta)
    return ficheros


def reportado_por_modulo(ficheros: list[Path]) -> tuple[dict[str, int], int]:
    """`classname` -> nº de `<testcase>`, y el total. Sin interpretar nada."""
    por_clase: dict[str, int] = {}
    total = 0
    for fichero in ficheros:
        raiz = ET.parse(fichero).getroot()
        for caso in raiz.iter("testcase"):
            clase = caso.get("classname") or ""
            por_clase[clase] = por_clase.get(clase, 0) + 1
            total += 1
    return por_clase, total


def cuenta_de(prefijo: str, por_clase: dict[str, int]) -> int:
    """Las pruebas de un modulo, con o sin clase de por medio."""
    return sum(n for clase, n in por_clase.items()
               if clase == prefijo or clase.startswith(prefijo + "."))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", action="append", required=True,
                    help="fichero o directorio con informes JUnit de pytest")
    ap.add_argument("--raiz", action="append", default=None,
                    help="limita la obligacion a estas raices (por defecto, "
                         "todas las del inventario)")
    args = ap.parse_args()

    if ABLACION:
        print("::warning::ABLACION ACTIVA: la comparacion contra el inventario "
              "esta DESACTIVADA. Solo queda la guardia anti-cero. Esto no puede "
              "quedarse puesto fuera de la calibracion.")

    if not INVENTARIO.exists():
        print(f"::error::falta {INVENTARIO.name}: sin inventario no hay con que "
              f"comparar lo ejecutado, y un control que no puede comparar no "
              f"puede certificar nada.")
        return 1
    datos = json.loads(INVENTARIO.read_text(encoding="utf-8"))
    en_pie: dict[str, int] = datos["en_pie"]
    delegados = set(datos.get("delegados") or ())
    raices = args.raiz or list(datos.get("raices") or ())

    ficheros = _ficheros_junit(args.junit)
    if not ficheros:
        print(f"::error::no hay ningun informe JUnit en {args.junit}. Sin "
              f"informe no se puede afirmar que el job ejecutara nada: un "
              f"control sin medida es un check verde que no mira.")
        return 1

    por_clase, total = reportado_por_modulo(ficheros)
    print(f"informes leidos: {[f.name for f in ficheros]}")
    print(f"pruebas reportadas en total: {total}")

    if total == 0:
        print("::error::el informe JUnit no contiene ni una sola prueba. El job "
              "no ejecuto nada, diga lo que diga su codigo de salida.")
        return 1

    obligatorios = {
        modulo: n for modulo, n in en_pie.items()
        if modulo not in delegados
        and any(modulo == r or modulo.startswith(r.rstrip("/") + "/")
                for r in raices)
    }
    print(f"modulos obligatorios en estas raices: {len(obligatorios)} "
          f"({len(delegados)} delegados excluidos)")

    if ABLACION:
        print("ABLACION: no se compara modulo a modulo.")
        return 0

    errores: list[str] = []
    reportado_total = 0
    con_pruebas = {m: n for m, n in obligatorios.items() if n > 0}
    sin_pruebas = len(obligatorios) - len(con_pruebas)
    for modulo, esperadas in sorted(con_pruebas.items()):
        reportadas = cuenta_de(_modulo_a_prefijo(modulo), por_clase)
        reportado_total += reportadas
        if reportadas == 0:
            errores.append(
                f"DESAPARECIDO EN EJECUCION: `{modulo}` declara {esperadas} "
                f"pruebas en el inventario y el job NO REPORTO NINGUNA. Da igual "
                f"por que: `--ignore`, `-k`, `-m`, `--deselect`, `PYTEST_ADDOPTS` "
                f"por cualquiera de sus vias, `container.options -e`, un "
                f"`sitecustomize.py`, un workflow reutilizable... o el vector que "
                f"nadie ha imaginado todavia. El efecto es el mismo, y es el "
                f"efecto lo que aqui se prohibe."
            )

    for e in errores:
        print(f"::error::{e}")
    if errores:
        print(f"\nFALLO: {len(errores)} problema(s) entre lo que el inventario "
              f"declara y lo que el job EJECUTO de verdad.")
        return 1

    print(f"OK: los {len(con_pruebas)} modulos obligatorios con pruebas "
          f"reportaron ejecucion real ({reportado_total} instancias); "
          f"{sin_pruebas} modulos sin pruebas propias quedan fuera de la "
          f"obligacion. Ninguna suite desaparecio del informe, sea cual sea la "
          f"via por la que alguien lo intentara.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
