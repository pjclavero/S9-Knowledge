# Mapa de propiedad de ficheros

Cada área tiene **un** propietario. Dos equipos nunca editan el mismo fichero a la
vez. Los conflictos previsibles se resuelven vía PR de integración del Organizador.

## Áreas compartidas (SOLO el Organizador, vía PR de integración)

| Área | Motivo |
|------|--------|
| `contracts/**` | contrato público v1; cambios requieren aprobación del Supervisor |
| `viewer/app/main.py` | registro de routers (colisión entre equipos) |
| `pyproject.toml`, `*/requirements*.txt`, `*/requirements.lock`, `package*.json` | dependencias |
| `.github/workflows/**`, `.github/dependabot.yml` | CI/CD y supply chain |
| `project-status.yaml`, `docs/02-current-state.md` | estado global |
| migraciones globales | consistencia de esquema |

Los equipos **proponen** cambios a estas áreas como documento o commit aislado; el
Organizador los aplica en un PR de integración tras revisión del Supervisor.

## Equipo R — RC6 y validación

- Permitido: `tests/` de auditoría, `docs/coordination/pre-rc6-*`, scripts de
  validación **no productivos**, informes de release.
- Prohibido: nuevas funciones de motor, OCR, import/export, relaciones nuevas,
  cambios de arquitectura, producción.

## Equipo A — motor, relaciones y calidad

- Permitido (nuevo): `data-engine/app/relations/**` (pipeline de relaciones nuevo),
  contratos **internos** versionados bajo `data-engine/app/relations/contracts/**`,
  `data-engine/app/prompts/relations/**`, tests propios, `docs/41-*`, `docs/42-*`.
- **Extiende, no duplica**: `external_ai/`, `external_processing/providers/nvidia.py`
  (ya existen — el ensemble los consume, no los reescribe).
- Prohibido: contratos públicos v1, main.py, deps, workflows, panel B, tests de D.

## Equipo B — multimedia, export/import y plataforma

- Permitido (nuevo): `data-engine/app/export_import/**` (extiende
  `test_review_export_import`), `data-engine/app/media/**` (extiende
  `media/transcriber.py`), `data-engine/app/ocr/**`, contratos internos de
  export/import/multimedia, corpus **sanitizado** de ejemplo, `docs/coordination/`
  de plataforma, prototipos UX (sin integrar en main.py).
- Propone (área compartida): `.github/dependabot.yml`, registro de routers.
- Prohibido: main.py directo, contratos v1, motor de relaciones de A, producción.

## Equipo Q — QA transversal

- Permitido: tests de regresión/mutación/hostiles bajo `tests/` (namespace Q), la
  matriz QA (doc). **No corrige producto**: reproduce, asigna severidad, bloquea
  gate, propone PR correctivo al equipo propietario.

## Scaffolding existente (NO duplicar)

Verificado en `main@6d6c21f`:

| Módulo existente | Estado | Equipo que lo extiende |
|------------------|--------|------------------------|
| `data-engine/app/external_ai/**` | base + estados STRONG/PARTIAL/CONFLICT/INVALID/HUMAN, modo sombra; Fase B stub | A (ensemble), B (multimedia) |
| `data-engine/app/external_processing/providers/nvidia.py` | provider NVIDIA (stub NotImplementedError en parte) | A (ensemble) |
| `data-engine/app/media/transcriber.py` | ASR faster-whisper parcial | B (multimedia) |
| `data-engine/app/tests/test_review_export_import.py` | export/import con redacción de IPs/rutas probada | B (export/import) |
| `data-engine/app/cli/extractor_benchmark.py`, `benchmark_comparator.py` | benchmark de extractor (Prioridad 2) | A (benchmark de relaciones = NUEVO doc, no sobrescribe 34/36/37) |
| `data-engine/app/review/controlled_ingest/**` | motor controlado (gate APPLY, DRY_RUN) | — (congelado; A no lo reescribe) |

## Conflictos previsibles y resolución

| Conflicto | Resolución |
|-----------|------------|
| A y B tocan `requirements.lock` | Organizador consolida en un PR de deps |
| B registra routers en `main.py` | PR de integración del Organizador tras rev. Supervisor |
| A y B añaden ejemplos a `contracts/` | prohibido; usan contratos internos hasta promoción a v2 |
| Cualquiera edita `project-status.yaml` | solo Organizador, al cerrar cada ola |
