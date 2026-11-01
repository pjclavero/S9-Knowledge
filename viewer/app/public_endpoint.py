"""Autoridad ÚNICA del endpoint público del visor (H-05 corte B).

CADENA (una sola, de izquierda a derecha, sin atajos):

    S9K_PUBLIC_BASE_URL  ->  hostname canónico  ->  hosts de confianza

``interpretar_url_publica`` es la ÚNICA función del repositorio que interpreta
esa URL (esquema, hostname, placeholder, comodín, malformación) y
``resolve_trusted_hosts`` la ÚNICA que decide qué ``Host`` acepta el visor.
El middleware (``app.public_host_middleware``), el arranque (``app.main``) y
el preflight de despliegue (``deploy/scripts/preflight_https.py``, que carga
ESTE fichero por ruta porque corre fuera del venv) consumen estas funciones;
ninguno las reimplementa. Un gate AST
(``viewer/tests/test_h05b_trusted_host.py``) vigila que no aparezca una
segunda lectura de la variable ni un segundo ``urlsplit`` de la URL pública.

Este módulo es SÓLO biblioteca estándar a propósito (el preflight no puede
importar el visor). ``resolve_public_endpoint`` importa ``effective_env_value``
de forma perezosa: esa es la lectura de la variable (autoridad de
``app.config``), no una segunda.

DECISIONES DEL OPERADOR (contrato H-05B) que gobiernan este módulo:

* La URL pública efectiva es OBLIGATORIA. Falta -> ``PublicEndpointError``
  (el arranque aborta). No existe ningún camino "sin configuración, no
  comprobar el Host".
* Sin comodín (``*``), sin autodetección (IP LAN, Tailscale, hostname de la
  máquina, DNS, interfaces, subdominios): la lista es EXACTAMENTE el hostname
  declarado + ``localhost`` + ``127.0.0.1`` + ``::1``.
* El placeholder de la plantilla (``cambiar.por.el.nombre.real``) se rechaza
  aunque sea una URL sintácticamente válida.
* ``testserver`` NO está aquí. Sólo un entorno de tests lo declara, de forma
  explícita, por ``app.state.extra_trusted_hosts`` (ver el middleware); esta
  función no lo conoce.
* Hosts adicionales futuros = configuración de despliegue explícita (otro
  corte), no deducción.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple
from urllib.parse import urlsplit

__all__ = [
    "PUBLIC_BASE_URL_VAR",
    "PLACEHOLDER_HOST",
    "LOOPBACK_HOSTS",
    "EFECTIVO",
    "PublicEndpoint",
    "PublicEndpointError",
    "interpretar_url_publica",
    "normalizar_host",
    "normalizar_host_cabecera",
    "resolve_public_endpoint",
    "resolve_trusted_hosts",
]

#: Nombre de la ÚNICA variable de configuración de la URL pública.
PUBLIC_BASE_URL_VAR = "S9K_PUBLIC_BASE_URL"

#: Hostname de la plantilla `deploy/config/viewer.env.example`: nunca es una
#: instalación real.
PLACEHOLDER_HOST = "cambiar.por.el.nombre.real"

#: Hosts de loopback siempre permitidos (health runner, verify-deployment.sh,
#: lib.sh, preflight local). No abren la LAN.
LOOPBACK_HOSTS: Tuple[str, ...] = ("localhost", "127.0.0.1", "::1")

_ESQUEMAS = ("http", "https")
_ETIQUETA_DNS = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_PUERTO = re.compile(r"^[0-9]{1,5}$")
_PROHIBIDOS_EN_HOST = re.compile(r"[\s\x00-\x1f\x7f/\\@,?#]")
_BLANCOS_O_CONTROL = re.compile(r"[\s\x00-\x1f\x7f]")

#: Centinela: "léelo de la configuración efectiva". ``None`` explícito NO es
#: esto: es "ausente" y falla (AUSENCIA != CERO).
EFECTIVO: Any = object()


class PublicEndpointError(ValueError):
    """La URL pública no es utilizable: el arranque debe abortar.

    ``code`` es estable (las pruebas comprueban el código, no la redacción).
    """

    def __init__(self, code: str, message: str):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PublicEndpoint:
    base_url: str
    scheme: str
    hostname: str  # canónico: minúsculas, sin punto final, IPv6 sin corchetes
    port: Optional[int]


def normalizar_host(host: str) -> Optional[str]:
    """Hostname canónico, o ``None`` si no es un host válido.

    Minúsculas, un único punto final eliminado, IP literal en forma canónica
    (``ipaddress``; IPv6 sin corchetes). Un comodín, un espacio, una etiqueta
    DNS inválida o un valor vacío -> ``None``. No consulta DNS ni la máquina.
    """
    if not isinstance(host, str) or not host or _PROHIBIDOS_EN_HOST.search(host):
        return None
    candidato = host.casefold()
    if candidato.endswith("."):
        candidato = candidato[:-1]
    if not candidato:
        return None
    try:
        return ipaddress.ip_address(candidato).compressed
    except ValueError:
        pass
    if len(candidato) > 253:
        return None
    if not all(_ETIQUETA_DNS.match(e) for e in candidato.split(".")):
        return None
    return candidato


def normalizar_host_cabecera(valor: Optional[str]) -> Optional[str]:
    """Hostname de una cabecera ``Host`` (sin puerto), o ``None`` si es inválida.

    Gestiona lo que ``TrustedHostMiddleware`` de Starlette no hace (medido por
    ejecución en Starlette 1.3.1: ``split(":")[0]`` convierte ``[::1]:8000`` en
    ``[``, distingue mayúsculas y no tolera el punto final): IPv6 entre
    corchetes con o sin puerto, casing, punto final. Cualquier forma ambigua
    (varios ``:`` sin corchetes, puerto no numérico, espacios, ``@``, ``/``)
    es inválida: fail-closed.
    """
    if not valor:
        return None
    if valor.startswith("["):
        cierre = valor.find("]")
        if cierre < 0:
            return None
        dentro, resto = valor[1:cierre], valor[cierre + 1:]
        if resto and not (resto.startswith(":") and _PUERTO.match(resto[1:])):
            return None
        try:
            ip = ipaddress.ip_address(dentro)
        except ValueError:
            return None
        if ip.version != 6:
            return None
        return ip.compressed
    if valor.count(":") > 1:
        return None
    nombre = valor
    if ":" in valor:
        nombre, puerto = valor.split(":", 1)
        if not _PUERTO.match(puerto):
            return None
    return normalizar_host(nombre)


def interpretar_url_publica(raw: Optional[str]) -> PublicEndpoint:
    """ÚNICA interpretación de la URL pública. Lanza ``PublicEndpointError``.

    Códigos: ``PUBLIC_URL_MISSING``, ``PUBLIC_URL_MALFORMED``,
    ``PUBLIC_URL_SCHEME``, ``PUBLIC_URL_NO_HOSTNAME``,
    ``PUBLIC_URL_WILDCARD``, ``PUBLIC_URL_PLACEHOLDER``,
    ``PUBLIC_URL_INVALID_HOSTNAME``.
    """
    if raw is None or not raw.strip():
        raise PublicEndpointError(
            "PUBLIC_URL_MISSING",
            "%s no está declarada. La URL pública es obligatoria: sin ella el "
            "visor no sabe qué Host aceptar y NO se desactiva la comprobación."
            % PUBLIC_BASE_URL_VAR)
    if _BLANCOS_O_CONTROL.search(raw):
        raise PublicEndpointError(
            "PUBLIC_URL_MALFORMED",
            "%s contiene espacios o caracteres de control." % PUBLIC_BASE_URL_VAR)
    if "*" in raw:
        raise PublicEndpointError(
            "PUBLIC_URL_WILDCARD",
            "%s contiene un comodín: no se acepta ningún '*'." % PUBLIC_BASE_URL_VAR)
    try:
        partes = urlsplit(raw)
        puerto = partes.port
        hostname = partes.hostname
    except ValueError:
        raise PublicEndpointError(
            "PUBLIC_URL_MALFORMED",
            "%s no es una URL válida." % PUBLIC_BASE_URL_VAR) from None
    if partes.scheme.lower() not in _ESQUEMAS:
        raise PublicEndpointError(
            "PUBLIC_URL_SCHEME",
            "esquema %r no permitido (sólo http/https)." % (partes.scheme,))
    if (partes.username is not None or partes.password is not None
            or partes.query or partes.fragment):
        raise PublicEndpointError(
            "PUBLIC_URL_MALFORMED",
            "%s no admite credenciales, query ni fragmento." % PUBLIC_BASE_URL_VAR)
    if not hostname:
        raise PublicEndpointError(
            "PUBLIC_URL_NO_HOSTNAME",
            "%s no tiene hostname." % PUBLIC_BASE_URL_VAR)
    canonico = normalizar_host(hostname)
    if canonico is None:
        raise PublicEndpointError(
            "PUBLIC_URL_INVALID_HOSTNAME",
            "el hostname de %s no es válido." % PUBLIC_BASE_URL_VAR)
    if canonico == PLACEHOLDER_HOST:
        raise PublicEndpointError(
            "PUBLIC_URL_PLACEHOLDER",
            "%s conserva el placeholder de la plantilla (%s): hay que declarar "
            "el nombre real de la instalación." % (PUBLIC_BASE_URL_VAR, PLACEHOLDER_HOST))
    return PublicEndpoint(base_url=raw, scheme=partes.scheme.lower(),
                          hostname=canonico, port=puerto)


def resolve_public_endpoint(raw: Optional[str] = EFECTIVO) -> PublicEndpoint:
    """Endpoint público EFECTIVO. Sin ``raw``, lee la variable por la
    autoridad de configuración (``effective_env_value``: entorno y luego
    ``.env``)."""
    if raw is EFECTIVO:
        from app.config import effective_env_value  # perezoso: módulo sólo stdlib
        raw = effective_env_value(PUBLIC_BASE_URL_VAR)
    return interpretar_url_publica(raw)


def resolve_trusted_hosts(raw: Optional[str] = EFECTIVO,
                          extra: Iterable[str] = ()) -> Tuple[str, ...]:
    """Hosts aceptados: hostname público + loopback (+ ``extra`` explícito).

    ``extra`` es la costura de TESTS (``app.state.extra_trusted_hosts``): el
    código de producción nunca lo pasa. Cada extra se normaliza y valida con
    las mismas reglas (sin comodín); uno inválido aborta, no se descarta.
    """
    endpoint = resolve_public_endpoint(raw)
    lista = [endpoint.hostname, *LOOPBACK_HOSTS]
    for candidato in extra:
        canonico = normalizar_host(candidato)
        if canonico is None:
            raise PublicEndpointError(
                "TRUSTED_HOST_INVALID",
                "host adicional inválido: %r." % (candidato,))
        lista.append(canonico)
    return tuple(dict.fromkeys(lista))
