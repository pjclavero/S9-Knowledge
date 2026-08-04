# Puerta 4, bloque B3: carril semantico NVIDIA en modo sombra

## Objetivo del bloque

B2 dejo la cobertura del extractor determinista en 0.607 sobre el gold
congelado de la puerta 4 (split `negation`, 57 claims / 56 casos evaluables).
B3 mide, honestamente, que aporta anadir un carril **semantico real** apoyado
en NVIDIA NIM (`meta/llama-3.3-70b-instruct`) al lado del determinista --
**siempre en SOMBRA**: el carril NVIDIA nunca escribe en Neo4j, nunca decide,
nunca se activa en produccion. Solo se compara contra el gold y contra el
determinista.

## Que se reutiliza (nada de esto es nuevo en B3)

| pieza | ruta | por que se reutiliza |
| --- | --- | --- |
| Gold congelado (57 claims, hash verificado) | `data-engine/app/knowledge_v3/benchmarks/datasets/negation/` (cargado via `knowledge_v3.eval.dev_corpus.load_dev_gold`) | es el MISMO split que miden B0/B1/B2; ni un byte se toca |
| Extractor semantico agnostico de proveedor | `knowledge_v3/extraction/semantic.py` (`SemanticEpisodeExtractor`) | ya implementado para el bloque de extraccion V3, ontologia cerrada, abstencion, anclaje de citas |
| Puerto NVIDIA | `knowledge_v3/extraction/provider_port.py::NvidiaProviderPort` sobre `external_processing/providers/nvidia.py::NvidiaProcessingProvider` | transporte HTTP, autenticacion y saneado de secretos YA implementados y auditados; B3 no abre un socket propio |
| Extractor determinista | `knowledge_v3/extraction/pipeline.py::ExtractionPipeline.local_default()` | el mismo pipeline heuristico usado como configuracion `A` en `semantic_bench.py` |
| Reconciliador de fusion coreferente (B2) | `knowledge_v3/reconcile/reconciler.py::ProposalReconciler` | el MISMO reconciliador que uso B2, invocado tal cual (configuracion `D-R` de `semantic_bench.py`) |
| Cache en disco de respuestas de proveedor | `knowledge_v3/extraction/semantic_bench.py::CachingPort` | evita refacturar una repuntuacion |
| Emparejamiento gold/prediccion | `knowledge_v3/benchmarks/matching.py` | mismo criterio de "uno a uno" y clave de claim que usa el arnes general |

## Que anade B3 (nuevo, en `scripts/gate4/measure_b3.py`)

* `RetryingPort`: backoff exponencial (2s, 4s, 8s, 16s, tope 30s) ante fallos
  de transporte (`ProviderUnavailable` -- 429/5xx/timeout ya vienen mapeados
  asi por el puerto existente) y timeout DURO de 60s por episodio (ejecutado
  en un hilo aparte para poder cortarlo aunque el socket no respete su propio
  timeout). Un `ProviderBadJSON` (el modelo contesto, pero mal) NO se
  reintenta aqui: eso ya lo resuelve el propio puerto.
* `MeteringPort`: mide cada llamada REAL (nunca las servidas desde cache) --
  latencia, tokens de entrada/salida, reintentos. Se coloca DEBAJO de
  `CachingPort` para que un acierto de cache no aparezca facturado.
* `family_recall`/`b3_gates`: traduce las metricas del extractor semantico
  (que hablan en `precision`/`recall`/`tp`/`fp`/`fn` de claims) al vocabulario
  de la puerta 4 (`cobertura`, `recall_simple`, `falsos positivos`), con
  desglose por familia de negacion, y deriva el veredicto CONFORME/NO_CONFORME
  contra los MISMOS umbrales que B0-B2 (cobertura >= 0.60, recall SIMPLE >=
  0.70) -- B3 no redefine el liston, mide si el carril nuevo ayuda a
  alcanzarlo.
* `_episode_for_semantic_pipeline` / `_build_context_negation`: **ajuste de
  compatibilidad declarado**. El gold de `negation` se autoro para el runner
  E2E congelado (que no pasa los episodios por `SourceEpisode.from_dict`) y
  por eso omite tres claves que ese contrato exige por FORMA aunque sean
  `Optional` por tipo (`speaker`, `turn`, `table`). B3 rellena esas tres
  claves a `None` en una copia EN MEMORIA antes de construir el contexto de
  extraccion, para poder reutilizar el mismo extractor semantico que ya corre
  sobre el split `dev`. El fichero en disco no se toca; la integridad ya se
  verifico por hash antes de este ajuste (`load_dev_gold(verify=True)`).

## Limitacion declarada: "determinista" en B3 no es el pipeline E2E de B0-B2

El 0.607 de B2 lo mide la cadena COMPLETA (normalizador + reglas de negacion
`extraction/cues.py` + motor + resolutor + writer en DRY-RUN, via el runner
congelado `artifacts/v3-final-validation/gate4_negation_measure.py`). La
configuracion `A` de `semantic_bench.py` -- que este bloque usa como
"determinista" para poder comparar en el MISMO arnes de matching que el carril
NVIDIA -- es `ExtractionPipeline.local_default()`: un extractor heuristico de
menciones/claims, no el clasificador de negacion de `cues.py`. Son dos
componentes deterministas DISTINTOS del repositorio. Esta asimetria se declara
aqui explicitamente, con el mismo criterio que ya usa
`knowledge_v3/eval/harness.py` para la asimetria dev/generalizacion: no se
esconde, se dice. La cifra de "determinista" de B3 responde a la pregunta
"¿que pasa si NVIDIA se compara con el otro extractor determinista del
repo, en el arnes de matching de claims?", no a "¿mejora el 0.607 de B2?".

**Como obtener la cifra comparable al 0.607 (via designada, bloque futuro).**
La conexion mecanica YA existe:
`knowledge_v3.pipeline.runner.run_one(gold, "external_only", ..., external_port=puerto)`
acepta un proveedor externo sobre este mismo split sin tocar produccion
(demostrado con test ejecutable en
`data-engine/app/tests/test_gate4_b3_adversarial.py`). Lo que queda como
trabajo real para ese bloque es: envolver `NvidiaProviderPort` con el
retry/metering/cache de B3 en esa ruta, y resolver la entrada raw-vs-episodes
del runner. Esa corrida es cara (otra tanda completa contra la API) y es
decision del orquestador; este bloque NO la ejecuto.

## Modo sombra: garantias verificadas, no solo declaradas

* `scripts/gate4/measure_b3.py` no importa ningun modulo de
  `knowledge_v3.writer.*` ni `neo4j` (comprobado por
  `test_gate4_b3_nvidia_shadow.py::test_measure_b3_no_importa_ningun_modulo_de_escritura_neo4j`).
* La API key de NVIDIA se lee del entorno (`S9K_NVIDIA_API_KEY`) por
  `external_ai.registry.get_api_key()`/`NvidiaProcessingProvider`, nunca por
  este script, y nunca se imprime ni se escribe en ningun artefacto -- ver el
  grep final contra los artefactos commiteados de B3 en el informe de cierre
  del bloque.

## Como reproducir la medicion

```bash
export S9K_NVIDIA_ENABLED=true
export S9K_NVIDIA_API_KEY=...        # nunca en la linea de comandos ni en un fichero versionado
cd /ruta/al/repo
PYTHONPATH=data-engine/app python3 scripts/gate4/measure_b3.py \
    --out-dir artifacts/gate4-program --out-name b3-nvidia-shadow \
    --cache artifacts/gate4-program/b3-cache --concurrency 2
```

`--mock` sustituye NVIDIA por un puerto guionizado (sin red, sin key): sirve
para probar el script sin gastar una sola llamada, y es lo que usan los tests
unitarios (`data-engine/app/tests/test_gate4_b3_nvidia_shadow.py`).

La cache de respuestas vive en `artifacts/gate4-program/b3-cache/` y NO esta
versionada (ver `.gitignore` del bloque): son respuestas de un modelo de
terceros bajo la clave del operador, no un artefacto de programa; el
resultado agregado que si se versiona es `b3-nvidia-shadow.{json,md}`.

## Resultados (corrida real del 2026-08-04)

Cifras completas en `artifacts/gate4-program/b3-nvidia-shadow.{json,md}`,
generadas de punta a punta por el script (nada transcrito a mano). Lectura
honesta de la corrida:

* El carril NVIDIA en sombra alcanza cobertura **0.3571** (20/56 evaluables,
  convencion de B0-B2: el ABSTAIN puro del gold se excluye del denominador,
  correccion del dictamen) y recall SIMPLE **0.4545**: **NO_CONFORME** contra
  los umbrales del programa (0.60 / 0.70). Precision 0.5588 con 15 falsos
  positivos.
* La configuracion `A` (etiquetada `heuristico_local_bench` en el artefacto)
  da 0.0 en este arnes de claims: no propone claims emparejables. Por eso la
  vista `nvidia_mas_heuristico_reconciliado` coincide con NVIDIA sola (la
  nota de cada carril lo dice dentro del propio JSON).
* Estabilidad de la API (tanda original, 2026-08-04 por la manana): 50
  reintentos de transporte, 31 timeouts duros de 60s y 2 episodios perdidos
  (3.3%) tras agotar reintentos; latencia media 36.0s por llamada, p95 53.4s.
  Los 2 episodios perdidos se recuperaron en la regeneracion desde cache del
  mismo dia (2 llamadas reales adicionales, ambas OK), por lo que el
  artefacto final cubre 60/60 episodios y su seccion de incidencias refleja
  la corrida de regeneracion, no la tanda original. **Advertencia**: una sola
  corrida no distingue un pico puntual del comportamiento habitual del
  proveedor.
* Tokens (tanda completa, 60 llamadas): 247,851 de entrada + 19,811 de
  salida = 267,662 totales (~4,461/episodio); extrapolacion ~4.46M tokens por
  1000 episodios. No hay precio fiable documentado en el repo ni precio
  publico por token verificable para este modelo en NVIDIA NIM: el coste
  queda como parametro (`--price-per-million-tokens-usd`) y la decision de
  adopcion debe tomarla el operador con su contrato en la mano.
