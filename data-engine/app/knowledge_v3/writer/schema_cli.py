# -*- coding: utf-8 -*-
"""Ruta de OPERADOR para el esquema del grafo. `ensure` y `verify`.

POR QUE EXISTE ESTE MODULO
--------------------------
Las restricciones del writer estaban DEFINIDAS en `schema.py` y NO INSTALADAS.
Medido contra un Neo4j con un apply real completo detras: `SHOW CONSTRAINTS`
devolvia CERO. `bootstrap_writer_schema` llevaba ahi todo el tiempo, pero
ningun mando de operador lo invocaba —se exportaba y se importaba, nada mas—,
asi que la unica forma de dejar un grafo nuevo en condiciones era teclear
Cypher a mano, que es justo lo que el criterio de producto prohibe.

Esto NO es un gate. Un gate juzga si se permite una operacion; esto INSTALA
lo que el producto necesita para funcionar. Es funcionalidad que faltaba.

LAS DOS PROPIEDADES QUE SE EXIGEN A SI MISMO
--------------------------------------------
* **Idempotente.** Todo el DDL es `IF NOT EXISTS`. Correrlo dos veces no
  rompe nada y la segunda vez no cambia nada; `ensure` lo DEMUESTRA en su
  salida, comparando el censo de antes y el de despues.
* **Observable.** No dice "hecho": dice QUE HAY, leido del servidor con
  `SHOW CONSTRAINTS`. La diferencia importa, porque el defecto que este
  modulo cierra nacio exactamente de creer una declaracion en vez de mirar.

USO

    python -m knowledge_v3.writer.schema_cli verify \\
        --neo4j-uri "$S9K_NEO4J_URI" --neo4j-user neo4j \\
        --neo4j-password-file /etc/s9k/neo4j.pass

    python -m knowledge_v3.writer.schema_cli ensure ... [--json]

`verify` es de SOLO LECTURA y no crea nada: sale 0 si esta todo, 3 si falta
algo. `ensure` instala y despues verifica; si tras instalar sigue faltando
algo, sale 3 y no miente.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from ..driver_neo4j import (
    ENV_DATABASE,
    ENV_PASSWORD_FILE,
    ENV_URI,
    ENV_USER,
    DriverConfigError,
    build_driver_factory,
    resolve_config,
)
from . import schema

#: Salidas de ESTE mando, deliberadamente fuera de la tabla del writer.
#: `writer/exit_codes.py` es de EQUIPO 5C (semantica de `--apply` y actas);
#: este modulo no toca ni un `rc` ni una frase de las suyas. Son tres valores
#: locales de una herramienta de esquema.
RC_OK = 0
RC_ERROR = 2
RC_INCOMPLETO = 3


def _censo(driver: Any) -> dict:
    """Lo que el SERVIDOR dice tener, no lo que este repo declara."""
    constraints = schema.observed_constraint_names(driver)
    indexes = schema.observed_index_names(driver)
    faltan = [n for n in schema.REQUIRED_CONSTRAINT_NAMES if n not in constraints]
    faltan_idx = [n for n in schema.REQUIRED_INDEX_NAMES if n not in indexes]
    return {
        "constraints_observadas": sorted(constraints),
        "constraints_requeridas": list(schema.REQUIRED_CONSTRAINT_NAMES),
        "constraints_faltantes": faltan,
        "indices_requeridos": list(schema.REQUIRED_INDEX_NAMES),
        "indices_faltantes": faltan_idx,
        "completo": not faltan and not faltan_idx,
    }


def _imprimir(censo: dict, cabecera: str, salida) -> None:
    print(cabecera, file=salida)
    print(f"  schema_version: {schema.SCHEMA_VERSION}", file=salida)
    print(
        f"  constraints observadas: {len(censo['constraints_observadas'])}"
        f" / requeridas: {len(censo['constraints_requeridas'])}",
        file=salida,
    )
    for nombre in censo["constraints_requeridas"]:
        marca = "OK  " if nombre not in censo["constraints_faltantes"] else "FALTA"
        print(f"    [{marca}] {nombre}", file=salida)
    for nombre in censo["indices_requeridos"]:
        marca = "OK  " if nombre not in censo["indices_faltantes"] else "FALTA"
        print(f"    [{marca}] {nombre}  (indice)", file=salida)
    print(f"  completo: {'si' if censo['completo'] else 'NO'}", file=salida)


def run(argv: Optional[list[str]] = None, *, driver_factory=None, env=None,
        stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)

    if driver_factory is None:
        try:
            config = resolve_config(
                uri=args.neo4j_uri,
                user=args.neo4j_user,
                password_file=args.neo4j_password_file,
                database=args.neo4j_database,
                env=env,
            )
        except DriverConfigError as exc:
            print(f"configuracion de conexion invalida: {exc}", file=stderr)
            return RC_ERROR
        driver_factory = build_driver_factory(config)

    try:
        driver = driver_factory()
    except Exception as exc:
        print(f"no se pudo conectar: {exc}", file=stderr)
        return RC_ERROR

    try:
        antes = _censo(driver)
        if args.accion == "verify":
            _imprimir(antes, "esquema OBSERVADO (verify, solo lectura):", stdout)
            resultado = antes
        else:
            _imprimir(antes, "esquema ANTES de ensure:", stdout)
            schema.bootstrap_writer_schema(driver)
            despues = _censo(driver)
            _imprimir(despues, "esquema DESPUES de ensure:", stdout)
            # La idempotencia se AFIRMA con datos, no de palabra: si ya
            # estaba completo antes, ensure no ha cambiado el censo.
            creadas = sorted(
                set(despues["constraints_observadas"])
                - set(antes["constraints_observadas"])
            )
            print(
                f"  creadas en esta ejecucion: {len(creadas)}"
                + (f" -> {', '.join(creadas)}" if creadas else " (ya estaban: no-op)"),
                file=stdout,
            )
            resultado = despues
        if args.json:
            print(json.dumps(resultado, ensure_ascii=False, sort_keys=True), file=stdout)
        return RC_OK if resultado["completo"] else RC_INCOMPLETO
    except Exception as exc:
        print(f"fallo al leer/aplicar el esquema: {exc}", file=stderr)
        return RC_ERROR
    finally:
        try:
            driver.close()
        except Exception:  # pragma: no cover - cierre best-effort
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="s9k-schema",
        description="instala (ensure) o comprueba (verify) el esquema del writer V3",
    )
    p.add_argument("accion", choices=("ensure", "verify"))
    p.add_argument("--json", action="store_true", help="ademas, el censo en JSON")
    p.add_argument("--neo4j-uri", default=None, help=f"URI del servidor ({ENV_URI})")
    p.add_argument("--neo4j-user", default=None, help=f"usuario ({ENV_USER})")
    p.add_argument(
        "--neo4j-password-file", default=None,
        help=f"CAMINO del fichero 0600 con el secreto, o '-' ({ENV_PASSWORD_FILE})",
    )
    p.add_argument("--neo4j-database", default=None, help=f"base de datos ({ENV_DATABASE})")
    return p


def main() -> int:  # pragma: no cover - envoltorio
    return run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
