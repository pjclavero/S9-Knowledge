# S9 Knowledge — Documentación consolidada

**Fecha:** 2026-07-27

Este documento consolida en un único lugar los 57 informes y notas técnicas que
antes vivían como archivos markdown sueltos en `docs/` (los numerados 00 a 53,
`INDEX.md`, `project dossier and checklist.md`, y otros dosieres sin numerar
sobre el motor de relaciones). Los originales se han movido, sin modificar, a
`docs/archivados/`, donde quedan disponibles como referencia primaria con todo
su detalle (tablas completas, comandos, cifras exactas). Este documento es una
**síntesis fiel** pensada para poder entender el proyecto de un vistazo, sin
tener que abrir 57 archivos.

No se han tocado los subdirectorios `docs/v3/`, `docs/current/` ni
`docs/experiments/`: siguen donde estaban. Única excepción: el capítulo 11,
añadido el 2026-08-05 como nota de continuidad breve — no una síntesis
detallada — para que quien lea solo este documento sepa que el desarrollo
siguió después del 2026-07-27 y dónde está la fuente viva.

## Índice

1. [Visión y arquitectura](#cap1)
2. [Estado y despliegue en VM105](#cap2)
3. [Motor de datos y calidad del extractor de entidades](#cap3)
4. [Motor de relaciones](#cap4)
5. [Ingesta y transcripción multimedia](#cap5)
6. [Revisión, benchmarks y calibración con IA externa](#cap6)
7. [Seguridad, usuarios y acceso externo](#cap7)
8. [Operaciones, backup y healthchecks](#cap8)
9. [Despliegues RC y regresiones de despliegue](#cap9)
10. [Auditoría, onboarding y dosier del proyecto](#cap10)
11. [Nota de continuidad — desarrollo posterior a este consolidado (V3)](#cap11)

---

<a id="cap1"></a>
## 1. Visión y arquitectura

Capítulo de fundamentos: qué es S9 Knowledge, por qué existe, cómo está
estructurado el repositorio y cuál es el modelo arquitectónico (fuentes →
data-engine → Neo4j → visor/panel). También cubre las fases previstas del
proyecto y el mecanismo de intercambio de conocimiento con sistemas externos
(paquetes de conocimiento). Es la base conceptual sobre la que se apoyan todos
los demás capítulos.

<a id="d00"></a>
### 00 · Visión
*origen: 00-vision.md*

S9 Knowledge convierte material heterogéneo de campañas de rol (PDFs, textos,
audios de sesión, vídeos de YouTube, páginas web, notas manuales) en un grafo
de conocimiento consultable, alojado en el homelab Sección 9, **self-hosted**
(sin servicios cloud). Objetivo: una memoria viva de cada campaña (personajes,
criaturas, lugares, facciones, objetos, eventos, combates, sesiones y sus
relaciones), con evolución temporal y **conocimiento por personaje** (cada
jugador ve solo lo que su personaje sabe). Principios rectores: Neo4j es la
única fuente de verdad (el visor solo presenta); trazabilidad total en cada
nodo/relación (documento, tipo de fuente, hash, versión de extractor y
prompt); modelo **multi-bóveda** (cada campaña es un `workspace` aislado);
nada de APIs externas expuestas (Neo4j/Ollama nunca públicos); ningún cambio
en producción sin backup y prueba mínima.

<a id="d01"></a>
### 01 · Arquitectura
*origen: 01-architecture.md*

Diagrama de flujo: las fuentes entran a una cola de trabajos (`state/jobs.db`)
y llegan al **data-engine**, que transcribe audio con faster-whisper, extrae
entidades/relaciones con Ollama (`qwen2.5:7b`), valida contra `rpg_schema.py`
y escribe en Neo4j con `ingest_rpg.py`, siempre con trazabilidad. Desde Neo4j
(grafo multi-workspace) se alimentan SilverBullet (edición manual en
Markdown) y, en el futuro, un visor web y un panel de gestión. Tabla de
componentes en VM105 (`192.168.1.205`): Neo4j (`neo4j-knowledge`, bolt 7687,
producción), Ollama (`192.168.1.157:11434`, producción), data-engine
(`/opt/knowledge-services/property-graph`, producción), SilverBullet
(contenedores `silverbullet-*`, producción), cola de trabajos SQLite y
almacén de accesos SQLite (implementados), visor/panel (en aquel momento
pendiente; hoy desplegado, ver capítulo 2), IA externa NVIDIA en modo sombra
(implementada, Fase A). Flujo: fuente → job pendiente → transcripción/extracción
LLM → escritura Neo4j con trazabilidad → visibilidad por sesión/personaje
(pendiente en visor/API en el momento de redacción).

<a id="d03"></a>
### 03 · Fases
*origen: 03-phases.md*

Tabla resumen de las 7 fases previstas del proyecto: Fase 0 — motor de datos
(extracción→Neo4j, schema 1.5.0, prompt 1.4.0): **HECHO**; Fase 1 — orden y
versionado (este repositorio Git): **EN CURSO**; Fase 2 — fuentes externas
(cola, audio, YouTube, web): **DISEÑADO/parcial**; Fase 3 — acceso (usuarios,
personajes, permisos): **BASE IMPLEMENTADA**; Fase 4 — visor web de solo
lectura: **PENDIENTE** en el momento de redacción (hoy implementado, ver
capítulos 2 y 8); Fase 5 — panel de gestión: **PENDIENTE**; Fase 6 — acceso
externo controlado: **PENDIENTE**. Criterio de "hecho": código que compila,
tests que pasan, documentación existente y prueba mínima reproducible; nada se
declara resuelto sin prueba real. El documento aclara que el estado vigente
autoritativo vive en `02-current-state.md` y `project-status.yaml`, no en este
documento de fases.

<a id="d04"></a>
### 04 · Estructura del repositorio
*origen: 04-repository-structure.md*

Árbol del repositorio: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `docs/`
(incluyendo `docs/current/` con diseños ya generados), `data-engine/` (copia
del motor: `app/schemas`, `app/prompts`, `ingest_rpg.py`, `jobs/job_store.py`,
`access/access_store.py`, `audio/`, `youtube/`, `exporters/`, tests, config,
docker, requirements), `viewer/`/`shared/`/`deployments/` (en el momento de
redacción, carpetas futuras vacías con `.gitkeep`; hoy implementadas), y
`scripts/`/`examples/`. Lista explícita de lo que **no** está en el repo por
`.gitignore`/rsync: entornos virtuales, cachés, estado de runtime
(`logs/`, `state/`, `output/`, `staging/`), bases de datos SQLite de runtime
(`jobs.db`, `access.db`, etc.), secretos (`.env`, tokens, certificados) y
datos fuente pesados (PDFs, audio/vídeo, dumps de Neo4j). El código de los
módulos (`job_store.py`, `access_store.py`) sí se versiona; solo se excluyen
las bases de datos que generan en runtime.

<a id="d23"></a>
### 23 · Knowledge Packages: export/import y procesamiento externo
*origen: 23-knowledge-packages.md*

Módulo `data-engine/app/review/export_import.py` (actualizado 2026-07-12).
Regla de oro: *"Externo propone. S9 Knowledge valida. Neo4j solo recibe
aprobado."* Nada externo escribe jamás directamente en Neo4j; todo paquete
entrante pasa por `validate → resolve → auto_decide → approved_payload →
ingest-approved (dry-run/guard)`. Cuatro tipos de paquete: **KnowledgePackage**
(export/backup lógico de un workspace, con manifest, metadata, entidades,
relaciones, alias, evidencia y `approved_payload` embebido); **ExternalReviewRequest**
(petición de ayuda a un sistema externo más potente — LLM grande, OCR pesado —
con sanitización obligatoria de rutas internas, IPs privadas, tokens y
credenciales); **ExternalReviewResponse** (el externo devuelve *propuestas*,
nunca conocimiento aprobado — el auto-decisor nunca las autoaprueba
directamente, motivo `external_origin`); **ImportedCandidatePackage**
(candidatos generados fuera del servidor, validados y marcados
`origin="imported"`, tratados como cualquier candidato local). Dos modos de
procesamiento: **local** (VM105 hace todo, siempre disponible) y **externo
asistido** (ayuda con transcripción pesada/OCR/LLM grande, pero S9K siempre
revalida localmente). El guard de `ingest-approved` exige `--dry-run` por
defecto y `S9K_ALLOW_REAL_INGEST=true` para escritura real, y rechaza
paquetes sin workspace/schema_version, entidades sin evidencia, relaciones
inválidas, timestamps rotos, y origen externo sin validación local.

---

<a id="cap2"></a>
## 2. Estado y despliegue en VM105

Este capítulo reúne todo lo relacionado con el entorno de producción físico
(VM105), el modelo de despliegue por releases inmutables, y los informes de
auditoría/preparación que fueron fijando el estado verificado del proyecto a
lo largo del tiempo (fase 0, Prioridad 1, instalación replicable, despliegue
reproducible). Cierra con el documento canónico de estado actual, que resume
la fuente de verdad vigente.

<a id="d08"></a>
### 08 · Despliegue en VM105
*origen: 08-deployment-vm105.md*

Referencia del entorno de producción: host VM105 "common", LAN
`192.168.1.205` (Proxmox VE 8.4), proyecto en
`/opt/knowledge-services/property-graph`, Python en venv (no versionado, se
recrea con `requirements.lock`), Neo4j en contenedor `neo4j-knowledge` (bolt
`127.0.0.1:7687`), Ollama remoto en `192.168.1.157:11434` (modelo
`qwen2.5:7b`), SilverBullet en contenedores `silverbullet-*`. El repo **no**
despliega nada por sí mismo: solo documenta el estado. Reglas de operación:
no exponer Neo4j ni Ollama a Internet, no versionar secretos ni datos de
campaña, cambios en producción siempre con backup previo y prueba mínima.

<a id="d22"></a>
### 22 · Instalación y replicabilidad (preparada, no completada)
*origen: 22-installation-and-replicability.md*

Actualizado 2026-07-12. Diseño documentado, **instalación replicable
completa no implementada** en ese momento. Filosofía: el núcleo no debe
depender obligatoriamente de VM105 ni de Nextcloud; VM105 es solo un
*deployment* concreto. Tres modos de instalación futuros: **A — con
Nextcloud** (como VM105), **B — sin Nextcloud** (carpetas locales
`S9K_DATA_ROOT`), **C — híbrido**. Tabla extensa de variables de
configuración (`S9K_ALLOW_REAL_INGEST`, `S9K_REVIEW_EXTRACTOR`,
`S9K_NEO4J_*`, `S9K_MEDIA_*`, `S9K_JOBS_DB`, etc.) con su estado
(implementada/preparada/documentada). Auditoría de hardcodes: rutas
aceptables como defaults configurables (`/opt/knowledge-services`,
`/mnt/nextcloud-rol`), pendientes no bloqueantes (`_REPO_ROOT` calculado por
posición de fichero, visor asumiendo `output/reviews/` relativo a la raíz).
Política de almacenamiento: Nextcloud = almacén principal recuperable, VM105
= procesamiento/cola/estado técnico, Neo4j = grafo vivo aprobado, Git =
código y documentación. Explícitamente fuera de alcance en esa fase:
instalador completo, wizard, Docker genérico, gestión web de workspaces.

<a id="d24"></a>
### 24 · Baseline VM105 y Verificación Fase 0A
*origen: 24-vm105-baseline-and-verification.md*

**Informe de auditoría verificable, 2026-07-13**, estrictamente de solo
lectura. Commit auditado: `1fd94b85` (tag `v0.2.5b`, 2026-07-10); `origin/main`
7 commits documentales por delante; working tree limpio. Qué funciona
realmente: visor web (FastAPI/uvicorn :8088, HTTP 200 en todos los endpoints),
Neo4j 5.26.0 Community (healthy, 199 nodos, 140 relaciones, solo localhost),
rclone/Nextcloud (5 workspaces montados read-only), guard de ingesta doble
capa activo y verificado, glosario ASR (1044 términos), jobs DB íntegra.
Solo en código, sin desplegar como servicio: worker multimedia, worker de
jobs, extractor LLM/híbrido (requieren Ollama). Tests: **196 recopilados, 155
aprobados, 41 fallidos** (deuda técnica de API, no afecta al guard de
ingesta). Ollama: remoto en ia-server (accesible, modelo disponible) pero
endpoint hardcodeado en `llm_extractor.py` en vez de en `.env` — reclasificado
como "Clasificación A: remoto configurado y accesible" tras corrección
(inicialmente se había reportado como hallazgo ALTO "no disponible", error
corregido en fase 0B). Neo4j: 14 labels, 28 tipos de relación, ~87 nodos
históricos sin `source_id`/`source_kind`. Seguridad: puertos Neo4j cerrados a
localhost desde 2026-07-12, acceso externo con Basic Auth vía nginx VM104,
sin backup automatizado de Neo4j (marcado Prioridad 1). Dictamen: **FASE 0A
CERRADA CON EXCEPCIONES DOCUMENTADAS** (Ollama config pendiente, 41 tests
fallidos, sin backup automatizado, tests del visor rotos por
`ModuleNotFoundError`). Fuera de alcance de fase 0: backup/restore/rollback
(Prioridad 1), benchmark del extractor (Prioridad 2), CI/CD (Prioridad 3),
primera ingesta real (Prioridad 4), login, permisos RPG, modo jugador.

<a id="d29"></a>
### 29 · Informe de Preparación — Prioridad 1
*origen: 29-priority-1-readiness-report.md*

Preparación 2026-07-13, ejecución 2026-07-13–14. Inventario de producción:
Neo4j 5.26.0 Community, contenedor `neo4j-knowledge`, volúmenes bind-mount,
3.1 MB de datos, 24 GB libres de 38 GB. Laboratorio aislado (`neo4j-lab`,
puertos 7475/7688): backup con `neo4j-admin database dump` (13.8 KB,
checksum SHA-256, éxito), restore en volumen nuevo (3 nodos antes = 3 después,
éxito). **Actualización 2026-07-13: ejecución completada** — backup real de
producción **EJECUTADO** (132 KB, SHA256 verificado), restore en instancia
aislada **VERIFICADO** (199 nodos, 140 relaciones idénticos a producción),
rollback por `source_id` **VALIDADO** en laboratorio con datos sintéticos,
copia a yggdrasil **TRANSFERIDA Y VERIFICADA POR CHECKSUM** (2026-07-14,
permisos 700) — **corrección 2026-08-09: `yggdrasil` es el hipervisor que
ejecuta VM105, así que esa copia NO es off-host; sigue en el mismo chasis y
el P0 de replicación externa sigue abierto (ver docs/52 y docs/53)**.
Pendiente para P1.1: script transaccional de
rollback con `--dry-run`, timer systemd de backup periódico. Dictamen: **Prioridad
1 completada** operativamente (dictamen definitivo en docs/32, capítulo 8).

<a id="d30"></a>
### 30 · Informe coordinador — Cierre Fase 0 y Prioridad 1
*origen: 30-coordinator-final-report.md*

Fecha 2026-07-13, consolida la auditoría distribuida que cerró fases 0A/0B y
preparó Prioridad 1. PR #3 fusionado (commit `9dd92b4d`) corrige dos
afirmaciones erróneas del informe inicial: (1) Ollama reclasificado de "no
disponible" a "remoto configurado y accesible" (Clasificación A); (2) la
frase "ningún fallo afecta a seguridad" se sustituye en 6 sitios por una
formulación más precisa sobre fiabilidad funcional. VM105 sincronizado por
fast-forward (`1fd94b8` → `9dd92b4`, 11 commits documentales, sin cambios de
código, sin reinicio de servicios). Análisis de los 41 tests fallidos:
**2 causas raíz** identificadas — CR-1 (ALTA): un `sys.path.insert()`
hardcodeado en `test_ingest_semantics.py` hacía que pytest importara módulos
del directorio antiguo `property-graph/app/` en vez de `data-engine/app/`,
produciendo 39 fallos + 6 errores de colección como **falsos negativos** (el
código de producción era correcto); CR-2 (MEDIA): `@lru_cache` de
`get_settings()` no se limpiaba entre tests del visor, causando 4 fallos por
estado compartido. Backup/restore/rollback: mismo contenido que docs/29,
scripts creados (`neo4j-backup.sh`, `neo4j-restore.sh`,
`neo4j-rollback-dryrun.sh`), rollback por `source_id` con diseño completo en 5
fases pero implementación de ejecución pendiente (~87 nodos históricos sin
`source_id` quedan fuera del alcance del rollback selectivo). Dictamen final:
Fase 0 **cerrada con excepciones documentadas**, análisis de tests
**completo**, Prioridad 1 **preparada**. Recomienda no iniciar la primera
ingesta real hasta tener backup de producción verificado.

<a id="d47"></a>
### 47 · Despliegue reproducible y recuperación (Tarea B)
*origen: 47-reproducible-deployment.md*

Rama `feat/reproducible-deployment`, **implementado**. Introduce un modelo de
**releases inmutables** con symlink atómico (similar a Capistrano/Kamal):
`/opt/s9-knowledge/releases/<id>/` con `current` apuntando a la release
activa; estado mutable fuera de las releases en `/var/lib/s9-knowledge/`
(auth.db, jobs, state, output, backups); configuración y secretos en
`/etc/s9-knowledge/` (EnvironmentFiles 0600). Ventaja: el cambio de symlink es
atómico, sin ventanas de inconsistencia, y el rollback es instantáneo (cambiar
el symlink de vuelta, sin reinstalar dependencias). Scripts de operación:
`preflight.sh` (verificación de solo lectura previa al despliegue, códigos de
salida 0/1/2/3), `deploy.sh` (por defecto dry-run; flujo de 16 pasos: lock,
resolver commit, crear release, instalar venv, manifest, backup+migración de
`auth.db`, symlink atómico, reinicio de systemd, verificación, rollback
automático si falla), `verify-deployment.sh` (comprobaciones post-despliegue:
symlink, venv, imports, servicio activo, Neo4j, endpoint HTTP), y
`rollback-release.sh` (vuelve a la release anterior, con distinción explícita
de que Neo4j y SQLite **no** se restauran automáticamente en rollback —
requiere restauración manual del backup si hay incompatibilidad de esquema).
Cada release genera un `manifest.json` sin secretos con `release_id`,
`git_commit`, huella de dependencias y checksums. Incluye roles Ansible
(`common`, `data_engine`, `viewer`, `auth`, `systemd`, `healthchecks`) e
integración en CI (`deployment-validation`: sintaxis, shellcheck, yamllint,
comprobación de secretos). El despliegue productivo en VM105 **no estaba
ejecutado** en el momento de este documento; requería aprobación explícita
antes de tocar `/opt/knowledge-services/`.

<a id="d50deploy"></a>
### 50 · Continuidad de estado y activación correcta de releases
*origen: 50-deploy-state-continuity.md*

Corrige los defectos estructurales que llevaron a **rechazar la RC1**
(`deploy-v0.3.0-rc1` / `d9af2d3`, marcada `DO NOT DEPLOY`): la unit systemd
versionada seguía apuntando al layout legacy, `deploy.sh` no garantizaba que
el proceso vivo usara `current`, el flujo podía inicializar una `auth.db`
vacía durante una actualización, no existía un `viewer.env` productivo
compatible ni una migración legacy→state-root validada y atómica. Se
introduce `detect_state.py` (clasifica el estado en 6 categorías: LEGACY,
NEW, MIXED_EQUIVALENT, CONFLICTING, EMPTY, CORRUPT — bloquea en modo upgrade
si `auth` está vacía/conflictiva/corrupta, o si hay 0 administradores
activos), `migrate_sqlite.py` (migrador atómico con modo PLAN por defecto,
`PRAGMA integrity_check`, comparación de conteos, `os.replace` atómico,
idempotente), `validate_deploy.sh` (gates sobre `viewer.env` y la unit
systemd — bloquea si la unit referencia el layout legacy o si el secreto CSRF
es un placeholder conocido, corto o de baja entropía), y
`verify_release_identity.py` (comprueba que el **proceso vivo**, no solo el
symlink, ejecuta la release autorizada, inspeccionando `/proc/<pid>/cwd` y el
`.venv` — si no coincide, `deploy.sh` hace auto-revert). El `deploy.sh` pasa a
tener 17 pasos con gates. El rollback antes de "externalizar" el estado es
simple; después de cruzar ese punto de no retorno, un rollback directo a una
release legacy queda **bloqueado** (requiere una "bridge release"). Validado
con un laboratorio de 25 escenarios (`test_state_continuity.py`). Estado:
corrección lista para revisión; **no despliega, no crea tag nuevo, no toca
producción** — la RC2 solo se crearía tras aprobación y merge.

<a id="d02"></a>
### 02 · Estado actual (documento canónico)
*origen: 02-current-state.md*

**Fecha de actualización: 2026-07-18.** Versión productiva `0.3.0-rc5.1`
(tag `deploy-v0.3.0-rc5.1`, commit `47bc3147...` = `main`). Estado verificado
por SSH en VM105: visor (`s9-knowledge-viewer.service` activo, FastAPI/uvicorn
en `127.0.0.1:8088`), **login propio del visor** (Basic Auth retirada del
proxy, 1 administrador activo `s9admin`), acceso externo por
`https://knowledge.seccionnueve.duckdns.org` (HTTPS, sin Basic Auth — auth en
la app), Neo4j con **199 nodos / 140 relaciones** (puertos solo
`127.0.0.1`), cola de jobs SQLite con 1 job, worker de cola disponible pero
sin ejecución de ingesta real, healthcheck instalado y timer horario
(`OnCalendar=hourly`, `Persistent=true`), backups en `/var/lib/s9-knowledge/`
(0700) con backup Neo4j validado, **0 ingestas aplicadas**
(`S9K_ALLOW_REAL_INGEST` sin definir). Despliegue: modelo de releases
inmutables activadas por symlink atómico; historial de candidatas: RC4
(`91bdc51`, desplegada 2026-07-17, hoy release *previous*/rollback), RC5
(`bcc3a59`, candidata **no desplegada**, cutover abortado antes de
activarse, conservada para auditoría), **RC5.1** (`47bc314`, **activa en
producción**, con la regresión forward-ref corregida — ver capítulo 9).
Motor de datos: pipeline de revisión completo (`segment→classify→extract→
validate→resolve→decide`), ingesta controlada solo dry-run salvo doble
guard, IA externa NVIDIA en modo sombra, burst orchestrator Fase B1
implementado (proveedores reales B2/B3 pendientes). Visor: rutas
`/login`, `/graph`, `/jobs`, `/reviews`, con login/roles/sesiones/CSRF.
Tests y CI: suite verde, **912 tests** recopilados (deploy 149, viewer 296,
data-engine 467), CI de GitHub Actions en verde en `main`. Deuda técnica
conocida: nombre de `release_id` con doble guion (cosmético), healthcheck de
`ollama`/`nextcloud_rclone` como `UNKNOWN` (integraciones opcionales no
usadas), calidad del extractor de relaciones aún por debajo de umbral
(ingesta real bloqueada), nodos históricos sin `source_id`, duplicados sin
fusionar. Bloqueos: **primera ingesta real no autorizada** (doble guard
activo), proveedores reales de burst pendientes. Siguiente prioridad: P0
contratos de review/ingest, P1 panel de revisión + permisos RPG + visibilidad
por personaje, P2 primera ingesta controlada + worker real, P3 limpieza
histórica + restore periódico. La fuente de verdad se deriva de `main`, tags
de release, manifiestos de la release activa, CI y verificación SSH de
producción — nunca se copia de informes anteriores.

---

<a id="cap3"></a>
## 3. Motor de datos y calidad del extractor de entidades

Este capítulo cubre el núcleo del pipeline de extracción de **entidades**
(personajes, lugares, facciones, objetos...): su arquitectura, el proceso de
benchmarking riguroso que se le aplicó (Prioridad 2 y 2.1), las mejoras de
calidad implementadas, y las herramientas de auditoría/limpieza del grafo. El
hilo conductor es la evolución medida y honesta de la calidad del extractor:
de "no evaluado" a "F1 de entidades 0.846 con revisión humana total
impuesta por código", mientras que las relaciones (tratadas en el capítulo 4)
quedan siempre excluidas de la autoaprobación.

<a id="d05"></a>
### 05 · Motor de datos (data-engine)
*origen: 05-data-engine.md*

Código en `data-engine/app/`. Módulos principales: `schemas/rpg_schema.py`
(modelos Pydantic, allowlists de tipos/relaciones, vocabularios, v1.5.0),
`prompts/rpg_extraction_prompt.py` (v1.4.0), `ingest_rpg.py` (pipeline
completo, CLI `property-graph-rpg`), `jobs/job_store.py` (cola SQLite),
`access/access_store.py` (usuario-personaje, permisos, audit log), `audio/`
(faster-whisper), `youtube/`, `exporters/` (a SilverBullet/Markdown). CLI con
flags para workspace, fuente (PDF/texto/imagen), perfil, `source-id`/`source-kind`,
capa de conocimiento, visibilidad, metadatos de sesión, `--dry-run`,
`--no-neo4j`. Modelo de grafo: nodos (Character, Creature, Location, Faction,
Object, Event, Session, Document...), relaciones narrativas/de sesión/de
fuente/de **conocimiento por personaje** (HAS_SEEN, HAS_FOUGHT,
HAS_HEARD_ABOUT...), trazabilidad completa en todos (workspace, source_id,
source_kind, source_hash, extractor_version, prompt_version, knowledge_layer,
visibility, review_status). Nota de auditoría añadida el 2026-07-13: la cifra
original "8/8 tests" quedó obsoleta; en el commit `1fd94b85` la suite real
tenía 196 tests recopilados, 155 aprobados, 41 fallidos (deuda técnica de API,
detallada en docs/24).

<a id="d11"></a>
### 11 · Revisión de calidad de datos (workspace "leyenda")
*origen: 11-data-quality-review.md*

Documento de solo lectura: durante una prueba del visor contra Neo4j real se
detectaron dos problemas de calidad sin corregir. (1) Relaciones semánticas
incorrectas: aristas `HAS_FOUGHT` con destino un nodo `Location`/`Region`
("luchar contra un lugar" no tiene sentido — síntoma de sujeto/objeto mal
asignado en la extracción); ya corregido a nivel de esquema/validación para
futuras ingestas (`_check_relation_semantics` en `ingest_rpg.py`), pero los
datos ya existentes en Neo4j **no** se corrigieron. (2) Posible duplicado:
`Tamori Family` y `Familia Tamori` como dos nodos distintos, ambos
relacionados con `Rejn Clan` — mismo concepto extraído dos veces en idiomas
distintos. Ninguno de los dos problemas se corrigió en esta fase; el
documento registra las consultas Cypher de diagnóstico usadas y remite a un
script de auditoría automatizada de solo lectura,
`data-engine/app/tools/audit_duplicates.py` (detecta candidatos a duplicado
por nombre normalizado, similitud de tokens `difflib` con umbral 0.75, y
solape de `source_document`/`source_pages`; nunca escribe en Neo4j; genera
`viewer/reports/duplicate_candidates.md`).

<a id="d28"></a>
### 28 · Migraciones del Grafo y Rollback por source_id
*origen: 28-graph-migrations-and-rollback.md*

**Diseño completo, implementación pendiente** (en el momento de redacción;
cerrado posteriormente por docs/53, ver más abajo). Modelo de procedencia:
`source_id`, `source_kind`, `workspace` en cada nodo/relación, asignados por
`set_doc_context()` en `ingest_rpg.py`. Tres categorías de nodos: exclusivos
de una fuente (eliminables en rollback), compartidos entre fuentes (solo se
desvincula la contribución, no se elimina el nodo), e históricos sin
`source_id` (~87 nodos estimados, no afectados por rollback selectivo, solo
eliminables por restore completo). Diseño del rollback en 5 fases: análisis
previo (dry-run, solo lectura), listado de impacto legible, aprobación
explícita del operador, ejecución (Cypher de eliminación de relaciones y
nodos exclusivos, desvinculación de nodos compartidos — **implementación
pendiente** en ese momento), y auditoría post-rollback. El script de dry-run
(`neo4j-rollback-dryrun.sh`, fases 1-2) sí estaba disponible. Se documenta
también una migración propuesta (no ejecutada) para asignar
`source_id='historical_legacy'` a los nodos históricos.

<a id="d33"></a>
### 33 · Plan de evaluación de calidad del extractor — Prioridad 2
*origen: 33-extractor-quality-benchmark-plan.md*

Fecha 2026-07-14. Define el método de benchmark para las tres modalidades del
extractor (heurístico, LLM vía qwen2.5:7b, híbrido): corpus mínimo (5 fuentes,
3 tipos, 100 candidatos anotados con ground truth), métricas objetivo (P/R/F1
de entidades con umbrales ≥0.85/≥0.70/≥0.75, P/R de relaciones ≥0.75/≥0.60,
tasa de duplicados ≤0.10, tasa de relaciones inválidas ≤0.05), criterios de
decisión por candidato (autoaprobado/revisión humana/rechazo automático),
comparativa de las tres modalidades sobre el mismo corpus, medición de
reproducibilidad del LLM (varianza entre 3 ejecuciones), 5 casos de regresión
obligatorios (p.ej. "Llevás" no debe aparecer nunca como Character), y las 7
condiciones que deben cumplirse **todas** antes de habilitar la primera
ingesta real (F1 mínimo en 2 modalidades, duplicados/relaciones inválidas
bajo umbral, casos de regresión pasando, backup < 7 días, ventana de rollback
acordada, revisión humana del `review_queue`).

<a id="d34"></a>
### 34 · Resultados del benchmark de calidad del extractor — Prioridad 2
*origen: 34-extractor-quality-benchmark-results.md*

Fecha 2026-07-14, run `20260714-094125` (35 runs, 35 OK). El primer intento
había dado métricas 0.0 en los tres modos: se identificaron y corrigieron
**dos fallos reales de wiring** (no del extractor): `data_review.py extract`
ignoraba `--extractor` y siempre ejecutaba el heurístico, y
`benchmark_comparator.py` leía `approved_payload.json` (que el benchmark
aislado nunca produce) en vez de `candidates.json`. Tras corregirlos, sobre 5
fuentes (56 entidades / 16+4 relaciones de ground truth): métricas agregadas
— heuristic F1 ent 0.689, **llm F1 ent 0.718** (P 0.810), **hybrid F1 ent
0.728** (recall 0.856); relaciones con **F1 ≈ 0 en todos los modos**.
Reproducibilidad perfecta (varianza F1 = 0.0 con temperature=0, seed=42).
Autoaprobación E2E: precisión 0.850 < umbral 0.95 → **falla**; se autoaprobaron
3 relaciones pese a su baja fiabilidad. Dictamen: **Prioridad 2 PARCIAL —
REQUIERE CORRECCIONES; primera ingesta controlada BLOQUEADA.** El extractor
es útil para generar candidatos con revisión humana total, no para
autoaprobación. Correcciones propuestas: rediseño del prompt de relaciones,
guard que envíe relaciones siempre a revisión, filtro de confianza sobre el
híbrido, glosario de alias, ampliar el corpus.

<a id="d35"></a>
### 35 · Informe de sesión — Ejecución del benchmark real (Prioridad 2)
*origen: 35-priority2-benchmark-session-report.md*

Narra **cómo** se ejecutó el benchmark de docs/34 en VM105 (rama/PR #11):
preflight (243 tests base pasando, CI verde, Neo4j 199/140, Ollama accesible,
`S9K_ALLOW_REAL_INGEST` no definida), diagnóstico de los dos fallos de wiring
y su corrección (commits `a2bbb44`, `13fcab9`), ejecución del runner (35 runs
secuenciales, ~1h35min, seed=42, siempre dry-run), y el mismo resultado
agregado que docs/34. Tras los fixes, suite completa de **249 tests** verdes.
Mismo dictamen: PARCIAL — REQUIERE CORRECCIONES, ingesta bloqueada. PR #11
quedó listo para **merge manual** (no automático).

<a id="d36"></a>
### 36 · Resultados de la mejora de calidad del extractor — Prioridad 2.1
*origen: 36-extractor-quality-improvement-results.md*

Fecha 2026-07-14, run mejorado `20260714-121026` sobre las mismas 5 fuentes
del baseline (comparación justa). Cinco mejoras implementadas con tests (289
tests totales, 249+40 nuevos): quality gate que impide autoaprobar relaciones
nunca (`auto_decider.py`), prompt de relaciones con taxonomía y few-shot,
resolución de extremos de relación por alias/dirección, glosario de alias por
workspace, y filtro de confianza sobre la unión híbrida (reglas A/B/C).
Resultado: **hybrid P ent 0.634→0.851** (+0.217), **F1 ent 0.728→0.806**
(+0.078) — **el modo hybrid supera los tres umbrales de entidad** (P≥0.85,
R≥0.70, F1≥0.75). Relaciones mejoran 2.5× (F1 rel 0.036→0.089) pero siguen
muy por debajo del umbral (0.60) y quedan excluidas de autoaprobación por el
quality gate (verificado: 0 relaciones autoaprobadas en el E2E). Precisión de
autoaprobación de entidades: 0.80 (< 0.95, arrastrada por la fuente ASR).
Ampliación del corpus a 7 fuentes (72 entidades, 27 relaciones) con ground
truth congelado, lista para evaluación confirmatoria. Dictamen: **Prioridad
2.1 PARCIAL — mejora demostrada, umbrales de relación no completos; primera
ingesta de entidades DESBLOQUEADA para entidades con revisión humana total**,
bajo condiciones (modo hybrid, relaciones excluidas, revisión total,
backup/rollback vigentes, fuente pequeña). Ninguna ingesta se ejecuta en esta
tarea.

<a id="d37"></a>
### 37 · Revisión humana total y benchmark confirmatorio de 7 fuentes — Prioridad 2.1
*origen: 37-full-human-review-and-confirmatory-benchmark.md*

Fecha 2026-07-14, run confirmatorio `20260714-151119` (49 runs, 49 OK) sobre
el corpus ampliado de 7 fuentes. Introduce `S9K_REVIEW_POLICY=full_human_review`
**impuesto por código**: bajo esta política, todos los candidatos (entidades
y relaciones) van a `needs_review`, cero autoaprobados, `approved_payload`
automático vacío, y `ingest-approved` rechaza sin escribir cualquier payload
cuyos candidatos no acrediten revisión humana explícita
(`reviewed_by`/`reviewed_at`/`review_action`/`evidence`). CLI mínima
`review_manual.py` (approve/reject/edit/use-existing) con log append-only,
nunca toca Neo4j directamente. 15 tests dedicados, todos en CI. Métricas
agregadas sobre 7 fuentes: **hybrid P ent 0.878, R ent 0.823, F1 ent 0.846**
— **tanto hybrid como llm superan los tres umbrales de entidad**; relaciones
F1 0.163 (mejora sobre el 0.036 previo pero aún bajo el umbral 0.60).
Reproducibilidad total (varianza 0.0). Dictamen: **Prioridad 2.1 COMPLETADA
— PREPARADA PARA INGESTA CONTROLADA CON REVISIÓN TOTAL; primera ingesta
PREPARADA, NO EJECUTADA.** Todos los criterios de desbloqueo verificados
(umbrales de entidad, 0 autoaprobados, 0 relaciones autoaprobadas, backup/
restore/rollback de Prioridad 1). Antes de ejecutar de verdad: reconfirmar
backup, elegir fuente pequeña, dry-run, revisión humana total y activación
del doble guard bajo autorización explícita.

<a id="d52motorentidad"></a>
### 52 · (referencia cruzada) — el motor de relaciones se trata en el capítulo 4

El documento `52-motor-extraccion-auditoria-externa.md`, pese a su nombre
genérico, es en realidad el informe de auditoría externa del **motor de
relaciones**; su síntesis está en el capítulo 4 (§ *Motor de extracción de
relaciones — informe para auditoría externa*) junto con el resto de
documentos sobre ese motor.

<a id="d53"></a>
### 53 · Limpieza del grafo — migraciones controladas y reversibles (Prioridad 5)
*origen: 53-graph-cleanup-migrations.md*

Cierra el hueco de docs/28. Herramienta `review/graph_cleanup.py`
**implementada y probada**; el **APPLY sobre producción (VM105) no se ha
ejecutado**: requiere backup fresco + autorización explícita. Clasifica la
limpieza en tres clases: **AUTO_SAFE** (backfill de procedencia en nodos
históricos sin `source_id`/`source_kind` — solo metadatos, no destructivo,
100% reversible vía marcador `_mig`, es la **única auto-aplicable**),
**REVIEW_REMAP** (relaciones fuera de vocabulario con mapeo canónico
conocido) y **REVIEW_REQUIRED** (relaciones inválidas sin mapeo y fusión de
duplicados — siempre revisión humana caso a caso). Garantías fail-closed:
`plan_cleanup` es solo lectura; `apply` exige doble llave
(`apply=True` + `S9K_ALLOW_GRAPH_MIGRATION=true`) y un `backup_ref` no vacío;
solo se permite aplicar `AUTO_SAFE`; cada aplicación genera un manifiesto con
rollback exacto por `_mig`. 12 tests que matan al mutante verifican
clasificación, bloqueo sin env/backup, dry-run que no escribe, y
reversibilidad. Protocolo de operador para el APPLY en producción (gateado,
el agente no lo ejecuta por su cuenta): backup fresco → revisar el plan →
autorización explícita → aplicar solo `AUTO_SAFE` con doble llave →
re-auditar con `audit-graph` → rollback si algo no cuadra. Estado: auditoría,
planificación y auto-fix `AUTO_SAFE` implementados y probados; APPLY sobre
VM105 pendiente de backup + autorización; remap y fusión de duplicados
pendientes de revisión humana caso a caso.

---

<a id="cap4"></a>
## 4. Motor de relaciones

El motor de extracción de **relaciones** (quién pertenece a qué clan, quién
posee qué objeto, quién luchó contra quién...) es un subsistema separado del
extractor de entidades, con su propio programa de calibración y varias rondas
de auditoría interna y externa. El hilo narrativo de este capítulo es la
identificación reiterada de un mismo cuello de botella — el **anclaje de
evidencia** (localizar la cita literal exacta que justifica cada relación) y,
en menor medida, el **techo mecánico del predicado** (el motor v1 solo podía
nombrar 5 de 113 predicados posibles) — y los sucesivos intentos, todos en
modo sombra y sin escritura en Neo4j, de resolverlo. Ningún experimento de
este capítulo llegó a desplegarse ni a autorizar ingesta real.

<a id="d41"></a>
### 41 · Benchmark de extracción de relaciones: plan y método (v1)
*origen: 41-relation-benchmark-plan.md*

Plan del runner/comparador (paquete `relations/benchmark/`) que ejecuta el
**pipeline R8 real** (`relations.pipeline.run_pipeline`) sobre el corpus B1
real, sin reimplementar ninguna etapa ni simular resultados (verificado por
`assert` en tiempo de import). La entrada del pipeline (segmentos con
entidades y offsets) se **deriva de forma determinista** de las menciones del
ground truth, no se simula — con consecuencias honestamente reportadas
(sujetos elididos o correferencias generan falsos negativos reales; el
pipeline deduplica a un candidato por par, así que ground truth con varias
relaciones para el mismo par produce como mucho un TP). Tres modos vía
`PipelineConfig` real (`baseline1`=misma frase, `baseline2`=mismo párrafo,
`full_offline`=cualquier par del segmento), con proveedores locales/externos
siempre deshabilitados. Criterio de emparejamiento primario: mismo
`source_id`+`workspace`+par de entidades no ordenado; la dirección semántica
se evalúa aparte, como atributo estructural. Métricas: globales
(precisión/recall/F1 de existencia), estrictas (par+predicado exacto), por
predicado, calidad estructural (predicado, dirección, tipos, negación,
temporalidad, estado epistémico, evidencia/offsets), operativas, y
determinismo (≥2 ejecuciones con hashes idénticos). 9 *gates* independientes,
cada uno PASS/PARTIAL/FAIL, con vocabulario cerrado de dictamen: *APTO PARA
CONTINUAR EN MODO SOMBRA / APTO CON REVISIÓN DE CASOS CONFLICTIVOS / APTO CON
REVISIÓN HUMANA TOTAL / NO APTO* — explícitamente **prohibido** el veredicto
"apto para ingesta real".

<a id="d52"></a>
### 52 · Motor de extracción de relaciones — informe para auditoría externa
*origen: 52-motor-extraccion-auditoria-externa.md*

El motor está **congelado en `main`** (commit de cierre del programa de
calibración de 9 bloques) y **no activado en producción**. Hallazgo material
del programa: medido con dos proveedores distintos (Ollama y NVIDIA), la
calidad actual **no justifica reducir la supervisión humana**; el cuello de
botella no es el modelo de IA sino el **anclaje de evidencia**. Arquitectura
en `data-engine/app/relations/`: pares candidatos → señales heurísticas
explicables → análisis sintáctico stdlib → construcción del candidato (con
evidencia como span literal) → proveedores LLM opcionales en sombra →
consenso → salida JSON determinista. El problema central, en dos capas: (1)
capa heurística — la evidencia es "todo el tramo de texto entre las dos
menciones" (`seg_text[lo:hi]`), a menudo demasiado ancha, penalizada por la
métrica IoU≥0.5 del benchmark; (2) capa LLM — el modelo parafrasea la cita en
vez de copiarla literalmente, y el validador estricto (correctamente) la
rechaza. Resultado del Bloque 7 (real, no simulado): NVIDIA 27/27 rechazos
por evidencia inválida en un caso, Ollama con mayoría de rechazos; P/R/F1
salen **idénticos con y sin proveedores** (0.7407/0.7692/0.7547) — confirma
que los proveedores están correctamente "en sombra" pero también confirma un
**techo de calidad** que ellos no mueven. Observaciones secundarias:
confianza heurística no calibrada, predicado por defecto genérico
`RELATED_TO`, analizador sintáctico solo heurístico (sin spaCy/Stanza), recall
acotado por ventana de pares. Ideas de mejora priorizadas (ninguna
implementada en este documento): anclar la evidencia a la frase mínima (bajo
riesgo, alto impacto esperado), re-alinear citas parafraseadas del LLM contra
el texto real en vez de rechazarlas, tolerancia de offsets controlada,
prompt few-shot centrado en la cita, confianza calibrada, parser sintáctico
opcional. Lista 7 garantías innegociables (sombra, fail-closed, umbrales
intactos, política de revisión fail-closed, doble llave para proveedores
reales, clasificación segura por defecto, manifiesto fail-closed) y las
prohibiciones operativas del proyecto (no desplegar, no ingerir real, no
tocar VM105/Neo4j, no crear tag RC6, no imprimir secretos).

<a id="d50rel"></a>
### 50 · Benchmark de extracción de relaciones: resultados
*origen: 50-relation-benchmark-results.md*

Última medición 2026-07-21 (ronda 4 acumulada) sobre el pipeline R8 real y el
corpus B1 real (16 fuentes, 54 relaciones de ground truth). Se endureció
exhaustivamente la instrumentación sin tocar el pipeline: autorización de
proveedores centralizada, validación del endpoint local, timeout local
elevado a 300s (p50 real 97.8s, máx 175.7s), separación de fallos de
transporte vs. respuesta vs. indeterminados, umbral de salud de transporte
del 10% por carril, y manifiesto de payloads reforzado con HMAC de operador
tras demostrarse que podía falsificarse con valores públicos. Hallazgo real
de esta ronda: un defecto (`external_model` nunca fijado en el preset
`nvidia_shadow`) hacía que el carril NVIDIA enviara un placeholder,
provocando 404 disfrazados de fallo de infraestructura — invisible mientras
NVIDIA figuraba como "no ejecutado"; corregido con guarda fail-closed. **Resultados
offline** (`baseline1`): Precisión 82.69%, Recall 79.63%, F1 81.13%
(existencia de relación; TP/FP/FN = 43/9/11). Calidad estructural sobre los
TP: predicado correcto 25.6%, dirección correcta 62.8%, temporalidad correcta
44.2%, evidencia correcta 90.7%, offsets correctos 93.0%. Gates: todos PASS
excepto `predicate_structural` (25.58% vs. umbral 50%, único FAIL real).
**Dictamen: APTO CON REVISIÓN HUMANA TOTAL** (nunca "apto para ingesta
real"). Ejecuciones reales verificadas: Ollama (`qwen2.5:7b`, CPU) sobre
submuestra de 6 fuentes (2026-07-20); NVIDIA (`meta/llama-3.3-70b-instruct`,
2026-07-21). Determinismo verificado (2 ejecuciones idénticas). Sin
escritura en Neo4j, sin autoaprobación.

<a id="d51pipeline"></a>
### 51 · Pipeline de relaciones (OLA 2B): arquitectura y operación en runtime
*origen: 51-relation-pipeline-runtime.md*

Documento de arquitectura/operación (no cambia producto ni producción) del
pipeline R8 integrado en `main`. Garantías duras: propositor en modo sombra
que nunca escribe en Neo4j ni auto-aprueba (el consenso solo emite
`propose`/`reject`/`human`); Ollama y NVIDIA reales no se ejecutan por
defecto (fail-closed sin transporte inyectado); sin OCR; sin ruta `APPLY`
implementada. Arquitectura: componentes deterministas orquestados por
`pipeline.run_pipeline` — pares candidatos, sintaxis heurística stdlib, 13
señales explicables, `RelationCandidate` (contrato cerrado de 20 campos,
`internal-1.0.0`), evaluación LLM opcional en sombra, y consenso con los 5
estados canónicos reutilizados de `external_ai`. Determinismo garantizado por
IDs con hash SHA-256 del contenido (sin timestamps/azar) y `result_hash` que
excluye la traza de observabilidad. `PipelineConfig` es un dataclass frozen
sin ninguna opción de escritura, y rechaza explícitamente flags tipo
`write`/`apply`/`commit`/`auto_approve`. Errores clasificados en fatales,
fatales de segmento (aíslan el segmento) y recuperables por par. Resume el
mismo dictamen de docs/50: **APTO CON REVISIÓN HUMANA TOTAL**, F1 de
existencia 81.1% pero F1 estricta (par+predicado exacto) solo 17.0%. Gates:
PASS en determinismo, contaminación de workspace, relaciones simples
(93.3%), evidencia (90.7%), offsets (93.0%), negación (100%); **FAIL** en
temporalidad (28.0% vs. 60%) y `predicate_structural` (20.9% vs. 50%);
PARTIAL en rumores (50.0% vs. 60%). Sección final reitera que cualquier
promoción a ingesta real es decisión gateada y humana, fuera de este
pipeline.

<a id="d51policy"></a>
### 51 · Política de reducción controlada de revisión humana (relaciones): calibración y resultado
*origen: 51-relation-review-policy-calibration.md*

Fecha 2026-07-21, Bloque 8 del programa secuencial. Objetivo: calibrar (sin
activar nunca) una política que identifique relaciones de alta confianza que
podrían saltarse la revisión humana, y **medir honestamente** si eso sería
seguro. Módulo `relations/review_policy.py`, completamente desconectado de
cualquier vía de escritura real. `classify_for_review` exige 5 condiciones
duras simultáneas para `AUTO_PROPOSABLE`: STRONG_CONSENSUS, al menos un
proveedor presente, score≥0.90, cero conflictos, evidencia presente. Gates
duros: `false_accept_rate ≤ 0.02`, `precision ≥ 0.98`, ambos exigiendo
`sample_size ≥ 20` (si no, `NOT_MEASURED`, salvo que ya haya un
falso-aceptado, que fuerza FAIL incondicional); la cobertura es solo
informativa, nunca gate duro, deliberadamente, para no incentivar relajar
umbrales. **Resultado real, sin maquillar:** en ambos modos evaluados,
`sample_size=0`, cobertura auto-proponible **0%**, gates en `NOT_MEASURED`.
**Dictamen: "POLÍTICA DE REDUCCIÓN: NO CALIBRABLE (COBERTURA
INSUFICIENTE)".** Causa raíz verificada en código: `STRONG_CONSENSUS` exige
estructuralmente al menos un proveedor ejecutado, y en modo offline no hay
ninguno, por lo que ese estado es matemáticamente inalcanzable sin
proveedores reales. Conclusión: con la calidad actual, nada puede saltarse
la revisión humana de forma segura. Predicción razonada (no ejecutada,
pendiente de autorización): las mediciones reales del Bloque 7 (Ollama
18/27=66.7% inválidas, NVIDIA 27/27 evidencia vacía/ausente) sugieren que el
mismo cuello de botella de anclaje de evidencia persistiría con proveedores
reales encendidos.

<a id="d52v2audit"></a>
### Motor de relaciones v2 — Auditoría (Etapa 1) y Diseño (Etapa 2)
*origen: relation-engine-v2-audit-and-design.md*

Rama `feat/relation-engine-v2-hybrid`, commit base `dcded31`. **Etapa 1
(auditoría) cerrada**, Etapa 2 (diseño) pendiente de aprobación antes de
implementar; **no se ha tocado el motor todavía** en este documento.
Diagnóstico confirmado con datos: `_choose_predicate` solo puede emitir 5
predicados (`MEMBER_OF, OWNS, LOCATED_IN, PARTICIPATED_IN, RELATED_TO`) de
los **113** que tiene la ontología; del ground truth del corpus B1 (54
relaciones, 20 tipos de predicado), **solo 25/54 (46.3%) tienen un predicado
que el motor puede siquiera nombrar** — el resto es imposible por
construcción. Segundo hallazgo: 9 tipos del ground truth (~15 relaciones) no
están en `ALLOWED_RELATION_TYPES`, requiriendo reconciliación explícita
(commits separados, sin amañar el GT para favorecer al motor). Diseño
objetivo v2: arquitectura por componentes (no monolito) —
pares→detector de existencia→familias candidatas→predicados
candidatos→filtro ontológico dominio/rango→ranking→dirección (módulo
independiente)→temporalidad/vigencia→epistémico→validación de
evidencia→consenso→decisión, cada etapa desactivable y con confianza
propia. Cambios clave: ontología como fuente única con dominio/rango/alias/
inversa/simetría; selector de predicado v2 que genera candidatos con score y
se **abstiene** (`REVIEW_PREDICATE`) si no hay margen, en vez de la cascada
de 5; dirección como módulo independiente; temporalidad con estados
ACTIVE/ENDED/PLANNED/HYPOTHETICAL/RECURRING/UNKNOWN; parser sintáctico
opcional (spaCy/Stanza) tras interfaz, desactivable. Plan en 9 bloques
(B0 reconciliación → B8 benchmark final). Gates experimentales definidos
(predicate_exact≥0.50, direction_exact≥0.75, temporal≥0.60, strict_F1≥0.35)
sin rebajar los umbrales existentes. Riesgo explícito de sobreajuste al
corpus de 54 relaciones, mitigado con validación por abstención y por clase.

<a id="d52v2results"></a>
### Motor de relaciones v2 — Informe de resultados
*origen: relation-engine-v2-results.md*

Rama `feat/relation-engine-v2-hybrid`, HEAD `1c444a9`, 15 commits,
+10.812/−77 líneas, 279 tests nuevos (suite completa: 2431 passed, 2
skipped). Confirma el diagnóstico previo (solo 5/113 predicados, 0 rechazos
offline en 52 candidatos). Se descubrió además que el propio arnés de
medición sub-contaba ~31% y sobre-contaba ~13%; corregido, la línea base de
predicado **bajó** de 0.2558 a 0.2093 (corrección aplicada aunque
perjudicaba el interés del programa). Resultados A/B v1→v2 en `baseline1`:
predicate_correct **0.2093→0.8140**, direction_correct **0.6279→0.9302**,
temporal_correct **0.4419→0.8837**, strict_predicate F1 **0.1698→0.6604**,
evidence_correct 0.9070→0.9302, falsos ACCEPT 4→**0**; `pair_F1` se mantuvo
en 0.8113 (el techo real de detección de pares no se tocó). Los 4 gates
experimentales se cumplen sin rebajar umbrales. Veredicto del arnés: **APTO
PARA CONTINUAR EN MODO SOMBRA**. Pero el motor se abstiene mucho más: de 30
relaciones que el GT acepta, v2 solo propone 3. Una ablación reveló que
~70% de la ganancia inicial del selector de predicados era sobreajuste al
corpus; purgado, quedó en 0.814, con rango honesto estimado **[0.42, 0.81]**.
Se corrigió el defecto P0 heredado (el evaluador externo recibía el ID del
segmento como "documento" en vez del texto real). Limitaciones críticas: n=54
con dev==test (sin held-out real), precisión de la señal de negación que
dispara rechazos solo 4/9 (44%). Dictamen original del supervisor: **APTO
COMO EXPERIMENTO. NO APTO PARA PRODUCCIÓN. NO FUSIONAR.** Adenda del
propietario (2026-07-26): autoriza **fusionar a `main` sin activar** (el
flag por defecto sigue en v1; el merge solo entra por el fix del defecto P0
y por un techo de seguridad añadido), manteniendo bloqueados: activar v2 por
defecto, retirar v1 (vía de rollback), promocionar la ruta de rechazo, y
cualquier despliegue/ingesta.

<a id="d52v2external"></a>
### Dosier de análisis externo — Motor de relaciones
*origen: relation-engine-external-analysis-dossier.md*

Dosier autocontenido para revisor externo, derivado del programa PR#95
(V1-V4, ramas draft "DO NOT MERGE", `main` intacto en `dcded31`). Distingue
dos capas: **Capa A** (corroboración externa / IA externa en sombra) y
**Capa B** (motor de extracción propio heurístico, el limitante real de cara
a la ingesta). Resultados de las 4 versiones probadas: **V1** (anclaje
conservador) **negativo** — evidence 0.907→0.837, 0 mejoras/3 regresiones;
**V2** (realineamiento determinista, capa A) mejora la aceptación sintética
0.185→0.796 pero con `false_realign` 0.182; **V3** (fragmentos, capa A)
aceptación sintética 0.185→**0.963**, inmune a inyección; **V4** (híbrido,
capa B) **neutro**, comportamiento por defecto igual a la línea base. La
capa B tuvo **0 de mejora** en todo el programa. Línea base del motor propio
(corpus C1): pair_F1 0.811, strict_F1 0.208, evidence_correct (IoU≥0.5)
0.907, evidence_exact 0.395, **predicate_exact 0.256** (cuello de botella
principal), direction_exact 0.628, negation 0.907, temporal 0.442, epistemic
0.860, decision 0.302. Dictamen del benchmark: "APTO CON REVISIÓN HUMANA
TOTAL — evidencia/offsets fiables pero el predicado heurístico es débil";
ingesta real bloqueada. Corrida real con NVIDIA (`meta/llama-3.3-70b-instruct`)
sobre los 52 candidatos completos, tras el fix de P0: configuración BASE
(solo P0) da **0/52** verdictos válidos (100% rechazado por offsets
inválidos); con V2 sube a **52/52**; con V3 a **49/52**. Conclusión con
datos reales: P0 es necesario pero no suficiente; P0+V2 o P0+V3 desatascan
la capa externa, pero "válido" significa offsets coherentes, no evidencia
correcta (V2 puede anclar en el span equivocado ~18% de las veces según el
banco sintético; V3 acepta menos, 94%, pero sin ese riesgo). La Capa B
(predicado 0.256) sigue bloqueando la ingesta independientemente de que se
resuelva la Capa A. Todo offline/dry-run; ingesta y despliegue siguen
bloqueados.

<a id="dpr95"></a>
### Informe consolidado PR #95 y prompt multiequipo — motor de relaciones
*origen: INFORME_CONSOLIDADO_PR95_Y_PROMPT_MULTIEQUIPO.md*

Fecha 2026-07-21, puramente analítico y de planificación (no autoriza
despliegue, ingesta, escritura ni fusión). Compara tres auditorías previas
sobre el motor de relaciones, resuelve sus discrepancias y diseña 4 versiones
experimentales más el prompt de ejecución multiequipo. Dictamen de causa
raíz, en orden: **P0 (crítico)** — confusión ID/texto: `pairs.py` asigna
`source_segment = seg["id"]`, y `external_ai_shadow.py` lo trata como
"DOCUMENTO", validando offsets contra el identificador en vez de contra el
texto real — confirmado por revisión directa del código como prioritario
sobre la hipótesis rival (span mecánico demasiado amplio); **P1 (alto)** —
evidencia heurística por envolvente literal entre menciones; **P2** —
normalización/realineamiento de citas causando falsos rechazos; **P3** — el
contrato solo admite un único span de evidencia. Conclusiones comunes: la
validación estricta `document_text[start:end] == evidence_text` debe
conservarse, no relajarse; igualdad de P/R/F1 no demuestra que el proveedor
externo no aporte valor; el benchmark es insuficiente para decisiones
definitivas (corpus pequeño/sintético, sin intervalos de confianza).
Catálogo de 12 problemas (P0-P12) con severidad, solución y tests
obligatorios. Las **cuatro versiones experimentales**, todas desde el mismo
commit base tras corregir P0: **V1** (anclaje conservador — reduce evidencia
a frase/cláusula segura, bajo riesgo), **V2** (realineamiento determinista —
exact match→normalizado→alineamiento token/char→fuzzy en ventana→rechazo si
ambiguo), **V3** (selección por fragmentos numerados — el proveedor elige un
`fragment_id` en vez de offsets crudos), **V4** (pipeline híbrido por etapas
desactivables, dirección más ambiciosa pero mayor superficie de fallo).
Métricas comunes extensas (estructura, evidencia, semántica,
operación/seguridad) sobre tres estratos de corpus (vigente, independiente,
adversarial). El prompt de ejecución multiequipo (§10) define restricciones
absolutas (nada de commits a `main`, sin despliegue, sin escritura, red
desactivada por defecto, PRs siempre draft/`do-not-merge`), jerarquía de
agentes (Supervisor General, Organizador, y por versión un equipo de 8
roles, con un agente de respaldo "FABLE" tras fallo del editor Opus), fases
(fotografía Git, rama base con P0, cuatro ramas independientes) y 6 puertas
de calidad (QG-01 a QG-06). Prohíbe explícitamente declarar una versión
ganadora. **Estado final:** experimentación ejecutada desde `BASE_SHA=92583f4`;
5 PRs draft (#97-#101, base+V1-V4), todos `DO NOT MERGE`, todos **CONFORME**
según las puertas de calidad pero **sin ganadora clara** (el diseño buscaba
artefactos comparables, no elegir un enfoque). `main` permaneció intacto
(`dcded31`).

<a id="dinformemejora"></a>
### S9 Knowledge — Informe consolidado V2 para mejorar el motor
*origen: S9_KNOWLEDGE_INFORME_MEJORA_MOTOR_CONSOLIDADO_V2.md*

Fecha 2026-07-26. Consolida dos propuestas previas de mejora, comparándolas y
tomando como referencia patrones de tres proyectos externos: **Graphiti**
(episodios, hechos temporales, invalidación sin borrado, resúmenes por
comunidades), **TrustGraph** (procedencia obligatoria, aislamiento,
versionado, snapshots/rollback) y **Neo4j LLM Graph Builder**
(puertos/adaptadores de proveedores, selección de modelos, medición de
consumo). No es un benchmark ejecutado sino un **diseño arquitectónico y plan
de implementación por bloques**. Dictamen: sí es posible mejorar
significativamente adaptando estos patrones, pero **sin ceder autoridad** —
S9 Knowledge conserva siempre contratos, validación, revisión y escritura;
los patrones externos solo amplían temporalidad, trazabilidad, modularidad y
operación. Rechaza explícitamente: que Graphiti escriba el grafo, desplegar
TrustGraph completo, introducir Apache Pulsar, ontologías mutables en
producción, y la cifra de "ahorro ~70%" de rendimiento del informe previo
(sin evidencia, sustituida por un objetivo de medición). 13 ideas aceptadas
en común entre los dos informes previos (Episode inmutable,
`valid_from`/`valid_to`, invalidación sin borrado, procedencia obligatoria,
aislamiento por workspace, snapshots/rollback, abstracción de proveedores,
medición de consumo, ontologías configurables...), más ideas adicionales
aceptadas con matices (capa de comunidades derivada no autoritativa,
`KnowledgeBundle`, inyección de dependencias con puertos/adaptadores).
**15 invariantes permanentes**: los modelos externos no escriben ni
aprueban; el pipeline de relaciones sigue en dry-run; toda evidencia se
valida localmente; ontología activa inmutable; relación histórica nunca se
borra; operación destructiva exige snapshot probado; reducción de revisión
requiere benchmark; producción no se toca sin autorización explícita.
Arquitectura objetivo en 4 capas: entradas inmutables (Source→Episode→
Segment→Evidence), **Assertion Ledger** (fuente de verdad auditable, con
estados vigente/histórico/propuesto/disputado/contradicho/retractado/
sustituido), vista materializada (derivada), conocimiento derivado
(EntitySynopsis, Community). Define 13 contratos nuevos
(`EpisodeRecord`, `EvidenceRecord`, `ProvenanceStamp`, `CandidateEnvelope`,
`TemporalAssertion`, `SupersessionPlan`, `FlowDefinition`/`FlowRun`,
`ProviderSpec`/`ModelSpec`, `UsageEvent`, `OntologyVersion`,
`KnowledgeBundle`, `EntitySynopsis`/`CommunitySummary`) que envuelven, sin
modificar, el contrato `RelationCandidate` existente. Plan de implementación
en **17 bloques secuenciales** (0 a 16), cada uno con gate de aceptación
cuantificado (p.ej. Bloque 1: 100% de candidatos con evidencia literal
válida; Bloque 8: 0 fugas de workspace; Bloque 12: restauración probada con
hashes/counts coincidentes), con orden estricto: no implementar
invalidación automática, procesamiento combinado ni resúmenes globales antes
de resolver evidencia, procedencia y contratos temporales. Conclusión: el
resultado no es una copia de los tres proyectos externos, sino una versión
más robusta de S9 Knowledge especializada en lore de campañas vivas.

---

<a id="cap5"></a>
## 5. Ingesta y transcripción multimedia

Cubre todo el camino desde un archivo de audio/vídeo hasta un texto revisable
listo para entrar al pipeline de extracción: pruebas de transcripción,
worker de ingesta multimedia, cola de jobs, mejora de transcripción con
glosario específico de dominio (L5A), benchmark de transcripción de YouTube,
el pipeline de revisión/aprobación de datos, el writer seguro de ingesta, y
el mecanismo de supersesión de revisiones. Ninguno de estos documentos
autoriza ni ejecuta una ingesta real en Neo4j.

<a id="d13"></a>
### Prueba de transcripción de vídeo — S9 Knowledge
*origen: 13-video-transcription-test.md*

Fecha 2026-07-11. Valida el pipeline completo (extracción de audio con
ffmpeg → WAV mono 16kHz → transcripción con faster-whisper modelo `small`,
CPU-only) primero con un vídeo sintético de 30s (tono sine, sin habla,
transcripción vacía como se esperaba) y después, en la "Parte 5", con **audio
real**: 16 archivos de podcast/campaña L5A en Nextcloud
(`/mnt/nextcloud-rol/leyenda/videos`), de los cuales se procesaron los
primeros 2 minutos de "Bienvenidos a Tsuma" (55 MB, español). Resultado:
transcripción de excelente calidad en español, con nombres propios L5A
reconocidos correctamente ("Akodo Masako", "Senpuku", "Topacio"), tiempo de
ejecución ~15s para 2 min de audio. Conclusión: **LISTO PARA PRODUCCIÓN** el
pipeline de transcripción en sí (no la ingesta a Neo4j, que queda fuera de
alcance). Confirmaciones de seguridad: no se escribió en Neo4j, no se tocó
Nextcloud/SilverBullet/Ollama, no se abrió acceso externo.

<a id="d14"></a>
### 14 · Worker de ingesta multimedia (v0.2.4)
*origen: 14-multimedia-ingestion-worker.md*

Automatiza el primer tramo del procesado de fuentes multimedia: detección de
archivos en `staging/media/` → cálculo de sha256 y deduplicación → sondeo con
ffprobe → extracción/normalización de audio con ffmpeg → transcripción con
motor configurable (`stub` por defecto, `faster-whisper` opcional) →
Markdown revisable con metadatos y observaciones de calidad → estado por job.
Explícitamente **no** escribe en Neo4j, no procesa PDFs, no genera resumen
automático, no es un daemon (ejecución manual o por cron/timer futuro). Cada
Markdown generado lleva `Preparado para ingesta: no`. Rutas configurables por
variables `S9K_MEDIA_*`, todas bajo directorios ignorados por git. CLI en
`data-engine/app/cli/media_jobs.py` (`scan`, `list`, `worker`, `show`).
Motor recomendado para VM105 (probado): `faster-whisper` en CPU con
`compute_type=int8`. Documenta (sin instalarlo) cómo convertir el worker en
un `systemd.timer` en una fase futura. Riesgos: depende de ffmpeg/ffprobe
en el sistema, el `stub` produce texto ficticio, sin control de concurrencia
entre workers.

<a id="d15"></a>
### 15 · Worker y panel de jobs (v0.2.4)
*origen: 15-jobs-worker-panel.md*

Construye una infraestructura de **cola de trabajos genérica** (más allá de
la cola histórica de ingesta de fuentes): un job se crea, un worker lo
reclama y procesa, y su estado se ve desde un panel web `/jobs`, todo sin
implementar aún la lógica real de transcripción/ingesta. Amplía de forma
aditiva la misma tabla `jobs` de SQLite (migración idempotente
`ALTER TABLE`), añadiendo `job_type`, `priority`, `payload_json`,
`result_json`, reintentos. Solo `noop`/`echo` tienen handler implementado en
esta fase; el resto (`media_probe`, `audio_extract`, `transcribe`,
`write_markdown`, `ingest_text`, `audit_duplicates`) son placeholders que se
marcan `skipped` (no fallo) si se piden. El panel `/jobs` del visor es **de
solo lectura**; `retry`/`cancel` solo existen en CLI. Describe cómo se
integrará después con el worker multimedia (docs/14) mediante un
`job_store_bridge.py` opcional, y cómo podría pasar a systemd/timer en una
fase posterior (no instalado en esta fase).

<a id="d18"></a>
### 18 · Mejora de transcripción L5A con glosario, normalización y corrección
*origen: 18-l5a-transcription-glossary-plan-and-test.md*

Fecha 2026-07-12. La transcripción con faster-whisper `small` es funcional
pero comete errores en nombres propios de dominio (L5A), lo que la hace poco
fiable para ingesta directa. Se diseñó y validó un pipeline de mejora con
cuatro piezas: (1) **glosario automático** en SQLite (1044 términos:
semillas manuales, entidades de Neo4j, términos de Markdown/docs), con
búsqueda exact/alias/error_form/fuzzy; (2) transcripción asistida por
`initial_prompt`/`hotwords` — **resultado negativo** con `small` (colapsó la
segmentación y perdió contenido); (3) **normalización determinista** por
`error_forms` con límites de palabra, preservando timestamps —
**recomendado**, corrigió casos reales ("Sei Yuro"→"Seijuro",
"Kitsubikaji"→"Kitsugi Kaji") con confianza 0.99; (4) corrección con Ollama
(qwen2.5:7b) — **falló la validación** (eliminó la mitad de los timestamps,
acortó el texto), se descartó de forma segura sin ingerir nada.
**Conclusión: la vía fiable es `medium` (0% de errores L5A críticos en el
benchmark, frente a 67% con `small`) + normalizador determinista.**
`medium` deja poca RAM libre (~250 MB de 7.7 GB) → nunca paralelizar dos
transcripciones `medium`. Ningún dato se ingirió al grafo;
`ready_for_ingestion=false` siempre.

<a id="d20"></a>
### Data Review y Aprobación de Ingesta
*origen: 20-data-review-and-approved-ingest.md*

Documenta la filosofía de **revisión humana mínima** (el humano revisa solo
lo dudoso; la autoaprobación segura es la norma) y el pipeline completo:
`segment → classify → extract → validate → resolve → decide →
approved_writer`, con cadena de evidencia
`transcript.md → candidates.json → approved_payload.json → Neo4j`. Estados
de candidato: `auto_approve` (confianza≥0.85 y validado), `needs_review`
(0.60-0.85 o ambigüedad), `auto_reject` (confianza<0.60 o inválido). CLI
`data_review.py` con subcomandos por etapa y `ingest-approved`
(**`--dry-run` obligatorio en esta fase**; sin él, el comando aborta).
Auditoría de calidad del grafo (`audit-graph`, solo lectura) detecta
duplicados, relaciones inválidas, nodos sin metadata. **Limitación crítica
verificada (2026-07-12):** el extractor heurístico produce falsos positivos
reales — en una prueba con una fuente real, autoaprobó palabras comunes en
mayúscula ("Llevás", "Todo", "Como") como `Character` con confianza 0.85. El
framework es seguro (nada se ingiere sin desactivar `--dry-run` y sin
autorización explícita), pero se recomienda explícitamente **no ejecutar
`ingest-approved` real** hasta sustituir el extractor heurístico por uno con
validación LLM — recomendación que las fases de mejora posteriores (docs/33
a 37) llevaron a cabo.

<a id="d27"></a>
### 27 · Runbook de Ingesta Controlada
*origen: 27-controlled-ingest-runbook.md*

Procedimiento operacional paso a paso para una ingesta real (cuando se
autorice): checklist pre-ingesta obligatoria (backup verificado, `source_id`
no existente, dry-run del extractor revisado, `review_queue` sin pendientes,
espacio en disco, ventana acordada), activación explícita y temporal del
doble guard (`--dry-run` desactivado + `export S9K_ALLOW_REAL_INGEST=true`
**solo para la sesión**, nunca en `.env` permanente), pasos del pipeline
(transcripción → dry-run del extractor → revisión de la cola → ingesta real
con el guard activo), validación post-ingesta (conteo de nodos antes/después,
verificación de `source_id`), y dos vías de rollback de emergencia
(selectivo por `source_id`, o restore completo desde backup). Incluye una
tabla de registro de ingestas reales ejecutadas — en el momento de redacción,
vacía ("primera ingesta pendiente"). Notas de seguridad: desactivar
`S9K_ALLOW_REAL_INGEST` al terminar la sesión; los ~87 nodos históricos sin
`source_id` no son eliminables por rollback selectivo.

<a id="d40"></a>
### 40 · Benchmark de transcripción YouTube vs faster-whisper
*origen: 40-youtube-whisper-transcription-benchmark.md*

Fecha 2026-07-15. Compara faster-whisper `medium` (raw y normalizado con
glosario) contra subtítulos automáticos de YouTube, sobre una ventana de 10
minutos de un vídeo L5A. Limitación reconocida: sin referencia humana, no es
posible un WER/CER verdadero; la comparación es indirecta (dos sistemas
automáticos entre sí) más una métrica semiobjetiva de términos L5A contra el
glosario de 1044 términos. Resultados: acuerdo token-level 0.887 entre los
dos ASR; el normalizador aplicó **0 sustituciones** (coherente con "medium =
0% error en nombres L5A" de docs/18, aunque el glosario de `error_forms`
resultó **incompleto** — no corrigió "caquita rico"→"Kakita Riko"). Detector
de segmentos conflictivos: **91% AUTO_ACCEPT, 7% REVIEW_CONFLICT, 2%
REJECT_SEGMENT** — cumple el objetivo de >90% auto-aceptable, y los pocos
conflictos concentran justamente los errores de nombre propio críticos para
el grafo. Rendimiento: RTF 0.56 (más rápido que tiempo real). **Dictamen:
transcripción de vídeo APTA CON REVISIÓN DE SEGMENTOS CONFLICTIVOS.**
Recomendación operativa explícita: **no usar una transcripción de vídeo
nueva para la primera ingesta** (añade riesgo de nombres propios sin
validar); reservar vídeo para ingestas posteriores y usar para la primera
ingesta una fuente pequeña ya validada (notas o transcripción corta
normalizada).

<a id="d43"></a>
### 43 · Writer de ingesta controlada — semántica create-only y segura
*origen: 43-safe-controlled-ingest-writer.md*

Fecha 2026-07-15. Corrige la semántica de escritura de
`review/ingest_approved.py` **antes** de autorizar cualquier ensayo E2E de
primera ingesta. Cambio central: entidades nuevas pasan de `MERGE` (que
podía **actualizar** silenciosamente un nodo existente) a **CREATE-only**
— `_build_create_entity` valida el tipo contra una allowlist, verifica
primero la no-existencia dentro de una transacción, y si el nodo ya existe
**aborta toda la transacción** (rollback), nunca actualiza. `USE_EXISTING`
pasa a ser verificación pura sin mutación (exige exactamente 1 coincidencia,
cero `SET`). El dry-run queda **conectado a Neo4j en lectura real**,
reportando `would_create`/`conflict_existing`/`ambiguous_existing`/etc., y
degrada de forma segura (`safe_to_write=False`) si Neo4j no está disponible.
Bajo `full_human_review`, cada entidad nueva debe declarar procedencia
explícita completa (`source_id`, `reviewed_by`, `reviewed_at`, `evidence`...)
— sin defaults inventados; falta de un campo = **paquete rechazado**.
Transacción atómica: si algún candidato falla el preflight, se revierte
**toda** la transacción. La primera ingesta controlada prevista admite
**cero relaciones** (un payload con relaciones se rechaza). Suite completa:
360 tests verdes. Ningún cambio de este documento activa escritura por sí
mismo.

<a id="d49"></a>
### 49 · Flujo de supersesión inmutable de reviews (RC2)
*origen: 49-immutable-review-supersession.md*

Herramienta `data-engine/app/review/supersede_review.py`: corrige un
`review_recommendations.json` **sin modificar el original**, generando una
versión `.v2.json` mediante transformación explícita y auditable. No escribe
en Neo4j, no ejecuta ingesta, no inventa metadatos de auditoría
(`reviewed_by`, `correction_reason`, `created_at` son obligatorios por
parámetro). Garantías: verifica el SHA-256 del original contra
`--supersedes` y aborta si no coincide; `--in`/`--out` no pueden coincidir;
idempotencia (`ALREADY_DONE` si ya existe con el mismo hash de origen, abort
si existe con hash distinto — segunda supersesión conflictiva); fichas
duplicadas se consolidan conservadoramente en una única decisión
`DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE` (nunca `CREATE_NEW`,
nunca `SET` sobre nodo existente); relaciones siempre excluidas
(`relations_authorized=0`); escritura atómica a `.tmp`+`rename`, permisos
0600; rechaza path traversal y symlinks. Caso aplicado documentado:
`leyenda/source_narrative_01`, donde "Clan Escorpión" tenía dos decisiones
contradictorias (REJECT como tipo inválido + APPROVE como entidad ya
existente), consolidadas en una sola. 25 tests. Estado: parte del candidato
**RC2** (`release/prepare-v0.3.1-rc2`), **no desplegado**; la primera
ingesta sigue sin autorizar.

---

<a id="cap6"></a>
## 6. Revisión, benchmarks y calibración con IA externa

Cubre la integración con proveedores de IA externos (principalmente NVIDIA
NIM) para revisión de candidatos en **modo sombra** (nunca decide, nunca
escribe), y el diseño de un orquestador de procesamiento externo por ráfaga
para trabajos pesados (transcripción/OCR/análisis de imagen a gran escala).
Ambos subsistemas están desactivados por defecto y separados con claridad de
la vía productiva local.

<a id="d42"></a>
### 42 · Calibración multi-IA (NVIDIA) y procesamiento externo por lotes
*origen: 42-external-ai-calibration-and-burst-processing.md*

Fecha 2026-07-15. **Modo sombra obligatorio**: toda ejecución externa
produce `shadow_recommendation`, nunca una decisión productiva; nada de este
subsistema escribe en Neo4j. **Fase A (implementada):** paquete
`data-engine/app/external_ai/` con cliente OpenAI-compatible, proveedor
NVIDIA NIM, parser robusto de JSON, motor de consenso, calibración contra
decisiones humanas, caché idempotente y detector de secretos (incluye
patrones `nvapi-...`). Dos revisores independientes (sin verse) evalúan cada
candidato con prompts idénticos; un árbitro solo interviene en conflicto.
Estados de consenso: `STRONG_CONSENSUS · PARTIAL_CONSENSUS · MODEL_CONFLICT ·
INVALID_RESPONSES · HUMAN_REQUIRED` (no existe `AUTO_APPROVED`). CLI exige
`--shadow` o aborta. 22 tests sin llamadas reales, incluido uno que falla si
el subsistema toca ingesta/Neo4j. **Validación real controlada, ejecutada
2026-07-15:** con API key en un EnvironmentFile privado, revisión real sobre
3 candidatos con 2 modelos de familias distintas (`nemotron-mini-4b`,
`solar-10.7b-instruct`) + adjudicador — 2 STRONG_CONSENSUS, 1
PARTIAL_CONSENSUS, 0 conflictos, 0 errores de validación, caché confirmada,
Neo4j intacto 199/140. **Fase B (diseñada, pendiente):** interfaz reutilizable
de procesamiento externo elástico sobre la cola de jobs, con tres modos
previstos (`local`/`hybrid`/`burst`) y regla invariante: toda respuesta
externa vuelve al pipeline local (`validate→normalize→resolve→review
policy→approved payload`) antes de tocar el grafo. B1 (orquestador y mock)
quedó implementada en esta misma fecha — ver docs/45; B2 (proveedores
reales) y B3 (activación en producción) pendientes.

<a id="d45"></a>
### 45 · Orquestador de procesamiento externo por ráfaga (Fase B1)
*origen: 45-external-burst-orchestrator.md*

Fecha 2026-07-15. **Modo seguro por defecto**: arranca con
`S9K_EXTERNAL_PROCESSING_ENABLED=false` y `S9K_EXTERNAL_DRY_RUN_REQUIRED=true`
— sin activación explícita, ningún dato sale del servidor. Paquete
`external_processing/` separado de `external_ai/` (distinto rol: aquí es
transcripción/OCR/análisis de imagen/embeddings/reranking, no revisión de
candidatos). Componentes: `planner.py` (`BurstPlanner` elige modo
local/hybrid/burst según umbrales configurables de duración de
audio/páginas/imágenes, siempre con `reason_codes` explicando la decisión),
`chunking.py` (división de audio/PDF/imágenes/texto con solapamiento
configurable), `dispatcher.py` (concurrencia limitada, reintentos con
backoff exponencial, circuit breaker, cancelación cooperativa),
`result_validator.py` (7 comprobaciones: schema, hash, rangos, workspace,
idioma, detector de secretos, detector de rutas privadas),
`result_merger.py` (fusiona segmentos externos y **nunca** escribe en Neo4j
ni llama a `ingest_approved`), y un proveedor `MockExternalProcessingProvider`
que cubre 10 escenarios de prueba (éxito, timeout, rate-limit, error
permanente...). Adaptador NVIDIA con capacidades verificadas en esta fase
(`EXTRACT_TEXT_ENTITIES`, `GENERATE_EMBEDDINGS`, `RERANK`,
`REVIEW_CANDIDATES`); ASR/OCR/imagen quedan como `UnsupportedCapabilityError`
hasta la Fase B2. Máquina de estados con 9 estados y transiciones
prohibidas explícitas. Migración SQLite aditiva sobre la tabla `jobs`
existente (columnas nuevas en NULL para jobs previos, compatibilidad total).
88 tests en 10 archivos. Fases pendientes: **B2** (proveedores ASR/OCR/imagen
reales) y **B3** (activación en producción, integración con el worker de
jobs, métricas históricas, alertas de fallo).

---

<a id="cap7"></a>
## 7. Seguridad, usuarios y acceso externo

Cómo se protege el acceso al visor y a los datos: el modelo de
usuarios/personajes/permisos por bóveda, la exposición controlada a
Internet (dominio público, Basic Auth, cierre de Neo4j) y el sistema de
autenticación propio del visor que sustituyó progresivamente al Basic Auth
de nginx.

<a id="d07"></a>
### 07 · Usuarios, personajes y permisos
*origen: 07-users-permissions.md*

Implementación base en `data-engine/app/access/access_store.py` (SQLite
`state/access.db`). Modelo: un usuario puede tener varios personajes, uno
activo por `workspace`; tabla intermedia `user_character_link` con estados
`pending/approved/rejected/revoked/assigned`; el admin asigna directamente o
aprueba solicitudes; `user_workspace_permission` define permisos **por
bóveda** (no globales): tipos de entidad visibles, sesión máxima visible,
flags de contenido sensible; `access_audit_log` con 7 tipos de evento.
Visibilidad en dos niveles: por sesión/campaña (público/grupo hasta la
sesión visible) y por **conocimiento de personaje** (un usuario en modo
`character_knowledge` solo ve una entidad si es pública/de grupo dentro de
la sesión visible, o si su personaje tiene una relación de conocimiento con
ella, participó en un evento donde apareció, o se la compartieron) — nunca
ve contenido `secret/narrator/future/reference/manual/admin_only` sin
permiso explícito. Estado en el momento de redacción: modelo y almacén
**implementados** (selftest OK); aplicación real de los filtros
**pendiente** (vive en el visor/API futuros, aunque el grafo ya guarda las
propiedades necesarias).

<a id="d21"></a>
### 21 · Acceso externo y seguridad
*origen: 21-external-access-and-security.md*

Actualizado 2026-07-15. Tabla de vías de acceso al visor: LAN, Tailscale y
dominio público `https://knowledge.seccionnueve.duckdns.org`. Acceso
externo vía **nginx en VM104** (reverse proxy, certificado wildcard Let's
Encrypt, Basic Auth con `.htpasswd_s9knowledge`, cabeceras de seguridad
HSTS/X-Frame-Options/etc.); nota histórica: ese subdominio apuntaba antes a
SilverBullet y se repuntó al visor. Seguridad de Neo4j: el contenedor
exponía 7474/7687 en `0.0.0.0` (accesible desde LAN/Tailscale); el
2026-07-12 se cerró a **solo 127.0.0.1**. Ni Neo4j, ni Ollama, ni Nextcloud
interno se exponen a Internet; no se abrieron puertos nuevos en el router.
Introduce la **autenticación propia del visor** (rama
`feat/viewer-auth-foundation`, implementada pero no activada en producción
en el momento de este documento — ver docs/44 para el diseño completo), con
un plan de doble barrera durante la transición (Basic Auth de nginx + login
propio) y su retirada posterior del Basic Auth una vez verificado el login
propio en producción durante al menos una semana. Pendiente de seguridad en
ese momento: activar `S9K_AUTH_ENABLED=true` en producción, retirar Basic
Auth tras verificación, y considerar Cloudflare Access/OIDC como fase
futura.

<a id="d44"></a>
### 44 · Autenticación del visor S9 Knowledge
*origen: 44-viewer-authentication-and-users.md*

Implementado en `feat/viewer-auth-foundation-clean` (julio 2026). Sistema
completo de autenticación/autorización basado en sesiones server-side,
**opt-in** (`S9K_AUTH_ENABLED=false` por defecto = comportamiento idéntico
al anterior). Almacenamiento SQLite en `viewer/state/auth.db`; hash de
contraseña Argon2id → bcrypt → PBKDF2-SHA256 (solo fallback dev); sesiones
por token CSPRNG (solo SHA-256 en DB); CSRF por HMAC-SHA256; cookies
`HttpOnly`/`Secure`/`SameSite=Lax`. **Endurecimiento de seguridad (Fase
A4)**: todas las APIs protegidas (401 JSON anónimo, 403 JSON rol
insuficiente, 302 a `/login` en HTML), CSRF de login firmado y temporal
ligado a cookie *double-submit*, validación de arranque que **aborta el
servicio** si el secreto CSRF es vacío/placeholder/corto/de baja entropía o
si el backend de contraseñas no es Argon2id/bcrypt en producción,
middleware fail-closed ante cualquier fallo del backend de auth, `/docs`
y `/redoc` no registrados por defecto (solo admin si se exponen
explícitamente). Roles: `admin > reviewer > viewer`, con matriz de permisos
por ruta (p.ej. `/reviews` solo reviewer+, `/admin/*` solo admin). Primer
arranque requiere crear administrador por CLI (`create-admin`, contraseña
nunca por línea de comandos). CLI administrativa completa (`create-user`,
`set-password`, `set-role`, `enable/disable-user`, `unlock-user`,
`revoke-sessions`, `cleanup-sessions`, `status`). Auditoría append-only en
`audit_events` (login, logout, cambios de rol/contraseña, acceso denegado...),
con IP/user-agent almacenados solo como prefijo SHA-256. Limitaciones
declaradas: sin recuperación de contraseña por email, sin MFA, sin
OIDC/OAuth2, identidad del operador aún no conectada a `review_manual.py`
ni al writer de ingesta.

---

<a id="cap8"></a>
## 8. Operaciones, backup y healthchecks

Cómo se mantiene el sistema en marcha una vez desplegado: el diseño original
del visor/panel, el procedimiento verificado de backup y restore de Neo4j
(con su validación real en producción), el sistema de healthchecks de solo
lectura, y las mejoras de usabilidad del visor de solo lectura.

<a id="d06"></a>
### 06 · Visor y panel
*origen: 06-viewer-panel.md*

Actualizado 2026-07-13 con una nota destacada: **el visor básico ya estaba
en producción** desde el commit `1fd94b85` (v0.2.5b), contradiciendo el
resto del documento que describía el visor como diseño pendiente — esa
contradicción se corrigió explícitamente (ver también docs/24, capítulo 2).
El resto del documento queda como referencia de diseño para funcionalidades
aún pendientes en ese momento: vistas del visor de solo lectura (grafo
global, bestiario, enemigos activos, cronología, red social...) con filtros
transversales (`workspace`, `visibility`, `knowledge_layer`,
`review_status`, personaje activo); panel de gestión (`/control/users`,
`/control/visibility`, alta de fuentes); endpoints REST previstos para
gestión de fuentes/jobs; y modos de visualización
(`admin_full`, `narrator`, `party`, `session_public`, `character_knowledge`).
Buena parte de este diseño se materializó después (ver capítulos 2, 7 y este
mismo capítulo, docs/44 y docs/48).

<a id="d26"></a>
### 26 · Operaciones: Backup y Restore de Neo4j
*origen: 26-operations-backup-and-restore.md*

**Método verificado en laboratorio, 2026-07-13**, aplicable a
`neo4j-knowledge` en VM105 (Neo4j 5.26.0 Community). Restricción
fundamental: Community Edition **no soporta backup en caliente** —
`neo4j-admin database dump` exige el contenedor parado (~2-5 min de
inactividad). Procedimiento completo paso a paso documentado (parar
contenedor, dump con imagen temporal, checksum SHA-256, arrancar, esperar
`healthy`, verificar conteo de nodos) y su contraparte de restore
(verificar checksum, parar, `neo4j-admin database load
--overwrite-destination=true`, arrancar, validar). Nota técnica descubierta
en el lab: el directorio destino del dump requiere `chmod 777` (UID 7474 del
proceso `neo4j`). Retención recomendada: pre-ingesta (manual), semanal (4
semanas), mensual (6 meses) — timer systemd **diseñado pero pendiente** de
ventana de mantenimiento en el momento de redacción. Resultados del
laboratorio: backup de 3 nodos de prueba → dump 13.8 KB → restore en volumen
nuevo → 3 nodos idénticos, sin interrumpir producción. Historial real:
backup de producción ejecutado 2026-07-13 21:49 UTC (132 KB, checksum
verificado) — el dictamen completo con datos reales vive en docs/32.

<a id="d32"></a>
### Validación de Backup Real en Producción — 2026-07-13
*origen: 32-production-backup-restore-validation.md*

Primer backup real de Neo4j en producción, restaurado en instancia aislada y
validado con rollback por `source_id` en laboratorio. Commit de producción
`cef9233`. Secuencia completa: preflight (Neo4j healthy, espacio libre,
`S9K_ALLOW_REAL_INGEST` no configurada, scripts auditados con
`set -euo pipefail` y trampas de emergencia) → dry-run (confirmado que no
detiene Neo4j ni crea dump) → **backup real** (ventana de ~25s de parada,
132 KB, SHA256 `c3179c01...`) → **copia externa a yggdrasil** (2026-07-14,
vía ia-server como intermediario en dos saltos SCP porque VM105 no tiene
SSH directo a yggdrasil; checksums idénticos en origen y destino, permisos
700/644) → **restore en instancia aislada** (red `--network none`,
199 nodos/140 relaciones/14 labels/28 tipos de relación/2 índices,
idénticos a producción) → **rollback por fuente en laboratorio** (datos
sintéticos, patrón Cypher transaccional de 3 operaciones: eliminar nodos
exclusivos, actualizar `source_ids` de nodos compartidos, eliminar
relaciones exclusivas — validado, sin script de orquestación con
`--dry-run` todavía). Estado final de producción verificado: Neo4j y
servicios intactos, sin cambios. **Dictamen: Backup real COMPLETADO,
checksum VERIFICADO, copia al hipervisor COMPLETADA Y VERIFICADA, restore
del *dump de Neo4j* en instancia aislada COMPLETADO, rollback por fuente
VALIDADO EN LABORATORIO — Prioridad 1 COMPLETADA.** Endurecimiento operativo
pendiente (P1.1): automatizar la copia, script transaccional de rollback con
`--dry-run`, timer systemd de backup semanal, prueba periódica de restore.
**Corrección 2026-08-09, dos veces: (a) la copia al hipervisor `yggdrasil`
NO es off-host —misma máquina física—, y el P0 de replicación externa sigue
abierto; (b) «restore real aislado» era el restore del dump de Neo4j, no la
recuperación de VM105. El primer restore de la máquina completa se ensayó el
2026-08-08 (ver docs/53).**

<a id="d46"></a>
### 46 · Observabilidad y healthchecks operacionales (Tarea A)
*origen: 46-operational-healthchecks.md*

Estado en el momento de redacción: **auditoría inicial / en curso**, rama
`feat/operational-healthchecks`. Sistema de solo lectura, no reinicia
servicios ni escribe en Neo4j. Decisión de ubicación: el paquete vive en
`viewer/app/health/` (no en `data-engine/`) porque el visor es el servicio
siempre activo. Componentes creados: `models.py`/`checks.py` (11
componentes)/`runner.py`/`storage.py` (último informe JSON 0600), endpoints
`GET /api/admin/health` (JSON) y `GET /admin/health` (panel, ambos exigen rol
admin), CLI `python -m app.cli.health` (`check`/`report`/`json`, exit codes
0/1/2/3), y unit/timer systemd `s9-knowledge-healthcheck.{service,timer}`
(oneshot + timer **horario**, `Persistent=true`, `RandomizedDelaySec=5m` —
**no instalado en producción en el momento de este documento**; sí lo estaba
en 2026-07-18 según docs/02). Contrato JSON público fijado: estado
`HEALTHY|DEGRADED|UNHEALTHY|UNKNOWN` por componente
(`viewer, neo4j, ollama, nextcloud_rclone, job_store, auth_db, external_ai,
burst, filesystem, backups, systemd`), con `details` sanitizados. Umbrales de
disco: warning ≥80%, critical ≥90%. 34 tests. Módulos explícitamente no
tocados: writer de ingesta, runtime de `external_processing`, escrituras en
Neo4j, internals de auth.

<a id="d48"></a>
### 48 · Visor de solo lectura — mejoras de usabilidad (Tarea C)
*origen: 48-viewer-readonly-usability.md*

**Implementado**, rama `feat/viewer-readonly-usability` fusionada en `main`.
Estrictamente de solo lectura: 0 escrituras en Neo4j, verificado
automáticamente por un test que falla si aparece un token de escritura
(CREATE/MERGE/SET/DELETE/...) en el router `readonly.py`, y por tests que
comprueban que el router solo expone GET/HEAD/OPTIONS. Rutas nuevas:
`/entities` y `/entities/{id}` (viewer+), `/sources` y `/sources/{id}`
(reviewer+), `/quality` (reviewer+, métricas de calidad: distribución por
tipo/estado/confianza, gaps de datos), todas con versión API JSON con
envelope `{items, pagination, filters}` y paginación empujada al proveedor
de datos (Neo4j `SKIP/LIMIT`, no en memoria). Allowlist de ordenación
(`sort`), búsqueda `q` con `CONTAINS` (no fulltext), timeouts configurables.
Seguridad: Jinja2 autoescape activo, datos del grafo inyectados con
`textContent` (no `innerHTML`), Cypher siempre paramétrico, `elementId(n)`
en vez de `id(n)`. `vis-network` vendorizado localmente (sin CDN, con
integridad SRI) — el visor funciona sin acceso a Internet. Recomienda (sin
crearlos automáticamente) varios índices Neo4j de rendimiento. Suite viewer:
194 tests pasan (46 de ellos en `test_readonly.py`).

---

<a id="cap9"></a>
## 9. Despliegues RC y regresiones de despliegue

Dos episodios operativos concretos: la reparación de la suite de tests para
que fuera reproducible en clones limpios (con CI añadida), y una regresión
real de despliegue detectada y corregida — la resolución de referencias de
Git "hacia delante" que duplicaba el ref y rompía el checkout.

<a id="d31"></a>
### 31 · Test Remediation and CI Report
*origen: 31-test-remediation-and-ci-report.md*

Fecha 2026-07-13, rama `fix/tests-imports-cache-and-ci`. Situación inicial:
184 tests de data-engine + 36 de viewer pasaban por separado (220 total),
pero la ejecución **combinada** producía 5 errores de colección. Causa
raíz (CR-1): `data-engine/app/__init__.py` vacío registraba el paquete
Python `app` en `sys.modules`, y cuando pytest llegaba a
`viewer/tests/`, el import `from app.config import Settings` fallaba porque
`sys.modules['app']` ya apuntaba al `app` equivocado; además,
`tests/__init__.py` vacíos duplicados en ambos proyectos causaban
`ImportPathMismatchError`. Solución: eliminar los tres `__init__.py` vacíos
problemáticos y reescribir el `conftest.py` raíz para insertar ambos paths
explícitamente. Otras causas sospechadas (CR-2 a CR-4: firma de
`create_job()`, `VALID_SOURCE_KINDS`, `HAS_FOUGHT→FOUGHT_AT`) resultaron ya
estar alineadas — sin cambios necesarios. Resultado: errores de colección
combinada 5→**0**, 220 tests pasando, duración 6.45s. Se añadió
`.github/workflows/ci.yml` con 4 jobs (data-engine, viewer, combinada,
comprobación de rutas hardcodeadas `/opt/`). Producción no se tocó en
ningún momento.

<a id="d51regression"></a>
### 51 · Regresión de despliegue "forward-ref" y contrato de resolución de refs
*origen: 51-deploy-forward-ref-regression.md*

Estado: **corregido**, fecha 2026-07-18, rama
`fix/deploy-forward-ref-regression`. Síntoma: un despliegue hacia un tag o
commit todavía no materializado en el object store de la release activa
fallaba al resolver la referencia — el caso **normal** de un deploy hacia
delante. Causa raíz: el patrón histórico de resolución
(`git rev-parse "$ref" || printf '%s' "$ref"`) hacía que, al fallar
`rev-parse`, tanto el propio comando como el fallback imprimieran el mismo
ref, dejando la variable con el valor **duplicado en dos líneas**
(`"deploy-v0.3.0-rc5\ndeploy-v0.3.0-rc5"`), lo que rompía el checkout
posterior con "invalid refspec"/"ambiguous argument". Un fix anterior (PR
#33) había corregido el síntoma inmediato pero de forma dispersa, sin
contrato único ni prueba automatizada. Corrección definitiva: función
centralizada `resolve_release_commit()` en `lib.sh`, con contrato estricto —
stdout es **exclusivamente** el SHA del commit (nunca el ref ni mensajes),
rechaza refs que empiecen por `-` (inyección de opciones), con espacios,
saltos de línea o caracteres fuera de `[A-Za-z0-9._/-]`, rechaza ambigüedad,
valida que el objeto sea un commit, y solo hace `fetch` sobre la copia nueva
de la release (nunca sobre `current`, para no romper su checksum). Prueba de
regresión con repositorios git **reales** (no mocks) que reproduce
exactamente el escenario del ref ausente y demuestra que el patrón antiguo
duplica el ref mientras que el nuevo devuelve un único SHA limpio, más
numerosos casos límite (tag ausente, SHA inexistente, origin inaccesible,
shallow clone, inyección, branch rechazada en modo release...).

---

<a id="cap10"></a>
## 10. Auditoría, onboarding y dosier del proyecto

Capítulo final: las reglas operativas transversales del proyecto (auditar
antes de trabajar), la guía de onboarding para clonar el repositorio en un
PC Windows, y los dos documentos "paraguas" que indexaban y hacían de
checklist maestra de todo lo demás — hoy sustituidos, en la práctica, por
este mismo documento consolidado y por `docs/02-current-state.md` /
`docs/project-status.yaml` como fuente de verdad vigente.

<a id="d09"></a>
### 09 · Auditar antes de trabajar
*origen: 09-audit-before-work.md*

Regla del proyecto: antes de programar cualquier cosa nueva, auditar lo que
ya existe, para no repetir trabajo ni pisar lo hecho. Checklist previa: qué
archivos y documentos existen ya, qué versión de schema/prompt está activa,
qué tests pasan, qué está implementado frente a solo diseñado, qué es
producción y no se toca (Neo4j, Ollama, SilverBullet, Nextcloud). Antes de
tocar producción: backup del dato afectado, cambio mínimo y localizado,
prueba mínima reproducible, nunca declarar "resuelto" sin prueba real, nunca
procesar en lote antes de validar individualmente. Fuentes de verdad, en
orden: el código en `data-engine/app`, `docs/current/INFORME_ENTREGA.md`,
Neo4j real, y el conjunto `docs/00–10` (visión y estado).

<a id="d10"></a>
### 10 · Clonar en el PC (Windows)
*origen: 10-clone-on-windows.md*

Guía de onboarding para clonar el repositorio en un PC Windows (ruta con
espacios `E:\Projectos Esp32\S9 Knowledge`), con los comandos PowerShell de
`git clone` y la advertencia de entrecomillar siempre las rutas con
espacios. Tras clonar: copiar `.env.example` a `.env` y rellenar valores
reales (no se sube al repo); `.venv`, estado de runtime y bases SQLite no
vienen en el repo, se recrean localmente. El repo del PC es el de trabajo
principal; VM105 conserva la instalación de producción.

<a id="dindex"></a>
### Índice de documentación — S9 Knowledge (histórico)
*origen: INDEX.md*

Era el índice general de `docs/`, con una clasificación explícita
(`vigente · operativo · diseño · auditoría · histórico · deprecado`) y la
advertencia de que el estado autoritativo vivía en
`02-current-state.md`/`project-status.yaml`, nunca en los informes
individuales. Enumeraba, con una frase de resumen cada uno, todos los
documentos vigentes/operativos de despliegue (46 a 51), toda la
documentación numerada del repositorio (00 a 37), y marcaba como
**histórico** los documentos de diseño inicial en `docs/current/`
(`INFORME_ENTREGA.md`, `RPG_GRAPH_MODEL_UPDATE.md`, `VISOR_DESIGN.md`,
`EXTERNAL_SOURCES_DESIGN.md`, `KNOWLEDGE_VISIBILITY_DESIGN.md`,
`USERS_CHARACTERS_DESIGN.md`, no tocados por esta consolidación) y los DOCX
de diseño inicial en la raíz del repo (superados por las versiones Markdown
en `docs/02` y `docs/03`). Todo el contenido factual que indexaba está ahora
sintetizado en los capítulos 1 a 9 de este documento; este archivo en sí
queda archivado como referencia de la organización histórica de `docs/`.

<a id="ddossier"></a>
### Project dossier and checklist
*origen: project dossier and checklist.md*

Documento de coordinación maestro histórico, fechado 2026-07-13 (revisando
el commit `1fd94b8`, tag `v0.2.5b`), con un aviso explícito al inicio de que
**está superado por producción** — a 2026-07-18 el estado real es RC5.1
(ver capítulo 2, docs/02). 33 secciones: leyenda de estados
(✅ cerrado, 🟢 operativo declarado, 🟡 parcial, 🟠 preparado, ❌ pendiente,
⚠️ riesgo, 🔍 verificación requerida), resumen ejecutivo, arquitectura
funcional en 7 capas, estado por 23 componentes, catálogo de 9
inconsistencias documentales corregidas, plan de actualización de 21
documentos, 4 *quality gates* obligatorios (merge, despliegue, escritura en
Neo4j, acceso de jugadores), tabla de riesgos, lista explícita de
**decisiones que no conviene tomar todavía** (no desbloquear ingesta masiva,
no fusionar duplicados automáticamente, no migrar SQLite sin métricas, no
sustituir todo por LLM, no migrar a Docker sin necesidad, no desarrollar
modo jugador antes de definir permisos...), y un **orden de 14 prioridades**
(0 estado verificable → 1 backup/restore/rollback → 2 calidad de extracción
→ 3 pruebas/CI → 4 primera ingesta controlada → 5 limpieza del grafo → 6
login/seguridad → 7 acciones de revisión → 8 permisos RPG → 9
Nextcloud/workspaces → 10 jobs/multimedia → 11 replicabilidad → 12
refactorización → 13 rendimiento/escala) que coincide con la progresión
histórica real documentada en el resto de capítulos de este consolidado.
Regla de mantenimiento clave, reiterada en todo el dosier: ninguna tarea se
marca cerrada solo porque exista código — necesita pruebas, evidencia
operativa, documentación y, si toca datos, procedimiento de reversión.
Checklist maestra de cierre (sección 31): commit en VM105 confirmado
(`1fd94b85`), 196 tests recopilados/155 aprobados/41 fallidos (deuda
técnica), documentación corregida, bloqueo de ingesta por defecto
confirmado — todo esto coincide con y está desarrollado en detalle en
docs/24 y docs/30 (capítulo 2). El resto de contenido factual (estado por
componente, prioridades, historial) está recogido y actualizado en los
capítulos 2 a 9 de este documento consolidado.

---

<a id="cap11"></a>
## 11. Nota de continuidad — desarrollo posterior a este consolidado (V3)

*Añadida: 2026-08-05. Este capítulo no sintetiza informes archivados como los
anteriores: es un puntero breve al estado vivo, para que este documento no
quede leyéndose como si el proyecto se hubiera detenido el 2026-07-27. El
detalle completo, con cifras y artefactos, vive en `docs/v3/` (ver su índice,
[`docs/v3/README.md`](v3/README.md)) y en el `README.md` de la raíz del
repositorio, ambos actualizados junto con esta nota.*

Después del cierre de este consolidado, sobre la línea V3 ya mergeada en
`main` (capítulos anteriores no la cubren: es posterior a los informes que
sintetizan), se cerraron dos programas de calidad más y avanza un tercero:

- **Puerta 4 — cobertura del extractor** (PRs #124-#130,
  `docs/v3/42-gate4-cierre-programa.md`): veredicto **PARCIAL**. Cobertura
  E2E de desarrollo 0.607 (conforme, umbral ≥0.60); recall de
  auto-aprobación SIMPLE 0.10 (no conforme, umbral ≥0.70); carril semántico
  NVIDIA en sombra insuficiente (0.357); invariantes de precisión intactos.
  Carril OCR validado con Tesseract 5.5.0 real en VM105
  (`docs/v3/39-carril-ocr.md`); Tesseract queda documentado como requisito
  de instalación adicional (`docs/v3/28-requisitos-de-instalacion.md`).
- **Puerta 6 — factividad composicional** (PRs #131-#133 y #136,
  `docs/v3/46-gate6-cierre-programa.md`): veredicto **CONFORME CON
  RESERVAS**, ratificado por el operador el 2026-08-05. El rework del
  bloque B2 conectó el operador de discurso reportado al extractor real de
  producción (estaba desconectado — código muerto para el extractor
  determinista — hasta ese rework). El criterio de "acuerdo
  determinista∧NVIDIA" se abandonó para esta puerta (Postura A del
  operador).
- **Medición del acuerdo determinista∧NVIDIA** (PRs #134-#135,
  `docs/v3/47-acuerdo-det-nvidia.md`, `docs/v3/48-acuerdo-eval2.md`):
  acuerdo activo 27/27 en la primera medición, 1.000 en un corpus de
  evaluación ampliado. El operador ratificó un **piloto controlado** (se
  ejercita la política con datos reales sin reducir todavía la revisión
  humana); pasar de piloto a reducción real queda **gateado al despliegue de
  V3 y a la primera ingesta autorizada**.
- **Programa multi-partida** (separación juego/partida, PR #137 de diseño +
  bloque M0 en PR #138, `docs/v3/49-multipartida-diseno.md`): **en curso**.
  M0 (contratos, `partida_id` en la tubería) mergeado en `main` (`ccf0fe4`).
  M1 (mapeo de ingesta Nextcloud→ámbito) bloqueado a que Nextcloud vuelva a
  estar disponible. M2 (resolutor) en desarrollo en una rama separada — no
  documentado todavía en este repositorio al momento de escribir esta nota.
- **Dependencias**: aiohttp actualizado a 3.14.3 por CVE-2026-59881/69243/69244
  (PR #128); httpx, argon2-cffi, fastapi, jinja2 y pytest actualizados vía
  Dependabot (PRs #119-#123).

**Estado operativo (sin cambios respecto al capítulo 2 de este documento):**
producción en VM105 sigue en `deploy-v0.3.0-rc5.1`; V3 **no** está desplegada
todavía; el timer/ingesta reales siguen sin autorizar; Nextcloud está caído
(no afecta al repositorio, sí bloquea el bloque M1 de multi-partida). No
tomar ninguna cifra de este capítulo como definitiva sin comprobarla contra
el documento fuente citado — es, deliberadamente, un resumen y no una
síntesis exhaustiva.
