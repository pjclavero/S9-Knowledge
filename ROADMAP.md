# ROADMAP — S9 Knowledge


revisar [project dossier and checklist.md](docs/project%20dossier%20and%20checklist.md) para una mayor aclaracion del estado

## Fase 0 — Motor de datos (HECHO)

- Extracción PDF/texto/audio → Neo4j con LlamaIndex + Ollama (qwen2.5:7b).
- Schema RPG v1.5.0: personajes, criaturas/espíritus/demonios/bestias, lugares,
  facciones, objetos, eventos, combates, tareas, sesiones, documentos, imágenes.
- Trazabilidad completa (source_id/kind/path/hash, extractor/prompt version).
- Metadatos temporales y de sesión; validación semántica; estado de revisión.
- Capa de conocimiento por personaje (relaciones HAS_SEEN/HAS_FOUGHT/TELLS…).

## Fase 1 — Orden y versionado (EN CURSO)

- Repositorio Git limpio con código + documentación.
- `.gitignore`/`.env.example` seguros; sin secretos ni datos pesados.
- Preparado para remoto y clonado en el PC.

## Fase 2 — Fuentes externas (DISEÑADO, parcial)

- Cola de trabajos `job_store.py` (SQLite) — implementada.
- Audio Nextcloud vía cola — parcial (base existente `property-graph-audio`).
- YouTube — módulo `fetch_youtube.py` existente, falta integrarlo en la cola.
- Web (trafilatura/readability) — solo diseño; dependencia no instalada.
- Worker que consume la cola — pendiente.

## Fase 3 — Acceso: usuarios, personajes y permisos (DISEÑADO/IMPLEMENTADO base)

- `access_store.py`: vínculos usuario-personaje (multi-workspace), permisos por
  bóveda, audit log — implementado (SQLite).
- Aplicación real de reglas de visibilidad — pendiente (vive en API/visor).

## Fase 4 — Visor web (PENDIENTE)

- Visor de solo lectura del grafo (vistas de `docs/06-viewer-panel.md`).
- Filtros por workspace, visibilidad, capa de conocimiento y personaje activo.

## Fase 5 — Panel de gestión (PENDIENTE)

- "Fuentes / Importar" (alta de trabajos).
- `/control/users` (usuarios-personajes) y `/control/visibility` (conocimiento).
- Endpoints REST documentados en `docs/06-viewer-panel.md`.

## Fase 6 — Acceso externo (PENDIENTE)

- Publicación controlada (dominio/Cloudflare/HTTPS local ya disponible para
  SilverBullet en 4100–4112). Sin exponer Neo4j/Ollama.
