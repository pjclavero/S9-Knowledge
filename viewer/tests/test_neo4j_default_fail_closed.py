"""RK-05: el default de conexión a Neo4j del visor debe fallar de forma cerrada.

El default NUNCA debe ser una IP/host productivo. Debe ser loopback (o vacío),
de modo que arrancar el visor con el provider neo4j sin configurar no apunte
jamás a producción. Estos tests SOLO inspeccionan la configuración: no abren
ninguna conexión de red.
"""
from urllib.parse import urlparse

from app.config import Settings

# Hosts/IPs de producción que el default NUNCA debe contener.
PRODUCTION_HOSTS = ("192.168.1.205", "100.103.100.105", "duckdns")

# Hosts de loopback aceptables como default fail-closed.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _default_uri() -> str:
    # _env_file=None evita cargar .env; sin S9K_NEO4J_URI en entorno se usa el default.
    return Settings(_env_file=None).S9K_NEO4J_URI


def test_neo4j_default_is_not_a_production_host():
    uri = _default_uri()
    for host in PRODUCTION_HOSTS:
        assert host not in uri, (
            f"El default de S9K_NEO4J_URI no debe contener el host productivo {host!r}; "
            f"valor actual: {uri!r}"
        )


def test_neo4j_default_is_loopback_or_empty():
    uri = _default_uri()
    if uri == "":
        # Default vacío: fail-closed por configuración explícita obligatoria.
        return
    host = urlparse(uri).hostname or ""
    assert host in LOOPBACK_HOSTS, (
        f"El default de S9K_NEO4J_URI debe ser loopback (o vacío) para fallar de forma "
        f"cerrada; host resuelto: {host!r} (uri {uri!r})"
    )
