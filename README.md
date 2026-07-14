# S9 Knowledge

**S9 Knowledge** es una plataforma self-hosted para convertir documentos, audios,
webs, vídeos de YouTube y notas en un **grafo de conocimiento en Neo4j**, con visor
web y permisos por usuario / personaje / bóveda (workspace).

Pensada para campañas de rol (L5A "Leyenda", Mundo de Tinieblas, Trudvang…): extrae
personajes, criaturas, lugares, facciones, objetos, eventos, combates y sesiones, y
la evolución del conocimiento de cada personaje a lo largo de la campaña.

## Estado actual (v0.2.5b — verificado 2026-07-13)

> Commit desplegado en VM105: `1fd94b85` (v0.2.5b, 2026-07-10).
> Tests verificados: 196 recopilados, 155 aprobados, 41 fallidos (deuda técnica funcional — semántica del grafo, jobs, multimedia, visor; guard de ingesta 16/16 confirmado).
> Neo4j: 199 nodos, 140 relaciones. Visor: HTTP 200 en `/graph`, `/jobs`, `/reviews`.
> Informe de auditoría completo: [docs/24-vm105-baseline-and-verification.md](docs/24-vm105-baseline-and-verification.md).

### Listo y operativo

- `data-engine` funcional: motor de extracción PDF/texto/audio → pipeline de revisión → Neo4j.
- Schema RPG **v1.5.0** (27 tipos de nodo, 113 relaciones, etiquetas ES).
- Prompt RPG **v1.4.0** (transcripción + libro + conocimiento de personaje).
- Writer Neo4j con trazabilidad, metadatos temporales, sesiones, imágenes y estado de revisión.
- Cola de trabajos `job_store.py` (SQLite) con worker.
- Modelo de acceso `access_store.py` (usuario-personaje + permisos).
- Transcripción de audio con faster-whisper (`medium`); glosario L5A + normalizador determinista.
- **Visor web desplegado** (FastAPI/uvicorn, puerto 8088, `s9-knowledge-viewer.service`):
  - `/graph` — grafo interactivo con vis.js.
  - `/jobs` — panel de cola de trabajos.
  - `/reviews` — panel de revisión de candidatos: lista de fuentes con badges de origen,
    contadores (aprobados/pendientes/rechazados), detalle por fuente con metadatos del
    paquete (origin, producer, model, confidence), cola de revisión enriquecida con
    motivo de decisión y confianza, e informe de calidad (`quality_report.json/.md`)
    cuando lo genera el pipeline.
- Pipeline de revisión completo: segment → classify → extract → validate → resolve →
  decide → approved_payload. CLI `data_review.py`.

### Bloqueado (ingesta real en Neo4j)

Los extractores **LLM e híbrido ya existen y han sido evaluados** con el benchmark real
(run `20260714-094125`, 2026-07-14 — ver
[docs/34](docs/34-extractor-quality-benchmark-results.md)): F1 entidades hybrid 0.728 /
llm 0.718 (precisión llm 0.810, recall hybrid 0.856), relaciones F1 ≈ 0 y precisión de
autoaprobación 0.85. **Todavía no alcanzan los umbrales necesarios** (F1 entidades ≥ 0.75,
P ≥ 0.85, autoaprobación ≥ 0.95).

Por tanto, **la ingesta real de candidatos aprobados en Neo4j continúa bloqueada** (dictamen
Prioridad 2: PARCIAL — REQUIERE CORRECCIONES). `ingest_approved.py` exige `--dry-run`; la
escritura real aborta sin `S9K_ALLOW_REAL_INGEST=true` y autorización explícita. No ingerir
sin revisión humana.

> Nota histórica: el extractor **heurístico** produce falsos positivos conocidos
> (`Llevás`/`Todo`/`Como` como Character); por eso el modo recomendado es LLM/híbrido con
> revisión humana total, no heurístico puro.

### Preparado pero no completado

- Export/import externo de paquetes de revisión: diseño y estructura preparados;
  pendiente de completar (ver `docs/22-installation-and-replicability.md` cuando
  esté disponible).
- Replicabilidad del entorno: `.env.example` y documentación de despliegue en
  `docs/08-deployment-vm105.md`; no existe script de setup automatizado aún.
- Gestión de usuarios y filtros de visibilidad en la UI: implementados en
  `access_store.py` pero no aplicados en el visor.
- Login propio del visor: actualmente solo Basic Auth en el proxy nginx (VM104).

Detalle completo en [project dossier and checklist.md](docs/project%20dossier%20and%20checklist.md)

## Arquitectura (resumen)

```
Fuentes (PDF, texto, audio, YouTube, web, notas)
      │
      ▼
 data-engine  ── Whisper (audio) ── Extractor heurístico (LLM pendiente)
      │
      ▼  pipeline de revisión (segment/classify/extract/validate/resolve/decide)
      │
      ├── approved_payload.json  ──(dry-run)──► Neo4j (escritura real: bloqueada)
      │
      └── Visor web (FastAPI, puerto 8088)
            ├── /graph  — grafo vis.js
            ├── /jobs   — cola de trabajos
            └── /reviews — panel de revisión de candidatos
```

## Estructura del repositorio

```
s9-knowledge-repo/
├── README.md          · este archivo
├── CHANGELOG.md       · historial de cambios
├── ROADMAP.md         · fases y plan
├── .gitignore
├── .env.example       · variables de entorno (sin secretos)
├── docs/              · documentación del proyecto (00–22 + current/)
├── data-engine/       · motor de datos (app/, tests/, docs/…)
├── viewer/            · visor web (FastAPI, desplegado en VM105:8088)
├── shared/            · utilidades compartidas (FUTURO)
├── deployments/       · despliegue VM105
├── scripts/           · scripts auxiliares
└── examples/          · ejemplos
```

Ver [`docs/04-repository-structure.md`](docs/04-repository-structure.md).

## Puesta en marcha (referencia)

Este repo es una **instantánea de lo ya hecho en el servidor VM105**. No incluye
`.venv`, estado de runtime (`state/`, `output/`, `logs/`, `staging/`), bases de
datos SQLite de runtime, `.env` con secretos ni archivos fuente pesados (PDF/audio).

1. Copia `.env.example` a `.env` y rellena los valores reales.
2. El motor de datos (`data-engine/`) requiere Python 3.11+, Neo4j y Ollama.
   Instalación en `docs/08-deployment-vm105.md`.
3. El visor (`viewer/`) requiere Python 3.11+ y se sirve con uvicorn.
   Servicio systemd: `s9-knowledge-viewer.service`.

## Seguridad

- No se versionan secretos (`.env`, tokens, claves, certificados) ni datos de
  campaña sensibles (audios, PDFs originales, transcripciones privadas).
- Neo4j y Ollama no se exponen a Internet.
- Acceso externo via `https://knowledge.seccionnueve.duckdns.org` (nginx VM104 + Basic Auth).
- Ver `docs/07-users-permissions.md` para el modelo de permisos.
- Ver `docs/21-external-access-and-security.md` para acceso externo y hardening.

## Licencia

Uso interno del homelab Sección 9. Sin licencia pública definida todavía.
