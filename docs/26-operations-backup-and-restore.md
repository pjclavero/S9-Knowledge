# Neo4j Backup and Restore Operations

**Status:** Foundation documented, tested in lab environment  
**Last Updated:** 2026-07-13  
**Author:** AgentC  
**Related:** docs/27 (ingesta controlada), docs/28 (rollback), docs/29 (readiness)

## Inventario de Producción

### Versión y Edición

- **Versión:** Neo4j 5.26.0 Community Edition
- **Imagen Docker:** `neo4j:5.26.0-community`
- **Contenedor:** neo4j-knowledge (VM105, common-services)
- **IP:** 192.168.1.205
- **Puerto Bolt (interno):** 127.0.0.1:7687
- **Puerto HTTP (interno):** 127.0.0.1:7474
- **Licencia:** ACCEPT_LICENSE_AGREEMENT=yes

### Volúmenes Persistentes

| Tipo | Source | Destination | Permisos | Propósito |
|---|---|---|---|---|
| bind | /opt/knowledge-services/neo4j/data | /data | 755 | Almacenamiento de grafo y metadatos |
| bind | /opt/knowledge-services/neo4j/logs | /logs | 755 | Logs de Neo4j |
| bind | /opt/knowledge-services/neo4j/import | /import | 755 | Directorio de importación |
| bind | /opt/knowledge-services/neo4j/plugins | /plugins | 755 | Plugins (vacío actualmente) |
| bind | /opt/knowledge-services/neo4j/conf | /conf | 755 | Configuración de Neo4j |

### Recursos Asignados

- **Heap inicial:** 512m
- **Heap máximo:** 2g
- **Pagecache:** 512m
- **Tamaño de datos (/data):** 3.1M (estado 2026-07-13)
- **Espacio disponible en disco:** 24G / 38G (63% libre)

### Datos Persistentes Adicionales

Otros almacenamientos asociados en VM105:

- `/opt/knowledge-services/s9-knowledge-repo/state/jobs.db` — estado de trabajos
- `/opt/knowledge-services/s9-knowledge-repo/state/glossary.db` — glosario
- `/opt/knowledge-services/s9-knowledge-repo/state/reviews.db` — revisiones aprobadas
- `/opt/knowledge-services/property-graph/state/jobs.db` — estado property graph

**Backup de estos archivos es independiente de Neo4j y debe coordinarse con rclone mount de Nextcloud.**

## Selección de Método de Backup

### Contexto: Community Edition Limitations

Neo4j 5.26.0 Community Edition **no soporta backup online** mediante `neo4j-admin backup`. Solo Enterprise Edition permite backups en vivo sin parada del contenedor.

### Método Seleccionado: `neo4j-admin database dump`

**Decisión:** Parada controlada + dump + checksum

**Justificación:**

1. **Consistencia garantizada:** dump genera snapshot consistente (requiere parada)
2. **Integridad:** checksum SHA256 valida que el archivo no se corrompió
3. **Recuperación simple:** `neo4j-admin database load` restaura en instancia nueva o existente
4. **Sin dependencias de licencia:** disponible en Community Edition
5. **Independencia de tamaño:** dump comprimido (15KB de test lab con 5 nodos)

### Alternativas Rechazadas

- **`neo4j-admin backup`:** No disponible en Community Edition
- **Backup de volumen Docker:** Incompleto; no garantiza estado consistente de WAL (write-ahead logs)
- **Copia directa de /data:** Propensa a corrupción si hay escrituras en paralelo

## Procedimiento de Backup

### Prerrequisitos

- neo4j-knowledge ejecutándose
- Espacio libre: al menos 2x tamaño estimado de /data (actualmente 6M; mantener >50MB libre)
- Script acceso SSH a VM105 con credenciales configuradas
- Docker instalado y acceso root

### Pasos de Backup Controlado

#### 1. Preparación (sin impacto en producción)

```bash
# Conectar a VM105
BACKUP_DEST="/opt/knowledge-services/backups/neo4j"
mkdir -p "$BACKUP_DEST"
BACKUP_FILE="$BACKUP_DEST/neo4j_$(date +%Y%m%d_%H%M%S).dump"

# Validar espacio disponible
df -h /opt | head -5
# Debe haber > 100MB libres

# Validar contenedor
docker ps | grep neo4j-knowledge
# Estado: Up
```

#### 2. Detención del Contenedor (VENTANA DE MANTENIMIENTO)

```bash
# Registrar hora de inicio
echo "Backup started: $(date)" >> "$BACKUP_DEST/backup.log"

# Parar neo4j-knowledge (todas las conexiones se cierran)
docker stop neo4j-knowledge

# Esperar confirmación de parada
sleep 5
docker ps | grep neo4j-knowledge || echo "Stopped"

# Registrar parada
echo "Container stopped: $(date)" >> "$BACKUP_DEST/backup.log"
```

#### 3. Ejecución del Dump (VENTANA DE MANTENIMIENTO)

```bash
# Usar la misma imagen para consistencia
PROD_IMAGE=$(docker inspect neo4j-knowledge --format '{{.Config.Image}}' 2>/dev/null || echo "neo4j:5.26.0-community")

# Ejecutar dump
docker run --rm \
  -v /opt/knowledge-services/neo4j/data:/data \
  -v "$BACKUP_DEST":/backup \
  --entrypoint neo4j-admin \
  "$PROD_IMAGE" \
  database dump neo4j --to-path=/backup/ 2>&1 | tee "$BACKUP_DEST/dump.log"

# Resultado esperado
# - Archivo neo4j.dump creado
# - Salida contiene "100.0% ... Done"
```

#### 4. Validación y Checksum

```bash
# Renombrar según timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mv "$BACKUP_DEST/neo4j.dump" "$BACKUP_FILE"

# Generar checksum
sha256sum "$BACKUP_FILE" > "$BACKUP_FILE.sha256"
cat "$BACKUP_FILE.sha256"

# Registrar éxito
echo "Backup completed: $(date)" >> "$BACKUP_DEST/backup.log"
echo "File: $BACKUP_FILE" >> "$BACKUP_DEST/backup.log"
cat "$BACKUP_FILE.sha256" >> "$BACKUP_DEST/backup.log"

# Tamaño del backup
ls -lh "$BACKUP_FILE"
```

#### 5. Reinicio de Producción (VENTANA DE MANTENIMIENTO)

```bash
# Arrancar Neo4j con docker compose
cd /opt/knowledge-services/neo4j
docker compose up -d

# Esperar inicialización (healthcheck demora ~2 min)
echo "Waiting for Neo4j to start (healthcheck enabled)..."
sleep 120

# Validar conexión
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$(cat /opt/knowledge-services/neo4j/secrets/neo4j_password 2>/dev/null || echo 'UNKNOWN')" \
  --format plain "MATCH (n) RETURN count(n) as total;" 2>&1 | head -3 || echo "Connection check failed"

# Registrar tiempo total
echo "Backup procedure completed: $(date)" >> "$BACKUP_DEST/backup.log"
```

### Tiempo Estimado de Ventana de Mantenimiento

- Parada: 5s
- Dump: 5-30s (depende de tamaño; con 3.1M fue 0.4s en test)
- Validación: 5s
- Arranque: 120s (healthcheck)
- **Total:** ~2-3 minutos

## Procedimiento de Restore

### Casos de Uso

1. **Disaster recovery:** Corrupción de grafo o pérdida accidental de datos
2. **Validación de backup:** Verificar que el dump es íntegro y recuperable
3. **Rollback parcial:** Restaurar a versión anterior, luego hacer rollback selectivo por source_id (ver docs/28)

### Opciones de Restauración

#### Opción A: Restaurar en Nueva Instancia (Recomendado para Validación)

```bash
# Preparar directorio nuevo
RESTORE_PATH="/tmp/neo4j-restore-validation"
mkdir -p "$RESTORE_PATH/data" "$RESTORE_PATH/logs"
chmod -R 755 "$RESTORE_PATH"

# Obtener imagen y backup
PROD_IMAGE="neo4j:5.26.0-community"
BACKUP_FILE="$BACKUP_DEST/neo4j_YYYYMMDD_HHMMSS.dump"

# 1. Verificar integridad del dump
sha256sum -c "$BACKUP_FILE.sha256"
# Output: neo4j_YYYYMMDD_HHMMSS.dump: OK

# 2. Cargar dump en nuevo directorio
docker run --rm \
  -v "$RESTORE_PATH/data":/data \
  -v "$(dirname $BACKUP_FILE)":/backup \
  --entrypoint neo4j-admin \
  "$PROD_IMAGE" \
  database load neo4j --from-path=/backup/ --overwrite-destination=true 2>&1 | tee "$RESTORE_PATH/restore.log"

# 3. Arrancar instancia de validación
docker run -d \
  --name neo4j-restore-validation \
  -p 7477:7474 -p 7479:7687 \
  -e NEO4J_AUTH=neo4j/restore_validation_pass \
  -e NEO4J_server_memory_heap_max__size=512m \
  -v "$RESTORE_PATH/data":/data \
  -v "$RESTORE_PATH/logs":/logs \
  "$PROD_IMAGE"

sleep 60

# 4. Validar datos
docker exec neo4j-restore-validation cypher-shell -u neo4j -p restore_validation_pass \
  --format plain "MATCH (n) RETURN labels(n)[0] as label, count(n) as total ORDER BY label;"

# Comparar con query en producción antes del backup:
# - Número de Entity nodes
# - Número de Source nodes
# - Número de relaciones

# 5. Limpiar
docker stop neo4j-restore-validation && docker rm neo4j-restore-validation
rm -rf "$RESTORE_PATH"
```

#### Opción B: Restaurar en Producción (Disaster Recovery)

**ADVERTENCIA:** Esta operación es destructiva y requiere ventana de mantenimiento.

```bash
# Prerequisitos:
# - Neo4j-knowledge detenido
# - Backup válido (checksum verificado)
# - Aprobación explícita del usuario

# 1. Detener Neo4j (ya estará detenido en disaster)
docker stop neo4j-knowledge || true

# 2. Hacer backup de seguridad de /data actual (por si el restore falla)
tar czf /opt/knowledge-services/backups/neo4j_data_pre_restore_$(date +%s).tar.gz \
  /opt/knowledge-services/neo4j/data

# 3. Limpiar /data
rm -rf /opt/knowledge-services/neo4j/data/*

# 4. Cargar dump
docker run --rm \
  -v /opt/knowledge-services/neo4j/data:/data \
  -v /opt/knowledge-services/backups/neo4j:/backup \
  --entrypoint neo4j-admin \
  neo4j:5.26.0-community \
  database load neo4j --from-path=/backup/ --overwrite-destination=true

# 5. Arrancar Neo4j
cd /opt/knowledge-services/neo4j
docker compose up -d

# 6. Validar post-restore
sleep 120
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$(cat /opt/knowledge-services/neo4j/secrets/neo4j_password)" \
  --format plain "MATCH (n) RETURN count(n) as total;"

# 7. Registrar operación
echo "Disaster recovery restore completed: $(date)" >> /opt/knowledge-services/backups/neo4j/restore.log
```

### Validación Post-Restore

En ambos casos, verificar:

```cypher
-- 1. Contar nodos por tipo
MATCH (n)
RETURN labels(n)[0] as label, count(n) as total
ORDER BY label;

-- 2. Contar relaciones
MATCH ()-[r]->()
RETURN type(r) as rel_type, count(r) as total
ORDER BY rel_type;

-- 3. Verificar source_id está presente (crítico para rollback)
MATCH (e:Entity)
WHERE e.source_id IS NOT NULL
RETURN count(e) as entities_with_source_id, count(DISTINCT e.source_id) as unique_sources;

-- 4. Revisar logs de errores en Neo4j
-- Acceder a /logs/debug.log dentro del contenedor
docker exec neo4j-knowledge tail -f /logs/debug.log
```

## Retención de Backups

### Política Recomendada

| Tipo | Retención | Justificación |
|---|---|---|
| Diarios (backup automático) | 7 días | Recuperación de cambios recientes |
| Semanales | 4 semanas | Mayor ventana de detección de corrupción |
| Mensuales | 12 meses | Auditoría a largo plazo; compliance |
| Pre-ingesta (Primera ingesta crítica) | Indefinido | Referencia para comparación |

### Script de Limpieza (Automation Future)

```bash
#!/bin/bash
BACKUP_DIR="/opt/knowledge-services/backups/neo4j"
RETENTION_DAYS=30

find "$BACKUP_DIR" -name "neo4j_*.dump" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "neo4j_*.dump.sha256" -mtime +$RETENTION_DAYS -delete

echo "Cleanup completed $(date)" >> "$BACKUP_DIR/retention.log"
```

## Limitaciones y Consideraciones

### Limitaciones de Community Edition

- Sin backup online (requiere parada siempre)
- Sin replicación nativa
- Sin High Availability
- Sin Advanced Security

### Impacto en Usuarios

- Parada: ~2-3 minutos
- No se pueden ejecutar queries durante el backup
- El viewer (si está conectado) se desconectará

### Recuperación ante Fallo del Dump

Si el dump falla:

1. Verificar logs: `docker logs neo4j-knowledge`
2. Verificar espacio: `df -h /opt`
3. Reintentar desde cero: `docker compose down && docker compose up -d`
4. Si /data está corrupto: usar backup anterior + Opción B de restore

## Matriz de Decisión

| Escenario | Acción | Ventana | Riesgo |
|---|---|---|---|
| Backup preventivo de rutina | Dump controlado | 2-3 min | Bajo — parada controlada |
| Validar dump existente | Restore en nueva instancia | 2-3 min | Muy bajo — no toca producción |
| Corrupción detectada en producción | Disaster recovery (Opción B) | 5-10 min | Medio — reemplaza datos |
| Rollback parcial por source_id | Restore + Cypher rollback | 5-15 min | Medio — requiere query exacta |

## Próximos Pasos

1. ✅ **Completado:** Método de backup documentado y validado en laboratorio aislado
2. ⏳ **Pendiente:** Ejecutar primer backup en producción (requiere ventana de mantenimiento)
3. ⏳ **Pendiente:** Implementar automatización con cron (después de primer backup manual exitoso)
4. ⏳ **Pendiente:** Integrar rclone para replicación a Nextcloud (ver docs/24)

## Apéndice A: Scripts de Ayuda

Ver `scripts/neo4j_backup.sh` y `scripts/neo4j_restore.sh` para implementaciones de estos procedimientos con modo `--dry-run`.

## Apéndice B: Laboratorio de Prueba (Completado 2026-07-13)

- **Objetivo:** Validar dump + restore + checksum
- **Imagen:** neo4j:5.26.0-community (idéntica a producción)
- **Puertos lab:** 7575 (HTTP), 7476 (Bolt)
- **Puertos restore:** 7577 (HTTP), 7478 (Bolt)
- **Datos creados:** 5 nodos (3 Entity, 2 Source), 2 relaciones
- **Dump generado:** 15KB
- **Checksum SHA256:** 5fab2a7918da322edba3f3b597c1398239943c30590226a4652e50d82c04db2a
- **Restore validado:** ✅ OK — datos recuperados íntegros
- **Lab eliminado:** ✅ Limpieza completada
- **Tiempo total:** ~5 minutos (incluye esperas de inicialización)
