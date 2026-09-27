#!/usr/bin/env python3
"""Mutaciones del ARNES de EXP-1: el que prueba al que prueba.

En la ronda 1 de este PR, los casos 3 y 4 de `calibra_topologia_publicable.py`
eran inertes: corrian el regex FUERA del gate, asi que seguian VERDES con el
motor del gate destripado. Un arnes que sobrevive a que su sujeto desaparezca
no mide nada. Este fichero fija esa leccion como propiedad ejecutable.

Cada mutacion tiene nombre, mensaje propio y un conjunto EXACTO de casos que
debe poner en ROJO -ni mas ni menos-, asi que ni un rojo prestado ni un rojo
de mas pasan desapercibidos:

  M1 `motor_destripado`  -> `encuentra_violaciones()` devuelve [].
     Rojos exigidos: casos 1, 3, 4, 5 y 6. El caso 2 espera VERDE por
     construccion (afirma una ausencia de violacion) y por eso sobrevive: es
     el unico que puede.
  M2 `marcador_sin_motivo` -> el marcador de excepcion vuelve a no exigir
     motivo. Rojo exigido: SOLO el caso 6. Mutacion dirigida: si tumbase
     otros casos, es que el caso 6 no aisla lo que dice aislar.

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

ANCLA_MOTOR = (
    '    """Devuelve (ruta, num_linea_1indexado, texto_ip) por cada violacion."""'
)
ANCLA_MARCADOR = (
    'MARCADOR_EXCEPCION = re.compile(r"#\\s*topologia:\\s*excepcion declarada'
    '\\s+(?P<motivo>\\S.*)")'
)
MUT_MARCADOR = (
    'MARCADOR_EXCEPCION = re.compile(r"#\\s*topologia:\\s*excepcion declarada")'
)

MUTANTES = {
    "M1 motor_destripado": {
        "ancla": ANCLA_MOTOR,
        "reemplazo": ANCLA_MOTOR + "\n    return []  # MUTANTE M1",
        "rojos_exigidos": {
            "caso_1_ip_privada_nueva_se_pone_rojo",
            "caso_3_fixture_legitimo_sigue_verde",
            "caso_4_ablacion_exclusion_tests",
            "caso_5_excepcion_declarada",
            "caso_6_marcador_sin_motivo_no_exime",
        },
        "porque": (
            "si el motor del gate no devuelve nada, todo caso que afirme una "
            "DETECCION tiene que caerse; el unico que puede sobrevivir es el "
            "que afirma una ausencia (caso 2)"
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
    GATE.write_text(texto.replace(ancla, reemplazo), encoding="utf-8")
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
    finally:
        GATE.write_bytes(original)
        if _sha256(GATE) != h0:
            raise SystemExit("RESTAURACION FALLIDA del gate: arbol contaminado")
    return rojos, causas


def main() -> int:
    if not _arbol_tracked_limpio():
        print(
            "ERROR: el arbol tracked no esta limpio antes de mutar; una "
            "mutacion medida sobre un arbol sucio no mide nada.",
            file=sys.stderr,
        )
        return 2

    fallos = []
    for nombre, m in MUTANTES.items():
        print(f"-- {nombre} --")
        rojos, causas = _rojos_bajo_mutacion(m["ancla"], m["reemplazo"])
        esperados = m["rojos_exigidos"]
        for c in sorted(causas):
            print(f"   ROJO  {c[:160]}")
        faltan = esperados - rojos
        sobran = rojos - esperados
        if faltan:
            fallos.append(
                f"[{nombre}] MUTANTE SUPERVIVIENTE en {sorted(faltan)}: "
                f"esos casos siguieron VERDES con el sujeto mutado, asi que "
                f"no lo estan probando. Razon exigida: {m['porque']}."
            )
        if sobran:
            fallos.append(
                f"[{nombre}] ROJOS DE MAS en {sorted(sobran)}: la mutacion no "
                f"esta dirigida o esos casos dependen de algo que no declaran. "
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
