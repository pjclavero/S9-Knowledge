# -*- coding: utf-8 -*-
"""
supersede_review.py — Herramienta genérica para superseder un review_recommendations.json.

CONTRATO:
  1. El archivo original es INMUTABLE. Se verifica su SHA-256 con --supersedes y se rechaza
     si el hash no coincide (el original fue modificado después de generar la v2 anterior).
  2. Crea un archivo NUEVO (--out). Nunca sobrescribe el original.
  3. Si --out ya existe y su supersedes_sha256 coincide con el original → idempotente (sale
     sin error, sin sobreescribir). Si --out ya existe con distinto hash de original →
     RECHAZA (second supersession conflictiva).
  4. Consolida decisiones explícitas (fichas duplicadas por `name` o resolver=use_existing
     / match_type=exact). La decisión consolidada para entidad preexistente es siempre
     DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE (nunca CREATE_NEW).
  5. Conserva historial en `consolidated_from`.
  6. Registra `reviewed_by` y `created_at` (parámetros obligatorios —no se inventan—).
  7. Registra `correction_reason` (parámetro obligatorio).
  8. Genera el SHA-256 del nuevo artefacto y lo incluye en `new_sha256`.
  9. Escritura ATÓMICA: escribe a un .tmp y renombra. Permisos 0600.
 10. Relaciones: excluidas (relations_total preservado, 0 autorizadas).
 11. NO escribe en la base de grafos. NO ejecuta ingest. NO autoriza decisiones. NO inventa reviewed_by.
 12. Validación de esquema mínima antes de escribir (fichas, source_id, workspace).
 13. Protección contra path traversal y symlinks peligrosos.
 14. Rechaza Unicode peligroso (caracteres de control en campos clave).

Uso:
  python3 supersede_review.py \\
    --in  original.json \\
    --supersedes <sha256-del-original> \\
    --out output/reviews/<workspace>/<source_id>/review_recommendations.v2.json \\
    --reviewed-by <identidad-del-revisor> \\
    --correction-reason "<razón explícita>"

Flags opcionales:
  --dry-run   Muestra el resultado sin escribir nada en disco.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFERRED = "DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE"

# Campos obligatorios en cada ficha para validación de esquema
_REQUIRED_FICHA_FIELDS = {"candidate_id", "name"}

# Caracteres de control que son indicadores de ataque Unicode
_DANGEROUS_BIDI = {"​", "‌", "‍", "‪", "‫", "‬",
                   "‭", "‮", "⁦", "⁧", "⁨", "⁩",
                   "⁪", "⁫", "⁬", "⁭", "⁮", "⁯",
                   "﻿", "\u0000"}


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _contains_dangerous_unicode(value: str) -> bool:
    for ch in value:
        if ch in _DANGEROUS_BIDI:
            return True
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf") and ch not in ("\t", "\n", "\r"):
            return True
    return False


def _validate_string_field(label: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Campo '{label}' es obligatorio y no puede estar vacío.")
    if _contains_dangerous_unicode(value):
        raise ValueError(f"Campo '{label}' contiene Unicode peligroso (Trojan Source / caracteres de control).")


def _resolve_path_safe(raw: str, allow_symlink: bool = False) -> Path:
    """Resuelve la ruta, protegiendo contra path traversal y symlinks no permitidos."""
    raw_path = Path(raw)
    # Protección extra: el string no debe contener secuencias de traversal
    if ".." in raw_path.parts:
        raise ValueError(f"Path traversal detectado en la ruta: {raw!r}")
    # El symlink debe comprobarse sobre la ruta SIN resolver: .resolve() sigue
    # los symlinks y haría que is_symlink() nunca detectase nada.
    if not allow_symlink and raw_path.is_symlink():
        raise ValueError(f"Ruta apunta a un symlink: {raw!r}. Rechazado por seguridad.")
    return raw_path.resolve()


def _is_existing_match(ficha: dict) -> bool:
    """Heurística conservadora: la entidad ya existe en el grafo."""
    return (
        ficha.get("match_type") == "exact"
        or ficha.get("resolver") == "use_existing"
        or ficha.get("recommendation") == "USE_EXISTING"
    )


# ---------------------------------------------------------------------------
# Validación de esquema
# ---------------------------------------------------------------------------

def validate_schema(data: dict) -> list[str]:
    """Valida estructura mínima. Devuelve lista de errores (vacía = OK)."""
    errors: list[str] = []
    if not isinstance(data.get("fichas"), list):
        errors.append("'fichas' debe ser una lista.")
    if not data.get("source_id"):
        errors.append("'source_id' es obligatorio.")
    if not data.get("workspace"):
        errors.append("'workspace' es obligatorio.")
    for i, f in enumerate(data.get("fichas", [])):
        for field in _REQUIRED_FICHA_FIELDS:
            if not f.get(field):
                errors.append(f"fichas[{i}] falta campo obligatorio '{field}'.")
        for field in ("name", "candidate_id"):
            val = f.get(field, "")
            if isinstance(val, str) and _contains_dangerous_unicode(val):
                errors.append(f"fichas[{i}].{field} contiene Unicode peligroso.")
    return errors


# ---------------------------------------------------------------------------
# Lógica principal de supersesión
# ---------------------------------------------------------------------------

def supersede(
    original: dict,
    supersedes_sha256: str,
    reviewed_by: str,
    correction_reason: str,
    created_at: str,
) -> dict:
    """
    Transforma el review original en una versión superseding.
    No modifica el dict `original` en su lugar.
    """
    fichas = original.get("fichas", [])
    by_name: dict[str, list[dict]] = {}
    order: list[str] = []
    for f in fichas:
        n = f.get("name", "")
        if n not in by_name:
            by_name[n] = []
            order.append(n)
        by_name[n].append(f)

    new_fichas: list[dict] = []
    consolidations: list[dict] = []

    for name in order:
        group = by_name[name]
        if len(group) > 1:
            # Duplicados → consolidar en DEFERRED_USE_EXISTING
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
            consolidations.append({
                "name": name,
                "collapsed": len(group),
                "decision": DEFERRED,
            })
        elif _is_existing_match(group[0]):
            # Entidad única pero con match existente: aplazar explícitamente
            f = dict(group[0])
            f["reviewed"] = "manual"
            f["review_note"] = "revisado sin cambio automático de la recomendación"
            new_fichas.append(f)
        else:
            # Ficha nueva sin conflicto: marcar como revisada sin cambio
            f = dict(group[0])
            f["reviewed"] = "manual"
            f["review_note"] = "revisado sin cambio automático de la recomendación"
            new_fichas.append(f)

    # Reconteo de buckets de recommendations
    buckets: dict[str, int] = {}
    for f in new_fichas:
        rec = f.get("recommendation", "UNKNOWN")
        buckets[rec] = buckets.get(rec, 0) + 1

    out = dict(original)
    out["fichas"] = new_fichas
    out["recommendations"] = buckets
    out["entities_total_original"] = original.get("entities_total")
    out["entities_total_active"] = len(new_fichas)
    out["relations_total"] = original.get("relations_total", 0)
    out["relations_authorized"] = 0
    out["supersedes_sha256"] = supersedes_sha256
    out["correction"] = {
        "generated_by": "supersede_review.py",
        "correction_reason": correction_reason,
        "reviewed_by": reviewed_by,
        "created_at": created_at,
        "consolidations": consolidations,
        "note": "Corrección de datos del review. El informe original permanece intacto.",
    }
    return out


# ---------------------------------------------------------------------------
# Escritura atómica con permisos restrictivos
# ---------------------------------------------------------------------------

def write_atomic(path: Path, data: dict) -> str:
    """Escribe data como JSON al path de forma atómica (tmp + rename). Permisos 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        tmp.rename(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 (por si rename no preservó)
    return _sha256(path)


# ---------------------------------------------------------------------------
# Punto de entrada principal (lógica separada del CLI para testabilidad)
# ---------------------------------------------------------------------------

def run(
    inp_path: str,
    supersedes_sha256: str,
    out_path: str,
    reviewed_by: str,
    correction_reason: str,
    dry_run: bool = False,
) -> dict:
    """
    Ejecuta la supersesión completa. Devuelve el informe de resultado.
    Levanta SystemExit con mensaje descriptivo si algo falla.
    """
    # 1. Validar parámetros obligatorios de auditoría
    _validate_string_field("reviewed_by", reviewed_by)
    _validate_string_field("correction_reason", correction_reason)
    _validate_string_field("supersedes_sha256", supersedes_sha256)

    # 2. Resolver rutas de forma segura
    inp = _resolve_path_safe(inp_path, allow_symlink=False)
    outp = _resolve_path_safe(out_path, allow_symlink=False)

    # 3. Verificar que el original existe y no es el mismo archivo que la salida
    if not inp.exists():
        raise SystemExit(f"ABORTADO: archivo original no encontrado: {inp}")
    if inp.resolve() == outp.resolve():
        raise SystemExit("ABORTADO: --in y --out apuntan al mismo archivo. No se puede sobrescribir el original.")

    # 4. Verificar SHA-256 del original
    real_sha = _sha256(inp)
    if real_sha != supersedes_sha256:
        raise SystemExit(
            "ABORTADO: el SHA-256 del original (%s) no coincide con --supersedes (%s). "
            "El original fue modificado o el hash es incorrecto." % (real_sha, supersedes_sha256)
        )

    # 5. Verificar idempotencia o detectar conflicto si ya existe salida
    if outp.exists() and not outp.is_symlink():
        existing = json.loads(outp.read_text(encoding="utf-8"))
        existing_supersedes = existing.get("correction", {}).get("supersedes_sha256") or existing.get("supersedes_sha256")
        if existing_supersedes == supersedes_sha256:
            # Idempotente: ya fue generado con el mismo original
            existing_sha = _sha256(outp)
            return {
                "status": "ALREADY_DONE",
                "input": str(inp),
                "supersedes_sha256": supersedes_sha256,
                "output": str(outp),
                "new_sha256": existing_sha,
                "idempotent": True,
            }
        else:
            raise SystemExit(
                "ABORTADO: --out ya existe con supersedes_sha256 diferente (%s). "
                "Una segunda supersesión conflictiva no está permitida." % existing_supersedes
            )

    # 6. Parsear y validar esquema del original
    try:
        original = json.loads(inp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"ABORTADO: JSON inválido en el original: {e}")

    errors = validate_schema(original)
    if errors:
        raise SystemExit("ABORTADO: esquema inválido en el original:\n  " + "\n  ".join(errors))

    # 7. Calcular created_at en UTC
    created_at = datetime.now(timezone.utc).isoformat()

    # 8. Ejecutar transformación
    v2 = supersede(original, supersedes_sha256, reviewed_by, correction_reason, created_at)

    # 9. Validar esquema del resultado
    errors_out = validate_schema(v2)
    if errors_out:
        raise SystemExit("ABORTADO: esquema inválido en el resultado generado:\n  " + "\n  ".join(errors_out))

    # 10. Calcular SHA-256 del resultado (antes de escribir, sobre el JSON serializado)
    text_v2 = json.dumps(v2, ensure_ascii=False, indent=2)
    new_sha = _sha256_str(text_v2)

    # 11. Verificar que el original no fue tocado (invariante post-transformación)
    real_sha_post = _sha256(inp)
    if real_sha_post != supersedes_sha256:
        raise SystemExit(
            "ABORTADO: el archivo original fue modificado DURANTE la ejecución. "
            "Abortando para preservar integridad."
        )

    # 12. Construir informe
    report = {
        "status": "OK",
        "input": str(inp),
        "supersedes_sha256": supersedes_sha256,
        "input_sha256_verified": True,
        "original_modified": False,
        "output": str(outp),
        "new_sha256": new_sha,
        "entities_active": v2["entities_total_active"],
        "recommendations": v2["recommendations"],
        "relations_authorized": 0,
        "consolidations": v2["correction"]["consolidations"],
        "reviewed_by": reviewed_by,
        "created_at": v2["correction"]["created_at"],
        "dry_run": dry_run,
    }

    if dry_run:
        report["note"] = "dry-run: no se escribió ningún archivo"
        return report

    # 13. Escritura atómica
    written_sha = write_atomic(outp, v2)
    # Verificar que el sha coincide (escritura correcta)
    if written_sha != _sha256_str(text_v2):
        raise SystemExit("ABORTADO: SHA-256 post-escritura no coincide. Archivo posiblemente corrupto.")

    # 14. Verificar invariante del original después de escribir
    real_sha_final = _sha256(inp)
    if real_sha_final != supersedes_sha256:
        raise SystemExit(
            "ABORTADO: el archivo original fue modificado DESPUÉS de la escritura. "
            "Investigar posible condición de carrera."
        )

    report["new_sha256"] = written_sha
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Genera una versión superseding (v2) de un review_recommendations.json."
    )
    ap.add_argument("--in", dest="inp", required=True,
                    help="Ruta al review original (inmutable).")
    ap.add_argument("--supersedes", required=True,
                    help="SHA-256 esperado del original.")
    ap.add_argument("--out", required=True,
                    help="Ruta de salida para el nuevo review (v2).")
    ap.add_argument("--reviewed-by", required=True,
                    help="Identidad del revisor (p.ej. 'manual-cli:ana'). Obligatorio.")
    ap.add_argument("--correction-reason", required=True,
                    help="Motivo explícito de la corrección. Obligatorio.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Muestra el resultado sin escribir en disco.")
    args = ap.parse_args()

    try:
        report = run(
            inp_path=args.inp,
            supersedes_sha256=args.supersedes,
            out_path=args.out,
            reviewed_by=args.reviewed_by,
            correction_reason=args.correction_reason,
            dry_run=args.dry_run,
        )
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
