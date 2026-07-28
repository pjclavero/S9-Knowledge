# -*- coding: utf-8 -*-
"""Transporte HTTP endurecido para proveedores externos.

Existe por tres fallos DEMOSTRADOS en vivo contra la version anterior de
`providers/nvidia.py` y `providers/ollama.py`:

**1. Fuga de credenciales por redirect (ALTA).**
`urllib.request.urlopen` sigue los 3xx automaticamente y **conserva la cabecera
`Authorization` al cambiar de host**. Un servidor que responda `302` apuntando a
otro dominio recibe la API key en claro. El mismo agujero permite inyeccion de
respuesta (el atacante elige el cuerpo que parsearemos) y SSRF hacia la LAN
(`http://192.168.1.x`, `http://169.254.169.254/...`).

La postura aqui es **rechazar todo redirect**, no "limpiar la cabecera y
seguir": un endpoint de API que redirige no es un endpoint de API que
conozcamos, y seguirlo a ciegas no aporta nada que compense el riesgo. Si algun
dia NVIDIA mueve su endpoint, se cambia la configuracion, que para eso existe.

**2. Sin deadline de pared (MEDIA).**
`timeout` de `urlopen` es por operacion de socket, no total. Un servidor que
gotea un byte cada 0,2 s mantiene viva la llamada indefinidamente con
`timeout=3`: cada lectura individual llega a tiempo. `read_bounded()` impone un
plazo de pared que se comprueba en cada vuelta del bucle.

**3. Lectura no acotada (MEDIA).**
Leer y despues mirar el tamano ya es tarde: el proceso cargo la respuesta
entera en memoria. `read_bounded()` lee a trozos y aborta en cuanto se pasa del
tope, sin llegar a materializar la respuesta completa.

Este modulo no conoce proveedores, ni claves, ni contratos. Solo transporte.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Optional

from external_processing.errors import (
    InputTooLargeError,
    ProviderUnavailableError,
    TimeoutError,
)

#: Tope de espera que aceptamos de un `Retry-After`. Un proveedor puede pedir
#: lo que quiera; nosotros no bloqueamos un hilo (con su semaforo y su
#: presupuesto retenidos) mas alla de esto.
MAX_RETRY_AFTER_SECONDS = 60.0

#: Tamano de trozo de lectura. Suficientemente grande para no penalizar y
#: suficientemente pequeno para que el deadline se compruebe a menudo.
READ_CHUNK_BYTES = 64 * 1024


class RedirectRejectedError(ProviderUnavailableError):
    """El servidor intento redirigirnos. No se sigue: la key no viaja."""

    def __init__(self, code: int, location: str = "") -> None:
        # `location` NO se interpola completo a proposito: podria llevar
        # credenciales en el userinfo de la URL.
        host = ""
        if location:
            try:
                from urllib.parse import urlparse

                host = urlparse(location).hostname or ""
            except Exception:  # noqa: BLE001
                host = "<ilegible>"
        super().__init__(
            f"redirect HTTP {code} rechazado"
            + (f" (destino: {host})" if host else "")
            + ": seguirlo enviaria la cabecera Authorization a otro host"
        )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Convierte cualquier 3xx en un error en vez de seguirlo."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise RedirectRejectedError(code, newurl)


def build_safe_opener() -> urllib.request.OpenerDirector:
    """Opener que NO sigue redirects.

    `build_opener` sustituye el handler por defecto cuando se le pasa una
    subclase suya, de modo que el `HTTPRedirectHandler` estandar queda fuera.
    """
    return urllib.request.build_opener(_NoRedirectHandler)


#: Opener compartido. Sin estado propio: es seguro reutilizarlo entre hilos.
_SAFE_OPENER = build_safe_opener()


def safe_urlopen(req, timeout=None):
    """`urlopen` que rechaza redirects. Firma identica a la estandar."""
    return _SAFE_OPENER.open(req, timeout=timeout)


def read_bounded(
    resp,
    max_bytes: int,
    *,
    deadline: Optional[float] = None,
    what: str = "respuesta",
) -> bytes:
    """Lee como mucho `max_bytes` y como mucho hasta `deadline`.

    `deadline` es un instante de `time.monotonic()`, no una duracion.

    Lanza `InputTooLargeError` en cuanto se supera el tope —sin materializar el
    resto— y `TimeoutError` si se agota el plazo de pared a mitad de lectura.
    """
    chunks: list = []
    total = 0
    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError(
                f"plazo total agotado leyendo la {what} ({total} bytes recibidos): "
                "un servidor que gotea no puede retener el hilo indefinidamente"
            )
        # Nunca se pide mas de lo que falta para pasarse del tope: asi el
        # exceso se detecta con un byte, no con la respuesta entera.
        want = min(READ_CHUNK_BYTES, max_bytes + 1 - total)
        if want <= 0:
            break
        chunk = resp.read(want)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise InputTooLargeError(
                f"{what} por encima del tope ({max_bytes} bytes); "
                "descartada sin leerla entera"
            )
    return b"".join(chunks)


def cap_retry_after(value, *, maximum: float = MAX_RETRY_AFTER_SECONDS) -> float:
    """Normaliza un `Retry-After` a un numero de segundos razonable.

    Un `Retry-After: 99999999` bloqueaba un hilo del dispatcher durante anos,
    con su semaforo y su reserva de presupuesto retenidos.
    """
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if seconds != seconds or seconds in (float("inf"), float("-inf")):  # NaN / inf
        return 0.0
    return max(0.0, min(seconds, maximum))
