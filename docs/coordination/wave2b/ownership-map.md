# Mapa de propiedad — OLA 2B

Un fichero, un propietario. Dos agentes nunca editan el mismo fichero.

## Áreas compartidas (SOLO Organizador, vía PR de integración)

`pytest.ini` · `pyproject.toml` · `*/requirements*` · `package*.json` ·
`.github/workflows/**` · `.github/dependabot.yml` · `project-status.yaml` ·
`docs/02-current-state.md` · migraciones globales.

## Propiedad por agente (submódulos disjuntos de `data-engine/app/relations/`)

| Agente | Ficheros propios | Prohibido |
|--------|------------------|-----------|
| R1 pares | `relations/pairs.py` + `data-engine/app/tests/test_relation_pairs.py` | signals/prompts/contracts; external_ai; viewer |
| R2 heurísticas | `relations/signals.py` + `test_relation_signals.py` | pairs/prompts/contracts |
| R3 sintaxis | `relations/syntax.py` + `test_relation_syntax.py` | otros submódulos |
| R4 prompts | `relations/prompts/**` + `test_relation_prompts.py` | contracts; external_ai/prompts (solo referencia) |
| R5 LLM local | `relations/providers/local_llm.py` + test | external_ai (reutiliza openai_compatible, no reescribe) |
| R6 IA externa | `relations/providers/external.py` + test | external_ai/models/consensus (reutiliza) |
| R7 consenso | `relations/consensus_adapter.py` + test | **external_ai/consensus.py NO se reescribe: se adapta/reutiliza** |
| R8 pipeline | `relations/pipeline.py` + test | contratos congelados |
| B1 corpus | `data-engine/app/tests/data/relation_benchmark/**` (sintético) | producto |
| B2 runner | `data-engine/app/relations/benchmark/**` + docs/41,42 (NUEVOS) | docs/33-37 |
| P1 threat model | `docs/coordination/wave2b/threat-model.md` | producto |
| P2 observabilidad | `relations/observability.py` + test | — |
| P3/P4/P5/P6 | docs/* de diseño (solo spec) | producto/rutas/DB |
| P7 RK-05 | `viewer/app/config.py` + `viewer/tests/test_neo4j_default_fail_closed.py` + doc dev | relaciones; producción desplegada |
| P8 QA | `tests/wave2b/**` + matriz doc | producto (no corrige; reproduce) |

## Reutilización obligatoria (extender, no duplicar)

`external_ai/consensus.py` (R7) · `external_ai/openai_compatible.py` (R5) ·
`external_ai/nvidia_nim.py` (R6) · `external_ai/models.py` estados (todos) ·
`relations/contracts.py` `RelationCandidate` (todos, sin modificar).

## Conflictos previsibles

- Varios agentes añaden tests a `data-engine/app/tests/` → nombres de fichero únicos.
- R5/R6 crean `relations/providers/` → cada uno su fichero; `__init__.py` lo consolida el Organizador si colisiona.
