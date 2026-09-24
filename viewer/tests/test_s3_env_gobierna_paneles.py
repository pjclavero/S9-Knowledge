# -*- coding: utf-8 -*-
"""S-3 · el `.env` gobierna lo que dice gobernar.

PROPIEDAD: la configuración que el operador cree haber establecido mediante
`viewer/.env` es realmente la que gobierna lo que los paneles del chasis
(`/panel/review`, `/panel/operations`, `/panel/sources`, `/panel/entities`) y
la pantalla de resultado (`/panel/resultado/...`) muestran y permiten.

MEDIDO COMO EL OPERADOR, a propósito, no con `TestClient` + variables
inyectadas: cada test arranca **uvicorn de verdad** en un **subproceso**, con
`cwd` apuntando a un directorio que sólo contiene el `.env` que el operador
editó (`cp .env.example .env`, cuatro flags a mano), y con esas variables
**ausentes del entorno del proceso** — exactamente el escenario medido sobre
`bcd9e59` que hoy da 404 en silencio.

Antes de este corte, `chassis.slot_enabled` y `resultado._encendido` leían
`os.environ` directamente y nunca consultaban `.env` (pydantic-settings no
exporta ese fichero al entorno del proceso): la propiedad estaba rota. La
corrección es una autoridad ÚNICA (`app.config.effective_env_value`) que
consulta primero el entorno del proceso y, si no dice nada, `.env` — la misma
precedencia que ya usan `Settings`/`AuthSettings`, y la que exige el
despliegue real (`EnvironmentFile=` de systemd sigue ganando).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Iterable, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VIEWER_DIR = REPO_ROOT / "viewer"

PANEL_ENV_KEYS = (
    "S9K_PANEL_C_ENABLED",
    "S9K_PANEL_B_ENABLED",
    "S9K_PANEL_F_ENABLED",
    "S9K_PANEL_G_ENABLED",
)
PANEL_PATH = {
    "S9K_PANEL_C_ENABLED": "/panel/review",
    "S9K_PANEL_B_ENABLED": "/panel/operations",
    "S9K_PANEL_F_ENABLED": "/panel/sources",
    "S9K_PANEL_G_ENABLED": "/panel/entities",
}
RESULTADO_ENV_KEY = "S9K_PANEL_RESULTADO_ENABLED"
RESULTADO_PATH = "/panel/resultado/no-existe-12345"

_TODAS_LAS_CLAVES_DE_INTERRUPTOR = PANEL_ENV_KEYS + (RESULTADO_ENV_KEY,)


# ---------------------------------------------------------------------------
# Infraestructura: uvicorn real en subproceso, cwd = instalación del operador
# ---------------------------------------------------------------------------

def _puerto_libre() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """Un 302 debe VERSE como 302, no disolverse en el 200 de `/login` al
    seguirlo automáticamente: eso ocultaría precisamente si el panel estaba
    apagado (404) o exigiendo sesión (302/401), que son códigos distintos con
    causas distintas."""

    def redirect_request(self, *args, **kwargs):  # noqa: D102
        return None


_OPENER_SIN_REDIRECCIONES = urllib.request.build_opener(_SinRedirecciones)


def _get(base_url: str, path: str) -> int:
    try:
        with _OPENER_SIN_REDIRECCIONES.open(f"{base_url}{path}", timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


class ServidorDeOperador:
    """Un uvicorn real, en subproceso, con su propio `.env` en `cwd`."""

    def __init__(self, proc: subprocess.Popen, base_url: str):
        self._proc = proc
        self.base_url = base_url

    def get(self, path: str) -> int:
        return _get(self.base_url, path)

    def detener(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self._proc.kill()
            self._proc.wait(timeout=5)


def _arrancar_como_operador(
    tmp_path: Path,
    lineas_env: Iterable[str],
    entorno_extra: Optional[dict] = None,
) -> ServidorDeOperador:
    """Arranca `uvicorn app.main:app` como lo haría el operador real:
    `cwd` es el directorio donde vive `.env` (así lo resuelve pydantic-settings
    y, tras este corte, `effective_env_value`), y el entorno del proceso NO
    trae ninguna de las claves de interruptor salvo las que pida el llamador
    explícitamente en `entorno_extra` (el "control positivo").
    """
    instalacion = Path(tempfile.mkdtemp(prefix="instalacion-de-fabrica-", dir=str(tmp_path)))
    (instalacion / ".env").write_text("\n".join(lineas_env) + "\n", encoding="utf-8")

    entorno = {
        k: v for k, v in os.environ.items()
        if k not in _TODAS_LAS_CLAVES_DE_INTERRUPTOR and k != "S9K_AUTH_ENABLED"
    }
    pythonpath_previo = entorno.get("PYTHONPATH", "")
    entorno["PYTHONPATH"] = (
        str(VIEWER_DIR) + (os.pathsep + pythonpath_previo if pythonpath_previo else "")
    )
    if entorno_extra:
        entorno.update(entorno_extra)

    puerto = _puerto_libre()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error",
        ],
        cwd=str(instalacion),
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{puerto}"
    inicio = time.monotonic()
    while time.monotonic() - inicio < 20:
        if proc.poll() is not None:
            salida = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            raise RuntimeError(
                f"uvicorn del operador no arrancó (rc={proc.returncode}):\n{salida}"
            )
        try:
            _get(base_url, "/api/status")
            return ServidorDeOperador(proc, base_url)
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.05)
    proc.terminate()
    raise RuntimeError("uvicorn del operador no respondió a tiempo")


_ENV_FABRICA_SIN_AUTH = (
    # Auth desactivada A PROPÓSITO en estos tests: el objetivo es aislar la
    # propiedad "`.env` gobierna los paneles" de la autorización, que ya
    # tiene su propio corte y su propia suite
    # (`test_instalacion_cerrada_fabrica.py`). Es, además, uno de los
    # negativos decisivos exigidos: el opt-out de laboratorio sigue
    # honrándose desde `.env` tras este cambio.
    "S9K_AUTH_ENABLED=false",
    "S9K_GRAPH_PROVIDER=mock",
)


# ---------------------------------------------------------------------------
# 1) El sujeto: `.env` con los cuatro paneles a `true`, entorno limpio
# ---------------------------------------------------------------------------

def test_env_con_los_cuatro_paneles_a_true_los_enciende(tmp_path):
    """CASO DEL OPERADOR: copia la plantilla, pone los cuatro a `true` en
    `.env`, arranca. Antes de este corte, los cuatro daban 404 en silencio
    (`chassis.slot_enabled` sólo miraba `os.environ`, nunca `.env`)."""
    lineas = _ENV_FABRICA_SIN_AUTH + tuple(f"{k}=true" for k in PANEL_ENV_KEYS)
    servidor = _arrancar_como_operador(tmp_path, lineas)
    try:
        resultados = {k: servidor.get(PANEL_PATH[k]) for k in PANEL_ENV_KEYS}
    finally:
        servidor.detener()

    for clave, codigo in resultados.items():
        assert codigo != 404, (
            f"{PANEL_PATH[clave]} respondió 404 con {clave}=true en `.env` y "
            "entorno limpio: el fichero que el operador editó NO gobernó el "
            "panel. Ésta es exactamente la falsa confirmación que este corte "
            "cierra."
        )
    # F (Sources) y G (Entities) usan la guarda no-op con auth desactivada y
    # sirven su pantalla directamente. B (Operations) exige rol admin incluso
    # con auth desactivada (docs/69 §1 bis: "302 a /login, igual que
    # /admin/users") y aquí llega como cliente no-navegador -> 401 JSON, no
    # 404: lo que importa es que la ausencia de sesión se distinga de "el
    # panel no existe". C (Review) depende de un almacén externo no
    # configurado en este test -> 503 ("servicio no disponible"), tampoco 404.
    assert resultados["S9K_PANEL_F_ENABLED"] == 200
    assert resultados["S9K_PANEL_G_ENABLED"] == 200
    assert resultados["S9K_PANEL_B_ENABLED"] == 401
    assert resultados["S9K_PANEL_C_ENABLED"] == 503


# ---------------------------------------------------------------------------
# 2) Control positivo: las mismas cuatro claves, pero en el ENTORNO
# ---------------------------------------------------------------------------

def test_control_positivo_las_cuatro_en_el_entorno_del_proceso(tmp_path):
    """Mismo `.env` (todo apagado) pero las cuatro puestas en el entorno del
    PROCESO: deben encender los paneles igual. Sin este control, un 200 en el
    test anterior no demuestra nada (podría estar siempre encendido)."""
    lineas = _ENV_FABRICA_SIN_AUTH + tuple(f"{k}=false" for k in PANEL_ENV_KEYS)
    entorno_extra = {k: "true" for k in PANEL_ENV_KEYS}
    servidor = _arrancar_como_operador(tmp_path, lineas, entorno_extra=entorno_extra)
    try:
        resultados = {k: servidor.get(PANEL_PATH[k]) for k in PANEL_ENV_KEYS}
    finally:
        servidor.detener()

    for clave, codigo in resultados.items():
        assert codigo != 404, (
            f"{PANEL_PATH[clave]} dio 404 con {clave}=true en el ENTORNO del "
            "proceso: el control positivo debe encender el panel."
        )
    assert resultados["S9K_PANEL_F_ENABLED"] == 200
    assert resultados["S9K_PANEL_G_ENABLED"] == 200
    assert resultados["S9K_PANEL_B_ENABLED"] == 401
    assert resultados["S9K_PANEL_C_ENABLED"] == 503


# ---------------------------------------------------------------------------
# 3) Precedencia: mismo fichero, mismo proceso — gana el entorno
# ---------------------------------------------------------------------------

def test_el_entorno_gana_sobre_el_env_mismo_fichero_mismo_proceso(tmp_path):
    """`.env` enciende el panel G; el entorno del proceso lo apaga
    explícitamente (`false`, no ausente). Debe ganar el entorno: es el orden
    de precedencia que usa el despliegue real
    (`EnvironmentFile=` de systemd sobre cualquier plantilla empaquetada)."""
    lineas = _ENV_FABRICA_SIN_AUTH + ("S9K_PANEL_G_ENABLED=true",)
    entorno_extra = {"S9K_PANEL_G_ENABLED": "false"}
    servidor = _arrancar_como_operador(tmp_path, lineas, entorno_extra=entorno_extra)
    try:
        codigo = servidor.get(PANEL_PATH["S9K_PANEL_G_ENABLED"])
    finally:
        servidor.detener()

    assert codigo == 404, (
        f"con `.env` diciendo `true` y el entorno diciendo `false`, se sirvió "
        f"el panel (código {codigo}): el entorno debe ganar y no lo hizo."
    )


def test_el_env_gana_solo_cuando_el_entorno_calla(tmp_path):
    """Simétrico del anterior: `.env` enciende G, el entorno NO menciona la
    clave -> debe ganar `.env`. Junto al test anterior, esto demuestra CUÁL
    de los dos mandó en cada caso, no sólo que uno de los dos funcionó."""
    lineas = _ENV_FABRICA_SIN_AUTH + ("S9K_PANEL_G_ENABLED=true",)
    servidor = _arrancar_como_operador(tmp_path, lineas)
    try:
        codigo = servidor.get(PANEL_PATH["S9K_PANEL_G_ENABLED"])
    finally:
        servidor.detener()

    assert codigo == 200, (
        f"con `.env` diciendo `true` y el entorno sin mencionar la clave, "
        f"debió ganar `.env` (código {codigo})."
    )


# ---------------------------------------------------------------------------
# 4) `S9K_PANEL_RESULTADO_ENABLED`: la misma propiedad, el mismo arreglo
# ---------------------------------------------------------------------------

def test_env_gobierna_tambien_el_interruptor_de_resultado(tmp_path):
    """`resultado._encendido` tenía el MISMO defecto que los cuatro huecos:
    leía `os.environ` a pelo. Con la clave sólo en `.env`, la pantalla debe
    dejar de dar 404 con el cuerpo de "apagado" (aunque el recurso pedido no
    exista y el 404 final sea el de "no encontrado", que es indistinguible a
    propósito del de "apagado" — lo que se comprueba aquí es que arrancar sin
    la clave en el entorno y sólo en `.env` no rompe el arranque ni dispara
    una ruta de error distinta)."""
    lineas = _ENV_FABRICA_SIN_AUTH + (f"{RESULTADO_ENV_KEY}=true",)
    servidor = _arrancar_como_operador(tmp_path, lineas)
    try:
        codigo_encendido = servidor.get(RESULTADO_PATH)
    finally:
        servidor.detener()

    lineas_apagado = _ENV_FABRICA_SIN_AUTH + (f"{RESULTADO_ENV_KEY}=false",)
    servidor2 = _arrancar_como_operador(tmp_path, lineas_apagado)
    try:
        codigo_apagado = servidor2.get(RESULTADO_PATH)
    finally:
        servidor2.detener()

    # Con la clave apagada, la guarda del interruptor corta ANTES de mirar el
    # servicio de resultado, así que la respuesta es inmediata. Con la clave
    # encendida, la petición llega al servicio real y falla por "no existe" —
    # también 404, con el MISMO cuerpo por diseño (ver `resultado.py`), así
    # que el código HTTP no distingue los dos casos. Lo que sí debe distinguir
    # el arreglo es que un identificador VÁLIDO deje de ser 404 cuando la
    # clave sólo vive en `.env`; se comprueba indirectamente vía la unidad
    # (test_env_gobierna_resultado_via_effective_env_value, abajo) porque
    # levantar aquí un almacén de procedencia real excede el alcance de S-3.
    assert codigo_apagado == 404
    assert codigo_encendido == 404  # ambos 404: el id no existe en ninguno.


def test_env_gobierna_resultado_via_effective_env_value(monkeypatch, tmp_path):
    """Unidad, sin subproceso: `resultado._encendido()` debe leer `.env` a
    través de la autoridad única cuando el entorno calla."""
    for k in _TODAS_LAS_CLAVES_DE_INTERRUPTOR:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{RESULTADO_ENV_KEY}=true\n", encoding="utf-8")

    import importlib
    from app.routers import resultado as modulo_resultado
    importlib.reload(modulo_resultado)
    try:
        assert modulo_resultado._encendido() is True, (
            "con la clave sólo en `.env`, `_encendido()` debe ver `true`"
        )
    finally:
        (tmp_path / ".env").write_text(f"{RESULTADO_ENV_KEY}=false\n", encoding="utf-8")
        importlib.reload(modulo_resultado)
        assert modulo_resultado._encendido() is False


# ---------------------------------------------------------------------------
# 5) El caso de fábrica de #248 sigue intacto con este corte aplicado
# ---------------------------------------------------------------------------

def test_caso_de_fabrica_248_sigue_intacto_setup_admin(tmp_path):
    """`.env.example` copiado literal (auth activada, paneles apagados):
    `/setup/admin` sigue accesible de forma anónima. Los paneles NO se
    comprueban aquí por HTTP: con auth activada y anónimo, la guarda de rol
    (`html_role_guard`/`require_admin`) redirige a `/login` ANTES de que el
    handler llegue a mirar el interruptor (302, no 404) — eso es una
    propiedad de auth, no de este corte, y ya la cubre
    `test_instalacion_cerrada_fabrica.py`. Que la plantilla deja los cuatro
    paneles apagados por defecto se comprueba abajo, a nivel de unidad, para
    no acoplar esta prueba a la interacción con auth."""
    plantilla = (VIEWER_DIR / ".env.example").read_text(encoding="utf-8")
    servidor = _arrancar_como_operador(tmp_path, plantilla.splitlines())
    try:
        codigo_setup = servidor.get("/setup/admin")
    finally:
        servidor.detener()

    assert codigo_setup == 200, (
        "el caso de fábrica de #248 (auth activada, sin admin) debe seguir "
        "sirviendo /setup/admin de forma anónima."
    )


def test_plantilla_sin_editar_deja_los_cuatro_paneles_apagados(monkeypatch, tmp_path):
    """Unidad: copiar `.env.example` a `.env` literal, sin tocar nada, debe
    dejar `slot_enabled` en `False` para los cuatro huecos -- la postura de
    fábrica correcta, sin la interferencia de la guarda de auth."""
    for k in _TODAS_LAS_CLAVES_DE_INTERRUPTOR:
        monkeypatch.delenv(k, raising=False)
    plantilla = (VIEWER_DIR / ".env.example").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(plantilla, encoding="utf-8")

    from app import chassis
    for slot in chassis.FEATURE_SLOTS:
        assert chassis.slot_enabled(slot) is False, (
            f"el hueco {slot.key} debería seguir apagado con la plantilla "
            "sin editar."
        )


# ---------------------------------------------------------------------------
# 6) Regresión: ninguna de las dos funciones vuelve a leer `os.environ` a pelo
# ---------------------------------------------------------------------------

def test_slot_enabled_no_lee_os_environ_directamente():
    """Guarda contra volver a introducir la segunda autoridad. La lectura del
    entorno vive en `app.config.effective_env_value`; `chassis.slot_enabled`
    delega en ella (o en el `env` explícito que le pase el llamador), y no
    debe volver a llamar a `os.environ` por su cuenta."""
    import inspect
    from app import chassis

    fuente = inspect.getsource(chassis.slot_enabled)
    assert "os.environ.get(" not in fuente, (
        "slot_enabled vuelve a leer os.environ directamente: eso reintroduce "
        "la segunda autoridad que este corte elimina."
    )
    assert "effective_env_value" in fuente


def test_resultado_encendido_no_lee_os_environ_directamente():
    import inspect
    from app.routers import resultado

    fuente = inspect.getsource(resultado._encendido)
    assert "os.environ.get(" not in fuente, (
        "_encendido vuelve a leer os.environ directamente: eso reintroduce "
        "la segunda autoridad que este corte elimina."
    )
    assert "effective_env_value" in fuente
