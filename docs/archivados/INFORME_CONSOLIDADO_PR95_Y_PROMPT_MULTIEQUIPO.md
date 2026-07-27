# Informe consolidado y plan multiversión  
## PR #95 · Motor de relaciones de S9 Knowledge

**Proyecto:** S9 Knowledge  
**Repositorio:** `pjclavero/S9-Knowledge`  
**Objeto:** comparación de tres auditorías, resolución de discrepancias, catálogo consolidado de problemas y soluciones, diseño de versiones experimentales y prompt de ejecución multiequipo.  
**Fecha:** 21 de julio de 2026  
**Naturaleza:** análisis y planificación. No autoriza despliegue, ingesta real, escritura en Neo4j ni fusión a `main`.

---

# 1. Dictamen ejecutivo

Las tres auditorías no deben tratarse como equivalentes:

1. La auditoría del **12 de julio de 2026**, sobre `main@1fd94b8 / v0.2.5b`, es una fotografía histórica anterior al programa actual del motor de relaciones. Conserva valor como diagnóstico general de preproducción, pero varias afirmaciones sobre tests, CI y estado del repositorio han quedado obsoletas.
2. Las otras dos auditorías del **21 de julio de 2026** sí estudian el PR #95 y el motor de relaciones actual. Coinciden en que el problema de evidencia es real, que el benchmark no permite todavía conclusiones definitivas sobre modelos y que deben conservarse las garantías de sombra, `fail-closed`, ausencia de escritura y umbrales.
3. No coinciden en cuál es la causa que debe corregirse primero:
   - una sitúa la causa principal en el **span mecánico entre menciones**;
   - la otra detecta antes un defecto de cableado: el proveedor externo puede recibir el **identificador del segmento** en lugar del texto.

La comprobación directa del código público actual resuelve esta discrepancia:

```text
pairs.py
    source_segment = seg["id"]

pipeline.py
    _run_external(cand, config, ctx)
    evaluate_relation_external(cand, ...)

external_ai_shadow.py
    DOCUMENTO = sanitize_document(cand.source_segment)
    seg = cand.source_segment
    validar evidence_text y offsets contra seg
```

Por tanto:

> **P0 — defecto de contrato y flujo de datos:** la ruta externa confunde `segment_id` con `document_text`.

Y después:

> **P1 — defecto de anclaje:** la evidencia heurística usa la envolvente literal entre las dos menciones y puede ser demasiado extensa o semánticamente insuficiente.

Ambos problemas son reales, pero el orden importa. Mientras P0 no esté corregido, cualquier comparación de Ollama, NVIDIA, prompts, offsets o realineamiento en la ruta externa puede estar contaminada y conducir a conclusiones falsas.

## Decisión recomendada

1. Congelar un commit de referencia de `main`.
2. Crear una **rama base nueva**, sin tocar `main` ni ramas existentes.
3. Reproducir P0 con un proveedor falso.
4. Corregir únicamente el contrato ID/texto.
5. Añadir métricas y archivar un baseline reproducible.
6. Desde ese mismo commit base, crear ramas independientes para cuatro versiones del motor:
   - V1: anclaje conservador a frase/cláusula;
   - V2: realineamiento determinista literal;
   - V3: selección por fragmentos numerados;
   - V4: pipeline híbrido por etapas.
7. Ejecutar exactamente el mismo corpus, configuración y batería de tests en todas las versiones.
8. No fusionar ninguna versión. Entregar artefactos comparables para una evaluación posterior.

---

# 2. Fuentes comparadas

## 2.1 Auditoría A — profunda y causal

Documento comparado: `Pegado text(7).txt`.

Fortalezas:

- traza completa `segmento → par → candidato → proveedor → consenso`;
- identifica la confusión `source_segment` ID/texto;
- separa defectos de contrato, evidencia, pares, predicado, temporalidad y benchmark;
- propone un orden de corrección técnicamente seguro;
- no atribuye toda la calidad del motor a una única métrica.

Limitaciones:

- no pudo clonar ni ejecutar tests;
- parte del estado de ramas se dedujo desde GitHub público;
- los resultados de proveedores se tratan como resultados publicados, no reproducidos.

## 2.2 Auditoría B — histórica de arquitectura general

Documento comparado: `Texto pegado (2)(1).txt`.

Fortalezas:

- fotografía útil del proyecto en `v0.2.5b`;
- detecta riesgos generales de preproducción;
- destaca la necesidad de automatización, test E2E, seguridad de dependencias, empaquetado y despliegue reproducible;
- confirma que el extractor heurístico era un bloqueo funcional relevante.

Limitaciones materiales:

- fecha y commit anteriores al programa de calibración de relaciones;
- afirma ausencia de tests y CI que no debe extrapolarse al estado del 21 de julio;
- no analiza el PR #95 ni el flujo concreto de evidencia externa;
- no sirve como fuente principal para decidir las ramas experimentales actuales.

Uso correcto: contexto histórico y deuda transversal.  
Uso incorrecto: tomar sus recuentos o conclusiones de estado como vigentes.

## 2.3 Auditoría C — profunda con ejecución offline

Documento comparado: `Se ha pegado el markdown (3).md`.

Fortalezas:

- reconstrucción Git y clasificación por contenido;
- verificación de afirmaciones del PR;
- ejecución declarada de tests offline;
- identifica carencias del benchmark y artefactos de proveedores no versionados;
- propone frase mínima, realineamiento, métricas y pipeline por etapas;
- conserva las garantías de seguridad.

Limitaciones:

- considera el span heurístico como causa primaria y no detecta la confusión crítica ID/texto;
- concluye que el IoU del anclaje a frase “no puede empeorar”, afirmación que solo es cierta respecto a una envolvente más amplia si la frase contiene completamente el GT y no se pierde contexto probatorio; debe demostrarse con tests metamórficos y casos de negación, atribución y temporalidad;
- interpreta algunos resultados documentados de proveedores sin disponer de los artefactos completos de las corridas reales.

---

# 3. Conclusiones comunes

Las dos auditorías actuales coinciden en los siguientes puntos, que deben considerarse base de trabajo:

## 3.1 El PR #95 documenta un problema real

La evidencia no es un detalle cosmético. Es la base de:

- trazabilidad;
- revisión humana eficiente;
- validación de la relación;
- consenso;
- políticas de auto-propuesta;
- depuración de falsos positivos;
- explicabilidad ante cambios futuros.

## 3.2 El span mecánico es insuficiente como estrategia final

La evidencia heurística actual se construye desde el inicio más temprano hasta el final más tardío de las menciones. Esto garantiza literalidad, pero no:

- mínima suficiencia;
- delimitación de la cláusula probatoria;
- inclusión correcta de negación;
- inclusión de atribución o rumor;
- selección de la mejor mención cuando existen varias;
- soporte de evidencia discontinua.

## 3.3 La validación externa es estricta y debe seguir siéndolo

La exigencia de que:

```python
document_text[start:end] == evidence_text
```

es una garantía de integridad valiosa. La solución no debe consistir en aceptar libremente paráfrasis o evidencia inexistente.

Lo correcto es mejorar el protocolo de selección y alineamiento, no relajar la barrera final.

## 3.4 La igualdad de P/R/F1 no demuestra que el modelo no aporte valor

Las métricas de existencia de pares pueden permanecer idénticas aunque cambie:

- el predicado;
- la dirección;
- la evidencia;
- la confianza;
- la recomendación del proveedor.

Además, si el ensemble en sombra no añade ni elimina pares, esas métricas son poco sensibles al valor del proveedor.

## 3.5 El benchmark no es suficiente para decisiones definitivas

Problemas comunes detectados:

- corpus pequeño;
- corpus en parte sintético;
- una única evidencia válida por relación;
- ausencia de intervalos de confianza;
- ausencia de ECE/Brier para confianza;
- artefactos completos de proveedores no versionados;
- `offsets_correct` basado en cualquier solapamiento;
- matching que puede mezclar objetivos;
- poca capacidad para medir falso aceptado por clase.

## 3.6 Hay más problemas que la evidencia

Las auditorías actuales reconocen, con diferente prioridad:

- `predicate_structural` insuficiente;
- dirección imperfecta;
- temporalidad débil;
- decisión final baja;
- generación de pares limitada por contexto;
- deduplicación por distancia y no por calidad probatoria;
- confianza heurística no calibrada;
- `RELATED_TO` como fallback;
- falta de evidencia múltiple;
- diferencias de normalización.

## 3.7 Deben conservarse las garantías existentes

Todas las versiones deben mantener:

1. modo sombra;
2. `dry-run`;
3. ausencia de escritura en Neo4j;
4. `fail-closed`;
5. ninguna red por defecto;
6. doble autorización para proveedores reales;
7. determinismo offline;
8. umbrales sin rebajar;
9. artefactos redactados, sin secretos;
10. rollback por rama y commit.

---

# 4. Conclusiones que no coinciden y resolución

## 4.1 Causa inmediata: contrato ID/texto frente a anclaje

### Auditoría A

Afirma que `source_segment` contiene `seg["id"]` y que la ruta externa usa ese valor como documento y para validar offsets.

### Auditoría C

Afirma que la causa primaria es la envolvente de menciones:

```python
evidence_text = seg_text[lo:hi]
```

### Resolución

Ambas describen problemas reales, pero en capas diferentes:

| Prioridad | Problema | Ruta afectada | Consecuencia |
|---|---|---|---|
| **P0** | ID usado como documento | proveedor externo | la tarea puede ser imposible antes de evaluar el modelo |
| **P1** | span demasiado amplio | heurística y baseline | evidencia literal pero poco precisa |
| **P2** | normalización/realineamiento | proveedor | falsos rechazos aun con texto correcto |
| **P3** | representación de un solo span | contrato/GT/UI | incapacidad para relaciones complejas |

La secuencia correcta es P0 → baseline → P1/P2 → P3.

## 4.2 ¿La puerta de evidencia falla o pasa?

Una auditoría cita resultados vigentes de aproximadamente:

- evidence: 90,70 %;
- offsets por solapamiento: 93,02 %.

La otra reproduce resultados documentales de otra ejecución o modo donde la evidencia se presenta como el bloqueo.

### Resolución

No mezclar:

- corpus;
- commit;
- modo offline/local/NVIDIA;
- versión de prompt;
- versión de matching;
- definición de la métrica;
- submuestra.

Todo resultado debe contener un `run_manifest` con:

```yaml
git_sha:
branch:
corpus_version:
ground_truth_hash:
config_hash:
provider:
model:
prompt_version:
normalization_version:
matching_version:
seed:
started_at:
```

Hasta repetir un baseline después de P0, no debe afirmarse de forma global que la puerta de evidencia pasa o falla.

## 4.3 ¿Instrumentar primero o corregir primero?

- Auditoría C prioriza métricas antes de tocar el anclaje.
- Auditoría A prioriza el defecto ID/texto antes de cualquier benchmark externo.

### Resolución

Ambas acciones son necesarias, en este orden:

1. test que reproduzca P0;
2. corrección mínima P0;
3. instrumentación común;
4. baseline reproducible;
5. variantes del motor.

No tiene sentido instrumentar una ejecución externa cuyo documento de entrada sea incorrecto; tampoco tiene sentido comparar algoritmos sin métricas adecuadas.

## 4.4 Estado de ramas

Una auditoría interpreta varias ramas como activas y con diferencias materiales; otra las considera integradas o superseded por comparación de blobs.

### Resolución

El estado de ramas es temporalmente inestable y debe reconstruirse al inicio del trabajo. Regla:

> Clasificar por contenido, merge-base y commits, nunca solo por nombre, fecha o descripción documental.

No modificar, rebasar, borrar ni reutilizar ninguna rama existente.

## 4.5 Validez de la auditoría histórica

La auditoría del 12 de julio señala falta de tests y CI.

### Resolución

Se conserva como deuda histórica, pero no como estado vigente. Antes de incluir cualquiera de sus hallazgos en el plan actual debe volver a verificarse contra el commit de referencia.

---

# 5. Registro consolidado de problemas y soluciones

## P0. Confusión entre procedencia y contenido

**Severidad:** crítica  
**Confianza:** alta  
**Ámbito:** `pairs.py`, `pipeline.py`, `external_ai_shadow.py`, contratos y tests.

### Problema

`source_segment` representa un ID, pero la ruta externa lo interpreta como texto.

### Impacto

- proveedor sin documento real;
- evidencia imposible o trivial;
- offsets calculados contra una cadena incorrecta;
- resultados NVIDIA/Ollama potencialmente contaminados;
- falsas conclusiones sobre modelos y prompts;
- 0 % de propuestas válidas por causas artificiales.

### Solución mínima

Crear una entrada explícita:

```python
@dataclass(frozen=True)
class RelationExternalEvalInput:
    candidate: RelationCandidate
    document_text: str
    source_segment_id: str
    text_hash: str
    normalization_version: str
```

Cambiar la llamada:

```python
_run_external(cand, seg_text, config, ctx)
```

El prompt y el validador deben usar `document_text`.  
La trazabilidad debe usar `source_segment_id`.

### Tests obligatorios

- el proveedor falso recibe el texto exacto;
- el proveedor falso no recibe `seg["id"]`;
- evidencia literal válida se acepta;
- evidencia del ID se rechaza;
- offsets se validan contra texto real;
- no cambia el contrato persistente sin migración explícita;
- no hay red;
- no hay escritura.

---

## P1. Evidencia heurística sobre-extendida

**Severidad:** alta  
**Confianza:** alta

### Problema

La envolvente entre menciones puede contener texto irrelevante o perder la estructura probatoria.

### Solución

Anclaje conservador:

1. frase que contiene ambas menciones;
2. detección de cláusula;
3. expansión para incluir:
   - negación;
   - verbo/predicado;
   - atribución;
   - marcador temporal;
   - marcador epistémico;
4. fallback al span actual cuando la reducción no sea segura.

### Tests

- frases cortas y largas;
- negación antes de sujeto;
- temporalidad después del objeto;
- rumor atribuido en oración previa;
- dos cláusulas coordinadas;
- menciones repetidas;
- span mínimo semánticamente insuficiente;
- propiedad: la salida siempre es literal del texto original.

---

## P2. Realineamiento de citas del proveedor

**Severidad:** alta  
**Confianza:** media-alta

### Problema

El modelo puede:

- copiar con espacios distintos;
- normalizar comillas;
- cambiar Unicode;
- devolver una cita literal pero con offsets erróneos;
- parafrasear parcialmente.

### Solución

Pipeline determinista:

1. exact match;
2. match sobre texto normalizado con mapa reversible;
3. token/char alignment;
4. fuzzy limitado solo dentro de una ventana;
5. rechazo cuando hay empate o ambigüedad;
6. retorno final siempre como subcadena del original.

### Condición de seguridad

Nunca aceptar una paráfrasis como evidencia persistida. La paráfrasis puede servir como consulta de localización, no como resultado final.

### Tests

- NFC/NFD;
- CRLF/LF;
- comillas tipográficas;
- espacios Unicode;
- cita repetida dos veces;
- una coincidencia correcta y otra semánticamente parecida;
- prompt injection;
- texto truncado;
- 0 alineamientos ambiguos aceptados.

---

## P3. Métricas de evidencia insuficientes

**Severidad:** alta  
**Confianza:** alta

### Problema

`offsets_correct = inter > 0` mide solapamiento, no exactitud.

### Solución

Publicar:

- `offset_exact_match`;
- `start_absolute_error`;
- `end_absolute_error`;
- `boundary_mae`;
- `char_iou`;
- `char_f1`;
- `token_f1`;
- `contains_ground_truth`;
- `contained_by_ground_truth`;
- `realignment_success_rate`;
- `ambiguous_realignment_rate`;
- distribución por longitud de cita.

Renombrar la métrica actual a `offsets_overlap`.

### Tests

- un span enorme que toca un carácter no puede contar como exacto;
- límites desplazados;
- span contenido;
- span envolvente;
- evidencia idéntica;
- casos sin intersección.

---

## P4. Matching no completamente desacoplado

**Severidad:** alta  
**Confianza:** media-alta

### Problema

La selección de predicciones puede influir en la evidencia medida y la existencia no refleja calidad semántica.

### Solución

Dos evaluaciones:

1. **Identidad estructural**
   - source/workspace;
   - sujeto;
   - objeto;
   - predicado canónico;
   - dirección.
2. **Evidencia condicionada**
   - solo después de fijar la correspondencia estructural;
   - matching bipartito cuando hay múltiples candidatos;
   - mejor evidencia válida entre varias anotaciones;
   - casos ambiguos reportados.

---

## P5. Ground truth con una sola evidencia

**Severidad:** media-alta  
**Confianza:** alta

### Problema

Puede penalizar citas válidas alternativas o evidencia discontinua.

### Solución de medición

```json
{
  "valid_evidence_sets": [
    [{"start": 10, "end": 35}],
    [
      {"start": 10, "end": 20},
      {"start": 80, "end": 100}
    ]
  ]
}
```

No migrar aún el contrato de producción. Primero ampliar el GT y el matching.

---

## P6. Generación de pares y deduplicación

**Severidad:** alta  
**Confianza:** alta

### Problemas

- contexto por frase pierde relaciones inter-frase;
- deduplicación conserva la mención más cercana, no la mejor evidencia;
- mejorar evidencia no recupera pares nunca generados.

### Soluciones

- ventana de dos frases;
- contexto paragraph con reranking;
- top-k menciones por pareja;
- puntuación de mención basada en señales probatorias;
- correferencia selectiva;
- límite duro de candidatos para evitar explosión combinatoria.

### Métricas

- recall de pares;
- precisión estructural;
- coste por documento;
- candidatos por segmento;
- pérdida por dedupe;
- relación entre distancia y calidad real.

---

## P7. Predicado, dirección y fallback genérico

**Severidad:** alta  
**Confianza:** alta

### Problemas

- `predicate_structural` por debajo de la puerta publicada;
- `RELATED_TO` puede ocultar incapacidad de clasificación;
- dirección exacta insuficiente.

### Soluciones

- reportar tasa `RELATED_TO`;
- métricas por predicado;
- alias y vocabulario canónico;
- parser sintáctico opcional;
- abstención explícita mejor que predicado genérico de alta confianza;
- matriz de confusión;
- casos adversariales por tipo de relación.

---

## P8. Temporalidad y epistemología

**Severidad:** media-alta  
**Confianza:** alta

### Problemas

- marcadores pueden quedar fuera del span reducido;
- señales pueden estar en otra frase;
- clases minoritarias con pocas muestras.

### Soluciones

- mantener una ventana de contexto independiente de la evidencia citada;
- separar `evidence_span` de `reasoning_context`;
- tests por rumor, hipótesis, intención, pasado, presente y futuro;
- métricas y umbrales por clase;
- no activar auto-propuesta en categorías sin suficiente soporte estadístico.

---

## P9. Confianza heurística no calibrada

**Severidad:** media  
**Confianza:** alta

### Problema

Una suma de bonificaciones no es una probabilidad.

### Solución

Después de estabilizar datos y métricas:

- calibración isotónica, Platt o logística;
- ECE;
- Brier score;
- curvas de fiabilidad;
- split independiente;
- calibración por categoría;
- intervalos bootstrap.

No calibrar sobre 54 relaciones como base de automatización real.

---

## P10. Artefactos y reproducibilidad

**Severidad:** alta  
**Confianza:** alta

### Problema

Los resultados de proveedores no están plenamente versionados.

### Solución

Cada ejecución conserva:

- manifest;
- configuración;
- hashes;
- JSONL de candidatos;
- respuestas redactadas;
- errores de validación;
- métricas;
- tiempos;
- versiones;
- commit;
- entorno;
- lista de tests;
- diff de resultados.

Nunca conservar secretos, headers o contenido sensible no autorizado.

---

## P11. Estado estructurado del proyecto

**Severidad:** media  
**Confianza:** alta

### Problema

`project-status.yaml` representa producción del 18 de julio, no todo el desarrollo del motor.

### Solución

Separar:

```yaml
production_status:
main_development_status:
relation_engine_status:
active_experiments:
superseded_branches:
last_reconciled_git_sha:
```

No sobrescribir la fotografía de producción con datos experimentales.

---

## P12. Seguridad documental y de proveedor

**Severidad:** media-alta  
**Confianza:** media-alta

### Riesgos

- prompt injection desde documentos;
- Unicode Bidi oculto;
- exposición de texto sensible a proveedor externo;
- red accidental;
- logs con contenido;
- dependencia externa no autorizada.

### Soluciones

- delimitadores fuertes de contenido;
- instrucción explícita de datos no confiables;
- allowlist de proveedor/modelo;
- capability de red;
- redacción de logs;
- hashes en vez de texto cuando sea posible;
- test Unicode Bidi;
- revisión de privacidad antes de corridas reales;
- suite offline como requisito por defecto.

---

# 6. Versiones experimentales para mejorar el motor

Todas las versiones parten del mismo commit de una rama base nueva que contiene únicamente:

- corrección P0;
- instrumentación común;
- baseline reproducible;
- fixtures comunes;
- garantías de seguridad reforzadas.

No deben copiar código de otras versiones una vez iniciada la comparación.

## Base común — `exp/pr95-compare-base-contract-v1`

### Objetivo

Crear una referencia justa y técnicamente válida.

### Incluye

- `document_text` separado de `source_segment_id`;
- validación contra texto original;
- hash y versión de normalización;
- métricas nuevas;
- manifest de ejecución;
- tests P0;
- baseline offline;
- artefactos estandarizados.

### No incluye

- frase mínima;
- fuzzy matching;
- parser nuevo;
- fragment IDs;
- multi-span de producción;
- cambio de thresholds;
- auto-propuesta;
- escritura.

---

## Versión 1 — Conservadora y explicable

**Rama:** `exp/pr95-v1-conservative-anchor`  
**Equipo:** V1

### Hipótesis

Una evidencia basada en frase o cláusula segura mejora precisión sin aumentar complejidad ni dependencias.

### Diseño

- sentence bounds;
- reducción a cláusula solo con reglas seguras;
- preservación de negación, atribución y temporalidad;
- fallback a baseline;
- flag de configuración;
- salida literal.

### Ventajas

- bajo riesgo;
- offline;
- fácil rollback;
- alta explicabilidad;
- poco cambio de arquitectura.

### Riesgos

- frase completa todavía amplia;
- cláusula demasiado estrecha;
- no resuelve citas LLM;
- no mejora pares ausentes.

### Criterio de éxito

- mejora de exact match/char-F1/boundary MAE;
- ninguna regresión material en predicado, negación, temporalidad y epistemología;
- 0 errores de literalidad;
- invariantes verdes.

---

## Versión 2 — Realineamiento determinista robusto

**Rama:** `exp/pr95-v2-deterministic-realignment`  
**Equipo:** V2

### Hipótesis

Los proveedores razonan mejor de lo que copian offsets; un realineamiento conservador recupera respuestas válidas sin aceptar evidencia inventada.

### Diseño

- exact match;
- normalización reversible;
- alineamiento token/char;
- fuzzy limitado a ventana;
- rechazo de ambigüedad;
- score de alineamiento;
- salida literal original.

### Ventajas

- ataca directamente rechazos de proveedor;
- compatible con modelos distintos;
- conserva validación estricta final.

### Riesgos

- falso alineamiento;
- complejidad Unicode;
- mayor superficie de tests;
- coste de mantenimiento.

### Criterio de éxito

- reducción de `invalid_response` por evidencia;
- 0 evidencia no literal;
- 0 coincidencias ambiguas aceptadas;
- tasa de falso realineamiento dentro del límite predeclarado;
- sin cambio de pares estructurales.

---

## Versión 3 — Selección por fragmentos numerados

**Rama:** `exp/pr95-v3-fragment-selection`  
**Equipo:** V3

### Hipótesis

Los modelos seleccionan mejor IDs discretos que offsets crudos.

### Diseño

- segmentar en frases/cláusulas estables;
- numerar fragmentos;
- el proveedor devuelve `fragment_id` o conjunto de IDs;
- el sistema reconstruye offsets;
- validación literal automática;
- protocolo versionado.

### Ventajas

- elimina el conteo de caracteres por LLM;
- alta explicabilidad;
- menor sensibilidad a Unicode;
- compatible con multi-span experimental.

### Riesgos

- prompt más largo;
- fragmentación incorrecta;
- pérdida de contexto entre fragmentos;
- dependencia del segmentador.

### Criterio de éxito

- menos campos ausentes;
- menos offsets inválidos;
- latencia y tokens dentro del presupuesto;
- mejor evidencia que V1 y baseline;
- estabilidad frente a NFC/NFD y saltos de línea.

---

## Versión 4 — Pipeline híbrido por etapas

**Rama:** `exp/pr95-v4-hybrid-staged-engine`  
**Equipo:** V4

### Hipótesis

Separar hipótesis estructural, selección de evidencia y verificación permite mejorar más dimensiones sin acoplarlas.

### Diseño

```text
generación de pares
→ ranking de menciones
→ hipótesis de relación
→ predicado/dirección
→ extracción de evidencia
→ verificación literal
→ temporal/epistémica
→ calibración
→ consenso
→ revisión
```

### Incluye

- contratos internos separados;
- top-k menciones;
- contexto de razonamiento separado de la cita;
- anclaje conservador;
- realineamiento literal;
- parser opcional detrás de flag;
- métricas por etapa.

### Ventajas

- dirección estratégica correcta;
- permite ablation;
- facilita multi-span futuro;
- mejora mantenibilidad conceptual.

### Riesgos

- mayor diff;
- más puntos de fallo;
- comparación menos pura;
- posible sobreingeniería;
- mayor necesidad de supervisión.

### Criterio de éxito

- mejora conjunta en evidencia y `predicate_structural`;
- ninguna regresión en recall de pares;
- cada etapa se puede desactivar;
- resultados reproducibles por ablation;
- no se rompe el contrato público sin migración.

---

# 7. Diseño de comparación común

## 7.1 Regla de justicia experimental

Todas las ramas deben compartir:

- mismo commit base;
- mismo corpus;
- mismo ground truth;
- mismos seeds;
- mismos proveedores/modelos;
- misma temperatura;
- mismos límites;
- mismo prompt, salvo cuando la versión requiera cambiar el protocolo;
- misma máquina o entorno;
- mismo conjunto de tests;
- mismo formato de artefactos;
- misma política de red;
- mismos thresholds.

## 7.2 Métricas primarias

### Estructura

- precision/recall/F1 de pares;
- predicado exacto;
- predicado canónico;
- dirección exacta;
- tasa `RELATED_TO`;
- recall inter-frase;
- pérdida por dedupe.

### Evidencia

- exact match;
- char-F1;
- token-F1;
- IoU;
- start/end error;
- boundary MAE;
- literalidad;
- evidencia suficiente;
- realineamiento válido;
- ambigüedad.

### Semántica

- negación;
- temporalidad;
- epistemología;
- rumor/hipótesis/intención;
- decisión final.

### Operación

- latencia p50/p95;
- tokens;
- memoria;
- candidatos por documento;
- errores;
- timeouts;
- coste por fuente;
- determinismo.

### Seguridad

- intentos de red;
- escrituras;
- datos sensibles en logs;
- prompt injection;
- bypass de capability;
- comportamiento fail-closed.

## 7.3 Corpus

Usar tres estratos:

1. **Corpus vigente** para continuidad.
2. **Corpus independiente** no usado al diseñar la versión.
3. **Corpus adversarial**:
   - Unicode;
   - varias menciones;
   - negación distante;
   - relación inter-frase;
   - cita repetida;
   - rumor;
   - temporalidad;
   - prompt injection;
   - texto largo;
   - ausencia de relación.

## 7.4 Artefactos por rama

Cada equipo debe producir:

```text
artifacts/pr95-variants/<version>/
├── run-manifest.yaml
├── config-effective.yaml
├── tests-summary.md
├── pytest.xml
├── coverage.xml
├── benchmark.json
├── benchmark-summary.md
├── predictions.jsonl
├── validation-errors.jsonl
├── security-report.md
├── performance-report.md
├── ablation-report.md
├── known-limitations.md
└── decision-log.md
```

No guardar secretos ni respuestas sin redacción.

---

# 8. Puertas de calidad y seguridad

Una versión no se considera entregada si falla cualquiera de estas puertas:

## QG-01 — Integridad Git

- `main` sin cambios;
- ramas antiguas sin cambios;
- worktree limpio;
- solo rama nueva asignada;
- diff limitado al alcance.

## QG-02 — Contrato

- ID y texto separados;
- offsets sobre texto versionado;
- evidencia literal;
- serialización determinista;
- compatibilidad validada.

## QG-03 — Tests

- suite común verde;
- tests de regresión;
- tests property-based;
- tests metamórficos;
- tests adversariales;
- cobertura de módulos modificados;
- mutation tests en invariantes críticas.

## QG-04 — Seguridad

- sin escritura en Neo4j;
- sin ingesta;
- sin despliegue;
- sin red no autorizada;
- `fail-closed`;
- secretos ausentes;
- logs redactados;
- prompt injection probado.

## QG-05 — Benchmark

- manifest completo;
- baseline y variante;
- métricas sin cambiar definiciones;
- thresholds sin rebajar;
- resultados negativos publicados;
- artefactos reproducibles.

## QG-06 — Revisión independiente

- revisor distinto del editor;
- seguridad distinta de QA;
- supervisor final;
- ninguna autocertificación del equipo.

---

# 9. Estrategia Git

## 9.1 Prohibiciones

- no hacer commit en `main`;
- no hacer merge a `main`;
- no rebasear ramas existentes;
- no borrar ramas;
- no reutilizar ramas de calibración;
- no forzar push;
- no modificar tags;
- no desplegar;
- no actualizar VM105;
- no escribir Neo4j;
- no alterar bases de datos;
- no fusionar versiones entre sí.

## 9.2 Secuencia segura

```bash
git fetch --all --prune
git status --short
git rev-parse origin/main
git worktree add ../s9-pr95-base -b exp/pr95-compare-base-contract-v1 <MAIN_SHA>
```

Tras aprobar la base:

```bash
BASE_SHA=<commit aprobado de la base>

git worktree add ../s9-pr95-v1 -b exp/pr95-v1-conservative-anchor "$BASE_SHA"
git worktree add ../s9-pr95-v2 -b exp/pr95-v2-deterministic-realignment "$BASE_SHA"
git worktree add ../s9-pr95-v3 -b exp/pr95-v3-fragment-selection "$BASE_SHA"
git worktree add ../s9-pr95-v4 -b exp/pr95-v4-hybrid-staged-engine "$BASE_SHA"
```

Cada equipo trabaja en un worktree propio.

## 9.3 PR

- PRs en **draft**;
- base temporal: la rama base experimental, no `main`;
- etiquetas: `experiment`, `do-not-merge`, `pr95-comparison`;
- descripción con hipótesis, tests y artefactos;
- el supervisor no autoriza merge.

---

# 10. Prompt de ejecución multiequipo

Copia íntegramente el siguiente prompt en el entorno de desarrollo.

---

## PROMPT

Actúa como director técnico y supervisor principal de una experimentación controlada sobre el motor de relaciones del repositorio:

```text
https://github.com/pjclavero/S9-Knowledge
```

El problema procede del PR #95 y de tres auditorías técnicas ya consolidadas.

Tu misión es implementar y probar **cuatro versiones independientes** de mejora del motor para que después puedan compararse de forma justa.

No debes elegir ni fusionar una ganadora. Debes producir ramas, código, tests y artefactos comparables.

### 1. Restricciones absolutas

1. No modifiques `main`.
2. No hagas commits, merges, rebases, cherry-picks, force-push ni borrados sobre ramas existentes.
3. No reutilices ramas anteriores.
4. Crea únicamente las ramas nuevas definidas en este prompt.
5. No despliegues.
6. No modifiques VM105.
7. No escribas en Neo4j.
8. No ejecutes ingestas reales.
9. No alteres `auth.db`, `jobs.db` ni otros datos persistentes.
10. No bajes thresholds.
11. No actives autoaprobación ni autoescritura.
12. La red debe estar desactivada por defecto.
13. Proveedores reales solo pueden ejecutarse con doble autorización explícita y secretos ya configurados; nunca imprimas secretos.
14. Todo debe conservar `dry-run`, modo sombra, `fail-closed` y determinismo offline.
15. Todos los PR deben quedar en draft y marcados `do-not-merge`.

Si cualquier restricción entra en conflicto con una tarea, detén esa tarea y eleva el bloqueo al supervisor.

### 2. Hecho técnico que debes verificar antes de programar

Reconstruye el flujo y confirma con código y un test fallido inicial:

```text
pairs.py:
    source_segment = seg["id"]

pipeline.py:
    _run_external recibe el candidato pero no seg_text

external_ai_shadow.py:
    cand.source_segment se presenta como DOCUMENTO
    cand.source_segment se usa para validar evidence_text y offsets
```

No des este hecho por supuesto: crea un proveedor falso y demuestra qué texto recibe.

Clasifica el resultado:

- `CONFIRMADO`;
- `YA CORREGIDO EN MAIN`;
- `CAMBIÓ EL FLUJO`;
- `NO REPRODUCIBLE`.

Si ya fue corregido en `main`, no reintroduzcas el cambio; conserva el test de regresión y adapta la base.

### 3. Organización de agentes

Crea un **Supervisor General Opus** que no edite código salvo emergencia y coordine:

- estado Git;
- alcance;
- conflictos;
- criterios de aceptación;
- seguridad;
- calidad;
- aprobación de cada fase.

Crea un **Organizador Opus** que:

- construya el DAG de tareas;
- asigne worktrees;
- evite solapamientos;
- mantenga el registro de ramas, commits y propietarios;
- bloquee tareas dependientes hasta aprobar la base.

Para cada versión crea un equipo multidisciplinar independiente:

1. **Arquitecto de versión — Opus**
2. **Editor principal de código — Opus**
3. **Ingeniero de tests — Sonnet**
4. **Especialista NLP/LLM — Sonnet u Opus según complejidad**
5. **Ingeniero de benchmark y estadística — Sonnet**
6. **Revisor de seguridad — Opus**
7. **QA independiente — Sonnet**
8. **Revisor final de versión — Opus**

Los agentes de equipos distintos no deben editar el mismo worktree.

#### Agente FABLE de respaldo

Si el editor Opus no consigue que la implementación y sus tests pasen en el **primer ciclo completo**, activa un agente independiente llamado:

```text
FABLE — Fallback Analysis, Build, Logic & Evidence
```

FABLE debe ser un agente Opus nuevo, sin asumir que el enfoque anterior es correcto.

Procedimiento:

1. congelar el diff y guardar logs del primer intento;
2. FABLE revisa requisitos, código, tests y fallo desde cero;
3. propone diagnóstico escrito;
4. el supervisor decide entre:
   - reparar el enfoque;
   - revertir parcialmente;
   - simplificar;
   - declarar la hipótesis no viable;
5. FABLE puede editar solo la rama de ese equipo;
6. nunca ocultar el primer fallo;
7. el informe final debe distinguir:
   - intento inicial;
   - intervención FABLE;
   - resultado final.

No hagas bucles indefinidos de agentes. Máximo:

- 1 intento del editor Opus;
- 1 intervención FABLE;
- 1 ciclo final de corrección supervisada.

Si sigue fallando, entrega la versión como `NO CONFORME` con evidencias.

### 4. Fase 0 — Fotografía Git y congelación del baseline

Ejecuta de forma segura:

```bash
git status
git remote -v
git fetch --all --prune
git branch -a -vv
git tag --sort=-creatordate
git log --graph --decorate --oneline --all
git for-each-ref --sort=-committerdate refs/heads refs/remotes
```

Determina:

- SHA real de `origin/main`;
- estado del PR #95;
- ramas relacionadas;
- merge-base;
- commits por delante/detrás;
- contenido ya integrado;
- ramas superseded;
- cambios recientes que afecten al motor.

Clasifica ramas por contenido, no por nombre.

Genera:

```text
artifacts/pr95-variants/git-snapshot.md
artifacts/pr95-variants/git-snapshot.json
```

El supervisor debe aprobar el SHA de referencia antes de crear ramas.

### 5. Fase 1 — Rama base común

Crea desde el SHA aprobado:

```text
exp/pr95-compare-base-contract-v1
```

Usa un worktree exclusivo.

#### Alcance permitido

- reproducir y corregir el contrato ID/texto;
- introducir una entrada explícita para evaluación externa;
- pasar `document_text`;
- conservar `source_segment_id` para trazabilidad;
- validar evidencia contra texto real;
- añadir hash/versiones;
- instrumentar métricas comunes;
- crear manifest y artefactos;
- añadir tests comunes.

#### Alcance prohibido

- cambiar el algoritmo de anclaje;
- realinear fuzzy;
- introducir fragment IDs;
- parser nuevo;
- cambiar generación de pares;
- cambiar review policy;
- bajar thresholds;
- escribir Neo4j.

#### Tests mínimos

```python
assert provider_received_document == segment["text"]
assert provider_received_document != segment["id"]
assert document_text[start:end] == evidence_text
```

Añade además:

- Unicode NFC/NFD;
- CRLF/LF;
- citas repetidas;
- texto vacío;
- offsets fuera de rango;
- timeout;
- respuesta inválida;
- no red;
- no escritura;
- determinismo.

Ejecuta todas las suites relevantes y archiva resultados.

El Supervisor General, Seguridad y QA deben aprobar la base.

Solo después crea un commit de base único y registra su SHA como `BASE_SHA`.

### 6. Fase 2 — Crear cuatro ramas independientes

Desde exactamente `BASE_SHA`:

```text
exp/pr95-v1-conservative-anchor
exp/pr95-v2-deterministic-realignment
exp/pr95-v3-fragment-selection
exp/pr95-v4-hybrid-staged-engine
```

Crea un worktree diferente para cada rama.

Ningún equipo puede:

- mergear otra versión;
- cherry-pickear otra versión;
- leer resultados finales de otra versión antes de cerrar su diseño;
- modificar el corpus común;
- modificar thresholds;
- cambiar definiciones comunes de métricas.

### 7. Equipo V1 — Anclaje conservador

Implementa:

- sentence bounds;
- cláusula segura;
- inclusión de negación;
- inclusión de atribución;
- inclusión temporal/epistémica;
- fallback al span anterior;
- flag desactivado por defecto;
- evidencia literal.

No implementes fuzzy matching ni fragment IDs.

Pruebas específicas:

- negación fuera de la envolvente inicial;
- dos cláusulas;
- sujeto/objeto repetidos;
- temporalidad al final;
- rumor en contexto;
- frase sin puntuación;
- fallback seguro;
- test metamórfico de estrechamiento;
- no regresión estructural.

### 8. Equipo V2 — Realineamiento determinista

Implementa:

```text
exact
→ normalized exact
→ token/character alignment
→ fuzzy limitado a ventana
→ rechazo de ambigüedad
→ vuelta al original
```

Requisitos:

- mapa reversible original↔normalizado;
- score de alineamiento;
- umbral predeclarado;
- varias coincidencias equivalentes = rechazo;
- evidencia final literal;
- sin recuperación semántica ilimitada.

Pruebas específicas:

- NFC/NFD;
- comillas;
- espacios;
- CRLF;
- repetición;
- paráfrasis;
- ambigüedad;
- prompt injection;
- false alignment;
- texto truncado.

### 9. Equipo V3 — Selección por fragmentos

Implementa un protocolo versionado:

```json
{
  "candidate_id": "...",
  "fragment_ids": ["f-003"],
  "verdict": "...",
  "confidence": 0.0
}
```

El sistema:

- crea fragmentos estables;
- presenta IDs;
- reconstruye offsets;
- valida literalidad;
- conserva contexto;
- permite uno o varios IDs solo en la capa experimental.

No migres el contrato persistente de producción.

Pruebas específicas:

- estabilidad de IDs;
- cambios de normalización;
- dos fragmentos;
- fragmento inexistente;
- solapamientos;
- orden;
- documento largo;
- token budget;
- fragmentación adversarial.

### 10. Equipo V4 — Pipeline híbrido

Separa internamente:

```text
SegmentReference
RelationHypothesis
EvidenceBundle
```

Implementa por etapas y flags:

- generación/ranking de menciones;
- hipótesis estructural;
- predicado/dirección;
- evidencia;
- verificación;
- temporal/epistémica;
- consenso.

Requisitos:

- cada etapa desactivable;
- ablation completa;
- parser fuerte solo opcional;
- fallback stdlib;
- sin cambio del contrato público sin adaptador;
- top-k acotado;
- contexto de razonamiento separado de evidencia.

Pruebas específicas:

- ablation por etapa;
- inter-frase;
- varias menciones;
- predicado;
- dirección;
- explosión de candidatos;
- rendimiento;
- compatibilidad.

### 11. Benchmark común

No permitas que cada equipo invente su evaluación.

Usa:

1. corpus vigente;
2. corpus independiente;
3. corpus adversarial.

Métricas obligatorias:

```text
pair_precision
pair_recall
pair_f1
predicate_exact
predicate_canonical
direction_exact
related_to_rate
pair_generation_recall
evidence_exact_match
evidence_char_f1
evidence_token_f1
evidence_iou
offset_exact_match
start_absolute_error
end_absolute_error
boundary_mae
literal_evidence_rate
realignment_success_rate
ambiguous_realignment_rate
negation_accuracy
temporality_accuracy
epistemic_accuracy
decision_accuracy
latency_p50
latency_p95
provider_invalid_rate
network_attempts
write_attempts
```

La métrica antigua de cualquier solapamiento debe mostrarse como:

```text
offsets_overlap
```

No como `offsets_correct`.

### 12. Proveedores reales

Primero ejecuta todo offline.

Solo ejecuta Ollama o NVIDIA cuando:

- la base esté aprobada;
- la suite offline esté verde;
- exista autorización explícita;
- la capability de red esté habilitada;
- el corpus esté autorizado;
- los logs estén redactados.

Mantén idénticos:

- modelo;
- temperatura;
- seed si aplica;
- prompt salvo la diferencia de protocolo propia de la versión;
- límites;
- timeout;
- número de reintentos.

Registra fallos, no los ocultes.

### 13. Seguridad

El revisor de seguridad debe probar:

- prompt injection;
- documento que intenta cambiar el sistema;
- Unicode Bidi;
- output JSON hostil;
- campos extra;
- tipos incorrectos;
- path traversal en artefactos;
- secretos en logs;
- egress no autorizado;
- intento de escritura;
- timeout;
- payload grande;
- deserialización;
- dependencia opcional ausente.

Dictamen permitido:

- `CONFORME`;
- `CONFORME CON OBSERVACIONES`;
- `NO CONFORME`.

### 14. Calidad

QA debe:

- ejecutar suite completa;
- revisar tests nuevos;
- verificar que un test falla sin el cambio;
- comprobar determinismo;
- revisar cobertura;
- ejecutar mutation tests de invariantes;
- validar artefactos;
- comparar contra baseline;
- verificar worktree limpio;
- comprobar que `main` y ramas existentes no cambiaron.

### 15. Entregables por versión

En cada rama crea:

```text
docs/experiments/pr95/<version>/README.md
docs/experiments/pr95/<version>/design.md
docs/experiments/pr95/<version>/test-plan.md
docs/experiments/pr95/<version>/results.md
docs/experiments/pr95/<version>/security.md
docs/experiments/pr95/<version>/limitations.md
artifacts/pr95-variants/<version>/*
```

El informe debe incluir:

- SHA base;
- SHA final;
- diffstat;
- hipótesis;
- arquitectura;
- cambios;
- tests;
- fallos;
- FABLE activado o no;
- métricas;
- seguridad;
- rendimiento;
- limitaciones;
- rollback;
- resultado `CONFORME` o `NO CONFORME`.

### 16. PRs

Abre cinco PRs draft:

```text
base contract
V1
V2
V3
V4
```

Las cuatro versiones deben tener como base el PR/branch experimental base, nunca `main`.

Añade claramente:

```text
DO NOT MERGE
EXPERIMENTAL
NO DEPLOY
NO NEO4J WRITE
```

No fusiones nada.

### 17. Informe de cierre

El Supervisor General debe entregar:

1. fotografía Git;
2. prueba de que `main` no cambió;
3. tabla de ramas;
4. SHA base;
5. estado de cada versión;
6. tests ejecutados;
7. seguridad;
8. intervención FABLE;
9. artefactos;
10. bloqueos;
11. diferencias metodológicas;
12. datos necesarios para la comparativa posterior.

No declares una ganadora.  
No combines resultados con opiniones.  
No ocultes resultados negativos.  
No prometas trabajo posterior.  
Deja todas las ramas listas para una auditoría comparativa independiente.

---

# 11. Criterios de aceptación globales

La ejecución completa será aceptable cuando:

- P0 esté reproducido y corregido en la base;
- `main` permanezca idéntico;
- ninguna rama existente haya cambiado;
- las cuatro versiones partan del mismo `BASE_SHA`;
- cada versión tenga editor Opus y revisión independiente;
- FABLE se active cuando corresponda;
- todas las pruebas y fallos estén registrados;
- no haya escritura, despliegue o ingesta;
- no se bajen umbrales;
- la red permanezca cerrada salvo autorización;
- los artefactos sean comparables;
- los PR queden en draft;
- no se elija ganador.

---

# 12. Conclusión final

El problema del PR #95 no es un único fallo de “calidad del LLM”. Es una cadena de defectos y limitaciones:

1. el proveedor externo puede recibir el ID en lugar del texto;
2. la evidencia heurística es demasiado mecánica;
3. el protocolo exige offsets que los modelos manejan mal;
4. la medición no distingue suficientemente exactitud, solapamiento y suficiencia;
5. el matching y el ground truth limitan la interpretación;
6. la generación de pares, predicado, dirección y temporalidad tienen defectos independientes;
7. el benchmark actual no justifica una decisión definitiva.

La estrategia correcta no es cambiar de modelo a ciegas ni rebajar validaciones. Es:

- corregir el contrato;
- medir de forma reproducible;
- construir versiones aisladas;
- conservar seguridad;
- ejecutar el mismo benchmark;
- comparar después con evidencia homogénea.
