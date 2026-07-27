# S9 Knowledge — Informe consolidado V2 para mejorar el motor

**Fecha:** 26 de julio de 2026  
**Base:** comparación entre el informe técnico inicial de S9 Knowledge y el informe complementario aportado posteriormente.  
**Proyectos de referencia:**

- Graphiti
- TrustGraph
- Neo4j LLM Graph Builder

---

# 1. Propósito

Este documento consolida las dos propuestas anteriores y selecciona únicamente las ideas que pueden mejorar realmente S9 Knowledge sin:

- sustituir el motor actual;
- debilitar el diseño fail-closed;
- permitir escrituras directas desde modelos;
- romper el contrato `RelationCandidate/internal-v1`;
- introducir infraestructura desproporcionada;
- añadir complejidad sin beneficio medible;
- comprometer la separación por workspace;
- perder evidencia, procedencia o historial.

El objetivo no es copiar tres proyectos externos, sino adaptar sus mejores patrones al motor existente.

---

# 2. Dictamen ejecutivo

Sí, S9 Knowledge puede mejorar significativamente tomando como referencia:

```text
Graphiti
→ episodios
→ hechos temporales
→ invalidación sin borrado
→ procesamiento incremental
→ resolución temporal separada
→ resúmenes derivados por comunidades

TrustGraph
→ procedencia obligatoria
→ aislamiento estructural
→ flujos versionados
→ paquetes de conocimiento versionados
→ snapshots y rollback

Neo4j LLM Graph Builder
→ puertos y adaptadores de proveedores
→ selección de modelos
→ medición de consumo
→ visualización por fuente
→ ontologías configurables y compiladas
```

La arquitectura recomendada es:

> **S9 Knowledge conserva la autoridad, los contratos, la validación, la revisión y la escritura. Los patrones externos amplían la temporalidad, la trazabilidad, la modularidad y la operación.**

No se recomienda:

- convertir Graphiti en el escritor del grafo;
- desplegar TrustGraph completo;
- introducir Apache Pulsar;
- permitir ontologías modificables directamente en producción;
- mezclar claves y configuración persistente;
- asumir ahorros de rendimiento no medidos;
- ejecutar extracción masiva combinada antes de resolver el anclaje de evidencia.

---

# 3. Comparación de los dos informes

## 3.1. Coincidencias

Ambos informes coinciden en que deben adoptarse:

1. `Episode` como unidad inmutable de entrada.
2. `valid_from / valid_to`.
3. invalidación o cierre de hechos sin borrado.
4. resolución temporal como etapa independiente.
5. procesamiento incremental.
6. procedencia obligatoria.
7. aislamiento estructural por workspace.
8. flujos versionados.
9. snapshots y rollback.
10. abstracción de proveedores.
11. medición de consumo.
12. visualización por fuente.
13. ontologías configurables.

Estas ideas se consideran aceptadas.

---

## 3.2. Aportaciones útiles del informe complementario

El informe complementario añade varias ideas que conviene incorporar.

### A. Tercera capa de comunidades y resúmenes

Graphiti organiza su información conceptualmente en:

```text
Episodios
→ hechos y entidades
→ comunidades y resúmenes
```

Esto puede mejorar las consultas globales y la navegación por:

- facciones;
- arcos narrativos;
- grupos de personajes;
- conflictos;
- zonas geográficas;
- capítulos;
- periodos de campaña.

No debe utilizarse como fuente de verdad. Será una capa derivada y regenerable.

### B. Procesamiento combinado de nodos y relaciones

La extracción conjunta puede reducir llamadas y evitar incoherencias entre dos pasos separados.

Sin embargo, en S9 debe ser:

- opcional;
- limitada por lote;
- en modo sombra al principio;
- sometida a benchmark;
- posterior al anclaje de evidencia;
- incapaz de escribir.

### C. Paquetes de contexto versionados

El concepto `Context Core` de TrustGraph es útil si se adapta a un paquete propio:

```text
KnowledgeBundle
```

Este paquete puede agrupar:

- fuentes;
- episodios;
- ontología;
- versión del flujo;
- políticas;
- manifiesto de assertions;
- snapshot;
- configuración de recuperación;
- hashes;
- métricas de QA.

Resulta útil para:

- releases;
- exportación;
- importación;
- laboratorio;
- comparación;
- rollback;
- traslado entre entornos.

### D. Inyección de dependencias

La arquitectura limpia y la reducción de parámetros de Neo4j LLM Graph Builder son aplicables.

S9 debería separar:

```text
Dominio
Puertos
Adaptadores
Configuración
Orquestación
```

El motor no debería conocer detalles de NVIDIA, Ollama, Parakeet, Whisper u otros proveedores.

### E. Jerarquía documental explícita

El informe complementario detalla:

```text
Documento
→ página
→ fragmento
→ evidencia
→ afirmación
```

Debe ampliarse para multimodalidad:

```text
Audio
→ intervalo temporal
→ intervención
→ evidencia
→ afirmación

Imagen
→ región o bounding box
→ bloque visual
→ evidencia
→ afirmación
```

### F. Índices temporales y por workspace

Es correcta la recomendación de optimizar consultas temporales y aisladas, aunque debe adaptarse a las capacidades reales de Neo4j y medirse antes de crear índices innecesarios.

---

## 3.3. Ideas corregidas o rechazadas

### A. “Estado actual probablemente…”

El informe complementario formula algunos problemas como supuestos:

```text
probablemente se sobrescriben hechos
probablemente no existe procedencia
probablemente hay dependencia de un proveedor
```

Estas suposiciones no se deben conservar como diagnóstico.

S9 ya tiene:

- procedencia mínima;
- workspace obligatorio;
- pipeline dry-run;
- contratos cerrados;
- proveedor externo abstracto en parte;
- temporalidad y estado epistémico;
- separación de revisión y escritura.

La nueva versión se basa en el código conocido, no en hipótesis genéricas.

### B. Ahorro aproximado del 70 %

No existe todavía evidencia suficiente para afirmar una reducción de tiempo del 70 %.

Debe sustituirse por:

```text
objetivo: medir reducción de llamadas, CPU, latencia y reprocesamiento
```

Solo un benchmark real puede establecer el porcentaje.

### C. Apache Pulsar

La arquitectura event-driven de TrustGraph es una referencia, pero introducir Pulsar en S9 sería desproporcionado.

Se mantendrán:

- jobs existentes;
- colas actuales;
- Docker;
- checkpoints;
- workers desacoplados.

Podrá revisarse otra infraestructura únicamente si la carga real la justifica.

### D. Namespace independiente como única solución

Separar físicamente cada workspace puede ser útil en casos sensibles, pero no debe imponerse siempre.

Se propone un modelo por niveles de aislamiento.

### E. `Entity.summary` mutable

No se recomienda guardar un resumen mutable como verdad dentro de `Entity`.

Los resúmenes serán objetos derivados y versionados:

```text
EntitySynopsis
CommunitySummary
```

Si cambian, se regeneran sin modificar los hechos.

### F. Extracción múltiple en un único prompt como regla general

Puede reducir llamadas, pero aumenta:

- contaminación cruzada;
- pérdida de procedencia;
- errores de asignación entre episodios;
- respuestas demasiado largas;
- riesgo de truncamiento.

Será una optimización controlada, no el camino base.

---

# 4. Invariantes de S9 Knowledge

Las mejoras deben respetar permanentemente:

```text
1. Los modelos externos no escriben.
2. Los modelos externos no aprueban.
3. El pipeline de relaciones sigue siendo dry-run.
4. Toda evidencia se valida localmente.
5. Los offsets se calculan o verifican localmente.
6. Toda salida externa es no confiable.
7. Toda afirmación tiene workspace.
8. Toda afirmación tiene procedencia.
9. Una ontología activa es inmutable.
10. Una relación histórica no se borra.
11. Una operación destructiva exige snapshot probado.
12. La reducción de revisión requiere benchmark.
13. La caché nunca cruza workspaces.
14. Los secretos no se guardan en la base de configuración.
15. Producción no se modifica sin autorización explícita.
```

---

# 5. Arquitectura objetivo consolidada

La arquitectura se divide en cuatro capas.

## 5.1. Capa 1 — Entradas inmutables

```text
Source
→ Episode
→ Segment / Region / Utterance
→ Evidence
```

Contiene la fuente original y sus localizadores.

## 5.2. Capa 2 — Libro mayor de afirmaciones

```text
Assertion Ledger
```

Conserva todas las afirmaciones:

- vigentes;
- históricas;
- propuestas;
- disputadas;
- contradichas;
- retractadas;
- sustituidas.

Es la fuente de verdad auditable.

## 5.3. Capa 3 — Vista materializada

Mantiene relaciones directas eficientes:

```text
(Entity)-[:ALLY_OF]->(Entity)
```

Se genera desde las afirmaciones aprobadas y vigentes.

No es la única fuente de verdad.

## 5.4. Capa 4 — Conocimiento derivado

```text
EntitySynopsis
Community
CommunitySummary
CampaignSummary
FactionSummary
```

Características:

- regenerable;
- versionado;
- no autoritativo;
- enlazado a assertions;
- útil para navegación y RAG;
- nunca sustituye la evidencia.

---

# 6. Contratos nuevos

No se modifica `RelationCandidate/internal-v1`.

Se añaden contratos adyacentes.

---

## 6.1. `EpisodeRecord`

```python
@dataclass(frozen=True)
class EpisodeRecord:
    episode_id: str
    workspace: str
    collection_id: str
    source_id: str
    source_kind: str
    content_hash: str
    reference_time: str | None
    ingested_at: str
    session_candidate_id: str | None
    source_locator: dict
    metadata: dict
    schema_version: str = "episode-record/1.0"
```

Puede representar:

- documento;
- capítulo;
- audio;
- bloque de audio;
- imagen;
- notas;
- transcripción;
- resumen;
- corrección;
- entrada incremental.

No equivale obligatoriamente a una sesión.

---

## 6.2. `EvidenceRecord`

```python
@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    episode_id: str
    source_id: str
    segment_id: str
    locator_type: str
    page: int | None
    char_start: int | None
    char_end: int | None
    timestamp_start_ms: int | None
    timestamp_end_ms: int | None
    bbox: tuple[float, float, float, float] | None
    literal_text: str
    literal_hash: str
    evidence_role: str
```

`locator_type`:

```text
TEXT_RANGE
PAGE_RANGE
AUDIO_INTERVAL
IMAGE_REGION
VIDEO_INTERVAL
STRUCTURED_FIELD
```

`evidence_role`:

```text
SUPPORTS
CONTRADICTS
QUALIFIES
RETRACTS
PROVIDES_CONTEXT
```

---

## 6.3. `ProvenanceStamp`

```python
@dataclass(frozen=True)
class ProvenanceStamp:
    provenance_id: str
    workspace: str
    collection_id: str
    episode_id: str
    source_id: str
    evidence_id: str
    input_hash: str
    extractor_component: str
    extractor_version: str
    provider_id: str | None
    model_id: str | None
    prompt_suite: str | None
    ontology_version: str
    pipeline_version: str
    flow_run_id: str
    created_at: str
```

Todo candidato que avance debe tener uno.

---

## 6.4. `CandidateEnvelope`

```python
@dataclass(frozen=True)
class CandidateEnvelope:
    envelope_id: str
    candidate: RelationCandidate
    provenance: ProvenanceStamp
    evidence: tuple[EvidenceRecord, ...]
    flow_run_id: str
    schema_version: str = "candidate-envelope/1.0"
```

Ventaja:

- se conserva el contrato actual;
- se añade contexto sin romperlo;
- se pueden versionar las capas por separado.

---

## 6.5. `TemporalAssertion`

```python
@dataclass(frozen=True)
class TemporalAssertion:
    assertion_id: str
    candidate_id: str
    valid_from: str | None
    valid_to: str | None
    temporal_precision: str
    temporal_mode: str
    discovered_at: str | None
    discovered_in_session: str | None
    recorded_at: str
    resolver_version: str
    confidence: float
    unresolved_expressions: tuple[str, ...]
```

Distingue:

```text
cuándo fue cierto
cuándo se descubrió
cuándo se registró
```

---

## 6.6. `SupersessionPlan`

```python
@dataclass(frozen=True)
class SupersessionAction:
    action: str
    target_assertion_id: str | None
    new_assertion_id: str | None
    effective_at: str | None
    reason: str
    evidence_ids: tuple[str, ...]

@dataclass(frozen=True)
class SupersessionPlan:
    plan_id: str
    workspace: str
    actions: tuple[SupersessionAction, ...]
    status: str
    flow_run_id: str
    requires_review: bool
```

Acciones permitidas:

```text
ATTACH_SUPPORTING_EVIDENCE
CREATE_ASSERTION
CLOSE_VALIDITY_INTERVAL
MARK_HISTORICAL
MARK_DISPUTED
MARK_CONTRADICTED
MARK_RETRACTED
SUPERSEDE_ASSERTION
NO_CHANGE
REVIEW_REQUIRED
```

El plan nunca escribe por sí mismo.

---

## 6.7. `FlowDefinition`

```python
@dataclass(frozen=True)
class FlowDefinition:
    flow_id: str
    version: str
    segmenter_version: str
    classifier_version: str
    extractor_policy: str
    evidence_anchor_version: str
    predicate_vocabulary_version: str
    ontology_version: str
    temporality_version: str
    epistemic_version: str
    ensemble_version: str
    provider_policy_version: str
    decision_policy_version: str
    limits: dict
    manifest_hash: str
```

---

## 6.8. `FlowRun`

```python
@dataclass(frozen=True)
class FlowRun:
    flow_run_id: str
    flow_id: str
    flow_version: str
    workspace: str
    collection_id: str
    episode_ids: tuple[str, ...]
    input_hash: str
    status: str
    started_at: str
    completed_at: str | None
    result_hash: str | None
    checkpoint_ids: tuple[str, ...]
```

---

## 6.9. `ProviderSpec` y `ModelSpec`

```python
@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    adapter_type: str
    endpoint: str
    capabilities: frozenset[str]
    secret_ref: str | None
    timeout_seconds: int
    max_retries: int
    max_concurrency: int
    enabled: bool

@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    provider_id: str
    capabilities: frozenset[str]
    input_modalities: frozenset[str]
    output_contract: str
    context_limit: int | None
    enabled: bool
```

---

## 6.10. `UsageEvent`

```python
@dataclass(frozen=True)
class UsageEvent:
    usage_id: str
    request_id: str
    flow_run_id: str
    principal_id: str | None
    workspace: str
    provider_id: str
    model_id: str
    capability: str
    input_tokens: int | None
    output_tokens: int | None
    audio_seconds: float | None
    image_count: int | None
    page_count: int | None
    latency_ms: int
    retries: int
    cache_hit: bool
    status: str
    error_class: str | None
    estimated_cost: float | None
    created_at: str
```

---

## 6.11. `OntologyVersion`

```python
@dataclass(frozen=True)
class OntologyVersion:
    ontology_id: str
    version: str
    workspace_scope: str | None
    entity_types: tuple[str, ...]
    predicates: tuple[str, ...]
    compatibility_rules: tuple[dict, ...]
    inverse_rules: tuple[dict, ...]
    symmetric_predicates: tuple[str, ...]
    temporal_rules: tuple[dict, ...]
    status: str
    manifest_hash: str
```

Estados:

```text
DRAFT
VALIDATED
ACTIVE
DEPRECATED
RETIRED
```

---

## 6.12. `KnowledgeBundle`

Adaptación del concepto `Context Core`.

```python
@dataclass(frozen=True)
class KnowledgeBundle:
    bundle_id: str
    workspace: str
    collection_id: str
    version: str
    source_manifest_hash: str
    episode_manifest_hash: str
    assertion_manifest_hash: str
    ontology_version: str
    flow_versions: tuple[str, ...]
    retrieval_policy_version: str | None
    snapshot_id: str
    qa_report_hash: str
    created_at: str
    status: str
```

Estados:

```text
DRAFT
VALIDATED
RELEASE_CANDIDATE
RELEASED
RETIRED
```

No contiene secretos.

---

## 6.13. `EntitySynopsis` y `CommunitySummary`

```python
@dataclass(frozen=True)
class EntitySynopsis:
    synopsis_id: str
    entity_id: str
    assertion_ids: tuple[str, ...]
    flow_version: str
    generated_at: str
    text: str
    status: str

@dataclass(frozen=True)
class CommunitySummary:
    summary_id: str
    community_id: str
    member_ids: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    flow_version: str
    generated_at: str
    text: str
    status: str
```

Son derivados y pueden regenerarse.

---

# 7. Pipeline consolidado

```text
Source detection
→ Episode creation
→ segmentation
→ relevance classification
→ structural extraction
→ CandidateEnvelope
→ EvidenceAnchor
→ ontology validation
→ temporal resolution
→ epistemic resolution
→ deduplication
→ conflict resolution
→ SupersessionPlan
→ policy decision
→ approved writer output
→ explicit apply gate
→ Assertion Ledger
→ materialized current graph
→ derived summaries and communities
```

---

## 7.1. Separación de etapas

El pipeline actual debe ampliarse sin convertir cada etapa en un servicio independiente.

Módulos propuestos:

```text
relations/evidence_anchor.py
relations/temporal_resolver.py
relations/conflict_resolver.py
relations/supersession.py
relations/provenance.py
relations/episodes.py
relations/flows.py
relations/usage.py
relations/ontology_registry.py
```

La separación aporta:

- pruebas independientes;
- errores localizables;
- versiones por componente;
- posibilidad de A/B;
- menor dependencia del LLM.

---

# 8. Procesamiento combinado y por lotes

Esta idea se incorpora con limitaciones estrictas.

## 8.1. Cuándo puede usarse

- mismo workspace;
- misma colección;
- mismo idioma;
- mismo tipo de fuente;
- episodios pequeños;
- límite estricto de tokens;
- respuesta estructurada por `episode_id`;
- procedencia preservada;
- ninguna escritura;
- benchmark previo.

## 8.2. Cuándo no debe usarse

- workspaces distintos;
- campañas distintas;
- audio con varios hablantes sin diarización;
- fuentes conflictivas de gran tamaño;
- episodios con diferente ontología;
- contenido privado mezclado;
- inputs próximos al límite de contexto.

## 8.3. Estrategia

```text
Camino base:
1 episodio → 1 extracción

Optimización:
N episodios compatibles → 1 lote limitado
```

Cada resultado debe incluir:

```text
episode_id
source_segment
evidence_text
candidate
```

Si falta la asociación inequívoca:

```text
descartar lote
→ reintentar por episodio
```

## 8.4. Benchmark obligatorio

Comparar:

- precisión;
- recall;
- predicado;
- offsets;
- contaminación cruzada;
- latencia;
- tokens;
- candidatos inválidos;
- coste;
- revisión humana.

No activar por defecto hasta demostrar mejora.

---

# 9. Comunidades y resúmenes derivados

## 9.1. Objetivo

Proporcionar vistas de alto nivel:

- principales facciones;
- relaciones políticas;
- arcos narrativos;
- grupos de personajes;
- eventos centrales;
- cambios entre sesiones;
- conflictos activos.

## 9.2. Fuente

Solo se construyen desde:

- assertions aprobadas;
- estado temporal seleccionado;
- workspace y colección explícitos;
- ontología activa;
- FlowDefinition versionado.

## 9.3. No son verdad primaria

Nunca deben:

- crear assertions;
- corregir hechos;
- cerrar intervalos;
- sustituir evidencia;
- activar escritura.

## 9.4. Recalculado

Se regeneran cuando:

- cambia una assertion relevante;
- cambia la ontología;
- se retira una fuente;
- cambia la ventana temporal;
- se publica un nuevo KnowledgeBundle.

---

# 10. Procedencia consolidada

La cadena recomendada es:

```text
Workspace
→ Collection
→ Source
→ Episode
→ Segment / Utterance / Region
→ Evidence
→ CandidateEnvelope
→ Assertion
→ Materialized Relationship
→ Derived Summary
```

Cada salto debe ser navegable.

## 10.1. Texto

```text
Documento
→ página
→ fragmento
→ rango de caracteres
→ evidencia literal
```

## 10.2. Audio

```text
Archivo de audio
→ bloque
→ hablante
→ intervalo temporal
→ transcripción original
→ transcripción corregida
→ evidencia
```

## 10.3. Imagen

```text
Imagen
→ región
→ bounding box
→ bloque textual o visual
→ relación visual
→ evidencia
```

## 10.4. Correcciones

Debe conservarse:

```text
salida original
salida corregida
componente que corrigió
motivo
fecha
hash
```

---

# 11. Aislamiento por workspace

Se propone un modelo de tres niveles.

## Nivel 1 — Lógico reforzado

Para la mayoría de workspaces:

- `WorkspaceContext` firmado por servidor;
- queries obligatoriamente scoped;
- IDs incluyen workspace;
- caché particionada;
- colas particionadas;
- rutas temporales separadas;
- métricas separadas.

## Nivel 2 — Almacenamiento separado

Para campañas o clientes sensibles:

- base auxiliar separada;
- colección vectorial separada;
- bucket o ruta separada;
- credenciales de servicio distintas.

## Nivel 3 — Instancia independiente

Para aislamiento máximo:

- Neo4j independiente;
- worker independiente;
- secretos independientes;
- red independiente.

No debe imponerse el nivel 3 a todos los usuarios.

---

# 12. Puertos, adaptadores e inyección de dependencias

## 12.1. Puertos del dominio

```text
RelationExtractionPort
CandidateReviewPort
ASRPort
DiarizationPort
VisionPort
OCRPort
EmbeddingPort
UsageSink
EpisodeStore
AssertionStore
SnapshotStore
```

## 12.2. Adaptadores

```text
NvidiaTextAdapter
OllamaTextAdapter
NvidiaASRAdapter
FasterWhisperAdapter
Neo4jAssertionAdapter
SqliteReviewAdapter
FilesystemSnapshotAdapter
```

## 12.3. Composición

La creación de objetos se realiza en un composition root:

```text
configuración
→ factories
→ adapters
→ pipeline
```

El dominio no importa SDK específicos.

## 12.4. Beneficios

- tests con adaptadores falsos;
- proveedores intercambiables;
- menos condicionales;
- menos parámetros repetidos;
- menor vendor lock-in;
- módulos más pequeños;
- mejor control de errores.

---

# 13. Ontología compilada y versionada

La configuración no se aplica directamente.

Flujo:

```text
DRAFT
→ validación de esquema
→ normalización
→ compilación a JSON Schema/Pydantic
→ tests de compatibilidad
→ corpus de regresión
→ Supervisor
→ ACTIVE
```

## 13.1. Capas

```text
RPG Core
→ Character
→ Location
→ Faction
→ Event
→ Object

Extensión Leyenda
→ Clan
→ School
→ Family
→ Title

Extensión Trudvang
→ tipos y relaciones propias
```

## 13.2. Activación

Una versión activa es inmutable.

Para cambiarla:

```text
crear nueva versión
→ validar
→ migración planificada
→ activar
```

## 13.3. Predicados desconocidos

```text
predicado no permitido
→ fallback seguro
→ REVIEW_REQUIRED
```

Nunca se crea automáticamente un tipo nuevo.

---

# 14. Modelo Neo4j recomendado

## 14.1. Nodos

```text
(:Workspace)
(:Collection)
(:Session)
(:Source)
(:Episode)
(:Segment)
(:Evidence)
(:Entity)
(:Assertion)
(:FlowDefinition)
(:FlowRun)
(:OntologyVersion)
(:KnowledgeBundle)
(:Snapshot)
(:Community)
(:EntitySynopsis)
(:CommunitySummary)
```

## 14.2. Relaciones

```text
(Workspace)-[:HAS_COLLECTION]->(Collection)
(Collection)-[:HAS_SESSION]->(Session)
(Collection)-[:HAS_SOURCE]->(Source)
(Source)-[:HAS_EPISODE]->(Episode)
(Session)-[:INCLUDES_EPISODE]->(Episode)

(Episode)-[:HAS_SEGMENT]->(Segment)
(Segment)-[:CONTAINS_EVIDENCE]->(Evidence)

(Evidence)-[:SUPPORTS]->(Assertion)
(Evidence)-[:CONTRADICTS]->(Assertion)
(Evidence)-[:QUALIFIES]->(Assertion)
(Evidence)-[:RETRACTS]->(Assertion)

(Assertion)-[:SUBJECT]->(Entity)
(Assertion)-[:OBJECT]->(Entity)
(Assertion)-[:SUPERSEDES]->(Assertion)
(Assertion)-[:CONTRADICTS]->(Assertion)

(FlowDefinition)-[:HAS_RUN]->(FlowRun)
(FlowRun)-[:PROCESSED]->(Episode)
(FlowRun)-[:PRODUCED]->(Assertion)
(FlowRun)-[:USED_ONTOLOGY]->(OntologyVersion)

(KnowledgeBundle)-[:INCLUDES]->(Snapshot)
(KnowledgeBundle)-[:USES_FLOW]->(FlowDefinition)
(KnowledgeBundle)-[:USES_ONTOLOGY]->(OntologyVersion)

(Community)-[:HAS_MEMBER]->(Entity)
(CommunitySummary)-[:SUMMARIZES]->(Community)
(EntitySynopsis)-[:SUMMARIZES]->(Entity)
```

---

# 15. Restricciones e índices

Antes de aplicar deben probarse con el volumen real.

## 15.1. Unicidad

```text
Workspace.workspace_id
Collection(workspace, collection_id)
Source(workspace, source_id)
Episode(workspace, episode_id)
Evidence(workspace, evidence_id)
Entity(workspace, entity_id)
Assertion(workspace, assertion_id)
FlowRun(workspace, flow_run_id)
```

## 15.2. Búsquedas

Índices candidatos:

```text
Assertion(workspace, subject_id, predicate, object_id)
Assertion(workspace, valid_from)
Assertion(workspace, valid_to)
Episode(workspace, reference_time)
Episode(workspace, ingested_at)
Evidence(workspace, source_id)
Session(workspace, session_number)
```

## 15.3. Regla

No crear todos los índices preventivamente.

Proceso:

```text
consulta real
→ PROFILE
→ identificar cuello
→ crear índice
→ medir
```

---

# 16. Snapshots, KnowledgeBundle y rollback

## 16.1. Snapshot

Debe incluir:

- dump de Neo4j;
- hash;
- conteos;
- bases auxiliares;
- manifiesto de fuentes;
- FlowDefinitions;
- ontologías;
- assertions;
- configuración no secreta;
- resultado del restore drill.

## 16.2. KnowledgeBundle

El bundle referencia un snapshot validado y añade:

- versión funcional;
- políticas;
- informes QA;
- manifiestos;
- estado de release.

## 16.3. Rollback completo

Para:

- migración;
- limpieza;
- corrupción;
- release defectuosa.

## 16.4. Reversión lógica

Para un conjunto pequeño de operaciones:

- ledger de acciones;
- plan inverso creado antes del apply;
- transacción;
- verificación posterior.

## 16.5. Gate

```text
Sin snapshot
→ no apply

Snapshot no restaurado
→ no operación destructiva

Counts o hashes incorrectos
→ bloqueo
```

---

# 17. Mejoras sobre módulos actuales

| Módulo actual | Mejora consolidada | Beneficio |
|---|---|---|
| `relations/contracts.py` | Mantener v1; añadir envelopes | Compatibilidad |
| `relations/pipeline.py` | Episodes, FlowRun, checkpoints | Incremental y reproducible |
| `relations/temporality.py` | Resolver independiente | Intervalos reales |
| `relations/observability.py` | UsageEvent | Consumo y calidad |
| `review/pipeline.py` | Evidence, ontology, temporal, conflict | Etapas claras |
| `review/validator.py` | Procedencia obligatoria | Auditoría |
| `review/resolver.py` | SupersessionPlan | Cambios sin borrado |
| `review/approved_writer.py` | Assertions y Evidence | Salida enriquecida |
| `review/ingest_approved.py` | Único apply gate | Seguridad |
| `review/review_store.py` | Runs y checkpoints | Reanudación |
| `external_ai/base.py` | Puertos por modalidad | Modularidad |
| `external_ai/registry.py` | ProviderSpec y ModelSpec | Selección por capacidad |
| `schemas/rpg_schema.py` | OntologyRegistry | Dominios versionados |
| `viewer` | Fuente, sesión, historia, comunidad | Navegación |
| `jobs` | WorkspaceContext y lotes | Aislamiento |
| limpieza | Snapshot y reversión | Operación segura |

---

# 18. Plan de implementación V2

Cada bloque sigue:

```text
auditoría
→ diseño
→ implementación
→ tests
→ especialista
→ Supervisor
→ PR
→ CI
→ merge
→ CI de main
→ checkpoint
```

---

## BLOQUE 0 — Documentación y ADR

Entregables:

- estado real de `main`;
- ADR Episode;
- ADR Assertion Ledger;
- ADR Provenance;
- ADR Temporal;
- ADR Supersession;
- ADR Provider Ports;
- ADR Ontology;
- ADR KnowledgeBundle;
- mapa de migración.

Sin código productivo ni despliegue.

---

## BLOQUE 1 — EvidenceAnchor

Implementar:

- anclaje literal;
- offsets locales;
- `EvidenceRecord`;
- hashing;
- pruebas de mutación;
- soporte de texto primero.

Gate:

```text
100 % de candidatos que avanzan tienen evidencia literal válida
```

---

## BLOQUE 2 — Procedencia

Implementar:

- `ProvenanceStamp`;
- `CandidateEnvelope`;
- jerarquía Source → Episode → Evidence;
- proveedor, modelo y flow.

Gate:

```text
0 candidatos sin procedencia
0 secretos
```

---

## BLOQUE 3 — EpisodeRecord

Implementar:

- Episode;
- hashes;
- deduplicación;
- idempotencia;
- sesión provisional;
- backfill.

Gate:

- episodio sin sesión permitido;
- misma entrada no se reprocesa;
- workspace aislado.

---

## BLOQUE 4 — FlowDefinition y FlowRun

Implementar:

- manifiestos;
- hashes;
- checkpoints;
- reanudación;
- comparación A/B.

Gate:

```text
mismo input + mismo flow
→ mismo result_hash en caminos deterministas
```

---

## BLOQUE 5 — TemporalAssertion

Implementar:

- `valid_from`;
- `valid_to`;
- precisión;
- tiempo de descubrimiento;
- tiempo de registro;
- expresiones sin resolver.

Gate:

- no inventar fechas;
- flashback;
- time skip;
- backfill;
- sin regresión temporal.

---

## BLOQUE 6 — Assertion Ledger

Implementar en dry-run:

- Assertion;
- múltiples Evidence;
- estados;
- vista actual derivada;
- compatibilidad con relaciones actuales.

Gate:

- ninguna escritura directa;
- assertions deterministas;
- relación actual reproducible.

---

## BLOQUE 7 — SupersessionPlan

Implementar:

- duplicados;
- evidencia adicional;
- cierre de intervalos;
- historical;
- contradicted;
- retracted;
- superseded.

Gate:

```text
0 borrados físicos
0 cambios sin evidencia
```

---

## BLOQUE 8 — WorkspaceContext

Implementar:

- contexto servidor;
- colas;
- caché;
- rutas;
- consultas;
- métricas;
- presupuestos.

Gate:

```text
0 fugas
0 consultas no scoped
0 contaminación de caché
```

---

## BLOQUE 9 — Puertos y adaptadores

Implementar:

- interfaces por capacidad;
- composition root;
- provider/model specs;
- adaptadores falsos;
- compatibilidad NVIDIA/Ollama.

Gate:

- modelos actuales siguen funcionando;
- sin SDKs en dominio;
- sin secretos en salida.

---

## BLOQUE 10 — UsageEvent y presupuestos

Implementar:

- tokens;
- audio;
- imágenes;
- páginas;
- latencia;
- errores;
- cache hits;
- circuit breaker.

Gate:

```text
≥ 99 % de llamadas registradas
```

---

## BLOQUE 11 — OntologyRegistry

Implementar:

- draft;
- compilación;
- JSON Schema/Pydantic;
- tests;
- activación inmutable;
- núcleo y extensiones.

Gate:

- predicados no permitidos fail-closed;
- corpus actual compatible.

---

## BLOQUE 12 — Snapshot y KnowledgeBundle

Implementar:

- SnapshotManifest;
- dumps;
- hashes;
- restore drill;
- KnowledgeBundle;
- exportación controlada.

Gate:

```text
restauración probada
hashes y counts coinciden
```

---

## BLOQUE 13 — Visualización

Implementar vistas:

- por fuente;
- por episodio;
- por sesión;
- por historia;
- por assertion;
- por modelo;
- por ontología;
- por contradicción.

Gate:

- read-only;
- workspace obligatorio;
- enlaces de evidencia correctos.

---

## BLOQUE 14 — Optimización batch

Probar:

- extracción combinada;
- múltiples episodios;
- límites;
- fallback por episodio;
- contaminación cruzada.

Gate:

Solo activar si mejora:

- precisión;
- evidencia;
- latencia;
- consumo;
- revisión.

---

## BLOQUE 15 — Comunidades y resúmenes

Implementar:

- Community;
- EntitySynopsis;
- CommunitySummary;
- regeneración;
- versionado;
- no autoridad.

Gate:

- no crean assertions;
- no alteran el ledger;
- toda frase puede rastrearse a assertions.

---

## BLOQUE 16 — Benchmark global

Comparar:

- motor anterior;
- motor V2;
- corpus B1/B2;
- backfill;
- temporalidad;
- contradicciones;
- evidencia;
- latencia;
- consumo;
- uso de CPU local;
- revisión humana;
- aislamiento;
- rollback.

Sin despliegue automático.

---

# 19. Métricas

## Evidencia

```text
Candidatos que avanzan con EvidenceRecord: 100 %
Offsets válidos: 100 %
Evidencias sin fuente: 0
```

## Procedencia

```text
CandidateEnvelope con ProvenanceStamp: 100 %
Modelo/proveedor/flow desconocido: 0
```

## Temporalidad

```text
Borrados de assertions históricas: 0
Fechas inventadas: 0
Cambios con historial: 100 %
```

## Aislamiento

```text
Fugas entre workspaces: 0
Consultas sin scope: 0
Cache poisoning: 0
```

## Proveedores

```text
Llamadas registradas: ≥ 99 %
Secretos registrados: 0
Capacidad de escritura externa: 0
```

## Reproducibilidad

```text
Mismo input y flow determinista
→ mismo hash
```

## Batch

No se fija un porcentaje previo.

Debe demostrar:

- menor consumo o latencia;
- misma o mayor calidad;
- cero contaminación cruzada crítica.

## Comunidades

```text
Assertions creadas por resúmenes: 0
Resúmenes sin trazabilidad: 0
```

---

# 20. Riesgos y mitigaciones

## Complejidad excesiva

Mitigación:

- contratos pequeños;
- bloques secuenciales;
- no microservicios innecesarios;
- no Pulsar;
- uso de infraestructura actual.

## Doble modelo de datos

Mitigación:

- Assertion Ledger como verdad;
- vista materializada derivada;
- proceso de reconciliación probado.

## Temporalidad incorrecta

Mitigación:

- EvidenceAnchor primero;
- resolver separado;
- precisión explícita;
- no inventar fechas;
- review en casos ambiguos.

## Ontología inestable

Mitigación:

- versiones inmutables;
- compilación;
- tests;
- activación controlada.

## Coste de proveedores

Mitigación:

- UsageEvent;
- presupuestos;
- shadow selectivo;
- cache;
- fallback;
- batch solo si demuestra beneficio.

## Resúmenes que alucinan

Mitigación:

- solo assertions aprobadas;
- trazabilidad;
- no persistencia como hechos;
- regenerables.

---

# 21. Qué mejora exactamente en S9 Knowledge

## Calidad del motor

- mejor evidencia;
- hechos con temporalidad real;
- contradicciones explícitas;
- correcciones sin pérdida;
- varias fuentes por hecho.

## Capacidad incremental

- no reconstruir todo;
- backfill;
- sesiones continuas;
- reanudación;
- deduplicación.

## Seguridad

- workspaces reforzados;
- proveedores sin autoridad;
- snapshots;
- restore probado;
- ontologías controladas.

## Flexibilidad

- NVIDIA;
- Ollama;
- ASR;
- visión;
- OCR;
- modelos futuros;
- políticas por capacidad.

## Observabilidad

- consumo;
- errores;
- latencia;
- calidad;
- procedencia;
- versión exacta del flujo.

## Experiencia de usuario

- ver por sesión;
- ver por historia;
- ver por fuente;
- entender por qué existe una relación;
- corregir una fuente;
- navegar grupos y arcos narrativos.

---

# 22. Orden real recomendado

```text
1. Documentación
2. EvidenceAnchor
3. Procedencia
4. Episode
5. Flow versioning
6. TemporalAssertion
7. Assertion Ledger
8. Supersession
9. Workspace isolation
10. Provider ports
11. Usage
12. Ontology
13. Snapshots y KnowledgeBundle
14. Visualización
15. Batch optimization
16. Comunidades
17. Benchmark y release
```

No debe invertirse este orden.

En particular:

> **No implementar invalidación automática, procesamiento combinado o resúmenes globales antes de resolver evidencia, procedencia y contratos temporales.**

---

# 23. Conclusión

La versión consolidada adopta las mejores ideas de ambos informes y las adapta al motor real de S9 Knowledge.

La combinación final es:

```text
S9 Knowledge
+ Episodes de Graphiti
+ TemporalAssertion
+ Assertion Ledger
+ Supersession sin borrado
+ procedencia de TrustGraph
+ WorkspaceContext
+ FlowDefinition y FlowRun
+ KnowledgeBundle
+ snapshots
+ puertos y adaptadores
+ selección de modelos
+ UsageEvent
+ OntologyRegistry
+ vistas por fuente
+ comunidades derivadas
```

Se mantienen como elementos irrenunciables:

- contratos cerrados;
- dry-run;
- evidencia literal;
- offsets locales;
- estados epistémicos;
- revisión selectiva;
- modelos sin autoridad;
- escritura controlada;
- aislamiento;
- trazabilidad;
- rollback;
- producción protegida.

El resultado no será una copia de Graphiti, TrustGraph o Neo4j LLM Graph Builder.

Será una versión más robusta de S9 Knowledge, especializada en:

- lore;
- campañas vivas;
- sesiones;
- audio;
- imágenes;
- descubrimientos;
- relaciones cambiantes;
- rumores;
- contradicciones;
- automatización con mínimo trabajo del usuario.

---

# 24. Decisiones consolidadas

| Idea | Decisión | Motivo |
|---|---|---|
| Episode | Adoptar | Unidad incremental y trazable |
| valid_from / valid_to | Adoptar | Historia y relaciones vivas |
| Invalidación sin borrado | Adoptar | Conserva historial |
| Resolución temporal separada | Adoptar | Mejor calidad y testabilidad |
| Batch de episodios | Adoptar después de benchmark | Riesgo de contaminación |
| Extracción nodos+relaciones conjunta | Opcional | Optimización, no base |
| Comunidades | Diferir | Capa de consulta, no bloqueo actual |
| Procedencia jerárquica | Adoptar | Evidencia y auditoría |
| Named graph RDF | Adaptar | S9 usa property graph |
| Workspace estructural | Adoptar por niveles | Seguridad proporcional |
| Context Core | Adaptar como KnowledgeBundle | Release, portabilidad y rollback |
| Flujos versionados | Adoptar | Reproducibilidad |
| Snapshots | Adoptar | Operaciones seguras |
| Pulsar | Rechazar ahora | Complejidad desproporcionada |
| Provider factory | Adoptar como ports/adapters | Menor acoplamiento |
| Token tracking | Ampliar a UsageEvent | Audio, imagen y páginas |
| Ontología dinámica | Adaptar con compilación y gates | Evitar cambios inseguros |
| Entity.summary mutable | Rechazar | Debe ser derivado y versionado |
| Ahorro del 70 % | Rechazar como afirmación | Debe medirse |
