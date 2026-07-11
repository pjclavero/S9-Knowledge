# S9 Knowledge

**S9 Knowledge** es una plataforma self-hosted para convertir documentos, audios,
webs, vídeos de YouTube y notas en un **grafo de conocimiento en Neo4j**, con visor
web y permisos por usuario / personaje / bóveda (workspace).

Pensada para campañas de rol (L5A "Leyenda", Mundo de Tinieblas, Trudvang…): extrae
personajes, criaturas, lugares, facciones, objetos, eventos, combates y sesiones, y
la evolución del conocimiento de cada personaje a lo largo de la campaña.

## Estado actual

- `data-engine` existente y funcional (extracción PDF/texto/audio → Neo4j).
- Schema RPG **v1.5.0** (27 tipos de nodo, 113 relaciones, etiquetas ES).
- Prompt RPG **v1.4.0** (transcripción + libro + conocimiento de personaje).
- Writer Neo4j actualizado (trazabilidad, metadatos temporales, sesiones, imágenes,
  validación semántica, estado de revisión).
- Cola de trabajos `job_store.py` (SQLite) diseñada/implementada.
- Modelo de acceso `access_store.py` (usuario-personaje + permisos) implementado.
- **Visor web: todavía no implementado.**
- **Panel de gestión: todavía no implementado.**

Detalle en [`docs/02-current-state.md`](docs/02-current-state.md) y en el informe de
entrega [`docs/current/INFORME_ENTREGA.md`](docs/current/INFORME_ENTREGA.md).

## Arquitectura (resumen)

```
Fuentes (PDF, texto, audio, YouTube, web, notas)
      │
      ▼
 data-engine  ── Whisper (audio) ── Ollama/LlamaIndex (extracción)
      │
      ▼
   Neo4j  (grafo de conocimiento, multi-workspace, con trazabilidad)
      │
      ├── SilverBullet (edición manual opcional en Markdown)
      └── Visor web + Panel (FUTURO: filtros de visibilidad por personaje)
```

## Estructura del repositorio

```
s9-knowledge-repo/
├── README.md          · este archivo
├── CHANGELOG.md       · historial de cambios
├── ROADMAP.md         · fases y plan
├── .gitignore
├── .env.example       · variables de entorno (sin secretos)
├── docs/              · documentación del proyecto (00–10 + current/)
├── data-engine/       · motor de datos (código actual: app/, tests/, docs/…)
├── viewer/            · visor web (FUTURO, vacío)
├── shared/            · utilidades compartidas (FUTURO)
├── deployments/       · despliegue VM105 (FUTURO)
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

## Seguridad

- No se versionan secretos (`.env`, tokens, claves, certificados) ni datos de
  campaña sensibles (audios, PDFs originales, transcripciones privadas).
- Neo4j y Ollama no se exponen a Internet.
- Ver `docs/07-users-permissions.md` para el modelo de permisos.

## Licencia

Uso interno del homelab Sección 9. Sin licencia pública definida todavía.
