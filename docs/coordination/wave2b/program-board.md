# Tablero OLA 2B

Base `a0ffc21`. Estados: READY · BLOCKED · IN_PROGRESS · AUDIT · READY_FOR_PR ·
READY_FOR_MERGE · DONE.

## Lote 1 — independientes (lanzados con agentes reales)

| ID | Agente | Rama | Ficheros | Dep | Estado |
|----|--------|------|----------|-----|--------|
| P7 | RK-05 | `fix/viewer-neo4j-default-fail-closed` | viewer/app/config.py + test aislamiento + doc dev | — | IN_PROGRESS |
| R1 | pares | `feat/relation-pair-generator-v1` | data-engine/app/relations/pairs.py + test | contrato (en main) | IN_PROGRESS |
| R2 | heurísticas | `feat/relation-heuristics-v1` | data-engine/app/relations/signals.py + test | contrato | IN_PROGRESS |
| R4 | prompts RPG | `feat/relation-rpg-prompts-v1` | data-engine/app/relations/prompts/** + test | contrato (ref external_ai/prompts) | IN_PROGRESS |
| P1 | threat model | `docs/relation-pipeline-threat-model-v1` | docs/coordination/wave2b/threat-model.md | — | IN_PROGRESS |

## Lotes siguientes (BLOCKED por dependencias)

| ID | Rama | Dep |
|----|------|-----|
| R3 adaptador sintáctico | `feat/relation-syntax-adapter-v1` | interfaz (puede arrancar; se agenda tras lote 1) |
| R5 LLM local sombra | `feat/relation-local-llm-shadow-v1` | R3 + R4 estables; reutiliza external_ai/openai_compatible |
| R6 IA externa sombra | `feat/relation-external-ai-shadow-v1` | reutiliza external_ai/nvidia_nim + consensus |
| R7 consenso | `feat/relation-consensus-v1` | R1+R2 integrados; reutiliza external_ai/consensus.py |
| R8 pipeline | `feat/relation-pipeline-v1` | R1,R2,R3,R4,R7 |
| B1 corpus benchmark | `test/relation-benchmark-corpus-v1` | — (puede adelantarse) |
| B2 runner+comparador | `test/relation-benchmark-runner-v1` | R8 + B1; docs/41,42 NUEVOS |
| P2 observabilidad | `feat/relation-observability-v1` | — |
| P3 UX review (spec) | `docs/relation-review-ux-spec-v1` | — |
| P4 export funcional (diseño) | `docs/export-functional-design-v1` | contrato export |
| P5 import seguro (diseño) | `docs/import-safe-design-v1` | contrato import (APPLY OFF) |
| P6 plan multimedia | `docs/multimedia-runtime-plan-v1` | contrato multimedia |
| P8 QA Wave 2B | `test/wave2b-quality-matrix-v1` | rebase final contra producto real; gate 12/12 mutaciones |

## Reglas

- PRs draft, contra main; Supervisor rev.2 CONFORME antes de merge.
- Áreas compartidas (pytest.ini, requirements, .github, project-status) → PR de
  integración del Organizador.
- Ningún merge en esta primera ejecución más allá de lo estrictamente listo.
