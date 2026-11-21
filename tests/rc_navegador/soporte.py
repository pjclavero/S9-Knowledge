# -*- coding: utf-8 -*-
"""Soporte de la batería de navegador contra una INSTALACIÓN REAL.

Esta batería no arranca el producto ni importa nada de él: habla con una
instalación ya desplegada (nginx + TLS + CA propia + visor + worker) a través
de un Chromium real en modo headless. Todo lo que necesita saber de esa
instalación entra por variables de entorno ``S9K_RC_NAV_*``; ninguna
credencial vive en el repositorio ni viaja por la línea de comandos.

Qué hay aquí
------------
* ``Config`` / ``cargar_config``: lectura y validación de la parametrización.
* ``Redactor``: retira cookies, contraseñas y testigos CSRF de todo lo que se
  guarda (HTML, registros y trazas de Playwright), y comprueba después que no
  quedó ninguno.
* ``Evidencia``: captura de pantalla + HTML redactado + registro por paso.
* Utilidades TLS: verificación ESTRICTA de la cadena con la CA declarada y
  cálculo de la huella SPKI que se le da a Chromium para que acepte esa
  cadena y sólo esa.
* Utilidades de navegación: inicio de sesión como una persona (formulario y
  botón) y ``fetch`` ejecutado dentro de la página.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import ssl
import stat
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

PREFIJO = "S9K_RC_NAV_"

#: Raíz del repositorio (este fichero vive en tests/rc_navegador/).
REPO = Path(__file__).resolve().parents[2]

#: Capacidades que la instalación puede declarar. Una prueba que necesita una
#: capacidad no declarada NO se ejecuta y NO cuenta como verde: queda PENDING
#: (si lo que falta es el grafo) o BLOCKED (si es configuración del ensayo).
CAPACIDADES = {
    "grafo": "Neo4j arrancado y el visor configurado con S9K_GRAPH_PROVIDER=neo4j",
    "panel_b": "S9K_PANEL_B_ENABLED=true (Panel · Operaciones)",
    "panel_c": "S9K_PANEL_C_ENABLED=true (Panel · Review)",
    "panel_f": "S9K_PANEL_F_ENABLED=true (Panel · Fuentes)",
    "panel_g": "S9K_PANEL_G_ENABLED=true (Panel · Entidades)",
    "resultado": "S9K_PANEL_RESULTADO_ENABLED=true (resultado y procedencia)",
    "boveda": "S9K_VAULT_ROOT declarado, con perfil y partidas",
    "boveda_solo_lectura": "la bóveda declarada NO es escribible por el servicio",
    "boveda_inexistente": "S9K_VAULT_ROOT declarado pero la carpeta del juego no existe",
    "ingesta": "S9K_INGEST_SOURCES_DIR poblado y worker activo",
    "apply": "S9K_ALLOW_REAL_INGEST=1 y S9K_WRITER_WORKSPACE = workspace del ensayo",
    "aislamiento": "S9K_WRITER_WORKSPACE apunta a OTRO workspace (negativo 8.M9)",
    "job_credencial": "existe un job fallido por credencial inutilizable (S9K_RC_NAV_JOB_CREDENCIAL)",
    "setup_abierto": "instalación SIN primer administrador (FIRST_ADMIN_PENDING)",
    "partidas": "hay dos partidas y los lectores acotados tienen concedida una cada uno",
}

#: Roles lógicos de la batería -> rol del producto. Cada cuenta tiene UN uso,
#: porque el producto revoca las sesiones anteriores de un usuario en cada
#: inicio de sesión (rotación): dos pruebas que entren con la misma cuenta se
#: tumbarían la sesión la una a la otra.
CUENTAS = {
    "admin": "admin",        # sesión compartida de administrador
    "revisor": "reviewer",   # sesión compartida de revisor
    "lector": "viewer",      # sesión compartida de lector
    "lector_b": "viewer",    # segundo lector, acotado a OTRO ámbito
    "sesion": "viewer",      # pruebas de inicio/cierre de sesión y rotación
    "bloqueo": "viewer",     # bloqueo por intentos fallidos
    "cambio": "viewer",      # obligado a cambiar la contraseña al entrar
    "inactivo": "viewer",    # cuenta desactivada
    "inact_a": "viewer",     # caducidad por inactividad: la que se deja quieta
    "inact_b": "viewer",     # caducidad por inactividad: el control con actividad
}

MARCA = "REDACTADO"


class ConfiguracionInvalida(Exception):
    """La parametrización no permite ejecutar: se dice la causa y se para."""


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    base_url: str
    ca_file: Path
    credenciales: dict
    salida: Path
    capacidades: frozenset
    idle_minutos: Optional[int]
    max_intentos: int
    fase_inactividad: str
    estado_dir: Path
    workspace: str
    otro_workspace: str
    fuente: str
    termino: str
    espera_worker_s: int
    job_credencial: str
    job_sellado: str
    partida_a: str
    partida_b: str
    flujo_desde: str
    flujo_hasta: str
    perfil_boveda: str
    fase_persistencia: str

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    @property
    def puerto(self) -> int:
        return urlparse(self.base_url).port or 443

    def url(self, ruta: str) -> str:
        return self.base_url + ruta

    def cuenta(self, clave: str) -> dict:
        try:
            return self.credenciales[clave]
        except KeyError:
            raise ConfiguracionInvalida(
                f"el fichero de credenciales no trae la cuenta «{clave}»: "
                "créala con herramientas/usuarios_de_prueba.py crear"
            ) from None


def _dentro_del_repo(ruta: Path) -> bool:
    try:
        ruta.resolve().relative_to(REPO)
    except ValueError:
        return False
    return True


def leer_credenciales(ruta: Path) -> dict:
    """Lee el fichero de credenciales, exigiendo que sea privado y externo."""
    if _dentro_del_repo(ruta):
        raise ConfiguracionInvalida(
            "el fichero de credenciales está DENTRO del repositorio: muévelo fuera"
        )
    try:
        st = ruta.stat()
    except OSError as exc:
        raise ConfiguracionInvalida(f"no se puede leer el fichero de credenciales: {exc}") from None
    if not stat.S_ISREG(st.st_mode):
        raise ConfiguracionInvalida("el fichero de credenciales no es un fichero regular")
    if st.st_mode & 0o077:
        raise ConfiguracionInvalida(
            f"el fichero de credenciales tiene modo {stat.S_IMODE(st.st_mode):04o}: "
            "tiene que ser 0600 (sin acceso de grupo ni de otros)"
        )
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    cuentas = datos.get("cuentas")
    if not isinstance(cuentas, dict) or not cuentas:
        raise ConfiguracionInvalida("el fichero de credenciales no trae «cuentas»")
    for clave, c in cuentas.items():
        if not c.get("username") or not c.get("password"):
            raise ConfiguracionInvalida(f"la cuenta «{clave}» no trae username/password")
    return cuentas


def cargar_config(env: Optional[dict] = None) -> Config:
    env = os.environ if env is None else env

    def v(nombre: str, defecto: str = "") -> str:
        return (env.get(PREFIJO + nombre) or defecto).strip()

    faltan = [PREFIJO + n for n in ("BASE_URL", "CA_FILE", "CREDENCIALES", "SALIDA") if not v(n)]
    if faltan:
        raise ConfiguracionInvalida(
            "faltan variables de entorno obligatorias: " + ", ".join(faltan)
            + ". Esta batería sólo corre contra una instalación real; ver README.md"
        )
    base = v("BASE_URL").rstrip("/")
    u = urlparse(base)
    if u.scheme != "https" or not u.hostname:
        raise ConfiguracionInvalida(
            f"{PREFIJO}BASE_URL tiene que ser https://<nombre público>: el producto "
            "emite la cookie de sesión con Secure y un navegador no la devuelve por http"
        )
    ca = Path(v("CA_FILE"))
    if not ca.is_file():
        raise ConfiguracionInvalida(f"{PREFIJO}CA_FILE no es un fichero legible")
    salida = Path(v("SALIDA"))
    if _dentro_del_repo(salida):
        raise ConfiguracionInvalida(f"{PREFIJO}SALIDA está dentro del repositorio: la evidencia va fuera")
    cred_path = Path(v("CREDENCIALES"))
    credenciales = leer_credenciales(cred_path)

    caps = frozenset(c.strip() for c in v("CAPACIDADES").split(",") if c.strip())
    desconocidas = sorted(caps - set(CAPACIDADES))
    if desconocidas:
        raise ConfiguracionInvalida(
            f"{PREFIJO}CAPACIDADES declara capacidades desconocidas: {desconocidas}; "
            f"conocidas: {sorted(CAPACIDADES)}"
        )
    idle = v("IDLE_MINUTOS")
    fase = v("FASE_INACTIVIDAD")
    if fase not in ("", "sembrar", "tocar", "comprobar"):
        raise ConfiguracionInvalida(f"{PREFIJO}FASE_INACTIVIDAD: «{fase}» no es sembrar|tocar|comprobar")
    estado_dir = Path(v("ESTADO_DIR") or str(cred_path.parent))
    if _dentro_del_repo(estado_dir):
        raise ConfiguracionInvalida(f"{PREFIJO}ESTADO_DIR está dentro del repositorio")
    return Config(
        base_url=base,
        ca_file=ca,
        credenciales=credenciales,
        salida=salida,
        capacidades=caps,
        idle_minutos=int(idle) if idle else None,
        max_intentos=int(v("MAX_INTENTOS", "5")),
        fase_inactividad=fase,
        estado_dir=estado_dir,
        workspace=v("WORKSPACE"),
        otro_workspace=v("OTRO_WORKSPACE"),
        fuente=v("FUENTE"),
        termino=v("TERMINO"),
        espera_worker_s=int(v("ESPERA_WORKER_S", "300")),
        job_credencial=v("JOB_CREDENCIAL"),
        job_sellado=v("JOB_SELLADO"),
        partida_a=v("PARTIDA_A"),
        partida_b=v("PARTIDA_B"),
        flujo_desde=v("FLUJO_DESDE", "ingesta"),
        flujo_hasta=v("FLUJO_HASTA", "busqueda"),
        perfil_boveda=v("PERFIL_BOVEDA"),
        fase_persistencia=v("FASE_PERSISTENCIA"),
    )


# ---------------------------------------------------------------------------
# TLS: la cadena se verifica de verdad, con la CA declarada
# ---------------------------------------------------------------------------

def _tlv(der: bytes, pos: int) -> tuple[int, int, int]:
    """Lee un TLV DER en ``pos``: (etiqueta, inicio del valor, fin del valor)."""
    etiqueta = der[pos]
    largo = der[pos + 1]
    inicio = pos + 2
    if largo & 0x80:
        n = largo & 0x7F
        largo = int.from_bytes(der[inicio:inicio + n], "big")
        inicio += n
    return etiqueta, inicio, inicio + largo


def spki_sha256_b64(cert_der: bytes) -> str:
    """Huella SHA-256 (base64) del SubjectPublicKeyInfo de un certificado X.509.

    Es el formato que entiende ``--ignore-certificate-errors-spki-list``. Se
    recorre el DER a mano para no depender de ninguna biblioteca criptográfica:
    Certificate -> tbsCertificate -> [version] serial, firma, emisor, validez,
    sujeto, **subjectPublicKeyInfo**.
    """
    _, c_ini, _ = _tlv(cert_der, 0)                 # Certificate
    _, pos, _ = _tlv(cert_der, c_ini)               # tbsCertificate
    etiqueta, _, fin = _tlv(cert_der, pos)
    if etiqueta == 0xA0:                            # [0] version, opcional
        pos = fin
    for _ in range(5):                              # serial, firma, emisor, validez, sujeto
        _, _, pos = _tlv(cert_der, pos)
    _, _, fin = _tlv(cert_der, pos)                 # subjectPublicKeyInfo
    return base64.b64encode(hashlib.sha256(cert_der[pos:fin]).digest()).decode("ascii")


def certificados_del_pem(ruta: Path) -> list[bytes]:
    texto = ruta.read_text(encoding="ascii", errors="replace")
    bloques = re.findall(
        r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", texto, flags=re.S
    )
    return [base64.b64decode("".join(b.split())) for b in bloques]


def verificar_tls(cfg: Config) -> dict:
    """Handshake ESTRICTO contra la instalación con la CA declarada.

    Verifica cadena y nombre (``check_hostname``). Devuelve los datos públicos
    del certificado servido y las huellas SPKI de la hoja y de la CA.
    """
    ctx = ssl.create_default_context(cafile=str(cfg.ca_file))
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    with socket.create_connection((cfg.host, cfg.puerto), timeout=15) as crudo:
        with ctx.wrap_socket(crudo, server_hostname=cfg.host) as tls:
            hoja_der = tls.getpeercert(binary_form=True)
            hoja = tls.getpeercert()
            protocolo = tls.version()
    huellas = [spki_sha256_b64(hoja_der)] + [spki_sha256_b64(c) for c in certificados_del_pem(cfg.ca_file)]
    return {
        "host": cfg.host,
        "protocolo": protocolo,
        "sujeto": hoja.get("subject"),
        "emisor": hoja.get("issuer"),
        "caduca": hoja.get("notAfter"),
        "nombres_alternativos": hoja.get("subjectAltName"),
        "spki_sha256": list(dict.fromkeys(huellas)),
    }


# ---------------------------------------------------------------------------
# Redacción
# ---------------------------------------------------------------------------

_PATRONES_TEXTO = (
    # <input type="hidden" name="csrf_token" value="...">
    (re.compile(r'(name="csrf_token"\s+value=")[^"]*'), r"\1" + MARCA),
    # cuerpos de formulario y query strings
    (re.compile(r"(csrf_token=)[^&\"'\\\s<]+"), r"\1" + MARCA),
    # cabeceras Cookie / Set-Cookie volcadas como texto
    (re.compile(r"((?:_?s9k_[a-z_]+)=)[^;\"'\\\s,]+"), r"\1" + MARCA),
)

_PATRONES_BYTES = (
    (re.compile(rb'(name=\\?"csrf_token\\?"\s+value=\\?")[^"\\]*'), rb"\1" + MARCA.encode()),
    (re.compile(rb'("name":"csrf_token","value":")[^"]*'), rb"\1" + MARCA.encode()),
    (re.compile(rb'("csrf_token",")[^"]*'), rb"\1" + MARCA.encode()),
    (re.compile(rb"(csrf_token=)[^&\"'\\\s<]+"), rb"\1" + MARCA.encode()),
    (re.compile(rb"((?:_?s9k_[a-z_]+)=)[^;\"'\\\s,]+"), rb"\1" + MARCA.encode()),
)


class Redactor:
    """Quita secretos de lo que se guarda y comprueba que no quedó ninguno.

    Dos mecanismos, a propósito: los valores CONOCIDOS (contraseñas del
    fichero de credenciales, valores de cookie vistos en el navegador) se
    sustituyen literalmente; y unos patrones cubren lo que no se llegó a ver
    (testigos CSRF de páginas por las que la prueba sólo pasó).
    """

    def __init__(self) -> None:
        self._secretos: set[str] = set()

    def registrar(self, valor: Optional[str]) -> None:
        if valor and len(valor) >= 8:
            self._secretos.add(valor)

    def registrar_cookies(self, cookies: Iterable[dict]) -> None:
        for c in cookies:
            self.registrar(c.get("value"))

    def registrar_set_cookie(self, cabecera: Optional[str]) -> None:
        for linea in (cabecera or "").split("\n"):
            par = linea.split(";", 1)[0]
            if "=" in par:
                self.registrar(par.split("=", 1)[1].strip().strip('"'))

    def texto(self, s: str) -> str:
        for secreto in sorted(self._secretos, key=len, reverse=True):
            s = s.replace(secreto, MARCA)
        for patron, sustituto in _PATRONES_TEXTO:
            s = patron.sub(sustituto, s)
        return s

    def binario(self, b: bytes) -> bytes:
        for secreto in sorted(self._secretos, key=len, reverse=True):
            b = b.replace(secreto.encode("utf-8"), MARCA.encode())
        for patron, sustituto in _PATRONES_BYTES:
            b = patron.sub(sustituto, b)
        return b

    def zip(self, origen: Path, destino: Path) -> None:
        """Reescribe una traza de Playwright sin secretos."""
        with zipfile.ZipFile(origen) as zin, zipfile.ZipFile(
            destino, "w", compression=zipfile.ZIP_DEFLATED
        ) as zout:
            for info in zin.infolist():
                zout.writestr(info.filename, self.binario(zin.read(info.filename)))

    def fugas(self, raiz: Path) -> list[str]:
        """Rutas (y miembros de zip) donde aparece algún secreto conocido."""
        halladas: list[str] = []
        agujas = [s.encode("utf-8") for s in self._secretos]

        def contiene(datos: bytes) -> bool:
            return any(a in datos for a in agujas)

        for ruta in sorted(raiz.rglob("*")):
            if not ruta.is_file():
                continue
            if ruta.suffix == ".zip":
                try:
                    with zipfile.ZipFile(ruta) as z:
                        for nombre in z.namelist():
                            if contiene(z.read(nombre)):
                                halladas.append(f"{ruta}!{nombre}")
                except zipfile.BadZipFile:
                    halladas.append(f"{ruta} (zip ilegible: no se pudo comprobar)")
            elif contiene(ruta.read_bytes()):
                halladas.append(str(ruta))
        return halladas


# ---------------------------------------------------------------------------
# Evidencia por paso
# ---------------------------------------------------------------------------

def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")[:60] or "paso"


@dataclass
class Evidencia:
    """Captura, HTML y registro de cada paso de UNA prueba."""

    directorio: Path
    redactor: Redactor
    pasos: list = field(default_factory=list)
    _n: int = 0

    def __post_init__(self) -> None:
        self.directorio.mkdir(parents=True, exist_ok=True)

    def paso(self, page, nombre: str, *, estado: Optional[int] = None, nota: str = "") -> None:
        """Guarda captura + HTML de la página tal como está ahora."""
        self._n += 1
        base = f"{self._n:02d}-{_slug(nombre)}"
        registro = {
            "n": self._n,
            "paso": nombre,
            "url": self.redactor.texto(page.url),
            "estado_http": estado,
            "nota": nota,
            "hora_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            page.screenshot(path=str(self.directorio / f"{base}.png"), full_page=True)
            registro["captura"] = f"{base}.png"
        except Exception as exc:  # la captura no puede tumbar la prueba
            registro["captura_error"] = type(exc).__name__
        try:
            html = self.redactor.texto(page.content())
            (self.directorio / f"{base}.html").write_text(html, encoding="utf-8")
            registro["html"] = f"{base}.html"
            registro["titulo"] = page.title()
        except Exception as exc:
            registro["html_error"] = type(exc).__name__
        self.pasos.append(registro)
        self._volcar()

    def dato(self, nombre: str, valor) -> None:
        """Anota un dato medido (no una pantalla)."""
        self._n += 1
        self.pasos.append({
            "n": self._n, "dato": nombre,
            "valor": json.loads(self.redactor.texto(json.dumps(valor, ensure_ascii=False, default=str))),
            "hora_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        self._volcar()

    def _volcar(self) -> None:
        (self.directorio / "pasos.json").write_text(
            json.dumps(self.pasos, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Navegación
# ---------------------------------------------------------------------------

def ir(page, cfg: Config, ruta: str):
    """Navega y devuelve la respuesta FINAL (tras las redirecciones)."""
    return page.goto(cfg.url(ruta), wait_until="domcontentloaded")


def cadena_de_redirecciones(respuesta) -> list[tuple[int, str]]:
    """[(estado, ruta)] desde la primera petición hasta la respuesta final."""
    cadena = []
    peticion = respuesta.request
    previas = []
    while peticion.redirected_from is not None:
        peticion = peticion.redirected_from
        previas.append(peticion)
    for p in reversed(previas):
        r = p.response()
        u = urlparse(p.url)
        cadena.append((r.status if r else -1, u.path + (f"?{u.query}" if u.query else "")))
    u = urlparse(respuesta.url)
    cadena.append((respuesta.status, u.path + (f"?{u.query}" if u.query else "")))
    return cadena


def ruta_de(page) -> str:
    u = urlparse(page.url)
    return u.path


def rellenar_login(page, cfg: Config, usuario: str, clave: str, *, siguiente: str = "/") -> None:
    """Abre /login y escribe usuario y contraseña, sin enviar."""
    page.goto(cfg.url(f"/login?next={siguiente}"), wait_until="domcontentloaded")
    page.fill("#username", usuario)
    page.fill("#password", clave)


def enviar_login(page):
    """Pulsa el botón visible y devuelve la respuesta del POST /login."""
    with page.expect_response(
        lambda r: r.request.method == "POST" and urlparse(r.url).path == "/login"
    ) as info:
        page.click("#login-submit")
    respuesta = info.value
    page.wait_for_load_state("domcontentloaded")
    return respuesta


def iniciar_sesion(page, cfg: Config, cuenta: dict, *, siguiente: str = "/"):
    """Inicia sesión como lo haría una persona. Devuelve la respuesta del POST."""
    rellenar_login(page, cfg, cuenta["username"], cuenta["password"], siguiente=siguiente)
    return enviar_login(page)


def fetch_en_pagina(page, metodo: str, ruta: str, *, formulario: Optional[dict] = None) -> dict:
    """``fetch`` ejecutado DENTRO de la página: usa la pila de red, las cookies
    y la política de mismo origen del navegador, no un cliente HTTP aparte."""
    return page.evaluate(
        """async ([metodo, ruta, formulario]) => {
            const opciones = {method: metodo, credentials: 'same-origin', redirect: 'follow'};
            if (formulario) {
                opciones.headers = {'Content-Type': 'application/x-www-form-urlencoded'};
                opciones.body = new URLSearchParams(formulario).toString();
            }
            const r = await fetch(ruta, opciones);
            const texto = await r.text();
            return {estado: r.status, url: r.url, redirigida: r.redirected,
                    tipo: r.headers.get('content-type') || '', texto: texto.slice(0, 4000)};
        }""",
        [metodo, ruta, formulario],
    )


def enlaces_de_navegacion(page) -> list[str]:
    """Nombres de ruta (``data-nav``) que la barra superior ofrece ahora."""
    return page.eval_on_selector_all("header.topbar nav a[data-nav]", "els => els.map(e => e.dataset.nav)")


def texto_visible(page, selector: str = "body") -> str:
    return " ".join(page.inner_text(selector).split())
