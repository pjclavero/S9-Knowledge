"""Local, append-only review queue for Knowledge V3 proposals.

The service deliberately has no dependency on Neo4j, the V3 engine or the
writer.  Human decisions are durable input for a later, separately gated
process; they are never mutation plans.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.authz.scope import UNRESTRICTED, VisibilityScope
from app.labels import negation_code, negation_label
from app.services.v3_glossary_candidates import GlossaryCandidateStore
from app.services.v3_review_store import SQLiteReviewStore

VALID_HUMAN_DECISIONS = frozenset({"APPROVE", "REJECT", "CORRECT"})
VALID_ENGINE_DECISIONS = frozenset({"ACCEPT", "REVIEW", "ABSTAIN", "REJECT_INVALID"})

# Motivos de revisión EN CASTELLANO, uno por cada código que el motor puede
# emitir de verdad. La lista de arriba mapeaba 7 códigos y NINGUNO de los
# reales: el 100 % de los motivos llegaba al operador como código crudo (y
# duplicado, "CODIGO: CODIGO"). La cobertura la fija un caso que deriva los
# emitibles del catálogo del motor (`engine.findings.emittable_reason_codes`)
# y exige que esta tabla y aquél sean el MISMO conjunto, para que no puedan
# volver a desalinearse en silencio.
REASON_LABELS = {
    # -- canónicos del contrato: el motivo de la DECISIÓN -------------------
    "REVIEW_ENTITY": "Hay dudas sobre a qué entidad se refiere la frase.",
    "REVIEW_EVIDENCE": "La evidencia del texto no basta para decidir sin una persona.",
    "REVIEW_PREDICATE": "No está claro qué relación afirma la frase.",
    "REVIEW_DIRECTION": "No está claro en qué sentido va la relación.",
    "REVIEW_TEMPORALITY": "No está claro cuándo ocurre o deja de ocurrir.",
    "CONFLICT_WITH_EXISTING": "Contradice algo que ya está registrado.",
    "INSUFFICIENT_EVIDENCE": "No hay evidencia suficiente para afirmarlo.",
    "AMBIGUOUS_SEMANTICS": "La frase admite más de una lectura.",
    "DEMONSTRABLY_FALSE": "Es falso de forma demostrable y no se admite.",
    "TYPE_INCOMPATIBLE": "Los tipos de las entidades no admiten esta relación.",
    "ONTOLOGY_INCOMPATIBLE": "La relación no existe en la ontología aplicable.",
    "LOW_QUALITY_EPISODE": "El fragmento de origen es de calidad demasiado baja.",
    # -- veredicto ACCEPT ---------------------------------------------------
    "LOCAL_APPROVED": "Aprobada por el motor sin reservas.",
    "LOCAL_APPROVED_WITH_WARNINGS": "Aprobada por el motor, pero con avisos.",
    # -- existencia / identidad de entidad ----------------------------------
    "UNRESOLVED_MENTION": "Una mención del texto no se ha podido asociar a ninguna entidad.",
    "ENTITY_NOT_IN_SNAPSHOT": "La entidad no existe en el grafo con el que se comparó.",
    "ENTITY_PROVISIONAL": "La entidad es provisional: aún no está dada de alta de verdad.",
    "ENTITY_RESOLUTION_DEFERRED": "La identificación de la entidad quedó pendiente.",
    "ENTITY_LOW_CONFIDENCE": "La entidad se identificó con poca confianza.",
    "ENTITY_ROLE_AMBIGUOUS": "No está claro cuál de las entidades hace cada papel.",
    "ENTITY_TYPE_UNKNOWN": "No se sabe de qué tipo es la entidad.",
    "SELF_RELATION": "La relación une una entidad consigo misma.",
    "CLAIM_ABSTAINED_UPSTREAM": "Un paso anterior de la cadena ya se abstuvo sobre esta afirmación.",
    # -- evidencia ----------------------------------------------------------
    "EVIDENCE_FRAGMENT_UNKNOWN": "No se sabe de qué fragmento del texto sale la afirmación.",
    "EVIDENCE_EPISODE_UNKNOWN": "No se sabe de qué episodio sale la afirmación.",
    "EVIDENCE_FOREIGN_ASSET": "La evidencia apunta a un material que no es el de esta fuente.",
    "EVIDENCE_TEXT_MISMATCH": "La cita no coincide con el texto del episodio.",
    "EVIDENCE_OFFSETS_OUT_OF_RANGE": "La cita señala una parte del texto que no existe.",
    "EVIDENCE_NOT_VERIFIABLE": "La cita no se ha podido verificar contra el texto.",
    "EVIDENCE_LOW_CONFIDENCE": "La evidencia se extrajo con poca confianza.",
    "EVIDENCE_LITERAL_VERIFIED": "La cita coincide literalmente con el texto del episodio.",
    "EXTRACTOR_REQUESTED_REVIEW": "Quien extrajo la afirmación pidió que la mirase una persona.",
    "CLAIM_LOW_CONFIDENCE": "La afirmación se extrajo con poca confianza.",
    "CONFIDENCE_BELOW_HARD_FLOOR": "La confianza está por debajo del mínimo que nunca se aprueba.",
    # -- estado epistémico --------------------------------------------------
    "EPISTEMIC_NOT_ASSERTED": "El texto no afirma esto: lo supone, lo pregunta o lo desea.",
    "EPISTEMIC_UNKNOWN": "No se sabe si el texto afirma esto o sólo lo menciona.",
    "EPISTEMIC_VISUAL_INFERRED": "Se dedujo de una imagen, no de algo dicho en el texto.",
    # -- predicado ----------------------------------------------------------
    "PREDICATE_ABSENT": "No se ha identificado ninguna relación en la frase.",
    "PREDICATE_AMBIGUOUS": "Hay más de una relación plausible para la frase.",
    "PREDICATE_LOW_CONFIDENCE": "La relación se identificó con poca confianza.",
    "PREDICATE_DEMOTED": "Se descartó una relación más específica por falta de apoyo.",
    "PREDICATE_OUT_OF_ONTOLOGY": "La relación no figura en la ontología aplicable.",
    "PREDICATE_TYPE_INCOMPATIBLE": "Los tipos de las entidades no admiten esta relación.",
    # -- dirección ----------------------------------------------------------
    "DIRECTION_AMBIGUOUS": "La frase admite la relación en los dos sentidos.",
    "DIRECTION_UNDETERMINED": "No se ha podido determinar el sentido de la relación.",
    "DIRECTION_LOW_CONFIDENCE": "El sentido de la relación se decidió con poca confianza.",
    "DIRECTION_TYPE_MISMATCH": "El sentido propuesto no encaja con los tipos de las entidades.",
    "SYMMETRIC_PREDICATE": "La relación es simétrica: el sentido da igual.",
    # -- contradicción ------------------------------------------------------
    "CONTRADICTS_VIGENTE_ASSERTION": "Contradice algo que ahora mismo consta como vigente.",
    "CONTRADICTS_CLAIM_IN_BATCH": "Contradice otra afirmación de esta misma ingesta.",
    "DIRECTION_CONFLICT_WITH_VIGENTE": "El sentido contradice el de algo ya registrado.",
    "DIRECTION_CONFLICT_IN_BATCH": "El sentido contradice el de otra afirmación de esta ingesta.",
    "FUNCTIONAL_PREDICATE_CONFLICT": "Esta relación sólo admite un valor y ya hay otro registrado.",
    "FUNCTIONAL_CONFLICT_IN_BATCH": "Esta relación sólo admite un valor y esta ingesta trae dos.",
    "REAFFIRMS_CONTRADICTED_ASSERTION": "Vuelve a afirmar algo que ya había sido contradicho.",
    "ALREADY_ASSERTED": "Ya constaba registrado: no añade nada nuevo.",
    "DUPLICATE_IN_BATCH": "Aparece repetida dentro de esta misma ingesta.",
    # -- negación -----------------------------------------------------------
    "NEGATED_CLAIM": "La frase niega la relación en vez de afirmarla.",
    "NEGATION_ABSOLUTE": "La negación es absoluta: niega que haya ocurrido nunca.",
    "NEGATION_NOT_YET": "La frase dice que aún no ha ocurrido, no que no vaya a ocurrir.",
    "NEGATION_SCOPE_AMBIGUOUS": "No está claro qué parte de la frase queda negada.",
    "NEGATION_NOT_ACCEPTED": "Las negaciones no se aprueban solas en este ámbito.",
    "NEGATION_POLICY_REVIEW": "La política vigente manda revisar a mano las negaciones.",
    "UNKNOWN_NEGATION_KIND": "No se reconoce de qué tipo es la negación.",
    "CESSATION_SHADOW_PLAN": "El cierre de la relación se ha planificado sólo en simulación.",
    "CESSATION_MULTIPLE_ACTIVE": "Hay varias relaciones vigentes y no se sabe cuál cierra la frase.",
    # -- temporalidad -------------------------------------------------------
    "TEMPORAL_UNSPECIFIED": "El texto no dice cuándo ocurre.",
    "TEMPORAL_BOUND_UNKNOWN": "Falta uno de los dos extremos del periodo.",
    "TEMPORAL_FRAGMENT_UNKNOWN": "No se sabe de qué parte del texto sale la fecha.",
    "TEMPORAL_UNRESOLVED_RELATIVE": "Hay una fecha relativa que no se ha podido anclar a una real.",
    "TEMPORAL_CALENDAR_UNKNOWN": "No se sabe a qué calendario pertenece la fecha.",
    "TEMPORAL_CALENDAR_MIXED": "Se mezclan fechas de calendarios distintos.",
    "TEMPORAL_CONFLICTING_EXPRESSIONS": "El texto da fechas que no concuerdan entre sí.",
    "TEMPORAL_INTERVAL_INVERTED": "El periodo acaba antes de empezar.",
    "TEMPORAL_SCOPE_MATERIAL": "El alcance temporal cambia lo que la afirmación significa.",
    "CESSATION_CLOSES_ASSERTION": "La frase cierra una relación que estaba vigente.",
    "CESSATION_WITHOUT_ACTIVE_ASSERTION": "Cierra una relación que no consta vigente.",
    "CESSATION_TARGET_UNANCHORED": "No se sabe con certeza qué relación cierra la frase.",
    # -- autoridad de la propuesta -----------------------------------------
    "OLLAMA_PROPOSAL": "La propuesta la sugirió un modelo local.",
    "EXTERNAL_PROPOSAL": "La propuesta la sugirió un modelo externo.",
    "EXTERNAL_SIGNAL_CONSULTED": "Se consultó a un modelo externo como segunda opinión.",
    "EXTERNAL_SIGNAL_DISSENTS": "Un modelo externo no está de acuerdo con la propuesta.",
}

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


# Códigos ESTABLES de rechazo de la cola de revisión (contrato observable).
# Sostienen garantías del RC (identidad durable de la historia append-only,
# unicidad de `request_id`, parcialidad de la cola). Las pruebas que sostienen
# esas garantías comprueban TIPO + CÓDIGO, nunca la redacción del mensaje.
REVIEW_ERROR = "REVIEW_ERROR"
MISSING_FIELD = "MISSING_FIELD"
EVIDENCE_OFFSETS_REQUIRED = "EVIDENCE_OFFSETS_REQUIRED"
EVIDENCE_OFFSETS_OUT_OF_RANGE = "EVIDENCE_OFFSETS_OUT_OF_RANGE"
EVIDENCE_LITERAL_MISMATCH = "EVIDENCE_LITERAL_MISMATCH"
PACKAGE_CORRUPT = "PACKAGE_CORRUPT"
PACKAGE_INVALID = "PACKAGE_INVALID"
#: AUSENCIA != CERO. El almacén de propuestas puede estar en TRES estados que
#: no son el mismo hecho, y hasta el Corte 4 los tres se presentaban como
#: «no hay propuestas»:
#:
#:   - NO ESTÁ           -> `PROPOSALS_STORE_MISSING`     (no se sabe nada)
#:   - ESTÁ Y NO SE LEE  -> `PROPOSALS_STORE_UNREADABLE`  (no se sabe nada)
#:   - ESTÁ, SE LEE, 0   -> lista vacía                   (SÍ se sabe: no hay)
#:
#: Sólo el tercero es una respuesta. Los dos primeros son ausencia de dato, y
#: decirle al operador «no hay nada que revisar» cuando el almacén no está es
#: una afirmación falsa y tranquilizadora: le hace dar por buena una ingesta
#: cuyas ambigüedades no ha visto.
PROPOSALS_STORE_MISSING = "PROPOSALS_STORE_MISSING"
PROPOSALS_STORE_UNREADABLE = "PROPOSALS_STORE_UNREADABLE"
PROPOSAL_INVALID = "PROPOSAL_INVALID"
INVALID_HUMAN_DECISION = "INVALID_HUMAN_DECISION"
REQUEST_ID_REUSED = "REQUEST_ID_REUSED"
PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
SUPERSEDED_DECISION_MISMATCH = "SUPERSEDED_DECISION_MISMATCH"
NO_ACTIVE_DECISION = "NO_ACTIVE_DECISION"
#: `CORRECT` cuyos campos coinciden TODOS con la propuesta: no hay corrección
#: que registrar, y fabricar una sería el defecto F-7 por la otra puerta.
CORRECTION_WITHOUT_CHANGE = "CORRECTION_WITHOUT_CHANGE"
STALE_REVIEW = "STALE_REVIEW"

HISTORY_INTEGRITY = "HISTORY_INTEGRITY"
HISTORY_ENTRY_NOT_OBJECT = "HISTORY_ENTRY_NOT_OBJECT"
HISTORY_CHAIN_BROKEN = "HISTORY_CHAIN_BROKEN"
HISTORY_HASH_INVALID = "HISTORY_HASH_INVALID"
HISTORY_DUPLICATE_ID = "HISTORY_DUPLICATE_ID"
HISTORY_INVALID_JSON = "HISTORY_INVALID_JSON"


class ReviewError(ValueError):
    """Invalid proposal, decision or append-only history.

    Carries a stable ``code``: behaviour, not wording, is what callers and
    tests are allowed to depend on.
    """

    code = REVIEW_ERROR

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code


#: LO QUE SE LE DICE AL OPERADOR CUANDO EL ALMACÉN NO SE PUDO CONSULTAR.
#:
#: Vive en el SERVICIO, no en un router, porque tiene DOS superficies: la
#: consola del chasis (`/panel/review`) y el visor auxiliar (`/v3/review`).
#: Ese fue justamente el defecto del primer intento de este corte —una función
#: con dos consumidores y sólo uno actualizado—, así que el texto no se vuelve
#: a escribir en cada sitio.
#:
#: Ni ruta, ni traza, ni `str(exc)`: el mensaje de la excepción lleva el
#: directorio dentro y el repositorio es público. Lo que sale es esta frase y
#: el código estable.
PROPOSALS_STORE_MESSAGES = {
    PROPOSALS_STORE_MISSING: (
        "El almacen de propuestas de revision NO ESTA. Esto no significa que no "
        "haya nada que revisar: significa que no se sabe. Lo habitual es que el "
        "worker que ejecuta la ingesta y este visor no esten resolviendo "
        "S9K_V3_REVIEW_PROPOSALS_DIR al mismo almacenamiento."
    ),
    PROPOSALS_STORE_UNREADABLE: (
        "El almacen de propuestas de revision existe pero NO SE PUEDE LEER. "
        "Tampoco significa que no haya nada que revisar: revisa los permisos "
        "del directorio en el servidor."
    ),
}


def store_unavailable_view(exc: "ReviewError") -> dict[str, str]:
    """La ausencia del almacén, lista para pintar. Código estable + frase."""
    code = getattr(exc, "code", PROPOSALS_STORE_MISSING)
    return {
        "code": code,
        "message": PROPOSALS_STORE_MESSAGES.get(
            code, PROPOSALS_STORE_MESSAGES[PROPOSALS_STORE_MISSING]
        ),
    }


class ProposalStoreUnavailable(ReviewError):
    """El almacén de propuestas no se pudo CONSULTAR.

    Se distingue de `ReviewError` a secas porque el desenlace del operador es
    otro: un paquete corrupto es un fallo de exportación del motor; un almacén
    que no está —o que no se puede leer— es, casi siempre, que escritor y
    lector no comparten `S9K_V3_REVIEW_PROPOSALS_DIR`, o un permiso mal puesto
    en el servidor. Lo que NO es, en ninguno de los dos casos, es «no hay nada
    que revisar».
    """

    code = PROPOSALS_STORE_MISSING


class HistoryIntegrityError(ReviewError):
    """The JSONL decision history is malformed or its hash chain is broken."""

    code = HISTORY_INTEGRITY


class StaleReviewError(ReviewError):
    """The proposal changed after it was rendered to the reviewer."""

    code = STALE_REVIEW

    def __init__(self, current: dict[str, Any]):
        super().__init__("STALE_REVIEW: la propuesta cambió; revisa su versión actual")
        self.current = current


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def proposal_hash(proposal: dict[str, Any]) -> str:
    """Hash of canonical proposal content, excluding its self-referential hash."""
    loader_metadata = {
        "proposal_hash",
        "package_origins",
        "available_version_hashes",
        "legacy_proposal_hash",
    }
    return _sha256({key: value for key, value in proposal.items() if key not in loader_metadata})


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.RLock())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _non_empty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReviewError(f"falta {field}", MISSING_FIELD)
    return text


def _proposal_id(proposal: dict[str, Any]) -> str:
    return _non_empty(
        proposal.get("proposal_id") or proposal.get("claim_id") or proposal.get("decision_id"),
        "proposal_id",
    )


def _evidence_parts(proposal: dict[str, Any]) -> tuple[str, str, str]:
    episode_text = str(proposal.get("episode_text") or "")
    evidence = proposal.get("evidence") or {}
    try:
        start = int(evidence["start"])
        end = int(evidence["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewError("evidence.start y evidence.end son obligatorios",
                          EVIDENCE_OFFSETS_REQUIRED) from exc
    if start < 0 or end < start or end > len(episode_text):
        raise ReviewError("offsets de evidencia fuera del episodio",
                          EVIDENCE_OFFSETS_OUT_OF_RANGE)
    literal = episode_text[start:end]
    declared = evidence.get("literal_text")
    if declared is not None and declared != literal:
        raise ReviewError("evidence.literal_text no coincide con los offsets",
                          EVIDENCE_LITERAL_MISMATCH)
    return episode_text[:start], literal, episode_text[end:]


# ===========================================================================
# F-7 — EL ACTA NO AFIRMA UNA CORRECCIÓN QUE EL REVISOR NO HIZO
# ===========================================================================
# EL DEFECTO, medido por HTTP: pulsar «Aprobar» sin tocar nada, con el
# formulario TAL COMO LO MANDA EL NAVEGADOR, grababa en el acta
#
#     "human_decision": "APPROVE"   junto a   "correction": {"scope": "not_available"}
#
# El campo Alcance del formulario viene precargado con `item.proposal.scope`, y
# el exportador real escribe ahí el literal `not_available` cuando el claim no
# trae alcance. El navegador lo reenvía —hace lo que debe— y el servidor lo
# recogía como CORRECCIÓN DEL HUMANO. La cadena `decision_audit`, encadenada
# por hash, firmaba así una afirmación FALSA sobre lo que hizo la persona.
#
# LA REGLA, y es de servidor: una corrección existe cuando el valor enviado
# DIFIERE del que traía la propuesta. Nada más. No se parchea el formulario
# —quitar el `value=` dejaría la pantalla peor y el siguiente consumidor con el
# mismo agujero—: se compara aquí, en `record()`, que es el embudo por el que
# pasan la ruta HTML y cualquier llamador programático.
#
# AUSENCIA NO ES CERO, también aquí. Si la propuesta NO trae `negated` y el
# operador marca «Afirmativa», eso SÍ es una corrección real (ausente -> False)
# y se registra como tal. Colapsar ausente sobre `False` perdería una decisión
# humana legítima, que es el error simétrico de la corrección fantasma.

#: Campos de corrección que tienen contrapartida en la propuesta y, por tanto,
#: se pueden COMPARAR. Los demás campos del formulario (alias observado, forma
#: hablada, tipo sugerido, error OCR/ASR…) son aportación del humano sin
#: original contra el que medir: si vienen rellenos, son suyos, y se conservan.
CAMPOS_COMPARABLES_CON_LA_PROPUESTA = ("predicate", "direction", "negated", "scope")


def _correccion_efectiva(
    correction: Mapping[str, Any] | None,
    claim: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Separa lo que el humano CAMBIÓ de lo que sólo reenvió igual.

    Devuelve `(correction, changes)`:

    * `correction` conserva la forma de siempre —campo -> valor nuevo—, porque
      la consume `_glossary_outbox_payload` y el resto del producto. Lo único
      que cambia es que ya no lleva campos idénticos a la propuesta.
    * `changes` es el `before`/`after` REAL de cada campo comparable que sí
      cambió. El autor, el momento y el ámbito no se duplican aquí: ya están en
      el acta (`reviewer`, `timestamp`, `workspace`), y el `record_hash` los
      firma junto con esto.

    Un campo comparable AUSENTE del formulario (el operador dejó «Mantener») no
    llega hasta aquí: la ruta lo descarta antes. Lo que sí llega —y es el caso
    del defecto— es el campo RELLENO con el mismo valor que ya tenía.
    """
    efectiva: dict[str, Any] = {}
    cambios: dict[str, dict[str, Any]] = {}
    for campo, valor in (correction or {}).items():
        if campo not in CAMPOS_COMPARABLES_CON_LA_PROPUESTA:
            # Sin original contra el que comparar: es aportación del humano.
            efectiva[campo] = valor
            continue
        anterior = claim.get(campo, _AUSENTE)
        if anterior is not _AUSENTE and _mismo_valor(anterior, valor):
            # IDÉNTICO A LA PROPUESTA -> no es una corrección. Se cae.
            continue
        efectiva[campo] = valor
        cambios[campo] = {
            "before": None if anterior is _AUSENTE else anterior,
            #: Distingue «la propuesta decía `null`» de «la propuesta no traía
            #: el campo». Sin esto, el acta no podría afirmar cuál de las dos.
            "before_present": anterior is not _AUSENTE,
            "after": valor,
        }
    return efectiva, cambios


class _Ausente:
    """Centinela: «la propuesta no trae este campo». No es `None` ni `False`."""

    def __repr__(self) -> str:  # pragma: no cover - diagnóstico
        return "<AUSENTE>"


_AUSENTE = _Ausente()


def _mismo_valor(anterior: Any, nuevo: Any) -> bool:
    """Igualdad ESTRICTA en el tipo, para que `False` no iguale a `0` ni a `""`.

    `True == 1` en Python, y un `negated` comparado a la ligera contra un `1`
    heredado diría «no cambió» cuando sí. Se exige el mismo tipo booleano.
    """
    if isinstance(anterior, bool) or isinstance(nuevo, bool):
        return anterior is nuevo
    if isinstance(anterior, str) and isinstance(nuevo, str):
        return anterior.strip() == nuevo.strip()
    return anterior == nuevo


def reason_label(code: str) -> str:
    """Return a human explanation, preserving unknown codes verbatim."""
    return REASON_LABELS.get(code, code)


def _engine_review_paths():
    """Puente hacia el resolvedor CANÓNICO, que vive en el motor.

    Mismo patrón que `app.jobs_client`: se añade `data-engine/app/` a `sys.path`
    y se importa el paquete top-level, nunca `app.*` (el visor ya publica su
    propio paquete `app` y la colisión fallaría en silencio).

    La dirección es visor -> motor porque la contraria no existe: el motor no
    puede importar el visor por esa misma colisión de nombres.
    """
    data_engine_app_dir = Path(__file__).resolve().parents[3] / "data-engine" / "app"
    if str(data_engine_app_dir) not in sys.path:
        sys.path.insert(0, str(data_engine_app_dir))
    from knowledge_v3 import review_paths  # type: ignore

    return review_paths


def default_proposals_dir() -> Path:
    """El almacén de propuestas. NO se resuelve aquí: se delega.

    Esta función existía derivando la ruta por su cuenta mientras el motor
    derivaba la suya. Dos derivaciones de una ruta son dos verdades, y el
    síntoma —motor escribiendo en una carpeta, visor mirando otra— se lee como
    «no hay nada que revisar». Desde el Corte 3 la única derivación del producto
    está en `knowledge_v3.review_paths.default_proposals_dir`.

    FALLA CERRADO: si el motor no está montado no se inventa una ruta de
    repuesto, porque una ruta de repuesto es exactamente la segunda verdad.
    """
    try:
        return _engine_review_paths().default_proposals_dir()
    except ImportError as exc:  # pragma: no cover - entorno sin data-engine
        raise RuntimeError(
            "No se puede resolver el almacén de propuestas de revisión: el "
            "motor (data-engine) no está disponible."
        ) from exc


def default_decisions_path() -> Path:
    configured = os.environ.get("S9K_V3_REVIEW_DECISIONS_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "output" / "reviews-v3" / "decisions.jsonl"


def default_audit_path() -> Path:
    return default_decisions_path().with_name("audit.jsonl")


def default_database_path() -> Path:
    configured = os.environ.get("S9K_V3_REVIEW_DATABASE_PATH")
    if configured:
        return Path(configured)
    return default_decisions_path().with_name("review.sqlite3")


def default_glossary_root() -> Path:
    configured = os.environ.get("S9K_V3_GLOSSARY_CANDIDATES_DIR")
    if configured:
        return Path(configured)
    return default_decisions_path().parent / "glossary-candidates"


def _candidate_views(
    explicit: Any,
    reconciled: Any,
    value_key: str,
) -> list[dict[str, Any]]:
    source = explicit if isinstance(explicit, list) and explicit else reconciled
    if not isinstance(source, list):
        return []
    views: list[dict[str, Any]] = []
    for candidate in source:
        if not isinstance(candidate, dict):
            continue
        origin = candidate.get("origin") if isinstance(candidate.get("origin"), dict) else {}
        value = candidate.get("value") or candidate.get(value_key)
        if not value:
            continue
        views.append({
            "value": str(value),
            "confidence": candidate.get("confidence"),
            "extractor": (
                candidate.get("extractor")
                or candidate.get("provider")
                or origin.get("name")
                or origin.get("provider")
            ),
            "proposal_id": candidate.get("proposal_id"),
        })
    return views


def _package_plan_context(raw: Any) -> dict[str, Any] | None:
    """El bloque `plan_context` del SOBRE del paquete, si la corrida lo dejo.

    Es lo que convierte una aprobacion en un plan aplicable: el ancla de
    estado, la procedencia de la fuente y la decision de motor de cada
    propuesta. Los paquetes anteriores al corte de Apply no lo traen, y
    entonces sus propuestas no se pueden sellar — lo que se DICE con un codigo,
    en vez de producir un plan a medias.

    No se deriva nada aqui: o esta en el sobre, o no esta.
    """
    if not isinstance(raw, dict):
        return None
    contexto = raw.get("plan_context")
    return contexto if isinstance(contexto, dict) and contexto else None


def _package_run_id(raw: Any) -> str | None:
    """`job_id` de la corrida que escribió el paquete, si lo declara.

    Los paquetes anteriores al Corte 4 no traen bloque `run`. Se devuelve
    `None` y la propuesta queda SIN corrida atribuida, que es la verdad: no
    se inventa una. La pantalla lo dice con «sin corrida declarada», no con un
    hueco en blanco que se lea como si no hubiera pasado nada.
    """
    if not isinstance(raw, dict):
        return None
    run = raw.get("run")
    if not isinstance(run, dict):
        return None
    job_id = run.get("job_id")
    return str(job_id) if job_id else None


def load_proposals(directory: Path) -> list[dict[str, Any]]:
    """Load and deterministically fold immutable proposal packages.

    Identical versions are deduplicated while retaining every package origin.
    Different hashes for one logical id remain versions; the deterministic
    package order selects one active version without depending on load order.
    """
    # --- LOS TRES DESENLACES, SEPARADOS EN EL ORIGEN -----------------------
    #
    # Antes del Corte 4 esto era `if not directory.exists(): return []`, es
    # decir AUSENCIA == LISTA VACÍA: exactamente la doctrina que el panel B
    # declara prohibida, incumplida en este módulo. El caso ILEGIBLE era peor,
    # porque no hacía falta ni esa línea: `exists()` devuelve True y
    # `Path.glob` SE TRAGA EL `PermissionError` EN SILENCIO, de modo que un
    # directorio con permisos rotos producía, sin un solo error, la misma
    # lista vacía que un almacén legítimamente vacío.
    #
    # Por eso la lectura ya no se hace con `glob`: se hace con `os.listdir`,
    # que SÍ levanta. Un listado que no puede fallar no puede distinguir.
    if not directory.exists():
        raise ProposalStoreUnavailable(
            f"almacén de propuestas ausente: {directory}", PROPOSALS_STORE_MISSING
        )
    if not directory.is_dir():
        raise ProposalStoreUnavailable(
            f"la ruta del almacén de propuestas no es un directorio: {directory}",
            PROPOSALS_STORE_UNREADABLE,
        )
    try:
        entries = sorted(os.listdir(directory))
    except OSError as exc:
        raise ProposalStoreUnavailable(
            f"almacén de propuestas ilegible: {directory}", PROPOSALS_STORE_UNREADABLE
        ) from exc
    versions: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    #: `contexts_by_proposal`: el `plan_context` de CADA corrida que produjo la
    #: propuesta, indexado por `job_id`. Se acumula al lado de `package_runs` y
    #: por la misma razón: una propuesta puede venir de varias corridas, y
    #: sellar el plan de la corrida A con el ancla de estado de la B sería
    #: aplicar sobre un snapshot que nadie observó en esa corrida.
    contexts_by_proposal: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    #: `package_runs`: las corridas que produjeron cada versión. Se acumula
    #: junto a `package_origins` y por la misma razón — una propuesta puede
    #: venir de varias corridas y ninguna debe perderse.
    runs_by_version: dict[tuple[str, str, str], set[str]] = {}
    for path in [directory / name for name in entries if name.endswith(".json")]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReviewError(f"paquete corrupto: {path}", PACKAGE_CORRUPT) from exc
        except OSError as exc:
            # Un paquete que no se puede ABRIR no es un paquete corrupto: es
            # almacén ilegible. Confundirlos manda al operador a revisar la
            # exportación del motor cuando lo que hay es un permiso.
            raise ProposalStoreUnavailable(
                f"paquete de propuestas ilegible: {path}", PROPOSALS_STORE_UNREADABLE
            ) from exc
        package_run = _package_run_id(raw)
        package_context = _package_plan_context(raw)
        documents = raw if isinstance(raw, list) else raw.get("items", [raw])
        if not isinstance(documents, list):
            raise ReviewError(f"paquete inválido: {path}", PACKAGE_INVALID)
        for proposal in documents:
            if not isinstance(proposal, dict):
                raise ReviewError(f"propuesta inválida: {path}", PROPOSAL_INVALID)
            identifier = _proposal_id(proposal)
            workspace = _non_empty(proposal.get("workspace"), "workspace")
            _non_empty(proposal.get("source_id"), "source_id")
            _non_empty(proposal.get("episode_id"), "episode_id")
            _evidence_parts(proposal)
            actual_hash = proposal_hash(proposal)
            declared_hash = proposal.get("proposal_hash")
            # Legacy exporters used a different self-hash. Accept it as input,
            # but canonicalise every loaded version at this trust boundary.
            normalized = json.loads(_canonical(proposal))
            normalized["proposal_hash"] = actual_hash
            by_hash = versions.setdefault((workspace, identifier), {})
            if package_run and package_context:
                # El bloque se recorta a ESTA propuesta: el sobre trae las
                # decisiones de todas las del paquete, y arrastrarlas enteras
                # a cada una multiplicaría el mismo dato por N.
                propias = (package_context.get("decisions") or {}).get(identifier)
                recorte = {
                    clave: valor
                    for clave, valor in package_context.items()
                    if clave != "decisions"
                }
                recorte["decisions"] = {identifier: propias} if propias else {}
                contexts_by_proposal.setdefault(
                    (workspace, identifier), {}
                )[package_run] = recorte
            if package_run:
                runs_by_version.setdefault(
                    (workspace, identifier, actual_hash), set()
                ).add(package_run)
            existing = by_hash.get(actual_hash)
            if existing is None:
                normalized["package_origins"] = [path.name]
                if declared_hash and declared_hash != actual_hash:
                    normalized["legacy_proposal_hash"] = declared_hash
                by_hash[actual_hash] = normalized
            else:
                existing["package_origins"] = sorted(
                    set(existing.get("package_origins") or ()) | {path.name}
                )
    proposals: list[dict[str, Any]] = []
    for key in sorted(versions):
        by_hash = versions[key]
        # Immutable package names are content-addressed. Lexical selection is
        # stable under reversed directory iteration and process restart.
        active_hash = max(
            by_hash,
            key=lambda digest: (
                max(by_hash[digest].get("package_origins") or ("",)),
                digest,
            ),
        )
        active = by_hash[active_hash]
        active["available_version_hashes"] = sorted(by_hash)
        # ATRIBUCIÓN. Las corridas de TODAS las versiones de esta propuesta,
        # no sólo las de la activa: si la corrida B reexportó sin cambios,
        # el paquete es otro fichero pero la propuesta es la misma, y el
        # operador tiene que poder ver que B también la produjo.
        workspace_key, identifier = key
        active["package_runs"] = sorted({
            run
            for digest in by_hash
            for run in runs_by_version.get((workspace_key, identifier, digest), ())
        })
        # EL CONTEXTO DE PLAN, POR CORRIDA. No se funde en uno solo: cada
        # corrida observó su propio snapshot, y mezclarlos daría un plan
        # anclado a un estado que ninguna de las dos vio.
        active["plan_context_by_run"] = dict(
            contexts_by_proposal.get((workspace_key, identifier), {})
        )
        proposals.append(active)
    return proposals


def _validate_history(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    previous_hash: str | None = None
    decision_ids: set[str] = set()
    request_ids: set[str] = set()
    for line_number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise HistoryIntegrityError(f"entrada {line_number} no es un objeto",
                                        HISTORY_ENTRY_NOT_OBJECT)
        body = {key: value for key, value in record.items() if key != "record_hash"}
        if record.get("previous_hash") != previous_hash:
            raise HistoryIntegrityError(f"cadena rota en entrada {line_number}",
                                        HISTORY_CHAIN_BROKEN)
        if record.get("record_hash") != _sha256(body):
            raise HistoryIntegrityError(f"hash inválido en entrada {line_number}",
                                        HISTORY_HASH_INVALID)
        decision_id = _non_empty(record.get("decision_id"), "decision_id")
        request_id = _non_empty(record.get("request_id"), "request_id")
        if decision_id in decision_ids or request_id in request_ids:
            raise HistoryIntegrityError(f"identificador duplicado en entrada {line_number}",
                                        HISTORY_DUPLICATE_ID)
        decision_ids.add(decision_id)
        request_ids.add(request_id)
        previous_hash = record["record_hash"]
        validated.append(record)
    return validated


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise HistoryIntegrityError(f"JSON inválido en entrada {line_number}",
                                        HISTORY_INVALID_JSON) from exc
    return _validate_history(records)


def _active_decisions(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    superseded: set[str] = set()
    for record in records:
        supersedes = record.get("supersedes_decision_id")
        if supersedes:
            superseded.add(supersedes)
        active[record["proposal"]["proposal_id"]] = record
    return {
        proposal_id: record
        for proposal_id, record in active.items()
        if record["decision_id"] not in superseded
        and not record.get("correction", {}).get("undo")
    }


@dataclass(frozen=True)
class QueueView:
    """Lo que la pantalla muestra, y lo que hay detrás, SIN mezclarlos.

    Tres cifras, cada una con una pregunta distinta y ninguna inventada:

    * ``mostradas``  — cuántas fichas se están pintando AHORA MISMO. Es
      exactamente ``len(items)``; no se estima ni se recalcula.
    * ``remaining``  — cuántas propuestas del workspace siguen SIN decidir,
      ignorando los filtros de pantalla. Es lo que queda por hacer.
    * ``total``      — cuántas propuestas del workspace hay, decididas o no.

    Las tres se calculan DESPUÉS de aplicar el ámbito de visibilidad
    (``allowed.allows``), así que ninguna delata la existencia de propuestas
    fuera del ámbito del lector. Un contador que cuente antes del recorte es
    una fuga de existencia, no un detalle de presentación.

    ``filtrado`` dice si hay algún filtro puesto. La cabecera lo necesita
    porque «N de M» sin decir que hay un filtro es lo que producía el texto
    falso «4 pendientes de 4» sobre una lista vacía.
    """

    items: list[dict[str, Any]]
    remaining: int
    total: int
    sources: tuple[str, ...]
    decisions: tuple[str, ...]
    #: Cuántas fichas se pintan con los filtros actuales.
    mostradas: int = 0
    #: ¿Hay algún filtro de pantalla puesto?
    filtrado: bool = False


def _scoped(scope: "VisibilityScope | None") -> "VisibilityScope":
    """Ámbito efectivo del llamador (sin ámbito explícito = interno, sin filtro).

    Las rutas HTTP siempre inyectan el ámbito de la petición. El corpus de
    propuestas V3 usa `workspace` como etiqueta del corpus, no como workspace
    del visor, por lo que aquí aplica la barrera de partida (ver
    ``app.authz.scope``).
    """
    return (scope or UNRESTRICTED).partida_only()


class ReviewService:
    """Workspace-scoped queue and append-only decision ledger."""

    def __init__(
        self,
        proposals_dir: Path | None = None,
        decisions_path: Path | None = None,
        *,
        graph_driver: Any = None,
    ) -> None:
        self.proposals_dir = proposals_dir or default_proposals_dir()
        self.decisions_path = decisions_path or default_decisions_path()
        self.database_path = (
            default_database_path()
            if self.decisions_path == default_decisions_path()
            else self.decisions_path.with_suffix(".sqlite3")
        )
        self.store = SQLiteReviewStore(self.database_path)
        # Kept only as a testable boundary: this service must never dereference it.
        self._graph_driver = graph_driver

    def workspaces(self, scope: "VisibilityScope | None" = None) -> tuple[str, ...]:
        """Workspaces con al menos una propuesta VISIBLE en el ámbito."""
        allowed = _scoped(scope)
        return tuple(sorted({
            str(item["workspace"])
            for item in load_proposals(self.proposals_dir)
            if allowed.allows(item)
        }))

    def glossary_candidates(self, workspace: str,
                            scope: "VisibilityScope | None" = None) -> list[dict[str, Any]]:
        self.store.project_outbox(workspace, _now())
        allowed = _scoped(scope)
        return [c for c in self.store.candidates(workspace) if allowed.allows(c)]

    def queue(
        self,
        workspace: str,
        *,
        source_id: str | None = None,
        engine_decision: str | None = None,
        #: LA CORRIDA. Filtra por la atribucion que el sobre del paquete ya
        #: traia (`package_runs`, poblado desde el bloque `run` del paquete).
        #: NO se deriva ni se adivina: una propuesta sin corrida declarada NO
        #: entra cuando se filtra por corrida, porque afirmar que es de esta
        #: seria inventar la atribucion que el paquete no tiene.
        job_id: str | None = None,
        include_decided: bool = False,
        scope: "VisibilityScope | None" = None,
    ) -> QueueView:
        workspace = _non_empty(workspace, "workspace")
        history = self.store.decisions()
        active = _active_decisions(history)
        allowed = _scoped(scope)
        # El ámbito se aplica ANTES de contar: `total` y `remaining` tampoco
        # deben delatar propuestas de otra partida.
        all_workspace = [
            proposal for proposal in load_proposals(self.proposals_dir)
            if proposal["workspace"] == workspace and allowed.allows(proposal)
        ]
        sources = tuple(sorted({str(item["source_id"]) for item in all_workspace}))
        decisions = tuple(sorted({
            str((item.get("engine_decision") or {}).get("decision") or "UNKNOWN")
            for item in all_workspace
        }))
        filtered = [
            proposal for proposal in all_workspace
            if (not source_id or proposal["source_id"] == source_id)
            and (not job_id or job_id in (proposal.get("package_runs") or ()))
            and (
                not engine_decision
                or (proposal.get("engine_decision") or {}).get("decision") == engine_decision
            )
            and (include_decided or _proposal_id(proposal) not in active)
        ]
        filtered.sort(key=lambda item: (
            str(item.get("source_id", "")),
            str(item.get("episode_id", "")),
            _proposal_id(item),
        ))
        items = [self.present(proposal, active.get(_proposal_id(proposal))) for proposal in filtered]
        remaining = sum(_proposal_id(item) not in active for item in all_workspace)
        return QueueView(
            items=items,
            remaining=remaining,
            total=len(all_workspace),
            sources=sources,
            decisions=decisions,
            mostradas=len(items),
            filtrado=bool(source_id or engine_decision or job_id),
        )

    def present(
        self,
        proposal: dict[str, Any],
        active_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        before, literal, after = _evidence_parts(proposal)
        #: La PROPUESTA en sí (sujeto/predicado/objeto/dirección/`negated`…).
        #: Es lo que la plantilla llama `item.proposal`, y lo que `record()`
        #: llama `claim`: el mismo diccionario, un solo nombre para los dos.
        claim = proposal.get("proposal") or {}
        engine = proposal.get("engine_decision") or {}
        metadata = proposal.get("metadata") or {}
        reconciliation = metadata.get("reconciliation") or {}
        alternatives = proposal.get("alternatives") or reconciliation.get("alternatives") or {}
        predicate_alternatives = _candidate_views(
            alternatives.get("predicates", []),
            reconciliation.get("predicate_candidate_origins", []),
            "predicate",
        )
        direction_alternatives = _candidate_views(
            alternatives.get("directions", []),
            reconciliation.get("direction_candidate_origins", []),
            "direction",
        )
        vista = {
            **proposal,
            "proposal_id": _proposal_id(proposal),
            "proposal_hash": proposal_hash(proposal),
            "evidence_before": before,
            "evidence_literal": literal,
            "evidence_after": after,
            "reason_explanations": [
                {"code": str(code), "label": reason_label(str(code))}
                for code in engine.get("reason_codes", [])
            ],
            "predicate_alternatives": predicate_alternatives,
            "direction_alternatives": direction_alternatives,
            "active_decision": active_decision,
            # EL SIGNO, EN LA PANTALLA DONDE SE DECIDE.
            #
            # El corte del signo de negación cerró resultado, procedencia y
            # ficha de entidad, y dejó JUSTO ésta: la tarjeta de Review pintaba
            # `item.proposal.negation`, una clave que el exportador real
            # (`knowledge_v3.review_export`) no escribe —el campo se llama
            # `negated`, plano—, así que el `default("No disponible")` de la
            # plantilla disparaba SIEMPRE, para `true` y para `false`. La
            # tarjeta se contradecía dentro del mismo recuadro: abajo, en prosa,
            # `NEGATED_CLAIM` decía «la frase niega la relación en vez de
            # afirmarla».
            #
            # No se inventa vocabulario: la AUTORIDAD ÚNICA es
            # `app.labels.negation_code`, la misma que sirve a las otras tres
            # pantallas, con su conversión ESTRICTA de tres estados. Ausente no
            # es `false`: es «no disponible», y se dice.
            #
            # Y se calcula AQUÍ, en el servidor, no en Jinja: `present()` es el
            # único punto por el que pasan la pantalla y la API, así que una
            # superficie nueva no puede volver a leer el campo antiguo por su
            # cuenta.
            "signo": negation_code(claim.get("negated")),
            "signo_label": negation_label(negation_code(claim.get("negated"))),
        }
        # CERO CONOCIMIENTO INTERNO. `plan_context_by_run` es el ancla de
        # estado del grafo y la procedencia de la fuente: material del
        # servidor. Entra en la propuesta porque el sellado lo necesita, y sale
        # AQUÍ porque esto es lo que se pinta y lo que serializa la API. Que se
        # retire en un solo punto es lo que hace que no pueda escaparse por
        # una vista nueva.
        vista.pop("plan_context_by_run", None)
        return vista

    def record(
        self,
        *,
        proposal_id: str,
        workspace: str,
        reviewer: str,
        human_decision: str,
        request_id: str,
        rationale: str = "",
        correction: dict[str, Any] | None = None,
        supersedes_decision_id: str | None = None,
        expected_proposal_hash: str | None = None,
        scope: "VisibilityScope | None" = None,
    ) -> dict[str, Any]:
        if human_decision not in VALID_HUMAN_DECISIONS:
            raise ReviewError(f"human_decision inválida: {human_decision}", INVALID_HUMAN_DECISION)
        request_id = _non_empty(request_id, "request_id")
        reviewer = _non_empty(reviewer, "reviewer")
        workspace = _non_empty(workspace, "workspace")

        with _lock_for(self.decisions_path):
            history = self.store.decisions()
            for existing in history:
                if existing["request_id"] == request_id:
                    if (
                        existing["workspace"] != workspace
                        or existing["proposal"]["proposal_id"] != proposal_id
                        or existing["reviewer"] != reviewer
                        or existing["human_decision"] != human_decision
                    ):
                        raise ReviewError("request_id reutilizado con otra decisión", REQUEST_ID_REUSED)
                    return existing
            proposal = next(
                (
                    item for item in load_proposals(self.proposals_dir)
                    if _proposal_id(item) == proposal_id and item["workspace"] == workspace
                    and _scoped(scope).allows(item)
                ),
                None,
            )
            if proposal is None:
                raise ReviewError("propuesta inexistente en el workspace seleccionado",
                                  PROPOSAL_NOT_FOUND)
            actual_proposal_hash = proposal_hash(proposal)
            # None is retained for programmatic backwards compatibility. The HTML
            # route always supplies the hash the reviewer actually saw.
            expected = expected_proposal_hash or actual_proposal_hash
            if expected != actual_proposal_hash:
                self._audit_stale(
                    proposal=proposal, reviewer=reviewer, request_id=request_id,
                    human_decision=human_decision, expected=expected,
                    actual=actual_proposal_hash,
                )
                raise StaleReviewError(self.present(proposal))
            if supersedes_decision_id and not any(
                item["decision_id"] == supersedes_decision_id
                and item["workspace"] == workspace
                and item["proposal"]["proposal_id"] == proposal_id
                for item in history
            ):
                raise ReviewError("la decisión supersedida no pertenece a esta propuesta y workspace",
                                  SUPERSEDED_DECISION_MISMATCH)

            # F-7. La corrección se decide CONTRA LA PROPUESTA QUE SE ESTÁ
            # DECIDIENDO, y aquí es el único sitio donde las dos están juntas y
            # ya verificadas (existe, es del workspace, el hash coincide). Ver
            # `_correccion_efectiva`.
            correction, correction_changes = _correccion_efectiva(
                correction, proposal.get("proposal") or {}
            )
            if human_decision == "CORRECT" and not correction:
                # Un `CORRECT` que reenvía la propuesta intacta no es una
                # corrección. Antes la ruta HTTP sólo miraba que el formulario
                # trajera ALGO relleno, y `scope=not_available` bastaba para
                # colarlo: se habría grabado un `CORRECT` con `correction` vacío.
                raise ReviewError(
                    "CORRECT sin ningún campo distinto de la propuesta",
                    CORRECTION_WITHOUT_CHANGE,
                )

            engine_decision = proposal.get("engine_decision") or {}
            record: dict[str, Any] = {
                "decision_id": f"human:{uuid.uuid4()}",
                "request_id": request_id,
                "timestamp": _now(),
                "reviewer": reviewer,
                "workspace": workspace,
                "source_id": proposal["source_id"],
                "episode_id": proposal["episode_id"],
                "proposal_id": proposal_id,
                "proposal": json.loads(_canonical(proposal)),
                "expected_proposal_hash": expected,
                "actual_proposal_hash": actual_proposal_hash,
                "engine_decision": json.loads(_canonical(engine_decision)),
                "effective_decision": engine_decision.get("effective_decision"),
                "shadow_decision": engine_decision.get("shadow_decision"),
                "human_decision": human_decision,
                "correction": correction or {},
                #: EL `before`/`after` REAL de cada campo que el humano cambió.
                #: Va DENTRO del registro, así que el `record_hash` de abajo lo
                #: firma: el acta afirma exactamente lo que ocurrió, ni más
                #: —la corrección fantasma— ni menos.
                #: Clave nueva y aditiva: los registros anteriores no la traen,
                #: sus `record_hash` no se recalculan y la cadena no se toca.
                "correction_changes": correction_changes,
                "rationale": rationale.strip(),
                "ontology_version": (
                    proposal.get("ontology_version")
                    or (proposal.get("ontology") or {}).get("version")
                ),
                "engine_version": proposal.get("engine_version"),
                "prompt_version": proposal.get("prompt_version"),
                "supersedes_decision_id": supersedes_decision_id,
                "previous_hash": history[-1]["record_hash"] if history else None,
            }
            record["record_hash"] = _sha256(record)
            outbox = self._glossary_outbox_payload(record, proposal)
            stored, created = self.store.append_decision_and_outbox(record, outbox)
            if not created:
                if (
                    stored["workspace"] != workspace
                    or stored["proposal"]["proposal_id"] != proposal_id
                    or stored["reviewer"] != reviewer
                    or stored["human_decision"] != human_decision
                ):
                    raise ReviewError("request_id reutilizado con otra decisión", REQUEST_ID_REUSED)
                return stored
            # JSONL remains a compatibility/audit export, never the authority.
            self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
            with self.decisions_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.store.project_outbox(workspace, _now())
            return stored

    def _audit_stale(self, *, proposal: dict[str, Any], reviewer: str, request_id: str,
                     human_decision: str, expected: str, actual: str) -> None:
        path = default_audit_path() if self.decisions_path == default_decisions_path() else (
            self.decisions_path.with_name("audit.jsonl")
        )
        event = {
            "event": "STALE_REVIEW", "timestamp": _now(), "request_id": request_id,
            "reviewer": reviewer, "workspace": proposal["workspace"],
            "source_id": proposal["source_id"], "episode_id": proposal["episode_id"],
            "proposal_id": _proposal_id(proposal),
            "expected_proposal_hash": expected, "actual_proposal_hash": actual,
            "human_decision": human_decision,
        }
        self.store.audit_stale(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _glossary_outbox_payload(
        self, record: dict[str, Any], proposal: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Only explicit human fields can produce candidates; rejections cannot."""
        if record["human_decision"] == "REJECT":
            return None
        correction = record["correction"]
        mapping = [
            ("subject_canonical_name", "CANONICAL_TERM_CANDIDATE", "subject"),
            ("object_canonical_name", "CANONICAL_TERM_CANDIDATE", "object"),
            ("subject_alias", "ALIAS_CANDIDATE", "subject"),
            ("object_alias", "ALIAS_CANDIDATE", "object"),
            ("spoken_form", "SPOKEN_FORM_CANDIDATE", "subject"),
            ("suggested_entity_type", "ENTITY_TYPE_CANDIDATE", "subject"),
            ("misrecognition", "KNOWN_MISRECOGNITION_CANDIDATE", "subject"),
        ]
        claim = proposal.get("proposal") or {}
        provenance = proposal.get("provenance") or {}
        candidates: list[dict[str, Any]] = []
        for field, candidate_type, canonical_field in mapping:
            value = str(correction.get(field) or "").strip()
            if not value:
                continue
            # An OCR/ASR correction is a known misrecognition, never an alias.
            canonical = str(claim.get(canonical_field) or value)
            resolved = (proposal.get("resolution") or {}).get(canonical_field)
            semantic_key = [
                record["workspace"], candidate_type,
                " ".join(canonical.casefold().split()),
                " ".join(value.casefold().split()), resolved,
            ]
            candidate_id = f"glossary:{_sha256(semantic_key)}"
            candidate = {
                "candidate_id": candidate_id,
                "candidate_type": candidate_type,
                "status": "PROPOSED",
                "workspace": record["workspace"],
                "canonical_value": canonical,
                "candidate_value": value,
                "entity_type": correction.get("suggested_entity_type"),
                "resolved_entity_id": resolved,
                "source_ids": [record["source_id"]],
                "episode_ids": [record["episode_id"]],
                "evidence": [proposal.get("evidence") or {}],
                "occurrence_count": 1,
                "source_count": 1,
                "origin": {
                    "human_decision_ids": [record["decision_id"]],
                    "proposal_ids": [record["proposal_id"]],
                    "extractors": provenance.get("extractors", []),
                    "providers": provenance.get("providers", []),
                },
                "confidence": None,
                "reason_codes": ["EXPLICIT_HUMAN_CORRECTION"],
                "created_at": record["timestamp"],
            }
            # Un candidato heredado de material de partida sigue siendo de esa
            # partida: se estampa para que el ámbito lo filtre igual que a la
            # propuesta de la que nace. Sin partida = capa juego (no se añade
            # la clave, para no alterar los documentos ya existentes).
            partida_id = proposal.get("partida_id")
            if partida_id:
                candidate["partida_id"] = partida_id
            candidates.append(candidate)
        return {"candidates": candidates} if candidates else None

    def undo_last(self, *, workspace: str, reviewer: str, request_id: str,
                  scope: "VisibilityScope | None" = None) -> dict[str, Any]:
        with _lock_for(self.decisions_path):
            history = self.store.decisions()
            allowed = _scoped(scope)
            active = [
                record for record in _active_decisions(history).values()
                if record["workspace"] == workspace and allowed.allows(record["proposal"])
            ]
            if not active:
                raise ReviewError("no hay una decisión activa que deshacer", NO_ACTIVE_DECISION)
            latest = max(active, key=lambda record: (record["timestamp"], record["decision_id"]))
            return self.record(
                proposal_id=latest["proposal"]["proposal_id"],
                workspace=workspace,
                reviewer=reviewer,
                human_decision="CORRECT",
                request_id=request_id,
                rationale="Deshacer última decisión",
                correction={"undo": True, "restores": "PENDING"},
                supersedes_decision_id=latest["decision_id"],
                scope=scope,
            )
