# -*- coding: utf-8 -*-
"""Configuracion de la cascada de resolucion.

TODOS los umbrales viven aqui y ninguno esta cableado en el codigo de los pasos.
Motivo: un umbral escondido dentro de un `if` no se puede auditar, ni ablacionar,
ni comparar entre perfiles de juego. La configuracion es inmutable
(`frozen=True`) para que una resolucion no pueda alterar la siguiente.

Los valores por defecto son CONSERVADORES: ante la duda, `REVIEW` o
`CREATE_PROVISIONAL`. Fabricar un nodo canonico equivocado es mas caro que pedir
una revision humana, y `CREATE_PROVISIONAL` existe precisamente para no crear
entidades definitivas a partir de errores de ASR u OCR (dosier 10.4).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .errors import ResolutionConfigError

#: Pasos GENERADORES de candidatos, en el orden por defecto de ejecucion.
#: Ver `docs/v3/04-resolution.md` para por que este orden no es el del enunciado
#: del prompt (`exact → alias → glosario → embeddings → ...`): el catalogo de
#: senales del prompt describe QUE se mira, no en que orden sale mas barato.
GENERATOR_STEPS: tuple[str, ...] = ("exact", "history", "alias", "glossary", "similarity")

#: Pasos MODIFICADORES: no crean candidatos, solo ajustan los existentes.
#: Siempre se ejecutan, aunque un generador haya cortocircuitado la cascada.
MODIFIER_STEPS: tuple[str, ...] = ("context", "types")


@dataclass(frozen=True)
class ResolutionConfig:
    """Umbrales, pesos y orden de la cascada."""

    # -- Orden de la cascada ------------------------------------------------
    step_order: tuple[str, ...] = GENERATOR_STEPS
    #: Pasos desactivados (ablaciones: "sin glosario", "sin embeddings"...).
    disabled_steps: frozenset[str] = frozenset()

    # -- Puntuacion base de cada senal generadora ---------------------------
    exact_score: float = 1.00
    history_score: float = 0.97
    alias_score: float = 0.95
    #: Forma canonica o alias del glosario: tan fiable como un alias del grafo.
    glossary_canonical_score: float = 0.95
    #: Forma HABLADA o ERRONEA: llega justo al umbral de enlace, de modo que
    #: enlaza cuando nada la contradice y cae a REVIEW en cuanto hay conflicto
    #: de tipos o un segundo candidato cerca.
    glossary_variant_score: float = 0.90
    #: La similitud de superficie NUNCA alcanza por si sola el umbral de enlace:
    #: es la senal mas debil y la que mas se parece a adivinar.
    similarity_weight: float = 0.88
    similarity_min: float = 0.50

    # -- Modificadores ------------------------------------------------------
    #: Deliberadamente MAYOR que `ambiguity_margin`: un bonus incapaz de romper
    #: un empate no sirve para desambiguar, que es justo para lo que existe la
    #: senal de contexto. Sigue siendo demasiado pequeno para levantar por si
    #: solo un candidato debil hasta el umbral de enlace.
    context_bonus: float = 0.12
    type_match_bonus: float = 0.03
    type_conflict_penalty: float = 0.35

    # -- Decision -----------------------------------------------------------
    #: A partir de aqui se puede enlazar con una entidad existente.
    link_min_score: float = 0.90
    #: Por debajo de aqui el candidato ni siquiera merece revision humana.
    review_min_score: float = 0.60
    #: Distancia minima al segundo candidato para no considerarlo ambiguo.
    ambiguity_margin: float = 0.10
    #: Senal "fuerte" que permitiria enlazar PESE a un conflicto de tipos.
    #: Por defecto es INALCANZABLE (> 1.0, y las puntuaciones viven en [0,1]):
    #: un conflicto de tipos siempre acaba en REVIEW. El parametro existe para
    #: poder EXPERIMENTAR con la regla y para que las pruebas de mutacion tengan
    #: donde morder, no para relajarla en produccion.
    type_override_score: float = 1.01

    # -- Creacion -----------------------------------------------------------
    allow_create_new: bool = True
    create_new_min_confidence: float = 0.90
    create_new_min_surface_chars: int = 3
    #: Si algun candidato descartado puntua POR ENCIMA de esto, no se acuna un
    #: nodo canonico: se crea una provisional. Traduccion: "si algo del catalogo
    #: ya se le parece remotamente, esto huele a variante de ASR/OCR y no a
    #: entidad nueva". Es la defensa del dosier 10.4 expresada como umbral.
    create_new_max_rival_score: float = 0.30
    provisional_confidence_cap: float = 0.50
    provisional_id_prefix: str = "entity:prov:"
    new_id_prefix: str = "entity:new:"
    resolution_id_prefix: str = "resolution:"
    #: Longitud del digest hexadecimal usado en los identificadores derivados.
    derived_id_digest_chars: int = 16

    # -- Cortocircuito ------------------------------------------------------
    short_circuit: bool = True
    #: Un generador corta la cascada si su mejor candidato llega aqui y es unico.
    short_circuit_score: float = 0.95

    # -- Historial ----------------------------------------------------------
    use_history: bool = True
    record_history: bool = True
    #: Por debajo del tope de confianza de las provisionales (0.50), a
    #: proposito: una provisional DEBE poder alimentar al historial, o la
    #: segunda mencion de la misma entidad volveria a crear otra.
    history_min_confidence: float = 0.40

    # -- Salida -------------------------------------------------------------
    #: Valida el documento emitido contra el JSON Schema congelado. Solo se
    #: desactiva en micro-benchmarks; en produccion emitir sin validar seria
    #: exactamente la clase de fallo que los contratos existen para evitar.
    validate_output: bool = True
    engine_name: str = "s9k.knowledge_v3.resolution"
    engine_version: str = "3.0.0"
    step_name: str = "resolve.identity"

    #: Extensiones por perfil de juego. No se usan todavia (V3 inicial es
    #: `generic`); existe el hueco para no cambiar la firma cuando se use.
    profile_overrides: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = [s for s in self.step_order if s not in GENERATOR_STEPS]
        if unknown:
            raise ResolutionConfigError(f"pasos generadores desconocidos: {unknown}")
        if len(set(self.step_order)) != len(self.step_order):
            raise ResolutionConfigError("step_order tiene pasos repetidos")
        bad = [s for s in self.disabled_steps if s not in GENERATOR_STEPS + MODIFIER_STEPS]
        if bad:
            raise ResolutionConfigError(f"pasos desconocidos en disabled_steps: {sorted(bad)}")
        if not 0.0 <= self.review_min_score <= self.link_min_score <= 1.0:
            raise ResolutionConfigError(
                "se exige 0 <= review_min_score <= link_min_score <= 1"
            )
        if not 0.0 <= self.ambiguity_margin <= 1.0:
            raise ResolutionConfigError("ambiguity_margin fuera de [0,1]")
        if not 0.0 <= self.similarity_min <= 1.0:
            raise ResolutionConfigError("similarity_min fuera de [0,1]")
        if self.derived_id_digest_chars < 8:
            raise ResolutionConfigError(
                "derived_id_digest_chars < 8: colisiones demasiado probables"
            )
        for name in ("provisional_id_prefix", "new_id_prefix", "resolution_id_prefix"):
            value = getattr(self, name)
            if not value or not value[0].isalnum():
                raise ResolutionConfigError(
                    f"{name} debe empezar por caracter alfanumerico (patron stable_id)"
                )

    def active_generators(self) -> tuple[str, ...]:
        """Pasos generadores efectivamente activos, en orden."""
        steps = tuple(s for s in self.step_order if s not in self.disabled_steps)
        if not self.use_history:
            steps = tuple(s for s in steps if s != "history")
        return steps

    def active_modifiers(self) -> tuple[str, ...]:
        return tuple(s for s in MODIFIER_STEPS if s not in self.disabled_steps)

    def without(self, *steps: str) -> "ResolutionConfig":
        """Copia con pasos desactivados. Pensado para ablaciones."""
        return replace(self, disabled_steps=frozenset(self.disabled_steps) | set(steps))


#: Configuracion por defecto compartida. Es inmutable, asi que compartirla es
#: seguro; se expone como constante para que los ablacionados partan de ella.
DEFAULT_CONFIG = ResolutionConfig()

__all__ = ["ResolutionConfig", "DEFAULT_CONFIG", "GENERATOR_STEPS", "MODIFIER_STEPS"]
