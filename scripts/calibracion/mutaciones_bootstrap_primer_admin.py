#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CALIBRACIÓN del corte «bootstrap web del primer administrador».

Mismo motor que `negacion_a_distancia.py` y `veracidad_tarjeta_review.py`, del
que esto copia el contrato a propósito: un verde sólo vale si la prueba que lo
da es CAPAZ DE PONERSE ROJA, y roja POR SU CAUSA. Cada mutación vuelve a meter
UN defecto —uno cada vez, sobre el código real, no sobre una copia— y se
comprueba:

    1. que los casos que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa, no un código de estado pelado.

LAS MUTACIONES SE REFERENCIAN POR NOMBRE, nunca por índice.

EL CALIBRADOR SE CALIBRA A SÍ MISMO: antes de mutar comprueba que la suite está
VERDE, que el árbol TRACKED está limpio, y que cada mutación MUERDE —que el
texto que dice sustituir existía, aparecía UNA vez y cambió—. Después restaura
y verifica la restauración POR EFECTO.

EL RECUENTO SALE DEL FICHERO: el total es `len(MUTACIONES)`.

EL CRUCE: al final compara los casos que la suite RECOLECTA (`--collect-only`,
no una lista escrita aquí) contra los rojos REALES.

EL TECHO DE ESTE CALIBRADOR, dicho entero:
  * Muta por SUSTITUCIÓN DE TEXTO EXACTO sobre el fuente. NO es una red AST: no
    ve alias, ni reexportaciones, ni una segunda copia de la misma lógica en
    otro módulo. Si mañana hubiera un segundo camino de alta de administrador
    (otro router, otra CLI), estas mutaciones seguirían tocando el de aquí y el
    rojo no llegaría. Lo que sí garantiza es que el texto que dice mutar existe
    y cambió.
  * MIRA UNA SOLA SUITE (`SUITE`, constante única). Un fichero de test nuevo
    del mismo corte sería INVISIBLE para el cruce.
  * COLAPSA LA PARAMETRIZACIÓN (`split("[")[0]`): los cuatro parámetros de
    `test_cond5_el_rol_enviado_por_el_cliente_se_ignora` cuentan como UN caso.
    La cifra del cruce es la COLAPSADA, y por tanto OPTIMISTA.
  * NO mide despliegue, ni un navegador de verdad, ni TLS, ni el proxy inverso.
    Las mediciones con `uvicorn` real (incluida la concurrencia de 8 peticiones
    simultáneas) están en el informe del corte, no aquí.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
VIEWER = RAIZ / "viewer"
SETUP = VIEWER / "app" / "routers" / "setup.py"
BOOT = VIEWER / "app" / "auth" / "bootstrap.py"
AUTHDB = VIEWER / "app" / "auth" / "db.py"
SEGURIDAD = VIEWER / "app" / "auth" / "security.py"
RUTAS_AUTH = VIEWER / "app" / "routers" / "auth.py"
SUITE = "tests/test_bootstrap_primer_admin.py"

#: La mitad de la regla de cierre que vive en `bootstrap_completado`.
CLAUSULA_USUARIOS = (
    '        hay_usuarios = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0'
)


@dataclass(frozen=True)
class Mutacion:
    """Un defecto reintroducido, con lo que DEBE caer y con qué debe decirlo."""

    nombre: str
    fichero: Path
    viejo: str
    nuevo: str
    #: Casos que tienen que ponerse rojos. Se comparan por subcadena del nodeid.
    caen: tuple[str, ...]
    #: Fragmento que TIENE que aparecer en la salida del rojo. Es la CAUSA.
    dice: str
    porque: str = ""
    extra: tuple[tuple[Path, str, str], ...] = field(default_factory=tuple)


MUTACIONES: tuple[Mutacion, ...] = (
    # ---- EL AGUJERO QUE EL OPERADOR CORRIGIÓ ANTES DE EMPEZAR ------------
    Mutacion(
        nombre="la-puerta-vuelve-a-decidirse-por-la-cuenta-de-administradores",
        fichero=SETUP,
        viejo="    if estado.completado:",
        nuevo=("    import app.auth.db as _adb\n"
               "    with _adb.get_conn(_db_path()) as _c:\n"
               "        estado_completado = _adb.count_active_admins(_c) > 0\n"
               "    if estado_completado:"),
        caen=("test_cond1_quedarse_sin_administradores_NO_reabre_la_puerta",),
        dice="LA PUERTA DE BOOTSTRAP SE REABRIO AL DESACTIVAR AL ULTIMO",
        porque=(
            "Es el defecto exacto del enunciado: `count_active_admins() == 0` "
            "es una cuenta VIVA y quedarse sin administradores reabriría una "
            "puerta anónima de creación de administrador."
        ),
    ),
    # ---- CONDICIÓN 2: el POST comprueba en servidor ----------------------
    Mutacion(
        nombre="el-post-confia-en-que-el-get-ya-miro",
        fichero=SETUP,
        viejo=("    # El POST NO confia en que el GET se haya hecho: repite la comprobacion.\n"
               "    cortar = _guarda(request)"),
        nuevo=("    # El POST NO confia en que el GET se haya hecho: repite la comprobacion.\n"
               "    cortar = None"),
        caen=("test_C_completado_la_ruta_no_existe_en_GET_ni_en_POST",),
        dice="EL POST NO COMPRUEBA EL ESTADO EN SERVIDOR",
        porque=(
            "Ocultar el formulario no cierra nada: lo que hay que cerrar es el "
            "POST directo, que no pasa por ninguna pantalla."
        ),
    ),
    # ---- CONDICIÓN 3: atomicidad ----------------------------------------
    Mutacion(
        nombre="el-sello-deja-de-ser-el-candado",
        fichero=BOOT,
        viejo='                    "INSERT INTO install_state (key, value, set_at) VALUES (?, \'true\', ?)",',
        nuevo='                    "INSERT OR IGNORE INTO install_state (key, value, set_at) VALUES (?, \'true\', ?)",',
        caen=("test_cond3_ocho_procesos_a_la_vez_producen_exactamente_un_administrador",),
        dice="LA CREACION DEL PRIMER ADMINISTRADOR NO ES ATOMICA",
        porque=(
            "`OR IGNORE` convierte el choque de clave primaria —que es LA "
            "exclusión mutua— en un silencio: todos los procesos siguen y "
            "crean su propio administrador inicial."
        ),
    ),
    # ---- CONDICIÓN 4: CSRF ----------------------------------------------
    Mutacion(
        nombre="el-bootstrap-se-salta-el-csrf",
        fichero=SETUP,
        viejo="    if not validate_login_csrf(",
        nuevo="    if False and not validate_login_csrf(",
        caen=("test_cond4_csrf_invalido_rechaza_y_no_crea_nada",
              "test_cond4_un_token_de_login_no_sirve_en_el_bootstrap"),
        dice="EL BOOTSTRAP ACEPTA UN POST SIN CSRF VALIDO",
        porque=(
            "«Todavía no hay sesión» es justo la excusa con la que este "
            "formulario se quedaría sin CSRF."
        ),
    ),
    Mutacion(
        nombre="los-dos-formularios-anonimos-comparten-token",
        fichero=SETUP,
        viejo="        csrf_token, cookie_token, secret=cfg.S9K_CSRF_SECRET, purpose=SETUP_PURPOSE",
        nuevo="        csrf_token, cookie_token, secret=cfg.S9K_CSRF_SECRET",
        caen=("test_cond4_un_token_de_login_no_sirve_en_el_bootstrap",),
        dice="UN TOKEN CSRF EMITIDO PARA OTRO FORMULARIO VALE EN EL BOOTSTRAP",
        porque=(
            "Sin el propósito firmado, un token emitido en /login vale en "
            "/setup/admin. Distingue «hay CSRF» de «el CSRF es de este "
            "formulario»."
        ),
    ),
    # ---- CONDICIÓN 5: el rol no lo decide el navegador -------------------
    Mutacion(
        nombre="el-rol-del-primer-admin-deja-de-estar-fijado",
        fichero=BOOT,
        viejo="                    role=ROL_PRIMER_ADMIN,",
        nuevo='                    role="viewer",',
        caen=("test_cond5_el_rol_enviado_por_el_cliente_se_ignora",),
        dice="EL NAVEGADOR DECIDIO EL ROL DEL PRIMER ADMINISTRADOR",
        porque=(
            "Mide el EFECTO en la base, que es lo que un test de firma no ve."
        ),
    ),
    Mutacion(
        nombre="el-endpoint-acepta-un-rol-del-formulario",
        fichero=SETUP,
        viejo='    csrf_token: str = Form(default=""),\n):',
        nuevo='    csrf_token: str = Form(default=""),\n    role: str = Form(default="viewer"),\n):',
        caen=("test_cond5_el_endpoint_no_declara_ningun_parametro_de_rol",),
        dice="EL ENDPOINT DEL BOOTSTRAP DECLARA UN PARAMETRO DE ROL",
        porque=(
            "El parámetro puede aparecer sin llegar a usarse todavía; el "
            "testigo de firma cae ahí, antes de que alguien lo conecte."
        ),
    ),
    # ---- CONDICIÓN 6: las mismas reglas ---------------------------------
    Mutacion(
        nombre="el-bootstrap-se-monta-sus-propias-reglas-de-contrasena",
        fichero=SETUP,
        viejo="    errores += validate_password(password, username)",
        nuevo=("    if len(password) < 6:\n"
               "        errores.append(\"contrasena corta\")"),
        caen=("test_cond6_las_reglas_son_LAS_MISMAS_funcion_que_la_pantalla_existente",),
        dice="EL BOOTSTRAP NO APLICA LAS MISMAS REGLAS DE CONTRASENA",
        porque=(
            "Un segundo validador es un segundo sistema de usuarios por la "
            "puerta de atrás: el mínimo se relaja sólo aquí y nadie se entera."
        ),
    ),
    # ---- CONDICIÓN 7: AUSENCIA != ERROR ---------------------------------
    Mutacion(
        nombre="un-almacen-ilegible-se-lee-como-instalacion-nueva",
        fichero=BOOT,
        viejo=("    except schema_compat.SchemaCompatibilityError as exc:\n"
               "        raise BootstrapStorageError(\n"
               "            f\"esquema de auth no utilizable [{exc.code}]: {exc}\"\n"
               "        ) from exc"),
        nuevo=("    except schema_compat.SchemaCompatibilityError:\n"
               "        return EstadoInstalacion(completado=False, base_existia=existia)"),
        caen=("test_cond7_base_corrupta_NO_es_primera_instalacion",),
        dice="UN ALMACEN DE AUTH ILEGIBLE SE ESTA LEYENDO COMO PRIMERA",
        porque=(
            "Es el colapso que el enunciado marca como el más fácil de perder: "
            "ausencia y error acabando en el mismo sitio."
        ),
    ),
    Mutacion(
        nombre="la-ausencia-de-base-vuelve-a-abortar-el-arranque",
        fichero=SEGURIDAD,
        viejo="        if problem.code == AUTH_DB_PATH_MISSING:",
        nuevo="        if False:",
        caen=("test_A_sin_base_el_servicio_arranca_y_muestra_configuracion_inicial",
              "test_cond7_base_ausente_SI_es_primera_instalacion"),
        dice="AuthSecurityError",
        porque=(
            "Es el estado A original: RC=3 y cero superficie HTTP. El rojo "
            "llega por el arranque, antes de cualquier aserción, y nombra la "
            "excepción que lo aborta."
        ),
    ),
    # ---- ESTADO B: el login conduce -------------------------------------
    Mutacion(
        nombre="el-login-vuelve-a-fingir-credenciales-incorrectas",
        fichero=RUTAS_AUTH,
        viejo="        return not bootstrap.estado_instalacion(db_path).completado",
        nuevo="        return False",
        caen=("test_B_login_no_finge_credenciales_incorrectas",
              "test_compat_instalacion_v3_sin_usuarios_queda_PENDIENTE"),
        dice="EL LOGIN NO CONDUCE A LA CONFIGURACION INICIAL",
        porque=(
            "Es el defecto B medido en la base: el producto no distingue «base "
            "vacía» de «te has equivocado»."
        ),
    ),
    # ---- COMPATIBILIDAD HACIA ATRÁS: el caso más peligroso ---------------
    Mutacion(
        nombre="una-instalacion-ya-provisionada-despierta-con-la-puerta-abierta",
        fichero=AUTHDB,
        viejo="                if ya_hay_usuarios:",
        nuevo="                if False:",
        caen=("test_compat_instalacion_con_admin_de_CLI_queda_CERRADA",),
        dice="CON LA PUERTA ANONIMA ABIERTA",
        porque=(
            "El caso real y más peligroso: una instalación desplegada, con "
            "administradores creados por CLI, migrando a v4 y quedando con el "
            "bootstrap ABIERTO. La protección es DOBLE a propósito (el sello "
            "que pone la migración y la condición «ya hay usuarios», que sólo "
            "cierra), así que la mutación retira LAS DOS: quitar una sola deja "
            "la suite verde, y eso no sería un control ciego sino redundancia "
            "declarada. Cuál sostiene qué por separado lo dice la mutación "
            "`la-segunda-condicion-que-solo-cierra-desaparece`."
        ),
        extra=((BOOT,
                '        hay_usuarios = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0',
                "        hay_usuarios = False"),),
    ),
    Mutacion(
        nombre="provisionar-por-cli-deja-la-puerta-abierta",
        fichero=BOOT,
        viejo=('    conn.execute(\n'
               '        "INSERT OR IGNORE INTO install_state (key, value, set_at) VALUES (?, \'true\', ?)",\n'
               '        (BOOTSTRAP_KEY, auth_db._utcnow()),\n'
               '    )\n'
               '    conn.commit()'),
        nuevo="    return None",
        caen=("test_compat_create_admin_de_la_CLI_cierra_el_bootstrap",),
        dice="PROVISIONAR POR CLI DEJA LA PUERTA ANONIMA ABIERTA",
        porque=(
            "`cli.auth create-admin` sigue siendo una vía vigente: si no "
            "sella, la instalación queda sirviendo /setup/admin a cualquiera. "
            "Misma protección doble que la mutación anterior, y por eso se "
            "retiran las dos mitades."
        ),
        extra=((BOOT,
                '        hay_usuarios = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0',
                "        hay_usuarios = False"),),
    ),
    Mutacion(
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
    ),
    # ---- QUE NO SE CIERRE DE MÁS ----------------------------------------
    Mutacion(
        nombre="la-guarda-corta-siempre-y-la-pantalla-nunca-aparece",
        fichero=SETUP,
        viejo="    if not get_auth_settings().S9K_AUTH_ENABLED:",
        nuevo="    if True:",
        caen=("test_A_sin_base_el_servicio_arranca_y_muestra_configuracion_inicial",
              "test_cond7_base_ausente_SI_es_primera_instalacion",
              "test_compat_instalacion_v3_sin_usuarios_queda_PENDIENTE",
              "test_cond1_lo_que_decide_es_el_SELLO_y_no_otra_cosa"),
        dice="SIN BASE, LA INSTALACION NO OFRECE CONFIGURACION INICIAL",
        porque=(
            "El 404 del estado C puede salir por el motivo equivocado. Esta "
            "mutación apaga la ruta ENTERA: los testigos que exigen que la "
            "pantalla SÍ esté son los que distinguen un cierre correcto de un "
            "apagado general."
        ),
    ),
    Mutacion(
        nombre="cerrar-el-bootstrap-se-lleva-por-delante-el-alta-normal",
        fichero=VIEWER / "app" / "routers" / "admin.py",
        viejo='@router.get("/users/new", response_class=HTMLResponse)',
        nuevo='@router.get("/users/new-desmontada", response_class=HTMLResponse)',
        caen=("test_C_el_login_normal_y_admin_users_new_siguen_funcionando",
              "test_compat_instalacion_con_admin_de_CLI_queda_CERRADA"),
        dice="LA PUERTA SE CERRO DE MAS",
        porque=(
            "El simétrico del enunciado: una puerta que se cierra de más "
            "tampoco vale. Si el alta normal desapareciera, el corte estaría "
            "«seguro» y roto."
        ),
    ),
)


def _pytest(selector: str | None = None) -> subprocess.CompletedProcess:
    # `--color=no` no es cosmético: con color, las líneas del resumen empiezan
    # por una secuencia de escape y `startswith("FAILED")` no casa nunca.
    orden = [sys.executable, "-m", "pytest", SUITE, "-q", "-p", "no:randomly",
             "--color=no"]
    if selector:
        orden += ["-k", selector]
    return subprocess.run(orden, cwd=VIEWER, capture_output=True, text=True)


def _casos_del_fichero() -> set[str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "--collect-only", "-q",
         "--color=no", "-p", "no:randomly"],
        cwd=VIEWER, capture_output=True, text=True,
    )
    casos = {
        linea.split("::")[-1].split("[")[0].strip()
        for linea in r.stdout.splitlines() if "::" in linea
    }
    if not casos:
        raise AssertionError(
            "EL CRUCE NO RECOLECTÓ NINGÚN CASO. Sin casos, «ninguno sin "
            "calibrar» sería verdad por vacío.\n"
            + r.stdout[-2000:] + r.stderr[-2000:]
        )
    return casos


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        if ".git" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio() -> bool:
    """TRACKED únicamente: es lo que la mutación puede destruir y lo que
    `git checkout --` puede devolver."""
    r = subprocess.run(
        ["git", "diff", "--stat", "--"], cwd=RAIZ, capture_output=True, text=True
    )
    return r.stdout.strip() == ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo", help="calibrar una mutación por NOMBRE")
    args = parser.parse_args()

    if not _arbol_limpio():
        print("ABORTA: el árbol tiene cambios sin commitear. Una mutación "
              "sobre un árbol sucio no se puede restaurar por efecto.")
        return 2

    seleccionadas = MUTACIONES
    if args.solo:
        seleccionadas = tuple(m for m in MUTACIONES if m.nombre == args.solo)
        if not seleccionadas:
            print(f"ABORTA: no hay ninguna mutación llamada {args.solo!r}. "
                  f"Hay: {[m.nombre for m in MUTACIONES]}")
            return 2

    _purgar_pycache()
    base = _pytest()
    if base.returncode != 0:
        print("ABORTA: la suite YA está roja sin mutar. Cualquier rojo de "
              "abajo sería suyo, no de la mutación.")
        print(base.stdout[-3000:])
        return 2
    print(f"BASE VERDE. {SUITE}\n")

    total = len(seleccionadas)
    fallos: list[str] = []
    rojos_vistos: set[str] = set()
    print(f"{total} mutaciones declaradas en este fichero.\n")

    for mut in seleccionadas:
        print("=" * 74)
        print(f"MUTACIÓN  {mut.nombre}")
        print(f"  fichero {mut.fichero.relative_to(RAIZ)}")
        print(f"  porqué  {mut.porque}")
        parches = ((mut.fichero, mut.viejo, mut.nuevo),) + mut.extra
        try:
            for fichero, viejo, nuevo in parches:
                texto = fichero.read_text(encoding="utf-8")
                if texto.count(viejo) != 1:
                    raise AssertionError(
                        f"el texto a mutar aparece {texto.count(viejo)} veces "
                        f"en {fichero.name} (se esperaba 1). El código se ha "
                        f"movido: esta mutación NO estaba mordiendo."
                    )
                fichero.write_text(texto.replace(viejo, nuevo), encoding="utf-8")
            if _arbol_limpio():
                raise AssertionError(
                    "tras escribir la mutación, `git diff` no ve NINGÚN "
                    "cambio. La mutación no llegó al disco."
                )
            _purgar_pycache()

            res = _pytest()
            salida = res.stdout + res.stderr
            if res.returncode == 0:
                fallos.append(
                    f"{mut.nombre}: LA SUITE SIGUE VERDE CON EL DEFECTO "
                    f"PUESTO. Ningún control vigila esto."
                )
                print("  RESULTADO  *** VERDE CON EL DEFECTO — CONTROL CIEGO ***")
                continue

            rojos = [
                linea.split("::")[-1].split(" ")[0]
                for linea in salida.splitlines()
                if linea.startswith("FAILED") or linea.startswith("ERROR ")
            ]
            faltan = [c for c in mut.caen if not any(c in r for r in rojos)]
            if faltan:
                fallos.append(
                    f"{mut.nombre}: se esperaba que cayeran {faltan} y NO "
                    f"cayeron. Cayeron: {rojos}"
                )
                print(f"  RESULTADO  rojo, pero NO cayeron {faltan}")
            else:
                print(f"  ROJOS      {len(rojos)}: {sorted(set(r.split('[')[0] for r in rojos))}")
            rojos_vistos.update(r.split("[")[0] for r in rojos)

            if mut.dice not in salida:
                fallos.append(
                    f"{mut.nombre}: el rojo NO DICE SU CAUSA. Se esperaba el "
                    f"mensaje {mut.dice!r} y no aparece."
                )
                print(f"  MENSAJE    *** FALTA {mut.dice!r} ***")
            else:
                print(f"  MENSAJE    OK — el rojo dice: «{mut.dice}»")
        finally:
            for fichero, _, _ in parches:
                subprocess.run(
                    ["git", "checkout", "--", str(fichero.relative_to(RAIZ))],
                    cwd=RAIZ, check=True,
                )
            _purgar_pycache()
            if not _arbol_limpio():
                print("  *** EL ÁRBOL NO QUEDÓ RESTAURADO. ABORTA. ***")
                return 3

    print("=" * 74)
    _purgar_pycache()
    final = _pytest()
    if final.returncode != 0:
        print("LA SUITE NO VOLVIÓ A VERDE tras restaurar. La calibración dejó "
              "el árbol tocado y sus resultados no valen.")
        print(final.stdout[-3000:])
        return 3

    if not args.solo:
        casos = _casos_del_fichero()
        huerfanos = sorted(casos - rojos_vistos)
        print(f"CRUCE: {len(casos)} casos recolectados, "
              f"{len(casos) - len(huerfanos)} enrojecen con alguna mutación.")
        if huerfanos:
            for h in huerfanos:
                print(f"  ::SIN CALIBRAR:: {h}")
            fallos.append(
                f"{len(huerfanos)} testigo(s) que NINGUNA mutación enrojece: "
                f"{huerfanos}. O comprueban algo que nada puede romper, o su "
                f"nombre promete más de lo que miden."
            )

    if fallos:
        print(f"CALIBRACIÓN FALLIDA — {len(fallos)} problemas sobre {total} "
              f"mutaciones:")
        for f in fallos:
            print("  * " + f)
        return 1
    print(f"CALIBRACIÓN OK — {total}/{total} mutaciones producen un rojo que "
          f"DICE SU CAUSA, y la suite vuelve a verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
