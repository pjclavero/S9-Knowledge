"""Rango de esquema soportado y negativa a arrancar fuera de rango.

Decisión del operador (carril I, release readiness):

    «auth_db.v3: N-1 no puede arrancar sobre schema v3 si pierde controles.
     Rango de schema soportado + REFUSE TO START; rollback antes de abrir
     escrituras = código N-1 + restaurar v2.»

Reglas, sin excepciones:

1. Cada componente DECLARA el rango de versiones de esquema que soporta.
2. Si la base está fuera de rango, el proceso **se niega a arrancar**. No hay
   modo degradado, no hay «arranca y ya veremos».

   ALCANCE EXACTO, para que nadie dé por cubierto lo que no lo está: la puerta
   se aplica en el ARRANQUE (`app.auth.db.ensure_migrated`), no en cada acceso
   a datos. `app.auth.db.get_conn()` NO la llama y, sobre una base fuera de
   rango, entrega conexiones. La garantía es «ningún proceso arranca fuera de
   rango», no «ningún acceso ocurre fuera de rango». El coste medido que
   motiva ese límite está en `get_conn.__doc__`; el límite lo fija una prueba.
3. La AUSENCIA de dato nunca es permiso. Una base que existe y está poblada
   pero no dice qué versión tiene es DESCONOCIDA, y desconocido se rechaza.
   Sólo una base inexistente o completamente vacía (instalación nueva) puede
   continuar, porque en ese caso no hay datos a los que aplicar controles
   equivocados.

Por qué el límite SUPERIOR es el que muerde: la v3 de `auth.db` añade
`partida_access.max_visible_session` (tope de progresión de campaña) y
`partida_access.character_id`. El código v2 no conoce esas columnas: si
arrancase sobre una base v3 no leería el tope y serviría sesiones por encima
del límite (control perdido, en silencio), y al conceder accesos escribiría
filas con `max_visible_session` NULL, que significa «sin tope». Es decir: N-1
sobre v3 no sólo lee de más, sino que deja datos sin control que sobreviven a
la vuelta a N. Por eso se rehúsa el arranque en vez de avisar.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

#: Versión de esquema que ESTA build escribe y espera.
#: Se importa de `app.auth.db` para que no puedan divergir dos constantes.
from app.auth.db import SCHEMA_VERSION

#: Versión mínima desde la que esta build sabe migrar hacia delante.
#: `migrate()` reconstruye el DDL v1 y aplica los saltos v2 y v3, así que
#: cualquier base >= 1 es recuperable por este código.
MIN_SUPPORTED_SCHEMA = 1

#: Versión máxima que esta build entiende. Una base por encima de este número
#: fue escrita por código MÁS NUEVO: este proceso es el N-1 del enunciado.
MAX_SUPPORTED_SCHEMA = SCHEMA_VERSION

#: Componente al que se refiere este rango (clave del manifiesto de release).
COMPONENT = "auth_db"

#: Tablas que sólo existen si alguien ya usó esta base. Su presencia convierte
#: «no sé la versión» en un error en vez de en una instalación nueva.
_POPULATED_MARKERS = ("users", "sessions", "audit_events", "partida_access")


#: Códigos ESTABLES de negativa a arrancar. La garantía «REFUSE TO START» se
#: comprueba por TIPO + CÓDIGO: el texto del mensaje es para el operador y
#: puede reescribirse sin que eso cambie ninguna conducta.
SCHEMA_DB_UNREADABLE = "SCHEMA_DB_UNREADABLE"
SCHEMA_NOT_SQLITE = "SCHEMA_NOT_SQLITE"
SCHEMA_VERSION_TABLE_MISSING = "SCHEMA_VERSION_TABLE_MISSING"
SCHEMA_VERSION_TABLE_UNREADABLE = "SCHEMA_VERSION_TABLE_UNREADABLE"
SCHEMA_VERSION_TABLE_EMPTY = "SCHEMA_VERSION_TABLE_EMPTY"
SCHEMA_VERSION_NOT_NUMERIC = "SCHEMA_VERSION_NOT_NUMERIC"
SCHEMA_ABOVE_MAX_SUPPORTED = "SCHEMA_ABOVE_MAX_SUPPORTED"
SCHEMA_BELOW_MIN_SUPPORTED = "SCHEMA_BELOW_MIN_SUPPORTED"


class SchemaCompatibilityError(RuntimeError):
    """La base está fuera del rango soportado: el proceso no debe arrancar.

    Lleva ``code`` estable y, cuando se conoce, ``schema_version``: la prueba
    que sostiene la garantía comprueba eso, no la redacción.
    """

    code = "SCHEMA_INCOMPATIBLE"

    def __init__(self, message: str, code: str | None = None,
                 schema_version: Optional[int] = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        self.schema_version = schema_version


class SchemaVersionUnknown(SchemaCompatibilityError):
    """No se pudo determinar la versión: se trata como incompatible."""

    code = "SCHEMA_VERSION_UNKNOWN"


def _tables(conn: sqlite3.Connection) -> set:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def read_schema_version(db_path: Path) -> Optional[int]:
    """Devuelve la versión de esquema de la base.

    - ``None`` significa «instalación nueva»: el fichero no existe, está vacío
      o es una base sin ninguna tabla. Es el ÚNICO caso de ausencia tolerado.
    - Un entero es la versión leída de `schema_version`.
    - Cualquier otra ausencia o fallo levanta :class:`SchemaVersionUnknown`.
      Desconocido no colapsa nunca a «versión buena».
    """
    path = Path(db_path)
    if not path.exists() or path.stat().st_size == 0:
        return None

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - depende del SO
        raise SchemaVersionUnknown(
            f"{COMPONENT}: no se pudo abrir '{path}' para leer su versión de "
            f"esquema ({exc}). Se rehúsa arrancar: una base ilegible no es "
            f"una base compatible.", SCHEMA_DB_UNREADABLE
        ) from exc

    try:
        try:
            tables = _tables(conn)
        except sqlite3.DatabaseError as exc:
            raise SchemaVersionUnknown(
                f"{COMPONENT}: '{path}' existe pero no es una base SQLite "
                f"legible ({exc}). Se rehúsa arrancar.", SCHEMA_NOT_SQLITE
            ) from exc

        if not tables:
            # Fichero creado pero nunca inicializado: instalación nueva.
            return None

        if "schema_version" not in tables:
            raise SchemaVersionUnknown(
                f"{COMPONENT}: '{path}' contiene tablas "
                f"({', '.join(sorted(tables))}) pero no tiene tabla "
                f"'schema_version'. No se puede saber qué controles rigen "
                f"esos datos. Se rehúsa arrancar: la ausencia de versión no "
                f"es permiso para asumir compatibilidad.", SCHEMA_VERSION_TABLE_MISSING
            )

        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        except sqlite3.DatabaseError as exc:
            raise SchemaVersionUnknown(
                f"{COMPONENT}: '{path}' tiene una tabla 'schema_version' que "
                f"no se puede consultar ({exc}). Se rehúsa arrancar.",
                SCHEMA_VERSION_TABLE_UNREADABLE
            ) from exc

        if row is None or row[0] is None:
            populated = sorted(set(_POPULATED_MARKERS) & tables)
            raise SchemaVersionUnknown(
                f"{COMPONENT}: '{path}' tiene la tabla 'schema_version' VACÍA "
                f"(tablas presentes: {', '.join(sorted(tables))}"
                + (f"; con datos de auth: {', '.join(populated)}" if populated else "")
                + "). Una versión sin registrar es desconocida, no es la 0. "
                "Se rehúsa arrancar.", SCHEMA_VERSION_TABLE_EMPTY
            )

        try:
            return int(row[0])
        except (TypeError, ValueError) as exc:
            raise SchemaVersionUnknown(
                f"{COMPONENT}: versión de esquema no numérica en '{path}': "
                f"{row[0]!r}. Se rehúsa arrancar.", SCHEMA_VERSION_NOT_NUMERIC
            ) from exc
    finally:
        conn.close()


def assert_compatible(db_path: Path) -> Optional[int]:
    """Verifica el rango soportado o impide el arranque.

    Devuelve la versión leída (``None`` si es instalación nueva). Levanta
    :class:`SchemaCompatibilityError` si la base está fuera de rango o si su
    versión no se puede determinar.
    """
    version = read_schema_version(db_path)  # puede levantar SchemaVersionUnknown
    if version is None:
        return None

    if version > MAX_SUPPORTED_SCHEMA:
        raise SchemaCompatibilityError(
            f"{COMPONENT}: la base '{db_path}' tiene esquema v{version}, "
            f"superior al máximo soportado por esta build "
            f"(v{MIN_SUPPORTED_SCHEMA}..v{MAX_SUPPORTED_SCHEMA}). "
            f"Este proceso es código N-1 sobre datos N: arrancar significaría "
            f"ignorar controles que esta build no conoce. SE REHÚSA ARRANCAR. "
            f"Para volver atrás: (1) parar el servicio, (2) desplegar el "
            f"código N-1, (3) RESTAURAR la copia v{MAX_SUPPORTED_SCHEMA} de la "
            f"base ANTES de abrir escrituras, (4) arrancar. "
            f"Ver docs/65-preparacion-de-release.md.",
            SCHEMA_ABOVE_MAX_SUPPORTED, schema_version=version
        )

    if version < MIN_SUPPORTED_SCHEMA:
        raise SchemaCompatibilityError(
            f"{COMPONENT}: la base '{db_path}' tiene esquema v{version}, "
            f"inferior al mínimo soportado (v{MIN_SUPPORTED_SCHEMA}). Esta "
            f"build no tiene ruta de migración desde ahí. SE REHÚSA ARRANCAR.",
            SCHEMA_BELOW_MIN_SUPPORTED, schema_version=version
        )

    return version
