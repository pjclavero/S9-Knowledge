#!/usr/bin/env python3
"""Crea y valida la estructura local mínima de un workspace S9 Knowledge.

No abre conexiones ni modifica el grafo. El nombre se conserva literalmente en
workspace.json para poder declararlo igual en PipelineConfig, GameProfile y
S9K_WRITER_WORKSPACE, las tres comprobaciones duras del código V3.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
DIRECTORIES = ("sources", "profiles", "ledger", "audit")


def validate(path: Path, expected_name: str | None = None) -> list[str]:
    errors: list[str] = []
    metadata = path / "workspace.json"
    if not path.is_dir():
        return [f"no existe el directorio: {path}"]
    if not metadata.is_file():
        errors.append(f"falta {metadata}")
    else:
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"workspace.json inválido: {exc}")
        else:
            name = data.get("workspace")
            if not isinstance(name, str) or not NAME_RE.fullmatch(name):
                errors.append("workspace.json contiene un workspace no válido")
            if name != path.name:
                errors.append(f"workspace {name!r} no coincide con el directorio {path.name!r}")
            if expected_name is not None and name != expected_name:
                errors.append(f"workspace {name!r} no coincide con el esperado {expected_name!r}")
    for dirname in DIRECTORIES:
        if not (path / dirname).is_dir():
            errors.append(f"falta directorio {dirname}/")
    return errors


def create(root: Path, name: str) -> Path:
    if not NAME_RE.fullmatch(name):
        raise ValueError("el nombre debe cumplir ^[a-z][a-z0-9_-]{0,63}$")
    target = root / name
    if target.exists():
        raise FileExistsError(f"el workspace ya existe: {target}")
    target.mkdir(parents=True)
    for dirname in DIRECTORIES:
        (target / dirname).mkdir()
    (target / "workspace.json").write_text(
        json.dumps(
            {
                "workspace": name,
                "profile_workspace_must_equal": name,
                "writer_environment": {"S9K_WRITER_WORKSPACE": name},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?", help="identificador local del workspace")
    parser.add_argument("--root", type=Path, default=Path("workspaces"))
    parser.add_argument("--validate", type=Path, metavar="PATH")
    args = parser.parse_args(argv)
    if args.validate is not None:
        errors = validate(args.validate, args.name)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(f"WORKSPACE_OK {args.validate}")
        return 0
    if not args.name:
        parser.error("name es obligatorio al crear")
    try:
        target = create(args.root, args.name)
    except (ValueError, FileExistsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    errors = validate(target, args.name)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"WORKSPACE_CREATED {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
