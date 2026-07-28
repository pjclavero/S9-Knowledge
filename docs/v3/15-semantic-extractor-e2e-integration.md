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

---

# Parte 2 · Negaciones

Commit separado: `fix: preserve negated claims through V3 pipeline`.

## 5. Principio

> Una afirmación negativa es información válida.
> **"relación negada" ≠ "ausencia de relación" ≠ "relación positiva".**

El extractor **detecta, propone, marca `negated=true` y conserva la cita**. El
**motor** decide qué significa. El plan nunca convierte una negación en una
arista positiva.

### 5.1 Los cinco valores

| Valor | Texto | Qué significa |
|---|---|---|
| `SIMPLE` | "A no pertenece a B" | afirmación negativa corriente |
| `NEVER` | "A nunca perteneció a B" | negación absoluta, **ligada al contexto temporal de la fuente**: no se deriva ningún intervalo infinito |
| `CESSATION` | "A ya no lidera B", "dejó de servir", "abandonó el clan", "rompió su alianza" | hubo relación y termina; `temporal_resolution_required = true` |
| `NOT_YET` | "A todavía no lidera B" | **no** es cesación: no demuestra que antes lo fuera |
| `SCOPE_AMBIGUOUS` | "el magistrado no cree que A pertenezca a B", doble negación | el texto niega, pero no consta que niegue *esta* relación → abstención / revisión, **nunca negación mecánica** |

No factual (pregunta, condicional, deseo, orden, prohibición) no produce claim
afirmado. Se separan dos tratamientos, y la diferencia está medida:

* **pregunta / condicional / ficción interna / falsedad** → no se emite **nada**
  (`payload._drop_non_factive`, decisión ya tomada en el bloque 12: eran las
  "trampas pisadas" que en realidad eran abstenciones bien razonadas);
* **deseo / orden / prohibición** (`DESIRE_CONTEXT`, `DEONTIC_CONTEXT`, nuevos)
  → **abstención con su rastro**: ahí el texto sí habla de esa relación, y
  perder la traza sería perder información.

### 5.2 Contrato: `negation_kind` va en `metadata`

Decisión del organizador, respetada al pie de la letra: **no se ha añadido un
solo campo a ningún schema**. `negation_kind` viaja en `metadata`, la única
excepción documentada a `additionalProperties: false`, junto a
`temporal_resolution_required` y `untrusted_origin`. También se conserva
`negation_kind_model` cuando lo que dijo el modelo difiere de lo que la evidencia
respalda — sin eso no se podría medir después si el modelo acierta.

**No hay bloqueo de contrato que reportar.** `metadata` ha bastado para que el
motor decida sin releer el texto: `ClaimDecision.negation_kind` sale de ahí y
`engine/negation.py` no mira una sola cadena del episodio.

## 6. Detección local (`extraction/cues.py`)

`classify_negation()` es la única regla, y la comparten el extractor
determinista y la frontera de modelos. Precedencia:

```
1. ALCANCE     "no <verbo de actitud>"   -> SCOPE_AMBIGUOUS  (negated=False)
2. DOBLE       dos marcas en la cláusula -> SCOPE_AMBIGUOUS  (negated=False)
3. NOT_YET     "todavía no", "aún no"    -> antes que cesación, a propósito
4. CESSATION   "ya no", "dejó de", …     -> la mitad no llevan marca de negación
5. NEVER       "nunca", "jamás"
6. SIMPLE      "no", "tampoco", "ni"
```

Dos piezas nuevas que valen la pena:

* **alcance de cláusula** (`clause_start`). "Kael no llegó a tiempo, **pero**
  Mira pertenece al Gremio": la negación no cruza una conjunción adversativa ni
  un signo de puntuación. Antes cruzaba, y convertía una afirmación positiva en
  su contraria. Los límites por puntuación se buscan en el **hueco entre
  tokens** (el tokenizador es `\w+`), lo que obliga a pasar el texto con offsets
  absolutos.
* **verbos de actitud** (`scope_negation`). Se buscan en toda la frase anterior
  a la relación, no en la ventana corta: lo que descalifica la propuesta no es
  la distancia, es que la relación cuelgue de la creencia de otro.

### 6.1 La evidencia manda sobre el modelo

En `normalize_semantic_payload`, tres reglas de un solo sentido:

| Situación | Resultado |
|---|---|
| el texto niega y el modelo dice `negated=false` | abstención `NEGATION_CONTEXT_MISMATCH` — el proveedor **no puede borrar** una negación |
| el modelo dice `negated=true` y el texto no lo respalda | abstención `NEGATION_NOT_IN_EVIDENCE` — el proveedor **no puede inventarla** |
| alcance ambiguo o doble negación | abstención `REVIEW_NEGATION_SCOPE` |

Se mantienen intactas las guardas previas: cita literal obligatoria, anclaje
verificado, sujeto + objeto + predicado presentes, y `negation_kind` desconocido
se diagnostica (`UNKNOWN_NEGATION_KIND`) y se degrada a `SIMPLE`.

## 7. Prompt (`ontology_prompt.py`, v1.1.0 → **v1.2.0**)

* regla 6 nueva y explícita: **una relación negada es un claim válido**, no se
  omite por estar negada, se marca `negated` y `negation_kind` con los cuatro
  tipos y su definición; "todavía no" no es cesación;
* regla 7: rumor sin confirmar es `RUMORED`, no `ASSERTED` con negación;
* regla 8 ampliada con **deseo, orden y prohibición**, y con la aclaración de que
  esto **no** contradice la regla 6 (una negación sí ocurre en el mundo; una
  pregunta o un deseo, no);
* `negation_kind` en el esquema de respuesta;
* tres ejemplos few-shot nuevos (5 · negativo simple, 6 · cesación, 7 · negación
  de otra cláusula y de la creencia) con entidades **inventadas** ajenas al
  corpus: *Zenobia Trask*, *Hermandad del Yunque*, *Puerto Nix*. Si el modelo las
  copiase, el anclaje local las tumbaría como `HALLUCINATED_MENTION` y se vería
  en el informe.

## 8. Motor (`engine/negation.py`, nuevo)

El motor **no lee texto**: lee `negated` y `metadata.negation_kind`, que la
frontera ya validó contra la evidencia.

| Tipo | Decisión |
|---|---|
| `SIMPLE` / `NEVER` | puede producir `FactAssertion` con `negated=true`. **Sin materializar arista positiva**: `PROJECT_RELATION` no se emite para hechos negativos |
| `CESSATION` **con** positiva vigente compatible | **transición**: `CREATE_ASSERTION` negativa con `supersedes` + `SUPERSEDE_ASSERTION` sobre la anterior (`status: SUPERSEDED`, `superseded_by`, `valid_to`, `reason_code`), con `expected_version`/`expected_hash` del snapshot. Historia y evidencia intactas |
| `CESSATION` **sin** positiva vigente | **no inventa la relación previa**: `CESSATION_WITHOUT_ACTIVE_ASSERTION` → `REVIEW_TEMPORALITY` |
| `CESSATION` sobre una vigente **sin `state_hash`** | `CESSATION_TARGET_UNANCHORED` → revisión. Sin concurrencia optimista no se cierra ninguna vigencia |
| `NOT_YET` | `NEGATION_NOT_YET` (aviso). No cierra nada |
| `SCOPE_AMBIGUOUS` | `NEGATION_SCOPE_AMBIGUOUS` → revisión |

**Contradicción vs transición.** Una cesación **no** contradice la afirmación que
cierra: están separadas en el tiempo. `check_contradictions` recibe ahora
`skip_assertion_ids` con *ese* identificador —por ID, no por regla— así que
cualquier **otra** afirmación sigue entrando en el eje. Una negativa `SIMPLE`
contra una positiva vigente sigue siendo `CONFLICT_WITH_EXISTING` y
`epistemic_status = CONFLICTED`, sin elegir automáticamente la más reciente.

`valid_to` del cierre sale de `temporal.valid_from` o, en su defecto,
`event_time`. Si el texto no fecha la cesación sale `None`: una vigencia sin
fecha de cierre es honesta; una fecha inventada, no.

El **writer no se ha tocado**: `SUPERSEDE_ASSERTION` ya estaba soportado, con su
`reason_code` obligatorio (R1) y su `expected_version`. Ejecuta; no interpreta.

## 9. Pruebas (`tests/test_knowledge_v3_negation.py`, 45)

* **extractor (11)** — los diez casos del encargo sobre texto real: simple,
  nunca, ya no / dejó de / cesó / abandonó / rompió su alianza, todavía no, aún
  no, alcance complejo, negación en otra cláusula, doble negación, `ni`/`tampoco`
  como coordinación, pregunta y prohibición;
* **frontera semántica (6)** — el proveedor no puede borrar ni inventar una
  negación, el alcance ambiguo no se resuelve mecánicamente, un tipo desconocido
  se diagnostica, y el prompt pide explícitamente las relaciones negadas;
* **motor (11)** — negativa sin previa, sin arista positiva, cesación que cierra
  sin borrar (con `expected_version`/`expected_hash`), separación temporal que no
  es contradicción, cesación sin previa que no inventa, cesación sin ancla,
  contradicción real, `NEVER` sin intervalo, `NOT_YET` que no cierra, alcance
  ambiguo, y positiva + negativa en el mismo lote;
* **E2E por `KnowledgePipeline` (17)** — control positivo, negativo, `NEVER`,
  `CESSATION`, `NOT_YET`, pregunta, alcance ambiguo, deseo, y el cierre de una
  afirmación previa: se comprueba que `negated`, el tipo, la evidencia, la
  temporalidad y la decisión sobreviven hasta el plan, y que **ninguna** negación
  produce una operación con `negated=false`.

## 10. Métricas de negación en el banco

`semantic_bench.negation_metrics()` añade, sobre el mismo emparejamiento del
arnés:

| Métrica | Qué mide |
|---|---|
| `gold_negated` | negativos que hay en el gold |
| `predicted_negated` | negativos propuestos como claim afirmado |
| `correct_negated` | emparejados con un gold negativo **y** marcados |
| `negated_as_abstention` | convertidos en abstención (no es acierto, tampoco error grave) |
| `positive_created_for_negated_gold` | **el error caro**: gold negativo propuesto como relación positiva |
| `kinds`, `cessation_detected`, `cessation_with_temporal_flag` | reparto por tipo y cierres temporales correctamente señalados |

---

# Parte 3 · Medición

Todo sobre el split **`dev`**. El **held-out no se ha tocado** y el gold **no se
ha modificado**. Las corridas de cadena entran **por el orquestador**
(`python -m knowledge_v3.pipeline.runner`), no llamando al extractor.

```bash
export PYTHONPATH=data-engine/app

# banco AISLADO (llama directo al extractor)
python3 -m knowledge_v3.extraction.semantic_bench --config A
python3 -m knowledge_v3.extraction.semantic_bench --config C1 --config D \
        --cache docs/v3/measurements/runs/c1-cache.json

# CADENA (por el orquestador)
python3 -m knowledge_v3.pipeline.runner --split dev --ablation local_only
python3 -m knowledge_v3.pipeline.runner --split dev --ablation local_plus_external --ollama
```

Equivalencias, porque los nombres no coinciden por casualidad:

| Configuración | Banco aislado | Cadena (ablación del orquestador) |
|---|---|---|
| **A** determinista | `--config A` | `local_only` |
| **C1** semántico Ollama | `--config C1` | *no existe aislada en la cadena*: el orquestador nunca monta el semántico sin los locales (`external_only` sin puerto no deja extractor). Es una diferencia real y se declara |
| **D** determinista + semántico | `--config D` | `local_plus_external --ollama` |

## 11. C2 (NVIDIA): preparado, **no ejecutado**

Es nube, de pago y con *rate limit*. Queda listo y sin lanzar. Para lanzarlo en
**VM105**, donde vive la clave:

```bash
ssh vm105
cd /opt/s9-knowledge            # repo desplegado
export PYTHONPATH=data-engine/app
export S9K_REPO_ROOT="$PWD"
set -a; . /etc/s9-knowledge/nvidia.env; set +a   # S9K_NVIDIA_API_KEY

# 1) banco aislado, con caché en disco para no repetir la tanda
python3 -m knowledge_v3.extraction.semantic_bench --config C2 \
        --cache runs/c2-cache.json --out runs/bench-C2.json

# 2) cadena, por el orquestador
python3 - <<'PY'
from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.extraction.provider_port import NvidiaProviderPort
from knowledge_v3.pipeline.runner import run_one, write_reports
from pathlib import Path

gold = load_gold("dev")
report, _ = run_one(
    gold, "no_ollama", workspace="bench-dev",
    external_port=NvidiaProviderPort(),   # el carril externo YA es un ProviderPort
)
write_reports(report, Path("runs"), "dev-no_ollama-nvidia-chain")
PY
```

Avisos, medidos en la ronda anterior: 4 de 16 episodios fallaron con
`PROVIDER_UNAVAILABLE`, así que cualquier *recall* de C2 se lee con una cuarta
parte del corpus sin ver. Y `nvidia.env` **no lo carga ninguna unidad systemd**:
hay que exportarlo a mano (deuda ya declarada en `14-estado-y-decisiones.md`).

## 12. Resultados

Salidas crudas en `docs/v3/measurements/runs/`. `etapas-*.json` lo produce
`scripts/dev/v3_chain_report.py`, que corre la cadena por el orquestador y cuenta
**documento a documento en cada etapa** — es lo que responde *entre qué dos
etapas desaparecen los claims*, que el arnés (que puntúa la salida) no puede
decir.

### 12.1 A · determinista — banco aislado **vs** cadena E2E

| | Banco aislado (`--config A`) | Cadena (`local_only`) | Δ |
|---|---|---|---|
| Menciones P / R / F1 | 0.905 / 0.745 / **0.817** | 0.905 / 0.745 / **0.817** | **0** |
| Claims P / R / F1 | — / 0.000 / — (tp 0, fn 20) | — / 0.000 / — (tp 0, fn 20) | **0** |
| Predicado top-1 / top-2 | 0.000 / 0.000 | — (sin claims) | — |
| Dirección top-1 | 0.000 | — (sin claims) | — |
| Correferencia P / R / F1 | 1.000 / 0.500 / 0.667 | 1.000 / 0.500 / 0.667 | **0** |
| Trampas pisadas | 0 / 4 | 0 / 4 | **0** |
| Abstenciones | 0 | 0 | **0** |
| Latencia | 97 ms | 272 ms (cadena entera, 6 fuentes) | — |

**El banco aislado y la cadena dan exactamente lo mismo para A**, y tenía que ser
así: `local_only` monta los mismos cuatro extractores que
`ExtractionPipeline.local_default()`. Que coincida *bit a bit* es la prueba de que
el orquestador no añade ni quita nada por su cuenta.

### 12.2 Dónde se pierden los claims (A · `local_only`)

```
episodios          16
fragmentos         72
menciones          42      <- el determinista sí ancla
claims extraídos    0      <- SE PIERDEN AQUÍ: en la EXTRACCIÓN
resoluciones       40
decisiones          0
afirmaciones        0
planes              0      (6 fuentes paradas en "engine": sin claims que decidir)
ledger              0
```

**La pérdida es íntegra en la extracción, no en la resolución, ni en el motor, ni
en el ledger.** Las 6 fuentes se detienen en la etapa `engine` con
`PIPELINE_STOPPED: el extractor no propuso ningún claim para esta fuente`. Es el
mismo hallazgo del bloque 12 —las 14 reglas léxicas del determinista no aparecen
ni una vez en `dev`— ahora localizado por etapa en vez de deducido. Aguas abajo de
la extracción no se pierde **ni un solo documento**: 42 menciones → 40
resoluciones (los 2 que faltan son menciones agrupadas por correferencia, no
descartes).

### 12.3 D · determinista + semántico, por la CADENA, con Ollama REAL

`local_plus_external --ollama` contra `192.168.1.157:11434` (qwen2.5:7b), 16
episodios, **58 llamadas al proveedor**, **48 min 28 s** de pared. Prompt
**1.2.0**. Es la primera vez que el extractor semántico se mide *dentro* de la
cadena: hasta este bloque, esa corrida montaba el legacy.

| | A · cadena (`local_only`) | D · cadena (`local_plus_external` + Ollama) |
|---|---|---|
| Menciones P / R / F1 | 0.905 / 0.745 / **0.817** | 0.476 / **0.765** / 0.586 |
| Menciones tp / fp / fn | 38 / 4 / 13 | 39 / **43** / 12 |
| Tipo de entidad correcto | 0.000 | **0.949** (37/39) |
| Claims P / R / F1 | — / 0.000 / — | 0.000 / 0.000 / 0.000 |
| Claims tp / fp / fn | 0 / 0 / 20 | 0 / **18** / 20 |
| Correferencia P / R / F1 | 1.000 / 0.500 / 0.667 | 1.000 / 0.500 / 0.667 |
| Resolutor · acción correcta | 0.923 (12/13) | 0.923 (12/13) |
| **Trampas pisadas** | 0 / 4 | **0 / 4** |
| Evidencia anclada | — (sin claims) | 100 % (todo claim emitido lleva su cita) |
| Abstenciones | 0 | **10** de 18 claims |
| Latencia | 272 ms | **2 907 796 ms** (48 min) |
| Llamadas a proveedor | 0 | 58 |

Lecturas, sin maquillar:

1. **El semántico aporta lo que el determinista no tiene y viceversa.** Tipo de
   entidad pasa de 0.000 a **0.949** y el *recall* de menciones sube. A cambio, la
   precisión de menciones se hunde (43 falsos positivos) porque la salida es la
   **UNIÓN** de los dos extractores sin reconciliador: 42 menciones locales + 40
   del modelo, muchas la misma entidad con dos identificadores.
2. **Los claims no puntúan, y no es porque se pierdan en la cadena.** 18 claims
   extraídos → **18 decisiones del motor**: no se cae ni uno entre etapas. Lo que
   falla es el EMPAREJAMIENTO del arnés: es uno a uno sobre menciones, adjudica
   cada mención a uno de los dos extractores y deja los claims del otro con
   argumentos sin alinear. Es exactamente el defecto que `14-estado-y-decisiones.md`
   §2.5 dejó anotado como justificación medida del `ProposalReconciler`, ahora
   confirmado **dentro** de la cadena y no sólo en el banco.
3. **Cero trampas pisadas** (0/4) y cero claims no anclados en los episodios
   trampa: la capa local de no-factividad se sostiene con el prompt 1.2.0.

### 12.3.1 Dónde se detiene la cadena (D)

```
episodios          16
fragmentos         72
menciones          82      (42 deterministas + 40 del modelo, sin fundir)
claims extraídos   18      -> 8 activos + 10 abstenciones
resoluciones       80
decisiones         18      <- NO se pierde ni un claim entre extracción y motor
   ACCEPT           0
   REVIEW           7
   ABSTAIN         10
   REJECT_INVALID   1
afirmaciones        0
planes              5      (0 aprobados)
ledger              0
```

**La cadena no pierde claims: los detiene, y en un sitio declarado.** Ninguna
fuente se para (`fuentes_paradas: []`, frente a las 6 de `local_only`). El corte
está en la DECISIÓN: **0 ACCEPT**, porque todo claim de LLM nace con
`review_required=True` y el motor lo respeta. No es un fallo del extractor ni del
motor; es la política de "origen no confiable ⇒ revisión humana" que
`14-estado-y-decisiones.md` §4.3 ya tiene listada como lo siguiente a atacar.
Ahora está **medida en la cadena**: 7 REVIEW + 10 ABSTAIN + 1 REJECT_INVALID, 5
planes construidos y firmados, ninguno aprobado, ledger vacío.

### 12.3.2 C1 aislado (semántico solo) — en curso

La pasada del banco aislado con el prompt 1.2.0
(`semantic_bench --config C1 --config D`) seguía ejecutándose al cerrar este
documento; a ~50 min por pasada contra este servidor, no cabía en la sesión. El
comando está lanzado y su salida cae en
`docs/v3/measurements/runs/bench-C1-D.json`, con caché en disco
(`c1-cache.json`) para que repuntuar no obligue a repetir la tanda.

Aviso para quien lea la tabla de `14-estado-y-decisiones.md` §2: **las cifras C1 y
C2 de allí son del banco AISLADO con el prompt 1.1.0**. No son comparables con
las de aquí (cadena, prompt 1.2.0), y por eso la versión del prompt viaja en la
traza.

### 12.4 Negación

Medido en la cadena D (Ollama real, 16 episodios, 18 claims):

| Métrica de negación | D · cadena |
|---|---:|
| Negativos en el gold | 3 |
| Claims negados propuestos | 0 |
| Convertidos en abstención | 0 |
| **Relaciones positivas creadas por error desde un negativo** | **0** |
| Cierres temporales propuestos | 0 |
| Afirmaciones negativas escritas | 0 |

**Cero de tres**: el modelo no propuso ninguno de los tres negativos del gold, y
tampoco los propuso en positivo — que es el error caro y el que este bloque existe
para impedir. El corpus `dev` no tiene ninguna cesación, así que ese camino no se
ejercita por aquí en absoluto; sí se ejercita, y se fija, en las 45 pruebas
(incluidas 17 E2E por `KnowledgePipeline` con texto que sí niega). Que la métrica
de corpus salga a cero es una limitación **del corpus**, no del detector, y decirlo
al revés sería exactamente el tipo de lectura que este programa lleva diez bloques
evitando.

Lo que sí está medido y demostrado:

| | antes | después |
|---|---|---|
| Tipos de negación distinguidos | **0** (un booleano `negated`) | **5** (SIMPLE, NEVER, CESSATION, NOT_YET, SCOPE_AMBIGUOUS) |
| Negación que cruza a otra cláusula | sí (falso positivo) | **no** |
| "no cree que X…" negaba la relación | sí | **no** — abstención `REVIEW_NEGATION_SCOPE` |
| Un proveedor podía borrar una negación | sí | **no** — `NEGATION_CONTEXT_MISMATCH` |
| Un proveedor podía inventar una negación | **sí** | **no** — `NEGATION_NOT_IN_EVIDENCE` |
| Cesación que cierra vigencia | no existía | `SUPERSEDE_ASSERTION` anclado, historia intacta |
| Cesación sin relación previa | — | no la inventa: `CESSATION_WITHOUT_ACTIVE_ASSERTION` |
| Relaciones positivas creadas por error desde un negativo | posible | **imposible**: sin `PROJECT_RELATION` y con prueba E2E |
| Pruebas de negación | 0 | **45** |

Las métricas de banco (`negation_metrics`) quedan añadidas y se leerán con
contenido en cuanto el corpus tenga negaciones que el extractor de la cadena
proponga: en `A` sobre `dev` dan `gold_negated: 3`, todo lo demás a 0.
