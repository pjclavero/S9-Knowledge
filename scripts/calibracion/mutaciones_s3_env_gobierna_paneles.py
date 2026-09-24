#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CALIBRACIÓN del corte S-3 «el `.env` gobierna lo que dice gobernar».

Mismo motor que `mutaciones_bootstrap_primer_admin.py` y
`mutaciones_instalacion_fabrica.py`: un verde sólo vale si la prueba que lo da
es CAPAZ DE PONERSE ROJA, y roja POR SU CAUSA. Cada mutación reintroduce UN
defecto real de este corte sobre el código real, uno cada vez, y comprueba:

    1. que los casos que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa.

Cubre las cinco formas en que la propiedad "`.env` gobierna" puede volver a
romperse:

    1. `chassis.slot_enabled` vuelve a leer `os.environ` directamente.
    2. `resultado._encendido` vuelve a leer `os.environ` directamente.
    3. `effective_env_value` deja de consultar `.env` (sólo mira el entorno).
    4. La precedencia se invierte (`.env` gana sobre el entorno del proceso).
    5. La comparación de nombres de clave vuelve a ser sensible a
       mayúsculas/minúsculas (la clave 14/14 de la ronda 2 de revisión: la
       misma firma del defecto original, por caja en vez de por fichero).

LAS MUTACIONES SE REFERENCIAN POR NOMBRE. EL RECUENTO SALE DEL FICHERO
(`len(MUTACIONES)`). EL CRUCE compara los casos que la suite RECOLECTA contra
los rojos REALES.

TECHO DE ESTE CALIBRADOR:
  * Muta por SUSTITUCIÓN DE TEXTO EXACTO sobre el fuente. No ve alias ni una
    segunda copia de la misma lógica en otro módulo (por ejemplo, si mañana
    apareciera un tercer lector de estos interruptores fuera de
    `app.config.effective_env_value`, esto no lo vería).
  * MIRA UNA SOLA SUITE (`SUITE`, constante única):
    `viewer/tests/test_s3_env_gobierna_paneles.py`.
  * No mide despliegue real, ni systemd, ni Ansible, ni un navegador de
    verdad: eso está en el informe del corte, medido con uvicorn real en
    subproceso, no aquí.
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
CONFIG = VIEWER / "app" / "config.py"
CHASSIS = VIEWER / "app" / "chassis.py"
RESULTADO = VIEWER / "app" / "routers" / "resultado.py"
SUITE = "tests/test_s3_env_gobierna_paneles.py"


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
        nombre="slot-enabled-vuelve-a-os-environ",
        fichero=CHASSIS,
        viejo=(
            "    else:\n"
            "        from app.config import effective_env_value\n"
            "\n"
            "        raw = effective_env_value(slot_flag_env(slot))\n"
        ),
        nuevo=(
            "    else:\n"
            "        import os as _os\n"
            "\n"
            "        raw = _os.environ.get(slot_flag_env(slot))\n"
        ),
        caen=(
            "test_env_con_los_cuatro_paneles_a_true_los_enciende",
            "test_el_env_gana_solo_cuando_el_entorno_calla",
            "test_slot_enabled_no_lee_os_environ_directamente",
        ),
        dice="respondió 404 con",
        porque=(
            "Es el defecto original del corte: `chassis.slot_enabled` volviendo "
            "a leer `os.environ` a pelo, ciego a `viewer/.env`, deja los cuatro "
            "paneles en 404 en silencio aunque el operador los haya encendido "
            "en el fichero."
        ),
    ),
    Mutacion(
        nombre="encendido-vuelve-a-os-environ",
        fichero=RESULTADO,
        viejo=(
            "    from app.config import effective_env_value\n"
            "\n"
            "    raw = effective_env_value(FLAG_ENV)\n"
        ),
        nuevo=(
            "    import os as _os\n"
            "\n"
            "    raw = _os.environ.get(FLAG_ENV)\n"
        ),
        caen=(
            "test_env_gobierna_resultado_via_effective_env_value",
            "test_resultado_encendido_no_lee_os_environ_directamente",
        ),
        dice="con la clave sólo en `.env`",
        porque=(
            "El MISMO defecto que el de `slot_enabled`, en la pantalla de "
            "resultado: `resultado._encendido` tenía la misma lectura ciega a "
            "`.env` y se corrigió a la vez porque es la MISMA propiedad."
        ),
    ),
    Mutacion(
        nombre="effective-env-value-ignora-el-dotenv",
        fichero=CONFIG,
        viejo=(
            "    valor_entorno = _valor_insensible_a_mayusculas(os.environ, name)\n"
            "    if valor_entorno is not None:\n"
            "        return valor_entorno\n"
            "    try:\n"
            "        valores = dotenv_values(DOTENV_FILENAME)\n"
            "    except OSError:\n"
            "        return None\n"
            "    return _valor_insensible_a_mayusculas(valores, name)\n"
        ),
        nuevo=(
            "    return _valor_insensible_a_mayusculas(os.environ, name)\n"
        ),
        caen=(
            "test_env_con_los_cuatro_paneles_a_true_los_enciende",
            "test_el_env_gana_solo_cuando_el_entorno_calla",
            "test_env_gobierna_resultado_via_effective_env_value",
        ),
        dice="respondió 404 con",
        porque=(
            "Si la autoridad única deja de mirar `.env` del todo, la "
            "propiedad entera queda vacía: da igual lo bien que deleguen "
            "`slot_enabled` y `_encendido`, el fichero nunca gobierna nada."
        ),
    ),
    Mutacion(
        nombre="precedencia-invertida-env-sobre-entorno",
        fichero=CONFIG,
        viejo=(
            "    valor_entorno = _valor_insensible_a_mayusculas(os.environ, name)\n"
            "    if valor_entorno is not None:\n"
            "        return valor_entorno\n"
            "    try:\n"
            "        valores = dotenv_values(DOTENV_FILENAME)\n"
            "    except OSError:\n"
            "        return None\n"
            "    return _valor_insensible_a_mayusculas(valores, name)\n"
        ),
        nuevo=(
            "    try:\n"
            "        valores = dotenv_values(DOTENV_FILENAME)\n"
            "    except OSError:\n"
            "        valores = {}\n"
            "    valor_dotenv = _valor_insensible_a_mayusculas(valores, name)\n"
            "    if valor_dotenv is not None:\n"
            "        return valor_dotenv\n"
            "    return _valor_insensible_a_mayusculas(os.environ, name)\n"
        ),
        caen=(
            "test_el_entorno_gana_sobre_el_env_mismo_fichero_mismo_proceso",
        ),
        dice="el entorno debe ganar y no lo hizo",
        porque=(
            "El despliegue real depende de que `EnvironmentFile=` de systemd "
            "siga ganando sobre cualquier `.env` que una release trajera "
            "consigo. Invertir la precedencia rompe justo esa garantía, en "
            "silencio: el síntoma es que un `.env` heredado de otra máquina "
            "pisaría la configuración de producción."
        ),
    ),
    Mutacion(
        nombre="caja-de-la-clave-vuelve-a-ser-sensible",
        fichero=CONFIG,
        viejo=(
            "    if name in mapa:\n"
            "        return mapa[name]\n"
            "    objetivo = name.casefold()\n"
            "    for clave, valor in mapa.items():\n"
            "        if clave.casefold() == objetivo:\n"
            "            return valor\n"
            "    return None\n"
        ),
        nuevo=(
            "    return mapa.get(name)\n"
        ),
        caen=(
            "test_env_en_minusculas_enciende_el_panel_igual_que_en_mayusculas",
            "test_effective_env_value_es_insensible_a_mayusculas_en_env_y_en_dotenv",
        ),
        dice="minúsculas",
        porque=(
            "La clave 14/14 de la ronda 2 de revisión: `pydantic-settings` "
            "(`case_sensitive=False`) sigue viendo `s9k_auth_enabled` en "
            "minúsculas, pero una comparación exacta aquí no ve "
            "`s9k_panel_g_enabled` — la MISMA firma del defecto original (una "
            "clave se aplica, la otra no, en silencio), esta vez por caja de "
            "la clave y no por fichero."
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
                "control positivo, el par de #248, los negativos de "
                "resultado— que verifican la propiedad desde otro ángulo y "
                "que ninguna mutación de ESTE fichero está diseñada para "
                "romper. Se listan para que quien añada mutaciones nuevas "
                "sepa qué falta cubrir.)"
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
