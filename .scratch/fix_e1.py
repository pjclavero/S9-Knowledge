R='/home/ia02/S9-Knowledge/.claude/worktrees/agent-a099e22c532796ef0/'

def sub(path, old, new, n=1):
    p=R+path
    s=open(p).read()
    assert s.count(old)==n, (path, s.count(old), old[:70])
    open(p,'w').write(s.replace(old,new,n))
    print('OK', path)

# ---------------------------------------------------------------------------
# E1: la inferencia por cuenta PERSISTE el sello. Deja de ser una cuenta viva.
# ---------------------------------------------------------------------------
sub('viewer/app/auth/bootstrap.py',
'''def bootstrap_completado(conn: sqlite3.Connection) -> bool:
    """True si el sello esta puesto en esta conexion ya abierta.

    Una tabla `install_state` ausente significa que la base es anterior a la
    v4 y todavia no ha migrado; aqui NO se asume «pendiente» por ausencia: se
    propaga como fallo de almacenamiento, porque quien lee esto ya paso por
    `ensure_migrated` y la tabla tiene que estar.
    """
    try:
        row = conn.execute(
            "SELECT value FROM install_state WHERE key = ?", (BOOTSTRAP_KEY,)
        ).fetchone()
        if row is not None and str(row[0]).lower() == "true":
            return True
        # SEGUNDA CONDICION, y solo CIERRA: una base que ya tiene usuarios esta
        # provisionada, venga su sello de donde venga. Cubre a quien creo
        # usuarios por un camino que no sella (la CLI de alta de usuario
        # corriente, un aprovisionamiento propio) sobre una base ya v4, donde
        # la migracion no tuvo ocasion de sellar.
        #
        # Esto NO es `count_active_admins() == 0` con otro nombre: es monotona
        # en la direccion segura. Solo puede pasar de PENDIENTE a COMPLETADO,
        # nunca al reves, porque el sello persistente manda. Borrar o
        # desactivar al ultimo administrador deja el sello puesto y la puerta
        # cerrada.
        hay_usuarios = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    except sqlite3.DatabaseError as exc:
        raise BootstrapStorageError(
            f"install_state no consultable: {exc}"
        ) from exc
    return bool(hay_usuarios)''',
'''def sello_puesto(conn: sqlite3.Connection) -> bool:
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
    return True''')

# log en bootstrap.py
sub('viewer/app/auth/bootstrap.py',
'''from __future__ import annotations

import sqlite3''',
'''from __future__ import annotations

import logging
import sqlite3''')
sub('viewer/app/auth/bootstrap.py',
'''#: Estados de instalacion.''',
'''log = logging.getLogger("s9k.auth.bootstrap")

#: Estados de instalacion.''')

# la cabecera del modulo tambien lo decia mal
sub('viewer/app/auth/bootstrap.py',
'''    auth.db inexistente -> ensure_migrated() -> PENDIENTE -> /setup/admin abierto
    crear primer admin  -> TRANSACCION ATOMICA: sello + admin
    -> COMPLETADO -> /setup/admin cerrado PARA SIEMPRE -> login normal''',
'''    auth.db inexistente -> ensure_migrated() -> PENDIENTE -> /setup/admin abierto
    crear primer admin  -> TRANSACCION ATOMICA: sello + admin
    -> COMPLETADO -> /setup/admin cerrado PARA SIEMPRE -> login normal

Y una instalacion provisionada por cualquier OTRA via legitima (la CLI, la
pantalla de alta de usuarios) tambien queda sellada: la inferencia «ya hay
usuarios» ESCRIBE el sello la primera vez que se consulta. Si no lo escribiese
seria una cuenta viva y vaciar la tabla de usuarios reabriria la puerta.''')

# ---------------------------------------------------------------------------
# D1: /login tampoco valida el cuerpo antes de su guarda
# ---------------------------------------------------------------------------
sub('viewer/app/routers/auth.py',
'''async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    next: str = Form(default="/"),
):''',
'''async def login_submit(
    request: Request,
    # Mismo criterio que `/setup/admin`, y por la misma razon medida: un campo
    # `Form(...)` obligatorio que falta produce un 422/400 de validacion ANTES
    # de que corra ninguna guarda, asi que la comprobacion de estado --«esta
    # instalacion no tiene primer administrador»-- no llegaria a ejecutarse y
    # el operador recibiria un error de formulario en vez de la pantalla de
    # configuracion inicial. Lo que falte se responde abajo, con su mensaje.
    username: str = Form(default=""),
    password: str = Form(default=""),
    csrf_token: str = Form(default=""),
    next: str = Form(default="/"),
):''')
