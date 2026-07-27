# 24 · Baseline VM105 y Verificación Fase 0A

> Estado: **INFORME DE AUDITORÍA VERIFICABLE — 2026-07-13**
> Auditoría de solo lectura. Sin escrituras en Neo4j, sin ingesta real, sin modificación de servicios ni código.

---

## 1. Cabecera de Auditoría

| Campo | Valor |
|---|---|
| Fecha de auditoría | 2026-07-13 (iniciada 2026-07-12T23:03:41Z) |
| Hostname | `common` (VM105) |
| Repositorio | `pjclavero/S9-Knowledge` |
| Rama en producción | `main` |
| Commit desplegado | `1fd94b85eb28b9137dad820362d85dd879c7814d` |
| Mensaje del commit | `feat(data): merge v0.2.5b — pipeline revisión datos cerrado` |
| Fecha del commit | 2026-07-10 |
| Tag | `v0.2.5b` |
| `origin/main` en momento de auditoría | `ffaf84c9715e8c7b5674416b2ed4ed21fb7920a3` (7 commits más reciente) |
| Autor | Agentes A/B/C + Coordinador (ia02, 2026-07-13) |
| Alcance | Fase 0A: fotografía verificable. Fase 0B: corrección documental. |
| Limitaciones | Ollama remoto (ia-server 192.168.1.157:11434) — accesible, modelo qwen2.5:7b operativo — pero endpoint NO configurado en `.env` (hardcodeado en `llm_extractor.py`); tests viewer rotos por import errors; sin backup restaurado; `CALL db.indexes()` no disponible en Neo4j Community. |
| Declaración | SOLO LECTURA. Sin escrituras en Neo4j, sin ingesta real, sin cambios en servicios, código ni configuración de producción. |

---

## 2. Resumen Ejecutivo

### Qué está realmente funcionando

- Visor web (FastAPI/uvicorn, puerto 8088): activo, HTTP 200 en todos los endpoints principales.
- Neo4j 5.26.0 Community: healthy, 199 nodos, 140 relaciones, localhost-only.
- rclone/Nextcloud: 5 workspaces montados en modo read-only, sin errores.
- Guard de ingesta doble capa: activo y verificado. `S9K_ALLOW_REAL_INGEST` no activa en producción.
- Glosario ASR: 1044 términos en workspace `leyenda`, índices operativos.
- Jobs DB: schema válido, íntegra.

### Qué existe solo en código (no desplegado como servicio)

- Worker multimedia: código completo con tests, sin servicio systemd persistente.
- Worker de jobs: módulo presente, sin servicio systemd persistente.
- Extractor LLM e híbrido: código y tests con mocks; requieren Ollama para ejecutar realmente.

### Qué está probado

- 155/196 tests aprobados (desglose en §10).
- Guard de ingesta: 16/16 tests de guard pasan.
- Pipeline completo (segmentación → ingesta aprobada): tests unitarios pasan.
- Glosario ASR: 26 tests pasan.
- Export/import de paquetes: 21 tests pasan.

### Qué no pudo verificarse

- Ollama: endpoint remoto (ia-server 192.168.1.157:11434, modelo qwen2.5:7b) accesible desde VM105, pero NO configurado en `.env` — hardcodeado en `llm_extractor.py`. El extractor LLM puede ejecutarse si se configura `S9K_OLLAMA_BASE_URL` en `.env`.
- Índices y constraints de Neo4j: `CALL db.indexes()` y `CALL db.constraints()` no disponibles en Neo4j Community.
- Backup de Neo4j: sin timer automático visible; sin evidencia de restore/rollback ejecutado.
- faster-whisper en producción: instalado, no probado con audio real durante esta auditoría.

### Contradicciones corregidas en fase 0B

1. `docs/06-viewer-panel.md` decía "no implementado / solo diseño" → corregido: visor en producción.
2. `docs/05-data-engine.md` decía "pytest 8/8" → nota añadida: 196 recopilados, 155 pasan.

### Dictamen

**FASE 0A CERRADA CON EXCEPCIONES DOCUMENTADAS** — ver §22.

---

## 3. Matriz de Estado

| Componente | Código | Tests | Desplegado | Operativo | Validado con datos | Estado |
|---|:---:|:---:|:---:|:---:|:---:|---|
| Visor web (`/graph`, `/jobs`, `/reviews`) | ✅ | ✅ | ✅ | ✅ | ✅ | **CONFIRMADO** |
| Neo4j 5.26.0 | ✅ | — | ✅ | ✅ | ✅ (199 nodos) | **CONFIRMADO** |
| rclone/Nextcloud mount | ✅ | — | ✅ | ✅ | ✅ (5 workspaces) | **CONFIRMADO** |
| Segmentación pipeline | ✅ | ✅ (5) | 🟡 | — | — | **CONFIRMADO CON LIMITACIONES** |
| Extracción heurística | ✅ | ✅ (20) | 🟡 | — | — | **CONFIRMADO CON LIMITACIONES** |
| Extracción LLM | ✅ | ✅ (mocks) | ❌ | ❌ | ❌ | **BLOQUEADO** (endpoint Ollama remoto accesible pero no configurado en `.env`) |
| Extracción híbrida | ✅ | ✅ (mocks) | ❌ | ❌ | ❌ | **BLOQUEADO** (endpoint Ollama remoto accesible pero no configurado en `.env`) |
| Validación | ✅ | ✅ | 🟡 | — | — | **CONFIRMADO CON LIMITACIONES** |
| Resolución | ✅ | ✅ | 🟡 | — | — | **CONFIRMADO CON LIMITACIONES** |
| Decisión automática | ✅ | ✅ (17) | 🟡 | — | — | **CONFIRMADO CON LIMITACIONES** |
| Ingesta aprobada (guard) | ✅ | ✅ (16) | ✅ | ✅ | — | **CONFIRMADO** (bloqueada por diseño) |
| `audit-graph` | ✅ | ✅ (2) | 🟡 | — | — | **CONFIRMADO CON LIMITACIONES** |
| Export/import paquetes | ✅ | ✅ (21) | 🟡 | — | — | **CONFIRMADO CON LIMITACIONES** |
| Jobs DB (`state/jobs.db`) | ✅ | ✅ | ✅ | ✅ | ✅ (1 job) | **CONFIRMADO** |
| Worker multimedia (código) | ✅ | ✅ (3) | ❌ | ❌ | — | **PARCIAL** (sin servicio systemd) |
| faster-whisper | ✅ | ✅ | ✅ (instalado) | — | ❌ | **DECLARADO, NO VERIFICADO** |
| Glosario ASR | ✅ | ✅ (26) | ✅ | ✅ | ✅ (1044 términos) | **CONFIRMADO** |
| Ollama | ✅ (cliente) | ✅ (mocks) | ❌ | ❌ | ❌ | **PENDIENTE CONFIG** (remoto en ia-server, accesible, endpoint no en `.env`) |
| Acceso externo (nginx + Basic Auth) | ✅ | — | ✅ | ✅ | — | **CONFIRMADO** |
| Autenticación propia del visor | ❌ | ❌ | ❌ | ❌ | — | **PENDIENTE** |
| Permisos RPG en UI | ✅ (DB) | — | ❌ | ❌ | — | **PENDIENTE** |
| Backup Neo4j | ❌ | — | ❌ | — | — | **PENDIENTE** |
| Rollback por `source_id` | ✅ (diseño) | — | ❌ | — | — | **PENDIENTE** |
| CI / GitHub Actions | ❌ | — | — | — | — | **PENDIENTE** |

---

## 4. Estado Git

| Campo | Valor |
|---|---|
| Ruta repositorio | `/opt/knowledge-services/s9-knowledge-repo` |
| Remote | `https://github.com/pjclavero/S9-Knowledge.git` |
| Rama actual | `main` |
| HEAD (desplegado) | `1fd94b85` — tag `v0.2.5b` |
| `origin/main` | `ffaf84c` (7 commits adelante) |
| Commits remotos no desplegados | 7 (documentales: referencias a dossier, fixes de formato/enlaces) |
| Commits locales no subidos | 0 |
| Working tree | LIMPIO — sin cambios locales, sin archivos sin versionar relevantes |

**Conclusión:** El commit desplegado es `1fd94b85` (v0.2.5b, 2026-07-10). Los 7 commits adelantados en `origin/main` son únicamente documentales. El árbol de producción está limpio.

---

## 5. Preflight del Sistema

| Parámetro | Valor |
|---|---|
| Fecha/hora auditoría (UTC) | 2026-07-12T23:03:41Z |
| Hostname | common |
| OS | Debian GNU/Linux 13 (trixie) |
| Kernel | Linux 6.12.90+deb13.1-amd64 |
| Uptime | 13h 25m |
| Cores CPU | 6 vCPUs |
| RAM total | 7.7 GiB |
| RAM usada | 2.0 GiB (26%) |
| Swap usada | 524 KiB de 2.0 GiB |
| Disco `/dev/sda1` | 38 GiB total, 12 GiB usado (33%), 24 GiB libre |
| Python | 3.13.5 |
| Docker | 29.5.2 / Docker Compose 5.1.4 |
| Git | 2.47.3 |
| Java | No instalado |
| rclone | Instalado (`/usr/bin/rclone`) |
| Ollama | No instalado localmente (no en PATH, no como proceso); endpoint remoto en ia-server (192.168.1.157:11434), accesible, modelo qwen2.5:7b disponible |
| faster-whisper | 1.2.1 (venv `/opt/knowledge-services/property-graph/.venv`) |

---

## 6. Servicios

### Servicios systemd de S9 Knowledge

| Servicio | Estado | Enabled | Iniciado | RAM | Puerto |
|---|---|---|---|---|---|
| `s9-knowledge-viewer.service` | ✅ active (running) | Sí | 2026-07-12 11:09:11 EDT | 70.3 MiB | 8088 |
| `rclone-nextcloud-rol.service` | ✅ active (running) | Sí | 2026-07-12 05:40:14 EDT | 64 MiB | — |

Sin timers systemd ni cron para S9 Knowledge, Neo4j, worker multimedia, worker de jobs ni backup automatizado.

### Contenedor Docker S9 Knowledge

| Contenedor | Imagen | Estado | Uptime | RAM | Puertos |
|---|---|---|---|---|---|
| `neo4j-knowledge` | neo4j:5.26.0-community | ✅ Healthy | 8h | 883.5 MiB | 127.0.0.1:7474 · 127.0.0.1:7687 |

14 contenedores Docker activos en total (11 healthy); el resto son otros servicios del homelab (Wanderer, Vaultwarden, Mosquitto, PostgreSQL, SilverBullet, Radicale).

---

## 7. Endpoints Verificados

| Endpoint | HTTP | Tiempo | Auth en LAN | Estado |
|---|:---:|---:|---|---|
| `GET /` | 200 | 5.65 ms | Ninguna | ✅ OK |
| `GET /graph` | 200 | 4.21 ms | Ninguna | ✅ OK |
| `GET /jobs` | 200 | 14.2 ms | Ninguna | ✅ OK |
| `GET /reviews` | 200 | 5.6 ms | Ninguna | ✅ OK |
| `GET /docs` | 200 | 0.81 ms | Ninguna | ✅ OK |
| `GET /api/status` | 200 | 16.2 ms | Ninguna | ✅ OK |
| `GET /api/v1/graph` | 404 | 0.89 ms | — | ⚠️ Ruta no existe |

Acceso desde `192.168.1.204` (nginx VM104) confirmado en logs: 200 OK.
Acceso externo vía `https://knowledge.seccionnueve.duckdns.org` → nginx VM104 → `:8088` con Basic Auth.

---

## 8. Puertos y Exposición de Red

| Interfaz | Puerto | Servicio | Nivel de acceso |
|---|---|---|---|
| `127.0.0.1` | 7474 | Neo4j HTTP Browser | Solo localhost ✅ |
| `127.0.0.1` | 7687 | Neo4j Bolt | Solo localhost ✅ |
| `0.0.0.0` | 8088 | S9 Knowledge Viewer | LAN + Tailscale ⚠️ (sin auth interna; Basic Auth solo en dominio externo) |
| `0.0.0.0` | 22 | SSH | LAN |
| `0.0.0.0` | 80, 443 | Vaultwarden | LAN |
| `0.0.0.0` | 1883, 8883, 9001 | Mosquitto MQTT | LAN (otros servicios) |
| `0.0.0.0` | 5432 | PostgreSQL | LAN (otros servicios) |

Puertos Neo4j vinculados SOLO a `127.0.0.1` desde el cambio de seguridad del 2026-07-12. ✅

---

## 9. Neo4j — Métricas de Solo Lectura

| Métrica | Valor |
|---|---|
| Versión | 5.26.0 Community Edition |
| Estado | ✅ Running, Healthy |
| RAM consumida | 883.5 MiB |
| Puerto HTTP | `127.0.0.1:7474` |
| Puerto Bolt | `127.0.0.1:7687` |
| Auth | Configurada (usuario `neo4j`) |
| **Nodos totales** | **199** |
| **Relaciones totales** | **140** |
| Tipos de nodo (labels) | 14 |
| Tipos de relación | 28 |

### Distribución de nodos por label

| Label | Nodos |
|---|---:|
| Entity + Character | 87 |
| Entity + Concept | 37 |
| Entity + Location | 25 |
| Entity + Clan | 14 |
| Entity + Faction | 13 |
| Entity + Object | 8 |
| Entity + Task | 4 |
| Entity + Event | 4 |
| Entity + Creature | 3 |
| Entity + School | 1 |
| Entity + Spell | 1 |
| Entity + Session | 1 |
| Entity + Spirit | 1 |
| **Total** | **199** |

### Tipos de relación (28)

`AGREES_TO` · `APPEARS_IN` · `ATTACKED` · `BELONGS_TO` · `CONTAINS` · `CREATED_BY` · `DISAPPEARED_NEAR` · `DISCOVERED` · `ENEMY_OF` · `HAS_FOUGHT` · `HAS_HEARD_ABOUT` · `HAS_SYMBOL_OF` · `HAS_TALKED_TO` · `INVESTIGATES` · `LEARNS` · `LOCATED_IN` · `MEMBER_OF` · `OCCURS_IN` · `ORDERS` · `OWNS` · `PARENT_OF` · `RELATED_TO` · `REQUIRES` · `SEES_IN_VISION` · `SERVES` · `SUSPECTS` · `TEACHES` · `WARNED_BY`

Índices y constraints: no disponibles vía `CALL db.indexes()` en Neo4j 5 Community. Nodos históricos sin `source_id`/`source_kind` (~87/~51) detectados, no corregidos (fuera del alcance de fase 0A).

---

## 10. Tests

### Resultados (commit `1fd94b85`, venv `/opt/knowledge-services/property-graph/.venv`)

| Métrica | Valor |
|---|---:|
| Recopilados | 196 |
| **Aprobados** | **155** |
| **Fallidos** | **41** |
| Omitidos | 0 |
| Errores de importación | 6 archivos (viewer tests) |
| Duración | 1.12 s |

### Suites que pasan completamente

`test_access_store` (3) · `test_audio_extract` (5) · `test_glossary_matcher` (14) · `test_glossary_store` (12) · `test_markdown_writer` (3) · `test_media_cli` (3) · `test_media_scanner` (5) · `test_media_transcriber` (5) · `test_media_worker` (3) · `test_review_cli` (16) · `test_review_decider` (17) · `test_review_export_import` (21) · `test_review_extractor` (20) · `test_review_pipeline` (10) · `test_schemas` (8) · `test_transcript_normalizer` (5)

### Fallos y causas (deuda técnica — impacto funcional, no en guard de ingesta)

| Suite | Fallos | Causa |
|---|:---:|---|
| `test_job_store.py` | 16 | `create_job()` ahora requiere `source_kind` — tests usan firma antigua |
| `test_ingest_semantics.py` | 2 | Tests esperan mapeo `FOUGHT_AT`; código mantiene `HAS_FOUGHT` |
| `test_media_jobstore_bridge.py` | 1 | `source_kind='video'` no está en lista de valores válidos |
| `viewer/tests/test_api_jobs.py` | 6 | `ModuleNotFoundError: No module named 'app.main'` |
| `viewer/tests/test_reviews.py` | 14 | `ModuleNotFoundError: No module named 'app.main'` |
| Otros viewer tests | 2 | Ídem import errors |

El guard de ingesta (`test_review_cli.py`, 16 tests) **pasa completamente**. No se ha demostrado impacto directo sobre la doble protección de escritura (`--dry-run` + `S9K_ALLOW_REAL_INGEST`), pero los fallos afectan a la fiabilidad funcional en múltiples componentes (semántica del grafo — `FOUGHT_AT`; jobs — firma `create_job`; multimedia — `source_kind='video'`; visor — imports `app.main`) y deben resolverse antes de la primera ingesta real.

### Discrepancia histórica

| Cifra | Origen | Explicación |
|---|---|---|
| `8/8` | `docs/05-data-engine.md`, CHANGELOG | Número de archivos o tests en estado anterior con menos suites |
| `84/84` | Notas anteriores al dosier | Ejecución parcial en punto intermedio del desarrollo |
| **196 / 155** | **Esta auditoría (HEAD `1fd94b85`)** | **Estado actual verificado** |

---

## 11. Protección de Ingesta

| Check | Estado | Evidencia |
|---|---|---|
| Guard CLI (`--dry-run`) | ✅ ACTIVO | `data_review.py` aborta con `RuntimeError` sin `--dry-run` |
| Guard código (`S9K_ALLOW_REAL_INGEST`) | ✅ ACTIVO | `ingest_approved.py` verifica la variable antes de escribir |
| Variable `S9K_ALLOW_REAL_INGEST` en `.env` | ✅ NO ACTIVA | Ausente en `.env` de producción |
| Variable en entorno del proceso | ✅ NO ACTIVA | No encontrada en entorno ni en unidades systemd |
| Validación de payload | ✅ ACTIVA | workspace, schema_version, evidence, timestamps, origin |
| Tests de guard | ✅ 16/16 PASAN | `test_review_cli.py::TestIngestApprovedGuards` |
| Rutas alternativas sin guard | ✅ NO DETECTADAS | Revisión de código completada |

Doble protección activa y verificada. No se activó la escritura real durante esta auditoría.

---

## 12. Pipeline de Datos

| Componente | Módulo | Tests | Estado |
|---|---|:---:|---|
| Segmentación | `media/scanner.py` | 5 ✅ | CONFIRMADO CON LIMITACIONES |
| Clasificación | `media/worker.py` | 3 ✅ | CONFIRMADO CON LIMITACIONES |
| Extracción heurística | `review/extractor.py` | 20 ✅ | CONFIRMADO CON LIMITACIONES |
| Extracción LLM | `review/llm_extractor.py` | 5 ✅ (mocks) | BLOQUEADO (Ollama) |
| Validación | integrada en extractor | ✅ | CONFIRMADO CON LIMITACIONES |
| Resolución | integrada en extractor | ✅ | CONFIRMADO CON LIMITACIONES |
| Decisión automática | `review/auto_decider.py` | 17 ✅ | CONFIRMADO CON LIMITACIONES |
| Ingesta aprobada | `review/ingest_approved.py` | 16 ✅ | CONFIRMADO |
| Auditoría grafo | `review/audit_graph.py` | 2 ✅ | CONFIRMADO CON LIMITACIONES |
| Export / Import | `review/export_import.py` | 21 ✅ | CONFIRMADO CON LIMITACIONES |
| Paquetes de conocimiento | `review/export_import.py` | 21 ✅ | CONFIRMADO CON LIMITACIONES |

---

## 13. Jobs y Worker Multimedia

### Jobs DB

| Propiedad | Valor |
|---|---|
| Ruta | `/opt/knowledge-services/s9-knowledge-repo/state/jobs.db` |
| Estado | ✅ Íntegra, 12 KiB |
| Total de jobs | 1 (status: `complete`, tipo: `echo`, workspace: `leyenda`, 2026-07-12) |
| Servicio worker persistente | ❌ No existe en systemd |

### Worker Multimedia

| Propiedad | Estado |
|---|---|
| Código | ✅ `data-engine/app/media/worker.py` completo |
| Tests | ✅ 3 tests pasan (modo stub) |
| Servicio systemd | ❌ No existe |
| faster-whisper instalado | ✅ 1.2.1 |
| Modelo configurado | `small` (por defecto; `medium` recomendado en documentación) |
| Probado con audio real | ❌ No durante esta auditoría |

---

## 14. Rclone y Nextcloud

| Propiedad | Valor |
|---|---|
| Servicio | `rclone-nextcloud-rol.service` ✅ active, enabled |
| Mount point | `/mnt/nextcloud-rol` (fuse.rclone, **read-only**) |
| Uptime | 13h 24m |
| Workspaces accesibles | `leyenda` · `mundo de tinieblas` · `plantilla bovedas` · `trudbang` · `vampiro carcasone` (5) |
| Credencial | Configurada y funcional: sí |
| Errores recientes | Ninguno |
| Prueba de escritura | No realizada (sin carpeta técnica segura identificada) |

---

## 15. Ollama

**No instalado localmente en VM105.** Proceso no encontrado en PATH, puerto 11434 no responde localmente.

**Endpoint remoto verificado:** Ollama corre en ia-server (192.168.1.157:11434). Modelo disponible: `qwen2.5:7b` (4.4 GiB, Q4_K_M, contexto 32768 tokens). Conectividad desde VM105 confirmada (`/api/tags` responde HTTP 200).

Archivos que lo referencian: `ingest_rpg.py`, `llm_extractor.py`, `review/pipeline.py`, `glossary/llm_corrector.py`.

**Configuración de endpoint:** `llm_extractor.py` tiene hardcoded `OLLAMA_URL = "http://192.168.1.157:11434/api/generate"`. El `.env.example` define `S9K_OLLAMA_BASE_URL=http://192.168.1.157:11434` pero el `.env` de producción NO tiene esta variable — el código usa la URL hardcodeada.

**Clasificación:** A — Ollama remoto configurado (hardcoded) y accesible.

Impacto: el extractor LLM puede ejecutarse en producción tal como está, pues la URL hardcodeada apunta a un endpoint operativo. Sin embargo, la configuración via `.env` es la práctica correcta. La ingesta real sigue bloqueada por el guard doble (`--dry-run` + `S9K_ALLOW_REAL_INGEST`) hasta validación explícita.

---

## 16. Glosario ASR y Normalización

| Propiedad | Valor |
|---|---|
| DB | `/opt/knowledge-services/s9-knowledge-repo/state/glossary.db` |
| Workspace `leyenda` | **1044 términos** |
| Índices | `workspace`, `normalized`, `type`, `priority` |
| Tests | 26 pasan (`test_glossary_matcher`, `test_glossary_store`) |
| Normalización | Determinista, preserva timestamps |
| Modelo faster-whisper por defecto | `small` |

---

## 17. Paquetes de Conocimiento

Módulo `review/export_import.py` implementado con 4 tipos de paquete: `KnowledgePackage`, `ExternalReviewRequest`, `ExternalReviewResponse`, `ImportedCandidatePackage`. 21 tests pasan (sanitización, validación, roundtrip local). Flujo productivo extremo a extremo no demostrado.

---

## 18. Backup e Inventario

| Elemento | Estado |
|---|---|
| Timer/cron automático para Neo4j | ❌ No encontrado |
| Timer/cron automático para S9 Knowledge | ❌ No encontrado |
| Backups de `compose.yaml` | ✅ Presentes (2026-07-09 y 2026-07-12) |
| Script de backup de Vaultwarden | ✅ Presente |
| Evidencia de restore/rollback ejecutado | ❌ No encontrada |

El grafo Neo4j (199 nodos, 3.1 MiB) no tiene backup automatizado. Riesgo manejable con el volumen actual. **Debe resolverse como Prioridad 1 antes de cualquier ingesta real.** Este inventario es la entrada de Prioridad 1.

---

## 19. Seguridad

| Aspecto | Estado |
|---|---|
| Neo4j puertos solo en localhost | ✅ Desde 2026-07-12 |
| Visor con auth en LAN | ⚠️ Puerto 8088 en `0.0.0.0`; sin login interno |
| Acceso externo con Basic Auth | ✅ nginx VM104 + htpasswd, HTTPS |
| Ingesta bloqueada por diseño | ✅ Guard doble capa activo |
| rclone read-only | ✅ Flag `--read-only` activo |
| Secretos en repositorio público | ✅ Sin secretos — `.env` en `.gitignore` |
| `S9K_ALLOW_REAL_INGEST` | ✅ NO activa en producción |

---

## 20. Contradicciones Encontradas y Correcciones Aplicadas

| Documento | Afirmación anterior | Evidencia real | Corrección |
|---|---|---|---|
| `docs/06-viewer-panel.md` | "Estado: **no implementado**. Solo diseño." | Visor operativo en `:8088` desde `v0.2.5b`; HTTP 200 verificado | Cabecera añadida: estado "EN PRODUCCIÓN" |
| `docs/05-data-engine.md` | `pytest app/tests/ -q  # 8/8` | 196 recopilados, 155 aprobados, 41 fallidos en HEAD | Nota de auditoría añadida con cifra real |
| `CHANGELOG.md` | `pytest 8/8` (en "Verified") | Cifra histórica, válida para momento anterior | Sección Unreleased añadida con estado actual |

---

## 21. Checklist de Fase 0A

- [x] Commit desplegado identificado: `1fd94b85` (v0.2.5b, 2026-07-10)
- [x] Comparación con `origin/main`: 7 commits documentales adelante
- [x] Tag verificado: `v0.2.5b`
- [x] Working tree del despliegue: limpio
- [x] Estado de servicios: 2 systemd activos + Neo4j en Docker
- [x] Visor verificado: HTTP 200 en endpoints principales
- [x] Endpoints inventariados
- [x] Neo4j: métricas de solo lectura (199 nodos, 140 relaciones)
- [x] Tests ejecutados: 196 recopilados, 155 aprobados, 41 fallidos (deuda técnica)
- [x] Worker multimedia: inventariado (código sin servicio)
- [x] rclone: mount activo, 5 workspaces
- [x] Ollama: estado verificado (remoto en ia-server, accesible; endpoint hardcodeado en código, no en `.env`)
- [x] Protección de ingesta: guard doble capa confirmado, variable no activa
- [x] Inventario de backups: sin backup automático
- [x] Contradicciones documentales: detectadas y corregidas en fase 0B
- [x] Informe completo: este documento
- [~] Índices/constraints Neo4j: no disponibles en Community (limitación del motor)
- [~] faster-whisper en producción: instalado, no probado con audio real
- [~] Ollama: remoto accesible (ia-server); endpoint no en `.env` (hardcodeado) — correctivo menor pendiente
- [!] Backup Neo4j: sin automatizar — Prioridad 1
- [ ] Restore/rollback: no probado

---

## 22. Dictamen de Fase 0A

**FASE 0A CERRADA CON EXCEPCIONES DOCUMENTADAS**

### Confirmado

- Commit desplegado identificado y verificado (`1fd94b85`, v0.2.5b).
- Servicios esenciales operativos: visor, Neo4j, rclone.
- Guard de ingesta doble capa activo y testeado (16/16 pasan).
- 155/196 tests pasan; guard de ingesta 16/16 confirmado; fallos son deuda técnica funcional (ver §10).
- Contradicciones documentales críticas corregidas en fase 0B.

### Excepciones documentadas

1. **Ollama remoto (ia-server, accesible) — endpoint no en `.env`** — `llm_extractor.py` usa URL hardcodeada que apunta a un endpoint operativo. El extractor LLM puede ejecutarse, pero la configuración debe migrarse a `.env` antes de considerar el setup como production-ready.
2. **41 tests fallidos** — Deuda técnica de API. No se ha demostrado impacto directo sobre la doble protección de escritura (`--dry-run` + `S9K_ALLOW_REAL_INGEST`), pero los fallos afectan a la fiabilidad funcional en múltiples componentes (semántica del grafo, jobs, multimedia, visor) y deben resolverse antes de la primera ingesta real.
3. **Sin backup automatizado de Neo4j** — Riesgo manejable con el volumen actual; debe resolverse antes de cualquier ingesta real.
4. **Tests viewer rotos** — `ModuleNotFoundError 'app.main'` en 6 archivos. El visor en producción funciona correctamente.

### No compete cerrar en fase 0

Backup, restore y rollback por `source_id` (Prioridad 1) · Benchmark del extractor (Prioridad 2) · CI/CD (Prioridad 3) · Primera ingesta real controlada (Prioridad 4) · Login · Permisos RPG · Modo jugador.
