# 22 · Instalación y replicabilidad (preparada, no completada)

> Relacionado: IA externa NVIDIA en modo sombra (revisión/consenso/calibración) — ver [docs/42](42-external-ai-calibration-and-burst-processing.md). Nada externo escribe en Neo4j.

Actualizado 2026-07-12. Estado: **diseño documentado; la instalación replicable completa NO está implementada**.

## Filosofía

El core de S9 Knowledge no debe depender de VM105 ni obligatoriamente de Nextcloud. VM105 es
un *deployment* concreto (`deployments/local-vm105/`), no un requisito. En esta fase se
auditan hardcodes y se documentan los modos futuros; no se construye instalador ni wizard.

## Modos de instalación futuros

| Modo | Descripción |
|------|-------------|
| **A — Con Nextcloud** | Fuentes y paquetes en Nextcloud (montaje rclone read-only + carpeta de escritura autorizada). Como VM105 hoy. |
| **B — Sin Nextcloud** | Carpetas locales (`S9K_DATA_ROOT`). Todo el pipeline funciona igual. |
| **C — Híbrido** | Nextcloud como almacén principal + cache/procesamiento local. |

## Variables de configuración

| Variable | Default | Estado |
|---|---|---|
| `S9K_ALLOW_REAL_INGEST` | `false` | **implementada** (doble guard de ingesta) |
| `S9K_REVIEW_EXTRACTOR` | `hybrid`/`heuristic` | **implementada** (heuristic/llm/hybrid) |
| `S9K_NEO4J_URI` / `_USER` / `_PASSWORD` | viewer/.env | **implementada** |
| `S9K_GLOSSARY_DB` | `state/glossary.db` | **implementada** |
| `S9K_MEDIA_*` | ver docs/14 | **implementada** |
| `S9K_JOBS_DB` | `state/jobs.db` | **implementada** |
| `S9K_DATA_ROOT` | repo root | preparada (documentada, no cableada en todo el core) |
| `S9K_STATE_ROOT` | `state/` | preparada |
| `S9K_OUTPUT_ROOT` | `output/` | preparada |
| `S9K_WORKSPACES_ROOT` | — | documentada |
| `S9K_USE_NEXTCLOUD` | `true` en VM105 | documentada |
| `S9K_NEXTCLOUD_BASE_PATH` | `/mnt/nextcloud-rol` | documentada |
| `S9K_REVIEW_EXPORTS_ENABLED` | `true` | documentada |
| `S9K_EXTERNAL_IMPORTS_ENABLED` | `false` | documentada |

## Auditoría de hardcodes

Aceptables (docs, deployments/local-vm105, fixtures, tests, defaults de env):
- Rutas `/opt/knowledge-services` y `/mnt/nextcloud-rol` como *defaults* configurables en `media/config.py` (sobreescribibles por `S9K_MEDIA_*`).
- `leyenda` como workspace por defecto (parámetro `--workspace` en todo el CLI).
- `media_2bdf6005fcffd476` solo en docs/tests como fuente de ejemplo.

Pendientes (no bloqueantes, a revisar en la fase de instalador):
- `_REPO_ROOT` calculado por posición de fichero en varios módulos (frágil si se instala como paquete).
- El visor asume `output/reviews/` relativo a la raíz del repo.
- IPs/dominios solo en docs y deployments (correcto), no en core.

## Política de almacenamiento

```
Nextcloud = almacén principal, compartible y recuperable
VM105     = procesamiento local, cache, colas, estado técnico
Neo4j     = grafo vivo aprobado
Git       = código y documentación
```

Diseño futuro de carpetas por ambientación en Nextcloud (NO implementado aún):
`00_fuentes / 10_transcripciones / 20_glosario / 30_pipeline / 40_exports / 50_informes / 90_archivo`

## Qué NO se hace en esta fase

Instalador completo, wizard, Docker genérico final, gestión web de workspaces,
creación automática de estructura Nextcloud, permisos Nextcloud desde panel.
