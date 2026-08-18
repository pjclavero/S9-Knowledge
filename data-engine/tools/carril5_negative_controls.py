#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controles negativos del carril 5 (V3.1): ¿medimos conducta o redacción?

Qué mide
--------
1. `text`      : reescribe SOLO el mensaje de cada excepción crítica sellada.
                 Con las pruebas nuevas debe quedar TODO VERDE.
2. `code`      : cambia SOLO el código estable de un raise (una mutación por
                 vez). Debe ponerse ROJO, y el rojo debe venir de la prueba que
                 cubre ese código (ancla única, sin rojo prestado).
3. `baseline`  : aplica la MISMA mutación de texto sobre el árbol de `aaf9695`
                 con sus pruebas originales. Debe ponerse ROJO — ése es el
                 argumento de necesidad del carril.
4. `ablation`  : devuelve una comprobación convertida a su forma antigua
                 (`match=`) y repite la mutación de código de ese mismo sitio.
                 Si sigue detectándose, el control no defendía nada.

Método
------
- Nunca se muta el árbol de trabajo: se copia `data-engine/` a un directorio de
  ejecución y se muta ahí. El árbol real se verifica por SHA-256 antes y
  después: si cambia un solo byte, el arnés aborta.
- Las mutaciones se aplican por AST (nodo `Raise` / llamada `coded`), jamás por
  búsqueda de subcadenas.
- Una mutación por ejecución, con su hash propio en el informe.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DE = REPO / "data-engine"
RUN = REPO / ".scratch_c5" / "run"

#: Ficheros de producto sellados en este carril.
SOURCES = [
    "app/knowledge_v3/ledger/assertions.py",
    "app/knowledge_v3/ledger/supersession.py",
    "app/knowledge_v3/ledger/store.py",
    "app/knowledge_v3/ledger/entries.py",
    "app/review/ingest_approved.py",
    "app/review/supersede_review.py",
]

#: Pruebas en alcance (las que sostienen garantías RC).
TESTS = [
    "app/tests/test_knowledge_v3_ledger.py",
    "app/tests/test_knowledge_v3_ledger_mutation.py",
    "app/tests/test_safe_writer.py",
    "app/tests/test_supersede_review.py",
    "app/tests/test_use_existing.py",
]

MUTATED_MESSAGE = "mensaje reescrito por el control negativo del carril 5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path, rels) -> dict:
    return {r: sha256(root / r) for r in rels}


def fresh_copy(git_ref: str | None = None) -> Path:
    if RUN.exists():
        shutil.rmtree(RUN)
    RUN.mkdir(parents=True)
    dst = RUN / "data-engine"
    shutil.copytree(DE, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    shutil.copy2(REPO / "conftest.py", RUN / "conftest.py")
    # `contracts/` se enlaza (solo lectura): el carril no lo toca y copiarlo
    # entero solo anadiria ruido a la medicion.
    (RUN / "contracts").symlink_to(REPO / "contracts", target_is_directory=True)
    if git_ref:
        for rel in SOURCES + TESTS:
            blob = subprocess.run(
                ["git", "-C", str(REPO), "show", f"{git_ref}:data-engine/{rel}"],
                capture_output=True, check=True).stdout
            (dst / rel).write_bytes(blob)
    return dst


def _offsets(raw: bytes):
    offs = [0]
    for line in raw.splitlines(keepends=True):
        offs.append(offs[-1] + len(line))
    return offs


def coded_calls(raw: bytes, path: str):
    """Devuelve los nodos `coded(Exc(...), CODE)` que envuelven un `raise`."""
    tree = ast.parse(raw.decode("utf-8"), path)
    out = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
                and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "coded"):
            out.append(n.exc)
    return out


def mutate_messages(path: Path) -> int:
    """Sustituye los argumentos del constructor de la excepción por un literal
    fijo. No toca ni el tipo ni el código: sólo la REDACCIÓN."""
    raw = path.read_bytes()
    offs = _offsets(raw)
    off = lambda ln, c: offs[ln - 1] + c
    edits = []
    for call in coded_calls(raw, str(path)):
        inner = call.args[0]
        if not isinstance(inner, ast.Call) or not inner.args:
            continue
        a0, aN = inner.args[0], inner.args[-1]
        edits.append((off(a0.lineno, a0.col_offset), off(aN.end_lineno, aN.end_col_offset)))
    out = raw
    for s, e in sorted(edits, reverse=True):
        out = out[:s] + repr(MUTATED_MESSAGE).encode() + out[e:]
    ast.parse(out.decode("utf-8"), str(path))
    path.write_bytes(out)
    return len(edits)


def mutate_messages_legacy(path: Path) -> int:
    """Igual, pero sobre el árbol de `aaf9695`, donde no hay `coded(...)`:
    se muta el mensaje de TODO `raise Exc("...")` del fichero."""
    raw = path.read_bytes()
    tree = ast.parse(raw.decode("utf-8"), str(path))
    offs = _offsets(raw)
    off = lambda ln, c: offs[ln - 1] + c
    edits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) and n.exc.args:
            a0, aN = n.exc.args[0], n.exc.args[-1]
            edits.append((off(a0.lineno, a0.col_offset), off(aN.end_lineno, aN.end_col_offset)))
    out = raw
    for s, e in sorted(edits, reverse=True):
        out = out[:s] + repr(MUTATED_MESSAGE).encode() + out[e:]
    ast.parse(out.decode("utf-8"), str(path))
    path.write_bytes(out)
    return len(edits)


def code_sites(root: Path):
    """Inventario de sitios sellados: (fichero, línea, código actual)."""
    sites = []
    for rel in SOURCES:
        p = root / rel
        raw = p.read_bytes()
        for call in coded_calls(raw, rel):
            code_node = call.args[1]
            sites.append((rel, call.lineno, ast.unparse(code_node)))
    return sites


def mutate_one_code(root: Path, rel: str, lineno: int, new_code: str) -> None:
    p = root / rel
    raw = p.read_bytes()
    offs = _offsets(raw)
    off = lambda ln, c: offs[ln - 1] + c
    target = [c for c in coded_calls(raw, rel) if c.lineno == lineno]
    assert len(target) == 1, (rel, lineno, len(target))
    node = target[0].args[1]
    s, e = off(node.lineno, node.col_offset), off(node.end_lineno, node.end_col_offset)
    out = raw[:s] + new_code.encode() + raw[e:]
    ast.parse(out.decode("utf-8"), rel)
    p.write_bytes(out)


def ablate_code_control(root: Path, code_suffix: str) -> int:
    """Quita el control NUEVO: `raises_code(T, X.CODE)` -> `pytest.raises(T)`.

    Solo en los sitios cuyo codigo coincide con `code_suffix`. Es la ablacion
    exacta: la prueba sigue existiendo y sigue exigiendo el TIPO, pero deja de
    exigir el codigo. Si aun asi el defecto se detecta, el control no defendia
    nada.
    """
    n = 0
    for rel in TESTS:
        p = root / rel
        raw = p.read_bytes()
        tree = ast.parse(raw.decode("utf-8"), rel)
        offs = _offsets(raw)
        off = lambda ln, c: offs[ln - 1] + c
        edits = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "raises_code" and len(node.args) == 2):
                if ast.unparse(node.args[1]).split(".")[-1] != code_suffix:
                    continue
                exc = raw[off(node.args[0].lineno, node.args[0].col_offset):
                          off(node.args[0].end_lineno, node.args[0].end_col_offset)].decode()
                edits.append((off(node.lineno, node.col_offset),
                              off(node.end_lineno, node.end_col_offset),
                              f"pytest.raises({exc})".encode()))
        if not edits:
            continue
        out = raw
        for s_, e_, new in sorted(edits, reverse=True):
            out = out[:s_] + new + out[e_:]
        ast.parse(out.decode("utf-8"), rel)
        p.write_bytes(out)
        n += len(edits)
    return n


def run_tests(root: Path, only: list[str] | None = None):
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--no-header", "--tb=no", "-rf", "--color=no", *(only or [t.split("app/", 1)[1] for t in TESTS])]
    r = subprocess.run(args, cwd=root / "app", capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def failing_tests(output: str) -> list[str]:
    return sorted({ln.split(" ")[1] for ln in output.splitlines()
                   if ln.startswith("FAILED") and len(ln.split(" ")) > 1})


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["text", "code", "baseline", "ablation", "all"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    before = tree_hashes(DE, SOURCES + TESTS)
    report = {"mode": args.mode, "results": []}

    if args.mode in ("text", "all"):
        root = fresh_copy()
        purge_pycache(root)
        n = sum(mutate_messages(root / rel) for rel in SOURCES)
        rc, out = run_tests(root)
        report["results"].append({
            "control": "text",
            "mutated_sites": n,
            "hashes": tree_hashes(root, SOURCES),
            "returncode": rc,
            "failed": failing_tests(out),
            "veredicto": "OK (nada rojo)" if rc == 0 else "FALLA: el texto sigue midiéndose",
            "tail": out.strip().splitlines()[-1:],
        })

    if args.mode in ("baseline", "all"):
        root = fresh_copy(git_ref="aaf9695")
        purge_pycache(root)
        n = sum(mutate_messages_legacy(root / rel) for rel in SOURCES)
        rc, out = run_tests(root)
        report["results"].append({
            "control": "baseline(aaf9695)",
            "mutated_sites": n,
            "hashes": tree_hashes(root, SOURCES),
            "returncode": rc,
            "failed": failing_tests(out),
            "veredicto": "OK (rojo esperado: antes se medía redacción)" if rc != 0
                         else "FALLA: no había nada que arreglar",
            "tail": out.strip().splitlines()[-1:],
        })

    if args.mode in ("code", "all"):
        base = fresh_copy()
        sites = code_sites(base)
        if args.limit:
            sites = sites[:args.limit]
        for rel, lineno, code in sites:
            root = fresh_copy()
            purge_pycache(root)
            mutate_one_code(root, rel, lineno, '"S9K_CODE_MUTADO_CONTROL_NEGATIVO"')
            rc, out = run_tests(root)
            report["results"].append({
                "control": "code",
                "site": f"{rel}:{lineno}",
                "code": code,
                "hash": sha256(root / rel),
                "returncode": rc,
                "failed": failing_tests(out),
                "detectado": rc != 0,
            })


    if args.mode in ("ablation", "all"):
        base = fresh_copy()
        detected = json.load(open(REPO / ".scratch_c5" / "code_report.json"))["results"]
        seen_codes = set()
        for entry in detected:
            if not entry.get("detectado"):
                continue
            suffix = entry["code"].split(".")[-1]
            if suffix in seen_codes:
                continue
            seen_codes.add(suffix)
            rel, lineno = entry["site"].rsplit(":", 1)
            root = fresh_copy()
            purge_pycache(root)
            n_abl = ablate_code_control(root, suffix)
            mutate_one_code(root, rel, int(lineno), '"S9K_CODE_MUTADO_CONTROL_NEGATIVO"')
            rc, out = run_tests(root)
            report["results"].append({
                "control": "ablation",
                "site": entry["site"],
                "code": entry["code"],
                "controles_quitados": n_abl,
                "hash_test_files": tree_hashes(root, TESTS),
                "returncode": rc,
                "failed": failing_tests(out),
                "empeora": rc == 0,
            })

    print(json.dumps(report, indent=1, ensure_ascii=False))
    after = tree_hashes(DE, SOURCES + TESTS)
    assert before == after, "EL ÁRBOL REAL CAMBIÓ durante el arnés: medición inválida"
    print("ARBOL REAL INTACTO (SHA-256 verificado antes y después)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
