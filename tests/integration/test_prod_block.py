"""test_prod_block.py — demuestra que el cortafuegos de producción funciona.

RESTRICCIÓN DURA de RC6 ETAPA 2: la suite debe FALLAR si algún test intenta
conectar a producción. Aquí probamos que cualquier intento de conexión a los
hosts/IP vetados lanza `ProductionAccessBlocked` (lo que aborta el test), y que
el tráfico a destinos NO productivos no se ve afectado.

El bloqueo se activa en `tests/conftest.py` (prod_block.install()) para toda la
sesión, incluidos los E2E con navegador.
"""
from __future__ import annotations

import socket

import pytest

from support.prod_block import (
    FORBIDDEN_HOSTS,
    ProductionAccessBlocked,
    _is_forbidden,
)

pytestmark = pytest.mark.prod_block

FORBIDDEN = [
    "knowledge.seccionnueve.duckdns.org",
    "192.168.1.205",
    "100.103.100.105",
]


def test_block_is_active(prod_block_active: bool) -> None:
    assert prod_block_active is True


@pytest.mark.parametrize("host", FORBIDDEN)
def test_getaddrinfo_to_prod_is_blocked(host: str) -> None:
    with pytest.raises(ProductionAccessBlocked):
        socket.getaddrinfo(host, 443)


@pytest.mark.parametrize("host", FORBIDDEN)
def test_socket_connect_to_prod_is_blocked(host: str) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(ProductionAccessBlocked):
            s.connect((host, 443))
    finally:
        s.close()


@pytest.mark.parametrize("host", FORBIDDEN)
def test_create_connection_to_prod_is_blocked(host: str) -> None:
    with pytest.raises(ProductionAccessBlocked):
        socket.create_connection((host, 443), timeout=0.1)


def test_http_client_to_prod_is_blocked() -> None:
    """Un cliente HTTP real (urllib) también queda bloqueado por la capa socket."""
    import urllib.error
    import urllib.request

    with pytest.raises((ProductionAccessBlocked, urllib.error.URLError)) as exc:
        urllib.request.urlopen("https://knowledge.seccionnueve.duckdns.org/", timeout=0.1)
    # Si fue URLError, la causa raíz debe ser el bloqueo, no un fallo de red real.
    err = exc.value
    if not isinstance(err, ProductionAccessBlocked):
        assert isinstance(err.__cause__ or err.reason, ProductionAccessBlocked) or \
            "BLOQUEO DE PRODUCCIÓN" in str(err)


def test_loopback_is_not_blocked() -> None:
    """El cortafuegos NO debe interferir con servidores locales de laboratorio."""
    assert socket.getaddrinfo("127.0.0.1", 80) is not None
    assert not _is_forbidden("127.0.0.1")
    assert not _is_forbidden("localhost")


def test_forbidden_set_matches_contract() -> None:
    assert set(FORBIDDEN) == set(FORBIDDEN_HOSTS)
