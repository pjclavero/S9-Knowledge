# -*- coding: utf-8 -*-
"""Tests de seguridad: secretos, rutas privadas, Neo4j, ingest-approved (Fase B1).

Tests 25-29.
"""
import uuid
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.models import ExternalTaskType, JobStatus, ProcessingJob, ProcessingMode
from external_processing.result_validator import _scan_secrets, _scan_private_paths
from external_processing.manifests import BatchFile


# ── Test 25: ausencia de secretos en resultado exportado ─────────────────────

def test_resultado_sin_secretos():
    """Resultado limpio del mock no contiene secretos."""
    from external_processing.providers.mock import MockExternalProcessingProvider

    provider = MockExternalProcessingProvider(scenario="success")
    job = ProcessingJob(
        batch_id=str(uuid.uuid4()),
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
        status=JobStatus.RUNNING,
        chunk={
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 60.0,
            "source_hash": "src_hash_clean",
            "overlap_start": 0.0,
            "overlap_end": 0.0,
        },
    )
    result = provider.execute(job)
    secrets = _scan_secrets(result)
    assert len(secrets) == 0, f"Secretos encontrados: {secrets}"


# ── Test 26: ruta privada no aparece en payload externo ──────────────────────

def test_ruta_privada_no_en_payload():
    """BatchFile.export_safe() no incluye private_path."""
    bf = BatchFile(
        private_path="/home/ia02/data/secreto.mp3",
        sanitized_name="audio.mp3",
        mime_type="audio/mpeg",
        size_bytes=1000000,
        file_hash="h" * 64,
        duration_seconds=120.0,
    )
    safe = bf.export_safe()
    assert "private_path" not in safe
    assert "/home/ia02" not in str(safe)


def test_ruta_privada_en_representacion_completa():
    """BatchFile.dict() SI contiene private_path (uso interno)."""
    bf = BatchFile(
        private_path="/home/ia02/data/secreto.mp3",
        sanitized_name="audio.mp3",
        mime_type="audio/mpeg",
        size_bytes=1000000,
        file_hash="h" * 64,
    )
    full = bf.dict()
    assert "private_path" in full


# ── Test 27: proveedor sin capacidad -> UNSUPPORTED, no ejecuta ──────────────

def test_proveedor_sin_capacidad_no_ejecuta():
    """Si el proveedor no tiene la capacidad, el job falla sin ejecutar."""
    from external_processing.dispatcher import BurstDispatcher
    from external_processing.providers.mock import MockExternalProcessingProvider
    from external_processing.capabilities import Capability

    provider = MockExternalProcessingProvider()
    provider.capabilities = {Capability.RERANK}  # sin TRANSCRIBE_AUDIO

    executed = [False]
    original_execute = provider.execute
    def tracking_execute(job):
        executed[0] = True
        return original_execute(job)
    provider.execute = tracking_execute

    dispatcher = BurstDispatcher(provider, max_concurrency=1)
    job = ProcessingJob(
        batch_id=str(uuid.uuid4()),
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
    )
    result = dispatcher.dispatch_one(job)

    provider.capabilities = set(Capability)  # restaurar

    assert result.status == JobStatus.FAILED
    from external_processing.errors import ErrorCode
    assert result.error_code == ErrorCode.UNSUPPORTED_CAPABILITY
    assert not executed[0], "execute() no debe llamarse para capacidad no soportada"


# ── Test 28: ninguna llamada a Neo4j en todo el flujo ────────────────────────

def test_ninguna_llamada_neo4j():
    """El flujo completo no importa ni llama a modulos Neo4j."""
    import sys
    # Guardar estado de modulos
    neo4j_before = [k for k in sys.modules if "neo4j" in k.lower()]

    # Ejecutar flujo basico
    from external_processing.providers.mock import MockExternalProcessingProvider
    from external_processing.dispatcher import BurstDispatcher
    from external_processing.result_validator import validate_batch
    from external_processing.result_merger import merge_batch_results

    provider = MockExternalProcessingProvider(scenario="success")
    dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.0)

    job = ProcessingJob(
        batch_id="test_batch",
        workspace="ws",
        source_id="src",
        task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
        processing_mode=ProcessingMode.LOCAL,
        chunk={"chunk_index": 0, "chunk_start": 0.0, "chunk_end": 60.0,
               "source_hash": "h", "overlap_start": 0.0, "overlap_end": 0.0},
    )
    results = dispatcher.dispatch_batch([job])
    validated, _ = validate_batch(results)
    merge_batch_results("b", "ws", "s", "h", ExternalTaskType.TRANSCRIBE_AUDIO, validated)

    neo4j_after = [k for k in sys.modules if "neo4j" in k.lower()]
    new_neo4j = set(neo4j_after) - set(neo4j_before)
    assert len(new_neo4j) == 0, f"Nuevos modulos Neo4j: {new_neo4j}"


# ── Test 29: ninguna llamada a ingest-approved ────────────────────────────────

def test_ninguna_llamada_ingest_approved():
    """El flujo no importa review.ingest_approved."""
    import sys
    # ingest_approved no debe estar importado como resultado del flujo
    before = set(k for k in sys.modules if "ingest_approved" in k)

    from external_processing.providers.mock import MockExternalProcessingProvider
    from external_processing.dispatcher import BurstDispatcher
    from external_processing.result_merger import merge_batch_results

    provider = MockExternalProcessingProvider()
    dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.0)

    job = ProcessingJob(
        batch_id="test",
        workspace="ws",
        source_id="s",
        task_type=ExternalTaskType.OCR_IMAGE,
        processing_mode=ProcessingMode.LOCAL,
        chunk={"chunk_index": 0, "page_start": 1, "page_end": 5,
               "document_hash": "dh"},
    )
    results = dispatcher.dispatch_batch([job])
    merge_batch_results("b", "ws", "s", "h", ExternalTaskType.OCR_IMAGE, results)

    after = set(k for k in sys.modules if "ingest_approved" in k)
    new_ingest = after - before
    assert len(new_ingest) == 0, f"ingest_approved importado: {new_ingest}"


def test_approved_payload_no_generado():
    """El flujo no genera approved_payload."""
    from external_processing.result_merger import merge_batch_results

    jobs = []  # sin jobs
    merged = merge_batch_results("b", "ws", "s", "h", ExternalTaskType.TRANSCRIBE_AUDIO, jobs)

    # MergedResult no tiene campo approved_payload
    result_dict = merged.dict()
    assert "approved_payload" not in result_dict
    assert "ingest" not in str(result_dict).lower() or "ingest" not in merged.status.lower()
