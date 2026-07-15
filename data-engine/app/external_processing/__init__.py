# -*- coding: utf-8 -*-
"""external_processing — Orquestador de procesamiento externo por rafaga (Fase B1).

Responsabilidades:
  - Planificacion de modo: local / hybrid / burst
  - Chunking de audio, PDF, imagenes y texto
  - Despacho con concurrencia limitada, retry y circuit breaker
  - Validacion y fusion de resultados
  - Cache idempotente por SHA256
  - Proveedor mock determinista (tests sin APIs reales)
  - Adaptador NVIDIA (capacidades verificadas)

NO gestiona: candidate_review, adjudication, consensus, calibration
(eso es responsabilidad de external_ai/).

NO escribe en Neo4j.
NO llama a ingest_approved.
NO genera approved_payload.
"""
__version__ = "0.1.0"
