# -*- coding: utf-8 -*-
"""Fabrica de driver Neo4j para la ruta de operador del writer.

Vive FUERA del paquete `knowledge_v3.writer` a proposito. El writer mantiene su
higiene comprobada — ni un `import` del paquete de Neo4j, ni una URI, ni una
credencial dentro de sus modulos — y la conexion real se construye aqui, en el
unico modulo que si conoce el controlador.

Reglas que este modulo impone, no sugiere:

* **La contrasena no viaja por `argv`.** Se lee de un fichero cuyo camino se
  declara (`--neo4j-password-file` o `S9K_NEO4J_PASSWORD_FILE`), o de la entrada
  estandar. No hay ninguna opcion que acepte el secreto en la linea de comandos.
* **El fichero de contrasena tiene que ser privado.** Si el grupo u otros pueden
  leerlo, se rechaza: un secreto legible por la maquina entera no es un secreto.
* **El secreto no se imprime nunca.** La configuracion que este modulo pasea
  guarda el CAMINO del fichero, no su contenido, y su `repr` es el de un
  dataclass sin campo de secreto.
* **La fabrica no conecta al construirse.** Devuelve un invocable; quien lo llama
  es el writer, y solo despues de que el gate haya autorizado el APPLY.
"""
from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

#: URI del servidor (esquema `bolt`/`neo4j`). Sin valor por defecto: una URI por
#: defecto es una conexion que nadie declaro.
ENV_URI = "S9K_NEO4J_URI"
ENV_USER = "S9K_NEO4J_USER"
#: CAMINO del fichero con la contrasena. Nunca la contrasena.
ENV_PASSWORD_FILE = "S9K_NEO4J_PASSWORD_FILE"
ENV_DATABASE = "S9K_NEO4J_DATABASE"

#: Valor admitido en `--neo4j-password-file` para leer el secreto de stdin.
STDIN_SENTINEL = "-"


class DriverConfigError(ValueError):
    """Configuracion de conexion incompleta o insegura. Nunca lleva el secreto."""


@dataclass(frozen=True)
class DriverConfig:
    """Como llegar al servidor. Guarda el CAMINO del secreto, no el secreto."""

    uri: str
    user: str
    password_file: str
    database: Optional[str] = None


def _first(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value:
            return value
    return None


def resolve_config(
    *,
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password_file: Optional[str] = None,
    database: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> DriverConfig:
    """Argumento explicito primero, entorno despues, nada por defecto."""
    environ = env if env is not None else dict(os.environ)
    resolved_uri = _first(uri, environ.get(ENV_URI))
    resolved_user = _first(user, environ.get(ENV_USER))
    resolved_file = _first(password_file, environ.get(ENV_PASSWORD_FILE))
    faltan = [
        nombre
        for nombre, valor in (
            (f"--neo4j-uri / {ENV_URI}", resolved_uri),
            (f"--neo4j-user / {ENV_USER}", resolved_user),
            (f"--neo4j-password-file / {ENV_PASSWORD_FILE}", resolved_file),
        )
        if not valor
    ]
    if faltan:
        raise DriverConfigError(
            "faltan datos de conexion para el APPLY: " + ", ".join(faltan)
        )
    return DriverConfig(
        uri=str(resolved_uri),
        user=str(resolved_user),
        password_file=str(resolved_file),
        database=_first(database, environ.get(ENV_DATABASE)),
    )


def read_secret(password_file: str) -> str:
    """Lee el secreto de un fichero privado (o de stdin con `-`).

    Comprueba los permisos ANTES de leer: si el fichero es legible por el grupo
    o por otros, no se lee. El mensaje de error jamas incluye el contenido.
    """
    if password_file == STDIN_SENTINEL:
        secreto = sys.stdin.readline().rstrip("\n")
        if not secreto:
            raise DriverConfigError("la entrada estandar no traia ninguna contrasena")
        return secreto

    ruta = Path(password_file)
    try:
        modo = ruta.stat().st_mode
    except OSError as exc:
        raise DriverConfigError(
            f"no se pudo leer el fichero de contrasena {password_file!r}: {exc.strerror}"
        ) from exc
    if modo & (stat.S_IRWXG | stat.S_IRWXO):
        raise DriverConfigError(
            f"el fichero de contrasena {password_file!r} es accesible por grupo u "
            "otros: hazlo 0600 antes de usarlo"
        )
    secreto = ruta.read_text(encoding="utf-8").rstrip("\n")
    if not secreto:
        raise DriverConfigError(
            f"el fichero de contrasena {password_file!r} esta vacio"
        )
    return secreto


def build_driver_factory(
    config: DriverConfig,
    *,
    connect: Optional[Callable[..., Any]] = None,
) -> Callable[[], Any]:
    """Devuelve la FABRICA. No conecta aqui: conectar es cosa de quien la invoca.

    `connect` existe para las pruebas: por defecto es `neo4j.GraphDatabase.driver`,
    importado dentro de la funcion para que este modulo no exija el controlador
    a quien solo hace dry-run.
    """

    def factory() -> Any:
        secreto = read_secret(config.password_file)
        abrir = connect
        if abrir is None:
            from neo4j import GraphDatabase  # import perezoso, a proposito

            abrir = GraphDatabase.driver
        driver = abrir(config.uri, auth=(config.user, secreto))
        if config.database:
            return _DriverEnBase(driver, config.database)
        return driver

    return factory


class _DriverEnBase:
    """Driver atado a una base concreta.

    El executor abre `driver.session()` sin argumentos; si el operador declara
    `--neo4j-database`, la unica forma de que ese `session()` caiga en la base
    correcta es interponer esta envoltura. No anade capacidades: reenvia.
    """

    def __init__(self, driver: Any, database: str):
        self._driver = driver
        self._database = database

    def session(self, **kwargs: Any) -> Any:
        kwargs.setdefault("database", self._database)
        return self._driver.session(**kwargs)

    def close(self) -> None:
        self._driver.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._driver, name)


__all__ = [
    "DriverConfig",
    "DriverConfigError",
    "ENV_URI",
    "ENV_USER",
    "ENV_PASSWORD_FILE",
    "ENV_DATABASE",
    "STDIN_SENTINEL",
    "resolve_config",
    "read_secret",
    "build_driver_factory",
]
