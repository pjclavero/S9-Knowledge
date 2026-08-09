"""Especificación declarativa de lo que hace falta para desplegar S9 Knowledge.

Fuente única de verdad compartida por:

  - ``generate_manifest.py`` — escribe el manifiesto de release.
  - ``config_check.py``      — comprueba un host destino contra esta especificación.

Reglas de este módulo:

  - NUNCA contiene secretos. Los secretos se referencian **por ruta**
    (``S9K_NEO4J_PASSWORD_FILE`` -> ``/etc/s9-knowledge/secrets/neo4j_password``)
    y su contenido no se lee, ni se imprime, ni se hashea aquí.
  - Los nombres de variable se toman VERBATIM del código
    (``viewer/app/config.py``, ``viewer/app/auth/config.py``,
    ``viewer/app/health/runner.py``). No se inventan variables.
  - Lo que sea CRITICAL debe coincidir con las marcas ``[CRÍTICA]`` de
    ``deploy/config/viewer.env.example``; hay un test que lo verifica.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Sequence


class Level(str, Enum):
    """Severidad con la que se reporta el incumplimiento de un requisito."""

    CRITICAL = "CRITICAL"       # su ausencia o invalidez es ERROR: no se despliega
    RECOMMENDED = "RECOMMENDED"  # su ausencia es WARNING: se despliega con reservas
    OPTIONAL = "OPTIONAL"        # informativo


class Status(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"


# Orden de gravedad, para agregar el estado global.
_SEVERITY = {Status.OK: 0, Status.WARNING: 1, Status.ERROR: 2}


def worst(statuses: Sequence[Status]) -> Status:
    """Estado global = el peor de los estados individuales.

    Vacío -> OK. Esta función es la única que decide el veredicto agregado, de
    modo que ningún ERROR pueda quedar enmascarado por un recuento de OKs.
    """
    return max(statuses, key=lambda s: _SEVERITY[s], default=Status.OK)


# ---------------------------------------------------------------------------
# Validadores de valor (no de presencia). Devuelven None si el valor vale, o un
# mensaje de por qué no. Nunca reciben ni devuelven material secreto.
# ---------------------------------------------------------------------------

def _is_bool(value: str) -> str | None:
    if value.strip().lower() not in {"true", "false", "1", "0", "yes", "no"}:
        return f"se esperaba un booleano, se encontró {value!r}"
    return None


def _is_true(value: str) -> str | None:
    if value.strip().lower() not in {"true", "1", "yes"}:
        return f"debe estar activado en producción (valor actual: {value!r})"
    return None


def _is_int(value: str) -> str | None:
    try:
        int(value)
    except ValueError:
        return f"se esperaba un entero, se encontró {value!r}"
    return None


def _is_port(value: str) -> str | None:
    if err := _is_int(value):
        return err
    if not 1 <= int(value) <= 65535:
        return f"puerto fuera de rango: {value}"
    return None


def _is_abs_path(value: str) -> str | None:
    if not value.startswith("/"):
        return f"debe ser una ruta absoluta, se encontró {value!r}"
    return None


def _is_bolt_uri(value: str) -> str | None:
    if not value.startswith(("bolt://", "bolt+s://", "bolt+ssc://", "neo4j://", "neo4j+s://")):
        return f"esquema de URI Neo4j no reconocido: {value!r}"
    return None


def _in(*allowed: str) -> Callable[[str], str | None]:
    def _check(value: str) -> str | None:
        if value not in allowed:
            return f"valor {value!r} fuera del conjunto permitido {sorted(allowed)}"
        return None
    return _check


def _outside_release(value: str) -> str | None:
    """El estado (auth.db, jobs.db, backups) NO puede vivir dentro de la release.

    Es la lección de `docs/50-deploy-state-continuity.md`: cualquier ruta bajo
    ``/opt/s9-knowledge/releases`` o bajo el symlink ``current`` se pierde en el
    siguiente despliegue.
    """
    if err := _is_abs_path(value):
        return err
    if "/releases/" in value or value.startswith("/opt/s9-knowledge/current"):
        return (
            "el estado no puede vivir dentro del árbol de la release "
            f"(se perdería en el siguiente despliegue): {value!r}"
        )
    return None


# ---------------------------------------------------------------------------
# Variables de entorno
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnvVar:
    name: str
    level: Level
    purpose: str
    validator: Callable[[str], str | None] | None = None
    # Si es True, el valor NUNCA se imprime ni se incluye en informes: solo se
    # reporta "definida" / "no definida" y, si procede, la ruta del fichero.
    secret: bool = False
    # Nombre de la variable ``*_FILE`` que puede sustituirla (secreto por ruta).
    file_alternative: str | None = None
    default_in_code: str | None = None


ENV_VARS: tuple[EnvVar, ...] = (
    # --- Servidor del visor ---
    EnvVar("S9K_VIEWER_HOST", Level.CRITICAL,
           "interfaz de escucha de uvicorn; 127.0.0.1 mantiene el visor detrás del proxy",
           default_in_code="127.0.0.1"),
    EnvVar("S9K_VIEWER_PORT", Level.CRITICAL,
           "puerto de uvicorn", _is_port, default_in_code="8088"),

    # --- Grafo / Neo4j ---
    EnvVar("S9K_GRAPH_PROVIDER", Level.CRITICAL,
           "proveedor de grafo; en producción debe ser 'neo4j', nunca 'mock'",
           _in("neo4j", "mock"), default_in_code="mock"),
    EnvVar("S9K_NEO4J_URI", Level.CRITICAL,
           "URI bolt del Neo4j de producción", _is_bolt_uri,
           default_in_code="bolt://127.0.0.1:7687"),
    EnvVar("S9K_NEO4J_USER", Level.CRITICAL, "usuario de Neo4j"),
    EnvVar("S9K_NEO4J_PASSWORD", Level.CRITICAL,
           "contraseña de Neo4j; se prefiere el fichero de secreto",
           secret=True, file_alternative="S9K_NEO4J_PASSWORD_FILE"),
    EnvVar("S9K_DEFAULT_WORKSPACE", Level.RECOMMENDED,
           "workspace por defecto del visor", default_in_code="leyenda"),
    EnvVar("S9K_GRAPH_LIMIT", Level.RECOMMENDED,
           "tope de nodos devueltos por consulta de grafo", _is_int, default_in_code="300"),

    # --- Estado externo a la release ---
    EnvVar("S9K_AUTH_DB_PATH", Level.CRITICAL,
           "ruta de auth.db (usuarios, sesiones, partida_access); FUERA de la release",
           _outside_release, default_in_code="viewer/state/auth.db"),
    EnvVar("S9K_JOBS_DB", Level.CRITICAL,
           "ruta de jobs.db; FUERA de la release", _outside_release),
    EnvVar("S9K_BACKUP_DIR", Level.RECOMMENDED,
           "directorio que el healthcheck de backups inspecciona", _is_abs_path),

    # --- Autenticación ---
    EnvVar("S9K_AUTH_ENABLED", Level.CRITICAL,
           "interruptor global de autenticación; en producción SIEMPRE true",
           _is_true, default_in_code="false"),
    EnvVar("S9K_CSRF_SECRET", Level.CRITICAL,
           "secreto de firma CSRF; el código NO soporta S9K_CSRF_SECRET_FILE, "
           "así que vive en /etc/s9-knowledge/viewer.env (0600 root)",
           secret=True, default_in_code="s9k-csrf-change-me"),
    EnvVar("S9K_AUTH_MAX_FAILED_ATTEMPTS", Level.RECOMMENDED,
           "intentos fallidos antes de bloquear la cuenta", _is_int, default_in_code="5"),
    EnvVar("S9K_AUTH_LOCK_MINUTES", Level.RECOMMENDED,
           "duración del bloqueo por fuerza bruta", _is_int, default_in_code="15"),
    EnvVar("S9K_AUTH_EXPOSE_DOCS", Level.RECOMMENDED,
           "expone /docs y /openapi.json; false en producción", _is_bool, default_in_code="false"),
    EnvVar("S9K_AUTH_TRUST_PROXY_HEADERS", Level.RECOMMENDED,
           "confiar en X-Forwarded-For; solo con proxy que filtre la cabecera",
           _is_bool, default_in_code="false"),

    # --- Sesiones ---
    EnvVar("S9K_SESSION_COOKIE_NAME", Level.OPTIONAL, "nombre de la cookie de sesión",
           default_in_code="s9k_session"),
    EnvVar("S9K_SESSION_TTL_HOURS", Level.RECOMMENDED, "vida máxima de la sesión",
           _is_int, default_in_code="12"),
    EnvVar("S9K_SESSION_IDLE_MINUTES", Level.RECOMMENDED, "inactividad máxima",
           _is_int, default_in_code="60"),
    EnvVar("S9K_SESSION_SECURE", Level.CRITICAL,
           "cookie Secure; false expondría la sesión en claro", _is_true,
           default_in_code="true"),
    EnvVar("S9K_SESSION_SAMESITE", Level.RECOMMENDED, "política SameSite",
           _in("lax", "strict", "none"), default_in_code="lax"),
    EnvVar("S9K_SESSION_HTTPONLY", Level.CRITICAL,
           "cookie HttpOnly; false la haría legible desde JavaScript", _is_true,
           default_in_code="true"),

    # --- Healthchecks ---
    EnvVar("S9K_HEALTH_VIEWER_URL", Level.RECOMMENDED, "URL que sondea el healthcheck"),
    EnvVar("S9K_HEALTH_REPORT_PATH", Level.RECOMMENDED,
           "destino del informe JSON de salud", _is_abs_path),
    EnvVar("S9K_HEALTH_UNITS", Level.RECOMMENDED,
           "unidades systemd vigiladas por el healthcheck"),
    EnvVar("S9K_HEALTH_DISK_PATH", Level.RECOMMENDED,
           "punto de montaje vigilado por ocupación", _is_abs_path),

    # --- Paginación / límites ---
    EnvVar("S9K_VIEWER_DEFAULT_PAGE_SIZE", Level.OPTIONAL, "tamaño de página por defecto",
           _is_int, default_in_code="50"),
    EnvVar("S9K_VIEWER_MAX_PAGE_SIZE", Level.OPTIONAL, "tamaño de página máximo",
           _is_int, default_in_code="200"),
    EnvVar("S9K_VIEWER_QUERY_TIMEOUT_SECONDS", Level.RECOMMENDED,
           "timeout de consulta al grafo", _is_int, default_in_code="10"),
    EnvVar("S9K_VIEWER_MAX_SEARCH_LENGTH", Level.OPTIONAL, "longitud máxima de búsqueda",
           _is_int, default_in_code="200"),
)

# Variables que, si están definidas, deben estar APAGADAS al desplegar. La
# primera ingesta real sigue sin autorizar (doble guard deliberado).
MUST_BE_OFF: tuple[str, ...] = (
    "S9K_ALLOW_REAL_INGEST",
    "S9K_ALLOW_RELATION_AUTOAPPROVAL",
)


# ---------------------------------------------------------------------------
# Ficheros, secretos, directorios
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RequiredFile:
    path: str
    level: Level
    purpose: str
    # Permisos máximos permitidos (octal). Si el fichero es más laxo -> fallo.
    max_mode: int | None = None
    owner: str | None = None
    # Si es True, se comprueba existencia y permisos pero NUNCA se lee.
    secret: bool = False


REQUIRED_FILES: tuple[RequiredFile, ...] = (
    RequiredFile("/etc/s9-knowledge/viewer.env", Level.CRITICAL,
                 "configuración del visor; contiene S9K_CSRF_SECRET",
                 max_mode=0o600, owner="root", secret=True),
    RequiredFile("/etc/s9-knowledge/secrets/neo4j_password", Level.CRITICAL,
                 "secreto de Neo4j referenciado por S9K_NEO4J_PASSWORD_FILE",
                 max_mode=0o640, secret=True),
    RequiredFile("/etc/s9-knowledge/providers.env", Level.OPTIONAL,
                 "claves de proveedores externos (NVIDIA); solo si se usa IA externa",
                 max_mode=0o600, owner="root", secret=True),
)


@dataclass(frozen=True)
class RequiredDir:
    path: str
    level: Level
    purpose: str
    writable_by_service: bool = False
    max_mode: int | None = None


REQUIRED_DIRS: tuple[RequiredDir, ...] = (
    RequiredDir("/opt/s9-knowledge/releases", Level.CRITICAL,
                "árbol de releases inmutables"),
    RequiredDir("/var/lib/s9-knowledge/auth", Level.CRITICAL,
                "directorio de auth.db; el visor NO lo crea, debe preexistir",
                writable_by_service=True, max_mode=0o750),
    RequiredDir("/var/lib/s9-knowledge/jobs", Level.CRITICAL,
                "directorio de jobs.db", writable_by_service=True, max_mode=0o750),
    RequiredDir("/var/lib/s9-knowledge/backups", Level.CRITICAL,
                "destino de copias; el healthcheck falla si su contenido es rancio",
                writable_by_service=True, max_mode=0o750),
    RequiredDir("/var/lib/s9-knowledge/health", Level.RECOMMENDED,
                "destino del informe de salud", writable_by_service=True),
    RequiredDir("/var/log/s9-knowledge", Level.RECOMMENDED, "logs de la aplicación",
                writable_by_service=True),
)


# ---------------------------------------------------------------------------
# Versiones exigidas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VersionRequirement:
    component: str
    level: Level
    # Versión mínima inclusive y exclusiva máxima, como tuplas comparables.
    min_version: tuple[int, ...]
    below_version: tuple[int, ...]
    note: str = ""


VERSION_REQUIREMENTS: tuple[VersionRequirement, ...] = (
    VersionRequirement("python", Level.CRITICAL, (3, 13), (3, 14),
                       "CI valida exclusivamente 3.13; el visor no se prueba en otra"),
    VersionRequirement("neo4j", Level.CRITICAL, (5, 26), (6, 0),
                       "5.26.0-community es lo verificado en VM105 y en CI; "
                       "el driver está pineado a >=5.20,<6.0"),
)


# ---------------------------------------------------------------------------
# Unidades systemd y comprobaciones operativas
# ---------------------------------------------------------------------------

SYSTEMD_UNITS: tuple[tuple[str, Level, str], ...] = (
    ("s9-knowledge-viewer.service", Level.CRITICAL, "uvicorn del visor"),
    ("s9-knowledge-healthcheck.timer", Level.RECOMMENDED,
     "disparo horario del healthcheck"),
)


# ---------------------------------------------------------------------------
# Componentes de la release y sus esquemas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Component:
    name: str
    path: str
    purpose: str
    deployed: bool


COMPONENTS: tuple[Component, ...] = (
    Component("viewer", "viewer/", "aplicación FastAPI servida por uvicorn", True),
    Component("viewer-cli", "viewer/app/cli/",
              "CLI de auth y de health; se ejecuta a mano y desde el timer", True),
    Component("data-engine", "data-engine/",
              "pipeline de extracción/ingesta; NO se activa en este despliegue "
              "(la primera ingesta real sigue sin autorizar)", True),
    Component("deploy-tools", "deploy/",
              "scripts de despliegue, verificación y rollback; se instalan "
              "aparte, en /opt/s9-knowledge/deploy-tools", True),
    Component("contracts", "contracts/", "JSON Schema congelados de review/ingest y v3", True),
    Component("docs", "docs/", "documentación; no se ejecuta", True),
)


@dataclass(frozen=True)
class Migration:
    """Una migración, esté o no pendiente de aplicar."""

    id: str
    component: str
    required: bool
    reversible: bool
    description: str
    # Por qué NO es necesaria, cuando required=False. Este campo es la mitad
    # del manifiesto que normalmente falta y que provoca sorpresas.
    rationale: str = ""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        id="auth_db.v3",
        component="auth.db (SQLite)",
        required=True,
        reversible=False,
        description=(
            "ALTER TABLE partida_access ADD COLUMN max_visible_session INTEGER; "
            "ADD COLUMN character_id TEXT. La aplica automáticamente "
            "app.auth.db.ensure_migrated() en el arranque del visor, bajo flock "
            "exclusivo y tras copiar <db>.bak.v<versión anterior>."
        ),
        rationale=(
            "Necesaria: el código de T2 lee ambas columnas. SQLite no soporta "
            "DROP COLUMN en versiones antiguas y el código no implementa "
            "downgrade: la vuelta atrás es por restauración de la copia .bak, "
            "no por migración inversa."
        ),
    ),
    Migration(
        id="auth_db.v2",
        component="auth.db (SQLite)",
        required=False,
        reversible=False,
        description="sessions.active_partida + tabla partida_access (M5a).",
        rationale=(
            "NO necesaria como paso separado: ensure_migrated() encadena v1->v2->v3 "
            "en la misma transacción lógica. Se declara aquí para que el manifiesto "
            "no sugiera que un auth.db en v1 salta directamente a v3 sin pasar por v2."
        ),
    ),
    Migration(
        id="graph.legacy_visibility_m5b",
        component="Neo4j (grafo de producción)",
        required=False,
        reversible=False,
        description=(
            "Estampado de ámbito y visibilidad sobre los nodos legacy del grafo "
            "de producción (plan 12f7278f de M5b)."
        ),
        rationale=(
            "NO APPLY por decisión del operador. El plan se validó pero se descartó: "
            "sin `known_by` en los datos legacy no hay migración semántica posible, "
            "solo una asignación arbitraria. El grafo de producción (199 nodos / 140 "
            "relaciones) se queda como está. Consecuencia que el manifiesto asume: "
            "los datos legacy quedan fuera del alcance de partida y se comportan "
            "según el cierre por defecto (fail-closed), no como contenido de juego "
            "reetiquetado. Cualquier release que EXIJA ámbito estampado en legacy "
            "está en contradicción con esta decisión y no debe desplegarse."
        ),
    ),
    Migration(
        id="jobs_db.v1",
        component="jobs.db (SQLite)",
        required=False,
        reversible=True,
        description="Esquema de la cola de trabajos.",
        rationale=(
            "NO necesaria: el esquema no cambia en esta release. La base se conserva "
            "intacta entre releases porque vive fuera del árbol de despliegue."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Smoke tests declarados en el manifiesto (los ejecuta smoke_lab.py)
# ---------------------------------------------------------------------------

SMOKE_CHECKS: tuple[tuple[str, str], ...] = (
    ("app_boots", "la aplicación importa y arranca con auth activa y CSRF válido"),
    ("login", "login con credenciales correctas emite sesión; con incorrectas, no"),
    ("viewer_home", "la portada responde a un usuario autenticado"),
    ("graph", "/graph y /api/graph responden dentro del workspace"),
    ("entities", "/entities y /api/entities responden y paginan"),
    ("sources", "/sources y /api/sources responden"),
    ("jobs", "/jobs y /api/jobs responden"),
    ("reviews", "/reviews y la consola de revisión responden"),
    ("admin", "/admin/users exige rol admin y lo deniega a un viewer"),
    ("health", "el CLI de salud produce un informe con veredicto explícito"),
    ("neo4j_connectivity", "el proveedor configurado abre sesión contra el grafo"),
    ("unauthorized_data_invisible",
     "un usuario sin concesión NO ve entidades de partida ajena por ninguna vía"),
)


@dataclass(frozen=True)
class RollbackStep:
    order: int
    action: str
    detail: str


ROLLBACK_PLAN: tuple[RollbackStep, ...] = (
    RollbackStep(1, "congelar", "systemctl stop s9-knowledge-viewer.service"),
    RollbackStep(2, "copia previa",
                 "copiar auth.db/jobs.db del estado ACTUAL antes de tocar nada; "
                 "el rollback destruye evidencia si no se hace"),
    RollbackStep(3, "restaurar código",
                 "deploy/scripts/rollback-release.sh: repuntar el symlink `current` "
                 "a la release N-1 (permanece en disco: S9K_RELEASES_TO_KEEP=3)"),
    RollbackStep(4, "restaurar configuración",
                 "/etc/s9-knowledge/viewer.env NO está versionado en la release: "
                 "si N añadió variables, revertirlas a mano desde la copia previa"),
    RollbackStep(5, "decidir sobre la BD",
                 "si N aplicó auth_db.v3, N-1 NO puede leer ese esquema con "
                 "garantías: restaurar <db>.bak.v2 o aceptar operar en v3"),
    RollbackStep(6, "arrancar y verificar",
                 "systemctl start + verify-deployment.sh --expected-release <N-1> "
                 "+ smoke suite de laboratorio contra el host"),
)


# Métricas de recuperación. Están separadas a propósito: mezclarlas es el error
# clásico que hace creer que un servicio vuelve en 8 minutos.
RECOVERY_METRICS: tuple[dict[str, str], ...] = (
    {
        "metric": "RPO observado",
        "value": "SIN GARANTÍA",
        "measured": "no",
        "detail": (
            "No hay backup automático instalado (deploy/propuestas/backup-automatico "
            "es una propuesta, no una unidad activa). La copia más reciente en VM105 "
            "es del 2026-07-17 más el checkpoint manual del 2026-08-06. El RPO real "
            "es 'desde la última copia manual', que a fecha de hoy se mide en semanas."
        ),
    },
    {
        "metric": "RTO de restore",
        "value": "8,2 min",
        "measured": "sí",
        "detail": (
            "Medido: duración de la fase de restauración en VM105. Cubre la "
            "restauración de los datos, NO el diagnóstico previo, NI la decisión "
            "humana, NI el arranque y verificación posteriores."
        ),
    },
    {
        "metric": "RTO hasta servicio",
        "value": "SIN MEDIR",
        "measured": "no",
        "detail": (
            "Tiempo desde la detección del fallo hasta que el visor vuelve a servir "
            "tráfico verificado. Incluye detección, decisión, restore (8,2 min), "
            "arranque, migración/compatibilidad de esquema y smoke. Nadie lo ha "
            "cronometrado de extremo a extremo. No debe suponerse igual a 8,2 min."
        ),
    },
)
