# -*- coding: utf-8 -*-
"""Puerta 6: convierte `gate6-raw-lanes.json` en matriz, gates e informe.

Separado del runner a proposito: medir cuesta minutos y llamadas reales a dos
proveedores; analizar es instantaneo y se repite muchas veces. Mezclarlos
obligaria a volver a pagar el coste de la medida cada vez que se corrige una
tabla del informe.

Ningun umbral se ajusta aqui para que el resultado salga verde. Si un gate falla,
sale FALLA con su cifra.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CORPUS = Path("data-engine/app/knowledge_v3/benchmarks/datasets/factivity/cases.json")

#: Familias en las que un hecho del mundo POSITIVO es un fallo duro de seguridad.
NO_WORLD_FACT_FAMILIES = ("PREGUNTA", "CONTRAFACTUAL", "FICCION_EN_FICCION")

#: Familias que no deben materializar una relacion factual, pero de las que si
#: se admite una abstencion con rastro (el texto SI habla de esa relacion).
NOT_MATERIALIZED_FAMILIES = ("DESEO", "ORDEN")


def load(raw_paths: list[Path]) -> tuple[dict, dict]:
    """Funde varios ficheros crudos en uno.

    Cada carril se mide por separado —los de proveedor tardan y se lanzan
    cuando la maquina lo permite—, asi que el analisis tiene que poder juntar
    lo que exista sin exigir que todo se haya medido a la vez.

    Los carriles de proveedor van sobre una MUESTRA, no sobre el corpus entero.
    Eso se propaga: `covered_cases` de cada carril dice sobre que frases se
    midio, y el gate de acuerdo solo se calcula donde ambos carriles miraron.
    """
    merged: dict = {"gate": "6", "corpus": None, "lanes": {}}
    for path in raw_paths:
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if merged["corpus"] is None:
            merged["corpus"] = raw["corpus"]
        for name, lane in raw["lanes"].items():
            lane = dict(lane)
            lane["covered_cases"] = sorted(lane.get("rows", {}))
            merged["lanes"][name] = lane
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    if merged["corpus"] is None:
        merged["corpus"] = {
            "path": str(CORPUS),
            "split": corpus["split"],
            "provenance": corpus["provenance"],
            "cases": len(corpus["cases"]),
        }
    cases = {c["case_id"]: c for c in corpus["cases"]}
    return merged, cases


def world_positive(row: dict) -> int:
    """Hechos del mundo POSITIVOS que el carril propondria escribir."""
    return int(row.get("world_claims", 0) or 0)


def world_negative(row: dict) -> int:
    return int(row.get("negated_world_claims", 0) or 0)


NOT_MEASURED = "NOT_MEASURED"


def action_of(row: dict) -> str:
    """Accion efectiva de un carril sobre una frase.

    Es la unidad del gate de acuerdo entre carriles: los carriles PUEDEN
    discrepar en diagnosticos (uno es mas locuaz que otro), pero no en si se
    crea un hecho y de que signo.
    """
    if "error" in row:
        return "ERROR"
    if world_positive(row):
        return "CREATE_POSITIVE"
    if world_negative(row):
        return "CREATE_NEGATIVE"
    return "NO_FACT"


def analyse(raw: dict, cases: dict) -> dict[str, Any]:
    lanes = raw["lanes"]
    extraction_lanes = [name for name in lanes if name != "policy"]
    policy_rows = lanes.get("policy", {}).get("rows", {})

    # --- matriz por frase -------------------------------------------------
    matrix = []
    for case_id, case in cases.items():
        entry = {
            "case_id": case_id,
            "family": case["family"],
            "expected": case["expected"],
            "text": case["text"],
            "policy": policy_rows.get(case_id, {}),
            "lanes": {},
        }
        for lane in extraction_lanes:
            rows = lanes[lane].get("rows", {})
            if case_id not in rows:
                # El carril no midio esta frase (muestra estratificada). Se
                # marca; NO se cuenta como "no produjo hechos", que seria
                # convertir una ausencia de medida en un acierto.
                entry["lanes"][lane] = {"action": NOT_MEASURED}
                continue
            row = rows[case_id]
            entry["lanes"][lane] = {
                "world_claims": world_positive(row),
                "negated_world_claims": world_negative(row),
                "epistemic_proposals": row.get("epistemic_proposals", 0),
                "diagnostics": row.get("diagnostics", 0),
                "abstentions": row.get("abstentions", 0),
                "action": action_of(row),
                "error": row.get("error"),
            }
        matrix.append(entry)

    def measured(lane: str):
        return [e for e in matrix if e["lanes"][lane]["action"] != NOT_MEASURED]

    # --- vacuidad: sin controles positivos, ningun gate significa nada ----
    vacuity = {}
    for lane in extraction_lanes:
        controls = [
            e
            for e in measured(lane)
            if e["family"] in ("HECHO_AFIRMADO", "NEGACION_FACTUAL")
        ]
        produced = sum(
            e["lanes"][lane]["world_claims"] + e["lanes"][lane]["negated_world_claims"]
            for e in controls
        )
        vacuity[lane] = {
            "cases_measured": len(measured(lane)),
            "controls_measured": len(controls),
            "controls_producing_facts": produced,
            "vacuous": produced == 0,
            "note": (
                "el carril no produce ningun hecho ni en los controles positivos: "
                "cualquier gate de seguridad pasaria por inanicion, no por acierto"
                if produced == 0
                else "el carril produce hechos en los controles: los gates son informativos"
            ),
        }

    # --- gates ------------------------------------------------------------
    gates = []

    def add(
        name: str,
        observed,
        threshold,
        ok: bool,
        detail: str = "",
        lane: str = "-",
        evaluable: bool = True,
    ):
        # Un gate sin poblacion NO es un suspenso: es un gate que no se ha
        # podido evaluar. Contarlo como NO CONFORME inventaria un fallo, igual
        # que contarlo como CONFORME inventaria un acierto.
        gates.append(
            {
                "name": name,
                "lane": lane,
                "observed": observed,
                "threshold": threshold,
                "status": ("CONFORME" if ok else "NO CONFORME") if evaluable else "NO EVALUABLE",
                "detail": detail,
            }
        )

    for lane in extraction_lanes:
        vacuo = vacuity[lane]["vacuous"]
        add(
            "carril util (no vacuo)",
            vacuity[lane]["controls_producing_facts"],
            "> 0 hechos en controles positivos",
            not vacuo,
            vacuity[lane]["note"] if vacuo else "",
            lane,
        )
        # OJO: aunque el carril sea vacuo se siguen evaluando los gates de
        # seguridad. La vacuidad invalida los APROBADOS —no se puede acreditar
        # "0 hechos en preguntas" a quien no extrae nada—, pero NO invalida las
        # VIOLACIONES: si un carril que no acierta los controles ademas
        # materializa un hecho donde no lo hay, eso es un fallo real y contarlo
        # como "no interpretable" seria esconderlo.
        suffix = " [carril vacuo: un APROBADO aqui no es acreditable]" if vacuo else ""

        offenders = [
            e["case_id"]
            for e in measured(lane)
            if e["family"] in NO_WORLD_FACT_FAMILIES and e["lanes"][lane]["world_claims"] > 0
        ]
        add(
            "0 hechos del mundo en preguntas/contrafactuales/ficcion interna",
            len(offenders),
            0,
            not offenders,
            ", ".join(offenders[:6]) + suffix,
            lane,
        )

        not_materialized = [
            e["case_id"]
            for e in measured(lane)
            if e["family"] in NOT_MATERIALIZED_FAMILIES
            and (e["lanes"][lane]["world_claims"] or e["lanes"][lane]["negated_world_claims"])
        ]
        add(
            "deseos/ordenes no materializados",
            len(not_materialized),
            0,
            not not_materialized,
            ", ".join(not_materialized[:6]) + suffix,
            lane,
        )

        inverted = [
            e["case_id"]
            for e in measured(lane)
            if e["family"] == "FALSEDAD_ATRIBUIDA" and e["lanes"][lane]["world_claims"] > 0
        ]
        add(
            "falsedad atribuida no invertida (no se afirma lo desmentido)",
            len(inverted),
            0,
            not inverted,
            ", ".join(inverted[:6]) + suffix,
            lane,
        )

        materialized_abstain = [
            (e["case_id"], e["family"], e["lanes"][lane]["action"])
            for e in measured(lane)
            if e["expected"] == "ABSTAIN"
            and e["lanes"][lane]["action"] in ("CREATE_POSITIVE", "CREATE_NEGATIVE")
        ]
        add(
            "(suplementario) ninguna familia con esperado ABSTAIN materializa un hecho",
            len(materialized_abstain),
            0,
            not materialized_abstain,
            "; ".join(f"{c}/{f}->{a}" for c, f, a in materialized_abstain[:8]) + suffix,
            lane,
        )

        neg_family = [e for e in measured(lane) if e["family"] == "NEGACION_FACTUAL"]
        kept = [e for e in neg_family if e["lanes"][lane]["negated_world_claims"] > 0]
        add(
            "negacion factual directa conserva claim negativo",
            f"{len(kept)}/{len(neg_family)}",
            f"{len(neg_family)}/{len(neg_family)}",
            len(kept) == len(neg_family),
            (", ".join(e["case_id"] for e in neg_family if e not in kept)[:200] + suffix)
            if neg_family
            else "el carril no midio ninguna frase de esta familia",
            lane,
            evaluable=bool(neg_family),
        )

    # acuerdo de ACCION entre carriles (solo carriles no vacuos y sin error)
    usable = [
        lane for lane in extraction_lanes if vacuity[lane]["cases_measured"] > 0
    ]
    if len(usable) >= 2 and any(not vacuity[l]["vacuous"] for l in usable):
        common = [
            e for e in matrix
            if all(e["lanes"][l]["action"] != NOT_MEASURED for l in usable)
        ]
        disagreements = []
        for entry in common:
            actions = {lane: entry["lanes"][lane]["action"] for lane in usable}
            if len(set(actions.values())) > 1:
                disagreements.append({"case_id": entry["case_id"], "actions": actions})
        agreement = 1 - len(disagreements) / len(common) if common else 0.0
        # TRAMPA QUE ESTE BLOQUE EVITA: al anadir un carril con muestra
        # pequena, la INTERSECCION se encoge. Si en las pocas frases comunes
        # ningun carril produce un hecho, todos "coinciden" en no hacer nada y
        # sale un 100% que no significa nada — la misma inanicion de siempre,
        # disfrazada de acuerdo. Se exige que haya algo sobre lo que discrepar.
        con_hecho = [
            e for e in common
            if any(
                e["lanes"][l]["action"] in ("CREATE_POSITIVE", "CREATE_NEGATIVE")
                for l in usable
            )
        ]
        add(
            "100% acuerdo de ACCION entre carriles",
            f"{agreement:.2%} sobre {len(common)} frases comunes "
            f"({len(disagreements)} discrepancias; {len(con_hecho)} con algun hecho)",
            "100%",
            not disagreements,
            "; ".join(f"{d['case_id']}:{d['actions']}" for d in disagreements[:8])
            or (
                ""
                if con_hecho
                else "en las frases comunes ningun carril produce un hecho: "
                "coincidir en no hacer nada no es acuerdo"
            ),
            "+".join(usable),
            evaluable=bool(con_hecho),
        )
    else:
        add(
            "100% acuerdo de ACCION entre carriles",
            (
                f"{len(usable)} carriles medidos, todos vacuos"
                if len(usable) >= 2
                else f"solo {len(usable)} carril(es) medidos"
            ),
            ">= 2 carriles utiles",
            False,
            "sin dos carriles medidos, y al menos uno no vacuo, el acuerdo no "
            "es medible: dos carriles que no extraen nada coinciden siempre",
            "+".join(usable) or "-",
        )

    # --- recuentos por familia y carril ----------------------------------
    by_family: dict[str, Any] = defaultdict(dict)
    for lane in extraction_lanes:
        per = defaultdict(lambda: Counter())
        for entry in measured(lane):
            per[entry["family"]][entry["lanes"][lane]["action"]] += 1
        for family, counter in per.items():
            by_family[family][lane] = dict(counter)

    return {
        "gate": "6",
        "corpus": raw["corpus"],
        "lanes": {
            lane: {
                "model": lanes[lane].get("model"),
                "latency_ms": lanes[lane].get("latency_ms"),
                "wall_seconds": lanes[lane].get("wall_seconds"),
                "errors": lanes[lane].get("errors", []),
            }
            for lane in extraction_lanes
        },
        "vacuity": vacuity,
        "gates": gates,
        "by_family": dict(by_family),
        "matrix": matrix,
    }


def to_markdown(report: dict) -> str:
    lines = [
        "# Puerta 6 — No-factividad medida",
        "",
        f"Corpus: `{report['corpus']['path']}` · split `{report['corpus']['split']}` · "
        f"{report['corpus']['cases']} casos · procedencia `{report['corpus']['provenance']}`.",
        "",
        "> El corpus es **dev-synthetic**: mide cobertura de familias de no-factividad, "
        "**no** generaliza a producción.",
        "",
        "## Carriles ejecutados",
        "",
        "| Carril | Modelo | Latencia mediana | Pared (s) | Errores |",
        "|---|---|---|---|---|",
    ]
    for lane, info in report["lanes"].items():
        lat = info.get("latency_ms") or {}
        lines.append(
            f"| `{lane}` | {info.get('model') or '—'} | "
            f"{lat.get('median', '—')} ms | {info.get('wall_seconds', '—')} | "
            f"{len(info.get('errors') or [])} |"
        )

    lines += ["", "## Prueba de vacuidad (controles positivos)", "",
              "Un carril que no produce ningún hecho aprueba todos los gates de "
              "seguridad por inanición. Se comprueba primero.", "",
              "| Carril | Hechos en controles | ¿Vacuo? |", "|---|---|---|"]
    for lane, info in report["vacuity"].items():
        lines.append(
            f"| `{lane}` | {info['controls_producing_facts']} | "
            f"{'**SÍ — gates no interpretables**' if info['vacuous'] else 'no'} |"
        )

    lines += ["", "## Gates", "", "| Gate | Carril | Observado | Umbral | Estado |",
              "|---|---|---|---|---|"]
    for gate in report["gates"]:
        lines.append(
            f"| {gate['name']} | `{gate['lane']}` | {gate['observed']} | "
            f"{gate['threshold']} | **{gate['status']}** |"
        )
        if gate["detail"]:
            lines.append(f"| ↳ detalle | | {gate['detail'][:300]} | | |")

    lines += ["", "## Acción por familia y carril", ""]
    lanes = list(report["lanes"])
    lines += ["| Familia | " + " | ".join(f"`{l}`" for l in lanes) + " |",
              "|---" * (len(lanes) + 1) + "|"]
    for family in sorted(report["by_family"]):
        cells = []
        for lane in lanes:
            counts = report["by_family"][family].get(lane, {})
            cells.append(", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "—")
        lines.append(f"| {family} | " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", nargs="+", default=["artifacts/v3-final-validation/gate6-raw-lanes.json"])
    parser.add_argument("--out", default="artifacts/v3-final-validation")
    args = parser.parse_args()

    raw, cases = load([Path(p) for p in args.raw])
    report = analyse(raw, cases)
    out = Path(args.out)
    (out / "gate6-factivity-matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    (out / "gate6-factivity-matrix.md").write_text(to_markdown(report), encoding="utf-8")
    for gate in report["gates"]:
        print(f"{gate['status']:14} {gate['lane']:10} {gate['name']} -> {gate['observed']}")


if __name__ == "__main__":
    main()
