# S9 Knowledge

**S9 Knowledge** es una plataforma self-hosted para convertir documentos, audios,
webs, vídeos de YouTube y notas en un **grafo de conocimiento en Neo4j**, con visor
web y permisos por usuario / personaje / bóveda (workspace).

Pensada para campañas de rol (L5A "Leyenda", Mundo de Tinieblas, Trudvang…): extrae
personajes, criaturas, lugares, facciones, objetos, eventos, combates y sesiones, y
la evolución del conocimiento de cada personaje a lo largo de la campaña.

## Estado actual (RC5.1 — 2026-07-18)

> **Producción (VM105):** release `deploy-v0.3.0-rc5.1` (`47bc314`), visor
> `s9-knowledge-viewer.service` active/running. **Login propio del visor** (Basic Auth
> retirada del proxy). Neo4j **199 nodos / 140 relaciones**. 1 administrador, 1 job,
> **0 ingestas** (ingesta real bloqueada por doble guard). Healthcheck con **timer horario**
> activo. Despliegue por releases inmutables + deploy-tools versionados.
>
> El estado autoritativo y verificable está en [`docs/project-status.yaml`](docs/project-status.yaml)
> y se narra en [`docs/02-current-state.md`](docs/archivados/02-current-state.md). External AI (NVIDIA) en
> modo sombra; burst orchestrator B1 implementado (B2/B3 pendientes).

### Línea principal del repositorio: V3

Desde el merge de la PR #110, `main` contiene como línea vigente el subsistema
`knowledge_v3`. V3 no está desplegada en VM105: el bloque anterior describe
producción y sigue siendo independiente del estado del repositorio.

La línea V3 incluye:

- contratos congelados bajo el tag `v3-contracts-frozen-1.0.0`;
- extracción determinista y semántica episódica, seguida de reconciliación de
  propuestas antes de entrar en el motor;
- motor local como autoridad de decisión, con política graduada de negaciones y
  temporalidad implementada tras flags que permanecen **OFF** hasta medirla en sombra;
- ledger temporal bitemporal y writer Neo4j con dry-run y gate explícito del operador;
- evidencia multimodal tipada como `OCR_TEXT`, `TRANSCRIBED_TEXT` o
  `VISUAL_INFERRED`; esta última nunca se autoaprueba;
- transcripción manuscrita integrada en el carril `OCR_TEXT`.

Los Lotes 1, 2, 2b, 3 y 6 del plan técnico ya están completados y mergeados
(PRs #111–#114). Los Lotes 4 y 5 requieren decisiones de producto; la activación
de las políticas graduadas requiere medición en sombra; el despliegue V3 sigue
pendiente. El plan vigente es
[`docs/v3/32-plan-consolidado-extractor-y-nucleo.md`](docs/v3/32-plan-consolidado-extractor-y-nucleo.md).

### Legacy v1/v2

El pipeline RPG v1/v2, sus benchmarks de extractor, el review/ingest anterior y
la documentación narrativa asociada se conservan como **legacy** y como contexto
de la release RC5.1 que continúa en producción. No son el camino de desarrollo
actual. Los documentos históricos están indexados en
[`docs/archivados/INDEX.md`](docs/archivados/INDEX.md).

## Arquitectura (resumen)

```
Fuentes (PDF, texto, audio, YouTube, web, notas)
      │
      ▼
 data-engine  ── OCR / transcripción ── Extractor V3 determinista + semántico
      │
      ▼  reconciliador ── motor local ── ledger temporal
      │
      └── plan de escritura ── gate del operador ──► Neo4j
```

La arquitectura desplegada en producción sigue siendo la de RC5.1, no este
flujo V3.

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

Ver [`docs/04-repository-structure.md`](docs/archivados/04-repository-structure.md)
para la fotografía legacy y [`docs/v3/`](docs/v3/) para la línea vigente.

## Puesta en marcha (referencia)

Este repo es una **instantánea de lo ya hecho en el servidor VM105**. No incluye
`.venv`, estado de runtime (`state/`, `output/`, `logs/`, `staging/`), bases de
datos SQLite de runtime, `.env` con secretos ni archivos fuente pesados (PDF/audio).

1. Copia `.env.example` a `.env` y rellena los valores reales.
2. El motor de datos (`data-engine/`) requiere Python 3.11+, Neo4j y Ollama.
   Instalación legacy en
   [`docs/08-deployment-vm105.md`](docs/archivados/08-deployment-vm105.md).
3. El visor (`viewer/`) requiere Python 3.11+ y se sirve con uvicorn.
   Servicio systemd: `s9-knowledge-viewer.service`.

## Seguridad

- No se versionan secretos (`.env`, tokens, claves, certificados) ni datos de
  campaña sensibles (audios, PDFs originales, transcripciones privadas).
- Neo4j y Ollama no se exponen a Internet.
- Acceso externo via `https://knowledge.seccionnueve.duckdns.org` (HTTPS, nginx VM104).
  La autenticación es del propio visor (login con sesiones/CSRF); Basic Auth retirada del proxy.
- Ver [`docs/07-users-permissions.md`](docs/archivados/07-users-permissions.md)
  para el modelo legacy de permisos.
- Ver
  [`docs/21-external-access-and-security.md`](docs/archivados/21-external-access-and-security.md)
  para acceso externo y hardening de la release desplegada.

## Licencia

Uso interno del homelab Sección 9. Sin licencia pública definida todavía.
