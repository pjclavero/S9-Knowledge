#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CALIBRACIÓN del corte S-3b «el `.env` gobierna también dónde vive la bóveda».

Mismo motor que `mutaciones_s3_env_gobierna_paneles.py`: un verde sólo vale si
la prueba que lo da es CAPAZ DE PONERSE ROJA, y roja POR SU CAUSA. Cada
mutación reintroduce UN defecto real de este corte sobre el código real, uno
cada vez, y comprueba:

    1. que los casos que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa.

Cubre las tres formas en que la propiedad "`.env` gobierna también la bóveda"
puede volver a romperse, en los TRES lectores que la auditoría de este corte
encontró con la MISMA firma:

    1. `sources_catalog._valor_gobernado` vuelve a leer `os.environ`
       directamente (el defecto original: `S9K_VAULT_ROOT`,
       `S9K_INGEST_SOURCES_DIR`, `S9K_VAULT_REQUIRE_MOUNT`).
    2. `auth.db._db_path` vuelve a leer `S9K_AUTH_DB_PATH` de `os.environ`
       en vez de por `effective_env_value`.
    3. `health.runner.build_default_config` vuelve a leer `S9K_NEO4J_URI`
       (y el resto de la familia de la plantilla) de `os.environ`.

LAS MUTACIONES SE REFERENCIAN POR NOMBRE. EL RECUENTO SALE DEL FICHERO
(`len(MUTACIONES)`). EL CRUCE compara los casos que la suite RECOLECTA contra
los rojos REALES.

TECHO DE ESTE CALIBRADOR:
  * Muta por SUSTITUCIÓN DE TEXTO EXACTO sobre el fuente. No ve alias ni una
    segunda copia de la misma lógica en otro módulo.
  * MIRA UNA SOLA SUITE (`SUITE`, constante única):
    `viewer/tests/test_s3b_env_gobierna_boveda.py`.
  * No mide despliegue real, ni systemd, ni Ansible: eso está en el informe
    del corte, medido con uvicorn real en subproceso, no aquí.
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
SOURCES_CATALOG = VIEWER / "app" / "sources_catalog.py"
AUTH_DB = VIEWER / "app" / "auth" / "db.py"
HEALTH_RUNNER = VIEWER / "app" / "health" / "runner.py"
SUITE = "tests/test_s3b_env_gobierna_boveda.py"


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
        nombre="valor-gobernado-vuelve-a-os-environ",
        fichero=SOURCES_CATALOG,
        viejo=(
            "    if env is not None:\n"
            "        return env.get(clave)\n"
            "    return config.effective_env_value(clave)\n"
        ),
        nuevo=(
            "    if env is not None:\n"
            "        return env.get(clave)\n"
            "    return os.environ.get(clave)\n"
        ),
        caen=(
            "test_A_vault_root_solo_en_env_enciende_el_modo_boveda",
            "test_B_ingest_sources_dir_solo_en_env_tiene_efecto",
            "test_sources_catalog_no_lee_os_environ_directamente",
        ),
        dice="el fichero que el operador editó no gobernó",
        porque=(
            "Es el defecto original de este corte: `raiz_de_bovedas`, "
            "`directorio_de_fuentes`, `ubicacion_declarada` y "
            "`_exigir_montaje` volviendo a leer `os.environ` a pelo, ciegas "
            "a `.env`, dejan cualquier bóveda declarada sólo en el fichero "
            "cayendo en el catálogo plano de ejemplo del repositorio."
        ),
    ),
    Mutacion(
        nombre="auth-db-path-vuelve-a-os-environ",
        fichero=AUTH_DB,
        viejo=(
            "    valor = config.effective_env_value(\"S9K_AUTH_DB_PATH\")\n"
            "    raw = valor if (valor is not None and valor.strip()) else _DB_PATH_DEFAULT\n"
        ),
        nuevo=(
            "    import os as _os\n\n"
            "    raw = _os.environ.get(\"S9K_AUTH_DB_PATH\", _DB_PATH_DEFAULT)\n"
        ),
        caen=(
            "test_auth_db_path_no_lee_os_environ_directamente",
            "test_auth_db_path_solo_en_env_resuelve_a_esa_ruta",
        ),
        dice="_db_path()",
        porque=(
            "La MISMA firma, en la base de datos de autenticación: un "
            "operador que declara `S9K_AUTH_DB_PATH` sólo en `.env` vería "
            "`AuthSettings` resolver una ruta y esta capa de bajo nivel "
            "abrir otra distinta — dos autoridades sobre la misma base."
        ),
    ),
    Mutacion(
        nombre="auth-db-path-vacia-se-toma-por-valor",
        fichero=AUTH_DB,
        viejo=(
            "    raw = valor if (valor is not None and valor.strip()) else _DB_PATH_DEFAULT\n"
        ),
        nuevo=(
            "    raw = valor if valor is not None else _DB_PATH_DEFAULT\n"
        ),
        caen=(
            "test_auth_db_path_de_la_plantilla_literal_no_es_un_directorio",
        ),
        dice="una clave PRESENTE PERO VACÍA se está tomando por una ruta declarada",
        porque=(
            "RONDA 2. `viewer/.env.example` trae `S9K_AUTH_DB_PATH=` EN "
            "BLANCO (línea activa, no comentada): `effective_env_value` "
            "devuelve `''`, no `None`, para esa clave. Comparar sólo contra "
            "`None` no basta — `Path('')` es el directorio de trabajo, no un "
            "fichero — y con la plantilla LITERAL (sin que ningún test la "
            "sobrescriba) `_db_path()` deja de apuntar a una base de datos."
        ),
    ),
    Mutacion(
        nombre="health-runner-neo4j-uri-vuelve-a-os-environ",
        fichero=HEALTH_RUNNER,
        viejo='            "uri": _gob("S9K_NEO4J_URI", "bolt://127.0.0.1:7687"),\n',
        nuevo=(
            '            "uri": os.environ.get('
            '"S9K_NEO4J_URI", "bolt://127.0.0.1:7687"),\n'
        ),
        caen=(
            "test_health_runner_no_lee_las_claves_de_la_plantilla_por_os_environ",
            "test_health_runner_neo4j_uri_solo_en_env_se_usa",
        ),
        dice="el healthcheck",
        porque=(
            "La MISMA firma, en el healthcheck operativo: si `S9K_NEO4J_URI` "
            "sólo está en `.env`, el healthcheck auditaría un Neo4j distinto "
            "del que la aplicación usa de verdad."
        ),
    ),
    Mutacion(
        nombre="health-runner-auth-db-path-vacia-se-toma-por-valor",
        fichero=HEALTH_RUNNER,
        viejo=(
            "    valor = config.effective_env_value(name)\n"
            "    if valor is not None and valor.strip():\n"
            "        return valor\n"
            "    return default\n"
        ),
        nuevo=(
            "    valor = config.effective_env_value(name)\n"
            "    return valor if valor is not None else default\n"
        ),
        caen=(
            "test_health_runner_auth_db_path_de_la_plantilla_literal_no_es_un_directorio",
        ),
        dice="una clave presente-pero-vacía se tomó por un valor declarado",
        porque=(
            "RONDA 2, MISMA firma en el healthcheck: con la plantilla "
            "literal (`S9K_AUTH_DB_PATH=` en blanco), `_gob_ruta` sin la "
            "comprobación de `.strip()` ofrecería `db_path=''` en vez del "
            "default de fábrica de `AuthSettings` — el healthcheck "
            "reportaría una base inexistente que no es tal."
        ),
    ),
)


def _pytest(selector: str | None = None) -> subprocess.CompletedProcess:
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
                "control positivo de A, la precedencia de C, el negativo D— "
                "que verifican la propiedad desde otro ángulo y que ninguna "
                "mutación de ESTE fichero está diseñada para romper.)"
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
