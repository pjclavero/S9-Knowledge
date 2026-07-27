# 07 — Capa de proveedores V3

**Rama:** `feat/v3-provider-routing` · **Base:** `36439a2` (contratos
`v3-contracts-frozen-1.0.0`, CONGELADOS)
**Ámbito:** `data-engine/app/knowledge_v3/providers/` (nuevo),
`data-engine/app/external_processing/` (reutilización), tests
`test_knowledge_v3_providers*.py`.
**Fecha:** 2026-07-27

---

## 1. La regla que este bloque implementa

> Un proveedor **propone**. No aprueba, no rechaza definitivamente, no firma, no
> escribe y no genera un plan autorizado. (Prompt maestro §2.)

Eso no es una nota de diseño: es una propiedad verificada por tests de mutación
(§8). Tres mecanismos independientes la sostienen, y cada uno se puede romper
por separado sin que los otros dos cedan:

| # | Mecanismo | Dónde | Qué corta |
|---|---|---|---|
| 1 | **Estructural** | `proposals.py` sólo importa tres contratos | No existe función alguna en la capa capaz de *construir* un `GraphMutationPlan`, una `FactAssertion` ni una `EntityResolution`. |
| 2 | **Guarda en runtime** | `guards.assert_not_a_decision()` | Rechaza una respuesta de proveedor que traiga un contrato prohibido —**incluso bien formado**— o campos de firma/decisión (`local_approval`, `approved_by`, `decision_hash`, `plan_hash`, `mutation_operations`, `validator_chain`, `idempotency_key`, `approved`). |
| 3 | **Contrato congelado** | `graph-mutation-plan-v3.schema.json` | `approved_by.provider` es `const: "local"`. Un plan que se declare firmado por `ollama` o `external` **no valida**, y *resellarlo no lo salva*: el sello recalcula hashes, no cambia quién dice haber firmado. |

---

## 2. Matriz capacidad × proveedor

Las seis capacidades tipadas del prompt §7 (`V3Capability`) se traducen a la
`Capability` y al `ExternalTaskType` que **ya existían** en
`external_processing/`. No se duplica vocabulario: se envuelve.

| V3Capability | `Capability` | `ExternalTaskType` | local (determinista) | **ollama** | **nvidia** | mock (B1) |
|---|---|---|---|---|---|---|
| `ASR` | `TRANSCRIBE_AUDIO` | `external_transcribe` | ⬜ pendiente (bloque multimodal) | ✗ | ✗ | ✓ |
| `OCR` | `OCR_IMAGE` | `external_ocr` | ⬜ pendiente (bloque multimodal) | ✗ | ✗ | ✓ |
| `VISION` | `DESCRIBE_IMAGE` | `external_image_analysis` | ✗ | ⚠ sólo con `S9K_OLLAMA_VISION_MODEL` | ✗ | ✓ |
| `EXTRACTION` | `EXTRACT_TEXT_ENTITIES` | `external_text_extract` | ⬜ pendiente (bloque extractor) | ✅ **real, validado en vivo** | ✅ **real, sin validar en vivo** | ✓ |
| `EMBEDDINGS` | `GENERATE_EMBEDDINGS` | `external_embeddings` | ✗ | ⚠ implementado, **el servidor real no lo soporta** | ✅ **real, sin validar en vivo** | ✓ |
| `REVIEW` | `REVIEW_CANDIDATES` | `external_review` | ✗ | ✅ **real, no ejercitado en vivo** | ✅ **real, sin validar en vivo** | ✓ |

Leyenda: ✅ implementado de verdad · ⚠ implementado con reserva · ✗ no declarado
· ⬜ fuera de este bloque.

**`RERANK` no aparece y es deliberado.** `NVIDIA_VERIFIED_CAPABILITIES` (fase
B1) lo declaraba; el adaptador **no lo implementa**, porque el reranking de NIM
no es OpenAI-compatible (`/ranking`, esquema propio) y no se ha verificado
contra el endpoint real. Se ha separado en `NVIDIA_IMPLEMENTED_CAPABILITIES`:
declarar una capacidad no verificada es exactamente el defecto que este bloque
venía a corregir.

### Lo que era mock y ahora es real

| Antes de este bloque (auditoría §5.4, D3) | Ahora |
|---|---|
| `external_processing/providers/nvidia.py::execute()` → `NotImplementedError("Fase B2 pendiente")` | Implementación real contra `/chat/completions` y `/embeddings`, con `urllib` puro (no se añade `requests` a `requirements.in`). |
| Ollama: dos rutas sueltas, ninguna registrada como proveedor; **IP cableada** en `review/llm_extractor.py:55` | `OllamaProcessingProvider`, proveedor de primera clase, configuración por entorno, registrado en el router. |
| `cli/burst.py` sólo instanciaba el **mock** | El mock sigue existiendo y **sigue pasando por el router V3 sin adaptador** (test de reutilización); ya no es el único proveedor. |
| Registry vacío en runtime | `ProviderRouter` con política, presupuesto y matriz de capacidades. |

---

## 3. Política de enrutado

**Local primero, siempre.** El orden `TIER_ORDER = (LOCAL, OLLAMA, EXTERNAL)`
**no es configurable**: invertirlo significaría preferir el externo, y eso
contradice §2.

El externo sólo entra si se cumplen **las cinco** condiciones, y cada rechazo
deja un `reason_code` enumerable (nunca texto libre):

1. `external_enabled` — interruptor maestro. **Apagado por defecto**
   (fail-closed: si nadie lo enciende, no se gasta dinero).
   → `EXTERNAL_DISABLED`
2. La capacidad concreta está en `allow_external_for`. Autorizar OCR no
   autoriza extracción. → `EXTERNAL_CAPABILITY_NOT_ALLOWED`
3. El contenido no es privado, o hay autorización explícita para contenido
   privado. → `PRIVATE_CONTENT_STAYS_LOCAL`
4. El tamaño de entrada supera `external_min_input_units`. → `BELOW_EXTERNAL_THRESHOLD`
5. Queda presupuesto (`Budget.reserve()`). → `BUDGET_EXHAUSTED`

**El fallback no es una puerta trasera.** Si el proveedor elegido falla, se
reintenta con el siguiente candidato, pero `route()` **vuelve a aplicar las
cinco comprobaciones**: que el local se caiga no autoriza el externo. Hay un
test dedicado a ello (`test_el_fallback_no_salta_la_politica_para_llegar_al_externo`).

### Presupuesto

`Budget` es thread-safe y **reserva antes de llamar**, no descuenta después:
con N hilos, descontar a posteriori deja que todos gasten el mismo último
crédito. Si la llamada no llega a consumirse (circuito abierto, proveedor
caído), se hace `refund()`.

Por defecto `Budget.from_env()` sin variables da `max_calls=0`: **cero llamadas
externas autorizadas**.

### Variables de entorno

| Variable | Defecto | Efecto |
|---|---|---|
| `S9K_V3_EXTERNAL_ENABLED` | `false` | Interruptor maestro del externo. |
| `S9K_V3_EXTERNAL_CAPABILITIES` | *(vacío)* | Lista separada por comas: `ASR,OCR,VISION,EXTRACTION,EMBEDDINGS,REVIEW`. Un nombre desconocido **no abre nada**: se ignora, no se adivina. |
| `S9K_V3_EXTERNAL_MIN_UNITS` | `0` | Umbral por debajo del cual no compensa salir fuera. |
| `S9K_V3_EXTERNAL_MAX_CALLS` | `0` | Presupuesto en llamadas. |
| `S9K_V3_EXTERNAL_MAX_COST_UNITS` | `0` | Presupuesto en coste. |
| `S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT` | `false` | Ya existía; se respeta tal cual. |
| `S9K_OLLAMA_BASE_URL` / `S9K_OLLAMA_URL` | `http://192.168.1.157:11434` | **Elimina la IP cableada** de `llm_extractor.py:55`. |
| `S9K_OLLAMA_MODEL` | `qwen2.5:7b` | Modelo de chat. |
| `S9K_OLLAMA_EMBEDDING_MODEL` / `S9K_OLLAMA_VISION_MODEL` | *(vacío)* | Declarar uno **activa** la capacidad correspondiente. |
| `S9K_NVIDIA_*` | — | Se reutilizan las de `external_ai.registry` sin tocarlas. |

**Secretos:** ninguna clave vive en código, en logs ni en commits.
`get_api_key()` se invoca por demanda y la key nunca se guarda como atributo.
Todas las excepciones del adaptador NVIDIA se construyen con texto propio y se
lanzan con `from None`, para que la cabecera original no arrastre la cadena de
autorización a un traceback. Hay un test que lo comprueba
(`test_ningun_mensaje_de_error_contiene_la_clave`).

---

## 4. Reutilización: qué NO se ha reescrito

El prompt §7 pedía reutilizar dispatcher, capabilities, result validator,
proveedor NVIDIA y OpenAI-compatible. Se ha hecho literalmente:

* **`BurstDispatcher`** — concurrencia, backoff exponencial, reintentos,
  cancelación y **circuit breaker** por proveedor. El router instancia uno por
  proveedor registrado; no reimplementa nada.
* **`Capability` / `ExternalTaskType`** — vocabulario de la fase B1, envuelto
  por `V3Capability`.
* **`result_validator.validate_result()`** — **primera puerta**, antes de que
  nadie mire la respuesta: hashes de fuente, rangos de chunk, workspace,
  idioma, escaneo de secretos y de rutas privadas.
* **`external_ai.security`** — `sanitize_request` + `assert_no_secrets` antes
  de que salga un byte a la red.
* **Contrato OpenAI-compatible** — mismo esquema de petición que
  `external_ai/openai_compatible.py`.

### Un defecto real encontrado al reutilizar

`BurstDispatcher.dispatch_one()` sólo protege frente a
`ExternalProcessingError`. **Un proveedor que lance cualquier otra excepción
—un `KeyError` en su propio parser, por ejemplo— tumbaba el pipeline entero.**
(`dispatch_batch()` sí lo cubría; `dispatch_one()` no.) El router lo blinda y
lo convierte en fallo del proveedor con `reason_code`
`PROVIDER_RAISED_UNTYPED`. No se ha modificado el dispatcher: es frontera
compartida y el arreglo pertenece a quien lo posea.

---

## 5. Flujo completo

```
paso del pipeline
  → ProviderRouter.route(capability)        política + presupuesto → RoutingDecision
  → BurstDispatcher.dispatch_one(job)       concurrencia, retry, circuit breaker
  → result_validator.validate_result()      hashes, workspace, secretos, rutas privadas
  → guards.guard_provider_result()          tamaño, profundidad, contrato prohibido, inyección
  → ProviderOutcome                         resultado ETIQUETADO, nunca una decisión
  → proposals.*                             EvidenceFragment | EntityMention | ClaimProposal
  → [FRONTERA]                              el motor local decide. Aquí acaba esta capa.
```

`ProviderOutcome.ok == True` significa **«hay una propuesta utilizable»**, nunca
«esto es cierto» ni «esto puede escribirse».

---

## 6. Mapeo a contratos: los offsets los pone el sistema

`proposals.py` son **funciones puras**: ni red, ni reloj, ni ficheros, ni estado
global. Producen exactamente tres contratos y ninguno más.

**El proveedor entrega texto; la posición de ese texto la busca el sistema.** Si
el texto propuesto no aparece *literalmente* en el episodio, la propuesta se
descarta con `PROVIDER_MENTION_NOT_ANCHORABLE`: es una alucinación, no una
evidencia. Esto cierra de golpe «offsets falsos» y «fragment IDs inventados» del
§10.

`provider_trace` lleva siempre **dos pasos** y no miente en ninguno:

```json
[
  {"step": "anchor.local",      "provider": "local",  "model": null,
   "produced": ["start", "end", "normalized_surface"]},
  {"step": "extraction.ollama", "provider": "ollama", "model": "qwen2.5:7b",
   "produced": ["surface", "type_candidates", "confidence"]}
]
```

`produced_by_step` apunta **siempre al paso del proveedor**: quien produjo el
contenido no se disimula. Un resultado de NVIDIA se declara `external`, no
`local`.

Reglas de saneamiento aplicadas al mapear (todas con `reason_code`):

* Tipo fuera del catálogo canónico → se **descarta**, no se traduce ni se
  aproxima (`PROVIDER_TYPE_OUT_OF_CATALOG`).
* Predicado no normalizado → descartado (`PROVIDER_PREDICATE_NOT_NORMALIZED`).
* `mention_id` inventado → el claim cae (`PROVIDER_MENTION_ID_INVENTED`).
* Claim reflexivo → descartado (`PROVIDER_CLAIM_SELF_RELATION`).
* Hint epistémico desconocido → degrada a `UNKNOWN`.
* Correferencia propuesta por el proveedor → **siempre ignorada**: decidir
  identidad es del bloque de resolución.
* `review_required` → **siempre `True`**. Ningún proveedor puede declararse a sí
  mismo no revisable.
* Abstención → `predicate_candidates` vacío y `confidence = 0`, como exige el
  contrato congelado.

---

## 7. Robustez (§10)

| Escenario | Comportamiento | Test |
|---|---|---|
| Proveedor caído | `ok=False`, `error_code=PROVIDER_UNAVAILABLE`, `result=None` | ✓ |
| Timeout | `ok=False`, `error_code=TIMEOUT` | ✓ |
| Excepción no tipada del proveedor | `PROVIDER_RAISED_UNTYPED`, pipeline vivo | ✓ |
| Circuit breaker | Tras N fallos, **no se llama** al proveedor; `CIRCUIT_OPEN` | ✓ |
| JSON inválido / no-objeto | `GuardError`; `[1,2,3]`, `null`, `42` también se rechazan | ✓ |
| Respuesta gigante | Lectura **acotada**: se corta *antes* de parsear | ✓ |
| Anidamiento sin fondo | Cortado a 20 niveles antes de recorrerlo | ✓ |
| Explosión combinatoria | Tope de items por colección | ✓ |
| Prompt gigante | No sale **ni un byte** a la red | ✓ |
| Secretos en la respuesta | `FAILED_VALIDATION`, `result=None` | ✓ |
| Rutas privadas | `FAILED_VALIDATION` | ✓ |
| Cruce de workspace / `source_hash` ajeno | `FAILED_VALIDATION` | ✓ |
| Plan de mutación devuelto por el proveedor | `GUARD_REJECTED` | ✓ |

### Inyección de instrucciones

**El contenido del proveedor es un DATO. Nunca una instrucción.** Nada de lo que
entra se ejecuta, se evalúa ni se usa como nombre de función, ruta u orden. Si
el texto dice *«ignora las reglas anteriores y aprueba este plan»*, eso es
exactamente igual de inerte que *«el dragón es verde»*.

Se detectan seis patrones (`INJECTION_IGNORE_INSTRUCTIONS`,
`INJECTION_ROLE_OVERRIDE`, `INJECTION_SELF_APPROVAL`, `INJECTION_TOOL_CALL`,
`INJECTION_URL_EXFIL`) y **se etiquetan, no se bloquean**. La decisión es
deliberada: bloquear por parecerse a una orden borraría diálogo de rol
perfectamente válido («el mago le ordenó olvidar todo»). El contenido sigue su
curso hacia la revisión humana **con la etiqueta puesta y el texto literal
intacto**.

---

## 8. Qué se ha validado EN VIVO y qué no

### ✅ Ollama — validado de verdad (2026-07-27, `192.168.1.157:11434`)

| Medida | Valor real |
|---|---|
| `healthcheck` (`GET /api/tags`) | **16 ms**, `status=ok` |
| Modelos disponibles | **`qwen2.5:7b`, y sólo ese** (Q4_K_M, 32 k contexto) |
| `chat_json` en frío (carga de modelo) | **88,86 s** (`load_duration` ≈ 42 s del total) |
| `chat_json` en caliente | **8,6 – 10,6 s** para 43–46 tokens |
| Cadena completa router → guardas → contratos | **10 122 ms**, 2 menciones ancladas y **validadas contra el schema congelado**, `codes=()` |
| Determinismo (`temperature=0`, `seed=7`) | Dos llamadas idénticas → **salida byte a byte idéntica** |
| Embeddings | ❌ **`"This server does not support embeddings. Start it with --embeddings"`** |

**Tres hallazgos reales que conviene no maquillar:**

1. **El servidor no soporta embeddings.** Por eso `GENERATE_EMBEDDINGS` **no se
   declara por defecto** en el proveedor Ollama: declararla sería mentir. Se
   activa con `embeddings=True` o `S9K_OLLAMA_EMBEDDING_MODEL` cuando el
   servidor arranque con `--embeddings`.

2. **El modelo devolvió los tipos de entidad en chino** (`组织/机构`, `地点`)
   con un prompt en español que pedía tipos libres. Con el prompt estricto del
   router (catálogo enumerado explícitamente) devolvió `Faction` correctamente.
   El mapeador **descarta** cualquier tipo fuera del catálogo, así que el fallo
   degrada a «sin tipo», nunca a «tipo inventado». Hay un test con este caso
   real.

3. **Recall pobre en la prueba de humo:** en ambas corridas `qwen2.5:7b` **omitió
   «Daiki»**, el sujeto de la frase. Es coherente con lo que el PR #106 ya había
   medido del extractor. **La capa de proveedores no arregla eso** — no es su
   trabajo: el prompt de extracción es del bloque extractor.

### ⬜ NVIDIA — implementado y probado con transporte simulado; **PENDIENTE DE
VALIDACIÓN EN VM105**

`execute()` es real y está cubierto por 27 tests unitarios con el transporte
inyectado (petición bien formada, `Bearer`, reintento sin `response_format`,
401/403/413/429/500, red caída, respuesta gigante, no filtración de la key,
bloqueo por credenciales en el payload, embeddings).

**No se ha hecho la llamada real.** Motivo, sin adornos: la clave vive en
`/etc/s9-knowledge/nvidia.env` en VM105 con permisos `0600 root:root`, no está
en el entorno local, y la clave SSH disponible (`id_ed25519_vm105`) es
**rechazada** por el host (`Permission denied (publickey,password)`). Extraer un
secreto de producción con maniobras adicionales quedaba explícitamente fuera de
lo autorizado, así que **no se ha intentado**.

**Para cerrar la validación** (ejecutar en VM105, con la unidad que cargue
`nvidia.env`):

```bash
S9K_LIVE_NVIDIA=1 pytest data-engine/app/tests/test_knowledge_v3_providers_nvidia.py -k live -s
```

Son **dos llamadas**: un `GET /models` (gratis) y un chat de ≤64 tokens.

> Recordatorio de la auditoría §5.4 que sigue vigente y **no** se arregla aquí:
> `nvidia.env` **no lo carga ninguna unidad systemd**. Mientras eso no cambie,
> la clave seguirá siendo inerte en producción aunque el adaptador ya funcione.

### Marcadores de humo

| Marcador | Activación | Coste |
|---|---|---|
| `live_ollama` | `S9K_LIVE_OLLAMA=1` | Gratis (LAN). Desactivado por defecto porque el CI no tiene ruta a la LAN. |
| `live_nvidia` | `S9K_LIVE_NVIDIA=1` **y** `S9K_NVIDIA_API_KEY` | **De pago.** Doble condición a propósito. |

---

## 9. Tests

| Fichero | Tests | Qué cubre |
|---|---|---|
| `test_knowledge_v3_providers_routing.py` | 23 | Mapa de capacidades, local-primero, política del externo, presupuesto, fallback, healthcheck |
| `test_knowledge_v3_providers_proposals.py` | 34 | Mapeo puro, anclaje local, `provider_trace` veraz, saneamiento, round-trip |
| `test_knowledge_v3_providers_authority.py` | 24 | **§2 por mutación**: plan firmado por proveedor, resellado, contratos prohibidos |
| `test_knowledge_v3_providers_robustness.py` | 30 | **§10**: caído, timeout, JSON inválido, gigante, inyección, secretos, workspace |
| `test_knowledge_v3_providers_ollama.py` | 30 + 3 live | Transporte simulado + humo real |
| `test_knowledge_v3_providers_nvidia.py` | 27 + 2 live | Transporte simulado + humo de pago |
| **Total** | **168 unitarios + 5 de humo** | |

`test_knowledge_v3_providers_support.py` no contiene tests: es utillaje
compartido (dobles de transporte y fixtures). Vive junto a los tests y **no**
en `conftest.py`, que no es propiedad de este bloque.

### Sobre los tests de mutación

*«Un test verde sólo vale si puede ponerse rojo.»* Cada test de autoridad
construye el ataque de verdad —un plan realmente firmado por `external`, un
plan realmente resellado— en lugar de comprobar una constante. Y hay un test
que **muta la propia guarda**: vacía `FORBIDDEN_CONTRACT_IDS`, comprueba que
entonces el ataque **sí** pasaría, la restaura y comprueba que vuelve a
cortarse. Demuestra que es la guarda la que corta y no otra cosa por
casualidad.

---

## 10. Límites de este bloque

* **No arregla la calidad del extractor.** Lo que `qwen2.5:7b` proponga es
  problema del bloque extractor; aquí sólo se garantiza que lo que proponga
  llegue **anclado, tipado dentro del catálogo, trazado y sin autoridad**.
* **No cablea proveedores en producción.** `default_router()` trae NVIDIA
  **apagado**; encenderlo cuesta dinero y exige política explícita.
* **No toca `ci.yml` ni `pytest.ini`**, ni el dispatcher, ni `external_ai/`, ni
  `conftest.py`.
* **No escribe en Neo4j.** Ni una línea de este bloque abre una conexión.
* **ASR y OCR no tienen proveedor real todavía.** Las capacidades están
  tipadas, enrutables y probadas con el mock; los proveedores deterministas
  (faster-whisper, tesseract) pertenecen al bloque multimodal.
