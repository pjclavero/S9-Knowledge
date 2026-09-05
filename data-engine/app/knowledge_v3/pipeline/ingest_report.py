# -*- coding: utf-8 -*-
"""`ingest-run/v1`: el informe de una ingesta real, y el contrato entre carriles.

POR QUE EXISTE
--------------
Tres carriles consumen la salida de una ingesta:

  * **B (altas de entidad)** necesita las resoluciones que proponen CREAR, con
    la superficie propuesta, el tipo y por que no se enlazo.
  * **C (escritura)** necesita el `GraphMutationPlan` APROBADO, sellado y con su
    `plan_hash`, tal cual lo emitio el motor.
  * **D (revision)** necesita el `review_plan` y las decisiones que NO son
    ACCEPT, con sus codigos.

Si cada uno se acoplara a `SourceRun` (un dataclass privado del orquestador,
con objetos vivos dentro), cualquier refactor del orquestador rompería tres
carriles a la vez. Este modulo publica esa salida como **JSON de documentos de
contrato**, y esa es la frontera.

QUE NO HACE
-----------
No inventa campos. Cada documento sale del `to_dict()` de su contrato congelado
(`source-asset`, `source-episode`, `evidence-fragment`, `entity-mention`,
`entity-resolution`, `claim-proposal`, `fact-assertion`, `graph-mutation-plan`).
Las secciones `candidates`, `decisions`, `abstentions` y `contradictions` son
PROYECCIONES: reordenan lo que ya esta, no lo completan.

Y no rellena un hueco con un cero. Lo que el motor no produce hoy sale en
`carencias`, con su codigo y su detalle, para que nadie lea "0 contradicciones"
donde lo cierto es "no se publican contradicciones".

FORMA DEL DOCUMENTO
-------------------
    {
      "report_contract": "ingest-run/v1",
      "run":           {...}   identidad de la corrida: fuente, hash, reloj
      "asset":         {...}   SourceAsset
      "episodes":      [...]   SourceEpisode
      "evidence":      [...]   EvidenceFragment
      "mentions":      [...]   EntityMention
      "resolutions":   [...]   EntityResolution
      "candidates":    {...}   proyeccion de las resoluciones por accion  <- B
      "claims":        [...]   ClaimProposal
      "decisions":     [...]   proyeccion de las decisiones del motor     <- D
      "assertions":    [...]   FactAssertion
      "plan":          {...}   GraphMutationPlan aprobado, o null         <- C
      "review_plan":   {...}   GraphMutationPlan de revision, o null      <- D
      "abstentions":   [...]   claims que el extractor marco `abstained`
      "contradictions":[...]   conflictos observados por el motor
      "diagnostics":   [...]   diagnosticos de la cadena, sin filtrar
      "totals":        {...}   conteos, TODOS derivados de las listas de arriba
      "carencias":     [...]   lo que hoy no hay, dicho como tal
    }

`totals` se calcula con `len()` de las listas que este mismo documento publica:
un conteo que no se puede comprobar mirando el documento no es un conteo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

REPORT_CONTRACT = "ingest-run/v1"

#: Acciones de `EntityResolution.action` que el carril B tiene que atender.
CREATING_ACTIONS = ("CREATE_NEW", "CREATE_PROVISIONAL")


def _doc(value: Any) -> Optional[dict]:
    return value.to_dict() if value is not None else None


def _findings(decision: Any) -> list[dict]:
    """Los hallazgos del motor, con sus DOS codigos.

    `canonical` es el `reason_code` del contrato (REVIEW_ENTITY) y `code` el
    descriptivo del motor (ENTITY_NOT_IN_SNAPSHOT). Publicar solo el canonico
    deja seis causas distintas indistinguibles, que es justo lo que un humano
    necesita separar para revisar.
    """
    return [
        {"axis": f.axis, "severity": str(getattr(f.severity, "name", f.severity)),
         "canonical": f.canonical, "code": f.code}
        for f in getattr(decision, "findings", ())
    ]


def _finding_codes(decision: Any) -> list[str]:
    """Solo los `reason_code` canonicos, para quien no quiera el detalle."""
    return [f["canonical"] or f["code"] for f in _findings(decision)]


def _decision_row(decision: Any) -> dict:
    return {
        "claim_id": decision.claim_id,
        "decision": decision.decision,
        "predicate": decision.predicate,
        "direction": decision.direction,
        "subject_entity_id": decision.subject_entity_id,
        "object_entity_id": decision.object_entity_id,
        "epistemic_status": decision.epistemic_status,
        "negated": bool(decision.negated),
        "confidence": decision.confidence,
        "episode_id": decision.episode_id,
        "evidence_fragment_ids": list(decision.evidence_fragment_ids),
        "reason_codes": _finding_codes(decision),
        "findings": _findings(decision),
        "conflicts": len(decision.conflicts),
        "duplicate_in_batch": bool(decision.duplicate_in_batch),
    }


def _candidates(resolutions: Sequence[Any]) -> dict:
    """Las resoluciones, agrupadas por lo que PIDEN hacerle al grafo.

    El criterio es el campo `action` del contrato, no una heuristica de este
    modulo: `LINK_EXISTING` enlaza, `CREATE_*` da de alta, `REVIEW`/`SPLIT`
    van a un humano.
    """
    link, create, review = [], [], []
    for res in resolutions:
        row = {
            "resolution_id": res.resolution_id,
            "mention_ids": list(res.mention_ids),
            "action": res.action,
            "entity_type": res.entity_type,
            "confidence": res.confidence,
            "reason_codes": list(res.reason_codes),
            "candidate_entity_ids": list(res.candidate_entity_ids),
            "selected_entity_id": res.selected_entity_id,
            # `assigned_entity_id` es el id que el resolutor ATRIBUYE; en un
            # enlace coincide con el seleccionado. Se publican los dos: si un
            # dia divergen, el consumidor lo ve en vez de leer un hueco.
            "assigned_entity_id": res.assigned_entity_id,
        }
        if res.action == "LINK_EXISTING":
            link.append(row)
        elif res.action in CREATING_ACTIONS:
            create.append(row)
        else:
            review.append(row)
    return {"link_existing": link, "create_entity": create, "review_identity": review}


def _contradictions(decisions: Sequence[Any]) -> list[dict]:
    """Conflictos que el motor OBSERVO contra el grafo previo.

    Solo salen los que el motor adjunta a la decision (`conflicts`). Si un
    conflicto no llega hasta aqui, no se inventa: se declara como carencia.
    """
    out: list[dict] = []
    for decision in decisions:
        for conflict in decision.conflicts:
            out.append(
                {
                    "claim_id": decision.claim_id,
                    "decision": decision.decision,
                    "predicate": decision.predicate,
                    "conflict_with": getattr(conflict, "assertion_id", None),
                    "reason_codes": _finding_codes(decision),
                }
            )
    return out


def _carencias(report: dict, run: Any, lexicon_size: Optional[int]) -> list[dict]:
    """Lo que la corrida NO pudo enseñar, cada cosa con su motivo observado."""
    faltas: list[dict] = []
    if lexicon_size == 0:
        faltas.append(
            {
                "code": "SIN_GLOSARIO",
                "detail": (
                    "ni el perfil ni el catalogo aportan una sola entrada de "
                    "glosario. El extractor determinista no tiene reconocedor "
                    "propio (D-6): sin glosario no puede haber menciones"
                ),
            }
        )
    if not report["mentions"]:
        faltas.append(
            {
                "code": "SIN_MENCIONES",
                "detail": (
                    "la fuente se normalizo pero no se detecto ninguna mencion: "
                    "ningun nombre del texto esta en el glosario ni sigue el "
                    "patron <titulo declarado> <Nombre Propio>"
                ),
            }
        )
    if not report["claims"]:
        faltas.append(
            {
                "code": "SIN_CLAIMS",
                "detail": (
                    "hubo menciones pero ninguna relacion emitida: revisa los "
                    "diagnosticos (RELATION_PHRASE_WITHOUT_ARGUMENTS y familia)"
                    if report["mentions"]
                    else "sin menciones no puede haber relaciones"
                ),
            }
        )
    if run.stopped_at:
        faltas.append(
            {
                "code": "CADENA_DETENIDA",
                "detail": f"la cadena paro en {run.stopped_at}: {run.stop_reason}",
            }
        )
    if report["plan"] is None:
        faltas.append(
            {
                "code": "SIN_PLAN",
                "detail": "el motor no llego a emitir GraphMutationPlan",
            }
        )
    elif not report["plan"].get("local_approval", {}).get("approved"):
        faltas.append(
            {
                "code": "PLAN_NO_APROBADO",
                "detail": (
                    "hay plan pero el motor no lo aprobo: el carril C no tiene "
                    "nada que escribir de esta corrida"
                ),
            }
        )
    en_revision = sum(
        1 for d in report["decisions"] if d["decision"] in ("REVIEW", "ABSTAIN")
    )
    if en_revision and not report["totals"]["review_operations"]:
        faltas.append(
            {
                "code": "PLAN_REVISION_SIN_OPERACIONES",
                "detail": (
                    f"{en_revision} decisiones en REVIEW/ABSTAIN pero el plan de "
                    "revision no lleva ninguna operacion de mutacion: el planner "
                    "solo materializa las ACCEPT. Lo que el carril D tiene que "
                    "consumir es `decisions`, no `review_plan.mutation_operations`"
                ),
            }
        )
    faltas.append(
        {
            "code": "SIN_ESCRITURA",
            "detail": (
                "dry-run: no se abrio ningun driver y no se toco Neo4j. Escribir "
                "es del carril C, contra un grafo efimero y con el gate del writer"
            ),
        }
    )
    return faltas


def ingest_report(
    result: Any,
    *,
    source_path: Path,
    input_hash: dict,
    source_bytes: int,
    catalog_entities: Sequence[dict],
    profile: Any,
    lexicon_entries: int,
    clock_read_at_boundary: bool,
) -> dict:
    """`PipelineResult` de UNA fuente -> documento `ingest-run/v1`."""
    if len(result.runs) != 1:
        raise ValueError(
            f"ingest_report describe UNA fuente; llegaron {len(result.runs)} corridas"
        )
    run = result.runs[0]
    config = dict(result.config_declared)

    resolutions = list(run.resolutions)
    decisions = list(run.decisions)
    report: dict[str, Any] = {
        "report_contract": REPORT_CONTRACT,
        "run": {
            "source_id": run.source_id,
            "source_path": str(source_path),
            "source_kind": (run.asset.source_kind if run.asset else None),
            "input_hash": input_hash,
            "byte_size": source_bytes,
            "workspace": config.get("workspace"),
            "collection_id": config.get("collection_id"),
            "profile_id": profile.profile_id,
            "now": config.get("now"),
            "writer_mode": config.get("writer_mode"),
            "apply": False,
            "clock_read_at_boundary": bool(clock_read_at_boundary),
            "catalog_entities_declared": len(catalog_entities),
            "catalog_entities_linkable": sum(
                1 for e in catalog_entities if not e.get("provisional")
            ),
            "latency_ms": round(result.latency_ms, 3),
            "provider_calls": result.provider_calls,
            "stopped_at": run.stopped_at,
            "stop_reason": run.stop_reason,
        },
        "asset": _doc(run.asset),
        "episodes": [e.to_dict() for e in run.episodes],
        "evidence": [f.to_dict() for f in run.fragments],
        "mentions": [m.to_dict() for m in run.mentions],
        "resolutions": [r.to_dict() for r in resolutions],
        "candidates": _candidates(resolutions),
        "claims": [c.to_dict() for c in run.claims],
        "decisions": [_decision_row(d) for d in decisions],
        "assertions": [a.to_dict() for a in run.assertions],
        "plan": _doc(run.plan),
        "review_plan": _doc(run.review_plan),
        "abstentions": [c.to_dict() for c in run.claims if c.abstained],
        "contradictions": _contradictions(decisions),
        "diagnostics": list(run.diagnostics),
        "normalization_report": dict(run.normalization_report),
        "reconciliation_report": dict(run.reconciliation_report),
        "stage_latency_ms": {k: round(v, 3) for k, v in run.stage_latency_ms.items()},
    }

    report["totals"] = {
        "episodes": len(report["episodes"]),
        "evidence": len(report["evidence"]),
        "mentions": len(report["mentions"]),
        "resolutions": len(report["resolutions"]),
        "link_existing": len(report["candidates"]["link_existing"]),
        "create_entity": len(report["candidates"]["create_entity"]),
        "review_identity": len(report["candidates"]["review_identity"]),
        "claims": len(report["claims"]),
        "abstentions": len(report["abstentions"]),
        "decisions": len(report["decisions"]),
        "assertions": len(report["assertions"]),
        "contradictions": len(report["contradictions"]),
        "plan_operations": len(report["plan"]["mutation_operations"]) if report["plan"] else 0,
        "review_operations": (
            len(report["review_plan"]["mutation_operations"]) if report["review_plan"] else 0
        ),
    }
    # Conteo por veredicto: se deriva de `decisions`, que este mismo informe
    # publica. Es lo que el carril D necesita y lo que `review_operations` NO
    # dice, porque un REVIEW no genera operacion de mutacion.
    por_veredicto: dict[str, int] = {}
    for fila in report["decisions"]:
        por_veredicto[fila["decision"]] = por_veredicto.get(fila["decision"], 0) + 1
    report["totals"]["decisions_by_outcome"] = dict(sorted(por_veredicto.items()))
    report["run"]["lexicon_entries"] = int(lexicon_entries)
    report["carencias"] = _carencias(report, run, int(lexicon_entries))
    return report


# --------------------------------------------------------------------------
# Acta legible
# --------------------------------------------------------------------------
def _tabla(cabeceras: Sequence[str], filas: Sequence[Sequence[Any]]) -> list[str]:
    if not filas:
        return ["_(ninguna)_", ""]
    out = ["| " + " | ".join(cabeceras) + " |",
           "|" + "|".join(["---"] * len(cabeceras)) + "|"]
    for fila in filas:
        out.append("| " + " | ".join("" if c is None else str(c) for c in fila) + " |")
    out.append("")
    return out


def to_markdown(report: dict) -> str:
    """Acta del vertical slice, vinculada por IDs de dominio."""
    run = report["run"]
    totals = report["totals"]
    lineas: list[str] = [
        f"# Acta de ingesta V3 — {run['source_id']}",
        "",
        "## SOURCE",
        "",
        f"- fichero: `{run['source_path']}`",
        f"- source_kind: `{run['source_kind']}`  ({run['byte_size']} bytes)",
        f"- INPUT HASH: `{run['input_hash']['algorithm']}:{run['input_hash']['value']}`",
        f"- workspace: `{run['workspace']}`  ·  perfil: `{run['profile_id']}`",
        f"- collection: `{run['collection_id']}`",
        f"- instante inyectado: `{run['now']}`"
        + ("  (reloj leido en la frontera del CLI)" if run["clock_read_at_boundary"] else ""),
        f"- modo del writer: **{run['writer_mode']}**  ·  apply: `{run['apply']}`",
        f"- catalogo declarado: {run['catalog_entities_declared']} entidades "
        f"({run['catalog_entities_linkable']} enlazables)",
        f"- latencia: {run['latency_ms']} ms  ·  llamadas a proveedor: {run['provider_calls']}",
        "",
        "## Conteos",
        "",
    ]
    lineas += _tabla(
        ["magnitud", "n"], [[k, v] for k, v in totals.items()]
    )
    lineas += ["> Todos estos numeros son `len()` de las listas que este mismo",
               "> informe publica: se pueden recontar sobre el JSON.", ""]

    lineas += ["## EPISODES", ""]
    lineas += _tabla(
        ["episode_id", "seq", "modality", "texto (inicio)"],
        [
            [e["episode_id"], e["sequence"], e["modality"],
             ((e.get("text") or "")[:70]).replace("\n", " ")]
            for e in report["episodes"]
        ],
    )

    lineas += ["## EVIDENCE", ""]
    lineas += _tabla(
        ["fragment_id", "episode_id", "literal"],
        [
            [f["fragment_id"], f.get("episode_id"),
             (f.get("literal_text") or "")[:60].replace("\n", " ")]
            for f in report["evidence"]
        ],
    )

    lineas += ["## ENTITIES (menciones detectadas)", ""]
    lineas += _tabla(
        ["mention_id", "superficie", "tipos", "conf", "episode_id"],
        [
            [m["mention_id"][-16:], m["surface"],
             ",".join(t.get("type", "?") for t in m.get("type_candidates", [])),
             m["confidence"], m["episode_id"]]
            for m in report["mentions"]
        ],
    )

    lineas += ["## LINK_EXISTING (menciones enlazadas a entidades del grafo)", ""]
    lineas += _tabla(
        ["resolution_id", "entidad", "conf", "motivos"],
        [
            [c["resolution_id"][:28],
             c["assigned_entity_id"] or c["selected_entity_id"], c["confidence"],
             ",".join(c["reason_codes"])]
            for c in report["candidates"]["link_existing"]
        ],
    )

    lineas += ["## CREATE_ENTITY (altas propuestas — carril B)", ""]
    lineas += _tabla(
        ["resolution_id", "accion", "tipo", "conf", "motivos"],
        [
            [c["resolution_id"][:28], c["action"], c["entity_type"], c["confidence"],
             ",".join(c["reason_codes"])]
            for c in report["candidates"]["create_entity"]
        ],
    )

    lineas += ["## RELATIONS (claims propuestos por el extractor)", ""]
    lineas += _tabla(
        ["claim_id", "frase", "predicados", "negado", "conf", "abst", "rev"],
        [
            [c["claim_id"][-16:], c["relation_phrase"],
             ",".join(p.get("predicate", "?") for p in c["predicate_candidates"]),
             c["negated"], c["confidence"], c["abstained"], c["review_required"]]
            for c in report["claims"]
        ],
    )

    lineas += ["## REVIEW (decisiones del motor)", ""]
    lineas += _tabla(
        ["claim_id", "decision", "predicado", "sujeto", "objeto", "neg", "conf", "motivos"],
        [
            [d["claim_id"][-16:], d["decision"], d["predicate"], d["subject_entity_id"],
             d["object_entity_id"], d["negated"], d["confidence"],
             ",".join(f["code"] for f in d["findings"])]
            for d in report["decisions"]
        ],
    )

    lineas += ["## ABSTAIN", ""]
    lineas += _tabla(
        ["claim_id", "frase", "motivo"],
        [
            [c["claim_id"][-16:], c["relation_phrase"],
             ",".join(str(v) for v in (c.get("metadata") or {}).values())[:70]]
            for c in report["abstentions"]
        ],
    )

    lineas += ["## Contradicciones", ""]
    lineas += _tabla(
        ["claim_id", "predicado", "choca con", "motivos"],
        [
            [c["claim_id"][-16:], c["predicate"], c["conflict_with"],
             ",".join(c["reason_codes"])]
            for c in report["contradictions"]
        ],
    )

    lineas += ["## ASSERTIONS", ""]
    lineas += _tabla(
        ["assertion_id", "predicado", "sujeto", "objeto", "estado"],
        [
            [a["assertion_id"][:28], a["predicate"], a["subject_entity_id"],
             a["object_entity_id"], a.get("epistemic_status")]
            for a in report["assertions"]
        ],
    )

    lineas += ["## PLAN de escritura", ""]
    plan = report["plan"]
    if plan is None:
        lineas += ["_El motor no emitio plan._", ""]
    else:
        aprobado = plan.get("local_approval", {}).get("approved")
        lineas += [
            f"- plan_id: `{plan['plan_id']}`",
            f"- plan_hash: `{plan['plan_hash']['value']}`",
            f"- snapshot_id: `{plan['snapshot_id']}`",
            f"- aprobado por el motor: **{aprobado}**",
            f"- expira: `{plan['expires_at']}`",
            "",
        ]
        lineas += _tabla(
            ["op", "detalle"],
            [
                [op.get("operation_type"),
                 str({k: v for k, v in op.items() if k != "operation_type"})[:110]]
                for op in plan["mutation_operations"]
            ],
        )

    lineas += ["## Diagnosticos de la cadena", ""]
    lineas += _tabla(
        ["step", "code", "episode_id", "detalle"],
        [[d["step"], d["code"], d["episode_id"], d["detail"][:60]] for d in report["diagnostics"]],
    )

    lineas += ["## CARENCIAS declaradas", "",
               "Lo que esta corrida NO puede enseñar, y por que. No se rellena",
               "con ceros que parezcan datos.", ""]
    lineas += _tabla(
        ["codigo", "detalle"], [[c["code"], c["detail"]] for c in report["carencias"]]
    )
    return "\n".join(lineas)


__all__ = ["REPORT_CONTRACT", "ingest_report", "to_markdown"]
