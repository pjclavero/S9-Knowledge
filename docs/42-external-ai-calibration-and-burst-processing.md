# 42 · Calibración multi-IA (NVIDIA) y procesamiento externo por lotes

**Fecha:** 2026-07-15
**Rama:** `feat/nvidia-multi-model-calibration`
**Estado:** Fase A implementada (modo sombra) · Fase B diseñada, pendiente.

> **Modo sombra obligatorio.** Toda ejecución externa es `shadow_mode=true`: produce
> `shadow_recommendation`, **nunca** una decisión productiva. Nada de este subsistema escribe
> en Neo4j ni activa la variable de ingesta real. El extractor `hybrid` local y Ollama siguen
> siendo la vía productiva.

---

## Fase A — Implementada ahora: revisión, consenso y calibración con NVIDIA

### Arquitectura
Paquete `data-engine/app/external_ai/`:

| Módulo | Rol |
|---|---|
| `base.py` | Interfaz `ExternalAIProvider` (capacidades declarativas; Fase B en placeholder) |
| `models.py` | Dataclasses: ReviewItem, ReviewBatchRequest, ModelReviewDecision/Response, ProviderHealth, ConsensusResult |
| `errors.py` | Errores tipados + `classify_http_status` (401/403/404/429/5xx) |
| `registry.py` | Config solo por entorno; `get_api_key` (nunca se registra) |
| `openai_compatible.py` | Cliente OpenAI-compatible (bearer, timeout, reintentos+backoff, concurrencia, latencia, tokens) |
| `nvidia_nim.py` | Proveedor NVIDIA NIM (`POST /v1/chat/completions`) |
| `prompts.py` | Prompts idénticos para revisores independientes + prompt de árbitro; `PROMPT_VERSION` |
| `response_parser.py` | Parser robusto de JSON (incl. envuelto en Markdown) + validación estricta |
| `consensus.py` | Motor de consenso por candidato |
| `calibration.py` | Métricas contra decisiones humanas + umbrales (sin activar autoaprobación) |
| `cache.py` | Caché idempotente (fuera de Git), invalida por prompt/esquema |
| `security.py` | Detector de secretos (incl. `nvapi-…`) + sanitización reutilizada |

CLI: `data-engine/app/cli/external_ai.py` — `health | review | adjudicate | calibrate | report`.
Los subcomandos de revisión **exigen `--shadow`** o abortan:
`ABORTADO: la integración externa solo está habilitada en modo sombra.`

### Configuración (solo entorno; la API key NO va en Git)
```
S9K_NVIDIA_ENABLED=false
S9K_NVIDIA_API_KEY=            # en un EnvironmentFile privado 0600, nunca en .env.example ni en logs
S9K_NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
S9K_NVIDIA_REVIEW_MODELS=<modelo-a>,<modelo-b>   # familias distintas
S9K_NVIDIA_ADJUDICATOR_MODEL=<modelo-c>
S9K_NVIDIA_TIMEOUT_SECONDS=180
S9K_NVIDIA_MAX_RETRIES=3
S9K_NVIDIA_MAX_CONCURRENCY=2
S9K_NVIDIA_CACHE_ENABLED=true
S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT=false      # por defecto solo segmentos sanitizados
```
La lista de modelos es configurable; el código **no** depende de nombres concretos. Modelos no
disponibles se descartan tras `health`.

### Revisores independientes y consenso
Dos revisores se ejecutan **sin verse** (mismo texto/reglas/glosario/candidato, prompts idénticos).
El árbitro solo interviene en conflicto y recibe ambas respuestas. Estados del consenso
(no existe `AUTO_APPROVED` en esta fase):

```
STRONG_CONSENSUS · PARTIAL_CONSENSUS · MODEL_CONFLICT · INVALID_RESPONSES · HUMAN_REQUIRED
```
La adjudicación, aunque resuelva, sigue siendo `shadow_recommendation`.

### Seguridad
- API key solo por entorno/EnvironmentFile `0600`; nunca en `.env.example` (valor), logs, excepciones ni informes.
- Antes de cada envío: sanitización (`review.export_import.sanitize_object`) + detector de secretos que **bloquea** el envío (`SecretLeakError`).
- Solo se registran hashes y tamaños. `S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT=false` por defecto.
- Escaneo de secretos ampliado con patrones NVIDIA (`nvapi-…`).

### Validación
- **22 tests** (`test_external_ai.py`), sin llamadas reales: config, key ausente, healthcheck mock, respuesta válida, JSON en Markdown, JSON inválido, timeout/429-retry/401-sin-retry, sin evidencia, evidencia fuera del segmento, revisores independientes, consenso fuerte/parcial/conflicto/adjudicación, caché e invalidación, sanitización/secretos, `--shadow` obligatorio, calibración vs humano, y un test que **falla si el subsistema toca ingesta/Neo4j/variable de ingesta**.
- E2E mockeado (fuente sintética `source_narrative_01`, 9 entidades): 7 STRONG_CONSENSUS, 1 MODEL_CONFLICT (adjudicado), 1 INVALID_RESPONSES (tipo inválido detectado). Neo4j intacto 199/140; sin secretos en artefactos.

### Salidas (fuera de Git)
`output/reviews/<ws>/<sid>/external_ai/`: `request.sanitized.json`, `review.<model>.json`,
`adjudication.json`, `consensus.json`, `calibration_report.json/.md`. Caché en
`state/external_ai_cache/` (ignorada por Git).

---

## Fase B — Diseñada, pendiente: procesamiento externo elástico por lotes

**No implementada.** Interfaz reutilizable prevista sobre la cola de jobs existente.

### Estado del procesamiento externo (auditoría §15)
| Componente | Estado |
|---|---|
| ExternalReviewRequest/Response | **implementados** (`review/export_import.py`) |
| Sanitización | **implementada** |
| Interfaz `media/transcriber.py` | **implementada** |
| Transcriptor externo | **placeholder** (`NotImplementedError`, solo documentado) |
| Cola de jobs (`job_store`, `worker`) | **implementada** (handlers de prueba `noop`/`echo`) |
| Handlers de jobs reales | **no implementados** |
| Orquestación de ráfaga paralela | **no implementada** |
| Proveedor OCR / imagen / ASR externo | **no implementados** |

### Modos de ejecución previstos
```
local   — todo en VM105 (Ollama + faster-whisper), como hoy
hybrid  — local + revisión/consenso externo en sombra (Fase A)
burst   — lotes grandes despachados a proveedores externos elásticos (Fase B)
```

### Tipos de trabajo futuros (Fase B)
```
external_transcribe · external_ocr · external_image_analysis
external_extract · external_rerank · external_review
```

### Regla invariante de la Fase B
Toda respuesta externa **vuelve al pipeline local** antes de tocar el grafo:
```
resultado externo → validate → normalize → resolve → review policy → approved payload
```
**Nada externo escribe en Neo4j.** La ingesta real permanece bajo el doble guard
(`--dry-run` + variable de ingesta) y la política de revisión (`full_human_review` /
`risk_based_autoapproval` en sombra, docs/39).

---

## Validación real controlada (§17) — EJECUTADA (2026-07-15)

API key en EnvironmentFile `/etc/s9-knowledge/nvidia.env` (0600). `health` → ok (muchos modelos NIM disponibles).
Revisión real sobre **3 candidatos conocidos** (source_narrative_01), 2 modelos de **familias distintas** + adjudicador:

| Rol | Modelo | Familia | Válido | Decisiones | Errores | Latencia | Tokens |
|---|---|---|---|---:|---:|---:|---:|
| reviewer_a | nvidia/nemotron-mini-4b-instruct | NVIDIA | sí | 3 | 0 | 5.5 s | 1563 |
| reviewer_b | upstage/solar-10.7b-instruct | Upstage | sí | 3 | 0 | 13.0 s | 1794 |
| adjudicador | nvidia/nvidia-nemotron-nano-9b-v2 | NVIDIA | (sin conflictos) | — | — | ~3 s | — |

Consenso: **2 STRONG_CONSENSUS, 1 PARTIAL_CONSENSUS, 0 conflictos** (coverage 0.67). Ambos modelos
devolvieron JSON estructurado que pasó la validación estricta (evidencia literal en el segmento,
tipos válidos): 0 errores de validación. **Caché confirmada** (2ª llamada 0.00 s, cache hit).
**Neo4j intacto 199/140**; sin secretos en artefactos; la API key nunca se imprimió.
Modelos descartados por no disponibles/no-JSON: zyphra/zamba2-7b (404), sarvamai/sarvam-m (prosa),
openai/gpt-oss-20b (JSON válido pero 53 s, demasiado lento) — sustituibles por configuración.

Para ejecutarla de forma segura (el operador, en VM105):
1. Crear un EnvironmentFile privado `0600` con `S9K_NVIDIA_API_KEY=...` (no mostrarla, no subirla).
2. `export S9K_NVIDIA_ENABLED=true` y las variables de modelos.
3. `python data-engine/app/cli/external_ai.py health --provider nvidia` → confirmar `ok:true` y modelos.
4. `python data-engine/app/cli/external_ai.py review --workspace leyenda --source-id <src> --models A,B --shadow` con ≤5 candidatos conocidos.
5. Confirmar salida estructurada, caché, latencia/tokens y **Neo4j intacto**. No ejecutar calibración masiva.

---

## Dictamen
```
Calibración multi-IA con NVIDIA: IMPLEMENTADA Y VALIDADA EN MODO SOMBRA (2 modelos reales, consenso correcto, Neo4j intacto)
Procesamiento externo de gran volumen: FASE B1 IMPLEMENTADA (orquestador + mock, 87 tests); B2/B3 pendientes
```

---

## Fases de procesamiento externo por rafaga

### B1 — Orquestador y mock (IMPLEMENTADA, 2026-07-15)

Paquete `external_processing/` con infraestructura completa:
- Planner (local/hybrid/burst) con umbrales configurables
- Chunking de audio, PDF, imagenes y texto
- Dispatcher con concurrencia, retry, backoff, circuit breaker
- Validacion y fusion de resultados
- Cache idempotente SHA256
- `MockExternalProcessingProvider`: todos los escenarios, sin APIs reales
- `NvidiaProcessingProvider`: capacidades verificadas declaradas (B2 pendiente)
- CLI: `data-engine/app/cli/burst.py`
- 87 tests (planner, chunking, cache, dispatcher, state machine, validacion, merger, seguridad, E2E mock)

Ver: [docs/43](43-external-burst-orchestrator.md)

### B2 — Proveedores ASR/OCR/Imagen reales (PENDIENTE)

Implementar `NvidiaProcessingProvider.execute()` para:
- Transcripcion de audio (ASR)
- OCR de documentos
- Analisis de imagenes

Candidatos: NVIDIA NIM (ASR/Vision), OpenAI Whisper API, Google Vision, Azure Cognitive Services.

### B3 — Procesamiento automatico en produccion (PENDIENTE)

- Activar `S9K_EXTERNAL_PROCESSING_ENABLED=true` en produccion
- Desactivar `S9K_EXTERNAL_DRY_RUN_REQUIRED`
- Integrar con worker de jobs existente
- Metricas historicas para mejora de estimaciones
- Alertas de tasa de fallos
