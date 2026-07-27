# -*- coding: utf-8 -*-
"""Configuracion del motor local: umbrales explicitos y auditables.

Todo umbral que condiciona una decision vive AQUI, con su valor por defecto y
su justificacion. Ninguna regla dura vive aqui: no hay ningun flag capaz de
aprobar una contradiccion, de aceptar sin evidencia verificada ni de dejar que
una senal externa decida. Esas tres no son umbrales, son invariantes, y estan
codificadas en `decision.py` y `planner.py` sin puerta de configuracion.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Identidad del firmante local. `approved_by.provider` es SIEMPRE "local" por
#: contrato; esto es el nombre y la version de quien firma.
ENGINE_NAME = "s9k.engine.local"
ENGINE_VERSION = "3.0.0-engine.1"

#: Paso local que produce las decisiones y el plan (`produced_by_step`).
STEP_DECIDE = "engine.decide"
STEP_PLAN = "engine.plan"

#: Estados de `status` (ciclo de vida del ledger) que hacen VIGENTE a una
#: afirmacion del snapshot. Una afirmacion superada, retractada o ya marcada
#: como contradicha no contradice a nadie.
LIVE_STATUSES = frozenset({"PROVISIONAL", "ASSERTED", "CONFIRMED", "LIMITED"})

#: Estados de `state` (eje TEMPORAL) que mantienen viva una afirmacion. Una
#: afirmacion ENDED no contradice una nueva: describe otro tramo de tiempo.
LIVE_STATES = frozenset({"ACTIVE", "RECURRING", "UNKNOWN"})


@dataclass(frozen=True)
class EngineConfig:
    """Umbrales del motor. Congelados por instancia (frozen) y hasheables.

    Los valores por defecto son deliberadamente conservadores: el historico del
    proyecto (auditoria 00, ~170 falsos positivos por 1 acierto en material
    real) demuestra que el modo de fallo de este sistema es aprobar de mas, no
    abstenerse de mas. Subir estos umbrales reduce escrituras; bajarlos las
    aumenta y hay que justificarlo con numeros, no con intuicion.
    """

    #: Confianza minima del claim para siquiera considerar ACCEPT.
    min_claim_confidence: float = 0.50
    #: Confianza minima del predicado ganador.
    min_predicate_confidence: float = 0.60
    #: Distancia minima entre el predicado ganador y el siguiente VIABLE.
    #: Sin margen no hay eleccion, hay sorteo.
    min_predicate_margin: float = 0.15
    #: Confianza minima de la direccion elegida (predicados no simetricos).
    min_direction_confidence: float = 0.60
    #: Confianza minima de una resolucion de identidad para no ir a revision.
    min_resolution_confidence: float = 0.70
    #: Calidad minima del episodio de origen.
    min_episode_quality: float = 0.50
    #: Confianza minima del fragmento de evidencia.
    min_fragment_confidence: float = 0.50

    #: Estatus epistemicos que pueden aprobarse localmente. Por defecto SOLO
    #: `ASSERTED`: un rumor, una hipotesis, una intencion o una lectura visual
    #: son afirmaciones sobre el discurso, no sobre el mundo.
    acceptable_epistemic_status: frozenset[str] = frozenset({"ASSERTED"})

    #: Un hecho negado es un hecho. Se acepta, pero siempre con aviso.
    accept_negated: bool = True

    #: Vida del plan. Un plan caduca (contrato: `expires_at`).
    plan_ttl_seconds: int = 86400

    #: Emitir ademas la operacion de proyeccion de la arista directa.
    emit_projection: bool = True

    #: Exigir que el texto citado por la evidencia este REALMENTE en el
    #: episodio (comparacion por offsets). Desactivarlo solo tiene sentido en
    #: modalidades sin texto plano, y deja rastro en el plan.
    require_literal_evidence: bool = True

    #: Separar las decisiones REVIEW en un plan propio no aprobado. Sin esto,
    #: un solo claim en revision impide aprobar el lote entero (el validador
    #: congelado prohibe `approved` con REVIEW pendientes).
    split_review_plan: bool = True

    #: Version de ontologia declarada en afirmaciones y plan. Debe coincidir
    #: con `GameProfile.core_ontology_version`; si no, el motor bloquea.
    ontology_version: str | None = None

    #: Codigos de razon descriptivos que el motor puede emitir. Solo
    #: documentacion viva: el conjunto real lo fija `findings.py`.
    extra: dict = field(default_factory=dict)


DEFAULT_CONFIG = EngineConfig()
