"""Estado de instalacion y alta del PRIMER administrador.

QUE PROBLEMA CIERRA
-------------------
La propiedad que el producto no tenia:

    instalacion -> abrir navegador -> crear primer administrador ->
    iniciar sesion -> entrar al producto

sin tocar un terminal. Antes: sin `auth.db` el proceso abortaba con RC=3 y
CERO superficie HTTP, y con la base creada y sin usuarios el `/login` era
indistinguible del normal (respondia «usuario o contrasena incorrectos» a
credenciales inventadas, que es mentir sobre la causa).

EL MODELO DE ESTADO, y por que NO es `count_active_admins() == 0`
-----------------------------------------------------------------
`count_active_admins() == 0` es una CUENTA VIVA: baja cuando alguien elimina o
desactiva al ultimo administrador. Si la puerta de bootstrap dependiese de
ella, quedarse sin administradores REABRIRIA una puerta anonima de creacion de
administrador sobre una instalacion con datos reales. Eso es un agujero.

El estado es PERSISTENTE e IRREVERSIBLE, y vive en la fila
`install_state['bootstrap_completed']` (esquema v4):

    auth.db inexistente -> ensure_migrated() -> PENDIENTE -> /setup/admin abierto
    crear primer admin  -> TRANSACCION ATOMICA: sello + admin
    -> COMPLETADO -> /setup/admin cerrado PARA SIEMPRE -> login normal

Y una instalacion provisionada por cualquier OTRA via legitima (la CLI, la
pantalla de alta de usuarios) tambien queda sellada: la inferencia «ya hay
usuarios» ESCRIBE el sello la primera vez que se consulta. Si no lo escribiese
seria una cuenta viva y vaciar la tabla de usuarios reabriria la puerta.

La recuperacion de «me he quedado sin administradores» sera otro mecanismo
explicito. Nunca la reapertura de esta puerta.

AUSENCIA != ERROR
-----------------
`estado_instalacion` distingue tres desenlaces, no dos. La base ausente (o
existente y sin ninguna tabla) es PRIMERA INSTALACION. Una base que existe
pero no se puede leer, no es SQLite, o no dice que version tiene, NO es una
primera instalacion: es un fallo de almacenamiento, y se responde fail-closed
con diagnostico. Quien se salta esta distincion convierte un disco roto en
«bienvenido, cree su administrador» sobre datos que siguen ahi.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.auth import db as auth_db
from app.auth import schema_compat
from app.auth.db import BOOTSTRAP_KEY
from app.auth.models import User

# ---------------------------------------------------------------------------
# Codigos ESTABLES. Son API: la prueba que sostiene una garantia comprueba el
# CODIGO, nunca la redaccion. Repo publico: ni rutas, ni trazas, ni str(exc).
# ---------------------------------------------------------------------------

log = logging.getLogger("s9k.auth.bootstrap")

#: Estados de instalacion.
BOOTSTRAP_PENDIENTE = "BOOTSTRAP_PENDIENTE"
BOOTSTRAP_COMPLETADO = "BOOTSTRAP_COMPLETADO"

#: Fallo de almacenamiento del estado de instalacion (condicion fail-closed).
AUTH_STORE_UNAVAILABLE = "AUTH_STORE_UNAVAILABLE"

#: Rechazos del alta del primer administrador.
BOOTSTRAP_YA_COMPLETADO = "BOOTSTRAP_YA_COMPLETADO"
BOOTSTRAP_USUARIO_VACIO = "BOOTSTRAP_USUARIO_VACIO"
BOOTSTRAP_USUARIO_DUPLICADO = "BOOTSTRAP_USUARIO_DUPLICADO"

#: Rol del primer administrador. NO es un dato del formulario: esta operacion
#: crea POR DEFINICION un administrador, asi que el navegador no decide nada.
ROL_PRIMER_ADMIN = "admin"

#: Ruta de la base que ESTE PROCESO dejo lista al arrancar, o None si el
#: arranque no llego a correr. Es memoria de proceso a proposito: no hay nada
#: en disco que distinga «la base no existe todavia» de «la base existia y ha
#: desaparecido», y esa distincion es justo la que hace falta.
_base_lista_en: Optional[str] = None


def registrar_base_lista(db_path: Path) -> None:
    """El arranque declara que dejo la base en su sitio. Lo llama `_startup_auth`."""
    global _base_lista_en
    _base_lista_en = str(Path(db_path))


def base_desaparecida(db_path: Path) -> bool:
    """True si la base que este proceso dejo lista YA NO ESTA.

    NO es «no existe»: sobre una instalacion nueva la base tampoco existe, y
    ahi la ausencia SI es una primera instalacion legitima --es el estado A de
    este corte, y `/setup/admin` tiene que crearla--. La distincion es
    «existia al arrancar y ha desaparecido», y eso solo lo sabe el proceso.

    Por que importa: `estado_instalacion` MIGRA, es decir CREA. Sin esta
    comprobacion, borrar `auth.db` con el servicio vivo --un volumen
    desmontado, una restauracion a medias, un `S9K_AUTH_DB_PATH` que deja de
    resolver-- hace que la guarda de `/setup/admin` fabrique una base vacia y
    vuelva a servir la pantalla de configuracion inicial, anonima, con los
    datos reales del producto detras. Medido por HTTP sobre el codigo anterior:
    GET /setup/admin -> 200 y la base recreada.
    """
    if _base_lista_en is None:
        return False
    p = Path(db_path)
    return str(p) == _base_lista_en and not p.exists()


class BootstrapStorageError(RuntimeError):
    """El estado de instalacion NO se pudo determinar: fail-closed.

    Lleva `code` estable. El detalle tecnico va al log del servidor, nunca al
    cliente.
    """

    def __init__(self, message: str, code: str = AUTH_STORE_UNAVAILABLE):
        super().__init__(message)
        self.code = code


class BootstrapCerrado(RuntimeError):
    """El bootstrap ya estaba completado: el alta se rechaza."""

    code = BOOTSTRAP_YA_COMPLETADO


@dataclass(frozen=True)
class EstadoInstalacion:
    """Lo que el servidor sabe de la instalacion, en una pieza.

    `completado` es el unico dato que decide si `/setup/admin` existe.
    `base_existia` sirve para el diagnostico, no para la decision.
    """

    completado: bool
    base_existia: bool

    @property
    def codigo(self) -> str:
        return BOOTSTRAP_COMPLETADO if self.completado else BOOTSTRAP_PENDIENTE


# ---------------------------------------------------------------------------
# Lectura del sello
# ---------------------------------------------------------------------------

def sello_puesto(conn: sqlite3.Connection) -> bool:
    """True si el SELLO PERSISTENTE esta escrito. Lectura pura.

    Una tabla `install_state` ausente significa que la base es anterior a la
    v4 y todavia no ha migrado; aqui NO se asume «pendiente» por ausencia: se
    propaga como fallo de almacenamiento, porque quien lee esto ya paso por
    `ensure_migrated` y la tabla tiene que estar.
    """
    try:
        row = conn.execute(
            "SELECT value FROM install_state WHERE key = ?", (BOOTSTRAP_KEY,)
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise BootstrapStorageError(f"install_state no consultable: {exc}") from exc
    return row is not None and str(row[0]).lower() == "true"


def hay_usuarios(conn: sqlite3.Connection) -> bool:
    """True si la base tiene ALGUNA fila de usuario (activa o no)."""
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    except sqlite3.DatabaseError as exc:
        raise BootstrapStorageError(f"tabla de usuarios no consultable: {exc}") from exc


def bootstrap_completado(conn: sqlite3.Connection) -> bool:
    """True si esta instalacion ya esta provisionada. PEGAJOSO.

    Dos mitades, y la segunda es la que hay que mirar con lupa:

    1. EL SELLO PERSISTENTE. Es la autoridad. Una vez escrito no se retira.
    2. LA INFERENCIA POR EFECTO: una base que YA TIENE USUARIOS esta
       provisionada, venga su sello de donde venga. Cubre a quien creo
       usuarios por un camino que no sella (`cli.auth create-user`,
       `/admin/users/new`, un aprovisionamiento propio) sobre una base ya v4,
       donde la migracion nunca tuvo ocasion de sellar.

    LA INFERENCIA ESCRIBE EL SELLO, y eso NO es un detalle de rendimiento: es
    lo unico que la hace irreversible. Sin persistirla, «hay usuarios» es una
    CUENTA VIVA --medido por HTTP sobre este mismo codigo: base v4 sin sello,
    alta por `create_user`, la puerta cierra; `DELETE FROM users`, y la puerta
    VUELVE A ABRIRSE anonima sobre una instalacion con datos--. Escrito el
    sello, borrar o desactivar a todos los usuarios ya no reabre nada.

    POR QUE AQUI Y NO EN CADA CAMINO DE ALTA: sellar en `create-user`, en
    `/admin/users/new` y en el proximo sitio que cree un usuario es una LISTA
    que hay que acordarse de actualizar, y este repositorio ya decidio dos
    veces que eso no vale (ver la cabecera de `scripts/route_map/gate.py`). El
    alta nueva que nadie recuerde anadir a la lista reabriria el agujero en
    silencio. Derivarlo del EFECTO --existe al menos un usuario-- no hay que
    recordarlo.

    Si el sello no se puede escribir (base de solo lectura, disco lleno), la
    RESPUESTA sigue siendo «completado»: se pierde la persistencia, no la
    negativa. Fallar hacia el lado abierto seria justo lo contrario.
    """
    if sello_puesto(conn):
        return True
    if not hay_usuarios(conn):
        return False
    try:
        marcar_completado(conn)
    except sqlite3.DatabaseError:
        log.error(
            "[%s] no se pudo persistir el sello de instalacion inferido; la "
            "puerta sigue cerrada en esta peticion, pero podria reabrirse si "
            "se vaciara la tabla de usuarios.", BOOTSTRAP_COMPLETADO,
        )
    return True


def estado_instalacion(db_path: Path) -> EstadoInstalacion:
    """Estado de instalacion leido del SERVIDOR, o fail-closed con diagnostico.

    Tres desenlaces, no dos:

    * base ausente / fichero vacio / base sin tablas -> PRIMERA INSTALACION:
      se crea (migra) y queda PENDIENTE;
    * base valida -> se lee el sello;
    * base ilegible, no-SQLite, sin version o fuera de rango ->
      :class:`BootstrapStorageError`. NO es una primera instalacion.
    """
    path = Path(db_path)
    existia = path.exists() and path.stat().st_size > 0

    try:
        schema_compat.assert_compatible(path)
        auth_db.ensure_migrated(path)
    except schema_compat.SchemaCompatibilityError as exc:
        raise BootstrapStorageError(
            f"esquema de auth no utilizable [{exc.code}]: {exc}"
        ) from exc
    except (sqlite3.DatabaseError, OSError) as exc:
        raise BootstrapStorageError(
            f"almacen de auth inaccesible: {exc}"
        ) from exc

    try:
        with auth_db.get_conn(path) as conn:
            completado = bootstrap_completado(conn)
    except sqlite3.DatabaseError as exc:
        raise BootstrapStorageError(f"almacen de auth inaccesible: {exc}") from exc

    return EstadoInstalacion(completado=completado, base_existia=existia)


# ---------------------------------------------------------------------------
# Sellado
# ---------------------------------------------------------------------------

def marcar_completado(conn: sqlite3.Connection) -> None:
    """Sella el bootstrap sin crear usuario (camino de la CLI).

    Idempotente. Se usa cuando el primer administrador se crea por otra via
    legitima —`cli.auth create-admin`— para que esa instalacion NO quede con
    la puerta anonima abierta.
    """
    conn.execute(
        "INSERT OR IGNORE INTO install_state (key, value, set_at) VALUES (?, 'true', ?)",
        (BOOTSTRAP_KEY, auth_db._utcnow()),
    )
    conn.commit()


def crear_primer_admin(
    db_path: Path,
    *,
    username: str,
    display_name: str,
    password_hash: str,
    must_change_password: bool = False,
) -> User:
    """Crea el primer administrador Y sella el bootstrap, ATOMICAMENTE.

    La exclusion mutua NO es «leer el estado y luego escribir» (eso deja una
    ventana entre la lectura y la escritura por la que caben dos navegadores):
    es la PRIMARY KEY de `install_state`. La transaccion empieza con
    ``BEGIN IMMEDIATE`` —toma el candado de escritura antes de nada— e inserta
    el sello PRIMERO. La segunda peticion concurrente choca con
    `IntegrityError` y se rechaza; su usuario no llega a existir porque el
    rollback deshace la transaccion entera.

    El rol no se recibe: lo fija :data:`ROL_PRIMER_ADMIN`.
    """
    username = (username or "").strip()
    if not username:
        raise ValueError(BOOTSTRAP_USUARIO_VACIO)

    path = Path(db_path)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        # isolation_level=None: el control de la transaccion es explicito, sin
        # BEGIN implicito de sqlite3 que abriria en modo DEFERRED.
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            try:
                conn.execute(
                    "INSERT INTO install_state (key, value, set_at) VALUES (?, 'true', ?)",
                    (BOOTSTRAP_KEY, auth_db._utcnow()),
                )
            except sqlite3.IntegrityError as exc:
                raise BootstrapCerrado(
                    "el bootstrap ya estaba completado en esta instalacion"
                ) from exc

            try:
                user_id = auth_db.insert_user_row(
                    conn,
                    username=username,
                    display_name=display_name or username,
                    password_hash=password_hash,
                    role=ROL_PRIMER_ADMIN,
                    must_change_password=must_change_password,
                    created_by="setup",
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(BOOTSTRAP_USUARIO_DUPLICADO) from exc

            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

        user = auth_db.get_user_by_id(conn, user_id)
    finally:
        conn.close()

    assert user is not None  # recien insertado dentro de la transaccion
    return user


def hay_admin_activo(db_path: Path) -> bool:
    """Utilidad de diagnostico. NO decide si /setup/admin existe."""
    with auth_db.get_conn(Path(db_path)) as conn:
        return auth_db.count_active_admins(conn) > 0
