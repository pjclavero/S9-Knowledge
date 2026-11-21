#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibrador de RC2-05: la primera ingesta proyecta las relaciones aprobadas.

Uso (desde un arbol LIMPIO; las mutaciones se revierten con `git checkout --`):

    python3 scripts/calibracion/mutaciones_rc2_05_relaciones_primera_ingesta.py

Cada mutacion revierte UNA garantia de la correccion y exige que la suite falle con el
PREFIJO propio de la causa (primera linea del mensaje del assert), no con un `repr` de
pytest. Un control nulo (tocar un comentario) tiene que seguir VERDE: si no, el instrumento
no sirve. Salida 0 = todas las mutaciones cazadas con su prefijo.

TECHO: la suite mide el plan sellado y su ejecucion contra un doble transaccional del writer,
no contra Neo4j (el caso real lo ejecuta el paso de CI de cobertura Neo4j real).
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PLAN = "data-engine/app/knowledge_v3/review_plan.py"
EXECUTOR = "data-engine/app/knowledge_v3/writer/executor.py"
WRITER = "data-engine/app/knowledge_v3/writer/writer.py"
TEST = "data-engine/app/tests/test_rc2_05_relaciones_primera_ingesta.py"


@dataclass(frozen=True)
class Mutacion:
    nombre: str
    fichero: str
    viejo: str
    nuevo: str
    suites: tuple
    #: Prefijos aceptables: el fallo tiene que contener AL MENOS UNO. `None` = control nulo.
    prefijos: tuple | None
    #: Reemplazos ADICIONALES (viejo, nuevo) en el mismo fichero, cada uno con ancla unica.
    extra: tuple = ()


CONTROL_NULO = Mutacion(
    "CONTROL NULO: tocar un comentario no cambia nada",
    PLAN,
    "# El sujeto lo crea este plan: no hay estado previo que esperar.",
    "# El sujeto lo crea este plan (comentario tocado por el calibrador).",
    (TEST,), None)

_ABORTO_VIEJO = (
    '                message=f"la transaccion se revirtio: {exc}",\n'
    "            )\n"
    "            return self._finish(OUTCOME_ABORTED,"
)
_ABORTO_NUEVO = _ABORTO_VIEJO.replace("OUTCOME_ABORTED", "OUTCOME_APPLIED")

MUTACIONES = [
    Mutacion("se proyecta sin comprobar la aprobacion: toda alta DECLARADA ancla la arista",
             PLAN, "    en_plan = frozenset(altas_incluidas)",
             "    en_plan = frozenset(contexto.get(ALTAS_KEY) or ())",
             (TEST,), ("RC2-05 SIN APROBACION:",)),
    Mutacion("se proyecta con el alta rechazada: toda alta APROBADA ancla, la deje fuera el plan o no",
             PLAN, "    en_plan = frozenset(altas_incluidas)",
             '    en_plan = frozenset(str(a.get("entity_id")) for a in approved_entities)',
             (TEST,), ("RC2-05 ALTA RECHAZADA:",)),
    Mutacion("se resuelve por NOMBRE en vez de por la identidad del alta del plan",
             PLAN, "    objeto_nuevo = objeto in altas_del_plan",
             '    objeto_nuevo = (contexto.get(ALTAS_KEY, {}).get(objeto) or {}).get("name") in {'
             '(contexto.get(ALTAS_KEY, {}).get(a) or {}).get("name") for a in altas_del_plan}',
             (TEST,), ("RC2-05 IDENTIDAD:",)),
    Mutacion("el reintento ya no reconoce lo aplicado y lo vuelve a ejecutar",
             EXECUTOR, "                if not created:", "                if False and not created:",
             (TEST,), ("RC2-05 REINTENTO:",)),
    Mutacion("el reintento DUPLICA: ni reconoce lo aplicado ni comprueba que el nodo ya existe",
             EXECUTOR, "                if not created:", "                if False and not created:",
             (TEST,), ("RC2-05 REINTENTO DUPLICA:",),
             extra=(
                 ("        _assert_absent(tx, op, ws, entity_id, is_assertion=False)", "        pass"),
                 ("        _assert_absent(tx, op, ws, assertion_id, is_assertion=True)", "        pass"),
             )),
    Mutacion("el fallo parcial se reporta como exito",
             WRITER, _ABORTO_VIEJO, _ABORTO_NUEVO,
             (TEST,), ("RC2-05 EXITO FALSO:",)),
    Mutacion("se cruza de ambito: un alta que la corrida no declara tambien se crea",
             PLAN, "        declarada = declaradas.get(entity_id)",
             "        declarada = declaradas.get(entity_id) or {}",
             (TEST,), ("RC2-05 AMBITO:",)),
    Mutacion("la arista deja de ir por detras de su alta",
             PLAN, "    if ancladas_en_plan:", "    if False:",
             (TEST,), ("RC2-05 ORDEN:",)),
]


def _leer(ruta: str) -> str:
    return (REPO / ruta).read_text(encoding="utf-8")


def _limpio() -> bool:
    r = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True, check=True)
    return not r.stdout.strip()


def _correr(suites: tuple) -> tuple:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *suites, "-q", "-p", "no:randomly", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=str(REPO), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _con_mutacion(m: Mutacion) -> tuple:
    original = _leer(m.fichero)
    mutado = original
    for viejo, nuevo in ((m.viejo, m.nuevo), *m.extra):
        if mutado.count(viejo) != 1:
            return 2, "ANCLA PERDIDA O AMBIGUA: el texto a mutar aparece %d veces en %s (debe ser 1)" % (
                mutado.count(viejo), m.fichero)
        mutado = mutado.replace(viejo, nuevo, 1)
    (REPO / m.fichero).write_text(mutado, encoding="utf-8")
    try:
        return _correr(m.suites)
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
