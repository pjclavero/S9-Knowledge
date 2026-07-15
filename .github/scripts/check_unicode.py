#!/usr/bin/env python3
"""
check_unicode.py — Trojan Source / invisible Unicode detector.

Falla con exit code 1 si encuentra caracteres bidi o invisibles peligrosos
fuera de la allowlist. Diseñado para correr en CI antes de merge.

Uso:
    python3 .github/scripts/check_unicode.py [--root PATH]

Caracteres vigilados:
    U+202A  LEFT-TO-RIGHT EMBEDDING
    U+202B  RIGHT-TO-LEFT EMBEDDING
    U+202C  POP DIRECTIONAL FORMATTING
    U+202D  LEFT-TO-RIGHT OVERRIDE
    U+202E  RIGHT-TO-LEFT OVERRIDE
    U+2066  LEFT-TO-RIGHT ISOLATE
    U+2067  RIGHT-TO-LEFT ISOLATE
    U+2068  FIRST STRONG ISOLATE
    U+2069  POP DIRECTIONAL ISOLATE
    U+200B  ZERO WIDTH SPACE
    U+200C  ZERO WIDTH NON-JOINER
    U+200D  ZERO WIDTH JOINER
    U+FEFF  BYTE ORDER MARK / ZERO WIDTH NO-BREAK SPACE
"""

import argparse
import pathlib
import sys

# ---------------------------------------------------------------------------
# Caracteres peligrosos (bytes UTF-8 exactos)
# ---------------------------------------------------------------------------
DANGEROUS: dict[str, bytes] = {
    "U+202A LTR_EMBEDDING":          b"\xe2\x80\xaa",
    "U+202B RTL_EMBEDDING":          b"\xe2\x80\xab",
    "U+202C POP_DIRECTIONAL":        b"\xe2\x80\xac",
    "U+202D LTR_OVERRIDE":           b"\xe2\x80\xad",
    "U+202E RTL_OVERRIDE":           b"\xe2\x80\xae",
    "U+2066 LTR_ISOLATE":            b"\xe2\x81\xa6",
    "U+2067 RTL_ISOLATE":            b"\xe2\x81\xa7",
    "U+2068 FIRST_STRONG_ISOLATE":   b"\xe2\x81\xa8",
    "U+2069 POP_DIR_ISOLATE":        b"\xe2\x81\xa9",
    "U+200B ZERO_WIDTH_SPACE":       b"\xe2\x80\x8b",
    "U+200C ZERO_WIDTH_NON_JOINER":  b"\xe2\x80\x8c",
    "U+200D ZERO_WIDTH_JOINER":      b"\xe2\x80\x8d",
    "U+FEFF BOM":                    b"\xef\xbb\xbf",
}

# ---------------------------------------------------------------------------
# Allowlist: rutas relativas (desde la raiz del repo) permitidas.
# Añadir aqui archivos donde el caracter sea deliberado (docs de prueba, etc.)
# Ejemplo: ALLOWLIST = {"docs/trojan-source-test.md"}
# ---------------------------------------------------------------------------
ALLOWLIST: set[str] = set()

# Directorios a ignorar completamente
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox"}


def audit(root: pathlib.Path) -> list[dict]:
    findings = []

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue

        rel = str(p.relative_to(root))
        if rel in ALLOWLIST:
            continue

        try:
            data = p.read_bytes()
        except OSError:
            continue

        for char_name, pattern in DANGEROUS.items():
            if pattern not in data:
                continue
            lines = data.split(b"\n")
            for lno, line in enumerate(lines, 1):
                if pattern not in line:
                    continue
                tag = f"[{char_name}]".encode()
                clean = line.replace(pattern, tag).decode("utf-8", errors="replace")
                findings.append(
                    {
                        "file": rel,
                        "line": lno,
                        "char": char_name,
                        "context": clean[:120],
                    }
                )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path("."),
        help="Raiz del repositorio a auditar (default: directorio actual)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    findings = audit(root)

    if not findings:
        print("OK: sin caracteres Unicode peligrosos.")
        return 0

    print("ERROR: caracteres Unicode peligrosos encontrados:\n")
    for f in findings:
        print(f"  {f['file']}:{f['line']}: {f['char']}")
        print(f"    {f['context']}")
    print(
        f"\nTotal: {len(findings)} hallazgo(s) en "
        f"{len({f['file'] for f in findings})} archivo(s)."
    )
    print(
        "\nSi el caracter es legitimo (documento de prueba, fixture), "
        "añade la ruta a ALLOWLIST en .github/scripts/check_unicode.py"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
