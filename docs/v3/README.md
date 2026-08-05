# Índice — `docs/v3/`

Documentación de la línea de desarrollo vigente del repositorio,
`knowledge_v3` (ver estado general en el [`README.md`](../../README.md) de la
raíz y detalle histórico legacy en
[`docs/S9_KNOWLEDGE_DOCUMENTACION_CONSOLIDADA.md`](../S9_KNOWLEDGE_DOCUMENTACION_CONSOLIDADA.md)).

La numeración no es continua: los huecos (13, 23, 45) corresponden a
documentos renombrados o cuyo número fue reasignado a otro bloque mientras
una rama paralela estaba abierta (ver nota de `49`). No se ha renumerado
nada para "rellenar" — los números son un identificador estable, no un
orden de lectura obligatorio.

| # | Documento | Contenido |
| --- | --- | --- |
| 00 | [00-audit-current-system.md](00-audit-current-system.md) | Auditoría previa del sistema actual (fase 5) |
| 01 | [01-contracts-v3.md](01-contracts-v3.md) | Contratos internos versionados V3 (fase 6) |
| 02 | [02-multimodal.md](02-multimodal.md) | Subsistema A: ingesta y normalización multimodal |
| 03 | [03-extractor.md](03-extractor.md) | Subsistema EXTRACTOR |
| 04 | [04-resolution.md](04-resolution.md) | Subsistema C: resolución de identidad |
| 05 | [05-local-engine.md](05-local-engine.md) | Motor local de conocimiento V3 |
| 06 | [06-temporal-ledger.md](06-temporal-ledger.md) | Ledger temporal V3 |
| 07 | [07-providers.md](07-providers.md) | Capa de proveedores V3 |
| 08 | [08-benchmarks.md](08-benchmarks.md) | Dataset gold y arnés de medición |
| 09 | [09-writer.md](09-writer.md) | Writer V3 |
| 10 | [10-heldout.md](10-heldout.md) | Split held-out (equipo independiente) |
| 11 | [11-e2e.md](11-e2e.md) | Cadena extremo a extremo |
| 12 | [12-semantic-extractor.md](12-semantic-extractor.md) | Extractor semántico episódico |
| 14 | [14-estado-y-decisiones.md](14-estado-y-decisiones.md) | Estado del programa y decisiones |
| 15 | [15-semantic-extractor-e2e-integration.md](15-semantic-extractor-e2e-integration.md) | Extractor semántico conectado a la cadena E2E |
| 16 | [16-plan-de-corpus-y-evaluacion.md](16-plan-de-corpus-y-evaluacion.md) | Plan de corpus y evaluación |
| 17 | [17-capacidad-y-observabilidad.md](17-capacidad-y-observabilidad.md) | Plan de medición de capacidad y observabilidad |
| 18 | [18-politica-de-aprobacion-de-negaciones.md](18-politica-de-aprobacion-de-negaciones.md) | Política de aprobación de negaciones |
| 19 | [19-bateria-de-negaciones.md](19-bateria-de-negaciones.md) | Batería de negaciones (split `negation`) |
| 20 | [20-bucle-humano-y-teacher-lab.md](20-bucle-humano-y-teacher-lab.md) | Bucle de revisión humana y Teacher Lab |
| 21 | [21-proposal-reconciler.md](21-proposal-reconciler.md) | `ProposalReconciler` — especificación |
| 22 | [22-encargo-equipo-externo-reconciliador.md](22-encargo-equipo-externo-reconciliador.md) | Encargo a equipo externo — `ProposalReconciler` |
| 24 | [24-encargo-externo-revision-y-multimodal.md](24-encargo-externo-revision-y-multimodal.md) | Encargo externo — interfaz de revisión, multimodalidad y writer real |
| 25 | [25-interfaz-de-revision.md](25-interfaz-de-revision.md) | Interfaz de revisión V3 |
| 26 | [26-multimodalidad-real.md](26-multimodalidad-real.md) | Multimodalidad real |
| 27 | [27-writer-contra-neo4j-real.md](27-writer-contra-neo4j-real.md) | Writer V3 contra Neo4j real |
| 28 | [28-requisitos-de-instalacion.md](28-requisitos-de-instalacion.md) | Requisitos de instalación y despliegue |
| 29 | [29-encargo-externo-transcripcion-manuscrita.md](29-encargo-externo-transcripcion-manuscrita.md) | Encargo externo — carril de transcripción manuscrita |
| 30 | [30-encargo-externo-tareas-paralelas-D-H.md](30-encargo-externo-tareas-paralelas-D-H.md) | Encargo externo — tareas paralelas D·E·F·G·H |
| 31 | [31-transcripcion-manuscrita.md](31-transcripcion-manuscrita.md) | Entrega — carril de transcripción manuscrita |
| 32 | [32-plan-consolidado-extractor-y-nucleo.md](32-plan-consolidado-extractor-y-nucleo.md) | Plan consolidado: extractor y validación del núcleo |
| 33 | [33-semantic-shadow-evaluation.md](33-semantic-shadow-evaluation.md) | Evaluación semántica en sombra |
| 34 | [34-common-factivity-policy.md](34-common-factivity-policy.md) | Política común de factualidad |
| 35 | [35-final-core-validation-results.md](35-final-core-validation-results.md) | Resultados finales de validación del núcleo |
| 36 | [36-human-review-and-glossary-candidates.md](36-human-review-and-glossary-candidates.md) | Revisión humana V3 y candidatos de glosario |
| 37 | [37-pr116-technical-closure.md](37-pr116-technical-closure.md) | PR #116 — cierre técnico |
| 38 | [38-pr117-phase1-neo4j-cessation.md](38-pr117-phase1-neo4j-cessation.md) | PR #117 — fase 1: Neo4j e idempotencia de cesaciones |
| 39 | [39-carril-ocr.md](39-carril-ocr.md) | Puerta 4, bloque B1: carril OCR conectado a la extracción V3 |
| 40 | [40-gate4-b3-nvidia-shadow.md](40-gate4-b3-nvidia-shadow.md) | Puerta 4, bloque B3: carril semántico NVIDIA en modo sombra |
| 41 | [41-gate4-b4-morphology.md](41-gate4-b4-morphology.md) | Puerta 4, bloque B4: análisis morfológico de verbos de reporte |
| 42 | [42-gate4-cierre-programa.md](42-gate4-cierre-programa.md) | Cierre del programa "Puerta 4: cobertura del extractor" (B0→B5) — veredicto **PARCIAL** |
| 43 | [43-gate6-b0-harness.md](43-gate6-b0-harness.md) | Puerta 6, bloque B0: arnés de medición de factividad composicional |
| 44 | [44-gate6-b1-operators.md](44-gate6-b1-operators.md) | Puerta 6, bloque B1: operador de discurso reportado por tercero |
| 46 | [46-gate6-cierre-programa.md](46-gate6-cierre-programa.md) | Cierre del programa Puerta 6 (B0→B2, con rework de B2) — veredicto **CONFORME CON RESERVAS** |
| 47 | [47-acuerdo-det-nvidia.md](47-acuerdo-det-nvidia.md) | Medición en sombra: precisión del subconjunto-acuerdo determinista ∧ NVIDIA |
| 48 | [48-acuerdo-eval2.md](48-acuerdo-eval2.md) | ACUERDO-2: corpus de evaluación ampliado y re-medición del acuerdo — piloto controlado ratificado |
| 49 | [49-multipartida-diseno.md](49-multipartida-diseno.md) | Diseño: separación de partidas por ámbitos (multi-partida) — **en obra, no tocar sin coordinar** |

Otros documentos no numerados en este directorio:

- [`S9_KNOWLEDGE_V3_DOSIER_REDISENO_INTEGRAL.md`](S9_KNOWLEDGE_V3_DOSIER_REDISENO_INTEGRAL.md)
  — dosier integral de rediseño V3.
- [`S9_KNOWLEDGE_V3_PROMPT_MULTIAGENTE (1).md`](<S9_KNOWLEDGE_V3_PROMPT_MULTIAGENTE (1).md>)
  — prompt de ejecución multiagente del programa V3.
- [`measurements/`](measurements/) — artefactos de medición asociados a los
  documentos numerados anteriores.

## Estado de programas (2026-08-05)

- **Puerta 4 — cobertura del extractor**: CERRADA, veredicto **PARCIAL**
  (docs/v3/42). Cobertura E2E en desarrollo 0.607 (≥0.60, conforme); recall
  de auto-aprobación SIMPLE 0.10 (umbral ≥0.70, no conforme); invariantes de
  precisión intactos. Carril OCR validado con Tesseract 5.5.0 real en VM105
  (docs/v3/39); Tesseract es un requisito de instalación adicional
  (docs/v3/28).
- **Puerta 6 — factividad composicional**: CERRADA, veredicto **CONFORME CON
  RESERVAS**, ratificado por el operador el 2026-08-05 (docs/v3/46). El
  operador de discurso reportado quedó conectado al extractor real tras el
  rework de B2; el invariante fail-closed se mide en dos capas. El criterio
  de "acuerdo determinista∧NVIDIA" para esta puerta fue abandonado
  (Postura A adoptada por el operador).
- **Acuerdo determinista∧NVIDIA**: medido en dos rondas (docs/v3/47, 48). El
  acuerdo activo se sostiene en 27/27 (medición 1) y 1.000 sobre el corpus
  ampliado (medición 2 / ACUERDO-2). El operador ratificó un **piloto
  controlado**, gateado al despliegue de V3 y a la primera ingesta
  autorizada; la revisión humana no se reduce durante el piloto.
- **Programa multi-partida**: EN CURSO. Diseño (docs/v3/49, PR #137) y bloque
  M0 (contratos: `partida_id` en la tubería, PR #138, `main` `ccf0fe4`)
  mergeados. M1 (mapeo de ingesta Nextcloud→ámbito) bloqueado a que
  Nextcloud vuelva y se pueda leer la plantilla de bóvedas. M2 (resolutor,
  `resolution/cascade.py`) en obra en una rama separada.
- **Dependencias**: aiohttp actualizado a 3.14.3 por CVE-2026-59881/69243/69244
  (PR #128); httpx, argon2-cffi, fastapi, jinja2 y pytest actualizados vía
  Dependabot (PRs #119-#123).
