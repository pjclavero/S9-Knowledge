# Tablero de ejecución del programa

Base: `main@6d6c21f`. Estados: READY · BLOCKED · IN_PROGRESS · AUDIT ·
READY_FOR_PR · READY_FOR_MERGE · REJECTED · DONE.

## OLA 1 (iniciada en esta ejecución)

| ID | Equipo | Agente | Rama | Dependencias | Ficheros permitidos | Estado | Riesgo | Gate |
|----|--------|--------|------|--------------|---------------------|--------|--------|------|
| R-1 | R | R1/R2 | audit/pre-rc6-main-validation | — | tests de auditoría, informes | **DONE** (validación ejecutada, ver pre-rc6-audit.md) | P0 | CI verde ✔ |
| R-2 | R | R1 | audit/pre-rc6-main-validation | R-1 | — (solo lectura) | **DONE** (auditoría estática conforme) | P0 | sin base-provider indebido ✔ |
| R-3 | R | R3 | audit/pre-rc6-main-validation | R-1 | — (dry-run laboratorio) | **DONE** (source_narrative_01 PASSED) | P0 | 0 escrituras ✔ |
| R-4 | R | R4 | audit/pre-rc6-main-validation | R-1..3 | docs de release | **READY** (checklist en pre-rc6-audit.md) | P1 | docs consistency ✔ |
| R-5 | R | R5 | audit/pre-rc6-main-validation | R-1 | scripts validación no-prod | **READY** (rollback ya validado en Prioridad 1) | P1 | — |
| A-REL-1 | A | A1 | epic/relation-extraction-quality → feat/relation-internal-contracts | — | data-engine/app/relations/** (nuevo) | **READY** (contrato propuesto, contract-proposals.md §1) | P1 | Supervisor rev.1 |
| B-SEC-1 | B | B4 | feat/dependabot-supply-chain | — | .github/dependabot.yml (área compartida→PR Org) | **READY** (análisis en dependabot-analysis.md) | P1 | Supervisor rev.1 |
| B-EXP-1c | B | B2/B3 | feat/export-import-contract | — | data-engine/app/export_import/** (extiende review_export_import) | **READY** (contrato propuesto, contract-proposals.md §2) | P1 | Supervisor rev.1 |
| Q-1 | Q | Q1..Q6 | audit/qa-cross-cutting-matrix | — | matriz QA (doc) | **DONE** (qa-matrix.md) | P0 | — |

## OLA 2–4 (planificadas, NO iniciadas)

| ID | Equipo | Rama | Dependencias | Estado |
|----|--------|------|--------------|--------|
| A-REL-2 generador de pares | A | feat/relation-pair-generator | A-REL-1 | BLOCKED (dep A-REL-1) |
| A-REL-3 extractor sintáctico | A | feat/relation-syntactic | A-REL-1 | BLOCKED |
| A-REL-4 prompts RPG | A | feat/relation-rpg-prompts | A-REL-1 | BLOCKED |
| A-REL-5 ensemble sombra | A | feat/relation-ensemble-shadow | A-REL-2..4 | BLOCKED |
| A-REL-6 benchmark relaciones (docs/41,42) | A | feat/relation-benchmark | A-REL-5 | BLOCKED |
| B-EXP-2 export v1 | B | feat/export-v1 | B-EXP-1c | BLOCKED |
| B-IMG-1 contrato multimedia | B | feat/multimedia-contract | — | READY (contract-proposals.md §3) |
| B-IMG-2 OCR base | B | feat/ocr-base | B-IMG-1 | BLOCKED |
| B-IMP-1 import dry-run | B | feat/import-dry-run | B-EXP-1c | BLOCKED |
| B-IMG-3 comprensión visual | B | feat/visual-understanding | B-IMG-2 | BLOCKED |
| B-OBS-1 observabilidad | B | feat/observability | — | READY |
| B-UX-1 prototipos UX | B | feat/ux-prototypes | contratos backend | BLOCKED |

## Reglas de estado

- Ninguna tarea pasa a READY_FOR_MERGE sin **Supervisor rev.2 CONFORME** + CI verde
  del head exacto + diff aislado.
- Cambios en áreas compartidas → PR de integración del Organizador (no del equipo).
- El carril R **no espera** a A ni a B. RC6 no incorpora A ni B.
