#!/usr/bin/env python3
"""Mutaciones del ARNES de EXP-1: el que prueba al que prueba.

En la ronda 1 de este PR, los casos 3 y 4 de `calibra_topologia_publicable.py`
eran inertes: corrian el regex FUERA del gate, asi que seguian VERDES con el
motor del gate destripado. Un arnes que sobrevive a que su sujeto desaparezca
no mide nada. Este fichero fija esa leccion como propiedad ejecutable.

Cada mutacion tiene nombre, mensaje propio y un conjunto EXACTO de casos que
debe poner en ROJO -ni mas ni menos-, asi que ni un mutante superviviente ni
un rojo prestado pasan desapercibidos. El "porque" de cada una explica por que
ese conjunto y no otro.

El gate se restaura por EFECTO (SHA-256) tras cada mutacion, pase lo que pase.

Uso: python3 scripts/calibracion/mutaciones_topologia_publicable.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / ".github" / "scripts" / "check_no_topologia_publicable.py"
CALIB = REPO / "scripts" / "calibracion" / "calibra_topologia_publicable.py"

ANCLA_MOTOR = '    violaciones: list[tuple[str, int, str]] = []'
ANCLA_MARCADOR = (
    'MARCADOR_EXCEPCION = re.compile(\n'
    '    r"#\\s*topologia:\\s*excepcion declarada\\s+(?P<motivo>\\S.*)"\n'
    ')'
)
MUT_MARCADOR = (
    'MARCADOR_EXCEPCION = re.compile(\n'
    '    r"#\\s*topologia:\\s*excepcion declarada"\n'
    ')'
)
ANCLA_RANGO = '    r"|192\\.168\\.\\d{1,3}\\.\\d{1,3}"'
MUT_RANGO = (
    '    r"|192\\.168\\.\\d{1,3}\\.\\d{1,3}"\n'
    '    r"|192\\.0\\.2\\.\\d{1,3}"  # MUTANTE M3: deja de tolerar RFC 5737'
)
ANCLA_OOXML = '    try:\n        datos = f.read_bytes()\n    except OSError:\n        return []'
MUT_OOXML = (
    '    return []  # MUTANTE M4: la cobertura OOXML desaparece\n'
    '    try:\n        datos = f.read_bytes()\n    except OSError:\n        return []'
)
ANCLA_AUTO = (
    '    "codigo-no-test": (\n'
    '        "*.py",\n'
    '        "*/*.py",\n'
)
MUT_AUTO = (
    '    "codigo-no-test": (\n'
    '        # MUTANTE M5: el codigo sale de la superficie publicable.\n'
)

MUTANTES = {
    "M1 motor_destripado": {
        "ancla": ANCLA_MOTOR,
        "reemplazo": ANCLA_MOTOR + "\n    return []  # MUTANTE M1",
        "rojos_exigidos": {
            "caso_1_ip_privada_nueva_se_pone_rojo",
            "caso_3_fixture_legitimo_sigue_verde",
            "caso_4_ablacion_categoria_tests",
            "caso_5_excepcion_declarada",
            "caso_6_marcador_sin_motivo_no_exime",
            "caso_7_docx_cobertura_real",
            "caso_8_autocobertura_del_guardarrail",
        },
        "porque": (
            "si el motor no devuelve nada, todo caso que afirme una DETECCION "
            "se cae. Sobreviven los dos que no dependen de el: el 2, que "
            "afirma una AUSENCIA de violacion, y el 9, que interroga a "
            "`clasifica()` y no al motor"
        ),
    },
    "M2 marcador_sin_motivo": {
        "ancla": ANCLA_MARCADOR,
        "reemplazo": MUT_MARCADOR,
        "rojos_exigidos": {"caso_6_marcador_sin_motivo_no_exime"},
        "porque": (
            "quitar la exigencia de motivo solo puede tumbar al caso que la "
            "mide; si tumbase otro, ese otro dependia de algo que no declara"
        ),
    },
    "M3 no_tolera_el_rango_de_documentacion": {
        "ancla": ANCLA_RANGO,
        "reemplazo": MUT_RANGO,
        "rojos_exigidos": {
            "caso_2_valor_ficticio_da_verde",
            "caso_3_fixture_legitimo_sigue_verde",
            "caso_5_excepcion_declarada",
            "caso_6_marcador_sin_motivo_no_exime",
            "caso_7_docx_cobertura_real",
        },
        "porque": (
            "el caso 2 es el unico que afirma que el rango de documentacion "
            "RFC 5737 NO dispara el gate, asi que es el que tiene que caer. "
            "Caen con el los dos que ademas exigen VERDE GLOBAL (3 y 7): la "
            "plantilla saneada usa 192.0.2.x, de modo que el arbol entero se "
            "pone rojo, y con ellos el 5 y el 6, cuya segunda mitad exige VERDE "
            "global tras poner el marcador. Se declara aqui, medido, para que "
            "ese arrastre sea una expectativa escrita y no un rojo prestado que "
            "nadie explico"
        ),
    },
    "M4 sin_cobertura_ooxml": {
        "ancla": ANCLA_OOXML,
        "reemplazo": MUT_OOXML,
        "rojos_exigidos": {"caso_7_docx_cobertura_real"},
        "porque": (
            "si el gate deja de abrir el ZIP, el unico caso que puede notarlo "
            "es el que mete el conocido negativo dentro de word/document.xml. "
            "Que caiga SOLO el 7 es lo que permite DECLARAR cobertura OOXML en "
            "vez de prometerla"
        ),
    },
    "M5 sin_autocobertura": {
        "ancla": ANCLA_AUTO,
        "reemplazo": MUT_AUTO,
        "rojos_exigidos": {
            "caso_3_fixture_legitimo_sigue_verde",
            "caso_4_ablacion_categoria_tests",
            "caso_8_autocobertura_del_guardarrail",
            "caso_9_frontera_decidible",
        },
        "porque": (
            "sacar el codigo no-test de la superficie es exactamente el "
            "agujero de la ronda 1: el guardarrail deja de mirarse. Cae el 8 "
            "(autocobertura), cae el 9 (la superficie se encoge por debajo de "
            "lo que puede encontrar algo nuevo), y caen el 3 y el 4, cuyos "
            "diferenciales usan esa clase como la UNICA via por la que el "
            "fixture -que es un `.py`- puede entrar en la superficie: sin ella "
            "la ablacion de `test-o-fixture` ya no lo hace aparecer"
        ),
    },
}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _arbol_tracked_limpio() -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPO, capture_output=True, text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == ""


def _cargar_calibrador():
    spec = importlib.util.spec_from_file_location("calib_exp1", CALIB)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _rojos_bajo_mutacion(ancla: str, reemplazo: str) -> tuple[set[str], list[str]]:
    original = GATE.read_bytes()
    h0 = hashlib.sha256(original).hexdigest()
    texto = original.decode("utf-8")
    if ancla not in texto:
        raise SystemExit(
            f"ancla de mutacion no encontrada en {GATE.relative_to(REPO)}: "
            "el sujeto se movio y esta mutacion ya no ataca lo que dice atacar"
        )
    GATE.write_text(texto.replace(ancla, reemplazo, 1), encoding="utf-8")
    rojos: set[str] = set()
    causas: list[str] = []
    try:
        cal = _cargar_calibrador()
        for caso in cal.CASOS:
            try:
                caso()
            except cal.Fallo as e:
                rojos.add(caso.__name__)
                causas.append(f"{caso.__name__}: {e}")
            except Exception as e:  # una mutacion puede romper el import, no el arnes
                rojos.add(caso.__name__)
                causas.append(f"{caso.__name__}: {type(e).__name__}: {e}")
    finally:
        GATE.write_bytes(original)
        if _sha256(GATE) != h0:
            raise SystemExit("RESTAURACION FALLIDA del gate: arbol contaminado")
    return rojos, causas


def main() -> int:
    if not _arbol_tracked_limpio():
        print("ERROR: el arbol tracked no esta limpio antes de mutar; una "
              "mutacion medida sobre un arbol sucio no mide nada.",
              file=sys.stderr)
        return 2

    fallos = []
    for nombre, m in MUTANTES.items():
        print(f"-- {nombre} --")
        rojos, causas = _rojos_bajo_mutacion(m["ancla"], m["reemplazo"])
        esperados = m["rojos_exigidos"]
        for c in sorted(causas):
            print(f"   ROJO  {c[:150]}")
        faltan, sobran = esperados - rojos, rojos - esperados
        if faltan:
            fallos.append(
                f"[{nombre}] MUTANTE SUPERVIVIENTE en {sorted(faltan)}: siguieron "
                f"VERDES con el sujeto mutado, asi que no lo estan probando. "
                f"Razon exigida: {m['porque']}."
            )
        if sobran:
            fallos.append(
                f"[{nombre}] ROJOS DE MAS en {sorted(sobran)}: la mutacion no esta "
                f"dirigida, o esos casos dependen de algo que no declaran. "
                f"Razon exigida: {m['porque']}."
            )
        if not faltan and not sobran:
            print(f"   OK  rojos exactamente los exigidos: {sorted(esperados)}")

    if not _arbol_tracked_limpio():
        print("ERROR: el arbol quedo sucio tras las mutaciones.", file=sys.stderr)
        return 2

    if fallos:
        print(f"\n{len(fallos)} fallo(s):", file=sys.stderr)
        for f in fallos:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"\nOK: {len(MUTANTES)}/{len(MUTANTES)} mutaciones dejaron el rastro exigido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
