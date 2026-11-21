#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibracion RC2-02 — `writer-schema` y las tres identidades de Neo4j.

Revierte, una a una, las garantias del arreglo DENTRO DEL PRODUCTO (y de la doc
que define los roles), corre la prueba que debe protegerlas y exige que se ponga
roja POR SU CAUSA (se comprueba el texto del fallo, no el color).

Antes de mutar nada corre el CONTROL NULO: la suite entera sin mutar tiene que
estar VERDE. Sin el, un rojo de un mutante podria ser el de una suite ya rota.

TECHO: mide contra el doble de driver de la suite. Lo que solo el servidor
demuestra vive en `viewer/tests/test_corte5_credencial_solo_lectura_neo4j_real.py`
(casos `test_rc2_02_*`, job «Viewer Tests» contra Neo4j Enterprise real).

USO
---
    python3 scripts/calibracion/mutaciones_rc2_02_writer_schema_verify.py

Requiere arbol sin cambios tracked: las mutaciones se revierten con
`git checkout --`, asi que hay que COMMITEAR antes de calibrar.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CLI = "data-engine/app/knowledge_v3/writer/schema_cli.py"
SCHEMA = "data-engine/app/knowledge_v3/writer/schema.py"
WRITER = "data-engine/app/knowledge_v3/writer/writer.py"
DRIVER = "data-engine/app/knowledge_v3/driver_neo4j.py"
README = "deploy/README.md"
SUITE = "data-engine/app/tests/test_writer_schema_verify_rc2_02.py"

_FIN_LECTOR = (
    '    "GRANT SHOW CONSTRAINT ON DATABASE {db} TO {role}",\n'
    '    "GRANT SHOW INDEX ON DATABASE {db} TO {role}",\n'
    ")\nSCHEMA_ROLE_PRIVILEGES"
)


class Mutacion:
    """Una garantia revertida, y la prueba que tiene que verlo."""

    def __init__(self, nombre, fichero, viejo, nuevo, prueba, esperado):
        self.nombre = nombre
        self.fichero = fichero
        self.viejo = viejo
        self.nuevo = nuevo
        self.prueba = prueba
        #: Fragmento que TIENE que aparecer en el fallo.
        self.esperado = esperado


MUTACIONES = [
    Mutacion(
        nombre="el Forbidden se reporta como «esquema incompleto»",
        fichero=CLI,
        viejo="        return RC_SIN_PRIVILEGIO\n",
        nuevo="        return RC_INCOMPLETO\n",
        prueba=f"{SUITE}::test_forbidden_es_codigo_de_autorizacion_no_incompleto",
        esperado="Forbidden no dio el rc de autorizacion",
    ),
    Mutacion(
        nombre="el README pierde SHOW CONSTRAINT del rol lector",
        fichero=README,
        viejo="GRANT SHOW CONSTRAINT ON DATABASE neo4j TO s9k_observador;\n",
        nuevo="",
        prueba=f"{SUITE}::test_readme_y_codigo_definen_los_mismos_tres_roles",
        esperado="diverge de la autoridad del codigo",
    ),
    Mutacion(
        nombre="el README pierde SHOW INDEX del rol lector",
        fichero=README,
        viejo="GRANT SHOW INDEX ON DATABASE neo4j TO s9k_observador;\n",
        nuevo="",
        prueba=f"{SUITE}::test_readme_y_codigo_definen_los_mismos_tres_roles",
        esperado="diverge de la autoridad del codigo",
    ),
    Mutacion(
        nombre="el codigo pierde SHOW INDEX del rol lector",
        fichero=SCHEMA,
        viejo=_FIN_LECTOR,
        nuevo=_FIN_LECTOR.replace('    "GRANT SHOW INDEX ON DATABASE {db} TO {role}",\n', ""),
        prueba=f"{SUITE}::test_cada_rol_concede_exactamente_su_lista_blanca[s9k_observador]",
        esperado="LISTA BLANCA ROTA",
    ),
    Mutacion(
        nombre="el rol lector gana GRANT INDEX (crear y BORRAR indices, sin palabra prohibida)",
        fichero=SCHEMA,
        viejo=_FIN_LECTOR,
        nuevo=_FIN_LECTOR.replace(
            ")\nSCHEMA_ROLE_PRIVILEGES",
            '    "GRANT INDEX ON DATABASE {db} TO {role}",\n)\nSCHEMA_ROLE_PRIVILEGES',
        ),
        prueba=f"{SUITE}::test_cada_rol_concede_exactamente_su_lista_blanca[s9k_observador]",
        esperado="LISTA BLANCA ROTA",
    ),
    Mutacion(
        nombre="is_forbidden vuelve a aceptar cualquier clase llamada Forbidden",
        fichero=SCHEMA,
        viejo='    return getattr(exc, "code", None) == NEO4J_FORBIDDEN_CODE\n',
        nuevo=('    return (getattr(exc, "code", None) == NEO4J_FORBIDDEN_CODE\n'
               '            or type(exc).__name__ == "Forbidden")\n'),
        prueba=(f"{SUITE}::test_lo_que_no_trae_el_codigo_forbidden_sigue_siendo_rc_error"
                "[clase-llamada-Forbidden-sin-codigo]"),
        esperado="is_forbidden acepta algo sin el codigo",
    ),
    Mutacion(
        nombre="is_forbidden acepta cualquier codigo de Neo4j",
        fichero=SCHEMA,
        viejo='    return getattr(exc, "code", None) == NEO4J_FORBIDDEN_CODE\n',
        nuevo='    return getattr(exc, "code", None) is not None\n',
        prueba=(f"{SUITE}::test_lo_que_no_trae_el_codigo_forbidden_sigue_siendo_rc_error"
                "[otro-codigo-neo4j]"),
        esperado="is_forbidden acepta algo sin el codigo",
    ),
    Mutacion(
        nombre="la denegacion de un indice se atribuye a CREATE CONSTRAINT",
        fichero=SCHEMA,
        viejo="        (OP_CREATE_INDEX, ENTITY_PARTIDA_INDEX_CYPHER),\n",
        nuevo="        (OP_CREATE_CONSTRAINT, ENTITY_PARTIDA_INDEX_CYPHER),\n",
        prueba=f"{SUITE}::test_la_cuenta_lectora_no_puede_crear_un_indice_que_falta",
        esperado="atribucion: la denegacion de un indice",
    ),
    Mutacion(
        nombre="el mensaje de la CLI arrastra el texto del servidor",
        fichero=CLI,
        viejo='            f"error_code={exc.code}: {_consejo(args.accion, exc, cuenta)}",\n',
        nuevo=('            f"error_code={exc.code}: {_consejo(args.accion, exc, cuenta)}"'
               ' f" ({exc.__cause__})",\n'),
        prueba=f"{SUITE}::test_el_mensaje_de_autorizacion_no_arrastra_el_texto_del_servidor",
        esperado="FUGA: el texto crudo del servidor",
    ),
    Mutacion(
        nombre="el rechazo del writer arrastra el texto del servidor",
        fichero=WRITER,
        viejo='                    "sin poder observar el esquema no se escribe; el privilegio "\n',
        nuevo=('                    f"sin poder observar el esquema no se escribe '
               '({exc.__cause__}); el privilegio "\n'),
        prueba=f"{SUITE}::test_el_writer_sin_show_constraint_no_escribe_y_lo_dice",
        esperado="FUGA: el rechazo del writer",
    ),
    Mutacion(
        nombre="ensure vuelve a aconsejar conceder DDL a la cuenta que fallo (B4)",
        fichero=CLI,
        viejo='        base + " Esta cuenta no puede crear lo que falta en el esquema, y no debe: "\n',
        nuevo='        base + " pidale a quien administra Neo4j que lo conceda a esta cuenta; "\n',
        prueba=f"{SUITE}::test_ensure_nunca_aconseja_dar_ddl_a_la_cuenta_que_fallo",
        esperado="CONSEJO DDL A LA LECTORA",
    ),
    Mutacion(
        nombre="ensure sin SHOW recibe el consejo del rol lector (O2)",
        fichero=CLI,
        viejo='    if accion == "verify":\n',
        nuevo='    if accion == "verify" or lectura:\n',
        prueba=f"{SUITE}::test_ensure_con_create_pero_sin_show_recibe_el_consejo_de_ensure",
        esperado="consejo del rol lector (O2)",
    ),
    Mutacion(
        nombre="verify devuelve 0 aunque falte una restriccion",
        fichero=CLI,
        viejo='        return RC_OK if resultado["completo"] else RC_INCOMPLETO\n',
        nuevo="        return RC_OK\n",
        prueba=f"{SUITE}::test_verify_con_una_restriccion_ausente_da_rc_incompleto",
        esperado="restriccion ausente debia dar rc 3",
    ),
    Mutacion(
        nombre="ensure traga la denegacion de creacion",
        fichero=SCHEMA,
        viejo="                    raise SchemaPrivilegeError(operacion) from exc\n",
        nuevo="                    continue\n",
        prueba=f"{SUITE}::test_la_cuenta_lectora_no_puede_crear_una_restriccion_que_falta",
        esperado="ensure con lector debia denegarse",
    ),
    Mutacion(
        nombre="el entorno (worker.env) gana al --neo4j-user explicito",
        fichero=DRIVER,
        viejo="    resolved_user = _first(user, environ.get(ENV_USER))\n",
        nuevo="    resolved_user = _first(environ.get(ENV_USER), user)\n",
        prueba=f"{SUITE}::test_el_argumento_explicito_gana_a_worker_env",
        esperado="ENTORNO GANA",
    ),
]


def _git_limpio() -> bool:
    salida = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO,
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    tracked = [l for l in salida if not l.startswith("??")]
    ajenos = [l for l in salida if l.startswith("??")]
    if ajenos:
        print("AVISO, ficheros sin seguir en el arbol (ignorados, NO son mios):")
        for l in ajenos:
            print("   " + l)
    if tracked:
        print("ARBOL SUCIO (cambios sin commitear), no se calibra:")
        for l in tracked:
            print("   " + l)
        return False
    return True


def _aplicar(m: Mutacion) -> None:
    ruta = REPO / m.fichero
    texto = ruta.read_text(encoding="utf-8")
    apariciones = texto.count(m.viejo)
    if apariciones != 1:
        raise SystemExit(
            f"[{m.nombre}] el fragmento a mutar aparece {apariciones} veces en "
            f"{m.fichero}; una mutacion que no se aplica produce un VERDE "
            f"enganoso, asi que se para aqui."
        )
    ruta.write_text(texto.replace(m.viejo, m.nuevo), encoding="utf-8")


def _revertir(m: Mutacion) -> None:
    subprocess.run(["git", "checkout", "--", m.fichero], cwd=REPO, check=True)


def _pytest(objetivo: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", objetivo],
        cwd=REPO, capture_output=True, text=True,
    )


def main() -> int:
    if not _git_limpio():
        return 2

    print(f"{'=' * 72}\nCONTROL NULO: {SUITE} sin mutar")
    nulo = _pytest(SUITE)
    print(f"  PYTEST_RC = {nulo.returncode}")
    if nulo.returncode != 0 or " passed" not in nulo.stdout:
        print(nulo.stdout[-2000:] + nulo.stderr[-2000:])
        print("RESULTADO: CONTROL NULO ROJO -- la suite sin mutar no esta verde; "
              "ningun rojo de abajo mediria nada")
        return 1

    fallos = []
    for m in MUTACIONES:
        print(f"\n{'=' * 72}\nMUTACION: {m.nombre}\n  fichero: {m.fichero}\n  prueba : {m.prueba}")
        _aplicar(m)
        try:
            proc = _pytest(m.prueba)
        finally:
            _revertir(m)

        salida = proc.stdout + proc.stderr
        rojo = proc.returncode != 0
        por_su_causa = m.esperado in salida

        print(f"  PYTEST_RC = {proc.returncode}  -> {'ROJO' if rojo else 'VERDE'}")
        if not rojo:
            fallos.append(f"{m.nombre}: la prueba NO se puso roja (PYTEST_RC=0)")
            continue
        if not por_su_causa:
            fallos.append(
                f"{m.nombre}: roja, pero NO por su causa. Se esperaba "
                f"{m.esperado!r} en el fallo."
            )
            print("  ATRIBUCION: NO -- se esperaba: " + repr(m.esperado))
            continue
        for linea in salida.splitlines():
            if m.esperado in linea:
                print("  MENSAJE   : " + linea.strip()[:200])
                break
        print("  ATRIBUCION: SI")

    print("\n" + "=" * 72)
    if not _git_limpio():
        print("RESULTADO: el arbol NO quedo limpio tras revertir las mutaciones")
        return 2
    print("arbol limpio tras revertir todas las mutaciones")
    if fallos:
        print("RESULTADO: CALIBRACION FALLIDA")
        for f in fallos:
            print("  - " + f)
        return 1
    print(f"RESULTADO: control nulo VERDE y {len(MUTACIONES)}/{len(MUTACIONES)} "
          "controles negativos rojos POR SU CAUSA, con el mensaje comprobado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
