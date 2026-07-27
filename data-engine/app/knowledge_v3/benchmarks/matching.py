# -*- coding: utf-8 -*-
"""Emparejamiento prediccion-vs-gold.

Aqui es donde se hacen las trampas sin querer. Un emparejamiento demasiado laxo
convierte una prediccion equivocada en un acierto y sube TODAS las metricas a la
vez sin que nadie toque el modelo. Por eso vive en un modulo propio, con las
reglas escritas, y con tests que se ponen rojos si se relaja.

Reglas (todas verificadas en `test_knowledge_v3_benchmarks_matching.py`):

1. **Uno a uno.** Una prediccion empareja con COMO MUCHO un gold, y un gold con
   como mucho una prediccion. Sin esta regla, repetir la misma prediccion cien
   veces subiria el recall sin coste.
2. **Determinismo total.** El resultado no depende del orden de entrada:
   candidatos y desempates se ordenan siempre por la misma clave.
3. **Span exacto por defecto.** `span_mode="exact"` exige mismo episodio y
   mismos offsets. `span_mode="overlap"` es un modo EXPLICITO y etiquetado, con
   umbral de IoU; nunca es el valor por defecto y queda registrado en el informe.
4. **La clave del claim no incluye el predicado por defecto.** Decidir el
   predicado es trabajo del motor, no del extractor: incluirlo en la clave del
   extractor mezclaria dos medidas. Se puede activar, y queda registrado.
5. **Los predicados simetricos canonizan sus extremos.** En un predicado
   declarado simetrico en el perfil, (A,B) y (B,A) son el MISMO hecho; en uno
   asimetrico, invertirlos es un error y debe contar como tal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Iterable, Sequence

#: Modos de emparejamiento de span admitidos.
SPAN_MODES = ("exact", "overlap")


@dataclass(frozen=True)
class MatchConfig:
    """Parametros del emparejamiento. Viajan al informe: sin ellos, un numero
    de P/R/F1 no es comparable con otro."""

    span_mode: str = "exact"
    overlap_threshold: float = 0.5
    #: Componentes de la clave de un claim, ademas de episodio/sujeto/objeto.
    claim_key_extra: tuple[str, ...] = ()
    #: Si True, la clave de un hecho incluye su intervalo de vigencia.
    fact_key_includes_validity: bool = False
    #: Predicados declarados simetricos en el perfil activo.
    symmetric_predicates: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.span_mode not in SPAN_MODES:
            raise ValueError(f"span_mode desconocido: {self.span_mode!r}")
        if not 0 < self.overlap_threshold <= 1:
            raise ValueError("overlap_threshold debe estar en (0, 1]")
        for extra in self.claim_key_extra:
            if extra not in ("predicate", "negated", "direction"):
                raise ValueError(f"componente de clave de claim desconocido: {extra!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "span_mode": self.span_mode,
            "overlap_threshold": self.overlap_threshold,
            "claim_key_extra": list(self.claim_key_extra),
            "fact_key_includes_validity": self.fact_key_includes_validity,
            "symmetric_predicates": sorted(self.symmetric_predicates),
        }


@dataclass
class MatchResult:
    """Resultado de un emparejamiento uno a uno."""

    pairs: list[tuple[str, str]] = field(default_factory=list)
    unmatched_gold: list[str] = field(default_factory=list)
    unmatched_pred: list[str] = field(default_factory=list)

    @property
    def tp(self) -> int:
        return len(self.pairs)

    @property
    def fn(self) -> int:
        return len(self.unmatched_gold)

    @property
    def fp(self) -> int:
        return len(self.unmatched_pred)

    def gold_of(self, pred_id: str) -> str | None:
        for g, p in self.pairs:
            if p == pred_id:
                return g
        return None

    def pred_of(self, gold_id: str) -> str | None:
        for g, p in self.pairs:
            if g == gold_id:
                return p
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "pairs": [list(p) for p in sorted(self.pairs)],
            "unmatched_gold": sorted(self.unmatched_gold),
            "unmatched_pred": sorted(self.unmatched_pred),
        }


# --------------------------------------------------------------------------
# Emparejamiento por clave exacta
# --------------------------------------------------------------------------
def match_by_key(
    gold: Sequence[dict[str, Any]],
    pred: Sequence[dict[str, Any]],
    *,
    id_field: str,
    key_fn: Callable[[dict[str, Any]], Hashable | None],
) -> MatchResult:
    """Empareja por igualdad de clave, uno a uno y de forma determinista.

    Los elementos cuya clave es `None` (no evaluables: por ejemplo un claim sin
    sujeto resuelto) quedan fuera del emparejamiento y se cuentan como no
    emparejados. Descartarlos en silencio inflaria la precision.
    """
    buckets: dict[Hashable, list[str]] = {}
    for item in sorted(gold, key=lambda d: str(d[id_field])):
        k = key_fn(item)
        if k is None:
            continue
        buckets.setdefault(k, []).append(str(item[id_field]))

    result = MatchResult()
    used_gold: set[str] = set()
    for item in sorted(pred, key=lambda d: str(d[id_field])):
        pid = str(item[id_field])
        k = key_fn(item)
        pool = buckets.get(k) if k is not None else None
        chosen = None
        if pool:
            for gid in pool:
                if gid not in used_gold:
                    chosen = gid
                    break
        if chosen is None:
            result.unmatched_pred.append(pid)
        else:
            used_gold.add(chosen)
            result.pairs.append((chosen, pid))
    for item in sorted(gold, key=lambda d: str(d[id_field])):
        gid = str(item[id_field])
        if gid not in used_gold:
            result.unmatched_gold.append(gid)
    return result


# --------------------------------------------------------------------------
# Emparejamiento de spans
# --------------------------------------------------------------------------
def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    lo = max(int(a["start"]), int(b["start"]))
    hi = min(int(a["end"]), int(b["end"]))
    inter = max(0, hi - lo)
    union = (
        max(int(a["end"]), int(b["end"])) - min(int(a["start"]), int(b["start"]))
    )
    return inter / union if union > 0 else 0.0


def match_spans(
    gold: Sequence[dict[str, Any]],
    pred: Sequence[dict[str, Any]],
    *,
    id_field: str,
    config: MatchConfig,
) -> MatchResult:
    """Empareja elementos anclados en texto (menciones, fragmentos).

    `exact` exige mismo episodio y mismos offsets. `overlap` empareja de forma
    voraz por IoU descendente, con desempate por identificador, y solo por
    encima del umbral. Voraz es deliberado: nunca puede superar al optimo, asi
    que como mucho SUBESTIMA. Una metrica de benchmark debe equivocarse hacia
    abajo, jamas hacia arriba.
    """
    if config.span_mode == "exact":
        return match_by_key(
            gold,
            pred,
            id_field=id_field,
            key_fn=lambda d: (str(d["episode_id"]), int(d["start"]), int(d["end"])),
        )

    gold_by_id = {str(g[id_field]): g for g in gold}
    pred_by_id = {str(p[id_field]): p for p in pred}
    candidates: list[tuple[float, str, str]] = []
    for gid, g in gold_by_id.items():
        for pid, p in pred_by_id.items():
            if str(g["episode_id"]) != str(p["episode_id"]):
                continue
            score = _iou(g, p)
            if score >= config.overlap_threshold:
                candidates.append((score, gid, pid))
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))

    result = MatchResult()
    used_gold: set[str] = set()
    used_pred: set[str] = set()
    for _score, gid, pid in candidates:
        if gid in used_gold or pid in used_pred:
            continue
        used_gold.add(gid)
        used_pred.add(pid)
        result.pairs.append((gid, pid))
    result.unmatched_gold = sorted(set(gold_by_id) - used_gold)
    result.unmatched_pred = sorted(set(pred_by_id) - used_pred)
    return result


# --------------------------------------------------------------------------
# Claves canonicas
# --------------------------------------------------------------------------
def canonical_endpoints(
    subject: str | None, obj: str | None, predicate: str | None, config: MatchConfig
) -> tuple[str | None, str | None]:
    """Ordena los extremos SOLO si el predicado es simetrico.

    En un predicado simetrico, invertir sujeto y objeto no cambia el hecho; en
    uno asimetrico, lo cambia por completo, y confundirlos es exactamente el
    error que el eje `direction` existe para detectar.
    """
    if predicate in config.symmetric_predicates and subject is not None and obj is not None:
        return tuple(sorted((subject, obj)))  # type: ignore[return-value]
    return subject, obj


def fact_key(assertion: dict[str, Any], config: MatchConfig) -> tuple | None:
    """Clave de un hecho del ledger.

    Incluye SIEMPRE la negacion: "X pertenece a Y" y "X no pertenece a Y" no son
    el mismo hecho, y tratarlos como uno es el error mas caro del sistema.
    """
    subj = assertion.get("subject_entity_id")
    obj = assertion.get("object_entity_id")
    pred = assertion.get("predicate")
    if subj is None or obj is None or pred is None:
        return None
    a, b = canonical_endpoints(subj, obj, pred, config)
    direction = assertion.get("direction")
    if pred in config.symmetric_predicates:
        direction = "UNDIRECTED"
    key: tuple = (a, pred, b, direction, bool(assertion.get("negated")))
    if config.fact_key_includes_validity:
        key = key + (assertion.get("valid_from"), assertion.get("valid_to"))
    return key


def claim_key(
    claim: dict[str, Any],
    mention_to_gold: dict[str, str],
    config: MatchConfig,
) -> tuple | None:
    """Clave de un claim, expresada en menciones GOLD alineadas.

    Un claim predicho apunta a menciones predichas; para poder compararlo con el
    gold hay que traducir esas menciones a las gold con las que emparejaron. Si
    alguna no emparejo, el claim NO es evaluable y se cuenta como fallo, no se
    ignora.
    """
    raw_subs = claim.get("subject_mentions") or []
    raw_objs = claim.get("object_mentions") or []
    if not raw_subs and not raw_objs:
        # Abstencion: el extractor dice explicitamente que no propone relacion.
        # Es una salida legitima y tiene que poder emparejarse; tratarla como
        # "no evaluable" penalizaria justo lo que se quiere fomentar.
        return (str(claim["episode_id"]), (), (), "ABSTAINED")
    subs = [mention_to_gold.get(m) for m in raw_subs]
    objs = [mention_to_gold.get(m) for m in raw_objs]
    if not subs or not objs or any(s is None for s in subs) or any(o is None for o in objs):
        return None
    key: tuple = (
        str(claim["episode_id"]),
        tuple(sorted(s for s in subs if s)),
        tuple(sorted(o for o in objs if o)),
    )
    for extra in config.claim_key_extra:
        if extra == "predicate":
            cands = claim.get("predicate_candidates") or []
            key = key + (cands[0]["predicate"] if cands else None,)
        elif extra == "negated":
            key = key + (bool(claim.get("negated")),)
        elif extra == "direction":
            cands = claim.get("direction_candidates") or []
            key = key + (cands[0]["direction"] if cands else None,)
    return key


def spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Solapamiento estricto de intervalos semiabiertos [start, end)."""
    return a_start < b_end and b_start < a_end


def build_alignment(match: MatchResult) -> dict[str, str]:
    """pred_id -> gold_id, a partir de un emparejamiento uno a uno."""
    return {p: g for g, p in match.pairs}


def pair_set(clusters: Iterable[Iterable[str]]) -> set[tuple[str, str]]:
    """Pares no ordenados de correferencia inducidos por unos grupos.

    Metrica de enlaces positivos (estilo BLANC/pairwise): dos menciones son
    correferentes si caen en el mismo grupo. Los singletons no aportan pares,
    asi que agrupar todo con todo no sale gratis: dispara los falsos positivos.
    """
    pairs: set[tuple[str, str]] = set()
    for cluster in clusters:
        items = sorted(set(cluster))
        for i, a in enumerate(items):
            for b in items[i + 1 :]:
                pairs.add((a, b))
    return pairs


__all__ = [
    "MatchConfig",
    "MatchResult",
    "SPAN_MODES",
    "build_alignment",
    "canonical_endpoints",
    "claim_key",
    "fact_key",
    "match_by_key",
    "match_spans",
    "pair_set",
    "spans_overlap",
]
