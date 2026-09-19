#!/usr/bin/env python3
"""CORTE 1 — inventario de concesiones de partida. SOLO LECTURA.

Lista las filas de `partida_access` que NO corresponden a un `(workspace,
partida)` alcanzable por este despliegue, para que un operador las vea antes de
decidir nada.

**Esta herramienta NO BORRA, NO MIGRA Y NO "LIMPIA" NADA.** Abre la base en modo
sólo lectura (`file:...?mode=ro`, URI) para que eso no dependa de la buena
voluntad del código: si alguien añadiera un `DELETE`, SQLite lo rechazaría.

## Qué cuenta como "no corresponde"

El arreglo del CORTE 1 hace que la existencia de una partida sea el par
`(workspace, partida_id)`, y que el único workspace alcanzable sea el efectivo
del despliegue (`S9K_DEFAULT_WORKSPACE`). De ahí dos clases:

  HUERFANA_DE_WORKSPACE  la fila vive en un workspace que no es el efectivo.
                         Antes del arreglo estas filas eran las peligrosas: le
                         daban existencia a su `partida_id` en el workspace
                         REAL. Después del arreglo ya no pueden hacerlo, pero
                         siguen siendo concesiones que el panel muestra como
                         vivas y que no conceden nada a nadie.

  SOLITARIA              la fila vive en el workspace efectivo y es la ÚNICA
                         concesión de esa partida. No es un defecto: es la
                         primera concesión de una partida legítima. Se lista
                         porque, sin censo, es también la forma que tiene una
                         ERRATA: revocarla haría desaparecer la partida.

## Lo que este inventario NO puede decir

No hay censo de partidas en este producto (ver `app/authz/existencia.py`), así
que **es imposible afirmar que un `partida_id` del workspace efectivo sea
inventado**. Contrastarlo contra las carpetas `<juego>/partidas/<partida>/` de la
bóveda es un trabajo manual del operador, y esta herramienta no lo hace.

Uso:
    python3 scripts/inventario_concesiones_partida.py --db ruta/auth.db \\
        [--workspace juego:real]

Si no se pasa `--workspace`, se toma de `S9K_DEFAULT_WORKSPACE` (o del default
de `app.config`). Salida por stdout, legible y estable. Código de salida 0
siempre que el inventario se pueda producir: es un diagnóstico, no una puerta.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path


def _conectar_solo_lectura(db: Path) -> sqlite3.Connection:
    if not db.exists():
        raise SystemExit(f"ERROR: no existe la base {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _workspace_efectivo(explicito: str | None) -> str:
    if explicito and explicito.strip():
        return explicito.strip()
    del_entorno = os.environ.get("S9K_DEFAULT_WORKSPACE", "")
    if del_entorno.strip():
        return del_entorno.strip()
    return "leyenda"  # el default declarado en app/config.py


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path, help="ruta a auth.db")
    ap.add_argument("--workspace", default=None,
                    help="workspace efectivo (por defecto: S9K_DEFAULT_WORKSPACE)")
    args = ap.parse_args(argv)

    ws = _workspace_efectivo(args.workspace)
    conn = _conectar_solo_lectura(args.db)
    try:
        filas = conn.execute(
            "SELECT id, user_id, workspace, partida_id, granted_by, granted_at "
            "FROM partida_access ORDER BY workspace, partida_id, id"
        ).fetchall()
        usuarios = {
            r["id"]: r["username"]
            for r in conn.execute("SELECT id, username FROM users").fetchall()
        }
    finally:
        conn.close()

    por_partida_efectiva: Counter[str] = Counter(
        r["partida_id"] for r in filas if r["workspace"] == ws
    )
    huerfanas = [r for r in filas if r["workspace"] != ws]
    solitarias = [
        r for r in filas
        if r["workspace"] == ws and por_partida_efectiva[r["partida_id"]] == 1
    ]

    print("INVENTARIO DE CONCESIONES DE PARTIDA — solo lectura, no se borra nada")
    print(f"  base            : {args.db}")
    print(f"  workspace efect.: {ws}")
    print(f"  filas totales   : {len(filas)}")
    print(f"  workspaces vistos: "
          f"{sorted({r['workspace'] for r in filas}) or '—'}")
    print()

    def _volcar(titulo: str, rows: list[sqlite3.Row], nota: str) -> None:
        print(f"[{titulo}] {len(rows)}")
        print(f"  {nota}")
        for r in rows:
            usuario = usuarios.get(r["user_id"], f"user_id={r['user_id']}")
            print(f"  - id={r['id']} usuario={usuario} "
                  f"workspace={r['workspace']!r} partida={r['partida_id']!r} "
                  f"concedido_por={r['granted_by']!r} el {r['granted_at']}")
        if not rows:
            print("  (ninguna)")
        print()

    _volcar(
        "HUERFANA_DE_WORKSPACE", huerfanas,
        "Workspace distinto del efectivo: ningún consumidor puede alcanzarlas. "
        "El panel las muestra como vivas y no conceden nada. NO se borran aquí.",
    )
    _volcar(
        "SOLITARIA", solitarias,
        "Única concesión de esa partida en el workspace efectivo. Sin censo de "
        "partidas, esta es la forma que tiene tanto una partida nueva legítima "
        "como una ERRATA. Revísalas contra las carpetas de la bóveda.",
    )

    print("EFECTO DEL ARREGLO SOBRE LO YA PERSISTIDO")
    if huerfanas:
        print(f"  {len(huerfanas)} concesión(es) dejan de dar existencia a su "
              f"partida_id en {ws!r}. Ya no la daban legítimamente: era el "
              f"defecto. No dejan de conceder acceso a nadie, porque en un "
              f"workspace inalcanzable nunca concedieron nada.")
    else:
        print("  Ninguna. Todas las concesiones viven en el workspace efectivo: "
              "el arreglo no invalida ninguna concesión existente.")
    print("  Ninguna fila ha sido modificada ni borrada por esta herramienta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
