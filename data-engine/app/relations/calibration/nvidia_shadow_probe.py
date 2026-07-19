# -*- coding: utf-8 -*-
"""Probe de CALIBRACION del proveedor externo NVIDIA NIM en MODO SOMBRA (`nvidia-shadow-probe/v1`).

Ejercita `relations.external_ai_shadow.evaluate_relation_external` contra el
proveedor NVIDIA NIM REAL (API OpenAI-compatible alojada) sobre un pequeno corpus
SINTETICO de relaciones candidatas, repitiendo cada caso N veces para medir
repetibilidad, latencia y coste, y agrega un informe estructurado.

Garantias (heredadas del evaluador/registry, NO reimplementadas aqui):
  * MODO SOMBRA: nunca decide, nunca aprueba (`AUTO_APPROVED` prohibido), nunca
    escribe (ni Neo4j, ni ficheros, ni caches del probe).
  * SECRETO SEGURO: la API key se obtiene por demanda de `external_ai.registry`
    (variable de entorno) y NUNCA se almacena, imprime ni serializa. El probe solo
    reporta `api_key_present: true/false`.
  * SIN DEFAULT PRODUCTIVO NI CORPUS PRIVADO: endpoint/clave via entorno explicito;
    si falta la clave y no se inyecta proveedor, FALLA CERRADO (`ConfigError`).
  * ENDPOINT REDACTADO: el informe ofusca el host del endpoint.

Reutilizacion (NO duplicacion):
  * Toda la logica de red/prompt/validacion/consenso vive en `external_ai_shadow`,
    `external_ai.*` y `relations.*`. Este probe SOLO orquesta llamadas y agrega.

Este modulo NO abre red al importarse. La red solo ocurre al llamar a
`run_probe(...)` sin proveedor inyectado y con la clave presente en el entorno.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from external_ai.errors import ConfigError
from relations.contracts import (
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
)
from relations.external_ai_shadow import (
    RelationExternalConfig,
    RelationExternalEvaluation,
    evaluate_relation_external,
)

PROBE_VERSION = "nvidia-shadow-probe-1.0.0"


# ---------------------------------------------------------------------------
# Corpus SINTETICO (no privado): relaciones candidatas ya formadas por el
# pipeline heuristico interno, que el modelo externo debe JUZGAR (no crear).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SyntheticCandidate:
    name: str
    segment: str
    evidence: str
    subject_id: str
    object_id: str
    predicate: str
    subject_type: str
    object_type: str
    negated: bool = False
    epistemic: EpistemicStatus = EpistemicStatus.ASSERTED
    workspace: str = "synthetic-block2"
    note: str = ""

    def to_candidate(self) -> RelationCandidate:
        start = self.segment.find(self.evidence)
        if start < 0:
            raise ValueError(f"evidencia no literal en el segmento del caso {self.name!r}")
        return RelationCandidate(
            subject_id=self.subject_id,
            subject_type=self.subject_type,
            predicate=self.predicate,
            object_id=self.object_id,
            object_type=self.object_type,
            direction=Direction.SUBJECT_TO_OBJECT,
            confidence=0.8,
            evidence_text=self.evidence,
            evidence_start=start,
            evidence_end=start + len(self.evidence),
            source_id=f"synthetic/{self.name}",
            source_page=1,
            source_segment=self.segment,
            extraction_method=ExtractionMethod.HEURISTIC,
            model=None,
            negated=self.negated,
            temporal_scope=None,
            epistemic_status=self.epistemic,
            workspace=self.workspace,
        ).validate()


DEFAULT_CANDIDATES: tuple[SyntheticCandidate, ...] = (
    SyntheticCandidate(
        name="alliance_affirmative",
        segment="Kakita Asuka es aliada de Bayushi Hisao en la corte de invierno.",
        evidence="Kakita Asuka es aliada de Bayushi Hisao",
        subject_id="ent_asuka", object_id="ent_hisao", predicate="ALLIED_WITH",
        subject_type="Character", object_type="Character",
        note="Afirmativa clara: el modelo deberia confirmar o pedir humano, nunca aprobar.",
    ),
    SyntheticCandidate(
        name="alliance_negated",
        segment="Kakita Asuka no es aliada de Bayushi Hisao pese a los rumores.",
        evidence="Kakita Asuka no es aliada de Bayushi Hisao",
        subject_id="ent_asuka", object_id="ent_hisao", predicate="ALLIED_WITH",
        subject_type="Character", object_type="Character",
        negated=True,
        note="Negacion: el modelo NO debe confirmar la relacion como hecho.",
    ),
    SyntheticCandidate(
        name="membership_affirmative",
        segment="Bayushi Hisao juro lealtad al Clan Escorpion en el consejo.",
        evidence="juro lealtad al Clan Escorpion",
        subject_id="ent_hisao", object_id="fac_escorpion", predicate="MEMBER_OF",
        subject_type="Character", object_type="Faction",
        note="Pertenencia asertada.",
    ),
)


# ---------------------------------------------------------------------------
# Agregacion por candidato
# ---------------------------------------------------------------------------
def _evaluation_fingerprint(ev: RelationExternalEvaluation) -> str:
    """Huella determinista del contenido decisivo (sin latencia)."""
    payload = {
        "state": ev.state,
        "shadow_recommendation": ev.shadow_recommendation,
        "verdict": ev.verdict,
        "reason_codes": sorted(ev.reason_codes or []),
        "validation_errors": sorted(ev.validation_errors or []),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


@dataclass
class CandidateResult:
    case: str
    candidate_id: str
    repetitions: int
    latencies_ms: list = field(default_factory=list)
    states: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    fingerprints: list = field(default_factory=list)
    request_hashes: list = field(default_factory=list)
    response_hashes: list = field(default_factory=list)
    validation_errors: list = field(default_factory=list)
    note: str = ""
    all_shadow: bool = True
    any_approval: bool = False

    @property
    def deterministic(self) -> bool:
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
            "candidate_id": self.candidate_id,
            "repetitions": self.repetitions,
            "deterministic": self.deterministic,
            "distinct_outputs": len(set(self.fingerprints)),
            "states": sorted(set(self.states)),
            "recommendations": sorted(set(self.recommendations)),
            "latency_p50_ms": self.latency_p50_ms,
            "latency_max_ms": self.latency_max_ms,
            "all_shadow": self.all_shadow,
            "any_approval": self.any_approval,
            "validation_errors": sorted({e for errs in self.validation_errors for e in errs}),
            "note": self.note,
        }


@dataclass
class ProbeReport:
    probe_version: str
    model: str
    endpoint: str
    api_key_present: bool
    repetitions: int
    cases: list = field(default_factory=list)  # list[CandidateResult]

    def to_dict(self) -> dict:
        return {
            "probe_version": self.probe_version,
            "model": self.model,
            "endpoint": self.endpoint,
            "api_key_present": self.api_key_present,
            "repetitions": self.repetitions,
            "global_invariants": {
                "all_shadow": all(c.all_shadow for c in self.cases),
                "no_approvals": not any(c.any_approval for c in self.cases),
            },
            "cases": [c.summary() for c in self.cases],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=indent)


def redact_endpoint_host(endpoint: str) -> str:
    """Ofusca el host del endpoint conservando esquema y ruta.

    'https://integrate.api.nvidia.com/v1' -> 'https://<host>/v1'.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(endpoint)
    if not parts.scheme:
        return "<host>"
    return urlunsplit((parts.scheme, "<host>", parts.path or "", "", ""))


_VALID_RECOMMENDATIONS = frozenset({"confirm", "refine", "reject", "human"})


# ---------------------------------------------------------------------------
# API PUBLICA
# ---------------------------------------------------------------------------
def run_probe(
    *,
    model: str,
    candidates: Sequence[SyntheticCandidate] = DEFAULT_CANDIDATES,
    repetitions: int = 3,
    provider: Optional[Any] = None,
    redact_endpoint: bool = True,
) -> ProbeReport:
    """Ejecuta el probe de calibracion NVIDIA en modo sombra y devuelve un `ProbeReport`.

    Parametros
    ----------
    model:
        Nombre del modelo NVIDIA NIM (p.ej. ``meta/llama-3.1-70b-instruct``).
    candidates:
        Relaciones candidatas sinteticas a juzgar. Por defecto, `DEFAULT_CANDIDATES`.
    repetitions:
        Numero de repeticiones por caso para medir repetibilidad y latencia.
    provider:
        Punto de inyeccion para tests deterministas (objeto con ``_post_chat``).
        Si es None, se usa el proveedor REAL del registry (NVIDIA por entorno).

    Fallo cerrado: sin proveedor inyectado y sin API key en el entorno, se lanza
    `ConfigError` ANTES de tocar red. La clave nunca se imprime ni serializa.
    """
    if repetitions < 1:
        raise ValueError("repetitions debe ser >= 1")

    # Estado del secreto/endpoint SIN revelar la clave (reutiliza registry).
    from external_ai import registry

    cfg_env = registry.nvidia_config()
    api_key_present = bool(cfg_env.get("api_key_present"))
    endpoint_raw = cfg_env.get("base_url", "")

    if provider is None and not api_key_present:
        raise ConfigError(
            "run_probe NVIDIA: S9K_NVIDIA_API_KEY ausente y sin proveedor inyectado; "
            "no se contacta infraestructura por defecto (fallo cerrado)."
        )

    endpoint_report = (
        redact_endpoint_host(endpoint_raw) if (endpoint_raw and redact_endpoint) else (endpoint_raw or "<injected-provider>")
    )
    report = ProbeReport(
        probe_version=PROBE_VERSION,
        model=model,
        endpoint=endpoint_report,
        api_key_present=api_key_present,
        repetitions=repetitions,
        cases=[],
    )

    for case in candidates:
        cand = case.to_candidate()
        config = RelationExternalConfig(model=model, provider=provider)
        cr: Optional[CandidateResult] = None
        for _ in range(repetitions):
            results = evaluate_relation_external(cand, config=config)
            ev = results[0]
            if cr is None:
                cr = CandidateResult(
                    case=case.name,
                    candidate_id=ev.candidate_id,
                    repetitions=repetitions,
                    note=case.note,
                )
            cr.latencies_ms.append(ev.latency_ms)
            cr.states.append(ev.state)
            cr.recommendations.append(ev.shadow_recommendation)
            cr.fingerprints.append(_evaluation_fingerprint(ev))
            cr.request_hashes.append(ev.request_hash)
            cr.response_hashes.append(ev.response_hash)
            cr.validation_errors.append(list(ev.validation_errors or []))
            if not ev.shadow_mode:
                cr.all_shadow = False
            if ev.shadow_recommendation not in _VALID_RECOMMENDATIONS:
                cr.any_approval = True
        assert cr is not None
        report.cases.append(cr)

    return report


__all__ = [
    "PROBE_VERSION",
    "SyntheticCandidate",
    "DEFAULT_CANDIDATES",
    "CandidateResult",
    "ProbeReport",
    "redact_endpoint_host",
    "run_probe",
]
