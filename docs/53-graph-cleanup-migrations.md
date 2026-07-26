# 53 · Limpieza del grafo — migraciones controladas y reversibles (Prioridad 5)

**Estado:** herramienta **implementada y probada** (`review/graph_cleanup.py`,
`tests/test_graph_cleanup.py`). El **APPLY sobre producción (VM105) NO se ha
ejecutado**: requiere backup fresco + autorización explícita del operador (ver §5).

Cierra el hueco de [docs/28](28-graph-migrations-and-rollback.md), que dejaba las
migraciones "diseñadas, implementación pendiente". Complementa a
`review/audit_graph.py` (que **audita** pero no corrige): este módulo **planifica y,
con doble llave, aplica** correcciones de calidad, siempre reversibles y en lotes.

---

## 1. Principio: auto-arreglar solo lo seguro

Según el dosier §17 y docs/28, la limpieza se clasifica en tres clases y **solo la
primera es auto-aplicable**:

| Clase | Qué es | Auto-aplicable | Reversible |
|---|---|---|---|
| `AUTO_SAFE` | Backfill de procedencia en nodos históricos sin `source_id`/`source_kind` (solo **metadatos**) | **Sí** | **Sí** (marcador `_mig`) |
| `REVIEW_REMAP` | Relaciones fuera del vocabulario **con** mapeo canónico conocido (cambia semántica) | No | Vía backup |
| `REVIEW_REQUIRED` | Relaciones inválidas **sin** mapeo (candidatas a borrado) y **fusión de duplicados** (destructivo) | No | Vía backup |

La herramienta **nunca** borra relaciones ni fusiona nodos por su cuenta: eso es
siempre revisión humana.

---

## 2. Qué corrige `AUTO_SAFE` (el único auto)

Nodos con `canonical_name` pero sin `source_id` (los ~87 nodos históricos que detecta
`audit-graph`). La migración les asigna:

```cypher
MATCH (n) WHERE n.canonical_name IS NOT NULL
  AND (n.source_id IS NULL OR n.source_id = '')
SET n.source_id = 'historical_legacy', n.source_kind = 'legacy', n._mig = $mig
RETURN count(n) AS updated
```

Es **no destructivo** (solo añade metadatos) y **100 % reversible**: cada nodo tocado
queda marcado con `_mig = <migration_id>`, así que el rollback deshace **exactamente**
lo que esa migración escribió y nada más:

```cypher
MATCH (n) WHERE n._mig = $mig
REMOVE n.source_id, n.source_kind, n._mig
RETURN count(n) AS reverted
```

---

## 3. Garantías de seguridad (fail-closed)

- **DRY-RUN por defecto:** `plan_cleanup` es solo lectura; `apply_plan(..., apply=False)`
  no escribe una sola propiedad.
- **Doble llave para escribir** (espejo de la ingesta real): `apply=True` **y**
  `S9K_ALLOW_GRAPH_MIGRATION=true` en el entorno. Falta cualquiera → `GraphCleanupError`.
- **Backup obligatorio:** `apply` exige un `backup_ref` no vacío (referencia a un
  backup verificado). Sin backup, no se aplica.
- **Solo `AUTO_SAFE`:** las clases de revisión se rechazan en `apply` aunque se pidan.
- **Manifiesto + rollback exacto:** cada aplicación devuelve un manifiesto con lo
  escrito y su rollback por `_mig`.

Verificado con tests que matan al mutante (12 tests): clasificación auto/revisión,
bloqueo sin env, bloqueo sin backup, dry-run que no escribe, y reversibilidad.

---

## 4. Uso (planificación, solo lectura)

```python
from neo4j import GraphDatabase
from review import graph_cleanup as gc

driver = GraphDatabase.driver(uri, auth=(user, password))  # 127.0.0.1 en VM105
with driver.session() as s:
    plan = gc.plan_cleanup(s)          # SOLO LECTURA
    print(plan.to_report_md())         # informe legible: qué es auto y qué es revisión
```

Esto **no toca el grafo**; produce el plan y el informe para revisar.

---

## 5. APPLY en producción — protocolo del operador (GATEADO)

**El agente no ejecuta esto por su cuenta.** Orden obligatorio:

1. **Backup fresco y verificado** de Neo4j (ver docs/26/32). Anota su referencia.
2. **Revisar el plan** (`plan.to_report_md()`): confirmar el número de nodos
   `AUTO_SAFE` y que no hay sorpresas.
3. **Autorización explícita** del operador para aplicar.
4. Aplicar **solo `AUTO_SAFE`**, en la VM105, con la doble llave:

```python
import os
os.environ["S9K_ALLOW_GRAPH_MIGRATION"] = "true"   # llave 1 (entorno)
res = gc.apply_plan(s, plan, apply=True,            # llave 2 (flag)
                    backup_ref="neo4j-<fecha>-<sha>")
assert res.applied
# Guardar res.manifest -> permite rollback exacto:
# gc.rollback_migration(s, res.manifest, apply=True)
```

5. **Re-auditar** con `audit-graph` y comprobar totales (nodos/relaciones sin cambio;
   `missing_source_id` → 0).
6. Si algo no cuadra, **rollback** con el manifiesto (o restore del backup).

Las clases `REVIEW_REMAP` y `REVIEW_REQUIRED` (relaciones inválidas, duplicados) se
tratan **caso a caso** con revisión humana: la herramienta las lista con el Cypher
propuesto, pero no las aplica.

---

## 6. Estado y pendientes

| Componente | Estado |
|---|---|
| Auditoría de calidad (solo lectura) | ✅ `review/audit_graph.py` |
| Planificación + clasificación | ✅ `review/graph_cleanup.py` |
| Auto-fix `AUTO_SAFE` (reversible) | ✅ implementado y probado |
| Rollback exacto por `_mig` | ✅ implementado y probado |
| Doble llave + backup obligatorio | ✅ fail-closed |
| **APPLY sobre VM105** | ⏳ **pendiente de backup + autorización** |
| Remap de relaciones inválidas | ⏳ revisión humana caso a caso |
| Fusión de duplicados | ⏳ revisión humana caso a caso |

> El grafo productivo es el activo principal. Nada de esto se ejecuta sobre VM105 sin
> backup verificado y tu OK. Ver [docs/28](28-graph-migrations-and-rollback.md).
