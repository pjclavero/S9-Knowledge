R='/home/ia02/S9-Knowledge/.claude/worktrees/agent-a099e22c532796ef0/'

def sub(path, old, new, n=1):
    p=R+path
    s=open(p).read()
    assert s.count(old)==n, (path, s.count(old), old[:70])
    open(p,'w').write(s.replace(old,new,n))
    print('OK', path)

NUEVOS = '''

def test_cond1_un_alta_por_un_camino_que_NO_sella_TAMPOCO_reabre(tmp_path):
    """EL NEGATIVO QUE FALTABA (hallazgo E1 de la revision independiente).

    Medido por HTTP sobre el codigo anterior: base v4 SIN sello --una
    instalacion nacida ya en v4, que por tanto nunca pasa por la migracion que
    sella--, alta por un camino que no sella (`cli.auth create-user`,
    `/admin/users/new`, un aprovisionamiento propio), y despues `DELETE FROM
    users`:

        GET /setup/admin  -> 200   sello: []
        [create_user]
        GET /setup/admin  -> 404   sello: []
        [DELETE FROM users]
        GET /setup/admin  -> 200   *** PUERTA REABIERTA ***

    La segunda mitad del predicado era una CUENTA VIVA y era, en esa base, lo
    unico que cerraba. Ahora la inferencia PERSISTE el sello, asi que el 404
    sobrevive al vaciado.

    ROJO SI: la inferencia por efecto vuelve a no escribir el sello.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password

    auth_db.ensure_migrated(db)  # base NACIDA en v4: la migracion no sella
    with auth_db.get_conn(db) as conn:
        assert not _sello(db), "una base v4 recien creada no puede traer sello"

    with _con_arranque() as c:
        assert c.get("/setup/admin").status_code == 200

        # Alta por una via legitima y vigente que NO sella.
        with auth_db.get_conn(db) as conn:
            auth_db.create_user(
                conn, username="admin-por-cli-ficticio", display_name="Admin CLI",
                password_hash=hash_password(PW_VALIDA), role="admin",
            )
        assert c.get("/setup/admin").status_code == 404
        assert _sello(db), (
            "LA INFERENCIA NO PERSISTIO EL SELLO: sigue siendo una cuenta viva")

        # Y ahora el vaciado, que antes reabria la puerta.
        con = sqlite3.connect(str(db))
        con.execute("DELETE FROM users")
        con.commit()
        con.close()

        g = c.get("/setup/admin")
        pp = c.post("/setup/admin", data={
            "username": "intruso-ficticio", "password": PW_VALIDA, "csrf_token": "x"})
        assert (g.status_code, pp.status_code) == (404, 404), (
            "LA PUERTA DE BOOTSTRAP SE REABRIO TRAS VACIAR LA TABLA DE USUARIOS "
            f"EN UNA BASE SIN SELLO: GET={g.status_code} POST={pp.status_code}")


def test_cond1_una_instalacion_con_un_unico_viewer_queda_CERRADA(tmp_path):
    """D2 DECLARADO, no descubierto: cerrar por «hay usuarios» cierra de mas.

    Un unico usuario `viewer` creado por CLI sobre una base v4 sin sello cierra
    `/setup/admin` aunque NO exista ningun administrador: esa instalacion se
    queda sin camino WEB para crear el primero y hay que usar la CLI.

    Es la cara simetrica del agujero E1 y se elige a conciencia. Entre «una
    instalacion con datos expone una puerta anonima de creacion de
    administrador» y «una instalacion rara necesita un comando», manda la
    primera: seguridad antes que ergonomia. La recuperacion es la misma que
    para «me he quedado sin administradores», que el operador ya declaro que
    sera otro mecanismo explicito.

    Este testigo existe para que ese coste este FIJADO: si alguien decide
    cambiarlo, tiene que venir aqui y decirlo.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password

    auth_db.ensure_migrated(db)
    with auth_db.get_conn(db) as conn:
        auth_db.create_user(
            conn, username="lector-ficticio", display_name="Lector",
            password_hash=hash_password(PW_VALIDA), role="viewer",
        )
        assert auth_db.count_active_admins(conn) == 0

    with _con_arranque() as c:
        r = c.get("/setup/admin")
        assert r.status_code == 404, (
            "CAMBIO NO DECLARADO: una instalacion con usuarios pero sin ningun "
            f"administrador vuelve a ofrecer el bootstrap ({r.status_code})")


def test_D1_el_login_comprueba_el_estado_ANTES_de_validar_el_cuerpo(tmp_path):
    """La ruta hermana, con el mismo criterio que `/setup/admin`.

    Un `POST /login` sin cuerpo sobre una instalacion sin primer administrador
    tiene que CONDUCIR a la configuracion inicial, no morir en un error de
    formulario: la guarda de estado corre antes que la validacion del cuerpo.

    ROJO SI: `csrf_token` vuelve a ser `Form(...)` obligatorio.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)

    with _con_arranque() as c:
        r = c.post("/login", data={})
        assert r.status_code == 303, (
            "EL LOGIN VALIDA EL CUERPO ANTES DE SU GUARDA: un POST vacio sobre "
            f"una instalacion sin administrador respondio {r.status_code}")
        assert r.headers["location"] == "/setup/admin"


def test_D1_el_formulario_incompleto_sigue_repintando_la_pagina(tmp_path):
    """Y el simetrico: quitar la obligatoriedad no puede empeorar el mensaje.

    Sobre una instalacion YA provisionada, un formulario incompleto tiene que
    seguir dando 400 con su frase, que es lo que producia el manejador de
    errores de validacion antes de este cambio.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        assert _crear_admin_por_pantalla(c).status_code == 303
        r = c.post("/login", data={})
        assert r.status_code == 400, r.status_code
        assert "Introduce el usuario y la contraseña" in r.text, (
            "EL FORMULARIO INCOMPLETO DEJO DE EXPLICARSE")
'''

sub('viewer/tests/test_bootstrap_primer_admin.py',
'''def _usuarios(db_path: Path):''',
'''def _sello(db_path: Path) -> bool:
    """True si el sello persistente esta escrito. Se lee de la BASE, no del
    servicio: lo que hay que comprobar es que quedo en disco."""
    con = sqlite3.connect(str(db_path))
    try:
        fila = con.execute(
            "SELECT value FROM install_state WHERE key = 'bootstrap_completed'"
        ).fetchone()
    finally:
        con.close()
    return fila is not None and str(fila[0]).lower() == "true"


def _usuarios(db_path: Path):''')

# Los nuevos casos van justo antes del bloque de CONDICION 3.
sub('viewer/tests/test_bootstrap_primer_admin.py',
'''# ---------------------------------------------------------------------------
# CONDICION 3 - atomicidad con concurrencia REAL''',
NUEVOS.strip('\n') + '''


# ---------------------------------------------------------------------------
# CONDICION 3 - atomicidad con concurrencia REAL''')
