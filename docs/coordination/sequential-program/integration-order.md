# Orden e integración de bloques

La ejecución es estrictamente secuencial. Cada flecha exige el checkpoint
`MERGED_AND_MAIN_GREEN` del bloque anterior.

```text
BLOQUE 0  Auditoría y coordinación (docs)          ── base del programa
   ↓
BLOQUE 1  Ollama real en sombra                    ── requiere endpoint Ollama
   ↓
BLOQUE 2  NVIDIA real en sombra                     ── requiere S9K_NVIDIA_API_KEY
   ↓
BLOQUE 3  Normalización de predicados
   ↓
BLOQUE 4  Temporalidad
   ↓
BLOQUE 5  Rumores / estado epistémico
   ↓
BLOQUE 6  Ensemble calibrado                        ── depende de 1–5
   ↓
BLOQUE 7  Reejecución del benchmark                 ── corpus B1 v1 inmutable
   ↓
BLOQUE 8  Reducción controlada de revisión humana
   ↓
BLOQUE 9  QA transversal y cierre
```

## Dependencias explícitas

- **Bloque 6** no comienza hasta cerrar los Bloques 1–5.
- **Bloque 7** usa el corpus B1 original sin modificar; cualquier variación es B1 v2 aparte.
- **Bloque 2** depende de un secreto externo. Si no hay clave ni endpoint accesible: `BLOQUEADO`.
  No se simula ejecución. Saltar al Bloque 3 con el Bloque 2 marcado "no ejecutable por causa
  externa" requiere aprobación explícita del Organizador, documentada en el checkpoint.

## Áreas compartidas y su ventana de integración

Si un bloque necesita tocar un área compartida (ver `ownership-map.md`), la PR de coordinación
del Organizador se integra **antes** de reanudar el bloque, y los tests del bloque se repiten
sobre el nuevo `main`. No se solapa esa PR con la implementación del bloque.

## Validación post-merge (GATE G) — checklist por bloque

Desde un worktree limpio `--detach` sobre `origin/main`:

```text
suite específica del bloque
suite de relaciones
Wave 2B
production-block
tests de seguridad
tests de determinismo
pip-audit
secret scan
Unicode scan
diff-check
no-network / no-write / no-Neo4j
```

Confirmar siempre: `release/rc6-candidate = 15ae1d4` · producción intacta ·
`S9K_ALLOW_REAL_INGEST = off`. El worktree de validación se elimina solo tras registrar el resultado.
