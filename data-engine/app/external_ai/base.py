# -*- coding: utf-8 -*-
"""Interfaz base de proveedores de IA externa (Fase A).

Diseñada para ampliarse en la Fase B (transcribe_audio, process_image, perform_ocr,
extract_candidates), que NO se implementan ahora. Las capacidades son declarativas.
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from external_ai.models import ProviderHealth, ReviewBatchRequest, ModelReviewResponse

# Capacidades declarativas (Fase A).
CAP_CANDIDATE_REVIEW = "candidate_review"
CAP_CANDIDATE_ADJUDICATION = "candidate_adjudication"
# Fase B (diseñadas, no implementadas):
CAP_TRANSCRIBE = "transcribe_audio"
CAP_IMAGE = "process_image"
CAP_OCR = "perform_ocr"
CAP_EXTRACT = "extract_candidates"


class ExternalAIProvider(ABC):
    """Contrato de un proveedor externo OpenAI-compatible en modo sombra."""

    provider_name: str = "base"
    capabilities: set = {CAP_CANDIDATE_REVIEW, CAP_CANDIDATE_ADJUDICATION}

    @abstractmethod
    def healthcheck(self) -> ProviderHealth:
        """Comprueba conectividad y modelos disponibles. No lanza; devuelve ProviderHealth."""
        raise NotImplementedError

    @abstractmethod
    def review_candidates(self, request: ReviewBatchRequest, model: str,
                          reviewer_role: str = "reviewer_a") -> ModelReviewResponse:
        """Envía un lote a un modelo y devuelve su revisión validada."""
        raise NotImplementedError

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    # --- Fase B: diseñadas, no implementadas (lanzan NotImplementedError explícito) ---
    def transcribe_audio(self, *a, **k):
        raise NotImplementedError("Fase B: transcribe_audio no implementado")

    def process_image(self, *a, **k):
        raise NotImplementedError("Fase B: process_image no implementado")

    def perform_ocr(self, *a, **k):
        raise NotImplementedError("Fase B: perform_ocr no implementado")

    def extract_candidates(self, *a, **k):
        raise NotImplementedError("Fase B: extract_candidates no implementado")
