# 26 · Operaciones: Backup y Restore de Neo4j

**Estado: MÉTODO VERIFICADO EN LAB (2026-07-13)**
**Aplicable a: VM105, contenedor `neo4j-knowledge`**
**Versión Neo4j: 5.26.0 Community Edition**

---

## Inventario de persistencia

### Contenedor de producción

| Campo | Valor |
|---|---|
| Nombre contenedor | `neo4j-knowledge` |
| Imagen | `neo4j:5.26.0-community` |
| Estado | healthy (uptime continuo) |
| Puerto Bolt | `127.0.0.1:7687` (solo localhost) |
| Puerto HTTP | `127.0.0.1:7474` (solo localhost) |

### Volúmenes (bind mounts en host)

| Ruta en host | Destino en contenedor | Contenido |
|---|---|---|
| `/opt/knowledge-services/neo4j/data` | `/data` | Base de datos Neo4j principal |
| `/opt/knowledge-services/neo4j/logs` | `/logs` | Logs del servidor |
| `/opt/knowledge-services/neo4j/import` | `/import` | Ficheros para importación |
| `/opt/knowledge-services/neo4j/plugins` | `/plugins` | Plugins Neo4j |
| `/opt/knowledge-services/neo4j/conf` | `/conf` | Configuración override |

### Tamaño y espacio

| Métrica | Valor |
|---|---|
| Tamaño `/data/` | ~3.1 MB en disco |
| Volumen procesado (dump) | 257.9 MiB (incluye índices internos) |
| Tamaño dump comprimido | ~13.8 KB |
| Espacio disponible en VM105 | 24 GB libres de 38 GB totales |
| Nodos en producción | 199 |
| Relaciones en producción | 140 |

### Ficheros de estado complementarios (SQLite)

Ruta: `/opt/knowledge-services/s9-knowledge-repo/state/`

| Fichero | Tamaño | Descripción |
|---|---|---|
| `glossary.db` | 328 KB | Glosario de términos del pipeline |
| `jobs.db` | 12 KB | Registro de jobs de ingesta |
| `reviews.db` | 12 KB | Cola de revisión de entidades |

Nota: `jobs.db-shm` y `jobs.db-wal` son ficheros auxiliares de SQLite (shared memory / write-ahead log). Se regeneran automáticamente tras restart. Hacer backup durante parada del proceso de ingesta garantiza su consistencia.

---

## Método de backup

### Restricción fundamental de Community Edition

Neo4j **Community Edition no soporta backup en caliente (online backup)**. El comando `neo4j-admin database dump` requiere que Neo4j no esté corriendo contra el volumen `/data`. Intentar dump con el servidor activo produce `AccessDeniedException`.

**Consecuencia operacional:** Cada backup implica una parada del servicio de ~2-5 minutos.

### Comando

```
neo4j-admin database dump <database> --to-path=<directorio>
```

- Genera `<database>.dump` en el directorio destino
- Formato: zip propietario de Neo4j con estructura interna
- 257.9 MiB procesados → ~13.8 KB dump (alta compresión)
- Tiempo en dataset actual: <2 segundos
- El directorio destino debe ser escribible por UID 7474 (usuario `neo4j` del contenedor)

**Sintaxis verificada en Neo4j 5.26.0:**
```bash
neo4j-admin database dump neo4j --to-path=/backup/
# El nombre de la base de datos va como argumento posicional al final
```

---

## Procedimiento de backup (paso a paso)

### Prerrequisitos

- Acceso root a VM105
- Ventana de mantenimiento acordada (servicio inaccesible ~5 minutos)
- Espacio libre en destino: mínimo 10x tamaño del dump (margen seguro con datos actuales)
- La variable `NEO4J_PASSWORD` debe estar disponible o leerla del compose

### Pasos manuales

```bash
# 1. Verificar estado del contenedor
docker inspect neo4j-knowledge --format '{{.State.Health.Status}}'
# Esperado: healthy

# 2. Registrar conteo de nodos pre-backup
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN count(n) as total;"

# 3. Crear directorio de backup con timestamp
BACKUP_DIR="/opt/knowledge-services/backups/neo4j-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
chmod 777 "$BACKUP_DIR"
# Nota: el UID 7474 (neo4j dentro del contenedor) necesita escribir en este directorio

# 4. Parar Neo4j (IMPACTO: servicio inaccesible)
docker stop neo4j-knowledge
echo "Neo4j stopped at $(date)"

# 5. Ejecutar dump usando imagen temporal (sin contenedor activo)
docker run --rm \
  -v /opt/knowledge-services/neo4j/data:/data \
  -v "$BACKUP_DIR":/backup \
  neo4j:5.26.0-community \
  neo4j-admin database dump neo4j --to-path=/backup/
echo "dump exit: $?"

# 6. Calcular y guardar checksum
sha256sum "$BACKUP_DIR/neo4j.dump" > "$BACKUP_DIR/neo4j.dump.sha256"
echo "Checksum saved:"
cat "$BACKUP_DIR/neo4j.dump.sha256"

# 7. Arrancar Neo4j
docker start neo4j-knowledge
echo "Neo4j started at $(date)"

# 8. Esperar que esté healthy (máx. 2.5 minutos)
for i in $(seq 1 30); do
  STATUS=$(docker inspect neo4j-knowledge --format '{{.State.Health.Status}}' 2>/dev/null)
  echo "[$i/30] Status: $STATUS"
  [ "$STATUS" = "healthy" ] && break
  sleep 5
done

# 9. Verificar conteo de nodos post-backup
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN count(n) as total;"
```

### Script automatizado

Ver: `scripts/backup/neo4j-backup.sh` (acepta `--dry-run`, lee contraseña de entorno)

---

## Procedimiento de restore

### Cuándo restaurar

- Ingesta fallida que corrompió el grafo (antes, ejecutar dry-run de rollback)
- Rollback total de una sesión de ingesta
- Fallo del volumen o corrupción de datos
- Migración a nuevo entorno o VM

### Pasos manuales

```bash
# 1. Verificar checksum del dump antes de restaurar
sha256sum -c /ruta/backup/neo4j.dump.sha256
# Esperado: /ruta/backup/neo4j.dump: OK

# 2. Parar Neo4j
docker stop neo4j-knowledge

# 3. (Opcional pero recomendado) Backup del estado actual antes de restore
# Ejecutar procedimiento de backup del estado actual primero

# 4. Restore con --overwrite-destination=true
BACKUP_DIR="/ruta/al/directorio/backup"
docker run --rm \
  -v /opt/knowledge-services/neo4j/data:/data \
  -v "$BACKUP_DIR":/backup:ro \
  neo4j:5.26.0-community \
  neo4j-admin database load --from-path=/backup/ --overwrite-destination=true neo4j
echo "load exit: $?"

# 5. Arrancar Neo4j
docker start neo4j-knowledge

# 6. Validar conteo de nodos (esperar ~30s antes de consultar)
sleep 30
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n)[0] as tipo, count(*) as cnt ORDER BY tipo;"
```

**Sintaxis verificada en Neo4j 5.26.0:**
```bash
neo4j-admin database load --from-path=/backup/ --overwrite-destination=true neo4j
# El nombre de la base de datos va como argumento posicional al final
```

### Script automatizado

Ver: `scripts/backup/neo4j-restore.sh` (acepta `--backup-file` y `--dry-run`)

---

## Validación post-backup / post-restore

```cypher
-- Conteo total de nodos
MATCH (n) RETURN count(n) AS total_nodos;

-- Por tipo
MATCH (n) RETURN labels(n)[0] AS tipo, count(*) AS cnt ORDER BY tipo;

-- Relaciones por tipo
MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS cnt ORDER BY tipo;

-- Muestra de entidades clave
MATCH (n:Person) RETURN n.name, n.source_id LIMIT 10;

-- Nodos sin source_id (históricos)
MATCH (n) WHERE n.source_id IS NULL OR n.source_id = ""
RETURN labels(n)[0] AS tipo, count(*) AS cnt;
```

### Cifras de referencia (producción 2026-07-13)

| Métrica | Valor esperado |
|---|---|
| Total nodos | 199 |
| Total relaciones | 140 |
| Nodos con source_id | ~112 (estimado) |
| Nodos históricos sin source_id | ~87 (estimado) |

---

## Checksum y verificación de integridad

El fichero `.sha256` permite verificar la integridad del dump antes de restaurar:

```bash
sha256sum -c /opt/knowledge-services/backups/neo4j-YYYYMMDD-HHMMSS/neo4j.dump.sha256
# Salida esperada: neo4j.dump: OK
```

---

## Retención recomendada

| Tipo | Frecuencia | Retención | Automatización |
|---|---|---|---|
| Pre-ingesta | Manual (antes de cada ingesta) | Hasta validar ingesta | Script manual |
| Semanal | Domingo 03:00 | 4 semanas | Timer systemd (pendiente) |
| Mensual | Día 1 de cada mes | 6 meses | Timer systemd (pendiente) |

**Espacio estimado:** ~15 KB por dump × 10 backups ≈ <200 KB (completamente despreciable)

---

## Automatización propuesta (PENDIENTE)

La automatización mediante timer systemd está diseñada pero pendiente de ventana de mantenimiento acordada:

```ini
# /etc/systemd/system/neo4j-backup.service
[Service]
Type=oneshot
ExecStart=/opt/knowledge-services/scripts/backup/neo4j-backup.sh
# Variables en /etc/environment o fichero .env referenciado

# /etc/systemd/system/neo4j-backup.timer
[Timer]
OnCalendar=Sun 03:00:00
Persistent=true
```

**Estado: DISEÑADO — Implementación pendiente de ventana de mantenimiento aprobada.**

---

## Resultados de la validación en laboratorio (2026-07-13)

| Paso | Resultado |
|---|---|
| Entorno | VM105, contenedor `neo4j-lab`, puertos `7475/7688`, volúmenes aislados |
| Datos de prueba | 3 nodos: 2×Person + 1×Location con 2 source_ids distintos |
| Backup | `neo4j-admin database dump` exitoso, dump 13.8 KB, 257.9 MiB procesados |
| Permiso especial | El directorio `/backup` requiere chmod 777 (UID 7474 de neo4j) |
| Checksum | `sha256sum` calculado y verificado |
| Restore | `neo4j-admin database load` exitoso en volumen nuevo independiente |
| Validación | Nodos antes=3, nodos después=3 |
| Producción | `neo4j-knowledge` NO interrumpido durante todo el lab |
| Limpieza | Todos los volúmenes y contenedores de lab eliminados |

---

## Historial de ejecuciones reales

| Fecha | Tipo | Archivo | SHA256 (parcial) | Resultado |
|-------|------|---------|-----------------|-----------|
| 2026-07-13 21:49 UTC | Backup producción | neo4j-20260713-174909/neo4j.dump (132 KB) | c3179c01... | COMPLETADO ✅ |
