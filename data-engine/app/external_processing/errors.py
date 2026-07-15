# -*- coding: utf-8 -*-
"""Errores del subsistema de procesamiento externo (Fase B1).

Los codigos de error son string enums para que puedan persistirse en la DB
y mostrarse en el panel de jobs sin dependencia de clases Python.
"""
from __future__ import annotations
from enum import Enum


class ErrorCode(str, Enum):
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    CONTENT_BLOCKED = "CONTENT_BLOCKED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CHUNK_ERROR = "CHUNK_ERROR"
    CACHE_ERROR = "CACHE_ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    CANCELLED = "CANCELLED"


# Errores que NO se reintentan (permanentes)
NON_RETRYABLE_ERRORS: set[ErrorCode] = {
    ErrorCode.AUTH_ERROR,
    ErrorCode.UNSUPPORTED_CAPABILITY,
    ErrorCode.INPUT_TOO_LARGE,
    ErrorCode.CONTENT_BLOCKED,
}


class ExternalProcessingError(Exception):
    """Base para todos los errores del subsistema de procesamiento externo."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.INVALID_RESPONSE):
        super().__init__(message)
        self.code = code


class AuthError(ExternalProcessingError):
    def __init__(self, message: str = "Autenticacion fallida"):
        super().__init__(message, ErrorCode.AUTH_ERROR)


class RateLimitError(ExternalProcessingError):
    def __init__(self, message: str = "Rate limit alcanzado", retry_after: float = 0.0):
        super().__init__(message, ErrorCode.RATE_LIMIT)
        self.retry_after = retry_after


class TimeoutError(ExternalProcessingError):
    def __init__(self, message: str = "Timeout en procesamiento externo"):
        super().__init__(message, ErrorCode.TIMEOUT)


class ProviderUnavailableError(ExternalProcessingError):
    def __init__(self, message: str = "Proveedor no disponible"):
        super().__init__(message, ErrorCode.PROVIDER_UNAVAILABLE)


class InvalidResponseError(ExternalProcessingError):
    def __init__(self, message: str = "Respuesta invalida del proveedor"):
        super().__init__(message, ErrorCode.INVALID_RESPONSE)


class UnsupportedCapabilityError(ExternalProcessingError):
    def __init__(self, capability: str = "", provider: str = ""):
        msg = f"Capacidad no soportada: {capability} en proveedor {provider}"
        super().__init__(msg, ErrorCode.UNSUPPORTED_CAPABILITY)
        self.capability = capability
        self.provider_name = provider


class InputTooLargeError(ExternalProcessingError):
    def __init__(self, message: str = "Input demasiado grande"):
        super().__init__(message, ErrorCode.INPUT_TOO_LARGE)


class ContentBlockedError(ExternalProcessingError):
    def __init__(self, message: str = "Contenido bloqueado por politica"):
        super().__init__(message, ErrorCode.CONTENT_BLOCKED)


class ValidationError(ExternalProcessingError):
    def __init__(self, message: str, field: str = ""):
        super().__init__(message, ErrorCode.VALIDATION_ERROR)
        self.field = field


class CircuitOpenError(ExternalProcessingError):
    def __init__(self, provider: str = ""):
        super().__init__(f"Circuit breaker abierto para proveedor: {provider}", ErrorCode.CIRCUIT_OPEN)


class CancelledError(ExternalProcessingError):
    def __init__(self):
        super().__init__("Job cancelado", ErrorCode.CANCELLED)
