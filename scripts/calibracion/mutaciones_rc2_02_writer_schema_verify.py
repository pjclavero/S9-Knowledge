#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibracion RC2-02 — `writer-schema verify` y el rol de sólo lectura.

Revierte, una a una, las garantias del arreglo DENTRO DEL PRODUCTO (y de la doc
que define el rol), corre la prueba que debe protegerlas y exige que se ponga
roja POR SU CAUSA (se comprueba el texto del fallo, no el color).

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
README = "deploy/README.md"
SUITE = "data-engine/app/tests/test_writer_schema_verify_rc2_02.py"


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
        nombre="el rol documentado pierde SHOW CONSTRAINT",
        fichero=README,
        viejo="GRANT SHOW CONSTRAINT ON DATABASE neo4j TO s9k_observador;\n",
        nuevo="",
        prueba=f"{SUITE}::test_readme_y_codigo_definen_el_mismo_rol_lector",
        esperado="el rol de deploy/README.md diverge del que espera el codigo",
    ),
    Mutacion(
        nombre="el rol del codigo pierde SHOW CONSTRAINT (la doc la conserva)",
        fichero=SCHEMA,
        viejo='    "GRANT SHOW CONSTRAINT ON DATABASE {db} TO {role}",\n',
        nuevo="",
        prueba=f"{SUITE}::test_el_rol_incluye_lectura_de_esquema",
        esperado="al rol le falta SHOW CONSTRAINT",
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
        nombre="el rol lector gana un privilegio de escritura",
        fichero=SCHEMA,
        viejo='    "GRANT SHOW INDEX ON DATABASE {db} TO {role}",\n',
        nuevo=('    "GRANT SHOW INDEX ON DATABASE {db} TO {role}",\n'
               '    "GRANT WRITE ON GRAPH {db} TO {role}",\n'),
        prueba=f"{SUITE}::test_el_rol_lector_no_concede_escritura_ni_administracion",
        esperado="el rol lector concede una capacidad de escritura/administracion",
    ),
    Mutacion(
        nombre="ensure traga el Forbidden de creacion (la cuenta lectora «parece» poder)",
        fichero=SCHEMA,
        viejo="            raise SchemaPrivilegeError(PRIVILEGE_CREATE_SCHEMA) from exc\n",
        nuevo="            return\n",
        prueba=f"{SUITE}::test_la_cuenta_lectora_no_puede_ensure_y_no_crea_nada",
        esperado="ensure con lector debia denegarse",
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


def main() -> int:
    if not _git_limpio():
        return 2

    fallos = []
    for m in MUTACIONES:
        print(f"\n{'=' * 72}\nMUTACION: {m.nombre}\n  fichero: {m.fichero}\n  prueba : {m.prueba}")
        _aplicar(m)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", m.prueba],
                cwd=REPO, capture_output=True, text=True,
            )
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
    print(f"RESULTADO: {len(MUTACIONES)}/{len(MUTACIONES)} controles negativos "
          "rojos POR SU CAUSA, con el mensaje comprobado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
