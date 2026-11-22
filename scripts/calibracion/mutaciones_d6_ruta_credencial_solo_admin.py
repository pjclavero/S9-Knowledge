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
STATUS = "viewer/app/api/status.py"
HEALTH = "viewer/app/routers/health_admin.py"
PLANTILLA = "viewer/app/templates/job_detail.html"
DRIVER = "data-engine/app/knowledge_v3/driver_neo4j.py"
#: Ruta RELATIVA a `viewer/`: la suite del visor se ejecuta desde ahi.
T = "tests/test_d6_ruta_credencial_solo_admin.py::"
#: Un llamador «sin restricciones» fabricado a mano en el punto del defecto.
SIN_RESTRICCION = '__import__("app.authz.scope", fromlist=["UNRESTRICTED"]).UNRESTRICTED'


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
        nuevo=f'job = scoped_job({SIN_RESTRICCION}, job_id) if status_info["ok"] else None',
        pruebas=[T + "test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino"],
        esperado="recibe la ruta de la credencial por html_detalle",
    ),
    Mutacion(
        nombre="el no-admin vuelve a ver la ruta en la LISTA HTML",
        fichero=MAIN,
        viejo="        scoped_jobs(scope, workspace=workspace, status=status, job_type=job_type)\n",
        nuevo=f"        scoped_jobs({SIN_RESTRICCION}, workspace=workspace, status=status, job_type=job_type)\n",
        pruebas=[T + "test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino"],
        esperado="recibe la ruta de la credencial por html_lista",
    ),
    Mutacion(
        nombre="el no-admin vuelve a ver la ruta en el JSON del detalle",
        fichero=API,
        viejo="    job = scoped_job(scope, job_id)\n",
        nuevo=f"    job = scoped_job({SIN_RESTRICCION}, job_id)\n",
        pruebas=[T + "test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino"],
        esperado="recibe la ruta de la credencial por api_detalle",
    ),
    Mutacion(
        nombre="el no-admin vuelve a ver la ruta en la API de LISTA",
        fichero=API,
        viejo="    jobs = scoped_jobs(scope, workspace=workspace, status=status,\n",
        nuevo=f"    jobs = scoped_jobs({SIN_RESTRICCION}, workspace=workspace, status=status,\n",
        pruebas=[T + "test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino"],
        esperado="recibe la ruta de la credencial por api_lista",
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
        fichero=MAIN,
        viejo='job = scoped_job(get_visibility_scope(request), job_id) if status_info["ok"] else None',
        nuevo=(
            f'job = scoped_job({SIN_RESTRICCION} if getattr(guard, "username", None) == "admin" '
            'else get_visibility_scope(request), job_id) if status_info["ok"] else None'
        ),
        pruebas=[T + "test_la_decision_es_por_rol_no_por_nombre_de_usuario"],
        esperado="un revisor llamado «admin» recibe la ruta por html_detalle",
    ),
    Mutacion(
        nombre="un error_code con forma de ruta ya no se sustituye por JOB_FAILED",
        fichero=JOBS,
        viejo="        codigo = _codigo_estable(job) or CODIGO_GENERICO\n",
        nuevo='        codigo = _codigo_estable(job) or "OTRO_CODIGO"\n',
        pruebas=[T + "test_un_error_code_con_forma_de_ruta_se_sustituye_por_el_generico"],
        esperado="un error_code que no es un código estable debe sustituirse por JOB_FAILED",
    ),
    Mutacion(
        nombre="la frase publica sale del texto del job y no del catalogo",
        fichero=JOBS,
        viejo='"message": panel_errors.CATALOGO.get(codigo, _FRASE_CODIGO_SIN_CATALOGO)}',
        nuevo='"message": str(job.get("error_message") or "")}',
        pruebas=[T + "test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino"],
        esperado="recibe la ruta de la credencial por",
    ),
    Mutacion(
        nombre="el detalle del job vuelve a dar 500 a un no-admin (sin la guarda de payload)",
        fichero=PLANTILLA,
        viejo="{% if job.payload is defined %}",
        nuevo="{% if true %}",
        pruebas=[T + "test_un_no_admin_recibe_codigo_explicacion_y_a_quien_avisar"],
        esperado="D6: el detalle da 500",
    ),
    Mutacion(
        nombre="la frase publica ya no depende del estado (un pending «ha fallado»)",
        fichero=JOBS,
        viejo="    if estado in _ESTADOS_FALLO:\n        codigo",
        nuevo="    if True:\n        codigo",
        pruebas=[T + "test_la_frase_publica_depende_del_estado"],
        esperado="el código público es",
    ),
    Mutacion(
        nombre="sin ambito (None) se vuelve a entregar el detalle",
        fichero=JOBS,
        viejo="    if scope is not None and scope.sees_operational_detail:\n",
        nuevo="    if scope is None or scope.sees_operational_detail:\n",
        pruebas=[T + "test_sin_ambito_no_se_entrega_nada"],
        esperado="redact_job(None) entrega el texto técnico",
    ),
    Mutacion(
        nombre="el prefijo de texto libre se publica sin estar en el catalogo",
        fichero=JOBS,
        viejo="    if prefijo in panel_errors.CATALOGO:\n        return prefijo\n",
        nuevo="    if _FORMA_CODIGO.fullmatch(prefijo):\n        return prefijo\n",
        pruebas=[T + "test_el_codigo_extraido_de_texto_libre_exige_pertenencia_al_catalogo"],
        esperado="el prefijo de un mensaje libre se publica como código",
    ),
    Mutacion(
        nombre="el secreto real sale en el mensaje de la politica (contenido)",
        fichero=DRIVER,
        viejo='            + "; ".join(v.detail for v in incumplimientos)\n',
        nuevo='            + "; ".join(v.detail for v in incumplimientos) + " contenido=" + ruta.read_text(encoding="utf-8")\n',
        pruebas=[T + "test_el_secreto_real_no_sale_por_ningun_camino"],
        esperado="H1: el secreto (o un trozo) sale por el error_message del handler",
    ),
    Mutacion(
        nombre="la longitud del secreto sale en el mensaje de la politica",
        fichero=DRIVER,
        viejo='            + "; ".join(v.detail for v in incumplimientos)\n',
        nuevo='            + "; ".join(v.detail for v in incumplimientos) + f" ({ruta.stat().st_size} bytes)"\n',
        pruebas=[T + "test_el_secreto_real_no_sale_por_ningun_camino"],
        esperado="H1: la longitud del secreto (70) sale por el error_message del handler",
    ),
    Mutacion(
        nombre="/api/admin/health vuelve a abrirse al anonimo con la auth apagada",
        fichero=HEALTH,
        viejo="Depends(require_api_admin())",
        nuevo='Depends(__import__("app.auth.dependencies", fromlist=["x"]).require_api_role("admin"))',
        pruebas=[T + "test_el_informe_de_salud_no_se_entrega_a_un_anonimo_con_la_auth_apagada"],
        esperado="responde 200 a un anónimo con la auth apagada",
    ),
    Mutacion(
        nombre="/jobs vuelve a pintar la ruta de la base a quien no es admin",
        fichero=MAIN,
        viejo="    if not scope.sees_operational_detail:\n        status_info =",
        nuevo="    if False:\n        status_info =",
        pruebas=[T + "test_la_ruta_de_la_base_de_trabajos_sale_solo_al_admin"],
        esperado="recibe la ruta de la base de trabajos",
    ),
    Mutacion(
        nombre="/api/status vuelve a entregar str(exc) del proveedor a todos",
        fichero=STATUS,
        viejo="        detalle = scope is not None and scope.sees_operational_detail\n",
        nuevo="        detalle = True\n",
        pruebas=[T + "test_el_fallo_del_proveedor_solo_llega_con_detalle_al_admin"],
        esperado="recibe host/puerto del grafo",
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

    # CONTROL NULO: una «mutacion» que reescribe un fichero con su MISMO texto
    # tiene que dejar la suite VERDE y el arbol limpio. Si no, el rojo de las
    # mutaciones no se podria atribuir a la mutacion sino al propio arnes.
    nulo = Mutacion("control nulo", MAIN, "import json", "import json", [], "")
    _aplicar(nulo)
    try:
        base = _pytest([m for mut in MUTACIONES for m in mut.pruebas])
    finally:
        _revertir(nulo)
    print(f"CONTROL NULO: PYTEST_RC={base.returncode} (esperado 0)")
    if base.returncode == 0 and not _git_limpio():
        print("RESULTADO: el control nulo dejo el arbol sucio")
        return 2
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
