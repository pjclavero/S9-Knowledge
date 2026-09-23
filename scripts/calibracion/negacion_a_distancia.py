#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CALIBRACIÓN del corte «una negación jamás acaba materializada en positivo».

Mismo contrato que `veracidad_tarjeta_review.py`, del que esto copia el motor
a propósito: un verde sólo vale si la prueba que lo da es CAPAZ DE PONERSE
ROJA, y roja POR SU CAUSA. Cada mutación vuelve a meter un defecto —uno cada
vez, sobre el código real, no sobre una copia— y se comprueba:

    1. que los casos que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa, no un valor pelado.

LAS MUTACIONES SE REFERENCIAN POR NOMBRE, nunca por índice.

EL CALIBRADOR SE CALIBRA A SÍ MISMO: antes de mutar comprueba que la suite
está VERDE, que el árbol TRACKED está limpio, y que cada mutación MUERDE —que
el texto que dice sustituir existía, aparecía UNA vez y cambió—. Después
restaura y verifica la restauración POR EFECTO.

EL RECUENTO SALE DEL FICHERO: `MUTACIONES` se recorre y el total es
`len(MUTACIONES)`.

EL CRUCE: al final compara los casos que la suite RECOLECTA (`--collect-only`,
no una lista escrita aquí) contra los rojos REALES. Un testigo que ninguna
mutación enrojece certifica cualquier cosa.

EL TECHO DE ESTE CALIBRADOR, dicho entero:
  * Muta por SUSTITUCIÓN DE TEXTO EXACTO sobre el fuente. NO es una red AST:
    no ve alias, ni reexportaciones, ni una segunda copia de la misma lógica
    en otro módulo. Si la lectura de negación se duplicara en `semantic.py` o
    en `payload.py` y la cadena llamara a la copia, estas mutaciones seguirían
    aplicándose a `deterministic.py` y el rojo no llegaría. Lo que sí
    garantiza es que el texto que dice mutar existe y cambió.
  * MIRA UNA SOLA SUITE (`SUITE`, constante única). Un fichero de test nuevo
    del mismo corte sería INVISIBLE para el cruce. Hay que añadirlo aquí.
  * COLAPSA LA PARAMETRIZACIÓN (`split("[")[0]`): todos los parámetros de un
    `parametrize` cuentan como UN caso. Basta con que uno enrojezca. **LA
    CIFRA QUE IMPRIME EL CRUCE ES LA COLAPSADA, y por tanto OPTIMISTA.** La
    revisión independiente contó a granularidad de PARÁMETRO y encontró
    22/25, no 7/7: tres parámetros afirmativos de `PARES_MINIMOS` eran
    TESTIGOS MUDOS —su rama `else` sólo afirmaba `negated is False`, sin la
    aserción de `review_required` que cubre a sus gemelos—. Ya están
    igualados, pero el techo se queda escrito: quien lea «7/7» tiene que
    saber que son casos, no parámetros.
  * NO mide el writer con `--apply`, ni Neo4j real, ni la frontera semántica.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MOTOR = RAIZ / "data-engine"
EXTRACTOR = MOTOR / "app" / "knowledge_v3" / "extraction" / "deterministic.py"
CUES = MOTOR / "app" / "knowledge_v3" / "extraction" / "cues.py"
SUITE = "app/tests/test_negacion_a_distancia_no_materializable.py"


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


ANCLA_ARREGLADA = (
    "        negation_anchor = min(first, subject_hit.first_token)\n"
    "        negacion = _cues.classify_negation(\n"
    "            tokens,\n"
    "            lo=max(sentence.first_token, negation_anchor - NEGATION_WINDOW),"
)

MUTACIONES: tuple[Mutacion, ...] = (
    # ---- EL DEFECTO ORIGINAL, tal cual estaba en origin/main@d0a0962 -----
    Mutacion(
        nombre="la-ventana-vuelve-a-anclarse-en-el-predicado",
        fichero=EXTRACTOR,
        viejo=ANCLA_ARREGLADA,
        nuevo=(
            "        negacion = _cues.classify_negation(\n"
            "            tokens,\n"
            "            lo=max(sentence.first_token, first - NEGATION_WINDOW),"
        ),
        caen=(
            "test_el_par_minimo_se_sostiene_con_el_sujeto_corto_y_con_el_largo",
            "test_la_longitud_del_NOMBRE_del_sujeto_no_decide_si_se_lee_la_negacion",
            "test_las_variantes_declaradas_salen_negadas_y_pidiendo_revision",
            "test_la_forma_negativa_no_llega_a_una_operacion_de_afirmacion",
        ),
        dice="UNA FRASE NEGATIVA SALIO COMO AFIRMACION PLANA",
        porque=(
            "EL DEFECTO EXACTO DE LA BASE: la ventana medida desde la frase "
            "de relación, de modo que la longitud del nombre del sujeto "
            "decide si la negación se lee. Es el `git show d0a0962` de estas "
            "cuatro líneas."
        ),
    ),
    # ---- ARREGLOS EQUIVOCADOS que apagan el síntoma ----------------------
    Mutacion(
        nombre="el-negado-se-aplana-al-construir-el-claim",
        fichero=EXTRACTOR,
        viejo="        negated = negacion.negated\n        negation_kind = negacion.kind",
        nuevo="        negated = False\n        negation_kind = negacion.kind",
        caen=(
            "test_el_par_minimo_se_sostiene_con_el_sujeto_corto_y_con_el_largo",
            "test_las_variantes_declaradas_salen_negadas_y_pidiendo_revision",
            "test_la_forma_negativa_no_llega_a_una_operacion_de_afirmacion",
        ),
        dice="UNA FRASE NEGATIVA SALIO COMO AFIRMACION PLANA",
        porque=(
            "LA PROPIEDAD, sin pasar por la ventana: el productor escribe "
            "False aunque haya examinado la negación. Si sólo el caso de la "
            "ventana enrojeciera, la suite estaría vigilando una línea, no "
            "una propiedad."
        ),
    ),
    Mutacion(
        nombre="la-ventana-se-abre-y-deja-de-acotarse-a-la-clausula",
        fichero=EXTRACTOR,
        viejo="            lo=max(sentence.first_token, negation_anchor - NEGATION_WINDOW),",
        nuevo="            lo=sentence.first_token,",
        extra=((EXTRACTOR, "            clause_scoped=True,", "            clause_scoped=False,"),),
        caen=("test_ninguna_frase_afirmativa_empieza_a_marcarse_como_negada",),
        dice="SE INVENTO UNA NEGACION SOBRE UNA FRASE AFIRMATIVA",
        porque=(
            "EL RIESGO SIMÉTRICO, y el arreglo perezoso que lo causa. OJO AL "
            "`extra`: abrir SÓLO `lo` a la frase entera NO cambia NADA "
            "medible —`clause_scoped=True` ya acota a la cláusula, así que "
            "esa mitad de la mutación cae en CAPA MUERTA y ningún control "
            "puede enrojecer con ella, ni debe—. Lo que de verdad invierte "
            "una afirmación es quitar el acotado a la cláusula, y por eso las "
            "dos van juntas. HALLAZGO: `NEGATION_WINDOW` sólo puede RESTAR "
            "respecto de la cláusula; ampliarlo es inerte."
        ),
    ),
    Mutacion(
        nombre="todo-pide-revision-y-el-instrumento-deja-de-alcanzar",
        fichero=EXTRACTOR,
        viejo="        review = bool(\n            (negated and not self.negation_policy_at_engine)",
        nuevo="        review = bool(\n            True or (negated and not self.negation_policy_at_engine)",
        caen=(
            "test_la_misma_frase_en_afirmativo_SI_llega_al_plan",
            "test_ninguna_frase_afirmativa_empieza_a_marcarse_como_negada",
        ),
        dice="LA CADENA NO MATERIALIZA NI SIQUIERA LA FRASE AFIRMATIVA",
        porque=(
            "CALIBRA EL CONTROL DEL INSTRUMENTO. Si todo pidiera revisión, "
            "nada llegaría al plan y el caso decisivo estaría verde por no "
            "alcanzar el punto peligroso, no porque la negación se respete. "
            "Sin esta mutación ese control era un testigo que nada podía "
            "poner rojo."
        ),
    ),
    Mutacion(
        nombre="lo-negado-deja-de-proponerse",
        fichero=EXTRACTOR,
        viejo="        negated = negacion.negated\n        negation_kind = negacion.kind",
        nuevo=(
            "        negated = negacion.negated\n"
            "        if negated:\n"
            "            return\n"
            "        negation_kind = negacion.kind"
        ),
        caen=(
            "test_el_unico_cambio_entre_las_dos_entradas_es_la_marca_de_negacion",
            "test_el_par_minimo_se_sostiene_con_el_sujeto_corto_y_con_el_largo",
        ),
        dice="NO HAY UN CLAIM QUE MEDIR",
        porque=(
            "LA PÉRDIDA DISFRAZADA DE ARREGLO: callarse ante lo negado "
            "también impide materializarlo, y dejaría verde cualquier "
            "control que sólo mirase el plan. `03-extractor.md §3.1.1` dice "
            "que lo negado SÍ se propone."
        ),
    ),
    Mutacion(
        nombre="lo-negado-deja-de-pedir-revision",
        fichero=EXTRACTOR,
        viejo="            (negated and not self.negation_policy_at_engine)\n",
        nuevo="            False\n",
        caen=(
            "test_el_par_minimo_se_sostiene_con_el_sujeto_corto_y_con_el_largo",
            "test_las_variantes_declaradas_salen_negadas_y_pidiendo_revision",
        ),
        dice="NEGADO PERO SIN REVISION",
        porque=(
            "Un hecho negativo que se auto-aprueba salta la única puerta "
            "humana entre la propuesta y el grafo."
        ),
    ),
    # ---- LAS MARCAS DE NEGACIÓN HACEN FALTA ------------------------------
    Mutacion(
        nombre="se-vacian-las-marcas-de-negacion",
        fichero=EXTRACTOR,
        viejo="NEGATION_CUES: tuple[str, ...] = _cues.NEGATION_CUES",
        nuevo='NEGATION_CUES: tuple[str, ...] = ()',
        caen=(
            "test_el_par_minimo_se_sostiene_con_el_sujeto_corto_y_con_el_largo",
            "test_las_variantes_declaradas_salen_negadas_y_pidiendo_revision",
            "test_la_forma_negativa_no_llega_a_una_operacion_de_afirmacion",
        ),
        dice="UNA FRASE NEGATIVA SALIO COMO AFIRMACION PLANA",
        porque=(
            "Sin las marcas no hay negación que leer. Se muta el alias del "
            "MÓDULO, que es donde el extractor lo lee: mutarlo dentro de "
            "`cues` no se notaría."
        ),
    ),
    Mutacion(
        nombre="ni-desaparece-de-las-marcas",
        fichero=CUES,
        viejo='NEGATION_CUES: tuple[str, ...] = ("no", "nunca", "jamas", "tampoco", "ni")',
        nuevo='NEGATION_CUES: tuple[str, ...] = ("no", "nunca", "jamas", "tampoco")',
        caen=(
            "test_el_par_minimo_se_sostiene_con_el_sujeto_corto_y_con_el_largo",
            "test_las_variantes_declaradas_salen_negadas_y_pidiendo_revision",
            "test_la_forma_negativa_no_llega_a_una_operacion_de_afirmacion",
        ),
        dice="UNA FRASE NEGATIVA SALIO COMO AFIRMACION PLANA",
        porque=(
            "«Ni siquiera» niega por el «ni». Quitarlo deja el resto de la "
            "familia intacta y sólo cae la forma del enunciado del corte: "
            "distingue el control de «ni siquiera» del de la distancia."
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
    return subprocess.run(orden, cwd=MOTOR, capture_output=True, text=True)


def _casos_del_fichero() -> set[str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "--collect-only", "-q",
         "--color=no", "-p", "no:randomly"],
        cwd=MOTOR, capture_output=True, text=True,
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
                if linea.startswith("FAILED")
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
