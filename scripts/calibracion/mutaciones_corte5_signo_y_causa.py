#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibración del Slice 2 · Corte 5 — controles negativos con su MENSAJE.

QUÉ ES ESTO Y POR QUÉ EXISTE
----------------------------
Una afirmación no cuenta hasta que hay una prueba capaz de ponerse ROJA. Este
arnés revierte, una a una, cada garantía del corte DENTRO DEL PRODUCTO, corre
la prueba que debería protegerla y exige:

  1. que se ponga roja, y
  2. que se ponga roja POR SU CAUSA — se comprueba el MENSAJE, no el color.

Lo segundo no es celo. En este repositorio ya pasó tres veces que una prueba
pasaba (o fallaba) por la razón equivocada, y un rojo por la razón equivocada se
lee exactamente igual que uno legítimo.

LOS DOS SENTIDOS, PORQUE AQUÍ EL ERROR ES SIMÉTRICO
---------------------------------------------------
Las mutaciones 1–4 reponen el defecto: el signo se pierde y un hecho negado se
pinta como afirmativo. Las 5 y 6 van EN SENTIDO CONTRARIO:

  * la 5 marca como negado TODO hecho —el error simétrico— y tiene que poner
    roja la prueba del hecho AFIRMATIVO;
  * la 6 normaliza la ausencia a `False` —«ausente es afirmativo»— y tiene que
    poner roja la prueba del tercer estado.

Sin ellas, la forma más fácil de aprobar las cuatro primeras sería marcarlo
todo, que es tan falso como no marcar nada.

La 7 y la 8 hacen lo propio con la causa del `superseded`: una repone el defecto
(la pantalla vuelve a culpar a una decisión) y la otra fabrica la causa que el
dato no contiene (atribuir el apply fallido a TODOS los supersedidos).

USO
---
    python3 scripts/calibracion/mutaciones_corte5_signo_y_causa.py

Requiere árbol limpio: las mutaciones se revierten con `git checkout --`, que
se lleva por delante cualquier cambio sin commitear del fichero mutado.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

LABELS = "viewer/app/labels.py"
PROVIDER = "viewer/app/providers/neo4j_provider.py"
LECTOR = "viewer/app/providers/provenance_reader.py"
SERVICIO = "viewer/app/services/result_provenance.py"
PLANTILLA_RESULTADO = "viewer/app/templates/resultado/resultado.html"
PLANTILLA_FICHA = "viewer/app/templates/chassis/entities_item.html"
APPLY = "viewer/app/services/v3_apply.py"

SUITE_SIGNO = "viewer/tests/test_panel_signo_de_negacion.py"
SUITE_CAUSA = "viewer/tests/test_panel_causa_del_plan_superseded.py"


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
    # -- 1. El signo no sale del grafo -----------------------------------
    Mutacion(
        "el proyector del proveedor deja de publicar el signo",
        PROVIDER,
        '        "negated": props.get("negated"),',
        '        # MUTADO: el signo se cae aqui\n',
        f"{SUITE_SIGNO}::test_ficha_de_entidad_pinta_el_NO_de_un_hecho_negado",
        "la ficha de entidad sigue publicando el predicado sin su signo",
    ),
    # -- 2. El serializador lo deja fuera --------------------------------
    Mutacion(
        "el serializador vuelve a la lista blanca sin signo",
        "viewer/app/serializers.py",
        '        "signo": negation_code(assertion.get("negated")),',
        '        "signo": "",\n',
        f"{SUITE_SIGNO}::test_el_serializador_publica_el_signo_y_no_el_booleano_crudo",
        "HECHO_NEGADO",
    ),
    # -- 3. La consulta de procedencia no lo pide ------------------------
    Mutacion(
        "el lector de procedencia deja de seleccionar `negated`",
        LECTOR,
        '            "a.predicate AS predicate, a.negated AS negated, "',
        '            "a.predicate AS predicate, "\n',
        f"{SUITE_SIGNO}::test_el_lector_de_procedencia_PIDE_el_signo_en_su_consulta",
        "ha dejado de seleccionar `negated`",
    ),
    # -- 4. La plantilla de resultado no lo pinta ------------------------
    Mutacion(
        "la pantalla de resultado deja de pintar el «NO»",
        PLANTILLA_RESULTADO,
        """        {% if h.signo == 'HECHO_NEGADO' %}<strong data-role="marca-negacion">NO</strong>{% endif %}""",
        "\n",
        f"{SUITE_SIGNO}::test_resultado_pinta_el_NO_de_un_hecho_negado",
        "el operador sigue leyendo",
    ),
    # -- 5. EL ERROR SIMÉTRICO: todo negado ------------------------------
    Mutacion(
        "SENTIDO CONTRARIO: se marca como negado TODO hecho",
        LABELS,
        "    if negated is True:\n        return NEGACION_NEGADO\n"
        "    if negated is False:\n        return NEGACION_AFIRMATIVO",
        "    return NEGACION_NEGADO\n    if False:\n        return NEGACION_AFIRMATIVO\n",
        f"{SUITE_SIGNO}::test_resultado_NO_marca_como_negado_un_hecho_afirmativo",
        "invertir el signo es tan grave como perderlo",
    ),
    # -- 6. AUSENCIA TRATADA COMO CERO -----------------------------------
    Mutacion(
        "SENTIDO CONTRARIO: la ausencia se normaliza a «afirmativo»",
        LABELS,
        "    if negated is False:\n        return NEGACION_AFIRMATIVO\n"
        "    return NEGACION_NO_DISPONIBLE",
        "    return NEGACION_AFIRMATIVO\n",
        f"{SUITE_SIGNO}::test_resultado_dice_que_no_sabe_el_signo_cuando_el_campo_no_viene",
        "ausencia no es",
    ),
    # -- 7. La pantalla vuelve a culpar a una decisión -------------------
    Mutacion(
        "el GET del estado deja de derivar la causa del `superseded`",
        APPLY,
        "            causa_superseded=(\n"
        "                causa_de_superseded(ultimo)\n"
        "                if estado == self.store.ESTADO_SUPERSEDIDO else None\n"
        "            ),",
        "            causa_superseded=None,\n",
        f"{SUITE_CAUSA}::test_la_pantalla_no_culpa_a_una_decision_de_lo_que_fue_un_apply_fallido",
        "la pantalla sigue sin distinguir un apply fallido",
    ),
    # -- 8. SENTIDO CONTRARIO: se fabrica la causa -----------------------
    Mutacion(
        "SENTIDO CONTRARIO: TODO `superseded` se atribuye a un apply fallido",
        APPLY,
        '    if crudo:\n        return "PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO"\n'
        '    return "PLAN_SUPERSEDED"',
        '    return "PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO"\n',
        f"{SUITE_CAUSA}::test_la_inferencia_distingue_los_dos_casos_por_ENUMERACION",
        "PLAN_SUPERSEDED",
    ),
    # -- 9. La inferencia mira la lista PARSEADA -------------------------
    Mutacion(
        "la inferencia pasa a mirar las notas ya parseadas",
        APPLY,
        "    if crudo:\n",
        "    import json as _j\n"
        "    try:\n"
        "        _p = _j.loads(crudo or '[]')\n"
        "    except Exception:\n"
        "        _p = []\n"
        "    if _p:\n",
        f"{SUITE_CAUSA}::test_la_inferencia_distingue_los_dos_casos_por_ENUMERACION",
        "la inferencia ha pasado a mirar la lista parseada",
    ),
]


def _purgar_pycache() -> None:
    """Antes y después. Un `.pyc` viejo hace que la mutación no se vea."""
    subprocess.run(
        ["find", str(REPO), "-name", "__pycache__", "-type", "d",
         "-prune", "-exec", "rm", "-rf", "{}", "+"],
        check=False, capture_output=True,
    )


def _arbol_limpio() -> bool:
    """TRINQUETE. Mira lo TRACKED, que es lo que la mutación puede destruir."""
    r = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain",
                        "--untracked-files=no"],
                       capture_output=True, text=True, check=True)
    return not r.stdout.strip()


def _leer(ruta: str) -> str:
    return (REPO / ruta).read_text(encoding="utf-8")


def _escribir(ruta: str, texto: str) -> None:
    (REPO / ruta).write_text(texto, encoding="utf-8")


def _restaurar(ruta: str, original: str) -> None:
    """Y se verifica POR EFECTO, no porque el comando dijera que lo hizo."""
    subprocess.run(["git", "-C", str(REPO), "checkout", "--", ruta], check=True)
    if _leer(ruta) != original:
        raise SystemExit(
            f"RESTAURACIÓN FALLIDA en {ruta}: el árbol ha quedado mutado. "
            f"Revísalo a mano ANTES de seguir.")


def _correr(prueba: str) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", prueba, "-q", "-p", "no:randomly",
         "--no-header", "-x"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    if not _arbol_limpio():
        print("ÁRBOL SUCIO. Commitea antes: las mutaciones se revierten con "
              "`git checkout --` y se llevarían por delante tu trabajo.")
        return 2

    _purgar_pycache()
    fallos = []
    for i, m in enumerate(MUTACIONES, 1):
        print(f"\n[{i}/{len(MUTACIONES)}] {m.nombre}")
        original = _leer(m.fichero)
        if m.viejo not in original:
            fallos.append(f"{i}. el texto a mutar ya no está en {m.fichero}: "
                          f"esta mutación no está mutando NADA")
            print("   ANCLA PERDIDA — la mutación no se aplicó")
            continue
        _escribir(m.fichero, original.replace(m.viejo, m.nuevo, 1))
        _purgar_pycache()
        try:
            rc, salida = _correr(m.prueba)
        finally:
            _restaurar(m.fichero, original)
            _purgar_pycache()

        if rc == 0:
            fallos.append(f"{i}. {m.nombre}: la prueba SIGUIÓ VERDE con la "
                          f"garantía revertida ({m.prueba})")
            print("   VERDE CON LA MUTACIÓN PUESTA — la prueba no protege nada")
        elif m.esperado not in salida:
            fallos.append(f"{i}. {m.nombre}: roja, pero SIN su causa. "
                          f"Se esperaba {m.esperado!r} en el fallo")
            print(f"   ROJA POR OTRA RAZÓN — no aparece {m.esperado!r}")
        else:
            print("   roja, y por su causa")

    print("\n" + "=" * 74)
    if fallos:
        print(f"CALIBRACIÓN FALLIDA: {len(fallos)} de {len(MUTACIONES)}")
        for f in fallos:
            print(f"  · {f}")
        return 1
    print(f"CALIBRACIÓN OK: {len(MUTACIONES)}/{len(MUTACIONES)} rojas por su causa")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
