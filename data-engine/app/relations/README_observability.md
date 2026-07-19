# Observabilidad DESACOPLADA del pipeline de relaciones (`observability.py`)

Utilidades de trazabilidad para instrumentar los componentes del **futuro pipeline de
relaciones** (generacion de pares, senales, sombra de LLM local, sombra de IA externa,
consenso, ...) **sin acoplarse a ningun backend de metricas ni a telemetria externa**.

## Principios de diseno

- **Solo stdlib.** `dataclasses`, `time`, `hashlib`, `json`, `logging`, `contextlib`,
  `enum`, `typing`, `re`. **No** anade dependencias ni requisitos de instalacion.
- **Sin backend obligatorio.** Los eventos y trazas se **devuelven** y se **serializan**;
  el consumidor decide donde escribirlos (log, fichero, cola). El modulo **no** escribe a
  disco por si mismo.
- **Sin red / sin telemetria.** No importa `requests`/`httpx`/`socket`, no abre sockets y
  no envia nada a ningun sitio.
- **Determinismo.** `to_dict`/`to_json` son deterministas (claves ordenadas, separadores
  estables). La temporizacion admite un **reloj inyectable** para tests reproducibles.
- **Redaccion por defecto.** Nunca se registran secretos, cabeceras `Authorization` ni
  texto completo privado. Se distingue el dato **sintetico** del **privado** con un flag.

## Componentes

### `RelationEvent`
Dataclass serializable con los campos de trazabilidad de una ejecucion de componente.

- **Obligatorios (validados, no vacios):** `execution_id`, `document_id`, `workspace`,
  `component`, `version`, `result` (`ComponentResult`: `OK`/`PARTIAL`/`ERROR`/`SKIPPED`).
- **Ambito opcional:** `segment_id`, `candidate_id`.
- **Metricas:** `duration`, `num_pairs`, `num_signals`, `retries`, `input_size`,
  `output_size`, `estimated_cost`, `consensus_decision`.
- **Estado/errores:** `provider_status` (dict), `errors` (lista de str).
- **Procedencia del dato:** `synthetic` (bool), `sample_text` (opcional).

Metodos: `validate()`, `to_dict(include_private=False)`, `to_json(...)`, `from_dict(...)`.

`validate()` lanza `ObservabilityError` si falta un obligatorio, el `result` no es valido,
un numerico es negativo, `errors` no es lista de str, etc.

### `RelationTrace`
Contenedor en memoria de eventos de una misma `execution_id`. `record(**campos)` crea,
valida y anade un evento; `to_dict()`/`to_json()` serializan la traza completa. **Sin
backend**: no persiste nada por si mismo.

### `time_component(clock=None)`
Context manager que mide la duracion de un bloque y la expone en el handle YIELDado
(`started_at`, `ended_at`, `duration`). Rellena la duracion incluso si el bloque lanza.
Para tests deterministas se inyecta `clock`, un callable sin argumentos que devuelve
floats controlados; por defecto usa `time.monotonic`.

```python
ticks = iter([10.0, 13.5])
with time_component(clock=lambda: next(ticks)) as h:
    ...  # trabajo
assert h.duration == 3.5  # reproducible
```

### Redaccion: `redact()`, `hash_value()`, `find_secrets()`
- `redact(value)` recorre str/dict/list y sustituye secretos (NVIDIA `nvapi-`, OpenAI
  `sk-`, GitHub `ghp_`, AWS `AKIA`, `Bearer`, PEM, `api_key=`/`password=`...) por
  `[REDACTED]`; ademas oculta el valor cuando la **clave** es sensible (`Authorization`,
  `api_key`, `token`, ...).
- `hash_value(v)` da un hash SHA-256 truncado y estable para correlacionar sin exponer.
- `find_secrets(text)` lista los patrones detectados **sin** exponer el valor.

### Sintetico vs privado
`RelationEvent.to_dict()` aplica redaccion **siempre**. `sample_text` se incluye solo si
`synthetic=True` o `include_private=True`; en un evento privado (`synthetic=False`) el
texto **no** se vuelca: solo `sample_text_hash` y `sample_text_len`.

## Uso tipico

```python
from relations.observability import RelationTrace, ComponentResult, time_component

trace = RelationTrace(execution_id="run-2026-07-19-abc")
with time_component() as t:
    pairs = generate_pairs(...)  # trabajo real del pipeline
trace.record(
    document_id="doc-42", workspace="ws-a", component="pairs", version="v1",
    result=ComponentResult.OK, duration=t.duration, num_pairs=len(pairs),
)
payload = trace.to_json()  # el consumidor decide donde escribirlo
```

## Alcance / no-objetivos
No extrae relaciones, no valida candidatos (`relations.contracts`), no llama a LLMs, no
toca Neo4j y no depende de `external_ai` (solo se replican los patrones de redaccion de
forma independiente). Es una utilidad transversal de trazabilidad.
