# 11 · Revisión de calidad de datos (workspace "leyenda")

## Contexto

El visor de solo lectura (`viewer/`, FastAPI + Jinja2 + vis-network) se probó
contra la instancia real de Neo4j en VM105 (`bolt://192.168.1.205:7687`,
accesible vía túnel SSH desde el PC local del usuario), usando el workspace
`leyenda`. Durante esa prueba se detectaron dos problemas de calidad de datos
en el grafo:

1. **Relación semántica incorrecta**: aristas `HAS_FOUGHT` con destino un nodo
   de tipo `Location`/`Region` (no tiene sentido "luchar contra" un lugar; es
   síntoma de una extracción con el sujeto/objeto de la relación mal
   asignado).
2. **Posible duplicado de entidad**: `Tamori Family` y `Familia Tamori`
   aparecen como dos nodos distintos, ambos relacionados con `Rejn Clan` vía
   `BELONGS_TO` (pertenece a). Todo indica que es el mismo concepto extraído
   dos veces con nombres en idiomas distintos (inglés/español), posiblemente
   con `entity_type` distinto (p. ej. `Faction` vs `Clan`).

Ninguno de los dos problemas se ha corregido en Neo4j en esta fase. Este
documento solo registra las consultas de diagnóstico usadas y remite a las
herramientas/cambios relevantes.

**Estas consultas son de solo lectura. No se ha modificado ni se debe
modificar Neo4j real en esta fase.**

## Consultas Cypher de diagnóstico

### 1. Relaciones `HAS_FOUGHT` con destino `Location`/`Region`

Busca aristas semánticamente incorrectas: un personaje/criatura "luchó contra"
un lugar en vez de contra otra entidad viva.

```cypher
-- 1. Relaciones HAS_FOUGHT con destino Location/Region (semánticamente incorrectas)
MATCH (a:Entity {workspace:'leyenda'})-[r:HAS_FOUGHT]->(b:Entity {workspace:'leyenda'})
WHERE b.entity_type IN ['Location','Region']
RETURN a.canonical_name, a.entity_type, type(r), b.canonical_name, b.entity_type, r.source_id, r.source_pages;
```

### 2. Nodos cuyo nombre contiene "tamori"

Lista todos los nodos del workspace cuyo `canonical_name` contiene la cadena
"tamori" (insensible a mayúsculas), para inspeccionar manualmente si son el
mismo concepto duplicado.

```cypher
-- 2. Todos los nodos cuyo nombre contiene "tamori" (para detectar duplicados)
MATCH (n:Entity {workspace:'leyenda'})
WHERE toLower(coalesce(n.canonical_name,'')) CONTAINS 'tamori'
RETURN elementId(n), n.canonical_name, n.display_name, n.entity_type, n.source_document, n.source_pages, n.confidence
ORDER BY n.canonical_name;
```

### 3. Relaciones salientes de "Rejn Clan"

Lista todas las relaciones donde el nodo origen es (o contiene en su nombre)
"Rejn", para ver el contexto completo de sus vínculos, incluyendo el posible
doble vínculo con `Tamori Family` / `Familia Tamori`.

```cypher
-- 3. Todas las relaciones salientes de "Rejn Clan"
MATCH (a:Entity {workspace:'leyenda'})-[r]->(b:Entity {workspace:'leyenda'})
WHERE a.canonical_name CONTAINS 'Rejn'
RETURN a.canonical_name, type(r), b.canonical_name, b.entity_type, r.confidence, r.source_document, r.source_pages;
```

## Script de auditoría automatizada

Además de las consultas manuales anteriores, existe un script de solo lectura
que automatiza la detección de candidatos a duplicado en todo el workspace:
`data-engine/app/tools/audit_duplicates.py`.

El script:

- Se conecta a Neo4j leyendo `S9K_NEO4J_URI`, `S9K_NEO4J_USER`,
  `S9K_NEO4J_PASSWORD` / `S9K_NEO4J_PASSWORD_FILE` (mismo esquema de
  configuración que el resto del proyecto).
- Ejecuta únicamente consultas `MATCH ... RETURN` — nunca `CREATE`, `SET`,
  `DELETE` ni `MERGE`.
- Detecta candidatos combinando: nombre normalizado igual (sin tildes, sin
  puntuación, con equivalencia básica EN/ES como "family"/"familia"),
  similitud de tokens/nombre (umbral `SIMILARITY_THRESHOLD = 0.75` con
  `difflib`), y coincidencia de `source_document`/solape de `source_pages`
  como señal de refuerzo para priorizar.
- Escribe un informe Markdown en `viewer/reports/duplicate_candidates.md`
  (nunca escribe en Neo4j).

### Cómo ejecutarlo

Con el túnel SSH activo hacia VM105:

```bash
# Ejemplo de túnel SSH hacia VM105 (ajustar host real)
ssh -L 7687:192.168.1.205:7687 usuario@bastion

# Variables de entorno (ejemplo, sin contraseña real en el repo)
export S9K_NEO4J_URI=bolt://127.0.0.1:7687
export S9K_NEO4J_USER=neo4j
export S9K_NEO4J_PASSWORD_FILE=/ruta/segura/neo4j_password.txt

python data-engine/app/tools/audit_duplicates.py --workspace leyenda
```

Si no hay túnel activo o las credenciales son incorrectas, el script falla de
forma explícita por stdout/stderr (sin traceback críptico) y **no** genera
`duplicate_candidates.md` con datos inventados.

## Hallazgos pendientes de decisión humana

1. **`HAS_FOUGHT` → `Location`/`Region`**: relación semánticamente incorrecta
   detectada con la consulta 1. Ya se corrigió a nivel de esquema/validación
   para futuras ingestas en `_check_relation_semantics`, dentro de
   `data-engine/app/ingest_rpg.py` (cambio realizado por otro trabajo en
   paralelo — no se toca aquí, se referencia como contexto cruzado). Los
   datos ya existentes en Neo4j con esta relación incorrecta **no** se han
   corregido; requieren revisión y corrección manual (o una migración
   dedicada) sobre el grafo real.
2. **`Tamori Family` / `Familia Tamori`**: candidato a duplicado detectado con
   las consultas 2 y 3, y por el script `audit_duplicates.py`. **No se ha
   fusionado nada.** Pendiente de revisión manual para decidir: cuál es el
   `canonical_name`/`entity_type` correcto, qué hacer con los alias, y cómo
   redirigir las relaciones (`BELONGS_TO` desde `Rejn Clan`, y cualquier otra
   que apunte a cualquiera de los dos nodos) antes de cualquier fusión.
