# -*- coding: utf-8 -*-
"""Preflight de la VIA HTTPS de la instalacion. Solo lectura, por EFECTO.

POR QUE EXISTE
--------------
Medido en el PR-3 del programa USABLE-V1: con la plantilla literal,
``S9K_SESSION_SECURE=true`` hace que la cookie CSRF de ``/setup/admin`` salga
con atributo ``Secure``. Sobre ``http://`` ningun cliente la devuelve y el
``POST`` entra en bucle de 403. Doble control positivo: reinyectando la cookie
a mano -> 303 correcto; con ``SESSION_SECURE=false`` -> bootstrap completo.
Consecuencia: una instalacion de fabrica sobre HTTP plano NO puede crear su
primer administrador.

DECISION DEL OPERADOR (D3) que gobierna este modulo:

  * ``S9K_SESSION_SECURE=true`` SIGUE siendo el default seguro. Aqui no se
    degrada nada: este modulo no escribe configuracion.
  * Esta PROHIBIDO usar el esquema de la peticion para degradar la cookie, y
    esta prohibido cualquier fallback a HTTP para "hacer pasar" la
    instalacion. Por eso lo que este modulo hace con HTTP plano es
    RECHAZARLO, no adaptarse a el.
  * TLS es responsabilidad del PROCESO DE INSTALACION. Una instalacion
    productiva no se considera completada hasta que entrega una URL HTTPS
    funcional. De ahi el codigo de salida: cualquier hallazgo => rc != 0 =>
    instalacion NO completa.

CONTRATO DE LA VIA HTTPS SOPORTADA (lo que este preflight exige)
-----------------------------------------------------------------
1. La instalacion DECLARA su URL publica en ``S9K_PUBLIC_BASE_URL``
   (``viewer.env``). Sin declaracion no hay nada que verificar y eso es un
   fallo, no un "no aplica": AUSENCIA != CERO.
2. El esquema de esa URL es ``https``.
3. El certificado que se presenta en esa URL verifica CONTRA UN ALMACEN DE
   CONFIANZA DECLARADO: el del sistema, o el fichero de ``S9K_TLS_CA_FILE``
   si la instalacion usa una CA propia / un certificado autofirmado. NUNCA se
   desactiva la verificacion: un autofirmado se acepta declarandolo, no
   ignorando la comprobacion.
4. El NOMBRE de la URL publica coincide con el certificado (SNI + hostname
   check del modulo ``ssl``).
5. El endpoint RESPONDE: se hace un ``GET`` real sobre esa conexion TLS y se
   exige un codigo de estado HTTP. Que la configuracion este escrita no
   cuenta; cuenta que conteste.

AUTORIDAD QUE SE EXTIENDE (no se duplica)
-----------------------------------------
* ``deploy/scripts/validate_deploy.sh`` es la autoridad ESTATICA de
  ``viewer.env`` (presencia y coherencia de variables criticas). Este modulo
  no la reimplementa: alli se anade ``validate_https_contract``, y aqui vive
  solo la mitad que ``bash`` no puede hacer -abrir el socket TLS-.
  ``deploy/tests/test_preflight_https.py::test_el_lector_de_env_coincide_con_validate_deploy_sh``
  CRUZA el lector de este modulo contra ``validate_deploy.sh::_env_value``
  sobre lineas dificiles, para que las dos mitades no se separen en silencio.
* El criterio de "el visor contesto" NO se inventa: es el de
  ``viewer/app/health/checks.py::check_viewer`` -200 (auth off) o 401 (auth
  on)-, replicado aqui en ``ESTADOS_QUE_SIGNIFICAN_QUE_CONTESTO`` porque este
  guion corre FUERA del venv del visor (solo biblioteca estandar, como
  ``preflight_ensayo_rc.py``) y no puede importarlo.

POR QUE NO SE USA ``viewer/app/config.py::effective_env_value``
----------------------------------------------------------------
Esa es la autoridad del PROCESO DEL VISOR en ejecucion: ``os.environ`` y
luego el ``.env`` del directorio de trabajo. Este preflight corre en el host,
ANTES de que el visor arranque y desde otro directorio: lo que gobernara al
visor en produccion es el ``EnvironmentFile=/etc/s9-knowledge/viewer.env`` de
systemd, no el entorno de este proceso. Leer ``os.environ`` aqui mediria el
entorno equivocado. Por eso se lee el FICHERO, con la misma semantica que
``validate_deploy.sh``, y el cruce de arriba lo mantiene honesto.

LO QUE ESTE MODULO **NO** DEMUESTRA
------------------------------------
Que la instalacion entrega HTTPS. Demuestra que, EN EL MOMENTO EN QUE SE
EJECUTA Y CONTRA LA URL QUE SE LE DA, hay un endpoint TLS que verifica y
contesta. El recorrido completo (VM limpia -> instalar -> crear primer admin
-> reinicio -> sigue funcionando) es el ENSAYO RC, cuyo guion esta escrito en
``deploy/README.md`` y que a fecha de este PR NO se ha ejecutado.

USO
---
    python3 deploy/scripts/preflight_https.py --env-file /etc/s9-knowledge/viewer.env
    python3 deploy/scripts/preflight_https.py --url https://host --session-secure true

rc=0 solo si TODO verifica. Cualquier otro rc significa INSTALACION NO
COMPLETA.
"""
from __future__ import annotations

import argparse
import http.client
import socket
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

#: Mismo criterio que `viewer/app/health/checks.py::check_viewer`: 200 con la
#: auth apagada, 401 con la auth encendida. Ambos significan "el proceso
#: contesto". Cualquier otro codigo es una respuesta inesperada y se nombra
#: aparte, porque un 502 del reverse proxy NO es una instalacion que funciona.
ESTADOS_QUE_SIGNIFICAN_QUE_CONTESTO = frozenset({200, 401})

#: Ruta sondeada. La misma que usa `check_viewer`.
RUTA_DE_SONDEO = "/api/status"

#: Valores que cuentan como verdadero. Misma doctrina que
#: `viewer/app/chassis.FLAG_ON_VALUES`: lista cerrada, no "cualquier cosa no
#: vacia". Replicada por la misma razon que el criterio de estado.
VALORES_VERDADEROS = frozenset({"1", "true", "yes", "on", "si"})

TIEMPO_LIMITE = 10.0


@dataclass(frozen=True)
class Hallazgo:
    """Un fallo, con su CAUSA nombrada. Nada de mensajes genericos."""

    causa: str
    mensaje: str

    def __str__(self) -> str:  # pragma: no cover - formato
        return "FALLO(%s): %s" % (self.causa, self.mensaje)


# ---------------------------------------------------------------------------
# Lectura de configuracion: el FICHERO, con la semantica de validate_deploy.sh
# ---------------------------------------------------------------------------

def valor_de_env_file(ruta: Path, nombre: str) -> Optional[str]:
    """Valor de `nombre` en un EnvironmentFile, o ``None``.

    Semantica identica a ``validate_deploy.sh::_env_value``, que es la
    autoridad estatica del despliegue: ultima aparicion no comentada, se
    recortan espacios de borde y UN par de comillas envolventes.
    """
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    encontrado: Optional[str] = None
    for linea in texto.splitlines():
        desnuda = linea.strip()
        if not desnuda or desnuda.startswith("#"):
            continue
        clave, sep, valor = linea.partition("=")
        if not sep or clave.strip() != nombre:
            continue
        valor = valor.strip()
        if valor.endswith('"'):
            valor = valor[:-1]
        if valor.startswith('"'):
            valor = valor[1:]
        if valor.endswith("'"):
            valor = valor[:-1]
        if valor.startswith("'"):
            valor = valor[1:]
        encontrado = valor
    return encontrado


def es_verdadero(valor: Optional[str]) -> bool:
    """``True`` solo para un valor de la lista cerrada. Ausente -> ``False``."""
    if valor is None:
        return False
    return valor.strip().lower() in VALORES_VERDADEROS


# ---------------------------------------------------------------------------
# Comprobaciones estaticas (cada garantia en su propia funcion, con su causa)
# ---------------------------------------------------------------------------

def comprobar_url_declarada(url: Optional[str]) -> Optional[Hallazgo]:
    """La instalacion tiene que DECIR cual es su URL publica."""
    if url is None or not url.strip():
        return Hallazgo(
            "URL_PUBLICA_NO_DECLARADA",
            "S9K_PUBLIC_BASE_URL no esta declarada. Una instalacion que no "
            "dice por donde se la alcanza no se puede verificar, y sin "
            "verificar no esta completa.",
        )
    return None


def comprobar_esquema_https(url: str) -> Optional[Hallazgo]:
    """El esquema de la URL publica tiene que ser ``https``."""
    esquema = urlsplit(url).scheme.lower()
    if esquema != "https":
        return Hallazgo(
            "ESQUEMA_NO_HTTPS",
            "la URL publica declarada usa el esquema %r, no 'https'. TLS es "
            "responsabilidad del proceso de instalacion: sin HTTPS la "
            "instalacion NO esta completa." % (esquema or "(ninguno)",),
        )
    return None


def comprobar_cookie_secure_coherente(url: str, session_secure: bool) -> Optional[Hallazgo]:
    """HTTP plano con cookie ``Secure`` = instalacion NO valida.

    ESTE ES EL DEFECTO MEDIDO, convertido en guardian. No se arregla
    degradando la cookie -eso fue considerado y DESCARTADO (D3)-: se arregla
    entregando HTTPS. Vive en su propia funcion y con su propia causa porque
    el diagnostico no es el mismo que ``ESQUEMA_NO_HTTPS``: aqui se nombra
    POR QUE el HTTP plano rompe, no solo que es HTTP.
    """
    if not session_secure:
        return None
    if urlsplit(url).scheme.lower() == "https":
        return None
    return Hallazgo(
        "COOKIE_SECURE_SOBRE_HTTP",
        "S9K_SESSION_SECURE=true y la URL publica es HTTP plano. La cookie "
        "CSRF de /setup/admin saldra con atributo Secure, ningun cliente la "
        "devolvera y el POST entrara en bucle de 403: NO se podra crear el "
        "primer administrador. Esto NO se resuelve poniendo "
        "S9K_SESSION_SECURE=false en produccion (opt-out solo de "
        "laboratorio): se resuelve entregando HTTPS.",
    )


# ---------------------------------------------------------------------------
# Comprobaciones POR EFECTO: se abre el socket TLS de verdad
# ---------------------------------------------------------------------------

def _contexto(ca_file: Optional[str], comprobar_nombre: bool) -> ssl.SSLContext:
    """Contexto TLS que SIEMPRE verifica la cadena.

    ``comprobar_nombre`` solo gobierna el hostname check, y existe para poder
    SEPARAR las dos causas (cadena invalida vs nombre que no coincide). La
    verificacion de cadena no se apaga nunca: ``CERT_REQUIRED`` es fijo.
    """
    ctx = ssl.create_default_context(cafile=ca_file)
    ctx.check_hostname = comprobar_nombre
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _destino(url: str) -> tuple:
    partes = urlsplit(url)
    return partes.hostname or "", partes.port or 443


def comprobar_cadena_de_certificado(url: str, ca_file: Optional[str] = None,
                                    timeout: float = TIEMPO_LIMITE) -> Optional[Hallazgo]:
    """Handshake real exigiendo cadena valida, SIN mirar el nombre todavia."""
    host, puerto = _destino(url)
    ctx = _contexto(ca_file, comprobar_nombre=False)
    try:
        with socket.create_connection((host, puerto), timeout=timeout) as crudo:
            with ctx.wrap_socket(crudo, server_hostname=host):
                return None
    except ssl.SSLCertVerificationError as exc:
        return Hallazgo(
            "CERTIFICADO_NO_VERIFICABLE",
            "el certificado presentado en %s:%d no verifica contra el almacen "
            "de confianza declarado (%s): %s. Un autofirmado se acepta "
            "DECLARANDOLO en S9K_TLS_CA_FILE, nunca desactivando la "
            "verificacion." % (host, puerto, ca_file or "almacen del sistema",
                               exc.verify_message or exc.reason),
        )
    except (OSError, ssl.SSLError) as exc:
        return Hallazgo(
            "ENDPOINT_NO_RESPONDE",
            "no se pudo establecer TLS contra %s:%d: %s. Si no hay nada "
            "escuchando, la instalacion no entrega HTTPS y NO esta completa."
            % (host, puerto, type(exc).__name__),
        )


def comprobar_nombre_del_certificado(url: str, ca_file: Optional[str] = None,
                                     timeout: float = TIEMPO_LIMITE) -> Optional[Hallazgo]:
    """Handshake real con hostname check ACTIVO contra el nombre de la URL."""
    host, puerto = _destino(url)
    ctx = _contexto(ca_file, comprobar_nombre=True)
    try:
        with socket.create_connection((host, puerto), timeout=timeout) as crudo:
            with ctx.wrap_socket(crudo, server_hostname=host):
                return None
    except ssl.SSLCertVerificationError as exc:
        return Hallazgo(
            "NOMBRE_NO_COINCIDE",
            "el certificado de %s:%d no ampara el nombre %r por el que se "
            "publica la instalacion: %s." % (host, puerto, host,
                                             exc.verify_message or exc.reason),
        )
    except (OSError, ssl.SSLError) as exc:
        return Hallazgo(
            "ENDPOINT_NO_RESPONDE",
            "no se pudo establecer TLS contra %s:%d: %s."
            % (host, puerto, type(exc).__name__),
        )


def comprobar_endpoint_responde(url: str, ca_file: Optional[str] = None,
                                timeout: float = TIEMPO_LIMITE) -> Optional[Hallazgo]:
    """VERIFICACION POR EFECTO: ``GET`` real sobre TLS y codigo de estado.

    No vale que la configuracion este escrita, ni que el handshake salga: se
    exige que el otro extremo DEVUELVA una respuesta HTTP. Un listener TLS que
    acepta y cierra sin hablar HTTP cae aqui, y es justo el caso que un
    "nginx arrancado" sin backend produce.
    """
    host, puerto = _destino(url)
    ctx = _contexto(ca_file, comprobar_nombre=True)
    conexion = http.client.HTTPSConnection(host, puerto, timeout=timeout, context=ctx)
    try:
        conexion.request("GET", RUTA_DE_SONDEO, headers={"Accept": "application/json"})
        respuesta = conexion.getresponse()
        estado = respuesta.status
        respuesta.read()
    except Exception as exc:
        return Hallazgo(
            "ENDPOINT_NO_RESPONDE",
            "https://%s:%d%s no devolvio ninguna respuesta HTTP (%s). Que la "
            "configuracion este escrita no es que el endpoint conteste."
            % (host, puerto, RUTA_DE_SONDEO, type(exc).__name__),
        )
    finally:
        conexion.close()
    if estado not in ESTADOS_QUE_SIGNIFICAN_QUE_CONTESTO:
        return Hallazgo(
            "ENDPOINT_RESPUESTA_INESPERADA",
            "https://%s:%d%s contesto HTTP %d; solo %s significan que el "
            "visor esta detras (200 auth off / 401 auth on). Un 502 es el "
            "terminador TLS sin backend."
            % (host, puerto, RUTA_DE_SONDEO, estado,
               sorted(ESTADOS_QUE_SIGNIFICAN_QUE_CONTESTO)),
        )
    return None


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Entrada:
    url: Optional[str]
    session_secure: bool
    ca_file: Optional[str] = None
    timeout: float = TIEMPO_LIMITE


def verificar(entrada: Entrada) -> list:
    """Todos los hallazgos. Lista vacia = via HTTPS verificada AHORA."""
    hallazgos = []
    falta = comprobar_url_declarada(entrada.url)
    if falta is not None:
        return [falta]
    url = (entrada.url or "").strip()

    estaticos = [
        comprobar_esquema_https(url),
        comprobar_cookie_secure_coherente(url, entrada.session_secure),
    ]
    hallazgos.extend(h for h in estaticos if h is not None)
    if hallazgos:
        # Sin HTTPS no hay nada que sondear: sondear http:// aqui seria
        # exactamente el fallback a HTTP que D3 prohibe.
        return hallazgos

    cadena = comprobar_cadena_de_certificado(url, entrada.ca_file, entrada.timeout)
    if cadena is not None:
        return [cadena]
    nombre = comprobar_nombre_del_certificado(url, entrada.ca_file, entrada.timeout)
    if nombre is not None:
        return [nombre]
    responde = comprobar_endpoint_responde(url, entrada.ca_file, entrada.timeout)
    if responde is not None:
        return [responde]
    return []


def codigo_de_salida(hallazgos: list) -> int:
    """rc=0 SOLO sin hallazgos. Fallo de HTTPS => instalacion NO completa."""
    return 0 if not hallazgos else 1


def entrada_desde_env_file(ruta: Path) -> Entrada:
    return Entrada(
        url=valor_de_env_file(ruta, "S9K_PUBLIC_BASE_URL"),
        session_secure=es_verdadero(valor_de_env_file(ruta, "S9K_SESSION_SECURE")),
        ca_file=valor_de_env_file(ruta, "S9K_TLS_CA_FILE") or None,
    )


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Preflight de la via HTTPS de la instalacion (por efecto).")
    ap.add_argument("--env-file", help="EnvironmentFile del visor (viewer.env)")
    ap.add_argument("--url", help="URL publica (sobreescribe la del fichero)")
    ap.add_argument("--session-secure", choices=["true", "false"],
                    help="valor efectivo de S9K_SESSION_SECURE")
    ap.add_argument("--ca-file", help="almacen de confianza declarado")
    ap.add_argument("--timeout", type=float, default=TIEMPO_LIMITE)
    args = ap.parse_args(argv)

    if args.env_file:
        base = entrada_desde_env_file(Path(args.env_file))
    else:
        base = Entrada(url=None, session_secure=True)
    entrada = Entrada(
        url=args.url if args.url else base.url,
        session_secure=(es_verdadero(args.session_secure)
                        if args.session_secure else base.session_secure),
        ca_file=args.ca_file or base.ca_file,
        timeout=args.timeout,
    )

    hallazgos = verificar(entrada)
    for h in hallazgos:
        print(str(h))
    rc = codigo_de_salida(hallazgos)
    if rc == 0:
        print("OK: la via HTTPS declarada verifica y CONTESTA en este momento.")
        print("    Esto NO es el ensayo RC (ver deploy/README.md).")
    else:
        print("INSTALACION NO COMPLETA: la via HTTPS no verifica.")
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
