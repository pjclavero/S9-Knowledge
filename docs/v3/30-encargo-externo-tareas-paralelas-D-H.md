# Encargo externo — tareas paralelas D · E · F · G · H

Fecha: 2026-07-29 · Estado: **especificado, listo para implementar**
Destinatario: equipo externo (Codex u otro). Documento autocontenido.

> **Regla dura del programa, sin excepciones.**
> Una entrega sin tests **escritos Y EJECUTADOS** no se acepta, y no se revisa.
> Se entrega la salida real de la ejecución, **con el número de tests**, no una
> captura verde. Un test que pasa solo cuenta si su mutación correspondiente lo
> pone en rojo.

---

## 0. Cómo usar este documento

Cinco tareas **independientes entre sí**. Cada una es una rama y un PR **sin merge**.
Pueden hacerse en paralelo por personas distintas; el orden entre ellas da igual.

| | Tarea | Toca | Depende de |
|---|---|---|---|
| **D** | Panel de proveedores y multiproveedor por carril | Config + UI | — |
| **E** | Eje temporal de campaña | `metadata` + consultas | — |
| **F** | Política de negaciones: del extractor al motor | **Motor** | docs 18 y 19 |
| **G** | Observabilidad del pipeline | Instrumentación | doc 17 |
| **H** | Registro del bucle de revisión humana | Persistencia | doc 20 |

**Solapamiento a vigilar:** D y G tocan ambas el registro de proveedores, y F y G
tocan ambas métricas. Coordinar nombres de métrica leyendo el anexo antes de
inventarlos; **si dos ramas crean la misma métrica con nombres distintos, ambas se
rechazan**.

**Restricciones vinculantes para las cinco** (§6 al final). Léelas antes de empezar.

---

## D · Panel de proveedores y multiproveedor por carril

### Problema

Hoy las credenciales viven en `/etc/s9-knowledge/providers.env` (0600 root:root) y
**cambiar de proveedor o de endpoint exige entrar por SSH y editar un archivo**. Eso
no es desplegable fuera de este homelab. Y hay una limitación real: **cada carril
admite un solo proveedor**. No se puede tener dos para OCR ni dos para visión, ni
tener recambio cuando uno falla o se agota.

### Qué se pide

**1. Panel de gestión** para dar de alta proveedores: nombre, tipo, endpoint base,
modelo, credencial, carriles que sirve, orden de preferencia, activo sí/no.

**2. Varios proveedores por carril**, con orden de preferencia y recambio
automático. Un carril declara una **lista** ordenada, no un proveedor.

**3. Recambio ante fallo**, disparado por: error de transporte, 5xx, 429, timeout, y
**404 de modelo no habilitado** — que es un caso real medido: `kimi-k2.6` aparece en
`/models` y devuelve `"Function '23d4f03a-…': Not found for account"`, mientras un
control con `llama-3.3-70b` devuelve 200. Un modelo listado **no** es un modelo
disponible.

**4. Prueba de conexión** desde el panel: botón que hace una llamada mínima real y
enseña código, latencia y si el modelo responde de verdad. Sin esto, dar de alta un
proveedor es a ciegas.

### Manejo de credenciales

- Cifradas en reposo con una clave maestra del entorno, **nunca en claro en la BD**.
- **Nunca** se devuelven al frontend. El panel muestra `nvapi-…3f7a` y nada más.
- **Nunca** aparecen en logs, trazas, mensajes de error ni respuestas de la prueba de
  conexión. Test explícito de esto.
- Se mantiene `providers.env` como **fuente de arranque** (bootstrap): si la BD está
  vacía, se siembra desde ahí. No se rompe el despliegue actual.

### Lo que NO se pide

Integración con Vaultwarden ni con ningún gestor externo. **Decisión tomada**: obliga
a desplegar y configurar una pieza más allá donde se instale el proyecto, y el
objetivo es justo lo contrario.

### Tests obligatorios

| # | Caso | Esperado |
|---|---|---|
| D1 | Alta de proveedor | Persiste; credencial cifrada en reposo |
| D2 | Lectura vía API | Credencial **enmascarada**, nunca completa |
| D3 | Provocar error de proveedor | Credencial **ausente** del mensaje y del log |
| D4 | Dos proveedores en un carril, el primero da 500 | Usa el segundo |
| D5 | Primero da 429 | Usa el segundo |
| D6 | Primero da 404 modelo no habilitado | Usa el segundo |
| D7 | Todos caídos | Error claro, **no** silencioso, **no** resultado vacío |
| D8 | Orden de preferencia | Respetado y determinista |
| D9 | Proveedor inactivo | No se usa nunca |
| D10 | BD vacía | Siembra desde `providers.env` |
| D11 | Contenido marcado privado | **Nunca** sale a proveedor externo, ni sin locales disponibles (§6) |
| D12 | Prueba de conexión | Reporta código y latencia reales, sin filtrar la clave |

---

## E · Eje temporal de campaña

### Problema

El ledger ya es bitemporal —tiempo de validez y tiempo de transacción— y la
supersesión ya permite que un hecho reemplace a otro sin borrarlo. **Lo que falta es
el ancla de campaña**: no se puede preguntar "qué se sabía al final de la sesión 4"
porque los episodios no llevan sesión ni fecha de juego.

Es barato porque **el episodio ya es la unidad de todo el sistema**: es un filtro
sobre lo que ya existe, no una estructura nueva.

### Qué se pide

En `metadata` del episodio (**los esquemas congelados no se tocan**, §6):

| Campo | Tipo | Obligatorio |
|---|---|---|
| `session_id` | string | no |
| `in_game_date` | string | no |

Y una consulta: **el estado del grafo tal como era al final de una sesión dada**,
apoyada en el ledger que ya existe.

`in_game_date` es **string libre**, deliberadamente: los calendarios de campaña no
son gregorianos y forzar un formato pierde información. El orden se establece por
`session_id`, que sí es ordenable. **No inventar un parser de fechas de fantasía.**

### Tests obligatorios

| # | Caso | Esperado |
|---|---|---|
| E1 | Episodio sin los campos | Funciona igual que hoy |
| E2 | Ingesta con sesión y fecha | Persisten y son consultables |
| E3 | Hecho sustituido en la sesión 7 | Consulta a sesión 4 devuelve **el valor antiguo** |
| E4 | Consulta a sesión posterior | Devuelve el valor nuevo |
| E5 | Sesiones sin episodios | No rompe; devuelve vacío |
| E6 | Episodios sin `session_id` mezclados | No desaparecen de la vista global |
| E7 | Esquemas de contrato | Hash **sin cambios** |

---

## F · Política de negaciones: del extractor al motor

> **La tarea más delicada de las cinco. Toca el motor.** Leer **doc 18** y **doc 19**
> enteros antes de escribir una línea.

### Problema

En `data-engine/app/knowledge_v3/extraction/deterministic.py:643-649` hay hoy un
freno universal (verificado el 2026-07-29):

```python
review = bool(
    negated                      # <-- el freno: toda negación va a revisión
    or hint != "ASSERTED"
    or confidence < 0.6
    or low_quality(episode)
    or phrase_anchor.ambiguous
)
```

**Toda** afirmación negada va a revisión humana. Fue correcto ponerlo
—se descubrió que el sistema confundía *"dejó de liderar"* con *"no dejó de
liderar"*— pero es una decisión tomada **en el extractor**, y el extractor propone,
no decide. La política pertenece al motor.

### Qué se pide

**1. Retirar la decisión del extractor.** Este emite `negated`, `negation_kind`,
alcance y evidencia: **datos, no decisiones**.

**2. Implementar la política del doc 18 en el motor**, por tipo:

- **Negación simple** y **NEVER**: autoaprobables, con las 7 condiciones del doc 18.
- **Cesación**: **siempre** `REVIEW_NEGATION_CESSATION`. Sin excepciones.
- **Negación de cesación**: `REVIEW_NEGATION_SCOPE`.
- **`NOT_YET` y alcance ambiguo**: a revisión.

**3. `scope_confidence` la calcula el motor, LOCALMENTE.** No se acepta del LLM. Un
modelo puntuando su propia confianza no es evidencia.

**4. Modo sombra para cesaciones** (doc 18 §5). El motor calcula qué **habría**
cerrado y lo registra **sin cerrarlo**; el ítem sigue yendo a revisión. Cuando el
humano decide, se compara. Con unas decenas de casos reales se sabe si el motor
acierta — con datos de producción, gratis, usando la cola que ya existe.

### La puerta

Las cuatro métricas del doc 18 §4:

```
false_positive_positive_edge            = 0
false_cessation_from_negated_cessation  = 0
evidence_grounding                      = 100 %
scope_accuracy                          suficientemente alta
```

**Y la quinta, que es la que impide hacer trampa:** *recall de autoaprobación* — de
las negaciones simples que **deberían** aprobarse, ¿cuántas se aprueban? Un sistema
tan conservador que autoaprueba 0 de 10 cumple las cuatro de arriba y **no sirve para
nada**. Se miden las dos caras o la puerta premia la parálisis.

Por encima de todo: **"no dejó de X" nunca puede convertirse en "dejó de X"**.

### Corpus

Usar el split `negation` (doc 19). **Solo lectura**: no se modifica, no se amplía, no
se corrige un caso porque "está mal etiquetado" — eso se reporta, no se arregla.

### Tests obligatorios

| # | Caso | Esperado |
|---|---|---|
| F1 | `deterministic.py:643` | El freno universal **ya no está ahí** |
| F2 | Extractor con texto negado | Emite datos; **no** decide revisión |
| F3 | Batería completa doc 19 | Ejecutada; resultados reportados por tipo |
| F4 | *"no dejó de liderar"* | **Jamás** produce arista de cesación |
| F5 | Cesación simple | **Siempre** `REVIEW_NEGATION_CESSATION` |
| F6 | Negación de cesación | `REVIEW_NEGATION_SCOPE` |
| F7 | `scope_confidence` del LLM | **Ignorado**; se recalcula local |
| F8 | Modo sombra | Registra, **no cierra**; el ítem sigue en revisión |
| F9 | Recall de autoaprobación | **Medido y reportado**, no omitido |
| F10 | Negación simple ambigua | A revisión |
| F11 | `NOT_YET` | A revisión |
| F12 | Mutación de la política | Los tests se ponen **en rojo** |

---

## G · Observabilidad del pipeline

### Contexto imprescindible

**La observabilidad de este homelab es InfluxDB v2 + Telegraf + `pvestatd`. NO hay
Prometheus, y está prohibido montar uno.** Ya se auditó (doc 17 §1).

Decisión tomada: la aplicación expone `/metrics` **en formato Prometheus** y
**Telegraf lo recoge** (`inputs.prometheus`) escribiendo a InfluxDB. Instrumentación
estándar y portable, sin exporter duplicado, y Grafana lo consume por el datasource
que ya existe.

### Qué falta (doc 17 §1)

1. Métricas internas del guest: presión PSI, swap, page faults, OOM kills, RSS por
   proceso. `pvestatd` ve la VM desde fuera; **no ve qué proceso consume dentro**.
2. Métricas por servicio: Ollama, workers, motor, Neo4j.
3. Métricas de aplicación: etapas del pipeline, proveedores, colas.
4. Dashboards **por VM**: el actual solo cubre el host.

### Nombres

Los del anexo: `s9_stage_duration_seconds`, `s9_claims_*`, `s9_provider_*`, con
etiquetas `stage`/`provider`/`model`/`pipeline_mode`/`result`/`modality`/
`negation_kind`.

**Prohibidas las etiquetas de alta cardinalidad**: nada de `run_id`, ids de episodio,
rutas, textos ni hashes completos. Eso va a logs e informes. Una sola etiqueta de
alta cardinalidad puede tumbar la serie temporal, y es difícil de revertir.

**Vigilar roles, no máquinas** (doc 17): `llm_host`, `engine_host`, `graph_host`,
`hypervisor`. Las VMs se mueven; los roles no.

### Tests obligatorios

| # | Caso | Esperado |
|---|---|---|
| G1 | `/metrics` | Responde en formato Prometheus válido |
| G2 | Nombres y etiquetas | Coinciden con el anexo |
| G3 | Etiqueta de alta cardinalidad | **Rechazada** por test, no por convención |
| G4 | Etapa del pipeline | Emite `s9_stage_duration_seconds` |
| G5 | Fallo y recambio de proveedor | Contabilizados por separado |
| G6 | Config de Telegraf | Válida; scrape verificado |
| G7 | Métricas por rol | Etiquetadas por rol, no por hostname |
| G8 | `/metrics` sin carga | No falla ni devuelve vacío |
| G9 | Coste de la instrumentación | Medido; **no** etapa dominante |

---

## H · Registro del bucle de revisión humana

### Problema

Hoy las decisiones humanas de la cola de revisión **se pierden**. Se aprueba o se
rechaza y no queda nada aprovechable. Es la fuente de verdad más valiosa del
sistema, gratis, y se está tirando.

Ojo: **H solo registra.** No aprende, no ajusta, no reentrena nada. Es la
infraestructura de datos sobre la que se construirá el Teacher Lab (doc 20) más
adelante. Un implementador que entregue "mejora automática del glosario" **ha
incumplido el encargo**, aunque funcione.

### Qué se pide

**1.** Cada decisión humana como dato de primera clase (doc 20 §2): qué se propuso,
qué decidió el humano, por qué, sobre qué evidencia, con qué ontología vigente.

**2.** Candidatos derivados: entradas de glosario y alias, predicados o ajustes de
dominio/rango del `GameProfile`, entidades canónicas y fusiones, casos de regresión.

**3. Todo candidato nace en estado `PROPOSED` y exige aprobación explícita.** Nunca
un cambio automático. El glosario y el perfil son datos **editables, versionados y
reversibles**.

> **Y la restricción que ya se marcó antes en el programa: el glosario no crece con
> las revisiones.** Un candidato `PROPOSED` **no** está en el glosario y **no** debe
> ser visible para ninguna etapa que consulte el glosario. Si lo fuera, el sistema
> se confirmaría a sí mismo: propone un término, lo registra, lo lee como conocido y
> sube su confianza. Test explícito de esto.

**4.** Procedencia obligatoria (doc 20 §4), incluidos `prompt_hash` —los prompts se
editan sin cambiar de versión— y `tokens`/`cost`, para saber si el laboratorio es
sostenible.

### Tests obligatorios

| # | Caso | Esperado |
|---|---|---|
| H1 | Decisión humana | Persistida con evidencia y ontología vigente |
| H2 | Candidato generado | Nace `PROPOSED` |
| H3 | **Candidato `PROPOSED`** | **Invisible** para las etapas que leen el glosario |
| H4 | Aprobar un candidato | Cambio versionado y **reversible** |
| H5 | Revertir | Deja el estado anterior exacto |
| H6 | Procedencia | Completa, con `prompt_hash`, `tokens`, `cost` |
| H7 | Cambio automático sin humano | **Imposible** por diseño, no por convención |
| H8 | Rechazo humano | Registrado igual que la aprobación (el negativo también enseña) |

---

## 6. Restricciones vinculantes (las cinco tareas)

- **NUNCA escribir en el Neo4j de producción** (`neo4j-knowledge`, VM105). Tests
  contra instancia efímera, destruida al terminar.
- **Contratos congelados** `v3-contracts-frozen-1.0.0`: `contracts/knowledge-v3/v1/`
  y `data-engine/app/knowledge_v3/contracts/` **no se tocan**. Todo excedente va en
  `metadata`, el único hueco con `additionalProperties` abierto.
- **No usar** el split `heldout` (sellado, un solo uso). El split `negation` es de
  **solo lectura**. **No modificar** el corpus gold.
- **No** `git commit --amend`, **no** `push --force`, **no** merge a `main`.
- **Claves de API**: jamás en código, logs, commits ni mensajes de error.
- **`PRIVATE_CONTENT_STAYS_LOCAL`**: el contenido marcado privado **no sale** a
  proveedores externos ni bajo saturación ni sin locales disponibles. Ante ausencia
  de proveedor local, **se falla**; no se degrada a la nube.
- **Principio de autoridad, que ordena toda la arquitectura**: los extractores y los
  LLM **proponen**; solo el motor local **aprueba**; solo el writer **escribe**, y
  solo planes firmados por el motor. Cualquier entrega donde un LLM apruebe algo se
  rechaza sin más revisión.
- **`jsonschema` es dependencia obligatoria** para ejecutar tests: sin ella el
  subsistema entero **se salta en silencio** y la suite sale verde sin haber probado
  nada. **Comprobar el NÚMERO de tests, no el color.**

## 7. Entrega

Rama propia por tarea, PR **sin merge**. En cada descripción:

1. Salida real de la ejecución de tests, **con el número de tests**.
2. Las métricas que la tarea exija medir (F: recall de autoaprobación; G: coste de
   instrumentación), con el material sobre el que se midieron.
3. Qué quedó fuera y por qué.

Se revisará contra este documento, punto por punto.
