# Mapa de integración — OLA 2B Lote 3 (R8 / B1 / B2 / QF)

Base real: `origin/main = 9458eb3`. RC6 candidata intacta en `release/rc6-candidate = 15ae1d4`.

Este documento fija las **interfaces reales ya integradas** que R8 debe reutilizar
sin duplicar. Todas viven en `data-engine/app/relations/` y reutilizan
`data-engine/app/external_ai/` para los estados de consenso. Import de cualquiera
de estos módulos **no** carga modelos, **no** abre red y **no** escribe.

## Contrato central — `relations.contracts`

| Símbolo | Tipo | Notas |
|---------|------|-------|
| `RelationCandidate` | dataclass (20 campos de datos) | `subject_id, subject_type, predicate, object_id, object_type, direction, confidence, evidence_text, evidence_start, evidence_end, source_id, source_page, source_segment, extraction_method, model, negated, temporal_scope, epistemic_status, workspace, validation_flags`. `.validate()` lanza `RelationContractError`. **Congelado (OLA 2A/2B). No modificar.** |
| `Direction`, `ExtractionMethod`, `EpistemicStatus` | Enum(str) | Enums canónicos. |
| `CANONICAL_CONSENSUS_STATES` | tuple | Re-exporta `external_ai.models.CONSENSUS_STATES`. |
| `normalize_predicate(raw) -> str` | fn | MAYÚSCULAS con guion_bajo. |
| `REFLEXIVE_PREDICATES` | tuple | Predicados que admiten subject==object. |

## Etapas del pipeline (entradas → salidas reales)

| Etapa | Módulo | API pública real | Entrada | Salida |
|-------|--------|------------------|---------|--------|
| Pares (R1) | `relations.pairs` | `generate_pairs(entities: Iterable[dict], segment: dict, *, config: PairConfig=None) -> PairGenerationResult` | entidades (dict) + segmento (`{text, workspace, ...}`) | `PairGenerationResult(pairs: tuple[CandidatePair], truncated, total_before_truncation, warnings)`. `stable_pair_id(workspace, subject_id, object_id, segment_id)`. |
| Señales (R2) | `relations.signals` | `compute_all_signals(ctx: SignalContext) -> list[Signal]` | `SignalContext(segment, subject_start, subject_end, object_start, object_end, subject_type?, object_type?, occurrences=())` (valida offsets en `__post_init__`) | lista de `Signal` (evidencia, NO decisión). `SIGNALS_VERSION`. |
| Sintaxis (R3) | `relations.syntax` | `get_analyzer(provider="heuristic") -> SyntaxAnalyzer`; `analyze(text, *, provider="heuristic", language=None) -> SyntaxAnalysis`; `safe_analyze(analyzer, text, *, language=None)` (aísla fallos → `degraded`) | texto | `SyntaxAnalysis(text, language, provider, version, sentences, degraded, quality, notes)`. `HeuristicSyntaxAnalyzer` es stdlib. `ExternalModelSyntaxAnalyzer` (spacy/stanza) **NO ejecutar** — sin modelos. |
| Prompts (R4) | `relations.prompts` | `templates.py` (versionadas); `TEMPLATE_VERSION`, `DEFAULT_SUITE` | par + señales + sintaxis | prompt renderizado (texto). |
| LLM local sombra (R5) | `relations.local_llm_shadow` | `evaluate_relation_local(candidate_or_pair, *, config: LocalLLMConfig) -> LocalRelationRecommendation` | `RelationEvalInput(document, subject_id, object_id, template_id, ...)` | `LocalRelationRecommendation` (recomendación, nunca decisión). `LocalLLMConfig.endpoint=None` ⇒ **falla cerrado** sin socket; `transport` inyectable en tests. `RECOMMEND_{PROPOSE,REJECT,HUMAN}`. |
| IA externa sombra (R6) | `relations.external_ai_shadow` | `evaluate_relation_external(candidate_or_pair, *, config: RelationExternalConfig) -> list[RelationExternalEvaluation]`; `summarize(results) -> dict` | `RelationCandidate`(s) | lista de `RelationExternalEvaluation`. `shadow_mode=True` obligatorio; `provider` inyectable (mock `_post_chat`); jamás red/secretos/AUTO_APPROVED. |
| Consenso (R7) | `relations.consensus_adapter` | `compute_relation_consensus(candidate, *, signals=None, syntax=None, local=None, external=None) -> RelationConsensus` | candidato + fuentes opcionales | `RelationConsensus(state ∈ CONSENSUS_STATES, recommendation ∈ {propose,reject,human}, ...)`. Independiente del orden; candidato **inmutable**; ausente ≠ rechazo. |
| Observabilidad (P2) | `relations.observability` | `RelationEvent`, `RelationTrace(execution_id)`, `time_component()`, `hash_value()`, `redact()`, `find_secrets()` | eventos | traza serializable en memoria (sin backend, sin red, sin disco). Redacción de secretos. `ComponentResult`. |

## Reglas para R8

1. **Reutilizar exclusivamente** las APIs anteriores. Prohibido reimplementar
   pares/señales/sintaxis/consenso o crear un segundo `RelationCandidate`.
2. Entrada del pipeline: representación controlada `{document, workspace, segments[], entities[], config, providers?}`. Si ya existe un tipo de segmento/entidad compatible (dict de pairs/signals), **no** introducir un segundo.
3. Proveedores por defecto `local_llm_enabled=false`, `external_ai_enabled=false`.
   Deshabilitados ⇒ pipeline funciona con heurísticas+sintaxis+consenso; registra
   proveedor NOT_EXECUTED; nunca abre red. Habilitados en tests ⇒ sólo
   `transport`/`provider` inyectados (mock/fixture), nunca socket/endpoint/API key real.
4. **Dry-run absoluto**: sin modo write, sin `apply=true`, sin persistencia, sin
   import de drivers Neo4j en esta ruta, sin repositorios productivos.
5. **Determinismo**: IDs reproducibles (ejecución/documento/segmento/par/candidato/
   resultado) por hash de contenido, no timestamps. Los timestamps de observabilidad
   no entran en el hash funcional. Salida ordenada; mismo input ⇒ mismos hashes.
6. **Workspace**: obligatorio; vacío ⇒ error; sin mezcla entre candidatos/caché/resumen.
7. **Límites** (config): segmentos/doc, entidades/segmento, pares/segmento, tamaño de
   texto/prompt/respuesta, tiempo/candidato, errores/lote, acumulación de resultados.
8. **Fallos**: fallo de segmento no invalida el resto; proveedor ausente ≠ rechazo;
   resultado parcial conserva señales; errores auditables; nunca silenciar excepciones.

## Áreas compartidas (solo Organizador, PR separado)

`pytest.ini`, `pyproject.toml`, `*/requirements*`, `.github/workflows/**`,
`project-status.yaml`, `viewer/app/main.py`, config/migraciones globales.

## Propiedad Lote 3

| Agente | Rama | Ficheros propios | Prohibido |
|--------|------|------------------|-----------|
| R8 pipeline | `feat/relation-pipeline-v1` | `relations/pipeline.py` (+ `relations/cli.py` opc.) + `test_relation_pipeline.py` | tocar otros submódulos; contratos congelados; Neo4j; áreas compartidas |
| B1 corpus | `test/relation-benchmark-corpus-v1` | `data-engine/app/tests/data/relation_benchmark/**` + test de integridad | producto; corpus privado |
| B2 runner | `test/relation-benchmark-runner-v1` | `relations/benchmark/**` + `docs/41,42` (o siguientes libres) | copiar lógica de R8; docs 33-37 |
| QF QA final | `test/wave2b-final-product-v1` | `tests/wave2b/**` (nuevos ficheros) + matriz | producto (reproduce, no corrige) |
| D1 runtime docs | `docs/relation-pipeline-runtime-v1` | `docs/**` runtime | producto |
| D2 cierre | `docs/wave2b-closeout-v1` | tablero/riesgos/cierre | sobrescribir histórico |
