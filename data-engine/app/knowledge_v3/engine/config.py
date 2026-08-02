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
#: afirmacion del snapshot.
LIVE_STATUSES = frozenset({"PROVISIONAL", "ASSERTED", "CONFIRMED", "LIMITED"})

#: Estados que BLOQUEAN un claim nuevo sobre la misma clave canonica.
#:
#: `CONTRADICTED` esta aqui y NO en `LIVE_STATUSES`, y la diferencia importa:
#: una afirmacion marcada como contradicha no es vigente (nadie ha decidido aun
#: si es cierta), pero tampoco es historia cerrada. Si no bloquease, reafirmar
#: una de las dos caras de un conflicto sin resolver se aprobaria en silencio
#: — bastaria con reprocesar el asset para saltarse la cola humana. Ese fue el
#: hallazgo H2 de la revision independiente.
#:
#: `SUPERSEDED` y `RETRACTED` siguen fuera: eso si es historia.
BLOCKING_STATUSES = LIVE_STATUSES | frozenset({"CONTRADICTED"})

#: Estados de `state` (eje TEMPORAL) que mantienen viva una afirmacion. Una
#: afirmacion ENDED no contradice una nueva: describe otro tramo de tiempo.
LIVE_STATES = frozenset({"ACTIVE", "RECURRING", "UNKNOWN"})

#: El UNICO estatus epistemico que puede aprobarse automaticamente, pase lo que
#: pase en la configuracion. Ampliar `acceptable_epistemic_status` permite que
#: otros estatus lleguen a la cola de revision con su afirmacion ya construida,
#: pero NUNCA que se escriban solos.
ALWAYS_ACCEPTABLE_EPISTEMIC = "ASSERTED"

#: Estatus que jamas pueden entrar en `acceptable_epistemic_status`: "no lo se"
#: y "el corpus dice dos cosas" no son grados de certeza, son ausencias de ella.
NEVER_ACCEPTABLE_EPISTEMIC = frozenset({"UNKNOWN", "CONFLICTED"})

#: Suelo DURO de confianza para aprobar. No es un umbral configurable: es el
#: limite por debajo del cual "aprobado" deja de significar nada. Con todos los
#: umbrales de `EngineConfig` a 0.0 el motor aprobaba a 0.05 (hallazgo H4).
HARD_CONFIDENCE_FLOOR = 0.5


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

    #: Traslada al motor la politica de aprobacion de negaciones. Apagado
    #: conserva la politica historica: el extractor puede seguir solicitando
    #: revision universal. Encendido solo SIMPLE/NEVER limpios pueden aceptar;
    #: las cesaciones se calculan en sombra y todos los demas tipos revisan.
    graduated_negation_policy: bool = False

    #: Activa la graduacion de relativas sin anclaje entre limite desconocido
    #: (WARN) y alcance material (REVIEW). Apagado conserva el finding historico.
    graduated_temporal_policy: bool = False

    #: Evalua, sin autoridad de escritura, que ocurriria si se ignorase
    #: exclusivamente la peticion de review del extractor semantico.
    semantic_shadow_evaluation: bool = False

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

    def __post_init__(self) -> None:
        """Rechaza configuraciones que no son "permisivas" sino inservibles.

        Un umbral bajo es una decision del operador. Un conjunto epistemico que
        acepta `UNKNOWN` no es una decision: es aprobar lo que el propio
        extractor declaro que no supo situar. Se rechaza en la construccion, no
        en la decision, para que el error salga donde se comete.
        """
        if ALWAYS_ACCEPTABLE_EPISTEMIC not in self.acceptable_epistemic_status:
            raise ValueError(
                "acceptable_epistemic_status debe contener 'ASSERTED': un motor que "
                "no aprueba ni lo asertado no aprueba nada"
            )
        forbidden = self.acceptable_epistemic_status & NEVER_ACCEPTABLE_EPISTEMIC
        if forbidden:
            raise ValueError(
                f"estatus epistemicos que nunca pueden aprobarse: {sorted(forbidden)}; "
                "'no lo se' y 'el corpus dice dos cosas' no son grados de certeza"
            )


DEFAULT_CONFIG = EngineConfig()
