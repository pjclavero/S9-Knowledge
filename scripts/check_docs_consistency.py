#!/usr/bin/env python3
"""
check_docs_consistency.py — valida que la documentación no contradiga el estado
real del proyecto.

Fuente de verdad: docs/project-status.yaml (derivado de main + tags + manifest +
CI + produccion verificada). Este script comprueba:

  1. Que la documentación clave no contenga afirmaciones OBSOLETAS conocidas
     (Basic Auth como acceso vigente, login pendiente, visor no desplegado,
     numero de tests fijo, RC1/RC5 desplegadas, timer de 5 minutos activo,
     auth DB dentro de la release, v0.2.6-B1 como estado vigente, etc.).
  2. Que el documento canónico (docs/02-current-state.md) mencione el tag y el
     commit de produccion declarados en project-status.yaml.

Los bloques históricos marcados explícitamente se ignoran: una sección cuyo
encabezado contiene "HISTORICO"/"HISTÓRICO"/"DEPRECADO" (o una línea con el
marcador `<!-- consistency:ignore -->`) no se analiza. Esto evita falsos
positivos porque una frase obsoleta aparezca dentro de una nota histórica.

Salida: rc 0 si coherente; rc 1 si hay contradicciones (las lista).
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
STATUS_YAML = REPO / "docs" / "project-status.yaml"

# Documentos que deben mantenerse coherentes con el estado real.
DOCS = [
    "README.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    "viewer/README.md",
    "docs/02-current-state.md",
]

HISTORIC_HEADING = re.compile(r"^#{1,6}\s.*(HIST[OÓ]RICO|DEPRECAD|DEPRECATED)", re.IGNORECASE)
ANY_HEADING = re.compile(r"^#{1,6}\s")
IGNORE_MARK = "<!-- consistency:ignore -->"


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# Patrones obsoletos: (id, regex_positiva, regex_de_excepcion_o_None).
# Se marca la línea si la positiva coincide y la de excepción NO (las negaciones
# como "sin basic auth", "basic auth retirada", "RC5 no desplegada" evitan el
# falso positivo). Todo sobre texto SIN acentos.
# Stems de negación (sin límites de palabra: "retirad" debe casar "retirada").
NEG_AUTH = re.compile(r"(\bsin\b|retirad|elimin|ya no|historic|deprecad|\bpropia\b|propio del)", re.IGNORECASE)
OBSOLETE = [
    ("basic-auth-vigente",
     re.compile(r"basic auth", re.IGNORECASE),
     NEG_AUTH),
    ("login-pendiente",
     re.compile(r"login (propio )?(pendiente|no implementado|sin implementar)", re.IGNORECASE),
     None),
    ("sin-login",
     re.compile(r"\b(solo basic auth|visor sin login|sin login propio)\b", re.IGNORECASE),
     re.compile(r"\bretirad|ya no\b", re.IGNORECASE)),
    ("visor-no-desplegado",
     re.compile(r"visor (web )?no desplegado|visor prototipo|solo mock", re.IGNORECASE),
     None),
    ("tests-fijos",
     re.compile(r"\b(220|249)\s*/?\s*(220|249)?\s*tests\b|\b(220|249) (tests|recopilad)", re.IGNORECASE),
     None),
    ("estado-v026b1",
     re.compile(r"v0\.2\.6-b1\b.*(actual|vigente|estado)", re.IGNORECASE),
     None),
    ("rc1-desplegada",
     re.compile(r"\brc1\b.*(desplegad|activa en produccion)", re.IGNORECASE),
     re.compile(r"no desplegad|nunca|candidata|abort", re.IGNORECASE)),
    ("rc5-desplegada",
     re.compile(r"\brc5\b(?!\.1).*(desplegad|activa en produccion)", re.IGNORECASE),
     re.compile(r"no desplegad|nunca|candidata|abort", re.IGNORECASE)),
    ("timer-5min-activo",
     re.compile(r"timer de 5\s*min(utos)?\s*activ|onunitactivesec=5min.*activ", re.IGNORECASE),
     None),
    ("authdb-en-release",
     re.compile(r"auth\.?db (dentro|en el interior) de (la )?release", re.IGNORECASE),
     None),
    ("rc4-activa",
     re.compile(r"\brc4\b.*(activa en produccion|es la release activa|current\s*->\s*91bdc51)", re.IGNORECASE),
     re.compile(r"previous|rollback|anterior", re.IGNORECASE)),
]


def scan_doc(path: Path) -> list[str]:
    findings: list[str] = []
    if not path.exists():
        return findings
    in_historic = False
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if ANY_HEADING.match(raw):
            in_historic = bool(HISTORIC_HEADING.match(raw))
        if in_historic or IGNORE_MARK in raw:
            continue
        text = _strip_accents(raw)
        for oid, rx, unless in OBSOLETE:
            if rx.search(text) and not (unless and unless.search(text)):
                try:
                    label = path.relative_to(REPO)
                except ValueError:
                    label = path
                findings.append(f"{label}:{n}: [{oid}] {raw.strip()[:100]}")
    return findings


def check_canonical(status: dict) -> list[str]:
    findings: list[str] = []
    canonical = REPO / "docs" / "02-current-state.md"
    if not canonical.exists():
        return [f"falta el documento canónico {canonical.relative_to(REPO)}"]
    body = canonical.read_text(encoding="utf-8")
    for key in ("production_tag", "production_commit"):
        val = str(status.get(key, "")).strip()
        if val and val not in body:
            findings.append(
                f"docs/02-current-state.md no menciona {key}={val} (project-status.yaml)"
            )
    return findings


def main() -> int:
    if not STATUS_YAML.exists():
        print(f"ERROR: falta {STATUS_YAML.relative_to(REPO)}", file=sys.stderr)
        return 1
    status = yaml.safe_load(STATUS_YAML.read_text(encoding="utf-8"))

    findings: list[str] = []
    for rel in DOCS:
        findings += scan_doc(REPO / rel)
    findings += check_canonical(status)

    if findings:
        print("DOCUMENTACION NO COHERENTE — contradicciones detectadas:")
        for f in findings:
            print(f"  - {f}")
        print(f"\nTotal: {len(findings)} contradiccion(es).")
        return 1

    print("DOCUMENTACION COHERENTE: sin contradicciones conocidas.")
    print(f"  produccion: {status.get('production_tag')} "
          f"({str(status.get('production_commit'))[:12]}) "
          f"release_id={status.get('production_release_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
