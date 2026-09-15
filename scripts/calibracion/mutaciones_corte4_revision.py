#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibración del Slice 2 · Corte 4 — controles negativos con su MENSAJE.

QUÉ ES ESTO Y POR QUÉ EXISTE
----------------------------
Una afirmación de seguridad —o de veracidad, como aquí— no cuenta hasta que hay
una prueba capaz de ponerse ROJA. Este arnés revierte, una a una, cada garantía
del corte DENTRO DEL PRODUCTO, corre la prueba que debería protegerla y exige:

  1. que se ponga roja, y
  2. que se ponga roja POR SU CAUSA — se comprueba el MENSAJE, no el color.

Lo segundo no es celo: en el Corte 1 una prueba pasaba por la razón equivocada
y en el Corte 2 tres rojos se atribuían mal. Un rojo por la razón equivocada se
lee exactamente igual que uno legítimo.

El control nº 3 va EN SENTIDO CONTRARIO a los otros: comprueba que arreglar
«ausente» e «ilegible» a lo bruto —tratando también el vacío legítimo como un
fallo— pone rojo. Sin él, la forma más fácil de aprobar los dos primeros sería
alarmar al operador siempre.

USO
---
    python3 scripts/calibracion/mutaciones_corte4_revision.py

Requiere árbol limpio: las mutaciones se revierten con `git checkout --`, que
se lleva por delante cualquier cambio sin commitear del fichero mutado.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SERVICIO = "viewer/app/services/v3_review.py"
HANDLER = "data-engine/app/jobs/handlers/ingest_v3.py"
EXPORTADOR = "data-engine/app/knowledge_v3/review_export.py"
ROUTER_V3 = "viewer/app/routers/v3_review.py"

SUITE = "viewer/tests/test_panel_review_estado_de_revision.py"
SUITE_V3 = "viewer/tests/test_v3_review_almacen_no_disponible.py"


class Mutacion:
    """Una garantía revertida, y la prueba que tiene que verlo."""

    def __init__(self, nombre, fichero, viejo, nuevo, prueba, esperado):
        self.nombre = nombre
        self.fichero = fichero
        self.viejo = viejo
        self.nuevo = nuevo
        self.prueba = prueba
        #: Fragmento que TIENE que aparecer en el fallo. Es lo que distingue
        #: «rojo por su causa» de «rojo por cualquier cosa».
        self.esperado = esperado


MUTACIONES = [
    Mutacion(
        nombre="revertir «ausencia != vacio»",
        fichero=SERVICIO,
        viejo="""    if not directory.exists():
        raise ProposalStoreUnavailable(
            f"almacén de propuestas ausente: {directory}", PROPOSALS_STORE_MISSING
        )""",
        nuevo="""    if not directory.exists():
        return []""",
        prueba=f"{SUITE}::test_almacen_ausente_no_se_presenta_como_vacio",
        esperado="sigue diciendo «Sin propuestas",
    ),
    Mutacion(
        nombre="revertir el caso ILEGIBLE (glob se traga el PermissionError)",
        fichero=SERVICIO,
        viejo="""    try:
        entries = sorted(os.listdir(directory))
    except OSError as exc:
        raise ProposalStoreUnavailable(
            f"almacén de propuestas ilegible: {directory}", PROPOSALS_STORE_UNREADABLE
        ) from exc""",
        nuevo="""    entries = sorted(p.name for p in directory.glob("*.json"))""",
        prueba=f"{SUITE}::test_almacen_ilegible_no_se_presenta_como_vacio",
        esperado="ILEGIBLE la pantalla dice «Sin propuestas visibles»",
    ),
    Mutacion(
        nombre="vacio legitimo tratado como error (arreglo a lo bruto)",
        fichero=SERVICIO,
        viejo="""    try:
        entries = sorted(os.listdir(directory))
    except OSError as exc:""",
        nuevo="""    try:
        entries = sorted(os.listdir(directory))
        if not entries:
            raise ProposalStoreUnavailable(
                "almacen vacio", PROPOSALS_STORE_MISSING
            )
    except OSError as exc:""",
        prueba=f"{SUITE}::test_almacen_vacio_legitimo_si_se_presenta_como_vacio",
        esperado="se está presentando como un FALLO",
    ),
    Mutacion(
        nombre="resumen sin REVIEW real (vuelve a review_identity)",
        fichero=HANDLER,
        viejo='        "en_revision": int(por_veredicto.get("REVIEW") or 0),',
        nuevo='        "en_revision": totales.get("review_identity"),',
        prueba=f"{SUITE}::test_el_resumen_refleja_el_review_real",
        esperado="el resumen dice «en revisión",
    ),
    Mutacion(
        nombre="propuestas sin atribucion (el paquete no declara su corrida)",
        fichero=EXPORTADOR,
        viejo='    if run:\n        package_body["run"] = {k: v for k, v in sorted(run.items()) if v is not None}',
        nuevo="    if False:\n        pass",
        prueba=(
            f"{SUITE}::"
            "test_insignia_dos_ingestas_se_distinguen_y_el_almacen_roto_cambia_la_pantalla"
        ),
        esperado="sin atribución a la corrida, A y B no se distinguen",
    ),
    # -------------------------------------------------------------------
    # LA REGRESIÓN QUE SE ESCAPÓ A LA PRIMERA ENTREGA.
    #
    # `load_proposals` tiene TRES consumidores y la primera entrega cubrió uno.
    # El enlace de la nav `/v3/review` daba 500 y lo cazó el contrato de
    # navegador — un check requerido que en la máquina de trabajo se SALTA por
    # falta de Chromium. Este control comprueba que ahora hay una prueba
    # EJECUTABLE aquí que lo ve.
    # -------------------------------------------------------------------
    Mutacion(
        nombre="dejar sin manejar el almacen caido en /v3/review (la regresion de CI)",
        fichero=ROUTER_V3,
        viejo="    except ProposalStoreUnavailable as exc:\n        # La pantalla ABRE y EXPLICA",
        nuevo="    except ZeroDivisionError as exc:\n        # La pantalla ABRE y EXPLICA",
        prueba=f"{SUITE_V3}::test_ningun_enlace_de_la_nav_revienta_con_el_almacen_ausente",
        esperado="enlaces de la nav que revientan",
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
