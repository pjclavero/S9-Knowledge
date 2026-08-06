#!/usr/bin/env python3
"""PROPUESTA — NO INSTALADA. Retención de copias: 7 diarias, 4 semanales, 3 mensuales.

Reglas deliberadas:

- Solo se consideran copias **publicadas**: los directorios temporales
  (``.tmp-*``) se ignoran, nunca se borran por retención (los limpia el propio
  backup al fallar).
- Una copia solo se borra si tiene ``MANIFEST.sha256``; sin manifiesto no se
  toca, porque no se puede afirmar qué es.
- **Nunca se borra la copia más reciente**, pase lo que pase con las cuotas. Si
  la retención se configurase a cero por error, seguiría quedando una.
- Por defecto es una simulación (``--dry-run`` implícito con ``--simular``):
  borrar copias de seguridad no debe ser nunca el comportamiento accidental.
"""
from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

PATRON = re.compile(r"^(?:auto|manual)-(\d{8})-(\d{6})$")


def copias(dest: Path) -> list[tuple[datetime, Path]]:
    encontradas: list[tuple[datetime, Path]] = []
    for hijo in dest.iterdir():
        if not hijo.is_dir() or hijo.name.startswith(".tmp-"):
            continue
        m = PATRON.match(hijo.name)
        if not m:
            continue
        if not (hijo / "MANIFEST.sha256").is_file():
            continue
        cuando = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
        encontradas.append((cuando, hijo))
    return sorted(encontradas, reverse=True)


def seleccionar(items, diarias: int, semanales: int, mensuales: int) -> set[Path]:
    """Devuelve las copias a CONSERVAR.

    Una misma copia puede satisfacer varias cuotas a la vez (la del lunes puede
    ser la diaria y la semanal); se conserva una vez.
    """
    conservar: set[Path] = set()
    if not items:
        return conservar

    # La más reciente siempre se conserva, sin excepción.
    conservar.add(items[0][1])

    for cuota, clave in (
        (diarias, lambda d: d.strftime("%Y-%m-%d")),
        (semanales, lambda d: d.strftime("%G-W%V")),
        (mensuales, lambda d: d.strftime("%Y-%m")),
    ):
        vistos: set[str] = set()
        for cuando, ruta in items:
            k = clave(cuando)
            if k in vistos:
                continue
            vistos.add(k)
            if len(vistos) <= cuota:
                conservar.add(ruta)
    return conservar


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest", required=True, type=Path)
    p.add_argument("--diarias", type=int, default=7)
    p.add_argument("--semanales", type=int, default=4)
    p.add_argument("--mensuales", type=int, default=3)
    p.add_argument("--simular", action="store_true",
                   help="no borra nada; solo informa de qué se borraría")
    args = p.parse_args()

    items = copias(args.dest)
    conservar = seleccionar(items, args.diarias, args.semanales, args.mensuales)

    for cuando, ruta in items:
        if ruta in conservar:
            print(f"CONSERVA  {ruta.name}")
            continue
        if args.simular:
            print(f"BORRARIA  {ruta.name}")
        else:
            shutil.rmtree(ruta)
            print(f"BORRADA   {ruta.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
