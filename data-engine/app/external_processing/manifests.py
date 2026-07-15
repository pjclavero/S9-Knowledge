# -*- coding: utf-8 -*-
"""Manifiesto de lote para procesamiento externo (Fase B1).

El BatchManifest describe completamente un lote de procesamiento:
archivos de entrada, jobs a ejecutar, modo seleccionado y metadatos.

Reglas de seguridad:
- private_path NUNCA se exporta a servicios externos.
- sanitized_name es el nombre seguro que puede aparecer en logs/payloads.
- source_hash permite idempotencia.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError("pydantic es requerido para external_processing.manifests")

from external_processing.models import ProcessingMode


class BatchFile(BaseModel):
    private_path: str       # NUNCA exportar a servicios externos
    sanitized_name: str
    mime_type: str
    size_bytes: int
    file_hash: str
    pages: Optional[int] = None
    duration_seconds: Optional[float] = None
    image_count: Optional[int] = None
    expected_language: Optional[str] = None

    def export_safe(self) -> dict:
        """Devuelve representacion sin private_path ni rutas internas."""
        return {
            "sanitized_name": self.sanitized_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "file_hash": self.file_hash,
            "pages": self.pages,
            "duration_seconds": self.duration_seconds,
            "image_count": self.image_count,
            "expected_language": self.expected_language,
        }


class BatchManifest(BaseModel):
    batch_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace: str
    source_id: str
    mode: ProcessingMode
    source_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    files: List[BatchFile] = Field(default_factory=list)
    jobs: List[str] = Field(default_factory=list)  # job IDs
    status: str = "created"
    planner_version: str = "B1.0"
    policy_version: str = "B1.0"
    dry_run: bool = False

    # Metricas de carga calculadas por el planner
    total_audio_minutes: float = 0.0
    total_pdf_pages: int = 0
    total_images: int = 0
    total_size_bytes: int = 0

    def to_dict(self) -> dict:
        return self.dict()

    def export_safe(self) -> dict:
        """Representacion sin rutas privadas, apta para logs y reportes externos."""
        d = self.dict()
        d["files"] = [f.export_safe() for f in self.files]
        return d

    def save(self, output_dir: Path) -> Path:
        """Persiste el manifiesto en disco como JSON."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"manifest_{self.batch_id}.json"
        path.write_text(
            json.dumps(self.dict(), ensure_ascii=False, default=str),
            encoding="utf-8"
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "BatchManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)
