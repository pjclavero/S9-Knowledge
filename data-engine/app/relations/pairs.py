# -*- coding: utf-8 -*-
"""Generador DETERMINISTA de pares candidatos de relacion (A-REL-2).

Este modulo produce, para un segmento y su lista de entidades, el conjunto de
"pares candidatos" (sujeto/objeto) que ALIMENTARAN la extraccion de relaciones
posterior. Es un paso puramente estructural y offline:

  * NO llama a ningun LLM (Ollama / NVIDIA), NO usa red, NO toca Neo4j.
  * NO escribe nada y NO autoaprueba: solo calcula candidatos en memoria.
  * NO produce todavia un `RelationCandidate` (ver `relations.contracts`): un
    par es la ENTRADA de la extraccion, no su salida. El extractor consumira
    estos pares y asignara predicate/direction/confidence/evidence, momento en
    el que se construira el `RelationCandidate` completo (20 campos).

Relacion con `relations.contracts.RelationCandidate`
----------------------------------------------------
Cada `CandidatePair` preserva ya los campos de identidad y procedencia que el
`RelationCandidate` final necesita: `subject_id`, `object_id`, `workspace`,
`source_id` y `source_segment`. Los offsets de cada mencion (`subject_start`,
`subject_end`, `object_start`, `object_end`) permiten al extractor recortar la
evidencia textual (`evidence_text`/`evidence_start`/`evidence_end`).

Garantias
---------
  * Determinismo: misma entrada -> misma salida, byte a byte del serializado.
    No se depende del orden de iteracion de dicts ni de hashing aleatorio de
    Python: los `pair_id` se derivan con SHA-256 de una clave canonica.
  * Exclusion de autorrelaciones: se descartan pares con
    `subject_id == object_id` salvo que `config.reflexive_predicates` no este
    vacia (lista configurable, vacia por defecto).
  * Deduplicacion: por defecto (relacion NO dirigida) un par no ordenado
    {A, B} se emite UNA sola vez, canonicalizado por orden textual (el sujeto
    es la mencion que aparece antes). Con `emit_both_directions=True` se
    emiten ambos sentidos (A->B y B->A).
  * Anti-explosion: `max_pairs` acota el numero de pares emitidos. Si se supera,
    se TRUNCA de forma determinista (se conservan los pares mas cercanos) y se
    marca `truncated=True` + un warning; no se lanza excepcion salvo
    `config.strict_max_pairs=True`.

Estructura de entrada minima
----------------------------
entities: lista de dicts, cada uno con al menos:
    id    (str, no vacio)   -> identificador de la entidad
    start (int >= 0)        -> offset de inicio de la mencion en el segmento
    end   (int >= start)    -> offset de fin de la mencion en el segmento
  opcionales:
    type      (str|None)    -> tipo ontologico (Character, Location, ...)
    workspace (str)         -> por defecto el del segmento

segment: dict con al menos:
    id        (str, no vacio) -> identificador del segmento
    text      (str)           -> texto del segmento (para frase/parrafo/tokens)
    workspace (str, no vacio) -> workspace de procedencia
  opcionales:
    source_id   (str)  -> id del documento/fuente; por defecto == segment id
    source_page (int)  -> pagina de origen (se propaga como metadato)
"""
from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Modos de contexto soportados (la razon por la que dos entidades forman par).
CONTEXT_MODES = ("sentence", "paragraph", "segment", "distance")
# Unidades de distancia soportadas.
DISTANCE_UNITS = ("char", "token")


class PairGenerationError(ValueError):
    """Error de entrada o de configuracion del generador de pares."""


@dataclass(frozen=True)
class PairConfig:
    """Configuracion del generador de pares.

    context_mode : razon contextual para emparejar
        - "sentence"  : ambas menciones en la misma frase (por defecto).
        - "paragraph" : ambas menciones en el mismo parrafo.
        - "segment"   : cualquier par dentro del segmento.
        - "distance"  : el par depende solo de la ventana de distancia.
    window : unidad de distancia, "char" (por defecto) o "token".
    max_distance : distancia maxima permitida entre menciones (en `window`).
        None = sin limite de distancia (solo aplica `context_mode`). Cuando se
        fija, actua como filtro ADICIONAL al modo de contexto.
    max_pairs : numero maximo de pares emitidos (anti-explosion). Por defecto
        1000.
    strict_max_pairs : si True, superar `max_pairs` lanza PairGenerationError
        en lugar de truncar. Por defecto False (trunca + warning).
    reflexive_predicates : predicados reflexivos permitidos. Si NO esta vacia,
        se permiten pares con subject_id == object_id (dos menciones de la
        misma entidad). Vacia por defecto -> autorrelaciones excluidas.
    emit_both_directions : si True, emite (A->B) y (B->A) para cada par no
        ordenado (relacion dirigida). Por defecto False (no dirigida: un unico
        par canonico por combinacion).
    """

    context_mode: str = "sentence"
    window: str = "char"
    max_distance: Optional[int] = None
    max_pairs: int = 1000
    strict_max_pairs: bool = False
    reflexive_predicates: tuple[str, ...] = ()
    emit_both_directions: bool = False

    def __post_init__(self) -> None:
        if self.context_mode not in CONTEXT_MODES:
            raise PairGenerationError(
                f"context_mode invalido: {self.context_mode!r}; validos: {CONTEXT_MODES}"
            )
        if self.window not in DISTANCE_UNITS:
            raise PairGenerationError(
                f"window invalido: {self.window!r}; validos: {DISTANCE_UNITS}"
            )
        if self.max_distance is not None:
            if not isinstance(self.max_distance, int) or isinstance(self.max_distance, bool):
                raise PairGenerationError("max_distance debe ser int o None")
            if self.max_distance < 0:
                raise PairGenerationError("max_distance no puede ser negativo")
        if self.context_mode == "distance" and self.max_distance is None:
            raise PairGenerationError(
                "context_mode='distance' requiere max_distance no nulo"
            )
        if not isinstance(self.max_pairs, int) or isinstance(self.max_pairs, bool):
            raise PairGenerationError("max_pairs debe ser int")
        if self.max_pairs < 0:
            raise PairGenerationError("max_pairs no puede ser negativo")
        if not isinstance(self.reflexive_predicates, tuple):
            # normalizamos a tupla para inmutabilidad/determinismo
            object.__setattr__(self, "reflexive_predicates", tuple(self.reflexive_predicates))


@dataclass(frozen=True)
class CandidatePair:
    """Un par candidato sujeto/objeto (entrada al pipeline de extraccion).

    NO es un `RelationCandidate`: no lleva predicate/direction/confidence. Solo
    identidad, procedencia y contexto posicional para la extraccion posterior.
    """

    pair_id: str
    subject_id: str
    object_id: str
    subject_type: Optional[str]
    object_type: Optional[str]
    subject_start: int
    subject_end: int
    object_start: int
    object_end: int
    distance: int
    distance_unit: str
    context_mode: str
    workspace: str
    source_id: str
    source_segment: str
    source_page: Optional[int]
    reflexive: bool

    def to_dict(self) -> dict:
        return {
            "pair_id": self.pair_id,
            "subject_id": self.subject_id,
            "object_id": self.object_id,
            "subject_type": self.subject_type,
            "object_type": self.object_type,
            "subject_start": self.subject_start,
            "subject_end": self.subject_end,
            "object_start": self.object_start,
            "object_end": self.object_end,
            "distance": self.distance,
            "distance_unit": self.distance_unit,
            "context_mode": self.context_mode,
            "workspace": self.workspace,
            "source_id": self.source_id,
            "source_segment": self.source_segment,
            "source_page": self.source_page,
            "reflexive": self.reflexive,
        }


@dataclass(frozen=True)
class PairGenerationResult:
    """Resultado de `generate_pairs`.

    pairs : lista de CandidatePair, en orden determinista y estable.
    truncated : True si se aplico el limite `max_pairs`.
    total_before_truncation : numero de pares deduplicados antes de truncar.
    warnings : lista de avisos (p.ej. truncamiento por anti-explosion).
    """

    pairs: tuple["CandidatePair", ...]
    truncated: bool
    total_before_truncation: int
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "pairs": [p.to_dict() for p in self.pairs],
            "truncated": self.truncated,
            "total_before_truncation": self.total_before_truncation,
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        """Serializacion determinista: claves ordenadas, separadores estables."""
        return json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )


# --- Helpers deterministas -------------------------------------------------
_SENTENCE_BOUNDARY = re.compile(r"[.!?]+(?:\s|$)")
_PARAGRAPH_BOUNDARY = re.compile(r"\n[ \t]*\n")
_TOKEN = re.compile(r"\S+")


def stable_pair_id(workspace: str, subject_id: str, object_id: str, segment_id: str) -> str:
    """pair_id reproducible: SHA-256 de una clave canonica.

    No depende del hashing aleatorio de Python (PYTHONHASHSEED). Mismo cuarteto
    -> mismo id, en cualquier proceso y plataforma.
    """
    key = "\x1f".join(("relpair-v1", workspace, subject_id, object_id, segment_id))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _boundary_ends(text: str, pattern: re.Pattern) -> list[int]:
    """Offsets de fin (exclusivos) de cada unidad delimitada por `pattern`.

    Devuelve una lista ordenada de posiciones que marcan el fin de cada frase o
    parrafo. El indice de unidad de un offset `o` es `bisect_right(ends, o)`.
    """
    ends: list[int] = []
    for m in pattern.finditer(text):
        ends.append(m.end())
    if not ends or ends[-1] < len(text):
        ends.append(len(text))
    return ends


def _unit_index(ends: list[int], offset: int) -> int:
    return bisect_right(ends, offset)


def _distance(text: str, a_end: int, b_start: int, unit: str) -> int:
    """Distancia (>=0) entre el fin de la primera mencion y el inicio de la
    segunda. Si se solapan, 0."""
    if b_start <= a_end:
        return 0
    gap = text[a_end:b_start]
    if unit == "token":
        return len(_TOKEN.findall(gap))
    return b_start - a_end


def _normalize_entities(entities: Iterable[dict], default_workspace: str) -> list[dict]:
    """Valida y normaliza las entidades a un orden determinista.

    Cada mencion se ordena por (start, end, id) para que la salida no dependa
    del orden de entrada.
    """
    norm: list[dict] = []
    for i, ent in enumerate(entities):
        if not isinstance(ent, dict):
            raise PairGenerationError(f"entidad #{i} no es un dict")
        ent_id = ent.get("id")
        if not isinstance(ent_id, str) or not ent_id.strip():
            raise PairGenerationError(f"entidad #{i}: 'id' obligatorio y no vacio")
        start = ent.get("start")
        end = ent.get("end")
        for label, val in (("start", start), ("end", end)):
            if not isinstance(val, int) or isinstance(val, bool):
                raise PairGenerationError(f"entidad {ent_id!r}: '{label}' debe ser int")
            if val < 0:
                raise PairGenerationError(f"entidad {ent_id!r}: '{label}' no puede ser negativo")
        if start > end:
            raise PairGenerationError(
                f"entidad {ent_id!r}: start ({start}) > end ({end})"
            )
        ent_type = ent.get("type")
        if ent_type is not None and not isinstance(ent_type, str):
            raise PairGenerationError(f"entidad {ent_id!r}: 'type' debe ser str o None")
        ws = ent.get("workspace", default_workspace)
        if not isinstance(ws, str) or not ws.strip():
            raise PairGenerationError(f"entidad {ent_id!r}: 'workspace' invalido")
        norm.append(
            {"id": ent_id, "type": ent_type, "start": start, "end": end, "workspace": ws}
        )
    norm.sort(key=lambda e: (e["start"], e["end"], e["id"]))
    return norm


def _validate_segment(segment: dict) -> dict:
    if not isinstance(segment, dict):
        raise PairGenerationError("segment debe ser un dict")
    seg_id = segment.get("id")
    if not isinstance(seg_id, str) or not seg_id.strip():
        raise PairGenerationError("segment['id'] obligatorio y no vacio")
    text = segment.get("text", "")
    if not isinstance(text, str):
        raise PairGenerationError("segment['text'] debe ser str")
    workspace = segment.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        raise PairGenerationError("segment['workspace'] obligatorio y no vacio")
    source_id = segment.get("source_id", seg_id)
    if not isinstance(source_id, str) or not source_id.strip():
        raise PairGenerationError("segment['source_id'] debe ser str no vacio")
    source_page = segment.get("source_page")
    if source_page is not None and (
        not isinstance(source_page, int) or isinstance(source_page, bool)
    ):
        raise PairGenerationError("segment['source_page'] debe ser int o None")
    return {
        "id": seg_id,
        "text": text,
        "workspace": workspace,
        "source_id": source_id,
        "source_page": source_page,
    }


# --- API principal ---------------------------------------------------------
def generate_pairs(
    entities: Iterable[dict],
    segment: dict,
    *,
    config: Optional[PairConfig] = None,
) -> PairGenerationResult:
    """Genera pares candidatos deterministas para un segmento.

    Ver la documentacion del modulo (`relations.pairs`) y `README_pairs.md`
    para la estructura de entrada, las garantias y la relacion con
    `RelationCandidate`.
    """
    cfg = config or PairConfig()
    seg = _validate_segment(segment)
    text = seg["text"]
    ents = _normalize_entities(entities, seg["workspace"])

    # Unidades de contexto (frases / parrafos) precomputadas una sola vez.
    if cfg.context_mode == "sentence":
        ends = _boundary_ends(text, _SENTENCE_BOUNDARY)
    elif cfg.context_mode == "paragraph":
        ends = _boundary_ends(text, _PARAGRAPH_BOUNDARY)
    else:
        ends = None

    def _same_context(a: dict, b: dict) -> bool:
        if ends is None:
            return True  # "segment" o "distance": el contexto lo da la distancia
        return _unit_index(ends, a["start"]) == _unit_index(ends, b["start"])

    # Recorrido determinista: menciones ya ordenadas por (start, end, id).
    # `a` (indice i) es siempre la mencion previa -> sujeto canonico.
    raw: list[CandidatePair] = []
    n = len(ents)
    for i in range(n):
        a = ents[i]
        for j in range(i + 1, n):
            b = ents[j]

            reflexive = a["id"] == b["id"]
            if reflexive and not cfg.reflexive_predicates:
                continue  # autorrelacion excluida por defecto

            if not _same_context(a, b):
                continue

            dist = _distance(text, a["end"], b["start"], cfg.window)
            if cfg.max_distance is not None and dist > cfg.max_distance:
                continue

            # workspace del par: el de las entidades si coinciden; si difieren,
            # se exige coherencia con el del segmento (procedencia inequivoca).
            workspace = a["workspace"]
            if b["workspace"] != workspace:
                # menciones de workspaces distintos no forman relacion valida
                continue

            forward = _make_pair(a, b, dist, cfg, seg, reflexive)
            raw.append(forward)
            if cfg.emit_both_directions and not reflexive:
                raw.append(_make_pair(b, a, dist, cfg, seg, reflexive))

    deduped = _dedup(raw)
    total = len(deduped)

    # Orden final estable e independiente del input.
    deduped.sort(key=_final_sort_key)

    warnings: list[str] = []
    truncated = False
    if total > cfg.max_pairs:
        if cfg.strict_max_pairs:
            raise PairGenerationError(
                f"numero de pares ({total}) supera max_pairs ({cfg.max_pairs}) "
                "y strict_max_pairs=True"
            )
        # Truncado determinista: conservamos los mas cercanos (menor distancia),
        # con desempate estable por identidad.
        truncated = True
        by_priority = sorted(deduped, key=_truncation_key)
        kept = by_priority[: cfg.max_pairs]
        kept.sort(key=_final_sort_key)
        deduped = kept
        warnings.append(
            f"truncated: {total} pares deduplicados exceden max_pairs="
            f"{cfg.max_pairs}; se conservan los {cfg.max_pairs} mas cercanos"
        )

    return PairGenerationResult(
        pairs=tuple(deduped),
        truncated=truncated,
        total_before_truncation=total,
        warnings=tuple(warnings),
    )


def _make_pair(
    subj: dict, obj: dict, dist: int, cfg: PairConfig, seg: dict, reflexive: bool
) -> CandidatePair:
    pair_id = stable_pair_id(seg["workspace"], subj["id"], obj["id"], seg["id"])
    return CandidatePair(
        pair_id=pair_id,
        subject_id=subj["id"],
        object_id=obj["id"],
        subject_type=subj["type"],
        object_type=obj["type"],
        subject_start=subj["start"],
        subject_end=subj["end"],
        object_start=obj["start"],
        object_end=obj["end"],
        distance=dist,
        distance_unit=cfg.window,
        context_mode=cfg.context_mode,
        workspace=seg["workspace"],
        source_id=seg["source_id"],
        source_segment=seg["id"],
        source_page=seg["source_page"],
        reflexive=reflexive,
    )


def _dedup(pairs: list[CandidatePair]) -> list[CandidatePair]:
    """Deduplica por (subject_id, object_id) conservando la mencion mas cercana.

    Dos menciones distintas de la misma pareja de entidades producen el mismo
    par logico; se conserva la de MENOR distancia (desempate por posicion del
    sujeto y del objeto) para representarla de forma unica y determinista.
    """
    best: dict[tuple[str, str], CandidatePair] = {}
    for p in pairs:
        key = (p.subject_id, p.object_id)
        cur = best.get(key)
        if cur is None or _truncation_key(p) < _truncation_key(cur):
            best[key] = p
    return list(best.values())


def _final_sort_key(p: CandidatePair) -> tuple:
    return (p.subject_id, p.object_id, p.subject_start, p.object_start, p.pair_id)


def _truncation_key(p: CandidatePair) -> tuple:
    # Prioridad: menor distancia primero; desempates deterministas.
    return (p.distance, p.subject_start, p.object_start, p.subject_id, p.object_id)


__all__ = [
    "CONTEXT_MODES",
    "DISTANCE_UNITS",
    "PairConfig",
    "CandidatePair",
    "PairGenerationResult",
    "PairGenerationError",
    "generate_pairs",
    "stable_pair_id",
]
