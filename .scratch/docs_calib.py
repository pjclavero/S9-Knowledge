R='/home/ia02/S9-Knowledge/.claude/worktrees/agent-a099e22c532796ef0/'

def sub(path, old, new, n=1):
    p=R+path
    s=open(p).read()
    assert s.count(old)==n, (path, s.count(old), old[:70])
    open(p,'w').write(s.replace(old,new,n))
    print('OK', path)

# ---------------------------------------------------------------------------
# La frase del contrato de codigos decia que era imposible. NO lo era.
# ---------------------------------------------------------------------------
sub('docs/v3/52-codigos-de-excepcion-contrato.md',
'''El estado de instalación es **persistente e irreversible**: vive en
`install_state['bootstrap_completed']` (esquema `auth.db` v4) y **no** se
deriva de `count_active_admins()`. Quedarse sin administradores **no** reabre
`/setup/admin`; la recuperación de ese caso será un mecanismo explícito aparte.
`AUTH_STORE_UNAVAILABLE` es el fail-closed de la condición «una base corrupta o
inaccesible NO es una primera instalación».''',
'''El estado de instalación es **persistente e irreversible**: vive en
`install_state['bootstrap_completed']` (esquema `auth.db` v4) y **no** se
deriva de `count_active_admins()`. Quedarse sin administradores **no** reabre
`/setup/admin`; la recuperación de ese caso será un mecanismo explícito aparte.
`AUTH_STORE_UNAVAILABLE` es el fail-closed de la condición «una base corrupta o
inaccesible NO es una primera instalación».

El predicado tiene **dos mitades**: el sello y la inferencia «esta base ya
tiene usuarios», que cubre las altas por caminos que no sellan
(`cli.auth create-user`, `/admin/users/new`). **La inferencia ESCRIBE el
sello**, y eso es lo que la hace irreversible: sin persistirla sería una cuenta
viva, y una revisión independiente lo midió por HTTP sobre este repositorio
—base v4 sin sello, alta por `create_user`, `DELETE FROM users`, y la puerta
anónima **volvía a abrirse** sobre una instalación con datos—. Una versión
anterior de este párrafo afirmaba que esa mitad «sólo cierra y no puede reabrir
nada»: **era falso**, y está corregido aquí porque quien lee la documentación
se fía de ella.

**Coste declarado**: como cierra cualquier usuario, una instalación con usuarios
pero **sin ningún administrador** se queda sin camino web para crear el primero
y hay que usar la CLI. Se elige a conciencia —seguridad antes que ergonomía— y
lo fija
`viewer/tests/test_bootstrap_primer_admin.py::test_cond1_una_instalacion_con_un_unico_viewer_queda_CERRADA`.''')

# ---------------------------------------------------------------------------
# El calibrador tiene que VER el agujero E1: su mutacion probaba que cierra,
# no que NO REABRE.
# ---------------------------------------------------------------------------
sub('scripts/calibracion/mutaciones_bootstrap_primer_admin.py',
'''#: La mitad de la regla de cierre que vive en `bootstrap_completado`.
CLAUSULA_USUARIOS = (
    \'        hay_usuarios = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0\'
)''',
'''#: La mitad de la regla de cierre que vive en `bootstrap_completado`: la
#: inferencia por efecto. Se muta su USO, no la funcion `hay_usuarios`, porque
#: lo que se quiere retirar es la consecuencia, no la consulta.
CLAUSULA_USUARIOS = "    if not hay_usuarios(conn):\\n        return False"

#: Lo que hace IRREVERSIBLE a esa inferencia: persistir el sello.
PERSISTIR_EL_SELLO = "        marcar_completado(conn)"''')

sub('scripts/calibracion/mutaciones_bootstrap_primer_admin.py',
'''EXTRA = (\'        extra=((BOOT,\\n\'''',
'''EXTRA = (\'        extra=((BOOT,\\n\'''')  # no-op sanity

sub('scripts/calibracion/mutaciones_bootstrap_primer_admin.py',
'''    Mutacion(
        nombre="la-segunda-condicion-que-solo-cierra-desaparece",
        fichero=BOOT,
        viejo=CLAUSULA_USUARIOS,
        nuevo="        hay_usuarios = False",
        caen=("test_cond1_lo_que_decide_es_el_SELLO_y_no_otra_cosa",),
        dice="SIN SELLO PERO CON USUARIOS LA PUERTA SE ABRE",
        porque=(
            "Aísla la mitad que las dos mutaciones de arriba retiran junto con "
            "el sello: una base con usuarios y sin sello —lo que deja un alta "
            "por un camino que no sella sobre una base ya v4— no es una "
            "primera instalación. Esta condición sólo CIERRA: no puede "
            "reabrir nada, y por eso no es `count_active_admins()` con otro "
            "nombre."
        ),
    ),''',
'''    Mutacion(
        nombre="la-inferencia-por-efecto-desaparece",
        fichero=BOOT,
        viejo=CLAUSULA_USUARIOS,
        nuevo="    if True:\\n        return False",
        caen=("test_cond1_lo_que_decide_es_el_SELLO_y_no_otra_cosa",
              "test_cond1_un_alta_por_un_camino_que_NO_sella_TAMPOCO_reabre",
              "test_cond1_una_instalacion_con_un_unico_viewer_queda_CERRADA"),
        dice="SIN SELLO PERO CON USUARIOS LA PUERTA SE ABRE",
        porque=(
            "Aísla la mitad que las dos mutaciones de arriba retiran junto con "
            "el sello: una base con usuarios y sin sello —lo que deja un alta "
            "por un camino que no sella sobre una base ya v4— no es una "
            "primera instalación."
        ),
    ),
    # ---- EL AGUJERO QUE LA REVISION INDEPENDIENTE ENCONTRO (E1) ----------
    Mutacion(
        nombre="la-inferencia-deja-de-persistir-el-sello",
        fichero=BOOT,
        viejo=PERSISTIR_EL_SELLO,
        nuevo="        pass",
        caen=("test_cond1_un_alta_por_un_camino_que_NO_sella_TAMPOCO_reabre",),
        dice="LA INFERENCIA NO PERSISTIO EL SELLO",
        porque=(
            "ESTE ES EL DEFECTO REAL QUE SE COLÓ EN LA RONDA 1, y el arnés NO "
            "LO VEÍA: la mutación de arriba prueba que la inferencia CIERRA, "
            "no que sea IRREVERSIBLE. Sin persistir el sello, «hay usuarios» "
            "es una cuenta viva: sobre una base v4 sin sello —una instalación "
            "nacida ya en v4 nunca pasa por la migración que sella— un alta "
            "por `create-user` cierra la puerta y un `DELETE FROM users` la "
            "vuelve a abrir, anónima, sobre una instalación con datos."
        ),
    ),''')
