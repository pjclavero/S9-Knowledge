# 15 · El extractor semántico, conectado a la cadena E2E

Rama: `fix/v3-semantic-extractor-e2e` · Base: `11ab5e7` (programa V3 completo
mergeado) · Contratos: `v3-contracts-frozen-1.0.0`, **sin tocar**.

Este documento cubre dos cosas que van juntas porque la segunda no se puede medir
sin la primera:

1. **la cadena V3 monta ahora el extractor semántico** (antes montaba los
   extractores legacy y las métricas C1/C2 no decían nada sobre la cadena);
2. **las negaciones sobreviven de punta a punta** — el extractor las detecta y las
   marca, el motor decide qué significan, y el plan nunca convierte una negación en
   una arista positiva.

---

## 1. Auditoría previa: lo que había

### 1.1 Dónde vive el orquestador

| Pieza | Fichero |
|---|---|
| Orquestador real | `data-engine/app/knowledge_v3/pipeline/pipeline.py` → `KnowledgePipeline` |
| Montaje de extractores | `KnowledgePipeline._build_extraction_pipeline()` |
| Configuración de la corrida | `pipeline/config.py` → `PipelineConfig` |
| Activación de Ollama | `PipelineConfig.wants_ollama` = `providers == "local_plus_external"` **y** `ollama_client is not None` |
| Activación del externo | `PipelineConfig.wants_external` = `providers ∈ {external_only, local_plus_external, no_ollama}` **y** `external_port is not None` |
| Entrada por CLI / benchmark | `pipeline/runner.py` (`build_config`, `run_one`) |
| Extractor semántico | `extraction/semantic.py` → `SemanticEpisodeExtractor` |
| Puertos de inferencia | `extraction/provider_port.py` → `OllamaProviderPort`, `NvidiaProviderPort`, `MockProviderPort` |
| Pipelines de producción declarados | `extraction/pipeline.py` → `production_local(port)`, `production_external(port)` |
| Banco aislado | `extraction/semantic_bench.py` (llama **directo** a `SemanticEpisodeExtractor`) |
| Pruebas conjuntas de la cadena | `tests/test_knowledge_v3_e2e.py` (+ `…_e2e_fixtures.py`) |

### 1.2 El defecto, en once líneas

`_build_extraction_pipeline()` construía los extractores a mano:

```python
if cfg.wants_ollama:
    extractors.append(OllamaExtractor(client=cfg.ollama_client))     # LEGACY
if cfg.wants_external:
    extractors.append(ExternalExtractor(port=cfg.external_port))     # LEGACY
```

`production_local()` / `production_external()` — los pipelines que sí montan el
semántico — **no los llamaba nadie fuera de sus propios tests**. Y los legacy no
son "una versión anterior del mismo extractor", son otro extractor:

| | legacy (`ollama.py` / `external.py`) | semántico (`semantic.py`) |
|---|---|---|
| Ontología en el prompt | **no** (prompt genérico) | sí, compilada del `GameProfile` |
| Predicado | lo inventa el modelo y luego se tira con `PREDICATE_NOT_IN_PROFILE` | elige dentro de la ontología o se abstiene |
| Candidatos de predicado | **uno** (`payload.normalize_payload`, línea 397) | lista ordenada, hasta 3 |
| Dirección | `SUBJECT_TO_OBJECT` **cableada** (línea 398) | pedida al modelo, `UNRESOLVED` admitido |
| Temporalidad | ninguna | escalonada (local gratis, modelo solo si queda ambiguo) |
| Verificación de sentido | ventana de la primera frase | todas las frases que la cita toca |

Consecuencia medida: **las métricas C1/C2 de `docs/v3/14` se obtuvieron con
`semantic_bench`, que instancia `SemanticEpisodeExtractor` a mano.** Ninguna
corrida de `KnowledgePipeline` había ejercitado nunca ese extractor.

### 1.3 Qué probaban las pruebas E2E

Las diez conjuntas de `test_knowledge_v3_e2e.py` ejercitaban la cadena de verdad,
pero con los dobles del **legacy**: `OLLAMA_PAYLOAD_E01` tenía la forma antigua
(`subject`/`object`/`predicate`/`quote`) y `ScriptedExternalPort` implementaba
`ExternalProposalPort.propose()`. Verdes y honestas sobre lo que había; ciegas al
extractor que se quería medir.

---

## 2. Decisión: **sustituir**, no convivir

```
OllamaExtractor    →  SemanticEpisodeExtractor(OllamaProviderPort)
ExternalExtractor  →  SemanticEpisodeExtractor(NvidiaProviderPort)
```

Sin bandera para volver atrás. Un interruptor que devolviese el legacy sólo
serviría para que una corrida futura volviese a medir otra cosa sin que se notara.
Los dos módulos siguen en el repo, marcados `DEPRECADO` en su cabecera, para
histórico y como término de comparación del banco.

**`ExtractionPipeline.local_default()` NO se toca.** Es el gate: determinista, sin
red, reproducible bit a bit. Nada de semántico ahí, ni hoy ni con una bandera.

---

## 3. Después: qué monta la cadena

```
DeterministicExtractor                          ancla primero (barato, preciso)
TableExtractor                                  lo estructural
SemanticEpisodeExtractor(puerto Ollama)         si wants_ollama
SemanticEpisodeExtractor(puerto externo)        si wants_external
TemporalExtractor                               después de los modelos
CoreferenceExtractor                            siempre el último
```

Cada extractor local **una sola vez**; ningún pipeline anidado dentro de otro.
El orquestador sólo construye **puertos** y **extractores**: no compila prompts, no
normaliza payloads, no valida candidatos y no fija dirección. Toda la lógica
semántica sigue en `extraction/`.

| Antes | Después |
|---|---|
| `Determinista, Tabla, Temporal, [Ollama legacy], [Externo legacy], Correferencia` | `Determinista, Tabla, [Semántico·Ollama], [Semántico·Externo], Temporal, Correferencia` |

### 3.1 Configuración adaptada (mínimo imprescindible)

* `PipelineConfig.ollama_client` sigue siendo un `OllamaClient` (o ya un
  `ProviderPort`); el orquestador lo envuelve en `OllamaProviderPort`.
* `PipelineConfig.external_port` pasa a ser un **`ProviderPort`**
  (`complete_json`). Un objeto con `propose()` —la puerta del legacy— produce
  ahora un `PipelineError` explícito de configuración, no un modo degradado.
* `PipelineConfig.declared()` añade `provider_extractor: "semantic"`: dos corridas
  con extractores distintos no son comparables y eso tiene que verse en el informe.

No se ha refactorizado nada más de la configuración: no era este PR.

### 3.2 Identidad de traza y tope de confianza

`SemanticEpisodeExtractor` deriva ambos del puerto:

| Puerto | `provider` | `name` de traza | tope |
|---|---|---|---|
| Ollama / mock | `ollama` / `local` | `s9k.extraction.semantic` | 0.70 |
| Externo (NVIDIA) | `external` | `external.semantic` | **0.60** |

El nombre externo sale a propósito del espacio reservado `s9k.extraction.*`: un
informe que leyese `s9k.extraction.semantic` con `provider: external` no podría
distinguir una propuesta local de una remota. El tope 0.60 es el mismo que aplicaba
`ExternalExtractor` (`EXTERNAL_CONFIDENCE_CAP`), reutilizado, no duplicado.

Códigos de diagnóstico que cambian de nombre (mismo hecho, puerto agnóstico):

| Legacy | Ahora |
|---|---|
| `OLLAMA_UNAVAILABLE`, `EXTERNAL_PROVIDER_FAILED` | `PROVIDER_UNAVAILABLE` |
| `OLLAMA_INVALID_JSON`, `EXTERNAL_PAYLOAD_MALFORMED` | `PROVIDER_INVALID_JSON`, `MODEL_PAYLOAD_MALFORMED` |

---

## 4. Pruebas (`tests/test_knowledge_v3_e2e_semantic_wiring.py`)

Todas instancian el **orquestador real** y miran los objetos montados o lo que sale
por el otro extremo. Ninguna comprueba nombres por `grep`.

| # | Qué fija |
|---|---|
| 9.1 | Ollama activo → 1 `SemanticEpisodeExtractor` sobre `OllamaProviderPort`; `OllamaExtractor` **ausente** |
| 9.2 | Externo activo → `SemanticEpisodeExtractor` sobre el puerto dado; `ExternalExtractor` **ausente**; nombre fuera del espacio local; tope 0.6; puerto sin `complete_json` = error |
| 9.3 | Los dos activos → 1 determinista, 1 tabla, 1 temporal, 1 correferencia, **2** semánticos (uno por puerto), 6 extractores, orden declarado, sin pipelines anidados |
| 9.4 | `local_default()` intacto: mismos 4 extractores, sin semántico, sin puertos; `local_only` monta exactamente eso; determinismo bit a bit sobre `dev` |
| 9.5 | **Regresión**: se espía el `__init__` de los dos legacy con `monkeypatch`; montar y **correr** la cadena no instancia ninguno |
| 9.6 | 2 `predicate_candidates` (LEADS 0.72 / MEMBER_OF 0.23) y 2 `direction_candidates` llegan íntegros al MOTOR: ni reducidos a uno ni cableados a `SUBJECT_TO_OBJECT` |
| 9.7 | El prompt real lleva tipos, predicados, definiciones, dominio/rango, simetría, inversas, confundibles, glosario, cargos, términos ambiguos, calendarios y **versión de ontología**; y no lleva `fragment_id` |
| 9.8 | Timeout / JSON inválido / no disponible / respuesta vacía / predicado fuera de ontología: los locales siguen, queda diagnóstico, no se aprueba, no se escribe, el lote entero se recorre |
| 9.9 | Autoridad: 0.99 del proveedor → ≤0.6 y revisión; ningún claim de proveedor se acepta solo; el plan lo firma el motor local; ninguna operación sin su decisión |
| 9.10 | Las 10 conjuntas siguen verdes **sin rebajar assertions**: sólo se han portado los dobles a la forma semántica y los dos códigos de diagnóstico renombrados |

Los dobles de `test_knowledge_v3_e2e_fixtures.py` se han portado a la forma
semántica (`local_ref`, `predicate_candidates`, `direction_candidates`,
`evidence_quote`, `abstentions`) y `ScriptedExternalPort` es ahora un
`ProviderPort`. Se han portado los **dobles de transporte**, no las
comprobaciones: ninguna aserción se ha debilitado.
