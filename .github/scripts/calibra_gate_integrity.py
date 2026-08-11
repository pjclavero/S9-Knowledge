#!/usr/bin/env python3
"""Calibracion de `check_ci_config.py`: el gate tiene que PONERSE ROJO.

Regla del operador: «Una afirmacion no constituye evidencia porque exista un
test verde. La evidencia aparece cuando: sabes que comportamiento afirma;
calibras el mecanismo que lo mide; introduces una violacion; el sistema se pone
rojo; reviertes; vuelve a verde.» Un gate que nunca se ha visto ROJO no es un
gate.

Este script introduce cada violacion de verdad —escribe el fichero, ejecuta el
gate, lee el codigo de retorno, y restaura— y refleja el resultado real. No
simula: si el gate deja de detectar un caso, aqui sale FALLO.

Uso:  python3 .github/scripts/calibra_gate_integrity.py
Sale 0 si TODOS los casos dan el veredicto esperado.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / ".github" / "scripts" / "check_ci_config.py"
CI = REPO / ".github" / "workflows" / "ci.yml"
SUPPLY = REPO / ".github" / "workflows" / "supply-chain.yml"
E2E_CONFTEST = REPO / "tests" / "e2e" / "conftest.py"

# Ficheros que cualquier mutacion puede tocar; se salvan y restauran enteros.
TOCABLES = (CI, SUPPLY, E2E_CONFTEST)

VERDE, ROJO = "VERDE", "ROJO"


def ejecuta_gate() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    return p.returncode, (p.stdout + p.stderr)


def ramas_de_origin() -> list[str]:
    p = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    ramas = []
    for linea in p.stdout.split():
        nombre = linea[len("origin/"):] if linea.startswith("origin/") else linea
        if nombre and nombre != "HEAD":
            ramas.append(nombre)
    return sorted(set(ramas))


# --------------------------------------------------------------------------
# Mutaciones. Cada una devuelve None; opera sobre los ficheros del repo.
# --------------------------------------------------------------------------

def _sustituye(ruta: Path, viejo: str, nuevo: str) -> None:
    texto = ruta.read_text(encoding="utf-8")
    if viejo not in texto:
        raise SystemExit(f"MUTACION IMPOSIBLE: no se encuentra el ancla en {ruta.name}")
    ruta.write_text(texto.replace(viejo, nuevo, 1), encoding="utf-8")


PUSH_CI = "  push:\n    branches:\n      - '**'\n"
PR_CI = "  pull_request:\n    branches: [ main ]\n"


def m_paths_ignore_push() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    paths-ignore: ['**']\n")


def m_paths_ignore_pr() -> None:
    _sustituye(CI, PR_CI, "  pull_request:\n    branches: [ main ]\n    paths-ignore: ['**']\n")


def m_paths_ignore_entrecomillado() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    \"paths-ignore\": ['**']\n")


def m_paths_ignore_espacio() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    paths-ignore : ['**']\n")


def m_paths_push() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    paths: ['viewer/**']\n")


def m_paths_pr() -> None:
    _sustituye(CI, PR_CI, "  pull_request:\n    branches: [ main ]\n    paths: ['viewer/**']\n")


def m_branches_ignore() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    branches-ignore: ['ops/**']\n")


def m_solo_main() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches: [ main ]\n")


def m_lista_blanca_exhaustiva() -> None:
    """Lista blanca con TODAS las ramas reales de origin de hoy, una por una.

    Es el caso que la version-lista-blanca del gate aprobaba: cubre el 100% de
    lo que existe. Debe seguir en ROJO, porque no cubre lo que no existe aun.
    """
    ramas = ramas_de_origin()
    if not ramas:
        raise SystemExit("MUTACION IMPOSIBLE: no hay ramas de origin locales")
    lineas = "".join(f"      - '{r}'\n" for r in ramas)
    _sustituye(CI, PUSH_CI, f"  push:\n    branches:\n{lineas}")
    print(f"    (lista blanca con {len(ramas)} ramas reales de origin)")


def m_borra_workflow() -> None:
    SUPPLY.unlink()


def m_job_cero_tests() -> None:
    """Quita la guardia anti-cero de un job: vuelve a poder salir verde con 0."""
    texto = CI.read_text(encoding="utf-8")
    ancla = "      - name: Run viewer tests"
    i = texto.index(ancla)
    j = texto.index("\n  test-neo4j-authz:", i)
    nuevo = (
        "      - name: Run viewer tests\n"
        "        env:\n"
        "          S9K_ALLOW_REAL_INGEST: \"\"\n"
        "        run: |\n"
        "          python -m pytest viewer/tests/ -v --tb=short --no-header\n"
    )
    CI.write_text(texto[:i] + nuevo + texto[j:], encoding="utf-8")


def m_skip_critico() -> None:
    """Un test nuevo que se auto-omite por falta de Chromium, sin job que lo cubra."""
    destino = REPO / "tests" / "e2e" / "conftest.py"
    destino.write_text(
        destino.read_text(encoding="utf-8")
        + '\n\nimport pytest as _p\n'
        + '_p.importorskip("playwright.sync_api")\n',
        encoding="utf-8",
    )


CASOS = [
    ("estado correcto", None, VERDE),
    ("`paths-ignore` bajo `push`", m_paths_ignore_push, ROJO),
    ("`paths-ignore` bajo `pull_request`", m_paths_ignore_pr, ROJO),
    ('`"paths-ignore"` entrecomillado', m_paths_ignore_entrecomillado, ROJO),
    ("`paths-ignore :` con espacio antes de los dos puntos", m_paths_ignore_espacio, ROJO),
    ("`paths:` bajo `push`", m_paths_push, ROJO),
    ("`paths:` bajo `pull_request`", m_paths_pr, ROJO),
    ("`branches-ignore`", m_branches_ignore, ROJO),
    ("politica reducida a `branches: [main]`", m_solo_main, ROJO),
    ("lista blanca EXHAUSTIVA con todas las ramas reales de origin", m_lista_blanca_exhaustiva, ROJO),
    ("workflow vigilado borrado (`supply-chain.yml`)", m_borra_workflow, ROJO),
    ("job que puede ejecutar 0 tests", m_job_cero_tests, ROJO),
    ("test que se auto-omite por falta de Chromium", m_skip_critico, ROJO),
    ("restaurado", None, VERDE),
]


def main() -> int:
    respaldo = Path(tempfile.mkdtemp(prefix="calibra-gate-"))
    for f in TOCABLES:
        shutil.copy2(f, respaldo / f.name)

    filas = []
    fallos = 0
    try:
        for titulo, mutacion, esperado in CASOS:
            # Estado limpio antes de cada caso.
            for f in TOCABLES:
                shutil.copy2(respaldo / f.name, f)
            print(f"\n########## {titulo}  (esperado: {esperado})")
            if mutacion is not None:
                mutacion()
            rc, salida = ejecuta_gate()
            obtenido = VERDE if rc == 0 else ROJO
            print(salida.rstrip())
            print(f"RC={rc}  ->  {obtenido}")
            ok = obtenido == esperado
            fallos += 0 if ok else 1
            motivo = ""
            for linea in salida.splitlines():
                if linea.startswith("::error::"):
                    motivo = linea[len("::error::"):].strip().replace("|", "/")
                    motivo = motivo.split("\n")[0][:120]
                    break
            if not motivo and rc == 0:
                motivo = "sin errores"
            filas.append((titulo, esperado, rc, obtenido, "OK" if ok else "**DESVIACION**", motivo))
    finally:
        for f in TOCABLES:
            shutil.copy2(respaldo / f.name, f)
        shutil.rmtree(respaldo, ignore_errors=True)

    print("\n\n===== TABLA DE CALIBRACION =====\n")
    print("| Caso | Esperado | RC | Obtenido | Veredicto | Primer error |")
    print("|---|---|---|---|---|---|")
    for fila in filas:
        print("| {} | {} | {} | {} | {} | {} |".format(*fila))

    if fallos:
        print(f"\nCALIBRACION FALLIDA: {fallos} caso(s) no dieron el veredicto esperado")
        return 1
    print(f"\nCALIBRACION SUPERADA: {len(filas)}/{len(filas)} casos con el veredicto esperado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
