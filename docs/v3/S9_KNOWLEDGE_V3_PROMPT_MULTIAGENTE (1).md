# PROMPT MAESTRO DE IMPLEMENTACIÓN
## S9-Knowledge V3 — extractor multimodal y motor local de conocimiento

Actúa como un equipo multiagente senior encargado de implementar el rediseño V3 descrito en el dosier técnico:

```text
docs/S9_KNOWLEDGE_V3_DOSIER_REDISENO_INTEGRAL.md
```

Repositorio:

```text
https://github.com/pjclavero/S9-Knowledge
```

Informe de partida:

```text
https://github.com/pjclavero/S9-Knowledge/pull/106
```

---

# 1. Objetivo

Crear una nueva versión aislada del sistema que procese:

- PDF nativo;
- PDF escaneado;
- fotos;
- texto manuscrito;
- dibujos;
- mapas;
- diagramas;
- tablas;
- audio;
- vídeo;
- YouTube;
- texto;
- Markdown;
- web;
- notas.

La cadena debe ser:

```text
fuente
→ normalización multimodal
→ episodios/evidencias
→ extractor
→ resolución de identidad
→ motor local
→ ledger temporal
→ validación local
→ GraphMutationPlan
→ writer controlado
→ Neo4j
```

Durante este programa:

- no escribir en Neo4j productivo;
- no desplegar;
- no tocar `main`;
- no borrar V1/V2;
- no bajar gates;
- no usar dev como test;
- no modificar ground truth para mejorar métricas.

---

# 2. Autoridad obligatoria

Esta regla no admite interpretación:

> Solo el motor local de S9-Knowledge puede validar, aprobar, invalidar, cerrar vigencias y autorizar una escritura.

Ollama:

- propone;
- razona;
- clasifica;
- ayuda a validar;
- no escribe por sí solo.

NVIDIA y cualquier proveedor externo:

- aportan potencia;
- alivian carga;
- pueden ejecutar OCR, ASR, visión, embeddings o extracción;
- solo producen propuestas;
- no aprueban;
- no rechazan definitivamente;
- no escriben;
- no generan un plan autorizado.

El writer solo acepta un `GraphMutationPlan` firmado por el motor local.

Crear tests que demuestren esta propiedad mediante mutaciones.

---

# 3. Organización

## Fable

Fable es:

- organizador;
- supervisor;
- propietario del tablero;
- controlador de dependencias;
- garante de independencia;
- supervisor de calidad;
- supervisor de seguridad;
- responsable del dictamen final.

Fable no debe implementar bloques normales.

## Opus

Asignar agentes Opus a:

1. auditoría y contratos;
2. multimodal;
3. extractor;
4. resolución;
5. motor;
6. temporalidad/ledger;
7. proveedores;
8. writer;
9. benchmark.

## Sonnet

Asignar Sonnet a:

- tests;
- cobertura;
- fixtures;
- seguridad;
- fuzzing;
- mutation testing;
- revisión de dependencias;
- análisis de métricas;
- documentación.

Ningún agente aprueba su propio trabajo.

---

# 4. Rama y worktrees

Actualizar `main`, registrar el SHA y crear:

```text
feat/knowledge-v3-redesign
```

Crear worktrees o ramas:

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

Definir propiedad exclusiva de carpetas.

No permitir que dos agentes editen el mismo fichero sin coordinación de Fable.

---

# 5. Auditoría previa obligatoria

Antes de implementar:

- leer PR #106;
- reproducir sus métricas;
- inspeccionar la ruta real de ingesta;
- identificar escrituras directas;
- identificar contratos;
- verificar Ollama;
- verificar NVIDIA;
- verificar multimedia;
- verificar review;
- verificar writer;
- verificar benchmarks;
- verificar producción intacta.

Crear:

```text
docs/v3/00-audit-current-system.md
```

Debe incluir un diagrama real con ficheros y funciones.

Fable debe aprobar la auditoría antes de comenzar.

---

# 6. Contratos

Crear contratos internos versionados para:

- SourceAsset;
- SourceEpisode;
- EvidenceFragment;
- EntityMention;
- ClaimProposal;
- EntityResolution;
- FactAssertion;
- GraphMutationPlan;
- GameProfile.

Mantener intacto:

```text
relation-candidate/internal-v1
```

Crear un adaptador V3 → internal-v1.

Los contratos deben:

- rechazar campos desconocidos cuando proceda;
- ser deterministas;
- incluir workspace;
- incluir version;
- incluir source hash;
- incluir provider trace;
- serializarse de forma estable;
- tener tests de roundtrip;
- tener tests de mutación.

Congelar contratos antes de paralelizar la implementación.

---

# 7. Implementación por subsistemas

## Multimodal

Reutilizar:

- `media/multimedia_contract.py`;
- `media/`;
- `audio/`;
- `youtube/`;
- `external_processing/`.

Añadir adaptadores para:

- PDF;
- OCR;
- HTR;
- imagen;
- dibujo;
- tabla;
- audio;
- vídeo.

Mantener OCR literal separado de interpretación visual.

## Extractor

Implementar extractores:

- determinista;
- Ollama;
- externo;
- visual;
- tabla;
- temporal;
- correferencia.

Salida: propuestas, nunca grafo.

## Resolver

Resolver identidades con:

- exact;
- alias;
- glosario;
- embeddings;
- contexto;
- tipos;
- historial;
- workspace.

Permitir entidades provisionales.

## Motor

Implementar:

- existencia;
- predicado;
- dirección;
- negación;
- epistemicidad;
- temporalidad;
- contradicción;
- decisión;
- aprobación local.

## Ledger

Implementar:

- FactAssertion;
- valid_from;
- valid_to;
- recorded_at;
- supersession;
- confirmación;
- contradicción;
- snapshot;
- rollback.

## Proveedores

Reutilizar:

- dispatcher;
- capabilities;
- result validator;
- NVIDIA provider;
- OpenAI-compatible.

Ollama será proveedor local principal.

Ningún proveedor tiene permiso de escribir.

## Writer

Modificar o envolver el writer para exigir:

- plan local;
- hash;
- versión;
- workspace;
- firma/decision hash;
- idempotencia.

---

# 8. Pruebas

Crear un dataset común con:

```text
fuente
episodios gold
evidencia gold
menciones gold
entidades gold
claims gold
assertions gold
mutation plan gold
```

## Pruebas separadas

1. normalizador;
2. extractor;
3. motor;
4. ledger;
5. writer.

## Pruebas conjuntas

1. normalizador + extractor;
2. extractor + motor;
3. motor + ledger;
4. cadena completa;
5. cadena completa con externo;
6. cadena completa sin externo;
7. cadena completa sin Ollama;
8. proveedor corrupto;
9. workspace incorrecto;
10. plan no firmado.

## Ablaciones

- gold entities → motor;
- real entities → motor;
- gold claims → motor;
- local only;
- external only;
- local + external;
- sin glosario;
- con glosario;
- generic profile;
- perfil incorrecto.

---

# 9. Held-out

El equipo que implementa no puede ver el held-out.

Un equipo independiente lo prepara con doble pase.

Debe incluir:

- distintos juegos;
- distintas fuentes;
- distintas modalidades;
- frases no presentes en prompts;
- casos negativos;
- temporalidad;
- cambios históricos;
- correferencia;
- simétricas;
- errores OCR/ASR.

Fable custodia el held-out y solo publica métricas.

---

# 10. Seguridad

Sonnet de seguridad debe comprobar:

- prompt injection;
- secretos;
- rutas privadas;
- workspace crossover;
- source hash mismatch;
- offsets falsos;
- fragment IDs inventados;
- JSON inválido;
- proveedor caído;
- circuit breaker;
- timeouts;
- input gigante;
- combinatorial explosion;
- graph mutation sin firma;
- firma externa;
- replay;
- mutación parcial;
- rollback.

Ejecutar mutation testing.

Un test verde solo cuenta si la mutación correspondiente lo pone rojo.

---

# 11. Gates de bloque

Cada bloque requiere:

1. Editor Opus;
2. Revisor Opus independiente;
3. Sonnet tests;
4. Sonnet seguridad cuando aplique;
5. Fable.

Dictámenes:

```text
CONFORME
CONFORME CON OBSERVACIONES NO BLOQUEANTES
NO CONFORME
```

No comenzar un bloque dependiente si existe `NO CONFORME`.

---

# 12. Paralelización

Después de congelar contratos:

- multimodal;
- extractor;
- resolver;
- motor;
- ledger;
- proveedores;
- benchmarks;

pueden trabajar en paralelo.

Integración, writer y extremo a extremo esperan contratos estables.

---

# 13. Métricas

## Normalizador

- CER;
- WER;
- cobertura;
- truncado;
- repetición;
- bbox;
- timecode;
- páginas.

## Extractor

- mention P/R/F1;
- type accuracy;
- coreference F1;
- entity linking;
- claim P/R/F1;
- false candidates.

## Motor

- predicate;
- direction;
- temporal;
- epistemic;
- negation P/R;
- evidence;
- decision;
- false approve;
- false reject;
- abstention.

## Extremo a extremo

- fact P/R/F1;
- duplicate node rate;
- false mutation plan;
- provenance completeness;
- identity accuracy;
- latency;
- RAM;
- calls;
- external cost.

---

# 14. Informe final

Crear:

```text
docs/v3/S9_KNOWLEDGE_V3_RESULTS.md
```

Debe incluir:

- base SHA;
- rama;
- commits;
- agentes;
- modelos;
- versiones;
- arquitectura;
- archivos;
- tests;
- mutations;
- métricas por subsistema;
- métricas conjuntas;
- held-out;
- seguridad;
- rendimiento;
- limitaciones;
- rollback;
- dictamen de cada revisor;
- dictamen de Fable.

Tabla mínima:

| Métrica | V1 | V2 | V3 dev | V3 held-out | V3 real |
|---|---:|---:|---:|---:|---:|

No ocultar regresiones.

---

# 15. Entrega

Preparar un PR:

```text
feat: knowledge v3 multimodal extraction and local-authority engine
```

No hacer merge.

Entregar:

1. enlace al PR;
2. rama;
3. commits;
4. ficheros;
5. tests;
6. métricas;
7. seguridad;
8. rendimiento;
9. limitaciones;
10. dictamen Fable.

La tarea termina únicamente con `CONFORME` de Fable y seguridad, CI verde y producción intacta.
