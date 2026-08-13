"""Hueco F del chasis — Panel de Fuentes, SOLO LECTURA.

FRONTERA DURA: aquí no hay ningún método que no sea GET, y ninguna llamada al
proveedor que no sea de lectura. Esta pantalla dice QUÉ fuentes hay en el
ámbito del lector, CUÁNTAS entidades visibles aporta cada una, EN QUÉ estado de
revisión están y DE QUÉ procedencia (`source_kind`) vienen. No sube nada, no
reingesta, no reprocesa, no borra y no marca nada como revisado. La tentación
en un panel de fuentes es justo la contraria; por eso la ausencia de escritura
se comprueba por ENUMERACIÓN del espacio de URL y por REGISTRO de los métodos
del proveedor que se invocan, no se promete en prosa.

MONTAJE
-------
Contrato publicado del chasis (``app/chassis.py``, docs/69): prefijo
``/panel/sources``, ruta raíz ``chassis_sources``, rol mínimo el declarado allí,
plantilla ``chassis/sources.html``. La guarda (``slot_guard``), el interruptor
(``slot_enabled``) y el contexto mínimo de plantilla (``slot_context``) se
importan de ``chassis_slot``: no se reescribe ninguno. Lo que sí se declara
aquí es un ``APIRouter`` propio, porque el hueco añade una ficha de fuente que
``build_slot_router`` no contempla.

DE DÓNDE SALE CADA DATO
-----------------------
De UNA sola llamada autorizada: ``provider.list_entities(workspace)`` sobre el
proveedor de ``get_filtered_provider``, es decir sobre ``PolicyFilteredProvider``,
que aplica la política ANTES de entregar nada. Todo lo que esta pantalla
agrega —número de fuentes, entidades por fuente, reparto por estado de revisión,
reparto por tipo, procedencia— se calcula DESPUÉS de la autorización, sobre el
conjunto ya filtrado. No hay ni un contador que se saque del proveedor sin
filtrar: un total que incluya lo que el espectador no puede ver es una fuga por
diferencia, y la pantalla la publicaría en la primera línea.

Por qué ``list_entities`` y no ``list_sources``: el ``list_sources`` filtrado
sólo devuelve ``source_id`` y un recuento —pierde ``source_kind`` y el estado de
revisión, que son justo "procedencia" y "estado"—, y ``source_detail`` filtrado
tampoco los trae. Pedir esos campos al proveedor SIN filtrar los recuperaría a
costa de contar lo invisible, que es exactamente lo que no se hace. Se agrega
aquí, sobre lo visible, y se declara que eso es lo que se está contando.

NOMBRES DE FICHERO Y RUTAS DE ORIGEN
------------------------------------
El identificador de una fuente suele ser un nombre de fichero, y a veces una
ruta del servidor. Eso es dato sensible: publica dónde vive el material y cómo
se llama el árbol de directorios de la máquina. Aquí NO sale del servidor:

  * la pantalla pinta sólo el ÚLTIMO segmento del identificador y marca la fila
    con ``data-path-redacted`` cuando ha recortado algo;
  * el enlace a la ficha usa un ASA opaca (``sha256`` truncado), no el
    identificador: así la ruta tampoco viaja en la URL, ni queda en el
    historial del navegador, ni en los logs de acceso de un proxy;
  * el diccionario que llega a la plantilla NO CONTIENE el identificador
    crudo por construcción (``_publicar`` lo retira), así que no hay forma de
    imprimirlo por descuido desde Jinja.

AUTORIZACIÓN
------------
Ni una regla nueva. La puerta es ``slot_guard(SLOT)`` —la misma que sirve el
hueco vacío— y los datos vienen de ``get_filtered_provider``, el mismo punto de
inyección que usan ``/sources`` y ``/api/sources``. Nótese que sustituir
``get_visibility_context`` en un test es INERTE (se llama como función normal
desde ``get_filtered_provider``): quien quiera controlar el ámbito de esta
pantalla tiene que sustituir ``get_filtered_provider`` o el proveedor base, y la
suite lo hace con un control de colapso.

Con la autenticación desactivada no hay principal, así que el contexto es
anónimo de mínimo privilegio (docs/75): se ve la capa juego compartida del
workspace por defecto y NADA de ninguna partida. Un panel vacío en ese banco es
el resultado CORRECTO, no una pantalla que arreglar. Un test lo fija en las dos
direcciones para que revertirlo se ponga rojo.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import review_status_contract
from app.authz.dependencies import get_filtered_provider
from app.chassis import FEATURE_SLOTS, slot_enabled
from app.config import get_settings
# Importado de producción, no copiado: es el mismo "sin tope" que usa el
# proveedor filtrado por dentro, así que pedir el conjunto entero no añade una
# pasada nueva. Una constante local haría divergir el tope EN SILENCIO
# (docs/73).
from app.graph_view import SIN_TOPE
from app.labels import entity_type_label, review_status_label
from app.providers.base import GraphProvider
from app.routers.chassis_slot import slot_context, slot_guard

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SLOT = next(s for s in FEATURE_SLOTS if s.key == "F")

#: Plantilla de la ficha. La del listado es la del contrato (``SLOT.template``).
ITEM_TEMPLATE = "chassis/sources_ficha.html"

#: Nombre de la ruta de ficha. NO entra en ``NAV``: se llega desde el listado.
ITEM_ROUTE_NAME = "chassis_sources_item"

#: Longitud (en caracteres hex) del asa opaca de una fuente. 16 hex = 64 bits:
#: de sobra para no colisionar con los pocos miles de fuentes de un workspace, y
#: no reversible.
LONGITUD_ASA = 16

#: Cubo de las entidades cuyo identificador de fuente NO se puede leer. Es una
#: AUSENCIA DECLARADA, no un cero y no una fuente llamada así: si diez entidades
#: no dicen de dónde vienen, la pantalla lo dice en vez de perderlas por el
#: camino (que es como un recuento acaba siendo menor que la realidad sin que
#: nadie se entere). Nunca se imprime: la plantilla pinta su etiqueta.
SIN_FUENTE = "\x00<sin-fuente-declarada>"

#: Texto único para "aquí no hay dato". Se usa igual en el listado y en la
#: ficha para que no haya dos formas de decir lo mismo.
NO_DISPONIBLE = "no disponible"

router = APIRouter(prefix=SLOT.prefix, tags=[f"chassis-{SLOT.key.lower()}"])


# ---------------------------------------------------------------------------
# Identidad publicable de una fuente: asa opaca + etiqueta recortada
# ---------------------------------------------------------------------------

def asa_de(source_id: str) -> str:
    """Asa opaca y estable de una fuente.

    Se deriva del identificador, así que es estable entre peticiones sin
    guardar estado en ninguna parte, y no es reversible: publicarla no publica
    la ruta. Es lo que viaja en la URL de la ficha.
    """
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:LONGITUD_ASA]


def etiqueta_de(source_id: str) -> tuple[str, bool]:
    """``(nombre para pintar, se recortó algo)``.

    Se queda con el último segmento, tratando ``/`` y ``\\`` por igual: un
    identificador escrito en una máquina Windows no puede escaparse de la
    redacción sólo por usar el otro separador. Si tras el recorte no queda
    nada legible se dice que no hay nombre, en vez de pintar la ruta entera
    "porque el nombre estaba vacío", que es el degradado permisivo.
    """
    normalizado = source_id.replace("\\", "/")
    nombre = normalizado.rsplit("/", 1)[-1].strip()
    recortado = nombre != source_id
    if not nombre:
        return "(nombre de fuente no legible)", True
    return nombre, recortado


# ---------------------------------------------------------------------------
# Agregación: TODO se cuenta sobre lo que la política ya dejó pasar
# ---------------------------------------------------------------------------

def _texto(valor: Any) -> Optional[str]:
    """El valor si es una cadena con contenido; ``None`` si no.

    Un ``0``, una lista o un ``None`` son AUSENCIA de dato, no un valor a
    agrupar: usarlos como clave de un contador produce grupos que no significan
    nada (y, con una lista, un ``unhashable type`` que tumba la pantalla
    entera — el defecto que ya se corrigió en ``quality_metrics``).
    """
    return valor if isinstance(valor, str) and valor.strip() else None


def clave_de_fuente(nodo: dict[str, Any]) -> str:
    """Identificador de fuente de una entidad, o el cubo de ausencia.

    Se exige CADENA: un ``source_document`` que llegue como número o como lista
    no es un identificador legible, y tratarlo como tal produciría una "fuente"
    inventada. Va al cubo declarado.
    """
    for campo in ("source_document", "source_id"):
        texto = _texto(nodo.get(campo))
        if texto is not None:
            return texto
    return SIN_FUENTE


def _sumar(contador: dict[Optional[str], int], clave: Optional[str]) -> None:
    contador[clave] = contador.get(clave, 0) + 1


def _reparto_de_estados(contador: dict[Optional[str], int]) -> list[dict[str, Any]]:
    """Reparto por ``review_status``, con FALLO CERRADO en lo desconocido.

    Tres casos distinguibles, y ninguno se funde con otro:
      * canónico  -> etiqueta en español, ``conocido=True``;
      * fuera del vocabulario -> "no reconocido (x)", ``conocido=False``. Un
        estado que este visor no conoce NO se pinta con el aspecto de un estado
        legítimo, y menos aún agregado y contado como si lo fuera;
      * ausente   -> "no declarado", ``conocido=False``. Ausencia no es cero ni
        es "pendiente".
    """
    filas: list[dict[str, Any]] = []
    for clave, cuenta in sorted(
        contador.items(), key=lambda kv: (-kv[1], kv[0] or "")
    ):
        if clave is None:
            filas.append({"clave": None, "etiqueta": "no declarado",
                          "conocido": False, "count": cuenta})
            continue
        try:
            conocido = bool(review_status_contract.is_canonical(clave))
        except Exception:
            # Un valor que ni se puede evaluar contra el contrato es, con más
            # motivo, desconocido.
            conocido = False
        filas.append({"clave": clave, "etiqueta": review_status_label(clave),
                      "conocido": conocido, "count": cuenta})
    return filas


def _reparto_simple(contador: dict[Optional[str], int],
                    etiquetar) -> list[dict[str, Any]]:
    return [
        {"clave": clave, "count": cuenta,
         "etiqueta": etiquetar(clave) if clave is not None else NO_DISPONIBLE}
        for clave, cuenta in sorted(contador.items(), key=lambda kv: (-kv[1], kv[0] or ""))
    ]


def _publicar(clave: str, acumulado: dict[str, Any]) -> dict[str, Any]:
    """Convierte un acumulado interno en la fila que ve la plantilla.

    Aquí es donde el identificador crudo DEJA DE EXISTIR: la fila publicada
    lleva asa y etiqueta, nunca la ruta. Que la plantilla no pueda imprimir lo
    que no tiene es más fuerte que acordarse de no imprimirlo.
    """
    sin_fuente = clave == SIN_FUENTE
    if sin_fuente:
        etiqueta, recortado = "sin fuente declarada", False
    else:
        etiqueta, recortado = etiqueta_de(clave)
    return {
        "handle": asa_de(clave),
        "etiqueta": etiqueta,
        "ruta_oculta": recortado,
        "sin_fuente": sin_fuente,
        "entity_count": acumulado["entity_count"],
        "procedencias": _reparto_simple(acumulado["kinds"], lambda k: k),
        "estados": _reparto_de_estados(acumulado["estados"]),
        "tipos": _reparto_simple(acumulado["tipos"], entity_type_label),
    }


def agregar_fuentes(entidades: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa por fuente las entidades YA AUTORIZADAS que se reciben.

    Esta función no conoce la política ni el proveedor: recibe el conjunto
    visible y cuenta. El acotado se hizo aguas arriba, una sola vez, en
    ``PolicyFilteredProvider``. Filtrar otra vez aquí sería una segunda
    autorización, y la segunda siempre acaba discrepando de la primera.
    """
    acumulado: dict[str, dict[str, Any]] = {}
    for nodo in entidades:
        if not isinstance(nodo, dict):
            continue
        clave = clave_de_fuente(nodo)
        fila = acumulado.setdefault(
            clave, {"entity_count": 0, "kinds": {}, "estados": {}, "tipos": {}}
        )
        fila["entity_count"] += 1
        _sumar(fila["kinds"], _texto(nodo.get("source_kind")))
        _sumar(fila["estados"], _texto(nodo.get("review_status")))
        _sumar(fila["tipos"], _texto(nodo.get("type")) or _texto(nodo.get("entity_type")))
    filas = [_publicar(clave, datos) for clave, datos in acumulado.items()]
    # Las fuentes con nombre primero (más entidades arriba); el cubo de
    # ausencia al final, para que no se lea como "la fuente más grande".
    filas.sort(key=lambda f: (f["sin_fuente"], -f["entity_count"], f["etiqueta"]))
    return filas


# ---------------------------------------------------------------------------
# Puerta, interruptor y carga
# ---------------------------------------------------------------------------

def _autorizar(user):
    """Puerta + interruptor, EN ESE ORDEN, igual que el hueco vacío.

    El orden no es cosmético: si el interruptor se evaluara antes, un anónimo
    podría enumerar qué paneles están encendidos comparando 404 contra 302.
    """
    if isinstance(user, (RedirectResponse, HTMLResponse)):
        return user
    if not slot_enabled(SLOT):
        raise HTTPException(status_code=404, detail=f"El panel {SLOT.title} está apagado")
    return None


def _contexto(user, **extra) -> dict:
    """Contexto de plantilla: el mínimo del chasis + lo propio del panel.

    Se construye sobre ``slot_context`` para no reinventar las claves que
    ``base.html`` espera (``auth_user`` en particular: pasarle otro nombre deja
    la barra superior en blanco sin que falle nada, y ese error ya se cometió en
    este repo).
    """
    ctx = slot_context(SLOT, user, items=extra.pop("items", None),
                       error=extra.pop("error", None))
    ctx.update(extra)
    return ctx


def _cargar(provider: GraphProvider, workspace: Optional[str]):
    """``(workspaces visibles, workspace elegido, filas)``. SÓLO LECTURA.

    Dos llamadas al proveedor y las dos de lectura: ``workspaces()`` y
    ``list_entities()``. No hay una tercera, y la suite lo comprueba
    registrando qué métodos se invocan de verdad.
    """
    workspaces = list(provider.workspaces())
    predeterminado = get_settings().S9K_DEFAULT_WORKSPACE
    if workspace:
        if workspace not in workspaces:
            # Workspace inexistente y workspace fuera de ámbito dan el MISMO
            # 404: distinguirlos convertiría la pantalla en un enumerador de
            # workspaces ajenos.
            raise HTTPException(status_code=404, detail="Workspace no encontrado")
        elegido: Optional[str] = workspace
    elif predeterminado in workspaces:
        elegido = predeterminado
    elif len(workspaces) == 1:
        elegido = workspaces[0]
    else:
        elegido = None
    if elegido is None:
        return workspaces, None, []
    entidades, _total = provider.list_entities(elegido, limit=SIN_TOPE, offset=0)
    return workspaces, elegido, agregar_fuentes(entidades)


def _pantalla_de_error(request: Request, user, exc: Exception):
    """503 sin fuga: el NOMBRE del tipo, nunca el mensaje ni la ruta.

    ``str(exc)`` de un fallo de E/S trae la ruta del fichero que no se pudo
    abrir; el de un fallo de driver trae el URI del servidor. Ninguno de los
    dos se publica.
    """
    return templates.TemplateResponse(
        request, SLOT.template,
        _contexto(
            user,
            error="No se pudieron leer las fuentes: la fuente de datos no está disponible.",
            error_detail=type(exc).__name__,
            sources=[], workspaces=[], workspace=None,
        ),
        status_code=503,
    )


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name=SLOT.route_name)
@router.get("/", response_class=HTMLResponse, name=SLOT.route_name)
def chassis_sources(
    request: Request,
    workspace: Optional[str] = Query(default=None),
    user=Depends(slot_guard(SLOT)),
    provider: GraphProvider = Depends(get_filtered_provider),
):
    """Listado de fuentes visibles del workspace elegido."""
    denegado = _autorizar(user)
    if denegado is not None:
        return denegado
    try:
        workspaces, elegido, filas = _cargar(provider, workspace)
    except HTTPException:
        # El 404 de workspace es una decisión, no un fallo: no se degrada a la
        # pantalla de error.
        raise
    except Exception as exc:  # noqa: BLE001 - el tipo se publica, el mensaje no
        return _pantalla_de_error(request, user, exc)
    return templates.TemplateResponse(
        request, SLOT.template,
        _contexto(user, items=filas, sources=filas,
                  workspaces=workspaces, workspace=elegido),
    )


@router.get("/ficha/{handle}", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)
def chassis_sources_item(
    request: Request,
    handle: str,
    workspace: Optional[str] = Query(default=None),
    user=Depends(slot_guard(SLOT)),
    provider: GraphProvider = Depends(get_filtered_provider),
):
    """Ficha de UNA fuente: procedencia y estado, sobre lo visible.

    La ficha se busca en el MISMO agregado que produjo el listado, así que
    enseña exactamente lo que la fila decía. No se vuelve a consultar por
    identificador por un camino distinto, que es como listado y ficha acaban
    discrepando — y, aquí, como un identificador fuera de ámbito acabaría
    resolviéndose por la puerta de atrás.
    """
    denegado = _autorizar(user)
    if denegado is not None:
        return denegado
    try:
        workspaces, elegido, filas = _cargar(provider, workspace)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return _pantalla_de_error(request, user, exc)
    fila = next((f for f in filas if f["handle"] == handle), None)
    if fila is None:
        # INEXISTENTE y FUERA DE ÁMBITO dan el mismo 404 con el mismo cuerpo,
        # y lo dan por construcción: la resolución del asa sólo mira el
        # agregado autorizado, así que aquí no hay forma de saber si la fuente
        # existe para otro. Un 403 diría "existe pero no es tuya", que es justo
        # el dato que no se entrega.
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    return templates.TemplateResponse(
        request, ITEM_TEMPLATE,
        _contexto(user, items=[fila], source=fila, sources=filas,
                  workspaces=workspaces, workspace=elegido),
    )
