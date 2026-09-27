# -*- coding: utf-8 -*-
"""S-3b · el `.env` gobierna también dónde vive la bóveda.

PROPIEDAD: un operador que declara `S9K_VAULT_ROOT` (o, sin árbol de
bóvedas, `S9K_INGEST_SOURCES_DIR`) en su `.env` llega a esa bóveda: el
catálogo de fuentes de `/panel/operations` la descubre y una ingesta
solicitada contra ella se ENCOLA con el ámbito correcto, en vez de caer en
el catálogo plano de ejemplo del repositorio (`SOURCE_WORKSPACE_UNDECLARED`).

MEDIDO COMO EL OPERADOR: uvicorn real en subproceso, `cwd` = una instalación
que sólo tiene el `.env` que el operador editó, bootstrap real en
`/setup/admin` y login real en `/login` — no `TestClient` con variables
inyectadas. Mismo motor que `test_s3_env_gobierna_paneles.py` (S-3), del que
este fichero reutiliza el arranque del servidor y le añade cookies de sesión
y el flujo de bootstrap + login + POST de ingesta.

ANTES DE ESTE CORTE: `sources_catalog.raiz_de_bovedas`,
`directorio_de_fuentes`, `ubicacion_declarada` y `_exigir_montaje` leían
`os.environ` directamente (`entorno.get(...)`) y nunca consultaban `.env`:
exactamente la misma familia de defecto que S-3, aquí en el catálogo de
fuentes en vez de en los paneles del chasis.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
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
EJEMPLOS = REPO_ROOT / "examples" / "ingesta-v3"

ADMIN_USER = "admin"
ADMIN_PASS = "SuperSecreta_1234567890!"

_TEXTO_EJEMPLO = (EJEMPLOS / "nota-cofradia-de-ambar.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Infraestructura: uvicorn real en subproceso, cwd = instalación del operador
# ---------------------------------------------------------------------------

def _puerto_libre() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102
        return None


class ServidorDeOperador:
    """Un uvicorn real, en subproceso, con su propio `.env` en `cwd`, y un
    cliente HTTP con cookies (necesarias para el login real)."""

    def __init__(self, proc: subprocess.Popen, base_url: str):
        self._proc = proc
        self.base_url = base_url
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar), _SinRedirecciones,
        )

    def get(self, path: str, headers: Optional[dict] = None):
        req = urllib.request.Request(f"{self.base_url}{path}", headers=headers or {})
        try:
            with self._opener.open(req, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers or {})

    def post(self, path: str, data: dict):
        cuerpo = "&".join(
            f"{urllib.request.quote(k)}={urllib.request.quote(str(v))}"
            for k, v in data.items()
        ).encode("ascii")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=cuerpo, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._opener.open(req, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers or {})

    def bootstrap_y_login(self) -> None:
        """Flujo REAL: GET /setup/admin -> POST crea admin -> GET/POST /login."""
        _, html, _ = self.get("/setup/admin")
        csrf = _csrf_de(html)
        codigo, _, headers = self.post("/setup/admin", {
            "username": ADMIN_USER, "display_name": "Admin",
            "password": ADMIN_PASS, "password_confirm": ADMIN_PASS,
            "csrf_token": csrf,
        })
        assert codigo == 303, f"el bootstrap no se completó (código {codigo})"

        _, html2, _ = self.get("/login")
        csrf2 = _csrf_de(html2)
        codigo2, _, _ = self.post("/login", {
            "username": ADMIN_USER, "password": ADMIN_PASS,
            "csrf_token": csrf2, "next": "/",
        })
        assert codigo2 in (302, 303), f"el login no se completó (código {codigo2})"

    def csrf_de_operations(self) -> str:
        _, html, _ = self.get("/panel/operations")
        return _csrf_de(html)

    def detener(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self._proc.kill()
            self._proc.wait(timeout=5)


def _csrf_de(html: str) -> str:
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, "la pantalla no trae csrf_token: no se puede continuar el flujo"
    return m.group(1)


def _arrancar_como_operador(
    tmp_path: Path,
    lineas_env: Iterable[str],
    entorno_extra: Optional[dict] = None,
) -> ServidorDeOperador:
    """Igual que en S-3: `cwd` es el directorio donde vive `.env`, y el
    entorno del proceso NO trae ninguna de las claves de bóveda salvo las que
    pida el llamador explícitamente en `entorno_extra` (el control positivo)."""
    instalacion = Path(tempfile.mkdtemp(prefix="instalacion-boveda-", dir=str(tmp_path)))
    (instalacion / ".env").write_text("\n".join(lineas_env) + "\n", encoding="utf-8")

    claves_de_boveda = ("S9K_VAULT_ROOT", "S9K_VAULT_REQUIRE_MOUNT", "S9K_INGEST_SOURCES_DIR")
    entorno = {
        k: v for k, v in os.environ.items()
        if k not in claves_de_boveda and k != "S9K_AUTH_ENABLED"
    }
    pythonpath_previo = entorno.get("PYTHONPATH", "")
    entorno["PYTHONPATH"] = (
        str(VIEWER_DIR) + (os.pathsep + pythonpath_previo if pythonpath_previo else "")
    )
    if entorno_extra:
        entorno.update(entorno_extra)

    puerto = _puerto_libre()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error"],
        cwd=str(instalacion), env=entorno,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{puerto}"
    inicio = time.monotonic()
    servidor = ServidorDeOperador(proc, base_url)
    while time.monotonic() - inicio < 20:
        if proc.poll() is not None:
            salida = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            raise RuntimeError(f"uvicorn del operador no arrancó (rc={proc.returncode}):\n{salida}")
        try:
            servidor.get("/api/status")
            return servidor
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.05)
    proc.terminate()
    raise RuntimeError("uvicorn del operador no respondió a tiempo")


# ---------------------------------------------------------------------------
# Árboles de material: una bóveda mínima y un directorio plano declarado
# ---------------------------------------------------------------------------

def _escribir(p: Path, texto: str = _TEXTO_EJEMPLO) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


def _crear_arbol_de_bovedas(raiz: Path, workspace: str = "leyenda") -> Path:
    """Una bóveda mínima con UN juego y DOS partidas, suficiente para
    demostrar el modo bóveda (descubrimiento jerárquico real, no un mock)."""
    plantilla = json.loads((EJEMPLOS / "perfil-operador.json").read_text(encoding="utf-8"))
    juego = raiz / "l5r"
    perfil = dict(plantilla)
    perfil["workspace"] = workspace
    perfil["source_asset_id"] = f"profile:{workspace}"
    _escribir(juego / "perfil-operador.json", json.dumps(perfil, ensure_ascii=False))
    _escribir(juego / "compartido" / "manuales" / "basico.md")
    for partida in ("cofradia", "saga-sur"):
        base = juego / "partidas" / partida
        _escribir(base / "material-jugadores" / "mapa.md")
    return raiz


def _crear_directorio_plano_declarado(raiz: Path, workspace: str = "ws-cofradia") -> Path:
    """Un directorio plano (sin árbol de bóvedas) con SU PROPIO perfil, tal y
    como `directorio_de_fuentes` + el catálogo plano lo resuelven cuando el
    operador SÍ declara `S9K_INGEST_SOURCES_DIR`."""
    plantilla = json.loads((EJEMPLOS / "perfil-operador.json").read_text(encoding="utf-8"))
    perfil = dict(plantilla)
    perfil["workspace"] = workspace
    _escribir(raiz / "perfil-operador.json", json.dumps(perfil, ensure_ascii=False))
    _escribir(raiz / "nota.md")
    return raiz


def _env_fabrica(tmp_path: Path) -> tuple[str, ...]:
    """Fábrica + AISLAMIENTO: `S9K_AUTH_DB_PATH` y `S9K_JOBS_DB` propios de
    CADA test, en `tmp_path`. Sin esto, el default (una ruta ABSOLUTA dentro
    del propio repo, ver `auth/config.py:DEFAULT_AUTH_DB_PATH`) haría que el
    bootstrap del primer test dejase sellado `/setup/admin` para todos los
    siguientes — y compartiría la cola de trabajos entre pruebas."""
    return (
        "S9K_GRAPH_PROVIDER=mock",
        "S9K_SESSION_SECURE=false",
        "S9K_PANEL_B_ENABLED=true",
        f"S9K_AUTH_DB_PATH={tmp_path / 'auth.db'}",
        f"S9K_JOBS_DB={tmp_path / 'jobs.db'}",
    )


def _solicitar_ingesta(servidor: ServidorDeOperador) -> tuple[int, str]:
    """POST real de ingesta contra la primera fuente ofrecida. Devuelve
    (código, Location) — nunca sigue la redirección: lo que hay que ver es
    el `?aviso=` o el `?solicitado=` de la propia respuesta 303."""
    _, html, _ = servidor.get("/panel/operations")
    csrf = _csrf_de(html)
    opciones = re.findall(r'<option value="([^"]+)"\s+data-ambito=', html)
    assert opciones, f"el catálogo no ofreció ninguna fuente:\n{html[:2000]}"
    codigo, _, headers = servidor.post(
        "/panel/operations/ingestas",
        {"fuente": opciones[0], "csrf_token": csrf},
    )
    return codigo, headers.get("location") or headers.get("Location") or ""


# ---------------------------------------------------------------------------
# A · S9K_VAULT_ROOT SÓLO en `.env`, entorno limpio -> modo bóveda
# ---------------------------------------------------------------------------

def test_A_vault_root_solo_en_env_enciende_el_modo_boveda(tmp_path):
    raiz = _crear_arbol_de_bovedas(tmp_path / "bovedas")
    lineas = _env_fabrica(tmp_path) + (f"S9K_VAULT_ROOT={raiz}", "S9K_VAULT_REQUIRE_MOUNT=0")
    servidor = _arrancar_como_operador(tmp_path, lineas)
    try:
        servidor.bootstrap_y_login()
        codigo, location = _solicitar_ingesta(servidor)
    finally:
        servidor.detener()

    assert codigo == 303
    assert "solicitado=" in location, (
        f"con S9K_VAULT_ROOT sólo en `.env` (entorno limpio) la ingesta NO se "
        f"encoló (redirigió a {location!r}): el fichero que el operador "
        f"editó no gobernó dónde vive su bóveda — cayó en el catálogo plano "
        f"de ejemplo del repositorio."
    )


def test_A_control_positivo_mismo_valor_por_entorno_dice_lo_mismo(tmp_path):
    """Par simétrico de A: la MISMA bóveda declarada por el ENTORNO del
    proceso debe dar el mismo resultado. Sin este control, un `solicitado=`
    en el test anterior no demuestra nada por sí solo."""
    raiz = _crear_arbol_de_bovedas(tmp_path / "bovedas")
    lineas = _env_fabrica(tmp_path)
    servidor = _arrancar_como_operador(
        tmp_path, lineas,
        entorno_extra={"S9K_VAULT_ROOT": str(raiz), "S9K_VAULT_REQUIRE_MOUNT": "0"},
    )
    try:
        servidor.bootstrap_y_login()
        codigo, location = _solicitar_ingesta(servidor)
    finally:
        servidor.detener()

    assert codigo == 303
    assert "solicitado=" in location, (
        f"el control positivo (misma bóveda por ENTORNO) debía encolar "
        f"igual que por `.env`, y no lo hizo (redirigió a {location!r})."
    )


# ---------------------------------------------------------------------------
# B · S9K_INGEST_SOURCES_DIR SÓLO en `.env` -> directorio plano declarado
# ---------------------------------------------------------------------------

def test_B_ingest_sources_dir_solo_en_env_tiene_efecto(tmp_path):
    plano = _crear_directorio_plano_declarado(tmp_path / "fuentes-declaradas")
    lineas = _env_fabrica(tmp_path) + (f"S9K_INGEST_SOURCES_DIR={plano}",)
    servidor = _arrancar_como_operador(tmp_path, lineas)
    try:
        servidor.bootstrap_y_login()
        codigo, location = _solicitar_ingesta(servidor)
    finally:
        servidor.detener()

    assert codigo == 303
    assert "solicitado=" in location, (
        f"con S9K_INGEST_SOURCES_DIR sólo en `.env` -exactamente la clave "
        f"que ofrece `viewer/.env.example`- la ingesta NO se encoló "
        f"(redirigió a {location!r}): la línea de la plantilla no tuvo "
        f"ningún efecto."
    )
    assert "aviso=SOURCE_WORKSPACE_UNDECLARED" not in location


# ---------------------------------------------------------------------------
# C · Precedencia: `.env` con un valor, ENTORNO con otro -> gana el entorno
# ---------------------------------------------------------------------------

def test_C_el_entorno_gana_sobre_el_env_para_la_boveda(tmp_path):
    """`.env` declara un directorio plano SIN el material esperado (catálogo
    vacío); el entorno del proceso declara el árbol de bóvedas real. Si el
    entorno gana (como debe), el catálogo ofrece la fuente de la bóveda; si
    `.env` ganara, el catálogo saldría vacío y la ingesta no tendría nada
    que ofrecer."""
    vacio = tmp_path / "declarado-en-env-vacio"
    vacio.mkdir()
    _escribir(vacio / "perfil-operador.json", "{}")
    raiz = _crear_arbol_de_bovedas(tmp_path / "bovedas-del-entorno")

    lineas = _env_fabrica(tmp_path) + (f"S9K_INGEST_SOURCES_DIR={vacio}",)
    servidor = _arrancar_como_operador(
        tmp_path, lineas,
        entorno_extra={"S9K_VAULT_ROOT": str(raiz), "S9K_VAULT_REQUIRE_MOUNT": "0"},
    )
    try:
        servidor.bootstrap_y_login()
        codigo, location = _solicitar_ingesta(servidor)
    finally:
        servidor.detener()

    assert codigo == 303
    assert "solicitado=" in location, (
        f"con `.env` declarando un directorio plano y el ENTORNO declarando "
        f"S9K_VAULT_ROOT, debía ganar el entorno y ofrecer la bóveda real; "
        f"en vez de eso: {location!r}. El entorno no ganó."
    )


# ---------------------------------------------------------------------------
# D · Sin ninguna de las dos declarada -> comportamiento de fábrica Y el
#     aviso nombra el canal
# ---------------------------------------------------------------------------

def test_D_sin_declarar_nada_sigue_el_comportamiento_de_fabrica_y_dice_el_canal(tmp_path):
    lineas = _env_fabrica(tmp_path)
    servidor = _arrancar_como_operador(tmp_path, lineas)
    try:
        servidor.bootstrap_y_login()
        codigo, location = _solicitar_ingesta(servidor)
        assert codigo == 303
        assert "aviso=SOURCE_WORKSPACE_UNDECLARED" in location, (
            f"sin declarar ni S9K_VAULT_ROOT ni S9K_INGEST_SOURCES_DIR, se "
            f"esperaba el aviso de workspace sin declarar y se obtuvo "
            f"{location!r}."
        )
        codigo2, html2, _ = servidor.get(f"/panel/operations?aviso=SOURCE_WORKSPACE_UNDECLARED")
    finally:
        servidor.detener()

    assert codigo2 == 200
    assert "S9K_VAULT_ROOT" in html2 and "S9K_INGEST_SOURCES_DIR" in html2, (
        "el aviso en pantalla no nombra ninguna de las dos variables."
    )
    assert (".env" in html2 or "entorno" in html2.lower()), (
        "el aviso manda a declarar una variable sin decir POR QUÉ CANAL "
        "(`.env` o el entorno del proceso): el operador no sabe dónde "
        "ponerla."
    )


# ---------------------------------------------------------------------------
# GUARDAS contra la segunda autoridad, en los otros dos lectores de esta
# misma familia que la auditoría por AST encontró: `auth/db.py`
# (S9K_AUTH_DB_PATH) y `health/runner.py` (S9K_NEO4J_*, S9K_AUTH_ENABLED,
# S9K_AUTH_DB_PATH, S9K_JOBS_DB) — las cuatro están en `.env.example` como
# configurables. Mismo patrón que `test_slot_enabled_no_lee_os_environ_
# directamente` de S-3.
# ---------------------------------------------------------------------------

def test_sources_catalog_no_lee_os_environ_directamente():
    import inspect
    from app import sources_catalog

    for nombre in ("raiz_de_bovedas", "directorio_de_fuentes",
                   "ubicacion_declarada", "_exigir_montaje", "_valor_gobernado"):
        fuente = inspect.getsource(getattr(sources_catalog, nombre))
        assert "os.environ.get(" not in fuente and "= os.environ" not in fuente, (
            f"sources_catalog.{nombre} vuelve a leer os.environ "
            f"directamente: reintroduce la segunda autoridad que este corte "
            f"elimina."
        )
    assert "effective_env_value" in inspect.getsource(sources_catalog._valor_gobernado)


def test_auth_db_path_no_lee_os_environ_directamente():
    import inspect
    from app.auth import db as auth_db

    fuente = inspect.getsource(auth_db._db_path)
    assert "os.environ.get(" not in fuente, (
        "auth.db._db_path vuelve a leer os.environ directamente: un operador "
        "que declara S9K_AUTH_DB_PATH sólo en `.env` abriría una base "
        "distinta de la que ve AuthSettings."
    )
    assert "effective_env_value" in fuente


def test_health_runner_no_lee_las_claves_de_la_plantilla_por_os_environ():
    import inspect
    from app.health import runner

    fuente = inspect.getsource(runner.build_default_config)
    for clave in ("S9K_NEO4J_URI", "S9K_NEO4J_USER", "S9K_NEO4J_PASSWORD",
                  "S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_JOBS_DB"):
        assert f'os.environ.get("{clave}"' not in fuente, (
            f"health.runner.build_default_config vuelve a leer {clave} de "
            f"os.environ a pelo: el healthcheck auditaría una configuración "
            f"distinta de la que usa la app cuando el operador sólo declaró "
            f"esa clave en `.env`."
        )
    assert "effective_env_value" in inspect.getsource(runner)


def test_auth_db_path_solo_en_env_resuelve_a_esa_ruta(tmp_path, monkeypatch):
    """Unitario, directo: `_db_path()` con S9K_AUTH_DB_PATH SÓLO en `.env`
    (cwd apuntando a un directorio con ese `.env`, sin la variable en el
    entorno del proceso) debe resolver a la ruta declarada."""
    from app.auth import db as auth_db

    instalacion = tmp_path / "instalacion"
    instalacion.mkdir()
    destino = tmp_path / "auth-declarada-en-env.db"
    (instalacion / ".env").write_text(f"S9K_AUTH_DB_PATH={destino}\n", encoding="utf-8")
    monkeypatch.chdir(instalacion)
    monkeypatch.delenv("S9K_AUTH_DB_PATH", raising=False)

    ruta = auth_db._db_path()
    assert ruta == destino, (
        f"con S9K_AUTH_DB_PATH sólo en `.env`, _db_path() debía resolver a "
        f"{destino} y resolvió a {ruta}."
    )


def test_health_runner_neo4j_uri_solo_en_env_se_usa(tmp_path, monkeypatch):
    """Unitario: `build_default_config()` con S9K_NEO4J_URI SÓLO en `.env`
    debe reflejarlo, no el default de fábrica."""
    from app.health import runner

    instalacion = tmp_path / "instalacion"
    instalacion.mkdir()
    (instalacion / ".env").write_text(
        "S9K_NEO4J_URI=bolt://declarada-en-env:7687\n", encoding="utf-8",
    )
    monkeypatch.chdir(instalacion)
    monkeypatch.delenv("S9K_NEO4J_URI", raising=False)

    cfg = runner.build_default_config()
    assert cfg["neo4j"]["uri"] == "bolt://declarada-en-env:7687", (
        f"con S9K_NEO4J_URI sólo en `.env`, el healthcheck siguió viendo "
        f"{cfg['neo4j']['uri']!r}: no consultó el fichero."
    )
