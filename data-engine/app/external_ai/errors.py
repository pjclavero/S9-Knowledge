# -*- coding: utf-8 -*-
"""Errores del subsistema de IA externa (Fase A: revisión en modo sombra).

Ninguna excepción debe silenciarse. Los errores de red/HTTP se mapean a tipos
específicos para que el motor de consenso y los reintentos decidan con precisión.
"""
from __future__ import annotations


class ExternalAIError(Exception):
    """Base de todos los errores del subsistema de IA externa."""


class ConfigError(ExternalAIError):
    """Configuración inválida o ausente (p. ej. base_url o API key faltante)."""


class ShadowModeRequired(ExternalAIError):
    """Se intentó una operación externa sin --shadow / shadow_mode=True."""


class ProviderAuthError(ExternalAIError):
    """HTTP 401/403: credenciales inválidas o sin permiso. NO se reintenta."""


class ProviderNotFoundError(ExternalAIError):
    """HTTP 404: modelo o endpoint inexistente. NO se reintenta."""


class RateLimitError(ExternalAIError):
    """HTTP 429: límite de tasa. Se reintenta con backoff."""


class ProviderServerError(ExternalAIError):
    """HTTP 5xx: error del proveedor. Se reintenta con backoff."""


class ProviderTimeoutError(ExternalAIError):
    """Timeout de red. Se reintenta con backoff."""


class InvalidResponseError(ExternalAIError):
    """La respuesta del modelo no es JSON válido, está incompleta o no valida."""


class SecretLeakError(ExternalAIError):
    """El detector de secretos encontró credenciales en el payload a enviar.

    Se lanza ANTES de cualquier llamada de red para bloquear la fuga.
    """


def classify_http_status(status: int, body: str = "") -> ExternalAIError:
    """Mapea un código HTTP a la excepción específica (sin filtrar secretos)."""
    body = (body or "")[:200]
    if status in (401, 403):
        return ProviderAuthError(f"HTTP {status}: autenticación/permiso rechazado")
    if status == 404:
        return ProviderNotFoundError(f"HTTP {status}: modelo o endpoint no encontrado")
    if status == 429:
        return RateLimitError(f"HTTP {status}: rate limit")
    if 500 <= status < 600:
        return ProviderServerError(f"HTTP {status}: error del proveedor")
    return ExternalAIError(f"HTTP {status}: respuesta inesperada")
