# 27 · Runbook de Ingesta Controlada

**Estado: OPERACIONAL**
**Aplicable a: VM105, data-engine S9 Knowledge**
**Guard activo:** `--dry-run` + `S9K_ALLOW_REAL_INGEST=true` (doble bloqueo por diseño)

---

## Propósito

Este runbook describe el procedimiento seguro para ejecutar una ingesta real de datos en el grafo Neo4j de producción. La ingesta real está bloqueada por diseño mediante un doble guard y requiere pasos explícitos para activarla.

---

## Prerrequisitos

### Entorno

- Acceso SSH a VM105 (`root@192.168.1.205`)
- El contenedor `neo4j-knowledge` está en estado `healthy`
- El visor FastAPI en puerto 8088 está accesible (opcional pero recomendado para validación)
- El proceso de ingesta (`data-engine`) no está corriendo actualmente

### Datos

- El fichero fuente (audio, PDF, texto) está disponible en el servidor o en `/mnt/nextcloud-rol`
- El `source_id` para la ingesta está definido y es único (formato recomendado: `<tipo>_<identificador>`, ej. `audio_l5a_s03e01`)
- El `source_kind` es válido: `audio`, `pdf`, `book`, `youtube`, `text`, `generic`
- El extractor LLM ha sido validado con dry-run previo

### Seguridad

- **Backup reciente disponible** (obligatorio antes de cualquier ingesta real)
- No hay otra ingesta en curso
- El `source_id` a usar NO existe ya en el grafo (verificar con Cypher)

---

## Checklist pre-ingesta (obligatoria)

```
[ ] 1. Backup ejecutado y checksum verificado (ver doc 26)
[ ] 2. Backup disponible en /opt/knowledge-services/backups/neo4j-TIMESTAMP/
[ ] 3. neo4j-knowledge está en estado healthy
[ ] 4. source_id no existe en producción (verificar con Cypher)
[ ] 5. Dry-run del extractor ejecutado y resultado revisado
[ ] 6. review_queue validada (entidades aprobadas, ninguna en estado PENDING)
[ ] 7. Espacio en disco suficiente (>5 GB libres en VM105)
[ ] 8. Ventana de ingesta acordada (sin otras operaciones paralelas)
```

### Verificar source_id no existe

```cypher
-- Ejecutar antes de la ingesta
MATCH (n) WHERE n.source_id = 'TU_SOURCE_ID_AQUI'
RETURN labels(n)[0] as tipo, count(*) as cnt;
-- Esperado: sin resultados (0 rows)
```

---

## Activar la ingesta real

### La ingesta está bloqueada por doble guard

El data-engine tiene dos mecanismos de protección:

1. **Flag `--dry-run`**: el pipeline corre en modo simulación sin escribir en Neo4j
2. **Variable `S9K_ALLOW_REAL_INGEST=true`**: debe estar presente en el entorno para que la ingesta real sea posible

Ambos deben estar correctamente configurados para ejecutar una ingesta real.

### Activar (solo cuando todo el checklist está marcado)

```bash
# En VM105, en el directorio del data-engine
cd /opt/knowledge-services/s9-knowledge-repo/data-engine

# Activar la variable de entorno para esta sesión
export S9K_ALLOW_REAL_INGEST=true

# Verificar que está activa
echo "S9K_ALLOW_REAL_INGEST=$S9K_ALLOW_REAL_INGEST"
```

**Nota de seguridad:** No añadir `S9K_ALLOW_REAL_INGEST=true` al fichero `.env` de forma permanente. Debe activarse manualmente para cada sesión de ingesta.

---

## Pasos del pipeline de ingesta

### Paso 1: Transcripción (si fuente es audio/vídeo)

```bash
cd /opt/knowledge-services/s9-knowledge-repo
source property-graph/.venv/bin/activate

# Transcribir (modelo: medium para mayor precisión)
python -m data_engine.transcribe \
  --input /mnt/nextcloud-rol/leyenda/transcripciones/FICHERO.mp3 \
  --output /tmp/transcripcion_TIMESTAMP.txt \
  --model medium \
  --language es
```

### Paso 2: Dry-run del extractor

```bash
# SIEMPRE ejecutar dry-run primero
python -m data_engine.ingest_rpg \
  --source-id audio_l5a_s03e01 \
  --source-kind audio \
  --input /tmp/transcripcion_TIMESTAMP.txt \
  --dry-run \
  2>&1 | tee /tmp/dryrun_TIMESTAMP.log

# Revisar el log antes de continuar
grep -E "WARN|ERROR|entity|relation" /tmp/dryrun_TIMESTAMP.log | head -50
```

### Paso 3: Revisar queue antes de ingesta

```bash
# Ver entidades en revisión
curl -s http://localhost:8088/reviews | python3 -m json.tool | head -50

# O con Cypher directo
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) WHERE n.review_status = 'PENDING' RETURN count(n) as pending;"
```

### Paso 4: Ingesta real (con doble guard activo)

```bash
# Verificar guard está activo
echo "Guard activo: $S9K_ALLOW_REAL_INGEST"

# Ingesta real (sin --dry-run, con S9K_ALLOW_REAL_INGEST=true)
python -m data_engine.ingest_rpg \
  --source-id audio_l5a_s03e01 \
  --source-kind audio \
  --workspace leyenda \
  --input /tmp/transcripcion_TIMESTAMP.txt \
  2>&1 | tee /tmp/ingest_real_TIMESTAMP.log

echo "Ingesta exit: $?"
```

---

## Validación post-ingesta

```bash
# 1. Conteo de nodos antes vs después
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN count(n) as total;"

# 2. Nodos del nuevo source_id
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) WHERE n.source_id = 'audio_l5a_s03e01' RETURN labels(n)[0] as tipo, count(*) as cnt;"

# 3. Relaciones del nuevo source_id
docker exec neo4j-knowledge cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH ()-[r]->() WHERE r.source_id = 'audio_l5a_s03e01' RETURN type(r) as tipo, count(*) as cnt;"

# 4. Verificar via visor web
curl -s http://localhost:8088/graph/summary | python3 -m json.tool
```

### Criterios de éxito

- El número de nodos aumentó respecto al baseline
- Todos los nodos nuevos tienen `source_id` correctamente asignado
- No hay errores en el log de ingesta
- El visor muestra las nuevas entidades correctamente

---

## Rollback de emergencia

Si la ingesta produce resultados incorrectos o corrupción del grafo:

### Opción 1: Rollback selectivo por source_id (recomendado)

```bash
# 1. Primero ejecutar dry-run para ver qué se eliminaría
scripts/backup/neo4j-rollback-dryrun.sh --source-id audio_l5a_s03e01

# 2. Revisar el informe generado en /tmp/
# 3. Si el resultado es aceptable, ejecutar la eliminación
#    (la eliminación requiere script separado de implementación pendiente)
```

Ver doc 28 para el diseño completo del rollback.

### Opción 2: Restore completo desde backup

```bash
# SOLO si el rollback selectivo no es suficiente
scripts/backup/neo4j-restore.sh \
  --backup-file /opt/knowledge-services/backups/neo4j-TIMESTAMP/neo4j.dump

# Ver doc 26 para el procedimiento completo de restore
```

---

## Registro de ingestas

Mantener un registro de cada ingesta real ejecutada:

| Fecha | source_id | source_kind | Nodos añadidos | Relaciones añadidas | Operador | Resultado |
|---|---|---|---|---|---|---|
| (primera ingesta pendiente) | - | - | - | - | - | - |

---

## Notas de seguridad

- `S9K_ALLOW_REAL_INGEST=true` debe desactivarse al terminar la sesión (`unset S9K_ALLOW_REAL_INGEST`)
- Nunca ejecutar ingesta real sin backup previo verificado
- El extractor LLM puede producir entidades erróneas — la dry-run + review_queue son la primera línea de defensa
- Los 87 nodos históricos sin `source_id` no son eliminables por rollback selectivo; solo por restore completo
