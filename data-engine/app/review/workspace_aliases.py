# -*- coding: utf-8 -*-
"""Glosario de alias por workspace (Prioridad 2.1).

Permite mapear alias de campaña ("La Cazadora" -> "Kakita Asuka") a nombres
canónicos, por workspace. Los alias de un workspace NO se aplican en otro.
Solo se usan los alias `reviewed=true`.

Formato del fichero `data-engine/config/aliases/<workspace>.json`:
{
  "schema_version": "1.0",
  "workspace": "leyenda",
  "aliases": [
    {"alias": "La Cazadora", "canonical": "Kakita Asuka", "type": "Character",
     "confidence": 0.9, "source": "campaign", "reviewed": true}
  ]
}
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional


def _aliases_path(repo_root: Path, workspace: str) -> Path:
    return repo_root / "data-engine" / "config" / "aliases" / f"{workspace}.json"


def load_alias_records(repo_root: Path, workspace: str) -> list[dict]:
    """Lista de registros de alias `reviewed=true` del workspace. [] si no hay."""
    p = _aliases_path(repo_root, workspace)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    # aislamiento: el fichero debe declarar su propio workspace
    if data.get("workspace") not in (None, workspace):
        return []
    out = []
    for a in data.get("aliases", []):
        if not a.get("reviewed", False):
            continue
        if a.get("alias") and a.get("canonical"):
            out.append(a)
    return out


def load_workspace_aliases(repo_root: Path, workspace: str) -> dict:
    """Devuelve {alias: canonical} para el workspace (solo reviewed=true)."""
    return {a["alias"]: a["canonical"] for a in load_alias_records(repo_root, workspace)}
