#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibrador de NAV-01 / NAV-02 / NAV-03 / NAV-06: cada garantia tiene que saber ponerse roja.

Uso (desde un arbol LIMPIO; las mutaciones se revierten con `git checkout --`):

    python3 scripts/calibracion/mutaciones_nav_defectos_de_navegador.py

Cada mutacion revierte UNA decision de las correcciones y exige que la suite falle con el
PREFIJO propio de la causa (el mensaje del assert del test), no con un `repr` de pytest.
Un control nulo (tocar un comentario) tiene que seguir VERDE: si no, el instrumento no sirve.
Salida 0 = todas las mutaciones cazadas con su prefijo.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

MIDDLEWARE = "viewer/app/auth/middleware.py"
BASE = "viewer/app/templates/base.html"
SALUD = "viewer/app/routers/health_admin.py"
MAIN = "viewer/app/main.py"
SUITE = "viewer/tests/test_nav_defectos_de_navegador.py"


@dataclass(frozen=True)
class Mutacion:
    nombre: str
    fichero: str
    viejo: str
    nuevo: str
    #: El fallo tiene que contener AL MENOS UNO. `None` = control nulo.
    prefijos: tuple | None


CONTROL_NULO = Mutacion(
    "CONTROL NULO: tocar un comentario no cambia nada",
    MIDDLEWARE, "# NAV-01 · UN solo punto.", "# NAV-01 (comentario tocado) · UN solo punto.", None)

MUTACIONES = [
    Mutacion("NAV-01 · el punto unico deja de poner no-store",
             MIDDLEWARE, 'response.headers.setdefault("Cache-Control", "no-store")', "pass",
             ("NAV-01: respuestas sin no-store",)),
    Mutacion("NAV-01 · una ruta protegida (/admin/audit) queda fuera del no-store",
             MIDDLEWARE, 'return path.startswith("/static/") or path == "/favicon.ico"',
             'return path.startswith("/static/") or path == "/favicon.ico" or path == "/admin/audit"',
             ("NAV-01: respuestas sin no-store: admin /admin/audit",)),
    Mutacion("NAV-01 · el JSON de la API autenticada deja de llevar no-store",
             MIDDLEWARE, 'elif not _es_estatico_publico(path):',
             'elif not (_es_estatico_publico(path) or path.startswith("/api/")):',
             ("NAV-01: el JSON de la API autenticada no lleva no-store",)),
    Mutacion("NAV-01 · los estaticos publicos dejan de ser cacheables",
             MIDDLEWARE, 'return path.startswith("/static/") or path == "/favicon.ico"',
             "return False",
             ("NAV-01 (negativo): se aplico no-store a un estatico publico",
              "NAV-01 (negativo): se aplicó no-store a un estático público")),
    Mutacion("NAV-02 · la barra deja de usar el usuario de la peticion",
             BASE, "{% set barra_user = request.state.user %}", "{% set barra_user = none %}",
             ("NAV-02 (admin)", "NAV-02 (reviewer)", "NAV-02 (viewer)")),
    Mutacion("NAV-06 · /api/admin/health vuelve a ser async (se bloquea a si mismo)",
             SALUD, "def api_admin_health(request", "async def api_admin_health(request",
             ("NAV-06: el visor que sirve la petición figura",)),
    Mutacion("NAV-06 · /admin/health vuelve a ser async",
             SALUD, "def admin_health_panel(request", "async def admin_health_panel(request",
             ("NAV-06: la pantalla publica ReadTimeout",)),
    Mutacion("NAV-06 · la instantanea vuelve a ser async",
             SALUD, "def admin_health_snapshot(", "async def admin_health_snapshot(",
             ("NAV-06: la instantánea guarda el visor",)),
    Mutacion("NAV-03 · el 403 de navegador vuelve a ser JSON",
             MAIN, 'return "text/html" in request.headers.get("accept", "")', "return False",
             ("NAV-03: el 403 del navegador no es HTML",)),
    Mutacion("NAV-03 · el 404 de navegador vuelve a ser JSON",
             MAIN, "if exc.status_code in (403, 404) and _quiere_html(request):",
             "if exc.status_code in (403,) and _quiere_html(request):",
             ("NAV-03: el 404 del navegador no es HTML",)),
    Mutacion("NAV-03 · la API pasa a HTML si quien pregunta acepta HTML",
             MAIN, 'if request.url.path.startswith("/api/"):\n        return False',
             'if False:\n        return False',
             ("NAV-03: una ruta /api/ pasó a HTML",)),
    Mutacion("NAV-03 · la pagina 403 reproduce el detalle interno de la excepcion",
             MAIN, '{"request": request, "detail": ""})', '{"request": request, "detail": exc.detail})',
             ("NAV-03: la página 403 reproduce el texto interno",)),
]


def _leer(ruta: str) -> str:
    return (REPO / ruta).read_text(encoding="utf-8")


def _limpio() -> bool:
    r = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True, check=True)
    return not r.stdout.strip()


def _correr() -> tuple:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "-q", "-p", "no:randomly", "--no-header",
         "-p", "no:cacheprovider", "-W", "ignore"],
        cwd=str(REPO), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _con_mutacion(m: Mutacion) -> tuple:
    original = _leer(m.fichero)
    if original.count(m.viejo) != 1:
        return 2, "ANCLA PERDIDA O AMBIGUA: el texto a mutar aparece %d veces en %s (debe ser 1)" % (
            original.count(m.viejo), m.fichero)
    (REPO / m.fichero).write_text(original.replace(m.viejo, m.nuevo, 1), encoding="utf-8")
    try:
        return _correr()
    finally:
        subprocess.run(["git", "-C", str(REPO), "checkout", "--", m.fichero], check=True)
        if _leer(m.fichero) != original:
            raise SystemExit("RESTAURACION FALLIDA en %s: revisa el arbol a mano" % m.fichero)


def main() -> int:
    if not _limpio():
        print("ARBOL SUCIO: commitea antes (las mutaciones se revierten con git checkout --).")
        return 2
    rc, salida = _con_mutacion(CONTROL_NULO)
    if rc != 0:
        print("CONTROL NULO ROJO: el instrumento no sirve.\n" + salida[-2000:])
        return 2
    print("control nulo verde")
    fallos = 0
    for m in MUTACIONES:
        rc, salida = _con_mutacion(m)
        cazada = rc not in (0, 2) and any(p in salida for p in m.prefijos)
        print("%s  %s" % ("CAZADA " if cazada else "ESCAPA ", m.nombre))
        if not cazada:
            fallos += 1
            print("   rc=%s, esperado alguno de %s\n%s" % (rc, m.prefijos, salida[-1200:]))
    print("\n%d mutaciones, %d escapan" % (len(MUTACIONES), fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
