#!/usr/bin/env python3
"""Smoke suite de LABORATORIO para el candidato de release.

Arranca la aplicación real en proceso (FastAPI + TestClient), con autenticación
ACTIVA, base ``auth.db`` efímera migrada por el propio código, y un grafo de
prueba, y comprueba que la superficie que un despliegue debe servir responde.

Qué NO es esto:

  - NO habla con VM105, ni con ningún host remoto, ni con Neo4j de producción.
  - NO sustituye a la verificación en el host destino: un 200 aquí no prueba
    que systemd, los permisos o el proxy estén bien allí.
  - NO es una prueba de carga ni de rendimiento.

Qué sí es: la comprobación de que este commit, con auth encendida, sirve las
páginas y APIs esperadas y —lo que de verdad importa— **no filtra datos que el
usuario no tiene autorizados**. Un smoke que solo mira códigos 200 aprobaría una
release que enseña la partida ajena a todo el mundo.

Uso:
    python3 deploy/release/smoke_lab.py            # informe + código de salida
    python3 deploy/release/smoke_lab.py --json

Códigos de salida: 0 todo pasa; 1 algún check falla; 3 fallo interno del propio
arnés (no se pudo ni ejecutar la suite).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import tempfile
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VIEWER_ROOT = REPO_ROOT / "viewer"
FIXTURE = VIEWER_ROOT / "tests" / "fixtures" / "multipartida_graph.json"
WORKSPACE = "juego:lab"


@dataclass
class Result:
    check: str
    passed: bool
    detail: str

    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] {self.check:<28} {self.detail}"


class SmokeHarnessError(RuntimeError):
    """El arnés no pudo montarse. Distinto de 'un check falló'."""


# ---------------------------------------------------------------------------
# Arnés
# ---------------------------------------------------------------------------

@contextmanager
def lab_environment():
    """Monta un entorno de laboratorio aislado y lo desmonta al salir."""
    if str(VIEWER_ROOT) not in sys.path:
        sys.path.insert(0, str(VIEWER_ROOT))

    if not FIXTURE.is_file():
        raise SmokeHarnessError(f"fixture de grafo ausente: {FIXTURE}")

    saved = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="s9k-smoke-") as tmp:
        state = Path(tmp)
        (state / "auth").mkdir()
        db_path = state / "auth" / "auth.db"

        os.environ.update({
            "S9K_AUTH_ENABLED": "true",
            "S9K_AUTH_DB_PATH": str(db_path),
            # Secreto EFÍMERO generado aquí: no procede de ningún fichero del
            # repositorio ni del host, y muere con el proceso.
            "S9K_CSRF_SECRET": secrets.token_urlsafe(48),
            "S9K_SESSION_SECURE": "false",   # el TestClient habla http://testserver
            "S9K_GRAPH_PROVIDER": os.environ.get("S9K_SMOKE_PROVIDER", "mock"),
            "S9K_SAMPLE_GRAPH_PATH": str(FIXTURE),
            "S9K_DEFAULT_WORKSPACE": WORKSPACE,
            "S9K_JOBS_DB": str(state / "jobs.db"),
        })

        try:
            # Purga de módulos 'app' de otra raíz (data-engine también define 'app').
            for name, module in list(sys.modules.items()):
                if name == "app" or name.startswith("app."):
                    file = getattr(module, "__file__", "") or ""
                    if str(VIEWER_ROOT / "app") not in str(file):
                        sys.modules.pop(name, None)

            from app.auth import db as auth_db  # noqa: PLC0415
            from app.auth.config import get_auth_settings  # noqa: PLC0415
            from app.config import get_settings  # noqa: PLC0415
            from app.deps import get_provider  # noqa: PLC0415

            for cache in (get_auth_settings, get_settings, get_provider):
                cache.cache_clear()
            auth_db.ensure_migrated(db_path)

            yield db_path
        except SmokeHarnessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SmokeHarnessError(f"no se pudo montar el laboratorio: {exc!r}") from exc
        finally:
            os.environ.clear()
            os.environ.update(saved)
            try:
                from app.auth.config import get_auth_settings
                from app.config import get_settings
                from app.deps import get_provider
                for cache in (get_auth_settings, get_settings, get_provider):
                    cache.cache_clear()
            except Exception:  # noqa: BLE001, S110 - limpieza de mejor esfuerzo
                pass


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _make_user(db_path: Path, username: str, password: str, role: str = "viewer"):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    with auth_db.get_conn(db_path) as conn:
        return auth_db.create_user(
            conn, username=username, display_name=username,
            password_hash=hash_password(password), role=role,
        )


def _logged_client(db_path: Path, user):
    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.sessions import create_session
    with auth_db.get_conn(db_path) as conn:
        token, _ = create_session(conn, user)
    client = _client()
    client.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    return client


def _entity_ids(client) -> set[str]:
    response = client.get("/api/entities?limit=1000", headers={"accept": "application/json"})
    if response.status_code != 200:
        raise AssertionError(f"/api/entities devolvió {response.status_code}")
    return {item["id"] for item in response.json()["items"]}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_app_boots(db_path: Path) -> str:
    client = _client()
    response = client.get("/", headers={"accept": "text/html"})
    if response.status_code not in (200, 302, 303, 307):
        raise AssertionError(f"la portada devolvió {response.status_code}")
    if response.status_code == 200:
        raise AssertionError("la portada respondió 200 SIN sesión: la auth no está activa")
    return f"app importada, auth activa (anónimo -> {response.status_code} al login)"


def check_login(db_path: Path) -> str:
    password = "contrasena-de-laboratorio-larga"
    _make_user(db_path, "smoke_login", password)
    client = _client()

    page = client.get("/login", headers={"accept": "text/html"})
    if page.status_code != 200:
        raise AssertionError(f"GET /login devolvió {page.status_code}")
    match = re.search(r'name="csrf_token" value="([^"]*)"', page.text)
    if not match:
        raise AssertionError("la página de login no trae csrf_token")
    csrf = match.group(1)

    bad = client.post("/login", data={"username": "smoke_login",
                                      "password": "contrasena-equivocada-xxxxx",
                                      "csrf_token": csrf})
    if bad.status_code == 302:
        raise AssertionError("una contraseña incorrecta emitió sesión")

    page = client.get("/login", headers={"accept": "text/html"})
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', page.text).group(1)
    good = client.post("/login", data={"username": "smoke_login", "password": password,
                                       "csrf_token": csrf})
    if good.status_code != 302:
        raise AssertionError(f"login correcto devolvió {good.status_code}, se esperaba 302")
    return "credenciales correctas -> 302 con sesión; incorrectas -> sin sesión"


def _page_check(db_path: Path, user_name: str, paths: list[str], role: str = "viewer") -> str:
    user = _make_user(db_path, user_name, "contrasena-de-laboratorio-larga", role=role)
    client = _logged_client(db_path, user)
    seen = []
    for path in paths:
        response = client.get(path, headers={"accept": "text/html"})
        if response.status_code >= 500:
            raise AssertionError(f"{path} devolvió {response.status_code}")
        if response.status_code in (401, 403):
            raise AssertionError(f"{path} denegado ({response.status_code}) a un usuario válido")
        seen.append(f"{path}->{response.status_code}")
    return ", ".join(seen)


def check_viewer_home(db_path: Path) -> str:
    return _page_check(db_path, "smoke_home", ["/", "/status"])


def check_graph(db_path: Path) -> str:
    return _page_check(db_path, "smoke_graph", ["/graph", "/api/graph"])


def check_entities(db_path: Path) -> str:
    user = _make_user(db_path, "smoke_entities", "contrasena-de-laboratorio-larga")
    client = _logged_client(db_path, user)
    response = client.get("/api/entities?limit=5", headers={"accept": "application/json"})
    if response.status_code != 200:
        raise AssertionError(f"/api/entities devolvió {response.status_code}")
    body = response.json()
    if "items" not in body:
        raise AssertionError("/api/entities no devuelve 'items'")
    html = client.get("/entities", headers={"accept": "text/html"})
    if html.status_code >= 400:
        raise AssertionError(f"/entities devolvió {html.status_code}")
    return f"/api/entities 200 ({len(body['items'])} items), /entities {html.status_code}"


def _reviewer_only(db_path: Path, prefix: str, paths: list[str],
                   *, grant_workspace: bool = False) -> str:
    """Rutas de reviewer+: deben servirse a un reviewer y negarse a un viewer.

    Comprobar solo que "responden" enmascararía una regresión de permisos: la
    mitad valiosa del check es la denegación.
    """
    reviewer = _make_user(db_path, f"{prefix}_rev", "contrasena-de-laboratorio-larga",
                          role="reviewer")
    viewer = _make_user(db_path, f"{prefix}_view", "contrasena-de-laboratorio-larga")

    if grant_workspace:
        # Sin concesión, el ámbito del reviewer no incluye el workspace y las
        # rutas de cola de revisión responden 404 a propósito (no confirman la
        # existencia del workspace). Para probar el camino feliz hace falta
        # concederlo explícitamente.
        from app.auth import db as auth_db
        with auth_db.get_conn(db_path) as conn:
            auth_db.grant_partida_access(conn, reviewer.id, WORKSPACE, "partida:uno",
                                         granted_by="smoke")

    rev_client = _logged_client(db_path, reviewer)
    view_client = _logged_client(db_path, viewer)

    seen = []
    for path in paths:
        allowed = rev_client.get(path, headers={"accept": "text/html"})
        if allowed.status_code >= 400:
            raise AssertionError(f"{path} devolvió {allowed.status_code} a un reviewer")
        denied = view_client.get(path, headers={"accept": "text/html"})
        if denied.status_code < 400:
            raise AssertionError(
                f"{path} devolvió {denied.status_code} a un usuario rol viewer: "
                "una ruta de reviewer+ no debe servirse a un viewer"
            )
        seen.append(f"{path}: reviewer {allowed.status_code} / viewer {denied.status_code}")
    return "; ".join(seen)


def check_sources(db_path: Path) -> str:
    return _reviewer_only(db_path, "smoke_sources", ["/sources", "/api/sources"])


def check_jobs(db_path: Path) -> str:
    return _page_check(db_path, "smoke_jobs", ["/jobs", "/api/jobs"])


def check_reviews(db_path: Path) -> str:
    """Consola de revisión + contrato observado de la cola ``/reviews``.

    HALLAZGO que este check fija por escrito: ``/reviews`` valida el nombre del
    workspace contra ``[A-Za-z0-9._-]{1,64}`` porque lo usa como componente de
    ruta bajo ``output/reviews``. El carácter ``:`` no está permitido, así que
    con la convención de nombres de multi-partida (``juego:<algo>``) la cola de
    revisión responde 404 SIEMPRE, para cualquier usuario y rol.

    Es fail-closed (no filtra nada) y hoy no afecta a producción, cuyo
    workspace es ``leyenda``. Pero convierte "renombrar el workspace a
    ``juego:*``" en un cambio que rompe ``/reviews`` en silencio. El check
    afirma exactamente eso: 404, nunca 200 y nunca 5xx.
    """
    detalle = _reviewer_only(db_path, "smoke_reviews", ["/review-console"],
                             grant_workspace=True)

    reviewer = _make_user(db_path, "smoke_reviews_cola", "contrasena-de-laboratorio-larga",
                          role="reviewer")
    response = _logged_client(db_path, reviewer).get("/reviews",
                                                     headers={"accept": "text/html"})
    if response.status_code >= 500:
        raise AssertionError(f"/reviews devolvió {response.status_code} (error de servidor)")
    if ":" in WORKSPACE:
        if response.status_code != 404:
            raise AssertionError(
                f"/reviews devolvió {response.status_code} con un workspace que "
                f"contiene ':' ({WORKSPACE}); se esperaba 404 fail-closed. "
                "Si esto cambia, revisar _reviews_dir() en viewer/app/main.py"
            )
        cola = ("/reviews: 404 con workspace 'juego:lab' — LIMITACIÓN CONOCIDA, "
                "el validador de ruta no admite ':' (fail-closed, no hay fuga)")
    else:
        if response.status_code >= 400:
            raise AssertionError(f"/reviews devolvió {response.status_code} a un reviewer")
        cola = f"/reviews: {response.status_code}"
    return f"{detalle}; {cola}"


def check_admin(db_path: Path) -> str:
    """El check de admin es de DENEGACIÓN, no solo de disponibilidad."""
    admin = _make_user(db_path, "smoke_admin", "contrasena-de-laboratorio-larga", role="admin")
    viewer = _make_user(db_path, "smoke_noadmin", "contrasena-de-laboratorio-larga")

    admin_response = _logged_client(db_path, admin).get("/admin/users",
                                                        headers={"accept": "text/html"})
    if admin_response.status_code != 200:
        raise AssertionError(f"/admin/users devolvió {admin_response.status_code} a un admin")

    viewer_response = _logged_client(db_path, viewer).get("/admin/users",
                                                          headers={"accept": "text/html"})
    if viewer_response.status_code < 400:
        raise AssertionError(
            f"/admin/users devolvió {viewer_response.status_code} a un usuario SIN rol admin"
        )
    return f"admin 200, viewer {viewer_response.status_code} (denegado)"


def check_health(db_path: Path) -> str:
    """El healthcheck debe producir un veredicto EXPLÍCITO, sea cual sea."""
    from app.health.runner import run_report

    # Solo componentes locales: sondear el visor o Neo4j desde aquí abriría
    # conexiones que esta suite no debe abrir.
    local_components = ["auth_db", "job_store", "filesystem"]
    report = run_report(only=local_components)

    if not report.components:
        raise AssertionError("el informe de salud no contiene ningún componente")
    overall = report.overall.value
    exit_code = report.exit_code()
    if exit_code not in (0, 1, 2, 3):
        raise AssertionError(f"código de salida de salud fuera de contrato: {exit_code}")
    detalle = ", ".join(f"{c.component}={c.status.value}" for c in report.components)
    return (f"veredicto explícito emitido: {overall} (exit {exit_code}) sobre "
            f"componentes locales [{detalle}]")


def check_neo4j_connectivity(db_path: Path) -> str:
    """Conectividad real solo si se pidió proveedor neo4j; si no, se declara.

    Deliberadamente NO se conecta a ningún Neo4j por defecto. Declarar "no
    verificado" es honesto; simular un OK sería exactamente el fallo que esta
    suite existe para evitar.
    """
    provider = os.environ.get("S9K_GRAPH_PROVIDER", "mock")
    if provider != "neo4j":
        return ("NO VERIFICADO en laboratorio (proveedor=mock). La conectividad "
                "Neo4j debe verificarse en el host destino con "
                "`python -m app.cli.health check`.")
    from app.deps import get_provider
    graph = get_provider()
    graph.list_entities(workspace=WORKSPACE, limit=1)
    return "sesión abierta contra el Neo4j configurado y consulta mínima servida"


def check_unauthorized_data_invisible(db_path: Path) -> str:
    """El check que convierte esto en una smoke suite de verdad.

    Con la fixture multipartida: capa juego + partida:uno + partida:dos + un
    nodo legacy sin ámbito declarado. Se comprueba, por la API y por la ficha
    individual, que:

      - sin concesión, el usuario solo ve la capa juego;
      - con concesión a una partida, nunca ve la otra;
      - el material legacy sin ámbito NO se cuela (coherente con NO APPLY: el
        grafo legacy no se migró, así que debe quedar callado, no abierto).
    """
    from app.auth import db as auth_db

    sin_acceso = _make_user(db_path, "smoke_sin_acceso", "contrasena-de-laboratorio-larga")
    con_p1 = _make_user(db_path, "smoke_partida_uno", "contrasena-de-laboratorio-larga")
    with auth_db.get_conn(db_path) as conn:
        auth_db.grant_partida_access(conn, con_p1.id, WORKSPACE, "partida:uno",
                                     granted_by="smoke")

    visible_sin = _entity_ids(_logged_client(db_path, sin_acceso))
    ajenas = {"partida1_pc_arden", "partida2_pc_bryn"}
    filtradas = visible_sin & ajenas
    if filtradas:
        raise AssertionError(
            f"un usuario SIN concesión ve entidades de partida: {sorted(filtradas)}"
        )
    if "legacy_material_sin_partida" in visible_sin:
        raise AssertionError(
            "el material legacy sin ámbito es visible: contradice el cierre por "
            "defecto y la decisión NO APPLY sobre el grafo legacy"
        )

    client_p1 = _logged_client(db_path, con_p1)
    csrf_page = client_p1.get("/entities", headers={"accept": "text/html"})
    match = re.search(r'name="csrf_token" value="([^"]*)"', csrf_page.text)
    if match:
        client_p1.post("/partida/select",
                       data={"partida_id": "partida:uno", "next": "/entities",
                             "csrf_token": match.group(1)})
    visible_p1 = _entity_ids(client_p1)
    if "partida2_pc_bryn" in visible_p1:
        raise AssertionError(
            "un usuario con acceso a partida:uno ve entidades de partida:dos"
        )

    # Segunda vía: acceso directo a la ficha, saltándose el listado.
    directo = client_p1.get("/api/entity/partida2_pc_bryn",
                            headers={"accept": "application/json"})
    if directo.status_code == 200:
        raise AssertionError(
            "la ficha directa de una entidad de partida ajena responde 200: "
            "el filtrado solo se aplica al listado"
        )

    return (f"sin concesión ve {sorted(visible_sin)}; con partida:uno no ve "
            f"partida:dos ni por listado ni por ficha directa "
            f"(/api/entity ajena -> {directo.status_code})")


CHECKS = (
    ("app_boots", check_app_boots),
    ("login", check_login),
    ("viewer_home", check_viewer_home),
    ("graph", check_graph),
    ("entities", check_entities),
    ("sources", check_sources),
    ("jobs", check_jobs),
    ("reviews", check_reviews),
    ("admin", check_admin),
    ("health", check_health),
    ("neo4j_connectivity", check_neo4j_connectivity),
    ("unauthorized_data_invisible", check_unauthorized_data_invisible),
)


def run_smoke() -> list[Result]:
    results: list[Result] = []
    with lab_environment() as db_path:
        for name, func in CHECKS:
            try:
                results.append(Result(name, True, func(db_path)))
            except AssertionError as exc:
                results.append(Result(name, False, str(exc)))
            except Exception as exc:  # noqa: BLE001
                results.append(Result(name, False, f"excepción inesperada: {exc!r}"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        results = run_smoke()
    except SmokeHarnessError as exc:
        print(f"INTERNAL: {exc}", file=sys.stderr)
        return 3
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 3

    failed = [r for r in results if not r.passed]
    if args.json:
        print(json.dumps({"passed": not failed,
                          "results": [asdict(r) for r in results]},
                         indent=2, ensure_ascii=False))
    else:
        for result in results:
            print(result.line())
        print("")
        print(f"{len(results) - len(failed)}/{len(results)} checks pasan")
        print("VEREDICTO: " + ("SMOKE OK" if not failed else "SMOKE FALLA"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
