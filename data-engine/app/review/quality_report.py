"""Generador de quality report para outputs del pipeline de revisión.

Analiza los JSON de output/reviews/<workspace>/<source_id>/ y produce:
  quality_report.json  — métricas estructuradas
  quality_report.md    — informe legible con veredicto LOW/MEDIUM/HIGH risk

Detecciones sobre AUTOAPROBADOS:
  - single-token (una sola palabra)
  - stopwords
  - confidence en umbral bajo (0.85-0.87)
  - evidence corta (< 30 chars)
  - nombre de 1 sola palabra en minúscula
  - top 20 por tipo de entidad
  - extractor usado (si pipeline_state.json lo registra)
  - riesgo de duplicados (nombres muy similares entre autoaprobados)
  - origin=external sin validated_by_s9k (flags de riesgo)

Veredicto final: LOW / MEDIUM / HIGH risk
"""
from __future__ import annotations
import json
import logging
import unicodedata
from collections import Counter
from pathlib import Path

log = logging.getLogger(__name__)

# Umbral de confidence que consideramos "en el filo"
CONF_THRESHOLD_LOW = 0.85
CONF_THRESHOLD_HIGH = 0.87

# Longitud mínima de evidence
EVIDENCE_MIN_LEN = 30

# Stopwords fallback mínimo embebido (por si falla el import)
_FALLBACK_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "de", "del", "al", "en", "es",
    "que", "y", "a", "por", "con", "si", "no", "se", "me", "te", "su",
    "ya", "yo", "tu", "le", "lo", "como", "todo", "toda", "este", "esta",
    "pero", "hay", "ser", "era", "fue", "son", "las", "uno", "dos", "tres",
}

def _load_stopwords() -> set[str]:
    """Importa stopwords del módulo del proyecto; fallback a lista mínima embebida."""
    try:
        import sys
        from pathlib import Path as _Path
        _app = _Path(__file__).resolve().parents[1]
        if str(_app) not in sys.path:
            sys.path.insert(0, str(_app))
        from review.stopwords import STOPWORDS_ES, _normalize as _sw_norm
        return STOPWORDS_ES
    except Exception as e:
        log.warning("No se pudo importar stopwords.py (%s); usando fallback mínimo.", e)
        return _fallback_stopwords_normalized()

def _fallback_stopwords_normalized() -> set[str]:
    def _n(t):
        nfkd = unicodedata.normalize("NFKD", t.lower())
        return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return {_n(w) for w in _FALLBACK_STOPWORDS}

def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").strip()


def _is_single_token(name: str) -> bool:
    return len(name.strip().split()) == 1


def _is_stopword_name(name: str, stopwords: set[str]) -> bool:
    norm = _normalize(name)
    return norm in stopwords


def _is_low_confidence(conf: float) -> bool:
    return CONF_THRESHOLD_LOW <= conf <= CONF_THRESHOLD_HIGH


def _is_short_evidence(evidence: str) -> bool:
    return len(evidence.strip()) < EVIDENCE_MIN_LEN


def _is_lowercase_single_word(name: str) -> bool:
    parts = name.strip().split()
    return len(parts) == 1 and parts[0] == parts[0].lower() and parts[0].isalpha()


def _similar_names(a: str, b: str) -> bool:
    """Detecta nombres muy similares por normalización."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    # Check if one starts with the other (truncated match)
    if len(na) >= 4 and len(nb) >= 4:
        short, long_ = (na, nb) if len(na) < len(nb) else (nb, na)
        if long_.startswith(short) and len(long_) - len(short) <= 5:
            return True
    return False


def _detect_duplicate_risk(approved: list[dict]) -> list[dict]:
    """Detecta pares de autoaprobados con nombres muy similares."""
    entities = [a for a in approved if a.get("kind") == "entity" and a.get("name")]
    pairs = []
    names = [(i, e.get("name", "")) for i, e in enumerate(entities)]
    checked = set()
    for i, (idx_a, name_a) in enumerate(names):
        for idx_b, name_b in names[i+1:]:
            key = (min(name_a, name_b), max(name_a, name_b))
            if key in checked:
                continue
            checked.add(key)
            if _similar_names(name_a, name_b):
                pairs.append({
                    "name_a": name_a,
                    "name_b": name_b,
                    "normalized_a": _normalize(name_a),
                    "normalized_b": _normalize(name_b),
                })
    return pairs


def _load_pipeline_state(source_dir: Path) -> dict:
    path = source_dir / "pipeline_state.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def generate(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Genera quality_report.json y quality_report.md. Retorna path del .md."""
    source_dir = repo_root / "output" / "reviews" / workspace / source_id

    if not source_dir.exists():
        raise FileNotFoundError(f"Directorio de outputs no encontrado: {source_dir}")

    # Cargar payload aprobado
    payload_path = source_dir / "approved_payload.json"
    if not payload_path.exists():
        raise FileNotFoundError(f"approved_payload.json no encontrado en {source_dir}")

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    approved = payload.get("approved", [])
    metadata = payload.get("metadata", {})

    # Cargar review_queue y rejected si existen
    review_queue: list[dict] = []
    rq_path = source_dir / "review_queue.json"
    if rq_path.exists():
        try:
            review_queue = json.loads(rq_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    rejected: list[dict] = []
    rej_path = source_dir / "rejected.json"
    if rej_path.exists():
        try:
            rejected = json.loads(rej_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    total = len(approved) + len(review_queue) + len(rejected)
    stopwords = _load_stopwords()

    # Análisis de sospechosos entre autoaprobados
    suspects: list[dict] = []
    for item in approved:
        name = item.get("name") or ""
        conf = item.get("confidence", 0.0)
        evidence = item.get("evidence", "")
        flags = []

        if _is_stopword_name(name, stopwords):
            flags.append("stopword")
        if _is_single_token(name):
            flags.append("single_token")
        if _is_low_confidence(conf):
            flags.append("threshold_confidence")
        if _is_short_evidence(evidence):
            flags.append("short_evidence")
        if _is_lowercase_single_word(name):
            flags.append("lowercase_single_word")

        if flags:
            suspects.append({
                "name": name,
                "entity_type": item.get("entity_type"),
                "confidence": conf,
                "evidence_len": len(evidence.strip()),
                "flags": flags,
            })

    # Top 20 autoaprobados por tipo
    type_counts = Counter(
        item.get("entity_type", "?") for item in approved if item.get("kind") == "entity"
    )
    top_types = [{"type": t, "count": c} for t, c in type_counts.most_common(20)]

    # Riesgo de duplicados
    dup_pairs = _detect_duplicate_risk(approved)

    # Extractor usado (desde pipeline_state.json)
    pipeline_state = _load_pipeline_state(source_dir)
    extractor_used = None
    if "extract" in pipeline_state:
        ext_details = pipeline_state["extract"].get("details", {})
        extractor_used = ext_details.get("extractor") or ext_details.get("mode")

    # origin=external sin validated (flags en el payload)
    external_unvalidated = [
        item.get("name", item.get("candidate_id", "?"))
        for item in approved
        if item.get("origin", metadata.get("origin", "local")) == "external"
        and not item.get("validated_by_s9k", False)
    ]

    # ── Veredicto ───────────────────────────────────────────────────────────
    risk_reasons: list[str] = []
    risk_level = "LOW"

    stopword_suspects = [s for s in suspects if "stopword" in s["flags"]]
    single_lower_suspects = [s for s in suspects if "lowercase_single_word" in s["flags"]]
    threshold_suspects = [s for s in suspects if "threshold_confidence" in s["flags"]]
    short_ev_suspects = [s for s in suspects if "short_evidence" in s["flags"]]

    if stopword_suspects:
        risk_reasons.append(f"{len(stopword_suspects)} autoaprobados son stopwords: {[s['name'] for s in stopword_suspects[:5]]}")
        risk_level = "HIGH"
    if single_lower_suspects:
        risk_reasons.append(f"{len(single_lower_suspects)} autoaprobados: nombre minúscula una palabra: {[s['name'] for s in single_lower_suspects[:5]]}")
        if risk_level == "LOW":
            risk_level = "MEDIUM"
    if len(threshold_suspects) > 5:
        risk_reasons.append(f"{len(threshold_suspects)} autoaprobados en umbral de confianza (0.85-0.87)")
        if risk_level == "LOW":
            risk_level = "MEDIUM"
    if len(short_ev_suspects) > 3:
        risk_reasons.append(f"{len(short_ev_suspects)} autoaprobados con evidence < {EVIDENCE_MIN_LEN} chars")
        if risk_level == "LOW":
            risk_level = "MEDIUM"
    if dup_pairs:
        risk_reasons.append(f"{len(dup_pairs)} pares de posibles duplicados entre autoaprobados")
        if risk_level == "LOW":
            risk_level = "MEDIUM"
    if external_unvalidated:
        risk_reasons.append(f"{len(external_unvalidated)} candidatos externos sin validated_by_s9k")
        risk_level = "HIGH"

    if total > 0:
        pct_auto = len(approved) / total * 100
        if pct_auto > 95 and total > 20:
            risk_reasons.append(f"Tasa de auto-aprobación muy alta: {pct_auto:.0f}%")
            if risk_level == "LOW":
                risk_level = "MEDIUM"

    if not risk_reasons:
        risk_reasons.append("No se detectaron señales de riesgo significativas.")

    # ── Construir JSON ────────────────────────────────────────────────────────
    report = {
        "workspace": workspace,
        "source_id": source_id,
        "schema_version": metadata.get("schema_version", "?"),
        "generated_at": metadata.get("generated_at", ""),
        "extractor_used": extractor_used,
        "counts": {
            "total": total,
            "approved": len(approved),
            "review_queue": len(review_queue),
            "rejected": len(rejected),
            "pct_approved": round(len(approved) / total * 100, 1) if total else 0,
            "pct_review": round(len(review_queue) / total * 100, 1) if total else 0,
            "pct_rejected": round(len(rejected) / total * 100, 1) if total else 0,
        },
        "suspects": suspects,
        "suspect_summary": {
            "total_suspects": len(suspects),
            "stopwords": len(stopword_suspects),
            "single_token": len([s for s in suspects if "single_token" in s["flags"]]),
            "threshold_confidence": len(threshold_suspects),
            "short_evidence": len(short_ev_suspects),
            "lowercase_single_word": len(single_lower_suspects),
        },
        "top_types": top_types,
        "duplicate_risk_pairs": dup_pairs,
        "external_unvalidated": external_unvalidated,
        "risk": {
            "level": risk_level,
            "reasons": risk_reasons,
        },
    }

    # Guardar JSON
    json_path = source_dir / "quality_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Generar MD
    md_path = source_dir / "quality_report.md"
    _write_md(md_path, report, workspace, source_id)

    log.info("quality_report generado: risk=%s, suspects=%d", risk_level, len(suspects))
    return md_path


def _write_md(md_path: Path, report: dict, workspace: str, source_id: str):
    risk = report["risk"]["level"]
    risk_emoji = {"LOW": "OK", "MEDIUM": "ATENCION", "HIGH": "ALTO RIESGO"}.get(risk, risk)
    counts = report["counts"]
    ss = report["suspect_summary"]
    lines = [
        f"# Quality Report — {workspace} / {source_id}",
        "",
        f"Generado: {report.get('generated_at', '')}",
        f"Extractor usado: {report.get('extractor_used') or 'desconocido'}",
        f"Schema version: {report.get('schema_version', '?')}",
        "",
        f"## Veredicto: {risk} [{risk_emoji}]",
        "",
    ]
    for r in report["risk"]["reasons"]:
        lines.append(f"- {r}")
    lines += [
        "",
        "## Distribución de candidatos",
        "",
        f"| Estado | Cantidad | % |",
        f"|--------|----------|----|",
        f"| Auto-aprobados | {counts['approved']} | {counts['pct_approved']}% |",
        f"| Revisión humana | {counts['review_queue']} | {counts['pct_review']}% |",
        f"| Rechazados | {counts['rejected']} | {counts['pct_rejected']}% |",
        f"| **Total** | **{counts['total']}** | |",
        "",
        "## Sospechosos entre autoaprobados",
        "",
        f"| Flag | Cantidad |",
        f"|------|----------|",
        f"| Stopwords | {ss['stopwords']} |",
        f"| Single token | {ss['single_token']} |",
        f"| Confidence en umbral (0.85-0.87) | {ss['threshold_confidence']} |",
        f"| Evidence corta (<30 chars) | {ss['short_evidence']} |",
        f"| Nombre 1 palabra minúscula | {ss['lowercase_single_word']} |",
        f"| **Total sospechosos** | **{ss['total_suspects']}** |",
        "",
    ]

    suspects = report.get("suspects", [])
    if suspects:
        lines += ["### Detalle de sospechosos (primeros 30)", ""]
        for s in suspects[:30]:
            flags_str = ", ".join(s["flags"])
            ev_len = s.get("evidence_len", 0)
            lines.append(
                f"- **{s['name']}** ({s.get('entity_type', '?')}) "
                f"conf={s['confidence']:.2f} ev={ev_len}c — [{flags_str}]"
            )
        lines.append("")

    top_types = report.get("top_types", [])
    if top_types:
        lines += ["## Top 20 autoaprobados por tipo", ""]
        for t in top_types:
            lines.append(f"- {t['type']}: {t['count']}")
        lines.append("")

    dup_pairs = report.get("duplicate_risk_pairs", [])
    if dup_pairs:
        lines += [f"## Riesgo de duplicados ({len(dup_pairs)} pares)", ""]
        for p in dup_pairs[:20]:
            lines.append(f"- `{p['name_a']}` ↔ `{p['name_b']}`")
        lines.append("")

    ext_unv = report.get("external_unvalidated", [])
    if ext_unv:
        lines += [f"## Origin=external sin validated_by_s9k ({len(ext_unv)})", ""]
        for name in ext_unv[:10]:
            lines.append(f"- {name}")
        lines.append("")

    lines += [
        "> Informe de solo lectura. Ninguna entidad fue modificada.",
        "",
    ]

    md_path.write_text("\n".join(lines), encoding="utf-8")
