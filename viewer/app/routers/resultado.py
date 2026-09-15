# -*- coding: utf-8 -*-
"""Pantallas de RESULTADO de una ejecucion y su PROCEDENCIA. SOLO LECTURA.

FRONTERA DURA: aqui no hay ningun metodo que no sea ``GET``. Este router no
decide, no aplica, no revierte y no reinterpreta la procedencia: ensena lo que
el writer ya escribio, filtrado por la autorizacion que ya existia. La ausencia
de escritura no se promete en prosa, se comprueba por ENUMERACION del espacio
de URL del prefijo en la suite.

POR QUE NO ES UN HUECO DEL CHASIS
---------------------------------
``app/chassis.py`` declara CUATRO huecos (C/B/F/G) y ese contrato --con su
suite, ``test_chassis_mount_contract.py``-- es de otro carril. Anadir un quinto
hueco tocaria las dos cosas. Este router se monta como ``readonly`` y
``review-console``: directamente en ``main``, con su propio prefijo, su propia
guarda YA EXISTENTE y su propio interruptor. No introduce una consola nueva:
son fichas de detalle a las que se llega desde un identificador de ejecucion.

PREFIJO: ``/panel/resultado``. Libre de colisiones --los cuatro huecos son
``/panel/{review,operations,sources,entities}`` y ninguna ruta dinamica
preexistente captura ``/panel/*``--.

AUTORIZACION: ni una regla nueva.

* ROL: ``html_role_guard("reviewer")``, la misma guarda y el mismo rol que
  ``/sources`` y ``/panel/sources``. No se compara ningun rol en este modulo.
* CONTENIDO: ``get_filtered_provider``, el mismo ``PolicyFilteredProvider``
  que sirve ``/entities``. El servicio le pregunta por identidad durable y no
  vuelve a filtrar en ninguna parte: filtrar dos veces en dos sitios es como
  acaban discrepando.

Un recurso no autorizado es INDISTINGUIBLE de uno inexistente: el servicio
devuelve ``None`` en los dos casos y aqui se traduce al MISMO 404 con el MISMO
cuerpo. Un 403 diria "existe pero no es tuyo", que es justo el dato que no se
entrega.

INTERRUPTOR: ``S9K_PANEL_RESULTADO_ENABLED``, con la MISMA semantica que la de
los huecos (``FLAG_ON_VALUES``, importada y no reescrita): se sirve si y solo
si vale exactamente ``true`` o ``1``. Ausente, vacia o ininteligible -> 404.
Apagado por defecto, que es lo correcto para produccion.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.models import User
from app.authz.dependencies import get_filtered_provider
from app.chassis import FLAG_ON_VALUES
from app.config import get_settings
from app.providers.base import GraphProvider
from app.providers.provenance_reader import reader_for
from app.routers.readonly import html_role_guard
from app.services import result_provenance as servicio

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

PREFIJO = "/panel/resultado"
FLAG_ENV = "S9K_PANEL_RESULTADO_ENABLED"
RUTA_RESULTADO = "resultado_de_ejecucion"
RUTA_EVIDENCIA = "resultado_evidencia_de_hecho"

#: Cuerpo UNICO del 404. Se nombra una sola vez a proposito: la
#: indistinguibilidad entre "no existe" y "no es tuyo" se rompe el dia que
#: alguien escribe dos mensajes parecidos en dos sitios distintos.
NO_ENCONTRADO = "No hay ningun resultado con ese identificador."

router = APIRouter(prefix=PREFIJO, tags=["resultado"])


def _encendido() -> bool:
    """Interruptor, con la semantica del chasis. Fallo cerrado, se lee siempre.

    Se consulta el entorno en CADA peticion a proposito: un flag cacheado al
    importar convierte "apagar la pantalla" en "reiniciar el proceso".
    """
    raw = os.environ.get(FLAG_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in FLAG_ON_VALUES


def _exigir_encendido() -> None:
    """El interruptor, DESPUES de la puerta de rol.

    El orden no es cosmetico: si el interruptor se evaluara antes, un anonimo
    podria averiguar si la pantalla esta encendida comparando 404 contra 302.
    """
    if not _encendido():
        raise HTTPException(status_code=404, detail=NO_ENCONTRADO)


def _contexto(user, **extra) -> dict:
    """Contexto de plantilla. ``auth_user`` con ese nombre EXACTO: ``base.html``
    pinta la barra superior con el, y otro nombre la deja en blanco sin que
    falle nada --ese error ya se cometio en este repo--."""
    ctx = {"auth_user": user if isinstance(user, User) else None}
    ctx.update(extra)
    return ctx


@router.get("/{apply_id}", response_class=HTMLResponse, name=RUTA_RESULTADO)
def resultado_de_ejecucion(
    request: Request,
    apply_id: str,
    workspace: Optional[str] = Query(default=None),
    user=Depends(html_role_guard("reviewer")),
    provider: GraphProvider = Depends(get_filtered_provider),
):
    """Que cambio ESA ejecucion: entidades, relaciones y hechos VISIBLES.

    El ``apply_id`` de la URL es la identidad durable del apply
    (``apply:<32hex>``, derivada de workspace+ambito+snapshot+plan_hash). No es
    una posicion, ni un nombre de fichero, ni un ``elementId``.
    """
    # `html_role_guard` es un guardian PASIVO: no deniega por si solo, DEVUELVE
    # la respuesta de denegacion y es el handler quien tiene que devolverla. Si
    # esto no estuviera, la ruta declararia guardian y serviria 200 a un
    # anonimo. Va escrito AQUI, a la vista de la ruta, y no delegado a un
    # ayudante: el censo de rutas (`scripts/route_map`) comprueba por AST que
    # el handler devuelve la salida de SU parametro de guardia, y un ayudante
    # lo esconde -- que es, de hecho, como los cuatro huecos del chasis se
    # libran hoy de esta comprobacion (deuda anotada, no arreglada aqui).
    if isinstance(user, (RedirectResponse, HTMLResponse)):
        return user
    _exigir_encendido()

    ws = workspace or get_settings().S9K_DEFAULT_WORKSPACE
    resultado = servicio.resultado_de_apply(
        provider=provider,
        reader=reader_for(provider),
        workspace=ws,
        apply_id=apply_id,
    )
    if resultado is None:
        raise HTTPException(status_code=404, detail=NO_ENCONTRADO)

    return templates.TemplateResponse(
        request, "resultado/resultado.html",
        _contexto(user, resultado=resultado, estados=servicio.ESTADOS),
    )


@router.get("/{apply_id}/hecho/{assertion_id}", response_class=HTMLResponse,
            name=RUTA_EVIDENCIA)
def resultado_evidencia_de_hecho(
    request: Request,
    apply_id: str,
    assertion_id: str,
    workspace: Optional[str] = Query(default=None),
    user=Depends(html_role_guard("reviewer")),
    provider: GraphProvider = Depends(get_filtered_provider),
):
    """La procedencia de UN hecho de ESE apply: evidencia literal y fuente.

    El ``apply_id`` no es decorativo en esta URL: el servicio exige que el
    hecho pertenezca a ESE apply antes de entregar nada. Sin esa comprobacion,
    la pantalla de una ejecucion ensenaria la evidencia de otra --atribucion
    cruzada-- y las dos se verian igual de bien.
    """
    # `html_role_guard` es un guardian PASIVO: no deniega por si solo, DEVUELVE
    # la respuesta de denegacion y es el handler quien tiene que devolverla. Si
    # esto no estuviera, la ruta declararia guardian y serviria 200 a un
    # anonimo. Va escrito AQUI, a la vista de la ruta, y no delegado a un
    # ayudante: el censo de rutas (`scripts/route_map`) comprueba por AST que
    # el handler devuelve la salida de SU parametro de guardia, y un ayudante
    # lo esconde -- que es, de hecho, como los cuatro huecos del chasis se
    # libran hoy de esta comprobacion (deuda anotada, no arreglada aqui).
    if isinstance(user, (RedirectResponse, HTMLResponse)):
        return user
    _exigir_encendido()

    ws = workspace or get_settings().S9K_DEFAULT_WORKSPACE
    detalle = servicio.detalle_de_asercion(
        provider=provider,
        reader=reader_for(provider),
        workspace=ws,
        apply_id=apply_id,
        assertion_id=assertion_id,
    )
    if detalle is None:
        raise HTTPException(status_code=404, detail=NO_ENCONTRADO)

    return templates.TemplateResponse(
        request, "resultado/evidencia.html",
        _contexto(user, detalle=detalle, estados=servicio.ESTADOS),
    )
