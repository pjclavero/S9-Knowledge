# -*- coding: utf-8 -*-
"""Observabilidad/trazabilidad DESACOPLADA para el futuro pipeline de relaciones.

Este modulo aporta estructuras de trazabilidad (eventos y trazas) para instrumentar
los componentes del pipeline de relaciones (generacion de pares, senales, sombra de
LLM local, sombra de IA externa, consenso, ...) SIN acoplarse a ningun backend de
metricas ni a ninguna telemetria externa.

Garantias de diseno
--------------------
  * SIN dependencias pesadas: solo stdlib (`dataclasses`, `time`, `hashlib`, `json`,
    `logging`, `contextlib`, `enum`, `typing`).
  * SIN backend obligatorio: los eventos/trazas se DEVUELVEN y se SERIALIZAN; el
    consumidor decide donde escribirlos (log, fichero, cola, ...). Este modulo NO
    escribe a disco, NO abre red y NO envia telemetria.
  * SIN red: no importa `requests`/`httpx`/`socket` ni abre sockets.
  * Determinismo: `to_dict`/`to_json` son deterministas (claves ordenadas). La
    temporizacion admite inyeccion de reloj (`clock`) para pruebas reproducibles.
  * Redaccion por defecto: nunca se registran secretos, cabeceras de autorizacion ni
    texto completo. Se ofrecen `redact()` y `hash_value()`, y se distingue el dato
    SINTETICO del PRIVADO mediante un flag (`synthetic`).

Relacion con `relations.contracts`
----------------------------------
Este modulo NO extrae relaciones ni valida candidatos: solo describe QUE hizo un
componente y CUANTO tardo. Es intencionadamente independiente del contrato
`relation-candidate/internal-v1` para poder instrumentar cualquier etapa sin
arrastrar su modelo de datos.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator, Optional

# Logger del modulo. Por defecto SIN handlers (el consumidor configura destino).
# NullHandler evita el warning "No handlers could be found" sin forzar salida.
logger = logging.getLogger("relations.observability")
logger.addHandler(logging.NullHandler())


class ObservabilityError(ValueError):
    """Error de validacion de un evento/traza de observabilidad."""


# --- Redaccion de secretos --------------------------------------------------
# Patrones de credenciales habituales. Se replican de forma independiente
# (external_ai.security es SOLO referencia, no se importa) para no acoplar este
# modulo a otro subsistema. Ampliar aqui si aparecen nuevos formatos.
_SECRET_PATTERNS = (
    re.compile(r"nvapi-[A-Za-z0-9_\-]{16,}"),            # NVIDIA NIM
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                  # OpenAI-style
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),           # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),                     # AWS access key id
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),     # Authorization: Bearer <token>
    re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----"),    # PEM
    re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|token|authorization)\b\s*[:=]\s*"
        r"['\"]?[^\s'\",;]{4,}"
    ),
)

REDACTED_PLACEHOLDER = "[REDACTED]"


def hash_value(value: Any, *, algo: str = "sha256", length: int = 16) -> str:
    """Devuelve un hash hex TRUNCADO de `value`, estable y sin exponer el contenido.

    Sirve para correlacionar el mismo valor (p.ej. un id sensible o un texto privado)
    entre eventos sin registrarlo en claro. Determinista: mismo valor -> mismo hash.

    `value` no-str se serializa con `str(value)` de forma estable. `length` acota los
    caracteres hex devueltos (0 o negativo => hash completo).
    """
    text = value if isinstance(value, str) else str(value)
    digest = hashlib.new(algo, text.encode("utf-8")).hexdigest()
    if length and length > 0:
        return digest[:length]
    return digest


def find_secrets(text: str) -> list:
    """Lista los NOMBRES/prefijos de patron detectados, sin exponer el valor.

    Devuelve `[]` si no hay coincidencias. No lanza; entrada no-str se coacciona.
    """
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, sort_keys=True)
    found = []
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            found.append(pat.pattern[:24])
    return found


def redact(value: Any, *, placeholder: str = REDACTED_PLACEHOLDER) -> Any:
    """Sustituye secretos por `placeholder` conservando el texto no sensible.

    Recorre de forma recursiva dicts/list/tuple y aplica los patrones de credenciales
    a cada str. NUNCA devuelve el secreto en claro. Determinista y sin red.
    """
    if isinstance(value, str):
        redacted = value
        for pat in _SECRET_PATTERNS:
            redacted = pat.sub(placeholder, redacted)
        return redacted
    if isinstance(value, dict):
        # Ademas de redactar valores, si la CLAVE parece sensible se oculta el valor
        # completo (p.ej. {"Authorization": "<token>"} o {"api_key": "..."}).
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive_key(k):
                out[k] = placeholder
            else:
                out[k] = redact(v, placeholder=placeholder)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, placeholder=placeholder) for v in value]
    return value


_SENSITIVE_KEY = re.compile(
    r"(?i)^(authorization|api[_-]?key|secret|password|passwd|token|access[_-]?key|"
    r"x-api-key|bearer)$"
)


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.match(key.strip()))


# --- Resultado de un componente --------------------------------------------
class ComponentResult(str, Enum):
    """Resultado agregado de la ejecucion de un componente."""

    OK = "OK"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


def _coerce_result(value: Any) -> ComponentResult:
    if isinstance(value, ComponentResult):
        return value
    try:
        return ComponentResult(value)
    except (ValueError, KeyError):
        valid = [e.value for e in ComponentResult]
        raise ObservabilityError(f"result={value!r} invalido; validos: {valid}")


# --- Temporizacion determinista --------------------------------------------
@dataclass
class TimingHandle:
    """Handle devuelto por `time_component`. `duration` se rellena al salir."""

    started_at: float = 0.0
    ended_at: float = 0.0
    duration: float = 0.0


@contextmanager
def time_component(clock: Optional[Callable[[], float]] = None) -> Iterator[TimingHandle]:
    """Context manager que mide la duracion de un bloque.

    Para pruebas deterministas se puede inyectar `clock`, un callable sin argumentos
    que devuelve un float monotono (p.ej. una lista de instantes controlada). Por
    defecto usa `time.monotonic` (no afectado por ajustes de reloj de pared).

    La duracion se expone en el handle YIELDado y queda disponible tras el `with`.
    Se rellena aunque el bloque lance una excepcion (bloque `finally`).
    """
    tick = clock if clock is not None else time.monotonic
    handle = TimingHandle()
    handle.started_at = float(tick())
    try:
        yield handle
    finally:
        handle.ended_at = float(tick())
        handle.duration = handle.ended_at - handle.started_at


# --- Evento de trazabilidad -------------------------------------------------
# Campos obligatorios (validados, no vacios): identifican QUE componente se ejecuto,
# sobre QUE ejecucion/documento/workspace y con QUE resultado.
_REQUIRED_STR_FIELDS = (
    "execution_id",
    "document_id",
    "workspace",
    "component",
    "version",
)


@dataclass
class RelationEvent:
    """Evento serializable de trazabilidad de un componente del pipeline de relaciones.

    Obligatorios (str no vacio): `execution_id`, `document_id`, `workspace`,
    `component`, `version`, mas `result` (ComponentResult). El resto es opcional y
    describe metricas de la ejecucion. Todos los campos son serializables a JSON.

    El flag `synthetic` distingue el dato SINTETICO (de prueba/rehearsal, se puede
    registrar tal cual) del PRIVADO (contenido real; por defecto NO se vuelca texto,
    solo hashes/tamanos). `sample_text`, si se aporta, se REDACTA siempre y ademas
    se OMITE de la salida cuando `synthetic=False`, salvo `include_private=True`.
    """

    # -- Obligatorios --
    execution_id: str
    document_id: str
    workspace: str
    component: str
    version: str
    result: ComponentResult

    # -- Identidad opcional del ambito --
    segment_id: Optional[str] = None
    candidate_id: Optional[str] = None

    # -- Metricas de ejecucion --
    duration: Optional[float] = None
    num_pairs: Optional[int] = None
    num_signals: Optional[int] = None
    retries: int = 0
    input_size: Optional[int] = None
    output_size: Optional[int] = None
    estimated_cost: Optional[float] = None
    consensus_decision: Optional[str] = None

    # -- Estado de proveedores / errores --
    provider_status: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    # -- Redaccion / procedencia del dato --
    synthetic: bool = False
    sample_text: Optional[str] = None

    def validate(self) -> "RelationEvent":
        """Valida el evento. Lanza `ObservabilityError` si algo no cumple.

        Devuelve self para encadenar.
        """
        for name in _REQUIRED_STR_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ObservabilityError(f"{name} es obligatorio y no puede estar vacio")

        self.result = _coerce_result(self.result)

        for name in ("segment_id", "candidate_id", "consensus_decision"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ObservabilityError(f"{name} debe ser str o None")

        if self.duration is not None:
            if not isinstance(self.duration, (int, float)) or isinstance(self.duration, bool):
                raise ObservabilityError("duration debe ser numerico o None")
            if self.duration < 0:
                raise ObservabilityError("duration no puede ser negativa")

        for name in ("num_pairs", "num_signals", "input_size", "output_size"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ObservabilityError(f"{name} debe ser int o None")
                if value < 0:
                    raise ObservabilityError(f"{name} no puede ser negativo")

        if not isinstance(self.retries, int) or isinstance(self.retries, bool) or self.retries < 0:
            raise ObservabilityError("retries debe ser int >= 0")

        if self.estimated_cost is not None:
            if not isinstance(self.estimated_cost, (int, float)) or isinstance(
                self.estimated_cost, bool
            ):
                raise ObservabilityError("estimated_cost debe ser numerico o None")
            if self.estimated_cost < 0:
                raise ObservabilityError("estimated_cost no puede ser negativo")

        if not isinstance(self.provider_status, dict):
            raise ObservabilityError("provider_status debe ser dict")

        if not isinstance(self.errors, list) or not all(isinstance(e, str) for e in self.errors):
            raise ObservabilityError("errors debe ser lista de strings")

        if not isinstance(self.synthetic, bool):
            raise ObservabilityError("synthetic debe ser bool explicito (True/False)")

        if self.sample_text is not None and not isinstance(self.sample_text, str):
            raise ObservabilityError("sample_text debe ser str o None")

        return self

    # -- Serializacion determinista ---------------------------------------
    def to_dict(self, *, include_private: bool = False) -> dict:
        """Dict serializable y determinista.

        La redaccion se aplica SIEMPRE: `errors`, `provider_status` y `sample_text`
        pasan por `redact()` para no filtrar secretos ni cabeceras de autorizacion.

        `sample_text` se incluye solo si el evento es `synthetic=True` o si se pide
        explicitamente `include_private=True`; en caso contrario se sustituye por su
        hash y tamano (`sample_text_hash`, `sample_text_len`), nunca el texto en claro.
        """
        data = {
            "execution_id": self.execution_id,
            "document_id": self.document_id,
            "workspace": self.workspace,
            "component": self.component,
            "version": self.version,
            "result": self.result.value if isinstance(self.result, ComponentResult) else self.result,
            "segment_id": self.segment_id,
            "candidate_id": self.candidate_id,
            "duration": self.duration,
            "num_pairs": self.num_pairs,
            "num_signals": self.num_signals,
            "retries": self.retries,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "estimated_cost": self.estimated_cost,
            "consensus_decision": self.consensus_decision,
            "provider_status": redact(dict(self.provider_status)),
            "errors": [redact(e) for e in self.errors],
            "synthetic": self.synthetic,
        }

        if self.sample_text is None:
            data["sample_text"] = None
            data["sample_text_hash"] = None
            data["sample_text_len"] = None
        elif self.synthetic or include_private:
            # Dato sintetico o volcado explicito: se registra (siempre redactado).
            data["sample_text"] = redact(self.sample_text)
            data["sample_text_hash"] = hash_value(self.sample_text)
            data["sample_text_len"] = len(self.sample_text)
        else:
            # Dato PRIVADO: no se vuelca el texto; solo hash y tamano.
            data["sample_text"] = None
            data["sample_text_hash"] = hash_value(self.sample_text)
            data["sample_text_len"] = len(self.sample_text)

        return data

    def to_json(self, *, include_private: bool = False) -> str:
        """JSON determinista: claves ordenadas, separadores estables, Unicode literal."""
        return json.dumps(
            self.to_dict(include_private=include_private),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "RelationEvent":
        """Reconstruye un evento desde un dict producido por `to_dict`.

        Ignora las claves derivadas de redaccion (`sample_text_hash`,
        `sample_text_len`), que no son campos del evento.
        """
        if not isinstance(data, dict):
            raise ObservabilityError("from_dict espera un dict")
        payload = {k: v for k, v in data.items() if k not in _DERIVED_KEYS}
        known = _EVENT_FIELD_NAMES
        unknown = set(payload) - known
        if unknown:
            raise ObservabilityError(f"campos desconocidos en RelationEvent: {sorted(unknown)}")
        inst = cls(
            execution_id=payload.get("execution_id"),
            document_id=payload.get("document_id"),
            workspace=payload.get("workspace"),
            component=payload.get("component"),
            version=payload.get("version"),
            result=payload.get("result"),
            segment_id=payload.get("segment_id"),
            candidate_id=payload.get("candidate_id"),
            duration=payload.get("duration"),
            num_pairs=payload.get("num_pairs"),
            num_signals=payload.get("num_signals"),
            retries=payload.get("retries", 0),
            input_size=payload.get("input_size"),
            output_size=payload.get("output_size"),
            estimated_cost=payload.get("estimated_cost"),
            consensus_decision=payload.get("consensus_decision"),
            provider_status=dict(payload.get("provider_status") or {}),
            errors=list(payload.get("errors") or []),
            synthetic=payload.get("synthetic", False),
            sample_text=payload.get("sample_text"),
        )
        return inst.validate()


_DERIVED_KEYS = frozenset({"sample_text_hash", "sample_text_len"})
_EVENT_FIELD_NAMES = frozenset(
    {
        "execution_id",
        "document_id",
        "workspace",
        "component",
        "version",
        "result",
        "segment_id",
        "candidate_id",
        "duration",
        "num_pairs",
        "num_signals",
        "retries",
        "input_size",
        "output_size",
        "estimated_cost",
        "consensus_decision",
        "provider_status",
        "errors",
        "synthetic",
        "sample_text",
    }
)


# --- Traza: coleccion ordenada de eventos ----------------------------------
@dataclass
class RelationTrace:
    """Traza serializable: eventos de una misma `execution_id`, en orden de registro.

    Es un simple contenedor SIN backend: acumula eventos en memoria y los serializa.
    El consumidor decide donde persistirlos. No abre red ni escribe a disco.
    """

    execution_id: str
    events: list = field(default_factory=list)

    def add(self, event: RelationEvent, *, validate: bool = True) -> RelationEvent:
        """Anade un evento validandolo y comprobando que comparte `execution_id`."""
        if not isinstance(event, RelationEvent):
            raise ObservabilityError("add espera un RelationEvent")
        if validate:
            event.validate()
        if event.execution_id != self.execution_id:
            raise ObservabilityError(
                f"execution_id del evento ({event.execution_id!r}) no coincide con la "
                f"traza ({self.execution_id!r})"
            )
        self.events.append(event)
        return event

    def record(self, **kwargs: Any) -> RelationEvent:
        """Crea, valida y anade un evento en un solo paso. Devuelve el evento."""
        kwargs.setdefault("execution_id", self.execution_id)
        event = RelationEvent(**kwargs).validate()
        return self.add(event, validate=False)

    def to_dict(self, *, include_private: bool = False) -> dict:
        return {
            "execution_id": self.execution_id,
            "events": [e.to_dict(include_private=include_private) for e in self.events],
        }

    def to_json(self, *, include_private: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_private=include_private),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )


__all__ = [
    "ObservabilityError",
    "ComponentResult",
    "RelationEvent",
    "RelationTrace",
    "TimingHandle",
    "time_component",
    "redact",
    "hash_value",
    "find_secrets",
    "REDACTED_PLACEHOLDER",
    "logger",
]
