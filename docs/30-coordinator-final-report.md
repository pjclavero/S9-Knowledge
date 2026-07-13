# 30 · Informe coordinador — Cierre Fase 0 y Prioridad 1

> Fecha: 2026-07-13
> Rama auditada: `docs/phase-0a-0b-baseline-20260713` (PR #3, fusionado)
> Commit VM105: `9dd92b4` (sincronizado desde `1fd94b8`)

Este documento consolida los resultados de la auditoría distribuida ejecutada el 2026-07-13,
que cerró las fases 0A y 0B y preparó la Prioridad 1 (backup y recuperación).

---

## 1. PR #3 — Corrección y merge

| Campo | Valor |
|---|---|
| Estado | FUSIONADO |
| Commit de merge | `9dd92b4d` |
| URL | https://github.com/pjclavero/S9-Knowledge/pull/3 |
| Archivos | CHANGELOG, README, docs/02, docs/05, docs/06, docs/24, docs/INDEX, docs/project dossier |
| Unicode | 8 archivos escaneados — ningún carácter peligroso |
| Secretos en diff | Ninguno |

### Corrección: Ollama

El informe inicial de auditoría clasificaba Ollama como "no disponible en VM105" (hallazgo ALTO).
Verificación posterior determinó:

**Clasificación A — Ollama remoto configurado y accesible.**

Ollama no está instalado en VM105. Corre en ia-server (192.168.1.157:11434). El endpoint
está hardcodeado en `data-engine/app/extractors/llm_extractor.py`. El modelo `qwen2.5:7b`
está disponible y responde desde VM105. El extractor LLM puede funcionar tal como está.

La ingesta real sigue bloqueada únicamente por el doble guard de escritura
(`--dry-run` + `S9K_ALLOW_REAL_INGEST`), no por ausencia de Ollama.

Docs actualizados: `docs/24`, `docs/02`, `README.md`, `docs/project dossier and checklist.md`.

### Corrección: valoración de tests

La frase "ninguno afecta a seguridad" fue reemplazada en 6 ubicaciones por:

> No se ha demostrado impacto directo sobre la doble protección de escritura
> (--dry-run + S9K_ALLOW_REAL_INGEST), pero los fallos afectan a la fiabilidad
> funcional en múltiples componentes (semántica del grafo, jobs, multimedia, visor)
> y deben resolverse antes de la primera ingesta real.

---

## 2. VM105 — Sincronización documental

| Campo | Valor |
|---|---|
| Commit anterior | `1fd94b8` (v0.2.5b, feat data-engine, 2026-07-10) |
| Commit nuevo | `9dd92b4` (docs phase 0A/0B, 2026-07-13) |
| Commits incorporados | 11 (todos documentales) |
| Archivos actualizados | 9 — todos `.md` |
| Cambios no documentales | Ninguno |
| Merge | Fast-forward (`git merge --ff-only origin/main`) |
| Working tree | Limpio |
| Servicios reiniciados | Ninguno |

---

## 3. Análisis de los 41 tests fallidos

> Documento completo: [docs/25-test-failure-analysis.md](25-test-failure-analysis.md)
> Rama: `audit/test-failures-20260713` | PR #4

| Campo | Valor |
|---|---|
| Commit auditado | `1fd94b8` (v0.2.5b) |
| Recopilados | 196 |
| Aprobados | 155 |
| Fallidos | 41 |
| Errores de colección | 6 |
| Causas raíz identificadas | **2** |

### CR-1 (ALTA) — Path contaminado en tests

`test_ingest_semantics.py` contiene en su cabecera:

```python
sys.path.insert(0, "/opt/knowledge-services/property-graph/app")
```

Esta línea hardcodeada hace que pytest importe módulos del directorio antiguo
`property-graph/app/` en lugar de `data-engine/app/`. Como consecuencia, 39 tests
y 6 errores de colección son **falsos negativos**: el código de producción en
`data-engine/` es correcto, pero los tests validan contra versiones antiguas de los
módulos.

Fallos que son consecuencia directa de CR-1:
- `create_job`: firma nueva con `source_kind` opcional (data-engine); tests validan firma antigua (property-graph).
- `FOUGHT_AT`: normalización `HAS_FOUGHT → FOUGHT_AT` presente en data-engine, ausente en la copia antigua.
- `source_kind='video'`: valor válido en data-engine; rechazado por lista antigua.
- Imports del visor: la contaminación de `sys.path` afecta la colección antes de que se ejecute cualquier test de viewer.

**Corrección mínima:** Eliminar la línea `sys.path.insert(0, ...)` de `test_ingest_semantics.py`.

### CR-2 (MEDIA) — Cache no limpiada entre tests

`get_settings()` usa `@lru_cache` en `viewer/`. El cache no se resetea entre tests
en `viewer/tests/test_api_jobs.py`, causando 4 fallos por estado compartido entre casos.

**Corrección mínima:** Añadir fixture `autouse` en `viewer/tests/conftest.py` que llame
a `get_settings.cache_clear()` antes de cada test.

### Impacto

Los 41 fallos son deuda técnica de tests, no de código. La doble protección de escritura
está intacta. No obstante, deben corregirse antes de la primera ingesta real para garantizar
que el pipeline de revisión queda cubierto por tests fiables.

### Ramas de corrección propuestas

- `fix/test-path-contamination` — eliminar `sys.path.insert` hardcodeado (resuelve 39+6)
- `fix/viewer-test-cache` — fixture `autouse` para `lru_cache` (resuelve 4)

---

## 4. Backup y restore — Prioridad 1

> Documentos completos: docs/26, docs/27, docs/28, docs/29
> Scripts: `scripts/backup/`
> Rama: `feat/neo4j-backup-restore-foundation` | PR #5

### Inventario de persistencia

| Recurso | Detalle |
|---|---|
| Neo4j | 5.26.0 Community Edition, contenedor `neo4j-knowledge` |
| Almacenamiento | Bind mounts en `/opt/knowledge-services/neo4j/` (data, logs, import, plugins, conf) |
| Tamaño `/data` | 3.1 MB en disco (257.9 MiB procesados por dump, alta compresión) |
| Espacio disponible | 24 GB libres de 38 GB |
| `jobs.db` | 12 KB + journal |
| Reviews / approved_payload | En `state/` del repo |
| Glosarios | SQLite en `state/glossary.db` (1044 términos) |

### Método de backup

**`neo4j-admin database dump`** — método oficial de Neo4j.

Community Edition no soporta backup online. El dump requiere detener el contenedor
(~2-5 min de inactividad). No hay alternativa sin parada en Community.

Nota técnica descubierta en el laboratorio: el directorio destino del dump dentro del
contenedor debe tener permisos `777` (UID 7474 del proceso neo4j).

### Laboratorio aislado (ejecutado 2026-07-13)

Entorno: contenedor `neo4j-lab`, puertos 127.0.0.1:7475/7688, volúmenes propios.
No compartió red ni volúmenes con el contenedor de producción `neo4j-knowledge`.

| Paso | Resultado |
|---|---|
| Datos de prueba creados | 3 nodos (2 source_ids distintos) |
| Backup generado | 13.8 KB dump |
| Checksum | `0a899ded4fd86f231cb5f4ffed4ff6564437e638...` |
| Restore en volumen nuevo | OK |
| Nodos antes del restore | 3 |
| Nodos después del restore | 3 |
| Lab limpiado | Sí (contenedores y volúmenes eliminados) |

### Scripts creados

| Script | Función |
|---|---|
| `scripts/backup/neo4j-backup.sh` | Backup con `--dry-run`, validación de espacio, log, checksum |
| `scripts/backup/neo4j-restore.sh` | Restore con verificación de checksum, validación post-restore |
| `scripts/backup/neo4j-rollback-dryrun.sh` | Análisis previo al rollback (solo lectura, nunca escribe) |

Los tres scripts leen credenciales de `.env` (sin secretos hardcodeados) y devuelven
códigos de salida 0/1 correctos.

---

## 5. Rollback por source_id

> Documento completo: [docs/28-graph-migrations-and-rollback.md](28-graph-migrations-and-rollback.md)

El modelo de procedencia del grafo usa `source_id`, `source_kind` y `workspace` en cada
nodo. El rollback debe distinguir:

- **Nodos exclusivos de una fuente**: se eliminan.
- **Nodos compartidos por varias fuentes**: solo se desvincula la contribución de la fuente.
- **Relaciones exclusivas**: se eliminan.
- **Relaciones respaldadas por otras fuentes**: se conservan.

El script `neo4j-rollback-dryrun.sh` realiza el análisis en modo lectura y genera un
informe de impacto antes de cualquier modificación.

**Limitación:** ~87 nodos históricos no tienen `source_id` (creados antes de la
implementación de trazabilidad). El rollback no puede actuar sobre ellos.

**Estado de implementación:** DISEÑO COMPLETO — código pendiente de fase posterior.

---

## 6. Resumen de PRs y ramas

| Rama | Commits | PR | Estado |
|---|---|---|---|
| `docs/phase-0a-0b-baseline-20260713` | 3 | PR #3 | MERGED (`9dd92b4`) |
| `audit/test-failures-20260713` | 1 | PR #4 | Abierto |
| `feat/neo4j-backup-restore-foundation` | 1 | PR #5 | Abierto |
| `docs/coordinator-final-report-20260713` | 1 | PR #6 | Este documento |
| VM105 `main` | fast-forward | — | `9dd92b4` (limpio) |

---

## 7. Dictamen

```
Fase 0:            CERRADA CON EXCEPCIONES DOCUMENTADAS
Análisis de tests: COMPLETO
Prioridad 1:       PREPARADA
```

### Excepciones documentadas (Fase 0)

| Excepción | Severidad | Estado |
|---|---|---|
| Ollama remoto — ingesta LLM condicionada a config | PENDIENTE CONFIG | Documentado, accesible |
| 41 tests fallidos — 2 causas raíz de tests, código correcto | MEDIA | Corrección mínima conocida |
| Sin backup automatizado de producción | ALTO | Método verificado en lab, ventana pendiente |
| 87 nodos históricos sin source_id | BAJO | Detectado, sin impacto inmediato |

---

## 8. Siguiente paso recomendado

### Opción A — Corregir tests (bajo riesgo, alto valor)

```
fix/test-path-contamination  — eliminar sys.path.insert (resuelve 39+6 fallos)
fix/viewer-test-cache        — fixture autouse lru_cache (resuelve 4 fallos)
```

Resultado esperado: 196/196 tests pasando. Prerequisito recomendado antes de ingesta real.

### Opción B — Ventana de mantenimiento para backup real (prioridad de seguridad)

Acordar ~5 min de parada de Neo4j para ejecutar el primer backup de producción y activar
el timer systemd de backup semanal. Sin este paso, la Prioridad 1 queda PREPARADA pero no COMPLETA.

**No iniciar la primera ingesta real hasta tener al menos un backup de producción verificado.**
