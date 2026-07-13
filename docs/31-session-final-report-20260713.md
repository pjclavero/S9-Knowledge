# 31 · Informe final de sesión — Cierre Fase 0 y Prioridad 1

> Fecha: 2026-07-13
> Redactor: coordinador de sesión (arquitecto senior)
> Referencia: dosier `docs/project dossier and checklist.md`

Este documento consolida los resultados verificados de la sesión del 2026-07-13, que ejecutó
tres agentes en paralelo para cerrar la Fase 0, analizar los 41 tests fallidos y preparar la
Prioridad 1 (backup, restore y rollback por fuente).

---

## 1. PR #3 — Corrección y cierre de Fase 0

| Campo | Valor |
|---|---|
| Estado | **FUSIONADO** |
| Rama | `docs/phase-0a-0b-baseline-20260713` → `main` |
| Commit de merge | `9dd92b4` |
| Fecha | 2026-07-13 09:34 +0200 |
| URL | https://github.com/pjclavero/S9-Knowledge/pull/3 |
| Archivos incluidos | 8 archivos `.md` — exclusivamente documentación |

### 1.1 Unicode peligroso

Búsqueda exhaustiva en todos los archivos del diff:
- Caracteres bidireccionales (`U+202A`–`U+202E`, `U+2066`–`U+2069`): **ninguno**
- Anchura cero (`U+200B`–`U+200D`): **ninguno**
- BOM inesperado: **ninguno**
- Acentos españoles y flechas visibles: válidos, presentes, no afectados

Resultado: **sin caracteres peligrosos**.

### 1.2 Secretos en diff

Búsqueda de tokens (`ghp_`, `sk-`, `Bearer`), contraseñas en texto plano, URLs con
credenciales, contenido de `.env`, app-passwords: **ninguno encontrado**.

### 1.3 Corrección: clasificación de Ollama

El informe inicial clasificaba Ollama como "no disponible en VM105" (hallazgo ALTO). La
verificación real determinó:

**Clasificación A — Ollama remoto configurado y accesible.**

| Aspecto | Resultado |
|---|---|
| Ollama local en VM105 | No instalado |
| Endpoint remoto | `192.168.1.157:11434` (ia-server) |
| Conectividad desde VM105 | HTTP 200 confirmado |
| Modelo activo | `qwen2.5:7b` (4.4 GiB, Q4_K_M) |
| Extractor LLM | Funcional |
| Endpoint en `.env` | No — hardcodeado en `llm_extractor.py` |

Impacto: el hallazgo ALTO queda eliminado. Excepción menor pendiente: migrar URL del
endpoint a `.env` para configuración production-ready.

### 1.4 Corrección: valoración de tests

Texto anterior (incorrecto): `"ninguno afecta a seguridad"`.

Texto corregido:

> No se ha demostrado impacto directo sobre la doble protección de escritura,
> pero los fallos sí afectan a la fiabilidad funcional en múltiples componentes
> y deben resolverse antes de la primera ingesta real.

Los guards de ingesta fueron confirmados operativos (16/16 ✅): `--dry-run` y
`S9K_ALLOW_REAL_INGEST`. La clasificación detallada de los 41 fallos se encuentra en
`docs/25-test-failure-analysis.md`.

### 1.5 Dictamen Fase 0

```
Fase 0: CERRADA CON EXCEPCIONES DOCUMENTADAS
```

Excepciones (no bloquean el cierre documental):
1. Endpoint Ollama hardcodeado — funcional, correctivo menor pendiente.
2. 41 tests fallidos — deuda técnica funcional, ver sección 3.
3. Sin backup automatizado — en tramitación (Prioridad 1, sección 4).

---

## 2. VM105 — Sincronización documental

| Campo | Valor |
|---|---|
| Commit en producción antes del merge PR #3 | `1fd94b85` (tag v0.2.5b) |
| Commit en producción tras el merge | `9dd92b4` (PR #3 incluido) |
| `origin/main` (GitHub) | `54e7813` (4 commits por delante) |
| Working tree | Limpio |
| Servicios reiniciados | **No** |

### 2.1 Estado del fast-forward a `origin/main`

**BLOQUEADO** — Los 4 commits entre `9dd92b4` y `54e7813` incluyen archivos `.sh`:

```
scripts/backup/neo4j-backup.sh
scripts/backup/neo4j-restore.sh
scripts/backup/neo4j-rollback-dryrun.sh
```

Regla aplicada: no actualizar el árbol de producción si aparecen scripts. Los scripts no se
activan automáticamente (sin timers, sin systemd, sin Docker Compose), pero la decisión de
incluirlos en el árbol de producción requiere autorización explícita.

**Acción pendiente:** el propietario puede ejecutar `git merge --ff-only origin/main` desde
`/opt/knowledge-services/s9-knowledge-repo` una vez revisado que los scripts son seguros.

---

## 3. Análisis de tests — 41 fallos

### 3.1 Entorno de reproducción

| Campo | Valor |
|---|---|
| Clone | `/tmp/s9k-work-agentB` (aislado, no árbol de producción) |
| Commit | `9dd92b4` |
| Venv | `/opt/knowledge-services/property-graph/.venv` |
| `S9K_ALLOW_REAL_INGEST` | Vacío (no activado) |
| Neo4j producción | No escrito |

### 3.2 Resultados por suite

| Suite | Recopilados | Aprobados | Fallidos | Errores colección |
|---|---:|---:|---:|---:|
| `data-engine/app/tests/` (sin jobs worker) | 163 | 141 | 22 | 0 |
| `test_jobs_worker.py` | 7 | 7 | 0 | 0 |
| `viewer/tests/` | 26 | 26 | 0 | 0 |
| **Corrida combinada** | 196 | 0 | — | **6** |

La corrida combinada falla por path poisoning (CR-1). En suites aisladas: 155 aprobados,
22 fallidos reales. El viewer y jobs-worker pasan al 100 % en aislamiento.

### 3.3 Causas raíz

| ID | Causa raíz | Tests afectados | Componente | Severidad |
|---|---|---:|---|---|
| CR-1 | `sys.path.insert(0, "/opt/.../property-graph/app")` hardcodeado en `test_ingest_semantics.py` y `test_schemas.py` — envenena el path en corrida combinada | 6 errores de colección | Tests | ALTA |
| CR-2 | `create_job()` firma divergente: producción sin `job_type`, `worker.py` ni columnas `priority`, `payload_json`, `result_json`, `attempts`, `max_attempts`, `locked_by`, `locked_at` | 21 fallos | Jobs | ALTA |
| CR-3 | `VALID_SOURCE_KINDS` en producción no incluye `'video'` ni `'generic'` | 1 fallo | Multimedia | ALTA |
| CR-4 | `_check_relation_semantics()` en producción no normaliza `HAS_FOUGHT→FOUGHT_AT` cuando el destino es `Location`/`Region` | 2 fallos | Semántica | MEDIA |

### 3.4 Análisis de puntos críticos

**`create_job` (CR-2):** La firma en producción exige `source_kind` como posicional obligatorio.
La rama de desarrollo lo hizo opcional y añadió el argumento `job_type`. La tabla `jobs` de
producción carece de las columnas extra del esquema de desarrollo. `worker.py` no existe en
producción. Los 21 fallos son efecto en cascada de esta divergencia.

**`source_kind='video'` (CR-3):** El validador de producción lanza `ValueError` para `'video'`
y `'generic'`. La rama de desarrollo amplió `VALID_SOURCE_KINDS` pero el cambio no llegó a
producción.

**`FOUGHT_AT` vs `HAS_FOUGHT` (CR-4):** La función `_check_relation_semantics()` del repo
normaliza `HAS_FOUGHT` a `FOUGHT_AT` cuando el nodo destino es `Location` o `Region`. En
producción este bloque condicional no existe: los tests esperan `"FOUGHT_AT"` y reciben
`"HAS_FOUGHT"`.

**Imports del visor (CR-1):** Cuando `test_ingest_semantics.py` se carga antes de
`test_jobs_worker.py` en la corrida combinada, la inserción de la ruta hardcodeada en
`sys.path[0]` hace que `from jobs import worker` y `from app.main import app` resuelvan al
paquete equivocado. El visor funciona en producción porque systemd configura `PYTHONPATH`
de forma diferente a pytest.

### 3.5 Orden de corrección propuesto

1. **CR-1** — Eliminar `sys.path.insert` hardcodeado (2 archivos). Mínimo cambio, máximo impacto:
   desbloquea la corrida combinada.
2. **CR-3** — Añadir `'video'` y `'generic'` a `VALID_SOURCE_KINDS`. Un cambio de una línea.
3. **CR-4** — Añadir bloque condicional en `_check_relation_semantics()`.
4. **CR-2** — Alinear esquema de `jobs`, firma de `create_job()` y añadir `worker.py`.
   Requiere análisis de migración (tabla `jobs` en producción).

### 3.6 Git

| Campo | Valor |
|---|---|
| Documento | `docs/25-test-failure-analysis.md` |
| Rama | `audit/test-failures-20260713` |
| Commit | `93d03de` |
| PR | **#4** — https://github.com/pjclavero/S9-Knowledge/pull/4 |

```
Análisis de tests: COMPLETO
```

---

## 4. Backup, restore y rollback — Prioridad 1

### 4.1 Inventario Neo4j

| Propiedad | Valor |
|---|---|
| Versión | **5.26.0 Community Edition** |
| Imagen Docker | `neo4j:5.26.0-community` |
| Contenedor | `neo4j-knowledge` |
| Datos | 3.1 MB en `/opt/knowledge-services/neo4j/data` |
| Disco libre VM105 | 24 GB / 38 GB (63 %) |
| Heap | 512 MB inicial, 2 GB máximo |
| Pagecache | 512 MB |
| Plugins | Ninguno |
| Puertos expuestos | 7474, 7687 — solo `127.0.0.1` desde 2026-07-12 |

**Otros datos persistentes:**
- `jobs.db`, `glossary.db`, `reviews.db` — requieren backup independiente del dump de Neo4j.
- Mount rclone (`/mnt/nextcloud-rol`): read-only, datos en Nextcloud, no requiere backup local.

### 4.2 Método de backup seleccionado

**`neo4j-admin database dump` + SHA256 checksum**

| Método | Consistencia | Parada requerida | Community | Enterprise |
|---|---|---|---|---|
| `database dump` | ACID ✅ | Sí (~2-3 min) | ✅ | ✅ |
| `backup` online | ACID ✅ | No | ❌ | ✅ |
| Snapshot volumen | Eventual | Recomendada | ✅ | ✅ |
| Export Cypher | Lógica | No | ✅ | ✅ |

El backup online no está disponible en Community Edition. El dump es el único método
con consistencia ACID garantizada. El snapshot de volumen sin parada puede capturar
un estado inconsistente durante una escritura.

**Ventana de mantenimiento:** ~2-3 minutos (stop + dump + checksum + start).

### 4.3 Laboratorio aislado

Ejecutado en VM105 con imagen idéntica a producción, puertos y volúmenes distintos.

| Paso | Resultado | Tiempo |
|---|---|---|
| Arrancar Neo4j lab (7575/7476) | ✅ | 30 s |
| Crear datos (5 nodos, 2 relaciones) | ✅ | 5 s |
| Parar lab | ✅ | 5 s |
| `neo4j-admin database dump neo4j` | ✅ — 15 KB | ~1 s |
| SHA256 checksum | ✅ — `5fab2a79…` | <1 s |
| `neo4j-admin database load` en instancia nueva (7577/7478) | ✅ | 5 s |
| Validar nodos/relaciones/propiedades | ✅ — íntegros | 5 s |
| Limpiar lab | ✅ — eliminado | 5 s |

**Conclusión:** backup y restore son reproducibles. El procedimiento es escalable a la base
de producción (3.1 MB → estimación <30 s de dump).

### 4.4 Diseño de rollback por `source_id`

**Modelo de procedencia:**

| Propiedad | Nodos | Relaciones |
|---|---|---|
| `source_id` | Identificador único de la fuente | ✅ |
| `source_kind` | Tipo (`rpg-session`, `pdf`, `video`, etc.) | ✅ |
| `source_ids[]` | Array para nodos compartidos por varias fuentes | ✅ |
| `workspace` | Aislamiento por espacio de trabajo | ✅ |
| `confidence` | Nivel de confianza de extracción | ✅ |

**Estrategia:**
- **Nodos exclusivos** (`source_id = X` y sin `source_ids` adicionales): eliminables.
- **Nodos compartidos** (`X ∈ source_ids[]` con más fuentes): retirar `X` de `source_ids`,
  no eliminar el nodo.
- **Relaciones exclusivas**: eliminar.
- **Relaciones compartidas**: retirar evidencia de la fuente.

**Fases del rollback:**
1. Análisis previo con Cypher (conteo de exclusivos vs compartidos).
2. Dry-run: lista de cambios sin ejecutar.
3. Aprobación explícita del operador.
4. Ejecución con Python driver (transacciones ACID).
5. Auditoría posterior con queries de integridad.
6. Revert: restore del backup pre-rollback si el resultado es incorrecto.

**Limitación:** Cypher puro no garantiza atomicidad en operaciones multi-nodo complejas.
Usar Python driver (`neo4j`) para transacciones.

### 4.5 Scripts creados

| Script | Ubicación | Modo dry-run | Sin secrets |
|---|---|---|---|
| `neo4j-backup.sh` | `scripts/backup/` | ✅ | ✅ |
| `neo4j-restore.sh` | `scripts/backup/` | ✅ | ✅ |
| `neo4j-rollback-dryrun.sh` | `scripts/backup/` | ✅ | ✅ |

Los tres scripts: validan espacio disponible, reciben contenedor y destino como argumentos,
generan log, devuelven código de salida correcto, no sobrescriben backups anteriores
(timestamp en nombre), no contienen secrets hardcodeados.

### 4.6 Documentación generada

| Documento | Líneas | Contenido |
|---|---|---|
| `docs/26-operations-backup-and-restore.md` | ~289 | Inventario, método, procedimientos, retención |
| `docs/27-controlled-ingest-runbook.md` | ~224 | Prerrequisitos, fases, rollback emergencia |
| `docs/28-graph-migrations-and-rollback.md` | ~257 | Modelo de procedencia, Cypher queries, fases |
| `docs/29-priority-1-readiness-report.md` | ~147 | Resumen ejecutivo, checklist, dictamen |

### 4.7 Git

| Campo | Valor |
|---|---|
| Rama | `feat/neo4j-backup-restore-foundation` |
| Commit | `f513b9d` |
| PR | **#5** — fusionado a `main` |

```
Prioridad 1: PARCIAL
```

Completado: inventario real, método seleccionado, laboratorio ejecutado y verificado, diseño
de rollback, documentación (4 docs), scripts (3 scripts con dry-run).

Pendiente (requiere ventana de mantenimiento):
- Primer backup real de producción (stop neo4j-knowledge + dump + checksum).
- Restore de datos reales en instancia de validación.
- Documentar resultados en `docs/30` o nuevo documento.

---

## 5. Git — Resumen de ramas y PRs

| Rama | Base | Commits | PR | Estado |
|---|---|---|---|---|
| `docs/phase-0a-0b-baseline-20260713` | `main` | 3 documentales | **#3** | Fusionado ✅ |
| `audit/test-failures-20260713` | `main` | 2 (análisis + anexo) | **#4** | Abierto — pendiente revisión |
| `feat/neo4j-backup-restore-foundation` | `main` | 1 (docs + scripts) | **#5** | Fusionado ✅ |
| `docs/coordinator-final-report-20260713` | `main` | 1 documental | **#6** | Fusionado ✅ |
| `docs/session-final-report-20260713` | `main` | 1 (este doc) | pendiente | — |

---

## 6. Dictamen final

```
Fase 0:             CERRADA CON EXCEPCIONES DOCUMENTADAS
Análisis de tests:  COMPLETO
Prioridad 1:        PARCIAL
```

---

## 7. Siguiente paso

**No iniciar ingesta real.** No implementar login ni modo jugador.

Orden de trabajo recomendado:

1. **Revisar y fusionar PR #4** — análisis de tests completo, sin cambios funcionales.
2. **Autorizar fast-forward VM105** — el propietario revisa `scripts/backup/` y ejecuta
   `git merge --ff-only origin/main` en `/opt/knowledge-services/s9-knowledge-repo`.
3. **Corregir CR-1** — eliminar `sys.path.insert` hardcodeado en `test_ingest_semantics.py`
   y `test_schemas.py`. Mínimo cambio, máximo impacto.
4. **Corregir CR-3 y CR-4** — en ramas separadas (`fix/source-kind-video`,
   `fix/fought-at-normalization`).
5. **Planificar ventana de mantenimiento** (~2-3 min) para primer backup real con
   `scripts/backup/neo4j-backup.sh`. Prioridad 1 pasa a COMPLETADA tras ese backup
   verificado.
6. **Corregir CR-2** (`create_job`, schema de jobs) una vez analizado el impacto de
   migración sobre la tabla `jobs` de producción.
