# Evaluador de relaciones con LLM LOCAL (modo sombra) — `relation-local-llm/v1`

Modulo: `relations/local_llm_shadow.py` (fichero plano, sin tocar `__init__`).

Evalua un candidato de relacion usando un modelo de lenguaje **LOCAL** (p. ej. un
servidor Ollama con API OpenAI-compatible) y produce una **RECOMENDACION**. Es
**exclusivamente de modo sombra**: nunca decide, nunca aprueba, nunca escribe.

## Garantias de seguridad

- **Modo sombra obligatorio.** `LocalLLMConfig(shadow=False)` lanza
  `ShadowModeRequired`. La salida es siempre una recomendacion
  (`recommend_propose` / `recommend_reject` / `recommend_human_review`); jamas se
  emite `APPROVED`/`AUTO_APPROVED` (barrera dura en `LocalRelationRecommendation`).
- **Sin endpoint por defecto → fallo cerrado.** `endpoint` es `None` por defecto.
  Si no hay endpoint explicito **ni** transporte inyectado, se lanza `ConfigError`
  **antes de abrir un solo socket**. Ningun valor por defecto apunta a
  infraestructura real.
- **Sin red en tests.** Todos los tests inyectan un transporte mock
  (`config.transport`). No se contacta a Ollama real ni a ninguna red. Hay un test
  que verifica que **no se abre ningun socket** cuando falta el endpoint.
- **Cero escrituras.** No escribe en Neo4j, ni en cache, ni en disco. Un test
  parchea `Path.write_text`/`mkdir` para demostrarlo.
- **Sin secretos en logs.** Se reutiliza `external_ai.security.assert_no_secrets`
  como guardia previa al envio; los errores se registran solo por **tipo de
  excepcion** (nunca cuerpo de respuesta, texto privado ni cabeceras
  `Authorization`). La salida guarda solo hashes y una cita de evidencia corta.
- **Limites.** `timeout`, `max_retries` (reintentos limitados), `max_prompt_chars`
  y `max_response_bytes` (respuesta demasiado grande → rechazada).
- **JSON estricto.** La respuesta se valida contra el contrato
  `relations.contracts.RelationCandidate`; se **rechaza** evidencia inexistente en
  el documento, offsets fuera de rango o incoherentes con la evidencia, campos
  ausentes y tipos de relacion (predicados) desconocidos.
- **Determinismo.** Mismo input → mismo `input_hash` y mismo `prompt_hash`
  (`external_ai.cache.sha256_text`).

## Reutilizacion (sin duplicar)

- **Cliente HTTP:** se **envuelve** `external_ai.openai_compatible.OpenAICompatibleProvider`
  (su `_post_chat` con reintentos/backoff/seguridad). No se copia logica de red.
  La via real solo se activa con `endpoint` explicito y `cache_enabled=False`.
- **Estados:** se reutilizan los estados canonicos de `external_ai.models`
  (`CONSENSUS_STATES`: `STRONG_CONSENSUS`, `PARTIAL_CONSENSUS`, `MODEL_CONFLICT`,
  `INVALID_RESPONSES`, `HUMAN_REQUIRED`). No se inventa taxonomia paralela.
- **Prompt:** se reutiliza `relations.prompts.render` / `build_system_prompt` /
  `sanitize_document` (plantillas RPG versionadas de R4).
- **Contrato:** `relations.contracts.RelationCandidate` (20 campos, `extraction_method=LLM_LOCAL`).
- **Redaccion/hash:** `external_ai.security` y `external_ai.cache.sha256_text`.

## API

```python
from relations.local_llm_shadow import (
    LocalLLMConfig, RelationEvalInput, evaluate_relation_local,
)

inp = RelationEvalInput(
    document="Bayushi Hisao juro lealtad al Clan Escorpion.",
    subject_id="Bayushi Hisao", object_id="Clan Escorpion",
    template_id="membership", subject_type="Character", object_type="Faction",
    workspace="leyenda",
    signals=[...],   # senales heuristicas de relations.signals (opcional)
)

# En tests / integracion: se inyecta un transporte mock (sin red).
cfg = LocalLLMConfig(model="ollama/llama3", transport=mi_transporte_mock)
rec = evaluate_relation_local(inp, config=cfg)
# rec.state in CONSENSUS_STATES; rec.recommendation nunca es una aprobacion.
```

`evaluate_relation_local(candidate_or_pair, *, config)` devuelve
`LocalRelationRecommendation` con: `state` (CONSENSUS_STATES), `recommendation`,
`relation_type`, `evidence_text`/`evidence_start`/`evidence_end`, `negated`,
`temporal_scope`, `epistemic_status`, `confidence`, `direction`, `provider`,
`model`, `prompt_suite`/`prompt_version`, `template_id`/`template_version`,
`input_hash`, `prompt_hash`, `latency_ms`, `validation_status` y
`validation_errors`.

El transporte inyectado tiene la firma
`transport(messages: list[dict]) -> tuple[response_json_openai_compatible, latency_ms]`.

## Mapa estado → recomendacion (nunca aprueba)

| Situacion                                   | `state`             | `recommendation`        |
|---------------------------------------------|---------------------|-------------------------|
| Valida, afirmativa, confianza ≥ 0.75        | `STRONG_CONSENSUS`  | `recommend_propose`     |
| Valida, afirmativa, confianza < 0.75        | `PARTIAL_CONSENSUS` | `recommend_propose`     |
| Valida pero negada / no-asertada            | `HUMAN_REQUIRED`    | `recommend_human_review`|
| Sin relacion extraida                       | `HUMAN_REQUIRED`    | `recommend_human_review`|
| JSON invalido / campo ausente / evidencia   | `INVALID_RESPONSES` | `recommend_human_review`|
| inventada / offsets malos / proveedor caido |                     |                         |

Incluso `STRONG_CONSENSUS` produce solo una **recomendacion**: la decision y la
escritura corresponden a un humano u otro subsistema, nunca a este modulo.

## Validacion real contra Ollama

```
OLLAMA_REAL_VALIDATION=NOT_EXECUTED
Reason: no explicit authorization
```

No se ha ejecutado ninguna llamada a Ollama real. Toda la validacion se realizo
con transporte mock inyectado, sin red.
