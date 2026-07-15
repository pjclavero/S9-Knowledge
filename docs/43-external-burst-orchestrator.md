# 43 · Orquestador de procesamiento externo por rafaga (Fase B1)

**Fecha:** 2026-07-15
**Rama:** `feat/external-burst-orchestrator`
**Estado:** Fase B1 implementada (mock + infraestructura) · B2/B3 pendientes.

> **Modo seguro por defecto.** Toda la infraestructura de procesamiento externo
> arranca con `S9K_EXTERNAL_PROCESSING_ENABLED=false` y
> `S9K_EXTERNAL_DRY_RUN_REQUIRED=true`. Sin activacion explicita, ningun dato
> sale del servidor local.

---

## Contexto y separacion de responsabilidades

El ecosistema S9K tiene dos subsistemas externos separados:

| Subsistema | Paquete | Rol |
|---|---|---|
| IA externa (Fase A) | `external_ai/` | Revision de candidatos, adjudicacion, consenso, calibracion |
| Procesamiento externo (Fase B1) | `external_processing/` | Transcripcion, OCR, analisis de imagen, embeddings, reranking |

Ambos pueden reutilizar cliente HTTP y auth, pero tienen contratos independientes y no se mezclan.

---

## Arquitectura: paquete `external_processing/`

```
data-engine/app/external_processing/
├── __init__.py
├── capabilities.py        # Enum Capability: TRANSCRIBE_AUDIO, OCR_IMAGE, ...
├── errors.py              # ErrorCode enum + excepciones tipadas
├── models.py              # ProcessingJob, JobStatus, state machine, MergedResult, ...
├── manifests.py           # BatchManifest, BatchFile (private_path nunca exportado)
├── planner.py             # BurstPlanner: seleccion local/hybrid/burst
├── chunking.py            # Division de audio, PDF, imagenes, texto
├── provider.py            # ExternalProcessingProvider (ABC)
├── registry.py            # Registro de proveedores por nombre/capacidad
├── cache.py               # Cache idempotente SHA256
├── dispatcher.py          # BurstDispatcher: concurrencia, retry, circuit breaker
├── result_validator.py    # Validacion de respuestas externas
├── result_merger.py       # Union de segmentos: audio, OCR, texto
└── providers/
    ├── __init__.py
    ├── mock.py            # MockExternalProcessingProvider (todos los escenarios)
    └── nvidia.py          # NvidiaProcessingProvider (capacidades verificadas)
```

---

## Maquina de estados

```
detected -> planned -> queued -> dispatching -> running -> completed -> validating -> ready
                                                        -> retry_wait -> queued (backoff)
                                                        -> failed
                         -> cancelled
```

Transiciones invalidas lanzaran `ValueError` inmediatamente:
- `completed -> running` (prohibido)
- `failed -> completed` sin retry explicito (prohibido)
- `ready -> cualquier estado` (estado terminal)

---

## Planner: seleccion de modo

El planner calcula la carga total y selecciona el modo de procesamiento:

| Modo | Criterio |
|---|---|
| `local` | Dentro de limites locales |
| `hybrid` | Supera limite local pero no alcanza umbral de burst |
| `burst` | Supera umbral de burst |

Umbrale configurables por entorno:

```bash
S9K_PROCESSING_MODE=auto              # auto | local | hybrid | burst
S9K_LOCAL_MAX_AUDIO_MINUTES=30
S9K_LOCAL_MAX_PDF_PAGES=20
S9K_LOCAL_MAX_IMAGES=10
S9K_BURST_MIN_AUDIO_MINUTES=120
S9K_BURST_MIN_PDF_PAGES=60
S9K_BURST_MIN_IMAGES=30
S9K_EXTERNAL_MAX_CONCURRENCY=4
```

El planner devuelve siempre `reason_codes` explicando la decision:

```json
{"selected_mode": "burst", "reason_codes": ["AUDIO_DURATION_EXCEEDS_BURST_THRESHOLD"]}
```

Si no hay metricas historicas, la estimacion de tiempo se marca como `ESTIMATE_LOW_CONFIDENCE`.

---

## Chunking

### Audio
- Division por duracion maxima (default: 600s / 10 min)
- Solapamiento configurable (default: 2s) para no cortar palabras
- Cada chunk conserva: `chunk_start`, `chunk_end`, `overlap_start`, `overlap_end`, `source_hash`

### PDF
- Division por rangos de paginas (default: 20 paginas por chunk)
- Mantiene `page_start`, `page_end`, `document_hash`

### Imagenes
- Una imagen por `ImageTask` (sin batching por defecto)
- Hash determinista por path de imagen

### Texto
- Division por tamaño maximo de caracteres (default: 4000)
- Intenta cortar en espacios para no partir palabras
- Preserva `offset_start`, `offset_end`, `source_hash`

---

## Cache idempotente

Clave de cache:

```python
SHA256(source_hash + task_type + chunk_range + provider + model + processing_version + parameters)
```

- Antes de crear un job: busca resultado previo valido
- Invalida cuando cambia modelo, version o parametros
- No cachea resultados con errores
- Ubicacion: `state/external_processing_cache/` (ignorada por Git)

---

## Dispatcher

`BurstDispatcher` gestiona:

- **Concurrencia limitada**: semaforo con `max_concurrency` (default: 4)
- **Reintentos con backoff exponencial**: `base_backoff * 2^attempt` (max: `max_backoff`)
- **Cancelacion limpia**: `cancel_batch(batch_id)` marca para cancelacion cooperativa
- **Rate limiting**: espera `retry_after` del proveedor
- **Circuit breaker**: abre tras N fallos consecutivos, se resetea tras cool-down

Errores **no reintentables** (permanentes):
- `AUTH_ERROR`
- `UNSUPPORTED_CAPABILITY`
- `INPUT_TOO_LARGE`
- `CONTENT_BLOCKED`

Errores **reintentables** (con backoff):
- `RATE_LIMIT`
- `TIMEOUT`
- `PROVIDER_UNAVAILABLE`
- `INVALID_RESPONSE`

---

## Validacion de resultados

Toda respuesta externa pasa por `result_validator.py`:

1. Schema validation (campos requeridos presentes)
2. Source hash validation
3. Chunk range validation (timestamps, paginas)
4. Workspace validation
5. Language validation (ISO 639-1 si presente)
6. Secret scan (patrones de credenciales)
7. Private path scan (rutas internas, IPs)

Respuesta invalida -> estado `FAILED_VALIDATION`, no continua al pipeline.

---

## Merger de resultados

`result_merger.py` une segmentos segun tipo:

**Audio**: ordena por `chunk_start`, elimina solapamientos, detecta gaps de tiempo.

**PDF/OCR**: ordena por `page_start`, detecta paginas faltantes.

**Texto**: ordena por `offset_start`, detecta gaps de caracteres.

Estado final siempre: `READY_FOR_LOCAL_PIPELINE`

El merger **NUNCA**:
- Escribe en Neo4j
- Llama a `ingest_approved`
- Genera `approved_payload`

---

## Proveedor Mock

`MockExternalProcessingProvider` soporta todos los escenarios de prueba:

| Escenario | Comportamiento |
|---|---|
| `success` | Respuesta valida determinista |
| `timeout` | `TimeoutError` en cada intento |
| `invalid_schema` | Respuesta con campos requeridos ausentes |
| `partial` | Resultado parcial (texto truncado) |
| `rate_limit` | N primeros intentos con `RateLimitError` |
| `permanent_error` | `AuthError` permanente (no reintenta) |
| `retry_once` | Falla el primer intento, exito en el segundo |
| `auth_error` | `AuthError` inmediato |
| `input_too_large` | `InputTooLargeError` |
| `content_blocked` | `ContentBlockedError` |

---

## Adaptador NVIDIA (Fase B1)

`NvidiaProcessingProvider` reutiliza `external_ai.openai_compatible` y `external_ai.registry`.

Capacidades verificadas en Fase B1:
- `EXTRACT_TEXT_ENTITIES`
- `GENERATE_EMBEDDINGS`
- `RERANK`
- `REVIEW_CANDIDATES`

Para las demas: `UnsupportedCapabilityError` inmediato.

Los endpoints especificos (`/embeddings`, `/rerank`) se implementaran en **Fase B2**.

---

## CLI

```bash
# Planificar (dry-run por defecto para proveedores reales)
python data-engine/app/cli/burst.py plan \
    --workspace leyenda \
    --source /path/to/audio.mp3 \
    --mode auto \
    --dry-run

# Ejecutar (mock no requiere dry-run)
python data-engine/app/cli/burst.py dispatch \
    --batch-id <UUID> \
    --provider mock

# Estado
python data-engine/app/cli/burst.py status --batch-id <UUID>

# Validar resultados
python data-engine/app/cli/burst.py validate --batch-id <UUID>

# Fusionar
python data-engine/app/cli/burst.py merge --batch-id <UUID>

# Informe final
python data-engine/app/cli/burst.py report --batch-id <UUID>

# Cancelar
python data-engine/app/cli/burst.py cancel --batch-id <UUID>
```

---

## Migracion SQLite

La migracion B1 añade columnas a la tabla `jobs` existente de forma idempotente:

| Columna | Tipo | Descripcion |
|---|---|---|
| `batch_id` | TEXT | ID del batch de procesamiento externo |
| `processing_mode` | TEXT | local/hybrid/burst |
| `provider` | TEXT | Nombre del proveedor |
| `model` | TEXT | Modelo usado |
| `task_type` | TEXT | Tipo de tarea externa |
| `chunk_json` | TEXT | Metadatos del chunk (JSON) |
| `progress` | REAL | Progreso 0.0-1.0 |
| `attempt_burst` | INTEGER | Numero de intento (burst) |
| `next_retry_at` | TEXT | Timestamp del proximo reintento |
| `latency_ms` | REAL | Latencia en ms |
| `error_code` | TEXT | Codigo de error si fallo |

Jobs existentes tienen estos campos en NULL (compatibilidad total).

---

## Seguridad

Variables de entorno, todo desactivado por defecto:

```bash
S9K_EXTERNAL_PROCESSING_ENABLED=false
S9K_EXTERNAL_ALLOW_PRIVATE_CONTENT=false
S9K_EXTERNAL_MAX_CONCURRENCY=4
S9K_EXTERNAL_DRY_RUN_REQUIRED=true
```

Garantias:
- `private_path` nunca se incluye en payloads exportados (`BatchFile.export_safe()`)
- Detector de secretos bloquea envio antes de cualquier llamada de red
- IPs internas y rutas del servidor se detectan y bloquean
- Workspaces no se mezclan

---

## Tests

87 tests en `data-engine/app/tests/test_external_processing/`:

| Archivo | Tests | Cubre |
|---|---|---|
| `test_planner.py` | 11 | Seleccion de modo, estimaciones, planner completo |
| `test_chunking.py` | 14 | Audio, PDF, imagenes, texto |
| `test_cache.py` | 8 | Idempotencia, hits, invalidacion |
| `test_dispatcher.py` | 10 | Concurrencia, retry, circuit breaker |
| `test_state_machine.py` | 9 | Transiciones validas e invalidas |
| `test_validator.py` | 12 | Hash, paginas, timestamps, secretos |
| `test_merger.py` | 8 | Audio, OCR, gaps, seguridad |
| `test_security.py` | 8 | Secretos, rutas privadas, Neo4j, ingest |
| `test_migration.py` | 3 | Migracion idempotente, compatibilidad |
| `test_e2e_mock.py` | 3 | E2E completo: plan->dispatch->validate->merge |

---

## Fases pendientes

### Fase B2: Proveedores ASR/OCR/Imagen reales

Implementar endpoints especificos en `NvidiaProcessingProvider.execute()`:
- ASR: endpoint de transcripcion audio
- OCR: endpoint de reconocimiento de texto
- Imagen: endpoint de descripcion/analisis visual

Otros proveedores posibles: OpenAI Whisper API, Google Vision, Azure Cognitive Services.

### Fase B3: Procesamiento automatico en produccion

- Activar `S9K_EXTERNAL_PROCESSING_ENABLED=true`
- Desactivar `S9K_EXTERNAL_DRY_RUN_REQUIRED`
- Integrar con el worker de jobs existente
- Metricas historicas para mejora de estimaciones
- Alertas si tasa de fallos supera umbral
