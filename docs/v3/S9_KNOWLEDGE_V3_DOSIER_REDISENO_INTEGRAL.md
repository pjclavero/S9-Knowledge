# DOSIER TÉCNICO DE REDISEÑO INTEGRAL
## S9-Knowledge V3 — desde la entrada multimodal hasta la validación local y el grafo

**Repositorio:** `https://github.com/pjclavero/S9-Knowledge`  
**Informe de partida:** PR `#106`  
**Fecha del dosier:** 27 de julio de 2026  
**Alcance:** arquitectura, contratos, integración, pruebas, seguridad, organización multiagente y criterios de aceptación.  
**Restricción:** este documento describe la solución técnica; no contiene implementación de código.

---

# 1. Decisión arquitectónica

S9-Knowledge debe rediseñar conjuntamente:

1. la entrada y normalización multimodal;
2. el extractor de entidades y afirmaciones;
3. el motor de relaciones;
4. la resolución de identidad;
5. la temporalidad y procedencia;
6. la validación y aprobación local;
7. la preparación de mutaciones;
8. la escritura controlada en Neo4j.

No se recomienda continuar ampliando el extractor heurístico y el selector léxico actuales mediante nuevas expresiones, listas de verbos o excepciones.

El PR #106 demuestra que el problema es extremo a extremo:

- el extractor real reduce drásticamente los pares alcanzables;
- el motor se degrada adicionalmente al recibir entidades imperfectas;
- la cadena completa obtiene aproximadamente un único predicado correcto de 52 relaciones en la prueba real descrita;
- aparecen alrededor de 170 falsos positivos;
- la dirección y la temporalidad no generalizan;
- los resultados altos del corpus de desarrollo estaban sobreajustados;
- los tests y gates anteriores no siempre ejercitaban la ruta real.

La nueva versión se desarrollará en paralelo con la actual.

```text
v1/v2 actual:
    baseline + rollback

v3:
    rediseño completo aislado
    modo sombra
    sin escritura durante desarrollo
```

No se eliminará el motor actual hasta que V3 supere pruebas separadas, integradas y extremo a extremo sobre datos no vistos.

---

# 2. Principio innegociable de autoridad

## 2.1. Única autoridad

**El motor local de S9-Knowledge es la única autoridad que puede:**

- validar una entidad;
- resolver una identidad;
- normalizar un predicado;
- determinar la dirección;
- aprobar una temporalidad;
- resolver una contradicción;
- cerrar una vigencia;
- invalidar una afirmación anterior;
- aprobar un candidato;
- generar un plan de mutación;
- autorizar la escritura en Neo4j.

## 2.2. Ollama

Ollama es el razonador semántico local principal.

Puede:

- extraer menciones;
- proponer entidades;
- proponer correferencias;
- proponer afirmaciones;
- clasificar alternativas;
- explicar incertidumbre;
- seleccionar evidencia;
- ayudar a comparar candidatos.

Ollama **no escribe directamente** y su salida tampoco se considera aprobada automáticamente.

Toda salida de Ollama pasa por el motor local determinista.

## 2.3. NVIDIA y otros servicios externos

Los proveedores externos aportan potencia de cálculo para aliviar la carga del servidor.

Pueden utilizarse para:

- OCR;
- HTR o reconocimiento de escritura a mano;
- transcripción de audio;
- diarización;
- análisis visual;
- descripción de diagramas;
- extracción semántica;
- embeddings;
- reranking;
- generación de candidatos;
- segunda opinión;
- procesamiento de lotes.

Los proveedores externos:

- no aprueban;
- no rechazan definitivamente;
- no invalidan;
- no cierran vigencias;
- no modifican la ontología;
- no escriben;
- no elevan por sí solos la confianza de aprobación;
- no sustituyen la comprobación local.

Toda respuesta externa se trata como **entrada no confiable**.

## 2.4. Puerta única de escritura

```text
Proveedor local o externo
        ↓
Propuesta no confiable
        ↓
Validación estructural local
        ↓
Resolución semántica local
        ↓
Resolución de identidad local
        ↓
Resolución temporal local
        ↓
Comprobación de contradicciones
        ↓
Decisión local
        ↓
GraphMutationPlan firmado localmente
        ↓
ApprovedGraphWriter
        ↓
Neo4j
```

Si falta la firma o el dictamen local, el escritor debe rechazar el payload.

---

# 3. Estado real del sistema según el PR #106

## 3.1. Resultados del motor con entidades perfectas

| Métrica | Corpus desarrollo | Held-out sintético | Material real |
|---|---:|---:|---:|
| Predicado | 0.8140 | 0.5385 | 0.2391 |
| Temporalidad | 0.8837 | 0.5641 | 0.1957 |
| Strict F1 | 0.6604 | 0.4565 | 0.1897 |
| Dirección | 0.9302 | 0.8974 | 0.6957 |
| Evidencia | 0.9302 | 0.8462 | 0.7174 |
| Pair F1 | 0.8113 | 0.8478 | 0.7931 |

Estos resultados todavía regalaban al motor las entidades del ground truth.

## 3.2. Resultados de la cadena completa

En la medición `extractor real → motor` sobre material real:

| Entrada de entidades | Pair F1 | Predicado | Strict F1 |
|---|---:|---:|---:|
| Perfectas | 0.7931 | 0.2391 | 0.1897 |
| Reales, IDs estrictos | 0.0333 | 0.0000 | 0.0000 |
| Reales, matching laxo | 0.1610 | 0.0526 | 0.0085 |

También se documentan:

- caída de `types_correct`;
- falsos positivos de aproximadamente 165–184;
- dependencia del ground truth para enlazar IDs incluso en la medición laxa;
- un gate capaz de producir un dictamen aceptable con `pair_F1` extremadamente bajo.

## 3.3. Diagnóstico

El sistema actual tiene dos problemas multiplicativos:

```text
alcanzabilidad del extractor
×
acierto semántico del motor
=
acierto extremo a extremo
```

Arreglar únicamente el extractor deja un motor semántico débil.

Arreglar únicamente el motor deja la mayoría de relaciones fuera de alcance.

Por eso V3 debe tratar ambos como un único programa, pero mantener benchmarks independientes.

---

# 4. Qué se conserva

## 4.1. Contratos y fronteras

Se conserva el contrato:

```text
relation-candidate/internal-v1
```

Campos:

```text
subject_id
subject_type
predicate
object_id
object_type
direction
confidence
evidence_text
evidence_start
evidence_end
source_id
source_page
source_segment
extraction_method
model
negated
temporal_scope
epistemic_status
workspace
validation_flags
```

V3 puede usar contratos internos más ricos, pero debe proyectar su resultado final a este contrato para mantener compatibles los consumidores existentes.

La información adicional se guarda en contratos adyacentes.

## 4.2. Componentes reutilizables

- aislamiento por workspace;
- hashes de fuente;
- determinismo de artefactos;
- `MultimediaArtifact`;
- dispatcher de procesamiento externo;
- circuit breaker;
- validación de respuestas externas;
- escaneo de secretos;
- generación y control de trabajos;
- ontology domain/range;
- contratos de relaciones;
- anclaje literal de evidencia;
- protocolo por fragmentos;
- realineamiento con unicidad obligatoria;
- review store;
- cola de revisión;
- writer aprobado;
- arneses existentes como baseline;
- corpus B1, H1 y H2;
- extractor benchmark;
- perfiles de proveedor;
- acceso OpenAI-compatible;
- Ollama;
- NVIDIA NIM;
- rollback mediante flags.

## 4.3. Componentes que quedan como baseline

No se eliminan, pero no serán el núcleo de V3:

- `review/extractor.py`;
- `relations/predicate_selector.py`;
- `relations/direction.py`;
- `relations/temporal_v2.py`;
- `relations/abstention.py`;
- selector V1;
- selector V2.

Se mantendrán para:

- comparación;
- regresión;
- rollback;
- análisis de ablación.

---

# 5. Patrones adoptados de motores que funcionan

---

## 5.1. Graphiti

Se adopta:

- unidad de ingesta tipo episodio;
- procesamiento incremental;
- procedencia episodio → afirmación;
- `valid_from` y `valid_to`;
- invalidación o supersession sin borrado;
- hechos que evolucionan;
- integración de nuevas fuentes sin reconstrucción completa;
- ontología prescrita con descubrimiento controlado;
- proveedor de modelos intercambiable.

Aplicación en S9-Knowledge:

```text
SourceAsset
    └── SourceEpisode
            └── EvidenceFragment
                    └── FactAssertion
```

Una afirmación nueva puede:

- confirmar una anterior;
- ampliar su evidencia;
- contradecirla;
- sustituirla a partir de una fecha;
- coexistir con ella por distinta fuente o epistemicidad.

---

## 5.2. TrustGraph

Se adopta:

- `Workspace` como aislamiento estructural;
- `Collection` como campaña o corpus;
- `Flow` como pipeline versionado;
- configuración separada de infraestructura;
- procedencia obligatoria;
- snapshot y rollback;
- política de autoridad de fuentes;
- capacidades de proveedor;
- contratos portables.

Aplicación:

```text
Workspace
    └── Collection
            └── SourceAsset
                    └── FlowRun
```

`workspace` no será solo un campo en el payload. Debe formar parte de:

- IDs;
- cachés;
- consultas;
- rutas;
- índices;
- trabajos;
- métricas;
- artefactos;
- claves de deduplicación.

---

## 5.3. Neo4j LLM Graph Builder

Se adopta:

- adaptadores de fuentes;
- schema configurable;
- selección de modelos;
- preview antes de persistir;
- postprocesado;
- deduplicación;
- estado por fuente;
- métricas de consumo;
- visualización de una fuente concreta;
- posibilidad de reintentar una fuente.

Aplicación:

- cada fuente tendrá un manifiesto de procesamiento;
- el usuario podrá ver el grafo propuesto antes de aprobar;
- la escritura será una fase distinta de la extracción;
- se guardarán proveedor, modelo, versión, coste y latencia.

---

## 5.4. LlamaIndex Property Graph

Se adopta:

- extractores como transformaciones;
- varios extractores aplicables al mismo episodio;
- schema estricto;
- modo dinámico solo para descubrimiento;
- abstracción de LLM;
- abstracción de almacenamiento;
- composición de extractores;
- salida desacoplada del almacén.

Aplicación:

```text
EpisodeTransform[]
    - EntityMentionExtractor
    - CoreferenceExtractor
    - ClaimExtractor
    - TemporalExpressionExtractor
    - VisualClaimExtractor
```

Todos producen propuestas; el motor local las fusiona y valida.

---

# 6. Arquitectura objetivo V3

```text
FUENTE
    ↓
A. Ingesta y normalización multimodal
    ↓
B. Episodios y fragmentos de evidencia
    ↓
C. Extracción de menciones y afirmaciones
    ↓
D. Resolución de entidades
    ↓
E. Motor local de conocimiento
    ↓
F. Ledger temporal y procedencia
    ↓
G. Validación y aprobación local
    ↓
H. GraphMutationPlan
    ↓
I. Writer controlado
    ↓
NEO4J
```

Cada letra es un subsistema con pruebas propias.

---

# 7. Subsistema A — ingesta y normalización multimodal

## 7.1. Entradas

Debe aceptar desde el principio:

- PDF con texto;
- PDF escaneado;
- imágenes;
- fotografías;
- capturas;
- texto manuscrito;
- dibujos;
- mapas;
- diagramas;
- fichas;
- tablas;
- audio;
- vídeo;
- YouTube;
- Markdown;
- texto;
- web;
- notas.

## 7.2. Contrato `SourceAsset`

Campos recomendados:

```yaml
asset_id:
workspace:
collection_id:
game_profile:
source_kind:
mime_type:
content_hash:
byte_size:
original_name:
original_location:
created_at:
ingested_at:
language_hint:
privacy_class:
copyright_class:
processing_policy:
metadata:
```

## 7.3. Contrato `SourceEpisode`

Una fuente se divide en episodios.

Ejemplos:

- página;
- sección;
- escena;
- intervalo de audio;
- turno de hablante;
- frame;
- región;
- bloque manuscrito;
- tabla;
- mensaje.

```yaml
episode_id:
asset_id:
workspace:
sequence:
modality:
text:
page:
bbox:
time_start:
time_end:
previous_episode_id:
next_episode_id:
quality:
content_hash:
provider_trace:
```

## 7.4. Contrato `EvidenceFragment`

```yaml
fragment_id:
episode_id:
literal_text:
normalized_text:
start:
end:
bbox:
time_start:
time_end:
frame_id:
page:
media_type:
confidence:
source_hash:
provider:
model:
version:
```

Los offsets, bounding boxes y timecodes son calculados o verificados localmente.

## 7.5. Flujo PDF

```text
PDF
  ├── texto nativo suficiente → extracción directa
  ├── texto defectuoso → OCR selectivo
  ├── página escaneada → OCR/HTR
  ├── tabla → extractor de tablas
  └── diagrama/mapa → análisis visual separado
```

No se aplicará OCR a todas las páginas si el texto nativo es correcto.

## 7.6. Flujo imagen, manuscrito y dibujo

Se separan:

- OCR literal;
- HTR;
- layout;
- descripción visual;
- objetos visuales;
- claims visuales.

Una descripción visual nunca se mezcla con OCR como si fuera texto literal.

Los claims derivados de dibujos o diagramas comienzan con:

```text
epistemic_status = VISUAL_INFERRED
review_required = true
```

hasta que el motor local los valide.

## 7.7. Flujo audio

- normalización;
- VAD;
- segmentación;
- ASR;
- timestamps;
- diarización opcional;
- glosario;
- detección de repetición;
- detección de truncado;
- score de cobertura;
- episodios por escena o turno.

El sistema debe detectar:

- final ausente;
- bucles de repetición;
- nombres inconsistentes;
- segmentos sin audio;
- saltos temporales;
- idioma incorrecto.

## 7.8. Flujo vídeo

- audio → flujo ASR;
- keyframes;
- escenas;
- OCR de pantalla;
- subtítulos;
- descripción visual;
- alineación de audio, texto y frames.

Los subtítulos automáticos externos son una fuente adicional, no ground truth.

---

# 8. Política de proveedores y carga

## 8.1. Niveles de ejecución

### Nivel 0 — local determinista

- extracción de texto nativo;
- hashes;
- chunking;
- offsets;
- validación;
- schema;
- reglas de seguridad;
- deduplicación exacta;
- resolución básica;
- control de escritura.

### Nivel 1 — Ollama local

- extracción semántica;
- clasificación de menciones;
- claims;
- correferencia;
- temporalidad implícita;
- comparación de alternativas;
- explicación de incertidumbre.

### Nivel 2 — potencia externa

Se activa cuando:

- la modalidad no puede resolverse localmente;
- el servidor está saturado;
- la cola supera un umbral;
- la calidad local es baja;
- el lote es grande;
- se solicita segunda opinión;
- una capacidad especializada ofrece una ventaja clara.

## 8.2. Planner

El `ProcessingPlanner` decide:

```yaml
task:
preferred_provider:
fallback_provider:
privacy_policy:
max_cost:
max_latency:
local_validation_required: true
```

## 8.3. Privacidad

Las fuentes se clasifican:

- `LOCAL_ONLY`;
- `EXTERNAL_ALLOWED_REDACTED`;
- `EXTERNAL_ALLOWED`;
- `MANUAL_ONLY`.

Las grabaciones con datos personales pueden permanecer `LOCAL_ONLY`.

## 8.4. Reglas de salida externa

Toda salida externa debe incluir:

- source hash;
- chunk/episode ID;
- workspace;
- modelo;
- versión;
- timestamps;
- fragmentos;
- confidence;
- schema version.

Después pasa por:

```text
external_processing/result_validator.py
        ↓
adaptador a propuesta interna
        ↓
motor local
```

---

# 9. Subsistema B — extractor semántico

## 9.1. Responsabilidad

El extractor no crea directamente el grafo.

Produce:

- menciones;
- tipos candidatos;
- alias;
- correferencias;
- afirmaciones crudas;
- eventos;
- expresiones temporales;
- evidencia;
- alternativas;
- abstenciones.

## 9.2. Contrato `EntityMention`

```yaml
mention_id:
episode_id:
surface:
normalized_surface:
start:
end:
bbox:
time_start:
time_end:
type_candidates:
confidence:
coreference_candidates:
evidence_fragment_ids:
provider_trace:
```

## 9.3. Contrato `ClaimProposal`

```yaml
claim_id:
subject_mentions:
relation_phrase:
object_mentions:
predicate_candidates:
direction_candidates:
temporal_expressions:
negated:
epistemic_cues:
qualifiers:
evidence_fragment_ids:
confidence:
alternatives:
abstained:
provider_trace:
```

No necesita decidir todavía el predicado canónico.

## 9.4. Extractores paralelos

Sobre el mismo episodio pueden ejecutarse:

1. extractor determinista;
2. extractor Ollama;
3. extractor externo;
4. extractor visual;
5. extractor de tablas;
6. extractor de eventos;
7. extractor de temporalidad.

Las salidas no se votan por mayoría simple.

El motor local las compara según:

- evidencia;
- cobertura;
- compatibilidad;
- independencia;
- autoridad de la fuente;
- historial del proveedor;
- calidad del episodio.

## 9.5. Ollama como extractor principal

Ollama recibe:

- episodio;
- contexto anterior y posterior;
- schema;
- tipos permitidos;
- vocabulario genérico;
- glosario del workspace;
- candidatos conocidos del grafo;
- obligación de usar fragment IDs;
- opción de abstenerse.

No debe recibir la libertad de inventar IDs, offsets o tipos fuera del contrato.

## 9.6. Extracción externa

La extracción externa puede ser más rápida o potente, pero su salida sigue siendo `ClaimProposal`.

No puede producir un `GraphMutationPlan`.

---

# 10. Subsistema C — resolución de identidad

## 10.1. Problema

Las variantes:

```text
Daiki
Daiqui
daiki
el magistrado
él
```

pueden representar una sola entidad o varias.

La resolución no puede depender únicamente del nombre normalizado.

## 10.2. Contrato `EntityResolution`

```yaml
resolution_id:
mention_ids:
candidate_entity_ids:
selected_entity_id:
action:
  - LINK_EXISTING
  - CREATE_PROVISIONAL
  - CREATE_NEW
  - SPLIT
  - REVIEW
confidence:
evidence:
reason_codes:
workspace:
game_profile:
```

## 10.3. Señales

- nombre exacto;
- alias;
- glosario;
- tipo;
- descripción;
- relaciones vecinas;
- proximidad temporal;
- fuente;
- workspace;
- embeddings;
- correferencia;
- título;
- contexto;
- exclusiones conocidas.

## 10.4. Estados provisionales

Una entidad puede crearse en staging como:

```text
PROVISIONAL
```

No tiene por qué convertirse inmediatamente en nodo canónico.

Esto evita fabricar nodos definitivos por cada error de ASR u OCR.

## 10.5. Resolución por juego

Ahora se utilizará:

```text
game_profile = generic
```

Desde el primer contrato debe existir el campo para que en el futuro puedan añadirse:

- perfil Leyenda;
- perfil Mundo de Tinieblas;
- perfil Trudvang;
- otros.

---

# 11. Subsistema D — motor local de conocimiento

## 11.1. Responsabilidad

El motor recibe:

- episodios;
- evidencias;
- menciones;
- resoluciones;
- claims;
- contexto del grafo;
- ontología;
- historial temporal;
- propuestas Ollama;
- propuestas externas.

Y produce:

- afirmaciones validadas;
- afirmaciones en revisión;
- abstenciones;
- contradicciones;
- supersessions;
- planes de mutación.

## 11.2. Etapas

```text
1. Validate input contracts
2. Resolve subject/object identity
3. Determine relation existence
4. Normalize predicate
5. Resolve direction
6. Resolve negation
7. Resolve epistemic state
8. Resolve temporal validity
9. Check ontology
10. Check evidence
11. Check graph conflicts
12. Decide
```

## 11.3. Predicado

El predicado se resuelve mediante:

- schema;
- definición semántica;
- descripción del claim;
- tipos;
- evidencia;
- comparación con predicados confundibles;
- Ollama local;
- embeddings opcionales;
- propuesta externa opcional.

No se selecciona por una lista de palabras como método principal.

## 11.4. Dirección

La dirección se deriva de:

- sujeto semántico;
- objeto semántico;
- voz;
- agente;
- inversa;
- simetría;
- correferencia;
- estructura del claim.

Las relaciones simétricas usan:

```text
semantic_direction = NONE
```

## 11.5. Temporalidad

Se separan:

```yaml
source_time:
recorded_at:
asserted_at:
event_time:
valid_from:
valid_to:
state:
```

Estados:

- `ACTIVE`;
- `ENDED`;
- `PLANNED`;
- `HYPOTHETICAL`;
- `RECURRING`;
- `UNKNOWN`.

El pasado verbal no significa automáticamente `ENDED`.

## 11.6. Epistemicidad

Estados mínimos:

- `ASSERTED`;
- `RUMORED`;
- `HYPOTHETICAL`;
- `INTENDED`;
- `VISUAL_INFERRED`;
- `CONFLICTED`;
- `UNKNOWN`.

## 11.7. Decisiones

```text
LOCAL_APPROVED
LOCAL_APPROVED_WITH_WARNINGS
REVIEW_ENTITY
REVIEW_PREDICATE
REVIEW_DIRECTION
REVIEW_TEMPORALITY
REVIEW_EVIDENCE
CONFLICT
ABSTAIN
REJECT_INVALID
```

`REJECT_INVALID` solo se usa para incompatibilidades demostrables.

Ante duda semántica se prefiere `ABSTAIN` o revisión.

---

# 12. Ledger temporal y procedencia

## 12.1. Modelo de afirmación

Se recomienda almacenar primero una afirmación, no únicamente una arista directa.

```text
(Entity)-[:SUBJECT_OF]->(FactAssertion)
(FactAssertion)-[:OBJECT_OF]->(Entity)
(FactAssertion)-[:SUPPORTED_BY]->(EvidenceFragment)
(FactAssertion)-[:FROM_EPISODE]->(SourceEpisode)
```

`FactAssertion` contiene:

```yaml
predicate:
direction:
valid_from:
valid_to:
recorded_at:
epistemic_status:
confidence:
status:
workspace:
collection_id:
game_profile:
engine_version:
```

## 12.2. Supersession

Una afirmación nueva puede:

- confirmar;
- corregir;
- limitar;
- reemplazar;
- contradecir;
- finalizar;
- reabrir.

Nunca se borra la historia silenciosamente.

```text
(old)-[:SUPERSEDED_BY]->(new)
```

## 12.3. Proyección

Para consultas rápidas se pueden materializar aristas directas:

```text
(Entity)-[:ALLY_OF]->(Entity)
```

La fuente autoritativa sigue siendo `FactAssertion`.

---

# 13. Validación y aprobación local

## 13.1. Dos validaciones distintas

### Validación estructural

- schema;
- hashes;
- workspace;
- offsets;
- fragment IDs;
- rangos;
- secretos;
- tipos;
- límites.

### Validación semántica

- existencia de relación;
- identidad;
- predicado;
- dirección;
- temporalidad;
- epistemicidad;
- contradicción;
- consistencia con ontología;
- evidencia suficiente.

La validación estructural no equivale a aprobación semántica.

## 13.2. Firma local

El resultado aprobado se encapsula en:

```yaml
GraphMutationPlan:
  plan_id:
  workspace:
  source_hash:
  engine_version:
  ontology_version:
  decisions:
  mutation_operations:
  local_approval:
    approved: true
    decision_hash:
    validator_chain:
    created_at:
```

El writer comprueba:

- firma/hash;
- versión;
- workspace;
- source hash;
- decisión;
- ausencia de campos externos no validados.

## 13.3. Writer

El writer:

- no interpreta;
- no corrige;
- no consulta modelos;
- no decide;
- solo ejecuta un plan local válido;
- es idempotente;
- soporta rollback;
- registra auditoría.

---

# 14. Perfiles por juego

## 14.1. Diseño inicial

Todos los juegos usan inicialmente:

```text
game_profile = generic
```

Pero la arquitectura carga:

```text
core ontology
+ generic profile
+ workspace glossary
```

## 14.2. Futuro

```text
core ontology
+ game profile
+ workspace glossary
+ optional learned adapter
```

## 14.3. Contenido de un perfil

- tipos específicos;
- alias;
- títulos;
- facciones;
- calendarios;
- predicados exclusivos;
- dominios y rangos;
- reglas de identidad;
- términos ambiguos;
- prioridades de fuente;
- ejemplos de evaluación.

## 14.4. Modelo aprendido futuro

No se entrenará un modelo productivo con el corpus pequeño actual.

La arquitectura permitirá:

```text
modelo base común
+ adaptador pequeño por juego
```

cuando existan suficientes correcciones revisadas.

---

# 15. Estructura de módulos recomendada

Se recomienda aislar V3.

```text
data-engine/app/knowledge_v3/
├── __init__.py
├── orchestrator.py
├── config.py
├── contracts/
│   ├── source_asset.py
│   ├── episode.py
│   ├── evidence.py
│   ├── mention.py
│   ├── claim.py
│   ├── resolution.py
│   ├── assertion.py
│   └── mutation_plan.py
├── ingestion/
│   ├── router.py
│   ├── pdf.py
│   ├── image.py
│   ├── audio.py
│   ├── video.py
│   ├── text.py
│   └── quality.py
├── extraction/
│   ├── base.py
│   ├── deterministic.py
│   ├── ollama.py
│   ├── external.py
│   ├── visual.py
│   ├── tables.py
│   ├── coreference.py
│   └── merger.py
├── resolution/
│   ├── entity_resolver.py
│   ├── alias_resolver.py
│   ├── embedding_matcher.py
│   └── provisional_store.py
├── engine/
│   ├── local_authority.py
│   ├── predicate.py
│   ├── direction.py
│   ├── temporality.py
│   ├── epistemic.py
│   ├── contradiction.py
│   ├── evidence.py
│   └── decision.py
├── ledger/
│   ├── assertions.py
│   ├── supersession.py
│   ├── snapshots.py
│   └── projection.py
├── providers/
│   ├── planner.py
│   ├── ollama.py
│   ├── external_adapter.py
│   └── capabilities.py
├── profiles/
│   ├── base.py
│   ├── generic.py
│   └── registry.py
├── adapters/
│   ├── relation_candidate_v1.py
│   ├── multimedia_artifact_v1.py
│   └── review_pipeline.py
└── observability/
    ├── events.py
    ├── metrics.py
    └── audit.py
```

Esto permite avanzar sin contaminar V1/V2.

---

# 16. Archivos actuales implicados

## 16.1. Integración principal

- `data-engine/app/ingest_rpg.py`
- `data-engine/app/review/pipeline.py`
- `data-engine/app/relations/pipeline.py`

`ingest_rpg.py` no debe escribir directamente en la nueva ruta. Debe producir un `SourceAsset` o llamar al orquestador V3.

## 16.2. Extractor y resolución

- `review/extractor.py`
- `review/llm_extractor.py`
- `review/hybrid_filter.py`
- `review/resolver.py`
- `review/workspace_aliases.py`
- `glossary/`
- `cli/extractor_benchmark.py`

## 16.3. Motor

- `relations/contracts.py`
- `relations/ontology.py`
- `relations/pairs.py`
- `relations/pipeline.py`
- `relations/predicate_selector.py`
- `relations/direction.py`
- `relations/temporal_v2.py`
- `relations/epistemic.py`
- `relations/abstention.py`
- `relations/consensus_adapter.py`
- `relations/ensemble.py`
- `relations/review_policy.py`

## 16.4. Ollama y externo

- `relations/local_llm_shadow.py`
- `relations/external_ai_shadow.py`
- `relations/external_consult.py`
- `relations/fragment_protocol.py`
- `relations/evidence_realignment.py`
- `external_ai/`
- `external_processing/`
- `external_processing/providers/nvidia.py`

## 16.5. Multimedia

- `media/multimedia_contract.py`
- `media/transcriber.py`
- `media/worker.py`
- `media/audio_extract.py`
- `audio/transcribe_audio.py`
- `youtube/fetch_youtube.py`

## 16.6. Revisión y escritura

- `review/validator.py`
- `review/auto_decider.py`
- `review/approved_writer.py`
- `review/ingest_approved.py`
- `review/export_import.py`
- `review/review_store.py`
- `review/supersede_review.py`

## 16.7. Benchmark

- `relations/benchmark/`
- `cli/extractor_benchmark.py`
- `cli/benchmark_comparator.py`
- `tests/fixtures/benchmark/`
- corpus B1;
- corpus H1;
- corpus H2.

---

# 17. Estrategia de migración

## Fase 1 — sombra

V3 recibe copias de fuentes reales y produce artefactos.

No escribe.

## Fase 2 — comparación

```text
v1 extractor + v1 motor
v2 extractor + v2 motor
v3 extractor + v3 motor
gold extractor + v3 motor
v3 extractor + gold motor input
```

## Fase 3 — review asistido

V3 llena la cola de revisión.

El writer continúa bloqueado.

## Fase 4 — escritura controlada

Solo operaciones simples, tras gates.

## Fase 5 — promoción gradual

Por:

- predicado;
- modalidad;
- juego;
- fuente;
- nivel de confianza.

---

# 18. Programa de pruebas

## 18.1. Principio

Extractor y motor se prueban:

1. por separado;
2. juntos;
3. con los mismos datos;
4. con entradas perfectas;
5. con entradas reales;
6. con proveedores ausentes;
7. con proveedores maliciosos;
8. en held-out.

---

## 18.2. Dataset común

Cada caso debe contener:

```yaml
source_asset:
episodes_gold:
evidence_gold:
mentions_gold:
entities_gold:
claims_gold:
assertions_gold:
mutation_plan_gold:
```

Así el mismo caso se usa para todos los niveles.

## 18.3. Benchmark A — normalización

Entrada:

```text
fuente original
```

Salida esperada:

```text
episodios + evidencia
```

Métricas:

- cobertura;
- CER;
- WER;
- duración cubierta;
- páginas cubiertas;
- bbox IoU;
- timecode error;
- truncado;
- repetición;
- calidad de tablas;
- calidad de layout.

Modalidades:

- PDF nativo;
- escaneado;
- fotografía;
- manuscrito;
- dibujo;
- tabla;
- audio;
- vídeo.

## 18.4. Benchmark B — extractor

Entrada:

```text
episodios gold
```

Salida:

```text
menciones + claims
```

Métricas:

- entity mention precision/recall/F1;
- type accuracy;
- span accuracy;
- coreference F1;
- entity linking accuracy;
- claim existence precision/recall/F1;
- evidence coverage;
- candidate recall;
- false candidates per 1.000 palabras.

## 18.5. Benchmark C — motor

Entrada:

```text
menciones y claims gold
```

Salida:

```text
assertions y decisiones
```

Métricas:

- predicate exact;
- predicate family;
- direction;
- temporality;
- epistemic;
- negation precision y recall;
- evidence;
- decision;
- false approve;
- false reject;
- abstention;
- contradiction resolution;
- supersession accuracy.

## 18.6. Benchmark D — extremo a extremo

Entrada:

```text
fuente original
```

Salida:

```text
GraphMutationPlan
```

Métricas:

- exact fact precision/recall/F1;
- entity identity accuracy;
- predicate;
- direction;
- temporal validity;
- evidence;
- false write plan;
- missed fact rate;
- duplicate node rate;
- provenance completeness.

## 18.7. Ablaciones obligatorias

- entidades perfectas → motor;
- entidades reales → motor;
- claims perfectos → motor;
- extractor local only;
- extractor external only;
- extractor local + external;
- Ollama absent;
- NVIDIA absent;
- external response corrupta;
- external response adversarial;
- generic profile;
- profile incorrecto;
- sin glosario;
- con glosario;
- episodio aislado;
- contexto anterior/posterior;
- sin Neo4j;
- Neo4j solo lectura no disponible.

## 18.8. Test de escritura

El writer debe rechazar:

- plan sin firma;
- plan firmado por proveedor externo;
- plan con hash modificado;
- workspace cambiado;
- source hash incorrecto;
- decisión REVIEW;
- plan expirado;
- versión no soportada;
- operación no idempotente;
- predicado fuera de ontología.

---

# 19. Corpus

## 19.1. Desarrollo

Puede verse por los implementadores.

## 19.2. Held-out

No puede verlo el equipo que ajusta reglas o prompts.

Debe anotarse con doble pase.

## 19.3. Real reservado

- varios juegos;
- libros;
- transcripción;
- imágenes;
- escritura manual;
- vídeo;
- distintas formulaciones.

## 19.4. Seguridad

- prompt injection;
- secretos;
- rutas privadas;
- instrucciones dentro del documento;
- JSON malformado;
- offsets falsos;
- fragment IDs inventados;
- colisión de workspace;
- input gigante;
- bomba combinatoria;
- contenido repetido.

---

# 20. Gates

Los gates definitivos se fijarán tras auditar la línea base. Como condiciones estructurales:

## Gate de seguridad

- cero escrituras sin plan local válido;
- cero secretos en artefactos;
- cero mezcla de workspace;
- cero aprobación externa;
- fail-closed real;
- mutaciones de seguridad detectadas.

## Gate de evaluación

- held-out separado;
- doble pase;
- métricas extremo a extremo;
- no aceptar resultados solo en dev;
- no calcular métricas estructurales únicamente sobre verdaderos positivos;
- gate global de existencia;
- reportar estricto y laxo;
- intervalos de confianza.

## Gate de calidad

- mejora del extractor;
- mejora del motor con gold input;
- mejora extremo a extremo;
- falsos positivos bajo control;
- falsos rechazos bajo control;
- evidencia completa;
- procedencia completa;
- determinismo.

---

# 21. Organización multiagente

## 21.1. Fable — organizador y supervisor general

Fable:

- divide el trabajo;
- asigna propiedad de ficheros;
- evita solapes;
- mantiene el tablero;
- congela contratos;
- autoriza el inicio de cada ola;
- revisa resultados de Opus y Sonnet;
- exige pruebas de mutación;
- bloquea merges;
- prepara el dictamen global;
- verifica seguridad;
- verifica que no se ha manipulado el benchmark;
- decide `GO / NO-GO`.

Fable no implementa módulos salvo emergencia documentada.

## 21.2. Agentes Opus

Equipos:

1. Opus Arquitectura y contratos.
2. Opus Normalización multimodal.
3. Opus Extractor semántico.
4. Opus Resolución de identidad.
5. Opus Motor local.
6. Opus Temporalidad y ledger.
7. Opus Integración Ollama/NVIDIA.
8. Opus Writer y migración.
9. Opus Benchmark extremo a extremo.

Cada Opus trabaja en rama o worktree separada.

## 21.3. Agentes Sonnet

Sonnet se usa para:

- tests unitarios;
- tests de integración;
- fixtures;
- fuzzing;
- mutation testing;
- revisión estática;
- seguridad;
- cobertura;
- análisis de logs;
- documentación;
- comparación de métricas;
- control de formatos;
- revisión de dependencias.

Sonnet no aprueba arquitectura.

## 21.4. Independencia

Un agente no puede:

- implementar y dar dictamen final del mismo bloque;
- crear el held-out y ajustar el código contra él;
- cambiar el gate que está intentando superar;
- editar ground truth y motor en el mismo commit;
- aprobar su propia seguridad.

---

# 22. Paralelización

## Ola 0 — auditoría

En paralelo:

- mapa de flujo real;
- inventario de contratos;
- benchmark actual;
- ruta de escritura;
- Ollama;
- NVIDIA;
- multimedia;
- seguridad.

## Ola 1 — contratos

En paralelo:

- contratos de fuente;
- episodios;
- evidencia;
- menciones;
- claims;
- assertions;
- mutation plan;
- perfiles.

Después se congelan.

## Ola 2 — construcción paralela

- normalizador;
- extractor;
- resolver;
- motor;
- ledger;
- proveedor planner;
- benchmark.

Cada equipo solo modifica su carpeta.

## Ola 3 — integración

- adaptadores;
- orquestador;
- cola de revisión;
- writer;
- observabilidad.

## Ola 4 — validación

- pruebas separadas;
- pruebas conjuntas;
- held-out;
- seguridad;
- rendimiento;
- fallos.

## Ola 5 — cierre

- informe;
- matriz A/B;
- dictámenes;
- PR;
- rollback;
- plan de despliegue en sombra.

---

# 23. Estrategia de ramas

Rama madre:

```text
feat/knowledge-v3-redesign
```

Ramas de trabajo:

```text
feat/v3-contracts
feat/v3-multimodal
feat/v3-extractor
feat/v3-entity-resolution
feat/v3-local-engine
feat/v3-temporal-ledger
feat/v3-provider-routing
feat/v3-review-writer
test/v3-benchmarks
test/v3-security
docs/v3-dossier-results
```

La integración se hace mediante merge commits controlados a la rama madre.

Nunca directamente a `main`.

---

# 24. Orden de bloques

1. Auditoría real.
2. Baselines reproducibles.
3. Contratos V3.
4. Dataset común.
5. Normalizador.
6. Extractor.
7. Resolver.
8. Motor.
9. Temporalidad y ledger.
10. Proveedores.
11. Adaptador `relation-candidate/internal-v1`.
12. Aprobación local.
13. Writer firmado.
14. Pruebas separadas.
15. Pruebas conjuntas.
16. Held-out.
17. Seguridad.
18. Rendimiento.
19. Informe.
20. PR sin merge.

---

# 25. Entregables

- arquitectura aprobada;
- contratos;
- mapa de ficheros;
- nueva rama;
- implementación aislada;
- fixtures multimodales;
- benchmark común;
- resultados extractor;
- resultados motor;
- resultados conjuntos;
- matriz local vs externo;
- matriz por modalidad;
- matriz por juego;
- informe de seguridad;
- informe de rendimiento;
- informe de limitaciones;
- dictámenes;
- PR listo;
- ninguna escritura productiva.

---

# 26. Criterio final de éxito

La nueva versión no se considera exitosa porque:

- compile;
- tenga muchos tests;
- obtenga métricas altas en desarrollo;
- Ollama produzca JSON válido;
- NVIDIA responda rápido;
- Neo4j acepte el payload.

Solo se considera exitosa cuando:

1. mejora el extractor en held-out;
2. mejora el motor con inputs gold;
3. mejora la cadena completa;
4. reduce falsos positivos;
5. no destruye hechos correctos;
6. preserva procedencia;
7. preserva temporalidad;
8. ninguna salida externa puede escribir;
9. el writer rechaza planes no autorizados;
10. los tests de mutación pueden poner rojo el sistema;
11. Fable emite `CONFORME`;
12. seguridad emite `CONFORME`;
13. CI está verde;
14. `main` y producción permanecen intactos.

---

# 27. Referencias técnicas

## S9-Knowledge

- PR #106:  
  `https://github.com/pjclavero/S9-Knowledge/pull/106`
- Repositorio:  
  `https://github.com/pjclavero/S9-Knowledge`
- Pipeline de relaciones:  
  `data-engine/app/relations/pipeline.py`
- Contrato:  
  `data-engine/app/relations/contracts.py`
- LLM local:  
  `data-engine/app/relations/local_llm_shadow.py`
- Multimedia:  
  `data-engine/app/media/multimedia_contract.py`
- Procesamiento externo:  
  `data-engine/app/external_processing/`
- Extractor actual:  
  `data-engine/app/review/extractor.py`
- Writer:  
  `data-engine/app/review/approved_writer.py`

## Referencias externas

- Graphiti:  
  `https://github.com/getzep/graphiti`
- Documentación Graphiti:  
  `https://help.getzep.com/graphiti/getting-started/overview`
- TrustGraph:  
  `https://github.com/trustgraph-ai/trustgraph`
- Documentación TrustGraph:  
  `https://docs.trustgraph.ai/`
- Neo4j LLM Graph Builder:  
  `https://github.com/neo4j-labs/llm-graph-builder`
- LlamaIndex Property Graph:  
  `https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/`
