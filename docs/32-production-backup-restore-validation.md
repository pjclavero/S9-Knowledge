# Validación de Backup Real en Producción — 2026-07-13

## Resumen ejecutivo

Primer backup real de Neo4j (producción) ejecutado el 2026-07-13 21:49 UTC, restaurado en instancia aislada y validado con rollback por `source_id` en laboratorio.

| Campo | Valor |
|-------|-------|
| **Fecha** | 2026-07-13 |
| **Entorno** | VM105 (192.168.1.205), Neo4j 5.26.0 Community |
| **Commit producción** | cef9233 |
| **Archivo backup** | neo4j-20260713-174909/neo4j.dump |
| **SHA256** | c3179c01b7437722056a7e17ca50b2a55cc16d60a9adc7436a0c7f73e2438e74 |
| **Parada Neo4j** | ~25 segundos |

---

## 1. Preflight (2026-07-13 21:48:12 UTC)

| Verificación | Resultado |
|--------------|-----------|
| Commit producción | cef9233 ✅ |
| Neo4j estado | healthy ✅ |
| Imagen Neo4j | neo4j:5.26.0-community ✅ |
| Tamaño datos Neo4j | 3.1 MB ✅ |
| Espacio libre en / | 24 GB ✅ |
| Jobs activos de ingesta | Ninguno ✅ |
| S9K_ALLOW_REAL_INGEST | No configurada (bloqueada por defecto) ✅ |
| Scripts auditados | set -euo pipefail, validaciones, --dry-run, trap de emergencia, checksum SHA256, logs ✅ |

---

## 2. Dry-run

| Verificación | Resultado |
|--------------|-----------|
| Ejecutado | Sí ✅ |
| Neo4j detenido durante dry-run | NO ✅ |
| Dump creado durante dry-run | NO ✅ |

---

## 3. Backup real (ventana de mantenimiento)

| Campo | Valor |
|-------|-------|
| Inicio ventana | 2026-07-13 21:49 UTC |
| Fin ventana | 2026-07-13 21:50 UTC |
| Duración parada Neo4j | ~25 segundos |
| Directorio | /opt/knowledge-services/backups/neo4j-20260713-174909/ |
| Archivo generado | neo4j.dump |
| Tamaño | 132 KB |
| SHA256 | c3179c01b7437722056a7e17ca50b2a55cc16d60a9adc7436a0c7f73e2438e74 |
| Neo4j healthy tras reinicio | Sí ✅ |
| s9-knowledge-viewer activo | Sí ✅ |
| rclone-nextcloud-rol activo | Sí ✅ |

---

## 4. Copia externa

| Campo | Valor |
|-------|-------|
| Destino previsto | /var/backups/s9-knowledge/neo4j/ (yggdrasil 192.168.1.152) |
| Resultado | **PENDIENTE** |
| Motivo | VM105 no tiene acceso SSH directo a yggdrasil; la clave está en ia-server |
| Acción recomendada | Ejecutar `scp /opt/knowledge-services/backups/neo4j-20260713-174909/* root@192.168.1.152:/var/backups/s9-knowledge/neo4j/` desde ia-server |

---

## 5. Restore en instancia aislada

| Verificación | Resultado |
|--------------|-----------|
| Imagen | neo4j:5.26.0-community (idéntica a producción) ✅ |
| Puertos | 127.0.0.1:7577 (HTTP), 127.0.0.1:7478 (Bolt) ✅ |
| Red | --network none (aislada) ✅ |
| Checksum verificado antes de restore | Sí ✅ |
| Total nodos | 199 ✅ |
| Total relaciones | 140 ✅ |
| Labels | 14 (Entity, Concept, Object, Character, Clan, Faction, School, Location, Task, Event, Creature, Spell, Session, Spirit) ✅ |
| Tipos de relación | 28 ✅ |
| Índices | 2 ✅ |
| Datos coinciden con producción | Sí ✅ |
| Instancia limpiada tras validación | Sí ✅ |

---

## 6. Rollback por fuente en laboratorio

Prueba sobre datos sintéticos en instancia aislada. **No se usaron datos de producción.**

| Verificación | Resultado |
|--------------|-----------|
| Instancia aislada (sin datos reales) | Sí ✅ |
| Red | --network none ✅ |
| Fuente de prueba | lab-source-A |
| Nodos exclusivos A eliminados | 2 (EntityOnlyA, EntityOnlyA2) ✅ |
| Nodos compartidos conservados y actualizados | SharedEntity: source_ids ['lab-source-A','lab-source-B'] → ['lab-source-B'] ✅ |
| Nodos de fuente B intactos | EntityOnlyB preservada ✅ |
| Instancia limpiada tras validación | Sí ✅ |

### Semántica del rollback (patrón validado)

El rollback por `source_id` sigue tres operaciones transaccionales en Cypher:

1. **Eliminar** nodos con `source_id == fuente` y sin `source_ids` (exclusivos de la fuente)
2. **Actualizar** nodos con la fuente en `source_ids` → retirar fuente de la lista (si quedan otros)
3. **Eliminar** relaciones exclusivas de la fuente (misma lógica)

Limitación: no existe aún un script de orquestación con `--dry-run`. Las consultas Cypher directas son correctas y replicables; su automatización queda como tarea de la Prioridad 2.

---

## 7. Estado final de producción

| Verificación | Resultado |
|--------------|-----------|
| Neo4j | healthy ✅ |
| s9-knowledge-viewer.service | active ✅ |
| rclone-nextcloud-rol.service | active ✅ |
| Nodos en producción | 199 (sin cambios) ✅ |
| Relaciones en producción | 140 (sin cambios) ✅ |
| Datos modificados por ingesta | NO ✅ |
| S9K_ALLOW_REAL_INGEST | No configurada (bloqueada por defecto) ✅ |

---

## Dictamen

```
Backup real:              COMPLETADO ✅
Restore real aislado:     COMPLETADO ✅
Rollback por fuente:      VALIDADO EN LAB ✅
Copia externa:            PENDIENTE ⚠️
Prioridad 1:              COMPLETADA ✅
```

**Pendiente post-Prioridad 1:**
- Copiar backup desde ia-server a yggdrasil (una sola operación manual)
- Automatizar copia externa en el script neo4j-backup.sh
- Implementar script de rollback con --dry-run (Prioridad 2)
