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
    "WriteCapability",
    "WRITE_CAPABILITIES",
    "capabilities_for_slot",
    "declared_write",
    "undeclared_writes",
    "ChassisContractError",
    "iter_mounted_routes",
    "route_index",
    "MountedRoute",
    "WRITE_METHODS",
    "METHODS_NOT_ENUMERABLE",
    "enumerable_methods",
    "write_methods",
    "is_write_capable",
    "PATH_NOT_RESOLVABLE",
    "effective_path",
    "route_path",
    "path_in_prefix",
    "route_in_prefix",
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
    NavItem("Revisión V3", "v3_review_queue", "reviewer", 7),
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
        # Un `_EffectiveRouteContext` que envuelve algo que NO es una `APIRoute`
        # —el caso medido es un `Mount` dentro de un `APIRouter` incluido con
        # prefijo— trae `path=''`: FastAPI sólo rellena el contexto para las
        # rutas de API. La ruta de Starlette subyacente SÍ la trae ya compuesta
        # (`Mount(path='/panel/review/inc/m')`), así que se sustituye por ella y
        # el descenso normal por `Mount` hace el resto. Sin esto, el censo
        # emitía un objeto con path vacío: invisible para todo filtro por
        # prefijo y saltado en silencio por el barrido de autorización, mientras
        # `POST /panel/review/inc/m/aprobar` respondía 200 y escribía.
        if not getattr(route, "path", None):
            real = getattr(route, "starlette_route", None)
            if real is not None and getattr(real, "path", None):
                route = real
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


# ---------------------------------------------------------------------------
# El `path` también es tri-estado, y el filtro tiene FRONTERA DE SEGMENTO
# ---------------------------------------------------------------------------
# Faltaba aplicar al `path` la misma doctrina que a `methods`. Un path que no se
# puede resolver se trataba como `''`: benigno, fuera de TODO prefijo, y saltado
# por el barrido de autorización con un `if not path: continue`. El fallo cerrado
# por métodos no salvaba nada, porque el filtro por path corre ANTES.
#
# Y el filtro es de ESPACIO DE URL, así que compara por segmentos: `/panel/review`
# no contiene a `/panel/reviewXYZ/borrar`. Con `startswith` a secas eso era un
# FALSO POSITIVO, y B/F/G van a tener prefijos vecinos (`/panel/sources` frente a
# un hipotético `/panel/sources-legacy`).

#: Marca que se devuelve cuando el path de una ruta no se puede resolver.
PATH_NOT_RESOLVABLE = "<PATH-NO-RESOLUBLE>"


def effective_path(route) -> Optional[str]:
    """Path efectivo de la ruta, o ``None`` si NO se puede resolver.

    Cadena vacía es ausencia de dato, no "la raíz": ninguna ruta servible tiene
    path vacío, así que `''` sólo aparece cuando el censo no supo resolverlo.
    """
    raw = getattr(route, "path", None)
    if raw is None:
        return None
    texto = str(raw)
    return texto or None


def route_path(route) -> str:
    """Path para IMPRIMIR en un hallazgo. Nunca miente con una cadena vacía."""
    path = effective_path(route)
    return PATH_NOT_RESOLVABLE if path is None else path


def path_in_prefix(path: str, prefix: str) -> bool:
    """¿Está ``path`` dentro del espacio de URL ``prefix``, por SEGMENTOS?

    `/panel/review` contiene a `/panel/review`, `/panel/review/` y
    `/panel/review/item/{id}`, pero NO a `/panel/reviewXYZ/borrar`.
    """
    base = prefix.rstrip("/")
    return path == base or path.startswith(base + "/")


def route_in_prefix(route, prefix: str) -> bool:
    """¿Cae ``route`` en el espacio de URL ``prefix``? FALLA CERRADO.

    Una ruta cuyo path no se puede resolver se declara DENTRO de cualquier
    espacio: no saber dónde está una ruta no la pone fuera de tu frontera, la
    pone en todas. Combinado con ``write_methods`` (que también falla cerrado
    ante esa misma ruta), el consumidor la reporta en vez de saltársela.
    """
    path = effective_path(route)
    if path is None:
        return True
    return path_in_prefix(path, prefix)


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


# ---------------------------------------------------------------------------
# CAPACIDADES DE ESCRITURA DEL PANEL — el contrato cambia, y cambia AQUI
# ---------------------------------------------------------------------------
# HASTA EL SLICE 2 el contrato de este chasis era `panel = solo lectura`: los
# cuatro huecos servian GET y nada mas, y cada suite de panel lo fijaba con una
# enumeracion de su espacio de URL.
#
# EL CONTRATO NUEVO, escrito entero y sin letra pequena:
#
#     GET                 -> observacion
#     POST / mutaciones   -> SOLO capacidades de producto EXPLICITAMENTE
#                            declaradas aqui, autenticadas, autorizadas,
#                            protegidas con CSRF y AUDITABLES.
#
# Lo que NO cambia, y es la mitad importante: **lectura por defecto**. Un hueco
# sin entrada en `WRITE_CAPABILITIES` no admite ni un solo metodo de escritura
# en todo su espacio de URL, exactamente igual que antes. El chasis no se abre;
# se le anade una puerta con cerradura declarada.
#
# Esto existe para que "este POST es especial" sea IMPOSIBLE de colar: una ruta
# de escritura que no este en esta tabla es un defecto detectable por
# enumeracion (`undeclared_writes`), no por revision ocular — la misma doctrina
# que `FEATURE_SLOTS` aplica a las rutas muertas.

@dataclass(frozen=True)
class WriteCapability:
    """Una capacidad de producto que MUTA, declarada como dato.

    `path` es la URL EFECTIVA completa (con el prefijo del hueco ya dentro): es
    la forma en que la enumeracion ve las rutas, y compararla con un path
    relativo seria comparar dos cosas distintas.
    """

    slot_key: str       # hueco al que pertenece; debe existir en FEATURE_SLOTS
    name: str           # identificador estable de la capacidad
    title: str          # nombre humano, para el operador
    path: str           # URL efectiva completa
    methods: frozenset  # metodos de escritura que ofrece
    role: str           # rol minimo: uno de ROLES
    audited: bool       # deja rastro de auditoria en el servidor
    summary: str        # que hace, en una frase

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ChassisContractError(
                f"capacidad {self.name!r}: rol {self.role!r} fuera de ROLES {ROLES}"
            )
        if not self.methods or not (self.methods <= WRITE_METHODS):
            raise ChassisContractError(
                f"capacidad {self.name!r}: {sorted(self.methods)} no son metodos "
                f"de escritura {sorted(WRITE_METHODS)}"
            )
        if not self.audited:
            # No es un aviso: el contrato dice "AUDITABLES". Una capacidad que
            # no deja rastro no cumple el contrato y no se monta.
            raise ChassisContractError(
                f"capacidad {self.name!r}: el contrato exige que sea auditable"
            )
        slot = next((s for s in FEATURE_SLOTS if s.key == self.slot_key), None)
        if slot is None:
            raise ChassisContractError(
                f"capacidad {self.name!r}: hueco {self.slot_key!r} no declarado"
            )
        if not path_in_prefix(self.path, slot.prefix):
            raise ChassisContractError(
                f"capacidad {self.name!r}: {self.path!r} cae fuera del espacio "
                f"de URL del hueco {self.slot_key} ({slot.prefix})"
            )


#: Las capacidades de escritura que el chasis aloja HOY. TRES, y las tres del
#: hueco B (Operaciones): el alta de fuente, y las dos de la cadena de apply.
#: Los huecos C, F y G no aparecen, y por eso siguen siendo de solo lectura
#: por construccion.
#:
#: EL APPLY VIVE EN `B`, NO EN `C`, Y NO ES UN DETALLE DE COLOCACION.
#: `/panel/review` (hueco C) declara una FRONTERA DURA -- "aqui no hay ningun
#: metodo que no sea GET" -- que se verifica por enumeracion. Colgar alli un
#: POST habria sido cambiar el contrato de un fichero que ya es de `main`, y
#: el encargo obliga a declararlo explicitamente si se hace. No se hace: la
#: alternativa legitima es que el apply viva sobre la CORRIDA, en
#: `/panel/operations`, que es donde el operador ya tiene su acuse de ingesta
#: y donde ya hay escritura declarada. `/panel/review` sigue siendo solo
#: lectura, byte a byte.
WRITE_CAPABILITIES: tuple[WriteCapability, ...] = (
    WriteCapability(
        slot_key="B",
        name="ingesta_de_fuente",
        title="Solicitar la ingesta de una fuente",
        path="/panel/operations/ingestas",
        methods=frozenset({"POST"}),
        role="admin",
        audited=True,
        summary=(
            "Encola un trabajo de ingesta (`ingest_v3`) para una fuente elegida "
            "del catalogo. No escribe en el grafo: deja un trabajo en la cola. "
            "El trabajo, al correr, SI deja una escritura fuera del grafo: la "
            "cola de revision en el almacen de propuestas "
            "(`S9K_V3_REVIEW_PROPOSALS_DIR`), que es lo que `/panel/review` "
            "lee. Se declara aqui porque es una escritura de esta capacidad, "
            "aunque la haga el worker y no la peticion."
        ),
    ),
    WriteCapability(
        slot_key="B",
        name="sellado_del_plan_revisado",
        title="Preparar lo aprobado de una ingesta",
        path="/panel/operations/planes",
        methods=frozenset({"POST"}),
        role="admin",
        audited=True,
        summary=(
            "Sella, como SNAPSHOT INMUTABLE en el almacen de revision, el plan "
            "derivado de las propuestas persistidas de una corrida y de las "
            "decisiones humanas efectivas ya persistidas. NO reejecuta el "
            "pipeline y NO escribe en el grafo: deja el artefacto que el "
            "operador reviso, para que aplicar consuma exactamente eso y no "
            "algo recalculado. Un cambio posterior de decisiones no lo modifica: "
            "lo invalida."
        ),
    ),
    WriteCapability(
        slot_key="B",
        name="aplicacion_del_plan_revisado",
        title="Anadir al conocimiento lo aprobado",
        path="/panel/operations/aplicaciones",
        methods=frozenset({"POST"}),
        role="admin",
        audited=True,
        summary=(
            "Aplica el plan sellado vigente de una corrida por la UNICA ruta "
            "canonica de aplicacion (`knowledge_v3.writer.apply.apply_v3`). SI "
            "escribe en el grafo, y por eso exige la doble declaracion del gate "
            "del writer (`S9K_ALLOW_REAL_INGEST` y `S9K_WRITER_WORKSPACE`). El "
            "plan se resuelve INTERNAMENTE desde la corrida: `plan_id` jamas es "
            "entrada del operador."
        ),
    ),
)


def capabilities_for_slot(slot_key: str) -> tuple[WriteCapability, ...]:
    """Capacidades declaradas de un hueco. Vacio = hueco de solo lectura."""
    return tuple(c for c in WRITE_CAPABILITIES if c.slot_key == slot_key)


def declared_write(path: str, method: str) -> Optional[WriteCapability]:
    """La capacidad que declara ``method path``, o ``None`` si no hay ninguna."""
    metodo = str(method).upper()
    for cap in WRITE_CAPABILITIES:
        if cap.path == path and metodo in cap.methods:
            return cap
    return None


def undeclared_writes(app, slot: "FeatureSlot") -> list[tuple]:
    """Escrituras montadas bajo ``slot`` que NADIE ha declarado. FALLA CERRADO.

    Es el sustituto exacto de la vieja enumeracion "ninguna ruta de este panel
    acepta escritura": para un hueco sin capacidades devuelve lo mismo que
    aquella (cualquier escritura es un hallazgo), y para un hueco con
    capacidades solo tolera las que estan en la tabla.

    Una ruta cuyo path o cuyos metodos no se pueden enumerar cae aqui dentro:
    `route_in_prefix` y `write_methods` ya fallan cerrado, y una ruta que no se
    sabe que hace NUNCA esta declarada.
    """
    hallazgos: list[tuple] = []
    for route in iter_mounted_routes(app):
        if not route_in_prefix(route, slot.prefix):
            continue
        metodos = write_methods(route)
        if not metodos:
            continue
        camino = route_path(route)
        sin_declarar = [m for m in metodos if declared_write(camino, m) is None]
        if sin_declarar:
            hallazgos.append((camino, sorted(sin_declarar)))
    return hallazgos
