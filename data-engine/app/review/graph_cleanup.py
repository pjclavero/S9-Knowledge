# -*- coding: utf-8 -*-
"""Limpieza controlada y REVERSIBLE del grafo Neo4j (Prioridad 5).

Complementa a `review/audit_graph.py` (que AUDITA pero no corrige): este modulo
planifica y, con doble autorizacion, APLICA correcciones de calidad del grafo,
siempre de forma reversible y en lotes.

Principio rector (docs/28 y dosier §17): **auto-arreglar solo metadatos seguros;
todo lo destructivo o semantico requiere revision humana**. Por eso las clases:

  * ``AUTO_SAFE``        — backfill de procedencia en nodos historicos sin
                           ``source_id``/``source_kind``. Solo escribe METADATOS,
                           es 100 % reversible (marcador de migracion) y no borra
                           ni fusiona nada. UNICA clase auto-aplicable.
  * ``REVIEW_REMAP``     — relaciones con tipo fuera del vocabulario que TIENEN un
                           mapeo canonico conocido. Se PROPONE el remapeo, pero
                           cambia semantica: requiere revision. NUNCA se auto-aplica.
  * ``REVIEW_REQUIRED``  — relaciones invalidas sin mapeo (candidatas a borrado) y
                           fusiones de duplicados. Destructivo: SOLO humano.

Garantias DURAS
---------------
  * DRY-RUN por defecto: sin ``apply=True`` no se escribe una sola propiedad.
  * DOBLE LLAVE para escribir: ``apply=True`` **y** ``S9K_ALLOW_GRAPH_MIGRATION=true``
    (env). Falta cualquiera de las dos -> se rechaza (fail-closed), igual que la
    ingesta real.
  * BACKUP OBLIGATORIO: ``apply`` exige un ``backup_ref`` no vacio (referencia a un
    backup verificado). Sin backup no se aplica.
  * SOLO ``AUTO_SAFE`` es auto-aplicable. Las clases de revision se rechazan en
    ``apply`` aunque se pidan: no hay via para que un agente borre/fusione solo.
  * REVERSIBLE: cada aplicacion marca los nodos tocados con ``_mig`` = id de
    migracion y emite un manifiesto + rollback exacto (solo revierte lo que ese id
    escribio). ``rollback_migration`` deshace por ese id.
  * SOLO LECTURA para planificar: ``plan_cleanup`` no escribe nada.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# --- Clases de hallazgo ----------------------------------------------------
CLASS_AUTO_SAFE = "AUTO_SAFE"
CLASS_REVIEW_REMAP = "REVIEW_REMAP"
CLASS_REVIEW_REQUIRED = "REVIEW_REQUIRED"

# Marcador de procedencia retroactiva para nodos historicos (docs/28).
LEGACY_SOURCE_ID = "historical_legacy"
LEGACY_SOURCE_KIND = "legacy"

# Doble llave (env) — espejo de S9K_ALLOW_REAL_INGEST para la ingesta.
GRAPH_MIGRATION_ENV = "S9K_ALLOW_GRAPH_MIGRATION"

CLEANUP_VERSION = "graph-cleanup-1.0.0"


class GraphCleanupError(RuntimeError):
    """Error fatal de configuracion/autorizacion de la limpieza."""


# ---------------------------------------------------------------------------
# Utilidades deterministas
# ---------------------------------------------------------------------------
def _migration_id(kind: str, payload: Any) -> str:
    """Id determinista y corto de una migracion (kind + contenido)."""
    blob = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"


def _canonical_relation(rel_type: str) -> Optional[str]:
    """Devuelve el tipo canonico de una relacion, o None si no hay mapeo/valido.

    Reutiliza el normalizador del esquema (no duplica el vocabulario). Un tipo que
    ya es valido se devuelve tal cual; uno con alias conocido se mapea; uno sin
    mapeo devuelve None (candidato a revision/borrado, jamas auto).
    """
    from schemas.rpg_schema import ALLOWED_RELATION_TYPES  # import perezoso

    if rel_type in ALLOWED_RELATION_TYPES:
        return rel_type
    try:
        from schemas.rpg_schema import normalize_relation_type
    except Exception:  # noqa: BLE001 - si no existe normalizador, no hay remap
        return None
    try:
        mapped = normalize_relation_type(rel_type)
    except Exception:  # noqa: BLE001 - normalizador estricto lanza si invalido
        return None
    if mapped and mapped in ALLOWED_RELATION_TYPES and mapped != rel_type:
        return mapped
    return None


# ---------------------------------------------------------------------------
# Modelo del plan
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CleanupItem:
    """Un hallazgo clasificado con su accion propuesta (forward + rollback)."""

    finding: str                 # tipo de hallazgo (missing_provenance, bad_relation, duplicate)
    klass: str                   # CLASS_*
    summary: str                 # descripcion legible
    count: int                   # cuantos elementos afecta
    forward_cypher: str          # Cypher propuesto (parametrizado)
    params: dict                 # parametros del Cypher
    rollback_cypher: str         # Cypher inverso exacto
    migration_id: str            # id determinista

    def to_dict(self) -> dict:
        return {
            "finding": self.finding,
            "class": self.klass,
            "summary": self.summary,
            "count": self.count,
            "forward_cypher": self.forward_cypher,
            "params": self.params,
            "rollback_cypher": self.rollback_cypher,
            "migration_id": self.migration_id,
            "auto_applicable": self.klass == CLASS_AUTO_SAFE,
        }


@dataclass(frozen=True)
class CleanupPlan:
    """Plan completo de limpieza (SOLO LECTURA; no ha escrito nada)."""

    items: tuple = field(default_factory=tuple)
    graph_totals: dict = field(default_factory=dict)   # {nodes, relationships}
    generated_at: float = 0.0

    @property
    def auto_items(self) -> list:
        return [it for it in self.items if it.klass == CLASS_AUTO_SAFE]

    @property
    def review_items(self) -> list:
        return [it for it in self.items if it.klass != CLASS_AUTO_SAFE]

    def to_dict(self) -> dict:
        return {
            "version": CLEANUP_VERSION,
            "graph_totals": self.graph_totals,
            "auto_safe": [it.to_dict() for it in self.auto_items],
            "review_required": [it.to_dict() for it in self.review_items],
        }

    def to_report_md(self) -> str:
        lines = [
            "# Plan de limpieza del grafo (dry-run)",
            "",
            f"- Version: `{CLEANUP_VERSION}`",
            f"- Nodos: {self.graph_totals.get('nodes', '?')} · "
            f"Relaciones: {self.graph_totals.get('relationships', '?')}",
            "",
            "> DRY-RUN: este plan NO ha escrito nada. Solo `AUTO_SAFE` es "
            "auto-aplicable (metadatos, reversible). El resto exige revision humana.",
            "",
            "## Auto-aplicable (AUTO_SAFE)",
            "",
        ]
        if not self.auto_items:
            lines += ["_(ninguno)_", ""]
        for it in self.auto_items:
            lines += [
                f"### {it.finding} — {it.count} elementos",
                f"- {it.summary}",
                f"- migration_id: `{it.migration_id}`",
                f"- forward: `{it.forward_cypher}`",
                f"- rollback: `{it.rollback_cypher}`",
                "",
            ]
        lines += ["## Requiere revision humana", ""]
        if not self.review_items:
            lines += ["_(ninguno)_", ""]
        for it in self.review_items:
            lines += [
                f"### [{it.klass}] {it.finding} — {it.count} elementos",
                f"- {it.summary}",
                f"- propuesta (NO auto): `{it.forward_cypher}`",
                "",
            ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Planificacion (SOLO LECTURA)
# ---------------------------------------------------------------------------
def _graph_totals(session) -> dict:
    nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return {"nodes": int(nodes), "relationships": int(rels)}


def _plan_missing_provenance(session) -> Optional[CleanupItem]:
    """AUTO_SAFE: nodos con canonical_name pero sin source_id -> backfill legacy."""
    rec = session.run(
        "MATCH (n) WHERE n.canonical_name IS NOT NULL "
        "AND (n.source_id IS NULL OR n.source_id = '') "
        "RETURN count(n) AS c"
    ).single()
    count = int(rec["c"]) if rec else 0
    if count == 0:
        return None
    mig = _migration_id("legacy_provenance", {"legacy": LEGACY_SOURCE_ID})
    forward = (
        "MATCH (n) WHERE n.canonical_name IS NOT NULL "
        "AND (n.source_id IS NULL OR n.source_id = '') "
        "SET n.source_id = $sid, n.source_kind = $skind, n._mig = $mig "
        "RETURN count(n) AS updated"
    )
    rollback = (
        "MATCH (n) WHERE n._mig = $mig "
        "REMOVE n.source_id, n.source_kind, n._mig "
        "RETURN count(n) AS reverted"
    )
    return CleanupItem(
        finding="missing_provenance",
        klass=CLASS_AUTO_SAFE,
        summary=(
            f"{count} nodos historicos sin source_id -> se les asigna "
            f"source_id='{LEGACY_SOURCE_ID}', source_kind='{LEGACY_SOURCE_KIND}' "
            "(solo metadatos, reversible por marcador _mig)."
        ),
        count=count,
        forward_cypher=forward,
        params={"sid": LEGACY_SOURCE_ID, "skind": LEGACY_SOURCE_KIND, "mig": mig},
        rollback_cypher=rollback,
        migration_id=mig,
    )


def _plan_bad_relations(session) -> list:
    """Relaciones con tipo fuera del vocabulario. REMAP (revision) o REQUIRED."""
    from schemas.rpg_schema import ALLOWED_RELATION_TYPES  # import perezoso

    recs = session.run(
        "MATCH ()-[r]->() WHERE NOT type(r) IN $allowed "
        "RETURN type(r) AS t, count(r) AS c",
        {"allowed": list(ALLOWED_RELATION_TYPES)},
    ).data()
    items: list = []
    for r in recs:
        rel_type = r["t"]
        count = int(r["c"])
        canonical = _canonical_relation(rel_type)
        if canonical == rel_type:
            # Ya es un tipo valido (no deberia llegar aqui: el auditor filtra por
            # NOT type(r) IN allowed). No hay nada que corregir -> se ignora.
            continue
        if canonical:
            mig = _migration_id("remap_relation", {"from": rel_type, "to": canonical})
            forward = (
                f"MATCH (a)-[r:`{rel_type}`]->(b) "
                f"CREATE (a)-[r2:`{canonical}`]->(b) SET r2 = properties(r) "
                "DELETE r"
            )
            items.append(CleanupItem(
                finding="bad_relation",
                klass=CLASS_REVIEW_REMAP,
                summary=(
                    f"Relacion '{rel_type}' ({count}) fuera del vocabulario pero con "
                    f"mapeo canonico a '{canonical}'. Cambia semantica -> revision."
                ),
                count=count,
                forward_cypher=forward,
                params={},
                rollback_cypher="(revertir via backup; el remap crea/borra relaciones)",
                migration_id=mig,
            ))
        else:
            mig = _migration_id("bad_relation", {"type": rel_type})
            items.append(CleanupItem(
                finding="bad_relation",
                klass=CLASS_REVIEW_REQUIRED,
                summary=(
                    f"Relacion '{rel_type}' ({count}) sin tipo valido ni mapeo "
                    "conocido. Candidata a borrado/correccion manual."
                ),
                count=count,
                forward_cypher=f"MATCH ()-[r:`{rel_type}`]->() DELETE r  // requiere revision",
                params={},
                rollback_cypher="(revertir via backup; DELETE es destructivo)",
                migration_id=mig,
            ))
    return items


def _plan_duplicates(session) -> Optional[CleanupItem]:
    """Duplicados por canonical_name normalizado. Siempre REVIEW_REQUIRED (fusion)."""
    recs = session.run(
        "MATCH (n) WHERE n.canonical_name IS NOT NULL "
        "RETURN n.canonical_name AS name LIMIT 5000"
    ).data()
    import unicodedata

    def _norm(t: str) -> str:
        nfkd = unicodedata.normalize("NFKD", t or "")
        return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    groups: dict[str, int] = {}
    for r in recs:
        groups[_norm(r.get("name", ""))] = groups.get(_norm(r.get("name", "")), 0) + 1
    dup_keys = [k for k, v in groups.items() if v > 1]
    if not dup_keys:
        return None
    mig = _migration_id("duplicates", {"keys": sorted(dup_keys)})
    return CleanupItem(
        finding="duplicate_candidate",
        klass=CLASS_REVIEW_REQUIRED,
        summary=(
            f"{len(dup_keys)} grupos de nombres canonicos duplicados. La fusion "
            "elige nodo superviviente y reconecta relaciones -> SOLO revision humana."
        ),
        count=len(dup_keys),
        forward_cypher="(fusion manual: elegir superviviente, reconectar, borrar duplicado)",
        params={"keys": sorted(dup_keys)},
        rollback_cypher="(revertir via backup; la fusion es destructiva)",
        migration_id=mig,
    )


def plan_cleanup(session) -> CleanupPlan:
    """Construye el plan de limpieza. SOLO LECTURA: no escribe nada en el grafo."""
    items: list = []
    prov = _plan_missing_provenance(session)
    if prov is not None:
        items.append(prov)
    items.extend(_plan_bad_relations(session))
    dup = _plan_duplicates(session)
    if dup is not None:
        items.append(dup)
    return CleanupPlan(
        items=tuple(items),
        graph_totals=_graph_totals(session),
        generated_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Aplicacion (FAIL-CLOSED, doble llave, solo AUTO_SAFE)
# ---------------------------------------------------------------------------
@dataclass
class ApplyResult:
    applied: bool
    manifest: dict
    message: str


def _env_allows_migration(env: Optional[dict]) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(GRAPH_MIGRATION_ENV, "")).strip().lower() == "true"


def apply_plan(
    session,
    plan: CleanupPlan,
    *,
    apply: bool = False,
    backup_ref: str = "",
    env: Optional[dict] = None,
) -> ApplyResult:
    """Aplica SOLO los items AUTO_SAFE del plan, fail-closed.

    Requiere, TODO a la vez (si falta cualquiera -> no escribe):
      * ``apply=True``;
      * ``S9K_ALLOW_GRAPH_MIGRATION=true`` en el entorno;
      * ``backup_ref`` no vacio (referencia a un backup verificado).

    Las clases de revision NUNCA se aplican aqui. Devuelve un manifiesto con lo
    aplicado (o lo que se aplicaria en dry-run) y su rollback exacto.
    """
    auto = plan.auto_items
    manifest = {
        "version": CLEANUP_VERSION,
        "backup_ref": backup_ref,
        "auto_items": [it.to_dict() for it in auto],
        "graph_totals_before": plan.graph_totals,
        "applied": False,
        "results": [],
    }

    if not apply:
        return ApplyResult(False, manifest, "DRY-RUN: no se ha escrito nada (apply=False).")

    # --- Puertas fail-closed ---
    if not _env_allows_migration(env):
        raise GraphCleanupError(
            f"escritura bloqueada: falta {GRAPH_MIGRATION_ENV}=true (doble llave)."
        )
    if not backup_ref or not str(backup_ref).strip():
        raise GraphCleanupError(
            "escritura bloqueada: backup_ref obligatorio (no se aplica sin backup verificado)."
        )
    if not auto:
        return ApplyResult(False, manifest, "Nada AUTO_SAFE que aplicar.")

    results = []
    for it in auto:
        rec = session.run(it.forward_cypher, it.params).single()
        updated = int(rec[list(rec.keys())[0]]) if rec else 0
        results.append({
            "migration_id": it.migration_id,
            "finding": it.finding,
            "updated": updated,
            "rollback_cypher": it.rollback_cypher,
            "rollback_params": {"mig": it.params.get("mig")},
        })
    manifest["applied"] = True
    manifest["results"] = results
    return ApplyResult(True, manifest, f"Aplicados {len(results)} items AUTO_SAFE.")


def rollback_migration(
    session,
    manifest: dict,
    *,
    apply: bool = False,
    env: Optional[dict] = None,
) -> dict:
    """Revierte una aplicacion previa usando los rollback exactos del manifiesto.

    Mismo fail-closed que ``apply_plan`` (doble llave). Cada rollback usa el
    marcador ``_mig`` del item, asi que solo deshace lo que esa migracion escribio.
    """
    out = {"reverted": [], "applied": False}
    if not apply:
        out["message"] = "DRY-RUN: no se revierte nada (apply=False)."
        return out
    if not _env_allows_migration(env):
        raise GraphCleanupError(f"rollback bloqueado: falta {GRAPH_MIGRATION_ENV}=true.")
    for res in manifest.get("results", []):
        rec = session.run(res["rollback_cypher"], res.get("rollback_params", {})).single()
        reverted = int(rec[list(rec.keys())[0]]) if rec else 0
        out["reverted"].append({"migration_id": res["migration_id"], "reverted": reverted})
    out["applied"] = True
    return out


__all__ = [
    "CLASS_AUTO_SAFE",
    "CLASS_REVIEW_REMAP",
    "CLASS_REVIEW_REQUIRED",
    "GRAPH_MIGRATION_ENV",
    "CLEANUP_VERSION",
    "GraphCleanupError",
    "CleanupItem",
    "CleanupPlan",
    "ApplyResult",
    "plan_cleanup",
    "apply_plan",
    "rollback_migration",
]
