#!/usr/bin/env python3
"""Migracion M5b de metadatos de visibilidad sobre el grafo de produccion.

ALCANCE, y es un limite duro, no una recomendacion: este script solo escribe
`visibility` y `visibility_source`. No borra, no fusiona, no toca identidad,
predicados, temporalidad, procedencia ni assertions. Cualquier objeto que ya
tenga un nivel valido se deja EXACTAMENTE como esta: la migracion nunca amplia
ni recorta lo ya declarado.

Se ejecuta en dos actos separados a proposito:

    1. --dry-run   calcula el plan completo, no escribe nada, y lo firma.
    2. --apply     aplica EXACTAMENTE ese plan firmado, sin recalcular.

La separacion es el punto de todo el diseno. Si el apply recalculara sobre la
marcha, lo revisado y lo ejecutado serian dos cosas distintas y el hash no
significaria nada: entre el dry-run y el apply el grafo podria haber cambiado.
Por eso el apply vuelve a leer el estado, lo compara con el que el plan dio por
supuesto, y ABORTA si algo se movio. Un plan obsoleto se rehace, no se fuerza.

Uso:
    migrar_visibilidad.py --dry-run  --out plan.json
    migrar_visibilidad.py --apply    --plan plan.json [--confirmar]
    migrar_visibilidad.py --verificar

Requiere NEO4J_PASSWORD en el entorno. Habla con la base por `docker exec` +
`cypher-shell`, igual que el resto de utillaje de este repositorio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from typing import Any

# El orden de restriccion es UNA sola fuente, compartida con el visor. Si aqui
# se copiara a mano, un cambio en el vocabulario dejaria migrador y motor
# discrepando en silencio, que es la peor forma de fallar.
_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RAIZ, "viewer"))

from app.policies.visibility_migration import (  # noqa: E402
    FALLBACK,
    RESTRICTIVENESS,
    normalize_level,
)

CONTENEDOR = os.environ.get("NEO4J_CONTAINER", "neo4j-knowledge")
USUARIO = os.environ.get("NEO4J_USER", "neo4j")
SEPARADOR = "\x1f"

# --- lectura ---------------------------------------------------------------
# Solo `elementId`, etiquetas/tipo y el nivel actual. Nada de contenido: este
# script no necesita leer los datos del grafo para hacer su trabajo, y no
# leerlos es tambien lo que impide que acaben en un informe o en un registro.
Q_NODOS = f"""
MATCH (n)
RETURN elementId(n) + '{SEPARADOR}'
     + coalesce(head(labels(n)), '') + '{SEPARADOR}'
     + coalesce(toString(n.visibility), '') AS fila
ORDER BY fila
"""

Q_RELACIONES = f"""
MATCH (a)-[r]->(b)
RETURN elementId(r) + '{SEPARADOR}'
     + type(r) + '{SEPARADOR}'
     + coalesce(toString(r.visibility), '') + '{SEPARADOR}'
     + coalesce(toString(a.visibility), '') + '{SEPARADOR}'
     + coalesce(toString(b.visibility), '') AS fila
ORDER BY fila
"""

Q_CONTEOS = """
MATCH (n) WITH count(n) AS nodos
MATCH ()-[r]->() RETURN nodos, count(r) AS relaciones
"""


def cypher(consulta: str, escribe: bool = False) -> list[str]:
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("ERROR: falta NEO4J_PASSWORD en el entorno")
    cmd = [
        "docker", "exec", "-i", CONTENEDOR,
        "cypher-shell", "-u", USUARIO, "-p", password,
        "--format", "plain",
    ]
    if not escribe:
        # Barrera real, no confianza: aunque el script tuviera un error y
        # enviara una escritura durante el dry-run, la sesion la rechaza.
        cmd += ["--access-mode", "read"]
    r = subprocess.run(cmd, input=consulta, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR cypher ({r.returncode}): {r.stderr.strip()[:400]}")
    lineas = [l.strip().strip('"') for l in r.stdout.splitlines() if l.strip()]
    return lineas[1:] if lineas else []  # descarta la cabecera


def leer_estado() -> dict[str, Any]:
    nodos, relaciones = [], []
    for fila in cypher(Q_NODOS):
        eid, etiqueta, vis = fila.split(SEPARADOR)
        nodos.append({"id": eid, "etiqueta": etiqueta, "actual": vis})
    for fila in cypher(Q_RELACIONES):
        eid, tipo, vis, va, vb = fila.split(SEPARADOR)
        relaciones.append(
            {"id": eid, "tipo": tipo, "actual": vis, "origen": va, "destino": vb}
        )
    return {"nodos": nodos, "relaciones": relaciones}


# --- plan ------------------------------------------------------------------
def _nivel_relacion(origen: str, destino: str) -> tuple[str, str]:
    """Nivel heredado por una relacion, y el motivo, para el informe."""
    rangos = []
    for extremo in (origen, destino):
        nivel = normalize_level(extremo)
        # Un extremo ilegible NO se ignora: cuenta como el mas restrictivo.
        # Ignorarlo dejaria la arista mas visible que el nodo que toca.
        rangos.append(RESTRICTIVENESS[FALLBACK] if nivel is None else RESTRICTIVENESS[nivel])
    peor = max(rangos)
    nivel = next(k for k, v in RESTRICTIVENESS.items() if v == peor)
    motivo = "heredado_extremo_mas_restrictivo"
    if normalize_level(origen) is None or normalize_level(destino) is None:
        motivo = "extremo_ilegible_o_ausente_fallback"
    return nivel, motivo


def construir_plan(estado: dict[str, Any]) -> dict[str, Any]:
    acciones: list[dict[str, str]] = []
    errores: list[dict[str, str]] = []

    for n in estado["nodos"]:
        actual = normalize_level(n["actual"])
        if actual is not None:
            continue  # ya declarado: intocable
        acciones.append({
            "clase": "nodo", "id": n["id"], "etiqueta": n["etiqueta"],
            "antes": n["actual"] or "<ausente>", "despues": FALLBACK,
            "motivo": "sin_nivel_deducible_fallback",
            "fuente": "migration_fail_closed",
        })

    for r in estado["relaciones"]:
        actual = normalize_level(r["actual"])
        if actual is not None:
            continue
        nivel, motivo = _nivel_relacion(r["origen"], r["destino"])
        acciones.append({
            "clase": "relacion", "id": r["id"], "etiqueta": r["tipo"],
            "antes": r["actual"] or "<ausente>", "despues": nivel,
            "motivo": motivo, "fuente": "migration_inherited",
        })

    # Invariante de monotonia, comprobado SOBRE EL PLAN y no solo en pruebas:
    # ninguna relacion puede quedar menos restringida que sus extremos, contando
    # ya el nivel que esos extremos tendran DESPUES de aplicar el plan.
    planeado = {a["id"]: a["despues"] for a in acciones}
    for r in estado["relaciones"]:
        nivel = planeado.get(r["id"]) or normalize_level(r["actual"])
        if nivel is None:
            errores.append({"id": r["id"], "motivo": "relacion_sin_nivel_resultante"})
            continue
        for extremo in ("origen", "destino"):
            ext = normalize_level(r[extremo]) or FALLBACK
            if RESTRICTIVENESS[nivel] < RESTRICTIVENESS[ext]:
                errores.append({
                    "id": r["id"],
                    "motivo": f"monotonia_violada: {nivel} < {ext} ({extremo})",
                })

    plan = {
        "version": 1,
        "alcance": "solo_visibility_y_visibility_source",
        "totales": {
            "nodos": len(estado["nodos"]),
            "relaciones": len(estado["relaciones"]),
            "objetos": len(estado["nodos"]) + len(estado["relaciones"]),
        },
        "acciones": sorted(acciones, key=lambda a: (a["clase"], a["id"])),
        "errores": errores,
        # Estado supuesto: el apply lo re-lee y aborta si no coincide.
        "estado_supuesto_sha256": _sha(estado),
    }
    return plan


def _sha(obj: Any) -> str:
    canonico = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def plan_sha(plan: dict[str, Any]) -> str:
    return _sha({k: v for k, v in plan.items() if k != "migration_plan_sha256"})


# --- informe ---------------------------------------------------------------
NIVELES_INFORME = ["player", "reference", "narrator", "secret", "deny"]


def informe(estado: dict[str, Any], plan: dict[str, Any]) -> str:
    def resultante(items, clave_actual="actual"):
        planeado = {a["id"]: a["despues"] for a in plan["acciones"]}
        cuenta = {n: 0 for n in NIVELES_INFORME}
        errados = 0
        for it in items:
            nivel = planeado.get(it["id"]) or normalize_level(it[clave_actual])
            if nivel in cuenta:
                cuenta[nivel] += 1
            else:
                errados += 1
        return cuenta, errados

    filas = []
    for etiqueta, items in (("Nodos", estado["nodos"]), ("Relaciones", estado["relaciones"])):
        cuenta, errados = resultante(items)
        filas.append((etiqueta, len(items), cuenta, errados))

    out = ["| Tipo | Total | " + " | ".join(NIVELES_INFORME) + " | error |",
           "|---|---:|" + "---:|" * (len(NIVELES_INFORME) + 1)]
    for etiqueta, total, cuenta, errados in filas:
        out.append(
            f"| {etiqueta} | {total} | "
            + " | ".join(str(cuenta[n]) for n in NIVELES_INFORME)
            + f" | {errados} |"
        )

    motivos: dict[str, int] = {}
    for a in plan["acciones"]:
        motivos[a["motivo"]] = motivos.get(a["motivo"], 0) + 1
    out.append("")
    out.append("Objetos a tocar por motivo:")
    for motivo, n in sorted(motivos.items()):
        out.append(f"  {motivo}: {n}")
    if not motivos:
        out.append("  (ninguno: el grafo ya esta completamente estampado)")
    out.append("")
    out.append(f"Objetos esperados : {plan['totales']['objetos']}")
    out.append(f"Objetos a modificar: {len(plan['acciones'])}")
    out.append(f"Errores           : {len(plan['errores'])}")
    for e in plan["errores"]:
        out.append(f"  ERROR {e['id']}: {e['motivo']}")
    return "\n".join(out)


# --- aplicacion ------------------------------------------------------------
def sentencias_apply(plan: dict[str, Any]) -> list[str]:
    """Una sentencia por (clase, nivel). Solo toca ids listados en el plan."""
    grupos: dict[tuple[str, str, str], list[str]] = {}
    for a in plan["acciones"]:
        grupos.setdefault((a["clase"], a["despues"], a["fuente"]), []).append(a["id"])
    sentencias = []
    for (clase, nivel, fuente), ids in sorted(grupos.items()):
        patron = "(x)" if clase == "nodo" else "()-[x]->()"
        sentencias.append(
            f"MATCH {patron} WHERE elementId(x) IN {json.dumps(sorted(ids))}\n"
            f"SET x.visibility = {json.dumps(nivel)},\n"
            f"    x.visibility_source = {json.dumps(fuente)}\n"
            f"RETURN count(x) AS tocados;"
        )
    return sentencias


def verificar() -> int:
    estado = leer_estado()
    problemas = []
    n_sin = [n for n in estado["nodos"] if normalize_level(n["actual"]) is None]
    r_sin = [r for r in estado["relaciones"] if normalize_level(r["actual"]) is None]
    if n_sin:
        problemas.append(f"nodos sin nivel valido: {len(n_sin)}")
    if r_sin:
        problemas.append(f"relaciones sin nivel valido: {len(r_sin)}")
    for r in estado["relaciones"]:
        nivel = normalize_level(r["actual"])
        if nivel is None:
            continue
        for extremo in ("origen", "destino"):
            ext = normalize_level(r[extremo]) or FALLBACK
            if RESTRICTIVENESS[nivel] < RESTRICTIVENESS[ext]:
                problemas.append(f"monotonia violada en {r['id']}: {nivel} < {ext}")

    print(f"nodos      : {len(estado['nodos'])}")
    print(f"relaciones : {len(estado['relaciones'])}")
    print(f"pendientes : {len(n_sin) + len(r_sin)}")
    for p in problemas:
        print(f"  PROBLEMA: {p}")
    print("VERIFICACION: " + ("OK" if not problemas else "FALLIDA"))
    return 0 if not problemas else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verificar", action="store_true")
    ap.add_argument("--out", default="plan-m5b.json")
    ap.add_argument("--plan")
    ap.add_argument("--confirmar", action="store_true",
                    help="sin esto, --apply se queda en enseniar lo que haria")
    args = ap.parse_args()

    if args.verificar:
        return verificar()

    if args.dry_run:
        estado = leer_estado()
        plan = construir_plan(estado)
        plan["migration_plan_sha256"] = plan_sha(plan)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print("DRY-RUN — NO SE HA ESCRITO NADA EN EL GRAFO\n")
        print(informe(estado, plan))
        print(f"\nmigration_plan_sha256: {plan['migration_plan_sha256']}")
        print(f"plan guardado en: {args.out}")
        return 1 if plan["errores"] else 0

    # --apply
    if not args.plan:
        sys.exit("ERROR: --apply exige --plan")
    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    esperado = plan.pop("migration_plan_sha256", None)
    real = plan_sha(plan)
    plan["migration_plan_sha256"] = esperado
    if esperado != real:
        sys.exit(f"ERROR: el plan esta alterado.\n  firmado: {esperado}\n  real   : {real}")
    if plan["errores"]:
        sys.exit(f"ERROR: el plan tiene {len(plan['errores'])} errores. No se aplica.")

    # El grafo pudo cambiar entre el dry-run y ahora. Aplicar un plan calculado
    # sobre otro estado seria escribir a ciegas: se aborta y se rehace el plan.
    estado = leer_estado()
    if _sha(estado) != plan["estado_supuesto_sha256"]:
        sys.exit("ERROR: el grafo ha cambiado desde el dry-run. Rehaz el plan.")

    sentencias = sentencias_apply(plan)
    if not args.confirmar:
        print("SIMULACION de --apply (falta --confirmar). Sentencias exactas:\n")
        print("\n\n".join(sentencias))
        return 0

    print(f"Aplicando plan {plan['migration_plan_sha256'][:12]} "
          f"({len(plan['acciones'])} objetos)...")
    for s in sentencias:
        for linea in cypher(s, escribe=True):
            print(f"  {linea}")
    print("\nVerificacion inmediata:")
    return verificar()


if __name__ == "__main__":
    raise SystemExit(main())
