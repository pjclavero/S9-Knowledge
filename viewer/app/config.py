"""Configuración del visor S9 Knowledge, leída de variables de entorno / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    S9K_VIEWER_HOST: str = "127.0.0.1"
    S9K_VIEWER_PORT: int = 8088

    S9K_GRAPH_PROVIDER: str = "mock"  # "mock" | "neo4j"
    S9K_DEFAULT_WORKSPACE: str = "leyenda"
    S9K_GRAPH_LIMIT: int = 300

    S9K_NEO4J_URI: str = "bolt://192.168.1.205:7687"
    S9K_NEO4J_USER: str = "neo4j"
    S9K_NEO4J_PASSWORD: str = ""
    S9K_NEO4J_PASSWORD_FILE: str = ""

    S9K_SAMPLE_GRAPH_PATH: str = "examples/sample_graph.json"

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
