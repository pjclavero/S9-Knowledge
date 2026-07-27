# Motor de relaciones de S9 Knowledge — Informe de desarrollo, resultados y guía de rediseño

**Fecha:** 2026-07-27 · **Autor:** supervisión técnica del programa ·
**Alcance:** todo el desarrollo del motor de extracción de relaciones hasta hoy, sus
resultados medidos, las causas de su bajo rendimiento, lo que sí funciona, y las costuras
que un motor nuevo debe respetar para sustituirlo **sin tocar el resto del sistema**.

> **Cifra que resume el informe:** el motor mide **predicado 0.8140** en el corpus con el
> que se desarrolló, **0.5385** en un held-out sintético y **0.2391** en material real de
> otros juegos. Todas las cifras de este documento han sido **reproducidas por el
> supervisor ejecutando el arnés**, no sólo reportadas por quien las produjo.

---

## 1. Qué se construyó y en qué orden

### 1.1. Programa "motor v2 híbrido" (PR #105, fusionado a `main` en `5ad9f18`)

Nueve bloques con editor + revisor independiente + supervisor. Base `dcded31`.

| Bloque | Entregó | Efecto medido en el corpus de desarrollo |
|---|---|---|
| B0 | Reconciliación ground-truth ↔ ontología (+9 canónicos) | neutro (habilitante) |
| B1 | `relations/ontology.py` — fuente única de predicados | neutro (habilitante) |
| B2 | **Corrección del medidor** + `predicate_selector.py` | predicado 0.209 → 0.814 |
| B3 | `direction.py` | dirección 0.628 → 0.930 |
| B4 | `temporal_v2.py` | temporal 0.442 → 0.884 |
| B5 | Parser opcional tras interfaz (spaCy/Stanza) | neutro (infraestructura) |
| B6 | `abstention.py` — consenso, abstención y rechazo | decisión +0.05; falsos ACCEPT 4→0 |
| B7 | IA externa como consultor (fragmentos) | **Δ = 0.0000** (sólo cierra puertas) |
| B8 | Informe y PR | — |

**Resultado publicado entonces:** los cuatro gates experimentales superados, con el caveat
—repetido en cada documento— de que el corpus tenía **n=54 y dev == test**, y de que el
rango honesto era **[0.42, 0.81]**.

### 1.2. Programa "v2 temporal/episódico" (rama `exp/relation-engine-v2-temporal-provenance-v1`)

| Bloque | Estado |
|---|---|
| B0 auditoría + baseline (`97b9a51`) | cerrado |
| Arreglo de CI en ramas `exp/**` (`76018a3`) | aplicado |
| B1 cierre de los 6 defectos abiertos (`0e4a6db`) | cerrado |
| **Corpus held-out H1 y H2** (rama `work/rel-v2e-b02-heldout`) | **entregados — motivo de este informe** |
| B3–B14 (episodios, ledger, supersession, procedencia…) | **NO EMPEZADOS** |

---

## 2. Ficheros creados y modificados

### 2.1. Módulos NUEVOS (todos bajo `data-engine/app/relations/`)

| Fichero | Responsabilidad |
|---|---|
| `ontology.py` | Fuente única: 20 predicados canónicos con familia, **dominio/rango**, simetría, inversa, alias y expresiones |
| `predicate_selector.py` | Genera candidatos de predicado, filtra por dominio/rango, puntúa y **se abstiene** |
| `direction.py` | Dirección: activa/pasiva/agente/inversa/simetría/preposición/correferencia |
| `temporal_v2.py` | Estados ACTIVE/ENDED/PLANNED/HYPOTHETICAL/RECURRING/UNKNOWN + vigencia |
| `abstention.py` | Motivos **estructurados** (catálogo cerrado) y veredicto NEUTRAL/ABSTAIN/REJECT |
| `external_consult.py` | Puerta de la IA externa: techo estructural, nunca autoridad |
| `fragment_protocol.py` | El modelo elige `fragment_ids`; el sistema reconstruye offsets |
| `evidence_realignment.py` | Realineamiento con **unicidad obligatoria** (o rechazo) |

### 2.2. Modificados

`pipeline.py` (orquestación y flags), `ensemble.py` y `consensus_adapter.py` (consenso),
`external_ai_shadow.py` (protocolo externo y **corrección de P0**), `syntax.py` (parser
opcional + caché), `schemas/rpg_schema.py` (+9 predicados),
`benchmark/{runner,report,matching,cli,metrics}.py` (arnés).

### 2.3. Lo que NO se tocó

`RelationCandidate/internal-v1` — **contrato de 20 campos, intacto**. El corpus B1 y su
ground truth, **diff cero**. Los umbrales de `review_policy.py`, **diff cero**.

---

## 3. Resultados medidos

### 3.1. La progresión que lo dice todo

| Métrica | B1 (dev == test, n=54) | H1 (held-out sintético) | **H2 (material real)** |
|---|--:|--:|--:|
| `predicate_correct` | 0.8140 | 0.5385 | **0.2391** |
| `temporal_correct` | 0.8837 | 0.5641 | **0.1957** |
| `strict_predicate.f1` | 0.6604 | 0.4565 | **0.1897** |
| `direction_correct` | 0.9302 | 0.8974 | **0.6957** |
| `evidence_correct` | 0.9302 | 0.8462 | 0.7174 |
| `pair_F1` | 0.8113 | 0.8478 | 0.7931 |
| offsets / tipos / workspace | ~1.0 | 1.0 | **1.0000** |
| Falsos ACCEPT | 0 | 0 | **2** (`ensemble_offline`) |
| **Falsos RECHAZOS** | 0 | 0 | **4** |

**El rango honesto [0.42, 0.81] no contiene la realidad.** De la ganancia v1→v2 de
**+0.6047** medida en el corpus de desarrollo, en material real sobrevive el **7 %**.

### 3.2. Tres hechos que invalidan conclusiones anteriores

1. **La dirección REGRESA.** En material real, v2 (0.6957) es **peor que v1** (0.7609).
   El módulo del bloque B3, que en el corpus de desarrollo subía de 0.63 a 0.93, **resta**
   fuera de él.
2. **"0 falsos ACCEPT" era una propiedad del corpus, no del motor.** Con material real y
   consenso recalibrado, acepta 2 de 3 centinelas.
3. **Aparecen 4 falsos RECHAZOS** (el ground truth dice ACCEPT y el motor rechaza). Esto es
   peor que abstenerse: **destruye información correcta**. Coherente con la precisión
   medida de la señal de negación, **4/9 = 0.4444**.

### 3.3. Comportamiento observado en material real

- **Abstención del 100 %**: 0 resultados `strong` de 64.
- **Sólo 8 tipos de predicado emitidos**, y **26 de 64 salidas (41 %) son el comodín
  `RELATED_TO`**.
- **9 de 14 familias del ground truth sacan cero.** Las simétricas (`ALLIED_WITH` 0/3) ni
  siquiera detectan el par.
- Veredicto del arnés, **sin tocar un solo umbral**: `APTO CON REVISIÓN HUMANA TOTAL` en
  los cuatro perfiles.

---

## 4. Causas: por qué no funciona

### 4.1. Causa raíz — el clasificador es **léxico**, no semántico

El selector de predicados decide por **expresiones observadas** (listas de verbos y giros
asociados a cada predicado). Funciona con las frases del corpus de desarrollo y se cae con
formulaciones distintas del mismo hecho. La evidencia es directa:

- Una **ablación** durante el desarrollo ya demostró que **~70 % de la ganancia inicial**
  (0.907) venía de expresiones **calcadas del corpus**. Se purgaron y bajó a 0.814.
- En held-out sintético las familias que se desploman son **exactamente** aquellas cuyas
  expresiones estaban en B1 y H1 formula de otro modo.
- En material real sólo sobreviven `MEMBER_OF` y `LOCATED_IN` — las de vocabulario más
  estereotipado ("pertenece a", "está en").

**No es un problema de calibración ni de umbrales: es de método.** Ampliar la lista de
expresiones mejora el corpus que se mire y no generaliza; es una carrera sin final.

### 4.2. Causa secundaria — sin detección de par no hay nada que clasificar

Las relaciones **simétricas** (`ALLIED_WITH`, `ENEMY_OF`, `MARRIED_TO`, `SIBLING_OF`) sacan
cero en parte porque el par **ni se genera**. Ninguna mejora posterior puede recuperar un
par que no existe. `pair_F1` no se movió en todo el programa v2 (0.8113 → 0.8113).

### 4.3. Causa terciaria — la temporalidad depende de marcadores explícitos

`temporal_v2` resuelve bien "desde hace tres años" y mal el tiempo implícito del relato.
En material real cae a **0.1957**. Además, el resolutor marca `ENDED` todo lo que va en
pasado, lo que hizo inviable el rechazo por temporalidad (se midió: habría fabricado 13
rechazos falsos).

### 4.4. Causa de la abstención total — vetos en cascada

`abstention.py` aplica varios vetos bloqueantes. Cada uno es defendible en aislamiento;
sumados sobre material real donde el predicado es dudoso casi siempre, **el motor no
propone nada**. Seguro e inútil.

### 4.5. Amplificador — el medidor no medía lo que parecía

- El medidor de predicado **sub-contaba 31 %** y **sobre-contaba 13 %** (crédito por alias).
  Se corrigió y **la línea base bajó** de 0.2558 a 0.2093.
- El gate `negation` mide **recall sobre 4 casos** y vale 1.0: **no puede ponerse rojo**
  mientras la precisión real es 0.4444. Se añadió `negation_precision` (FAIL, informativo).
- Los `result_hashes` **no cubren la decisión**: dos modos con hash idéntico dan
  `decision_correct` distinto.

---

## 5. Lo que SÍ funciona y hay que conservar

Esto es tan importante como lo anterior: **no todo el motor está mal, y sería un error
tirarlo entero.**

| Componente | Evidencia |
|---|---|
| **Localización de pares** | `pair_F1` 0.79–0.85 estable **en los tres corpus**; en held-out incluso **sube** |
| **Anclaje de evidencia y offsets** | offsets exactos **46/46** en material real; literalidad garantizada por construcción |
| **Tipos y workspaces** | 1.0000 en material real |
| **Determinismo** | `deterministic=True` en todas las corridas; `result_hashes` reproducibles |
| **Robustez** | 0 fallos con Unicode; **2 h de transcripción (85.718 caracteres) en 482 ms** |
| **Ontología con dominio/rango** | `ontology.py` es una base sólida y reutilizable |
| **Garantías de seguridad de la IA externa** | techo estructural verificado con barridos adversariales de 38.808 y 3.430 combinaciones, **cero violaciones**; evidencia siempre literal, offsets puestos por el sistema |
| **Arnés de evaluación** | un único banco, determinista, con corpus sellados y gates |

**Diagnóstico de una frase: es un localizador de pares y anclador de evidencia fiable, con
un clasificador de predicado que no funciona fuera de su corpus.**

---

## 6. Qué hay alrededor: costuras para sustituir el motor

Esta sección es la que permite **diseñar otro motor desde cero tocando lo mínimo**.

### 6.1. La frontera real del motor

```
payload (dict)
  └─ run_pipeline(payload, config, local_transport, external_provider) -> dict
        └─ results[].candidate  ==  RelationCandidate/internal-v1  (20 campos)
```

**Todo el sistema aguas abajo depende de UNA sola cosa: el contrato de 20 campos.**
Un motor nuevo que produzca candidatos válidos de ese contrato es intercambiable.

### 6.2. El contrato `relation-candidate/internal-v1` (NO cambiar)

```
subject_id, subject_type, predicate, object_id, object_type,
direction, confidence, evidence_text, evidence_start, evidence_end,
source_id, source_page, source_segment, extraction_method, model,
negated, temporal_scope, epistemic_status, workspace, validation_flags
```

Definido en `relations/contracts.py`. **Rechaza campos desconocidos.** Cualquier
información adicional debe ir en **contratos adyacentes**, nunca dentro de éste.

### 6.3. Entrada del pipeline

```python
payload = {
  "document" | "source_id": str,
  "workspace": str,
  "segments": [
     {"segment_id": str, "text": str,
      "entities": [{"id","text","type","start","end"}, ...]},
  ],
}
```

**Nota crítica para el rediseño:** el arnés **deriva las entidades del ground truth**. Es
decir, **el extractor de entidades real nunca se ha medido**. Un motor nuevo que además
extraiga entidades se enfrenta a un problema no evaluado hoy.

### 6.4. Consumidores aguas abajo

- `review/export_import.py` y `review/ingest_approved.py` — la ruta hacia el grafo.
- `relations/benchmark/` — el arnés (**único**, no crear otro).
- `relations/consensus_adapter.py`, `ensemble.py`, `review_policy.py` — decisión y
  clasificación para revisión humana.

### 6.5. Invariantes innegociables del sistema

1. **Dry-run estructural**: el pipeline funciona sin driver Neo4j, sin writer, sin `apply`.
   No existe flag que desactive el dry-run.
2. **La IA externa propone, nunca decide**: no escribe, no aprueba, no eleva consenso, no
   invalida, no cierra intervalos.
3. **Evidencia literal**: toda evidencia aceptada existe literalmente en el documento y
   **los offsets los pone el sistema, jamás el modelo**. Cita ambigua ⇒ rechazo.
4. **Fail-closed**: ausencia o fallo de un proveedor nunca equivale a rechazo.
5. **Determinismo**: mismo input ⇒ mismo `result_hash`.
6. **Aislamiento por workspace** en IDs, cachés, consultas y métricas.
7. **Sin secretos** en artefactos ni logs.

### 6.6. Estrategia de sustitución con mínimo impacto

**Un motor nuevo puede convivir con el actual tras el flag que ya existe**, del mismo modo
que v2 convive hoy con v1:

```python
PipelineConfig(predicate_selector="v1" | "v2" | "<nuevo>")
```

`v1` sigue siendo el valor por defecto y **la vía de rollback**. El patrón está probado:
todo el motor v2 se fusionó a `main` sin cambiar el comportamiento de nada.

**Superficie mínima a tocar para un motor nuevo:**

1. Un módulo nuevo en `relations/` que decida predicado (y opcionalmente dirección).
2. Una rama en `pipeline._build_candidate` tras un valor nuevo del flag.
3. Nada más. Ni contratos, ni arnés, ni consumidores, ni umbrales.

**Lo que conviene reutilizar tal cual:** generación de pares, anclaje de evidencia,
`ontology.py`, el arnés, los corpus B1/H1/H2 y las garantías de la capa externa.

---

## 7. Recomendaciones para el rediseño

1. **Atacar la clasificación semántica, no la léxica.** Es la causa raíz. Las opciones
   razonables —modelo local de embeddings sobre plantillas de predicado, clasificador
   entrenado con supervisión débil, o un LLM local en modo propuesta con validación
   determinista— comparten una condición: **medirse en H2 antes que en B1**.
2. **No entrenar nada con 54 relaciones.** Y no volver a usar el corpus de desarrollo como
   evidencia de generalización.
3. **Atacar `pair_F1` y las simétricas**: sin par no hay relación posible.
4. **Medir el extractor de entidades**, hoy no evaluado.
5. **Revisar los vetos en cascada**: hoy producen abstención del 100 % en material real.
6. **No promocionar el camino de rechazo** hasta que la precisión de negación supere el
   0.4444 actual: ya está generando 4 rechazos falsos sobre material real.
7. **Ampliar el material anotado.** El ground truth de H1 y H2 es de **un solo pase**; es
   la limitación metodológica más seria que queda.

---

## 8. Estado actual del código

- **`main`**: contiene el motor v2 **fusionado y NO activado**
  (`predicate_selector="v1"`, proveedores desactivados). Los despliegues **no han cambiado
  de comportamiento** en ningún momento.
- **`exp/relation-engine-v2-temporal-provenance-v1`**: auditoría, baseline, arreglo de CI y
  cierre de los 6 defectos abiertos. Los bloques de arquitectura (episodios, ledger,
  supersession, procedencia) **no se han empezado**.
- **`work/rel-v2e-b02-heldout`**: corpus H1 y H2, política de held-out y comparación de
  transcripción.
- **Producción**: intacta. Sin ingesta, sin despliegue, sin escritura en Neo4j.

### 8.1. Nota sobre el material real

El corpus H2 se construyó desde 3 libros (881 páginas, Trudvang y Vampiro V20) y una sesión
grabada de 2 h. **Ese material no está en el repositorio y no debe estarlo**: son obras con
derechos de autor y grabaciones con datos personales. Al repositorio sólo entraron métricas,
hashes y citas de evidencia de ≤400 caracteres (**0,3 %** del texto), con tests que lo hacen
cumplir mecánicamente.

### 8.2. Transcripción

El modelo `faster-whisper small` **no es apto para ingesta**: le faltan los últimos 78 s de
la sesión (justo el cierre, lo más valioso para un grafo episódico), entra en **bucle de
repetición literal** —que fabrica evidencia falsa con aspecto de confirmación— y produce el
mismo nombre de varias formas (`daiki`/`daiqui`), lo que crearía **dos nodos para la misma
persona**. Los subtítulos de YouTube son **segunda opinión automática, no ground truth**.

---

## 9. Lección metodológica

Apareció **tres veces** el mismo patrón y merece quedar escrito: **tests y gates verdes que
no ejercitan la ruta real.**

- Los tests de pereza del parser afirmaban que spaCy no estaba importado **en un entorno
  donde no podía estarlo**.
- El defecto P0 —el evaluador externo recibía el *identificador* del segmento en vez del
  texto, lo que habría producido **100 % de rechazos**— era invisible para la suite porque
  los tests metían el texto en el campo que en producción lleva el ID.
- El gate `negation` mide recall sobre 4 casos y **no puede ponerse rojo** mientras la
  precisión real es 0.4444.

A eso se suman dos incidentes de suite verde falsa por bytecode obsoleto.

**Un test verde sólo vale si puede ponerse rojo.** Las pruebas de mutación fueron lo único
que destapó estos huecos: 4 en el bloque del parser, 2 en el de consenso y 1 en el de la
capa externa, todos invisibles a una suite completa en verde.

Y la lección mayor: **medir en el corpus con el que se desarrolla no es medir**. Costó dos
programas completos y un corpus reservado descubrir que la cifra de referencia estaba
inflada en más de tres veces.
