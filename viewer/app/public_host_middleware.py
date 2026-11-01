"""Frontera de host del visor (H-05 corte B): 400 ANTES de cualquier lógica.

Por qué no es ``starlette.middleware.trustedhost.TrustedHostMiddleware``
(comprobado por EJECUCIÓN contra la Starlette instalada, 1.3.1):

* extrae el host con ``split(":")[0]``: para ``Host: [::1]:8000`` obtiene
  ``[`` y rechaza el loopback IPv6 que el contrato exige permitir;
* compara sin normalizar: ``Public.Example`` y ``public.example.`` (punto
  final, FQDN legítimo) se rechazan;
* con ``allowed_hosts=None`` o ``"*"`` deja pasar todo (``allow_any``), y
  ``www_redirect=True`` por defecto REDIRIGE en vez de rechazar.

Aquí se conserva la forma (middleware ASGI puro, 400 ``Invalid host header``)
con la interpretación única de ``app.public_endpoint``. Sin estado global: los
hosts se resuelven en cada petición (como ``effective_env_value``, sin caché a
propósito: editar ``.env`` y reiniciar tiene que bastar), y si la resolución
falla se responde 503 sin tocar la aplicación (fail-closed por petición;
el arranque ya aborta antes: ``app.main._startup_public_endpoint``).

ORDEN: se registra el ÚLTIMO en ``app.main``, o sea el más externo
(``add_middleware`` inserta en cabeza): corre antes de ``AuthMiddleware``,
de las rutas, de la sesión, de los almacenes y de los redirects de Starlette
(``redirect_slashes``, que construye ``Location`` con el Host del cliente: O1
del revisor de A queda cerrado porque ese Host ya fue validado aquí).

COSTURA DE TESTS: ``HOSTS_EXTRA_DE_PRUEBAS`` (vacía en producción). Sólo la
fixture de tests (`viewer/tests/conftest.py`) la sustituye; un gate AST
comprueba que ningún módulo de producción la asigna ni la lee fuera de aquí.
"""
from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.public_endpoint import (
    PublicEndpointError,
    normalizar_host_cabecera,
    resolve_trusted_hosts,
)

__all__ = ["PublicHostMiddleware", "HOSTS_EXTRA_DE_PRUEBAS"]

#: Hosts EXTRA declarados por un entorno de tests (p. ej. ``testserver``).
#: Producción no los fija jamás: vacía por defecto, y la lista productiva
#: (`resolve_trusted_hosts()` sin argumentos) no la consulta.
HOSTS_EXTRA_DE_PRUEBAS: tuple = ()


async def _responder(estado: int, texto: str, scope: Scope, receive: Receive,
                     send: Send) -> None:
    await PlainTextResponse(texto, status_code=estado)(scope, receive, send)


class PublicHostMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        try:
            permitidos = resolve_trusted_hosts(extra=HOSTS_EXTRA_DE_PRUEBAS)
        except PublicEndpointError:
            await _responder(503, "Public endpoint misconfigured", scope, receive, send)
            return

        cabeceras = Headers(scope=scope).getlist("host")
        host = normalizar_host_cabecera(cabeceras[0]) if len(cabeceras) == 1 else None
        if host is not None and host in permitidos:
            await self.app(scope, receive, send)
            return
        await _responder(400, "Invalid host header", scope, receive, send)
