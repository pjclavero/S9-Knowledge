# -*- coding: utf-8 -*-
"""Ejes de PREDICADO y DIRECCION, resueltos por estructura y tipos.

Esto NO es un clasificador lexico, y la diferencia no es de estilo: en la
auditoria 00 el clasificador lexico de V2 saca ~70 % de su ganancia de
expresiones calcadas del corpus, 9 de 14 familias de predicado se van a cero en
material real y el 41 % de las salidas es el comodin `RELATED_TO`. Ampliar la
lista de expresiones es, literalmente, "una carrera sin final".

Aqui no hay ni una sola lista de palabras. Las entradas del motor son:

* los `predicate_candidates` que YA vienen puntuados por el extractor (el
  motor no vuelve a leer el texto: no es su trabajo y hacerlo duplicaria el
  modo de fallo);
* la ONTOLOGIA del `GameProfile`: dominio, rango, simetria, inversa,
  funcionalidad;
* los TIPOS de las entidades resueltas.

Y la salida es una eleccion con margen o una abstencion. El motor prefiere
quedarse callado a elegir entre dos candidatos que casi empatan: un empate no
es una eleccion, es un sorteo, y un sorteo repetido un millon de veces es
exactamente como se fabrican 170 falsos positivos por acierto.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..contracts.game_profile import GameProfile
from . import findings as F
from .config import EngineConfig

SUBJECT_TO_OBJECT = "SUBJECT_TO_OBJECT"
OBJECT_TO_SUBJECT = "OBJECT_TO_SUBJECT"
UNDIRECTED = "UNDIRECTED"


@dataclass(frozen=True)
class PredicateSpec:
    """Un predicado tal y como lo define el perfil activo."""

    predicate: str
    domain: frozenset[str]
    range: frozenset[str]
    symmetric: bool = False
    transitive: bool = False
    functional: bool = False
    inverse_of: Optional[str] = None

    def allows(self, subject_type: Optional[str], object_type: Optional[str]) -> bool:
        """Compatibilidad de dominio/rango.

        Un tipo desconocido (None) NO se da por bueno: sin tipo no hay
        comprobacion, y dar por buena una comprobacion que no se ha hecho es
        precisamente lo que hay que evitar.
        """
        if subject_type is None or object_type is None:
            return False
        return subject_type in self.domain and object_type in self.range


class ProfileIndex:
    """Indice del `GameProfile` activo. Solo lectura, construido una vez."""

    def __init__(self, profile: GameProfile):
        self.profile = profile
        self.predicates: dict[str, PredicateSpec] = {}
        for raw in profile.predicates:
            self.predicates[raw["predicate"]] = PredicateSpec(
                predicate=raw["predicate"],
                domain=frozenset(raw["domain"]),
                range=frozenset(raw["range"]),
                symmetric=bool(raw.get("symmetric")),
                transitive=bool(raw.get("transitive")),
                functional=bool(raw.get("functional")),
                inverse_of=raw.get("inverse_of"),
            )
        self.entity_types = frozenset(profile.entity_types)
        self.calendars = frozenset(c["calendar_id"] for c in profile.calendars)
        self.ontology_version = profile.core_ontology_version

    def spec(self, predicate: str) -> Optional[PredicateSpec]:
        return self.predicates.get(predicate)

    def compatible(
        self, predicate: str, subject_type: Optional[str], object_type: Optional[str]
    ) -> bool:
        """True si el predicado encaja en ALGUNA orientacion de la pareja.

        La orientacion concreta la decide el eje de direccion; aqui solo se
        descarta lo imposible en las dos.
        """
        spec = self.spec(predicate)
        if spec is None:
            return False
        return spec.allows(subject_type, object_type) or spec.allows(object_type, subject_type)


# --------------------------------------------------------------------------
# Identidad logica de una relacion
# --------------------------------------------------------------------------
def canonical_key(
    index: ProfileIndex,
    subject_entity_id: str,
    object_entity_id: str,
    predicate: str,
    direction: str,
) -> tuple[str, str, str]:
    """Forma canonica `(sujeto, predicado, objeto)` de una relacion.

    Tres normalizaciones, y las tres son necesarias para que "lo mismo dicho de
    otra manera" se detecte como lo mismo:

    1. **orientacion**: `OBJECT_TO_SUBJECT` se reescribe intercambiando los
       extremos, de modo que solo existe una orientacion canonica;
    2. **simetria**: si el predicado es simetrico, la pareja se ordena — para
       `ALLY_OF`, (A,B) y (B,A) son la MISMA afirmacion;
    3. **inversa**: si el perfil declara `P inverse_of Q`, `(a,P,b)` y
       `(b,Q,a)` son la misma afirmacion; se elige el nombre menor en orden
       alfabetico como representante, que es una regla arbitraria pero TOTAL
       (y por tanto reproducible).

    Sin (3), `MEMBER_OF(Daiki, Casa)` y `HAS_MEMBER(Casa, Daiki)` conviven como
    dos hechos distintos y el detector de contradicciones no ve nada.
    """
    subject, obj = subject_entity_id, object_entity_id
    if direction == OBJECT_TO_SUBJECT:
        subject, obj = obj, subject
    spec = index.spec(predicate)
    if spec is not None and spec.symmetric:
        subject, obj = sorted((subject, obj))
        return (subject, predicate, obj)
    if spec is not None and spec.inverse_of and spec.inverse_of < predicate:
        return (obj, spec.inverse_of, subject)
    return (subject, predicate, obj)


# --------------------------------------------------------------------------
# Eje PREDICADO
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PredicateOutcome:
    predicate: Optional[str]
    confidence: float
    findings: tuple[F.Finding, ...]


def resolve_predicate(
    candidates: list[dict],
    index: ProfileIndex,
    subject_type: Optional[str],
    object_type: Optional[str],
    config: EngineConfig,
) -> PredicateOutcome:
    """Elige el predicado canonico, o no elige.

    Cascada, en este orden y no en otro:

    1. sin candidatos -> `ABSTAIN` (nadie propuso nada que normalizar);
    2. ninguno en la ontologia del perfil -> `REJECT_INVALID`
       (`ONTOLOGY_INCOMPATIBLE`): es una incompatibilidad DEMOSTRABLE contra el
       perfil, no una duda semantica;
    3. alguno en la ontologia pero ninguno compatible con los tipos en ninguna
       orientacion -> `REJECT_INVALID` (`TYPE_INCOMPATIBLE`);
    4. si el ganador global se cayo por (2) o (3), aviso `PREDICATE_DEMOTED`:
       el motor esta eligiendo algo distinto de lo que propuso el extractor y
       eso tiene que verse;
    5. margen insuficiente con el siguiente viable -> `REVIEW_PREDICATE`;
    6. confianza por debajo del umbral -> `REVIEW_PREDICATE`.
    """
    out: list[F.Finding] = []
    if not candidates:
        return PredicateOutcome(None, 0.0, (F.PREDICATE_ABSENT("sin predicate_candidates"),))

    in_profile = [c for c in candidates if index.spec(c["predicate"]) is not None]
    if not in_profile:
        proposed = ", ".join(c["predicate"] for c in candidates)
        return PredicateOutcome(
            None,
            0.0,
            (F.PREDICATE_OUT_OF_ONTOLOGY(f"ninguno en el perfil: {proposed}"),),
        )

    # La comprobacion de tipos solo puede hacerse si HAY tipos. Si la identidad
    # no quedo fijada, el tipo es None y aqui no se declara incompatibilidad:
    # "no lo se" no es "es falso", y `REJECT_INVALID` esta reservado a
    # incompatibilidades DEMOSTRABLES. El eje de existencia ya mando el claim a
    # revision; convertirlo en rechazo lo sacaria de la cola humana para
    # siempre por un dato que faltaba, no por un dato que fuese incorrecto.
    types_known = subject_type is not None and object_type is not None
    viable = (
        [c for c in in_profile if index.compatible(c["predicate"], subject_type, object_type)]
        if types_known
        else list(in_profile)
    )
    if not viable:
        proposed = ", ".join(c["predicate"] for c in in_profile)
        return PredicateOutcome(
            None,
            0.0,
            (
                F.PREDICATE_TYPE_INCOMPATIBLE(
                    f"{proposed} incompatible con ({subject_type}, {object_type})"
                ),
            ),
        )

    winner = viable[0]
    if winner["predicate"] != candidates[0]["predicate"]:
        out.append(
            F.PREDICATE_DEMOTED(
                f"{candidates[0]['predicate']} descartado; se usa {winner['predicate']}"
            )
        )

    if len(viable) > 1:
        margin = float(winner["confidence"]) - float(viable[1]["confidence"])
        if margin < config.min_predicate_margin:
            out.append(
                F.PREDICATE_AMBIGUOUS(
                    f"{winner['predicate']} vs {viable[1]['predicate']}: margen {margin:.3f} "
                    f"< {config.min_predicate_margin}"
                )
            )

    confidence = float(winner["confidence"])
    if confidence < config.min_predicate_confidence:
        out.append(
            F.PREDICATE_LOW_CONFIDENCE(f"{confidence:.3f} < {config.min_predicate_confidence}")
        )
    return PredicateOutcome(winner["predicate"], confidence, tuple(out))


# --------------------------------------------------------------------------
# Eje DIRECCION
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DirectionOutcome:
    direction: Optional[str]
    confidence: float
    findings: tuple[F.Finding, ...]


def resolve_direction(
    candidates: list[dict],
    spec: PredicateSpec,
    subject_type: Optional[str],
    object_type: Optional[str],
    config: EngineConfig,
) -> DirectionOutcome:
    """Fija la direccion, sin darle la vuelta a nada por su cuenta.

    * predicado **simetrico** -> `UNDIRECTED` por ontologia, diga lo que diga
      el extractor (dosier 11.4: `semantic_direction = NONE`). Es la unica vez
      que el motor ignora la propuesta, y puede hacerlo porque no es una
      opinion: es una propiedad declarada del predicado;
    * predicado asimetrico sin direccion propuesta, o propuesta `UNDIRECTED`
      -> `REVIEW_DIRECTION`. Elegir por defecto `SUBJECT_TO_OBJECT` seria
      inventarse el agente de la frase;
    * direccion propuesta **incompatible con los tipos** cuando la contraria si
      encaja -> `REVIEW_DIRECTION`, **nunca un volteo automatico**. Voltear en
      silencio convierte un error del extractor en un hecho del grafo, y el
      humano ya no ve que hubo duda;
    * empate entre las dos direcciones -> `REVIEW_DIRECTION`;
    * confianza por debajo del umbral -> `REVIEW_DIRECTION`.
    """
    out: list[F.Finding] = []
    if spec.symmetric:
        return DirectionOutcome(
            UNDIRECTED, 1.0, (F.SYMMETRIC_PREDICATE(f"{spec.predicate} es simetrico"),)
        )

    if not candidates:
        return DirectionOutcome(None, 0.0, (F.DIRECTION_UNDETERMINED("sin direction_candidates"),))

    winner = candidates[0]
    direction = winner["direction"]
    confidence = float(winner["confidence"])

    if direction == UNDIRECTED:
        return DirectionOutcome(
            None,
            confidence,
            (F.DIRECTION_UNDETERMINED(f"{spec.predicate} no es simetrico y se propuso UNDIRECTED"),),
        )

    if len(candidates) > 1 and abs(confidence - float(candidates[1]["confidence"])) < 1e-9:
        out.append(
            F.DIRECTION_AMBIGUOUS(
                f"{direction} y {candidates[1]['direction']} empatan en {confidence:.3f}"
            )
        )

    types_known = subject_type is not None and object_type is not None
    chosen_ok = (
        spec.allows(subject_type, object_type)
        if direction == SUBJECT_TO_OBJECT
        else spec.allows(object_type, subject_type)
    )
    if types_known and not chosen_ok:
        out.append(
            F.DIRECTION_TYPE_MISMATCH(
                f"{spec.predicate} en {direction} no encaja con ({subject_type}, {object_type}); "
                "la orientacion contraria si — el motor NO la voltea solo"
            )
        )

    if confidence < config.min_direction_confidence:
        out.append(
            F.DIRECTION_LOW_CONFIDENCE(f"{confidence:.3f} < {config.min_direction_confidence}")
        )
    return DirectionOutcome(direction, confidence, tuple(out))
