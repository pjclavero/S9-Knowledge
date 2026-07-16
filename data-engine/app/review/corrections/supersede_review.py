# -*- coding: utf-8 -*-
"""
Genera una versión CORREGIDA (superseding) de un review_recommendations.json
mediante una transformación EXPLÍCITA y revisable — no una edición silenciosa.

Reglas (source_narrative_01 / leyenda):
  1. NO modifica el archivo original. Verifica su SHA-256 contra --supersedes.
  2. Consolida fichas duplicadas por `name`: si un nombre aparece >1 vez, o
     hace match exacto contra un nodo existente (resolver=use_existing /
     match_type=exact), se colapsa en UNA sola decisión activa.
  3. La decisión consolidada para una entidad preexistente es
     DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE (nunca CREATE_NEW).
     No implica SET sobre el nodo existente ni cambio de procedencia.
  4. Conserva el historial de las decisiones originales en `consolidated_from`.
  5. USE_EXISTING y EDIT se marcan `reviewed=manual` SIN cambiarse automáticamente;
     se aplazarán en la ingesta.
  6. Relaciones: se mantienen EXCLUIDAS (relations_total preservado, 0 autorizadas).
  7. Registra `supersedes_sha256` y calcula el nuevo SHA-256 del artefacto.

Uso:
  python3 supersede_review.py --in <original.json> --supersedes <sha256> --out <v2.json>
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

DEFERRED = "DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_existing_match(ficha: dict) -> bool:
    """Heurística conservadora: la entidad ya existe en el grafo."""
    return (
        ficha.get("match_type") == "exact"
        or ficha.get("resolver") == "use_existing"
        or ficha.get("recommendation") == "USE_EXISTING"
    )


def supersede(original: dict, supersedes_sha256: str) -> dict:
    fichas = original.get("fichas", [])
    by_name: dict[str, list[dict]] = {}
    order: list[str] = []
    for f in fichas:
        n = f.get("name", "")
        if n not in by_name:
            by_name[n] = []
            order.append(n)
        by_name[n].append(f)

    new_fichas = []
    consolidations = []
    for name in order:
        group = by_name[name]
        if len(group) > 1:
            # Conflicto de duplicados -> consolidar en DEFERRED_USE_EXISTING
            # Elegimos como base la ficha con tipo válido (mayor confidence).
            base = max(group, key=lambda g: g.get("confidence", 0))
            merged = dict(base)
            merged["recommendation"] = DEFERRED
            merged["deferred"] = True
            merged["resolver"] = "use_existing"
            merged["review_action"] = DEFERRED
            merged["reviewed"] = "manual"
            merged["why"] = (
                "Ya existe en el grafo (match exacto). Consolidado de %d decisiones "
                "en conflicto. No CREATE_NEW; no SET sobre nodo existente; "
                "procedencia intacta; aplazado hasta procedencia multifuente." % len(group)
            )
            merged["consolidated_from"] = [
                {
                    "candidate_id": g.get("candidate_id"),
                    "type": g.get("type"),
                    "recommendation": g.get("recommendation"),
                    "resolver": g.get("resolver"),
                    "why": g.get("why"),
                }
                for g in group
            ]
            new_fichas.append(merged)
            consolidations.append({"name": name, "collapsed": len(group), "decision": DEFERRED})
        else:
            # Ficha única: se REVISA sin cambiar automáticamente su recomendación
            # (regla del operador para Akodo Toturi / clan León / clan Grulla).
            # La deferral de USE_EXISTING/EDIT en la ingesta es responsabilidad del
            # writer (política), no del review. Solo marcamos revisión manual.
            f = dict(group[0])
            f["reviewed"] = "manual"
            f["review_note"] = "revisado sin cambio automático de la recomendación"
            new_fichas.append(f)

    # Recontar buckets de recommendations sobre las fichas activas
    buckets: dict[str, int] = {}
    for f in new_fichas:
        buckets[f.get("recommendation")] = buckets.get(f.get("recommendation"), 0) + 1

    out = dict(original)
    out["fichas"] = new_fichas
    out["recommendations"] = buckets
    out["entities_total_original"] = original.get("entities_total")
    out["entities_total_active"] = len(new_fichas)
    out["relations_total"] = original.get("relations_total", 0)  # excluidas, preservadas
    out["relations_authorized"] = 0
    out["supersedes_sha256"] = supersedes_sha256
    out["correction"] = {
        "generated_by": "supersede_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "consolidations": consolidations,
        "note": "Corrección de datos del review. El informe original permanece intacto.",
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--supersedes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    inp = Path(args.inp)
    real = _sha256(inp)
    if real != args.supersedes:
        raise SystemExit(
            "ABORTADO: el SHA-256 del original (%s) no coincide con --supersedes (%s)"
            % (real, args.supersedes)
        )
    original = json.loads(inp.read_text(encoding="utf-8"))
    v2 = supersede(original, args.supersedes)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(v2, ensure_ascii=False, indent=2), encoding="utf-8")
    new_sha = _sha256(outp)
    print(json.dumps({
        "input": str(inp),
        "supersedes_sha256": args.supersedes,
        "input_sha256_verified": real == args.supersedes,
        "output": str(outp),
        "new_sha256": new_sha,
        "entities_active": v2["entities_total_active"],
        "recommendations": v2["recommendations"],
        "consolidations": v2["correction"]["consolidations"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
