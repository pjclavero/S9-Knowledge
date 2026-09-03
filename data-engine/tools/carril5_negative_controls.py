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
    "app/tests/test_carril5_anclas_rc.py",
]

MUTATED_MESSAGE = "mensaje reescrito por el control negativo del carril 5"

#: Ficheros que NO se pueden recolectar dentro del arbol copiado del arnes
#: (buscan runners congelados y datos por ruta absoluta del repo real). Se
#: excluyen SOLO en el modo `--full`, y el `baseline_sin_mutar` demuestra que su
#: exclusion no depende de ninguna mutacion. Ninguno toca las guardas medidas.
SANDBOX_INCOLECTABLES = [
    "test_agreement_shadow.py",
    "test_gate4_b1_ocr_adversarial.py",
    "test_gate4_b1_ocr_lane.py",
    "test_gate4_b1_ocr_real.py",
    "test_gate4_b3_adversarial.py",
    "test_gate4_b3_nvidia_shadow.py",
    "test_gate4_b5_final.py",
    "test_gate6_measure_b1.py",
]

#: Las OCHO guardas de garantía RC que la revisión encontró INDEFENSAS: se podía
#: neutralizar el `raise` (envolviéndolo en `if False:`, que preserva el censo AST
#: de sitios sellados) y los 5255 tests seguían verdes. Cada una lleva ahora su
#: ancla de conducta en `app/tests/test_carril5_anclas_rc.py`, y el modo `guards`
#: mide que neutralizarla pone roja ESA prueba y sólo ésa.
#:
#: Las OCHO estaban verdes allí, `SUPERSESSION_CYCLE` incluida: allí no había
#: ninguna prueba que entrase en el bucle. Que hoy esa mutación CUELGUE en vez
#: de dar verde es consecuencia de haberla anclado, no un cuelgue que estuviera
#: escondido antes. Ver `_plazo` en el fichero de anclas.
GUARDS = [
    ("app/knowledge_v3/ledger/assertions.py", "CHAIN_SEQ_GAP"),
    ("app/knowledge_v3/ledger/assertions.py", "SUPERSEDE_TARGET_EXISTS"),
    ("app/knowledge_v3/ledger/supersession.py", "VALIDITY_INVERTED"),
    ("app/knowledge_v3/ledger/supersession.py", "SUPERSESSION_CYCLE"),
    ("app/review/ingest_approved.py", "WRITE_PROVENANCE_INCOMPLETE"),
    ("app/review/supersede_review.py", "SOURCE_MODIFIED_DURING"),
    ("app/review/supersede_review.py", "WRITTEN_SHA_MISMATCH"),
    ("app/review/supersede_review.py", "SOURCE_MODIFIED_AFTER"),
]


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


def neutralize_guard(root: Path, rel: str, code_suffix: str) -> tuple[int, str]:
    """Neutraliza la guarda cuyo `coded(..., X.<code_suffix>)` la sella.

    Reproduce EXACTAMENTE la mutación del revisor: envuelve el `raise` en
    `if False:`. Se elige esa forma, y no borrar la línea, porque preserva el
    censo AST de sitios sellados: la guarda desaparece de la conducta sin que la
    prueba de censo (`test_el_numero_de_raises_sellados_es_el_declarado`) se
    entere. Ése es justo el escenario que las anclas deben detectar.

    Devuelve `(linea, sha256 del fichero mutado)`.
    """
    p = root / rel
    raw = p.read_bytes()
    tree = ast.parse(raw.decode("utf-8"), rel)
    targets = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
        and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "coded"
        and len(n.exc.args) == 2
        and ast.unparse(n.exc.args[1]).split(".")[-1] == code_suffix
    ]
    assert len(targets) == 1, f"{rel}: {code_suffix} aparece {len(targets)} veces"
    node = targets[0]
    lines = raw.decode("utf-8").splitlines(keepends=True)
    first, last = node.lineno - 1, node.end_lineno  # [first, last)
    indent = " " * node.col_offset
    block = [indent + "if False:\n"] + ["    " + ln for ln in lines[first:last]]
    out = "".join(lines[:first] + block + lines[last:])
    ast.parse(out, rel)
    p.write_bytes(out.encode("utf-8"))
    return node.lineno, sha256(p)


def restore(root: Path, rels) -> None:
    """Devuelve `rels` a su contenido real. Sustituye a recopiar el arbol entero:
    la copia completa de `data-engine` tarda minutos en este disco y el arnes se
    volvia inejecutable. El contenido restaurado se verifica por SHA-256 contra
    el arbol real, asi que la reversion es demostrable, no confiada."""
    for rel in rels:
        shutil.copyfile(DE / rel, root / rel)
        assert sha256(root / rel) == sha256(DE / rel), f"reversion fallida en {rel}"


def run_tests(root: Path, only: list[str] | None = None, timeout: int | None = None):
    """Devuelve `(returncode, salida)`. `returncode` es -1 si expiro el plazo.

    El plazo existe por un hallazgo real, contado exacto: con el ancla de ciclo
    presente, neutralizar `SUPERSESSION_CYCLE` no deja la suite verde, la deja
    COLGADA --sin esa guarda `chain_from` recorre el ciclo para siempre--. Ojo
    al matiz: en el arbol de la revision, SIN ese ancla, la misma mutacion daba
    un verde limpio, porque ninguna prueba entraba en el bucle. Sin timeout el
    arnes se queda esperando y un colgado se confunde con "sigue corriendo"."""
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--no-header", "--tb=no", "-rf", "--color=no", *(only or [t.split("app/", 1)[1] for t in TESTS])]
    try:
        r = subprocess.run(args, cwd=root / "app", capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired as e:
        salida = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -1, salida + f"\nPLAZO AGOTADO ({timeout}s): la suite no termina."
    return r.returncode, r.stdout + r.stderr


def failing_tests(output: str) -> list[str]:
    return sorted({ln.split(" ")[1] for ln in output.splitlines()
                   if ln.startswith("FAILED") and len(ln.split(" ")) > 1})


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def veredicto_guards(resultados: list) -> dict:
    """Verdicto del modo `guards`, restando el baseline.

    Por que la resta y no el recuento crudo: al correr la suite ENTERA dentro
    del arbol copiado hay ~19 rojos y ~24 errores que no dependen de ninguna
    mutacion --pruebas que buscan runners congelados, corpus y artefactos por
    ruta absoluta del repo real, y el censo de rutas, que desde una copia no
    encuentra el indice de git--. Contarlos como deteccion seria justo el falso
    hallazgo de medir contra el propio montaje. La linea `baseline_sin_mutar`
    los mide sin tocar nada, y aqui se restan.

    Un ancla es UNICA si, tras la resta, el unico rojo exclusivo es su propia
    prueba. Se admite ademas la prueba de la lista nominal
    (`test_los_sitios_sin_ancla...`): la mutacion inserta una linea y esa lista
    guarda `fichero:linea`, asi que enrojecer es la conducta correcta, no un
    rojo prestado.

    QUE CUENTA COMO "SU PROPIA PRUEBA", y por que se estrecho el criterio: una
    roja es propia SOLO si su nombre contiene el CODIGO de la guarda mutada. La
    version anterior aceptaba ademas cualquier nombre que empezara por
    `test_ancla_`. Era inocuo hoy --las 8 casan por codigo, que es el criterio
    fuerte-- pero es un rojo prestado esperando su ocasion DENTRO del propio
    veredicto: una mutacion que enrojeciera SOLO un ancla AJENA se habria
    contado como anclada. Con el criterio por codigo, ese caso sale como NO
    anclada. Tiene control negativo:
    `tests/test_carril5_exception_codes.py::test_el_veredicto_no_acepta_un_ancla_ajena`.

    La resta, ademas, falla hacia el lado seguro: si un ancla real cayese dentro
    del baseline, restarla la BORRARIA y la guarda saldria SIN ancla. No puede
    fabricar un ancla que no exista.
    """
    base = None
    for e in resultados:
        if e.get("control") == "baseline_sin_mutar":
            base = set(e["failed"])
    if base is None:
        return {"veredicto": "sin baseline: no se puede restar el montaje"}
    tolerado = "test_los_sitios_sin_ancla_estan_nombrados_uno_a_uno"
    filas, todas_ok = [], True
    for e in resultados:
        if e.get("control") != "guard_neutralizada":
            continue
        exclusivas = sorted(set(e["failed"]) - base)
        # SOLO por codigo. El prefijo `test_ancla_` NO cuenta: aceptarlo dejaba
        # que una mutacion que enrojeciera unicamente un ancla AJENA se contase
        # como anclada, o sea un rojo prestado dentro del propio veredicto.
        propias = [x for x in exclusivas if e["code"].lower() in x.lower()]
        colaterales = [x for x in exclusivas if x not in propias]
        ok = len(propias) == 1 and all(tolerado in x for x in colaterales)
        todas_ok &= ok
        filas.append({
            "code": e["code"], "site": e["site"],
            "rojas_exclusivas": exclusivas, "ancla": propias,
            "colaterales_admitidos": colaterales,
            "ancla_unica_tras_restar_baseline": ok,
        })
    return {
        "baseline_rojas_del_montaje": len(base),
        "guardas": filas,
        "veredicto": ("LAS 8 GUARDAS TIENEN ANCLA UNICA (sin rojos prestados)"
                      if todas_ok and len(filas) == 8
                      else "HAY GUARDAS SIN ANCLA UNICA"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["text", "code", "baseline", "ablation", "guards",
                                     "informe", "all"])
    ap.add_argument("--informe-de", default=None,
                    help="con `informe`: fichero JSON de una ejecucion previa de `guards`")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--full", action="store_true",
                    help="corre TODA la suite del data-engine, no sólo las de alcance: "
                         "es lo que permite afirmar 'sin rojos prestados'")
    ap.add_argument("--timeout", type=int, default=900,
                    help="plazo por ejecucion de pytest; un colgado NO es un verde")
    args = ap.parse_args()

    if args.mode == "informe":
        previo = json.load(open(args.informe_de))
        print(json.dumps(veredicto_guards(previo["results"]), indent=1, ensure_ascii=False))
        return 0

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


    if args.mode in ("guards", "all"):
        # `--full` corre TODA la suite del data-engine. Ocho ficheros no se
        # pueden RECOLECTAR dentro del arbol copiado: buscan runners congelados
        # y datos por ruta absoluta del repo real. Eso no lo causa ninguna
        # mutacion --se demuestra con la linea `baseline` de mas abajo, sin
        # mutar-- y sin excluirlos pytest devuelve 2 (error de recoleccion), que
        # se confundiria con "la mutacion se detecto". Es exactamente el falso
        # hallazgo de medir contra el propio montaje.
        scope = None
        if args.full:
            scope = ["tests"] + [f"--ignore=tests/{f}" for f in SANDBOX_INCOLECTABLES]
            root0 = fresh_copy()
            purge_pycache(root0)
            rc0, out0 = run_tests(root0, only=scope, timeout=args.timeout)
            report["results"].append({
                "control": "baseline_sin_mutar",
                "alcance": "suite completa del data-engine (menos incolectables)",
                "returncode": rc0,
                "failed": failing_tests(out0),
                "tail": out0.strip().splitlines()[-1:],
                "veredicto": "OK (verde de partida)" if rc0 == 0 else "ARNES INVALIDO",
            })
        # UNA sola copia del arbol, y entre mutaciones se restauran SOLO los
        # ficheros de producto (6). Recopiar 25 MB por mutacion tardaba minutos.
        root = root0 if args.full else fresh_copy()
        for rel, code_suffix in GUARDS:
            restore(root, SOURCES)
            purge_pycache(root)
            lineno, h = neutralize_guard(root, rel, code_suffix)
            rc, out = run_tests(root, only=scope, timeout=args.timeout)
            failed = failing_tests(out)
            report["results"].append({
                "control": "guard_neutralizada",
                "site": f"{rel}:{lineno}",
                "code": code_suffix,
                "mutacion": "raise envuelto en `if False:` (el censo AST no se entera)",
                "hash_mutado": h,
                "alcance": "suite completa del data-engine" if args.full else "pruebas en alcance",
                "returncode": rc,
                "failed": failed,
                "detectado": rc != 0,
                "como": ("colgado: la guarda era lo unico que acotaba el bucle"
                         if rc == -1 else "rojo" if rc != 0 else "NADA: guarda indefensa"),
                "ancla_unica": len(failed) == 1,
            })
        restore(root, SOURCES)
        if args.full:
            report["veredicto_guards"] = veredicto_guards(report["results"])

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
