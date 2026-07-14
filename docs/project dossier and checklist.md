# DOSIER DE ESTADO, CORRECCIÓN Y EJECUCIÓN  

> Benchmark de transcripción de vídeo (docs/40, 2026-07-15): faster-whisper medium APTA CON REVISIÓN DE SEGMENTOS CONFLICTIVOS (91% auto-aceptable). Para la primera ingesta se recomienda una fuente pequeña ya validada, no una transcripción de vídeo nueva.
## S9 Knowledge

**Repositorio:** `pjclavero/S9-Knowledge`  
**Rama revisada:** `main`  
**Referencia visible:** etiqueta `v0.2.5b`, commit `1fd94b8`  
**Fecha del dosier:** 13 de julio de 2026  
**Función del documento:** guía maestra, hoja de ruta y checklist de cierre del proyecto

---

## 0. Cómo debe utilizarse este dosier

Este documento consolida:

- el objetivo funcional de S9 Knowledge;
- el estado declarado en el repositorio;
- las diferencias entre la documentación antigua y la actual;
- los riesgos que todavía no están cerrados;
- las correcciones documentales necesarias;
- el orden de trabajo recomendado;
- los criterios de aceptación de cada bloque;
- una checklist general para avanzar sin reabrir tareas ya completadas.

Debe utilizarse como documento principal de coordinación. El resto de documentos de `docs/` pueden seguir explicando áreas concretas, pero este dosier debe indicar qué está terminado, qué está parcialmente terminado, qué no está hecho y qué requiere verificación en el servidor.

### Regla de mantenimiento

Cada bloque que se cierre debe actualizar simultáneamente:

- este dosier;
- `docs/02-current-state.md`;
- `ROADMAP.md`;
- `CHANGELOG.md`;
- la documentación específica del componente;
- la etiqueta o versión del repositorio, cuando corresponda.

No se debe marcar una tarea como cerrada únicamente porque exista código. Para considerarla terminada deben existir pruebas, evidencia operativa, documentación y, cuando afecte a datos, un procedimiento de reversión.

---

## 1. Leyenda de estados

| Símbolo | Estado | Significado |
|---|---|---|
| ✅ | Cerrado | Implementado, documentado y con evidencia suficiente en el repositorio |
| 🟢 | Operativo declarado | La documentación afirma que está desplegado u operativo, pero debe verificarse en VM105 |
| 🟡 | Parcial | Existe una base funcional, pero faltan piezas, validación o integración |
| 🟠 | Preparado | Hay diseño, interfaces o módulos, pero no se ha demostrado el flujo completo |
| ❌ | Pendiente | No está implementado |
| ⚠️ | Riesgo | Puede afectar a seguridad, integridad, recuperación o calidad del grafo |
| 🔍 | Verificación requerida | No puede confirmarse únicamente revisando GitHub |

### Distinción obligatoria

En toda la documentación deben separarse cuatro conceptos:

1. **Implementado en el repositorio.**
2. **Probado automáticamente.**
3. **Desplegado en VM105.**
4. **Validado con datos reales y recuperación comprobada.**

Estos cuatro estados no son equivalentes.

---

# 2. Resumen ejecutivo

S9 Knowledge ya dispone de una base técnica considerable. El repositorio muestra:

- un motor de datos orientado a RPG;
- un esquema de entidades y relaciones;
- integración con Neo4j;
- transcripción mediante faster-whisper;
- glosario y normalización determinista;
- pipeline de revisión;
- resolución de entidades contra Neo4j en modo lectura;
- generación de `approved_payload`;
- ingesta aprobada protegida;
- auditoría del grafo;
- exportación e importación de paquetes de conocimiento;
- visor web;
- panel de trabajos;
- panel de revisiones;
- almacenamiento de permisos;
- documentación extensa;
- suites de pruebas en `data-engine` y `viewer`.

El proyecto, por tanto, **no está en una fase inicial**.

Sin embargo, tampoco puede considerarse terminado. Los bloqueos resueltos y pendientes son:

**RESUELTOS (2026-07-13–14):**

1. ✅ Fotografía verificable del estado: commit `cef9233` en VM105, 220/220 tests, CI activa.
2. ✅ Documentación reconciliada: docs/02, 26–33, ROADMAP, CHANGELOG, INDEX, dossier actualizados.
6. ✅ Backup, restore y rollback: primer backup real ejecutado, restore aislado verificado, rollback validado en lab, copia externa a yggdrasil verificada. Ver docs/32.
11. ✅ CI en GitHub Actions: 4 jobs verdes (Python 3.13).

**PENDIENTES:**

3. La calidad del extractor no está aceptada para ingesta real general. Benchmark real ejecutado (docs/34, run 20260714-094125): dictamen Prioridad 2 PARCIAL — REQUIERE CORRECCIONES; ingesta BLOQUEADA (docs/33 para el plan).
4. No se ha ejecutado una primera ingesta real controlada (Prioridad 3).
5. La auditoría del grafo detecta problemas, pero la limpieza histórica no está aplicada (Prioridad 4).
7. El visor no tiene autenticación propia ni permisos aplicados (Prioridad 5).
8. El panel de revisión es principalmente de lectura.
9. El modo jugador y la visibilidad RPG no están implementados en la consulta.
10. La automatización de despliegue y la replicabilidad siguen incompletas.
12. El ciclo Nextcloud → worker → revisión → ingesta necesita una definición operativa única.

La Prioridad 2 evaluó la calidad del extractor con métricas cuantitativas (docs/34): ningún modo alcanza los umbrales de autoaprobación (F1 ent < 0.75, relaciones F1≈0, autoaprobación 0.85 < 0.95); se requiere una fase de mejora (relaciones, precisión de entidades, glosario de alias) antes de autorizar la primera ingesta real.

---

# 3. Qué se quiere conseguir con S9 Knowledge

## 3.1. Objetivo de producto

S9 Knowledge debe convertirse en una plataforma privada y autoalojada de conocimiento para juegos de rol, campañas y ambientaciones, capaz de:

- recibir fuentes heterogéneas;
- extraer conocimiento estructurado;
- conservar la evidencia y procedencia;
- detectar información dudosa;
- requerir revisión humana únicamente cuando sea necesaria;
- construir un grafo de conocimiento vivo;
- diferenciar información del narrador y de los jugadores;
- mantener varias ambientaciones o workspaces;
- permitir reconstrucción, auditoría y rollback;
- ofrecer consulta visual y, en fases posteriores, edición controlada.

## 3.2. Fuentes previstas

El sistema debe poder trabajar con:

- libros y manuales;
- documentos;
- notas;
- transcripciones;
- audio;
- vídeo;
- páginas web;
- contenido de YouTube;
- resultados generados por procesamiento externo;
- datos ya existentes en Neo4j;
- paquetes de conocimiento intercambiables.

## 3.3. Resultado final esperado

El flujo funcional objetivo es:

**Fuente original → preparación → transcripción o lectura → normalización → segmentación → clasificación → extracción → validación → resolución contra el grafo → decisión automática → revisión humana de excepciones → payload aprobado → backup → ingesta → auditoría posterior → visor con permisos**

## 3.4. El activo principal

El activo principal no es el código ni el visor. Es el conocimiento acumulado en el grafo.

Por ello, toda decisión técnica debe priorizar:

- integridad;
- trazabilidad;
- explicabilidad;
- deduplicación;
- recuperación;
- control de cambios;
- seguridad;
- separación entre información pública y secreta.

---

# 4. Fuentes revisadas y límites de esta auditoría

## 4.1. Documentación principal revisada

Se ha contrastado el estado descrito en:

- `README.md`;
- `ROADMAP.md`;
- `CHANGELOG.md`;
- `docs/INDEX.md`;
- `docs/00-vision.md`;
- `docs/01-architecture.md`;
- `docs/02-current-state.md`;
- `docs/03-phases.md`;
- `docs/05-data-engine.md`;
- `docs/06-viewer.md`;
- `docs/07-users-permissions.md`;
- `docs/08-deployment.md`;
- `docs/09-audit-before-work.md`;
- `docs/11-data-quality-review.md`;
- `docs/14-multimedia-ingestion-worker.md`;
- `docs/15-jobs-panel-and-worker.md`;
- `docs/18-l5a-transcription-glossary.md`;
- `docs/20-data-review-and-approved-ingest.md`;
- `docs/21-external-access-and-security.md`;
- `docs/22-replicability-and-external-processing.md`;
- `docs/23-knowledge-packages.md`;
- etiqueta `v0.2.5b`;
- PR `#2`;
- estructura visible de pruebas de `data-engine` y `viewer`.

También se han incorporado los dos informes de auditoría aportados como base del trabajo.

## 4.2. Límites

Esta revisión confirma el contenido público del repositorio, pero no ha tenido acceso directo a:

- VM105;
- servicios systemd;
- Neo4j en ejecución;
- montaje rclone;
- Nextcloud;
- Ollama;
- logs actuales;
- secretos;
- backups;
- estado real de los workers;
- ejecución actual de las pruebas.

Por tanto, cualquier afirmación sobre servicios desplegados debe tratarse como **operativo declarado pendiente de verificación**, salvo que se adjunte evidencia de VM105.

---

# 5. Fuente de verdad recomendada

Cuando dos documentos discrepen, se debe utilizar este orden:

1. Commit exacto desplegado en VM105.
2. Código correspondiente a ese commit.
3. Resultado reproducible de pruebas y auditorías.
4. Estado real de los servicios y bases de datos.
5. Este dosier y `docs/02-current-state.md`.
6. Documentación específica actualizada.
7. Informes históricos, ramas y PR cerrados.

Los informes de fase deben conservarse como historial, pero no deben utilizarse como estado actual si no están marcados expresamente como históricos.

---

# 6. Arquitectura funcional consolidada

## 6.1. Capa de fuentes

Responsable de almacenar y localizar:

- PDFs;
- documentos;
- notas;
- audio y vídeo;
- transcripciones;
- workspaces;
- paquetes exportados;
- peticiones y respuestas de procesamiento externo.

Nextcloud se plantea como almacenamiento principal. La VM procesa y conserva estados temporales o técnicos. Git almacena código y documentación. Neo4j contiene el grafo vivo.

## 6.2. Capa multimedia

Responsable de:

- detectar archivos;
- registrar trabajos;
- analizar el medio;
- extraer audio cuando corresponda;
- transcribir;
- normalizar términos;
- conservar timestamps;
- generar un resultado preparado para revisión.

El uso de faster-whisper `medium` y normalización determinista aparece como la vía recomendada para L5A, pero el resultado documentado corresponde a muestras concretas y no debe presentarse como garantía universal.

## 6.3. Capa de tratamiento de conocimiento

Responsable de:

- segmentar;
- clasificar;
- extraer entidades y relaciones;
- validar contra el esquema RPG;
- resolver contra nodos existentes;
- detectar ambigüedad y duplicados;
- calcular confianza;
- tomar una decisión automática;
- generar la cola de revisión;
- construir el payload aprobado.

## 6.4. Capa de ingesta

Responsable de:

- comprobar el paquete;
- verificar procedencia;
- rechazar datos incompletos;
- simular la escritura;
- requerir autorización explícita;
- escribir por fuente;
- permitir auditoría y rollback.

La ingesta real debe permanecer bloqueada por defecto.

## 6.5. Capa de grafo

Neo4j debe conservar:

- entidades;
- relaciones;
- workspaces;
- sesiones;
- procedencia;
- confianza;
- visibilidad;
- conocimiento por personaje;
- historial o versión cuando se implemente;
- metadatos de extracción y revisión.

## 6.6. Capa de aplicación

El visor actual cubre consulta y paneles básicos. La evolución prevista incluye:

- login;
- usuarios;
- sesiones;
- roles;
- acciones de revisión;
- administración;
- modo narrador;
- modo jugador;
- filtros de visibilidad;
- gestión de workspaces.

## 6.7. Capa operativa

Debe incluir:

- despliegue;
- healthchecks;
- logs;
- backup;
- restore;
- rollback;
- actualización;
- CI;
- control de versiones;
- documentación;
- recuperación ante fallos.

---

# 7. Estado real consolidado por componente

## 7.1. Base del repositorio

**Estado:** ✅ Cerrado como estructura base.

Existe separación entre motor de datos, visor, documentación, despliegues, scripts, ejemplos y carpeta compartida.

### Pendiente

- aclarar el propósito real de `shared/`;
- retirar archivos de backup u obsoletos versionados;
- impedir que reaparezcan;
- convertir componentes en paquetes instalables si todavía utilizan rutas manuales;
- unificar configuración y logging cuando haya duplicación real.

### Decisión

No reorganizar el repositorio antes de cerrar seguridad de datos y primera ingesta. La refactorización no debe alterar el comportamiento funcional.

---

## 7.2. Modelo RPG y esquema

**Estado:** ✅ Base implementada.

La documentación declara un esquema RPG amplio, con tipos de nodo y relaciones, además de etiquetas en español.

### Pendiente

- comprobar que todas las reglas semánticas están cubiertas por pruebas;
- versionar explícitamente cambios de esquema;
- establecer migraciones de esquema;
- separar incompatibilidad semántica de baja confianza;
- documentar qué relaciones pueden transformarse y cuáles deben rechazarse.

---

## 7.3. Data-engine

**Estado:** ✅ Núcleo implementado. 🟡 Flujo productivo pendiente de cierre.

El motor incluye lectura, tratamiento, validación, escritura y herramientas auxiliares.

### Problema documental

`docs/05-data-engine.md` todavía describe un flujo directo hacia Neo4j que puede interpretarse como la ruta principal. La documentación nueva establece un pipeline protegido con revisión y payload aprobado.

### Corrección necesaria

Deben distinguirse:

- **flujo legado o de laboratorio:** extracción y escritura directa;
- **flujo autorizado:** extracción, revisión, payload, dry-run, backup e ingesta;
- **herramientas de diagnóstico:** auditoría sin escritura.

La guía debe dejar claro cuál está permitido en producción.

---

## 7.4. Extractor

**Estado:** 🟡 Implementado con varias modalidades, calidad no aceptada para uso general.

El repositorio y el PR describen:

- extractor heurístico;
- stopwords;
- reglas contra personajes débiles;
- glosario por workspace;
- extractor LLM opcional;
- modo híbrido;
- contrato estructurado de salida;
- endurecimiento de validador, resolvedor y decisión.

### Contradicción actual

Parte de la documentación dice que el extractor LLM todavía debe implementarse. Otra parte afirma que ya existe una modalidad LLM o híbrida.

### Estado correcto

La falta no es simplemente “crear un extractor LLM”. La falta real es:

- comparar modalidades con un corpus representativo;
- medir falsos positivos y falsos negativos;
- definir qué modalidad se usa por tipo de fuente;
- fijar un umbral de aceptación;
- demostrar que los autoaprobados son seguros;
- conservar revisión humana para excepciones.

### Enfoque recomendado

Mantener una arquitectura híbrida:

- reglas deterministas para señales claras;
- LLM para contexto complejo;
- validador determinista obligatorio;
- resolución contra Neo4j;
- revisión humana para ambigüedad.

---

## 7.5. Pipeline de revisión

**Estado:** ✅ Framework implementado. 🟡 Aceptación productiva pendiente.

Están descritas las fases:

- segmentación;
- clasificación;
- extracción;
- validación;
- resolución;
- decisión automática;
- cola de revisión;
- payload aprobado;
- informe de calidad;
- auditoría.

### Pendiente

- métricas estables por tipo de fuente;
- deduplicación previa al autoaprobado;
- política para entidades de un solo token;
- política para nombres parecidos;
- evidencia visible de cada candidato;
- prueba extremo a extremo reproducible;
- definición clara de cuándo un resultado puede autoaprobarse;
- revisión del efecto de errores ASR.

---

## 7.6. Ingesta aprobada

**Estado:** ✅ Protecciones implementadas. 🟠 Ingesta real controlada no demostrada.

La documentación describe doble protección:

- ejecución simulada;
- autorización adicional para escritura.

### Pendiente crítico

- backup probado;
- restauración probada;
- rollback por fuente probado;
- ingesta de una fuente pequeña;
- auditoría anterior y posterior;
- comprobación de que el resto del grafo no cambia;
- registro de quién autorizó la operación;
- cierre automático de la autorización después de ejecutar.

### Decisión

No habilitar ingesta masiva hasta completar el bloque de primera ingesta controlada.

---

## 7.7. Neo4j

**Estado:** ✅ Operativo y verificado (commit cef9233). ✅ Backup y restore demostrados.

Neo4j 5.26.0 Community en VM105, puertos limitados a 127.0.0.1 desde 2026-07-12. Estado verificado: 199 nodos, 140 relaciones, 14 labels, 2 índices.

### Prioridad 1 — COMPLETADA (2026-07-13–14)

| Ítem | Estado | Evidencia |
|------|--------|-----------|
| Backup real de producción | ✅ | neo4j-20260713-174909/neo4j.dump, 132 KB, SHA256 c3179c01... |
| Restore en instancia aislada | ✅ | 199/140 nodos/relaciones, idéntico a producción |
| Rollback por source_id | ✅ | Patrón Cypher validado en lab |
| Copia externa a yggdrasil | ✅ | /var/backups/s9-knowledge/neo4j/, SHA256 verificado, 2026-07-14 |
| Scripts backup/restore/rollback | ✅ | scripts/backup/ en main |
| Documentación | ✅ | docs/26–29, 32 |

### Pendiente operativo (P1.1)

- Timer systemd para backup periódico (diseñado, sin activar)
- Script transaccional de rollback con --dry-run (patrón Cypher validado, orquestación pendiente)
- Prueba periódica programada de restore

### Pendiente calidad del grafo

- ~87 nodos históricos sin source_id/source_kind (detectados por audit-graph)
- Relaciones históricas semánticamente inválidas (HAS_FOUGHT → FOUGHT_AT con destino Location)
- Duplicados detectados por audit-graph, no corregidos
- Política de migraciones de esquema
- Dashboard de calidad o informes periódicos

---

## 7.8. Calidad del grafo

**Estado:** ✅ Herramientas de auditoría. 🟡 Corrección real pendiente.

La auditoría puede detectar:

- duplicados;
- metadatos ausentes;
- baja confianza;
- relaciones problemáticas;
- anomalías históricas.

### Falta real

Detectar no equivale a corregir.

Se necesita una fase de migraciones controladas que:

- clasifique problemas;
- proponga cambios;
- genere dry-run;
- exija revisión en casos ambiguos;
- cree rollback;
- aplique lotes pequeños;
- vuelva a auditar después.

---

## 7.9. Visor web

**Estado:** 🟢 Visor mínimo desplegado según la documentación. 🔍 Verificación requerida.

El repositorio describe:

- FastAPI;
- Jinja2;
- visualización con vis-network;
- proveedor mock;
- proveedor Neo4j;
- búsqueda y fichas;
- `/graph`;
- `/jobs`;
- `/reviews`;
- adaptación móvil.

### Contradicción grave

`docs/01-architecture.md`, `docs/03-phases.md`, `docs/06-viewer.md` y `ROADMAP.md` todavía presentan el visor como futuro o pendiente.

### Estado correcto

- visor de consulta: implementado;
- paneles básicos: implementados;
- administración: pendiente;
- autenticación propia: pendiente;
- permisos: pendientes;
- edición: pendiente;
- acciones de revisión: pendientes.

---

## 7.10. Panel de revisión

**Estado:** ✅ Lectura básica. 🟡 Flujo de trabajo pendiente.

El panel muestra fuentes, decisiones, origen y calidad.

### Pendiente

- aprobar;
- rechazar;
- editar;
- vincular con nodo existente;
- marcar duplicado;
- regenerar payload;
- guardar autor y fecha;
- conservar historial;
- aplicar permisos.

No debe añadirse escritura al panel antes de disponer de autenticación, auditoría y control de concurrencia.

---

## 7.11. Jobs

**Estado:** 🟡 Infraestructura base implementada.

Existe almacenamiento de jobs, CLI, worker y panel de lectura. La documentación señala que el worker genérico dispone de handlers de prueba y que los handlers reales o controles del panel están incompletos.

### Pendiente

- ciclo de vida único;
- handlers reales;
- reintentos;
- cancelación;
- pausa;
- logs;
- límites de concurrencia;
- idempotencia;
- detección de duplicados;
- recuperación tras reinicio;
- integración clara con multimedia;
- servicio persistente;
- permisos.

### Decisión sobre SQLite

Mantener SQLite mientras exista un único escritor y no se demuestre contención. PostgreSQL o Redis deben considerarse únicamente cuando haya varios workers, procesamiento distribuido o problemas medidos.

---

## 7.12. Worker multimedia

**Estado:** 🟡 Código y flujo base presentes. 🔍 Operación completa por verificar.

La documentación describe detección, ffmpeg, transcripción y Markdown revisable.

### Contradicciones

- algunos documentos lo presentan como futuro o parcial;
- otros lo declaran operativo;
- algunos ejemplos usan `small`;
- la guía de glosario recomienda `medium`;
- la conexión entre colas o estados no aparece consolidada.

### Corrección

Definir una política única:

- modelo por defecto;
- límites de RAM;
- número máximo de procesos;
- estados del job;
- rutas de entrada y salida;
- comportamiento ante fallo;
- cuándo pasa a revisión;
- qué archivos vuelven a Nextcloud;
- qué no se escribe en Neo4j.

---

## 7.13. Glosario y normalización de transcripciones

**Estado:** ✅ Prototipo funcional y probado. 🟡 Política productiva pendiente.

Se documenta:

- glosario SQLite;
- extracción de términos;
- formas erróneas;
- normalización determinista;
- preservación de timestamps;
- benchmark con una muestra real;
- corrección LLM descartada o limitada por no preservar correctamente el formato.

### Precisión documental

El dato de error cero de `medium` debe presentarse como resultado de la muestra ensayada, no como tasa global garantizada.

### Pendiente

- corpus mayor;
- varias voces;
- ruido;
- sesiones largas;
- otros workspaces;
- versionado del glosario;
- conflictos entre términos;
- revisión de correcciones;
- métricas por modelo.

---

## 7.14. Paquetes de conocimiento

**Estado:** ✅ Módulos descritos e implementados. 🟠 Flujo externo completo por demostrar.

La documentación describe paquetes sanitizados, peticiones externas, respuestas externas y candidatos importados.

### Contradicción

README y estado actual hablan en algunos puntos de exportación/importación “preparada pero no completa”, mientras `docs/23` y el PR describen módulos ya implementados.

### Estado correcto

- formatos y módulos: implementados;
- validaciones básicas: implementadas;
- roundtrip productivo completo: requiere evidencia;
- integración con Nextcloud: requiere verificación;
- operación con un worker externo real: no demostrada en la documentación;
- ingesta local posterior: continúa protegida.

---

## 7.15. Permisos y access store

**Estado:** 🟡 Capa de datos presente, aplicación pendiente.

Existe una base para permisos o visibilidad, pero no está aplicada en el visor y la API.

### Pendiente

- usuarios;
- roles;
- campañas;
- personajes asociados;
- visibilidad;
- `known_by`;
- nivel de spoiler;
- filtrado de nodos;
- filtrado de relaciones;
- filtrado de búsquedas;
- protección de endpoints;
- pruebas que garanticen que un jugador no puede inferir datos ocultos.

---

## 7.16. Login y sesiones

**Estado:** ❌ No implementado.

Actualmente se describe Basic Auth en el proxy para acceso externo, pero no autenticación propia.

### Pendiente

- usuarios;
- hash de contraseñas;
- sesiones;
- cookies seguras;
- cierre de sesión;
- administración;
- recuperación o rotación;
- protección de rutas;
- auditoría de acciones;
- política LAN, Tailscale y dominio.

---

## 7.17. Modo narrador y jugador

**Estado:** ❌ No implementado.

### Narrador

Debe poder:

- ver todo;
- revisar;
- administrar;
- consultar secretos;
- ver trazabilidad;
- ejecutar acciones autorizadas.

### Jugador

Debe poder:

- consultar información pública;
- consultar información conocida por su personaje;
- evitar spoilers;
- no acceder a jobs ni revisiones;
- no inferir la existencia de nodos ocultos mediante búsquedas o relaciones.

---

## 7.18. Acceso externo y seguridad

**Estado:** 🟡 Parcial.

La documentación declara:

- acceso externo por proxy HTTPS;
- Basic Auth;
- Neo4j cerrado a localhost;
- visor directo por LAN o Tailscale sin autenticación propia.

### Riesgos

- rutas sensibles visibles desde redes internas;
- falta de roles;
- imposibilidad de atribuir revisiones;
- detalles de topología interna en un repositorio público;
- dependencia de una barrera externa que no conoce permisos RPG;
- librería frontend cargada desde CDN, según la auditoría aportada.

### Correcciones

- autenticación propia;
- protección uniforme;
- revisión de cabeceras y cookies;
- vendorizar recursos frontend o usar integridad verificable;
- sanitizar documentación pública;
- trasladar IP, usuarios operativos, rutas y detalles concretos a documentación privada cuando no sean necesarios públicamente;
- escaneo automático de secretos.

---

## 7.19. Nextcloud, rclone y workspaces

**Estado:** 🟡 Integración operativa declarada fuera del repositorio. 🔍 Verificación requerida.

### Pendiente

- usuario de servicio;
- permisos mínimos;
- estructura estándar;
- healthcheck;
- escritura controlada;
- separación entre fuentes y derivados;
- política de nombres;
- versionado;
- cuarentena;
- exportaciones;
- no borrado de fuentes;
- recuperación tras pérdida del montaje;
- documentación del error y rotación de credenciales de aplicación.

---

## 7.20. Pruebas

**Estado:** 🟡 Suites presentes; resultado actual no verificado.

La estructura del repositorio muestra numerosos tests en ambos componentes. Esto contradice la auditoría que afirmaba ausencia de pruebas.

### Inconsistencia importante

La etiqueta `v0.2.5b` menciona `84/84` pruebas. El comentario final del PR menciona `116` pruebas de data-engine y `36` de viewer.

No debe publicarse una cifra como estado actual hasta ejecutar la suite sobre el commit desplegado y registrar:

- commit;
- fecha;
- entorno;
- comandos;
- número de pruebas;
- resultados;
- exclusiones;
- pruebas que requieren servicios reales.

### Pendiente

- CI;
- integración con Neo4j;
- integración con Ollama;
- extremo a extremo;
- backup/restore;
- rollback;
- seguridad de permisos;
- regresión de falsos positivos;
- concurrencia de jobs;
- roundtrip de paquetes.

---

## 7.21. CI/CD

**Estado:** ❌ No aparece configurado.

La página de GitHub Actions no muestra workflows del proyecto.

### Mínimo necesario

- linting;
- pruebas;
- comprobación de tipos;
- auditoría de dependencias;
- escaneo de secretos;
- validación de Markdown;
- comprobación de enlaces internos;
- construcción o validación de artefactos;
- bloqueo de merge si falla una comprobación crítica.

El despliegue automático puede añadirse después. La primera necesidad es CI, no CD.

---

## 7.22. Replicabilidad

**Estado:** 🟠 Diseñada y documentada parcialmente.

Existen modos de funcionamiento y variables previstas, pero no un instalador completo.

### Pendiente

- instalación reproducible;
- validación de requisitos;
- inicialización;
- servicios;
- permisos de directorios;
- plantillas;
- actualización;
- rollback de versión;
- post-check;
- desinstalación o reconstrucción;
- variante Docker, si aporta valor.

### Decisión

No migrar VM105 a Docker únicamente para cumplir una preferencia arquitectónica. Primero debe hacerse reproducible el despliegue existente. Docker puede ofrecerse como modo alternativo.

---

## 7.23. Operación, backup y recuperación

**Estado:** ❌ No cerrado como procedimiento probado.

La documentación menciona backup, pero no se ha identificado una guía integral que demuestre:

- qué se respalda;
- con qué frecuencia;
- retención;
- consistencia;
- restauración;
- rollback de una fuente;
- recuperación de jobs;
- recuperación de reviews;
- recuperación de configuración;
- validación posterior.

Este es el principal bloqueo antes de permitir escrituras reales.

---

# 8. Inconsistencias documentales que deben corregirse

## 8.1. Visor futuro frente a visor desplegado

### Documentos afectados

- `docs/01-architecture.md`;
- `docs/03-phases.md`;
- `docs/06-viewer.md`;
- `ROADMAP.md`.

### Corrección

Cambiar “futuro” o “pendiente” por una división explícita:

- visor mínimo de consulta: implementado;
- panel `/jobs`: implementado como base;
- panel `/reviews`: implementado como lectura;
- login: pendiente;
- administración: pendiente;
- acciones: pendientes;
- permisos RPG: pendientes.

---

## 8.2. Estado de la rama y PR

### Documento afectado

- `docs/02-current-state.md`.

### Problema

Todavía aparecen referencias a rama de feature o PR draft, aunque existe una etiqueta `v0.2.5b` sobre `1fd94b8` y el PR está cerrado.

### Corrección

Indicar:

- estado consolidado en `main`;
- tag actual;
- commit;
- PR histórico;
- método exacto de integración solo si es relevante.

---

## 8.3. Estado del extractor

### Documentos afectados

- `README.md`;
- `docs/02-current-state.md`;
- `docs/20-data-review-and-approved-ingest.md`;
- PR histórico.

### Problema

Se mezclan estas afirmaciones:

- el heurístico genera falsos positivos;
- debe sustituirse por LLM;
- ya hay stopwords;
- ya existe modo LLM;
- ya existe modo híbrido;
- el número de autoaprobados se redujo considerablemente.

### Corrección

Sustituir el bloqueo de implementación por un bloqueo de calidad:

> La ingesta real general permanece bloqueada hasta que una batería representativa demuestre que la modalidad seleccionada cumple los umbrales de precisión, deduplicación, trazabilidad y rollback.

---

## 8.4. Exportación e importación

### Documentos afectados

- `README.md`;
- `docs/02-current-state.md`;
- `docs/22-replicability-and-external-processing.md`;
- `docs/23-knowledge-packages.md`.

### Problema

Unos textos dicen que está preparado; otros que está implementado.

### Corrección

Separar:

- clases y formatos implementados;
- validación implementada;
- flujo local probado;
- roundtrip con worker externo;
- almacenamiento Nextcloud;
- operación productiva.

---

## 8.5. Tests

### Documentos afectados

- `docs/05-data-engine.md`;
- `CHANGELOG.md`;
- etiqueta `v0.2.5b`;
- comentarios del PR;
- `docs/02-current-state.md`.

### Problema

Aparecen cifras diferentes y antiguas.

### Corrección

Crear una tabla de pruebas generada o actualizada para cada release con:

- commit;
- fecha;
- data-engine;
- viewer;
- integración;
- E2E;
- resultado total;
- entorno.

---

## 8.6. Neo4j en LAN

### Documentos afectados

- `docs/08-deployment.md`;
- `docs/11-data-quality-review.md`;
- otros informes históricos.

### Problema

Algunos documentos muestran acceso LAN mientras seguridad declara que Neo4j se cerró a localhost.

### Corrección

Marcar el acceso LAN como situación histórica. La configuración vigente debe describirse una sola vez en la guía de seguridad.

---

## 8.7. Modelo Whisper

### Documentos afectados

- `docs/14-multimedia-ingestion-worker.md`;
- `docs/18-l5a-transcription-glossary.md`;
- ejemplos de configuración.

### Problema

Se mezclan `small` y `medium` sin política clara.

### Corrección

Definir:

- modelo de desarrollo;
- modelo recomendado para calidad;
- modelo externo o GPU;
- límites de RAM;
- concurrencia;
- criterio para cambiar de modelo.

---

## 8.8. Jobs y worker multimedia

### Documentos afectados

- `docs/14-multimedia-ingestion-worker.md`;
- `docs/15-jobs-panel-and-worker.md`;
- `docs/02-current-state.md`;
- `ROADMAP.md`.

### Problema

No queda claro si:

- el worker está desplegado;
- se ejecuta periódicamente;
- usa la cola general;
- usa una cola separada;
- qué handlers son reales;
- qué partes son únicamente prototipo.

### Corrección

Crear una matriz de implementación por handler y un diagrama único del ciclo del job.

---

## 8.9. Documentación pública de infraestructura

### Documentos afectados

- especialmente `docs/08` y `docs/21`.

### Problema

El repositorio es público y contiene detalles concretos de topología, direcciones, usuarios operativos, dominios y rutas.

### Corrección

Separar:

- documentación pública y reproducible;
- documentación privada del despliegue real.

No es necesario ocultar la arquitectura general, pero sí reducir información operativa que no aporta valor al usuario del proyecto.

---

# 9. Plan de actualización documental por archivo

## 9.1. `README.md`

### Debe conservar

- visión;
- arquitectura general;
- inicio rápido;
- estado de alto nivel;
- enlaces a documentación.

### Debe corregir

- estado del extractor;
- estado de export/import;
- visor implementado;
- tag y release;
- diferencia entre código y despliegue;
- enlace a este dosier;
- advertencia de ingesta real;
- estado de autenticación.

### Checklist

- [ ] Sustituir afirmaciones absolutas antiguas por estado medible.
- [ ] Añadir tabla “implementado / parcial / pendiente”.
- [ ] Enlazar el dosier como guía maestra.
- [ ] Enlazar runbook de ingesta.
- [ ] Enlazar runbook de backup.
- [ ] Evitar repetir detalles que deben vivir en `docs/`.

---

## 9.2. `docs/00-vision.md`

- [ ] Cambiar referencias al visor futuro.
- [ ] Añadir revisión humana mínima.
- [ ] Añadir rollback por fuente.
- [ ] Añadir permisos RPG como objetivo de producto.
- [ ] Añadir definición de éxito.

---

## 9.3. `docs/01-architecture.md`

- [ ] Sustituir arquitectura antigua por el flujo protegido.
- [ ] Incluir paneles actuales.
- [ ] Diferenciar extracción, revisión e ingesta.
- [ ] Incluir paquetes externos.
- [ ] Incluir fuentes y almacenamiento.
- [ ] Incluir autenticación como capa pendiente.
- [ ] Marcar cada componente por estado.

---

## 9.4. `docs/02-current-state.md`

Debe ser una fotografía factual, no una mezcla de roadmap y diario.

- [ ] Indicar tag, commit y fecha.
- [ ] Retirar referencias a PR draft.
- [ ] Separar repositorio y VM105.
- [ ] Registrar pruebas verificadas.
- [ ] Registrar servicios verificados.
- [ ] Registrar riesgos residuales.
- [ ] No repetir propuestas largas.
- [ ] Enlazar este dosier para el plan completo.

---

## 9.5. `docs/03-phases.md`

- [ ] Cerrar fases ya ejecutadas.
- [ ] Reordenar fases futuras según integridad del grafo.
- [ ] Añadir dependencias entre bloques.
- [ ] Eliminar “visor pendiente”.
- [ ] Añadir primera ingesta controlada.
- [ ] Añadir migraciones del grafo.
- [ ] Añadir auth antes de acciones de revisión.
- [ ] Añadir visibilidad RPG después de auth.

---

## 9.6. `docs/05-data-engine.md`

- [ ] Diferenciar flujo directo y flujo autorizado.
- [ ] Marcar el flujo directo como laboratorio o legado.
- [ ] Documentar versiones del esquema.
- [ ] Actualizar referencias de tests.
- [ ] Enlazar pipeline de revisión.
- [ ] Enlazar migraciones y rollback.

---

## 9.7. `docs/06-viewer.md`

Debe reescribirse casi por completo.

- [ ] Describir visor existente.
- [ ] Describir providers.
- [ ] Describir rutas.
- [ ] Describir paneles.
- [ ] Indicar limitaciones.
- [ ] Separar futuro: auth, edición, usuarios y permisos.
- [ ] Añadir pruebas y healthcheck.
- [ ] Añadir límites de consultas.

---

## 9.8. `docs/07-users-permissions.md`

- [ ] Indicar que access store existe.
- [ ] Indicar que no está aplicado.
- [ ] Definir roles iniciales.
- [ ] Definir visibilidad por nodo y relación.
- [ ] Definir modo jugador.
- [ ] Añadir amenazas de inferencia.
- [ ] Añadir pruebas de autorización.

---

## 9.9. `docs/08-deployment.md`

- [ ] Corregir exposición de Neo4j.
- [ ] Describir servicios actuales.
- [ ] Añadir healthchecks.
- [ ] Añadir actualización y rollback.
- [ ] Enlazar backup/restore.
- [ ] Separar datos públicos y privados.
- [ ] Retirar recomendación de conservar backups de código versionados.
- [ ] Añadir validación post-despliegue.

---

## 9.10. `docs/09-audit-before-work.md`

- [ ] Actualizar orden de fuentes de verdad.
- [ ] Incluir commit desplegado.
- [ ] Incluir tests.
- [ ] Incluir backup.
- [ ] Incluir dry-run.
- [ ] Incluir revisión documental final.
- [ ] Aplicarlo a cualquier cambio de datos.

---

## 9.11. `docs/11-data-quality-review.md`

- [ ] Marcar observaciones históricas.
- [ ] Separar problemas corregidos de problemas aún presentes.
- [ ] Añadir clasificación de riesgos.
- [ ] Enlazar plan de migraciones.
- [ ] Añadir auditoría posterior.
- [ ] Actualizar conectividad Neo4j.

---

## 9.12. `docs/14-multimedia-ingestion-worker.md`

- [ ] Fijar modelo recomendado.
- [ ] Documentar límites de recursos.
- [ ] Definir estados.
- [ ] Definir integración con jobs.
- [ ] Definir reintentos.
- [ ] Definir salida a Nextcloud.
- [ ] Aclarar estado de despliegue.
- [ ] Retirar instrucciones antiguas de importación cuando se empaquete correctamente.

---

## 9.13. `docs/15-jobs-panel-and-worker.md`

- [ ] Marcar el informe de fase como histórico o actualizarlo.
- [ ] Inventariar handlers.
- [ ] Indicar cuáles son de prueba.
- [ ] Definir servicio persistente.
- [ ] Añadir idempotencia.
- [ ] Añadir acciones futuras del panel.
- [ ] Añadir permisos.
- [ ] Definir relación con multimedia.

---

## 9.14. `docs/18-l5a-transcription-glossary.md`

- [ ] Conservar benchmark con contexto.
- [ ] No presentar un resultado muestral como garantía.
- [ ] Añadir corpus futuro.
- [ ] Definir versionado del glosario.
- [ ] Definir revisión de correcciones.
- [ ] Enlazar normalización previa a extracción.

---

## 9.15. `docs/20-data-review-and-approved-ingest.md`

- [ ] Marcar los falsos positivos iniciales como hallazgo histórico.
- [ ] Describir endurecimiento ya aplicado.
- [ ] Documentar las modalidades actuales.
- [ ] Sustituir “implementar LLM” por criterios de aceptación.
- [ ] Añadir primera ingesta controlada.
- [ ] Añadir backup.
- [ ] Añadir rollback.
- [ ] Añadir auditoría anterior y posterior.
- [ ] Definir evidencias obligatorias.

---

## 9.16. `docs/21-external-access-and-security.md`

- [ ] Mantener Neo4j en localhost.
- [ ] Documentar rutas actualmente sin auth.
- [ ] Añadir plan de autenticación propia.
- [ ] Añadir política de sesiones.
- [ ] Añadir roles.
- [ ] Añadir escaneo de secretos.
- [ ] Revisar exposición de topología.
- [ ] Definir si Basic Auth permanece como segunda barrera.

---

## 9.17. `docs/22-replicability-and-external-processing.md`

- [ ] Separar preparación, implementación y demostración.
- [ ] Definir modos soportados.
- [ ] Definir almacenamiento.
- [ ] Definir seguridad del worker externo.
- [ ] Definir roundtrip.
- [ ] Añadir checklist de instalación.
- [ ] Añadir compatibilidad de versiones.

---

## 9.18. `docs/23-knowledge-packages.md`

- [ ] Añadir estado por tipo de paquete.
- [ ] Añadir compatibilidad de esquema.
- [ ] Añadir firma o checksum.
- [ ] Añadir política de datos sanitizados.
- [ ] Añadir prueba roundtrip.
- [ ] Añadir origen y auditoría.
- [ ] Añadir rechazo de paquetes incompatibles.

---

## 9.19. `docs/INDEX.md`

- [ ] Añadir este dosier.
- [ ] Distinguir documentos actuales e históricos.
- [ ] Identificar el documento canónico de cada área.
- [ ] Añadir runbooks futuros.
- [ ] Añadir mapa de dependencias.

---

## 9.20. `ROADMAP.md`

Debe reescribirse.

- [ ] Retirar tareas ya cerradas.
- [ ] Usar las prioridades de este dosier.
- [ ] Añadir criterios de salida.
- [ ] Añadir dependencias.
- [ ] Añadir versión objetivo.
- [ ] No mezclar deseos futuros con bloqueos actuales.

---

## 9.21. `CHANGELOG.md`

- [ ] Añadir visor mínimo.
- [ ] Añadir v0.2.4.
- [ ] Añadir v0.2.5 y v0.2.5b.
- [ ] Añadir seguridad Neo4j.
- [ ] Añadir glosario.
- [ ] Añadir revisión.
- [ ] Añadir paquetes.
- [ ] Registrar cifras de tests solo después de verificarlas.
- [ ] Usar formato coherente por release.

---

# 10. Documentos nuevos recomendados

## `docs/24-project-dossier-and-checklist.md`

Versión de este dosier dentro del repositorio.

## `docs/25-operations-backup-and-restore.md`

Debe cubrir operación, backups, restore y verificación.

## `docs/26-controlled-ingest-runbook.md`

Debe cubrir la primera ingesta y las siguientes ingestiones autorizadas.

## `docs/27-graph-migrations-and-rollback.md`

Debe cubrir limpieza, fusiones, metadatos, relaciones y reversión.

## `docs/28-test-strategy-and-quality-gates.md`

Debe cubrir suites, CI, corpus, criterios y evidencias.

## `docs/29-auth-and-rpg-visibility.md`

Debe cubrir usuarios, sesiones, roles, jugador, narrador y spoilers.

---

# 11. Orden de prioridad del proyecto

| Prioridad | Bloque | Resultado |
|---:|---|---|
| 0 | Estado verificable y documentación | Una única versión de la verdad |
| 1 | Backup, restore y rollback | Escrituras recuperables |
| 2 | Calidad de extracción | Candidatos fiables |
| 3 | Pruebas y CI | Cambios verificables |
| 4 | Primera ingesta controlada | Flujo real demostrado |
| 5 | Limpieza del grafo | Base histórica coherente |
| 6 | Login y seguridad | Acceso atribuible y protegido |
| 7 | Acciones de revisión | Flujo humano desde el visor |
| 8 | Permisos RPG | Modo narrador y jugador |
| 9 | Nextcloud y workspaces | Ciclo de archivos ordenado |
| 10 | Jobs y multimedia | Automatización completa |
| 11 | Replicabilidad | Instalación reconstruible |
| 12 | Refactorización | Mantenibilidad |
| 13 | Rendimiento y escala | Crecimiento medido |

---

# 12. PRIORIDAD 0 — Estado verificable y cierre documental

## Objetivo

Eliminar contradicciones antes de programar nuevas funciones.

## Checklist

- [ ] Registrar el commit desplegado en VM105.
- [ ] Confirmar que coincide con la versión deseada.
- [ ] Registrar tag.
- [ ] Ejecutar pruebas de data-engine.
- [ ] Ejecutar pruebas de viewer.
- [ ] Registrar resultados reales.
- [ ] Confirmar `/graph`.
- [ ] Confirmar `/jobs`.
- [ ] Confirmar `/reviews`.
- [ ] Confirmar conexión local con Neo4j.
- [ ] Confirmar bloqueo de ingesta.
- [ ] Confirmar estado de workers.
- [ ] Confirmar rclone.
- [ ] Confirmar servicios systemd.
- [ ] Actualizar `docs/02`.
- [ ] Actualizar `README`.
- [ ] Actualizar `ROADMAP`.
- [ ] Actualizar `CHANGELOG`.
- [ ] Añadir este dosier al índice.

## Criterio de cierre

Existe una ficha firmada por fecha y commit que permite reproducir el estado declarado.

## Evidencias

- salida de pruebas;
- estado de servicios;
- endpoints;
- commit;
- auditoría;
- captura o log de healthcheck.

---

# 13. PRIORIDAD 1 — Backup, restore y rollback

## Objetivo

Evitar que una escritura incorrecta dañe permanentemente el conocimiento.

## Checklist

- [ ] Inventariar datos persistentes.
- [ ] Definir backup de Neo4j.
- [ ] Definir backup de jobs.
- [ ] Definir backup de reviews.
- [ ] Definir backup de paquetes.
- [ ] Definir backup de configuración sin exponer secretos.
- [ ] Definir retención.
- [ ] Definir ubicación externa.
- [ ] Probar restauración de Neo4j.
- [ ] Probar restauración de jobs.
- [ ] Probar restauración de reviews.
- [ ] Diseñar rollback por `source_id`.
- [ ] Probar rollback con datos de laboratorio.
- [ ] Auditar antes y después.
- [ ] Documentar tiempos y requisitos.
- [ ] Añadir alerta si el último backup es demasiado antiguo.
- [ ] Bloquear ingesta si no existe backup válido.

## Criterio de cierre

Se restaura una copia y se elimina una fuente de prueba sin afectar a otras fuentes.

---

# 14. PRIORIDAD 2 — Calidad del extractor y del pipeline

## Objetivo

Demostrar que la selección de autoaprobados es fiable.

## Corpus mínimo

Debe incluir:

- transcripción limpia;
- transcripción con errores;
- manual;
- texto narrativo;
- notas cortas;
- nombres de un token;
- alias;
- homónimos;
- entidades ya existentes;
- relaciones inválidas;
- casos negativos.

## Checklist

- [ ] Crear corpus versionado.
- [ ] Anotar verdad esperada.
- [ ] Ejecutar heurístico.
- [ ] Ejecutar LLM.
- [ ] Ejecutar híbrido.
- [ ] Medir precisión.
- [ ] Medir recall.
- [ ] Medir falsos positivos.
- [ ] Medir duplicados.
- [ ] Medir relaciones inválidas.
- [ ] Medir candidatos sin evidencia.
- [ ] Medir coste y tiempo.
- [ ] Definir modalidad por tipo de fuente.
- [ ] Definir umbrales.
- [ ] Añadir regresiones.
- [ ] Exigir evidencia.
- [ ] Versionar prompt, modelo, esquema y glosario.

## Criterio de cierre

Los resultados alcanzan los umbrales acordados y ningún caso crítico conocido vuelve a autoaprobarse incorrectamente.

---

# 15. PRIORIDAD 3 — Pruebas y CI

## Objetivo

Convertir el estado del proyecto en una comprobación automática.

## Checklist

- [ ] Inventariar tests existentes.
- [ ] Resolver la discrepancia de cifras.
- [ ] Clasificar unitarios.
- [ ] Clasificar integración.
- [ ] Clasificar semánticos.
- [ ] Clasificar E2E.
- [ ] Añadir Neo4j de prueba.
- [ ] Añadir mocks de Ollama cuando corresponda.
- [ ] Añadir prueba real opcional.
- [ ] Añadir rollback.
- [ ] Añadir permisos.
- [ ] Añadir jobs.
- [ ] Añadir paquetes.
- [ ] Añadir Markdown lint.
- [ ] Añadir comprobación de enlaces.
- [ ] Crear GitHub Actions.
- [ ] Bloquear merge si falla una etapa crítica.
- [ ] Publicar informe de cada release.

## Criterio de cierre

Cada cambio en `main` dispone de un resultado automático y reproducible.

---

# 16. PRIORIDAD 4 — Primera ingesta real controlada

## Objetivo

Demostrar el recorrido completo sin riesgo innecesario.

## Selección de la fuente

Debe ser:

- pequeña;
- conocida;
- con resultado verificable;
- sin cientos de entidades;
- aislable por `source_id`;
- fácil de retirar.

## Checklist previa

- [ ] Commit verificado.
- [ ] Tests correctos.
- [ ] Backup reciente.
- [ ] Restore probado.
- [ ] Corpus y extractor aceptados.
- [ ] Quality report limpio.
- [ ] Duplicados revisados.
- [ ] Payload revisado.
- [ ] Dry-run revisado.
- [ ] Autorización registrada.
- [ ] Ventana de mantenimiento definida.

## Checklist posterior

- [ ] Contar nodos creados.
- [ ] Contar relaciones creadas.
- [ ] Comprobar procedencia.
- [ ] Comprobar evidencia.
- [ ] Comprobar duplicados.
- [ ] Comprobar consultas.
- [ ] Comprobar visor.
- [ ] Ejecutar audit-graph.
- [ ] Probar rollback.
- [ ] Restaurar la protección.
- [ ] Documentar el resultado.

## Criterio de cierre

La fuente puede añadirse y retirarse sin afectar al resto del grafo.

---

# 17. PRIORIDAD 5 — Limpieza del grafo histórico

## Objetivo

Eliminar deuda de datos antes de crecer.

## Orden

1. Metadatos seguros.
2. Relaciones claramente inválidas.
3. Duplicados exactos.
4. Duplicados aproximados.
5. Entidades sin procedencia.
6. Casos ambiguos.

## Checklist

- [ ] Exportar auditoría.
- [ ] Clasificar hallazgos.
- [ ] Definir auto-fix permitido.
- [ ] Definir revisión obligatoria.
- [ ] Generar propuesta.
- [ ] Generar dry-run.
- [ ] Generar rollback.
- [ ] Hacer backup.
- [ ] Aplicar lote pequeño.
- [ ] Auditar.
- [ ] Repetir.
- [ ] Registrar migración.

## Criterio de cierre

No quedan incidencias críticas conocidas y todas las modificaciones son trazables.

---

# 18. PRIORIDAD 6 — Login y seguridad del visor

## Objetivo

Proteger y atribuir todas las acciones.

## Checklist

- [ ] Modelo de usuario.
- [ ] Hash de contraseña.
- [ ] Sesiones.
- [ ] Cookies seguras.
- [ ] Login.
- [ ] Logout.
- [ ] Roles.
- [ ] Admin de usuarios.
- [ ] Protección de `/graph`.
- [ ] Protección de `/jobs`.
- [ ] Protección de `/reviews`.
- [ ] Registro de acciones.
- [ ] Política LAN.
- [ ] Política Tailscale.
- [ ] Política dominio.
- [ ] Revisión de Basic Auth.
- [ ] Rate limiting si procede.
- [ ] Pruebas de autorización.
- [ ] Escaneo de secretos.
- [ ] Recursos frontend locales o verificables.

## Criterio de cierre

Ninguna ruta sensible puede utilizarse sin sesión y cada acción queda atribuida.

---

# 19. PRIORIDAD 7 — Acciones de revisión

## Objetivo

Permitir revisión completa desde la aplicación.

## Checklist

- [ ] Aprobar.
- [ ] Rechazar.
- [ ] Editar.
- [ ] Vincular existente.
- [ ] Marcar duplicado.
- [ ] Posponer.
- [ ] Ver evidencia.
- [ ] Ver decisión.
- [ ] Ver origen.
- [ ] Regenerar payload.
- [ ] Historial.
- [ ] Autor.
- [ ] Fecha.
- [ ] Control de concurrencia.
- [ ] Permisos.
- [ ] Reversión de una decisión.
- [ ] Pruebas.

## Criterio de cierre

Un revisor autorizado puede cerrar una fuente sin editar archivos manualmente.

---

# 20. PRIORIDAD 8 — Permisos RPG y modo jugador

## Objetivo

Mostrar vistas diferentes del mismo grafo sin filtrar secretos.

## Checklist

- [ ] Definir narrador.
- [ ] Definir jugador.
- [ ] Definir administrador.
- [ ] Asociar personaje.
- [ ] Definir visibilidad.
- [ ] Definir `known_by`.
- [ ] Definir spoiler.
- [ ] Definir campaña.
- [ ] Filtrar nodos.
- [ ] Filtrar relaciones.
- [ ] Filtrar búsquedas.
- [ ] Filtrar contadores.
- [ ] Evitar inferencias.
- [ ] Probar acceso directo.
- [ ] Probar API.
- [ ] Probar visor.
- [ ] Auditar denegaciones.

## Criterio de cierre

Un jugador no puede descubrir información secreta ni siquiera mediante búsquedas, relaciones o endpoints directos.

---

# 21. PRIORIDAD 9 — Nextcloud y workspaces

## Objetivo

Crear un ciclo de archivos seguro y predecible.

## Estructura conceptual

Cada workspace debe separar:

- fuentes;
- entrada;
- transcripciones;
- normalizados;
- revisión;
- aprobados;
- exportaciones;
- respuestas externas;
- errores;
- archivo.

## Checklist

- [ ] Usuario de servicio.
- [ ] Permisos mínimos.
- [ ] No usar administrador.
- [ ] No borrar fuentes.
- [ ] Estructura estándar.
- [ ] Nombres únicos.
- [ ] Versionado.
- [ ] Checksums.
- [ ] Healthcheck de lectura.
- [ ] Healthcheck de escritura.
- [ ] Detección de montaje caído.
- [ ] Reintentos.
- [ ] Cuarentena.
- [ ] Política de limpieza.
- [ ] Documentar rotación de app-password.
- [ ] Prueba de extremo a extremo.

## Criterio de cierre

Depositar una fuente produce un recorrido identificable y recuperable sin mezclar originales y derivados.

---

# 22. PRIORIDAD 10 — Jobs y multimedia

## Objetivo

Automatizar el tratamiento sin perder control.

## Estados recomendados

- detectado;
- validado;
- en cola;
- preparando;
- extrayendo audio;
- transcribiendo;
- normalizando;
- extrayendo conocimiento;
- validando;
- resolviendo;
- preparado para revisión;
- aprobado;
- ingerido;
- fallido;
- cancelado;
- en cuarentena.

## Checklist

- [ ] Estado único.
- [ ] Transiciones válidas.
- [ ] Idempotencia.
- [ ] Lock por fuente.
- [ ] Reintentos.
- [ ] Backoff.
- [ ] Cancelación.
- [ ] Pausa.
- [ ] Logs.
- [ ] Recuperación tras reinicio.
- [ ] Límites de RAM.
- [ ] Límites de CPU.
- [ ] Concurrencia.
- [ ] Modelo Whisper.
- [ ] Integración con review.
- [ ] Integración con Nextcloud.
- [ ] Acciones del panel.
- [ ] Permisos.

## Criterio de cierre

Un fallo o reinicio no duplica fuentes ni pierde el estado del trabajo.

---

# 23. PRIORIDAD 11 — Replicabilidad

## Objetivo

Reconstruir el sistema sin conocimiento oral.

## Checklist

- [ ] Requisitos.
- [ ] Validación previa.
- [ ] Entornos Python.
- [ ] Dependencias fijadas.
- [ ] Configuración de ejemplo.
- [ ] Directorios.
- [ ] Permisos.
- [ ] Bases locales.
- [ ] Servicios.
- [ ] Healthchecks.
- [ ] Actualización.
- [ ] Rollback.
- [ ] Backup inicial.
- [ ] Modo de prueba.
- [ ] Modo VM105.
- [ ] Modo externo.
- [ ] Opción Docker evaluada.
- [ ] Guía de desinstalación.
- [ ] Prueba en entorno limpio.

## Criterio de cierre

Una instalación limpia puede levantarse siguiendo únicamente la documentación.

---

# 24. PRIORIDAD 12 — Refactorización y mantenibilidad

## Objetivo

Reducir fragilidad sin alterar la funcionalidad.

## Checklist

- [ ] Paquetes instalables.
- [ ] Eliminar hacks de rutas.
- [ ] Centralizar configuración.
- [ ] Validar configuración al arrancar.
- [ ] Centralizar logging.
- [ ] Separar rutas y lógica.
- [ ] Excepciones concretas.
- [ ] Tipos.
- [ ] Linting.
- [ ] Dependencias fijadas.
- [ ] Escaneo de vulnerabilidades.
- [ ] Eliminar backups del repo.
- [ ] Actualizar `.gitignore`.
- [ ] Definir contribución.
- [ ] Revisar `shared/`.
- [ ] Vendorizar frontend cuando corresponda.

## Criterio de cierre

El refactor pasa las mismas pruebas y no cambia los resultados del pipeline.

---

# 25. PRIORIDAD 13 — Rendimiento y escalabilidad

## Objetivo

Optimizar únicamente los límites demostrados.

## Medición previa

- tiempo por etapa;
- RAM;
- CPU;
- disco;
- consultas;
- tamaño de grafo;
- jobs diarios;
- tasa de error;
- tiempos de espera;
- bloqueos SQLite.

## Posibles acciones

- índices Neo4j;
- caché de metadatos;
- paginación;
- consultas limitadas;
- lectura perezosa;
- procesamiento externo;
- múltiples workers;
- PostgreSQL o Redis;
- GPU;
- exportación incremental.

## Criterio de cierre

Cada optimización debe mostrar una mejora medida y no reducir la calidad o trazabilidad.

---

# 26. Quality gates obligatorios

## Gate A — Merge a `main`

- [ ] Tests.
- [ ] Lint.
- [ ] Tipos.
- [ ] Secret scan.
- [ ] Documentación.
- [ ] Changelog.
- [ ] Sin credenciales.
- [ ] Revisión de migraciones.

## Gate B — Despliegue

- [ ] Commit identificado.
- [ ] Backup.
- [ ] Configuración validada.
- [ ] Servicios saludables.
- [ ] Endpoints.
- [ ] Logs.
- [ ] Rollback de versión.

## Gate C — Escritura en Neo4j

- [ ] Fuente identificada.
- [ ] Payload válido.
- [ ] Procedencia completa.
- [ ] Quality report.
- [ ] Dry-run.
- [ ] Backup.
- [ ] Autorización.
- [ ] Rollback disponible.
- [ ] Auditoría posterior.

## Gate D — Acceso de jugadores

- [ ] Login.
- [ ] Sesión.
- [ ] Rol.
- [ ] Filtros.
- [ ] Tests de fuga.
- [ ] API protegida.
- [ ] Búsqueda protegida.
- [ ] Logs.

---

# 27. Definición global de terminado

Una función se considera terminada cuando:

- está implementada;
- tiene pruebas;
- está documentada;
- está desplegada cuando corresponde;
- tiene healthcheck;
- registra errores;
- no expone secretos;
- respeta permisos;
- conserva trazabilidad;
- dispone de rollback si modifica datos;
- aparece en el changelog;
- su estado se refleja en este dosier.

---

# 28. Riesgos principales

| Riesgo | Nivel | Mitigación |
|---|---|---|
| Ingesta de falsos positivos | Alto | Corpus, calidad, revisión, dry-run |
| Duplicados | Alto | Resolución y dedupe antes de ingesta |
| Falta de rollback | Crítico | Prioridad 1 |
| Fuga de spoilers | Alto | Auth y permisos RPG |
| Documentación contradictoria | Medio-alto | Prioridad 0 |
| Estado VM distinto de `main` | Alto | Registrar commit desplegado |
| Pérdida de jobs | Medio | Persistencia e idempotencia |
| Montaje Nextcloud caído | Medio | Healthcheck y reintentos |
| Dependencia de CDN | Medio | Vendorizar o verificar integridad |
| Falta de CI | Medio-alto | GitHub Actions |
| Topología en repo público | Medio | Sanitización |
| Escalado prematuro | Medio | Medir antes de migrar |
| Dependencias LlamaIndex cambiantes | Medio | Versionado y pruebas |
| Corrección ASR destructiva | Alto | Normalización determinista y timestamps |

---

# 29. Decisiones que no conviene tomar todavía

- [ ] No desbloquear ingesta masiva.
- [ ] No fusionar duplicados automáticamente.
- [ ] No migrar SQLite sin métricas.
- [ ] No sustituir todo por LLM.
- [ ] No eliminar las reglas deterministas.
- [ ] No migrar VM105 a Docker sin necesidad.
- [ ] No añadir un frontend complejo por estética.
- [ ] No paralelizar Whisper en VM105 sin medir RAM.
- [ ] No permitir acciones de revisión sin usuarios.
- [ ] No desarrollar modo jugador antes de definir permisos.
- [ ] No mezclar documentación pública y secretos operativos.
- [ ] No marcar “cerrado” solo porque exista código.

---

# 30. Versiones sugeridas

## v0.2.5b — Consolidación documental

- estado real;
- documentación coherente;
- pruebas verificadas;
- tag y changelog;
- sin cambios funcionales grandes.

## v0.2.6 — Seguridad de datos y primera ingesta

- backup;
- restore;
- rollback;
- benchmark de extractor;
- primera ingesta controlada.

## v0.2.7 — Calidad del grafo

- migraciones;
- dedupe;
- metadatos;
- relaciones históricas;
- auditoría periódica.

## v0.3 — Usuarios y revisión

- login;
- sesiones;
- roles;
- rutas protegidas;
- acciones de revisión;
- auditoría de usuario.

## v0.4 — RPG y workspaces

- narrador;
- jugador;
- visibilidad;
- spoilers;
- personajes;
- campañas;
- Nextcloud estructurado.

## v0.5 — Automatización y replicabilidad

- jobs completos;
- multimedia;
- procesamiento externo;
- instalador;
- despliegue reproducible;
- CI/CD maduro.

---

# 31. Checklist maestra resumida

## Cierre inmediato

- [x] Confirmar commit en VM105 — `1fd94b85` (v0.2.5b, 2026-07-10). Verificado 2026-07-13.
- [x] Ejecutar pruebas — 196 recopilados, 155 aprobados, 41 fallidos (deuda técnica API). Verificado 2026-07-13.
- [x] Corregir documentación — docs/06 (visor en prod), docs/05 (tests), docs/02 (fecha), CHANGELOG, INDEX, README. Verificado 2026-07-13.
- [ ] Actualizar roadmap.
- [x] Actualizar changelog — sección Unreleased con auditoría 2026-07-13.
- [x] Añadir este dosier — presente en `origin/main` desde `ffaf84c`.

## Seguridad de datos

- [ ] Backup.
- [ ] Restore.
- [ ] Rollback.
- [ ] Audit-graph antes y después.
- [x] Bloqueo de ingesta por defecto — guard doble capa confirmado, `S9K_ALLOW_REAL_INGEST` no activa. Verificado 2026-07-13.

## Calidad

- [ ] Corpus.
- [ ] Benchmark.
- [ ] Dedupe.
- [ ] Evidencia.
- [ ] Umbrales.
- [ ] Regresiones.

## Demostración real

- [ ] Fuente pequeña.
- [ ] Dry-run.
- [ ] Ingesta.
- [ ] Visor.
- [ ] Auditoría.
- [ ] Rollback.

## Producto

- [ ] Login.
- [ ] Usuarios.
- [ ] Revisión.
- [ ] Narrador.
- [ ] Jugador.
- [ ] Workspaces.

## Operación

- [ ] Nextcloud.
- [ ] Jobs.
- [ ] Multimedia.
- [ ] Healthchecks.
- [ ] Replicabilidad.
- [ ] CI.

---

# 32. Próximo bloque recomendado

El siguiente trabajo debe ser **Prioridad 0 + Prioridad 1**, sin añadir nuevas funcionalidades:

1. verificar `main` y VM105;
2. ejecutar y registrar pruebas;
3. corregir toda la documentación contradictoria;
4. crear el runbook de backup y restore;
5. demostrar rollback por fuente;
6. mantener la ingesta real bloqueada.

Después debe abordarse la **calidad del extractor** y realizarse una **primera ingesta real controlada**.

Solo después se recomienda iniciar autenticación, acciones del panel y modo jugador.

---

# 33. Resultado de proyecto que debe perseguirse

S9 Knowledge estará en un estado sólido cuando sea posible afirmar y demostrar:

> Una fuente entra desde un workspace identificado, se procesa de manera reproducible, conserva su evidencia, genera candidatos validados, presenta únicamente las dudas a una persona autorizada, produce un payload trazable, se ingiere después de un backup, aparece en el visor con los permisos adecuados y puede retirarse completamente sin afectar al resto del conocimiento.

Ese es el punto en el que el proyecto deja de ser una suma de componentes funcionales y se convierte en una plataforma fiable de conocimiento RPG.

---

## Historial del dosier

### 2026-07-13 — Auditoría y cierre fase 0A/0B

- Creación inicial del dosier.
- Consolidación de los dos informes aportados.
- Contraste con documentación de `main`.
- Identificación de contradicciones.
- Definición del estado por componente.
- Creación del plan priorizado y checklist.
- Auditoría verificable de VM105: commit `1fd94b85` (v0.2.5b), Neo4j 199 nodos, visor HTTP 200, tests 155/196.
- **Dictamen fase 0A: CERRADA CON EXCEPCIONES DOCUMENTADAS** — Ollama no disponible, 41 tests fallidos (debt técnico), sin backup automático.
- **Dictamen fase 0B: CERRADA CON EXCEPCIONES DOCUMENTADAS** — Documentación corregida y PR abierto; roadmap pendiente de actualización.
- Informe de baseline: [`docs/24-vm105-baseline-and-verification.md`](24-vm105-baseline-and-verification.md).
