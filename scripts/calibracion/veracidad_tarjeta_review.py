#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CALIBRACIÓN del corte «veracidad de la tarjeta de Review».

Un verde sólo vale si la prueba que lo da es CAPAZ DE PONERSE ROJA, y roja
POR SU CAUSA. Este calibrador vuelve a meter cada defecto —uno cada vez, sobre
el código real, no sobre una copia— y comprueba dos cosas de cada rojo:

    1. que los casos que DEBÍAN caer cayeron, y
    2. que el mensaje del rojo DICE LA CAUSA.

Lo segundo es lo que separa esto de contar colores: un rojo con un mensaje de
valor pelado («assert 'X' == 'Y'») se lee igual que uno sin causa, y no
demuestra que el control apunte a donde dice apuntar.

CÓMO SE REFERENCIAN LAS MUTACIONES. Por NOMBRE, nunca por índice. Un control
mal dirigido por un índice desplazado nunca enrojece, y como nadie lo ve
fallar, nada lo delata.

EL CALIBRADOR SE CALIBRA A SÍ MISMO. Antes de mutar nada comprueba que la
suite está VERDE (si ya estuviera roja, cualquier rojo posterior sería suyo y
no de la mutación) y que cada mutación MUERDE DE VERDAD el fichero —que el
texto que dice sustituir existía y cambió—. Una mutación que no se aplica
produce un «no cayó nadie» indistinguible de un control flojo.

EL RECUENTO SALE DEL FICHERO, no de este plan: `MUTACIONES` se recorre, y el
total se imprime de `len(MUTACIONES)`.

EL TECHO DE ESTE CALIBRADOR, dicho entero:
  * Muta por SUSTITUCIÓN DE TEXTO EXACTO sobre el fuente. No es una red AST:
    no ve alias, ni reexportaciones, ni una segunda copia de la misma lógica en
    otro módulo. Si alguien duplicara `_correccion_efectiva` en otro sitio y el
    servicio llamara a la copia, estas mutaciones seguirían aplicándose al
    original y el rojo no llegaría. Lo que sí garantiza es que el texto que
    dice mutar existe y cambió: si el código se mueve, el calibrador falla en
    voz alta en vez de callar.
  * No mide autorización, ni Neo4j, ni el writer.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
VISOR = RAIZ / "viewer"
SERVICIO = VISOR / "app" / "services" / "v3_review.py"
CONSOLA = VISOR / "app" / "services" / "review_console_v2.py"
PLANTILLA = VISOR / "app" / "templates" / "v3_review.html"
PANEL = VISOR / "app" / "templates" / "chassis" / "review_item.html"
SUITE = "tests/test_veracidad_de_la_tarjeta_de_review.py"


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
    #: Mutaciones de apoyo que se aplican junto a la principal.
    extra: tuple[tuple[Path, str, str], ...] = field(default_factory=tuple)


MUTACIONES: tuple[Mutacion, ...] = (
    # ---- PIEZA A: el signo mostrado -------------------------------------
    Mutacion(
        nombre="lector-de-la-clave-antigua",
        fichero=SERVICIO,
        viejo='"signo": negation_code(claim.get("negated")),\n            "signo_label": negation_label(negation_code(claim.get("negated"))),',
        nuevo='"signo": negation_code(claim.get("negation")),\n            "signo_label": negation_label(negation_code(claim.get("negation"))),',
        caen=(
            "test_negado_true_la_tarjeta_dice_que_esta_negado",
            "test_negado_false_la_tarjeta_dice_que_NO_esta_negado",
            "test_la_prosa_y_el_campo_estructurado_dicen_lo_mismo",
            "test_la_mutacion_a_la_clave_antigua_derrumba_los_tres_casos",
        ),
        dice="HECHO NEGADO PINTADO COMO",
        porque="EL DEFECTO ORIGINAL: leer `proposal.negation`, que no existe.",
    ),
    Mutacion(
        nombre="ausente-se-convierte-en-false",
        fichero=SERVICIO,
        viejo='"signo": negation_code(claim.get("negated")),',
        nuevo='"signo": negation_code(bool(claim.get("negated"))),',
        caen=("test_negado_ausente_es_no_disponible_y_NUNCA_se_vuelve_false",),
        dice="UNA PROPUESTA SIN `negated` SE PINTÓ COMO AFIRMATIVA",
        porque="AUSENCIA != CERO. Colapsar el tercer estado sobre el segundo.",
    ),
    Mutacion(
        nombre="la-tarjeta-pierde-el-codigo-del-signo",
        fichero=PLANTILLA,
        viejo='<dd data-signo="{{ item.signo | e }}">{{ item.signo_label | e }}</dd>',
        nuevo='<dd>{{ item.proposal.negation | default("No disponible") | e }}</dd>',
        caen=(
            "test_negado_true_la_tarjeta_dice_que_esta_negado",
            "test_negado_false_la_tarjeta_dice_que_NO_esta_negado",
        ),
        dice="EL CAMPO «Negación» NO APARECE EN LA TARJETA SERVIDA",
        porque="La plantilla vuelve EXACTAMENTE a como estaba antes del corte.",
    ),
    # ---- PIEZA E: la segunda tarjeta -------------------------------------
    Mutacion(
        nombre="la-consola-vuelve-a-pintar-la-clase",
        fichero=CONSOLA,
        viejo='"signo": negation_code(negated),\n        "signo_label": negation_label(negation_code(negated)),',
        nuevo='"signo": negation_code(_clean(negation_kind)),\n        "signo_label": negation_label(negation_code(_clean(negation_kind))),',
        caen=(
            "test_la_consola_publica_el_signo_y_no_la_clase_de_negacion",
            "test_la_ficha_SERVIDA_de_la_consola_dice_el_signo",
        ),
        dice="LA SEGUNDA TARJETA PUBLICA",
        porque="El defecto de /panel/review: la CLASE bajo el rótulo del SIGNO.",
    ),
    Mutacion(
        nombre="la-ficha-de-la-consola-vuelve-a-pintar-la-clase",
        fichero=PANEL,
        viejo='<dd data-signo="{{ row.signo | e }}">{{ row.signo_label | e }}</dd>',
        nuevo="<dd>{{ row.negation_kind | e if row.negation_kind else 'no disponible' }}</dd>",
        caen=("test_la_ficha_SERVIDA_de_la_consola_dice_el_signo",),
        dice="EL CAMPO «Negación» DE LA FICHA SERVIDA NO PUBLICA EL CÓDIGO",
        porque=(
            "LA PLANTILLA de /panel/review vuelve a como estaba. Es la mitad "
            "que `row_view` no puede vigilar: antes de este corte el `negated` "
            "YA se calculaba bien y aun así la pantalla decía «no disponible»."
        ),
    ),
    # ---- PIEZA C: F-7, la corrección fantasma ---------------------------
    Mutacion(
        nombre="el-servidor-se-cree-el-formulario",
        fichero=SERVICIO,
        viejo="correction, correction_changes = _correccion_efectiva(\n                correction, proposal.get(\"proposal\") or {}\n            )",
        nuevo="correction_changes = {}",
        caen=(
            "test_aprobar_sin_tocar_nada_deja_CERO_correcciones_en_el_acta",
            "test_el_acta_leida_del_fichero_coincide_con_la_del_almacen",
            "test_correct_que_reenvia_la_propuesta_intacta_se_rechaza",
        ),
        dice="EL ACTA PERSISTIDA AFIRMA UNA CORRECCIÓN QUE EL REVISOR NO HIZO",
        porque="F-7 EXACTO: «Aprobar» sin tocar nada deja una corrección falsa.",
    ),
    Mutacion(
        nombre="la-precarga-del-alcance-desaparece",
        fichero=PLANTILLA,
        viejo="""<label>Alcance <input name="scope" value="{{ item.proposal.scope | default('') | e }}"></label>""",
        nuevo="""<label>Alcance <input name="scope"></label>""",
        caen=("test_el_formulario_servido_SIGUE_trayendo_el_alcance_precargado",),
        dice="EL FORMULARIO YA NO MANDA `scope=not_available`",
        porque=(
            "EL ARREGLO EQUIVOCADO. Quitar el campo del formulario apaga el "
            "síntoma y deja el servidor creyéndose lo que le manden: el "
            "siguiente consumidor que precargue un valor reabre F-7."
        ),
    ),
    # ---- PIEZA D: la corrección real no se pierde ------------------------
    Mutacion(
        nombre="sin-captura-del-cambio",
        fichero=SERVICIO,
        viejo='        cambios[campo] = {\n            "before": None if anterior is _AUSENTE else anterior,',
        nuevo='        cambios.pop(campo, None) if False else None\n        _descartado = {\n            "before": None if anterior is _AUSENTE else anterior,',
        caen=(
            "test_cambiar_false_a_true_registra_UNA_correccion_exactamente_esa",
            "test_cambiar_true_a_false_registra_la_correccion_inversa",
            "test_una_correccion_de_alcance_de_verdad_si_se_registra",
            "test_poner_el_signo_donde_no_lo_habia_es_una_correccion_real",
        ),
        dice="EL `before`/`after` NO DESCRIBE EL CAMBIO QUE OCURRIÓ",
        porque="El acta dice «hubo corrección» sin decir de qué a qué.",
    ),
    Mutacion(
        nombre="matar-las-fantasma-matando-todas",
        fichero=SERVICIO,
        viejo="        if anterior is not _AUSENTE and _mismo_valor(anterior, valor):",
        nuevo="        if True:",
        caen=(
            "test_cambiar_false_a_true_registra_UNA_correccion_exactamente_esa",
            "test_cambiar_true_a_false_registra_la_correccion_inversa",
            "test_una_correccion_de_alcance_de_verdad_si_se_registra",
            "test_poner_el_signo_donde_no_lo_habia_es_una_correccion_real",
            # `test_correct_..._se_rechaza` NO entra aquí, y conviene decir por
            # qué: con esta mutación un `CORRECT` se queda sin campos, el
            # servicio lo rechaza con 400 y el caso sigue VERDE. Es el
            # resultado correcto, no un control flojo — declararlo como caída
            # era un error de ESTE fichero, y el calibrador lo destapó.
        ),
        dice="UNA CORRECCIÓN HUMANA REAL SE PERDIÓ O SE DEFORMÓ",
        porque=(
            "EL SIMÉTRICO. La forma barata de matar las correcciones fantasma "
            "es dejar de registrar correcciones. Sin este control, el arreglo "
            "más fácil sería el que rompe el producto."
        ),
    ),
    Mutacion(
        nombre="ausente-igual-a-false-en-la-correccion",
        fichero=SERVICIO,
        viejo="        anterior = claim.get(campo, _AUSENTE)",
        nuevo="        anterior = claim.get(campo, False)",
        caen=("test_poner_el_signo_donde_no_lo_habia_es_una_correccion_real",),
        dice="SE PERDIÓ UNA DECISIÓN HUMANA POR CONFUNDIR AUSENTE CON `False`",
        porque="AUSENCIA != CERO, ahora del lado de la acción del operador.",
    ),
    Mutacion(
        nombre="correct-vacio-se-acepta",
        fichero=SERVICIO,
        viejo='            if human_decision == "CORRECT" and not correction:\n                # Un `CORRECT` que reenvía la propuesta intacta no es una',
        nuevo='            if False:\n                # Un `CORRECT` que reenvía la propuesta intacta no es una',
        caen=("test_correct_que_reenvia_la_propuesta_intacta_se_rechaza",),
        dice="UN `CORRECT` SIN NINGÚN CAMBIO FUE ACEPTADO",
        porque="Un acta que dice «la persona corrigió» con `correction` vacío.",
    ),
)


def _pytest(selector: str | None = None) -> subprocess.CompletedProcess:
    # `--color=no` NO es cosmético: con color, las líneas del resumen empiezan
    # por una secuencia de escape y `startswith("FAILED")` no casa NUNCA. El
    # recuento de rojos salía vacío mientras la suite estaba roja de verdad —un
    # control que no ve caer a nadie y no lo dice es justo lo que este fichero
    # existe para impedir, así que queda escrito aquí.
    orden = [sys.executable, "-m", "pytest", SUITE, "-q", "-p", "no:randomly",
             "--color=no"]
    if selector:
        orden += ["-k", selector]
    return subprocess.run(orden, cwd=VISOR, capture_output=True, text=True)


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        if ".git" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio() -> bool:
    """TRACKED únicamente: es lo que la mutación puede destruir y lo que
    `git checkout --` puede devolver. Un fichero nuevo sin seguir no es
    contaminación del sujeto."""
    r = subprocess.run(
        ["git", "diff", "--stat", "--"], cwd=RAIZ, capture_output=True, text=True
    )
    return r.stdout.strip() == ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo", help="calibrar una mutación por NOMBRE")
    args = parser.parse_args()

    if not _arbol_limpio():
        print("ABORTA: el árbol tiene cambios sin commitear. Una mutación sobre "
              "un árbol sucio no se puede restaurar por efecto, y la medición "
              "no valdría.")
        return 2

    seleccionadas = MUTACIONES
    if args.solo:
        seleccionadas = tuple(m for m in MUTACIONES if m.nombre == args.solo)
        if not seleccionadas:
            print(f"ABORTA: no hay ninguna mutación llamada {args.solo!r}. "
                  f"Hay: {[m.nombre for m in MUTACIONES]}")
            return 2

    # AUTOCALIBRACIÓN 1: el punto de partida está VERDE.
    _purgar_pycache()
    base = _pytest()
    if base.returncode != 0:
        print("ABORTA: la suite YA está roja sin mutar. Cualquier rojo de "
              "abajo sería suyo, no de la mutación.")
        print(base.stdout[-3000:])
        return 2
    print(f"BASE VERDE. {SUITE}\n")

    # El recuento sale del FICHERO, no del plan.
    total = len(seleccionadas)
    fallos: list[str] = []
    print(f"{total} mutaciones declaradas en este fichero.\n")

    for mut in seleccionadas:
        print("=" * 74)
        print(f"MUTACIÓN  {mut.nombre}")
        print(f"  fichero {mut.fichero.relative_to(RAIZ)}")
        print(f"  porqué  {mut.porque}")
        parches = ((mut.fichero, mut.viejo, mut.nuevo),) + mut.extra
        try:
            # AUTOCALIBRACIÓN 2: la mutación MUERDE.
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
                    f"{mut.nombre}: LA SUITE SIGUE VERDE CON EL DEFECTO PUESTO. "
                    f"Ningún control vigila esto."
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
                print(f"  ROJOS      {len(rojos)}: {rojos}")

            if mut.dice not in salida:
                fallos.append(
                    f"{mut.nombre}: el rojo NO DICE SU CAUSA. Se esperaba el "
                    f"mensaje {mut.dice!r} y no aparece. Un rojo con un valor "
                    f"pelado se lee igual que uno sin causa."
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
            # RESTAURACIÓN VERIFICADA POR EFECTO, no por «el comando no falló».
            if not _arbol_limpio():
                print("  *** EL ÁRBOL NO QUEDÓ RESTAURADO. ABORTA. ***")
                return 3

    print("=" * 74)
    # Y la vuelta a verde, medida, no supuesta.
    _purgar_pycache()
    final = _pytest()
    if final.returncode != 0:
        print("LA SUITE NO VOLVIÓ A VERDE tras restaurar. La calibración dejó "
              "el árbol tocado y sus resultados no valen.")
        print(final.stdout[-3000:])
        return 3

    if fallos:
        print(f"CALIBRACIÓN FALLIDA — {len(fallos)} de {total} mutaciones:")
        for f in fallos:
            print("  * " + f)
        return 1
    print(f"CALIBRACIÓN OK — {total}/{total} mutaciones producen un rojo que "
          f"DICE SU CAUSA, y la suite vuelve a verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
