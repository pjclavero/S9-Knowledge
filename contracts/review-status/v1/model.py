# -*- coding: utf-8 -*-
"""model.py — vocabulario CANONICO de `review_status` (Carril J, calidad de datos).

Por que existe
--------------
`review_status` se declaraba por su cuenta en CUATRO sitios, con cuatro formas
distintas y ningun punto donde se comparasen:

  1. `data-engine/app/schemas/rpg_schema.py::ALLOWED_REVIEW_STATUS`
     -- minusculas, conjunto cerrado, es lo que se PERSISTE en el grafo.
  2. `viewer/app/labels.py::REVIEW_STATUS_LABELS_ES`
     -- segunda lista, mantenida a mano, que decide que ve el humano.
  3. `contracts/review-ingest/v1/_common-v1.schema.json::candidate_status`
     -- MAYUSCULAS, nueve valores, ciclo de vida del CANDIDATO antes de entrar.
  4. `data-engine/app/review/{auto_decider,approved_writer}.py`
     -- `auto_approve` / `needs_review` / `auto_reject`, y un literal
        `review_status="auto_approved"` que NO pertenece a ninguno de los otros
        tres. Que no cause dano hoy es un accidente afortunado: lo intercepta
        una comparacion de cadena en `review/ingest_approved.py`.

Cual es el canonico y por que
-----------------------------
El canonico de DOMINIO es (1): el conjunto en minusculas que se persiste como
propiedad de nodo/relacion. Razones, en orden:

  * Es el unico que llega al DATO. Lo demas son estados de un proceso; esto es
    el estado del hecho una vez guardado, que es lo que el visor filtra, ordena
    y etiqueta, y lo que sobrevive al pipeline que lo produjo.
  * Ya era cerrado y validado (`field_validator` de `rpg_schema`), asi que
    elegirlo no relaja nada.
  * Los otros tres son FRONTERAS: (3) es un contrato JSON Schema congelado que
    describe otro ciclo de vida (el candidato, antes de existir en el grafo) y
    no se puede ni se debe reescribir; (4) es vocabulario interno de un
    pipeline legacy. A una frontera se le pone un ADAPTADOR, no se le cambia el
    idioma -- y (2) deja de ser una lista para pasar a DERIVARSE de aqui.

Regla dura, la misma del resto del proyecto: **fail-closed**. `normalize` no
tiene default permisivo, no adivina, no repara y no acepta `None`. Un
`review_status` ilegible es un dato invalido, nunca "revisado".

Restriccion de importacion (igual que `knowledge-visibility/v1/model.py`):
solo libreria estandar. Este modulo lo cargan por RUTA tanto `viewer` como
`data-engine`; no conoce a ninguno de los dos.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

CONTRACT_ID = "review-status/v1"


class ReviewStatusError(ValueError):
    """Valor de `review_status` invalido, ausente o fuera del vocabulario."""


class ReviewStatus(str, Enum):
    """Vocabulario CANONICO de dominio. Enum CERRADO.

    No hay estado "aprobado por maquina": el pipeline automatico produce
    `auto_extracted`. Anadir uno seria exactamente el quinto vocabulario que
    este modulo existe para impedir, y ademas mentiria -- un hecho que ningun
    humano ha mirado no esta revisado.
    """

    AUTO_EXTRACTED = "auto_extracted"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"
    CORRECTED = "corrected"


#: Conjunto canonico en crudo, para comprobar cadenas sin construir el enum.
CANONICAL_VALUES: frozenset[str] = frozenset(s.value for s in ReviewStatus)

#: Subconjunto que afirma que un HUMANO decidio sobre el hecho. Es el unico
#: admisible en la via de aprobacion humana (`review/ingest_approved.py`).
#: Se declara aqui, no alli, para que la via humana no pueda volver a
#: comprobarse con una comparacion contra un solo valor prohibido: enumerar lo
#: PROHIBIDO deja pasar todo lo que nadie penso en prohibir.
HUMAN_REVIEWED: frozenset[str] = frozenset(
    {ReviewStatus.REVIEWED.value, ReviewStatus.CORRECTED.value}
)

#: Token LEGACY del pipeline automatico (`review/approved_writer.py`). NO es un
#: valor de dominio y `normalize` lo rechaza: se nombra aqui para que exista un
#: unico sitio donde consta que ese literal circula por el repositorio, y para
#: que la via humana pueda seguir citandolo en su mensaje de error sin
#: redeclararlo.
LEGACY_MACHINE_APPROVED = "auto_approved"


# ---------------------------------------------------------------------------
# Normalizacion (fail-closed)
# ---------------------------------------------------------------------------

def normalize(value: Any) -> ReviewStatus:
    """Convierte un valor crudo en `ReviewStatus`, o levanta.

    No acepta `None`, ni cadena vacia, ni mayusculas, ni el token legacy. La
    ausencia de dato NO es un estado favorable: es un error.
    """
    if not isinstance(value, str):
        raise ReviewStatusError(
            f"review_status invalido o ausente: {value!r} "
            f"(vocabulario canonico: {sorted(CANONICAL_VALUES)})"
        )
    if value not in CANONICAL_VALUES:
        raise ReviewStatusError(
            f"review_status fuera del vocabulario canonico: {value!r} "
            f"(canonico: {sorted(CANONICAL_VALUES)})"
        )
    return ReviewStatus(value)


def is_canonical(value: Any) -> bool:
    try:
        normalize(value)
    except ReviewStatusError:
        return False
    return True


def is_human_reviewed(value: Any) -> bool:
    """True SOLO si el valor es canonico y afirma revision humana."""
    try:
        return normalize(value).value in HUMAN_REVIEWED
    except ReviewStatusError:
        return False


# ---------------------------------------------------------------------------
# ADAPTADOR de frontera 1: contrato `review-ingest/v1` (candidate_status)
# ---------------------------------------------------------------------------
# El contrato describe el ciclo de vida del CANDIDATO, no el del hecho
# persistido, y esta congelado en JSON Schema. La traduccion va en una sola
# direccion (contrato -> dominio) y es CONSERVADORA: ningun estado del
# candidato se traduce a `reviewed` salvo que el contrato afirme una decision
# humana. `AUTO_APPROVABLE` significa "podria aprobarse sin humano", no "un
# humano lo aprobo", y por eso NO cruza a `reviewed`.

_DESDE_CANDIDATE_STATUS: dict[str, ReviewStatus] = {
    "PENDING": ReviewStatus.NEEDS_REVIEW,
    "AUTO_APPROVABLE": ReviewStatus.NEEDS_REVIEW,
    "REQUIRES_REVIEW": ReviewStatus.NEEDS_REVIEW,
    "DEFERRED": ReviewStatus.NEEDS_REVIEW,
    "CONFLICT": ReviewStatus.NEEDS_REVIEW,
    "APPROVED": ReviewStatus.REVIEWED,
    "USE_EXISTING": ReviewStatus.REVIEWED,
    "EDITED": ReviewStatus.CORRECTED,
    "REJECTED": ReviewStatus.REJECTED,
}


def from_candidate_status(value: Any) -> ReviewStatus:
    """Adapta `review-ingest/v1::candidate_status` al vocabulario canonico."""
    if not isinstance(value, str) or value not in _DESDE_CANDIDATE_STATUS:
        raise ReviewStatusError(
            f"candidate_status desconocido: {value!r} "
            f"(admitidos: {sorted(_DESDE_CANDIDATE_STATUS)})"
        )
    return _DESDE_CANDIDATE_STATUS[value]


def candidate_statuses_cubiertos() -> frozenset[str]:
    """Dominio del adaptador, para que un test lo compare con el JSON Schema.

    Si el contrato gana un estado nuevo y este adaptador no lo cubre, la
    traduccion dejaria de ser total y habria que decidir a que se traduce; el
    test lo pone rojo en vez de dejar que caiga en el `raise` en produccion.
    """
    return frozenset(_DESDE_CANDIDATE_STATUS)


# ---------------------------------------------------------------------------
# ADAPTADOR de frontera 2: decisiones del pipeline legacy (`auto_decider`)
# ---------------------------------------------------------------------------

_DESDE_DECISION: dict[str, ReviewStatus] = {
    "auto_approve": ReviewStatus.AUTO_EXTRACTED,
    "needs_review": ReviewStatus.NEEDS_REVIEW,
    "auto_reject": ReviewStatus.REJECTED,
}


def from_pipeline_decision(value: Any) -> ReviewStatus:
    """Adapta `auto_decider.Decision.decision` al vocabulario canonico.

    `auto_approve` -> `auto_extracted`, no `reviewed`: la maquina decidio que no
    hacia falta un humano, y eso no es lo mismo que haber pasado por uno.
    """
    if not isinstance(value, str) or value not in _DESDE_DECISION:
        raise ReviewStatusError(
            f"decision de pipeline desconocida: {value!r} "
            f"(admitidas: {sorted(_DESDE_DECISION)})"
        )
    return _DESDE_DECISION[value]


def decisiones_cubiertas() -> frozenset[str]:
    return frozenset(_DESDE_DECISION)


# ---------------------------------------------------------------------------
# ADAPTADOR de frontera 3: via de revision humana (`cli/review_manual.py`)
# ---------------------------------------------------------------------------
# La CLI de revision manual marca los items con `pending` -> `approved`. Ninguno
# de esos dos valores pertenece al vocabulario canonico, y sin embargo
# `approved` se escribia TAL CUAL como propiedad `review_status` del nodo en
# Neo4j. Consecuencias observables: `rpg_schema.ALLOWED_REVIEW_STATUS` --el
# conjunto cerrado que supuestamente rige esa propiedad-- no lo contiene, y
# `viewer/app/labels.py` no tenia etiqueta para el, asi que la interfaz mostraba
# la cadena cruda. El dato entraba al grafo hablando un idioma que el grafo no
# declara.

_DESDE_REVIEW_MANUAL: dict[str, ReviewStatus] = {
    "pending": ReviewStatus.NEEDS_REVIEW,
    "deferred": ReviewStatus.NEEDS_REVIEW,
    "approved": ReviewStatus.REVIEWED,
    "edited": ReviewStatus.CORRECTED,
    "corrected": ReviewStatus.CORRECTED,
    "rejected": ReviewStatus.REJECTED,
}


def from_review_manual_status(value: Any) -> ReviewStatus:
    """Adapta el vocabulario de la CLI de revision manual al canonico.

    Fail-closed: `auto_approved`, MAYUSCULAS, vacio, `None` o cualquier cadena
    no prevista levantan. No hay traduccion "por parecido".
    """
    if not isinstance(value, str):
        raise ReviewStatusError(f"review_status de revision manual ausente: {value!r}")
    clave = value.strip().lower()
    if clave not in _DESDE_REVIEW_MANUAL:
        raise ReviewStatusError(
            f"review_status de revision manual desconocido: {value!r} "
            f"(admitidos: {sorted(_DESDE_REVIEW_MANUAL)})"
        )
    return _DESDE_REVIEW_MANUAL[clave]


def estados_de_revision_manual_cubiertos() -> frozenset[str]:
    return frozenset(_DESDE_REVIEW_MANUAL)


def etiquetar(value: Any, labels: dict[str, str]) -> Optional[str]:
    """Auxiliar para capas de presentacion: etiqueta o `None` si no es canonico.

    No devuelve el valor crudo como respaldo. Un `review_status` corrupto
    mostrado tal cual se lee como si fuera un estado legitimo del sistema.
    """
    if not is_canonical(value):
        return None
    return labels.get(str(value))
