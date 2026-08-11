#!/usr/bin/env python3
"""Versiones de esquema DECLARADAS POR EL CÓDIGO de una release.

Existe por un defecto real de este repositorio: el manifiesto de release
llevaba la línea

    "schema_versions": {"auth_db": 1, "job_store": 1}

como literal escrito a mano en `deploy/scripts/lib.sh`, mientras el código
llevaba años en `SCHEMA_VERSION = 3` (`viewer/app/auth/db.py`). El manifiesto
mentía sobre su propio esquema y nadie se enteraba, porque el verificador sólo
comprobaba que la clave existiese (`schema_versions_present`, no crítica).

Aquí la versión se EXTRAE del código de la propia release, de modo que
declarado y real no pueden divergir: no hay dos sitios que mantener.

Se lee el fuente en vez de importarlo a propósito: este script corre sobre el
directorio de release, sin su venv ni sus dependencias instaladas, y no debe
ejecutar código de la release para producir un manifiesto.

Uso:
    python3 schema_versions.py <release_dir>      # imprime JSON
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

#: Componente -> (fichero relativo a la raíz de la release, nombre de constante).
COMPONENT_SOURCES = {
    "auth_db": ("viewer/app/auth/db.py", "SCHEMA_VERSION"),
    "job_store": ("data-engine/app/jobs/job_store.py", "SCHEMA_VERSION"),
}

#: Componente -> (fichero, constante mínima, constante máxima) del rango
#: soportado. El rango es lo que decide si un proceso arranca o se niega.
COMPONENT_RANGES = {
    "auth_db": (
        "viewer/app/auth/schema_compat.py",
        "MIN_SUPPORTED_SCHEMA",
        "MAX_SUPPORTED_SCHEMA",
    ),
}


class SchemaDeclarationError(RuntimeError):
    """No se pudo determinar una versión declarada: no se inventa un valor."""


def _read_int_constant(path: Path, name: str) -> int:
    if not path.exists():
        raise SchemaDeclarationError(
            f"no existe '{path}': no se puede determinar {name}. "
            f"Un manifiesto sin versión real es peor que no tener manifiesto."
        )
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    if match is None:
        raise SchemaDeclarationError(
            f"'{path}' no declara un entero literal en {name}. "
            f"El manifiesto no puede adivinarlo."
        )
    return int(match.group(1))


def declared_versions(release_dir: Path) -> dict:
    """Versiones de esquema que el código de esta release declara."""
    out = {}
    for component, (rel, const) in COMPONENT_SOURCES.items():
        out[component] = _read_int_constant(release_dir / rel, const)
    return out


def supported_ranges(release_dir: Path) -> dict:
    """Rango [min, max] de esquema que cada componente acepta al arrancar."""
    out = {}
    for component, (rel, min_name, max_name) in COMPONENT_RANGES.items():
        path = release_dir / rel
        lo = _read_int_constant(path, min_name)
        hi_text = (release_dir / rel).read_text(encoding="utf-8")
        # MAX_SUPPORTED_SCHEMA = SCHEMA_VERSION (alias), no un literal: se
        # resuelve al valor declarado del componente.
        if re.search(rf"^{re.escape(max_name)}\s*=\s*SCHEMA_VERSION\s*$",
                     hi_text, re.MULTILINE):
            hi = declared_versions(release_dir)[component]
        else:
            hi = _read_int_constant(path, max_name)
        if lo > hi:
            raise SchemaDeclarationError(
                f"{component}: rango invertido min={lo} max={hi}"
            )
        out[component] = {"min": lo, "max": hi}
    return out


def manifest_block(release_dir: Path) -> dict:
    versions = declared_versions(release_dir)
    ranges = supported_ranges(release_dir)
    for component, rng in ranges.items():
        declared = versions[component]
        if not (rng["min"] <= declared <= rng["max"]):
            raise SchemaDeclarationError(
                f"{component}: la versión declarada v{declared} queda fuera de "
                f"su propio rango soportado v{rng['min']}..v{rng['max']}"
            )
    return {"schema_versions": versions, "schema_supported_ranges": ranges}


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(json.dumps(manifest_block(Path(argv[1])), sort_keys=True))
    except SchemaDeclarationError as exc:
        print(f"ERROR schema_versions: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
