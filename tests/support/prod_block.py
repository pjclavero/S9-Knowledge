"""prod_block.py — Cortafuegos de red para la suite E2E/integración del EQUIPO D.

Objetivo (RESTRICCIÓN DURA de RC6 ETAPA 2): ningún test puede tocar producción.
Este módulo parchea la capa `socket` para que CUALQUIER intento de conectar a los
hosts/IP de producción de S9 Knowledge lance `ProductionAccessBlocked`, abortando
el test (y, por tanto, la suite) en lugar de alcanzar la infraestructura real.

Hosts/IP prohibidos:
  - knowledge.seccionnueve.duckdns.org  (dominio público del visor productivo)
  - 192.168.1.205                       (IP LAN de la VM productiva)
  - 100.103.100.105                     (IP Tailscale de la VM productiva)

Cobertura: se interceptan `socket.getaddrinfo`, `socket.create_connection` y
`socket.socket.connect/connect_ex`. Como `requests`, `httpx`, `urllib`, drivers
de Neo4j, etc. terminan resolviendo/conectando por estas rutas, el bloqueo aplica
con independencia del cliente HTTP usado. El tráfico a loopback y a cualquier otro
host (servidores locales de laboratorio, SQLite temporal) no se ve afectado.

No tiene efectos secundarios más allá del parcheo (idempotente).
"""
from __future__ import annotations

import socket

# Conjunto canónico de destinos vetados. Se comparan como strings normalizados.
FORBIDDEN_HOSTS: frozenset[str] = frozenset({
    "knowledge.seccionnueve.duckdns.org",
    "192.168.1.205",
    "100.103.100.105",
})


class ProductionAccessBlocked(RuntimeError):
    """Se intentó abrir una conexión a un host/IP de producción desde los tests."""


def _is_forbidden(host: object) -> bool:
    if host is None:
        return False
    h = str(host).strip().strip("[]").lower()
    return h in {f.lower() for f in FORBIDDEN_HOSTS}


def _guard(host: object, *, via: str) -> None:
    if _is_forbidden(host):
        raise ProductionAccessBlocked(
            f"BLOQUEO DE PRODUCCIÓN: intento de conexión a {host!r} vía {via}. "
            "Los tests del EQUIPO D no pueden tocar producción "
            "(usa SQLite temporal, dobles, fixtures anonimizadas o servidores locales)."
        )


# Referencias a los originales para poder restaurar y para delegar.
_orig_getaddrinfo = socket.getaddrinfo
_orig_create_connection = socket.create_connection
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex

_INSTALLED = False


def _patched_getaddrinfo(host, *args, **kwargs):
    _guard(host, via="socket.getaddrinfo")
    return _orig_getaddrinfo(host, *args, **kwargs)


def _patched_create_connection(address, *args, **kwargs):
    if isinstance(address, (tuple, list)) and address:
        _guard(address[0], via="socket.create_connection")
    return _orig_create_connection(address, *args, **kwargs)


def _patched_connect(self, address):
    if isinstance(address, (tuple, list)) and address:
        _guard(address[0], via="socket.socket.connect")
    return _orig_connect(self, address)


def _patched_connect_ex(self, address):
    if isinstance(address, (tuple, list)) and address:
        _guard(address[0], via="socket.socket.connect_ex")
    return _orig_connect_ex(self, address)


def install() -> None:
    """Activa el cortafuegos. Idempotente."""
    global _INSTALLED
    if _INSTALLED:
        return
    socket.getaddrinfo = _patched_getaddrinfo
    socket.create_connection = _patched_create_connection
    socket.socket.connect = _patched_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _patched_connect_ex  # type: ignore[method-assign]
    _INSTALLED = True


def uninstall() -> None:
    """Restaura los originales (para autotests del propio cortafuegos)."""
    global _INSTALLED
    socket.getaddrinfo = _orig_getaddrinfo
    socket.create_connection = _orig_create_connection
    socket.socket.connect = _orig_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _orig_connect_ex  # type: ignore[method-assign]
    _INSTALLED = False
