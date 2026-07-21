# -*- coding: utf-8 -*-
"""Politica de REDUCCION CONTROLADA de revision humana (Bloque 8).

Este modulo NO decide si algo se escribe: decide si un resultado YA CALCULADO por
el ensemble/consenso (Bloques 6/7) es candidato a que un humano NO tenga que
revisarlo (`AUTO_PROPOSABLE`) o si sigue requiriendo revision humana
(`REVIEW_REQUIRED`). No existe una tercera etiqueta, y ninguna de las dos
etiquetas es una aprobacion, una escritura ni un "accept": la clasificacion mas
favorable que existe (`AUTO_PROPOSABLE`) sigue significando "puede PROPONERSE sin
que un humano tenga que mirarlo primero", nunca "queda escrito en el grafo".

Principios duros (identicos en espiritu a `relations.ensemble`)
-----------------------------------------------------------------
  * DETERMINISTA y PURO: sin red, sin disco, sin reloj, sin aleatoriedad. Recibe
    valores YA CALCULADOS.
  * FAIL-CLOSED: cualquier entrada corrupta, incompleta, de tipo inesperado o
    ausente produce `REVIEW_REQUIRED`. Nunca se lanza una excepcion no controlada
    por un input malformado; el fallo se absorbe hacia el lado seguro.
  * NO IMPORTA `review/*`, ni ningun driver de Neo4j, ni nada de red. No conoce
    Ollama/NVIDIA. Es una capa de PURA CLASIFICACION en memoria.
  * NO define un tercer estado de consenso ni una taxonomia de recomendacion
    paralela: reutiliza `external_ai.models.CONSENSUS_STATES` unicamente para
    validar que el `state` recibido pertenece a la taxonomia canonica.
  * NUNCA emite ni acepta como entrada una etiqueta de aprobacion/escritura
    (`AUTO_APPROVED`, `APPROVED`, `WRITE`, `APPLY`, `COMMIT`, ...): estan
    prohibidas explicitamente y su aparicion como *label* propio es un error de
    programacion (se comprueba en `__post_init__`).

Version
-------
`REVIEW_POLICY_VERSION` versiona el CODIGO de este modulo (cambios de forma o de
reglas). `ReviewPolicyConfig` versiona los UMBRALES por separado (calibracion),
al estilo de `weights_version`/`thresholds_version` en `relations.ensemble`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

# --- Taxonomia canonica de estados (REUTILIZADA, nunca duplicada) -----------
try:  # pragma: no cover - la rama de fallback solo cubre entornos sin external_ai
    from external_ai.models import CONSENSUS_STATES, STRONG_CONSENSUS
except Exception:  # pragma: no cover
    CONSENSUS_STATES = (
        "STRONG_CONSENSUS", "PARTIAL_CONSENSUS", "MODEL_CONFLICT",
        "INVALID_RESPONSES", "HUMAN_REQUIRED",
    )
    STRONG_CONSENSUS = "STRONG_CONSENSUS"

REVIEW_POLICY_VERSION = "relation-review-policy-1.0.0"
REVIEW_POLICY_SCHEMA = "relation-review-policy/v1"

# ---------------------------------------------------------------------------
# Etiquetas de la politica (dos, y solo dos; ninguna solapa consenso/recomendacion)
# ---------------------------------------------------------------------------
AUTO_PROPOSABLE = "AUTO_PROPOSABLE"
# NOTA: NO puede llamarse "HUMAN_REQUIRED" -- ese literal ya es un ESTADO DE
# CONSENSO canonico (`external_ai.models.HUMAN_REQUIRED`). Un label de politica
# con el mismo texto solaparia dos conceptos distintos (estado de consenso vs.
# etiqueta de politica de revision) y esta EXPRESAMENTE prohibido por el diseno
# del Bloque 8. Se usa un nombre disjunto.
REVIEW_REQUIRED = "REVIEW_REQUIRED"
REVIEW_POLICY_LABELS: tuple = (AUTO_PROPOSABLE, REVIEW_REQUIRED)

# Barrera anti-aprobacion: ningun label de esta politica puede coincidir jamas
# con ninguno de estos valores prohibidos, ni contenerlos como alias.
_FORBIDDEN_LABELS = frozenset({
    "AUTO_APPROVED", "APPROVED", "APPROVE", "WRITE", "APPLY", "COMMIT", "MERGE",
    "ACCEPT", "ACCEPTED", "AUTO_ACCEPT", "AUTO_ACCEPTED",
})
if any(lbl in _FORBIDDEN_LABELS for lbl in REVIEW_POLICY_LABELS):  # pragma: no cover
    raise AssertionError("etiqueta de politica prohibida detectada en tiempo de import")
if set(REVIEW_POLICY_LABELS) & set(CONSENSUS_STATES):  # pragma: no cover
    raise AssertionError("las etiquetas de politica NO pueden solapar CONSENSUS_STATES")


class ReviewPolicyConfigError(ValueError):
    """Config de la politica de revision invalida."""


# ---------------------------------------------------------------------------
# Configuracion versionada (umbrales calibrables)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReviewPolicyConfig:
    """Umbrales de la politica, versionados y hasheables.

    `auto_propose_score_threshold` es el UNICO umbral calibrable al alza. El
    Organizador exige que solo pueda SUBIR para mantener el falso-aceptado bajo
    control; nunca bajar para ganar cobertura. Este modulo no impone ese
    historial (no tiene estado entre llamadas), pero documenta la garantia y la
    hace explicita en `to_dict()`/`config_hash` para que cualquier cambio quede
    trazado y sea auditable por el AGENTE-TESTS o por el Organizador.

    `min_providers_present` y `min_score` (alias del umbral anterior, mantenido
    aqui por claridad de nombre) son las condiciones DURAS descritas en el
    diseno del Bloque 8: STRONG_CONSENSUS, >=1 proveedor presente, score por
    encima del umbral, cero conflictos, evidencia presente.
    """

    auto_propose_score_threshold: float = 0.90
    min_providers_present: int = 1
    config_version: str = "relation-review-policy-thresholds-1.0.0"

    def __post_init__(self) -> None:
        if isinstance(self.auto_propose_score_threshold, bool) or not isinstance(
            self.auto_propose_score_threshold, (int, float)
        ):
            raise ReviewPolicyConfigError(
                f"auto_propose_score_threshold no numerico: "
                f"{self.auto_propose_score_threshold!r}"
            )
        if not (0.0 < float(self.auto_propose_score_threshold) <= 1.0):
            raise ReviewPolicyConfigError(
                "auto_propose_score_threshold debe estar en (0, 1]: "
                f"{self.auto_propose_score_threshold}"
            )
        object.__setattr__(
            self, "auto_propose_score_threshold",
            float(self.auto_propose_score_threshold),
        )
        if isinstance(self.min_providers_present, bool) or not isinstance(
            self.min_providers_present, int
        ) or self.min_providers_present < 1:
            raise ReviewPolicyConfigError(
                f"min_providers_present debe ser un entero >= 1: "
                f"{self.min_providers_present!r}"
            )

    def to_dict(self) -> dict:
        return {
            "auto_propose_score_threshold": self.auto_propose_score_threshold,
            "min_providers_present": int(self.min_providers_present),
            "config_version": self.config_version,
        }

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


#: Perfil por defecto. Inmutable; recalibrar requiere construir una nueva config
#: (nunca mutar esta instancia).
DEFAULT_REVIEW_POLICY_CONFIG = ReviewPolicyConfig()


# ---------------------------------------------------------------------------
# Resultado de la politica
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReviewPolicyOutcome:
    """Decision de la politica de revision para UN candidato ya evaluado.

    `label` es SIEMPRE uno de `REVIEW_POLICY_LABELS`. `signals` conserva, de
    forma trazable y SIN secretos, los valores de entrada que motivaron la
    decision (para auditoria); `reason` es una frase corta y estable.
    """

    label: str
    reason: str
    signals: Mapping = field(default_factory=dict)
    config_hash: str = ""
    version: str = REVIEW_POLICY_VERSION
    schema: str = REVIEW_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.label not in REVIEW_POLICY_LABELS:
            raise ValueError(
                f"label {self.label!r} no pertenece a REVIEW_POLICY_LABELS "
                f"{REVIEW_POLICY_LABELS}"
            )
        if self.label.upper() in _FORBIDDEN_LABELS:  # defensa en profundidad
            raise ValueError("label prohibido (aprobacion/escritura no permitida)")
        object.__setattr__(self, "signals", MappingProxyType(dict(self.signals)))

    @property
    def is_auto_proposable(self) -> bool:
        return self.label == AUTO_PROPOSABLE

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "reason": self.reason,
            "signals": dict(self.signals),
            "config_hash": self.config_hash,
            "version": self.version,
            "schema": self.schema,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


def _human_required(reason: str, *, config: ReviewPolicyConfig,
                    signals: Optional[dict] = None) -> ReviewPolicyOutcome:
    return ReviewPolicyOutcome(
        label=REVIEW_REQUIRED,
        reason=reason,
        signals=signals or {},
        config_hash=config.config_hash,
    )


def _coerce_bool(value: Any) -> Optional[bool]:
    """`bool` estricto, o `None` si no lo es (fail-closed: nunca adivina)."""
    if isinstance(value, bool):
        return value
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _coerce_score(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def classify_for_review(
    *,
    state: Any,
    recommendation: Any = None,
    score: Any,
    n_decisive: Any = None,
    providers_present: Any,
    has_evidence: Any,
    conflicts: Any,
    config: ReviewPolicyConfig = DEFAULT_REVIEW_POLICY_CONFIG,
) -> ReviewPolicyOutcome:
    """Clasifica un resultado YA CALCULADO del ensemble/consenso.

    Entrada esperada (todo YA CALCULADO por `relations.ensemble.combine` u otra
    fuente equivalente; esta funcion NO recalcula nada de eso):

      * `state`: uno de `external_ai.models.CONSENSUS_STATES`.
      * `recommendation`: informativo (no se usa como puerta dura; la puerta
        dura es `state == STRONG_CONSENSUS`), se conserva en las senales para
        trazabilidad.
      * `score`: score agregado en [-1, 1] (o cualquier numerico); se compara
        con `config.auto_propose_score_threshold`.
      * `n_decisive`: numero de fuentes decisivas (informativo/trazabilidad).
      * `providers_present`: numero de proveedores (local/external) con
        evaluacion real presente.
      * `has_evidence`: `True` si el candidato tiene evidencia textual real.
      * `conflicts`: coleccion de conflictos tipificados (vacia si ninguno).

    Regla AUTO_PROPOSABLE (TODAS deben cumplirse; fail-closed -- si falta una,
    hay duda, o el tipo de un campo no es el esperado, se devuelve
    HUMAN_REQUIRED sin lanzar excepcion):

      1. `state == STRONG_CONSENSUS`
      2. `providers_present >= config.min_providers_present` (>=1 por defecto)
      3. `score >= config.auto_propose_score_threshold`
      4. `len(conflicts) == 0`
      5. `has_evidence is True`

    Cualquier input corrupto (None inesperado, tipo incorrecto, coleccion no
    iterable, etc.) hace que la funcion devuelva HUMAN_REQUIRED en vez de
    lanzar una excepcion no controlada -- salvo errores de PROGRAMACION del
    propio modulo (config invalida), que SI deben fallar ruidosamente.
    """
    if not isinstance(config, ReviewPolicyConfig):
        raise ReviewPolicyConfigError("config debe ser una ReviewPolicyConfig")

    # -- Recogida defensiva de senales (para trazabilidad, incluso si invalidas) --
    raw_signals = {
        "state": state if isinstance(state, str) else repr(state),
        "recommendation": recommendation if isinstance(recommendation, str) else None,
        "score": score if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
        "n_decisive": n_decisive if isinstance(n_decisive, int) and not isinstance(n_decisive, bool) else None,
        "providers_present": providers_present
        if isinstance(providers_present, int) and not isinstance(providers_present, bool) else None,
        "has_evidence": has_evidence if isinstance(has_evidence, bool) else None,
        "conflicts_count": None,
        "auto_propose_score_threshold": config.auto_propose_score_threshold,
        "min_providers_present": config.min_providers_present,
    }

    # -- Validacion FAIL-CLOSED de cada campo, una a una, sin excepcion no controlada --
    if not isinstance(state, str) or state not in CONSENSUS_STATES:
        return _human_required(
            f"state invalido o ausente ({state!r}); requiere revision humana.",
            config=config, signals=raw_signals,
        )

    score_val = _coerce_score(score)
    if score_val is None:
        return _human_required(
            f"score invalido o ausente ({score!r}); requiere revision humana.",
            config=config, signals=raw_signals,
        )
    raw_signals["score"] = score_val

    providers_val = _coerce_int(providers_present)
    if providers_val is None or providers_val < 0:
        return _human_required(
            f"providers_present invalido o ausente ({providers_present!r}); "
            "requiere revision humana.",
            config=config, signals=raw_signals,
        )
    raw_signals["providers_present"] = providers_val

    evidence_val = _coerce_bool(has_evidence)
    if evidence_val is None:
        return _human_required(
            f"has_evidence invalido o ausente ({has_evidence!r}); requiere "
            "revision humana.",
            config=config, signals=raw_signals,
        )
    raw_signals["has_evidence"] = evidence_val

    try:
        conflicts_list = list(conflicts) if conflicts is not None else None
    except TypeError:
        conflicts_list = None
    if conflicts_list is None:
        return _human_required(
            f"conflicts invalido o no iterable ({conflicts!r}); requiere "
            "revision humana.",
            config=config, signals=raw_signals,
        )
    raw_signals["conflicts_count"] = len(conflicts_list)

    n_decisive_val = _coerce_int(n_decisive)
    if n_decisive_val is not None:
        raw_signals["n_decisive"] = n_decisive_val

    # -- Las 5 condiciones duras, TODAS obligatorias --------------------------
    checks: list[tuple[bool, str]] = [
        (state == STRONG_CONSENSUS, f"state={state} (requiere STRONG_CONSENSUS)"),
        (providers_val >= config.min_providers_present,
         f"providers_present={providers_val} (< {config.min_providers_present})"),
        (score_val >= config.auto_propose_score_threshold,
         f"score={score_val} (< umbral {config.auto_propose_score_threshold})"),
        (len(conflicts_list) == 0, f"conflicts={len(conflicts_list)} (>0)"),
        (evidence_val is True, "has_evidence=False"),
    ]
    failed = [detail for ok, detail in checks if not ok]
    if failed:
        return _human_required(
            "condiciones de auto-propuesta no satisfechas: " + "; ".join(failed),
            config=config, signals=raw_signals,
        )

    return ReviewPolicyOutcome(
        label=AUTO_PROPOSABLE,
        reason=(
            f"STRONG_CONSENSUS con score={score_val} >= "
            f"{config.auto_propose_score_threshold}, "
            f"{providers_val} proveedor(es) presente(s), sin conflictos, "
            "con evidencia."
        ),
        signals=raw_signals,
        config_hash=config.config_hash,
    )


__all__ = [
    "REVIEW_POLICY_VERSION",
    "REVIEW_POLICY_SCHEMA",
    "AUTO_PROPOSABLE",
    "REVIEW_REQUIRED",
    "REVIEW_POLICY_LABELS",
    "ReviewPolicyConfigError",
    "ReviewPolicyConfig",
    "DEFAULT_REVIEW_POLICY_CONFIG",
    "ReviewPolicyOutcome",
    "classify_for_review",
]
