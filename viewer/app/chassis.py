"""Chasis de montaje del visor: contrato único de routers, rutas y navegación.

PROPÓSITO
---------
Cuatro funcionalidades futuras (C=Review, B=Operations, F=Sources, G=Entities)
se van a montar sobre este visor en paralelo. Sin un contrato común cada una
inventa su prefijo, su nombre de ruta, su guarda y su enlace de menú, y los
fallos que aparecen son siempre los mismos tres:

  1. un router que se define pero nadie incluye  -> ruta muerta, silenciosa;
  2. un enlace de menú a una ruta que no existe  -> 404 que nadie ve venir;
  3. una ruta que se olvida de la autorización   -> fuga.

Este módulo declara el contrato en DATOS (``FEATURE_SLOTS`` y ``NAV``) para que
los tres fallos sean comprobables por enumeración, no por revisión ocular.

LO QUE ESTE MÓDULO **NO** HACE
------------------------------
No define autorización. No hay aquí ningún concepto de permiso nuevo: el campo
``role`` de cada entrada toma valores del vocabulario que ya existe
(``app.auth.models.ROLES``: admin > reviewer > viewer) y la decisión se delega
siempre en los métodos del propio ``User`` (``can_see_reviews``,
``can_access_admin``) y en las guardas ya escritas
(``app.auth.dependencies`` / ``app.routers.readonly.html_role_guard``).
Un chasis que reimplementa la autorización es una segunda autorización, y la
segunda siempre acaba siendo la permisiva.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

# Vocabulario de roles: se importa, no se redefine.
from app.auth.models import ROLES

__all__ = [
    "FeatureSlot",
    "NavItem",
    "FEATURE_SLOTS",
    "NAV",
    "ChassisContractError",
    "iter_mounted_routes",
    "route_index",
    "MountedRoute",
    "WRITE_METHODS",
    "METHODS_NOT_ENUMERABLE",
    "enumerable_methods",
    "write_methods",
    "is_write_capable",
    "nav_for",
    "install_nav_globals",
    "FLAG_ENV_TEMPLATE",
    "FLAG_ON_VALUES",
    "slot_flag_env",
    "slot_enabled",
    "enabled_slots",
]


class ChassisContractError(RuntimeError):
    """El chasis está mal montado. Se levanta RUIDOSAMENTE a propósito.

    Un enlace de menú que apunta a una ruta inexistente, o una plantilla que
    pide un elemento de navegación que no se puede resolver, no se degradan a
    "no pinto ese enlace": eso es exactamente el fallo silencioso que este
    módulo existe para impedir.
    """


# ---------------------------------------------------------------------------
# Contrato de montaje
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeatureSlot:
    """Hueco reservado para una funcionalidad futura.

    Fija TODO lo que un carril necesita saber para montarse sin renegociar
    nada: qué módulo exporta el router, con qué prefijo se monta, cómo se llama
    la ruta raíz, quién puede entrar, qué plantilla pinta y qué enlace de menú
    aparece.
    """

    key: str            # "C" | "B" | "F" | "G"
    title: str          # nombre humano de la funcionalidad
    module: str         # módulo Python que DEBE exportar `router`
    prefix: str         # prefijo de montaje (sin barra final)
    route_name: str     # nombre de la ruta raíz del hueco
    role: str           # rol mínimo: uno de ROLES
    template: str       # plantilla que pinta la pantalla
    nav_label: str      # texto del enlace de navegación
    nav_order: int      # posición en el menú

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ChassisContractError(
                f"slot {self.key}: rol {self.role!r} fuera de ROLES {ROLES}"
            )
        if not self.prefix.startswith("/") or self.prefix.endswith("/"):
            raise ChassisContractError(
                f"slot {self.key}: prefijo {self.prefix!r} debe empezar por '/' "
                "y no terminar en '/'"
            )


#: Los cuatro huecos. Se montan YA, vacíos: un hueco declarado pero no montado
#: es una ruta muerta, y el objetivo del chasis es que no exista ninguna. El
#: carril dueño de cada hueco sustituye el cuerpo del handler y la plantilla;
#: NO cambia prefijo, nombre de ruta ni rol sin tocar también este contrato.
#:
#: Sobre los prefijos: `/entities`, `/sources` y `/reviews` ya están ocupados
#: por el visor de solo lectura, y `/sources/panel` quedaría capturado por la
#: ruta dinámica `/sources/{source_id}`. Por eso los cuatro huecos viven bajo
#: un espacio de nombres propio `/panel/...`: es libre de colisiones por
#: construcción y el test `test_slot_prefixes_do_not_collide` lo comprueba.
FEATURE_SLOTS: tuple[FeatureSlot, ...] = (
    FeatureSlot(
        key="C", title="Review",
        module="app.routers.chassis_review",
        prefix="/panel/review", route_name="chassis_review",
        role="reviewer", template="chassis/review.html",
        nav_label="Panel · Review", nav_order=10,
    ),
    FeatureSlot(
        key="B", title="Operations",
        module="app.routers.chassis_operations",
        prefix="/panel/operations", route_name="chassis_operations",
        role="admin", template="chassis/operations.html",
        nav_label="Panel · Operaciones", nav_order=11,
    ),
    FeatureSlot(
        key="F", title="Sources",
        module="app.routers.chassis_sources",
        prefix="/panel/sources", route_name="chassis_sources",
        role="reviewer", template="chassis/sources.html",
        nav_label="Panel · Fuentes", nav_order=12,
    ),
    FeatureSlot(
        key="G", title="Entities",
        module="app.routers.chassis_entities",
        prefix="/panel/entities", route_name="chassis_entities",
        role="viewer", template="chassis/entities.html",
        nav_label="Panel · Entidades", nav_order=13,
    ),
)


# ---------------------------------------------------------------------------
# Interruptor por hueco: un panel a medio construir se apaga
# ---------------------------------------------------------------------------
# Los cuatro huecos se montan siempre (un router declarado y no montado es la
# ruta muerta que este chasis existe para impedir), pero servir su pantalla
# depende de un interruptor por hueco. Sin él no habría forma de apagar un
# panel a medio construir salvo desmontarlo, que es justo lo que rompe el
# contrato de montaje.
#
# CIERRA CERRADO, sin excepciones: el panel se sirve si y sólo si su variable
# de entorno vale exactamente uno de `FLAG_ON_VALUES`. Ausente, vacía, "false",
# "quizas" o cualquier otra cosa -> panel NO accesible. La ausencia de dato
# nunca es permiso máximo, y un valor que no se entiende es un dato ausente.
# El valor por defecto (todos apagados) es el correcto para producción: hoy los
# cuatro huecos sirven una pantalla vacía.

#: Únicos valores que ENCIENDEN un hueco (comparados en minúsculas, sin espacios).
FLAG_ON_VALUES = frozenset({"true", "1"})

#: Plantilla del nombre de la variable de entorno de cada hueco.
FLAG_ENV_TEMPLATE = "S9K_PANEL_{key}_ENABLED"


def slot_flag_env(slot: "FeatureSlot") -> str:
    """Nombre de la variable de entorno que enciende ``slot``."""
    return FLAG_ENV_TEMPLATE.format(key=slot.key.upper())


def slot_enabled(slot: "FeatureSlot", env: Optional[dict] = None) -> bool:
    """¿Está encendido este hueco? Fallo cerrado ante ausencia o valor raro.

    Se lee del entorno en CADA llamada a propósito: un flag cacheado al importar
    convierte "apagar el panel" en "reiniciar el proceso y esperar".
    """
    import os

    raw = (env if env is not None else os.environ).get(slot_flag_env(slot))
    if raw is None:
        return False
    return raw.strip().lower() in FLAG_ON_VALUES


def enabled_slots(env: Optional[dict] = None) -> tuple["FeatureSlot", ...]:
    """Los huecos encendidos ahora mismo."""
    return tuple(s for s in FEATURE_SLOTS if slot_enabled(s, env))


@dataclass(frozen=True)
class NavItem:
    """Entrada del menú. Apunta a un NOMBRE de ruta, nunca a una URL literal.

    Escribir `href="/reviews"` a mano es lo que produce enlaces rotos: nadie se
    entera cuando la ruta cambia o desaparece. Resolviendo por nombre contra las
    rutas realmente montadas, un enlace huérfano revienta.
    """

    label: str
    route_name: str
    role: Optional[str]  # None = visible para cualquiera con sesión; si no, rol mínimo
    order: int

    def __post_init__(self) -> None:
        if self.role is not None and self.role not in ROLES:
            raise ChassisContractError(
                f"nav {self.label!r}: rol {self.role!r} fuera de ROLES {ROLES}"
            )


#: Navegación completa del visor. Fuente ÚNICA: `base.html` la recorre, no
#: lleva enlaces escritos a mano.
NAV: tuple[NavItem, ...] = (
    NavItem("Inicio", "home", None, 0),
    NavItem("Entidades", "entities_page", None, 1),
    NavItem("Grafo", "graph_view", None, 2),
    NavItem("Jobs", "jobs_view", None, 3),
    NavItem("Estado", "status_view", None, 4),
    NavItem("Fuentes", "sources_page", "reviewer", 5),
    NavItem("Reviews", "reviews_view", "reviewer", 6),
    NavItem("Revisión V3", "queue", "reviewer", 7),
    NavItem("Admin", "admin_users", "admin", 20),
    NavItem("Partidas", "admin_partidas", "admin", 21),
) + tuple(
    NavItem(s.nav_label, s.route_name, s.role, s.nav_order) for s in FEATURE_SLOTS
)


# ---------------------------------------------------------------------------
# Enumeración de rutas realmente montadas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MountedRoute:
    """Una ruta interna de un ``Mount``, vista con su URL EFECTIVA.

    Starlette guarda en ``route.path`` de una sub-aplicación montada el camino
    **relativo al punto de montaje**: una sub-app montada en
    ``/panel/review/admin`` con un ``POST /aprobar`` aparece en el censo aplanado
    como ``'/aprobar'``. Cualquier consumidor que filtre por prefijo
    (``path.startswith(SLOT.prefix)``) la descarta, aunque la URL que sirve de
    verdad —``/panel/review/admin/aprobar``— sí está dentro del prefijo. Medido:
    la ruta respondía 200 y escribía en disco con la suite entera en verde.

    Este envoltorio arrastra el prefijo del ``Mount`` y expone el path compuesto,
    delegando TODO lo demás (``name``, ``methods``, ``endpoint``…) en la ruta
    real. Sólo se construye cuando hay prefijo que componer, de modo que una app
    sin ``Mount`` produce exactamente el mismo censo de antes.
    """

    route: object
    path: str

    def __getattr__(self, name: str):
        # `path` y `route` son campos: nunca llegan aquí.
        return getattr(object.__getattribute__(self, "route"), name)

    def __repr__(self) -> str:  # pragma: no cover - diagnóstico
        return f"MountedRoute({self.path!r} -> {self.route!r})"


def _join(prefix: str, path: str) -> str:
    """Compone el prefijo de montaje con el path interno de la sub-app."""
    if not prefix:
        return path
    return prefix.rstrip("/") + path


def _walk(routes: Iterable, prefix: str = "") -> Iterator:
    """Aplana el árbol de rutas de la aplicación.

    FastAPI >= 0.116 no deja las rutas incluidas colgando de ``app.routes``:
    inserta envoltorios ``_IncludedRouter`` cuyas rutas efectivas hay que pedir
    con ``effective_candidates()``. Por eso ``len(app.routes)`` (27) no es el
    censo real de rutas (68): sin aplanar, una ruta puede esconderse de
    cualquier barrido que recorra sólo el primer nivel — y el barrido de
    autorización es uno de ellos.

    CORRECCIÓN (medido en FastAPI 0.139.0 / Starlette 1.3.1): ``url_path_for``
    **sí** resuelve las rutas de un router incluido —
    ``app.url_path_for("chassis_review")`` devuelve ``/panel/review/`` y
    ``app.url_path_for("entities_page")`` devuelve ``/entities``—. Una versión
    anterior de este docstring afirmaba lo contrario; era falso. El índice
    propio se mantiene por otras dos razones, éstas sí comprobadas: (1) es el
    MISMO censo aplanado que usa el barrido de autorización, así que una ruta no
    puede estar en un censo y faltar en el otro —resolver la navegación con
    Starlette y auditar con ``_walk`` serían dos censos capaces de discrepar—; y
    (2) ``url_path_for`` devuelve la variante con barra final
    (``/panel/review/``), mientras que el canónico para un enlace es el otro.

    Se acepta cualquiera de las tres formas (envoltorio moderno, ``.routes``
    anidado, ruta suelta) para no atarse a una versión concreta.
    """
    for route in routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            # Envoltorio de router incluido: NO añade prefijo propio (FastAPI ya
            # lo resolvió dentro del path de cada APIRoute), sólo lo propaga.
            yield from _walk(candidates(), prefix)
            low = getattr(route, "effective_low_priority_routes", None)
            if callable(low):
                yield from _walk(low(), prefix)
            continue
        sub = getattr(route, "routes", None)
        if sub and not hasattr(route, "endpoint"):
            # `Mount`: sus rutas internas llevan el path RELATIVO al punto de
            # montaje. Se arrastra el prefijo para emitir la URL efectiva.
            # Cuando el montaje no expone `.routes` (una app ASGI opaca, p.ej.
            # `StaticFiles`) no se desciende y el propio `Mount` se emite como
            # hoja: sin `methods` enumerables, `write_methods` lo declara capaz
            # de escribir y el consumidor falla CERRADO.
            yield from _walk(sub, _join(prefix, str(getattr(route, "path", "") or "")))
            continue
        if prefix:
            yield MountedRoute(route, _join(prefix, str(getattr(route, "path", "") or "")))
            continue
        yield route


def iter_mounted_routes(app) -> Iterator:
    """Todas las rutas efectivamente montadas, en cualquier nivel de anidamiento.

    El ``path`` que se emite es siempre el EFECTIVO (con el prefijo de todos los
    ``Mount`` que lo contienen ya compuesto), que es el único con el que tiene
    sentido comparar un prefijo de URL.
    """
    yield from _walk(app.routes)


# ---------------------------------------------------------------------------
# Métodos de una ruta: la ausencia de dato NO es ausencia de escritura
# ---------------------------------------------------------------------------
# Misma doctrina que `slot_enabled` y que el tope tri-estado: un dato que no se
# puede leer no se interpreta como el valor benigno.
#
# El caso medido: `APIWebSocketRoute` **no tiene** atributo `methods`, así que
# `getattr(r, "methods", set())` devuelve `set()`, la intersección con los
# métodos de escritura sale vacía y un canal de escritura perfectamente capaz
# queda invisible EN SILENCIO. Lo mismo vale para un `Mount` opaco.

#: Métodos HTTP que escriben.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Marca que se devuelve en lugar de una lista de métodos cuando la ruta no
#: permite enumerarlos. No es un método: es la declaración explícita de que aquí
#: no se sabe, y por eso se cuenta como escritura.
METHODS_NOT_ENUMERABLE = "<METODOS-NO-ENUMERABLES>"


def enumerable_methods(route) -> Optional[frozenset]:
    """Métodos declarados por la ruta, o ``None`` si NO se pueden enumerar.

    ``None`` y ``frozenset()`` son cosas distintas a propósito: el primero es
    "no lo sé", el segundo no llega a existir (una ruta que declara cero métodos
    tampoco es enumerable en ningún sentido útil).
    """
    raw = getattr(route, "methods", None)
    if raw is None:
        return None
    try:
        metodos = frozenset(str(m).upper() for m in raw)
    except TypeError:
        return None
    return metodos or None


def write_methods(route) -> tuple:
    """Superficie de escritura de ``route``. FALLA CERRADO.

    Devuelve los métodos de escritura declarados; si la ruta no permite
    enumerar métodos devuelve ``(METHODS_NOT_ENUMERABLE,)`` —nunca la tupla
    vacía—, para que quien filtre por "tiene escritura" la vea y quien imprima
    el hallazgo lea el motivo.
    """
    metodos = enumerable_methods(route)
    if metodos is None:
        return (METHODS_NOT_ENUMERABLE,)
    return tuple(sorted(metodos & WRITE_METHODS))


def is_write_capable(route) -> bool:
    """¿Puede esta ruta escribir, hasta donde el censo puede demostrar?"""
    return bool(write_methods(route))


def route_index(app) -> dict[str, str]:
    """``{nombre de ruta: path}`` de lo que está montado DE VERDAD.

    Si un nombre aparece dos veces —el caso habitual es la misma pantalla
    declarada con y sin barra final— gana el path más corto: ambos sirven lo
    mismo y el canónico para un enlace es el sin barra.
    """
    index: dict[str, str] = {}
    for route in iter_mounted_routes(app):
        name = getattr(route, "name", None)
        path = getattr(route, "path", None)
        if not name or not path:
            continue
        previo = index.get(name)
        if previo is None or len(path) < len(previo):
            index[name] = path
    return index


# ---------------------------------------------------------------------------
# Navegación
# ---------------------------------------------------------------------------

def _user_passes(user, role: Optional[str]) -> bool:
    """¿Ve este usuario un enlace que exige ``role``?

    Delega en los métodos del propio ``User``: no hay aquí una segunda tabla de
    rangos. Sin usuario (auth desactivada o anónimo) sólo se muestran los
    enlaces sin exigencia de rol: la ausencia de identidad no concede nada.
    """
    if user is None:
        return role is None
    if role is None:
        return True
    if role == "admin":
        return bool(user.can_access_admin())
    if role == "reviewer":
        return bool(user.can_see_reviews())
    return True  # "viewer": basta con estar autenticado


def nav_for(app, user) -> list[dict]:
    """Enlaces visibles para ``user``, ya resueltos a URL.

    Levanta ``ChassisContractError`` si algún enlace apunta a una ruta que no
    está montada. Es deliberado: preferimos una pantalla rota en el primer test
    que un menú que se autocensura y esconde el error hasta producción.
    """
    index = route_index(app)
    # Huecos apagados: su ruta está montada pero devuelve 404. Enlazarla sería
    # un enlace roto, así que el menú no la pinta. Ojo: ésta es la ÚNICA
    # omisión permitida, y sólo para un hueco declarado y explícitamente
    # apagado; cualquier otro enlace sin ruta sigue reventando.
    apagados = {s.route_name for s in FEATURE_SLOTS if not slot_enabled(s)}
    items: list[dict] = []
    for item in sorted(NAV, key=lambda n: (n.order, n.label)):
        if item.route_name in apagados:
            continue
        if item.route_name not in index:
            raise ChassisContractError(
                f"El elemento de navegación {item.label!r} apunta a la ruta "
                f"{item.route_name!r}, que no está montada. Rutas conocidas: "
                f"{sorted(index)}"
            )
        if _user_passes(user, item.role):
            items.append({"label": item.label, "url": index[item.route_name],
                          "route_name": item.route_name})
    return items


#: Nombre del global de Jinja que usa `base.html`.
NAV_GLOBAL = "chassis_nav"


def install_nav_globals(app, envs: Iterable) -> None:
    """Instala ``chassis_nav`` en cada entorno Jinja recibido.

    Cada router trae su propia instancia de ``Jinja2Templates``, así que un
    global puesto sólo en el entorno de ``main`` dejaría a la mitad de las
    pantallas sin menú. El descubrimiento de entornos vive en ``main`` (que es
    quien conoce el conjunto de routers montados); aquí sólo se inyecta.
    """
    def _nav(user=None):
        return nav_for(app, user)

    for env in envs:
        env.globals[NAV_GLOBAL] = _nav
