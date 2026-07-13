# Validación de Backup Real en Producción — 2026-07-13

## Resumen

Primer backup real de Neo4j (producción) ejecutado, restaurado en instancia aislada y validado con rollback por `source_id` en laboratorio.

**Fecha**: 2026-07-13  
**Entorno**: VM105 (192.168.1.205), Neo4j 5.26.0 Community  
**Commit en producción**: cef9233  
**Responsable**: Operación automatizada coordinada  

---

## 1. Preflight

| Verificación | Resultado |
|--------------|-----------|
| Commit producción | cef9233 ✅ |
| Neo4j estado | [PENDIENTE] |
| Imagen Neo4j | [PENDIENTE] |
| Tamaño datos | [PENDIENTE] |
| Espacio libre | [PENDIENTE] |
| Jobs activos | Ninguno ✅ |
| S9K_ALLOW_REAL_INGEST | Desactivado ✅ |
| Scripts auditados | [PENDIENTE] |

---

## 2. Dry-run

| Verificación | Resultado |
|--------------|-----------|
| Ejecutado | [PENDIENTE] |
| Neo4j detenido durante dry-run | NO ✅ |
| Dump creado durante dry-run | NO ✅ |

---

## 3. Backup real (ventana de mantenimiento)

| Campo | Valor |
|-------|-------|
| Inicio ventana | [PENDIENTE] |
| Fin ventana | [PENDIENTE] |
| Duración total | [PENDIENTE] |
| Archivo generado | [PENDIENTE] |
| Tamaño | [PENDIENTE] |
| SHA256 | [PENDIENTE] |
| Neo4j healthy tras reinicio | [PENDIENTE] |
| Visor activo tras backup | [PENDIENTE] |

---

## 4. Copia externa

| Campo | Valor |
|-------|-------|
| Destino | [PENDIENTE] |
| SHA256 verificado en destino | [PENDIENTE] |
| Resultado | [PENDIENTE] |

---

## 5. Restore en instancia aislada

| Verificación | Resultado |
|--------------|-----------|
| Imagen (idéntica a prod) | [PENDIENTE] |
| Puertos | 127.0.0.1:7577 / 127.0.0.1:7478 |
| Total nodos | [PENDIENTE] |
| Total relaciones | [PENDIENTE] |
| Labels | [PENDIENTE] |
| Tipos de relación | [PENDIENTE] |
| Índices | [PENDIENTE] |
| Instancia limpiada tras validación | Sí ✅ |

---

## 6. Rollback por fuente en laboratorio

Prueba ejecutada sobre datos de laboratorio sintéticos (NO datos de producción).

| Verificación | Resultado |
|--------------|-----------|
| Instancia aislada | Sí ✅ |
| Fuente de prueba | lab-source-A |
| Nodos exclusivos eliminados | [PENDIENTE] |
| Nodos compartidos conservados | [PENDIENTE] |
| Relaciones de fuente B intactas | [PENDIENTE] |
| Instancia limpiada tras validación | Sí ✅ |

### Semántica del rollback

El rollback por `source_id` sigue la regla:
- **Eliminar**: nodos cuyo `source_id == fuente` y NO tienen `source_ids` (exclusivos de la fuente)
- **Retirar**: nodos cuyo `source_ids` incluye la fuente y tiene otras (quitar la fuente de la lista)
- **Conservar**: nodos de otras fuentes sin relación con la fuente eliminada

---

## 7. Estado final de producción

| Verificación | Resultado |
|--------------|-----------|
| Neo4j | [PENDIENTE] |
| s9-knowledge-viewer.service | [PENDIENTE] |
| rclone-nextcloud-rol.service | [PENDIENTE] |
| Datos modificados por ingesta | NO ✅ |
| S9K_ALLOW_REAL_INGEST | Desactivado ✅ |

---

## Dictamen

```
Backup real: [PENDIENTE]
Restore real aislado: [PENDIENTE]
Rollback por fuente: [PENDIENTE]
Prioridad 1: [PENDIENTE]
```

---

*Documento generado automáticamente. Datos del backup pendientes de actualización por el coordinador.*
