# Evaluador de relaciones con IA externa (NVIDIA NIM) - MODO SOMBRA

Modulo: `relations/external_ai_shadow.py`
Estado: Fase A (revision en modo sombra). Sin escritura, sin red en tests, sin Neo4j.

## Que hace

`evaluate_relation_external(candidate_or_pair, *, config)` toma una relacion
candidata interna (`relation-candidate/internal-v1`) -o una lista de ellas- y le
pide a un modelo externo compatible con la API OpenAI (NVIDIA NIM) que **juzgue si
el documento sustenta la relacion propuesta**. Devuelve una lista de
`RelationExternalEvaluation`, una por candidato.

El resultado es **siempre una recomendacion sombra** (`shadow_recommendation`):
nunca una decision productiva. **NO existe el estado `AUTO_APPROVED`.** Toda
escritura sigue exigiendo revision humana posterior.

## Reutilizacion de `external_ai/**` (NO se duplica nada)

Este modulo es un **envoltorio fino**. Reutiliza, importandolo, todo el
subsistema de IA externa ya existente:

| Necesidad | Se reutiliza de `external_ai` |
|---|---|
| Cliente/transporte HTTP, reintentos con backoff, timeout, rate-limit, concurrencia | `nvidia_nim.NvidiaNimProvider` / `openai_compatible.OpenAICompatibleProvider._post_chat` |
| Endpoint explicito y API key por secreto (nunca guardada) | `registry.get_provider`, `registry.get_api_key`, `registry.nvidia_config` |
| Redaccion / guarda de secretos antes de enviar | `security.assert_no_secrets` |
| Extraccion robusta de JSON de la respuesta cruda | `response_parser.extract_json` |
| Estados canonicos de consenso | `models.CONSENSUS_STATES` (`STRONG_CONSENSUS`, `PARTIAL_CONSENSUS`, `MODEL_CONFLICT`, `INVALID_RESPONSES`, `HUMAN_REQUIRED`) |
| Guarda de modo sombra | `require_shadow` |
| Contrato y validacion de la relacion, prompt de sistema, sanitizacion/anti-inyeccion | `relations.contracts`, `relations.prompts` |

No se reescriben clientes, modelos, estados, consenso, validadores, redaccion ni
errores: se importan de su fuente canonica.

## Estados y recomendaciones

`state` es uno de `external_ai.models.CONSENSUS_STATES`. Mapeo del verdicto del
modelo (`confirm | refine | reject | uncertain`) a estado:

- **STRONG_CONSENSUS** (`confirm`): el modelo confirma con evidencia literal
  valida, mismo predicado y tipos compatibles. Recomendacion sombra: `confirm`.
- **PARTIAL_CONSENSUS** (`refine`, o `confirm` con matices): apoya la relacion
  pero sugiere ajustes de predicado/tipos. Recomendacion: `refine`.
- **MODEL_CONFLICT** (`reject`, o inversion de `negated`): el modelo contradice
  la propuesta interna. Recomendacion: `reject` o `human`.
- **HUMAN_REQUIRED** (`uncertain`): el modelo no se compromete. Recomendacion: `human`.
- **INVALID_RESPONSES**: JSON malformado, evidencia inexistente, offsets
  invalidos, tipo incompatible, verdict fuera de catalogo, o error de proveedor
  (timeout / 429 / 500 / auth). Recomendacion: `human`.

`shadow_recommendation` in `{confirm, refine, reject, human}`. **Nunca `AUTO_APPROVED`**
(hay un invariante que lo prohibe en `RelationExternalEvaluation.__post_init__`).

## Seguridad

- **Modo sombra obligatorio**: `require_shadow(config.shadow_mode)` aborta si no es True.
- **Sin escritura**: no importa ni usa ningun cliente Neo4j; no activa ingesta.
- **Endpoint explicito**: el base_url lo resuelve `registry` desde el entorno.
- **API key solo por secreto**: se obtiene por demanda del entorno; nunca se
  guarda como atributo ni se serializa. `config.to_dict()` no la expone.
- **Ninguna key en logs**: los errores se registran solo por `type(exc).__name__`.
- **Guarda de secretos**: `assert_no_secrets(messages)` bloquea el envio si el
  payload contiene credenciales (`SecretLeakError`), antes de tocar la red.
- **Validacion estricta por candidato**: JSON estricto; rechaza evidencia que no
  sea subcadena literal del segmento y offsets que no casen o esten fuera de rango.
- **Fallo aislado por candidato**: una excepcion en un candidato no aborta el
  lote; se registra como `INVALID_RESPONSES` con la causa (sin secretos).
- **Control de volumen**: `RelationVolumeError` si se superan `max_candidates`.

## Uso (produccion, NO ejecutado aqui)

```python
from pathlib import Path
from relations.external_ai_shadow import evaluate_relation_external, RelationExternalConfig

cfg = RelationExternalConfig(
    model="meta/llama-3.1-70b-instruct",  # segun S9K_NVIDIA_REVIEW_MODELS
    provider_name="nvidia",
    repo_root=Path("/ruta/al/repo"),
    shadow_mode=True,
)
# Requiere en el entorno: S9K_NVIDIA_ENABLED=true, S9K_NVIDIA_API_KEY=<secreto>,
# S9K_NVIDIA_BASE_URL=<endpoint explicito>.
resultados = evaluate_relation_external(candidato_relacion, config=cfg)
```

En tests SIEMPRE se inyecta `config.provider` con un doble sintetico (`_post_chat`
mockeado). NO hay red, NO hay claves reales (las fixtures usan claves falsas
evidentes tipo `nvapi-FAKEKEY...`).

## Validacion real

```
NVIDIA_REAL_VALIDATION=NOT_EXECUTED
Reason: no explicit authorization
```

No se ha realizado ninguna llamada real a NVIDIA. La validacion contra el
endpoint real queda pendiente de autorizacion explicita del operador y de una
API key provista por secreto.
