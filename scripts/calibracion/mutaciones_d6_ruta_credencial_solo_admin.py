#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibracion D6 — la ruta del fichero de credencial sólo la ven administradores.

Revierte, una a una, las garantias del arreglo DENTRO DEL PRODUCTO, corre la
prueba que debe protegerlas y exige que se ponga roja POR SU CAUSA (se
comprueba el texto del fallo, no el color).

USO
---
    python3 scripts/calibracion/mutaciones_d6_ruta_credencial_solo_admin.py

Requiere arbol sin cambios tracked: las mutaciones se revierten con
`git checkout --`, asi que hay que COMMITEAR antes de calibrar.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VIEWER = REPO / "viewer"

JOBS = "viewer/app/jobs_client.py"
MAIN = "viewer/app/main.py"
API = "viewer/app/api/jobs.py"
CHASIS = "viewer/app/routers/chassis_operations.py"
#: Ruta RELATIVA a `viewer/`: la suite del visor se ejecuta desde ahi.
T = "tests/test_d6_ruta_credencial_solo_admin.py::"


class Mutacion:
    """Una garantia revertida, y la(s) prueba(s) que tiene(n) que verlo."""

    def __init__(self, nombre, fichero, viejo, nuevo, pruebas, esperado):
        self.nombre = nombre
        self.fichero = fichero
        self.viejo = viejo
        self.nuevo = nuevo
        self.pruebas = pruebas
        #: Fragmento que TIENE que aparecer en el fallo.
        self.esperado = esperado

    @property
    def prueba(self):
        return " ".join(self.pruebas)


MUTACIONES = [
    Mutacion(
        nombre="el no-admin vuelve a ver la ruta en el HTML del detalle",
        fichero=MAIN,
        viejo='job = scoped_job(get_visibility_scope(request), job_id) if status_info["ok"] else None',
        nuevo='job = scoped_job(None, job_id) if status_info["ok"] else None',
        pruebas=[T + "test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino"],
        esperado="recibe la ruta de la credencial por html_detalle",
    ),
    Mutacion(
        nombre="el no-admin vuelve a ver la ruta en el JSON del detalle",
        fichero=API,
        viejo="    job = scoped_job(scope, job_id)\n",
        nuevo="    job = scoped_job(None, job_id)\n",
        pruebas=[T + "test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino"],
        esperado="recibe la ruta de la credencial por api_detalle",
    ),
    Mutacion(
        nombre="la redaccion se aplica tambien al admin (pierde el detalle)",
        fichero=JOBS,
        viejo='        return {**job, "error_public": publico}\n',
        nuevo='        return {k: v for k, v in job.items() if k != "error_message"}\n',
        pruebas=[T + "test_el_admin_si_ve_la_ruta_en_html_y_en_json"],
        esperado="el admin no ve la ruta en el HTML del detalle",
    ),
    Mutacion(
        nombre="la comprobacion se hace por nombre de usuario y no por rol",
        fichero=JOBS,
        viejo="    if scope is None or scope.sees_operational_detail:\n        if publico",
        nuevo=(
            '    if scope is None or getattr(getattr(scope, "ctx", None), "username", None) == "admin":\n'
            "        if publico"
        ),
        pruebas=[
            T + "test_un_admin_con_otro_nombre_sigue_viendo_la_ruta",
            T + "test_la_decision_es_por_rol_no_por_nombre_de_usuario",
        ],
        esperado="un admin con otro nombre de usuario no ve la ruta",
    ),
    Mutacion(
        nombre="un error_code con forma de ruta ya no se redacta (por defecto, visible)",
        fichero=JOBS,
        viejo='_FORMA_CODIGO = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")',
        nuevo='_FORMA_CODIGO = re.compile(r"^.{2,200}$")',
        pruebas=[T + "test_un_error_code_con_forma_de_ruta_se_sustituye_por_el_generico"],
        esperado="un error_code con ruta sale por",
    ),
    Mutacion(
        nombre="el panel del chasis vuelve a ignorar el error_code publico",
        fichero=CHASIS,
        viejo='        codigo = str(job.get("error_code") or "").strip()\n',
        nuevo='        codigo = ""\n',
        pruebas=[T + "test_el_desenlace_del_panel_para_un_no_admin_da_el_codigo_real"],
        esperado="el desenlace del panel no da el codigo estable al no-admin",
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


def _pytest(pruebas) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-W", "ignore", "-p", "no:cacheprovider", *pruebas],
        cwd=VIEWER, capture_output=True, text=True,
    )


def main() -> int:
    if not _git_limpio():
        return 2

    base = _pytest([m for mut in MUTACIONES for m in mut.pruebas])
    print(f"BASE: PYTEST_RC={base.returncode} (esperado 0)")
    if base.returncode != 0:
        print(base.stdout[-1500:])
        print("RESULTADO: la base no esta verde; no se calibra")
        return 2

    fallos = []
    for m in MUTACIONES:
        print(f"\n{'=' * 72}\nMUTACION: {m.nombre}\n  fichero: {m.fichero}\n  prueba : {m.prueba}")
        _aplicar(m)
        try:
            proc = _pytest(m.pruebas)
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
