# -*- coding: utf-8 -*-
"""Fixtures y reglas de la batería de navegador contra una instalación real.

Reglas que este fichero IMPONE (no son convenciones):

1. Toda prueba declara si necesita Neo4j: exactamente uno de los marcadores
   ``sin_grafo`` / ``necesita_grafo``. Y declara qué cubre del contrato con
   ``cubre(...)``. Sin eso la colección falla.
2. Una prueba cuya capacidad no está declarada en ``S9K_RC_NAV_CAPACIDADES``
   NO se ejecuta y NO cuenta como verde: queda ``PENDING`` (falta el grafo) o
   ``BLOCKED`` (falta configuración del ensayo), con su motivo, en
   ``resultado.json``. Cualquier otro salto se trata como fallo de la tanda.
3. Playwright y Chromium son obligatorios: si faltan, la batería falla al
   arrancar. Aquí no hay omisión por herramienta ausente.
4. Nada de lo que se guarda lleva cookies ni contraseñas. Al terminar se
   recorre TODA la salida buscando los secretos conocidos; si aparece uno, la
   tanda termina en rojo aunque todas las pruebas hayan pasado.
5. La cadena TLS se verifica de verdad con la CA declarada antes de abrir el
   navegador, y a Chromium se le da la huella de la clave de esa cadena: no
   se navega con los errores de certificado desactivados.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import soporte  # noqa: E402
from soporte import (  # noqa: E402
    CAPACIDADES,
    Config,
    ConfiguracionInvalida,
    Evidencia,
    Redactor,
    cargar_config,
    iniciar_sesion,
    verificar_tls,
)

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright  # noqa: E402

VENTANA = {"width": 1280, "height": 900}

_CLAVE_CONFIG = pytest.StashKey[Config]()
_CLAVE_RESULTADOS = pytest.StashKey[dict]()
_CLAVE_REDACTOR = pytest.StashKey[Redactor]()


# ---------------------------------------------------------------------------
# Arranque: configuración o nada
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    try:
        cfg = cargar_config()
    except ConfiguracionInvalida as exc:
        raise pytest.UsageError(f"batería de navegador: {exc}") from None
    cfg.salida.mkdir(parents=True, exist_ok=True)
    os.chmod(cfg.salida, 0o700)
    redactor = Redactor()
    for cuenta in cfg.credenciales.values():
        redactor.registrar(cuenta["password"])
    config.stash[_CLAVE_CONFIG] = cfg
    config.stash[_CLAVE_REDACTOR] = redactor
    config.stash[_CLAVE_RESULTADOS] = {}


def _marcas(item: pytest.Item, nombre: str) -> list[str]:
    valores: list[str] = []
    for marca in item.iter_markers(name=nombre):
        valores.extend(str(a) for a in marca.args)
    return list(dict.fromkeys(valores))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    cfg = config.stash[_CLAVE_CONFIG]
    errores = []
    for item in items:
        sin = item.get_closest_marker("sin_grafo") is not None
        con = item.get_closest_marker("necesita_grafo") is not None
        if sin == con:
            errores.append(f"{item.nodeid}: declara exactamente uno de sin_grafo / necesita_grafo")
        if not _marcas(item, "cubre"):
            errores.append(f"{item.nodeid}: falta el marcador cubre(...)")
        requeridas = _marcas(item, "requiere")
        desconocidas = [c for c in requeridas if c not in CAPACIDADES]
        if desconocidas:
            errores.append(f"{item.nodeid}: requiere capacidades desconocidas {desconocidas}")
        if con and "grafo" not in cfg.capacidades:
            item.add_marker(pytest.mark.skip(
                reason="PENDING[D1]: necesita Neo4j y la instalación no declara la capacidad «grafo»"
            ))
            continue
        faltan = [c for c in requeridas if c not in cfg.capacidades]
        if faltan:
            detalle = "; ".join(f"{c} = {CAPACIDADES[c]}" for c in faltan)
            item.add_marker(pytest.mark.skip(
                reason=f"BLOCKED[config]: la instalación no declara {detalle}"
            ))
    if errores:
        raise pytest.UsageError("batería de navegador mal declarada:\n  " + "\n  ".join(errores))


# ---------------------------------------------------------------------------
# Resultado declarado: PASS / FAIL / PENDING / BLOCKED
# ---------------------------------------------------------------------------

def _estado_de_salto(motivo: str) -> str:
    for estado in ("PENDING", "BLOCKED"):
        if motivo.startswith(estado + "["):
            return estado
    return "SALTO_NO_DECLARADO"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    salida = yield
    informe = salida.get_result()
    resultados = item.config.stash[_CLAVE_RESULTADOS]
    fila = resultados.setdefault(item.nodeid, {
        "prueba": item.nodeid,
        "necesita_grafo": item.get_closest_marker("necesita_grafo") is not None,
        "requiere": _marcas(item, "requiere"),
        "cubre": _marcas(item, "cubre"),
        "estado": None,
        "motivo": "",
        "evidencia": "",
    })
    if informe.skipped:
        motivo = ""
        if isinstance(informe.longrepr, tuple) and len(informe.longrepr) == 3:
            motivo = str(informe.longrepr[2])
        motivo = motivo.removeprefix("Skipped: ")
        fila["estado"] = _estado_de_salto(motivo)
        fila["motivo"] = motivo
    elif informe.failed:
        fila["estado"] = "FAIL"
        crash = getattr(informe.longrepr, "reprcrash", None)
        mensaje = crash.message if crash is not None else str(informe.longrepr).strip().splitlines()[-1]
        fila["motivo"] = f"fallo en la fase «{informe.when}»: " + " ".join(mensaje.split())[:600]
    elif informe.when == "call" and fila["estado"] is None:
        fila["estado"] = "PASS"
    directorio = getattr(item, "_rc_nav_evidencia", None)
    if directorio is not None:
        fila["evidencia"] = str(directorio)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    cfg = session.config.stash.get(_CLAVE_CONFIG, None)
    if cfg is None:
        return
    redactor = session.config.stash[_CLAVE_REDACTOR]
    resultados = session.config.stash[_CLAVE_RESULTADOS]
    filas = [resultados[k] for k in sorted(resultados)]
    recuento: dict[str, int] = {}
    for fila in filas:
        recuento[fila["estado"] or "SIN_ESTADO"] = recuento.get(fila["estado"] or "SIN_ESTADO", 0) + 1
    fugas = redactor.fugas(cfg.salida)
    # El motivo de un fallo puede citar texto de la página: se redacta también.
    for fila in filas:
        fila["motivo"] = redactor.texto(fila["motivo"])
    resumen = {
        "generado_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "capacidades_declaradas": sorted(cfg.capacidades),
        "recuento": recuento,
        "fugas_de_secretos": fugas,
        "pruebas": filas,
    }
    (cfg.salida / "resultado.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lineas = ["| Prueba | Neo4j | Estado | Cubre | Motivo |", "|---|---|---|---|---|"]
    for fila in filas:
        lineas.append("| `{}` | {} | {} | {} | {} |".format(
            fila["prueba"], "sí" if fila["necesita_grafo"] else "no", fila["estado"],
            ", ".join(fila["cubre"]), fila["motivo"].replace("|", "/")[:200],
        ))
    (cfg.salida / "resultado.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    informe = session.config.pluginmanager.get_plugin("terminalreporter")
    if informe is not None:
        informe.write_sep("=", "batería de navegador: resultado declarado")
        informe.write_line("RECUENTO " + " ".join(f"{k}={v}" for k, v in sorted(recuento.items())))
        informe.write_line(f"FUGAS_DE_SECRETOS={len(fugas)}")
        for fuga in fugas:
            informe.write_line(f"  FUGA: {fuga}")
    # Un salto que no declara PENDING/BLOCKED, o un secreto en la evidencia,
    # ponen la tanda en rojo aunque pytest la diera por buena.
    if (recuento.get("SALTO_NO_DECLARADO") or recuento.get("SIN_ESTADO") or fugas) and session.exitstatus == 0:
        session.exitstatus = 1


# ---------------------------------------------------------------------------
# Fixtures de sesión
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def cfg(pytestconfig: pytest.Config) -> Config:
    return pytestconfig.stash[_CLAVE_CONFIG]


@pytest.fixture(scope="session")
def redactor(pytestconfig: pytest.Config) -> Redactor:
    return pytestconfig.stash[_CLAVE_REDACTOR]


@pytest.fixture(scope="session")
def tls(cfg: Config) -> dict:
    """Cadena verificada con la CA declarada. Si no verifica, no se navega."""
    datos = verificar_tls(cfg)
    (cfg.salida / "tls.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return datos


@pytest.fixture(scope="session")
def playwright_sesion(cfg: Config):
    # El cliente HTTP del propio Playwright (no el navegador) confía en la CA
    # declarada de forma estricta, igual que la verificación previa.
    os.environ["NODE_EXTRA_CA_CERTS"] = str(cfg.ca_file)
    with sync_playwright() as p:
        yield p


def argumentos_de_chromium(tls: dict) -> list[str]:
    """Chromium acepta la cadena cuya clave se verificó con la CA, y sólo ésa."""
    return ["--ignore-certificate-errors-spki-list=" + ",".join(tls["spki_sha256"])]


@pytest.fixture(scope="session")
def navegador(playwright_sesion, tls: dict) -> Iterator[Browser]:
    """UN Chromium headless para toda la tanda (una instancia, un worker)."""
    b = playwright_sesion.chromium.launch(args=argumentos_de_chromium(tls))
    try:
        yield b
    finally:
        b.close()


@pytest.fixture(scope="session")
def estados_de_sesion(navegador: Browser, cfg: Config, redactor: Redactor) -> Callable[[str], dict]:
    """Inicia sesión UNA vez por cuenta compartida y reutiliza sus cookies.

    El producto revoca las sesiones anteriores de un usuario en cada inicio de
    sesión, así que volver a entrar con ``admin`` a mitad de tanda tumbaría la
    sesión de las pruebas que ya la estaban usando.
    """
    cache: dict[str, dict] = {}

    def _estado(clave: str) -> dict:
        if clave not in cache:
            ctx = navegador.new_context(viewport=VENTANA)
            try:
                pagina = ctx.new_page()
                respuesta = iniciar_sesion(pagina, cfg, cfg.cuenta(clave))
                if respuesta.status != 302 or "/login" in pagina.url:
                    raise AssertionError(
                        f"PREPARACIÓN: la cuenta «{clave}» no pudo iniciar sesión "
                        f"(POST /login -> {respuesta.status}, acabó en {soporte.ruta_de(pagina)})"
                    )
                redactor.registrar_cookies(ctx.cookies())
                cache[clave] = ctx.storage_state()
            finally:
                ctx.close()
        return cache[clave]

    return _estado


# ---------------------------------------------------------------------------
# Fixtures por prueba
# ---------------------------------------------------------------------------

@pytest.fixture()
def evidencia(request: pytest.FixtureRequest, cfg: Config, redactor: Redactor) -> Evidencia:
    modulo = Path(request.node.fspath).stem
    nombre = request.node.name.replace("[", "-").replace("]", "").replace("/", "_")
    directorio = cfg.salida / modulo / nombre
    request.node._rc_nav_evidencia = directorio
    return Evidencia(directorio, redactor)


@pytest.fixture()
def contexto(navegador: Browser, cfg: Config, redactor: Redactor,
             evidencia: Evidencia) -> Iterator[Callable[..., BrowserContext]]:
    """Fábrica de contextos aislados (cookies separadas), con traza redactada."""
    abiertos: list[tuple[str, BrowserContext]] = []

    def _nuevo(nombre: str = "principal", *, estado: Optional[dict] = None,
               navegador_alternativo: Optional[Browser] = None) -> BrowserContext:
        ctx = (navegador_alternativo or navegador).new_context(viewport=VENTANA, storage_state=estado)
        ctx.set_default_timeout(20_000)
        ctx.on("response", lambda r: redactor.registrar_set_cookie(r.headers.get("set-cookie")))
        ctx.tracing.start(screenshots=True, snapshots=True, sources=False)
        abiertos.append((nombre, ctx))
        return ctx

    try:
        yield _nuevo
    finally:
        for nombre, ctx in abiertos:
            try:
                redactor.registrar_cookies(ctx.cookies())
                with tempfile.TemporaryDirectory(dir=str(cfg.salida)) as tmp:
                    cruda = Path(tmp) / "traza.zip"
                    ctx.tracing.stop(path=str(cruda))
                    redactor.zip(cruda, evidencia.directorio / f"traza-{nombre}.zip")
            finally:
                ctx.close()


def _con_registradores(pagina: Page) -> Page:
    pagina.errores_de_consola = []     # type: ignore[attr-defined]
    pagina.errores_de_pagina = []      # type: ignore[attr-defined]

    def _consola(msg):
        if msg.type != "error":
            return
        url = (msg.location or {}).get("url", "") if isinstance(msg.location, dict) else ""
        pagina.errores_de_consola.append({"texto": msg.text or "", "url": url})  # type: ignore[attr-defined]

    pagina.on("console", _consola)
    pagina.on("pageerror", lambda exc: pagina.errores_de_pagina.append(str(exc)))  # type: ignore[attr-defined]
    return pagina


@pytest.fixture()
def pagina_anonima(contexto) -> Page:
    """Una página sin ninguna cookie: un navegador recién abierto."""
    return _con_registradores(contexto("anonimo").new_page())


@pytest.fixture()
def pagina_como(contexto, estados_de_sesion) -> Callable[[str], Page]:
    """Página con la sesión compartida de una cuenta (admin, revisor, lector…)."""

    def _pagina(clave: str) -> Page:
        return _con_registradores(contexto(clave, estado=estados_de_sesion(clave)).new_page())

    return _pagina
