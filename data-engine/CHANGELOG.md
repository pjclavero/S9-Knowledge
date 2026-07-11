## 2026-07-10 — Mejora extracción RPG

### Archivos modificados
- `app/schemas/rpg_schema.py` → v1.3.0
- `app/ingest_rpg.py`
- `app/prompts/rpg_extraction_prompt.py` → v1.2.0

### Cambios principales
- Normalizador español→inglés para tipos de relación (~90 entradas)
- Soporte --profile (short/transcript/book/image-text)
- Segunda pasada LLM para Events/relaciones en perfil transcript
- Resolución fuzzy de source/target antes de Neo4j
- SYSTEM_PROMPT_TRANSCRIPT con ejemplos de todos los tipos de entidad
- Escritura incremental por chunk, log honesto

### Pruebas superadas
- test-ficha-akodo.md: 9 entidades, Opción B (LEARNS_FROM descartado)
- leyenda-transcripcion-prueba.md: 18 entidades de 7 tipos, 7/7 relaciones en Neo4j

