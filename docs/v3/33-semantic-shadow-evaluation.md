# Evaluación semántica en sombra

Fecha: 2026-07-30 · Rama: `integration/v3-final-core-validation`

## Decisión efectiva y decisión sombra

La **decisión efectiva** es la única que alimenta el planner y, por tanto, la
única que puede llegar al writer. La **decisión sombra** es una contrafactual de
medida: vuelve a decidir sobre una copia del lote ignorando exclusivamente el
finding `EXTRACTOR_REQUESTED_REVIEW`, reaplica las contradicciones de lote y
registra qué habría ocurrido. No sustituye ni modifica la decisión efectiva.

La sombra sólo es elegible para claims producidos por `extract.semantic`, no
abstenidos, marcados `review_required` y con procedencia de proveedor válida.
No ignora ningún otro finding. Un claim que siga teniendo razones de revisión o
rechazo después de retirar esa única finding continúa cerrado.

## Por qué la sombra no puede escribir

La separación no depende de una convención:

1. `engine.py` hace `deepcopy` de las decisiones antes de la segunda pasada y
   `shadow.py` usa además `dataclasses.replace`; las decisiones efectivas no se
   reutilizan como buffer de trabajo.
2. `build_plan(..., decision_source="effective")` rechaza cualquier
   `decision_source` distinto de `effective`.
3. `ShadowDecisionRecord` es `frozen` y sólo transporta escalares y tuplas. Sus
   `operation_kinds` son nombres inertes, no contratos ni payloads aplicables.

Así, la sombra puede decir `would_emit_operations=true`, pero no contiene una
operación ejecutable ni existe una ruta que la convierta en plan.

## Configuración

`EngineConfig.semantic_shadow_evaluation` está **OFF** por defecto
(`False`). Debe activarse explícitamente para medir. Las puertas 4 y 6
deterministas la activaron, pero produjeron **0 registros** porque no había
claims del carril semántico elegibles. Esto prueba la frontera estructural de
no escritura, no la utilidad de la comparación efectiva/sombra.

## Puerta 5: autoridad local y proveedores reales

Los cinco gates duros resultaron **CONFORME**:

| Gate | Observado |
|---|---:|
| Claims sin evidencia literal | 0 |
| Predicados fuera de ontología | 0 |
| Decisiones efectivas alteradas por sombra | 0 |
| Operaciones sombra aplicables | 0 |
| Escrituras decididas por proveedor | 0 |

La evidencia real de proveedor fue:

- **NVIDIA NIM**, `meta/llama-3.3-70b-instruct`: 24 frases, 48 llamadas,
  mediana 50 107 ms por frase, mínimo 1 336 ms, máximo 180 296 ms, pared
  total 1 372 s y **0 errores**.
- **Ollama**, `qwen2.5:7b` en CPU: de 4 episodios, **2 agotaron el timeout de
  600 s**. Ambos se tradujeron a `PROVIDER_UNAVAILABLE`, con 0 claims activos,
  abstención anclada, 0 escrituras y continuación del lote. La mediana
  observada del fallo fue 600 199 ms.

El fallo de Ollama no fue inducido ni simulado: ocurrió durante la medida. El
sistema aguantó, pero la ausencia de escritura ante el fallo no convierte al
proveedor en operativo para ingesta.

## No determinismo medido

El carril de proveedor cambió **7 de 24 casos** entre dos corridas con entrada
idéntica. Sólo 2 cambios coincidieron con el parche de cues; los otros 5 forman
un suelo de ruido de 20,8 %, superior al efecto medido de 8,3 %. Una única
comparación antes/después no permite atribuir el cambio al código.

Fuentes: `artifacts/v3-final-validation/gate5-authority.md`,
`gate6-factivity-matrix.*`, `gate6-findings.md`, `perf-notes.md` y
`knowledge_v3/engine/{shadow,engine,planner,config}.py`.
