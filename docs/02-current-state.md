# 02 · Estado actual

Instantánea a 2026-07-11.

## HECHO

- `data-engine/app/schemas/rpg_schema.py` — **schema v1.5.0** (27 tipos de nodo,
  113 relaciones, 113 etiquetas ES, vocabularios controlados, ~200 normalizadores,
  campos opcionales temporales/estado/imagen/conocimiento).
- `data-engine/app/prompts/rpg_extraction_prompt.py` — **prompt v1.4.0**
  (transcript + book + conocimiento de personaje).
- `data-engine/app/ingest_rpg.py` — writer Neo4j actualizado (trazabilidad,
  metadatos temporales, nodo Session + APPEARS_IN, imágenes, semántica
  ok/dubious/invalid, review_status, `[AUDIT]` ampliada, nuevas CLI).
- `data-engine/app/jobs/job_store.py` — cola de trabajos SQLite.
- `data-engine/app/access/access_store.py` — usuario-personaje + permisos + audit.
- Documentación de diseño (VISOR, EXTERNAL_SOURCES, KNOWLEDGE_VISIBILITY,
  USERS_CHARACTERS, RPG_GRAPH_MODEL_UPDATE, INFORME_ENTREGA) — en `docs/current/`.
- **pytest 8/8**; `py_compile` OK en todos los módulos.
- Prueba end-to-end con `source_id = test_creatures_locations_timeline`
  (perfil transcript, sesión 4): estado `complete`, con nodo Session, APPEARS_IN y
  relaciones de conocimiento verificadas en Neo4j.

## NO HECHO

- Visor web.
- Panel de gestión (fuentes, usuarios, visibilidad).
- Aplicación real de filtros de visibilidad en API/UI.
- Worker que consume la cola de trabajos.
- Importación web real (dependencia trafilatura/readability no instalada).
- Integración de YouTube en la cola (el módulo de descarga/transcripción existe).
- Acceso externo por dominio/Cloudflare para el visor.

## Limitaciones conocidas

- Recall de **relaciones** limitado y volátil con qwen2.5:7b (las entidades son
  estables). Para producción, modelo mayor o few-shot reforzado.
- Nodos históricos (GM Guide pp.1-40): ~92 sin `source_id`, ~51 sin `source_kind`
  (previos a los fixes de trazabilidad). No tocados.
- Duplicados previos pendientes de fusión (p.ej. "Uso"/"Mirumoto Uso").
- `HAS_FOUGHT` con destino Lugar debería degradarse a `FOUGHT_AT` (refinar
  validación semántica).
