# 05 · Motor de datos (data-engine)

Código en `data-engine/app/`. Copia de `/opt/knowledge-services/property-graph`.

## Módulos principales

| Módulo | Rol |
|---|---|
| `schemas/rpg_schema.py` | Modelos Pydantic, allowlists de tipos/relaciones, etiquetas ES, vocabularios, normalizadores. **v1.5.0** |
| `prompts/rpg_extraction_prompt.py` | Prompts de extracción (transcript/book/conocimiento). **v1.4.0** |
| `ingest_rpg.py` | Pipeline: leer → chunk → LLM → validar → escribir en Neo4j. CLI principal (`property-graph-rpg`). |
| `jobs/job_store.py` | Cola de trabajos SQLite (fuentes externas). |
| `access/access_store.py` | Usuario-personaje, permisos por workspace, audit log. |
| `audio/` | Transcripción con faster-whisper. |
| `youtube/` | Descarga/transcripción de YouTube (`property-graph-youtube`). |
| `exporters/` | Exportación a SilverBullet/Markdown. |

## CLI (property-graph-rpg)

```
--workspace <ws>            (leyenda | mundo_tinieblas | trudvang | infrastructure)
--pdf / --text / --image <ruta>
--pages 1-20               (PDF)
--profile short|transcript|book|image-text
--source-id <id>  --source-kind book|pdf|audio|transcript|text|image|youtube|web|manual_note|reference|test
--knowledge-layer <..>  --visibility <..>
--session-number N --session-title "…" --session-date YYYY-MM-DD --campaign-arc "…"
--source-url/--source-title/--source-author
--export-json  --export-markdown  --force  --dry-run  --no-neo4j
```

## Modelo de grafo (resumen)

- **Nodos**: Character, Creature, NonHuman, Spirit, Demon, Beast, Location, Region,
  Faction, Clan, Family, School, Group, Object, Artifact, Spell, Rule, Concept,
  Event, Encounter, Combat, Task, Session, Document, Chapter, Transcript, Image.
- **Relaciones**: narrativas (LOCATED_IN, FOUGHT_AT, ATTACKED, ALLY_OF…), de
  sesión/evento (OCCURS_DURING, PARTICIPATES_IN, INVOLVES…), de fuente
  (EXTRACTED_FROM, HAS_TRANSCRIPT…) y de **conocimiento por personaje**
  (HAS_SEEN, HAS_FOUGHT, HAS_HEARD_ABOUT, TELLS, DISCOVERED…).
- **Trazabilidad** en todos: workspace, source_id, source_kind, source_path,
  source_hash, extractor_version, prompt_version, knowledge_layer, visibility,
  review_status.

Detalle en `docs/current/RPG_GRAPH_MODEL_UPDATE.md` y `docs/current/VISOR_DESIGN.md`.

## Pruebas

```
cd data-engine && .venv/bin/python -m pytest app/tests/ -q     # 8/8
```
(el `.venv` no se versiona; se recrea con `requirements.lock`.)

> **Nota de auditoría (2026-07-13):** El número de tests ha crecido desde la redacción inicial de este documento.
> En commit `1fd94b85` (v0.2.5b), ejecutando desde la raíz del repo con el venv de producción:
> **196 tests recopilados, 155 aprobados, 41 fallidos** (deuda técnica de API — cambio de firma `create_job()`,
> mapeo semántico `FOUGHT_AT`, `source_kind='video'`, imports rotos en viewer tests).
> No se ha demostrado impacto directo sobre la doble protección de escritura (`--dry-run` + `S9K_ALLOW_REAL_INGEST`), pero los fallos afectan a la fiabilidad funcional en múltiples componentes y deben resolverse antes de la primera ingesta real.
> Ver [docs/24-vm105-baseline-and-verification.md §10](24-vm105-baseline-and-verification.md) para desglose completo.
