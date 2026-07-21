# -*- coding: utf-8 -*-
"""Pipeline END-TO-END de extraccion de relaciones en DRY-RUN (`relation-pipeline/v1`).

Este modulo ORQUESTA los componentes ya integrados de `relations/` para producir,
a partir de una representacion controlada de documento+segmentos+entidades, un
resultado COMPLETO y DETERMINISTA de relaciones candidatas evaluadas, SIN escribir
en ningun sitio, SIN abrir red y SIN autoaprobar nada.

Es EXCLUSIVAMENTE un orquestador: NO reimplementa ninguna pieza y NO define un
segundo `RelationCandidate`. Reutiliza literalmente:

  * `relations.pairs.generate_pairs`      -> pares candidatos deterministas.
  * `relations.signals.compute_all_signals`-> senales heuristicas explicables.
  * `relations.syntax` (proveedor `heuristic`, stdlib) -> estructura sintactica.
  * `relations.prompts`                    -> plantillas versionadas (para el prompt).
  * `relations.contracts.RelationCandidate`-> el UNICO contrato de candidato.
  * `relations.local_llm_shadow`           -> proveedor LOCAL en sombra (opcional).
  * `relations.external_ai_shadow`         -> proveedor EXTERNO en sombra (opcional).
  * `relations.consensus_adapter`          -> consenso (estados canonicos).
  * `relations.observability`              -> traza/eventos redactados.

Garantias DURAS
---------------
  * DRY-RUN: sin modo write, sin `apply`, sin persistencia, sin drivers Neo4j, sin
    repositorios productivos, sin autoaprobacion.
  * Proveedores DESHABILITADOS por defecto: el pipeline completa con
    heuristicas+sintaxis+consenso y registra el proveedor como NOT_EXECUTED, sin
    abrir un solo socket. Habilitados: SOLO con `transport`/`provider` inyectado.
  * DETERMINISMO: IDs reproducibles por hash de contenido (no timestamps ni azar).
    Mismo input+config+versiones -> mismo resultado, mismo orden, mismos IDs y
    hashes. El orden de los segmentos de entrada NO altera la salida.
  * WORKSPACE obligatorio; vacio -> error; mezcla de workspaces -> rechazada.
  * Fallo de un segmento NO invalida el resto; ausencia/fallo de proveedor NO es un
    rechazo (se registra); errores auditables; nunca se silencian excepciones.
  * INMUTABILIDAD: no se muta la entrada (segmentos/entidades) ni los resultados de
    los componentes reutilizados.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# --- Componentes reutilizados (NO se reimplementa nada) --------------------
from relations.consensus_adapter import (
    MODULE_VERSION as CONSENSUS_VERSION,
    compute_relation_consensus,
)
from relations.contracts import (
    SCHEMA_VERSION as CONTRACT_VERSION,
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
    RelationContractError,
)
from relations.observability import (
    ComponentResult,
    RelationTrace,
)
from relations import prompts as relation_prompts
from relations.pairs import (
    CandidatePair,
    PairConfig,
    PairGenerationError,
    generate_pairs,
)
from relations.signals import (
    SIGNALS_VERSION,
    SignalContext,
    compute_all_signals,
    _sentence_bounds,
    _clause_index,
    _NEGATION_CUES,
    _TEMPORAL_CUES,
    _RUMOR_CUES,
    _MODALITY_CUES,
)
from relations.syntax import SYNTAX_VERSION, get_analyzer, safe_analyze

PIPELINE_VERSION = "relation-pipeline-1.0.0"
PIPELINE_SCHEMA = "relation-pipeline/v1"

# Predicado generico cuando ninguna senal especifica una familia concreta. Es un
# predicado canonico normalizado y no vacio (valido para el contrato), pero NO
# pertenece a KNOWN_PREDICATES: el proveedor local solo corre para familias con
# plantilla.
GENERIC_PREDICATE = "RELATED_TO"

# Estados posibles de un proveedor en el resumen de ejecucion.
PROVIDER_NOT_EXECUTED = "NOT_EXECUTED"   # deshabilitado por defecto: jamas red
PROVIDER_EXECUTED = "EXECUTED"           # ejecutado con transporte/proveedor inyectado
PROVIDER_FAILED_CLOSED = "FAILED_CLOSED" # habilitado sin via legitima: fallo cerrado
PROVIDER_SKIPPED = "SKIPPED"             # no aplicable a este candidato

# Mapa senal-lexica -> predicado canonico (orden de prioridad determinista).
_CUE_PREDICATE = (
    ("membership", "MEMBER_OF"),
    ("possession", "OWNS"),
    ("location", "LOCATED_IN"),
)
# Mapa categoria de compatibilidad de tipos -> predicado canonico.
_CATEGORY_PREDICATE = {
    "MEMBERSHIP": "MEMBER_OF",
    "LOCATION": "LOCATED_IN",
    "POSSESSION": "OWNS",
    "PARTICIPATION": "PARTICIPATED_IN",
}

# Direccion por defecto y plantilla por predicado (derivadas del catalogo de
# plantillas, no duplicadas).
_DIR_BY_PRED = {t.predicate: t.default_direction for t in relation_prompts.list_templates()}
_TEMPLATE_ID_BY_PRED = {t.predicate: t.id for t in relation_prompts.list_templates()}

# Consenso -> contador del resumen.
_STATE_COUNTER = {
    "STRONG_CONSENSUS": "results_strong",
    "PARTIAL_CONSENSUS": "results_partial",
    "MODEL_CONFLICT": "results_conflict",
    "INVALID_RESPONSES": "results_invalid",
    "HUMAN_REQUIRED": "results_human",
}


class PipelineError(ValueError):
    """Error FATAL de configuracion o entrada del pipeline (aborta la ejecucion)."""


# ---------------------------------------------------------------------------
# Configuracion (limites y proveedores). Sin ninguna opcion de escritura.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PipelineConfig:
    """Configuracion del pipeline en dry-run.

    NO existe ninguna opcion de escritura/apply/persistencia: el dry-run es
    estructural, no un flag que se pueda desactivar.
    """

    # Limites configurables (anti-explosion / control de recursos).
    max_segments_per_doc: int = 500
    max_entities_per_segment: int = 200
    max_pairs_per_segment: int = 1000
    max_text_chars: int = 200_000
    max_prompt_chars: int = 24_000
    max_response_bytes: int = 65_536
    max_time_per_candidate_ms: int = 30_000
    max_errors_per_batch: int = 1000
    max_results: int = 100_000

    # Contexto de emparejamiento (se propaga a PairConfig).
    context_mode: str = "sentence"
    pair_window: str = "char"
    max_distance: Optional[int] = None

    # Modo de anclaje de la evidencia heuristica (PR#95 V1). Por DEFECTO "span":
    # comportamiento historico (span mecanico min(starts)..max(ends)). "conservative"
    # activa el anclaje conservador basado en clausula + marcadores (flag OFF por
    # defecto: no altera la salida a menos que se pida explicitamente por config).
    evidence_anchor_mode: str = "span"

    # Proveedores (DESHABILITADOS por defecto). Habilitar SOLO con inyeccion.
    local_llm_enabled: bool = False
    external_ai_enabled: bool = False
    local_model: str = "local-llm"
    external_model: str = "external-model"
    external_provider_name: str = "nvidia"
    prompt_suite: str = relation_prompts.DEFAULT_SUITE

    def to_dict(self) -> dict:
        return {
            "max_segments_per_doc": self.max_segments_per_doc,
            "max_entities_per_segment": self.max_entities_per_segment,
            "max_pairs_per_segment": self.max_pairs_per_segment,
            "max_text_chars": self.max_text_chars,
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_bytes": self.max_response_bytes,
            "max_time_per_candidate_ms": self.max_time_per_candidate_ms,
            "max_errors_per_batch": self.max_errors_per_batch,
            "max_results": self.max_results,
            "context_mode": self.context_mode,
            "pair_window": self.pair_window,
            "max_distance": self.max_distance,
            "evidence_anchor_mode": self.evidence_anchor_mode,
            "local_llm_enabled": self.local_llm_enabled,
            "external_ai_enabled": self.external_ai_enabled,
            "local_model": self.local_model,
            "external_model": self.external_model,
            "external_provider_name": self.external_provider_name,
            "prompt_suite": self.prompt_suite,
        }


_CONFIG_KEYS = frozenset(PipelineConfig().to_dict().keys())
# Flags de escritura PROHIBIDOS: si aparecen en la config de entrada, el pipeline
# aborta (defensa explicita del dry-run; objetivo de mutacion "escribir en dry-run").
_FORBIDDEN_CONFIG_KEYS = frozenset(
    {"write", "apply", "persist", "commit", "auto_approve", "autoapprove", "dry_run"}
)


def config_from_dict(data: Optional[dict]) -> PipelineConfig:
    """Construye una PipelineConfig desde un dict, rechazando flags de escritura."""
    data = dict(data or {})
    forbidden = _FORBIDDEN_CONFIG_KEYS & set(data)
    if forbidden:
        raise PipelineError(
            f"config prohibida en dry-run (no se permite escritura/apply): {sorted(forbidden)}"
        )
    unknown = set(data) - _CONFIG_KEYS
    if unknown:
        raise PipelineError(f"claves de config desconocidas: {sorted(unknown)}")
    return PipelineConfig(**data)


# ---------------------------------------------------------------------------
# Utilidades deterministas
# ---------------------------------------------------------------------------
def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _stable_hash(obj: Any, *, length: int = 16) -> str:
    digest = hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()
    return digest[:length] if length and length > 0 else digest


def _signal_map(signals: Iterable[Any]) -> dict:
    """Mapa {name: value} independiente del orden de las senales."""
    out: dict[str, Any] = {}
    for s in signals or ():
        name = getattr(s, "name", None)
        if name is not None and name not in out:
            out[name] = getattr(s, "value", None)
    return out


# ---------------------------------------------------------------------------
# Proposicion heuristica del candidato (glue, NO extraccion duplicada)
# ---------------------------------------------------------------------------
def _choose_predicate(sigmap: dict, pair: CandidatePair) -> str:
    for name, pred in _CUE_PREDICATE:
        if sigmap.get(name):
            return pred
    categories = sigmap.get("type_compatibility") or []
    if isinstance(categories, list) and categories:
        return _CATEGORY_PREDICATE.get(categories[0], GENERIC_PREDICATE)
    return GENERIC_PREDICATE


def _temporal_scope(sigmap: dict) -> Optional[str]:
    """Alcance temporal como STRING canonico (class-aware) o None.

    Reutiliza el `scope` ya serializado por `signal_temporality`
    (`TemporalClassification.to_scope_string()`), producido SOLO cuando hay alcance
    temporal no trivial. Sin senal -> None (no se inventa). Contrato intacto: sigue
    devolviendo str|None.
    """
    temporal = sigmap.get("temporality")
    if not isinstance(temporal, dict):
        return None
    scope = temporal.get("scope")
    return scope if isinstance(scope, str) and scope else None


def _epistemic_status(sigmap: dict) -> EpistemicStatus:
    """Elige el `epistemic_status` (uno de los 4 valores del contrato) de forma
    SEGURA y class-aware.

    Delega en `signal_epistemic` (que ya invoco `epistemic.classify_epistemic`
    sobre la ventana): si el clasificador propone RUMORED/HYPOTHETICAL/INTENDED se
    usa tal cual. ASSERTED solo cuando NO hay ninguna marca epistemica.

    INVARIANTE DURO: un rumor NUNCA se convierte en hecho. Se conserva ademas el
    comportamiento historico como red de seguridad (rumor->RUMORED,
    modality->HYPOTHETICAL) para el caso improbable de que la senal class-aware no
    este presente. Un cue no-asertivo jamas produce ASSERTED.
    """
    epi = sigmap.get("epistemic")
    if isinstance(epi, dict):
        raw = epi.get("status")
        try:
            status = EpistemicStatus(raw)
        except (ValueError, KeyError):
            status = None
        if status is not None:
            # Guardia de seguridad: si por cualquier razon el clasificador marcase
            # ASSERTED teniendo un cue no-asertivo, se degrada (nunca afirmar rumor).
            if status == EpistemicStatus.ASSERTED and epi.get("has_cue"):
                if sigmap.get("rumor"):
                    return EpistemicStatus.RUMORED
                return EpistemicStatus.HYPOTHETICAL
            return status

    # Red de seguridad historica (retrocompatible) si no hay senal class-aware.
    if sigmap.get("rumor"):
        return EpistemicStatus.RUMORED
    if sigmap.get("modality"):
        return EpistemicStatus.HYPOTHETICAL
    return EpistemicStatus.ASSERTED


def _confidence(sigmap: dict) -> float:
    """Confianza heuristica determinista en [0,1] (evidencia, no decision)."""
    conf = 0.3
    if sigmap.get("same_sentence"):
        conf += 0.2
    if sigmap.get("same_clause"):
        conf += 0.1
    if sigmap.get("svo_pattern"):
        conf += 0.2
    if sigmap.get("type_compatibility"):
        conf += 0.1
    rep = sigmap.get("repetition")
    if isinstance(rep, int) and rep > 1:
        conf += 0.1
    return round(min(conf, 0.9), 4)


@dataclass
class _CandidateBuildError(Exception):
    reason_code: str
    message: str


# ---------------------------------------------------------------------------
# Anclaje conservador de evidencia (PR#95 V1) -- flag OFF por defecto
# ---------------------------------------------------------------------------
# Marcadores de ATRIBUCION/reportativos. Reutiliza el estilo de los lexicos
# deterministas de `relations.signals` (variantes con y sin tilde, en minuscula).
# Son senales de "quien afirma" que el ground-truth suele incluir en la evidencia
# cuando encabezan la clausula (p.ej. "Segun los rumores, ...").
_ATTRIBUTION_CUES = (
    "segun ", "segun ", "de acuerdo con", "conforme a", "afirma", "afirman",
    "declaro", "declararon", "sostiene", "asegura", "aseguran", "dijo", "dice",
)
# Marcadores EPISTEMICOS relevantes = rumor + modalidad (reutilizados de signals).
_EPISTEMIC_CUES = tuple(_RUMOR_CUES) + tuple(_MODALITY_CUES)


def _find_all_cues(window_lower: str, cues) -> list[int]:
    """Offsets (relativos a la ventana) de TODAS las apariciones de cualquier cue.

    Determinista y sin efectos: solo lee. Case-insensitive por `lower` (preserva
    longitudes en espanol). Devuelve la lista de posiciones de inicio.
    """
    out: list[int] = []
    for cue in cues:
        start = 0
        while True:
            idx = window_lower.find(cue, start)
            if idx == -1:
                break
            out.append(idx)
            start = idx + 1
    return out


def _clause_bounds_for_range(
    segment: str, sent_lo: int, sent_hi: int, c_min: int, c_max: int
) -> tuple[int, int]:
    """Limites de caracter de las clausulas [c_min..c_max] DENTRO de una frase ya
    delimitada por `_sentence_bounds`. NO reimplementa deteccion de frase: deriva
    las clausulas por separadores ,;: con la MISMA semantica que `_clause_index`
    (una posicion pertenece a la clausula = numero de separadores estrictamente a
    su izquierda dentro de la frase).
    """
    clause_sep = set(",;:")
    seps = [i for i in range(sent_lo, sent_hi) if segment[i] in clause_sep]
    clause_lo = sent_lo if c_min == 0 else seps[c_min - 1] + 1
    clause_hi = sent_hi if c_max >= len(seps) else seps[c_max] + 1
    return clause_lo, clause_hi


def _conservative_anchor(
    segment: str,
    subject_start: int,
    subject_end: int,
    object_start: int,
    object_end: int,
) -> Optional[tuple[int, int]]:
    """Calcula la envolvente CONSERVADORA de evidencia para un par de menciones.

    Estrategia (pura y determinista):
      1. Parte de los limites de FRASE (`_sentence_bounds`) de ambas menciones.
      2. ESTRECHA a la clausula segura que contiene ambas (separadores ,;: via
         `_clause_index` + `_clause_bounds_for_range`), sin expandir a la frase
         entera salvo que la propia frase sea una unica clausula.
      3. INCLUYE, si caen FUERA de esa clausula pero DENTRO de la frase: negacion
         y atribucion/epistemico que preceden a la envolvente, y marcas temporales
         que la siguen (para no perder senales que el GT si incluye).
      4. Recorta espacios y separadores externos para offsets limpios.

    Devuelve (lo, hi) coherentes con `segment[lo:hi]`, o None si el calculo diera
    algo vacio/incoherente o que se saliese de la frase (FALLBACK SEGURO al span,
    que gestiona el llamante). GARANTIA: la envolvente devuelta es SUBCONJUNTO de
    la frase y CONTIENE ambas menciones.
    """
    m_lo = min(subject_start, object_start)
    m_hi = max(subject_end, object_end)

    s1i, s1f = _sentence_bounds(segment, subject_start, subject_end)
    s2i, s2f = _sentence_bounds(segment, object_start, object_end)
    sent_lo, sent_hi = min(s1i, s2i), max(s1f, s2f)

    # Clausula segura que contiene ambas menciones (indices dentro de la frase).
    c_sub = _clause_index(segment, subject_start, sent_lo, sent_hi)
    c_obj = _clause_index(segment, object_start, sent_lo, sent_hi)
    clause_lo, clause_hi = _clause_bounds_for_range(
        segment, sent_lo, sent_hi, min(c_sub, c_obj), max(c_sub, c_obj)
    )

    # La envolvente base debe contener ambas menciones completas.
    env_lo = min(clause_lo, m_lo)
    env_hi = max(clause_hi, m_hi)

    # Inclusion de marcadores relevantes que caen FUERA de la clausula (pero en la
    # frase). Negacion/atribucion/epistemico ANTES -> bajan env_lo; temporal
    # DESPUES -> sube env_hi. Siempre acotado a la frase (nunca la desborda).
    window = segment[sent_lo:sent_hi]
    window_lower = window.lower()

    pre_cues = tuple(_NEGATION_CUES) + _ATTRIBUTION_CUES + _EPISTEMIC_CUES
    for rel in _find_all_cues(window_lower, pre_cues):
        abs_start = sent_lo + rel
        if abs_start < env_lo:
            env_lo = abs_start

    for rel in _find_all_cues(window_lower, tuple(_TEMPORAL_CUES)):
        cue_len = 0
        # longitud del cue concreto que casa en esta posicion (para el offset final)
        for cue in _TEMPORAL_CUES:
            if window_lower.startswith(cue, rel):
                cue_len = max(cue_len, len(cue))
        abs_end = sent_lo + rel + cue_len
        if abs_end > env_hi:
            env_hi = abs_end

    # Recorte de espacios y separadores de clausula externos (offsets limpios).
    sep_ws = set(",;: \t\n")
    while env_lo < env_hi and segment[env_lo] in sep_ws:
        env_lo += 1
    while env_hi > env_lo and segment[env_hi - 1] in sep_ws:
        env_hi -= 1

    # Coherencia / fallback seguro.
    if env_hi <= env_lo:
        return None
    if env_lo > m_lo or env_hi < m_hi:      # debe contener ambas menciones
        return None
    if env_lo < sent_lo or env_hi > sent_hi:  # nunca desborda la frase
        return None
    if not segment[env_lo:env_hi].strip():
        return None
    return env_lo, env_hi


def _build_candidate(
    pair: CandidatePair,
    sigmap: dict,
    seg_text: str,
    workspace: str,
    anchor_mode: str = "span",
) -> RelationCandidate:
    """Construye (y valida) un RelationCandidate a partir del par y sus senales.

    La evidencia es el span LITERAL que cubre ambas menciones. Un span vacio se
    rechaza EXPLICITAMENTE (evidencia inexistente): objetivo de mutacion.

    `anchor_mode`:
      * "span" (defecto): span mecanico min(starts)..max(ends) -- comportamiento
        historico, sin cambios.
      * "conservative": envolvente conservadora (clausula + marcadores) via
        `_conservative_anchor`, con FALLBACK SEGURO al span si diese algo
        incoherente/vacio. La coherencia `seg_text[lo:hi]==evidence_text` se
        mantiene igual (se corta literalmente del segmento).
    """
    lo = min(pair.subject_start, pair.object_start)
    hi = max(pair.subject_end, pair.object_end)
    if hi <= lo:
        raise _CandidateBuildError("evidence_span_empty", "el par no ancla evidencia (span vacio)")
    if anchor_mode == "conservative":
        cons = _conservative_anchor(
            seg_text,
            pair.subject_start,
            pair.subject_end,
            pair.object_start,
            pair.object_end,
        )
        if cons is not None:
            lo, hi = cons  # si es None -> se conserva el span (fallback seguro)
    evidence_text = seg_text[lo:hi]
    if not evidence_text.strip():
        raise _CandidateBuildError("evidence_blank", "la evidencia es solo espacios")

    predicate = _choose_predicate(sigmap, pair)
    candidate = RelationCandidate(
        subject_id=pair.subject_id,
        subject_type=pair.subject_type,
        predicate=predicate,
        object_id=pair.object_id,
        object_type=pair.object_type,
        direction=_DIR_BY_PRED.get(predicate, Direction.UNDIRECTED),
        confidence=_confidence(sigmap),
        evidence_text=evidence_text,
        evidence_start=lo,
        evidence_end=hi,
        source_id=pair.source_id,
        source_page=pair.source_page,
        source_segment=pair.source_segment,
        extraction_method=ExtractionMethod.HEURISTIC,
        model=None,
        negated=bool(sigmap.get("negation")),
        temporal_scope=_temporal_scope(sigmap),
        epistemic_status=_epistemic_status(sigmap),
        workspace=workspace,
        validation_flags=["dry_run", "heuristic"],
    )
    try:
        candidate.validate()
    except RelationContractError as exc:
        raise _CandidateBuildError("contract_invalid", str(exc)) from exc
    return candidate


def _candidate_key(workspace: str, cand: RelationCandidate) -> str:
    return _stable_hash(
        {
            "workspace": workspace,
            "subject_id": cand.subject_id,
            "predicate": cand.predicate,
            "object_id": cand.object_id,
            "source_segment": cand.source_segment,
        }
    )


# ---------------------------------------------------------------------------
# Proveedores en sombra (opcionales, SOLO con inyeccion)
# ---------------------------------------------------------------------------
def _run_local(cand: RelationCandidate, pair: CandidatePair, seg_text: str, config: PipelineConfig,
               ctx: "_RunContext") -> tuple[Optional[Any], str]:
    """Ejecuta el LLM local en sombra si esta habilitado. Devuelve (recomendacion, estado)."""
    if not config.local_llm_enabled:
        return None, PROVIDER_NOT_EXECUTED
    template_id = _TEMPLATE_ID_BY_PRED.get(cand.predicate)
    if template_id is None:
        return None, PROVIDER_SKIPPED
    from relations.local_llm_shadow import (
        LocalLLMConfig,
        RelationEvalInput,
        evaluate_relation_local,
    )

    inp = RelationEvalInput(
        document=seg_text,
        subject_id=cand.subject_id,
        object_id=cand.object_id,
        template_id=template_id,
        subject_type=cand.subject_type,
        object_type=cand.object_type,
        workspace=cand.workspace,
        source_id=cand.source_id,
        source_segment=cand.source_segment,
        source_page=cand.source_page,
        signals=ctx.signals_for(pair),
        max_chars=min(config.max_text_chars, 4000),
    )
    local_cfg = LocalLLMConfig(
        model=config.local_model,
        transport=ctx.local_transport,   # None => fallo cerrado (sin endpoint)
        suite=config.prompt_suite,
        max_prompt_chars=config.max_prompt_chars,
        max_response_bytes=config.max_response_bytes,
    )
    try:
        rec = evaluate_relation_local(inp, config=local_cfg)
        return rec, PROVIDER_EXECUTED
    except Exception:  # noqa: BLE001 - fallo cerrado sin endpoint/transport, sin red
        return None, PROVIDER_FAILED_CLOSED


def _run_external(cand: RelationCandidate, config: PipelineConfig, ctx: "_RunContext",
                  seg_text: str) -> tuple[Optional[Any], str]:
    """Ejecuta la IA externa en sombra si esta habilitada. Devuelve (evaluacion, estado).

    P0: se pasa el TEXTO REAL del segmento (`seg_text`) como `document_text`, para
    que el proveedor evalue/valide contra el documento y NO contra el ID del
    segmento (`cand.source_segment`, que se conserva solo como trazabilidad).
    """
    if not config.external_ai_enabled:
        return None, PROVIDER_NOT_EXECUTED
    from relations.external_ai_shadow import (
        RelationExternalConfig,
        evaluate_relation_external,
    )

    ext_cfg = RelationExternalConfig(
        model=config.external_model,
        provider_name=config.external_provider_name,
        suite=config.prompt_suite,
        shadow_mode=True,
        provider=ctx.external_provider,   # None => registry (sin key => fallo cerrado)
    )
    try:
        evals = evaluate_relation_external(cand, config=ext_cfg, document_text=seg_text)
        return (evals[0] if evals else None), PROVIDER_EXECUTED
    except Exception:  # noqa: BLE001 - aislado; ausencia/fallo != rechazo
        return None, PROVIDER_FAILED_CLOSED


# ---------------------------------------------------------------------------
# Contexto de ejecucion (inyeccion de transporte/proveedor; sin red por defecto)
# ---------------------------------------------------------------------------
@dataclass
class _RunContext:
    local_transport: Optional[Any] = None
    external_provider: Optional[Any] = None
    _signals_by_pair: dict = field(default_factory=dict)

    def register_signals(self, pair_id: str, signals: list) -> None:
        self._signals_by_pair[pair_id] = signals

    def signals_for(self, pair: CandidatePair) -> list:
        return self._signals_by_pair.get(pair.pair_id, [])


# ---------------------------------------------------------------------------
# Validacion / normalizacion de la entrada
# ---------------------------------------------------------------------------
def _validate_payload(payload: dict) -> tuple[str, str, list]:
    if not isinstance(payload, dict):
        raise PipelineError("payload debe ser un dict")
    workspace = payload.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        raise PipelineError("workspace es obligatorio y no puede estar vacio")
    document_id = payload.get("document") or payload.get("source_id") or payload.get("document_id")
    if not isinstance(document_id, str) or not document_id.strip():
        raise PipelineError("document/source_id es obligatorio y no puede estar vacio")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise PipelineError("segments debe ser una lista (puede estar vacia)")
    return workspace, document_id, segments


# ---------------------------------------------------------------------------
# Procesado de un segmento (fallo aislado)
# ---------------------------------------------------------------------------
def _process_segment(
    seg: dict,
    index: int,
    workspace: str,
    document_id: str,
    execution_id: str,
    config: PipelineConfig,
    ctx: _RunContext,
    trace: RelationTrace,
    summary: dict,
) -> dict:
    errors: list[dict] = []
    seg_id = seg.get("segment_id") or seg.get("id")
    if not isinstance(seg_id, str) or not seg_id.strip():
        seg_id = f"seg-{index}"

    text = seg.get("text", "")
    if not isinstance(text, str):
        errors.append({"code": "segment_text_not_str", "message": "segment text no es str", "fatal_for_segment": True})
        return _segment_result(seg_id, "failed", [], [], errors)

    # Limite de tamano de texto.
    if len(text) > config.max_text_chars:
        errors.append({
            "code": "segment_text_too_large",
            "message": f"texto del segmento excede max_text_chars={config.max_text_chars}",
            "fatal_for_segment": True,
        })
        return _segment_result(seg_id, "failed", [], [], errors)

    # Workspace: se rechaza la MEZCLA (workspace de segmento distinto del pipeline).
    seg_ws = seg.get("workspace", workspace)
    if seg_ws != workspace:
        errors.append({
            "code": "workspace_mismatch",
            "message": f"workspace del segmento ({seg_ws!r}) != workspace del pipeline ({workspace!r})",
            "fatal_for_segment": True,
        })
        return _segment_result(seg_id, "failed", [], [], errors)

    entities = seg.get("entities", [])
    if not isinstance(entities, list):
        errors.append({"code": "entities_not_list", "message": "entities no es lista", "fatal_for_segment": True})
        return _segment_result(seg_id, "failed", [], [], errors)

    summary["entities"] += len(entities)
    if len(entities) > config.max_entities_per_segment:
        errors.append({
            "code": "too_many_entities",
            "message": f"entidades ({len(entities)}) exceden max_entities_per_segment={config.max_entities_per_segment}",
            "fatal_for_segment": True,
        })
        return _segment_result(seg_id, "failed", [], [], errors)

    # Potencial combinatorio (para el contador de descartes).
    n = len(entities)
    summary["pairs_potential"] += n * (n - 1) // 2

    # --- generate_pairs (reutilizado; NO se reimplementa) ---
    pair_segment = {
        "id": seg_id,
        "text": text,
        "workspace": workspace,
        "source_id": seg.get("source_id", document_id),
        "source_page": seg.get("source_page"),
    }
    pair_cfg = PairConfig(
        context_mode=config.context_mode,
        window=config.pair_window,
        max_distance=config.max_distance,
        max_pairs=config.max_pairs_per_segment,
    )
    try:
        pair_result = generate_pairs(entities, pair_segment, config=pair_cfg)
    except PairGenerationError as exc:
        errors.append({"code": "pair_generation_error", "message": str(exc), "fatal_for_segment": True})
        return _segment_result(seg_id, "failed", [], [], errors)

    pairs = list(pair_result.pairs)
    summary["pairs_generated"] += len(pairs)

    # --- sintaxis (proveedor heuristico, stdlib) una vez por segmento ---
    syntax_analysis = safe_analyze(get_analyzer("heuristic"), text)

    candidate_records: list[dict] = []
    seen_candidates: set[str] = set()
    for pair in pairs:
        rec = _process_pair(
            pair, text, syntax_analysis, workspace, config, ctx, summary, errors, seen_candidates
        )
        if rec is not None:
            candidate_records.append(rec)

    status = "ok" if not any(e.get("fatal_for_segment") for e in errors) else "partial"
    # Evento de observabilidad del segmento (redactado; sin volcar texto en claro).
    trace.record(
        document_id=document_id,
        workspace=workspace,
        component="pipeline.segment",
        version=PIPELINE_VERSION,
        result=ComponentResult.OK if status == "ok" and not errors else (
            ComponentResult.ERROR if status == "failed" else ComponentResult.PARTIAL
        ),
        segment_id=seg_id,
        num_pairs=len(pairs),
        input_size=len(text),
        errors=[f"{e['code']}" for e in errors],
    )

    pairs_out = [p.to_dict() for p in pairs]
    signals_out = {p.pair_id: [s.to_dict() for s in ctx.signals_for(p)] for p in pairs}
    return {
        "segment_id": seg_id,
        "status": status,
        "pairs": pairs_out,
        "signals": signals_out,
        "syntax": syntax_analysis.to_dict(),
        "candidates": candidate_records,
        "errors": errors,
        "truncated": pair_result.truncated,
        "pair_warnings": list(pair_result.warnings),
    }


def _process_pair(
    pair: CandidatePair,
    seg_text: str,
    syntax_analysis: Any,
    workspace: str,
    config: PipelineConfig,
    ctx: _RunContext,
    summary: dict,
    errors: list,
    seen_candidates: set,
) -> Optional[dict]:
    # --- senales (reutilizado) ---
    try:
        sig_ctx = SignalContext(
            segment=seg_text,
            subject_start=pair.subject_start,
            subject_end=pair.subject_end,
            object_start=pair.object_start,
            object_end=pair.object_end,
            subject_type=pair.subject_type,
            object_type=pair.object_type,
        )
        signals = compute_all_signals(sig_ctx)
    except Exception as exc:  # noqa: BLE001 - offsets fuera de rango, tipos invalidos...
        errors.append({
            "code": "signal_error",
            "message": f"{type(exc).__name__}: {exc}",
            "pair_id": pair.pair_id,
            "fatal_for_segment": False,
        })
        return None
    ctx.register_signals(pair.pair_id, signals)
    sigmap = _signal_map(signals)

    # --- candidato (contrato unico) ---
    try:
        candidate = _build_candidate(
            pair, sigmap, seg_text, workspace,
            anchor_mode=config.evidence_anchor_mode,
        )
    except _CandidateBuildError as exc:
        errors.append({
            "code": exc.reason_code,
            "message": exc.message,
            "pair_id": pair.pair_id,
            "fatal_for_segment": False,
        })
        return None

    ckey = _candidate_key(workspace, candidate)
    if ckey in seen_candidates:
        return None  # candidato repetido: dedup determinista
    seen_candidates.add(ckey)
    summary["candidates_evaluated"] += 1

    # --- proveedores en sombra (opcionales) ---
    local_rec, local_status = _run_local(candidate, pair, seg_text, config, ctx)
    external_eval, external_status = _run_external(candidate, config, ctx, seg_text)
    if local_status == PROVIDER_EXECUTED:
        summary["local_calls_simulated"] += 1
    if external_status == PROVIDER_EXECUTED:
        summary["external_calls_simulated"] += 1
    if local_status == PROVIDER_FAILED_CLOSED:
        summary["provider_fail_closed"] += 1
    if external_status == PROVIDER_FAILED_CLOSED:
        summary["provider_fail_closed"] += 1

    # --- consenso (reutilizado; estados canonicos) ---
    consensus = compute_relation_consensus(
        candidate,
        signals=signals,
        syntax=syntax_analysis,
        local=local_rec,
        external=external_eval,
    )
    counter = _STATE_COUNTER.get(consensus.state)
    if counter:
        summary[counter] += 1

    candidate_id = ckey
    return {
        "candidate_id": candidate_id,
        "pair_id": pair.pair_id,
        "candidate": candidate.to_dict(),
        "consensus": consensus.to_dict(),
        "local": local_rec.to_dict() if local_rec is not None else None,
        "local_status": local_status,
        "external": external_eval.to_dict() if external_eval is not None else None,
        "external_status": external_status,
    }


def _segment_result(seg_id: str, status: str, pairs: list, candidates: list, errors: list) -> dict:
    return {
        "segment_id": seg_id,
        "status": status,
        "pairs": pairs,
        "signals": {},
        "syntax": None,
        "candidates": candidates,
        "errors": errors,
        "truncated": False,
        "pair_warnings": [],
    }


# ---------------------------------------------------------------------------
# Entrada publica
# ---------------------------------------------------------------------------
def _new_summary() -> dict:
    return {
        "documents": 0,
        "segments": 0,
        "segments_processed": 0,
        "segments_failed": 0,
        "entities": 0,
        "pairs_potential": 0,
        "pairs_generated": 0,
        "pairs_discarded": 0,
        "candidates_evaluated": 0,
        "results_strong": 0,
        "results_partial": 0,
        "results_conflict": 0,
        "results_invalid": 0,
        "results_human": 0,
        "local_calls_simulated": 0,
        "external_calls_simulated": 0,
        "provider_fail_closed": 0,
        "timeouts": 0,
        "errors": 0,
        "chars_processed": 0,
        "bytes_processed": 0,
    }


def run_pipeline(
    payload: dict,
    *,
    config: Optional[PipelineConfig] = None,
    local_transport: Optional[Any] = None,
    external_provider: Optional[Any] = None,
) -> dict:
    """Ejecuta el pipeline end-to-end en DRY-RUN y devuelve un dict JSON-serializable.

    Parametros
    ----------
    payload:
        `{document|source_id, workspace, segments:[{text, segment_id, entities:[...]}],
        config?}`. Los segmentos y entidades reutilizan la forma que ya consumen
        `generate_pairs` y `SignalContext`.
    config:
        `PipelineConfig`. Si es None se toma de `payload["config"]` (o defaults).
    local_transport / external_provider:
        Inyeccion de proveedores en sombra para tests. SIN ellos y con el proveedor
        habilitado, el pipeline FALLA CERRADO (no abre red).

    Determinismo: mismo `payload` + `config` -> misma salida byte a byte (IDs y
    hashes incluidos). El ORDEN de los segmentos de entrada NO afecta a la salida.
    """
    if config is None:
        config = config_from_dict(payload.get("config"))

    workspace, document_id, segments = _validate_payload(payload)

    if len(segments) > config.max_segments_per_doc:
        raise PipelineError(
            f"segmentos ({len(segments)}) exceden max_segments_per_doc={config.max_segments_per_doc}"
        )

    # --- Orden canonico de segmentos (independiente del orden de entrada) ---
    def _seg_key(item: tuple[int, dict]) -> tuple:
        i, seg = item
        sid = seg.get("segment_id") or seg.get("id") or f"seg-{i}"
        return (str(sid), i)

    ordered = [seg for _, seg in sorted(enumerate(segments), key=_seg_key)]

    versions = {
        "pipeline": PIPELINE_VERSION,
        "contract": CONTRACT_VERSION,
        "signals": SIGNALS_VERSION,
        "syntax": SYNTAX_VERSION,
        "consensus": CONSENSUS_VERSION,
        "prompts": relation_prompts.PROMPT_SUITE_VERSION,
        "template": relation_prompts.TEMPLATE_VERSION,
    }

    # --- execution_id: hash de contenido canonico (NO timestamps ni azar) ---
    canonical_input = {
        "document_id": document_id,
        "workspace": workspace,
        "segments": [_canonical_segment(s) for s in ordered],
        "config": config.to_dict(),
        "versions": versions,
    }
    execution_id = _stable_hash(canonical_input, length=32)

    summary = _new_summary()
    summary["documents"] = 1
    summary["segments"] = len(ordered)

    trace = RelationTrace(execution_id=execution_id)
    ctx = _RunContext(local_transport=local_transport, external_provider=external_provider)

    segment_results: list[dict] = []
    for i, seg in enumerate(ordered):
        seg_res = _process_segment(
            seg, i, workspace, document_id, execution_id, config, ctx, trace, summary
        )
        segment_results.append(seg_res)
        text = seg.get("text", "")
        if isinstance(text, str):
            summary["chars_processed"] += len(text)
            summary["bytes_processed"] += len(text.encode("utf-8"))
        if seg_res["status"] == "failed":
            summary["segments_failed"] += 1
        else:
            summary["segments_processed"] += 1

    # --- Contadores derivados ---
    summary["pairs_discarded"] = max(0, summary["pairs_potential"] - summary["pairs_generated"])
    total_errors = sum(len(s["errors"]) for s in segment_results)
    summary["errors"] = total_errors
    if total_errors > config.max_errors_per_batch:
        raise PipelineError(
            f"errores del lote ({total_errors}) exceden max_errors_per_batch="
            f"{config.max_errors_per_batch}"
        )

    # --- Resultados por candidato (orden determinista) ---
    results: list[dict] = []
    for seg_res in segment_results:
        for rec in seg_res["candidates"]:
            results.append(rec)
    results.sort(key=lambda r: (
        r["candidate"]["source_segment"],
        r["candidate"]["subject_id"],
        r["candidate"]["object_id"],
        r["candidate"]["predicate"],
        r["candidate_id"],
    ))
    if len(results) > config.max_results:
        results = results[: config.max_results]

    # --- Estado de proveedores para el resumen ---
    provider_status = {
        "local_llm": PROVIDER_EXECUTED if config.local_llm_enabled and local_transport is not None
        else (PROVIDER_NOT_EXECUTED if not config.local_llm_enabled else PROVIDER_FAILED_CLOSED),
        "external_ai": PROVIDER_EXECUTED if config.external_ai_enabled and external_provider is not None
        else (PROVIDER_NOT_EXECUTED if not config.external_ai_enabled else PROVIDER_FAILED_CLOSED),
    }

    output = {
        "schema": PIPELINE_SCHEMA,
        "execution_id": execution_id,
        "dry_run": True,
        "workspace": workspace,
        "document_id": document_id,
        "versions": versions,
        "config": config.to_dict(),
        "provider_status": provider_status,
        "summary": summary,
        "documents": [
            {
                "document_id": document_id,
                "workspace": workspace,
                "segments": segment_results,
            }
        ],
        "results": results,
        "errors": [
            {**e, "segment_id": s["segment_id"]}
            for s in segment_results
            for e in s["errors"]
        ],
        "observability": trace.to_dict(),
    }
    # --- Hash funcional (excluye la traza de observabilidad y sus tiempos) ---
    functional = {k: v for k, v in output.items() if k != "observability"}
    output["result_hash"] = _stable_hash(functional, length=32)
    return output


def _canonical_segment(seg: dict) -> dict:
    """Representacion canonica de un segmento para el hash de ejecucion (sin mutar)."""
    ents = []
    for e in seg.get("entities", []) or []:
        if isinstance(e, dict):
            ents.append({
                "id": e.get("id"),
                "start": e.get("start"),
                "end": e.get("end"),
                "type": e.get("type"),
            })
    ents.sort(key=lambda e: (str(e.get("start")), str(e.get("end")), str(e.get("id"))))
    return {
        "segment_id": seg.get("segment_id") or seg.get("id"),
        "text": seg.get("text", ""),
        "source_id": seg.get("source_id"),
        "source_page": seg.get("source_page"),
        "entities": ents,
    }


def to_jsonl(output: dict) -> str:
    """Serializa el resultado como JSONL (una linea por candidato), determinista.

    Cada linea es un objeto autonomo con execution_id/workspace + el resultado del
    candidato. Orden estable (el de `output['results']`). Salida NO destructiva.
    """
    lines = []
    header = {
        "type": "execution",
        "execution_id": output["execution_id"],
        "workspace": output["workspace"],
        "document_id": output["document_id"],
        "dry_run": output["dry_run"],
        "summary": output["summary"],
        "versions": output["versions"],
        "result_hash": output["result_hash"],
    }
    lines.append(_canonical(header))
    for rec in output["results"]:
        lines.append(_canonical({
            "type": "candidate",
            "execution_id": output["execution_id"],
            "workspace": output["workspace"],
            **rec,
        }))
    return "\n".join(lines)


def to_json(output: dict) -> str:
    """Serializa el resultado completo como JSON determinista."""
    return json.dumps(output, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "PIPELINE_VERSION",
    "PIPELINE_SCHEMA",
    "GENERIC_PREDICATE",
    "PROVIDER_NOT_EXECUTED",
    "PROVIDER_EXECUTED",
    "PROVIDER_FAILED_CLOSED",
    "PROVIDER_SKIPPED",
    "PipelineError",
    "PipelineConfig",
    "config_from_dict",
    "run_pipeline",
    "to_json",
    "to_jsonl",
]
