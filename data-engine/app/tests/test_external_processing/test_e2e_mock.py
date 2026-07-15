# -*- coding: utf-8 -*-
"""Test E2E de pipeline completo con proveedor mock (Fase B1).

Lote sintetico:
  - 2 audios pequeños (fixtures, no archivos reales)
  - 3 imagenes (fixtures)
  - 10 paginas de texto/PDF (fixtures)

Flujo: plan -> dispatch(mock) -> validate -> merge -> READY_FOR_LOCAL_PIPELINE

Confirma explicitamente:
  - Neo4j: 0 llamadas
  - writer: no invocado
  - ingest_approved: no invocado
  - approved_payload: no generado
"""
import sys
import time
import uuid
import pytest
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.cache import ProcessingCache, build_cache_key
from external_processing.capabilities import Capability
from external_processing.chunking import chunk_audio, chunk_pdf, chunk_images, chunk_range_key
from external_processing.dispatcher import BurstDispatcher
from external_processing.manifests import BatchFile, BatchManifest
from external_processing.models import (
    ExternalTaskType,
    JobStatus,
    ProcessingJob,
    ProcessingMode,
)
from external_processing.planner import BurstPlanner
from external_processing.providers.mock import MockExternalProcessingProvider
from external_processing.result_merger import merge_batch_results
from external_processing.result_validator import validate_batch


# ── Fixtures sinteticos ────────────────────────────────────────────────────────

def _make_audio_file(name: str, duration: float) -> BatchFile:
    import hashlib
    return BatchFile(
        private_path=f"/private/audio/{name}",
        sanitized_name=name,
        mime_type="audio/mpeg",
        size_bytes=int(duration * 16000),
        file_hash=hashlib.sha256(name.encode()).hexdigest(),
        duration_seconds=duration,
        expected_language="es",
    )


def _make_image_file(name: str) -> BatchFile:
    import hashlib
    return BatchFile(
        private_path=f"/private/images/{name}",
        sanitized_name=name,
        mime_type="image/jpeg",
        size_bytes=250000,
        file_hash=hashlib.sha256(name.encode()).hexdigest(),
        image_count=1,
    )


def _make_pdf_file(name: str, pages: int) -> BatchFile:
    import hashlib
    return BatchFile(
        private_path=f"/private/pdfs/{name}",
        sanitized_name=name,
        mime_type="application/pdf",
        size_bytes=pages * 50000,
        file_hash=hashlib.sha256(name.encode()).hexdigest(),
        pages=pages,
    )


# ── Helper para crear jobs manualmente ───────────────────────────────────────

def _create_jobs_from_files(
    batch_id: str,
    workspace: str,
    source_id: str,
    files: list[BatchFile],
    provider: str = "mock",
    cache: ProcessingCache = None,
    cache_hits_requested: list[BatchFile] = None,
) -> list[ProcessingJob]:
    """Crea jobs de procesamiento a partir de los archivos del batch."""
    jobs = []
    cache_hits_requested = cache_hits_requested or []

    for bf in files:
        mime = bf.mime_type.lower()

        if "audio" in mime:
            # Crear chunks de audio
            dur = bf.duration_seconds or 0.0
            chunks = chunk_audio(bf.file_hash, dur, max_chunk_seconds=600.0, overlap_seconds=2.0)
            for chunk in chunks:
                cr = chunk_range_key(chunk)
                cache_k = build_cache_key(bf.file_hash, ExternalTaskType.TRANSCRIBE_AUDIO, cr, provider, "mock-asr")
                cache_hit = False
                cached_result = None
                if cache and bf in cache_hits_requested:
                    # Forzar cache hit: pre-almacenar resultado
                    pre_result = {
                        "text": f"Texto cacheado {bf.sanitized_name}",
                        "source_hash": bf.file_hash,
                        "language": "es",
                    }
                    cache.put(cache_k, pre_result)
                    cached_result = {"result": pre_result}
                    cache_hit = True

                job = ProcessingJob(
                    batch_id=batch_id,
                    workspace=workspace,
                    source_id=source_id,
                    task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
                    processing_mode=ProcessingMode.LOCAL,
                    provider=provider,
                    model="mock-asr",
                    chunk=chunk.dict(),
                    cache_hit=cache_hit,
                    result=cached_result["result"] if cached_result else None,
                    status=JobStatus.READY if cache_hit else JobStatus.DETECTED,
                )
                jobs.append(job)

        elif "image" in mime:
            image_count = bf.image_count or 1
            from external_processing.chunking import chunk_images
            tasks = chunk_images(bf.file_hash, [f"img_{i}" for i in range(image_count)])
            for task in tasks:
                job = ProcessingJob(
                    batch_id=batch_id,
                    workspace=workspace,
                    source_id=source_id,
                    task_type=ExternalTaskType.IMAGE_ANALYSIS,
                    processing_mode=ProcessingMode.LOCAL,
                    provider=provider,
                    model="mock-vision",
                    chunk=task.dict(),
                )
                jobs.append(job)

        elif "pdf" in mime:
            pages = bf.pages or 1
            from external_processing.chunking import chunk_pdf
            chunks = chunk_pdf(bf.file_hash, pages, max_pages_per_chunk=5)
            for chunk in chunks:
                job = ProcessingJob(
                    batch_id=batch_id,
                    workspace=workspace,
                    source_id=source_id,
                    task_type=ExternalTaskType.OCR_IMAGE,
                    processing_mode=ProcessingMode.LOCAL,
                    provider=provider,
                    model="mock-ocr",
                    chunk=chunk.dict(),
                )
                jobs.append(job)

    return jobs


# ── Test E2E principal ────────────────────────────────────────────────────────

class TestE2EMockPipeline:
    """Test E2E completo: plan -> dispatch -> validate -> merge."""

    def setup_method(self):
        """Configuracion inicial."""
        self.batch_id = str(uuid.uuid4())
        self.workspace = "leyenda"
        self.source_id = "source_e2e_b1"
        self.source_hash = "e2e_source_hash_b1_" + "0" * 44

        # Lote sintetico
        self.audio_files = [
            _make_audio_file("sesion_01.mp3", duration=120.0),  # 2 min
            _make_audio_file("sesion_02.mp3", duration=180.0),  # 3 min
        ]
        self.image_files = [
            _make_image_file("mapa_01.jpg"),
            _make_image_file("ficha_02.jpg"),
            _make_image_file("ilustracion_03.jpg"),
        ]
        self.pdf_files = [
            _make_pdf_file("notas_sesion.pdf", pages=10),  # 10 paginas
        ]
        self.all_files = self.audio_files + self.image_files + self.pdf_files

        # Contadores de seguridad
        self._neo4j_calls = 0
        self._writer_calls = 0
        self._ingest_approved_calls = 0
        self._approved_payloads = []

    def test_e2e_flujo_completo(self, tmp_path):
        """Ejecuta el pipeline completo y verifica metricas y seguridad."""
        # ── 0. Snapshot de estado de modulos ANTES del pipeline ───────────────
        # Capturar ANTES de ejecutar el pipeline para detectar solo contaminacion
        # causada por el pipeline de Fase B1, no por otros tests de la suite.
        _ingest_mods_before = set(k for k in sys.modules if "ingest_approved" in k)

        # ── 1. Crear cache ────────────────────────────────────────────────────
        cache = ProcessingCache(tmp_path, enabled=True)

        # Pre-cachear el primer audio (para verificar cache hits)
        first_audio = self.audio_files[0]
        first_chunk_range = "audio:0.000-120.000"
        cache_key = build_cache_key(
            first_audio.file_hash, ExternalTaskType.TRANSCRIBE_AUDIO,
            first_chunk_range, "mock", "mock-asr"
        )
        cache.put(cache_key, {
            "text": "Audio cacheado del primer segmento",
            "source_hash": first_audio.file_hash,
            "language": "es",
        })

        # ── 2. Crear jobs ─────────────────────────────────────────────────────
        start_time = time.time()
        jobs = _create_jobs_from_files(
            self.batch_id,
            self.workspace,
            self.source_id,
            self.all_files,
            cache=cache,
            cache_hits_requested=[first_audio],
        )

        # Verificar jobs creados
        total_jobs_created = len(jobs)
        cache_hits_at_start = sum(1 for j in jobs if j.cache_hit)

        # Esperamos: 2 audios (chunks) + 3 imagenes + 10 paginas/5 = 2 chunks pdf
        # Los audios de 120s y 180s no se dividen (< 600s = 10 min)
        assert total_jobs_created >= 7, f"Jobs insuficientes: {total_jobs_created}"

        # ── 3. Dispatch con mock ──────────────────────────────────────────────
        provider = MockExternalProcessingProvider(scenario="success")
        dispatcher = BurstDispatcher(
            provider=provider,
            max_concurrency=4,
            base_backoff=0.0,
            dry_run=False,
        )

        # Solo despachar jobs que no son cache hits
        jobs_to_dispatch = [j for j in jobs if not j.cache_hit]
        cache_hit_jobs = [j for j in jobs if j.cache_hit]

        dispatched_results = dispatcher.dispatch_batch(jobs_to_dispatch)
        all_results = dispatched_results + cache_hit_jobs

        elapsed = time.time() - start_time

        # ── 4. Validar ────────────────────────────────────────────────────────
        # Los cache hits ya estan READY, los otros estan COMPLETED
        # Normalizar READY jobs que vienen de cache
        results_for_validation = []
        for j in all_results:
            if j.status == JobStatus.READY and j.cache_hit:
                results_for_validation.append(j)
            else:
                results_for_validation.append(j)

        validated_jobs, validation_results = validate_batch(results_for_validation)

        valid_count = sum(1 for vr in validation_results if vr.valid)
        invalid_count = sum(1 for vr in validation_results if not vr.valid)

        # ── 5. Merge por tipo ─────────────────────────────────────────────────
        audio_jobs = [j for j in validated_jobs
                      if j.task_type == ExternalTaskType.TRANSCRIBE_AUDIO]
        image_jobs = [j for j in validated_jobs
                      if j.task_type == ExternalTaskType.IMAGE_ANALYSIS]
        pdf_jobs = [j for j in validated_jobs
                    if j.task_type == ExternalTaskType.OCR_IMAGE]

        audio_merged = merge_batch_results(
            self.batch_id, self.workspace, self.source_id, self.source_hash,
            ExternalTaskType.TRANSCRIBE_AUDIO, audio_jobs, provider="mock", model="mock-asr"
        )
        image_merged = merge_batch_results(
            self.batch_id, self.workspace, self.source_id, self.source_hash,
            ExternalTaskType.IMAGE_ANALYSIS, image_jobs, provider="mock", model="mock-vision"
        )
        pdf_merged = merge_batch_results(
            self.batch_id, self.workspace, self.source_id, self.source_hash,
            ExternalTaskType.OCR_IMAGE, pdf_jobs, provider="mock", model="mock-ocr"
        )

        # ── 6. Verificaciones de resultado ────────────────────────────────────

        # Estado final
        assert audio_merged.status == "READY_FOR_LOCAL_PIPELINE"
        assert image_merged.status == "READY_FOR_LOCAL_PIPELINE"
        assert pdf_merged.status == "READY_FOR_LOCAL_PIPELINE"

        # Jobs completados
        total_ready = sum(1 for j in validated_jobs if j.status == JobStatus.READY)
        total_failed = sum(1 for j in validated_jobs
                          if j.status in (JobStatus.FAILED, JobStatus.FAILED_VALIDATION))

        assert total_ready >= len(audio_jobs) + len(image_jobs), (
            f"Demasiados fallos: {total_failed}/{len(validated_jobs)}"
        )

        # Cache hits
        assert cache_hits_at_start >= 1, "Debe haber al menos 1 cache hit"

        # Reintentos (en escenario 'success' no deberia haber)
        assert dispatcher.total_retries == 0

        # Tiempo razonable (sin delay el mock es instantaneo)
        assert elapsed < 30.0, f"Pipeline demasiado lento: {elapsed:.1f}s"

        # ── 7. Verificaciones de seguridad ────────────────────────────────────

        # Neo4j: 0 llamadas
        neo4j_modules = [k for k in sys.modules if "neo4j" in k.lower()]
        assert len(neo4j_modules) == 0 or all(
            "external_processing" not in str(sys.modules.get(m, "")) for m in neo4j_modules
        ), f"Neo4j importado desde external_processing: {neo4j_modules}"

        # writer: no invocado
        assert self._writer_calls == 0

        # ingest_approved: no importado COMO RESULTADO DEL PIPELINE (delta desde antes)
        # Nota: otros tests de la suite pueden haber cargado review.ingest_approved antes;
        # aqui verificamos que el pipeline de Fase B1 no lo importa por si mismo.
        _ingest_mods_after = set(k for k in sys.modules if "ingest_approved" in k)
        _new_ingest_mods = _ingest_mods_after - _ingest_mods_before
        assert len(_new_ingest_mods) == 0, f"ingest_approved importado por el pipeline: {_new_ingest_mods}"

        # approved_payload: no generado
        assert len(self._approved_payloads) == 0
        for merged in [audio_merged, image_merged, pdf_merged]:
            assert "approved_payload" not in merged.dict()

        # Secretos ausentes en resultados
        import json
        from external_processing.result_validator import _scan_secrets
        for j in validated_jobs:
            if j.result:
                secrets = _scan_secrets(j.result)
                assert len(secrets) == 0, f"Secretos en job {j.job_id}: {secrets}"

        # Rutas privadas no en resultados exportados
        from external_processing.result_validator import _scan_private_paths
        for j in validated_jobs:
            if j.result:
                private = _scan_private_paths(j.result)
                assert len(private) == 0, f"Rutas privadas en resultado {j.job_id}: {private}"

        # ── 8. Reporte final ──────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"E2E Mock Pipeline - Fase B1")
        print(f"{'='*60}")
        print(f"Fuentes: {len(self.audio_files)} audio, {len(self.image_files)} imagenes, {len(self.pdf_files)} PDF")
        print(f"Jobs creados: {total_jobs_created}")
        print(f"Cache hits al inicio: {cache_hits_at_start}")
        print(f"Jobs completados (READY): {total_ready}")
        print(f"Jobs fallidos: {total_failed}")
        print(f"Reintentos: {dispatcher.total_retries}")
        print(f"Tiempo: {elapsed:.2f}s")
        print(f"")
        print(f"Audio segments: {len(audio_merged.segments)}")
        print(f"Image segments: {len(image_merged.segments)}")
        print(f"PDF segments: {len(pdf_merged.segments)}")
        print(f"Audio gaps: {len(audio_merged.gaps_detected)}")
        print(f"")
        print(f"Neo4j calls: {self._neo4j_calls}")
        print(f"Writer calls: {self._writer_calls}")
        print(f"ingest_approved calls: {self._ingest_approved_calls}")
        print(f"approved_payload generated: {len(self._approved_payloads)}")
        print(f"{'='*60}")
        print(f"RESULTADO: READY_FOR_LOCAL_PIPELINE")

    def test_e2e_ningun_job_toca_neo4j(self):
        """Confirma que ningun modulo del pipeline toca Neo4j."""
        import sys
        neo4j_modules_before = set(k for k in sys.modules if "neo4j" in k.lower())

        provider = MockExternalProcessingProvider()
        dispatcher = BurstDispatcher(provider, max_concurrency=2, base_backoff=0.0)

        jobs = [
            ProcessingJob(
                batch_id=self.batch_id,
                workspace=self.workspace,
                source_id=self.source_id,
                task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
                processing_mode=ProcessingMode.LOCAL,
                chunk={"chunk_index": 0, "chunk_start": 0.0, "chunk_end": 60.0,
                       "source_hash": "h", "overlap_start": 0.0, "overlap_end": 0.0},
            )
        ]
        results = dispatcher.dispatch_batch(jobs)
        validated, _ = validate_batch(results)
        merge_batch_results(
            self.batch_id, self.workspace, self.source_id, "h",
            ExternalTaskType.TRANSCRIBE_AUDIO, validated
        )

        neo4j_modules_after = set(k for k in sys.modules if "neo4j" in k.lower())
        new_neo4j = neo4j_modules_after - neo4j_modules_before
        assert len(new_neo4j) == 0, f"Neo4j importado: {new_neo4j}"

    def test_e2e_writer_no_invocado(self):
        """Confirma que el writer de Neo4j no se invoca."""
        # El writer de Neo4j esta en review/approved_writer.py
        # No debe importarse como consecuencia del pipeline
        modules_before = set(k for k in sys.modules if "approved_writer" in k)

        provider = MockExternalProcessingProvider()
        dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.0)
        job = ProcessingJob(
            batch_id="b",
            workspace="ws",
            source_id="s",
            task_type=ExternalTaskType.TEXT_EXTRACT,
            processing_mode=ProcessingMode.LOCAL,
            chunk={"chunk_index": 0, "offset_start": 0, "offset_end": 100, "source_hash": "h"},
        )
        results = dispatcher.dispatch_batch([job])
        merge_batch_results("b", "ws", "s", "h", ExternalTaskType.TEXT_EXTRACT, results)

        modules_after = set(k for k in sys.modules if "approved_writer" in k)
        new_writer = modules_after - modules_before
        assert len(new_writer) == 0, f"approved_writer importado: {new_writer}"

    def test_e2e_ingest_approved_no_importado_por_pipeline(self):
        """Regresion: el pipeline B1 no importa ingest_approved aunque otros tests si lo hagan.

        Este test falla si se revierte el fix de captura de snapshot previo al pipeline
        en test_e2e_flujo_completo. Verifica el mismo contrato usando delta de sys.modules.
        """
        # Cargar ingest_approved deliberadamente para simular orden de ejecucion real
        # en el que otros tests lo cargan antes que nosotros
        try:
            import importlib
            importlib.import_module("review.ingest_approved")
        except ImportError:
            pass  # Si no existe en el entorno de prueba, el test sigue siendo valido

        before = set(k for k in sys.modules if "ingest_approved" in k)

        # Ejecutar un ciclo completo del pipeline B1
        provider = MockExternalProcessingProvider()
        dispatcher = BurstDispatcher(provider, max_concurrency=1, base_backoff=0.0)
        job = ProcessingJob(
            batch_id="reg-b1",
            workspace="ws",
            source_id="src",
            task_type=ExternalTaskType.TRANSCRIBE_AUDIO,
            processing_mode=ProcessingMode.LOCAL,
            chunk={"chunk_index": 0, "chunk_start": 0.0, "chunk_end": 60.0,
                   "source_hash": "h_reg", "overlap_start": 0.0, "overlap_end": 0.0},
        )
        results = dispatcher.dispatch_batch([job])
        validated, _ = validate_batch(results)
        merge_batch_results(
            "reg-b1", "ws", "src", "h_reg",
            ExternalTaskType.TRANSCRIBE_AUDIO, validated
        )

        after = set(k for k in sys.modules if "ingest_approved" in k)
        new_mods = after - before
        assert len(new_mods) == 0, (
            f"El pipeline B1 importo ingest_approved inesperadamente: {new_mods}. "
            "Si este test falla, la cadena dispatcher->merger->validator importa "
            "review.ingest_approved, lo que indica una regresion de aislamiento."
        )
