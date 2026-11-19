#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibracion RC1-G02 — el fallo de credencial dice su causa, con su MENSAJE.

Revierte, una a una, las garantias del arreglo DENTRO DEL PRODUCTO, corre la
prueba que debe protegerlas y exige que se ponga roja POR SU CAUSA (se
comprueba el texto del fallo, no el color).

USO
---
    python3 scripts/calibracion/mutaciones_rc1_g02_credencial_veraz.py

Requiere arbol sin cambios tracked: las mutaciones se revierten con
`git checkout --`, asi que hay que COMMITEAR antes de calibrar.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

HANDLER = "data-engine/app/jobs/handlers/ingest_v3.py"
WORKER = "data-engine/app/jobs/worker.py"
SUITE = "data-engine/app/tests/test_ingest_v3_credencial_veraz.py"
JOB_STORE = "data-engine/app/jobs/job_store.py"
#: Ronda 2 (P1-1): `error_code` y `error_message` se escriben y limpian juntos.
SUITE_ERROR = "data-engine/app/tests/test_job_store_error_code_coherente.py"


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
        nombre="volver a mapear el fallo de credencial a «no declarada»",
        fichero=HANDLER,
        viejo="""    except DriverConfigError as exc:
        log.error("credencial del grafo inutilizable: %s", exc)
        raise IngestV3Error("GRAPH_CREDENTIAL_UNUSABLE", str(exc)) from exc
    except UnicodeDecodeError""",
        nuevo="""    except DriverConfigError as exc:
        log.error("credencial del grafo inutilizable: %s", exc)
        raise IngestV3Error("GRAPH_OBSERVATION_UNCONFIGURED") from exc
    except UnicodeDecodeError""",
        prueba=f"{SUITE}::test_modo_accesible_por_grupo_u_otros_dice_credencial_y_el_motivo",
        esperado="AssertionError: GRAPH_OBSERVATION_UNCONFIGURED",
    ),
    Mutacion(
        nombre="no comprobar la lectura del fichero (ilegible = «el grafo no responde»)",
        fichero=HANDLER,
        viejo="""    _exigir_credencial_utilizable(config)
    try:""",
        nuevo="""    try:""",
        prueba=f"{SUITE}::test_fichero_ilegible_para_el_worker_dice_credencial_no_grafo_caido",
        esperado="AssertionError: GRAPH_OBSERVATION_UNAVAILABLE",
    ),
    Mutacion(
        nombre="el worker deja de rellenar error_code",
        fichero=WORKER,
        viejo="""                                     error_code=getattr(exc, "error_code", None)):""",
        nuevo="""                                     error_code=None):""",
        prueba=f"{SUITE}::test_el_job_guarda_error_code_coherente_con_el_mensaje",
        esperado="'error_code': None",
    ),
    Mutacion(
        nombre="declarar el codigo de credencial como reintentable",
        fichero=HANDLER,
        viejo="""    # Un fichero de credencial ausente o con mal modo no se arregla solo.
    "GRAPH_CREDENTIAL_UNUSABLE",
""",
        nuevo="",
        prueba=f"{SUITE}::test_el_codigo_nuevo_esta_en_el_catalogo_y_es_permanente",
        esperado="in frozenset({",
    ),
    # --- Ronda 2 (P1-1): el codigo no puede quedar RANCIO ---
    Mutacion(
        nombre="mark_complete deja de limpiar error_code (job complete con incidencia)",
        fichero=JOB_STORE,
        viejo="""                error_message = NULL, error_code = NULL, next_retry_at = NULL""",
        nuevo="""                error_message = NULL, next_retry_at = NULL""",
        prueba=f"{SUITE_ERROR}::test_reintentable_y_luego_exito_no_deja_error_code",
        esperado="('complete', 'GRAPH_OBSERVATION_UNAVAILABLE', None)",
    ),
    Mutacion(
        nombre="mark_failed sin codigo conserva el codigo del fallo anterior",
        fichero=JOB_STORE,
        viejo="""        fields["error_code"] = error_code or None
""",
        nuevo="""        if error_code:
            fields["error_code"] = error_code
""",
        prueba=f"{SUITE_ERROR}::test_un_fallo_nuevo_sin_codigo_no_hereda_el_anterior",
        esperado="('pending', 'GRAPH_OBSERVATION_UNAVAILABLE', 'otro fallo')",
    ),
    Mutacion(
        nombre="el reencolado (update_job con error_message) no limpia el codigo",
        fichero=JOB_STORE,
        viejo="""    if "error_message" in fields and "error_code" not in fields:
        fields["error_code"] = None
""",
        nuevo="",
        prueba=f"{SUITE_ERROR}::test_reencolado_de_la_cli_limpia_los_dos",
        esperado="('pending', 'GRAPH_OBSERVATION_UNAVAILABLE', None)",
    ),
]


def _git_limpio() -> bool:
    """¿Hay cambios TRACKED sin commitear? Esos son los que importan.

    La mutación se revierte con `git checkout --`, que sólo toca ficheros
    seguidos: un cambio tracked sin commitear se perdería, y por eso aborta.
    Un fichero SIN SEGUIR no corre ese riesgo y no se puede revertir por esa
    vía, así que bloquear por él sólo consigue que la calibración no se pueda
    correr en un árbol donde otro carril dejó un temporal —que es exactamente
    lo que pasó aquí—. Se ignoran, pero se AVISA: un intruso en el árbol es
    dato, no ruido.
    """
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
        # El mensaje real del rojo, que es lo que se informa.
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
