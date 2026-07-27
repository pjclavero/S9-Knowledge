# 50 - Benchmark de extraccion de relaciones: resultados

**Ultima medicion: 2026-07-21 (NVIDIA real, submuestra de 6 fuentes).**
**Ultima resincronizacion con el codigo: 2026-07-21, tras la ronda 4
(defecto `external_model` corregido).** El documento describe el codigo
congelado tras **ronda 1** (D1-D7), **ronda 2** (B1-B5, N2, N5), **ronda 3**
(B1/B3 + N1-N13) y **ronda 4** (guarda `require_external_model` + flag
`--external-model` + medicion real de NVIDIA). Sustituye por completo a las
versiones anteriores, que describian un contrato ya superado.

> **NVIDIA ya NO figura como "no ejecutado".** Con clave de API valida se
> midio de verdad el carril externo (§12A). Antes de esa medicion existia un
> defecto real que lo impedia (§7A/§12A.0): el preset `nvidia_shadow` nunca
> fijaba un id de modelo real, asi que el carril enviaba el placeholder
> `"external-model"` a NVIDIA, que respondia 404, y el run abortaba
> **disfrazado de fallo de infraestructura**. Los revisores no podian verlo
> porque tenian prohibido llamar a NVIDIA de verdad; solo midiendo con clave
> real salio a la luz. Corregido en la ronda 4.

Ejecucion del pipeline R8 **REAL** (`relations.pipeline.run_pipeline`) sobre el
corpus B1 **REAL** (`data-engine/app/tests/data/relation_benchmark/`), comparado
contra el ground truth. El runner NO reimplementa ninguna etapa de R8 ni simula
resultados. El plan, el criterio de emparejamiento y la derivacion de entidades se
documentan en `docs/41-relation-benchmark-plan.md`.

> **Vigencia.** La ronda 3 ha **CERRADO** y el codigo esta congelado. Las tres
> cosas que la version anterior de este documento marcaba «EN CURSO» estan
> **resueltas** y se describen en su estado final: clasificacion de
> `provider_error` (§5.2), manifiesto de procedencia (§7) y umbral **por
> proveedor** (§5.3). La **ronda 4** es posterior y puntual: corrige el defecto
> `external_model` (§7A) y añade la medicion real de NVIDIA (§12A). Lo que sigue
> abierto esta en §13, sin banderas de «en curso».

## 0. Que es MEDIDO y que es DESCRIPTIVO en este documento

| Seccion | Naturaleza |
|---|---|
| 1-8 (contrato: modos, autorizacion, endpoint, transporte, gates, payloads, ejecucion) | **Descriptivo** — leido del codigo, verificado el 2026-07-21 |
| 9, 10, 11 (cifras offline) | **MEDIDO el 2026-07-20**, offline, sin proveedores; **reproducido identico el 2026-07-21** sobre el codigo de la ronda 3 |
| 12 (ejecucion real con Ollama) | **MEDIDO el 2026-07-20** contra un Ollama REAL |
| 12A (ejecucion real con NVIDIA) | **MEDIDO el 2026-07-21** contra NVIDIA REAL (`meta/llama-3.3-70b-instruct`), tras corregir el defecto `external_model` (ronda 4) |
| 13 (limites) | Descriptivo |

Salvo la **§12**, todas las cifras proceden de ejecuciones **offline**:
`provider_status = {local_llm: NOT_EXECUTED, external_ai: NOT_EXECUTED}`, red
`none`, `network_calls_counted: 0`, escrituras `none (dry-run, sin Neo4j)`, **0
llamadas**, **0 fallos de transporte**, `verdict_scope = COMPLETO`.

Trazas de la medicion:

- Pipeline: `relation-pipeline-1.0.0`
- Corpus v1.0.0: 16 fuentes, 54 relaciones de ground truth
- Ground truth sha256: `15973d1837deb29ea339bca6bb3980d62e07ef283b196bf38d0d1e2653d9cc5c`
- Versiones: `{"consensus": "relation-consensus-1.0.0", "contract": "internal-1.0.0", "pipeline": "relation-pipeline-1.0.0", "prompts": "1.0", "signals": "relation-signals-1.0.0", "syntax": "relation-syntax-1.0.0", "template": "1.0.0"}`
- Determinismo (2 ejecuciones): **True**

## 1. Modos disponibles

### 1.1 Modos OFFLINE (`runner.MODES`) — CI-safe, jamas abren red

| Modo | `context_mode` | Consenso | Descripcion |
|---|---|---|---|
| `baseline1` (**por defecto, modo del dictamen**) | `sentence` | base (`consensus_adapter`) | par en la misma frase; el mas restrictivo |
| `baseline2` | `paragraph` | base | par en el mismo parrafo |
| `full_offline` | `segment` | base | cualquier par del segmento |
| `ensemble_offline` | `sentence` | **recalibrado con `relations.ensemble` (B6)** | identico a `baseline1` salvo el consenso, recalibrado por post-proceso |

`ensemble_offline` aplica el ensemble sobre las señales, la sintaxis y los
payloads que el pipeline **ya** produjo (`extract_predictions_ensemble`), sin
llamar a ningun proveedor.

### 1.2 Modos CON PROVEEDOR (`runner.PROVIDER_MODES`)

| Modo | Proveedores | `context_mode` |
|---|---|---|
| `ollama_shadow` | LLM local (Ollama) | `sentence` |
| `nvidia_shadow` | IA externa (NVIDIA) | `sentence` |
| `ensemble_full` | ambos + ensemble B6 | `sentence` |

No estan en `MODES`: ni `--all-modes` ni ningun test que itere `MODES` puede
ejecutarlos por accidente. `--all-modes` recorre **solo** modos offline y aborta
si se combina con un modo con proveedor, **antes** de construir transportes y de
cargar el corpus.

## 2. Autorizacion de proveedores: llave del NUCLEO, no solo de la CLI

### 2.1 `authorize_provider_run` — la regla vigente

La comprobacion ya **no vive solo en la CLI**. `runner.authorize_provider_run` se
ejecuta dentro de `run_benchmark` / `run_source` —API publica exportada en
`relations.benchmark.__init__`— **antes de construir ninguna `PipelineConfig`**.

Motivo: `require_provider_authorization` solo se invocaba desde `cli.main()`, asi
que llamar `run_benchmark(corpus, mode="nvidia_shadow")` desde codigo ponia
`external_ai_enabled=True` y, con `external_provider=None`, el pipeline **delegaba
en el registry de `external_ai`**, que lee la clave del entorno y abre conexiones
**reales** contra NVIDIA sin bandera ni variable de entorno.

Reglas, en orden, con **fallo cerrado**:

1. **Modo offline** → no hay nada que autorizar.
2. **Modo con proveedor** → por cada proveedor que el preset habilita, el objeto
   correspondiente **debe estar INYECTADO**. Si falta, `BenchmarkError`. **El
   nucleo NUNCA delega la resolucion del proveedor en el registry.**
3. **Si el llamante no inyecta todos los proveedores del modo**, se exige ademas
   la **doble llave** explicita (`--enable-providers` + `S9K_BENCH_PROVIDERS=1`).

### 2.2 La doble llave NO es una condicion necesaria universal

**Importante, y facil de malinterpretar:** un llamante de libreria que **inyecta
los proveedores** (`local_transport=…`, `external_provider=…`) **no necesita la
doble llave**. Es una decision **deliberada**: quien construye e inyecta un
transporte real lo ha hecho a proposito y de forma explicita; la doble llave
existe para impedir el camino *implicito* (el registry), no para estorbar al
explicito.

| Situacion | ¿Doble llave? | Resultado |
|---|---|---|
| Modo offline | no aplica | se ejecuta |
| Modo con proveedor, **todos** los proveedores inyectados | **NO se exige** | se ejecuta |
| Modo con proveedor, algun proveedor **sin inyectar** | **SI se exige**… | …y aun asi falla: sin objeto inyectado no se resuelve por registry |
| CLI (`--mode ollama_shadow`) | **SI** — la CLI la valida y luego construye los transportes | se ejecuta |

La CLI sigue siendo el camino con doble llave, verificado el 2026-07-20:

```
$ python -m relations.benchmark.cli --mode ollama_shadow
ERROR: modo con proveedor 'ollama_shadow' requiere DOBLE LLAVE; falta:
--enable-providers, S9K_BENCH_PROVIDERS=1. ABORTADO ANTES DE ABRIR RED
(ninguna llamada a Ollama/NVIDIA realizada).
```

### 2.3 Proveedor externo: se construye explicitamente, no se hereda del registry

`providers.build_external_provider()` **ya no es la identidad**: construye el
proveedor del registry de `external_ai` de forma explicita, **exigiendo API key
presente** y **validando el `base_url`** (esquema, host, sin credenciales
embebidas). Falla **cerrado** con `BenchmarkError` si falta cualquiera de las dos
cosas. **Construirlo no abre red.**

> La afirmacion de versiones anteriores de este documento —«el proveedor externo
> se resuelve via `external_ai_shadow`, que falla cerrado si no hay API key»— **ya
> no es cierta y describia justo la via que habia que cerrar**.

Otros refuerzos vigentes: `providers.py` se importa de forma **perezosa** (en modo
offline el unico modulo con codigo de red ni se importa) y
`build_local_transport` **no tiene default a infraestructura real**.

**Ronda 3 (N13) — el endpoint es EXPLICITO, sin fallback implicito al entorno.**
`build_local_transport(endpoint)` ya **no lee `S9K_BENCH_OLLAMA_ENDPOINT` por su
cuenta**: si el argumento falta o esta vacio, falla cerrada con `BenchmarkError`
**aunque la variable de entorno este definida** (y el mensaje lo menciona para que
el llamante la pase a proposito). Quien resuelve el entorno es la **CLI**
(`cli._build_providers`), que pasa el endpoint explicito a la fabrica y publica
**ese mismo** destino en la atestacion del informe.

> La redaccion anterior de este documento —«sin `--local-endpoint` **ni**
> `S9K_BENCH_OLLAMA_ENDPOINT` falla cerrada»— **ya no describe el codigo**:
> sugeria que la variable de entorno bastaba para construir el transporte. El
> motivo del cambio es concreto: con `S9K_BENCH_OLLAMA_ENDPOINT` apuntando a un
> host atacante, un llamante de la API publica abria conexiones a ese host **sin
> haber nombrado ningun destino**.

## 3. Endpoint local: normalizacion, validacion y atestacion

### 3.1 Normalizacion (`normalize_local_endpoint`)

| Endpoint aportado | URL usada |
|---|---|
| `…/v1/chat/completions` | **tal cual** |
| `…/v1` | se le añade `/chat/completions` |
| cualquier otra base (`http://host:11434`) | se le añade `/v1/chat/completions` |

Las barras finales se recortan. **No abre red.**

**Ronda 3 (N9): la normalizacion sustituye la RUTA, no concatena sufijos.** Se
reconstruye la URL con `urlunsplit`, de modo que:

- una base **con query** (`http://host:11434/v1?k=X`) produce
  `http://host:11434/v1/chat/completions?k=X` y **no** el
  `…/v1?k=X/chat/completions` de antes, que **siempre** daba 404 — la misma clase
  de defecto que D2;
- un host **IPv6** conserva los corchetes (`http://[::1]:11434/…`); la
  concatenacion anterior producia `http://::1:11434`, ambiguo e irreconstruible;
- el **fragmento** se descarta (no se envia en una peticion HTTP) y la
  normalizacion es **idempotente**.

**Caso real que lo motivo:** con `http://127.0.0.1:11434/v1` se hacia POST a esa
URL tal cual y se obtenian **18 respuestas 404** contabilizadas como llamadas
ejecutadas, como si el modelo hubiera contestado mal. Con la URL completa, **ese
mismo Ollama responde 200 en ~3,9 s**.

### 3.2 Validacion del endpoint (`_split_checked`)

Comprobaciones, **en este orden** (el orden es parte del contrato, ver N5):

| # | Comprobacion | Rechazo |
|---|---|---|
| 0 | `urlsplit` + lectura del puerto | **N10**: un puerto fuera de rango (`http://host:99999/v1`) lanzaba `ValueError` crudo con rc=1; hoy se traduce a `BenchmarkError` → **codigo de salida 2**, el mismo contrato que el resto de errores de uso |
| 1 | **credenciales embebidas** | `BenchmarkError` |
| 2 | esquema en `{http, https}` | `BenchmarkError` |
| 3 | host no vacio, sin espacios | `BenchmarkError` |
| 4 | **puerto 0** (**N9**) | `BenchmarkError`: no es un destino valido y ademas *desaparecia* de la atestacion publicada |

**N5 — las credenciales se comprueban ANTES que el host, y NINGUNA rama vuelca la
URL cruda.** `http://tok:SECRETO@/v1` tiene credenciales y no tiene host: con el
orden anterior ganaba la rama de host, que imprimia el endpoint **entero** y
**filtraba el secreto a stderr** (y a los logs de CI, donde un
`S9K_NVIDIA_BASE_URL` mal escrito es un error humano plausible). Hoy ningun
mensaje de validacion reproduce la URL de entrada.

Motivo original de la validacion: antes se aceptaba cualquier cadena. Con
`file:///…` se fabricaba un run con «Ollama real: EXECUTED», llamadas contadas y
latencias medidas **sin una sola conexion de red**; con `ftp://` se abriria
conexion a un host y puerto arbitrarios.

### 3.3 Atestacion (`endpoint_attestation`)

El informe publica `esquema://host:puerto` **sin credenciales, ruta ni query**
(campo `providers.endpoints`), para que la atestacion sea auditable sin filtrar
secretos. Los hosts IPv6 se publican **entre corchetes** (N9) y el puerto 0 no
puede llegar hasta aqui (§3.2). Existe la variante
`external_endpoint_attestation()` para NVIDIA.

## 4. Endurecimiento del transporte

| Control | Valor | Por que |
|---|---|---|
| `PROVIDER_LOCAL_TIMEOUT_S` | **300 s** | timeout por operacion de socket del transporte inyectado (§4.1) |
| `WALL_CLOCK_MARGIN_S` | 30 s | margen del deadline de reloj de pared |
| **Deadline efectivo por llamada** | **330 s** (300 + 30) | `urlopen(timeout=)` es *por operacion*: un servidor que gotea 1 byte/s mantuvo viva una llamada 60 s con `timeout=2`. El deadline se comprueba **entre trozos de lectura** |
| `MAX_RESPONSE_BYTES` | 1 MiB | el `max_response_bytes` del pipeline se aplicaba **despues** de leer y parsear el cuerpo entero: una respuesta de 200 MB llegaba a memoria (RSS 25 MB → 627 MB) |
| Redirecciones | **bloqueadas entre origenes** | un opener propio **previene** la peticion al segundo host en lugar de detectarla a posteriori: la respuesta de otro host no es la del modelo |
| **Deadline GLOBAL de run** (N11) | `--max-run-seconds` (opcional, sin default) | comprobado **entre fuentes** en `run_benchmark`: el deadline por llamada NO acota el total |

### 4.0 El endurecimiento NO depende de un global mutable (N6)

`_open` comparaba `urllib.request.urlopen is _STDLIB_URLOPEN` y, si diferian, **se
saltaba el manejador `_NoCrossOriginRedirect`**: un control de seguridad que
cualquier mock, `responses`, `vcrpy` o instrumentacion que reemplazase ese global
**desactivaba en silencio**. Hoy el opener endurecido se usa **siempre** y la
costura de test es **explicita**: el parametro `opener=` de
`build_local_transport`, o el modulo-global `providers._OPENER` (que vale `None`
en produccion). Parchear `urllib.request.urlopen` ya no relaja nada.

### 4.0.1 Deadline GLOBAL de run (`--max-run-seconds`, N11)

**Existe desde la ronda 3.** El limite de 330 s es **por llamada** y no acota el
total: con 300 s por llamada, un servidor que se atasca **1 de cada 10** llamadas
añade el timeout entero por atasco **sin superar el umbral del 10 %** de fallos de
transporte, de modo que una pasada podia crecer sin tope y sin disparar ninguna
alarma. `run_benchmark(..., max_run_seconds=…)` comprueba el presupuesto **entre
fuentes** y, al agotarse, aborta con `BenchmarkError` declarando cuantas fuentes
se procesaron; **las fuentes ya ejecutadas NO producen dictamen** (muestra
incompleta).

Limite conocido de este control (§13.9): la granularidad es **por fuente**, no por
llamada — una sola fuente muy lenta puede rebasar el presupuesto antes de la
siguiente comprobacion. Y **no hay default**: si no se pasa la bandera, no hay
presupuesto global.

### 4.1 Timeout local = 300 s (antes 180 s) — riesgo CERRADO

El valor se elevo **sobre la latencia medida** en §12: p50 = **97,8 s**, maximo
observado = **175,7 s**. Con 180 s el margen era de **4,3 s** sobre el peor caso,
es decir practicamente ninguno: cualquier cola algo peor se habria contabilizado
como fallo de transporte y el run habria abortado por infraestructura.

**300 s ≈ 175,7 s × 1,7**, un margen de ~124 s sobre el peor caso observado.
`build_local_transport` sigue **rechazando** cualquier timeout inferior a 120 s.

> La estimacion «p50 real de Ollama 10-65 s», heredada de los Bloques 1 y 2
> (casos **sinteticos**), **quedo refutada por la medicion** y ya no sostiene
> ningun valor del codigo. El riesgo que versiones anteriores de este documento
> declaraban abierto —«timeout marginal, se recomienda subirlo»— **esta CERRADO**.

## 5. Fallos de TRANSPORTE frente a respuestas INVALIDAS del modelo

El pipeline R8 degrada **cualquier** problema de un proveedor al mismo estado
canonico `INVALID_RESPONSES`: un 404 y un JSON malformado del modelo acaban
indistinguibles. Eso convierte un fallo de **infraestructura** en un dictamen de
**calidad**. El benchmark separa **tres categorias disjuntas** (`metrics.py`:
`CATEGORY_TRANSPORT`, `CATEGORY_RESPONDED`, `CATEGORY_INDETERMINATE`) leyendo los
marcadores que el propio evaluador ya escribe.

| Categoria | Que es | Marcadores |
|---|---|---|
| **TRANSPORTE** | la llamada **nunca obtuvo respuesta utilizable**; no dice nada del modelo | `transport_error:*`, `response_structure_invalid`, `response_content_not_str`, y `provider_error:<Excepcion>` **solo si la excepcion es de red/servidor/auth/timeout** (§5.2) |
| **RESPONDIDA** | el proveedor **si respondio**; la calidad del contenido se mide aparte | ausencia de marcador de fallo, `parse:*`, campos invalidos, respuesta demasiado grande, y `provider_error:InvalidResponseError` (§5.2) |
| **INDETERMINADA** | el marcador **NO permite decidir** si el proveedor respondio | `provider_error` generico, sin nombre de excepcion o con un nombre desconocido |

### 5.1 Salidas

- `provider_cost.transport_errors` — por proveedor y total: `attempted`,
  `responded`, `errors`, `rate`, `by_type`, `min_calls`, `min_rate_sample`,
  `sample_below_minimum`, `rate_applied`, `final_check`, `evaluable`.
- `provider_cost.transport_error_rate` — global y por proveedor.
- `provider_cost.indeterminate` / `indeterminate_rate` — **bloque propio** por
  proveedor y total, con `count`, `rate`, `by_type` y una `note` que explica que
  **no se cuentan como transporte ni como calidad** (§5.2).
- `provider_cost.fail_closed` + `fail_closed_note` (N7) — candidatos que un
  proveedor habilitado **no llego a evaluar**: **no dejan payload**, asi que no
  aparecen en `attempted` ni en `errors`. Un carril entero muerto daba
  `rate = 0.0` y gate `PASS`; ahora se publica junto a `attempted` para poder
  contrastarlo, y **degrada el gate a `PARTIAL`** aunque la tasa sea cero.
- `latency` (p50/p95/max) **solo de llamadas RESPONDIDAS**; las de transporte van
  en `failed_latency` y las indeterminadas en **`indeterminate_latency`**, un
  bloque separado. Mezclarlas producia el p50 de 0 ms que delato el defecto.
- `report["provider_transport"]` en la raiz del JSON y seccion propia en el
  Markdown, con columna de **indeterminadas**.

### 5.2 `provider_error` NO es sinonimo de fallo de transporte (ronda 3, CERRADO)

**El problema.** Tanto `relations/local_llm_shadow.py`
(`validation_errors=["provider_error:<Excepcion>"]`) como
`relations/external_ai_shadow.py` (`reason_codes=["provider_error"]` +
`validation_errors=["<Excepcion>"]`) marcan con la **misma** etiqueta cosas
radicalmente distintas, porque su `except _PROVIDER_ERRORS` agrupa toda la familia
`ExternalAIError` — **incluida `InvalidResponseError`**, que se emite cuando el
modelo **SI contesto** (HTTP 200) pero su contenido no es utilizable:

- `{"relations": []}` → «la respuesta no contiene ningun verdicto»;
- texto libre no-JSON («no puedo…») → el extractor de JSON falla.

Esas son averias de **CALIDAD** canonicas — las mismas que el carril local
clasifica como `no_relation_extracted`. Contarlas como transporte **abortaba
pasadas sanas con un diagnostico de «fallo de INFRAESTRUCTURA» falso**.

**Donde vive la causa raiz, y por que no se ha tocado.** El agrupamiento esta en
`relations/external_ai_shadow.py` (linea del `except _PROVIDER_ERRORS`), fichero
**FUERA del alcance del Bloque 7** y **NO modificado**. La discriminacion se hace
sin tocarlo: ambos emisores dejan escrito en el payload el **nombre de la
excepcion** subyacente, y el benchmark lo lee
(`metrics.classify_provider_outcome`).

| Nombre de la excepcion en el payload | Categoria |
|---|---|
| `ProviderTimeoutError`, `ProviderServerError`, `ProviderAuthError`, `ProviderNotFoundError`, `RateLimitError`, `ProviderTransportError`, `URLError`, `HTTPError`, `TimeoutError`, `ConnectionError`, `ConnectionResetError`, `ConnectionRefusedError`, `socket.timeout` | **TRANSPORTE** |
| `InvalidResponseError` | **RESPONDIDA** (calidad del modelo) |
| cualquier otro, generico (`ExternalAIError`) o **ausente** | **INDETERMINADA** |

**La limitacion, dicha sin adornos.** Cuando el nombre no permite decidir, el
benchmark **no afirma lo que no sabe**. La llamada queda **INDETERMINADA**:

- **no** cuenta como transporte → **no aborta el run** (un marcador ambiguo no
  puede tumbar una pasada acusando a la infraestructura);
- **no** se presenta como medida de calidad del modelo → no entra en `responded`
  ni en las latencias del modelo;
- **se publica como tal**, con su recuento, su tasa y sus latencias propias, y
  **degrada el gate `provider_transport` a `PARTIAL`**, que se declara en
  `verdict_scope` (§6).

Es decir: **el benchmark declara su incertidumbre en vez de resolverla a favor de
una de las dos hipotesis.** Cerrar del todo esta zona gris exige corregir el
`except` de `external_ai_shadow.py`, que es **otro bloque** (§13.12).

Compatibilidad: `classify_provider_payload(payload)` sigue existiendo y devuelve
el tipo de fallo de transporte o `None`; **`None` ya no significa «respondio»**,
puede ser tambien INDETERMINADO. Para distinguirlos hay que usar
`classify_provider_outcome`, que devuelve `(categoria, tipo)`.

### 5.3 Umbral de salud: 10 %, aplicado POR CARRIL, con la muestra pequeña ENDURECIENDO

`PROVIDER_TRANSPORT_ERROR_MAX_RATE = 0.10`, `PROVIDER_TRANSPORT_MIN_CALLS = 3`,
`PROVIDER_TRANSPORT_MIN_RATE_SAMPLE = 20` (ronda 3). La comprobacion se hace
**tras cada fuente** (*fail-fast*) y ademas una vez **FINAL** sobre la muestra
completa.

**N1 — el umbral EFECTIVO es el DOCUMENTADO.** Corriendo tras cada fuente con
`min_calls = 3`, **un solo fallo en la llamada #1 de 36** abortaba con «1/5 = 20 %
> 10 %», aunque la tasa final habria sido del **2,8 %**: el umbral real era
«cualquier fallo temprano», no el 10 % publicado. Hoy:

| Comprobacion | Muestra minima para aplicar la TASA |
|---|---|
| Intermedia (tras cada fuente) | `min_rate_sample = 20` |
| **FINAL** (muestra completa) | `min_calls = 3` |

Siguen abortando **siempre**, sin depender de la tasa: (a) muestra por debajo del
minimo **con errores**, y (b) un carril con el **100 %** de sus llamadas fallidas
(proveedor demostrablemente caido).

**N2 — la tasa se aplica tambien POR PROVEEDOR.** Un carril local al **14,3 %**
diluido con el externo al 0 % daba un agregado del **4,76 %** y un dictamen
«APTO». Hoy cada carril con muestra suficiente debe cumplir el umbral por su
cuenta, y el mensaje de aborto dice explicitamente que el agregado **por si solo
no lo habria detectado**.

**`strict_small_sample` (por defecto `True` desde la ronda 3, y como lo invoca
SIEMPRE `run_benchmark`):** por debajo del minimo de llamadas, **cualquier** error
de transporte aborta. La muestra pequeña **no perdona, endurece**. Antes ocurria
lo contrario: 9 de 16 fuentes emitian «APTO» con 1-2 llamadas **todas fallidas**,
o con 0 llamadas.

> **El 10 % sigue siendo una eleccion de diseño razonada, NO un umbral calibrado
> con datos reales de fallo de VM105.** Debe revisarse cuando exista una serie de
> medidas (§13.8).

### 5.4 Gate DURO `provider_transport`

Solo existe en **modos con proveedor** (en offline el gate no aparece).

| Estado | Cuando |
|---|---|
| `PASS` | run evaluable, **0** errores de transporte, **0** indeterminadas y **0** `fail_closed` |
| `PARTIAL` | run evaluable con errores por debajo del umbral, **o** con llamadas INDETERMINADAS (§5.2), **o** con `provider_fail_closed > 0` (N7) |
| `FAIL` | `evaluable = False`: tasa por encima del umbral, carril completamente caido, **o muestra por debajo de `min_calls`** aunque no haya errores (con 1-2 llamadas no hay medicion que defender) |
| `NOT_MEASURED` | **0 llamadas contabilizadas**: no se midio a ningun proveedor |

El gate publica `indeterminate`, `fail_closed` y **`degraded_reasons`** (lista de
motivos en texto), que se reproducen en el Markdown y en `verdict_scope`.

### 5.5 Dictamen nuevo: `SIN DICTAMEN: PROVEEDOR NO MEDIDO`

Añadido a `VERDICTS`. Si `provider_transport` no esta en `PASS` ni `PARTIAL`,
**no se emite dictamen de calidad**: «NO APTO» seria una **afirmacion falsa**
sobre el pipeline, porque no se ha medido nada. `verdict_scope` pasa entonces a
**`NO MEDIDO (…)`**, y la CLI termina con **codigo de salida 2** aunque haya
escrito sus salidas (documentan el intento).

### 5.6 Atestacion de red y `status_consistency`

El campo `network` se deriva de las llamadas **realmente contabilizadas**
(`total_attempted`), no de si un objeto es `None`. Antes, `--mode nvidia_shadow`
publicaba «Red: none» **tras 5 POST reales contra NVIDIA**, porque
`external_provider` valia `None`: una atestacion de seguridad **falsa**. Valores:

| `network` | Cuando |
|---|---|
| `yes (N llamadas a proveedor contabilizadas; M fallos de transporte)` | `attempted > 0` |
| `yes (proveedores ejecutados)` | sin llamadas contabilizadas pero `provider_status` dice `EXECUTED` — lado conservador |
| `unknown (modo con proveedor y 0 llamadas contabilizadas…)` | no verificable desde el informe |
| `none` | modo offline |

`status_consistency` contrasta el literal `provider_status` (que calcula
`relations/pipeline.py`, **fuera de alcance**, a partir de si el objeto proveedor
es `None`) con las llamadas contadas, y declara `INCONSISTENTE` en vez de publicar
una atestacion que se sabe falsa.

**N8 (ronda 3) — la comprobacion se hace en las DOS direcciones**, y eso cambia lo
que este documento decia de ella:

| Direccion | ¿Ocurre en un run real? |
|---|---|
| «llamadas contabilizadas pero **ningun** `EXECUTED`» | **NO — codigo muerto hoy**: `authorize_provider_run` exige el proveedor inyectado y `pipeline.py` publica `EXECUTED` en cuanto el objeto no es `None`. Se conserva como red de seguridad, no como mitigacion activa |
| «`EXECUTED` pero **CERO** llamadas contabilizadas» | **SI**: fuentes sin candidatos, o un proveedor que nunca llego a invocarse. Es justo el caso en que la atestacion «proveedor EXECUTED» induce a error, y hoy **se declara** |

> **Correccion de una afirmacion anterior de este documento.** Versiones previas
> decian que `status_consistency: INCONSISTENTE` era **inalcanzable** y «solo
> codigo defensivo». Eso **ya no es cierto**: es exacto **solo para la primera
> direccion**. La segunda es alcanzable en runs reales y hoy esta cubierta.
> La atestacion de red, en cambio, sigue siendo **incompleta aunque nunca falsa**
> (§13.10): puede decir `yes (proveedores ejecutados)` con
> `network_calls_counted: 0`.

## 6. Determinismo NO EVALUADO y alcance del dictamen

| `deterministic` | Gate | Significado |
|---|---|---|
| `True` | `PASS` | comprobado y determinista |
| `False` | `FAIL` | comprobado y **no** determinista → `NO APTO` |
| `None` | `NOT_EVALUATED` | **no comprobado** (`--no-determinism` o modo con proveedor) |

Sigue siendo gate **DURO**: un `FAIL` real sigue dando `NO APTO`. Lo que ya no
ocurre es que «no comprobado» cuente como «comprobado y fallido».

`verdict_scope` declara el alcance: `COMPLETO`, `PARCIAL (…)` o `NO MEDIDO (…)`
(§5.5). Verificado en vivo con `--no-determinism`:
`PARCIAL (gates duros no evaluados: determinism)`.

**N3 (ronda 3) — el transporte `PARTIAL` tambien se DECLARA.** Si «no comprobado»
consta en el alcance, «comprobado y degradado» tambien debe constar: emitir un
dictamen normal sin mencionar el transporte degradado era la misma clase de
silencio. Hoy un gate `provider_transport = PARTIAL` produce
`PARCIAL (transporte del proveedor DEGRADADO: <motivos> | …)` y el mismo desglose
se repite dentro de `verdict_justification`, con la coletilla «el dictamen se
emite sobre las llamadas que SI midieron al modelo». Los motivos incluyen los
errores tolerados, las llamadas **INDETERMINADAS** (§5.2) y los
`provider_fail_closed` (N7).

## 7. Payloads: el manifiesto es INTEGRIDAD, no AUTENTICIDAD

`--out-payloads` emite, junto al JSONL, un manifiesto `<jsonl>.manifest.json`
(`relation-benchmark-payloads-manifest-v1`) con: `payloads_sha256`,
`payloads_bytes`, `records`, `mode`, `code_sha`, `pipeline_version`,
`ground_truth_sha256`, `corpus_hashes` y `source_ids`. `--recombine-from` lo
**exige y lo verifica** (o el que se indique con `--recombine-manifest`).

### 7.1 Que se comprueba exactamente

| Comprobacion | Rechazo si… |
|---|---|
| version del manifiesto | no es `relation-benchmark-payloads-manifest-v1` |
| `payloads_sha256` y `payloads_bytes` | no coinciden con el fichero recomputado |
| `records` | el numero de lineas no coincide con el declarado |
| topes | > **64 MiB** o > **100 000** registros |
| esquema de **cada** registro | cualquiera invalido → se rechaza el fichero **ENTERO** |
| `mode` | no pertenece a `MODES ∪ PROVIDER_MODES` |
| **`code_sha`** (ronda 3) | ver §7.2 |
| **`corpus_hashes`** (ronda 3) | ausente, **vacio**, o que **no cubra EXACTAMENTE** los `source_ids` |
| `ground_truth_sha256` | no es el del corpus cargado |
| `source_ids` | ausentes; ademas el JSONL **no puede** traer fuentes no declaradas |
| `hmac_sha256` | ver §7.3 |

Los `source_ids` evaluados salen del **manifiesto**, no del fichero: el JSONL **no
elige su propio examen**.

### 7.2 Los dos agujeros que cerro la ronda 3

**(a) `corpus_hashes: {}` desactivaba por completo la atadura al corpus**, porque
la verificacion iteraba las claves **del propio manifiesto**: un diccionario vacio
significaba «cero comprobaciones». Hoy se exige que sea **no vacio** y que cubra
**exactamente** el conjunto de `source_ids` (`sorted(hashes) == sorted(set(ids))`).

**(b) `code_sha` no se contrastaba con NADA**: un manifiesto forjado con 40 ceros
era aceptado. Hoy debe ser **igual al `code_sha` del proceso que recombina** —
recombinar payloads producidos por otra version del pipeline no mide **este**
codigo.

**El ORDEN de esa comprobacion es parte del arreglo, no un detalle.** Primero se
exige que **este** proceso tenga un `code_sha` determinable y, **solo despues**,
se compara con el del manifiesto:

```python
code_sha_actual = _code_sha()
if code_sha_actual is None:      # 1) guard PRIMERO
    raise BenchmarkError(...)
if manifest.get("code_sha") != code_sha_actual:   # 2) igualdad DESPUES
    raise BenchmarkError(...)
```

Con el orden inverso, un arbol **sin git** (`code_sha_actual is None`) frente a un
manifiesto que declarase `code_sha: null` **pasaba la igualdad** (`None == None`)
y el rechazo quedaba a merced de la guarda posterior: la seguridad dependia de que
la comparacion de igualdad no cambiara nunca. **La ausencia de atadura es un
motivo de rechazo por si misma**, no un empate afortunado.

### 7.3 Que demuestra el manifiesto — y que NO

**Demuestra INTEGRIDAD INTERNA:** que el JSONL no ha cambiado desde que se emitio
**ese** manifiesto, que corresponde a **este** corpus, a **este** ground truth y a
**este** `code_sha`, y que su esquema es valido.

**NO demuestra AUTENTICIDAD.** No prueba **QUIEN** emitio los payloads, ni que
procedan de llamadas reales a un proveedor: **todos** los valores del manifiesto
(hashes del corpus, hash del ground truth, `code_sha`, `pipeline_version`) son
**publicos en el repositorio**, asi que cualquiera con una copia del repositorio
puede fabricar un manifiesto valido para un JSONL inventado.

Por eso el JSON de recombinacion **rebaja el vocabulario** y lo dice literalmente:

```json
"provenance": {
  "recombined": true,
  "verified": "integridad interna, NO autenticidad",
  "verified_detail": "comprobado: … NO comprobado: quien emitio el manifiesto …",
  "hmac": "AUSENTE (sin clave de operador: NO hay autenticidad)"
}
```

**La unica pieza que aporta autenticidad es el HMAC**, y solo si el operador
define `S9K_BENCH_MANIFEST_HMAC_KEY`:

| Entorno | `provenance.hmac` | Efecto |
|---|---|---|
| clave **definida**, manifiesto **con** HMAC valido | `VERIFICADO con la clave de operador` | hay cadena de custodia |
| clave definida, manifiesto **sin** `hmac_sha256` | — | **RECHAZADO** |
| clave definida, HMAC **invalido** | — | **RECHAZADO** (`hmac.compare_digest`) |
| clave **ausente**, manifiesto con HMAC | `PRESENTE pero NO verificado (…)` | se recombina, sin autenticar |
| clave **ausente**, manifiesto sin HMAC | `AUSENTE (sin clave de operador: NO hay autenticidad)` | se recombina, sin autenticar |

### 7.4 Por que se cambio el vocabulario: la falsificacion real

El corpus verificaba sha256 pero los payloads **no verificaban nada**. Un JSONL
forjado producia **P = R = F1 = 1.0 con `rc=0`** y latencias inventadas de 99 999
ms que nunca ocurrieron; y como el ground truth se elegia por los `source_id` del
propio fichero, **el atacante escogia su examen**.

La ronda 2 añadio el manifiesto. **La ronda 3 documenta por que eso no bastaba:**
el Organizador **falsifico un manifiesto usando solo valores publicos del
repositorio** y volvio a obtener **P = R = F1 = 1.0 con `rc=0`** antes del
arreglo. Ese hecho es el que justifica (i) las ataduras de §7.2 y (ii) que la
palabra «verificado» se sustituya por **«integridad interna, NO autenticidad»**:
un manifiesto sin clave de operador **no es** una prueba de procedencia, y
presentarlo como tal era la misma clase de afirmacion falsa que este bloque
persigue.

## 7A. Defecto `external_model` (ronda 4) — la avería que solo se veía MIDIENDO

**El defecto, tal como estaba antes de la ronda 4.** `PipelineConfig.external_model`
(`relations/pipeline.py:151`) trae por defecto el placeholder `"external-model"`. El
preset `nvidia_shadow` en `relations/benchmark/runner.py` (`MODE_PRESETS`) solo ponia
`external_ai_enabled: True`: **nunca fijaba `external_model`**, y no existia ninguna
bandera de CLI para hacerlo. Consecuencia: al ejecutar `nvidia_shadow` con una API key
valida, el carril externo enviaba literalmente la cadena `"external-model"` a NVIDIA,
que respondia **404** (`ProviderNotFoundError`), y el runner lo contabilizaba como
fallo de **transporte** (§5) — el run abortaba con un diagnostico de **"fallo de
INFRAESTRUCTURA"** que era, en realidad, un error de **configuracion**.

**Por que nadie lo vio antes.** El defecto es invisible en dos regimenes a la vez:

- Con NVIDIA figurando como **"NO EJECUTADO"** (sin clave de API en la sesion), el
  camino que fija `external_model` nunca se ejercitaba: nada en los tests offline ni
  en la revision de codigo lo dispara, porque el placeholder solo importa **en el
  momento del POST real**.
- Los revisores tenian **prohibido hacer llamadas externas reales** (es la misma
  regla que motiva todo el diseño offline del bloque, §2), asi que no podian
  reproducir el 404 para diagnosticarlo: solo aparecia **midiendo de verdad**, con
  clave real, contra el endpoint real.

Es la leccion central de este bloque: **medir de verdad revela lo que la teoria
tapa.** Mientras el carril NVIDIA quedaba sin ejecutar, la avería quedaba oculta
detras de un "NO EJECUTADO" que parecía prudencia y en realidad escondía un bug.

**El arreglo, todo en `relations/benchmark/` (sin tocar `pipeline.py` ni
`external_ai_shadow.py`):**

1. **Nuevo flag `--external-model`** en `cli.py`: id real del modelo externo
   (p. ej. `meta/llama-3.3-70b-instruct`) para los modos que habilitan IA externa
   (`nvidia_shadow`, `ensemble_full`). Si se omite, `_resolve_external_model` toma
   el primer id de `S9K_NVIDIA_REVIEW_MODELS` (via el registry); si tampoco hay
   ninguno, la guarda decide.
2. **Threading explicito** hasta `PipelineConfig.external_model`:
   `run_benchmark(..., external_model=...)` → `run_source(..., external_model=...)`
   → `_config_for_mode(mode, external_model=...)`, que solo sobreescribe el campo
   si se paso un valor no vacio (si no, queda el placeholder por defecto, que la
   guarda rechaza).
3. **Guarda fail-closed `require_external_model(mode, external_model)`**
   (`runner.py`): si el modo habilita IA externa y el `external_model` esta
   ausente, vacio o es literalmente `PLACEHOLDER_EXTERNAL_MODEL = "external-model"`,
   lanza `BenchmarkError` **antes de construir transporte o proveedor** — es decir,
   **antes de tocar la red**. El mensaje nombra la causa real
   ("error de CONFIGURACION, no de red") y explica exactamente lo que habria
   pasado (placeholder → 404 → abortado disfrazado de infraestructura).

**Verificado en el codigo** (`relations/benchmark/runner.py`): `require_external_model`
se invoca en `run_source` y en `run_benchmark`, ambas API publica, no solo desde la
CLI — la misma disciplina de "la llave vive en el nucleo" que ya aplicaba
`authorize_provider_run` (§2.1). `ensemble_full` (que tambien habilita IA externa)
queda cubierto por la misma guarda.

**Cobertura de tests:** `tests/test_relation_benchmark_block7_round4.py` (parte del
total de 177 del bloque, §4.6) incluye, entre otros,
`test_nvidia_sin_external_model_aborta_como_configuracion_no_transporte`,
`test_nvidia_con_external_model_llega_el_id_real_no_el_placeholder`,
`test_nvidia_config_for_mode_thread_del_external_model`,
`test_ensemble_full_tambien_exige_external_model`,
`test_ollama_shadow_no_afectado_por_la_guarda` (la guarda no interfiere con el
carril local) y un *mutation check*
(`test_nvidia_mutation_guarda_placeholder`) que reintroduce el placeholder para
comprobar que la guarda lo sigue detectando.

## 8. Como se ejecuta

Desde `data-engine/app` (o con `PYTHONPATH=data-engine/app`):

```bash
# Corpus completo, offline, con comparativa de todos los modos offline
python -m relations.benchmark.cli --mode baseline1 --all-modes \
    --out-json /tmp/resultados.json --out-jsonl /tmp/predicciones.jsonl \
    --out-md /tmp/informe.md

# Modo con ensemble calibrado B6 (offline, 0 llamadas)
python -m relations.benchmark.cli --mode ensemble_offline --out-json /tmp/ens.json

# Submuestra acotada de fuentes
python -m relations.benchmark.cli --mode baseline1 \
    --sources src-01,src-02,src-03,src-04,src-05,src-06 --out-json /tmp/sub.json
```

| Opcion | Efecto |
|---|---|
| `--mode` | modo del dictamen (offline o con proveedor) |
| `--all-modes` | ejecuta ademas los demas modos **offline** |
| `--sources` | submuestra; el corpus se carga y verifica **igual**, y el ground truth evaluado se restringe a esas fuentes |
| `--enable-providers` | primera llave (§2.2: solo necesaria si no se inyectan los proveedores) |
| `--local-endpoint` / `--local-model` | endpoint (se **normaliza y valida**, §3) y modelo del LLM local |
| `--external-model` | (ronda 4, §7A) id REAL del modelo de IA externa/NVIDIA (p.ej. `meta/llama-3.3-70b-instruct`), exigido por `nvidia_shadow`/`ensemble_full`; sin el, la guarda `require_external_model` aborta con error de CONFIGURACION antes de tocar red |
| `--out-payloads` | JSONL de payloads crudos **+ manifiesto** (§7) |
| `--recombine-from` / `--recombine-manifest` | recombinacion **offline** verificada: **cero** llamadas |
| `--max-run-seconds` | presupuesto **GLOBAL** de tiempo del run (N11, §4.0.1); sin default |
| `--no-determinism` | omite la segunda ejecucion → `verdict_scope = PARCIAL` |
| `--out-json` / `--out-jsonl` / `--out-md` | salidas |

Codigos de salida: `cli.run_cli(argv)` traduce **siempre** `BenchmarkError` (y
`ProviderTransportError`) al codigo **2**. Un modo con proveedor sin medicion
tambien termina en **2** (§5.5), y desde la ronda 3 tambien un endpoint con
**puerto fuera de rango** (N10), que antes se escapaba como `ValueError` crudo con
rc=1. `main()` sigue propagando la excepcion a proposito, para que quien importe
el benchmark como funcion reciba un error visible y no un entero ignorable.

La CLI imprime `transport_errors=… rate=…` y `verdict_scope=…`.

> **Cuidado:** `--out-md docs/50-relation-benchmark-results.md` **sobrescribe este
> fichero** con el informe generado en crudo y elimina las secciones curadas
> (1-8, 13). Vuelca el Markdown a un fichero temporal.

## 9. Resultados medidos — corpus completo (16 fuentes), 2026-07-20

Reproducidos tras las correcciones de la ronda 2 y **de nuevo el 2026-07-21 tras
la ronda 3**: **identicos** en los tres casos (P/R/F1, TP/FP/FN, gates, dictamen,
contadores operativos, matriz de confusion y `verdict_scope`). Los arreglos
afectan a la instrumentacion, la seguridad y el alcance del dictamen, **no al
pipeline ni al ensemble**.

### 9.1 `baseline1` vs `ensemble_offline`

| Metrica (existencia: par no ordenado) | `baseline1` | `ensemble_offline` |
|---|---|---|
| Precision | 82.69% | 82.69% |
| Recall | 79.63% | 79.63% |
| F1 | 81.13% | 81.13% |
| TP / FP / FN | 43 / 9 / 11 | 43 / 9 / 11 |
| Dictamen | APTO CON REVISION HUMANA TOTAL | APTO CON REVISION HUMANA TOTAL |
| `verdict_scope` | COMPLETO | COMPLETO |

**P/R/F1 identicos, y es lo esperado.** El emparejamiento es por par
sujeto-predicado-objeto: mide **que pares se generan**. El ensemble no genera ni
elimina pares; **recalibra el CONSENSO**. Por construccion, P/R/F1 no pueden
moverse.

### 9.2 Donde SI se mide la diferencia: la decision

| Metrica | `baseline1` | `ensemble_offline` |
|---|---|---|
| `decision_correct` | 30.23% (13/43) | **39.53% (17/43)** |
| Confusion ACCEPT → ACCEPT | 9 | **13** |
| Confusion REJECT → ACCEPT (error grave) | 4 | **2** |

Cuatro decisiones mas acertadas y la mitad de casos en que un REJECT del ground
truth se propone como ACCEPT: **calidad de decision, no cobertura**.

### 9.3 Comparativa de los cuatro modos offline

| Modo | context_mode | P | R | F1 | pares | tasa humana | conflictos | llamadas | dictamen |
|---|---|---|---|---|---|---|---|---|---|
| `baseline1` | sentence | 82.7% | 79.6% | 81.1% | 52 | 38.5% | 13 | 0 | APTO CON REVISION HUMANA TOTAL |
| `baseline2` | paragraph | 36.1% | 96.3% | 52.5% | 144 | 52.8% | 33 | 0 | APTO CON REVISION HUMANA TOTAL |
| `ensemble_offline` | sentence | 82.7% | 79.6% | 81.1% | 52 | 38.5% | 13 | 0 | APTO CON REVISION HUMANA TOTAL |
| `full_offline` | segment | 36.1% | 96.3% | 52.5% | 144 | 52.8% | 33 | 0 | APTO CON REVISION HUMANA TOTAL |

Ampliar el contexto sube el recall a 96.3% hundiendo la precision a 36.1%. El
dictamen se emite sobre `baseline1`.

### 9.4 Calidad estructural (sobre los 43 TP)

| Atributo | Correctos / Total | Tasa |
|---|---|---|
| predicate_correct | 11/43 | 25.6% |
| direction_correct | 27/43 | 62.8% |
| direction_orientation_ok | 33/43 | 76.7% |
| types_correct | 43/43 | 100.0% |
| negation_correct | 39/43 | 90.7% |
| temporal_correct | 19/43 | 44.2% |
| epistemic_correct | 37/43 | 86.1% |
| evidence_correct | 39/43 | 90.7% |
| offsets_correct | 40/43 | 93.0% |
| workspace_correct | 43/43 | 100.0% |
| decision_correct (`baseline1`) | 13/43 | 30.2% |

### 9.5 Metricas operativas

| Contador | Valor |
|---|---|
| documents / segments / segments_processed | 16 / 16 / 16 |
| segments_failed / errors | 0 / 0 |
| entities | 93 |
| pairs_potential / generated / discarded | 236 / 52 / 184 |
| candidates_evaluated | 52 |
| results_strong / partial / conflict / invalid / human | 0 / 19 / 13 / 0 / 20 |
| tasa humana / conflicto / invalida | 38.5% / 25.0% / 0.0% |

Los tiempos absolutos dependen de la maquina y no son un resultado del benchmark.

**Nota sobre el contador de llamadas** (`provider_cost.calls_counter_note`): el
valor viene de `summary.local_calls_simulated` / `external_calls_simulated`. **El
sufijo `_simulated` es historico y NO implica simulacion**: cuenta llamadas
**REALES** cuando hay transporte inyectado. Hay alias aditivos `local_calls` /
`external_calls` en `metrics.operational.counters` y en cada fila de `all_modes`.

## 10. Gates vigentes

Umbrales en `report.py::THRESHOLDS`. Corpus completo, `baseline1` (identicos en
`ensemble_offline`):

| Gate | Estado | Valor | Umbral | Tipo |
|---|---|---|---|---|
| determinism | **PASS** | - | - | DURO |
| workspace_contamination | **PASS** | - | - | DURO |
| `provider_transport` | *(no aplica: modo offline)* | - | - | DURO |
| simple_relations | **PASS** | 93.33% | 80% | calidad |
| evidence | **PASS** | 90.70% | 80% | calidad |
| offsets | **PASS** | 93.02% | 90% | calidad |
| negation | **PASS** | 100.0% | 80% | calidad |
| temporality | **PASS** | 76.00% | 60% | calidad |
| rumors | **PASS** | 100.0% | 60% | calidad |
| predicate_structural | **FAIL** | 25.58% | 50% | calidad |

**Unico FAIL de calidad real: `predicate_structural`.** Temporalidad y rumores,
que fallaban en versiones anteriores de este documento, hoy pasan (Bloques 4 y 5).

Dictamen vigente: **APTO CON REVISION HUMANA TOTAL** (`verdict_scope = COMPLETO`).
El vocabulario **no** incluye «APTO PARA INGESTA REAL»: el pipeline es un
propositor en modo sombra / dry-run.

## 11. Submuestra acotada (6 fuentes), 2026-07-20

`--sources src-01,src-02,src-03,src-04,src-05,src-06`, offline:

| Metrica | `baseline1` | `ensemble_offline` |
|---|---|---|
| Precision / Recall / F1 | 0.7407 / 0.7692 / 0.7547 | 0.7407 / 0.7692 / 0.7547 |
| TP / FP / FN | 20 / 7 / 6 | 20 / 7 / 6 |
| Llamadas / fallos de transporte | 0 / 0 | 0 / 0 |
| Determinista | True | True |

> ### ADVERTENCIA ESTADISTICA
>
> **Con ~25-26 candidatos, una diferencia pequeña de F1 NO es estadisticamente
> significativa.** La submuestra sirve para verificar que la tuberia **funciona**
> y para medir **coste y latencia**; **no** para declarar que un modelo es mejor
> que otro. Con 54 relaciones de ground truth, tambien en el corpus completo las
> diferencias pequeñas deben tratarse con prudencia.

## 12. Ejecucion real acotada (Ollama) — MEDIDA el 2026-07-20

Unica seccion con llamadas a un LLM.

### 12.1 Condiciones

| Parametro | Valor |
|---|---|
| Modo | `ollama_shadow` (doble llave concedida) |
| Submuestra | `src-01`…`src-06` |
| Modelo | `qwen2.5:7b` (7,6 B, Q4_K_M, contexto 4096) |
| Servidor | Ollama local **en CPU, SIN GPU** (`size_vram: 0`, `llama-server` a ~596 % de CPU) |
| Endpoint | `http://127.0.0.1:11434/v1/chat/completions` |
| IA externa (NVIDIA) | **NO EJECUTADA** (§12.6) |

### 12.2 Coste y latencia REALES

| Magnitud | Valor |
|---|---|
| Candidatos evaluados | 27 |
| Llamadas al LLM local | **18** (9 `SKIPPED`) |
| p50 | **97 775 ms (97,8 s)** |
| p95 | **159 269 ms** |
| Maximo | **175 690 ms (175,7 s)** |
| Tiempo total | **1 680 219 ms ≈ 28 min** (6 fuentes) |
| Por candidato / por documento | 62 230 ms / 280 037 ms |
| `timeouts` / `errors` / fallos de transporte | 0 / 0 / **0** |

### 12.3 Consecuencia: el timeout se subio a 300 s

Con el valor de entonces (180 s) el maximo medido quedaba a **4,3 s** del limite.
Esa medicion es la que justifico elevarlo a **300 s** (§4.1) y **cerro** el riesgo.

### 12.4 Calidad: las 18 respuestas fueron RECHAZADAS

| Tasa | Valor |
|---|---|
| `invalid_rate` | **0.6667** (18/27) |
| `human_rate` | 0.3333 (9/27) |
| `results_strong` / `partial` / `conflict` | 0 / 0 / 0 |

| Motivo | Nº |
|---|---|
| `offsets_do_not_match_evidence` | **10** |
| `no_relation_extracted` | 7 |
| `evidence_not_in_document` | 1 |

**Confirma sobre el CORPUS REAL el hallazgo transversal de los Bloques 1 y 2**,
hasta ahora solo visto en casos sinteticos: evidencia plausible con **offsets
incorrectos**, rechazada con seguridad por la validacion estricta.

### 12.5 Impacto en las metricas: NINGUNO, y es lo esperado

P/R/F1 = 0.7407 / 0.7692 / 0.7547 (TP 20, FP 7, FN 6), **identicos** a
`baseline1` y `ensemble_offline` sobre la misma submuestra. El modo sombra
**nunca decide**: no puede cambiar que pares se extraen, solo aporta señal de
consenso. Es la **confirmacion de que la garantia de sombra se cumple**.

### 12.6 IA externa (NVIDIA): MEDIDA — ver §12A

**Actualizacion (2026-07-21).** Cuando se escribio esta seccion originalmente
NVIDIA no se habia ejecutado por falta de clave de API. Eso ya **no es el
estado vigente**: con clave valida se midio de verdad el carril externo, y en
el proceso se descubrio y corrigio el defecto `external_model` (§7A) que lo
habia bloqueado. Los datos completos estan en la nueva §12A. El alcance
`PARCIAL` del dictamen del bloque **ya no es por NVIDIA no ejecutada**; el
`PARCIAL` que queda es por `determinism` no evaluado en la ruta CLI (§6, §13.13
actualizado), un motivo **distinto**.

### 12.7 Recombinacion validada con datos REALES

Se volcaron los 27 payloads y `--recombine-from` reprodujo el run con **0
llamadas** y P/R/F1 identicos: funciona sobre respuestas reales del modelo, no
solo en tests sinteticos. **Reanalizar estas respuestas es gratis.**

### 12.8 Extrapolacion de coste (ESTIMACION, no medida)

6 fuentes → 28 min; las 16 del corpus ≈ **75 min** *solo* con Ollama, en esta
maquina y **sin GPU**. Extrapolacion lineal. Coherente con la estimacion previa de
5-20 h para una pasada completa con **ambos** proveedores y repeticiones.

### 12.9 Trazabilidad

El run se ejecuto con el codigo **PREVIO** a las correcciones (el proceso ya tenia
los modulos cargados). La recombinacion posterior si uso codigo corregido y **da
lo mismo**. El manifiesto de procedencia (§7) es **posterior** a este run, igual
que todo lo de las rondas 2 y 3: **ninguna de las mediciones de esta seccion se
tomo con el codigo congelado que describe el resto del documento.**

## 12A. Ejecucion real acotada (NVIDIA) — MEDIDA el 2026-07-21

Segunda seccion con llamadas a un LLM real. Tras corregir el defecto `external_model`
(§7A), se ejecuto `nvidia_shadow` con clave de API valida sobre la **misma**
submuestra de 6 fuentes usada con Ollama (§12).

### 12A.0 El defecto que este run destapo

El **primer** intento de ejecutar NVIDIA con clave real fallo con 404
(`ProviderNotFoundError`) en las 5 primeras llamadas, contabilizado como fallo de
**transporte**: exactamente el sintoma que predice §7A. Ese fallo **es** la
evidencia empirica del defecto `external_model` — no se detecto leyendo codigo, se
detecto **midiendo**. Corregido el defecto (guarda + flag + threading, §7A), la
segunda ejecucion es la que se documenta abajo.

### 12A.1 Condiciones

| Parametro | Valor |
|---|---|
| Modo | `nvidia_shadow` (doble llave concedida) |
| Submuestra | `src-01`…`src-06` (las **mismas** fuentes que §12) |
| Modelo pedido en `--external-model` | `meta/llama-3.3-70b-instruct` |
| Modelo configurado por el operador (`EnvironmentFile`) | `meta/llama-3.1-70b-instruct` — **RETIRADO** para inferencia: aparece listado por el healthcheck pero responde **404** si se invoca. Se uso el **3.3-70b**, vigente |
| Endpoint | `https://integrate.api.nvidia.com` |
| Healthcheck previo | clave valida, `ok: true`, **118 modelos NIM** disponibles |
| LLM local (Ollama) | **NO EJECUTADO** en este run (`local_llm: NOT_EXECUTED`) |

**Sin fugas de secretos.** La API key no se imprimio ni se serializo en ningun
artefacto de este run (verificado: ningun prefijo `nvapi-` aparece en el JSON de
resultados ni en el JSONL de payloads).

### 12A.2 Transporte: 27/27 respondidas, 0 fallos

| Magnitud | Valor |
|---|---|
| Candidatos evaluados / llamadas intentadas | 27 |
| Llamadas **respondidas** | **27** |
| Errores de transporte | **0** |
| Llamadas indeterminadas | **0** |
| `external_ai` | `EXECUTED` |
| `local_llm` | `NOT_EXECUTED` |
| `status_consistency` | `OK` |
| Atestacion de endpoint | `https://integrate.api.nvidia.com` |
| `network` | `yes (27 llamadas a proveedor contabilizadas; 0 fallos de transporte)` |
| Gate `provider_transport` | `PASS` |

### 12A.3 Latencia REAL (NVIDIA, 27 muestras)

| Magnitud | Valor |
|---|---|
| p50 | **29 434 ms (~29,4 s)** |
| p95 | **89 354,6 ms (~89,4 s)** |
| Maximo | **125 862 ms (~125,9 s)** |

Comparado con Ollama (§12.2, `qwen2.5:7b` en CPU sin GPU): p50 **97 775 ms
(~97,8 s)**. **NVIDIA respondio con p50 unas 3,3x mas rapido que el Ollama local en
esta maquina** — esperable: NVIDIA sirve el modelo en infraestructura NIM dedicada,
mientras que el Ollama medido corria en CPU sin GPU. No es una comparacion de
"calidad de modelo", solo de latencia de transporte.

### 12A.4 Impacto en las metricas: NINGUNO — la garantia de sombra, confirmada de nuevo con un SEGUNDO proveedor

| Metrica | Valor |
|---|---|
| Precision / Recall / F1 | **0.7407 / 0.7692 / 0.7547** |
| TP / FP / FN | 20 / 7 / 6 |

**Identicos byte a byte a `baseline1`, `ensemble_offline` y a la ejecucion real de
Ollama (§12.5)** sobre la misma submuestra de 6 fuentes. El modo sombra **nunca
decide, aprueba ni escribe**: el proveedor externo aporta solo señal de consenso.
Que dos proveedores completamente distintos — un modelo local de 7B y uno alojado
de 70B — den el **mismo** P/R/F1 es la confirmacion mas fuerte disponible de que la
garantia de sombra se cumple: **ningun proveedor mueve las metricas del pipeline**.

### 12A.5 Calidad: las 27 respuestas fueron RECHAZADAS — pero por un motivo UNIFORME y distinto al de Ollama

| Tasa | Valor |
|---|---|
| `invalid_rate` | **1.0 (27/27)** |
| `results_strong` / `partial` / `conflict` | 0 / 0 / 0 |

**Las 27 respuestas fueron rechazadas por la validacion estricta, y las 27 con el
mismo marcador exacto:** `evidence_text vacia o ausente` (verificado leyendo los 27
registros del JSONL de payloads: `validation_errors` es identico en los 27). Un
fallo **100% uniforme en el mismo campo** apunta a un desajuste sistematico de
**contrato/prompt** — el modelo no devuelve la evidencia en la forma que espera el
validador —, **no** a una incapacidad del modelo para razonar sobre las relaciones.

**No leer esto como "NVIDIA es peor que Ollama".** Es la **misma** clase de cuello
de botella transversal que ya documentaban los Bloques 1 y 2 y que §12.4 confirmo
sobre el corpus real con Ollama, manifestada de otra forma:

| Proveedor | Modelo | Tasa de rechazo | Motivo(s) |
|---|---|---|---|
| Ollama | `qwen2.5:7b` (7,6B, local) | 18/27 (66,7%) | `offsets_do_not_match_evidence` (10), `no_relation_extracted` (7), `evidence_not_in_document` (1) |
| NVIDIA | `meta/llama-3.3-70b-instruct` (70B, alojado) | 27/27 (100%) | `evidence_text vacia o ausente` (27/27, uniforme) |

Ollama devuelve evidencia con **offsets incorrectos**; NVIDIA a menudo **no
devuelve** el campo `evidence_text` en absoluto. Son sintomas distintos del **mismo**
problema raiz: el anclaje de evidencia (`evidence_text`/offsets) al contrato que
espera el validador. **Ningun cambio de modelo, local o alojado, de 7B o de 70B,
lo resuelve**; la correccion vive en el prompt/contrato de `pipeline.py`, **fuera
del alcance del Bloque 7** (ver §13.4, §13.12).

### 12A.6 Veredicto del run NVIDIA

`APTO CON REVISION HUMANA TOTAL`, `verdict_scope: PARCIAL (gates duros no
evaluados: determinism)`. El motivo del `PARCIAL` es que la ruta CLI no evalua
determinismo en modos con proveedor (comportamiento ya documentado, §6) — **no**
por NVIDIA sin ejecutar.

### 12A.7 Comparacion honesta: NO forzar una equivalencia llamada-a-llamada

Ollama real (§12) hizo **18** llamadas sobre src-01…src-06 (9 candidatos
`SKIPPED`); NVIDIA hizo **27** sobre las **mismas** fuentes. La diferencia no es un
error de medicion: el numero de candidatos que ve cada carril difiere entre el LLM
local y el externo dentro del propio pipeline (rutas de evaluacion distintas por
carril). **No se fuerza** una comparacion llamada-a-llamada; se compara lo
comparable:

| Dimension | Comparable? | Resultado |
|---|---|---|
| P/R/F1 de existencia | Si (misma submuestra, mismo ground truth) | **Identicos** entre Ollama, NVIDIA y offline: 0.7407 / 0.7692 / 0.7547 |
| Transporte (fallos, indeterminadas) | Si | Ambos: 0 fallos, 0 indeterminadas |
| Latencia (p50/p95/max) | Si (mismas 6 fuentes) | Ollama p50 97,8 s vs NVIDIA p50 29,4 s |
| Tipo de rechazo de calidad | Si, cualitativamente | Distinto (offsets vs evidence_text ausente), **misma raiz** (anclaje de evidencia) |
| Numero de llamadas (18 vs 27) | **No** — no comparar como si midiera lo mismo | Depende de como cada carril del pipeline genera candidatos, no del proveedor |

### 12A.8 Trazabilidad

Corpus, ground truth y `code_sha` identicos a los de §12. Payloads volcados (27
registros JSONL); ningun `nvapi-` presente. Este run se ejecuto **con el codigo ya
corregido** de la ronda 4 (a diferencia del run de Ollama en §12.9, que se lanzo con
codigo previo a correcciones): el defecto `external_model` estaba **ya resuelto**
cuando se tomo esta medicion.

## 13. Limites conocidos

1. **Una pasada completa con proveedores reales es inviable como rutina.** Con la
   latencia medida (p50 97,8 s; 28 min para 6 fuentes en CPU sin GPU), el corpus
   completo solo con Ollama se estima en **~75 min**; con ambos proveedores y
   repeticiones, **5-20 h**.
2. **No hay cache efectiva en la ruta de relaciones.**
   `evaluate_relation_external` llama directamente a `provider._post_chat(...)`,
   evitando la `ResponseCache` de `external_ai.openai_compatible`. Repetir una
   ejecucion repite integramente el coste; se mitiga con
   `--out-payloads`/`--recombine-from`.
3. **El emparejamiento no puede medir el efecto del ensemble en P/R/F1.** Hay que
   mirar `decision_correct` y la matriz de confusion.
4. **Anclaje de evidencia (Bloques 1 y 2, CONFIRMADO en §12.4 y §12A.5, con DOS
   proveedores reales distintos).** Ollama (`qwen2.5:7b`, local) produce evidencia
   **con offsets incorrectos** (10/18 rechazos por `offsets_do_not_match_evidence`).
   NVIDIA (`meta/llama-3.3-70b-instruct`, alojado) falla de otra forma: **27/27**
   respuestas rechazadas, **todas** por `evidence_text vacia o ausente` — el campo
   de evidencia falta o llega vacio. Son sintomas distintos del **mismo** cuello de
   botella transversal: el anclaje de evidencia al contrato que exige el validador.
   **La prioridad siguiente es corregir ese anclaje (prompt/contrato en
   `pipeline.py`), no cambiar de modelo** — 7B local y 70B alojado fallan por la
   misma raiz — **ni relajar la validacion**.
5. **Los contadores operativos y las tasas de consenso proceden del `summary` del
   pipeline (consenso BASE)**, tambien en `ensemble_offline`. La recalibracion se
   refleja en las predicciones y en `decision_correct`, no en esos contadores.
6. **Los modos no aislan etapas.** R8 es monolitico; los modos offline solo varian
   el `context_mode`.
7. **La derivacion de entidades de entrada procede del ground truth.** El
   benchmark mide extraccion de **relaciones**, no reconocimiento de entidades.
8. **El umbral de transporte del 10 % no esta calibrado con datos reales de fallo
   de VM105.** Eleccion de diseño razonada (§5.3).
9. **El deadline global de run existe (`--max-run-seconds`, §4.0.1) pero es
   OPCIONAL y de granularidad por FUENTE.** Sin la bandera no hay presupuesto
   global; con ella, el corte se comprueba **entre fuentes**, asi que una unica
   fuente muy lenta puede rebasarlo antes de la siguiente comprobacion. El
   deadline **por llamada** sigue siendo de **330 s** (300 + 30 de margen).
   *(Correccion: versiones anteriores de este documento afirmaban «no existe
   deadline global de run». Era cierto antes de la ronda 3; ya no lo es.)*
10. **La atestacion de red en modo con proveedor es INCOMPLETA, nunca falsa.**
    Puede publicar `yes (proveedores ejecutados)` con `network_calls_counted: 0`.
    Afirma red del lado conservador, pero no prueba el numero de llamadas.
11. **`status_consistency` solo cubre de verdad UNA de sus dos direcciones.** La
    direccion «`EXECUTED` con 0 llamadas» **si ocurre** en runs reales y se
    declara (N8). La direccion «llamadas sin ningun `EXECUTED`» es **inalcanzable
    hoy** y es **codigo defensivo**: no debe presentarse como control efectivo.
    *(Correccion: versiones anteriores declaraban inalcanzable el mecanismo
    ENTERO. Era una descripcion pesimista y ya inexacta.)*
12. **La causa raiz de `provider_error` sigue viva en
    `relations/external_ai_shadow.py`, FUERA de alcance.** Su
    `except _PROVIDER_ERRORS` agrupa `InvalidResponseError` con los errores de
    red, y **no se ha modificado**. El benchmark solo **mitiga** el efecto leyendo
    el nombre de la excepcion (§5.2); cuando el nombre no basta, la llamada queda
    **INDETERMINADA**: ni transporte ni calidad. **Esa zona gris es una limitacion
    abierta**, no un problema resuelto — cerrarla exige tocar
    `external_ai_shadow.py`, que es otro bloque.
13. ~~**NVIDIA sigue SIN EJECUTAR**~~ **MEDIDA el 2026-07-21 (§12A).** 27 llamadas
    reales a `meta/llama-3.3-70b-instruct`, 0 fallos de transporte, P/R/F1
    identicos a Ollama y a offline. **El alcance `PARCIAL` del dictamen del bloque
    ya NO es por esta razon**: el motivo que queda es `determinism` no evaluado en
    la ruta CLI (§6, §12A.6), un motivo distinto y ya documentado. Lo que sigue
    abierto de NVIDIA: las 27 respuestas fueron rechazadas por calidad (100%
    `evidence_text vacia o ausente`, §12A.5) — no es un problema de ejecucion,
    es la misma limitacion transversal del punto 4.
14. **Las correcciones estan validadas offline, con transporte inyectado, y con DOS
    ejecuciones reales acotadas.** El run de Ollama (§12) se lanzo con el codigo
    **previo** a las correcciones de las rondas 2 y 3 (posteriores a ese run); el
    run de NVIDIA (§12A) se lanzo **ya con el codigo corregido** de la ronda 4,
    incluida la guarda `require_external_model`. Ninguno de los dos cubre una
    pasada completa (16 fuentes) con proveedores reales.
15. **El manifiesto de payloads NO es autenticidad sin clave de operador**
    (§7.3): sin `S9K_BENCH_MANIFEST_HMAC_KEY` cualquiera con el repositorio puede
    emitir un manifiesto valido, y nada prueba que los payloads procedan de
    llamadas reales a un proveedor.

## 14. Estado de produccion

Intacta. Las mediciones son offline y en el worktree de desarrollo, salvo la §12
(**Ollama local**) y la §12A (**NVIDIA real, endpoint
`https://integrate.api.nvidia.com`), ambas en modo sombra, dry-run y sin
escrituras (`results_strong = 0` en las dos). No se toco VM105, Neo4j, `auth.db`,
`jobs.db`, timers ni servicios. `S9K_ALLOW_REAL_INGEST = off`. Ingestas reales: 0.
La clave de API de NVIDIA no se imprimio ni se serializo en ningun artefacto.
