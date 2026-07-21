# Informe de validación — Bloque 7: Reejecución del benchmark

**Fecha:** 2026-07-20 · **resincronizado con el codigo el 2026-07-21 (ronda 4:
defecto `external_model` corregido + NVIDIA medida REAL)**
**Rama:** `test/relation-calibrated-benchmark-v1`
**Worktree:** `/home/ia02/worktrees/test-relation-calibrated-benchmark-v1`
**Base:** `1df631d` (Bloque 6 integrado: «feat(relations): ensemble calibrado explicable (#91)»)
**Módulos:** `relations/benchmark/` — nuevo `providers.py`; modificados `runner.py`,
`cli.py`, `metrics.py`, `report.py`
**Estado:** IMPLEMENTING (sin commit, sin push, sin PR)
**Revisiones incorporadas:** **ronda 1** (D1-D7: transporte vs calidad,
normalización de endpoint, `provider_status` en raíz, guard de `--all-modes`,
`run_cli`, alias de contadores, `NOT_EVALUATED` + `verdict_scope`), **ronda 2**
(B1-B5, N2, N5: llave en el núcleo, gate duro `provider_transport`, dictamen
`SIN DICTAMEN: PROVEEDOR NO MEDIDO`, muestra pequeña que endurece, manifiesto de
procedencia, validación/atestación de endpoint, endurecimiento del transporte,
timeout a 300 s), **ronda 3, CERRADA** (B1: tres categorías disjuntas con
`INDETERMINADA`; B3: manifiesto = integridad, **no** autenticidad; N1-N13) y
**ronda 4** (defecto `external_model` descubierto y corregido: guarda
`require_external_model` + flag `--external-model`; primera ejecución REAL de
NVIDIA con clave válida)
**Tests propios del bloque:** **177** (`153` de rondas 1-3 + `24` de la ronda 4,
`test_relation_benchmark_block7_round4.py`)
**Resultados publicados en:** [`docs/50-relation-benchmark-results.md`](../../50-relation-benchmark-results.md)

> **Vigencia: la ronda 3 había CERRADO el código; la ronda 4 es posterior y
> puntual.** No reabre el contrato de rondas 1-3 (§3.1-§3.19 siguen vigentes tal
> cual). Corrige un defecto real descubierto al medir NVIDIA por primera vez con
> clave de API válida — el carril externo nunca cableaba un id de modelo real
> (§3.20) — y documenta esa medición real (§6A). Con esto, **NVIDIA deja de
> figurar como "no ejecutada"**: el motivo del `verdict_scope = PARCIAL` que
> queda es `determinism` no evaluado en la ruta CLI, no NVIDIA.
>
> Historia del documento: §3.2 y §6.2 conservan el relato del bloque; el contrato
> vigente es el de §3.12-§3.20. Este informe se ha revisado **después de cada
> ronda de código**, que es justo lo que evita que un informe escrito una vez
> «mienta por construcción».

## 1. Objetivo

Reejecutar el benchmark de relaciones sobre el ensemble calibrado del Bloque 6 y
responder con datos a una pregunta concreta: **¿mejora algo el ensemble, y qué
exactamente?** Y hacerlo sin pagar el coste prohibitivo de una pasada completa con
proveedores reales ni arriesgar que CI abra red.

## 2. Encuadre: implementación 100 % offline, ejecuciones reales ACOTADAS

Es la decisión de diseño que condiciona todo el bloque, y se toma por dos hechos
medidos, no por prudencia genérica:

1. **Coste.** La estimación de partida —p50 de 10-65 s por evaluación, tomada de
   los Bloques 1 y 2— daba **5-20 h para una pasada COMPLETA con proveedores
   reales**. La medición del §6 la ha **corregido al alza**: el p50 real es de
   **97,8 s** y 6 fuentes tardaron **28 min** solo con Ollama. La conclusión del
   encuadre no solo se sostiene: se refuerza.
2. **No hay caché efectiva en la ruta de relaciones.**
   `relations.external_ai_shadow.evaluate_relation_external` llama directamente a
   `provider._post_chat(...)`, evitando la `ResponseCache` que
   `external_ai.openai_compatible` sí aplica en su ruta de alto nivel. Repetir una
   ejecución **repite íntegramente el coste**.

Consecuencia: el modo nuevo del benchmark es **offline y CI-safe**, los modos con
proveedor quedan **fuera** del diccionario que iteran `--all-modes` y los tests, y
las ejecuciones reales se acotan por submuestra y se **recombinan** en lugar de
repetirse.

## 3. Qué se implementó

### 3.1 Modo OFFLINE `ensemble_offline` (nuevo, dentro de `MODES`)

Aplica el ensemble calibrado del Bloque 6 **por post-proceso** sobre lo que el
pipeline ya calculó: `extract_predictions_ensemble` re-indexa las señales y la
sintaxis por par (`segment_context`) y llama a `ensemble.combine(...)` con las
evaluaciones ya existentes. **Cero llamadas a proveedor, cero red.**

Usa **el mismo `context_mode = "sentence"` que `baseline1`** deliberadamente: así
la comparativa es directa y la única variable que cambia es el combinador.

Las predicciones mantienen el esquema de `extract_predictions` (que **no** se
modifica) y añaden dos campos de trazabilidad: `base_consensus_state` y
`ensemble_score`.

### 3.2 Modos con proveedor FUERA de `MODES`, con DOBLE LLAVE

`ollama_shadow`, `nvidia_shadow` y `ensemble_full` viven en un diccionario
separado, `PROVIDER_MODES`. No están en `MODES` **a propósito**: ni `--all-modes`
ni ningún test que itere `MODES` puede ejecutarlos por accidente.

Para ejecutarlos hacen falta **dos llaves independientes**:

1. la bandera CLI `--enable-providers`, y
2. la variable de entorno `S9K_BENCH_PROVIDERS=1`.

`require_provider_authorization` se invoca en `cli.main` **antes** de cargar el
corpus y **antes** de construir ningún transporte — es decir, **antes de abrir
red**. Verificado en vivo:

```
$ python -m relations.benchmark.cli --mode ollama_shadow
ERROR: modo con proveedor 'ollama_shadow' requiere DOBLE LLAVE; falta:
--enable-providers, S9K_BENCH_PROVIDERS=1. ABORTADO ANTES DE ABRIR RED
(ninguna llamada a Ollama/NVIDIA realizada).

$ python -m relations.benchmark.cli --mode ensemble_full --enable-providers
ERROR: modo con proveedor 'ensemble_full' requiere DOBLE LLAVE; falta:
S9K_BENCH_PROVIDERS=1. ABORTADO ANTES DE ABRIR RED
(ninguna llamada a Ollama/NVIDIA realizada).
```

Refuerzos adicionales: `_build_providers` **importa `providers.py` de forma
perezosa** (en modo offline el módulo ni se importa); `providers.build_local_transport`
**no tiene default a infraestructura real** y falla cerrada sin endpoint explícito;
`--all-modes` aborta si se combina con un modo con proveedor.

> **SUPERADO por la ronda 2 (B1).** Esta sección describe la doble llave **de la
> CLI**, que sigue vigente, pero **ya no es la barrera principal ni una condición
> universal**. La llave vive ahora en el **núcleo** (`authorize_provider_run`), y
> un llamante que **inyecta** los proveedores **no necesita doble llave**. Ver
> §3.12, que es el contrato correcto.

### 3.3 Nuevas opciones de CLI

| Opción | Para qué |
|---|---|
| `--sources` | submuestra de `source_id`. El corpus se carga y verifica **igual**; solo se acotan las fuentes procesadas, y `build_report` restringe el ground truth evaluado a esas fuentes (si no, las no procesadas contarían como falsos negativos y el informe mentiría) |
| `--out-payloads` | vuelca a JSONL los payloads CRUDOS local/external por candidato; desde la ronda 2 emite además `<jsonl>.manifest.json` (§3.16) |
| `--recombine-from` | recombina el ensemble **offline** desde ese JSONL: **cero** llamadas. Desde la ronda 2 **exige y verifica un manifiesto de procedencia** (§3.16) |
| `--local-endpoint` / `--local-model` | endpoint y modelo del LLM local (solo modos con proveedor) |

`--out-payloads` + `--recombine-from` es la **contramedida al coste**: una única
pasada real se recombina tantas veces como haga falta con distintas
configuraciones de ensemble sin volver a pagar. Sustituye funcionalmente a la
caché inexistente.

### 3.4 `metrics.provider_cost()`

Llamadas y latencias p50/p95/máx por proveedor, más el recuento de payloads y las
estadísticas de estado. Con los proveedores desactivados devuelve **ceros y `None`
limpios**: sin muestras no se inventa ninguna latencia.

### 3.5 Corrección: el bloque `providers` del informe ya no miente

Antes, el Markdown imprimía el literal «Ollama real: **NOT_EXECUTED**»
**siempre**, incluso si los proveedores se hubieran ejecutado. Ahora ese bloque se
**deriva** de `output['provider_status']` (`report._providers_block`), y el campo
`network` pasa a `yes (proveedores ejecutados)` cuando alguno se ejecutó. Un
informe que afirma una garantía de seguridad debe **medirla**, no declararla.

### 3.6 Timeout del LLM local: **300 s** (era 180 s) — riesgo CERRADO

`PROVIDER_LOCAL_TIMEOUT_S = **300**`, y `build_local_transport` **rechaza**
cualquier timeout inferior a 120 s. Motivo original: el default de
`LocalLLMConfig` es de 30 s, pensado para tests con transporte inyectado (latencia
~0); con la latencia real de Ollama casi todas las llamadas expirarían y **el
benchmark mediría timeouts, no calidad del modelo**.

**Historia completa, sin adornos.** El valor inicial de 180 s se eligió sobre una
estimación de «p50 10-65 s» heredada de los casos **sintéticos** de los Bloques 1
y 2. La medición del §6 la **refutó** (p50 real 97,8 s; máximo 175,7 s): los 180 s
bastaron —**0 timeouts**— pero por **4,3 s**. Este informe registró entonces un
riesgo abierto recomendando subirlo; **la ronda 2 lo aplicó**:

> **300 s ≈ 175,7 s × 1,7**, un margen de ~124 s sobre el peor caso observado.
> El riesgo «timeout marginal» queda **CERRADO** (§8.9). Nótese que la latencia
> medida es de una máquina **sin GPU**: otra configuración dará otro perfil.

El **deadline efectivo por llamada** es de **330 s** (300 + `WALL_CLOCK_MARGIN_S`
= 30), y **no existe deadline global de run** (§3.13, §8.10).

### 3.7 (D2) Normalización del endpoint local

`providers.normalize_local_endpoint(endpoint)` normaliza la URL antes de cualquier
POST:

| Endpoint aportado | URL usada |
|---|---|
| `…/v1/chat/completions` | se usa **tal cual** |
| `…/v1` | se le añade `/chat/completions` |
| cualquier otra base (`http://host:11434`) | se le añade `/v1/chat/completions` |

Las barras finales se recortan; la normalización **no abre red**.

**El caso real que lo motivó:** el Organizador pasó `http://127.0.0.1:11434/v1`
—la forma natural de indicar la base OpenAI-compatible de Ollama— y el transporte
hizo POST a esa URL tal cual: **18 respuestas 404, contabilizadas como llamadas
ejecutadas**, como si el modelo hubiera contestado mal. Con la URL completa **ese
mismo Ollama responde 200 en ~3,9 s**. Era un fallo de ruta disfrazado de fallo de
calidad del modelo, y es exactamente la confusión que ataca D1.

### 3.8 (D1) Fallo de TRANSPORTE ≠ respuesta INVÁLIDA del modelo

El pipeline R8 degrada **cualquier** problema de un proveedor al mismo estado
canónico `INVALID_RESPONSES`: un 404 y un JSON malformado del modelo acaban
indistinguibles en `results_invalid`. Eso convierte un fallo de **infraestructura**
en un dictamen de **calidad**. El benchmark separa ahora dos categorías
**disjuntas**, sin reimplementar nada del pipeline: lee los marcadores que el
propio evaluador ya escribe (`validation_errors` en local, `reason_codes` en
external) y los reclasifica.

| Categoría | Qué es | Marcadores |
|---|---|---|
| **Fallo de TRANSPORTE** | la llamada **nunca obtuvo respuesta utilizable**; no dice nada del modelo | `transport_error:*` (error de red/HTTP, timeout, DNS, cuerpo no parseable como JSON), `provider_error:*`, `response_structure_invalid` (falta `choices[0].message.content`), `response_content_not_str` |
| **Respuesta INVÁLIDA del modelo** | el proveedor **sí respondió**, pero el contenido no supera la validación (parseo, campos, tamaño); **esto sí es señal de calidad** | `parse:*`, campos inválidos, respuesta demasiado grande |

El transporte de `providers.py` colabora elevando `ProviderTransportError` ante
cualquier excepción de red, cuerpo no parseable, ausencia de
`choices[0].message.content` o contenido que no sea texto.

Nuevas salidas:

- `provider_cost.transport_errors` — por proveedor y total:
  `attempted` / `responded` / `errors` / `rate` / `by_type`.
- `provider_cost.transport_error_rate` (global y por proveedor).
- `provider_cost.<local|external>.latency` — p50/p95/máx **solo de llamadas
  RESPONDIDAS**. Mezclar un 404 inmediato con una respuesta real producía **el p50
  de 0 ms** que delató el defecto.
- `provider_cost.<local|external>.failed_latency` — las latencias fallidas,
  reportadas **aparte**, no descartadas.
- `report["provider_transport"]` en la raíz del JSON y sección propia
  «Fallos de TRANSPORTE (infraestructura, NO calidad del modelo)» en el Markdown.

### 3.9 (D1) Umbral de salud del transporte: 10 %, mínimo 3 llamadas

`PROVIDER_TRANSPORT_ERROR_MAX_RATE = 0.10`, `PROVIDER_TRANSPORT_MIN_CALLS = 3`.

Si la tasa de fallos de transporte supera el 10 % con al menos 3 llamadas
intentadas, `check_provider_transport_health` lanza `ProviderTransportError`, el
run **ABORTA** y **NO se emite dictamen alguno**. La comprobación se hace **tras
cada fuente** (*fail-fast*): no se sigue pagando llamadas a un proveedor que ya se
ha demostrado caído. El mensaje de error incluye el desglose por tipo y apunta a
la causa más probable (¿el endpoint termina en `/v1/chat/completions`?).

Justificación: **un fallo de infraestructura no mide la calidad del modelo.**
Emitir un «NO APTO» a partir de llamadas que nunca llegaron al modelo es el error
de medición que este bloque debe eliminar. Un proveedor sano prácticamente nunca
falla en transporte, así que el 10 % no es una tolerancia estadística sino un
margen para un hipo puntual (un reintento agotado, un corte de un segundo) sin
invalidar una pasada larga. El mínimo de 3 llamadas existe porque con 1-2 la tasa
es ruido puro.

> **El 10 % es una elección de diseño razonada, NO un umbral calibrado con datos
> reales de fallo de VM105.** No existe serie histórica de tasas de fallo de
> transporte contra esa máquina. Cuando la haya, el número debe revisarse con
> datos, no defenderse por antigüedad.

> **SUPERADO EN PARTE por la ronda 3 (N1/N2, §3.19).** Lo que esta sección describe
> —10 %, mínimo 3 llamadas, fail-fast tras cada fuente— era, tal cual, un umbral
> **efectivo distinto del documentado**: con `min_calls = 3` corriendo tras cada
> fuente, **un solo fallo en la llamada #1 de 36** abortaba con «1/5 = 20 %», pese
> a que la tasa final habría sido del **2,8 %**. Y la tasa se evaluaba **solo
> agregada**, de modo que un carril al 14,3 % diluido por otro al 0 % daba 4,76 %
> y dictamen «APTO». El contrato vigente está en §3.19 (N1, N2).

### 3.10 (D7) Determinismo NO EVALUADO y `verdict_scope`

El gate `determinism` pasa a `NOT_EVALUATED` cuando `deterministic is None`
(`--no-determinism` o modo con proveedor), en vez de contar como FAIL. **Sigue
siendo un gate DURO:** un `FAIL` real sigue produciendo `NO APTO`; lo que ya no
ocurre es que «no comprobado» se trate como «comprobado y fallido».

Nuevo campo `report["verdict_scope"]`:

- `COMPLETO` — todos los gates duros evaluados.
- `PARCIAL (gates duros no evaluados: …)` — el dictamen no cubre esas
  comprobaciones. El aviso se repite dentro de `verdict_justification` y en la
  sección «Determinismo» del Markdown: no se oculta, se declara.

**Esto corrige el defecto que este informe había detectado**: las cuatro filas de
`all_modes` reportaban `NO APTO`. Queda **confirmado que la causa era
`check_determinism=False`, no la calidad** — hoy las cuatro filas reportan
«APTO CON REVISION HUMANA TOTAL» (ver §4.3).

### 3.11 (D3/D4/D5/D6) Correcciones menores

| Def. | Corrección |
|---|---|
| D3 | `provider_status` aparece ahora en la **raíz** del JSON (antes salía `null` ahí y solo estaba enterrado en `providers.provider_status_raw`, que se conserva por compatibilidad); se añade `report["provider_transport"]` |
| D4 | el guard de `--all-modes` con modo de proveedor se evalúa **antes** de construir transportes y de cargar el corpus. Antes vivía después del run: con la doble llave concedida se ejecutaba el benchmark completo contra proveedores reales —**pagando las llamadas**— y solo después se abortaba, tirando todo el trabajo |
| D5 | nuevo punto de entrada `cli.run_cli(argv)` que traduce **siempre** `BenchmarkError` (y `ProviderTransportError`) al código de salida **2**, sin traza. `main()` sigue propagando la excepción a propósito: importado como función, un abort debe ser un error visible, no un entero ignorable |
| D6 | alias aditivos `local_calls` / `external_calls` en `metrics.operational.counters` y en cada fila de `all_modes`, más la nota `provider_cost.calls_counter_note`: el sufijo `_simulated` es **histórico** y NO implica simulación — cuenta llamadas **REALES** cuando hay transporte inyectado. El nombre original nace en `relations/pipeline.py` y se conserva para no romper su contrato |

La CLI imprime además `transport_errors=… rate=…` y `verdict_scope=…`.

---

## 3.12 (B1) La llave pasa al NÚCLEO: `authorize_provider_run`

**Cambio de contrato.** `require_provider_authorization` solo se invocaba desde
`cli.main()`, pero `run_benchmark` / `run_source` son **API pública** exportada en
`relations.benchmark.__init__`. Llamar `run_benchmark(corpus, mode="nvidia_shadow")`
desde código ponía `external_ai_enabled=True` y, con `external_provider=None`, el
pipeline **delegaba en el registry de `external_ai`**, que lee la clave del
entorno y abre conexiones **reales** contra NVIDIA sin bandera ni variable de
entorno. Demostrado: **5 intentos**; **10** si además se pedía
`check_determinism=True`.

`runner.authorize_provider_run` se ejecuta ahora dentro del núcleo, **antes de
construir ninguna `PipelineConfig`**, con fallo cerrado:

1. Modo offline → nada que autorizar.
2. Modo con proveedor → **cada** proveedor habilitado por el preset **debe estar
   INYECTADO**; si falta, `BenchmarkError`. **El núcleo nunca delega en el
   registry.**
3. Si el llamante **no** inyecta todos los proveedores, se exige además la doble
   llave explícita.

### La doble llave NO es condición necesaria universal

Punto que el documento público no explicaba y el docstring sí: **un llamante de
librería que inyecta los proveedores no necesita doble llave**. Es **deliberado**
— quien construye e inyecta un transporte real lo ha hecho a propósito; la doble
llave existe para cerrar el camino *implícito* (el registry), no para estorbar al
explícito.

| Situación | ¿Doble llave? |
|---|---|
| Modo offline | no aplica |
| Modo con proveedor, **todos** inyectados | **NO se exige** |
| Modo con proveedor, alguno **sin inyectar** | **SÍ** — y aun así falla: no hay resolución por registry |
| CLI | **SÍ**: la valida y después construye los transportes |

## 3.13 (B5/N2/N5) Endpoint validado y transporte endurecido

| Control | Estado |
|---|---|
| **Validación de endpoint** | esquema `http`/`https`, host no vacío, **sin credenciales embebidas**. Antes se aceptaba cualquier cadena: con `file:///…` se fabricaba un run con «Ollama EXECUTED», llamadas contadas y latencias medidas **sin una sola conexión**; con `ftp://` se abría conexión a un host arbitrario |
| **`endpoint_attestation`** | el informe publica `esquema://host:puerto`, sin credenciales, ruta ni query (`providers.endpoints`); variante `external_endpoint_attestation()` para NVIDIA |
| **Redirecciones** | **bloqueadas entre orígenes** por un opener propio, que **previene** la petición al segundo host en vez de detectarla a posteriori |
| **Tope de lectura** | `MAX_RESPONSE_BYTES = 1 MiB`, aplicado **por trozos**. El tope del pipeline se aplicaba tras leer y parsear el cuerpo entero: una respuesta de 200 MB llegaba a memoria (RSS 25 MB → 627 MB) |
| **Deadline de reloj de pared** | 300 + 30 = **330 s por llamada**, comprobado entre trozos. `urlopen(timeout=)` es por operación: un servidor que goteaba 1 byte/s mantuvo viva una llamada 60 s con `timeout=2` |
| **Proveedor externo (N5)** | `build_external_provider()` ya **no es la identidad**: construye el proveedor del registry de forma explícita, exigiendo API key y validando `base_url`; falla **cerrado**. Antes devolvía siempre `None`, lo que alimentaba B1 y B2 |

> **Aviso de numeración.** Los identificadores `N…` de la **ronda 2** (los de esta
> sección: N2 = tope de lectura y deadline de pared; N5 = `build_external_provider`)
> **no** son los de la **ronda 3** (§3.19), que reutiliza `N1`-`N13` para otros
> hallazgos. Los comentarios de `providers.py` conviven con ambas numeraciones:
> la cabecera «Apertura HTTP endurecida (N1 + N2)» es de la **ronda 2**, mientras
> que `N5`/`N6`/`N9`/`N10`/`N12`/`N13` en ese mismo fichero son de la **ronda 3**.
> No es un error del código, pero se advierte para que nadie los cruce.

**El deadline GLOBAL de run existe desde la ronda 3** (`--max-run-seconds`, N11,
§3.19). *Corrección de este informe: hasta la ronda 2 la afirmación «no existe
deadline global de run» era cierta; hoy es falsa.* Ver §8.10 para lo que sigue
abierto de ese control.

## 3.14 (B2) Gate duro `provider_transport`, dictamen «SIN DICTAMEN» y atestación

**Gate DURO nuevo `provider_transport`**, solo en modos con proveedor:

| Estado | Cuándo |
|---|---|
| `PASS` | evaluable, **0** errores de transporte y (desde la ronda 3) **0** indeterminadas y **0** `fail_closed` |
| `PARTIAL` | evaluable con errores por debajo del umbral; desde la ronda 3 también con llamadas **INDETERMINADAS** (§3.17) o con `provider_fail_closed > 0` (N7) |
| `FAIL` | `evaluable = False`: tasa por encima del umbral, carril completamente caído, o **muestra por debajo de `min_calls`** aunque no haya errores |
| `NOT_MEASURED` | **0 llamadas contabilizadas** |

**Dictamen nuevo en `VERDICTS`: `SIN DICTAMEN: PROVEEDOR NO MEDIDO`.** Si el gate
no está en `PASS`/`PARTIAL` no se emite dictamen de calidad: «NO APTO» sería una
**afirmación falsa** sobre el pipeline, porque no se ha medido nada.
`verdict_scope` pasa a **`NO MEDIDO (…)`** y la CLI termina en **código 2**.

**Atestación de red derivada de llamadas contabilizadas.** Antes,
`--mode nvidia_shadow` publicaba «Red: none» **tras 5 POST reales contra NVIDIA**,
porque `external_provider` valía `None`: una atestación de seguridad **falsa**.
Ahora `network` sale de `total_attempted`, y cuando no es determinable se publica
`unknown`, nunca `none`. `status_consistency` contrasta el literal
`provider_status` (que calcula `relations/pipeline.py`, fuera de alcance) con las
llamadas contadas.

> **Honestidad exigida sobre estos dos mecanismos** (§8.11, §8.12): la atestación
> de red en modo con proveedor es **incompleta, nunca falsa** —puede decir
> `yes (proveedores ejecutados)` con `network_calls_counted: 0`—, y
> `status_consistency: INCONSISTENTE` era, tal como estaba escrito entonces,
> **inalcanzable**: **código defensivo, no una mitigación activa**.
>
> **Actualización de la ronda 3 (N8):** la comprobación se hace ahora en las **dos
> direcciones**, y solo una de ellas sigue siendo código muerto. «Llamadas
> contabilizadas sin ningún `EXECUTED`» sigue siendo **inalcanzable**; «`EXECUTED`
> con **cero** llamadas contabilizadas» **sí ocurre** en runs reales (fuentes sin
> candidatos, proveedor que nunca llegó a invocarse) y hoy se declara. La
> afirmación «el mecanismo entero es inalcanzable» **ya no es correcta**.

## 3.15 (B3) La muestra pequeña ENDURECE, no perdona

`check_provider_transport_health(..., strict_small_sample=True)` —que es como lo
invoca **siempre** `run_benchmark`— hace que, por debajo de
`PROVIDER_TRANSPORT_MIN_CALLS = 3`, **cualquier** error de transporte aborte.
Antes ocurría lo contrario: **9 de 16 fuentes emitían «APTO» con 1-2 llamadas
todas fallidas, o con 0 llamadas**. Con tan pocas llamadas no se distingue un hipo
puntual de una caída total, así que el criterio se endurece. Las estadísticas
publican `min_calls`, `min_rate_sample`, `sample_below_minimum`, `rate_applied`,
`final_check` y `evaluable`.

**Ronda 3:** `strict_small_sample` pasa a ser **`True` por defecto** en la firma
de `check_provider_transport_health` — la variante permisiva no la usaba ningún
llamante del bloque y solo servía para que un run con 1-2 llamadas todas fallidas
pareciera sano. Y el umbral **por proveedor** está **aplicado** (N2, §3.19).

## 3.16 (B4) Manifiesto de procedencia obligatorio para los payloads

`--out-payloads` emite junto al JSONL un manifiesto `<jsonl>.manifest.json`
(`relation-benchmark-payloads-manifest-v1`) con `payloads_sha256`,
`payloads_bytes`, `records`, `mode`, `code_sha`, `pipeline_version`,
`ground_truth_sha256`, `corpus_hashes` y `source_ids`.

**`--recombine-from` lo exige y lo verifica** (o `--recombine-manifest`):
sha256, tamaño, número de registros, hash del ground truth y hashes del corpus;
topes de **64 MiB** y **100 000 registros**; validación de esquema de cada
registro con **rechazo en bloque**. Los `source_ids` evaluados salen del
**manifiesto**, no del fichero.

Motivo: el corpus verificaba sha256 pero los payloads **no verificaban nada**. Un
JSONL forjado producía **P = R = F1 = 1.0 con `rc=0`** y latencias inventadas de
99 999 ms; y como el ground truth se elegía por los `source_id` del propio
fichero, **el atacante escogía su examen**.

**Ronda 3: este manifiesto, tal como quedó en B4, NO bastaba.** Ver §3.18 — dos de
sus campos eran decorativos y el vocabulario («verificado») prometía más de lo que
comprueba.

---

## 3.17 (B1, ronda 3) `provider_error` deja de ser sinónimo de fallo de transporte

**El defecto.** §3.8 clasificaba `provider_error:*` como **fallo de TRANSPORTE**.
Eso es falso para una parte importante de los casos: el `except _PROVIDER_ERRORS`
de `relations/external_ai_shadow.py` agrupa **toda** la familia `ExternalAIError`,
e incluye `InvalidResponseError`, que se emite cuando el modelo **SÍ contestó**
(HTTP 200) pero su contenido no es utilizable — `{"relations": []}` («la respuesta
no contiene ningún veredicto») o texto libre no-JSON del que no se puede extraer
nada. Eso es **calidad**, no infraestructura: es la misma avería que el carril
local etiqueta `no_relation_extracted`. Contarla como transporte **abortaba
pasadas sanas con un diagnóstico de infraestructura falso**.

**Dónde vive la causa raíz y por qué no se toca.** En
`relations/external_ai_shadow.py`, **fuera del alcance del Bloque 7**, y **no se
ha modificado**. La discriminación se hace sin tocarlo, leyendo el **nombre de la
excepción** que el propio payload deja escrito (`provider_error:<Excepcion>` en
local; `reason_codes=["provider_error"]` + el nombre pelado en `validation_errors`
en external).

**Tres categorías DISJUNTAS** (`metrics.CATEGORY_TRANSPORT`, `CATEGORY_RESPONDED`,
`CATEGORY_INDETERMINATE`), resueltas por `classify_provider_outcome`:

| Categoría | Criterio | Efecto |
|---|---|---|
| **TRANSPORTE** | `transport_error:*`, `response_structure_invalid`, `response_content_not_str`, o un `provider_error` cuya excepción está en `TRANSPORT_EXCEPTION_NAMES` (timeout, servidor, auth, not-found, ratelimit, `URLError`, `HTTPError`, `Connection*`…) | cuenta para el umbral y **puede abortar** el run |
| **RESPONDIDA** | sin marcador de fallo, o `provider_error:InvalidResponseError` (`QUALITY_EXCEPTION_NAMES`) | entra en `responded` y en las latencias del modelo: **es la señal de calidad** |
| **INDETERMINADA** | `provider_error` genérico, sin nombre o con nombre desconocido | **ni una cosa ni la otra** |

**La limitación, documentada como tal.** Cuando el nombre no permite decidir, el
benchmark **no afirma lo que no puede saber**: la llamada queda **INDETERMINADA**,
**no aborta el run** y **no se presenta como medida de calidad del modelo**. Se
publica explícitamente: bloque `indeterminate` en el JSON (por proveedor y total,
con `count`, `rate`, `by_type` y una `note` textual), `indeterminate_latency`
**separada** de `latency` y de `failed_latency`, columna propia en el Markdown y
**degradación del gate `provider_transport` a `PARTIAL`**, que se declara en
`verdict_scope` (N3).

Esto es una **mitigación honesta, no una solución**: el benchmark declara su
incertidumbre en vez de resolverla a favor de una hipótesis. Cerrar la zona gris
exige corregir el `except` de `external_ai_shadow.py` — otro bloque (§8.13).

**Rotura de contrato menor, deliberada:** `classify_provider_payload` sigue
existiendo, pero su `None` **ya no significa «respondió»**: puede ser
INDETERMINADO. El docstring lo dice y remite a `classify_provider_outcome`.

## 3.18 (B3, ronda 3) El manifiesto es INTEGRIDAD, no AUTENTICIDAD

**El hecho que lo motivó, sin suavizar:** con el manifiesto de B4 ya implantado,
el Organizador **falsificó un manifiesto usando solo valores públicos del
repositorio** y volvió a obtener **P = R = F1 = 1.0 con `rc=0`**. El sello existía
pero no ataba nada comprobable.

**Los dos agujeros cerrados:**

| Campo | Antes | Ahora |
|---|---|---|
| `corpus_hashes` | `{}` **desactivaba por completo** la atadura al corpus: la verificación iteraba las claves **del propio manifiesto** | debe ser **no vacío** y cubrir **EXACTAMENTE** los `source_ids` (`sorted(hashes) == sorted(set(ids))`) |
| `code_sha` | **no se contrastaba con nada**: 40 ceros era aceptado | debe ser **igual** al `code_sha` del proceso que recombina |

**El ORDEN de la comprobación de `code_sha` es parte del arreglo.** Primero se
exige que **este** proceso tenga un `code_sha` determinable y **solo después** se
compara. Con el orden inverso, un árbol **sin git** (`code_sha_actual is None`)
frente a un manifiesto con `code_sha: null` **pasaba la igualdad** (`None ==
None`): la seguridad dependía de que un `!=` no cambiara nunca. **La ausencia de
atadura es motivo de rechazo por sí misma, no un empate afortunado.**

**Cambio de vocabulario, que es el fondo del asunto.** `provenance.verified` ya no
dice «verificado»; dice literalmente **«integridad interna, NO autenticidad»**, y
`verified_detail` enumera lo comprobado y **lo NO comprobado**:

- **demuestra**: que el JSONL no ha cambiado desde que se emitió ese manifiesto, y
  que corresponde a este corpus, este ground truth y este `code_sha`;
- **NO demuestra**: **QUIÉN** emitió los payloads, ni que procedan de llamadas
  reales a un proveedor. Todos los valores del manifiesto son **públicos en el
  repositorio**: cualquiera con una copia puede fabricar uno válido.

**Sin clave de operador no hay autenticidad.** La única pieza que la aporta es el
HMAC-SHA256 sobre el manifiesto (excluyendo su propio campo), activo solo si el
operador define `S9K_BENCH_MANIFEST_HMAC_KEY`. Con clave definida, un manifiesto
sin HMAC o con HMAC inválido se **RECHAZA** (`hmac.compare_digest`); sin clave, el
informe publica `hmac: "AUSENTE (sin clave de operador: NO hay autenticidad)"`.

## 3.19 (N1-N13, ronda 3) No bloqueantes, verificados uno a uno en el código

| # | Qué fallaba | Qué hace hoy el código |
|---|---|---|
| **N1** | umbral **efectivo ≠ documentado**: con `min_calls = 3` y chequeo tras cada fuente, **un fallo en la llamada #1 de 36** abortaba con «1/5 = 20 %» aunque la tasa final fuera 2,8 % | `PROVIDER_TRANSPORT_MIN_RATE_SAMPLE = 20` para las comprobaciones **intermedias**; la comprobación **FINAL** (`final=True`) aplica la tasa con `min_calls`. Siguen abortando siempre: muestra por debajo del mínimo **con errores**, y carril con el **100 %** de llamadas fallidas |
| **N2** | tasa **solo agregada**: carril local al 14,3 % diluido con externo al 0 % → 4,76 % y «APTO» | la tasa se aplica **por carril** además de agregada; el mensaje de aborto dice que el agregado «por sí solo NO lo habría detectado» |
| **N3** | `PARTIAL` de transporte **no se declaraba**: se emitía dictamen normal sin mencionar el transporte degradado | `verdict_scope` → `PARCIAL (transporte del proveedor DEGRADADO: <motivos> …)`, y los mismos `degraded_reasons` en `verdict_justification` y en el Markdown |
| **N4** | el criterio de vigilancia (`local_transport is not None or …`) dejaba el umbral **muerto** en el carril externo; end-to-end la mutación quedaba **enmascarada** por `authorize_provider_run` | `should_watch_transport(mode, …)` es función aislada cuyo criterio es **el modo**, con *mutation check* directo que mata la variante «por inyección» |
| **N5** | validar el host **antes** que las credenciales volcaba `endpoint!r` **entero** a stderr: `http://tok:SECRETO@/v1` **filtraba el secreto** (y a los logs de CI) | credenciales **primero**; **ninguna** rama de validación reproduce la URL cruda |
| **N6** | `_open` comparaba `urllib.request.urlopen is _STDLIB_URLOPEN` y, si diferían, **se saltaba** el bloqueo de redirecciones: cualquier mock lo desactivaba en silencio | el opener endurecido se usa **siempre**; la costura de test es **explícita** (`opener=` o `providers._OPENER`, `None` en producción) |
| **N7** | `provider_fail_closed` (candidatos que un proveedor habilitado no llegó a evaluar) **no deja payload**: carril entero muerto → `rate = 0.0` y gate `PASS` | se publica `fail_closed` + `fail_closed_note` junto a `attempted`, y **degrada el gate a `PARTIAL`** aunque la tasa sea cero |
| **N8** | `status_consistency` solo miraba una dirección, y era la **inalcanzable** | se comprueba en las **dos**; la alcanzable («`EXECUTED` con 0 llamadas») hoy se declara |
| **N9** | atestación/normalización rotas en los bordes: puerto 0 **desaparecía** de la atestación; IPv6 daba `http://::1:11434`; una base con query producía `…/v1?k=X/chat/completions` (404 siempre) | puerto 0 **rechazado**; IPv6 **con corchetes**; la ruta se sustituye con `urlunsplit` **conservando la query** y descartando el fragmento; normalización **idempotente** |
| **N10** | puerto fuera de rango (`http://host:99999/v1`) → `ValueError` crudo y **rc=1**, fuera del contrato de códigos de salida | se traduce a `BenchmarkError` → **código 2**, sin reproducir la URL |
| **N11** | **no había** presupuesto global: con 300 s por llamada, un servidor que se atasca 1 de cada 10 llamadas añade el timeout entero por atasco **sin superar el umbral del 10 %** | `--max-run-seconds` / `run_benchmark(max_run_seconds=…)`, comprobado **entre fuentes**; al agotarse aborta y **las fuentes ya ejecutadas NO producen dictamen** |
| **N12** | `repo_root = Path.cwd()`: el destino/config del proveedor externo dependía **del directorio desde el que se lanzara el proceso** | `_REPO_ROOT` se deriva del propio módulo (`data-engine/app`) |
| **N13** | `build_local_transport` caía **implícitamente** a `S9K_BENCH_OLLAMA_ENDPOINT`: con esa variable apuntando a un host atacante, un llamante de la API pública abría conexiones **sin haber nombrado ningún destino** | el endpoint es **explícito y obligatorio**; falla cerrada **aunque la variable exista** (y lo menciona). La **CLI** resuelve el entorno, lo pasa explícito y publica **ese mismo** destino en la atestación |

**Cobertura:** el fichero `tests/test_relation_benchmark_block7_round3.py` cubre
B1, B3 y N1-N13 con **79 tests**, incluidos *mutation checks* explícitos para las
regresiones que un cambio inocente reintroduciría (N1 umbral intermedio restaurado
a `min_calls`, N2 «solo agregado», N4 criterio por inyección, N6 costura ignorada,
N13 fallback al entorno, B1 `InvalidResponseError` como transporte y B1
indeterminado colapsado a «respondida», B3 `code_sha` sin contrastar y `code_sha`
inventado en vez de indeterminado).

## 3.20 (ronda 4) El defecto `external_model`: descubierto MIDIENDO, no leyendo código

**El defecto, verificado en el código.** `PipelineConfig.external_model`
(`relations/pipeline.py:151`) vale por defecto el placeholder literal
`"external-model"`. El preset `nvidia_shadow` de `MODE_PRESETS`
(`relations/benchmark/runner.py`) solo ponía `external_ai_enabled: True` —
**nunca fijaba `external_model`** — y no existía ninguna bandera de CLI para
hacerlo. Consecuencia: al ejecutar `nvidia_shadow` con clave de API real, el
carril externo enviaba el placeholder literal a NVIDIA, que responde **404**
(`ProviderNotFoundError`); el runner lo clasificaba como fallo de
**transporte** (§3.8/§3.17) y el run abortaba con un diagnóstico de **"fallo de
INFRAESTRUCTURA"** que en realidad era un error de **configuración**.

**Por qué ninguna ronda anterior (1-3) lo detectó.** Las rondas 1-3 son
exhaustivas en transporte, autorización, endpoint y manifiestos, pero **todas**
sus verificaciones son offline o con transporte inyectado por un doble de
prueba (`_RecordingProvider`-like), que nunca ejercita el valor real de
`external_model` contra un servidor HTTP real. El defecto solo se manifiesta en
el momento del POST real a NVIDIA — exactamente la llamada que las rondas
anteriores, y los propios revisores, tenían **prohibido hacer** (es la misma
regla de diseño que motiva todo el bloque, §2). Mientras NVIDIA figuraba como
**"NO EJECUTADA"** (§6.6, §8.7 de versiones previas de este informe), la
avería quedaba oculta detrás de una etiqueta que parecía prudencia razonada y
en realidad escondía un bug real. **Es la lección central del bloque: medir de
verdad revela lo que la teoría — y la revisión de código sin red — tapa.**

**El arreglo**, íntegro en `relations/benchmark/` (sin tocar `pipeline.py` ni
`external_ai_shadow.py`):

1. `cli.py`: nuevo flag `--external-model <id>` para los modos con IA externa
   (`nvidia_shadow`, `ensemble_full`). `_resolve_external_model(args)` usa el
   valor explícito o, si se omite, el primer id de `S9K_NVIDIA_REVIEW_MODELS`
   (vía el registry de `external_ai`) — sin hardcodear ningún id.
2. `runner.py`: threading explícito `run_benchmark(..., external_model=...)` →
   `run_source(..., external_model=...)` → `_config_for_mode(mode,
   external_model=...)`, que solo sobreescribe `PipelineConfig.external_model`
   si el valor no es vacío.
3. `runner.require_external_model(mode, external_model)`: guarda **fail-closed**
   que, si el modo habilita IA externa y el id está ausente, vacío o es
   exactamente `PLACEHOLDER_EXTERNAL_MODEL = "external-model"`, lanza
   `BenchmarkError` **antes de construir transporte o proveedor** — antes de
   tocar la red — nombrando la causa real como **CONFIGURACIÓN**, no red.

**Se invoca desde `run_source` y `run_benchmark` (API pública), no solo desde la
CLI** — la misma disciplina que ya aplicaba `authorize_provider_run` (§3.12):
un llamante de librería que se salte la CLI también queda protegido.

**Cobertura:** `tests/test_relation_benchmark_block7_round4.py`, **24 tests**,
incluyendo `test_nvidia_sin_external_model_aborta_como_configuracion_no_transporte`,
`test_nvidia_con_external_model_llega_el_id_real_no_el_placeholder`,
`test_nvidia_config_for_mode_thread_del_external_model`,
`test_ensemble_full_tambien_exige_external_model`,
`test_ollama_shadow_no_afectado_por_la_guarda` y el *mutation check*
`test_nvidia_mutation_guarda_placeholder`.

## 4. Resultados medidos (2026-07-20, offline, determinismo verificado)

Todas las cifras: `provider_status = NOT_EXECUTED/NOT_EXECUTED`, red `none`,
escrituras `none (dry-run, sin Neo4j)`, **0 llamadas**, **0 fallos de transporte**
(`transport_error_rate = 0.0`), `verdict_scope = COMPLETO`. Corpus v1.0.0 (16
fuentes, 54 relaciones; GT sha256 `15973d18…`), pipeline
`relation-pipeline-1.0.0`.

**Las cifras se reprodujeron después de las correcciones D1-D7, después de la
ronda 2 y de nuevo el 2026-07-21 después de la ronda 3: idénticas las tres
veces** — P/R/F1, TP/FP/FN, gates, dictamen, contadores operativos, matriz de
confusión y `verdict_scope`. Los arreglos afectan a la instrumentación, la
seguridad y el alcance del dictamen, **no al pipeline ni al ensemble**.

### 4.1 Corpus completo: el ensemble NO mueve P/R/F1 — y es lo correcto

| Métrica (existencia) | `baseline1` | `ensemble_offline` |
|---|---|---|
| Precisión | 0.8269 | 0.8269 |
| Recall | 0.7963 | 0.7963 |
| F1 | 0.8113 | 0.8113 |
| TP / FP / FN | 43 / 9 / 11 | 43 / 9 / 11 |
| Gates | idénticos | idénticos |
| Dictamen | APTO CON REVISION HUMANA TOTAL | APTO CON REVISION HUMANA TOTAL |

**Explicación, no excusa:** el emparejamiento del benchmark es por par
sujeto-predicado-objeto, es decir mide **qué pares se generan**. El ensemble no
genera ni elimina pares: **recalibra el CONSENSO** sobre los pares que el pipeline
ya produjo. Por construcción, P/R/F1 de existencia **no pueden** moverse. Un
resultado idéntico aquí es la confirmación de que el ensemble hace lo que dice
hacer y nada más.

### 4.2 Donde sí hay diferencia real y medible: la decisión

| Métrica | `baseline1` | `ensemble_offline` |
|---|---|---|
| `decision_correct` | 30.23 % (13/43) | **39.53 % (17/43)** |
| Confusión ACCEPT → ACCEPT | 9 | **13** |
| Confusión REJECT → ACCEPT (error grave) | 4 | **2** |

El ensemble acierta **4 decisiones más** y **reduce a la mitad** los casos en que
una relación que el ground truth marca REJECT se propone como ACCEPT. Ese es el
valor medido del Bloque 6: **calidad de decisión, no cobertura**.

### 4.3 Comparativa de los cuatro modos offline (dictámenes ya correctos)

| Modo | context_mode | P | R | F1 | pares | tasa humana | llamadas | dictamen |
|---|---|---|---|---|---|---|---|---|
| `baseline1` | sentence | 0.8269 | 0.7963 | 0.8113 | 52 | 38.5 % | 0 | APTO CON REVISION HUMANA TOTAL |
| `baseline2` | paragraph | 0.3611 | 0.9630 | 0.5253 | 144 | 52.8 % | 0 | APTO CON REVISION HUMANA TOTAL |
| `ensemble_offline` | sentence | 0.8269 | 0.7963 | 0.8113 | 52 | 38.5 % | 0 | APTO CON REVISION HUMANA TOTAL |
| `full_offline` | segment | 0.3611 | 0.9630 | 0.5253 | 144 | 52.8 % | 0 | APTO CON REVISION HUMANA TOTAL |

Antes de D7 las cuatro filas decían `NO APTO`. **Confirmado: la causa era
`check_determinism=False` en la construcción de la comparativa, no la calidad.**

### 4.4 Submuestra de 6 fuentes (`src-01`…`src-06`), offline

| Métrica | `baseline1` | `ensemble_offline` |
|---|---|---|
| Precisión / Recall / F1 | 0.7407 / 0.7692 / 0.7547 | 0.7407 / 0.7692 / 0.7547 |
| TP / FP / FN | 20 / 7 / 6 | 20 / 7 / 6 |
| Llamadas a proveedor | 0 | 0 |
| Fallos de transporte | 0 | 0 |
| Determinista | True | True |

> ### ⚠ ADVERTENCIA ESTADÍSTICA (obligatoria al leer cualquier cifra de submuestra)
>
> **Con ~25-26 candidatos, las diferencias pequeñas de F1 NO son estadísticamente
> significativas.** La submuestra sirve para (a) verificar que la tubería con
> proveedor **funciona** de extremo a extremo y (b) medir **coste y latencia**.
> **NO** sirve para declarar que un modelo es mejor que otro. Cualquier
> comparación de calidad entre modelos hecha sobre esta submuestra es inválida,
> por muy sugerente que parezca el número.

### 4.5 Gates vigentes en `main`

| Gate | Estado | Valor | Umbral |
|---|---|---|---|
| determinism (DURO) | PASS | - | - |
| workspace_contamination (DURO) | PASS | - | - |
| simple_relations | PASS | 0.9333 | 0.80 |
| evidence | PASS | 0.9070 | 0.80 |
| offsets | PASS | 0.9302 | 0.90 |
| negation | PASS | 1.0 | 0.80 |
| temporality | PASS | 0.7600 | 0.60 |
| rumors | PASS | 1.0 | 0.60 |
| **predicate_structural** | **FAIL** | **0.2558** | **0.50** |

**Único FAIL de calidad real: `predicate_structural`.** Temporalidad y rumores,
que fallaban en la versión anterior de `docs/50`, hoy pasan — efecto medible de
los Bloques 4 y 5.

### 4.6 Tests: 74 → 153 → 177 (ejecutados el 2026-07-21 por el agente de documentación)

| Alcance | Antes de ronda 3 | Ronda 3 | Ronda 4 |
|---|---|---|---|
| Tests **propios del bloque** (`test_relation_benchmark_block7*.py`) | 74 (3 ficheros) | 153 (4 ficheros: +79 en `…_round3.py`) | **177** (5 ficheros: +24 en `…_round4.py`) |
| Suite de `data-engine/app/tests` | 1166 | 1245 | **1269 passed**, 0 skipped, 0 xfailed, 0 xpassed |

Comandos exactos, desde `data-engine/app` con `PYTHONPATH=.`:

```bash
python3 -m pytest tests/test_relation_benchmark_block7.py \
    tests/test_relation_benchmark_block7_fixes.py \
    tests/test_relation_benchmark_block7_round2.py \
    tests/test_relation_benchmark_block7_round3.py \
    tests/test_relation_benchmark_block7_round4.py -q     # 177 passed
python3 -m pytest tests -q                                 # 1269 passed
```

> **Precisión sobre «la suite completa».** Los **1269** son el árbol
> `data-engine/app/tests`, que es donde vive este bloque, y ahí **no hay ningún
> skip ni xfail** (verificado ejecutando la suite el 2026-07-21). La suite del
> **repositorio entero** (los `testpaths` de `pytest.ini`: viewer, deploy,
> contracts, integration, e2e, wave2, wave2b) no se ha re-verificado en esta
> ronda; la cifra de **2000 passed / 3 skipped** citada en versiones previas de
> este informe corresponde a la ronda 3 y no se ha vuelto a comprobar tras la
> ronda 4.

## 5. Hallazgo transversal registrado (Bloques 1 y 2) — ahora CONFIRMADO

Queda constancia formal en `docs/50` §13.4 y aquí:

> Tanto Ollama (`qwen2.5:7b`) como NVIDIA (`meta/llama-3.1-70b-instruct`) producen
> texto de evidencia **VÁLIDO** pero **offsets de carácter INCORRECTOS**, y la
> validación estricta los rechaza con seguridad (`INVALID_RESPONSES`).

Hasta este bloque solo se había observado en **casos sintéticos**. La ejecución
real del §6 lo **confirma sobre el corpus**: 10 de 18 respuestas rechazadas por
`offsets_do_not_match_evidence`, `invalid_rate = 0.6667`, `results_strong = 0`.

**Consecuencia operativa:** la prioridad real siguiente es el **anclaje de
evidencia**, no cambiar de modelo ni relajar la validación. Ningún cambio de
proveedor arregla offsets que ningún proveedor produce bien — ni uno local de 7B
ni uno alojado de 70B.

## 6. Ejecución real acotada (Ollama) — MEDIDA el 2026-07-20

Ejecutada por el **Organizador** (este agente no abrió ninguna conexión: 0
llamadas, 0 sockets). Detalle completo en `docs/50` §12.

**Condiciones:** modo `ollama_shadow`, submuestra `src-01`…`src-06`, modelo
`qwen2.5:7b` (7,6 B, Q4_K_M, contexto 4096), Ollama local **en CPU, SIN GPU**
(`size_vram: 0`, `llama-server` a ~596 % de CPU), endpoint
`http://127.0.0.1:11434/v1/chat/completions`.

### 6.1 Coste y latencia reales — el resultado más útil del bloque

| Magnitud | Valor |
|---|---|
| Candidatos evaluados | 27 |
| Llamadas al LLM local | **18** (9 `SKIPPED`) |
| p50 / p95 / máx | **97 775 ms** / 159 269 ms / **175 690 ms** |
| Tiempo total (6 fuentes) | **1 680 219 ms ≈ 28 min** |
| Por candidato / por documento | 62 230 ms / 280 037 ms |
| `timeouts` / `errors` / fallos de transporte | 0 / 0 / **0** — las 18 se respondieron |

### 6.2 HALLAZGO: el timeout de entonces (180 s) era MARGINAL → hoy 300 s

El máximo observado, **175,7 s**, quedaba a **4,3 s** del valor de entonces
(`PROVIDER_LOCAL_TIMEOUT_S = 180`). Una llamada algo más lenta habría expirado y
el benchmark habría vuelto a medir un timeout en lugar de calidad — exactamente el
fallo de medición que §3.6 pretendía eliminar.

Y la medición **refutó la estimación que sostenía ese valor**: la cifra «p50 real
de Ollama 10-65 s», que este informe repetía en §2 y §3.6, procede de los casos
**sintéticos** de los Bloques 1 y 2. **El p50 real sobre el corpus es de 97,8 s:
casi el doble del extremo superior de esa estimación.**

**RIESGO CERRADO.** La recomendación de subir `PROVIDER_LOCAL_TIMEOUT_S` **se
aplicó en la ronda 2**: el valor vigente es **300 s** (≈ 175,7 s × 1,7, margen de
~124 s sobre el peor caso observado), con un deadline efectivo por llamada de
**330 s**. Ver §3.6 y §8.9.

### 6.3 Calidad: las 18 respuestas fueron RECHAZADAS por la validación estricta

`invalid_rate = 0.6667` (18/27), `human_rate = 0.3333` (9/27),
`results_strong = 0`, `results_partial = 0`, `results_conflict = 0`.

| Motivo del rechazo | Nº |
|---|---|
| `offsets_do_not_match_evidence` | **10** |
| `no_relation_extracted` | 7 |
| `evidence_not_in_document` | 1 |

**Esto confirma sobre el CORPUS REAL el hallazgo transversal de los Bloques 1 y
2** (§5), que hasta ahora solo se había observado en casos sintéticos. Refuerza la
conclusión: la prioridad siguiente es el **anclaje de evidencia**, no cambiar de
modelo ni relajar la validación.

### 6.4 Impacto en las métricas: NINGUNO, y es lo esperado

P/R/F1 con Ollama real = **0.7407 / 0.7692 / 0.7547** (TP 20, FP 7, FN 6),
**idénticos** a `baseline1` y `ensemble_offline` sobre la misma submuestra (§4.4).
El modo sombra **nunca decide**, así que no puede cambiar qué pares se extraen:
solo aporta señal de consenso. Que las cifras no se muevan es la **confirmación de
que la garantía de sombra se cumple**, no una decepción.

> **⚠ ADVERTENCIA ESTADÍSTICA:** 6 fuentes, 27 candidatos. Sirve para verificar
> que la tubería funciona y para medir **coste y latencia reales**; **NO** para
> comparar la calidad de modelos.

### 6.5 Recombinación validada con datos REALES

Se volcaron los 27 payloads y `--recombine-from` reprodujo el run con **0
llamadas** y P/R/F1 idénticos. La función no solo pasa tests sintéticos: **funciona
sobre respuestas reales del modelo**. Consecuencia práctica: **reanalizar estas
respuestas es gratis**, que es justo la contramedida al coste que justificaba el
diseño del bloque (§2).

### 6.6 NVIDIA: MEDIDA el 2026-07-21 — ver §6A

**Actualización de la ronda 4.** Cuando esta sección se escribió no se había
ejecutado NVIDIA por falta de clave de API. Con clave válida se ejecutó, y ese
primer intento **destapó el defecto `external_model`** (§3.20): las llamadas
fallaban con 404, disfrazadas de fallo de transporte. Corregido el defecto, la
ejecución real se documenta íntegra en la nueva §6A. **El alcance `PARCIAL` del
dictamen ya no es por NVIDIA no ejecutada**; el motivo que queda es
`determinism` no evaluado en la ruta CLI (§6A.5), documentado desde D7/§3.10.

### 6.7 Extrapolación de coste (ESTIMACIÓN, no medida)

6 fuentes → 28 min, luego las 16 del corpus ≈ **75 min** *solo* con Ollama, en
esta máquina y sin GPU. Extrapolación lineal, no medición. Coherente con la
estimación previa de **5-20 h** para una pasada completa con ambos proveedores y
repeticiones (§2).

### 6.8 Trazabilidad

El run se ejecutó con el código **PREVIO** a las correcciones D1-D7: el proceso ya
tenía los módulos cargados. La recombinación posterior sí se hizo con el código
corregido y **da lo mismo**. Se dice tal cual, sin adornarlo.

## 6A. Ejecución real acotada (NVIDIA) — MEDIDA el 2026-07-21, con el código de la ronda 4

Ejecutada tras corregir el defecto `external_model` (§3.20). Condiciones: modo
`nvidia_shadow`, submuestra `src-01`…`src-06` (**las mismas** que Ollama en §6),
`--external-model meta/llama-3.3-70b-instruct`, endpoint
`https://integrate.api.nvidia.com`.

### 6A.0 El defecto detectado por este mismo run, antes de corregirlo

El primer intento con clave real (antes de la ronda 4) fallaba con **404** en las 5
primeras llamadas, contabilizado como fallo de transporte 5/5 — el sintoma exacto
que predice §3.20. Esa falla **es** la evidencia empírica que motivó la ronda 4:
no se encontró leyendo código, se encontró **midiendo**. El modelo configurado por
el operador en el `EnvironmentFile` (`meta/llama-3.1-70b-instruct`) también resultó
estar **retirado** para inferencia (aparece en el listado de 118 modelos NIM del
healthcheck pero da 404 si se invoca); se usó `meta/llama-3.3-70b-instruct`,
vigente.

### 6A.1 Transporte y latencia — el resultado más útil de esta sección

| Magnitud | Valor |
|---|---|
| Candidatos evaluados / llamadas | 27 |
| Respondidas / errores de transporte / indeterminadas | **27 / 0 / 0** |
| `external_ai` / `local_llm` | `EXECUTED` / `NOT_EXECUTED` |
| `status_consistency` | `OK` |
| Atestación de endpoint | `https://integrate.api.nvidia.com` |
| `network` | `yes (27 llamadas a proveedor contabilizadas; 0 fallos de transporte)` |
| p50 / p95 / máx | **29 434 ms (~29,4 s)** / 89 354,6 ms (~89,4 s) / **125 862 ms (~125,9 s)** |
| Gate `provider_transport` | `PASS` |

Sin fugas de secretos: ningún prefijo `nvapi-` aparece en el JSON de resultados ni
en el JSONL de 27 payloads volcados.

### 6A.2 Comparación de latencia con Ollama (§6.1)

| Proveedor | p50 | Contexto |
|---|---|---|
| Ollama (`qwen2.5:7b`, local) | **97 775 ms (~97,8 s)** | CPU sin GPU |
| NVIDIA (`meta/llama-3.3-70b-instruct`, alojado) | **29 434 ms (~29,4 s)** | infraestructura NIM |

NVIDIA respondió con p50 unas 3,3x más rápido; esperable dado que sirve el modelo
en infraestructura dedicada frente al Ollama local en CPU. No es una afirmación
sobre "calidad de modelo", solo de latencia de transporte.

### 6A.3 Impacto en las métricas: NINGUNO — sombra confirmada con un SEGUNDO proveedor real

P/R/F1 = **0.7407 / 0.7692 / 0.7547** (TP 20, FP 7, FN 6): **idénticos** a
`baseline1`, `ensemble_offline` y a la ejecución real de Ollama (§6.4) sobre la
misma submuestra. Dos proveedores completamente distintos — 7B local y 70B
alojado — dan el mismo P/R/F1: confirmación reforzada de que el modo sombra
**nunca decide, aprueba ni escribe**.

### 6A.4 Calidad: 27/27 rechazadas, pero por un motivo UNIFORME — no es "NVIDIA peor que Ollama"

`invalid_rate = 1.0` (27/27). Las 27 respuestas fueron rechazadas por la
validación estricta, y **las 27 con el mismo marcador exacto**:
`evidence_text vacía o ausente` (verificado leyendo `validation_errors` en los 27
registros del JSONL). Un fallo 100% uniforme en el mismo campo apunta a un
desajuste sistemático de **contrato/prompt** entre lo que el modelo devuelve y lo
que el validador exige — **no** a incapacidad del modelo para razonar sobre
relaciones.

| Proveedor | Modelo | Rechazo | Motivo(s) |
|---|---|---|---|
| Ollama | `qwen2.5:7b` (7,6B, local) | 18/27 (66,7%) | `offsets_do_not_match_evidence` (10), `no_relation_extracted` (7), `evidence_not_in_document` (1) |
| NVIDIA | `meta/llama-3.3-70b-instruct` (70B, alojado) | 27/27 (100%) | `evidence_text vacía o ausente` (27/27, uniforme) |

Son manifestaciones **distintas** del **mismo** hallazgo transversal (§5): el
anclaje de evidencia al contrato del validador. Ollama devuelve evidencia con
offsets incorrectos; NVIDIA a menudo no devuelve el campo en absoluto. Ningún
cambio de modelo lo arregla — 7B y 70B fallan por la misma raíz —; la corrección
vive en el prompt/contrato de `pipeline.py`, **fuera del alcance del Bloque 7**.

### 6A.5 Veredicto y alcance

`APTO CON REVISION HUMANA TOTAL`, `verdict_scope: PARCIAL (gates duros no
evaluados: determinism)` — mismo motivo que en la comparativa offline (§4.3,
D7/§3.10): la ruta CLI no evalúa determinismo en modos con proveedor. **No** por
NVIDIA sin ejecutar.

### 6A.6 Comparación honesta: no forzar equivalencia llamada-a-llamada

Ollama hizo 18 llamadas (9 `SKIPPED`) sobre las 6 fuentes; NVIDIA hizo 27 sobre
las **mismas** fuentes. La diferencia depende de cómo cada carril del pipeline
(local vs externo) genera candidatos, no del proveedor: no se compara llamada a
llamada. Sí es comparable, y se compara: P/R/F1 (idénticos), transporte (ambos
sanos), latencia (dato propio de cada carril) y tipo de rechazo de calidad
(distinto, misma raíz).

### 6A.7 Trazabilidad

Corpus, ground truth y `code_sha` idénticos a §6. A diferencia del run de Ollama
(ejecutado con código previo a D1-D7), **este run se ejecutó ya con el código
corregido de la ronda 4**, incluida la guarda `require_external_model`.

## 7. Garantías de seguridad verificadas

- **Sin proveedores reales en las mediciones offline** (§4): `local_llm =
  NOT_EXECUTED`, `external_ai = NOT_EXECUTED`, `network = none`,
  `total_calls = 0`. La única ejecución con proveedor es la del §6, la lanzó el
  Organizador con la doble llave concedida, y también fue **modo sombra,
  dry-run, sin escrituras**: `results_strong = 0`, ninguna relación aprobada.
- **Doble llave de la CLI verificada en vivo** en los dos sentidos del fallo
  (falta la bandera, falta la variable), abortando antes de abrir red. Desde la
  ronda 2 la barrera principal es del **núcleo** (`authorize_provider_run`,
  §3.12), y la doble llave **no se exige** cuando el llamante inyecta los
  proveedores.
- **Import perezoso** de `providers.py`: en modo offline el módulo con el código
  de red ni siquiera se importa.
- **Fallo cerrado sin endpoint**: `build_local_transport` lanza `BenchmarkError`
  sin abrir socket si no hay `--local-endpoint` ni `S9K_BENCH_OLLAMA_ENDPOINT`.
- **Sin escritura**: dry-run, sin Neo4j. Los únicos ficheros escritos son las
  salidas explícitas (`--out-json/--out-jsonl/--out-md/--out-payloads`), volcadas
  a `/tmp` durante la medición.
- **Determinismo**: `deterministic = True` (hashes, métricas y predicciones
  idénticas entre dos ejecuciones) en corpus completo y en submuestra, en ambos
  modos.
- **Sin secretos**: no se imprimió ni se almacenó ninguna clave. El proveedor
  externo se **construye explícitamente** (`build_external_provider`, §3.13),
  exigiendo API key y validando `base_url`, y falla **cerrado** sin ella; el
  núcleo **ya no delega** su resolución en el registry. La atestación de endpoint
  publica solo `esquema://host:puerto`, sin credenciales ni ruta. **Ronda 3
  (N5):** además, **ninguna rama de validación de endpoint vuelca la URL cruda a
  stderr** — antes, un endpoint con credenciales y sin host las imprimía enteras,
  y en CI un `S9K_NVIDIA_BASE_URL` mal escrito es un error humano plausible.
- **El destino ya no puede venir de un entorno no nombrado (N13)** ni depender del
  directorio de invocación (N12): `build_local_transport` exige endpoint explícito
  y `_REPO_ROOT` se deriva del módulo, no de `Path.cwd()`.
- **El endurecimiento de red no se puede desactivar parcheando un global (N6):**
  el opener que bloquea redirecciones entre orígenes se usa siempre; la costura de
  test es explícita.
- **CI intacto**: los modos con proveedor están fuera de `MODES`, que es lo que
  iteran `--all-modes` y los tests.
- **Transporte sano**: `transport_error_rate = 0.0` y `total_errors = 0`. En las
  mediciones offline, trivialmente (no hay llamadas); **en la ejecución real del
  §6, de verdad**: las 18 llamadas se respondieron, 0 timeouts, 0 errores, con el
  umbral de aborto del 10 % activo.
- **Alcance del dictamen declarado**: `verdict_scope = COMPLETO` en las
  mediciones publicadas; `PARCIAL (gates duros no evaluados: determinism)`
  verificado en vivo con `--no-determinism`, que es exactamente lo que debe
  aparecer cuando la comprobación no se hace.
- **Guard de `--all-modes` antes del gasto**: con modo de proveedor aborta antes
  de construir transportes y de cargar el corpus.

## 8. Discrepancias y riesgos detectados

1. **`docs/50` es a la vez fichero generado y documento curado.**
   `cli.render_markdown` escribe ese fichero si se le pasa
   `--out-md docs/50-relation-benchmark-results.md`, y al hacerlo **destruiría**
   las secciones curadas (modos, doble llave, cómo se ejecuta, límites). Queda
   avisado dentro del propio `docs/50` §8. Corregirlo de verdad exige tocar
   `cli.py`, que está **fuera del alcance** de este agente. **Sigue abierto.**
2. ~~**`all_modes` reporta `verdict = "NO APTO"` para todos los modos.**~~
   **CORREGIDO (D7).** La causa era la que se diagnosticó: `cli.main` construye la
   comparativa con `build_report(..., check_determinism=False)`, el gate DURO
   `determinism` quedaba en `None` y contaba como FAIL. Hoy ese estado es
   `NOT_EVALUATED`, no participa en el dictamen y el alcance se declara en
   `verdict_scope`. Verificado: las cuatro filas reportan su dictamen real
   (§4.3).
3. **Los contadores operativos de `ensemble_offline` son los del consenso BASE.**
   `metrics.aggregate_operational` suma el `summary` del pipeline, así que
   `results_strong/partial/conflict/human`, `human_rate` y `conflict_rate` **no
   reflejan la recalibración del ensemble** (de ahí que la comparativa muestre
   38.5 % de tasa humana idéntica en `baseline1` y `ensemble_offline`). El efecto
   del ensemble se ve en las predicciones y en `decision_correct`. Documentado
   como límite conocido en `docs/50` §13.5. **Sigue abierto.**
4. **Matiz sobre el timeout, vigente tras la subida a 300 s.**
   `LocalLLMConfig.timeout` **sigue valiendo 30 s**: el pipeline construye su
   `LocalLLMConfig` internamente y **no** es configurable desde el benchmark. Los
   **300 s** son el timeout **del transporte inyectado**, que es el que gobierna
   la espera efectiva. Si algún día se dejara de inyectar transporte, volverían a
   regir los 30 s.
5. **Ficheros de test escritos por otro agente.** `git status` muestra **cuatro**
   ficheros sin seguimiento creados por el agente implementador:
   `test_relation_benchmark_block7.py`, `…_block7_fixes.py`, `…_block7_round2.py`
   y `…_block7_round3.py`. Este agente **no los ha escrito ni modificado**; a
   diferencia de rondas anteriores **sí los ha ejecutado** para verificar los
   números publicados en §4.6 (153 propios, 1245 en `data-engine/app/tests`). Que
   pasen **no es un juicio sobre su calidad ni sobre su cobertura**: no se ha
   auditado si los *mutation checks* cubren todo lo que dicen cubrir, y eso sigue
   correspondiendo al supervisor.
6. **El umbral de transporte del 10 % no está calibrado con datos reales.** Es
   una elección de diseño razonada (§3.9); no existe serie de tasas de fallo
   medidas contra VM105 que lo respalde. Debe revisarse cuando la haya.
7. ~~**La ruta del proveedor externo (NVIDIA) sigue SIN EJECUTAR**~~ **CORREGIDO
   y MEDIDO en la ronda 4 (§6A).** El primer intento con clave real destapó el
   defecto `external_model` (§3.20: placeholder enviado a NVIDIA → 404 → abortado
   disfrazado de fallo de infraestructura). Corregido, la ejecución real dio 27
   llamadas / 27 respondidas / 0 fallos de transporte, P/R/F1 idénticos a offline
   y a Ollama. Lo que queda abierto de NVIDIA no es la ejecución sino la
   **calidad**: 27/27 respuestas rechazadas por `evidence_text vacía o ausente`
   (§6A.4) — la misma limitación transversal de evidencia que Ollama (punto 4 de
   §13 en `docs/50`), no un defecto de infraestructura.
8. **Las correcciones están validadas offline, con transporte inyectado.** Contra
   infraestructura real solo hay dos cosas: la comprobación manual del endpoint
   (404 con `…/v1`, 200 en ~3,9 s normalizado) y la ejecución del §6, que **se
   lanzó con el código PREVIO a las correcciones** (el proceso ya tenía los
   módulos cargados). La recombinación posterior sí usó código corregido y dio el
   mismo resultado. El manifiesto de procedencia (§3.16) es **posterior** a ese
   run. Ni este informe ni `docs/50` afirman nada más.
9. ~~**RIESGO ABIERTO — el timeout local de 180 s es MARGINAL.**~~ **CERRADO en
   la ronda 2.** `PROVIDER_LOCAL_TIMEOUT_S = **300**` (≈ 175,7 s × 1,7; margen de
   ~124 s sobre el peor caso medido), deadline efectivo por llamada **330 s**. La
   estimación «p50 10-65 s» está refutada y ya no sostiene ningún valor del
   código. Queda la advertencia de fondo: la latencia medida es de una máquina
   **sin GPU**; otra configuración dará otro perfil y el margen debe fijarse sobre
   el peor caso esperado, no sobre este.
10. ~~**No existe deadline GLOBAL de run.**~~ **CERRADO en la ronda 3** con
    `--max-run-seconds` (N11). **Lo que queda abierto es más estrecho:** el
    presupuesto es **opcional** (sin bandera no hay tope global) y su granularidad
    es **por fuente**, así que una única fuente muy lenta puede rebasarlo antes de
    la siguiente comprobación. El deadline **por llamada** sigue siendo 330 s.
11. **La atestación de red en modo con proveedor es INCOMPLETA, nunca falsa.**
    Puede publicar `yes (proveedores ejecutados)` con `network_calls_counted: 0`.
    Afirma red del lado conservador, pero **no prueba el número de llamadas**.
    **Sigue abierto.**
12. **`status_consistency`: una de sus dos direcciones sigue siendo código
    muerto.** *Corrección de este informe:* decir que el mecanismo **entero** era
    inalcanzable **ya no es exacto**. Tras N8, la dirección «`EXECUTED` con 0
    llamadas contabilizadas» **sí ocurre** en runs reales y se declara; la
    dirección «llamadas sin ningún `EXECUTED`» sigue siendo **inalcanzable** —
    código defensivo, no una mitigación activa, y no debe presentarse como control
    efectivo.
13. **La causa raíz de `provider_error` sigue viva y FUERA de alcance.** El
    `except _PROVIDER_ERRORS` de `relations/external_ai_shadow.py` sigue agrupando
    `InvalidResponseError` con los errores de red, y **no se ha tocado**. El
    bloque **mitiga** el efecto leyendo el nombre de la excepción (§3.17); cuando
    el nombre no basta, la llamada queda **INDETERMINADA** y el benchmark lo
    **publica** en vez de decidir por su cuenta. **Esa zona gris es una limitación
    abierta**, y cerrarla exige tocar `external_ai_shadow.py`: otro bloque.
14. **El manifiesto de payloads no acredita autenticidad sin clave de operador**
    (§3.18). Sin `S9K_BENCH_MANIFEST_HMAC_KEY`, cualquiera con el repositorio
    puede emitir un manifiesto válido, y nada prueba que los payloads procedan de
    llamadas reales a un proveedor. **Abierto por diseño**, no por descuido: el
    informe lo declara en lugar de prometer procedencia.

## 9. Qué queda FUERA de este bloque

- **Ninguna ejecución con proveedor real por parte de este agente.** Las de §6
  (Ollama) y §6A (NVIDIA) las ejecutó el Organizador.
- **Sin pasada completa con proveedor.** Solo la submuestra de 6 fuentes en ambos
  proveedores; el corpus completo con Ollama se estima en ~75 min (§6.7) y no se
  ha ejecutado con ninguno de los dos proveedores.
- ~~**NVIDIA no ejecutada**~~ **NVIDIA MEDIDA (§6A, ronda 4)** con 27 llamadas
  reales, 0 fallos de transporte. Lo que sigue abierto: sus 27 respuestas fueron
  rechazadas por calidad (`evidence_text vacía o ausente`, §6A.4) — corrección de
  contrato/prompt fuera del alcance de este bloque, no un defecto de ejecución.
- **Sin calibración empírica del umbral de transporte, ni agregado ni por
  proveedor.** El umbral por carril **existe** desde la ronda 3 (N2); lo que no
  existe es una serie de medidas reales que fije el 10 %.
- **Sin presupuesto global de run por defecto:** `--max-run-seconds` es opcional y
  se comprueba entre fuentes (§8.10).
- **Sin corregir la causa raíz de `provider_error`** en
  `relations/external_ai_shadow.py`: fuera de alcance, solo mitigado (§8.13).
- **Sin autenticidad de los payloads recombinables** salvo que el operador
  configure la clave HMAC (§8.14).
- **Sin recalibración empírica de pesos del ensemble.** Los perfiles de
  `default-1.0.0` siguen siendo el punto de partida del Bloque 6. Este bloque
  aporta la **infraestructura de medición** para recalibrar; la recalibración en
  sí no se hizo.
- **Sin cableado del ensemble en `run_pipeline`.** Sigue siendo una capa
  disponible, no camino crítico.
- **Sin caché en la ruta de relaciones.** Se documenta su ausencia y se mitiga con
  `--out-payloads`/`--recombine-from`; implementarla es otro bloque.
- **Sin commit, sin push, sin PR, sin tag.**

## 10. Estado de producción

Intacta. No se tocó VM105, Neo4j, `auth.db`, `jobs.db`, timers ni servicios. No se
ejecutó ninguna ingesta. La ejecución real del §6 fue contra un **Ollama local**,
y la del §6A contra **NVIDIA real** (`https://integrate.api.nvidia.com`); ambas en
modo sombra y dry-run: sin escrituras, sin Neo4j y sin ninguna relación aprobada
(`results_strong = 0` en las dos). La clave de API de NVIDIA no se imprimió ni se
serializó en ningún artefacto (verificado: sin `nvapi-` en JSON/JSONL).
`S9K_ALLOW_REAL_INGEST = off`. Ingestas reales: 0.
Reinicios: 0. `release/rc6-candidate = 15ae1d4f364b19e601bbe32a5e3904e889c8bf65`
(**inmutable**, no tocado; la rama no existe en este worktree). Tag RC6 = **no
creado**. Release RC6 = **no creada**. Despliegue RC6 = **no realizado**.

## 11. Reproducción

```bash
export PYTHONPATH="$PWD/data-engine/app"
cd data-engine/app

# Corpus completo + comparativa de modos offline
python -m relations.benchmark.cli --mode baseline1 --all-modes \
    --out-json /tmp/b7_baseline1.json --out-md /tmp/b7_baseline1.md

# Ensemble calibrado B6, offline
python -m relations.benchmark.cli --mode ensemble_offline --out-json /tmp/b7_ens.json

# Submuestra de 6 fuentes
python -m relations.benchmark.cli --mode baseline1 \
    --sources src-01,src-02,src-03,src-04,src-05,src-06 --out-json /tmp/b7_sub_b1.json
python -m relations.benchmark.cli --mode ensemble_offline \
    --sources src-01,src-02,src-03,src-04,src-05,src-06 --out-json /tmp/b7_sub_ens.json
```

Ejecución con proveedor real — **doble llave obligatoria**, ~28 min en CPU sin
GPU, con volcado de payloads para recombinar después sin coste. Receta equivalente
a la del §6 (el run lo lanzó el Organizador; aquí se reconstruye a partir de las
condiciones declaradas y de las opciones reales de la CLI):

```bash
S9K_BENCH_PROVIDERS=1 python -m relations.benchmark.cli \
    --mode ollama_shadow --enable-providers \
    --local-endpoint http://127.0.0.1:11434/v1/chat/completions \
    --local-model qwen2.5:7b \
    --sources src-01,src-02,src-03,src-04,src-05,src-06 \
    --out-json /tmp/b7_ollama.json --out-payloads /tmp/b7_payloads.jsonl

# Recombinación offline de esas MISMAS respuestas: 0 llamadas.
# Requiere el manifiesto /tmp/b7_payloads.jsonl.manifest.json que emite
# --out-payloads (o indicar otro con --recombine-manifest); sin él NO recombina.
python -m relations.benchmark.cli --recombine-from /tmp/b7_payloads.jsonl \
    --out-json /tmp/b7_recombine.json
```

Receta equivalente para NVIDIA (§6A), **posterior a la ronda 4**: requiere
`--external-model` con un id real — sin él, `require_external_model` (§3.20)
aborta antes de tocar red con un error de CONFIGURACIÓN:

```bash
S9K_BENCH_PROVIDERS=1 python -m relations.benchmark.cli \
    --mode nvidia_shadow --enable-providers \
    --external-model meta/llama-3.3-70b-instruct \
    --sources src-01,src-02,src-03,src-04,src-05,src-06 \
    --out-json /tmp/b7_nvidia.json --out-payloads /tmp/b7_nvidia_payloads.jsonl
```

Notas:

- El timeout vigente del transporte local es de **300 s** (deadline efectivo por
  llamada, **330 s**); el run del §6 se ejecutó cuando eran 180 s.
- Desde la ronda 3 conviene añadir un presupuesto **global** al run con proveedor,
  p. ej. `--max-run-seconds 5400` (N11, §3.19): sin él no hay tope de tiempo para
  la pasada entera.
- Desde la ronda 4, `--external-model` es **obligatorio de facto** para
  `nvidia_shadow`/`ensemble_full`: sin él (ni `S9K_NVIDIA_REVIEW_MODELS`
  definido), el run aborta con un `BenchmarkError` de configuración, no con un
  404 disfrazado de fallo de transporte (§3.20).

Tests (§4.6), desde `data-engine/app` con `PYTHONPATH=.`:

```bash
python3 -m pytest tests/test_relation_benchmark_block7.py \
    tests/test_relation_benchmark_block7_fixes.py \
    tests/test_relation_benchmark_block7_round2.py \
    tests/test_relation_benchmark_block7_round3.py \
    tests/test_relation_benchmark_block7_round4.py -q     # 177 passed
python3 -m pytest tests -q                                 # 1269 passed, sin skips
```

## 12. Checkpoint (borrador — campos de proceso a rellenar por el Organizador)

```text
CHECKPOINT — BLOQUE 7

Bloque: 7 — Reejecución del benchmark
Objetivo: reejecutar el benchmark sobre el ensemble calibrado (B6) sin coste de proveedor
Estado: IMPLEMENTING (implementación offline completa tras la ronda 3, CERRADA y congelada;
        ejecución real acotada con Ollama REALIZADA y documentada; NVIDIA MEDIDA en la ronda 4
        tras corregir el defecto external_model -> alcance del dictamen PARCIAL SOLO por
        determinism no evaluado en la ruta CLI, no por NVIDIA)
Auditoría: código leído y cifras reproducidas por el agente de documentación tras cada ronda
           (última resincronización: 2026-07-21, ronda 4)
Rama: test/relation-calibrated-benchmark-v1
Worktree: /home/ia02/worktrees/test-relation-calibrated-benchmark-v1
PR: pendiente (sin commit ni push en este bloque)
Head: 1df631d (base; sin commits nuevos)
Merge commit: pendiente
Tests específicos: 177 passed (CINCO ficheros sin seguimiento del agente implementador:
                   test_relation_benchmark_block7.py, ..._block7_fixes.py, ..._block7_round2.py,
                   ..._block7_round3.py, ..._block7_round4.py; 153 de rondas 1-3 + 24 de la
                   ronda 4). NO escritos por el agente de documentación, que sí los ejecutó
                   el 2026-07-21; cobertura sin auditar
Tests globales: 1269 passed en data-engine/app/tests, sin skips ni xfails (antes de la ronda 4: 1245;
                antes de la ronda 3: 1166). Repositorio entero (testpaths de pytest.ini) NO
                re-verificado en la ronda 4; la cifra de 2000 passed / 3 skipped es de la ronda 3
                y no se ha vuelto a comprobar
Mutation checks: declarados en ..._block7_round3.py (N1 umbral intermedio, N2 solo agregado,
                 N4 criterio por inyección, N6 costura ignorada, N13 fallback al entorno,
                 B1 InvalidResponseError como transporte, B1 indeterminado colapsado,
                 B3 code_sha sin contrastar / inventado) y ..._block7_round4.py (guarda del
                 placeholder external-model reintroducido). Ejecutados en verde; NO auditados
                 por el agente de documentación
CI de PR: pendiente
CI post-merge de main: pendiente
Supervisor: pendiente
Hallazgos: ensemble no mueve P/R/F1 (por construcción) pero sube decision_correct 30.23% -> 39.53%
           y baja REJECT->ACCEPT de 4 a 2; único FAIL de calidad = predicate_structural 0.2558;
           Ollama real (6 fuentes, CPU sin GPU): p50 97,8 s / máx 175,7 s / 28 min, 0 timeouts,
           18/18 respuestas RECHAZADAS (10 por offsets), invalid_rate 0.6667, P/R/F1 sin cambio;
           NVIDIA real (ronda 4, mismas 6 fuentes, meta/llama-3.3-70b-instruct): 27/27 respondidas,
           0 fallos de transporte, p50 29,4 s / p95 89,4 s / máx 125,9 s, 27/27 rechazadas TODAS por
           "evidence_text vacía o ausente" (invalid_rate 1.0), P/R/F1 IDÉNTICOS a Ollama y a offline
           (0.7407/0.7692/0.7547) -> confirma la garantía de sombra con un SEGUNDO proveedor real;
           el modelo del EnvironmentFile del operador (llama-3.1-70b-instruct) está RETIRADO (404);
           timeout de 180 s MARGINAL (4,3 s de margen) y estimación previa "p50 10-65 s" REFUTADA
           -> CERRADO en ronda 2 subiéndolo a 300 s (deadline efectivo por llamada 330 s);
           recombinación validada con datos reales (0 llamadas, mismo P/R/F1);
           vías a red sin autorización cerradas en el núcleo (B1: 5-10 conexiones reales
           demostradas vía registry) y atestación de red que decía "none" tras 5 POST (B2);
           defecto external_model (ronda 4): nvidia_shadow nunca fijaba un id de modelo real,
           enviaba el placeholder "external-model" -> 404 -> abortado disfrazado de fallo de
           INFRAESTRUCTURA; invisible mientras NVIDIA figuraba "no ejecutada" y con los revisores
           sin poder llamar a la red real; encontrado SOLO al medir con clave real
Correcciones: RONDA 1 -- bloque `providers` derivado de provider_status (antes literal falso);
              timeout del LLM local 30 s -> 180 s; D1 transporte vs calidad + aborto al 10%
              (fail-fast); D2 normalización de endpoint (18x404 -> 200 en ~3,9 s);
              D3 provider_status en raíz; D4 guard de --all-modes antes de gastar;
              D5 run_cli con salida 2; D6 alias local_calls/external_calls;
              D7 determinism NOT_EVALUATED + verdict_scope (arregla el "NO APTO" de all_modes).
              RONDA 2 -- B1 authorize_provider_run: llave en el NÚCLEO, sin delegar en el registry
              (la doble llave NO se exige si el llamante inyecta los proveedores);
              B2 gate DURO provider_transport (PASS/PARTIAL/FAIL/NOT_MEASURED) + dictamen
              "SIN DICTAMEN: PROVEEDOR NO MEDIDO" + verdict_scope "NO MEDIDO" + status_consistency
              + atestación de red derivada de llamadas contabilizadas;
              B3 strict_small_sample (la muestra pequeña ENDURECE, no perdona);
              B4 manifiesto de procedencia obligatorio para --out-payloads/--recombine-from;
              B5 validación y atestación de endpoint (esquema/host/credenciales);
              N2 tope de lectura 1 MiB + deadline de reloj de pared + redirecciones entre
              orígenes bloqueadas; N5 build_external_provider construye de verdad y falla cerrado;
              timeout 180 -> 300 s sobre la latencia MEDIDA.
              RONDA 3 (CERRADA) -- B1 provider_error deja de ser sinónimo de transporte: TRES
              categorías disjuntas (TRANSPORT / RESPONDED / INDETERMINATE) resueltas por el nombre
              de la excepción que el payload ya escribe; la causa raíz (except _PROVIDER_ERRORS de
              relations/external_ai_shadow.py) queda FUERA DE ALCANCE y SIN TOCAR, y lo indeterminado
              se PUBLICA (bloque indeterminate + indeterminate_latency + gate PARTIAL) en vez de
              inventarse; B3 el manifiesto pasa a ser INTEGRIDAD, NO AUTENTICIDAD: corpus_hashes no
              vacío que cubre EXACTAMENTE los source_ids, code_sha igual al del proceso que recombina
              (guard de code_sha indeterminable comprobado ANTES de la igualdad), HMAC opcional del
              operador como única fuente de autenticidad -- motivado por una falsificación real de
              manifiesto con valores públicos del repo que dio P=R=F1=1.0 con rc=0;
              N1 umbral efectivo = documentado (min_rate_sample=20 en intermedias, min_calls en la
              final); N2 tasa POR CARRIL además de agregada; N3 PARTIAL de transporte declarado en
              verdict_scope; N4 should_watch_transport aislado con mutation check; N5 credenciales
              validadas antes que el host y sin volcar la URL a stderr; N6 costura de urlopen
              explícita (parchear el global ya no desactiva el bloqueo de redirecciones);
              N7 provider_fail_closed publicado y degradando el gate; N8 status_consistency en las
              DOS direcciones; N9 puerto 0 rechazado + IPv6 con corchetes + query preservada;
              N10 puerto fuera de rango -> BenchmarkError (código 2, no ValueError con rc=1);
              N11 deadline GLOBAL de run (--max-run-seconds) comprobado entre fuentes;
              N12 _REPO_ROOT derivado del módulo en vez de Path.cwd();
              N13 endpoint local EXPLÍCITO, sin fallback implícito al entorno
              RONDA 4 -- defecto external_model descubierto MIDIENDO NVIDIA con clave real (el
              404 disfrazado de fallo de transporte que produjo el placeholder): nuevo flag
              --external-model en cli.py; threading explícito hasta PipelineConfig.external_model
              vía run_benchmark -> run_source -> _config_for_mode; guarda fail-closed
              require_external_model (aborta con BenchmarkError de CONFIGURACIÓN, antes de tocar
              red, si el modo con IA externa corre sin modelo real o con el placeholder); invocada
              desde la API pública (run_source/run_benchmark), no solo desde la CLI; cubre también
              ensemble_full. Ejecución real de NVIDIA resultante: 27 llamadas, 0 fallos de
              transporte, P/R/F1 idénticos a Ollama y a offline
Riesgos residuales: ver §8 (docs/50 sobrescribible por --out-md; contadores operativos de
                    ensemble_offline son del consenso base; umbral 10% sin calibrar con datos
                    de VM105; correcciones validadas solo offline (Ollama) o con el código YA
                    corregido (NVIDIA, ronda 4) y el run de Ollama se lanzó con el código previo
                    a las correcciones (rondas 2 y 3 son posteriores a ESE run, no al de NVIDIA);
                    el deadline global existe pero es OPCIONAL y de granularidad por fuente;
                    la atestación de red es INCOMPLETA aunque nunca falsa; de status_consistency
                    solo una de las dos direcciones es alcanzable (la otra es código defensivo);
                    la causa raíz de provider_error sigue viva en relations/external_ai_shadow.py,
                    fuera de alcance: el bloque solo la MITIGA y publica lo INDETERMINADO;
                    el manifiesto no acredita autenticidad sin clave HMAC del operador; NVIDIA
                    real rechazó 27/27 respuestas por "evidence_text vacía o ausente" -- misma
                    limitación transversal de anclaje de evidencia que Ollama, corrección de
                    contrato/prompt en pipeline.py FUERA de alcance de este bloque)
Producción: intacta (los runs con Ollama y con NVIDIA fueron en sombra/dry-run, results_strong = 0
            en ambos; clave de API de NVIDIA nunca impresa ni serializada)
Neo4j: 199 nodos / 140 relaciones (sin cambios)
Ingestas: 0
S9K_ALLOW_REAL_INGEST: off
release/rc6-candidate: 15ae1d4f364b19e601bbe32a5e3904e889c8bf65 (inmutable)
Tag RC6: no creado
Release RC6: no creada
Despliegue: no realizado
Main final: pendiente
Autorización del siguiente bloque: <!-- PENDIENTE: decisión del Organizador -->
```
