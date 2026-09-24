"""Configuración del visor S9 Knowledge, leída de variables de entorno / .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "Settings",
    "get_settings",
    "effective_env_value",
]

#: Mismo fichero que consultan `Settings`/`AuthSettings` (`env_file=".env"`):
#: relativo al directorio de trabajo del proceso, NO a la ubicación de este
#: módulo. Una única constante para que quien lea variables "gobernadas por
#: `.env`" fuera de un modelo `BaseSettings` (por ejemplo, un interruptor
#: leído en caliente en cada petición) consulte el MISMO fichero, con la
#: MISMA regla de precedencia, en vez de inventar una tercera lectura.
DOTENV_FILENAME = ".env"


def effective_env_value(name: str) -> Optional[str]:
    """Valor EFECTIVO de ``name``: autoridad única para "¿qué dice `.env`?".

    Precedencia, la misma que aplica `pydantic-settings` a `Settings` y
    `AuthSettings` (y la misma que exige el despliegue real, donde
    `EnvironmentFile=` de systemd sigue mandando sobre cualquier plantilla):

      1. **Entorno del proceso** (`os.environ`). Si la variable está puesta
         ahí —aunque sea a cadena vacía—, gana. Este es el canal que systemd
         usa en producción (`viewer/systemd/s9-knowledge-viewer.service`,
         `EnvironmentFile=/etc/s9-knowledge/viewer.env`) y el que un
         operador de laboratorio usa con `export` o `docker run -e`.
      2. **`.env`** en el directorio de trabajo del proceso —el mismo fichero
         y la misma ruta relativa que usan `Settings`/`AuthSettings`—. Sólo se
         consulta si el paso 1 no dio nada.
      3. Ninguno de los dos define la variable -> ``None``.

    SIN CACHÉ a propósito, igual que `slot_enabled`/`_encendido`: un operador
    que edita `.env` y reinicia el proceso tiene que ver el cambio, y una
    variable de entorno cacheada al importar convertiría "editar el fichero"
    en "editar el fichero y además tocar el código". Releer `.env` en cada
    llamada es una lectura de fichero pequeña (unas pocas líneas) en el
    camino de una petición HTTP local; el coste es aceptable frente a la
    alternativa de un flag que miente tras el primer arranque.
    """
    if name in os.environ:
        return os.environ[name]
    try:
        valores = dotenv_values(DOTENV_FILENAME)
    except OSError:
        return None
    return valores.get(name)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    S9K_VIEWER_HOST: str = "127.0.0.1"
    S9K_VIEWER_PORT: int = 8088

    S9K_GRAPH_PROVIDER: str = "mock"  # "mock" | "neo4j"
    S9K_DEFAULT_WORKSPACE: str = "leyenda"
    S9K_GRAPH_LIMIT: int = 300

    # Fail-closed (RK-05): el default apunta a loopback, igual que data-engine
    # (bolt://127.0.0.1:7687). Nunca a una IP productiva. Producción configura
    # S9K_NEO4J_URI explícitamente por entorno; en laboratorio/CI se usa el
    # provider "mock", de modo que este default nunca abre una conexión a prod.
    S9K_NEO4J_URI: str = "bolt://127.0.0.1:7687"
    S9K_NEO4J_USER: str = "neo4j"
    S9K_NEO4J_PASSWORD: str = ""
    S9K_NEO4J_PASSWORD_FILE: str = ""

    S9K_SAMPLE_GRAPH_PATH: str = "examples/sample_graph.json"

    # Panel de jobs (Fase v0.2.4 "jobs worker and jobs panel"). Vacío por
    # defecto: se resuelve en tiempo de uso contra data-engine/state/jobs.db
    # o la ruta que indique job_store.DEFAULT_DB_PATH si tampoco se ha fijado.
    S9K_JOBS_DB: str = ""

    # Visor de solo lectura — parámetros de paginación y seguridad (Tarea C).
    S9K_VIEWER_DEFAULT_PAGE_SIZE: int = 50
    S9K_VIEWER_MAX_PAGE_SIZE: int = 200
    S9K_VIEWER_QUERY_TIMEOUT_SECONDS: int = 10
    S9K_VIEWER_MAX_SEARCH_LENGTH: int = 200

    @property
    def neo4j_password(self) -> str:
        """Resuelve la contraseña de Neo4j: archivo primero, luego variable directa."""
        if self.S9K_NEO4J_PASSWORD_FILE:
            path = Path(self.S9K_NEO4J_PASSWORD_FILE)
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()
        return self.S9K_NEO4J_PASSWORD


@lru_cache
def get_settings() -> Settings:
    return Settings()
