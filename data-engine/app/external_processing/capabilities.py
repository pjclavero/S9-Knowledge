# -*- coding: utf-8 -*-
"""Capacidades del subsistema de procesamiento externo (Fase B1).

Separadas de external_ai/ para mantener contratos independientes.
"""
from __future__ import annotations
from enum import Enum


class Capability(str, Enum):
    TRANSCRIBE_AUDIO = "transcribe_audio"
    OCR_IMAGE = "ocr_image"
    OCR_PDF_PAGE = "ocr_pdf_page"
    DESCRIBE_IMAGE = "describe_image"
    EXTRACT_TEXT_ENTITIES = "extract_text_entities"
    GENERATE_EMBEDDINGS = "generate_embeddings"
    RERANK = "rerank"
    REVIEW_CANDIDATES = "review_candidates"


# Capacidades que el proveedor NVIDIA tiene verificadas
NVIDIA_VERIFIED_CAPABILITIES: set[Capability] = {
    Capability.EXTRACT_TEXT_ENTITIES,
    Capability.GENERATE_EMBEDDINGS,
    Capability.RERANK,
    Capability.REVIEW_CANDIDATES,
}

# Capacidades disponibles solo en modo local (faster-whisper, tesseract, etc.)
LOCAL_ONLY_CAPABILITIES: set[Capability] = {
    Capability.TRANSCRIBE_AUDIO,
    Capability.OCR_IMAGE,
    Capability.OCR_PDF_PAGE,
    Capability.DESCRIBE_IMAGE,
}
