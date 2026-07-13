# Runbook: Primera Ingesta Controlada

**Status:** En diseño — Prerrequisitos documentados, ejecución pendiente  
**Last Updated:** 2026-07-13  
**Author:** AgentC  
**Related:** docs/26 (backup), docs/28 (rollback), docs/29 (readiness)

## Objetivo

Ejecutar la **primera ingesta de documentos RPG** en Neo4j S9 Knowledge de forma controlada, validada y con rollback garantizado.

## Prerrequisitos

### 1. Backup Validado (CRÍTICO)

- [ ] Backup de Neo4j generado y checksum verificado (ver docs/26, paso 4)
- [ ] Backup comprobado mediante restore en instancia aislada (docs/26, Opción A)
- [ ] Archivo de backup almacenado: `/opt/knowledge-services/backups/neo4j/neo4j_PRE_INGEST_*.dump`
- [ ] Referencia anotada en runbook anterior de ejecución

```bash
# Verificar backup pre-ingesta
ls -lh /opt/knowledge-services/backups/neo4j/neo4j_PRE_INGEST_*.dump
sha256sum -c /opt/knowledge-services/backups/neo4j/neo4j_PRE_INGEST_*.dump.sha256
```

### 2. Tests Aprobados

- [ ] Suite de tests ejecutada en rama `feat/neo4j-backup-restore-foundation`
- [ ] Tests de ingest: `data-engine/app/tests/test_ingest_rpg.py`
- [ ] Tests de rollback: `data-engine/app/tests/test_rollback.py` (si existen)
- [ ] Cobertura >=80% de código crítico de ingesta
- [ ] Ningún test fallando

```bash
cd /opt/knowledge-services/s9-knowledge-repo/data-engine
python -m pytest tests/test_ingest_rpg.py -v --cov=app/ingest_rpg
```

### 3. Equipos Aprobados

- [ ] Product Owner: Aprobación de datos y alcance de ingesta
- [ ] Data Engineer: Validación de transformaciones Cypher
- [ ] DevOps: Disponibilidad de ventana de mantenimiento y runbook ejecutable
- [ ] Arquitecto de Datos: Revisión del modelo de rollback por source_id

### 4. Documentos de Datos

- [ ] Primer documento RPG listo para ingesta (ej: "Campaign Arc 1 - Session 1")
- [ ] Formato: JSON conforme a schema de `docs/23-knowledge-packages.md`
- [ ] Validación previa con `--dry-run` (ver Paso 1 abajo)
- [ ] Conteo esperado de nodos y relaciones anotado
- [ ] source_id y source_kind asignados: `{source_id: "doc-campaign-s1", source_kind: "rpg-session"}`

### 5. Protecciones de Ingesta Activas

#### Protección 1: Modo Dry-Run

El ingester debe ejecutarse primero sin escribir:

```bash
# Pseudo-código (ver app/ingest_rpg.py para detalles)
ingest_rpg.py \
  --dry-run \
  --document "$DOC_PATH" \
  --source-id "doc-campaign-s1" \
  --source-kind "rpg-session" \
  --workspace "default" \
  --output-report "/tmp/ingest_report_dry.json"
```

**Validar salida:**
- Número de entidades a crear: ✅ esperadas
- Número de relaciones a crear: ✅ esperadas
- Warnings o errores: ✅ none or expected
- source_id propagado: ✅ present in all nodes/rels

#### Protección 2: Variable de Entorno S9K_ALLOW_REAL_INGEST

El código de ingesta **rechaza escribir sin este flag**:

```python
# En ingest_rpg.py (verificar presencia)
if not os.getenv("S9K_ALLOW_REAL_INGEST") == "true":
    raise RuntimeError("S9K_ALLOW_REAL_INGEST=true required for real ingest. Use --dry-run to validate.")
```

Solo se establece durante ejecución controlada:

```bash
export S9K_ALLOW_REAL_INGEST=true
# Ejecución real
ingest_rpg.py --document ...
unset S9K_ALLOW_REAL_INGEST
```

## Fases de Ingesta

### Fase 1: Validación Offline (Sin Acceso a Neo4j)

**Duración:** ~15 minutos  
**Requiere:** /opt/knowledge-services/s9-knowledge-repo acceso local

```bash
cd /opt/knowledge-services/s9-knowledge-repo

# 1.1 Validar JSON del documento contra schema
python data-engine/app/schemas/rpg_schema.py --validate \
  --file "$DOC_PATH" \
  --output "/tmp/schema_validation.json"

# Verificar:
# - "valid": true
# - Ningún error en "errors"

# 1.2 Contar entidades y relaciones esperadas
python -c "
import json
with open('$DOC_PATH') as f:
    doc = json.load(f)
    entities = doc.get('entities', [])
    relationships = doc.get('relationships', [])
    print(f'Expected entities: {len(entities)}')
    print(f'Expected relationships: {len(relationships)}')
" | tee /tmp/expected_counts.txt

# 1.3 Listar source_id y source_kind que se usarán
echo "Source ID: doc-campaign-s1"
echo "Source Kind: rpg-session"
echo "Workspace: default"
```

### Fase 2: Ingesta en Seco (Dry-Run con Neo4j)

**Duración:** ~5 minutos  
**Requiere:** Neo4j-knowledge ejecutándose

```bash
cd /opt/knowledge-services/s9-knowledge-repo/data-engine

# 2.1 Ejecutar en dry-run (se conecta a Neo4j pero no escribe)
python app/ingest_rpg.py \
  --dry-run \
  --document "$DOC_PATH" \
  --source-id "doc-campaign-s1" \
  --source-kind "rpg-session" \
  --workspace "default" \
  --output-report "/tmp/ingest_dry_report.json" 2>&1 | tee /tmp/ingest_dry.log

# 2.2 Validar reporte
cat /tmp/ingest_dry_report.json | python -m json.tool | head -50

# Verificar:
# - "status": "success"
# - "dry_run": true
# - "entities_created": X (match fase 1)
# - "relationships_created": Y (match fase 1)
# - "errors": [] (empty)

# 2.3 Tomar screenshot del grafo actual pre-ingesta
curl -s -u neo4j:$(cat /opt/knowledge-services/neo4j/secrets/neo4j_password) \
  'http://127.0.0.1:7474/db/neo4j/sync' \
  -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH (n) RETURN count(n) as total;"}]}' \
  | python -m json.tool > /tmp/graph_pre_ingest.json

# Anotar: número de nodos antes de ingesta
```

### Fase 3: Ingesta Real (Con Escritura)

**Duración:** ~5-10 minutos  
**Requiere:** Confirmación explícita del usuario  
**Ventana de mantenimiento:** Recomendada para aislar de otras operaciones

#### Pre-Ingesta Real

```bash
# Verificación final (checklist humano)
# [ ] Fase 1 validación: OK
# [ ] Fase 2 dry-run: OK
# [ ] Backup pre-ingesta verificado
# [ ] User aprobó: "Execute ingest for doc-campaign-s1"
# [ ] Neo4j accesible: OK
# [ ] S9K_ALLOW_REAL_INGEST será establecido brevemente

echo "=== PRE-INGESTA CHECKLIST ==="
echo "Documento: $DOC_PATH"
echo "Source ID: doc-campaign-s1"
echo "Expected entities: $(grep 'Expected entities' /tmp/expected_counts.txt)"
echo "Expected relationships: $(grep 'Expected relationships' /tmp/expected_counts.txt)"
echo "Backup file: $(ls -1 /opt/knowledge-services/backups/neo4j/neo4j_PRE_INGEST_*.dump | head -1)"
echo "Backup checksum: $(sha256sum /opt/knowledge-services/backups/neo4j/neo4j_PRE_INGEST_*.dump.sha256 | head -1)"
```

#### Ejecución Real

```bash
cd /opt/knowledge-services/s9-knowledge-repo/data-engine

# Establecer protección: SOLO para esta ingesta
export S9K_ALLOW_REAL_INGEST=true

# Ejecutar sin --dry-run
python app/ingest_rpg.py \
  --document "$DOC_PATH" \
  --source-id "doc-campaign-s1" \
  --source-kind "rpg-session" \
  --workspace "default" \
  --output-report "/tmp/ingest_real_report.json" 2>&1 | tee /tmp/ingest_real.log

# Capturar resultado
INGEST_STATUS=$?

# Desproteger inmediatamente
unset S9K_ALLOW_REAL_INGEST

# Log resultado
echo "Ingest status code: $INGEST_STATUS"
echo "Timestamp: $(date)" >> /tmp/ingest_real.log
```

#### Post-Ingesta Inmediata

```bash
# 3.1 Validar que la ingesta escribió datos
cat /tmp/ingest_real_report.json | python -m json.tool

# Verificar:
# - "status": "success"
# - "dry_run": false
# - "entities_created": X (match expected)
# - "relationships_created": Y (match expected)

# 3.2 Validar en Neo4j
curl -s -u neo4j:$(cat /opt/knowledge-services/neo4j/secrets/neo4j_password) \
  'http://127.0.0.1:7474/db/neo4j/sync' \
  -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH (e:Entity) WHERE e.source_id = '"'"'doc-campaign-s1'"'"' RETURN count(e) as count;"}]}' \
  | python -m json.tool

# Output debe mostrar: { "count": X } (match esperado)

# 3.3 Verificar diversidad de labels
curl -s -u neo4j:$(cat /opt/knowledge-services/neo4j/secrets/neo4j_password) \
  'http://127.0.0.1:7474/db/neo4j/sync' \
  -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY label;"}]}' \
  | python -m json.tool

# 3.4 Verificar relaciones
curl -s -u neo4j:$(cat /opt/knowledge-services/neo4j/secrets/neo4j_password) \
  'http://127.0.0.1:7474/db/neo4j/sync' \
  -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH ()-[r]->() WHERE any(x IN [r.source_id, r.source_ids] WHERE x IS NOT NULL) RETURN type(r) as rel_type, count(r) as count ORDER BY rel_type;"}]}' \
  | python -m json.tool
```

### Fase 4: Validación Integrada (15-30 min)

```bash
# 4.1 Tests de smoke (si existen)
cd /opt/knowledge-services/s9-knowledge-repo
python -m pytest tests/test_smoke_ingest.py -v -s

# 4.2 Audit queries (ver docs/28 para modelo de rollback)
# Contar nodos únicos vs compartidos
curl -s -u neo4j:... 'http://127.0.0.1:7474/db/neo4j/sync' -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"
MATCH (e:Entity) WHERE e.source_id = '"'"'doc-campaign-s1'"'"'
RETURN count(e) as unique_to_ingested,
       count(DISTINCT e.source_id) as sources_count;
  "}]}'

# 4.3 Verificar viewer funciona
curl -s http://127.0.0.1:8000/api/entities | head -20
# (Si viewer está operativo)
```

### Fase 5: Post-Ingesta — Documentación de Rollback

```bash
# Registrar información crítica para rollback futuro si es necesario
cat > /opt/knowledge-services/backups/neo4j/ingest_doc-campaign-s1.metadata << 'META'
Source ID: doc-campaign-s1
Source Kind: rpg-session
Ingest Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Entities Created: X
Relationships Created: Y
Pre-Ingest Backup: /opt/knowledge-services/backups/neo4j/neo4j_PRE_INGEST_*.dump
Dry-Run Report: /tmp/ingest_dry_report.json
Real Report: /tmp/ingest_real_report.json
Rollback Cypher Query (if needed): MATCH (n) WHERE n.source_id = 'doc-campaign-s1' DETACH DELETE n;
META
```

## Rollback de Emergencia

Si durante o después de la ingesta se detecta:
- Corrupción de datos
- Entidades duplicadas incorrectamente
- Relaciones rotas

### Opción 1: Rollback por source_id (Recomendado)

Ver docs/28 para procedimiento completo. Resumido:

```bash
# Con Neo4j ejecutándose
cat > /tmp/rollback_doc-campaign-s1.cypher << 'CYPHER'
MATCH (n)
WHERE n.source_id = 'doc-campaign-s1'
      OR 'doc-campaign-s1' IN (n.source_ids ?: [])
WITH n
OPTIONAL MATCH (n)-[r]->()
DELETE r, n
RETURN count(n) as deleted_nodes;
CYPHER

# Ejecutar en dry-run primero
curl -s -u neo4j:... 'http://127.0.0.1:7474/db/neo4j/sync' ...

# Si OK, ejecutar real con aprobación explícita
```

### Opción 2: Disaster Recovery (si rollback falla)

Ver docs/26, Opción B. Resumido:

```bash
# 1. Detener Neo4j
docker stop neo4j-knowledge

# 2. Restore pre-ingesta backup
# ... (ver docs/26 pasos 2-5)

# 3. Arrancar Neo4j
docker compose up -d

# Tiempo: ~5-10 minutos
```

## Métricas de Éxito

| Métrica | Target | Resultado |
|---|---|---|
| Validación schema | 100% | ⏳ TBD |
| Dry-run accuracy | Match entities/rels | ⏳ TBD |
| Real ingest status | success | ⏳ TBD |
| Entities recuperables | 100% | ⏳ TBD |
| source_id presente | 100% de nodos | ⏳ TBD |
| Viewer acceso | OK | ⏳ TBD |
| Rollback viabilidad | Cypher dry-run OK | ⏳ TBD |

## Checklist de Ejecución

```markdown
### Pre-Ingesta
- [ ] Backup validado
- [ ] Tests passing
- [ ] Equipo aprobó
- [ ] Documento validado
- [ ] Ventana de mantenimiento confirmada

### Fase 1-2
- [ ] Schema validation OK
- [ ] Dry-run executed
- [ ] Dry-run report reviewed
- [ ] Graph snapshot taken
- [ ] Counts match expected

### Fase 3
- [ ] S9K_ALLOW_REAL_INGEST set
- [ ] Ingest script ran successfully
- [ ] Variable cleared immediately after
- [ ] Real report OK

### Fase 4-5
- [ ] Smoke tests passed
- [ ] Audit queries verified
- [ ] Viewer operational
- [ ] Rollback metadata saved
- [ ] Documentation updated

### Sign-off
- [ ] Product Owner sign-off
- [ ] Data Engineer sign-off
- [ ] Timestamp: ___________
```

## Próximos Pasos

1. ⏳ **Pendiente:** Ejecutar Fase 1 (validación offline)
2. ⏳ **Pendiente:** Ejecutar Fase 2 (dry-run)
3. ⏳ **Pendiente:** Obtener aprobación de usuario
4. ⏳ **Pendiente:** Ejecutar Fase 3 (ingesta real)
5. ⏳ **Pendiente:** Ejecutar Fase 4 (validación)
6. ⏳ **Pendiente:** Documentar en docs/30 (después de ejecución)

## Referencias

- docs/26: Backup and Restore Operations
- docs/28: Graph Migrations and Rollback
- docs/23: Knowledge Packages
- app/ingest_rpg.py: Ingester implementation
- app/schemas/rpg_schema.py: Schema validation
