# 02 · Estado actual

Instantánea a 2026-07-12.

## HECHO

### Motor de datos y grafo
- `data-engine/app/schemas/rpg_schema.py` — **schema v1.5.0** (27 tipos de nodo,
  113 relaciones, 113 etiquetas ES, vocabularios controlados, normalizadores).
- `data-engine/app/prompts/rpg_extraction_prompt.py` — prompt v1.4.0.
- `data-engine/app/ingest_rpg.py` — writer Neo4j (trazabilidad, metadatos, Session).
- `data-engine/app/jobs/job_store.py` + `jobs/worker.py` — cola SQLite **con worker** (echo/noop).
- `data-engine/app/access/access_store.py` — usuario-personaje + permisos + audit (no aplicado en UI).

### Visor
- **Visor web desplegado** (FastAPI/uvicorn, `s9-knowledge-viewer.service`, puerto 8088).
- `/graph` (vis.js), `/jobs` (panel de cola), `/reviews` (cola de revisión).
- Fix móvil: la ficha lateral ya no tapa el grafo (se cierra/abre al tocar).

### Multimedia y transcripción
- Worker de ingesta multimedia (`data-engine/app/media/`) — escanea Nextcloud, extrae audio, transcribe.
- faster-whisper operativo con audios reales de Nextcloud. **`medium` recomendado** (0% error en nombres L5A vs 67% en `small`); no paralelizar (RAM).
- Glosario L5A + normalizador determinista (`data-engine/app/glossary/`) — ver [18](18-l5a-transcription-glossary-plan-and-test.md).

### Pipeline de revisión de datos (rama feat/data-processing-final-v0.2.5)
- `data-engine/app/review/` — segment → classify → extract → validate → resolve → decide → approved_payload.
- CLI `data_review.py`, `audit-graph`, ingesta **solo dry-run** (requiere autorización explícita para escribir). Ver [20](20-data-review-and-approved-ingest.md).
- Revisión humana mínima: solo los candidatos dudosos llegan a `review.md`.

### Infraestructura y seguridad (ver [21](21-external-access-and-security.md))
- Acceso externo: `https://knowledge.seccionnueve.duckdns.org` (nginx VM104 + Basic Auth).
- Neo4j cerrado a solo 127.0.0.1 (antes expuesto en LAN/Tailscale).
- VM105 ampliada a 6 vCPUs.

### Integración
- **main**: integración v0.2.4 (jobs + multimedia + validaciones).
- Ramas: `feat/l5a-transcription-glossary` (glosario) y `feat/data-processing-final-v0.2.5` (pipeline de revisión) → **PR draft #2**.

## NO HECHO / pendiente

- **Extractor LLM.** El extractor de candidatos es heurístico y da falsos positivos
  (`Llevás`/`Todo`/`Como` como Character). **La ingesta real a Neo4j está bloqueada**
  hasta sustituirlo por LLM + stopwords. De momento el pipeline queda en dry-run.
- Gestión de usuarios y aplicación real de filtros de visibilidad en API/UI.
- Login propio del visor (hoy solo Basic Auth en el proxy).
- Importación web real (trafilatura/readability) e integración de YouTube en la cola.
- Fusión de duplicados del grafo (audit-graph los detecta, no los corrige).

## Limitaciones conocidas

- Extractor heurístico con falsos positivos (ver arriba) — no ingerir sin revisar.
- Recall de **relaciones** limitado con qwen2.5:7b; entidades estables.
- Nodos históricos sin `source_id`/`source_kind` (~87/~51) detectados por audit-graph.
- Corrección LLM de transcripción (qwen2.5:7b, bloque completo) no preserva timestamps → queda deshabilitada; se usa el normalizador determinista.
- `HAS_FOUGHT` con destino Lugar debería degradarse a `FOUGHT_AT`.
