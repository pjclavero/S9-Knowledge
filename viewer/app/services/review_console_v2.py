"""Review Console V2 — capa de lectura de la cola de revisión V3.

SOLO LECTURA. Este módulo no escribe nada: ni Neo4j, ni el ledger de decisiones,
ni las propuestas. No decide, no corrige, no aplica: presenta.

Reglas que se respetan de forma explícita:

1. **No se inventan campos.** Todo lo que se muestra procede de las claves que
   el exportador del motor (``data-engine/app/knowledge_v3/review_export.py``)
   escribe de verdad en el paquete de propuestas. Cuando un dato no existe, se
   devuelve ``None`` y la plantilla dice "no disponible"; nunca se rellena con
   un valor plausible ni se abre una segunda API para adivinarlo.
2. **Primero filtrar, después paginar.** ``apply_filters`` produce el conjunto
   sobre el que se cuenta y se ordena; ``paginate`` corta ese conjunto ya
   filtrado. Los conteos de la vista son los del conjunto filtrado, nunca los
   de una página recortada a posteriori.
3. **Autorización: no se toca.** El ámbito de visibilidad se aplica aguas
   arriba, en ``ReviewService.queue(..., scope=...)``. Aquí no hay ninguna
   regla de visibilidad, ni vocabulario paralelo de autorización.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from app.services.v3_review import VALID_ENGINE_DECISIONS, reason_label


def decision_is_known(decision: Optional[str]) -> bool:
    """¿Es ``decision`` una de las que el motor declara producir?

    El vocabulario se IMPORTA de ``app.services.v3_review``
    (``VALID_ENGINE_DECISIONS``); no se redeclara aquí. Una segunda lista de
    decisiones válidas es una segunda especificación, y la segunda siempre
    acaba siendo la desactualizada.
    """
    return bool(decision) and decision in VALID_ENGINE_DECISIONS

# Umbral por defecto de "baja confianza" para el filtro de la consola. Es un
# criterio DE PRESENTACIÓN de esta pantalla, no el umbral de decisión del motor
# (el motor no exporta sus umbrales; ver limitaciones en la documentación).
DEFAULT_LOW_CONFIDENCE = 0.6

# Prioridad de revisión: lo que más necesita ojos humanos, primero.
_DECISION_PRIORITY = {
    "REVIEW": 0,
    "ABSTAIN": 1,
    "REJECT_INVALID": 2,
}

PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25


class ReviewConsoleV2Error(ValueError):
    """Entrada inválida de la consola (filtro o paginación mal formados)."""


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _normalize(value: Any) -> str:
    """Minúsculas sin acentos, para que la búsqueda no dependa de la tilde."""
    decomposed = unicodedata.normalize("NFKD", _text(value))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _clean(value: Any) -> Optional[str]:
    """Valor de texto presentable, o None si el backend no lo expone.

    ``not_available`` es el marcador literal que usa el exportador cuando no
    pudo resolver un dato: se traduce a ausencia, no se muestra como si fuera
    un valor real.
    """
    text = _text(value).strip()
    if not text or text in {"not_available", "UNKNOWN", "None"}:
        return None
    return text


def _float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_text(item) for item in value if _text(item).strip()]
    return []


def row_view(item: dict[str, Any]) -> dict[str, Any]:
    """Proyección de una propuesta ya presentada por ``ReviewService.present``.

    Tolerante a datos parciales: un paquete antiguo al que le falten
    ``provenance`` o ``engine_decision`` produce una fila con ausencias
    explícitas, no una excepción.
    """
    engine = item.get("engine_decision") or {}
    claim = item.get("proposal") or {}
    provenance = item.get("provenance") or {}
    resolution = item.get("resolution") or {}
    negation = claim.get("negation") if isinstance(claim.get("negation"), dict) else None

    negated = claim.get("negated")
    if negated is None and negation is not None:
        negated = negation.get("negated")
    negation_kind = claim.get("negation_kind")
    if negation_kind is None and negation is not None:
        negation_kind = negation.get("type")

    effective = _clean(engine.get("effective_decision")) or _clean(engine.get("decision"))
    shadow = _clean(engine.get("shadow_decision"))
    # Acuerdo/desacuerdo SOLO cuando existen las dos partes. Sin sombra no hay
    # comparación posible: eso es "sin dato", no "acuerdo".
    # Añadido del carril C (no estaba en 41f8688): si alguna de las dos partes
    # es un estado que el motor no declara producir, tampoco hay comparación
    # válida. Declarar AGREE entre dos valores desconocidos es fabricar un
    # acuerdo sobre algo que no se entiende.
    if effective and shadow and decision_is_known(effective) and decision_is_known(shadow):
        agreement = "AGREE" if effective == shadow else "DISAGREE"
    else:
        agreement = None

    reasons = [
        {"code": _text(code), "label": reason_label(_text(code))}
        for code in _list(engine.get("reason_codes"))
    ]
    if item.get("reason_explanations"):
        reasons = list(item["reason_explanations"])

    literal = item.get("evidence_literal")
    evidence = item.get("evidence") or {}
    if literal is None:
        literal = evidence.get("literal_text")

    return {
        # Identidad y navegación
        "proposal_id": _text(item.get("proposal_id")),
        "workspace": _clean(item.get("workspace")),
        "source_id": _clean(item.get("source_id")),
        "episode_id": _clean(item.get("episode_id")),
        "claim_id": _clean(item.get("claim_id")),
        # Fuente y evidencia
        "episode_text": _text(item.get("episode_text")),
        "evidence_before": _text(item.get("evidence_before")),
        "evidence_literal": _text(literal),
        "evidence_after": _text(item.get("evidence_after")),
        "evidence_start": evidence.get("start"),
        "evidence_end": evidence.get("end"),
        "has_evidence": bool(_text(literal).strip()),
        # Candidato
        "subject": _clean(claim.get("subject")),
        "predicate": _clean(claim.get("predicate")),
        "object": _clean(claim.get("object")),
        "direction": _clean(claim.get("direction")),
        "negated": negated,
        "negation_kind": _clean(negation_kind),
        "temporal_status": _clean(claim.get("temporal_status")),
        "epistemic_status": _clean(claim.get("epistemic_status")),
        "claim_scope": _clean(claim.get("scope")),
        "subject_entity_id": _clean(resolution.get("subject")),
        "object_entity_id": _clean(resolution.get("object")),
        "predicate_alternatives": item.get("predicate_alternatives") or [],
        "direction_alternatives": item.get("direction_alternatives") or [],
        # Decisión
        "engine_decision": _clean(engine.get("decision")),
        "effective_decision": effective,
        # Estado desconocido = FALLO CERRADO. Un valor que el motor no declara
        # producir no se pinta como una decisión buena: la plantilla lo marca
        # como no reconocido. Pintar lo desconocido con el mismo aspecto que
        # ACCEPT es cómo un estado nuevo del motor se cuela por bueno.
        "decision_known": decision_is_known(effective),
        "shadow_decision_known": shadow is None or decision_is_known(shadow),
        "shadow_decision": shadow,
        "agreement": agreement,
        "confidence": _float(engine.get("confidence")),
        "provider": _clean(engine.get("provider")),
        "model": _clean(engine.get("model")),
        "reasons": reasons,
        "reason_codes": [reason["code"] for reason in reasons],
        "would_emit_operations": engine.get("would_emit_operations"),
        "operation_kinds": _list(engine.get("operation_kinds")),
        "shadow_findings": _list(engine.get("shadow_findings")),
        "ignored_findings": _list(engine.get("ignored_findings")),
        "effective_findings": _list(engine.get("effective_findings")),
        # Procedencia
        "extractors": _list(provenance.get("extractors")),
        "providers": _list(provenance.get("providers")),
        "models": _list(provenance.get("models")),
        "independent_families": _list(provenance.get("independent_families")),
        "engine_version": _clean(item.get("engine_version")),
        "ontology_version": _clean(item.get("ontology_version")),
        "prompt_version": _clean(item.get("prompt_version")),
        "profile_version": _clean(item.get("profile_version")),
        "proposal_hash": _clean(item.get("proposal_hash")),
        "package_origins": _list(item.get("package_origins")),
        # Estado de revisión (solo informativo: esta consola no decide)
        "human_decision": _clean((item.get("active_decision") or {}).get("human_decision")),
        "decided_at": _clean((item.get("active_decision") or {}).get("timestamp")),
        "reviewer": _clean((item.get("active_decision") or {}).get("reviewer")),
    }


def review_explanation(row: dict[str, Any]) -> list[str]:
    """Por qué este elemento está aquí, en frases completas y sin adornos."""
    lines: list[str] = []
    decision = row.get("effective_decision") or row.get("engine_decision")
    if decision and not decision_is_known(decision):
        lines.append(
            f"El paquete declara un estado que este visor no reconoce ({decision}): "
            "no se interpreta como aprobado."
        )
    elif decision:
        lines.append(f"El motor resolvió {decision} y por eso la propuesta no se aplicó sola.")
    else:
        lines.append("El paquete no declara la decisión del motor para esta propuesta.")
    for reason in row.get("reasons") or []:
        lines.append(f"{reason['code']}: {reason['label']}")
    if not row.get("reasons"):
        lines.append("El paquete no declara códigos de motivo para esta propuesta.")
    confidence = row.get("confidence")
    if confidence is None:
        lines.append("El paquete no declara confianza para esta decisión.")
    else:
        lines.append(f"Confianza declarada por el motor: {confidence:.2f}.")
    if row.get("agreement") == "DISAGREE":
        lines.append(
            "Desacuerdo: el proveedor externo en sombra propuso "
            f"{row['shadow_decision']} frente a {row['effective_decision']} del determinista."
        )
    elif row.get("agreement") == "AGREE":
        lines.append("El proveedor externo en sombra coincidió con la decisión determinista.")
    else:
        lines.append("No hay decisión en sombra registrada: no se puede comparar con el proveedor.")
    if not row.get("has_evidence"):
        lines.append("Sin texto literal de evidencia en el paquete: revisa la fuente antes de nada.")
    return lines


@dataclass(frozen=True)
class FilterSpec:
    """Filtros de la consola. Todos opcionales; todos se aplican ANTES de paginar."""

    decision: Optional[str] = None
    reason_code: Optional[str] = None
    provider: Optional[str] = None
    extractor: Optional[str] = None
    query: str = ""
    disagreements_only: bool = False
    low_confidence_only: bool = False
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    include_decided: bool = False

    @property
    def active(self) -> bool:
        return bool(
            self.decision or self.reason_code or self.provider or self.extractor
            or self.query.strip() or self.disagreements_only or self.low_confidence_only
            or self.min_confidence is not None or self.max_confidence is not None
        )


def parse_filters(
    *,
    decision: Optional[str] = None,
    reason_code: Optional[str] = None,
    provider: Optional[str] = None,
    extractor: Optional[str] = None,
    query: Optional[str] = None,
    disagreements_only: bool = False,
    low_confidence_only: bool = False,
    low_confidence_threshold: Optional[float] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    include_decided: bool = False,
) -> FilterSpec:
    threshold = DEFAULT_LOW_CONFIDENCE if low_confidence_threshold is None else low_confidence_threshold
    for name, value in (("low_confidence_threshold", threshold),
                        ("min_confidence", min_confidence),
                        ("max_confidence", max_confidence)):
        if value is not None and not 0.0 <= float(value) <= 1.0:
            raise ReviewConsoleV2Error(f"{name} debe estar entre 0 y 1")
    if (min_confidence is not None and max_confidence is not None
            and float(min_confidence) > float(max_confidence)):
        raise ReviewConsoleV2Error("min_confidence no puede superar a max_confidence")
    return FilterSpec(
        decision=_clean(decision),
        reason_code=_clean(reason_code),
        provider=_clean(provider),
        extractor=_clean(extractor),
        query=_text(query).strip(),
        disagreements_only=bool(disagreements_only),
        low_confidence_only=bool(low_confidence_only),
        low_confidence_threshold=float(threshold),
        min_confidence=None if min_confidence is None else float(min_confidence),
        max_confidence=None if max_confidence is None else float(max_confidence),
        include_decided=bool(include_decided),
    )


_SEARCH_FIELDS = (
    "proposal_id", "source_id", "episode_id", "claim_id", "subject", "predicate",
    "object", "evidence_literal", "provider", "model", "engine_version",
)


def _matches_query(row: dict[str, Any], needle: str) -> bool:
    haystack = " ".join(
        _normalize(row.get(field_name)) for field_name in _SEARCH_FIELDS
    )
    haystack += " " + " ".join(_normalize(code) for code in row.get("reason_codes", []))
    haystack += " " + " ".join(_normalize(name) for name in row.get("extractors", []))
    return _normalize(needle) in haystack


def matches(row: dict[str, Any], spec: FilterSpec) -> bool:
    if spec.decision and (row.get("effective_decision") or row.get("engine_decision")) != spec.decision:
        return False
    if spec.reason_code and spec.reason_code not in row.get("reason_codes", []):
        return False
    if spec.provider and spec.provider not in set(row.get("providers", [])) | {row.get("provider")}:
        return False
    if spec.extractor and spec.extractor not in row.get("extractors", []):
        return False
    if spec.disagreements_only and row.get("agreement") != "DISAGREE":
        return False
    confidence = row.get("confidence")
    if spec.low_confidence_only:
        # Sin confianza declarada NO es baja confianza: es un dato ausente, y
        # esconderlo aquí sería inventarse un valor.
        if confidence is None or confidence >= spec.low_confidence_threshold:
            return False
    if spec.min_confidence is not None and (confidence is None or confidence < spec.min_confidence):
        return False
    if spec.max_confidence is not None and (confidence is None or confidence > spec.max_confidence):
        return False
    if not spec.include_decided and row.get("human_decision"):
        return False
    if spec.query and not _matches_query(row, spec.query):
        return False
    return True


def apply_filters(rows: Iterable[dict[str, Any]], spec: FilterSpec) -> list[dict[str, Any]]:
    return [row for row in rows if matches(row, spec)]


def priority_key(row: dict[str, Any]) -> tuple:
    """Orden por prioridad de revisión, totalmente determinista.

    REVIEW antes que ABSTAIN antes que REJECT_INVALID; dentro de cada grupo,
    primero los desacuerdos con el proveedor, luego la menor confianza (la
    confianza ausente va justo detrás de la más baja, porque tampoco se puede
    dar por buena), y el ``proposal_id`` como desempate estable.
    """
    decision = row.get("effective_decision") or row.get("engine_decision") or ""
    confidence = row.get("confidence")
    return (
        _DECISION_PRIORITY.get(decision, 9),
        0 if row.get("agreement") == "DISAGREE" else 1,
        0 if confidence is None else 1,
        confidence if confidence is not None else 0.0,
        _text(row.get("source_id")),
        _text(row.get("episode_id")),
        _text(row.get("proposal_id")),
    )


SORTS = {
    "priority": priority_key,
    "confidence": lambda row: (
        1 if row.get("confidence") is None else 0,
        row.get("confidence") if row.get("confidence") is not None else 0.0,
        _text(row.get("proposal_id")),
    ),
    "source": lambda row: (
        _text(row.get("source_id")), _text(row.get("episode_id")), _text(row.get("proposal_id"))
    ),
}


def sort_rows(rows: Sequence[dict[str, Any]], sort: str = "priority") -> list[dict[str, Any]]:
    if sort not in SORTS:
        raise ReviewConsoleV2Error(f"orden desconocido: {sort}")
    return sorted(rows, key=SORTS[sort])


@dataclass(frozen=True)
class Page:
    """Una página del conjunto YA filtrado. ``total`` es del filtrado, no de la página."""

    rows: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
    pages: int
    has_previous: bool
    has_next: bool
    first_index: int
    last_index: int


def paginate(rows: Sequence[dict[str, Any]], page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> Page:
    """Corta el conjunto YA filtrado. Nunca filtra: si filtrase aquí, los
    conteos de la cabecera dejarían de cuadrar con lo que se enseña."""
    if page_size <= 0:
        raise ReviewConsoleV2Error("page_size debe ser positivo")
    total = len(rows)
    pages = max(1, -(-total // page_size))
    page = max(1, min(int(page), pages))
    start = (page - 1) * page_size
    window = list(rows[start:start + page_size])
    return Page(
        rows=window,
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
        has_previous=page > 1,
        has_next=page < pages,
        first_index=start + 1 if window else 0,
        last_index=start + len(window),
    )


@dataclass(frozen=True)
class Facets:
    """Valores disponibles para los desplegables, calculados sobre TODO el
    conjunto visible del workspace (no sobre la página) para que elegir un
    filtro no vacíe la lista de opciones."""

    decisions: tuple[str, ...] = ()
    reason_codes: tuple[tuple[str, str], ...] = ()
    providers: tuple[str, ...] = ()
    extractors: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


def facets(rows: Iterable[dict[str, Any]]) -> Facets:
    decisions: set[str] = set()
    reasons: dict[str, str] = {}
    providers: set[str] = set()
    extractors: set[str] = set()
    sources: set[str] = set()
    for row in rows:
        decision = row.get("effective_decision") or row.get("engine_decision")
        if decision:
            decisions.add(decision)
        for reason in row.get("reasons") or []:
            reasons.setdefault(reason["code"], reason["label"])
        if row.get("provider"):
            providers.add(row["provider"])
        providers.update(row.get("providers") or [])
        extractors.update(row.get("extractors") or [])
        if row.get("source_id"):
            sources.add(row["source_id"])
    return Facets(
        decisions=tuple(sorted(decisions)),
        reason_codes=tuple(sorted(reasons.items())),
        providers=tuple(sorted(providers)),
        extractors=tuple(sorted(extractors)),
        sources=tuple(sorted(sources)),
    )


@dataclass(frozen=True)
class ConsoleView:
    """Todo lo que la plantilla necesita, ya calculado y coherente entre sí."""

    page: Page
    facets: Facets
    spec: FilterSpec
    sort: str
    visible_total: int
    filtered_total: int
    disagreements: int
    low_confidence: int
    missing_confidence: int
    decided: int
    rows_all: list[dict[str, Any]] = field(default_factory=list, repr=False)


def build_view(
    items: Iterable[dict[str, Any]],
    spec: FilterSpec,
    *,
    sort: str = "priority",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> ConsoleView:
    """Filtra, ordena y solo entonces pagina. Ese orden es el contrato."""
    rows = [row_view(item) for item in items]
    available = facets(rows)
    filtered = sort_rows(apply_filters(rows, spec), sort)
    return ConsoleView(
        page=paginate(filtered, page, page_size),
        facets=available,
        spec=spec,
        sort=sort,
        visible_total=len(rows),
        filtered_total=len(filtered),
        disagreements=sum(1 for row in filtered if row.get("agreement") == "DISAGREE"),
        low_confidence=sum(
            1 for row in filtered
            if row.get("confidence") is not None
            and row["confidence"] < spec.low_confidence_threshold
        ),
        missing_confidence=sum(1 for row in filtered if row.get("confidence") is None),
        decided=sum(1 for row in filtered if row.get("human_decision")),
        rows_all=filtered,
    )


def neighbours(rows: Sequence[dict[str, Any]], proposal_id: str) -> tuple[
    Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[int]
]:
    """(anterior, actual, siguiente, posición 1-based) dentro del orden filtrado."""
    for index, row in enumerate(rows):
        if row.get("proposal_id") == proposal_id:
            return (
                rows[index - 1] if index > 0 else None,
                row,
                rows[index + 1] if index + 1 < len(rows) else None,
                index + 1,
            )
    return None, None, None, None


__all__ = [
    "ConsoleView", "DEFAULT_LOW_CONFIDENCE", "DEFAULT_PAGE_SIZE", "Facets", "FilterSpec",
    "Page", "PAGE_SIZES", "ReviewConsoleV2Error", "SORTS", "apply_filters", "build_view",
    "decision_is_known",
    "facets", "matches", "neighbours", "paginate", "parse_filters", "priority_key",
    "review_explanation", "row_view", "sort_rows",
]
