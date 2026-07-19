# Mapa de propiedad

## Áreas compartidas — propiedad exclusiva del Organizador

Cambios en estas rutas **no** los realiza un bloque directamente. El agente documenta la
necesidad; el Organizador abre una **PR pequeña separada**, con su propia supervisión, que se
integra **antes** de continuar el bloque; luego se repiten los tests del bloque sobre el nuevo `main`.

```text
pytest.ini
pyproject.toml
requirements*.txt
package*.json
.github/workflows/**           (hoy: .github/workflows/ci.yml)
conftest.py                    (raíz)
project-status.yaml            (si existe)
viewer/app/main.py
contracts/**                   (esquemas de contrato review/ingest)
migraciones globales
configuración global
documentos globales de estado
```

## Rutas de trabajo por bloque (propiedad del implementador del bloque)

Base real de código de relaciones: `data-engine/app/relations/`.

| Bloque | Rutas principales (dentro de alcance) |
|---|---|
| 1 — Ollama sombra | `data-engine/app/relations/local_llm_shadow.py`, `prompts/templates.py`, tests de sombra |
| 2 — NVIDIA sombra | `data-engine/app/relations/external_ai_shadow.py`, `app/external_ai/nvidia_nim.py`, `app/external_processing/providers/nvidia.py`, tests |
| 3 — Predicados | `data-engine/app/review/relation_normalizer.py`, `relations/contracts.py`, vocabulario canónico + tests |
| 4 — Temporalidad | `data-engine/app/relations/signals.py`, `syntax.py`, `pipeline.py` (rutas de temporalidad) + tests |
| 5 — Epistémico | `data-engine/app/relations/signals.py`, `pipeline.py` (estado epistémico/rumor) + tests |
| 6 — Ensemble | `data-engine/app/relations/consensus_adapter.py`, `app/external_ai/consensus.py`, `pipeline.py` (combinación) + tests |
| 7 — Benchmark | `data-engine/app/relations/benchmark/**`, `app/cli/*benchmark*.py`, corpus (solo lectura / versionado) |
| 8 — Política revisión | `data-engine/app/relations/` (clasificación de candidatos), sin escritura productiva |
| 9 — QA final | `tests/**`, `tests/wave2/**`, `tests/wave2b/**` (validación transversal, sin cambios funcionales) |

## Regla de no solapamiento

- No se ejecutan dos bloques funcionales dependientes simultáneamente.
- Un implementador **no** modifica áreas compartidas sin la PR de coordinación previa.
- Un implementador **no** repara incidentalmente otros bloques ni toca sus rutas.
- Solo pueden solaparse tareas **puramente documentales o de análisis** que no modifiquen las
  mismas rutas ni adelanten implementación de bloques futuros.

## Corpus del benchmark (versionado, no destructivo)

- `data-engine/app/tests/data/relation_benchmark/` (16 fuentes + ground truth + schemas).
- `tests/fixtures/benchmark/` (fixtures por tipo de fuente).
- El corpus B1 original **no se modifica**. Si se necesita variación, crear **B1 v2** manteniendo
  B1 v1, justificar y comparar ambos (ver Bloque 7).
