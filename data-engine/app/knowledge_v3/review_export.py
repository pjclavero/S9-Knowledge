"""Export immutable pipeline results for the decoupled V3 review viewer.

Direction is deliberately one way::

    PipelineResult -> immutable review package -> proposals/ -> viewer

The viewer never imports the engine and this module never imports the viewer.
Policy: REVIEW is always exported. ABSTAIN and REJECT_INVALID are exported to
the same package (and remain filterable) so that no engine outcome disappears
silently. ACCEPT is omitted because it is not a human-review claim.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts.base import canonical_json, sha256_hash
from .review_decisions import resolved_proposal_ids
from .review_plan import PLAN_CONTEXT_KEY, plan_context_from_run


EXPORTED_DECISIONS = frozenset({"REVIEW", "ABSTAIN", "REJECT_INVALID"})


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    for method in ("to_contract_dict", "to_dict"):
        fn = getattr(value, method, None)
        if fn:
            return fn()
    return dict(vars(value))


def _semantic_hash(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k not in {"proposal_id", "proposal_hash"}}
    result = sha256_hash(body)
    return result["value"] if isinstance(result, dict) else str(result)


def _stable_proposal_id(document: dict[str, Any], claim_id: Any) -> str:
    identity = {
        "workspace": document["workspace"],
        "source_id": document["source_id"],
        "episode_id": document["episode_id"],
        "claim_id": str(claim_id or "not_available"),
    }
    digest = sha256_hash(identity)
    value = digest["value"] if isinstance(digest, dict) else str(digest)
    return f"review:{value}"


def _lookup(items: list[Any], key: str, value: Any) -> dict[str, Any]:
    for item in items:
        raw = _dict(item)
        if raw.get(key) == value:
            return raw
    return {}


def _mention_and_resolution(
    mention_ids: Any,
    mentions: list[Any],
    resolutions: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the first claim mention using the real plural contracts."""
    mention_id = next(iter(mention_ids or []), None)
    mention = _lookup(mentions, "mention_id", mention_id)
    for resolution_value in resolutions:
        resolution = _dict(resolution_value)
        if mention_id is not None and mention_id in (resolution.get("mention_ids") or []):
            return mention, resolution
    return mention, {}


def _resolved_entity_id(resolution: dict[str, Any]) -> Any:
    return (
        resolution.get("selected_entity_id")
        or resolution.get("assigned_entity_id")
        or "not_available"
    )


def run_plan_material(result: Any) -> tuple[Any, dict[str, Any]]:
    """El plan de la corrida y sus decisiones de motor, INDEXADAS por claim.

    Es lo que `knowledge_v3.review_plan` necesita y una propuesta no contiene:
    el ancla de estado (`snapshot_id`), la procedencia de la fuente
    (`source_hash`, `source_asset_id`) y las versiones. Hasta este corte la
    corrida lo calculaba y lo TIRABA -- vive en `run.plan`/`run.review_plan`,
    que mueren con el proceso -- y por eso no existia ningun plan aprobado
    durable que aplicar.

    Se prefiere `review_plan` a `plan` porque es el de las reclamaciones que
    van a revision, que son justamente las que el operador puede aprobar; el
    de escritura sirve de respaldo cuando aquel no existe. Los dos comparten
    contexto: el `PlanContext` de la corrida es uno solo.

    Las decisiones se toman de `run.decisions` --TODAS-- y no de las del plan:
    el paquete tambien exporta `ABSTAIN` y `REJECT_INVALID`, y si esas se
    quedasen sin decision, aprobarlas mas tarde no produciria nada.
    """
    for run in getattr(result, "runs", ()):
        plan = getattr(run, "review_plan", None) or getattr(run, "plan", None)
        if plan is None:
            continue
        decisiones = {}
        for decision_value in getattr(run, "decisions", ()):
            bruto = _dict(decision_value)
            claim_id = bruto.get("claim_id")
            if claim_id:
                decisiones[str(claim_id)] = bruto
        return plan.to_dict(), decisiones
    return None, {}


def review_documents(result: Any, *, workspace: str) -> list[dict[str, Any]]:
    """Adapt a real PipelineResult without inventing absent data."""
    documents: list[dict[str, Any]] = []
    config = getattr(result, "config_declared", {}) or {}
    for run in getattr(result, "runs", ()):
        episodes = list(getattr(run, "episodes", ()))
        claims = list(getattr(run, "claims", ()))
        mentions = list(getattr(run, "mentions", ()))
        resolutions = list(getattr(run, "resolutions", ()))
        fragments = list(getattr(run, "fragments", ()))
        shadow_by_claim_id = {
            _dict(record).get("claim_id"): _dict(record)
            for record in getattr(run, "shadow_decisions", ())
        }
        for decision_value in getattr(run, "decisions", ()):
            decision = _dict(decision_value)
            outcome = str(decision.get("decision") or "UNKNOWN")
            if outcome not in EXPORTED_DECISIONS:
                continue
            claim_id = decision.get("claim_id")
            claim = _lookup(claims, "claim_id", claim_id)
            episode_id = decision.get("episode_id") or claim.get("episode_id") or "not_available"
            episode = _lookup(episodes, "episode_id", episode_id)
            episode_text = episode.get("text") or episode.get("content") or ""
            fragment_id = next(iter(claim.get("evidence_fragment_ids") or []), None)
            fragment = _lookup(fragments, "fragment_id", fragment_id)
            start = fragment.get("start_offset", fragment.get("start", 0))
            end = fragment.get("end_offset", fragment.get("end", start))
            try:
                start, end = int(start), int(end)
            except (TypeError, ValueError):
                start = end = 0
            if not (0 <= start <= end <= len(episode_text)):
                start = end = 0
            subject_mention, subject_resolution = _mention_and_resolution(
                claim.get("subject_mentions"), mentions, resolutions
            )
            object_mention, object_resolution = _mention_and_resolution(
                claim.get("object_mentions"), mentions, resolutions
            )
            subject_entity = _resolved_entity_id(subject_resolution)
            object_entity = _resolved_entity_id(object_resolution)
            proposal = {
                "subject": (
                    subject_entity
                    if subject_entity != "not_available"
                    else subject_mention.get("surface") or "not_available"
                ),
                "predicate": decision.get("predicate") or claim.get("predicate") or "UNKNOWN",
                "object": (
                    object_entity
                    if object_entity != "not_available"
                    else object_mention.get("surface") or "not_available"
                ),
                "direction": decision.get("direction") or claim.get("direction") or "UNKNOWN",
                "negated": claim.get("negated", False),
                "negation_kind": claim.get("negation_kind") or "UNKNOWN",
                "scope": claim.get("scope") or "not_available",
                "epistemic_status": claim.get("epistemic_status") or "UNKNOWN",
                "temporal_status": claim.get("temporal_status") or "UNKNOWN",
            }
            trace = claim.get("provider_trace") or []
            shadow = shadow_by_claim_id.get(claim_id)
            document: dict[str, Any] = {
                "workspace": workspace,
                "source_id": getattr(run, "source_id", None) or "not_available",
                "episode_id": episode_id,
                "episode_text": episode_text,
                "evidence": {
                    "start": start,
                    "end": end,
                    "literal_text": episode_text[start:end],
                },
                "proposal": proposal,
                "engine_decision": {
                    "decision": outcome,
                    "reason_codes": decision.get("reason_codes") or [],
                    "confidence": decision.get("confidence"),
                    "effective_decision": outcome,
                    "shadow_decision": shadow.get("shadow_decision") if shadow else None,
                    "ignored_findings": shadow.get("ignored_findings", []) if shadow else [],
                    "effective_findings": (
                        shadow.get("effective_findings", [])
                        if shadow else decision.get("reason_codes") or []
                    ),
                    "shadow_findings": shadow.get("shadow_findings", []) if shadow else [],
                    "would_emit_operations": (
                        bool(shadow.get("would_emit_operations")) if shadow else False
                    ),
                    "operation_kinds": shadow.get("operation_kinds", []) if shadow else [],
                    "provider": shadow.get("provider") if shadow else None,
                    "model": shadow.get("model") if shadow else None,
                },
                "resolution": {
                    "subject": subject_entity,
                    "object": object_entity,
                },
                "alternatives": {
                    "predicates": claim.get("predicate_alternatives") or [],
                    "directions": claim.get("direction_alternatives") or [],
                },
                "provenance": {
                    "extractors": sorted({str(x.get("step") or "not_available") for x in trace}),
                    "providers": sorted({str(x.get("provider") or "not_available") for x in trace}),
                    "models": sorted({str(x.get("model") or "not_available") for x in trace}),
                    "independent_families": sorted({
                        str(x.get("independent_family") or "not_available") for x in trace
                    }),
                },
                "ontology_version": config.get("ontology_version"),
                "engine_version": config.get("engine_version") or "knowledge-v3",
                "prompt_version": config.get("prompt_version"),
                "profile_version": config.get("profile_version") or config.get("profile_id"),
            }
            document["claim_id"] = claim_id
            document["proposal_id"] = _stable_proposal_id(document, claim_id)
            document["proposal_hash"] = _semantic_hash(document)
            documents.append(document)
    return sorted(documents, key=lambda x: (x["source_id"], x["episode_id"], x["proposal_id"]))


def run_entity_anchors(
    result: Any, documents: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """El ancla de estado de cada entidad que las propuestas resuelven.

    DE DONDE SALE, Y POR QUE NO ES UNA SEGUNDA AUTORIDAD: del MISMO
    `GraphSnapshot` del que `engine/planner.py` copia `expected_version` y
    `expected_hash` (`context.snapshot.entity(...)`), que es tambien de donde
    sale el `snapshot_id` que este sobre ya publicaba. No se lee el grafo, no
    se deduce nada y no se inventa ninguna version: se copia la foto sobre la
    que se decidio.

    Se acota a las entidades que las propuestas EXPORTADAS nombran. Publicar
    el snapshot entero engordaria el paquete con estado que nadie va a usar,
    y el almacen de propuestas ya crece sin cota.
    """
    interesan: set[str] = set()
    for documento in documents:
        for bloque in (documento.get("resolution") or {}, documento.get("proposal") or {}):
            for campo in ("subject", "object"):
                valor = bloque.get(campo)
                if isinstance(valor, str) and valor and valor != "not_available":
                    interesan.add(valor)
    anclas: dict[str, dict[str, Any]] = {}
    if not interesan:
        return anclas
    for run in getattr(result, "runs", ()):
        snapshot = getattr(run, "snapshot", None)
        if snapshot is None:
            continue
        for entity_id in sorted(interesan):
            if entity_id in anclas:
                continue
            nodo = None
            try:
                nodo = snapshot.entity(entity_id)
            except Exception:  # noqa: BLE001 - un snapshot raro no rompe el export
                nodo = None
            if nodo is None:
                continue
            anclas[entity_id] = {
                "version": getattr(nodo, "version", None),
                "state_hash": dict(getattr(nodo, "state_hash", None) or {}),
                "pending_creation": bool(getattr(nodo, "pending_creation", False)),
                # OBSERVADA o DECLARADA. Se publica el dato, no una conclusion:
                # quien sella decide con el, y el sobre deja constancia de cual
                # de las dos cosas era.
                "observed": bool(getattr(nodo, "observed", False)),
            }
    return anclas


def run_provenance_material(
    result: Any,
    documents: Sequence[Mapping[str, Any]],
    decisions_by_claim: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Los DOCUMENTOS de procedencia que las propuestas exportadas citan.

    Es el material que `apply_v3` necesita para persistir procedencia y que el
    plan NO puede contener: el plan CITA `evidence_fragment_ids`; los
    documentos que esos ids nombran viven en la corrida. Por la ruta del CLI
    se los pasa `pipeline.write` desde el `SourceRun` vivo; por la ruta de la
    UI la corrida ya ha muerto cuando el operador aprueba, asi que el material
    tiene que viajar.

    ACOTADO A LO CITADO, no a la corrida entera: solo los fragmentos que las
    propuestas exportadas nombran, los episodios de esos fragmentos y la
    fuente. Un paquete que arrastrase toda la corrida crecerria sin relacion
    con lo que hay que revisar.
    """
    citados: set[str] = set()
    for documento in documents:
        decision = decisions_by_claim.get(str(documento.get("claim_id") or "")) or {}
        for fid in decision.get("evidence_fragment_ids") or ():
            if fid:
                citados.add(str(fid))
    material: dict[str, Any] = {"source_asset": None, "episodes": [], "fragments": []}
    if not citados:
        return material
    episodios_vistos: set[str] = set()
    for run in getattr(result, "runs", ()):
        fragmentos = [
            _dict(f) for f in getattr(run, "fragments", ())
            if str(_dict(f).get("fragment_id") or "") in citados
        ]
        if not fragmentos:
            continue
        if material["source_asset"] is None and getattr(run, "asset", None) is not None:
            material["source_asset"] = _dict(run.asset)
        material["fragments"].extend(fragmentos)
        necesarios = {str(f.get("episode_id") or "") for f in fragmentos}
        for episodio in getattr(run, "episodes", ()):
            doc = _dict(episodio)
            eid = str(doc.get("episode_id") or "")
            if eid in necesarios and eid not in episodios_vistos:
                episodios_vistos.add(eid)
                material["episodes"].append(doc)
    material["fragments"].sort(key=lambda f: str(f.get("fragment_id") or ""))
    material["episodes"].sort(key=lambda e: str(e.get("episode_id") or ""))
    return material


@dataclass(frozen=True)
class ReviewPackageExport:
    """Lo que UNA corrida dejó de verdad en el almacen de revision.

    Se devuelve en vez de la ruta a secas porque el resumen de la ingesta
    tiene que poder decir CUANTAS propuestas revisables produjo esta corrida y
    a que corrida pertenecen. Derivarlo mas tarde volviendo a leer la carpeta
    seria una segunda derivacion del mismo hecho, y dos derivaciones de un
    hecho son dos verdades.
    """

    path: Path
    workspace: str
    proposal_ids: tuple[str, ...]
    job_id: "str | None" = None

    @property
    def count(self) -> int:
        return len(self.proposal_ids)

    def __fspath__(self) -> str:
        # Compatibilidad: este valor se usaba como `Path`. Sigue sirviendo
        # como ruta para `open()` y para `os.path`.
        return str(self.path)


def export_review_package(
    result: Any,
    output_dir: Path,
    *,
    workspace: str,
    decisions_db: "Path | None" = None,
    run: "dict[str, Any] | None" = None,
) -> ReviewPackageExport:
    """Atomically write one content-addressed immutable package; reruns dedup.

    CIERRE DEL LAZO: antes de publicar, se leen las decisiones humanas ACTIVAS
    de su unica autoridad (la tabla ``human_decisions`` del visor) y toda
    propuesta ya resuelta por una persona (``APPROVE``/``REJECT``) DEJA de
    presentarse como reclamacion pendiente. Queda anotada en ``resolved`` con
    la decision que la resolvio, para que la resolucion se vea y no se
    adivine. Un ``undo`` la devuelve a pendiente, porque la autoridad dice que
    ya no hay decision activa.

    No se lee ``decisions.jsonl``: es exportacion de auditoria, no autoridad.
    """
    documents = review_documents(result, workspace=workspace)
    plan_doc, decisions_by_claim = run_plan_material(result)
    resolved = resolved_proposal_ids(decisions_db, workspace=workspace)
    pending = [doc for doc in documents if doc["proposal_id"] not in resolved]
    consumed = [
        resolved[doc["proposal_id"]].to_dict()
        for doc in documents
        if doc["proposal_id"] in resolved
    ]
    documents = pending
    package_body: dict[str, Any] = {
        "workspace": workspace, "items": documents, "resolved": consumed,
    }
    # ATRIBUCION A LA CORRIDA (Slice 2 · Corte 4).
    #
    # Va en el SOBRE, no dentro de cada documento. La diferencia importa: el
    # `proposal_hash` es el hash SEMANTICO de la propuesta, y meterle el
    # `job_id` convertiria cada reejecucion en una "version distinta" de la
    # misma reclamacion, que es mentira — la reclamacion no ha cambiado, la ha
    # vuelto a producir otra corrida.
    #
    # En el sobre, en cambio, el digest del paquete SI cambia, asi que la
    # corrida B escribe su propio fichero; y al cargarlo, el visor pliega las
    # dos copias en UNA propuesta cuya lista de corridas es [A, B]. El
    # operador ve una sola reclamacion y las dos corridas que la produjeron.
    #
    # `run=None` (CLI, arneses, cualquier llamador que no venga de la cola) no
    # anade la clave: el cuerpo es byte a byte el de antes y el paquete
    # conserva su digest historico.
    if run:
        package_body["run"] = {k: v for k, v in sorted(run.items()) if v is not None}
        # EL RESTO DEL ARTEFACTO, que hasta ahora se tiraba (Slice 2 · Apply).
        #
        # Va junto a `run` y bajo la MISMA condicion, y eso no es casualidad:
        # el bloque solo tiene sentido atado a una corrida identificada, que es
        # la unidad sobre la que el operador sella y aplica. Sin `run` (CLI,
        # arneses) el cuerpo del paquete sigue siendo byte a byte el de antes y
        # conserva su digest historico.
        contexto = plan_context_from_run(
            plan_doc,
            decisions_by_claim,
            documents,
            entity_anchors=run_entity_anchors(result, documents),
            provenance=run_provenance_material(result, documents, decisions_by_claim),
        )
        if contexto is not None:
            package_body[PLAN_CONTEXT_KEY] = contexto
    package_hash = sha256_hash(package_body)
    digest = package_hash["value"] if isinstance(package_hash, dict) else str(package_hash)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{workspace}--{digest}.json"
    exported = ReviewPackageExport(
        path=target,
        workspace=workspace,
        proposal_ids=tuple(doc["proposal_id"] for doc in documents),
        job_id=(run or {}).get("job_id"),
    )
    if target.exists():
        return exported
    fd, temporary = tempfile.mkstemp(prefix=".review-", suffix=".tmp", dir=output_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(package_body) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return exported


__all__ = [
    "EXPORTED_DECISIONS", "ReviewPackageExport", "export_review_package",
    "review_documents", "run_plan_material",
]
