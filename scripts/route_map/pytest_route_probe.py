"""Sonda pytest: registra qué rutas de la app REAL se ejercitan durante los tests.

Principio: `tested` no es "el nombre de la ruta aparece en un test". Es "una
petición HTTP atravesó el objeto Route de `app.main.app` durante la corrida".

Sólo se instrumenta el objeto `app` del módulo `app.main` (la app real). Las
apps privadas que algunos tests construyen con `FastAPI()` NO se tocan, así que
ejercitar un router en una app propia de test no cuenta como cobertura.

Uso:
    PYTHONPATH=scripts S9K_ROUTE_PROBE_OUT=/ruta/tested_routes.json \
        pytest -p route_map.pytest_route_probe <targets>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SEEN: dict[str, dict] = {}
_PATCHED_APPS: set[int] = set()


def _wrap_route(route, path: str | None = None) -> None:
    if getattr(route, "_s9k_route_probe", False):
        return
    handle = getattr(route, "handle", None)
    if handle is None:
        return
    path = path or getattr(route, "path", None) or getattr(route, "path_format", "?")

    async def _handle(scope, receive, send, _orig=handle, _path=path):
        status: dict[str, int | None] = {"code": None}

        async def _send(message):
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status")
            await send(message)

        try:
            await _orig(scope, receive, _send)
        finally:
            key = f"{scope.get('method', '?')} {_path}"
            rec = _SEEN.setdefault(key, {"count": 0, "statuses": []})
            rec["count"] += 1
            code = status["code"]
            if code is not None and code not in rec["statuses"]:
                rec["statuses"].append(code)

    try:
        route.handle = _handle
        route._s9k_route_probe = True
    except Exception:  # pragma: no cover - rutas inmutables
        pass


def _patch_real_app() -> None:
    mod = sys.modules.get("app.main")
    if mod is None:
        return
    app = getattr(mod, "app", None)
    if app is None or id(app) in _PATCHED_APPS:
        return
    _PATCHED_APPS.add(id(app))
    from route_map.route_map import iter_effective_routes

    from route_map.route_map import KIND_OPACO

    for path, _methods, _dep, _endpoint, handler_route, kind, _motivo in \
            iter_effective_routes(app):
        if kind == KIND_OPACO:
            # Entrada que el censo no supo caracterizar (montaje no enumerable,
            # WebSocket, tipo desconocido): no se instrumenta, porque no se sabe
            # qué se estaría instrumentando. Sale del censo como opaca y el mapa
            # lo declara en rojo; aquí, callar sería fingir cobertura.
            continue
        # `handler_route` es el objeto Route ORIGINAL: es el que FastAPI invoca
        # (`original_route.handle`) tras resolver el include. Se etiqueta con el
        # path EFECTIVO para que la clave coincida con la del mapa.
        _wrap_route(handler_route, path)


def pytest_runtest_setup(item):  # noqa: ARG001
    _patch_real_app()


def pytest_runtest_teardown(item):  # noqa: ARG001
    _patch_real_app()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    out = os.environ.get("S9K_ROUTE_PROBE_OUT")
    if not out:
        return
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exitstatus": int(exitstatus),
        "apps_instrumented": len(_PATCHED_APPS),
        "exercised": _SEEN,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
