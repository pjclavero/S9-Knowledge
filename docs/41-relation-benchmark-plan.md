# 41 - Benchmark de extraccion de relaciones: plan y metodo (v1)

Plan del **runner y comparador** que ejecuta el **pipeline R8 REAL**
(`relations.pipeline.run_pipeline`) sobre el **corpus B1 REAL**
(`data-engine/app/tests/data/relation_benchmark/`) y compara sus predicciones
contra el ground truth. Los resultados reales viven en
`docs/50-relation-benchmark-results.md`.

Regla critica de diseno: **el runner importa y ejecuta R8; NO reimplementa ninguna
etapa (pares, senales, sintaxis, consenso) y NO simula resultados finales.** Un
`assert` en tiempo de import (`relations/benchmark/runner.py`) y un test
(`test_usa_pipeline_r8_real`) garantizan que `run_pipeline` es la funcion real del
pipeline, no un espejo.

## 1. Arquitectura del paquete

`data-engine/app/relations/benchmark/`:

- `runner.py`    - carga del corpus + integridad, derivacion determinista de
  entidades de entrada, ejecucion del pipeline REAL por fuente y por corpus.
- `matching.py`  - emparejamiento determinista prediccion <-> ground truth y
  comprobaciones estructurales.
- `metrics.py`   - metricas globales, por predicado, estructurales y operativas.
- `report.py`    - ensamblado del informe, GATES y dictamen.
- `cli.py`       - `python -m relations.benchmark.cli` -> JSON, JSONL y Markdown.

## 2. Derivacion de la ENTRADA del pipeline (construccion, no simulacion)

El pipeline necesita `segments` con `entities` (id, tipo y offsets de caracter),
pero el corpus da las fuentes como TEXTO. La entrada se **deriva de forma
determinista** de las **menciones del ground truth**, lo cual es *construccion de
entrada de benchmark*, no simulacion de resultados: no decide ninguna relacion.

- **Un segmento por fuente**: `segment_id == source_id`, `text` = fuente completa.
  Asi los offsets del ground truth (indices de caracter en la fuente completa) son
  directamente comparables con los de la evidencia que emite el pipeline.
- **Menciones -> entidades**: para cada relacion del ground truth de la fuente se
  localiza el `subject_text` y el `object_text`:
  1. primero DENTRO del span `[evidence_start, evidence_end)`;
  2. si no aparece ahi (sujeto elidido, pronombre, etc.), en la PRIMERA aparicion
     en la fuente completa;
  3. si no aparece en absoluto, la mencion se OMITE y se registra en
     `derivation_notes` (no se inventa posicion).
- Cada mencion produce `{id, text, type, start, end}`. Menciones identicas (mismo
  id y misma posicion) se deduplican. Orden determinista por `(start, end, id, type)`.

Consecuencias asumidas y reportadas honestamente (no se maquillan):

- Sujetos **elididos** o resueltos por **correferencia** (p.ej. "Draven" ausente de
  la evidencia, "le" = Sela) quedan en frases distintas del objeto y R8 no genera
  el par -> **FN reales**.
- Relaciones **reflexivas de alias** (`subject_id == object_id`, p.ej. "el Cuervo"
  = Draven) las excluye el generador de pares de R8 por defecto -> **FN reales**.
- Cuando el ground truth tiene **varias relaciones para el mismo par** en la misma
  fuente (segmentos contradictorios), R8 deduplica a un unico candidato por par y
  segmento -> a lo sumo un TP, el resto FN.

## 3. Modos del benchmark (via PipelineConfig REAL)

El pipeline R8 es **monolitico**: cada ejecucion corre siempre
pares -> senales heuristicas -> sintaxis -> consenso, y **no expone banderas** para
desactivar la sintaxis o el consenso. Reimplementarlas esta PROHIBIDO. Por tanto
los tres modos se materializan como **presets reales de `PipelineConfig`** que
varian el unico parametro de etapa que R8 expone en modo offline: el **modo de
contexto** del emparejamiento (amplitud de los pares). Los proveedores local y
externo estan **siempre deshabilitados** (jamas Ollama/NVIDIA reales, jamas red):

| Modo | `context_mode` | Descripcion |
|---|---|---|
| `baseline1` | `sentence` | par en la misma frase (mas restrictivo). |
| `baseline2` | `paragraph` | par en el mismo parrafo (amplia cobertura). |
| `full_offline` | `segment` | cualquier par del segmento (maxima cobertura offline). |

**Transparencia**: no es posible aislar "solo heuristicas" frente a
"heuristicas+sintaxis" a traves del pipeline real sin reimplementar etapas (que es
lo prohibido); la separacion que si es legitima y se reporta es la de las **capas
de la MISMA salida real**: el candidato heuristico (predicado/evidencia/negacion/…)
frente a la decision de consenso (`consensus.state`/`recommendation`). El dictamen
se emite sobre `baseline1` (el mas conservador, menor riesgo de contaminacion de
pares).

## 4. Criterio de EMPAREJAMIENTO (documentado, sin matching laxo)

### 4.1 Emparejamiento PRIMARIO (existencia de relacion)

Una prediccion P empareja con una relacion de ground truth G si y solo si:

- mismo `source_id`, y
- mismo `workspace`, y
- **mismo par de entidades NO ORDENADO**: `{P.subject_id, P.object_id} == {G.subject_id, G.object_id}`.

Se usa el par **no ordenado** porque el generador de pares de R8 canonicaliza el
"sujeto" como la mencion que aparece **antes en el texto** (orden textual), que no
tiene por que ser el sujeto semantico del ground truth. La direccion semantica se
evalua **aparte**, como atributo estructural, no como condicion de existencia.

**Asignacion 1:1 greedy determinista**: se recorren las relaciones de ground truth
en orden de `relation_id`; cada una toma la mejor prediccion aun libre del mismo
grupo, desempatando por `(predicado correcto, direccion correcta, candidate_id)`.
Relaciones sin prediccion = **FN**; predicciones sin relacion = **FP**. El resultado
es independiente del orden de entrada (se ordena por claves canonicas).

### 4.2 Atributos estructurales (solo sobre los TP)

Se evaluan por separado, sin afectar a la existencia (definidos en
`matching.structural_flags`):

- **predicado**: `normalize_predicate` exacto contra el GT.
- **direccion**: exacta (`SUBJECT_TO_OBJECT`/`OBJECT_TO_SUBJECT`/`UNDIRECTED`); se
  registra ademas una variante tolerante a inversion textual del par.
- **tipos**: conjunto NO ORDENADO de tipos de las dos entidades igual al del GT.
- **negacion**: `bool` exacto.
- **temporalidad**: comprobacion *coarse* de DETECCION. El pipeline emite
  `temporal_scope` como texto libre o `None`; el ground truth usa vocabulario
  cerrado. Se comprueba que el pipeline **detecte marcador temporal exactamente
  cuando** el GT tiene un estado temporal no trivial (`PAST/FUTURE/ONGOING/ENDED`).
  No es una igualdad de vocabulario y se documenta como tal.
- **estado epistemico**: enum exacto (`ASSERTED/RUMORED/HYPOTHETICAL/INTENDED`).
  R8 nunca produce `INTENDED`, por lo que esos casos son incorrectos por diseno.
- **evidencia / offsets**: solape de spans `[start, end)`. `offsets_correct` si la
  interseccion > 0; `evidence_correct` si el IoU (interseccion/union) >= **0.5**
  (`EVIDENCE_IOU_THRESHOLD`). Es la **tolerancia de offsets** del benchmark.
- **workspace**: igualdad exacta.
- **decision**: `recommendation` del consenso -> decision esperada
  (`propose->ACCEPT`, `reject->REJECT`, `human->REVIEW`) comparada con
  `expected_decision`.

## 5. Metricas

- **Globales** (existencia): precision, recall, F1, TP, FP, FN.
- **Estrictas** (par + predicado exacto): un TP de existencia con predicado
  incorrecto degrada a FP y FN.
- **Por predicado del GT**: soporte, recall de existencia y recall de predicado
  exacto; ademas distribucion de predicados **predichos** por el heuristico.
- **Calidad estructural**: tasas de los atributos de §4.2 sobre los TP, con
  subgrupos condicionados (relaciones simples, negadas, temporales, rumores).
- **Operativas** (contadores REALES del `summary` del pipeline, solo agregados):
  documentos/segmentos procesados, pares potenciales/generados/descartados,
  candidatos, estados de consenso, errores, tiempos (total, por doc, por
  candidato) y tasas humana/conflicto/invalida.
- **Determinismo**: se ejecuta el pipeline REAL **>= 2 veces** y se comparan
  `result_hash`, predicciones y metricas.

## 6. Gates (evaluados por separado)

No se declara aptitud solo por el F1 global. Cada gate es independiente
(`report.evaluate_gates`), con umbrales deterministas (`THRESHOLDS`):

| Gate | Tipo | Criterio |
|---|---|---|
| `determinism` | DURO | hashes + predicciones + metricas identicas en 2 ejecuciones. |
| `workspace_contamination` | DURO | cero predicciones cruzando workspaces. |
| `simple_relations` | calidad | evidencia correcta en relaciones simples (ACCEPT/ASSERTED/no negadas). |
| `evidence` | calidad | tasa de evidencia correcta (IoU>=0.5). |
| `offsets` | calidad | tasa de offsets con solape. |
| `negation` | calidad | negacion correcta en relaciones negadas del GT. |
| `temporality` | calidad | deteccion temporal en relaciones temporales del GT. |
| `rumors` | calidad | epistemico correcto en rumores del GT. |
| `predicate_structural` | calidad | predicado exacto sobre los TP. |

Estados: `PASS` (>= umbral), `PARTIAL` (>= 60% del umbral) o `FAIL`.

## 7. Dictamen del benchmark (vocabulario cerrado)

`report.decide_verdict` elige de forma determinista uno de:

- `APTO PARA CONTINUAR EN MODO SOMBRA`
- `APTO CON REVISION DE CASOS CONFLICTIVOS`
- `APTO CON REVISION HUMANA TOTAL`
- `NO APTO`

**PROHIBIDO** el veredicto "APTO PARA INGESTA REAL". Cualquier gate DURO en `FAIL`
fuerza `NO APTO`. Los numeros que se reportan son los reales del pipeline, aunque
sean bajos.

## 8. Salidas y ejecucion

```bash
cd data-engine/app
python -m relations.benchmark.cli --mode baseline1 --all-modes \
    --out-json /tmp/results.json \
    --out-jsonl /tmp/predictions.jsonl \
    --out-md ../../docs/50-relation-benchmark-results.md
```

Genera: JSON del informe completo (config, versiones, hashes del corpus, SHA de
codigo, metricas, gates, dictamen, FP/FN, notas de derivacion), JSONL de
predicciones (una por linea) y el resumen Markdown de `docs/50`.

Tests: `python -m pytest app/tests/test_relation_benchmark_runner.py -q`.

**Seguridad**: sin red, sin Ollama/NVIDIA reales, sin escritura, sin Neo4j.
