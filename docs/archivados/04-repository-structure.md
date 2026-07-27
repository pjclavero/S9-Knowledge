# 04 · Estructura del repositorio

```
s9-knowledge-repo/
├── README.md
├── CHANGELOG.md
├── ROADMAP.md
├── .gitignore
├── .env.example
├── docs/
│   ├── INDEX.md
│   ├── 00-vision.md
│   ├── 01-architecture.md
│   ├── 02-current-state.md
│   ├── 03-phases.md
│   ├── 04-repository-structure.md
│   ├── 05-data-engine.md
│   ├── 06-viewer-panel.md
│   ├── 07-users-permissions.md
│   ├── 08-deployment-vm105.md
│   ├── 09-audit-before-work.md
│   ├── 10-clone-on-windows.md
│   └── current/            · docs de diseño ya generados en el servidor
├── data-engine/            · copia del motor actual (app/, tests/, docs/, config…)
│   ├── app/
│   │   ├── schemas/rpg_schema.py
│   │   ├── prompts/rpg_extraction_prompt.py
│   │   ├── ingest_rpg.py
│   │   ├── jobs/job_store.py
│   │   ├── access/access_store.py
│   │   ├── audio/  · youtube/  · exporters/
│   │   └── tests/
│   ├── tests/
│   ├── config/
│   ├── docker/
│   ├── requirements.in · requirements.lock
│   └── CHANGELOG.md
├── viewer/                 · FUTURO (vacío, con .gitkeep)
├── shared/                 · FUTURO (vacío, con .gitkeep)
├── deployments/            · FUTURO (vacío, con .gitkeep)
├── scripts/                · scripts auxiliares
└── examples/               · ejemplos (datos de prueba no sensibles)
```

## Qué NO está en el repo (excluido por `.gitignore` / rsync)

- `.venv/`, `__pycache__/`, `.pytest_cache/`
- Runtime: `logs/`, `state/`, `output/`, `staging/`
- Bases de datos de runtime: `*.db`, `*.sqlite*` (incluye `jobs.db`, `access.db`)
- Secretos: `.env`, tokens, claves, certificados
- Datos fuente pesados: `*.pdf`, `*.mp3/wav/m4a/mp4`, dumps de Neo4j

Los módulos de código (`job_store.py`, `access_store.py`) **sí** están; lo que se
excluye son las **bases de datos** que generan en runtime.
