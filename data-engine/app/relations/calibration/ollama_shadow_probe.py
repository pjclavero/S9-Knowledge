# -*- coding: utf-8 -*-
"""Probe de CALIBRACION del LLM local (Ollama) en MODO SOMBRA (`ollama-shadow-probe/v1`).

Ejercita `relations.local_llm_shadow.evaluate_relation_local` contra un servidor
Ollama REAL (API OpenAI-compatible en `<base>/v1`) sobre un pequeno corpus
SINTETICO, repitiendo cada caso N veces para medir repetibilidad, latencia y
coste, y agrega un informe estructurado.

Garantias (heredadas del evaluador, NO reimplementadas aqui):
  * MODO SOMBRA: nunca decide, nunca aprueba, nunca escribe (Neo4j/ficheros/cache).
  * SIN DEFAULT PRODUCTIVO: el endpoint es SIEMPRE explicito. Si falta, FALLA
    CERRADO (`ConfigError`) sin abrir un solo socket.
  * SIN CORPUS PRIVADO: solo se usan los casos sinteticos de este modulo o los
    que el llamador inyecte explicitamente.
  * SECRETOS REDACTADOS: el informe nunca contiene claves; el host del endpoint
    puede ofuscarse con `redact_endpoint=True`.

Reutilizacion (NO duplicacion):
  * Toda la logica de red/prompt/validacion vive en `local_llm_shadow` y el
    subsistema `external_ai`. Este probe SOLO orquesta llamadas y agrega metricas.

Este modulo NO abre red al importarse. La red solo ocurre si se llama a
`run_probe(...)` con un `endpoint` explicito (o un `transport` inyectado en tests).
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from external_ai.errors import ConfigError
from relations.local_llm_shadow import (
    LocalLLMConfig,
    LocalRelationRecommendation,
    RelationEvalInput,
    evaluate_relation_local,
)

PROBE_VERSION = "ollama-shadow-probe-1.0.0"


# ---------------------------------------------------------------------------
# Corpus SINTETICO (no privado). Cada caso trae su evidencia y offsets exactos
# para poder contrastar lo que el modelo devuelve. Los offsets de referencia
# NO se envian al modelo: son solo verdad-terreno del probe.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SyntheticCase:
    name: str
    document: str
    subject_id: str
    object_id: str
    template_id: str
    subject_type: Optional[str] = None
    object_type: Optional[str] = None
    workspace: str = "synthetic-block1"
    note: str = ""

    def to_input(self) -> RelationEvalInput:
        return RelationEvalInput(
            document=self.document,
            subject_id=self.subject_id,
            object_id=self.object_id,
            template_id=self.template_id,
            subject_type=self.subject_type,
            object_type=self.object_type,
            workspace=self.workspace,
            source_id=f"synthetic/{self.name}",
            source_segment="seg-0",
        )


# Casos deliberadamente cortos y sinteticos (personajes/facciones inventados).
DEFAULT_CASES: tuple[SyntheticCase, ...] = (
    SyntheticCase(
        name="membership_affirmative",
        document="Bayushi Hisao juro lealtad al Clan Escorpion en el consejo de invierno.",
        subject_id="Bayushi Hisao",
        object_id="Clan Escorpion",
        template_id="membership",
        subject_type="Character",
        object_type="Faction",
        note="Afirmativa clara: pertenencia asertada.",
    ),
    SyntheticCase(
        name="alliance_negated",
        document="Kakita Asuka no es aliada de Bayushi Hisao pese a los rumores de la corte.",
        subject_id="Kakita Asuka",
        object_id="Bayushi Hisao",
        template_id="alliance",
        subject_type="Character",
        object_type="Character",
        note="Negacion explicita: la relacion NO debe proponerse como hecho.",
    ),
    SyntheticCase(
        name="alliance_rumored",
        document="Se rumorea que Kakita Asuka podria haberse aliado con el Clan Grulla.",
        subject_id="Kakita Asuka",
        object_id="Clan Grulla",
        template_id="alliance",
        subject_type="Character",
        object_type="Faction",
        note="Estado epistemico: rumor/posibilidad, no aserto.",
    ),
)


# ---------------------------------------------------------------------------
# Resultado de una repeticion y agregado por caso
# ---------------------------------------------------------------------------
def _recommendation_fingerprint(rec: LocalRelationRecommendation) -> str:
    """Huella determinista del contenido decisivo de una recomendacion.

    Solo campos de contenido (no latencia): permite medir repetibilidad
    real ejecucion-a-ejecucion.
    """
    payload = {
        "state": rec.state,
        "recommendation": rec.recommendation,
        "validation_status": rec.validation_status,
        "relation_type": rec.relation_type,
        "direction": rec.direction,
        "confidence": rec.confidence,
        "negated": rec.negated,
        "epistemic_status": rec.epistemic_status,
        "evidence_text": rec.evidence_text,
        "evidence_start": rec.evidence_start,
        "evidence_end": rec.evidence_end,
        "validation_errors": sorted(rec.validation_errors or []),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


@dataclass
class CaseResult:
    case: str
    input_hash: str
    prompt_hash: str
    repetitions: int
    latencies_ms: list = field(default_factory=list)
    states: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    validation_statuses: list = field(default_factory=list)
    fingerprints: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    note: str = ""
    # invariantes de sombra observados en TODAS las repeticiones
    all_shadow: bool = True
    any_approval: bool = False

    @property
    def deterministic(self) -> bool:
        """True si todas las repeticiones produjeron el MISMO contenido decisivo."""
        return len(set(self.fingerprints)) <= 1

    @property
    def latency_p50_ms(self) -> Optional[float]:
        return statistics.median(self.latencies_ms) if self.latencies_ms else None

    @property
    def latency_max_ms(self) -> Optional[int]:
        return max(self.latencies_ms) if self.latencies_ms else None

    def summary(self) -> dict:
        return {
            "case": self.case,
            "input_hash": self.input_hash,
            "prompt_hash": self.prompt_hash,
            "repetitions": self.repetitions,
            "deterministic": self.deterministic,
            "distinct_outputs": len(set(self.fingerprints)),
            "states": sorted(set(self.states)),
            "recommendations": sorted(set(self.recommendations)),
            "validation_statuses": sorted(set(self.validation_statuses)),
            "latency_p50_ms": self.latency_p50_ms,
            "latency_max_ms": self.latency_max_ms,
            "all_shadow": self.all_shadow,
            "any_approval": self.any_approval,
            "validation_errors": sorted({e for errs in self.errors for e in errs}),
            "note": self.note,
        }


@dataclass
class ProbeReport:
    probe_version: str
    model: str
    endpoint: str
    repetitions: int
    cases: list = field(default_factory=list)  # list[CaseResult]

    def to_dict(self) -> dict:
        return {
            "probe_version": self.probe_version,
            "model": self.model,
            "endpoint": self.endpoint,
            "repetitions": self.repetitions,
            "global_invariants": {
                # NINGUN caso, en NINGUNA repeticion, aprueba o sale de sombra.
                "all_shadow": all(c.all_shadow for c in self.cases),
                "no_approvals": not any(c.any_approval for c in self.cases),
            },
            "cases": [c.summary() for c in self.cases],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=indent)


# ---------------------------------------------------------------------------
# Redaccion del endpoint para informes (host ofuscado, esquema y ruta visibles)
# ---------------------------------------------------------------------------
def redact_endpoint_host(endpoint: str) -> str:
    """Ofusca el host del endpoint conservando esquema y sufijo de ruta.

    'http://192.168.1.157:11434/v1' -> 'http://<host>/v1'.
    Nunca revela IP/hostname en informes compartibles.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(endpoint)
    if not parts.scheme:
        return "<host>"
    return urlunsplit((parts.scheme, "<host>", parts.path or "", "", ""))


# ---------------------------------------------------------------------------
# API PUBLICA
# ---------------------------------------------------------------------------
def run_probe(
    *,
    endpoint: Optional[str],
    model: str,
    cases: Sequence[SyntheticCase] = DEFAULT_CASES,
    repetitions: int = 3,
    timeout: int = 120,
    max_retries: int = 1,
    transport: Optional[Callable[[list], tuple]] = None,
    redact_endpoint: bool = True,
    sleep_between: float = 0.0,
) -> ProbeReport:
    """Ejecuta el probe de calibracion en modo sombra y devuelve un `ProbeReport`.

    Parametros
    ----------
    endpoint:
        URL EXPLICITA del servidor (p.ej. ``http://host:11434/v1``). Si es None y
        no se inyecta `transport`, el evaluador subyacente FALLA CERRADO
        (`ConfigError`) sin abrir red. NO existe endpoint por defecto.
    model:
        Nombre del modelo (p.ej. ``qwen2.5:7b``).
    cases:
        Casos sinteticos a ejercitar. Por defecto, `DEFAULT_CASES`.
    repetitions:
        Numero de repeticiones por caso para medir repetibilidad y latencia.
    transport:
        Punto de inyeccion para tests deterministas (sin red). Si se aporta, se
        usa en lugar de la red real.

    La escritura de cualquier informe a disco es responsabilidad del llamador
    (CLI): este metodo NO escribe nada.
    """
    if repetitions < 1:
        raise ValueError("repetitions debe ser >= 1")
    if transport is None and not endpoint:
        # Fallo cerrado explicito y temprano (coherente con el evaluador).
        raise ConfigError(
            "run_probe: endpoint ausente y sin transporte inyectado; "
            "no se contacta infraestructura por defecto."
        )

    ep_report = redact_endpoint_host(endpoint) if (endpoint and redact_endpoint) else (endpoint or "<injected-transport>")
    report = ProbeReport(
        probe_version=PROBE_VERSION,
        model=model,
        endpoint=ep_report,
        repetitions=repetitions,
        cases=[],
    )

    for case in cases:
        inp = case.to_input()
        cfg = LocalLLMConfig(
            model=model,
            endpoint=endpoint,
            transport=transport,
            timeout=timeout,
            max_retries=max_retries,
        )
        cr: Optional[CaseResult] = None
        for i in range(repetitions):
            rec = evaluate_relation_local(inp, config=cfg)
            if cr is None:
                cr = CaseResult(
                    case=case.name,
                    input_hash=rec.input_hash,
                    prompt_hash=rec.prompt_hash,
                    repetitions=repetitions,
                    note=case.note,
                )
            cr.latencies_ms.append(rec.latency_ms)
            cr.states.append(rec.state)
            cr.recommendations.append(rec.recommendation)
            cr.validation_statuses.append(rec.validation_status)
            cr.fingerprints.append(_recommendation_fingerprint(rec))
            cr.errors.append(list(rec.validation_errors or []))
            # Invariantes de sombra (barrera dura observacional).
            if not rec.shadow:
                cr.all_shadow = False
            if rec.recommendation not in {
                "recommend_propose", "recommend_reject", "recommend_human_review"
            }:
                cr.any_approval = True
            if sleep_between and i < repetitions - 1:
                time.sleep(sleep_between)
        assert cr is not None
        report.cases.append(cr)

    return report


__all__ = [
    "PROBE_VERSION",
    "SyntheticCase",
    "DEFAULT_CASES",
    "CaseResult",
    "ProbeReport",
    "redact_endpoint_host",
    "run_probe",
]
