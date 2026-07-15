# 01 · Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│ FUENTES                                                     │
│  PDF · texto · audio · YouTube · web · notas manuales       │
└───────────────┬─────────────────────────────────────────────┘
                │  (cola de trabajos: state/jobs.db)
                ▼
┌─────────────────────────────────────────────────────────────┐
│ DATA-ENGINE (data-engine/app)                               │
│  · Whisper / faster-whisper  → transcripción de audio       │
│  · Ollama (qwen2.5:7b) + prompts → extracción entidades/rel │
│  · rpg_schema.py  → validación Pydantic + normalizadores    │
│  · ingest_rpg.py  → writer Neo4j con trazabilidad           │
└───────────────┬─────────────────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────┐
│ NEO4J (grafo, multi-workspace)                              │
│  nodos: Character/Creature/Location/Faction/…/Session/Image │
│  relaciones: narrativas + de conocimiento por personaje     │
└───────────────┬───────────────────────────┬─────────────────┘
                │                           │
                ▼                           ▼
        SilverBullet (edición        Visor web + Panel (FUTURO)
        manual en Markdown)          filtros de visibilidad
```

## Componentes en VM105 (192.168.1.205)

| Componente | Dónde | Estado |
|---|---|---|
| Neo4j | contenedor `neo4j-knowledge` (bolt 7687) | producción |
| Ollama | 192.168.1.157:11434 (qwen2.5:7b) | producción |
| data-engine | `/opt/knowledge-services/property-graph` | producción |
| SilverBullet | contenedores `silverbullet-*` (3100–3112 / HTTPS 4100–4112) | producción |
| Cola trabajos | `state/jobs.db` (SQLite) | implementada |
| Acceso/permisos | `state/access.db` (SQLite) | implementado |
| Visor / Panel | — | pendiente |
| IA externa (NVIDIA, revisión sombra) | `external_ai/` | implementado (Fase A, shadow); docs/42 |

## Flujo de datos

1. Una fuente entra como **trabajo** (`job_store.py`) → estado `pending`/`needs_metadata`.
2. Se transcribe (si audio/vídeo) y se extraen entidades/relaciones con el LLM.
3. El writer persiste en Neo4j con trazabilidad y metadatos temporales.
4. La visibilidad (por sesión y por personaje) se aplicará en el visor/API (futuro).
